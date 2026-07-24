// records/camera_rig.hpp -- lossless multi-camera calibration record.
//
// The existing Camera type is COLMAP-model-specific. CameraRig instead keeps
// source projection/distortion model names and ragged coefficient vectors, so
// OpenCV, ROS CameraInfo, and Kalibr fields are not silently narrowed.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "io/common.hpp"

struct CameraRig {
    size_t n = 0;
    std::vector<uint32_t> camera_ids;       // n
    std::vector<uint64_t> resolutions;      // n*2: width,height
    std::vector<std::string> names;         // n
    std::vector<std::string> projection_models;  // n
    std::vector<uint64_t> intrinsic_offsets;     // n+1
    std::vector<double> intrinsics;               // ragged
    std::vector<std::string> distortion_models;  // n
    std::vector<uint64_t> distortion_offsets;    // n+1
    std::vector<double> distortion_coefficients; // ragged

    // Transform of the named reference frame and each camera. `has_extrinsics`
    // distinguishes an absent transform from the numerical identity.
    std::vector<double> quaternions;    // n*4
    std::vector<double> translations;   // n*3
    std::vector<uint8_t> has_extrinsics;  // n

    // Exact matrix carriers. K/R/P are row-major 3x3/3x3/3x4; masks preserve
    // absent-vs-present even when a present matrix is all zeros.
    std::vector<double> camera_matrices;       // n*9
    std::vector<uint8_t> has_camera_matrix;   // n
    std::vector<double> rectification_matrices;  // n*9
    std::vector<uint8_t> has_rectification;      // n
    std::vector<double> projection_matrices;     // n*12
    std::vector<uint8_t> has_projection_matrix; // n

    // ROS CameraInfo operational fields.
    std::vector<uint32_t> binning;  // n*2: x,y
    std::vector<uint32_t> roi;      // n*4: x,y,width,height
    std::vector<uint8_t> roi_do_rectify;  // n
    std::vector<uint8_t> has_operational; // n

    // Kalibr fields. The fixed convention is
    // reference_time = camera_time + time_offset_seconds.
    std::vector<std::string> topics;        // n
    std::vector<double> time_offsets;       // n
    std::vector<uint8_t> has_time_offset;   // n

    std::string quaternion_order = "wxyz";
    std::string quaternion_sign = "preserved";
    std::string transform_convention = "reference_to_camera";
    std::string axis_frame = "opencv";
    std::string reference_frame = "unknown";
    double scale_to_meters = 1.0;

    size_t num_cameras() const { return n; }
};

void validate_camera_rig(
    const CameraRig &rig, const char *context = "camera_rig");

inline bool rig_valid_quaternion_order(const std::string &value) {
    return value == "wxyz" || value == "xyzw";
}
inline bool rig_valid_quaternion_sign(const std::string &value) {
    return value == "preserved" ||
           value == "canonical_positive_w";
}
inline bool rig_valid_transform_convention(const std::string &value) {
    return value == "reference_to_camera" ||
           value == "camera_to_reference";
}
inline bool rig_valid_axis_frame(const std::string &value) {
    return value == "opencv" || value == "opengl";
}
inline bool rig_valid_reference_frame(const std::string &value) {
    return value == "unknown" || value == "rig" ||
           value == "imu" || value == "camera0";
}
