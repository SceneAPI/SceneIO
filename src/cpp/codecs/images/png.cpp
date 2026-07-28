// codecs/images/png.cpp -- PNG <-> Image via vendored lodepng (zlib license,
// src/cpp/third_party/lodepng; COMMIT.txt pins the source). lodepng carries its
// own self-contained inflate/deflate (lodepng_*-prefixed, no interaction with
// our miniz), so this is the tier's zero-risk "vendored third-party lib builds
// in the wheel" spike. Decode/encode run with the GIL released (flo/splat
// precedent); nb::bytes is built afterward, under the GIL.
//
// Reader: inspect IHDR first (a decompression-bomb guard — a tiny PNG can claim
// a huge raster), then decode to the file's own color mode and CONVERT to a
// supported Image target. Supported: gray 8/16, RGB 8/16, RGBA 8/16, and
// palette (expanded to RGB, or RGBA when the palette carries transparency).
// 16-bit samples are big-endian on disk (PNG/lodepng) -> native uint16.
// REJECTED (clear error, never a silent lossy conversion): sub-8-bit grayscale,
// grayscale+alpha (2-channel), and colorkey tRNS on non-palette images.
//
// Writer: guards conventions PNG can't represent (float32; linear color_space;
// premultiplied alpha; a partial maxval range) rather than converting, mirrors
// the netpbm writer discipline, and writes exactly the declared color type
// (auto_convert=0) so the bytes are deterministic and oracle-pinnable.
#include <cstdlib>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>

#include "lodepng.h"
#include "records/depth_map.hpp"
#include "records/image.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
// Bomb guards, checked against IHDR before the pixel allocation. 250 MP covers
// any real photo/render (a 16K x 16K image is 256 MP); worst-case decode buffer
// at RGBA16 (8 B/px) stays a few GB, and anything larger is refused up front.
constexpr uint64_t kPngPixelCap = 250000000ull;
constexpr unsigned kPngAxisCap = 200000u;

inline void be16_to_native(const unsigned char *src, uint16_t *dst, size_t n,
                           size_t lanes) {
    parallel_for_blocks(n, lanes, 262144,
                        [&](size_t begin, size_t end, size_t) {
        for (size_t i = begin; i < end; ++i)
            dst[i] = static_cast<uint16_t>(
                (static_cast<uint16_t>(src[2 * i]) << 8) |
                static_cast<uint16_t>(src[2 * i + 1]));
    });
}

inline void native_to_be16(const uint16_t *src, unsigned char *dst, size_t n,
                           size_t lanes) {
    parallel_for_blocks(n, lanes, 262144,
                        [&](size_t begin, size_t end, size_t) {
        for (size_t i = begin; i < end; ++i) {
            dst[2 * i] =
                static_cast<unsigned char>((src[i] >> 8) & 0xff);
            dst[2 * i + 1] = static_cast<unsigned char>(src[i] & 0xff);
        }
    });
}

Image read_png(nb::handle source, size_t lanes) {
    sio::ByteView data(source);
    const unsigned char *in = data.data();
    const size_t insize = data.size();
    Image im;
    {
        nb::gil_scoped_release rel;  // pure-C++ decode; no Python objects touched
        LodePNGState state;
        lodepng_state_init(&state);
        unsigned char *raw = nullptr;
        // free the malloc'd raw buffer and the state on ANY exit (incl. throw)
        struct Guard {
            LodePNGState *s;
            unsigned char **r;
            ~Guard() {
                lodepng_state_cleanup(s);
                free(*r);
            }
        } guard{&state, &raw};

        // 1. inspect IHDR only (cheap) to bound dimensions before decoding pixels
        unsigned w = 0, h = 0;
        if (unsigned e = lodepng_inspect(&w, &h, &state, in, insize))
            throw std::invalid_argument(std::string("png: ") + lodepng_error_text(e));
        if (w == 0 || h == 0) throw std::invalid_argument("png: zero-dimension image");
        if (w > kPngAxisCap || h > kPngAxisCap ||
            static_cast<uint64_t>(w) * h > kPngPixelCap)
            throw std::invalid_argument("png: image dimensions exceed the supported limit");

        // 2. decode to the file's own color mode (color_convert=0) so info_png
        //    carries the true colortype/bitdepth/palette/tRNS for the target choice
        state.decoder.color_convert = 0;
        unsigned dw = 0, dh = 0;
        if (unsigned e = lodepng_decode(&raw, &dw, &dh, &state, in, insize))
            throw std::invalid_argument(std::string("png: ") + lodepng_error_text(e));

        // 3. choose a supported Image target from the source color mode
        const LodePNGColorMode &src = state.info_png.color;
        if (src.key_defined)  // single-color tRNS on gray/RGB -> would silently drop transparency
            throw std::invalid_argument(
                "png: colorkey transparency (non-palette tRNS) is not supported");
        LodePNGColorType tgt_ct;
        unsigned tgt_bd;
        size_t C;
        const char *cspace;
        const char *amode;
        switch (src.colortype) {
            case LCT_GREY:
                if (src.bitdepth != 8 && src.bitdepth != 16)
                    throw std::invalid_argument("png: sub-8-bit grayscale PNG is not supported");
                tgt_ct = LCT_GREY; tgt_bd = src.bitdepth; C = 1; cspace = "gray"; amode = "none";
                break;
            case LCT_RGB:
                tgt_ct = LCT_RGB; tgt_bd = src.bitdepth; C = 3; cspace = "srgb"; amode = "none";
                break;
            case LCT_RGBA:
                tgt_ct = LCT_RGBA; tgt_bd = src.bitdepth; C = 4; cspace = "srgb"; amode = "straight";
                break;
            case LCT_PALETTE: {
                bool has_alpha = false;  // any non-opaque palette entry -> keep alpha
                for (size_t i = 0; i < src.palettesize; i++)
                    if (src.palette[4 * i + 3] != 255) { has_alpha = true; break; }
                tgt_bd = 8;
                if (has_alpha) { tgt_ct = LCT_RGBA; C = 4; cspace = "srgb"; amode = "straight"; }
                else           { tgt_ct = LCT_RGB;  C = 3; cspace = "srgb"; amode = "none"; }
                break;
            }
            case LCT_GREY_ALPHA:
                throw std::invalid_argument(
                    "png: grayscale+alpha (2-channel) PNG is not supported");
            default:
                throw std::invalid_argument("png: unsupported PNG color type");
        }

        // 4. convert raw (source mode) -> target mode, then copy into the record
        LodePNGColorMode tgt = lodepng_color_mode_make(tgt_ct, tgt_bd);
        std::vector<unsigned char> out(lodepng_get_raw_size(dw, dh, &tgt));
        unsigned cerr = lodepng_convert(out.data(), raw, &tgt, &src, dw, dh);
        lodepng_color_mode_cleanup(&tgt);
        if (cerr) throw std::invalid_argument(std::string("png: convert: ") + lodepng_error_text(cerr));

        im.height = dh;
        im.width = dw;
        im.channels = C;
        im.color_space = cspace;
        im.alpha_mode = amode;
        const size_t cnt = static_cast<size_t>(dw) * dh * C;
        if (tgt_bd == 16) {
            im.dtype = PixelType::U16;
            im.maxval = 65535;
            im.u16.resize(cnt);
            be16_to_native(out.data(), im.u16.data(), cnt, lanes);
        } else {
            im.dtype = PixelType::U8;
            im.maxval = 255;
            im.u8.assign(out.begin(), out.end());
        }
    }
    return im;
}

void require_png_depth_encoding(const std::string &unit,
                                double scale_to_meters,
                                const std::string &invalid_policy) {
    if (!depth_map_valid_unit(unit))
        throw std::invalid_argument(
            "PNG depth: unit must be "
            "meters|millimeters|custom|unitless|unknown");
    if (!depth_map_unit_scale_consistent(unit, scale_to_meters))
        throw std::invalid_argument(
            "PNG depth: unit/scale_to_meters mismatch");
    if (!depth_map_valid_invalid_policy(invalid_policy))
        throw std::invalid_argument(
            "PNG depth: invalid_policy must be "
            "none|zero|nonfinite|negative");
}

DepthMap read_png_depth(nb::handle source, const std::string &unit,
                        double scale_to_meters,
                        const std::string &invalid_policy, size_t lanes) {
    require_png_depth_encoding(unit, scale_to_meters, invalid_policy);
    Image image = read_png(source, lanes);
    if (image.channels != 1 || image.dtype != PixelType::U16 ||
        image.color_space != "gray" || image.maxval != 65535)
        throw std::invalid_argument(
            "PNG depth: expected grayscale uint16 samples");

    DepthMap result;
    result.height = image.height;
    result.width = image.width;
    result.unit = unit;
    result.scale_to_meters = scale_to_meters;
    result.invalid_policy = invalid_policy;
    result.depth.resize(image.u16.size());
    {
        nb::gil_scoped_release release;
        parallel_for_blocks(
            image.u16.size(), lanes, 262144,
            [&](size_t begin, size_t end, size_t) {
                for (size_t index = begin; index < end; ++index)
                    result.depth[index] =
                        static_cast<float>(image.u16[index]);
            });
    }
    return result;
}

nb::bytes write_png(const Image &img, size_t lanes) {
    // --- guards: refuse conventions PNG cannot represent (never convert) ---
    // Dimensions first: width/height are size_t but lodepng_encode takes unsigned,
    // so an oversized record would silently truncate to a wrong-but-valid PNG.
    // Enforce the same caps as the reader (also the write/read symmetry).
    if (img.width == 0 || img.height == 0)
        throw std::invalid_argument("png: cannot write a zero-dimension image");
    if (img.width > kPngAxisCap || img.height > kPngAxisCap ||
        static_cast<uint64_t>(img.width) * img.height > kPngPixelCap)
        throw std::invalid_argument("png: image dimensions exceed the supported limit");
    if (img.dtype == PixelType::F32)
        throw std::invalid_argument("png: cannot store float32 pixels (PNG is integer; use EXR/HDR)");
    const size_t C = img.channels;
    LodePNGColorType ct;
    if (C == 1) {
        if (img.color_space != "gray")
            throw std::invalid_argument(
                "png: 1-channel image requires color_space 'gray' (got '" + img.color_space + "')");
        ct = LCT_GREY;
    } else if (C == 3) {
        if (img.color_space != "srgb")
            throw std::invalid_argument(
                "png: 3-channel image requires color_space 'srgb' (got '" + img.color_space +
                "'; convert linear->srgb first)");
        ct = LCT_RGB;
    } else if (C == 4) {
        if (img.color_space != "srgb")
            throw std::invalid_argument(
                "png: 4-channel image requires color_space 'srgb' (got '" + img.color_space + "')");
        if (img.alpha_mode != "straight")
            throw std::invalid_argument(
                "png: RGBA PNG requires alpha_mode 'straight' (got '" + img.alpha_mode +
                "'; PNG stores straight alpha)");
        ct = LCT_RGBA;
    } else {
        throw std::invalid_argument("png: only 1/3/4-channel images are supported");
    }
    const bool wide = (img.dtype == PixelType::U16);
    // PNG has no maxval concept: a partial-range record (e.g. u16 with maxval<65535)
    // would misrepresent the sample range, so it is refused rather than rescaled.
    if (!wide && img.maxval != 255)
        throw std::invalid_argument(
            "png: uint8 PNG requires maxval 255 (partial-range record — convert first)");
    if (wide && img.maxval != 65535)
        throw std::invalid_argument(
            "png: uint16 PNG requires maxval 65535 (partial-range record — convert first)");

    std::string out_bytes;
    {
        nb::gil_scoped_release rel;  // pure-C++ encode; nb::bytes built after the scope, under the GIL
        const size_t cnt = img.count();
        const unsigned bd = wide ? 16 : 8;
        std::vector<unsigned char> scratch;  // native uint16 -> big-endian for lodepng
        const unsigned char *pixels;
        if (wide) {
            scratch.resize(cnt * 2);
            native_to_be16(img.u16.data(), scratch.data(), cnt, lanes);
            pixels = scratch.data();
        } else {
            pixels = img.u8.data();
        }

        LodePNGState state;
        lodepng_state_init(&state);
        state.info_raw.colortype = ct;        // format of the input buffer
        state.info_raw.bitdepth = bd;
        state.info_png.color.colortype = ct;  // format to write into the PNG
        state.info_png.color.bitdepth = bd;
        state.encoder.auto_convert = 0;       // write exactly this color type (deterministic bytes)
        unsigned char *out = nullptr;
        size_t outsize = 0;
        unsigned err = lodepng_encode(&out, &outsize, pixels, static_cast<unsigned>(img.width),
                                      static_cast<unsigned>(img.height), &state);
        struct Guard {
            LodePNGState *s;
            unsigned char **o;
            ~Guard() {
                lodepng_state_cleanup(s);
                free(*o);
            }
        } guard{&state, &out};
        if (err) throw std::invalid_argument(std::string("png: encode: ") + lodepng_error_text(err));
        out_bytes.assign(reinterpret_cast<const char *>(out), outsize);
    }
    return emit_bytes(out_bytes.data(), out_bytes.size());
}

nb::bytes write_png_depth(const DepthMap &depth, const std::string &unit,
                          double scale_to_meters,
                          const std::string &invalid_policy, size_t lanes) {
    require_png_depth_encoding(unit, scale_to_meters, invalid_policy);
    if (depth.unit != unit || depth.scale_to_meters != scale_to_meters ||
        depth.invalid_policy != invalid_policy)
        throw std::invalid_argument(
            "PNG depth: DepthMap metadata does not match DepthEncoding");
    if (depth.has_confidence())
        throw std::invalid_argument(
            "PNG depth: confidence cannot be represented");
    if (depth.height == 0 || depth.width == 0 ||
        depth.width > std::numeric_limits<size_t>::max() / depth.height)
        throw std::invalid_argument(
            "PNG depth: invalid or overflowing dimensions");
    if (depth.width > kPngAxisCap || depth.height > kPngAxisCap ||
        static_cast<uint64_t>(depth.width) * depth.height > kPngPixelCap)
        throw std::invalid_argument(
            "PNG depth: image dimensions exceed the supported limit");
    const size_t count = depth.height * depth.width;
    if (depth.depth.size() != count)
        throw std::invalid_argument(
            "PNG depth: DepthMap storage disagrees with its dimensions");

    Image image;
    image.height = depth.height;
    image.width = depth.width;
    image.channels = 1;
    image.dtype = PixelType::U16;
    image.color_space = "gray";
    image.alpha_mode = "none";
    image.maxval = 65535;
    image.u16.resize(count);
    {
        nb::gil_scoped_release release;
        parallel_for_blocks(
            count, lanes, 262144,
            [&](size_t begin, size_t end, size_t) {
                for (size_t index = begin; index < end; ++index) {
                    const float value = depth.depth[index];
                    if (!std::isfinite(value) || value < 0.0f ||
                        value > 65535.0f || std::trunc(value) != value ||
                        (value == 0.0f && std::signbit(value)))
                        throw std::invalid_argument(
                            "PNG depth: every stored value must be an exact "
                            "non-negative integer in [0,65535]");
                    image.u16[index] = static_cast<uint16_t>(value);
                }
            });
    }
    return write_png(image, lanes);
}

nb::bytes write_png_depth_request(nb::tuple request) {
    if (request.size() != 4)
        throw std::invalid_argument(
            "PNG depth: internal write request must contain four values");
    return write_png_depth(
        nb::cast<const DepthMap &>(request[0]),
        nb::cast<std::string>(request[1]),
        nb::cast<double>(request[2]),
        nb::cast<std::string>(request[3]), 0);
}

}  // namespace

void register_png(nb::module_ &m) {
    m.def("read_png", &read_png, "data"_a, "_lanes"_a = 0,
          "Decode PNG bytes into an Image: gray/RGB/RGBA at 8 or 16 bit (16-bit read "
          "big-endian-on-disk -> native uint16), palette expanded to RGB/RGBA; top-to-bottom "
          "rows, straight alpha. Sub-8-bit gray, gray+alpha, and non-palette colorkey tRNS raise.");
    m.def("write_png", &write_png, "img"_a, "_lanes"_a = 0,
          "Encode an Image to PNG bytes (writes exactly the record's color type). Guards "
          "channel/color_space and alpha pairings and refuses float32 / linear / premultiplied / "
          "partial-maxval records rather than converting. Large 16-bit byte-order transforms "
          "use bounded parallel lanes.");
    m.def("read_png_depth", &read_png_depth, "data"_a, "unit"_a,
          "scale_to_meters"_a, "invalid_policy"_a, "_lanes"_a = 0,
          "Decode grayscale uint16 PNG into an owning float32 DepthMap by "
          "exact widening, using the caller-supplied external depth encoding.");
    m.def("write_png_depth", &write_png_depth, "depth"_a, "unit"_a,
          "scale_to_meters"_a, "invalid_policy"_a, "_lanes"_a = 0,
          "Encode an externally tagged DepthMap as deterministic grayscale "
          "uint16 PNG after exact-integral range and confidence guards.");
    m.def("_write_png_depth_request", &write_png_depth_request, "request"_a,
          "Encode the private (DepthMap, unit, scale, invalid_policy) sink request.");
}
