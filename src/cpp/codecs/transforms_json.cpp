// codecs/transforms_json.cpp — NeRF / Instant-NGP / Nerfstudio transforms.json
// camera poses <-> PosedViewSet.
//
// SCAFFOLD STUB: the seams (record, binding, registry, build) are wired; the
// read/write bodies are authored in Phase 1. The real body parses with
// nlohmann/json (linked via CMake) and RECORDS the source convention as
// metadata (Instant-NGP is camera_to_world / OpenGL) rather than converting.
#include <stdexcept>

#include "records/posed_view_set.hpp"

using namespace nb::literals;

namespace {
PosedViewSet read_transforms_json(nb::bytes /*data*/) {
    throw std::runtime_error("transforms.json reader not implemented yet (scaffold stub)");
}
nb::bytes write_transforms_json(const PosedViewSet & /*views*/) {
    throw std::runtime_error("transforms.json writer not implemented yet (scaffold stub)");
}
}  // namespace

void register_transforms_json(nb::module_ &m) {
    m.def("read_transforms_json", &read_transforms_json, "data"_a,
          "Decode transforms.json (NeRF/Instant-NGP/Nerfstudio) bytes into a PosedViewSet.");
    m.def("write_transforms_json", &write_transforms_json, "views"_a,
          "Encode a PosedViewSet to transforms.json bytes.");
}
