// records/material_set.hpp -- canonical physically based material tables.
//
// Variable-length material names and texture image references are stored as
// UTF-8 offset/value tables. Texture bindings form a separate SoA domain so a
// material can carry any supported semantic without a Python object array.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "io/common.hpp"

struct MaterialSet {
    size_t n = 0;
    size_t t = 0;

    // glTF material names are optional and non-identifying, so empty and
    // duplicate values are valid. Codecs such as MTL that address materials
    // by name must guard those values at write time.
    std::vector<uint64_t> name_offsets;  // n+1
    std::vector<uint8_t> name_utf8;

    std::vector<float> base_colors;      // n*4, linear RGBA
    std::vector<float> emissive_colors;  // n*3, linear RGB
    std::vector<float> metallic;         // n
    std::vector<float> roughness;        // n
    std::vector<uint8_t> alpha_modes;    // 0 opaque, 1 mask, 2 blend
    std::vector<float> alpha_cutoffs;    // n

    std::vector<uint64_t> texture_materials;  // t, each < n
    std::vector<uint8_t> texture_semantics;   // t, see semantic names
    std::vector<uint64_t> texture_path_offsets;  // t+1
    std::vector<uint8_t> texture_path_utf8;
    std::vector<uint32_t> texture_uv_sets;    // t
    std::vector<uint8_t> texture_wrap_s;      // 0 repeat, 1 clamp, 2 mirror
    std::vector<uint8_t> texture_wrap_t;
    std::vector<uint8_t> texture_min_filters;
    std::vector<uint8_t> texture_mag_filters;

    size_t num_materials() const { return n; }
    size_t num_textures() const { return t; }
};

const char *material_alpha_mode_name(uint8_t value);
const char *material_texture_semantic_name(uint8_t value);
const char *material_wrap_name(uint8_t value);
const char *material_filter_name(uint8_t value);

std::vector<std::string> material_names(const MaterialSet &materials);
std::vector<std::string> material_texture_paths(
    const MaterialSet &materials);
void assign_material_names(
    MaterialSet &materials,
    const std::vector<std::string> &names);
void assign_material_texture_paths(
    MaterialSet &materials,
    const std::vector<std::string> &paths);

void validate_material_set(
    const MaterialSet &materials,
    const char *context = "material set");
