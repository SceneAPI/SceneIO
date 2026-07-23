// Shared helpers for the sceneio nanobind core: endianness, little-endian
// binary read/write, and the zero-copy "own_array" ndarray factory.
#pragma once

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <vector>

namespace nb = nanobind;

namespace sio {

inline bool valid_utf8(std::string_view text) {
    const auto *p = reinterpret_cast<const unsigned char *>(text.data());
    const size_t n = text.size();
    size_t i = 0;
    while (i < n) {
        const unsigned char c = p[i++];
        if (c <= 0x7f) continue;
        if (c >= 0xc2 && c <= 0xdf) {
            if (i >= n || (p[i++] & 0xc0) != 0x80) return false;
            continue;
        }
        if (c >= 0xe0 && c <= 0xef) {
            if (i + 1 >= n) return false;
            const unsigned char c1 = p[i++], c2 = p[i++];
            if ((c1 & 0xc0) != 0x80 || (c2 & 0xc0) != 0x80) return false;
            if ((c == 0xe0 && c1 < 0xa0) || (c == 0xed && c1 >= 0xa0)) return false;
            continue;
        }
        if (c >= 0xf0 && c <= 0xf4) {
            if (i + 2 >= n) return false;
            const unsigned char c1 = p[i++], c2 = p[i++], c3 = p[i++];
            if ((c1 & 0xc0) != 0x80 || (c2 & 0xc0) != 0x80 || (c3 & 0xc0) != 0x80)
                return false;
            if ((c == 0xf0 && c1 < 0x90) || (c == 0xf4 && c1 >= 0x90)) return false;
            continue;
        }
        return false;
    }
    return true;
}

// Canonical zero-copy input for every in-memory codec reader. This explicit
// Py_buffer guard is deliberately stricter than nb::ndarray<const uint8_t>:
// nanobind may convert a wrong-dtype/noncontiguous ndarray, and `const` does not
// require the exported view itself to be read-only. As with every borrowed
// buffer API, callers must also keep any writable aliases/backing file stable
// until the synchronous decoder returns.
class ByteView {
public:
    explicit ByteView(nb::handle source) {
        if (PyObject_GetBuffer(source.ptr(), &buffer_, PyBUF_FORMAT | PyBUF_STRIDES) != 0)
            throw nb::python_error();
        acquired_ = true;
        const bool exact_byte =
            buffer_.itemsize == 1 && buffer_.format && std::strcmp(buffer_.format, "B") == 0;
        if (!buffer_.readonly || !exact_byte || !PyBuffer_IsContiguous(&buffer_, 'C') ||
            buffer_.len < 0) {
            PyBuffer_Release(&buffer_);
            acquired_ = false;
            throw std::invalid_argument(
                "codec input must be a read-only, C-contiguous unsigned-byte buffer");
        }
    }

    ByteView(const ByteView &) = delete;
    ByteView &operator=(const ByteView &) = delete;
    ~ByteView() {
        if (acquired_) PyBuffer_Release(&buffer_);
    }

    const uint8_t *data() const { return static_cast<const uint8_t *>(buffer_.buf); }
    size_t size() const { return static_cast<size_t>(buffer_.len); }

private:
    Py_buffer buffer_{};
    bool acquired_ = false;
};

inline bool host_is_le() {
    const uint16_t x = 1;
    return *reinterpret_cast<const uint8_t *>(&x) == 1;
}

// Little-endian binary reader over an in-memory buffer. (Hosts are LE in
// practice — x86/arm64; a big-endian host would need byte-swaps here.)
struct LeReader {
    const uint8_t *p;
    size_t n;
    size_t pos = 0;
    LeReader(const void *data, size_t size)
        : p(static_cast<const uint8_t *>(data)), n(size) {}

    template <typename T>
    T get() {
        static_assert(std::is_trivially_copyable_v<T>);
        if (pos + sizeof(T) > n) throw std::invalid_argument("binary read past end of buffer");
        T v;
        std::memcpy(&v, p + pos, sizeof(T));
        pos += sizeof(T);
        return v;
    }
    std::string get_cstr() {
        std::string s;
        while (pos < n && p[pos] != '\0') s.push_back(static_cast<char>(p[pos++]));
        if (pos < n) pos++;  // consume the NUL
        return s;
    }
};

// Little-endian binary writer into a growable string sink.
struct LeWriter {
    std::string out;
    template <typename T>
    void put(T v) {
        out.append(reinterpret_cast<const char *>(&v), sizeof(T));
    }
    void put_cstr(const std::string &s) {
        out.append(s);
        out.push_back('\0');
    }
};

// Return a *zero-copy* numpy ndarray that is a view into the C++ buffer
// `data`, keeping `owner` (the Python object holding that buffer) alive for
// as long as any array references it. This is the canonical accessor
// pattern for the SoA Record types.
template <typename T>
nb::ndarray<nb::numpy, T> view(nb::handle owner, const T *data, std::vector<size_t> shape) {
    return nb::ndarray<nb::numpy, T>(const_cast<T *>(data), shape.size(), shape.data(), owner);
}

// Wrap a *moved* std::vector<T> as an ndarray that owns the buffer (used
// when there is no persistent owner object, e.g. a freshly decoded image).
template <typename T>
nb::ndarray<nb::numpy, T> own_array(std::vector<T> &&v, std::vector<size_t> shape) {
    auto *held = new std::vector<T>(std::move(v));
    nb::capsule owner(held, [](void *q) noexcept { delete static_cast<std::vector<T> *>(q); });
    return nb::ndarray<nb::numpy, T>(held->data(), shape.size(), shape.data(), owner);
}

// Runtime-dtype twin of own_array: wrap a moved byte buffer as an owning ndarray
// whose dtype is chosen at runtime (for the generic tensor codecs — npy/npz,
// later HDF5/safetensors). `dt` is a DLPack dtype {code, bits, lanes}.
inline nb::ndarray<nb::numpy> own_bytes(std::vector<uint8_t> &&v, std::vector<size_t> shape,
                                        nb::dlpack::dtype dt) {
    auto *held = new std::vector<uint8_t>(std::move(v));
    nb::capsule owner(held, [](void *q) noexcept { delete static_cast<std::vector<uint8_t> *>(q); });
    return nb::ndarray<nb::numpy>(held->data(), shape.size(), shape.data(), owner,
                                  /*strides=*/nullptr, dt);
}

static_assert(sizeof(double) == 8 && sizeof(float) == 4 && sizeof(uint64_t) == 8);

}  // namespace sio
