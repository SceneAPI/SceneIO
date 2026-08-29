// Native stored-row E57 scan records.
//
// PointScan deliberately keeps the provider's stored rows (including raw
// invalid-state bytes and optional row/column indices) separate from the
// valid-point projection.  The child PointCloud is always local and neutral;
// the scan-level viewpoint is the single authoritative pose.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "records/point_cloud.hpp"

struct PointScan {
    PointCloud point_cloud;
    std::vector<uint8_t> invalid_states;
    std::vector<int64_t> row_indices;
    std::vector<int64_t> column_indices;
    bool has_invalid_states = false;
    bool has_row_indices = false;
    bool has_column_indices = false;
    int64_t row_minimum = 0;
    int64_t row_maximum = 0;
    int64_t column_minimum = 0;
    int64_t column_maximum = 0;
    int64_t scan_id = 0;
    std::string name;
    std::string guid;
    std::optional<double> timestamp;
    // tx, ty, tz, qw, qx, qy, qz; scan/local -> reference/global.
    double viewpoint[7] = {0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0};

    size_t num_stored_points() const { return point_cloud.n; }
    size_t num_valid_points() const;
};

struct ScanSet {
    std::vector<PointScan> scans;
    std::vector<int64_t> scan_ids;

    size_t num_scans() const { return scans.size(); }
};

void validate_point_scan(
    const PointScan &scan, const char *context = "PointScan");
void validate_scan_set(
    const ScanSet &scans, const char *context = "ScanSet");
void register_point_scan(nb::module_ &module);
