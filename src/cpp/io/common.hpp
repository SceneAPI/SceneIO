// Shared helpers for the sceneio nanobind core: endianness, little-endian
// binary read/write, and the zero-copy "own_array" ndarray factory.
#pragma once

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <algorithm>
#include <cerrno>
#include <climits>
#include <cstdint>
#include <cstring>
#include <exception>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <type_traits>
#include <vector>

#ifdef _WIN32
#include <io.h>
#else
#include <unistd.h>
#endif

namespace nb = nanobind;

namespace sio {

constexpr size_t kMaxParallelLanes = 64;

inline size_t checked_half_open_range(size_t start, size_t stop, size_t total,
                                      const char *what) {
    if (start >= stop)
        throw std::invalid_argument(std::string(what) +
                                    " must be a non-empty half-open range");
    if (stop > total)
        throw std::invalid_argument(std::string(what) +
                                    " exceeds the available extent");
    return stop - start;
}

inline size_t parallel_lane_count(size_t count, size_t requested,
                                  size_t min_items_per_lane) {
    if (requested > kMaxParallelLanes)
        throw std::invalid_argument("parallel lane count exceeds 64");
    if (count == 0) return 1;
    size_t lanes = requested;
    if (lanes == 0) {
        lanes = std::max<size_t>(1, std::thread::hardware_concurrency());
        lanes = std::min<size_t>(lanes, 8);
        const size_t useful =
            1 + (count - 1) / std::max<size_t>(1, min_items_per_lane);
        lanes = std::min(lanes, useful);
    }
    return std::max<size_t>(1, std::min(lanes, count));
}

// Run deterministic contiguous blocks on a bounded number of threads. An
// explicit lane count is a private verification seam; zero selects up to eight
// hardware lanes but retains the serial path for small inputs. Worker
// exceptions are captured, every started thread is joined, then the first error
// is rethrown on the caller.
template <typename Fn>
size_t parallel_for_blocks(size_t count, size_t requested,
                           size_t min_items_per_lane, Fn &&fn) {
    const size_t lanes =
        parallel_lane_count(count, requested, min_items_per_lane);
    if (count == 0) return lanes;
    if (lanes == 1) {
        fn(0, count, 0);
        return lanes;
    }

    std::exception_ptr error;
    std::mutex error_mutex;
    auto run = [&](size_t lane) {
        const size_t base = count / lanes;
        const size_t extra = count % lanes;
        const size_t begin = lane * base + std::min(lane, extra);
        const size_t end = begin + base + (lane < extra ? 1 : 0);
        try {
            fn(begin, end, lane);
        } catch (...) {
            std::lock_guard<std::mutex> lock(error_mutex);
            if (!error) error = std::current_exception();
        }
    };

    std::vector<std::thread> workers;
    workers.reserve(lanes - 1);
    try {
        for (size_t lane = 1; lane < lanes; ++lane)
            workers.emplace_back(run, lane);
    } catch (...) {
        for (std::thread &worker : workers)
            if (worker.joinable()) worker.join();
        throw;
    }
    run(0);
    for (std::thread &worker : workers) worker.join();
    if (error) std::rethrow_exception(error);
    return lanes;
}

class FileSink;
inline thread_local FileSink *active_file_sink = nullptr;

// Python's open()/fileno()/close() are overridable and can re-enter a compiled
// encoder. Disable interception during those callbacks so a reentrant encoder
// returns its ordinary bytes instead of corrupting the in-progress file sink.
class FileSinkSuppression {
public:
    FileSinkSuppression()
        : previous_(active_file_sink) {
        active_file_sink = nullptr;
    }
    FileSinkSuppression(const FileSinkSuppression &) = delete;
    FileSinkSuppression &operator=(const FileSinkSuppression &) = delete;
    ~FileSinkSuppression() { active_file_sink = previous_; }

private:
    FileSink *previous_;
};

// Direct-to-file encoder sink. It opens the Python path lazily on the first
// emission, after codec validation/encoding succeeds, preserving both Unicode
// path handling and the previous rule that guard failures do not truncate an
// existing destination. Codec writers call emit_bytes() exactly as before;
// inside an active scope it writes the existing C++ output buffer through the
// file's native descriptor instead of exposing its non-owning pointer to Python
// or allocating a second, output-sized Python bytes object.
class FileSink {
public:
    explicit FileSink(nb::handle path, size_t max_chunk = 0,
                      size_t test_short_write = 0,
                      size_t test_fail_after = 0)
        : path_(nb::borrow<nb::object>(path)),
          max_chunk_(max_chunk == 0 ? std::numeric_limits<size_t>::max()
                                    : max_chunk),
          test_short_write_(test_short_write),
          test_fail_after_(test_fail_after) {}

    void write(const char *data, size_t size) {
        calls_++;
        int fd;
        {
            FileSinkSuppression suppress;
            if (!file_.is_valid())
                file_ = nb::module_::import_("builtins").attr("open")(
                    path_, "wb", 0);  // C++ buffer is already complete
            fd = PyObject_AsFileDescriptor(file_.ptr());
            if (fd < 0) throw nb::python_error();
        }
        {
            nb::gil_scoped_release rel;
            while (size != 0) {
#ifdef _WIN32
                const unsigned int chunk = static_cast<unsigned int>(
                    std::min({size, static_cast<size_t>(INT_MAX), max_chunk_}));
                const unsigned int request = static_cast<unsigned int>(
                    test_short_write_ == 0
                        ? chunk
                        : std::min(static_cast<size_t>(chunk),
                                   test_short_write_));
                native_write_calls_++;
                int written;
                if (test_fail_after_ != 0 &&
                    native_write_calls_ > test_fail_after_) {
                    errno = EIO;
                    written = -1;
                } else {
                    written = ::_write(fd, data, request);
                }
#else
                const size_t chunk =
                    std::min({size,
                              static_cast<size_t>(
                                  std::numeric_limits<ssize_t>::max()),
                              max_chunk_});
                const size_t request =
                    test_short_write_ == 0
                        ? chunk
                        : std::min(chunk, test_short_write_);
                native_write_calls_++;
                ssize_t written;
                if (test_fail_after_ != 0 &&
                    native_write_calls_ > test_fail_after_) {
                    errno = EIO;
                    written = -1;
                } else {
                    written = ::write(fd, data, request);
                }
#endif
                if (written < 0) {
                    if (errno == EINTR) continue;
                    throw std::runtime_error(
                        std::string("file sink write failed: ") +
                        std::strerror(errno));
                }
                if (written == 0)
                    throw std::runtime_error("file sink write made no progress");
                const size_t count = static_cast<size_t>(written);
                data += count;
                size -= count;
                bytes_ += count;
            }
        }
    }

    void close() {
        if (!file_.is_valid()) return;
        FileSinkSuppression suppress;
        nb::object file = std::move(file_);
        file.attr("close")();
    }
    void close_noexcept() noexcept {
        if (!file_.is_valid()) return;
        FileSinkSuppression suppress;
        nb::object file = std::move(file_);
        PyObject *result = PyObject_CallMethod(file.ptr(), "close", nullptr);
        if (result)
            Py_DECREF(result);
        else
            PyErr_Clear();
    }
    size_t calls() const { return calls_; }
    size_t bytes() const { return bytes_; }
    size_t native_write_calls() const { return native_write_calls_; }

private:
    nb::object path_;
    nb::object file_;
    size_t max_chunk_;
    // Private deterministic test shim. It models a native write returning less
    // than the logical chunk and, optionally, failing after prior progress.
    // Production callers always leave both values at zero.
    size_t test_short_write_;
    size_t test_fail_after_;
    size_t calls_ = 0;
    size_t bytes_ = 0;
    size_t native_write_calls_ = 0;
};

class FileSinkScope {
public:
    explicit FileSinkScope(nb::handle path, size_t max_chunk = 0,
                           size_t test_short_write = 0,
                           size_t test_fail_after = 0)
        : sink_(path, max_chunk, test_short_write, test_fail_after),
          previous_(active_file_sink) {
        active_file_sink = &sink_;
    }
    FileSinkScope(const FileSinkScope &) = delete;
    FileSinkScope &operator=(const FileSinkScope &) = delete;
    ~FileSinkScope() { active_file_sink = previous_; }

    void close() { sink_.close(); }
    void close_noexcept() noexcept { sink_.close_noexcept(); }
    size_t calls() const { return sink_.calls(); }
    size_t bytes() const { return sink_.bytes(); }
    size_t native_write_calls() const { return sink_.native_write_calls(); }

private:
    FileSink sink_;
    FileSink *previous_;
};

inline nb::bytes emit_bytes(const char *data, size_t size) {
    if (active_file_sink) {
        active_file_sink->write(data, size);
        return nb::bytes("", 0);
    }
    return nb::bytes(data, size);
}

// Private buffer-exporter type used as numpy.ndarray.base for mmap-backed
// arrays. It holds a live Py_buffer but deliberately exposes no close/release
// method. Returning a nanobind ndarray directly would make numpy install a
// releasable memoryview as `.base`; calling array.base.release() could then
// unpin an mmap while the array still held its raw pointer.
struct PinnedBufferObject {
    PyObject_HEAD
    Py_buffer view;
};

inline int pinned_buffer_getbuffer(PyObject *self, Py_buffer *view, int flags) {
    auto *held = reinterpret_cast<PinnedBufferObject *>(self);
    return PyBuffer_FillInfo(view, self, held->view.buf, held->view.len,
                             /*readonly=*/1, flags);
}

inline void pinned_buffer_dealloc(PyObject *self) {
    auto *held = reinterpret_cast<PinnedBufferObject *>(self);
    PyTypeObject *type = Py_TYPE(self);
    PyBuffer_Release(&held->view);
    PyObject_Free(self);
    // PyType_GenericAlloc retains heap types for each instance. A custom
    // tp_dealloc must release that reference after freeing the instance.
    Py_DECREF(reinterpret_cast<PyObject *>(type));
}

inline nb::object make_pinned_buffer_type() {
    static PyType_Slot slots[] = {
        {Py_tp_dealloc, reinterpret_cast<void *>(pinned_buffer_dealloc)},
        {Py_bf_getbuffer, reinterpret_cast<void *>(pinned_buffer_getbuffer)},
        {0, nullptr},
    };
    static PyType_Spec spec = {
        "sceneio._core._PinnedBuffer",
        static_cast<int>(sizeof(PinnedBufferObject)),
        0,
        Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE,
        slots,
    };
    nb::object type = nb::steal<nb::object>(PyType_FromSpec(&spec));
    if (!type.is_valid()) throw nb::python_error();
    return type;
}

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

    // Transfer the live export into an uncloseable private Python owner.
    nb::object pin() {
        if (!acquired_) throw std::logic_error("ByteView buffer was already transferred");
        // The fresh heap type is retained by its instance. This avoids a
        // process-global or deletable module-attribute type cache, and remains
        // correct across independent Python interpreters.
        nb::object type = make_pinned_buffer_type();
        auto *type_ptr = reinterpret_cast<PyTypeObject *>(type.ptr());
        auto *held = reinterpret_cast<PinnedBufferObject *>(
            PyType_GenericAlloc(type_ptr, 0));
        if (!held) throw nb::python_error();
        held->view = buffer_;
        acquired_ = false;
        return nb::steal<nb::object>(reinterpret_cast<PyObject *>(held));
    }

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

// Return a read-only numpy array that aliases a slice of `source`. Strides use
// DLPack/nanobind element units (not bytes). ByteView::pin keeps the exact
// Py_buffer export alive, preventing an mmap exporter from being closed while
// numpy still holds the raw pointer. The exporter/backing file must remain
// byte-stable for the lifetime of the returned array and all derived views.
inline nb::object borrowed_bytes(ByteView &source, const uint8_t *data,
                                 const std::vector<size_t> &shape, const char *dtype_name,
                                 size_t itemsize,
                                 const std::vector<int64_t> &strides = {}) {
    if (!strides.empty() && strides.size() != shape.size())
        throw std::logic_error("borrowed array shape/stride rank mismatch");
    if (data < source.data() ||
        static_cast<size_t>(data - source.data()) > source.size())
        throw std::logic_error("borrowed array data is outside its source buffer");
    const size_t offset = static_cast<size_t>(data - source.data());
    nb::object owner = source.pin();
    nb::tuple py_shape = nb::steal<nb::tuple>(
        PyTuple_New(static_cast<Py_ssize_t>(shape.size())));
    if (!py_shape.is_valid()) throw nb::python_error();
    for (size_t i = 0; i < shape.size(); i++) {
        PyObject *value = PyLong_FromSize_t(shape[i]);
        if (!value) throw nb::python_error();
        PyTuple_SetItem(py_shape.ptr(), static_cast<Py_ssize_t>(i), value);
    }
    nb::object py_strides = nb::none();
    if (!strides.empty()) {
        if (itemsize == 0 ||
            itemsize > static_cast<size_t>(std::numeric_limits<int64_t>::max()))
            throw std::invalid_argument("array item size cannot be represented");
        const int64_t signed_itemsize = static_cast<int64_t>(itemsize);
        nb::tuple values = nb::steal<nb::tuple>(
            PyTuple_New(static_cast<Py_ssize_t>(strides.size())));
        if (!values.is_valid()) throw nb::python_error();
        for (size_t i = 0; i < strides.size(); i++) {
            if (strides[i] > std::numeric_limits<int64_t>::max() / signed_itemsize ||
                strides[i] < std::numeric_limits<int64_t>::min() / signed_itemsize)
                throw std::invalid_argument("array byte stride overflows int64");
            PyObject *value = PyLong_FromLongLong(strides[i] * signed_itemsize);
            if (!value) throw nb::python_error();
            PyTuple_SetItem(values.ptr(), static_cast<Py_ssize_t>(i), value);
        }
        py_strides = std::move(values);
    }
    nb::module_ numpy = nb::module_::import_("numpy");
    nb::object dtype = numpy.attr("dtype")(dtype_name);
    nb::object array_type =
        nb::module_::import_("sceneio._mapped_array").attr("_MappedArray");
    using namespace nb::literals;
    return array_type(py_shape, "dtype"_a = dtype, "buffer"_a = owner,
                      "offset"_a = offset, "strides"_a = py_strides);
}

static_assert(sizeof(double) == 8 && sizeof(float) == 4 && sizeof(uint64_t) == 8);

}  // namespace sio
