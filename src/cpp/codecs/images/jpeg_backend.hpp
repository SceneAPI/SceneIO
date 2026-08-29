#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "records/image.hpp"

namespace sio::jpeg_backend {

inline constexpr uint64_t kPixelCap = 250000000ull;

void guard_dimensions(size_t width, size_t height);

Image decode_with_stb(const uint8_t *data, size_t size);
Image decode(const uint8_t *data, size_t size);
std::string encode(const Image &image, int quality);

}  // namespace sio::jpeg_backend
