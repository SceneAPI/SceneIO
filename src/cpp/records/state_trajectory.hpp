// records/state_trajectory.hpp -- timestamped navigation states in a
// zero-copy SoA representation.
//
// Timestamps are signed int64 nanoseconds so EuRoC epoch-scale values remain
// exact. Numeric state channels are float64 and row-aligned. The convention
// fields are metadata: codecs record what the source means, and writers guard
// rather than silently changing frames, units, quaternion order, or sign.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "io/common.hpp"

struct StateTrajectory {
    size_t n = 0;
    std::vector<int64_t> timestamps_ns;
    std::vector<double> positions;
    std::vector<double> quaternions;
    std::vector<double> velocities;
    std::vector<double> gyro_biases;
    std::vector<double> accel_biases;

    std::string quaternion_order = "wxyz";
    std::string quaternion_sign = "preserved";
    std::string pose_convention = "sensor_to_reference";
    std::string position_frame = "reference";
    std::string velocity_frame = "reference";
    std::string bias_frame = "sensor";
    std::string position_unit = "meters";
    std::string velocity_unit = "meters_per_second";
    std::string gyro_bias_unit = "radians_per_second";
    std::string accel_bias_unit = "meters_per_second_squared";
    std::string timestamp_unit = "nanoseconds";

    size_t num_states() const { return n; }
};

inline bool trajectory_valid_quaternion_order(const std::string &value) {
    return value == "wxyz" || value == "xyzw";
}
inline bool trajectory_valid_quaternion_sign(const std::string &value) {
    return value == "preserved" || value == "canonical_positive_w";
}
inline bool trajectory_valid_pose_convention(const std::string &value) {
    return value == "sensor_to_reference" ||
           value == "reference_to_sensor";
}
inline bool trajectory_valid_vector_frame(const std::string &value) {
    return value == "reference" || value == "sensor";
}
inline bool trajectory_valid_position_unit(const std::string &value) {
    return value == "meters" || value == "millimeters";
}
inline bool trajectory_valid_velocity_unit(const std::string &value) {
    return value == "meters_per_second" ||
           value == "millimeters_per_second";
}
inline bool trajectory_valid_gyro_bias_unit(const std::string &value) {
    return value == "radians_per_second" ||
           value == "degrees_per_second";
}
inline bool trajectory_valid_accel_bias_unit(const std::string &value) {
    return value == "meters_per_second_squared" ||
           value == "standard_gravity";
}
inline bool trajectory_valid_timestamp_unit(const std::string &value) {
    return value == "nanoseconds";
}
