// Early-Apex PHY (S0-S3): the 20-byte header (size, id, solid count, model checksum,
// keyvalue offset), a solid table, per-solid hull records and hull geometry, then the
// keyvalue text. Offsets in the solid data are 64-bit and relative to the end of the
// header. Layout measured over every installed S0-S3 file; see docs/mdl-v54-format.md.
#include <cstring>

#include "core/buffer.h"
#include "core/log.h"
#include "write/writers.h"

namespace r2c {

std::vector<uint8_t> WritePHY54(const CPhysics& p, bool edgeFaces, int checksum) {
    constexpr size_t kHeader = 20, kTable = 0x20, kSolid = 0x90, kHull = 0x40, kFace = 32;
    const size_t edgeSize = edgeFaces ? 4 : 2;
    if (p.apexSolids.empty()) Fatal("internal: no physics solids to write");
    if (p.apexSolids.size() > 0x7FFF) Fatal("too many physics solids");
    // offsets relative to the solid table
    size_t at = kTable + kSolid * p.apexSolids.size();
    std::vector<size_t> hullAt;
    std::vector<std::array<size_t, 3>> dataAt;
    for (auto& s : p.apexSolids) {
        hullAt.push_back(at);
        at += kHull * s.hulls.size();
        for (auto& h : s.hulls) {
            std::array<size_t, 3> d;
            d[0] = at; at += 12 * h.verts.size();
            d[1] = at; at += kFace * h.faces.size();
            d[2] = at; at += edgeSize * h.edges.size();
            dataAt.push_back(d);
        }
    }
    const size_t total = at;
    Buffer b;
    b.I32(static_cast<int>(kHeader));
    b.I32(1);
    b.I16(static_cast<int16_t>(p.apexSolids.size()));
    b.I16(0);
    b.I32(checksum);
    b.I32(static_cast<int>(kHeader + total));
    auto i64 = [&](size_t v) { b.I32(static_cast<int>(v)); b.I32(0); };
    auto v4 = [&](const Vec3& v, float w) { b.F32(v.x); b.F32(v.y); b.F32(v.z); b.F32(w); };
    i64(kTable);
    i64(p.apexSolids.size());
    i64(0);
    i64(total);
    for (size_t i = 0; i < p.apexSolids.size(); i++) {
        auto& s = p.apexSolids[i];
        i64(hullAt[i]);
        i64(s.hulls.size());
        v4(Vec3(1, 0, 0), 0);  // first float is 1.0 in every surveyed solid; the rest are zero
        v4(s.centre, 0);
        for (int r = 0; r < 3; r++) v4(Vec3(s.inertia[r][0], s.inertia[r][1], s.inertia[r][2]), 0);
        v4(s.centre, 0);
        b.V3(s.mins);
        b.V3(s.maxs);
        b.I32(0);
        b.I32(0);
    }
    size_t hullIndex = 0;
    for (auto& s : p.apexSolids) {
        size_t first = hullIndex;
        for (auto& h : s.hulls) {
            auto& d = dataAt[hullIndex++];
            v4(h.centroid, h.innerRadius);
            i64(d[0]); i64(h.verts.size());
            i64(d[1]); i64(h.faces.size());
            i64(d[2]); i64(h.edges.size());
        }
        for (size_t k = 0; k < s.hulls.size(); k++) {
            auto& h = s.hulls[k];
            if (b.Size() != kHeader + dataAt[first + k][0]) Fatal("internal: PHY layout mismatch");
            for (auto& v : h.verts) b.V3(v);
            for (auto& f : h.faces) {
                uint8_t face[kFace];
                std::memset(face, 0xFF, sizeof(face));
                for (size_t j = 0; j < f.size(); j++) face[j] = static_cast<uint8_t>(f[j]);
                b.Bytes(face, sizeof(face));
            }
            for (auto& e : h.edges) {
                b.U8(static_cast<uint8_t>(e[0]));
                b.U8(static_cast<uint8_t>(e[1]));
                if (edgeFaces) {
                    b.U8(static_cast<uint8_t>(e[2]));
                    b.U8(static_cast<uint8_t>(e[3]));
                }
            }
        }
    }
    if (b.Size() != kHeader + total) Fatal("internal: PHY size mismatch");
    b.Bytes(p.text.data(), p.text.size());
    b.U8(0);
    return b.Data();
}

}  // namespace r2c
