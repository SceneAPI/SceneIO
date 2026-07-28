#pragma once

#include <array>
#include <cstddef>

#include <nanobind/nanobind.h>

namespace sio::bindings {

namespace nb = nanobind;

using RegisterFunction = void (*)(nb::module_ &);

struct SymbolList {
    std::array<const char *, 8> values{};
    std::size_t size = 0;
};

template <typename... Values>
constexpr SymbolList symbols(Values... values) {
    static_assert(sizeof...(Values) <= 8, "native symbol list is too large");
    return SymbolList{{values...}, sizeof...(Values)};
}

struct RegistrationDescriptor {
    std::size_t order;
    const char *name;
    RegisterFunction function;
};

struct CodecDescriptor {
    std::size_t manifest_order;
    const char *id;
    const char *family;
    SymbolList read;
    SymbolList write;
    SymbolList inspect;
    SymbolList stream_read;
    SymbolList stream_write;
    SymbolList partial;
};

struct FamilyBindings {
    const char *family;
    const RegistrationDescriptor *registrations;
    std::size_t registration_count;
    const CodecDescriptor *codecs;
    std::size_t codec_count;
};

const FamilyBindings &array_bindings();
const FamilyBindings &calibration_bindings();
const FamilyBindings &image_bindings();
const FamilyBindings &mesh_bindings();
const FamilyBindings &point_bindings();
const FamilyBindings &reconstruction_bindings();
const FamilyBindings &sequence_bindings();
const FamilyBindings &splat_bindings();

void register_records(nb::module_ &module);
void register_codecs(nb::module_ &module);
nb::tuple codec_inventory(nb::module_ &module);

} // namespace sio::bindings
