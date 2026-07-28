#include "bindings/registry.hpp"

void register_netpbm(nanobind::module_ &);
void register_png(nanobind::module_ &);
void register_jpeg(nanobind::module_ &);
void register_hdr(nanobind::module_ &);
void register_bmp_tga(nanobind::module_ &);
void register_exr(nanobind::module_ &);
void register_webp(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {16, "netpbm", &::register_netpbm},
    {25, "png", &::register_png},
    {26, "jpeg", &::register_jpeg},
    {27, "hdr", &::register_hdr},
    {28, "bmp_tga", &::register_bmp_tga},
    {29, "exr", &::register_exr},
    {33, "webp", &::register_webp},
};

constexpr CodecDescriptor CODECS[] = {
    {28,
     "netpbm",
     "images",
     symbols("read_netpbm"),
     symbols("write_netpbm"),
     symbols(),
     symbols("read_netpbm"),
     symbols("write_netpbm"),
     symbols("read_netpbm_window")},
    {29,
     "png",
     "images",
     symbols("read_png"),
     symbols("write_png"),
     symbols(),
     symbols("read_png"),
     symbols("write_png"),
     symbols()},
    {30,
     "jpeg",
     "images",
     symbols("read_jpeg"),
     symbols("write_jpeg"),
     symbols(),
     symbols("read_jpeg"),
     symbols("write_jpeg"),
     symbols()},
    {31,
     "bmp",
     "images",
     symbols("read_bmp"),
     symbols("write_bmp"),
     symbols("_inspect_bmp"),
     symbols("read_bmp"),
     symbols("write_bmp"),
     symbols()},
    {32,
     "tga",
     "images",
     symbols("read_tga"),
     symbols("write_tga"),
     symbols("_inspect_tga"),
     symbols("read_tga"),
     symbols("write_tga"),
     symbols()},
    {33,
     "hdr",
     "images",
     symbols("read_hdr"),
     symbols("write_hdr"),
     symbols(),
     symbols("read_hdr"),
     symbols("write_hdr"),
     symbols()},
    {34,
     "exr",
     "images",
     symbols("read_exr"),
     symbols("write_exr"),
     symbols(),
     symbols("read_exr"),
     symbols("write_exr"),
     symbols()},
    {35,
     "webp",
     "images",
     symbols("read_webp"),
     symbols("write_webp"),
     symbols(),
     symbols("read_webp"),
     symbols("write_webp"),
     symbols("read_webp_window")},
};

constexpr FamilyBindings FAMILY{
    "images",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

} // namespace

const FamilyBindings &image_bindings() { return FAMILY; }

} // namespace sio::bindings
