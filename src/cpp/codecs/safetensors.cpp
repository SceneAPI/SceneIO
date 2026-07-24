// codecs/safetensors.cpp — deterministic safetensors reader/writer over the
// existing TensorDict record. The public path maps the file and returns
// read-only tensor views whose TensorDict retains an uncloseable Py_buffer
// owner. Unsupported dtypes are rejected rather than converted.
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "records/tensor_dict.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

using Json = nlohmann::ordered_json;
constexpr uint64_t kMaxHeaderSize = 100'000'000;

struct TensorLayout {
    std::string name;
    DType dtype;
    std::vector<size_t> shape;
    size_t begin = 0;
    size_t end = 0;
};

struct SafeLayout {
    size_t data_offset = 0;
    size_t payload_size = 0;
    std::vector<TensorLayout> tensors;
    std::vector<std::pair<std::string, std::string>> attrs;
};

struct SelectedTensor {
    const TensorLayout *tensor = nullptr;
    std::vector<size_t> shape;
    size_t begin = 0;
    size_t end = 0;
};

uint64_t read_u64_le(const uint8_t *data) {
    uint64_t value = 0;
    for (size_t i = 0; i < 8; i++)
        value |= static_cast<uint64_t>(data[i]) << (i * 8);
    return value;
}

void write_u64_le(uint64_t value, char *out) {
    for (size_t i = 0; i < 8; i++)
        out[i] = static_cast<char>((value >> (i * 8)) & 0xff);
}

const DTypeInfo *dtype_from_safetensors(const std::string &name) {
    if (name == "BOOL") return &dtype_info(DType::Bool);
    if (name == "I8") return &dtype_info(DType::I8);
    if (name == "I16") return &dtype_info(DType::I16);
    if (name == "I32") return &dtype_info(DType::I32);
    if (name == "I64") return &dtype_info(DType::I64);
    if (name == "U8") return &dtype_info(DType::U8);
    if (name == "U16") return &dtype_info(DType::U16);
    if (name == "U32") return &dtype_info(DType::U32);
    if (name == "U64") return &dtype_info(DType::U64);
    if (name == "F16") return &dtype_info(DType::F16);
    if (name == "F32") return &dtype_info(DType::F32);
    if (name == "F64") return &dtype_info(DType::F64);
    return nullptr;
}

const char *dtype_to_safetensors(DType dtype) {
    switch (dtype) {
        case DType::Bool: return "BOOL";
        case DType::I8: return "I8";
        case DType::I16: return "I16";
        case DType::I32: return "I32";
        case DType::I64: return "I64";
        case DType::U8: return "U8";
        case DType::U16: return "U16";
        case DType::U32: return "U32";
        case DType::U64: return "U64";
        case DType::F16: return "F16";
        case DType::F32: return "F32";
        case DType::F64: return "F64";
    }
    throw std::logic_error("safetensors: unhandled TensorDict dtype");
}

// Match safetensors 0.8's canonical enum ordering. Its writer sorts by
// descending dtype alignment/order, then tensor name.
int dtype_sort_rank(DType dtype) {
    switch (dtype) {
        case DType::Bool: return 0;
        case DType::U8: return 4;
        case DType::I8: return 5;
        case DType::I16: return 11;
        case DType::U16: return 12;
        case DType::F16: return 13;
        case DType::I32: return 15;
        case DType::U32: return 16;
        case DType::F32: return 17;
        case DType::F64: return 19;
        case DType::I64: return 20;
        case DType::U64: return 21;
    }
    throw std::logic_error("safetensors: unhandled TensorDict dtype");
}

Json parse_json_without_duplicates(const uint8_t *begin, const uint8_t *end) {
    std::vector<std::unordered_set<std::string>> object_keys;
    auto callback = [&object_keys](
                        int, Json::parse_event_t event, Json &parsed) {
        if (event == Json::parse_event_t::object_start) {
            object_keys.emplace_back();
        } else if (event == Json::parse_event_t::key) {
            if (object_keys.empty())
                throw std::invalid_argument(
                    "safetensors: malformed JSON object");
            const std::string &key = parsed.get_ref<const std::string &>();
            if (!object_keys.back().insert(key).second)
                throw std::invalid_argument(
                    "safetensors: duplicate JSON key '" + key + "'");
        } else if (event == Json::parse_event_t::object_end) {
            if (object_keys.empty())
                throw std::invalid_argument(
                    "safetensors: malformed JSON object");
            object_keys.pop_back();
        }
        return true;
    };
    try {
        return Json::parse(begin, end, callback, true, false);
    } catch (const std::invalid_argument &) {
        throw;
    } catch (const std::exception &error) {
        throw std::invalid_argument(
            std::string("safetensors: invalid JSON header: ") + error.what());
    }
}

size_t unsigned_size(const Json &value, const std::string &what) {
    if (!value.is_number_unsigned())
        throw std::invalid_argument("safetensors: " + what +
                                    " must be an unsigned integer");
    const uint64_t raw = value.get<uint64_t>();
    if (raw > static_cast<uint64_t>(SIZE_MAX))
        throw std::invalid_argument("safetensors: " + what +
                                    " exceeds size_t");
    return static_cast<size_t>(raw);
}

SafeLayout parse_layout(const uint8_t *data, size_t size) {
    if (size < 8)
        throw std::invalid_argument(
            "safetensors: file is smaller than the 8-byte header length");
    const uint64_t header64 = read_u64_le(data);
    if (header64 > kMaxHeaderSize)
        throw std::invalid_argument(
            "safetensors: header exceeds the 100,000,000-byte limit");
    if (header64 > static_cast<uint64_t>(SIZE_MAX - 8))
        throw std::invalid_argument("safetensors: header length overflows size_t");
    const size_t header_size = static_cast<size_t>(header64);
    const size_t data_offset = 8 + header_size;
    if (header_size == 0 || data_offset > size)
        throw std::invalid_argument("safetensors: truncated JSON header");
    if (data[8] != static_cast<uint8_t>('{'))
        throw std::invalid_argument(
            "safetensors: JSON header must begin with '{'");

    Json root = parse_json_without_duplicates(data + 8, data + data_offset);
    if (!root.is_object())
        throw std::invalid_argument(
            "safetensors: JSON header root must be an object");

    SafeLayout layout;
    layout.data_offset = data_offset;
    layout.payload_size = size - data_offset;
    for (auto it = root.begin(); it != root.end(); ++it) {
        const std::string name = it.key();
        const Json &descriptor = it.value();
        if (name == "__metadata__") {
            if (!descriptor.is_object())
                throw std::invalid_argument(
                    "safetensors: __metadata__ must be a string-to-string object");
            for (auto attr = descriptor.begin(); attr != descriptor.end();
                 ++attr) {
                if (!attr.value().is_string())
                    throw std::invalid_argument(
                        "safetensors: __metadata__ values must be strings");
                layout.attrs.emplace_back(
                    attr.key(), attr.value().get<std::string>());
            }
            continue;
        }
        if (!descriptor.is_object() || descriptor.size() != 3 ||
            !descriptor.contains("dtype") ||
            !descriptor.contains("shape") ||
            !descriptor.contains("data_offsets"))
            throw std::invalid_argument(
                "safetensors: tensor '" + name +
                "' must contain exactly dtype, shape, and data_offsets");
        if (!descriptor["dtype"].is_string())
            throw std::invalid_argument("safetensors: tensor '" + name +
                                        "' dtype must be a string");
        const std::string dtype_name =
            descriptor["dtype"].get<std::string>();
        const DTypeInfo *dtype = dtype_from_safetensors(dtype_name);
        if (!dtype)
            throw std::invalid_argument(
                "safetensors: tensor '" + name + "' uses unsupported dtype '" +
                dtype_name +
                "' (supported: BOOL, I8/I16/I32/I64, U8/U16/U32/U64, "
                "F16/F32/F64)");

        const Json &shape_json = descriptor["shape"];
        if (!shape_json.is_array())
            throw std::invalid_argument("safetensors: tensor '" + name +
                                        "' shape must be an array");
        std::vector<size_t> shape;
        shape.reserve(shape_json.size());
        for (size_t axis = 0; axis < shape_json.size(); axis++)
            shape.push_back(unsigned_size(
                shape_json[axis], "tensor '" + name + "' shape dimension"));

        const Json &offsets = descriptor["data_offsets"];
        if (!offsets.is_array() || offsets.size() != 2)
            throw std::invalid_argument(
                "safetensors: tensor '" + name +
                "' data_offsets must contain two integers");
        const size_t begin =
            unsigned_size(offsets[0], "tensor '" + name + "' start offset");
        const size_t end =
            unsigned_size(offsets[1], "tensor '" + name + "' end offset");
        if (begin > end || end > layout.payload_size)
            throw std::invalid_argument(
                "safetensors: tensor '" + name +
                "' offsets are outside the payload");
        const size_t expected =
            TensorDict::checked_size(name, dtype->tag, shape);
        if (end - begin != expected)
            throw std::invalid_argument(
                "safetensors: tensor '" + name +
                "' byte range disagrees with dtype and shape");
        layout.tensors.push_back(
            TensorLayout{name, dtype->tag, std::move(shape), begin, end});
    }

    std::vector<const TensorLayout *> ordered;
    ordered.reserve(layout.tensors.size());
    for (const TensorLayout &tensor : layout.tensors)
        ordered.push_back(&tensor);
    std::sort(
        ordered.begin(), ordered.end(),
        [](const TensorLayout *left, const TensorLayout *right) {
            if (left->begin != right->begin)
                return left->begin < right->begin;
            if (left->end != right->end) return left->end < right->end;
            return left->name < right->name;
        });
    size_t cursor = 0;
    for (const TensorLayout *tensor : ordered) {
        if (tensor->begin != cursor) {
            const char *kind = tensor->begin < cursor ? "overlap" : "gap";
            throw std::invalid_argument(
                std::string("safetensors: tensor payload contains an offset ") +
                kind + " at tensor '" + tensor->name + "'");
        }
        cursor = tensor->end;
    }
    if (cursor != layout.payload_size)
        throw std::invalid_argument(
            "safetensors: tensor offsets do not cover the complete payload");
    return layout;
}

const TensorLayout &find_tensor(const SafeLayout &layout,
                                const std::string &name) {
    for (const TensorLayout &tensor : layout.tensors)
        if (tensor.name == name) return tensor;
    throw std::invalid_argument("safetensors: tensor '" + name +
                                "' was not found");
}

std::vector<SelectedTensor> select_tensors(
    const SafeLayout &layout, const std::vector<std::string> &names,
    const std::vector<std::tuple<std::string, size_t, size_t>> &slices) {
    if (!names.empty() && !slices.empty())
        throw std::invalid_argument(
            "safetensors: tensor names and tensor slices are mutually exclusive");
    std::vector<SelectedTensor> selected;
    if (names.empty() && slices.empty()) {
        selected.reserve(layout.tensors.size());
        for (const TensorLayout &tensor : layout.tensors)
            selected.push_back(
                SelectedTensor{&tensor, tensor.shape, tensor.begin, tensor.end});
        return selected;
    }

    std::unordered_set<std::string> seen;
    if (!names.empty()) {
        selected.reserve(names.size());
        for (const std::string &name : names) {
            if (!seen.insert(name).second)
                throw std::invalid_argument(
                    "safetensors: duplicate selected tensor '" + name + "'");
            const TensorLayout &tensor = find_tensor(layout, name);
            selected.push_back(
                SelectedTensor{&tensor, tensor.shape, tensor.begin, tensor.end});
        }
        return selected;
    }

    selected.reserve(slices.size());
    for (const auto &[name, start, stop] : slices) {
        if (!seen.insert(name).second)
            throw std::invalid_argument(
                "safetensors: duplicate sliced tensor '" + name + "'");
        const TensorLayout &tensor = find_tensor(layout, name);
        if (tensor.shape.empty())
            throw std::invalid_argument(
                "safetensors: scalar tensor '" + name +
                "' has no leading axis to slice");
        if (start >= stop || stop > tensor.shape[0])
            throw std::invalid_argument(
                "safetensors: leading-axis slice for tensor '" + name +
                "' is outside its shape");
        const size_t leading = tensor.shape[0];
        if (leading == 0)
            throw std::invalid_argument(
                "safetensors: empty tensor '" + name + "' cannot be sliced");
        const size_t row_bytes = (tensor.end - tensor.begin) / leading;
        if (row_bytes != 0 &&
            (start > SIZE_MAX / row_bytes || stop > SIZE_MAX / row_bytes))
            throw std::invalid_argument(
                "safetensors: tensor slice byte offset overflows size_t");
        std::vector<size_t> shape = tensor.shape;
        shape[0] = stop - start;
        selected.push_back(SelectedTensor{
            &tensor,
            std::move(shape),
            tensor.begin + start * row_bytes,
            tensor.begin + stop * row_bytes,
        });
    }
    return selected;
}

bool can_borrow(const uint8_t *payload,
                const std::vector<SelectedTensor> &selected) {
    if (!host_is_le()) return false;
    for (const SelectedTensor &item : selected) {
        const size_t alignment = dtype_info(item.tensor->dtype).itemsize;
        const uintptr_t address =
            reinterpret_cast<uintptr_t>(payload + item.begin);
        if (alignment > 1 && address % alignment != 0) return false;
    }
    return true;
}

void populate_tensor_dict(
    TensorDict &result, const SafeLayout &layout,
    const std::vector<SelectedTensor> &selected, const uint8_t *payload,
    bool borrowed) {
    result.attrs = layout.attrs;
    for (const SelectedTensor &item : selected) {
        const size_t byte_size = item.end - item.begin;
        const uint8_t *source = payload + item.begin;
        if (borrowed) {
            result.add_borrowed(
                item.tensor->name, item.tensor->dtype, item.shape, source,
                byte_size);
        } else {
            TensorEntry &entry = result.add(
                item.tensor->name, item.tensor->dtype, item.shape);
            if (byte_size != 0)
                std::memcpy(entry.bytes.data(), source, byte_size);
        }
    }
}

TensorDict read_copy(
    nb::handle source, const std::vector<std::string> &names,
    const std::vector<std::tuple<std::string, size_t, size_t>> &slices) {
    if (!host_is_le())
        throw std::invalid_argument(
            "safetensors: big-endian hosts are unsupported");
    ByteView data(source);
    TensorDict result;
    {
        nb::gil_scoped_release release;
        SafeLayout layout = parse_layout(data.data(), data.size());
        const std::vector<SelectedTensor> selected =
            select_tensors(layout, names, slices);
        populate_tensor_dict(result, layout, selected,
                             data.data() + layout.data_offset, false);
    }
    return result;
}

TensorDict read_view(
    nb::handle source, const std::vector<std::string> &names,
    const std::vector<std::tuple<std::string, size_t, size_t>> &slices) {
    if (!host_is_le())
        throw std::invalid_argument(
            "safetensors: big-endian hosts are unsupported");
    ByteView data(source);
    TensorDict result;
    bool borrowed = false;
    {
        nb::gil_scoped_release release;
        SafeLayout layout = parse_layout(data.data(), data.size());
        const std::vector<SelectedTensor> selected =
            select_tensors(layout, names, slices);
        const uint8_t *payload = data.data() + layout.data_offset;
        borrowed = can_borrow(payload, selected);
        populate_tensor_dict(result, layout, selected, payload, borrowed);
    }
    if (borrowed) {
        result.backing_data = data.data();
        result.backing_size = data.size();
        result.backing_owner = data.pin();
    }
    return result;
}

TensorDict read_safetensors(nb::handle source) {
    return read_copy(source, {}, {});
}

TensorDict read_safetensors_tensors(
    nb::handle source, const std::vector<std::string> &names) {
    if (names.empty())
        throw std::invalid_argument(
            "safetensors: selected tensor list must not be empty");
    return read_copy(source, names, {});
}

TensorDict read_safetensors_slices(
    nb::handle source,
    const std::vector<std::tuple<std::string, size_t, size_t>> &slices) {
    if (slices.empty())
        throw std::invalid_argument(
            "safetensors: selected tensor slices must not be empty");
    return read_copy(source, {}, slices);
}

TensorDict read_safetensors_view(nb::handle source) {
    return read_view(source, {}, {});
}

TensorDict read_safetensors_tensors_view(
    nb::handle source, const std::vector<std::string> &names) {
    if (names.empty())
        throw std::invalid_argument(
            "safetensors: selected tensor list must not be empty");
    return read_view(source, names, {});
}

TensorDict read_safetensors_slices_view(
    nb::handle source,
    const std::vector<std::tuple<std::string, size_t, size_t>> &slices) {
    if (slices.empty())
        throw std::invalid_argument(
            "safetensors: selected tensor slices must not be empty");
    return read_view(source, {}, slices);
}

nb::tuple inspect_safetensors(nb::handle source) {
    ByteView data(source);
    SafeLayout layout;
    {
        nb::gil_scoped_release release;
        layout = parse_layout(data.data(), data.size());
    }
    nb::list arrays;
    for (const TensorLayout &tensor : layout.tensors) {
        arrays.append(nb::make_tuple(
            nb::str(tensor.name.data(), tensor.name.size()), tensor.shape,
            dtype_info(tensor.dtype).name));
    }
    nb::dict attrs;
    for (const auto &[key, value] : layout.attrs)
        attrs[nb::str(key.data(), key.size())] =
            nb::str(value.data(), value.size());
    return nb::make_tuple(arrays, attrs);
}

struct PreparedWrite {
    std::array<char, 8> prefix{};
    std::string header;
    std::vector<const TensorEntry *> tensors;
    size_t total_size = 0;
};

PreparedWrite prepare_write(const TensorDict &tensors) {
    if (!host_is_le())
        throw std::invalid_argument(
            "safetensors: big-endian hosts are unsupported");
    PreparedWrite prepared;
    prepared.tensors.reserve(tensors.entries.size());
    for (const TensorEntry &entry : tensors.entries) {
        if (entry.name == "__metadata__")
            throw std::invalid_argument(
                "safetensors: '__metadata__' is reserved and cannot be a tensor name");
        const size_t expected =
            TensorDict::checked_size(entry.name, entry.dtype, entry.shape);
        if (entry.size_bytes() != expected)
            throw std::invalid_argument(
                "safetensors: tensor '" + entry.name +
                "' storage disagrees with dtype and shape");
        prepared.tensors.push_back(&entry);
    }
    std::sort(
        prepared.tensors.begin(), prepared.tensors.end(),
        [](const TensorEntry *left, const TensorEntry *right) {
            const int left_rank = dtype_sort_rank(left->dtype);
            const int right_rank = dtype_sort_rank(right->dtype);
            if (left_rank != right_rank) return left_rank > right_rank;
            return left->name < right->name;
        });

    Json root = Json::object();
    if (!tensors.attrs.empty()) {
        std::vector<const std::pair<std::string, std::string> *> attrs;
        attrs.reserve(tensors.attrs.size());
        for (const auto &attr : tensors.attrs) attrs.push_back(&attr);
        std::sort(
            attrs.begin(), attrs.end(),
            [](const auto *left, const auto *right) {
                return left->first < right->first;
            });
        Json metadata = Json::object();
        std::string previous;
        bool have_previous = false;
        for (const auto *attr : attrs) {
            if (have_previous && attr->first == previous)
                throw std::invalid_argument(
                    "safetensors: duplicate metadata key '" + attr->first +
                    "'");
            metadata[attr->first] = attr->second;
            previous = attr->first;
            have_previous = true;
        }
        root["__metadata__"] = std::move(metadata);
    }

    size_t offset = 0;
    for (const TensorEntry *entry : prepared.tensors) {
        if (entry->size_bytes() > SIZE_MAX - offset)
            throw std::invalid_argument(
                "safetensors: tensor payload size overflows size_t");
        const size_t end = offset + entry->size_bytes();
        Json descriptor = Json::object();
        descriptor["dtype"] = dtype_to_safetensors(entry->dtype);
        descriptor["shape"] = entry->shape;
        descriptor["data_offsets"] = Json::array({offset, end});
        root[entry->name] = std::move(descriptor);
        offset = end;
    }
    try {
        prepared.header = root.dump();
    } catch (const std::exception &error) {
        throw std::invalid_argument(
            std::string("safetensors: metadata is not valid UTF-8 JSON: ") +
            error.what());
    }
    while (prepared.header.size() % 8 != 0) prepared.header.push_back(' ');
    if (prepared.header.size() > kMaxHeaderSize)
        throw std::invalid_argument(
            "safetensors: header exceeds the 100,000,000-byte limit");
    if (prepared.header.size() > SIZE_MAX - 8 ||
        offset > SIZE_MAX - 8 - prepared.header.size())
        throw std::invalid_argument(
            "safetensors: output size overflows size_t");
    prepared.total_size = 8 + prepared.header.size() + offset;
    write_u64_le(static_cast<uint64_t>(prepared.header.size()),
                 prepared.prefix.data());
    return prepared;
}

nb::bytes write_safetensors(const TensorDict &tensors) {
    PreparedWrite prepared;
    {
        nb::gil_scoped_release release;
        prepared = prepare_write(tensors);
    }
    std::string output;
    const bool streamed =
        emit_file_chunk(prepared.prefix.data(), prepared.prefix.size());
    if (streamed) {
        emit_file_chunk(prepared.header.data(), prepared.header.size());
        for (const TensorEntry *tensor : prepared.tensors)
            if (tensor->size_bytes() != 0)
                emit_file_chunk(
                    reinterpret_cast<const char *>(tensor->data()),
                    tensor->size_bytes());
    } else {
        nb::gil_scoped_release release;
        output.reserve(prepared.total_size);
        output.append(prepared.prefix.data(), prepared.prefix.size());
        output.append(prepared.header);
        for (const TensorEntry *tensor : prepared.tensors)
            if (tensor->size_bytes() != 0)
                output.append(
                    reinterpret_cast<const char *>(tensor->data()),
                    tensor->size_bytes());
    }
    if (streamed) return nb::bytes("", 0);
    return nb::bytes(output.data(), output.size());
}

}  // namespace

void register_safetensors(nb::module_ &m) {
    m.def("_inspect_safetensors", &inspect_safetensors, "data"_a,
          "Return safetensors array metadata without decoding payload tensors.");
    m.def("read_safetensors", &read_safetensors, "data"_a,
          "Decode safetensors into an owned TensorDict.");
    m.def("read_safetensors_view", &read_safetensors_view, "data"_a,
          "Decode safetensors into read-only mapped TensorDict views when aligned.");
    m.def("read_safetensors_tensors", &read_safetensors_tensors, "data"_a,
          "names"_a, "Copy only selected safetensors tensors.");
    m.def("read_safetensors_tensors_view", &read_safetensors_tensors_view,
          "data"_a, "names"_a,
          "Return read-only mapped views of selected safetensors tensors.");
    m.def("read_safetensors_slices", &read_safetensors_slices, "data"_a,
          "slices"_a, "Copy selected leading-axis safetensors slices.");
    m.def("read_safetensors_slices_view", &read_safetensors_slices_view,
          "data"_a, "slices"_a,
          "Return mapped selected leading-axis safetensors slices.");
    m.def("write_safetensors", &write_safetensors, "tensors"_a,
          "Encode a TensorDict as deterministic safetensors bytes or stream it "
          "through the active file sink.");
}
