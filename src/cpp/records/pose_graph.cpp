// records/pose_graph.cpp -- PoseGraph validation and nanobind binding.
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/optional.h>

#include <cmath>
#include <cstring>
#include <limits>
#include <optional>
#include <string>
#include <unordered_set>

#include "records/pose_graph.hpp"

using namespace nb::literals;

namespace {

using i64_array =
    nb::ndarray<const int64_t, nb::c_contig, nb::device::cpu>;
using u8_array =
    nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;
using f64_array =
    nb::ndarray<const double, nb::c_contig, nb::device::cpu>;

template <typename T>
nb::ndarray<nb::numpy, T> graph_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static T sentinel{};
    T *data =
        values.empty() ? &sentinel : const_cast<T *>(values.data());
    return nb::ndarray<nb::numpy, T>(
        data, shape.size(), shape.data());
}

void require_shape(
    const f64_array &array, size_t rows, size_t columns,
    const char *name) {
    if (array.ndim() != 2 || array.shape(0) != rows ||
        array.shape(1) != columns)
        throw std::invalid_argument(
            std::string("pose_graph: ") + name + " must be (N," +
            std::to_string(columns) + ") float64");
}

void require_information_shape(
    const f64_array &array, size_t edges) {
    if (array.ndim() != 3 || array.shape(0) != edges ||
        array.shape(1) != 6 || array.shape(2) != 6)
        throw std::invalid_argument(
            "pose_graph: information_matrices must be (M,6,6) "
            "float64");
}

void validate_type_name(
    const std::string &value, const char *context,
    const char *kind) {
    if (value.empty())
        throw std::invalid_argument(
            std::string(context) + ": " + kind +
            " type names must be non-empty");
    for (unsigned char c : value)
        if (c < 0x20 || c == 0x7f)
            throw std::invalid_argument(
                std::string(context) + ": " + kind +
                " type names cannot contain control characters");
}

void validate_quaternions(
    const std::vector<double> &values, size_t count,
    const std::string &order, const std::string &sign,
    const char *context, const char *kind) {
    const size_t w_index = order == "wxyz" ? 0 : 3;
    for (size_t row = 0; row < count; ++row) {
        const double *q = values.data() + row * 4;
        double norm_squared = 0.0;
        for (size_t component = 0; component < 4; ++component) {
            if (!std::isfinite(q[component]))
                throw std::invalid_argument(
                    std::string(context) + ": " + kind +
                    " quaternions must be finite");
            norm_squared += q[component] * q[component];
        }
        if (!std::isfinite(norm_squared) ||
            std::abs(norm_squared - 1.0) > 1e-3)
            throw std::invalid_argument(
                std::string(context) + ": " + kind +
                " quaternions must be unit length within 1e-3");
        if (sign == "canonical_positive_w" && q[w_index] < 0.0)
            throw std::invalid_argument(
                std::string(context) + ": canonical_positive_w " +
                kind + " quaternions must have nonnegative W");
    }
}

template <typename T>
void assign_nonempty(
    std::vector<T> &target, const T *data, size_t count) {
    if (count != 0) target.assign(data, data + count);
}

std::vector<std::string> optional_types(
    std::optional<std::vector<std::string>> source,
    size_t count, const char *kind) {
    if (!source)
        return std::vector<std::string>(count, "se3");
    auto result = std::move(*source);
    if (result.size() != count)
        throw std::invalid_argument(
            std::string("pose_graph: ") + kind +
            "_types must contain one value per " + kind);
    return result;
}

PoseGraph make_pose_graph(
    i64_array node_ids, f64_array node_translations,
    f64_array node_quaternions, i64_array edge_endpoints,
    f64_array edge_translations, f64_array edge_quaternions,
    f64_array information_matrices,
    std::optional<u8_array> fixed,
    std::optional<std::vector<std::string>> node_types,
    std::optional<std::vector<std::string>> edge_types,
    const std::string &quaternion_order,
    const std::string &quaternion_sign,
    const std::string &node_transform_convention,
    const std::string &edge_transform_convention,
    const std::string &translation_unit,
    const std::string &information_variable_order) {
    if (node_ids.ndim() != 1)
        throw std::invalid_argument(
            "pose_graph: node_ids must be (N,) int64");
    const size_t nodes = node_ids.shape(0);
    if (nodes > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument(
            "pose_graph: node count overflows field extents");
    require_shape(
        node_translations, nodes, 3, "node_translations");
    require_shape(
        node_quaternions, nodes, 4, "node_quaternions");
    if (edge_endpoints.ndim() != 2 ||
        edge_endpoints.shape(1) != 2)
        throw std::invalid_argument(
            "pose_graph: edge_endpoints must be (M,2) int64");
    const size_t edges = edge_endpoints.shape(0);
    if (edges > std::numeric_limits<size_t>::max() / 36)
        throw std::invalid_argument(
            "pose_graph: edge count overflows field extents");
    require_shape(
        edge_translations, edges, 3, "edge_translations");
    require_shape(
        edge_quaternions, edges, 4, "edge_quaternions");
    require_information_shape(information_matrices, edges);

    PoseGraph graph;
    graph.n = nodes;
    graph.m = edges;
    graph.quaternion_order = quaternion_order;
    graph.quaternion_sign = quaternion_sign;
    graph.node_transform_convention =
        node_transform_convention;
    graph.edge_transform_convention =
        edge_transform_convention;
    graph.translation_unit = translation_unit;
    graph.information_variable_order =
        information_variable_order;
    graph.node_types =
        optional_types(std::move(node_types), nodes, "node");
    graph.edge_types =
        optional_types(std::move(edge_types), edges, "edge");

    if (!fixed) {
        graph.fixed.assign(nodes, 0);
    } else {
        if (fixed->ndim() != 1 || fixed->shape(0) != nodes)
            throw std::invalid_argument(
                "pose_graph: fixed must be (N,) uint8");
        assign_nonempty(graph.fixed, fixed->data(), nodes);
    }

    {
        nb::gil_scoped_release release;
        assign_nonempty(graph.node_ids, node_ids.data(), nodes);
        assign_nonempty(
            graph.node_translations, node_translations.data(),
            nodes * 3);
        assign_nonempty(
            graph.node_quaternions, node_quaternions.data(),
            nodes * 4);
        assign_nonempty(
            graph.edge_endpoints, edge_endpoints.data(), edges * 2);
        assign_nonempty(
            graph.edge_translations, edge_translations.data(),
            edges * 3);
        assign_nonempty(
            graph.edge_quaternions, edge_quaternions.data(),
            edges * 4);
        assign_nonempty(
            graph.information_matrices,
            information_matrices.data(), edges * 36);
        validate_pose_graph(graph);
    }
    return graph;
}

}  // namespace

void validate_pose_graph(
    const PoseGraph &graph, const char *context) {
    const size_t nodes = graph.n;
    const size_t edges = graph.m;
    if (nodes > std::numeric_limits<size_t>::max() / 4 ||
        edges > std::numeric_limits<size_t>::max() / 36 ||
        graph.node_ids.size() != nodes ||
        graph.node_translations.size() != nodes * 3 ||
        graph.node_quaternions.size() != nodes * 4 ||
        graph.fixed.size() != nodes ||
        graph.node_types.size() != nodes ||
        graph.edge_endpoints.size() != edges * 2 ||
        graph.edge_translations.size() != edges * 3 ||
        graph.edge_quaternions.size() != edges * 4 ||
        graph.information_matrices.size() != edges * 36 ||
        graph.edge_types.size() != edges)
        throw std::invalid_argument(
            std::string(context) +
            ": inconsistent PoseGraph field lengths");

    if (!pose_graph_valid_quaternion_order(
            graph.quaternion_order))
        throw std::invalid_argument(
            std::string(context) +
            ": quaternion_order must be wxyz|xyzw");
    if (!pose_graph_valid_quaternion_sign(
            graph.quaternion_sign))
        throw std::invalid_argument(
            std::string(context) +
            ": quaternion_sign must be "
            "preserved|canonical_positive_w");
    if (!pose_graph_valid_node_convention(
            graph.node_transform_convention))
        throw std::invalid_argument(
            std::string(context) +
            ": node_transform_convention must be "
            "node_to_reference|reference_to_node");
    if (!pose_graph_valid_edge_convention(
            graph.edge_transform_convention))
        throw std::invalid_argument(
            std::string(context) +
            ": edge_transform_convention must be "
            "source_inverse_times_target|"
            "target_inverse_times_source");
    if (!pose_graph_valid_translation_unit(
            graph.translation_unit))
        throw std::invalid_argument(
            std::string(context) +
            ": translation_unit must be "
            "unspecified|meters|millimeters");
    if (!pose_graph_valid_information_order(
            graph.information_variable_order))
        throw std::invalid_argument(
            std::string(context) +
            ": information_variable_order must be "
            "tx_ty_tz_qx_qy_qz");

    std::unordered_set<int64_t> ids;
    ids.reserve(nodes);
    for (size_t row = 0; row < nodes; ++row) {
        if (!ids.insert(graph.node_ids[row]).second)
            throw std::invalid_argument(
                std::string(context) +
                ": node ids must be unique");
        if (graph.fixed[row] > 1)
            throw std::invalid_argument(
                std::string(context) +
                ": fixed flags must be canonical 0 or 1");
        validate_type_name(
            graph.node_types[row], context, "node");
        for (size_t component = 0; component < 3; ++component)
            if (!std::isfinite(
                    graph.node_translations[row * 3 + component]))
                throw std::invalid_argument(
                    std::string(context) +
                    ": node translations must be finite");
    }
    validate_quaternions(
        graph.node_quaternions, nodes, graph.quaternion_order,
        graph.quaternion_sign, context, "node");

    for (size_t row = 0; row < edges; ++row) {
        const int64_t source = graph.edge_endpoints[row * 2];
        const int64_t target = graph.edge_endpoints[row * 2 + 1];
        if (!ids.count(source) || !ids.count(target))
            throw std::invalid_argument(
                std::string(context) +
                ": every edge endpoint must reference a node id");
        validate_type_name(
            graph.edge_types[row], context, "edge");
        for (size_t component = 0; component < 3; ++component)
            if (!std::isfinite(
                    graph.edge_translations[row * 3 + component]))
                throw std::invalid_argument(
                    std::string(context) +
                    ": edge translations must be finite");
        const double *matrix =
            graph.information_matrices.data() + row * 36;
        for (size_t r = 0; r < 6; ++r) {
            for (size_t c = 0; c < 6; ++c) {
                if (!std::isfinite(matrix[r * 6 + c]))
                    throw std::invalid_argument(
                        std::string(context) +
                        ": information matrices must be finite");
                if (std::memcmp(
                        &matrix[r * 6 + c],
                        &matrix[c * 6 + r],
                        sizeof(double)) != 0)
                    throw std::invalid_argument(
                        std::string(context) +
                        ": information matrices must be bitwise symmetric");
            }
        }
    }
    validate_quaternions(
        graph.edge_quaternions, edges, graph.quaternion_order,
        graph.quaternion_sign, context, "edge");
}

void register_pose_graph(nb::module_ &module) {
    const auto reference_internal =
        nb::rv_policy::reference_internal;
    nb::class_<PoseGraph>(module, "PoseGraph")
        .def_prop_ro(
            "num_nodes",
            [](const PoseGraph &value) {
                return value.num_nodes();
            })
        .def_prop_ro(
            "num_edges",
            [](const PoseGraph &value) {
                return value.num_edges();
            })
        .def_prop_ro(
            "node_ids",
            [](const PoseGraph &value) {
                return graph_view(value.node_ids, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "node_translations",
            [](const PoseGraph &value) {
                return graph_view(
                    value.node_translations, {value.n, 3});
            },
            reference_internal)
        .def_prop_ro(
            "node_quaternions",
            [](const PoseGraph &value) {
                return graph_view(
                    value.node_quaternions, {value.n, 4});
            },
            reference_internal)
        .def_prop_ro(
            "fixed",
            [](const PoseGraph &value) {
                return graph_view(value.fixed, {value.n});
            },
            reference_internal)
        .def_prop_ro(
            "node_types",
            [](const PoseGraph &value) {
                return value.node_types;
            })
        .def_prop_ro(
            "edge_endpoints",
            [](const PoseGraph &value) {
                return graph_view(
                    value.edge_endpoints, {value.m, 2});
            },
            reference_internal)
        .def_prop_ro(
            "edge_translations",
            [](const PoseGraph &value) {
                return graph_view(
                    value.edge_translations, {value.m, 3});
            },
            reference_internal)
        .def_prop_ro(
            "edge_quaternions",
            [](const PoseGraph &value) {
                return graph_view(
                    value.edge_quaternions, {value.m, 4});
            },
            reference_internal)
        .def_prop_ro(
            "information_matrices",
            [](const PoseGraph &value) {
                return graph_view(
                    value.information_matrices,
                    {value.m, 6, 6});
            },
            reference_internal)
        .def_prop_ro(
            "edge_types",
            [](const PoseGraph &value) {
                return value.edge_types;
            })
        .def_ro(
            "quaternion_order",
            &PoseGraph::quaternion_order)
        .def_ro(
            "quaternion_sign",
            &PoseGraph::quaternion_sign)
        .def_ro(
            "node_transform_convention",
            &PoseGraph::node_transform_convention)
        .def_ro(
            "edge_transform_convention",
            &PoseGraph::edge_transform_convention)
        .def_ro(
            "translation_unit",
            &PoseGraph::translation_unit)
        .def_ro(
            "information_variable_order",
            &PoseGraph::information_variable_order)
        .def_prop_ro(
            "information_storage",
            [](const PoseGraph &) {
                return "symmetric_6x6";
            })
        .def(
            "__repr__",
            [](const PoseGraph &value) {
                return "<PoseGraph nodes=" +
                       std::to_string(value.n) +
                       " edges=" + std::to_string(value.m) +
                       " " + value.edge_transform_convention +
                       ">";
            });

    module.def(
        "pose_graph", &make_pose_graph,
        "node_ids"_a, "node_translations"_a,
        "node_quaternions"_a, "edge_endpoints"_a,
        "edge_translations"_a, "edge_quaternions"_a,
        "information_matrices"_a,
        "fixed"_a = nb::none(),
        "node_types"_a = nb::none(),
        "edge_types"_a = nb::none(),
        "quaternion_order"_a = "xyzw",
        "quaternion_sign"_a = "preserved",
        "node_transform_convention"_a =
            "node_to_reference",
        "edge_transform_convention"_a =
            "source_inverse_times_target",
        "translation_unit"_a = "unspecified",
        "information_variable_order"_a =
            "tx_ty_tz_qx_qy_qz",
        "Build a typed pose graph with exact node ids, SE(3) node "
        "estimates and edge measurements, fixed flags, and symmetric "
        "6x6 information matrices. Inputs are copied into record-owned "
        "storage.");
}
