// records/reconstruction.hpp — the COLMAP-style sparse-reconstruction memory
// representation (cameras + image poses + points3D, SoA), shared by the
// colmap codec and its binding.
//
// Conventions (exposed as metadata by the binding): quaternions are WXYZ,
// the pose is world->camera, camera intrinsics are a model-tagged params[].
#pragma once

#include <string>

#include "io/common.hpp"

struct Camera {
    uint32_t id;
    int32_t model_id;
    uint64_t width, height;
    std::vector<double> params;
};

struct Reconstruction {
    std::vector<Camera> cameras;
    // images (SoA) + names + CSR observations (per-image 2D points)
    std::vector<uint32_t> img_ids;
    std::vector<double> quats;  // N*4, WXYZ
    std::vector<double> trans;  // N*3
    std::vector<uint32_t> img_cam_ids;
    std::vector<std::string> img_names;
    std::vector<double> obs_xy;     // 2*sumK
    std::vector<int64_t> obs_pt3d;  // sumK (-1 = no 3D point)
    std::vector<uint64_t> obs_off;  // N+1
    // points3D (SoA) + CSR tracks
    std::vector<uint64_t> pt_ids;
    std::vector<double> xyz;   // M*3
    std::vector<uint8_t> rgb;  // M*3
    std::vector<double> err;   // M
    std::vector<uint32_t> track;      // 2*sumT (image_id, point2D_idx)
    std::vector<uint64_t> track_off;  // M+1

    // COLMAP 3.12+ rig/frame model. Legacy sparse models omit rigs/frames
    // entirely; has_rig_frame_model preserves that distinction even when a
    // modern model contains zero rigs and zero frames.
    bool has_rig_frame_model = false;

    // rigs (SoA) + CSR non-reference sensors. Sensor types use COLMAP's
    // stable enum values: INVALID=-1, CAMERA=0, IMU=1. A zero-sensor rig uses
    // INVALID/UINT32_MAX for its absent reference sensor.
    std::vector<uint32_t> rig_ids;
    std::vector<int32_t> rig_ref_sensor_types;
    std::vector<uint32_t> rig_ref_sensor_ids;
    std::vector<uint64_t> rig_sensor_off;  // R+1, non-reference sensors
    std::vector<int32_t> rig_sensor_types;
    std::vector<uint32_t> rig_sensor_ids;
    std::vector<uint8_t> rig_sensor_has_pose;
    std::vector<double> rig_sensor_quats;  // S*4, WXYZ sensor_from_rig
    std::vector<double> rig_sensor_trans;  // S*3

    // registered frames (SoA) + CSR data identifiers.
    std::vector<uint32_t> frame_ids;
    std::vector<uint32_t> frame_rig_ids;
    std::vector<double> frame_quats;  // F*4, WXYZ rig_from_world
    std::vector<double> frame_trans;  // F*3
    std::vector<uint64_t> frame_data_off;  // F+1
    std::vector<int32_t> frame_sensor_types;
    std::vector<uint32_t> frame_sensor_ids;
    std::vector<uint64_t> frame_data_ids;

    size_t num_images() const { return img_ids.size(); }
    size_t num_points() const { return pt_ids.size(); }
    size_t num_rigs() const { return rig_ids.size(); }
    size_t num_frames() const { return frame_ids.size(); }
};

inline bool valid_colmap_sensor_type(int32_t value) {
    return value >= -1 && value <= 1;
}

void validate_colmap_rig_frame_model(
    const Reconstruction &reconstruction, const char *context);
void validate_colmap_reconstruction(
    const Reconstruction &reconstruction, const char *context);
void select_colmap_rig_frame_for_image(
    const Reconstruction &source, uint32_t image_id,
    Reconstruction &destination, const char *context);

inline void require_no_colmap_rig_frame_model(
    const Reconstruction &reconstruction, const char *format) {
    if (reconstruction.has_rig_frame_model)
        throw std::invalid_argument(
            std::string(format) +
            ": cannot represent COLMAP rig/frame metadata");
}

struct ModelInfo {
    const char *name;
    int nparams;
};
inline ModelInfo colmap_model_info(int id) {
    switch (id) {
        case 0: return {"SIMPLE_PINHOLE", 3};
        case 1: return {"PINHOLE", 4};
        case 2: return {"SIMPLE_RADIAL", 4};
        case 3: return {"RADIAL", 5};
        case 4: return {"OPENCV", 8};
        case 5: return {"OPENCV_FISHEYE", 8};
        case 6: return {"FULL_OPENCV", 12};
        case 7: return {"FOV", 5};
        case 8: return {"SIMPLE_RADIAL_FISHEYE", 4};
        case 9: return {"RADIAL_FISHEYE", 5};
        case 10: return {"THIN_PRISM_FISHEYE", 12};
        case 11: return {"RAD_TAN_THIN_PRISM_FISHEYE", 16};
        case 12: return {"SIMPLE_DIVISION", 4};
        case 13: return {"DIVISION", 5};
        case 14: return {"SIMPLE_FISHEYE", 3};
        case 15: return {"FISHEYE", 4};
        case 16: return {"EUCM", 6};
        case 17: return {"EQUIRECTANGULAR", 2};
        default: throw std::invalid_argument("COLMAP: unknown camera model id " + std::to_string(id));
    }
}
