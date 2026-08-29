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

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>

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
    // Semantic metadata beyond byte layout. The legacy factory defaults are
    // intentionally conservative: raw 3DGS quaternions are magnitude-
    // unconstrained, RGB transfer and coordinates are not tagged by PLY, and
    // no metric scale is inferred.
    std::string quaternion_norm = "unconstrained";
    std::string sh_basis = "3dgs_real";
    std::string sh_phase = "3dgs";
    std::string sh_coefficient_order = "degree_then_m_neg_to_pos";
    std::string color_space = "unknown";
    std::string coordinate_frame = "unknown";
    std::optional<double> scale_to_meters;
    std::string scale_to_meters_source = "unknown";
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

inline bool gc_valid_quaternion_norm(const std::string &value) {
    return value == "unknown" || value == "unconstrained" ||
           value == "unit";
}

inline bool gc_valid_sh_basis(const std::string &value) {
    return value == "unknown" || value == "3dgs_real";
}

inline bool gc_valid_sh_phase(const std::string &value) {
    return value == "unknown" || value == "3dgs";
}

inline bool gc_valid_sh_coefficient_order(const std::string &value) {
    return value == "unknown" ||
           value == "degree_then_m_neg_to_pos";
}

inline bool gc_valid_color_space(const std::string &value) {
    return value == "unknown" || value == "srgb" ||
           value == "linear_srgb";
}

inline bool gc_valid_coordinate_frame(const std::string &value) {
    return value == "unknown" || value == "opencv" ||
           value == "opengl" || value == "enu" || value == "ned";
}

inline bool gc_valid_scale_to_meters_source(const std::string &value) {
    return value == "unknown" || value == "format" || value == "file" ||
           value == "caller";
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
    if (!gc_valid_quaternion_norm(cloud.quaternion_norm))
        throw std::invalid_argument(prefix + "unknown quaternion_norm");
    if (!gc_valid_sh_basis(cloud.sh_basis))
        throw std::invalid_argument(prefix + "unknown sh_basis");
    if (!gc_valid_sh_phase(cloud.sh_phase))
        throw std::invalid_argument(prefix + "unknown sh_phase");
    if (!gc_valid_sh_coefficient_order(cloud.sh_coefficient_order))
        throw std::invalid_argument(prefix + "unknown sh_coefficient_order");
    if (!gc_valid_color_space(cloud.color_space))
        throw std::invalid_argument(prefix + "unknown color_space");
    if (!gc_valid_coordinate_frame(cloud.coordinate_frame))
        throw std::invalid_argument(prefix + "unknown coordinate_frame");
    if (!gc_valid_scale_to_meters_source(cloud.scale_to_meters_source))
        throw std::invalid_argument(prefix + "unknown scale_to_meters_source");
    if (cloud.scale_to_meters.has_value()) {
        if (!std::isfinite(*cloud.scale_to_meters) ||
            !(*cloud.scale_to_meters > 0.0))
            throw std::invalid_argument(
                prefix + "scale_to_meters must be finite and positive");
        if (cloud.scale_to_meters_source == "unknown")
            throw std::invalid_argument(
                prefix + "scale_to_meters requires a known source");
    } else if (cloud.scale_to_meters_source != "unknown") {
        throw std::invalid_argument(
            prefix + "scale_to_meters_source requires scale_to_meters");
    }
    if (cloud.quaternion_norm == "unit") {
        // A unit declaration describes rotation semantics, not the original
        // quantizer. Packed carriers can retain float16/uint10 rounding after
        // promotion, so use one strict-but-transport-safe tolerance.
        const double tolerance = 5e-4;
        for (size_t index = 0; index < cloud.n; ++index) {
            double norm_squared = 0.0;
            for (size_t component = 0; component < 4; ++component) {
                const double value = cloud.quats[index * 4 + component];
                norm_squared += value * value;
            }
            if (!std::isfinite(norm_squared) ||
                std::abs(std::sqrt(norm_squared) - 1.0) > tolerance)
                throw std::invalid_argument(
                    prefix + "quaternion_norm='unit' requires unit values");
        }
    }
}

inline void require_legacy_gaussian_conventions(
    const GaussianCloud &cloud, const char *context,
    const char *declared_coordinate_frame = "unknown") {
    validate_gaussian_structure(cloud, context);
    validate_gaussian_conventions(cloud, context);
    if (cloud.quaternion_order != "wxyz" ||
        cloud.scale_space != "log" ||
        cloud.opacity_space != "logit" ||
        cloud.sh_layout != "channel_grouped" ||
        cloud.source_precision != "float32" ||
        cloud.projection_mode_hint != "perspective" ||
        cloud.sorting_mode_hint != "zDepth" ||
        (cloud.quaternion_norm != "unconstrained" &&
         cloud.quaternion_norm != "unit") ||
        cloud.sh_basis != "3dgs_real" ||
        cloud.sh_phase != "3dgs" ||
        cloud.sh_coefficient_order != "degree_then_m_neg_to_pos" ||
        cloud.color_space != "unknown" ||
        (cloud.coordinate_frame != "unknown" &&
         cloud.coordinate_frame != declared_coordinate_frame) ||
        cloud.scale_to_meters.has_value() ||
        cloud.scale_to_meters_source != "unknown")
        throw std::invalid_argument(
            std::string(context) +
            ": requires quaternion_order='wxyz', scale_space='log', "
            "opacity_space='logit', sh_layout='channel_grouped', and "
            "source_precision='float32', 3DGS SH semantics, untagged RGB and "
            "coordinates, and default USD rendering hints; "
            "convert explicitly before writing");
}

inline void require_finite_gaussian_values(
    const GaussianCloud &cloud, const char *context) {
    validate_gaussian_structure(cloud, context);
    const std::string prefix = std::string(context) + ": ";
    auto require_finite = [&](const std::vector<float> &values,
                              const char *name) {
        if (!std::all_of(values.begin(), values.end(), [](float value) {
                return std::isfinite(value);
            }))
            throw std::invalid_argument(
                prefix + name + " values must be finite");
    };
    require_finite(cloud.means, "mean");
    require_finite(cloud.scales, "scale");
    require_finite(cloud.quats, "quaternion");
    require_finite(cloud.opacity, "opacity");
    require_finite(cloud.sh_dc, "SH DC");
    require_finite(cloud.sh_rest, "SH rest");
    for (size_t index = 0; index < cloud.n; ++index) {
        double norm_squared = 0.0;
        for (size_t component = 0; component < 4; ++component) {
            const double value = cloud.quats[index * 4 + component];
            norm_squared += value * value;
        }
        if (!(norm_squared > 0.0) || !std::isfinite(norm_squared))
            throw std::invalid_argument(
                prefix + "quaternions must have non-zero finite norm");
    }
}
