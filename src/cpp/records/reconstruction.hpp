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

    size_t num_images() const { return img_ids.size(); }
    size_t num_points() const { return pt_ids.size(); }
};

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
        default: throw std::invalid_argument("COLMAP: unknown camera model id " + std::to_string(id));
    }
}
