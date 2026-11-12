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
std::vector<uint8_t> WriteSequence54(const CompiledModel& m, size_t sequence);
std::vector<uint8_t> WriteRig54(const CompiledModel& m);
std::vector<uint8_t> WriteVG(const CompiledModel& m);
// Early-Apex PHY; S3 edges also store their two faces.
std::vector<uint8_t> WritePHY54(const CPhysics& p, bool edgeFaces, int checksum);

}  // namespace r2c
