// University of Washington Bundle Adjustment in the Large (BAL) text codec.
//
// Grammar (whitespace-delimited, matching the reference Ceres fscanf reader):
//   num_cameras num_points num_observations
//   (camera_index point_index x y) * num_observations
//   (angle_axis[3] translation[3] focal k1 k2) * num_cameras
//   xyz[3] * num_points
//
// BAL uses the same camera frame and projection as Bundler: center-origin
// pixels with +Y up, and an OpenGL-style camera looking down -Z. SceneIO's
// Reconstruction uses COLMAP's +Y-down/+Z-forward camera frame, so read and
// write apply the self-inverse F=diag(1,-1,-1):
//   R_sceneio = F * R_bal, t_sceneio = F * t_bal
//   observation_sceneio = (x_bal, -y_bal)
//
// The format carries no dimensions, names, colors, or point errors. Reads use
// one zero-dimension RADIAL camera per image ({f,0,0,k1,k2}), empty names,
// zero RGB, and error=-1. The writer accepts only that canonical BAL-shaped
// subset and a strict one-to-one observation/track relation; it refuses rather
// than dropping or converting record fields.
#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

#include "fast_float/fast_float.h"
#include "records/reconstruction.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kBalIndexMax =
    static_cast<uint64_t>(std::numeric_limits<int32_t>::max());
constexpr size_t kChunkRecords = 8192;

inline bool is_ws(char value) {
    return value == ' ' || value == '\t' || value == '\r' || value == '\n';
}

struct Tokens {
    const char *cursor;
    const char *end;

    bool next(std::string_view &token) {
        while (cursor < end && is_ws(*cursor)) ++cursor;
        if (cursor == end) return false;
        const char *start = cursor;
        while (cursor < end && !is_ws(*cursor)) {
            if (cursor - start >= 1024 * 1024)
                throw std::invalid_argument(
                    "BAL: metadata token exceeds 1 MiB");
            ++cursor;
        }
        token = std::string_view(
            start, static_cast<size_t>(cursor - start));
        return true;
    }

    std::string_view require(const char *field) {
        std::string_view token;
        if (!next(token))
            throw std::invalid_argument(
                std::string("BAL: missing field ") + field);
        return token;
    }
};

std::string bounded_token(std::string_view token) {
    const size_t size = std::min<size_t>(token.size(), 40);
    std::string shown(token.data(), size);
    if (token.size() > size) shown += "...";
    return shown;
}

uint64_t parse_u64(std::string_view token, const char *field) {
    uint64_t value = 0;
    const auto result = std::from_chars(
        token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size())
        throw std::invalid_argument(
            std::string("BAL: bad integer for ") + field + " '" +
            bounded_token(token) + "'");
    return value;
}

double parse_f64(std::string_view token, const char *field) {
    double value = 0.0;
    const auto result = fast_float::from_chars(
        token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size() ||
        !std::isfinite(value))
        throw std::invalid_argument(
            std::string("BAL: bad finite number for ") + field + " '" +
            bounded_token(token) + "'");
    return value;
}

struct BalHeader {
    size_t cameras;
    size_t points;
    size_t observations;
};

void checked_add_tokens(uint64_t count, uint64_t per_record,
                        uint64_t &total) {
    if (count > (std::numeric_limits<uint64_t>::max() - total) /
                    per_record)
        throw std::invalid_argument(
            "BAL: declared token count overflows uint64");
    total += count * per_record;
}

BalHeader parse_header(Tokens &tokens, size_t file_size) {
    const uint64_t cameras =
        parse_u64(tokens.require("num_cameras"), "num_cameras");
    const uint64_t points =
        parse_u64(tokens.require("num_points"), "num_points");
    const uint64_t observations =
        parse_u64(tokens.require("num_observations"), "num_observations");
    if (cameras > kBalIndexMax || points > kBalIndexMax ||
        observations > kBalIndexMax)
        throw std::invalid_argument(
            "BAL: declared counts exceed the reference int32 index range");
    const uint64_t size_max =
        static_cast<uint64_t>(std::numeric_limits<size_t>::max());
    if (cameras > size_max / 4 ||
        points > size_max / 3 ||
        observations > size_max / 2)
        throw std::invalid_argument(
            "BAL: declared counts exceed the address space");

    uint64_t required_tokens = 3;
    checked_add_tokens(observations, 4, required_tokens);
    checked_add_tokens(cameras, 9, required_tokens);
    checked_add_tokens(points, 3, required_tokens);
    // Every token needs at least one byte and adjacent tokens need at least one
    // whitespace byte: file_size >= 2*required_tokens-1.
    if (required_tokens > static_cast<uint64_t>(file_size / 2) + 1)
        throw std::invalid_argument(
            "BAL: declared counts exceed the available file size");
    return {
        static_cast<size_t>(cameras),
        static_cast<size_t>(points),
        static_cast<size_t>(observations),
    };
}

void angle_axis_to_matrix(const double angle_axis[3], double matrix[9]) {
    const double x = angle_axis[0];
    const double y = angle_axis[1];
    const double z = angle_axis[2];
    const double theta2 = x * x + y * y + z * z;
    if (!std::isfinite(theta2))
        throw std::invalid_argument(
            "BAL: camera angle-axis norm is not finite");
    double a;
    double b;
    if (theta2 > 1e-16) {
        const double theta = std::sqrt(theta2);
        a = std::sin(theta) / theta;
        b = (1.0 - std::cos(theta)) / theta2;
    } else {
        // Rodrigues series at zero avoids a 0/0 and retains tiny rotations.
        a = 1.0 - theta2 / 6.0 + theta2 * theta2 / 120.0;
        b = 0.5 - theta2 / 24.0 + theta2 * theta2 / 720.0;
    }
    const double xx = x * x;
    const double yy = y * y;
    const double zz = z * z;
    const double xy = x * y;
    const double xz = x * z;
    const double yz = y * z;
    matrix[0] = 1.0 - b * (yy + zz);
    matrix[1] = b * xy - a * z;
    matrix[2] = b * xz + a * y;
    matrix[3] = b * xy + a * z;
    matrix[4] = 1.0 - b * (xx + zz);
    matrix[5] = b * yz - a * x;
    matrix[6] = b * xz - a * y;
    matrix[7] = b * yz + a * x;
    matrix[8] = 1.0 - b * (xx + yy);
}

void quat_to_matrix(const double quaternion[4], double matrix[9]) {
    double w = quaternion[0];
    double x = quaternion[1];
    double y = quaternion[2];
    double z = quaternion[3];
    const double norm = std::sqrt(w * w + x * x + y * y + z * z);
    w /= norm;
    x /= norm;
    y /= norm;
    z /= norm;
    matrix[0] = 1.0 - 2.0 * (y * y + z * z);
    matrix[1] = 2.0 * (x * y - w * z);
    matrix[2] = 2.0 * (x * z + w * y);
    matrix[3] = 2.0 * (x * y + w * z);
    matrix[4] = 1.0 - 2.0 * (x * x + z * z);
    matrix[5] = 2.0 * (y * z - w * x);
    matrix[6] = 2.0 * (x * z - w * y);
    matrix[7] = 2.0 * (y * z + w * x);
    matrix[8] = 1.0 - 2.0 * (x * x + y * y);
}

void canonicalize_quaternion(double quaternion[4]) {
    bool negate = quaternion[0] < 0.0;
    if (quaternion[0] == 0.0) {
        for (size_t index = 1; index < 4; ++index) {
            if (quaternion[index] == 0.0) continue;
            negate = quaternion[index] < 0.0;
            break;
        }
    }
    if (negate)
        for (size_t index = 0; index < 4; ++index)
            quaternion[index] = -quaternion[index];
    // A zero component has no quaternion sign information. Normalize signed
    // zero so equivalent matrix conversions produce the same record bytes
    // across libm/compiler implementations.
    for (size_t index = 0; index < 4; ++index)
        if (quaternion[index] == 0.0) quaternion[index] = 0.0;
}

void matrix_to_quat(const double matrix[9], double quaternion[4]) {
    const double m00 = matrix[0], m01 = matrix[1], m02 = matrix[2];
    const double m10 = matrix[3], m11 = matrix[4], m12 = matrix[5];
    const double m20 = matrix[6], m21 = matrix[7], m22 = matrix[8];
    const double trace = m00 + m11 + m22;
    if (trace > 0.0) {
        const double scale = std::sqrt(trace + 1.0) * 2.0;
        quaternion[0] = 0.25 * scale;
        quaternion[1] = (m21 - m12) / scale;
        quaternion[2] = (m02 - m20) / scale;
        quaternion[3] = (m10 - m01) / scale;
    } else if (m00 > m11 && m00 > m22) {
        const double scale =
            std::sqrt(1.0 + m00 - m11 - m22) * 2.0;
        quaternion[0] = (m21 - m12) / scale;
        quaternion[1] = 0.25 * scale;
        quaternion[2] = (m01 + m10) / scale;
        quaternion[3] = (m02 + m20) / scale;
    } else if (m11 > m22) {
        const double scale =
            std::sqrt(1.0 + m11 - m00 - m22) * 2.0;
        quaternion[0] = (m02 - m20) / scale;
        quaternion[1] = (m01 + m10) / scale;
        quaternion[2] = 0.25 * scale;
        quaternion[3] = (m12 + m21) / scale;
    } else {
        const double scale =
            std::sqrt(1.0 + m22 - m00 - m11) * 2.0;
        quaternion[0] = (m10 - m01) / scale;
        quaternion[1] = (m02 + m20) / scale;
        quaternion[2] = (m12 + m21) / scale;
        quaternion[3] = 0.25 * scale;
    }
    const double norm = std::sqrt(
        quaternion[0] * quaternion[0] +
        quaternion[1] * quaternion[1] +
        quaternion[2] * quaternion[2] +
        quaternion[3] * quaternion[3]);
    for (size_t index = 0; index < 4; ++index)
        quaternion[index] /= norm;
    canonicalize_quaternion(quaternion);
}

void matrix_to_angle_axis(const double matrix[9], double angle_axis[3]) {
    double quaternion[4];
    matrix_to_quat(matrix, quaternion);
    const double sine_half = std::sqrt(
        quaternion[1] * quaternion[1] +
        quaternion[2] * quaternion[2] +
        quaternion[3] * quaternion[3]);
    if (sine_half < 1e-15) {
        angle_axis[0] = 2.0 * quaternion[1];
        angle_axis[1] = 2.0 * quaternion[2];
        angle_axis[2] = 2.0 * quaternion[3];
        return;
    }
    const double angle =
        2.0 * std::atan2(sine_half, quaternion[0]);
    const double factor = angle / sine_half;
    angle_axis[0] = quaternion[1] * factor;
    angle_axis[1] = quaternion[2] * factor;
    angle_axis[2] = quaternion[3] * factor;
}

Reconstruction decode_bal(const uint8_t *data, size_t size) {
    Tokens tokens{
        reinterpret_cast<const char *>(data),
        reinterpret_cast<const char *>(data) + size,
    };
    const BalHeader header = parse_header(tokens, size);

    std::vector<uint32_t> observation_camera(header.observations);
    std::vector<uint32_t> observation_point(header.observations);
    std::vector<double> observation_xy(header.observations * 2);
    std::vector<uint64_t> camera_counts(header.cameras, 0);
    std::vector<uint64_t> point_counts(header.points, 0);
    for (size_t index = 0; index < header.observations; ++index) {
        const uint64_t camera = parse_u64(
            tokens.require("observation camera index"),
            "observation camera index");
        const uint64_t point = parse_u64(
            tokens.require("observation point index"),
            "observation point index");
        if (camera >= header.cameras)
            throw std::invalid_argument(
                "BAL: observation camera index is out of range");
        if (point >= header.points)
            throw std::invalid_argument(
                "BAL: observation point index is out of range");
        observation_camera[index] = static_cast<uint32_t>(camera);
        observation_point[index] = static_cast<uint32_t>(point);
        observation_xy[index * 2] = parse_f64(
            tokens.require("observation x"), "observation x");
        observation_xy[index * 2 + 1] = parse_f64(
            tokens.require("observation y"), "observation y");
        if (++camera_counts[camera] >
            std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "BAL: one camera has too many observations");
        ++point_counts[point];
    }

    Reconstruction result;
    result.cameras.reserve(header.cameras);
    result.img_ids.reserve(header.cameras);
    result.img_cam_ids.reserve(header.cameras);
    result.img_names.reserve(header.cameras);
    result.quats.reserve(header.cameras * 4);
    result.trans.reserve(header.cameras * 3);
    for (size_t index = 0; index < header.cameras; ++index) {
        double angle_axis[3];
        double translation[3];
        for (double &value : angle_axis)
            value = parse_f64(
                tokens.require("camera angle-axis"), "camera angle-axis");
        for (double &value : translation)
            value = parse_f64(
                tokens.require("camera translation"), "camera translation");
        const double focal = parse_f64(
            tokens.require("camera focal length"), "camera focal length");
        const double k1 =
            parse_f64(tokens.require("camera k1"), "camera k1");
        const double k2 =
            parse_f64(tokens.require("camera k2"), "camera k2");
        if (!(focal > 0.0))
            throw std::invalid_argument(
                "BAL: camera focal length must be positive");

        double bal_rotation[9];
        angle_axis_to_matrix(angle_axis, bal_rotation);
        const double scene_rotation[9] = {
            bal_rotation[0], bal_rotation[1], bal_rotation[2],
            -bal_rotation[3], -bal_rotation[4], -bal_rotation[5],
            -bal_rotation[6], -bal_rotation[7], -bal_rotation[8],
        };
        double quaternion[4];
        matrix_to_quat(scene_rotation, quaternion);

        const uint32_t identifier = static_cast<uint32_t>(index + 1);
        result.cameras.push_back(
            Camera{
                identifier,
                3,
                0,
                0,
                {focal, 0.0, 0.0, k1, k2},
            });
        result.img_ids.push_back(identifier);
        result.img_cam_ids.push_back(identifier);
        result.img_names.emplace_back();
        result.quats.insert(
            result.quats.end(),
            {quaternion[0], quaternion[1], quaternion[2],
             quaternion[3]});
        result.trans.insert(
            result.trans.end(),
            {translation[0], -translation[1], -translation[2]});
    }

    result.pt_ids.reserve(header.points);
    result.xyz.reserve(header.points * 3);
    result.rgb.assign(header.points * 3, 0);
    result.err.assign(header.points, -1.0);
    for (size_t index = 0; index < header.points; ++index) {
        result.pt_ids.push_back(static_cast<uint64_t>(index + 1));
        for (size_t component = 0; component < 3; ++component)
            result.xyz.push_back(parse_f64(
                tokens.require("point coordinate"), "point coordinate"));
    }
    std::string_view trailing;
    if (tokens.next(trailing))
        throw std::invalid_argument(
            "BAL: trailing data after the final point");

    result.obs_off.assign(header.cameras + 1, 0);
    for (size_t index = 0; index < header.cameras; ++index)
        result.obs_off[index + 1] =
            result.obs_off[index] + camera_counts[index];
    result.track_off.assign(header.points + 1, 0);
    for (size_t index = 0; index < header.points; ++index)
        result.track_off[index + 1] =
            result.track_off[index] + point_counts[index];
    result.obs_xy.resize(header.observations * 2);
    result.obs_pt3d.resize(header.observations);
    result.track.resize(header.observations * 2);

    std::vector<uint64_t> camera_cursor = result.obs_off;
    std::vector<uint64_t> point_cursor = result.track_off;
    for (size_t index = 0; index < header.observations; ++index) {
        const size_t camera = observation_camera[index];
        const size_t point = observation_point[index];
        const uint64_t observation_slot = camera_cursor[camera]++;
        const uint64_t point2d_index =
            observation_slot - result.obs_off[camera];
        result.obs_xy[observation_slot * 2] =
            observation_xy[index * 2];
        result.obs_xy[observation_slot * 2 + 1] =
            -observation_xy[index * 2 + 1];
        result.obs_pt3d[observation_slot] =
            static_cast<int64_t>(point + 1);

        const uint64_t track_slot = point_cursor[point]++;
        result.track[track_slot * 2] =
            static_cast<uint32_t>(camera + 1);
        result.track[track_slot * 2 + 1] =
            static_cast<uint32_t>(point2d_index);
    }
    return result;
}

Reconstruction read_bal(nb::handle source) {
    ByteView view(source);
    Reconstruction result;
    {
        nb::gil_scoped_release release;
        result = decode_bal(view.data(), view.size());
    }
    return result;
}

nb::tuple inspect_bal(nb::handle source) {
    ByteView view(source);
    BalHeader header;
    {
        nb::gil_scoped_release release;
        Tokens tokens{
            reinterpret_cast<const char *>(view.data()),
            reinterpret_cast<const char *>(view.data()) + view.size(),
        };
        header = parse_header(tokens, view.size());
    }
    return nb::make_tuple(
        header.cameras, header.points, header.observations);
}

struct BalObservation {
    uint32_t camera_index;
    uint32_t point_index;
    double x;
    double y;
};

struct BalWritePlan {
    std::vector<std::array<double, 9>> cameras;
    std::vector<BalObservation> observations;
};

void require_finite(double value, const char *field) {
    if (!std::isfinite(value))
        throw std::invalid_argument(
            std::string("BAL: ") + field + " must be finite");
}

BalWritePlan prepare_write(const Reconstruction &reconstruction) {
    const size_t camera_count = reconstruction.num_images();
    const size_t point_count = reconstruction.num_points();
    if (camera_count > kBalIndexMax || point_count > kBalIndexMax)
        throw std::invalid_argument(
            "BAL: record counts exceed the reference int32 index range");
    if (camera_count > std::numeric_limits<size_t>::max() / 4 ||
        point_count > std::numeric_limits<size_t>::max() / 3)
        throw std::invalid_argument(
            "BAL: record arrays exceed the address space");
    if (reconstruction.cameras.size() != camera_count)
        throw std::invalid_argument(
            "BAL: writer requires exactly one camera per image");
    if (reconstruction.quats.size() != camera_count * 4 ||
        reconstruction.trans.size() != camera_count * 3 ||
        reconstruction.img_cam_ids.size() != camera_count ||
        reconstruction.img_names.size() != camera_count)
        throw std::invalid_argument(
            "BAL: image arrays disagree with the image count");
    if (reconstruction.xyz.size() != point_count * 3 ||
        reconstruction.rgb.size() != point_count * 3 ||
        reconstruction.err.size() != point_count)
        throw std::invalid_argument(
            "BAL: point arrays disagree with the point count");
    if (reconstruction.obs_off.size() != camera_count + 1 ||
        reconstruction.track_off.size() != point_count + 1)
        throw std::invalid_argument(
            "BAL: observation/track offsets have the wrong length");
    if (reconstruction.track.size() % 2 != 0)
        throw std::invalid_argument(
            "BAL: track storage has an odd number of values");

    const size_t observation_count = reconstruction.obs_pt3d.size();
    const size_t track_count = reconstruction.track.size() / 2;
    if (observation_count > kBalIndexMax ||
        track_count != observation_count)
        throw std::invalid_argument(
            "BAL: every observation must have exactly one track");
    if (observation_count > std::numeric_limits<size_t>::max() / 2 ||
        reconstruction.obs_xy.size() != observation_count * 2)
        throw std::invalid_argument(
            "BAL: observation storage disagrees with its count");
    if (reconstruction.obs_off.empty() ||
        reconstruction.obs_off.front() != 0 ||
        reconstruction.obs_off.back() != observation_count)
        throw std::invalid_argument(
            "BAL: observation offsets do not span the observations");
    if (reconstruction.track_off.empty() ||
        reconstruction.track_off.front() != 0 ||
        reconstruction.track_off.back() != track_count)
        throw std::invalid_argument(
            "BAL: track offsets do not span the tracks");
    for (size_t index = 0; index < camera_count; ++index) {
        if (reconstruction.obs_off[index] >
            reconstruction.obs_off[index + 1])
            throw std::invalid_argument(
                "BAL: observation offsets are not monotonic");
    }
    for (size_t index = 0; index < point_count; ++index) {
        if (reconstruction.track_off[index] >
            reconstruction.track_off[index + 1])
            throw std::invalid_argument(
                "BAL: track offsets are not monotonic");
    }

    BalWritePlan plan;
    plan.cameras.reserve(camera_count);
    for (size_t index = 0; index < camera_count; ++index) {
        const uint32_t expected_id = static_cast<uint32_t>(index + 1);
        const Camera &camera = reconstruction.cameras[index];
        if (reconstruction.img_ids[index] != expected_id ||
            camera.id != expected_id ||
            reconstruction.img_cam_ids[index] != expected_id)
            throw std::invalid_argument(
                "BAL: writer requires contiguous one-based image/camera ids");
        if (!reconstruction.img_names[index].empty())
            throw std::invalid_argument(
                "BAL: image names are not representable");
        if (camera.width != 0 || camera.height != 0)
            throw std::invalid_argument(
                "BAL: image dimensions are not representable");
        if (camera.model_id != 3 || camera.params.size() != 5)
            throw std::invalid_argument(
                "BAL: writer requires canonical RADIAL cameras");
        for (double value : camera.params)
            require_finite(value, "camera parameter");
        if (!(camera.params[0] > 0.0))
            throw std::invalid_argument(
                "BAL: camera focal length must be positive");
        if (camera.params[1] != 0.0 || camera.params[2] != 0.0)
            throw std::invalid_argument(
                "BAL: nonzero principal points are not representable");

        double quaternion[4];
        double norm_squared = 0.0;
        for (size_t component = 0; component < 4; ++component) {
            quaternion[component] =
                reconstruction.quats[index * 4 + component];
            require_finite(quaternion[component], "quaternion");
            norm_squared += quaternion[component] * quaternion[component];
        }
        if (!(norm_squared > 0.0) || !std::isfinite(norm_squared))
            throw std::invalid_argument(
                "BAL: quaternion must have a finite nonzero norm");
        double scene_rotation[9];
        quat_to_matrix(quaternion, scene_rotation);
        const double bal_rotation[9] = {
            scene_rotation[0], scene_rotation[1], scene_rotation[2],
            -scene_rotation[3], -scene_rotation[4], -scene_rotation[5],
            -scene_rotation[6], -scene_rotation[7], -scene_rotation[8],
        };
        std::array<double, 9> parameters{};
        matrix_to_angle_axis(bal_rotation, parameters.data());
        parameters[3] = reconstruction.trans[index * 3];
        parameters[4] = -reconstruction.trans[index * 3 + 1];
        parameters[5] = -reconstruction.trans[index * 3 + 2];
        for (size_t component = 3; component < 6; ++component)
            require_finite(parameters[component], "translation");
        parameters[6] = camera.params[0];
        parameters[7] = camera.params[3];
        parameters[8] = camera.params[4];
        plan.cameras.push_back(parameters);
    }

    for (size_t point = 0; point < point_count; ++point) {
        if (reconstruction.pt_ids[point] != point + 1)
            throw std::invalid_argument(
                "BAL: writer requires contiguous one-based point ids");
        for (size_t component = 0; component < 3; ++component) {
            require_finite(
                reconstruction.xyz[point * 3 + component],
                "point coordinate");
            if (reconstruction.rgb[point * 3 + component] != 0)
                throw std::invalid_argument(
                    "BAL: point colors are not representable");
        }
        if (reconstruction.err[point] != -1.0)
            throw std::invalid_argument(
                "BAL: point errors are not representable");
    }

    std::vector<uint8_t> observation_used(observation_count, 0);
    plan.observations.reserve(observation_count);
    for (size_t point = 0; point < point_count; ++point) {
        const uint64_t begin = reconstruction.track_off[point];
        const uint64_t end = reconstruction.track_off[point + 1];
        for (uint64_t index = begin; index < end; ++index) {
            const uint32_t image_id = reconstruction.track[index * 2];
            const uint32_t point2d_index =
                reconstruction.track[index * 2 + 1];
            if (image_id == 0 || image_id > camera_count)
                throw std::invalid_argument(
                    "BAL: track references an unknown image");
            const size_t camera = static_cast<size_t>(image_id - 1);
            const uint64_t observation_begin =
                reconstruction.obs_off[camera];
            const uint64_t observation_end =
                reconstruction.obs_off[camera + 1];
            if (point2d_index >= observation_end - observation_begin)
                throw std::invalid_argument(
                    "BAL: track references an out-of-range observation");
            const size_t slot = static_cast<size_t>(
                observation_begin + point2d_index);
            if (observation_used[slot])
                throw std::invalid_argument(
                    "BAL: multiple tracks reference one observation");
            if (reconstruction.obs_pt3d[slot] !=
                static_cast<int64_t>(point + 1))
                throw std::invalid_argument(
                    "BAL: track and observation point ids disagree");
            const double x = reconstruction.obs_xy[slot * 2];
            const double y = reconstruction.obs_xy[slot * 2 + 1];
            require_finite(x, "observation coordinate");
            require_finite(y, "observation coordinate");
            observation_used[slot] = 1;
            plan.observations.push_back(
                BalObservation{
                    static_cast<uint32_t>(camera),
                    static_cast<uint32_t>(point),
                    x,
                    -y,
                });
        }
    }
    if (std::find(
            observation_used.begin(), observation_used.end(), 0) !=
        observation_used.end())
        throw std::invalid_argument(
            "BAL: untracked observations are not representable");
    return plan;
}

void append_f64(std::string &output, double value) {
    if (value == 0.0) value = 0.0;
    char buffer[64];
    const int size =
        std::snprintf(buffer, sizeof(buffer), "%.17g", value);
    if (size <= 0 || static_cast<size_t>(size) >= sizeof(buffer))
        throw std::runtime_error("BAL: numeric formatting failed");
    output.append(buffer, static_cast<size_t>(size));
}

void append_header(std::string &output, const Reconstruction &reconstruction,
                   const BalWritePlan &plan) {
    output += std::to_string(reconstruction.num_images());
    output += ' ';
    output += std::to_string(reconstruction.num_points());
    output += ' ';
    output += std::to_string(plan.observations.size());
    output += '\n';
}

void append_observation(std::string &output,
                        const BalObservation &observation) {
    output += std::to_string(observation.camera_index);
    output += ' ';
    output += std::to_string(observation.point_index);
    output += ' ';
    append_f64(output, observation.x);
    output += ' ';
    append_f64(output, observation.y);
    output += '\n';
}

void append_camera(std::string &output,
                   const std::array<double, 9> &camera) {
    for (double value : camera) {
        append_f64(output, value);
        output += '\n';
    }
}

void append_point(std::string &output,
                  const Reconstruction &reconstruction, size_t point) {
    for (size_t component = 0; component < 3; ++component) {
        append_f64(
            output, reconstruction.xyz[point * 3 + component]);
        output += '\n';
    }
}

nb::bytes write_bal(const Reconstruction &reconstruction) {
    BalWritePlan plan;
    {
        nb::gil_scoped_release release;
        require_no_colmap_rig_frame_model(reconstruction, "BAL");
        plan = prepare_write(reconstruction);
    }

    std::string header;
    append_header(header, reconstruction, plan);
    if (!emit_file_chunk(header.data(), header.size())) {
        std::string output = std::move(header);
        {
            nb::gil_scoped_release release;
            for (const BalObservation &observation : plan.observations)
                append_observation(output, observation);
            for (const auto &camera : plan.cameras)
                append_camera(output, camera);
            for (size_t point = 0;
                 point < reconstruction.num_points(); ++point)
                append_point(output, reconstruction, point);
        }
        return nb::bytes(output.data(), output.size());
    }

    for (size_t begin = 0; begin < plan.observations.size();
         begin += kChunkRecords) {
        const size_t end =
            std::min(plan.observations.size(), begin + kChunkRecords);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            for (size_t index = begin; index < end; ++index)
                append_observation(chunk, plan.observations[index]);
        }
        emit_file_chunk(chunk.data(), chunk.size());
    }
    for (size_t begin = 0; begin < plan.cameras.size();
         begin += kChunkRecords) {
        const size_t end =
            std::min(plan.cameras.size(), begin + kChunkRecords);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            for (size_t index = begin; index < end; ++index)
                append_camera(chunk, plan.cameras[index]);
        }
        emit_file_chunk(chunk.data(), chunk.size());
    }
    for (size_t begin = 0; begin < reconstruction.num_points();
         begin += kChunkRecords) {
        const size_t end = std::min(
            reconstruction.num_points(), begin + kChunkRecords);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            for (size_t point = begin; point < end; ++point)
                append_point(chunk, reconstruction, point);
        }
        emit_file_chunk(chunk.data(), chunk.size());
    }
    return nb::bytes("", 0);
}

}  // namespace

void register_bal(nb::module_ &module) {
    module.def(
        "_inspect_bal", &inspect_bal, "data"_a,
        "Return (camera_count, point_count, observation_count) from a BAL "
        "header without decoding records.");
    module.def(
        "read_bal", &read_bal, "data"_a,
        "Decode a University of Washington BAL text problem into a canonical "
        "Reconstruction. Applies F=diag(1,-1,-1) from BAL's y-up/-Z camera "
        "frame to SceneIO's y-down/+Z frame. Cameras are zero-dimension "
        "RADIAL models, names are empty, RGB is zero, and point error is -1.");
    module.def(
        "write_bal", &write_bal, "reconstruction"_a,
        "Encode a canonical BAL-shaped Reconstruction using deterministic "
        "17-digit text. Requires contiguous one-based ids, one zero-dimension "
        "RADIAL camera per image, empty names, zero RGB, error=-1, and a "
        "one-to-one observation/track relation; unrepresentable fields raise.");
}
