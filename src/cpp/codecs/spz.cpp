// Niantic SPZ codec (formats_survey.md §4). Two on-disk containers share the
// SAME per-attribute quantization ("packed" sections); only the framing differs:
//   * legacy gzip (v1/v2/v3): one gzip stream over a 16B header + the
//     contiguous sections.
//   * NGSP v4: an uncompressed 32B header + a TOC, then each attribute section
//     as its own independent zstd stream (no gzip).
//
// 16B legacy header:
//   magic u32 (NGSP) | version u32 | num_points u32 |
//   sh_degree u8 | fractional_bits u8 | flags u8 | reserved u8
// 32B NGSP v4 header:
//   magic u32 | version u32 | num_points u32 | sh_degree u8 | fractional_bits u8 |
//   flags u8 | num_streams u8 | toc_byte_offset u32 | reserved[12]
//   then TOC = num_streams * (compressed_len u64, uncompressed_len u64), then
//   the concatenated zstd frames.
// Sections (identical in both containers, in stream order): positions(9N,
// 24-bit signed fixed point) alphas(N) colors(3N) scales(3N)
// rotations(rot_stride*N) sh(sh_dim*3*N). The section quantize/dequantize is
// shared by v3 and v4; the exact math mirrors gsply's reference decode/encode.
#include <algorithm>
#include <cmath>
#include <vector>

#include <zstd.h>

#include "io/gzip.hpp"
#include "records/gaussian_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint32_t NGSP_MAGIC = 0x5053474Eu;  // "NGSP" little-endian
constexpr uint32_t NGSP_HEADER_SIZE = 32u;    // v4 uncompressed header size
constexpr int DEFAULT_ZSTD_LEVEL = 12;        // matches the Niantic reference / gsply
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

// Dequantize a contiguous packed-sections buffer (positions | alphas | colors |
// scales | rotations | sh) into a GaussianCloud. Shared by the legacy gzip and
// NGSP v4 readers — only the container framing differs upstream of this.
GaussianCloud decode_spz_payload(const uint8_t *buf, size_t n, int sh_degree,
                                 int frac_bits, bool uses_st, size_t rot_stride) {
    const int sh_dim = sh_dim_for_degree(sh_degree);
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
        if (uses_st) {  // v3/v4: smallest-three
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

// Read a legacy gzip-container SPZ (v1/v2/v3): one gzip stream over the 16B
// header + contiguous packed sections.
GaussianCloud read_legacy_spz(const uint8_t *fp, size_t fn) {
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
    return decode_spz_payload(raw.data() + 16, n, sh_degree, frac_bits, uses_st, rot_stride);
}

// Per-section uncompressed byte sizes, in the canonical stream order (empty
// sections carry no stream — mirrors gsply's _section_layout).
std::vector<size_t> section_sizes(size_t n, int sh_dim, size_t rot_stride) {
    return {9 * n, 1 * n, 3 * n, 3 * n, rot_stride * n, static_cast<size_t>(sh_dim) * 3 * n};
}

// Read an NGSP v4 container (uncompressed header + TOC + per-section zstd
// streams). Decompresses each stream, reassembles the contiguous packed
// payload, then shares decode_spz_payload with the legacy reader.
GaussianCloud read_ngsp_v4(const uint8_t *fp, size_t fn) {
    if (fn < NGSP_HEADER_SIZE) throw std::invalid_argument("SPZ v4: NGSP file too small");
    LeReader r(fp, fn);
    const uint32_t magic = r.get<uint32_t>();
    const uint32_t version = r.get<uint32_t>();
    const uint32_t num_points = r.get<uint32_t>();
    const uint8_t sh_degree = r.get<uint8_t>();
    const uint8_t frac_bits = r.get<uint8_t>();
    r.get<uint8_t>();  // flags (unused)
    const uint8_t num_streams = r.get<uint8_t>();
    const uint32_t toc_off = r.get<uint32_t>();  // 12 reserved bytes follow, indexed past via toc_off
    if (magic != NGSP_MAGIC) throw std::invalid_argument("SPZ v4: bad NGSP magic");
    if (version != 4) throw std::invalid_argument("SPZ: unsupported NGSP version " + std::to_string(version));
    if (frac_bits < 1 || frac_bits > 24) throw std::invalid_argument("SPZ v4: invalid fractional_bits");

    const size_t n = num_points;
    const int sh_dim = sh_dim_for_degree(sh_degree);
    const size_t rot_stride = 4;  // v4 always uses smallest-three quaternions
    // Non-empty sections carry a stream, in canonical order.
    std::vector<size_t> sizes = section_sizes(n, sh_dim, rot_stride);
    std::vector<size_t> stream_usizes;
    for (size_t sz : sizes)
        if (sz > 0) stream_usizes.push_back(sz);
    if (static_cast<size_t>(num_streams) != stream_usizes.size())
        throw std::invalid_argument("SPZ v4: NGSP stream count mismatch");

    const size_t toc_end = static_cast<size_t>(toc_off) + static_cast<size_t>(num_streams) * 16;
    if (toc_off < NGSP_HEADER_SIZE || toc_end > fn)
        throw std::invalid_argument("SPZ v4: NGSP TOC out of bounds");

    // Compressed streams are concatenated after the TOC; offsets are cumulative.
    size_t total = 0;
    for (size_t u : stream_usizes) total += u;
    std::vector<uint8_t> payload;
    payload.reserve(total);
    size_t offset = toc_end;
    LeReader toc(fp + toc_off, static_cast<size_t>(num_streams) * 16);
    for (size_t i = 0; i < stream_usizes.size(); i++) {
        const uint64_t csize = toc.get<uint64_t>();
        const uint64_t usize = toc.get<uint64_t>();
        if (usize != stream_usizes[i]) throw std::invalid_argument("SPZ v4: NGSP stream size mismatch");
        // `offset <= fn` is invariant (toc_end <= fn, offset grows only by an accepted
        // csize), so compare via subtraction — `offset + csize` could overflow on a
        // crafted 64-bit TOC value and defeat the guard (heap OOB read).
        if (csize > fn - offset) throw std::invalid_argument("SPZ v4: NGSP stream overruns file");
        std::vector<uint8_t> chunk(static_cast<size_t>(usize));
        const size_t got = ZSTD_decompress(chunk.data(), chunk.size(), fp + offset, static_cast<size_t>(csize));
        if (ZSTD_isError(got))
            throw std::invalid_argument(std::string("SPZ v4: zstd decompress failed: ") + ZSTD_getErrorName(got));
        if (got != usize) throw std::invalid_argument("SPZ v4: NGSP decompressed size mismatch");
        payload.insert(payload.end(), chunk.begin(), chunk.end());
        offset += csize;
    }
    return decode_spz_payload(payload.data(), n, sh_degree, frac_bits, /*uses_st=*/true, rot_stride);
}

GaussianCloud read_spz(nb::bytes data) {
    const uint8_t *fp = reinterpret_cast<const uint8_t *>(data.c_str());
    const size_t fn = data.size();
    if (fn >= 4) {
        uint32_t m;
        std::memcpy(&m, fp, 4);
        if (m == NGSP_MAGIC) return read_ngsp_v4(fp, fn);  // raw NGSP magic -> v4 zstd container
    }
    return read_legacy_spz(fp, fn);
}

// Quantize a GaussianCloud into the canonical SPZ sections (positions | alphas |
// colors | scales | rotations | [sh]), appended in stream order. Shared by the
// v3 gzip and v4 NGSP writers; the exact math mirrors gsply's reference encode.
void encode_sections(const GaussianCloud &g, int fractional_bits, int sh_dim,
                     std::vector<std::vector<uint8_t>> &sections) {
    const size_t n = g.n;
    auto clampb = [](float f) -> uint8_t {
        return static_cast<uint8_t>(std::min(std::max(f, 0.0f), 255.0f));
    };

    // positions (9N): round(mean * 2^frac), clip to signed 24-bit, 3 bytes LE
    std::vector<uint8_t> pos;
    pos.reserve(n * 9);
    const float pscale = static_cast<float>(1u << fractional_bits);
    for (size_t i = 0; i < n * 3; i++) {
        float f = std::min(std::max(std::nearbyintf(g.means[i] * pscale), -8388608.0f), 8388607.0f);
        int32_t q = static_cast<int32_t>(f) & 0xFFFFFF;
        pos.push_back(static_cast<uint8_t>(q & 0xff));
        pos.push_back(static_cast<uint8_t>((q >> 8) & 0xff));
        pos.push_back(static_cast<uint8_t>((q >> 16) & 0xff));
    }
    sections.push_back(std::move(pos));

    // alphas (N): sigmoid(opacity) -> byte
    std::vector<uint8_t> alpha;
    alpha.reserve(n);
    for (size_t i = 0; i < n; i++)
        alpha.push_back(clampb(std::nearbyintf(1.0f / (1.0f + std::exp(-g.opacity[i])) * 255.0f)));
    sections.push_back(std::move(alpha));

    // colors (3N): sh_dc -> byte
    std::vector<uint8_t> color;
    color.reserve(n * 3);
    const float cmul = static_cast<float>(0.15 * 255.0);
    for (size_t i = 0; i < n * 3; i++) color.push_back(clampb(std::nearbyintf(g.sh_dc[i] * cmul + 127.5f)));
    sections.push_back(std::move(color));

    // scales (3N): (log_scale + 10) * 16 -> byte
    std::vector<uint8_t> scl;
    scl.reserve(n * 3);
    for (size_t i = 0; i < n * 3; i++) scl.push_back(clampb(std::nearbyintf((g.scales[i] + 10.0f) * 16.0f)));
    sections.push_back(std::move(scl));

    // rotations (4N): smallest-three pack of xyzw
    std::vector<uint8_t> rot;
    rot.reserve(n * 4);
    for (size_t i = 0; i < n; i++) {
        float q[4] = {g.quats[i * 4 + 1], g.quats[i * 4 + 2], g.quats[i * 4 + 3], g.quats[i * 4]};  // xyzw
        float norm = std::sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
        if (!(norm > 0.0f)) { q[0] = q[1] = q[2] = 0.0f; q[3] = 1.0f; norm = 1.0f; }  // degenerate -> identity
        for (float &c : q) c /= norm;
        int lg = 0;
        for (int k = 1; k < 4; k++)
            if (std::fabs(q[k]) > std::fabs(q[lg])) lg = k;
        float sgn = q[lg] < 0.0f ? -1.0f : 1.0f;
        for (float &c : q) c *= sgn;
        uint32_t packed = 0;
        for (int axis = 0; axis < 4; axis++) {
            if (axis == lg) continue;
            float m = std::nearbyintf(static_cast<float>(C_MASK) * std::fabs(q[axis]) / INV_SQRT2);
            uint32_t mag = static_cast<uint32_t>(std::min(std::max(m, 0.0f), static_cast<float>(C_MASK)));
            packed = (packed << 10) | ((q[axis] < 0.0f ? 1u : 0u) << 9) | mag;
        }
        packed |= static_cast<uint32_t>(lg) << 30;
        for (int k = 0; k < 4; k++) rot.push_back(static_cast<uint8_t>((packed >> (8 * k)) & 0xff));
    }
    sections.push_back(std::move(rot));

    // sh (sh_dim*3*N): our channel-grouped [ch*sh_dim+kk] -> file's [kk*3+ch]
    if (sh_dim > 0) {
        std::vector<uint8_t> sh;
        sh.reserve(n * static_cast<size_t>(sh_dim) * 3);
        for (size_t i = 0; i < n; i++)
            for (int kk = 0; kk < sh_dim; kk++)
                for (int ch = 0; ch < 3; ch++)
                    sh.push_back(clampb(std::nearbyintf(
                        g.sh_rest[i * g.num_rest + static_cast<size_t>(ch) * sh_dim + kk] * 128.0f + 128.0f)));
        sections.push_back(std::move(sh));
    }
}

// Encode a GaussianCloud into SPZ bytes. version==3 writes the legacy gzip
// container (smallest-three quats); version==4 writes the NGSP zstd container
// (per-section independent zstd streams). Both share encode_sections().
nb::bytes write_spz(const GaussianCloud &g, int version, int fractional_bits, int zstd_level) {
    if (version != 3 && version != 4)
        throw std::invalid_argument("write_spz: only version 3 (gzip) or 4 (zstd) is supported");
    if (fractional_bits < 1 || fractional_bits > 24)
        throw std::invalid_argument("write_spz: fractional_bits must be 1..24");
    const size_t n = g.n;
    const int sh_dim = static_cast<int>(g.num_rest / 3);
    const int sh_degree = sh_dim == 0 ? 0 : (sh_dim == 3 ? 1 : (sh_dim == 8 ? 2 : 3));

    std::vector<std::vector<uint8_t>> sections;
    encode_sections(g, fractional_bits, sh_dim, sections);

    if (version == 3) {
        LeWriter w;  // 16-byte header (gzipped together with the payload)
        w.put<uint32_t>(NGSP_MAGIC);
        w.put<uint32_t>(3);
        w.put<uint32_t>(static_cast<uint32_t>(n));
        w.put<uint8_t>(static_cast<uint8_t>(sh_degree));
        w.put<uint8_t>(static_cast<uint8_t>(fractional_bits));
        w.put<uint8_t>(0);
        w.put<uint8_t>(0);
        for (const auto &sec : sections)
            w.out.append(reinterpret_cast<const char *>(sec.data()), sec.size());
        std::string gz = gzip_compress(reinterpret_cast<const uint8_t *>(w.out.data()), w.out.size());
        return nb::bytes(gz.data(), gz.size());
    }

    // version == 4: NGSP zstd container — compress each non-empty section
    // independently, then assemble header + TOC + concatenated frames.
    std::vector<std::vector<uint8_t>> streams;  // one zstd frame per non-empty section
    std::vector<size_t> usizes;
    streams.reserve(sections.size());
    usizes.reserve(sections.size());
    for (const auto &sec : sections) {
        if (sec.empty()) continue;  // gsply carries no stream for an empty section
        const size_t bound = ZSTD_compressBound(sec.size());
        std::vector<uint8_t> comp(bound);
        const size_t clen = ZSTD_compress(comp.data(), bound, sec.data(), sec.size(), zstd_level);
        if (ZSTD_isError(clen))
            throw std::runtime_error(std::string("write_spz: zstd compress failed: ") + ZSTD_getErrorName(clen));
        comp.resize(clen);
        streams.push_back(std::move(comp));
        usizes.push_back(sec.size());
    }
    const uint32_t num_streams = static_cast<uint32_t>(streams.size());

    LeWriter w;  // 32-byte uncompressed header
    w.put<uint32_t>(NGSP_MAGIC);
    w.put<uint32_t>(4);
    w.put<uint32_t>(static_cast<uint32_t>(n));
    w.put<uint8_t>(static_cast<uint8_t>(sh_degree));
    w.put<uint8_t>(static_cast<uint8_t>(fractional_bits));
    w.put<uint8_t>(0);                              // flags
    w.put<uint8_t>(static_cast<uint8_t>(num_streams));
    w.put<uint32_t>(NGSP_HEADER_SIZE);             // toc_byte_offset (no extensions)
    for (int i = 0; i < 12; i++) w.put<uint8_t>(0);  // reserved
    for (uint32_t i = 0; i < num_streams; i++) {   // TOC: (compressed_len, uncompressed_len)
        w.put<uint64_t>(static_cast<uint64_t>(streams[i].size()));
        w.put<uint64_t>(static_cast<uint64_t>(usizes[i]));
    }
    for (const auto &s : streams)
        w.out.append(reinterpret_cast<const char *>(s.data()), s.size());
    return nb::bytes(w.out.data(), w.out.size());
}

}  // namespace

void register_spz(nb::module_ &m) {
    m.def("read_spz", &read_spz, "data"_a,
          "Decode a Niantic SPZ file (gzip legacy v1/v2/v3 or NGSP v4 zstd) into a GaussianCloud.");
    m.def("write_spz", &write_spz, "cloud"_a, "version"_a = 3, "fractional_bits"_a = 12,
          "zstd_level"_a = DEFAULT_ZSTD_LEVEL,
          "Encode a GaussianCloud to Niantic SPZ bytes (v3 gzip or v4 NGSP zstd, smallest-three).");
}
