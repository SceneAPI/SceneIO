// PlayCanvas/SuperSplat compressed PLY codec.
//
// Format contract pinned against playcanvas/splat-transform at
// 6b07ba05d731eac1163ad4ff1b14e47e5e3f162c:
//   * binary little-endian PLY 1.0;
//   * one `chunk` row per 256 vertices, containing position/scale and
//     optionally RGB min/max values;
//   * four packed uint32 vertex fields (11/10/11 position and scale,
//     largest-three 2/10/10/10 quaternion, and RGBA 8/8/8/8);
//   * optional 9/24/45 byte-quantized channel-grouped SH coefficients.
//
// The format is intentionally lossy. The writer emits the current 18-float
// chunk schema, Morton-orders rows exactly as the reference writer does, and
// refuses non-finite values, zero quaternions, or log scales outside the
// reference's representable [-20, 20] interval instead of silently repairing
// them. The reader also accepts the older 12-float chunk schema whose RGB
// values are direct UNORM8.
#include <nanobind/stl/string.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "io/common.hpp"
#include "records/gaussian_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kChunkSize = 256;
constexpr size_t kHeaderLimit = 1024 * 1024;
constexpr double kShC0 = 0.28209479177387814;
constexpr double kQuaternionRange = 0.70710678118654752440;

enum class Scalar {
    F32,
    U32,
    U8,
};

struct Property {
    Scalar type;
    std::string name;
    size_t offset = 0;
};

struct Element {
    std::string name;
    size_t count = 0;
    size_t stride = 0;
    std::vector<Property> properties;
};

struct Header {
    size_t body = 0;
    std::vector<Element> elements;
};

struct Layout {
    size_t count = 0;
    size_t chunks = 0;
    size_t rest = 0;
    int degree = 0;
    bool chunk_colors = false;
    size_t body = 0;
    size_t chunk_stride = 0;
    size_t vertex_stride = 0;
    size_t sh_stride = 0;
    size_t chunk_bytes = 0;
    size_t vertex_bytes = 0;
    std::unordered_map<std::string, size_t> chunk_offsets;
    std::unordered_map<std::string, size_t> vertex_offsets;
    std::unordered_map<std::string, size_t> sh_offsets;
};

size_t checked_add(size_t a, size_t b, const char *what) {
    if (b > std::numeric_limits<size_t>::max() - a)
        throw std::invalid_argument(std::string("compressed PLY: ") + what +
                                    " overflows address space");
    return a + b;
}

size_t checked_mul(size_t a, size_t b, const char *what) {
    if (a != 0 && b > std::numeric_limits<size_t>::max() / a)
        throw std::invalid_argument(std::string("compressed PLY: ") + what +
                                    " overflows address space");
    return a * b;
}

std::vector<std::string_view> split(std::string_view line) {
    std::vector<std::string_view> result;
    size_t pos = 0;
    while (pos < line.size()) {
        while (pos < line.size() &&
               (line[pos] == ' ' || line[pos] == '\t'))
            ++pos;
        if (pos == line.size()) break;
        const size_t begin = pos;
        while (pos < line.size() && line[pos] != ' ' &&
               line[pos] != '\t')
            ++pos;
        result.push_back(line.substr(begin, pos - begin));
    }
    return result;
}

size_t parse_count(std::string_view token) {
    if (token.empty() ||
        !std::all_of(token.begin(), token.end(),
                     [](unsigned char c) { return c >= '0' && c <= '9'; }))
        throw std::invalid_argument(
            "compressed PLY: malformed element count");
    uint64_t value = 0;
    const auto parsed =
        std::from_chars(token.data(), token.data() + token.size(), value);
    if (parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size() ||
        value > std::numeric_limits<size_t>::max())
        throw std::invalid_argument(
            "compressed PLY: element count exceeds addressable size");
    return static_cast<size_t>(value);
}

std::pair<Scalar, size_t> parse_scalar(std::string_view token) {
    if (token == "float" || token == "float32")
        return {Scalar::F32, 4};
    if (token == "uint" || token == "uint32")
        return {Scalar::U32, 4};
    if (token == "uchar" || token == "uint8")
        return {Scalar::U8, 1};
    throw std::invalid_argument(
        "compressed PLY: unsupported scalar type '" + std::string(token) +
        "'");
}

Header parse_header(const uint8_t *data, size_t size) {
    Header header;
    size_t cursor = 0;
    size_t header_bytes = 0;
    bool saw_format = false;
    Element *current = nullptr;
    std::unordered_set<std::string> element_names;
    std::unordered_set<std::string> property_names;

    auto line = [&]() -> std::string_view {
        if (cursor >= size)
            throw std::invalid_argument(
                "compressed PLY: missing end_header");
        const size_t begin = cursor;
        while (cursor < size && data[cursor] != '\n') {
            if (data[cursor] == 0)
                throw std::invalid_argument(
                    "compressed PLY: NUL byte in header");
            ++cursor;
            if (++header_bytes > kHeaderLimit)
                throw std::invalid_argument(
                    "compressed PLY: header exceeds 1 MiB");
        }
        if (cursor == size)
            throw std::invalid_argument(
                "compressed PLY: unterminated header line");
        ++cursor;
        if (++header_bytes > kHeaderLimit)
            throw std::invalid_argument(
                "compressed PLY: header exceeds 1 MiB");
        size_t end = cursor - 1;
        if (end > begin && data[end - 1] == '\r') --end;
        return std::string_view(
            reinterpret_cast<const char *>(data + begin), end - begin);
    };

    if (line() != "ply")
        throw std::invalid_argument(
            "compressed PLY: missing 'ply' magic");

    while (true) {
        const std::string_view raw = line();
        const auto words = split(raw);
        if (words.empty())
            throw std::invalid_argument(
                "compressed PLY: blank header directive");
        const std::string_view directive = words[0];
        if (directive == "comment" || directive == "obj_info") continue;
        if (directive == "format") {
            if (words.size() != 3 || words[1] != "binary_little_endian" ||
                words[2] != "1.0" || saw_format ||
                !header.elements.empty())
                throw std::invalid_argument(
                    "compressed PLY: requires one leading "
                    "'format binary_little_endian 1.0' declaration");
            saw_format = true;
        } else if (directive == "element") {
            if (words.size() != 3 || !saw_format)
                throw std::invalid_argument(
                    "compressed PLY: malformed or misplaced element");
            std::string name(words[1]);
            if (!element_names.insert(name).second)
                throw std::invalid_argument(
                    "compressed PLY: duplicate element '" + name + "'");
            header.elements.push_back(
                Element{name, parse_count(words[2]), 0, {}});
            current = &header.elements.back();
            property_names.clear();
        } else if (directive == "property") {
            if (!current)
                throw std::invalid_argument(
                    "compressed PLY: property appears before an element");
            if (words.size() != 3)
                throw std::invalid_argument(
                    "compressed PLY: list or malformed properties are "
                    "unsupported");
            const auto [type, bytes] = parse_scalar(words[1]);
            std::string name(words[2]);
            if (name.empty() || !property_names.insert(name).second)
                throw std::invalid_argument(
                    "compressed PLY: empty or duplicate property");
            const size_t offset = current->stride;
            current->stride =
                checked_add(current->stride, bytes, "element stride");
            current->properties.push_back(
                Property{type, std::move(name), offset});
        } else if (directive == "end_header") {
            if (words.size() != 1)
                throw std::invalid_argument(
                    "compressed PLY: malformed end_header");
            break;
        } else {
            throw std::invalid_argument(
                "compressed PLY: unsupported header directive '" +
                std::string(directive) + "'");
        }
    }
    if (!saw_format)
        throw std::invalid_argument(
            "compressed PLY: missing format declaration");
    header.body = cursor;
    return header;
}

std::unordered_map<std::string, size_t> validate_properties(
    const Element &element,
    const std::vector<std::pair<std::string, Scalar>> &expected) {
    if (element.properties.size() != expected.size())
        throw std::invalid_argument(
            "compressed PLY: element '" + element.name +
            "' has an unsupported property count");
    std::unordered_map<std::string, Scalar> expected_types;
    for (const auto &[name, type] : expected)
        expected_types.emplace(name, type);
    std::unordered_map<std::string, size_t> offsets;
    for (const Property &property : element.properties) {
        const auto it = expected_types.find(property.name);
        if (it == expected_types.end() || it->second != property.type)
            throw std::invalid_argument(
                "compressed PLY: element '" + element.name +
                "' has unsupported property '" + property.name + "'");
        offsets.emplace(property.name, property.offset);
    }
    return offsets;
}

Layout validate_layout(const Header &header, size_t size) {
    if (header.elements.size() != 2 && header.elements.size() != 3)
        throw std::invalid_argument(
            "compressed PLY: requires chunk, vertex, and optional sh "
            "elements");
    if (header.elements[0].name != "chunk" ||
        header.elements[1].name != "vertex" ||
        (header.elements.size() == 3 &&
         header.elements[2].name != "sh"))
        throw std::invalid_argument(
            "compressed PLY: elements must be ordered chunk, vertex, "
            "optional sh");

    static const std::vector<std::pair<std::string, Scalar>>
        base_chunk_properties = {
            {"min_x", Scalar::F32},
            {"min_y", Scalar::F32},
            {"min_z", Scalar::F32},
            {"max_x", Scalar::F32},
            {"max_y", Scalar::F32},
            {"max_z", Scalar::F32},
            {"min_scale_x", Scalar::F32},
            {"min_scale_y", Scalar::F32},
            {"min_scale_z", Scalar::F32},
            {"max_scale_x", Scalar::F32},
            {"max_scale_y", Scalar::F32},
            {"max_scale_z", Scalar::F32},
        };
    static const std::vector<std::pair<std::string, Scalar>>
        color_chunk_properties = {
            {"min_r", Scalar::F32},
            {"min_g", Scalar::F32},
            {"min_b", Scalar::F32},
            {"max_r", Scalar::F32},
            {"max_g", Scalar::F32},
            {"max_b", Scalar::F32},
        };
    static const std::vector<std::pair<std::string, Scalar>>
        vertex_properties = {
            {"packed_position", Scalar::U32},
            {"packed_rotation", Scalar::U32},
            {"packed_scale", Scalar::U32},
            {"packed_color", Scalar::U32},
        };

    Layout layout;
    const Element &chunk = header.elements[0];
    const Element &vertex = header.elements[1];
    layout.count = vertex.count;
    layout.chunks =
        layout.count / kChunkSize + (layout.count % kChunkSize != 0);
    if (chunk.count != layout.chunks)
        throw std::invalid_argument(
            "compressed PLY: chunk count does not equal ceil(vertex/256)");

    std::vector<std::pair<std::string, Scalar>> chunk_expected =
        base_chunk_properties;
    if (chunk.properties.size() ==
        base_chunk_properties.size() + color_chunk_properties.size()) {
        chunk_expected.insert(chunk_expected.end(),
                              color_chunk_properties.begin(),
                              color_chunk_properties.end());
        layout.chunk_colors = true;
    } else if (chunk.properties.size() != base_chunk_properties.size()) {
        throw std::invalid_argument(
            "compressed PLY: chunk schema must contain 12 or 18 float "
            "properties");
    }
    layout.chunk_offsets = validate_properties(chunk, chunk_expected);
    layout.vertex_offsets =
        validate_properties(vertex, vertex_properties);
    layout.chunk_stride = chunk.stride;
    layout.vertex_stride = vertex.stride;

    if (header.elements.size() == 3) {
        const Element &sh = header.elements[2];
        if (sh.count != layout.count)
            throw std::invalid_argument(
                "compressed PLY: sh count does not equal vertex count");
        layout.rest = sh.properties.size();
        layout.degree = gc_deg_from_rest(layout.rest);
        if (layout.degree < 1)
            throw std::invalid_argument(
                "compressed PLY: sh element requires exactly 9, 24, or "
                "45 uchar properties");
        std::vector<std::pair<std::string, Scalar>> sh_expected;
        sh_expected.reserve(layout.rest);
        for (size_t i = 0; i < layout.rest; ++i)
            sh_expected.emplace_back("f_rest_" + std::to_string(i),
                                     Scalar::U8);
        layout.sh_offsets = validate_properties(sh, sh_expected);
        layout.sh_stride = sh.stride;
    }

    layout.body = header.body;
    layout.chunk_bytes =
        checked_mul(layout.chunks, layout.chunk_stride, "chunk payload");
    layout.vertex_bytes =
        checked_mul(layout.count, layout.vertex_stride, "vertex payload");
    size_t expected =
        checked_add(layout.body, layout.chunk_bytes, "file size");
    expected = checked_add(expected, layout.vertex_bytes, "file size");
    expected = checked_add(
        expected,
        checked_mul(layout.count, layout.sh_stride, "sh payload"),
        "file size");
    if (expected != size)
        throw std::invalid_argument(
            std::string("compressed PLY: ") +
            (expected > size ? "truncated" : "trailing") +
            " binary payload");
    return layout;
}

uint32_t load_u32_le(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

float load_f32_le(const uint8_t *data) {
    const uint32_t bits = load_u32_le(data);
    float value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

void append_u32_le(std::string &out, uint32_t value) {
    out.push_back(static_cast<char>(value & 0xffu));
    out.push_back(static_cast<char>((value >> 8) & 0xffu));
    out.push_back(static_cast<char>((value >> 16) & 0xffu));
    out.push_back(static_cast<char>((value >> 24) & 0xffu));
}

void append_f32_le(std::string &out, float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    append_u32_le(out, bits);
}

double unpack_unorm(uint32_t value, unsigned int bits) {
    const uint32_t mask = (uint32_t{1} << bits) - 1;
    return static_cast<double>(value & mask) /
           static_cast<double>(mask);
}

std::array<double, 3> unpack_111011(uint32_t value) {
    return {
        unpack_unorm(value >> 21, 11),
        unpack_unorm(value >> 11, 10),
        unpack_unorm(value, 11),
    };
}

std::array<double, 4> unpack_8888(uint32_t value) {
    return {
        unpack_unorm(value >> 24, 8),
        unpack_unorm(value >> 16, 8),
        unpack_unorm(value >> 8, 8),
        unpack_unorm(value, 8),
    };
}

std::array<float, 4> unpack_rotation(uint32_t value) {
    const double a = (unpack_unorm(value >> 20, 10) - 0.5) /
                     kQuaternionRange;
    const double b = (unpack_unorm(value >> 10, 10) - 0.5) /
                     kQuaternionRange;
    const double c = (unpack_unorm(value, 10) - 0.5) /
                     kQuaternionRange;
    const double missing =
        std::sqrt(std::max(0.0, 1.0 - (a * a + b * b + c * c)));
    std::array<float, 4> result{};
    const size_t largest = value >> 30;
    size_t source = 0;
    const std::array<double, 3> stored{a, b, c};
    for (size_t component = 0; component < 4; ++component) {
        result[component] = static_cast<float>(
            component == largest ? missing : stored[source++]);
    }
    return result;
}

double lerp(float low, float high, double value) {
    return static_cast<double>(low) * (1.0 - value) +
           static_cast<double>(high) * value;
}

void validate_chunk_bounds(const uint8_t *data, const Layout &layout) {
    static const std::array<std::pair<const char *, const char *>, 9>
        ranges = {{
            {"min_x", "max_x"},
            {"min_y", "max_y"},
            {"min_z", "max_z"},
            {"min_scale_x", "max_scale_x"},
            {"min_scale_y", "max_scale_y"},
            {"min_scale_z", "max_scale_z"},
            {"min_r", "max_r"},
            {"min_g", "max_g"},
            {"min_b", "max_b"},
        }};
    for (size_t chunk = 0; chunk < layout.chunks; ++chunk) {
        const uint8_t *row =
            data + layout.body + chunk * layout.chunk_stride;
        const size_t range_count = layout.chunk_colors ? ranges.size() : 6;
        for (size_t i = 0; i < range_count; ++i) {
            const auto &[minimum_name, maximum_name] = ranges[i];
            const float minimum =
                load_f32_le(row + layout.chunk_offsets.at(minimum_name));
            const float maximum =
                load_f32_le(row + layout.chunk_offsets.at(maximum_name));
            if (!std::isfinite(minimum) || !std::isfinite(maximum) ||
                minimum > maximum)
                throw std::invalid_argument(
                    "compressed PLY: chunk min/max values must be finite "
                    "and ordered");
            if (i >= 6) {
                const double decoded_minimum =
                    (static_cast<double>(minimum) - 0.5) / kShC0;
                const double decoded_maximum =
                    (static_cast<double>(maximum) - 0.5) / kShC0;
                if (std::abs(decoded_minimum) >
                        std::numeric_limits<float>::max() ||
                    std::abs(decoded_maximum) >
                        std::numeric_limits<float>::max())
                    throw std::invalid_argument(
                        "compressed PLY: chunk color range exceeds "
                        "float32 SH storage");
            }
        }
    }
}

GaussianCloud decode_compressed_ply(const uint8_t *data, size_t size,
                                    bool partial, size_t start,
                                    size_t stop) {
    const Header header = parse_header(data, size);
    const Layout layout = validate_layout(header, size);
    validate_chunk_bounds(data, layout);
    if (!partial) {
        start = 0;
        stop = layout.count;
    } else {
        checked_half_open_range(start, stop, layout.count,
                                "compressed PLY point range");
    }

    const size_t selected = stop - start;
    GaussianCloud cloud;
    cloud.quaternion_norm = "unit";
    cloud.n = selected;
    cloud.num_rest = layout.rest;
    cloud.sh_degree = layout.degree;
    cloud.means.resize(checked_mul(selected, 3, "decoded means"));
    cloud.scales.resize(checked_mul(selected, 3, "decoded scales"));
    cloud.quats.resize(checked_mul(selected, 4, "decoded rotations"));
    cloud.opacity.resize(selected);
    cloud.sh_dc.resize(checked_mul(selected, 3, "decoded DC"));
    cloud.sh_rest.resize(
        checked_mul(selected, layout.rest, "decoded SH"));

    const uint8_t *chunk_data = data + layout.body;
    const uint8_t *vertex_data = chunk_data + layout.chunk_bytes;
    const uint8_t *sh_data = vertex_data + layout.vertex_bytes;
    auto chunk_value = [&](size_t chunk, const char *name) {
        return load_f32_le(
            chunk_data + chunk * layout.chunk_stride +
            layout.chunk_offsets.at(name));
    };
    auto packed_value = [&](size_t row, const char *name) {
        return load_u32_le(
            vertex_data + row * layout.vertex_stride +
            layout.vertex_offsets.at(name));
    };

    for (size_t output = 0; output < selected; ++output) {
        const size_t row = start + output;
        const size_t chunk = row / kChunkSize;
        const auto position =
            unpack_111011(packed_value(row, "packed_position"));
        const auto rotation =
            unpack_rotation(packed_value(row, "packed_rotation"));
        const auto scale =
            unpack_111011(packed_value(row, "packed_scale"));
        const auto color =
            unpack_8888(packed_value(row, "packed_color"));

        static const std::array<const char *, 3> axes{"x", "y", "z"};
        static const std::array<const char *, 3> colors{"r", "g", "b"};
        for (size_t component = 0; component < 3; ++component) {
            const std::string min_position =
                "min_" + std::string(axes[component]);
            const std::string max_position =
                "max_" + std::string(axes[component]);
            cloud.means[output * 3 + component] = static_cast<float>(
                lerp(chunk_value(chunk, min_position.c_str()),
                     chunk_value(chunk, max_position.c_str()),
                     position[component]));

            const std::string min_scale =
                "min_scale_" + std::string(axes[component]);
            const std::string max_scale =
                "max_scale_" + std::string(axes[component]);
            cloud.scales[output * 3 + component] = static_cast<float>(
                lerp(chunk_value(chunk, min_scale.c_str()),
                     chunk_value(chunk, max_scale.c_str()),
                     scale[component]));

            double linear_color = color[component];
            if (layout.chunk_colors) {
                const std::string min_color =
                    "min_" + std::string(colors[component]);
                const std::string max_color =
                    "max_" + std::string(colors[component]);
                linear_color =
                    lerp(chunk_value(chunk, min_color.c_str()),
                         chunk_value(chunk, max_color.c_str()),
                         color[component]);
            }
            cloud.sh_dc[output * 3 + component] =
                static_cast<float>((linear_color - 0.5) /
                                   kShC0);
        }
        for (size_t component = 0; component < 4; ++component)
            cloud.quats[output * 4 + component] = rotation[component];

        const double alpha = color[3];
        if (alpha == 0.0)
            cloud.opacity[output] =
                -std::numeric_limits<float>::infinity();
        else if (alpha == 1.0)
            cloud.opacity[output] =
                std::numeric_limits<float>::infinity();
        else
            cloud.opacity[output] =
                static_cast<float>(std::log(alpha / (1.0 - alpha)));

        for (size_t coefficient = 0; coefficient < layout.rest;
             ++coefficient) {
            const std::string name =
                "f_rest_" + std::to_string(coefficient);
            const uint8_t quantized =
                *(sh_data + row * layout.sh_stride +
                  layout.sh_offsets.at(name));
            const double normalized =
                quantized == 0
                    ? 0.0
                    : quantized == 255
                          ? 1.0
                          : (static_cast<double>(quantized) + 0.5) /
                                256.0;
            cloud.sh_rest[output * layout.rest + coefficient] =
                static_cast<float>((normalized - 0.5) * 8.0);
        }
    }
    return cloud;
}

void validate_cloud(const GaussianCloud &cloud) {
    if (cloud.means.size() != checked_mul(cloud.n, 3, "means") ||
        cloud.scales.size() != checked_mul(cloud.n, 3, "scales") ||
        cloud.quats.size() != checked_mul(cloud.n, 4, "rotations") ||
        cloud.opacity.size() != cloud.n ||
        cloud.sh_dc.size() != checked_mul(cloud.n, 3, "DC") ||
        cloud.sh_rest.size() !=
            checked_mul(cloud.n, cloud.num_rest, "SH") ||
        gc_deg_from_rest(cloud.num_rest) != cloud.sh_degree)
        throw std::invalid_argument(
            "compressed PLY: inconsistent GaussianCloud storage");
    if (cloud.n > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "compressed PLY: reference format is limited to 2^32-1 "
            "vertices");

    for (float value : cloud.means)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "compressed PLY: positions must be finite");
    for (float value : cloud.scales)
        if (!std::isfinite(value) || value < -20.0f || value > 20.0f)
            throw std::invalid_argument(
                "compressed PLY: log scales must be finite and within "
                "[-20, 20]");
    for (float value : cloud.opacity)
        if (std::isnan(value))
            throw std::invalid_argument(
                "compressed PLY: opacities must not be NaN");
    for (float value : cloud.sh_dc)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "compressed PLY: DC coefficients must be finite");
    for (float value : cloud.sh_rest)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "compressed PLY: SH coefficients must be finite");
    for (size_t row = 0; row < cloud.n; ++row) {
        double norm_squared = 0.0;
        for (size_t component = 0; component < 4; ++component) {
            const float value = cloud.quats[row * 4 + component];
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "compressed PLY: quaternions must be finite");
            norm_squared += static_cast<double>(value) * value;
        }
        if (!(norm_squared > 0.0) || !std::isfinite(norm_squared))
            throw std::invalid_argument(
                "compressed PLY: quaternions must have non-zero finite "
                "norm");
    }
}

uint32_t part1_by2(uint32_t value) {
    value &= 0x000003ffu;
    value = (value ^ (value << 16)) & 0xff0000ffu;
    value = (value ^ (value << 8)) & 0x0300f00fu;
    value = (value ^ (value << 4)) & 0x030c30c3u;
    value = (value ^ (value << 2)) & 0x09249249u;
    return value;
}

uint32_t morton3(uint32_t x, uint32_t y, uint32_t z) {
    return (part1_by2(z) << 2) + (part1_by2(y) << 1) +
           part1_by2(x);
}

void refine_morton(const GaussianCloud &cloud, std::vector<uint32_t> &order,
                   size_t begin, size_t end) {
    if (begin == end) return;
    std::array<float, 3> minimum{
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
    };
    std::array<float, 3> maximum{
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
    };
    for (size_t pos = begin; pos < end; ++pos) {
        const size_t row = order[pos];
        for (size_t component = 0; component < 3; ++component) {
            const float value = cloud.means[row * 3 + component];
            minimum[component] =
                std::min(minimum[component], value);
            maximum[component] =
                std::max(maximum[component], value);
        }
    }
    const std::array<double, 3> extent{
        static_cast<double>(maximum[0]) - minimum[0],
        static_cast<double>(maximum[1]) - minimum[1],
        static_cast<double>(maximum[2]) - minimum[2],
    };
    if (extent[0] == 0.0 && extent[1] == 0.0 && extent[2] == 0.0)
        return;

    struct Keyed {
        uint32_t code;
        uint32_t row;
    };
    std::vector<Keyed> keyed;
    keyed.reserve(end - begin);
    for (size_t pos = begin; pos < end; ++pos) {
        const uint32_t row = order[pos];
        std::array<uint32_t, 3> quantized{};
        for (size_t component = 0; component < 3; ++component) {
            if (extent[component] == 0.0) continue;
            const double scaled =
                (static_cast<double>(
                     cloud.means[static_cast<size_t>(row) * 3 +
                                 component]) -
                 minimum[component]) *
                (1024.0 / extent[component]);
            quantized[component] = static_cast<uint32_t>(
                std::min(1023.0, std::max(0.0, std::floor(scaled))));
        }
        keyed.push_back(
            Keyed{morton3(quantized[0], quantized[1], quantized[2]),
                  row});
    }
    std::stable_sort(
        keyed.begin(), keyed.end(),
        [](const Keyed &a, const Keyed &b) { return a.code < b.code; });
    for (size_t i = 0; i < keyed.size(); ++i)
        order[begin + i] = keyed[i].row;

    size_t group_begin = 0;
    while (group_begin < keyed.size()) {
        size_t group_end = group_begin + 1;
        while (group_end < keyed.size() &&
               keyed[group_end].code == keyed[group_begin].code)
            ++group_end;
        if (group_end - group_begin > kChunkSize)
            refine_morton(cloud, order, begin + group_begin,
                          begin + group_end);
        group_begin = group_end;
    }
}

uint32_t pack_unorm(double value, unsigned int bits) {
    const uint32_t maximum = (uint32_t{1} << bits) - 1;
    const double rounded =
        std::floor(value * static_cast<double>(maximum) + 0.5);
    return static_cast<uint32_t>(
        std::max(0.0,
                 std::min(static_cast<double>(maximum), rounded)));
}

double normalize(float value, float minimum, float maximum) {
    if (value <= minimum) return 0.0;
    if (value >= maximum) return 1.0;
    if (static_cast<double>(maximum) - minimum < 0.00001) return 0.0;
    return (static_cast<double>(value) - minimum) /
           (static_cast<double>(maximum) - minimum);
}

uint32_t pack_111011(double x, double y, double z) {
    return (pack_unorm(x, 11) << 21) |
           (pack_unorm(y, 10) << 11) | pack_unorm(z, 11);
}

uint32_t pack_8888(double x, double y, double z, double w) {
    return (pack_unorm(x, 8) << 24) |
           (pack_unorm(y, 8) << 16) |
           (pack_unorm(z, 8) << 8) | pack_unorm(w, 8);
}

uint32_t pack_rotation(const float *source) {
    std::array<double, 4> value{
        source[0], source[1], source[2], source[3]};
    double norm_squared = 0.0;
    for (double component : value)
        norm_squared += component * component;
    const double inverse_norm = 1.0 / std::sqrt(norm_squared);
    for (double &component : value) component *= inverse_norm;

    size_t largest = 0;
    for (size_t component = 1; component < 4; ++component)
        if (std::abs(value[component]) >
            std::abs(value[largest]))
            largest = component;
    if (value[largest] < 0.0)
        for (double &component : value) component = -component;

    uint32_t result = static_cast<uint32_t>(largest);
    for (size_t component = 0; component < 4; ++component) {
        if (component == largest) continue;
        result = (result << 10) |
                 pack_unorm(value[component] * kQuaternionRange + 0.5,
                            10);
    }
    return result;
}

std::string encode_compressed_ply(const GaussianCloud &cloud) {
    validate_cloud(cloud);
    const size_t chunks =
        cloud.n / kChunkSize + (cloud.n % kChunkSize != 0);
    const size_t rest = cloud.num_rest;
    const std::string comment =
        "comment Generated by SceneIO; PlayCanvas compressed PLY "
        "(lossy quantization)\n";
    std::string header =
        "ply\nformat binary_little_endian 1.0\n" + comment +
        "element chunk " + std::to_string(chunks) + "\n"
        "property float min_x\n"
        "property float min_y\n"
        "property float min_z\n"
        "property float max_x\n"
        "property float max_y\n"
        "property float max_z\n"
        "property float min_scale_x\n"
        "property float min_scale_y\n"
        "property float min_scale_z\n"
        "property float max_scale_x\n"
        "property float max_scale_y\n"
        "property float max_scale_z\n"
        "property float min_r\n"
        "property float min_g\n"
        "property float min_b\n"
        "property float max_r\n"
        "property float max_g\n"
        "property float max_b\n"
        "element vertex " +
        std::to_string(cloud.n) +
        "\n"
        "property uint packed_position\n"
        "property uint packed_rotation\n"
        "property uint packed_scale\n"
        "property uint packed_color\n";
    if (rest != 0) {
        header += "element sh " + std::to_string(cloud.n) + "\n";
        for (size_t coefficient = 0; coefficient < rest; ++coefficient)
            header += "property uchar f_rest_" +
                      std::to_string(coefficient) + "\n";
    }
    header += "end_header\n";

    std::vector<uint32_t> order(cloud.n);
    for (size_t i = 0; i < cloud.n; ++i)
        order[i] = static_cast<uint32_t>(i);
    refine_morton(cloud, order, 0, order.size());

    std::vector<float> chunk_data(
        checked_mul(chunks, 18, "encoded chunk table"));
    std::vector<uint32_t> vertex_data(
        checked_mul(cloud.n, 4, "encoded vertex table"));
    std::vector<uint8_t> sh_data(
        checked_mul(cloud.n, rest, "encoded SH table"));

    for (size_t chunk = 0; chunk < chunks; ++chunk) {
        const size_t begin = chunk * kChunkSize;
        const size_t end = std::min(cloud.n, begin + kChunkSize);
        std::array<float, 9> minimum;
        std::array<float, 9> maximum;
        minimum.fill(std::numeric_limits<float>::infinity());
        maximum.fill(-std::numeric_limits<float>::infinity());
        for (size_t output = begin; output < end; ++output) {
            const size_t row = order[output];
            for (size_t component = 0; component < 3; ++component) {
                const float position = cloud.means[row * 3 + component];
                const float scale = cloud.scales[row * 3 + component];
                const float color =
                    static_cast<float>(
                        static_cast<double>(
                            cloud.sh_dc[row * 3 + component]) *
                            kShC0 +
                        0.5);
                minimum[component] =
                    std::min(minimum[component], position);
                maximum[component] =
                    std::max(maximum[component], position);
                minimum[3 + component] =
                    std::min(minimum[3 + component], scale);
                maximum[3 + component] =
                    std::max(maximum[3 + component], scale);
                minimum[6 + component] =
                    std::min(minimum[6 + component], color);
                maximum[6 + component] =
                    std::max(maximum[6 + component], color);
            }
        }
        float *chunk_row = chunk_data.data() + chunk * 18;
        for (size_t component = 0; component < 3; ++component) {
            chunk_row[component] = minimum[component];
            chunk_row[3 + component] = maximum[component];
            chunk_row[6 + component] = minimum[3 + component];
            chunk_row[9 + component] = maximum[3 + component];
            chunk_row[12 + component] = minimum[6 + component];
            chunk_row[15 + component] = maximum[6 + component];
        }

        for (size_t output = begin; output < end; ++output) {
            const size_t row = order[output];
            const float *position = cloud.means.data() + row * 3;
            const float *scale = cloud.scales.data() + row * 3;
            const float *quaternion = cloud.quats.data() + row * 4;
            std::array<float, 3> color{};
            for (size_t component = 0; component < 3; ++component)
                color[component] =
                    static_cast<float>(
                        static_cast<double>(
                            cloud.sh_dc[row * 3 + component]) *
                            kShC0 +
                        0.5);

            uint32_t *packed = vertex_data.data() + output * 4;
            packed[0] = pack_111011(
                normalize(position[0], minimum[0], maximum[0]),
                normalize(position[1], minimum[1], maximum[1]),
                normalize(position[2], minimum[2], maximum[2]));
            packed[1] = pack_rotation(quaternion);
            packed[2] = pack_111011(
                normalize(scale[0], minimum[3], maximum[3]),
                normalize(scale[1], minimum[4], maximum[4]),
                normalize(scale[2], minimum[5], maximum[5]));
            const double opacity =
                1.0 / (1.0 + std::exp(
                                 -static_cast<double>(
                                     cloud.opacity[row])));
            packed[3] = pack_8888(
                normalize(color[0], minimum[6], maximum[6]),
                normalize(color[1], minimum[7], maximum[7]),
                normalize(color[2], minimum[8], maximum[8]), opacity);

            for (size_t coefficient = 0; coefficient < rest;
                 ++coefficient) {
                const double normalized =
                    static_cast<double>(
                        cloud.sh_rest[row * rest + coefficient]) /
                        8.0 +
                    0.5;
                const double truncated = std::trunc(normalized * 256.0);
                sh_data[output * rest + coefficient] =
                    static_cast<uint8_t>(std::max(
                        0.0, std::min(255.0, truncated)));
            }
        }
    }

    const size_t chunk_bytes =
        checked_mul(chunk_data.size(), sizeof(float), "encoded chunks");
    const size_t vertex_bytes =
        checked_mul(vertex_data.size(), sizeof(uint32_t),
                    "encoded vertices");
    size_t total = checked_add(header.size(), chunk_bytes, "encoded file");
    total = checked_add(total, vertex_bytes, "encoded file");
    total = checked_add(total, sh_data.size(), "encoded file");
    std::string output;
    output.reserve(total);
    output += header;
    for (float value : chunk_data) append_f32_le(output, value);
    for (uint32_t value : vertex_data) append_u32_le(output, value);
    if (!sh_data.empty())
        output.append(reinterpret_cast<const char *>(sh_data.data()),
                      sh_data.size());
    return output;
}

GaussianCloud read_compressed_ply(nb::handle source) {
    ByteView view(source);
    GaussianCloud result;
    {
        nb::gil_scoped_release release;
        result =
            decode_compressed_ply(view.data(), view.size(), false, 0, 0);
    }
    return result;
}

GaussianCloud read_compressed_ply_points(nb::handle source, size_t start,
                                         size_t stop) {
    ByteView view(source);
    GaussianCloud result;
    {
        nb::gil_scoped_release release;
        result = decode_compressed_ply(view.data(), view.size(), true,
                                       start, stop);
    }
    return result;
}

nb::bytes write_compressed_ply(const GaussianCloud &cloud) {
    require_legacy_gaussian_conventions(cloud, "compressed PLY writer");
    std::string output;
    {
        nb::gil_scoped_release release;
        output = encode_compressed_ply(cloud);
    }
    return emit_bytes(output.data(), output.size());
}

}  // namespace

void register_compressed_ply(nb::module_ &m) {
    m.def(
        "read_compressed_ply", &read_compressed_ply, "data"_a,
        "Decode PlayCanvas/SuperSplat compressed PLY into GaussianCloud. "
        "The quantized row order and raw log/logit/SH conventions are "
        "preserved.");
    m.def(
        "read_compressed_ply_points", &read_compressed_ply_points,
        "data"_a, "start"_a, "stop"_a,
        "Decode a non-empty half-open compressed-Ply point range without "
        "allocating the full cloud.");
    m.def(
        "write_compressed_ply", &write_compressed_ply, "cloud"_a,
        "Encode GaussianCloud as deterministic PlayCanvas compressed PLY. "
        "Lossy: Morton reordering plus chunk, quaternion, color, opacity, "
        "and SH quantization.");
}
