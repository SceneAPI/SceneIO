// codecs/sequences/webm.cpp -- bounded WebM VP8/VP9 video I/O.
//
// SceneIO owns the EBML/WebM container adapter and uses the repository-pinned
// libwebp VP8 implementation for the legacy independent-frame profile and the
// repository-pinned libvpx implementation for temporal VP8/VP9. The supported
// profile remains deliberately explicit: one progressive video track, 8-bit
// 4:2:0, no lacing, alpha, audio, subtitles, attachments, or implicit tagged
// color conversion. Timing is represented on WebM's conventional
// one-millisecond TimestampScale without rounding.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <nanobind/stl/string.h>

#include "records/image_sequence.hpp"
#include "vpx/vp8cx.h"
#include "vpx/vp8dx.h"
#include "vpx/vpx_decoder.h"
#include "vpx/vpx_encoder.h"
#include "webp/decode.h"
#include "webp/encode.h"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kTimestampScaleNs = 1000000;
constexpr uint64_t kWebmPixelCap = 250000000;
constexpr uint64_t kWebmSampleCap = 1000000000;
constexpr size_t kWebmFrameCap = 1000000;

constexpr uint32_t kEbml = 0x1A45DFA3;
constexpr uint32_t kEbmlVersion = 0x4286;
constexpr uint32_t kEbmlReadVersion = 0x42F7;
constexpr uint32_t kEbmlMaxIdLength = 0x42F2;
constexpr uint32_t kEbmlMaxSizeLength = 0x42F3;
constexpr uint32_t kDocType = 0x4282;
constexpr uint32_t kDocTypeVersion = 0x4287;
constexpr uint32_t kDocTypeReadVersion = 0x4285;
constexpr uint32_t kSegment = 0x18538067;
constexpr uint32_t kInfo = 0x1549A966;
constexpr uint32_t kSeekHead = 0x114D9B74;
constexpr uint32_t kTimestampScale = 0x2AD7B1;
constexpr uint32_t kDuration = 0x4489;
constexpr uint32_t kMuxingApp = 0x4D80;
constexpr uint32_t kWritingApp = 0x5741;
constexpr uint32_t kTracks = 0x1654AE6B;
constexpr uint32_t kTrackEntry = 0xAE;
constexpr uint32_t kTrackNumber = 0xD7;
constexpr uint32_t kTrackUid = 0x73C5;
constexpr uint32_t kTrackType = 0x83;
constexpr uint32_t kFlagEnabled = 0xB9;
constexpr uint32_t kFlagDefault = 0x88;
constexpr uint32_t kFlagForced = 0x55AA;
constexpr uint32_t kFlagLacing = 0x9C;
constexpr uint32_t kDefaultDuration = 0x23E383;
constexpr uint32_t kCodecId = 0x86;
constexpr uint32_t kCodecDecodeAll = 0xAA;
constexpr uint32_t kCodecDelay = 0x56AA;
constexpr uint32_t kSeekPreRoll = 0x56BB;
constexpr uint32_t kVideo = 0xE0;
constexpr uint32_t kFlagInterlaced = 0x9A;
constexpr uint32_t kStereoMode = 0x53B8;
constexpr uint32_t kAlphaMode = 0x53C0;
constexpr uint32_t kPixelWidth = 0xB0;
constexpr uint32_t kPixelHeight = 0xBA;
constexpr uint32_t kColour = 0x55B0;
constexpr uint32_t kMatrixCoefficients = 0x55B1;
constexpr uint32_t kRange = 0x55B9;
constexpr uint32_t kPixelCropBottom = 0x54AA;
constexpr uint32_t kPixelCropTop = 0x54BB;
constexpr uint32_t kPixelCropLeft = 0x54CC;
constexpr uint32_t kPixelCropRight = 0x54DD;
constexpr uint32_t kDisplayWidth = 0x54B0;
constexpr uint32_t kDisplayHeight = 0x54BA;
constexpr uint32_t kDisplayUnit = 0x54B2;
constexpr uint32_t kCluster = 0x1F43B675;
constexpr uint32_t kCues = 0x1C53BB6B;
constexpr uint32_t kClusterTimestamp = 0xE7;
constexpr uint32_t kSimpleBlock = 0xA3;
constexpr uint32_t kBlockGroup = 0xA0;
constexpr uint32_t kBlock = 0xA1;
constexpr uint32_t kBlockDuration = 0x9B;
constexpr uint32_t kReferencePriority = 0xFA;
constexpr uint32_t kReferenceBlock = 0xFB;
constexpr uint32_t kVoid = 0xEC;

struct PictureGuard {
    WebPPicture *value = nullptr;
    ~PictureGuard() {
        if (value) WebPPictureFree(value);
    }
};

struct MemoryWriterGuard {
    WebPMemoryWriter *value;
    ~MemoryWriterGuard() { WebPMemoryWriterClear(value); }
};

struct DecodedGuard {
    uint8_t *value = nullptr;
    ~DecodedGuard() { WebPFree(value); }
};

struct VpxCodecGuard {
    vpx_codec_ctx_t value{};
    bool initialized = false;
    ~VpxCodecGuard() {
        if (initialized) vpx_codec_destroy(&value);
    }
};

enum class WebmCodec { vp8, vp9 };

const char *codec_id(WebmCodec codec) {
    return codec == WebmCodec::vp8 ? "V_VP8" : "V_VP9";
}

const char *codec_name(WebmCodec codec) {
    return codec == WebmCodec::vp8 ? "vp8" : "vp9";
}

vpx_codec_iface_t *decoder_interface(WebmCodec codec) {
    return codec == WebmCodec::vp8
        ? vpx_codec_vp8_dx() : vpx_codec_vp9_dx();
}

vpx_codec_iface_t *encoder_interface(WebmCodec codec) {
    return codec == WebmCodec::vp8
        ? vpx_codec_vp8_cx() : vpx_codec_vp9_cx();
}

std::string vpx_failure(
    const vpx_codec_ctx_t &context, const char *operation) {
    std::string result = std::string("webm: libvpx ") + operation + " failed";
    if (const char *message = vpx_codec_error(&context)) {
        result += ": ";
        result += message;
    }
    if (const char *detail = vpx_codec_error_detail(&context)) {
        result += " (";
        result += detail;
        result += ")";
    }
    return result;
}

struct Element {
    uint32_t id = 0;
    const uint8_t *data = nullptr;
    size_t size = 0;
    bool unknown_size = false;
};

class Cursor {
public:
    Cursor(const uint8_t *data, size_t size)
        : data_(data), size_(size) {}

    bool empty() const { return position_ == size_; }

    Element next(bool allow_unknown_size = false) {
        if (empty())
            throw std::invalid_argument("webm: unexpected end of EBML data");
        const uint8_t first_id = data_[position_];
        const size_t id_width = vint_width(first_id, 4, "element id");
        if (id_width > size_ - position_)
            throw std::invalid_argument("webm: truncated EBML element id");
        uint32_t id = 0;
        for (size_t index = 0; index < id_width; ++index)
            id = (id << 8) | data_[position_++];

        if (position_ == size_)
            throw std::invalid_argument("webm: missing EBML element size");
        const uint8_t first_size = data_[position_];
        const size_t size_width = vint_width(first_size, 8, "element size");
        if (size_width > size_ - position_)
            throw std::invalid_argument("webm: truncated EBML element size");
        uint64_t value = first_size & (0xffu >> size_width);
        ++position_;
        for (size_t index = 1; index < size_width; ++index)
            value = (value << 8) | data_[position_++];
        const uint64_t unknown_value =
            (uint64_t{1} << (7 * size_width)) - 1;
        const bool unknown = value == unknown_value;
        if (unknown && !allow_unknown_size)
            throw std::invalid_argument(
                "webm: unknown-sized element is outside the supported profile");
        if (unknown) value = size_ - position_;
        if (value > size_ - position_ ||
            value > std::numeric_limits<size_t>::max())
            throw std::invalid_argument("webm: EBML element exceeds its parent");
        Element result{
            id, data_ + position_, static_cast<size_t>(value), unknown};
        position_ += static_cast<size_t>(value);
        return result;
    }

private:
    static size_t vint_width(
        uint8_t first, size_t maximum, const char *context) {
        if (first == 0)
            throw std::invalid_argument(
                std::string("webm: invalid EBML ") + context);
        size_t width = 1;
        uint8_t marker = 0x80;
        while ((first & marker) == 0) {
            ++width;
            marker >>= 1;
        }
        if (width > maximum)
            throw std::invalid_argument(
                std::string("webm: EBML ") + context + " is too wide");
        return width;
    }

    const uint8_t *data_;
    size_t size_;
    size_t position_ = 0;
};

uint64_t element_uint(const Element &element, const char *context) {
    if (element.size == 0 || element.size > 8)
        throw std::invalid_argument(
            std::string("webm: malformed ") + context);
    uint64_t value = 0;
    for (size_t index = 0; index < element.size; ++index)
        value = (value << 8) | element.data[index];
    return value;
}

int64_t element_int(const Element &element, const char *context) {
    uint64_t bits = element_uint(element, context);
    if ((element.data[0] & 0x80) != 0 && element.size < 8)
        bits |= ~uint64_t{0} << (element.size * 8);
    int64_t value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

std::string element_string(const Element &element, const char *context) {
    if (element.size > 1024 * 1024)
        throw std::invalid_argument(
            std::string("webm: ") + context + " exceeds 1 MiB");
    std::string value(
        reinterpret_cast<const char *>(element.data), element.size);
    if (value.find('\0') != std::string::npos || !valid_utf8(value))
        throw std::invalid_argument(
            std::string("webm: invalid ") + context);
    return value;
}

double element_float(const Element &element, const char *context) {
    if (element.size == 4) {
        uint32_t bits = static_cast<uint32_t>(element_uint(element, context));
        float value;
        std::memcpy(&value, &bits, sizeof(value));
        return value;
    }
    if (element.size == 8) {
        const uint64_t bits = element_uint(element, context);
        double value;
        std::memcpy(&value, &bits, sizeof(value));
        return value;
    }
    throw std::invalid_argument(
        std::string("webm: malformed ") + context);
}

void require_once(bool &seen, const char *context) {
    if (seen)
        throw std::invalid_argument(
            std::string("webm: duplicate ") + context);
    seen = true;
}

void parse_ebml_header(const Element &header) {
    if (header.id != kEbml || header.unknown_size)
        throw std::invalid_argument("webm: missing finite EBML header");
    Cursor cursor(header.data, header.size);
    bool version_seen = false;
    bool read_version_seen = false;
    bool max_id_seen = false;
    bool max_size_seen = false;
    bool doctype_seen = false;
    bool doctype_version_seen = false;
    bool doctype_read_seen = false;
    while (!cursor.empty()) {
        const Element element = cursor.next();
        switch (element.id) {
            case kEbmlVersion:
                require_once(version_seen, "EBMLVersion");
                if (element_uint(element, "EBMLVersion") != 1)
                    throw std::invalid_argument(
                        "webm: EBMLVersion must be 1");
                break;
            case kEbmlReadVersion:
                require_once(read_version_seen, "EBMLReadVersion");
                if (element_uint(element, "EBMLReadVersion") != 1)
                    throw std::invalid_argument(
                        "webm: EBMLReadVersion must be 1");
                break;
            case kEbmlMaxIdLength:
                require_once(max_id_seen, "EBMLMaxIDLength");
                if (element_uint(element, "EBMLMaxIDLength") != 4)
                    throw std::invalid_argument(
                        "webm: EBMLMaxIDLength must be 4");
                break;
            case kEbmlMaxSizeLength:
                require_once(max_size_seen, "EBMLMaxSizeLength");
                if (element_uint(element, "EBMLMaxSizeLength") != 8)
                    throw std::invalid_argument(
                        "webm: EBMLMaxSizeLength must be 8");
                break;
            case kDocType:
                require_once(doctype_seen, "DocType");
                if (element_string(element, "DocType") != "webm")
                    throw std::invalid_argument(
                        "webm: DocType must be 'webm'");
                break;
            case kDocTypeVersion: {
                require_once(doctype_version_seen, "DocTypeVersion");
                const uint64_t value = element_uint(element, "DocTypeVersion");
                if (value == 0 || value > 4)
                    throw std::invalid_argument(
                        "webm: unsupported DocTypeVersion");
                break;
            }
            case kDocTypeReadVersion:
                require_once(doctype_read_seen, "DocTypeReadVersion");
                if (element_uint(element, "DocTypeReadVersion") > 2)
                    throw std::invalid_argument(
                        "webm: unsupported DocTypeReadVersion");
                break;
            case kVoid:
                break;
            default:
                throw std::invalid_argument(
                    "webm: unrepresented EBML-header element");
        }
    }
    if (!version_seen || !read_version_seen || !max_id_seen ||
        !max_size_seen || !doctype_seen || !doctype_version_seen ||
        !doctype_read_seen)
        throw std::invalid_argument(
            "webm: incomplete EBML header");
}

struct InfoMetadata {
    bool duration_present = false;
    uint64_t duration_ms = 0;
};

InfoMetadata parse_info(const Element &info) {
    Cursor cursor(info.data, info.size);
    bool scale_seen = false;
    bool duration_seen = false;
    bool muxing_seen = false;
    bool writing_seen = false;
    InfoMetadata result;
    while (!cursor.empty()) {
        const Element element = cursor.next();
        switch (element.id) {
            case kTimestampScale:
                require_once(scale_seen, "TimestampScale");
                if (element_uint(element, "TimestampScale") !=
                    kTimestampScaleNs)
                    throw std::invalid_argument(
                        "webm: profile requires a 1 ms TimestampScale");
                break;
            case kDuration: {
                require_once(duration_seen, "Duration");
                const double value = element_float(element, "Duration");
                if (!std::isfinite(value) || value <= 0.0 ||
                    std::floor(value) != value ||
                    value > static_cast<double>(
                        std::numeric_limits<int64_t>::max() /
                        static_cast<int64_t>(kTimestampScaleNs)))
                    throw std::invalid_argument(
                        "webm: Duration is not an exact positive millisecond value");
                result.duration_present = true;
                result.duration_ms = static_cast<uint64_t>(value);
                break;
            }
            case kMuxingApp:
                require_once(muxing_seen, "MuxingApp");
                (void)element_string(element, "MuxingApp");
                break;
            case kWritingApp:
                require_once(writing_seen, "WritingApp");
                (void)element_string(element, "WritingApp");
                break;
            case kVoid:
                break;
            default:
                throw std::invalid_argument(
                    "webm: unrepresented Segment Info metadata");
        }
    }
    if (!scale_seen || !muxing_seen || !writing_seen)
        throw std::invalid_argument("webm: incomplete Segment Info");
    return result;
}

struct TrackMetadata {
    uint64_t number = 0;
    size_t width = 0;
    size_t height = 0;
    uint64_t default_duration_ms = 0;
    WebmCodec codec = WebmCodec::vp8;
    bool color_present = false;
    std::string matrix = "unknown";
    std::string color_range = "unknown";
};

void parse_colour(const Element &colour, TrackMetadata &track) {
    Cursor cursor(colour.data, colour.size);
    bool matrix_seen = false;
    bool range_seen = false;
    while (!cursor.empty()) {
        const Element element = cursor.next();
        if (element.id == kMatrixCoefficients) {
            require_once(matrix_seen, "MatrixCoefficients");
            const uint64_t value = element_uint(element, "MatrixCoefficients");
            if (value == 1) track.matrix = "bt709";
            else if (value == 6) track.matrix = "bt601";
            else if (value == 9) track.matrix = "bt2020";
            else throw std::invalid_argument(
                "webm: color matrix is not represented");
        } else if (element.id == kRange) {
            require_once(range_seen, "Range");
            const uint64_t value = element_uint(element, "Range");
            if (value == 1) track.color_range = "limited";
            else if (value == 2) track.color_range = "full";
            else throw std::invalid_argument(
                "webm: color range is not represented");
        } else if (element.id != kVoid) {
            throw std::invalid_argument(
                "webm: unrepresented Colour metadata");
        }
    }
    if (!matrix_seen || !range_seen)
        throw std::invalid_argument(
            "webm: bounded Colour metadata requires matrix and range");
    track.color_present = true;
}

TrackMetadata parse_video(const Element &video, uint64_t track_number) {
    Cursor cursor(video.data, video.size);
    bool interlace_seen = false;
    bool width_seen = false;
    bool height_seen = false;
    bool stereo_seen = false;
    bool alpha_seen = false;
    bool colour_seen = false;
    uint64_t width = 0;
    uint64_t height = 0;
    uint64_t display_width = 0;
    uint64_t display_height = 0;
    bool display_width_seen = false;
    bool display_height_seen = false;
    Element colour;
    while (!cursor.empty()) {
        const Element element = cursor.next();
        switch (element.id) {
            case kFlagInterlaced:
                require_once(interlace_seen, "FlagInterlaced");
                if (element_uint(element, "FlagInterlaced") != 2)
                    throw std::invalid_argument(
                        "webm: profile requires progressive video");
                break;
            case kStereoMode:
                require_once(stereo_seen, "StereoMode");
                if (element_uint(element, "StereoMode") != 0)
                    throw std::invalid_argument(
                        "webm: stereoscopic video is not represented");
                break;
            case kAlphaMode:
                require_once(alpha_seen, "AlphaMode");
                if (element_uint(element, "AlphaMode") != 0)
                    throw std::invalid_argument(
                        "webm: alpha video is not represented");
                break;
            case kPixelWidth:
                require_once(width_seen, "PixelWidth");
                width = element_uint(element, "PixelWidth");
                break;
            case kPixelHeight:
                require_once(height_seen, "PixelHeight");
                height = element_uint(element, "PixelHeight");
                break;
            case kColour:
                require_once(colour_seen, "Colour");
                colour = element;
                break;
            case kPixelCropBottom:
            case kPixelCropTop:
            case kPixelCropLeft:
            case kPixelCropRight:
                if (element_uint(element, "PixelCrop") != 0)
                    throw std::invalid_argument(
                        "webm: cropped display rectangles are not represented");
                break;
            case kDisplayWidth:
                require_once(display_width_seen, "DisplayWidth");
                display_width = element_uint(element, "DisplayWidth");
                break;
            case kDisplayHeight:
                require_once(display_height_seen, "DisplayHeight");
                display_height = element_uint(element, "DisplayHeight");
                break;
            case kDisplayUnit:
                if (element_uint(element, "DisplayUnit") != 0)
                    throw std::invalid_argument(
                        "webm: non-pixel display units are not represented");
                break;
            case kVoid:
                break;
            default:
                throw std::invalid_argument(
                    "webm: unrepresented video-track metadata");
        }
    }
    if (!interlace_seen || !width_seen || !height_seen ||
        width == 0 || height == 0 || width > 16383 || height > 16383 ||
        width > std::numeric_limits<size_t>::max() ||
        height > std::numeric_limits<size_t>::max())
        throw std::invalid_argument(
            "webm: incomplete or unsupported video dimensions");
    if ((display_width_seen && display_width != width) ||
        (display_height_seen && display_height != height))
        throw std::invalid_argument(
            "webm: scaled display dimensions are not represented");
    const uint64_t pixels = width * height;
    if (pixels > kWebmPixelCap)
        throw std::invalid_argument(
            "webm: canvas dimensions exceed the supported limit");
    TrackMetadata result{
        track_number, static_cast<size_t>(width), static_cast<size_t>(height)};
    if (colour_seen) parse_colour(colour, result);
    return result;
}

TrackMetadata parse_tracks(const Element &tracks) {
    Cursor tracks_cursor(tracks.data, tracks.size);
    bool entry_seen = false;
    TrackMetadata result;
    while (!tracks_cursor.empty()) {
        const Element entry = tracks_cursor.next();
        if (entry.id == kVoid) continue;
        if (entry.id != kTrackEntry || entry_seen)
            throw std::invalid_argument(
                "webm: profile requires exactly one video track");
        entry_seen = true;
        Cursor cursor(entry.data, entry.size);
        bool number_seen = false;
        bool uid_seen = false;
        bool type_seen = false;
        bool codec_seen = false;
        bool video_seen = false;
        bool default_duration_seen = false;
        uint64_t track_number = 0;
        uint64_t default_duration_ms = 0;
        WebmCodec codec = WebmCodec::vp8;
        Element video;
        while (!cursor.empty()) {
            const Element element = cursor.next();
            switch (element.id) {
                case kTrackNumber:
                    require_once(number_seen, "TrackNumber");
                    track_number = element_uint(element, "TrackNumber");
                    if (track_number == 0 || track_number > 126)
                        throw std::invalid_argument(
                            "webm: TrackNumber is outside the supported range");
                    break;
                case kTrackUid:
                    require_once(uid_seen, "TrackUID");
                    if (element_uint(element, "TrackUID") == 0)
                        throw std::invalid_argument(
                            "webm: TrackUID must be nonzero");
                    break;
                case kTrackType:
                    require_once(type_seen, "TrackType");
                    if (element_uint(element, "TrackType") != 1)
                        throw std::invalid_argument(
                            "webm: audio, subtitle, and metadata tracks are unsupported");
                    break;
                case kFlagEnabled:
                case kCodecDecodeAll:
                    if (element_uint(element, "track flag") != 1)
                        throw std::invalid_argument(
                            "webm: disabled or nondefault track flags are unsupported");
                    break;
                case kFlagDefault:
                    if (element_uint(element, "FlagDefault") > 1)
                        throw std::invalid_argument(
                            "webm: malformed FlagDefault");
                    break;
                case kFlagForced:
                case kCodecDelay:
                case kSeekPreRoll:
                    if (element_uint(element, "track flag") != 0)
                        throw std::invalid_argument(
                            "webm: delayed or forced tracks are unsupported");
                    break;
                case kFlagLacing:
                    if (element_uint(element, "FlagLacing") != 0)
                        throw std::invalid_argument(
                            "webm: laced blocks are unsupported");
                    break;
                case kDefaultDuration: {
                    require_once(default_duration_seen, "DefaultDuration");
                    const uint64_t value =
                        element_uint(element, "DefaultDuration");
                    if (value == 0 || value % kTimestampScaleNs != 0)
                        throw std::invalid_argument(
                            "webm: DefaultDuration must be exact milliseconds");
                    default_duration_ms = value / kTimestampScaleNs;
                    break;
                }
                case kCodecId:
                    require_once(codec_seen, "CodecID");
                    if (const std::string value =
                            element_string(element, "CodecID");
                        value == "V_VP8") {
                        codec = WebmCodec::vp8;
                    } else if (value == "V_VP9") {
                        codec = WebmCodec::vp9;
                    } else {
                        throw std::invalid_argument(
                            "webm: profile supports only V_VP8 or V_VP9");
                    }
                    break;
                case kVideo:
                    require_once(video_seen, "Video");
                    video = element;
                    break;
                case kVoid:
                    break;
                default:
                    throw std::invalid_argument(
                        "webm: unrepresented track metadata");
            }
        }
        if (!number_seen || !uid_seen || !type_seen || !codec_seen ||
            !video_seen)
            throw std::invalid_argument("webm: incomplete TrackEntry");
        result = parse_video(video, track_number);
        result.default_duration_ms = default_duration_ms;
        result.codec = codec;
    }
    if (!entry_seen)
        throw std::invalid_argument("webm: missing video TrackEntry");
    return result;
}

struct FramePacket {
    const uint8_t *data = nullptr;
    size_t size = 0;
    uint64_t timestamp_ms = 0;
    uint64_t duration_ms = 0;
    bool keyframe = false;
    uint64_t reference_timestamp_ms = 0;
};

struct ParsedWebm {
    size_t width = 0;
    size_t height = 0;
    std::vector<FramePacket> frames;
    uint64_t duration_ms = 0;
    WebmCodec codec = WebmCodec::vp8;
    bool all_keyframes = true;
    bool color_present = false;
    std::string matrix = "unknown";
    std::string color_range = "unknown";
};

uint64_t block_track_number(
    const uint8_t *data, size_t size, size_t &position) {
    if (position >= size || data[position] == 0)
        throw std::invalid_argument("webm: malformed Block track number");
    uint8_t marker = 0x80;
    size_t width = 1;
    while ((data[position] & marker) == 0) {
        ++width;
        marker >>= 1;
    }
    if (width > 8 || width > size - position)
        throw std::invalid_argument("webm: truncated Block track number");
    uint64_t value = data[position] & (0xffu >> width);
    ++position;
    for (size_t index = 1; index < width; ++index)
        value = (value << 8) | data[position++];
    if (value == 0)
        throw std::invalid_argument("webm: Block track number is zero");
    return value;
}

void validate_vp8_keyframe(
    const uint8_t *data, size_t size,
    size_t expected_width, size_t expected_height) {
    if (size < 10 || (data[0] & 1) != 0 ||
        data[3] != 0x9d || data[4] != 0x01 || data[5] != 0x2a)
        throw std::invalid_argument(
            "webm: profile requires independently decodable VP8 keyframes");
    const size_t width =
        (static_cast<size_t>(data[6]) |
         (static_cast<size_t>(data[7]) << 8)) & 0x3fff;
    const size_t height =
        (static_cast<size_t>(data[8]) |
         (static_cast<size_t>(data[9]) << 8)) & 0x3fff;
    if (width != expected_width || height != expected_height)
        throw std::invalid_argument(
            "webm: VP8 frame dimensions disagree with the track");
    WebPBitstreamFeatures features;
    if (WebPGetFeatures(data, size, &features) != VP8_STATUS_OK ||
        features.format != 1 || features.has_alpha || features.has_animation ||
        features.width != static_cast<int>(expected_width) ||
        features.height != static_cast<int>(expected_height))
        throw std::invalid_argument("webm: invalid VP8 keyframe payload");
}

void validate_vpx_packet(
    const uint8_t *data, size_t size, const TrackMetadata &track,
    bool declared_keyframe) {
    if (size == 0 || size > std::numeric_limits<unsigned int>::max())
        throw std::invalid_argument("webm: invalid encoded frame size");
    // libvpx's VP8 stream-info probe intentionally accepts keyframes only.
    // For an interframe the uncompressed three-byte frame tag still carries
    // the normative frame-type bit; the stateful decoder below performs the
    // complete payload validation in decode order.
    if (track.codec == WebmCodec::vp8 && !declared_keyframe) {
        if (size < 3 || (data[0] & 1) == 0)
            throw std::invalid_argument(
                "webm: container and VP8 frame-type flags disagree");
        return;
    }
    vpx_codec_stream_info_t info{};
    info.sz = sizeof(info);
    const vpx_codec_err_t status = vpx_codec_peek_stream_info(
        decoder_interface(track.codec), data,
        static_cast<unsigned int>(size), &info);
    if (status != VPX_CODEC_OK)
        throw std::invalid_argument("webm: invalid VP8/VP9 frame payload");
    const bool bitstream_keyframe = info.is_kf != 0;
    if (bitstream_keyframe != declared_keyframe)
        throw std::invalid_argument(
            "webm: container and codec keyframe flags disagree");
    if (bitstream_keyframe &&
        (info.w != track.width || info.h != track.height))
        throw std::invalid_argument(
            "webm: encoded frame dimensions disagree with the track");
    if (track.codec == WebmCodec::vp8 && bitstream_keyframe)
        validate_vp8_keyframe(
            data, size, track.width, track.height);
}

FramePacket parse_block_group(
    const Element &group, uint64_t cluster_timestamp,
    const TrackMetadata &track) {
    Cursor cursor(group.data, group.size);
    bool block_seen = false;
    bool duration_seen = false;
    bool reference_seen = false;
    int64_t reference = 0;
    Element block;
    uint64_t duration = 0;
    while (!cursor.empty()) {
        const Element element = cursor.next();
        switch (element.id) {
            case kBlock:
                require_once(block_seen, "Block");
                block = element;
                break;
            case kBlockDuration:
                require_once(duration_seen, "BlockDuration");
                duration = element_uint(element, "BlockDuration");
                break;
            case kReferencePriority:
                if (element_uint(element, "ReferencePriority") != 0)
                    throw std::invalid_argument(
                        "webm: nondefault reference priority is not represented");
                break;
            case kReferenceBlock:
                require_once(reference_seen, "ReferenceBlock");
                reference = element_int(element, "ReferenceBlock");
                if (reference >= 0)
                    throw std::invalid_argument(
                        "webm: temporal references must point backward");
                break;
            case kVoid:
                break;
            default:
                throw std::invalid_argument(
                    "webm: unrepresented BlockGroup metadata");
        }
    }
    if (!block_seen || !duration_seen || duration == 0)
        throw std::invalid_argument(
            "webm: every frame requires Block and positive BlockDuration");
    size_t position = 0;
    const uint64_t number =
        block_track_number(block.data, block.size, position);
    if (number != track.number || block.size - position < 3)
        throw std::invalid_argument("webm: malformed Block header");
    const int16_t relative = static_cast<int16_t>(
        (static_cast<uint16_t>(block.data[position]) << 8) |
        block.data[position + 1]);
    position += 2;
    const uint8_t flags = block.data[position++];
    if (flags != 0)
        throw std::invalid_argument(
            "webm: invisible, discardable, or laced Blocks are unsupported");
    if (cluster_timestamp >
        static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument("webm: frame timestamp exceeds int64");
    const int64_t signed_timestamp =
        static_cast<int64_t>(cluster_timestamp) + relative;
    if (signed_timestamp < 0)
        throw std::invalid_argument("webm: negative frame timestamp");
    if (duration >
        static_cast<uint64_t>(std::numeric_limits<int64_t>::max()) /
        kTimestampScaleNs)
        throw std::invalid_argument("webm: frame duration exceeds int64");
    const uint8_t *payload = block.data + position;
    const size_t payload_size = block.size - position;
    const bool keyframe = !reference_seen;
    uint64_t reference_timestamp = 0;
    if (reference_seen) {
        if (reference < -signed_timestamp)
            throw std::invalid_argument(
                "webm: temporal reference precedes the frame timeline");
        reference_timestamp = static_cast<uint64_t>(
            signed_timestamp + reference);
    }
    validate_vpx_packet(
        payload, payload_size, track, keyframe);
    return {
        payload, payload_size, static_cast<uint64_t>(signed_timestamp),
        duration, keyframe, reference_timestamp};
}

FramePacket parse_simple_block(
    const Element &block, uint64_t cluster_timestamp,
    const TrackMetadata &track) {
    size_t position = 0;
    const uint64_t number =
        block_track_number(block.data, block.size, position);
    if (number != track.number || block.size - position < 3)
        throw std::invalid_argument("webm: malformed SimpleBlock header");
    const int16_t relative = static_cast<int16_t>(
        (static_cast<uint16_t>(block.data[position]) << 8) |
        block.data[position + 1]);
    position += 2;
    const uint8_t flags = block.data[position++];
    if ((flags & 0x7f) != 0)
        throw std::invalid_argument(
            "webm: SimpleBlock must be visible and unlaced");
    if (cluster_timestamp >
        static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument("webm: frame timestamp exceeds int64");
    const int64_t signed_timestamp =
        static_cast<int64_t>(cluster_timestamp) + relative;
    if (signed_timestamp < 0)
        throw std::invalid_argument("webm: negative frame timestamp");
    const uint8_t *payload = block.data + position;
    const size_t payload_size = block.size - position;
    const bool keyframe = (flags & 0x80) != 0;
    validate_vpx_packet(
        payload, payload_size, track, keyframe);
    return {
        payload, payload_size, static_cast<uint64_t>(signed_timestamp),
        0, keyframe};
}

void parse_cluster(
    const Element &cluster, const TrackMetadata &track,
    ParsedWebm &result) {
    Cursor cursor(cluster.data, cluster.size);
    bool timestamp_seen = false;
    uint64_t timestamp = 0;
    while (!cursor.empty()) {
        const Element element = cursor.next();
        switch (element.id) {
            case kClusterTimestamp:
                require_once(timestamp_seen, "Cluster Timestamp");
                timestamp = element_uint(element, "Cluster Timestamp");
                break;
            case kBlockGroup:
            case kSimpleBlock: {
                if (!timestamp_seen)
                    throw std::invalid_argument(
                        "webm: Cluster Timestamp must precede Blocks");
                if (result.frames.size() == kWebmFrameCap)
                    throw std::invalid_argument(
                        "webm: frame count exceeds the supported limit");
                FramePacket frame = element.id == kBlockGroup
                    ? parse_block_group(element, timestamp, track)
                    : parse_simple_block(element, timestamp, track);
                if (!result.frames.empty()) {
                    const FramePacket &previous = result.frames.back();
                    if (frame.timestamp_ms <= previous.timestamp_ms)
                        throw std::invalid_argument(
                            "webm: frame timestamps must be strictly increasing");
                } else if (frame.timestamp_ms != 0) {
                    throw std::invalid_argument(
                        "webm: exact timing must start at zero");
                }
                if (element.id == kBlockGroup && !frame.keyframe &&
                    std::none_of(
                        result.frames.begin(), result.frames.end(),
                        [&frame](const FramePacket &candidate) {
                            return candidate.timestamp_ms ==
                                   frame.reference_timestamp_ms;
                        }))
                    throw std::invalid_argument(
                        "webm: temporal reference does not identify an earlier frame");
                if (!frame.keyframe) result.all_keyframes = false;
                result.frames.push_back(frame);
                break;
            }
            case kVoid:
                break;
            default:
                throw std::invalid_argument(
                    "webm: unrepresented Cluster metadata");
        }
    }
    if (!timestamp_seen)
        throw std::invalid_argument("webm: Cluster is missing Timestamp");
}

ParsedWebm parse_webm(const uint8_t *data, size_t size) {
    Cursor root(data, size);
    const Element header = root.next();
    parse_ebml_header(header);
    if (root.empty())
        throw std::invalid_argument("webm: missing Segment");
    const Element segment = root.next(true);
    if (segment.id != kSegment)
        throw std::invalid_argument("webm: missing Segment");
    if (!root.empty())
        throw std::invalid_argument("webm: trailing data after Segment");

    Cursor cursor(segment.data, segment.size);
    bool info_seen = false;
    bool tracks_seen = false;
    bool cluster_seen = false;
    InfoMetadata info;
    TrackMetadata track;
    ParsedWebm result;
    while (!cursor.empty()) {
        const Element element = cursor.next();
        switch (element.id) {
            case kInfo:
                require_once(info_seen, "Info");
                if (cluster_seen)
                    throw std::invalid_argument(
                        "webm: Info must precede Clusters");
                info = parse_info(element);
                break;
            case kTracks:
                require_once(tracks_seen, "Tracks");
                if (cluster_seen)
                    throw std::invalid_argument(
                        "webm: Tracks must precede Clusters");
                track = parse_tracks(element);
                result.width = track.width;
                result.height = track.height;
                result.codec = track.codec;
                result.color_present = track.color_present;
                result.matrix = track.matrix;
                result.color_range = track.color_range;
                break;
            case kCluster:
                if (!info_seen || !tracks_seen)
                    throw std::invalid_argument(
                        "webm: Info and Tracks must precede Clusters");
                cluster_seen = true;
                parse_cluster(element, track, result);
                break;
            case kSeekHead:
            case kCues:
                // Both are redundant navigation tables. Frame and track
                // semantics remain authoritative and are validated directly.
                break;
            case kVoid:
                break;
            default:
                throw std::invalid_argument(
                    "webm: unsupported top-level element");
        }
    }
    if (!info_seen || !tracks_seen || !cluster_seen || result.frames.empty())
        throw std::invalid_argument(
            "webm: profile requires Info, Tracks, and nonempty Clusters");
    if (!result.frames.front().keyframe)
        throw std::invalid_argument(
            "webm: first video frame must be a keyframe");
    const uint64_t pixels = result.width * result.height;
    if (result.frames.size() > kWebmSampleCap / (pixels * 3))
        throw std::invalid_argument(
            "webm: decoded sequence exceeds the supported sample limit");
    for (size_t index = 0; index < result.frames.size(); ++index) {
        FramePacket &frame = result.frames[index];
        if (frame.duration_ms == 0) {
            if (index + 1 < result.frames.size())
                frame.duration_ms =
                    result.frames[index + 1].timestamp_ms - frame.timestamp_ms;
            else
                frame.duration_ms = track.default_duration_ms;
        }
        if (frame.duration_ms == 0 ||
            frame.timestamp_ms >
                static_cast<uint64_t>(std::numeric_limits<int64_t>::max()) /
                    kTimestampScaleNs ||
            frame.duration_ms >
                static_cast<uint64_t>(std::numeric_limits<int64_t>::max()) /
                    kTimestampScaleNs - frame.timestamp_ms)
            throw std::invalid_argument(
                "webm: frame timing cannot be represented exactly");
        if (index + 1 < result.frames.size() &&
            frame.timestamp_ms + frame.duration_ms !=
                result.frames[index + 1].timestamp_ms)
            throw std::invalid_argument(
                "webm: frame timing must be contiguous");
    }
    const FramePacket &last = result.frames.back();
    result.duration_ms = last.timestamp_ms + last.duration_ms;
    if (info.duration_present && info.duration_ms != result.duration_ms)
        throw std::invalid_argument(
            "webm: Segment Duration disagrees with the frame timeline");
    return result;
}

void copy_vpx_plane(
    std::vector<uint8_t> &destination, size_t output_frame,
    size_t height, size_t width, const uint8_t *source, int stride) {
    if (!source || stride < 0 ||
        static_cast<size_t>(stride) < width)
        throw std::invalid_argument(
            "webm: libvpx returned inconsistent plane storage");
    const size_t plane_size = height * width;
    uint8_t *output = destination.data() + output_frame * plane_size;
    for (size_t row = 0; row < height; ++row)
        std::memcpy(
            output + row * width,
            source + row * static_cast<size_t>(stride), width);
}

std::string vpx_matrix(WebmCodec codec, vpx_color_space_t value) {
    if (codec == WebmCodec::vp8 && value == VPX_CS_UNKNOWN)
        return "bt601";
    switch (value) {
        case VPX_CS_UNKNOWN: return "unknown";
        case VPX_CS_BT_601:
        case VPX_CS_SMPTE_170: return "bt601";
        case VPX_CS_BT_709: return "bt709";
        case VPX_CS_BT_2020: return "bt2020";
        default:
            throw std::invalid_argument(
                "webm: encoded color matrix is not represented");
    }
}

void decode_vpx_range(
    const ParsedWebm &parsed, size_t start, size_t stop,
    ImageSequence &sequence) {
    size_t decode_start = start;
    while (decode_start != 0 && !parsed.frames[decode_start].keyframe)
        --decode_start;
    if (!parsed.frames[decode_start].keyframe)
        throw std::invalid_argument(
            "webm: selected frame range has no preceding keyframe");

    vpx_codec_dec_cfg_t config{};
    config.threads = static_cast<unsigned int>(std::min<size_t>(
        8, std::max<unsigned int>(1, std::thread::hardware_concurrency())));
    VpxCodecGuard decoder;
    if (vpx_codec_dec_init(
            &decoder.value, decoder_interface(parsed.codec), &config, 0) !=
        VPX_CODEC_OK)
        throw std::invalid_argument(
            vpx_failure(decoder.value, "decoder initialization"));
    decoder.initialized = true;

    const size_t chroma_height = (parsed.height + 1) / 2;
    const size_t chroma_width = (parsed.width + 1) / 2;
    bool color_metadata_seen = false;
    for (size_t index = decode_start; index < stop; ++index) {
        const FramePacket &packet = parsed.frames[index];
        if (vpx_codec_decode(
                &decoder.value, packet.data,
                static_cast<unsigned int>(packet.size), nullptr,
                VPX_DL_REALTIME) != VPX_CODEC_OK)
            throw std::invalid_argument(
                vpx_failure(decoder.value, "frame decode"));
        vpx_codec_iter_t iterator = nullptr;
        vpx_image_t *image = vpx_codec_get_frame(
            &decoder.value, &iterator);
        if (!image)
            throw std::invalid_argument(
                "webm: visible VP8/VP9 packet produced no frame");
        if (vpx_codec_get_frame(&decoder.value, &iterator) != nullptr)
            throw std::invalid_argument(
                "webm: one VP8/VP9 packet produced multiple frames");
        if (image->fmt != VPX_IMG_FMT_I420 || image->bit_depth != 8 ||
            image->d_w != parsed.width || image->d_h != parsed.height)
            throw std::invalid_argument(
                "webm: temporal profile requires 8-bit 4:2:0 frames at the track dimensions");
        const std::string decoded_matrix = vpx_matrix(parsed.codec, image->cs);
        const std::string decoded_range =
            image->range == VPX_CR_FULL_RANGE ? "full" : "limited";
        if (parsed.color_present &&
            decoded_matrix != "unknown" &&
            decoded_matrix != parsed.matrix)
            throw std::invalid_argument(
                "webm: codec and container color matrices disagree");
        if (parsed.color_present && decoded_range != parsed.color_range)
            throw std::invalid_argument(
                "webm: codec and container color ranges disagree");
        const std::string &matrix = parsed.color_present
            ? parsed.matrix : decoded_matrix;
        const std::string &range = parsed.color_present
            ? parsed.color_range : decoded_range;
        if (!color_metadata_seen) {
            sequence.matrix = matrix;
            sequence.color_range = range;
            color_metadata_seen = true;
        } else if (sequence.matrix != matrix ||
                   sequence.color_range != range) {
            throw std::invalid_argument(
                "webm: per-frame color metadata changes are not represented");
        }
        if (index < start) continue;
        const size_t output_frame = index - start;
        copy_vpx_plane(
            sequence.y, output_frame, parsed.height, parsed.width,
            image->planes[VPX_PLANE_Y], image->stride[VPX_PLANE_Y]);
        copy_vpx_plane(
            sequence.u, output_frame, chroma_height, chroma_width,
            image->planes[VPX_PLANE_U], image->stride[VPX_PLANE_U]);
        copy_vpx_plane(
            sequence.v, output_frame, chroma_height, chroma_width,
            image->planes[VPX_PLANE_V], image->stride[VPX_PLANE_V]);
    }
}

ImageSequence decode_webm(
    nb::handle source, bool partial, size_t start, size_t stop) {
    ByteView input(source);
    const uint8_t *data = input.data();
    const size_t size = input.size();
    ImageSequence sequence;
    {
        nb::gil_scoped_release release;
        const ParsedWebm parsed = parse_webm(data, size);
        const size_t total = parsed.frames.size();
        if (!partial) {
            start = 0;
            stop = total;
        } else {
            checked_half_open_range(start, stop, total, "webm frame range");
        }
        const bool legacy_rgb =
            parsed.codec == WebmCodec::vp8 && parsed.all_keyframes &&
            !parsed.color_present;
        sequence.storage_mode = legacy_rgb ? "packed" : "yuv_planar";
        sequence.n = stop - start;
        sequence.height = parsed.height;
        sequence.width = parsed.width;
        sequence.channels = 3;
        sequence.frame_dtype = "uint8";
        sequence.color_space = legacy_rgb ? "srgb" : "ycbcr";
        sequence.alpha_mode = "none";
        sequence.interlace = "progressive";
        sequence.maxval = 255;
        if (legacy_rgb) {
            const size_t frame_samples =
                parsed.height * parsed.width * sequence.channels;
            sequence.pixels_u8.resize(sequence.n * frame_samples);
            for (size_t index = start; index < stop; ++index) {
                const FramePacket &frame = parsed.frames[index];
                int width = 0;
                int height = 0;
                DecodedGuard decoded{
                    WebPDecodeRGB(frame.data, frame.size, &width, &height)};
                if (!decoded.value ||
                    width != static_cast<int>(parsed.width) ||
                    height != static_cast<int>(parsed.height))
                    throw std::invalid_argument(
                        "webm: VP8 keyframe decode failed");
                std::memcpy(
                    sequence.pixels_u8.data() +
                        (index - start) * frame_samples,
                    decoded.value, frame_samples);
            }
        } else {
            sequence.chroma_height = (parsed.height + 1) / 2;
            sequence.chroma_width = (parsed.width + 1) / 2;
            sequence.chroma_subsampling = "420";
            sequence.chroma_siting = "unspecified";
            sequence.color_range = "unknown";
            sequence.matrix = "unknown";
            const size_t y_size = parsed.height * parsed.width;
            const size_t c_size =
                sequence.chroma_height * sequence.chroma_width;
            sequence.y.resize(sequence.n * y_size);
            sequence.u.resize(sequence.n * c_size);
            sequence.v.resize(sequence.n * c_size);
            decode_vpx_range(parsed, start, stop, sequence);
        }
        sequence.timestamps_ns.reserve(sequence.n);
        sequence.durations_ns.reserve(sequence.n);
        for (size_t index = start; index < stop; ++index) {
            const FramePacket &frame = parsed.frames[index];
            sequence.timestamps_ns.push_back(static_cast<int64_t>(
                frame.timestamp_ms * kTimestampScaleNs));
            sequence.durations_ns.push_back(static_cast<int64_t>(
                frame.duration_ms * kTimestampScaleNs));
        }
        validate_image_sequence(sequence, "webm decoded sequence");
    }
    return sequence;
}

void append_id(std::string &output, uint32_t id) {
    size_t width = 1;
    if (id > 0xffffff) width = 4;
    else if (id > 0xffff) width = 3;
    else if (id > 0xff) width = 2;
    for (size_t index = width; index != 0; --index)
        output.push_back(static_cast<char>(id >> (8 * (index - 1))));
}

void append_size(std::string &output, uint64_t value) {
    size_t width = 1;
    while (width < 8 && value > (uint64_t{1} << (7 * width)) - 2)
        ++width;
    if (value > (uint64_t{1} << (7 * width)) - 2)
        throw std::length_error("webm: EBML element exceeds the size limit");
    const uint64_t encoded = value | (uint64_t{1} << (7 * width));
    for (size_t index = width; index != 0; --index)
        output.push_back(static_cast<char>(encoded >> (8 * (index - 1))));
}

void append_element(
    std::string &output, uint32_t id, const char *data, size_t size) {
    append_id(output, id);
    append_size(output, size);
    output.append(data, size);
}

void append_master(
    std::string &output, uint32_t id, const std::string &payload) {
    append_element(output, id, payload.data(), payload.size());
}

void append_uint(
    std::string &output, uint32_t id, uint64_t value) {
    size_t width = 1;
    while (width < 8 && value >= (uint64_t{1} << (8 * width)))
        ++width;
    char bytes[8];
    for (size_t index = 0; index < width; ++index)
        bytes[width - index - 1] = static_cast<char>(value >> (8 * index));
    append_element(output, id, bytes, width);
}

void append_int(
    std::string &output, uint32_t id, int64_t value) {
    uint64_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    char bytes[8];
    for (size_t index = 0; index < 8; ++index)
        bytes[7 - index] = static_cast<char>(bits >> (8 * index));
    append_element(output, id, bytes, sizeof(bytes));
}

void append_text(
    std::string &output, uint32_t id, const char *value) {
    append_element(output, id, value, std::strlen(value));
}

void append_float64(
    std::string &output, uint32_t id, double value) {
    uint64_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    char bytes[8];
    for (size_t index = 0; index < 8; ++index)
        bytes[7 - index] = static_cast<char>(bits >> (8 * index));
    append_element(output, id, bytes, 8);
}

std::string make_header(
    size_t width, size_t height, uint64_t duration_ms,
    WebmCodec codec = WebmCodec::vp8,
    const std::string &matrix = "",
    const std::string &color_range = "") {
    std::string ebml;
    append_uint(ebml, kEbmlVersion, 1);
    append_uint(ebml, kEbmlReadVersion, 1);
    append_uint(ebml, kEbmlMaxIdLength, 4);
    append_uint(ebml, kEbmlMaxSizeLength, 8);
    append_text(ebml, kDocType, "webm");
    append_uint(ebml, kDocTypeVersion, 4);
    append_uint(ebml, kDocTypeReadVersion, 2);

    std::string output;
    append_master(output, kEbml, ebml);
    append_id(output, kSegment);
    output.push_back('\x01');
    output.append(7, static_cast<char>(0xff));

    std::string info;
    append_uint(info, kTimestampScale, kTimestampScaleNs);
    append_float64(info, kDuration, static_cast<double>(duration_ms));
    append_text(info, kMuxingApp, "SceneIO");
    append_text(info, kWritingApp, "SceneIO");
    append_master(output, kInfo, info);

    std::string video;
    append_uint(video, kFlagInterlaced, 2);
    append_uint(video, kStereoMode, 0);
    append_uint(video, kAlphaMode, 0);
    append_uint(video, kPixelWidth, width);
    append_uint(video, kPixelHeight, height);
    if (!matrix.empty()) {
        std::string colour;
        const uint64_t matrix_value = matrix == "bt709" ? 1
            : matrix == "bt601" ? 6
            : matrix == "bt2020" ? 9
            : throw std::invalid_argument(
                  "webm: color matrix is not representable");
        const uint64_t range_value = color_range == "limited" ? 1
            : color_range == "full" ? 2
            : throw std::invalid_argument(
                  "webm: color range is not representable");
        append_uint(colour, kMatrixCoefficients, matrix_value);
        append_uint(colour, kRange, range_value);
        append_master(video, kColour, colour);
    }

    std::string entry;
    append_uint(entry, kTrackNumber, 1);
    append_uint(entry, kTrackUid, 1);
    append_uint(entry, kTrackType, 1);
    append_uint(entry, kFlagEnabled, 1);
    append_uint(entry, kFlagDefault, 1);
    append_uint(entry, kFlagForced, 0);
    append_uint(entry, kFlagLacing, 0);
    append_text(entry, kCodecId, codec_id(codec));
    append_uint(entry, kCodecDecodeAll, 1);
    append_uint(entry, kCodecDelay, 0);
    append_uint(entry, kSeekPreRoll, 0);
    append_master(entry, kVideo, video);
    std::string tracks;
    append_master(tracks, kTrackEntry, entry);
    append_master(output, kTracks, tracks);
    return output;
}

uint32_t read_le_u32(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

std::string extract_vp8_packet(
    const uint8_t *data, size_t size) {
    if (size < 12 || std::memcmp(data, "RIFF", 4) != 0 ||
        std::memcmp(data + 8, "WEBP", 4) != 0 ||
        read_le_u32(data + 4) != size - 8)
        throw std::invalid_argument(
            "webm: libwebp returned a malformed frame container");
    size_t position = 12;
    bool found = false;
    std::string packet;
    while (position < size) {
        if (size - position < 8)
            throw std::invalid_argument(
                "webm: libwebp returned a truncated frame chunk");
        const uint8_t *fourcc = data + position;
        const uint32_t chunk_size = read_le_u32(data + position + 4);
        position += 8;
        if (chunk_size > size - position)
            throw std::invalid_argument(
                "webm: libwebp frame chunk exceeds its container");
        if (std::memcmp(fourcc, "VP8 ", 4) == 0) {
            if (found)
                throw std::invalid_argument(
                    "webm: libwebp returned duplicate VP8 chunks");
            packet.assign(
                reinterpret_cast<const char *>(data + position), chunk_size);
            found = true;
        } else {
            throw std::invalid_argument(
                "webm: libwebp returned a non-VP8 frame profile");
        }
        position += chunk_size;
        if ((chunk_size & 1) != 0) {
            if (position == size)
                throw std::invalid_argument(
                    "webm: libwebp frame chunk lacks padding");
            ++position;
        }
    }
    if (!found || position != size)
        throw std::invalid_argument(
            "webm: libwebp frame has no VP8 payload");
    return packet;
}

std::string encode_vp8_frame(
    const uint8_t *pixels, size_t width, size_t height,
    const WebPConfig &config) {
    WebPPicture picture;
    if (!WebPPictureInit(&picture))
        throw std::invalid_argument(
            "webm: VP8 picture initialization failed");
    PictureGuard picture_guard{&picture};
    picture.use_argb = 1;
    picture.width = static_cast<int>(width);
    picture.height = static_cast<int>(height);
    if (!WebPPictureImportRGB(
            &picture, pixels, static_cast<int>(width * 3)))
        throw std::invalid_argument("webm: VP8 frame import failed");
    WebPMemoryWriter writer;
    WebPMemoryWriterInit(&writer);
    MemoryWriterGuard writer_guard{&writer};
    picture.writer = WebPMemoryWrite;
    picture.custom_ptr = &writer;
    if (!WebPEncode(&config, &picture))
        throw std::invalid_argument(
            "webm: VP8 frame encode failed (error " +
            std::to_string(static_cast<int>(picture.error_code)) + ")");
    return extract_vp8_packet(writer.mem, writer.size);
}

std::string make_cluster(
    uint64_t timestamp_ms, uint64_t duration_ms,
    const std::string &packet, bool keyframe = true,
    uint64_t reference_distance_ms = 0) {
    std::string block;
    block.push_back(static_cast<char>(0x81));
    block.push_back(0);
    block.push_back(0);
    block.push_back(0);
    block.append(packet);
    std::string group;
    append_element(group, kBlock, block.data(), block.size());
    append_uint(group, kBlockDuration, duration_ms);
    if (!keyframe) {
        if (reference_distance_ms == 0 ||
            reference_distance_ms > static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()))
            throw std::invalid_argument(
                "webm: temporal reference distance is not representable");
        append_int(
            group, kReferenceBlock,
            -static_cast<int64_t>(reference_distance_ms));
    }
    std::string cluster;
    append_uint(cluster, kClusterTimestamp, timestamp_ms);
    append_master(cluster, kBlockGroup, group);
    std::string output;
    append_master(output, kCluster, cluster);
    return output;
}

uint64_t validate_writer_input(
    const ImageSequence &sequence, bool temporal = false) {
    validate_image_sequence(sequence, "webm write");
    const bool packed =
        sequence.storage_mode == "packed" &&
        sequence.frame_dtype == "uint8" && sequence.channels == 3;
    const bool planar =
        sequence.storage_mode == "yuv_planar" &&
        sequence.frame_dtype == "uint8" && sequence.channels == 3 &&
        sequence.color_space == "ycbcr" &&
        sequence.chroma_subsampling == "420" &&
        sequence.chroma_siting == "unspecified" &&
        (sequence.color_range == "limited" ||
         sequence.color_range == "full") &&
        (sequence.matrix == "bt601" ||
         sequence.matrix == "bt709" ||
         sequence.matrix == "bt2020");
    if ((!temporal && !packed) || (temporal && !packed && !planar))
        throw std::invalid_argument(
            temporal
                ? "webm: temporal writer requires packed uint8 RGB or planar uint8 4:2:0 Y'CbCr"
                : "webm: all-keyframe writer requires packed uint8 RGB frames");
    if (packed && (sequence.color_space != "srgb" ||
                   sequence.alpha_mode != "none" ||
                   sequence.maxval != 255))
        throw std::invalid_argument(
            "webm: writer requires full-range sRGB without alpha");
    if (planar && sequence.alpha_mode != "none")
        throw std::invalid_argument(
            "webm: temporal planar writer requires no alpha");
    if (sequence.interlace != "progressive")
        throw std::invalid_argument(
            "webm: writer requires progressive frames");
    if (sequence.n == 0 || sequence.width == 0 || sequence.height == 0 ||
        sequence.width > 16383 || sequence.height > 16383)
        throw std::invalid_argument(
            "webm: writer needs nonempty frames within the VP8/VP9 axis limit");
    const uint64_t pixels = sequence.width * sequence.height;
    if (pixels > kWebmPixelCap ||
        sequence.n > kWebmFrameCap ||
        sequence.n > kWebmSampleCap / (pixels * 3))
        throw std::invalid_argument(
            "webm: sequence exceeds the supported sample limit");
    if (sequence.loop_count_present || sequence.background_present)
        throw std::invalid_argument(
            "webm: loop and animation-background metadata are not represented");
    if (!sequence.has_timing() || sequence.timestamps_ns.front() != 0)
        throw std::invalid_argument(
            "webm: exact timing must start at zero");
    int64_t expected = 0;
    for (size_t index = 0; index < sequence.n; ++index) {
        const int64_t timestamp = sequence.timestamps_ns[index];
        const int64_t duration = sequence.durations_ns[index];
        if (timestamp != expected ||
            timestamp % static_cast<int64_t>(kTimestampScaleNs) != 0 ||
            duration % static_cast<int64_t>(kTimestampScaleNs) != 0)
            throw std::invalid_argument(
                "webm: timing must be contiguous and exactly representable in milliseconds");
        if (duration <= 0 ||
            duration > std::numeric_limits<int64_t>::max() - expected)
            throw std::invalid_argument(
                "webm: frame timeline exceeds int64 nanoseconds");
        expected += duration;
    }
    return static_cast<uint64_t>(
        expected / static_cast<int64_t>(kTimestampScaleNs));
}

ImageSequence read_webm(nb::handle source) {
    return decode_webm(source, false, 0, 0);
}

ImageSequence read_webm_frames(
    nb::handle source, size_t start, size_t stop) {
    return decode_webm(source, true, start, stop);
}

nb::dict inspect_webm(nb::handle source) {
    ByteView input(source);
    ParsedWebm parsed;
    {
        nb::gil_scoped_release release;
        parsed = parse_webm(input.data(), input.size());
    }
    nb::dict result;
    result["width"] = parsed.width;
    result["height"] = parsed.height;
    result["frames"] = parsed.frames.size();
    result["channels"] = 3;
    result["dtype"] = "uint8";
    result["alpha_mode"] = "none";
    const bool legacy_rgb =
        parsed.codec == WebmCodec::vp8 && parsed.all_keyframes &&
        !parsed.color_present;
    result["color_space"] = legacy_rgb ? "srgb" : "ycbcr";
    result["color_range"] = legacy_rgb ? "unknown" : parsed.color_range;
    result["matrix"] = legacy_rgb ? "unknown" : parsed.matrix;
    result["codec"] = codec_name(parsed.codec);
    result["profile"] = legacy_rgb ? "all_keyframe" : "temporal";
    result["storage_mode"] = legacy_rgb ? "packed" : "yuv_planar";
    result["keyframes"] = std::count_if(
        parsed.frames.begin(), parsed.frames.end(),
        [](const FramePacket &frame) { return frame.keyframe; });
    result["duration_ns"] = parsed.duration_ms * kTimestampScaleNs;
    return result;
}

vpx_color_space_t vpx_color_space(const std::string &matrix) {
    if (matrix == "bt601") return VPX_CS_BT_601;
    if (matrix == "bt709") return VPX_CS_BT_709;
    if (matrix == "bt2020") return VPX_CS_BT_2020;
    throw std::invalid_argument(
        "webm: temporal writer cannot represent the requested color matrix");
}

void assign_vpx_image(
    vpx_image_t &image, size_t width, size_t height,
    uint8_t *y, uint8_t *u, uint8_t *v,
    int y_stride, int uv_stride,
    vpx_color_space_t color_space, vpx_color_range_t range) {
    image = {};
    image.fmt = VPX_IMG_FMT_I420;
    image.cs = color_space;
    image.range = range;
    image.w = image.d_w = image.r_w = static_cast<unsigned int>(width);
    image.h = image.d_h = image.r_h = static_cast<unsigned int>(height);
    image.bit_depth = 8;
    image.x_chroma_shift = 1;
    image.y_chroma_shift = 1;
    image.planes[VPX_PLANE_Y] = y;
    image.planes[VPX_PLANE_U] = u;
    image.planes[VPX_PLANE_V] = v;
    image.stride[VPX_PLANE_Y] = y_stride;
    image.stride[VPX_PLANE_U] = uv_stride;
    image.stride[VPX_PLANE_V] = uv_stride;
    image.bps = 12;
}

void drain_vpx_packets(
    vpx_codec_ctx_t &encoder, WebmCodec codec,
    const ImageSequence &sequence, ChunkedOutput &output,
    size_t &packet_index) {
    TrackMetadata track{
        1, sequence.width, sequence.height, 0, codec};
    vpx_codec_iter_t iterator = nullptr;
    while (const vpx_codec_cx_pkt_t *packet =
               vpx_codec_get_cx_data(&encoder, &iterator)) {
        if (packet->kind != VPX_CODEC_CX_FRAME_PKT)
            throw std::runtime_error(
                "webm: temporal encoder emitted an unexpected packet kind");
        if (packet_index >= sequence.n ||
            packet->data.frame.buf == nullptr ||
            packet->data.frame.sz == 0 ||
            (packet->data.frame.flags &
             (VPX_FRAME_IS_INVISIBLE | VPX_FRAME_IS_FRAGMENT)) != 0)
            throw std::runtime_error(
                "webm: temporal encoder emitted an unsupported frame packet");
        const uint64_t timestamp_ms = static_cast<uint64_t>(
            sequence.timestamps_ns[packet_index] /
            static_cast<int64_t>(kTimestampScaleNs));
        const uint64_t duration_ms = static_cast<uint64_t>(
            sequence.durations_ns[packet_index] /
            static_cast<int64_t>(kTimestampScaleNs));
        if (packet->data.frame.pts < 0 ||
            static_cast<uint64_t>(packet->data.frame.pts) != timestamp_ms ||
            static_cast<uint64_t>(packet->data.frame.duration) != duration_ms)
            throw std::runtime_error(
                "webm: temporal encoder changed the exact frame timeline");
        const bool keyframe =
            (packet->data.frame.flags & VPX_FRAME_IS_KEY) != 0;
        if (packet_index == 0 && !keyframe)
            throw std::runtime_error(
                "webm: temporal encoder did not begin with a keyframe");
        const auto *data = static_cast<const uint8_t *>(
            packet->data.frame.buf);
        validate_vpx_packet(
            data, packet->data.frame.sz, track, keyframe);
        const std::string payload(
            reinterpret_cast<const char *>(data),
            packet->data.frame.sz);
        const uint64_t reference_distance_ms = keyframe ? 0
            : timestamp_ms - static_cast<uint64_t>(
                sequence.timestamps_ns[packet_index - 1] /
                static_cast<int64_t>(kTimestampScaleNs));
        output.write(make_cluster(
            timestamp_ms, duration_ms, payload, keyframe,
            reference_distance_ms));
        ++packet_index;
    }
}

nb::bytes write_webm_temporal(
    const ImageSequence &sequence, const std::string &codec_value,
    float quality, int threads, int speed, int keyframe_interval) {
    const uint64_t duration_ms = validate_writer_input(sequence, true);
    const WebmCodec codec = codec_value == "vp8"
        ? WebmCodec::vp8
        : codec_value == "vp9"
            ? WebmCodec::vp9
            : throw std::invalid_argument(
                  "webm: temporal codec must be 'vp8' or 'vp9'");
    if (!(quality >= 0.0f && quality <= 100.0f))
        throw std::invalid_argument("webm: quality must be in 0..100");
    if (threads < 0 || threads > 8)
        throw std::invalid_argument("webm: threads must be in 0..8");
    if (speed < 0 || speed > 8)
        throw std::invalid_argument("webm: speed must be in 0..8");
    if (keyframe_interval < 2 || keyframe_interval > 32768)
        throw std::invalid_argument(
            "webm: temporal keyframe_interval must be in 2..32768");
    const unsigned int lane_count = threads == 0
        ? static_cast<unsigned int>(std::min<size_t>(
              8, std::max<unsigned int>(
                     1, std::thread::hardware_concurrency())))
        : static_cast<unsigned int>(threads);
    if (sequence.storage_mode == "yuv_planar" &&
        codec == WebmCodec::vp8 && sequence.matrix != "bt601")
        throw std::invalid_argument(
            "webm: VP8 temporal writer requires the bt601 matrix");
    for (int64_t value : sequence.durations_ns) {
        const uint64_t milliseconds = static_cast<uint64_t>(
            value / static_cast<int64_t>(kTimestampScaleNs));
        if (milliseconds > std::numeric_limits<unsigned long>::max())
            throw std::invalid_argument(
                "webm: frame duration exceeds the libvpx API limit");
    }

    vpx_codec_enc_cfg_t config{};
    if (vpx_codec_enc_config_default(
            encoder_interface(codec), &config, 0) != VPX_CODEC_OK)
        throw std::runtime_error(
            "webm: libvpx has no default encoder configuration");
    config.g_profile = 0;
    config.g_w = static_cast<unsigned int>(sequence.width);
    config.g_h = static_cast<unsigned int>(sequence.height);
    config.g_bit_depth = VPX_BITS_8;
    config.g_input_bit_depth = 8;
    config.g_timebase.num = 1;
    config.g_timebase.den = 1000;
    config.g_threads = lane_count;
    config.g_lag_in_frames = 0;
    config.g_pass = VPX_RC_ONE_PASS;
    config.rc_end_usage = VPX_CQ;
    config.rc_min_quantizer = 0;
    config.rc_max_quantizer = 63;
    const uint64_t raw_kbps =
        (sequence.width * sequence.height * uint64_t{12} * sequence.n +
         duration_ms - 1) / duration_ms;
    config.rc_target_bitrate = static_cast<unsigned int>(std::min<uint64_t>(
        std::numeric_limits<unsigned int>::max(),
        std::max<uint64_t>(64, raw_kbps)));
    config.rc_dropframe_thresh = 0;
    config.kf_mode = VPX_KF_AUTO;
    config.kf_min_dist = static_cast<unsigned int>(keyframe_interval);
    config.kf_max_dist = static_cast<unsigned int>(keyframe_interval);

    const std::string encoded_matrix =
        sequence.storage_mode == "packed" ? "bt601" : sequence.matrix;
    const std::string encoded_range =
        sequence.storage_mode == "packed" ? "limited" : sequence.color_range;
    const vpx_color_space_t encoded_color_space =
        vpx_color_space(encoded_matrix);
    const vpx_color_range_t encoded_color_range =
        encoded_range == "full" ? VPX_CR_FULL_RANGE : VPX_CR_STUDIO_RANGE;

    VpxCodecGuard encoder;
    if (vpx_codec_enc_init(
            &encoder.value, encoder_interface(codec), &config, 0) !=
        VPX_CODEC_OK)
        throw std::invalid_argument(
            vpx_failure(encoder.value, "encoder initialization"));
    encoder.initialized = true;
    const int quantizer = static_cast<int>(std::lround(
        (100.0f - quality) * 63.0f / 100.0f));
    if (vpx_codec_control(
            &encoder.value, VP8E_SET_CPUUSED, speed) != VPX_CODEC_OK ||
        vpx_codec_control(
            &encoder.value, VP8E_SET_CQ_LEVEL, quantizer) != VPX_CODEC_OK)
        throw std::invalid_argument(
            vpx_failure(encoder.value, "quality configuration"));
    if (codec == WebmCodec::vp9 &&
        (vpx_codec_control(
             &encoder.value, VP9E_SET_COLOR_SPACE,
             static_cast<int>(encoded_color_space)) != VPX_CODEC_OK ||
         vpx_codec_control(
             &encoder.value, VP9E_SET_COLOR_RANGE,
             static_cast<int>(encoded_color_range)) != VPX_CODEC_OK))
        throw std::invalid_argument(
            vpx_failure(encoder.value, "VP9 color configuration"));
    if (codec == WebmCodec::vp9 && lane_count > 1 &&
        vpx_codec_control(
            &encoder.value, VP9E_SET_ROW_MT, 1u) != VPX_CODEC_OK)
        throw std::invalid_argument(
            vpx_failure(encoder.value, "VP9 row threading configuration"));

    ChunkedOutput output("webm");
    size_t packet_index = 0;
    {
        nb::gil_scoped_release release;
        output.write(make_header(
            sequence.width, sequence.height, duration_ms, codec,
            encoded_matrix, encoded_range));
        const size_t y_size = sequence.width * sequence.height;
        const size_t c_size =
            ((sequence.width + 1) / 2) * ((sequence.height + 1) / 2);
        const size_t rgb_size = y_size * 3;
        for (size_t index = 0; index < sequence.n; ++index) {
            vpx_image_t image{};
            WebPPicture converted;
            PictureGuard converted_guard;
            if (sequence.storage_mode == "packed") {
                if (!WebPPictureInit(&converted))
                    throw std::runtime_error(
                        "webm: RGB conversion initialization failed");
                converted_guard.value = &converted;
                converted.use_argb = 0;
                converted.width = static_cast<int>(sequence.width);
                converted.height = static_cast<int>(sequence.height);
                if (!WebPPictureImportRGB(
                        &converted,
                        sequence.pixels_u8.data() + index * rgb_size,
                        static_cast<int>(sequence.width * 3))) {
                    throw std::invalid_argument(
                        "webm: RGB-to-YUV conversion failed");
                }
                assign_vpx_image(
                    image, sequence.width, sequence.height,
                    converted.y, converted.u, converted.v,
                    converted.y_stride, converted.uv_stride,
                    VPX_CS_BT_601, VPX_CR_STUDIO_RANGE);
            } else {
                assign_vpx_image(
                    image, sequence.width, sequence.height,
                    const_cast<uint8_t *>(
                        sequence.y.data() + index * y_size),
                    const_cast<uint8_t *>(
                        sequence.u.data() + index * c_size),
                    const_cast<uint8_t *>(
                        sequence.v.data() + index * c_size),
                    static_cast<int>(sequence.width),
                    static_cast<int>((sequence.width + 1) / 2),
                    encoded_color_space, encoded_color_range);
            }
            const vpx_codec_pts_t timestamp = static_cast<vpx_codec_pts_t>(
                sequence.timestamps_ns[index] /
                static_cast<int64_t>(kTimestampScaleNs));
            const unsigned long duration = static_cast<unsigned long>(
                sequence.durations_ns[index] /
                static_cast<int64_t>(kTimestampScaleNs));
            const vpx_codec_err_t status = vpx_codec_encode(
                &encoder.value, &image, timestamp, duration, 0,
                VPX_DL_REALTIME);
            if (status != VPX_CODEC_OK)
                throw std::invalid_argument(
                    vpx_failure(encoder.value, "frame encode"));
            drain_vpx_packets(
                encoder.value, codec, sequence, output, packet_index);
        }
        for (size_t flush = 0; flush < 16; ++flush) {
            const size_t before = packet_index;
            if (vpx_codec_encode(
                    &encoder.value, nullptr, 0, 0, 0,
                    VPX_DL_REALTIME) != VPX_CODEC_OK)
                throw std::runtime_error(
                    vpx_failure(encoder.value, "encoder flush"));
            drain_vpx_packets(
                encoder.value, codec, sequence, output, packet_index);
            if (packet_index == before) break;
        }
        if (packet_index != sequence.n)
            throw std::runtime_error(
                "webm: temporal encoder did not emit exactly one visible packet per frame");
    }
    return output.finish();
}

nb::bytes write_webm(
    const ImageSequence &sequence, float quality,
    bool threads, int method) {
    const uint64_t duration_ms = validate_writer_input(sequence);
    if (!(quality >= 0.0f && quality <= 100.0f))
        throw std::invalid_argument("webm: quality must be in 0..100");
    if (method < 0 || method > 6)
        throw std::invalid_argument("webm: encoder method must be in 0..6");

    WebPConfig config;
    if (!WebPConfigInit(&config))
        throw std::invalid_argument(
            "webm: VP8 encoder ABI initialization failed");
    config.lossless = 0;
    config.quality = quality;
    config.method = method;
    config.thread_level = threads ? 1 : 0;
    if (!WebPValidateConfig(&config))
        throw std::invalid_argument("webm: invalid VP8 encoder configuration");

    const std::string header =
        make_header(sequence.width, sequence.height, duration_ms);
    const size_t frame_samples = sequence.width * sequence.height * 3;
    if (active_file_sink) {
        emit_file_chunk(header.data(), header.size());
        for (size_t index = 0; index < sequence.n; ++index) {
            std::string cluster;
            {
                nb::gil_scoped_release release;
                const std::string packet = encode_vp8_frame(
                    sequence.pixels_u8.data() + index * frame_samples,
                    sequence.width, sequence.height, config);
                cluster = make_cluster(
                    static_cast<uint64_t>(
                        sequence.timestamps_ns[index] /
                        static_cast<int64_t>(kTimestampScaleNs)),
                    static_cast<uint64_t>(
                        sequence.durations_ns[index] /
                        static_cast<int64_t>(kTimestampScaleNs)),
                    packet);
            }
            emit_file_chunk(cluster.data(), cluster.size());
        }
        return nb::bytes("", 0);
    }

    std::string output = header;
    {
        nb::gil_scoped_release release;
        for (size_t index = 0; index < sequence.n; ++index) {
            const std::string packet = encode_vp8_frame(
                sequence.pixels_u8.data() + index * frame_samples,
                sequence.width, sequence.height, config);
            output += make_cluster(
                static_cast<uint64_t>(
                    sequence.timestamps_ns[index] /
                    static_cast<int64_t>(kTimestampScaleNs)),
                static_cast<uint64_t>(
                    sequence.durations_ns[index] /
                    static_cast<int64_t>(kTimestampScaleNs)),
                packet);
        }
    }
    return emit_bytes(output.data(), output.size());
}

}  // namespace

void register_webm(nb::module_ &module) {
    module.def(
        "read_webm", &read_webm, "data"_a,
        "Decode bounded video-only WebM VP8/VP9: legacy independent VP8 "
        "frames remain packed RGB, temporal streams return exact planar "
        "8-bit 4:2:0 storage.");
    module.def(
        "read_webm_frames", &read_webm_frames,
        "data"_a, "start"_a, "stop"_a,
        "Decode one nonempty half-open frame range from bounded WebM VP8/VP9, "
        "starting internally at the required preceding keyframe.");
    module.def(
        "write_webm", &write_webm,
        "sequence"_a, "quality"_a = 90.0f,
        "_threads"_a = true, "_method"_a = 4,
        "Encode packed uint8 sRGB frames as a video-only WebM/V_VP8 stream "
        "whose frames are independently decodable keyframes.");
    module.def(
        "write_webm_temporal", &write_webm_temporal,
        "sequence"_a, "codec"_a = "vp9", "quality"_a = 82.0f,
        "threads"_a = 0, "speed"_a = 6,
        "keyframe_interval"_a = 120,
        "Encode packed RGB or explicit planar 4:2:0 frames with direct "
        "multithreaded libvpx VP8/VP9 temporal compression.");
    module.def(
        "_inspect_webm", &inspect_webm, "data"_a,
        "Validate bounded WebM VP8/VP9 metadata and frame tables without "
        "decoding pixels.");
}
