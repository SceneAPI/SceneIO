// records/pose_graph.hpp -- typed SE(3) pose graph in a zero-copy SoA layout.
//
// Node estimates and edge measurements deliberately carry separate convention
// metadata.  For g2o's SE3:QUAT types, a node estimate is a node-to-reference
// transform and an edge measurement is source.inverse() * target.  The public
// information matrices are full symmetric 6x6 matrices in
// (tx,ty,tz,qx,qy,qz) order; the g2o codec serializes their 21 upper-triangle
// coefficients without changing coefficient values.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "io/common.hpp"

struct PoseGraph {
    size_t n = 0;
    size_t m = 0;

    std::vector<int64_t> node_ids;          // n
    std::vector<double> node_translations;  // n*3
    std::vector<double> node_quaternions;   // n*4
    std::vector<uint8_t> fixed;             // n, canonical 0/1
    std::vector<std::string> node_types;    // n

    std::vector<int64_t> edge_endpoints;       // m*2: source,target ids
    std::vector<double> edge_translations;     // m*3
    std::vector<double> edge_quaternions;      // m*4
    std::vector<double> information_matrices;  // m*6*6, symmetric
    std::vector<std::string> edge_types;       // m

    std::string quaternion_order = "xyzw";
    std::string quaternion_sign = "preserved";
    std::string node_transform_convention = "node_to_reference";
    std::string edge_transform_convention =
        "source_inverse_times_target";
    std::string translation_unit = "unspecified";
    std::string information_variable_order =
        "tx_ty_tz_qx_qy_qz";

    size_t num_nodes() const { return n; }
    size_t num_edges() const { return m; }
};

void validate_pose_graph(
    const PoseGraph &graph, const char *context = "pose_graph");

inline bool pose_graph_valid_quaternion_order(
    const std::string &value) {
    return value == "wxyz" || value == "xyzw";
}
inline bool pose_graph_valid_quaternion_sign(
    const std::string &value) {
    return value == "preserved" ||
           value == "canonical_positive_w";
}
inline bool pose_graph_valid_node_convention(
    const std::string &value) {
    return value == "node_to_reference" ||
           value == "reference_to_node";
}
inline bool pose_graph_valid_edge_convention(
    const std::string &value) {
    return value == "source_inverse_times_target" ||
           value == "target_inverse_times_source";
}
inline bool pose_graph_valid_translation_unit(
    const std::string &value) {
    return value == "unspecified" || value == "meters" ||
           value == "millimeters";
}
inline bool pose_graph_valid_information_order(
    const std::string &value) {
    return value == "tx_ty_tz_qx_qy_qz";
}
