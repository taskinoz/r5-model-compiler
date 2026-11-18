// Small string and path helpers.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace r2c {

std::string ToLower(std::string s);
bool IEquals(const std::string& a, const std::string& b);
std::string Trim(const std::string& s);
std::string StripExtension(const std::string& s);
std::string GetExtension(const std::string& s);  // without the dot
std::string FileBase(const std::string& s);      // file name without directory or extension
std::string DirName(const std::string& s);       // directory with trailing separator, or ""
std::string JoinPath(const std::string& a, const std::string& b);
std::string FixSlashes(std::string s, char sep = '/');
bool FileExists(const std::string& p);
bool StartsWithI(const std::string& s, const std::string& prefix);
bool EndsWithI(const std::string& s, const std::string& suffix);
std::vector<std::string> Split(const std::string& s, char c);
// 64-bit FNV-1a: identifies a source file or bone list (not a security hash)
inline uint64_t Fnv1a64(const void* data, size_t size, uint64_t h = 0xcbf29ce484222325ull) {
    const auto* p = static_cast<const unsigned char*>(data);
    for (size_t i = 0; i < size; ++i) { h ^= p[i]; h *= 0x100000001b3ull; }
    return h;
}
// RTech asset GUID of an asset path ("animseq/.../x.rseq"): letters fold to upper case
// and '\\' to '/', four bytes at a time. Resolves 208 of the 292 autolayer GUIDs in the S3
// sequence assets to their extracted sequences (the rest name assets not extracted).
inline uint64_t AssetGuid(const std::string& path) {
    std::string d = path;
    d.append(8, '\0');
    auto word = [&](size_t p) { uint32_t w; std::memcpy(&w, d.data() + p, 4); return w; };
    auto fold = [](uint32_t w) {
        uint32_t x = w ^ 0x5C5C5C5Cu;
        uint32_t backslash = (~x >> 7) & ((x - 0x01010101u) >> 7) & 0x01010101u;
        return (w - 45u * backslash) & 0xDFDFDFDFu;
    };
    uint64_t h = 0;
    uint32_t length = 0;
    size_t pos = 0;
    uint32_t w = word(0), folded = fold(w);
    uint32_t zero = ~w & (w - 0x01010101u) & 0x80808080u;
    while (!zero) {
        uint64_t mixed = (0xFB8C4D96501ull * folded) >> 24;
        h = mixed + 0x633D5F1ull * h;
        h = (h >> 61) ^ h;
        pos += 4;
        length += 4;
        if (pos + 4 > d.size()) d.append(4, '\0');
        w = word(pos);
        folded = fold(w);
        zero = ~w & (w - 0x01010101u) & 0x80808080u;
    }
    uint32_t below = (zero & (0u - zero)) - 1u;
    int top = -1;
    for (int b = 31; b >= 0; --b)
        if (below >> b & 1) { top = b; break; }
    uint64_t tail = (0xFB8C4D96501ull * (folded & below)) >> 24;
    return 0x633D5F1ull * h + tail - 0xAE502812AA7333ull * static_cast<uint32_t>(length + top / 8);
}

}  // namespace r2c
