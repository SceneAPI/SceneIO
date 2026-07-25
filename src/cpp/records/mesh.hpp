// records/mesh.hpp -- polygon-preserving mesh record.
//
// Faces use CSR-style offsets plus one contiguous index buffer. Attributes are
// stored in their actual domains: vertex rows have N entries and corner rows
// have C entries, where C is face_offsets.back(). Primitive offsets partition
// the F faces into non-empty contiguous ranges and carry one material index per
// range. This representation never requires implicit triangulation or merging
// independent corner attributes into vertex attributes.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "io/common.hpp"
#include "records/material_set.hpp"

struct Mesh {
    size_t n = 0;
    size_t f = 0;
    size_t c = 0;

    std::vector<float> positions;       // n*3, required
    std::vector<uint64_t> face_offsets; // f+1, starts at zero, ends at c
    std::vector<uint64_t> face_indices; // c, each < n

    std::vector<float> vertex_normals;  // n*3 or empty
    std::vector<float> corner_normals;  // c*3 or empty
    std::vector<float> vertex_uvs;      // n*2 or empty
    std::vector<float> corner_uvs;      // c*2 or empty
    std::vector<uint8_t> vertex_colors; // n*4 RGBA or empty
    std::vector<uint8_t> corner_colors; // c*4 RGBA or empty
    std::vector<uint32_t> face_smoothing_groups; // f or empty; 0 = off

    // Primitive ranges partition faces. Empty meshes have {0} and no material
    // rows. Non-empty meshes always have at least one primitive. -1 denotes no
    // material; nonnegative values index a future/attached MaterialSet.
    std::vector<uint64_t> primitive_offsets; // p+1, face-domain offsets
    std::vector<int32_t> primitive_materials; // p
    // Optional UTF-8 object/group names in the primitive domain. Empty string
    // entries are meaningful and use repeated offsets.
    std::vector<uint64_t> primitive_object_offsets; // p+1 or empty
    std::vector<uint8_t> primitive_object_utf8;
    std::vector<uint64_t> primitive_group_offsets; // p+1 or empty
    std::vector<uint8_t> primitive_group_utf8;

    // Material factors and texture references are attached when the source
    // format can carry them. Detached nonnegative primitive indices remain
    // valid for formats such as PLY that preserve ids but no material table.
    bool has_material_set = false;
    MaterialSet materials;

    // Recorded conventions. A codec that cannot represent a non-default value
    // must reject it rather than silently converting or dropping it.
    std::string coordinate_frame = "unknown";
    double scale_to_meters = 1.0;
    double local_transform[16] = {
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };

    size_t num_vertices() const { return n; }
    size_t num_faces() const { return f; }
    size_t num_corners() const { return c; }
    size_t num_primitives() const { return primitive_materials.size(); }

    bool has_vertex_normals() const { return !vertex_normals.empty(); }
    bool has_corner_normals() const { return !corner_normals.empty(); }
    bool has_vertex_uvs() const { return !vertex_uvs.empty(); }
    bool has_corner_uvs() const { return !corner_uvs.empty(); }
    bool has_vertex_colors() const { return !vertex_colors.empty(); }
    bool has_corner_colors() const { return !corner_colors.empty(); }
    bool has_smoothing_groups() const {
        return !face_smoothing_groups.empty();
    }
    bool has_object_names() const {
        return !primitive_object_offsets.empty();
    }
    bool has_group_names() const {
        return !primitive_group_offsets.empty();
    }
};

inline bool mesh_valid_frame(const std::string &value) {
    return value == "unknown" || value == "opencv" ||
           value == "opengl" || value == "enu" || value == "ned";
}

void validate_mesh(const Mesh &mesh, const char *context = "mesh");
void assign_mesh_primitive_names(
    Mesh &mesh,
    const std::vector<std::string> &object_names,
    const std::vector<std::string> &group_names);
std::vector<std::string> mesh_primitive_object_names(
    const Mesh &mesh);
std::vector<std::string> mesh_primitive_group_names(
    const Mesh &mesh);
