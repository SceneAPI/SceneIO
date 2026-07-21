// sceneio._core — the nanobind module assembler. Each codec lives in its
// own translation unit and registers via a small hook.
#include <nanobind/nanobind.h>

namespace nb = nanobind;

void register_pfm(nb::module_ &);
void register_colmap(nb::module_ &);
void register_ply_gaussian(nb::module_ &);
void register_spz(nb::module_ &);

NB_MODULE(_core, m) {
    m.doc() = "sceneio compiled core (nanobind): codecs + SoA memory representations";
    m.attr("__phase__") = 1;
    register_pfm(m);
    register_colmap(m);
    register_ply_gaussian(m);  // registers the GaussianCloud type (shared with SPZ)
    register_spz(m);
}
