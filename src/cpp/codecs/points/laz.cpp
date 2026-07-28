// codecs/points/laz.cpp -- LASzip-compatible LAZ <-> PointCloud through LAZperf 3.4.
//
// The wrapper parses and bounds the container itself before entering LAZperf:
// only the exact standard point records 0-3 and 6-8 plus one LASzip VLR are
// accepted. Unrepresented CRS/extra-byte/VLR/EVLR metadata rejects instead of
// being discarded. Chunk-table allocations and every decompressor callback are
// bounded by the mapped input. Point ranges decompress only overlapping chunks.
//
// Public writes default to point format 0 or 2, matching the plain-LAS writer.
// A private point-format argument covers every LAZperf-supported record in
// parity tests. Direct file writes use a seekable bounded stream over SceneIO's
// native sink, so compressed output and header patches never require a complete
// in-memory byte string.

#include <lazperf/excepts.hpp>
#include <lazperf/header.hpp>
#include <lazperf/lazperf.hpp>
#include <lazperf/vlr.hpp>
#include <lazperf/writers.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <functional>
#include <ios>
#include <limits>
#include <ostream>
#include <sstream>
#include <streambuf>
#include <string>
#include <type_traits>
#include <vector>

#include "records/point_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kLazMaxPoints = 4000000000ull;
constexpr uint32_t kLazMaxChunks = 4000000u;
constexpr double kI32Max = 2147483647.0;
constexpr size_t kSinkBufferSize = 256 * 1024;

struct LazItem {
    uint16_t type;
    uint16_t size;
    uint16_t version;
};

struct LazChunk {
    uint64_t point_start = 0;
    uint64_t point_count = 0;
    size_t byte_start = 0;
    size_t byte_size = 0;
};

struct LazInfo {
    uint8_t version_minor = 0;
    uint8_t point_format = 0;
    uint16_t record_length = 0;
    uint64_t count = 0;
    double scale[3] = {0.0, 0.0, 0.0};
    double offset[3] = {0.0, 0.0, 0.0};
    uint32_t chunk_size = 0;
    std::vector<LazChunk> chunks;
};

size_t required_header_size(uint8_t version_minor) {
    if (version_minor >= 4) return 375;
    if (version_minor >= 3) return 235;
    return 227;
}

uint16_t base_record_length(uint8_t point_format) {
    switch (point_format) {
        case 0:
            return 20;
        case 1:
            return 28;
        case 2:
            return 26;
        case 3:
            return 34;
        case 6:
            return 30;
        case 7:
            return 36;
        case 8:
            return 38;
        default:
            throw std::invalid_argument(
                "laz: supported point formats are 0-3 and 6-8");
    }
}

int color_offset(uint8_t point_format) {
    switch (point_format) {
        case 2:
            return 20;
        case 3:
            return 28;
        case 7:
        case 8:
            return 30;
        default:
            return -1;
    }
}

std::string fixed_text(const uint8_t *data, size_t size) {
    size_t end = 0;
    while (end < size && data[end] != 0) ++end;
    while (end != 0 && data[end - 1] == ' ') --end;
    for (size_t index = end; index < size; ++index) {
        if (data[index] != 0 && data[index] != ' ')
            throw std::invalid_argument(
                "laz: fixed-width VLR text has non-padding bytes");
    }
    return std::string(
        reinterpret_cast<const char *>(data), end);
}

std::vector<LazItem> expected_items(uint8_t point_format) {
    switch (point_format) {
        case 0:
            return {{6, 20, 2}};
        case 1:
            return {{6, 20, 2}, {7, 8, 2}};
        case 2:
            return {{6, 20, 2}, {8, 6, 2}};
        case 3:
            return {{6, 20, 2}, {7, 8, 2}, {8, 6, 2}};
        case 6:
            return {{10, 30, 3}};
        case 7:
            return {{10, 30, 3}, {11, 6, 3}};
        case 8:
            return {{10, 30, 3}, {12, 8, 3}};
        default:
            throw std::invalid_argument(
                "laz: unsupported point format");
    }
}

class BoundedInput {
public:
    BoundedInput(
        const uint8_t *data, size_t size,
        const char *context)
        : data_(data), size_(size), context_(context) {}

    void read(unsigned char *output, size_t count) {
        if (count > size_ - position_)
            throw std::invalid_argument(
                std::string("laz: truncated ") + context_);
        if (count != 0)
            std::memcpy(output, data_ + position_, count);
        position_ += count;
    }

    lazperf::InputCb callback() {
        using namespace std::placeholders;
        return std::bind(
            &BoundedInput::read, this, _1, _2);
    }

    size_t position() const { return position_; }

    void require_zero_padding(size_t maximum) {
        const size_t remaining = size_ - position_;
        if (remaining > maximum)
            throw std::invalid_argument(
                std::string("laz: trailing bytes after ") +
                context_);
        for (size_t index = position_; index < size_; ++index) {
            if (data_[index] != 0)
                throw std::invalid_argument(
                    std::string("laz: nonzero arithmetic padding after ") +
                    context_);
        }
        position_ = size_;
    }

private:
    const uint8_t *data_;
    size_t size_;
    const char *context_;
    size_t position_ = 0;
};

void validate_format14_chunk(
    const uint8_t *data, const LazChunk &chunk,
    uint8_t point_format, uint16_t record_length) {
    if (chunk.point_count == 0) {
        if (chunk.byte_size != 0)
            throw std::invalid_argument(
                "laz: empty chunk has compressed payload");
        return;
    }
    const size_t stream_count =
        9 + (point_format == 7 ? 1 :
             point_format == 8 ? 2 : 0);
    const size_t prefix =
        static_cast<size_t>(record_length) + 4 +
        stream_count * 4;
    if (chunk.byte_size < prefix)
        throw std::invalid_argument(
            "laz: format-1.4 chunk header is truncated");
    LeReader reader(data + chunk.byte_start, chunk.byte_size);
    reader.pos = record_length;
    const uint32_t stored_count = reader.get<uint32_t>();
    if (stored_count != chunk.point_count)
        throw std::invalid_argument(
            "laz: compressed chunk point count disagrees "
            "with the chunk table");
    uint64_t stream_bytes = 0;
    for (size_t index = 0; index < stream_count; ++index) {
        const uint32_t bytes = reader.get<uint32_t>();
        if (bytes != 0 && bytes < 4)
            throw std::invalid_argument(
                "laz: arithmetic stream is too short");
        stream_bytes += bytes;
    }
    if (stream_bytes != chunk.byte_size - prefix)
        throw std::invalid_argument(
            "laz: format-1.4 stream sizes disagree with "
            "the compressed chunk extent");
}

LazInfo parse_laz(const uint8_t *data, size_t size) {
    if (size < 227)
        throw std::invalid_argument(
            "laz: file is smaller than the LAS public header");
    if (std::memcmp(data, "LASF", 4) != 0)
        throw std::invalid_argument(
            "laz: bad signature (expected 'LASF')");

    LeReader header(data, size);
    header.pos = 6;
    const uint16_t global_encoding = header.get<uint16_t>();
    // Bit 0 describes the GPS-time field that this deliberately lossy
    // PointCloud projection drops. Waveform, synthetic-return, WKT, and
    // reserved flags describe semantics we cannot retain.
    if ((global_encoding & 0xfffeU) != 0)
        throw std::invalid_argument(
            "laz: global-encoding metadata is not representable");
    header.pos = 24;
    const uint8_t version_major = header.get<uint8_t>();
    LazInfo info;
    info.version_minor = header.get<uint8_t>();
    if (version_major != 1 ||
        info.version_minor < 1 ||
        info.version_minor > 4)
        throw std::invalid_argument(
            "laz: supported versions are 1.1 through 1.4");
    const size_t required =
        required_header_size(info.version_minor);
    if (size < required)
        throw std::invalid_argument(
            "laz: truncated public header");

    header.pos = 94;
    const uint16_t header_size = header.get<uint16_t>();
    const uint32_t point_offset = header.get<uint32_t>();
    const uint32_t vlr_count = header.get<uint32_t>();
    if (header_size != required)
        throw std::invalid_argument(
            "laz: extended public headers are not representable");
    header.pos = 104;
    const uint8_t encoded_format = header.get<uint8_t>();
    if ((encoded_format & 0xc0U) != 0x80U)
        throw std::invalid_argument(
            "laz: header does not use supported LASzip compression bits");
    info.point_format =
        static_cast<uint8_t>(encoded_format & 0x3fU);
    info.record_length = header.get<uint16_t>();
    const uint32_t legacy_count = header.get<uint32_t>();
    if (info.record_length !=
        base_record_length(info.point_format))
        throw std::invalid_argument(
            "laz: extra bytes and nonstandard point strides "
            "are not representable");
    if (info.point_format >= 6 &&
        info.version_minor < 4)
        throw std::invalid_argument(
            "laz: point formats 6-8 require LAS 1.4");

    header.pos = 131;
    for (double &value : info.scale)
        value = header.get<double>();
    for (double &value : info.offset)
        value = header.get<double>();
    for (double value : info.scale) {
        if (!(value > 0.0) || !std::isfinite(value))
            throw std::invalid_argument(
                "laz: coordinate scales must be finite and positive");
    }
    for (double value : info.offset) {
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "laz: coordinate offsets must be finite");
    }

    info.count = legacy_count;
    if (info.version_minor >= 3) {
        header.pos = 227;
        if (header.get<uint64_t>() != 0)
            throw std::invalid_argument(
                "laz: waveform packet records are not representable");
    }
    if (info.version_minor >= 4) {
        const uint64_t evlr_offset = header.get<uint64_t>();
        const uint32_t evlr_count = header.get<uint32_t>();
        info.count = header.get<uint64_t>();
        if (evlr_offset != 0 || evlr_count != 0)
            throw std::invalid_argument(
                "laz: EVLR metadata is not representable");
    }
    if (info.count > kLazMaxPoints)
        throw std::invalid_argument(
            "laz: point count exceeds the supported limit");
    if (point_offset < header_size ||
        point_offset > size ||
        size - point_offset < 8)
        throw std::invalid_argument(
            "laz: invalid compressed point-data offset");

    size_t cursor = header_size;
    const uint8_t *laz_payload = nullptr;
    size_t laz_payload_size = 0;
    for (uint32_t index = 0; index < vlr_count; ++index) {
        if (cursor > point_offset ||
            point_offset - cursor < 54)
            throw std::invalid_argument(
                "laz: truncated VLR header");
        LeReader vlr(data + cursor, point_offset - cursor);
        const uint16_t reserved = vlr.get<uint16_t>();
        const std::string user =
            fixed_text(data + cursor + 2, 16);
        vlr.pos = 18;
        const uint16_t record_id = vlr.get<uint16_t>();
        const uint16_t length = vlr.get<uint16_t>();
        if (reserved != 0 ||
            user != "laszip encoded" ||
            record_id != 22204)
            throw std::invalid_argument(
                "laz: only the LASzip VLR is representable");
        if (laz_payload)
            throw std::invalid_argument(
                "laz: duplicate LASzip VLR");
        if (length > point_offset - cursor - 54)
            throw std::invalid_argument(
                "laz: truncated LASzip VLR");
        laz_payload = data + cursor + 54;
        laz_payload_size = length;
        cursor += 54 + length;
    }
    if (!laz_payload)
        throw std::invalid_argument(
            "laz: missing LASzip VLR");
    if (cursor != point_offset)
        throw std::invalid_argument(
            "laz: VLR padding or unindexed metadata is not representable");
    if (laz_payload_size < 34)
        throw std::invalid_argument(
            "laz: LASzip VLR is truncated");

    LeReader laz(laz_payload, laz_payload_size);
    const uint16_t compressor = laz.get<uint16_t>();
    const uint16_t coder = laz.get<uint16_t>();
    laz.get<uint8_t>();
    laz.get<uint8_t>();
    laz.get<uint16_t>();
    const uint32_t options = laz.get<uint32_t>();
    info.chunk_size = laz.get<uint32_t>();
    laz.get<uint64_t>();
    laz.get<uint64_t>();
    const uint16_t item_count = laz.get<uint16_t>();
    const uint16_t expected_compressor =
        info.point_format <= 5 ? 2 : 3;
    if (compressor != expected_compressor ||
        coder != 0 || options != 0 ||
        info.chunk_size == 0)
        throw std::invalid_argument(
            "laz: unsupported LASzip compressor configuration");
    if (item_count >
        (std::numeric_limits<size_t>::max() - 34) / 6 ||
        laz_payload_size != 34 + item_count * 6)
        throw std::invalid_argument(
            "laz: LASzip item table extent is malformed");
    const std::vector<LazItem> expected =
        expected_items(info.point_format);
    if (item_count != expected.size())
        throw std::invalid_argument(
            "laz: LASzip item schema disagrees with point format");
    for (size_t index = 0; index < expected.size(); ++index) {
        const LazItem actual{
            laz.get<uint16_t>(),
            laz.get<uint16_t>(),
            laz.get<uint16_t>()};
        if (actual.type != expected[index].type ||
            actual.size != expected[index].size ||
            actual.version != expected[index].version)
            throw std::invalid_argument(
                "laz: unsupported LASzip item schema");
    }

    LeReader point_data(data + point_offset, size - point_offset);
    const int64_t signed_table_offset =
        point_data.get<int64_t>();
    if (signed_table_offset < 0)
        throw std::invalid_argument(
            "laz: deferred or negative chunk-table offsets "
            "are not supported");
    const uint64_t table_offset =
        static_cast<uint64_t>(signed_table_offset);
    const uint64_t first_chunk =
        static_cast<uint64_t>(point_offset) + 8;
    if (table_offset < first_chunk ||
        table_offset > size ||
        size - static_cast<size_t>(table_offset) < 8)
        throw std::invalid_argument(
            "laz: chunk-table offset is out of bounds");
    LeReader table_header(
        data + static_cast<size_t>(table_offset),
        size - static_cast<size_t>(table_offset));
    if (table_header.get<uint32_t>() != 0)
        throw std::invalid_argument(
            "laz: unsupported chunk-table version");
    const uint32_t chunk_count =
        table_header.get<uint32_t>();
    if (chunk_count > kLazMaxChunks)
        throw std::invalid_argument(
            "laz: chunk count exceeds the supported limit");
    if (info.count != 0 &&
        (chunk_count == 0 || chunk_count > info.count))
        throw std::invalid_argument(
            "laz: chunk count disagrees with point count");
    if (info.count == 0 && chunk_count > 1)
        throw std::invalid_argument(
            "laz: empty files may not contain multiple chunks");

    const bool variable =
        info.chunk_size == lazperf::VariableChunkSize;
    if (!variable) {
        const uint64_t expected_chunks =
            info.count == 0
                ? 0
                : 1 + (info.count - 1) / info.chunk_size;
        if (chunk_count != expected_chunks &&
            !(info.count == 0 && chunk_count == 1))
            throw std::invalid_argument(
                "laz: fixed chunk count disagrees with "
                "the LASzip chunk size");
    }

    std::vector<lazperf::chunk> entries;
    if (chunk_count != 0) {
        BoundedInput table_input(
            data + static_cast<size_t>(table_offset) + 8,
            size - static_cast<size_t>(table_offset) - 8,
            "compressed chunk table");
        try {
            entries = lazperf::decompress_chunk_table(
                table_input.callback(), chunk_count, variable);
            // LASzip's arithmetic encoder appends the exact zero bytes needed
            // for decoder renormalization. A valid table consumes all of them;
            // any remainder is unindexed container data.
            table_input.require_zero_padding(0);
        } catch (const lazperf::error &error) {
            throw std::invalid_argument(
                std::string("laz: invalid chunk table: ") +
                error.what());
        }
    } else if (static_cast<size_t>(table_offset) + 8 != size) {
        throw std::invalid_argument(
            "laz: trailing bytes after empty chunk table");
    }

    uint64_t point_cursor = 0;
    uint64_t byte_cursor = first_chunk;
    info.chunks.reserve(entries.size());
    for (size_t index = 0; index < entries.size(); ++index) {
        const uint64_t points =
            variable
                ? entries[index].count
                : std::min<uint64_t>(
                      info.chunk_size,
                      info.count - point_cursor);
        const uint64_t bytes = entries[index].offset;
        if (points == 0 && info.count != 0)
            throw std::invalid_argument(
                "laz: nonterminal chunk is empty");
        if (points > info.count - point_cursor ||
            bytes > table_offset - byte_cursor)
            throw std::invalid_argument(
                "laz: chunk table points outside compressed data");
        LazChunk chunk;
        chunk.point_start = point_cursor;
        chunk.point_count = points;
        chunk.byte_start = static_cast<size_t>(byte_cursor);
        chunk.byte_size = static_cast<size_t>(bytes);
        info.chunks.push_back(chunk);
        point_cursor += points;
        byte_cursor += bytes;
    }
    if (point_cursor != info.count ||
        byte_cursor != table_offset)
        throw std::invalid_argument(
            "laz: chunk extents do not cover the declared data");

    if (info.point_format >= 6) {
        for (const LazChunk &chunk : info.chunks)
            validate_format14_chunk(
                data, chunk, info.point_format,
                info.record_length);
    }
    return info;
}

void decompress_chunk(
    const uint8_t *data, const LazInfo &info,
    const LazChunk &chunk,
    const std::function<void(uint64_t, const char *)> &consume,
    uint64_t point_limit =
        std::numeric_limits<uint64_t>::max()) {
    if (chunk.point_count == 0) return;
    BoundedInput input(
        data + chunk.byte_start, chunk.byte_size,
        "compressed point chunk");
    lazperf::las_decompressor::ptr decompressor;
    try {
        decompressor = lazperf::build_las_decompressor(
            input.callback(), info.point_format, 0);
        if (!decompressor)
            throw std::invalid_argument(
                "laz: LAZperf rejected the point format");
        std::array<char, 38> record{};
        const uint64_t decode_count =
            std::min(chunk.point_count, point_limit);
        for (uint64_t local = 0;
             local < decode_count; ++local) {
            decompressor->decompress(record.data());
            consume(chunk.point_start + local, record.data());
        }
        if (decode_count == chunk.point_count &&
            info.point_format <= 3)
            input.require_zero_padding(0);
    } catch (const lazperf::error &error) {
        throw std::invalid_argument(
            std::string("laz: point decompression failed: ") +
            error.what());
    }
}

PointCloud read_laz_impl(
    nb::handle source, size_t lanes, bool partial,
    size_t start, size_t stop) {
    ByteView view(source);
    const uint8_t *data = view.data();
    const size_t size = view.size();
    PointCloud cloud;
    {
        nb::gil_scoped_release release;
        const LazInfo info = parse_laz(data, size);
        const size_t total = static_cast<size_t>(info.count);
        if (!partial) {
            start = 0;
            stop = total;
        } else {
            checked_half_open_range(
                start, stop, total, "laz point range");
        }
        const size_t count = stop - start;
        if (count >
            std::numeric_limits<size_t>::max() / 3)
            throw std::length_error(
                "laz: decoded point array is too large");

        int32_t anchor[3] = {0, 0, 0};
        if (total != 0) {
            decompress_chunk(
                data, info, info.chunks.front(),
                [&](uint64_t row, const char *record) {
                    if (row != 0) return;
                    LeReader point(record, info.record_length);
                    anchor[0] = point.get<int32_t>();
                    anchor[1] = point.get<int32_t>();
                    anchor[2] = point.get<int32_t>();
                },
                1);
        }

        cloud.n = count;
        cloud.xyz.resize(count * 3);
        cloud.intensity.resize(count);
        cloud.intensity_range = "u16";
        cloud.origin[0] =
            info.offset[0] +
            static_cast<double>(anchor[0]) * info.scale[0];
        cloud.origin[1] =
            info.offset[1] +
            static_cast<double>(anchor[1]) * info.scale[1];
        cloud.origin[2] =
            info.offset[2] +
            static_cast<double>(anchor[2]) * info.scale[2];
        const int rgb_offset = color_offset(info.point_format);
        if (rgb_offset >= 0)
            cloud.rgb16.resize(count * 3);

        std::vector<size_t> selected_chunks;
        for (size_t index = 0;
             index < info.chunks.size(); ++index) {
            const LazChunk &chunk = info.chunks[index];
            const uint64_t chunk_stop =
                chunk.point_start + chunk.point_count;
            if (chunk_stop > start &&
                chunk.point_start < stop)
                selected_chunks.push_back(index);
        }
        parallel_for_blocks(
            selected_chunks.size(), lanes, 1,
            [&](size_t begin, size_t end, size_t) {
                for (size_t selected = begin;
                     selected < end; ++selected) {
                    const LazChunk &chunk =
                        info.chunks[
                            selected_chunks[selected]];
                    decompress_chunk(
                        data, info, chunk,
                        [&](uint64_t row,
                            const char *record) {
                            if (row < start || row >= stop)
                                return;
                            const size_t output =
                                static_cast<size_t>(row) -
                                start;
                            LeReader point(
                                record,
                                info.record_length);
                            const int32_t x =
                                point.get<int32_t>();
                            const int32_t y =
                                point.get<int32_t>();
                            const int32_t z =
                                point.get<int32_t>();
                            cloud.intensity[output] =
                                static_cast<float>(
                                    point.get<uint16_t>());
                            cloud.xyz[output * 3] =
                                static_cast<float>(
                                    (static_cast<int64_t>(x) -
                                     anchor[0]) *
                                    info.scale[0]);
                            cloud.xyz[output * 3 + 1] =
                                static_cast<float>(
                                    (static_cast<int64_t>(y) -
                                     anchor[1]) *
                                    info.scale[1]);
                            cloud.xyz[output * 3 + 2] =
                                static_cast<float>(
                                    (static_cast<int64_t>(z) -
                                     anchor[2]) *
                                    info.scale[2]);
                            if (rgb_offset >= 0) {
                                point.pos =
                                    static_cast<size_t>(
                                        rgb_offset);
                                cloud.rgb16[output * 3] =
                                    point.get<uint16_t>();
                                cloud.rgb16[
                                    output * 3 + 1] =
                                    point.get<uint16_t>();
                                cloud.rgb16[
                                    output * 3 + 2] =
                                    point.get<uint16_t>();
                            }
                        });
                }
            });
    }
    return cloud;
}

PointCloud read_laz(nb::handle source, size_t lanes) {
    return read_laz_impl(
        source, lanes, false, 0, 0);
}

PointCloud read_laz_points(
    nb::handle source, size_t start, size_t stop,
    size_t lanes) {
    return read_laz_impl(
        source, lanes, true, start, stop);
}

struct Bounds {
    bool set = false;
    double min[3] = {0.0, 0.0, 0.0};
    double max[3] = {0.0, 0.0, 0.0};
};

Bounds quantized_bounds(
    const PointCloud &cloud, double scale,
    size_t lanes) {
    std::vector<Bounds> local_bounds(kMaxParallelLanes);
    const size_t active = parallel_for_blocks(
        cloud.n, lanes, 65536,
        [&](size_t begin, size_t end, size_t lane) {
            Bounds bounds;
            for (size_t row = begin; row < end; ++row) {
                double values[3];
                for (size_t axis = 0; axis < 3; ++axis) {
                    const double local =
                        cloud.xyz[row * 3 + axis];
                    if (!(std::fabs(local / scale) <=
                          kI32Max))
                        throw std::invalid_argument(
                            "laz: a coordinate is non-finite "
                            "or does not fit LAS's 32-bit "
                            "grid at this scale");
                    values[axis] =
                        std::lround(local / scale) *
                            scale +
                        cloud.origin[axis];
                    if (!std::isfinite(values[axis]))
                        throw std::invalid_argument(
                            "laz: quantized coordinates "
                            "must be finite");
                }
                if (!bounds.set) {
                    bounds.set = true;
                    for (size_t axis = 0;
                         axis < 3; ++axis)
                        bounds.min[axis] =
                            bounds.max[axis] =
                                values[axis];
                } else {
                    for (size_t axis = 0;
                         axis < 3; ++axis) {
                        bounds.min[axis] =
                            std::min(
                                bounds.min[axis],
                                values[axis]);
                        bounds.max[axis] =
                            std::max(
                                bounds.max[axis],
                                values[axis]);
                    }
                }
            }
            local_bounds[lane] = bounds;
        });
    Bounds result;
    for (size_t lane = 0; lane < active; ++lane) {
        const Bounds &local = local_bounds[lane];
        if (!local.set) continue;
        if (!result.set) {
            result = local;
        } else {
            for (size_t axis = 0; axis < 3; ++axis) {
                result.min[axis] =
                    std::min(
                        result.min[axis],
                        local.min[axis]);
                result.max[axis] =
                    std::max(
                        result.max[axis],
                        local.max[axis]);
            }
        }
    }
    return result;
}

void validate_intensities(
    const PointCloud &cloud, size_t lanes) {
    if (!cloud.has_intensity()) return;
    parallel_for_blocks(
        cloud.n, lanes, 65536,
        [&](size_t begin, size_t end, size_t) {
            for (size_t row = begin; row < end; ++row) {
                const double value = cloud.intensity[row];
                if (!std::isfinite(value) ||
                    std::signbit(value) ||
                    value > 65535.0 ||
                    std::trunc(value) != value)
                    throw std::invalid_argument(
                        "laz: intensity values must be exact "
                        "unsigned 16-bit integers");
            }
        });
}

template <typename T>
void put_native(char *&destination, T value) {
    static_assert(std::is_trivially_copyable_v<T>);
    std::memcpy(destination, &value, sizeof(T));
    destination += sizeof(T);
}

struct LazWritePlan {
    uint8_t point_format = 0;
    uint8_t version_minor = 2;
    uint16_t record_length = 20;
    bool color = false;
    bool intensity = false;
    double scale = 0.001;
    Bounds bounds;
};

LazWritePlan make_write_plan(
    const PointCloud &cloud, double scale,
    int requested_format, size_t lanes) {
    if (cloud.has_las_waveform())
        throw std::invalid_argument(
            "laz: LAZperf does not support waveform "
            "point formats 4/5/9/10");
    if (cloud.has_normals())
        throw std::invalid_argument(
            "laz: LAS cannot store normals");
    if (cloud.has_rgb())
        throw std::invalid_argument(
            "laz: LAS stores 16-bit color; provide colors16");
    if (cloud.has_intensity() &&
        cloud.intensity_range != "u16" &&
        cloud.intensity_range != "unknown")
        throw std::invalid_argument(
            "laz: LAS intensity is 16-bit; rescale "
            "the declared range to u16 first");
    if (!cloud.has_default_organization() ||
        !cloud.has_default_viewpoint())
        throw std::invalid_argument(
            "laz: organized shape and acquisition viewpoint "
            "metadata are not representable");
    if (!(scale > 0.0) || !std::isfinite(scale))
        throw std::invalid_argument(
            "laz: scale must be finite and positive");
    for (double value : cloud.origin) {
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "laz: origin values must be finite");
    }
    if (cloud.n >
        std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "laz: point count exceeds SceneIO's "
            "bounded LAZ tier");

    LazWritePlan plan;
    if (requested_format == -1)
        plan.point_format =
            cloud.has_rgb16() ? 2 : 0;
    else if (requested_format == 0 ||
             requested_format == 1 ||
             requested_format == 2 ||
             requested_format == 3 ||
             requested_format == 6 ||
             requested_format == 7 ||
             requested_format == 8)
        plan.point_format =
            static_cast<uint8_t>(requested_format);
    else
        throw std::invalid_argument(
            "laz: point_format must be -1, 0-3, or 6-8");
    plan.color =
        color_offset(plan.point_format) >= 0;
    if (cloud.n != 0 &&
        plan.color != cloud.has_rgb16())
        throw std::invalid_argument(
            plan.color
                ? "laz: selected point format requires colors16"
                : "laz: selected point format cannot store colors16");
    plan.version_minor =
        plan.point_format >= 6 ? 4 : 2;
    plan.record_length =
        base_record_length(plan.point_format);
    plan.intensity = cloud.has_intensity();
    plan.scale = scale;
    plan.bounds =
        quantized_bounds(cloud, scale, lanes);
    validate_intensities(cloud, lanes);
    return plan;
}

std::array<char, 38> make_point_record(
    const PointCloud &cloud,
    const LazWritePlan &plan, size_t row) {
    std::array<char, 38> record{};
    char *destination = record.data();
    put_native<int32_t>(
        destination,
        static_cast<int32_t>(std::lround(
            cloud.xyz[row * 3] / plan.scale)));
    put_native<int32_t>(
        destination,
        static_cast<int32_t>(std::lround(
            cloud.xyz[row * 3 + 1] / plan.scale)));
    put_native<int32_t>(
        destination,
        static_cast<int32_t>(std::lround(
            cloud.xyz[row * 3 + 2] / plan.scale)));
    const double intensity =
        plan.intensity ? cloud.intensity[row] : 0.0;
    put_native<uint16_t>(
        destination,
        static_cast<uint16_t>(intensity));
    if (plan.point_format < 6) {
        put_native<uint8_t>(destination, 0x09);
        put_native<uint8_t>(destination, 0);
        put_native<int8_t>(destination, 0);
        put_native<uint8_t>(destination, 0);
        put_native<uint16_t>(destination, 0);
        if (plan.point_format == 1 ||
            plan.point_format == 3)
            put_native<double>(destination, 0.0);
    } else {
        put_native<uint8_t>(destination, 0x11);
        put_native<uint8_t>(destination, 0);
        put_native<uint8_t>(destination, 0);
        put_native<uint8_t>(destination, 0);
        put_native<int16_t>(destination, 0);
        put_native<uint16_t>(destination, 0);
        put_native<double>(destination, 0.0);
    }
    if (plan.color) {
        put_native<uint16_t>(
            destination, cloud.rgb16[row * 3]);
        put_native<uint16_t>(
            destination, cloud.rgb16[row * 3 + 1]);
        put_native<uint16_t>(
            destination, cloud.rgb16[row * 3 + 2]);
    }
    if (plan.point_format == 8)
        put_native<uint16_t>(destination, 0);
    if (static_cast<size_t>(
            destination - record.data()) !=
        plan.record_length)
        throw std::logic_error(
            "laz: internal point-record size mismatch");
    return record;
}

class DirectSinkStreambuf : public std::streambuf {
public:
    DirectSinkStreambuf() {
        buffer_.reserve(kSinkBufferSize);
    }
    ~DirectSinkStreambuf() override {
        try {
            flush();
        } catch (...) {
        }
    }

protected:
    std::streamsize xsputn(
        const char *source,
        std::streamsize count) override {
        if (count <= 0) return 0;
        size_t remaining =
            static_cast<size_t>(count);
        while (remaining != 0) {
            if (buffer_.empty() &&
                remaining >= kSinkBufferSize) {
                nb::gil_scoped_acquire acquire;
                if (!emit_file_chunk(
                        source, kSinkBufferSize))
                    throw std::logic_error(
                        "LAZ direct sink disappeared");
                source += kSinkBufferSize;
                remaining -= kSinkBufferSize;
                continue;
            }
            const size_t amount = std::min(
                remaining,
                kSinkBufferSize - buffer_.size());
            buffer_.insert(
                buffer_.end(), source, source + amount);
            source += amount;
            remaining -= amount;
            if (buffer_.size() == kSinkBufferSize)
                flush();
        }
        return count;
    }

    int_type overflow(int_type character) override {
        if (traits_type::eq_int_type(
                character, traits_type::eof()))
            return traits_type::not_eof(character);
        const char value =
            traits_type::to_char_type(character);
        if (xsputn(&value, 1) != 1)
            return traits_type::eof();
        return character;
    }

    int sync() override {
        flush();
        return 0;
    }

    pos_type seekoff(
        off_type offset, std::ios_base::seekdir direction,
        std::ios_base::openmode mode) override {
        if ((mode & std::ios_base::out) == 0)
            return pos_type(off_type(-1));
        flush();
        int origin;
        if (direction == std::ios_base::beg)
            origin = SEEK_SET;
        else if (direction == std::ios_base::cur)
            origin = SEEK_CUR;
        else if (direction == std::ios_base::end)
            origin = SEEK_END;
        else
            return pos_type(off_type(-1));
        nb::gil_scoped_acquire acquire;
        return pos_type(seek_file_sink(offset, origin));
    }

    pos_type seekpos(
        pos_type position,
        std::ios_base::openmode mode) override {
        return seekoff(
            static_cast<off_type>(position),
            std::ios_base::beg, mode);
    }

private:
    void flush() {
        if (buffer_.empty()) return;
        nb::gil_scoped_acquire acquire;
        if (!emit_file_chunk(
                buffer_.data(), buffer_.size()))
            throw std::logic_error(
                "LAZ direct sink disappeared");
        buffer_.clear();
    }

    std::vector<char> buffer_;
};

class BasicLazWriter final
    : public lazperf::writer::basic_file {
public:
    BasicLazWriter() = default;
    ~BasicLazWriter() override = default;
};

template <typename T>
void write_little(std::ostream &output, T value) {
    static_assert(std::is_unsigned_v<T>);
    std::array<char, sizeof(T)> bytes{};
    for (size_t index = 0; index < sizeof(T); ++index)
        bytes[index] = static_cast<char>(
            (value >> (index * 8)) & 0xffU);
    output.write(bytes.data(), bytes.size());
}

void patch_header(
    std::ostream &output, const LazWritePlan &plan,
    size_t count) {
    const std::streampos end = output.tellp();
    output.seekp(6);
    write_little<uint16_t>(output, 0);
    if (plan.version_minor >= 4) {
        output.seekp(107);
        for (size_t index = 0; index < 6; ++index)
            write_little<uint32_t>(output, 0);
        output.seekp(255);
        write_little<uint64_t>(
            output, static_cast<uint64_t>(count));
    } else {
        output.seekp(111);
        write_little<uint32_t>(
            output, static_cast<uint32_t>(count));
    }
    output.seekp(end);
}

void write_empty_laz(
    std::ostream &output, const PointCloud &cloud,
    const LazWritePlan &plan) {
    lazperf::header14 header;
    header.version.minor = plan.version_minor;
    header.global_encoding = 0;
    header.header_size = static_cast<uint16_t>(
        required_header_size(plan.version_minor));
    lazperf::laz_vlr vlr(
        plan.point_format, 0,
        lazperf::DefaultChunkSize);
    header.vlr_count = 1;
    header.point_offset = static_cast<uint32_t>(
        header.header_size +
        lazperf::vlr_header::Size + vlr.size());
    header.point_format_id =
        static_cast<uint8_t>(
            plan.point_format | 0x80U);
    header.point_record_length =
        plan.record_length;
    header.scale = lazperf::vector3(
        plan.scale, plan.scale, plan.scale);
    header.offset = lazperf::vector3(
        cloud.origin[0], cloud.origin[1],
        cloud.origin[2]);
    header.minx = header.maxx = cloud.origin[0];
    header.miny = header.maxy = cloud.origin[1];
    header.minz = header.maxz = cloud.origin[2];
    if (plan.version_minor >= 4)
        header.write(output);
    else
        static_cast<const lazperf::header12 &>(
            header).write(output);
    vlr.header().write(output);
    vlr.write(output);
    const uint64_t table_offset =
        static_cast<uint64_t>(header.point_offset) + 8;
    write_little<uint64_t>(output, table_offset);
    write_little<uint32_t>(output, 0);
    write_little<uint32_t>(output, 0);
}

void encode_laz(
    std::ostream &output, const PointCloud &cloud,
    const LazWritePlan &plan) {
    if (cloud.n == 0) {
        write_empty_laz(output, cloud, plan);
        return;
    }
    lazperf::header12 header;
    header.version.minor = plan.version_minor;
    header.global_encoding = 0;
    header.point_format_id = plan.point_format;
    header.point_record_length =
        plan.record_length;
    header.scale = lazperf::vector3(
        plan.scale, plan.scale, plan.scale);
    header.offset = lazperf::vector3(
        cloud.origin[0], cloud.origin[1],
        cloud.origin[2]);
    header.minx = plan.bounds.min[0];
    header.maxx = plan.bounds.max[0];
    header.miny = plan.bounds.min[1];
    header.maxy = plan.bounds.max[1];
    header.minz = plan.bounds.min[2];
    header.maxz = plan.bounds.max[2];
    header.points_by_return[0] =
        static_cast<uint32_t>(cloud.n);

    BasicLazWriter writer;
    if (!writer.open(
            output, header,
            lazperf::DefaultChunkSize))
        throw std::invalid_argument(
            "laz: LAZperf refused the output header");
    for (size_t row = 0; row < cloud.n; ++row) {
        const std::array<char, 38> record =
            make_point_record(cloud, plan, row);
        writer.writePoint(record.data());
    }
    writer.close();
    patch_header(output, plan, cloud.n);
}

nb::bytes write_laz(
    const PointCloud &cloud, double scale,
    int point_format, size_t lanes) {
    const LazWritePlan plan =
        make_write_plan(
            cloud, scale, point_format, lanes);
    const bool streaming =
        active_file_sink != nullptr;
    std::string encoded;
    {
        nb::gil_scoped_release release;
        try {
            if (streaming) {
                DirectSinkStreambuf buffer;
                std::ostream output(&buffer);
                output.exceptions(
                    std::ios::badbit |
                    std::ios::failbit);
                encode_laz(output, cloud, plan);
                output.flush();
            } else {
                std::ostringstream output(
                    std::ios::binary |
                    std::ios::in |
                    std::ios::out);
                output.exceptions(
                    std::ios::badbit |
                    std::ios::failbit);
                encode_laz(output, cloud, plan);
                encoded = output.str();
            }
        } catch (const lazperf::error &error) {
            throw std::invalid_argument(
                std::string("laz: compression failed: ") +
                error.what());
        }
    }
    if (streaming)
        return nb::bytes("", 0);
    return nb::bytes(encoded.data(), encoded.size());
}

}  // namespace

void register_laz(nb::module_ &module) {
    module.def(
        "read_laz", &read_laz, "data"_a,
        "_lanes"_a = 0,
        "Decode LASzip-compatible LAZ point formats 0-3 and 6-8 "
        "into PointCloud XYZ/intensity/RGB16. The container is "
        "preflighted and chunk callbacks are input-bounded.");
    module.def(
        "read_laz_points", &read_laz_points,
        "data"_a, "start"_a, "stop"_a,
        "_lanes"_a = 0,
        "Decode a non-empty half-open LAZ point range by "
        "decompressing only overlapping chunks.");
    module.def(
        "write_laz", &write_laz, "cloud"_a,
        "scale"_a = 0.001,
        "_point_format"_a = -1,
        "_lanes"_a = 0,
        "Encode a PointCloud as LAZ. The public default chooses "
        "point format 0 or 2; the private point-format seam covers "
        "0-3 and 6-8 for parity. Direct file sinks stream compressed "
        "chunks and seek only for required header/table patches.");
}
