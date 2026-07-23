// codecs/jpeg.cpp — baseline/progressive JPEG <-> Image via vendored stb (public
// domain / MIT, src/cpp/third_party/stb). stb decodes JPEG (YCbCr -> RGB, or
// grayscale) to 8-bit; we map it to Image{U8, C in {1,3}}: gray -> "gray",
// color -> "srgb". JPEG has no alpha and is 8-bit only.
//
// Reader: stbi_info first (header-only) to bound dimensions before allocation,
// then stbi_load; supports grayscale (C=1) and color (C=3). Writer is LOSSY (DCT
// quantization at the chosen quality), baseline sequential, and RGB-ONLY: stb's
// encoder always emits 3 components, so grayscale (C=1) is refused rather than
// silently expanded to RGB; it also refuses uint16/float32 and RGBA (no alpha).
// stb's malloc'd buffer is freed via RAII; decode/encode run with the GIL released.
#include <climits>
#include <cstdlib>

#include "records/image.hpp"
#include "stb_config.h"
#include "stb_image.h"
#include "stb_image_write.h"

using namespace nb::literals;
using namespace sio;

namespace {
constexpr uint64_t kStbPixelCap = 250000000ull;  // 250 MP

void guard_dims(size_t w, size_t h) {
    if (w == 0 || h == 0) throw std::invalid_argument("jpeg: zero-dimension image");
    if (w > static_cast<size_t>(INT_MAX) || h > static_cast<size_t>(INT_MAX) ||
        static_cast<uint64_t>(w) * h > kStbPixelCap)
        throw std::invalid_argument("jpeg: image dimensions exceed the supported limit");
}

Image read_jpeg(nb::bytes data) {
    const stbi_uc *in = reinterpret_cast<const stbi_uc *>(data.c_str());
    if (data.size() > static_cast<size_t>(INT_MAX))
        throw std::invalid_argument("jpeg: input larger than 2 GiB is not supported");
    const int len = static_cast<int>(data.size());
    Image im;
    {
        nb::gil_scoped_release rel;
        // stb compiles the JPEG *and* HDR decoders into one library and sniffs both,
        // so without this a .hdr fed to read_jpeg would be tone-mapped to u8 and
        // returned. Require the SOI marker so only real JPEG streams decode here.
        if (len < 2 || in[0] != 0xFF || in[1] != 0xD8)
            throw std::invalid_argument("jpeg: not a JPEG stream (missing FF D8 SOI marker)");
        int w = 0, h = 0, comp = 0;
        if (!stbi_info_from_memory(in, len, &w, &h, &comp))
            throw std::invalid_argument(std::string("jpeg: ") + stbi_failure_reason());
        guard_dims(static_cast<size_t>(w), static_cast<size_t>(h));

        int n = 0;
        stbi_uc *px = stbi_load_from_memory(in, len, &w, &h, &n, 0);  // native channel count
        struct Guard {
            stbi_uc **p;
            ~Guard() { stbi_image_free(*p); }
        } g{&px};
        if (!px) throw std::invalid_argument(std::string("jpeg: ") + stbi_failure_reason());
        if (n != 1 && n != 3)
            throw std::invalid_argument("jpeg: only grayscale or RGB JPEG is supported (got " +
                                        std::to_string(n) + " channels)");

        im.height = static_cast<size_t>(h);
        im.width = static_cast<size_t>(w);
        im.channels = static_cast<size_t>(n);
        im.dtype = PixelType::U8;
        im.color_space = (n == 1) ? "gray" : "srgb";
        im.alpha_mode = "none";
        im.maxval = 255;
        const size_t cnt = static_cast<size_t>(w) * h * n;
        im.u8.assign(px, px + cnt);
    }
    return im;
}

nb::bytes write_jpeg(const Image &img, int quality) {
    // --- guards: refuse what baseline JPEG cannot represent (never convert) ---
    if (img.dtype != PixelType::U8)
        throw std::invalid_argument("jpeg: JPEG stores 8-bit samples (got " +
                                    std::string(image_dtype_name(img.dtype)) +
                                    "; use png for 16-bit / exr for float)");
    if (img.maxval != 255)
        throw std::invalid_argument("jpeg: requires maxval 255 (partial-range record — convert first)");
    // stb's JPEG encoder ALWAYS emits 3 components (for comp==1 it just feeds the
    // single channel into Y/Cb/Cr), so a 1-channel write would silently become a
    // 3-channel JPEG that reads back as RGB. Refuse it rather than convert. (The
    // reader still decodes true grayscale JPEGs to a 1-channel Image.)
    if (img.channels == 3) {
        if (img.color_space != "srgb")
            throw std::invalid_argument(
                "jpeg: 3-channel image requires color_space 'srgb' (got '" + img.color_space +
                "'; convert linear->srgb first)");
    } else if (img.channels == 1) {
        throw std::invalid_argument(
            "jpeg: cannot write a grayscale JPEG — the stb encoder always emits 3 components, so a "
            "1-channel image would silently become RGB. Convert to 3-channel RGB, or use PNG.");
    } else {
        throw std::invalid_argument(
            "jpeg: only 3-channel RGB is writable (JPEG has no alpha; grayscale unsupported by the encoder)");
    }
    if (quality < 1 || quality > 100)
        throw std::invalid_argument("jpeg: quality must be in 1..100");
    // JPEG's SOF header stores dimensions as 16-bit; stb would silently truncate a
    // larger axis and emit a corrupt file, so refuse it (panorama strips hit this).
    if (img.width > 65535 || img.height > 65535)
        throw std::invalid_argument("jpeg: JPEG stores 16-bit dimensions (max 65535 per axis)");
    guard_dims(img.width, img.height);

    std::string out;
    {
        nb::gil_scoped_release rel;
        auto cb = [](void *ctx, void *d, int size) {
            static_cast<std::string *>(ctx)->append(static_cast<char *>(d), static_cast<size_t>(size));
        };
        if (!stbi_write_jpg_to_func(cb, &out, static_cast<int>(img.width),
                                    static_cast<int>(img.height), static_cast<int>(img.channels),
                                    img.u8.data(), quality))
            throw std::invalid_argument("jpeg: encode failed");
    }
    return nb::bytes(out.data(), out.size());
}

}  // namespace

void register_jpeg(nb::module_ &m) {
    m.def("read_jpeg", &read_jpeg, "data"_a,
          "Decode JPEG bytes into an Image (uint8; grayscale -> 1-channel 'gray', color -> "
          "3-channel 'srgb'). Baseline and progressive JPEG are supported. NOTE: CMYK/YCCK "
          "JPEGs are converted to approximate 3-channel RGB by the stb decoder (not color-managed).");
    m.def("write_jpeg", &write_jpeg, "img"_a, "quality"_a = 95,
          "Encode a uint8 3-channel sRGB Image to baseline JPEG bytes at the given quality "
          "(1..100, default 95). LOSSY (DCT quantization). RGB-only: refuses grayscale (the stb "
          "encoder can't write true 1-channel JPEG), uint16/float32, and RGBA.");
}
