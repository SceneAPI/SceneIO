// Shared 3D Gaussian Splatting memory representation. Both the PLY and SPZ
// codecs decode into this same GaussianCloud (registered once), so a splat
// loaded from either format has an identical in-memory layout.
//
// Existing codecs default to the raw / pre-activation 3DGS PLY conventions:
//   means (N,3), scales (N,3, log space), quats (N,4, WXYZ),
//   opacity (N, logit space), sh_dc (N,3), sh_rest (N,R) channel-grouped
//   [R.. G.. B..] with R in {0,9,24,45}.
//
// USD's ParticleField3DGaussianSplat instead stores linear scales/opacities
// and coefficient-major RGB SH values. Keep those conventions as record data
// so a codec can refuse an incompatible record instead of activating values
// silently. The vectors remain float32; source_precision records whether a
// losslessly promoted float16 source should be written back as float16.
#pragma once

#include <limits>

#include "io/common.hpp"

struct GaussianCloud {
    size_t n = 0;
    std::vector<float> means;    // n*3
    std::vector<float> sh_dc;    // n*3
    std::vector<float> sh_rest;  // n*R, channel-grouped
    std::vector<float> opacity;  // n
    std::vector<float> scales;   // n*3
    std::vector<float> quats;    // n*4 (WXYZ)
    size_t num_rest = 0;         // R
    int sh_degree = 0;
    std::string quaternion_order = "wxyz";
    std::string scale_space = "log";
    std::string opacity_space = "logit";
    std::string sh_layout = "channel_grouped";
    std::string source_precision = "float32";
    std::string projection_mode_hint = "perspective";
    std::string sorting_mode_hint = "zDepth";
};

inline int gc_deg_from_rest(size_t R) {
    if (R == 0) return 0;
    if (R == 9) return 1;
    if (R == 24) return 2;
    if (R == 45) return 3;
    return -1;
}

inline size_t gc_rest_for_sh_dim(size_t sh_dim) { return sh_dim * 3; }  // {0,3,8,15} -> {0,9,24,45}

inline bool gc_valid_quaternion_order(const std::string &value) {
    return value == "wxyz" || value == "xyzw";
}

inline bool gc_valid_scale_space(const std::string &value) {
    return value == "linear" || value == "log";
}

inline bool gc_valid_opacity_space(const std::string &value) {
    return value == "linear" || value == "logit";
}

inline bool gc_valid_sh_layout(const std::string &value) {
    return value == "channel_grouped" || value == "coefficient_rgb";
}

inline bool gc_valid_source_precision(const std::string &value) {
    return value == "float16" || value == "float32";
}

inline bool gc_valid_projection_mode_hint(const std::string &value) {
    return value == "perspective" || value == "tangential";
}

inline bool gc_valid_sorting_mode_hint(const std::string &value) {
    return value == "zDepth" || value == "cameraDistance" ||
           value == "rayHitDistance";
}

inline size_t gc_expected_size(
    size_t count, size_t width, const char *context) {
    if (width != 0 &&
        count > std::numeric_limits<size_t>::max() / width)
        throw std::invalid_argument(
            std::string(context) + ": field size overflows size_t");
    return count * width;
}

inline void validate_gaussian_structure(
    const GaussianCloud &cloud, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    if (cloud.means.size() != gc_expected_size(cloud.n, 3, context) ||
        cloud.scales.size() != gc_expected_size(cloud.n, 3, context) ||
        cloud.quats.size() != gc_expected_size(cloud.n, 4, context) ||
        cloud.opacity.size() != cloud.n ||
        cloud.sh_dc.size() != gc_expected_size(cloud.n, 3, context) ||
        cloud.sh_rest.size() !=
            gc_expected_size(cloud.n, cloud.num_rest, context) ||
        gc_deg_from_rest(cloud.num_rest) != cloud.sh_degree)
        throw std::invalid_argument(prefix + "inconsistent GaussianCloud storage");
}

inline void validate_gaussian_conventions(
    const GaussianCloud &cloud, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    if (!gc_valid_quaternion_order(cloud.quaternion_order))
        throw std::invalid_argument(prefix + "unknown quaternion_order");
    if (!gc_valid_scale_space(cloud.scale_space))
        throw std::invalid_argument(prefix + "unknown scale_space");
    if (!gc_valid_opacity_space(cloud.opacity_space))
        throw std::invalid_argument(prefix + "unknown opacity_space");
    if (!gc_valid_sh_layout(cloud.sh_layout))
        throw std::invalid_argument(prefix + "unknown sh_layout");
    if (!gc_valid_source_precision(cloud.source_precision))
        throw std::invalid_argument(prefix + "unknown source_precision");
    if (!gc_valid_projection_mode_hint(cloud.projection_mode_hint))
        throw std::invalid_argument(prefix + "unknown projection_mode_hint");
    if (!gc_valid_sorting_mode_hint(cloud.sorting_mode_hint))
        throw std::invalid_argument(prefix + "unknown sorting_mode_hint");
}

inline void require_legacy_gaussian_conventions(
    const GaussianCloud &cloud, const char *context) {
    validate_gaussian_structure(cloud, context);
    validate_gaussian_conventions(cloud, context);
    if (cloud.quaternion_order != "wxyz" ||
        cloud.scale_space != "log" ||
        cloud.opacity_space != "logit" ||
        cloud.sh_layout != "channel_grouped" ||
        cloud.source_precision != "float32" ||
        cloud.projection_mode_hint != "perspective" ||
        cloud.sorting_mode_hint != "zDepth")
        throw std::invalid_argument(
            std::string(context) +
            ": requires quaternion_order='wxyz', scale_space='log', "
            "opacity_space='logit', sh_layout='channel_grouped', and "
            "source_precision='float32' with default USD rendering hints; "
            "convert explicitly before writing");
}
