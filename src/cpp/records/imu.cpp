// records/imu.cpp -- ImuCalibration/ImuSequence validation and bindings.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <cmath>
#include <limits>
#include <string>

#include "records/imu.hpp"

using namespace nb::literals;

namespace {

constexpr size_t kImuTextLimit = 1024 * 1024;
constexpr double kQuaternionNormTolerance = 1e-9;

using i64_array =
    nb::ndarray<const int64_t, nb::c_contig, nb::device::cpu>;
using f64_array =
    nb::ndarray<const double, nb::c_contig, nb::device::cpu>;

void validate_text(
    const std::string &value, const char *name, bool allow_empty = false) {
    if (value.empty() && !allow_empty)
        throw std::invalid_argument(
            std::string("imu: ") + name + " must be non-empty");
    if (value.size() > kImuTextLimit)
        throw std::invalid_argument(
            std::string("imu: ") + name + " exceeds 1 MiB");
    if (value.find('\0') != std::string::npos)
        throw std::invalid_argument(
            std::string("imu: ") + name + " contains embedded NUL");
    if (!sio::valid_utf8(value))
        throw std::invalid_argument(
            std::string("imu: ") + name + " must be valid UTF-8");
    for (unsigned char character : value)
        if (character < 0x20)
            throw std::invalid_argument(
                std::string("imu: ") + name +
                " cannot contain control characters");
}

void validate_optional_nonnegative(
    const std::optional<double> &value, const char *name) {
    if (value && (!std::isfinite(*value) || *value < 0.0))
        throw std::invalid_argument(
            std::string("imu_calibration: ") + name +
            " must be finite and nonnegative when present");
}

void require_vector(
    const f64_array &array, size_t count, const char *name) {
    if (array.ndim() != 1 || array.shape(0) != count)
        throw std::invalid_argument(
            std::string("imu_calibration: ") + name + " must be (" +
            std::to_string(count) + ",) float64");
}

void require_matrix(
    const f64_array &array, size_t rows, const char *name) {
    if (array.ndim() != 2 || array.shape(0) != rows ||
        array.shape(1) != 3)
        throw std::invalid_argument(
            std::string("imu_sequence: ") + name +
            " must be (N,3) float64");
}

ImuCalibration make_imu_calibration(
    uint32_t sensor_id,
    const std::string &name,
    const std::string &topic,
    f64_array quaternion,
    f64_array translation,
    std::optional<double> nominal_rate_hz,
    std::optional<double> gyroscope_noise_density,
    std::optional<double> gyroscope_random_walk,
    std::optional<double> accelerometer_noise_density,
    std::optional<double> accelerometer_random_walk,
    std::optional<int64_t> time_offset_ns,
    const std::string &quaternion_order,
    const std::string &quaternion_sign,
    const std::string &sensor_axis_frame,
    const std::string &reference_frame) {
    require_vector(quaternion, 4, "quaternion");
    require_vector(translation, 3, "translation");
    validate_text(name, "name");
    validate_text(topic, "topic", true);
    validate_text(reference_frame, "reference_frame");
    if (!imu_valid_quaternion_order(quaternion_order))
        throw std::invalid_argument(
            "imu_calibration: quaternion_order must be wxyz|xyzw");
    if (!imu_valid_quaternion_sign(quaternion_sign))
        throw std::invalid_argument(
            "imu_calibration: quaternion_sign must be "
            "preserved|canonical_positive_w");
    if (!imu_valid_axis_frame(sensor_axis_frame))
        throw std::invalid_argument(
            "imu_calibration: sensor_axis_frame must be sensor|enu|ned");
    if (nominal_rate_hz &&
        (!std::isfinite(*nominal_rate_hz) || *nominal_rate_hz <= 0.0))
        throw std::invalid_argument(
            "imu_calibration: nominal_rate_hz must be finite and positive "
            "when present");
    validate_optional_nonnegative(
        gyroscope_noise_density, "gyroscope_noise_density");
    validate_optional_nonnegative(
        gyroscope_random_walk, "gyroscope_random_walk");
    validate_optional_nonnegative(
        accelerometer_noise_density, "accelerometer_noise_density");
    validate_optional_nonnegative(
        accelerometer_random_walk, "accelerometer_random_walk");

    ImuCalibration calibration;
    calibration.sensor_id = sensor_id;
    calibration.name = name;
    calibration.topic = topic;
    calibration.nominal_rate_hz = nominal_rate_hz;
    calibration.gyroscope_noise_density = gyroscope_noise_density;
    calibration.gyroscope_random_walk = gyroscope_random_walk;
    calibration.accelerometer_noise_density =
        accelerometer_noise_density;
    calibration.accelerometer_random_walk =
        accelerometer_random_walk;
    calibration.time_offset_ns = time_offset_ns;
    calibration.quaternion_order = quaternion_order;
    calibration.quaternion_sign = quaternion_sign;
    calibration.sensor_axis_frame = sensor_axis_frame;
    calibration.reference_frame = reference_frame;

    {
        nb::gil_scoped_release release;
        double norm_squared = 0.0;
        for (size_t index = 0; index < 4; ++index) {
            const double value = quaternion.data()[index];
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "imu_calibration: quaternion values must be finite");
            calibration.quaternion[index] = value;
            norm_squared += value * value;
        }
        for (size_t index = 0; index < 3; ++index) {
            const double value = translation.data()[index];
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "imu_calibration: translation values must be finite");
            calibration.translation[index] = value;
        }
        if (!std::isfinite(norm_squared) ||
            std::abs(std::sqrt(norm_squared) - 1.0) >
                kQuaternionNormTolerance)
            throw std::invalid_argument(
                "imu_calibration: quaternion must have unit norm");
        const size_t w_index = quaternion_order == "wxyz" ? 0 : 3;
        if (quaternion_sign == "canonical_positive_w" &&
            calibration.quaternion[w_index] < 0.0)
            throw std::invalid_argument(
                "imu_calibration: canonical_positive_w requires a "
                "nonnegative W coefficient");
    }
    return calibration;
}

ImuSequence make_imu_sequence(
    uint32_t sensor_id,
    i64_array timestamps_ns,
    f64_array angular_velocities,
    f64_array linear_accelerations,
    const std::string &angular_velocity_unit,
    const std::string &linear_acceleration_unit,
    const std::string &sensor_axis_frame,
    const std::string &timestamp_reference,
    const std::string &clock_domain) {
    if (timestamps_ns.ndim() != 1)
        throw std::invalid_argument(
            "imu_sequence: timestamps_ns must be (N,) int64");
    const size_t count = timestamps_ns.shape(0);
    if (count > std::numeric_limits<size_t>::max() / 3)
        throw std::invalid_argument(
            "imu_sequence: sample count overflows field extents");
    require_matrix(angular_velocities, count, "angular_velocities");
    require_matrix(linear_accelerations, count, "linear_accelerations");
    if (!imu_valid_angular_velocity_unit(angular_velocity_unit))
        throw std::invalid_argument(
            "imu_sequence: angular_velocity_unit must be "
            "radians_per_second|degrees_per_second");
    if (!imu_valid_linear_acceleration_unit(linear_acceleration_unit))
        throw std::invalid_argument(
            "imu_sequence: linear_acceleration_unit must be "
            "meters_per_second_squared|standard_gravity");
    if (!imu_valid_axis_frame(sensor_axis_frame))
        throw std::invalid_argument(
            "imu_sequence: sensor_axis_frame must be sensor|enu|ned");
    if (!imu_valid_timestamp_reference(timestamp_reference))
        throw std::invalid_argument(
            "imu_sequence: timestamp_reference must be measurement");
    validate_text(clock_domain, "clock_domain");

    ImuSequence sequence;
    sequence.sensor_id = sensor_id;
    sequence.n = count;
    sequence.angular_velocity_unit = angular_velocity_unit;
    sequence.linear_acceleration_unit = linear_acceleration_unit;
    sequence.sensor_axis_frame = sensor_axis_frame;
    sequence.timestamp_reference = timestamp_reference;
    sequence.clock_domain = clock_domain;

    {
        nb::gil_scoped_release release;
        const int64_t *timestamps = timestamps_ns.data();
        for (size_t index = 0; index < count; ++index) {
            if (timestamps[index] < 0)
                throw std::invalid_argument(
                    "imu_sequence: timestamps must be nonnegative");
            if (index != 0 && timestamps[index] <= timestamps[index - 1])
                throw std::invalid_argument(
                    "imu_sequence: timestamps must be strictly increasing");
        }
        for (size_t index = 0; index < count * 3; ++index) {
            if (!std::isfinite(angular_velocities.data()[index]))
                throw std::invalid_argument(
                    "imu_sequence: angular velocity values must be finite");
            if (!std::isfinite(linear_accelerations.data()[index]))
                throw std::invalid_argument(
                    "imu_sequence: linear acceleration values must be finite");
        }
        if (count != 0) {
            sequence.timestamps_ns.assign(timestamps, timestamps + count);
            sequence.angular_velocities.assign(
                angular_velocities.data(),
                angular_velocities.data() + count * 3);
            sequence.linear_accelerations.assign(
                linear_accelerations.data(),
                linear_accelerations.data() + count * 3);
        }
    }
    return sequence;
}

template <typename T>
nb::ndarray<nb::numpy, const T> imu_sequence_view(
    nb::handle owner,
    const std::vector<T> &values,
    std::vector<size_t> shape) {
    static const T sentinel{};
    const T *data = values.empty() ? &sentinel : values.data();
    return sio::view<const T>(owner, data, std::move(shape));
}

}  // namespace

void register_imu(nb::module_ &module) {
    nb::class_<ImuCalibration>(module, "ImuCalibration")
        .def_ro("sensor_id", &ImuCalibration::sensor_id)
        .def_ro("name", &ImuCalibration::name)
        .def_ro("topic", &ImuCalibration::topic)
        .def_prop_ro(
            "quaternion",
            [](nb::handle_t<ImuCalibration> self) {
                const auto &value = nb::cast<const ImuCalibration &>(self);
                return sio::view<const double>(
                    self, value.quaternion.data(), {4});
            })
        .def_prop_ro(
            "translation",
            [](nb::handle_t<ImuCalibration> self) {
                const auto &value = nb::cast<const ImuCalibration &>(self);
                return sio::view<const double>(
                    self, value.translation.data(), {3});
            })
        .def_ro("nominal_rate_hz", &ImuCalibration::nominal_rate_hz)
        .def_ro(
            "gyroscope_noise_density",
            &ImuCalibration::gyroscope_noise_density)
        .def_ro(
            "gyroscope_random_walk",
            &ImuCalibration::gyroscope_random_walk)
        .def_ro(
            "accelerometer_noise_density",
            &ImuCalibration::accelerometer_noise_density)
        .def_ro(
            "accelerometer_random_walk",
            &ImuCalibration::accelerometer_random_walk)
        .def_ro("time_offset_ns", &ImuCalibration::time_offset_ns)
        .def_ro("quaternion_order", &ImuCalibration::quaternion_order)
        .def_ro("quaternion_sign", &ImuCalibration::quaternion_sign)
        .def_ro("sensor_axis_frame", &ImuCalibration::sensor_axis_frame)
        .def_ro("reference_frame", &ImuCalibration::reference_frame)
        .def_prop_ro(
            "nominal_rate_unit",
            [](const ImuCalibration &) { return "hertz"; })
        .def_prop_ro(
            "transform_convention",
            [](const ImuCalibration &) { return "sensor_to_reference"; })
        .def_prop_ro(
            "translation_unit",
            [](const ImuCalibration &) { return "meters"; })
        .def_prop_ro(
            "gyroscope_noise_density_unit",
            [](const ImuCalibration &) {
                return "radians_per_second_per_sqrt_hertz";
            })
        .def_prop_ro(
            "gyroscope_random_walk_unit",
            [](const ImuCalibration &) {
                return "radians_per_second_squared_per_sqrt_hertz";
            })
        .def_prop_ro(
            "accelerometer_noise_density_unit",
            [](const ImuCalibration &) {
                return "meters_per_second_squared_per_sqrt_hertz";
            })
        .def_prop_ro(
            "accelerometer_random_walk_unit",
            [](const ImuCalibration &) {
                return "meters_per_second_cubed_per_sqrt_hertz";
            })
        .def_prop_ro(
            "time_offset_convention",
            [](const ImuCalibration &) {
                return "reference_time_ns = sensor_time_ns + time_offset_ns";
            })
        .def_prop_ro(
            "time_offset_unit",
            [](const ImuCalibration &) { return "nanoseconds"; })
        .def(
            "__repr__",
            [](const ImuCalibration &value) {
                return "<ImuCalibration sensor_id=" +
                       std::to_string(value.sensor_id) + " name='" +
                       value.name + "'>";
            });

    nb::class_<ImuSequence>(module, "ImuSequence")
        .def_ro("sensor_id", &ImuSequence::sensor_id)
        .def_prop_ro(
            "num_samples",
            [](const ImuSequence &value) { return value.num_samples(); })
        .def_prop_ro(
            "timestamps_ns",
            [](nb::handle_t<ImuSequence> self) {
                const auto &value = nb::cast<const ImuSequence &>(self);
                return imu_sequence_view(
                    self, value.timestamps_ns, {value.n});
            })
        .def_prop_ro(
            "angular_velocities",
            [](nb::handle_t<ImuSequence> self) {
                const auto &value = nb::cast<const ImuSequence &>(self);
                return imu_sequence_view(
                    self, value.angular_velocities, {value.n, 3});
            })
        .def_prop_ro(
            "linear_accelerations",
            [](nb::handle_t<ImuSequence> self) {
                const auto &value = nb::cast<const ImuSequence &>(self);
                return imu_sequence_view(
                    self, value.linear_accelerations, {value.n, 3});
            })
        .def_ro(
            "angular_velocity_unit",
            &ImuSequence::angular_velocity_unit)
        .def_ro(
            "linear_acceleration_unit",
            &ImuSequence::linear_acceleration_unit)
        .def_ro("sensor_axis_frame", &ImuSequence::sensor_axis_frame)
        .def_ro("timestamp_reference", &ImuSequence::timestamp_reference)
        .def_ro("clock_domain", &ImuSequence::clock_domain)
        .def_prop_ro(
            "timestamp_unit",
            [](const ImuSequence &) { return "nanoseconds"; })
        .def(
            "__repr__",
            [](const ImuSequence &value) {
                return "<ImuSequence sensor_id=" +
                       std::to_string(value.sensor_id) + " n=" +
                       std::to_string(value.n) + ">";
            });

    module.def(
        "imu_calibration", &make_imu_calibration,
        "sensor_id"_a, "name"_a, "topic"_a,
        "quaternion"_a, "translation"_a,
        nb::kw_only(),
        "nominal_rate_hz"_a = nb::none(),
        "gyroscope_noise_density"_a = nb::none(),
        "gyroscope_random_walk"_a = nb::none(),
        "accelerometer_noise_density"_a = nb::none(),
        "accelerometer_random_walk"_a = nb::none(),
        "time_offset_ns"_a = nb::none(),
        "quaternion_order"_a = "wxyz",
        "quaternion_sign"_a = "preserved",
        "sensor_axis_frame"_a = "sensor",
        "reference_frame"_a = "body",
        "Build one IMU calibration with a metric sensor-to-reference "
        "transform, optional rate/noise terms, and an exact clock offset.");

    module.def(
        "imu_sequence", &make_imu_sequence,
        "sensor_id"_a, "timestamps_ns"_a,
        "angular_velocities"_a, "linear_accelerations"_a,
        nb::kw_only(),
        "angular_velocity_unit"_a = "radians_per_second",
        "linear_acceleration_unit"_a =
            "meters_per_second_squared",
        "sensor_axis_frame"_a = "sensor",
        "timestamp_reference"_a = "measurement",
        "clock_domain"_a = "sensor",
        "Build a raw IMU sequence from exact int64 nanosecond timestamps "
        "and float64 measurement rows. Inputs are copied into owned storage.");
}
