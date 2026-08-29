// records/gaussian_cloud.cpp — GaussianCloud nanobind binding. Registered
// once and shared by the PLY and SPZ codecs; conventions are metadata.
#include <nanobind/stl/string.h>
#include <nanobind/stl/optional.h>

#include "records/gaussian_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
template <typename T>
nb::ndarray<nb::numpy, T> vw(const std::vector<T> &v, std::vector<size_t> shape) {
    return nb::ndarray<nb::numpy, T>(const_cast<T *>(v.data()), shape.size(), shape.data());
}
}  // namespace

void register_gaussian_cloud(nb::module_ &m) {
    auto ri = nb::rv_policy::reference_internal;
    nb::class_<GaussianCloud>(m, "GaussianCloud")
        .def_prop_ro("num_gaussians", [](const GaussianCloud &g) { return g.n; })
        .def_prop_ro("sh_degree", [](const GaussianCloud &g) { return g.sh_degree; })
        .def_prop_ro("num_rest", [](const GaussianCloud &g) { return g.num_rest; })
        .def_prop_ro("means", [](const GaussianCloud &g) { return vw(g.means, {g.n, 3}); }, ri)
        .def_prop_ro("scales", [](const GaussianCloud &g) { return vw(g.scales, {g.n, 3}); }, ri)
        .def_prop_ro("quaternions", [](const GaussianCloud &g) { return vw(g.quats, {g.n, 4}); }, ri)
        .def_prop_ro("opacities", [](const GaussianCloud &g) { return vw(g.opacity, {g.n}); }, ri)
        .def_prop_ro("sh_dc", [](const GaussianCloud &g) { return vw(g.sh_dc, {g.n, 3}); }, ri)
        .def_prop_ro("sh_rest", [](const GaussianCloud &g) { return vw(g.sh_rest, {g.n, g.num_rest}); }, ri)
        // conventions (metadata, not comments)
        .def_ro("quaternion_order", &GaussianCloud::quaternion_order)
        .def_ro("scale_space", &GaussianCloud::scale_space)
        .def_ro("opacity_space", &GaussianCloud::opacity_space)
        .def_ro("sh_layout", &GaussianCloud::sh_layout)
        .def_ro("source_precision", &GaussianCloud::source_precision)
        .def_ro("projection_mode_hint", &GaussianCloud::projection_mode_hint)
        .def_ro("sorting_mode_hint", &GaussianCloud::sorting_mode_hint)
        .def_ro("quaternion_norm", &GaussianCloud::quaternion_norm)
        .def_ro("sh_basis", &GaussianCloud::sh_basis)
        .def_ro("sh_phase", &GaussianCloud::sh_phase)
        .def_ro("sh_coefficient_order", &GaussianCloud::sh_coefficient_order)
        .def_ro("color_space", &GaussianCloud::color_space)
        .def_ro("coordinate_frame", &GaussianCloud::coordinate_frame)
        .def_ro("scale_to_meters", &GaussianCloud::scale_to_meters)
        .def_ro(
            "scale_to_meters_source",
            &GaussianCloud::scale_to_meters_source)
        .def("__repr__", [](const GaussianCloud &g) {
            return "<GaussianCloud n=" + std::to_string(g.n) +
                   " sh_degree=" + std::to_string(g.sh_degree) + ">";
        });
}
