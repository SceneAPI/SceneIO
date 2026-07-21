// codecs/pose_text.cpp — plain-text pose-trajectory formats <-> PosedViewSet:
// TUM (`timestamp tx ty tz qx qy qz qw`) and KITTI (12 numbers = a 3x4
// row-major pose matrix per line). Both are permissive/spec-only formats.
//
// SCAFFOLD STUB: seams wired; read/write bodies authored in Phase 1. Each
// reader RECORDS the source's conventions as metadata (TUM: xyzw quaternion,
// camera_to_world; KITTI: matrix -> quaternion) rather than converting.
// (g2o pose graphs are deferred — their edges don't fit PosedViewSet.)
#include <stdexcept>

#include "records/posed_view_set.hpp"

using namespace nb::literals;

namespace {
PosedViewSet read_tum(nb::bytes /*data*/) {
    throw std::runtime_error("TUM reader not implemented yet (scaffold stub)");
}
nb::bytes write_tum(const PosedViewSet & /*views*/) {
    throw std::runtime_error("TUM writer not implemented yet (scaffold stub)");
}
PosedViewSet read_kitti(nb::bytes /*data*/) {
    throw std::runtime_error("KITTI reader not implemented yet (scaffold stub)");
}
nb::bytes write_kitti(const PosedViewSet & /*views*/) {
    throw std::runtime_error("KITTI writer not implemented yet (scaffold stub)");
}
}  // namespace

void register_pose_text(nb::module_ &m) {
    m.def("read_tum", &read_tum, "data"_a, "Decode a TUM trajectory (bytes) into a PosedViewSet.");
    m.def("write_tum", &write_tum, "views"_a, "Encode a PosedViewSet to TUM trajectory bytes.");
    m.def("read_kitti", &read_kitti, "data"_a, "Decode a KITTI pose file (bytes) into a PosedViewSet.");
    m.def("write_kitti", &write_kitti, "views"_a, "Encode a PosedViewSet to KITTI pose bytes.");
}
