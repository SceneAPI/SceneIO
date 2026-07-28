#include "bindings/registry.hpp"

void register_y4m(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {32, "y4m", &::register_y4m},
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
