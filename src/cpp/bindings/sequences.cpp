#include "bindings/registry.hpp"

void register_y4m(nanobind::module_ &);
void register_webm(nanobind::module_ &);
void register_animated_webp(nanobind::module_ &);
void register_apng(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {32, "y4m", &::register_y4m},
    {41, "animated_webp", &::register_animated_webp},
    {42, "apng", &::register_apng},
    {43, "webm", &::register_webm},
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
     symbols("write_webm"),
     symbols("_inspect_webm"),
     symbols("read_webm"),
     symbols("write_webm"),
     symbols("read_webm_frames")},
    {38,
     "animated_webp",
     "sequences",
     symbols("read_animated_webp"),
     symbols("write_animated_webp"),
     symbols("_inspect_animated_webp"),
     symbols("read_animated_webp"),
     symbols("write_animated_webp"),
     symbols()},
    {39,
     "apng",
     "sequences",
     symbols("read_apng"),
     symbols("write_apng"),
     symbols("_inspect_apng"),
     symbols("read_apng"),
     symbols("write_apng"),
     symbols()},
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
