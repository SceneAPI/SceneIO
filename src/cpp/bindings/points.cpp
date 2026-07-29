#include "bindings/registry.hpp"

void register_ply_point(nanobind::module_ &);
void register_pcd(nanobind::module_ &);
void register_xyz(nanobind::module_ &);
void register_las(nanobind::module_ &);
void register_laz(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {6, "ply_point", &::register_ply_point},
    {11, "pcd", &::register_pcd},
    {18, "xyz", &::register_xyz},
    {30, "las", &::register_las},
    {31, "laz", &::register_laz},
};

constexpr CodecDescriptor CODECS[] = {
    {12,
     "ply",
     "points",
     symbols("read_ply"),
     symbols("write_ply"),
     symbols(),
     symbols("read_ply"),
     symbols("write_ply"),
     symbols("read_ply_points")},
    {13,
     "pcd",
     "points",
     symbols("read_pcd"),
     symbols("write_pcd"),
     symbols(),
     symbols("read_pcd"),
     symbols("write_pcd"),
     symbols("read_pcd_points")},
    {40,
     "xyz",
     "points",
     symbols("read_xyz"),
     symbols("write_xyz"),
     symbols("_inspect_xyz", "_inspect_xyz_file"),
     symbols("read_xyz"),
     symbols("write_xyz"),
     symbols("read_xyz_points")},
    {41,
     "pts",
     "points",
     symbols("read_pts"),
     symbols("write_pts"),
     symbols("_inspect_pts"),
     symbols("read_pts"),
     symbols("write_pts"),
     symbols("read_pts_points")},
    {42,
     "las",
     "points",
     symbols("read_las"),
     symbols("write_las"),
     symbols(),
     symbols("read_las"),
     symbols("write_las"),
     symbols("read_las_points")},
    {43,
     "laz",
     "points",
     symbols("read_laz"),
     symbols("write_laz"),
     symbols(),
     symbols("read_laz"),
     symbols("write_laz"),
     symbols("read_laz_points")},
};

constexpr FamilyBindings FAMILY{
    "points",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

} // namespace

const FamilyBindings &point_bindings() { return FAMILY; }

} // namespace sio::bindings
