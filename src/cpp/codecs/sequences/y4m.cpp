// codecs/sequences/y4m.cpp -- original, dependency-free YUV4MPEG2 planar sequence I/O.
//
// The supported tier is deliberately narrow: uint8 mono, 4:2:0, 4:2:2, and
// 4:4:4 frames with one global layout and no per-frame tags. Planes remain
// native Y/U/V; this codec never performs an RGB conversion.
#include <algorithm>
#include <charconv>
#include <cstring>
#include <limits>
#include <nanobind/stl/string.h>
#include <string>
#include <string_view>
#include <vector>

#include "records/image_sequence.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kY4mLineLimit = 4096;
constexpr size_t kY4mMaxFrames = 10000000;

struct Y4mLayout {
    size_t width = 0;
    size_t height = 0;
    size_t chroma_width = 0;
    size_t chroma_height = 0;
    size_t frame_bytes = 0;
    uint32_t rate_num = 0;
    uint32_t rate_den = 0;
    uint32_t aspect_num = 0;
    uint32_t aspect_den = 0;
    std::string subsampling;
    std::string siting;
    std::string color_range = "unknown";
    std::string matrix = "unknown";
    std::string interlace;
    std::vector<size_t> payload_offsets;
};

size_t checked_product(
    size_t left, size_t right, const char *context) {
    if (left != 0 &&
        right > std::numeric_limits<size_t>::max() / left)
        throw std::length_error(
            std::string("y4m: ") + context + " overflows size_t");
    return left * right;
}

std::string_view next_line(
    const uint8_t *data, size_t size, size_t &position,
    const char *context) {
    if (position >= size)
        throw std::invalid_argument(
            std::string("y4m: missing ") + context);
    const size_t begin = position;
    const size_t available =
        std::min(kY4mLineLimit + 1, size - position);
    const void *found =
        std::memchr(data + position, '\n', available);
    if (!found)
        throw std::invalid_argument(
            std::string("y4m: unterminated or oversized ") + context);
    const size_t newline =
        static_cast<const uint8_t *>(found) - data;
    position = newline + 1;
    size_t end = newline;
    if (end != begin && data[end - 1] == '\r') --end;
    return std::string_view(
        reinterpret_cast<const char *>(data + begin),
        end - begin);
}

std::vector<std::string_view> tokens(std::string_view line) {
    std::vector<std::string_view> result;
    size_t position = 0;
    while (position < line.size()) {
        while (position < line.size() && line[position] == ' ')
            ++position;
        if (position == line.size()) break;
        const size_t begin = position;
        while (position < line.size() && line[position] != ' ')
            ++position;
        result.push_back(line.substr(begin, position - begin));
    }
    return result;
}

bool starts_with(
    std::string_view value, std::string_view prefix) {
    return value.size() >= prefix.size() &&
           value.substr(0, prefix.size()) == prefix;
}

uint32_t parse_u32(
    std::string_view text, const char *context,
    bool allow_zero = false) {
    if (text.empty())
        throw std::invalid_argument(
            std::string("y4m: empty ") + context);
    uint32_t value = 0;
    const auto [end, error] =
        std::from_chars(text.data(), text.data() + text.size(), value);
    if (error != std::errc{} ||
        end != text.data() + text.size() ||
        (!allow_zero && value == 0))
        throw std::invalid_argument(
            std::string("y4m: invalid ") + context);
    return value;
}

std::pair<uint32_t, uint32_t> parse_ratio(
    std::string_view text, const char *context,
    bool allow_unknown) {
    const size_t colon = text.find(':');
    if (colon == std::string_view::npos ||
        text.find(':', colon + 1) != std::string_view::npos)
        throw std::invalid_argument(
            std::string("y4m: malformed ") + context);
    const uint32_t numerator =
        parse_u32(text.substr(0, colon), context, allow_unknown);
    const uint32_t denominator =
        parse_u32(text.substr(colon + 1), context, allow_unknown);
    if ((numerator == 0 || denominator == 0) &&
        !(allow_unknown && numerator == 0 && denominator == 0))
        throw std::invalid_argument(
            std::string("y4m: malformed ") + context);
    return {numerator, denominator};
}

void set_chroma(
    Y4mLayout &layout, std::string_view value) {
    if (value == "mono") {
        layout.subsampling = "mono";
        layout.siting = "none";
    } else if (value == "420jpeg") {
        layout.subsampling = "420";
        layout.siting = "jpeg";
    } else if (value == "420mpeg2") {
        layout.subsampling = "420";
        layout.siting = "mpeg2";
    } else if (value == "420paldv") {
        layout.subsampling = "420";
        layout.siting = "paldv";
    } else if (value == "422") {
        layout.subsampling = "422";
        layout.siting = "unspecified";
    } else if (value == "444") {
        layout.subsampling = "444";
        layout.siting = "unspecified";
    } else {
        throw std::invalid_argument(
            "y4m: supported chroma tokens are "
            "mono|420jpeg|420mpeg2|420paldv|422|444");
    }
}

std::string expected_xyscss(const Y4mLayout &layout) {
    if (layout.subsampling == "mono") return "";
    if (layout.subsampling == "420") {
        if (layout.siting == "jpeg") return "420JPEG";
        if (layout.siting == "mpeg2") return "420MPEG2";
        return "420PALDV";
    }
    return layout.subsampling == "422" ? "422" : "444";
}

void validate_timing_extent(
    uint32_t numerator, uint32_t denominator,
    size_t frames) {
    if (frames > kY4mMaxFrames)
        throw std::invalid_argument(
            "y4m: frame count exceeds the supported limit");
    const uint64_t period =
        static_cast<uint64_t>(1000000000U) * denominator;
    const uint64_t base = period / numerator;
    const uint64_t remainder = period % numerator;
    if (base == 0)
        throw std::invalid_argument(
            "y4m: frame rate exceeds nanosecond timing resolution");
    if (frames == 0) return;
    const uint64_t maximum =
        static_cast<uint64_t>(
            std::numeric_limits<int64_t>::max());
    if (base > maximum / frames)
        throw std::invalid_argument(
            "y4m: sequence timing exceeds int64 nanoseconds");
    const uint64_t elapsed_base = base * frames;
    // remainder < numerator <= uint32 max and frames is capped at 10m, so
    // this multiplication is bounded well below uint64 max.
    const uint64_t elapsed_extra =
        (remainder * frames) / numerator;
    if (elapsed_extra > maximum - elapsed_base)
        throw std::invalid_argument(
            "y4m: sequence timing exceeds int64 nanoseconds");
}

Y4mLayout parse_y4m(const uint8_t *data, size_t size) {
    size_t position = 0;
    const std::string_view header =
        next_line(data, size, position, "stream header");
    const auto fields = tokens(header);
    if (fields.empty() || fields[0] != "YUV4MPEG2")
        throw std::invalid_argument(
            "y4m: bad magic (expected YUV4MPEG2)");

    Y4mLayout layout;
    bool have_width = false;
    bool have_height = false;
    bool have_rate = false;
    bool have_interlace = false;
    bool have_aspect = false;
    bool have_chroma = false;
    bool have_xyscss = false;
    std::string xyscss;
    for (size_t index = 1; index < fields.size(); ++index) {
        const std::string_view field = fields[index];
        if (field.size() < 2)
            throw std::invalid_argument(
                "y4m: malformed stream-header token");
        const std::string_view value = field.substr(1);
        switch (field[0]) {
            case 'W':
                if (have_width)
                    throw std::invalid_argument(
                        "y4m: duplicate width token");
                layout.width = parse_u32(value, "width");
                have_width = true;
                break;
            case 'H':
                if (have_height)
                    throw std::invalid_argument(
                        "y4m: duplicate height token");
                layout.height = parse_u32(value, "height");
                have_height = true;
                break;
            case 'F': {
                if (have_rate)
                    throw std::invalid_argument(
                        "y4m: duplicate frame-rate token");
                const auto ratio =
                    parse_ratio(value, "frame rate", false);
                layout.rate_num = ratio.first;
                layout.rate_den = ratio.second;
                have_rate = true;
                break;
            }
            case 'I':
                if (have_interlace || value.size() != 1)
                    throw std::invalid_argument(
                        "y4m: malformed or duplicate interlace token");
                if (value == "p")
                    layout.interlace = "progressive";
                else if (value == "t")
                    layout.interlace = "top_field_first";
                else if (value == "b")
                    layout.interlace = "bottom_field_first";
                else if (value == "?")
                    layout.interlace = "unknown";
                else
                    throw std::invalid_argument(
                        "y4m: mixed/per-frame interlace is unsupported");
                have_interlace = true;
                break;
            case 'A': {
                if (have_aspect)
                    throw std::invalid_argument(
                        "y4m: duplicate pixel-aspect token");
                const auto ratio =
                    parse_ratio(value, "pixel aspect", true);
                layout.aspect_num = ratio.first;
                layout.aspect_den = ratio.second;
                have_aspect = true;
                break;
            }
            case 'C':
                if (have_chroma)
                    throw std::invalid_argument(
                        "y4m: duplicate chroma token");
                set_chroma(layout, value);
                have_chroma = true;
                break;
            case 'X':
                if (starts_with(field, "XCOLORRANGE=")) {
                    const std::string_view range =
                        field.substr(std::string_view("XCOLORRANGE=").size());
                    if (layout.color_range != "unknown")
                        throw std::invalid_argument(
                            "y4m: duplicate color-range extension");
                    if (range == "FULL")
                        layout.color_range = "full";
                    else if (range == "LIMITED")
                        layout.color_range = "limited";
                    else
                        throw std::invalid_argument(
                            "y4m: unsupported color-range extension");
                } else if (starts_with(field, "XCOLORSPACE=")) {
                    if (layout.matrix != "unknown")
                        throw std::invalid_argument(
                            "y4m: duplicate color-space extension");
                    const std::string_view matrix =
                        field.substr(std::string_view("XCOLORSPACE=").size());
                    if (matrix == "BT601")
                        layout.matrix = "bt601";
                    else if (matrix == "BT709")
                        layout.matrix = "bt709";
                    else if (matrix == "BT2020")
                        layout.matrix = "bt2020";
                    else
                        throw std::invalid_argument(
                            "y4m: unsupported color-space extension");
                } else if (starts_with(field, "XYSCSS=")) {
                    if (have_xyscss)
                        throw std::invalid_argument(
                            "y4m: duplicate XYSCSS extension");
                    xyscss = std::string(
                        field.substr(std::string_view("XYSCSS=").size()));
                    if (xyscss.empty())
                        throw std::invalid_argument(
                            "y4m: empty XYSCSS extension");
                    have_xyscss = true;
                } else {
                    throw std::invalid_argument(
                        "y4m: unrepresented stream extension");
                }
                break;
            default:
                throw std::invalid_argument(
                    "y4m: unrepresented stream-header token");
        }
    }
    if (!have_width || !have_height || !have_rate ||
        !have_interlace || !have_aspect || !have_chroma)
        throw std::invalid_argument(
            "y4m: W/H/F/I/A/C stream tokens are required");
    if (have_xyscss &&
        xyscss != expected_xyscss(layout))
        throw std::invalid_argument(
            "y4m: C and XYSCSS chroma metadata disagree");

    const size_t y_bytes =
        checked_product(layout.height, layout.width, "Y plane");
    if (layout.subsampling == "mono") {
        layout.chroma_width = 0;
        layout.chroma_height = 0;
        layout.frame_bytes = y_bytes;
    } else {
        layout.chroma_width =
            layout.subsampling == "444"
                ? layout.width
                : (layout.width + 1) / 2;
        layout.chroma_height =
            layout.subsampling == "420"
                ? (layout.height + 1) / 2
                : layout.height;
        const size_t chroma_bytes =
            checked_product(
                layout.chroma_height, layout.chroma_width,
                "chroma plane");
        if (chroma_bytes >
            (std::numeric_limits<size_t>::max() - y_bytes) / 2)
            throw std::length_error(
                "y4m: frame extent overflows size_t");
        layout.frame_bytes = y_bytes + 2 * chroma_bytes;
    }

    while (position < size) {
        if (layout.payload_offsets.size() == kY4mMaxFrames)
            throw std::invalid_argument(
                "y4m: frame count exceeds the supported limit");
        const std::string_view frame_header =
            next_line(data, size, position, "frame header");
        if (frame_header != "FRAME")
            throw std::invalid_argument(
                "y4m: per-frame tags are not representable");
        if (layout.frame_bytes > size - position)
            throw std::invalid_argument(
                "y4m: truncated frame payload");
        layout.payload_offsets.push_back(position);
        position += layout.frame_bytes;
    }
    validate_timing_extent(
        layout.rate_num, layout.rate_den,
        layout.payload_offsets.size());
    return layout;
}

void assign_timing(
    ImageSequence &sequence,
    size_t full_count, size_t start, size_t stop,
    uint32_t numerator, uint32_t denominator) {
    const uint64_t period =
        static_cast<uint64_t>(1000000000U) * denominator;
    const uint64_t base = period / numerator;
    const uint64_t remainder = period % numerator;
    if (base == 0)
        throw std::invalid_argument(
            "y4m: frame rate exceeds nanosecond timing resolution");
    uint64_t timestamp = 0;
    uint64_t accumulator = 0;
    sequence.timestamps_ns.reserve(stop - start);
    sequence.durations_ns.reserve(stop - start);
    for (size_t index = 0; index < full_count; ++index) {
        uint64_t duration = base;
        accumulator += remainder;
        if (accumulator >= numerator) {
            accumulator -= numerator;
            ++duration;
        }
        const uint64_t maximum =
            static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max());
        if (timestamp > maximum ||
            duration > maximum - timestamp)
            throw std::invalid_argument(
                "y4m: sequence timing exceeds int64 nanoseconds");
        if (index >= start && index < stop) {
            sequence.timestamps_ns.push_back(
                static_cast<int64_t>(timestamp));
            sequence.durations_ns.push_back(
                static_cast<int64_t>(duration));
        }
        timestamp += duration;
    }
}

ImageSequence read_y4m_impl(
    nb::handle source, bool partial,
    size_t start, size_t stop) {
    ByteView view(source);
    const uint8_t *data = view.data();
    const size_t size = view.size();
    ImageSequence sequence;
    {
        nb::gil_scoped_release release;
        const Y4mLayout layout = parse_y4m(data, size);
        const size_t total = layout.payload_offsets.size();
        if (!partial) {
            start = 0;
            stop = total;
        } else {
            checked_half_open_range(
                start, stop, total, "y4m frame range");
        }
        sequence.storage_mode = "yuv_planar";
        sequence.n = stop - start;
        sequence.height = layout.height;
        sequence.width = layout.width;
        sequence.channels =
            layout.subsampling == "mono" ? 1 : 3;
        sequence.chroma_height = layout.chroma_height;
        sequence.chroma_width = layout.chroma_width;
        sequence.frame_dtype = "uint8";
        sequence.color_space =
            layout.subsampling == "mono" ? "gray" : "ycbcr";
        sequence.chroma_subsampling = layout.subsampling;
        sequence.chroma_siting = layout.siting;
        sequence.color_range = layout.color_range;
        sequence.matrix = layout.matrix;
        sequence.interlace = layout.interlace;
        sequence.frame_rate_numerator = layout.rate_num;
        sequence.frame_rate_denominator = layout.rate_den;
        sequence.pixel_aspect_numerator = layout.aspect_num;
        sequence.pixel_aspect_denominator = layout.aspect_den;

        const size_t y_size =
            checked_product(layout.height, layout.width, "Y plane");
        const size_t chroma_size =
            checked_product(
                layout.chroma_height, layout.chroma_width,
                "chroma plane");
        sequence.y.resize(
            checked_product(sequence.n, y_size, "selected Y planes"));
        if (layout.subsampling != "mono") {
            sequence.u.resize(
                checked_product(
                    sequence.n, chroma_size,
                    "selected U planes"));
            sequence.v.resize(
                checked_product(
                    sequence.n, chroma_size,
                    "selected V planes"));
        }
        for (size_t source_index = start;
             source_index < stop; ++source_index) {
            const size_t output = source_index - start;
            const uint8_t *frame =
                data + layout.payload_offsets[source_index];
            std::memcpy(
                sequence.y.data() + output * y_size,
                frame, y_size);
            if (chroma_size != 0) {
                std::memcpy(
                    sequence.u.data() + output * chroma_size,
                    frame + y_size, chroma_size);
                std::memcpy(
                    sequence.v.data() + output * chroma_size,
                    frame + y_size + chroma_size,
                    chroma_size);
            }
        }
        assign_timing(
            sequence, total, start, stop,
            layout.rate_num, layout.rate_den);
        validate_image_sequence(sequence, "y4m decoded sequence");
    }
    return sequence;
}

std::string chroma_token(const ImageSequence &sequence) {
    if (sequence.chroma_subsampling == "mono") return "mono";
    if (sequence.chroma_subsampling == "422" ||
        sequence.chroma_subsampling == "444") {
        if (sequence.chroma_siting != "unspecified")
            throw std::invalid_argument(
                "y4m: 4:2:2/4:4:4 writing requires unspecified "
                "chroma siting");
        return sequence.chroma_subsampling;
    }
    if (sequence.chroma_siting == "jpeg") return "420jpeg";
    if (sequence.chroma_siting == "mpeg2") return "420mpeg2";
    if (sequence.chroma_siting == "paldv") return "420paldv";
    throw std::invalid_argument(
        "y4m: 4:2:0 writing requires jpeg|mpeg2|paldv chroma siting");
}

void validate_write_timing(const ImageSequence &sequence) {
    validate_timing_extent(
        sequence.frame_rate_numerator,
        sequence.frame_rate_denominator,
        sequence.n);
    if (!sequence.has_timing()) return;

    const uint64_t period =
        static_cast<uint64_t>(1000000000U) *
        sequence.frame_rate_denominator;
    const uint64_t base =
        period / sequence.frame_rate_numerator;
    const uint64_t remainder =
        period % sequence.frame_rate_numerator;
    uint64_t timestamp = 0;
    uint64_t accumulator = 0;
    for (size_t index = 0; index < sequence.n; ++index) {
        uint64_t duration = base;
        accumulator += remainder;
        if (accumulator >= sequence.frame_rate_numerator) {
            accumulator -= sequence.frame_rate_numerator;
            ++duration;
        }
        if (sequence.timestamps_ns[index] !=
                static_cast<int64_t>(timestamp) ||
            sequence.durations_ns[index] !=
                static_cast<int64_t>(duration))
            throw std::invalid_argument(
                "y4m: exact timing disagrees with the frame-rate rational");
        timestamp += duration;
    }
}

char interlace_token(const std::string &value) {
    if (value == "progressive") return 'p';
    if (value == "top_field_first") return 't';
    if (value == "bottom_field_first") return 'b';
    if (value == "unknown") return '?';
    throw std::invalid_argument(
        "y4m: unsupported interlace metadata");
}

nb::bytes write_y4m(const ImageSequence &sequence) {
    validate_image_sequence(sequence, "y4m write");
    require_no_image_sequence_acquisition(sequence, "y4m write");
    if (sequence.storage_mode != "yuv_planar")
        throw std::invalid_argument(
            "y4m: writer requires planar YUV storage");
    if (sequence.frame_rate_numerator == 0 ||
        sequence.frame_rate_denominator == 0)
        throw std::invalid_argument(
            "y4m: writer requires a positive frame rate");
    validate_write_timing(sequence);
    const std::string chroma = chroma_token(sequence);
    const char interlace = interlace_token(sequence.interlace);
    Y4mLayout output_layout;
    output_layout.subsampling = sequence.chroma_subsampling;
    output_layout.siting = sequence.chroma_siting;
    const std::string xyscss =
        sequence.chroma_subsampling == "mono"
            ? ""
            : " XYSCSS=" + expected_xyscss(output_layout);
    std::string range;
    if (sequence.color_range == "full")
        range = " XCOLORRANGE=FULL";
    else if (sequence.color_range == "limited")
        range = " XCOLORRANGE=LIMITED";
    std::string matrix;
    if (sequence.matrix == "bt601")
        matrix = " XCOLORSPACE=BT601";
    else if (sequence.matrix == "bt709")
        matrix = " XCOLORSPACE=BT709";
    else if (sequence.matrix == "bt2020")
        matrix = " XCOLORSPACE=BT2020";

    ChunkedOutput output("y4m");
    {
        nb::gil_scoped_release release;
        const std::string header =
            "YUV4MPEG2 W" + std::to_string(sequence.width) +
            " H" + std::to_string(sequence.height) +
            " F" + std::to_string(sequence.frame_rate_numerator) +
            ":" + std::to_string(sequence.frame_rate_denominator) +
            " I" + std::string(1, interlace) +
            " A" + std::to_string(sequence.pixel_aspect_numerator) +
            ":" + std::to_string(sequence.pixel_aspect_denominator) +
            " C" + chroma + xyscss + range + matrix + "\n";
        output.write(header);
        const size_t y_size =
            checked_product(
                sequence.height, sequence.width, "Y plane");
        const size_t chroma_size =
            checked_product(
                sequence.chroma_height,
                sequence.chroma_width, "chroma plane");
        for (size_t frame = 0; frame < sequence.n; ++frame) {
            output.write("FRAME\n", 6);
            output.write(
                reinterpret_cast<const char *>(
                    sequence.y.data() + frame * y_size),
                y_size);
            if (chroma_size != 0) {
                output.write(
                    reinterpret_cast<const char *>(
                        sequence.u.data() + frame * chroma_size),
                    chroma_size);
                output.write(
                    reinterpret_cast<const char *>(
                        sequence.v.data() + frame * chroma_size),
                    chroma_size);
            }
        }
    }
    return output.finish();
}

ImageSequence read_y4m(nb::handle source) {
    return read_y4m_impl(source, false, 0, 0);
}

ImageSequence read_y4m_frames(
    nb::handle source, size_t start, size_t stop) {
    return read_y4m_impl(source, true, start, stop);
}

nb::dict inspect_y4m(nb::handle source) {
    ByteView view(source);
    Y4mLayout layout;
    {
        nb::gil_scoped_release release;
        layout = parse_y4m(view.data(), view.size());
    }
    nb::dict result;
    result["width"] = layout.width;
    result["height"] = layout.height;
    result["frames"] = layout.payload_offsets.size();
    result["channels"] =
        layout.subsampling == "mono" ? 1 : 3;
    result["chroma_width"] = layout.chroma_width;
    result["chroma_height"] = layout.chroma_height;
    result["chroma_subsampling"] = layout.subsampling;
    result["chroma_siting"] = layout.siting;
    result["color_range"] = layout.color_range;
    result["matrix"] = layout.matrix;
    result["interlace"] = layout.interlace;
    result["frame_rate_numerator"] = layout.rate_num;
    result["frame_rate_denominator"] = layout.rate_den;
    result["pixel_aspect_numerator"] = layout.aspect_num;
    result["pixel_aspect_denominator"] = layout.aspect_den;
    result["frame_bytes"] = layout.frame_bytes;
    return result;
}

}  // namespace

void register_y4m(nb::module_ &module) {
    module.def(
        "read_y4m", &read_y4m, "data"_a,
        "Decode a strict uint8 YUV4MPEG2 subset into native planar Y/U/V "
        "ImageSequence storage without RGB conversion.");
    module.def(
        "read_y4m_frames", &read_y4m_frames,
        "data"_a, "start"_a, "stop"_a,
        "Decode a nonempty half-open Y4M frame range.");
    module.def(
        "write_y4m", &write_y4m, "sequence"_a,
        "Encode native uint8 planar sequence frames as YUV4MPEG2; direct "
        "file sinks stream one frame at a time.");
    module.def(
        "_inspect_y4m", &inspect_y4m, "data"_a,
        "Validate a YUV4MPEG2 stream and return planar sequence metadata "
        "without copying frame payloads.");
}
