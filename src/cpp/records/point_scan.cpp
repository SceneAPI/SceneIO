// Stored-row PointScan and ordered ScanSet records.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>

#include "io/common.hpp"
#include "records/point_scan.hpp"

using namespace nb::literals;

namespace {

using i64_array =
    nb::ndarray<const int64_t, nb::c_contig, nb::device::cpu>;
using u8_array =
    nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;

constexpr double kQuaternionTolerance = 1e-3;

template <typename T>
void assign_nonempty(
    std::vector<T> &destination, const T *source, size_t count) {
    if (count != 0) destination.assign(source, source + count);
}

template <typename T>
nb::ndarray<nb::numpy, const T> array_view(
    nb::handle owner, const std::vector<T> &values, std::vector<size_t> shape) {
    static const T sentinel{};
    const T *data = values.empty() ? &sentinel : values.data();
    return sio::view<const T>(owner, data, std::move(shape));
}

void validate_text(const std::string &value, const char *name, bool allow_empty) {
    if ((!allow_empty && value.empty()) || value.size() > 1024 * 1024 ||
        value.find('\0') != std::string::npos || !sio::valid_utf8(value))
        throw std::invalid_argument(
            std::string("PointScan: ") + name +
            " must be valid UTF-8 without NUL and at most 1 MiB");
    for (unsigned char character : value)
        if (character < 0x20 && character != '\t' && character != '\n' &&
            character != '\r')
            throw std::invalid_argument(
                std::string("PointScan: ") + name +
                " must not contain control characters");
}

bool unit_quaternion(const double *q) {
    double norm_squared = 0.0;
    for (size_t index = 0; index < 4; ++index) {
        if (!std::isfinite(q[index])) return false;
        norm_squared += q[index] * q[index];
    }
    return std::abs(norm_squared - 1.0) <= kQuaternionTolerance;
}

void validate_bounds(
    int64_t minimum, int64_t maximum, const char *axis) {
    if (minimum > maximum)
        throw std::invalid_argument(
            std::string("PointScan: ") + axis +
            " bounds must be inclusive and minimum <= maximum");
}

template <typename T>
void copy_selected_rows(
    const std::vector<T> &source, std::vector<T> &destination,
    const std::vector<size_t> &rows, size_t components = 1) {
    if (source.empty()) return;
    if (rows.size() > std::numeric_limits<size_t>::max() / components)
        throw std::length_error("PointScan: projected field extent overflows size_t");
    destination.resize(rows.size() * components);
    for (size_t output = 0; output < rows.size(); ++output) {
        const size_t source_offset = rows[output] * components;
        const size_t destination_offset = output * components;
        std::copy_n(
            source.data() + source_offset, components,
            destination.data() + destination_offset);
    }
}

PointCloud project_valid_cloud(const PointScan &scan) {
    const PointCloud &source = scan.point_cloud;
    std::vector<size_t> rows;
    rows.reserve(source.n);
    for (size_t row = 0; row < source.n; ++row)
        if (!scan.has_invalid_states || scan.invalid_states[row] == 0)
            rows.push_back(row);

    PointCloud result;
    result.n = rows.size();
    copy_selected_rows(source.xyz, result.xyz, rows, 3);
    copy_selected_rows(source.rgb, result.rgb, rows, 3);
    copy_selected_rows(source.rgb16, result.rgb16, rows, 3);
    copy_selected_rows(source.normals, result.normals, rows, 3);
    copy_selected_rows(source.intensity, result.intensity, rows);
    copy_selected_rows(source.display_colors, result.display_colors, rows, 3);
    copy_selected_rows(source.display_opacities, result.display_opacities, rows);
    copy_selected_rows(source.widths, result.widths, rows);
    copy_selected_rows(source.ids, result.ids, rows);
    copy_selected_rows(source.velocities, result.velocities, rows, 3);
    copy_selected_rows(source.accelerations, result.accelerations, rows, 3);
    if (source.has_tracks()) {
        result.track_offsets.reserve(rows.size() + 1);
        result.track_offsets.push_back(0);
        for (size_t row : rows) {
            const size_t begin = source.track_offsets[row];
            const size_t end = source.track_offsets[row + 1];
            result.track_image_ids.insert(
                result.track_image_ids.end(),
                source.track_image_ids.begin() + begin,
                source.track_image_ids.begin() + end);
            result.track_keypoint_indices.insert(
                result.track_keypoint_indices.end(),
                source.track_keypoint_indices.begin() + begin,
                source.track_keypoint_indices.begin() + end);
            result.track_offsets.push_back(
                result.track_image_ids.size());
        }
    }
    result.display_color_space = source.display_color_space;
    result.coordinate_frame = source.coordinate_frame;
    result.scale_to_meters = source.scale_to_meters;
    result.intensity_range = source.intensity_range;
    for (size_t component = 0; component < 3; ++component)
        result.origin[component] = source.origin[component];

    // Organization remains representable only when the projection did not
    // remove rows.  A filtered projection is an ordinary unorganized cloud.
    if (rows.size() == source.n) {
        result.organized_width = source.organized_width;
        result.organized_height = source.organized_height;
    }
    if (source.las_waveform) {
        auto sidecar = std::make_shared<LasWaveformSidecar>();
        *sidecar = *source.las_waveform;
        sidecar->n = rows.size();
        sidecar->point_records.clear();
        const size_t stride = source.las_waveform->point_record_length;
        if (stride != 0) {
            sidecar->point_records.resize(rows.size() * stride);
            for (size_t output = 0; output < rows.size(); ++output)
                std::copy_n(
                    source.las_waveform->point_records.data() + rows[output] * stride,
                    stride, sidecar->point_records.data() + output * stride);
        }
        result.las_waveform = std::move(sidecar);
    }
    for (size_t component = 0; component < 7; ++component)
        result.viewpoint[component] = scan.viewpoint[component];
    validate_point_cloud(result, "PointScan.valid_point_cloud");
    return result;
}

PointScan make_point_scan(
    PointCloud cloud, int64_t scan_id,
    std::optional<u8_array> invalid_states,
    std::optional<i64_array> row_indices,
    std::optional<i64_array> column_indices,
    std::optional<int64_t> row_minimum,
    std::optional<int64_t> row_maximum,
    std::optional<int64_t> column_minimum,
    std::optional<int64_t> column_maximum,
    const std::string &name, const std::string &guid,
    std::optional<double> timestamp,
    std::optional<nb::ndarray<const double, nb::c_contig, nb::device::cpu>> viewpoint) {
    // PointScan owns the scan-level pose.  Silently resetting a child pose
    // would lose information, so non-neutral PointCloud children are refused.
    if (!cloud.has_default_viewpoint())
        throw std::invalid_argument(
            "point_scan: point_cloud viewpoint must be the neutral identity; "
            "the PointScan viewpoint is authoritative");
    if (!cloud.has_default_organization())
        throw std::invalid_argument(
            "point_scan: point_cloud organization must be the neutral "
            "unorganized shape; stored row/column metadata is authoritative");
    validate_point_cloud(cloud, "point_scan point_cloud");
    const size_t count = cloud.n;
    if (invalid_states &&
        (invalid_states->ndim() != 1 || invalid_states->shape(0) != count))
        throw std::invalid_argument(
            "point_scan: invalid_states must be (N,) uint8");
    if (row_indices.has_value() != column_indices.has_value())
        throw std::invalid_argument(
            "point_scan: row_indices and column_indices must be provided together");
    if (row_indices &&
        (row_indices->ndim() != 1 || row_indices->shape(0) != count ||
         column_indices->ndim() != 1 || column_indices->shape(0) != count))
        throw std::invalid_argument(
            "point_scan: row_indices and column_indices must be (N,) int64");

    PointScan result;
    result.point_cloud = std::move(cloud);
    result.scan_id = scan_id;
    result.name = name;
    result.guid = guid;
    result.timestamp = timestamp;
    validate_text(result.name, "name", true);
    validate_text(result.guid, "guid", true);
    if (result.timestamp && !std::isfinite(*result.timestamp))
        throw std::invalid_argument("point_scan: timestamp must be finite");
    if (invalid_states) {
        result.has_invalid_states = true;
        assign_nonempty(
            result.invalid_states, invalid_states->data(), count);
    }
    if (row_indices) {
        result.has_row_column_indices = true;
        assign_nonempty(result.row_indices, row_indices->data(), count);
        assign_nonempty(result.column_indices, column_indices->data(), count);
    }

    auto set_bounds = [](
        const std::optional<int64_t> &minimum,
        const std::optional<int64_t> &maximum,
        const std::vector<int64_t> &indices, const char *axis,
        size_t count, bool row_axis) {
        int64_t lower;
        int64_t upper;
        if (minimum) {
            lower = *minimum;
        } else if (!indices.empty()) {
            lower = *std::min_element(indices.begin(), indices.end());
        } else {
            lower = 0;
        }
        if (maximum) {
            upper = *maximum;
        } else if (!indices.empty()) {
            upper = *std::max_element(indices.begin(), indices.end());
        } else if (indices.empty() && count != 0 && row_axis) {
            // Dense defaults apply only when no explicit sparse indices exist.
            if (count - 1 > static_cast<size_t>(std::numeric_limits<int64_t>::max()))
                throw std::length_error(
                    std::string("point_scan: ") + axis + " extent exceeds int64");
            upper = static_cast<int64_t>(count - 1);
        } else {
            upper = lower;
        }
        validate_bounds(lower, upper, axis);
        for (int64_t index : indices)
            if (index < lower || index > upper)
                throw std::invalid_argument(
                    std::string("point_scan: ") + axis +
                    " index is outside declared inclusive bounds");
        return std::pair<int64_t, int64_t>{lower, upper};
    };
    const auto rows = set_bounds(
        row_minimum, row_maximum, result.row_indices, "row", count, true);
    const auto columns = set_bounds(
        column_minimum, column_maximum, result.column_indices, "column", count, false);
    result.row_minimum = rows.first;
    result.row_maximum = rows.second;
    result.column_minimum = columns.first;
    result.column_maximum = columns.second;

    if (viewpoint) {
        if (viewpoint->ndim() != 1 || viewpoint->shape(0) != 7)
            throw std::invalid_argument(
                "point_scan: viewpoint must be (7,) float64 "
                "(tx,ty,tz,qw,qx,qy,qz)");
        for (size_t index = 0; index < 7; ++index) {
            if (!std::isfinite(viewpoint->data()[index]))
                throw std::invalid_argument(
                    "point_scan: viewpoint values must be finite");
            result.viewpoint[index] = viewpoint->data()[index];
        }
    }
    validate_point_scan(result);
    return result;
}

ScanSet make_scan_set(std::vector<PointScan> scans) {
    ScanSet result;
    result.scans = std::move(scans);
    result.scan_ids.reserve(result.scans.size());
    for (const PointScan &scan : result.scans)
        result.scan_ids.push_back(scan.scan_id);
    validate_scan_set(result);
    return result;
}

}  // namespace

size_t PointScan::num_valid_points() const {
    if (!has_invalid_states) return point_cloud.n;
    return static_cast<size_t>(std::count(
        invalid_states.begin(), invalid_states.end(), uint8_t{0}));
}

void validate_point_scan(const PointScan &scan, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    validate_point_cloud(scan.point_cloud, (prefix + "point_cloud").c_str());
    if (!scan.point_cloud.has_default_viewpoint())
        throw std::invalid_argument(
            prefix + "point_cloud viewpoint must be neutral");
    if (!scan.point_cloud.has_default_organization())
        throw std::invalid_argument(
            prefix + "point_cloud organization must be neutral");
    const size_t count = scan.point_cloud.n;
    if ((scan.has_invalid_states && scan.invalid_states.size() != count) ||
        (!scan.has_invalid_states && !scan.invalid_states.empty()) ||
        (scan.has_row_column_indices &&
         (scan.row_indices.size() != count ||
          scan.column_indices.size() != count)) ||
        (!scan.has_row_column_indices &&
         (!scan.row_indices.empty() || !scan.column_indices.empty())))
        throw std::invalid_argument(prefix + "stored-row field lengths disagree");
    validate_bounds(scan.row_minimum, scan.row_maximum, "row");
    validate_bounds(scan.column_minimum, scan.column_maximum, "column");
    if (scan.has_row_column_indices)
        for (size_t index = 0; index < count; ++index)
            if (scan.row_indices[index] < scan.row_minimum ||
                scan.row_indices[index] > scan.row_maximum ||
                scan.column_indices[index] < scan.column_minimum ||
                scan.column_indices[index] > scan.column_maximum)
                throw std::invalid_argument(
                    prefix + "stored row/column index is outside bounds");
    validate_text(scan.name, "name", true);
    validate_text(scan.guid, "guid", true);
    if (scan.timestamp && !std::isfinite(*scan.timestamp))
        throw std::invalid_argument(prefix + "timestamp must be finite");
    for (size_t index = 0; index < 3; ++index)
        if (!std::isfinite(scan.viewpoint[index]))
            throw std::invalid_argument(prefix + "viewpoint translation must be finite");
    if (!unit_quaternion(scan.viewpoint + 3))
        throw std::invalid_argument(
            prefix + "viewpoint quaternion must be finite and unit length");
}

void validate_scan_set(const ScanSet &scans, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    if (scans.scan_ids.size() != scans.scans.size())
        throw std::invalid_argument(prefix + "scan id storage is inconsistent");
    std::unordered_set<int64_t> ids;
    std::unordered_set<std::string> guids;
    ids.reserve(scans.scans.size());
    guids.reserve(scans.scans.size());
    for (size_t index = 0; index < scans.scans.size(); ++index) {
        validate_point_scan(scans.scans[index], context);
        if (!ids.insert(scans.scans[index].scan_id).second)
            throw std::invalid_argument(prefix + "scan ids must be unique");
        if (!scans.scans[index].guid.empty() &&
            !guids.insert(scans.scans[index].guid).second)
            throw std::invalid_argument(prefix + "non-empty scan guids must be unique");
        if (scans.scan_ids[index] != scans.scans[index].scan_id)
            throw std::invalid_argument(prefix + "scan id storage is inconsistent");
    }
}

void register_point_scan(nb::module_ &module) {
    nb::class_<PointScan>(module, "PointScan")
        .def_prop_ro("point_cloud", [](nb::handle_t<PointScan> self) -> PointCloud & {
            return nb::cast<PointScan &>(self).point_cloud;
        }, nb::rv_policy::reference_internal)
        .def_prop_ro("num_stored_points", [](const PointScan &scan) {
            return scan.num_stored_points();
        })
        .def_prop_ro("num_valid_points", [](const PointScan &scan) {
            return scan.num_valid_points();
        })
        .def_prop_ro("has_invalid_states", [](const PointScan &scan) {
            return scan.has_invalid_states;
        })
        .def_prop_ro("has_row_column_indices", [](const PointScan &scan) {
            return scan.has_row_column_indices;
        })
        .def_prop_ro("invalid_states", [](nb::handle_t<PointScan> self) {
            const auto &scan = nb::cast<const PointScan &>(self);
            return array_view(self, scan.invalid_states, {scan.invalid_states.size()});
        })
        .def_prop_ro("row_indices", [](nb::handle_t<PointScan> self) {
            const auto &scan = nb::cast<const PointScan &>(self);
            return array_view(self, scan.row_indices, {scan.row_indices.size()});
        })
        .def_prop_ro("column_indices", [](nb::handle_t<PointScan> self) {
            const auto &scan = nb::cast<const PointScan &>(self);
            return array_view(self, scan.column_indices, {scan.column_indices.size()});
        })
        .def_prop_ro("row_minimum", [](const PointScan &scan) { return scan.row_minimum; })
        .def_prop_ro("row_maximum", [](const PointScan &scan) { return scan.row_maximum; })
        .def_prop_ro("column_minimum", [](const PointScan &scan) { return scan.column_minimum; })
        .def_prop_ro("column_maximum", [](const PointScan &scan) { return scan.column_maximum; })
        .def_prop_ro("scan_id", [](const PointScan &scan) { return scan.scan_id; })
        .def_prop_ro("name", [](const PointScan &scan) { return scan.name; })
        .def_prop_ro("guid", [](const PointScan &scan) { return scan.guid; })
        .def_prop_ro("has_timestamp", [](const PointScan &scan) {
            return scan.timestamp.has_value();
        })
        .def_prop_ro("timestamp", [](const PointScan &scan) -> nb::object {
            return scan.timestamp ? nb::cast(*scan.timestamp) : nb::none();
        })
        .def_prop_ro("viewpoint", [](const PointScan &scan) {
            return nb::make_tuple(
                scan.viewpoint[0], scan.viewpoint[1], scan.viewpoint[2],
                scan.viewpoint[3], scan.viewpoint[4], scan.viewpoint[5],
                scan.viewpoint[6]);
        })
        .def_prop_ro("translation", [](const PointScan &scan) {
            return nb::make_tuple(
                scan.viewpoint[0], scan.viewpoint[1], scan.viewpoint[2]);
        })
        .def_prop_ro("rotation", [](const PointScan &scan) {
            return nb::make_tuple(
                scan.viewpoint[3], scan.viewpoint[4], scan.viewpoint[5],
                scan.viewpoint[6]);
        })
        .def_prop_ro("pose_convention", [](const PointScan &) {
            return "scan_to_reference";
        })
        .def_prop_ro("quaternion_order", [](const PointScan &) { return "wxyz"; })
        .def_prop_ro("coordinate_frame", [](const PointScan &scan) {
            return scan.point_cloud.coordinate_frame;
        })
        .def_prop_ro("scale_to_meters", [](const PointScan &scan) {
            return scan.point_cloud.scale_to_meters;
        })
        .def_prop_ro("intensity_range", [](const PointScan &scan) {
            return scan.point_cloud.intensity_range;
        })
        .def_prop_ro("origin", [](const PointScan &scan) {
            return nb::make_tuple(
                scan.point_cloud.origin[0], scan.point_cloud.origin[1],
                scan.point_cloud.origin[2]);
        })
        .def("valid_point_cloud", [](const PointScan &scan) {
            nb::gil_scoped_release release;
            return project_valid_cloud(scan);
        })
        .def("__repr__", [](const PointScan &scan) {
            return "<PointScan id=" + std::to_string(scan.scan_id) +
                   " stored=" + std::to_string(scan.num_stored_points()) +
                   " valid=" + std::to_string(scan.num_valid_points()) + ">";
        });

    module.def(
        "point_scan", &make_point_scan, "point_cloud"_a,
        nb::kw_only(), "scan_id"_a = int64_t{0},
        "invalid_states"_a = nb::none(),
        "row_indices"_a = nb::none(), "column_indices"_a = nb::none(),
        "row_minimum"_a = int64_t{0}, "row_maximum"_a = nb::none(),
        "column_minimum"_a = int64_t{0}, "column_maximum"_a = nb::none(),
        "name"_a = "", "guid"_a = "", "timestamp"_a = nb::none(),
        "viewpoint"_a = nb::none(),
        "Build a stored-row PointScan around a neutral PointCloud child. "
        "Invalid states are raw uint8 bytes; row and column indices are int64 "
        "and are validated against inclusive declared bounds.");

    nb::class_<ScanSet>(module, "ScanSet")
        .def_prop_ro("num_scans", [](const ScanSet &scans) {
            return scans.num_scans();
        })
        .def_prop_ro("scan_ids", [](nb::handle_t<ScanSet> self) {
            const auto &scans = nb::cast<const ScanSet &>(self);
            return array_view(self, scans.scan_ids, {scans.scan_ids.size()});
        })
        .def_prop_ro("scans", [](const ScanSet &scans) {
            return scans.scans;
        })
        .def("scan_at", [](nb::handle_t<ScanSet> self, size_t index) -> PointScan & {
            ScanSet &scans = nb::cast<ScanSet &>(self);
            if (index >= scans.scans.size())
                throw nb::index_error("ScanSet scan index out of range");
            return scans.scans[index];
        }, nb::rv_policy::reference_internal)
        .def("__len__", [](const ScanSet &scans) { return scans.num_scans(); })
        .def("__repr__", [](const ScanSet &scans) {
            return "<ScanSet n=" + std::to_string(scans.num_scans()) + ">";
        });

    module.def(
        "scan_set", &make_scan_set, "scans"_a,
        "Build an ordered ScanSet; duplicate scan identifiers are rejected.");
}
