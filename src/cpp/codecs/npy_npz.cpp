// numpy .npy / .npz codec (io_implementation_plan.md §2). Four functions, all
// bytes-in / bytes-out like every codec here:
//   read_npy  : .npy bytes  -> a generic-dtype numpy ndarray (native-LE, C-order)
//   write_npy : a CPU array -> byte-exact numpy v1.0 .npy bytes
//   read_npz  : .npz bytes   -> a TensorDict (one named tensor per zip member)
//   write_npz : a TensorDict -> .npz bytes (stored, or deflate when compress=True)
//
// The .npy header is hand-parsed with a tiny eval-free recursive-descent parser
// over numpy's closed dict grammar (format versions 1.0/2.0/3.0), and the writer
// emits the exact bytes modern numpy (np.lib.format, ARRAY_ALIGN=64) does, so
// write_npy is byte-identical to np.save. Endianness and Fortran order are
// resolved in C++ — the reader byteswaps '>' payloads and de-permutes
// fortran_order=True — so Python always sees a native-endian, C-contiguous
// array, the canonical form the TensorDict record documents. The dtype <-> descr
// machinery is the single source of truth in records/tensor_dict.hpp (the 12
// numpy dtypes bool/int8..64/uint8..64/float16/32/64; complex, object, str,
// datetime, and structured/subarray dtypes are rejected with a typed error,
// never silently coerced). .npz is a ZIP of "<key>.npy" members via the vendored
// miniz mz_zip_* API (stored == np.savez, deflate == np.savez_compressed).
//
// Overflow guards run before every allocation (a hostile header cannot wrap
// size_t and drive a heap OOB write), and the pure-C++ decode/encode sections
// run with the GIL released; nb::bytes / TensorDict / ndarray objects are only
// constructed with the GIL held.
#include <miniz.h>

#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include "records/tensor_dict.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// ---------------------------------------------------------------------------
// .npy header parsing (eval-free recursive descent over the closed grammar).
// ---------------------------------------------------------------------------

struct NpyInfo {
    DType tag = DType::U8;
    size_t itemsize = 1;
    bool fortran = false;
    bool byteswap = false;
    std::vector<size_t> shape;
    size_t data_ofs = 0;
};

// A minimal cursor over the header-dict slice. numpy emits ASCII with either
// quote char, arbitrary whitespace, the keys in any order, and an optional
// trailing comma; we accept exactly that and nothing that requires evaluation.
struct HdrCursor {
    const char *s;
    size_t n;
    size_t i = 0;
    HdrCursor(const char *s_, size_t n_) : s(s_), n(n_) {}
    void skip_ws() {
        while (i < n && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) i++;
    }
    char peek() {
        skip_ws();
        return i < n ? s[i] : '\0';
    }
    void expect(char c, const char *what) {
        skip_ws();
        if (i >= n || s[i] != c)
            throw std::invalid_argument(std::string("npy: malformed header (expected ") + what + ")");
        i++;
    }
    std::string quoted() {
        skip_ws();
        if (i >= n || (s[i] != '\'' && s[i] != '"'))
            throw std::invalid_argument("npy: malformed header (expected a quoted string)");
        const char q = s[i++];
        std::string out;
        while (i < n && s[i] != q) out.push_back(s[i++]);
        if (i >= n) throw std::invalid_argument("npy: malformed header (unterminated string)");
        i++;  // closing quote
        return out;
    }
    // Match & consume an unquoted keyword (True/False); false if it is not next.
    bool keyword(const char *lit) {
        skip_ws();
        const size_t len = std::strlen(lit);
        if (i + len <= n && std::memcmp(s + i, lit, len) == 0) {
            i += len;
            return true;
        }
        return false;
    }
};

std::vector<size_t> parse_shape(HdrCursor &c) {
    c.expect('(', "'('");
    std::vector<size_t> shape;
    for (;;) {
        const char ch = c.peek();
        if (ch == ')') { c.i++; break; }
        if (ch < '0' || ch > '9')
            throw std::invalid_argument("npy: malformed shape (expected a dimension)");
        size_t dim = 0;
        while (c.i < c.n && c.s[c.i] >= '0' && c.s[c.i] <= '9') {
            const size_t d = static_cast<size_t>(c.s[c.i] - '0');
            if (dim > (SIZE_MAX - d) / 10)
                throw std::invalid_argument("npy: shape dimension overflows size_t");
            dim = dim * 10 + d;
            c.i++;
        }
        shape.push_back(dim);
        if (shape.size() > 64) throw std::invalid_argument("npy: too many dimensions (>64)");
        const char sep = c.peek();
        if (sep == ',') { c.i++; continue; }
        if (sep == ')') { c.i++; break; }
        throw std::invalid_argument("npy: malformed shape (expected ',' or ')')");
    }
    return shape;
}

NpyInfo parse_npy_header(const uint8_t *p, size_t n) {
    static const uint8_t MAGIC[6] = {0x93, 'N', 'U', 'M', 'P', 'Y'};
    if (n < 10 || std::memcmp(p, MAGIC, 6) != 0)
        throw std::invalid_argument("npy: bad magic (not a .npy file)");
    const uint8_t major = p[6];
    size_t dict_start;
    uint32_t hlen;
    if (major == 1) {
        hlen = static_cast<uint32_t>(p[8]) | (static_cast<uint32_t>(p[9]) << 8);
        dict_start = 10;
    } else if (major == 2 || major == 3) {
        if (n < 12) throw std::invalid_argument("npy: truncated v2/v3 header");
        hlen = static_cast<uint32_t>(p[8]) | (static_cast<uint32_t>(p[9]) << 8) |
               (static_cast<uint32_t>(p[10]) << 16) | (static_cast<uint32_t>(p[11]) << 24);
        dict_start = 12;
    } else {
        throw std::invalid_argument("npy: unsupported format version " + std::to_string(major));
    }
    if (hlen > n - dict_start)  // n - dict_start is safe (n >= dict_start checked above)
        throw std::invalid_argument("npy: header length runs past end of file");

    HdrCursor c(reinterpret_cast<const char *>(p + dict_start), hlen);
    c.expect('{', "'{'");
    bool have_descr = false, have_fortran = false, have_shape = false;
    std::string descr;
    NpyInfo info;
    for (;;) {
        const char ch = c.peek();
        if (ch == '}') { c.i++; break; }
        const std::string key = c.quoted();
        c.expect(':', "':'");
        if (key == "descr") {
            // A structured/subarray descr is a Python list/tuple, not a string.
            if (c.peek() == '[' || c.peek() == '(')
                throw std::invalid_argument("npy: structured/subarray dtypes are not supported");
            descr = c.quoted();
            have_descr = true;
        } else if (key == "fortran_order") {
            if (c.keyword("True")) info.fortran = true;
            else if (c.keyword("False")) info.fortran = false;
            else throw std::invalid_argument("npy: malformed header (fortran_order must be True/False)");
            have_fortran = true;
        } else if (key == "shape") {
            info.shape = parse_shape(c);
            have_shape = true;
        } else {
            throw std::invalid_argument("npy: unexpected header key '" + key + "'");
        }
        const char sep = c.peek();
        if (sep == ',') { c.i++; continue; }
        if (sep == '}') { c.i++; break; }
        throw std::invalid_argument("npy: malformed header (expected ',' or '}')");
    }
    if (!have_descr || !have_fortran || !have_shape)
        throw std::invalid_argument("npy: header is missing descr/fortran_order/shape");

    char bo = '=';
    if (!descr.empty() && (descr[0] == '<' || descr[0] == '>' || descr[0] == '=' || descr[0] == '|'))
        bo = descr[0];
    const DTypeInfo *dt = dtype_from_descr(descr);
    if (!dt)
        throw std::invalid_argument("npy: unsupported dtype '" + descr +
                                    "' (supported: bool, int8..64, uint8..64, float16/32/64)");
    info.tag = dt->tag;
    info.itemsize = dt->itemsize;
    if (info.itemsize <= 1) info.byteswap = false;             // 1-byte types are orderless
    else if (bo == '>') info.byteswap = host_is_le();          // big-endian file on an LE host
    else if (bo == '<') info.byteswap = !host_is_le();         // little-endian file on a BE host
    else info.byteswap = false;                                // '=' native, '|' orderless
    info.data_ofs = dict_start + hlen;
    return info;
}

// Re-order a Fortran-order payload into C order (odometer gather); ndim >= 2.
std::vector<uint8_t> fortran_to_c(const std::vector<uint8_t> &src,
                                  const std::vector<size_t> &shape, size_t itemsize) {
    const size_t k = shape.size();
    size_t count = 1;
    for (size_t d : shape) count *= d;  // already overflow-checked by the caller
    std::vector<uint8_t> dst(src.size());
    std::vector<size_t> sf(k);  // Fortran strides, in elements
    sf[0] = 1;
    for (size_t j = 1; j < k; j++) sf[j] = sf[j - 1] * shape[j - 1];
    std::vector<size_t> idx(k, 0);
    for (size_t ci = 0; ci < count; ci++) {
        size_t fi = 0;
        for (size_t j = 0; j < k; j++) fi += idx[j] * sf[j];
        std::memcpy(dst.data() + ci * itemsize, src.data() + fi * itemsize, itemsize);
        for (size_t j = k; j-- > 0;) {  // increment the C-order odometer (last axis fastest)
            if (++idx[j] < shape[j]) break;
            idx[j] = 0;
        }
    }
    return dst;
}

std::vector<uint8_t> load_npy_payload(const uint8_t *p, size_t n, const NpyInfo &h) {
    size_t count = 1;
    for (size_t d : h.shape) {
        if (d != 0 && count > SIZE_MAX / d)
            throw std::invalid_argument("npy: element count overflows size_t");
        count *= d;
    }
    if (h.itemsize != 0 && count > SIZE_MAX / h.itemsize)
        throw std::invalid_argument("npy: byte size overflows size_t");
    const size_t nbytes = count * h.itemsize;
    if (nbytes > n - h.data_ofs)  // data_ofs <= n (established in parse_npy_header)
        throw std::invalid_argument("npy: truncated array data");
    std::vector<uint8_t> buf(nbytes);
    if (nbytes) std::memcpy(buf.data(), p + h.data_ofs, nbytes);
    if (h.byteswap && h.itemsize > 1) {  // reverse each element in place (no complex here)
        for (size_t e = 0; e < count; e++) {
            uint8_t *el = buf.data() + e * h.itemsize;
            for (size_t a = 0, b = h.itemsize - 1; a < b; a++, b--) std::swap(el[a], el[b]);
        }
    }
    if (h.fortran && h.shape.size() >= 2) buf = fortran_to_c(buf, h.shape, h.itemsize);
    return buf;
}

// ---------------------------------------------------------------------------
// .npy serialization (byte-exact numpy v1.0, ARRAY_ALIGN = 64).
// ---------------------------------------------------------------------------

std::string shape_repr(const std::vector<size_t> &shape) {  // Python tuple repr
    if (shape.empty()) return "()";
    if (shape.size() == 1) return "(" + std::to_string(shape[0]) + ",)";
    std::string s = "(";
    for (size_t i = 0; i < shape.size(); i++) {
        if (i) s += ", ";
        s += std::to_string(shape[i]);
    }
    s += ")";
    return s;
}

std::string serialize_npy(const char *descr, const std::vector<size_t> &shape,
                          const void *data, size_t nbytes) {
    std::string dict = std::string("{'descr': '") + descr +
                       "', 'fortran_order': False, 'shape': " + shape_repr(shape) + ", }";
    const size_t hlen = dict.size() + 1;              // numpy's hlen counts the trailing '\n'
    const size_t padlen = 64 - ((10 + hlen) % 64);    // 10 = 6 magic + 2 version + 2 length; in [1,64]
    const size_t stored = hlen + padlen;              // the u16 header-length field for v1.0
    if (stored > 0xFFFF) throw std::invalid_argument("npy: header too large for format v1.0");
    std::string out;
    out.reserve(10 + stored + nbytes);
    out.push_back('\x93');
    out.append("NUMPY");
    out.push_back('\x01');  // major 1
    out.push_back('\x00');  // minor 0
    out.push_back(static_cast<char>(stored & 0xff));
    out.push_back(static_cast<char>((stored >> 8) & 0xff));
    out.append(dict);
    out.append(padlen, ' ');
    out.push_back('\n');
    if (nbytes) out.append(static_cast<const char *>(data), nbytes);
    return out;
}

std::string serialize_entry(const TensorEntry &e) {  // one TensorDict entry -> a .npy member
    const DTypeInfo &info = dtype_info(e.dtype);
    return serialize_npy(info.npy_descr, e.shape, e.bytes.data(), e.bytes.size());
}

// ndarray strides are in ELEMENTS; a null stride pointer (DLPack compact form)
// means C-contiguous. A size-1 axis may carry any stride, so ignore it.
bool is_c_contig(const nb::ndarray<nb::ro, nb::device::cpu> &a) {
    const size_t nd = a.ndim();
    if (nd == 0 || !a.stride_ptr() || a.size() == 0) return true;
    int64_t expected = 1;
    for (size_t k = nd; k-- > 0;) {
        const size_t dim = a.shape(k);
        if (dim != 1 && a.stride(k) != expected) return false;
        expected *= static_cast<int64_t>(dim);
    }
    return true;
}

// ---------------------------------------------------------------------------
// bound functions
// ---------------------------------------------------------------------------

nb::ndarray<nb::numpy> read_npy(nb::bytes data) {
    const uint8_t *p = reinterpret_cast<const uint8_t *>(data.c_str());
    const size_t n = data.size();
    std::vector<uint8_t> buf;
    std::vector<size_t> shape;
    nb::dlpack::dtype dt{};
    {
        nb::gil_scoped_release rel;  // pure C++ decode; touches no Python object
        const NpyInfo info = parse_npy_header(p, n);
        buf = load_npy_payload(p, n, info);
        shape = info.shape;
        const DTypeInfo &di = dtype_info(info.tag);
        dt = nb::dlpack::dtype{di.code, di.bits, 1};
    }
    // own_bytes hands numpy the buffer's data() pointer; a 0-element array has an
    // empty buffer whose data() may be null, which numpy's buffer protocol
    // dislikes — back it with one unused byte (the view still reports 0 elements),
    // mirroring the record's empty-array sentinel.
    if (buf.empty()) buf.resize(1);
    return own_bytes(std::move(buf), std::move(shape), dt);
}

nb::bytes write_npy(nb::ndarray<nb::ro, nb::device::cpu> array) {
    if (!is_c_contig(array))
        throw std::invalid_argument("npy: array must be C-contiguous (use np.ascontiguousarray)");
    const DTypeInfo *info = dtype_from_dlpack(array.dtype());
    if (!info)
        throw std::invalid_argument(
            "npy: dtype not representable in .npy (supported: bool, int8..64, uint8..64, float16/32/64)");
    std::vector<size_t> shape(array.ndim());
    for (size_t i = 0; i < array.ndim(); i++) shape[i] = array.shape(i);
    size_t count = 1;
    for (size_t d : shape) {
        if (d != 0 && count > SIZE_MAX / d)
            throw std::invalid_argument("npy: element count overflows size_t");
        count *= d;
    }
    if (info->itemsize != 0 && count > SIZE_MAX / info->itemsize)
        throw std::invalid_argument("npy: byte size overflows size_t");
    const size_t nbytes = count * info->itemsize;
    const void *src = array.data();     // valid while `array` is alive (whole call)
    const char *descr = info->npy_descr;
    std::string out;
    {
        nb::gil_scoped_release rel;      // pure C++ header build + payload memcpy
        out = serialize_npy(descr, shape, src, nbytes);
    }
    return nb::bytes(out.data(), out.size());
}

TensorDict read_npz(nb::bytes data) {
    const uint8_t *p = reinterpret_cast<const uint8_t *>(data.c_str());
    const size_t n = data.size();
    TensorDict td;  // plain C++ struct — populated with the GIL released
    {
        nb::gil_scoped_release rel;
        mz_zip_archive zip;
        std::memset(&zip, 0, sizeof(zip));
        if (!mz_zip_reader_init_mem(&zip, p, n, 0))
            throw std::invalid_argument(std::string("npz: not a zip archive: ") +
                                        mz_zip_get_error_string(mz_zip_get_last_error(&zip)));
        struct ZipGuard {
            mz_zip_archive *z;
            ~ZipGuard() { mz_zip_end(z); }
        } guard{&zip};

        const mz_uint num = mz_zip_reader_get_num_files(&zip);
        for (mz_uint i = 0; i < num; i++) {
            if (mz_zip_reader_is_file_a_directory(&zip, i)) continue;
            mz_zip_archive_file_stat st;
            if (!mz_zip_reader_file_stat(&zip, i, &st))
                throw std::invalid_argument("npz: could not read a member header");
            size_t usz = 0;
            void *buf = mz_zip_reader_extract_to_heap(&zip, i, &usz, 0);  // handles store + deflate
            if (!buf)
                throw std::invalid_argument(std::string("npz: could not extract member '") +
                                            st.m_filename + "'");
            try {
                const NpyInfo info = parse_npy_header(static_cast<const uint8_t *>(buf), usz);
                const std::vector<uint8_t> payload =
                    load_npy_payload(static_cast<const uint8_t *>(buf), usz, info);
                std::string key = st.m_filename;  // strip one trailing ".npy" for the tensor name
                if (key.size() >= 4 && key.compare(key.size() - 4, 4, ".npy") == 0)
                    key.resize(key.size() - 4);
                TensorEntry &e = td.add(std::move(key), info.tag, info.shape);  // rejects duplicates
                if (!e.bytes.empty()) std::memcpy(e.bytes.data(), payload.data(), e.bytes.size());
            } catch (const std::exception &ex) {
                mz_free(buf);
                throw std::invalid_argument(std::string("npz: member '") + st.m_filename +
                                            "': " + ex.what());
            }
            mz_free(buf);
        }
    }
    return td;
}

nb::bytes write_npz(const TensorDict &td, bool compress) {
    std::string result;
    {
        nb::gil_scoped_release rel;
        mz_zip_archive zip;
        std::memset(&zip, 0, sizeof(zip));
        if (!mz_zip_writer_init_heap(&zip, 0, 1 << 16))
            throw std::runtime_error("npz: could not initialize the zip writer");
        struct ZipGuard {
            mz_zip_archive *z;
            ~ZipGuard() { mz_zip_end(z); }
        } guard{&zip};

        for (const TensorEntry &e : td.entries) {  // insertion order == member order
            const std::string member = serialize_entry(e);
            if (member.size() > 0xFFFFFFFFull)
                throw std::invalid_argument("npz: member '" + e.name +
                                            "' exceeds 4 GiB (zip64 write is unsupported)");
            const std::string arcname = e.name + ".npy";
            const mz_uint level = compress ? static_cast<mz_uint>(MZ_DEFAULT_LEVEL)   // deflate
                                           : static_cast<mz_uint>(MZ_NO_COMPRESSION);  // stored
            if (!mz_zip_writer_add_mem(&zip, arcname.c_str(), member.data(), member.size(), level))
                throw std::runtime_error("npz: could not add member '" + e.name + "'");
        }
        void *out = nullptr;
        size_t olen = 0;
        if (!mz_zip_writer_finalize_heap_archive(&zip, &out, &olen))
            throw std::runtime_error("npz: could not finalize the archive");
        result.assign(static_cast<const char *>(out), olen);
        mz_free(out);
    }
    return nb::bytes(result.data(), result.size());
}

}  // namespace

void register_npy_npz(nb::module_ &m) {
    m.def("read_npy", &read_npy, "data"_a,
          "Decode .npy bytes to a native-endian, C-contiguous numpy ndarray (any of the 12 "
          "supported dtypes; '>' payloads are byteswapped and fortran_order is de-permuted).");
    m.def("write_npy", &write_npy, "array"_a,
          "Encode a C-contiguous CPU ndarray (numpy or torch) to byte-exact numpy v1.0 .npy bytes.");
    m.def("read_npz", &read_npz, "data"_a,
          "Decode .npz (a zip of .npy members, stored or deflate) into a TensorDict; member order "
          "is preserved and duplicate keys are rejected.");
    m.def("write_npz", &write_npz, "tensors"_a, "compress"_a = false,
          "Encode a TensorDict to .npz bytes: stored (compress=False, np.savez) or deflate "
          "(compress=True, np.savez_compressed).");
}
