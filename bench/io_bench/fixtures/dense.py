"""Deterministic COLMAP dense-MVS benchmark fixtures."""

from __future__ import annotations

import numpy as np

from sceneio import _core


def dense_fixtures(scale: float):
    side = max(1, int(1024 * scale**0.5))
    rng = np.random.default_rng(20260729)
    depth_values = rng.standard_normal((side, side)).astype(np.float32)
    depth = _core.depth_map(
        depth_values,
        unit="unknown",
        invalid_policy="nonpositive",
        depth_convention="camera_z",
    )
    normal_values = rng.standard_normal((side, side, 3)).astype(np.float32)
    normal = _core.normal_map(normal_values)

    flat = np.arange(side * side, dtype=np.uint64)[::4]
    rows = (flat // side).astype(np.uint32)
    columns = (flat % side).astype(np.uint32)
    offsets = np.arange(rows.size + 1, dtype=np.uint64) * 4
    graph_indices = (
        np.arange(rows.size * 4, dtype=np.uint32).reshape(-1, 4)
        * np.array([3, 5, 7, 11], np.uint32)
    ).reshape(-1) % 2048
    graph = _core.consistency_graph(
        side, side, rows, columns, offsets, graph_indices
    )

    points = max(1, int(500_000 * scale))
    point_offsets = np.arange(points + 1, dtype=np.uint64) * 4
    visibility_indices = (
        np.arange(points * 4, dtype=np.uint32).reshape(-1, 4)
        * np.array([11, 3, 17, 5], np.uint32)
    ).reshape(-1) % 4096
    visibility = _core.point_visibility(
        point_offsets, visibility_indices
    )
    return {
        "depth": (depth, depth_values),
        "normal": (normal, normal_values),
        "consistency": (
            graph,
            (
                side,
                side,
                rows,
                columns,
                offsets,
                graph_indices,
            ),
        ),
        "visibility": (
            visibility,
            (point_offsets, visibility_indices),
        ),
    }


__all__ = ["dense_fixtures"]

