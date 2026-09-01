// codecs/sequences/ivf.cpp -- bounded native IVF VP8/VP9/AV1 video I/O.
//
// SceneIO owns the 32-byte IVF container and frame table. Codec work is
// delegated directly to the repository-pinned libvpx and libaom libraries;
// no general media framework or system codec discovery is involved.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <aom/aom_decoder.h>
#include <aom/aom_encoder.h>
#include <aom/aomcx.h>
#include <aom/aomdx.h>
#include <nanobind/stl/string.h>
#include <vpx/vp8cx.h>
#include <vpx/vp8dx.h>
#include <vpx/vpx_decoder.h>
#include <vpx/vpx_encoder.h>
#include <webp/encode.h>

#include "codecs/sequences/video_frame.hpp"
#include "records/image_sequence.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kIvfPixelCap = 250000000;
constexpr uint64_t kIvfSampleCap = 1000000000;
constexpr size_t kIvfFrameCap = 1000000;

enum class IvfCodec { vp8, vp9, av1 };

struct PacketView {
    const uint8_t *data = nullptr;
    size_t size = 0;
    uint64_t timestamp = 0;
};

struct ParsedIvf {
    IvfCodec codec = IvfCodec::vp8;
    size_t width = 0;
    size_t height = 0;
    uint32_t rate = 0;
    uint32_t scale = 0;
    std::vector<PacketView> packets;
};

struct VpxGuard {
    vpx_codec_ctx_t value{};
    bool initialized = false;
    ~VpxGuard() {
        if (initialized) vpx_codec_destroy(&value);
    }
};

struct AomGuard {
    aom_codec_ctx_t value{};
    bool initialized = false;
    ~AomGuard() {
        if (initialized) aom_codec_destroy(&value);
    }
};

struct PictureGuard {
    WebPPicture *value = nullptr;
    ~PictureGuard() {
        if (value) WebPPictureFree(value);
    }
};

uint16_t read_u16(const uint8_t *data) {
    return static_cast<uint16_t>(data[0]) |
           static_cast<uint16_t>(data[1] << 8);
}

uint32_t read_u32(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

uint64_t read_u64(const uint8_t *data) {
    return static_cast<uint64_t>(read_u32(data)) |
           (static_cast<uint64_t>(read_u32(data + 4)) << 32);
}

void append_u16(std::string &output, uint16_t value) {
    output.push_back(static_cast<char>(value));
    output.push_back(static_cast<char>(value >> 8));
}

void append_u32(std::string &output, uint32_t value) {
    for (size_t index = 0; index < 4; ++index)
        output.push_back(static_cast<char>(value >> (8 * index)));
}

void append_u64(std::string &output, uint64_t value) {
    for (size_t index = 0; index < 8; ++index)
        output.push_back(static_cast<char>(value >> (8 * index)));
}

const char *codec_name(IvfCodec codec) {
    switch (codec) {
        case IvfCodec::vp8: return "vp8";
        case IvfCodec::vp9: return "vp9";
        case IvfCodec::av1: return "av1";
    }
    return "unknown";
}

IvfCodec parse_codec(const std::string &value) {
    if (value == "vp8") return IvfCodec::vp8;
    if (value == "vp9") return IvfCodec::vp9;
    if (value == "av1") return IvfCodec::av1;
    throw std::invalid_argument("ivf: codec must be 'vp8', 'vp9', or 'av1'");
}

ParsedIvf parse_ivf(const uint8_t *data, size_t size) {
    if (size < 32 || std::memcmp(data, "DKIF", 4) != 0)
        throw std::invalid_argument("ivf: missing DKIF header");
    if (read_u16(data + 4) != 0 || read_u16(data + 6) != 32)
        throw std::invalid_argument("ivf: only the version-0 32-byte header is supported");

    ParsedIvf result;
    if (std::memcmp(data + 8, "VP80", 4) == 0)
        result.codec = IvfCodec::vp8;
    else if (std::memcmp(data + 8, "VP90", 4) == 0)
        result.codec = IvfCodec::vp9;
    else if (std::memcmp(data + 8, "AV01", 4) == 0)
        result.codec = IvfCodec::av1;
    else
        throw std::invalid_argument("ivf: supported FourCCs are VP80, VP90, and AV01");
    result.width = read_u16(data + 12);
    result.height = read_u16(data + 14);
    result.rate = read_u32(data + 16);
    result.scale = read_u32(data + 20);
    const uint32_t declared_frames = read_u32(data + 24);
    if (result.width == 0 || result.height == 0 ||
        result.rate == 0 || result.scale == 0)
        throw std::invalid_argument("ivf: dimensions and time base must be nonzero");
    const uint64_t pixels = result.width * result.height;
    if (pixels > kIvfPixelCap)
        throw std::invalid_argument("ivf: dimensions exceed the supported limit");

    size_t position = 32;
    while (position < size) {
        if (result.packets.size() == kIvfFrameCap)
            throw std::invalid_argument("ivf: frame count exceeds the supported limit");
        if (size - position < 12)
            throw std::invalid_argument("ivf: truncated frame header");
        const uint32_t packet_size = read_u32(data + position);
        const uint64_t timestamp = read_u64(data + position + 4);
        position += 12;
        if (packet_size == 0 || packet_size > size - position)
            throw std::invalid_argument("ivf: truncated or empty frame payload");
        if (!result.packets.empty() && timestamp <= result.packets.back().timestamp)
            throw std::invalid_argument("ivf: frame timestamps must be strictly increasing");
        result.packets.push_back({data + position, packet_size, timestamp});
        position += packet_size;
    }
    if (result.packets.empty())
        throw std::invalid_argument("ivf: stream contains no frames");
    if (declared_frames != 0 && declared_frames != result.packets.size())
        throw std::invalid_argument("ivf: declared frame count disagrees with the frame table");
    if (result.packets.front().timestamp != 0)
        throw std::invalid_argument("ivf: exact timing must start at zero");
    if (result.packets.size() > kIvfSampleCap / (pixels * 3))
        throw std::invalid_argument("ivf: decoded sequence exceeds the supported sample limit");
    return result;
}

int64_t timestamp_ns(const ParsedIvf &parsed, uint64_t value) {
    if (value > std::numeric_limits<uint64_t>::max() / parsed.scale)
        throw std::invalid_argument("ivf: timestamp overflows the time base");
    const uint64_t scaled = value * parsed.scale;
    if (scaled > std::numeric_limits<uint64_t>::max() / 1000000000ull)
        throw std::invalid_argument("ivf: timestamp exceeds nanosecond range");
    const uint64_t numerator = scaled * 1000000000ull;
    if (numerator % parsed.rate != 0 ||
        numerator / parsed.rate > static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument("ivf: timing is not exactly representable in nanoseconds");
    return static_cast<int64_t>(numerator / parsed.rate);
}

std::string vpx_failure(const vpx_codec_ctx_t &context, const char *operation) {
    std::string result = std::string("ivf: libvpx ") + operation + " failed";
    if (const char *message = vpx_codec_error(&context)) {
        result += ": ";
        result += message;
    }
    return result;
}

std::string aom_failure(const aom_codec_ctx_t &context, const char *operation) {
    std::string result = std::string("ivf: libaom ") + operation + " failed";
    if (const char *message = aom_codec_error(&context)) {
        result += ": ";
        result += message;
    }
    return result;
}

std::string vpx_matrix(IvfCodec codec, vpx_color_space_t value) {
    if (codec == IvfCodec::vp8 && value == VPX_CS_UNKNOWN) return "bt601";
    switch (value) {
        case VPX_CS_BT_601:
        case VPX_CS_SMPTE_170: return "bt601";
        case VPX_CS_BT_709: return "bt709";
        case VPX_CS_BT_2020: return "bt2020";
        case VPX_CS_UNKNOWN: return "unknown";
        default: throw std::invalid_argument("ivf: encoded color matrix is not represented");
    }
}

void accept_color(ImageSequence &sequence, const std::string &matrix,
                  const std::string &range, bool &seen) {
    if (!seen) {
        sequence.matrix = matrix;
        sequence.color_range = range;
        seen = true;
    } else if (sequence.matrix != matrix || sequence.color_range != range) {
        throw std::invalid_argument("ivf: per-frame color metadata changes are not represented");
    }
}

void decode_vpx(const ParsedIvf &parsed, size_t start, size_t stop,
                ImageSequence &sequence) {
    vpx_codec_dec_cfg_t config{};
    config.threads = static_cast<unsigned int>(std::min<size_t>(
        8, std::max<unsigned int>(1, std::thread::hardware_concurrency())));
    VpxGuard decoder;
    vpx_codec_iface_t *interface = parsed.codec == IvfCodec::vp8
        ? vpx_codec_vp8_dx() : vpx_codec_vp9_dx();
    if (vpx_codec_dec_init(&decoder.value, interface, &config, 0) != VPX_CODEC_OK)
        throw std::invalid_argument(vpx_failure(decoder.value, "decoder initialization"));
    decoder.initialized = true;
    bool color_seen = false;
    const size_t ch = sequence.chroma_height;
    const size_t cw = sequence.chroma_width;
    for (size_t index = 0; index < stop; ++index) {
        const PacketView &packet = parsed.packets[index];
        if (packet.size > std::numeric_limits<unsigned int>::max() ||
            vpx_codec_decode(&decoder.value, packet.data,
                             static_cast<unsigned int>(packet.size), nullptr, 0) != VPX_CODEC_OK)
            throw std::invalid_argument(vpx_failure(decoder.value, "frame decode"));
        vpx_codec_iter_t iterator = nullptr;
        vpx_image_t *image = vpx_codec_get_frame(&decoder.value, &iterator);
        if (!image || vpx_codec_get_frame(&decoder.value, &iterator))
            throw std::invalid_argument("ivf: each VP8/VP9 packet must produce exactly one visible frame");
        const bool high = (image->fmt & VPX_IMG_FMT_HIGHBITDEPTH) != 0;
        const vpx_img_fmt_t base = static_cast<vpx_img_fmt_t>(
            image->fmt & ~VPX_IMG_FMT_HIGHBITDEPTH);
        if (base != VPX_IMG_FMT_I420 ||
            (image->bit_depth != 8 && image->bit_depth != 10 &&
             image->bit_depth != 12) || high != (image->bit_depth > 8) ||
            image->d_w != parsed.width || image->d_h != parsed.height)
            throw std::invalid_argument("ivf: VP8/VP9 profile requires 8/10/12-bit 4:2:0 at the header dimensions");
        accept_color(sequence, vpx_matrix(parsed.codec, image->cs),
                     image->range == VPX_CR_FULL_RANGE ? "full" : "limited",
                     color_seen);
        if (index < start) continue;
        const size_t output = index - start;
        sio::video::copy_decoded_plane_to_u8(
            sequence.y, output, parsed.height, parsed.width,
            image->planes[VPX_PLANE_Y], image->stride[VPX_PLANE_Y],
            image->bit_depth, high,
            "ivf: libvpx returned inconsistent plane storage");
        sio::video::copy_decoded_plane_to_u8(
            sequence.u, output, ch, cw,
            image->planes[VPX_PLANE_U], image->stride[VPX_PLANE_U],
            image->bit_depth, high,
            "ivf: libvpx returned inconsistent plane storage");
        sio::video::copy_decoded_plane_to_u8(
            sequence.v, output, ch, cw,
            image->planes[VPX_PLANE_V], image->stride[VPX_PLANE_V],
            image->bit_depth, high,
            "ivf: libvpx returned inconsistent plane storage");
    }
}

void decode_aom(const ParsedIvf &parsed, size_t start, size_t stop,
                ImageSequence &sequence) {
    aom_codec_dec_cfg_t config{};
    config.threads = static_cast<unsigned int>(std::min<size_t>(
        8, std::max<unsigned int>(1, std::thread::hardware_concurrency())));
    config.w = static_cast<unsigned int>(parsed.width);
    config.h = static_cast<unsigned int>(parsed.height);
    config.allow_lowbitdepth = 1;
    AomGuard decoder;
    if (aom_codec_dec_init(&decoder.value, aom_codec_av1_dx(), &config, 0) != AOM_CODEC_OK)
        throw std::invalid_argument(aom_failure(decoder.value, "decoder initialization"));
    decoder.initialized = true;
    bool color_seen = false;
    const size_t ch = sequence.chroma_height;
    const size_t cw = sequence.chroma_width;
    for (size_t index = 0; index < stop; ++index) {
        const PacketView &packet = parsed.packets[index];
        if (aom_codec_decode(&decoder.value, packet.data, packet.size, nullptr) != AOM_CODEC_OK)
            throw std::invalid_argument(aom_failure(decoder.value, "frame decode"));
        aom_codec_iter_t iterator = nullptr;
        aom_image_t *image = aom_codec_get_frame(&decoder.value, &iterator);
        if (!image || aom_codec_get_frame(&decoder.value, &iterator))
            throw std::invalid_argument("ivf: each AV1 packet must produce exactly one visible frame");
        const bool high = (image->fmt & AOM_IMG_FMT_HIGHBITDEPTH) != 0;
        const aom_img_fmt_t base = static_cast<aom_img_fmt_t>(
            image->fmt & ~AOM_IMG_FMT_HIGHBITDEPTH);
        if (base != AOM_IMG_FMT_I420 ||
            (image->bit_depth != 8 && image->bit_depth != 10 &&
             image->bit_depth != 12) || high != (image->bit_depth > 8) ||
            image->d_w != parsed.width || image->d_h != parsed.height)
            throw std::invalid_argument("ivf: AV1 profile requires 8/10/12-bit 4:2:0 at the header dimensions");
        accept_color(sequence, sio::video::aom_matrix_name(image->mc, "ivf"),
                     image->range == AOM_CR_FULL_RANGE ? "full" : "limited",
                     color_seen);
        if (index < start) continue;
        const size_t output = index - start;
        sio::video::copy_decoded_plane_to_u8(
            sequence.y, output, parsed.height, parsed.width,
            image->planes[AOM_PLANE_Y], image->stride[AOM_PLANE_Y],
            image->bit_depth, high,
            "ivf: libaom returned inconsistent plane storage");
        sio::video::copy_decoded_plane_to_u8(
            sequence.u, output, ch, cw,
            image->planes[AOM_PLANE_U], image->stride[AOM_PLANE_U],
            image->bit_depth, high,
            "ivf: libaom returned inconsistent plane storage");
        sio::video::copy_decoded_plane_to_u8(
            sequence.v, output, ch, cw,
            image->planes[AOM_PLANE_V], image->stride[AOM_PLANE_V],
            image->bit_depth, high,
            "ivf: libaom returned inconsistent plane storage");
    }
}

ImageSequence decode_ivf(nb::handle source, bool partial, size_t start, size_t stop) {
    ByteView input(source);
    ImageSequence sequence;
    {
        nb::gil_scoped_release release;
        const ParsedIvf parsed = parse_ivf(input.data(), input.size());
        const size_t total = parsed.packets.size();
        if (!partial) {
            start = 0;
            stop = total;
        } else {
            checked_half_open_range(start, stop, total, "ivf frame range");
        }
        sequence.n = stop - start;
        sequence.height = parsed.height;
        sequence.width = parsed.width;
        sequence.channels = 3;
        sequence.chroma_height = (parsed.height + 1) / 2;
        sequence.chroma_width = (parsed.width + 1) / 2;
        sequence.storage_mode = "yuv_planar";
        sequence.frame_dtype = "uint8";
        sequence.color_space = "ycbcr";
        sequence.alpha_mode = "none";
        sequence.chroma_subsampling = "420";
        sequence.chroma_siting = "unspecified";
        sequence.color_range = "unknown";
        sequence.matrix = "unknown";
        sequence.interlace = "progressive";
        sequence.maxval = 255;
        sequence.frame_rate_numerator = parsed.rate;
        sequence.frame_rate_denominator = parsed.scale;
        const size_t y_size = parsed.width * parsed.height;
        const size_t c_size = sequence.chroma_width * sequence.chroma_height;
        sequence.y.resize(sequence.n * y_size);
        sequence.u.resize(sequence.n * c_size);
        sequence.v.resize(sequence.n * c_size);
        if (parsed.codec == IvfCodec::av1)
            decode_aom(parsed, start, stop, sequence);
        else
            decode_vpx(parsed, start, stop, sequence);
        sequence.timestamps_ns.reserve(sequence.n);
        sequence.durations_ns.reserve(sequence.n);
        for (size_t index = start; index < stop; ++index) {
            const int64_t current = timestamp_ns(parsed, parsed.packets[index].timestamp);
            const int64_t next = index + 1 < parsed.packets.size()
                ? timestamp_ns(parsed, parsed.packets[index + 1].timestamp)
                : timestamp_ns(parsed, parsed.packets[index].timestamp + 1);
            if (next <= current)
                throw std::invalid_argument("ivf: frame duration must be positive");
            sequence.timestamps_ns.push_back(current);
            sequence.durations_ns.push_back(next - current);
        }
        validate_image_sequence(sequence, "ivf decoded sequence");
    }
    return sequence;
}

ImageSequence read_ivf(nb::handle source) {
    return decode_ivf(source, false, 0, 0);
}

ImageSequence read_ivf_frames(nb::handle source, size_t start, size_t stop) {
    return decode_ivf(source, true, start, stop);
}

nb::dict inspect_ivf(nb::handle source) {
    ByteView input(source);
    ParsedIvf parsed;
    {
        nb::gil_scoped_release release;
        parsed = parse_ivf(input.data(), input.size());
        for (const PacketView &packet : parsed.packets)
            (void)timestamp_ns(parsed, packet.timestamp);
    }
    nb::dict result;
    result["width"] = parsed.width;
    result["height"] = parsed.height;
    result["frames"] = parsed.packets.size();
    result["channels"] = 3;
    result["dtype"] = "uint8";
    result["color_space"] = "ycbcr";
    result["alpha_mode"] = "none";
    result["storage_mode"] = "yuv_planar";
    result["codec"] = codec_name(parsed.codec);
    result["frame_rate_numerator"] = parsed.rate;
    result["frame_rate_denominator"] = parsed.scale;
    return result;
}

struct TimeBase {
    uint32_t rate = 0;
    uint32_t scale = 0;
};

TimeBase validate_write(const ImageSequence &sequence) {
    validate_image_sequence(sequence, "ivf write");
    require_no_image_sequence_acquisition(sequence, "ivf write");
    require_no_image_sequence_projection(sequence, "ivf write");
    const bool packed = sequence.storage_mode == "packed" &&
        sequence.frame_dtype == "uint8" && sequence.channels == 3 &&
        sequence.color_space == "srgb" && sequence.alpha_mode == "none" &&
        sequence.maxval == 255;
    const bool planar = sequence.storage_mode == "yuv_planar" &&
        sequence.frame_dtype == "uint8" && sequence.channels == 3 &&
        sequence.color_space == "ycbcr" && sequence.alpha_mode == "none" &&
        sequence.chroma_subsampling == "420" &&
        sequence.chroma_siting == "unspecified" &&
        (sequence.color_range == "limited" || sequence.color_range == "full") &&
        (sequence.matrix == "bt601" || sequence.matrix == "bt709" ||
         sequence.matrix == "bt2020");
    if (!packed && !planar)
        throw std::invalid_argument("ivf: writer requires packed uint8 RGB or planar uint8 4:2:0 Y'CbCr");
    if (sequence.width > 65535 || sequence.height > 65535 ||
        sequence.n > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument("ivf: dimensions or frame count exceed header limits");
    if (!sequence.has_timing() || sequence.timestamps_ns.front() != 0)
        throw std::invalid_argument("ivf: exact fixed-rate timing must start at zero");
    const int64_t duration = sequence.durations_ns.front();
    if (duration <= 0)
        throw std::invalid_argument("ivf: frame duration must be positive");
    for (size_t index = 0; index < sequence.n; ++index) {
        if (sequence.durations_ns[index] != duration ||
            sequence.timestamps_ns[index] != duration * static_cast<int64_t>(index))
            throw std::invalid_argument("ivf: writer requires contiguous fixed-rate timing");
    }
    const uint64_t divisor = std::gcd<uint64_t>(
        static_cast<uint64_t>(duration), 1000000000ull);
    const uint64_t scale = static_cast<uint64_t>(duration) / divisor;
    const uint64_t rate = 1000000000ull / divisor;
    if (scale > std::numeric_limits<uint32_t>::max() ||
        rate > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument("ivf: frame rate exceeds the container time-base limits");
    return {static_cast<uint32_t>(rate), static_cast<uint32_t>(scale)};
}

std::string make_header(const ImageSequence &sequence, IvfCodec codec,
                        const TimeBase &time_base) {
    std::string output("DKIF", 4);
    append_u16(output, 0);
    append_u16(output, 32);
    output += codec == IvfCodec::vp8 ? "VP80" :
              codec == IvfCodec::vp9 ? "VP90" : "AV01";
    append_u16(output, static_cast<uint16_t>(sequence.width));
    append_u16(output, static_cast<uint16_t>(sequence.height));
    append_u32(output, time_base.rate);
    append_u32(output, time_base.scale);
    append_u32(output, static_cast<uint32_t>(sequence.n));
    append_u32(output, 0);
    return output;
}

vpx_color_space_t vpx_color_space(const std::string &matrix) {
    if (matrix == "bt601") return VPX_CS_BT_601;
    if (matrix == "bt709") return VPX_CS_BT_709;
    if (matrix == "bt2020") return VPX_CS_BT_2020;
    throw std::invalid_argument("ivf: color matrix is not representable");
}

void assign_vpx_image(vpx_image_t &image, const ImageSequence &sequence,
                      uint8_t *y, uint8_t *u, uint8_t *v,
                      int y_stride, int uv_stride,
                      const std::string &matrix, const std::string &range) {
    image = {};
    image.fmt = VPX_IMG_FMT_I420;
    image.cs = vpx_color_space(matrix);
    image.range = range == "full" ? VPX_CR_FULL_RANGE : VPX_CR_STUDIO_RANGE;
    image.w = image.d_w = image.r_w = static_cast<unsigned int>(sequence.width);
    image.h = image.d_h = image.r_h = static_cast<unsigned int>(sequence.height);
    image.bit_depth = 8;
    image.x_chroma_shift = image.y_chroma_shift = 1;
    image.planes[VPX_PLANE_Y] = y;
    image.planes[VPX_PLANE_U] = u;
    image.planes[VPX_PLANE_V] = v;
    image.stride[VPX_PLANE_Y] = y_stride;
    image.stride[VPX_PLANE_U] = image.stride[VPX_PLANE_V] = uv_stride;
    image.bps = 12;
}

void assign_aom_image(aom_image_t &image, const ImageSequence &sequence,
                      uint8_t *y, uint8_t *u, uint8_t *v,
                      int y_stride, int uv_stride,
                      const std::string &matrix, const std::string &range) {
    image = {};
    image.fmt = AOM_IMG_FMT_I420;
    image.cp = AOM_CICP_CP_BT_709;
    image.tc = AOM_CICP_TC_SRGB;
    image.mc = matrix == "bt709" ? AOM_CICP_MC_BT_709 :
               matrix == "bt2020" ? AOM_CICP_MC_BT_2020_NCL : AOM_CICP_MC_BT_601;
    image.range = range == "full" ? AOM_CR_FULL_RANGE : AOM_CR_STUDIO_RANGE;
    image.w = image.d_w = image.r_w = static_cast<unsigned int>(sequence.width);
    image.h = image.d_h = image.r_h = static_cast<unsigned int>(sequence.height);
    image.bit_depth = 8;
    image.x_chroma_shift = image.y_chroma_shift = 1;
    image.planes[AOM_PLANE_Y] = y;
    image.planes[AOM_PLANE_U] = u;
    image.planes[AOM_PLANE_V] = v;
    image.stride[AOM_PLANE_Y] = y_stride;
    image.stride[AOM_PLANE_U] = image.stride[AOM_PLANE_V] = uv_stride;
    image.bps = 12;
}

void emit_packet(ChunkedOutput &output, const void *data, size_t size,
                 uint64_t timestamp) {
    if (!data || size == 0 || size > std::numeric_limits<uint32_t>::max())
        throw std::runtime_error("ivf: encoder emitted an invalid packet");
    std::string header;
    header.reserve(12);
    append_u32(header, static_cast<uint32_t>(size));
    append_u64(header, timestamp);
    output.write(header);
    output.write(static_cast<const char *>(data), size);
}

nb::bytes write_ivf(const ImageSequence &sequence, const std::string &codec_value,
                    float quality, int threads, int speed, int keyframe_interval) {
    const TimeBase time_base = validate_write(sequence);
    const IvfCodec codec = parse_codec(codec_value);
    if (!(quality >= 0.0f && quality <= 100.0f))
        throw std::invalid_argument("ivf: quality must be in 0..100");
    if (threads < 0 || threads > 8)
        throw std::invalid_argument("ivf: threads must be in 0..8");
    if (speed < 0 || speed > 8)
        throw std::invalid_argument("ivf: speed must be in 0..8");
    if (keyframe_interval < 1 || keyframe_interval > 32768)
        throw std::invalid_argument("ivf: keyframe_interval must be in 1..32768");
    const unsigned int lanes = threads == 0
        ? static_cast<unsigned int>(std::min<size_t>(8, std::max<unsigned int>(
              1, std::thread::hardware_concurrency())))
        : static_cast<unsigned int>(threads);
    const std::string matrix = sequence.storage_mode == "packed" ? "bt601" : sequence.matrix;
    const std::string range = sequence.storage_mode == "packed" ? "limited" : sequence.color_range;
    const size_t y_size = sequence.width * sequence.height;
    const size_t c_size = ((sequence.width + 1) / 2) * ((sequence.height + 1) / 2);
    const size_t rgb_size = y_size * 3;

    ChunkedOutput output("ivf");
    output.write(make_header(sequence, codec, time_base));
    size_t packet_count = 0;
    {
      nb::gil_scoped_release release;
      if (codec == IvfCodec::vp8 || codec == IvfCodec::vp9) {
        vpx_codec_iface_t *interface = codec == IvfCodec::vp8
            ? vpx_codec_vp8_cx() : vpx_codec_vp9_cx();
        vpx_codec_enc_cfg_t config{};
        if (vpx_codec_enc_config_default(interface, &config, 0) != VPX_CODEC_OK)
            throw std::runtime_error("ivf: libvpx has no default encoder configuration");
        config.g_w = static_cast<unsigned int>(sequence.width);
        config.g_h = static_cast<unsigned int>(sequence.height);
        config.g_timebase.num = static_cast<int>(time_base.scale);
        config.g_timebase.den = static_cast<int>(time_base.rate);
        config.g_threads = lanes;
        config.g_lag_in_frames = 0;
        config.g_pass = VPX_RC_ONE_PASS;
        config.rc_end_usage = VPX_CQ;
        config.rc_min_quantizer = 0;
        config.rc_max_quantizer = 63;
        config.rc_target_bitrate = static_cast<unsigned int>(std::min<uint64_t>(
            2000000, std::max<uint64_t>(64, sequence.width * sequence.height / 8)));
        config.rc_dropframe_thresh = 0;
        config.kf_mode = VPX_KF_AUTO;
        config.kf_min_dist = config.kf_max_dist = static_cast<unsigned int>(keyframe_interval);
        VpxGuard encoder;
        if (vpx_codec_enc_init(&encoder.value, interface, &config, 0) != VPX_CODEC_OK)
            throw std::invalid_argument(vpx_failure(encoder.value, "encoder initialization"));
        encoder.initialized = true;
        const int quantizer = static_cast<int>(std::lround((100.0f - quality) * 63.0f / 100.0f));
        if (vpx_codec_control(&encoder.value, VP8E_SET_CPUUSED, speed) != VPX_CODEC_OK ||
            vpx_codec_control(&encoder.value, VP8E_SET_CQ_LEVEL, quantizer) != VPX_CODEC_OK)
            throw std::invalid_argument(vpx_failure(encoder.value, "quality configuration"));
        for (size_t index = 0; index < sequence.n; ++index) {
            vpx_image_t image{};
            WebPPicture converted;
            PictureGuard guard;
            if (sequence.storage_mode == "packed") {
                if (!WebPPictureInit(&converted))
                    throw std::runtime_error("ivf: RGB conversion initialization failed");
                guard.value = &converted;
                converted.use_argb = 0;
                converted.width = static_cast<int>(sequence.width);
                converted.height = static_cast<int>(sequence.height);
                if (!WebPPictureImportRGB(&converted,
                        sequence.pixels_u8.data() + index * rgb_size,
                        static_cast<int>(sequence.width * 3)))
                    throw std::invalid_argument("ivf: RGB-to-YUV conversion failed");
                assign_vpx_image(image, sequence, converted.y, converted.u, converted.v,
                                 converted.y_stride, converted.uv_stride, matrix, range);
            } else {
                assign_vpx_image(image, sequence,
                    const_cast<uint8_t *>(sequence.y.data() + index * y_size),
                    const_cast<uint8_t *>(sequence.u.data() + index * c_size),
                    const_cast<uint8_t *>(sequence.v.data() + index * c_size),
                    static_cast<int>(sequence.width),
                    static_cast<int>((sequence.width + 1) / 2), matrix, range);
            }
            if (vpx_codec_encode(&encoder.value, &image,
                    static_cast<vpx_codec_pts_t>(index), 1, 0, VPX_DL_REALTIME) != VPX_CODEC_OK)
                throw std::invalid_argument(vpx_failure(encoder.value, "frame encode"));
            vpx_codec_iter_t iterator = nullptr;
            while (const vpx_codec_cx_pkt_t *packet = vpx_codec_get_cx_data(&encoder.value, &iterator)) {
                if (packet->kind == VPX_CODEC_CX_FRAME_PKT) {
                    emit_packet(output, packet->data.frame.buf, packet->data.frame.sz,
                                static_cast<uint64_t>(packet->data.frame.pts));
                    ++packet_count;
                }
            }
        }
      } else {
        aom_codec_enc_cfg_t config{};
        if (aom_codec_enc_config_default(aom_codec_av1_cx(), &config,
                                         AOM_USAGE_REALTIME) != AOM_CODEC_OK)
            throw std::runtime_error("ivf: libaom has no realtime encoder configuration");
        config.g_w = static_cast<unsigned int>(sequence.width);
        config.g_h = static_cast<unsigned int>(sequence.height);
        config.g_bit_depth = AOM_BITS_8;
        config.g_input_bit_depth = 8;
        config.g_timebase.num = static_cast<int>(time_base.scale);
        config.g_timebase.den = static_cast<int>(time_base.rate);
        config.g_threads = lanes;
        config.g_lag_in_frames = 0;
        config.g_pass = AOM_RC_ONE_PASS;
        config.rc_end_usage = AOM_CQ;
        config.rc_min_quantizer = 0;
        config.rc_max_quantizer = 63;
        config.rc_target_bitrate = static_cast<unsigned int>(std::min<uint64_t>(
            2000000, std::max<uint64_t>(64, sequence.width * sequence.height / 8)));
        config.rc_dropframe_thresh = 0;
        config.kf_mode = AOM_KF_AUTO;
        config.kf_min_dist = config.kf_max_dist = static_cast<unsigned int>(keyframe_interval);
        AomGuard encoder;
        if (aom_codec_enc_init(&encoder.value, aom_codec_av1_cx(), &config, 0) != AOM_CODEC_OK)
            throw std::invalid_argument(aom_failure(encoder.value, "encoder initialization"));
        encoder.initialized = true;
        const unsigned int quantizer = static_cast<unsigned int>(
            std::lround((100.0f - quality) * 63.0f / 100.0f));
        const int matrix_value = matrix == "bt709" ? AOM_CICP_MC_BT_709 :
                                 matrix == "bt2020" ? AOM_CICP_MC_BT_2020_NCL : AOM_CICP_MC_BT_601;
        if (aom_codec_control(&encoder.value, AOME_SET_CPUUSED, speed) != AOM_CODEC_OK ||
            aom_codec_control(&encoder.value, AOME_SET_CQ_LEVEL, quantizer) != AOM_CODEC_OK ||
            aom_codec_control(&encoder.value, AV1E_SET_COLOR_PRIMARIES,
                              static_cast<int>(AOM_CICP_CP_BT_709)) != AOM_CODEC_OK ||
            aom_codec_control(&encoder.value, AV1E_SET_TRANSFER_CHARACTERISTICS,
                              static_cast<int>(AOM_CICP_TC_SRGB)) != AOM_CODEC_OK ||
            aom_codec_control(&encoder.value, AV1E_SET_MATRIX_COEFFICIENTS,
                              matrix_value) != AOM_CODEC_OK ||
            aom_codec_control(&encoder.value, AV1E_SET_COLOR_RANGE,
                              range == "full" ? 1 : 0) != AOM_CODEC_OK)
            throw std::invalid_argument(aom_failure(encoder.value, "quality/color configuration"));
        for (size_t index = 0; index < sequence.n; ++index) {
            aom_image_t image{};
            WebPPicture converted;
            PictureGuard guard;
            if (sequence.storage_mode == "packed") {
                if (!WebPPictureInit(&converted))
                    throw std::runtime_error("ivf: RGB conversion initialization failed");
                guard.value = &converted;
                converted.use_argb = 0;
                converted.width = static_cast<int>(sequence.width);
                converted.height = static_cast<int>(sequence.height);
                if (!WebPPictureImportRGB(&converted,
                        sequence.pixels_u8.data() + index * rgb_size,
                        static_cast<int>(sequence.width * 3)))
                    throw std::invalid_argument("ivf: RGB-to-YUV conversion failed");
                assign_aom_image(image, sequence, converted.y, converted.u, converted.v,
                                 converted.y_stride, converted.uv_stride, matrix, range);
            } else {
                assign_aom_image(image, sequence,
                    const_cast<uint8_t *>(sequence.y.data() + index * y_size),
                    const_cast<uint8_t *>(sequence.u.data() + index * c_size),
                    const_cast<uint8_t *>(sequence.v.data() + index * c_size),
                    static_cast<int>(sequence.width),
                    static_cast<int>((sequence.width + 1) / 2), matrix, range);
            }
            if (aom_codec_encode(&encoder.value, &image,
                    static_cast<aom_codec_pts_t>(index), 1, 0) != AOM_CODEC_OK)
                throw std::invalid_argument(aom_failure(encoder.value, "frame encode"));
            aom_codec_iter_t iterator = nullptr;
            while (const aom_codec_cx_pkt_t *packet = aom_codec_get_cx_data(&encoder.value, &iterator)) {
                if (packet->kind == AOM_CODEC_CX_FRAME_PKT) {
                    emit_packet(output, packet->data.frame.buf, packet->data.frame.sz,
                                static_cast<uint64_t>(packet->data.frame.pts));
                    ++packet_count;
                }
            }
        }
      }
    }
    if (packet_count != sequence.n)
        throw std::runtime_error("ivf: encoder did not emit exactly one packet per frame");
    return output.finish();
}

}  // namespace

void register_ivf(nb::module_ &module) {
    module.def("read_ivf", &read_ivf, "data"_a,
               "Decode bounded IVF VP8, VP9, or AV1 into planar uint8 4:2:0 frames.");
    module.def("read_ivf_frames", &read_ivf_frames,
               "data"_a, "start"_a, "stop"_a,
               "Decode one nonempty half-open IVF frame range.");
    module.def("write_ivf", &write_ivf,
               "sequence"_a, "codec"_a = "vp9", "quality"_a = 82.0f,
               "threads"_a = 0, "speed"_a = 6, "keyframe_interval"_a = 120,
               "Encode fixed-rate packed RGB or planar 4:2:0 frames as IVF VP8/VP9/AV1.");
    module.def("_inspect_ivf", &inspect_ivf, "data"_a,
               "Validate IVF metadata and the complete bounded frame table without decoding pixels.");
}
