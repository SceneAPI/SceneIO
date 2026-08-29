// codecs/reconstruction/euroc_state.cpp -- EuRoC MAV state and IMU CSV.
//
// Canonical schema (17 columns):
// timestamp ns, position p_RS_R, quaternion q_RS (WXYZ), velocity v_RS_R,
// gyroscope bias b_w_RS_S, accelerometer bias b_a_RS_S.
//
// Parsing is bounded and allocation is proportional to validated input. The
// decoder accepts any contiguous buffer exporter, so the public path can mmap.
// Writers preserve all coefficients and refuse convention metadata that the
// EuRoC header cannot express. A live file sink receives bounded row chunks.
#include <nanobind/stl/string.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <string_view>

#include "fast_float/fast_float.h"
#include "records/imu.hpp"
#include "records/state_trajectory.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kLineLimit = 1024 * 1024;
constexpr size_t kChunkRows = 2048;
constexpr std::array<std::string_view, 17> kHeaderFields = {
    "#timestamp [ns]",
    "p_RS_R_x [m]", "p_RS_R_y [m]", "p_RS_R_z [m]",
    "q_RS_w []", "q_RS_x []", "q_RS_y []", "q_RS_z []",
    "v_RS_R_x [m s^-1]", "v_RS_R_y [m s^-1]",
    "v_RS_R_z [m s^-1]",
    "b_w_RS_S_x [rad s^-1]", "b_w_RS_S_y [rad s^-1]",
    "b_w_RS_S_z [rad s^-1]",
    "b_a_RS_S_x [m s^-2]", "b_a_RS_S_y [m s^-2]",
    "b_a_RS_S_z [m s^-2]",
};

constexpr std::array<std::string_view, 7> kImuHeaderFields = {
    "#timestamp [ns]",
    "w_RS_S_x [rad s^-1]", "w_RS_S_y [rad s^-1]",
    "w_RS_S_z [rad s^-1]", "a_RS_S_x [m s^-2]",
    "a_RS_S_y [m s^-2]", "a_RS_S_z [m s^-2]",
};

constexpr std::string_view kCanonicalHeader =
    "#timestamp [ns],p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],"
    "q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z [],"
    "v_RS_R_x [m s^-1],v_RS_R_y [m s^-1],v_RS_R_z [m s^-1],"
    "b_w_RS_S_x [rad s^-1],b_w_RS_S_y [rad s^-1],"
    "b_w_RS_S_z [rad s^-1],b_a_RS_S_x [m s^-2],"
    "b_a_RS_S_y [m s^-2],b_a_RS_S_z [m s^-2]\n";

constexpr std::string_view kCanonicalImuHeader =
    "#timestamp [ns],w_RS_S_x [rad s^-1],"
    "w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],"
    "a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]\n";

std::string_view trim(std::string_view value) {
    while (!value.empty() &&
           (value.front() == ' ' || value.front() == '\t' ||
            value.front() == '\r'))
        value.remove_prefix(1);
    while (!value.empty() &&
           (value.back() == ' ' || value.back() == '\t' ||
            value.back() == '\r'))
        value.remove_suffix(1);
    return value;
}

template <typename Callback>
void for_each_line(
    const uint8_t *bytes, size_t size, Callback callback,
    const char *context = "EuRoC state") {
    const char *cursor = reinterpret_cast<const char *>(bytes);
    const char *const end = cursor + size;
    size_t line_number = 0;
    while (cursor < end) {
        ++line_number;
        const size_t remaining =
            static_cast<size_t>(end - cursor);
        const size_t search =
            std::min(remaining, kLineLimit + 1);
        const void *newline = std::memchr(cursor, '\n', search);
        if (!newline && remaining > kLineLimit)
            throw std::invalid_argument(
                std::string(context) + ": line exceeds 1 MiB");
        const char *line_end =
            newline ? static_cast<const char *>(newline) : end;
        const size_t line_size =
            static_cast<size_t>(line_end - cursor);
        if (line_size > kLineLimit)
            throw std::invalid_argument(
                std::string(context) + ": line exceeds 1 MiB");
        if (std::memchr(cursor, '\0', line_size))
            throw std::invalid_argument(
                std::string(context) + ": NUL byte in text input");
        callback(
            std::string_view(cursor, line_size), line_number);
        cursor = newline ? line_end + 1 : end;
    }
}

std::array<std::string_view, 17> split_17(
    std::string_view line, size_t line_number) {
    std::array<std::string_view, 17> fields;
    size_t begin = 0;
    for (size_t field = 0; field < fields.size(); ++field) {
        const size_t comma = line.find(',', begin);
        if (field + 1 == fields.size()) {
            if (comma != std::string_view::npos)
                throw std::invalid_argument(
                    "EuRoC state: line " +
                    std::to_string(line_number) +
                    " must contain exactly 17 columns");
            fields[field] = trim(line.substr(begin));
        } else {
            if (comma == std::string_view::npos)
                throw std::invalid_argument(
                    "EuRoC state: line " +
                    std::to_string(line_number) +
                    " must contain exactly 17 columns");
            fields[field] =
                trim(line.substr(begin, comma - begin));
            begin = comma + 1;
        }
        if (fields[field].empty())
            throw std::invalid_argument(
                "EuRoC state: line " +
                std::to_string(line_number) +
                " contains an empty column");
    }
    return fields;
}

std::array<std::string_view, 7> split_7(
    std::string_view line, size_t line_number) {
    std::array<std::string_view, 7> fields;
    size_t begin = 0;
    for (size_t field = 0; field < fields.size(); ++field) {
        const size_t comma = line.find(',', begin);
        if (field + 1 == fields.size()) {
            if (comma != std::string_view::npos)
                throw std::invalid_argument(
                    "EuRoC IMU: line " +
                    std::to_string(line_number) +
                    " must contain exactly 7 columns");
            fields[field] = trim(line.substr(begin));
        } else {
            if (comma == std::string_view::npos)
                throw std::invalid_argument(
                    "EuRoC IMU: line " +
                    std::to_string(line_number) +
                    " must contain exactly 7 columns");
            fields[field] =
                trim(line.substr(begin, comma - begin));
            begin = comma + 1;
        }
        if (fields[field].empty())
            throw std::invalid_argument(
                "EuRoC IMU: line " + std::to_string(line_number) +
                " contains an empty column");
    }
    return fields;
}

void validate_header(
    std::string_view line, size_t line_number, bool first_line) {
    if (first_line && line.size() >= 3 &&
        static_cast<uint8_t>(line[0]) == 0xef &&
        static_cast<uint8_t>(line[1]) == 0xbb &&
        static_cast<uint8_t>(line[2]) == 0xbf)
        line.remove_prefix(3);
    const auto fields = split_17(line, line_number);
    for (size_t field = 0; field < fields.size(); ++field)
        if (fields[field] != kHeaderFields[field])
            throw std::invalid_argument(
                "EuRoC state: header does not match the 17-column "
                "ground-truth schema");
}

void validate_imu_header(
    std::string_view line, size_t line_number, bool first_line) {
    if (first_line && line.size() >= 3 &&
        static_cast<uint8_t>(line[0]) == 0xef &&
        static_cast<uint8_t>(line[1]) == 0xbb &&
        static_cast<uint8_t>(line[2]) == 0xbf)
        line.remove_prefix(3);
    const auto fields = split_7(line, line_number);
    for (size_t field = 0; field < fields.size(); ++field)
        if (fields[field] != kImuHeaderFields[field])
            throw std::invalid_argument(
                "EuRoC IMU: header does not match the 7-column "
                "inertial schema");
}

int64_t parse_timestamp(
    std::string_view token, size_t line_number,
    const char *context = "EuRoC state") {
    uint64_t value = 0;
    const auto result = std::from_chars(
        token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size() ||
        value > static_cast<uint64_t>(
                    std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument(
            std::string(context) + ": line " +
            std::to_string(line_number) +
            " has an invalid nonnegative int64 timestamp");
    return static_cast<int64_t>(value);
}

double parse_number(
    std::string_view token, size_t line_number,
    const char *context = "EuRoC state") {
    double value = 0.0;
    const auto result = fast_float::from_chars(
        token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size() ||
        !std::isfinite(value))
        throw std::invalid_argument(
            std::string(context) + ": line " +
            std::to_string(line_number) +
            " has an invalid or non-finite numeric value");
    return value;
}

void append_selected(
    StateTrajectory &trajectory, int64_t timestamp,
    const std::array<double, 16> &values) {
    trajectory.timestamps_ns.push_back(timestamp);
    trajectory.positions.insert(
        trajectory.positions.end(), values.begin(), values.begin() + 3);
    trajectory.quaternions.insert(
        trajectory.quaternions.end(), values.begin() + 3,
        values.begin() + 7);
    trajectory.velocities.insert(
        trajectory.velocities.end(), values.begin() + 7,
        values.begin() + 10);
    trajectory.gyro_biases.insert(
        trajectory.gyro_biases.end(), values.begin() + 10,
        values.begin() + 13);
    trajectory.accel_biases.insert(
        trajectory.accel_biases.end(), values.begin() + 13,
        values.end());
}

struct ScanResult {
    StateTrajectory trajectory;
    size_t total_states = 0;
    int64_t first_timestamp = -1;
    int64_t last_timestamp = -1;
};

ScanResult decode(
    const uint8_t *bytes, size_t size, bool partial,
    size_t start, size_t stop, bool collect = true) {
    if (partial && start >= stop)
        throw std::invalid_argument(
            "EuRoC state range must be a non-empty half-open range");

    ScanResult result;
    StateTrajectory &trajectory = result.trajectory;
    const size_t possible_rows =
        std::min<size_t>(size / 34 + 1, size);
    const size_t reserve_rows =
        partial ? std::min(stop - start, possible_rows)
                : possible_rows;
    if (collect) {
        trajectory.timestamps_ns.reserve(reserve_rows);
        trajectory.positions.reserve(reserve_rows * 3);
        trajectory.quaternions.reserve(reserve_rows * 4);
        trajectory.velocities.reserve(reserve_rows * 3);
        trajectory.gyro_biases.reserve(reserve_rows * 3);
        trajectory.accel_biases.reserve(reserve_rows * 3);
    }

    bool header_seen = false;
    bool any_line_seen = false;
    size_t state_index = 0;
    int64_t previous_timestamp = -1;
    for_each_line(
        bytes, size,
        [&](std::string_view line, size_t line_number) {
            const std::string_view stripped = trim(line);
            if (stripped.empty()) return;
            const bool first_nonblank = !any_line_seen;
            any_line_seen = true;
            if (!header_seen) {
                validate_header(
                    stripped, line_number, first_nonblank);
                header_seen = true;
                return;
            }
            if (stripped.front() == '#') return;
            const auto fields = split_17(stripped, line_number);
            const int64_t timestamp =
                parse_timestamp(fields[0], line_number);
            if (timestamp <= previous_timestamp)
                throw std::invalid_argument(
                    "EuRoC state: timestamps must be strictly increasing");
            previous_timestamp = timestamp;
            if (state_index == 0)
                result.first_timestamp = timestamp;
            result.last_timestamp = timestamp;
            std::array<double, 16> values;
            for (size_t field = 0; field < values.size(); ++field)
                values[field] =
                    parse_number(fields[field + 1], line_number);
            if (values[3] == 0.0 && values[4] == 0.0 &&
                values[5] == 0.0 && values[6] == 0.0)
                throw std::invalid_argument(
                    "EuRoC state: quaternions must be nonzero");
            if (collect &&
                (!partial ||
                 (state_index >= start && state_index < stop)))
                append_selected(trajectory, timestamp, values);
            ++state_index;
        });
    if (!header_seen)
        throw std::invalid_argument(
            "EuRoC state: missing 17-column header");
    if (partial && stop > state_index)
        throw std::invalid_argument(
            "EuRoC state range exceeds the available extent");
    trajectory.n = trajectory.timestamps_ns.size();
    result.total_states = state_index;
    return result;
}

struct ImuScanResult {
    ImuSequence sequence;
    size_t total_samples = 0;
    int64_t first_timestamp = -1;
    int64_t last_timestamp = -1;
};

ImuScanResult decode_imu(
    const uint8_t *bytes, size_t size, bool partial,
    int64_t start_ns, int64_t stop_ns, bool collect = true) {
    if (partial && (start_ns < 0 || start_ns >= stop_ns))
        throw std::invalid_argument(
            "EuRoC IMU time range must be a nonnegative, non-empty "
            "half-open interval");

    ImuScanResult result;
    ImuSequence &sequence = result.sequence;
    size_t possible_rows = 0;
    if (size != 0) {
        possible_rows = static_cast<size_t>(
            std::count(bytes, bytes + size, uint8_t{'\n'}));
        if (bytes[size - 1] != uint8_t{'\n'}) ++possible_rows;
    }
    const size_t reserve_rows =
        partial ? std::min<size_t>(possible_rows, 1024)
                : possible_rows;
    if (possible_rows > std::numeric_limits<size_t>::max() / 3)
        throw std::invalid_argument(
            "EuRoC IMU: input extent overflows sample storage");
    if (collect) {
        sequence.timestamps_ns.reserve(reserve_rows);
        sequence.angular_velocities.reserve(reserve_rows * 3);
        sequence.linear_accelerations.reserve(reserve_rows * 3);
    }

    bool header_seen = false;
    bool any_line_seen = false;
    int64_t previous_timestamp = -1;
    for_each_line(
        bytes, size,
        [&](std::string_view line, size_t line_number) {
            const std::string_view stripped = trim(line);
            if (stripped.empty()) return;
            const bool first_nonblank = !any_line_seen;
            any_line_seen = true;
            if (!header_seen) {
                validate_imu_header(
                    stripped, line_number, first_nonblank);
                header_seen = true;
                return;
            }
            if (stripped.front() == '#') return;
            const auto fields = split_7(stripped, line_number);
            const int64_t timestamp =
                parse_timestamp(
                    fields[0], line_number, "EuRoC IMU");
            if (timestamp <= previous_timestamp)
                throw std::invalid_argument(
                    "EuRoC IMU: timestamps must be strictly increasing");
            previous_timestamp = timestamp;
            if (result.total_samples == 0)
                result.first_timestamp = timestamp;
            result.last_timestamp = timestamp;
            std::array<double, 6> values;
            for (size_t field = 0; field < values.size(); ++field)
                values[field] =
                    parse_number(
                        fields[field + 1], line_number,
                        "EuRoC IMU");
            if (collect &&
                (!partial ||
                 (timestamp >= start_ns && timestamp < stop_ns))) {
                sequence.timestamps_ns.push_back(timestamp);
                sequence.angular_velocities.insert(
                    sequence.angular_velocities.end(),
                    values.begin(), values.begin() + 3);
                sequence.linear_accelerations.insert(
                    sequence.linear_accelerations.end(),
                    values.begin() + 3, values.end());
            }
            ++result.total_samples;
        },
        "EuRoC IMU");
    if (!header_seen)
        throw std::invalid_argument(
            "EuRoC IMU: missing 7-column header");
    sequence.n = sequence.timestamps_ns.size();
    return result;
}

ImuSequence read_euroc_imu(
    nb::handle source, uint32_t sensor_id,
    const std::string &clock_domain) {
    ByteView view(source);
    ImuSequence sequence;
    {
        nb::gil_scoped_release release;
        sequence = std::move(
            decode_imu(
                view.data(), view.size(), false, 0, 0).sequence);
        sequence.sensor_id = sensor_id;
        sequence.clock_domain = clock_domain;
        validate_imu_sequence(sequence, "EuRoC IMU");
    }
    return sequence;
}

ImuSequence read_euroc_imu_time_range(
    nb::handle source, int64_t start_ns, int64_t stop_ns,
    uint32_t sensor_id, const std::string &clock_domain) {
    ByteView view(source);
    ImuSequence sequence;
    {
        nb::gil_scoped_release release;
        sequence = std::move(
            decode_imu(
                view.data(), view.size(), true,
                start_ns, stop_ns).sequence);
        sequence.sensor_id = sensor_id;
        sequence.clock_domain = clock_domain;
        validate_imu_sequence(sequence, "EuRoC IMU");
    }
    return sequence;
}

nb::tuple inspect_euroc_imu(nb::handle source) {
    ByteView view(source);
    ImuScanResult result;
    {
        nb::gil_scoped_release release;
        result = decode_imu(
            view.data(), view.size(), false, 0, 0, false);
    }
    return nb::make_tuple(
        result.total_samples,
        result.first_timestamp,
        result.last_timestamp);
}

StateTrajectory read_euroc_state(nb::handle source) {
    ByteView view(source);
    StateTrajectory trajectory;
    {
        nb::gil_scoped_release release;
        trajectory = std::move(
            decode(view.data(), view.size(), false, 0, 0).trajectory);
    }
    return trajectory;
}

StateTrajectory read_euroc_state_states(
    nb::handle source, size_t start, size_t stop) {
    ByteView view(source);
    StateTrajectory trajectory;
    {
        nb::gil_scoped_release release;
        trajectory = std::move(
            decode(
                view.data(), view.size(), true, start, stop).trajectory);
    }
    return trajectory;
}

nb::tuple inspect_euroc_state(nb::handle source) {
    ByteView view(source);
    ScanResult result;
    {
        nb::gil_scoped_release release;
        result = decode(
            view.data(), view.size(), false, 0, 0, false);
    }
    return nb::make_tuple(
        result.total_states,
        result.first_timestamp,
        result.last_timestamp);
}

void validate_write(const StateTrajectory &trajectory) {
    const size_t count = trajectory.n;
    if (count > std::numeric_limits<size_t>::max() / 4 ||
        trajectory.timestamps_ns.size() != count ||
        trajectory.positions.size() != count * 3 ||
        trajectory.quaternions.size() != count * 4 ||
        trajectory.velocities.size() != count * 3 ||
        trajectory.gyro_biases.size() != count * 3 ||
        trajectory.accel_biases.size() != count * 3)
        throw std::invalid_argument(
            "EuRoC state: inconsistent StateTrajectory field lengths");
    if (trajectory.quaternion_order != "wxyz" ||
        trajectory.quaternion_sign != "preserved" ||
        trajectory.pose_convention != "sensor_to_reference" ||
        trajectory.position_frame != "reference" ||
        trajectory.velocity_frame != "reference" ||
        trajectory.bias_frame != "sensor" ||
        trajectory.position_unit != "meters" ||
        trajectory.velocity_unit != "meters_per_second" ||
        trajectory.gyro_bias_unit != "radians_per_second" ||
        trajectory.accel_bias_unit !=
            "meters_per_second_squared" ||
        trajectory.timestamp_unit != "nanoseconds")
        throw std::invalid_argument(
            "EuRoC state: record conventions are not representable by "
            "the ground-truth CSV schema");
    for (size_t row = 0; row < count; ++row) {
        const int64_t timestamp = trajectory.timestamps_ns[row];
        if (timestamp < 0 ||
            (row != 0 &&
             timestamp <= trajectory.timestamps_ns[row - 1]))
            throw std::invalid_argument(
                "EuRoC state: timestamps must be nonnegative and "
                "strictly increasing");
        const std::array<const std::vector<double> *, 5> arrays = {
            &trajectory.positions, &trajectory.quaternions,
            &trajectory.velocities, &trajectory.gyro_biases,
            &trajectory.accel_biases};
        for (const std::vector<double> *array : arrays) {
            const size_t width =
                array == &trajectory.quaternions ? 4 : 3;
            const size_t offset = row * width;
            for (size_t component = 0; component < width; ++component)
                if (!std::isfinite((*array)[offset + component]))
                    throw std::invalid_argument(
                        "EuRoC state: state values must be finite");
        }
        const double *quaternion =
            trajectory.quaternions.data() + row * 4;
        if (quaternion[0] == 0.0 && quaternion[1] == 0.0 &&
            quaternion[2] == 0.0 && quaternion[3] == 0.0)
            throw std::invalid_argument(
                "EuRoC state: quaternions must be nonzero");
    }
}

void append_number(std::string &output, double value) {
    char buffer[64];
    const int length =
        std::snprintf(buffer, sizeof(buffer), "%.17g", value);
    if (length <= 0 ||
        static_cast<size_t>(length) >= sizeof(buffer))
        throw std::runtime_error(
            "EuRoC state: numeric formatting failed");
    output.append(buffer, static_cast<size_t>(length));
}

void append_row(
    std::string &output, const StateTrajectory &trajectory,
    size_t row) {
    output += std::to_string(trajectory.timestamps_ns[row]);
    const std::array<const std::vector<double> *, 5> arrays = {
        &trajectory.positions, &trajectory.quaternions,
        &trajectory.velocities, &trajectory.gyro_biases,
        &trajectory.accel_biases};
    for (const std::vector<double> *array : arrays) {
        const size_t width =
            array == &trajectory.quaternions ? 4 : 3;
        const size_t offset = row * width;
        for (size_t component = 0; component < width; ++component) {
            output += ',';
            append_number(output, (*array)[offset + component]);
        }
    }
    output += '\n';
}

nb::bytes write_euroc_state(const StateTrajectory &trajectory) {
    {
        nb::gil_scoped_release release;
        validate_write(trajectory);
    }
    if (!emit_file_chunk(
            kCanonicalHeader.data(), kCanonicalHeader.size())) {
        std::string output(kCanonicalHeader);
        {
            nb::gil_scoped_release release;
            for (size_t row = 0; row < trajectory.n; ++row)
                append_row(output, trajectory, row);
        }
        return nb::bytes(output.data(), output.size());
    }
    for (size_t begin = 0; begin < trajectory.n;
         begin += kChunkRows) {
        const size_t end =
            std::min(trajectory.n, begin + kChunkRows);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            for (size_t row = begin; row < end; ++row)
                append_row(chunk, trajectory, row);
        }
        emit_file_chunk(chunk.data(), chunk.size());
    }
    return nb::bytes("", 0);
}

void validate_imu_write(const ImuSequence &sequence) {
    validate_imu_sequence(sequence, "EuRoC IMU");
    if (sequence.angular_velocity_unit != "radians_per_second" ||
        sequence.linear_acceleration_unit !=
            "meters_per_second_squared" ||
        sequence.sensor_axis_frame != "sensor" ||
        sequence.timestamp_reference != "measurement")
        throw std::invalid_argument(
            "EuRoC IMU: record conventions are not representable by "
            "the 7-column inertial CSV schema");
}

void append_imu_row(
    std::string &output, const ImuSequence &sequence, size_t row) {
    output += std::to_string(sequence.timestamps_ns[row]);
    const std::array<const std::vector<double> *, 2> arrays = {
        &sequence.angular_velocities,
        &sequence.linear_accelerations};
    for (const std::vector<double> *array : arrays) {
        for (size_t component = 0; component < 3; ++component) {
            output += ',';
            append_number(output, (*array)[row * 3 + component]);
        }
    }
    output += '\n';
}

nb::bytes write_euroc_imu(const ImuSequence &sequence) {
    {
        nb::gil_scoped_release release;
        validate_imu_write(sequence);
    }
    if (!emit_file_chunk(
            kCanonicalImuHeader.data(),
            kCanonicalImuHeader.size())) {
        std::string output(kCanonicalImuHeader);
        {
            nb::gil_scoped_release release;
            for (size_t row = 0; row < sequence.n; ++row)
                append_imu_row(output, sequence, row);
        }
        return nb::bytes(output.data(), output.size());
    }
    for (size_t begin = 0; begin < sequence.n;
         begin += kChunkRows) {
        const size_t end =
            std::min(sequence.n, begin + kChunkRows);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            for (size_t row = begin; row < end; ++row)
                append_imu_row(chunk, sequence, row);
        }
        emit_file_chunk(chunk.data(), chunk.size());
    }
    return nb::bytes("", 0);
}

}  // namespace

void register_euroc_state(nb::module_ &module) {
    module.def(
        "_inspect_euroc_state", &inspect_euroc_state, "data"_a,
        "Validate a EuRoC state CSV and return count/first/last "
        "timestamps without constructing state arrays.");
    module.def(
        "read_euroc_state", &read_euroc_state, "data"_a,
        "Decode a EuRoC MAV 17-column ground-truth CSV into a "
        "StateTrajectory.");
    module.def(
        "read_euroc_state_states", &read_euroc_state_states,
        "data"_a, "start"_a, "stop"_a,
        "Decode a half-open state range while validating the complete "
        "EuRoC CSV.");
    module.def(
        "write_euroc_state", &write_euroc_state, "trajectory"_a,
        "Encode a convention-compatible StateTrajectory as deterministic "
        "EuRoC MAV ground-truth CSV.");
    module.def(
        "_inspect_euroc_imu", &inspect_euroc_imu, "data"_a,
        "Validate a EuRoC 7-column IMU CSV and return "
        "count/first/last timestamps without constructing sample arrays.");
    module.def(
        "read_euroc_imu", &read_euroc_imu,
        "data"_a, "sensor_id"_a = 0,
        "clock_domain"_a = "sensor",
        "Decode a EuRoC 7-column inertial CSV into an ImuSequence.");
    module.def(
        "read_euroc_imu_time_range", &read_euroc_imu_time_range,
        "data"_a, "start_ns"_a, "stop_ns"_a,
        "sensor_id"_a = 0, "clock_domain"_a = "sensor",
        "Decode a half-open nanosecond range while validating the "
        "complete EuRoC inertial CSV.");
    module.def(
        "write_euroc_imu", &write_euroc_imu, "sequence"_a,
        "Encode a convention-compatible ImuSequence as deterministic "
        "EuRoC 7-column inertial CSV.");
}
