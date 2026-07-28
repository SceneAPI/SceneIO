#include "bindings/registry.hpp"

#include <array>
#include <cstring>
#include <stdexcept>
#include <string>
#include <unordered_set>

namespace sio::bindings {
namespace {

constexpr std::size_t REGISTRATION_COUNT = 40;
constexpr std::size_t MANIFEST_COUNT = 50;
constexpr std::size_t NATIVE_CODEC_COUNT = 49;
constexpr std::size_t PYTHON_ONLY_MANIFEST_ORDER = 37;

const std::array<const FamilyBindings *, 8> &families() {
    static const std::array<const FamilyBindings *, 8> value{{
        &array_bindings(),
        &calibration_bindings(),
        &image_bindings(),
        &mesh_bindings(),
        &point_bindings(),
        &reconstruction_bindings(),
        &sequence_bindings(),
        &splat_bindings(),
    }};
    return value;
}

void validate_symbol_list(
    nb::module_ &module, const CodecDescriptor &codec, const char *operation,
    const SymbolList &symbols) {
    if (symbols.size > symbols.values.size())
        throw std::runtime_error("native codec symbol list exceeds capacity");
    std::unordered_set<std::string> names;
    for (std::size_t index = 0; index < symbols.size; ++index) {
        const char *name = symbols.values[index];
        if (name == nullptr || name[0] == '\0' ||
            !names.emplace(name).second) {
            throw std::runtime_error(
                std::string("native codec ") + codec.id + " has invalid " +
                operation + " symbols");
        }
        if (!nb::hasattr(module, name)) {
            throw std::runtime_error(
                std::string("native codec ") + codec.id +
                " references missing _core symbol " + name);
        }
        nb::object value = module.attr(name);
        if (PyCallable_Check(value.ptr()) == 0) {
            throw std::runtime_error(
                std::string("native codec ") + codec.id +
                " references non-callable _core symbol " + name);
        }
    }
}

nb::tuple symbol_tuple(const SymbolList &symbols) {
    nb::tuple result = nb::steal<nb::tuple>(
        PyTuple_New(static_cast<Py_ssize_t>(symbols.size)));
    if (!result.is_valid()) throw nb::python_error();
    for (std::size_t index = 0; index < symbols.size; ++index) {
        PyObject *value = PyUnicode_FromString(symbols.values[index]);
        if (value == nullptr) throw nb::python_error();
        PyTuple_SetItem(
            result.ptr(), static_cast<Py_ssize_t>(index), value);
    }
    return result;
}

} // namespace

void register_codecs(nb::module_ &module) {
    std::array<const RegistrationDescriptor *, REGISTRATION_COUNT> ordered{};
    std::unordered_set<std::string> names;
    std::size_t count = 0;
    for (const FamilyBindings *family : families()) {
        if (family == nullptr || family->family == nullptr ||
            family->family[0] == '\0') {
            throw std::runtime_error("native codec family table is invalid");
        }
        for (std::size_t index = 0; index < family->registration_count;
             ++index) {
            const auto &entry = family->registrations[index];
            bool repeated_function = false;
            for (const RegistrationDescriptor *owned : ordered)
                repeated_function =
                    repeated_function ||
                    (owned != nullptr &&
                     owned->function == entry.function);
            if (entry.order >= ordered.size() || entry.function == nullptr ||
                entry.name == nullptr || entry.name[0] == '\0' ||
                repeated_function || ordered[entry.order] != nullptr ||
                !names.emplace(entry.name).second) {
                throw std::runtime_error(
                    "native codec registration ownership is inconsistent");
            }
            ordered[entry.order] = &entry;
            ++count;
        }
    }
    if (count != ordered.size())
        throw std::runtime_error(
            "native codec registration table has an orphaned entry");
    for (const RegistrationDescriptor *entry : ordered) {
        if (entry == nullptr)
            throw std::runtime_error(
                "native codec registration order has a gap");
        entry->function(module);
    }
}

nb::tuple codec_inventory(nb::module_ &module) {
    std::array<const CodecDescriptor *, MANIFEST_COUNT> ordered{};
    std::unordered_set<std::string> ids;
    std::size_t count = 0;
    for (const FamilyBindings *family : families()) {
        for (std::size_t index = 0; index < family->codec_count; ++index) {
            const auto &codec = family->codecs[index];
            if (codec.manifest_order >= ordered.size() ||
                codec.manifest_order == PYTHON_ONLY_MANIFEST_ORDER ||
                codec.id == nullptr || codec.id[0] == '\0' ||
                codec.family == nullptr ||
                std::strcmp(codec.family, family->family) != 0 ||
                ordered[codec.manifest_order] != nullptr ||
                !ids.emplace(codec.id).second) {
                throw std::runtime_error(
                    "native codec inventory ownership is inconsistent");
            }
            ordered[codec.manifest_order] = &codec;
            ++count;
        }
    }
    if (count != NATIVE_CODEC_COUNT ||
        ordered[PYTHON_ONLY_MANIFEST_ORDER] != nullptr) {
        throw std::runtime_error(
            "native codec inventory has an orphaned or extra codec");
    }

    nb::tuple result = nb::steal<nb::tuple>(
        PyTuple_New(static_cast<Py_ssize_t>(NATIVE_CODEC_COUNT)));
    if (!result.is_valid()) throw nb::python_error();
    nb::object mapping_proxy =
        nb::module_::import_("types").attr("MappingProxyType");
    std::size_t output_index = 0;
    for (const CodecDescriptor *codec : ordered) {
        if (codec == nullptr)
            continue;
        validate_symbol_list(module, *codec, "read", codec->read);
        validate_symbol_list(module, *codec, "write", codec->write);
        validate_symbol_list(module, *codec, "inspect", codec->inspect);
        validate_symbol_list(
            module, *codec, "stream_read", codec->stream_read);
        validate_symbol_list(
            module, *codec, "stream_write", codec->stream_write);
        validate_symbol_list(module, *codec, "partial", codec->partial);
        if (codec->read.size == 0 || codec->write.size == 0 ||
            codec->stream_read.size == 0 || codec->stream_write.size == 0) {
            throw std::runtime_error(
                std::string("native codec ") + codec->id +
                " lacks a required operation symbol");
        }

        nb::dict item;
        item["id"] = codec->id;
        item["family"] = codec->family;
        item["read"] = symbol_tuple(codec->read);
        item["write"] = symbol_tuple(codec->write);
        item["inspect"] = symbol_tuple(codec->inspect);
        item["stream_read"] = symbol_tuple(codec->stream_read);
        item["stream_write"] = symbol_tuple(codec->stream_write);
        item["partial"] = symbol_tuple(codec->partial);
        nb::object frozen_item = mapping_proxy(item);
        PyTuple_SetItem(
            result.ptr(), static_cast<Py_ssize_t>(output_index++),
            frozen_item.release().ptr());
    }
    if (output_index != result.size())
        throw std::runtime_error("native codec inventory order has a gap");
    return result;
}

} // namespace sio::bindings
