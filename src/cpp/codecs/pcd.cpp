// PCD 0.7 point-cloud codec.
//
// The supported semantic subset maps losslessly to PointCloud: required x/y/z,
// optional normal_x/y/z, packed rgb (TYPE F/U, SIZE 4), and intensity. All
// scalar input widths are accepted and canonicalized to float32; organization
// and VIEWPOINT are retained. Unknown fields and COUNT != 1 are refused because
// PointCloud cannot preserve them.
//
// DATA ascii, binary, and binary_compressed are supported. PCD's compressed
// representation is LZF over a field-major (SoA) byte rearrangement. The small
// compatible implementation below follows the published LZF token format and
// avoids another runtime or vendored dependency. Decode/encode is pure C++ and
// runs with the GIL released.
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
constexpr size_t kLzfWindow = 8192;
constexpr size_t kLzfMaxMatch = 264;
constexpr size_t kLzfHashSize = 1 << 14;

enum class Kind { Signed, Unsigned, Floating };
enum class Storage { ASCII, Binary, BinaryCompressed };

struct Field {
    std::string name;
    size_t size = 0;
    Kind kind = Kind::Floating;
    size_t count = 0;
    size_t offset = 0;
    size_t soa_offset = 0;
};

struct Header {
    std::vector<Field> fields;
    size_t width = 0;
    size_t height = 0;
    size_t points = 0;
    size_t stride = 0;
    size_t body = 0;
    std::array<double, 7> viewpoint{0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0};
    Storage storage = Storage::Binary;
};

struct Schema {
    size_t x = 0;
    size_t y = 0;
    size_t z = 0;
    bool normals = false;
    size_t nx = 0;
    size_t ny = 0;
    size_t nz = 0;
    bool rgb = false;
    size_t rgb_index = 0;
    bool intensity = false;
    size_t intensity_index = 0;
    std::string intensity_range = "unknown";
};

std::vector<std::string_view> split(std::string_view line) {
    std::vector<std::string_view> result;
    size_t cursor = 0;
    while (cursor < line.size()) {
        while (cursor < line.size() &&
               (line[cursor] == ' ' || line[cursor] == '\t'))
            ++cursor;
        if (cursor == line.size()) break;
        const size_t begin = cursor;
        while (cursor < line.size() && line[cursor] != ' ' &&
               line[cursor] != '\t')
            ++cursor;
        result.push_back(line.substr(begin, cursor - begin));
    }
    return result;
}

size_t parse_size(std::string_view token, const char *what) {
    if (token.empty() ||
        !std::all_of(token.begin(), token.end(),
                     [](unsigned char value) {
                         return value >= '0' && value <= '9';
                     }))
        throw std::invalid_argument(
            std::string("PCD: malformed ") + what);
    uint64_t value = 0;
    const auto result =
        std::from_chars(token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size() ||
        value > std::numeric_limits<size_t>::max())
        throw std::invalid_argument(
            std::string("PCD: ") + what + " exceeds addressable size");
    return static_cast<size_t>(value);
}

double parse_finite_double(std::string_view token, const char *what) {
    double value = 0.0;
    const auto result =
        fast_float::from_chars(token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size() ||
        !std::isfinite(value))
        throw std::invalid_argument(
            std::string("PCD: malformed or non-finite ") + what);
    return value;
}

Header parse_header(const uint8_t *data, size_t size) {
    static constexpr std::array<std::string_view, 10> expected{
        "VERSION", "FIELDS", "SIZE", "TYPE", "COUNT",
        "WIDTH", "HEIGHT", "VIEWPOINT", "POINTS", "DATA"};

    Header header;
    std::array<std::vector<std::string_view>, expected.size()> values;
    size_t cursor = 0;
    size_t index = 0;

    while (index < expected.size()) {
        if (cursor >= size)
            throw std::invalid_argument("PCD: missing DATA header");
        const size_t begin = cursor;
        while (cursor < size && data[cursor] != '\n') {
            if (data[cursor] == 0)
                throw std::invalid_argument("PCD: NUL byte in header");
            ++cursor;
            if (cursor > kHeaderLimit)
                throw std::invalid_argument("PCD: header exceeds 1 MiB");
        }
        if (cursor == size)
            throw std::invalid_argument(
                "PCD: header line is unterminated");
        size_t end = cursor++;
        if (cursor > kHeaderLimit)
            throw std::invalid_argument("PCD: header exceeds 1 MiB");
        if (end > begin && data[end - 1] == '\r') --end;
        const std::string_view line(
            reinterpret_cast<const char *>(data + begin), end - begin);
        auto tokens = split(line);
        if (tokens.empty() || (!tokens[0].empty() && tokens[0][0] == '#'))
            continue;
        if (tokens[0] == "COLUMNS" && expected[index] == "FIELDS")
            tokens[0] = "FIELDS";
        if (tokens[0] != expected[index])
            throw std::invalid_argument(
                "PCD: expected " + std::string(expected[index]) +
                " header, found '" + std::string(tokens[0]) + "'");
        values[index].assign(tokens.begin() + 1, tokens.end());
        ++index;
    }
    header.body = cursor;

    if (values[0].size() != 1 ||
        (values[0][0] != ".7" && values[0][0] != "0.7"))
        throw std::invalid_argument(
            "PCD: only VERSION .7 is supported");
    const size_t field_count = values[1].size();
    if (field_count == 0 || values[2].size() != field_count ||
        values[3].size() != field_count ||
        values[4].size() != field_count)
        throw std::invalid_argument(
            "PCD: FIELDS/SIZE/TYPE/COUNT lengths differ or are empty");

    std::unordered_set<std::string> names;
    header.fields.reserve(field_count);
    for (size_t i = 0; i < field_count; ++i) {
        Field field;
        field.name = std::string(values[1][i]);
        if (field.name.empty() || !names.insert(field.name).second)
            throw std::invalid_argument(
                "PCD: FIELDS names must be nonempty and unique");
        field.size = parse_size(values[2][i], "SIZE");
        if (values[3][i] == "F") {
            field.kind = Kind::Floating;
            if (field.size != 4 && field.size != 8)
                throw std::invalid_argument(
                    "PCD: floating fields require SIZE 4 or 8");
        } else if (values[3][i] == "I") {
            field.kind = Kind::Signed;
            if (field.size != 1 && field.size != 2 &&
                field.size != 4 && field.size != 8)
                throw std::invalid_argument(
                    "PCD: integer fields require SIZE 1, 2, 4, or 8");
        } else if (values[3][i] == "U") {
            field.kind = Kind::Unsigned;
            if (field.size != 1 && field.size != 2 &&
                field.size != 4 && field.size != 8)
                throw std::invalid_argument(
                    "PCD: integer fields require SIZE 1, 2, 4, or 8");
        } else {
            throw std::invalid_argument(
                "PCD: unsupported TYPE '" + std::string(values[3][i]) + "'");
        }
        field.count = parse_size(values[4][i], "COUNT");
        if (field.count == 0)
            throw std::invalid_argument(
                "PCD: COUNT values must be positive");
        if (field.count > std::numeric_limits<size_t>::max() / field.size)
            throw std::invalid_argument("PCD: field extent overflows size_t");
        const size_t bytes = field.count * field.size;
        if (header.stride > std::numeric_limits<size_t>::max() - bytes)
            throw std::invalid_argument("PCD: point stride overflows size_t");
        field.offset = header.stride;
        header.stride += bytes;
        header.fields.push_back(std::move(field));
    }

    if (values[5].size() != 1 || values[6].size() != 1 ||
        values[8].size() != 1)
        throw std::invalid_argument(
            "PCD: WIDTH, HEIGHT, and POINTS require one value");
    header.width = parse_size(values[5][0], "WIDTH");
    header.height = parse_size(values[6][0], "HEIGHT");
    header.points = parse_size(values[8][0], "POINTS");
    if (header.height == 0 ||
        (header.width == 0 && header.height != 1) ||
        (header.width != 0 &&
         header.height >
             std::numeric_limits<size_t>::max() / header.width) ||
        header.width * header.height != header.points)
        throw std::invalid_argument(
            "PCD: WIDTH*HEIGHT must equal POINTS");

    if (values[7].size() != 7)
        throw std::invalid_argument(
            "PCD: VIEWPOINT requires tx ty tz qw qx qy qz");
    for (size_t i = 0; i < 7; ++i)
        header.viewpoint[i] =
            parse_finite_double(values[7][i], "VIEWPOINT");

    if (values[9].size() != 1)
        throw std::invalid_argument(
            "PCD: DATA requires one storage mode");
    if (values[9][0] == "ascii")
        header.storage = Storage::ASCII;
    else if (values[9][0] == "binary")
        header.storage = Storage::Binary;
    else if (values[9][0] == "binary_compressed")
        header.storage = Storage::BinaryCompressed;
    else
        throw std::invalid_argument(
            "PCD: unsupported DATA mode '" +
            std::string(values[9][0]) + "'");

    if (header.points != 0 &&
        header.stride >
            std::numeric_limits<size_t>::max() / header.points)
        throw std::invalid_argument("PCD: payload extent overflows size_t");
    size_t soa = 0;
    for (Field &field : header.fields) {
        field.soa_offset = soa;
        soa += field.size * field.count * header.points;
    }
    return header;
}

Schema validate_schema(const Header &header) {
    std::unordered_map<std::string, size_t> indices;
    for (size_t i = 0; i < header.fields.size(); ++i) {
        const Field &field = header.fields[i];
        if (field.count != 1)
            throw std::invalid_argument(
                "PCD: mapped PointCloud fields require COUNT 1");
        indices.emplace(field.name, i);
    }
    static const std::unordered_set<std::string> known{
        "x", "y", "z", "normal_x", "normal_y", "normal_z",
        "rgb", "intensity"};
    for (const auto &[name, unused] : indices) {
        (void) unused;
        if (known.find(name) == known.end())
            throw std::invalid_argument(
                "PCD: unsupported field '" + name + "'");
    }
    for (const char *name : {"x", "y", "z"})
        if (indices.find(name) == indices.end())
            throw std::invalid_argument(
                "PCD: missing field '" + std::string(name) + "'");

    Schema schema;
    schema.x = indices.at("x");
    schema.y = indices.at("y");
    schema.z = indices.at("z");
    const bool nx = indices.find("normal_x") != indices.end();
    const bool ny = indices.find("normal_y") != indices.end();
    const bool nz = indices.find("normal_z") != indices.end();
    if ((nx || ny || nz) && !(nx && ny && nz))
        throw std::invalid_argument(
            "PCD: normals require normal_x, normal_y, and normal_z");
    schema.normals = nx;
    if (nx) {
        schema.nx = indices.at("normal_x");
        schema.ny = indices.at("normal_y");
        schema.nz = indices.at("normal_z");
    }
    const auto rgb = indices.find("rgb");
    if (rgb != indices.end()) {
        const Field &field = header.fields[rgb->second];
        if (field.size != 4 ||
            (field.kind != Kind::Floating &&
             field.kind != Kind::Unsigned))
            throw std::invalid_argument(
                "PCD: rgb must be packed SIZE 4 TYPE F or U");
        schema.rgb = true;
        schema.rgb_index = rgb->second;
    }
    const auto intensity = indices.find("intensity");
    if (intensity != indices.end()) {
        schema.intensity = true;
        schema.intensity_index = intensity->second;
        const Field &field = header.fields[intensity->second];
        if (field.kind == Kind::Unsigned && field.size == 1)
            schema.intensity_range = "u8";
        else if (field.kind == Kind::Unsigned && field.size == 2)
            schema.intensity_range = "u16";
    }
    return schema;
}

template <typename T>
T load_le(const uint8_t *source) {
    static_assert(std::is_trivially_copyable_v<T>);
    std::array<uint8_t, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), source, sizeof(T));
    if (!host_is_le()) std::reverse(bytes.begin(), bytes.end());
    T value;
    std::memcpy(&value, bytes.data(), sizeof(T));
    return value;
}

float narrow_double(double value) {
    if (std::isfinite(value) &&
        std::fabs(value) >
            static_cast<double>(std::numeric_limits<float>::max()))
        throw std::invalid_argument(
            "PCD: finite floating value overflows float32");
    return static_cast<float>(value);
}

float binary_number(const uint8_t *source, const Field &field) {
    if (field.kind == Kind::Floating)
        return field.size == 4 ? load_le<float>(source)
                               : narrow_double(load_le<double>(source));
    if (field.kind == Kind::Signed) {
        switch (field.size) {
            case 1:
                return static_cast<float>(load_le<int8_t>(source));
            case 2:
                return static_cast<float>(load_le<int16_t>(source));
            case 4:
                return static_cast<float>(load_le<int32_t>(source));
            case 8:
                return static_cast<float>(load_le<int64_t>(source));
        }
    } else {
        switch (field.size) {
            case 1:
                return static_cast<float>(load_le<uint8_t>(source));
            case 2:
                return static_cast<float>(load_le<uint16_t>(source));
            case 4:
                return static_cast<float>(load_le<uint32_t>(source));
            case 8:
                return static_cast<float>(load_le<uint64_t>(source));
        }
    }
    throw std::logic_error("PCD: invalid scalar schema");
}

uint32_t binary_rgb(const uint8_t *source, const Field &field) {
    if (field.kind == Kind::Unsigned)
        return load_le<uint32_t>(source);
    const float packed = load_le<float>(source);
    uint32_t bits = 0;
    std::memcpy(&bits, &packed, sizeof(bits));
    return bits;
}

struct Tokens {
    const char *data;
    size_t size;
    size_t cursor = 0;

    bool next(std::string_view &result) {
        while (cursor < size &&
               (data[cursor] == ' ' || data[cursor] == '\t' ||
                data[cursor] == '\r' || data[cursor] == '\n' ||
                data[cursor] == '\v' || data[cursor] == '\f'))
            ++cursor;
        if (cursor == size) return false;
        const size_t begin = cursor;
        while (cursor < size &&
               data[cursor] != ' ' && data[cursor] != '\t' &&
               data[cursor] != '\r' && data[cursor] != '\n' &&
               data[cursor] != '\v' && data[cursor] != '\f')
            ++cursor;
        result = std::string_view(data + begin, cursor - begin);
        return true;
    }
};

template <typename T>
T parse_integer(std::string_view token, const char *what) {
    T value{};
    const auto result =
        std::from_chars(token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size())
        throw std::invalid_argument(
            std::string("PCD: malformed or out-of-range ") + what);
    return value;
}

float ascii_number(std::string_view token, const Field &field) {
    if (field.kind == Kind::Floating) {
        if (field.size == 4) {
            float value = 0.0f;
            const auto result = fast_float::from_chars(
                token.data(), token.data() + token.size(), value);
            if (result.ec != std::errc{} ||
                result.ptr != token.data() + token.size())
                throw std::invalid_argument(
                    "PCD: malformed or out-of-range floating value");
            return value;
        }
        double value = 0.0;
        const auto result = fast_float::from_chars(
            token.data(), token.data() + token.size(), value);
        if (result.ec != std::errc{} ||
            result.ptr != token.data() + token.size())
            throw std::invalid_argument(
                "PCD: malformed or out-of-range floating value");
        return narrow_double(value);
    }
    if (field.kind == Kind::Signed) {
        switch (field.size) {
            case 1:
                return static_cast<float>(
                    parse_integer<int8_t>(token, "signed integer"));
            case 2:
                return static_cast<float>(
                    parse_integer<int16_t>(token, "signed integer"));
            case 4:
                return static_cast<float>(
                    parse_integer<int32_t>(token, "signed integer"));
            case 8:
                return static_cast<float>(
                    parse_integer<int64_t>(token, "signed integer"));
        }
    } else {
        switch (field.size) {
            case 1:
                return static_cast<float>(
                    parse_integer<uint8_t>(token, "unsigned integer"));
            case 2:
                return static_cast<float>(
                    parse_integer<uint16_t>(token, "unsigned integer"));
            case 4:
                return static_cast<float>(
                    parse_integer<uint32_t>(token, "unsigned integer"));
            case 8:
                return static_cast<float>(
                    parse_integer<uint64_t>(token, "unsigned integer"));
        }
    }
    throw std::logic_error("PCD: invalid scalar schema");
}

uint32_t ascii_rgb(std::string_view token, const Field &field) {
    if (field.kind == Kind::Unsigned)
        return parse_integer<uint32_t>(token, "packed rgb");
    float packed = 0.0f;
    const auto result = fast_float::from_chars(
        token.data(), token.data() + token.size(), packed);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size())
        throw std::invalid_argument(
            "PCD: malformed packed rgb float");
    uint32_t bits = 0;
    std::memcpy(&bits, &packed, sizeof(bits));
    return bits;
}

void unpack_rgb(uint32_t packed, PointCloud &cloud, size_t row) {
    cloud.rgb[row * 3] = static_cast<uint8_t>((packed >> 16) & 0xff);
    cloud.rgb[row * 3 + 1] =
        static_cast<uint8_t>((packed >> 8) & 0xff);
    cloud.rgb[row * 3 + 2] = static_cast<uint8_t>(packed & 0xff);
}

void validate_lzf(
    const uint8_t *input, size_t input_size, size_t output_size) {
    size_t ip = 0;
    size_t op = 0;
    while (ip < input_size) {
        const uint8_t control = input[ip++];
        if (control < 32) {
            const size_t length = static_cast<size_t>(control) + 1;
            if (length > input_size - ip || length > output_size - op)
                throw std::invalid_argument(
                    "PCD: malformed LZF literal run");
            ip += length;
            op += length;
            continue;
        }
        size_t length = control >> 5;
        size_t distance = static_cast<size_t>(control & 0x1f) << 8;
        if (length == 7) {
            if (ip >= input_size)
                throw std::invalid_argument(
                    "PCD: truncated LZF match length");
            length += input[ip++];
        }
        if (ip >= input_size)
            throw std::invalid_argument(
                "PCD: truncated LZF match distance");
        distance += static_cast<size_t>(input[ip++]) + 1;
        length += 2;
        if (distance > op || length > output_size - op)
            throw std::invalid_argument(
                "PCD: invalid LZF back-reference");
        op += length;
    }
    if (op != output_size)
        throw std::invalid_argument(
            "PCD: LZF output size does not match header");
}

std::vector<uint8_t> lzf_decompress(
    const uint8_t *input, size_t input_size, size_t output_size) {
    // Validate the complete stream before allocating from its declared output
    // size. A malformed tiny payload therefore cannot trigger a large
    // allocation merely by claiming a large uncompressed extent.
    validate_lzf(input, input_size, output_size);
    std::vector<uint8_t> output(output_size);
    size_t ip = 0;
    size_t op = 0;
    while (ip < input_size) {
        const uint8_t control = input[ip++];
        if (control < 32) {
            const size_t length = static_cast<size_t>(control) + 1;
            std::memcpy(output.data() + op, input + ip, length);
            ip += length;
            op += length;
            continue;
        }
        size_t length = control >> 5;
        size_t distance = static_cast<size_t>(control & 0x1f) << 8;
        if (length == 7) length += input[ip++];
        distance += static_cast<size_t>(input[ip++]) + 1;
        length += 2;
        const size_t reference = op - distance;
        for (size_t i = 0; i < length; ++i)
            output[op++] = output[reference + i];
    }
    return output;
}

size_t lzf_hash(const uint8_t *value) {
    const uint32_t sequence =
        (static_cast<uint32_t>(value[0]) << 16) |
        (static_cast<uint32_t>(value[1]) << 8) |
        static_cast<uint32_t>(value[2]);
    return ((sequence * 2654435761u) >> 18) & (kLzfHashSize - 1);
}

std::vector<uint8_t> lzf_compress(
    const uint8_t *input, size_t size) {
    if (size == 0) return {};
    const size_t literal_overhead =
        size / 32 + (size % 32 == 0 ? 0 : 1);
    if (size >
        std::numeric_limits<size_t>::max() - literal_overhead)
        throw std::length_error("PCD: LZF output extent overflows size_t");
    std::vector<uint8_t> output;
    output.reserve(size + literal_overhead);
    std::vector<size_t> table(
        kLzfHashSize, std::numeric_limits<size_t>::max());

    auto literals = [&](size_t begin, size_t end) {
        while (begin < end) {
            const size_t length = std::min<size_t>(32, end - begin);
            output.push_back(static_cast<uint8_t>(length - 1));
            output.insert(
                output.end(), input + begin, input + begin + length);
            begin += length;
        }
    };

    size_t literal_begin = 0;
    size_t cursor = 0;
    while (cursor + 2 < size) {
        const size_t hash = lzf_hash(input + cursor);
        const size_t reference = table[hash];
        table[hash] = cursor;
        bool match = reference != std::numeric_limits<size_t>::max() &&
                     cursor > reference &&
                     cursor - reference <= kLzfWindow &&
                     input[reference] == input[cursor] &&
                     input[reference + 1] == input[cursor + 1] &&
                     input[reference + 2] == input[cursor + 2];
        if (!match) {
            ++cursor;
            if (cursor - literal_begin == 32) {
                literals(literal_begin, cursor);
                literal_begin = cursor;
            }
            continue;
        }

        literals(literal_begin, cursor);
        size_t length = 3;
        const size_t maximum =
            std::min({kLzfMaxMatch, size - cursor,
                      size - reference});
        while (length < maximum &&
               input[reference + length] == input[cursor + length])
            ++length;
        const size_t distance = cursor - reference - 1;
        const size_t encoded_length = length - 2;
        if (encoded_length < 7) {
            output.push_back(static_cast<uint8_t>(
                (encoded_length << 5) | (distance >> 8)));
        } else {
            output.push_back(static_cast<uint8_t>(
                (7 << 5) | (distance >> 8)));
            output.push_back(
                static_cast<uint8_t>(encoded_length - 7));
        }
        output.push_back(static_cast<uint8_t>(distance & 0xff));

        const size_t end = cursor + length;
        for (size_t pos = cursor + 1; pos + 2 < end; ++pos)
            table[lzf_hash(input + pos)] = pos;
        cursor = end;
        literal_begin = cursor;
    }
    literals(literal_begin, size);
    return output;
}

PointCloud allocate_cloud(
    const Header &header, const Schema &schema, size_t count, bool partial) {
    if (count > std::numeric_limits<size_t>::max() / 3)
        throw std::invalid_argument(
            "PCD: point count overflows PointCloud field extents");
    PointCloud cloud;
    cloud.n = count;
    cloud.xyz.resize(count * 3);
    if (schema.normals) cloud.normals.resize(count * 3);
    if (schema.rgb) cloud.rgb.resize(count * 3);
    if (schema.intensity) {
        cloud.intensity.resize(count);
        cloud.intensity_range = schema.intensity_range;
    }
    if (!partial) {
        cloud.organized_width = header.width;
        cloud.organized_height = header.height;
    }
    std::copy(
        header.viewpoint.begin(), header.viewpoint.end(), cloud.viewpoint);
    return cloud;
}

void decode_binary_rows(
    const Header &header, const Schema &schema, const uint8_t *body,
    bool soa, size_t start, size_t stop, PointCloud &cloud) {
    auto location = [&](size_t field, size_t row) {
        const Field &value = header.fields[field];
        return soa ? body + value.soa_offset + row * value.size
                   : body + row * header.stride + value.offset;
    };
    for (size_t source_row = start; source_row < stop; ++source_row) {
        const size_t row = source_row - start;
        cloud.xyz[row * 3] =
            binary_number(location(schema.x, source_row),
                          header.fields[schema.x]);
        cloud.xyz[row * 3 + 1] =
            binary_number(location(schema.y, source_row),
                          header.fields[schema.y]);
        cloud.xyz[row * 3 + 2] =
            binary_number(location(schema.z, source_row),
                          header.fields[schema.z]);
        if (schema.normals) {
            cloud.normals[row * 3] =
                binary_number(location(schema.nx, source_row),
                              header.fields[schema.nx]);
            cloud.normals[row * 3 + 1] =
                binary_number(location(schema.ny, source_row),
                              header.fields[schema.ny]);
            cloud.normals[row * 3 + 2] =
                binary_number(location(schema.nz, source_row),
                              header.fields[schema.nz]);
        }
        if (schema.rgb)
            unpack_rgb(
                binary_rgb(location(schema.rgb_index, source_row),
                           header.fields[schema.rgb_index]),
                cloud, row);
        if (schema.intensity)
            cloud.intensity[row] =
                binary_number(location(schema.intensity_index, source_row),
                              header.fields[schema.intensity_index]);
    }
}

PointCloud decode_pcd(
    const uint8_t *data, size_t size, bool partial,
    size_t start, size_t stop) {
    const Header header = parse_header(data, size);
    const Schema schema = validate_schema(header);
    if (header.body > size)
        throw std::logic_error("PCD: header body offset is invalid");
    const size_t body_size = size - header.body;
    const size_t raw_size = header.points * header.stride;

    if (partial) {
        if (header.storage != Storage::Binary)
            throw std::invalid_argument(
                "PCD: point ranges require uncompressed binary DATA");
        checked_half_open_range(start, stop, header.points, "PCD point range");
    } else {
        start = 0;
        stop = header.points;
    }
    const size_t count = stop - start;

    if (header.storage == Storage::ASCII) {
        if (partial)
            throw std::logic_error("PCD: ASCII partial read escaped guard");
        const size_t tokens_per_point = header.fields.size();
        if (tokens_per_point != 0) {
            const size_t maximum_tokens = (body_size + 1) / 2;
            if (header.points > maximum_tokens / tokens_per_point)
                throw std::invalid_argument(
                    "PCD: declared ASCII point count exceeds payload");
        }
        PointCloud cloud =
            allocate_cloud(header, schema, count, partial);
        Tokens tokens{
            reinterpret_cast<const char *>(data + header.body), body_size};
        for (size_t row = 0; row < header.points; ++row) {
            for (size_t field_index = 0;
                 field_index < header.fields.size(); ++field_index) {
                std::string_view token;
                if (!tokens.next(token))
                    throw std::invalid_argument(
                        "PCD: truncated ASCII payload");
                const Field &field = header.fields[field_index];
                if (field_index == schema.x)
                    cloud.xyz[row * 3] = ascii_number(token, field);
                else if (field_index == schema.y)
                    cloud.xyz[row * 3 + 1] = ascii_number(token, field);
                else if (field_index == schema.z)
                    cloud.xyz[row * 3 + 2] = ascii_number(token, field);
                else if (schema.normals && field_index == schema.nx)
                    cloud.normals[row * 3] = ascii_number(token, field);
                else if (schema.normals && field_index == schema.ny)
                    cloud.normals[row * 3 + 1] =
                        ascii_number(token, field);
                else if (schema.normals && field_index == schema.nz)
                    cloud.normals[row * 3 + 2] =
                        ascii_number(token, field);
                else if (schema.rgb && field_index == schema.rgb_index)
                    unpack_rgb(ascii_rgb(token, field), cloud, row);
                else if (schema.intensity &&
                         field_index == schema.intensity_index)
                    cloud.intensity[row] = ascii_number(token, field);
                else
                    throw std::logic_error(
                        "PCD: validated field was not decoded");
            }
        }
        std::string_view extra;
        if (tokens.next(extra))
            throw std::invalid_argument(
                "PCD: trailing ASCII payload");
        return cloud;
    }

    if (header.storage == Storage::Binary) {
        if (body_size != raw_size)
            throw std::invalid_argument(
                body_size < raw_size
                    ? "PCD: truncated binary payload"
                    : "PCD: trailing binary payload");
        PointCloud cloud =
            allocate_cloud(header, schema, count, partial);
        decode_binary_rows(
            header, schema, data + header.body, false, start, stop, cloud);
        return cloud;
    }

    if (raw_size > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "PCD: compressed payload exceeds the format's 32-bit size");
    if (body_size < 8)
        throw std::invalid_argument(
            "PCD: truncated compressed-size header");
    const uint32_t compressed_size =
        load_le<uint32_t>(data + header.body);
    const uint32_t uncompressed_size =
        load_le<uint32_t>(data + header.body + 4);
    if (uncompressed_size != raw_size)
        throw std::invalid_argument(
            "PCD: compressed uncompressed-size does not match schema");
    if (static_cast<size_t>(compressed_size) > body_size - 8 ||
        body_size - 8 != static_cast<size_t>(compressed_size))
        throw std::invalid_argument(
            body_size - 8 < static_cast<size_t>(compressed_size)
                ? "PCD: truncated compressed payload"
                : "PCD: trailing compressed payload");
    std::vector<uint8_t> raw = lzf_decompress(
        data + header.body + 8, compressed_size, raw_size);
    PointCloud cloud =
        allocate_cloud(header, schema, count, partial);
    decode_binary_rows(
        header, schema, raw.data(), true, 0, header.points, cloud);
    return cloud;
}

PointCloud read_pcd(nb::handle source) {
    ByteView view(source);
    PointCloud cloud;
    {
        nb::gil_scoped_release release;
        cloud = decode_pcd(view.data(), view.size(), false, 0, 0);
    }
    return cloud;
}

PointCloud read_pcd_points(
    nb::handle source, size_t start, size_t stop) {
    ByteView view(source);
    PointCloud cloud;
    {
        nb::gil_scoped_release release;
        cloud = decode_pcd(view.data(), view.size(), true, start, stop);
    }
    return cloud;
}

void validate_writer(const PointCloud &cloud) {
    if (cloud.n > std::numeric_limits<size_t>::max() / 3 ||
        cloud.xyz.size() != cloud.n * 3 ||
        (cloud.has_normals() &&
         cloud.normals.size() != cloud.n * 3) ||
        (cloud.has_rgb() && cloud.rgb.size() != cloud.n * 3) ||
        (cloud.has_rgb16() && cloud.rgb16.size() != cloud.n * 3) ||
        (cloud.has_intensity() &&
         cloud.intensity.size() != cloud.n))
        throw std::invalid_argument(
            "PCD: inconsistent PointCloud field lengths");
    if (cloud.has_rgb16())
        throw std::invalid_argument(
            "PCD: packed rgb is 8-bit; colors16 must be converted explicitly");
    if (cloud.coordinate_frame != "unknown" ||
        cloud.scale_to_meters != 1.0)
        throw std::invalid_argument(
            "PCD: coordinate frame and scale metadata are not representable");
    if (cloud.origin[0] != 0.0 || cloud.origin[1] != 0.0 ||
        cloud.origin[2] != 0.0)
        throw std::invalid_argument(
            "PCD: georeferenced origin is not representable");
    if (cloud.width() != 0 &&
        cloud.height() >
            std::numeric_limits<size_t>::max() / cloud.width())
        throw std::invalid_argument(
            "PCD: organized dimensions overflow size_t");
    if (cloud.width() * cloud.height() != cloud.n)
        throw std::invalid_argument(
            "PCD: organized dimensions do not match the point count");
    for (double value : cloud.viewpoint)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "PCD: viewpoint values must be finite");
    if (!cloud.has_intensity() &&
        cloud.intensity_range != "unknown")
        throw std::invalid_argument(
            "PCD: intensity range metadata has no intensity field");
    if (cloud.has_intensity() &&
        cloud.intensity_range == "unit")
        throw std::invalid_argument(
            "PCD: unit intensity semantics are not representable");
    if (cloud.has_intensity() &&
        (cloud.intensity_range == "u8" ||
         cloud.intensity_range == "u16")) {
        const float maximum =
            cloud.intensity_range == "u8" ? 255.0f : 65535.0f;
        for (float value : cloud.intensity)
            if (!std::isfinite(value) || value < 0.0f ||
                value > maximum || std::floor(value) != value)
                throw std::invalid_argument(
                    "PCD: integer intensity metadata requires exact in-range integers");
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
        throw std::runtime_error("PCD: float formatter failed");
    output.append(buffer, static_cast<size_t>(count));
}

void append_double(std::string &output, double value) {
    char buffer[64];
    const int count =
        std::snprintf(buffer, sizeof(buffer), "%.17g", value);
    if (count < 0 || static_cast<size_t>(count) >= sizeof(buffer))
        throw std::runtime_error("PCD: double formatter failed");
    output.append(buffer, static_cast<size_t>(count));
}

template <typename T>
void append_le(std::string &output, T value) {
    std::array<uint8_t, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), &value, sizeof(T));
    if (!host_is_le()) std::reverse(bytes.begin(), bytes.end());
    output.append(
        reinterpret_cast<const char *>(bytes.data()), bytes.size());
}

template <typename T>
void store_le(uint8_t *output, T value) {
    std::array<uint8_t, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), &value, sizeof(T));
    if (!host_is_le()) std::reverse(bytes.begin(), bytes.end());
    std::memcpy(output, bytes.data(), bytes.size());
}

uint32_t pack_rgb(const PointCloud &cloud, size_t row) {
    return (static_cast<uint32_t>(cloud.rgb[row * 3]) << 16) |
           (static_cast<uint32_t>(cloud.rgb[row * 3 + 1]) << 8) |
           static_cast<uint32_t>(cloud.rgb[row * 3 + 2]);
}

std::string make_header(
    const PointCloud &cloud, const std::string &storage) {
    std::string fields = "x y z";
    std::string sizes = "4 4 4";
    std::string types = "F F F";
    std::string counts = "1 1 1";
    if (cloud.has_normals()) {
        fields += " normal_x normal_y normal_z";
        sizes += " 4 4 4";
        types += " F F F";
        counts += " 1 1 1";
    }
    if (cloud.has_rgb()) {
        fields += " rgb";
        sizes += " 4";
        types += " U";
        counts += " 1";
    }
    if (cloud.has_intensity()) {
        fields += " intensity";
        sizes += cloud.intensity_range == "u8"
                     ? " 1"
                     : cloud.intensity_range == "u16" ? " 2" : " 4";
        types += cloud.intensity_range == "u8" ||
                         cloud.intensity_range == "u16"
                     ? " U"
                     : " F";
        counts += " 1";
    }
    std::string header =
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION .7\nFIELDS " +
        fields + "\nSIZE " + sizes + "\nTYPE " + types +
        "\nCOUNT " + counts + "\nWIDTH " +
        std::to_string(cloud.width()) + "\nHEIGHT " +
        std::to_string(cloud.height()) + "\nVIEWPOINT";
    for (double value : cloud.viewpoint) {
        header.push_back(' ');
        append_double(header, value);
    }
    header += "\nPOINTS " + std::to_string(cloud.n) +
              "\nDATA " + storage + "\n";
    return header;
}

struct WriterSchema {
    size_t stride = 12;
    size_t nx = 0;
    size_t rgb = 0;
    size_t intensity = 0;
    size_t intensity_size = 0;
};

WriterSchema writer_schema(const PointCloud &cloud) {
    WriterSchema schema;
    if (cloud.has_normals()) {
        schema.nx = schema.stride;
        schema.stride += 12;
    }
    if (cloud.has_rgb()) {
        schema.rgb = schema.stride;
        schema.stride += 4;
    }
    if (cloud.has_intensity()) {
        schema.intensity = schema.stride;
        schema.intensity_size =
            cloud.intensity_range == "u8"
                ? 1
                : cloud.intensity_range == "u16" ? 2 : 4;
        schema.stride += schema.intensity_size;
    }
    return schema;
}

void write_field(
    uint8_t *destination, const PointCloud &cloud,
    const WriterSchema &schema, size_t field, size_t row) {
    if (field < 3) {
        store_le(
            destination, cloud.xyz[row * 3 + field]);
        return;
    }
    size_t cursor = 3;
    if (cloud.has_normals()) {
        if (field < cursor + 3) {
            store_le(
                destination,
                cloud.normals[row * 3 + field - cursor]);
            return;
        }
        cursor += 3;
    }
    if (cloud.has_rgb()) {
        if (field == cursor) {
            store_le(destination, pack_rgb(cloud, row));
            return;
        }
        ++cursor;
    }
    if (cloud.has_intensity() && field == cursor) {
        const float value = cloud.intensity[row];
        if (schema.intensity_size == 1)
            store_le(destination, static_cast<uint8_t>(value));
        else if (schema.intensity_size == 2)
            store_le(destination, static_cast<uint16_t>(value));
        else
            store_le(destination, value);
        return;
    }
    throw std::logic_error("PCD: invalid writer field index");
}

std::vector<size_t> writer_field_sizes(
    const PointCloud &cloud, const WriterSchema &schema) {
    std::vector<size_t> sizes{4, 4, 4};
    if (cloud.has_normals())
        sizes.insert(sizes.end(), {4, 4, 4});
    if (cloud.has_rgb()) sizes.push_back(4);
    if (cloud.has_intensity())
        sizes.push_back(schema.intensity_size);
    return sizes;
}

void append_ascii_rows(
    std::string &output, const PointCloud &cloud,
    const WriterSchema &schema, size_t begin, size_t end) {
    for (size_t row = begin; row < end; ++row) {
        bool first = true;
        auto separator = [&]() {
            if (!first) output.push_back(' ');
            first = false;
        };
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
        if (cloud.has_rgb()) {
            separator();
            output += std::to_string(pack_rgb(cloud, row));
        }
        if (cloud.has_intensity()) {
            separator();
            if (schema.intensity_size == 1 ||
                schema.intensity_size == 2)
                output += std::to_string(
                    static_cast<uint32_t>(cloud.intensity[row]));
            else
                append_float(output, cloud.intensity[row]);
        }
        output.push_back('\n');
    }
}

void append_binary_rows(
    std::string &output, const PointCloud &cloud,
    const WriterSchema &schema,
    const std::vector<size_t> &field_sizes,
    size_t begin, size_t end) {
    const size_t rows = end - begin;
    if (rows != 0 &&
        schema.stride >
            (output.max_size() - output.size()) / rows)
        throw std::length_error(
            "PCD: encoded binary is too large");
    const size_t base = output.size();
    output.resize(base + rows * schema.stride);
    uint8_t *body =
        reinterpret_cast<uint8_t *>(output.data() + base);
    for (size_t row = begin; row < end; ++row) {
        size_t offset = 0;
        for (size_t field = 0; field < field_sizes.size(); ++field) {
            write_field(
                body + (row - begin) * schema.stride + offset,
                cloud, schema, field, row);
            offset += field_sizes[field];
        }
    }
}

std::string encode_pcd(
    const PointCloud &cloud, const std::string &storage) {
    validate_writer(cloud);
    if (storage != "ascii" && storage != "binary" &&
        storage != "binary_compressed")
        throw std::invalid_argument(
            "PCD: encoding must be ascii|binary|binary_compressed");
    std::string output = make_header(cloud, storage);
    const WriterSchema schema = writer_schema(cloud);

    if (storage == "ascii") {
        if (cloud.n >
            (output.max_size() - output.size()) / 160)
            throw std::length_error(
                "PCD: encoded text is too large");
        output.reserve(output.size() + cloud.n * 160);
        append_ascii_rows(output, cloud, schema, 0, cloud.n);
        return output;
    }

    if (cloud.n != 0 &&
        schema.stride >
            std::numeric_limits<size_t>::max() / cloud.n)
        throw std::length_error(
            "PCD: encoded binary extent overflows size_t");
    const size_t raw_size = cloud.n * schema.stride;
    const std::vector<size_t> field_sizes =
        writer_field_sizes(cloud, schema);

    if (storage == "binary") {
        append_binary_rows(
            output, cloud, schema, field_sizes, 0, cloud.n);
        return output;
    }

    if (raw_size > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "PCD: compressed payload exceeds the format's 32-bit size");
    std::vector<uint8_t> raw(raw_size);
    size_t soa_offset = 0;
    for (size_t field = 0; field < field_sizes.size(); ++field) {
        const size_t field_size = field_sizes[field];
        for (size_t row = 0; row < cloud.n; ++row)
            write_field(
                raw.data() + soa_offset + row * field_size,
                cloud, schema, field, row);
        soa_offset += field_size * cloud.n;
    }
    std::vector<uint8_t> compressed =
        lzf_compress(raw.data(), raw.size());
    if (compressed.size() > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "PCD: compressed payload exceeds the format's 32-bit size");
    if (output.size() > output.max_size() - 8 ||
        compressed.size() >
            output.max_size() - output.size() - 8)
        throw std::length_error(
            "PCD: encoded compressed output is too large");
    append_le(output, static_cast<uint32_t>(compressed.size()));
    append_le(output, static_cast<uint32_t>(raw.size()));
    if (!compressed.empty())
        output.append(
            reinterpret_cast<const char *>(compressed.data()),
            compressed.size());
    return output;
}

nb::bytes write_pcd(
    const PointCloud &cloud, const std::string &encoding) {
    // The public sink path streams ASCII and uncompressed binary in bounded
    // record chunks. Compressed PCD necessarily materializes its field-major
    // transform and LZF stream, but still avoids a second Python bytes object.
    if (active_file_sink &&
        (encoding == "ascii" || encoding == "binary")) {
        WriterSchema schema;
        std::vector<size_t> field_sizes;
        std::string header;
        {
            nb::gil_scoped_release release;
            validate_writer(cloud);
            schema = writer_schema(cloud);
            field_sizes = writer_field_sizes(cloud, schema);
            if (cloud.n != 0 &&
                schema.stride >
                    std::numeric_limits<size_t>::max() / cloud.n)
                throw std::length_error(
                    "PCD: encoded binary extent overflows size_t");
            header = make_header(cloud, encoding);
        }
        emit_file_chunk(header.data(), header.size());
        const size_t chunk_rows =
            encoding == "ascii" ? 4096 : 65536;
        for (size_t begin = 0; begin < cloud.n;) {
            const size_t end =
                begin + std::min(chunk_rows, cloud.n - begin);
            std::string chunk;
            {
                nb::gil_scoped_release release;
                if (encoding == "ascii") {
                    chunk.reserve((end - begin) * 160);
                    append_ascii_rows(
                        chunk, cloud, schema, begin, end);
                } else {
                    append_binary_rows(
                        chunk, cloud, schema, field_sizes, begin, end);
                }
            }
            emit_file_chunk(chunk.data(), chunk.size());
            begin = end;
        }
        return nb::bytes("", 0);
    }
    std::string output;
    {
        nb::gil_scoped_release release;
        output = encode_pcd(cloud, encoding);
    }
    return emit_bytes(output.data(), output.size());
}

}  // namespace

void register_pcd(nb::module_ &m) {
    m.def(
        "read_pcd", &read_pcd, "data"_a,
        "Decode PCD 0.7 ASCII, binary, or binary_compressed into PointCloud.");
    m.def(
        "read_pcd_points", &read_pcd_points,
        "data"_a, "start"_a, "stop"_a,
        "Decode a half-open point range from uncompressed binary PCD.");
    m.def(
        "write_pcd", &write_pcd, "cloud"_a,
        "_encoding"_a = "binary",
        "Encode PointCloud as deterministic PCD 0.7. The private encoding seam "
        "accepts ascii, binary, or binary_compressed.");
}
