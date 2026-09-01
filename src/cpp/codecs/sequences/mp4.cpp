// codecs/sequences/mp4.cpp -- bounded read-only ISO BMFF AV1 video I/O.
//
// SceneIO parses the classic (non-fragmented) MP4 sample tables directly and
// delegates AV1 decoding to the repository-pinned libaom build. This is the
// same native profile exposed by colmap_mod: one selected visual AV1 track in
// .mp4/.m4v/.mov, including 8/10/12-bit sources. High-bit-depth decoder planes
// are deterministically normalized to the canonical uint8 ImageSequence YUV
// representation; the encoded bit depth remains visible to inspection.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <numeric>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <aom/aom_decoder.h>
#include <aom/aomdx.h>
#include <nanobind/stl/string.h>

#include "codecs/sequences/av1_obu.hpp"
#include "codecs/sequences/video_frame.hpp"
#include "records/image_sequence.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kMp4PixelCap = 250000000;
constexpr uint64_t kMp4SampleCap = 1000000000;
constexpr size_t kMp4FrameCap = 1000000;

struct Box {
    std::string type;
    uint64_t offset = 0;
    uint64_t data_offset = 0;
    uint64_t end = 0;
};

struct Sample {
    uint64_t offset = 0;
    uint64_t size = 0;
    int64_t decode_tick = 0;
    int64_t presentation_tick = 0;
    uint32_t duration_tick = 0;
    bool keyframe = false;
};

struct ParsedMp4 {
    size_t width = 0;
    size_t height = 0;
    uint32_t timescale = 0;
    int bit_depth = 8;
    bool monochrome = false;
    unsigned int x_chroma_shift = 1;
    unsigned int y_chroma_shift = 1;
    std::string chroma_subsampling = "420";
    std::string matrix = "unknown";
    std::string color_range = "limited";
    uint32_t pixel_aspect_numerator = 0;
    uint32_t pixel_aspect_denominator = 0;
    uint32_t frame_rate_numerator = 0;
    uint32_t frame_rate_denominator = 1;
    std::vector<uint8_t> decoder_config;
    std::vector<Sample> samples;
    std::vector<size_t> full_display_order;
    std::vector<size_t> display_order;
    std::vector<int64_t> timestamps_ns;
    std::vector<int64_t> durations_ns;
};

struct AomGuard {
    aom_codec_ctx_t value{};
    bool initialized = false;
    ~AomGuard() {
        if (initialized) aom_codec_destroy(&value);
    }
};

uint16_t read_u16(const uint8_t *data) {
    return static_cast<uint16_t>(
        (static_cast<uint16_t>(data[0]) << 8) | data[1]);
}

uint32_t read_u24(const uint8_t *data) {
    return (static_cast<uint32_t>(data[0]) << 16) |
           (static_cast<uint32_t>(data[1]) << 8) | data[2];
}

uint32_t read_u32(const uint8_t *data) {
    return (static_cast<uint32_t>(data[0]) << 24) |
           (static_cast<uint32_t>(data[1]) << 16) |
           (static_cast<uint32_t>(data[2]) << 8) | data[3];
}

uint64_t read_u64(const uint8_t *data) {
    return (static_cast<uint64_t>(read_u32(data)) << 32) |
           read_u32(data + 4);
}

int64_t read_i32(const uint8_t *data) {
    const uint32_t value = read_u32(data);
    return value <= static_cast<uint32_t>(
                        std::numeric_limits<int32_t>::max())
        ? static_cast<int64_t>(value)
        : static_cast<int64_t>(value) - (int64_t{1} << 32);
}

int64_t read_i64(const uint8_t *data) {
    const uint64_t value = read_u64(data);
    if (value <= static_cast<uint64_t>(
                     std::numeric_limits<int64_t>::max()))
        return static_cast<int64_t>(value);
    return -1 - static_cast<int64_t>(
                    std::numeric_limits<uint64_t>::max() - value);
}

Box read_box(const uint8_t *data, size_t size, uint64_t position,
             uint64_t parent_end) {
    if (!data || parent_end > size || position > parent_end ||
        parent_end - position < 8)
        throw std::invalid_argument("mp4: truncated box header");
    uint64_t box_size = read_u32(data + static_cast<size_t>(position));
    const std::string type(
        reinterpret_cast<const char *>(
            data + static_cast<size_t>(position + 4)),
        4);
    uint64_t header_size = 8;
    if (box_size == 1) {
        if (parent_end - position < 16)
            throw std::invalid_argument("mp4: truncated extended box header");
        box_size = read_u64(data + static_cast<size_t>(position + 8));
        header_size = 16;
    } else if (box_size == 0) {
        box_size = parent_end - position;
    }
    if (box_size < header_size || box_size > parent_end - position)
        throw std::invalid_argument("mp4: invalid box extent");
    return {type, position, position + header_size, position + box_size};
}

std::vector<Box> boxes(const uint8_t *data, size_t size,
                       uint64_t begin, uint64_t end) {
    std::vector<Box> result;
    uint64_t position = begin;
    while (position < end) {
        Box box = read_box(data, size, position, end);
        result.push_back(box);
        position = box.end;
    }
    if (position != end)
        throw std::invalid_argument("mp4: child boxes do not fill their parent");
    return result;
}

std::optional<Box> child(const uint8_t *data, size_t size,
                         const Box &parent, const char *type) {
    for (const Box &candidate :
         boxes(data, size, parent.data_offset, parent.end))
        if (candidate.type == type) return candidate;
    return std::nullopt;
}

std::vector<Box> children(const uint8_t *data, size_t size,
                          const Box &parent, const char *type) {
    std::vector<Box> result;
    for (const Box &candidate :
         boxes(data, size, parent.data_offset, parent.end))
        if (candidate.type == type) result.push_back(candidate);
    return result;
}

void require_full_box(const uint8_t *data, const Box &box,
                      uint8_t maximum_version = 0) {
    if (box.end - box.data_offset < 4 || data[box.data_offset] > maximum_version ||
        read_u24(data + static_cast<size_t>(box.data_offset + 1)) != 0)
        throw std::invalid_argument("mp4: unsupported full-box version or flags");
}

uint32_t parse_movie_timescale(const uint8_t *data, const Box &mvhd) {
    require_full_box(data, mvhd, 1);
    const uint8_t version = data[mvhd.data_offset];
    const uint64_t offset = mvhd.data_offset + (version == 0 ? 12 : 20);
    if (mvhd.end - offset < 4)
        throw std::invalid_argument("mp4: truncated movie header");
    const uint32_t value = read_u32(data + static_cast<size_t>(offset));
    if (value == 0) throw std::invalid_argument("mp4: zero movie timescale");
    return value;
}

struct MediaHeader {
    uint32_t timescale = 0;
    uint64_t duration = 0;
};

MediaHeader parse_media_header(const uint8_t *data, const Box &mdhd) {
    require_full_box(data, mdhd, 1);
    const uint8_t version = data[mdhd.data_offset];
    const uint64_t offset = mdhd.data_offset + (version == 0 ? 12 : 20);
    const size_t duration_width = version == 0 ? 4 : 8;
    if (mdhd.end - offset < 4 + duration_width)
        throw std::invalid_argument("mp4: truncated media header");
    MediaHeader result;
    result.timescale = read_u32(data + static_cast<size_t>(offset));
    result.duration = version == 0
        ? read_u32(data + static_cast<size_t>(offset + 4))
        : read_u64(data + static_cast<size_t>(offset + 4));
    if (result.timescale == 0)
        throw std::invalid_argument("mp4: zero media timescale");
    return result;
}

bool is_visual_handler(const uint8_t *data, const Box &hdlr) {
    require_full_box(data, hdlr);
    if (hdlr.end - hdlr.data_offset < 12)
        throw std::invalid_argument("mp4: truncated handler box");
    const uint8_t *value = data + static_cast<size_t>(hdlr.data_offset + 8);
    return std::memcmp(value, "vide", 4) == 0 ||
           std::memcmp(value, "pict", 4) == 0;
}

struct StscEntry {
    uint32_t first_chunk = 0;
    uint32_t samples_per_chunk = 0;
    uint32_t description_index = 0;
};

std::vector<StscEntry> parse_stsc(const uint8_t *data, const Box &stsc) {
    require_full_box(data, stsc);
    if (stsc.end - stsc.data_offset < 8)
        throw std::invalid_argument("mp4: truncated stsc box");
    const uint32_t count = read_u32(
        data + static_cast<size_t>(stsc.data_offset + 4));
    const uint64_t begin = stsc.data_offset + 8;
    if (count == 0 || count > (stsc.end - begin) / 12 ||
        begin + static_cast<uint64_t>(count) * 12 != stsc.end)
        throw std::invalid_argument("mp4: malformed stsc table");
    std::vector<StscEntry> result;
    result.reserve(count);
    for (uint32_t index = 0; index < count; ++index) {
        const uint8_t *entry = data + static_cast<size_t>(
            begin + static_cast<uint64_t>(index) * 12);
        StscEntry value{read_u32(entry), read_u32(entry + 4),
                        read_u32(entry + 8)};
        if (value.first_chunk == 0 || value.samples_per_chunk == 0 ||
            value.description_index == 0 ||
            (index == 0 && value.first_chunk != 1) ||
            (index != 0 && value.first_chunk <= result.back().first_chunk) ||
            (!result.empty() && value.description_index !=
                                    result.front().description_index))
            throw std::invalid_argument(
                "mp4: malformed or changing sample-to-chunk table");
        result.push_back(value);
    }
    return result;
}

std::vector<uint64_t> parse_sample_sizes(const uint8_t *data,
                                         const Box &stsz) {
    require_full_box(data, stsz);
    if (stsz.end - stsz.data_offset < 12)
        throw std::invalid_argument("mp4: truncated stsz box");
    const uint32_t uniform = read_u32(
        data + static_cast<size_t>(stsz.data_offset + 4));
    const uint32_t count = read_u32(
        data + static_cast<size_t>(stsz.data_offset + 8));
    if (count == 0 || count > kMp4FrameCap)
        throw std::invalid_argument("mp4: empty or excessive sample table");
    const uint64_t begin = stsz.data_offset + 12;
    if ((uniform != 0 && begin != stsz.end) ||
        (uniform == 0 &&
         (count > (stsz.end - begin) / 4 ||
          begin + static_cast<uint64_t>(count) * 4 != stsz.end)))
        throw std::invalid_argument("mp4: malformed sample-size table");
    std::vector<uint64_t> result(count, uniform);
    if (uniform == 0) {
        for (uint32_t index = 0; index < count; ++index)
            result[index] = read_u32(data + static_cast<size_t>(
                begin + static_cast<uint64_t>(index) * 4));
    }
    if (std::any_of(result.begin(), result.end(),
                    [](uint64_t value) { return value == 0; }))
        throw std::invalid_argument("mp4: empty video sample");
    return result;
}

std::vector<uint64_t> parse_chunk_offsets(const uint8_t *data,
                                          const Box &box) {
    require_full_box(data, box);
    if (box.end - box.data_offset < 8)
        throw std::invalid_argument("mp4: truncated chunk-offset box");
    const uint32_t count = read_u32(
        data + static_cast<size_t>(box.data_offset + 4));
    const uint64_t begin = box.data_offset + 8;
    const uint64_t width = box.type == "co64" ? 8 : 4;
    if (count == 0 || count > (box.end - begin) / width ||
        begin + static_cast<uint64_t>(count) * width != box.end)
        throw std::invalid_argument("mp4: malformed chunk-offset table");
    std::vector<uint64_t> result;
    result.reserve(count);
    for (uint32_t index = 0; index < count; ++index) {
        const uint8_t *entry = data + static_cast<size_t>(
            begin + static_cast<uint64_t>(index) * width);
        result.push_back(width == 8 ? read_u64(entry) : read_u32(entry));
    }
    return result;
}

struct TimeRun {
    uint32_t count = 0;
    int64_t value = 0;
};

std::vector<TimeRun> parse_time_runs(const uint8_t *data, const Box &box,
                                     size_t sample_count, bool composition) {
    require_full_box(data, box, composition ? 1 : 0);
    const uint8_t version = data[box.data_offset];
    if (box.end - box.data_offset < 8)
        throw std::invalid_argument("mp4: truncated timing table");
    const uint32_t count = read_u32(
        data + static_cast<size_t>(box.data_offset + 4));
    const uint64_t begin = box.data_offset + 8;
    if (count == 0 || count > (box.end - begin) / 8 ||
        begin + static_cast<uint64_t>(count) * 8 != box.end)
        throw std::invalid_argument("mp4: malformed timing table");
    std::vector<TimeRun> result;
    result.reserve(count);
    uint64_t total = 0;
    for (uint32_t index = 0; index < count; ++index) {
        const uint8_t *entry = data + static_cast<size_t>(
            begin + static_cast<uint64_t>(index) * 8);
        const uint32_t run_count = read_u32(entry);
        const int64_t value = composition && version == 1
            ? read_i32(entry + 4)
            : static_cast<int64_t>(read_u32(entry + 4));
        if (run_count == 0 || run_count > sample_count - total ||
            (!composition && value <= 0))
            throw std::invalid_argument("mp4: invalid timing run");
        total += run_count;
        result.push_back({run_count, value});
    }
    if (total != sample_count)
        throw std::invalid_argument("mp4: timing table has the wrong sample count");
    return result;
}

std::vector<bool> parse_sync_samples(const uint8_t *data,
                                     const std::optional<Box> &stss,
                                     size_t sample_count) {
    std::vector<bool> result(sample_count, !stss.has_value());
    if (!stss) return result;
    require_full_box(data, *stss);
    if (stss->end - stss->data_offset < 8)
        throw std::invalid_argument("mp4: truncated sync-sample box");
    const uint32_t count = read_u32(
        data + static_cast<size_t>(stss->data_offset + 4));
    const uint64_t begin = stss->data_offset + 8;
    if (count > (stss->end - begin) / 4 ||
        begin + static_cast<uint64_t>(count) * 4 != stss->end)
        throw std::invalid_argument("mp4: malformed sync-sample table");
    uint32_t previous = 0;
    for (uint32_t index = 0; index < count; ++index) {
        const uint32_t value = read_u32(data + static_cast<size_t>(
            begin + static_cast<uint64_t>(index) * 4));
        if (value == 0 || value > sample_count || value <= previous)
            throw std::invalid_argument("mp4: invalid sync-sample number");
        result[value - 1] = true;
        previous = value;
    }
    return result;
}

std::string matrix_name(uint16_t value) {
    if (value == 1) return "bt709";
    if (value == 5 || value == 6 || value == 7) return "bt601";
    if (value == 9 || value == 10) return "bt2020";
    return "unknown";
}

struct SampleDescription {
    size_t width = 0;
    size_t height = 0;
    int bit_depth = 8;
    bool monochrome = false;
    unsigned int x_shift = 1;
    unsigned int y_shift = 1;
    std::string matrix = "unknown";
    std::string range = "limited";
    bool color_box_present = false;
    uint32_t aspect_numerator = 0;
    uint32_t aspect_denominator = 0;
    std::vector<uint8_t> decoder_config;
};

SampleDescription parse_sample_description(
    const uint8_t *data, size_t size, const Box &stsd,
    uint32_t selected_index) {
    require_full_box(data, stsd);
    if (stsd.end - stsd.data_offset < 8)
        throw std::invalid_argument("mp4: truncated stsd box");
    const uint32_t count = read_u32(
        data + static_cast<size_t>(stsd.data_offset + 4));
    if (selected_index == 0 || selected_index > count)
        throw std::invalid_argument("mp4: invalid sample-description index");
    uint64_t position = stsd.data_offset + 8;
    for (uint32_t index = 1; index <= count; ++index) {
        const Box entry = read_box(data, size, position, stsd.end);
        position = entry.end;
        if (index != selected_index) continue;
        if (entry.type != "av01")
            throw std::invalid_argument("mp4: selected video track is not AV1");
        if (entry.end - entry.data_offset < 78)
            throw std::invalid_argument("mp4: truncated AV1 sample entry");
        SampleDescription result;
        result.width = read_u16(
            data + static_cast<size_t>(entry.data_offset + 24));
        result.height = read_u16(
            data + static_cast<size_t>(entry.data_offset + 26));
        if (result.width == 0 || result.height == 0 ||
            result.width * result.height > kMp4PixelCap)
            throw std::invalid_argument("mp4: invalid AV1 track dimensions");
        const uint64_t child_begin = entry.data_offset + 78;
        std::optional<Box> av1c;
        for (const Box &nested : boxes(data, size, child_begin, entry.end)) {
            if (nested.type == "av1C") {
                if (av1c) throw std::invalid_argument("mp4: duplicate av1C box");
                av1c = nested;
            } else if (nested.type == "colr") {
                if (nested.end - nested.data_offset >= 11 &&
                    std::memcmp(data + nested.data_offset, "nclx", 4) == 0) {
                    result.color_box_present = true;
                    result.matrix = matrix_name(read_u16(
                        data + static_cast<size_t>(nested.data_offset + 8)));
                    result.range = (data[nested.data_offset + 10] & 0x80)
                        ? "full" : "limited";
                }
            } else if (nested.type == "pasp") {
                if (nested.end - nested.data_offset != 8)
                    throw std::invalid_argument("mp4: malformed pasp box");
                result.aspect_numerator = read_u32(
                    data + static_cast<size_t>(nested.data_offset));
                result.aspect_denominator = read_u32(
                    data + static_cast<size_t>(nested.data_offset + 4));
                if (result.aspect_numerator == 0 ||
                    result.aspect_denominator == 0)
                    throw std::invalid_argument("mp4: zero pixel aspect ratio");
            }
        }
        if (!av1c || av1c->end - av1c->data_offset < 4)
            throw std::invalid_argument("mp4: missing or truncated av1C box");
        const uint8_t *configuration =
            data + static_cast<size_t>(av1c->data_offset);
        if (configuration[0] != 0x81 || (configuration[3] & 0xe0) != 0)
            throw std::invalid_argument(
                "mp4: malformed AV1CodecConfigurationRecord");
        const bool high = (configuration[2] & 0x40) != 0;
        const bool twelve = (configuration[2] & 0x20) != 0;
        result.bit_depth = twelve ? 12 : high ? 10 : 8;
        result.monochrome = (configuration[2] & 0x10) != 0;
        result.x_shift = (configuration[2] & 0x08) != 0 ? 1u : 0u;
        result.y_shift = (configuration[2] & 0x04) != 0 ? 1u : 0u;
        if (!result.x_shift && result.y_shift)
            throw std::invalid_argument("mp4: invalid AV1 chroma subsampling");
        result.decoder_config.assign(
            configuration + 4,
            data + static_cast<size_t>(av1c->end));
        if (!result.decoder_config.empty()) {
            av1::Av1WebmPacketInfo info;
            std::string error;
            if (!av1::ParseAv1WebmPacket(
                    result.decoder_config.data(),
                    result.decoder_config.size(), &info, &error) ||
                !info.has_sequence_header ||
                info.max_frame_width < static_cast<int>(result.width) ||
                info.max_frame_height < static_cast<int>(result.height))
                throw std::invalid_argument(
                    "mp4: av1C config OBUs do not describe the track");
            const std::string stream_matrix = matrix_name(info.color.matrix);
            const std::string stream_range =
                info.color.full_range ? "full" : "limited";
            if (result.matrix != "unknown" && stream_matrix != "unknown" &&
                result.matrix != stream_matrix)
                throw std::invalid_argument(
                    "mp4: AV1 and colr matrices disagree");
            if (result.color_box_present && result.range != stream_range)
                throw std::invalid_argument(
                    "mp4: AV1 and colr ranges disagree");
            if (result.matrix == "unknown") result.matrix = stream_matrix;
            if (!result.color_box_present) result.range = stream_range;
        }
        return result;
    }
    throw std::invalid_argument("mp4: missing selected sample description");
}

struct Edit {
    bool present = false;
    uint64_t leading_movie_ticks = 0;
    uint64_t media_segment_movie_ticks = 0;
    int64_t media_start_tick = 0;
};

struct WideProduct {
    uint64_t high = 0;
    uint64_t low = 0;
};

WideProduct multiply_wide(uint64_t left, uint64_t right) {
    const uint64_t left_low = static_cast<uint32_t>(left);
    const uint64_t left_high = left >> 32;
    const uint64_t right_low = static_cast<uint32_t>(right);
    const uint64_t right_high = right >> 32;
    const uint64_t word0 = left_low * right_low;
    const uint64_t partial = left_high * right_low + (word0 >> 32);
    const uint64_t word1 = partial & 0xffffffffull;
    const uint64_t word2 = partial >> 32;
    const uint64_t combined = left_low * right_high + word1;
    return {
        left_high * right_high + word2 + (combined >> 32),
        (combined << 32) | (word0 & 0xffffffffull),
    };
}

bool product_less(uint64_t left_a, uint64_t left_b,
                  uint64_t right_a, uint64_t right_b) {
    const WideProduct left = multiply_wide(left_a, left_b);
    const WideProduct right = multiply_wide(right_a, right_b);
    return left.high != right.high ? left.high < right.high
                                   : left.low < right.low;
}

Edit parse_edit(const uint8_t *data, size_t size, const Box &trak) {
    const std::optional<Box> edts = child(data, size, trak, "edts");
    if (!edts) return {};
    const std::optional<Box> elst = child(data, size, *edts, "elst");
    if (!elst) return {};
    require_full_box(data, *elst, 1);
    const uint8_t version = data[elst->data_offset];
    if (elst->end - elst->data_offset < 8)
        throw std::invalid_argument("mp4: truncated edit list");
    const uint32_t count = read_u32(
        data + static_cast<size_t>(elst->data_offset + 4));
    const uint64_t entry_size = version == 0 ? 12 : 20;
    const uint64_t begin = elst->data_offset + 8;
    if ((count != 1 && count != 2) ||
        begin + static_cast<uint64_t>(count) * entry_size != elst->end)
        throw std::invalid_argument("mp4: unsupported edit-list shape");
    struct Entry { uint64_t duration; int64_t media_time; };
    std::vector<Entry> entries;
    for (uint32_t index = 0; index < count; ++index) {
        const uint8_t *entry = data + static_cast<size_t>(
            begin + static_cast<uint64_t>(index) * entry_size);
        const uint64_t duration = version == 0 ? read_u32(entry) : read_u64(entry);
        const int64_t media_time = version == 0
            ? read_i32(entry + 4) : read_i64(entry + 8);
        const size_t rate_offset = version == 0 ? 8 : 16;
        if (duration == 0 || read_u16(entry + rate_offset) != 1 ||
            read_u16(entry + rate_offset + 2) != 0)
            throw std::invalid_argument("mp4: unsupported edit rate");
        entries.push_back({duration, media_time});
    }
    Edit result;
    size_t media_index = 0;
    if (entries.size() == 2) {
        if (entries[0].media_time != -1)
            throw std::invalid_argument("mp4: malformed leading empty edit");
        result.leading_movie_ticks = entries[0].duration;
        media_index = 1;
    }
    if (entries[media_index].media_time < 0)
        throw std::invalid_argument("mp4: edit has no media segment");
    result.present = true;
    result.media_segment_movie_ticks = entries[media_index].duration;
    result.media_start_tick = entries[media_index].media_time;
    return result;
}

bool in_mdat(uint64_t offset, uint64_t length,
             const std::vector<Box> &mdats) {
    for (const Box &mdat : mdats)
        if (offset >= mdat.data_offset && offset <= mdat.end &&
            length <= mdat.end - offset)
            return true;
    return false;
}

int64_t positive_ticks_to_ns(uint64_t ticks, uint32_t timescale,
                             const char *context) {
    const uint64_t whole = ticks / timescale;
    const uint64_t remainder = ticks % timescale;
    if (whole > static_cast<uint64_t>(
                    std::numeric_limits<int64_t>::max()) / 1000000000ull)
        throw std::invalid_argument(std::string("mp4: ") + context +
                                    " exceeds nanosecond range");
    uint64_t value = whole * 1000000000ull;
    const uint64_t fraction =
        (remainder * 1000000000ull + timescale / 2) / timescale;
    if (value > static_cast<uint64_t>(
                    std::numeric_limits<int64_t>::max()) - fraction)
        throw std::invalid_argument(std::string("mp4: ") + context +
                                    " exceeds nanosecond range");
    return static_cast<int64_t>(value + fraction);
}

int64_t ticks_to_ns(int64_t ticks, uint32_t timescale,
                    const char *context) {
    const bool negative = ticks < 0;
    const uint64_t magnitude = negative
        ? static_cast<uint64_t>(-(ticks + 1)) + 1
        : static_cast<uint64_t>(ticks);
    const int64_t value = positive_ticks_to_ns(
        magnitude, timescale, context);
    return negative ? -value : value;
}

std::optional<ParsedMp4> parse_track(
    const uint8_t *data, size_t size, const Box &trak,
    uint32_t movie_timescale, const std::vector<Box> &mdats) {
    const std::optional<Box> mdia = child(data, size, trak, "mdia");
    if (!mdia) return std::nullopt;
    const std::optional<Box> hdlr = child(data, size, *mdia, "hdlr");
    if (!hdlr || !is_visual_handler(data, *hdlr)) return std::nullopt;
    const std::optional<Box> mdhd = child(data, size, *mdia, "mdhd");
    const std::optional<Box> minf = child(data, size, *mdia, "minf");
    if (!mdhd || !minf)
        throw std::invalid_argument("mp4: incomplete visual track");
    const MediaHeader media = parse_media_header(data, *mdhd);
    const std::optional<Box> stbl = child(data, size, *minf, "stbl");
    if (!stbl) throw std::invalid_argument("mp4: missing sample table");
    const auto required = [&](const char *type) -> Box {
        const std::optional<Box> value = child(data, size, *stbl, type);
        if (!value)
            throw std::invalid_argument(
                std::string("mp4: missing ") + type + " table");
        return *value;
    };
    const Box stsd = required("stsd");
    const Box stsz = required("stsz");
    const Box stsc_box = required("stsc");
    const Box stts = required("stts");
    std::optional<Box> offset_box = child(data, size, *stbl, "stco");
    if (!offset_box) offset_box = child(data, size, *stbl, "co64");
    if (!offset_box)
        throw std::invalid_argument("mp4: missing chunk-offset table");

    const std::vector<uint64_t> sizes = parse_sample_sizes(data, stsz);
    const std::vector<StscEntry> stsc = parse_stsc(data, stsc_box);
    const std::vector<uint64_t> offsets =
        parse_chunk_offsets(data, *offset_box);
    const SampleDescription description = parse_sample_description(
        data, size, stsd, stsc.front().description_index);
    const std::vector<TimeRun> decoding =
        parse_time_runs(data, stts, sizes.size(), false);
    std::vector<TimeRun> composition;
    if (const std::optional<Box> ctts = child(data, size, *stbl, "ctts"))
        composition = parse_time_runs(data, *ctts, sizes.size(), true);
    else
        composition.push_back(
            {static_cast<uint32_t>(sizes.size()), 0});
    const std::vector<bool> sync = parse_sync_samples(
        data, child(data, size, *stbl, "stss"), sizes.size());

    ParsedMp4 result;
    result.width = description.width;
    result.height = description.height;
    result.timescale = media.timescale;
    result.bit_depth = description.bit_depth;
    result.monochrome = description.monochrome;
    result.x_chroma_shift = description.x_shift;
    result.y_chroma_shift = description.y_shift;
    result.chroma_subsampling = result.monochrome ? "mono"
        : result.x_chroma_shift == 0 ? "444"
        : result.y_chroma_shift == 0 ? "422" : "420";
    result.matrix = description.matrix;
    result.color_range = description.range;
    result.pixel_aspect_numerator = description.aspect_numerator;
    result.pixel_aspect_denominator = description.aspect_denominator;
    result.decoder_config = description.decoder_config;
    result.samples.resize(sizes.size());

    size_t sample_index = 0;
    size_t stsc_index = 0;
    for (size_t chunk = 1; chunk <= offsets.size() &&
                           sample_index < sizes.size(); ++chunk) {
        while (stsc_index + 1 < stsc.size() &&
               stsc[stsc_index + 1].first_chunk <= chunk)
            ++stsc_index;
        uint64_t sample_offset = offsets[chunk - 1];
        for (uint32_t within = 0;
             within < stsc[stsc_index].samples_per_chunk &&
             sample_index < sizes.size();
             ++within, ++sample_index) {
            if (!in_mdat(sample_offset, sizes[sample_index], mdats))
                throw std::invalid_argument(
                    "mp4: video sample lies outside mdat payloads");
            result.samples[sample_index].offset = sample_offset;
            result.samples[sample_index].size = sizes[sample_index];
            result.samples[sample_index].keyframe = sync[sample_index];
            if (sizes[sample_index] >
                std::numeric_limits<uint64_t>::max() - sample_offset)
                throw std::invalid_argument("mp4: sample range overflow");
            sample_offset += sizes[sample_index];
        }
    }
    if (sample_index != sizes.size())
        throw std::invalid_argument("mp4: chunk table omits video samples");

    size_t decode_run = 0;
    uint32_t decode_remaining = decoding[0].count;
    size_t composition_run = 0;
    uint32_t composition_remaining = composition[0].count;
    int64_t decode_tick = 0;
    for (size_t index = 0; index < result.samples.size(); ++index) {
        const int64_t delta = decoding[decode_run].value;
        const int64_t offset = composition[composition_run].value;
        if ((offset > 0 && decode_tick >
                std::numeric_limits<int64_t>::max() - offset) ||
            (offset < 0 && decode_tick <
                std::numeric_limits<int64_t>::min() - offset))
            throw std::invalid_argument("mp4: presentation timestamp overflow");
        Sample &sample = result.samples[index];
        sample.decode_tick = decode_tick;
        sample.presentation_tick = decode_tick + offset;
        sample.duration_tick = static_cast<uint32_t>(delta);
        if (decode_tick > std::numeric_limits<int64_t>::max() - delta)
            throw std::invalid_argument("mp4: decode timestamp overflow");
        decode_tick += delta;
        if (--decode_remaining == 0 && ++decode_run < decoding.size())
            decode_remaining = decoding[decode_run].count;
        if (--composition_remaining == 0 &&
            ++composition_run < composition.size())
            composition_remaining = composition[composition_run].count;
    }

    result.display_order.resize(result.samples.size());
    std::iota(result.display_order.begin(), result.display_order.end(), 0);
    std::stable_sort(
        result.display_order.begin(), result.display_order.end(),
        [&](size_t left, size_t right) {
            return result.samples[left].presentation_tick <
                   result.samples[right].presentation_tick;
        });
    for (size_t index = 1; index < result.display_order.size(); ++index)
        if (result.samples[result.display_order[index - 1]].presentation_tick >=
            result.samples[result.display_order[index]].presentation_tick)
            throw std::invalid_argument(
                "mp4: presentation timestamps must be unique");
    result.full_display_order = result.display_order;

    const Edit edit = parse_edit(data, size, trak);
    if (edit.present) {
        result.display_order.erase(
            std::remove_if(
                result.display_order.begin(), result.display_order.end(),
                [&](size_t index) {
                    const int64_t presentation =
                        result.samples[index].presentation_tick;
                    if (presentation < edit.media_start_tick) return true;
                    const uint64_t media_delta = static_cast<uint64_t>(
                        presentation - edit.media_start_tick);
                    return !product_less(
                        media_delta, movie_timescale,
                        edit.media_segment_movie_ticks, media.timescale);
                }),
            result.display_order.end());
    }
    if (result.display_order.empty())
        throw std::invalid_argument("mp4: edit list removes every frame");

    const int64_t base_tick = edit.present ? edit.media_start_tick : 0;
    const int64_t leading_ns = positive_ticks_to_ns(
        edit.leading_movie_ticks, movie_timescale, "leading edit");
    result.timestamps_ns.reserve(result.display_order.size());
    result.durations_ns.reserve(result.display_order.size());
    for (size_t index : result.display_order) {
        const int64_t relative =
            result.samples[index].presentation_tick - base_tick;
        const int64_t timestamp =
            leading_ns + ticks_to_ns(relative, media.timescale, "timestamp");
        if (!result.timestamps_ns.empty() &&
            timestamp <= result.timestamps_ns.back())
            throw std::invalid_argument(
                "mp4: projected nanosecond timestamps collide");
        result.timestamps_ns.push_back(timestamp);
    }
    for (size_t index = 0; index < result.display_order.size(); ++index) {
        int64_t duration = 0;
        if (index + 1 < result.display_order.size())
            duration = result.timestamps_ns[index + 1] -
                       result.timestamps_ns[index];
        else
            duration = ticks_to_ns(
                result.samples[result.display_order[index]].duration_tick,
                media.timescale, "frame duration");
        if (duration <= 0)
            throw std::invalid_argument(
                "mp4: frame duration is not representable in nanoseconds");
        result.durations_ns.push_back(duration);
    }

    bool constant_delta = true;
    const uint32_t first_delta = result.samples.front().duration_tick;
    for (const Sample &sample : result.samples)
        constant_delta = constant_delta &&
                         sample.duration_tick == first_delta;
    if (constant_delta) {
        const uint32_t divisor = std::gcd(media.timescale, first_delta);
        result.frame_rate_numerator = media.timescale / divisor;
        result.frame_rate_denominator = first_delta / divisor;
    }
    return result;
}

ParsedMp4 parse_mp4(const uint8_t *data, size_t size) {
    if (!data || size < 16)
        throw std::invalid_argument("mp4: input is too small");
    const std::vector<Box> top = boxes(data, size, 0, size);
    std::optional<Box> ftyp;
    std::optional<Box> moov;
    std::vector<Box> mdats;
    for (const Box &box : top) {
        if (box.type == "ftyp") {
            if (ftyp) throw std::invalid_argument("mp4: duplicate ftyp box");
            ftyp = box;
        } else if (box.type == "moov") {
            if (moov) throw std::invalid_argument("mp4: duplicate moov box");
            moov = box;
        } else if (box.type == "mdat") {
            mdats.push_back(box);
        } else if (box.type == "moof") {
            throw std::invalid_argument(
                "mp4: fragmented movies are outside the native profile");
        }
    }
    if (!ftyp || ftyp->end - ftyp->data_offset < 8 || !moov || mdats.empty())
        throw std::invalid_argument("mp4: missing ftyp, moov, or mdat box");
    const std::optional<Box> mvhd = child(data, size, *moov, "mvhd");
    if (!mvhd) throw std::invalid_argument("mp4: missing movie header");
    const uint32_t movie_timescale = parse_movie_timescale(data, *mvhd);
    std::optional<ParsedMp4> best;
    for (const Box &trak : children(data, size, *moov, "trak")) {
        try {
            std::optional<ParsedMp4> candidate = parse_track(
                data, size, trak, movie_timescale, mdats);
            if (candidate &&
                (!best || candidate->samples.size() > best->samples.size()))
                best = std::move(candidate);
        } catch (const std::invalid_argument &error) {
            const std::string message = error.what();
            if (message == "mp4: selected video track is not AV1") continue;
            throw;
        }
    }
    if (!best)
        throw std::invalid_argument("mp4: no supported AV1 visual track");
    const uint64_t pixels = best->width * best->height;
    const uint64_t samples_per_frame = best->monochrome
        ? pixels
        : pixels + 2 *
            (((best->width + (uint64_t{1} << best->x_chroma_shift) - 1) >>
              best->x_chroma_shift) *
             ((best->height + (uint64_t{1} << best->y_chroma_shift) - 1) >>
              best->y_chroma_shift));
    if (best->display_order.size() > kMp4SampleCap / samples_per_frame)
        throw std::invalid_argument(
            "mp4: decoded sequence exceeds the supported sample limit");
    return std::move(*best);
}

std::string aom_failure(const aom_codec_ctx_t &context,
                        const char *operation) {
    std::string result = std::string("mp4: libaom ") + operation + " failed";
    if (const char *message = aom_codec_error(&context)) {
        result += ": ";
        result += message;
    }
    if (const char *detail = aom_codec_error_detail(&context)) {
        result += " (";
        result += detail;
        result += ")";
    }
    return result;
}

void validate_decoded_image(const ParsedMp4 &parsed,
                            const aom_image_t &image) {
    const bool high = (image.fmt & AOM_IMG_FMT_HIGHBITDEPTH) != 0;
    const aom_img_fmt_t base = static_cast<aom_img_fmt_t>(
        image.fmt & ~AOM_IMG_FMT_HIGHBITDEPTH);
    const aom_img_fmt_t expected = parsed.monochrome ||
            (parsed.x_chroma_shift == 1 && parsed.y_chroma_shift == 1)
        ? AOM_IMG_FMT_I420
        : parsed.x_chroma_shift == 1
            ? AOM_IMG_FMT_I422 : AOM_IMG_FMT_I444;
    if (base != expected || image.bit_depth != parsed.bit_depth ||
        high != (parsed.bit_depth > 8) ||
        image.d_w != parsed.width || image.d_h != parsed.height ||
        image.x_chroma_shift != parsed.x_chroma_shift ||
        image.y_chroma_shift != parsed.y_chroma_shift)
        throw std::invalid_argument(
            "mp4: decoded AV1 layout disagrees with av1C and track dimensions");
    const std::string decoded_matrix =
        sio::video::aom_matrix_name(image.mc, "mp4");
    const std::string decoded_range =
        image.range == AOM_CR_FULL_RANGE ? "full" : "limited";
    if (parsed.matrix != "unknown" && decoded_matrix != "unknown" &&
        parsed.matrix != decoded_matrix)
        throw std::invalid_argument(
            "mp4: codec and container color matrices disagree");
    if (parsed.color_range != decoded_range)
        throw std::invalid_argument(
            "mp4: codec and container color ranges disagree");
}

ImageSequence decode_mp4(nb::handle source, bool partial,
                         size_t start, size_t stop) {
    ByteView input(source);
    ImageSequence sequence;
    {
        nb::gil_scoped_release release;
        const ParsedMp4 parsed = parse_mp4(input.data(), input.size());
        const size_t total = parsed.display_order.size();
        if (!partial) {
            start = 0;
            stop = total;
        } else {
            checked_half_open_range(start, stop, total, "mp4 frame range");
        }
        sequence.n = stop - start;
        sequence.height = parsed.height;
        sequence.width = parsed.width;
        sequence.channels = parsed.monochrome ? 1 : 3;
        sequence.storage_mode = "yuv_planar";
        sequence.frame_dtype = "uint8";
        sequence.color_space = parsed.monochrome ? "gray" : "ycbcr";
        sequence.alpha_mode = "none";
        sequence.chroma_subsampling = parsed.chroma_subsampling;
        sequence.chroma_siting = "unspecified";
        sequence.color_range = parsed.color_range;
        sequence.matrix = parsed.monochrome ? "unknown" : parsed.matrix;
        sequence.interlace = "progressive";
        sequence.maxval = 255;
        sequence.frame_rate_numerator = parsed.frame_rate_numerator;
        sequence.frame_rate_denominator = parsed.frame_rate_denominator;
        sequence.pixel_aspect_numerator = parsed.pixel_aspect_numerator;
        sequence.pixel_aspect_denominator = parsed.pixel_aspect_denominator;
        sequence.timestamps_ns.assign(
            parsed.timestamps_ns.begin() + static_cast<ptrdiff_t>(start),
            parsed.timestamps_ns.begin() + static_cast<ptrdiff_t>(stop));
        sequence.durations_ns.assign(
            parsed.durations_ns.begin() + static_cast<ptrdiff_t>(start),
            parsed.durations_ns.begin() + static_cast<ptrdiff_t>(stop));

        const size_t y_size = parsed.width * parsed.height;
        sequence.y.resize(sequence.n * y_size);
        if (!parsed.monochrome) {
            sequence.chroma_width =
                (parsed.width + (size_t{1} << parsed.x_chroma_shift) - 1) >>
                parsed.x_chroma_shift;
            sequence.chroma_height =
                (parsed.height + (size_t{1} << parsed.y_chroma_shift) - 1) >>
                parsed.y_chroma_shift;
            const size_t chroma_size =
                sequence.chroma_width * sequence.chroma_height;
            sequence.u.resize(sequence.n * chroma_size);
            sequence.v.resize(sequence.n * chroma_size);
        }

        constexpr size_t kNotSelected = std::numeric_limits<size_t>::max();
        std::vector<size_t> selected_output(
            parsed.samples.size(), kNotSelected);
        for (size_t output = start; output < stop; ++output)
            selected_output[parsed.display_order[output]] = output - start;

        aom_codec_dec_cfg_t config{};
        config.threads = static_cast<unsigned int>(std::min<size_t>(
            8, std::max<unsigned int>(
                   1, std::thread::hardware_concurrency())));
        config.w = static_cast<unsigned int>(parsed.width);
        config.h = static_cast<unsigned int>(parsed.height);
        config.allow_lowbitdepth = 1;
        AomGuard decoder;
        if (aom_codec_dec_init(
                &decoder.value, aom_codec_av1_dx(), &config, 0) !=
            AOM_CODEC_OK)
            throw std::invalid_argument(
                aom_failure(decoder.value, "decoder initialization"));
        decoder.initialized = true;

        size_t display_index = 0;
        size_t copied = 0;
        auto drain = [&]() {
            aom_codec_iter_t iterator = nullptr;
            while (aom_image_t *image =
                       aom_codec_get_frame(&decoder.value, &iterator)) {
                if (display_index >= parsed.full_display_order.size())
                    throw std::invalid_argument(
                        "mp4: decoder produced too many visible frames");
                validate_decoded_image(parsed, *image);
                const size_t sample_index =
                    parsed.full_display_order[display_index];
                if (image->user_priv != const_cast<Sample *>(
                        &parsed.samples[sample_index]))
                    throw std::invalid_argument(
                        "mp4: codec display order disagrees with the sample timeline");
                const size_t output = selected_output[sample_index];
                if (output != kNotSelected) {
                    const bool high =
                        (image->fmt & AOM_IMG_FMT_HIGHBITDEPTH) != 0;
                    sio::video::copy_decoded_plane_to_u8(
                        sequence.y, output, parsed.height, parsed.width,
                        image->planes[AOM_PLANE_Y],
                        image->stride[AOM_PLANE_Y], parsed.bit_depth, high,
                        "mp4: decoder returned inconsistent plane storage");
                    if (!parsed.monochrome) {
                        sio::video::copy_decoded_plane_to_u8(
                            sequence.u, output,
                            sequence.chroma_height, sequence.chroma_width,
                            image->planes[AOM_PLANE_U],
                            image->stride[AOM_PLANE_U], parsed.bit_depth, high,
                            "mp4: decoder returned inconsistent plane storage");
                        sio::video::copy_decoded_plane_to_u8(
                            sequence.v, output,
                            sequence.chroma_height, sequence.chroma_width,
                            image->planes[AOM_PLANE_V],
                            image->stride[AOM_PLANE_V], parsed.bit_depth, high,
                            "mp4: decoder returned inconsistent plane storage");
                    }
                    ++copied;
                }
                ++display_index;
            }
        };
        std::vector<uint8_t> first_packet;
        for (size_t index = 0; index < parsed.samples.size(); ++index) {
            const Sample &sample = parsed.samples[index];
            const uint8_t *packet = input.data() + sample.offset;
            size_t packet_size = static_cast<size_t>(sample.size);
            av1::Av1WebmPacketInfo first_info;
            std::string first_error;
            const bool first_has_sequence_header = index == 0 &&
                av1::ParseAv1WebmPacket(
                    packet, packet_size, &first_info, &first_error) &&
                first_info.has_sequence_header;
            if (index == 0 && !parsed.decoder_config.empty() &&
                !first_has_sequence_header) {
                if (parsed.decoder_config.size() >
                    std::numeric_limits<size_t>::max() - packet_size)
                    throw std::invalid_argument("mp4: first packet is too large");
                first_packet = parsed.decoder_config;
                first_packet.insert(
                    first_packet.end(), packet, packet + packet_size);
                packet = first_packet.data();
                packet_size = first_packet.size();
            }
            if (aom_codec_decode(
                    &decoder.value, packet, packet_size,
                    const_cast<Sample *>(&sample)) !=
                AOM_CODEC_OK)
                throw std::invalid_argument(
                    aom_failure(decoder.value, "frame decode"));
            drain();
        }
        if (aom_codec_decode(&decoder.value, nullptr, 0, nullptr) !=
            AOM_CODEC_OK)
            throw std::invalid_argument(
                aom_failure(decoder.value, "decoder flush"));
        drain();
        if (display_index != parsed.full_display_order.size() ||
            copied != sequence.n)
            throw std::invalid_argument(
                "mp4: AV1 sample table and decoded display count disagree");
        validate_image_sequence(sequence, "mp4 decoded sequence");
    }
    return sequence;
}

ImageSequence read_mp4(nb::handle source) {
    return decode_mp4(source, false, 0, 0);
}

ImageSequence read_mp4_frames(nb::handle source,
                              size_t start, size_t stop) {
    return decode_mp4(source, true, start, stop);
}

nb::dict inspect_mp4(nb::handle source) {
    ByteView input(source);
    ParsedMp4 parsed;
    {
        nb::gil_scoped_release release;
        parsed = parse_mp4(input.data(), input.size());
    }
    nb::dict result;
    result["width"] = parsed.width;
    result["height"] = parsed.height;
    result["frames"] = parsed.display_order.size();
    result["channels"] = parsed.monochrome ? 1 : 3;
    result["dtype"] = "uint8";
    result["source_bit_depth"] = parsed.bit_depth;
    result["color_space"] = parsed.monochrome ? "gray" : "ycbcr";
    result["color_range"] = parsed.color_range;
    result["matrix"] = parsed.monochrome ? "unknown" : parsed.matrix;
    result["alpha_mode"] = "none";
    result["storage_mode"] = "yuv_planar";
    result["chroma_subsampling"] = parsed.chroma_subsampling;
    result["codec"] = "av1";
    result["frame_rate_numerator"] = parsed.frame_rate_numerator;
    result["frame_rate_denominator"] = parsed.frame_rate_denominator;
    result["pixel_aspect_numerator"] = parsed.pixel_aspect_numerator;
    result["pixel_aspect_denominator"] = parsed.pixel_aspect_denominator;
    result["duration_ns"] =
        parsed.timestamps_ns.back() + parsed.durations_ns.back() -
        parsed.timestamps_ns.front();
    result["timing_projection"] = "nearest_nanosecond";
    return result;
}

}  // namespace

void register_mp4(nanobind::module_ &module) {
    module.def(
        "read_mp4", &read_mp4, "data"_a,
        "Decode bounded classic ISO BMFF AV1 video into normalized uint8 planar storage.");
    module.def(
        "read_mp4_frames", &read_mp4_frames,
        "data"_a, "start"_a, "stop"_a,
        "Decode one nonempty half-open display-frame range from bounded AV1 MP4.");
    module.def(
        "_inspect_mp4", &inspect_mp4, "data"_a,
        "Validate AV1 MP4 metadata and sample tables without decoding pixels.");
}
