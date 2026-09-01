// codecs/sequences/mjpeg.cpp -- bounded raw concatenated-JPEG video I/O.
//
// Raw MJPEG has no container timing or metadata layer. SceneIO therefore
// preserves exactly the semantics it can prove: a nonempty sequence of
// complete 8-bit JPEG images with identical dimensions and channel layout.
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include <nanobind/stl/string.h>

#include "codecs/images/jpeg_backend.hpp"
#include "records/image_sequence.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kMjpegPixelCap = 250000000;
constexpr uint64_t kMjpegSampleCap = 1000000000;
constexpr size_t kMjpegFrameCap = 1000000;

struct JpegFrame {
    size_t offset = 0;
    size_t size = 0;
    size_t width = 0;
    size_t height = 0;
    size_t channels = 0;
};

uint16_t read_be16(const uint8_t *data) {
    return static_cast<uint16_t>(
        (static_cast<uint16_t>(data[0]) << 8) | data[1]);
}

bool is_sof(uint8_t marker) {
    // Keep inspection aligned with the built-in stb decoder. Arithmetic,
    // differential, lossless, and hierarchical JPEG modes must fail before
    // a stream is advertised as readable.
    return marker == 0xc0 || marker == 0xc1 || marker == 0xc2;
}

JpegFrame scan_jpeg(const uint8_t *data, size_t size, size_t start) {
    if (size - start < 4 || data[start] != 0xff || data[start + 1] != 0xd8)
        throw std::invalid_argument("mjpeg: every frame must begin with a JPEG SOI marker");
    size_t position = start + 2;
    bool in_entropy = false;
    bool sof_seen = false;
    uint8_t pending_marker = 0;
    JpegFrame frame;
    frame.offset = start;

    while (position < size) {
        uint8_t marker = 0;
        if (pending_marker != 0) {
            marker = pending_marker;
            pending_marker = 0;
        } else if (in_entropy) {
            while (position < size) {
                if (data[position++] != 0xff) continue;
                while (position < size && data[position] == 0xff) ++position;
                if (position == size)
                    throw std::invalid_argument("mjpeg: truncated entropy-coded JPEG frame");
                marker = data[position++];
                if (marker == 0x00 || (marker >= 0xd0 && marker <= 0xd7)) {
                    marker = 0;
                    continue;
                }
                in_entropy = false;
                break;
            }
            if (marker == 0) continue;
        } else {
            if (data[position++] != 0xff)
                throw std::invalid_argument("mjpeg: malformed JPEG marker stream");
            while (position < size && data[position] == 0xff) ++position;
            if (position == size)
                throw std::invalid_argument("mjpeg: truncated JPEG marker");
            marker = data[position++];
            if (marker == 0x00)
                throw std::invalid_argument("mjpeg: stuffed byte outside entropy data");
        }

        if (marker == 0xd9) {
            if (!sof_seen)
                throw std::invalid_argument("mjpeg: JPEG frame has no supported frame header");
            frame.size = position - start;
            return frame;
        }
        if (marker == 0xd8)
            throw std::invalid_argument("mjpeg: nested JPEG SOI marker");
        if (marker == 0x01 || (marker >= 0xd0 && marker <= 0xd7))
            continue;
        if (size - position < 2)
            throw std::invalid_argument("mjpeg: truncated JPEG segment length");
        const uint16_t segment_size = read_be16(data + position);
        if (segment_size < 2 || segment_size > size - position)
            throw std::invalid_argument("mjpeg: JPEG segment exceeds the input");
        if (is_sof(marker)) {
            if (sof_seen || segment_size < 8)
                throw std::invalid_argument("mjpeg: malformed or duplicate JPEG frame header");
            const uint8_t precision = data[position + 2];
            frame.height = read_be16(data + position + 3);
            frame.width = read_be16(data + position + 5);
            frame.channels = data[position + 7];
            if (precision != 8 || frame.width == 0 || frame.height == 0 ||
                (frame.channels != 1 && frame.channels != 3))
                throw std::invalid_argument("mjpeg: profile supports only 8-bit grayscale or RGB JPEG frames");
            const uint64_t pixels = frame.width * frame.height;
            if (pixels > kMjpegPixelCap)
                throw std::invalid_argument("mjpeg: frame dimensions exceed the supported limit");
            sof_seen = true;
        }
        position += segment_size;
        if (marker == 0xda) in_entropy = true;
    }
    throw std::invalid_argument("mjpeg: truncated JPEG frame (missing EOI marker)");
}

std::vector<JpegFrame> scan_mjpeg(const uint8_t *data, size_t size) {
    if (size == 0)
        throw std::invalid_argument("mjpeg: stream is empty");
    std::vector<JpegFrame> frames;
    size_t position = 0;
    while (position < size) {
        if (frames.size() == kMjpegFrameCap)
            throw std::invalid_argument("mjpeg: frame count exceeds the supported limit");
        JpegFrame frame = scan_jpeg(data, size, position);
        if (!frames.empty() &&
            (frame.width != frames.front().width ||
             frame.height != frames.front().height ||
             frame.channels != frames.front().channels))
            throw std::invalid_argument("mjpeg: every frame must have identical dimensions and channels");
        frames.push_back(frame);
        position += frame.size;
    }
    const uint64_t samples = frames.front().width * frames.front().height *
                             frames.front().channels;
    if (frames.size() > kMjpegSampleCap / samples)
        throw std::invalid_argument("mjpeg: decoded sequence exceeds the supported sample limit");
    return frames;
}

ImageSequence decode_mjpeg(nb::handle source, bool partial,
                           size_t start, size_t stop) {
    ByteView input(source);
    ImageSequence sequence;
    {
        nb::gil_scoped_release release;
        const std::vector<JpegFrame> frames =
            scan_mjpeg(input.data(), input.size());
        if (!partial) {
            start = 0;
            stop = frames.size();
        } else {
            checked_half_open_range(start, stop, frames.size(),
                                    "mjpeg frame range");
        }
        sequence.n = stop - start;
        sequence.height = frames.front().height;
        sequence.width = frames.front().width;
        sequence.channels = frames.front().channels;
        sequence.storage_mode = "packed";
        sequence.frame_dtype = "uint8";
        sequence.color_space = sequence.channels == 1 ? "gray" : "srgb";
        sequence.alpha_mode = "none";
        sequence.interlace = "progressive";
        sequence.maxval = 255;
        const size_t frame_samples =
            sequence.width * sequence.height * sequence.channels;
        sequence.pixels_u8.resize(sequence.n * frame_samples);
        for (size_t index = start; index < stop; ++index) {
            const JpegFrame &frame = frames[index];
            Image image = sio::jpeg_backend::decode(
                input.data() + frame.offset, frame.size);
            if (image.width != sequence.width ||
                image.height != sequence.height ||
                image.channels != sequence.channels ||
                image.dtype != PixelType::U8 || image.u8.size() != frame_samples)
                throw std::invalid_argument("mjpeg: JPEG decoder disagrees with the indexed frame header");
            std::memcpy(sequence.pixels_u8.data() +
                            (index - start) * frame_samples,
                        image.u8.data(), frame_samples);
        }
        validate_image_sequence(sequence, "mjpeg decoded sequence");
    }
    return sequence;
}

ImageSequence read_mjpeg(nb::handle source) {
    return decode_mjpeg(source, false, 0, 0);
}

ImageSequence read_mjpeg_frames(nb::handle source, size_t start, size_t stop) {
    return decode_mjpeg(source, true, start, stop);
}

nb::dict inspect_mjpeg(nb::handle source) {
    ByteView input(source);
    std::vector<JpegFrame> frames;
    {
        nb::gil_scoped_release release;
        frames = scan_mjpeg(input.data(), input.size());
    }
    nb::dict result;
    result["width"] = frames.front().width;
    result["height"] = frames.front().height;
    result["frames"] = frames.size();
    result["channels"] = frames.front().channels;
    result["dtype"] = "uint8";
    result["color_space"] = frames.front().channels == 1 ? "gray" : "srgb";
    result["alpha_mode"] = "none";
    result["storage_mode"] = "packed";
    result["codec"] = "mjpeg";
    result["timing"] = "absent";
    return result;
}

nb::bytes write_mjpeg(const ImageSequence &sequence, int quality) {
    validate_image_sequence(sequence, "mjpeg write");
    require_no_image_sequence_acquisition(sequence, "mjpeg write");
    require_no_image_sequence_projection(sequence, "mjpeg write");
    if (sequence.storage_mode != "packed" ||
        sequence.frame_dtype != "uint8" || sequence.channels != 3 ||
        sequence.color_space != "srgb" || sequence.alpha_mode != "none" ||
        sequence.maxval != 255)
        throw std::invalid_argument("mjpeg: writer requires packed uint8 sRGB frames without alpha");
    if (sequence.has_timing())
        throw std::invalid_argument("mjpeg: raw elementary streams cannot represent frame timing");
    if (quality < 1 || quality > 100)
        throw std::invalid_argument("mjpeg: quality must be in 1..100");
    if (sequence.width > 65535 || sequence.height > 65535)
        throw std::invalid_argument("mjpeg: JPEG dimensions exceed 65535");

    const size_t frame_samples = sequence.width * sequence.height * 3;
    ChunkedOutput output("mjpeg");
    {
        nb::gil_scoped_release release;
        for (size_t index = 0; index < sequence.n; ++index) {
            Image frame;
            frame.height = sequence.height;
            frame.width = sequence.width;
            frame.channels = 3;
            frame.dtype = PixelType::U8;
            frame.color_space = "srgb";
            frame.alpha_mode = "none";
            frame.maxval = 255;
            const uint8_t *begin =
                sequence.pixels_u8.data() + index * frame_samples;
            frame.u8.assign(begin, begin + frame_samples);
            const std::string encoded =
                sio::jpeg_backend::encode(frame, quality);
            output.write(encoded);
        }
    }
    return output.finish();
}

}  // namespace

void register_mjpeg(nb::module_ &module) {
    module.def("read_mjpeg", &read_mjpeg, "data"_a,
               "Decode a bounded raw concatenated-JPEG stream into packed frames.");
    module.def("read_mjpeg_frames", &read_mjpeg_frames,
               "data"_a, "start"_a, "stop"_a,
               "Decode one nonempty half-open raw MJPEG frame range.");
    module.def("write_mjpeg", &write_mjpeg,
               "sequence"_a, "quality"_a = 90,
               "Encode untimed packed uint8 sRGB frames as raw concatenated JPEG.");
    module.def("_inspect_mjpeg", &inspect_mjpeg, "data"_a,
               "Validate every raw MJPEG frame boundary and header without decoding pixels.");
}
