// records/posed_view_set.hpp — a set of posed camera views (an SE3 pose per
// view + optional shared/per-view intrinsics), the memory representation for
// the camera-pose formats (transforms.json, TUM/KITTI trajectories).
//
// Unlike Reconstruction it carries no 3D points, and its pose/axis
// conventions are RECORDED per source rather than fixed: a codec tags what it
// read (quaternion order, pose direction, axis frame, metric scale) and a
// separate normalizer converts. See docs/io_implementation_plan.md.
#pragma once

#include <string>

#include "records/reconstruction.hpp"  // reuse the Camera struct for intrinsics

struct PosedViewSet {
    // pose per view (SoA); the semantics of these numbers are given by the
    // convention tags below, which the reader sets from the source.
    std::vector<double> quats;       // N*4, order per `quaternion_order`
    std::vector<double> trans;       // N*3
    std::vector<int32_t> cam_idx;    // N, index into `cameras` (-1 = no intrinsics); empty if none
    std::vector<std::string> names;  // N image paths / frame ids (may be empty)
    std::vector<double> stamps;      // N timestamps (e.g. TUM), or empty if the format has none
    std::vector<Camera> cameras;     // optional intrinsics (shared or per-view); may be empty

    // conventions the codec recorded (metadata, not fixed like the splat records):
    std::string quaternion_order = "wxyz";            // "wxyz" | "xyzw"
    std::string pose_convention = "camera_to_world";  // "camera_to_world" | "world_to_camera"
    std::string axis_frame = "opencv";                // "opencv" | "opengl"
    double scale_to_meters = 1.0;  // multiply translations by this to get meters (TUM sensors, etc.)

    size_t num_views() const { return trans.size() / 3; }
    size_t num_cameras() const { return cameras.size(); }
};
