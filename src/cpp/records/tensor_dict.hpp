// records/tensor_dict.hpp — a dict-like container of named, dtype-erased
// tensors (raw bytes + a small dtype tag) plus ordered string attrs. One
// untemplated record stores any of the 12 supported numpy dtypes (bool,
// int8..64, uint8..64, float16/32/64) as per-entry contiguous, native-endian,
// C-order byte buffers, each zero-copy-viewable at its restored dtype (a
// per-name SoA — every tensor is its own contiguous block, like GaussianCloud's
// per-field vectors).
//
// This is the shared memory representation the tensor-container codecs decode
// into (.npy is a single array; .npz / later HDF5 / safetensors hold many), so
// the dtype machinery — the DType enum, the kDTypes source-of-truth table, and
// the DLPack/descr mappings — lives here in the header where every codec picks
// it up by include (the gc_deg_from_rest pattern in gaussian_cloud.hpp).
//
// Canonical form (what codecs must produce): bytes are always native
// little-endian and C-contiguous; dtype is one of the 12-row table; foreign
// byte order / Fortran order is normalized on decode. The fixed conventions
// byte_order="little" / order="C" record that.
#pragma once

#include <cassert>
#include <string_view>
#include <unordered_map>
#include <utility>

#include "io/common.hpp"  // nb alias; <vector>/<string>/<cstdint>/<cstring>/<stdexcept>

namespace sio {

// The 12 numpy dtypes this record round-trips. Values are explicit so codecs
// may serialize the tag; do not renumber.
enum class DType : uint8_t {
    Bool = 0, I8, I16, I32, I64, U8, U16, U32, U64, F16, F32, F64
};

// One row of the single source of truth mapping DType <-> DLPack {code,bits}
// <-> numpy descr ("<f4", "|b1", ...) <-> numpy name. `code` is a DLPack
// dtype_code (Int=0, UInt=1, Float=2, Bool=6 — nanobind ndarray.h).
struct DTypeInfo {
    DType tag;
    uint8_t code;
    uint8_t bits;
    uint8_t itemsize;
    const char *npy_descr;
    const char *name;
};

// POSITIONAL aggregate initialization (MSVC /std:c++17 has no designated
// initializers). Field order is {tag, code, bits, itemsize, npy_descr, name};
// the DLPack {code,bits,lanes} brace order elsewhere must match ndarray.h.
inline constexpr DTypeInfo kDTypes[12] = {
    {DType::Bool, 6, 8, 1, "|b1", "bool"},
    {DType::I8, 0, 8, 1, "|i1", "int8"},
    {DType::I16, 0, 16, 2, "<i2", "int16"},
    {DType::I32, 0, 32, 4, "<i4", "int32"},
    {DType::I64, 0, 64, 8, "<i8", "int64"},
    {DType::U8, 1, 8, 1, "|u1", "uint8"},
    {DType::U16, 1, 16, 2, "<u2", "uint16"},
    {DType::U32, 1, 32, 4, "<u4", "uint32"},
    {DType::U64, 1, 64, 8, "<u8", "uint64"},
    {DType::F16, 2, 16, 2, "<f2", "float16"},
    {DType::F32, 2, 32, 4, "<f4", "float32"},
    {DType::F64, 2, 64, 8, "<f8", "float64"},
};

// Look up a table row by a DType known to be valid: every DType value in this
// process originates from a kDTypes row (via dtype_from_dlpack / dtype_from_descr
// / dtype_from_tag), so this is always in bounds. A raw byte read off disk MUST
// NOT be cast to DType and passed here — route it through dtype_from_tag, which
// bounds-checks. The assert documents that invariant in debug builds.
inline const DTypeInfo &dtype_info(DType t) {
    assert(static_cast<size_t>(t) < std::size(kDTypes) &&
           "dtype_info: out-of-range DType — deserialized tags must go through dtype_from_tag");
    return kDTypes[static_cast<size_t>(t)];
}

// Map an imported array's DLPack dtype back to a table row. Only lanes==1 is
// supported; returns nullptr for anything outside the 12 rows (complex,
// bfloat16, float8, ...), which the caller turns into a typed error.
inline const DTypeInfo *dtype_from_dlpack(nb::dlpack::dtype d) {
    if (d.lanes != 1) return nullptr;
    for (const auto &info : kDTypes)
        if (info.code == d.code && info.bits == d.bits) return &info;
    return nullptr;
}

// Map a numpy header descr ("<f4", "|u1", ">i8", "=f8", "f4", ...) to a table
// row, ignoring any leading byte-order char (the .npy codec inspects
// '<'/'>'/'='/'|' itself to decide whether to byteswap the payload). Returns
// nullptr when the kind+size is unsupported (structured, unicode, object, ...).
inline const DTypeInfo *dtype_from_descr(std::string_view descr) {
    if (!descr.empty() && (descr.front() == '<' || descr.front() == '>' ||
                           descr.front() == '=' || descr.front() == '|'))
        descr.remove_prefix(1);
    for (const auto &info : kDTypes) {
        std::string_view canon(info.npy_descr);
        canon.remove_prefix(1);  // drop the table's stored byte-order char
        if (canon == descr) return &info;
    }
    return nullptr;
}

// Map a raw serialized tag byte (a persisted DType enum value — the enum notes
// "codecs may serialize the tag") back to a table row. This is the checked
// restore seam every deserializer MUST use: any byte outside the 12 rows yields
// nullptr (mirroring dtype_from_dlpack / dtype_from_descr's contract), which the
// caller turns into a typed error — instead of static_cast<DType>(byte) driving
// an out-of-bounds read of kDTypes in dtype_info.
inline const DTypeInfo *dtype_from_tag(uint8_t raw) {
    return static_cast<size_t>(raw) < std::size(kDTypes) ? &kDTypes[raw] : nullptr;
}

}  // namespace sio

// One named array: dtype erased to a raw, C-contiguous, native-endian byte
// buffer + a DType tag. Each entry owns its own contiguous block.
struct TensorEntry {
    std::string name;
    sio::DType dtype = sio::DType::U8;
    std::vector<size_t> shape;   // ndim >= 0; 0-d scalar and zero-size dims are legal
    std::vector<uint8_t> bytes;  // len == prod(shape) * itemsize, native-endian, C-order

    size_t num_elems() const {  // prod(shape); 1 for a 0-d scalar
        size_t n = 1;
        for (size_t d : shape) n *= d;
        return n;
    }
};

// Append-only, insertion-ordered dict of tensors + an ordered str->str attrs
// side channel (HDF5 attributes / safetensors __metadata__). Member order is
// meaningful — npz / safetensors want byte-deterministic round-trips.
struct TensorDict {
    std::vector<TensorEntry> entries;
    std::vector<std::pair<std::string, std::string>> attrs;
    std::unordered_map<std::string, size_t> index;  // name -> entries index, O(1) find

    size_t size() const { return entries.size(); }

    const TensorEntry *find(const std::string &name) const {
        auto it = index.find(name);
        return it == index.end() ? nullptr : &entries[it->second];
    }

    // Append a new entry, allocating a zero-filled bytes buffer of
    // prod(shape) * itemsize for the codec to memcpy / inflate straight into
    // (via the returned reference's bytes.data()). This is the single anti-OOB
    // seam: the element-count and byte-size multiplies are overflow-checked so a
    // hostile npz / safetensors header cannot wrap size_t, under-allocate, and
    // drive a heap write past the buffer (the crafted-64-bit-length lesson from
    // spz.cpp). Throws std::invalid_argument on a duplicate name (readers must
    // reject two members that map to the same key, never silently overwrite).
    TensorEntry &add(std::string name, sio::DType dt, std::vector<size_t> shape) {
        if (index.count(name))
            throw std::invalid_argument("TensorDict: duplicate tensor name '" + name + "'");
        const size_t itemsize = sio::dtype_info(dt).itemsize;
        size_t elems = 1;
        for (size_t d : shape) {
            if (d != 0 && elems > SIZE_MAX / d)
                throw std::invalid_argument("TensorDict: tensor '" + name +
                                            "' element count overflows size_t");
            elems *= d;
        }
        if (itemsize != 0 && elems > SIZE_MAX / itemsize)
            throw std::invalid_argument("TensorDict: tensor '" + name +
                                        "' byte size overflows size_t");
        const size_t idx = entries.size();
        TensorEntry e;
        e.name = name;
        e.dtype = dt;
        e.shape = std::move(shape);
        e.bytes.resize(elems * itemsize);  // zero-filled
        entries.push_back(std::move(e));   // push first: exception-safe vs the index
        index.emplace(entries[idx].name, idx);
        return entries[idx];
    }
};
