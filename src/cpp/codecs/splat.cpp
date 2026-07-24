// codecs/splat.cpp — antimatter15 ".splat" 3D-Gaussian codec into the shared
// GaussianCloud record (records/gaussian_cloud.hpp), a quantized sibling of
// spz.cpp. The format is a HEADERLESS flat array of 32-byte records, one per
// Gaussian, little-endian:
//   [0,12)   float32 position[3]       -> means (direct)
//   [12,24)  float32 scale[3] (LINEAR) -> GaussianCloud.scales = log(scale)
//   [24,28)  uint8   color[4] = RGBA   -> rgb: sh_dc = (c/255 - 0.5)/SH_C0 ;
//                                          A: opacity = logit(a/255)
//   [28,32)  uint8   rot[4] in WXYZ    -> q[k] = (byte-128)/128, normalize
// Record count n = filesize/32; a size not divisible by 32 raises.
//
// PROVENANCE / conventions (verified against antimatter15/splat convert.py +
// main.js and gsplat's export_splats): rot byte order is WXYZ (main.js reads
// byte 28 as the scalar w); SH_C0 = 1/(2*sqrt(pi)) = 0.28209479177387814 (the DC
// SH scaling, NOT spz's COLOR_SCALE=0.15). Activation math mirrors spz.cpp: the
// same EPS alpha clamp before logit and the degenerate-quat -> identity guard.
//
// Deviations from the reference writer, both intentional: we round with
// nearbyintf (the reference truncates via clip+astype(uint8), a <=1 u8-LSB
// difference) so read->write->read is stable; and we do NOT importance-sort on
// write (row order is non-semantic — viewers depth-sort at render time). LOSSY:
// SH bands above DC (sh_degree>0) cannot be represented and are dropped with
// this documented note (both reference writers accept degree-3 clouds), rather
// than rejected — down-converting trained models for web viewers is the point.
// The pure-C++ decode/encode runs with the GIL released (flo.cpp precedent).
#include <algorithm>
#include <cmath>

#include "records/gaussian_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
constexpr size_t kRecordSize = 32;
constexpr float SH_C0 = 0.28209479177387814f;  // 1/(2*sqrt(pi)); antimatter15/gsplat DC scaling
constexpr float EPS = 1e-6f;                    // alpha clamp before logit (spz.cpp)
constexpr float kScaleFloor = 1e-30f;           // guard scale<=0 on read: log(1e-30) ~ -69

GaussianCloud read_splat_impl(nb::handle source, bool partial, size_t start,
                              size_t stop) {
    sio::ByteView data(source);
    const uint8_t *p = data.data();
    const size_t fn = data.size();
    GaussianCloud g;
    {
        nb::gil_scoped_release rel;  // pure-C++ decode; no Python objects touched
        if (fn % kRecordSize != 0)
            throw std::invalid_argument("splat: file size " + std::to_string(fn) +
                                        " is not a multiple of the 32-byte record");
        const size_t total = fn / kRecordSize;
        if (!partial) {
            start = 0;
            stop = total;
        } else {
            checked_half_open_range(start, stop, total,
                                    "splat point range");
        }
        const size_t n = stop - start;
        g.n = n;
        g.sh_degree = 0;
        g.num_rest = 0;
        g.means.resize(n * 3);
        g.scales.resize(n * 3);
        g.quats.resize(n * 4);
        g.opacity.resize(n);
        g.sh_dc.resize(n * 3);
        for (size_t i = 0; i < n; i++) {
            const uint8_t *rec = p + (start + i) * kRecordSize;
            float f[6];
            std::memcpy(f, rec, 24);  // pos[3] + LINEAR scale[3], little-endian
            for (int j = 0; j < 3; j++) {
                g.means[i * 3 + j] = f[j];
                g.scales[i * 3 + j] = std::log(std::max(f[3 + j], kScaleFloor));  // LINEAR -> LOG
                g.sh_dc[i * 3 + j] = (static_cast<float>(rec[24 + j]) / 255.0f - 0.5f) / SH_C0;
            }
            float a = static_cast<float>(rec[27]) / 255.0f;
            a = std::min(std::max(a, EPS), 1.0f - EPS);  // keep logit finite (spz.cpp)
            g.opacity[i] = std::log(a / (1.0f - a));
            float q[4];
            for (int k = 0; k < 4; k++) q[k] = (static_cast<float>(rec[28 + k]) - 128.0f) / 128.0f;  // WXYZ
            float norm = std::sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
            if (!(norm > 0.0f)) { q[0] = 1.0f; q[1] = q[2] = q[3] = 0.0f; norm = 1.0f; }  // degenerate -> identity
            for (int k = 0; k < 4; k++) g.quats[i * 4 + k] = q[k] / norm;
        }
    }
    return g;
}

GaussianCloud read_splat(nb::handle source) {
    return read_splat_impl(source, false, 0, 0);
}

GaussianCloud read_splat_points(nb::handle source, size_t start, size_t stop) {
    return read_splat_impl(source, true, start, stop);
}

nb::bytes write_splat(const GaussianCloud &g) {
    std::string out;
    {
        nb::gil_scoped_release rel;  // pure-C++ encode; reads only the record's C++ vectors
        out.reserve(g.n * kRecordSize);
        auto put_f32 = [&out](float v) { out.append(reinterpret_cast<const char *>(&v), 4); };  // LE host
        auto clampb = [](float f) {  // fmin/fmax return the non-NaN operand -> NaN maps to 0, so the float->uint8 cast is always defined (a NaN sh_dc/opacity/quat from a down-converted PLY would otherwise be UB)
            return static_cast<char>(static_cast<uint8_t>(std::fmin(std::fmax(f, 0.0f), 255.0f)));
        };
        for (size_t i = 0; i < g.n; i++) {
            for (int j = 0; j < 3; j++) put_f32(g.means[i * 3 + j]);
            for (int j = 0; j < 3; j++) put_f32(std::exp(g.scales[i * 3 + j]));  // LOG -> LINEAR
            for (int j = 0; j < 3; j++)
                out.push_back(clampb(std::nearbyintf((0.5f + SH_C0 * g.sh_dc[i * 3 + j]) * 255.0f)));
            out.push_back(clampb(std::nearbyintf(255.0f / (1.0f + std::exp(-g.opacity[i])))));  // sigmoid alpha
            float q[4] = {g.quats[i * 4], g.quats[i * 4 + 1], g.quats[i * 4 + 2], g.quats[i * 4 + 3]};
            float norm = std::sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
            if (!(norm > 0.0f) || !std::isfinite(norm))  // 0- or non-finite-norm (e.g. an inf quat -> inf/inf=NaN) -> identity
                { q[0] = 1.0f; q[1] = q[2] = q[3] = 0.0f; norm = 1.0f; }
            for (int k = 0; k < 4; k++) out.push_back(clampb(std::nearbyintf(q[k] / norm * 128.0f + 128.0f)));
        }
    }
    return emit_bytes(out.data(), out.size());
}
}  // namespace

void register_splat(nb::module_ &m) {
    m.def("read_splat", &read_splat, "data"_a,
          "Decode antimatter15 .splat bytes (headerless 32 B/Gaussian: pos 3xf32, LINEAR scale "
          "3xf32, RGBA u8, quat u8[4] WXYZ) into a GaussianCloud (log scales, logit opacity, sh_dc "
          "via SH_C0=0.28209479...; sh_degree=0).");
    m.def("read_splat_points", &read_splat_points, "data"_a, "start"_a,
          "stop"_a,
          "Decode a non-empty half-open .splat point range without allocating "
          "the full Gaussian cloud.");
    m.def("write_splat", &write_splat, "cloud"_a,
          "Encode a GaussianCloud to antimatter15 .splat bytes. Lossy: color/alpha/rotation "
          "quantize to 8 bits and SH bands above the DC term are discarded; input order is kept.");
}
