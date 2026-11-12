// Early-Apex BVH collision block (studiohdr 0x214), measured on the installed S3 corpus;
// see docs/mdl-v54-format.md. One entry per collision mesh: the static trace mesh
// (LOD 0 render triangles), the rigid physics hull, or one per jointed solid. Leaves are
// triangle lists (type 5 with packed int16 vertices, type 4 with float vertices).
#include <algorithm>
#include <array>
#include <cstdint>
#include <cfloat>
#include <cmath>
#include <cstring>
#include <functional>
#include <map>

#include "core/buffer.h"
#include "core/log.h"
#include "write/writers.h"

namespace r2c {

namespace {

constexpr int kLeafTris = 16;         // four-bit triangle count
constexpr int kFinestStep = -14;      // log2 of the finest packed step retail uses
constexpr int kCoarsestPacked = -7;   // beyond this packed vertices lose too much: use floats
constexpr int kTypeNode = 0, kTypeEmpty = 1, kTypeList = 3, kTypeFloatTris = 4, kTypePackedTris = 5, kTypePackedQuads = 7;

struct Entry {
    std::vector<Vec3> verts;
    std::vector<std::array<int, 3>> tris;  // counter-clockwise seen from outside
};

struct Built {
    bool packed = true;
    Vec3 origin;
    int stepLog2 = 0;  // node/vertex unit = 2^stepLog2 inches; scale = 2^(stepLog2-16)
    std::vector<uint8_t> verts, leaves, nodes;
    Vec3 mins, maxs;
};

int16_t Quant(double v, double step, bool up) {
    double q = up ? std::ceil(v / step) : std::floor(v / step);
    return static_cast<int16_t>(std::clamp(q, -32768.0, 32767.0));
}

Built BuildEntry(const Entry& e, const char* what) {
    Built out;
    if (e.tris.empty()) Fatal("BVH %s has no triangles", what);
    out.mins = Vec3(FLT_MAX, FLT_MAX, FLT_MAX);
    out.maxs = Vec3(-FLT_MAX, -FLT_MAX, -FLT_MAX);
    for (auto& t : e.tris)
        for (int c = 0; c < 3; c++) {
            out.mins = Min(out.mins, e.verts[t[c]]);
            out.maxs = Max(out.maxs, e.verts[t[c]]);
        }
    double extent = 0;
    for (int a = 0; a < 3; a++) {
        out.origin[a] = std::round((out.mins[a] + out.maxs[a]) * 0.5f);
        extent = std::max({extent, double(std::fabs(out.maxs[a] - out.origin[a])), double(std::fabs(out.mins[a] - out.origin[a]))});
    }
    // smallest power-of-two unit that keeps every coordinate within int16
    int stepLog2 = kFinestStep;
    while (std::ldexp(32767.0, stepLog2) < extent + std::ldexp(1.0, stepLog2)) stepLog2++;
    out.packed = stepLog2 <= kCoarsestPacked;
    out.stepLog2 = stepLog2;
    const double step = std::ldexp(1.0, stepLog2);

    // drop degenerate triangles: a repeated corner cannot be encoded, and retail also
    // drops triangles whose corners share a position (wood_gib01c's render mesh has two)
    std::vector<std::array<int, 3>> tris;
    // (compared on the stored grid: the source corners may differ below one step)
    auto same = [&](int a, int b) {
        if (a == b) return true;
        for (int k = 0; k < 3; k++) {
            double p = e.verts[a][k] - out.origin[k], q = e.verts[b][k] - out.origin[k];
            if (out.packed ? std::round(p / step) != std::round(q / step) : p != q) return false;
        }
        return true;
    };
    for (auto& t : e.tris)
        if (!same(t[0], t[1]) && !same(t[1], t[2]) && !same(t[0], t[2])) tris.push_back(t);
    if (tris.empty()) Fatal("BVH %s has only degenerate triangles", what);

    struct Node { std::array<int, 4> type{}; std::array<int, 4> index{}; std::array<std::array<int16_t, 6>, 4> box{}; };
    std::vector<Node> nodes;
    Buffer leafWords, vertBytes;
    int vertexCount = 0;

    auto boxOf = [&](const std::vector<int>& ids) {
        Vec3 mn(FLT_MAX, FLT_MAX, FLT_MAX), mx(-FLT_MAX, -FLT_MAX, -FLT_MAX);
        for (int i : ids)
            for (int c = 0; c < 3; c++) {
                mn = Min(mn, e.verts[tris[i][c]]);
                mx = Max(mx, e.verts[tris[i][c]]);
            }
        std::array<int16_t, 6> q{};
        for (int a = 0; a < 3; a++) {
            q[a * 2] = Quant(mn[a] - out.origin[a], step, false);
            q[a * 2 + 1] = Quant(mx[a] - out.origin[a], step, true);
        }
        return q;
    };
    // a leaf: its own run of vertices; triangles start at their lowest local vertex,
    // sorted, so each base only grows (retail winding is clockwise from outside)
    // A leaf, as retail writes them: vertices stored once per position, triangle pairs
    // that form an exact parallelogram on the packed grid as quads (type 7, whose fourth
    // corner b + c - a is computed and not stored unless something else uses it), the
    // rest as triangles (type 5); a leaf with both is a type 3 list of the two. Float
    // entries keep triangles (type 4): b + c - a is not exact in floats.
    using Key = std::array<int64_t, 3>;
    auto keyOf = [&](int v) {
        Key k{};
        for (int a = 0; a < 3; a++) {
            if (out.packed) {
                k[a] = std::llround((e.verts[v][a] - out.origin[a]) / step);
            } else {
                float f = e.verts[v][a];
                int32_t bits;
                std::memcpy(&bits, &f, 4);
                k[a] = bits;
            }
        }
        return k;
    };
    auto emitLeaf = [&](const std::vector<int>& ids) -> std::pair<int, int> {
        std::map<Key, int> unique;
        std::vector<int> rep;  // a source vertex per unique position
        std::vector<Key> pos;
        auto U = [&](int v) {
            Key k = keyOf(v);
            auto it = unique.find(k);
            if (it != unique.end()) return it->second;
            unique.emplace(k, static_cast<int>(rep.size()));
            rep.push_back(v);
            pos.push_back(k);
            return static_cast<int>(rep.size()) - 1;
        };
        std::vector<std::array<int, 3>> et;  // winding reversed (retail hulls wind the other way)
        for (int i : ids) et.push_back({U(tris[i][0]), U(tris[i][2]), U(tris[i][1])});

        // pair triangles sharing an edge (a->b in one, b->a in the other) whose far corners
        // p, q make a parallelogram: p + q == a + b exactly; outline p, a, q, b
        std::vector<bool> paired(et.size(), false);
        std::vector<std::array<int, 4>> outlines;
        for (size_t x = 0; out.packed && x < et.size(); x++) {
            if (paired[x]) continue;
            for (size_t y = x + 1; y < et.size() && !paired[x]; y++) {
                if (paired[y]) continue;
                for (int i = 0; i < 3 && !paired[x]; i++) {
                    int a = et[x][i], b = et[x][(i + 1) % 3], p = et[x][(i + 2) % 3];
                    for (int j = 0; j < 3; j++) {
                        if (et[y][j] != b || et[y][(j + 1) % 3] != a) continue;
                        int q = et[y][(j + 2) % 3];
                        bool para = q != p;
                        for (int k = 0; k < 3 && para; k++) para = pos[p][k] + pos[q][k] == pos[a][k] + pos[b][k];
                        if (!para) continue;
                        outlines.push_back({p, a, q, b});
                        paired[x] = paired[y] = true;
                        break;
                    }
                }
            }
        }

        // local vertex numbers: triangle corners first, then each quad's base and its two
        // neighbours (the base is its lowest-numbered corner, so b and c follow it)
        std::vector<int> local(rep.size(), -1), order;
        auto assign = [&](int u) {
            if (local[u] < 0) {
                local[u] = static_cast<int>(order.size());
                order.push_back(u);
            }
            return local[u];
        };
        std::vector<std::array<int, 3>> lt, lq;
        for (size_t x = 0; x < et.size(); x++) {
            if (paired[x]) continue;
            std::array<int, 3> t = {assign(et[x][0]), assign(et[x][1]), assign(et[x][2])};
            std::rotate(t.begin(), std::min_element(t.begin(), t.end()), t.end());
            lt.push_back(t);
        }
        for (auto& o : outlines) {
            int k = 0;
            for (int m = 1; m < 4; m++) {
                int lm = local[o[m]] < 0 ? INT32_MAX : local[o[m]], lk = local[o[k]] < 0 ? INT32_MAX : local[o[k]];
                if (lm < lk) k = m;
            }
            int a = assign(o[k]), b = assign(o[(k + 1) % 4]), c = assign(o[(k + 3) % 4]);  // o[k+2] is computed
            lq.push_back({a, b, c});
        }
        std::sort(lt.begin(), lt.end());
        std::sort(lq.begin(), lq.end());
        if (vertexCount + static_cast<int>(order.size()) > 0xFFFF) Fatal("BVH %s needs more than 65535 vertices", what);

        // a sub-leaf: header (1024-vertex page, count - 1), then one word per item on a
        // running base; quads: A 10 bits, B 9, C 9, flags 0xF; triangles: A 11, B 9, C 9, 7
        auto subLeaf = [&](Buffer& w, const std::vector<std::array<int, 3>>& items, bool quad) {
            int first = vertexCount + items[0][0];
            w.U32(static_cast<uint32_t>(first / 1024) << 16 | static_cast<uint32_t>(items.size() - 1) << 12);
            int base = first / 1024 * 1024 - vertexCount;
            for (auto& t : items) {
                int a = t[0] - base, b = t[1] - t[0] - 1, c = t[2] - t[0] - 1;
                if (a < 0 || a > (quad ? 0x3FF : 0x7FF) || b < 0 || b > 0x1FF || c < 0 || c > 0x1FF)
                    Fatal("internal: BVH %s leaf offsets out of range", what);
                base = t[0];
                w.U32(quad ? static_cast<uint32_t>(a) | static_cast<uint32_t>(b) << 10 | static_cast<uint32_t>(c) << 19 | 0xFu << 28
                           : static_cast<uint32_t>(a) | static_cast<uint32_t>(b) << 11 | static_cast<uint32_t>(c) << 20 | 7u << 29);
            }
        };
        int word = static_cast<int>(leafWords.Size() / 4);
        int triType = out.packed ? kTypePackedTris : kTypeFloatTris;
        int type;
        if (lq.empty() || lt.empty()) {
            subLeaf(leafWords, lq.empty() ? lt : lq, !lq.empty());
            type = lq.empty() ? triType : kTypePackedQuads;
        } else {
            Buffer quads, triangles;
            subLeaf(quads, lq, true);
            subLeaf(triangles, lt, false);
            leafWords.U32(2);
            leafWords.U32(static_cast<uint32_t>(kTypePackedQuads) << 8 | static_cast<uint32_t>(quads.Size() / 4) << 16);
            leafWords.U32(static_cast<uint32_t>(triType) << 8 | static_cast<uint32_t>(triangles.Size() / 4) << 16);
            leafWords.Bytes(quads.Data().data(), quads.Size());
            leafWords.Bytes(triangles.Data().data(), triangles.Size());
            type = kTypeList;
        }
        for (int u : order) {
            const Vec3& p = e.verts[rep[u]];
            for (int a = 0; a < 3; a++) {
                if (out.packed) vertBytes.I16(static_cast<int16_t>(std::clamp(static_cast<double>(pos[u][a]), -32768.0, 32767.0)));
                else vertBytes.F32(p[a]);
            }
        }
        vertexCount += static_cast<int>(order.size());
        return std::make_pair(word, type);
    };
    auto split = [&](std::vector<int> ids) {
        Vec3 mn(FLT_MAX, FLT_MAX, FLT_MAX), mx(-FLT_MAX, -FLT_MAX, -FLT_MAX);
        auto centre = [&](int i) { return (e.verts[tris[i][0]] + e.verts[tris[i][1]] + e.verts[tris[i][2]]) * (1.0f / 3); };
        for (int i : ids) { mn = Min(mn, centre(i)); mx = Max(mx, centre(i)); }
        int axis = 0;
        for (int a = 1; a < 3; a++) if (mx[a] - mn[a] > mx[axis] - mn[axis]) axis = a;
        std::sort(ids.begin(), ids.end(), [&](int x, int y) { return centre(x)[axis] < centre(y)[axis]; });
        size_t half = ids.size() / 2;
        return std::make_pair(std::vector<int>(ids.begin(), ids.begin() + half), std::vector<int>(ids.begin() + half, ids.end()));
    };
    std::function<int(const std::vector<int>&)> build = [&](const std::vector<int>& ids) {
        int self = static_cast<int>(nodes.size());
        nodes.emplace_back();
        std::vector<std::vector<int>> groups;
        if (static_cast<int>(ids.size()) <= kLeafTris) groups = {ids};
        else {
            auto [l, r] = split(ids);
            for (auto* part : {&l, &r}) {
                if (static_cast<int>(part->size()) <= kLeafTris) groups.push_back(*part);
                else { auto [a, b] = split(*part); groups.push_back(a); groups.push_back(b); }
            }
        }
        for (int c = 0; c < 4; c++) {
            if (c >= static_cast<int>(groups.size())) {
                nodes[self].type[c] = kTypeEmpty;
                nodes[self].box[c] = {32767, -32768, 32767, -32768, 32767, -32768};  // inverted: never hit
                continue;
            }
            nodes[self].box[c] = boxOf(groups[c]);
            if (static_cast<int>(groups[c].size()) <= kLeafTris) {
                auto [word, type] = emitLeaf(groups[c]);
                nodes[self].type[c] = type;
                nodes[self].index[c] = word;
            } else {
                int child = build(groups[c]);
                nodes[self].type[c] = kTypeNode;
                nodes[self].index[c] = child;
            }
        }
        return self;
    };
    std::vector<int> all(tris.size());
    for (size_t i = 0; i < tris.size(); i++) all[i] = static_cast<int>(i);
    build(all);
    for (auto& n : nodes)
        for (int x : n.index)
            if (x > 0xFFFFFF) Fatal("BVH %s index exceeds 24 bits", what);

    Buffer nb;
    for (auto& n : nodes) {
        for (int a = 0; a < 3; a++) {
            for (int c = 0; c < 4; c++) nb.I16(n.box[c][a * 2]);
            for (int c = 0; c < 4; c++) nb.I16(n.box[c][a * 2 + 1]);
        }
        nb.U32(static_cast<uint32_t>(n.index[0]) << 8);
        nb.U32(static_cast<uint32_t>(n.index[1]) << 8);
        nb.U32(static_cast<uint32_t>(n.index[2]) << 8 | static_cast<uint32_t>(n.type[0]) | static_cast<uint32_t>(n.type[1]) << 4);
        nb.U32(static_cast<uint32_t>(n.index[3]) << 8 | static_cast<uint32_t>(n.type[2]) | static_cast<uint32_t>(n.type[3]) << 4);
    }
    out.nodes = nb.Data();
    out.leaves = leafWords.Data();
    out.verts = vertBytes.Data();
    while (out.verts.size() % 4) out.verts.push_back(0);
    return out;
}

}  // namespace

CBvh BuildBvh54(const CompiledModel& m) {
    CBvh bvh;
    std::vector<Entry> entries;
    std::vector<std::string> names;
    // static trace mesh: LOD 0 triangles of each body part's default model
    if (m.bvhTrace) {
        Entry e;
        for (auto& bp : m.bodyParts) {
            if (bp.models.empty()) continue;
            for (auto& me : bp.models[0].meshes) {
                if (me.lods.empty()) continue;
                int base = static_cast<int>(e.verts.size());
                for (auto& v : me.verts) e.verts.push_back(v.pos);
                auto& idx = me.lods[0].indices;
                for (size_t t = 0; t + 2 < idx.size(); t += 3)
                    e.tris.push_back({base + static_cast<int>(idx[t]), base + static_cast<int>(idx[t + 1]), base + static_cast<int>(idx[t + 2])});
            }
        }
        if (!e.tris.empty()) {
            bvh.traceEntry = static_cast<int>(entries.size());
            entries.push_back(std::move(e));
            names.push_back("trace mesh");
        }
    }
    // physics solids: their hull faces as triangles (faces are counter-clockwise outside)
    auto solidEntry = [&](const std::vector<const CApexSolid*>& solids) {
        Entry e;
        for (auto* s : solids)
            for (auto& h : s->hulls) {
                int base = static_cast<int>(e.verts.size());
                for (auto& v : h.verts) e.verts.push_back(v);
                for (auto& f : h.faces)
                    for (size_t k = 1; k + 1 < f.size(); k++) e.tris.push_back({base + f[0], base + f[k], base + f[k + 1]});
            }
        return e;
    };
    const auto& solids = m.physics.apexSolids;
    if (!solids.empty()) {
        if (m.physics.jointed) {
            // retail orders jointed entries by bone index, not by PHY solid
            std::vector<const CApexSolid*> byBone;
            for (auto& s : solids) byBone.push_back(&s);
            std::stable_sort(byBone.begin(), byBone.end(), [](const CApexSolid* x, const CApexSolid* y) { return x->bone < y->bone; });
            for (auto* sp : byBone) {
                auto& s = *sp;
                entries.push_back(solidEntry({&s}));
                names.push_back("physics solid");
            }
            bvh.traceEntry = -1;  // jointed models carry only their solids
            if (m.bvhTrace) entries.erase(entries.begin()), names.erase(names.begin());
        } else {
            bvh.hullEntry = static_cast<int>(entries.size());
            entries.push_back(solidEntry({&solids[0]}));
            names.push_back("physics hull");
        }
    }
    if (entries.empty()) return bvh;

    std::vector<Built> built;
    for (size_t i = 0; i < entries.size(); i++) built.push_back(BuildEntry(entries[i], names[i].c_str()));
    const int n = static_cast<int>(built.size());
    // header, entries, a two-word table, the contents list (CONTENTS_SOLID), 8-byte alignment
    const int table = 0x10 + 0x20 * n, contents = table + 8, contentsEnd = contents + 4;
    size_t at = (contentsEnd + 7) & ~size_t(7);
    std::vector<std::array<size_t, 3>> offs(n);
    for (int i = 0; i < n; i++) {
        offs[i][1] = at; at += built[i].verts.size();
        offs[i][2] = at; at += built[i].leaves.size();
    }
    at = (at + 63) & ~size_t(63);
    for (int i = 0; i < n; i++) { offs[i][0] = at; at += built[i].nodes.size(); }
    Buffer b;
    b.I32(contents);
    b.I32(table);
    b.I32(contentsEnd);
    b.I32(n);
    bvh.mins = Vec3(FLT_MAX, FLT_MAX, FLT_MAX);
    bvh.maxs = Vec3(-FLT_MAX, -FLT_MAX, -FLT_MAX);
    for (int i = 0; i < n; i++) {
        auto& e = built[i];
        b.I32(e.packed ? 1 : 0);
        b.I32(static_cast<int>(offs[i][0]));
        b.I32(static_cast<int>(offs[i][1]));
        b.I32(static_cast<int>(offs[i][2]));
        b.V3(e.origin);
        b.F32(static_cast<float>(std::ldexp(1.0, e.stepLog2 - 16)));
        if (i == bvh.traceEntry || bvh.traceEntry < 0) {
            bvh.mins = Min(bvh.mins, e.mins);
            bvh.maxs = Max(bvh.maxs, e.maxs);
        }
    }
    b.I32(0); b.I32(0);  // table
    b.I32(1);            // contents: solid
    while (b.Size() < offs[0][1]) b.U8(0);
    for (int i = 0; i < n; i++) {
        b.Bytes(built[i].verts.data(), built[i].verts.size());
        b.Bytes(built[i].leaves.data(), built[i].leaves.size());
    }
    while (b.Size() % 64) b.U8(0);
    for (int i = 0; i < n; i++) {
        if (b.Size() != offs[i][0]) Fatal("internal: BVH layout mismatch");
        b.Bytes(built[i].nodes.data(), built[i].nodes.size());
    }
    bvh.block = b.Data();
    return bvh;
}

}  // namespace r2c
