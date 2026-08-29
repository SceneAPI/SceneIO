// Gipuma .dmb scalar depth-map codec. This is not COLMAP's unrelated
// width&height&depth& dense-MVS matrix format.
//
// On-disk layout is little-endian:
//   int32 type (=1), int32 height, int32 width, int32 channels (=1),
//   followed by height*width float32 values in top-to-bottom row-major order.
//
// The wider DMB container can carry multi-channel normal maps. SceneIO's
// `dmb` format is deliberately the scalar DepthMap contract, so channels other
// than one are rejected instead of being flattened or silently discarded.
// DMB stores no metric scale/unit metadata; reads record unknown/0.0 and the
// Gipuma zero-invalid convention, and writes guard those exact conventions.
#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#include "records/depth_map.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kDimCap = 1'000'000;
constexpr uint64_t kPixelCap = 250'000'000;

uint32_t read_u32_le(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

void write_u32_le(uint32_t value, char *out) {
    out[0] = static_cast<char>(value & 0xff);
    out[1] = static_cast<char>((value >> 8) & 0xff);
    out[2] = static_cast<char>((value >> 16) & 0xff);
    out[3] = static_cast<char>((value >> 24) & 0xff);
}

uint32_t bswap32(uint32_t value) {
    return (value >> 24) | ((value >> 8) & 0x0000ff00u) |
           ((value << 8) & 0x00ff0000u) | (value << 24);
}

struct DmbInfo {
    size_t height = 0;
    size_t width = 0;
    size_t count = 0;
};

DmbInfo parse_dmb(const uint8_t *data, size_t size) {
    if (size < 16)
        throw std::invalid_argument(
            "dmb: truncated header (need four little-endian int32 fields)");
    const uint32_t type = read_u32_le(data);
    const uint32_t height = read_u32_le(data + 4);
    const uint32_t width = read_u32_le(data + 8);
    const uint32_t channels = read_u32_le(data + 12);
    if (type != 1)
        throw std::invalid_argument(
            "dmb: unsupported image type (expected float32 type 1)");
    if (height == 0 || width == 0)
        throw std::invalid_argument("dmb: dimensions must be positive");
    if (height > kDimCap || width > kDimCap)
        throw std::invalid_argument("dmb: dimensions exceed the supported limit");
    if (channels != 1)
        throw std::invalid_argument(
            "dmb: only scalar depth maps (channels=1) are supported");
    const uint64_t pixels =
        static_cast<uint64_t>(height) * static_cast<uint64_t>(width);
    if (pixels > kPixelCap)
        throw std::invalid_argument(
            "dmb: pixel count exceeds the supported limit");
    const uint64_t expected = 16 + pixels * sizeof(float);
    if (expected != static_cast<uint64_t>(size))
        throw std::invalid_argument(
            expected > size ? "dmb: truncated float32 payload"
                            : "dmb: trailing bytes after float32 payload");
    return {
        static_cast<size_t>(height),
        static_cast<size_t>(width),
        static_cast<size_t>(pixels),
    };
}

float load_f32_le(const uint8_t *source) {
    uint32_t bits = read_u32_le(source);
    float value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

DepthMap decode_dmb(const uint8_t *data, const DmbInfo &info,
                    size_t row_start, size_t row_stop,
                    size_t col_start, size_t col_stop) {
    checked_half_open_range(row_start, row_stop, info.height, "dmb row range");
    checked_half_open_range(col_start, col_stop, info.width, "dmb column range");
    DepthMap result;
    result.height = row_stop - row_start;
    result.width = col_stop - col_start;
    result.unit = "unknown";
    result.scale_to_meters = 0.0;
    result.invalid_policy = "zero";
    const size_t output_count = result.height * result.width;
    result.depth.resize(output_count);
    const uint8_t *payload = data + 16;
    for (size_t row = 0; row < result.height; ++row) {
        const size_t source_index =
            (row_start + row) * info.width + col_start;
        float *destination = result.depth.data() + row * result.width;
        if (host_is_le()) {
            std::memcpy(destination, payload + source_index * sizeof(float),
                        result.width * sizeof(float));
        } else {
            for (size_t col = 0; col < result.width; ++col)
                destination[col] = load_f32_le(
                    payload + (source_index + col) * sizeof(float));
        }
    }
    return result;
}

DepthMap read_dmb(nb::handle source) {
    ByteView data(source);
    DmbInfo info;
    DepthMap result;
    {
        nb::gil_scoped_release release;
        info = parse_dmb(data.data(), data.size());
        result = decode_dmb(data.data(), info, 0, info.height, 0, info.width);
    }
    return result;
}

DepthMap read_dmb_window(nb::handle source, size_t row_start, size_t row_stop,
                         size_t col_start, size_t col_stop) {
    ByteView data(source);
    DmbInfo info;
    DepthMap result;
    {
        nb::gil_scoped_release release;
        info = parse_dmb(data.data(), data.size());
        result = decode_dmb(data.data(), info, row_start, row_stop, col_start,
                            col_stop);
    }
    return result;
}

nb::tuple inspect_dmb(nb::handle source) {
    ByteView data(source);
    DmbInfo info;
    {
        nb::gil_scoped_release release;
        info = parse_dmb(data.data(), data.size());
    }
    return nb::make_tuple(info.height, info.width, 1, 1);
}

void validate_write(const DepthMap &depth) {
    if (depth.height == 0 || depth.width == 0 ||
        depth.height > kDimCap || depth.width > kDimCap)
        throw std::invalid_argument(
            "dmb: DepthMap dimensions are outside the supported range");
    if (depth.height > kPixelCap / depth.width)
        throw std::invalid_argument(
            "dmb: DepthMap pixel count exceeds the supported limit");
    const size_t count = depth.height * depth.width;
    if (depth.depth.size() != count)
        throw std::invalid_argument(
            "dmb: DepthMap storage disagrees with its dimensions");
    if (depth.has_confidence())
        throw std::invalid_argument(
            "dmb: confidence is not representable in a scalar depth map");
    if (depth.unit != "unknown" || depth.scale_to_meters != 0.0)
        throw std::invalid_argument(
            "dmb: metric unit/scale metadata is not representable");
    if (depth.invalid_policy != "zero")
        throw std::invalid_argument(
            "dmb: writer requires invalid_policy='zero'");
    if (depth.depth_convention != "unspecified")
        throw std::invalid_argument(
            "dmb: depth convention metadata is not representable");
}

nb::bytes write_dmb(const DepthMap &depth) {
    validate_write(depth);
    std::array<char, 16> header{};
    write_u32_le(1, header.data());
    write_u32_le(static_cast<uint32_t>(depth.height), header.data() + 4);
    write_u32_le(static_cast<uint32_t>(depth.width), header.data() + 8);
    write_u32_le(1, header.data() + 12);

    std::vector<uint32_t> swapped;
    const char *payload =
        reinterpret_cast<const char *>(depth.depth.data());
    const size_t payload_size = depth.depth.size() * sizeof(float);
    if (!host_is_le()) {
        swapped.resize(depth.depth.size());
        for (size_t index = 0; index < depth.depth.size(); ++index) {
            uint32_t bits;
            std::memcpy(&bits, &depth.depth[index], sizeof(bits));
            swapped[index] = bswap32(bits);
        }
        payload = reinterpret_cast<const char *>(swapped.data());
    }

    const bool streamed = emit_file_chunk(header.data(), header.size());
    if (streamed) {
        emit_file_chunk(payload, payload_size);
        return nb::bytes("", 0);
    }
    std::string output;
    {
        nb::gil_scoped_release release;
        output.reserve(header.size() + payload_size);
        output.append(header.data(), header.size());
        output.append(payload, payload_size);
    }
    return nb::bytes(output.data(), output.size());
}

}  // namespace

void register_dmb(nb::module_ &m) {
    m.def("_inspect_dmb", &inspect_dmb, "data"_a,
          "Return (height, width, channels, type) from a scalar DMB header.");
    m.def("read_dmb", &read_dmb, "data"_a,
          "Decode a little-endian scalar Gipuma .dmb depth map.");
    m.def("read_dmb_window", &read_dmb_window, "data"_a, "row_start"_a,
          "row_stop"_a, "col_start"_a, "col_stop"_a,
          "Decode one non-empty half-open pixel window from scalar DMB.");
    m.def("write_dmb", &write_dmb, "depth"_a,
          "Encode an unknown-unit, zero-invalid scalar DepthMap as "
          "little-endian Gipuma .dmb bytes or stream it to a file.");
}
