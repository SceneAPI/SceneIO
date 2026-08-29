// codecs/images/webp.cpp -- WebP <-> Image (uint8 sRGB) via libwebp (BSD), built from
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
#include <atomic>
#include <mutex>
#include <string>

#include "records/image.hpp"
#include "src/utils/thread_utils.h"
#include "webp/decode.h"
#include "webp/encode.h"

using namespace nb::literals;
using namespace sio;

namespace {
// 250 MP, matching the other image codecs; a WebP decode-bomb is format-bounded to
// 16384^2 (~1 GB) anyway, and this rejects that largest legal raster consistently.
constexpr uint64_t kWebpPixelCap = 250000000ull;

std::atomic<uint64_t> webp_worker_launches{0};
WebPWorkerInterface webp_base_worker{};
std::once_flag webp_worker_counter_once;

void counting_webp_worker_launch(WebPWorker *worker) {
    webp_worker_launches.fetch_add(1, std::memory_order_relaxed);
    webp_base_worker.Launch(worker);
}

void install_webp_worker_counter() {
    // libwebp's worker interface is process-global and must be replaced before
    // the first worker starts. Module registration is the single-threaded point
    // at which _core can safely wrap it. All operations except Launch delegate
    // directly; the counter provides deterministic coverage that `_threads`
    // reaches libwebp's real side-worker path.
    std::call_once(webp_worker_counter_once, []() {
        webp_base_worker = *WebPGetWorkerInterface();
        WebPWorkerInterface counting_worker = webp_base_worker;
        counting_worker.Launch = counting_webp_worker_launch;
        if (!WebPSetWorkerInterface(&counting_worker))
            throw std::runtime_error(
                "webp: could not install worker interface");
    });
}

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

Image read_webp_window(nb::handle source, size_t row_start, size_t row_stop,
                       size_t col_start, size_t col_stop) {
    sio::ByteView data(source);
    const uint8_t *in = data.data();
    const size_t size = data.size();
    Image im;
    {
        nb::gil_scoped_release rel;
        WebPDecoderConfig config;
        if (!WebPInitDecoderConfig(&config))
            throw std::invalid_argument(
                "webp: decoder config init failed (ABI mismatch?)");
        struct ConfigGuard {
            WebPDecoderConfig *config;
            ~ConfigGuard() { WebPFreeDecBuffer(&config->output); }
        } guard{&config};
        if (WebPGetFeatures(in, size, &config.input) != VP8_STATUS_OK)
            throw std::invalid_argument("webp: not a valid WebP stream");
        if (config.input.has_animation)
            throw std::invalid_argument(
                "webp: animated WebP is not supported");
        // VP8 cropping changes chroma/fancy-upsampling context at the crop
        // boundary, so it is not guaranteed to equal a full-decode slice.
        // VP8L has no such context dependency and remains slice-exact.
        if (config.input.format != 2)
            throw std::invalid_argument(
                "webp: pixel-window reads require lossless VP8L for "
                "slice-exact decoding");
        if (config.input.width <= 0 || config.input.height <= 0 ||
            static_cast<uint64_t>(config.input.width) * config.input.height >
                kWebpPixelCap)
            throw std::invalid_argument(
                "webp: image dimensions exceed the supported limit");
        const size_t height = static_cast<size_t>(config.input.height);
        const size_t width = static_cast<size_t>(config.input.width);
        const size_t out_h = checked_half_open_range(
            row_start, row_stop, height, "webp row window");
        const size_t out_w = checked_half_open_range(
            col_start, col_stop, width, "webp column window");

        // libwebp snaps crop origins down to even coordinates. Decode at most
        // one extra leading row/column, then copy the exact requested box.
        const size_t decode_top = row_start & ~size_t{1};
        const size_t decode_left = col_start & ~size_t{1};
        const size_t decode_h = row_stop - decode_top;
        const size_t decode_w = col_stop - decode_left;
        const size_t channels = config.input.has_alpha ? 4 : 3;
        std::vector<uint8_t> decoded(decode_h * decode_w * channels);

        config.output.colorspace =
            config.input.has_alpha ? MODE_RGBA : MODE_RGB;
        config.output.is_external_memory = 1;
        config.output.u.RGBA.rgba = decoded.data();
        config.output.u.RGBA.stride =
            static_cast<int>(decode_w * channels);
        config.output.u.RGBA.size = decoded.size();
        config.options.use_cropping = 1;
        config.options.crop_left = static_cast<int>(decode_left);
        config.options.crop_top = static_cast<int>(decode_top);
        config.options.crop_width = static_cast<int>(decode_w);
        config.options.crop_height = static_cast<int>(decode_h);
        const VP8StatusCode status = WebPDecode(in, size, &config);
        if (status != VP8_STATUS_OK)
            throw std::invalid_argument("webp: window decode failed");

        im.height = out_h;
        im.width = out_w;
        im.channels = channels;
        im.dtype = PixelType::U8;
        im.color_space = "srgb";
        im.alpha_mode = config.input.has_alpha ? "straight" : "none";
        im.maxval = 255;
        im.u8.resize(out_h * out_w * channels);
        const size_t row_offset = row_start - decode_top;
        const size_t col_offset = col_start - decode_left;
        for (size_t y = 0; y < out_h; ++y)
            std::memcpy(
                im.u8.data() + y * out_w * channels,
                decoded.data() +
                    ((row_offset + y) * decode_w + col_offset) * channels,
                out_w * channels);
    }
    return im;
}

nb::bytes write_webp(const Image &img, bool lossless, float quality,
                     bool threads, int effort, int method) {
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
    if (!lossless &&
        !(quality >= 0.0f && quality <= 100.0f))  // negated form also rejects NaN
        throw std::invalid_argument("webp: quality must be in 0..100");
    if (effort < 0 || effort > 100)
        throw std::invalid_argument("webp: lossless effort must be in 0..100");
    if (method < 0 || method > 6)
        throw std::invalid_argument("webp: encoder method must be in 0..6");

    std::string out;
    {
        nb::gil_scoped_release rel;  // nb::bytes built after the scope, under the GIL
        WebPConfig config;
        if (!WebPConfigInit(&config))
            throw std::invalid_argument("webp: config init failed (ABI mismatch?)");
        if (lossless) {
            config.lossless = 1;
            // Lossless effort affects only compression time/size, never decoded
            // pixels. O4 lowers the old forced-100 setting to a balanced 75;
            // method 5 lets libwebp split independent palette candidates.
            config.quality = static_cast<float>(effort);
            config.exact = 1;         // preserve RGB under alpha=0 -> byte-exact lossless round-trip
            config.method = method;
            config.thread_level = threads ? 1 : 0;
        } else {
            config.quality = quality;
            // O4 targets lossless only. Preserve libwebp's prior lossy defaults
            // (method 4, worker-off) so lossy bytes/performance do not drift.
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
    install_webp_worker_counter();
    m.def("read_webp", &read_webp, "data"_a,
          "Decode WebP bytes into an Image (uint8 sRGB; RGB, or RGBA with straight alpha when the "
          "file has alpha). Animated WebP raises.");
    m.def("read_webp_window", &read_webp_window, "data"_a, "row_start"_a,
          "row_stop"_a, "column_start"_a, "column_stop"_a,
          "Decode one non-empty half-open lossless VP8L pixel window; lossy "
          "VP8 rejects because crop-local chroma upsampling is not slice-exact.");
    m.def("write_webp", &write_webp, "img"_a, "lossless"_a = true,
          "quality"_a = 90.0f, "_threads"_a = true, "_effort"_a = 75,
          "_method"_a = 5,
          "Encode a uint8 sRGB RGB/RGBA Image to WebP bytes. Lossless by default (exact=1): RGB "
          "and transparent RGBA round-trip byte-exactly, but a fully-opaque alpha channel is "
          "dropped to RGB by the format. Quality selects fidelity for lossy mode; lossless uses "
          "a balanced internal effort of 75 (0..100). Worker threads are enabled by default. Refuses "
          "non-uint8, grayscale (no WebP gray plane), and non-straight alpha.");
    m.def("_webp_worker_launch_count",
          []() { return webp_worker_launches.load(std::memory_order_relaxed); },
          "Return the number of libwebp side-worker launches (private test hook).");
    m.def("_install_webp_worker_counter", &install_webp_worker_counter,
          "Re-run the idempotent libwebp worker setup (private test hook).");
}
