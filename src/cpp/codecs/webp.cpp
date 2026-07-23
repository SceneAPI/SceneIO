// codecs/webp.cpp — WebP <-> Image (uint8 sRGB) via libwebp (BSD), built from
// source into _core. Read decodes VP8 (lossy) / VP8L (lossless) to RGB (C=3) or
// RGBA (C=4, straight alpha) depending on whether the file carries alpha. Write
// defaults to LOSSLESS with config.exact=1 (so RGB samples under alpha=0 are kept).
// Round-trip is byte-exact for RGB and for RGBA that carries actual transparency;
// a FULLY-OPAQUE alpha channel (all 255) is dropped by the format itself — WebP
// stores a single "alpha is used" bit that its encoder derives from a pixel scan,
// with no knob to force it — so such an image round-trips to 3-channel RGB with
// identical RGB values. WebP has no grayscale plane and no 16-bit/float, so C=1 /
// uint16 / float32 are refused (not expanded), and animated WebP is rejected.
// Decode/encode run with the GIL released; the decoder's malloc'd buffer and the
// encoder's picture/writer are freed via RAII.
#include <string>

#include "records/image.hpp"
#include "webp/decode.h"
#include "webp/encode.h"

using namespace nb::literals;
using namespace sio;

namespace {
// 250 MP, matching the other image codecs; a WebP decode-bomb is format-bounded to
// 16384^2 (~1 GB) anyway, and this rejects that largest legal raster consistently.
constexpr uint64_t kWebpPixelCap = 250000000ull;

Image read_webp(nb::handle source) {
    sio::ByteView data(source);
    const uint8_t *in = data.data();
    const size_t size = data.size();
    Image im;
    {
        nb::gil_scoped_release rel;  // pure-C++ decode; no Python objects touched
        WebPBitstreamFeatures feat;
        if (WebPGetFeatures(in, size, &feat) != VP8_STATUS_OK)
            throw std::invalid_argument("webp: not a valid WebP stream");
        if (feat.has_animation)
            throw std::invalid_argument("webp: animated WebP is not supported");
        if (feat.width <= 0 || feat.height <= 0 ||
            static_cast<uint64_t>(feat.width) * feat.height > kWebpPixelCap)
            throw std::invalid_argument("webp: image dimensions exceed the supported limit");

        int w = 0, h = 0;
        uint8_t *px = feat.has_alpha ? WebPDecodeRGBA(in, size, &w, &h)
                                     : WebPDecodeRGB(in, size, &w, &h);
        struct Guard {
            uint8_t **p;
            ~Guard() { WebPFree(*p); }
        } g{&px};
        if (!px) throw std::invalid_argument("webp: decode failed");

        const size_t C = feat.has_alpha ? 4 : 3;
        im.height = static_cast<size_t>(h);
        im.width = static_cast<size_t>(w);
        im.channels = C;
        im.dtype = PixelType::U8;
        im.color_space = "srgb";
        im.alpha_mode = feat.has_alpha ? "straight" : "none";
        im.maxval = 255;
        im.u8.assign(px, px + static_cast<size_t>(w) * h * C);
    }
    return im;
}

nb::bytes write_webp(const Image &img, bool lossless, float quality) {
    // --- guards: refuse what WebP cannot represent (never convert) ---
    if (img.dtype != PixelType::U8)
        throw std::invalid_argument("webp: WebP stores 8-bit samples (got " +
                                    std::string(image_dtype_name(img.dtype)) + ")");
    if (img.maxval != 255)
        throw std::invalid_argument("webp: requires maxval 255 (partial-range record — convert first)");
    const size_t C = img.channels;
    if (C != 3 && C != 4)
        throw std::invalid_argument(
            "webp: only 3-channel RGB or 4-channel RGBA is supported (WebP has no grayscale plane)");
    if (img.color_space != "srgb")
        throw std::invalid_argument("webp: requires color_space 'srgb' (got '" + img.color_space + "')");
    if (C == 4 && img.alpha_mode != "straight")
        throw std::invalid_argument(
            "webp: RGBA WebP requires alpha_mode 'straight' (got '" + img.alpha_mode + "')");
    if (img.width == 0 || img.height == 0)
        throw std::invalid_argument("webp: cannot write a zero-dimension image");
    if (img.width > 16383 || img.height > 16383)
        throw std::invalid_argument("webp: WebP dimensions are limited to 16383 per axis");
    if (!lossless && !(quality >= 0.0f && quality <= 100.0f))  // negated form also rejects NaN
        throw std::invalid_argument("webp: quality must be in 0..100");

    std::string out;
    {
        nb::gil_scoped_release rel;  // nb::bytes built after the scope, under the GIL
        WebPConfig config;
        if (!WebPConfigInit(&config))
            throw std::invalid_argument("webp: config init failed (ABI mismatch?)");
        if (lossless) {
            config.lossless = 1;
            config.quality = 100.0f;  // for lossless, quality drives the compression effort
            config.exact = 1;         // preserve RGB under alpha=0 -> byte-exact lossless round-trip
        } else {
            config.quality = quality;
        }
        if (!WebPValidateConfig(&config))
            throw std::invalid_argument("webp: invalid encoder configuration");
        WebPPicture pic;
        if (!WebPPictureInit(&pic))
            throw std::invalid_argument("webp: picture init failed");
        struct PicGuard {
            WebPPicture *p;
            ~PicGuard() { WebPPictureFree(p); }
        } pg{&pic};
        pic.use_argb = 1;  // required for lossless; harmless for lossy
        pic.width = static_cast<int>(img.width);
        pic.height = static_cast<int>(img.height);
        const int stride = static_cast<int>(img.width * C);
        const int ok = (C == 4) ? WebPPictureImportRGBA(&pic, img.u8.data(), stride)
                                : WebPPictureImportRGB(&pic, img.u8.data(), stride);
        if (!ok) throw std::invalid_argument("webp: picture import failed (out of memory?)");

        WebPMemoryWriter writer;
        WebPMemoryWriterInit(&writer);
        struct WrGuard {
            WebPMemoryWriter *w;
            ~WrGuard() { WebPMemoryWriterClear(w); }
        } wg{&writer};
        pic.writer = WebPMemoryWrite;
        pic.custom_ptr = &writer;
        if (!WebPEncode(&config, &pic))
            throw std::invalid_argument("webp: encode failed (error " +
                                        std::to_string(static_cast<int>(pic.error_code)) + ")");
        out.assign(reinterpret_cast<const char *>(writer.mem), writer.size);
    }
    return emit_bytes(out.data(), out.size());
}

}  // namespace

void register_webp(nb::module_ &m) {
    m.def("read_webp", &read_webp, "data"_a,
          "Decode WebP bytes into an Image (uint8 sRGB; RGB, or RGBA with straight alpha when the "
          "file has alpha). Animated WebP raises.");
    m.def("write_webp", &write_webp, "img"_a, "lossless"_a = true, "quality"_a = 90.0f,
          "Encode a uint8 sRGB RGB/RGBA Image to WebP bytes. Lossless by default (exact=1): RGB "
          "and transparent RGBA round-trip byte-exactly, but a fully-opaque alpha channel is "
          "dropped to RGB by the format. Lossy when lossless=False (quality 0..100). Refuses "
          "non-uint8, grayscale (no WebP gray plane), and non-straight alpha.");
}
