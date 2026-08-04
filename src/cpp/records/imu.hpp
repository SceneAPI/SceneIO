// records/imu.hpp -- calibrated IMU sensors and raw inertial observations.
//
// Values are stored in record-owned canonical arrays.  Units, clock domains,
// and transform direction remain explicit; factories validate and copy rather
// than normalizing caller data implicitly.
#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "io/common.hpp"

struct ImuCalibration {
    uint32_t sensor_id = 0;
    std::string name;
    std::string topic;

    // Rigid sensor-to-reference transform. Translation is always meters.
    std::array<double, 4> quaternion{1.0, 0.0, 0.0, 0.0};
    std::array<double, 3> translation{0.0, 0.0, 0.0};

    std::optional<double> nominal_rate_hz;
    std::optional<double> gyroscope_noise_density;
    std::optional<double> gyroscope_random_walk;
    std::optional<double> accelerometer_noise_density;
    std::optional<double> accelerometer_random_walk;
    std::optional<int64_t> time_offset_ns;

    std::string quaternion_order = "wxyz";
    std::string quaternion_sign = "preserved";
    std::string sensor_axis_frame = "sensor";
    std::string reference_frame = "body";
};

struct ImuSequence {
    uint32_t sensor_id = 0;
    size_t n = 0;
    std::vector<int64_t> timestamps_ns;
    std::vector<double> angular_velocities;
    std::vector<double> linear_accelerations;

    std::string angular_velocity_unit = "radians_per_second";
    std::string linear_acceleration_unit =
        "meters_per_second_squared";
    std::string sensor_axis_frame = "sensor";
    std::string timestamp_reference = "measurement";
    std::string clock_domain = "sensor";

    size_t num_samples() const { return n; }
};

void validate_imu_sequence(
    const ImuSequence &sequence,
    const char *context = "imu_sequence");

inline bool imu_valid_quaternion_order(const std::string &value) {
    return value == "wxyz" || value == "xyzw";
}

inline bool imu_valid_quaternion_sign(const std::string &value) {
    return value == "preserved" || value == "canonical_positive_w";
}

inline bool imu_valid_axis_frame(const std::string &value) {
    return value == "sensor" || value == "enu" || value == "ned";
}

inline bool imu_valid_angular_velocity_unit(const std::string &value) {
    return value == "radians_per_second" ||
           value == "degrees_per_second";
}

inline bool imu_valid_linear_acceleration_unit(const std::string &value) {
    return value == "meters_per_second_squared" ||
           value == "standard_gravity";
}

inline bool imu_valid_timestamp_reference(const std::string &value) {
    return value == "measurement";
}
