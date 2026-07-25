// records/mesh_scene.cpp -- MeshScene validation, construction, and bindings.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <string>
#include <vector>

#include "records/mesh_scene.hpp"

using namespace nb::literals;

namespace {

using f64_array =
    nb::ndarray<const double, nb::c_contig, nb::device::cpu>;
using i64_array =
    nb::ndarray<const int64_t, nb::c_contig, nb::device::cpu>;
using u64_array =
    nb::ndarray<const uint64_t, nb::c_contig, nb::device::cpu>;

constexpr size_t kNameLimit = 1024 * 1024;

template <typename T>
void assign_nonempty(
    std::vector<T> &target, const T *data, size_t count) {
    if (count != 0) target.assign(data, data + count);
}

template <typename T>
nb::ndarray<nb::numpy, const T> const_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static const T sentinel{};
    const T *data = values.empty() ? &sentinel : values.data();
    return nb::ndarray<nb::numpy, const T>(
        data, shape.size(), shape.data());
}

void validate_name(const std::string &value, const char *context) {
    if (value.size() > kNameLimit)
        throw std::invalid_argument(
            std::string(context) + " exceeds 1 MiB");
    if (value.find('\0') != std::string::npos)
        throw std::invalid_argument(
            std::string(context) + " contains embedded NUL");
    if (!sio::valid_utf8(value))
        throw std::invalid_argument(
            std::string(context) + " must be valid UTF-8");
}

void encode_names(
    const std::vector<std::string> &values,
    std::vector<uint64_t> &offsets,
    std::vector<uint8_t> &utf8,
    const char *context) {
    offsets.clear();
    utf8.clear();
    if (values.size() == std::numeric_limits<size_t>::max())
        throw std::length_error(
            std::string(context) + " table has too many rows");
    offsets.reserve(values.size() + 1);
    offsets.push_back(0);
    for (const std::string &value : values) {
        validate_name(value, context);
        if (value.size() >
            std::numeric_limits<size_t>::max() - utf8.size())
            throw std::length_error(
                std::string(context) + " table is too large");
        utf8.insert(utf8.end(), value.begin(), value.end());
        offsets.push_back(static_cast<uint64_t>(utf8.size()));
    }
}

std::vector<std::string> decode_names(
    const std::vector<uint64_t> &offsets,
    const std::vector<uint8_t> &utf8,
    const char *context) {
    if (offsets.empty() || offsets.front() != 0 ||
        offsets.back() != utf8.size())
        throw std::invalid_argument(
            std::string(context) + " has malformed extents");
    std::vector<std::string> result;
    result.reserve(offsets.size() - 1);
    const char *data = utf8.empty()
                           ? ""
                           : reinterpret_cast<const char *>(utf8.data());
    for (size_t row = 0; row + 1 < offsets.size(); ++row) {
        const uint64_t begin = offsets[row];
        const uint64_t end = offsets[row + 1];
        if (end < begin || end > utf8.size())
            throw std::invalid_argument(
                std::string(context) + " has malformed offsets");
        result.emplace_back(
            data + static_cast<size_t>(begin),
            static_cast<size_t>(end - begin));
    }
    return result;
}

bool identity_transform(const double *values) {
    for (size_t row = 0; row < 4; ++row)
        for (size_t column = 0; column < 4; ++column) {
            const double expected = row == column ? 1.0 : 0.0;
            if (values[row * 4 + column] != expected) return false;
        }
    return true;
}

void require_offsets(
    const std::vector<uint64_t> &offsets,
    size_t rows, size_t values,
    const std::string &prefix, const char *name,
    bool require_nonempty_rows) {
    if (offsets.empty() || offsets.size() != rows + 1 ||
        offsets.front() != 0 ||
        offsets.back() != values)
        throw std::invalid_argument(
            prefix + name + " must contain row+1 offsets spanning values");
    for (size_t row = 0; row < rows; ++row) {
        if (offsets[row + 1] < offsets[row] ||
            (require_nonempty_rows &&
             offsets[row + 1] == offsets[row]))
            throw std::invalid_argument(
                prefix + name +
                (require_nonempty_rows
                     ? " rows must be non-empty and monotonic"
                     : " must be monotonic"));
    }
}

MeshScene make_mesh_scene(
    std::vector<Mesh> primitives,
    u64_array mesh_primitive_offsets,
    const std::vector<std::string> &mesh_names,
    std::optional<i64_array> node_meshes,
    std::optional<u64_array> node_child_offsets,
    std::optional<u64_array> node_children,
    std::optional<f64_array> node_local_transforms,
    const std::vector<std::string> &node_names,
    std::optional<u64_array> scene_root_offsets,
    std::optional<u64_array> scene_roots,
    const std::vector<std::string> &scene_names,
    nb::object default_scene,
    std::optional<MaterialSet> materials) {
    if (mesh_primitive_offsets.ndim() != 1 ||
        mesh_primitive_offsets.shape(0) == 0)
        throw std::invalid_argument(
            "mesh scene: mesh_primitive_offsets must be (M+1,) uint64");
    const size_t mesh_count = mesh_primitive_offsets.shape(0) - 1;
    if (!mesh_names.empty() && mesh_names.size() != mesh_count)
        throw std::invalid_argument(
            "mesh scene: mesh_names must have one entry per mesh");

    size_t node_count = node_names.size();
    if (node_meshes) {
        if (node_meshes->ndim() != 1)
            throw std::invalid_argument(
                "mesh scene: node_meshes must be (N,) int64");
        node_count = node_meshes->shape(0);
    }
    if (node_count == std::numeric_limits<size_t>::max() ||
        node_count > std::numeric_limits<size_t>::max() / 16 ||
        node_count >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()))
        throw std::length_error(
            "mesh scene: node count exceeds index capacity");
    if (!node_names.empty() && node_names.size() != node_count)
        throw std::invalid_argument(
            "mesh scene: node_names must have one entry per node");
    if (node_count != 0) {
        if (!node_child_offsets || !node_children ||
            !node_local_transforms)
            throw std::invalid_argument(
                "mesh scene: nodes require child offsets, children, "
                "and local transforms");
        if (node_child_offsets->ndim() != 1 ||
            node_child_offsets->shape(0) != node_count + 1 ||
            node_children->ndim() != 1 ||
            node_local_transforms->ndim() != 3 ||
            node_local_transforms->shape(0) != node_count ||
            node_local_transforms->shape(1) != 4 ||
            node_local_transforms->shape(2) != 4)
            throw std::invalid_argument(
                "mesh scene: node arrays must be offsets (N+1,), "
                "children (E,), and transforms (N,4,4)");
    } else if (
        (node_child_offsets &&
         (node_child_offsets->ndim() != 1 ||
          node_child_offsets->shape(0) != 1)) ||
        (node_children &&
         (node_children->ndim() != 1 ||
          node_children->shape(0) != 0)) ||
        (node_local_transforms &&
         (node_local_transforms->ndim() != 3 ||
          node_local_transforms->shape(0) != 0 ||
          node_local_transforms->shape(1) != 4 ||
          node_local_transforms->shape(2) != 4))) {
        throw std::invalid_argument(
            "mesh scene: empty node arrays have invalid shapes");
    }

    size_t scene_count = scene_names.size();
    if (scene_root_offsets) {
        if (scene_root_offsets->ndim() != 1 ||
            scene_root_offsets->shape(0) == 0)
            throw std::invalid_argument(
                "mesh scene: scene_root_offsets must be (S+1,) uint64");
        scene_count = scene_root_offsets->shape(0) - 1;
    }
    if (scene_count >
        static_cast<size_t>(
            std::numeric_limits<int64_t>::max()))
        throw std::length_error(
            "mesh scene: scene count exceeds index capacity");
    if (!scene_names.empty() && scene_names.size() != scene_count)
        throw std::invalid_argument(
            "mesh scene: scene_names must have one entry per scene");
    if (scene_count != 0 && (!scene_root_offsets || !scene_roots))
        throw std::invalid_argument(
            "mesh scene: scenes require root offsets and roots");
    if (scene_roots && scene_roots->ndim() != 1)
        throw std::invalid_argument(
            "mesh scene: scene_roots must be (R,) uint64");

    MeshScene result;
    result.primitives = std::move(primitives);
    if (materials) {
        result.materials = std::move(*materials);
        result.has_material_set = true;
    }
    assign_nonempty(
        result.mesh_primitive_offsets,
        mesh_primitive_offsets.data(), mesh_count + 1);
    if (node_meshes)
        assign_nonempty(
            result.node_meshes, node_meshes->data(), node_count);
    else
        result.node_meshes.assign(node_count, -1);
    result.node_child_offsets.assign(1, 0);
    if (node_child_offsets)
        assign_nonempty(
            result.node_child_offsets,
            node_child_offsets->data(), node_count + 1);
    if (node_children)
        assign_nonempty(
            result.node_children, node_children->data(),
            node_children->shape(0));
    if (node_local_transforms)
        assign_nonempty(
            result.node_local_transforms,
            node_local_transforms->data(), node_count * 16);
    else {
        result.node_local_transforms.resize(node_count * 16, 0.0);
        for (size_t node = 0; node < node_count; ++node)
            for (size_t axis = 0; axis < 4; ++axis)
                result.node_local_transforms[node * 16 + axis * 4 + axis] =
                    1.0;
    }
    result.scene_root_offsets.assign(1, 0);
    if (scene_root_offsets)
        assign_nonempty(
            result.scene_root_offsets,
            scene_root_offsets->data(), scene_count + 1);
    if (scene_roots)
        assign_nonempty(
            result.scene_roots, scene_roots->data(),
            scene_roots->shape(0));
    result.default_scene = default_scene.is_none()
                               ? -1
                               : nb::cast<int64_t>(default_scene);
    assign_mesh_scene_names(
        result,
        mesh_names.empty()
            ? std::vector<std::string>(mesh_count)
            : mesh_names,
        node_names.empty()
            ? std::vector<std::string>(node_count)
            : node_names,
        scene_names.empty()
            ? std::vector<std::string>(scene_count)
            : scene_names);
    {
        nb::gil_scoped_release release;
        validate_mesh_scene(result);
    }
    return result;
}

}  // namespace

std::vector<std::string> mesh_scene_mesh_names(
    const MeshScene &scene) {
    return decode_names(
        scene.mesh_name_offsets, scene.mesh_name_utf8,
        "mesh scene: mesh names");
}

std::vector<std::string> mesh_scene_node_names(
    const MeshScene &scene) {
    return decode_names(
        scene.node_name_offsets, scene.node_name_utf8,
        "mesh scene: node names");
}

std::vector<std::string> mesh_scene_scene_names(
    const MeshScene &scene) {
    return decode_names(
        scene.scene_name_offsets, scene.scene_name_utf8,
        "mesh scene: scene names");
}

void assign_mesh_scene_names(
    MeshScene &scene,
    const std::vector<std::string> &mesh_names,
    const std::vector<std::string> &node_names,
    const std::vector<std::string> &scene_names) {
    encode_names(
        mesh_names, scene.mesh_name_offsets,
        scene.mesh_name_utf8, "mesh scene: mesh name");
    encode_names(
        node_names, scene.node_name_offsets,
        scene.node_name_utf8, "mesh scene: node name");
    encode_names(
        scene_names, scene.scene_name_offsets,
        scene.scene_name_utf8, "mesh scene: scene name");
}

void validate_mesh_scene(
    const MeshScene &scene, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    const size_t mesh_count = scene.num_meshes();
    const size_t node_count = scene.num_nodes();
    const size_t scene_count = scene.num_scenes();
    if (node_count > std::numeric_limits<size_t>::max() / 16 ||
        node_count >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()) ||
        mesh_count >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()) ||
        scene_count >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()))
        throw std::length_error(
            prefix + "domain count exceeds index capacity");

    require_offsets(
        scene.mesh_primitive_offsets, mesh_count,
        scene.primitives.size(), prefix,
        "mesh_primitive_offsets", true);
    if (scene.mesh_name_offsets.size() != mesh_count + 1)
        throw std::invalid_argument(
            prefix + "mesh name count disagrees with meshes");
    for (const std::string &name : mesh_scene_mesh_names(scene))
        validate_name(name, (prefix + "mesh name").c_str());

    if (scene.has_material_set)
        validate_material_set(
            scene.materials, (prefix + "materials").c_str());
    else if (
        scene.materials.n != 0 || scene.materials.t != 0 ||
        !scene.materials.name_offsets.empty() ||
        !scene.materials.texture_path_offsets.empty())
        throw std::invalid_argument(
            prefix + "detached material storage must be empty");

    for (size_t primitive = 0;
         primitive < scene.primitives.size(); ++primitive) {
        const Mesh &mesh = scene.primitives[primitive];
        validate_mesh(
            mesh, (prefix + "primitive " +
                   std::to_string(primitive)).c_str());
        if (mesh.has_material_set)
            throw std::invalid_argument(
                prefix + "primitive meshes must use scene-shared materials");
        if (mesh.coordinate_frame != "opengl" ||
            mesh.scale_to_meters != 1.0 ||
            !identity_transform(mesh.local_transform))
            throw std::invalid_argument(
                prefix + "primitive meshes must be canonical glTF "
                "right-handed Y-up geometry");
        if (mesh.f == 0 ||
            mesh.f > std::numeric_limits<size_t>::max() / 3 ||
            mesh.c != mesh.f * 3)
            throw std::invalid_argument(
                prefix + "primitive meshes must contain triangles");
        if (mesh.primitive_offsets.size() != 2 ||
            mesh.primitive_offsets[0] != 0 ||
            mesh.primitive_offsets[1] != mesh.f ||
            mesh.primitive_materials.size() != 1)
            throw std::invalid_argument(
                prefix + "each primitive mesh must contain one face range");
        const int32_t material = mesh.primitive_materials[0];
        if (material < -1 ||
            (material >= 0 &&
             (!scene.has_material_set ||
              static_cast<size_t>(material) >= scene.materials.n)))
            throw std::invalid_argument(
                prefix + "primitive material index is out of range");
    }

    require_offsets(
        scene.node_child_offsets, node_count,
        scene.node_children.size(), prefix,
        "node_child_offsets", false);
    if (scene.node_local_transforms.size() != node_count * 16 ||
        scene.node_name_offsets.size() != node_count + 1)
        throw std::invalid_argument(
            prefix + "node-domain field lengths disagree");
    for (const std::string &name : mesh_scene_node_names(scene))
        validate_name(name, (prefix + "node name").c_str());
    std::vector<int64_t> parents(node_count, -1);
    for (size_t node = 0; node < node_count; ++node) {
        const int64_t mesh = scene.node_meshes[node];
        if (mesh < -1 ||
            (mesh >= 0 &&
             static_cast<size_t>(mesh) >= mesh_count))
            throw std::invalid_argument(
                prefix + "node mesh index is out of range");
        for (size_t element = 0; element < 16; ++element)
            if (!std::isfinite(
                    scene.node_local_transforms[node * 16 + element]))
                throw std::invalid_argument(
                    prefix + "node transforms must be finite");
        for (uint64_t child_index =
                 scene.node_child_offsets[node];
             child_index < scene.node_child_offsets[node + 1];
             ++child_index) {
            const uint64_t child =
                scene.node_children[
                    static_cast<size_t>(child_index)];
            if (child >= node_count || child == node)
                throw std::invalid_argument(
                    prefix + "node child index is invalid");
            if (parents[static_cast<size_t>(child)] != -1)
                throw std::invalid_argument(
                    prefix + "a node cannot have multiple parents");
            parents[static_cast<size_t>(child)] =
                static_cast<int64_t>(node);
        }
    }
    // Single-parent validation above lets a root traversal detect every cycle
    // without recursive native calls. This remains safe for very deep scene
    // hierarchies that would otherwise exhaust the process stack.
    std::vector<size_t> pending;
    pending.reserve(node_count);
    for (size_t node = 0; node < node_count; ++node)
        if (parents[node] == -1) pending.push_back(node);
    size_t visited = 0;
    while (!pending.empty()) {
        const size_t node = pending.back();
        pending.pop_back();
        ++visited;
        for (uint64_t child_index = scene.node_child_offsets[node];
             child_index < scene.node_child_offsets[node + 1];
             ++child_index)
            pending.push_back(static_cast<size_t>(
                scene.node_children[
                    static_cast<size_t>(child_index)]));
    }
    if (visited != node_count)
        throw std::invalid_argument(
            prefix + "node graph must be acyclic");

    require_offsets(
        scene.scene_root_offsets, scene_count,
        scene.scene_roots.size(), prefix,
        "scene_root_offsets", false);
    if (scene.scene_name_offsets.size() != scene_count + 1)
        throw std::invalid_argument(
            prefix + "scene name count disagrees with scenes");
    for (const std::string &name : mesh_scene_scene_names(scene))
        validate_name(name, (prefix + "scene name").c_str());
    for (uint64_t root : scene.scene_roots) {
        if (root >= node_count)
            throw std::invalid_argument(
                prefix + "scene root index is out of range");
        if (parents[static_cast<size_t>(root)] != -1)
            throw std::invalid_argument(
                prefix + "scene roots cannot have parents");
    }
    if (scene.default_scene < -1 ||
        (scene.default_scene >= 0 &&
         static_cast<size_t>(scene.default_scene) >= scene_count))
        throw std::invalid_argument(
            prefix + "default scene index is out of range");
}

void register_mesh_scene(nb::module_ &module) {
    const auto reference_internal = nb::rv_policy::reference_internal;
    nb::class_<MeshScene>(module, "MeshScene")
        .def_prop_ro(
            "num_primitives",
            [](const MeshScene &scene) {
                return scene.num_primitives();
            })
        .def_prop_ro(
            "num_meshes",
            [](const MeshScene &scene) {
                return scene.num_meshes();
            })
        .def_prop_ro(
            "num_nodes",
            [](const MeshScene &scene) {
                return scene.num_nodes();
            })
        .def_prop_ro(
            "num_scenes",
            [](const MeshScene &scene) {
                return scene.num_scenes();
            })
        .def(
            "primitive_at",
            [](MeshScene &scene, size_t index) -> Mesh & {
                if (index >= scene.primitives.size())
                    throw nb::index_error();
                return scene.primitives[index];
            },
            reference_internal)
        .def_prop_ro(
            "mesh_primitive_offsets",
            [](const MeshScene &scene) {
                return const_view(
                    scene.mesh_primitive_offsets,
                    {scene.mesh_primitive_offsets.size()});
            },
            reference_internal)
        .def_prop_ro("mesh_names", &mesh_scene_mesh_names)
        .def_prop_ro(
            "materials",
            [](MeshScene &scene) -> MaterialSet & {
                return scene.materials;
            },
            reference_internal)
        .def_prop_ro(
            "has_materials",
            [](const MeshScene &scene) {
                return scene.has_material_set;
            })
        .def_prop_ro(
            "node_meshes",
            [](const MeshScene &scene) {
                return const_view(
                    scene.node_meshes, {scene.num_nodes()});
            },
            reference_internal)
        .def_prop_ro(
            "node_child_offsets",
            [](const MeshScene &scene) {
                return const_view(
                    scene.node_child_offsets,
                    {scene.node_child_offsets.size()});
            },
            reference_internal)
        .def_prop_ro(
            "node_children",
            [](const MeshScene &scene) {
                return const_view(
                    scene.node_children,
                    {scene.node_children.size()});
            },
            reference_internal)
        .def_prop_ro(
            "node_local_transforms",
            [](const MeshScene &scene) {
                return const_view(
                    scene.node_local_transforms,
                    {scene.num_nodes(), 4, 4});
            },
            reference_internal)
        .def_prop_ro("node_names", &mesh_scene_node_names)
        .def_prop_ro(
            "scene_root_offsets",
            [](const MeshScene &scene) {
                return const_view(
                    scene.scene_root_offsets,
                    {scene.scene_root_offsets.size()});
            },
            reference_internal)
        .def_prop_ro(
            "scene_roots",
            [](const MeshScene &scene) {
                return const_view(
                    scene.scene_roots,
                    {scene.scene_roots.size()});
            },
            reference_internal)
        .def_prop_ro("scene_names", &mesh_scene_scene_names)
        .def_prop_ro(
            "default_scene",
            [](const MeshScene &scene) -> nb::object {
                return scene.default_scene < 0
                           ? nb::none()
                           : nb::cast(scene.default_scene);
            })
        .def(
            "__repr__",
            [](const MeshScene &scene) {
                return "<MeshScene meshes=" +
                       std::to_string(scene.num_meshes()) +
                       " primitives=" +
                       std::to_string(scene.num_primitives()) +
                       " nodes=" +
                       std::to_string(scene.num_nodes()) +
                       " scenes=" +
                       std::to_string(scene.num_scenes()) + ">";
            });

    module.def(
        "mesh_scene", &make_mesh_scene,
        "primitives"_a, "mesh_primitive_offsets"_a,
        "mesh_names"_a = std::vector<std::string>{},
        "node_meshes"_a = nb::none(),
        "node_child_offsets"_a = nb::none(),
        "node_children"_a = nb::none(),
        "node_local_transforms"_a = nb::none(),
        "node_names"_a = std::vector<std::string>{},
        "scene_root_offsets"_a = nb::none(),
        "scene_roots"_a = nb::none(),
        "scene_names"_a = std::vector<std::string>{},
        "default_scene"_a = nb::none(),
        "materials"_a = nb::none(),
        "Build a hierarchy-preserving mesh scene from canonical records.");
}
