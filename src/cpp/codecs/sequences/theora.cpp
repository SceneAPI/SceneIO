// codecs/sequences/theora.cpp -- bounded Ogg/Theora planar-video I/O.
//
// SceneIO owns the Ogg container policy and calls the repository-pinned
// libogg/libtheora APIs directly. The accepted profile is one Theora logical
// stream, progressive 8-bit 4:2:0 Y'CbCr, fixed rational frame rate, optional
// pixel aspect, no user comments, audio, subtitles, chained streams, or
// implicit color conversion.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "ogg/ogg.h"
#include "records/image_sequence.hpp"
#include "theora/theoradec.h"
#include "theora/theoraenc.h"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kFeedChunk = 64 * 1024;
constexpr size_t kFrameCap = 1000000;
constexpr uint64_t kPixelCap = 250000000;
constexpr uint64_t kSampleCap = 1000000000;
constexpr uint32_t kAxisCap = 1048560;
constexpr int kSerial = 0x53494f54;  // "SIOT"

size_t checked_product(size_t left, size_t right, const char *what) {
    if (left != 0 && right > std::numeric_limits<size_t>::max() / left)
        throw std::length_error(
            std::string("theora: ") + what + " overflows size_t");
    return left * right;
}

void validate_sample_count(size_t frames, size_t height, size_t width) {
    const uint64_t pixels = static_cast<uint64_t>(height) * width;
    const uint64_t chroma =
        static_cast<uint64_t>((height + 1) / 2) * ((width + 1) / 2);
    const uint64_t per_frame = pixels + 2 * chroma;
    if (per_frame > kSampleCap || frames > kSampleCap / per_frame)
        throw std::invalid_argument(
            "theora: decoded sequence exceeds the supported sample limit");
}

struct SyncGuard {
    ogg_sync_state value{};
    SyncGuard() {
        if (ogg_sync_init(&value) != 0)
            throw std::runtime_error("theora: libogg sync initialization failed");
    }
    ~SyncGuard() { ogg_sync_clear(&value); }
};

struct StreamGuard {
    ogg_stream_state value{};
    bool initialized = false;
    ~StreamGuard() {
        if (initialized) ogg_stream_clear(&value);
    }
    void init(int serial) {
        if (initialized || ogg_stream_init(&value, serial) != 0)
            throw std::runtime_error("theora: libogg stream initialization failed");
        initialized = true;
    }
};

struct HeaderGuard {
    th_info info{};
    th_comment comment{};
    th_setup_info *setup = nullptr;
    th_dec_ctx *decoder = nullptr;
    HeaderGuard() {
        th_info_init(&info);
        th_comment_init(&comment);
    }
    ~HeaderGuard() {
        if (decoder) th_decode_free(decoder);
        if (setup) th_setup_free(setup);
        th_comment_clear(&comment);
        th_info_clear(&info);
    }
};

struct EncoderGuard {
    th_enc_ctx *value = nullptr;
    ~EncoderGuard() {
        if (value) th_encode_free(value);
    }
};

struct CommentGuard {
    th_comment value{};
    CommentGuard() { th_comment_init(&value); }
    ~CommentGuard() { th_comment_clear(&value); }
};

struct Metadata {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t chroma_width = 0;
    uint32_t chroma_height = 0;
    uint32_t fps_num = 0;
    uint32_t fps_den = 0;
    uint32_t aspect_num = 0;
    uint32_t aspect_den = 0;
    uint32_t pic_x = 0;
    uint32_t pic_y = 0;
    uint32_t frame_width = 0;
    uint32_t frame_height = 0;
    int keyframe_shift = 0;
    unsigned version_major = 0;
    unsigned version_minor = 0;
    unsigned version_subminor = 0;
    size_t frames = 0;
};

void validate_info(const th_info &info) {
    if (info.pixel_fmt != TH_PF_420)
        throw std::invalid_argument(
            "theora: profile requires 8-bit 4:2:0 video");
    if (info.colorspace != TH_CS_UNSPECIFIED)
        throw std::invalid_argument(
            "theora: tagged color spaces are not exactly represented");
    if (info.pic_width == 0 || info.pic_height == 0 ||
        info.frame_width == 0 || info.frame_height == 0 ||
        info.frame_width > kAxisCap || info.frame_height > kAxisCap ||
        info.pic_width > info.frame_width ||
        info.pic_height > info.frame_height ||
        info.pic_x > info.frame_width - info.pic_width ||
        info.pic_y > info.frame_height - info.pic_height)
        throw std::invalid_argument("theora: invalid picture crop");
    if ((info.pic_x & 1U) != 0 || (info.pic_y & 1U) != 0)
        throw std::invalid_argument(
            "theora: 4:2:0 crop offsets must be even");
    if (info.fps_numerator == 0 || info.fps_denominator == 0)
        throw std::invalid_argument(
            "theora: a positive fixed frame rate is required");
    if ((info.aspect_numerator == 0) != (info.aspect_denominator == 0))
        throw std::invalid_argument(
            "theora: pixel aspect numerator and denominator must both be zero or positive");
    if (info.keyframe_granule_shift < 0 ||
        info.keyframe_granule_shift > 31)
        throw std::invalid_argument(
            "theora: invalid keyframe granule shift");
    const uint64_t pixels =
        static_cast<uint64_t>(info.pic_width) * info.pic_height;
    if (pixels > kPixelCap)
        throw std::invalid_argument(
            "theora: picture dimensions exceed the supported pixel limit");
}

Metadata metadata_from(const th_info &info, size_t frames) {
    Metadata result;
    result.width = info.pic_width;
    result.height = info.pic_height;
    result.chroma_width = (info.pic_width + 1) / 2;
    result.chroma_height = (info.pic_height + 1) / 2;
    result.fps_num = info.fps_numerator;
    result.fps_den = info.fps_denominator;
    result.aspect_num = info.aspect_numerator;
    result.aspect_den = info.aspect_denominator;
    result.pic_x = info.pic_x;
    result.pic_y = info.pic_y;
    result.frame_width = info.frame_width;
    result.frame_height = info.frame_height;
    result.keyframe_shift = info.keyframe_granule_shift;
    result.version_major = info.version_major;
    result.version_minor = info.version_minor;
    result.version_subminor = info.version_subminor;
    result.frames = frames;
    return result;
}

struct DecodeTarget {
    ImageSequence *sequence;
    size_t start;
    size_t stop;
};

void copy_plane(
    std::vector<uint8_t> &destination,
    size_t output_frame,
    size_t output_height,
    size_t output_width,
    const th_img_plane &source,
    size_t source_y,
    size_t source_x) {
    const size_t plane_size =
        checked_product(output_height, output_width, "decoded plane");
    uint8_t *output = destination.data() + output_frame * plane_size;
    for (size_t row = 0; row < output_height; ++row) {
        const unsigned char *input =
            source.data + (source_y + row) * source.stride + source_x;
        std::memcpy(output + row * output_width, input, output_width);
    }
}

void validate_decoded_planes(const th_info &info, const th_ycbcr_buffer planes) {
    const uint32_t x[3]{info.pic_x, info.pic_x / 2, info.pic_x / 2};
    const uint32_t y[3]{info.pic_y, info.pic_y / 2, info.pic_y / 2};
    const uint32_t width[3]{
        info.pic_width, (info.pic_width + 1) / 2,
        (info.pic_width + 1) / 2};
    const uint32_t height[3]{
        info.pic_height, (info.pic_height + 1) / 2,
        (info.pic_height + 1) / 2};
    for (size_t plane = 0; plane < 3; ++plane) {
        if (planes[plane].data == nullptr || planes[plane].stride < 0 ||
            static_cast<uint64_t>(x[plane]) + width[plane] >
                static_cast<uint64_t>(planes[plane].width) ||
            static_cast<uint64_t>(y[plane]) + height[plane] >
                static_cast<uint64_t>(planes[plane].height) ||
            static_cast<uint64_t>(x[plane]) + width[plane] >
                static_cast<uint64_t>(planes[plane].stride))
            throw std::runtime_error(
                "theora: decoder returned inconsistent plane bounds");
    }
}

Metadata walk_theora(
    const uint8_t *data, size_t size, DecodeTarget *target) {
    SyncGuard sync;
    StreamGuard stream;
    HeaderGuard header;
    int serial = 0;
    int64_t expected_page = 0;
    bool saw_page = false;
    bool saw_eos_page = false;
    bool saw_eos_packet = false;
    bool headers_finished = false;
    size_t header_count = 0;
    size_t frame_count = 0;
    size_t page_bytes = 0;

    auto process_packet = [&](ogg_packet &packet) {
        if (saw_eos_packet)
            throw std::invalid_argument("theora: packet follows end of stream");
        if (!headers_finished) {
            const int status = th_decode_headerin(
                &header.info, &header.comment, &header.setup, &packet);
            if (status < 0)
                throw std::invalid_argument(
                    "theora: invalid or non-Theora header packet");
            if (status > 0) {
                if (packet.e_o_s)
                    throw std::invalid_argument(
                        "theora: stream ended in its headers");
                if (++header_count > 16)
                    throw std::invalid_argument(
                        "theora: too many header packets");
                return;
            }
            if (header_count < 3)
                throw std::invalid_argument(
                    "theora: fewer than three header packets");
            validate_info(header.info);
            if (header.comment.comments != 0)
                throw std::invalid_argument(
                    "theora: user comments are not represented");
            headers_finished = true;
            if (target) {
                header.decoder = th_decode_alloc(&header.info, header.setup);
                if (!header.decoder)
                    throw std::invalid_argument(
                        "theora: decoder rejected stream setup");
            }
        }

        if (++frame_count > kFrameCap)
            throw std::invalid_argument(
                "theora: frame count exceeds the supported limit");
        if (packet.granulepos >= 0) {
            const unsigned shift = static_cast<unsigned>(
                header.info.keyframe_granule_shift);
            const uint64_t granule = static_cast<uint64_t>(
                packet.granulepos);
            const uint64_t mask = (uint64_t{1} << shift) - 1;
            const uint64_t granule_frame =
                (granule >> shift) + (granule & mask);
            if (granule_frame != frame_count)
                throw std::invalid_argument(
                    "theora: granule position disagrees with frame order");
        }
        if (target && frame_count <= target->stop) {
            ogg_int64_t granule = -1;
            const int status =
                th_decode_packetin(header.decoder, &packet, &granule);
            if (status < 0)
                throw std::invalid_argument(
                    "theora: invalid encoded frame packet");
            if (status == TH_DUPFRAME && frame_count == 1)
                throw std::invalid_argument(
                    "theora: first video packet cannot duplicate a prior frame");
            if (frame_count > target->start) {
                th_ycbcr_buffer planes;
                if (th_decode_ycbcr_out(header.decoder, planes) != 0)
                    throw std::runtime_error(
                        "theora: decoded planes are unavailable");
                validate_decoded_planes(header.info, planes);
                const size_t output_frame =
                    frame_count - target->start - 1;
                copy_plane(
                    target->sequence->y, output_frame,
                    header.info.pic_height, header.info.pic_width,
                    planes[0], header.info.pic_y, header.info.pic_x);
                copy_plane(
                    target->sequence->u, output_frame,
                    (header.info.pic_height + 1) / 2,
                    (header.info.pic_width + 1) / 2,
                    planes[1], header.info.pic_y / 2,
                    header.info.pic_x / 2);
                copy_plane(
                    target->sequence->v, output_frame,
                    (header.info.pic_height + 1) / 2,
                    (header.info.pic_width + 1) / 2,
                    planes[2], header.info.pic_y / 2,
                    header.info.pic_x / 2);
            }
        }
        saw_eos_packet = packet.e_o_s != 0;
    };

    auto process_page = [&](ogg_page &page) {
        if (saw_eos_page)
            throw std::invalid_argument("theora: page follows end of stream");
        if (ogg_page_version(&page) != 0)
            throw std::invalid_argument("theora: unsupported Ogg page version");
        const int page_serial = ogg_page_serialno(&page);
        const long page_number = ogg_page_pageno(&page);
        if (!saw_page) {
            if (!ogg_page_bos(&page) || page_number != 0)
                throw std::invalid_argument(
                    "theora: first Ogg page must begin one logical stream");
            serial = page_serial;
            stream.init(serial);
            saw_page = true;
        } else {
            if (page_serial != serial)
                throw std::invalid_argument(
                    "theora: multiple or chained logical streams are unsupported");
            if (ogg_page_bos(&page))
                throw std::invalid_argument(
                    "theora: chained logical streams are unsupported");
        }
        if (page_number < 0 || page_number != expected_page++)
            throw std::invalid_argument(
                "theora: Ogg page sequence is not contiguous");
        if (ogg_stream_pagein(&stream.value, &page) != 0)
            throw std::invalid_argument("theora: invalid Ogg page");
        ogg_packet packet{};
        for (;;) {
            const int status = ogg_stream_packetout(&stream.value, &packet);
            if (status == 0) break;
            if (status < 0)
                throw std::invalid_argument(
                    "theora: discontinuous Ogg packet data");
            process_packet(packet);
        }
        saw_eos_page = ogg_page_eos(&page) != 0;
        const size_t header_size = static_cast<size_t>(page.header_len);
        const size_t body_size = static_cast<size_t>(page.body_len);
        if (page_bytes > size || header_size > size - page_bytes)
            throw std::invalid_argument(
                "theora: Ogg page lengths exceed the input buffer");
        page_bytes += header_size;
        if (body_size > size - page_bytes)
            throw std::invalid_argument(
                "theora: Ogg page lengths exceed the input buffer");
        page_bytes += body_size;
    };

    size_t offset = 0;
    while (offset < size) {
        const size_t amount = std::min(kFeedChunk, size - offset);
        char *buffer = ogg_sync_buffer(
            &sync.value, static_cast<long>(amount));
        if (!buffer)
            throw std::bad_alloc();
        std::memcpy(buffer, data + offset, amount);
        if (ogg_sync_wrote(&sync.value, static_cast<long>(amount)) != 0)
            throw std::runtime_error("theora: libogg input staging failed");
        offset += amount;
        for (;;) {
            ogg_page page{};
            const int status = ogg_sync_pageout(&sync.value, &page);
            if (status == 0) break;
            if (status < 0)
                throw std::invalid_argument(
                    "theora: malformed Ogg framing or checksum");
            process_page(page);
        }
    }
    if (!saw_page || page_bytes != size)
        throw std::invalid_argument("theora: truncated or trailing Ogg data");
    if (!saw_eos_page || !saw_eos_packet)
        throw std::invalid_argument("theora: missing end-of-stream marker");
    if (!headers_finished || frame_count == 0)
        throw std::invalid_argument("theora: stream contains no video frames");
    validate_sample_count(
        frame_count, header.info.pic_height, header.info.pic_width);
    return metadata_from(header.info, frame_count);
}

void assign_timing(
    ImageSequence &sequence, const Metadata &metadata,
    size_t source_start) {
    const uint64_t period =
        uint64_t{1000000000} * metadata.fps_den;
    const uint64_t base = period / metadata.fps_num;
    const uint64_t remainder = period % metadata.fps_num;
    uint64_t timestamp = 0;
    uint64_t accumulator = 0;
    for (size_t index = 0; index < metadata.frames; ++index) {
        uint64_t duration = base;
        accumulator += remainder;
        if (accumulator >= metadata.fps_num) {
            accumulator -= metadata.fps_num;
            ++duration;
        }
        if (timestamp > static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()) ||
            duration > static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()) ||
            timestamp > std::numeric_limits<uint64_t>::max() - duration)
            throw std::invalid_argument(
                "theora: frame timing exceeds int64 nanoseconds");
        if (index >= source_start &&
            index < source_start + sequence.n) {
            sequence.timestamps_ns.push_back(
                static_cast<int64_t>(timestamp));
            sequence.durations_ns.push_back(
                static_cast<int64_t>(duration));
        }
        timestamp += duration;
    }
}

ImageSequence decode_theora(
    nb::handle source, bool partial, size_t start, size_t stop) {
    ByteView input(source);
    ImageSequence sequence;
    {
        nb::gil_scoped_release release;
        const Metadata metadata =
            walk_theora(input.data(), input.size(), nullptr);
        if (!partial) {
            start = 0;
            stop = metadata.frames;
        } else {
            checked_half_open_range(
                start, stop, metadata.frames, "theora frame range");
        }
        sequence.storage_mode = "yuv_planar";
        sequence.n = stop - start;
        sequence.height = metadata.height;
        sequence.width = metadata.width;
        sequence.channels = 3;
        sequence.chroma_height = metadata.chroma_height;
        sequence.chroma_width = metadata.chroma_width;
        sequence.frame_dtype = "uint8";
        sequence.color_space = "ycbcr";
        sequence.alpha_mode = "none";
        sequence.chroma_subsampling = "420";
        sequence.chroma_siting = "unspecified";
        sequence.color_range = "unknown";
        sequence.matrix = "unknown";
        sequence.interlace = "progressive";
        sequence.frame_rate_numerator = metadata.fps_num;
        sequence.frame_rate_denominator = metadata.fps_den;
        sequence.pixel_aspect_numerator = metadata.aspect_num;
        sequence.pixel_aspect_denominator = metadata.aspect_den;
        const size_t y_size = checked_product(
            metadata.height, metadata.width, "Y plane");
        const size_t c_size = checked_product(
            metadata.chroma_height, metadata.chroma_width, "chroma plane");
        sequence.y.resize(checked_product(sequence.n, y_size, "Y planes"));
        sequence.u.resize(checked_product(sequence.n, c_size, "Cb planes"));
        sequence.v.resize(checked_product(sequence.n, c_size, "Cr planes"));
        DecodeTarget target{&sequence, start, stop};
        const Metadata decoded =
            walk_theora(input.data(), input.size(), &target);
        if (decoded.frames != metadata.frames)
            throw std::logic_error("theora: inconsistent stream scan");
        assign_timing(sequence, metadata, start);
        validate_image_sequence(sequence, "theora decoded sequence");
    }
    return sequence;
}

void validate_write_timing(const ImageSequence &sequence) {
    if (!sequence.has_timing()) return;
    Metadata metadata;
    metadata.frames = sequence.n;
    metadata.fps_num = sequence.frame_rate_numerator;
    metadata.fps_den = sequence.frame_rate_denominator;
    ImageSequence expected;
    expected.n = sequence.n;
    assign_timing(expected, metadata, 0);
    if (sequence.timestamps_ns != expected.timestamps_ns ||
        sequence.durations_ns != expected.durations_ns)
        throw std::invalid_argument(
            "theora: exact timing disagrees with the frame-rate rational");
}

void validate_write(const ImageSequence &sequence) {
    validate_image_sequence(sequence, "theora write");
    if (sequence.storage_mode != "yuv_planar" ||
        sequence.frame_dtype != "uint8" ||
        sequence.color_space != "ycbcr" ||
        sequence.chroma_subsampling != "420" ||
        sequence.chroma_siting != "unspecified")
        throw std::invalid_argument(
            "theora: writer requires planar uint8 4:2:0 Y'CbCr with unspecified siting");
    if (sequence.color_range != "unknown" || sequence.matrix != "unknown")
        throw std::invalid_argument(
            "theora: writer cannot preserve explicit range or matrix metadata");
    if (sequence.interlace != "progressive" ||
        sequence.alpha_mode != "none")
        throw std::invalid_argument(
            "theora: writer requires progressive video without alpha");
    if (sequence.n == 0 || sequence.n > kFrameCap ||
        sequence.width == 0 || sequence.height == 0 ||
        sequence.width > kAxisCap || sequence.height > kAxisCap)
        throw std::invalid_argument("theora: unsupported sequence extent");
    if (sequence.frame_rate_numerator == 0 ||
        sequence.frame_rate_denominator == 0)
        throw std::invalid_argument(
            "theora: writer requires a positive fixed frame rate");
    if ((sequence.pixel_aspect_numerator == 0) !=
        (sequence.pixel_aspect_denominator == 0))
        throw std::invalid_argument(
            "theora: pixel aspect numerator and denominator must both be zero or positive");
    if (sequence.loop_count_present || sequence.background_present)
        throw std::invalid_argument(
            "theora: loop and animation-background metadata are not represented");
    validate_sample_count(sequence.n, sequence.height, sequence.width);
    validate_write_timing(sequence);
}

void drain_pages(
    ogg_stream_state &stream, ChunkedOutput &output, bool flush) {
    for (;;) {
        ogg_page page{};
        const int status =
            flush ? ogg_stream_flush(&stream, &page)
                  : ogg_stream_pageout(&stream, &page);
        if (status == 0) break;
        if (status < 0)
            throw std::runtime_error("theora: libogg page output failed");
        output.write(
            reinterpret_cast<const char *>(page.header), page.header_len);
        output.write(
            reinterpret_cast<const char *>(page.body), page.body_len);
    }
}

nb::bytes write_theora(
    const ImageSequence &sequence, int quality, int keyframe_interval) {
    validate_write(sequence);
    if (quality < 0 || quality > 63)
        throw std::invalid_argument("theora: quality must be in 0..63");
    if (keyframe_interval < 1 || keyframe_interval > 32768)
        throw std::invalid_argument(
            "theora: keyframe_interval must be in 1..32768");
    ChunkedOutput output("theora");
    {
        nb::gil_scoped_release release;
        th_info info;
        th_info_init(&info);
        info.frame_width = static_cast<ogg_uint32_t>((sequence.width + 15) & ~size_t{15});
        info.frame_height = static_cast<ogg_uint32_t>((sequence.height + 15) & ~size_t{15});
        info.pic_width = static_cast<ogg_uint32_t>(sequence.width);
        info.pic_height = static_cast<ogg_uint32_t>(sequence.height);
        info.pic_x = 0;
        info.pic_y = 0;
        info.fps_numerator = sequence.frame_rate_numerator;
        info.fps_denominator = sequence.frame_rate_denominator;
        info.aspect_numerator = sequence.pixel_aspect_numerator;
        info.aspect_denominator = sequence.pixel_aspect_denominator;
        info.colorspace = TH_CS_UNSPECIFIED;
        info.pixel_fmt = TH_PF_420;
        info.target_bitrate = 0;
        info.quality = quality;
        int shift = 0;
        while ((1U << shift) < static_cast<unsigned>(keyframe_interval)) ++shift;
        info.keyframe_granule_shift = shift;
        EncoderGuard encoder;
        encoder.value = th_encode_alloc(&info);
        th_info_clear(&info);
        if (!encoder.value)
            throw std::invalid_argument(
                "theora: encoder rejected sequence parameters");
        int forced_interval = keyframe_interval;
        if (th_encode_ctl(
                encoder.value,
                TH_ENCCTL_SET_KEYFRAME_FREQUENCY_FORCE,
                &forced_interval,
                sizeof(forced_interval)) < 0)
            throw std::invalid_argument(
                "theora: encoder rejected keyframe interval");

        StreamGuard stream;
        stream.init(kSerial);
        CommentGuard comments;
        ogg_packet packet{};
        int header_count = 0;
        for (;;) {
            const int status = th_encode_flushheader(
                encoder.value, &comments.value, &packet);
            if (status < 0)
                throw std::runtime_error(
                    "theora: header encoding failed");
            if (status == 0) break;
            if (ogg_stream_packetin(&stream.value, &packet) != 0)
                throw std::runtime_error(
                    "theora: Ogg header packet staging failed");
            ++header_count;
            if (header_count == 1)
                drain_pages(stream.value, output, true);
        }
        if (header_count < 3)
            throw std::runtime_error(
                "theora: encoder emitted incomplete headers");
        drain_pages(stream.value, output, true);

        const size_t y_size = checked_product(
            sequence.height, sequence.width, "Y plane");
        const size_t c_size = checked_product(
            sequence.chroma_height, sequence.chroma_width, "chroma plane");
        for (size_t frame = 0; frame < sequence.n; ++frame) {
            th_ycbcr_buffer planes;
            planes[0].width = static_cast<int>(sequence.width);
            planes[0].height = static_cast<int>(sequence.height);
            planes[0].stride = static_cast<int>(sequence.width);
            planes[0].data = const_cast<unsigned char *>(
                sequence.y.data() + frame * y_size);
            planes[1].width = static_cast<int>(sequence.chroma_width);
            planes[1].height = static_cast<int>(sequence.chroma_height);
            planes[1].stride = static_cast<int>(sequence.chroma_width);
            planes[1].data = const_cast<unsigned char *>(
                sequence.u.data() + frame * c_size);
            planes[2].width = static_cast<int>(sequence.chroma_width);
            planes[2].height = static_cast<int>(sequence.chroma_height);
            planes[2].stride = static_cast<int>(sequence.chroma_width);
            planes[2].data = const_cast<unsigned char *>(
                sequence.v.data() + frame * c_size);
            if (th_encode_ycbcr_in(encoder.value, planes) != 0)
                throw std::invalid_argument(
                    "theora: encoder rejected frame planes");
            for (;;) {
                const int status = th_encode_packetout(
                    encoder.value, frame + 1 == sequence.n, &packet);
                if (status < 0)
                    throw std::runtime_error("theora: frame encoding failed");
                if (status == 0) break;
                if (ogg_stream_packetin(&stream.value, &packet) != 0)
                    throw std::runtime_error(
                        "theora: Ogg frame packet staging failed");
                drain_pages(stream.value, output, false);
            }
        }
        drain_pages(stream.value, output, true);
    }
    return output.finish();
}

ImageSequence read_theora(nb::handle source) {
    return decode_theora(source, false, 0, 0);
}

ImageSequence read_theora_frames(
    nb::handle source, size_t start, size_t stop) {
    return decode_theora(source, true, start, stop);
}

nb::dict inspect_theora(nb::handle source) {
    ByteView input(source);
    Metadata metadata;
    {
        nb::gil_scoped_release release;
        metadata = walk_theora(input.data(), input.size(), nullptr);
    }
    nb::dict result;
    result["width"] = metadata.width;
    result["height"] = metadata.height;
    result["frames"] = metadata.frames;
    result["channels"] = 3;
    result["chroma_width"] = metadata.chroma_width;
    result["chroma_height"] = metadata.chroma_height;
    result["chroma_subsampling"] = "420";
    result["chroma_siting"] = "unspecified";
    result["color_range"] = "unknown";
    result["matrix"] = "unknown";
    result["interlace"] = "progressive";
    result["frame_rate_numerator"] = metadata.fps_num;
    result["frame_rate_denominator"] = metadata.fps_den;
    result["pixel_aspect_numerator"] = metadata.aspect_num;
    result["pixel_aspect_denominator"] = metadata.aspect_den;
    result["frame_width"] = metadata.frame_width;
    result["frame_height"] = metadata.frame_height;
    result["picture_x"] = metadata.pic_x;
    result["picture_y"] = metadata.pic_y;
    result["keyframe_granule_shift"] = metadata.keyframe_shift;
    result["version"] =
        std::to_string(metadata.version_major) + "." +
        std::to_string(metadata.version_minor) + "." +
        std::to_string(metadata.version_subminor);
    return result;
}

}  // namespace

void register_theora(nb::module_ &module) {
    module.def(
        "read_theora", &read_theora, "data"_a,
        "Decode one strict Ogg/Theora video stream into owned planar 4:2:0 "
        "ImageSequence storage.");
    module.def(
        "read_theora_frames", &read_theora_frames,
        "data"_a, "start"_a, "stop"_a,
        "Decode a nonempty half-open Theora frame range.");
    module.def(
        "write_theora", &write_theora,
        "sequence"_a, "quality"_a = 48, "keyframe_interval"_a = 64,
        "Encode planar 4:2:0 frames into a video-only Ogg/Theora stream; "
        "direct file sinks emit completed Ogg pages.");
    module.def(
        "_inspect_theora", &inspect_theora, "data"_a,
        "Validate Ogg/Theora framing and return stream metadata without "
        "decoding pixel planes.");
}
