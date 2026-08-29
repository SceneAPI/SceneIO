// Generic point-cloud PLY codec.
//
// The parser accepts PLY 1.0 ASCII and fixed-record binary little/big endian
// vertex streams. Every standard scalar spelling is decoded into PointCloud's
// canonical float32 fields; RGB is retained exactly as uint8 or uint16. The
// point subset is intentionally strict: unknown vertex properties, lists, and
// non-vertex elements are refused because PointCloud cannot preserve them.
#include <nanobind/stl/string.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <limits>
#include <string_view>
#include <unordered_map>
#include <unordered_set>

#include "fast_float/fast_float.h"
#include "io/common.hpp"
#include "records/point_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kHeaderLimit = 1024 * 1024;
constexpr size_t kTokenLimit = 1024 * 1024;

enum class Encoding { ASCII, BinaryLE, BinaryBE };
enum class Scalar { I8, U8, I16, U16, I32, U32, F32, F64 };

struct Property {
    Scalar type;
    std::string name;
    size_t offset = 0;
};

struct Header {
    Encoding encoding = Encoding::ASCII;
    bool saw_format = false;
    bool saw_vertex = false;
    bool saw_other_element = false;
    size_t count = 0;
    size_t body = 0;
    size_t stride = 0;
    std::vector<Property> properties;
};

struct Schema {
    size_t x;
    size_t y;
    size_t z;
    bool normals = false;
    size_t nx = 0;
    size_t ny = 0;
    size_t nz = 0;
    bool colors = false;
    bool colors16 = false;
    size_t red = 0;
    size_t green = 0;
    size_t blue = 0;
    bool intensity = false;
    size_t intensity_index = 0;
    std::string intensity_range = "unknown";
};

size_t scalar_size(Scalar type) {
    switch (type) {
        case Scalar::I8:
        case Scalar::U8:
            return 1;
        case Scalar::I16:
        case Scalar::U16:
            return 2;
        case Scalar::I32:
        case Scalar::U32:
        case Scalar::F32:
            return 4;
        case Scalar::F64:
            return 8;
    }
    throw std::logic_error("PLY point cloud: unknown scalar type");
}

Scalar parse_scalar(std::string_view value) {
    if (value == "char" || value == "int8") return Scalar::I8;
    if (value == "uchar" || value == "uint8") return Scalar::U8;
    if (value == "short" || value == "int16") return Scalar::I16;
    if (value == "ushort" || value == "uint16") return Scalar::U16;
    if (value == "int" || value == "int32") return Scalar::I32;
    if (value == "uint" || value == "uint32") return Scalar::U32;
    if (value == "float" || value == "float32") return Scalar::F32;
    if (value == "double" || value == "float64") return Scalar::F64;
    throw std::invalid_argument(
        "PLY point cloud: unsupported scalar type '" + std::string(value) + "'");
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
        while (pos < line.size() && line[pos] != ' ' && line[pos] != '\t')
            ++pos;
        result.push_back(line.substr(begin, pos - begin));
    }
    return result;
}

size_t parse_count(std::string_view token) {
    if (token.empty() ||
        !std::all_of(token.begin(), token.end(),
                     [](unsigned char c) { return c >= '0' && c <= '9'; }))
        throw std::invalid_argument("PLY point cloud: malformed element count");
    uint64_t value = 0;
    const auto parsed =
        std::from_chars(token.data(), token.data() + token.size(), value);
    if (parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size() ||
        value > std::numeric_limits<size_t>::max())
        throw std::invalid_argument("PLY point cloud: element count is too large");
    return static_cast<size_t>(value);
}

Header parse_header(const uint8_t *data, size_t size) {
    Header header;
    size_t cursor = 0;
    size_t header_bytes = 0;
    std::string current_element;
    std::unordered_set<std::string> element_names;
    std::unordered_set<std::string> property_names;

    auto line = [&]() -> std::string_view {
        if (cursor >= size)
            throw std::invalid_argument("PLY point cloud: missing end_header");
        const size_t begin = cursor;
        while (cursor < size && data[cursor] != '\n') {
            if (data[cursor] == 0)
                throw std::invalid_argument("PLY point cloud: NUL byte in header");
            ++cursor;
            if (++header_bytes > kHeaderLimit)
                throw std::invalid_argument("PLY point cloud: header exceeds 1 MiB");
        }
        if (cursor == size)
            throw std::invalid_argument(
                "PLY point cloud: unterminated header line");
        ++cursor;
        if (++header_bytes > kHeaderLimit)
            throw std::invalid_argument("PLY point cloud: header exceeds 1 MiB");
        size_t end = cursor - 1;
        if (end > begin && data[end - 1] == '\r') --end;
        return std::string_view(
            reinterpret_cast<const char *>(data + begin), end - begin);
    };

    if (line() != "ply")
        throw std::invalid_argument("PLY point cloud: missing 'ply' magic");
    while (true) {
        const std::string_view raw = line();
        const auto words = split(raw);
        if (words.empty())
            throw std::invalid_argument("PLY point cloud: blank header directive");
        const std::string_view directive = words[0];
        if (directive == "comment" || directive == "obj_info") continue;
        if (directive == "format") {
            if (words.size() != 3 || words[2] != "1.0" ||
                header.saw_format || !element_names.empty())
                throw std::invalid_argument(
                    "PLY point cloud: malformed, duplicate, or misplaced format header");
            header.saw_format = true;
            if (words[1] == "ascii")
                header.encoding = Encoding::ASCII;
            else if (words[1] == "binary_little_endian")
                header.encoding = Encoding::BinaryLE;
            else if (words[1] == "binary_big_endian")
                header.encoding = Encoding::BinaryBE;
            else
                throw std::invalid_argument("PLY point cloud: unsupported format");
        } else if (directive == "element") {
            if (words.size() != 3 || !header.saw_format)
                throw std::invalid_argument(
                    "PLY point cloud: malformed or misplaced element header");
            current_element.assign(words[1]);
            if (!element_names.insert(current_element).second)
                throw std::invalid_argument(
                    "PLY point cloud: duplicate element '" + current_element + "'");
            property_names.clear();
            const size_t count = parse_count(words[2]);
            if (current_element == "vertex") {
                if (header.saw_vertex)
                    throw std::invalid_argument(
                        "PLY point cloud: duplicate vertex element");
                header.saw_vertex = true;
                header.count = count;
            } else {
                header.saw_other_element = true;
            }
        } else if (directive == "property") {
            if (current_element.empty())
                throw std::invalid_argument(
                    "PLY point cloud: property appears before an element");
            if (words.size() == 5 && words[1] == "list") {
                (void)parse_scalar(words[2]);
                (void)parse_scalar(words[3]);
                if (!property_names.insert(std::string(words[4])).second)
                    throw std::invalid_argument(
                        "PLY point cloud: duplicate property");
                if (current_element == "vertex")
                    throw std::invalid_argument(
                        "PLY point cloud: list-valued vertex properties are unsupported");
            } else {
                if (words.size() != 3)
                    throw std::invalid_argument(
                        "PLY point cloud: malformed property header");
                const Scalar type = parse_scalar(words[1]);
                const std::string name(words[2]);
                if (name.empty() || !property_names.insert(name).second)
                    throw std::invalid_argument(
                        "PLY point cloud: empty or duplicate property");
                if (current_element == "vertex") {
                    const size_t width = scalar_size(type);
                    if (header.stride >
                        std::numeric_limits<size_t>::max() - width)
                        throw std::invalid_argument(
                            "PLY point cloud: vertex stride overflows address space");
                    header.properties.push_back(
                        Property{type, name, header.stride});
                    header.stride += width;
                }
            }
        } else if (directive == "end_header") {
            if (words.size() != 1)
                throw std::invalid_argument(
                    "PLY point cloud: malformed end_header");
            header.body = cursor;
            break;
        } else {
            throw std::invalid_argument(
                "PLY point cloud: unsupported header directive '" +
                std::string(directive) + "'");
        }
    }
    if (!header.saw_format)
        throw std::invalid_argument("PLY point cloud: missing format header");
    if (!header.saw_vertex)
        throw std::invalid_argument("PLY point cloud: missing vertex element");
    if (header.saw_other_element)
        throw std::invalid_argument(
            "PLY point cloud: non-vertex elements require the mesh codec");
    if (header.properties.empty())
        throw std::invalid_argument("PLY point cloud: empty vertex schema");
    return header;
}

Schema validate_schema(const Header &header) {
    std::unordered_map<std::string, size_t> columns;
    for (size_t index = 0; index < header.properties.size(); ++index)
        columns.emplace(header.properties[index].name, index);
    const std::unordered_set<std::string> known = {
        "x", "y", "z", "nx", "ny", "nz",
        "red", "green", "blue", "intensity"};
    for (const Property &property : header.properties)
        if (!known.count(property.name))
            throw std::invalid_argument(
                "PLY point cloud: unsupported vertex property '" +
                property.name + "'");
    auto required = [&](const char *name) {
        const auto found = columns.find(name);
        if (found == columns.end())
            throw std::invalid_argument(
                std::string("PLY point cloud: missing property '") + name + "'");
        return found->second;
    };

    Schema schema{required("x"), required("y"), required("z")};
    const size_t normal_count =
        columns.count("nx") + columns.count("ny") + columns.count("nz");
    if (normal_count != 0 && normal_count != 3)
        throw std::invalid_argument(
            "PLY point cloud: normals require nx, ny, and nz");
    if (normal_count == 3) {
        schema.normals = true;
        schema.nx = columns.at("nx");
        schema.ny = columns.at("ny");
        schema.nz = columns.at("nz");
    }

    const size_t color_count =
        columns.count("red") + columns.count("green") + columns.count("blue");
    if (color_count != 0 && color_count != 3)
        throw std::invalid_argument(
            "PLY point cloud: colors require red, green, and blue");
    if (color_count == 3) {
        const Scalar red = header.properties[columns.at("red")].type;
        const Scalar green = header.properties[columns.at("green")].type;
        const Scalar blue = header.properties[columns.at("blue")].type;
        if (red != green || red != blue ||
            (red != Scalar::U8 && red != Scalar::U16))
            throw std::invalid_argument(
                "PLY point cloud: RGB must be uniformly uint8 or uint16");
        schema.colors = red == Scalar::U8;
        schema.colors16 = red == Scalar::U16;
        schema.red = columns.at("red");
        schema.green = columns.at("green");
        schema.blue = columns.at("blue");
    }
    if (columns.count("intensity")) {
        schema.intensity = true;
        schema.intensity_index = columns.at("intensity");
        const Scalar type = header.properties[schema.intensity_index].type;
        if (type == Scalar::U8)
            schema.intensity_range = "u8";
        else if (type == Scalar::U16)
            schema.intensity_range = "u16";
    }
    return schema;
}

template <typename T>
T load_binary(const uint8_t *source, bool swap) {
    std::array<uint8_t, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), source, sizeof(T));
    if (swap) std::reverse(bytes.begin(), bytes.end());
    T value;
    std::memcpy(&value, bytes.data(), sizeof(T));
    return value;
}

double binary_number(const uint8_t *source, Scalar type, bool swap) {
    switch (type) {
        case Scalar::I8:
            return load_binary<int8_t>(source, false);
        case Scalar::U8:
            return load_binary<uint8_t>(source, false);
        case Scalar::I16:
            return load_binary<int16_t>(source, swap);
        case Scalar::U16:
            return load_binary<uint16_t>(source, swap);
        case Scalar::I32:
            return load_binary<int32_t>(source, swap);
        case Scalar::U32:
            return load_binary<uint32_t>(source, swap);
        case Scalar::F32:
            return load_binary<float>(source, swap);
        case Scalar::F64:
            return load_binary<double>(source, swap);
    }
    throw std::logic_error("PLY point cloud: unknown binary scalar type");
}

template <typename T>
T parse_signed_integer(std::string_view token, T minimum, T maximum) {
    if (!token.empty() && token.front() == '+') token.remove_prefix(1);
    int64_t value = 0;
    const auto parsed =
        std::from_chars(token.data(), token.data() + token.size(), value);
    if (token.empty() || parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size() ||
        value < static_cast<int64_t>(minimum) ||
        value > static_cast<int64_t>(maximum))
        throw std::invalid_argument("PLY point cloud: invalid signed integer token");
    return static_cast<T>(value);
}

template <typename T>
T parse_unsigned_integer(std::string_view token, T maximum) {
    if (!token.empty() && token.front() == '+') token.remove_prefix(1);
    uint64_t value = 0;
    const auto parsed =
        std::from_chars(token.data(), token.data() + token.size(), value);
    if (token.empty() || parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size() ||
        value > static_cast<uint64_t>(maximum))
        throw std::invalid_argument(
            "PLY point cloud: invalid unsigned integer token");
    return static_cast<T>(value);
}

double ascii_number(std::string_view token, Scalar type) {
    switch (type) {
        case Scalar::I8:
            return parse_signed_integer<int8_t>(
                token, std::numeric_limits<int8_t>::min(),
                std::numeric_limits<int8_t>::max());
        case Scalar::U8:
            return parse_unsigned_integer<uint8_t>(
                token, std::numeric_limits<uint8_t>::max());
        case Scalar::I16:
            return parse_signed_integer<int16_t>(
                token, std::numeric_limits<int16_t>::min(),
                std::numeric_limits<int16_t>::max());
        case Scalar::U16:
            return parse_unsigned_integer<uint16_t>(
                token, std::numeric_limits<uint16_t>::max());
        case Scalar::I32:
            return parse_signed_integer<int32_t>(
                token, std::numeric_limits<int32_t>::min(),
                std::numeric_limits<int32_t>::max());
        case Scalar::U32:
            return parse_unsigned_integer<uint32_t>(
                token, std::numeric_limits<uint32_t>::max());
        case Scalar::F32: {
            float value = 0;
            const auto parsed =
                fast_float::from_chars(
                    token.data(), token.data() + token.size(), value);
            if (token.empty() || parsed.ec != std::errc{} ||
                parsed.ptr != token.data() + token.size())
                throw std::invalid_argument(
                    "PLY point cloud: invalid float32 token");
            return value;
        }
        case Scalar::F64: {
            double value = 0;
            const auto parsed =
                fast_float::from_chars(
                    token.data(), token.data() + token.size(), value);
            if (token.empty() || parsed.ec != std::errc{} ||
                parsed.ptr != token.data() + token.size())
                throw std::invalid_argument(
                    "PLY point cloud: invalid float64 token");
            return value;
        }
    }
    throw std::logic_error("PLY point cloud: unknown ASCII scalar type");
}

float canonical_float(double value, const char *field) {
    const float result = static_cast<float>(value);
    if (std::isfinite(value) && !std::isfinite(result))
        throw std::invalid_argument(
            std::string("PLY point cloud: ") + field +
            " value exceeds float32 range");
    return result;
}

class AsciiTokens {
public:
    AsciiTokens(const uint8_t *begin, const uint8_t *end)
        : cursor_(reinterpret_cast<const char *>(begin)),
          end_(reinterpret_cast<const char *>(end)) {}

    std::string_view require() {
        while (cursor_ < end_ &&
               (*cursor_ == ' ' || *cursor_ == '\t' || *cursor_ == '\r' ||
                *cursor_ == '\n'))
            ++cursor_;
        if (cursor_ == end_)
            throw std::invalid_argument(
                "PLY point cloud: truncated ASCII vertex payload");
        const char *begin = cursor_;
        while (cursor_ < end_ &&
               *cursor_ != ' ' && *cursor_ != '\t' && *cursor_ != '\r' &&
               *cursor_ != '\n') {
            ++cursor_;
            if (static_cast<size_t>(cursor_ - begin) > kTokenLimit)
                throw std::invalid_argument(
                    "PLY point cloud: ASCII token exceeds 1 MiB");
        }
        return std::string_view(
            begin, static_cast<size_t>(cursor_ - begin));
    }

    bool has_trailing() {
        while (cursor_ < end_ &&
               (*cursor_ == ' ' || *cursor_ == '\t' || *cursor_ == '\r' ||
                *cursor_ == '\n'))
            ++cursor_;
        return cursor_ != end_;
    }

private:
    const char *cursor_;
    const char *end_;
};

void allocate(PointCloud &cloud, size_t count, const Schema &schema) {
    if (count > cloud.xyz.max_size() / 3)
        throw std::length_error("PLY point cloud: decoded cloud is too large");
    cloud.n = count;
    cloud.xyz.resize(count * 3);
    if (schema.normals) cloud.normals.resize(count * 3);
    if (schema.colors) cloud.rgb.resize(count * 3);
    if (schema.colors16) cloud.rgb16.resize(count * 3);
    if (schema.intensity) cloud.intensity.resize(count);
    cloud.intensity_range = schema.intensity_range;
}

template <typename Number>
void assign_row(PointCloud &cloud, size_t row, const Header &header,
                const Schema &schema, Number number) {
    auto value = [&](size_t index) {
        return number(header.properties[index]);
    };
    cloud.xyz[row * 3] = canonical_float(value(schema.x), "x");
    cloud.xyz[row * 3 + 1] = canonical_float(value(schema.y), "y");
    cloud.xyz[row * 3 + 2] = canonical_float(value(schema.z), "z");
    if (schema.normals) {
        cloud.normals[row * 3] = canonical_float(value(schema.nx), "nx");
        cloud.normals[row * 3 + 1] =
            canonical_float(value(schema.ny), "ny");
        cloud.normals[row * 3 + 2] =
            canonical_float(value(schema.nz), "nz");
    }
    if (schema.colors) {
        cloud.rgb[row * 3] = static_cast<uint8_t>(value(schema.red));
        cloud.rgb[row * 3 + 1] =
            static_cast<uint8_t>(value(schema.green));
        cloud.rgb[row * 3 + 2] =
            static_cast<uint8_t>(value(schema.blue));
    }
    if (schema.colors16) {
        cloud.rgb16[row * 3] = static_cast<uint16_t>(value(schema.red));
        cloud.rgb16[row * 3 + 1] =
            static_cast<uint16_t>(value(schema.green));
        cloud.rgb16[row * 3 + 2] =
            static_cast<uint16_t>(value(schema.blue));
    }
    if (schema.intensity)
        cloud.intensity[row] =
            canonical_float(value(schema.intensity_index), "intensity");
}

PointCloud decode_ply(const uint8_t *data, size_t size, bool partial,
                      size_t start, size_t stop) {
    const Header header = parse_header(data, size);
    const Schema schema = validate_schema(header);
    if (header.encoding == Encoding::ASCII) {
        if (partial)
            throw std::invalid_argument(
                "PLY point cloud: bounded point ranges require a binary fixed-record body");
        // Reject count bombs before any record vector is allocated. Every
        // scalar needs at least one byte, and adjacent tokens need at least one
        // whitespace byte, so (body_size + 1) / 2 bounds the token count.
        const size_t body_size = size - header.body;
        const size_t max_tokens = body_size / 2 + body_size % 2;
        if (header.count > max_tokens / header.properties.size())
            throw std::invalid_argument(
                "PLY point cloud: declared ASCII vertex count exceeds payload");
    } else {
        // Validate the complete fixed-record extent before allocating even a
        // selected range. This also makes malformed full and partial outcomes
        // identical and prevents a hostile count from driving a huge reserve.
        if (header.count >
            (std::numeric_limits<size_t>::max() - header.body) /
                header.stride)
            throw std::invalid_argument(
                "PLY point cloud: binary payload size overflows address space");
        const size_t expected =
            header.body + header.count * header.stride;
        if (expected != size)
            throw std::invalid_argument(
                expected > size
                    ? "PLY point cloud: truncated binary vertex payload"
                    : "PLY point cloud: trailing binary vertex payload");
    }
    if (!partial) {
        start = 0;
        stop = header.count;
    } else {
        checked_half_open_range(
            start, stop, header.count, "PLY point-cloud point range");
    }
    const size_t selected = stop - start;
    PointCloud cloud;
    allocate(cloud, selected, schema);

    if (header.encoding == Encoding::ASCII) {
        AsciiTokens tokens(data + header.body, data + size);
        std::vector<double> row(header.properties.size());
        for (size_t source_row = 0; source_row < header.count; ++source_row) {
            for (size_t index = 0; index < header.properties.size(); ++index)
                row[index] = ascii_number(
                    tokens.require(), header.properties[index].type);
            assign_row(
                cloud, source_row, header, schema,
                [&](const Property &property) {
                    const size_t index =
                        static_cast<size_t>(&property - header.properties.data());
                    return row[index];
                });
        }
        if (tokens.has_trailing())
            throw std::invalid_argument(
                "PLY point cloud: trailing ASCII vertex tokens");
        return cloud;
    }

    const bool file_little = header.encoding == Encoding::BinaryLE;
    const bool swap = file_little != host_is_le();
    for (size_t output_row = 0; output_row < selected; ++output_row) {
        const size_t source_row = start + output_row;
        const uint8_t *record =
            data + header.body + source_row * header.stride;
        assign_row(
            cloud, output_row, header, schema,
            [&](const Property &property) {
                return binary_number(
                    record + property.offset, property.type, swap);
            });
    }
    return cloud;
}

PointCloud read_ply(nb::handle source) {
    sio::ByteView view(source);
    PointCloud cloud;
    {
        nb::gil_scoped_release release;
        cloud = decode_ply(view.data(), view.size(), false, 0, 0);
    }
    return cloud;
}

PointCloud read_ply_points(nb::handle source, size_t start, size_t stop) {
    sio::ByteView view(source);
    PointCloud cloud;
    {
        nb::gil_scoped_release release;
        cloud = decode_ply(view.data(), view.size(), true, start, stop);
    }
    return cloud;
}

void validate_writer(const PointCloud &cloud) {
    require_no_extended_point_fields(cloud, "PLY point writer");
    if (cloud.n > std::numeric_limits<size_t>::max() / 3)
        throw std::invalid_argument(
            "PLY point cloud: point count overflows field extents");
    if (cloud.xyz.size() != cloud.n * 3 ||
        (cloud.has_normals() && cloud.normals.size() != cloud.n * 3) ||
        (cloud.has_rgb() && cloud.rgb.size() != cloud.n * 3) ||
        (cloud.has_rgb16() && cloud.rgb16.size() != cloud.n * 3) ||
        (cloud.has_intensity() && cloud.intensity.size() != cloud.n))
        throw std::invalid_argument(
            "PLY point cloud: inconsistent PointCloud field lengths");
    if (cloud.has_rgb() && cloud.has_rgb16())
        throw std::invalid_argument(
            "PLY point cloud: rgb and colors16 cannot both be represented");
    if (cloud.coordinate_frame != "unknown" || cloud.scale_to_meters != 1.0)
        throw std::invalid_argument(
            "PLY point cloud: coordinate frame and scale metadata are not representable");
    if (cloud.origin[0] != 0.0 || cloud.origin[1] != 0.0 ||
        cloud.origin[2] != 0.0)
        throw std::invalid_argument(
            "PLY point cloud: georeferenced origin is not representable");
    if (!cloud.has_default_organization() ||
        !cloud.has_default_viewpoint())
        throw std::invalid_argument(
            "PLY point cloud: organized shape and acquisition viewpoint metadata are not representable");
    if (!cloud.has_intensity() && cloud.intensity_range != "unknown")
        throw std::invalid_argument(
            "PLY point cloud: intensity range metadata has no intensity field");
    if (cloud.has_intensity() && cloud.intensity_range == "unit")
        throw std::invalid_argument(
            "PLY point cloud: unit intensity semantics are not representable");
    if (cloud.has_intensity() &&
        (cloud.intensity_range == "u8" ||
         cloud.intensity_range == "u16")) {
        const float maximum =
            cloud.intensity_range == "u8" ? 255.0f : 65535.0f;
        for (float value : cloud.intensity)
            if (!std::isfinite(value) || value < 0.0f || value > maximum ||
                std::floor(value) != value)
                throw std::invalid_argument(
                    "PLY point cloud: integer intensity metadata requires exact in-range integers");
    }
}

void append_float(std::string &output, float value) {
    if (std::isnan(value)) {
        output += std::signbit(value) ? "-nan" : "nan";
        return;
    }
    if (std::isinf(value)) {
        output += std::signbit(value) ? "-inf" : "inf";
        return;
    }
    char buffer[64];
    const int count = std::snprintf(
        buffer, sizeof(buffer), "%.9g", static_cast<double>(value));
    if (count < 0 || static_cast<size_t>(count) >= sizeof(buffer))
        throw std::runtime_error("PLY point cloud: float formatter failed");
    output.append(buffer, static_cast<size_t>(count));
}

template <typename T>
void append_binary(std::string &output, T value, bool little) {
    std::array<uint8_t, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), &value, sizeof(T));
    if (little != host_is_le()) std::reverse(bytes.begin(), bytes.end());
    output.append(
        reinterpret_cast<const char *>(bytes.data()), bytes.size());
}

std::string encode_ply(const PointCloud &cloud,
                       const std::string &encoding_name) {
    validate_writer(cloud);
    Encoding encoding;
    if (encoding_name == "ascii")
        encoding = Encoding::ASCII;
    else if (encoding_name == "binary_little_endian")
        encoding = Encoding::BinaryLE;
    else if (encoding_name == "binary_big_endian")
        encoding = Encoding::BinaryBE;
    else
        throw std::invalid_argument(
            "PLY point cloud: encoding must be ascii|binary_little_endian|binary_big_endian");

    std::string header = "ply\nformat " + encoding_name +
                         " 1.0\nelement vertex " +
                         std::to_string(cloud.n) +
                         "\nproperty float x\nproperty float y\nproperty float z\n";
    if (cloud.has_normals())
        header +=
            "property float nx\nproperty float ny\nproperty float nz\n";
    if (cloud.has_rgb()) {
        header +=
            "property uchar red\nproperty uchar green\nproperty uchar blue\n";
    } else if (cloud.has_rgb16()) {
        header +=
            "property ushort red\nproperty ushort green\nproperty ushort blue\n";
    }
    if (cloud.has_intensity()) {
        const char *type =
            cloud.intensity_range == "u8"
                ? "uchar"
                : cloud.intensity_range == "u16" ? "ushort" : "float";
        header += std::string("property ") + type + " intensity\n";
    }
    header += "end_header\n";

    std::string output = std::move(header);
    if (encoding == Encoding::ASCII) {
        if (cloud.n >
            (output.max_size() - output.size()) / 160)
            throw std::length_error("PLY point cloud: encoded text is too large");
        output.reserve(output.size() + cloud.n * 160);
        auto separator = [&]() {
            if (!output.empty() && output.back() != '\n') output.push_back(' ');
        };
        for (size_t row = 0; row < cloud.n; ++row) {
            for (size_t component = 0; component < 3; ++component) {
                separator();
                append_float(output, cloud.xyz[row * 3 + component]);
            }
            if (cloud.has_normals())
                for (size_t component = 0; component < 3; ++component) {
                    separator();
                    append_float(
                        output, cloud.normals[row * 3 + component]);
                }
            if (cloud.has_rgb())
                for (size_t component = 0; component < 3; ++component) {
                    separator();
                    output += std::to_string(
                        cloud.rgb[row * 3 + component]);
                }
            if (cloud.has_rgb16())
                for (size_t component = 0; component < 3; ++component) {
                    separator();
                    output += std::to_string(
                        cloud.rgb16[row * 3 + component]);
                }
            if (cloud.has_intensity()) {
                separator();
                const float value = cloud.intensity[row];
                if (cloud.intensity_range == "u8" ||
                    cloud.intensity_range == "u16")
                    output += std::to_string(static_cast<uint32_t>(value));
                else
                    append_float(output, value);
            }
            output.push_back('\n');
        }
        return output;
    }

    size_t stride = 3 * sizeof(float);
    if (cloud.has_normals()) stride += 3 * sizeof(float);
    if (cloud.has_rgb()) stride += 3;
    if (cloud.has_rgb16()) stride += 3 * sizeof(uint16_t);
    if (cloud.has_intensity())
        stride += cloud.intensity_range == "u8"
                      ? 1
                      : cloud.intensity_range == "u16" ? 2 : sizeof(float);
    if (cloud.n >
        (output.max_size() - output.size()) / stride)
        throw std::length_error("PLY point cloud: encoded binary is too large");
    output.reserve(output.size() + cloud.n * stride);
    const bool little = encoding == Encoding::BinaryLE;
    for (size_t row = 0; row < cloud.n; ++row) {
        for (size_t component = 0; component < 3; ++component)
            append_binary(
                output, cloud.xyz[row * 3 + component], little);
        if (cloud.has_normals())
            for (size_t component = 0; component < 3; ++component)
                append_binary(
                    output, cloud.normals[row * 3 + component], little);
        if (cloud.has_rgb())
            for (size_t component = 0; component < 3; ++component)
                append_binary(
                    output, cloud.rgb[row * 3 + component], little);
        if (cloud.has_rgb16())
            for (size_t component = 0; component < 3; ++component)
                append_binary(
                    output, cloud.rgb16[row * 3 + component], little);
        if (cloud.has_intensity()) {
            const float value = cloud.intensity[row];
            if (cloud.intensity_range == "u8")
                append_binary(output, static_cast<uint8_t>(value), little);
            else if (cloud.intensity_range == "u16")
                append_binary(output, static_cast<uint16_t>(value), little);
            else
                append_binary(output, value, little);
        }
    }
    return output;
}

nb::bytes write_ply(const PointCloud &cloud,
                    const std::string &encoding) {
    std::string output;
    {
        nb::gil_scoped_release release;
        output = encode_ply(cloud, encoding);
    }
    return emit_bytes(output.data(), output.size());
}

}  // namespace

void register_ply_point(nb::module_ &m) {
    m.def(
        "read_ply", &read_ply, "data"_a,
        "Decode a generic point-cloud PLY (ASCII or binary LE/BE) into PointCloud.");
    m.def(
        "read_ply_points", &read_ply_points, "data"_a, "start"_a, "stop"_a,
        "Decode a half-open point range from a fixed-record binary generic PLY.");
    m.def(
        "write_ply", &write_ply, "cloud"_a,
        "_encoding"_a = "binary_little_endian",
        "Encode PointCloud as deterministic PLY. The private encoding seam accepts "
        "ascii, binary_little_endian, or binary_big_endian.");
}
