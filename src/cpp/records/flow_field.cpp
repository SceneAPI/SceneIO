// records/flow_field.cpp -- FlowField nanobind binding.
//
// The factory deliberately accepts only float32 without numeric conversion.
// Non-contiguous inputs may be copied to C order by nanobind, after which this
// record takes one owned copy. `vectors` is a zero-copy view over that owned
// storage and carries the record as its ndarray owner.
#include <nanobind/stl/string.h>

#include <limits>
#include <string>

#include "records/flow_field.hpp"

using namespace nb::literals;

namespace {

using anyarr = nb::ndarray<nb::ro, nb::c_contig, nb::device::cpu>;

FlowField make_flow_field(anyarr vectors, const std::string &component_order,
                          const std::string &u_axis,
                          const std::string &v_axis,
                          const std::string &row_order,
                          const std::string &unit,
                          const std::string &invalid_policy) {
    if (vectors.ndim() != 3 || vectors.shape(2) != 2)
        throw std::invalid_argument(
            "flow_field: vectors must be (H,W,2) float32 with H,W >= 1");
    const size_t height = vectors.shape(0);
    const size_t width = vectors.shape(1);
    if (height == 0 || width == 0)
        throw std::invalid_argument(
            "flow_field: vectors must be (H,W,2) float32 with H,W >= 1");
    if (vectors.dtype() != nb::dtype<float>())
        throw std::invalid_argument("flow_field: vectors must be float32");

    if (height > std::numeric_limits<size_t>::max() / width ||
        height * width > std::numeric_limits<size_t>::max() / 2)
        throw std::invalid_argument(
            "flow_field: dimensions overflow address space");
    const size_t value_count = height * width * 2;

    if (!flow_valid_component_order(component_order))
        throw std::invalid_argument(
            "flow_field: component_order must be uv|vu");
    if (!flow_valid_u_axis(u_axis))
        throw std::invalid_argument("flow_field: u_axis must be right|left");
    if (!flow_valid_v_axis(v_axis))
        throw std::invalid_argument("flow_field: v_axis must be down|up");
    if (!flow_valid_row_order(row_order))
        throw std::invalid_argument(
            "flow_field: row_order must be top_to_bottom|bottom_to_top");
    if (!flow_valid_unit(unit))
        throw std::invalid_argument(
            "flow_field: unit must be pixels|unknown");
    if (!flow_valid_invalid_policy(invalid_policy))
        throw std::invalid_argument(
            "flow_field: invalid_policy must be "
            "none|component_abs_gt_1e9|nonfinite");

    FlowField result;
    result.height = height;
    result.width = width;
    result.component_order = component_order;
    result.u_axis = u_axis;
    result.v_axis = v_axis;
    result.row_order = row_order;
    result.unit = unit;
    result.invalid_policy = invalid_policy;
    const auto *source = static_cast<const float *>(vectors.data());
    result.vectors.assign(source, source + value_count);
    return result;
}

}  // namespace

void register_flow_field(nb::module_ &m) {
    nb::class_<FlowField>(m, "FlowField")
        .def_prop_ro("height",
                     [](const FlowField &flow) { return flow.height; })
        .def_prop_ro("width",
                     [](const FlowField &flow) { return flow.width; })
        .def_prop_ro("vectors", [](nb::handle_t<FlowField> self) {
            const FlowField &flow = nb::cast<const FlowField &>(self);
            return sio::view(self, flow.vectors.data(),
                             {flow.height, flow.width, 2});
        })
        .def_prop_ro("component_order", [](const FlowField &flow) {
            return flow.component_order;
        })
        .def_prop_ro("u_axis",
                     [](const FlowField &flow) { return flow.u_axis; })
        .def_prop_ro("v_axis",
                     [](const FlowField &flow) { return flow.v_axis; })
        .def_prop_ro("row_order", [](const FlowField &flow) {
            return flow.row_order;
        })
        .def_prop_ro("unit",
                     [](const FlowField &flow) { return flow.unit; })
        .def_prop_ro("invalid_policy", [](const FlowField &flow) {
            return flow.invalid_policy;
        })
        .def("__repr__", [](const FlowField &flow) {
            return "<FlowField " + std::to_string(flow.height) + "x" +
                   std::to_string(flow.width) + " " +
                   flow.component_order + " " + flow.unit + " u+" +
                   flow.u_axis + " v+" + flow.v_axis + " invalid=" +
                   flow.invalid_policy + ">";
        });

    m.def(
        "flow_field", &make_flow_field, "vectors"_a,
        "component_order"_a = "uv", "u_axis"_a = "right",
        "v_axis"_a = "down", "row_order"_a = "top_to_bottom",
        "unit"_a = "pixels",
        "invalid_policy"_a = "component_abs_gt_1e9",
        "Build a FlowField from an owned copy of a (H,W,2) float32 array. "
        "Values are preserved raw; component order, positive axis directions, "
        "row order, units, and invalid-value policy are recorded as metadata.");
}
