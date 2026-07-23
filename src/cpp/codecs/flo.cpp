// Middlebury .flo optical-flow codec (Tier-1, zero-dep; formats_survey §3g).
// Returns a bare (H,W,2) float32 ndarray (u,v interleaved) via sio::own_array —
// the PFM bare-ndarray precedent (registry record=None), NOT a new record: .flo
// carries no metadata beyond W/H, so the future Dense/DepthMap record absorbs it
// later exactly as PFM will.
//
// Byte layout (little-endian throughout, total = 12 + W*H*2*4 bytes):
//   [0,4)   float32 magic 202021.25 == the ASCII bytes "PIEH" (validated by
//           memcmp against the 4 bytes, endian-explicit — never a float compare)
//   [4,8)   int32 width  W  (>= 1)
//   [8,12)  int32 height H  (>= 1)
//   [12,..) W*H*2 float32 samples, per-pixel interleaved (u then v), row-major,
//           rows TOP-TO-BOTTOM (row 0 first in file — NO flip, the opposite of
//           PFM's bottom-to-top). u = horizontal displacement in pixels (+right);
//           v = vertical displacement in pixels (+down), for top-to-bottom images.
//
// Sample values are pass-through DATA, never inspected: the Middlebury unknown-
// flow sentinel UNKNOWN_FLOW = 1e10 (|value| > 1e9) is metadata documented in the
// docstrings only — NaN/Inf/sentinels round-trip bit-exact (the netpbm maxval-is-
// metadata rule: reader records, does not judge). Malformed input raises
// std::invalid_argument (mapped to FormatError by the io layer); the per-axis
// dimension cap plus a bounds check *before* allocating mean a crafted 12-byte
// header can never trigger a large/OOM allocation.
//
// Unlike pfm/netpbm (which hold the GIL through decode/encode), this releases the
// GIL around the pure-C++ body (the npy_npz precedent, roadmap §1.3): no Python
// object is touched inside the release scope — the nb::bytes/own_array results are
// built outside it. The file is always little-endian on disk; on a big-endian
// host both the int32 header fields (width/height) and the float payload are
// byte-swapped on read/write (the pfm.cpp payload path, extended to the header)
// so the on-disk bytes are LE throughout — magic, dimensions, and samples.
#include "io/common.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// 1e9 per axis: keeps W*H*2*4 well inside uint64 and rejects absurd headers up
// front (netpbm.cpp kDimCap precedent). kDimCap < INT32_MAX, so the write path's
// int32 casts can never wrap.
constexpr uint64_t kDimCap = 1000000000ull;

// The 4-byte magic == float32 little-endian 202021.25
// (struct.pack('<f', 202021.25) == b"PIEH"). Compared as raw bytes, not a float.
constexpr char kFloMagic[4] = {'P', 'I', 'E', 'H'};

// Byte-swap primitives for the big-endian host path. The .flo file is always
// little-endian on disk, so a big-endian host swaps the int32 width/height header
// AND the float payload on read/write. Practically untested (hosts are LE in
// practice, common.hpp:24); kept trivially simple. bswap32f is the pfm.cpp:9 float
// path; bswap32i reuses the same 32-bit swap for the int32 header fields.
uint32_t bswap32(uint32_t u) {
    return (u >> 24) | ((u >> 8) & 0x0000ff00u) | ((u << 8) & 0x00ff0000u) | (u << 24);
}
float bswap32f(float f) {
    uint32_t u;
    std::memcpy(&u, &f, 4);
    u = bswap32(u);
    float r;
    std::memcpy(&r, &u, 4);
    return r;
}
int32_t bswap32i(int32_t v) {
    uint32_t u;
    std::memcpy(&u, &v, 4);
    u = bswap32(u);
    std::memcpy(&v, &u, 4);
    return v;
}

nb::ndarray<nb::numpy, float> read_flo(nb::bytes data) {
    const uint8_t *p = reinterpret_cast<const uint8_t *>(data.c_str());
    const size_t n = data.size();
    std::vector<float> buf;
    size_t H = 0, W = 0;
    {
        nb::gil_scoped_release rel;  // pure C++ decode; touches no Python object
        if (n < 12)
            throw std::invalid_argument("flo: truncated header (need 12 bytes: magic, width, height)");
        if (std::memcmp(p, kFloMagic, 4) != 0)
            throw std::invalid_argument("flo: bad magic (expected float32 202021.25 == 'PIEH')");
        int32_t w32, h32;
        std::memcpy(&w32, p + 4, 4);  // int32 stored little-endian on disk
        std::memcpy(&h32, p + 8, 4);
        if (!host_is_le()) {  // BE host: swap the LE-on-disk bytes into host order
            w32 = bswap32i(w32);
            h32 = bswap32i(h32);
        }
        // Reject non-positive dims BEFORE any unsigned cast (a negative int32 cast
        // to uint64 becomes huge and would slip past the cap check).
        if (w32 <= 0 || h32 <= 0) throw std::invalid_argument("flo: non-positive dimensions");
        if (static_cast<uint64_t>(w32) > kDimCap || static_cast<uint64_t>(h32) > kDimCap)
            throw std::invalid_argument("flo: dimensions out of range");
        const uint64_t count = static_cast<uint64_t>(w32) * static_cast<uint64_t>(h32) * 2ull;
        // Bounds-check before allocating: a 12-byte file claiming a huge raster
        // raises here without ever reserving memory (netpbm.cpp:125 rule).
        if (count * 4ull > static_cast<uint64_t>(n - 12))
            throw std::invalid_argument("flo: truncated flow raster");
        buf.resize(static_cast<size_t>(count));
        std::memcpy(buf.data(), p + 12, static_cast<size_t>(count) * 4);  // one bulk copy; NO flip
        if (!host_is_le())
            for (float &f : buf) f = bswap32f(f);
        H = static_cast<size_t>(h32);
        W = static_cast<size_t>(w32);
        // Trailing bytes after the raster are ignored (PFM/netpbm precedent).
    }
    return own_array(std::move(buf), {H, W, 2});  // capsule (a Python object) built after release
}

nb::bytes write_flo(nb::ndarray<const float, nb::c_contig, nb::device::cpu> flow) {
    if (flow.ndim() != 3 || flow.shape(2) != 2)
        throw std::invalid_argument(
            "write_flo: expected float32 (H,W,2) flow (u=[...,0] horizontal, v=[...,1] vertical)");
    const size_t H = flow.shape(0), W = flow.shape(1);
    if (H < 1 || W < 1) throw std::invalid_argument("flo: non-positive dimensions");
    if (H > kDimCap || W > kDimCap)
        throw std::invalid_argument("flo: dimensions exceed int32");  // < INT32_MAX -> safe casts
    const float *src = flow.data();  // valid while `flow` is alive (whole call)
    const size_t count = H * W * 2;
    std::string out;
    {
        nb::gil_scoped_release rel;  // pure C++ header build + payload copy
        LeWriter w;
        w.out.reserve(12 + count * 4);
        w.out.append(kFloMagic, 4);                       // endian-explicit magic bytes
        int32_t w_disk = static_cast<int32_t>(W), h_disk = static_cast<int32_t>(H);
        if (!host_is_le()) {  // BE host: pre-swap so the on-disk header bytes are LE
            w_disk = bswap32i(w_disk);
            h_disk = bswap32i(h_disk);
        }
        w.put<int32_t>(w_disk);                           // int32 little-endian on disk
        w.put<int32_t>(h_disk);
        if (host_is_le())
            w.out.append(reinterpret_cast<const char *>(src),
                         count * 4);                       // bulk copy: bit-exact incl. NaN/sentinels
        else
            for (size_t i = 0; i < count; i++)  // BE host: swap so on-disk bytes are LE (pfm.cpp:83)
                w.put<float>(bswap32f(src[i]));
        out = std::move(w.out);
    }
    return nb::bytes(out.data(), out.size());
}

}  // namespace

void register_flo(nb::module_ &m) {
    m.def("read_flo", &read_flo, "data"_a,
          "Decode Middlebury .flo bytes to a float32 (H,W,2) ndarray: [...,0]=u horizontal "
          "(+right), [...,1]=v vertical (+down), rows top-to-bottom, units pixels; |value|>1e9 "
          "conventionally marks unknown flow (sentinel 1e10) and is passed through raw.");
    m.def("write_flo", &write_flo, "flow"_a,
          "Encode a float32 (H,W,2) flow array (numpy or torch) to Middlebury .flo bytes "
          "(little-endian, magic 202021.25 'PIEH'); values incl. NaN/unknown-flow sentinels "
          "pass through bit-exact.");
}
