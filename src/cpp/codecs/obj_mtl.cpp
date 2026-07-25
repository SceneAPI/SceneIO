// Strict polygon-preserving Wavefront OBJ/MTL codec.
//
// TinyObjLoader performs the independent-index geometry parse with
// triangulation disabled. SceneIO pre-scans directives so unsupported
// fidelity-bearing constructs reject rather than disappearing inside
// TinyObjLoader's intentionally permissive unknown-command behavior. MTL is
// mapped into the canonical MaterialSet PBR/texture subset.
#include <nanobind/stl/string.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <iterator>
#include <limits>
#include <locale.h>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string_view>
#include <unordered_map>
#include <unordered_set>

#include "io/common.hpp"
#include "records/material_set.hpp"
#include "records/mesh.hpp"

#define TINYOBJLOADER_IMPLEMENTATION
// TinyObjLoader embeds a newer fast_float release in the public `fast_float`
// namespace. SceneIO also links codecs compiled against its pinned v6 headers;
// keep the embedded implementation private to this translation unit so the
// two inline-definition sets cannot violate the C++ one-definition rule.
#define fast_float tinyobj_fast_float
#include "tiny_obj_loader.h"
#undef fast_float

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kLineLimit = 1024 * 1024;

struct ObjFaceMetadata {
    size_t corners = 0;
    std::string object;
    std::string group;
    std::string material;
    uint32_t smoothing = 0;
};

struct ObjMetadata {
    size_t vertices = 0;
    size_t normals = 0;
    size_t texcoords = 0;
    size_t face_count = 0;
    size_t corners = 0;
    bool saw_colored_vertex = false;
    bool saw_plain_vertex = false;
    bool saw_object = false;
    bool saw_group = false;
    bool saw_smoothing = false;
    std::optional<std::string> material_library;
    std::vector<ObjFaceMetadata> faces;
};

struct TextureDraft {
    uint8_t semantic = 0;
    std::string path;
    uint8_t wrap = 0;
};

struct MaterialDraft {
    std::string name;
    std::array<float, 4> base = {1.0F, 1.0F, 1.0F, 1.0F};
    std::array<float, 3> emissive = {0.0F, 0.0F, 0.0F};
    float metallic = 0.0F;
    float roughness = 1.0F;
    bool saw_base = false;
    bool saw_emissive = false;
    bool saw_metallic = false;
    bool saw_roughness = false;
    bool saw_alpha = false;
    std::vector<TextureDraft> textures;
};

std::vector<std::string> tokenize(
    std::string_view line, const char *context) {
    std::vector<std::string> result;
    std::string token;
    bool quoted = false;
    char quote = '\0';
    bool escaped = false;
    auto flush = [&]() {
        if (!token.empty()) {
            result.push_back(std::move(token));
            token.clear();
        }
    };
    for (char value : line) {
        if (escaped) {
            token.push_back(value);
            escaped = false;
            continue;
        }
        if (value == '\\') {
            escaped = true;
            continue;
        }
        if (quoted) {
            if (value == quote) {
                quoted = false;
            } else {
                token.push_back(value);
            }
            continue;
        }
        if (value == '"' || value == '\'') {
            quoted = true;
            quote = value;
            continue;
        }
        if (value == '#') break;
        if (value == ' ' || value == '\t') {
            flush();
            continue;
        }
        token.push_back(value);
    }
    if (escaped || quoted)
        throw std::invalid_argument(
            std::string(context) +
            ": unterminated escape or quote");
    flush();
    return result;
}

template <typename Function>
void for_each_line(
    std::string_view text, const char *context, Function &&function) {
    if (text.find('\0') != std::string_view::npos)
        throw std::invalid_argument(
            std::string(context) + ": embedded NUL");
    if (!valid_utf8(text))
        throw std::invalid_argument(
            std::string(context) + ": input is not valid UTF-8");
    size_t cursor = 0;
    size_t line_number = 0;
    while (cursor < text.size()) {
        const size_t begin = cursor;
        const size_t newline = text.find('\n', cursor);
        const size_t end =
            newline == std::string_view::npos ? text.size() : newline;
        cursor =
            newline == std::string_view::npos ? text.size() : newline + 1;
        ++line_number;
        size_t length = end - begin;
        if (length != 0 && text[begin + length - 1] == '\r')
            --length;
        if (length > kLineLimit)
            throw std::invalid_argument(
                std::string(context) + ": line exceeds 1 MiB");
        std::string_view line = text.substr(begin, length);
        if (line_number == 1 && line.size() >= 3 &&
            static_cast<uint8_t>(line[0]) == 0xEF &&
            static_cast<uint8_t>(line[1]) == 0xBB &&
            static_cast<uint8_t>(line[2]) == 0xBF)
            line.remove_prefix(3);
        function(line, line_number);
    }
}

std::string join_tokens(
    const std::vector<std::string> &tokens, size_t begin) {
    std::string result;
    for (size_t index = begin; index < tokens.size(); ++index) {
        if (!result.empty()) result.push_back(' ');
        result += tokens[index];
    }
    return result;
}

uint32_t parse_u32(const std::string &token, const char *context) {
    uint64_t result = 0;
    const auto parsed = std::from_chars(
        token.data(), token.data() + token.size(), result);
    if (token.empty() || parsed.ec != std::errc{} ||
        parsed.ptr != token.data() + token.size() ||
        result > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            std::string(context) + ": invalid uint32 value");
    return static_cast<uint32_t>(result);
}

float parse_float(
    const std::string &token, const char *context,
    float minimum, float maximum) {
    double value = 0.0;
    const auto parsed = tinyobj_fast_float::from_chars(
        token.data(), token.data() + token.size(), value);
    const float result = static_cast<float>(value);
    if (token.empty() || parsed.ec != tinyobj_ff::ff_errc::ok ||
        parsed.ptr != token.data() + token.size() ||
        !std::isfinite(value) || !std::isfinite(result) ||
        result < minimum || result > maximum)
        throw std::invalid_argument(
            std::string(context) +
            ": invalid or out-of-range number");
    return result;
}

ObjMetadata scan_obj(
    std::string_view text, bool retain_faces = true) {
    ObjMetadata result;
    std::string object;
    std::string group;
    std::string material;
    uint32_t smoothing = 0;
    for_each_line(
        text, "OBJ",
        [&](std::string_view line, size_t line_number) {
            const std::vector<std::string> tokens =
                tokenize(line, "OBJ");
            if (tokens.empty()) return;
            const std::string &command = tokens[0];
            auto require = [&](bool condition, const char *message) {
                if (!condition)
                    throw std::invalid_argument(
                        "OBJ line " + std::to_string(line_number) +
                        ": " + message);
            };
            if (command == "v") {
                require(
                    tokens.size() == 4 || tokens.size() == 7,
                    "vertices require xyz or xyz+rgb");
                for (size_t component = 1; component <= 3; ++component)
                    (void)parse_float(
                        tokens[component], "OBJ vertex position",
                        -std::numeric_limits<float>::max(),
                        std::numeric_limits<float>::max());
                for (size_t component = 4;
                     component < tokens.size(); ++component)
                    (void)parse_float(
                        tokens[component], "OBJ vertex color",
                        0.0F, 1.0F);
                result.vertices++;
                result.saw_colored_vertex |= tokens.size() == 7;
                result.saw_plain_vertex |= tokens.size() == 4;
            } else if (command == "vn") {
                require(tokens.size() == 4, "normals require xyz");
                for (size_t component = 1; component <= 3; ++component)
                    (void)parse_float(
                        tokens[component], "OBJ normal",
                        -std::numeric_limits<float>::max(),
                        std::numeric_limits<float>::max());
                result.normals++;
            } else if (command == "vt") {
                require(tokens.size() == 3, "texture coordinates require uv");
                for (size_t component = 1; component <= 2; ++component)
                    (void)parse_float(
                        tokens[component],
                        "OBJ texture coordinate",
                        -std::numeric_limits<float>::max(),
                        std::numeric_limits<float>::max());
                result.texcoords++;
            } else if (command == "f") {
                require(
                    tokens.size() >= 4,
                    "faces require at least three corners");
                const size_t corners = tokens.size() - 1;
                if (result.face_count ==
                    std::numeric_limits<size_t>::max())
                    throw std::length_error(
                        "OBJ: face count is too large");
                ++result.face_count;
                if (corners >
                    std::numeric_limits<size_t>::max() -
                        result.corners)
                    throw std::length_error(
                        "OBJ: aggregate corner count is too large");
                result.corners += corners;
                if (retain_faces)
                    result.faces.push_back({
                        corners, object, group, material, smoothing});
            } else if (command == "o") {
                object = join_tokens(tokens, 1);
                if (object.size() > kLineLimit)
                    throw std::invalid_argument(
                        "OBJ: object name exceeds 1 MiB");
                result.saw_object = true;
            } else if (command == "g") {
                require(
                    tokens.size() <= 2,
                    "multiple simultaneous groups are unsupported");
                group = tokens.size() == 2 ? tokens[1] : "";
                result.saw_group = true;
            } else if (command == "s") {
                require(
                    tokens.size() == 2,
                    "smoothing requires one id or off");
                if (tokens[1] == "off" || tokens[1] == "0")
                    smoothing = 0;
                else
                    smoothing = parse_u32(
                        tokens[1], "OBJ smoothing group");
                result.saw_smoothing = true;
            } else if (command == "usemtl") {
                require(
                    tokens.size() == 2,
                    "usemtl requires one escaped material name");
                material = tokens[1];
            } else if (command == "mtllib") {
                require(
                    tokens.size() == 2,
                    "exactly one escaped material-library path is supported");
                require(
                    !result.material_library.has_value(),
                    "only one material library is supported");
                result.material_library = tokens[1];
            } else {
                throw std::invalid_argument(
                    "OBJ line " + std::to_string(line_number) +
                    ": unsupported directive '" + command + "'");
            }
        });
    if (result.saw_colored_vertex && result.saw_plain_vertex)
        throw std::invalid_argument(
            "OBJ: mixed colored and uncolored vertices are unsupported");
    if (retain_faces && result.faces.size() != result.face_count)
        throw std::runtime_error(
            "OBJ: internal face-metadata count mismatch");
    return result;
}

uint8_t mtl_semantic(const std::string &command) {
    if (command == "map_Kd") return 0;
    if (command == "map_Ka") return 1;
    if (command == "map_Ks") return 2;
    if (command == "map_Ns") return 3;
    if (command == "bump" || command == "map_bump" ||
        command == "map_Bump" || command == "norm")
        return 4;
    if (command == "disp") return 5;
    if (command == "map_d") return 6;
    if (command == "map_Ke") return 7;
    if (command == "map_Pm") return 8;
    if (command == "map_Pr") return 9;
    if (command == "refl") return 12;
    throw std::invalid_argument(
        "MTL: unsupported texture directive '" + command + "'");
}

std::vector<MaterialDraft> scan_mtl(std::string_view text) {
    std::vector<MaterialDraft> result;
    std::unordered_set<std::string> names;
    MaterialDraft *current = nullptr;
    for_each_line(
        text, "MTL",
        [&](std::string_view line, size_t line_number) {
            const std::vector<std::string> tokens =
                tokenize(line, "MTL");
            if (tokens.empty()) return;
            const std::string &command = tokens[0];
            auto fail = [&](const std::string &message) {
                throw std::invalid_argument(
                    "MTL line " + std::to_string(line_number) +
                    ": " + message);
            };
            auto require = [&](bool condition, const char *message) {
                if (!condition) fail(message);
            };
            if (command == "newmtl") {
                const std::string name = join_tokens(tokens, 1);
                require(!name.empty(), "newmtl requires a name");
                require(
                    name.size() <= kLineLimit,
                    "material name exceeds 1 MiB");
                if (!names.insert(name).second)
                    fail("material names must be unique");
                result.push_back({});
                current = &result.back();
                current->name = name;
                return;
            }
            require(
                current != nullptr,
                "material property appears before newmtl");
            auto vector3 = [&](std::array<float, 3> &target,
                               bool &seen, float maximum,
                               const char *name) {
                require(tokens.size() == 4, "expected three values");
                if (seen) fail(std::string("duplicate ") + name);
                for (size_t component = 0; component < 3; ++component)
                    target[component] = parse_float(
                        tokens[component + 1], name, 0.0F, maximum);
                seen = true;
            };
            if (command == "Kd") {
                std::array<float, 3> rgb{};
                vector3(
                    rgb, current->saw_base, 1.0F, "Kd");
                std::copy(
                    rgb.begin(), rgb.end(), current->base.begin());
            } else if (command == "Ke") {
                vector3(
                    current->emissive, current->saw_emissive,
                    std::numeric_limits<float>::max(), "Ke");
            } else if (command == "Pm" || command == "Pr") {
                require(tokens.size() == 2, "expected one value");
                bool &seen = command == "Pm"
                                 ? current->saw_metallic
                                 : current->saw_roughness;
                if (seen) fail("duplicate " + command);
                float &target = command == "Pm"
                                    ? current->metallic
                                    : current->roughness;
                target = parse_float(
                    tokens[1], command.c_str(), 0.0F, 1.0F);
                seen = true;
            } else if (command == "d" || command == "Tr") {
                require(tokens.size() == 2, "expected one value");
                if (current->saw_alpha)
                    fail("duplicate d/Tr alpha");
                const float value = parse_float(
                    tokens[1], command.c_str(), 0.0F, 1.0F);
                current->base[3] =
                    command == "Tr" ? 1.0F - value : value;
                current->saw_alpha = true;
            } else if (
                command.rfind("map_", 0) == 0 ||
                command == "bump" || command == "norm" ||
                command == "disp" || command == "refl") {
                const uint8_t semantic = mtl_semantic(command);
                uint8_t wrap = 0;
                size_t cursor = 1;
                while (cursor < tokens.size() &&
                       !tokens[cursor].empty() &&
                       tokens[cursor][0] == '-') {
                    if (tokens[cursor] != "-clamp" ||
                        cursor + 1 >= tokens.size())
                        fail(
                            "only the texture option '-clamp on|off' "
                            "is supported");
                    const std::string &value = tokens[cursor + 1];
                    if (value == "on")
                        wrap = 1;
                    else if (value == "off")
                        wrap = 0;
                    else
                        fail("-clamp requires on or off");
                    cursor += 2;
                }
                const std::string path = join_tokens(tokens, cursor);
                require(!path.empty(), "texture path is missing");
                for (const TextureDraft &texture : current->textures)
                    if (texture.semantic == semantic)
                        fail(
                            "duplicate texture semantic for material");
                current->textures.push_back({semantic, path, wrap});
            } else {
                fail(
                    "unsupported fidelity-bearing directive '" +
                    command + "'");
            }
        });
    return result;
}

MaterialSet build_materials(
    const std::vector<MaterialDraft> &drafts) {
    if (drafts.size() >
        static_cast<size_t>(std::numeric_limits<int32_t>::max()))
        throw std::length_error(
            "MTL: material count exceeds OBJ's signed index domain");
    MaterialSet materials;
    std::vector<std::string> names;
    names.reserve(drafts.size());
    size_t textures = 0;
    for (const MaterialDraft &draft : drafts) {
        names.push_back(draft.name);
        if (draft.textures.size() >
            std::numeric_limits<size_t>::max() - textures)
            throw std::length_error(
                "MTL: texture count is too large");
        textures += draft.textures.size();
    }
    assign_material_names(materials, names);
    materials.t = textures;
    materials.base_colors.reserve(materials.n * 4);
    materials.emissive_colors.reserve(materials.n * 3);
    materials.metallic.reserve(materials.n);
    materials.roughness.reserve(materials.n);
    materials.alpha_modes.reserve(materials.n);
    materials.alpha_cutoffs.assign(materials.n, 0.5F);
    materials.texture_materials.reserve(textures);
    materials.texture_semantics.reserve(textures);
    materials.texture_uv_sets.assign(textures, 0);
    materials.texture_wrap_s.reserve(textures);
    materials.texture_wrap_t.reserve(textures);
    materials.texture_min_filters.assign(textures, 0);
    materials.texture_mag_filters.assign(textures, 0);
    std::vector<std::string> paths;
    paths.reserve(textures);

    for (size_t material = 0; material < drafts.size(); ++material) {
        const MaterialDraft &draft = drafts[material];
        materials.base_colors.insert(
            materials.base_colors.end(),
            draft.base.begin(), draft.base.end());
        materials.emissive_colors.insert(
            materials.emissive_colors.end(),
            draft.emissive.begin(), draft.emissive.end());
        materials.metallic.push_back(draft.metallic);
        materials.roughness.push_back(draft.roughness);
        materials.alpha_modes.push_back(
            draft.base[3] < 1.0F ? 2 : 0);
        for (const TextureDraft &texture : draft.textures) {
            materials.texture_materials.push_back(material);
            materials.texture_semantics.push_back(texture.semantic);
            materials.texture_wrap_s.push_back(texture.wrap);
            materials.texture_wrap_t.push_back(texture.wrap);
            paths.push_back(texture.path);
        }
    }
    assign_material_texture_paths(materials, paths);
    validate_material_set(materials, "MTL");
    return materials;
}

Mesh decode_obj(
    std::string obj_text, std::optional<std::string> mtl_text) {
    const ObjMetadata metadata = scan_obj(obj_text);
    if (metadata.material_library.has_value() != mtl_text.has_value())
        throw std::invalid_argument(
            metadata.material_library
                ? "OBJ: referenced material library was not supplied"
                : "OBJ: material data supplied without mtllib");
    const std::vector<MaterialDraft> material_drafts =
        mtl_text ? scan_mtl(*mtl_text)
                 : std::vector<MaterialDraft>{};
    MaterialSet materials = build_materials(material_drafts);
    const std::vector<std::string> names =
        material_names(materials);
    std::unordered_map<std::string, int32_t> material_ids;
    for (size_t index = 0; index < names.size(); ++index)
        material_ids.emplace(
            names[index], static_cast<int32_t>(index));
    for (const ObjFaceMetadata &face : metadata.faces)
        if (!face.material.empty() &&
            material_ids.find(face.material) == material_ids.end())
            throw std::invalid_argument(
                "OBJ: usemtl references unknown material '" +
                face.material + "'");

    tinyobj::ObjReaderConfig config;
    config.triangulate = false;
    config.vertex_color = false;
    tinyobj::ObjReader reader;
    if (!reader.ParseFromString(
            obj_text, mtl_text.value_or(""), config))
        throw std::invalid_argument(
            "OBJ: TinyObjLoader parse failed: " + reader.Error());
    if (!reader.Warning().empty())
        throw std::invalid_argument(
            "OBJ: TinyObjLoader warning: " + reader.Warning());
    const auto &tiny_materials = reader.GetMaterials();
    if (tiny_materials.size() != names.size())
        throw std::invalid_argument(
            "MTL: TinyObjLoader material count disagrees");
    for (size_t index = 0; index < names.size(); ++index)
        if (tiny_materials[index].name != names[index])
            throw std::invalid_argument(
                "MTL: TinyObjLoader material order disagrees");

    const tinyobj::attrib_t &attributes = reader.GetAttrib();
    if (attributes.vertices.size() != metadata.vertices * 3 ||
        attributes.normals.size() != metadata.normals * 3 ||
        attributes.texcoords.size() != metadata.texcoords * 2)
        throw std::invalid_argument(
            "OBJ: parsed attribute counts disagree with directives");

    Mesh mesh;
    mesh.n = metadata.vertices;
    mesh.f = metadata.face_count;
    mesh.c = metadata.corners;
    mesh.positions.assign(
        attributes.vertices.begin(), attributes.vertices.end());
    mesh.face_offsets.reserve(mesh.f + 1);
    mesh.face_offsets.push_back(0);
    mesh.face_indices.reserve(mesh.c);
    if (metadata.saw_colored_vertex) {
        if (attributes.colors.size() != mesh.n * 3)
            throw std::invalid_argument(
                "OBJ: parsed vertex colors disagree with directives");
        mesh.vertex_colors.reserve(mesh.n * 4);
        for (float value : attributes.colors) {
            if (!std::isfinite(value) || value < 0.0F || value > 1.0F)
                throw std::invalid_argument(
                    "OBJ: vertex color is outside 0..1");
            const float scaled = value * 255.0F;
            const float rounded = std::round(scaled);
            if (rounded < 0.0F || rounded > 255.0F ||
                static_cast<float>(
                    static_cast<uint8_t>(rounded)) /
                        255.0F !=
                    value)
                throw std::invalid_argument(
                    "OBJ: vertex color is not exactly representable as rgba8");
            mesh.vertex_colors.push_back(
                static_cast<uint8_t>(rounded));
            if (mesh.vertex_colors.size() % 4 == 3)
                mesh.vertex_colors.push_back(255);
        }
    }

    size_t face_row = 0;
    size_t corner_row = 0;
    bool saw_normal = false, missed_normal = false;
    bool saw_uv = false, missed_uv = false;
    bool vertex_domain_normals =
        metadata.normals == metadata.vertices;
    bool vertex_domain_uvs =
        metadata.texcoords == metadata.vertices;
    std::vector<uint8_t> used_normals(metadata.normals, 0);
    std::vector<uint8_t> used_uvs(metadata.texcoords, 0);
    std::vector<int32_t> face_materials;
    face_materials.reserve(mesh.f);
    std::vector<std::string> face_objects;
    std::vector<std::string> face_groups;
    face_objects.reserve(mesh.f);
    face_groups.reserve(mesh.f);
    if (metadata.saw_smoothing)
        mesh.face_smoothing_groups.reserve(mesh.f);

    for (const tinyobj::shape_t &shape : reader.GetShapes()) {
        if (!shape.lines.indices.empty() ||
            !shape.points.indices.empty() ||
            !shape.mesh.tags.empty())
            throw std::invalid_argument(
                "OBJ: non-face primitives or subdivision tags are unsupported");
        size_t shape_corner = 0;
        if (shape.mesh.num_face_vertices.size() !=
                shape.mesh.material_ids.size() ||
            shape.mesh.num_face_vertices.size() !=
                shape.mesh.smoothing_group_ids.size())
            throw std::invalid_argument(
                "OBJ: TinyObjLoader face metadata is inconsistent");
        for (size_t local_face = 0;
             local_face < shape.mesh.num_face_vertices.size();
             ++local_face, ++face_row) {
            if (face_row >= metadata.faces.size())
                throw std::invalid_argument(
                    "OBJ: parsed face count exceeds directive count");
            const size_t corners =
                shape.mesh.num_face_vertices[local_face];
            const ObjFaceMetadata &expected = metadata.faces[face_row];
            if (corners != expected.corners)
                throw std::invalid_argument(
                    "OBJ: polygon boundary changed during parse");
            for (size_t corner = 0; corner < corners; ++corner) {
                if (shape_corner >= shape.mesh.indices.size())
                    throw std::invalid_argument(
                        "OBJ: truncated parsed index stream");
                const tinyobj::index_t index =
                    shape.mesh.indices[shape_corner++];
                if (index.vertex_index < 0 ||
                    static_cast<size_t>(index.vertex_index) >= mesh.n)
                    throw std::invalid_argument(
                        "OBJ: vertex index is out of range");
                mesh.face_indices.push_back(
                    static_cast<uint64_t>(index.vertex_index));
                if (index.normal_index >= 0) {
                    saw_normal = true;
                    const size_t normal =
                        static_cast<size_t>(index.normal_index);
                    if (normal >= metadata.normals)
                        throw std::invalid_argument(
                            "OBJ: normal index is out of range");
                    vertex_domain_normals &=
                        normal ==
                        static_cast<size_t>(index.vertex_index);
                    used_normals[normal] = 1;
                    for (size_t component = 0; component < 3; ++component)
                        mesh.corner_normals.push_back(
                            attributes.normals[normal * 3 + component]);
                } else {
                    missed_normal = true;
                }
                if (index.texcoord_index >= 0) {
                    saw_uv = true;
                    const size_t uv =
                        static_cast<size_t>(index.texcoord_index);
                    if (uv >= metadata.texcoords)
                        throw std::invalid_argument(
                            "OBJ: texture-coordinate index is out of range");
                    vertex_domain_uvs &=
                        uv ==
                        static_cast<size_t>(index.vertex_index);
                    used_uvs[uv] = 1;
                    for (size_t component = 0; component < 2; ++component)
                        mesh.corner_uvs.push_back(
                            attributes.texcoords[uv * 2 + component]);
                } else {
                    missed_uv = true;
                }
                ++corner_row;
            }
            mesh.face_offsets.push_back(corner_row);
            const auto found = material_ids.find(expected.material);
            const int32_t material =
                expected.material.empty() ? -1 : found->second;
            if (shape.mesh.material_ids[local_face] != material)
                throw std::invalid_argument(
                    "OBJ: material assignment changed during parse");
            if (shape.mesh.smoothing_group_ids[local_face] !=
                expected.smoothing)
                throw std::invalid_argument(
                    "OBJ: smoothing assignment changed during parse");
            face_materials.push_back(material);
            face_objects.push_back(expected.object);
            face_groups.push_back(expected.group);
            if (metadata.saw_smoothing)
                mesh.face_smoothing_groups.push_back(
                    expected.smoothing);
        }
        if (shape_corner != shape.mesh.indices.size())
            throw std::invalid_argument(
                "OBJ: trailing parsed index stream");
    }
    if (face_row != mesh.f || corner_row != mesh.c)
        throw std::invalid_argument(
            "OBJ: parsed face/corner counts disagree");
    if (saw_normal && missed_normal)
        throw std::invalid_argument(
            "OBJ: mixed present/missing corner normals are unsupported");
    if (saw_uv && missed_uv)
        throw std::invalid_argument(
            "OBJ: mixed present/missing corner UVs are unsupported");
    if (saw_normal && vertex_domain_normals) {
        mesh.vertex_normals.assign(
            attributes.normals.begin(), attributes.normals.end());
        mesh.corner_normals.clear();
    } else if (
        std::find(
            used_normals.begin(), used_normals.end(), 0) !=
        used_normals.end()) {
        throw std::invalid_argument(
            "OBJ: unreferenced normal records cannot be preserved");
    } else if (!saw_normal) {
        mesh.corner_normals.clear();
    }
    if (saw_uv && vertex_domain_uvs) {
        mesh.vertex_uvs.assign(
            attributes.texcoords.begin(), attributes.texcoords.end());
        mesh.corner_uvs.clear();
    } else if (
        std::find(used_uvs.begin(), used_uvs.end(), 0) !=
        used_uvs.end()) {
        throw std::invalid_argument(
            "OBJ: unreferenced texture-coordinate records cannot be preserved");
    } else if (!saw_uv) {
        mesh.corner_uvs.clear();
    }

    mesh.primitive_offsets = {0};
    std::vector<std::string> primitive_objects;
    std::vector<std::string> primitive_groups;
    if (mesh.f != 0) {
        mesh.primitive_materials.push_back(face_materials[0]);
        primitive_objects.push_back(face_objects[0]);
        primitive_groups.push_back(face_groups[0]);
        for (size_t face = 1; face < mesh.f; ++face) {
            if (face_materials[face] ==
                    mesh.primitive_materials.back() &&
                face_objects[face] == primitive_objects.back() &&
                face_groups[face] == primitive_groups.back())
                continue;
            mesh.primitive_offsets.push_back(face);
            mesh.primitive_materials.push_back(
                face_materials[face]);
            primitive_objects.push_back(face_objects[face]);
            primitive_groups.push_back(face_groups[face]);
        }
        mesh.primitive_offsets.push_back(mesh.f);
    }
    assign_mesh_primitive_names(
        mesh,
        metadata.saw_object
            ? primitive_objects
            : std::vector<std::string>{},
        metadata.saw_group
            ? primitive_groups
            : std::vector<std::string>{});
    if (mtl_text) {
        mesh.materials = std::move(materials);
        mesh.has_material_set = true;
    }
    validate_mesh(mesh, "OBJ");
    return mesh;
}

class FloatAppender {
public:
    explicit FloatAppender(std::string &output)
        : output_(output) {
#ifdef _WIN32
        locale_ = _create_locale(LC_NUMERIC, "C");
        if (locale_ == nullptr)
            throw std::runtime_error(
                "OBJ/MTL writer: cannot create C numeric locale");
#else
        locale_ = newlocale(LC_NUMERIC_MASK, "C", nullptr);
        if (locale_ == nullptr)
            throw std::runtime_error(
                "OBJ/MTL writer: cannot create C numeric locale");
        previous_locale_ = uselocale(locale_);
        if (previous_locale_ == static_cast<locale_t>(0)) {
            freelocale(locale_);
            locale_ = static_cast<locale_t>(0);
            throw std::runtime_error(
                "OBJ/MTL writer: cannot activate C numeric locale");
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
                "OBJ/MTL writer: float formatter failed");
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

std::string escape_token(
    const std::string &value, const char *context,
    bool allow_empty = false) {
    if (!allow_empty && value.empty())
        throw std::invalid_argument(
            std::string(context) + " must be non-empty");
    if (value.find('\0') != std::string::npos ||
        value.find('\r') != std::string::npos ||
        value.find('\n') != std::string::npos)
        throw std::invalid_argument(
            std::string(context) +
            " cannot contain NUL or line breaks");
    if (!valid_utf8(value))
        throw std::invalid_argument(
            std::string(context) + " must be valid UTF-8");
    std::string result;
    result.reserve(value.size());
    for (char character : value) {
        if (character == '\\' || character == ' ' ||
            character == '\t' || character == '#' ||
            character == '"' || character == '\'')
            result.push_back('\\');
        result.push_back(character);
    }
    if (result.size() > kLineLimit - 64)
        throw std::invalid_argument(
            std::string(context) +
            " is too long after OBJ/MTL escaping");
    return result;
}

const char *mtl_texture_directive(uint8_t semantic) {
    static constexpr const char *directives[] = {
        "map_Kd",
        "map_Ka",
        "map_Ks",
        "map_Ns",
        "norm",
        "disp",
        "map_d",
        "map_Ke",
        "map_Pm",
        "map_Pr",
        nullptr,
        nullptr,
        "refl",
    };
    if (semantic >= std::size(directives) ||
        directives[semantic] == nullptr)
        throw std::invalid_argument(
            "MTL writer: texture semantic is not representable");
    return directives[semantic];
}

std::string encode_mtl(const MaterialSet &materials) {
    validate_material_set(materials, "MTL writer");
    const std::vector<std::string> names =
        material_names(materials);
    const std::vector<std::string> paths =
        material_texture_paths(materials);

    for (size_t material = 0; material < materials.n; ++material) {
        const float alpha = materials.base_colors[material * 4 + 3];
        const uint8_t mode = materials.alpha_modes[material];
        if (mode == 1)
            throw std::invalid_argument(
                "MTL writer: mask alpha mode is not representable");
        if ((mode == 0 && alpha != 1.0F) ||
            (mode == 2 && alpha >= 1.0F))
            throw std::invalid_argument(
                "MTL writer: alpha mode and base alpha cannot round-trip");
        if (materials.alpha_cutoffs[material] != 0.5F)
            throw std::invalid_argument(
                "MTL writer: alpha cutoff is not representable");
    }
    for (size_t texture = 0; texture < materials.t; ++texture) {
        if (texture != 0 &&
            materials.texture_materials[texture] <
                materials.texture_materials[texture - 1])
            throw std::invalid_argument(
                "MTL writer: texture rows must be grouped by material");
        if (materials.texture_uv_sets[texture] != 0)
            throw std::invalid_argument(
                "MTL writer: only UV set zero is representable");
        if (materials.texture_wrap_s[texture] !=
                materials.texture_wrap_t[texture] ||
            materials.texture_wrap_s[texture] > 1)
            throw std::invalid_argument(
                "MTL writer: sampler wrap is not representable");
        if (materials.texture_min_filters[texture] != 0 ||
            materials.texture_mag_filters[texture] != 0)
            throw std::invalid_argument(
                "MTL writer: sampler filters are not representable");
        (void)mtl_texture_directive(
            materials.texture_semantics[texture]);
        if (!paths[texture].empty() && paths[texture][0] == '-')
            throw std::invalid_argument(
                "MTL writer: texture paths beginning with '-' are "
                "not representable");
    }

    std::string output =
        "# SceneIO deterministic MTL\n";
    FloatAppender floats(output);
    size_t texture_cursor = 0;
    for (size_t material = 0; material < materials.n; ++material) {
        output += "newmtl " +
                  escape_token(names[material], "MTL material name") +
                  "\n";
        output += "Kd";
        for (size_t component = 0; component < 3; ++component) {
            output.push_back(' ');
            floats.append(
                materials.base_colors[material * 4 + component]);
        }
        output += "\nKe";
        for (size_t component = 0; component < 3; ++component) {
            output.push_back(' ');
            floats.append(
                materials.emissive_colors[
                    material * 3 + component]);
        }
        output += "\nPm ";
        floats.append(materials.metallic[material]);
        output += "\nPr ";
        floats.append(materials.roughness[material]);
        output += "\nd ";
        floats.append(materials.base_colors[material * 4 + 3]);
        output.push_back('\n');
        while (texture_cursor < materials.t &&
               materials.texture_materials[texture_cursor] == material) {
            const size_t texture = texture_cursor++;
            output += mtl_texture_directive(
                materials.texture_semantics[texture]);
            if (materials.texture_wrap_s[texture] == 1)
                output += " -clamp on";
            output += " " +
                      escape_token(
                          paths[texture], "MTL texture path") +
                      "\n";
        }
        output += "\n";
    }
    return output;
}

bool identity_transform(const double *values) {
    static constexpr double identity[16] = {
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    return std::equal(
        std::begin(identity), std::end(identity), values);
}

std::string encode_obj(
    const Mesh &mesh, const std::string &mtl_filename) {
    validate_mesh(mesh, "OBJ writer");
    if (mesh.coordinate_frame != "unknown" ||
        mesh.scale_to_meters != 1.0 ||
        !identity_transform(mesh.local_transform))
        throw std::invalid_argument(
            "OBJ writer: coordinate frame, scale, and transform "
            "metadata are not representable");
    if (mesh.has_vertex_normals() &&
        mesh.has_corner_normals())
        throw std::invalid_argument(
            "OBJ writer: simultaneous vertex and corner normals "
            "are not representable");
    if (mesh.has_vertex_uvs() && mesh.has_corner_uvs())
        throw std::invalid_argument(
            "OBJ writer: simultaneous vertex and corner UVs "
            "are not representable");
    if (mesh.has_corner_colors())
        throw std::invalid_argument(
            "OBJ writer: corner colors are not representable");
    if (mesh.f == 0 &&
        (mesh.has_vertex_normals() || mesh.has_vertex_uvs()))
        throw std::invalid_argument(
            "OBJ writer: normal and UV pools without faces have no "
            "representable index association");
    if (mesh.has_vertex_colors())
        for (size_t vertex = 0; vertex < mesh.n; ++vertex)
            if (mesh.vertex_colors[vertex * 4 + 3] != 255)
                throw std::invalid_argument(
                    "OBJ writer: vertex alpha is not representable");
    if (mesh.has_material_set != !mtl_filename.empty())
        throw std::invalid_argument(
            mesh.has_material_set
                ? "OBJ writer: attached materials require an MTL filename"
                : "OBJ writer: MTL filename supplied without materials");
    if (mesh.has_material_set)
        (void)encode_mtl(mesh.materials);
    else
        for (int32_t material : mesh.primitive_materials)
            if (material >= 0)
                throw std::invalid_argument(
                    "OBJ writer: detached material indices are not representable");

    bool saw_material = false;
    for (int32_t material : mesh.primitive_materials) {
        if (material >= 0)
            saw_material = true;
        else if (saw_material)
            throw std::invalid_argument(
                "OBJ writer: an unassigned material cannot follow usemtl");
    }
    const std::vector<std::string> object_names =
        mesh_primitive_object_names(mesh);
    const std::vector<std::string> group_names =
        mesh_primitive_group_names(mesh);
    std::vector<std::string> material_names_value;
    if (mesh.has_material_set)
        material_names_value = material_names(mesh.materials);

    std::string output =
        "# SceneIO deterministic polygonal OBJ\n";
    FloatAppender floats(output);
    if (mesh.has_material_set)
        output += "mtllib " +
                  escape_token(
                      mtl_filename, "OBJ material-library filename") +
                  "\n";
    for (size_t vertex = 0; vertex < mesh.n; ++vertex) {
        output += "v";
        for (size_t component = 0; component < 3; ++component) {
            output.push_back(' ');
            floats.append(mesh.positions[vertex * 3 + component]);
        }
        if (mesh.has_vertex_colors()) {
            for (size_t component = 0; component < 3; ++component) {
                output.push_back(' ');
                floats.append(
                    static_cast<float>(
                        mesh.vertex_colors[
                            vertex * 4 + component]) /
                        255.0F);
            }
        }
        output += "\n";
    }
    const std::vector<float> &uvs =
        mesh.has_vertex_uvs() ? mesh.vertex_uvs : mesh.corner_uvs;
    for (size_t row = 0; row < uvs.size() / 2; ++row) {
        output += "vt ";
        floats.append(uvs[row * 2]);
        output.push_back(' ');
        floats.append(uvs[row * 2 + 1]);
        output.push_back('\n');
    }
    const std::vector<float> &normals =
        mesh.has_vertex_normals()
            ? mesh.vertex_normals
            : mesh.corner_normals;
    for (size_t row = 0; row < normals.size() / 3; ++row) {
        output += "vn ";
        floats.append(normals[row * 3]);
        output.push_back(' ');
        floats.append(normals[row * 3 + 1]);
        output.push_back(' ');
        floats.append(normals[row * 3 + 2]);
        output.push_back('\n');
    }

    const bool has_uvs = !uvs.empty();
    const bool has_normals = !normals.empty();
    size_t primitive = 0;
    uint32_t last_smoothing = std::numeric_limits<uint32_t>::max();
    int32_t last_material = -1;
    for (size_t face = 0; face < mesh.f; ++face) {
        if (face == mesh.primitive_offsets[primitive]) {
            if (mesh.has_object_names())
                output += "o " +
                          escape_token(
                              object_names[primitive],
                              "OBJ object name", true) +
                          "\n";
            if (mesh.has_group_names())
                output += "g " +
                          escape_token(
                              group_names[primitive],
                              "OBJ group name", true) +
                          "\n";
            const int32_t material =
                mesh.primitive_materials[primitive];
            if (material >= 0 && material != last_material) {
                output += "usemtl " +
                          escape_token(
                              material_names_value[
                                  static_cast<size_t>(material)],
                              "OBJ material name") +
                          "\n";
                last_material = material;
            }
        }
        if (mesh.has_smoothing_groups()) {
            const uint32_t smoothing =
                mesh.face_smoothing_groups[face];
            if (smoothing != last_smoothing) {
                output += smoothing == 0
                              ? "s off\n"
                              : "s " + std::to_string(smoothing) + "\n";
                last_smoothing = smoothing;
            }
        }
        const size_t begin =
            static_cast<size_t>(mesh.face_offsets[face]);
        const size_t end =
            static_cast<size_t>(mesh.face_offsets[face + 1]);
        output += "f";
        for (size_t corner = begin; corner < end; ++corner) {
            const uint64_t vertex = mesh.face_indices[corner] + 1;
            output += " " + std::to_string(vertex);
            const uint64_t uv =
                mesh.has_vertex_uvs()
                    ? vertex
                    : static_cast<uint64_t>(corner + 1);
            const uint64_t normal =
                mesh.has_vertex_normals()
                    ? vertex
                    : static_cast<uint64_t>(corner + 1);
            if (has_uvs)
                output += "/" + std::to_string(uv);
            else if (has_normals)
                output += "/";
            if (has_normals)
                output += "/" + std::to_string(normal);
        }
        output += "\n";
        if (face + 1 == mesh.primitive_offsets[primitive + 1])
            ++primitive;
    }
    return output;
}

std::optional<std::string> obj_material_library(
    nb::handle source) {
    ByteView view(source);
    std::optional<std::string> result;
    {
        nb::gil_scoped_release release;
        result = scan_obj(std::string_view(
            reinterpret_cast<const char *>(view.data()),
            view.size()), false).material_library;
    }
    return result;
}

Mesh read_obj(nb::handle source, nb::handle mtl_source) {
    ByteView view(source);
    std::unique_ptr<ByteView> mtl_view;
    if (!mtl_source.is_none())
        mtl_view = std::make_unique<ByteView>(mtl_source);
    Mesh result;
    {
        nb::gil_scoped_release release;
        std::string obj_text(
            reinterpret_cast<const char *>(view.data()),
            view.size());
        std::optional<std::string> mtl_text;
        if (mtl_view)
            mtl_text.emplace(
                reinterpret_cast<const char *>(mtl_view->data()),
                mtl_view->size());
        result = decode_obj(
            std::move(obj_text), std::move(mtl_text));
    }
    return result;
}

nb::dict inspect_obj(nb::handle source) {
    ByteView view(source);
    ObjMetadata metadata;
    {
        nb::gil_scoped_release release;
        metadata = scan_obj(std::string_view(
            reinterpret_cast<const char *>(view.data()),
            view.size()), false);
    }
    nb::dict result;
    result["num_vertices"] = metadata.vertices;
    result["num_faces"] = metadata.face_count;
    result["num_corners"] = metadata.corners;
    result["num_normals"] = metadata.normals;
    result["num_texcoords"] = metadata.texcoords;
    result["has_vertex_colors"] =
        metadata.saw_colored_vertex;
    result["has_smoothing_groups"] =
        metadata.saw_smoothing;
    result["material_library"] =
        metadata.material_library
            ? nb::cast(*metadata.material_library)
            : nb::none();
    return result;
}

nb::dict inspect_mtl(nb::handle source) {
    ByteView view(source);
    std::vector<MaterialDraft> drafts;
    {
        nb::gil_scoped_release release;
        drafts = scan_mtl(std::string_view(
            reinterpret_cast<const char *>(view.data()),
            view.size()));
    }
    size_t texture_count = 0;
    for (const MaterialDraft &draft : drafts) {
        if (draft.textures.size() >
            std::numeric_limits<size_t>::max() - texture_count)
            throw std::length_error(
                "MTL: texture count is too large");
        texture_count += draft.textures.size();
    }
    nb::dict result;
    result["num_materials"] = drafts.size();
    result["num_textures"] = texture_count;
    return result;
}

nb::bytes write_obj(
    const Mesh &mesh, const std::string &mtl_filename) {
    std::string output;
    {
        nb::gil_scoped_release release;
        output = encode_obj(mesh, mtl_filename);
    }
    return emit_bytes(output.data(), output.size());
}

nb::bytes write_mtl(const MaterialSet &materials) {
    std::string output;
    {
        nb::gil_scoped_release release;
        output = encode_mtl(materials);
    }
    return emit_bytes(output.data(), output.size());
}

}  // namespace

void register_obj_mtl(nb::module_ &module) {
    module.def(
        "obj_material_library", &obj_material_library,
        "data"_a,
        "Return the single referenced MTL path, or None.");
    module.def(
        "read_obj", &read_obj,
        "data"_a, "mtl_data"_a = nb::none(),
        "Decode polygonal OBJ plus optional supplied MTL bytes.");
    module.def(
        "inspect_obj", &inspect_obj,
        "data"_a,
        "Scan OBJ counts and conventions without constructing a Mesh.");
    module.def(
        "inspect_mtl", &inspect_mtl,
        "data"_a,
        "Scan MTL material and texture counts without constructing a MaterialSet.");
    module.def(
        "write_obj", &write_obj,
        "mesh"_a, "mtl_filename"_a = "",
        "Encode a Mesh as deterministic polygonal OBJ.");
    module.def(
        "write_mtl", &write_mtl,
        "materials"_a,
        "Encode a MaterialSet as deterministic strict-subset MTL.");
}
