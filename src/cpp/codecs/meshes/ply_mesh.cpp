// Polygon-preserving generic PLY mesh codec.
//
// The core subset accepts ASCII and binary little/big-endian PLY 1.0 with one
// vertex element and one face element. Standard vertex positions, normals,
// texture coordinates, and RGBA colors retain their vertex domain. SceneIO's
// documented face-list extensions retain independent corner normals, UVs, and
// RGBA colors without splitting vertices or triangulating polygons. Primitive
// and material ids are explicit face scalars. Unknown fidelity-bearing
// elements/properties reject instead of being discarded.
#include <nanobind/stl/string.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <string_view>
#include <unordered_map>
#include <unordered_set>

#include "fast_float/fast_float.h"
#include "io/common.hpp"
#include "records/mesh.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kHeaderLimit = 1024 * 1024;
constexpr size_t kTokenLimit = 1024 * 1024;

enum class Encoding { ASCII, BinaryLE, BinaryBE };
enum class Scalar { I8, U8, I16, U16, I32, U32, F32, F64 };

struct Property {
    bool list = false;
    Scalar type = Scalar::F32;
    Scalar count_type = Scalar::U8;
    Scalar item_type = Scalar::F32;
    std::string name;
};

struct Element {
    std::string name;
    size_t count = 0;
    std::vector<Property> properties;
};

struct Header {
    Encoding encoding = Encoding::ASCII;
    bool saw_format = false;
    size_t body = 0;
    std::vector<Element> elements;
    std::string coordinate_frame = "unknown";
    double scale_to_meters = 1.0;
    std::array<double, 16> transform = {
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    bool saw_frame = false;
    bool saw_scale = false;
    bool saw_transform = false;
};

struct VertexSchema {
    size_t x = 0, y = 0, z = 0;
    bool normals = false;
    size_t nx = 0, ny = 0, nz = 0;
    bool uvs = false;
    size_t u = 0, v = 0;
    bool colors = false;
    bool alpha = false;
    size_t red = 0, green = 0, blue = 0, alpha_index = 0;
};

struct FaceSchema {
    size_t indices = 0;
    bool corner_normals = false;
    size_t normals = 0;
    bool corner_uvs = false;
    size_t uvs = 0;
    bool corner_colors = false;
    size_t colors = 0;
    bool material = false;
    size_t material_index = 0;
    bool primitive = false;
    size_t primitive_index = 0;
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
    throw std::logic_error("PLY mesh: unknown scalar type");
}

bool scalar_integer(Scalar type) {
    return type == Scalar::I8 || type == Scalar::U8 ||
           type == Scalar::I16 || type == Scalar::U16 ||
           type == Scalar::I32 || type == Scalar::U32;
}

bool scalar_signed(Scalar type) {
    return type == Scalar::I8 || type == Scalar::I16 ||
           type == Scalar::I32;
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
        "PLY mesh: unsupported scalar type '" + std::string(value) + "'");
}

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

size_t parse_count(std::string_view token, const char *what) {
    if (token.empty() ||
        !std::all_of(
            token.begin(), token.end(),
            [](unsigned char value) {
                return value >= '0' && value <= '9';
            }))
        throw std::invalid_argument(
            std::string("PLY mesh: malformed ") + what);
    uint64_t value = 0;
    const auto parsed =
        std::from_chars(token.data(), token.data() + token.size(), value);
    if (parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size() ||
        value > std::numeric_limits<size_t>::max())
        throw std::invalid_argument(
            std::string("PLY mesh: ") + what + " is too large");
    return static_cast<size_t>(value);
}

double parse_double_token(std::string_view token, const char *what) {
    double value = 0.0;
    const auto parsed = fast_float::from_chars(
        token.data(), token.data() + token.size(), value);
    if (token.empty() || parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size() ||
        !std::isfinite(value))
        throw std::invalid_argument(
            std::string("PLY mesh: invalid ") + what);
    return value;
}

void parse_sceneio_comment(Header &header,
                           const std::vector<std::string_view> &words) {
    if (words.size() < 2 ||
        words[1].substr(0, 8) != "sceneio_")
        return;
    if (words[1] == "sceneio_coordinate_frame") {
        if (header.saw_frame || words.size() != 3)
            throw std::invalid_argument(
                "PLY mesh: malformed or duplicate coordinate-frame comment");
        header.coordinate_frame = std::string(words[2]);
        if (!mesh_valid_frame(header.coordinate_frame))
            throw std::invalid_argument(
                "PLY mesh: unsupported coordinate frame");
        header.saw_frame = true;
        return;
    }
    if (words[1] == "sceneio_scale_to_meters") {
        if (header.saw_scale || words.size() != 3)
            throw std::invalid_argument(
                "PLY mesh: malformed or duplicate scale comment");
        header.scale_to_meters =
            parse_double_token(words[2], "scale_to_meters");
        if (header.scale_to_meters <= 0.0)
            throw std::invalid_argument(
                "PLY mesh: scale_to_meters must be positive");
        header.saw_scale = true;
        return;
    }
    if (words[1] == "sceneio_local_transform") {
        if (header.saw_transform || words.size() != 18)
            throw std::invalid_argument(
                "PLY mesh: malformed or duplicate transform comment");
        for (size_t index = 0; index < 16; ++index)
            header.transform[index] =
                parse_double_token(words[index + 2], "transform value");
        header.saw_transform = true;
        return;
    }
    throw std::invalid_argument(
        "PLY mesh: unsupported SceneIO metadata comment '" +
        std::string(words[1]) + "'");
}

Header parse_header(const uint8_t *data, size_t size) {
    Header header;
    size_t cursor = 0;
    size_t header_bytes = 0;
    Element *current = nullptr;
    std::unordered_set<std::string> element_names;
    std::unordered_set<std::string> property_names;

    auto line = [&]() -> std::string_view {
        if (cursor >= size)
            throw std::invalid_argument("PLY mesh: missing end_header");
        const size_t begin = cursor;
        while (cursor < size && data[cursor] != '\n') {
            if (data[cursor] == 0)
                throw std::invalid_argument(
                    "PLY mesh: NUL byte in header");
            ++cursor;
            if (++header_bytes > kHeaderLimit)
                throw std::invalid_argument(
                    "PLY mesh: header exceeds 1 MiB");
        }
        if (cursor == size)
            throw std::invalid_argument(
                "PLY mesh: unterminated header line");
        ++cursor;
        if (++header_bytes > kHeaderLimit)
            throw std::invalid_argument(
                "PLY mesh: header exceeds 1 MiB");
        size_t end = cursor - 1;
        if (end > begin && data[end - 1] == '\r') --end;
        return std::string_view(
            reinterpret_cast<const char *>(data + begin), end - begin);
    };

    if (line() != "ply")
        throw std::invalid_argument("PLY mesh: missing 'ply' magic");
    while (true) {
        const auto words = split(line());
        if (words.empty())
            throw std::invalid_argument(
                "PLY mesh: blank header directive");
        const std::string_view directive = words[0];
        if (directive == "comment") {
            if (words.size() >= 2 &&
                (words[1] == "TextureFile" ||
                 words[1] == "texture_file"))
                throw std::invalid_argument(
                    "PLY mesh: texture-file comments require MaterialSet");
            parse_sceneio_comment(header, words);
            continue;
        }
        if (directive == "obj_info")
            throw std::invalid_argument(
                "PLY mesh: obj_info metadata cannot be preserved");
        if (directive == "format") {
            if (words.size() != 3 || words[2] != "1.0" ||
                header.saw_format || !header.elements.empty())
                throw std::invalid_argument(
                    "PLY mesh: malformed, duplicate, or misplaced format header");
            header.saw_format = true;
            if (words[1] == "ascii")
                header.encoding = Encoding::ASCII;
            else if (words[1] == "binary_little_endian")
                header.encoding = Encoding::BinaryLE;
            else if (words[1] == "binary_big_endian")
                header.encoding = Encoding::BinaryBE;
            else
                throw std::invalid_argument(
                    "PLY mesh: unsupported format");
        } else if (directive == "element") {
            if (words.size() != 3 || !header.saw_format)
                throw std::invalid_argument(
                    "PLY mesh: malformed or misplaced element header");
            const std::string name(words[1]);
            if (name.empty() || !element_names.insert(name).second)
                throw std::invalid_argument(
                    "PLY mesh: empty or duplicate element");
            header.elements.push_back(
                Element{name, parse_count(words[2], "element count"), {}});
            current = &header.elements.back();
            property_names.clear();
        } else if (directive == "property") {
            if (current == nullptr)
                throw std::invalid_argument(
                    "PLY mesh: property appears before an element");
            Property property;
            if (words.size() == 3) {
                property.type = parse_scalar(words[1]);
                property.name = std::string(words[2]);
            } else if (words.size() == 5 && words[1] == "list") {
                property.list = true;
                property.count_type = parse_scalar(words[2]);
                property.item_type = parse_scalar(words[3]);
                property.name = std::string(words[4]);
                if (!scalar_integer(property.count_type))
                    throw std::invalid_argument(
                        "PLY mesh: list count type must be integer");
            } else {
                throw std::invalid_argument(
                    "PLY mesh: malformed property header");
            }
            if (property.name.empty() ||
                !property_names.insert(property.name).second)
                throw std::invalid_argument(
                    "PLY mesh: empty or duplicate property");
            current->properties.push_back(std::move(property));
        } else if (directive == "end_header") {
            if (words.size() != 1)
                throw std::invalid_argument(
                    "PLY mesh: malformed end_header");
            header.body = cursor;
            break;
        } else {
            throw std::invalid_argument(
                "PLY mesh: unsupported header directive '" +
                std::string(directive) + "'");
        }
    }
    if (!header.saw_format)
        throw std::invalid_argument("PLY mesh: missing format header");
    if (header.elements.size() != 2 ||
        header.elements[0].name != "vertex" ||
        header.elements[1].name != "face")
        throw std::invalid_argument(
            "PLY mesh: elements must be exactly vertex then face");
    return header;
}

std::unordered_map<std::string, size_t> property_map(
    const Element &element) {
    std::unordered_map<std::string, size_t> result;
    for (size_t index = 0; index < element.properties.size(); ++index)
        result.emplace(element.properties[index].name, index);
    return result;
}

VertexSchema validate_vertex_schema(const Element &element) {
    const auto columns = property_map(element);
    const std::unordered_set<std::string> known = {
        "x", "y", "z", "nx", "ny", "nz",
        "texture_u", "texture_v", "u", "v", "s", "t",
        "red", "green", "blue", "alpha"};
    for (const Property &property : element.properties) {
        if (property.list)
            throw std::invalid_argument(
                "PLY mesh: list-valued vertex properties are unsupported");
        if (!known.count(property.name))
            throw std::invalid_argument(
                "PLY mesh: unsupported vertex property '" +
                property.name + "'");
    }
    auto required = [&](const char *name) {
        const auto found = columns.find(name);
        if (found == columns.end())
            throw std::invalid_argument(
                std::string("PLY mesh: missing vertex property '") +
                name + "'");
        return found->second;
    };
    VertexSchema schema;
    schema.x = required("x");
    schema.y = required("y");
    schema.z = required("z");

    const size_t normal_count =
        columns.count("nx") + columns.count("ny") +
        columns.count("nz");
    if (normal_count != 0 && normal_count != 3)
        throw std::invalid_argument(
            "PLY mesh: vertex normals require nx, ny, and nz");
    if (normal_count == 3) {
        schema.normals = true;
        schema.nx = columns.at("nx");
        schema.ny = columns.at("ny");
        schema.nz = columns.at("nz");
    }

    const std::array<std::pair<const char *, const char *>, 3>
        uv_pairs = {{{"texture_u", "texture_v"}, {"u", "v"}, {"s", "t"}}};
    size_t uv_groups = 0;
    for (const auto &names : uv_pairs) {
        const bool has_u = columns.count(names.first) != 0;
        const bool has_v = columns.count(names.second) != 0;
        if (has_u != has_v)
            throw std::invalid_argument(
                "PLY mesh: vertex UV coordinates require a complete pair");
        if (has_u) {
            ++uv_groups;
            schema.uvs = true;
            schema.u = columns.at(names.first);
            schema.v = columns.at(names.second);
        }
    }
    if (uv_groups > 1)
        throw std::invalid_argument(
            "PLY mesh: multiple vertex UV naming conventions are ambiguous");

    const size_t color_count =
        columns.count("red") + columns.count("green") +
        columns.count("blue");
    if (color_count != 0 && color_count != 3)
        throw std::invalid_argument(
            "PLY mesh: vertex colors require red, green, and blue");
    if (columns.count("alpha") && color_count != 3)
        throw std::invalid_argument(
            "PLY mesh: vertex alpha requires RGB");
    if (color_count == 3) {
        schema.colors = true;
        schema.alpha = columns.count("alpha") != 0;
        schema.red = columns.at("red");
        schema.green = columns.at("green");
        schema.blue = columns.at("blue");
        if (schema.alpha) schema.alpha_index = columns.at("alpha");
        for (size_t index : {
                 schema.red, schema.green, schema.blue,
                 schema.alpha ? schema.alpha_index : schema.red})
            if (element.properties[index].type != Scalar::U8)
                throw std::invalid_argument(
                    "PLY mesh: vertex RGBA must be uint8");
    }
    return schema;
}

FaceSchema validate_face_schema(const Element &element) {
    const auto columns = property_map(element);
    const std::unordered_set<std::string> known = {
        "vertex_indices", "vertex_index", "texcoord",
        "corner_normals", "corner_colors",
        "material_index", "primitive_index"};
    for (const Property &property : element.properties)
        if (!known.count(property.name))
            throw std::invalid_argument(
                "PLY mesh: unsupported face property '" +
                property.name + "'");
    if (columns.count("vertex_indices") +
            columns.count("vertex_index") !=
        1)
        throw std::invalid_argument(
            "PLY mesh: faces require exactly one vertex-index list");

    FaceSchema schema;
    schema.indices = columns.count("vertex_indices")
                         ? columns.at("vertex_indices")
                         : columns.at("vertex_index");
    const Property &indices = element.properties[schema.indices];
    if (!indices.list || !scalar_integer(indices.item_type))
        throw std::invalid_argument(
            "PLY mesh: vertex indices must be an integer list");

    auto list_property = [&](const char *name, bool &present,
                             size_t &index, bool integer) {
        const auto found = columns.find(name);
        if (found == columns.end()) return;
        present = true;
        index = found->second;
        const Property &property = element.properties[index];
        if (!property.list ||
            (integer ? property.item_type != Scalar::U8
                     : scalar_integer(property.item_type)))
            throw std::invalid_argument(
                std::string("PLY mesh: invalid ") + name +
                " list type");
    };
    list_property(
        "texcoord", schema.corner_uvs, schema.uvs, false);
    list_property(
        "corner_normals", schema.corner_normals,
        schema.normals, false);
    list_property(
        "corner_colors", schema.corner_colors,
        schema.colors, true);

    auto scalar_property = [&](const char *name, bool &present,
                               size_t &index) {
        const auto found = columns.find(name);
        if (found == columns.end()) return;
        present = true;
        index = found->second;
        const Property &property = element.properties[index];
        if (property.list || !scalar_integer(property.type))
            throw std::invalid_argument(
                std::string("PLY mesh: ") + name +
                " must be an integer scalar");
    };
    scalar_property(
        "material_index", schema.material, schema.material_index);
    scalar_property(
        "primitive_index", schema.primitive, schema.primitive_index);
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

class BinaryCursor {
public:
    BinaryCursor(const uint8_t *begin, const uint8_t *end, bool swap)
        : cursor_(begin), end_(end), swap_(swap) {}

    double number(Scalar type) {
        const size_t width = scalar_size(type);
        if (static_cast<size_t>(end_ - cursor_) < width)
            throw std::invalid_argument(
                "PLY mesh: truncated binary payload");
        double result = 0.0;
        switch (type) {
            case Scalar::I8:
                result = load_binary<int8_t>(cursor_, false);
                break;
            case Scalar::U8:
                result = load_binary<uint8_t>(cursor_, false);
                break;
            case Scalar::I16:
                result = load_binary<int16_t>(cursor_, swap_);
                break;
            case Scalar::U16:
                result = load_binary<uint16_t>(cursor_, swap_);
                break;
            case Scalar::I32:
                result = load_binary<int32_t>(cursor_, swap_);
                break;
            case Scalar::U32:
                result = load_binary<uint32_t>(cursor_, swap_);
                break;
            case Scalar::F32:
                result = load_binary<float>(cursor_, swap_);
                break;
            case Scalar::F64:
                result = load_binary<double>(cursor_, swap_);
                break;
        }
        cursor_ += width;
        return result;
    }

    bool at_end() const { return cursor_ == end_; }

private:
    const uint8_t *cursor_;
    const uint8_t *end_;
    bool swap_;
};

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
        throw std::invalid_argument(
            "PLY mesh: invalid signed integer token");
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
            "PLY mesh: invalid unsigned integer token");
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
            float value = 0.0f;
            const auto parsed = fast_float::from_chars(
                token.data(), token.data() + token.size(), value);
            if (token.empty() || parsed.ec != std::errc{} ||
                parsed.ptr != token.data() + token.size())
                throw std::invalid_argument(
                    "PLY mesh: invalid float32 token");
            return value;
        }
        case Scalar::F64:
            return parse_double_token(token, "float64 token");
    }
    throw std::logic_error("PLY mesh: unknown ASCII scalar type");
}

class AsciiTokens {
public:
    AsciiTokens(const uint8_t *begin, const uint8_t *end)
        : cursor_(reinterpret_cast<const char *>(begin)),
          end_(reinterpret_cast<const char *>(end)) {}

    std::string_view require() {
        while (cursor_ < end_ &&
               (*cursor_ == ' ' || *cursor_ == '\t' ||
                *cursor_ == '\r' || *cursor_ == '\n'))
            ++cursor_;
        if (cursor_ == end_)
            throw std::invalid_argument(
                "PLY mesh: truncated ASCII payload");
        const char *begin = cursor_;
        while (cursor_ < end_ && *cursor_ != ' ' &&
               *cursor_ != '\t' && *cursor_ != '\r' &&
               *cursor_ != '\n') {
            ++cursor_;
            if (static_cast<size_t>(cursor_ - begin) > kTokenLimit)
                throw std::invalid_argument(
                    "PLY mesh: ASCII token exceeds 1 MiB");
        }
        return std::string_view(
            begin, static_cast<size_t>(cursor_ - begin));
    }

    bool at_end() {
        while (cursor_ < end_ &&
               (*cursor_ == ' ' || *cursor_ == '\t' ||
                *cursor_ == '\r' || *cursor_ == '\n'))
            ++cursor_;
        return cursor_ == end_;
    }

private:
    const char *cursor_;
    const char *end_;
};

uint64_t checked_unsigned(double value, Scalar type, const char *what) {
    if (!scalar_integer(type) || scalar_signed(type) && value < 0.0 ||
        !std::isfinite(value) ||
        value > static_cast<double>(std::numeric_limits<uint32_t>::max()))
        throw std::invalid_argument(
            std::string("PLY mesh: invalid ") + what);
    return static_cast<uint64_t>(value);
}

int64_t checked_signed(double value, Scalar type, const char *what) {
    if (!scalar_integer(type) || !std::isfinite(value) ||
        value < static_cast<double>(std::numeric_limits<int32_t>::min()) ||
        value > static_cast<double>(std::numeric_limits<uint32_t>::max()))
        throw std::invalid_argument(
            std::string("PLY mesh: invalid ") + what);
    if (!scalar_signed(type) && value >
            static_cast<double>(std::numeric_limits<int32_t>::max()))
        throw std::invalid_argument(
            std::string("PLY mesh: ") + what + " exceeds int32 range");
    return static_cast<int64_t>(value);
}

float checked_float(double value, const char *what) {
    const float result = static_cast<float>(value);
    if (!std::isfinite(value) || !std::isfinite(result))
        throw std::invalid_argument(
            std::string("PLY mesh: invalid or out-of-range ") + what);
    return result;
}

template <typename Number>
Mesh decode_mesh(
    const Header &header, const VertexSchema &vertex_schema,
    const FaceSchema &face_schema, Number &&number,
    size_t body_size, bool partial, size_t start, size_t stop) {
    const Element &vertices = header.elements[0];
    const Element &faces = header.elements[1];
    if (partial)
        (void)checked_half_open_range(
            start, stop, faces.count, "PLY mesh face range");
    else {
        start = 0;
        stop = faces.count;
    }
    Mesh mesh;
    mesh.n = vertices.count;
    mesh.f = stop - start;
    mesh.coordinate_frame = header.coordinate_frame;
    mesh.scale_to_meters = header.scale_to_meters;
    std::copy(
        header.transform.begin(), header.transform.end(),
        mesh.local_transform);

    if (mesh.n > mesh.positions.max_size() / 3 ||
        mesh.f == std::numeric_limits<size_t>::max())
        throw std::length_error("PLY mesh: declared mesh is too large");
    mesh.positions.resize(mesh.n * 3);
    if (vertex_schema.normals)
        mesh.vertex_normals.resize(mesh.n * 3);
    if (vertex_schema.uvs) mesh.vertex_uvs.resize(mesh.n * 2);
    if (vertex_schema.colors)
        mesh.vertex_colors.resize(mesh.n * 4);

    for (size_t row = 0; row < mesh.n; ++row) {
        for (size_t property_index = 0;
             property_index < vertices.properties.size();
             ++property_index) {
            const Property &property =
                vertices.properties[property_index];
            const double value = number(property.type);
            auto field = [&](const char *name) {
                return checked_float(value, name);
            };
            if (property_index == vertex_schema.x)
                mesh.positions[row * 3] = field("vertex position");
            else if (property_index == vertex_schema.y)
                mesh.positions[row * 3 + 1] =
                    field("vertex position");
            else if (property_index == vertex_schema.z)
                mesh.positions[row * 3 + 2] =
                    field("vertex position");
            else if (vertex_schema.normals &&
                     property_index == vertex_schema.nx)
                mesh.vertex_normals[row * 3] =
                    field("vertex normal");
            else if (vertex_schema.normals &&
                     property_index == vertex_schema.ny)
                mesh.vertex_normals[row * 3 + 1] =
                    field("vertex normal");
            else if (vertex_schema.normals &&
                     property_index == vertex_schema.nz)
                mesh.vertex_normals[row * 3 + 2] =
                    field("vertex normal");
            else if (vertex_schema.uvs &&
                     property_index == vertex_schema.u)
                mesh.vertex_uvs[row * 2] =
                    field("vertex UV");
            else if (vertex_schema.uvs &&
                     property_index == vertex_schema.v)
                mesh.vertex_uvs[row * 2 + 1] =
                    field("vertex UV");
            else if (vertex_schema.colors &&
                     property_index == vertex_schema.red)
                mesh.vertex_colors[row * 4] = static_cast<uint8_t>(
                    checked_unsigned(value, property.type, "red"));
            else if (vertex_schema.colors &&
                     property_index == vertex_schema.green)
                mesh.vertex_colors[row * 4 + 1] = static_cast<uint8_t>(
                    checked_unsigned(value, property.type, "green"));
            else if (vertex_schema.colors &&
                     property_index == vertex_schema.blue)
                mesh.vertex_colors[row * 4 + 2] = static_cast<uint8_t>(
                    checked_unsigned(value, property.type, "blue"));
            else if (vertex_schema.alpha &&
                     property_index == vertex_schema.alpha_index)
                mesh.vertex_colors[row * 4 + 3] = static_cast<uint8_t>(
                    checked_unsigned(value, property.type, "alpha"));
        }
        if (vertex_schema.colors && !vertex_schema.alpha)
            mesh.vertex_colors[row * 4 + 3] = 255;
    }

    mesh.face_offsets.reserve(mesh.f + 1);
    mesh.face_offsets.push_back(0);
    std::vector<int32_t> face_materials;
    std::vector<uint32_t> face_primitives;
    if (face_schema.material) face_materials.reserve(mesh.f);
    if (face_schema.primitive) face_primitives.reserve(mesh.f);
    bool have_global_primitive = false;
    uint32_t last_global_primitive = 0;
    int32_t last_global_material = -1;

    for (size_t row = 0; row < faces.count; ++row) {
        const bool keep_face = row >= start && row < stop;
        std::vector<uint64_t> indices;
        std::vector<float> normals;
        std::vector<float> uvs;
        std::vector<uint8_t> colors;
        size_t index_count = 0;
        size_t normal_count = 0;
        size_t uv_count = 0;
        size_t color_count = 0;
        int32_t material = -1;
        uint32_t primitive = 0;

        for (size_t property_index = 0;
             property_index < faces.properties.size();
             ++property_index) {
            const Property &property = faces.properties[property_index];
            if (property.list) {
                const uint64_t count = checked_unsigned(
                    number(property.count_type), property.count_type,
                    "face list count");
                if (count > std::numeric_limits<size_t>::max())
                    throw std::length_error(
                        "PLY mesh: face list count is too large");
                const size_t item_count = static_cast<size_t>(count);
                const size_t maximum_items =
                    header.encoding == Encoding::ASCII
                        ? body_size == 0
                              ? 0
                              : 1 + (body_size - 1) / 2
                        : body_size / scalar_size(property.item_type);
                if (item_count > maximum_items)
                    throw std::invalid_argument(
                        "PLY mesh: face list count exceeds payload");
                if (property_index == face_schema.indices) {
                    if (count < 3)
                        throw std::invalid_argument(
                            "PLY mesh: every face needs at least three corners");
                    index_count = item_count;
                    if (keep_face) indices.reserve(item_count);
                    for (uint64_t item = 0; item < count; ++item) {
                        const uint64_t index = checked_unsigned(
                            number(property.item_type),
                            property.item_type, "vertex index");
                        if (index >= mesh.n)
                            throw std::invalid_argument(
                                "PLY mesh: face index is outside the vertex domain");
                        if (keep_face) indices.push_back(index);
                    }
                } else if (face_schema.corner_uvs &&
                           property_index == face_schema.uvs) {
                    uv_count = item_count;
                    if (keep_face) uvs.reserve(item_count);
                    for (uint64_t item = 0; item < count; ++item) {
                        const float value = checked_float(
                            number(property.item_type), "corner UV");
                        if (keep_face) uvs.push_back(value);
                    }
                } else if (face_schema.corner_normals &&
                           property_index == face_schema.normals) {
                    normal_count = item_count;
                    if (keep_face) normals.reserve(item_count);
                    for (uint64_t item = 0; item < count; ++item) {
                        const float value = checked_float(
                            number(property.item_type), "corner normal");
                        if (keep_face) normals.push_back(value);
                    }
                } else if (face_schema.corner_colors &&
                           property_index == face_schema.colors) {
                    color_count = item_count;
                    if (keep_face) colors.reserve(item_count);
                    for (uint64_t item = 0; item < count; ++item) {
                        const uint8_t value = static_cast<uint8_t>(
                            checked_unsigned(
                                number(property.item_type),
                                property.item_type,
                                "corner color"));
                        if (keep_face) colors.push_back(value);
                    }
                } else {
                    throw std::logic_error(
                        "PLY mesh: unclassified list property");
                }
            } else {
                const double value = number(property.type);
                if (face_schema.material &&
                    property_index == face_schema.material_index) {
                    const int64_t parsed = checked_signed(
                        value, property.type, "material index");
                    if (parsed < -1 ||
                        parsed > std::numeric_limits<int32_t>::max())
                        throw std::invalid_argument(
                            "PLY mesh: material index is outside -1..INT32_MAX");
                    material = static_cast<int32_t>(parsed);
                } else if (
                    face_schema.primitive &&
                    property_index == face_schema.primitive_index) {
                    primitive = static_cast<uint32_t>(checked_unsigned(
                        value, property.type, "primitive index"));
                } else {
                    throw std::logic_error(
                        "PLY mesh: unclassified scalar property");
                }
            }
        }

        const size_t corners = index_count;
        auto expected_list = [&](size_t actual, size_t components,
                                 const char *name) {
            if (actual != corners * components)
                throw std::invalid_argument(
                    std::string("PLY mesh: ") + name +
                    " list length does not match face corners");
        };
        if (face_schema.corner_uvs)
            expected_list(uv_count, 2, "texcoord");
        if (face_schema.corner_normals)
            expected_list(normal_count, 3, "corner_normals");
        if (face_schema.corner_colors)
            expected_list(color_count, 4, "corner_colors");
        if (face_schema.primitive) {
            if (!have_global_primitive) {
                if (primitive != 0)
                    throw std::invalid_argument(
                        "PLY mesh: primitive indices must start at zero");
                have_global_primitive = true;
            } else {
                const bool advances =
                    primitive != last_global_primitive;
                if (primitive < last_global_primitive ||
                    (advances &&
                     (last_global_primitive ==
                          std::numeric_limits<uint32_t>::max() ||
                      primitive != last_global_primitive + 1)))
                    throw std::invalid_argument(
                        "PLY mesh: primitive indices must form contiguous runs");
                if (primitive == last_global_primitive &&
                    material != last_global_material)
                    throw std::invalid_argument(
                        "PLY mesh: material changes inside a primitive");
            }
            last_global_primitive = primitive;
            last_global_material = material;
        }
        if (!keep_face) continue;
        if (mesh.face_indices.size() >
            mesh.face_indices.max_size() - corners)
            throw std::length_error(
                "PLY mesh: aggregate corner count is too large");
        mesh.face_indices.insert(
            mesh.face_indices.end(), indices.begin(), indices.end());
        mesh.corner_uvs.insert(
            mesh.corner_uvs.end(), uvs.begin(), uvs.end());
        mesh.corner_normals.insert(
            mesh.corner_normals.end(), normals.begin(), normals.end());
        mesh.corner_colors.insert(
            mesh.corner_colors.end(), colors.begin(), colors.end());
        mesh.face_offsets.push_back(mesh.face_indices.size());
        if (face_schema.material) face_materials.push_back(material);
        if (face_schema.primitive) face_primitives.push_back(primitive);
    }
    mesh.c = mesh.face_indices.size();

    mesh.primitive_offsets = {0};
    if (mesh.f != 0) {
        uint32_t current_primitive = 0;
        int32_t current_material =
            face_schema.material ? face_materials[0] : -1;
        if (face_schema.primitive) {
            current_primitive = face_primitives[0];
        }
        mesh.primitive_materials.push_back(current_material);
        for (size_t face = 1; face < mesh.f; ++face) {
            const int32_t material =
                face_schema.material ? face_materials[face] : -1;
            uint32_t primitive = current_primitive;
            if (face_schema.primitive) {
                primitive = face_primitives[face];
            } else if (material != current_material) {
                if (current_primitive ==
                    std::numeric_limits<uint32_t>::max())
                    throw std::length_error(
                        "PLY mesh: too many material runs");
                primitive = current_primitive + 1;
            }
            const bool advances = primitive != current_primitive;
            if (primitive < current_primitive ||
                (advances &&
                 (current_primitive ==
                      std::numeric_limits<uint32_t>::max() ||
                  primitive != current_primitive + 1)))
                throw std::invalid_argument(
                    "PLY mesh: primitive indices must form contiguous runs");
            if (primitive == current_primitive) {
                if (material != current_material)
                    throw std::invalid_argument(
                        "PLY mesh: material changes inside a primitive");
            } else {
                mesh.primitive_offsets.push_back(face);
                mesh.primitive_materials.push_back(material);
                current_primitive = primitive;
                current_material = material;
            }
        }
        mesh.primitive_offsets.push_back(mesh.f);
    }
    validate_mesh(mesh, "PLY mesh");
    return mesh;
}

void validate_payload_feasibility(
    const Header &header, const FaceSchema &face, size_t size) {
    const Element &vertices = header.elements[0];
    const Element &faces = header.elements[1];
    const size_t body_size = size - header.body;

    auto checked_product = [](size_t left, size_t right,
                              const char *what) {
        if (left != 0 &&
            right > std::numeric_limits<size_t>::max() / left)
            throw std::invalid_argument(
                std::string("PLY mesh: declared ") + what +
                " overflows address space");
        return left * right;
    };
    auto checked_sum = [](size_t left, size_t right,
                          const char *what) {
        if (right > std::numeric_limits<size_t>::max() - left)
            throw std::invalid_argument(
                std::string("PLY mesh: declared ") + what +
                " overflows address space");
        return left + right;
    };

    size_t vertex_units = 0;
    for (const Property &property : vertices.properties)
        vertex_units = checked_sum(
            vertex_units,
            header.encoding == Encoding::ASCII
                ? 1
                : scalar_size(property.type),
            "vertex extent");
    size_t face_units = 0;
    for (size_t property_index = 0;
         property_index < faces.properties.size(); ++property_index) {
        const Property &property = faces.properties[property_index];
        if (!property.list) {
            face_units = checked_sum(
                face_units,
                header.encoding == Encoding::ASCII
                    ? 1
                    : scalar_size(property.type),
                "face extent");
            continue;
        }
        const size_t minimum_items =
            property_index == face.indices
                ? 3
                : face.corner_uvs && property_index == face.uvs
                      ? 6
                      : face.corner_normals &&
                                property_index == face.normals
                            ? 9
                            : face.corner_colors &&
                                      property_index == face.colors
                                  ? 12
                                  : 0;
        const size_t list_units =
            header.encoding == Encoding::ASCII
                ? checked_sum(1, minimum_items, "face list extent")
                : checked_sum(
                      scalar_size(property.count_type),
                      checked_product(
                          minimum_items,
                          scalar_size(property.item_type),
                          "face list extent"),
                      "face list extent");
        face_units = checked_sum(
            face_units, list_units, "face extent");
    }
    const size_t minimum_units = checked_sum(
        checked_product(
            vertices.count, vertex_units, "vertex payload"),
        checked_product(faces.count, face_units, "face payload"),
        "payload extent");
    if (header.encoding == Encoding::ASCII) {
        // Every token occupies at least one byte and, except possibly the last,
        // one separator byte. This rejects impossible declarations before any
        // record-sized allocation.
        const size_t maximum_tokens =
            body_size == 0 ? 0 : 1 + (body_size - 1) / 2;
        if (minimum_units > maximum_tokens)
            throw std::invalid_argument(
                "PLY mesh: declared ASCII counts exceed payload");
    } else if (minimum_units > body_size) {
        throw std::invalid_argument(
            "PLY mesh: declared binary counts exceed payload");
    }
}

Mesh decode(const uint8_t *data, size_t size) {
    const Header header = parse_header(data, size);
    const VertexSchema vertex =
        validate_vertex_schema(header.elements[0]);
    const FaceSchema face =
        validate_face_schema(header.elements[1]);
    validate_payload_feasibility(header, face, size);

    if (header.encoding == Encoding::ASCII) {
        AsciiTokens tokens(data + header.body, data + size);
        Mesh result = decode_mesh(
            header, vertex, face,
            [&](Scalar type) {
                return ascii_number(tokens.require(), type);
            },
            size - header.body, false, 0, 0);
        if (!tokens.at_end())
            throw std::invalid_argument(
                "PLY mesh: trailing ASCII payload");
        return result;
    }
    const bool file_little = header.encoding == Encoding::BinaryLE;
    BinaryCursor cursor(
        data + header.body, data + size,
        file_little != host_is_le());
    Mesh result = decode_mesh(
        header, vertex, face,
        [&](Scalar type) { return cursor.number(type); },
        size - header.body, false, 0, 0);
    if (!cursor.at_end())
        throw std::invalid_argument(
            "PLY mesh: trailing binary payload");
    return result;
}

Mesh decode_faces(
    const uint8_t *data, size_t size, size_t start, size_t stop) {
    const Header header = parse_header(data, size);
    const VertexSchema vertex =
        validate_vertex_schema(header.elements[0]);
    const FaceSchema face =
        validate_face_schema(header.elements[1]);
    validate_payload_feasibility(header, face, size);
    // The partial path still parses and validates every record while retaining
    // only the selected face-domain buffers.
    if (header.encoding == Encoding::ASCII) {
        AsciiTokens tokens(data + header.body, data + size);
        Mesh result = decode_mesh(
            header, vertex, face,
            [&](Scalar type) {
                return ascii_number(tokens.require(), type);
            },
            size - header.body, true, start, stop);
        if (!tokens.at_end())
            throw std::invalid_argument(
                "PLY mesh: trailing ASCII payload");
        return result;
    }
    const bool file_little = header.encoding == Encoding::BinaryLE;
    BinaryCursor cursor(
        data + header.body, data + size,
        file_little != host_is_le());
    Mesh result = decode_mesh(
        header, vertex, face,
        [&](Scalar type) { return cursor.number(type); },
        size - header.body, true, start, stop);
    if (!cursor.at_end())
        throw std::invalid_argument(
            "PLY mesh: trailing binary payload");
    return result;
}

template <typename T>
void append_binary(std::string &output, T value) {
    std::array<uint8_t, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), &value, sizeof(T));
    if (!host_is_le()) std::reverse(bytes.begin(), bytes.end());
    output.append(
        reinterpret_cast<const char *>(bytes.data()), bytes.size());
}

std::string format_double(double value) {
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::setprecision(17) << value;
    return stream.str();
}

std::string encode(const Mesh &mesh) {
    validate_mesh(mesh, "PLY mesh writer");
    if (mesh.has_smoothing_groups() ||
        mesh.has_object_names() ||
        mesh.has_group_names() ||
        mesh.has_material_set)
        throw std::invalid_argument(
            "PLY mesh writer: smoothing, object/group names, and "
            "MaterialSet fields are not representable");
    if (mesh.n > std::numeric_limits<uint32_t>::max() ||
        mesh.f > std::numeric_limits<uint32_t>::max() ||
        mesh.num_primitives() >
            std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "PLY mesh writer: counts exceed the uint32 PLY subset");
    for (uint64_t index : mesh.face_indices)
        if (index > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "PLY mesh writer: vertex index exceeds uint32");

    std::string header =
        "ply\nformat binary_little_endian 1.0\n"
        "comment sceneio_coordinate_frame " +
        mesh.coordinate_frame +
        "\ncomment sceneio_scale_to_meters " +
        format_double(mesh.scale_to_meters) +
        "\ncomment sceneio_local_transform";
    for (double value : mesh.local_transform)
        header += " " + format_double(value);
    header += "\nelement vertex " + std::to_string(mesh.n) +
              "\nproperty float x\nproperty float y\nproperty float z\n";
    if (mesh.has_vertex_normals())
        header +=
            "property float nx\nproperty float ny\nproperty float nz\n";
    if (mesh.has_vertex_uvs())
        header += "property float texture_u\nproperty float texture_v\n";
    if (mesh.has_vertex_colors())
        header +=
            "property uchar red\nproperty uchar green\n"
            "property uchar blue\nproperty uchar alpha\n";
    header += "element face " + std::to_string(mesh.f) +
              "\nproperty list uint uint vertex_indices\n";
    if (mesh.has_corner_uvs())
        header += "property list uint float texcoord\n";
    if (mesh.has_corner_normals())
        header += "property list uint float corner_normals\n";
    if (mesh.has_corner_colors())
        header += "property list uint uchar corner_colors\n";
    header +=
        "property int material_index\nproperty uint primitive_index\n"
        "end_header\n";

    size_t vertex_stride = 12;
    if (mesh.has_vertex_normals()) vertex_stride += 12;
    if (mesh.has_vertex_uvs()) vertex_stride += 8;
    if (mesh.has_vertex_colors()) vertex_stride += 4;
    if (mesh.n >
        (std::numeric_limits<size_t>::max() - header.size()) /
            vertex_stride)
        throw std::length_error(
            "PLY mesh writer: output size overflows address space");
    size_t payload = mesh.n * vertex_stride;
    for (size_t face = 0; face < mesh.f; ++face) {
        const size_t corners = static_cast<size_t>(
            mesh.face_offsets[face + 1] - mesh.face_offsets[face]);
        if (corners > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "PLY mesh writer: polygon has more than uint32 corners");
        size_t face_size = 4 + corners * 4 + 8;
        if (mesh.has_corner_uvs()) face_size += 4 + corners * 8;
        if (mesh.has_corner_normals()) face_size += 4 + corners * 12;
        if (mesh.has_corner_colors()) face_size += 4 + corners * 4;
        if (payload > std::numeric_limits<size_t>::max() - face_size)
            throw std::length_error(
                "PLY mesh writer: output size overflows address space");
        payload += face_size;
    }
    if (header.size() > std::numeric_limits<size_t>::max() - payload)
        throw std::length_error(
            "PLY mesh writer: output size overflows address space");

    std::string output;
    output.reserve(header.size() + payload);
    output += header;
    for (size_t vertex = 0; vertex < mesh.n; ++vertex) {
        for (size_t component = 0; component < 3; ++component)
            append_binary(
                output, mesh.positions[vertex * 3 + component]);
        if (mesh.has_vertex_normals())
            for (size_t component = 0; component < 3; ++component)
                append_binary(
                    output,
                    mesh.vertex_normals[vertex * 3 + component]);
        if (mesh.has_vertex_uvs())
            for (size_t component = 0; component < 2; ++component)
                append_binary(
                    output, mesh.vertex_uvs[vertex * 2 + component]);
        if (mesh.has_vertex_colors())
            output.append(
                reinterpret_cast<const char *>(
                    mesh.vertex_colors.data() + vertex * 4),
                4);
    }

    size_t primitive = 0;
    for (size_t face = 0; face < mesh.f; ++face) {
        while (face >= mesh.primitive_offsets[primitive + 1])
            ++primitive;
        const size_t begin =
            static_cast<size_t>(mesh.face_offsets[face]);
        const size_t end =
            static_cast<size_t>(mesh.face_offsets[face + 1]);
        const uint32_t corners =
            static_cast<uint32_t>(end - begin);
        if ((mesh.has_corner_uvs() &&
             corners > std::numeric_limits<uint32_t>::max() / 2) ||
            (mesh.has_corner_normals() &&
             corners > std::numeric_limits<uint32_t>::max() / 3) ||
            (mesh.has_corner_colors() &&
             corners > std::numeric_limits<uint32_t>::max() / 4))
            throw std::invalid_argument(
                "PLY mesh writer: corner attribute list exceeds uint32");
        append_binary(output, corners);
        for (size_t corner = begin; corner < end; ++corner)
            append_binary(
                output,
                static_cast<uint32_t>(mesh.face_indices[corner]));
        if (mesh.has_corner_uvs()) {
            append_binary(output, corners * 2);
            for (size_t index = begin * 2; index < end * 2; ++index)
                append_binary(output, mesh.corner_uvs[index]);
        }
        if (mesh.has_corner_normals()) {
            append_binary(output, corners * 3);
            for (size_t index = begin * 3; index < end * 3; ++index)
                append_binary(output, mesh.corner_normals[index]);
        }
        if (mesh.has_corner_colors()) {
            append_binary(output, corners * 4);
            output.append(
                reinterpret_cast<const char *>(
                    mesh.corner_colors.data() + begin * 4),
                (end - begin) * 4);
        }
        append_binary(output, mesh.primitive_materials[primitive]);
        append_binary(output, static_cast<uint32_t>(primitive));
    }
    return output;
}

Mesh read_ply_mesh(nb::handle source) {
    ByteView view(source);
    Mesh result;
    {
        nb::gil_scoped_release release;
        result = decode(view.data(), view.size());
    }
    return result;
}

Mesh read_ply_mesh_faces(
    nb::handle source, size_t start, size_t stop) {
    ByteView view(source);
    Mesh result;
    {
        nb::gil_scoped_release release;
        result = decode_faces(view.data(), view.size(), start, stop);
    }
    return result;
}

nb::bytes write_ply_mesh(const Mesh &mesh) {
    std::string output;
    {
        nb::gil_scoped_release release;
        output = encode(mesh);
    }
    return emit_bytes(output.data(), output.size());
}

}  // namespace

void register_ply_mesh(nb::module_ &module) {
    module.def(
        "read_ply_mesh", &read_ply_mesh, "data"_a,
        "Decode a polygon-preserving ASCII or binary PLY mesh.");
    module.def(
        "read_ply_mesh_faces", &read_ply_mesh_faces,
        "data"_a, "start"_a, "stop"_a,
        "Decode a face range while retaining the complete vertex domain.");
    module.def(
        "write_ply_mesh", &write_ply_mesh, "mesh"_a,
        "Encode a Mesh as deterministic binary little-endian PLY.");
}
