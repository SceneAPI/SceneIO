#include "bindings/registry.hpp"

void register_pfm(nanobind::module_ &);
void register_npy_npz(nanobind::module_ &);
void register_flo(nanobind::module_ &);
void register_safetensors(nanobind::module_ &);
void register_dmb(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {0, "pfm", &::register_pfm},
    {15, "npy_npz", &::register_npy_npz},
    {19, "flo", &::register_flo},
    {34, "safetensors", &::register_safetensors},
    {35, "dmb", &::register_dmb},
};

constexpr CodecDescriptor CODECS[] = {
    {0,
     "pfm",
     "arrays",
     symbols("read_pfm"),
     symbols("write_pfm"),
     symbols("_inspect_pfm"),
     symbols("read_pfm"),
     symbols("write_pfm"),
     symbols("read_pfm_window")},
    {25,
     "npy",
     "arrays",
     symbols("read_npy", "read_npy_view"),
     symbols("write_npy"),
     symbols("_inspect_npy"),
     symbols("read_npy", "read_npy_view"),
     symbols("write_npy"),
     symbols()},
    {26,
     "npz",
     "arrays",
     symbols("read_npz"),
     symbols("write_npz"),
     symbols(),
     symbols("read_npz"),
     symbols("write_npz"),
     symbols()},
    {27,
     "safetensors",
     "arrays",
     symbols("read_safetensors", "read_safetensors_view"),
     symbols("write_safetensors"),
     symbols("_inspect_safetensors"),
     symbols("read_safetensors", "read_safetensors_view"),
     symbols("write_safetensors"),
     symbols(
         "read_safetensors_tensors",
         "read_safetensors_tensors_view",
         "read_safetensors_slices",
         "read_safetensors_slices_view")},
    {44,
     "flo",
     "arrays",
     symbols("read_flo", "read_flo_view"),
     symbols("write_flo"),
     symbols(),
     symbols("read_flo", "read_flo_view"),
     symbols("write_flo"),
     symbols("read_flo", "read_flo_view")},
    {45,
     "dmb",
     "arrays",
     symbols("read_dmb"),
     symbols("write_dmb"),
     symbols("_inspect_dmb"),
     symbols("read_dmb"),
     symbols("write_dmb"),
     symbols("read_dmb_window")},
};

constexpr FamilyBindings FAMILY{
    "arrays",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

} // namespace

const FamilyBindings &array_bindings() { return FAMILY; }

} // namespace sio::bindings
