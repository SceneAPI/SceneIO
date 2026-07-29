// records/dense_mvs.hpp -- typed dense-MVS records shared by COLMAP's
// repository-owned dense codecs.
#pragma once

#include <cstdint>
#include <vector>

#include "io/common.hpp"

inline constexpr uint64_t kColmapMvsDimensionCap = 1'000'000;
inline constexpr uint64_t kColmapMvsEntryCap = 250'000'000;
inline constexpr uint64_t kColmapMvsListValueCap = 1'000'000'000;

struct NormalMap {
    size_t height = 0;
    size_t width = 0;
    std::vector<float> normals;  // H*W*3, row-major, interleaved XYZ

    size_t count() const { return height * width; }
};

struct ConsistencyGraph {
    size_t height = 0;
    size_t width = 0;
    // One row per explicitly stored pixel, retained in source order.
    std::vector<uint32_t> rows;
    std::vector<uint32_t> columns;
    // CSR offsets into image_indices. Zero-count entries remain representable.
    std::vector<uint64_t> offsets;
    std::vector<uint32_t> image_indices;

    size_t entry_count() const { return rows.size(); }
};

struct PointVisibility {
    // One CSR row per fused point. Values are COLMAP MVS sequential image
    // indices, not sparse-reconstruction image IDs.
    std::vector<uint64_t> offsets;
    std::vector<uint32_t> image_indices;

    size_t point_count() const {
        return offsets.empty() ? 0 : offsets.size() - 1;
    }
};
