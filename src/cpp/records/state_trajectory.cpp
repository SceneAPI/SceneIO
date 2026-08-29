// records/state_trajectory.cpp -- StateTrajectory nanobind binding.
#include <nanobind/stl/string.h>

#include <cmath>
#include <limits>
#include <string>

#include "records/state_trajectory.hpp"

using namespace nb::literals;

namespace {

template <typename T>
nb::ndarray<nb::numpy, T> trajectory_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static T sentinel{};
    T *data =
        values.empty() ? &sentinel : const_cast<T *>(values.data());
    return nb::ndarray<nb::numpy, T>(
        data, shape.size(), shape.data());
}

using i64_array =
    nb::ndarray<const int64_t, nb::c_contig, nb::device::cpu>;
using f64_array =
    nb::ndarray<const double, nb::c_contig, nb::device::cpu>;

void require_matrix(
    const f64_array &array, size_t rows, size_t columns,
    const char *name) {
    if (array.ndim() != 2 || array.shape(0) != rows ||
        array.shape(1) != columns)
        throw std::invalid_argument(
            std::string("state_trajectory: ") + name + " must be (N," +
            std::to_string(columns) + ") float64");
}

void require_finite(
    const double *values, size_t count, const char *name) {
    for (size_t index = 0; index < count; ++index)
        if (!std::isfinite(values[index]))
            throw std::invalid_argument(
                std::string("state_trajectory: ") + name +
                " values must be finite");
}

void validate_metadata(const StateTrajectory &trajectory) {
    if (!trajectory_valid_quaternion_order(
            trajectory.quaternion_order))
        throw std::invalid_argument(
            "state_trajectory: quaternion_order must be wxyz|xyzw");
    if (!trajectory_valid_quaternion_sign(
            trajectory.quaternion_sign))
        throw std::invalid_argument(
            "state_trajectory: quaternion_sign must be "
            "preserved|canonical_positive_w");
    if (!trajectory_valid_pose_convention(
            trajectory.pose_convention))
        throw std::invalid_argument(
            "state_trajectory: pose_convention must be "
            "sensor_to_reference|reference_to_sensor");
    if (!trajectory_valid_vector_frame(trajectory.position_frame))
        throw std::invalid_argument(
            "state_trajectory: position_frame must be reference|sensor");
    if (!trajectory_valid_vector_frame(trajectory.velocity_frame))
        throw std::invalid_argument(
            "state_trajectory: velocity_frame must be reference|sensor");
    if (!trajectory_valid_vector_frame(trajectory.bias_frame))
        throw std::invalid_argument(
            "state_trajectory: bias_frame must be reference|sensor");
    if (!trajectory_valid_position_unit(trajectory.position_unit))
        throw std::invalid_argument(
            "state_trajectory: position_unit must be meters|millimeters");
    if (!trajectory_valid_velocity_unit(trajectory.velocity_unit))
        throw std::invalid_argument(
            "state_trajectory: velocity_unit must be "
            "meters_per_second|millimeters_per_second");
    if (!trajectory_valid_gyro_bias_unit(trajectory.gyro_bias_unit))
        throw std::invalid_argument(
            "state_trajectory: gyro_bias_unit must be "
            "radians_per_second|degrees_per_second");
    if (!trajectory_valid_accel_bias_unit(trajectory.accel_bias_unit))
        throw std::invalid_argument(
            "state_trajectory: accel_bias_unit must be "
            "meters_per_second_squared|standard_gravity");
    if (!trajectory_valid_timestamp_unit(trajectory.timestamp_unit))
        throw std::invalid_argument(
            "state_trajectory: timestamp_unit must be nanoseconds");
}

StateTrajectory make_state_trajectory(
    i64_array timestamps_ns, f64_array positions,
    f64_array quaternions, f64_array velocities,
    f64_array gyro_biases, f64_array accel_biases,
    const std::string &quaternion_order,
    const std::string &quaternion_sign,
    const std::string &pose_convention,
    const std::string &position_frame,
    const std::string &velocity_frame,
    const std::string &bias_frame,
    const std::string &position_unit,
    const std::string &velocity_unit,
    const std::string &gyro_bias_unit,
    const std::string &accel_bias_unit,
    const std::string &timestamp_unit) {
    if (timestamps_ns.ndim() != 1)
        throw std::invalid_argument(
            "state_trajectory: timestamps_ns must be (N,) int64");
    const size_t count = timestamps_ns.shape(0);
    if (count > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument(
            "state_trajectory: state count overflows field extents");
    require_matrix(positions, count, 3, "positions");
    require_matrix(quaternions, count, 4, "quaternions");
    require_matrix(velocities, count, 3, "velocities");
    require_matrix(gyro_biases, count, 3, "gyro_biases");
    require_matrix(accel_biases, count, 3, "accel_biases");

    StateTrajectory trajectory;
    trajectory.n = count;
    trajectory.quaternion_order = quaternion_order;
    trajectory.quaternion_sign = quaternion_sign;
    trajectory.pose_convention = pose_convention;
    trajectory.position_frame = position_frame;
    trajectory.velocity_frame = velocity_frame;
    trajectory.bias_frame = bias_frame;
    trajectory.position_unit = position_unit;
    trajectory.velocity_unit = velocity_unit;
    trajectory.gyro_bias_unit = gyro_bias_unit;
    trajectory.accel_bias_unit = accel_bias_unit;
    trajectory.timestamp_unit = timestamp_unit;
    validate_metadata(trajectory);

    {
        nb::gil_scoped_release release;
        const int64_t *timestamps = timestamps_ns.data();
        for (size_t index = 0; index < count; ++index) {
            if (timestamps[index] < 0)
                throw std::invalid_argument(
                    "state_trajectory: timestamps must be nonnegative");
            if (index != 0 &&
                timestamps[index] <= timestamps[index - 1])
                throw std::invalid_argument(
                    "state_trajectory: timestamps must be strictly increasing");
        }
        require_finite(positions.data(), count * 3, "position");
        require_finite(quaternions.data(), count * 4, "quaternion");
        require_finite(velocities.data(), count * 3, "velocity");
        require_finite(gyro_biases.data(), count * 3, "gyro bias");
        require_finite(accel_biases.data(), count * 3, "accelerometer bias");
        for (size_t row = 0; row < count; ++row) {
            const double *quaternion = quaternions.data() + row * 4;
            if (quaternion[0] == 0.0 && quaternion[1] == 0.0 &&
                quaternion[2] == 0.0 && quaternion[3] == 0.0)
                throw std::invalid_argument(
                    "state_trajectory: quaternions must be nonzero");
            const size_t w_index =
                quaternion_order == "wxyz" ? 0 : 3;
            if (quaternion_sign == "canonical_positive_w" &&
                quaternion[w_index] < 0.0)
                throw std::invalid_argument(
                    "state_trajectory: canonical_positive_w quaternions "
                    "must have a nonnegative W coefficient");
        }

        if (count != 0) {
            trajectory.timestamps_ns.assign(timestamps, timestamps + count);
            trajectory.positions.assign(
                positions.data(), positions.data() + count * 3);
            trajectory.quaternions.assign(
                quaternions.data(), quaternions.data() + count * 4);
            trajectory.velocities.assign(
                velocities.data(), velocities.data() + count * 3);
            trajectory.gyro_biases.assign(
                gyro_biases.data(), gyro_biases.data() + count * 3);
            trajectory.accel_biases.assign(
                accel_biases.data(), accel_biases.data() + count * 3);
        }
    }
    return trajectory;
}

}  // namespace

void register_state_trajectory(nb::module_ &module) {
    const auto reference_internal = nb::rv_policy::reference_internal;
    nb::class_<StateTrajectory>(module, "StateTrajectory")
        .def_prop_ro(
            "num_states",
            [](const StateTrajectory &value) { return value.num_states(); })
        .def_prop_ro(
            "timestamps_ns",
            [](const StateTrajectory &value) {
                return trajectory_view(value.timestamps_ns, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "positions",
            [](const StateTrajectory &value) {
                return trajectory_view(value.positions, {value.n, 3});
            },
            reference_internal)
        .def_prop_ro(
            "quaternions",
            [](const StateTrajectory &value) {
                return trajectory_view(value.quaternions, {value.n, 4});
            },
            reference_internal)
        .def_prop_ro(
            "velocities",
            [](const StateTrajectory &value) {
                return trajectory_view(value.velocities, {value.n, 3});
            },
            reference_internal)
        .def_prop_ro(
            "gyro_biases",
            [](const StateTrajectory &value) {
                return trajectory_view(value.gyro_biases, {value.n, 3});
            },
            reference_internal)
        .def_prop_ro(
            "accel_biases",
            [](const StateTrajectory &value) {
                return trajectory_view(value.accel_biases, {value.n, 3});
            },
            reference_internal)
        .def_ro("quaternion_order", &StateTrajectory::quaternion_order)
        .def_ro("quaternion_sign", &StateTrajectory::quaternion_sign)
        .def_ro("pose_convention", &StateTrajectory::pose_convention)
        .def_ro("position_frame", &StateTrajectory::position_frame)
        .def_ro("velocity_frame", &StateTrajectory::velocity_frame)
        .def_ro("bias_frame", &StateTrajectory::bias_frame)
        .def_ro("position_unit", &StateTrajectory::position_unit)
        .def_ro("velocity_unit", &StateTrajectory::velocity_unit)
        .def_ro("gyro_bias_unit", &StateTrajectory::gyro_bias_unit)
        .def_ro("accel_bias_unit", &StateTrajectory::accel_bias_unit)
        .def_ro("timestamp_unit", &StateTrajectory::timestamp_unit)
        .def(
            "__repr__",
            [](const StateTrajectory &value) {
                return "<StateTrajectory n=" +
                       std::to_string(value.n) + " " +
                       value.pose_convention + " " +
                       value.quaternion_order + ">";
            });

    module.def(
        "state_trajectory", &make_state_trajectory,
        "timestamps_ns"_a, "positions"_a, "quaternions"_a,
        "velocities"_a, "gyro_biases"_a, "accel_biases"_a,
        "quaternion_order"_a = "wxyz",
        "quaternion_sign"_a = "preserved",
        "pose_convention"_a = "sensor_to_reference",
        "position_frame"_a = "reference",
        "velocity_frame"_a = "reference",
        "bias_frame"_a = "sensor",
        "position_unit"_a = "meters",
        "velocity_unit"_a = "meters_per_second",
        "gyro_bias_unit"_a = "radians_per_second",
        "accel_bias_unit"_a = "meters_per_second_squared",
        "timestamp_unit"_a = "nanoseconds",
        "Build a StateTrajectory from exact int64 nanosecond timestamps "
        "and float64 SoA state channels. Inputs are copied into record-owned "
        "storage; convention and unit metadata are validated.");
}
