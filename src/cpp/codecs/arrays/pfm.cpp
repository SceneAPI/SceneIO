// PFM codec (Tier-1 float depth/disparity container, formats_survey.md §6).
#include "io/common.hpp"

#include <charconv>
#include <cmath>
#include <limits>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>

#include "records/depth_map.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

float bswap32f(float f) {
    uint32_t u;
    std::memcpy(&u, &f, 4);
    u = (u >> 24) | ((u >> 8) & 0x0000ff00u) | ((u << 8) & 0x00ff0000u) | (u << 24);
    float r;
    std::memcpy(&r, &u, 4);
    return r;
}
bool is_ws(uint8_t c) { return c == ' ' || c == '\n' || c == '\r' || c == '\t'; }
std::string next_token(const uint8_t *p, size_t n, size_t &pos) {
    while (pos < n && is_ws(p[pos])) pos++;
    size_t s = pos;
    while (pos < n && !is_ws(p[pos])) {
        if (pos - s >= 1024 * 1024)
            throw std::invalid_argument(
                "PFM: metadata token exceeds 1 MiB");
        pos++;
    }
    return std::string(reinterpret_cast<const char *>(p + s), pos - s);
}

size_t positive_dimension(const std::string &token) {
    if (token.empty())
        throw std::invalid_argument("dimension");
    size_t value = 0;
    const char *begin = token.data(), *end = begin + token.size();
    const auto parsed = std::from_chars(begin, end, value);
    if (parsed.ec != std::errc{} || parsed.ptr != end || value == 0)
        throw std::invalid_argument("dimension");
    return value;
}

struct PfmInfo {
    size_t width;
    size_t height;
    size_t channels;
    size_t row;
    size_t count;
    size_t data_ofs;
    bool swap;
    double header_scale;
};

PfmInfo parse_pfm(const uint8_t *p, size_t n) {
    size_t pos = 0;
    const std::string magic = next_token(p, n, pos);
    int C;
    if (magic == "PF") C = 3;
    else if (magic == "Pf") C = 1;
    else throw std::invalid_argument("PFM: bad magic (expected 'PF' or 'Pf')");
    size_t width, height;
    double scale;
    try {
        width = positive_dimension(next_token(p, n, pos));
        height = positive_dimension(next_token(p, n, pos));
        const std::string scale_token = next_token(p, n, pos);
        size_t consumed = 0;
        scale = std::stod(scale_token, &consumed);
        if (consumed != scale_token.size())
            throw std::invalid_argument("scale");
    } catch (const std::exception &) {
        throw std::invalid_argument("PFM: malformed header (width/height/scale)");
    }
    if (!std::isfinite(scale) || scale == 0.0)
        throw std::invalid_argument("PFM: scale must be finite and nonzero");
    const bool file_le = std::signbit(scale);
    if (pos < n && is_ws(p[pos])) pos++;
    if (width > std::numeric_limits<size_t>::max() / static_cast<size_t>(C))
        throw std::invalid_argument("PFM: dimensions overflow address space");
    const size_t row = width * static_cast<size_t>(C);
    if (height > std::numeric_limits<size_t>::max() / row)
        throw std::invalid_argument("PFM: dimensions overflow address space");
    const size_t count = row * height;
    if (count > (n - pos) / sizeof(float))
        throw std::invalid_argument("PFM: truncated pixel data");
    return {width, height, static_cast<size_t>(C), row, count, pos,
            file_le != host_is_le(), scale};
}

std::vector<float> copy_pfm(const uint8_t *p, const PfmInfo &info) {
    std::vector<float> buf(info.count);
    const uint8_t *src = p + info.data_ofs;
    for (size_t y = 0; y < info.height; y++) {  // PFM rows are bottom-to-top -> flip
        const uint8_t *sr =
            src + (info.height - 1 - y) * info.row * sizeof(float);
        float *dr = buf.data() + y * info.row;
        std::memcpy(dr, sr, info.row * sizeof(float));
        if (info.swap)
            for (size_t i = 0; i < info.row; i++) dr[i] = bswap32f(dr[i]);
    }
    return buf;
}

void require_typed_pfm(const PfmInfo &info) {
    if (info.channels != 1)
        throw std::invalid_argument(
            "PFM depth: expected a one-channel 'Pf' payload");
    if (std::abs(info.header_scale) != 1.0)
        throw std::invalid_argument(
            "PFM depth: header scale magnitude must be exactly 1.0; "
            "depth semantics belong in DepthEncoding");
}

void require_depth_encoding(const std::string &unit, double scale_to_meters,
                            const std::string &invalid_policy) {
    if (!depth_map_valid_unit(unit))
        throw std::invalid_argument(
            "PFM depth: unit must be "
            "meters|millimeters|custom|unitless|unknown");
    if (!depth_map_unit_scale_consistent(unit, scale_to_meters))
        throw std::invalid_argument(
            "PFM depth: unit/scale_to_meters mismatch");
    if (!depth_map_valid_invalid_policy(invalid_policy))
        throw std::invalid_argument(
            "PFM depth: invalid_policy must be "
            "none|zero|nonfinite|negative");
}

DepthMap make_pfm_depth(std::vector<float> values, size_t height, size_t width,
                        const std::string &unit, double scale_to_meters,
                        const std::string &invalid_policy) {
    require_depth_encoding(unit, scale_to_meters, invalid_policy);
    DepthMap result;
    result.height = height;
    result.width = width;
    result.depth = std::move(values);
    result.unit = unit;
    result.scale_to_meters = scale_to_meters;
    result.invalid_policy = invalid_policy;
    return result;
}

size_t checked_pfm_count(size_t height, size_t width, size_t channels) {
    if (height < 1 || width < 1)
        throw std::invalid_argument("PFM: non-positive dimensions");
    constexpr size_t max_size = std::numeric_limits<size_t>::max();
    if (channels == 0 || width > max_size / channels)
        throw std::invalid_argument("PFM: dimensions overflow address space");
    const size_t row = width * channels;
    if (height > max_size / row)
        throw std::invalid_argument("PFM: dimensions overflow address space");
    const size_t count = height * row;
    if (count > max_size / sizeof(float))
        throw std::invalid_argument("PFM: dimensions overflow address space");
    return count;
}

std::string encode_pfm(const float *source, size_t height, size_t width,
                       size_t channels) {
    const size_t count = checked_pfm_count(height, width, channels);
    const size_t row = width * channels;
    std::string out;
    out.append(channels == 3 ? "PF\n" : "Pf\n");
    out.append(std::to_string(width))
        .append(" ")
        .append(std::to_string(height))
        .append("\n-1.0\n");
    if (out.size() > std::numeric_limits<size_t>::max() - count * sizeof(float))
        throw std::invalid_argument("PFM: output size overflows address space");
    out.reserve(out.size() + count * sizeof(float));
    const bool swap = !host_is_le();
    std::vector<float> temporary;
    if (swap) temporary.resize(row);
    for (size_t y = 0; y < height; ++y) {
        const float *input =
            source + (height - 1 - y) * row;  // write bottom-to-top
        if (swap) {
            for (size_t index = 0; index < row; ++index)
                temporary[index] = bswap32f(input[index]);
            input = temporary.data();
        }
        out.append(reinterpret_cast<const char *>(input),
                   row * sizeof(float));
    }
    return out;
}

nb::ndarray<nb::numpy, float> read_pfm(nb::handle source) {
    sio::ByteView data(source);
    const uint8_t *p = data.data();
    PfmInfo info;
    std::vector<float> buf;
    {
        nb::gil_scoped_release rel;
        info = parse_pfm(p, data.size());
        buf = copy_pfm(p, info);
    }
    if (info.channels == 1)
        return own_array(std::move(buf), {info.height, info.width});
    return own_array(std::move(buf), {info.height, info.width, 3});
}

DepthMap read_pfm_depth(nb::handle source, const std::string &unit,
                        double scale_to_meters,
                        const std::string &invalid_policy) {
    require_depth_encoding(unit, scale_to_meters, invalid_policy);
    sio::ByteView data(source);
    const uint8_t *bytes = data.data();
    PfmInfo info;
    std::vector<float> values;
    {
        nb::gil_scoped_release release;
        info = parse_pfm(bytes, data.size());
        require_typed_pfm(info);
        values = copy_pfm(bytes, info);
    }
    return make_pfm_depth(std::move(values), info.height, info.width, unit,
                          scale_to_meters, invalid_policy);
}

nb::ndarray<nb::numpy, float> read_pfm_window(
    nb::handle source, size_t row_start, size_t row_stop, size_t col_start,
    size_t col_stop) {
    sio::ByteView data(source);
    const uint8_t *p = data.data();
    PfmInfo info;
    std::vector<float> buf;
    {
        nb::gil_scoped_release rel;
        info = parse_pfm(p, data.size());
        const size_t out_h = checked_half_open_range(
            row_start, row_stop, info.height, "PFM row window");
        const size_t out_w = checked_half_open_range(
            col_start, col_stop, info.width, "PFM column window");
        const size_t out_row = out_w * info.channels;
        buf.resize(out_h * out_row);
        const uint8_t *src = p + info.data_ofs;
        for (size_t y = 0; y < out_h; ++y) {
            const size_t source_y = info.height - 1 - (row_start + y);
            const uint8_t *source_row =
                src + (source_y * info.row + col_start * info.channels) *
                          sizeof(float);
            float *destination = buf.data() + y * out_row;
            std::memcpy(destination, source_row, out_row * sizeof(float));
            if (info.swap)
                for (size_t i = 0; i < out_row; ++i)
                    destination[i] = bswap32f(destination[i]);
        }
    }
    const size_t out_h = row_stop - row_start;
    const size_t out_w = col_stop - col_start;
    if (info.channels == 1)
        return own_array(std::move(buf), {out_h, out_w});
    return own_array(std::move(buf), {out_h, out_w, 3});
}

DepthMap read_pfm_depth_window(
    nb::handle source, size_t row_start, size_t row_stop, size_t col_start,
    size_t col_stop, const std::string &unit, double scale_to_meters,
    const std::string &invalid_policy) {
    require_depth_encoding(unit, scale_to_meters, invalid_policy);
    sio::ByteView data(source);
    const uint8_t *bytes = data.data();
    PfmInfo info;
    std::vector<float> values;
    size_t out_height = 0;
    size_t out_width = 0;
    {
        nb::gil_scoped_release release;
        info = parse_pfm(bytes, data.size());
        require_typed_pfm(info);
        out_height = checked_half_open_range(
            row_start, row_stop, info.height, "PFM depth row window");
        out_width = checked_half_open_range(
            col_start, col_stop, info.width, "PFM depth column window");
        values.resize(out_height * out_width);
        const uint8_t *payload = bytes + info.data_ofs;
        for (size_t y = 0; y < out_height; ++y) {
            const size_t source_y = info.height - 1 - (row_start + y);
            const uint8_t *source_row =
                payload + (source_y * info.width + col_start) * sizeof(float);
            float *destination = values.data() + y * out_width;
            std::memcpy(destination, source_row, out_width * sizeof(float));
            if (info.swap)
                for (size_t index = 0; index < out_width; ++index)
                    destination[index] = bswap32f(destination[index]);
        }
    }
    return make_pfm_depth(std::move(values), out_height, out_width, unit,
                          scale_to_meters, invalid_policy);
}

std::tuple<size_t, size_t, size_t, bool> inspect_pfm(
    nb::handle source) {
    sio::ByteView data(source);
    PfmInfo info;
    {
        nb::gil_scoped_release rel;
        info = parse_pfm(data.data(), data.size());
    }
    const bool file_little_endian = info.swap != host_is_le();
    return {
        info.height,
        info.width,
        info.channels,
        file_little_endian,
    };
}

std::tuple<size_t, size_t, size_t, bool, double, size_t> inspect_pfm_depth(
    nb::handle source) {
    sio::ByteView data(source);
    PfmInfo info;
    {
        nb::gil_scoped_release release;
        info = parse_pfm(data.data(), data.size());
        require_typed_pfm(info);
    }
    const bool file_little_endian = info.swap != host_is_le();
    return {
        info.height,
        info.width,
        info.channels,
        file_little_endian,
        info.header_scale,
        data.size(),
    };
}

nb::bytes write_pfm(nb::ndarray<const float, nb::c_contig, nb::device::cpu> img) {
    const size_t nd = img.ndim();
    size_t height, width, channels;
    if (nd == 2) {
        height = img.shape(0);
        width = img.shape(1);
        channels = 1;
    } else if (nd == 3 && img.shape(2) == 3) {
        height = img.shape(0);
        width = img.shape(1);
        channels = 3;
    } else {
        throw std::invalid_argument("write_pfm: expected float32 (H,W) or (H,W,3)");
    }
    const float *source = img.data();
    std::string out;
    {
        nb::gil_scoped_release release;
        out = encode_pfm(source, height, width, channels);
    }
    return emit_bytes(out.data(), out.size());
}

nb::bytes write_pfm_depth(const DepthMap &depth, const std::string &unit,
                          double scale_to_meters,
                          const std::string &invalid_policy) {
    require_depth_encoding(unit, scale_to_meters, invalid_policy);
    if (depth.unit != unit || depth.scale_to_meters != scale_to_meters ||
        depth.invalid_policy != invalid_policy)
        throw std::invalid_argument(
            "PFM depth: DepthMap metadata does not match DepthEncoding");
    if (depth.has_confidence())
        throw std::invalid_argument(
            "PFM depth: confidence cannot be represented");
    const size_t count = checked_pfm_count(depth.height, depth.width, 1);
    if (depth.depth.size() != count)
        throw std::invalid_argument(
            "PFM depth: DepthMap storage disagrees with its dimensions");
    std::string out;
    {
        nb::gil_scoped_release release;
        out = encode_pfm(depth.depth.data(), depth.height, depth.width, 1);
    }
    return emit_bytes(out.data(), out.size());
}

nb::bytes write_pfm_depth_request(nb::tuple request) {
    if (request.size() != 4)
        throw std::invalid_argument(
            "PFM depth: internal write request must contain four values");
    return write_pfm_depth(
        nb::cast<const DepthMap &>(request[0]),
        nb::cast<std::string>(request[1]),
        nb::cast<double>(request[2]),
        nb::cast<std::string>(request[3]));
}

}  // namespace

void register_pfm(nb::module_ &m) {
    m.def("_inspect_pfm", &inspect_pfm, "data"_a,
          "Return (height, width, channels, little_endian) without decoding pixels.");
    m.def("_inspect_pfm_depth", &inspect_pfm_depth, "data"_a,
          "Validate scalar typed-depth PFM and return "
          "(height, width, channels, little_endian, signed_header_scale, "
          "byte_size).");
    m.def("read_pfm", &read_pfm, "data"_a,
          "Decode PFM bytes to a float32 ndarray (H,W)/(H,W,3), top-to-bottom, native-endian.");
    m.def("read_pfm_depth", &read_pfm_depth, "data"_a, "unit"_a,
          "scale_to_meters"_a, "invalid_policy"_a,
          "Decode a scalar, unit-magnitude PFM into an owning DepthMap using "
          "the caller-supplied external depth encoding.");
    m.def("read_pfm_window", &read_pfm_window, "data"_a, "row_start"_a,
          "row_stop"_a, "column_start"_a, "column_stop"_a,
          "Decode one non-empty half-open PFM pixel window without allocating "
          "the full raster.");
    m.def("read_pfm_depth_window", &read_pfm_depth_window, "data"_a,
          "row_start"_a, "row_stop"_a, "column_start"_a, "column_stop"_a,
          "unit"_a, "scale_to_meters"_a, "invalid_policy"_a,
          "Decode one non-empty scalar PFM depth window into an owning "
          "DepthMap without allocating the full raster.");
    m.def("write_pfm", &write_pfm, "img"_a,
          "Encode a float32 (H,W)/(H,W,3) array (numpy or torch) to PFM bytes (little-endian).");
    m.def("write_pfm_depth", &write_pfm_depth, "depth"_a, "unit"_a,
          "scale_to_meters"_a, "invalid_policy"_a,
          "Encode a scalar DepthMap to deterministic PFM bytes after verifying "
          "that its metadata matches the external DepthEncoding.");
    m.def("_write_pfm_depth_request", &write_pfm_depth_request, "request"_a,
          "Encode the private (DepthMap, unit, scale, invalid_policy) sink request.");
}
