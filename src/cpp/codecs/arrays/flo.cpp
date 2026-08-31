// Middlebury .flo optical-flow codec (Tier-1, zero-dep; formats_survey §3g).
// Returns an owning FlowField whose contiguous (H,W,2) float32 vectors retain
// the u/v bits exactly and whose convention fields make the format's otherwise
// implicit semantics explicit.
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
// GIL around pure-C++ parsing/copy/encode work (the npy_npz precedent, roadmap
// §1.3); Python view construction runs after reacquiring it. The file is always
// little-endian on disk; on a big-endian
// host both the int32 header fields (width/height) and the float payload are
// byte-swapped on read/write (the pfm.cpp payload path, extended to the header)
// so the on-disk bytes are LE throughout — magic, dimensions, and samples.
#include "io/common.hpp"
#include "records/flow_field.hpp"

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

struct FloInfo {
    size_t height;
    size_t width;
};

FloInfo parse_flo(const uint8_t *p, size_t n) {
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
    // Trailing bytes after the raster are ignored (PFM/netpbm precedent).
    return {static_cast<size_t>(h32), static_cast<size_t>(w32)};
}

std::vector<float> copy_flo_window(const uint8_t *p, const FloInfo &info,
                                   size_t row_start, size_t row_stop,
                                   size_t col_start, size_t col_stop) {
    const size_t height = row_stop - row_start;
    const size_t width = col_stop - col_start;
    const size_t row_count = width * 2;
    std::vector<float> buf(height * row_count);
    for (size_t row = 0; row < height; ++row) {
        const uint8_t *source =
            p + 12 +
            ((row_start + row) * info.width + col_start) * 2 * sizeof(float);
        std::memcpy(buf.data() + row * row_count, source,
                    row_count * sizeof(float));
    }
    if (!host_is_le())
        for (float &f : buf) f = bswap32f(f);
    return buf;
}

FlowField make_flow_field(std::vector<float> vectors, size_t height,
                          size_t width) {
    FlowField result;
    result.height = height;
    result.width = width;
    result.vectors = std::move(vectors);
    return result;
}

size_t checked_value_count(size_t height, size_t width) {
    if (height < 1 || width < 1)
        throw std::invalid_argument("flo: non-positive dimensions");
    if (height > kDimCap || width > kDimCap)
        throw std::invalid_argument(
            "flo: dimensions exceed int32");
    const uint64_t count = static_cast<uint64_t>(height) *
                           static_cast<uint64_t>(width) * 2ull;
    constexpr size_t max_size = std::numeric_limits<size_t>::max();
    if (count > max_size || static_cast<size_t>(count) > (max_size - 12) / 4)
        throw std::invalid_argument(
            "flo: dimensions overflow address space");
    return static_cast<size_t>(count);
}

std::string encode_flo(const float *source, size_t height, size_t width,
                       size_t count) {
    LeWriter writer;
    writer.out.reserve(12 + count * 4);
    writer.out.append(kFloMagic, 4);
    int32_t width_disk = static_cast<int32_t>(width);
    int32_t height_disk = static_cast<int32_t>(height);
    if (!host_is_le()) {
        width_disk = bswap32i(width_disk);
        height_disk = bswap32i(height_disk);
    }
    writer.put<int32_t>(width_disk);
    writer.put<int32_t>(height_disk);
    if (host_is_le()) {
        writer.out.append(reinterpret_cast<const char *>(source), count * 4);
    } else {
        for (size_t index = 0; index < count; ++index)
            writer.put<float>(bswap32f(source[index]));
    }
    return writer.out;
}

FlowField read_flo(nb::handle source) {
    sio::ByteView data(source);
    const uint8_t *p = data.data();
    FloInfo info;
    std::vector<float> buf;
    {
        nb::gil_scoped_release rel;  // pure C++ decode; touches no Python object
        info = parse_flo(p, data.size());
        buf = copy_flo_window(p, info, 0, info.height, 0, info.width);
    }
    return make_flow_field(std::move(buf), info.height, info.width);
}

FlowField read_flo_window(nb::handle source, size_t row_start,
                          size_t row_stop, size_t col_start,
                          size_t col_stop) {
    sio::ByteView data(source);
    const uint8_t *bytes = data.data();
    FloInfo info;
    size_t height = 0;
    size_t width = 0;
    std::vector<float> vectors;
    {
        nb::gil_scoped_release release;
        info = parse_flo(bytes, data.size());
        height = checked_half_open_range(
            row_start, row_stop, info.height, "flo row window");
        width = checked_half_open_range(
            col_start, col_stop, info.width, "flo column window");
        vectors = copy_flo_window(bytes, info, row_start, row_stop,
                                  col_start, col_stop);
    }
    return make_flow_field(std::move(vectors), height, width);
}

nb::bytes write_flo(const FlowField &flow) {
    const size_t count = checked_value_count(flow.height, flow.width);
    if (flow.vectors.size() != count)
        throw std::invalid_argument(
            "flo: FlowField storage disagrees with its dimensions");
    if (flow.component_order != "uv")
        throw std::invalid_argument(
            "flo: requires FlowField component_order 'uv'");
    if (flow.u_axis != "right")
        throw std::invalid_argument(
            "flo: requires FlowField u_axis 'right'");
    if (flow.v_axis != "down")
        throw std::invalid_argument(
            "flo: requires FlowField v_axis 'down'");
    if (flow.row_order != "top_to_bottom")
        throw std::invalid_argument(
            "flo: requires FlowField row_order 'top_to_bottom'");
    if (flow.unit != "pixels")
        throw std::invalid_argument(
            "flo: requires FlowField unit 'pixels'");
    if (flow.invalid_policy != "component_abs_gt_1e9")
        throw std::invalid_argument(
            "flo: requires FlowField invalid_policy "
            "'component_abs_gt_1e9'");

    std::string out;
    {
        nb::gil_scoped_release release;
        out = encode_flo(flow.vectors.data(), flow.height, flow.width, count);
    }
    return emit_bytes(out.data(), out.size());
}

}  // namespace

void register_flo(nb::module_ &m) {
    m.def("read_flo", &read_flo, "data"_a,
          "Decode Middlebury .flo bytes into an owning FlowField with uv, +right/+down, "
          "top-to-bottom, pixel, and component-abs-greater-than-1e9 conventions.");
    m.def("read_flo_window", &read_flo_window, "data"_a, "row_start"_a,
          "row_stop"_a, "col_start"_a, "col_stop"_a,
          "Decode a half-open pixel window from Middlebury .flo bytes into an owning "
          "FlowField with the same fixed conventions.");
    m.def("write_flo", &write_flo, "flow"_a,
          "Encode a canonical Middlebury-convention FlowField to .flo bytes. Foreign "
          "component, axis, row, unit, or invalid-value conventions are rejected.");
}
