#pragma once
#include "core/math.h"
#include <cstdint>
#include <vector>
namespace r2c {
Vec4 NativeFrameScales54(const std::vector<Vec4>& frames);
// Retail's frames per native section: (frames + 32) / 64 sections of equal length
// (rounded up), one section when that is 1. A clip also stays whole up to 96 frames;
// its frame movement does not (96 frames: two sections of 48). Fits all 4,249 retail
// S3 sequence assets (4,172 clips). Returns 0 for one section.
int RetailSectionFrames54(int frames, bool clip);
// sectionFrames: frames per section, 0 = one section (stored as the frame count)
std::vector<uint8_t> EncodeFrameMovement54(const std::vector<Vec4>& frames, const Vec4& scales, int sectionFrames);
void ValidateFrameMovement54(const std::vector<uint8_t>& data, int frames);
}
