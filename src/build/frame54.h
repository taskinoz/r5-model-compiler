#pragma once
#include "core/math.h"
#include <cstdint>
#include <vector>
namespace r2c {
Vec4 NativeFrameScales54(const std::vector<Vec4>& frames);
std::vector<uint8_t> EncodeFrameMovement54(const std::vector<Vec4>& frames, const Vec4& scales);
void ValidateFrameMovement54(const std::vector<uint8_t>& data, int frames);
}
