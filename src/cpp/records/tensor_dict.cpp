// records/tensor_dict.cpp — TensorDict nanobind binding: a dict-like,
// insertion-ordered container of named dtype-erased tensors. Registered once
// and shared by the tensor-container codecs (npy/npz now, HDF5/safetensors
// later). Each __getitem__ / items view is a zero-copy numpy array at the
// entry's restored dtype, with the record itself baked in as the ndarray owner
// so a view keeps the record alive (the sio::view / own_bytes owner pattern,
// generalized to a runtime DLPack dtype). A tensor_dict(arrays, attrs=None)
// factory ingests a dict of numpy/torch CPU arrays for tests. Conventions
// (byte_order/order) are metadata, fixed like GaussianCloud's.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "records/tensor_dict.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// Generic runtime-dtype, zero-copy view of one entry. `owner` (the TensorDict
// Python object) is baked into the ndarray so the array keeps the record alive
// even after the caller drops its own reference — the canonical owner-carrying
// accessor from io/common.hpp, extended to a runtime dlpack dtype. Passing the
// owner directly (rather than rv_policy::reference_internal) is what lets a
// container of views — items() — keep every element alive individually.
// strides=nullptr => C-contiguous.
nb::ndarray<nb::numpy> view_entry(nb::handle owner, const TensorEntry &e) {
    const DTypeInfo &info = dtype_info(e.dtype);
    static uint8_t sentinel = 0;  // never hand numpy a null base pointer for empty arrays
    void *p = e.bytes.empty() ? &sentinel : const_cast<uint8_t *>(e.bytes.data());
    return nb::ndarray<nb::numpy>(p, e.shape.size(), e.shape.data(), owner,
                                  /*strides=*/nullptr,
                                  nb::dlpack::dtype{info.code, info.bits, 1});
}

// dtype-ERASED input: accepts any supported dtype / framework (numpy, torch),
// and converts a non-C-contiguous source via a temporary copy (nanobind's
// c_contig conversion). Scalar is void, so data() is a raw byte pointer.
using anyarr = nb::ndarray<nb::c_contig, nb::device::cpu>;

TensorDict make_td(nb::dict arrays, std::optional<nb::dict> attrs) {
    TensorDict t;
    for (auto [k, v] : arrays) {  // Python dict iteration preserves insertion order
        auto name = nb::cast<std::string>(k);
        anyarr a;
        if (!nb::try_cast<anyarr>(v, a))
            throw nb::type_error(("tensor_dict: value for '" + name +
                                  "' is not a CPU array (numpy/torch ndarray expected)")
                                     .c_str());
        const DTypeInfo *info = dtype_from_dlpack(a.dtype());
        if (!info)
            throw std::invalid_argument(
                "tensor_dict: unsupported dtype for '" + name +
                "' (supported: bool, int8..64, uint8..64, float16/32/64)");
        std::vector<size_t> shape(a.shape_ptr(), a.shape_ptr() + a.ndim());
        TensorEntry &e = t.add(std::move(name), info->tag, std::move(shape));
        if (!e.bytes.empty()) std::memcpy(e.bytes.data(), a.data(), e.bytes.size());
    }
    if (attrs)
        for (auto [k, v] : *attrs)
            t.attrs.emplace_back(nb::cast<std::string>(k), nb::cast<std::string>(v));
    return t;
}

}  // namespace

void register_tensor_dict(nb::module_ &m) {
    nb::class_<TensorDict>(m, "TensorDict")
        .def("__len__", [](const TensorDict &t) { return t.size(); })
        .def("__contains__",
             [](const TensorDict &t, const std::string &k) { return t.find(k) != nullptr; })
        .def("keys",
             [](const TensorDict &t) {
                 std::vector<std::string> ks;
                 ks.reserve(t.entries.size());
                 for (const auto &e : t.entries) ks.push_back(e.name);
                 return ks;
             })
        .def("__iter__",
             [](const TensorDict &t) {  // iterate keys, dict-like
                 nb::list ks;
                 // size-aware ctor (PyUnicode_FromStringAndSize) so names with an
                 // embedded NUL agree with keys()/items() instead of truncating
                 for (const auto &e : t.entries) ks.append(nb::str(e.name.data(), e.name.size()));
                 return nb::iter(ks);  // iterator holds the snapshot list alive
             })
        .def("__getitem__",
             [](nb::handle_t<TensorDict> self, const std::string &k) {
                 const TensorDict &t = nb::cast<const TensorDict &>(self);
                 const TensorEntry *e = t.find(k);
                 if (!e) throw nb::key_error(k.c_str());
                 return view_entry(self, *e);
             })
        .def("items",
             [](nb::handle_t<TensorDict> self) {
                 const TensorDict &t = nb::cast<const TensorDict &>(self);
                 std::vector<std::pair<std::string, nb::ndarray<nb::numpy>>> out;
                 out.reserve(t.entries.size());
                 for (const auto &e : t.entries) out.emplace_back(e.name, view_entry(self, e));
                 return out;
             })
        .def("dtype_of",
             [](const TensorDict &t, const std::string &k) {  // introspect without a view
                 const TensorEntry *e = t.find(k);
                 if (!e) throw nb::key_error(k.c_str());
                 return dtype_info(e->dtype).name;
             })
        .def("shape_of",
             [](const TensorDict &t, const std::string &k) {
                 const TensorEntry *e = t.find(k);
                 if (!e) throw nb::key_error(k.c_str());
                 return e->shape;  // std::vector<size_t> -> Python list
             })
        .def_prop_ro("attrs",
                     [](const TensorDict &t) {
                         nb::dict d;
                         // size-aware ctor so keys/values with an embedded NUL are
                         // preserved (matching keys()/items()), not truncated at '\0'
                         for (const auto &kv : t.attrs)
                             d[nb::str(kv.first.data(), kv.first.size())] =
                                 nb::str(kv.second.data(), kv.second.size());
                         return d;
                     })
        // conventions (metadata; the canonical form readers normalize into,
        // fixed like GaussianCloud's quaternion_order):
        .def_prop_ro("byte_order", [](const TensorDict &) { return "little"; })
        .def_prop_ro("order", [](const TensorDict &) { return "C"; })
        .def("__repr__", [](const TensorDict &t) {
            std::string s = "<TensorDict n=" + std::to_string(t.size()) + " [";
            const size_t cap = 8;  // truncate long dicts
            for (size_t i = 0; i < t.entries.size() && i < cap; i++) {
                const TensorEntry &e = t.entries[i];
                if (i) s += ", ";
                s += e.name + " " + dtype_info(e.dtype).name + "(";
                for (size_t d = 0; d < e.shape.size(); d++) {
                    if (d) s += ",";
                    s += std::to_string(e.shape[d]);
                }
                s += ")";
            }
            if (t.entries.size() > cap) s += ", ...";
            s += "]>";
            return s;
        });

    m.def("tensor_dict", &make_td, "arrays"_a, "attrs"_a = nb::none(),
          "Build a TensorDict from a dict of arrays (numpy/torch, any of bool, int8..64, "
          "uint8..64, float16/32/64) plus optional str->str attrs; insertion order is preserved.");
}
