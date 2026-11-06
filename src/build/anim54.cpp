// Independent early Apex animation encoder. Raw (mode 0) native tracks retain
// signed 16-bit samples; the format is distinct from Source valid/total RLE.
#include "build/anim54.h"
#include "core/buffer.h"
#include "core/log.h"
#include <algorithm>
#include <cmath>

namespace r2c {
namespace {
constexpr float rotationStep = 0.00019175345f;
constexpr float scaleStep = 0.0030518509f;

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
        float positionStep = 1.f / 32768.f;
        for (int f = first; f <= last; ++f)
            for (int axis = 0; axis < 3; ++axis) {
                float v = a.sanim[f][j].pos[axis] - (delta ? 0.f : ctx.bones[j].pos[axis]);
                positionStep = std::max(positionStep, std::fabs(v) / 32767.f);
            }
        if (positionStep / 2 > .01f) Fatal("v54 animation position exceeds 0.01-inch quantization budget");
        b.F32(positionStep);
        size_t pos = b.Reserve(4), rot = b.Reserve(4), scale = b.Reserve(4);
        auto track = [&](size_t ptr, int kind, float step) {
            size_t data = b.Tell();
            if (data - ptr > 8191) Fatal("v54 track offset overflow");
            b.PatchAt<uint16_t>(ptr, uint16_t((7 << 13) | (data - ptr)));
            for (int axis = 0; axis < 3; ++axis) {
                size_t words = (b.Tell() - data) / 2;
                if (words > 255) Fatal("v54 axis offset overflow");
                if (axis) b.PatchAt<uint8_t>(ptr + 1 + axis, uint8_t(words));
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
        track(pos, 0, positionStep);
        track(rot, 1, rotationStep);
        track(scale, 2, scaleStep);
        size_t size = b.Tell() - record;
        if (size > 8191) Fatal("v54 animation bone record overflow");
        b.PatchAt<uint16_t>(record, uint16_t((7 << 13) | size));
    }
    b.Align(4);
    return b.Data();
}
}
void EncodeNative54(const BuildContext& ctx, const WAnim& a, CAnimation& out) {
    constexpr int sectionFrames = 30;
    if (a.numFrames <= sectionFrames) {
        out.nativeSections.push_back(Section(ctx, a, 0, a.numFrames-1));
    } else {
        out.sectionFrames = sectionFrames;
        for (int first = 0; first < a.numFrames; first += sectionFrames)
            out.nativeSections.push_back(Section(ctx, a, first, std::min(first + sectionFrames, a.numFrames-1)));
        out.nativeSections.push_back(Section(ctx, a, a.numFrames-1, a.numFrames-1));
    }
}
}
