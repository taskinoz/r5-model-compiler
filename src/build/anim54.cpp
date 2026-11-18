// Independent early Apex animation encoder. Raw (mode 0) native tracks retain
// signed 16-bit samples; the format is distinct from Source valid/total RLE.
#include "build/anim54.h"
#include "build/frame54.h"
#include "core/buffer.h"
#include "core/log.h"
#include "core/strings.h"
#include <algorithm>
#include <cmath>
#include <cstring>

namespace r2c {
namespace {
constexpr float rotationStep = 0.00019175345f;
constexpr float scaleStep = 0.0030518509f;

// IEEE half precision, rounding to nearest even (finite inputs; overflow saturates to inf)
uint16_t FloatToHalf(float value) {
    uint32_t f;
    std::memcpy(&f, &value, 4);
    uint32_t sign = (f >> 16) & 0x8000, mag = f & 0x7FFFFFFF;
    if (mag >= 0x477FF000) return uint16_t(sign | 0x7C00);  // beyond the largest half
    if (mag < 0x38800000) {                                  // subnormal half
        float a = std::fabs(value) * 16777216.f;            // units of 2^-24
        return uint16_t(sign | static_cast<uint32_t>(std::nearbyint(a)));
    }
    uint32_t h = ((mag - 0x38000000) >> 13), rest = mag & 0x1FFF;
    if (rest > 0x1000 || (rest == 0x1000 && (h & 1))) h++;
    return uint16_t(sign | h);
}

float HalfToFloat(uint16_t h) {
    int e = (h >> 10) & 31, m = h & 1023;
    float v = e == 0 ? std::ldexp(static_cast<float>(m), -24) : std::ldexp(static_cast<float>(m | 1024), e - 25);
    return (h & 0x8000) ? -v : v;
}

std::vector<uint8_t> Section(const BuildContext& ctx, const WAnim& a, int first, int last) {
    Buffer b;
    size_t maskBytes = ((ctx.bones.size() + 1) / 2 + 1) & ~size_t(1);
    b.Reserve(maskBytes);
    const bool delta = (a.flags & 4) != 0;
    const int count = last - first + 1;
    for (size_t j = 0; j < ctx.bones.size(); ++j) {
        // Explicit channels avoid ambiguities about absent channels in deltas.
        b.Data()[j/2] |= uint8_t(7 << (4*(j%2)));
        size_t record = b.Reserve(2);
        // studiomdl's position scale with a 128-inch floor: the larger side of the section's
        // offsets (at least -128..128) over 32768 (negative) or 32767 (positive). 9,121 of
        // 9,128 sampled S3 tracks store 128/32767; the rest exceed 128 inches.
        // Retail-derived clips (imports, decompiles) lie on that grid and keep it exactly;
        // other clips use the finest step their range allows, as before.
        float minOffset = -128.f, maxOffset = 128.f, maxAbs = 0.f;
        for (int f = first; f <= last; ++f)
            for (int axis = 0; axis < 3; ++axis) {
                float v = a.sanim[f][j].pos[axis] - (delta ? 0.f : ctx.bones[j].pos[axis]);
                minOffset = std::min(minOffset, v);
                maxOffset = std::max(maxOffset, v);
                maxAbs = std::max(maxAbs, std::fabs(v));
            }
        const float retailStep = -minOffset > maxOffset ? -minOffset / 32768.f : maxOffset / 32767.f;
        bool onRetailGrid = true;
        for (int f = first; f <= last && onRetailGrid; ++f)
            for (int axis = 0; axis < 3; ++axis) {
                float v = a.sanim[f][j].pos[axis] - (delta ? 0.f : ctx.bones[j].pos[axis]);
                // 1% of a step: float32 transforms of values near 128 inches move them by
                // up to ~1e-5, and authored values rarely all land this close to the grid
                if (std::fabs(v - std::round(v / retailStep) * retailStep) > retailStep * 1e-2f) { onRetailGrid = false; break; }
            }
        const float positionStep = onRetailGrid ? retailStep : std::max(1.f / 32768.f, maxAbs / 32767.f);
        // A constant position may instead be stored as three absolute half floats (mode bit
        // 4 clear), as retail stores them: used when no less accurate than the track (exact
        // for retail-derived values on either grid, e.g. empty_lights' ref clip at 179 inches).
        bool constant = true;
        float halfError = 0, trackError = 0;
        uint16_t halves[3] = {};
        for (int axis = 0; axis < 3; ++axis) {
            float v0 = a.sanim[first][j].pos[axis];
            for (int f = first + 1; f <= last; ++f)
                if (a.sanim[f][j].pos[axis] != v0) constant = false;
            halves[axis] = FloatToHalf(v0);
            halfError = std::max(halfError, std::fabs(HalfToFloat(halves[axis]) - v0));
            float offset = v0 - (delta ? 0.f : ctx.bones[j].pos[axis]);
            float stored = (delta ? 0.f : ctx.bones[j].pos[axis]) + std::round(offset / positionStep) * positionStep;
            trackError = std::max(trackError, std::fabs(stored - v0));
        }
        size_t pos = SIZE_MAX;
        if (constant && (onRetailGrid ? halfError <= trackError : halfError <= positionStep / 2)) {
            for (uint16_t h : halves) b.U16(h);
        } else {
            if (positionStep / 2 > .01f) Fatal("v54 animation position exceeds 0.01-inch quantization budget");
            b.F32(positionStep);
            pos = b.Reserve(4);
        }
        size_t rot = b.Reserve(4), scale = b.Reserve(4);
        auto track = [&](size_t ptr, int kind, float step) {
            size_t data = b.Tell();
            if (data - ptr > 8191) Fatal("v54 track offset overflow");
            b.PatchAt<uint16_t>(ptr, uint16_t((7 << 13) | (data - ptr)));
            for (int axis = 0; axis < 3; ++axis) {
                size_t words = (b.Tell() - data) / 2;
                if (words > 255) Fatal("v54 axis offset overflow");
                if (axis) b.PatchAt<uint8_t>(ptr + 1 + axis, uint8_t(words));
                if (count + 1 > 255) Fatal("v54 animation section exceeds 254 frames; set sectionframes");
                b.U8(0); b.U8(uint8_t(count + 1));
                for (int f = first; f <= last + 1; ++f) {
                    const auto& xf = a.sanim[std::min(f, last)][j];
                    float value = 0;
                    if (kind == 0) value = xf.pos[axis] - (delta ? 0.f : ctx.bones[j].pos[axis]);
                    if (kind == 1) {
                        value = xf.rot[axis];
                        while (value >= kPi) value -= 2*kPi;
                        while (value < -kPi) value += 2*kPi;
                    }
                    if (kind == 2) value = xf.scale[axis] - (delta ? 0.f : ctx.bones[j].scale[axis]);
                    float q = std::round(value / step);
                    if (!std::isfinite(q) || q < -32768 || q > 32767)
                        Fatal("v54 animation sample exceeds native channel range");
                    b.I16(int16_t(q));
                }
            }
        };
        if (pos != SIZE_MAX) track(pos, 0, positionStep);
        track(rot, 1, rotationStep);
        track(scale, 2, scaleStep);
        size_t size = b.Tell() - record;
        if (size > 8191) Fatal("v54 animation bone record overflow");
        // modes: 4 position track (else constant halves), 2 rotation track, 1 scale track
        b.PatchAt<uint16_t>(record, uint16_t(((pos != SIZE_MAX ? 7 : 3) << 13) | size));
    }
    b.Align(4);
    return b.Data();
}
}
void EncodeNative54(const BuildContext& ctx, const WAnim& a, CAnimation& out) {
    // an imported clip's retail sections, while the import still describes this clip
    if (a.qc && !a.qc->nativeStream.empty() && a.qc->nativeStreamCurrent) {
        uint64_t bones = 0xcbf29ce484222325ull;
        for (size_t j = 0; j < ctx.bones.size(); ++j) {
            if (j) bones = Fnv1a64("\n", 1, bones);
            bones = Fnv1a64(ctx.bones[j].name.data(), ctx.bones[j].name.size(), bones);
        }
        const int sf = a.qc->nativeStreamSectionFrames;
        const size_t expected = sf ? static_cast<size_t>((a.numFrames - 1) / sf + 2) : 1;
        if (a.qc->nativeStreamFrames == a.numFrames && a.qc->nativeStreamBones == static_cast<int>(ctx.bones.size()) &&
            a.qc->nativeStreamBoneHash == bones && a.qc->nativeStream.size() == expected &&
            (a.qc->sectionFrames < 0 || a.qc->sectionFrames == sf)) {
            out.nativeSections = a.qc->nativeStream;
            if (sf) out.sectionFrames = sf;
            return;
        }
        Warn("%s: its native stream does not match this model's bones or frames; re-encoding it", a.name.c_str());
    }
    // frames per section: the animation's `sectionframes` (0 = one section), else retail's rule
    const int sectionFrames = a.qc && a.qc->sectionFrames >= 0 ? a.qc->sectionFrames : RetailSectionFrames54(a.numFrames, true);
    if (sectionFrames == 0 || a.numFrames <= sectionFrames) {
        out.nativeSections.push_back(Section(ctx, a, 0, a.numFrames-1));
    } else {
        out.sectionFrames = sectionFrames;
        for (int first = 0; first < a.numFrames; first += sectionFrames)
            out.nativeSections.push_back(Section(ctx, a, first, std::min(first + sectionFrames, a.numFrames-1)));
        out.nativeSections.push_back(Section(ctx, a, a.numFrames-1, a.numFrames-1));
    }
}
}
