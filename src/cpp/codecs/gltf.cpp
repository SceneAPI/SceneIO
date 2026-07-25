// codecs/gltf.cpp -- strict glTF 2.0 JSON/GLB mesh-scene core.
//
// cgltf owns JSON/GLB parsing, validation, accessor conversion (including
// sparse float accessors), and deterministic JSON writing. SceneIO supplies
// external mapped buffers, retains the non-flattened mesh/node/scene domains,
// and writes the binary payload itself so both .gltf+.bin and GLB can use the
// normal native file-sink path.
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <locale.h>
#include <memory>
#include <optional>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

#include "io/common.hpp"
#include "records/mesh_scene.hpp"

#define CGLTF_IMPLEMENTATION
#define CGLTF_WRITE_IMPLEMENTATION
#include "cgltf_write.h"

using namespace nb::literals;

namespace {

constexpr uint32_t kGlbMagic = 0x46546c67U;
constexpr uint32_t kGlbJsonChunk = 0x4e4f534aU;
constexpr uint32_t kGlbBinChunk = 0x004e4942U;
constexpr size_t kMaxUriBytes = 1024 * 1024;

const char *cgltf_result_name(cgltf_result result) {
    switch (result) {
        case cgltf_result_success:
            return "success";
        case cgltf_result_data_too_short:
            return "data is truncated";
        case cgltf_result_unknown_format:
            return "unknown container or resource encoding";
        case cgltf_result_invalid_json:
            return "invalid JSON";
        case cgltf_result_invalid_gltf:
            return "invalid glTF";
        case cgltf_result_invalid_options:
            return "invalid parser options";
        case cgltf_result_file_not_found:
            return "resource not found";
        case cgltf_result_io_error:
            return "resource I/O failed";
        case cgltf_result_out_of_memory:
            return "allocation failed";
        case cgltf_result_legacy_gltf:
            return "legacy glTF 1.x is unsupported";
        case cgltf_result_max_enum:
            break;
    }
    return "unknown cgltf error";
}

void require_success(cgltf_result result, const char *operation) {
    if (result != cgltf_result_success)
        throw std::invalid_argument(
            std::string("glTF ") + operation + ": " +
            cgltf_result_name(result));
}

struct ParsedData {
    cgltf_data *value = nullptr;
    ParsedData() = default;
    ParsedData(const ParsedData &) = delete;
    ParsedData &operator=(const ParsedData &) = delete;
    ParsedData(ParsedData &&other) noexcept
        : value(std::exchange(other.value, nullptr)) {}
    ParsedData &operator=(ParsedData &&other) noexcept {
        if (this != &other) {
            if (value) cgltf_free(value);
            value = std::exchange(other.value, nullptr);
        }
        return *this;
    }
    ~ParsedData() {
        if (value) cgltf_free(value);
    }
};

ParsedData parse_document(
    const sio::ByteView &source,
    cgltf_file_type expected) {
    cgltf_options options{};
    ParsedData parsed;
    cgltf_result result;
    {
        nb::gil_scoped_release release;
        result = cgltf_parse(
            &options, source.data(), source.size(), &parsed.value);
    }
    require_success(result, "parse");
    if (parsed.value->file_type != expected)
        throw std::invalid_argument(
            expected == cgltf_file_type_glb
                ? "GLB reader requires a binary glTF 2.0 container"
                : "glTF reader requires a JSON glTF 2.0 document");
    return parsed;
}

void validate_uri(const char *uri, const char *context) {
    if (!uri) return;
    const size_t length = std::strlen(uri);
    if (length > kMaxUriBytes)
        throw std::invalid_argument(
            std::string(context) + " exceeds 1 MiB");
    if (!sio::valid_utf8(std::string_view(uri, length)))
        throw std::invalid_argument(
            std::string(context) + " must be valid UTF-8");
}

std::vector<std::unique_ptr<sio::ByteView>> load_buffers(
    ParsedData &parsed, nb::dict resources) {
    cgltf_options options{};
    std::vector<std::unique_ptr<sio::ByteView>> pins;
    pins.reserve(parsed.value->buffers_count);
    for (cgltf_size index = 0;
         index < parsed.value->buffers_count; ++index) {
        cgltf_buffer &buffer = parsed.value->buffers[index];
        if (buffer.data || !buffer.uri ||
            std::strncmp(buffer.uri, "data:", 5) == 0)
            continue;
        validate_uri(buffer.uri, "glTF buffer URI");
        nb::str key(buffer.uri);
        if (!resources.contains(key))
            throw std::invalid_argument(
                "glTF external buffer was not supplied: " +
                std::string(buffer.uri));
        auto pin = std::make_unique<sio::ByteView>(resources[key]);
        if (pin->size() < buffer.size)
            throw std::invalid_argument(
                "glTF external buffer is shorter than byteLength: " +
                std::string(buffer.uri));
        buffer.data = const_cast<uint8_t *>(pin->data());
        buffer.data_free_method = cgltf_data_free_method_none;
        pins.push_back(std::move(pin));
    }
    // This now resolves only GLB's BIN chunk and data: buffers. External
    // resources were attached above, so cgltf skips filesystem I/O.
    cgltf_result load_result;
    cgltf_result validate_result;
    {
        nb::gil_scoped_release release;
        load_result =
            cgltf_load_buffers(&options, parsed.value, nullptr);
        validate_result =
            load_result == cgltf_result_success
                ? cgltf_validate(parsed.value)
                : load_result;
    }
    require_success(load_result, "embedded-buffer load");
    for (cgltf_size index = 0;
         index < parsed.value->buffers_count; ++index)
        if (!parsed.value->buffers[index].data)
            throw std::invalid_argument(
                "glTF buffer has neither embedded data nor a supplied URI");
    require_success(validate_result, "validation");
    return pins;
}

void reject_extras(
    const cgltf_extras &extras, const char *context) {
    if (extras.data)
        throw std::invalid_argument(
            std::string("glTF ") + context +
            " extras are not representable");
}

void reject_extensions(const cgltf_data &data) {
    if (data.extensions_used_count != 0 ||
        data.extensions_required_count != 0 ||
        data.data_extensions_count != 0)
        throw std::invalid_argument(
            "glTF extensions are outside the plain core subset");
    if (data.skins_count != 0)
        throw std::invalid_argument(
            "glTF skins are not representable by MeshScene");
    if (data.cameras_count != 0)
        throw std::invalid_argument(
            "glTF cameras are not representable by MeshScene");
    if (data.lights_count != 0)
        throw std::invalid_argument(
            "glTF lights are not representable by MeshScene");
    if (data.animations_count != 0)
        throw std::invalid_argument(
            "glTF animation is not representable by MeshScene");
    if (data.variants_count != 0)
        throw std::invalid_argument(
            "glTF material variants are not representable by MeshScene");
    reject_extras(data.extras, "document");
}

void reject_unrepresented_content(const cgltf_data &data) {
    reject_extensions(data);
    if (data.materials_count >
            static_cast<cgltf_size>(
                std::numeric_limits<int32_t>::max()) ||
        data.meshes_count >
            static_cast<cgltf_size>(
                std::numeric_limits<int64_t>::max()) ||
        data.nodes_count >
            static_cast<cgltf_size>(
                std::numeric_limits<int64_t>::max()) ||
        data.scenes_count >
            static_cast<cgltf_size>(
                std::numeric_limits<int64_t>::max()))
        throw std::length_error(
            "glTF domain count exceeds MeshScene index capacity");
    for (cgltf_size index = 0; index < data.buffers_count; ++index) {
        validate_uri(data.buffers[index].uri, "glTF buffer URI");
        reject_extras(data.buffers[index].extras, "buffer");
        if (data.buffers[index].extensions_count != 0)
            throw std::invalid_argument(
                "glTF buffer extensions are not representable");
    }
    for (cgltf_size index = 0;
         index < data.buffer_views_count; ++index) {
        const cgltf_buffer_view &view = data.buffer_views[index];
        reject_extras(view.extras, "bufferView");
        if (view.extensions_count != 0 ||
            view.has_meshopt_compression)
            throw std::invalid_argument(
                "glTF compressed or extended bufferViews are unsupported");
    }
    for (cgltf_size index = 0; index < data.accessors_count; ++index) {
        reject_extras(data.accessors[index].extras, "accessor");
        if (data.accessors[index].extensions_count != 0)
            throw std::invalid_argument(
                "glTF accessor extensions are not representable");
    }
    for (cgltf_size index = 0; index < data.images_count; ++index) {
        const cgltf_image &image = data.images[index];
        validate_uri(image.uri, "glTF image URI");
        reject_extras(image.extras, "image");
        if (image.extensions_count != 0)
            throw std::invalid_argument(
                "glTF image extensions are not representable");
        if (!image.uri && image.buffer_view)
            throw std::invalid_argument(
                "glTF bufferView-backed images are outside the "
                "MaterialSet image-reference subset");
        if (!image.uri)
            throw std::invalid_argument(
                "glTF image must contain a URI reference");
    }
    for (cgltf_size index = 0; index < data.textures_count; ++index) {
        const cgltf_texture &texture = data.textures[index];
        reject_extras(texture.extras, "texture");
        if (texture.extensions_count != 0 ||
            texture.has_basisu || texture.has_webp)
            throw std::invalid_argument(
                "glTF extended texture sources are unsupported");
        if (!texture.image)
            throw std::invalid_argument(
                "glTF texture has no image source");
    }
    for (cgltf_size index = 0; index < data.samplers_count; ++index) {
        reject_extras(data.samplers[index].extras, "sampler");
        if (data.samplers[index].extensions_count != 0)
            throw std::invalid_argument(
                "glTF sampler extensions are not representable");
    }
    for (cgltf_size index = 0; index < data.materials_count; ++index) {
        const cgltf_material &material = data.materials[index];
        reject_extras(material.extras, "material");
        if (material.extensions_count != 0 ||
            material.has_pbr_specular_glossiness ||
            material.has_clearcoat || material.has_transmission ||
            material.has_volume || material.has_ior ||
            material.has_specular || material.has_sheen ||
            material.has_emissive_strength ||
            material.has_iridescence ||
            material.has_diffuse_transmission ||
            material.has_anisotropy || material.has_dispersion ||
            material.unlit)
            throw std::invalid_argument(
                "glTF material extensions are outside the metallic-"
                "roughness core");
        if (material.double_sided)
            throw std::invalid_argument(
                "glTF double-sided materials are not represented by "
                "MaterialSet");
    }
    for (cgltf_size mesh_index = 0;
         mesh_index < data.meshes_count; ++mesh_index) {
        const cgltf_mesh &mesh = data.meshes[mesh_index];
        reject_extras(mesh.extras, "mesh");
        if (mesh.extensions_count != 0 ||
            mesh.weights_count != 0 ||
            mesh.target_names_count != 0)
            throw std::invalid_argument(
                "glTF mesh morph metadata is not representable");
        if (mesh.primitives_count == 0)
            throw std::invalid_argument(
                "glTF meshes must contain at least one primitive");
        for (cgltf_size primitive_index = 0;
             primitive_index < mesh.primitives_count;
             ++primitive_index) {
            const cgltf_primitive &primitive =
                mesh.primitives[primitive_index];
            reject_extras(primitive.extras, "primitive");
            if (primitive.extensions_count != 0 ||
                primitive.targets_count != 0 ||
                primitive.has_draco_mesh_compression ||
                primitive.mappings_count != 0)
                throw std::invalid_argument(
                    "glTF compressed, morphed, or variant primitives "
                    "are unsupported");
            if (primitive.type != cgltf_primitive_type_triangles)
                throw std::invalid_argument(
                    "glTF core supports TRIANGLES primitives only");
        }
    }
    for (cgltf_size index = 0; index < data.nodes_count; ++index) {
        const cgltf_node &node = data.nodes[index];
        reject_extras(node.extras, "node");
        if (node.extensions_count != 0 || node.skin ||
            node.camera || node.light ||
            node.weights_count != 0 ||
            node.has_mesh_gpu_instancing)
            throw std::invalid_argument(
                "glTF node skins, cameras, lights, weights, and "
                "instancing are not representable");
    }
    for (cgltf_size index = 0; index < data.scenes_count; ++index) {
        reject_extras(data.scenes[index].extras, "scene");
        if (data.scenes[index].extensions_count != 0)
            throw std::invalid_argument(
                "glTF scene extensions are not representable");
    }
}

const cgltf_accessor *find_unique_attribute(
    const cgltf_primitive &primitive,
    cgltf_attribute_type type, cgltf_int set,
    bool required) {
    const cgltf_accessor *found = nullptr;
    for (cgltf_size index = 0;
         index < primitive.attributes_count; ++index) {
        const cgltf_attribute &attribute =
            primitive.attributes[index];
        const bool supported =
            (attribute.type == cgltf_attribute_type_position &&
             attribute.index == 0) ||
            (attribute.type == cgltf_attribute_type_normal &&
             attribute.index == 0) ||
            (attribute.type == cgltf_attribute_type_texcoord &&
             attribute.index == 0) ||
            (attribute.type == cgltf_attribute_type_color &&
             attribute.index == 0);
        if (!supported)
            throw std::invalid_argument(
                "glTF primitive contains an unsupported attribute "
                "semantic or attribute set");
        if (attribute.type == type && attribute.index == set) {
            if (found)
                throw std::invalid_argument(
                    "glTF primitive repeats an attribute semantic");
            found = attribute.data;
        }
    }
    if (required && !found)
        throw std::invalid_argument(
            "glTF primitive requires POSITION");
    return found;
}

void require_accessor(
    const cgltf_accessor &accessor,
    cgltf_type type, cgltf_component_type component,
    bool normalized, const char *name) {
    if (accessor.type != type ||
        accessor.component_type != component ||
        static_cast<bool>(accessor.normalized) != normalized)
        throw std::invalid_argument(
            std::string("glTF ") + name +
            " accessor has an unsupported type");
}

struct PrimitiveSchema {
    const cgltf_accessor *positions;
    const cgltf_accessor *normals;
    const cgltf_accessor *uvs;
    const cgltf_accessor *colors;
    size_t vertices;
    size_t indices;
};

PrimitiveSchema validate_primitive_schema(
    const cgltf_primitive &primitive) {
    PrimitiveSchema schema{
        find_unique_attribute(
            primitive, cgltf_attribute_type_position, 0, true),
        find_unique_attribute(
            primitive, cgltf_attribute_type_normal, 0, false),
        find_unique_attribute(
            primitive, cgltf_attribute_type_texcoord, 0, false),
        find_unique_attribute(
            primitive, cgltf_attribute_type_color, 0, false),
        0,
        0,
    };
    require_accessor(
        *schema.positions, cgltf_type_vec3,
        cgltf_component_type_r_32f, false, "POSITION");
    schema.vertices =
        static_cast<size_t>(schema.positions->count);
    if (schema.vertices == 0)
        throw std::invalid_argument(
            "glTF primitives cannot have zero POSITION rows");

    if (schema.normals) {
        require_accessor(
            *schema.normals, cgltf_type_vec3,
            cgltf_component_type_r_32f, false, "NORMAL");
        if (schema.normals->count != schema.positions->count)
            throw std::invalid_argument(
                "glTF NORMAL count disagrees with POSITION");
    }
    if (schema.uvs) {
        if (schema.uvs->type != cgltf_type_vec2 ||
            !(
                (schema.uvs->component_type ==
                     cgltf_component_type_r_32f &&
                 !schema.uvs->normalized) ||
                ((schema.uvs->component_type ==
                      cgltf_component_type_r_8u ||
                  schema.uvs->component_type ==
                      cgltf_component_type_r_16u) &&
                 schema.uvs->normalized)))
            throw std::invalid_argument(
                "glTF TEXCOORD_0 accessor has an unsupported type");
        if (schema.uvs->count != schema.positions->count)
            throw std::invalid_argument(
                "glTF TEXCOORD_0 count disagrees with POSITION");
    }
    if (schema.colors) {
        if ((schema.colors->type != cgltf_type_vec3 &&
             schema.colors->type != cgltf_type_vec4) ||
            schema.colors->component_type !=
                cgltf_component_type_r_8u ||
            !schema.colors->normalized)
            throw std::invalid_argument(
                "glTF core preserves COLOR_0 only as normalized "
                "unsigned bytes");
        if (schema.colors->count != schema.positions->count)
            throw std::invalid_argument(
                "glTF COLOR_0 count disagrees with POSITION");
    }
    if (primitive.indices &&
        (primitive.indices->type != cgltf_type_scalar ||
         primitive.indices->normalized ||
         (primitive.indices->component_type !=
              cgltf_component_type_r_8u &&
          primitive.indices->component_type !=
              cgltf_component_type_r_16u &&
          primitive.indices->component_type !=
              cgltf_component_type_r_32u)))
        throw std::invalid_argument(
            "glTF index accessor has an unsupported type");
    schema.indices =
        primitive.indices
            ? static_cast<size_t>(primitive.indices->count)
            : schema.vertices;
    if (schema.indices == 0 || schema.indices % 3 != 0)
        throw std::invalid_argument(
            "glTF TRIANGLES index count must be positive and "
            "divisible by 3");
    return schema;
}

std::vector<float> unpack_floats(
    const cgltf_accessor &accessor,
    size_t components, const char *name) {
    if (accessor.count >
        std::numeric_limits<size_t>::max() / components)
        throw std::length_error(
            std::string("glTF ") + name + " accessor is too large");
    std::vector<float> result(
        static_cast<size_t>(accessor.count) * components);
    const cgltf_size count = cgltf_accessor_unpack_floats(
        &accessor, result.data(), result.size());
    if (count != result.size())
        throw std::invalid_argument(
            std::string("glTF ") + name +
            " accessor could not be unpacked");
    return result;
}

uint64_t read_index_component(
    const uint8_t *data, cgltf_component_type type) {
    switch (type) {
        case cgltf_component_type_r_8u:
            return data[0];
        case cgltf_component_type_r_16u:
            return static_cast<uint64_t>(data[0]) |
                   (static_cast<uint64_t>(data[1]) << 8);
        case cgltf_component_type_r_32u:
            return static_cast<uint64_t>(data[0]) |
                   (static_cast<uint64_t>(data[1]) << 8) |
                   (static_cast<uint64_t>(data[2]) << 16) |
                   (static_cast<uint64_t>(data[3]) << 24);
        default:
            throw std::invalid_argument(
                "glTF index accessor must use unsigned 8/16/32-bit "
                "components");
    }
}

std::vector<uint64_t> unpack_indices(
    const cgltf_accessor &accessor) {
    if (accessor.type != cgltf_type_scalar ||
        accessor.normalized ||
        (accessor.component_type != cgltf_component_type_r_8u &&
         accessor.component_type != cgltf_component_type_r_16u &&
         accessor.component_type != cgltf_component_type_r_32u))
        throw std::invalid_argument(
            "glTF index accessor has an unsupported type");
    std::vector<uint64_t> result(
        static_cast<size_t>(accessor.count), 0);
    if (accessor.buffer_view) {
        const uint8_t *base =
            cgltf_buffer_view_data(accessor.buffer_view);
        if (!base)
            throw std::invalid_argument(
                "glTF index buffer is unavailable");
        base += accessor.offset;
        for (size_t index = 0; index < result.size(); ++index)
            result[index] = read_index_component(
                base + accessor.stride * index,
                accessor.component_type);
    }
    if (accessor.is_sparse) {
        const cgltf_accessor_sparse &sparse = accessor.sparse;
        const uint8_t *indices =
            cgltf_buffer_view_data(sparse.indices_buffer_view);
        const uint8_t *values =
            cgltf_buffer_view_data(sparse.values_buffer_view);
        if (!indices || !values)
            throw std::invalid_argument(
                "glTF sparse index buffers are unavailable");
        indices += sparse.indices_byte_offset;
        values += sparse.values_byte_offset;
        const size_t index_stride =
            static_cast<size_t>(
                cgltf_component_size(
                    sparse.indices_component_type));
        const size_t value_stride =
            static_cast<size_t>(
                cgltf_calc_size(
                    accessor.type, accessor.component_type));
        uint64_t previous_destination = 0;
        for (size_t row = 0;
             row < static_cast<size_t>(sparse.count); ++row) {
            const uint64_t destination = read_index_component(
                indices + row * index_stride,
                sparse.indices_component_type);
            if (destination >= result.size())
                throw std::invalid_argument(
                    "glTF sparse index destination is out of range");
            if (row != 0 &&
                destination <= previous_destination)
                throw std::invalid_argument(
                    "glTF sparse indices must be strictly increasing");
            previous_destination = destination;
            result[static_cast<size_t>(destination)] =
                read_index_component(
                    values + row * value_stride,
                    accessor.component_type);
        }
    }
    return result;
}

uint8_t color_byte(float value) {
    if (!std::isfinite(value) || value < 0.0F || value > 1.0F)
        throw std::invalid_argument(
            "glTF COLOR_0 values must be finite normalized values");
    return static_cast<uint8_t>(
        std::lround(static_cast<double>(value) * 255.0));
}

Mesh decode_primitive(const cgltf_data &data,
                      const cgltf_primitive &primitive) {
    const PrimitiveSchema schema =
        validate_primitive_schema(primitive);
    const cgltf_accessor *positions = schema.positions;
    const cgltf_accessor *normals = schema.normals;
    const cgltf_accessor *uvs = schema.uvs;
    const cgltf_accessor *colors = schema.colors;
    const size_t vertices = schema.vertices;

    Mesh mesh;
    mesh.n = vertices;
    mesh.positions = unpack_floats(*positions, 3, "POSITION");
    if (normals) {
        mesh.vertex_normals = unpack_floats(*normals, 3, "NORMAL");
    }
    if (uvs) {
        mesh.vertex_uvs = unpack_floats(*uvs, 2, "TEXCOORD_0");
    }
    if (colors) {
        const size_t components =
            colors->type == cgltf_type_vec3 ? 3 : 4;
        const std::vector<float> values =
            unpack_floats(*colors, components, "COLOR_0");
        mesh.vertex_colors.resize(vertices * 4, 255);
        for (size_t vertex = 0; vertex < vertices; ++vertex)
            for (size_t component = 0;
                 component < components; ++component)
                mesh.vertex_colors[vertex * 4 + component] =
                    color_byte(
                        values[vertex * components + component]);
    }

    if (primitive.indices)
        mesh.face_indices = unpack_indices(*primitive.indices);
    else {
        mesh.face_indices.resize(vertices);
        for (size_t index = 0; index < vertices; ++index)
            mesh.face_indices[index] = index;
    }
    mesh.c = mesh.face_indices.size();
    if (mesh.c != schema.indices)
        throw std::logic_error(
            "glTF decoded index count disagrees with validated schema");
    mesh.f = mesh.c / 3;
    for (uint64_t index : mesh.face_indices)
        if (index >= vertices)
            throw std::invalid_argument(
                "glTF primitive index exceeds POSITION count");
    mesh.face_offsets.resize(mesh.f + 1);
    for (size_t face = 0; face <= mesh.f; ++face)
        mesh.face_offsets[face] =
            static_cast<uint64_t>(face * 3);
    mesh.primitive_offsets = {0, static_cast<uint64_t>(mesh.f)};
    mesh.primitive_materials = {
        primitive.material
            ? static_cast<int32_t>(
                  cgltf_material_index(&data, primitive.material))
            : -1};
    mesh.coordinate_frame = "opengl";
    mesh.scale_to_meters = 1.0;
    validate_mesh(mesh, "glTF primitive");
    return mesh;
}

uint8_t wrap_code(cgltf_wrap_mode value) {
    switch (value) {
        case cgltf_wrap_mode_repeat:
            return 0;
        case cgltf_wrap_mode_clamp_to_edge:
            return 1;
        case cgltf_wrap_mode_mirrored_repeat:
            return 2;
        default:
            throw std::invalid_argument(
                "glTF sampler contains an unsupported wrap mode");
    }
}

uint8_t filter_code(cgltf_filter_type value, bool magnification) {
    switch (value) {
        case cgltf_filter_type_undefined:
            return 0;
        case cgltf_filter_type_nearest:
            return 1;
        case cgltf_filter_type_linear:
            return 2;
        case cgltf_filter_type_nearest_mipmap_nearest:
            if (magnification) break;
            return 3;
        case cgltf_filter_type_linear_mipmap_nearest:
            if (magnification) break;
            return 4;
        case cgltf_filter_type_nearest_mipmap_linear:
            if (magnification) break;
            return 5;
        case cgltf_filter_type_linear_mipmap_linear:
            if (magnification) break;
            return 6;
    }
    throw std::invalid_argument(
        "glTF sampler contains an unsupported filter");
}

void add_texture_binding(
    MaterialSet &result, size_t material,
    uint8_t semantic, const cgltf_texture_view &view) {
    if (!view.texture) return;
    if (view.has_transform)
        throw std::invalid_argument(
            "glTF texture transforms are not represented by MaterialSet");
    if (view.texcoord < 0)
        throw std::invalid_argument(
            "glTF texture coordinate set cannot be negative");
    if (view.texcoord != 0)
        throw std::invalid_argument(
            "glTF core preserves TEXCOORD_0 only");
    const cgltf_texture &texture = *view.texture;
    if (!texture.image || !texture.image->uri)
        throw std::invalid_argument(
            "glTF texture image URI is unavailable");
    result.texture_materials.push_back(material);
    result.texture_semantics.push_back(semantic);
    result.texture_uv_sets.push_back(
        static_cast<uint32_t>(view.texcoord));
    const cgltf_sampler *sampler = texture.sampler;
    result.texture_wrap_s.push_back(
        sampler ? wrap_code(sampler->wrap_s) : 0);
    result.texture_wrap_t.push_back(
        sampler ? wrap_code(sampler->wrap_t) : 0);
    result.texture_min_filters.push_back(
        sampler ? filter_code(sampler->min_filter, false) : 0);
    result.texture_mag_filters.push_back(
        sampler ? filter_code(sampler->mag_filter, true) : 0);
}

MaterialSet decode_materials(const cgltf_data &data) {
    MaterialSet result;
    result.n = static_cast<size_t>(data.materials_count);
    std::vector<std::string> names;
    std::vector<std::string> paths;
    names.reserve(result.n);
    for (size_t index = 0; index < result.n; ++index) {
        const cgltf_material &source = data.materials[index];
        names.emplace_back(source.name ? source.name : "");
        const cgltf_pbr_metallic_roughness &pbr =
            source.pbr_metallic_roughness;
        result.base_colors.insert(
            result.base_colors.end(),
            pbr.base_color_factor,
            pbr.base_color_factor + 4);
        result.emissive_colors.insert(
            result.emissive_colors.end(),
            source.emissive_factor,
            source.emissive_factor + 3);
        result.metallic.push_back(pbr.metallic_factor);
        result.roughness.push_back(pbr.roughness_factor);
        switch (source.alpha_mode) {
            case cgltf_alpha_mode_opaque:
                result.alpha_modes.push_back(0);
                break;
            case cgltf_alpha_mode_mask:
                result.alpha_modes.push_back(1);
                break;
            case cgltf_alpha_mode_blend:
                result.alpha_modes.push_back(2);
                break;
            default:
                throw std::invalid_argument(
                    "glTF material has an invalid alpha mode");
        }
        result.alpha_cutoffs.push_back(source.alpha_cutoff);
        add_texture_binding(
            result, index, 0, pbr.base_color_texture);
        add_texture_binding(
            result, index, 10,
            pbr.metallic_roughness_texture);
        if (source.normal_texture.texture &&
            source.normal_texture.scale != 1.0F)
            throw std::invalid_argument(
                "glTF normal texture scale is not represented by "
                "MaterialSet");
        add_texture_binding(
            result, index, 4, source.normal_texture);
        if (source.occlusion_texture.texture &&
            source.occlusion_texture.scale != 1.0F)
            throw std::invalid_argument(
                "glTF occlusion strength is not represented by "
                "MaterialSet");
        add_texture_binding(
            result, index, 11, source.occlusion_texture);
        add_texture_binding(
            result, index, 7, source.emissive_texture);
    }
    result.t = result.texture_materials.size();
    paths.reserve(result.t);
    for (size_t material = 0; material < result.n; ++material) {
        const cgltf_material &source = data.materials[material];
        const std::array<const cgltf_texture_view *, 5> views = {
            &source.pbr_metallic_roughness.base_color_texture,
            &source.pbr_metallic_roughness.metallic_roughness_texture,
            &source.normal_texture,
            &source.occlusion_texture,
            &source.emissive_texture,
        };
        for (const cgltf_texture_view *view : views)
            if (view->texture)
                paths.emplace_back(
                    view->texture->image->uri);
    }
    assign_material_names(result, names);
    assign_material_texture_paths(result, paths);
    validate_material_set(result, "glTF materials");
    return result;
}

std::string source_name(const char *value) {
    return value ? std::string(value) : std::string();
}

struct Selection {
    enum class Kind { All, Mesh, Primitive };
    Kind kind = Kind::All;
    size_t index = 0;
};

MeshScene decode_scene(
    const cgltf_data &data, Selection selection) {
    reject_unrepresented_content(data);
    MeshScene result;
    if (data.materials_count != 0) {
        result.materials = decode_materials(data);
        result.has_material_set = true;
    }

    size_t global_primitive = 0;
    std::vector<std::string> mesh_names;
    result.mesh_primitive_offsets.push_back(0);
    for (size_t mesh_index = 0;
         mesh_index < static_cast<size_t>(data.meshes_count);
         ++mesh_index) {
        const cgltf_mesh &source = data.meshes[mesh_index];
        const size_t begin = global_primitive;
        if (static_cast<size_t>(source.primitives_count) >
            std::numeric_limits<size_t>::max() - begin)
            throw std::length_error(
                "glTF primitive count overflows size_t");
        const size_t end =
            begin + static_cast<size_t>(source.primitives_count);
        const bool include_mesh =
            selection.kind == Selection::Kind::All ||
            (selection.kind == Selection::Kind::Mesh &&
             selection.index == mesh_index) ||
            (selection.kind == Selection::Kind::Primitive &&
             selection.index >= begin && selection.index < end);
        if (include_mesh) {
            mesh_names.push_back(source_name(source.name));
            for (size_t local = 0;
                 local < static_cast<size_t>(source.primitives_count);
                 ++local) {
                const size_t current = begin + local;
                if (selection.kind != Selection::Kind::Primitive ||
                    selection.index == current)
                    result.primitives.push_back(
                        decode_primitive(
                            data, source.primitives[local]));
            }
            result.mesh_primitive_offsets.push_back(
                static_cast<uint64_t>(result.primitives.size()));
        }
        global_primitive = end;
    }
    if (selection.kind == Selection::Kind::Mesh &&
        selection.index >= static_cast<size_t>(data.meshes_count))
        throw std::out_of_range(
            "glTF mesh_id is out of range");
    if (selection.kind == Selection::Kind::Primitive &&
        selection.index >= global_primitive)
        throw std::out_of_range(
            "glTF primitive_id is out of range");

    if (selection.kind == Selection::Kind::All) {
        std::vector<std::string> node_names;
        node_names.reserve(data.nodes_count);
        result.node_child_offsets.push_back(0);
        for (size_t index = 0;
             index < static_cast<size_t>(data.nodes_count); ++index) {
            const cgltf_node &node = data.nodes[index];
            node_names.push_back(source_name(node.name));
            result.node_meshes.push_back(
                node.mesh
                    ? static_cast<int64_t>(
                          cgltf_mesh_index(&data, node.mesh))
                    : -1);
            for (size_t child = 0;
                 child < static_cast<size_t>(node.children_count);
                 ++child)
                result.node_children.push_back(
                    cgltf_node_index(&data, node.children[child]));
            result.node_child_offsets.push_back(
                static_cast<uint64_t>(
                    result.node_children.size()));
            cgltf_float column_major[16];
            cgltf_node_transform_local(&node, column_major);
            for (size_t row = 0; row < 4; ++row)
                for (size_t column = 0; column < 4; ++column)
                    result.node_local_transforms.push_back(
                        static_cast<double>(
                            column_major[column * 4 + row]));
        }
        std::vector<std::string> scene_names;
        scene_names.reserve(data.scenes_count);
        result.scene_root_offsets.push_back(0);
        for (size_t index = 0;
             index < static_cast<size_t>(data.scenes_count); ++index) {
            const cgltf_scene &scene = data.scenes[index];
            scene_names.push_back(source_name(scene.name));
            for (size_t root = 0;
                 root < static_cast<size_t>(scene.nodes_count);
                 ++root)
                result.scene_roots.push_back(
                    cgltf_node_index(&data, scene.nodes[root]));
            result.scene_root_offsets.push_back(
                static_cast<uint64_t>(
                    result.scene_roots.size()));
        }
        result.default_scene =
            data.scene
                ? static_cast<int64_t>(
                      data.scene - data.scenes)
                : -1;
        assign_mesh_scene_names(
            result, mesh_names, node_names, scene_names);
    } else {
        result.node_child_offsets = {0};
        result.scene_root_offsets = {0};
        result.default_scene = -1;
        assign_mesh_scene_names(
            result, mesh_names, {}, {});
    }
    validate_mesh_scene(result, "glTF decode");
    return result;
}

MeshScene read_document(
    nb::handle source, nb::dict resources,
    cgltf_file_type expected, Selection selection) {
    sio::ByteView bytes(source);
    ParsedData parsed = parse_document(bytes, expected);
    auto pins = load_buffers(parsed, std::move(resources));
    nb::gil_scoped_release release;
    return decode_scene(*parsed.value, selection);
}

nb::dict inspect_document(
    nb::handle source, cgltf_file_type expected) {
    sio::ByteView bytes(source);
    ParsedData parsed = parse_document(bytes, expected);
    size_t primitive_count = 0;
    size_t vertex_count = 0;
    size_t face_count = 0;
    size_t external_buffers = 0;
    size_t buffer_bytes = 0;
    size_t external_buffer_bytes = 0;
    {
        nb::gil_scoped_release release;
        require_success(cgltf_validate(parsed.value), "validation");
        reject_unrepresented_content(*parsed.value);
        for (size_t mesh = 0;
             mesh < static_cast<size_t>(
                        parsed.value->meshes_count);
             ++mesh) {
            const cgltf_mesh &value = parsed.value->meshes[mesh];
            if (static_cast<size_t>(value.primitives_count) >
                std::numeric_limits<size_t>::max() -
                    primitive_count)
                throw std::length_error(
                    "glTF primitive count overflows size_t");
            primitive_count +=
                static_cast<size_t>(value.primitives_count);
            for (size_t primitive = 0;
                 primitive <
                 static_cast<size_t>(value.primitives_count);
                 ++primitive) {
                const cgltf_primitive &item =
                    value.primitives[primitive];
                const PrimitiveSchema schema =
                    validate_primitive_schema(item);
                if (schema.vertices >
                        std::numeric_limits<size_t>::max() -
                            vertex_count ||
                    schema.indices / 3 >
                        std::numeric_limits<size_t>::max() -
                            face_count)
                    throw std::length_error(
                        "glTF inspected geometry counts overflow "
                        "size_t");
                vertex_count += schema.vertices;
                face_count += schema.indices / 3;
            }
        }
        for (size_t index = 0;
             index < static_cast<size_t>(
                         parsed.value->buffers_count);
             ++index) {
            const size_t length =
                static_cast<size_t>(
                    parsed.value->buffers[index].size);
            if (length >
                std::numeric_limits<size_t>::max() -
                    buffer_bytes)
                throw std::length_error(
                    "glTF declared buffer sizes overflow size_t");
            buffer_bytes += length;
            const char *uri =
                parsed.value->buffers[index].uri;
            if (uri && std::strncmp(uri, "data:", 5) != 0) {
                ++external_buffers;
                if (length >
                    std::numeric_limits<size_t>::max() -
                        external_buffer_bytes)
                    throw std::length_error(
                        "glTF external buffer sizes overflow "
                        "size_t");
                external_buffer_bytes += length;
            }
        }
    }
    nb::dict result;
    result["num_meshes"] =
        static_cast<size_t>(parsed.value->meshes_count);
    result["num_primitives"] = primitive_count;
    result["num_vertices"] = vertex_count;
    result["num_faces"] = face_count;
    result["num_nodes"] =
        static_cast<size_t>(parsed.value->nodes_count);
    result["num_scenes"] =
        static_cast<size_t>(parsed.value->scenes_count);
    result["num_materials"] =
        static_cast<size_t>(parsed.value->materials_count);
    result["num_accessors"] =
        static_cast<size_t>(parsed.value->accessors_count);
    result["num_buffers"] =
        static_cast<size_t>(parsed.value->buffers_count);
    result["num_external_buffers"] = external_buffers;
    result["buffer_bytes"] = buffer_bytes;
    result["external_buffer_bytes"] = external_buffer_bytes;
    result["dtype"] = "float32";
    return result;
}

std::vector<std::string> external_buffer_uris(
    nb::handle source, cgltf_file_type expected) {
    sio::ByteView bytes(source);
    ParsedData parsed = parse_document(bytes, expected);
    std::vector<std::string> result;
    std::unordered_set<std::string> unique;
    {
        nb::gil_scoped_release release;
        for (size_t index = 0;
             index < static_cast<size_t>(
                         parsed.value->buffers_count);
             ++index) {
            const char *uri = parsed.value->buffers[index].uri;
            if (!uri || std::strncmp(uri, "data:", 5) == 0)
                continue;
            validate_uri(uri, "glTF external buffer URI");
            if (unique.insert(uri).second)
                result.emplace_back(uri);
        }
    }
    return result;
}

template <typename T>
void append_little(std::vector<uint8_t> &out, T value) {
    static_assert(std::is_trivially_copyable_v<T>);
    if (!sio::host_is_le()) {
        std::array<uint8_t, sizeof(T)> bytes{};
        std::memcpy(bytes.data(), &value, sizeof(T));
        std::reverse(bytes.begin(), bytes.end());
        out.insert(out.end(), bytes.begin(), bytes.end());
    } else {
        const uint8_t *bytes =
            reinterpret_cast<const uint8_t *>(&value);
        out.insert(out.end(), bytes, bytes + sizeof(T));
    }
}

void align_four(std::vector<uint8_t> &out) {
    while (out.size() % 4 != 0) out.push_back(0);
}

struct EncodedScene {
    std::string json;
    std::vector<uint8_t> binary;
};

struct WriterModel {
    cgltf_data data{};
    cgltf_options options{};
    std::vector<uint8_t> binary;
    std::vector<cgltf_buffer> buffers;
    std::vector<cgltf_buffer_view> views;
    std::vector<cgltf_accessor> accessors;
    std::vector<cgltf_attribute> attributes;
    std::vector<cgltf_primitive> primitives;
    std::vector<cgltf_mesh> meshes;
    std::vector<cgltf_material> materials;
    std::vector<cgltf_image> images;
    std::vector<cgltf_texture> textures;
    std::vector<cgltf_sampler> samplers;
    std::vector<cgltf_node> nodes;
    std::vector<cgltf_node *> child_pointers;
    std::vector<cgltf_scene> scenes;
    std::vector<cgltf_node *> root_pointers;
    std::vector<std::string> mesh_names;
    std::vector<std::string> node_names;
    std::vector<std::string> scene_names;
    std::vector<std::string> material_names_value;
    std::vector<std::string> texture_paths;
    std::string buffer_uri;
    std::string asset_version = "2.0";
    std::string asset_generator = "SceneIO 0.2";

    size_t view_cursor = 0;
    size_t accessor_cursor = 0;
    size_t attribute_cursor = 0;

    cgltf_accessor *append_float_accessor(
        const std::vector<float> &values, size_t count,
        cgltf_type type, bool position,
        cgltf_buffer_view_type view_type) {
        if (values.size() >
            std::numeric_limits<size_t>::max() / sizeof(float))
            throw std::length_error(
                "glTF float accessor byte extent overflows size_t");
        align_four(binary);
        const size_t offset = binary.size();
        for (float value : values) append_little(binary, value);
        cgltf_buffer_view &view = views[view_cursor++];
        view.buffer = &buffers[0];
        view.offset = offset;
        view.size = values.size() * sizeof(float);
        view.type = view_type;
        cgltf_accessor &accessor =
            accessors[accessor_cursor++];
        accessor.buffer_view = &view;
        accessor.component_type =
            cgltf_component_type_r_32f;
        accessor.type = type;
        accessor.count = count;
        accessor.stride =
            cgltf_num_components(type) * sizeof(float);
        if (position) {
            accessor.has_min = true;
            accessor.has_max = true;
            for (size_t axis = 0; axis < 3; ++axis) {
                accessor.min[axis] =
                    std::numeric_limits<float>::infinity();
                accessor.max[axis] =
                    -std::numeric_limits<float>::infinity();
            }
            for (size_t row = 0; row < count; ++row)
                for (size_t axis = 0; axis < 3; ++axis) {
                    accessor.min[axis] = std::min(
                        accessor.min[axis],
                        values[row * 3 + axis]);
                    accessor.max[axis] = std::max(
                        accessor.max[axis],
                        values[row * 3 + axis]);
                }
        }
        return &accessor;
    }

    cgltf_accessor *append_color_accessor(const Mesh &mesh) {
        align_four(binary);
        const size_t offset = binary.size();
        binary.insert(
            binary.end(), mesh.vertex_colors.begin(),
            mesh.vertex_colors.end());
        cgltf_buffer_view &view = views[view_cursor++];
        view.buffer = &buffers[0];
        view.offset = offset;
        view.size = mesh.vertex_colors.size();
        view.type = cgltf_buffer_view_type_vertices;
        cgltf_accessor &accessor =
            accessors[accessor_cursor++];
        accessor.buffer_view = &view;
        accessor.component_type =
            cgltf_component_type_r_8u;
        accessor.normalized = true;
        accessor.type = cgltf_type_vec4;
        accessor.count = mesh.n;
        accessor.stride = 4;
        return &accessor;
    }

    cgltf_accessor *append_index_accessor(const Mesh &mesh) {
        if (mesh.face_indices.size() >
            std::numeric_limits<size_t>::max() / sizeof(uint32_t))
            throw std::length_error(
                "glTF index accessor byte extent overflows size_t");
        align_four(binary);
        const size_t offset = binary.size();
        for (uint64_t value : mesh.face_indices) {
            if (value > std::numeric_limits<uint32_t>::max())
                throw std::invalid_argument(
                    "glTF writer cannot represent an index above "
                    "uint32");
            append_little(
                binary, static_cast<uint32_t>(value));
        }
        cgltf_buffer_view &view = views[view_cursor++];
        view.buffer = &buffers[0];
        view.offset = offset;
        view.size = mesh.face_indices.size() * sizeof(uint32_t);
        view.type = cgltf_buffer_view_type_indices;
        cgltf_accessor &accessor =
            accessors[accessor_cursor++];
        accessor.buffer_view = &view;
        accessor.component_type =
            cgltf_component_type_r_32u;
        accessor.type = cgltf_type_scalar;
        accessor.count = mesh.face_indices.size();
        accessor.stride = sizeof(uint32_t);
        return &accessor;
    }

    void add_attribute(
        cgltf_primitive &primitive,
        cgltf_attribute_type type,
        cgltf_accessor *accessor) {
        cgltf_attribute &attribute =
            attributes[attribute_cursor++];
        attribute.type = type;
        attribute.index = 0;
        attribute.data = accessor;
        switch (type) {
            case cgltf_attribute_type_position:
                attribute.name =
                    const_cast<char *>("POSITION");
                break;
            case cgltf_attribute_type_normal:
                attribute.name =
                    const_cast<char *>("NORMAL");
                break;
            case cgltf_attribute_type_texcoord:
                attribute.name =
                    const_cast<char *>("TEXCOORD_0");
                break;
            case cgltf_attribute_type_color:
                attribute.name =
                    const_cast<char *>("COLOR_0");
                break;
            default:
                throw std::logic_error(
                    "unsupported writer attribute type");
        }
        if (!primitive.attributes)
            primitive.attributes = &attribute;
        ++primitive.attributes_count;
    }
};

cgltf_wrap_mode writer_wrap(uint8_t code) {
    switch (code) {
        case 0:
            return cgltf_wrap_mode_repeat;
        case 1:
            return cgltf_wrap_mode_clamp_to_edge;
        case 2:
            return cgltf_wrap_mode_mirrored_repeat;
        default:
            throw std::invalid_argument(
                "glTF writer received an invalid texture wrap");
    }
}

cgltf_filter_type writer_filter(uint8_t code, bool magnification) {
    static constexpr cgltf_filter_type values[] = {
        cgltf_filter_type_undefined,
        cgltf_filter_type_nearest,
        cgltf_filter_type_linear,
        cgltf_filter_type_nearest_mipmap_nearest,
        cgltf_filter_type_linear_mipmap_nearest,
        cgltf_filter_type_nearest_mipmap_linear,
        cgltf_filter_type_linear_mipmap_linear,
    };
    if (code >= std::size(values) || (magnification && code > 2))
        throw std::invalid_argument(
            "glTF writer received an invalid texture filter");
    return values[code];
}

void build_writer_model(
    WriterModel &model, const MeshScene &scene,
    const std::string &buffer_uri,
    bool binary_container) {
    validate_mesh_scene(scene, "glTF writer");
    model.mesh_names = mesh_scene_mesh_names(scene);
    model.node_names = mesh_scene_node_names(scene);
    model.scene_names = mesh_scene_scene_names(scene);
    model.material_names_value =
        scene.has_material_set
            ? material_names(scene.materials)
            : std::vector<std::string>{};
    model.texture_paths =
        scene.has_material_set
            ? material_texture_paths(scene.materials)
            : std::vector<std::string>{};
    model.buffer_uri = buffer_uri;

    size_t attribute_count = 0;
    for (const Mesh &mesh : scene.primitives) {
        if (mesh.has_corner_normals() ||
            mesh.has_corner_uvs() ||
            mesh.has_corner_colors())
            throw std::invalid_argument(
                "glTF writer cannot preserve corner-domain attributes");
        if (mesh.has_smoothing_groups() ||
            mesh.has_object_names() || mesh.has_group_names())
            throw std::invalid_argument(
                "glTF writer cannot preserve smoothing groups or "
                "primitive object/group names");
        const size_t primitive_attributes = 1 +
            (mesh.has_vertex_normals() ? 1 : 0) +
            (mesh.has_vertex_uvs() ? 1 : 0) +
            (mesh.has_vertex_colors() ? 1 : 0);
        if (primitive_attributes >
            std::numeric_limits<size_t>::max() - attribute_count)
            throw std::length_error(
                "glTF attribute count overflows size_t");
        attribute_count += primitive_attributes;
    }
    if (scene.primitives.size() >
        std::numeric_limits<size_t>::max() - attribute_count)
        throw std::length_error(
            "glTF accessor count overflows size_t");
    const size_t accessor_count =
        attribute_count + scene.primitives.size();
    model.views.resize(accessor_count);
    model.accessors.resize(accessor_count);
    model.attributes.resize(attribute_count);
    model.primitives.resize(scene.primitives.size());
    model.meshes.resize(scene.num_meshes());
    model.materials.resize(
        scene.has_material_set
            ? scene.materials.n : 0);
    const size_t texture_count =
        scene.has_material_set
            ? scene.materials.t : 0;
    model.images.resize(texture_count);
    model.textures.resize(texture_count);
    model.samplers.resize(texture_count);
    model.nodes.resize(scene.num_nodes());
    model.child_pointers.resize(scene.node_children.size());
    model.scenes.resize(scene.num_scenes());
    model.root_pointers.resize(scene.scene_roots.size());
    model.buffers.resize(
        accessor_count == 0 ? 0 : 1);

    size_t primitive_index = 0;
    for (size_t mesh_index = 0;
         mesh_index < scene.num_meshes(); ++mesh_index) {
        cgltf_mesh &target_mesh = model.meshes[mesh_index];
        target_mesh.name = model.mesh_names[mesh_index].empty()
                               ? nullptr
                               : model.mesh_names[mesh_index].data();
        target_mesh.primitives =
            model.primitives.data() + primitive_index;
        target_mesh.primitives_count =
            static_cast<cgltf_size>(
                scene.mesh_primitive_offsets[mesh_index + 1] -
                scene.mesh_primitive_offsets[mesh_index]);
        for (size_t local = 0;
             local <
             static_cast<size_t>(target_mesh.primitives_count);
             ++local, ++primitive_index) {
            const Mesh &mesh = scene.primitives[primitive_index];
            cgltf_primitive &primitive =
                model.primitives[primitive_index];
            primitive.type = cgltf_primitive_type_triangles;
            model.add_attribute(
                primitive, cgltf_attribute_type_position,
                model.append_float_accessor(
                    mesh.positions, mesh.n, cgltf_type_vec3,
                    true, cgltf_buffer_view_type_vertices));
            if (mesh.has_vertex_normals())
                model.add_attribute(
                    primitive, cgltf_attribute_type_normal,
                    model.append_float_accessor(
                        mesh.vertex_normals, mesh.n,
                        cgltf_type_vec3, false,
                        cgltf_buffer_view_type_vertices));
            if (mesh.has_vertex_uvs())
                model.add_attribute(
                    primitive, cgltf_attribute_type_texcoord,
                    model.append_float_accessor(
                        mesh.vertex_uvs, mesh.n,
                        cgltf_type_vec2, false,
                        cgltf_buffer_view_type_vertices));
            if (mesh.has_vertex_colors())
                model.add_attribute(
                    primitive, cgltf_attribute_type_color,
                    model.append_color_accessor(mesh));
            primitive.indices =
                model.append_index_accessor(mesh);
            const int32_t material =
                mesh.primitive_materials[0];
            if (material >= 0)
                primitive.material =
                    &model.materials[
                        static_cast<size_t>(material)];
        }
    }

    if (scene.has_material_set) {
        const MaterialSet &source = scene.materials;
        for (size_t index = 0; index < source.n; ++index) {
            cgltf_material &material =
                model.materials[index];
            material.name =
                model.material_names_value[index].empty()
                    ? nullptr
                    : model.material_names_value[index].data();
            material.has_pbr_metallic_roughness = true;
            std::copy_n(
                source.base_colors.data() + index * 4, 4,
                material.pbr_metallic_roughness
                    .base_color_factor);
            std::copy_n(
                source.emissive_colors.data() + index * 3, 3,
                material.emissive_factor);
            for (size_t channel = 0; channel < 3; ++channel)
                if (material.emissive_factor[channel] > 1.0F)
                    throw std::invalid_argument(
                        "glTF core cannot encode emissive factors "
                        "above one without an extension");
            material.pbr_metallic_roughness.metallic_factor =
                source.metallic[index];
            material.pbr_metallic_roughness.roughness_factor =
                source.roughness[index];
            material.alpha_cutoff =
                source.alpha_cutoffs[index];
            switch (source.alpha_modes[index]) {
                case 0:
                    material.alpha_mode =
                        cgltf_alpha_mode_opaque;
                    break;
                case 1:
                    material.alpha_mode =
                        cgltf_alpha_mode_mask;
                    break;
                case 2:
                    material.alpha_mode =
                        cgltf_alpha_mode_blend;
                    break;
                default:
                    throw std::invalid_argument(
                        "glTF writer received an invalid alpha mode");
            }
            if (source.alpha_modes[index] != 1 &&
                source.alpha_cutoffs[index] != 0.5F)
                throw std::invalid_argument(
                    "glTF writes alphaCutoff only for MASK materials");
        }
        for (size_t index = 0; index < source.t; ++index) {
            if (source.texture_uv_sets[index] != 0)
                throw std::invalid_argument(
                    "glTF writer preserves TEXCOORD_0 only");
            cgltf_image &image = model.images[index];
            image.uri = model.texture_paths[index].data();
            cgltf_sampler &sampler = model.samplers[index];
            sampler.wrap_s =
                writer_wrap(source.texture_wrap_s[index]);
            sampler.wrap_t =
                writer_wrap(source.texture_wrap_t[index]);
            sampler.min_filter =
                writer_filter(
                    source.texture_min_filters[index], false);
            sampler.mag_filter =
                writer_filter(
                    source.texture_mag_filters[index], true);
            cgltf_texture &texture = model.textures[index];
            texture.image = &image;
            texture.sampler = &sampler;
            cgltf_texture_view view{};
            view.texture = &texture;
            view.texcoord = static_cast<cgltf_int>(
                source.texture_uv_sets[index]);
            view.scale = 1.0F;
            cgltf_material &material =
                model.materials[
                    static_cast<size_t>(
                        source.texture_materials[index])];
            switch (source.texture_semantics[index]) {
                case 0:
                    material.pbr_metallic_roughness
                        .base_color_texture = view;
                    break;
                case 4:
                    material.normal_texture = view;
                    break;
                case 7:
                    material.emissive_texture = view;
                    break;
                case 10:
                    material.pbr_metallic_roughness
                        .metallic_roughness_texture = view;
                    break;
                case 11:
                    material.occlusion_texture = view;
                    break;
                default:
                    throw std::invalid_argument(
                        "glTF writer cannot represent this texture "
                        "semantic");
            }
        }
    }

    size_t child_cursor = 0;
    for (size_t index = 0; index < scene.num_nodes(); ++index) {
        cgltf_node &node = model.nodes[index];
        node.name = model.node_names[index].empty()
                        ? nullptr
                        : model.node_names[index].data();
        const int64_t mesh = scene.node_meshes[index];
        if (mesh >= 0)
            node.mesh =
                &model.meshes[static_cast<size_t>(mesh)];
        node.children_count =
            static_cast<cgltf_size>(
                scene.node_child_offsets[index + 1] -
                scene.node_child_offsets[index]);
        node.children =
            node.children_count == 0
                ? nullptr
                : model.child_pointers.data() + child_cursor;
        for (size_t local = 0;
             local < static_cast<size_t>(node.children_count);
             ++local, ++child_cursor)
            model.child_pointers[child_cursor] =
                &model.nodes[
                    static_cast<size_t>(
                        scene.node_children[child_cursor])];
        node.has_matrix = true;
        const double *row_major =
            scene.node_local_transforms.data() + index * 16;
        for (size_t row = 0; row < 4; ++row)
            for (size_t column = 0; column < 4; ++column)
                {
                    const double value =
                        row_major[row * 4 + column];
                    const float encoded =
                        static_cast<float>(value);
                    if (static_cast<double>(encoded) != value)
                        throw std::invalid_argument(
                            "glTF node transforms must be exactly "
                            "representable as float32");
                    node.matrix[column * 4 + row] = encoded;
                }
    }
    size_t root_cursor = 0;
    for (size_t index = 0; index < scene.num_scenes(); ++index) {
        cgltf_scene &target = model.scenes[index];
        target.name = model.scene_names[index].empty()
                          ? nullptr
                          : model.scene_names[index].data();
        target.nodes_count =
            static_cast<cgltf_size>(
                scene.scene_root_offsets[index + 1] -
                scene.scene_root_offsets[index]);
        target.nodes =
            target.nodes_count == 0
                ? nullptr
                : model.root_pointers.data() + root_cursor;
        for (size_t local = 0;
             local < static_cast<size_t>(target.nodes_count);
             ++local, ++root_cursor)
            model.root_pointers[root_cursor] =
                &model.nodes[
                    static_cast<size_t>(
                        scene.scene_roots[root_cursor])];
    }

    if (!model.buffers.empty()) {
        model.buffers[0].size = model.binary.size();
        model.buffers[0].data = model.binary.data();
        model.buffers[0].data_free_method =
            cgltf_data_free_method_none;
        model.buffers[0].uri =
            binary_container
                ? nullptr
                : model.buffer_uri.data();
    }
    model.data.file_type =
        binary_container
            ? cgltf_file_type_glb
            : cgltf_file_type_gltf;
    model.data.asset.version =
        model.asset_version.data();
    model.data.asset.generator =
        model.asset_generator.data();
    model.data.buffers = model.buffers.data();
    model.data.buffers_count = model.buffers.size();
    model.data.buffer_views = model.views.data();
    model.data.buffer_views_count = model.views.size();
    model.data.accessors = model.accessors.data();
    model.data.accessors_count = model.accessors.size();
    model.data.meshes = model.meshes.data();
    model.data.meshes_count = model.meshes.size();
    model.data.materials = model.materials.data();
    model.data.materials_count = model.materials.size();
    model.data.images = model.images.data();
    model.data.images_count = model.images.size();
    model.data.textures = model.textures.data();
    model.data.textures_count = model.textures.size();
    model.data.samplers = model.samplers.data();
    model.data.samplers_count = model.samplers.size();
    model.data.nodes = model.nodes.data();
    model.data.nodes_count = model.nodes.size();
    model.data.scenes = model.scenes.data();
    model.data.scenes_count = model.scenes.size();
    if (scene.default_scene >= 0)
    model.data.scene =
            &model.scenes[
                static_cast<size_t>(scene.default_scene)];
}

class CNumericLocaleGuard {
public:
    CNumericLocaleGuard() {
#ifdef _WIN32
        const char *current = setlocale(LC_NUMERIC, nullptr);
        if (current == nullptr)
            throw std::runtime_error(
                "glTF writer cannot query the numeric locale");
        previous_locale_ = current;
        previous_mode_ =
            _configthreadlocale(_ENABLE_PER_THREAD_LOCALE);
        if (previous_mode_ == -1)
            throw std::runtime_error(
                "glTF writer cannot enable a thread-local locale");
        if (setlocale(LC_NUMERIC, "C") == nullptr) {
            (void)_configthreadlocale(previous_mode_);
            previous_mode_ = -1;
            throw std::runtime_error(
                "glTF writer cannot activate the C numeric locale");
        }
#else
        locale_ = newlocale(
            LC_NUMERIC_MASK, "C", nullptr);
        if (locale_ == nullptr)
            throw std::runtime_error(
                "glTF writer cannot create the C numeric locale");
        previous_locale_ = uselocale(locale_);
        if (previous_locale_ == static_cast<locale_t>(0)) {
            freelocale(locale_);
            locale_ = static_cast<locale_t>(0);
            throw std::runtime_error(
                "glTF writer cannot activate the C numeric locale");
        }
#endif
    }

    CNumericLocaleGuard(const CNumericLocaleGuard &) = delete;
    CNumericLocaleGuard &operator=(
        const CNumericLocaleGuard &) = delete;

    ~CNumericLocaleGuard() {
#ifdef _WIN32
        if (previous_mode_ != -1) {
            (void)setlocale(
                LC_NUMERIC, previous_locale_.c_str());
            (void)_configthreadlocale(previous_mode_);
        }
#else
        if (previous_locale_ != static_cast<locale_t>(0))
            (void)uselocale(previous_locale_);
        if (locale_ != static_cast<locale_t>(0))
            freelocale(locale_);
#endif
    }

private:
#ifdef _WIN32
    int previous_mode_ = -1;
    std::string previous_locale_;
#else
    locale_t locale_ = static_cast<locale_t>(0);
    locale_t previous_locale_ = static_cast<locale_t>(0);
#endif
};

EncodedScene encode_scene(
    const MeshScene &scene, const std::string &buffer_uri,
    bool binary_container) {
    if (!binary_container) {
        if (buffer_uri.empty())
            throw std::invalid_argument(
                "glTF external buffer URI must be non-empty");
        validate_uri(buffer_uri.c_str(), "glTF external buffer URI");
        if (buffer_uri.rfind("data:", 0) == 0)
            throw std::invalid_argument(
                "glTF writer buffer URI must name the sibling binary file");
    }
    WriterModel model;
    build_writer_model(
        model, scene, buffer_uri, binary_container);
    require_success(
        cgltf_validate(&model.data),
        "writer model validation");
    CNumericLocaleGuard locale_guard;
    const cgltf_size required =
        cgltf_write(
            &model.options, nullptr, 0, &model.data);
    if (required == 0)
        throw std::runtime_error(
            "cgltf writer could not size the JSON document");
    std::string json(static_cast<size_t>(required), '\0');
    const cgltf_size written =
        cgltf_write(
            &model.options, json.data(), required, &model.data);
    if (written != required || json.back() != '\0')
        throw std::runtime_error(
            "cgltf writer returned an inconsistent JSON size");
    json.pop_back();
    return {std::move(json), std::move(model.binary)};
}

std::string make_glb(EncodedScene encoded) {
    constexpr size_t maximum_chunk =
        static_cast<size_t>(
            std::numeric_limits<uint32_t>::max()) - 3;
    if (encoded.json.size() > maximum_chunk ||
        encoded.binary.size() > maximum_chunk)
        throw std::length_error(
            "GLB output exceeds the 4 GiB container limit");
    while (encoded.json.size() % 4 != 0)
        encoded.json.push_back(' ');
    align_four(encoded.binary);
    const uint64_t total =
        12ULL + 8ULL + encoded.json.size() +
        (encoded.binary.empty()
             ? 0ULL
             : 8ULL + encoded.binary.size());
    if (total > std::numeric_limits<uint32_t>::max())
        throw std::length_error(
            "GLB output exceeds the 4 GiB container limit");
    std::vector<uint8_t> out;
    out.reserve(static_cast<size_t>(total));
    append_little(out, kGlbMagic);
    append_little(out, uint32_t{2});
    append_little(out, static_cast<uint32_t>(total));
    append_little(
        out, static_cast<uint32_t>(encoded.json.size()));
    append_little(out, kGlbJsonChunk);
    out.insert(
        out.end(), encoded.json.begin(), encoded.json.end());
    if (!encoded.binary.empty()) {
        append_little(
            out, static_cast<uint32_t>(encoded.binary.size()));
        append_little(out, kGlbBinChunk);
        out.insert(
            out.end(), encoded.binary.begin(),
            encoded.binary.end());
    }
    return std::string(
        reinterpret_cast<const char *>(out.data()), out.size());
}

nb::tuple write_gltf(
    const MeshScene &scene, const std::string &buffer_uri) {
    EncodedScene encoded;
    {
        nb::gil_scoped_release release;
        encoded = encode_scene(scene, buffer_uri, false);
    }
    return nb::make_tuple(
        nb::bytes(encoded.json.data(), encoded.json.size()),
        nb::bytes(
            reinterpret_cast<const char *>(encoded.binary.data()),
            encoded.binary.size()));
}

nb::bytes write_gltf_json(
    const MeshScene &scene, const std::string &buffer_uri) {
    EncodedScene encoded;
    {
        nb::gil_scoped_release release;
        encoded = encode_scene(scene, buffer_uri, false);
    }
    return sio::emit_bytes(
        encoded.json.data(), encoded.json.size());
}

nb::bytes write_gltf_bin(
    const MeshScene &scene, const std::string &buffer_uri) {
    EncodedScene encoded;
    {
        nb::gil_scoped_release release;
        encoded = encode_scene(scene, buffer_uri, false);
    }
    return sio::emit_bytes(
        reinterpret_cast<const char *>(encoded.binary.data()),
        encoded.binary.size());
}

size_t write_file(
    nb::handle path, const char *data, size_t size) {
    sio::FileSinkScope sink(path);
    try {
        if (!sio::emit_file_chunk(data, size))
            throw std::logic_error(
                "glTF direct file writer has no active sink");
        sink.close();
        return sink.native_write_calls();
    } catch (...) {
        sink.close_noexcept();
        throw;
    }
}

nb::tuple write_gltf_to_files(
    const MeshScene &scene, const std::string &buffer_uri,
    nb::handle json_path, nb::handle binary_path) {
    EncodedScene encoded;
    {
        nb::gil_scoped_release release;
        encoded = encode_scene(scene, buffer_uri, false);
    }
    // Publish the payload first. The Python adapter supplies temporary paths
    // and atomically installs both only after this call has completed.
    const size_t binary_calls = write_file(
        binary_path,
        reinterpret_cast<const char *>(encoded.binary.data()),
        encoded.binary.size());
    const size_t json_calls = write_file(
        json_path, encoded.json.data(), encoded.json.size());
    return nb::make_tuple(json_calls, binary_calls);
}

nb::bytes write_glb(const MeshScene &scene) {
    std::string encoded;
    {
        nb::gil_scoped_release release;
        encoded =
            make_glb(encode_scene(scene, "", true));
    }
    return sio::emit_bytes(encoded.data(), encoded.size());
}

}  // namespace

void register_gltf(nb::module_ &module) {
    module.def(
        "gltf_external_buffer_uris",
        [](nb::handle source) {
            return external_buffer_uris(
                source, cgltf_file_type_gltf);
        },
        "data"_a);
    module.def(
        "read_gltf",
        [](nb::handle source, nb::dict resources) {
            return read_document(
                source, std::move(resources),
                cgltf_file_type_gltf, {});
        },
        "data"_a, "resources"_a = nb::dict());
    module.def(
        "read_glb",
        [](nb::handle source) {
            return read_document(
                source, nb::dict(),
                cgltf_file_type_glb, {});
        },
        "data"_a);
    module.def(
        "read_gltf_mesh",
        [](nb::handle source, nb::dict resources, size_t index) {
            return read_document(
                source, std::move(resources),
                cgltf_file_type_gltf,
                {Selection::Kind::Mesh, index});
        },
        "data"_a, "resources"_a, "index"_a);
    module.def(
        "read_glb_mesh",
        [](nb::handle source, size_t index) {
            return read_document(
                source, nb::dict(),
                cgltf_file_type_glb,
                {Selection::Kind::Mesh, index});
        },
        "data"_a, "index"_a);
    module.def(
        "read_gltf_primitive",
        [](nb::handle source, nb::dict resources, size_t index) {
            return read_document(
                source, std::move(resources),
                cgltf_file_type_gltf,
                {Selection::Kind::Primitive, index});
        },
        "data"_a, "resources"_a, "index"_a);
    module.def(
        "read_glb_primitive",
        [](nb::handle source, size_t index) {
            return read_document(
                source, nb::dict(),
                cgltf_file_type_glb,
                {Selection::Kind::Primitive, index});
        },
        "data"_a, "index"_a);
    module.def(
        "inspect_gltf",
        [](nb::handle source) {
            return inspect_document(
                source, cgltf_file_type_gltf);
        },
        "data"_a);
    module.def(
        "inspect_glb",
        [](nb::handle source) {
            return inspect_document(
                source, cgltf_file_type_glb);
        },
        "data"_a);
    module.def(
        "write_gltf", &write_gltf,
        "scene"_a, "buffer_uri"_a = "scene.bin");
    module.def(
        "_write_gltf_json", &write_gltf_json,
        "scene"_a, "buffer_uri"_a);
    module.def(
        "_write_gltf_bin", &write_gltf_bin,
        "scene"_a, "buffer_uri"_a);
    module.def(
        "_write_gltf_to_files", &write_gltf_to_files,
        "scene"_a, "buffer_uri"_a, "json_path"_a, "binary_path"_a);
    module.def("write_glb", &write_glb, "scene"_a);
}
