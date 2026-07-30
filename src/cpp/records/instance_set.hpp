// records/instance_set.hpp -- compact point-instancer payload.
//
// Prototype references are SceneGraph node indices.  Per-instance arrays stay
// in authored order and use one row per instance.  The explicit convention
// field prevents a codec from silently reordering quaternion components.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "records/tensor_dict.hpp"

struct InstanceSet {
    size_t n = 0;
    std::vector<uint64_t> prototype_nodes;    // P SceneGraph node indices
    std::vector<uint64_t> prototype_indices;  // n, each < P
    std::vector<int64_t> ids;                 // n, unique
    std::vector<float> translations;          // n*3
    std::vector<float> orientations;          // n*4
    std::vector<float> scales;                // n*3
    std::vector<int64_t> invisible_ids;        // unique subset of ids
    std::vector<uint8_t> invisible_mask;       // n, derived from ids
    std::string quaternion_order = "wxyz";

    bool has_attributes = false;
    TensorDict attributes;

    size_t num_instances() const { return n; }
    size_t num_prototypes() const { return prototype_nodes.size(); }
};

inline bool instance_valid_quaternion_order(const std::string &value) {
    return value == "wxyz" || value == "xyzw";
}

void validate_instance_set(
    const InstanceSet &instances,
    const char *context = "instance set");

