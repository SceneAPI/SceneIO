// records/gaussian_cloud.cpp — GaussianCloud nanobind binding. Registered
// once and shared by the PLY and SPZ codecs; conventions are metadata.
#include <nanobind/stl/string.h>

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
        .def_prop_ro("quaternion_order", [](const GaussianCloud &) { return "wxyz"; })
        .def_prop_ro("scale_space", [](const GaussianCloud &) { return "log"; })
        .def_prop_ro("opacity_space", [](const GaussianCloud &) { return "logit"; })
        .def_prop_ro("sh_layout", [](const GaussianCloud &) { return "channel_grouped"; })
        .def("__repr__", [](const GaussianCloud &g) {
            return "<GaussianCloud n=" + std::to_string(g.n) +
                   " sh_degree=" + std::to_string(g.sh_degree) + ">";
        });
}
