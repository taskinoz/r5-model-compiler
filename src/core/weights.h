#pragma once
#include <array>
#include <cstdint>

namespace r2c {
constexpr int kMaxWeightsPerVertex = 16;
// Native packed weights store (normalized units - 1), where 32768 units = 1.
// Apportion the rounding remainder without changing the normalized sum.
std::array<int16_t, kMaxWeightsPerVertex> PackWeights(const float* weights, int count);
}
