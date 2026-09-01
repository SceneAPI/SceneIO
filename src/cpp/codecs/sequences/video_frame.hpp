// codecs/sequences/video_frame.hpp -- shared decoded-video frame mechanics.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

#include <aom/aom_image.h>

namespace sio::video {

inline std::string aom_matrix_name(
    aom_matrix_coefficients_t value, const char *context) {
    switch (value) {
        case AOM_CICP_MC_BT_709: return "bt709";
        case AOM_CICP_MC_BT_601:
        case AOM_CICP_MC_BT_470_B_G:
        case AOM_CICP_MC_FCC:
        case AOM_CICP_MC_SMPTE_240: return "bt601";
        case AOM_CICP_MC_BT_2020_NCL:
        case AOM_CICP_MC_BT_2020_CL: return "bt2020";
        case AOM_CICP_MC_UNSPECIFIED: return "unknown";
        default:
            throw std::invalid_argument(
                std::string(context) +
                ": AV1 color matrix is not represented");
    }
}

inline void copy_decoded_plane_to_u8(
    std::vector<uint8_t> &destination, size_t frame,
    size_t height, size_t width, const uint8_t *source,
    int stride, int bit_depth, bool high_bit_depth,
    const char *storage_error) {
    const size_t bytes_per_sample = high_bit_depth ? 2 : 1;
    if (!source || stride < 0 ||
        static_cast<size_t>(stride) < width * bytes_per_sample)
        throw std::invalid_argument(storage_error);
    uint8_t *output = destination.data() + frame * height * width;
    const uint32_t maximum = (uint32_t{1} << bit_depth) - 1;
    for (size_t row = 0; row < height; ++row) {
        const uint8_t *input = source + row * static_cast<size_t>(stride);
        if (!high_bit_depth) {
            std::memcpy(output + row * width, input, width);
            continue;
        }
        for (size_t column = 0; column < width; ++column) {
            uint16_t value = 0;
            std::memcpy(&value, input + column * 2, sizeof(value));
            output[row * width + column] = static_cast<uint8_t>(
                (static_cast<uint32_t>(value) * 255 + maximum / 2) /
                maximum);
        }
    }
}

}  // namespace sio::video
