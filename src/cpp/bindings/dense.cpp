#include "bindings/registry.hpp"

void register_colmap_dense_mvs(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {40, "colmap_dense_mvs", &::register_colmap_dense_mvs},
};

constexpr CodecDescriptor CODECS[] = {
    {56,
     "colmap_mvs_depth",
     "dense",
     symbols("read_colmap_mvs_depth"),
     symbols("write_colmap_mvs_depth"),
     symbols("_inspect_colmap_mvs_depth"),
     symbols("read_colmap_mvs_depth"),
     symbols("write_colmap_mvs_depth"),
     symbols("read_colmap_mvs_depth_window")},
    {57,
     "colmap_mvs_normal",
     "dense",
     symbols("read_colmap_mvs_normal"),
     symbols("write_colmap_mvs_normal"),
     symbols("_inspect_colmap_mvs_normal"),
     symbols("read_colmap_mvs_normal"),
     symbols("write_colmap_mvs_normal"),
     symbols("read_colmap_mvs_normal_window")},
    {58,
     "colmap_mvs_consistency",
     "dense",
     symbols("read_colmap_mvs_consistency"),
     symbols("write_colmap_mvs_consistency"),
     symbols("_inspect_colmap_mvs_consistency"),
     symbols("read_colmap_mvs_consistency"),
     symbols("write_colmap_mvs_consistency"),
     symbols()},
    {59,
     "colmap_fused_visibility",
     "dense",
     symbols("read_colmap_fused_visibility"),
     symbols("write_colmap_fused_visibility"),
     symbols("_inspect_colmap_fused_visibility"),
     symbols("read_colmap_fused_visibility"),
     symbols("write_colmap_fused_visibility"),
     symbols()},
};

constexpr FamilyBindings FAMILY{
    "dense",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

}  // namespace

const FamilyBindings &dense_bindings() { return FAMILY; }

}  // namespace sio::bindings
