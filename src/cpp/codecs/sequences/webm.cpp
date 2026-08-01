// codecs/sequences/webm.cpp -- bounded WebM/VP8 all-keyframe video I/O.
//
// SceneIO owns the EBML/WebM container adapter and uses the repository-pinned
// libwebp VP8 implementation for frame compression and decompression. The
// supported profile is deliberately explicit: one progressive video track,
// V_VP8, packed uint8 RGB, full-canvas all-keyframes, no lacing, alpha, audio,
// subtitles, attachments, or inter-frame prediction. Timing is represented on
// WebM's conventional one-millisecond TimestampScale without rounding.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "records/image_sequence.hpp"
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
    WebPPicture *value;
    ~PictureGuard() { WebPPictureFree(value); }
};

struct MemoryWriterGuard {
    WebPMemoryWriter *value;
    ~MemoryWriterGuard() { WebPMemoryWriterClear(value); }
};

struct DecodedGuard {
    uint8_t *value = nullptr;
    ~DecodedGuard() { WebPFree(value); }
};

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
};

TrackMetadata parse_video(const Element &video, uint64_t track_number) {
    Cursor cursor(video.data, video.size);
    bool interlace_seen = false;
    bool width_seen = false;
    bool height_seen = false;
    bool stereo_seen = false;
    bool alpha_seen = false;
    uint64_t width = 0;
    uint64_t height = 0;
    uint64_t display_width = 0;
    uint64_t display_height = 0;
    bool display_width_seen = false;
    bool display_height_seen = false;
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
    return {
        track_number, static_cast<size_t>(width), static_cast<size_t>(height), 0};
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
                    if (element_string(element, "CodecID") != "V_VP8")
                        throw std::invalid_argument(
                            "webm: profile supports only V_VP8");
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
};

struct ParsedWebm {
    size_t width = 0;
    size_t height = 0;
    std::vector<FramePacket> frames;
    uint64_t duration_ms = 0;
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

FramePacket parse_block_group(
    const Element &group, uint64_t cluster_timestamp,
    const TrackMetadata &track) {
    Cursor cursor(group.data, group.size);
    bool block_seen = false;
    bool duration_seen = false;
    bool reference_seen = false;
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
                        "webm: referenced frames are outside the all-keyframe profile");
                break;
            case kReferenceBlock:
                reference_seen = true;
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
    if (reference_seen)
        throw std::invalid_argument(
            "webm: inter-frame prediction is outside the supported profile");
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
    validate_vp8_keyframe(
        payload, payload_size, track.width, track.height);
    return {
        payload, payload_size, static_cast<uint64_t>(signed_timestamp), duration};
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
    if (flags != 0x80)
        throw std::invalid_argument(
            "webm: SimpleBlock must be an independently decodable, visible keyframe without lacing");
    if (cluster_timestamp >
        static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
        throw std::invalid_argument("webm: frame timestamp exceeds int64");
    const int64_t signed_timestamp =
        static_cast<int64_t>(cluster_timestamp) + relative;
    if (signed_timestamp < 0)
        throw std::invalid_argument("webm: negative frame timestamp");
    const uint8_t *payload = block.data + position;
    const size_t payload_size = block.size - position;
    validate_vp8_keyframe(
        payload, payload_size, track.width, track.height);
    return {
        payload, payload_size, static_cast<uint64_t>(signed_timestamp), 0};
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
        sequence.storage_mode = "packed";
        sequence.n = stop - start;
        sequence.height = parsed.height;
        sequence.width = parsed.width;
        sequence.channels = 3;
        sequence.frame_dtype = "uint8";
        sequence.color_space = "srgb";
        sequence.alpha_mode = "none";
        sequence.interlace = "progressive";
        sequence.maxval = 255;
        const size_t frame_samples =
            parsed.height * parsed.width * sequence.channels;
        sequence.pixels_u8.resize(sequence.n * frame_samples);
        sequence.timestamps_ns.reserve(sequence.n);
        sequence.durations_ns.reserve(sequence.n);
        for (size_t index = start; index < stop; ++index) {
            const FramePacket &frame = parsed.frames[index];
            int width = 0;
            int height = 0;
            DecodedGuard decoded{
                WebPDecodeRGB(frame.data, frame.size, &width, &height)};
            if (!decoded.value ||
                width != static_cast<int>(parsed.width) ||
                height != static_cast<int>(parsed.height))
                throw std::invalid_argument("webm: VP8 frame decode failed");
            std::memcpy(
                sequence.pixels_u8.data() +
                    (index - start) * frame_samples,
                decoded.value, frame_samples);
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
    size_t width, size_t height, uint64_t duration_ms) {
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

    std::string entry;
    append_uint(entry, kTrackNumber, 1);
    append_uint(entry, kTrackUid, 1);
    append_uint(entry, kTrackType, 1);
    append_uint(entry, kFlagEnabled, 1);
    append_uint(entry, kFlagDefault, 1);
    append_uint(entry, kFlagForced, 0);
    append_uint(entry, kFlagLacing, 0);
    append_text(entry, kCodecId, "V_VP8");
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
    const std::string &packet) {
    std::string block;
    block.push_back(static_cast<char>(0x81));
    block.push_back(0);
    block.push_back(0);
    block.push_back(0);
    block.append(packet);
    std::string group;
    append_element(group, kBlock, block.data(), block.size());
    append_uint(group, kBlockDuration, duration_ms);
    std::string cluster;
    append_uint(cluster, kClusterTimestamp, timestamp_ms);
    append_master(cluster, kBlockGroup, group);
    std::string output;
    append_master(output, kCluster, cluster);
    return output;
}

uint64_t validate_writer_input(const ImageSequence &sequence) {
    validate_image_sequence(sequence, "webm write");
    if (sequence.storage_mode != "packed" ||
        sequence.frame_dtype != "uint8" || sequence.channels != 3)
        throw std::invalid_argument(
            "webm: writer requires packed uint8 RGB frames");
    if (sequence.color_space != "srgb" ||
        sequence.alpha_mode != "none" || sequence.maxval != 255)
        throw std::invalid_argument(
            "webm: writer requires full-range sRGB without alpha");
    if (sequence.interlace != "progressive")
        throw std::invalid_argument(
            "webm: writer requires progressive frames");
    if (sequence.n == 0 || sequence.width == 0 || sequence.height == 0 ||
        sequence.width > 16383 || sequence.height > 16383)
        throw std::invalid_argument(
            "webm: writer needs nonempty frames within the VP8 axis limit");
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
    result["color_space"] = "srgb";
    result["alpha_mode"] = "none";
    result["codec"] = "vp8";
    result["profile"] = "all_keyframe";
    result["duration_ns"] = parsed.duration_ms * kTimestampScaleNs;
    return result;
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
        "Decode the bounded video-only WebM/V_VP8 all-keyframe profile into "
        "packed uint8 RGB frames with exact millisecond timing.");
    module.def(
        "read_webm_frames", &read_webm_frames,
        "data"_a, "start"_a, "stop"_a,
        "Decode one nonempty half-open frame range from the bounded WebM/VP8 "
        "all-keyframe profile.");
    module.def(
        "write_webm", &write_webm,
        "sequence"_a, "quality"_a = 90.0f,
        "_threads"_a = true, "_method"_a = 4,
        "Encode packed uint8 sRGB frames as a video-only WebM/V_VP8 stream "
        "whose frames are independently decodable keyframes.");
    module.def(
        "_inspect_webm", &inspect_webm, "data"_a,
        "Validate bounded WebM/VP8 metadata and frame tables without decoding "
        "pixels.");
}
