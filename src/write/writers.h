// Early Apex studio data and season-specific companion buffers.
#pragma once

#include <cstdint>
#include <vector>

#include "build/compiled.h"

namespace r2c {

std::vector<uint8_t> WriteVVD(const CompiledModel& m, int checksum);
std::vector<uint8_t> WriteVVC(const CompiledModel& m, int checksum);
std::vector<uint8_t> WriteVVW(const CompiledModel& m, int checksum);
std::vector<uint8_t> WriteVTX(const CompiledModel& m, int checksum);
// Native v54 studio data, excluding render/physics components.
std::vector<uint8_t> WriteMDL(const CompiledModel& m, bool vertexGroup = false);
std::vector<uint8_t> WriteVG(const CompiledModel& m);

}  // namespace r2c
