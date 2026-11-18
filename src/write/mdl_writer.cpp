// Early Apex v54 studio data. Vertex data is written to separate components or
// a VG buffer by the selected season profile; no TF2 embedded-file container.
#include <algorithm>
#include <cstring>
#include <numeric>
#include <map>
#include <filesystem>

#include "core/buffer.h"
#include "core/log.h"
#include "core/strings.h"
#include "write/writers.h"

namespace r2c {

namespace {

// Early Apex studiohdr_t, 0x224 bytes; measured against installed S0-S3 assets.
enum HdrOff : size_t {
    H_ID = 0x0, H_VERSION = 0x4, H_CHECKSUM = 0x8, H_SZNAME = 0xC, H_NAME = 0x10, H_LENGTH = 0x50,
    H_EYEPOS = 0x54, H_ILLUMPOS = 0x60, H_HULLMIN = 0x6C, H_HULLMAX = 0x78, H_VIEWMIN = 0x84, H_VIEWMAX = 0x90,
    H_FLAGS = 0x9C, H_NUMBONES = 0xA0, H_BONEINDEX = 0xA4, H_NUMBONECONTROLLERS = 0xA8, H_BONECONTROLLERINDEX = 0xAC,
    H_NUMHITBOXSETS = 0xB0, H_HITBOXSETINDEX = 0xB4, H_NUMLOCALANIM = 0xB8, H_LOCALANIMINDEX = 0xBC,
    H_NUMLOCALSEQ = 0xC0, H_LOCALSEQINDEX = 0xC4, H_ACTIVITYLISTVERSION = 0xC8, H_EVENTSINDEXED = 0xCC,
    H_NUMTEXTURES = 0xD0, H_TEXTUREINDEX = 0xD4, H_NUMCDTEXTURES = 0xD8, H_CDTEXTUREINDEX = 0xDC,
    H_NUMSKINREF = 0xE0, H_NUMSKINFAMILIES = 0xE4, H_SKININDEX = 0xE8, H_NUMBODYPARTS = 0xEC, H_BODYPARTINDEX = 0xF0,
    H_NUMLOCALATTACHMENTS = 0xF4, H_LOCALATTACHMENTINDEX = 0xF8, H_NUMLOCALNODES = 0xFC, H_LOCALNODEINDEX = 0x100,
    H_LOCALNODENAMEINDEX = 0x104, H_LOCALNODEUNK = 0x108, H_FLEXDESCINDEX = 0x10C, H_NUMFLEXCONTROLLERS = 0x114,
    H_FLEXCONTROLLERINDEX = 0x118, H_NUMFLEXRULES = 0x11C, H_FLEXRULEINDEX = 0x120, H_NUMIKCHAINS = 0x124,
    H_IKCHAININDEX = 0x128, H_UIPANELCOUNT = 0x12C, H_UIPANELOFFSET = 0x130, H_NUMLOCALPOSEPARAMETERS = 0x134,
    H_LOCALPOSEPARAMINDEX = 0x138, H_SURFACEPROPINDEX = 0x13C, H_KEYVALUEINDEX = 0x140, H_KEYVALUESIZE = 0x144,
    H_NUMLOCALIKAUTOPLAYLOCKS = 0x148, H_LOCALIKAUTOPLAYLOCKINDEX = 0x14C, H_MASS = 0x150, H_CONTENTS = 0x154,
    H_NUMINCLUDEMODELS = 0x158, H_INCLUDEMODELINDEX = 0x15C, H_VIRTUALMODEL = 0x160, H_BONETABLEBYNAMEINDEX = 0x164,
    H_CONSTDIRLIGHTDOT = 0x168, H_ROOTLOD = 0x169, H_NUMALLOWEDROOTLODS = 0x16A, H_FADEDISTANCE = 0x16C,
    H_NUMFLEXCONTROLLERUI = 0x174, H_FLEXCONTROLLERUIINDEX = 0x178, H_VERTANIMSCALE = 0x17C, H_SURFACEPROPLOOKUP = 0x180,
    H_SOURCEFILENAMEOFFSET = 0x184, H_NUMSRCBONETRANSFORM = 0x188, H_SRCBONETRANSFORMINDEX = 0x18C,
    H_ILLUMPOSATTACHMENTINDEX = 0x190, H_LINEARBONEINDEX = 0x194, H_NUMPROCBONES = 0x198,
    H_PROCBONETABLEINDEX = 0x19C, H_LINEARPROCBONEINDEX = 0x1A0, H_BONEFLEXDRIVERCOUNT = 0x1A4,
    H_BONEFLEXDRIVERINDEX = 0x1A8, H_PERTRIINDEX = 0x1AC, H_PERTRINODECOUNT = 0x1B0, H_PERTRILEAFCOUNT = 0x1B4,
    H_PERTRIVERTCOUNT = 0x1B8, H_UNKSTRINGOFFSET = 0x1BC, H_VTXOFFSET = 0x1C0, H_VVDOFFSET = 0x1C4, H_VVCOFFSET = 0x1C8,
    H_PHYOFFSET = 0x1CC, H_VTXSIZE = 0x1D0, H_VVDSIZE = 0x1D4, H_VVCSIZE = 0x1D8, H_PHYSIZE = 0x1DC,
    H_COLLISIONOFFSET = 0x1E0, H_STATICCOLLISIONCOUNT = 0x1E4, H_BONEFOLLOWERCOUNT = 0x1E8, H_BONEFOLLOWEROFFSET = 0x1EC,
    H_SIZE = 0x224,
};

constexpr size_t kBoneSize = 0xB8, kJiggleSize = 0x78, kAttachSize = 0x3C, kHboxSetSize = 0x0C, kHboxSize = 0x2C,
                 kAnimDescSize = 0x34, kSeqDescSize = 0xD0, kEventSize = 0x110, kAutoLayerSize = 0x18, kIKLockSize = 0x10,
                 kBodyPartSize = 0x10, kModelSize = 0x88, kMeshSize = 0x5C, kIKChainSize = 0x14, kIKLinkSize = 0x10, kIKRuleSize = 0x88,
                 kPoseParamSize = 0x14, kModelGroupSize = 0x08, kTextureSize = 0xC, kMovementSize = 0x2C;

class MdlWriter {
public:
    explicit MdlWriter(const CompiledModel& m, bool vertexGroup) : m_(m), vertexGroup_(vertexGroup) {}
    std::vector<uint8_t> Run();
    std::vector<uint8_t> RunSequence();

private:
    const CompiledModel& m_;
    bool vertexGroup_;
    bool standaloneSequence_ = false;
    size_t animationBase_ = 0;
    struct AnimationRef { size_t field, sequence; int index; };
    std::vector<AnimationRef> animationRefs_;
    Buffer b_;
    StringTable st_;

    void Str(size_t field, size_t base, const std::string& s) { st_.Add(field, base, s); }
    void Hdr(size_t off, int32_t v) { if (!standaloneSequence_) b_.PatchI32(off, v); }
    void HdrHere(size_t off) { Hdr(off, static_cast<int32_t>(b_.Tell())); }
    int32_t Rel(size_t from) const { return static_cast<int32_t>(b_.Tell() - from); }

    void WriteHeader();
    void WriteSourceFiles();
    void WriteBones();
    void WriteProceduralBones(size_t boneBase);
    void WriteAttachments();
    void WriteHitboxes();
    void WriteBoneTable();
    void WriteAnimations();
    void WriteSequences();
    void WriteIKRules(size_t p, const CAnimation& a);
    void WriteAnimDesc(size_t p, const CAnimation& a, bool inlineClip);
    void WriteNodes();
    void WriteBodyParts();
    void WriteIK();
    void WritePoseParams();
    void WriteIncludeModels();
    void WriteTextures();
    void WriteKeyValues();
    void WriteLinearBones();
    void WritePerTri();
};

void MdlWriter::WriteHeader() {
    b_.Reserve(H_SIZE);
    b_.PatchAt<uint32_t>(H_ID, 0x54534449);  // IDST
    Hdr(H_VERSION, 54);
    Str(H_SZNAME, 0, m_.name);
    std::string n = m_.name;
    if (n.size() > 62) n = n.substr(0, 62);  // retail keeps at most 62 characters here (9/9 long names)
    std::memcpy(&b_.Data()[H_NAME], n.data(), n.size());
    auto v3 = [&](size_t off, const Vec3& v) {
        b_.PatchAt<float>(off, v.x);
        b_.PatchAt<float>(off + 4, v.y);
        b_.PatchAt<float>(off + 8, v.z);
    };
    v3(H_EYEPOS, m_.eyePosition);
    v3(H_ILLUMPOS, m_.illumPosition);
    v3(H_HULLMIN, m_.hullMin);
    v3(H_HULLMAX, m_.hullMax);
    v3(H_VIEWMIN, m_.viewMin);
    v3(H_VIEWMAX, m_.viewMax);
    Hdr(H_FLAGS, m_.flags);
    b_.PatchAt<float>(H_MASS, m_.physics.mass);
    Hdr(H_CONTENTS, m_.contents);
    b_.PatchAt<uint8_t>(H_CONSTDIRLIGHTDOT, m_.constDirectionalLightDot);
    b_.PatchAt<uint8_t>(H_ROOTLOD, m_.rootLod);
    b_.PatchAt<uint8_t>(H_NUMALLOWEDROOTLODS, m_.numAllowedRootLods);
    b_.PatchAt<uint8_t>(H_NUMALLOWEDROOTLODS, m_.numAllowedRootLods);
    b_.PatchAt<float>(H_FADEDISTANCE, m_.fadeDistance);
    Str(H_SURFACEPROPINDEX, 0, m_.surfaceProp);
    Hdr(H_SURFACEPROPLOOKUP, m_.SurfacePropId(m_.surfaceProp));
    Str(H_UNKSTRINGOFFSET, 0, m_.unkString);
    Hdr(H_ILLUMPOSATTACHMENTINDEX, m_.illumPositionAttachment);
}

void MdlWriter::WriteSourceFiles() {
    HdrHere(H_SOURCEFILENAMEOFFSET);
    std::string s;
    for (auto& f : m_.sourceFiles) s += f + ";";
    b_.CString(s);
    b_.Zero(3);
    b_.Align(4);
}

void MdlWriter::WriteBones() {
    HdrHere(H_BONEINDEX);
    Hdr(H_NUMBONES, static_cast<int>(m_.bones.size()));
    size_t base = b_.Reserve(kBoneSize * m_.bones.size());
    for (size_t i = 0; i < m_.bones.size(); i++) {
        const CBone& bn = m_.bones[i];
        size_t p = base + i * kBoneSize;
        Str(p + 0x00, p, bn.name);
        b_.PatchI32(p + 0x04, bn.parent);
        for (int c = 0; c < 6; c++) b_.PatchI32(p + 0x08 + c * 4, -1);
        auto f = [&](size_t off, float v) { b_.PatchAt<float>(p + off, v); };
        f(0x20, bn.pos.x); f(0x24, bn.pos.y); f(0x28, bn.pos.z);
        f(0x2C, bn.quat.x); f(0x30, bn.quat.y); f(0x34, bn.quat.z); f(0x38, bn.quat.w);
        f(0x3C, bn.rot.x); f(0x40, bn.rot.y); f(0x44, bn.rot.z);
        f(0x48, bn.scale.x); f(0x4C, bn.scale.y); f(0x50, bn.scale.z);
        for (int r = 0; r < 3; r++)
            for (int c = 0; c < 4; c++) f(0x54 + (r * 4 + c) * 4, bn.poseToBone.m[r][c]);
        b_.PatchI32(p + 0x94, bn.flagsVerbatim ? bn.flags : bn.flags & ~BONE_USED_BY_BONE_MERGE);
        b_.PatchI32(p + 0xA0, bn.physicsBone);
        Str(p + 0xA4, p, bn.surfaceProp);
        b_.PatchI32(p + 0xA8, bn.contents);
        b_.PatchI32(p + 0xAC, m_.SurfacePropId(bn.surfaceProp));  // the game's surface id
        b_.PatchI32(p + 0xB4, bn.bvhEntry);
    }
    WriteProceduralBones(base);
    // the bone-controller offset is the unpadded end of the procedural tables (all 114
    // retail jiggle models; padding here crashed R5R); attachments follow 4-aligned
    HdrHere(H_BONECONTROLLERINDEX);
    b_.Align(4);
}

// v54 jiggle bones, measured on all 748 retail records (114 S0-S3 models): one 0x7C
// record per procedural bone straight after the bone array, in procedural ($jigglebone)
// order; then a byte table of bone indices in that order (0x19C) and a per-bone byte
// table holding each bone's procedural slot or 255 (0x1A0). Models without procedural
// bones store zeros in all three header fields.
void MdlWriter::WriteProceduralBones(size_t boneBase) {
    std::vector<int> order(m_.jiggles.size(), -1);
    for (size_t i = 0; i < m_.bones.size(); i++)
        if (m_.bones[i].jiggle >= 0) order.at(m_.bones[i].jiggle) = static_cast<int>(i);
    std::vector<int> slots;
    for (int bone : order)
        if (bone >= 0) slots.push_back(bone);  // a jiggle whose bone was dropped writes nothing
    if (slots.empty()) return;
    Hdr(H_NUMPROCBONES, static_cast<int>(slots.size()));
    for (int bone : slots) {
        const CJiggle& j = m_.jiggles[m_.bones[bone].jiggle];
        size_t p = b_.Tell();
        b_.PatchI32(boneBase + bone * kBoneSize + 0x98, 5);  // STUDIO_PROC_JIGGLE
        b_.PatchI32(boneBase + bone * kBoneSize + 0x9C, static_cast<int32_t>(p - (boneBase + bone * kBoneSize)));
        b_.U8(static_cast<uint8_t>(j.flags));
        b_.U8(static_cast<uint8_t>(j.storedBone >= 0 ? j.storedBone : bone));
        b_.I16(0);
        b_.F32(j.v[0]);
        b_.F32(j.v[1]);
        b_.F32(j.tipFriction);
        for (int k = 2; k < 29; k++) b_.F32(j.v[k]);
    }
    HdrHere(H_PROCBONETABLEINDEX);
    for (int bone : slots) b_.U8(static_cast<uint8_t>(bone));
    HdrHere(H_LINEARPROCBONEINDEX);
    std::vector<uint8_t> slotOf(m_.bones.size(), 255);
    for (size_t s = 0; s < slots.size(); s++) slotOf[slots[s]] = static_cast<uint8_t>(s);
    for (uint8_t s : slotOf) b_.U8(s);
}

void MdlWriter::WriteAttachments() {
    HdrHere(H_LOCALATTACHMENTINDEX);
    Hdr(H_NUMLOCALATTACHMENTS, static_cast<int>(m_.attachments.size()));
    for (auto& a : m_.attachments) {
        size_t p = b_.Tell();
        b_.I32(0);
        Str(p, p, a.name);
        b_.U32(a.flags);
        b_.I32(a.bone);
        b_.M34(a.local);
    }
}

void MdlWriter::WriteHitboxes() {
    HdrHere(H_HITBOXSETINDEX);
    Hdr(H_NUMHITBOXSETS, static_cast<int>(m_.hitboxSets.size()));
    size_t base = b_.Reserve(kHboxSetSize * m_.hitboxSets.size());
    for (size_t s = 0; s < m_.hitboxSets.size(); s++) {
        auto& set = m_.hitboxSets[s];
        size_t p = base + s * kHboxSetSize;
        Str(p, p, set.name);
        b_.PatchI32(p + 4, static_cast<int>(set.boxes.size()));
        b_.PatchI32(p + 8, Rel(p));
        for (auto& h : set.boxes) {
            size_t q = b_.Tell();
            b_.I32(h.bone);
            b_.I32(h.group);
            b_.V3(h.bmin);
            b_.V3(h.bmax);
            b_.I32(0);
            Str(q + 0x20, q, h.name);
            b_.I32(h.critOverride);
            b_.I32(0);
            Str(q + 0x28, q, h.hitDataGroup);
        }
    }
}

void MdlWriter::WriteBoneTable() {
    HdrHere(H_BONETABLEBYNAMEINDEX);
    std::vector<int> order(m_.bones.size());
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](int a, int b) {
        return ToLower(m_.bones[a].name) < ToLower(m_.bones[b].name);
    });
    for (int i : order) b_.U8(static_cast<uint8_t>(i));
    b_.Align(4);
}

void MdlWriter::WriteAnimations() {
    // Descriptors are referenced by sequence-relative int32 offsets in v54.
    HdrHere(H_LOCALANIMINDEX);
    size_t count = m_.modelAnimations >= 0 ? static_cast<size_t>(m_.modelAnimations) : m_.animations.size();
    size_t base = b_.Reserve(kAnimDescSize * count);
    animationBase_ = base;
    for (size_t i = 0; i < count; ++i) WriteAnimDesc(base + i * kAnimDescSize, m_.animations[i], false);
    if (!count) Hdr(H_LOCALANIMINDEX, 0);  // retail stores 0 for an empty table (all S3 models)
}

// One animation descriptor (reserved at p) and its data. A reference descriptor's
// inline clip starts its data on a 16-byte boundary, as retail's do; a clip without
// tracks (flag 0x20000 clear) has no data, its offset pointing at that boundary.
void MdlWriter::WriteAnimDesc(size_t p, const CAnimation& a, bool inlineClip) {
    {
        b_.PatchI32(p, 0); // native animation descriptors, including embedded clips
        Str(p + 4, p, a.name);
        b_.PatchAt<float>(p + 8, a.fps);
        b_.PatchI32(p + 12, a.flags);
        b_.PatchI32(p + 16, a.numFrames);
        // Native v8-v10 animation descriptors retain 44-byte piecewise movements.
        b_.PatchI32(p + 0x14, static_cast<int32_t>(a.movements.size()));
        if (!a.movements.empty()) {
            b_.PatchI32(p + 0x18, Rel(p));
            for (const auto& move : a.movements) {
                b_.I32(move.endFrame); b_.I32(move.motionFlags);
                b_.F32(move.v0); b_.F32(move.v1); b_.F32(move.angle);
                b_.V3(move.vector); b_.V3(move.position);
            }
        }
        if (!a.frameMovement.empty()) {
            b_.Align(4);
            b_.PatchI32(p + 0x1C, Rel(p));
            b_.Append(a.frameMovement);
        }
        // Native sections include the boundary sample for interpolation.
        if (inlineClip) b_.Align(16);
        if (a.nativeSections.empty()) {
            if (!inlineClip) b_.Align(16);
            b_.PatchI32(p + 0x20, Rel(p));
        } else if (a.nativeSections.size() == 1) {
            b_.PatchI32(p + 0x20, Rel(p));
            b_.Append(a.nativeSections[0]);
        } else {
            b_.PatchI32(p + 0x2C, Rel(p));
            b_.PatchI32(p + 0x30, a.sectionFrames);
            size_t table = b_.Reserve(4 * a.nativeSections.size());
            for (size_t j = 0; j < a.nativeSections.size(); ++j) {
                b_.PatchI32(table + 4*j, Rel(p));
                b_.Append(a.nativeSections[j]);
            }
        }
        b_.Align(4);
        if (!a.ikRules.empty()) WriteIKRules(p, a);
    }
}

// v54 mstudioikrule_t (0x88): v53's fields with 0x1C bytes inserted at +0x3C and the
// trailing unused block dropped (stride and fields measured on S3 sequence assets, all
// of whose rules are whole-range releases). The error index is rule-relative; a rule
// without an error stream points past the rule array, as retail's do.
void MdlWriter::WriteIKRules(size_t p, const CAnimation& a) {
    b_.PatchI32(p + 0x24, static_cast<int32_t>(a.ikRules.size()));
    b_.PatchI32(p + 0x28, Rel(p));
    size_t rules = b_.Reserve(kIKRuleSize * a.ikRules.size());
    size_t after = b_.Tell();
    for (size_t j = 0; j < a.ikRules.size(); j++) {
        const CIKRule& r = a.ikRules[j];
        if (!r.compressedError.empty())
            Fatal("%s: Apex IK rules with error streams are not implemented (retail stores only releases)", a.name.c_str());
        size_t q = rules + j * kIKRuleSize;
        b_.PatchI32(q + 0x00, r.index);
        b_.PatchI32(q + 0x04, r.type);
        b_.PatchI32(q + 0x08, r.chain);
        b_.PatchI32(q + 0x0C, r.bone);
        b_.PatchI32(q + 0x10, r.slot);
        b_.PatchAt<float>(q + 0x14, r.height);
        b_.PatchAt<float>(q + 0x18, r.radius);
        b_.PatchAt<float>(q + 0x1C, r.floor);
        b_.PatchAt<float>(q + 0x20, r.pos.x);
        b_.PatchAt<float>(q + 0x24, r.pos.y);
        b_.PatchAt<float>(q + 0x28, r.pos.z);
        b_.PatchAt<float>(q + 0x2C, r.q.x);
        b_.PatchAt<float>(q + 0x30, r.q.y);
        b_.PatchAt<float>(q + 0x34, r.q.z);
        b_.PatchAt<float>(q + 0x38, r.q.w);
        b_.PatchI32(q + 0x58, static_cast<int32_t>(after - q));
        b_.PatchI32(q + 0x5C, r.iStart);
        b_.PatchAt<float>(q + 0x64, r.start);
        b_.PatchAt<float>(q + 0x68, r.peak);
        b_.PatchAt<float>(q + 0x6C, r.tail);
        b_.PatchAt<float>(q + 0x70, r.end);
        b_.PatchAt<float>(q + 0x74, r.contact);
        b_.PatchAt<float>(q + 0x78, 0.f);  // drop
        b_.PatchAt<float>(q + 0x7C, 0.f);  // top
        if (!r.attachment.empty()) Str(q + 0x80, q, r.attachment);
        b_.PatchAt<float>(q + 0x84, r.endHeight);
    }
}

void MdlWriter::WriteSequences() {
    HdrHere(H_LOCALSEQINDEX);
    Hdr(H_NUMLOCALSEQ, static_cast<int>(m_.sequences.size()));
    size_t base = b_.Reserve(kSeqDescSize * m_.sequences.size());
    size_t lastWeights = SIZE_MAX;
    const std::vector<float>* lastWeightVals = nullptr;
    for (size_t i = 0; i < m_.sequences.size(); i++) {
        const CSequence& s = m_.sequences[i];
        size_t p = base + i * kSeqDescSize;
        auto I = [&](size_t off, int32_t v) { b_.PatchI32(p + off, v); };
        auto F = [&](size_t off, float v) { b_.PatchAt<float>(p + off, v); };
        I(0x00, 0); // native int32 animation references; nonzero selects legacy int16 indices
        Str(p + 0x04, p, s.label);
        Str(p + 0x08, p, s.activityName);
        int flags = s.flags;
        bool single = true;
        for (int16_t ai : s.animIndices)
            if (m_.animations[ai].numFrames > 1) single = false;
        // STUDIO_SINGLEFRAME, as retail sets it; a descriptor without a clip keeps the
        // flags it was given (retail has them both with and without the bit)
        if (single && !s.animIndices.empty()) flags |= 0x80000;
        I(0x0C, flags);
        I(0x10, -1);  // activity, resolved at load time
        I(0x14, s.actWeight);
        F(0x20, s.bmin.x); F(0x24, s.bmin.y); F(0x28, s.bmin.z);
        F(0x2C, s.bmax.x); F(0x30, s.bmax.y); F(0x34, s.bmax.z);
        I(0x38, static_cast<int>(s.animIndices.size()));
        I(0x44, s.groupSize[0]);
        I(0x48, s.groupSize[1]);
        I(0x4C, s.paramIndex[0]);
        I(0x50, s.paramIndex[1]);
        F(0x54, s.paramStart[0]); F(0x58, s.paramStart[1]);
        // a standalone sequence asset stores end 1 on an axis without a pose parameter
        // (every unused axis of the 4,249 S3 assets; in-model descriptors store 0)
        for (int axis = 0; axis < 2; ++axis)
            F(0x5C + 4 * axis, standaloneSequence_ && s.paramIndex[axis] < 0 && !s.axisRange[axis] ? 1.f : s.paramEnd[axis]);
        F(0x68, s.fadeIn);
        F(0x6C, s.fadeOut);
        I(0x70, s.entryNode);
        I(0x74, s.exitNode);
        I(0x78, s.nodeFlags);
        F(0x7C, s.entryPhase);
        F(0x80, s.exitPhase);
        F(0x84, s.lastFrame);
        I(0x88, s.nextSeq);
        I(0x8C, s.pose);
        I(0x90, s.numIKRules);
        I(0xB4, s.cyclePose);
        I(0xC0, s.ikResetMask);
        I(0xC4, s.unkC4);
        // pose keys (blends only)
        if (!s.poseKeys.empty()) {
            I(0xA0, Rel(p));
            for (float k : s.poseKeys) b_.F32(k);
        }
        // events
        I(0x18, static_cast<int>(s.events.size()));
        I(0x1C, Rel(p));
        for (auto& e : s.events) {
            size_t q = b_.Tell();
            b_.F32(e.cycle);
            b_.I32(e.event);
            b_.I32(e.type);
            b_.FixedString(e.options, 256);
            b_.I32(0);
            if (e.type != 0) Str(q + 0x10C, q, e.name);
        }
        b_.Align(4);
        // autolayers
        // v54 layers name their sequence asset by GUID (local-index layers are refused)
        I(0x94, static_cast<int>(s.assetLayers.size()));
        I(0x98, Rel(p));
        for (auto& l : s.assetLayers) {
            b_.U32(static_cast<uint32_t>(l.guid));
            b_.U32(static_cast<uint32_t>(l.guid >> 32));
            b_.I16(static_cast<int16_t>(l.pose));
            b_.I16(0);
            b_.I32(l.flags);
            b_.F32(l.start);
            b_.F32(l.peak);
            b_.F32(l.tail);
            b_.F32(l.end);
        }
        // bone weights (shared with the previous sequence when identical)
        if (lastWeightVals && *lastWeightVals == s.weights) {
            I(0x9C, static_cast<int32_t>(lastWeights - p));
        } else {
            I(0x9C, Rel(p));
            lastWeights = b_.Tell();
            lastWeightVals = &s.weights;
            for (float w : s.weights) b_.F32(w);
        }
        // ik locks
        I(0xA4, static_cast<int>(s.ikLocks.size()));
        I(0xA8, Rel(p));
        for (auto& l : s.ikLocks) {
            b_.I32(l.chain);
            b_.F32(l.posWeight);
            b_.F32(l.localQWeight);
            b_.I32(l.flags);
        }
        b_.Align(4);
        // anim indices
        I(0x3C, Rel(p));
        for (int16_t ai : s.animIndices) {
            animationRefs_.push_back({b_.Tell(), p, ai});
            b_.I32(static_cast<int32_t>(animationBase_ + ai * kAnimDescSize) - static_cast<int32_t>(p));
        }
        if (s.animIndices.empty() && s.assetAnim >= 0) {
            // A reference descriptor (no counted blends) still holds one entry, read through
            // its 1x1 grid: its clip, inline right after the entry (every S0-S3 ref and
            // ragdoll descriptor). Without it R5R reads a descriptor from unrelated bytes.
            b_.I32(static_cast<int32_t>(b_.Tell() + 4 - p));  // sequence-relative
            size_t desc = b_.Reserve(kAnimDescSize);
            WriteAnimDesc(desc, m_.animations.at(s.assetAnim), true);
        }
        b_.Align(4);
        // keyvalues
        I(0xAC, Rel(p));
        if (!s.keyValues.empty()) {
            std::string kv = s.keyValues;
            b_.Bytes(kv.data(), kv.size());
            b_.U8(0);
            I(0xB0, static_cast<int>(kv.size() + 1));
            b_.Align(4);
        }
        // the 0xC8/0xCC table (unk_cc)
        if (!s.unkCC.empty()) {
            I(0xC8, Rel(p));
            I(0xCC, static_cast<int>(s.unkCC.size()));
            for (auto& r : s.unkCC) {
                b_.F32(r.value);
                b_.I32(r.bone);
                for (float x : r.ramp) b_.F32(x);
            }
        }
        // activity modifiers
        I(0xB8, Rel(p));
        I(0xBC, static_cast<int>(s.activityModifiers.size()));
        for (auto& am : s.activityModifiers) {
            size_t q = b_.Tell();
            b_.I32(0);
            Str(q, q, am.name);
            b_.U8(am.negate ? 1 : 0);
            b_.Zero(3);
        }
    }
}

void MdlWriter::WriteNodes() {
    HdrHere(H_LOCALNODENAMEINDEX);
    size_t names = b_.Reserve(4 * m_.nodeNames.size());
    for (size_t i = 0; i < m_.nodeNames.size(); i++) Str(names + i * 4, 0, m_.nodeNames[i]);
    // v54 stores the node names without a transition table: every S3 rig with nodes (62)
    // has index 0 (sequences keep their entry/exit nodes)
    Hdr(H_NUMLOCALNODES, static_cast<int>(m_.nodeNames.size()));
    Hdr(H_LOCALNODEUNK, m_.localNodeUnk);
    Hdr(H_LOCALNODEINDEX, 0);
}

void MdlWriter::WriteBodyParts() {
    HdrHere(H_BODYPARTINDEX);
    HdrHere(H_FLEXDESCINDEX);  // the empty flex-descriptor table sits here in retail
    Hdr(H_NUMBODYPARTS, static_cast<int>(m_.bodyParts.size()));
    size_t base = b_.Reserve(kBodyPartSize * m_.bodyParts.size());
    for (size_t i = 0; i < m_.bodyParts.size(); i++) {
        auto& bp = m_.bodyParts[i];
        size_t p = base + i * kBodyPartSize;
        Str(p, p, bp.name);
        b_.PatchI32(p + 4, static_cast<int>(bp.models.size()));
        b_.PatchI32(p + 8, bp.base);
        b_.PatchI32(p + 12, Rel(p));
        size_t mbase = b_.Reserve(kModelSize * bp.models.size());
        for (size_t mi = 0; mi < bp.models.size(); mi++) {
            auto& md = bp.models[mi];
            size_t q = mbase + mi * kModelSize;
            std::string nm = md.name;
            if (nm.size() > 64) nm = nm.substr(nm.size() - 64);
            std::memcpy(&b_.Data()[q], nm.data(), nm.size());
            b_.PatchAt<float>(q + 0x48, md.boundingRadius);
            b_.PatchI32(q + 0x4C, static_cast<int>(md.meshes.size()));
            b_.PatchI32(q + 0x54, md.NumVerts());
            b_.PatchI32(q + 0x58, md.vertexStart * 48);
            b_.PatchI32(q + 0x5C, md.vertexStart * 16);
            b_.PatchI32(q + 0x80, md.vertexStart * 4);
            b_.PatchI32(q + 0x84, md.vertexStart * 8);
        }
        for (size_t mi = 0; mi < bp.models.size(); mi++) {
            auto& md = bp.models[mi];
            size_t q = mbase + mi * kModelSize;
            b_.PatchI32(q + 0x50, Rel(q));
            int voff = 0;
            for (auto& me : md.meshes) {
                size_t r = b_.Tell();
                if (b_.ReadAt<int32_t>(0x110) == 0) b_.PatchI32(0x110, static_cast<int32_t>(r));
                b_.I32(me.material);
                b_.I32(static_cast<int32_t>(q) - static_cast<int32_t>(r));
                b_.I32(static_cast<int>(me.verts.size()));
                b_.I32(voff);
                b_.Zero(16);  // flexes, material type/param
                b_.I32(me.meshId);
                b_.V3(me.center);
                b_.I32(0);  // modelvertexdata (runtime)
                for (int l = 0; l < kMaxLods; l++) b_.I32(me.lodVertexCount[l]);
                b_.Zero(8);   // runtime pointer
                voff += static_cast<int>(me.verts.size());
            }
        }
    }
    // Deprecated flex offsets.
    HdrHere(H_FLEXCONTROLLERINDEX);
    HdrHere(H_FLEXRULEINDEX);
    HdrHere(H_FLEXCONTROLLERUIINDEX);
}

void MdlWriter::WriteIK() {
    HdrHere(H_IKCHAININDEX);
    Hdr(H_NUMIKCHAINS, static_cast<int>(m_.ikChains.size()));
    size_t base = b_.Reserve(kIKChainSize * m_.ikChains.size());
    for (size_t i = 0; i < m_.ikChains.size(); i++) {
        auto& c = m_.ikChains[i];
        size_t p = base + i * kIKChainSize;
        Str(p, p, c.name);
        b_.PatchI32(p + 4, c.linkType);
        b_.PatchI32(p + 8, static_cast<int>(c.links.size()));
        b_.PatchAt<float>(p + 0x10, c.unk);
    }
    for (size_t i = 0; i < m_.ikChains.size(); i++) {
        size_t p = base + i * kIKChainSize;
        b_.PatchI32(p + 12, Rel(p));
        for (auto& l : m_.ikChains[i].links) {
            b_.I32(l.bone);
            b_.V3(l.kneeDir);
        }
    }
}

void MdlWriter::WritePoseParams() {
    HdrHere(H_LOCALPOSEPARAMINDEX);
    Hdr(H_NUMLOCALPOSEPARAMETERS, static_cast<int>(m_.poseParams.size()));
    for (auto& pp : m_.poseParams) {
        size_t p = b_.Tell();
        b_.I32(0);
        Str(p, p, pp.name);
        b_.I32(pp.flags);
        b_.F32(pp.start);
        b_.F32(pp.end);
        b_.F32(pp.loop);
    }
    HdrHere(H_LOCALIKAUTOPLAYLOCKINDEX);
    Hdr(H_NUMLOCALIKAUTOPLAYLOCKS, static_cast<int>(m_.ikAutoplayLocks.size()));
    for (auto& l : m_.ikAutoplayLocks) {
        b_.I32(l.chain);
        b_.F32(l.posWeight);
        b_.F32(l.localQWeight);
        b_.I32(l.flags);
    }
}

void MdlWriter::WriteIncludeModels() {
    // RUI panel meshes come first: header array (hash, offset), then each mesh 16-byte
    // aligned. MDL v54 mesh (all 6,621 S0-S3 retail panels): uint16 parent, vertex,
    // face and mask counts; int32 parent, vertex, mask, face and bounds offsets; the
    // name at +28; then, packed back from the 16-aligned vertices: parents (int16),
    // faces (3 x int16), one uint16 mask per face; vertices (int parent slot, vec3);
    // bounds (8 floats per face).
    b_.Align(4);
    size_t panelStart = b_.Tell();
    HdrHere(H_UIPANELOFFSET);
    Hdr(H_UIPANELCOUNT, static_cast<int>(m_.uiPanels.size()));
    size_t headers = b_.Reserve(8 * m_.uiPanels.size());
    for (size_t i = 0; i < m_.uiPanels.size(); i++) {
        const CUIPanel& p = m_.uiPanels[i];
        b_.Align(16);
        size_t mesh = b_.Tell();
        b_.PatchAt<uint32_t>(headers + i * 8, p.hash);
        b_.PatchI32(headers + i * 8 + 4, static_cast<int32_t>(mesh - (headers + i * 8)));
        int pc = static_cast<int>(p.parents.size()), vc = static_cast<int>(p.vertices.size());
        int fc = static_cast<int>(p.faces.size());
        int vo = static_cast<int>((28 + p.name.size() + 1 + 2 * pc + 6 * fc + 2 * fc + 15) & ~size_t(15));
        int xo = vo - 2 * fc, io = xo - 6 * fc, po = io - 2 * pc, bo = vo + 16 * vc;
        for (int v : {pc, vc, fc, p.maskCount}) b_.U16(static_cast<uint16_t>(v));
        for (int v : {po, vo, xo, io, bo}) b_.I32(v);
        for (char c : p.name) b_.U8(static_cast<uint8_t>(c));
        b_.U8(0);
        while (b_.Tell() < mesh + po) b_.U8(0);
        for (int bone : p.parents) b_.I16(static_cast<int16_t>(bone));
        for (auto& f : p.faces)
            for (int16_t v : f) b_.I16(v);
        for (uint16_t m : p.faceMasks) b_.U16(m);
        while (b_.Tell() < mesh + vo) b_.U8(0);
        for (auto& v : p.vertices) {
            b_.I32(v.first);
            b_.V3(v.second);
        }
        for (auto& bd : p.bounds)
            for (float f : bd) b_.F32(f);
    }
    // retail models (which have no include models) point the include index at the panels
    if (m_.includeModels.empty()) {
        b_.PatchI32(H_INCLUDEMODELINDEX, static_cast<int32_t>(panelStart));
        // -1 tells the RPak loader to construct the virtual rig from asset
        // references. Zero leaves it absent, which crashes native IK playback.
        Hdr(H_NUMINCLUDEMODELS, m_.externalAssetRig ? -1 : 0);
        return;
    }
    b_.Align(8);
    HdrHere(H_INCLUDEMODELINDEX);
    Hdr(H_NUMINCLUDEMODELS, static_cast<int>(m_.includeModels.size()));
    for (auto& im : m_.includeModels) {
        size_t p = b_.Tell();
        b_.I32(0);
        b_.I32(0);
        Str(p, p, "");
        Str(p + 4, p, im);
    }
}

void MdlWriter::WriteTextures() {
    HdrHere(H_TEXTUREINDEX);
    Hdr(H_NUMTEXTURES, static_cast<int>(m_.textures.size()));
    for (auto& t : m_.textures) {
        size_t p = b_.Tell();
        b_.Zero(kTextureSize);
        Str(p, p, t);
    }
    b_.Align(4);
    if (!m_.materialTypes.empty()) {
        if (m_.materialTypes.size()!=m_.textures.size()) Fatal("material type count does not match texture slots");
        HdrHere(0xCC);
        for (uint8_t type : m_.materialTypes) b_.U8(type);
        b_.Align(4);
    }
    HdrHere(H_CDTEXTUREINDEX);
    Hdr(H_NUMCDTEXTURES, static_cast<int>(m_.cdTextures.size()));
    size_t cd = b_.Reserve(4 * m_.cdTextures.size());
    for (size_t i = 0; i < m_.cdTextures.size(); i++) Str(cd + i * 4, 0, m_.cdTextures[i]);
    HdrHere(H_SKININDEX);
    Hdr(H_NUMSKINREF, m_.numSkinRef);
    Hdr(H_NUMSKINFAMILIES, static_cast<int>(m_.skins.size()));
    for (auto& fam : m_.skins)
        for (int16_t v : fam) b_.I16(v);
    // Apex names every family after the first: int32 string offsets after the table
    // (all S0-S3 models; an unnamed family points at an empty string)
    if (m_.skins.size() > 1) {
        b_.Align(4);
        size_t names = b_.Reserve(4 * (m_.skins.size() - 1));
        for (size_t f = 1; f < m_.skins.size(); f++)
            Str(names + 4 * (f - 1), 0, f - 1 < m_.skinNames.size() ? m_.skinNames[f - 1] : std::string());
    }
    b_.Align(4);
}

void MdlWriter::WriteKeyValues() {
    HdrHere(H_KEYVALUEINDEX);
    if (!m_.keyValues.empty()) {
        const std::string& kv = m_.keyValues;  // compact "mdlkeyvalue{...}" text (ApexKeyValues)
        b_.Bytes(kv.data(), kv.size());
        b_.U8(0);
        b_.U8(0);  // retail stores two NULs: size = length + 2 in all S0-S3 models
        Hdr(H_KEYVALUESIZE, static_cast<int>(kv.size() + 2));
    }
    b_.Align(4);
    HdrHere(H_SRCBONETRANSFORMINDEX);
    Hdr(H_NUMSRCBONETRANSFORM, static_cast<int>(m_.srcBoneTransforms.size()));
    for (auto& t : m_.srcBoneTransforms) {
        size_t p = b_.Tell();
        b_.I32(0);
        Str(p, p, t.bone);
        for (float v : t.pre) b_.F32(v);
        for (float v : t.post) b_.F32(v);
    }
}

// Linear bones (0x194): in every multi-bone retail model (677 S0/S3 models), never in a
// rig. v54 layout: count and six offsets (relative to the table) to the bone flags,
// parents, positions, quaternions, Euler rotations and pose-to-bone matrices, each a
// copy of the bone records; no TF2 scale or alignment arrays. It sits right before the
// string table.
void MdlWriter::WriteLinearBones() {
    size_t nb = m_.bones.size();
    if (nb <= 1 || m_.rigAsset) return;
    b_.Align(4);
    size_t p = b_.Tell();
    HdrHere(H_LINEARBONEINDEX);
    b_.Reserve(0x1C);
    b_.PatchI32(p, static_cast<int>(nb));
    b_.PatchI32(p + 0x04, Rel(p));
    for (auto& bn : m_.bones) b_.I32(bn.flags & ~BONE_USED_BY_BONE_MERGE);
    b_.PatchI32(p + 0x08, Rel(p));
    for (auto& bn : m_.bones) b_.I32(bn.parent);
    b_.PatchI32(p + 0x0C, Rel(p));
    for (auto& bn : m_.bones) b_.V3(bn.pos);
    b_.PatchI32(p + 0x10, Rel(p));
    for (auto& bn : m_.bones) b_.Q(bn.quat);
    b_.PatchI32(p + 0x14, Rel(p));
    for (auto& bn : m_.bones) b_.RE(bn.rot);
    b_.PatchI32(p + 0x18, Rel(p));
    for (auto& bn : m_.bones) b_.M34(bn.poseToBone);
}

void MdlWriter::WritePerTri() {
    b_.Align(4);
    HdrHere(H_PERTRIINDEX);
    const CPerTri& pt = m_.perTri;
    b_.I32(pt.version);
    b_.V3(pt.bmin);
    b_.V3(pt.bmax);
    b_.Zero(32);
    b_.Append(pt.data);
    Hdr(H_PERTRINODECOUNT, pt.nodeCount);
    Hdr(H_PERTRILEAFCOUNT, pt.leafCount);
    Hdr(H_PERTRIVERTCOUNT, pt.vertCount);
    b_.Align(4);
}

std::vector<uint8_t> MdlWriter::RunSequence() {
    standaloneSequence_ = true;
    WriteSequences();
    WriteAnimations();
    for (const auto& ref : animationRefs_)
        b_.PatchI32(ref.field, static_cast<int32_t>(animationBase_ + ref.index * kAnimDescSize) - static_cast<int32_t>(ref.sequence));
    st_.Write(b_);
    b_.Align(4);
    return b_.Data();
}

std::vector<uint8_t> MdlWriter::Run() {
    WriteHeader();
    WriteSourceFiles();
    WriteBones();
    WriteAttachments();
    WriteHitboxes();
    WriteBoneTable();
    WriteAnimations();
    WriteSequences();
    WriteNodes();
    WriteBodyParts();
    WriteIK();
    WritePoseParams();
    WriteIncludeModels();
    WriteTextures();
    WriteKeyValues();
    WriteLinearBones();
    st_.Write(b_);
    b_.Align(4);

    // BVH collision (0x214) on a 64-byte boundary, as retail places it. 0x1F0 holds the
    // hull box, extended to the origin when a BVH is present; 0x218 names the physics-
    // hull and trace entries ((0, 0) without a BVH). Measured on 1,789 S0-S3 models.
    Vec3 boxMin = m_.hullMin, boxMax = m_.hullMax;
    if (!m_.bvh.block.empty()) {
        b_.Align(64);
        HdrHere(0x214);
        b_.Append(m_.bvh.block);
        boxMin = Min(boxMin, Vec3(0, 0, 0));
        boxMax = Max(boxMax, Vec3(0, 0, 0));
        b_.PatchAt<int16_t>(0x218, static_cast<int16_t>(m_.bvh.hullEntry));
        b_.PatchAt<int16_t>(0x21A, static_cast<int16_t>(m_.bvh.traceEntry));
    }
    for (int a = 0; a < 3; a++) {
        b_.PatchAt<float>(0x1F0 + 4 * a, boxMin[a]);
        b_.PatchAt<float>(0x1FC + 4 * a, boxMax[a]);
    }

    // checksum over the model body, studiomdl style (shift-add over dwords)
    uint32_t ck = 0;
    for (size_t i = 0; i + 4 <= b_.Size(); i += 4) {
        uint32_t v = b_.ReadAt<uint32_t>(i);
        ck = (ck << 1) + ((ck & 0x8000000) ? 1 : 0) + v;
    }
    int32_t checksum = static_cast<int32_t>(ck);
    Hdr(H_CHECKSUM, checksum);

    size_t componentOffset = 0;
    bool hasMesh = false;
    for (auto& bp : m_.bodyParts) for (auto& md : bp.models)
        if (!md.meshes.empty()) hasMesh = true;
    if (hasMesh) {
        auto vtx = WriteVTX(m_, checksum);
        Hdr(H_VTXOFFSET, -1);
        Hdr(H_VTXSIZE, static_cast<int>(vtx.size()));
        componentOffset += vtx.size();
        auto vvd = WriteVVD(m_, checksum);
        Hdr(H_VVDOFFSET, static_cast<int>(componentOffset));
        Hdr(H_VVDSIZE, static_cast<int>(vvd.size()));
        componentOffset += vvd.size();
        if (m_.hasVertexColor || m_.hasUV2) {
            auto vvc = WriteVVC(m_, checksum);
            Hdr(H_VVCOFFSET, static_cast<int>(componentOffset));
            Hdr(H_VVCSIZE, static_cast<int>(vvc.size()));
            componentOffset += vvc.size();
        }
        if(m_.HasComplexWeights()) {
            auto vvw=WriteVVW(m_,checksum);
            Hdr(0x21C,static_cast<int>(componentOffset));
            Hdr(0x220,static_cast<int>(vvw.size()));
        }
    }
    if (m_.physics.apexPhySize > 0) {
        // retail stores this sentinel offset and the PHY file's size
        Hdr(H_PHYOFFSET, -123456);
        Hdr(H_PHYSIZE, m_.physics.apexPhySize);
    }
    // no bone followers: retail points their (empty) table at the end of the file
    Hdr(H_BONEFOLLOWEROFFSET, static_cast<int>(b_.Size()));
    Hdr(H_LENGTH, static_cast<int>(b_.Size()));
    return b_.Data();
}

}  // namespace

std::vector<uint8_t> WriteMDL(const CompiledModel& m, bool vertexGroup) { return MdlWriter(m, vertexGroup).Run(); }

std::vector<uint8_t> WriteSequence54(const CompiledModel& model, size_t index) {
    if (index >= model.sequences.size()) Fatal("sequence index outside model");
    CompiledModel subset;
    subset.sequences.push_back(model.sequences[index]);
    // a referencepose sequence's asset carries its bind-pose clip
    if (subset.sequences[0].animIndices.empty() && subset.sequences[0].assetAnim >= 0)
        subset.sequences[0].animIndices = {static_cast<int16_t>(subset.sequences[0].assetAnim)};
    std::map<int, int> indices;
    for (auto& ai : subset.sequences[0].animIndices) {
        auto found = indices.find(ai);
        if (found == indices.end()) {
            int mapped = static_cast<int>(subset.animations.size());
            indices.emplace(ai, mapped);
            subset.animations.push_back(model.animations.at(ai));
            ai = static_cast<int16_t>(mapped);
        } else ai = static_cast<int16_t>(found->second);
    }
    // A standalone sequence carries 0x40000 exactly when its clips have frame movement
    // (all 4,249 retail S3 sequence assets); sequences inside models never do.
    bool movement = !subset.animations.empty();
    for (const auto& a : subset.animations)
        if (!(a.flags & 0x40000)) movement = false;
    if (movement) subset.sequences[0].flags |= 0x40000;
    return MdlWriter(subset, false).RunSequence();
}

std::vector<uint8_t> WriteRig54(const CompiledModel& model) {
    CompiledModel rig;
    rig.name = std::filesystem::path(model.name).replace_extension().u8string() + ".rrig";
    rig.rigAsset = true;
    rig.bones = model.bones;
    // Retail rigs carry no procedural bones: the jiggle records stay in the model, and
    // the rig's copies of those bones have no procedure or always-procedural flag (all
    // 10 S3 rigs paired with jiggle models). R5R leaves a rig-side jiggle bone unposed.
    for (auto& bone : rig.bones) {
        if (bone.jiggle >= 0 || bone.proctype) bone.flags &= 0x20;
        bone.proctype = 0;
        bone.jiggle = -1;
    }
    rig.attachments = model.attachments;
    rig.hitboxSets = model.hitboxSets;
    rig.ikChains = model.ikChains;
    rig.poseParams = model.poseParams;
    // the rig owns the transition node names its sequence assets refer to (62 S3 rigs)
    rig.nodeNames = model.nodeNames;
    rig.localNodeUnk = model.localNodeUnk;
    rig.surfaceProp = model.surfaceProp;
    rig.sourceFiles = model.sourceFiles;
    return WriteMDL(rig, true);
}

}  // namespace r2c
