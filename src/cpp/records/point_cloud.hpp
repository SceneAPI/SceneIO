// records/point_cloud.hpp — generic unstructured point-cloud memory
// representation (SoA, zero-copy), shared by the point codecs (.xyz/.pts,
// point PLY, PCD, and LAS; LAZ/E57 later). Positions are the only required field;
// the optional rgb/normals/intensity fields are empty vectors when absent and,
// when present, hold exactly `n` rows.
//
// Unlike GaussianCloud's fixed constants, the conventions here are RECORDED
// metadata (the PoseStorage flavor) because point formats declare no
// frame/unit/intensity range — the reader tags what it read and future writers
// guard. See docs/io_implementation_plan.md.
//
// Canonical structural facts (not tags): xyz float32 (N,3), rgb uint8 (N,3) in
// RGB order, per-point row alignment. Georeferenced double precision (LAS/E57)
// is handled by a recorded origin double[3]. PCD's organized shape and
// acquisition viewpoint are likewise additive metadata; records themselves are
// not serialized.
#pragma once

#include <memory>
#include <string>

#include "io/common.hpp"

// Opaque, lossless LAS waveform sidecar. Point formats 4/5/9/10 contain many
// LAS-specific fields that do not belong in the generic PointCloud contract.
// Keeping the complete raw point records preserves those fields without
// allocating per-field arrays for ordinary clouds. The LAS writer copies each
// record, patches only canonical position/intensity/color fields, and retains
// all waveform packet references and non-generic point metadata bit-for-bit.
struct LasWaveformSidecar {
    size_t n = 0;
    uint8_t point_format = 0;
    uint8_t version_minor = 0;
    uint16_t global_encoding = 0;
    uint16_t point_record_length = 0;
    std::vector<uint8_t> point_records;  // n * point_record_length
    std::vector<uint8_t> descriptor_vlrs;
    std::vector<uint8_t> waveform_packet_record;
};

struct PointCloud {
    size_t n = 0;                   // point count (explicit, GaussianCloud precedent)
    std::vector<float> xyz;         // n*3 (required; bound as `positions`)
    std::vector<uint8_t> rgb;       // n*3 or empty (8-bit color)
    std::vector<uint16_t> rgb16;    // n*3 or empty (16-bit color, e.g. LAS; NOT narrowed to rgb)
    std::vector<float> normals;     // n*3 or empty (stored raw; unit length not enforced)
    std::vector<float> intensity;   // n or empty (raw values, never rescaled)
    // USD/scene payload fields. These stay distinct from quantized RGB so no
    // format writer needs to narrow or activate values implicitly.
    std::vector<float> display_colors;    // n*3 or empty, authored float RGB
    std::vector<float> display_opacities; // n or empty, [0,1]
    std::vector<float> widths;            // n or empty, nonnegative diameters
    std::vector<int64_t> ids;             // n or empty, unique
    std::vector<float> velocities;        // n*3 or empty
    std::vector<float> accelerations;     // n*3 or empty
    // Optional per-point observation tracks in canonical CSR form.  When
    // present, offsets has n+1 entries and the two observation columns have
    // offsets.back() rows. Image identities are stable UTF-8 names rather
    // than format-local numeric ids.
    std::vector<uint64_t> track_offsets;
    std::vector<std::string> track_image_ids;
    std::vector<uint64_t> track_keypoint_indices;
    std::string display_color_space = "unknown";
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
    std::shared_ptr<LasWaveformSidecar> las_waveform;

    bool has_rgb() const { return !rgb.empty(); }
    bool has_rgb16() const { return !rgb16.empty(); }
    bool has_normals() const { return !normals.empty(); }
    bool has_intensity() const { return !intensity.empty(); }
    bool has_display_colors() const {
        return !display_colors.empty();
    }
    bool has_display_opacities() const {
        return !display_opacities.empty();
    }
    bool has_widths() const { return !widths.empty(); }
    bool has_ids() const { return !ids.empty(); }
    bool has_velocities() const { return !velocities.empty(); }
    bool has_accelerations() const {
        return !accelerations.empty();
    }
    bool has_tracks() const { return !track_offsets.empty(); }
    size_t num_track_observations() const {
        return track_image_ids.size();
    }
    bool has_las_waveform() const {
        return static_cast<bool>(las_waveform);
    }
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

void validate_las_waveform_sidecar(
    const LasWaveformSidecar &sidecar,
    const char *context = "LAS waveform sidecar");
void validate_point_cloud(
    const PointCloud &cloud,
    const char *context = "point cloud");

// Vocabulary helpers (image_valid_color_space precedent): the factory validates
// against these closed sets so a typo raises instead of silently persisting.
inline bool pc_valid_frame(const std::string &s) {
    return s == "unknown" || s == "opencv" || s == "opengl" || s == "enu" || s == "ned";
}
inline bool pc_valid_intensity_range(const std::string &s) {
    return s == "unknown" || s == "unit" || s == "u8" || s == "u16";
}
inline bool pc_valid_display_color_space(const std::string &s) {
    return s == "unknown" || s == "linear" || s == "srgb";
}
inline bool pc_has_extended_scene_fields(const PointCloud &cloud) {
    return cloud.has_display_colors() ||
           cloud.has_display_opacities() || cloud.has_widths() ||
           cloud.has_ids() || cloud.has_velocities() ||
           cloud.has_accelerations() || cloud.has_tracks() ||
           cloud.display_color_space != "unknown";
}
inline void require_no_extended_point_fields(
    const PointCloud &cloud, const char *context) {
    if (pc_has_extended_scene_fields(cloud))
        throw std::invalid_argument(
            std::string(context) +
            ": cannot represent float display colors/opacities, widths, "
            "ids, velocities, accelerations, tracks, or display_color_space; "
            "remove them explicitly before writing");
}
