// records/posed_view_set.cpp — PosedViewSet nanobind binding. Registered once
// (after Camera/Reconstruction) and shared by the pose codecs (transforms.json,
// TUM/KITTI). Array accessors are zero-copy views; conventions are metadata
// the codec recorded, and a `posed_view_set(...)` factory builds one from
// arrays for tests.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <optional>

#include "records/posed_view_set.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
template <typename T>
nb::ndarray<nb::numpy, T> vw(const std::vector<T> &v, std::vector<size_t> shape) {
    return nb::ndarray<nb::numpy, T>(const_cast<T *>(v.data()), shape.size(), shape.data());
}

using darr = nb::ndarray<const double, nb::c_contig, nb::device::cpu>;
PosedViewSet make_pvs(darr quaternions, darr translations,
                      std::optional<std::vector<std::string>> names, std::optional<darr> timestamps,
                      const std::string &quaternion_order, const std::string &pose_convention,
                      const std::string &axis_frame, double scale_to_meters) {
    const size_t nv = translations.shape(0);
    if (translations.ndim() < 2 || translations.shape(1) != 3 || quaternions.shape(0) != nv ||
        quaternions.ndim() < 2 || quaternions.shape(1) != 4)
        throw std::invalid_argument("posed_view_set: need quaternions (N,4) and translations (N,3)");
    PosedViewSet p;
    p.quats.assign(quaternions.data(), quaternions.data() + nv * 4);
    p.trans.assign(translations.data(), translations.data() + nv * 3);
    if (names) {
        if (names->size() != nv) throw std::invalid_argument("posed_view_set: len(names) != N");
        p.names = std::move(*names);
    }
    if (timestamps) {
        if (timestamps->shape(0) != nv) throw std::invalid_argument("posed_view_set: len(timestamps) != N");
        p.stamps.assign(timestamps->data(), timestamps->data() + nv);
    }
    p.quaternion_order = quaternion_order;
    p.pose_convention = pose_convention;
    p.axis_frame = axis_frame;
    p.scale_to_meters = scale_to_meters;
    return p;
}
}  // namespace

void register_posed_view_set(nb::module_ &m) {
    auto ri = nb::rv_policy::reference_internal;
    nb::class_<PosedViewSet>(m, "PosedViewSet")
        .def_prop_ro("num_views", [](const PosedViewSet &p) { return p.num_views(); })
        .def_prop_ro("num_cameras", [](const PosedViewSet &p) { return p.num_cameras(); })
        .def_prop_ro("quaternions", [](const PosedViewSet &p) { return vw(p.quats, {p.num_views(), 4}); }, ri)
        .def_prop_ro("translations", [](const PosedViewSet &p) { return vw(p.trans, {p.num_views(), 3}); }, ri)
        .def_prop_ro("camera_indices", [](const PosedViewSet &p) { return vw(p.cam_idx, {p.cam_idx.size()}); }, ri)
        .def_prop_ro("timestamps", [](const PosedViewSet &p) { return vw(p.stamps, {p.stamps.size()}); }, ri)
        .def_prop_ro("names", [](const PosedViewSet &p) { return p.names; })
        .def_prop_ro("cameras", [](const PosedViewSet &p) { return p.cameras; })
        // conventions the codec recorded (metadata, not fixed):
        .def_prop_ro("quaternion_order", [](const PosedViewSet &p) { return p.quaternion_order; })
        .def_prop_ro("pose_convention", [](const PosedViewSet &p) { return p.pose_convention; })
        .def_prop_ro("axis_frame", [](const PosedViewSet &p) { return p.axis_frame; })
        .def_prop_ro("scale_to_meters", [](const PosedViewSet &p) { return p.scale_to_meters; })
        .def("__repr__", [](const PosedViewSet &p) {
            return "<PosedViewSet views=" + std::to_string(p.num_views()) +
                   " cameras=" + std::to_string(p.num_cameras()) + " " + p.pose_convention + "/" +
                   p.axis_frame + ">";
        });

    m.def("posed_view_set", &make_pvs, "quaternions"_a, "translations"_a, "names"_a = nb::none(),
          "timestamps"_a = nb::none(), "quaternion_order"_a = "wxyz",
          "pose_convention"_a = "camera_to_world", "axis_frame"_a = "opencv", "scale_to_meters"_a = 1.0,
          "Build a PosedViewSet from arrays (numpy/torch): quaternions (N,4), translations (N,3), "
          "optional names/timestamps, plus the pose/axis convention tags the source uses.");
}
