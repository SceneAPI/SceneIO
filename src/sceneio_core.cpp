// sceneio._core — compiled codec + memory engine (nanobind). Phase 0.
//
// Phase 0 proves the pattern end to end: a real Tier-1 codec (PFM — the
// float depth/disparity container from docs/formats_survey.md §6) that
// returns a zero-copy float32 ndarray (numpy by default; torch/cupy via
// DLPack) and accepts numpy OR torch on the write path. It also exercises
// the two PFM gotchas the survey flagged: scanlines are stored
// bottom-to-top, and the header scale sign selects endianness.

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace nb = nanobind;
using namespace nb::literals;

namespace {

bool host_is_le() {
    const uint16_t x = 1;
    return *reinterpret_cast<const uint8_t *>(&x) == 1;
}

float bswap32f(float f) {
    uint32_t u;
    std::memcpy(&u, &f, 4);
    u = (u >> 24) | ((u >> 8) & 0x0000ff00u) | ((u << 8) & 0x00ff0000u) | (u << 24);
    float r;
    std::memcpy(&r, &u, 4);
    return r;
}

bool is_ws(uint8_t c) { return c == ' ' || c == '\n' || c == '\r' || c == '\t'; }

// Whitespace-delimited token from a PFM header, advancing pos.
std::string next_token(const uint8_t *p, size_t n, size_t &pos) {
    while (pos < n && is_ws(p[pos])) pos++;
    size_t start = pos;
    while (pos < n && !is_ws(p[pos])) pos++;
    return std::string(reinterpret_cast<const char *>(p + start), pos - start);
}

}  // namespace

// Decode a PFM byte string -> float32 ndarray, canonicalized to
// top-to-bottom, native-endian, C-contiguous. Shape (H, W) for grayscale
// ("Pf") or (H, W, 3) for color ("PF").
static nb::ndarray<nb::numpy, float> read_pfm(nb::bytes data) {
    const uint8_t *p = reinterpret_cast<const uint8_t *>(data.c_str());
    const size_t n = data.size();
    size_t pos = 0;

    const std::string magic = next_token(p, n, pos);
    int C;
    if (magic == "PF") C = 3;
    else if (magic == "Pf") C = 1;
    else throw std::invalid_argument("PFM: bad magic (expected 'PF' or 'Pf')");

    long W, H;
    double scale;
    try {
        W = std::stol(next_token(p, n, pos));
        H = std::stol(next_token(p, n, pos));
        scale = std::stod(next_token(p, n, pos));
    } catch (const std::exception &) {
        throw std::invalid_argument("PFM: malformed header (width/height/scale)");
    }
    if (W <= 0 || H <= 0) throw std::invalid_argument("PFM: non-positive dimensions");

    const bool file_le = scale < 0.0;  // sign of scale = endianness
    if (pos < n && is_ws(p[pos])) pos++;  // one whitespace byte precedes the raster

    const size_t row_floats = static_cast<size_t>(W) * C;
    const size_t count = row_floats * static_cast<size_t>(H);
    if (pos + count * 4 > n) throw std::invalid_argument("PFM: truncated pixel data");

    float *buf = new float[count];
    const uint8_t *src = p + pos;
    const bool swap = (file_le != host_is_le());
    // PFM rows are bottom-to-top; flip to top-to-bottom.
    for (long y = 0; y < H; y++) {
        const uint8_t *srow = src + static_cast<size_t>(H - 1 - y) * row_floats * 4;
        float *drow = buf + static_cast<size_t>(y) * row_floats;
        std::memcpy(drow, srow, row_floats * 4);
        if (swap)
            for (size_t i = 0; i < row_floats; i++) drow[i] = bswap32f(drow[i]);
    }

    nb::capsule owner(buf, [](void *q) noexcept { delete[] static_cast<float *>(q); });
    if (C == 1) {
        size_t shape[2] = {static_cast<size_t>(H), static_cast<size_t>(W)};
        return nb::ndarray<nb::numpy, float>(buf, 2, shape, owner);
    }
    size_t shape[3] = {static_cast<size_t>(H), static_cast<size_t>(W), 3};
    return nb::ndarray<nb::numpy, float>(buf, 3, shape, owner);
}

// Encode a float32 (H, W) or (H, W, 3) array -> PFM bytes (little-endian,
// scale -1.0). Accepts numpy OR torch (any CPU float32 c-contiguous array).
static nb::bytes write_pfm(nb::ndarray<const float, nb::c_contig, nb::device::cpu> img) {
    const size_t nd = img.ndim();
    long H, W, C;
    if (nd == 2) {
        H = static_cast<long>(img.shape(0));
        W = static_cast<long>(img.shape(1));
        C = 1;
    } else if (nd == 3 && img.shape(2) == 3) {
        H = static_cast<long>(img.shape(0));
        W = static_cast<long>(img.shape(1));
        C = 3;
    } else {
        throw std::invalid_argument("write_pfm: expected float32 (H, W) or (H, W, 3)");
    }

    std::string out;
    out.append(C == 3 ? "PF\n" : "Pf\n");
    out.append(std::to_string(W)).append(" ").append(std::to_string(H)).append("\n-1.0\n");

    const size_t row_floats = static_cast<size_t>(W) * C;
    out.reserve(out.size() + row_floats * static_cast<size_t>(H) * 4);
    const float *d = img.data();
    const bool swap = !host_is_le();  // file is little-endian
    std::vector<float> tmp;
    if (swap) tmp.resize(row_floats);
    for (long y = 0; y < H; y++) {  // write bottom-to-top
        const float *srow = d + static_cast<size_t>(H - 1 - y) * row_floats;
        if (swap) {
            for (size_t i = 0; i < row_floats; i++) tmp[i] = bswap32f(srow[i]);
            srow = tmp.data();
        }
        out.append(reinterpret_cast<const char *>(srow), row_floats * 4);
    }
    return nb::bytes(out.data(), out.size());
}

NB_MODULE(_core, m) {
    m.doc() = "sceneio compiled core (nanobind) — Phase 0 (PFM reference codec)";
    m.attr("__phase__") = 0;
    m.def("read_pfm", &read_pfm, "data"_a,
          "Decode PFM bytes to a float32 ndarray (H,W) or (H,W,3), top-to-bottom, native-endian.");
    m.def("write_pfm", &write_pfm, "img"_a,
          "Encode a float32 (H,W) or (H,W,3) array (numpy or torch) to PFM bytes (little-endian).");
}
