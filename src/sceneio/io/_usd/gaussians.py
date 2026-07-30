"""Official OpenUSD Gaussian-splat schema vocabulary."""

from __future__ import annotations

GAUSSIAN_PRIM_TYPE = "ParticleField3DGaussianSplat"
GAUSSIAN_PROPERTIES = frozenset(
    {
        "extent",
        "opacities",
        "orientations",
        "positions",
        "projectionModeHint",
        "radiance:sphericalHarmonicsCoefficients",
        "radiance:sphericalHarmonicsDegree",
        "scales",
        "sortingModeHint",
        "velocities",
    }
)
PROJECTION_HINTS = frozenset({"perspective", "tangential"})
SORTING_HINTS = frozenset({"zDepth", "cameraDistance", "rayHitDistance"})


__all__ = [
    "GAUSSIAN_PRIM_TYPE",
    "GAUSSIAN_PROPERTIES",
    "PROJECTION_HINTS",
    "SORTING_HINTS",
]
