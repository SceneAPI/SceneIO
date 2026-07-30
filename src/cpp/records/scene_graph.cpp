// records/scene_graph.cpp -- validation, construction, and nanobind views.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

#include "records/scene_graph.hpp"

using namespace nb::literals;

namespace {

using f64_array =
    nb::ndarray<const double, nb::c_contig, nb::device::cpu>;
using u8_array =
    nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;
using u64_array =
    nb::ndarray<const uint64_t, nb::c_contig, nb::device::cpu>;

constexpr uint64_t kNoPayload =
    std::numeric_limits<uint64_t>::max();
constexpr size_t kTextLimit = 1024 * 1024;

template <typename T>
void assign_nonempty(
    std::vector<T> &target, const T *data, size_t count) {
    if (count != 0) target.assign(data, data + count);
}

template <typename T>
nb::ndarray<nb::numpy, const T> owned_view(
    nb::handle owner, const std::vector<T> &values,
    std::vector<size_t> shape) {
    static const T sentinel{};
    const T *data = values.empty() ? &sentinel : values.data();
    return sio::view<const T>(owner, data, std::move(shape));
}

void validate_text(
    const std::string &value, const std::string &context,
    bool allow_empty) {
    if (!allow_empty && value.empty())
        throw std::invalid_argument(
            context + " must be non-empty");
    if (value.size() > kTextLimit)
        throw std::invalid_argument(
            context + " exceeds 1 MiB");
    if (value.find('\0') != std::string::npos)
        throw std::invalid_argument(
            context + " contains embedded NUL");
    if (!sio::valid_utf8(value))
        throw std::invalid_argument(
            context + " must be valid UTF-8");
}

uint8_t payload_kind_code(const std::string &value) {
    if (value == "none") return 0;
    if (value == "mesh") return 1;
    if (value == "point_cloud") return 2;
    if (value == "gaussian_cloud") return 3;
    if (value == "camera") return 4;
    if (value == "volume") return 5;
    if (value == "instances") return 6;
    throw std::invalid_argument(
        "scene_graph: payload kinds must be none|mesh|point_cloud|"
        "gaussian_cloud|camera|volume|instances");
}

uint8_t visibility_code(const std::string &value) {
    if (value == "inherited") return 0;
    if (value == "visible") return 1;
    if (value == "invisible") return 2;
    throw std::invalid_argument(
        "scene_graph: visibility values must be "
        "inherited|visible|invisible");
}

uint8_t purpose_code(const std::string &value) {
    if (value == "default") return 0;
    if (value == "render") return 1;
    if (value == "proxy") return 2;
    if (value == "guide") return 3;
    throw std::invalid_argument(
        "scene_graph: purpose values must be "
        "default|render|proxy|guide");
}

std::vector<uint8_t> optional_codes(
    const std::optional<std::vector<std::string>> &source,
    size_t count, uint8_t default_value,
    uint8_t (*convert)(const std::string &),
    const char *name) {
    std::vector<uint8_t> result(count, default_value);
    if (!source) return result;
    if (source->size() != count)
        throw std::invalid_argument(
            std::string("scene_graph: ") + name +
            " must have one value per node");
    for (size_t index = 0; index < count; ++index)
        result[index] = convert((*source)[index]);
    return result;
}

VolumeAsset make_volume_asset(
    const std::string &uri, const std::string &grid_name,
    const std::string &field_name) {
    VolumeAsset result{uri, grid_name, field_name};
    validate_text(result.uri, "volume_asset: uri", false);
    validate_text(
        result.grid_name, "volume_asset: grid_name", false);
    validate_text(
        result.field_name, "volume_asset: field_name", true);
    return result;
}

SceneGraph make_scene_graph(
    const std::vector<std::string> &node_names,
    std::optional<u64_array> node_child_offsets,
    std::optional<u64_array> node_children,
    std::optional<f64_array> node_local_transforms,
    std::optional<std::vector<std::string>> node_payload_kinds,
    std::optional<u64_array> node_payload_indices,
    std::optional<std::vector<std::string>> node_visibility,
    std::optional<std::vector<std::string>> node_purpose,
    std::optional<std::vector<std::string>>
        node_semantic_taxonomies,
    std::optional<std::vector<std::string>>
        node_semantic_labels,
    std::vector<Mesh> meshes,
    std::vector<PointCloud> point_clouds,
    std::vector<GaussianCloud> gaussian_clouds,
    std::optional<CameraRig> cameras,
    std::vector<VolumeAsset> volumes,
    std::vector<InstanceSet> instances,
    std::optional<MaterialSet> materials,
    const std::vector<std::string> &external_asset_uris,
    const std::vector<std::string> &external_asset_kinds,
    const std::string &up_axis,
    double meters_per_unit,
    const std::string &source_representation,
    nb::object default_prim,
    std::optional<double> selected_time,
    std::optional<double> start_time_code,
    std::optional<double> end_time_code,
    double time_codes_per_second) {
    const size_t count = node_names.size();
    if (count == std::numeric_limits<size_t>::max() ||
        count > std::numeric_limits<size_t>::max() / 16 ||
        count >
            static_cast<size_t>(std::numeric_limits<int64_t>::max()))
        throw std::length_error(
            "scene_graph: node count exceeds index capacity");
    if (node_child_offsets &&
        (node_child_offsets->ndim() != 1 ||
         node_child_offsets->shape(0) != count + 1))
        throw std::invalid_argument(
            "scene_graph: node_child_offsets must be (N+1,) uint64");
    if (node_children && node_children->ndim() != 1)
        throw std::invalid_argument(
            "scene_graph: node_children must be (E,) uint64");
    if (node_child_offsets.has_value() !=
        node_children.has_value())
        throw std::invalid_argument(
            "scene_graph: child offsets and values must be provided "
            "together");
    if (node_local_transforms &&
        (node_local_transforms->ndim() != 3 ||
         node_local_transforms->shape(0) != count ||
         node_local_transforms->shape(1) != 4 ||
         node_local_transforms->shape(2) != 4))
        throw std::invalid_argument(
            "scene_graph: node_local_transforms must be "
            "(N,4,4) float64");
    if (node_payload_indices &&
        (node_payload_indices->ndim() != 1 ||
         node_payload_indices->shape(0) != count))
        throw std::invalid_argument(
            "scene_graph: node_payload_indices must be (N,) uint64");
    if (external_asset_uris.size() !=
        external_asset_kinds.size())
        throw std::invalid_argument(
            "scene_graph: external asset URI and kind counts differ");
    if (start_time_code.has_value() !=
        end_time_code.has_value())
        throw std::invalid_argument(
            "scene_graph: start and end time codes must be provided "
            "together");

    SceneGraph result;
    result.n = count;
    result.node_names = node_names;
    result.node_child_offsets.assign(count + 1, 0);
    if (node_child_offsets)
        assign_nonempty(
            result.node_child_offsets,
            node_child_offsets->data(), count + 1);
    if (node_children)
        assign_nonempty(
            result.node_children, node_children->data(),
            node_children->shape(0));
    result.node_parents.assign(count, -1);
    if (!result.node_child_offsets.empty() &&
        result.node_child_offsets.front() == 0 &&
        result.node_child_offsets.back() ==
            result.node_children.size()) {
        bool offsets_valid = true;
        for (size_t row = 0; row < count; ++row)
            offsets_valid =
                offsets_valid &&
                result.node_child_offsets[row] <=
                    result.node_child_offsets[row + 1];
        if (offsets_valid)
            for (size_t parent = 0; parent < count; ++parent)
                for (uint64_t edge =
                         result.node_child_offsets[parent];
                     edge <
                     result.node_child_offsets[parent + 1];
                     ++edge) {
                    const uint64_t child =
                        result.node_children[
                            static_cast<size_t>(edge)];
                    if (child < count &&
                        result.node_parents[
                            static_cast<size_t>(child)] == -1)
                        result.node_parents[
                            static_cast<size_t>(child)] =
                            static_cast<int64_t>(parent);
                }
    }
    result.node_local_transforms.assign(count * 16, 0.0);
    if (node_local_transforms) {
        assign_nonempty(
            result.node_local_transforms,
            node_local_transforms->data(), count * 16);
    } else {
        for (size_t node = 0; node < count; ++node)
            for (size_t axis = 0; axis < 4; ++axis)
                result.node_local_transforms[
                    node * 16 + axis * 4 + axis] = 1.0;
    }
    result.node_payload_kinds = optional_codes(
        node_payload_kinds, count, 0, &payload_kind_code,
        "node_payload_kinds");
    result.node_payload_indices.assign(count, kNoPayload);
    if (node_payload_indices)
        assign_nonempty(
            result.node_payload_indices,
            node_payload_indices->data(), count);
    result.node_visibility = optional_codes(
        node_visibility, count, 0, &visibility_code,
        "node_visibility");
    result.node_purpose = optional_codes(
        node_purpose, count, 0, &purpose_code,
        "node_purpose");
    result.node_semantic_taxonomies =
        node_semantic_taxonomies.value_or(
            std::vector<std::string>(count));
    result.node_semantic_labels =
        node_semantic_labels.value_or(
            std::vector<std::string>(count));

    result.meshes = std::move(meshes);
    result.point_clouds = std::move(point_clouds);
    result.gaussian_clouds = std::move(gaussian_clouds);
    if (cameras) {
        result.cameras = std::move(*cameras);
        result.has_camera_rig = true;
    }
    result.volumes = std::move(volumes);
    result.instances = std::move(instances);
    if (materials) {
        result.materials = std::move(*materials);
        result.has_material_set = true;
    }
    result.external_asset_uris = external_asset_uris;
    result.external_asset_kinds = external_asset_kinds;
    result.up_axis = up_axis;
    result.meters_per_unit = meters_per_unit;
    result.source_representation = source_representation;
    result.default_prim = default_prim.is_none()
                              ? -1
                              : nb::cast<int64_t>(default_prim);
    if (selected_time) {
        result.has_selected_time = true;
        result.selected_time = *selected_time;
    }
    if (start_time_code) {
        result.has_time_range = true;
        result.start_time_code = *start_time_code;
        result.end_time_code = *end_time_code;
    }
    result.time_codes_per_second = time_codes_per_second;
    {
        nb::gil_scoped_release release;
        validate_scene_graph(result);
    }
    return result;
}

template <typename Payload>
Payload &payload_at(
    std::vector<Payload> &values, size_t index) {
    if (index >= values.size()) throw nb::index_error();
    return values[index];
}

}  // namespace

const char *scene_payload_kind_name(uint8_t value) {
    switch (static_cast<ScenePayloadKind>(value)) {
        case ScenePayloadKind::None:
            return "none";
        case ScenePayloadKind::Mesh:
            return "mesh";
        case ScenePayloadKind::PointCloud:
            return "point_cloud";
        case ScenePayloadKind::GaussianCloud:
            return "gaussian_cloud";
        case ScenePayloadKind::Camera:
            return "camera";
        case ScenePayloadKind::Volume:
            return "volume";
        case ScenePayloadKind::Instances:
            return "instances";
    }
    throw std::invalid_argument(
        "scene graph: invalid payload kind code");
}

const char *scene_visibility_name(uint8_t value) {
    switch (value) {
        case 0:
            return "inherited";
        case 1:
            return "visible";
        case 2:
            return "invisible";
        default:
            throw std::invalid_argument(
                "scene graph: invalid visibility code");
    }
}

const char *scene_purpose_name(uint8_t value) {
    switch (value) {
        case 0:
            return "default";
        case 1:
            return "render";
        case 2:
            return "proxy";
        case 3:
            return "guide";
        default:
            throw std::invalid_argument(
                "scene graph: invalid purpose code");
    }
}

void validate_scene_graph(
    const SceneGraph &scene, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    const size_t count = scene.n;
    if (count == std::numeric_limits<size_t>::max() ||
        count > std::numeric_limits<size_t>::max() / 16 ||
        count >
            static_cast<size_t>(std::numeric_limits<int64_t>::max()) ||
        scene.node_names.size() != count ||
        scene.node_parents.size() != count ||
        scene.node_child_offsets.size() != count + 1 ||
        scene.node_local_transforms.size() != count * 16 ||
        scene.node_visibility.size() != count ||
        scene.node_purpose.size() != count ||
        scene.node_payload_kinds.size() != count ||
        scene.node_payload_indices.size() != count ||
        scene.node_semantic_taxonomies.size() != count ||
        scene.node_semantic_labels.size() != count)
        throw std::invalid_argument(
            prefix + "inconsistent SceneGraph node-domain lengths");
    if (scene.node_child_offsets.front() != 0 ||
        scene.node_child_offsets.back() !=
            scene.node_children.size())
        throw std::invalid_argument(
            prefix + "child offsets must span all child indices");
    for (size_t node = 0; node < count; ++node)
        if (scene.node_child_offsets[node] >
            scene.node_child_offsets[node + 1])
            throw std::invalid_argument(
                prefix + "child offsets must be monotonic");

    std::vector<int64_t> expected_parents(count, -1);
    for (size_t parent = 0; parent < count; ++parent)
        for (uint64_t edge =
                 scene.node_child_offsets[parent];
             edge < scene.node_child_offsets[parent + 1];
             ++edge) {
            const uint64_t child =
                scene.node_children[static_cast<size_t>(edge)];
            if (child >= count || child == parent)
                throw std::invalid_argument(
                    prefix + "node child index is invalid");
            if (expected_parents[static_cast<size_t>(child)] != -1)
                throw std::invalid_argument(
                    prefix + "a node cannot have multiple parents");
            expected_parents[static_cast<size_t>(child)] =
                static_cast<int64_t>(parent);
        }
    if (scene.node_parents != expected_parents)
        throw std::invalid_argument(
            prefix + "parent and child topology disagree");

    std::vector<size_t> pending;
    pending.reserve(count);
    for (size_t node = 0; node < count; ++node)
        if (expected_parents[node] == -1) pending.push_back(node);
    size_t visited = 0;
    while (!pending.empty()) {
        const size_t node = pending.back();
        pending.pop_back();
        ++visited;
        for (uint64_t edge = scene.node_child_offsets[node];
             edge < scene.node_child_offsets[node + 1]; ++edge)
            pending.push_back(static_cast<size_t>(
                scene.node_children[static_cast<size_t>(edge)]));
    }
    if (visited != count)
        throw std::invalid_argument(
            prefix + "node graph must be acyclic");

    std::vector<std::unordered_set<std::string>> sibling_names(
        count + 1);
    for (size_t node = 0; node < count; ++node) {
        validate_text(
            scene.node_names[node], prefix + "node name", false);
        const size_t parent_slot =
            expected_parents[node] < 0
                ? count
                : static_cast<size_t>(expected_parents[node]);
        if (!sibling_names[parent_slot]
                 .insert(scene.node_names[node])
                 .second)
            throw std::invalid_argument(
                prefix + "sibling node names must be unique");
        for (size_t element = 0; element < 16; ++element)
            if (!std::isfinite(
                    scene.node_local_transforms[
                        node * 16 + element]))
                throw std::invalid_argument(
                    prefix + "node transforms must be finite");
        scene_visibility_name(scene.node_visibility[node]);
        scene_purpose_name(scene.node_purpose[node]);
        validate_text(
            scene.node_semantic_taxonomies[node],
            prefix + "semantic taxonomy", true);
        validate_text(
            scene.node_semantic_labels[node],
            prefix + "semantic label", true);
        if (scene.node_semantic_taxonomies[node].empty() !=
            scene.node_semantic_labels[node].empty())
            throw std::invalid_argument(
                prefix + "semantic taxonomy and label must be "
                         "present together");

        const uint8_t kind = scene.node_payload_kinds[node];
        const uint64_t index = scene.node_payload_indices[node];
        scene_payload_kind_name(kind);
        size_t bound = 0;
        switch (static_cast<ScenePayloadKind>(kind)) {
            case ScenePayloadKind::None:
                if (index != kNoPayload)
                    throw std::invalid_argument(
                        prefix + "payload-free nodes must use the "
                                 "no-payload index");
                continue;
            case ScenePayloadKind::Mesh:
                bound = scene.meshes.size();
                break;
            case ScenePayloadKind::PointCloud:
                bound = scene.point_clouds.size();
                break;
            case ScenePayloadKind::GaussianCloud:
                bound = scene.gaussian_clouds.size();
                break;
            case ScenePayloadKind::Camera:
                bound =
                    scene.has_camera_rig
                        ? scene.cameras.num_cameras()
                        : 0;
                break;
            case ScenePayloadKind::Volume:
                bound = scene.volumes.size();
                break;
            case ScenePayloadKind::Instances:
                bound = scene.instances.size();
                break;
        }
        if (index >= bound)
            throw std::invalid_argument(
                prefix + "node payload index is out of range");
    }
    if (scene.default_prim < -1 ||
        (scene.default_prim >= 0 &&
         (static_cast<size_t>(scene.default_prim) >= count ||
          expected_parents[
              static_cast<size_t>(scene.default_prim)] != -1)))
        throw std::invalid_argument(
            prefix + "default prim must be a root node index");

    for (size_t index = 0; index < scene.meshes.size(); ++index) {
        validate_mesh(
            scene.meshes[index],
            (prefix + "mesh " + std::to_string(index)).c_str());
        const Mesh &mesh = scene.meshes[index];
        if (mesh.has_material_set)
            throw std::invalid_argument(
                prefix + "payload meshes must use the scene-shared "
                         "material table");
        for (int32_t material : mesh.primitive_materials)
            if (material >= 0 &&
                (!scene.has_material_set ||
                 static_cast<size_t>(material) >=
                     scene.materials.n))
                throw std::invalid_argument(
                    prefix + "mesh material index is out of range");
    }
    for (size_t index = 0;
         index < scene.point_clouds.size(); ++index)
        validate_point_cloud(
            scene.point_clouds[index],
            (prefix + "point cloud " +
             std::to_string(index))
                .c_str());
    for (size_t index = 0;
         index < scene.gaussian_clouds.size(); ++index) {
        const std::string gaussian_context =
            prefix + "Gaussian cloud " + std::to_string(index);
        validate_gaussian_structure(
            scene.gaussian_clouds[index],
            gaussian_context.c_str());
        validate_gaussian_conventions(
            scene.gaussian_clouds[index],
            gaussian_context.c_str());
    }
    if (scene.has_camera_rig) {
        validate_camera_rig(
            scene.cameras, (prefix + "cameras").c_str());
    } else if (scene.cameras.n != 0) {
        throw std::invalid_argument(
            prefix + "detached camera storage must be empty");
    }
    for (size_t index = 0; index < scene.instances.size();
         ++index) {
        validate_instance_set(
            scene.instances[index],
            (prefix + "instances " +
             std::to_string(index))
                .c_str());
        for (uint64_t prototype :
             scene.instances[index].prototype_nodes)
            if (prototype >= count)
                throw std::invalid_argument(
                    prefix + "instance prototype node is out of range");
    }
    for (const VolumeAsset &volume : scene.volumes) {
        validate_text(
            volume.uri, prefix + "volume URI", false);
        validate_text(
            volume.grid_name, prefix + "volume grid name", false);
        validate_text(
            volume.field_name, prefix + "volume field name", true);
    }
    if (scene.has_material_set) {
        validate_material_set(
            scene.materials, (prefix + "materials").c_str());
    } else if (
        scene.materials.n != 0 || scene.materials.t != 0 ||
        !scene.materials.name_offsets.empty() ||
        !scene.materials.texture_path_offsets.empty()) {
        throw std::invalid_argument(
            prefix + "detached material storage must be empty");
    }

    if (scene.external_asset_uris.size() !=
        scene.external_asset_kinds.size())
        throw std::invalid_argument(
            prefix + "external asset URI and kind counts differ");
    static const std::unordered_set<std::string> asset_kinds{
        "texture", "openvdb", "layer", "reference", "payload"};
    std::unordered_set<std::string> texture_assets;
    std::unordered_set<std::string> openvdb_assets;
    for (size_t index = 0;
         index < scene.external_asset_uris.size(); ++index) {
        validate_text(
            scene.external_asset_uris[index],
            prefix + "external asset URI", false);
        if (!asset_kinds.count(
                scene.external_asset_kinds[index]))
            throw std::invalid_argument(
                prefix + "external asset kind must be "
                         "texture|openvdb|layer|reference|payload");
        if (scene.external_asset_kinds[index] == "texture")
            texture_assets.insert(
                scene.external_asset_uris[index]);
        if (scene.external_asset_kinds[index] == "openvdb")
            openvdb_assets.insert(
                scene.external_asset_uris[index]);
    }
    for (const VolumeAsset &volume : scene.volumes)
        if (!openvdb_assets.count(volume.uri))
            throw std::invalid_argument(
                prefix + "volume URI is missing from external "
                         "OpenVDB assets");
    if (scene.has_material_set)
        for (const std::string &path :
             material_texture_paths(scene.materials))
            if (!texture_assets.count(path))
                throw std::invalid_argument(
                    prefix + "material texture is missing from "
                             "external texture assets");
    if (scene.up_axis != "y" && scene.up_axis != "z")
        throw std::invalid_argument(
            prefix + "up_axis must be y or z");
    if (!std::isfinite(scene.meters_per_unit) ||
        scene.meters_per_unit <= 0.0)
        throw std::invalid_argument(
            prefix + "meters_per_unit must be finite and positive");
    if (scene.source_representation != "unknown" &&
        scene.source_representation != "usda" &&
        scene.source_representation != "usdc" &&
        scene.source_representation != "usdz")
        throw std::invalid_argument(
            prefix + "source_representation must be "
                     "unknown|usda|usdc|usdz");
    if (!std::isfinite(scene.time_codes_per_second) ||
        scene.time_codes_per_second <= 0.0)
        throw std::invalid_argument(
            prefix +
            "time_codes_per_second must be finite and positive");
    if (scene.has_selected_time) {
        if (!std::isfinite(scene.selected_time))
            throw std::invalid_argument(
                prefix + "selected time must be finite");
    } else if (scene.selected_time != 0.0) {
        throw std::invalid_argument(
            prefix + "absent selected time must use zero");
    }
    if (scene.has_time_range) {
        if (!std::isfinite(scene.start_time_code) ||
            !std::isfinite(scene.end_time_code) ||
            scene.end_time_code < scene.start_time_code)
            throw std::invalid_argument(
                prefix + "time range must be finite and ordered");
    } else if (
        scene.start_time_code != 0.0 ||
        scene.end_time_code != 0.0) {
        throw std::invalid_argument(
            prefix + "absent time range must use zero bounds");
    }
}

void register_scene_graph(nb::module_ &module) {
    const auto reference_internal =
        nb::rv_policy::reference_internal;

    nb::class_<VolumeAsset>(module, "VolumeAsset")
        .def_ro("uri", &VolumeAsset::uri)
        .def_ro("grid_name", &VolumeAsset::grid_name)
        .def_ro("field_name", &VolumeAsset::field_name)
        .def(
            "__repr__",
            [](const VolumeAsset &value) {
                return "<VolumeAsset uri='" + value.uri +
                       "' grid='" + value.grid_name + "'>";
            });
    module.def(
        "volume_asset", &make_volume_asset,
        "uri"_a, "grid_name"_a, "field_name"_a = "",
        "Build a named external OpenVDB grid reference.");

    nb::class_<SceneGraph>(module, "SceneGraph")
        .def_prop_ro(
            "num_nodes",
            [](const SceneGraph &value) {
                return value.num_nodes();
            })
        .def_prop_ro(
            "num_meshes",
            [](const SceneGraph &value) {
                return value.meshes.size();
            })
        .def_prop_ro(
            "num_point_clouds",
            [](const SceneGraph &value) {
                return value.point_clouds.size();
            })
        .def_prop_ro(
            "num_gaussian_clouds",
            [](const SceneGraph &value) {
                return value.gaussian_clouds.size();
            })
        .def_prop_ro(
            "num_cameras",
            [](const SceneGraph &value) {
                return value.has_camera_rig
                           ? value.cameras.num_cameras()
                           : 0;
            })
        .def_prop_ro(
            "num_volumes",
            [](const SceneGraph &value) {
                return value.volumes.size();
            })
        .def_prop_ro(
            "num_instance_sets",
            [](const SceneGraph &value) {
                return value.instances.size();
            })
        .def_ro("node_names", &SceneGraph::node_names)
        .def_prop_ro(
            "node_parents",
            [](nb::handle_t<SceneGraph> self) {
                const auto &value =
                    nb::cast<const SceneGraph &>(self);
                return owned_view(
                    self, value.node_parents, {value.n});
            })
        .def_prop_ro(
            "node_child_offsets",
            [](nb::handle_t<SceneGraph> self) {
                const auto &value =
                    nb::cast<const SceneGraph &>(self);
                return owned_view(
                    self, value.node_child_offsets,
                    {value.n + 1});
            })
        .def_prop_ro(
            "node_children",
            [](nb::handle_t<SceneGraph> self) {
                const auto &value =
                    nb::cast<const SceneGraph &>(self);
                return owned_view(
                    self, value.node_children,
                    {value.node_children.size()});
            })
        .def_prop_ro(
            "node_local_transforms",
            [](nb::handle_t<SceneGraph> self) {
                const auto &value =
                    nb::cast<const SceneGraph &>(self);
                return owned_view(
                    self, value.node_local_transforms,
                    {value.n, 4, 4});
            })
        .def_prop_ro(
            "node_payload_kind_codes",
            [](nb::handle_t<SceneGraph> self) {
                const auto &value =
                    nb::cast<const SceneGraph &>(self);
                return owned_view(
                    self, value.node_payload_kinds, {value.n});
            })
        .def_prop_ro(
            "node_payload_kinds",
            [](const SceneGraph &value) {
                std::vector<std::string> result;
                result.reserve(value.n);
                for (uint8_t kind :
                     value.node_payload_kinds)
                    result.emplace_back(
                        scene_payload_kind_name(kind));
                return result;
            })
        .def_prop_ro(
            "node_payload_indices",
            [](nb::handle_t<SceneGraph> self) {
                const auto &value =
                    nb::cast<const SceneGraph &>(self);
                return owned_view(
                    self, value.node_payload_indices,
                    {value.n});
            })
        .def_prop_ro(
            "node_visibility_codes",
            [](nb::handle_t<SceneGraph> self) {
                const auto &value =
                    nb::cast<const SceneGraph &>(self);
                return owned_view(
                    self, value.node_visibility, {value.n});
            })
        .def_prop_ro(
            "node_visibility",
            [](const SceneGraph &value) {
                std::vector<std::string> result;
                result.reserve(value.n);
                for (uint8_t visibility :
                     value.node_visibility)
                    result.emplace_back(
                        scene_visibility_name(visibility));
                return result;
            })
        .def_prop_ro(
            "node_purpose_codes",
            [](nb::handle_t<SceneGraph> self) {
                const auto &value =
                    nb::cast<const SceneGraph &>(self);
                return owned_view(
                    self, value.node_purpose, {value.n});
            })
        .def_prop_ro(
            "node_purpose",
            [](const SceneGraph &value) {
                std::vector<std::string> result;
                result.reserve(value.n);
                for (uint8_t purpose : value.node_purpose)
                    result.emplace_back(
                        scene_purpose_name(purpose));
                return result;
            })
        .def_ro(
            "node_semantic_taxonomies",
            &SceneGraph::node_semantic_taxonomies)
        .def_ro(
            "node_semantic_labels",
            &SceneGraph::node_semantic_labels)
        .def(
            "mesh_at",
            [](SceneGraph &value, size_t index) -> Mesh & {
                return payload_at(value.meshes, index);
            },
            reference_internal)
        .def(
            "point_cloud_at",
            [](SceneGraph &value,
               size_t index) -> PointCloud & {
                return payload_at(value.point_clouds, index);
            },
            reference_internal)
        .def(
            "gaussian_cloud_at",
            [](SceneGraph &value,
               size_t index) -> GaussianCloud & {
                return payload_at(
                    value.gaussian_clouds, index);
            },
            reference_internal)
        .def_prop_ro(
            "cameras",
            [](SceneGraph &value) -> CameraRig & {
                return value.cameras;
            },
            reference_internal)
        .def_prop_ro(
            "has_cameras",
            [](const SceneGraph &value) {
                return value.has_camera_rig;
            })
        .def(
            "volume_at",
            [](SceneGraph &value,
               size_t index) -> VolumeAsset & {
                return payload_at(value.volumes, index);
            },
            reference_internal)
        .def(
            "instance_set_at",
            [](SceneGraph &value,
               size_t index) -> InstanceSet & {
                return payload_at(value.instances, index);
            },
            reference_internal)
        .def_prop_ro(
            "materials",
            [](SceneGraph &value) -> MaterialSet & {
                return value.materials;
            },
            reference_internal)
        .def_prop_ro(
            "has_materials",
            [](const SceneGraph &value) {
                return value.has_material_set;
            })
        .def_ro(
            "external_asset_uris",
            &SceneGraph::external_asset_uris)
        .def_ro(
            "external_asset_kinds",
            &SceneGraph::external_asset_kinds)
        .def_ro("up_axis", &SceneGraph::up_axis)
        .def_ro(
            "meters_per_unit",
            &SceneGraph::meters_per_unit)
        .def_ro(
            "source_representation",
            &SceneGraph::source_representation)
        .def_ro("default_prim", &SceneGraph::default_prim)
        .def_prop_ro(
            "selected_time",
            [](const SceneGraph &value) -> nb::object {
                if (!value.has_selected_time)
                    return nb::none();
                return nb::float_(value.selected_time);
            })
        .def_prop_ro(
            "start_time_code",
            [](const SceneGraph &value) -> nb::object {
                if (!value.has_time_range)
                    return nb::none();
                return nb::float_(value.start_time_code);
            })
        .def_prop_ro(
            "end_time_code",
            [](const SceneGraph &value) -> nb::object {
                if (!value.has_time_range)
                    return nb::none();
                return nb::float_(value.end_time_code);
            })
        .def_ro(
            "time_codes_per_second",
            &SceneGraph::time_codes_per_second)
        .def(
            "__repr__",
            [](const SceneGraph &value) {
                return "<SceneGraph nodes=" +
                       std::to_string(value.n) +
                       " meshes=" +
                       std::to_string(value.meshes.size()) +
                       " points=" +
                       std::to_string(
                           value.point_clouds.size()) +
                       " gaussians=" +
                       std::to_string(
                           value.gaussian_clouds.size()) +
                       ">";
            });

    module.def(
        "scene_graph", &make_scene_graph,
        "node_names"_a,
        "node_child_offsets"_a = nb::none(),
        "node_children"_a = nb::none(),
        "node_local_transforms"_a = nb::none(),
        "node_payload_kinds"_a = nb::none(),
        "node_payload_indices"_a = nb::none(),
        "node_visibility"_a = nb::none(),
        "node_purpose"_a = nb::none(),
        "node_semantic_taxonomies"_a = nb::none(),
        "node_semantic_labels"_a = nb::none(),
        "meshes"_a = std::vector<Mesh>{},
        "point_clouds"_a = std::vector<PointCloud>{},
        "gaussian_clouds"_a =
            std::vector<GaussianCloud>{},
        "cameras"_a = nb::none(),
        "volumes"_a = std::vector<VolumeAsset>{},
        "instances"_a = std::vector<InstanceSet>{},
        "materials"_a = nb::none(),
        "external_asset_uris"_a =
            std::vector<std::string>{},
        "external_asset_kinds"_a =
            std::vector<std::string>{},
        "up_axis"_a = "y", "meters_per_unit"_a = 1.0,
        "source_representation"_a = "unknown",
        "default_prim"_a = nb::none(),
        "selected_time"_a = nb::none(),
        "start_time_code"_a = nb::none(),
        "end_time_code"_a = nb::none(),
        "time_codes_per_second"_a = 24.0,
        "Build an owning bounded 3D-CV scene graph with typed payload "
        "references and explicit stage conventions.");
}
