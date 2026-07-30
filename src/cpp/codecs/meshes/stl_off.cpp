// codecs/meshes/stl_off.cpp -- strict STL triangle-soup and polygonal ASCII OFF.
//
// STL is decoded without welding: every stored triangle corner becomes one
// Mesh vertex, preserving the format's lack of connectivity. Facet normals
// map to three identical corner normals. An all-zero normal stream is the
// canonical "no normals" representation. Writers reject indexed/shared
// topology or non-uniform corner normals rather than silently changing Mesh
// domains.
//
// OFF preserves indexed polygon boundaries. The ASCII OFF, NOFF, COFF,
// CNOFF, STOFF, STNOFF, STCOFF, and STCNOFF variants map exactly to Mesh
// vertex positions, normals, RGBA8 colors, and UVs. Binary OFF, face colors,
// homogeneous/n-dimensional vertices, and other Mesh metadata reject.
#include <nanobind/stl/string.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <limits>
#include <locale.h>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <vector>

#include "fast_float/fast_float.h"
#include "io/common.hpp"
#include "records/mesh.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kLineLimit = 1024 * 1024;
constexpr size_t kChunkFaces = 4096;
constexpr size_t kChunkVertices = 4096;
constexpr size_t kOffChunkFaces = 32768;

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

template <typename T>
void append_le(std::string &output, T value) {
    static_assert(std::is_trivially_copyable_v<T>);
    std::array<uint8_t, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), &value, sizeof(T));
    if (!host_is_le()) std::reverse(bytes.begin(), bytes.end());
    output.append(
        reinterpret_cast<const char *>(bytes.data()), bytes.size());
}

bool token_space(char value) {
    return value == ' ' || value == '\t' ||
           value == '\r' || value == '\v' ||
           value == '\f';
}

class TextLines {
public:
    TextLines(
        const uint8_t *data, size_t size,
        const char *context, bool comments)
        : text_(
              reinterpret_cast<const char *>(data), size),
          context_(context),
          comments_(comments) {
        if (text_.find('\0') != std::string_view::npos)
            throw std::invalid_argument(
                std::string(context_) + ": embedded NUL");
        if (!valid_utf8(text_))
            throw std::invalid_argument(
                std::string(context_) +
                ": input is not valid UTF-8");
    }

    bool next(
        std::vector<std::string_view> &result,
        size_t &line_number) {
        result.clear();
        while (cursor_ < text_.size()) {
            const size_t begin = cursor_;
            const size_t newline =
                text_.find('\n', cursor_);
            const size_t end =
                newline == std::string_view::npos
                    ? text_.size()
                    : newline;
            cursor_ =
                newline == std::string_view::npos
                    ? text_.size()
                    : newline + 1;
            ++line_number_;
            size_t length = end - begin;
            if (length != 0 &&
                text_[begin + length - 1] == '\r')
                --length;
            if (length > kLineLimit)
                throw std::invalid_argument(
                    std::string(context_) +
                    ": line exceeds 1 MiB");
            std::string_view line =
                text_.substr(begin, length);
            if (line_number_ == 1 &&
                line.size() >= 3 &&
                static_cast<uint8_t>(line[0]) == 0xEF &&
                static_cast<uint8_t>(line[1]) == 0xBB &&
                static_cast<uint8_t>(line[2]) == 0xBF)
                line.remove_prefix(3);
            if (comments_) {
                const size_t comment = line.find('#');
                if (comment != std::string_view::npos)
                    line = line.substr(0, comment);
            }
            size_t token_cursor = 0;
            while (token_cursor < line.size()) {
                while (
                    token_cursor < line.size() &&
                    token_space(line[token_cursor]))
                    ++token_cursor;
                if (token_cursor == line.size()) break;
                const size_t token_begin = token_cursor;
                while (
                    token_cursor < line.size() &&
                    !token_space(line[token_cursor]))
                    ++token_cursor;
                result.push_back(line.substr(
                    token_begin,
                    token_cursor - token_begin));
            }
            if (!result.empty()) {
                line_number = line_number_;
                return true;
            }
        }
        return false;
    }

private:
    std::string_view text_;
    const char *context_;
    bool comments_;
    size_t cursor_ = 0;
    size_t line_number_ = 0;
};

bool ascii_iequal(
    std::string_view value, std::string_view expected) {
    if (value.size() != expected.size()) return false;
    for (size_t index = 0; index < value.size(); ++index) {
        char character = value[index];
        if (character >= 'A' && character <= 'Z')
            character = static_cast<char>(
                character - 'A' + 'a');
        if (character != expected[index]) return false;
    }
    return true;
}

[[noreturn]] void text_error(
    const char *context, size_t line,
    const std::string &message) {
    throw std::invalid_argument(
        std::string(context) + " line " +
        std::to_string(line) + ": " + message);
}

float parse_float32(
    std::string_view token, const char *context,
    size_t line) {
    double parsed_value = 0.0;
    const auto parsed = fast_float::from_chars(
        token.data(), token.data() + token.size(),
        parsed_value);
    const float value = static_cast<float>(parsed_value);
    if (token.empty() ||
        parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size() ||
        !std::isfinite(parsed_value) ||
        !std::isfinite(value))
        text_error(
            context, line,
            "invalid or out-of-range float32 value");
    return value;
}

uint64_t parse_u64(
    std::string_view token, const char *context,
    size_t line) {
    uint64_t value = 0;
    const auto parsed = std::from_chars(
        token.data(), token.data() + token.size(),
        value);
    if (token.empty() ||
        parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size())
        text_error(
            context, line,
            "invalid nonnegative integer");
    return value;
}

size_t decimal_digits(uint64_t value) {
    if (value < 10ULL) return 1;
    if (value < 100ULL) return 2;
    if (value < 1000ULL) return 3;
    if (value < 10000ULL) return 4;
    if (value < 100000ULL) return 5;
    if (value < 1000000ULL) return 6;
    if (value < 10000000ULL) return 7;
    if (value < 100000000ULL) return 8;
    if (value < 1000000000ULL) return 9;
    if (value < 10000000000ULL) return 10;
    if (value < 100000000000ULL) return 11;
    if (value < 1000000000000ULL) return 12;
    if (value < 10000000000000ULL) return 13;
    if (value < 100000000000000ULL) return 14;
    if (value < 1000000000000000ULL) return 15;
    if (value < 10000000000000000ULL) return 16;
    if (value < 100000000000000000ULL) return 17;
    if (value < 1000000000000000000ULL) return 18;
    if (value < 10000000000000000000ULL) return 19;
    return 20;
}

class FloatAppender {
public:
    explicit FloatAppender(std::string &output)
        : output_(output) {
#ifdef _WIN32
        locale_ = _create_locale(LC_NUMERIC, "C");
        if (locale_ == nullptr)
            throw std::runtime_error(
                "mesh text writer: cannot create C numeric locale");
#else
        locale_ = newlocale(
            LC_NUMERIC_MASK, "C", nullptr);
        if (locale_ == nullptr)
            throw std::runtime_error(
                "mesh text writer: cannot create C numeric locale");
        previous_locale_ = uselocale(locale_);
        if (previous_locale_ == static_cast<locale_t>(0)) {
            freelocale(locale_);
            locale_ = static_cast<locale_t>(0);
            throw std::runtime_error(
                "mesh text writer: cannot activate C numeric locale");
        }
#endif
    }

    FloatAppender(const FloatAppender &) = delete;
    FloatAppender &operator=(const FloatAppender &) = delete;

    ~FloatAppender() {
#ifdef _WIN32
        _free_locale(locale_);
#else
        if (previous_locale_ != static_cast<locale_t>(0))
            (void)uselocale(previous_locale_);
        if (locale_ != static_cast<locale_t>(0))
            freelocale(locale_);
#endif
    }

    void append(float value) {
        char buffer[64];
#ifdef _WIN32
        const int count = _snprintf_l(
            buffer, sizeof(buffer), "%.9g", locale_,
            static_cast<double>(value));
#else
        const int count = std::snprintf(
            buffer, sizeof(buffer), "%.9g",
            static_cast<double>(value));
#endif
        if (count < 0 ||
            static_cast<size_t>(count) >= sizeof(buffer))
            throw std::runtime_error(
                "mesh text writer: float formatting failed");
        output_.append(buffer, static_cast<size_t>(count));
    }

private:
    std::string &output_;
#ifdef _WIN32
    _locale_t locale_ = nullptr;
#else
    locale_t locale_ = static_cast<locale_t>(0);
    locale_t previous_locale_ = static_cast<locale_t>(0);
#endif
};

bool identity_transform(const double *values) {
    static constexpr double identity[16] = {
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    return std::equal(
        std::begin(identity), std::end(identity),
        values);
}

void validate_common_mesh_metadata(
    const Mesh &mesh, const char *format) {
    validate_mesh(mesh, format);
    require_no_extended_mesh_fields(mesh, format);
    const std::string prefix =
        std::string(format) + " writer: ";
    if (mesh.coordinate_frame != "unknown" ||
        mesh.scale_to_meters != 1.0 ||
        !identity_transform(mesh.local_transform))
        throw std::invalid_argument(
            prefix +
            "coordinate frame, scale, and transform metadata "
            "are not representable");
    if (mesh.has_smoothing_groups())
        throw std::invalid_argument(
            prefix +
            "face smoothing groups are not representable");
    if (mesh.has_object_names() ||
        mesh.has_group_names())
        throw std::invalid_argument(
            prefix +
            "primitive object/group names are not representable");
    if (mesh.has_material_set)
        throw std::invalid_argument(
            prefix + "MaterialSet is not representable");
    if (mesh.num_primitives() > (mesh.f == 0 ? 0 : 1))
        throw std::invalid_argument(
            prefix +
            "multiple primitive ranges are not representable");
    for (int32_t material : mesh.primitive_materials)
        if (material != -1)
            throw std::invalid_argument(
                prefix +
                "material indices are not representable");
}

void finish_triangle_soup(
    Mesh &mesh, size_t faces, bool keep_normals) {
    mesh.f = faces;
    if (faces >
        std::numeric_limits<size_t>::max() / 3)
        throw std::length_error(
            "STL: selected triangle count is too large");
    mesh.n = faces * 3;
    mesh.c = mesh.n;
    if (!keep_normals) mesh.corner_normals.clear();
    mesh.primitive_offsets = {0};
    if (faces != 0) {
        mesh.primitive_offsets.push_back(faces);
        mesh.primitive_materials.push_back(-1);
    }
    validate_mesh(mesh, "STL");
}

void append_stl_triangle(
    Mesh &mesh,
    const std::array<float, 3> &normal,
    const std::array<float, 9> &vertices) {
    const uint64_t begin =
        static_cast<uint64_t>(mesh.positions.size() / 3);
    mesh.positions.insert(
        mesh.positions.end(),
        vertices.begin(), vertices.end());
    mesh.face_indices.push_back(begin);
    mesh.face_indices.push_back(begin + 1);
    mesh.face_indices.push_back(begin + 2);
    mesh.face_offsets.push_back(
        static_cast<uint64_t>(
            mesh.face_indices.size()));
    for (size_t corner = 0; corner < 3; ++corner)
        mesh.corner_normals.insert(
            mesh.corner_normals.end(),
            normal.begin(), normal.end());
}

struct StlResult {
    Mesh mesh;
    size_t faces = 0;
    bool binary = false;
    bool has_normals = false;
};

bool stl_is_binary(
    const uint8_t *data, size_t size,
    uint32_t &faces) {
    if (size < 84) return false;
    faces = load_le<uint32_t>(data + 80);
    if (faces >
        (std::numeric_limits<size_t>::max() - 84) / 50)
        return false;
    return 84 + static_cast<size_t>(faces) * 50 == size;
}

StlResult parse_binary_stl(
    const uint8_t *data, size_t size,
    bool collect,
    std::optional<std::pair<size_t, size_t>> selection) {
    uint32_t declared = 0;
    if (!stl_is_binary(data, size, declared))
        throw std::invalid_argument(
            "STL: binary length does not match triangle count");
    size_t start = 0;
    size_t stop = declared;
    if (selection) {
        start = selection->first;
        stop = selection->second;
        (void)checked_half_open_range(
            start, stop, declared, "STL face range");
    }
    StlResult result;
    result.faces = declared;
    result.binary = true;
    if (collect) {
        const size_t selected = stop - start;
        if (selected >
            std::numeric_limits<size_t>::max() / 9)
            throw std::length_error(
                "STL: selected triangle arrays are too large");
        result.mesh.positions.reserve(selected * 9);
        result.mesh.face_offsets.reserve(selected + 1);
        result.mesh.face_offsets.push_back(0);
        result.mesh.face_indices.reserve(selected * 3);
        result.mesh.corner_normals.reserve(selected * 9);
    }
    bool any_normal = false;
    for (size_t face = 0; face < declared; ++face) {
        const uint8_t *record =
            data + 84 + face * 50;
        std::array<float, 3> normal{};
        std::array<float, 9> vertices{};
        for (size_t component = 0; component < 3; ++component)
            normal[component] =
                load_le<float>(record + component * 4);
        for (size_t component = 0; component < 9; ++component)
            vertices[component] =
                load_le<float>(record + 12 + component * 4);
        for (float value : normal)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "STL: non-finite binary facet normal");
        for (float value : vertices)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "STL: non-finite binary vertex coordinate");
        if (load_le<uint16_t>(record + 48) != 0)
            throw std::invalid_argument(
                "STL: nonzero binary facet attributes/colors "
                "are unsupported");
        any_normal |=
            normal[0] != 0.0F ||
            normal[1] != 0.0F ||
            normal[2] != 0.0F;
        if (collect && face >= start && face < stop)
            append_stl_triangle(
                result.mesh, normal, vertices);
    }
    result.has_normals = any_normal;
    if (collect)
        finish_triangle_soup(
            result.mesh, stop - start, any_normal);
    return result;
}

StlResult parse_ascii_stl(
    const uint8_t *data, size_t size,
    bool collect,
    std::optional<std::pair<size_t, size_t>> selection) {
    TextLines lines(data, size, "STL", false);
    std::vector<std::string_view> tokens;
    size_t line = 0;
    if (!lines.next(tokens, line) ||
        !ascii_iequal(tokens[0], "solid"))
        throw std::invalid_argument(
            "STL: ASCII input must begin with solid");
    StlResult result;
    result.binary = false;
    if (collect) result.mesh.face_offsets.push_back(0);
    bool ended = false;
    bool any_normal = false;
    while (lines.next(tokens, line)) {
        if (ascii_iequal(tokens[0], "endsolid")) {
            ended = true;
            break;
        }
        if (tokens.size() != 5 ||
            !ascii_iequal(tokens[0], "facet") ||
            !ascii_iequal(tokens[1], "normal"))
            text_error(
                "STL", line,
                "expected 'facet normal nx ny nz'");
        std::array<float, 3> normal{};
        for (size_t component = 0; component < 3; ++component)
            normal[component] = parse_float32(
                tokens[component + 2], "STL", line);
        any_normal |=
            normal[0] != 0.0F ||
            normal[1] != 0.0F ||
            normal[2] != 0.0F;

        size_t record_line = 0;
        if (!lines.next(tokens, record_line) ||
            tokens.size() != 2 ||
            !ascii_iequal(tokens[0], "outer") ||
            !ascii_iequal(tokens[1], "loop"))
            text_error(
                "STL", record_line == 0 ? line : record_line,
                "expected 'outer loop'");
        std::array<float, 9> vertices{};
        for (size_t vertex = 0; vertex < 3; ++vertex) {
            if (!lines.next(tokens, record_line) ||
                tokens.size() != 4 ||
                !ascii_iequal(tokens[0], "vertex"))
                text_error(
                    "STL",
                    record_line == 0 ? line : record_line,
                    "expected three vertex records");
            for (size_t component = 0;
                 component < 3; ++component)
                vertices[vertex * 3 + component] =
                    parse_float32(
                        tokens[component + 1],
                        "STL", record_line);
        }
        if (!lines.next(tokens, record_line) ||
            tokens.size() != 1 ||
            !ascii_iequal(tokens[0], "endloop"))
            text_error(
                "STL", record_line == 0 ? line : record_line,
                "expected endloop");
        if (!lines.next(tokens, record_line) ||
            tokens.size() != 1 ||
            !ascii_iequal(tokens[0], "endfacet"))
            text_error(
                "STL", record_line == 0 ? line : record_line,
                "expected endfacet");
        if (result.faces ==
            std::numeric_limits<size_t>::max())
            throw std::length_error(
                "STL: triangle count is too large");
        const size_t face = result.faces++;
        if (collect &&
            (!selection ||
             (face >= selection->first &&
              face < selection->second)))
            append_stl_triangle(
                result.mesh, normal, vertices);
    }
    if (!ended)
        throw std::invalid_argument(
            "STL: ASCII input is missing endsolid");
    if (lines.next(tokens, line))
        text_error(
            "STL", line,
            "trailing records after endsolid");
    size_t start = 0;
    size_t stop = result.faces;
    if (selection) {
        start = selection->first;
        stop = selection->second;
        (void)checked_half_open_range(
            start, stop, result.faces,
            "STL face range");
    }
    result.has_normals = any_normal;
    if (collect)
        finish_triangle_soup(
            result.mesh, stop - start, any_normal);
    return result;
}

StlResult parse_stl(
    const uint8_t *data, size_t size,
    bool collect,
    std::optional<std::pair<size_t, size_t>> selection =
        std::nullopt) {
    uint32_t binary_faces = 0;
    if (stl_is_binary(data, size, binary_faces))
        return parse_binary_stl(
            data, size, collect, selection);
    return parse_ascii_stl(
        data, size, collect, selection);
}

void validate_stl_write(const Mesh &mesh) {
    validate_common_mesh_metadata(mesh, "STL");
    if (mesh.f >
        std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "STL writer: triangle count exceeds uint32");
    if (mesh.has_vertex_normals())
        throw std::invalid_argument(
            "STL writer: vertex normals are not facet normals");
    if (mesh.has_vertex_uvs() ||
        mesh.has_corner_uvs() ||
        mesh.has_vertex_colors() ||
        mesh.has_corner_colors())
        throw std::invalid_argument(
            "STL writer: UVs and colors are not representable");
    if (mesh.n != mesh.c)
        throw std::invalid_argument(
            "STL writer: Mesh must use one distinct vertex per "
            "triangle corner");
    bool any_attached_normal = false;
    for (size_t face = 0; face < mesh.f; ++face) {
        const uint64_t begin = mesh.face_offsets[face];
        const uint64_t end = mesh.face_offsets[face + 1];
        if (end - begin != 3)
            throw std::invalid_argument(
                "STL writer: every face must be a triangle");
        for (uint64_t corner = begin; corner < end; ++corner)
            if (mesh.face_indices[static_cast<size_t>(corner)] !=
                corner)
                throw std::invalid_argument(
                    "STL writer: indexed/shared topology is not "
                    "representable by lossless triangle soup");
        if (!mesh.has_corner_normals()) continue;
        const size_t first =
            static_cast<size_t>(begin) * 3;
        any_attached_normal |=
            mesh.corner_normals[first] != 0.0F ||
            mesh.corner_normals[first + 1] != 0.0F ||
            mesh.corner_normals[first + 2] != 0.0F;
        for (size_t corner = 1; corner < 3; ++corner)
            if (std::memcmp(
                    mesh.corner_normals.data() + first,
                    mesh.corner_normals.data() +
                        first + corner * 3,
                    3 * sizeof(float)) != 0)
                throw std::invalid_argument(
                    "STL writer: each triangle requires one "
                    "bit-identical facet normal");
    }
    if (mesh.has_corner_normals() &&
        !any_attached_normal)
        throw std::invalid_argument(
            "STL writer: an attached all-zero normal stream is "
            "indistinguishable from absent normals");
}

std::array<float, 3> stl_face_normal(
    const Mesh &mesh, size_t face) {
    if (!mesh.has_corner_normals())
        return {0.0F, 0.0F, 0.0F};
    const size_t begin =
        static_cast<size_t>(mesh.face_offsets[face]) * 3;
    return {
        mesh.corner_normals[begin],
        mesh.corner_normals[begin + 1],
        mesh.corner_normals[begin + 2],
    };
}

std::string stl_binary_header(const Mesh &mesh) {
    std::string output(80, '\0');
    static constexpr std::string_view label =
        "SceneIO deterministic binary STL";
    std::copy(
        label.begin(), label.end(), output.begin());
    append_le(
        output, static_cast<uint32_t>(mesh.f));
    return output;
}

void append_binary_stl_faces(
    std::string &output, const Mesh &mesh,
    size_t begin_face, size_t end_face) {
    output.reserve(
        output.size() +
        (end_face - begin_face) * 50);
    for (size_t face = begin_face;
         face < end_face; ++face) {
        const auto normal =
            stl_face_normal(mesh, face);
        for (float value : normal)
            append_le(output, value);
        const size_t begin =
            static_cast<size_t>(
                mesh.face_offsets[face]);
        for (size_t corner = 0; corner < 3; ++corner) {
            const size_t vertex =
                static_cast<size_t>(
                    mesh.face_indices[begin + corner]);
            for (size_t component = 0;
                 component < 3; ++component)
                append_le(
                    output,
                    mesh.positions[
                        vertex * 3 + component]);
        }
        append_le(output, uint16_t{0});
    }
}

void append_ascii_stl_faces(
    std::string &output, const Mesh &mesh,
    size_t begin_face, size_t end_face) {
    FloatAppender floats(output);
    for (size_t face = begin_face;
         face < end_face; ++face) {
        const auto normal =
            stl_face_normal(mesh, face);
        output += "  facet normal";
        for (float value : normal) {
            output.push_back(' ');
            floats.append(value);
        }
        output += "\n    outer loop\n";
        const size_t begin =
            static_cast<size_t>(
                mesh.face_offsets[face]);
        for (size_t corner = 0; corner < 3; ++corner) {
            const size_t vertex =
                static_cast<size_t>(
                    mesh.face_indices[begin + corner]);
            output += "      vertex";
            for (size_t component = 0;
                 component < 3; ++component) {
                output.push_back(' ');
                floats.append(
                    mesh.positions[
                        vertex * 3 + component]);
            }
            output.push_back('\n');
        }
        output += "    endloop\n  endfacet\n";
    }
}

nb::bytes write_stl(
    const Mesh &mesh, const std::string &encoding) {
    {
        nb::gil_scoped_release release;
        validate_stl_write(mesh);
    }
    if (encoding != "binary" && encoding != "ascii")
        throw std::invalid_argument(
            "STL writer: encoding must be 'binary' or 'ascii'");
    const bool binary = encoding == "binary";
    const std::string header =
        binary
            ? stl_binary_header(mesh)
            : std::string("solid SceneIO\n");
    if (!emit_file_chunk(header.data(), header.size())) {
        std::string output = header;
        {
            nb::gil_scoped_release release;
            if (binary)
                append_binary_stl_faces(
                    output, mesh, 0, mesh.f);
            else {
                append_ascii_stl_faces(
                    output, mesh, 0, mesh.f);
                output += "endsolid SceneIO\n";
            }
        }
        return nb::bytes(output.data(), output.size());
    }
    for (size_t begin = 0; begin < mesh.f;
         begin += kChunkFaces) {
        const size_t end =
            std::min(mesh.f, begin + kChunkFaces);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            if (binary)
                append_binary_stl_faces(
                    chunk, mesh, begin, end);
            else
                append_ascii_stl_faces(
                    chunk, mesh, begin, end);
        }
        emit_file_chunk(chunk.data(), chunk.size());
    }
    if (!binary) {
        static constexpr std::string_view footer =
            "endsolid SceneIO\n";
        emit_file_chunk(footer.data(), footer.size());
    }
    return nb::bytes("", 0);
}

Mesh read_stl(nb::handle source) {
    ByteView view(source);
    Mesh result;
    {
        nb::gil_scoped_release release;
        result = parse_stl(
            view.data(), view.size(), true).mesh;
    }
    return result;
}

Mesh read_stl_faces(
    nb::handle source, size_t start, size_t stop) {
    ByteView view(source);
    Mesh result;
    {
        nb::gil_scoped_release release;
        result = parse_stl(
            view.data(), view.size(), true,
            std::pair<size_t, size_t>{start, stop}).mesh;
    }
    return result;
}

nb::dict inspect_stl(nb::handle source) {
    ByteView view(source);
    StlResult inspected;
    {
        nb::gil_scoped_release release;
        inspected = parse_stl(
            view.data(), view.size(), false);
    }
    nb::dict result;
    result["encoding"] =
        inspected.binary ? "binary" : "ascii";
    if (inspected.faces >
        std::numeric_limits<size_t>::max() / 3)
        throw std::length_error(
            "STL: triangle count is too large");
    result["num_vertices"] = inspected.faces * 3;
    result["num_faces"] = inspected.faces;
    result["num_corners"] = inspected.faces * 3;
    result["has_facet_normals"] =
        inspected.has_normals;
    return result;
}

struct OffFlags {
    bool normals = false;
    bool colors = false;
    bool uvs = false;
    std::string variant;
};

OffFlags off_flags(std::string_view value) {
    OffFlags result;
    result.variant = std::string(value);
    if (value == "OFF") return result;
    if (value == "NOFF") {
        result.normals = true;
        return result;
    }
    if (value == "COFF") {
        result.colors = true;
        return result;
    }
    if (value == "CNOFF") {
        result.colors = true;
        result.normals = true;
        return result;
    }
    if (value == "STOFF") {
        result.uvs = true;
        return result;
    }
    if (value == "STNOFF") {
        result.uvs = true;
        result.normals = true;
        return result;
    }
    if (value == "STCOFF") {
        result.uvs = true;
        result.colors = true;
        return result;
    }
    if (value == "STCNOFF") {
        result.uvs = true;
        result.colors = true;
        result.normals = true;
        return result;
    }
    throw std::invalid_argument(
        "OFF: unsupported header variant '" +
        std::string(value) + "'");
}

std::array<uint8_t, 4> parse_off_color(
    const std::vector<std::string_view> &tokens,
    size_t begin, size_t line) {
    std::array<uint64_t, 4> integers{};
    bool all_integers = true;
    bool any_above_one = false;
    for (size_t component = 0; component < 4; ++component) {
        const std::string_view token =
            tokens[begin + component];
        const auto parsed = std::from_chars(
            token.data(), token.data() + token.size(),
            integers[component]);
        if (token.empty() ||
            parsed.ec != std::errc{} ||
            parsed.ptr != token.data() + token.size()) {
            all_integers = false;
            break;
        }
        any_above_one |= integers[component] > 1;
    }
    std::array<uint8_t, 4> result{};
    if (all_integers && any_above_one) {
        for (size_t component = 0; component < 4; ++component) {
            if (integers[component] > 255)
                text_error(
                    "OFF", line,
                    "integer vertex color is outside 0..255");
            result[component] =
                static_cast<uint8_t>(integers[component]);
        }
        return result;
    }
    for (size_t component = 0; component < 4; ++component) {
        const float value = parse_float32(
            tokens[begin + component], "OFF", line);
        if (value < 0.0F || value > 1.0F)
            text_error(
                "OFF", line,
                "normalized vertex color is outside 0..1");
        const float scaled = value * 255.0F;
        const float rounded = std::round(scaled);
        const uint8_t byte =
            static_cast<uint8_t>(rounded);
        if (static_cast<float>(byte) / 255.0F != value)
            text_error(
                "OFF", line,
                "vertex color is not exactly representable as RGBA8");
        result[component] = byte;
    }
    return result;
}

struct OffResult {
    Mesh mesh;
    OffFlags flags;
    size_t vertices = 0;
    size_t faces = 0;
    size_t corners = 0;
    uint64_t declared_edges = 0;
};

OffResult parse_off(
    const uint8_t *data, size_t size,
    bool collect,
    std::optional<std::pair<size_t, size_t>> selection =
        std::nullopt,
    bool validate_payload = true) {
    TextLines lines(data, size, "OFF", true);
    std::vector<std::string_view> tokens;
    size_t line = 0;
    if (!lines.next(tokens, line))
        throw std::invalid_argument("OFF: empty input");
    OffResult result;
    result.flags = off_flags(tokens[0]);
    std::vector<std::string_view> counts;
    size_t counts_line = line;
    if (tokens.size() == 1) {
        if (!lines.next(counts, counts_line))
            throw std::invalid_argument(
                "OFF: missing counts record");
    } else {
        counts.assign(tokens.begin() + 1, tokens.end());
    }
    if (counts.size() != 3)
        text_error(
            "OFF", counts_line,
            "counts require vertices, faces, and edges");
    const uint64_t vertices_u64 =
        parse_u64(counts[0], "OFF", counts_line);
    const uint64_t faces_u64 =
        parse_u64(counts[1], "OFF", counts_line);
    result.declared_edges =
        parse_u64(counts[2], "OFF", counts_line);
    if (vertices_u64 >
            std::numeric_limits<size_t>::max() ||
        faces_u64 >
            std::numeric_limits<size_t>::max())
        throw std::length_error(
            "OFF: declared counts exceed size_t");
    result.vertices = static_cast<size_t>(vertices_u64);
    result.faces = static_cast<size_t>(faces_u64);
    // Even the shortest valid records need "0 0 0\n" per vertex and
    // "3 0 0 0\n" per face. Reject impossible declarations before reserve()
    // so malformed tiny inputs cannot request enormous allocations.
    if (result.vertices > size / 6 ||
        result.faces > size / 8)
        throw std::invalid_argument(
            "OFF: declared counts exceed the input extent");
    size_t start = 0;
    size_t stop = result.faces;
    if (selection) {
        start = selection->first;
        stop = selection->second;
        (void)checked_half_open_range(
            start, stop, result.faces,
            "OFF face range");
    }

    const size_t values_per_vertex =
        3 + (result.flags.normals ? 3 : 0) +
        (result.flags.colors ? 4 : 0) +
        (result.flags.uvs ? 2 : 0);
    if (collect) {
        if (result.vertices >
            std::numeric_limits<size_t>::max() / 3)
            throw std::length_error(
                "OFF: vertex arrays are too large");
        result.mesh.n = result.vertices;
        result.mesh.positions.reserve(result.vertices * 3);
        if (result.flags.normals)
            result.mesh.vertex_normals.reserve(
                result.vertices * 3);
        if (result.flags.colors)
            result.mesh.vertex_colors.reserve(
                result.vertices * 4);
        if (result.flags.uvs)
            result.mesh.vertex_uvs.reserve(
                result.vertices * 2);
        result.mesh.face_offsets.reserve(
            stop - start + 1);
        result.mesh.face_indices.reserve(
            (stop - start) * 3);
        result.mesh.face_offsets.push_back(0);
    }
    for (size_t vertex = 0;
         vertex < result.vertices; ++vertex) {
        if (!lines.next(tokens, line))
            throw std::invalid_argument(
                "OFF: truncated vertex table");
        if (tokens.size() != values_per_vertex)
            text_error(
                "OFF", line,
                "vertex field count disagrees with header variant");
        if (!collect && !validate_payload) continue;
        size_t cursor = 0;
        std::array<float, 3> position{};
        for (float &value : position)
            value = parse_float32(
                tokens[cursor++], "OFF", line);
        std::array<float, 3> normal{};
        if (result.flags.normals)
            for (float &value : normal)
                value = parse_float32(
                    tokens[cursor++], "OFF", line);
        std::array<uint8_t, 4> color{};
        if (result.flags.colors) {
            color = parse_off_color(
                tokens, cursor, line);
            cursor += 4;
        }
        std::array<float, 2> uv{};
        if (result.flags.uvs)
            for (float &value : uv)
                value = parse_float32(
                    tokens[cursor++], "OFF", line);
        if (!collect) continue;
        result.mesh.positions.insert(
            result.mesh.positions.end(),
            position.begin(), position.end());
        if (result.flags.normals)
            result.mesh.vertex_normals.insert(
                result.mesh.vertex_normals.end(),
                normal.begin(), normal.end());
        if (result.flags.colors)
            result.mesh.vertex_colors.insert(
                result.mesh.vertex_colors.end(),
                color.begin(), color.end());
        if (result.flags.uvs)
            result.mesh.vertex_uvs.insert(
                result.mesh.vertex_uvs.end(),
                uv.begin(), uv.end());
    }

    size_t selected_corners = 0;
    for (size_t face = 0; face < result.faces; ++face) {
        if (!lines.next(tokens, line))
            throw std::invalid_argument(
                "OFF: truncated face table");
        if (tokens.empty())
            text_error(
                "OFF", line, "empty face record");
        const uint64_t corners_u64 =
            parse_u64(tokens[0], "OFF", line);
        if (corners_u64 < 3)
            text_error(
                "OFF", line,
                "every face requires at least three corners");
        if (corners_u64 >
            std::numeric_limits<size_t>::max() - 1)
            throw std::length_error(
                "OFF: face corner count is too large");
        const size_t face_corners =
            static_cast<size_t>(corners_u64);
        if (tokens.size() != face_corners + 1)
            text_error(
                "OFF", line,
                "face colors or trailing fields are unsupported");
        if (face_corners >
            std::numeric_limits<size_t>::max() -
                result.corners)
            throw std::length_error(
                "OFF: aggregate corner count is too large");
        result.corners += face_corners;
        const bool selected =
            face >= start && face < stop;
        if (selected &&
            face_corners >
                std::numeric_limits<size_t>::max() -
                    selected_corners)
            throw std::length_error(
                "OFF: selected corner count is too large");
        if (!collect && !validate_payload) continue;
        for (size_t corner = 0;
             corner < face_corners; ++corner) {
            const uint64_t index =
                parse_u64(
                    tokens[corner + 1], "OFF", line);
            if (index >= result.vertices)
                text_error(
                    "OFF", line,
                    "face index is outside the vertex domain");
            if (collect && selected)
                result.mesh.face_indices.push_back(index);
        }
        if (collect && selected) {
            selected_corners += face_corners;
            result.mesh.face_offsets.push_back(
                static_cast<uint64_t>(selected_corners));
        }
    }
    if (lines.next(tokens, line))
        text_error(
            "OFF", line,
            "trailing records after declared face table");
    if (collect) {
        result.mesh.f = stop - start;
        result.mesh.c = selected_corners;
        result.mesh.primitive_offsets = {0};
        if (result.mesh.f != 0) {
            result.mesh.primitive_offsets.push_back(
                result.mesh.f);
            result.mesh.primitive_materials.push_back(-1);
        }
        validate_mesh(result.mesh, "OFF");
    }
    return result;
}

void validate_off_write(const Mesh &mesh) {
    validate_common_mesh_metadata(mesh, "OFF");
    if (mesh.has_corner_normals() ||
        mesh.has_corner_uvs() ||
        mesh.has_corner_colors())
        throw std::invalid_argument(
            "OFF writer: corner-domain attributes are not "
            "representable by the supported vertex variants");
    const uint64_t maximum =
        static_cast<uint64_t>(
            std::numeric_limits<int32_t>::max());
    if (mesh.n > maximum || mesh.f > maximum ||
        mesh.c > maximum)
        throw std::invalid_argument(
            "OFF writer: counts exceed the signed 32-bit "
            "interchange domain");
    for (size_t face = 0; face < mesh.f; ++face) {
        const uint64_t begin = mesh.face_offsets[face];
        const uint64_t end = mesh.face_offsets[face + 1];
        if (mesh.face_offsets[face + 1] -
                mesh.face_offsets[face] >
            maximum)
            throw std::invalid_argument(
                "OFF writer: face size exceeds the signed "
                "32-bit interchange domain");
        size_t line_size =
            decimal_digits(end - begin) + 1;
        for (uint64_t corner = begin; corner < end; ++corner) {
            const uint64_t index =
                mesh.face_indices[static_cast<size_t>(corner)];
            const size_t digits = decimal_digits(index);
            if (line_size >
                kLineLimit - 1 - digits)
                throw std::invalid_argument(
                    "OFF writer: face record exceeds the "
                    "1 MiB parser limit");
            line_size += 1 + digits;
        }
    }
    for (uint64_t index : mesh.face_indices)
        if (index > maximum)
            throw std::invalid_argument(
                "OFF writer: vertex index exceeds the signed "
                "32-bit interchange domain");
}

std::string off_variant(const Mesh &mesh) {
    std::string result;
    if (mesh.has_vertex_uvs()) result += "ST";
    if (mesh.has_vertex_colors()) result += "C";
    if (mesh.has_vertex_normals()) result += "N";
    result += "OFF";
    return result;
}

std::string off_header(const Mesh &mesh) {
    return off_variant(mesh) + "\n" +
           std::to_string(mesh.n) + " " +
           std::to_string(mesh.f) + " 0\n";
}

void append_off_vertices(
    std::string &output, const Mesh &mesh,
    size_t begin_vertex, size_t end_vertex) {
    FloatAppender floats(output);
    for (size_t vertex = begin_vertex;
         vertex < end_vertex; ++vertex) {
        for (size_t component = 0;
             component < 3; ++component) {
            if (component != 0) output.push_back(' ');
            floats.append(
                mesh.positions[
                    vertex * 3 + component]);
        }
        if (mesh.has_vertex_normals())
            for (size_t component = 0;
                 component < 3; ++component) {
                output.push_back(' ');
                floats.append(
                    mesh.vertex_normals[
                        vertex * 3 + component]);
            }
        if (mesh.has_vertex_colors())
            for (size_t component = 0;
                 component < 4; ++component) {
                output.push_back(' ');
                floats.append(
                    static_cast<float>(
                        mesh.vertex_colors[
                            vertex * 4 + component]) /
                    255.0F);
            }
        if (mesh.has_vertex_uvs())
            for (size_t component = 0;
                 component < 2; ++component) {
                output.push_back(' ');
                floats.append(
                    mesh.vertex_uvs[
                        vertex * 2 + component]);
            }
        output.push_back('\n');
    }
}

void append_off_faces(
    std::string &output, const Mesh &mesh,
    size_t begin_face, size_t end_face) {
    for (size_t face = begin_face;
         face < end_face; ++face) {
        const size_t begin =
            static_cast<size_t>(
                mesh.face_offsets[face]);
        const size_t end =
            static_cast<size_t>(
                mesh.face_offsets[face + 1]);
        output += std::to_string(end - begin);
        for (size_t corner = begin;
             corner < end; ++corner)
            output += " " +
                      std::to_string(
                          mesh.face_indices[corner]);
        output.push_back('\n');
    }
}

nb::bytes write_off(const Mesh &mesh) {
    {
        nb::gil_scoped_release release;
        validate_off_write(mesh);
    }
    const std::string header = off_header(mesh);
    if (!emit_file_chunk(header.data(), header.size())) {
        std::string output = header;
        {
            nb::gil_scoped_release release;
            append_off_vertices(
                output, mesh, 0, mesh.n);
            append_off_faces(
                output, mesh, 0, mesh.f);
        }
        return nb::bytes(output.data(), output.size());
    }
    for (size_t begin = 0; begin < mesh.n;
         begin += kChunkVertices) {
        const size_t end =
            std::min(mesh.n, begin + kChunkVertices);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            append_off_vertices(
                chunk, mesh, begin, end);
        }
        emit_file_chunk(chunk.data(), chunk.size());
    }
    for (size_t begin = 0; begin < mesh.f;
         begin += kOffChunkFaces) {
        const size_t end =
            std::min(mesh.f, begin + kOffChunkFaces);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            append_off_faces(
                chunk, mesh, begin, end);
        }
        emit_file_chunk(chunk.data(), chunk.size());
    }
    return nb::bytes("", 0);
}

Mesh read_off(nb::handle source) {
    ByteView view(source);
    Mesh result;
    {
        nb::gil_scoped_release release;
        result = parse_off(
            view.data(), view.size(), true).mesh;
    }
    return result;
}

Mesh read_off_faces(
    nb::handle source, size_t start, size_t stop) {
    ByteView view(source);
    Mesh result;
    {
        nb::gil_scoped_release release;
        result = parse_off(
            view.data(), view.size(), true,
            std::pair<size_t, size_t>{start, stop}).mesh;
    }
    return result;
}

nb::dict inspect_off(nb::handle source) {
    ByteView view(source);
    OffResult inspected;
    {
        nb::gil_scoped_release release;
        inspected = parse_off(
            view.data(), view.size(), false,
            std::nullopt, false);
    }
    nb::dict result;
    result["variant"] = inspected.flags.variant;
    result["num_vertices"] = inspected.vertices;
    result["num_faces"] = inspected.faces;
    result["num_corners"] = inspected.corners;
    result["declared_edges"] =
        inspected.declared_edges;
    result["has_vertex_normals"] =
        inspected.flags.normals;
    result["has_vertex_colors"] =
        inspected.flags.colors;
    result["has_vertex_uvs"] =
        inspected.flags.uvs;
    return result;
}

}  // namespace

void register_stl_off(nb::module_ &module) {
    module.def(
        "read_stl", &read_stl, "data"_a,
        "Decode strict binary or ASCII STL into an unwelded "
        "triangle-soup Mesh.");
    module.def(
        "read_stl_faces", &read_stl_faces,
        "data"_a, "start"_a, "stop"_a,
        "Decode a bounded STL triangle range.");
    module.def(
        "_inspect_stl", &inspect_stl, "data"_a,
        "Validate STL and return encoding, topology, and normal metadata.");
    module.def(
        "write_stl", &write_stl,
        "mesh"_a, "encoding"_a = "binary",
        "Encode a losslessly representable triangle-soup Mesh "
        "as binary or ASCII STL.");

    module.def(
        "read_off", &read_off, "data"_a,
        "Decode polygon-preserving ASCII OFF vertex variants into Mesh.");
    module.def(
        "read_off_faces", &read_off_faces,
        "data"_a, "start"_a, "stop"_a,
        "Decode an OFF face range while retaining the vertex domain.");
    module.def(
        "_inspect_off", &inspect_off, "data"_a,
        "Scan OFF structure and return variant, topology, "
        "and attribute metadata.");
    module.def(
        "write_off", &write_off, "mesh"_a,
        "Encode a losslessly representable Mesh as deterministic ASCII OFF.");
}
