// records/mesh_scene.hpp -- glTF-style mesh scene graph without flattening.
//
// Each entry in `primitives` is one canonical Mesh for one source primitive.
// `mesh_primitive_offsets` groups those entries into source mesh objects.
// Nodes retain local transforms and child topology; scenes retain their root
// sets. This is intentionally smaller than a general animation scene: codecs
// must reject cameras, skins, morph targets, animation, and extensions that
// cannot be represented here.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "records/material_set.hpp"
#include "records/mesh.hpp"

struct MeshScene {
    std::vector<Mesh> primitives;
    std::vector<uint64_t> mesh_primitive_offsets;  // M+1
    std::vector<uint64_t> mesh_name_offsets;       // M+1
    std::vector<uint8_t> mesh_name_utf8;

    bool has_material_set = false;
    MaterialSet materials;

    std::vector<int64_t> node_meshes;           // N, -1 means no mesh
    std::vector<uint64_t> node_child_offsets;    // N+1
    std::vector<uint64_t> node_children;         // E
    std::vector<double> node_local_transforms;   // N*16, row-major
    std::vector<uint64_t> node_name_offsets;     // N+1
    std::vector<uint8_t> node_name_utf8;

    std::vector<uint64_t> scene_root_offsets;    // S+1
    std::vector<uint64_t> scene_roots;           // R
    std::vector<uint64_t> scene_name_offsets;    // S+1
    std::vector<uint8_t> scene_name_utf8;
    int64_t default_scene = -1;

    size_t num_primitives() const { return primitives.size(); }
    size_t num_meshes() const {
        return mesh_primitive_offsets.empty()
                   ? 0
                   : mesh_primitive_offsets.size() - 1;
    }
    size_t num_nodes() const { return node_meshes.size(); }
    size_t num_scenes() const {
        return scene_root_offsets.empty()
                   ? 0
                   : scene_root_offsets.size() - 1;
    }
};

std::vector<std::string> mesh_scene_mesh_names(
    const MeshScene &scene);
std::vector<std::string> mesh_scene_node_names(
    const MeshScene &scene);
std::vector<std::string> mesh_scene_scene_names(
    const MeshScene &scene);
void assign_mesh_scene_names(
    MeshScene &scene,
    const std::vector<std::string> &mesh_names,
    const std::vector<std::string> &node_names,
    const std::vector<std::string> &scene_names);
void validate_mesh_scene(
    const MeshScene &scene, const char *context = "mesh scene");
