// records/scene_graph.hpp -- bounded, typed 3D-CV scene graph.
//
// This is the single aggregate scene record used by USD- and glTF-family I/O.
// Nodes use CSR children, one local transform, and at most one typed payload
// reference. Mesh payloads may be grouped so a glTF logical mesh can retain
// heterogeneous primitives without flattening. Named scene root sets preserve
// glTF's multi-scene document structure. Numeric tables are contiguous and
// exposed as owner-retaining ndarray views.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "records/camera_rig.hpp"
#include "records/gaussian_cloud.hpp"
#include "records/instance_set.hpp"
#include "records/material_set.hpp"
#include "records/mesh.hpp"
#include "records/point_cloud.hpp"

enum class ScenePayloadKind : uint8_t {
    None = 0,
    Mesh = 1,
    PointCloud = 2,
    GaussianCloud = 3,
    Camera = 4,
    Volume = 5,
    Instances = 6,
};

struct VolumeAsset {
    std::string uri;
    std::string grid_name;
    std::string field_name;
};

struct SceneGraph {
    size_t n = 0;
    std::vector<std::string> node_names;
    std::vector<int64_t> node_parents;          // n, -1 for roots
    std::vector<uint64_t> node_child_offsets;   // n+1
    std::vector<uint64_t> node_children;        // E
    std::vector<double> node_local_transforms;  // n*16, row-major
    std::vector<uint8_t>
        node_resets_transform_stack;                  // n, boolean
    std::vector<uint8_t> node_visibility;       // 0 inherited, 1 visible, 2 invisible
    std::vector<uint8_t> node_purpose;          // 0 default, 1 render, 2 proxy, 3 guide
    std::vector<uint8_t> node_payload_kinds;    // ScenePayloadKind
    std::vector<uint64_t> node_payload_indices; // UINT64_MAX for none
    std::vector<std::string> node_semantic_taxonomies;
    std::vector<std::string> node_semantic_labels;

    std::vector<Mesh> meshes;
    // Logical mesh groups span the mesh payload vector. USD records use the
    // canonical one-payload-per-group default; glTF may group heterogeneous
    // primitive payloads under one node mesh reference.
    std::vector<uint64_t> mesh_primitive_offsets;  // G+1
    std::vector<std::string> mesh_names;            // G
    std::vector<PointCloud> point_clouds;
    std::vector<GaussianCloud> gaussian_clouds;
    bool has_camera_rig = false;
    CameraRig cameras;
    std::vector<VolumeAsset> volumes;
    std::vector<InstanceSet> instances;

    bool has_material_set = false;
    MaterialSet materials;

    std::vector<std::string> external_asset_uris;
    std::vector<std::string> external_asset_kinds;
    // Source locators are reader/writer provenance, not authored USD paths.
    // Direct files use absolute filesystem paths; packaged entries use the
    // bounded SceneIO USDZ locator understood by the Python package adapter.
    std::vector<std::string> external_asset_sources;

    std::string up_axis = "y";
    double meters_per_unit = 1.0;
    std::string source_representation = "unknown";
    int64_t default_prim = -1;

    // Optional named document scenes. These are orthogonal to USD defaultPrim:
    // each row is a root-node set and default_scene selects one row.
    std::vector<uint64_t> scene_root_offsets;  // S+1
    std::vector<uint64_t> scene_roots;         // R
    std::vector<std::string> scene_names;      // S
    int64_t default_scene = -1;

    bool has_selected_time = false;
    double selected_time = 0.0;
    bool has_time_range = false;
    double start_time_code = 0.0;
    double end_time_code = 0.0;
    double time_codes_per_second = 24.0;

    size_t num_nodes() const { return n; }
    size_t num_meshes() const {
        return mesh_primitive_offsets.empty()
                   ? 0
                   : mesh_primitive_offsets.size() - 1;
    }
    size_t num_mesh_primitives() const { return meshes.size(); }
    size_t num_scenes() const {
        return scene_root_offsets.empty()
                   ? 0
                   : scene_root_offsets.size() - 1;
    }
};

const char *scene_payload_kind_name(uint8_t value);
const char *scene_visibility_name(uint8_t value);
const char *scene_purpose_name(uint8_t value);
void validate_scene_graph(
    const SceneGraph &scene,
    const char *context = "scene graph");
