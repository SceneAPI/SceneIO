// Shared 3D Gaussian Splatting memory representation. Both the PLY and SPZ
// codecs decode into this same GaussianCloud (registered once), so a splat
// loaded from either format has an identical in-memory layout.
//
// Canonical conventions (raw / pre-activation, matching the 3DGS PLY):
//   means (N,3), scales (N,3, log space), quats (N,4, WXYZ),
//   opacity (N, logit space), sh_dc (N,3), sh_rest (N,R) channel-grouped
//   [R.. G.. B..] with R in {0,9,24,45}.
#pragma once

#include "io/common.hpp"

struct GaussianCloud {
    size_t n = 0;
    std::vector<float> means;    // n*3
    std::vector<float> sh_dc;    // n*3
    std::vector<float> sh_rest;  // n*R, channel-grouped
    std::vector<float> opacity;  // n
    std::vector<float> scales;   // n*3
    std::vector<float> quats;    // n*4 (WXYZ)
    size_t num_rest = 0;         // R
    int sh_degree = 0;
};

inline int gc_deg_from_rest(size_t R) {
    if (R == 0) return 0;
    if (R == 9) return 1;
    if (R == 24) return 2;
    if (R == 45) return 3;
    return -1;
}

inline size_t gc_rest_for_sh_dim(size_t sh_dim) { return sh_dim * 3; }  // {0,3,8,15} -> {0,9,24,45}
