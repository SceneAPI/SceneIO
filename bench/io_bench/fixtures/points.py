"""Deterministic fixtures for point-cloud benchmark codecs."""

from __future__ import annotations

import numpy as np

from sceneio import _core


def _pc(n, color):
    rng = np.random.default_rng(0)
    xyz = (rng.random((n, 3), dtype=np.float32) * 100.0).astype(np.float32)
    kw = {}
    if color:
        kw["colors16"] = (rng.random((n, 3)) * 65535).astype(np.uint16)
        kw["intensity"] = (rng.random(n) * 60000).astype(np.float32)
    return _core.point_cloud(xyz, **kw), xyz


def _pc_laz(n):
    rng = np.random.default_rng(29)
    positions = (rng.random((n, 3), dtype=np.float32) * 100.0).astype(np.float32)
    colors16 = rng.integers(0, 65_536, (n, 3), dtype=np.uint16)
    intensity = rng.integers(0, 65_536, n, dtype=np.uint16)
    payload = {
        "positions": positions,
        "colors16": colors16,
        "intensity": intensity,
    }
    return (
        _core.point_cloud(
            positions,
            colors16=colors16,
            intensity=intensity.astype(np.float32),
            intensity_range="u16",
        ),
        payload,
    )


def _pc_ply(n):
    rng = np.random.default_rng(17)
    xyz = (rng.random((n, 3), dtype=np.float32) * 100.0).astype(np.float32)
    normals = rng.standard_normal((n, 3)).astype(np.float32)
    colors = rng.integers(0, 256, (n, 3), dtype=np.uint8)
    payload = {"positions": xyz, "normals": normals, "colors": colors}
    return (
        _core.point_cloud(xyz, colors=colors, normals=normals),
        payload,
    )


__all__ = ["_pc", "_pc_laz", "_pc_ply"]
