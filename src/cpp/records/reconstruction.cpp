// records/reconstruction.cpp — Camera + Reconstruction nanobind bindings.
// Array accessors return zero-copy views (rv_policy::reference_internal keeps
// the owning Record alive); conventions are exposed as metadata.
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include "records/reconstruction.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
template <typename T>
nb::ndarray<nb::numpy, T> vw(const std::vector<T> &v, std::vector<size_t> shape) {
    return nb::ndarray<nb::numpy, T>(const_cast<T *>(v.data()), shape.size(), shape.data());
}
}  // namespace

void register_reconstruction(nb::module_ &m) {
    nb::class_<Camera>(m, "Camera")
        .def_ro("id", &Camera::id)
        .def_ro("model_id", &Camera::model_id)
        .def_prop_ro("model", [](const Camera &c) { return colmap_model_info(c.model_id).name; })
        .def_ro("width", &Camera::width)
        .def_ro("height", &Camera::height)
        .def_prop_ro("params", [](const Camera &c) { return vw(c.params, {c.params.size()}); })
        .def("__repr__", [](const Camera &c) {
            return "<Camera id=" + std::to_string(c.id) + " model=" + colmap_model_info(c.model_id).name +
                   " " + std::to_string(c.width) + "x" + std::to_string(c.height) + ">";
        });

    auto ri = nb::rv_policy::reference_internal;
    nb::class_<Reconstruction>(m, "Reconstruction")
        .def_prop_ro("num_cameras", [](const Reconstruction &r) { return r.cameras.size(); })
        .def_prop_ro("num_images", [](const Reconstruction &r) { return r.num_images(); })
        .def_prop_ro("num_points3D", [](const Reconstruction &r) { return r.num_points(); })
        .def_prop_ro("cameras", [](const Reconstruction &r) { return r.cameras; })
        .def_prop_ro("image_ids", [](const Reconstruction &r) { return vw(r.img_ids, {r.num_images()}); }, ri)
        .def_prop_ro("quaternions", [](const Reconstruction &r) { return vw(r.quats, {r.num_images(), 4}); }, ri)
        .def_prop_ro("translations", [](const Reconstruction &r) { return vw(r.trans, {r.num_images(), 3}); }, ri)
        .def_prop_ro("image_camera_ids", [](const Reconstruction &r) { return vw(r.img_cam_ids, {r.num_images()}); }, ri)
        .def_prop_ro("image_names", [](const Reconstruction &r) { return r.img_names; })
        .def_prop_ro("point3D_ids", [](const Reconstruction &r) { return vw(r.pt_ids, {r.num_points()}); }, ri)
        .def_prop_ro("xyz", [](const Reconstruction &r) { return vw(r.xyz, {r.num_points(), 3}); }, ri)
        .def_prop_ro("rgb", [](const Reconstruction &r) { return vw(r.rgb, {r.num_points(), 3}); }, ri)
        .def_prop_ro("errors", [](const Reconstruction &r) { return vw(r.err, {r.num_points()}); }, ri)
        // conventions (metadata, not comments)
        .def_prop_ro("quaternion_order", [](const Reconstruction &) { return "wxyz"; })
        .def_prop_ro("pose_convention", [](const Reconstruction &) { return "world_to_camera"; })
        .def("__repr__", [](const Reconstruction &r) {
            return "<Reconstruction cameras=" + std::to_string(r.cameras.size()) +
                   " images=" + std::to_string(r.num_images()) +
                   " points3D=" + std::to_string(r.num_points()) + ">";
        });
}
