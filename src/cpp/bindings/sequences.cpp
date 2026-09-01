#include "bindings/registry.hpp"

void register_y4m(nanobind::module_ &);
void register_webm(nanobind::module_ &);
void register_animated_webp(nanobind::module_ &);
void register_apng(nanobind::module_ &);
void register_theora(nanobind::module_ &);
void register_ivf(nanobind::module_ &);
void register_mjpeg(nanobind::module_ &);
void register_mp4(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {32, "y4m", &::register_y4m},
    {41, "animated_webp", &::register_animated_webp},
    {42, "apng", &::register_apng},
    {43, "webm", &::register_webm},
    {44, "theora", &::register_theora},
    {45, "ivf", &::register_ivf},
    {46, "mjpeg", &::register_mjpeg},
    {47, "mp4", &::register_mp4},
};

constexpr CodecDescriptor CODECS[] = {
    {36,
     "y4m",
     "sequences",
     symbols("read_y4m"),
     symbols("write_y4m"),
     symbols("_inspect_y4m"),
     symbols("read_y4m"),
     symbols("write_y4m"),
     symbols("read_y4m_frames")},
    {37,
     "webm",
     "sequences",
     symbols("read_webm"),
     symbols("write_webm", "write_webm_temporal"),
     symbols("_inspect_webm"),
     symbols("read_webm"),
     symbols("write_webm", "write_webm_temporal"),
     symbols("read_webm_frames")},
    {42,
     "animated_webp",
     "sequences",
     symbols("read_animated_webp"),
     symbols("write_animated_webp"),
     symbols("_inspect_animated_webp"),
     symbols("read_animated_webp"),
     symbols("write_animated_webp"),
     symbols()},
    {43,
     "apng",
     "sequences",
     symbols("read_apng"),
     symbols("write_apng"),
     symbols("_inspect_apng"),
     symbols("read_apng"),
     symbols("write_apng"),
     symbols()},
    {41,
     "theora",
     "sequences",
     symbols("read_theora"),
     symbols("write_theora"),
     symbols("_inspect_theora"),
     symbols("read_theora"),
     symbols("write_theora"),
     symbols("read_theora_frames")},
    {38,
     "ivf",
     "sequences",
     symbols("read_ivf"),
     symbols("write_ivf"),
     symbols("_inspect_ivf"),
     symbols("read_ivf"),
     symbols("write_ivf"),
     symbols("read_ivf_frames")},
    {39,
     "mjpeg",
     "sequences",
     symbols("read_mjpeg"),
     symbols("write_mjpeg"),
     symbols("_inspect_mjpeg"),
     symbols("read_mjpeg"),
     symbols("write_mjpeg"),
     symbols("read_mjpeg_frames")},
    {40,
     "mp4",
     "sequences",
     symbols("read_mp4"),
     symbols(),
     symbols("_inspect_mp4"),
     symbols("read_mp4"),
     symbols(),
     symbols("read_mp4_frames")},
};

constexpr FamilyBindings FAMILY{
    "sequences",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

} // namespace

const FamilyBindings &sequence_bindings() { return FAMILY; }

} // namespace sio::bindings
