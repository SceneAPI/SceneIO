// sceneio._core — the nanobind module assembler. Records register first
// (they are the codecs' return types), then codecs. See
// docs/core_architecture.md for how to add a codec.
#include <nanobind/nanobind.h>

namespace nb = nanobind;

// records/
void register_reconstruction(nb::module_ &);
void register_gaussian_cloud(nb::module_ &);
void register_posed_view_set(nb::module_ &);
// codecs/
void register_pfm(nb::module_ &);
void register_colmap(nb::module_ &);
void register_ply_gaussian(nb::module_ &);
void register_spz(nb::module_ &);
void register_transforms_json(nb::module_ &);
void register_pose_text(nb::module_ &);

NB_MODULE(_core, m) {
    m.doc() = "sceneio compiled core (nanobind): codecs + SoA memory representations";
    m.attr("__phase__") = 2;

    register_reconstruction(m);
    register_gaussian_cloud(m);
    register_posed_view_set(m);

    register_pfm(m);
    register_colmap(m);
    register_ply_gaussian(m);
    register_spz(m);
    register_transforms_json(m);
    register_pose_text(m);
}
