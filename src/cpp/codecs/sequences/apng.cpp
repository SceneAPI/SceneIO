// codecs/sequences/apng.cpp -- APNG <-> packed ImageSequence.
//
// The container layer is repository-owned and uses the already vendored
// lodepng implementation for each frame's PNG inflate/deflate. Reads accept a
// bounded 8-bit RGB/RGBA subset, validate APNG chunk order/CRC/sequence state,
// and return fully composited RGBA canvases. Writes emit deterministic
// full-canvas source/no-dispose frames, preserving every duration that has an
// exact uint16 APNG rational representation.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <numeric>
#include <string>
#include <vector>

#include "lodepng.h"
#include "records/image_sequence.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr std::array<uint8_t, 8> kPngSignature{
    137, 80, 78, 71, 13, 10, 26, 10};
constexpr uint64_t kApngPixelCap = 250000000ull;
constexpr uint64_t kApngSampleCap = 1000000000ull;
constexpr uint32_t kApngChunkCap = 1000000;
constexpr uint64_t kNanosecondsPerSecond = 1000000000ull;

struct ByteSpan {
    const uint8_t *data = nullptr;
    size_t size = 0;
};

struct FrameControl {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t x_offset = 0;
    uint32_t y_offset = 0;
    uint16_t delay_num = 0;
    uint16_t delay_den = 0;
    uint8_t dispose_op = 0;
    uint8_t blend_op = 0;
    bool uses_idat = false;
    std::vector<ByteSpan> compressed;
};

struct ParsedApng {
    uint32_t width = 0;
    uint32_t height = 0;
    uint8_t color_type = 0;
    uint8_t interlace = 0;
    uint32_t declared_frames = 0;
    uint32_t loop_count = 0;
    std::vector<FrameControl> frames;
    std::vector<int64_t> durations_ns;
};

uint16_t read_be16(const uint8_t *data) {
    return static_cast<uint16_t>(
        (static_cast<uint16_t>(data[0]) << 8) |
        static_cast<uint16_t>(data[1]));
}

uint32_t read_be32(const uint8_t *data) {
    return
        (static_cast<uint32_t>(data[0]) << 24) |
        (static_cast<uint32_t>(data[1]) << 16) |
        (static_cast<uint32_t>(data[2]) << 8) |
        static_cast<uint32_t>(data[3]);
}

void append_be16(std::vector<uint8_t> &output, uint16_t value) {
    output.push_back(static_cast<uint8_t>(value >> 8));
    output.push_back(static_cast<uint8_t>(value));
}

void append_be32(std::vector<uint8_t> &output, uint32_t value) {
    output.push_back(static_cast<uint8_t>(value >> 24));
    output.push_back(static_cast<uint8_t>(value >> 16));
    output.push_back(static_cast<uint8_t>(value >> 8));
    output.push_back(static_cast<uint8_t>(value));
}

void append_chunk(
    std::vector<uint8_t> &output,
    const char type[5],
    const uint8_t *data,
    size_t size) {
    if (size > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "apng: chunk exceeds the uint32 length limit");
    append_be32(output, static_cast<uint32_t>(size));
    const size_t crc_start = output.size();
    output.insert(output.end(), type, type + 4);
    if (size != 0)
        output.insert(output.end(), data, data + size);
    append_be32(
        output,
        lodepng_crc32(
            output.data() + crc_start,
            output.size() - crc_start));
}

void append_chunk(
    std::vector<uint8_t> &output,
    const char type[5],
    const std::vector<uint8_t> &data) {
    append_chunk(output, type, data.data(), data.size());
}

class ApngOutput {
public:
    ApngOutput()
        : streaming_(active_file_sink != nullptr) {}

    void append(const uint8_t *data, size_t size) {
        if (!streaming_) {
            output_.insert(output_.end(), data, data + size);
            return;
        }
        nb::gil_scoped_acquire acquire;
        if (!emit_file_chunk(
                reinterpret_cast<const char *>(data), size))
            throw std::runtime_error(
                "apng: file sink disappeared during encode");
    }

    void chunk(
        const char type[5],
        const uint8_t *data,
        size_t size) {
        if (!streaming_) {
            append_chunk(output_, type, data, size);
            return;
        }
        std::vector<uint8_t> encoded;
        encoded.reserve(size + 12);
        append_chunk(encoded, type, data, size);
        append(encoded.data(), encoded.size());
    }

    void chunk(
        const char type[5],
        const std::vector<uint8_t> &data) {
        chunk(type, data.data(), data.size());
    }

    nb::bytes finish() {
        if (streaming_)
            return nb::bytes("", 0);
        return nb::bytes(
            reinterpret_cast<const char *>(output_.data()),
            output_.size());
    }

private:
    bool streaming_;
    std::vector<uint8_t> output_;
};

uint64_t checked_sample_count(
    uint32_t frames,
    uint32_t height,
    uint32_t width,
    const char *context) {
    const uint64_t pixels =
        static_cast<uint64_t>(height) * width;
    if (height == 0 || width == 0 ||
        pixels > kApngPixelCap)
        throw std::invalid_argument(
            std::string(context) +
            ": canvas dimensions exceed the supported limit");
    const uint64_t samples =
        pixels * static_cast<uint64_t>(frames) * 4;
    if (frames == 0 || samples > kApngSampleCap ||
        samples > std::numeric_limits<size_t>::max())
        throw std::invalid_argument(
            std::string(context) +
            ": decoded sequence exceeds the supported sample limit");
    return samples;
}

bool equal_type(const uint8_t *type, const char expected[5]) {
    return std::memcmp(type, expected, 4) == 0;
}

bool is_critical_chunk(const uint8_t *type) {
    return (type[0] & 0x20) == 0;
}

bool is_unrepresented_metadata(const uint8_t *type) {
    return
        equal_type(type, "iCCP") ||
        equal_type(type, "gAMA") ||
        equal_type(type, "cHRM") ||
        equal_type(type, "eXIf") ||
        equal_type(type, "tEXt") ||
        equal_type(type, "zTXt") ||
        equal_type(type, "iTXt");
}

int64_t duration_to_nanoseconds(
    uint16_t numerator,
    uint16_t denominator) {
    if (numerator == 0)
        throw std::invalid_argument(
            "apng: zero-duration frames cannot be represented");
    const uint64_t den = denominator == 0 ? 100 : denominator;
    const uint64_t scaled =
        static_cast<uint64_t>(numerator) *
        kNanosecondsPerSecond;
    if (scaled % den != 0)
        throw std::invalid_argument(
            "apng: frame duration is not exactly representable "
            "in integer nanoseconds");
    const uint64_t duration = scaled / den;
    if (duration >
        static_cast<uint64_t>(
            std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument(
            "apng: frame duration exceeds the int64 nanosecond range");
    return static_cast<int64_t>(duration);
}

ParsedApng parse_apng(const uint8_t *data, size_t size) {
    if (size < kPngSignature.size() ||
        std::memcmp(
            data, kPngSignature.data(),
            kPngSignature.size()) != 0)
        throw std::invalid_argument(
            "apng: invalid PNG signature");

    ParsedApng result;
    bool seen_ihdr = false;
    bool seen_actl = false;
    bool seen_idat = false;
    bool idat_closed = false;
    bool seen_iend = false;
    uint32_t expected_sequence = 0;
    uint32_t chunk_count = 0;
    size_t current_frame =
        std::numeric_limits<size_t>::max();

    size_t position = kPngSignature.size();
    while (position < size) {
        if (++chunk_count > kApngChunkCap)
            throw std::invalid_argument(
                "apng: chunk count exceeds the supported limit");
        if (size - position < 12)
            throw std::invalid_argument(
                "apng: truncated chunk header");
        const uint32_t length = read_be32(data + position);
        if (length > 0x7fffffffu ||
            static_cast<size_t>(length) > size - position - 12)
            throw std::invalid_argument(
                "apng: chunk length exceeds the input");
        const uint8_t *type = data + position + 4;
        const uint8_t *payload = data + position + 8;
        const uint32_t stored_crc =
            read_be32(payload + length);
        const uint32_t actual_crc =
            lodepng_crc32(type, static_cast<size_t>(length) + 4);
        if (stored_crc != actual_crc)
            throw std::invalid_argument(
                "apng: chunk CRC mismatch");
        const size_t next =
            position + static_cast<size_t>(length) + 12;

        if (!seen_ihdr && !equal_type(type, "IHDR"))
            throw std::invalid_argument(
                "apng: IHDR must be the first chunk");

        if (equal_type(type, "IHDR")) {
            if (seen_ihdr || length != 13)
                throw std::invalid_argument(
                    "apng: malformed or duplicate IHDR");
            result.width = read_be32(payload);
            result.height = read_be32(payload + 4);
            const uint8_t bit_depth = payload[8];
            result.color_type = payload[9];
            const uint8_t compression = payload[10];
            const uint8_t filter = payload[11];
            result.interlace = payload[12];
            if (bit_depth != 8 ||
                (result.color_type != 2 &&
                 result.color_type != 6))
                throw std::invalid_argument(
                    "apng: supported input is 8-bit RGB or RGBA");
            if (compression != 0 || filter != 0 ||
                result.interlace > 1)
                throw std::invalid_argument(
                    "apng: unsupported IHDR method");
            seen_ihdr = true;
        } else if (equal_type(type, "acTL")) {
            if (!seen_ihdr || seen_actl ||
                seen_idat || !result.frames.empty() ||
                length != 8)
                throw std::invalid_argument(
                    "apng: malformed or misplaced acTL");
            result.declared_frames = read_be32(payload);
            result.loop_count = read_be32(payload + 4);
            (void)checked_sample_count(
                result.declared_frames,
                result.height,
                result.width,
                "apng");
            result.frames.reserve(result.declared_frames);
            result.durations_ns.reserve(
                result.declared_frames);
            seen_actl = true;
        } else if (equal_type(type, "fcTL")) {
            if (!seen_actl || seen_iend || length != 26)
                throw std::invalid_argument(
                    "apng: malformed or misplaced fcTL");
            if (read_be32(payload) != expected_sequence++)
                throw std::invalid_argument(
                    "apng: animation sequence numbers are not contiguous");
            if (current_frame !=
                    std::numeric_limits<size_t>::max() &&
                result.frames[current_frame].compressed.empty())
                throw std::invalid_argument(
                    "apng: frame has no image data");
            if (result.frames.size() >=
                result.declared_frames)
                throw std::invalid_argument(
                    "apng: more frames than declared by acTL");

            FrameControl frame;
            frame.width = read_be32(payload + 4);
            frame.height = read_be32(payload + 8);
            frame.x_offset = read_be32(payload + 12);
            frame.y_offset = read_be32(payload + 16);
            frame.delay_num = read_be16(payload + 20);
            frame.delay_den = read_be16(payload + 22);
            frame.dispose_op = payload[24];
            frame.blend_op = payload[25];
            frame.uses_idat = result.frames.empty();
            if (seen_idat && frame.uses_idat)
                throw std::invalid_argument(
                    "apng: a separate default image is not supported");
            if (frame.width == 0 || frame.height == 0 ||
                frame.x_offset > result.width ||
                frame.y_offset > result.height ||
                frame.width > result.width - frame.x_offset ||
                frame.height > result.height - frame.y_offset)
                throw std::invalid_argument(
                    "apng: frame rectangle is outside the canvas");
            if (frame.dispose_op > 2 ||
                frame.blend_op > 1)
                throw std::invalid_argument(
                    "apng: invalid blend or disposal operation");
            if (frame.uses_idat &&
                (frame.width != result.width ||
                 frame.height != result.height ||
                 frame.x_offset != 0 ||
                 frame.y_offset != 0))
                throw std::invalid_argument(
                    "apng: the first frame must cover the canvas");
            result.durations_ns.push_back(
                duration_to_nanoseconds(
                    frame.delay_num, frame.delay_den));
            result.frames.push_back(std::move(frame));
            current_frame = result.frames.size() - 1;
            if (seen_idat)
                idat_closed = true;
        } else if (equal_type(type, "IDAT")) {
            if (seen_actl && result.frames.empty())
                throw std::invalid_argument(
                    "apng: a separate default image is not supported");
            if (!seen_actl || result.frames.empty() ||
                !result.frames.front().uses_idat ||
                current_frame != 0 || idat_closed)
                throw std::invalid_argument(
                    "apng: IDAT is outside the first animation frame");
            result.frames.front().compressed.push_back(
                {payload, length});
            seen_idat = true;
        } else if (equal_type(type, "fdAT")) {
            if (!seen_idat ||
                current_frame ==
                    std::numeric_limits<size_t>::max() ||
                result.frames[current_frame].uses_idat ||
                length < 4)
                throw std::invalid_argument(
                    "apng: fdAT is outside a later animation frame");
            if (read_be32(payload) != expected_sequence++)
                throw std::invalid_argument(
                    "apng: animation sequence numbers are not contiguous");
            result.frames[current_frame].compressed.push_back(
                {payload + 4, static_cast<size_t>(length - 4)});
            idat_closed = true;
        } else if (equal_type(type, "IEND")) {
            if (length != 0 || seen_iend)
                throw std::invalid_argument(
                    "apng: malformed IEND");
            seen_iend = true;
            position = next;
            break;
        } else {
            if (is_unrepresented_metadata(type))
                throw std::invalid_argument(
                    "apng: color/text/EXIF metadata is not represented");
            if (is_critical_chunk(type))
                throw std::invalid_argument(
                    "apng: unsupported critical PNG chunk");
            if (seen_idat)
                idat_closed = true;
        }
        position = next;
    }

    if (!seen_ihdr || !seen_actl || !seen_iend ||
        position != size)
        throw std::invalid_argument(
            "apng: incomplete stream or trailing bytes");
    if (!seen_idat || result.frames.size() !=
            result.declared_frames)
        throw std::invalid_argument(
            "apng: frame count disagrees with acTL");
    if (current_frame ==
            std::numeric_limits<size_t>::max() ||
        result.frames[current_frame].compressed.empty())
        throw std::invalid_argument(
            "apng: final frame has no image data");
    return result;
}

std::vector<uint8_t> make_frame_png(
    const ParsedApng &animation,
    const FrameControl &frame) {
    size_t compressed_size = 0;
    for (const ByteSpan span : frame.compressed) {
        if (span.size >
            std::numeric_limits<size_t>::max() -
                compressed_size)
            throw std::invalid_argument(
                "apng: compressed frame size overflows size_t");
        compressed_size += span.size;
    }
    if (compressed_size == 0)
        throw std::invalid_argument(
            "apng: frame has no compressed payload");

    std::vector<uint8_t> png;
    png.reserve(
        kPngSignature.size() + 25 +
        compressed_size +
        frame.compressed.size() * 12 + 12);
    png.insert(
        png.end(), kPngSignature.begin(),
        kPngSignature.end());
    std::vector<uint8_t> ihdr;
    ihdr.reserve(13);
    append_be32(ihdr, frame.width);
    append_be32(ihdr, frame.height);
    ihdr.push_back(8);
    ihdr.push_back(animation.color_type);
    ihdr.push_back(0);
    ihdr.push_back(0);
    ihdr.push_back(animation.interlace);
    append_chunk(png, "IHDR", ihdr);
    for (const ByteSpan span : frame.compressed)
        append_chunk(
            png, "IDAT", span.data, span.size);
    append_chunk(png, "IEND", nullptr, 0);
    return png;
}

std::vector<uint8_t> decode_frame_rgba(
    const ParsedApng &animation,
    const FrameControl &frame) {
    const std::vector<uint8_t> png =
        make_frame_png(animation, frame);
    unsigned char *decoded = nullptr;
    unsigned width = 0;
    unsigned height = 0;
    const unsigned error = lodepng_decode32(
        &decoded, &width, &height,
        png.data(), png.size());
    struct Guard {
        unsigned char *value;
        ~Guard() { std::free(value); }
    } guard{decoded};
    if (error != 0)
        throw std::invalid_argument(
            std::string("apng: frame decode: ") +
            lodepng_error_text(error));
    if (width != frame.width ||
        height != frame.height)
        throw std::invalid_argument(
            "apng: decoded frame dimensions disagree with fcTL");
    const size_t samples =
        static_cast<size_t>(width) * height * 4;
    return std::vector<uint8_t>(
        decoded, decoded + samples);
}

uint8_t rounded_divide(uint64_t numerator, uint64_t denominator) {
    return static_cast<uint8_t>(
        (numerator + denominator / 2) /
        denominator);
}

void blend_over(
    uint8_t *destination,
    const uint8_t *source) {
    const uint32_t source_alpha = source[3];
    const uint32_t destination_alpha = destination[3];
    if (source_alpha == 255) {
        std::memcpy(destination, source, 4);
        return;
    }
    if (source_alpha == 0)
        return;
    const uint32_t inverse_alpha =
        255 - source_alpha;
    const uint64_t alpha_numerator =
        static_cast<uint64_t>(source_alpha) * 255 +
        static_cast<uint64_t>(destination_alpha) *
            inverse_alpha;
    if (alpha_numerator == 0) {
        std::fill(destination, destination + 4, 0);
        return;
    }
    for (size_t channel = 0; channel < 3; ++channel) {
        const uint64_t color_numerator =
            static_cast<uint64_t>(source[channel]) *
                source_alpha * 255 +
            static_cast<uint64_t>(destination[channel]) *
                destination_alpha * inverse_alpha;
        destination[channel] =
            rounded_divide(
                color_numerator, alpha_numerator);
    }
    destination[3] =
        rounded_divide(alpha_numerator, 255);
}

ImageSequence decode_apng(
    const uint8_t *data, size_t size) {
    const ParsedApng animation =
        parse_apng(data, size);
    const uint64_t sample_count =
        checked_sample_count(
            animation.declared_frames,
            animation.height,
            animation.width,
            "apng");
    const size_t canvas_samples =
        static_cast<size_t>(animation.width) *
        animation.height * 4;

    ImageSequence sequence;
    sequence.storage_mode = "packed";
    sequence.n = animation.declared_frames;
    sequence.height = animation.height;
    sequence.width = animation.width;
    sequence.channels = 4;
    sequence.frame_dtype = "uint8";
    sequence.color_space = "srgb";
    sequence.alpha_mode = "straight";
    sequence.maxval = 255;
    sequence.loop_count_present = true;
    sequence.loop_count = animation.loop_count;
    sequence.pixels_u8.resize(
        static_cast<size_t>(sample_count));
    sequence.durations_ns = animation.durations_ns;
    sequence.timestamps_ns.reserve(sequence.n);

    std::vector<uint8_t> canvas(
        canvas_samples, 0);
    std::vector<uint8_t> previous_canvas;
    int64_t timestamp = 0;
    for (size_t frame_index = 0;
         frame_index < animation.frames.size();
         ++frame_index) {
        const FrameControl &frame =
            animation.frames[frame_index];
        const std::vector<uint8_t> pixels =
            decode_frame_rgba(animation, frame);
        if (frame.dispose_op == 2)
            previous_canvas = canvas;

        for (size_t row = 0; row < frame.height; ++row) {
            for (size_t column = 0;
                 column < frame.width; ++column) {
                const size_t source_index =
                    (row * frame.width + column) * 4;
                const size_t destination_index =
                    ((row + frame.y_offset) *
                         animation.width +
                     column + frame.x_offset) *
                    4;
                if (frame.blend_op == 0)
                    std::memcpy(
                        canvas.data() + destination_index,
                        pixels.data() + source_index, 4);
                else
                    blend_over(
                        canvas.data() + destination_index,
                        pixels.data() + source_index);
            }
        }

        std::memcpy(
            sequence.pixels_u8.data() +
                frame_index * canvas_samples,
            canvas.data(), canvas_samples);
        sequence.timestamps_ns.push_back(timestamp);
        const int64_t duration =
            sequence.durations_ns[frame_index];
        if (duration >
            std::numeric_limits<int64_t>::max() -
                timestamp)
            throw std::invalid_argument(
                "apng: animation timeline exceeds int64 nanoseconds");
        timestamp += duration;

        if (frame.dispose_op == 1) {
            for (size_t row = 0;
                 row < frame.height; ++row) {
                const size_t begin =
                    ((row + frame.y_offset) *
                         animation.width +
                     frame.x_offset) *
                    4;
                std::fill_n(
                    canvas.data() + begin,
                    static_cast<size_t>(frame.width) * 4,
                    0);
            }
        } else if (frame.dispose_op == 2) {
            canvas.swap(previous_canvas);
        }
    }
    return sequence;
}

ImageSequence read_apng(nb::handle source) {
    sio::ByteView input(source);
    ImageSequence sequence;
    {
        nb::gil_scoped_release release;
        sequence = decode_apng(
            input.data(), input.size());
    }
    validate_image_sequence(sequence, "apng");
    return sequence;
}

nb::dict inspect_apng(nb::handle source) {
    sio::ByteView input(source);
    ParsedApng value;
    {
        nb::gil_scoped_release release;
        value = parse_apng(
            input.data(), input.size());
    }
    int64_t total_duration = 0;
    for (const int64_t duration : value.durations_ns) {
        if (duration >
            std::numeric_limits<int64_t>::max() -
                total_duration)
            throw std::invalid_argument(
                "apng: animation timeline exceeds int64 nanoseconds");
        total_duration += duration;
    }
    nb::dict result;
    result["width"] = value.width;
    result["height"] = value.height;
    result["frames"] = value.declared_frames;
    result["channels"] = 4;
    result["dtype"] = "uint8";
    result["color_space"] = "srgb";
    result["alpha_mode"] = "straight";
    result["loop_count"] = value.loop_count;
    result["duration_ns"] = total_duration;
    return result;
}

bool is_apng(nb::handle source) {
    sio::ByteView input(source);
    try {
        nb::gil_scoped_release release;
        (void)parse_apng(
            input.data(), input.size());
        return true;
    } catch (const std::invalid_argument &) {
        return false;
    }
}

std::pair<uint16_t, uint16_t> apng_delay(
    int64_t duration_ns) {
    if (duration_ns <= 0)
        throw std::invalid_argument(
            "apng: frame duration must be positive");
    const uint64_t duration =
        static_cast<uint64_t>(duration_ns);
    const uint64_t divisor =
        std::gcd(duration, kNanosecondsPerSecond);
    const uint64_t numerator = duration / divisor;
    const uint64_t denominator =
        kNanosecondsPerSecond / divisor;
    if (numerator >
            std::numeric_limits<uint16_t>::max() ||
        denominator >
            std::numeric_limits<uint16_t>::max())
        throw std::invalid_argument(
            "apng: frame duration has no exact uint16 rational representation");
    return {
        static_cast<uint16_t>(numerator),
        static_cast<uint16_t>(denominator)};
}

void validate_writer_input(
    const ImageSequence &sequence) {
    validate_image_sequence(sequence, "apng");
    if (sequence.storage_mode != "packed" ||
        sequence.frame_dtype != "uint8")
        throw std::invalid_argument(
            "apng: requires packed uint8 frames");
    if (sequence.channels != 3 &&
        sequence.channels != 4)
        throw std::invalid_argument(
            "apng: requires RGB or RGBA frames");
    if (sequence.color_space != "srgb" ||
        sequence.maxval != 255)
        throw std::invalid_argument(
            "apng: requires full-range sRGB samples");
    if ((sequence.channels == 4 &&
         sequence.alpha_mode != "straight") ||
        (sequence.channels == 3 &&
         sequence.alpha_mode != "none"))
        throw std::invalid_argument(
            "apng: alpha metadata disagrees with channels");
    if (sequence.n == 0 ||
        sequence.n >
            std::numeric_limits<uint32_t>::max() ||
        sequence.width == 0 ||
        sequence.height == 0 ||
        sequence.width >
            std::numeric_limits<uint32_t>::max() ||
        sequence.height >
            std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "apng: dimensions/frame count exceed the container range");
    (void)checked_sample_count(
        static_cast<uint32_t>(sequence.n),
        static_cast<uint32_t>(sequence.height),
        static_cast<uint32_t>(sequence.width),
        "apng");
    if (sequence.background_present)
        throw std::invalid_argument(
            "apng: background metadata is not representable");
    if (!sequence.has_timing() ||
        sequence.timestamps_ns.front() != 0)
        throw std::invalid_argument(
            "apng: exact timing must start at zero");

    int64_t expected_timestamp = 0;
    for (size_t index = 0; index < sequence.n;
         ++index) {
        if (sequence.timestamps_ns[index] !=
            expected_timestamp)
            throw std::invalid_argument(
                "apng: frame timing must be contiguous");
        (void)apng_delay(
            sequence.durations_ns[index]);
        if (sequence.durations_ns[index] >
            std::numeric_limits<int64_t>::max() -
                expected_timestamp)
            throw std::invalid_argument(
                "apng: animation timeline exceeds int64 nanoseconds");
        expected_timestamp +=
            sequence.durations_ns[index];
    }
}

std::vector<ByteSpan> png_idat_spans(
    const std::vector<uint8_t> &png) {
    if (png.size() < kPngSignature.size() ||
        std::memcmp(
            png.data(), kPngSignature.data(),
            kPngSignature.size()) != 0)
        throw std::invalid_argument(
            "apng: internal PNG encoder returned an invalid signature");
    std::vector<ByteSpan> spans;
    size_t position = kPngSignature.size();
    while (position < png.size()) {
        if (png.size() - position < 12)
            throw std::invalid_argument(
                "apng: internal PNG encoder returned a truncated chunk");
        const uint32_t length =
            read_be32(png.data() + position);
        if (static_cast<size_t>(length) >
            png.size() - position - 12)
            throw std::invalid_argument(
                "apng: internal PNG encoder returned an invalid chunk");
        const uint8_t *type =
            png.data() + position + 4;
        if (equal_type(type, "IDAT"))
            spans.push_back(
                {png.data() + position + 8, length});
        position +=
            static_cast<size_t>(length) + 12;
    }
    if (spans.empty())
        throw std::invalid_argument(
            "apng: internal PNG encoder returned no IDAT");
    return spans;
}

std::vector<uint8_t> encode_frame_png(
    const uint8_t *pixels,
    uint32_t width,
    uint32_t height,
    size_t channels) {
    LodePNGState state;
    lodepng_state_init(&state);
    const LodePNGColorType color_type =
        channels == 4 ? LCT_RGBA : LCT_RGB;
    state.info_raw.colortype = color_type;
    state.info_raw.bitdepth = 8;
    state.info_png.color.colortype = color_type;
    state.info_png.color.bitdepth = 8;
    state.encoder.auto_convert = 0;
    unsigned char *encoded = nullptr;
    size_t encoded_size = 0;
    struct Guard {
        LodePNGState *state;
        unsigned char *value;
        ~Guard() {
            lodepng_state_cleanup(state);
            std::free(value);
        }
    } guard{&state, encoded};
    const unsigned error = lodepng_encode(
        &encoded, &encoded_size, pixels,
        width, height, &state);
    guard.value = encoded;
    if (error != 0)
        throw std::invalid_argument(
            std::string("apng: frame encode: ") +
            lodepng_error_text(error));
    return std::vector<uint8_t>(
        encoded, encoded + encoded_size);
}

nb::bytes write_apng(
    const ImageSequence &sequence) {
    validate_writer_input(sequence);
    ApngOutput output;
    {
        nb::gil_scoped_release release;
        output.append(
            kPngSignature.data(), kPngSignature.size());

        std::vector<uint8_t> ihdr;
        ihdr.reserve(13);
        append_be32(
            ihdr, static_cast<uint32_t>(sequence.width));
        append_be32(
            ihdr, static_cast<uint32_t>(sequence.height));
        ihdr.push_back(8);
        ihdr.push_back(
            sequence.channels == 4 ? 6 : 2);
        ihdr.push_back(0);
        ihdr.push_back(0);
        ihdr.push_back(0);
        output.chunk("IHDR", ihdr);

        std::vector<uint8_t> actl;
        actl.reserve(8);
        append_be32(
            actl, static_cast<uint32_t>(sequence.n));
        append_be32(
            actl,
            sequence.loop_count_present
                ? sequence.loop_count
                : 1);
        output.chunk("acTL", actl);

        uint32_t sequence_number = 0;
        const size_t frame_samples =
            sequence.width * sequence.height *
            sequence.channels;
        for (size_t index = 0;
             index < sequence.n; ++index) {
            const auto [delay_num, delay_den] =
                apng_delay(
                    sequence.durations_ns[index]);
            std::vector<uint8_t> fctl;
            fctl.reserve(26);
            append_be32(fctl, sequence_number++);
            append_be32(
                fctl,
                static_cast<uint32_t>(sequence.width));
            append_be32(
                fctl,
                static_cast<uint32_t>(sequence.height));
            append_be32(fctl, 0);
            append_be32(fctl, 0);
            append_be16(fctl, delay_num);
            append_be16(fctl, delay_den);
            fctl.push_back(0);
            fctl.push_back(0);
            output.chunk("fcTL", fctl);

            const uint8_t *frame =
                sequence.pixels_u8.data() +
                index * frame_samples;
            const std::vector<uint8_t> png =
                encode_frame_png(
                    frame,
                    static_cast<uint32_t>(sequence.width),
                    static_cast<uint32_t>(sequence.height),
                    sequence.channels);
            const std::vector<ByteSpan> idat =
                png_idat_spans(png);
            for (const ByteSpan span : idat) {
                if (index == 0) {
                    output.chunk(
                        "IDAT", span.data, span.size);
                } else {
                    if (span.size >
                        std::numeric_limits<uint32_t>::max() -
                            4)
                        throw std::invalid_argument(
                            "apng: compressed frame chunk is too large");
                    std::vector<uint8_t> fdat;
                    fdat.reserve(span.size + 4);
                    append_be32(
                        fdat, sequence_number++);
                    fdat.insert(
                        fdat.end(),
                        span.data, span.data + span.size);
                    output.chunk("fdAT", fdat);
                }
            }
        }
        output.chunk("IEND", nullptr, 0);
    }
    return output.finish();
}

}  // namespace

void register_apng(nb::module_ &module) {
    module.def(
        "read_apng", &read_apng,
        "data"_a,
        "Decode 8-bit RGB/RGBA APNG into fully composited packed "
        "uint8 RGBA ImageSequence frames with exact integer-nanosecond timing.");
    module.def(
        "write_apng", &write_apng,
        "sequence"_a,
        "Encode packed uint8 RGB/RGBA full-canvas frames as deterministic "
        "APNG with exact uint16-rational timing.");
    module.def(
        "_inspect_apng", &inspect_apng,
        "data"_a,
        "Validate APNG chunks and return animation metadata without "
        "inflating frame pixels.");
    module.def(
        "_is_apng", &is_apng,
        "data"_a,
        "Return whether a buffer is a valid APNG in the supported subset.");
}
