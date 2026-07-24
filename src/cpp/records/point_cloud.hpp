// records/point_cloud.hpp — generic unstructured point-cloud memory
// representation (SoA, zero-copy), shared by the point codecs (.xyz/.pts,
// point PLY, PCD, and LAS; LAZ/E57 later). Positions are the only required field;
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
// is handled by a recorded origin double[3]. PCD's organized shape and
// acquisition viewpoint are likewise additive metadata; records themselves are
// not serialized.
#pragma once

#include <string>

#include "io/common.hpp"

struct PointCloud {
    size_t n = 0;                   // point count (explicit, GaussianCloud precedent)
    std::vector<float> xyz;         // n*3 (required; bound as `positions`)
    std::vector<uint8_t> rgb;       // n*3 or empty (8-bit color)
    std::vector<uint16_t> rgb16;    // n*3 or empty (16-bit color, e.g. LAS; NOT narrowed to rgb)
    std::vector<float> normals;     // n*3 or empty (stored raw; unit length not enforced)
    std::vector<float> intensity;   // n or empty (raw values, never rescaled)
    // conventions the codec recorded (metadata, not fixed like GaussianCloud's):
    std::string coordinate_frame = "unknown";  // "unknown"|"opencv"|"opengl"|"enu"|"ned"
    double scale_to_meters = 1.0;              // multiply xyz by this to get meters
    std::string intensity_range = "unknown";   // "unknown"|"unit"|"u8"|"u16"
    // georef anchor (LAS/E57): true position = xyz + origin. Kept in double so a
    // large offset (UTM easting ~1e6) doesn't crush the f32 xyz precision.
    double origin[3] = {0.0, 0.0, 0.0};
    // Optional organized raster shape plus sensor acquisition viewpoint. A
    // zero organized_height means the implicit unorganized shape (n, 1), so
    // existing codecs do not need to materialize redundant metadata. PCD sets
    // both dimensions explicitly and preserves tx,ty,tz,qw,qx,qy,qz.
    size_t organized_width = 0;
    size_t organized_height = 0;
    double viewpoint[7] = {0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0};

    bool has_rgb() const { return !rgb.empty(); }
    bool has_rgb16() const { return !rgb16.empty(); }
    bool has_normals() const { return !normals.empty(); }
    bool has_intensity() const { return !intensity.empty(); }
    size_t num_points() const { return n; }
    size_t width() const {
        return organized_height == 0 ? n : organized_width;
    }
    size_t height() const {
        return organized_height == 0 ? 1 : organized_height;
    }
    bool is_organized() const { return height() > 1; }
    bool has_default_organization() const {
        return width() == n && height() == 1;
    }
    bool has_default_viewpoint() const {
        return viewpoint[0] == 0.0 && viewpoint[1] == 0.0 &&
               viewpoint[2] == 0.0 && viewpoint[3] == 1.0 &&
               viewpoint[4] == 0.0 && viewpoint[5] == 0.0 &&
               viewpoint[6] == 0.0;
    }
};

// Vocabulary helpers (image_valid_color_space precedent): the factory validates
// against these closed sets so a typo raises instead of silently persisting.
inline bool pc_valid_frame(const std::string &s) {
    return s == "unknown" || s == "opencv" || s == "opengl" || s == "enu" || s == "ned";
}
inline bool pc_valid_intensity_range(const std::string &s) {
    return s == "unknown" || s == "unit" || s == "u8" || s == "u16";
}
