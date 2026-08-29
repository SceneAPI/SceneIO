// records/camera_rig.cpp -- CameraRig validation and nanobind surface.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <optional>
#include <string>
#include <type_traits>
#include <unordered_set>
#include <utility>

#include "records/camera_rig.hpp"

using namespace nb::literals;

namespace {

template <typename T>
nb::ndarray<nb::numpy, T> rig_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static T sentinel{};
    T *data =
        values.empty() ? &sentinel : const_cast<T *>(values.data());
    return nb::ndarray<nb::numpy, T>(
        data, shape.size(), shape.data());
}

using u8_array =
    nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;
using u32_array =
    nb::ndarray<const uint32_t, nb::c_contig, nb::device::cpu>;
using u64_array =
    nb::ndarray<const uint64_t, nb::c_contig, nb::device::cpu>;
using f64_array =
    nb::ndarray<const double, nb::c_contig, nb::device::cpu>;

template <typename Array>
void require_shape(
    const Array &array, size_t rows, size_t columns,
    const char *name) {
    if (array.ndim() != 2 || array.shape(0) != rows ||
        array.shape(1) != columns)
        throw std::invalid_argument(
            std::string("camera_rig: ") + name + " must be (N," +
            std::to_string(columns) + ")");
}

template <typename T>
void copy_optional_matrix(
    size_t count, size_t rows, size_t columns,
    const std::optional<f64_array> &source,
    const std::optional<u8_array> &source_mask,
    std::vector<double> &destination,
    std::vector<uint8_t> &mask,
    const char *name) {
    static_assert(std::is_same_v<T, double>);
    const size_t extent = rows * columns;
    destination.assign(count * extent, 0.0);
    mask.assign(count, 0);
    if (!source) {
        if (source_mask)
            throw std::invalid_argument(
                std::string("camera_rig: ") + name +
                " mask requires its matrix");
        return;
    }
    if (source->ndim() != 3 || source->shape(0) != count ||
        source->shape(1) != rows ||
        source->shape(2) != columns)
        throw std::invalid_argument(
            std::string("camera_rig: ") + name + " must be (N," +
            std::to_string(rows) + "," +
            std::to_string(columns) + ")");
    if (count != 0)
        destination.assign(
            source->data(), source->data() + count * extent);
    if (source_mask) {
        if (source_mask->ndim() != 1 ||
            source_mask->shape(0) != count)
            throw std::invalid_argument(
                std::string("camera_rig: ") + name +
                " mask must be (N,) uint8");
        if (count != 0)
            mask.assign(
                source_mask->data(), source_mask->data() + count);
    } else {
        std::fill(mask.begin(), mask.end(), 1);
    }
}

void copy_optional_rows(
    size_t count, size_t columns,
    const std::optional<u32_array> &source,
    std::vector<uint32_t> &destination,
    const char *name) {
    destination.assign(count * columns, 0);
    if (!source) return;
    require_shape(*source, count, columns, name);
    if (count != 0)
        destination.assign(
            source->data(), source->data() + count * columns);
}

void copy_optional_flags(
    size_t count, const std::optional<u8_array> &source,
    std::vector<uint8_t> &destination, const char *name,
    uint8_t default_value = 0) {
    destination.assign(count, default_value);
    if (!source) return;
    if (source->ndim() != 1 || source->shape(0) != count)
        throw std::invalid_argument(
            std::string("camera_rig: ") + name +
            " must be (N,) uint8");
    if (count != 0)
        destination.assign(source->data(), source->data() + count);
}

CameraRig make_camera_rig(
    u32_array camera_ids, u64_array resolutions,
    std::vector<std::string> projection_models,
    u64_array intrinsic_offsets, f64_array intrinsics,
    std::vector<std::string> distortion_models,
    u64_array distortion_offsets, f64_array distortion_coefficients,
    f64_array quaternions, f64_array translations,
    std::optional<u8_array> has_extrinsics,
    std::optional<std::vector<std::string>> names,
    std::optional<f64_array> camera_matrices,
    std::optional<u8_array> has_camera_matrix,
    std::optional<f64_array> rectification_matrices,
    std::optional<u8_array> has_rectification,
    std::optional<f64_array> projection_matrices,
    std::optional<u8_array> has_projection_matrix,
    std::optional<u32_array> binning,
    std::optional<u32_array> roi,
    std::optional<u8_array> roi_do_rectify,
    std::optional<u8_array> has_operational,
    std::optional<std::vector<std::string>> topics,
    std::optional<f64_array> time_offsets,
    std::optional<u8_array> has_time_offset,
    const std::string &quaternion_order,
    const std::string &quaternion_sign,
    const std::string &transform_convention,
    const std::string &axis_frame,
    const std::string &reference_frame,
    double scale_to_meters) {
    if (camera_ids.ndim() != 1)
        throw std::invalid_argument(
            "camera_rig: camera_ids must be (N,) uint32");
    const size_t count = camera_ids.shape(0);
    if (count > std::numeric_limits<size_t>::max() / 12)
        throw std::invalid_argument(
            "camera_rig: camera count overflows field extents");
    require_shape(resolutions, count, 2, "resolutions");
    require_shape(quaternions, count, 4, "quaternions");
    require_shape(translations, count, 3, "translations");
    if (intrinsic_offsets.ndim() != 1 ||
        intrinsic_offsets.shape(0) != count + 1)
        throw std::invalid_argument(
            "camera_rig: intrinsic_offsets must be (N+1,) uint64");
    if (intrinsics.ndim() != 1)
        throw std::invalid_argument(
            "camera_rig: intrinsics must be one-dimensional float64");
    if (distortion_offsets.ndim() != 1 ||
        distortion_offsets.shape(0) != count + 1)
        throw std::invalid_argument(
            "camera_rig: distortion_offsets must be (N+1,) uint64");
    if (distortion_coefficients.ndim() != 1)
        throw std::invalid_argument(
            "camera_rig: distortion_coefficients must be "
            "one-dimensional float64");
    if (projection_models.size() != count ||
        distortion_models.size() != count)
        throw std::invalid_argument(
            "camera_rig: model-name counts must equal N");

    CameraRig rig;
    rig.n = count;
    if (count != 0) {
        rig.camera_ids.assign(
            camera_ids.data(), camera_ids.data() + count);
        rig.resolutions.assign(
            resolutions.data(), resolutions.data() + count * 2);
    }
    rig.projection_models = std::move(projection_models);
    rig.intrinsic_offsets.assign(
        intrinsic_offsets.data(), intrinsic_offsets.data() + count + 1);
    if (intrinsics.shape(0) != 0)
        rig.intrinsics.assign(
            intrinsics.data(),
            intrinsics.data() + intrinsics.shape(0));
    rig.distortion_models = std::move(distortion_models);
    rig.distortion_offsets.assign(
        distortion_offsets.data(),
        distortion_offsets.data() + count + 1);
    if (distortion_coefficients.shape(0) != 0)
        rig.distortion_coefficients.assign(
            distortion_coefficients.data(),
            distortion_coefficients.data() +
                distortion_coefficients.shape(0));
    if (count != 0) {
        rig.quaternions.assign(
            quaternions.data(), quaternions.data() + count * 4);
        rig.translations.assign(
            translations.data(), translations.data() + count * 3);
    }
    copy_optional_flags(
        count, has_extrinsics, rig.has_extrinsics,
        "has_extrinsics", 1);

    if (names) {
        if (names->size() != count)
            throw std::invalid_argument(
                "camera_rig: len(names) must equal N");
        rig.names = std::move(*names);
    } else {
        rig.names.resize(count);
        for (size_t index = 0; index < count; ++index)
            rig.names[index] = "camera" + std::to_string(index);
    }

    copy_optional_matrix<double>(
        count, 3, 3, camera_matrices, has_camera_matrix,
        rig.camera_matrices, rig.has_camera_matrix,
        "camera_matrices");
    copy_optional_matrix<double>(
        count, 3, 3, rectification_matrices, has_rectification,
        rig.rectification_matrices, rig.has_rectification,
        "rectification_matrices");
    copy_optional_matrix<double>(
        count, 3, 4, projection_matrices, has_projection_matrix,
        rig.projection_matrices, rig.has_projection_matrix,
        "projection_matrices");
    copy_optional_rows(
        count, 2, binning, rig.binning, "binning");
    copy_optional_rows(count, 4, roi, rig.roi, "roi");
    copy_optional_flags(
        count, roi_do_rectify, rig.roi_do_rectify,
        "roi_do_rectify");
    copy_optional_flags(
        count, has_operational, rig.has_operational,
        "has_operational");

    if (topics) {
        if (topics->size() != count)
            throw std::invalid_argument(
                "camera_rig: len(topics) must equal N");
        rig.topics = std::move(*topics);
    } else {
        rig.topics.resize(count);
    }
    rig.time_offsets.assign(count, 0.0);
    rig.has_time_offset.assign(count, 0);
    if (time_offsets) {
        if (time_offsets->ndim() != 1 ||
            time_offsets->shape(0) != count)
            throw std::invalid_argument(
                "camera_rig: time_offsets must be (N,) float64");
        if (count != 0)
            rig.time_offsets.assign(
                time_offsets->data(), time_offsets->data() + count);
        if (has_time_offset) {
            if (has_time_offset->ndim() != 1 ||
                has_time_offset->shape(0) != count)
                throw std::invalid_argument(
                    "camera_rig: has_time_offset must be (N,) uint8");
            if (count != 0)
                rig.has_time_offset.assign(
                    has_time_offset->data(),
                    has_time_offset->data() + count);
        } else {
            std::fill(
                rig.has_time_offset.begin(),
                rig.has_time_offset.end(), 1);
        }
    } else if (has_time_offset) {
        throw std::invalid_argument(
            "camera_rig: has_time_offset requires time_offsets");
    }

    rig.quaternion_order = quaternion_order;
    rig.quaternion_sign = quaternion_sign;
    rig.transform_convention = transform_convention;
    rig.axis_frame = axis_frame;
    rig.reference_frame = reference_frame;
    rig.scale_to_meters = scale_to_meters;
    validate_camera_rig(rig);
    return rig;
}

}  // namespace

void validate_camera_rig(const CameraRig &rig, const char *context) {
    const size_t count = rig.n;
    const std::string prefix = std::string(context) + ": ";
    if (count > std::numeric_limits<size_t>::max() / 12 ||
        rig.camera_ids.size() != count ||
        rig.resolutions.size() != count * 2 ||
        rig.names.size() != count ||
        rig.projection_models.size() != count ||
        rig.intrinsic_offsets.size() != count + 1 ||
        rig.distortion_models.size() != count ||
        rig.distortion_offsets.size() != count + 1 ||
        rig.quaternions.size() != count * 4 ||
        rig.translations.size() != count * 3 ||
        rig.has_extrinsics.size() != count ||
        rig.camera_matrices.size() != count * 9 ||
        rig.has_camera_matrix.size() != count ||
        rig.rectification_matrices.size() != count * 9 ||
        rig.has_rectification.size() != count ||
        rig.projection_matrices.size() != count * 12 ||
        rig.has_projection_matrix.size() != count ||
        rig.binning.size() != count * 2 ||
        rig.roi.size() != count * 4 ||
        rig.roi_do_rectify.size() != count ||
        rig.has_operational.size() != count ||
        rig.topics.size() != count ||
        rig.time_offsets.size() != count ||
        rig.has_time_offset.size() != count)
        throw std::invalid_argument(
            prefix + "inconsistent CameraRig field lengths");
    if (rig.intrinsic_offsets.front() != 0 ||
        rig.intrinsic_offsets.back() != rig.intrinsics.size() ||
        rig.distortion_offsets.front() != 0 ||
        rig.distortion_offsets.back() !=
            rig.distortion_coefficients.size())
        throw std::invalid_argument(
            prefix + "ragged offsets do not match coefficient arrays");
    for (size_t index = 0; index < count; ++index) {
        if (rig.intrinsic_offsets[index] >
                rig.intrinsic_offsets[index + 1] ||
            rig.distortion_offsets[index] >
                rig.distortion_offsets[index + 1])
            throw std::invalid_argument(
                prefix + "ragged offsets must be nondecreasing");
    }
    if (!rig_valid_quaternion_order(rig.quaternion_order) ||
        !rig_valid_quaternion_sign(rig.quaternion_sign) ||
        !rig_valid_transform_convention(rig.transform_convention) ||
        !rig_valid_axis_frame(rig.axis_frame) ||
        !rig_valid_reference_frame(rig.reference_frame))
        throw std::invalid_argument(
            prefix + "invalid convention metadata");
    if (!std::isfinite(rig.scale_to_meters) ||
        rig.scale_to_meters <= 0.0)
        throw std::invalid_argument(
            prefix + "scale_to_meters must be finite and positive");

    std::unordered_set<uint32_t> ids;
    std::unordered_set<std::string> names;
    auto valid_text = [&](const std::string &value,
                          const char *name) {
        for (unsigned char character : value)
            if (character < 0x20)
                throw std::invalid_argument(
                    prefix + name +
                    " strings cannot contain control characters");
    };
    auto finite_values = [&](const std::vector<double> &values,
                             const char *name) {
        for (double value : values)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    prefix + name + " values must be finite");
    };
    finite_values(rig.intrinsics, "intrinsic");
    finite_values(
        rig.distortion_coefficients, "distortion coefficient");
    finite_values(rig.camera_matrices, "camera matrix");
    finite_values(
        rig.rectification_matrices, "rectification matrix");
    finite_values(rig.projection_matrices, "projection matrix");
    finite_values(rig.time_offsets, "time offset");

    for (size_t index = 0; index < count; ++index) {
        if (!ids.insert(rig.camera_ids[index]).second)
            throw std::invalid_argument(
                prefix + "camera ids must be unique");
        if (rig.names[index].empty() ||
            !names.insert(rig.names[index]).second)
            throw std::invalid_argument(
                prefix + "camera names must be nonempty and unique");
        valid_text(rig.names[index], "camera name");
        if (rig.projection_models[index].empty())
            throw std::invalid_argument(
                prefix + "projection model names must be nonempty");
        valid_text(
            rig.projection_models[index], "projection model");
        valid_text(
            rig.distortion_models[index], "distortion model");
        valid_text(rig.topics[index], "topic");
        const uint64_t width = rig.resolutions[index * 2];
        const uint64_t height = rig.resolutions[index * 2 + 1];
        if (width == 0 || height == 0)
            throw std::invalid_argument(
                prefix + "camera resolutions must be positive");
        const std::array<const std::vector<uint8_t> *, 7> flags = {
            &rig.has_extrinsics, &rig.has_camera_matrix,
            &rig.has_rectification, &rig.has_projection_matrix,
            &rig.roi_do_rectify, &rig.has_operational,
            &rig.has_time_offset};
        for (const auto *field : flags)
            if ((*field)[index] > 1)
                throw std::invalid_argument(
                    prefix + "presence flags must be zero or one");

        const double *quaternion =
            rig.quaternions.data() + index * 4;
        const double *translation =
            rig.translations.data() + index * 3;
        for (size_t component = 0; component < 4; ++component)
            if (!std::isfinite(quaternion[component]))
                throw std::invalid_argument(
                    prefix + "quaternions must be finite");
        for (size_t component = 0; component < 3; ++component)
            if (!std::isfinite(translation[component]))
                throw std::invalid_argument(
                    prefix + "translations must be finite");
        if (rig.has_extrinsics[index]) {
            if (quaternion[0] == 0.0 && quaternion[1] == 0.0 &&
                quaternion[2] == 0.0 && quaternion[3] == 0.0)
                throw std::invalid_argument(
                    prefix + "present quaternions must be nonzero");
            const size_t w_index =
                rig.quaternion_order == "wxyz" ? 0 : 3;
            if (rig.quaternion_sign == "canonical_positive_w" &&
                quaternion[w_index] < 0.0)
                throw std::invalid_argument(
                    prefix + "canonical_positive_w requires "
                             "nonnegative W");
        } else {
            const size_t w_index =
                rig.quaternion_order == "wxyz" ? 0 : 3;
            for (size_t component = 0; component < 4; ++component)
                if (quaternion[component] !=
                    (component == w_index ? 1.0 : 0.0))
                    throw std::invalid_argument(
                        prefix + "absent extrinsics must use "
                                 "identity/zero placeholders");
            if (translation[0] != 0.0 || translation[1] != 0.0 ||
                translation[2] != 0.0)
                throw std::invalid_argument(
                    prefix + "absent extrinsics must use "
                             "identity/zero placeholders");
        }
        if (!rig.has_time_offset[index] &&
            rig.time_offsets[index] != 0.0)
            throw std::invalid_argument(
                prefix + "absent time offsets must use zero placeholders");
        if (!rig.has_operational[index]) {
            const size_t bin = index * 2;
            const size_t region = index * 4;
            if (rig.binning[bin] != 0 || rig.binning[bin + 1] != 0 ||
                rig.roi[region] != 0 || rig.roi[region + 1] != 0 ||
                rig.roi[region + 2] != 0 ||
                rig.roi[region + 3] != 0 ||
                rig.roi_do_rectify[index] != 0)
                throw std::invalid_argument(
                    prefix + "absent operational metadata must use "
                             "zero placeholders");
        } else {
            const size_t region = index * 4;
            const uint64_t x = rig.roi[region];
            const uint64_t y = rig.roi[region + 1];
            const uint64_t roi_width = rig.roi[region + 2];
            const uint64_t roi_height = rig.roi[region + 3];
            if ((roi_width != 0 &&
                 (x > width || roi_width > width - x)) ||
                (roi_height != 0 &&
                 (y > height || roi_height > height - y)))
                throw std::invalid_argument(
                    prefix + "ROI exceeds the camera resolution");
        }
        const std::array<
            std::pair<const std::vector<uint8_t> *,
                      std::pair<const std::vector<double> *, size_t>>,
            3>
            matrices = {{
                {&rig.has_camera_matrix, {&rig.camera_matrices, 9}},
                {&rig.has_rectification,
                 {&rig.rectification_matrices, 9}},
                {&rig.has_projection_matrix,
                 {&rig.projection_matrices, 12}},
            }};
        for (const auto &[present, matrix] : matrices) {
            if ((*present)[index]) continue;
            const auto &[values, extent] = matrix;
            const size_t offset = index * extent;
            for (size_t component = 0; component < extent;
                 ++component)
                if ((*values)[offset + component] != 0.0)
                    throw std::invalid_argument(
                        prefix + "absent matrices must use zero "
                                 "placeholders");
        }
    }
}

void register_camera_rig(nb::module_ &module) {
    const auto reference_internal = nb::rv_policy::reference_internal;
    nb::class_<CameraRig>(module, "CameraRig")
        .def_prop_ro(
            "num_cameras",
            [](const CameraRig &value) { return value.num_cameras(); })
        .def_prop_ro(
            "camera_ids",
            [](const CameraRig &value) {
                return rig_view(value.camera_ids, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "resolutions",
            [](const CameraRig &value) {
                return rig_view(value.resolutions, {value.n, 2});
            },
            reference_internal)
        .def_prop_ro("names", [](const CameraRig &value) {
            return value.names;
        })
        .def_prop_ro(
            "projection_models",
            [](const CameraRig &value) {
                return value.projection_models;
            })
        .def_prop_ro(
            "intrinsic_offsets",
            [](const CameraRig &value) {
                return rig_view(
                    value.intrinsic_offsets, {value.n + 1});
            },
            reference_internal)
        .def_prop_ro(
            "intrinsics",
            [](const CameraRig &value) {
                return rig_view(
                    value.intrinsics, {value.intrinsics.size()});
            },
            reference_internal)
        .def_prop_ro(
            "distortion_models",
            [](const CameraRig &value) {
                return value.distortion_models;
            })
        .def_prop_ro(
            "distortion_offsets",
            [](const CameraRig &value) {
                return rig_view(
                    value.distortion_offsets, {value.n + 1});
            },
            reference_internal)
        .def_prop_ro(
            "distortion_coefficients",
            [](const CameraRig &value) {
                return rig_view(
                    value.distortion_coefficients,
                    {value.distortion_coefficients.size()});
            },
            reference_internal)
        .def_prop_ro(
            "quaternions",
            [](const CameraRig &value) {
                return rig_view(value.quaternions, {value.n, 4});
            },
            reference_internal)
        .def_prop_ro(
            "translations",
            [](const CameraRig &value) {
                return rig_view(value.translations, {value.n, 3});
            },
            reference_internal)
        .def_prop_ro(
            "has_extrinsics",
            [](const CameraRig &value) {
                return rig_view(value.has_extrinsics, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "camera_matrices",
            [](const CameraRig &value) {
                return rig_view(
                    value.camera_matrices, {value.n, 3, 3});
            },
            reference_internal)
        .def_prop_ro(
            "has_camera_matrix",
            [](const CameraRig &value) {
                return rig_view(value.has_camera_matrix, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "rectification_matrices",
            [](const CameraRig &value) {
                return rig_view(
                    value.rectification_matrices, {value.n, 3, 3});
            },
            reference_internal)
        .def_prop_ro(
            "has_rectification",
            [](const CameraRig &value) {
                return rig_view(value.has_rectification, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "projection_matrices",
            [](const CameraRig &value) {
                return rig_view(
                    value.projection_matrices, {value.n, 3, 4});
            },
            reference_internal)
        .def_prop_ro(
            "has_projection_matrix",
            [](const CameraRig &value) {
                return rig_view(
                    value.has_projection_matrix, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "binning",
            [](const CameraRig &value) {
                return rig_view(value.binning, {value.n, 2});
            },
            reference_internal)
        .def_prop_ro(
            "roi",
            [](const CameraRig &value) {
                return rig_view(value.roi, {value.n, 4});
            },
            reference_internal)
        .def_prop_ro(
            "roi_do_rectify",
            [](const CameraRig &value) {
                return rig_view(value.roi_do_rectify, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "has_operational",
            [](const CameraRig &value) {
                return rig_view(value.has_operational, {value.n});
            },
            reference_internal)
        .def_prop_ro("topics", [](const CameraRig &value) {
            return value.topics;
        })
        .def_prop_ro(
            "time_offsets",
            [](const CameraRig &value) {
                return rig_view(value.time_offsets, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "has_time_offset",
            [](const CameraRig &value) {
                return rig_view(value.has_time_offset, {value.n});
            },
            reference_internal)
        .def_ro("quaternion_order", &CameraRig::quaternion_order)
        .def_ro("quaternion_sign", &CameraRig::quaternion_sign)
        .def_ro(
            "transform_convention",
            &CameraRig::transform_convention)
        .def_ro("axis_frame", &CameraRig::axis_frame)
        .def_ro("reference_frame", &CameraRig::reference_frame)
        .def_ro("scale_to_meters", &CameraRig::scale_to_meters)
        .def_prop_ro(
            "time_offset_convention",
            [](const CameraRig &) {
                return "reference_time = camera_time + "
                       "time_offset_seconds";
            })
        .def(
            "__repr__",
            [](const CameraRig &value) {
                return "<CameraRig cameras=" +
                       std::to_string(value.n) + " " +
                       value.reference_frame + "->camera/" +
                       value.axis_frame + ">";
            });

    module.def(
        "camera_rig", &make_camera_rig,
        "camera_ids"_a, "resolutions"_a,
        "projection_models"_a, "intrinsic_offsets"_a,
        "intrinsics"_a, "distortion_models"_a,
        "distortion_offsets"_a, "distortion_coefficients"_a,
        "quaternions"_a, "translations"_a,
        "has_extrinsics"_a = nb::none(),
        "names"_a = nb::none(),
        "camera_matrices"_a = nb::none(),
        "has_camera_matrix"_a = nb::none(),
        "rectification_matrices"_a = nb::none(),
        "has_rectification"_a = nb::none(),
        "projection_matrices"_a = nb::none(),
        "has_projection_matrix"_a = nb::none(),
        "binning"_a = nb::none(), "roi"_a = nb::none(),
        "roi_do_rectify"_a = nb::none(),
        "has_operational"_a = nb::none(),
        "topics"_a = nb::none(), "time_offsets"_a = nb::none(),
        "has_time_offset"_a = nb::none(),
        "quaternion_order"_a = "wxyz",
        "quaternion_sign"_a = "preserved",
        "transform_convention"_a = "reference_to_camera",
        "axis_frame"_a = "opencv",
        "reference_frame"_a = "unknown",
        "scale_to_meters"_a = 1.0,
        "Build a lossless multi-camera calibration record with ragged "
        "intrinsics/distortion, exact K/R/P matrices, optional extrinsics, "
        "ROS operational fields, and Kalibr topic/time metadata.");
}
