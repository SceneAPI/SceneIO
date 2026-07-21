// Niantic SPZ codec (formats_survey.md §4). This turn: the legacy gzip
// container reader (v1/v2/v3). The exact dequantization mirrors gsply's
// reference decode; the NGSP v4 (zstd) container is deferred.
//
// Payload (after gunzip): 16B header
//   magic u32 (NGSP) | version u32 | num_points u32 |
//   sh_degree u8 | fractional_bits u8 | flags u8 | reserved u8
// then contiguous sections: positions(9N) alphas(N) colors(3N) scales(3N)
// rotations(rot_stride*N) sh(sh_dim*3*N). Values are quantized/fixed-point.
#include <algorithm>
#include <cmath>

#include "io/gzip.hpp"
#include "records/gaussian_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint32_t NGSP_MAGIC = 0x5053474Eu;  // "NGSP" little-endian
constexpr float COLOR_SCALE = 0.15f;
constexpr uint32_t C_MASK = 511u;  // 9-bit magnitude
constexpr float INV_SQRT2 = 0.70710677f;
constexpr float EPS = 1e-6f;

int sh_dim_for_degree(int d) {
    switch (d) {
        case 0: return 0;
        case 1: return 3;
        case 2: return 8;
        case 3: return 15;
        default: throw std::invalid_argument("SPZ: unsupported sh_degree " + std::to_string(d));
    }
}


GaussianCloud read_spz(nb::bytes data) {
    const uint8_t *fp = reinterpret_cast<const uint8_t *>(data.c_str());
    const size_t fn = data.size();
    if (fn >= 4) {
        uint32_t m;
        std::memcpy(&m, fp, 4);
        if (m == NGSP_MAGIC)
            throw std::invalid_argument("SPZ: NGSP v4 (zstd) container not yet supported; only gzip v1/v2/v3");
    }
    std::vector<uint8_t> raw = gunzip(fp, fn);
    if (raw.size() < 16) throw std::invalid_argument("SPZ: header too small");
    uint32_t magic, version, num_points;
    std::memcpy(&magic, raw.data(), 4);
    std::memcpy(&version, raw.data() + 4, 4);
    std::memcpy(&num_points, raw.data() + 8, 4);
    const uint8_t sh_degree = raw[12], frac_bits = raw[13];
    if (magic != NGSP_MAGIC) throw std::invalid_argument("SPZ: bad magic after gunzip");
    if (version < 1 || version > 3) throw std::invalid_argument("SPZ: unsupported legacy version " + std::to_string(version));
    if (frac_bits < 1 || frac_bits > 24) throw std::invalid_argument("SPZ: invalid fractional_bits");

    const size_t n = num_points;
    const int sh_dim = sh_dim_for_degree(sh_degree);
    const bool uses_st = version >= 3;
    const size_t rot_stride = uses_st ? 4 : 3;
    const size_t expected = (9 + 1 + 3 + 3 + rot_stride + static_cast<size_t>(sh_dim) * 3) * n;
    if (raw.size() - 16 < expected) throw std::invalid_argument("SPZ: payload too small");
    const uint8_t *buf = raw.data() + 16;

    const size_t alpha_ofs = 9 * n, color_ofs = 10 * n, scale_ofs = 13 * n, rot_ofs = 16 * n;
    const size_t sh_ofs = 16 * n + rot_stride * n;
    const float inv_frac = 1.0f / static_cast<float>(1u << frac_bits);

    GaussianCloud g;
    g.n = n;
    g.num_rest = static_cast<size_t>(sh_dim) * 3;
    g.sh_degree = sh_degree;
    g.means.resize(n * 3);
    g.scales.resize(n * 3);
    g.quats.resize(n * 4);
    g.opacity.resize(n);
    g.sh_dc.resize(n * 3);
    g.sh_rest.resize(n * g.num_rest);

    for (size_t i = 0; i < n; i++) {
        const size_t pp = i * 9;  // positions: 24-bit signed fixed point
        for (int j = 0; j < 3; j++) {
            int32_t v = static_cast<int32_t>(buf[pp + j * 3]) |
                        (static_cast<int32_t>(buf[pp + j * 3 + 1]) << 8) |
                        (static_cast<int32_t>(buf[pp + j * 3 + 2]) << 16);
            if (v >= 8388608) v -= 16777216;  // sign-extend 24-bit
            g.means[i * 3 + j] = static_cast<float>(v) * inv_frac;
        }
        for (int j = 0; j < 3; j++)  // scales: log space
            g.scales[i * 3 + j] = static_cast<float>(buf[scale_ofs + i * 3 + j]) / 16.0f - 10.0f;

        float qx = 0, qy = 0, qz = 0, qw = 0;
        if (uses_st) {  // v3: smallest-three
            const size_t r = rot_ofs + i * 4;
            uint32_t packed = static_cast<uint32_t>(buf[r]) | (static_cast<uint32_t>(buf[r + 1]) << 8) |
                              (static_cast<uint32_t>(buf[r + 2]) << 16) | (static_cast<uint32_t>(buf[r + 3]) << 24);
            const uint32_t i_largest = (packed >> 30) & 3u;
            uint32_t work = packed;
            float ss = 0;
            for (int axis = 3; axis >= 0; axis--) {
                if (static_cast<uint32_t>(axis) != i_largest) {
                    const uint32_t mag = work & C_MASK;
                    const uint32_t negbit = (work >> 9) & 1u;
                    work >>= 10;
                    float val = INV_SQRT2 * (static_cast<float>(mag) / static_cast<float>(C_MASK));
                    if (negbit) val = -val;
                    if (axis == 0) qx = val;
                    else if (axis == 1) qy = val;
                    else if (axis == 2) qz = val;
                    else qw = val;
                    ss += val * val;
                }
            }
            const float large = std::sqrt(std::max(0.0f, 1.0f - ss));
            if (i_largest == 0) qx = large;
            else if (i_largest == 1) qy = large;
            else if (i_largest == 2) qz = large;
            else qw = large;
        } else {  // v1/v2: 3 bytes, recover w
            const size_t r = rot_ofs + i * 3;
            qx = static_cast<float>(buf[r]) / 127.5f - 1.0f;
            qy = static_cast<float>(buf[r + 1]) / 127.5f - 1.0f;
            qz = static_cast<float>(buf[r + 2]) / 127.5f - 1.0f;
            qw = std::sqrt(std::max(0.0f, 1.0f - qx * qx - qy * qy - qz * qz));
        }
        g.quats[i * 4] = qw;  // WXYZ
        g.quats[i * 4 + 1] = qx;
        g.quats[i * 4 + 2] = qy;
        g.quats[i * 4 + 3] = qz;

        float a = static_cast<float>(buf[alpha_ofs + i]) / 255.0f;  // alpha -> logit
        a = std::min(std::max(a, EPS), 1.0f - EPS);
        g.opacity[i] = std::log(a / (1.0f - a));

        for (int j = 0; j < 3; j++)  // color -> SH0
            g.sh_dc[i * 3 + j] = (static_cast<float>(buf[color_ofs + i * 3 + j]) / 255.0f - 0.5f) / COLOR_SCALE;

        if (sh_dim > 0) {  // SH rest: bytes are [kk*3+ch]; store channel-grouped [ch*sh_dim+kk]
            const size_t sb = sh_ofs + i * static_cast<size_t>(sh_dim) * 3;
            for (int kk = 0; kk < sh_dim; kk++)
                for (int ch = 0; ch < 3; ch++)
                    g.sh_rest[i * g.num_rest + static_cast<size_t>(ch) * sh_dim + kk] =
                        (static_cast<float>(buf[sb + kk * 3 + ch]) - 128.0f) / 128.0f;
        }
    }
    return g;
}

}  // namespace

void register_spz(nb::module_ &m) {
    m.def("read_spz", &read_spz, "data"_a,
          "Decode a Niantic SPZ file (gzip legacy v1/v2/v3) into a GaussianCloud.");
}
