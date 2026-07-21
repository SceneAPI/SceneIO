// PFM codec (Tier-1 float depth/disparity container, formats_survey.md §6).
#include "io/common.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

float bswap32f(float f) {
    uint32_t u;
    std::memcpy(&u, &f, 4);
    u = (u >> 24) | ((u >> 8) & 0x0000ff00u) | ((u << 8) & 0x00ff0000u) | (u << 24);
    float r;
    std::memcpy(&r, &u, 4);
    return r;
}
bool is_ws(uint8_t c) { return c == ' ' || c == '\n' || c == '\r' || c == '\t'; }
std::string next_token(const uint8_t *p, size_t n, size_t &pos) {
    while (pos < n && is_ws(p[pos])) pos++;
    size_t s = pos;
    while (pos < n && !is_ws(p[pos])) pos++;
    return std::string(reinterpret_cast<const char *>(p + s), pos - s);
}

nb::ndarray<nb::numpy, float> read_pfm(nb::bytes data) {
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
    const bool file_le = scale < 0.0;
    if (pos < n && is_ws(p[pos])) pos++;
    const size_t row = static_cast<size_t>(W) * C, count = row * static_cast<size_t>(H);
    if (pos + count * 4 > n) throw std::invalid_argument("PFM: truncated pixel data");
    std::vector<float> buf(count);
    const uint8_t *src = p + pos;
    const bool swap = (file_le != host_is_le());
    for (long y = 0; y < H; y++) {  // PFM rows are bottom-to-top -> flip
        const uint8_t *sr = src + static_cast<size_t>(H - 1 - y) * row * 4;
        float *dr = buf.data() + static_cast<size_t>(y) * row;
        std::memcpy(dr, sr, row * 4);
        if (swap)
            for (size_t i = 0; i < row; i++) dr[i] = bswap32f(dr[i]);
    }
    if (C == 1) return own_array(std::move(buf), {static_cast<size_t>(H), static_cast<size_t>(W)});
    return own_array(std::move(buf), {static_cast<size_t>(H), static_cast<size_t>(W), 3});
}

nb::bytes write_pfm(nb::ndarray<const float, nb::c_contig, nb::device::cpu> img) {
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
        throw std::invalid_argument("write_pfm: expected float32 (H,W) or (H,W,3)");
    }
    LeWriter w;
    w.out.append(C == 3 ? "PF\n" : "Pf\n");
    w.out.append(std::to_string(W)).append(" ").append(std::to_string(H)).append("\n-1.0\n");
    const size_t row = static_cast<size_t>(W) * C;
    w.out.reserve(w.out.size() + row * static_cast<size_t>(H) * 4);
    const float *d = img.data();
    const bool swap = !host_is_le();
    std::vector<float> tmp;
    if (swap) tmp.resize(row);
    for (long y = 0; y < H; y++) {  // write bottom-to-top
        const float *sr = d + static_cast<size_t>(H - 1 - y) * row;
        if (swap) {
            for (size_t i = 0; i < row; i++) tmp[i] = bswap32f(sr[i]);
            sr = tmp.data();
        }
        w.out.append(reinterpret_cast<const char *>(sr), row * 4);
    }
    return nb::bytes(w.out.data(), w.out.size());
}

}  // namespace

void register_pfm(nb::module_ &m) {
    m.def("read_pfm", &read_pfm, "data"_a,
          "Decode PFM bytes to a float32 ndarray (H,W)/(H,W,3), top-to-bottom, native-endian.");
    m.def("write_pfm", &write_pfm, "img"_a,
          "Encode a float32 (H,W)/(H,W,3) array (numpy or torch) to PFM bytes (little-endian).");
}
