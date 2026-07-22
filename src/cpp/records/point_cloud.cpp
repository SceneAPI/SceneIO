// records/point_cloud.cpp — PointCloud nanobind binding. Registered once (after
// the other records) and shared by the point codecs (.xyz/.pts now; PCD,
// LAS/LAZ, E57, PLY-point later). Array accessors are fixed-dtype zero-copy
// views (the vw + rv_policy::reference_internal pattern, like GaussianCloud /
// PosedViewSet — NOT the sio::view(self,...) trick, which Image needs only
// because its getter returns a dtype-polymorphic nb::object). Conventions are
// metadata the codec recorded, and a `point_cloud(...)` factory builds one from
// arrays for tests.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <optional>

#include "records/point_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
// Fixed-dtype zero-copy view (the GaussianCloud/PosedViewSet vw + rv_policy
// pattern). The optional fields legitimately produce shaped-empty views ((0,3),
// (0,)) when absent or when N==0, whose vector .data() may be nullptr; feed
// numpy a static sentinel instead so a 0-size view never carries a null base
// pointer (the tensor_dict.cpp view_entry precedent — numpy reads 0 elements
// from it, so the byte's value is never observed).
template <typename T>
nb::ndarray<nb::numpy, T> vw(const std::vector<T> &v, std::vector<size_t> shape) {
    static T sentinel{};
    T *data = v.empty() ? &sentinel : const_cast<T *>(v.data());
    return nb::ndarray<nb::numpy, T>(data, shape.size(), shape.data());
}

// Fixed-dtype, read-only, contiguous CPU arrays. A foreign dtype / framework
// (float64 positions, a torch tensor, an int32 color array) is copy-converted
// to the canonical dtype by nanobind's typed caster (the make_pvs precedent);
// non-contiguous input is likewise copied. We assign() straight into our own
// vectors, so the caster's temporary lifetime is irrelevant.
using farr = nb::ndarray<const float, nb::c_contig, nb::device::cpu>;
using carr = nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;

PointCloud make_pc(farr positions, std::optional<carr> colors, std::optional<farr> normals,
                   std::optional<farr> intensity, const std::string &coordinate_frame,
                   double scale_to_meters, const std::string &intensity_range) {
    // 1. positions (N,3): ndim==2 && shape(1)==3; N==0 is legal (an empty .xyz
    //    file must round-trip once the codec lands).
    if (positions.ndim() != 2 || positions.shape(1) != 3)
        throw std::invalid_argument("point_cloud: positions must be (N,3) float32");
    const size_t N = positions.shape(0);
    PointCloud p;
    p.n = N;
    p.xyz.assign(positions.data(), positions.data() + N * 3);  // one bulk copy

    // 2. optional fields: each must be exactly (N,3) / (N,); absent -> empty vector.
    if (colors) {
        if (colors->ndim() != 2 || colors->shape(1) != 3 || colors->shape(0) != N)
            throw std::invalid_argument("point_cloud: colors must be (N,3) uint8");
        p.rgb.assign(colors->data(), colors->data() + N * 3);
    }
    if (normals) {
        if (normals->ndim() != 2 || normals->shape(1) != 3 || normals->shape(0) != N)
            throw std::invalid_argument("point_cloud: normals must be (N,3) float32");
        p.normals.assign(normals->data(), normals->data() + N * 3);
    }
    if (intensity) {
        if (intensity->ndim() != 1 || intensity->shape(0) != N)
            throw std::invalid_argument("point_cloud: intensity must be (N,) float32");
        p.intensity.assign(intensity->data(), intensity->data() + N);
    }

    // 3. conventions: validate the closed vocabulary (Image's color_space
    //    precedent; stricter than make_pvs, which validates nothing).
    if (!pc_valid_frame(coordinate_frame))
        throw std::invalid_argument(
            "point_cloud: coordinate_frame must be unknown|opencv|opengl|enu|ned");
    if (!pc_valid_intensity_range(intensity_range))
        throw std::invalid_argument(
            "point_cloud: intensity_range must be unknown|unit|u8|u16");
    p.coordinate_frame = coordinate_frame;
    p.scale_to_meters = scale_to_meters;
    p.intensity_range = intensity_range;
    return p;
}
}  // namespace

void register_point_cloud(nb::module_ &m) {
    auto ri = nb::rv_policy::reference_internal;  // fixed-dtype record => vw + ri
    nb::class_<PointCloud>(m, "PointCloud")
        .def_prop_ro("num_points", [](const PointCloud &p) { return p.num_points(); })
        .def_prop_ro("positions", [](const PointCloud &p) { return vw(p.xyz, {p.n, 3}); }, ri)
        .def_prop_ro(
            "colors", [](const PointCloud &p) { return vw(p.rgb, {p.has_rgb() ? p.n : 0, 3}); }, ri)
        .def_prop_ro(
            "normals",
            [](const PointCloud &p) { return vw(p.normals, {p.has_normals() ? p.n : 0, 3}); }, ri)
        .def_prop_ro(
            "intensities", [](const PointCloud &p) { return vw(p.intensity, {p.intensity.size()}); },
            ri)
        .def_prop_ro("has_rgb", [](const PointCloud &p) { return p.has_rgb(); })
        .def_prop_ro("has_normals", [](const PointCloud &p) { return p.has_normals(); })
        .def_prop_ro("has_intensity", [](const PointCloud &p) { return p.has_intensity(); })
        // conventions the codec recorded (metadata, not fixed):
        .def_prop_ro("coordinate_frame", [](const PointCloud &p) { return p.coordinate_frame; })
        .def_prop_ro("scale_to_meters", [](const PointCloud &p) { return p.scale_to_meters; })
        .def_prop_ro("intensity_range", [](const PointCloud &p) { return p.intensity_range; })
        .def("__repr__", [](const PointCloud &p) {
            return "<PointCloud n=" + std::to_string(p.n) + (p.has_rgb() ? " rgb" : "") +
                   (p.has_normals() ? " normals" : "") + (p.has_intensity() ? " intensity" : "") +
                   " " + p.coordinate_frame + ">";
        });

    m.def("point_cloud", &make_pc, "positions"_a, "colors"_a = nb::none(), "normals"_a = nb::none(),
          "intensity"_a = nb::none(), "coordinate_frame"_a = "unknown", "scale_to_meters"_a = 1.0,
          "intensity_range"_a = "unknown",
          "Build a PointCloud from arrays (numpy/torch): positions (N,3) float32, optional "
          "colors (N,3) uint8 / normals (N,3) float32 / intensity (N,) float32 (foreign dtypes "
          "are copy-converted by the caster), plus recorded convention tags "
          "(coordinate_frame, scale_to_meters, intensity_range).");
}
