#include "bindings/registry.hpp"

void register_ply_gaussian(nanobind::module_ &);
void register_compressed_ply(nanobind::module_ &);
void register_sog(nanobind::module_ &);
void register_ksplat(nanobind::module_ &);
void register_spz(nanobind::module_ &);
void register_splat(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {2, "ply_gaussian", &::register_ply_gaussian},
    {3, "compressed_ply", &::register_compressed_ply},
    {4, "sog", &::register_sog},
    {5, "ksplat", &::register_ksplat},
    {12, "spz", &::register_spz},
    {24, "splat", &::register_splat},
};

constexpr CodecDescriptor CODECS[] = {
    {2,
     "gaussian_ply",
     "splats",
     symbols("read_gaussian_ply"),
     symbols("write_gaussian_ply"),
     symbols(),
     symbols("read_gaussian_ply"),
     symbols("write_gaussian_ply"),
     symbols("read_gaussian_ply_points")},
    {3,
     "compressed_ply",
     "splats",
     symbols("read_compressed_ply"),
     symbols("write_compressed_ply"),
     symbols(),
     symbols("read_compressed_ply"),
     symbols("write_compressed_ply"),
     symbols("read_compressed_ply_points")},
    {4,
     "sog",
     "splats",
     symbols("read_sog", "read_sog_directory"),
     symbols("write_sog", "write_sog_directory"),
     symbols("_inspect_sog_metadata"),
     symbols("read_sog", "read_sog_directory"),
     symbols("write_sog", "write_sog_directory"),
     symbols("read_sog_points", "read_sog_directory_points")},
    {5,
     "ksplat",
     "splats",
     symbols("read_ksplat"),
     symbols("write_ksplat"),
     symbols("_inspect_ksplat_metadata"),
     symbols("read_ksplat"),
     symbols("write_ksplat"),
     symbols("read_ksplat_points")},
    {14,
     "spz",
     "splats",
     symbols("read_spz"),
     symbols("write_spz"),
     symbols(),
     symbols("read_spz"),
     symbols("write_spz"),
     symbols()},
    {49,
     "splat",
     "splats",
     symbols("read_splat"),
     symbols("write_splat"),
     symbols(),
     symbols("read_splat"),
     symbols("write_splat"),
     symbols("read_splat_points")},
};

constexpr FamilyBindings FAMILY{
    "splats",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

} // namespace

const FamilyBindings &splat_bindings() { return FAMILY; }

} // namespace sio::bindings
