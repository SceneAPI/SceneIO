// PFM codec (Tier-1 float depth/disparity container, formats_survey.md §6).
#include "io/common.hpp"

#include <charconv>
#include <cmath>
#include <limits>

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

size_t positive_dimension(const std::string &token) {
    if (token.empty())
        throw std::invalid_argument("dimension");
    size_t value = 0;
    const char *begin = token.data(), *end = begin + token.size();
    const auto parsed = std::from_chars(begin, end, value);
    if (parsed.ec != std::errc{} || parsed.ptr != end || value == 0)
        throw std::invalid_argument("dimension");
    return value;
}

struct PfmInfo {
    size_t width;
    size_t height;
    size_t channels;
    size_t row;
    size_t count;
    size_t data_ofs;
    bool swap;
};

PfmInfo parse_pfm(const uint8_t *p, size_t n) {
    size_t pos = 0;
    const std::string magic = next_token(p, n, pos);
    int C;
    if (magic == "PF") C = 3;
    else if (magic == "Pf") C = 1;
    else throw std::invalid_argument("PFM: bad magic (expected 'PF' or 'Pf')");
    size_t width, height;
    double scale;
    try {
        width = positive_dimension(next_token(p, n, pos));
        height = positive_dimension(next_token(p, n, pos));
        const std::string scale_token = next_token(p, n, pos);
        size_t consumed = 0;
        scale = std::stod(scale_token, &consumed);
        if (consumed != scale_token.size())
            throw std::invalid_argument("scale");
    } catch (const std::exception &) {
        throw std::invalid_argument("PFM: malformed header (width/height/scale)");
    }
    if (!std::isfinite(scale) || scale == 0.0)
        throw std::invalid_argument("PFM: scale must be finite and nonzero");
    const bool file_le = std::signbit(scale);
    if (pos < n && is_ws(p[pos])) pos++;
    if (width > std::numeric_limits<size_t>::max() / static_cast<size_t>(C))
        throw std::invalid_argument("PFM: dimensions overflow address space");
    const size_t row = width * static_cast<size_t>(C);
    if (height > std::numeric_limits<size_t>::max() / row)
        throw std::invalid_argument("PFM: dimensions overflow address space");
    const size_t count = row * height;
    if (count > (n - pos) / sizeof(float))
        throw std::invalid_argument("PFM: truncated pixel data");
    return {width, height, static_cast<size_t>(C), row, count, pos,
            file_le != host_is_le()};
}

std::vector<float> copy_pfm(const uint8_t *p, const PfmInfo &info) {
    std::vector<float> buf(info.count);
    const uint8_t *src = p + info.data_ofs;
    for (size_t y = 0; y < info.height; y++) {  // PFM rows are bottom-to-top -> flip
        const uint8_t *sr =
            src + (info.height - 1 - y) * info.row * sizeof(float);
        float *dr = buf.data() + y * info.row;
        std::memcpy(dr, sr, info.row * sizeof(float));
        if (info.swap)
            for (size_t i = 0; i < info.row; i++) dr[i] = bswap32f(dr[i]);
    }
    return buf;
}

nb::ndarray<nb::numpy, float> read_pfm(nb::handle source) {
    sio::ByteView data(source);
    const uint8_t *p = data.data();
    PfmInfo info;
    std::vector<float> buf;
    {
        nb::gil_scoped_release rel;
        info = parse_pfm(p, data.size());
        buf = copy_pfm(p, info);
    }
    if (info.channels == 1)
        return own_array(std::move(buf), {info.height, info.width});
    return own_array(std::move(buf), {info.height, info.width, 3});
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
