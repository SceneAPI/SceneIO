// codecs/hdr.cpp — Radiance RGBE (".hdr") <-> Image via vendored stb (public
// domain / MIT, src/cpp/third_party/stb). HDR is a linear-light HDR raster: on
// disk each pixel is RGBE (a shared 8-bit exponent + 8-bit RGB mantissas), which
// stb decodes losslessly to float32 RGB. We map it to Image{F32, C=3,
// color_space="linear"} — the float sibling of the netpbm/png integer codecs.
//
// Reader: stbi_info first (header-only) to bound dimensions before the pixel
// allocation (a small RLE header can claim a huge raster), then stbi_loadf.
// Writer is LOSSY: RGBE re-quantizes the mantissas to 8 bits per channel (a
// documented ~2^-8 relative error, like the .splat codec), and only RGB is
// representable — float32/linear/3-channel are enforced, everything else raised.
// Decode/encode run GIL-released; stb's malloc'd buffer is freed via RAII.
#include <climits>
#include <cmath>
#include <cstdlib>

#include "records/image.hpp"
#include "stb_config.h"
#include "stb_image.h"
#include "stb_image_write.h"

using namespace nb::literals;
using namespace sio;

namespace {
constexpr uint64_t kStbPixelCap = 250000000ull;  // 250 MP; worst-case f32 RGB buffer ~3 GB
constexpr uint64_t kHdrAxisCap = 1ull << 24;     // stb's reader caps axes at 2^24; keep write symmetric

void guard_dims(size_t w, size_t h, const char *fmt) {
    if (w == 0 || h == 0) throw std::invalid_argument(std::string(fmt) + ": zero-dimension image");
    if (w > kHdrAxisCap || h > kHdrAxisCap || static_cast<uint64_t>(w) * h > kStbPixelCap)
        throw std::invalid_argument(std::string(fmt) + ": image dimensions exceed the supported limit");
}

Image read_hdr(nb::handle source) {
    sio::ByteView data(source);
    const stbi_uc *in = data.data();
    if (data.size() > static_cast<size_t>(INT_MAX))
        throw std::invalid_argument("hdr: input larger than 2 GiB is not supported");
    const int len = static_cast<int>(data.size());
    Image im;
    {
        nb::gil_scoped_release rel;  // pure-C++ decode; no Python objects touched
        // stb sniffs both compiled decoders (JPEG + HDR), so without this a .jpg fed
        // to read_hdr would be gamma-expanded to float and returned. Require the
        // Radiance "#?" signature so only real .hdr streams decode here.
        if (len < 2 || in[0] != '#' || in[1] != '?')
            throw std::invalid_argument("hdr: not a Radiance HDR stream (missing '#?' signature)");
        int w = 0, h = 0, comp = 0;
        if (!stbi_info_from_memory(in, len, &w, &h, &comp))
            throw std::invalid_argument(std::string("hdr: ") + stbi_failure_reason());
        guard_dims(static_cast<size_t>(w), static_cast<size_t>(h), "hdr");

        int n = 0;
        float *px = stbi_loadf_from_memory(in, len, &w, &h, &n, 3);  // force RGB (HDR is RGBE)
        struct Guard {
            float **p;
            ~Guard() { stbi_image_free(*p); }
        } g{&px};
        if (!px) throw std::invalid_argument(std::string("hdr: ") + stbi_failure_reason());

        im.height = static_cast<size_t>(h);
        im.width = static_cast<size_t>(w);
        im.channels = 3;
        im.dtype = PixelType::F32;
        im.color_space = "linear";
        im.alpha_mode = "none";
        im.maxval = 0;
        const size_t cnt = static_cast<size_t>(w) * h * 3;
        im.f32.assign(px, px + cnt);
    }
    return im;
}

nb::bytes write_hdr(const Image &img) {
    // --- guards: refuse what RGBE cannot represent (never convert) ---
    if (img.dtype != PixelType::F32)
        throw std::invalid_argument(
            "hdr: Radiance .hdr stores float32 linear pixels (got " +
            std::string(image_dtype_name(img.dtype)) + "; use png/netpbm for integers)");
    if (img.channels != 3)
        throw std::invalid_argument(
            "hdr: only 3-channel RGB is supported (stb would replicate gray / drop alpha)");
    if (img.color_space != "linear")
        throw std::invalid_argument(
            "hdr: requires color_space 'linear' (got '" + img.color_space + "')");
    guard_dims(img.width, img.height, "hdr");

    std::string out;
    {
        nb::gil_scoped_release rel;  // encode; nb::bytes built after the scope, under the GIL
        // RGBE cannot represent negatives (stb casts a negative float to unsigned char
        // -> UB), non-finite values, or a magnitude >= 2^127 (frexp exponent overflows
        // the 8-bit byte and wraps). Refuse rather than emit garbage (netpbm precedent).
        for (float v : img.f32)
            if (!(std::isfinite(v) && v >= 0.0f && v < 0x1p127f))
                throw std::invalid_argument(
                    "hdr: RGBE cannot store negative, non-finite, or >= 2^127 samples");
        auto cb = [](void *ctx, void *d, int size) {
            static_cast<std::string *>(ctx)->append(static_cast<char *>(d), static_cast<size_t>(size));
        };
        if (!stbi_write_hdr_to_func(cb, &out, static_cast<int>(img.width),
                                    static_cast<int>(img.height), 3, img.f32.data()))
            throw std::invalid_argument("hdr: encode failed");
    }
    return emit_bytes(out.data(), out.size());
}

}  // namespace

void register_hdr(nb::module_ &m) {
    m.def("read_hdr", &read_hdr, "data"_a,
          "Decode Radiance RGBE (.hdr) bytes into an Image (float32, 3-channel RGB, "
          "color_space='linear'). RGBE decode is exact.");
    m.def("write_hdr", &write_hdr, "img"_a,
          "Encode a float32 linear 3-channel Image to Radiance .hdr bytes. LOSSY: RGBE "
          "quantizes the mantissas to 8 bits per channel. Refuses non-float32 / non-linear / "
          "non-RGB records rather than converting.");
}
