// records/depth_map.hpp -- scalar depth-map memory representation. A single
// (H,W) float32 depth raster (row-major, top-to-bottom rows, RAW stored values
// -- never rescaled) plus an optional (H,W) float32 confidence raster. The
// unit / scale_to_meters / invalid_policy conventions are metadata the codec
// RECORDED (reader records, writer guards); nothing here is ever baked into the
// pixel values. Backs the depth codecs later (16-bit depth PNG, ScanNet/Azure
// mm PNG, Gipuma .dmb, COLMAP MVS matrices, EXR/PFM metric depth) without ABI breaks -- a
// 16-bit-PNG codec widens u16->f32 losslessly and records the scale, it never
// divides. Gipuma DMB is the first in-tree consumer; COLMAP's unrelated
// width&height&depth& matrix format requires its own codec.
//
// Optical flow (.flo) is deliberately NOT this record -- it ships separately as
// a bare (H,W,2) float32 ndarray codec (in-tree at
// src/cpp/codecs/arrays/flo.cpp; the
// read_pfm precedent), because .flo fixes every convention in its spec and a
// (H,W,2) field would break this record's scalar contract. The design-sanctioned
// escape for typed flow is a separate FlowField record, never widening DepthMap.
//
// Mirrors the Phase-1a Image record exactly: a plain struct with inline
// vocabulary / pairing validators, an owner-carrying zero-copy binding
// (sio::view), and a depth_map(...) factory whose unit<->scale pairing guard is
// the Image dtype<->maxval guard, transposed.
#pragma once

#include <cmath>  // std::isfinite

#include "io/common.hpp"  // nb alias; sio::view; <vector>/<string>/<cstdint>/<stdexcept>

struct DepthMap {
    size_t height = 0, width = 0;  // both >= 1 (enforced by the factory / codecs)
    // H*W raw stored depth values, row-major, top-to-bottom rows -- NEVER
    // rescaled (a 16-bit-PNG codec widens u16->f32 losslessly, records scale).
    std::vector<float> depth;
    // H*W confidence scores, or empty == absent. RAW as stored; the range is
    // deliberately unconstrained (MVS photometric scores are unbounded -- the
    // [0,1] rule belongs to the Python contract sceneio.ConfidenceMap,
    // not this record).
    std::vector<float> confidence;
    // Optional semantic validity mask (0/1, H*W). Empty means every pixel is
    // valid. The source sentinel policy remains separate encoding metadata.
    std::vector<uint8_t> valid;
    // Conventions the codec RECORDED (metadata, never applied to the arrays):
    std::string unit = "meters";          // meters|millimeters|custom|unitless|unknown
    double scale_to_meters = 1.0;         // depth * scale_to_meters -> meters; 0.0 == non-metric/unknown
    std::string invalid_policy =
        "none";  // none|zero|nonfinite|negative|nonpositive
    // Geometric meaning of each scalar. File formats that do not encode it
    // must retain "unspecified"; COLMAP MVS records optical-axis camera Z.
    std::string depth_convention =
        "unspecified";  // unspecified|camera_z|ray_distance

    size_t count() const { return height * width; }
    bool has_confidence() const { return !confidence.empty(); }
    bool has_validity() const { return !valid.empty(); }
};

// Semantic of the raw stored depth values (5-token closed vocabulary).
inline bool depth_map_valid_unit(const std::string &s) {
    return s == "meters" || s == "millimeters" || s == "custom" || s == "unitless" ||
           s == "unknown";
}
// Which stored-value class means "no measurement" (4-token closed vocabulary).
inline bool depth_map_valid_invalid_policy(const std::string &s) {
    return s == "none" || s == "zero" || s == "nonfinite" ||
           s == "negative" || s == "nonpositive";
}
inline bool depth_map_valid_depth_convention(const std::string &s) {
    return s == "unspecified" || s == "camera_z" ||
           s == "ray_distance";
}
// The Image dtype<->maxval pairing guard, transposed to unit<->scale: each unit
// pins the scale that means it, and 0.0 is the non-metric ("not convertible")
// sentinel shared by unitless|unknown.
inline bool depth_map_unit_scale_consistent(const std::string &u, double s) {
    if (u == "meters") return s == 1.0;
    if (u == "millimeters") return s == 0.001;
    if (u == "custom") return std::isfinite(s) && s > 0.0;  // e.g. TUM 1/5000 = 0.0002
    return s == 0.0;                                        // unitless | unknown
}

inline bool depth_map_policy_valid(const std::string &policy, float value) {
    if (policy == "none") return true;
    if (policy == "zero") return value != 0.0f;
    if (policy == "nonfinite") return std::isfinite(value);
    if (policy == "negative") return value >= 0.0f;
    return value > 0.0f;  // nonpositive
}

inline void depth_map_derive_validity(DepthMap &value) {
    if (value.invalid_policy == "none") return;
    std::vector<uint8_t> valid(value.count(), uint8_t{1});
    bool all_valid = true;
    for (size_t index = 0; index < value.count(); ++index) {
        valid[index] = static_cast<uint8_t>(
            depth_map_policy_valid(value.invalid_policy, value.depth[index]));
        all_valid = all_valid && valid[index] != 0;
    }
    if (!all_valid) value.valid = std::move(valid);
}

inline bool depth_map_validity_matches_policy(const DepthMap &value) {
    if (!value.has_validity()) return true;
    if (value.valid.size() != value.count()) return false;
    for (size_t index = 0; index < value.count(); ++index)
        if (static_cast<bool>(value.valid[index]) !=
            depth_map_policy_valid(value.invalid_policy, value.depth[index]))
            return false;
    return true;
}
