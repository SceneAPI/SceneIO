// codecs/sequences/animated_webp.cpp -- animated WebP <-> packed
// ImageSequence via the repository-pinned libwebp demux/mux APIs.
//
// Reads return fully composited RGBA canvases, preserving display timing,
// loop count, and background color. Writes accept packed uint8 RGB/RGBA
// full-canvas frames whose nanosecond timing is exactly representable in
// WebP's millisecond clock. No color, alpha, timing, or layout conversion is
// performed implicitly.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#include "records/image_sequence.hpp"
#include "webp/decode.h"
#include "webp/demux.h"
#include "webp/encode.h"
#include "webp/mux.h"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kAnimatedWebpPixelCap = 250000000ull;
constexpr uint64_t kAnimatedWebpSampleCap = 1000000000ull;
constexpr int64_t kNanosecondsPerMillisecond = 1000000;
constexpr int64_t kMaximumFrameDurationMilliseconds = 0xFFFFFF;

struct AnimDecoderGuard {
    WebPAnimDecoder *value = nullptr;
    ~AnimDecoderGuard() {
        if (value) WebPAnimDecoderDelete(value);
    }
};

struct DemuxGuard {
    WebPDemuxer *value = nullptr;
    ~DemuxGuard() {
        if (value) WebPDemuxDelete(value);
    }
};

struct AnimEncoderGuard {
    WebPAnimEncoder *value = nullptr;
    ~AnimEncoderGuard() {
        if (value) WebPAnimEncoderDelete(value);
    }
};

struct PictureGuard {
    WebPPicture *value;
    ~PictureGuard() { WebPPictureFree(value); }
};

struct WebPDataGuard {
    WebPData *value;
    ~WebPDataGuard() { WebPDataClear(value); }
};

struct MuxGuard {
    WebPMux *value = nullptr;
    ~MuxGuard() {
        if (value) WebPMuxDelete(value);
    }
};

struct MemoryWriterGuard {
    WebPMemoryWriter *value;
    ~MemoryWriterGuard() { WebPMemoryWriterClear(value); }
};

uint64_t checked_sample_count(
    uint32_t frames, uint32_t height, uint32_t width,
    size_t channels, const char *context) {
    const uint64_t pixels =
        static_cast<uint64_t>(height) * width;
    if (height == 0 || width == 0 ||
        pixels > kAnimatedWebpPixelCap)
        throw std::invalid_argument(
            std::string(context) +
            ": canvas dimensions exceed the supported limit");
    const uint64_t samples =
        pixels * static_cast<uint64_t>(frames) * channels;
    if (frames == 0 || samples > kAnimatedWebpSampleCap ||
        samples > std::numeric_limits<size_t>::max())
        throw std::invalid_argument(
            std::string(context) +
            ": decoded sequence exceeds the supported sample limit");
    return samples;
}

std::array<uint8_t, 4> unpack_background(uint32_t value) {
    return {
        static_cast<uint8_t>((value >> 8) & 0xff),
        static_cast<uint8_t>((value >> 16) & 0xff),
        static_cast<uint8_t>((value >> 24) & 0xff),
        static_cast<uint8_t>(value & 0xff),
    };
}

uint32_t pack_background(const std::array<uint8_t, 4> &value) {
    return
        (static_cast<uint32_t>(value[2]) << 24) |
        (static_cast<uint32_t>(value[1]) << 16) |
        (static_cast<uint32_t>(value[0]) << 8) |
        static_cast<uint32_t>(value[3]);
}

void require_animation(
    const uint8_t *data, size_t size, const char *context) {
    WebPBitstreamFeatures features;
    if (WebPGetFeatures(data, size, &features) != VP8_STATUS_OK)
        throw std::invalid_argument(
            std::string(context) + ": not a valid WebP stream");
    if (!features.has_animation)
        throw std::invalid_argument(
            std::string(context) + ": stream is not animated WebP");
}

ImageSequence read_animated_webp(nb::handle source) {
    sio::ByteView input(source);
    const uint8_t *data = input.data();
    const size_t size = input.size();
    ImageSequence sequence;
    {
        nb::gil_scoped_release release;
        require_animation(data, size, "animated webp");
        WebPData webp_data{data, size};
        WebPAnimDecoderOptions options;
        if (!WebPAnimDecoderOptionsInit(&options))
            throw std::invalid_argument(
                "animated webp: decoder ABI initialization failed");
        options.color_mode = MODE_RGBA;
        options.use_threads = 1;
        AnimDecoderGuard decoder{
            WebPAnimDecoderNew(&webp_data, &options)};
        if (!decoder.value)
            throw std::invalid_argument(
                "animated webp: demux initialization failed");

        WebPAnimInfo info;
        if (!WebPAnimDecoderGetInfo(decoder.value, &info))
            throw std::invalid_argument(
                "animated webp: animation metadata is malformed");
        const uint64_t sample_count = checked_sample_count(
            info.frame_count, info.canvas_height, info.canvas_width,
            4, "animated webp");

        sequence.storage_mode = "packed";
        sequence.n = info.frame_count;
        sequence.height = info.canvas_height;
        sequence.width = info.canvas_width;
        sequence.channels = 4;
        sequence.frame_dtype = "uint8";
        sequence.color_space = "srgb";
        sequence.alpha_mode = "straight";
        sequence.maxval = 255;
        sequence.loop_count_present = true;
        sequence.loop_count = info.loop_count;
        sequence.background_present = true;
        sequence.background_rgba = unpack_background(info.bgcolor);
        sequence.pixels_u8.resize(
            static_cast<size_t>(sample_count));
        sequence.timestamps_ns.reserve(info.frame_count);
        sequence.durations_ns.reserve(info.frame_count);

        const size_t frame_samples =
            static_cast<size_t>(info.canvas_width) *
            info.canvas_height * 4;
        int previous_timestamp_ms = 0;
        for (uint32_t index = 0; index < info.frame_count; ++index) {
            uint8_t *frame = nullptr;
            int timestamp_ms = 0;
            if (!WebPAnimDecoderGetNext(
                    decoder.value, &frame, &timestamp_ms) ||
                frame == nullptr)
                throw std::invalid_argument(
                    "animated webp: frame decode failed");
            if (timestamp_ms <= previous_timestamp_ms)
                throw std::invalid_argument(
                    "animated webp: zero or negative frame duration "
                    "cannot be represented");
            sequence.timestamps_ns.push_back(
                static_cast<int64_t>(previous_timestamp_ms) *
                kNanosecondsPerMillisecond);
            sequence.durations_ns.push_back(
                static_cast<int64_t>(
                    timestamp_ms - previous_timestamp_ms) *
                kNanosecondsPerMillisecond);
            std::memcpy(
                sequence.pixels_u8.data() +
                    static_cast<size_t>(index) * frame_samples,
                frame, frame_samples);
            previous_timestamp_ms = timestamp_ms;
        }
        if (WebPAnimDecoderHasMoreFrames(decoder.value))
            throw std::invalid_argument(
                "animated webp: frame count disagrees with the stream");
    }
    validate_image_sequence(sequence, "animated webp");
    return sequence;
}

struct AnimatedWebpInspection {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t frames = 0;
    uint32_t loop_count = 0;
    uint32_t background = 0;
    uint64_t duration_ms = 0;
    std::vector<uint32_t> frame_durations_ms;
};

AnimatedWebpInspection inspect_animation(
    const uint8_t *data, size_t size) {
    require_animation(data, size, "animated webp");
    WebPData webp_data{data, size};
    DemuxGuard demux{WebPDemux(&webp_data)};
    if (!demux.value)
        throw std::invalid_argument(
            "animated webp: demux failed");
    AnimatedWebpInspection result;
    result.width = WebPDemuxGetI(demux.value, WEBP_FF_CANVAS_WIDTH);
    result.height = WebPDemuxGetI(demux.value, WEBP_FF_CANVAS_HEIGHT);
    result.frames = WebPDemuxGetI(demux.value, WEBP_FF_FRAME_COUNT);
    result.loop_count = WebPDemuxGetI(demux.value, WEBP_FF_LOOP_COUNT);
    result.background =
        WebPDemuxGetI(demux.value, WEBP_FF_BACKGROUND_COLOR);
    (void)checked_sample_count(
        result.frames, result.height, result.width, 4,
        "animated webp");
    result.frame_durations_ms.reserve(result.frames);
    for (uint32_t frame_number = 1;
         frame_number <= result.frames; ++frame_number) {
        WebPIterator iterator;
        if (!WebPDemuxGetFrame(
                demux.value, static_cast<int>(frame_number),
                &iterator))
            throw std::invalid_argument(
                "animated webp: frame table is malformed");
        const int duration = iterator.duration;
        WebPDemuxReleaseIterator(&iterator);
        if (duration <= 0)
            throw std::invalid_argument(
                "animated webp: zero or negative frame duration "
                "cannot be represented");
        const uint64_t duration_ms =
            static_cast<uint32_t>(duration);
        const uint64_t maximum_duration_ms =
            static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()) /
            kNanosecondsPerMillisecond;
        if (result.duration_ms >
            maximum_duration_ms - duration_ms)
            throw std::invalid_argument(
                "animated webp: total duration exceeds the "
                "int64 nanosecond range");
        result.frame_durations_ms.push_back(
            static_cast<uint32_t>(duration));
        result.duration_ms += duration_ms;
    }
    return result;
}

nb::dict inspect_animated_webp(nb::handle source) {
    sio::ByteView input(source);
    AnimatedWebpInspection value;
    {
        nb::gil_scoped_release release;
        value = inspect_animation(input.data(), input.size());
    }
    const auto background = unpack_background(value.background);
    nb::dict result;
    result["width"] = value.width;
    result["height"] = value.height;
    result["frames"] = value.frames;
    result["channels"] = 4;
    result["dtype"] = "uint8";
    result["color_space"] = "srgb";
    result["alpha_mode"] = "straight";
    result["loop_count"] = value.loop_count;
    result["duration_ns"] =
        value.duration_ms * kNanosecondsPerMillisecond;
    result["background_rgba"] = nb::make_tuple(
        background[0], background[1],
        background[2], background[3]);
    return result;
}

bool is_animated_webp(nb::handle source) {
    sio::ByteView input(source);
    WebPBitstreamFeatures features;
    return WebPGetFeatures(
               input.data(), input.size(), &features) ==
               VP8_STATUS_OK &&
           features.has_animation;
}

void validate_writer_input(const ImageSequence &sequence) {
    validate_image_sequence(sequence, "animated webp");
    if (sequence.storage_mode != "packed" ||
        sequence.frame_dtype != "uint8")
        throw std::invalid_argument(
            "animated webp: requires packed uint8 frames");
    if (sequence.channels != 3 && sequence.channels != 4)
        throw std::invalid_argument(
            "animated webp: requires RGB or RGBA frames");
    if (sequence.color_space != "srgb" ||
        sequence.maxval != 255)
        throw std::invalid_argument(
            "animated webp: requires full-range sRGB samples");
    if ((sequence.channels == 4 &&
         sequence.alpha_mode != "straight") ||
        (sequence.channels == 3 &&
         sequence.alpha_mode != "none"))
        throw std::invalid_argument(
            "animated webp: alpha metadata disagrees with channels");
    if (sequence.n == 0 ||
        sequence.width > 16383 ||
        sequence.height > 16383)
        throw std::invalid_argument(
            "animated webp: needs nonempty frames within the "
            "16383-pixel axis limit");
    if (!sequence.has_timing() ||
        sequence.timestamps_ns.front() != 0)
        throw std::invalid_argument(
            "animated webp: exact timing must start at zero");

    int64_t expected_timestamp = 0;
    for (size_t index = 0; index < sequence.n; ++index) {
        const int64_t timestamp = sequence.timestamps_ns[index];
        const int64_t duration = sequence.durations_ns[index];
        if (timestamp != expected_timestamp ||
            timestamp % kNanosecondsPerMillisecond != 0 ||
            duration % kNanosecondsPerMillisecond != 0)
            throw std::invalid_argument(
                "animated webp: timing must be contiguous and exactly "
                "representable in milliseconds");
        const int64_t duration_ms =
            duration / kNanosecondsPerMillisecond;
        if (duration_ms <= 0 ||
            duration_ms > kMaximumFrameDurationMilliseconds)
            throw std::invalid_argument(
                "animated webp: frame duration exceeds the 24-bit "
                "millisecond range");
        if (duration >
            std::numeric_limits<int64_t>::max() -
                expected_timestamp)
            throw std::invalid_argument(
                "animated webp: timeline overflows int64");
        expected_timestamp += duration;
    }
    if (expected_timestamp / kNanosecondsPerMillisecond >
        std::numeric_limits<int>::max())
        throw std::invalid_argument(
            "animated webp: timeline exceeds encoder range");
    if (sequence.loop_count_present &&
        sequence.loop_count >
            static_cast<uint32_t>(std::numeric_limits<int>::max()))
        throw std::invalid_argument(
            "animated webp: loop count exceeds encoder range");
}

std::string encode_animation_without_frame_elision(
    const ImageSequence &sequence,
    const WebPConfig &config,
    const WebPMuxAnimParams &animation_params) {
    MuxGuard mux{WebPMuxNew()};
    if (!mux.value)
        throw std::invalid_argument(
            "animated webp: fallback mux allocation failed");
    if (WebPMuxSetCanvasSize(
            mux.value, static_cast<int>(sequence.width),
            static_cast<int>(sequence.height)) != WEBP_MUX_OK ||
        WebPMuxSetAnimationParams(
            mux.value, &animation_params) != WEBP_MUX_OK)
        throw std::invalid_argument(
            "animated webp: fallback mux metadata failed");

    const size_t frame_samples =
        sequence.height * sequence.width * sequence.channels;
    for (size_t index = 0; index < sequence.n; ++index) {
        WebPPicture picture;
        if (!WebPPictureInit(&picture))
            throw std::invalid_argument(
                "animated webp: fallback picture initialization failed");
        PictureGuard picture_guard{&picture};
        picture.use_argb = 1;
        picture.width = static_cast<int>(sequence.width);
        picture.height = static_cast<int>(sequence.height);
        const uint8_t *pixels =
            sequence.pixels_u8.data() + index * frame_samples;
        const int stride = static_cast<int>(
            sequence.width * sequence.channels);
        const int imported =
            sequence.channels == 4
                ? WebPPictureImportRGBA(&picture, pixels, stride)
                : WebPPictureImportRGB(&picture, pixels, stride);
        if (!imported)
            throw std::invalid_argument(
                "animated webp: fallback frame import failed");

        WebPMemoryWriter writer;
        WebPMemoryWriterInit(&writer);
        MemoryWriterGuard writer_guard{&writer};
        picture.writer = WebPMemoryWrite;
        picture.custom_ptr = &writer;
        if (!WebPEncode(&config, &picture))
            throw std::invalid_argument(
                "animated webp: fallback frame encode failed");

        WebPMuxFrameInfo frame_info{};
        frame_info.bitstream.bytes = writer.mem;
        frame_info.bitstream.size = writer.size;
        frame_info.duration = static_cast<int>(
            sequence.durations_ns[index] /
            kNanosecondsPerMillisecond);
        frame_info.id = WEBP_CHUNK_ANMF;
        frame_info.dispose_method = WEBP_MUX_DISPOSE_NONE;
        frame_info.blend_method = WEBP_MUX_NO_BLEND;
        if (WebPMuxPushFrame(
                mux.value, &frame_info, 1) != WEBP_MUX_OK)
            throw std::invalid_argument(
                "animated webp: fallback frame mux failed");
    }

    WebPData assembled;
    WebPDataInit(&assembled);
    WebPDataGuard assembled_guard{&assembled};
    if (WebPMuxAssemble(
            mux.value, &assembled) != WEBP_MUX_OK)
        throw std::invalid_argument(
            "animated webp: fallback assembly failed");
    return std::string(
        reinterpret_cast<const char *>(assembled.bytes),
        assembled.size);
}

nb::bytes write_animated_webp(
    const ImageSequence &sequence,
    bool lossless,
    float quality,
    bool threads,
    int effort,
    int method) {
    validate_writer_input(sequence);
    if (!lossless &&
        !(quality >= 0.0f && quality <= 100.0f))
        throw std::invalid_argument(
            "animated webp: quality must be in 0..100");
    if (effort < 0 || effort > 100)
        throw std::invalid_argument(
            "animated webp: lossless effort must be in 0..100");
    if (method < 0 || method > 6)
        throw std::invalid_argument(
            "animated webp: encoder method must be in 0..6");

    std::string output;
    {
        nb::gil_scoped_release release;
        WebPAnimEncoderOptions animation_options;
        if (!WebPAnimEncoderOptionsInit(&animation_options))
            throw std::invalid_argument(
                "animated webp: encoder ABI initialization failed");
        animation_options.anim_params.loop_count =
            sequence.loop_count_present
                ? static_cast<int>(sequence.loop_count)
                : 1;
        animation_options.anim_params.bgcolor =
            pack_background(
                sequence.background_present
                    ? sequence.background_rgba
                    : std::array<uint8_t, 4>{0, 0, 0, 0});
        const WebPMuxAnimParams animation_params =
            animation_options.anim_params;

        AnimEncoderGuard encoder{WebPAnimEncoderNew(
            static_cast<int>(sequence.width),
            static_cast<int>(sequence.height),
            &animation_options)};
        if (!encoder.value)
            throw std::invalid_argument(
                "animated webp: encoder initialization failed");

        WebPConfig config;
        if (!WebPConfigInit(&config))
            throw std::invalid_argument(
                "animated webp: frame config initialization failed");
        config.lossless = lossless ? 1 : 0;
        config.quality =
            lossless ? static_cast<float>(effort) : quality;
        config.exact = 1;
        config.method = method;
        config.thread_level = threads ? 1 : 0;
        if (!WebPValidateConfig(&config))
            throw std::invalid_argument(
                "animated webp: invalid frame encoder configuration");

        const size_t frame_samples =
            sequence.height * sequence.width * sequence.channels;
        int final_timestamp_ms = 0;
        for (size_t index = 0; index < sequence.n; ++index) {
            WebPPicture picture;
            if (!WebPPictureInit(&picture))
                throw std::invalid_argument(
                    "animated webp: picture initialization failed");
            PictureGuard picture_guard{&picture};
            picture.use_argb = 1;
            picture.width = static_cast<int>(sequence.width);
            picture.height = static_cast<int>(sequence.height);
            const uint8_t *frame =
                sequence.pixels_u8.data() + index * frame_samples;
            const int stride = static_cast<int>(
                sequence.width * sequence.channels);
            const int imported =
                sequence.channels == 4
                    ? WebPPictureImportRGBA(
                          &picture, frame, stride)
                    : WebPPictureImportRGB(
                          &picture, frame, stride);
            if (!imported)
                throw std::invalid_argument(
                    "animated webp: frame import failed");
            const int timestamp_ms = static_cast<int>(
                sequence.timestamps_ns[index] /
                kNanosecondsPerMillisecond);
            if (!WebPAnimEncoderAdd(
                    encoder.value, &picture,
                    timestamp_ms, &config))
                throw std::invalid_argument(
                    std::string("animated webp: frame encode failed: ") +
                    WebPAnimEncoderGetError(encoder.value));
            final_timestamp_ms = static_cast<int>(
                (sequence.timestamps_ns[index] +
                 sequence.durations_ns[index]) /
                kNanosecondsPerMillisecond);
        }
        if (!WebPAnimEncoderAdd(
                encoder.value, nullptr,
                final_timestamp_ms, nullptr))
            throw std::invalid_argument(
                std::string("animated webp: timeline finalization failed: ") +
                WebPAnimEncoderGetError(encoder.value));

        WebPData assembled;
        WebPDataInit(&assembled);
        WebPDataGuard assembled_guard{&assembled};
        if (!WebPAnimEncoderAssemble(
                encoder.value, &assembled))
            throw std::invalid_argument(
                std::string("animated webp: assembly failed: ") +
                WebPAnimEncoderGetError(encoder.value));
        output.assign(
            reinterpret_cast<const char *>(assembled.bytes),
            assembled.size);
        // libwebp intentionally merges visually identical adjacent frames,
        // and may collapse an all-identical animation into a still image.
        // That changes ImageSequence length/timing metadata. Retain the
        // optimized encoder when its frame table is faithful; otherwise use
        // the lower-level mux with full-canvas no-blend frames.
        bool faithful_frame_table = false;
        try {
            const AnimatedWebpInspection inspection =
                inspect_animation(
                    reinterpret_cast<const uint8_t *>(output.data()),
                    output.size());
            faithful_frame_table =
                inspection.frames == sequence.n;
            if (faithful_frame_table) {
                for (size_t index = 0; index < sequence.n; ++index) {
                    const uint32_t expected_duration_ms =
                        static_cast<uint32_t>(
                            sequence.durations_ns[index] /
                            kNanosecondsPerMillisecond);
                    if (inspection.frame_durations_ms[index] !=
                        expected_duration_ms) {
                        faithful_frame_table = false;
                        break;
                    }
                }
            }
        } catch (const std::invalid_argument &) {
            faithful_frame_table = false;
        }
        if (!faithful_frame_table)
            output = encode_animation_without_frame_elision(
                sequence, config, animation_params);
    }
    return emit_bytes(output.data(), output.size());
}

}  // namespace

void register_animated_webp(nb::module_ &module) {
    module.def(
        "read_animated_webp", &read_animated_webp,
        "data"_a,
        "Decode animated WebP into fully composited packed uint8 RGBA "
        "ImageSequence frames with exact millisecond timing.");
    module.def(
        "write_animated_webp", &write_animated_webp,
        "sequence"_a, "lossless"_a = true,
        "quality"_a = 90.0f, "_threads"_a = true,
        "_effort"_a = 75, "_method"_a = 5,
        "Encode packed uint8 RGB/RGBA full-canvas frames as animated WebP; "
        "timing must be exactly representable in milliseconds.");
    module.def(
        "_inspect_animated_webp", &inspect_animated_webp,
        "data"_a,
        "Validate animated WebP metadata without decoding frame pixels.");
    module.def(
        "_is_animated_webp", &is_animated_webp,
        "data"_a,
        "Return whether a valid WebP buffer carries animation.");
}
