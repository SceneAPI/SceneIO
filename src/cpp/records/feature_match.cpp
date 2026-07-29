// records/feature_match.cpp -- validation, construction, and nanobind views.
#include <nanobind/stl/array.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <optional>
#include <stdexcept>
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
            std::string(context) + " must be non-empty");
    if (value.find('\0') != std::string::npos)
        throw std::invalid_argument(
            std::string(context) + " cannot contain embedded NUL");
    if (!sio::valid_utf8(value))
        throw std::invalid_argument(
            std::string(context) + " must be valid UTF-8");
}

void validate_nullable_text(
    const std::string &value, const char *context) {
    if (value.find('\0') != std::string::npos)
        throw std::invalid_argument(
            std::string(context) +
            ": text cannot contain embedded NUL");
    if (!sio::valid_utf8(value))
        throw std::invalid_argument(
            std::string(context) +
            ": text must be valid UTF-8");
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
    if (count > std::numeric_limits<size_t>::max() / 36)
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
    result.match_score_present.assign(
        count, static_cast<uint8_t>(has_scores));
    result.provenance_present.assign(count, 0);
    result.source_flags.assign(count, 0);
    result.retrieval_score_present.assign(count, 0);
    result.retrieval_scores.assign(count, 0.0f);
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
    result.pose_priors.generalized = true;
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
    if (features.has_time_id &&
        (features.time_id < 0 ||
         features.time_id >=
             static_cast<int64_t>(
                 std::numeric_limits<uint32_t>::max())))
        throw std::invalid_argument(
            std::string(context) +
            ": time_id must be a valid uint32 frame id");
    if (!features.has_time_id && features.time_id != 0)
        throw std::invalid_argument(
            std::string(context) +
            ": absent time_id carries a value");
    if (features.image_id >= kColmapMaxNumImages ||
        features.camera_id >= kColmapMaxNumImages)
        throw std::invalid_argument(
            std::string(context) +
            ": image_id and camera_id must be below 2147483647");
    validate_text(features.image_name, "image_name");
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
            features.extractor_type != -1 ||
            features.descriptor_dtype_present ||
            features.descriptor_dim_present ||
            features.extractor_type_name_present ||
            !features.extractor_type_name.empty())
            throw std::invalid_argument(
                std::string(context) +
                ": absent descriptors carry descriptor metadata");
    } else {
        if (features.descriptor_dtype != sio::DType::U8 &&
            features.descriptor_dtype != sio::DType::I8 &&
            features.descriptor_dtype != sio::DType::F16 &&
            features.descriptor_dtype != sio::DType::F32 &&
            features.descriptor_dtype != sio::DType::F64)
            throw std::invalid_argument(
                std::string(context) +
                ": descriptor dtype is not a MAXX wire dtype");
        if ((features.extractor_type == 0 &&
             features.descriptor_dtype != sio::DType::U8) ||
            ((features.extractor_type == 1 ||
              features.extractor_type == 2) &&
             features.descriptor_dtype != sio::DType::F32))
            throw std::invalid_argument(
                std::string(context) +
                ": descriptor dtype contradicts its built-in "
                "extractor type");
        if (features.extractor_type_name_present)
            validate_nullable_text(
                features.extractor_type_name,
                "extractor type_name");
        else if (!features.extractor_type_name.empty())
            throw std::invalid_argument(
                std::string(context) +
                ": absent extractor type_name carries text");
        const size_t expected = TensorDict::checked_size(
            "descriptors", features.descriptor_dtype,
            {features.rows, features.descriptor_columns});
        if (features.descriptors.size() != expected)
            throw std::invalid_argument(
                std::string(context) +
                ": descriptor bytes disagree with shape and dtype");
    }

    if (features.keypoint_colors_present) {
        if (!features.keypoints_present ||
            features.rows >
                std::numeric_limits<size_t>::max() / 3 ||
            features.keypoint_colors.size() != features.rows * 3)
            throw std::invalid_argument(
                std::string(context) +
                ": keypoint colors must be Nx3 and parallel "
                "to keypoints");
    } else if (!features.keypoint_colors.empty()) {
        throw std::invalid_argument(
            std::string(context) +
            ": absent keypoint colors carry values");
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
    if (features.quality_present) {
        if (!std::isfinite(features.quality))
            throw std::invalid_argument(
                std::string(context) +
                ": image quality must be finite");
    } else if (features.quality != 0.0) {
        throw std::invalid_argument(
            std::string(context) +
            ": absent image quality carries a value");
    }
}

void validate_match_graph(
    const MatchGraph &graph, const char *context) {
    const size_t count = graph.pair_count;
    if (count > std::numeric_limits<size_t>::max() / 9 ||
        graph.pair_ids.size() != count ||
        graph.image_pairs.size() != count * 2 ||
        graph.match_present.size() != count ||
        graph.match_score_present.size() != count ||
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
        graph.camera2_prior_focal_length.size() != count ||
        graph.provenance_present.size() != count ||
        graph.source_flags.size() != count ||
        graph.retrieval_score_present.size() != count ||
        graph.retrieval_scores.size() != count)
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
    } else if (!graph.scores.empty()) {
        throw std::invalid_argument(
            std::string(context) +
            ": absent scores carry values");
    }
    const bool any_match_score = std::any_of(
        graph.match_score_present.begin(),
        graph.match_score_present.end(),
        [](uint8_t present) { return present != 0; });
    if (graph.has_scores != any_match_score)
        throw std::invalid_argument(
            std::string(context) +
            ": has_scores must match score-row presence");

    require_binary_flags(
        graph.match_present, context, "match_present");
    require_binary_flags(
        graph.match_score_present, context,
        "match_score_present");
    require_binary_flags(
        graph.geometry_present, context, "geometry_present");
    require_binary_flags(
        graph.provenance_present, context,
        "provenance_present");
    require_binary_flags(
        graph.retrieval_score_present, context,
        "retrieval_score_present");
    for (size_t index = 0; index < count; ++index) {
        const size_t begin =
            static_cast<size_t>(graph.match_offsets[index]);
        const size_t end =
            static_cast<size_t>(graph.match_offsets[index + 1]);
        if (graph.match_score_present[index] &&
            !graph.match_present[index])
            throw std::invalid_argument(
                std::string(context) +
                ": match scores require a raw match row");
        if (graph.has_scores &&
            !graph.match_score_present[index])
            for (size_t score = begin; score < end; ++score)
                if (graph.scores[score] != 0.0f)
                    throw std::invalid_argument(
                        std::string(context) +
                        ": absent match scores carry values");
        if (!graph.provenance_present[index] &&
            (graph.source_flags[index] != 0 ||
             graph.retrieval_score_present[index]))
            throw std::invalid_argument(
                std::string(context) +
                ": absent provenance carries metadata");
        if (!graph.retrieval_score_present[index] &&
            graph.retrieval_scores[index] != 0.0f) {
            throw std::invalid_argument(
                std::string(context) +
                ": absent retrieval score carries a value");
        }
    }
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
            !graph.geometry_present[index] &&
            !graph.provenance_present[index])
            throw std::invalid_argument(
                std::string(context) +
                ": every pair must exist in matches, "
                "two_view_geometries, or pair_provenance");
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

void validate_colmap_rig_frames(
    const ColmapRigFrameSet &value, const char *context) {
    const size_t rigs = value.num_rigs();
    const size_t sensors = value.num_rig_sensors();
    const size_t frames = value.num_frames();
    const size_t data = value.num_frame_data();
    if (sensors > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument(
            std::string(context) +
            ": rig sensor count overflows field lengths");
    if (value.rig_ref_sensor_types.size() != rigs ||
        value.rig_ref_sensor_ids.size() != rigs ||
        value.rig_sensor_types.size() != sensors ||
        value.rig_sensor_pose_present.size() != sensors ||
        value.rig_sensor_qvecs.size() != sensors * 4 ||
        value.rig_sensor_tvecs.size() != sensors * 3 ||
        value.frame_rig_ids.size() != frames ||
        value.frame_sensor_types.size() != data ||
        value.frame_sensor_ids.size() != data)
        throw std::invalid_argument(
            std::string(context) +
            ": inconsistent rig/frame field lengths");
    validate_offsets(
        value.rig_sensor_offsets, rigs, sensors,
        context, "rig_sensor_offsets");
    validate_offsets(
        value.frame_data_offsets, frames, data,
        context, "frame_data_offsets");
    require_binary_flags(
        value.rig_sensor_pose_present, context,
        "rig_sensor_pose_present");

    const auto sensor_key =
        [&](int32_t type, uint32_t id,
            const char *field) -> uint64_t {
            if ((type != 0 && type != 1) ||
                id == std::numeric_limits<uint32_t>::max())
                throw std::invalid_argument(
                    std::string(context) + ": " + field +
                    " must use CAMERA/IMU and a non-sentinel id");
            return (static_cast<uint64_t>(type) << 32) | id;
        };
    std::unordered_map<uint32_t, size_t> rig_index;
    std::unordered_set<uint64_t> assigned_sensors;
    rig_index.reserve(rigs);
    assigned_sensors.reserve(rigs + sensors);
    for (size_t rig = 0; rig < rigs; ++rig) {
        const uint32_t rig_id = value.rig_ids[rig];
        if (rig_id == std::numeric_limits<uint32_t>::max() ||
            !rig_index.emplace(rig_id, rig).second)
            throw std::invalid_argument(
                std::string(context) +
                ": rig ids must be non-sentinel and unique");
        if (!assigned_sensors.insert(sensor_key(
                value.rig_ref_sensor_types[rig],
                value.rig_ref_sensor_ids[rig],
                "reference sensor")).second)
            throw std::invalid_argument(
                std::string(context) +
                ": a sensor cannot belong to multiple rigs");
        for (uint64_t row = value.rig_sensor_offsets[rig];
             row < value.rig_sensor_offsets[rig + 1]; ++row) {
            const size_t index = static_cast<size_t>(row);
            if (!assigned_sensors.insert(sensor_key(
                    value.rig_sensor_types[index],
                    value.rig_sensor_ids[index],
                    "rig sensor")).second)
                throw std::invalid_argument(
                    std::string(context) +
                    ": a sensor cannot belong to multiple rigs");
            double norm_squared = 0.0;
            for (size_t component = 0; component < 4; ++component) {
                const double item =
                    value.rig_sensor_qvecs[index * 4 + component];
                if (value.rig_sensor_pose_present[index] &&
                    !std::isfinite(item))
                    throw std::invalid_argument(
                        std::string(context) +
                        ": sensor pose quaternion must be finite");
                norm_squared += item * item;
            }
            for (size_t component = 0; component < 3; ++component) {
                const double item =
                    value.rig_sensor_tvecs[index * 3 + component];
                if (value.rig_sensor_pose_present[index] &&
                    !std::isfinite(item))
                    throw std::invalid_argument(
                        std::string(context) +
                        ": sensor pose translation must be finite");
            }
            if (value.rig_sensor_pose_present[index]) {
                const double norm = std::sqrt(norm_squared);
                if (!std::isfinite(norm) ||
                    std::abs(norm - 1.0) > 1e-6)
                    throw std::invalid_argument(
                        std::string(context) +
                        ": sensor pose quaternion must be unit length");
            } else {
                for (size_t component = 0; component < 4; ++component)
                    if (value.rig_sensor_qvecs[
                            index * 4 + component] != 0.0)
                        throw std::invalid_argument(
                            std::string(context) +
                            ": absent sensor pose carries a quaternion");
                for (size_t component = 0; component < 3; ++component)
                    if (value.rig_sensor_tvecs[
                            index * 3 + component] != 0.0)
                        throw std::invalid_argument(
                            std::string(context) +
                            ": absent sensor pose carries a translation");
            }
        }
    }

    std::unordered_set<uint32_t> frame_ids;
    std::unordered_set<std::string> assigned_data;
    frame_ids.reserve(frames);
    assigned_data.reserve(data);
    for (size_t frame = 0; frame < frames; ++frame) {
        const uint32_t frame_id = value.frame_ids[frame];
        const auto rig = rig_index.find(value.frame_rig_ids[frame]);
        if (frame_id == std::numeric_limits<uint32_t>::max() ||
            !frame_ids.insert(frame_id).second ||
            rig == rig_index.end())
            throw std::invalid_argument(
                std::string(context) +
                ": frames contain an invalid id or rig reference");
        std::unordered_set<uint64_t> rig_sensors;
        const size_t rig_row = rig->second;
        rig_sensors.insert(sensor_key(
            value.rig_ref_sensor_types[rig_row],
            value.rig_ref_sensor_ids[rig_row],
            "reference sensor"));
        for (uint64_t row =
                 value.rig_sensor_offsets[rig_row];
             row < value.rig_sensor_offsets[rig_row + 1]; ++row) {
            const size_t index = static_cast<size_t>(row);
            rig_sensors.insert(sensor_key(
                value.rig_sensor_types[index],
                value.rig_sensor_ids[index], "rig sensor"));
        }
        for (uint64_t row = value.frame_data_offsets[frame];
             row < value.frame_data_offsets[frame + 1]; ++row) {
            const size_t index = static_cast<size_t>(row);
            const uint64_t data_id = value.frame_data_ids[index];
            const uint64_t sensor = sensor_key(
                value.frame_sensor_types[index],
                value.frame_sensor_ids[index], "frame sensor");
            if (!rig_sensors.count(sensor))
                throw std::invalid_argument(
                    std::string(context) +
                    ": frame data references an invalid datum or sensor");
            const std::string key =
                std::to_string(value.frame_sensor_types[index]) + ":" +
                std::to_string(data_id);
            if (!assigned_data.insert(key).second)
                throw std::invalid_argument(
                    std::string(context) +
                    ": one datum cannot belong to multiple frames");
        }
    }
}

void validate_colmap_pose_priors(
    const ColmapPosePriorSet &value, const char *context) {
    const size_t count = value.size();
    if (count > std::numeric_limits<size_t>::max() / 9)
        throw std::invalid_argument(
            std::string(context) +
            ": pose-prior count overflows field lengths");
    if (value.corr_data_ids.size() != count ||
        value.corr_sensor_ids.size() != count ||
        value.corr_sensor_types.size() != count ||
        value.coordinate_systems.size() != count ||
        value.position_present.size() != count ||
        value.positions.size() != count * 3 ||
        value.position_covariance_present.size() != count ||
        value.position_covariances.size() != count * 9 ||
        value.gravity_present.size() != count ||
        value.gravities.size() != count * 3 ||
        value.rotation_present.size() != count ||
        value.rotations.size() != count * 4 ||
        value.rotation_covariance_present.size() != count ||
        value.rotation_covariances.size() != count * 9 ||
        value.pose_covariance_present.size() != count ||
        (count != 0 &&
         value.pose_covariances.size() / count != 36) ||
        value.pose_covariances.size() != count * 36)
        throw std::invalid_argument(
            std::string(context) +
            ": inconsistent pose-prior field lengths");
    require_binary_flags(
        value.position_present, context, "position_present");
    require_binary_flags(
        value.position_covariance_present, context,
        "position_covariance_present");
    require_binary_flags(
        value.gravity_present, context, "gravity_present");
    require_binary_flags(
        value.rotation_present, context, "rotation_present");
    require_binary_flags(
        value.rotation_covariance_present, context,
        "rotation_covariance_present");
    require_binary_flags(
        value.pose_covariance_present, context,
        "pose_covariance_present");
    std::unordered_set<uint32_t> ids;
    std::unordered_set<std::string> data;
    ids.reserve(count);
    data.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        const uint32_t id = value.prior_ids[index];
        const uint64_t data_id = value.corr_data_ids[index];
        const uint32_t sensor_id = value.corr_sensor_ids[index];
        const int32_t sensor_type = value.corr_sensor_types[index];
        if (id == std::numeric_limits<uint32_t>::max() ||
            sensor_id == std::numeric_limits<uint32_t>::max() ||
            (sensor_type != 0 && sensor_type != 1) ||
            value.coordinate_systems[index] < -1 ||
            value.coordinate_systems[index] > 1 ||
            !ids.insert(id).second)
            throw std::invalid_argument(
                std::string(context) +
                ": pose prior metadata is invalid");
        const std::string data_key =
            std::to_string(sensor_type) + ":" +
            std::to_string(sensor_id) + ":" +
            std::to_string(data_id);
        if (!data.insert(data_key).second)
            throw std::invalid_argument(
                std::string(context) +
                ": correlated data ids must be unique");
        const auto validate_values =
            [&](const std::vector<double> &items, size_t begin,
                size_t length, uint8_t present,
                const char *field) {
                for (size_t component = 0; component < length;
                     ++component) {
                    const double item = items[begin + component];
                    if (!present && item != 0.0)
                        throw std::invalid_argument(
                            std::string(context) + ": " + field +
                            " is absent but carries values");
                }
            };
        validate_values(
            value.positions, index * 3, 3,
            value.position_present[index], "position");
        validate_values(
            value.position_covariances, index * 9, 9,
            value.position_covariance_present[index],
            "position covariance");
        validate_values(
            value.gravities, index * 3, 3,
            value.gravity_present[index], "gravity");
        validate_values(
            value.rotations, index * 4, 4,
            value.rotation_present[index], "rotation");
        validate_values(
            value.rotation_covariances, index * 9, 9,
            value.rotation_covariance_present[index],
            "rotation covariance");
        validate_values(
            value.pose_covariances, index * 36, 36,
            value.pose_covariance_present[index],
            "pose covariance");
        if (!value.generalized &&
            (sensor_type != 0 || id != data_id ||
             value.gravity_present[index] ||
             value.rotation_present[index] ||
             value.rotation_covariance_present[index] ||
             value.pose_covariance_present[index]))
            throw std::invalid_argument(
                std::string(context) +
                ": image-linked pose priors cannot carry generalized "
                "associations or gravity");
    }
}

void validate_colmap_markers(
    const ColmapMarkerSet &value, const char *context) {
    const size_t markers = value.num_markers();
    const size_t projections = value.num_projections();
    if (markers > std::numeric_limits<size_t>::max() / 9 ||
        projections >
            std::numeric_limits<size_t>::max() / 2 ||
        value.labels.size() != markers ||
        value.types.size() != markers ||
        value.world_position_present.size() != markers ||
        value.world_positions.size() != markers * 3 ||
        value.world_covariance_present.size() != markers ||
        value.world_covariances.size() != markers * 9 ||
        value.point3d_ids.size() != markers ||
        value.enabled.size() != markers ||
        value.projection_image_ids.size() != projections ||
        value.projection_xy.size() != projections * 2 ||
        value.projection_sizes.size() != projections ||
        value.projection_pinned.size() != projections ||
        value.projection_point2d_indices.size() != projections)
        throw std::invalid_argument(
            std::string(context) +
            ": inconsistent marker field lengths");
    require_binary_flags(
        value.world_position_present, context,
        "world_position_present");
    require_binary_flags(
        value.world_covariance_present, context,
        "world_covariance_present");
    require_binary_flags(value.enabled, context, "marker enabled");
    require_binary_flags(
        value.projection_pinned, context,
        "projection pinned");
    std::unordered_set<uint32_t> marker_ids;
    std::unordered_set<std::string> labels;
    marker_ids.reserve(markers);
    labels.reserve(markers);
    for (size_t index = 0; index < markers; ++index) {
        if (value.marker_ids[index] ==
                std::numeric_limits<uint32_t>::max() ||
            !marker_ids.insert(value.marker_ids[index]).second ||
            value.types[index] < 0 || value.types[index] > 3)
            throw std::invalid_argument(
                std::string(context) +
                ": marker id or type is invalid");
        validate_text(value.labels[index], "marker label");
        if (!labels.insert(value.labels[index]).second)
            throw std::invalid_argument(
                std::string(context) +
                ": marker labels must be unique");
        for (size_t component = 0; component < 3; ++component)
            if (!value.world_position_present[index] &&
                value.world_positions[index * 3 + component] != 0.0)
                throw std::invalid_argument(
                    std::string(context) +
                    ": absent marker position carries values");
        for (size_t component = 0; component < 9; ++component)
            if (!value.world_covariance_present[index] &&
                value.world_covariances[
                    index * 9 + component] != 0.0)
                throw std::invalid_argument(
                    std::string(context) +
                    ": absent marker covariance carries values");
    }
    std::unordered_set<std::string> projection_keys;
    projection_keys.reserve(projections);
    for (size_t index = 0; index < projections; ++index) {
        if (!marker_ids.count(
                value.projection_marker_ids[index]))
            throw std::invalid_argument(
                std::string(context) +
                ": marker projection metadata is invalid");
        const std::string key =
            std::to_string(value.projection_marker_ids[index]) +
            ":" +
            std::to_string(value.projection_image_ids[index]);
        if (!projection_keys.insert(key).second)
            throw std::invalid_argument(
                std::string(context) +
                ": marker projections must be unique");
    }
}

void validate_colmap_videos(
    const ColmapVideoMetadataSet &value, const char *context) {
    const size_t videos = value.num_videos();
    const size_t frames = value.num_video_frames();
    if (value.names.size() != videos ||
        value.source_path_present.size() != videos ||
        value.source_paths.size() != videos ||
        value.content_hash_present.size() != videos ||
        value.content_hashes.size() != videos ||
        value.widths.size() != videos ||
        value.heights.size() != videos ||
        value.num_frames.size() != videos ||
        value.fps.size() != videos ||
        value.duration_seconds.size() != videos ||
        value.codec_name_present.size() != videos ||
        value.codec_names.size() != videos ||
        value.sync_group_present.size() != videos ||
        value.sync_groups.size() != videos ||
        value.frame_image_ids.size() != frames ||
        value.frame_ids.size() != frames ||
        value.pts_present.size() != frames ||
        value.pts_seconds.size() != frames ||
        value.time_id_present.size() != frames ||
        value.time_ids.size() != frames)
        throw std::invalid_argument(
            std::string(context) +
            ": inconsistent video field lengths");
    require_binary_flags(
        value.source_path_present, context,
        "source_path_present");
    require_binary_flags(
        value.content_hash_present, context,
        "content_hash_present");
    require_binary_flags(
        value.codec_name_present, context,
        "codec_name_present");
    require_binary_flags(
        value.sync_group_present, context,
        "sync_group_present");
    require_binary_flags(
        value.pts_present, context, "pts_present");
    require_binary_flags(
        value.time_id_present, context, "time_id_present");
    std::unordered_set<uint32_t> video_ids;
    std::unordered_set<std::string> names;
    video_ids.reserve(videos);
    names.reserve(videos);
    for (size_t index = 0; index < videos; ++index) {
        if (value.video_ids[index] ==
                std::numeric_limits<uint32_t>::max() ||
            !video_ids.insert(value.video_ids[index]).second)
            throw std::invalid_argument(
                std::string(context) +
                ": video metadata is invalid");
        validate_text(value.names[index], "video name");
        if (!names.insert(value.names[index]).second)
            throw std::invalid_argument(
                std::string(context) +
                ": video names must be unique");
        const auto check_optional_text =
            [&](uint8_t present, const std::string &item,
                const char *field) {
                if (present)
                    validate_nullable_text(item, field);
                else if (!item.empty())
                    throw std::invalid_argument(
                        std::string(context) + ": absent " +
                        field + " carries text");
            };
        check_optional_text(
            value.source_path_present[index],
            value.source_paths[index], "video source_path");
        check_optional_text(
            value.content_hash_present[index],
            value.content_hashes[index], "video content_hash");
        check_optional_text(
            value.codec_name_present[index],
            value.codec_names[index], "video codec_name");
        check_optional_text(
            value.sync_group_present[index],
            value.sync_groups[index], "video sync_group");
    }
    std::unordered_set<std::string> frame_keys;
    std::unordered_set<uint32_t> frame_images;
    frame_keys.reserve(frames);
    frame_images.reserve(frames);
    for (size_t index = 0; index < frames; ++index) {
        if (!video_ids.count(value.frame_video_ids[index]) ||
            value.frame_ids[index] < 0 ||
            (!value.pts_present[index] &&
             value.pts_seconds[index] != 0.0) ||
            (!value.time_id_present[index] &&
             value.time_ids[index] != 0) ||
            (value.time_id_present[index] &&
             value.time_ids[index] ==
                 std::numeric_limits<uint32_t>::max()))
            throw std::invalid_argument(
                std::string(context) +
                ": video-frame metadata is invalid");
        const std::string key =
            std::to_string(value.frame_video_ids[index]) +
            ":" + std::to_string(value.frame_ids[index]);
        if (!frame_keys.insert(key).second ||
            !frame_images.insert(
                value.frame_image_ids[index]).second)
            throw std::invalid_argument(
                std::string(context) +
                ": video-frame assignments must be unique");
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
    std::unordered_map<uint32_t, uint32_t> feature_cameras;
    std::unordered_set<std::string> names;
    feature_rows.reserve(database.features.size());
    feature_cameras.reserve(database.features.size());
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
        feature_cameras.emplace(
            features.image_id, features.camera_id);
        if (!names.insert(features.image_name).second)
            throw std::invalid_argument(
                std::string(context) +
                ": image names must be unique");
    }

    validate_match_graph(database.match_graph, context);
    validate_colmap_rig_frames(database.rig_frames, context);
    validate_colmap_pose_priors(database.pose_priors, context);
    validate_colmap_markers(database.markers, context);
    validate_colmap_videos(database.video_metadata, context);
    if (database.maxx_schema_info.present) {
        if (database.maxx_schema_info.schema_version == 0 ||
            database.maxx_schema_info.minimum_reader_version == 0)
            throw std::invalid_argument(
                std::string(context) +
                ": MAXX ownership versions must be positive");
        validate_text(
            database.maxx_schema_info.producer_version,
            "MAXX producer_version");
        validate_text(
            database.maxx_schema_info.producer_commit,
            "MAXX producer_commit");
    } else if (database.maxx_schema_info.schema_version != 0 ||
               database.maxx_schema_info.minimum_reader_version != 0 ||
               !database.maxx_schema_info.producer_version.empty() ||
               !database.maxx_schema_info.producer_commit.empty()) {
        throw std::invalid_argument(
            std::string(context) +
            ": absent MAXX ownership carries metadata");
    }
    const ColmapRigFrameSet &rig_frames =
        database.rig_frames;
    for (size_t frame = 0;
         frame < rig_frames.num_frames(); ++frame) {
        for (uint64_t row =
                 rig_frames.frame_data_offsets[frame];
             row < rig_frames.frame_data_offsets[frame + 1];
             ++row) {
            const size_t index = static_cast<size_t>(row);
            if (rig_frames.frame_sensor_types[index] != 0)
                continue;
            const uint64_t data_id =
                rig_frames.frame_data_ids[index];
            if (data_id >
                std::numeric_limits<uint32_t>::max())
                continue;
            const auto image = feature_cameras.find(
                static_cast<uint32_t>(data_id));
            // Stock permits staged/orphan frame data. When its image is
            // present, however, the camera identity cannot contradict it.
            if (image != feature_cameras.end() &&
                image->second !=
                    rig_frames.frame_sensor_ids[index])
                throw std::invalid_argument(
                    std::string(context) +
                    ": CAMERA frame datum disagrees with its image "
                    "camera");
        }
    }
    if (!database.pose_priors.generalized) {
        for (size_t index = 0;
             index < database.pose_priors.size(); ++index) {
            const uint64_t data_id =
                database.pose_priors.corr_data_ids[index];
            if (data_id >
                std::numeric_limits<uint32_t>::max())
                throw std::invalid_argument(
                    std::string(context) +
                    ": image-linked pose prior has an invalid image id");
            const auto feature = feature_cameras.find(
                static_cast<uint32_t>(data_id));
            if (feature == feature_cameras.end() ||
                feature->second !=
                    database.pose_priors.corr_sensor_ids[index])
                throw std::invalid_argument(
                    std::string(context) +
                    ": image-linked pose prior does not match its image "
                    "camera");
        }
    }
    const ColmapMarkerSet &markers = database.markers;
    for (size_t index = 0;
         index < markers.num_projections(); ++index) {
        const auto feature = feature_rows.find(
            markers.projection_image_ids[index]);
        if (feature == feature_rows.end())
            throw std::invalid_argument(
                std::string(context) +
                ": marker projection references a missing image");
    }
    const ColmapVideoMetadataSet &videos =
        database.video_metadata;
    for (size_t index = 0;
         index < videos.num_video_frames(); ++index) {
        const auto feature = feature_rows.find(
            videos.frame_image_ids[index]);
        if (feature == feature_rows.end())
            throw std::invalid_argument(
                std::string(context) +
                ": video frame references a missing image");
    }
    const MatchGraph &graph = database.match_graph;
    for (size_t pair = 0; pair < graph.pair_count; ++pair) {
        const uint32_t image_a = graph.image_pairs[pair * 2];
        const uint32_t image_b = graph.image_pairs[pair * 2 + 1];
        const auto rows_a = feature_rows.find(image_a);
        const auto rows_b = feature_rows.find(image_b);
        if (rows_a == feature_rows.end() ||
            rows_b == feature_rows.end()) {
            if (graph.match_present[pair] ||
                graph.geometry_present[pair])
                throw std::invalid_argument(
                    std::string(context) +
                    ": every data-bearing match endpoint "
                    "must reference an image");
            continue;
        }
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
            "extractor_type_name",
            [](const FeatureSet &value) -> nb::object {
                return value.extractor_type_name_present
                           ? nb::cast(value.extractor_type_name)
                           : nb::none();
            })
        .def_prop_ro(
            "descriptor_dtype_present",
            [](const FeatureSet &value) {
                return value.descriptor_dtype_present;
            })
        .def_prop_ro(
            "descriptor_dim_present",
            [](const FeatureSet &value) {
                return value.descriptor_dim_present;
            })
        .def_prop_ro(
            "keypoint_colors",
            [](nb::handle_t<FeatureSet> self) -> nb::object {
                const FeatureSet &value =
                    nb::cast<const FeatureSet &>(self);
                return value.keypoint_colors_present
                           ? owner_typed_view(
                                 self, value.keypoint_colors,
                                 {value.rows, 3})
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
        .def_prop_ro(
            "quality",
            [](const FeatureSet &value) -> nb::object {
                return value.quality_present
                           ? nb::cast(value.quality)
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
            "match_score_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.match_score_present,
                    {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "provenance_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.provenance_present,
                    {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "source_flags",
            [](const MatchGraph &value) {
                return typed_view(
                    value.source_flags,
                    {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "retrieval_score_present",
            [](const MatchGraph &value) {
                return typed_view(
                    value.retrieval_score_present,
                    {value.pair_count});
            },
            reference_internal)
        .def_prop_ro(
            "retrieval_scores",
            [](const MatchGraph &value) {
                return typed_view(
                    value.retrieval_scores,
                    {value.pair_count});
            },
            reference_internal)
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

    nb::class_<ColmapRigFrameSet>(module, "ColmapRigFrameSet")
        .def_prop_ro(
            "num_rigs",
            [](const ColmapRigFrameSet &value) {
                return value.num_rigs();
            })
        .def_prop_ro(
            "num_rig_sensors",
            [](const ColmapRigFrameSet &value) {
                return value.num_rig_sensors();
            })
        .def_prop_ro(
            "num_frames",
            [](const ColmapRigFrameSet &value) {
                return value.num_frames();
            })
        .def_prop_ro(
            "num_frame_data",
            [](const ColmapRigFrameSet &value) {
                return value.num_frame_data();
            })
        .def_prop_ro(
            "rig_ids",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_ids, {value.num_rigs()});
            },
            reference_internal)
        .def_prop_ro(
            "rig_reference_sensor_types",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_ref_sensor_types,
                    {value.num_rigs()});
            },
            reference_internal)
        .def_prop_ro(
            "rig_reference_sensor_ids",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_ref_sensor_ids,
                    {value.num_rigs()});
            },
            reference_internal)
        .def_prop_ro(
            "rig_sensor_offsets",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_sensor_offsets,
                    {value.num_rigs() + 1});
            },
            reference_internal)
        .def_prop_ro(
            "rig_sensor_types",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_sensor_types,
                    {value.num_rig_sensors()});
            },
            reference_internal)
        .def_prop_ro(
            "rig_sensor_ids",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_sensor_ids,
                    {value.num_rig_sensors()});
            },
            reference_internal)
        .def_prop_ro(
            "rig_sensor_pose_present",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_sensor_pose_present,
                    {value.num_rig_sensors()});
            },
            reference_internal)
        .def_prop_ro(
            "rig_sensor_quaternions",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_sensor_qvecs,
                    {value.num_rig_sensors(), 4});
            },
            reference_internal)
        .def_prop_ro(
            "rig_sensor_translations",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.rig_sensor_tvecs,
                    {value.num_rig_sensors(), 3});
            },
            reference_internal)
        .def_prop_ro(
            "frame_ids",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.frame_ids, {value.num_frames()});
            },
            reference_internal)
        .def_prop_ro(
            "frame_rig_ids",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.frame_rig_ids, {value.num_frames()});
            },
            reference_internal)
        .def_prop_ro(
            "frame_data_offsets",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.frame_data_offsets,
                    {value.num_frames() + 1});
            },
            reference_internal)
        .def_prop_ro(
            "frame_data_ids",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.frame_data_ids,
                    {value.num_frame_data()});
            },
            reference_internal)
        .def_prop_ro(
            "frame_sensor_types",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.frame_sensor_types,
                    {value.num_frame_data()});
            },
            reference_internal)
        .def_prop_ro(
            "frame_sensor_ids",
            [](const ColmapRigFrameSet &value) {
                return typed_view(
                    value.frame_sensor_ids,
                    {value.num_frame_data()});
            },
            reference_internal)
        .def_prop_ro(
            "quaternion_order",
            [](const ColmapRigFrameSet &) {
                return "wxyz";
            })
        .def_prop_ro(
            "sensor_pose_convention",
            [](const ColmapRigFrameSet &) {
                return "sensor_from_rig";
            })
        .def(
            "__repr__",
            [](const ColmapRigFrameSet &value) {
                return "<ColmapRigFrameSet rigs=" +
                       std::to_string(value.num_rigs()) +
                       " frames=" +
                       std::to_string(value.num_frames()) +
                       ">";
            });

    nb::class_<ColmapPosePriorSet>(
        module, "ColmapPosePriorSet")
        .def_ro("generalized", &ColmapPosePriorSet::generalized)
        .def_prop_ro(
            "num_pose_priors",
            [](const ColmapPosePriorSet &value) {
                return value.size();
            })
        .def_prop_ro(
            "prior_ids",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.prior_ids, {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "correlated_data_ids",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.corr_data_ids, {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "correlated_sensor_ids",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.corr_sensor_ids, {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "correlated_sensor_types",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.corr_sensor_types, {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "coordinate_systems",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.coordinate_systems, {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "position_present",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.position_present, {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "positions",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.positions, {value.size(), 3});
            },
            reference_internal)
        .def_prop_ro(
            "position_covariance_present",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.position_covariance_present,
                    {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "position_covariances",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.position_covariances,
                    {value.size(), 3, 3});
            },
            reference_internal)
        .def_prop_ro(
            "gravity_present",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.gravity_present, {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "gravities",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.gravities, {value.size(), 3});
            },
            reference_internal)
        .def_prop_ro(
            "rotation_present",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.rotation_present, {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "rotations",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.rotations, {value.size(), 4});
            },
            reference_internal)
        .def_prop_ro(
            "rotation_covariance_present",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.rotation_covariance_present,
                    {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "rotation_covariances",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.rotation_covariances,
                    {value.size(), 3, 3});
            },
            reference_internal)
        .def_prop_ro(
            "pose_covariance_present",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.pose_covariance_present,
                    {value.size()});
            },
            reference_internal)
        .def_prop_ro(
            "pose_covariances",
            [](const ColmapPosePriorSet &value) {
                return typed_view(
                    value.pose_covariances,
                    {value.size(), 6, 6});
            },
            reference_internal)
        .def_prop_ro(
            "rotation_order",
            [](const ColmapPosePriorSet &) {
                return "xyzw";
            })
        .def_prop_ro(
            "rotation_convention",
            [](const ColmapPosePriorSet &) {
                return "cam_from_world";
            })
        .def_prop_ro(
            "covariance_storage",
            [](const ColmapPosePriorSet &) {
                return "row_major";
            })
        .def_prop_ro(
            "rotation_covariance_variable_order",
            [](const ColmapPosePriorSet &) {
                return "rotation_tangent_xyz";
            })
        .def_prop_ro(
            "pose_covariance_variable_order",
            [](const ColmapPosePriorSet &) {
                return "rotation_tangent_xyz_translation_xyz";
            })
        .def_prop_ro(
            "rotation_covariance_unit",
            [](const ColmapPosePriorSet &) {
                return "radians_squared";
            })
        .def_prop_ro(
            "position_covariance_unit",
            [](const ColmapPosePriorSet &) {
                return "meters_squared";
            })
        .def_prop_ro(
            "pose_covariance_cross_unit",
            [](const ColmapPosePriorSet &) {
                return "radian_meters";
            })
        .def(
            "__len__",
            [](const ColmapPosePriorSet &value) {
                return value.size();
            })
        .def(
            "__repr__",
            [](const ColmapPosePriorSet &value) {
                return "<ColmapPosePriorSet priors=" +
                       std::to_string(value.size()) +
                       " generalized=" +
                       (value.generalized ? "True>" : "False>");
            });

    nb::class_<ColmapMarkerSet>(module, "ColmapMarkerSet")
        .def_prop_ro(
            "num_markers",
            [](const ColmapMarkerSet &value) {
                return value.num_markers();
            })
        .def_prop_ro(
            "num_projections",
            [](const ColmapMarkerSet &value) {
                return value.num_projections();
            })
        .def_prop_ro(
            "marker_ids",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.marker_ids, {value.num_markers()});
            },
            reference_internal)
        .def_ro("labels", &ColmapMarkerSet::labels)
        .def_prop_ro(
            "marker_types",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.types, {value.num_markers()});
            },
            reference_internal)
        .def_prop_ro(
            "world_position_present",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.world_position_present,
                    {value.num_markers()});
            },
            reference_internal)
        .def_prop_ro(
            "world_positions",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.world_positions,
                    {value.num_markers(), 3});
            },
            reference_internal)
        .def_prop_ro(
            "world_position_covariance_present",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.world_covariance_present,
                    {value.num_markers()});
            },
            reference_internal)
        .def_prop_ro(
            "world_position_covariances",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.world_covariances,
                    {value.num_markers(), 3, 3});
            },
            reference_internal)
        .def_prop_ro(
            "point3D_ids",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.point3d_ids, {value.num_markers()});
            },
            reference_internal)
        .def_prop_ro(
            "enabled",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.enabled, {value.num_markers()});
            },
            reference_internal)
        .def_prop_ro(
            "projection_marker_ids",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.projection_marker_ids,
                    {value.num_projections()});
            },
            reference_internal)
        .def_prop_ro(
            "projection_image_ids",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.projection_image_ids,
                    {value.num_projections()});
            },
            reference_internal)
        .def_prop_ro(
            "projection_xy",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.projection_xy,
                    {value.num_projections(), 2});
            },
            reference_internal)
        .def_prop_ro(
            "projection_sizes",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.projection_sizes,
                    {value.num_projections()});
            },
            reference_internal)
        .def_prop_ro(
            "projection_pinned",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.projection_pinned,
                    {value.num_projections()});
            },
            reference_internal)
        .def_prop_ro(
            "projection_point2D_indices",
            [](const ColmapMarkerSet &value) {
                return typed_view(
                    value.projection_point2d_indices,
                    {value.num_projections()});
            },
            reference_internal)
        .def_prop_ro(
            "projection_coordinate_origin",
            [](const ColmapMarkerSet &) {
                return "top_left";
            })
        .def_prop_ro(
            "projection_coordinate_unit",
            [](const ColmapMarkerSet &) {
                return "pixels";
            })
        .def_prop_ro(
            "projection_size_unit",
            [](const ColmapMarkerSet &) {
                return "pixels";
            })
        .def(
            "__repr__",
            [](const ColmapMarkerSet &value) {
                return "<ColmapMarkerSet markers=" +
                       std::to_string(value.num_markers()) +
                       " projections=" +
                       std::to_string(value.num_projections()) +
                       ">";
            });

    nb::class_<ColmapVideoMetadataSet>(
        module, "ColmapVideoMetadataSet")
        .def_prop_ro(
            "num_videos",
            [](const ColmapVideoMetadataSet &value) {
                return value.num_videos();
            })
        .def_prop_ro(
            "num_video_frames",
            [](const ColmapVideoMetadataSet &value) {
                return value.num_video_frames();
            })
        .def_prop_ro(
            "video_ids",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.video_ids, {value.num_videos()});
            },
            reference_internal)
        .def_ro("names", &ColmapVideoMetadataSet::names)
        .def_prop_ro(
            "source_path_present",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.source_path_present,
                    {value.num_videos()});
            },
            reference_internal)
        .def_ro(
            "source_paths",
            &ColmapVideoMetadataSet::source_paths)
        .def_prop_ro(
            "content_hash_present",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.content_hash_present,
                    {value.num_videos()});
            },
            reference_internal)
        .def_ro(
            "content_hashes",
            &ColmapVideoMetadataSet::content_hashes)
        .def_prop_ro(
            "widths",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.widths, {value.num_videos()});
            },
            reference_internal)
        .def_prop_ro(
            "heights",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.heights, {value.num_videos()});
            },
            reference_internal)
        .def_prop_ro(
            "num_frames",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.num_frames, {value.num_videos()});
            },
            reference_internal)
        .def_prop_ro(
            "fps",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.fps, {value.num_videos()});
            },
            reference_internal)
        .def_prop_ro(
            "duration_seconds",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.duration_seconds,
                    {value.num_videos()});
            },
            reference_internal)
        .def_prop_ro(
            "codec_name_present",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.codec_name_present,
                    {value.num_videos()});
            },
            reference_internal)
        .def_ro(
            "codec_names",
            &ColmapVideoMetadataSet::codec_names)
        .def_prop_ro(
            "sync_group_present",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.sync_group_present,
                    {value.num_videos()});
            },
            reference_internal)
        .def_ro(
            "sync_groups",
            &ColmapVideoMetadataSet::sync_groups)
        .def_prop_ro(
            "frame_video_ids",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.frame_video_ids,
                    {value.num_video_frames()});
            },
            reference_internal)
        .def_prop_ro(
            "frame_image_ids",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.frame_image_ids,
                    {value.num_video_frames()});
            },
            reference_internal)
        .def_prop_ro(
            "video_frame_indices",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.frame_ids,
                    {value.num_video_frames()});
            },
            reference_internal)
        .def_prop_ro(
            "pts_present",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.pts_present,
                    {value.num_video_frames()});
            },
            reference_internal)
        .def_prop_ro(
            "pts_seconds",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.pts_seconds,
                    {value.num_video_frames()});
            },
            reference_internal)
        .def_prop_ro(
            "time_id_present",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.time_id_present,
                    {value.num_video_frames()});
            },
            reference_internal)
        .def_prop_ro(
            "time_ids",
            [](const ColmapVideoMetadataSet &value) {
                return typed_view(
                    value.time_ids,
                    {value.num_video_frames()});
            },
            reference_internal)
        .def(
            "__repr__",
            [](const ColmapVideoMetadataSet &value) {
                return "<ColmapVideoMetadataSet videos=" +
                       std::to_string(value.num_videos()) +
                       " frames=" +
                       std::to_string(value.num_video_frames()) +
                       ">";
            });

    nb::class_<ColmapMaxxSchemaInfo>(
        module, "ColmapMaxxSchemaInfo")
        .def_ro(
            "schema_version",
            &ColmapMaxxSchemaInfo::schema_version)
        .def_ro(
            "minimum_reader_version",
            &ColmapMaxxSchemaInfo::minimum_reader_version)
        .def_ro(
            "producer_version",
            &ColmapMaxxSchemaInfo::producer_version)
        .def_ro(
            "producer_commit",
            &ColmapMaxxSchemaInfo::producer_commit);

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
        .def_prop_ro(
            "rig_frames",
            [](const ColmapDatabase &value)
                -> const ColmapRigFrameSet & {
                return value.rig_frames;
            },
            reference_internal)
        .def_prop_ro(
            "pose_priors",
            [](const ColmapDatabase &value)
                -> const ColmapPosePriorSet & {
                return value.pose_priors;
            },
            reference_internal)
        .def_prop_ro(
            "markers",
            [](const ColmapDatabase &value)
                -> const ColmapMarkerSet & {
                return value.markers;
            },
            reference_internal)
        .def_prop_ro(
            "video_metadata",
            [](const ColmapDatabase &value)
                -> const ColmapVideoMetadataSet & {
                return value.video_metadata;
            },
            reference_internal)
        .def_prop_ro(
            "maxx_schema_info",
            [](const ColmapDatabase &value) -> nb::object {
                if (!value.maxx_schema_info.present)
                    return nb::none();
                return nb::cast(value.maxx_schema_info);
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
