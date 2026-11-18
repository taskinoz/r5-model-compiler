// Build orchestration plus the smaller stages: attachments, IK, hitboxes, bounds,
// sequences, skins and the final bone table.
#include <algorithm>
#include <cctype>
#include <cmath>
#include <functional>
#include <limits>

#include "build/context.h"
#include "core/buffer.h"
#include "core/log.h"
#include "core/strings.h"

namespace r2c {

// The hash the client looks RUI panel meshes up by (a weapon script's "mesh" name):
// MurmurHash3 x86_32 over the name with every byte ANDed with 0xDF (case folding),
// seed 0, with the terminating nul counted in the length. Reproduces all 163 retail
// mp_common panel hashes.
// Early-Apex model keyvalues, as Respawn's tool writes them in all 1,789 surveyed S0-S3
// models: compact text, `mdlkeyvalue{prop_data{base "<base>"}}` plus a newline, and always
// a prop_data block with a base (empty when the QC gives none; R5R deletes a prop_physics
// without prop_data). The QC block arrives in studiomdl's layout (CmdKeyValues); other keys
// keep the same compact style, siblings separated by a space (retail has no example).
static std::string ApexKeyValues(const std::string& studiomdl) {
    struct Node { std::string key, value; bool block = false; std::vector<Node> children; };
    std::vector<std::string> tokens;
    for (size_t i = 0; i < studiomdl.size();) {
        char c = studiomdl[i];
        if (std::isspace(static_cast<unsigned char>(c))) { i++; continue; }
        if (c == '{' || c == '}') { tokens.emplace_back(1, c); i++; continue; }
        if (c == '"') {
            size_t j = studiomdl.find('"', i + 1);
            if (j == std::string::npos) Fatal("unterminated keyvalue string");
            tokens.push_back("\x01" + studiomdl.substr(i + 1, j - i - 1));  // quoted marker
            i = j + 1;
            continue;
        }
        size_t j = i;
        while (j < studiomdl.size() && !std::isspace(static_cast<unsigned char>(studiomdl[j])) && studiomdl[j] != '{' &&
               studiomdl[j] != '}' && studiomdl[j] != '"')
            j++;
        tokens.push_back(studiomdl.substr(i, j - i));
        i = j;
    }
    auto text = [](const std::string& t) { return !t.empty() && t[0] == '\x01' ? t.substr(1) : t; };
    size_t at = 0;
    std::function<std::vector<Node>()> items = [&]() {
        std::vector<Node> out;
        while (at < tokens.size() && tokens[at] != "}") {
            Node n;
            n.key = text(tokens[at++]);
            if (at < tokens.size() && tokens[at] == "{") {
                at++;
                n.block = true;
                n.children = items();
                if (at >= tokens.size()) Fatal("keyvalue block missing a closing brace");
                at++;
            } else {
                if (at >= tokens.size()) Fatal("keyvalue %s has no value", n.key.c_str());
                n.value = text(tokens[at++]);
            }
            out.push_back(std::move(n));
        }
        return out;
    };
    std::vector<Node> top;
    if (!studiomdl.empty()) {
        // the text is "mdlkeyvalue { ... }"
        if (tokens.size() < 2 || tokens[0] != "mdlkeyvalue" || tokens[1] != "{") Fatal("unexpected keyvalue text");
        at = 2;
        top = items();
    }
    auto prop = std::find_if(top.begin(), top.end(), [](const Node& n) { return n.block && IEquals(n.key, "prop_data"); });
    if (prop == top.end()) {
        Node p;
        p.key = "prop_data";
        p.block = true;
        top.insert(top.begin(), p);
        prop = top.begin();
    }
    if (std::none_of(prop->children.begin(), prop->children.end(), [](const Node& n) { return !n.block && IEquals(n.key, "base"); })) {
        Node b;
        b.key = "base";
        prop->children.insert(prop->children.begin(), b);
    }
    std::function<std::string(const std::vector<Node>&)> write = [&](const std::vector<Node>& nodes) {
        std::string s;
        for (size_t i = 0; i < nodes.size(); i++) {
            if (i) s += ' ';
            s += nodes[i].key;
            s += nodes[i].block ? "{" + write(nodes[i].children) + "}" : " \"" + nodes[i].value + "\"";
        }
        return s;
    };
    return "mdlkeyvalue{" + write(top) + "}\n";
}

static uint32_t UIPanelHash(const std::string& name) {
    auto rol = [](uint32_t x, int r) { return (x << r) | (x >> (32 - r)); };
    auto mix = [&](uint32_t k) { return rol(k * 0xcc9e2d51u, 15) * 0x1b873593u; };
    uint32_t h = 0, len = 0;
    size_t i = 0;
    for (; i + 4 <= name.size(); i += 4, len += 4) {
        uint32_t w = 0;
        for (int b = 0; b < 4; b++) w |= static_cast<uint32_t>(static_cast<uint8_t>(name[i + b])) << (8 * b);
        h = rol(h ^ mix(w & 0xdfdfdfdfu), 13) * 5 + 0xe6546b64u;
    }
    uint32_t t = 0;
    for (size_t b = 0; i + b < name.size(); b++) t |= static_cast<uint32_t>(static_cast<uint8_t>(name[i + b]) & 0xdf) << (8 * b);
    len += static_cast<uint32_t>(name.size() - i) + 1;  // the length includes the nul
    h ^= mix(t) ^ len;
    h ^= h >> 16; h *= 0x85ebca6bu; h ^= h >> 13; h *= 0xc2b2ae35u;
    return h ^ (h >> 16);
}

// A v54 RUI face's mask: bit (4 * row + column) for each cell of a 4x4 grid over the
// panel's [0,1] x [0,1] coordinates whose interior the convex hull of the face's four
// bounds points overlaps (touching an edge does not count). Separating-axis test on the
// grid axes and the hull's edge normals, in double. Reproduces all 33,173 S0-S3 faces.
static uint16_t UIPanelFaceMask(const std::array<float, 8>& bounds) {
    using P = std::pair<double, double>;
    std::vector<P> pts;
    for (int i = 0; i < 4; i++) pts.push_back({bounds[i], bounds[4 + i]});
    std::sort(pts.begin(), pts.end());
    pts.erase(std::unique(pts.begin(), pts.end()), pts.end());
    std::vector<P> hull = pts;
    if (pts.size() > 2) {  // Andrew's monotone chain, collinear points dropped
        auto cross = [](const P& o, const P& a, const P& b) {
            return (a.first - o.first) * (b.second - o.second) - (a.second - o.second) * (b.first - o.first);
        };
        std::vector<P> lower, upper;
        for (const P& p : pts) {
            while (lower.size() >= 2 && cross(lower[lower.size() - 2], lower.back(), p) <= 0) lower.pop_back();
            lower.push_back(p);
        }
        for (auto it = pts.rbegin(); it != pts.rend(); ++it) {
            while (upper.size() >= 2 && cross(upper[upper.size() - 2], upper.back(), *it) <= 0) upper.pop_back();
            upper.push_back(*it);
        }
        hull.assign(lower.begin(), lower.end() - 1);
        hull.insert(hull.end(), upper.begin(), upper.end() - 1);
    }
    std::vector<P> axes = {{1, 0}, {0, 1}};
    for (size_t i = 0; i < hull.size(); i++) {
        const P& a = hull[i];
        const P& b = hull[(i + 1) % hull.size()];
        axes.push_back({-(b.second - a.second), b.first - a.first});
    }
    uint16_t mask = 0;
    for (int row = 0; row < 4; row++)
        for (int col = 0; col < 4; col++) {
            const P box[4] = {{col / 4.0, row / 4.0}, {(col + 1) / 4.0, row / 4.0},
                              {col / 4.0, (row + 1) / 4.0}, {(col + 1) / 4.0, (row + 1) / 4.0}};
            bool overlap = true;
            for (const P& ax : axes) {
                if (ax.first == 0 && ax.second == 0) continue;
                double pmin = 1e300, pmax = -1e300, cmin = 1e300, cmax = -1e300;
                for (const P& q : hull) {
                    double d = ax.first * q.first + ax.second * q.second;
                    pmin = std::min(pmin, d); pmax = std::max(pmax, d);
                }
                for (const P& q : box) {
                    double d = ax.first * q.first + ax.second * q.second;
                    cmin = std::min(cmin, d); cmax = std::max(cmax, d);
                }
                if (pmax <= cmin || cmax <= pmin) { overlap = false; break; }
            }
            if (overlap) mask |= static_cast<uint16_t>(1u << (4 * row + col));
        }
    return mask;
}

void EncodeAnimations(BuildContext& ctx);
void ProcessIKRules(BuildContext& ctx);
void BuildCollisionModel(BuildContext& ctx);
void BuildPerTriAABB(BuildContext& ctx);

void BuildContext::BuildAttachments() {
    for (auto& qa : qc.attachments) {
        CAttachment a;
        a.name = qa.name;
        a.flags = qa.flags;
        int k = FindBone(qa.bone);
        Mat3x4 boneToPose, poseToBone;
        if (k >= 0) {
            boneToPose = bones[k].boneToPose;
            poseToBone = Invert(boneToPose);
        } else {
            // the bone was optimised out: walk up its source hierarchy to a kept bone
            bool found = false;
            for (auto& ip : insts) {
                SrcInst& s = *ip;
                int j = s.src->FindBone(qa.bone);
                if (j < 0) continue;
                std::vector<Mat3x4> b2w;
                BuildRawTransforms(s, 0, 1, Vec3(), RadianEuler(), b2w);
                boneToPose = b2w[j];
                int m = j;
                while (m != -1 && s.globalToLocal[s.localToGlobal[m]] != m) m = s.bones[m].parent;
                if (m == -1) Fatal("unable to find valid bone for attachment %s:%s", qa.name.c_str(), qa.bone.c_str());
                poseToBone = Invert(b2w[m]);
                k = s.localToGlobal[m];
                found = true;
                break;
            }
            if (!found) Fatal("unknown attachment link '%s'", qa.bone.c_str());
        }
        a.bone = k;
        Mat3x4 world = qa.absolute ? qa.local : Concat(boneToPose, qa.local);
        a.local = qa.exactMatrix ? qa.local : Concat(poseToBone, world);
        for (int j = k; j != -1; j = bones[j].parent) bones[j].flags |= BONE_USED_BY_ATTACHMENT;
        out.attachments.push_back(a);
    }
}

void BuildContext::BuildIK() {
    for (auto& c : qc.ikChains) {
        if (!std::isfinite(c.unk) || !std::isfinite(c.knee.x) || !std::isfinite(c.knee.y) || !std::isfinite(c.knee.z))
            Fatal("ikchain '%s': non-finite chain value or knee direction", c.name.c_str());
        CIKChain ch;
        ch.name = c.name;
        ch.linkType = 0;
        ch.unk = c.unk;
        int k = FindBone(c.bone);
        if (k == -1) Fatal("unknown bone '%s' in ikchain '%s'", c.bone.c_str(), c.name.c_str());
        int k1 = -1, k0 = -1;
        if (c.links.size() == 3) {
            k0 = FindBone(c.links[0]);
            k1 = FindBone(c.links[1]);
            k = FindBone(c.links[2]);
            if (k0 < 0 || k1 < 0 || k < 0) Fatal("ikchain '%s': unknown link bone", c.name.c_str());
        } else {
            k1 = bones[k].parent;
            if (k1 == -1) Fatal("ikchain '%s' too close to root, no parent knee/elbow", c.name.c_str());
            k0 = bones[k1].parent;
            if (k0 == -1) Fatal("ikchain '%s' too close to root, no parent hip/shoulder", c.name.c_str());
        }
        ch.links.resize(3);
        ch.links[0].bone = k0;
        ch.links[1].bone = k1;
        ch.links[2].bone = k;
        ch.links[0].kneeDir = c.knee;
        for (int b : {k0, k1, k}) bones[b].flags |= BONE_USED_BY_ATTACHMENT;
        out.ikChains.push_back(ch);
    }
    // bones an IK chain moves: its links and everything below them (retail, all models)
    std::vector<bool> influenced(bones.size(), false);
    for (auto& ch : out.ikChains)
        for (auto& l : ch.links) influenced[l.bone] = true;
    for (size_t b = 0; b < bones.size(); b++) {
        if (bones[b].parent >= 0 && influenced[bones[b].parent]) influenced[b] = true;
        if (influenced[b]) bones[b].flags |= BONE_IKCHAIN_INFLUENCE;
    }
    for (auto& l : qc.ikAutoplayLocks) {
        int c = qc.FindIKChain(l.chain);
        if (c < 0) Fatal("unknown chain '%s' in ikautoplaylock", l.chain.c_str());
        CIKLock lk;
        lk.chain = c;
        lk.posWeight = l.posWeight;
        lk.localQWeight = l.localQWeight;
        out.ikAutoplayLocks.push_back(lk);
    }
}

void BuildContext::BuildHitboxes() {
    // hit groups inherit from the parent bone (no $hgroup support beyond default 0)
    for (auto& b : bones) b.group = 0;
    // per-bone vertex bounds (also used for sequence boxes)
    for (auto& b : bones) {
        b.bmin = Vec3(9999, 9999, 9999);
        b.bmax = Vec3(-9999, -9999, -9999);
    }
    for (auto* s : bodyInsts) {
        if (!s) continue;
        for (auto& v : s->gverts)
            for (auto& w : v.weights) {
                Vec3 p = Transform(Invert(bones[w.bone].boneToPose), v.pos);
                bones[w.bone].bmin = Min(bones[w.bone].bmin, p);
                bones[w.bone].bmax = Max(bones[w.bone].bmax, p);
            }
    }
    if (qc.hitboxSets.empty() && !qc.autoHitboxes) {
        // Respawn's studiomdl flags the hitboxes as generated but writes none
        CHitboxSet set;
        set.name = "default";
        qc.flags |= STUDIOHDR_FLAGS_AUTOGENERATED_HITBOX;
        out.hitboxSets.push_back(set);
    } else if (qc.hitboxSets.empty()) {
        // $autohitboxes: one box per bone from its vertices, as Valve's studiomdl
        CHitboxSet set;
        set.name = "default";
        qc.flags |= STUDIOHDR_FLAGS_AUTOGENERATED_HITBOX;
        std::vector<Vec3> mn(bones.size()), mx(bones.size());
        for (size_t k = 0; k < bones.size(); k++) {
            mn[k] = bones[k].bmin;
            mx[k] = bones[k].bmax;
            // retail's generated boxes always contain the bone's origin
            if (mn[k].x <= mx[k].x) {
                mn[k] = Min(mn[k], Vec3());
                mx[k] = Max(mx[k], Vec3());
            }
        }
        for (size_t k = 0; k < bones.size(); k++) {
            int j = bones[k].parent;
            if (j == -1) continue;
            mn[j] = Min(mn[j], bones[k].pos);
            mx[j] = Max(mx[j], bones[k].pos);
        }
        for (size_t k = 0; k < bones.size(); k++) {
            if (mn[k].x < mx[k].x - 1 && mn[k].y < mx[k].y - 1 && mn[k].z < mx[k].z - 1) {
                CHitbox h;
                h.bone = static_cast<int>(k);
                h.group = bones[k].group;
                h.bmin = mn[k];
                h.bmax = mx[k];
                set.boxes.push_back(h);
            }
        }
        out.hitboxSets.push_back(set);
    } else {
        qc.flags &= ~STUDIOHDR_FLAGS_AUTOGENERATED_HITBOX;
        for (auto& qs : qc.hitboxSets) {
            CHitboxSet set;
            set.name = qs.name;
            for (auto& qh : qs.boxes) {
                CHitbox h;
                h.bone = FindBone(qh.bone);
                if (h.bone == -1) Fatal("cannot find bone %s for hitbox", qh.bone.c_str());
                h.group = qh.group;
                h.bmin = qh.bmin;
                h.bmax = qh.bmax;
                h.name = qh.name;
                h.critOverride = qh.critOverride;
                h.hitDataGroup = qh.hitDataGroup;
                set.boxes.push_back(h);
            }
            out.hitboxSets.push_back(set);
        }
    }
    for (auto& set : out.hitboxSets)
        for (auto& h : set.boxes)
            for (int k = h.bone; k != -1; k = bones[k].parent) bones[k].flags |= BONE_USED_BY_HITBOX;
}

void BuildContext::BuildBounds() {
    // CalcSequenceBoundingBoxes: every posed vertex of every mesh, lower LODs included
    // (the vertices the VVD holds), plus each bone's hitbox bounds as a transformed AABB.
    // Retail leaves the per-bone vertex bounds out of the AABB step (rotated vertex boxes
    // would overshoot the vertices themselves).
    std::vector<const SrcVertex*> meshVerts;
    for (auto& ip : insts) {
        if (!ip->active) continue;
        std::vector<bool> used(ip->gverts.size(), false);
        for (auto& f : ip->faces)
            for (int c = 0; c < 3; c++) used[f.v[c]] = true;
        for (auto& mv : ip->src->meshVertices) used[mv.vertex] = true;
        for (size_t i = 0; i < ip->gverts.size(); i++)
            if (used[i]) meshVerts.push_back(&ip->gverts[i]);
    }
    std::vector<Vec3> rmin(bones.size(), Vec3(9999, 9999, 9999)), rmax(bones.size(), Vec3(-9999, -9999, -9999));
    for (auto& set : out.hitboxSets)
        for (auto& h : set.boxes) {
            rmin[h.bone] = Min(rmin[h.bone], h.bmin);
            rmax[h.bone] = Max(rmax[h.bone], h.bmax);
        }
    // deltas are measured applied to a base pose: the first full animation's first frame
    // (retail gives additive sequences that pose's box, nudged by the delta)
    std::vector<Vec3> basePos(bones.size());
    std::vector<RadianEuler> baseRot(bones.size());
    for (size_t k = 0; k < bones.size(); k++) {
        basePos[k] = bones[k].pos;
        baseRot[k] = bones[k].rot;
    }
    for (auto& a : anims)
        if (!(a.flags & STUDIO_DELTA) && a.numFrames > 0) {
            if (a.IsReferenceClip()) break;  // stands for the bind pose
            for (size_t k = 0; k < bones.size(); k++) {
                basePos[k] = a.sanim[0][k].pos;
                baseRot[k] = a.sanim[0][k].rot;
            }
            break;
        }
    for (auto& a : anims) {
        Vec3 bmin(9999, 9999, 9999), bmax(-9999, -9999, -9999);
        for (int j = 0; j < a.numFrames; j++) {
            std::vector<Mat3x4> bt;
            if (a.flags & STUDIO_DELTA) {
                bt.resize(bones.size());
                for (size_t k = 0; k < bones.size(); k++) {
                    const auto& f = a.sanim[j][k];
                    Quat q = QuaternionNormalize(QuaternionMult(AngleQuaternion(f.rot), AngleQuaternion(baseRot[k])));
                    Mat3x4 bm = QuaternionMatrix(q, basePos[k] + f.pos);
                    bt[k] = bones[k].parent == -1 ? bm : Concat(bt[bones[k].parent], bm);
                }
            } else
                CalcBoneTransforms(a, j, bt);
            std::vector<Mat3x4> pt(bones.size());
            for (size_t k = 0; k < bones.size(); k++) {
                pt[k] = Concat(bt[k], Invert(bones[k].boneToPose));
                if (rmin[k].x <= rmax[k].x) {
                    // TransformAABB
                    for (int c = 0; c < 8; c++) {
                        Vec3 corner((c & 1) ? rmax[k].x : rmin[k].x, (c & 2) ? rmax[k].y : rmin[k].y, (c & 4) ? rmax[k].z : rmin[k].z);
                        Vec3 p = Transform(bt[k], corner);
                        bmin = Min(bmin, p);
                        bmax = Max(bmax, p);
                    }
                }
            }
            for (const SrcVertex* v : meshVerts) {
                Vec3 pos;
                for (auto& w : v->weights) pos += Transform(pt[w.bone], v->pos) * w.weight;
                bmin = Min(bmin, pos);
                bmax = Max(bmax, pos);
            }
        }
        if (bmin.x > bmax.x) bmin = bmax = Vec3();
        a.bmin = bmin;
        a.bmax = bmax;
    }
}

void BuildContext::BuildSequences() {
    // nodes for transitions
    std::vector<std::string> nodes;
    auto node = [&](const std::string& n) -> int {
        if (n.empty()) return 0;
        for (size_t i = 0; i < nodes.size(); i++)
            if (IEquals(nodes[i], n)) return static_cast<int>(i) + 1;
        nodes.push_back(n);
        return static_cast<int>(nodes.size());
    };
    for (auto& n : qc.nodes) node(n);  // declared nodes first, in their order
    auto animIndex = [&](const std::string& n) -> int {
        for (size_t i = 0; i < anims.size(); i++)
            if (IEquals(anims[i].name, n)) return static_cast<int>(i);
        return -1;
    };
    for (auto& qs : qc.sequences) {
        if (qs.isOverride) continue;
        CSequence s;
        s.label = qs.name;
        s.activityName = qs.activity;
        s.actWeight = qs.actWeight;
        // Root motion is an animation property, and noforceloop only steers compilation;
        // retail sequences never carry either bit (0x8000 changes the pose in game).
        s.flags = qs.flags & ~(STUDIO_FRAMEMOVEMENT | STUDIO_NOFORCELOOP);
        s.groupSize[0] = qs.groupSize[0];
        s.groupSize[1] = qs.groupSize[1];
        s.fadeIn = qs.fadeIn;
        s.fadeOut = qs.fadeOut;
        s.entryNode = node(qs.entryNode);
        s.exitNode = node(qs.exitNode);
        s.nodeFlags = qs.nodeFlags;
        s.entryPhase = qs.entryPhase;
        s.exitPhase = qs.exitPhase;
        s.keyValues = qs.keyValues;
        s.ikResetMask = qs.ikResetMask;
        s.unkC4 = qs.unkC4;
        for (auto& am : qs.activityModifiers) s.activityModifiers.push_back({am.name, am.negate});
        if (!qs.cyclePose.empty()) s.cyclePose = qc.FindPoseParam(qs.cyclePose);
        if (qs.referencePose) {
            // a descriptor without a clip: 1x1, weights from its list (else every bone),
            // bounds as given (else empty), as retail's ref and ragdoll descriptors
            s.groupSize[0] = s.groupSize[1] = 1;
            if (!qs.assetPose.empty()) s.assetAnim = animIndex(qs.assetPose);
            s.weights.assign(bones.size(), 1.f);
            if (!qs.seqWeights.empty()) {
                auto it = weightLists.find(ToLower(qs.seqWeights));
                if (it == weightLists.end()) Fatal("sequence %s: unknown weightlist '%s'", qs.name.c_str(), qs.seqWeights.c_str());
                s.weights = it->second;
            }
            if (qs.bboxSet) {
                s.bmin = qs.bboxMin;
                s.bmax = qs.bboxMax;
                s.explicitBox = true;
            }
            out.sequences.push_back(s);
            continue;
        }
        // anim index grid: offset = k * groupsize[0] + j for blend (j, k)
        s.animIndices.assign(s.groupSize[0] * s.groupSize[1], 0);
        for (int i = 0; i < static_cast<int>(qs.animations.size()); i++) {
            int a = animIndex(qs.animations[i]);
            if (a < 0) Fatal("sequence %s: missing animation %s", qs.name.c_str(), qs.animations[i].c_str());
            int j = i % s.groupSize[0], k = i / s.groupSize[0];
            s.animIndices[k * s.groupSize[0] + j] = static_cast<int16_t>(a);
            if ((anims[a].flags & STUDIO_HAS_SCALE) && !qs.flagsExplicit) s.flags |= STUDIO_HAS_SCALE;  // as retail sequences do
        }
        const WAnim& first = anims[s.animIndices[0]];
        // blends / pose keys
        for (int p = 0; p < 2; p++) {
            if (!qs.paramName[p].empty()) {
                s.paramIndex[p] = qc.FindPoseParam(qs.paramName[p]);
                s.paramStart[p] = qs.paramStart[p];
                s.paramEnd[p] = qs.paramEnd[p];
            } else if (qs.axisRange[p]) {
                s.axisRange[p] = true;
                s.paramStart[p] = qs.paramStart[p];
                s.paramEnd[p] = qs.paramEnd[p];
            }
        }
        if (!qs.poseKeys.empty()) {
            if (static_cast<int>(qs.poseKeys.size()) != s.groupSize[0] + s.groupSize[1])
                Fatal("sequence %s: posekeys needs %d values", qs.name.c_str(), s.groupSize[0] + s.groupSize[1]);
            s.poseKeys = qs.poseKeys;
        } else if (!qs.noPoseKeys && (s.groupSize[0] > 1 || s.groupSize[1] > 1)) {
            for (int p = 0; p < 2; p++)
                for (int m = 0; m < s.groupSize[p]; m++) {
                    float f = s.groupSize[p] > 1 ? static_cast<float>(m) / (s.groupSize[p] - 1) : 0.f;
                    s.poseKeys.push_back(s.paramStart[p] * (1 - f) + s.paramEnd[p] * f);
                }
        }
        // events
        for (auto& e : qs.events) {
            CEvent ce;
            int k = first.numFrames - 1;
            if (e.explicitCycle)
                ce.cycle = e.cycle;
            else if (e.frame <= k)
                // studiomdl divides by numframes - 1: a one-frame clip's events get 0/0
                // (x86's negative quiet NaN), as retail stores them
                ce.cycle = k > 0 ? e.frame / static_cast<float>(k) : -std::numeric_limits<float>::quiet_NaN();
            else
                Fatal("event %s (frame %d) out of range in %s", e.name.c_str(), e.frame, qs.name.c_str());
            if (!e.name.empty() && std::isdigit(static_cast<unsigned char>(e.name[0]))) {
                ce.event = std::atoi(e.name.c_str());
                ce.type = 0;
            } else {
                ce.name = e.name;
                ce.type = 1 << 10;  // NEW_EVENT_STYLE
            }
            ce.options = e.options;
            s.events.push_back(ce);
        }
        // autolayers
        for (auto& l : qs.layers) {
            CAutoLayer al;
            int si = qc.FindSequence(l.sequence);
            if (si < 0) Fatal("sequence \"%s\" cannot find autolayer sequence \"%s\"", qs.name.c_str(), l.sequence.c_str());
            al.sequence = si;
            al.flags = l.flags;
            al.pose = l.pose.empty() ? 0 : qc.FindPoseParam(l.pose);
            float d = std::max(1, first.numFrames - 1);
            if (!(l.flags & STUDIO_AL_POSE)) {
                al.start = l.start / d;
                al.peak = l.peak / d;
                al.tail = l.tail / d;
                al.end = l.end / d;
            } else {
                al.start = l.start;
                al.peak = l.peak;
                al.tail = l.tail;
                al.end = l.end;
            }
            s.layers.push_back(al);
        }
        for (auto& l : qs.ikLocks) {
            int c = qc.FindIKChain(l.chain);
            if (c < 0) Fatal("unknown chain '%s' in sequence iklock", l.chain.c_str());
            s.ikLocks.push_back({c, l.posWeight, l.localQWeight, 0});
        }
        // bone weights: the sequence's own list ("seqweights"), else the max over blends
        s.weights.assign(bones.size(), 0.f);
        if (!qs.seqWeights.empty()) {
            auto it = weightLists.find(ToLower(qs.seqWeights));
            if (it == weightLists.end()) Fatal("sequence %s: unknown weightlist '%s'", qs.name.c_str(), qs.seqWeights.c_str());
            s.weights = it->second;
        } else {
            for (int16_t ai : s.animIndices)
                for (size_t n = 0; n < bones.size(); n++) s.weights[n] = std::max(s.weights[n], anims[ai].weight[n]);
        }
        // bounds: union over blends
        Vec3 bmin(9999, 9999, 9999), bmax(-9999, -9999, -9999);
        for (int16_t ai : s.animIndices) {
            bmin = Min(bmin, anims[ai].bmin);
            bmax = Max(bmax, anims[ai].bmax);
        }
        s.bmin = bmin;
        s.bmax = bmax;
        if (qs.bboxSet) {
            s.bmin = qs.bboxMin;
            s.bmax = qs.bboxMax;
            s.explicitBox = true;
        }
        out.sequences.push_back(s);
    }
    // autolayer sequence indices refer to the QC order; remap if declared-only sequences were skipped
    out.nodeNames = nodes;
    out.localNodeUnk = qc.localNodeUnk;
    size_t nn = nodes.size();
    out.transitions.assign(nn * nn, 0);
    for (auto& s : out.sequences) {
        if (s.entryNode != s.exitNode && s.entryNode && s.exitNode) {
            out.transitions[(s.entryNode - 1) * nn + (s.exitNode - 1)] = static_cast<uint8_t>(s.exitNode);
            if (s.nodeFlags) out.transitions[(s.exitNode - 1) * nn + (s.entryNode - 1)] = static_cast<uint8_t>(s.entryNode);
        }
    }
    // pose parameters
    for (auto& p : qc.poseParams) {
        CPoseParam cp;
        cp.name = p.name;
        cp.flags = p.flags;
        cp.start = p.min;
        cp.end = p.max;
        cp.loop = p.loop;
        out.poseParams.push_back(cp);
    }
}

void BuildContext::BuildSkins() {
    for (auto& t : qc.textures) {
        std::string n = t;
        bool renamed = false;
        for (auto& r : qc.renameMaterials) {
            // Source readers strip image extensions. A rename's destination is an
            // asset name, however: Apex also stores names ending in .vmt. Once
            // renamed, match subsequent rules exactly so foo and foo.vmt stay distinct.
            if (IEquals(n, r.first) || (!renamed && IEquals(n, StripExtension(r.first)))) {
                n = r.second;
                renamed = true;
            }
        }
        out.textures.push_back(n);  // as written: retail keeps both slash styles
    }
    out.numSkinRef = static_cast<int>(out.textures.size());
    if (qc.cdMaterials.empty()) {
        std::string d = "models/" + StripExtension(FixSlashes(qc.modelName));
        d = DirName(d);
        out.cdTextures.push_back(FixSlashes(d, '\\'));
    } else
        out.cdTextures = qc.cdMaterials;
    if (qc.hasSkinFamilies) {
        // the stored table: every texture slot in row 0, no renumbering
        if (!qc.textureGroups.empty()) Fatal("$skinfamilies and $texturegroup cannot be combined");
        if (qc.skinFamilies[0].size() != out.textures.size())
            Fatal("$skinfamilies lists %d texture slots, but the model has %d (every material belongs in the first family)",
                  static_cast<int>(qc.skinFamilies[0].size()), static_cast<int>(out.textures.size()));
        for (size_t j = 0; j < qc.skinFamilies[0].size(); j++)
            if (qc.TextureIndex(qc.skinFamilies[0][j], false) != static_cast<int>(j))
                Fatal("$skinfamilies: the first family must list every texture slot once, in order");
        for (auto& row : qc.skinFamilies) {
            std::vector<int16_t> fam;
            for (auto& name : row) {
                int t = qc.TextureIndex(name, false);
                if (t < 0) Fatal("$skinfamilies: material \"%s\" is not a texture slot", name.c_str());
                fam.push_back(static_cast<int16_t>(t));
            }
            out.skins.push_back(fam);
        }
        out.skinNames = qc.skinFamilyNames;
        return;
    }
    int families = 1;
    if (!qc.textureGroups.empty()) families = std::max<int>(1, static_cast<int>(qc.textureGroups[0].size()));
    out.skins.assign(families, std::vector<int16_t>(out.numSkinRef));
    for (int f = 0; f < families; f++)
        for (int j = 0; j < out.numSkinRef; j++) out.skins[f][j] = static_cast<int16_t>(j);
    if (!qc.textureGroups.empty()) {
        auto& g = qc.textureGroups[0];
        for (size_t f = 0; f < g.size(); f++)
            for (size_t j = 0; j < g[f].size() && j < g[0].size(); j++) {
                int base = qc.TextureIndex(g[0][j], false);
                int repl = qc.TextureIndex(g[f][j], false);
                if (base >= 0 && repl >= 0) out.skins[f][base] = static_cast<int16_t>(repl);
            }
        if (qc.textureGroups.size() > 1) Warn("only the first $texturegroup is used");

        // Retail lists each base texture followed by its replacements (column by column)
        // rather than all replacements after the base set; renumber to match.
        std::vector<int> remap(out.textures.size(), -1);
        int next = 0;
        for (int j = 0; j < out.numSkinRef; j++)
            for (int f = 0; f < families; f++) {
                int t = out.skins[f][j];
                if (remap[t] < 0) remap[t] = next++;
            }
        for (auto& r : remap)
            if (r < 0) r = next++;
        std::vector<std::string> textures(out.textures.size());
        for (size_t i = 0; i < remap.size(); i++) textures[remap[i]] = out.textures[i];
        out.textures = textures;
        auto skins = out.skins;
        for (int f = 0; f < families; f++)
            for (int j = 0; j < out.numSkinRef; j++) out.skins[f][remap[j]] = static_cast<int16_t>(remap[skins[f][j]]);
        for (auto& bp : out.bodyParts)
            for (auto& md : bp.models)
                for (auto& me : md.meshes) me.material = remap[me.material];
        for (auto& lod : out.lodMaterialReplacements)
            for (auto& r : lod) r.first = remap[r.first];
    }
}

void BuildContext::FinalizeBones() {
    for (size_t i = 0; i < bones.size(); i++) {
        const GBone& g = bones[i];
        CBone b;
        b.name = g.name;
        b.parent = g.parent;
        b.pos = g.pos;
        b.scale = g.scale;
        b.rot = g.rot;
        b.qAlignment = Quat();
        b.quat = AngleQuaternion(g.rot);  // retail stores it unaligned (w may be negative)
        b.rotscale = g.rotscale;
        b.posscale = Vec3();  // v53 keeps position scales in the animation records
        b.scalescale = Vec3();
        b.boneToPose = g.boneToPose;
        b.poseToBone = Invert(g.boneToPose);
        b.flags = g.flags;
        b.physicsBone = g.physicsBone;
        // surface prop / contents walk up the hierarchy
        b.surfaceProp = qc.surfaceProp;
        b.contents = qc.contents;
        for (int k = static_cast<int>(i); k != -1; k = bones[k].parent) {
            bool found = false;
            for (auto& sp : qc.jointSurfaceProps)
                if (IEquals(sp.first, bones[k].name)) {
                    b.surfaceProp = sp.second;
                    found = true;
                }
            if (found) break;
        }
        for (int k = static_cast<int>(i); k != -1; k = bones[k].parent) {
            bool found = false;
            for (auto& c : qc.jointContents)
                if (IEquals(c.first, bones[k].name)) {
                    b.contents = c.second;
                    found = true;
                }
            if (found) break;
        }
        for (auto& sa : qc.screenAlign)
            if (IEquals(sa.first, g.name)) b.flags |= sa.second;
        out.bones.push_back(b);
    }
    for (auto& jb : qc.jiggleBones) {
        int k = FindBone(jb.bone);
        if (k < 0) {
            Warn("jigglebone %s: bone not in model, ignored", jb.bone.c_str());
            continue;
        }
        CJiggle j;
        j.flags = jb.flags;
        std::copy(std::begin(jb.v), std::end(jb.v), j.v);
        j.tipFriction = jb.tipFriction;
        j.storedBone = jb.storedBone;
        out.bones[k].proctype = 5;  // STUDIO_PROC_JIGGLE
        out.bones[k].jiggle = static_cast<int>(out.jiggles.size());
        out.bones[k].flags |= BONE_ALWAYS_PROCEDURAL;
        out.jiggles.push_back(j);
    }
    // other procedural bones (studiomdl TagProceduralBones / RemapProceduralBones / WriteBoneInfo)
    auto procBone = [&](const std::string& name, const char* what) -> int {
        int k = FindBone(name);
        if (k < 0) Verbose("%s \"%s\" unused", what, name.c_str());
        return k;
    };
    auto needBone = [&](const std::string& name, const std::string& owner) -> int {
        int k = FindBone(name);
        if (k < 0) Fatal("missing control bone \"%s\" for procedural bone \"%s\"", name.c_str(), owner.c_str());
        return k;
    };
    auto quatOf = [](const Mat3x4& m) { return AngleQuaternion(MatrixAngles(m)); };
    auto markChain = [&](int from, int flags) {
        for (int k = from; k != -1; k = bones[k].parent) out.bones[k].flags |= flags;
    };
    for (auto& ax : qc.axisInterpBones) {
        int k = procBone(ax.bone, "axisinterpbone");
        if (k < 0) continue;
        int control = needBone(ax.control, ax.bone);
        Buffer b;
        b.I32(control);
        b.I32(ax.axis);
        for (auto& p : ax.pos) b.V3(p);
        for (auto& q : ax.quat) b.Q(q);
        out.bones[k].proctype = 1;  // STUDIO_PROC_AXISINTERP
        out.bones[k].procData = b.Data();
        out.bones[k].flags |= BONE_ALWAYS_PROCEDURAL;
    }
    for (auto& qi : qc.quatInterpBones) {
        int k = procBone(qi.bone, "quatinterpbone");
        if (k < 0) continue;
        int control = needBone(qi.control, qi.bone);
        Buffer b;
        b.I32(control);
        b.I32(static_cast<int>(qi.triggers.size()));
        b.I32(12);  // triggers follow the struct
        for (auto& t : qi.triggers) {
            Quat trigger = quatOf(Concat(QuaternionMatrix(t.trigger), bones[control].srcRealign));
            Vec3 tmp = t.pos + bones[control].pos * qi.percentage;
            Mat3x4 dest = Concat(QuaternionMatrix(t.quat, tmp), bones[k].srcRealign);
            b.F32(t.tolerance > 0 ? 1.f / t.tolerance : 0.f);
            b.Q(trigger);
            b.V3(dest.Origin());
            b.Q(quatOf(dest));
        }
        out.bones[k].proctype = 2;  // STUDIO_PROC_QUATINTERP
        out.bones[k].procData = b.Data();
        out.bones[k].flags |= BONE_ALWAYS_PROCEDURAL;
        // MarkProceduralBoneChain: the control chain is used wherever the bone is
        int used = out.bones[k].flags & BONE_USED_BY_ANYTHING;
        markChain(control, used);
        markChain(k, used);
    }
    for (auto& am : qc.aimAtBones) {
        int k = procBone(am.bone, "<aimconstraint>");
        if (k < 0) continue;
        int parent = needBone(am.parent, am.bone);
        int attach = -1;
        for (size_t i = 0; i < out.attachments.size(); i++)
            if (out.attachments[i].name == am.aim) attach = static_cast<int>(i);
        int aim = attach >= 0 ? attach : FindBone(am.aim);
        if (aim < 0) Fatal("missing aim control attachment or bone \"%s\" for procedural bone \"%s\"", am.aim.c_str(), am.bone.c_str());
        Buffer b;
        b.I32(parent);
        b.I32(aim);
        b.V3(am.aimVector);
        b.V3(am.upVector);
        b.V3(am.basePos);
        out.bones[k].proctype = attach >= 0 ? 4 : 3;  // STUDIO_PROC_AIMATATTACH / AIMATBONE
        out.bones[k].procData = b.Data();
        out.bones[k].flags |= BONE_ALWAYS_PROCEDURAL;
        int used = out.bones[k].flags & BONE_USED_BY_ANYTHING;
        markChain(parent, used);
        if (attach < 0) markChain(aim, used);
    }
    // RUI panel meshes
    for (auto& qp : qc.uiPanels) {
        CUIPanel p;
        p.name = qp.name;
        p.hash = qp.hasHash ? qp.hash : UIPanelHash(qp.name);
        // v54 face order: the faces drawn with the stored winding, then the ccw faces
        // (drawn reversed); the mask count is the number of the former. The client's
        // panel draw (r5apex.exe 0x1402FF7A0) switches index writers at that face.
        std::vector<size_t> order;
        for (int pass = 0; pass < 2; pass++)
            for (size_t i = 0; i < qp.faces.size(); i++)
                if (qp.ccw[i] == pass) order.push_back(i);
        int front = static_cast<int>(std::count(qp.ccw.begin(), qp.ccw.end(), 0));
        p.maskCount = qp.maskCount >= 0 ? qp.maskCount : front;
        for (size_t i : order) {
            p.bounds.push_back(qp.bounds[i]);
            // per-face mask: the cells of a 4x4 grid over the panel that the face's
            // bounds polygon overlaps, given or derived (all 33,173 S0-S3 retail faces)
            p.faceMasks.push_back(qp.faceMasks.empty() ? UIPanelFaceMask(qp.bounds[i]) : qp.faceMasks[i]);
        }
        for (auto& name : qp.parents) p.parents.push_back(needBone(name, qp.name));
        for (auto& v : qp.vertices) {
            if (v.parent < 0 || v.parent >= static_cast<int>(p.parents.size()))
                Fatal("$uipanel %s: vertex parent slot %d out of range", qp.name.c_str(), v.parent);
            p.vertices.push_back({v.parent, v.pos});
        }
        for (size_t fi : order) {
            const auto& f = qp.faces[fi];
            for (int i : f)
                if (i < 0 || i >= static_cast<int>(p.vertices.size()))
                    Fatal("$uipanel %s: face vertex %d out of range", qp.name.c_str(), i);
            p.faces.push_back({static_cast<int16_t>(f[0]), static_cast<int16_t>(f[1]), static_cast<int16_t>(f[2])});
        }
        out.uiPanels.push_back(std::move(p));
    }
    for (auto& bf : qc.boneFollowers) {
        int k = FindBone(bf);
        if (k < 0)
            Warn("bone follower %s: bone not found", bf.c_str());
        else
            out.boneFollowers.push_back(k);
    }
}

CompiledModel Build(QcModelDef& qc) {
    BuildContext ctx(qc);
    if (qc.modelName.empty()) Fatal("$modelname is missing");
    if (qc.sequences.empty() && qc.includeModels.empty()) {
        // studiomdl requires a sequence; give static meshes an implicit idle from the first body
        for (auto& bp : qc.bodyParts)
            for (auto& sm : bp.models)
                if (!sm.blank && sm.source && qc.sequences.empty()) {
                    auto a = std::make_shared<QcAnimation>();
                    a->name = "@idle";
                    a->implied = true;
                    a->file = sm.file;
                    a->source = sm.source;
                    a->sourceScale = sm.scale;
                    a->adjust = qc.defaultAdjust;
                    a->rotation = qc.defaultRotation;
                    a->startFrame = a->endFrame = sm.source->startFrame;
                    a->frameRangeSet = true;
                    qc.animations.push_back(a);
                    QcSequence s;
                    s.name = "idle";
                    s.animations.push_back(a->name);
                    s.groupSize[0] = s.groupSize[1] = 1;
                    qc.sequences.push_back(s);
                    Info("no $sequence given; added \"idle\" from %s", sm.file.c_str());
                }
        if (qc.sequences.empty()) Fatal("model has no sequences");
    }
    ctx.LoadInstances();
    if (qc.staticProp) ctx.MakeStaticProp();
    ctx.BuildBones();
    ctx.RemapVertices();
    ctx.BuildMeshes();
    ctx.BuildAnimations();
    ctx.BuildAttachments();
    ctx.BuildIK();
    ctx.BuildHitboxes();
    ctx.BuildBounds();
    ctx.BuildSequences();
    ProcessIKRules(ctx);
    EncodeAnimations(ctx);
    {
        // asset-only animations (referencepose clips) go last, outside the model's table
        auto& anims = ctx.out.animations;
        std::vector<int> order, remap(anims.size());
        for (int pass = 0; pass < 2; pass++)
            for (size_t i = 0; i < anims.size(); i++)
                if (anims[i].assetOnly == (pass == 1)) order.push_back(static_cast<int>(i));
        std::vector<CAnimation> sorted;
        for (size_t n = 0; n < order.size(); n++) {
            remap[order[n]] = static_cast<int>(n);
            sorted.push_back(std::move(anims[order[n]]));
        }
        anims = std::move(sorted);
        ctx.out.modelAnimations = 0;
        for (auto& a : anims) ctx.out.modelAnimations += a.assetOnly ? 0 : 1;
        for (auto& s : ctx.out.sequences) {
            for (auto& ai : s.animIndices) ai = static_cast<int16_t>(remap[ai]);
            if (s.assetAnim >= 0) s.assetAnim = remap[s.assetAnim];
        }
    }
    ctx.BuildSkins();
    ctx.FinalizeBones();

    CompiledModel& out = ctx.out;
    // a static prop's single bone has every usage bit through 0x800000 (all 152 S3 props)
    if (qc.staticProp)
        for (auto& b : out.bones) { b.flags |= 0xFFFF00; b.flagsVerbatim = true; }
    out.name = qc.modelName;  // as written (retail names keep their slashes)
    if (!EndsWithI(out.name, ".mdl")) out.name += ".mdl";
    out.surfaceProp = qc.surfaceProp;
    out.contents = qc.contents;
    out.keyValues = ApexKeyValues(qc.keyValues);
    out.sourceFiles = qc.sourceFiles;
    for (auto& t : qc.srcBoneTransforms) {
        CompiledModel::SrcBoneTransform c;
        c.bone = t.bone;
        std::copy(std::begin(t.pre), std::end(t.pre), c.pre);
        std::copy(std::begin(t.post), std::end(t.post), c.post);
        out.srcBoneTransforms.push_back(c);
    }
    out.fadeDistance = qc.fadeDistance;
    out.constDirectionalLightDot = qc.constDirectionalLightDot;
    out.maxEyeDeflection = qc.maxEyeDeflection;
    out.unkString = qc.unkString;
    out.includeModels = qc.includeModels;
    out.eyePosition = qc.eyePosition;
    out.numAllowedRootLods = static_cast<uint8_t>(qc.allowRootLods);
    if (qc.illumSet) {
        out.illumPosition = qc.illumPosition;
        if (!qc.illumBone.empty()) {
            int k = ctx.FindBone(qc.illumBone);
            if (k >= 0) out.illumPosition = Transform(ctx.bones[k].boneToPose, qc.illumPosition);
        }
    } else if (!out.sequences.empty()) {
        // retail: centred horizontally, three quarters of (min + max) vertically
        const Vec3 &mn = out.sequences[0].bmin, &mx = out.sequences[0].bmax;
        out.illumPosition = (mn + mx) * 0.5f;
        out.illumPosition.z = (mn.z + mx.z) * 0.75f;
    }
    // header 0x190: the __illumPosition attachment's index + 1, else 0 (580 of 1,789
    // S0-S3 models have it, always last). Ten R-301 models store a value 8 past it,
    // a stale retail index the decompiler keeps with $illumpositionattachment.
    out.illumPositionAttachment = 0;
    for (size_t i = 0; i < out.attachments.size(); i++)
        if (IEquals(out.attachments[i].name, "__illumPosition")) out.illumPositionAttachment = static_cast<int>(i) + 1;
    if (qc.illumAttachment >= 0) out.illumPositionAttachment = qc.illumAttachment;
    // collision may grow the bounds
    BuildCollisionModel(ctx);
    if (!qc.collision.present && qc.headerMass >= 0) out.physics.mass = qc.headerMass;
    if (qc.bboxSet) {
        out.hullMin = qc.bbox[0];
        out.hullMax = qc.bbox[1];
    } else if (!out.sequences.empty()) {
        out.hullMin = out.sequences[0].bmin;
        out.hullMax = out.sequences[0].bmax;
    }
    if (qc.cboxSet) {
        out.viewMin = qc.cbox[0];
        out.viewMax = qc.cbox[1];
    }
    if (out.hasVertexColor) qc.flags |= STUDIOHDR_FLAGS_USES_VERTEX_COLOR;
    if (out.hasUV2) qc.flags |= STUDIOHDR_FLAGS_USES_UV2;
    // retail sets this on every single-bone model except those with physics, no
    // map-collision block and a static collision count of 0 (4/4 across both corpora)
    if (out.bones.size() == 1 &&
        !(qc.collision.present && qc.collision.noMapCollision && out.physics.staticCollisionCount == 0))
        qc.flags |= STUDIOHDR_FLAGS_RESPAWN_800000;
    out.flags = qc.flags;
    if (qc.generatedHitboxes) out.flags |= STUDIOHDR_FLAGS_AUTOGENERATED_HITBOX;
    if (qc.respawnFlag >= 0) {
        out.flags &= ~STUDIOHDR_FLAGS_RESPAWN_800000;
        if (qc.respawnFlag) out.flags |= STUDIOHDR_FLAGS_RESPAWN_800000;
    }
    out.zeroUnusedLods = qc.zeroUnusedLods;
    for (auto& f : qc.boneFlags) {
        int k = ctx.FindBone(f.first);
        if (k < 0) Fatal("unknown bone '%s' in $boneflags", f.first.c_str());
        out.bones[k].flags = f.second;
        out.bones[k].flagsVerbatim = true;
    }
    for (auto& usage : qc.boneUsage) {
        int k = ctx.FindBone(usage.first);
        if (k < 0) Fatal("unknown bone '%s' in $boneusage", usage.first.c_str());
        out.bones[k].flags = (out.bones[k].flags & ~0xfff00) | usage.second;
    }
    if (qc.staticProp) out.flags |= STUDIOHDR_FLAGS_STATIC_PROP;
    out.forceComplexWeights = qc.forceComplexWeights;
    out.externalAssetRig = qc.externalAssets;
    out.surfacePropIds = qc.surfacePropIds;
    out.extraHeaderFlags = qc.extraHeaderFlags;
    // $materialtype: the slot's shader family, matched against the final material names
    if (!qc.materialTypes.empty()) {
        out.materialTypes.assign(out.textures.size(), out.bones.size() > 1 ? 5 : 2);
        for (auto& binding : qc.materialTypes) {
            bool found = false;
            for (size_t i = 0; i < out.textures.size(); i++)
                if (out.textures[i] == binding.first) { out.materialTypes[i] = static_cast<uint8_t>(binding.second); found = true; }
            if (!found) Fatal("$materialtype \"%s\" does not match a texture slot", binding.first.c_str());
        }
    }
    BuildPerTriAABB(ctx);
    if (qc.perTriMesh.present && !qc.bboxSet) {
        out.hullMin = Min(out.hullMin, qc.perTriMesh.bmin);
        out.hullMax = Max(out.hullMax, qc.perTriMesh.bmax);
    }
    if (out.unkString.empty()) out.unkString = "";
    return std::move(ctx.out);
}

}  // namespace r2c
