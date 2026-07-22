// records/point_cloud.hpp — generic unstructured point-cloud memory
// representation (SoA, zero-copy), shared by the point codecs (.xyz/.pts now;
// PCD, LAS/LAZ, E57, PLY-point later). Positions are the only required field;
// the optional rgb/normals/intensity fields are empty vectors when absent and,
// when present, hold exactly `n` rows.
//
// Unlike GaussianCloud's fixed constants, the conventions here are RECORDED
// metadata (the PosedViewSet flavor) because point formats declare no
// frame/unit/intensity range — the reader tags what it read and future writers
// guard. See docs/io_implementation_plan.md.
//
// Canonical structural facts (not tags): xyz float32 (N,3), rgb uint8 (N,3) in
// RGB order, per-point row alignment. Georeferenced double precision (LAS/E57)
// is handled later by an ADDITIVE recorded origin double[3]; records are not
// serialized, so that field addition is zero-cost.
#pragma once

#include <string>

#include "io/common.hpp"

struct PointCloud {
    size_t n = 0;                  // point count (explicit, GaussianCloud precedent)
    std::vector<float> xyz;        // n*3 (required; bound as `positions`)
    std::vector<uint8_t> rgb;      // n*3 or empty
    std::vector<float> normals;    // n*3 or empty (stored raw; unit length not enforced)
    std::vector<float> intensity;  // n or empty (raw values, never rescaled)
    // conventions the codec recorded (metadata, not fixed like GaussianCloud's):
    std::string coordinate_frame = "unknown";  // "unknown"|"opencv"|"opengl"|"enu"|"ned"
    double scale_to_meters = 1.0;              // multiply xyz by this to get meters
    std::string intensity_range = "unknown";   // "unknown"|"unit"|"u8"|"u16"

    bool has_rgb() const { return !rgb.empty(); }
    bool has_normals() const { return !normals.empty(); }
    bool has_intensity() const { return !intensity.empty(); }
    size_t num_points() const { return n; }
};

// Vocabulary helpers (image_valid_color_space precedent): the factory validates
// against these closed sets so a typo raises instead of silently persisting.
inline bool pc_valid_frame(const std::string &s) {
    return s == "unknown" || s == "opencv" || s == "opengl" || s == "enu" || s == "ned";
}
inline bool pc_valid_intensity_range(const std::string &s) {
    return s == "unknown" || s == "unit" || s == "u8" || s == "u16";
}
