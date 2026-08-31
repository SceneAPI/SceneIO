// records/flow_field.hpp -- typed dense optical-flow memory representation.
// The required payload is one contiguous (H,W,2) float32 array. Values are
// stored raw and are never reordered, rescaled, scrubbed, or interpreted by
// the record; the convention fields describe how callers must interpret them.
//
// Middlebury .flo uses this record directly so raw vectors and their semantic
// conventions cannot diverge into parallel in-memory representations.
#pragma once

#include <string>

#include "io/common.hpp"

struct FlowField {
    size_t height = 0;
    size_t width = 0;
    std::vector<float> vectors;  // H*W*2, row-major, interleaved components

    // Recorded conventions. Writers guard these instead of silently changing
    // axis direction, component order, row order, units, or invalid values.
    std::string component_order = "uv";  // uv|vu
    std::string u_axis = "right";        // right|left
    std::string v_axis = "down";         // down|up
    std::string row_order = "top_to_bottom";  // top_to_bottom|bottom_to_top
    std::string unit = "pixels";              // pixels|unknown
    std::string invalid_policy =
        "component_abs_gt_1e9";  // none|component_abs_gt_1e9|nonfinite

    size_t count() const { return height * width; }
};

inline bool flow_valid_component_order(const std::string &value) {
    return value == "uv" || value == "vu";
}
inline bool flow_valid_u_axis(const std::string &value) {
    return value == "right" || value == "left";
}
inline bool flow_valid_v_axis(const std::string &value) {
    return value == "down" || value == "up";
}
inline bool flow_valid_row_order(const std::string &value) {
    return value == "top_to_bottom" || value == "bottom_to_top";
}
inline bool flow_valid_unit(const std::string &value) {
    return value == "pixels" || value == "unknown";
}
inline bool flow_valid_invalid_policy(const std::string &value) {
    return value == "none" || value == "component_abs_gt_1e9" ||
           value == "nonfinite";
}
