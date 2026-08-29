// Repository-owned codecs for COLMAP dense-MVS files.
//
// Matrices:
//   ASCII width&height&depth& followed by little-endian float32 values.
//   Multi-slice matrices are planar on disk.
// Consistency graphs:
//   the same header with depth=1, followed by signed little-endian int32
//   chunks: column, row, count, image_idx[count].
// Fused visibility:
//   uint64 point_count, then uint32 count + uint32 image_idx[count] per point.
#include <array>
#include <charconv>
#include <cstdint>
#include <cstring>
#include <limits>
#include <optional>
#include <string>
#include <vector>

#include "records/dense_mvs.hpp"
#include "records/depth_map.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kHeaderCap = 96;
constexpr size_t kChunkBytes = 64 * 1024;

size_t checked_add(size_t left, size_t right, const char *what) {
    if (left > std::numeric_limits<size_t>::max() - right)
        throw std::invalid_argument(std::string("colmap_mvs: ") + what +
                                    " overflows address space");
    return left + right;
}

size_t checked_mul(size_t left, size_t right, const char *what) {
    if (left != 0 &&
        right > std::numeric_limits<size_t>::max() / left)
        throw std::invalid_argument(std::string("colmap_mvs: ") + what +
                                    " overflows address space");
    return left * right;
}

uint32_t load_u32_le(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

uint64_t load_u64_le(const uint8_t *data) {
    uint64_t value = 0;
    for (size_t index = 0; index < 8; ++index)
        value |= static_cast<uint64_t>(data[index]) << (index * 8);
    return value;
}

int32_t load_i32_le(const uint8_t *data) {
    const uint32_t bits = load_u32_le(data);
    int32_t value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

float load_f32_le(const uint8_t *data) {
    const uint32_t bits = load_u32_le(data);
    float value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

void store_u32_le(uint32_t value, char *data) {
    data[0] = static_cast<char>(value & 0xff);
    data[1] = static_cast<char>((value >> 8) & 0xff);
    data[2] = static_cast<char>((value >> 16) & 0xff);
    data[3] = static_cast<char>((value >> 24) & 0xff);
}

void store_u64_le(uint64_t value, char *data) {
    for (size_t index = 0; index < 8; ++index)
        data[index] = static_cast<char>((value >> (index * 8)) & 0xff);
}

void store_f32_le(float value, char *data) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    store_u32_le(bits, data);
}

struct MatrixInfo {
    size_t width = 0;
    size_t height = 0;
    size_t depth = 0;
    size_t header_size = 0;
    size_t pixels = 0;
};

uint64_t parse_decimal(const uint8_t *data, size_t size, size_t &position,
                       const char *what) {
    if (position >= size || data[position] < '0' || data[position] > '9')
        throw std::invalid_argument(std::string("colmap_mvs: ") + what +
                                    " must be an unsigned decimal integer");
    uint64_t value = 0;
    size_t digits = 0;
    while (position < size && data[position] != '&') {
        const uint8_t byte = data[position++];
        if (byte < '0' || byte > '9')
            throw std::invalid_argument(
                std::string("colmap_mvs: invalid byte in ") + what);
        const uint64_t digit = byte - '0';
        if (value > (std::numeric_limits<uint64_t>::max() - digit) / 10)
            throw std::invalid_argument(std::string("colmap_mvs: ") + what +
                                        " overflows uint64");
        value = value * 10 + digit;
        if (++digits > 20)
            throw std::invalid_argument(std::string("colmap_mvs: ") + what +
                                        " is too long");
        if (position > kHeaderCap)
            throw std::invalid_argument(
                "colmap_mvs: matrix header exceeds the supported limit");
    }
    if (position >= size || data[position] != '&')
        throw std::invalid_argument(
            "colmap_mvs: truncated matrix header delimiter");
    ++position;
    return value;
}

MatrixInfo parse_matrix_header(const uint8_t *data, size_t size) {
    size_t position = 0;
    const uint64_t width =
        parse_decimal(data, size, position, "width");
    const uint64_t height =
        parse_decimal(data, size, position, "height");
    const uint64_t depth =
        parse_decimal(data, size, position, "depth");
    if (width == 0 || height == 0 || depth == 0)
        throw std::invalid_argument(
            "colmap_mvs: matrix dimensions must be positive");
    if (width > kColmapMvsDimensionCap ||
        height > kColmapMvsDimensionCap)
        throw std::invalid_argument(
            "colmap_mvs: matrix dimensions exceed the supported limit");
    if (width > kColmapMvsEntryCap / height)
        throw std::invalid_argument(
            "colmap_mvs: matrix pixel count exceeds the supported limit");
    const uint64_t pixels = width * height;
    return {static_cast<size_t>(width),
            static_cast<size_t>(height),
            static_cast<size_t>(depth),
            position,
            static_cast<size_t>(pixels)};
}

MatrixInfo parse_float_matrix(const uint8_t *data, size_t size,
                              size_t expected_depth, const char *format) {
    const MatrixInfo info = parse_matrix_header(data, size);
    if (info.depth != expected_depth)
        throw std::invalid_argument(
            std::string(format) + ": expected matrix depth " +
            std::to_string(expected_depth));
    const uint64_t values =
        static_cast<uint64_t>(info.pixels) * expected_depth;
    const uint64_t expected =
        static_cast<uint64_t>(info.header_size) + values * sizeof(float);
    if (expected != size)
        throw std::invalid_argument(
            std::string(format) +
            (expected > size ? ": truncated float32 payload"
                             : ": trailing bytes after float32 payload"));
    return info;
}

DepthMap decode_depth(const uint8_t *data, const MatrixInfo &info,
                      size_t row_start, size_t row_stop, size_t col_start,
                      size_t col_stop) {
    checked_half_open_range(row_start, row_stop, info.height,
                            "colmap_mvs_depth row range");
    checked_half_open_range(col_start, col_stop, info.width,
                            "colmap_mvs_depth column range");
    DepthMap result;
    result.height = row_stop - row_start;
    result.width = col_stop - col_start;
    result.unit = "unknown";
    result.scale_to_meters = 0.0;
    result.invalid_policy = "nonpositive";
    result.depth_convention = "camera_z";
    result.depth.resize(result.height * result.width);
    const uint8_t *payload = data + info.header_size;
    for (size_t row = 0; row < result.height; ++row) {
        const size_t source =
            (row_start + row) * info.width + col_start;
        float *destination =
            result.depth.data() + row * result.width;
        if (host_is_le()) {
            std::memcpy(destination, payload + source * sizeof(float),
                        result.width * sizeof(float));
        } else {
            for (size_t column = 0; column < result.width; ++column)
                destination[column] =
                    load_f32_le(payload +
                                (source + column) * sizeof(float));
        }
    }
    return result;
}

NormalMap decode_normal(const uint8_t *data, const MatrixInfo &info,
                        size_t row_start, size_t row_stop, size_t col_start,
                        size_t col_stop) {
    checked_half_open_range(row_start, row_stop, info.height,
                            "colmap_mvs_normal row range");
    checked_half_open_range(col_start, col_stop, info.width,
                            "colmap_mvs_normal column range");
    NormalMap result;
    result.height = row_stop - row_start;
    result.width = col_stop - col_start;
    result.normals.resize(result.height * result.width * 3);
    const uint8_t *payload = data + info.header_size;
    for (size_t row = 0; row < result.height; ++row) {
        for (size_t column = 0; column < result.width; ++column) {
            const size_t source_pixel =
                (row_start + row) * info.width + col_start + column;
            const size_t destination_pixel =
                (row * result.width + column) * 3;
            for (size_t component = 0; component < 3; ++component) {
                const uint8_t *source =
                    payload +
                    (component * info.pixels + source_pixel) *
                        sizeof(float);
                if (host_is_le())
                    std::memcpy(
                        &result.normals[destination_pixel + component],
                        source, sizeof(float));
                else
                    result.normals[destination_pixel + component] =
                        load_f32_le(source);
            }
        }
    }
    return result;
}

DepthMap read_depth(nb::handle source) {
    ByteView bytes(source);
    DepthMap result;
    {
        nb::gil_scoped_release release;
        const MatrixInfo info =
            parse_float_matrix(bytes.data(), bytes.size(), 1,
                               "colmap_mvs_depth");
        result = decode_depth(bytes.data(), info, 0, info.height, 0,
                              info.width);
    }
    return result;
}

DepthMap read_depth_window(nb::handle source, size_t row_start,
                           size_t row_stop, size_t col_start,
                           size_t col_stop) {
    ByteView bytes(source);
    DepthMap result;
    {
        nb::gil_scoped_release release;
        const MatrixInfo info =
            parse_float_matrix(bytes.data(), bytes.size(), 1,
                               "colmap_mvs_depth");
        result = decode_depth(bytes.data(), info, row_start, row_stop,
                              col_start, col_stop);
    }
    return result;
}

NormalMap read_normal(nb::handle source) {
    ByteView bytes(source);
    NormalMap result;
    {
        nb::gil_scoped_release release;
        const MatrixInfo info =
            parse_float_matrix(bytes.data(), bytes.size(), 3,
                               "colmap_mvs_normal");
        result = decode_normal(bytes.data(), info, 0, info.height, 0,
                               info.width);
    }
    return result;
}

NormalMap read_normal_window(nb::handle source, size_t row_start,
                             size_t row_stop, size_t col_start,
                             size_t col_stop) {
    ByteView bytes(source);
    NormalMap result;
    {
        nb::gil_scoped_release release;
        const MatrixInfo info =
            parse_float_matrix(bytes.data(), bytes.size(), 3,
                               "colmap_mvs_normal");
        result = decode_normal(bytes.data(), info, row_start, row_stop,
                               col_start, col_stop);
    }
    return result;
}

nb::tuple inspect_float_matrix(nb::handle source, size_t expected_depth,
                               const char *format) {
    ByteView bytes(source);
    MatrixInfo info;
    {
        nb::gil_scoped_release release;
        info = parse_float_matrix(bytes.data(), bytes.size(),
                                  expected_depth, format);
    }
    return nb::make_tuple(info.height, info.width, info.depth);
}

nb::tuple inspect_depth(nb::handle source) {
    return inspect_float_matrix(source, 1, "colmap_mvs_depth");
}

nb::tuple inspect_normal(nb::handle source) {
    return inspect_float_matrix(source, 3, "colmap_mvs_normal");
}

struct GraphStats {
    size_t entries = 0;
    size_t links = 0;
};

GraphStats scan_consistency(const uint8_t *data, size_t size,
                            const MatrixInfo &info,
                            ConsistencyGraph *output) {
    if (info.depth != 1)
        throw std::invalid_argument(
            "colmap_mvs_consistency: expected matrix depth 1");
    const size_t payload_size = size - info.header_size;
    if (payload_size % sizeof(int32_t) != 0)
        throw std::invalid_argument(
            "colmap_mvs_consistency: truncated int32 payload");
    size_t position = info.header_size;
    GraphStats stats;
    while (position < size) {
        if (size - position < 3 * sizeof(int32_t))
            throw std::invalid_argument(
                "colmap_mvs_consistency: truncated pixel entry");
        const int32_t column = load_i32_le(data + position);
        const int32_t row =
            load_i32_le(data + position + sizeof(int32_t));
        const int32_t count =
            load_i32_le(data + position + 2 * sizeof(int32_t));
        position += 3 * sizeof(int32_t);
        if (column < 0 || row < 0 || count < 0)
            throw std::invalid_argument(
                "colmap_mvs_consistency: coordinates and counts must be "
                "non-negative");
        if (static_cast<uint64_t>(column) >= info.width ||
            static_cast<uint64_t>(row) >= info.height)
            throw std::invalid_argument(
                "colmap_mvs_consistency: pixel coordinate is outside the "
                "raster");
        const uint64_t count_bytes =
            static_cast<uint64_t>(count) * sizeof(int32_t);
        if (count_bytes > size - position)
            throw std::invalid_argument(
                "colmap_mvs_consistency: truncated image-index list");
        if (static_cast<uint64_t>(stats.links) +
                static_cast<uint64_t>(count) >
            kColmapMvsListValueCap)
            throw std::invalid_argument(
                "colmap_mvs_consistency: image-index count exceeds the "
                "supported limit");
        if (output) {
            output->columns.push_back(static_cast<uint32_t>(column));
            output->rows.push_back(static_cast<uint32_t>(row));
        }
        for (int32_t index = 0; index < count; ++index) {
            const int32_t image = load_i32_le(data + position);
            position += sizeof(int32_t);
            if (image < 0)
                throw std::invalid_argument(
                    "colmap_mvs_consistency: image indices must be "
                    "non-negative");
            if (output)
                output->image_indices.push_back(
                    static_cast<uint32_t>(image));
        }
        ++stats.entries;
        stats.links += static_cast<size_t>(count);
        if (stats.entries > kColmapMvsEntryCap)
            throw std::invalid_argument(
                "colmap_mvs_consistency: entry count exceeds the supported "
                "limit");
        if (output)
            output->offsets.push_back(output->image_indices.size());
    }
    return stats;
}

ConsistencyGraph read_consistency(nb::handle source) {
    ByteView bytes(source);
    ConsistencyGraph result;
    {
        nb::gil_scoped_release release;
        const MatrixInfo info =
            parse_matrix_header(bytes.data(), bytes.size());
        const GraphStats stats =
            scan_consistency(bytes.data(), bytes.size(), info, nullptr);
        result.height = info.height;
        result.width = info.width;
        result.rows.reserve(stats.entries);
        result.columns.reserve(stats.entries);
        result.offsets.reserve(
            checked_add(stats.entries, 1, "consistency offsets"));
        result.image_indices.reserve(stats.links);
        result.offsets.push_back(0);
        scan_consistency(bytes.data(), bytes.size(), info, &result);
    }
    return result;
}

nb::tuple inspect_consistency(nb::handle source) {
    ByteView bytes(source);
    MatrixInfo info;
    GraphStats stats;
    {
        nb::gil_scoped_release release;
        info = parse_matrix_header(bytes.data(), bytes.size());
        stats =
            scan_consistency(bytes.data(), bytes.size(), info, nullptr);
    }
    return nb::make_tuple(info.height, info.width, stats.entries,
                          stats.links);
}

struct VisibilityStats {
    size_t points = 0;
    size_t links = 0;
};

VisibilityStats scan_visibility(const uint8_t *data, size_t size,
                                PointVisibility *output) {
    if (size < sizeof(uint64_t))
        throw std::invalid_argument(
            "colmap_fused_visibility: truncated point-count header");
    const uint64_t points = load_u64_le(data);
    if (points > kColmapMvsEntryCap ||
        points > static_cast<uint64_t>(
                     std::numeric_limits<size_t>::max() - 1))
        throw std::invalid_argument(
            "colmap_fused_visibility: point count exceeds the supported "
            "limit");
    size_t position = sizeof(uint64_t);
    size_t links = 0;
    for (uint64_t point = 0; point < points; ++point) {
        if (size - position < sizeof(uint32_t))
            throw std::invalid_argument(
                "colmap_fused_visibility: truncated visibility count");
        const uint32_t count = load_u32_le(data + position);
        position += sizeof(uint32_t);
        const uint64_t count_bytes =
            static_cast<uint64_t>(count) * sizeof(uint32_t);
        if (count_bytes > size - position)
            throw std::invalid_argument(
                "colmap_fused_visibility: truncated image-index list");
        if (static_cast<uint64_t>(links) + count >
            kColmapMvsListValueCap)
            throw std::invalid_argument(
                "colmap_fused_visibility: image-index count exceeds the "
                "supported limit");
        for (uint32_t index = 0; index < count; ++index) {
            const uint32_t image = load_u32_le(data + position);
            position += sizeof(uint32_t);
            if (image >
                static_cast<uint32_t>(
                    std::numeric_limits<int32_t>::max()))
                throw std::invalid_argument(
                    "colmap_fused_visibility: image index exceeds COLMAP's "
                    "non-negative int32 domain");
            if (output) output->image_indices.push_back(image);
        }
        links += count;
        if (output) output->offsets.push_back(output->image_indices.size());
    }
    if (position != size)
        throw std::invalid_argument(
            "colmap_fused_visibility: trailing bytes after visibility "
            "payload");
    return {static_cast<size_t>(points), links};
}

PointVisibility read_visibility(nb::handle source) {
    ByteView bytes(source);
    PointVisibility result;
    {
        nb::gil_scoped_release release;
        const VisibilityStats stats =
            scan_visibility(bytes.data(), bytes.size(), nullptr);
        result.offsets.reserve(
            checked_add(stats.points, 1, "visibility offsets"));
        result.image_indices.reserve(stats.links);
        result.offsets.push_back(0);
        scan_visibility(bytes.data(), bytes.size(), &result);
    }
    return result;
}

nb::tuple inspect_visibility(nb::handle source) {
    ByteView bytes(source);
    VisibilityStats stats;
    {
        nb::gil_scoped_release release;
        stats = scan_visibility(bytes.data(), bytes.size(), nullptr);
    }
    return nb::make_tuple(stats.points, stats.links);
}

std::string matrix_header(size_t width, size_t height, size_t depth) {
    return std::to_string(width) + "&" + std::to_string(height) + "&" +
           std::to_string(depth) + "&";
}

class EncodedOutput {
public:
    explicit EncodedOutput(size_t reserve = 0)
        : streamed_(active_file_sink != nullptr) {
        if (!streamed_) output_.reserve(reserve);
    }

    void append(const char *data, size_t size) {
        if (streamed_) {
            nb::gil_scoped_acquire acquire;
            emit_file_chunk(data, size);
        } else {
            output_.append(data, size);
        }
    }

    nb::bytes finish() {
        if (streamed_) return nb::bytes("", 0);
        return nb::bytes(output_.data(), output_.size());
    }

private:
    bool streamed_;
    std::string output_;
};

void validate_depth_write(const DepthMap &depth) {
    if (depth.height == 0 || depth.width == 0 ||
        depth.height > kColmapMvsDimensionCap ||
        depth.width > kColmapMvsDimensionCap ||
        depth.height > kColmapMvsEntryCap / depth.width)
        throw std::invalid_argument(
            "colmap_mvs_depth: dimensions exceed the supported range");
    if (depth.depth.size() != depth.height * depth.width)
        throw std::invalid_argument(
            "colmap_mvs_depth: record storage disagrees with its dimensions");
    if (depth.has_confidence())
        throw std::invalid_argument(
            "colmap_mvs_depth: confidence is not representable");
    if (depth.unit != "unknown" || depth.scale_to_meters != 0.0)
        throw std::invalid_argument(
            "colmap_mvs_depth: metric unit/scale metadata is not "
            "representable");
    if (depth.invalid_policy != "nonpositive")
        throw std::invalid_argument(
            "colmap_mvs_depth: writer requires "
            "invalid_policy='nonpositive'");
    if (depth.depth_convention != "camera_z")
        throw std::invalid_argument(
            "colmap_mvs_depth: writer requires "
            "depth_convention='camera_z'");
}

nb::bytes write_depth(const DepthMap &depth) {
    std::optional<EncodedOutput> output;
    {
        nb::gil_scoped_release release;
        validate_depth_write(depth);
        const std::string header =
            matrix_header(depth.width, depth.height, 1);
        const size_t payload_size = checked_mul(
            depth.depth.size(), sizeof(float), "depth payload");
        output.emplace(
            checked_add(header.size(), payload_size, "depth output"));
        output->append(header.data(), header.size());
        if (host_is_le()) {
            output->append(
                reinterpret_cast<const char *>(depth.depth.data()),
                payload_size);
        } else {
            std::array<char, sizeof(float)> bytes{};
            for (float value : depth.depth) {
                store_f32_le(value, bytes.data());
                output->append(bytes.data(), bytes.size());
            }
        }
    }
    return output->finish();
}

void validate_normal_write(const NormalMap &normal) {
    if (normal.height == 0 || normal.width == 0 ||
        normal.height > kColmapMvsDimensionCap ||
        normal.width > kColmapMvsDimensionCap ||
        normal.height > kColmapMvsEntryCap / normal.width)
        throw std::invalid_argument(
            "colmap_mvs_normal: dimensions exceed the supported range");
    const size_t pixels = normal.height * normal.width;
    if (pixels > std::numeric_limits<size_t>::max() / 3 ||
        normal.normals.size() != pixels * 3)
        throw std::invalid_argument(
            "colmap_mvs_normal: record storage disagrees with its dimensions");
}

nb::bytes write_normal(const NormalMap &normal) {
    std::optional<EncodedOutput> output;
    {
        nb::gil_scoped_release release;
        validate_normal_write(normal);
        const size_t pixels =
            checked_mul(normal.height, normal.width, "normal pixel count");
        const std::string header =
            matrix_header(normal.width, normal.height, 3);
        const size_t payload_size = checked_mul(
            checked_mul(pixels, 3, "normal value count"),
            sizeof(float), "normal payload");
        output.emplace(
            checked_add(header.size(), payload_size, "normal output"));
        output->append(header.data(), header.size());
        std::vector<char> chunk;
        chunk.reserve(kChunkBytes);
        for (size_t component = 0; component < 3; ++component) {
            for (size_t row_index = 0; row_index < normal.height;
                 ++row_index) {
                for (size_t column = 0; column < normal.width; ++column) {
                    const float value =
                        normal.normals[
                            (row_index * normal.width + column) * 3 +
                            component];
                    const size_t offset = chunk.size();
                    chunk.resize(offset + sizeof(float));
                    store_f32_le(value, chunk.data() + offset);
                    if (chunk.size() >= kChunkBytes) {
                        output->append(chunk.data(), chunk.size());
                        chunk.clear();
                    }
                }
            }
        }
        if (!chunk.empty())
            output->append(chunk.data(), chunk.size());
    }
    return output->finish();
}

void append_u32(std::vector<char> &chunk, uint32_t value,
                EncodedOutput &output) {
    const size_t offset = chunk.size();
    chunk.resize(offset + sizeof(uint32_t));
    store_u32_le(value, chunk.data() + offset);
    if (chunk.size() >= kChunkBytes) {
        output.append(chunk.data(), chunk.size());
        chunk.clear();
    }
}

void validate_consistency_write(const ConsistencyGraph &graph) {
    if (graph.height == 0 || graph.width == 0 ||
        graph.height > kColmapMvsDimensionCap ||
        graph.width > kColmapMvsDimensionCap ||
        graph.height > kColmapMvsEntryCap / graph.width)
        throw std::invalid_argument(
            "colmap_mvs_consistency: dimensions exceed the supported range");
    if (graph.rows.size() != graph.columns.size() ||
        graph.offsets.size() != graph.rows.size() + 1 ||
        graph.offsets.empty() || graph.offsets.front() != 0 ||
        graph.offsets.back() != graph.image_indices.size())
        throw std::invalid_argument(
            "colmap_mvs_consistency: record CSR storage is inconsistent");
    if (graph.rows.size() > kColmapMvsEntryCap ||
        graph.image_indices.size() > kColmapMvsListValueCap)
        throw std::invalid_argument(
            "colmap_mvs_consistency: entry or image-index count exceeds the "
            "supported limit");
    for (size_t entry = 0; entry < graph.rows.size(); ++entry) {
        if (graph.rows[entry] >= graph.height ||
            graph.columns[entry] >= graph.width ||
            graph.rows[entry] >
                static_cast<uint32_t>(
                    std::numeric_limits<int32_t>::max()) ||
            graph.columns[entry] >
                static_cast<uint32_t>(
                    std::numeric_limits<int32_t>::max()) ||
            graph.offsets[entry] > graph.offsets[entry + 1] ||
            graph.offsets[entry + 1] - graph.offsets[entry] >
                static_cast<uint64_t>(
                    std::numeric_limits<int32_t>::max()))
            throw std::invalid_argument(
                "colmap_mvs_consistency: record contains an "
                "unrepresentable entry");
    }
    for (uint32_t image : graph.image_indices) {
        if (image >
            static_cast<uint32_t>(
                std::numeric_limits<int32_t>::max()))
            throw std::invalid_argument(
                "colmap_mvs_consistency: image index exceeds COLMAP's "
                "non-negative int32 domain");
    }
}

nb::bytes write_consistency(const ConsistencyGraph &graph) {
    std::optional<EncodedOutput> output;
    {
        nb::gil_scoped_release release;
        validate_consistency_write(graph);
        const std::string header =
            matrix_header(graph.width, graph.height, 1);
        const size_t word_count = checked_add(
            checked_mul(graph.rows.size(), 3,
                        "consistency entry words"),
            graph.image_indices.size(), "consistency word count");
        const size_t payload_size = checked_mul(
            word_count, sizeof(uint32_t), "consistency payload");
        output.emplace(checked_add(
            header.size(), payload_size, "consistency output"));
        output->append(header.data(), header.size());
        std::vector<char> chunk;
        chunk.reserve(kChunkBytes);
        for (size_t entry = 0; entry < graph.rows.size(); ++entry) {
            append_u32(chunk, graph.columns[entry], *output);
            append_u32(chunk, graph.rows[entry], *output);
            append_u32(
                chunk,
                static_cast<uint32_t>(graph.offsets[entry + 1] -
                                      graph.offsets[entry]),
                *output);
            for (uint64_t offset = graph.offsets[entry];
                 offset < graph.offsets[entry + 1]; ++offset)
                append_u32(
                    chunk, graph.image_indices[offset], *output);
        }
        if (!chunk.empty())
            output->append(chunk.data(), chunk.size());
    }
    return output->finish();
}

void validate_visibility_write(const PointVisibility &visibility) {
    if (visibility.offsets.empty() || visibility.offsets.front() != 0 ||
        visibility.offsets.back() != visibility.image_indices.size() ||
        visibility.point_count() > kColmapMvsEntryCap)
        throw std::invalid_argument(
            "colmap_fused_visibility: record CSR storage is inconsistent");
    if (visibility.image_indices.size() > kColmapMvsListValueCap)
        throw std::invalid_argument(
            "colmap_fused_visibility: image-index count exceeds the "
            "supported limit");
    for (size_t point = 0; point < visibility.point_count(); ++point) {
        if (visibility.offsets[point] >
                visibility.offsets[point + 1] ||
            visibility.offsets[point + 1] -
                    visibility.offsets[point] >
                std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "colmap_fused_visibility: one visibility row is "
                "unrepresentable");
    }
    for (uint32_t image : visibility.image_indices) {
        if (image >
            static_cast<uint32_t>(
                std::numeric_limits<int32_t>::max()))
            throw std::invalid_argument(
                "colmap_fused_visibility: image index exceeds COLMAP's "
                "non-negative int32 domain");
    }
}

nb::bytes write_visibility(const PointVisibility &visibility) {
    std::optional<EncodedOutput> output;
    {
        nb::gil_scoped_release release;
        validate_visibility_write(visibility);
        const size_t words = checked_add(
            visibility.point_count(), visibility.image_indices.size(),
            "visibility word count");
        const size_t payload_size = checked_mul(
            words, sizeof(uint32_t), "visibility payload");
        output.emplace(checked_add(
            sizeof(uint64_t), payload_size, "visibility output"));
        std::array<char, sizeof(uint64_t)> header{};
        store_u64_le(visibility.point_count(), header.data());
        output->append(header.data(), header.size());
        std::vector<char> chunk;
        chunk.reserve(kChunkBytes);
        for (size_t point = 0; point < visibility.point_count(); ++point) {
            append_u32(
                chunk,
                static_cast<uint32_t>(visibility.offsets[point + 1] -
                                      visibility.offsets[point]),
                *output);
            for (uint64_t offset = visibility.offsets[point];
                 offset < visibility.offsets[point + 1]; ++offset)
                append_u32(
                    chunk, visibility.image_indices[offset], *output);
        }
        if (!chunk.empty())
            output->append(chunk.data(), chunk.size());
    }
    return output->finish();
}

}  // namespace

void register_colmap_dense_mvs(nb::module_ &m) {
    m.def("_inspect_colmap_mvs_depth", &inspect_depth, "data"_a);
    m.def("read_colmap_mvs_depth", &read_depth, "data"_a);
    m.def("read_colmap_mvs_depth_window", &read_depth_window, "data"_a,
          "row_start"_a, "row_stop"_a, "col_start"_a, "col_stop"_a);
    m.def("write_colmap_mvs_depth", &write_depth, "depth"_a);

    m.def("_inspect_colmap_mvs_normal", &inspect_normal, "data"_a);
    m.def("read_colmap_mvs_normal", &read_normal, "data"_a);
    m.def("read_colmap_mvs_normal_window", &read_normal_window, "data"_a,
          "row_start"_a, "row_stop"_a, "col_start"_a, "col_stop"_a);
    m.def("write_colmap_mvs_normal", &write_normal, "normal"_a);

    m.def("_inspect_colmap_mvs_consistency", &inspect_consistency,
          "data"_a);
    m.def("read_colmap_mvs_consistency", &read_consistency, "data"_a);
    m.def("write_colmap_mvs_consistency", &write_consistency, "graph"_a);

    m.def("_inspect_colmap_fused_visibility", &inspect_visibility,
          "data"_a);
    m.def("read_colmap_fused_visibility", &read_visibility, "data"_a);
    m.def("write_colmap_fused_visibility", &write_visibility,
          "visibility"_a);
}
