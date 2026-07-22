// Shared helpers for the sceneio nanobind core: endianness, little-endian
// binary read/write, and the zero-copy "own_array" ndarray factory.
#pragma once

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace nb = nanobind;

namespace sio {

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
