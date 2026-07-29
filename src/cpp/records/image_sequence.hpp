// records/image_sequence.hpp -- lazy encoded-frame, owned packed-raster, or
// owned planar-YUV sequence data with exact timing and explicit conventions.
#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "io/common.hpp"

struct ImageSequence {
    size_t n = 0;
    size_t height = 0;
    size_t width = 0;
    size_t channels = 0;
    size_t chroma_height = 0;
    size_t chroma_width = 0;

    // Empty together when timing is unknown; otherwise both are N.
    std::vector<int64_t> timestamps_ns;
    std::vector<int64_t> durations_ns;

    // Encoded-path storage uses UTF-8 offset/value tables so no Python object
    // arrays or borrowed path buffers enter the canonical record.
    std::vector<uint64_t> path_offsets;
    std::vector<uint8_t> path_utf8;
    std::vector<uint64_t> name_offsets;
    std::vector<uint8_t> name_utf8;

    // Packed raster storage. Exactly one vector is active for
    // storage_mode="packed", holding N*H*W*C interleaved samples in canonical
    // gray/RGB/RGBA order and top-to-bottom rows.
    std::vector<uint8_t> pixels_u8;
    std::vector<uint16_t> pixels_u16;
    std::vector<float> pixels_f32;

    // Planar YUV storage. Y is N*H*W. U and V are both
    // N*chroma_height*chroma_width, or empty together for monochrome.
    std::vector<uint8_t> y;
    std::vector<uint8_t> u;
    std::vector<uint8_t> v;

    std::string storage_mode = "encoded_paths";
    std::string frame_dtype = "uint8";
    std::string color_space = "unknown";
    std::string alpha_mode = "none";
    std::string chroma_subsampling = "none";
    std::string chroma_siting = "none";
    std::string color_range = "unknown";
    std::string matrix = "unknown";
    std::string interlace = "progressive";
    uint32_t maxval = 255;
    uint32_t frame_rate_numerator = 0;
    uint32_t frame_rate_denominator = 1;
    uint32_t pixel_aspect_numerator = 0;
    uint32_t pixel_aspect_denominator = 0;

    // Animation repetition is absent for generic sequences. When present,
    // zero means repeat indefinitely, matching APNG and animated WebP.
    bool loop_count_present = false;
    uint32_t loop_count = 0;
    bool background_present = false;
    std::array<uint8_t, 4> background_rgba{0, 0, 0, 0};

    bool has_timing() const {
        return !timestamps_ns.empty();
    }
    bool has_paths() const { return storage_mode == "encoded_paths"; }
    bool has_pixels() const { return storage_mode == "packed"; }
    bool has_chroma() const { return !u.empty(); }
};

std::vector<std::string> image_sequence_paths(
    const ImageSequence &sequence);
std::vector<std::string> image_sequence_names(
    const ImageSequence &sequence);
void assign_image_sequence_paths(
    ImageSequence &sequence,
    const std::vector<std::string> &values);
void assign_image_sequence_names(
    ImageSequence &sequence,
    const std::vector<std::string> &values);
void validate_image_sequence(
    const ImageSequence &sequence,
    const char *context = "image sequence");
