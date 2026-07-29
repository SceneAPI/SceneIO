// records/dense_mvs.cpp -- nanobind records for COLMAP dense-MVS payloads.
#include <nanobind/stl/string.h>

#include <limits>
#include <stdexcept>

#include "records/dense_mvs.hpp"

using namespace nb::literals;

namespace {

using anyarr = nb::ndarray<nb::ro, nb::c_contig, nb::device::cpu>;

size_t checked_pixels(size_t height, size_t width, const char *what) {
    if (height == 0 || width == 0)
        throw std::invalid_argument(std::string(what) +
                                    ": dimensions must be positive");
    if (height > kColmapMvsDimensionCap ||
        width > kColmapMvsDimensionCap ||
        height > kColmapMvsEntryCap / width)
        throw std::invalid_argument(std::string(what) +
                                    ": dimensions exceed the supported range");
    return height * width;
}

NormalMap make_normal_map(anyarr normals) {
    if (normals.ndim() != 3 || normals.shape(2) != 3)
        throw std::invalid_argument(
            "normal_map: normals must be (H,W,3) float32 with H,W >= 1");
    if (normals.dtype() != nb::dtype<float>())
        throw std::invalid_argument("normal_map: normals must be float32");
    NormalMap result;
    result.height = normals.shape(0);
    result.width = normals.shape(1);
    const size_t pixels =
        checked_pixels(result.height, result.width, "normal_map");
    if (pixels > std::numeric_limits<size_t>::max() / 3)
        throw std::invalid_argument(
            "normal_map: value count overflows address space");
    const auto *data = static_cast<const float *>(normals.data());
    result.normals.assign(data, data + pixels * 3);
    return result;
}

void require_vector(anyarr array, nb::dlpack::dtype dtype, const char *what) {
    if (array.ndim() != 1 || array.dtype() != dtype)
        throw std::invalid_argument(std::string(what) +
                                    " must be a one-dimensional array with "
                                    "the documented unsigned dtype");
}

void validate_csr(const std::vector<uint64_t> &offsets,
                  size_t row_count, size_t value_count, const char *what) {
    if (offsets.size() != row_count + 1 || offsets.front() != 0 ||
        offsets.back() != value_count)
        throw std::invalid_argument(std::string(what) +
                                    ": offsets must begin at zero, contain "
                                    "one terminator per row, and end at the "
                                    "image-index count");
    for (size_t index = 1; index < offsets.size(); ++index) {
        if (offsets[index] < offsets[index - 1])
            throw std::invalid_argument(std::string(what) +
                                        ": offsets must be nondecreasing");
        if (offsets[index] - offsets[index - 1] >
            static_cast<uint64_t>(std::numeric_limits<int32_t>::max()))
            throw std::invalid_argument(std::string(what) +
                                        ": one row exceeds COLMAP's int32 "
                                        "count domain");
    }
}

ConsistencyGraph make_consistency_graph(size_t height, size_t width,
                                        anyarr rows, anyarr columns,
                                        anyarr offsets, anyarr image_indices) {
    checked_pixels(height, width, "consistency_graph");
    require_vector(rows, nb::dtype<uint32_t>(), "consistency_graph: rows");
    require_vector(columns, nb::dtype<uint32_t>(),
                   "consistency_graph: columns");
    require_vector(offsets, nb::dtype<uint64_t>(),
                   "consistency_graph: offsets");
    require_vector(image_indices, nb::dtype<uint32_t>(),
                   "consistency_graph: image_indices");
    if (rows.shape(0) != columns.shape(0))
        throw std::invalid_argument(
            "consistency_graph: rows and columns must have equal length");

    ConsistencyGraph result;
    result.height = height;
    result.width = width;
    const size_t entries = rows.shape(0);
    const size_t values = image_indices.shape(0);
    if (entries > kColmapMvsEntryCap ||
        values > kColmapMvsListValueCap)
        throw std::invalid_argument(
            "consistency_graph: entry or image-index count exceeds the "
            "supported range");
    const auto *row_data = static_cast<const uint32_t *>(rows.data());
    const auto *column_data =
        static_cast<const uint32_t *>(columns.data());
    const auto *offset_data =
        static_cast<const uint64_t *>(offsets.data());
    const auto *image_data =
        static_cast<const uint32_t *>(image_indices.data());
    result.rows.assign(row_data, row_data + entries);
    result.columns.assign(column_data, column_data + entries);
    result.offsets.assign(offset_data, offset_data + offsets.shape(0));
    result.image_indices.assign(image_data, image_data + values);
    validate_csr(result.offsets, entries, values, "consistency_graph");

    for (size_t index = 0; index < entries; ++index) {
        if (result.rows[index] >= height || result.columns[index] >= width)
            throw std::invalid_argument(
                "consistency_graph: pixel coordinate is outside the raster");
        if (result.rows[index] >
                static_cast<uint64_t>(std::numeric_limits<int32_t>::max()) ||
            result.columns[index] >
                static_cast<uint64_t>(std::numeric_limits<int32_t>::max()))
            throw std::invalid_argument(
                "consistency_graph: pixel coordinate exceeds COLMAP's int32 "
                "domain");
    }
    for (uint32_t value : result.image_indices) {
        if (value > static_cast<uint32_t>(
                        std::numeric_limits<int32_t>::max()))
            throw std::invalid_argument(
                "consistency_graph: image index exceeds COLMAP's non-negative "
                "int32 domain");
    }
    return result;
}

PointVisibility make_point_visibility(anyarr offsets, anyarr image_indices) {
    require_vector(offsets, nb::dtype<uint64_t>(),
                   "point_visibility: offsets");
    require_vector(image_indices, nb::dtype<uint32_t>(),
                   "point_visibility: image_indices");
    if (offsets.shape(0) == 0)
        throw std::invalid_argument(
            "point_visibility: offsets must contain the initial zero");
    if (offsets.shape(0) - 1 > kColmapMvsEntryCap ||
        image_indices.shape(0) > kColmapMvsListValueCap)
        throw std::invalid_argument(
            "point_visibility: point or image-index count exceeds the "
            "supported range");
    PointVisibility result;
    const auto *offset_data =
        static_cast<const uint64_t *>(offsets.data());
    const auto *image_data =
        static_cast<const uint32_t *>(image_indices.data());
    result.offsets.assign(offset_data, offset_data + offsets.shape(0));
    result.image_indices.assign(
        image_data, image_data + image_indices.shape(0));
    validate_csr(result.offsets, result.point_count(),
                 result.image_indices.size(), "point_visibility");
    for (uint32_t value : result.image_indices) {
        if (value > static_cast<uint32_t>(
                        std::numeric_limits<int32_t>::max()))
            throw std::invalid_argument(
                "point_visibility: image index exceeds COLMAP's non-negative "
                "int32 domain");
    }
    return result;
}

}  // namespace

void register_dense_mvs_records(nb::module_ &m) {
    nb::class_<NormalMap>(m, "NormalMap")
        .def_prop_ro("height",
                     [](const NormalMap &value) { return value.height; })
        .def_prop_ro("width",
                     [](const NormalMap &value) { return value.width; })
        .def_prop_ro("normals", [](nb::handle_t<NormalMap> self) {
            const NormalMap &value = nb::cast<const NormalMap &>(self);
            return sio::view(self, value.normals.data(),
                             {value.height, value.width, 3});
        })
        .def_prop_ro("coordinate_system",
                     [](const NormalMap &) {
                         return "opencv_camera";
                     })
        .def_prop_ro("component_order",
                     [](const NormalMap &) { return "xyz"; })
        .def_prop_ro("row_order",
                     [](const NormalMap &) { return "top_to_bottom"; })
        .def_prop_ro("invalid_policy",
                     [](const NormalMap &) { return "zero_vector"; })
        .def_prop_ro("orientation",
                     [](const NormalMap &) {
                         return "opposes_camera_to_surface_ray";
                     })
        .def("__repr__", [](const NormalMap &value) {
            return "<NormalMap " + std::to_string(value.height) + "x" +
                   std::to_string(value.width) +
                   " opencv_camera xyz invalid=zero_vector>";
        });

    nb::class_<ConsistencyGraph>(m, "ConsistencyGraph")
        .def_prop_ro("height", [](const ConsistencyGraph &value) {
            return value.height;
        })
        .def_prop_ro("width", [](const ConsistencyGraph &value) {
            return value.width;
        })
        .def_prop_ro("num_entries", [](const ConsistencyGraph &value) {
            return value.entry_count();
        })
        .def_prop_ro("num_image_indices",
                     [](const ConsistencyGraph &value) {
                         return value.image_indices.size();
                     })
        .def_prop_ro("rows", [](nb::handle_t<ConsistencyGraph> self) {
            const auto &value = nb::cast<const ConsistencyGraph &>(self);
            return sio::view(self, value.rows.data(), {value.rows.size()});
        })
        .def_prop_ro("columns", [](nb::handle_t<ConsistencyGraph> self) {
            const auto &value = nb::cast<const ConsistencyGraph &>(self);
            return sio::view(self, value.columns.data(),
                             {value.columns.size()});
        })
        .def_prop_ro("offsets", [](nb::handle_t<ConsistencyGraph> self) {
            const auto &value = nb::cast<const ConsistencyGraph &>(self);
            return sio::view(self, value.offsets.data(),
                             {value.offsets.size()});
        })
        .def_prop_ro("image_indices",
                     [](nb::handle_t<ConsistencyGraph> self) {
                         const auto &value =
                             nb::cast<const ConsistencyGraph &>(self);
                         return sio::view(self, value.image_indices.data(),
                                          {value.image_indices.size()});
                     })
        .def_prop_ro("index_domain",
                     [](const ConsistencyGraph &) {
                         return "mvs_sequential_image_index";
                     })
        .def("__repr__", [](const ConsistencyGraph &value) {
            return "<ConsistencyGraph " + std::to_string(value.height) +
                   "x" + std::to_string(value.width) + " entries=" +
                   std::to_string(value.entry_count()) + " links=" +
                   std::to_string(value.image_indices.size()) + ">";
        });

    nb::class_<PointVisibility>(m, "PointVisibility")
        .def_prop_ro("num_points", [](const PointVisibility &value) {
            return value.point_count();
        })
        .def_prop_ro("num_image_indices",
                     [](const PointVisibility &value) {
                         return value.image_indices.size();
                     })
        .def_prop_ro("offsets", [](nb::handle_t<PointVisibility> self) {
            const auto &value = nb::cast<const PointVisibility &>(self);
            return sio::view(self, value.offsets.data(),
                             {value.offsets.size()});
        })
        .def_prop_ro("image_indices",
                     [](nb::handle_t<PointVisibility> self) {
                         const auto &value =
                             nb::cast<const PointVisibility &>(self);
                         return sio::view(self, value.image_indices.data(),
                                          {value.image_indices.size()});
                     })
        .def_prop_ro("index_domain",
                     [](const PointVisibility &) {
                         return "mvs_sequential_image_index";
                     })
        .def("__repr__", [](const PointVisibility &value) {
            return "<PointVisibility points=" +
                   std::to_string(value.point_count()) + " links=" +
                   std::to_string(value.image_indices.size()) + ">";
        });

    m.def("normal_map", &make_normal_map, "normals"_a,
          "Build an owning NormalMap from an exact (H,W,3) float32 array.");
    m.def("consistency_graph", &make_consistency_graph, "height"_a,
          "width"_a, "rows"_a, "columns"_a, "offsets"_a,
          "image_indices"_a,
          "Build an ordered pixel-to-MVS-image consistency graph.");
    m.def("point_visibility", &make_point_visibility, "offsets"_a,
          "image_indices"_a,
          "Build fused-point visibility CSR using MVS sequential image "
          "indices.");
}
