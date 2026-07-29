// records/feature_match.cpp -- validation, construction, and nanobind views.
#include <nanobind/stl/array.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "records/feature_match.hpp"

using namespace nb::literals;

namespace {

using any_array = nb::ndarray<nb::c_contig, nb::device::cpu>;
using f32_array =
    nb::ndarray<const float, nb::c_contig, nb::device::cpu>;
using f64_array =
    nb::ndarray<const double, nb::c_contig, nb::device::cpu>;
using u8_array =
    nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;
using u32_array =
    nb::ndarray<const uint32_t, nb::c_contig, nb::device::cpu>;
using u64_array =
    nb::ndarray<const uint64_t, nb::c_contig, nb::device::cpu>;
using i32_array =
    nb::ndarray<const int32_t, nb::c_contig, nb::device::cpu>;

template <typename T>
void assign_nonempty(
    std::vector<T> &target, const T *data, size_t count) {
    if (count != 0) target.assign(data, data + count);
}

template <typename T>
nb::ndarray<nb::numpy, T> typed_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static T sentinel{};
    T *data =
        values.empty() ? &sentinel : const_cast<T *>(values.data());
    return nb::ndarray<nb::numpy, T>(
        data, shape.size(), shape.data());
}

template <typename T>
nb::object owner_typed_view(
    nb::handle owner, const std::vector<T> &values,
    std::vector<size_t> shape) {
    static T sentinel{};
    const T *data =
        values.empty() ? &sentinel : values.data();
    return nb::cast(sio::view(owner, data, std::move(shape)));
}

nb::object descriptor_view(
    nb::handle owner, const FeatureSet &features) {
    const auto &info = sio::dtype_info(features.descriptor_dtype);
    static uint8_t sentinel = 0;
    void *data = features.descriptors.empty()
                     ? &sentinel
                     : const_cast<uint8_t *>(
                           features.descriptors.data());
    const size_t shape[2] = {
        features.rows, features.descriptor_columns};
    return nb::cast(nb::ndarray<nb::numpy>(
        data, 2, shape, owner, nullptr,
        nb::dlpack::dtype{info.code, info.bits, 1}));
}

void validate_text(const std::string &value, const char *context) {
    if (value.empty())
        throw std::invalid_argument(
            std::string(context) + ": image_name must be non-empty");
    if (value.find('\0') != std::string::npos)
        throw std::invalid_argument(
            std::string(context) +
            ": image_name cannot contain embedded NUL");
    if (!sio::valid_utf8(value))
        throw std::invalid_argument(
            std::string(context) +
            ": image_name must be valid UTF-8");
}

void require_binary_flags(
    const std::vector<uint8_t> &values,
    const char *context, const char *name) {
    for (uint8_t value : values)
        if (value > 1)
            throw std::invalid_argument(
                std::string(context) + ": " + name +
                " flags must be canonical 0 or 1");
}

size_t validate_offsets(
    const std::vector<uint64_t> &offsets, size_t count,
    size_t value_count, const char *context,
    const char *name) {
    if (offsets.size() != count + 1 || offsets.front() != 0)
        throw std::invalid_argument(
            std::string(context) + ": " + name +
            " must contain P+1 offsets beginning at zero");
    for (size_t index = 1; index < offsets.size(); ++index)
        if (offsets[index] < offsets[index - 1])
            throw std::invalid_argument(
                std::string(context) + ": " + name +
                " must be monotonic");
    if (offsets.back() >
            static_cast<uint64_t>(
                std::numeric_limits<size_t>::max()) ||
        static_cast<size_t>(offsets.back()) != value_count)
        throw std::invalid_argument(
            std::string(context) + ": " + name +
            " terminal offset disagrees with the value count");
    return value_count;
}

std::vector<uint8_t> optional_flags(
    std::optional<u8_array> source, size_t count,
    bool default_value, const char *name) {
    std::vector<uint8_t> result(
        count, default_value ? uint8_t{1} : uint8_t{0});
    if (!source) return result;
    if (source->ndim() != 1 || source->shape(0) != count)
        throw std::invalid_argument(
            std::string("match_graph: ") + name +
            " must be (P,) uint8");
    assign_nonempty(result, source->data(), count);
    return result;
}

std::vector<int32_t> optional_configs(
    std::optional<i32_array> source, size_t count) {
    std::vector<int32_t> result(count, 0);
    if (!source) return result;
    if (source->ndim() != 1 || source->shape(0) != count)
        throw std::invalid_argument(
            "match_graph: configs must be (P,) int32");
    assign_nonempty(result, source->data(), count);
    return result;
}

std::vector<double> optional_matrices(
    std::optional<f64_array> source, size_t count,
    const char *name) {
    if (!source) return std::vector<double>(count * 9, 0.0);
    if (source->ndim() != 3 ||
        source->shape(0) != count ||
        source->shape(1) != 3 || source->shape(2) != 3)
        throw std::invalid_argument(
            std::string("match_graph: ") + name +
            " must be (P,3,3) float64");
    std::vector<double> result;
    assign_nonempty(result, source->data(), count * 9);
    return result;
}

bool is_default_camera(const Camera &camera) {
    return camera.id == 0 && camera.model_id == 0 &&
           camera.width == 0 && camera.height == 0 &&
           camera.params.empty();
}

void validate_camera_value(
    const Camera &camera, const char *context,
    const char *kind) {
    if (camera.id >= kColmapMaxNumImages ||
        camera.width == 0 || camera.height == 0 ||
        camera.width >
            static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()) ||
        camera.height >
            static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument(
            std::string(context) + ": " + kind +
            " ids must be below 2147483647 and dimensions positive");
    const auto info = colmap_model_info(camera.model_id);
    if (camera.params.size() !=
        static_cast<size_t>(info.nparams))
        throw std::invalid_argument(
            std::string(context) + ": " + kind +
            " parameter count disagrees with model");
    for (double value : camera.params)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                std::string(context) + ": " + kind +
                " parameters must be finite");
}

void validate_recovered_camera_value(
    const Camera &camera, const char *context,
    const char *kind) {
    if (camera.id == std::numeric_limits<uint32_t>::max() ||
        camera.width == 0 || camera.height == 0)
        throw std::invalid_argument(
            std::string(context) + ": " + kind +
            " id must not be UINT32_MAX and dimensions must be positive");
    const auto info = colmap_model_info(camera.model_id);
    if (camera.params.size() !=
        static_cast<size_t>(info.nparams))
        throw std::invalid_argument(
            std::string(context) + ": " + kind +
            " parameter count disagrees with model");
    for (double value : camera.params)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                std::string(context) + ": " + kind +
                " parameters must be finite");
}

FeatureSet make_feature_set(
    f32_array keypoints, nb::object descriptors,
    nb::object scores, uint32_t image_id,
    const std::string &image_name, uint32_t camera_id,
    std::array<uint64_t, 2> image_size,
    int32_t extractor_type, nb::object time_id,
    bool keypoints_present) {
    if (keypoints.ndim() != 2 ||
        (keypoints.shape(1) != 2 &&
         keypoints.shape(1) != 4 &&
         keypoints.shape(1) != 6))
        throw std::invalid_argument(
            "feature_set: keypoints must be (N,2|4|6) float32");

    FeatureSet result;
    result.image_id = image_id;
    result.image_name = image_name;
    result.camera_id = camera_id;
    result.image_width = image_size[0];
    result.image_height = image_size[1];
    result.extractor_type = extractor_type;
    result.keypoints_present = keypoints_present;
    result.rows = keypoints.shape(0);
    result.keypoint_columns = keypoints.shape(1);

    any_array descriptor_array;
    const sio::DTypeInfo *descriptor_info = nullptr;
    if (!descriptors.is_none()) {
        if (!nb::try_cast<any_array>(descriptors, descriptor_array))
            throw nb::type_error(
                "feature_set: descriptors must be a C-contiguous "
                "CPU array");
        if (descriptor_array.ndim() != 2 ||
            descriptor_array.shape(0) != result.rows)
            throw std::invalid_argument(
                "feature_set: descriptors must be (N,D)");
        descriptor_info =
            sio::dtype_from_dlpack(descriptor_array.dtype());
        if (!descriptor_info ||
            (descriptor_info->tag != sio::DType::U8 &&
             descriptor_info->tag != sio::DType::F32))
            throw std::invalid_argument(
                "feature_set: descriptor dtype must be uint8 or float32");
        result.has_descriptors = true;
        result.descriptor_dtype = descriptor_info->tag;
        result.descriptor_columns = descriptor_array.shape(1);
    } else if (extractor_type != -1) {
        throw std::invalid_argument(
            "feature_set: extractor_type must be -1 without descriptors");
    }

    f32_array score_array;
    if (!scores.is_none()) {
        if (!nb::try_cast<f32_array>(scores, score_array))
            throw nb::type_error(
                "feature_set: scores must be a C-contiguous "
                "float32 CPU array");
        if (score_array.ndim() != 1 ||
            score_array.shape(0) != result.rows)
            throw std::invalid_argument(
                "feature_set: scores must be (N,) float32");
        result.has_scores = true;
    }

    if (!time_id.is_none()) {
        result.time_id = nb::cast<int64_t>(time_id);
        result.has_time_id = true;
    }

    {
        nb::gil_scoped_release release;
        assign_nonempty(
            result.keypoints, keypoints.data(),
            result.rows * result.keypoint_columns);
        if (result.has_descriptors) {
            const size_t bytes = TensorDict::checked_size(
                "descriptors", result.descriptor_dtype,
                {result.rows, result.descriptor_columns});
            result.descriptors.resize(bytes);
            if (bytes != 0)
                std::memcpy(
                    result.descriptors.data(),
                    descriptor_array.data(), bytes);
        }
        if (result.has_scores)
            assign_nonempty(
                result.scores, score_array.data(), result.rows);
        validate_feature_set(result);
    }
    return result;
}

MatchGraph make_match_graph(
    u32_array image_pairs, u64_array match_offsets,
    u32_array matches, u64_array verified_offsets,
    u32_array verified_matches,
    nb::object scores, std::optional<i32_array> configs,
    std::optional<f64_array> fundamental_matrices,
    std::optional<u8_array> fundamental_present,
    std::optional<f64_array> essential_matrices,
    std::optional<u8_array> essential_present,
    std::optional<f64_array> homographies,
    std::optional<u8_array> homography_present,
    std::optional<f64_array> qvecs,
    std::optional<f64_array> tvecs,
    std::optional<u8_array> pose_present,
    std::optional<u8_array> match_present,
    std::optional<u8_array> geometry_present,
    std::optional<std::vector<std::optional<Camera>>>
        recovered_camera1,
    std::optional<u8_array> camera1_present,
    std::optional<u8_array> camera1_prior_focal_length,
    std::optional<std::vector<std::optional<Camera>>>
        recovered_camera2,
    std::optional<u8_array> camera2_present,
    std::optional<u8_array> camera2_prior_focal_length) {
    if (image_pairs.ndim() != 2 || image_pairs.shape(1) != 2)
        throw std::invalid_argument(
            "match_graph: image_pairs must be (P,2) uint32");
    const size_t count = image_pairs.shape(0);
    if (match_offsets.ndim() != 1 ||
        match_offsets.shape(0) != count + 1 ||
        matches.ndim() != 2 || matches.shape(1) != 2)
        throw std::invalid_argument(
            "match_graph: matches require offsets (P+1,) uint64 "
            "and values (M,2) uint32");
    if (verified_offsets.ndim() != 1 ||
        verified_offsets.shape(0) != count + 1 ||
        verified_matches.ndim() != 2 ||
        verified_matches.shape(1) != 2)
        throw std::invalid_argument(
            "match_graph: verified matches require offsets (P+1,) "
            "uint64 and values (K,2) uint32");
    if (count > std::numeric_limits<size_t>::max() / 9)
        throw std::invalid_argument(
            "match_graph: pair count overflows field extents");

    f32_array score_array;
    const bool has_scores = !scores.is_none();
    if (has_scores) {
        if (!nb::try_cast<f32_array>(scores, score_array))
            throw nb::type_error(
                "match_graph: scores must be a C-contiguous "
                "float32 CPU array");
        if (score_array.ndim() != 1 ||
            score_array.shape(0) != matches.shape(0))
            throw std::invalid_argument(
                "match_graph: scores must be (M,) float32");
    }
    if (static_cast<bool>(qvecs) != static_cast<bool>(tvecs))
        throw std::invalid_argument(
            "match_graph: qvecs and tvecs must be supplied together");
    if (qvecs &&
        (qvecs->ndim() != 2 || qvecs->shape(0) != count ||
         qvecs->shape(1) != 4))
        throw std::invalid_argument(
            "match_graph: qvecs must be (P,4) float64");
    if (tvecs &&
        (tvecs->ndim() != 2 || tvecs->shape(0) != count ||
         tvecs->shape(1) != 3))
        throw std::invalid_argument(
            "match_graph: tvecs must be (P,3) float64");

    MatchGraph result;
    result.pair_count = count;
    result.has_scores = has_scores;
    result.match_present = optional_flags(
        std::move(match_present), count, true,
        "match_present");
    result.geometry_present = optional_flags(
        std::move(geometry_present), count, true,
        "geometry_present");
    result.configs = optional_configs(std::move(configs), count);
    result.F_present = optional_flags(
        std::move(fundamental_present), count,
        static_cast<bool>(fundamental_matrices), "F_present");
    result.E_present = optional_flags(
        std::move(essential_present), count,
        static_cast<bool>(essential_matrices), "E_present");
    result.H_present = optional_flags(
        std::move(homography_present), count,
        static_cast<bool>(homographies), "H_present");
    result.pose_present = optional_flags(
        std::move(pose_present), count,
        static_cast<bool>(qvecs), "pose_present");
    result.camera1_prior_focal_length = optional_flags(
        std::move(camera1_prior_focal_length), count, false,
        "camera1_prior_focal_length");
    result.camera2_prior_focal_length = optional_flags(
        std::move(camera2_prior_focal_length), count, false,
        "camera2_prior_focal_length");
    result.recovered_camera1.assign(count, Camera{});
    result.recovered_camera2.assign(count, Camera{});
    const auto assign_recovered =
        [&](std::optional<
                std::vector<std::optional<Camera>>> &source,
            std::optional<u8_array> &explicit_present,
            std::vector<Camera> &cameras,
            std::vector<uint8_t> &present,
            const char *camera_name,
            const char *presence_name) {
            std::vector<uint8_t> inferred(
                count, uint8_t{0});
            if (source) {
                if (source->size() != count)
                    throw std::invalid_argument(
                        std::string("match_graph: ") +
                        camera_name +
                        " must have P camera-or-None values");
                for (size_t index = 0; index < count; ++index) {
                    if (!(*source)[index]) continue;
                    cameras[index] =
                        std::move(*(*source)[index]);
                    inferred[index] = 1;
                }
            }
            if (!explicit_present) {
                present = std::move(inferred);
                return;
            }
            present = optional_flags(
                std::move(explicit_present), count, false,
                presence_name);
            if (present != inferred)
                throw std::invalid_argument(
                    std::string("match_graph: ") +
                    presence_name +
                    " must agree with camera-or-None values");
        };
    assign_recovered(
        recovered_camera1, camera1_present,
        result.recovered_camera1, result.camera1_present,
        "recovered_camera1", "camera1_present");
    assign_recovered(
        recovered_camera2, camera2_present,
        result.recovered_camera2, result.camera2_present,
        "recovered_camera2", "camera2_present");
    result.F = optional_matrices(
        std::move(fundamental_matrices), count,
        "fundamental_matrices");
    result.E = optional_matrices(
        std::move(essential_matrices), count,
        "essential_matrices");
    result.H = optional_matrices(
        std::move(homographies), count, "homographies");
    result.qvecs.assign(count * 4, 0.0);
    result.tvecs.assign(count * 3, 0.0);

    {
        nb::gil_scoped_release release;
        assign_nonempty(
            result.image_pairs, image_pairs.data(), count * 2);
        assign_nonempty(
            result.match_offsets, match_offsets.data(), count + 1);
        assign_nonempty(
            result.matches, matches.data(), matches.shape(0) * 2);
        assign_nonempty(
            result.verified_offsets, verified_offsets.data(),
            count + 1);
        assign_nonempty(
            result.verified_matches, verified_matches.data(),
            verified_matches.shape(0) * 2);
        if (has_scores)
            assign_nonempty(
                result.scores, score_array.data(),
                matches.shape(0));
        if (qvecs) assign_nonempty(
            result.qvecs, qvecs->data(), count * 4);
        if (tvecs) assign_nonempty(
            result.tvecs, tvecs->data(), count * 3);
        for (size_t index = 0; index < count; ++index) {
            if (!result.F_present[index])
                std::fill_n(result.F.data() + index * 9, 9, 0.0);
            if (!result.E_present[index])
                std::fill_n(result.E.data() + index * 9, 9, 0.0);
            if (!result.H_present[index])
                std::fill_n(result.H.data() + index * 9, 9, 0.0);
            if (!result.pose_present[index]) {
                std::fill_n(
                    result.qvecs.data() + index * 4, 4, 0.0);
                std::fill_n(
                    result.tvecs.data() + index * 3, 3, 0.0);
            }
        }
        result.pair_ids.reserve(count);
        for (size_t index = 0; index < count; ++index)
            result.pair_ids.push_back(colmap_pair_id(
                result.image_pairs[index * 2],
                result.image_pairs[index * 2 + 1]));
        validate_match_graph(result);
    }
    return result;
}

ColmapDatabase make_colmap_database(
    std::vector<Camera> cameras,
    std::vector<FeatureSet> features,
    const MatchGraph &match_graph,
    std::optional<u8_array> prior_focal_length,
    int32_t user_version,
    const std::string &profile,
    int32_t application_id) {
    ColmapDatabase result;
    result.cameras = std::move(cameras);
    result.features = std::move(features);
    result.match_graph = match_graph;
    result.user_version = user_version;
    result.profile = profile;
    result.application_id = application_id;
    if (profile != "sceneio-hybrid-v1")
        throw std::invalid_argument(
            "colmap_database: constructed records currently require "
            "profile='sceneio-hybrid-v1'; exact profile construction "
            "requires the profile-aware database factories");
    if (application_id != 0)
        throw std::invalid_argument(
            "colmap_database: profile='sceneio-hybrid-v1' requires "
            "application_id=0");
    result.prior_focal_length.assign(
        result.cameras.size(), uint8_t{0});
    if (prior_focal_length) {
        if (prior_focal_length->ndim() != 1 ||
            prior_focal_length->shape(0) != result.cameras.size())
            throw std::invalid_argument(
                "colmap_database: prior_focal_length must be "
                "(num_cameras,) uint8");
        assign_nonempty(
            result.prior_focal_length,
            prior_focal_length->data(), result.cameras.size());
    }
    {
        nb::gil_scoped_release release;
        validate_colmap_database(result);
    }
    return result;
}

Camera make_camera(
    uint32_t id, int32_t model_id, uint64_t width,
    uint64_t height, f64_array params) {
    const auto model = colmap_model_info(model_id);
    if (id == std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "camera: id must not be UINT32_MAX");
    if (params.ndim() != 1 ||
        params.shape(0) != static_cast<size_t>(model.nparams))
        throw std::invalid_argument(
            "camera: params length disagrees with camera model");
    Camera result;
    result.id = id;
    result.model_id = model_id;
    result.width = width;
    result.height = height;
    assign_nonempty(
        result.params, params.data(), params.shape(0));
    if (width == 0 || height == 0)
        throw std::invalid_argument(
            "camera: width and height must be positive");
    for (double value : result.params)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "camera: params must be finite");
    return result;
}

}  // namespace

int64_t colmap_pair_id(
    uint32_t image_id1, uint32_t image_id2) {
    if (image_id1 >= kColmapMaxNumImages ||
        image_id2 >= kColmapMaxNumImages)
        throw std::invalid_argument(
            "COLMAP: image id must be below 2147483647");
    if (image_id1 == image_id2)
        throw std::invalid_argument(
            "COLMAP: image pair endpoints must be distinct");
    const uint32_t low = std::min(image_id1, image_id2);
    const uint32_t high = std::max(image_id1, image_id2);
    return kColmapMaxNumImages * static_cast<int64_t>(low) +
           static_cast<int64_t>(high);
}

void validate_feature_set(
    const FeatureSet &features, const char *context) {
    if (features.image_id >= kColmapMaxNumImages ||
        features.camera_id >= kColmapMaxNumImages)
        throw std::invalid_argument(
            std::string(context) +
            ": image_id and camera_id must be below 2147483647");
    validate_text(features.image_name, context);
    if (features.image_width == 0 ||
        features.image_height == 0)
        throw std::invalid_argument(
            std::string(context) +
            ": image dimensions must be positive");
    if (features.image_width >
            static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()) ||
        features.image_height >
            static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()) ||
        features.rows >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()) ||
        features.keypoint_columns >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()) ||
        features.descriptor_columns >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument(
            std::string(context) +
            ": image or feature extents exceed SQLite INTEGER");
    if (features.keypoint_columns != 2 &&
        features.keypoint_columns != 4 &&
        features.keypoint_columns != 6)
        throw std::invalid_argument(
            std::string(context) +
            ": keypoint layout must have 2, 4, or 6 columns");
    if (!features.keypoints_present && features.rows != 0)
        throw std::invalid_argument(
            std::string(context) +
            ": absent keypoint rows must have zero keypoints");
    if (features.rows >
            std::numeric_limits<size_t>::max() /
                features.keypoint_columns ||
        features.keypoints.size() !=
            features.rows * features.keypoint_columns)
        throw std::invalid_argument(
            std::string(context) +
            ": inconsistent keypoint extent");
    for (float value : features.keypoints)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                std::string(context) +
                ": keypoints must be finite");

    if (!features.has_descriptors) {
        if (!features.descriptors.empty() ||
            features.descriptor_columns != 0 ||
            features.extractor_type != -1)
            throw std::invalid_argument(
                std::string(context) +
                ": absent descriptors carry descriptor metadata");
    } else {
        if (features.descriptor_dtype != sio::DType::U8 &&
            features.descriptor_dtype != sio::DType::F32)
            throw std::invalid_argument(
                std::string(context) +
                ": descriptor dtype must be uint8 or float32");
        const size_t expected = TensorDict::checked_size(
            "descriptors", features.descriptor_dtype,
            {features.rows, features.descriptor_columns});
        if (features.descriptors.size() != expected)
            throw std::invalid_argument(
                std::string(context) +
                ": descriptor bytes disagree with shape and dtype");
        if (features.descriptor_dtype == sio::DType::F32) {
            for (size_t offset = 0;
                 offset < features.descriptors.size();
                 offset += sizeof(float)) {
                float value;
                std::memcpy(
                    &value,
                    features.descriptors.data() + offset,
                    sizeof(float));
                if (!std::isfinite(value))
                    throw std::invalid_argument(
                        std::string(context) +
                        ": float descriptors must be finite");
            }
        }
    }

    if (features.has_scores) {
        if (features.scores.size() != features.rows)
            throw std::invalid_argument(
                std::string(context) +
                ": scores length must equal keypoint rows");
        for (float value : features.scores)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    std::string(context) +
                    ": scores must be finite");
    } else if (!features.scores.empty()) {
        throw std::invalid_argument(
            std::string(context) +
            ": absent scores carry values");
    }
}

void validate_match_graph(
    const MatchGraph &graph, const char *context) {
    const size_t count = graph.pair_count;
    if (count > std::numeric_limits<size_t>::max() / 9 ||
        graph.pair_ids.size() != count ||
        graph.image_pairs.size() != count * 2 ||
        graph.match_present.size() != count ||
        graph.geometry_present.size() != count ||
        graph.configs.size() != count ||
        graph.F_present.size() != count ||
        graph.E_present.size() != count ||
        graph.H_present.size() != count ||
        graph.F.size() != count * 9 ||
        graph.E.size() != count * 9 ||
        graph.H.size() != count * 9 ||
        graph.pose_present.size() != count ||
        graph.qvecs.size() != count * 4 ||
        graph.tvecs.size() != count * 3 ||
        graph.camera1_present.size() != count ||
        graph.camera2_present.size() != count ||
        graph.recovered_camera1.size() != count ||
        graph.recovered_camera2.size() != count ||
        graph.camera1_prior_focal_length.size() != count ||
        graph.camera2_prior_focal_length.size() != count)
        throw std::invalid_argument(
            std::string(context) +
            ": inconsistent MatchGraph field lengths");

    const size_t match_count = graph.matches.size() / 2;
    if (graph.matches.size() % 2 != 0)
        throw std::invalid_argument(
            std::string(context) +
            ": match values must contain two columns");
    validate_offsets(
        graph.match_offsets, count, match_count,
        context, "match_offsets");
    const size_t verified_count =
        graph.verified_matches.size() / 2;
    if (graph.verified_matches.size() % 2 != 0)
        throw std::invalid_argument(
            std::string(context) +
            ": verified match values must contain two columns");
    validate_offsets(
        graph.verified_offsets, count, verified_count,
        context, "verified_offsets");
    if (match_count >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()) ||
        verified_count >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument(
            std::string(context) +
            ": match counts exceed SQLite INTEGER");
    if (graph.has_scores) {
        if (graph.scores.size() != match_count)
            throw std::invalid_argument(
                std::string(context) +
                ": scores length must equal raw match count");
        for (float value : graph.scores)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    std::string(context) +
                    ": scores must be finite");
    } else if (!graph.scores.empty()) {
        throw std::invalid_argument(
            std::string(context) +
            ": absent scores carry values");
    }

    require_binary_flags(
        graph.match_present, context, "match_present");
    require_binary_flags(
        graph.geometry_present, context, "geometry_present");
    require_binary_flags(
        graph.F_present, context, "F_present");
    require_binary_flags(
        graph.E_present, context, "E_present");
    require_binary_flags(
        graph.H_present, context, "H_present");
    require_binary_flags(
        graph.pose_present, context, "pose_present");
    require_binary_flags(
        graph.camera1_present, context, "camera1_present");
    require_binary_flags(
        graph.camera2_present, context, "camera2_present");
    require_binary_flags(
        graph.camera1_prior_focal_length, context,
        "camera1_prior_focal_length");
    require_binary_flags(
        graph.camera2_prior_focal_length, context,
        "camera2_prior_focal_length");

    std::unordered_set<int64_t> seen;
    seen.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        const uint32_t low = graph.image_pairs[index * 2];
        const uint32_t high =
            graph.image_pairs[index * 2 + 1];
        if (low >= high)
            throw std::invalid_argument(
                std::string(context) +
                ": image_pairs must be distinct and ordered low first");
        const int64_t expected = colmap_pair_id(low, high);
        if (graph.pair_ids[index] != expected)
            throw std::invalid_argument(
                std::string(context) +
                ": pair id disagrees with its image endpoints");
        if (!seen.insert(expected).second)
            throw std::invalid_argument(
                std::string(context) +
                ": image pairs must be unique");
        if (!graph.match_present[index] &&
            !graph.geometry_present[index])
            throw std::invalid_argument(
                std::string(context) +
                ": every pair must exist in matches or "
                "two_view_geometries");
        if (!graph.match_present[index] &&
            graph.match_offsets[index] !=
                graph.match_offsets[index + 1])
            throw std::invalid_argument(
                std::string(context) +
                ": absent raw-match rows cannot carry matches");
        if (!graph.geometry_present[index] &&
            (graph.verified_offsets[index] !=
                 graph.verified_offsets[index + 1] ||
             graph.configs[index] != 0 ||
             graph.F_present[index] ||
             graph.E_present[index] ||
             graph.H_present[index] ||
             graph.pose_present[index] ||
             graph.camera1_present[index] ||
             graph.camera2_present[index]))
            throw std::invalid_argument(
                std::string(context) +
                ": absent geometry rows cannot carry geometry");
        const auto validate_recovered =
            [&](const Camera &camera, uint8_t present,
                uint8_t prior_focal_length,
                const char *name) {
                if (!present) {
                    if (prior_focal_length ||
                        !is_default_camera(camera))
                        throw std::invalid_argument(
                            std::string(context) + ": absent " +
                            name +
                            " cannot carry camera data or flags");
                    return;
                }
                validate_recovered_camera_value(
                    camera, context, name);
            };
        validate_recovered(
            graph.recovered_camera1[index],
            graph.camera1_present[index],
            graph.camera1_prior_focal_length[index],
            "recovered_camera1");
        validate_recovered(
            graph.recovered_camera2[index],
            graph.camera2_present[index],
            graph.camera2_prior_focal_length[index],
            "recovered_camera2");

        const std::array<std::pair<const std::vector<uint8_t> *,
                                   const std::vector<double> *>, 3>
            matrices = {{
                {&graph.F_present, &graph.F},
                {&graph.E_present, &graph.E},
                {&graph.H_present, &graph.H},
            }};
        for (const auto &entry : matrices) {
            if (!(*entry.first)[index]) continue;
            for (size_t component = 0; component < 9;
                 ++component)
                if (!std::isfinite(
                        (*entry.second)[index * 9 + component]))
                    throw std::invalid_argument(
                        std::string(context) +
                        ": present geometry matrices must be finite");
        }
        if (graph.pose_present[index]) {
            double norm_squared = 0.0;
            for (size_t component = 0; component < 4;
                 ++component) {
                const double value =
                    graph.qvecs[index * 4 + component];
                if (!std::isfinite(value))
                    throw std::invalid_argument(
                        std::string(context) +
                        ": relative qvecs must be finite");
                norm_squared += value * value;
            }
            if (!std::isfinite(norm_squared) ||
                std::abs(norm_squared - 1.0) > 1e-3)
                throw std::invalid_argument(
                    std::string(context) +
                    ": relative qvecs must be unit length "
                    "within 1e-3");
            for (size_t component = 0; component < 3;
                 ++component)
                if (!std::isfinite(
                        graph.tvecs[index * 3 + component]))
                    throw std::invalid_argument(
                        std::string(context) +
                        ": relative tvecs must be finite");
        }
    }
}

void validate_colmap_database(
    const ColmapDatabase &database, const char *context) {
    if (database.user_version < 0)
        throw std::invalid_argument(
            std::string(context) +
            ": user_version must be non-negative");
    if (database.prior_focal_length.size() !=
        database.cameras.size())
        throw std::invalid_argument(
            std::string(context) +
            ": prior_focal_length length must equal camera count");
    require_binary_flags(
        database.prior_focal_length, context,
        "prior_focal_length");

    std::unordered_map<uint32_t, const Camera *> cameras;
    cameras.reserve(database.cameras.size());
    for (const Camera &camera : database.cameras) {
        validate_camera_value(camera, context, "camera");
        if (!cameras.emplace(camera.id, &camera).second)
            throw std::invalid_argument(
                std::string(context) +
                ": camera ids must be unique");
    }

    std::unordered_map<uint32_t, size_t> feature_rows;
    std::unordered_set<std::string> names;
    feature_rows.reserve(database.features.size());
    names.reserve(database.features.size());
    for (const FeatureSet &features : database.features) {
        validate_feature_set(features, context);
        const auto camera = cameras.find(features.camera_id);
        if (camera == cameras.end())
            throw std::invalid_argument(
                std::string(context) +
                ": every image must reference a camera");
        if (features.image_width != camera->second->width ||
            features.image_height != camera->second->height)
            throw std::invalid_argument(
                std::string(context) +
                ": feature image_size must match its camera");
        if (!feature_rows.emplace(
                features.image_id, features.rows).second)
            throw std::invalid_argument(
                std::string(context) +
                ": image ids must be unique");
        if (!names.insert(features.image_name).second)
            throw std::invalid_argument(
                std::string(context) +
                ": image names must be unique");
    }

    validate_match_graph(database.match_graph, context);
    const MatchGraph &graph = database.match_graph;
    for (size_t pair = 0; pair < graph.pair_count; ++pair) {
        const uint32_t image_a = graph.image_pairs[pair * 2];
        const uint32_t image_b = graph.image_pairs[pair * 2 + 1];
        const auto rows_a = feature_rows.find(image_a);
        const auto rows_b = feature_rows.find(image_b);
        if (rows_a == feature_rows.end() ||
            rows_b == feature_rows.end())
            throw std::invalid_argument(
                std::string(context) +
                ": every match endpoint must reference an image");
        const auto check_range = [&](const std::vector<uint32_t> &values,
                                     uint64_t begin, uint64_t end,
                                     const char *kind) {
            for (uint64_t row = begin; row < end; ++row) {
                if (values[static_cast<size_t>(row) * 2] >=
                        rows_a->second ||
                    values[static_cast<size_t>(row) * 2 + 1] >=
                        rows_b->second)
                    throw std::invalid_argument(
                        std::string(context) + ": " + kind +
                        " index exceeds an endpoint FeatureSet");
            }
        };
        check_range(
            graph.matches, graph.match_offsets[pair],
            graph.match_offsets[pair + 1], "raw match");
        check_range(
            graph.verified_matches,
            graph.verified_offsets[pair],
            graph.verified_offsets[pair + 1],
            "verified match");
    }
}

void register_feature_match(nb::module_ &module) {
    const auto reference_internal =
        nb::rv_policy::reference_internal;

    nb::class_<FeatureSet>(module, "FeatureSet")
        .def_ro("image_id", &FeatureSet::image_id)
        .def_ro("image_name", &FeatureSet::image_name)
        .def_ro("camera_id", &FeatureSet::camera_id)
        .def_prop_ro(
            "image_size",
            [](const FeatureSet &value) {
                return std::array<uint64_t, 2>{
                    value.image_width, value.image_height};
            })
        .def_prop_ro(
            "time_id",
            [](const FeatureSet &value) -> nb::object {
                return value.has_time_id
                           ? nb::cast(value.time_id)
                           : nb::none();
            })
        .def_ro("extractor_type", &FeatureSet::extractor_type)
        .def_prop_ro(
            "keypoints_present",
            [](const FeatureSet &value) {
                return value.keypoints_present;
            })
        .def_prop_ro(
            "num_keypoints",
            [](const FeatureSet &value) { return value.rows; })
        .def_prop_ro(
            "keypoint_columns",
            [](const FeatureSet &value) {
                return value.keypoint_columns;
            })
        .def_prop_ro(
            "keypoints",
            [](const FeatureSet &value) {
                return typed_view(
                    value.keypoints,
                    {value.rows, value.keypoint_columns});
            },
            reference_internal)
        .def_prop_ro(
            "descriptors",
            [](nb::handle_t<FeatureSet> self) -> nb::object {
                const FeatureSet &value =
                    nb::cast<const FeatureSet &>(self);
                return value.has_descriptors
                           ? descriptor_view(self, value)
                           : nb::none();
            })
        .def_prop_ro(
            "descriptor_dtype",
            [](const FeatureSet &value) -> nb::object {
                return value.has_descriptors
                           ? nb::cast(std::string(
                                 sio::dtype_info(
                                     value.descriptor_dtype)
                                     .name))
                           : nb::none();
            })
        .def_prop_ro(
            "descriptor_dim",
            [](const FeatureSet &value) -> nb::object {
                return value.has_descriptors
                           ? nb::cast(value.descriptor_columns)
                           : nb::none();
            })
        .def_prop_ro(
            "scores",
            [](nb::handle_t<FeatureSet> self) -> nb::object {
                const FeatureSet &value =
                    nb::cast<const FeatureSet &>(self);
                return value.has_scores
                           ? owner_typed_view(
                                 self, value.scores, {value.rows})
                           : nb::none();
            })
        .def(
            "__len__",
            [](const FeatureSet &value) { return value.rows; })
        .def(
            "__repr__",
            [](const FeatureSet &value) {
                return "<FeatureSet image_id=" +
                       std::to_string(value.image_id) +
                       " keypoints=" +
                       std::to_string(value.rows) +
                       " layout=" +
                       std::to_string(value.keypoint_columns) +
                       ">";
            });

    nb::class_<MatchGraph>(module, "MatchGraph")
        .def_prop_ro(
            "num_pairs",
            [](const MatchGraph &value) {
                return value.num_pairs();
            })
        .def_prop_ro(
            "num_matches",
            [](const MatchGraph &value) {
                return value.num_matches();
            })
        .def_prop_ro(
            "num_verified_matches",
            [](const MatchGraph &value) {
                return value.num_verified_matches();
            })
        .def_prop_ro(
            "pair_ids",
            [](const MatchGraph &value) {
                return typed_view(
                    value.pair_ids, {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "image_pairs",
            [](const MatchGraph &value) {
                return typed_view(
                    value.image_pairs,
                    {value.pair_count, 2});
            },
            reference_internal)
        .def_prop_ro(
            "match_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.match_present, {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "geometry_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.geometry_present,
                    {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "match_offsets",
            [](const MatchGraph &value) {
                return typed_view(
                    value.match_offsets,
                    {value.pair_count + 1});
            },
            reference_internal)
        .def_prop_ro(
            "matches",
            [](const MatchGraph &value) {
                return typed_view(
                    value.matches,
                    {value.num_matches(), 2});
            },
            reference_internal)
        .def_prop_ro(
            "scores",
            [](nb::handle_t<MatchGraph> self) -> nb::object {
                const MatchGraph &value =
                    nb::cast<const MatchGraph &>(self);
                return value.has_scores
                           ? owner_typed_view(
                                 self, value.scores,
                                 {value.num_matches()})
                           : nb::none();
            })
        .def_prop_ro(
            "verified_offsets",
            [](const MatchGraph &value) {
                return typed_view(
                    value.verified_offsets,
                    {value.pair_count + 1});
            },
            reference_internal)
        .def_prop_ro(
            "verified_matches",
            [](const MatchGraph &value) {
                return typed_view(
                    value.verified_matches,
                    {value.num_verified_matches(), 2});
            },
            reference_internal)
        .def_prop_ro(
            "configs",
            [](const MatchGraph &value) {
                return typed_view(
                    value.configs, {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "F_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.F_present, {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "E_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.E_present, {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "H_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.H_present, {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "fundamental_matrices",
            [](const MatchGraph &value) {
                return typed_view(
                    value.F, {value.pair_count, 3, 3});
            },
            reference_internal)
        .def_prop_ro(
            "essential_matrices",
            [](const MatchGraph &value) {
                return typed_view(
                    value.E, {value.pair_count, 3, 3});
            },
            reference_internal)
        .def_prop_ro(
            "homographies",
            [](const MatchGraph &value) {
                return typed_view(
                    value.H, {value.pair_count, 3, 3});
            },
            reference_internal)
        .def_prop_ro(
            "pose_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.pose_present, {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "qvecs",
            [](const MatchGraph &value) {
                return typed_view(
                    value.qvecs, {value.pair_count, 4});
            },
            reference_internal)
        .def_prop_ro(
            "tvecs",
            [](const MatchGraph &value) {
                return typed_view(
                    value.tvecs, {value.pair_count, 3});
            },
            reference_internal)
        .def_prop_ro(
            "camera1_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.camera1_present,
                    {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "camera2_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.camera2_present,
                    {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "camera1_prior_focal_length",
            [](const MatchGraph &value) {
                return typed_view(
                    value.camera1_prior_focal_length,
                    {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "camera2_prior_focal_length",
            [](const MatchGraph &value) {
                return typed_view(
                    value.camera2_prior_focal_length,
                    {value.pair_count});
            },
            reference_internal)
        .def(
            "recovered_camera1",
            [](const MatchGraph &value,
               size_t index) -> nb::object {
                if (index >= value.pair_count)
                    throw nb::index_error();
                if (!value.camera1_present[index])
                    return nb::none();
                return nb::cast(Camera(
                    value.recovered_camera1[index]));
            },
            "index"_a)
        .def(
            "recovered_camera2",
            [](const MatchGraph &value,
               size_t index) -> nb::object {
                if (index >= value.pair_count)
                    throw nb::index_error();
                if (!value.camera2_present[index])
                    return nb::none();
                return nb::cast(Camera(
                    value.recovered_camera2[index]));
            },
            "index"_a)
        .def_prop_ro(
            "quaternion_order",
            [](const MatchGraph &) { return "wxyz"; })
        .def_prop_ro(
            "relative_pose_convention",
            [](const MatchGraph &) {
                return "second_from_first";
            })
        .def(
            "__repr__",
            [](const MatchGraph &value) {
                return "<MatchGraph pairs=" +
                       std::to_string(value.pair_count) +
                       " matches=" +
                       std::to_string(value.num_matches()) +
                       " verified=" +
                       std::to_string(
                           value.num_verified_matches()) +
                       ">";
            });

    nb::class_<ColmapDatabase>(module, "ColmapDatabase")
        .def_prop_ro(
            "num_cameras",
            [](const ColmapDatabase &value) {
                return value.num_cameras();
            })
        .def_prop_ro(
            "num_images",
            [](const ColmapDatabase &value) {
                return value.num_images();
            })
        .def_prop_ro(
            "cameras",
            [](const ColmapDatabase &value) {
                return value.cameras;
            })
        .def_prop_ro(
            "prior_focal_length",
            [](const ColmapDatabase &value) {
                return typed_view(
                    value.prior_focal_length,
                    {value.cameras.size()});
            },
            reference_internal)
        .def_prop_ro(
            "image_ids",
            [](const ColmapDatabase &value) {
                std::vector<uint32_t> result;
                result.reserve(value.features.size());
                for (const auto &features : value.features)
                    result.push_back(features.image_id);
                return result;
            })
        .def(
            "feature_at",
            [](const ColmapDatabase &value,
               size_t index) -> const FeatureSet & {
                if (index >= value.features.size())
                    throw nb::index_error();
                return value.features[index];
            },
            reference_internal)
        .def(
            "feature",
            [](const ColmapDatabase &value,
               uint32_t image_id) -> const FeatureSet & {
                for (const auto &features : value.features)
                    if (features.image_id == image_id)
                        return features;
                throw nb::key_error(
                    std::to_string(image_id).c_str());
            },
            reference_internal)
        .def_prop_ro(
            "match_graph",
            [](const ColmapDatabase &value)
                -> const MatchGraph & {
                return value.match_graph;
            },
            reference_internal)
        .def_ro("user_version", &ColmapDatabase::user_version)
        .def_ro("application_id", &ColmapDatabase::application_id)
        .def_ro("profile", &ColmapDatabase::profile)
        .def(
            "__repr__",
            [](const ColmapDatabase &value) {
                return "<ColmapDatabase cameras=" +
                       std::to_string(value.cameras.size()) +
                       " images=" +
                       std::to_string(value.features.size()) +
                       " pairs=" +
                       std::to_string(
                           value.match_graph.pair_count) +
                       ">";
            });

    module.def(
        "camera", &make_camera,
        "id"_a, "model_id"_a, "width"_a, "height"_a,
        "params"_a,
        "Build a COLMAP camera with model-checked float64 params.");
    module.def(
        "feature_set", &make_feature_set,
        "keypoints"_a, "descriptors"_a = nb::none(),
        "scores"_a = nb::none(), "image_id"_a = 0,
        "image_name"_a = "image", "camera_id"_a = 0,
        "image_size"_a = std::array<uint64_t, 2>{1, 1},
        "extractor_type"_a = -1, "time_id"_a = nb::none(),
        "keypoints_present"_a = true,
        "Build a typed per-image FeatureSet. Inputs are copied into "
        "record-owned storage.");
    module.def(
        "match_graph", &make_match_graph,
        "image_pairs"_a, "match_offsets"_a, "matches"_a,
        "verified_offsets"_a, "verified_matches"_a,
        "scores"_a = nb::none(), "configs"_a = nb::none(),
        "fundamental_matrices"_a = nb::none(),
        "fundamental_present"_a = nb::none(),
        "essential_matrices"_a = nb::none(),
        "essential_present"_a = nb::none(),
        "homographies"_a = nb::none(),
        "homography_present"_a = nb::none(),
        "qvecs"_a = nb::none(), "tvecs"_a = nb::none(),
        "pose_present"_a = nb::none(),
        "match_present"_a = nb::none(),
        "geometry_present"_a = nb::none(),
        "recovered_camera1"_a = nb::none(),
        "camera1_present"_a = nb::none(),
        "camera1_prior_focal_length"_a = nb::none(),
        "recovered_camera2"_a = nb::none(),
        "camera2_present"_a = nb::none(),
        "camera2_prior_focal_length"_a = nb::none(),
        "Build a typed ragged image-pair MatchGraph.");
    module.def(
        "colmap_database", &make_colmap_database,
        "cameras"_a, "features"_a, "match_graph"_a,
        "prior_focal_length"_a = nb::none(),
        "user_version"_a = 3140002,
        "profile"_a = "sceneio-hybrid-v1",
        "application_id"_a = 0,
        "Build the lossless core payload of a COLMAP feature "
        "database.");
}
