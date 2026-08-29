"""Generated rich-USD geometry benchmark used by the USD closure ledger."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path

import numpy as np

import sceneio
from bench.io_bench.measure import measure, measure_in_process_rss
from sceneio import _core


def build_scene(face_count: int, point_count: int):
    """Build one deterministic mesh-plus-points SceneGraph and byte count."""

    if face_count < 0 or point_count < 0:
        raise ValueError("face_count and point_count must be nonnegative")

    vertex_count = face_count * 3
    mesh_index = np.arange(vertex_count, dtype=np.float32)
    positions = np.column_stack(
        (
            mesh_index / np.float32(1024),
            np.sin(mesh_index / np.float32(127)),
            np.cos(mesh_index / np.float32(251)),
        )
    ).astype(np.float32, copy=False)
    normals = np.zeros((vertex_count, 3), dtype=np.float32)
    normals[:, 2] = 1
    uvs = np.column_stack(
        (
            (mesh_index % np.float32(3)) / np.float32(2),
            (mesh_index % np.float32(5)) / np.float32(4),
        )
    ).astype(np.float32, copy=False)
    colors = np.column_stack(
        (
            mesh_index % np.float32(17) / np.float32(16),
            mesh_index % np.float32(29) / np.float32(28),
            mesh_index % np.float32(43) / np.float32(42),
        )
    ).astype(np.float32, copy=False)
    face_offsets = np.arange(0, vertex_count + 1, 3, dtype=np.uint64)
    face_indices = np.arange(vertex_count, dtype=np.uint64)
    mesh = _core.mesh(
        positions,
        face_offsets,
        face_indices,
        vertex_normals=normals,
        corner_uvs=uvs,
        vertex_display_colors=colors,
        display_color_space="linear",
        coordinate_frame="opengl",
        scale_to_meters=1.0,
    )

    point_index = np.arange(point_count, dtype=np.float32)
    point_positions = np.column_stack(
        (
            point_index / np.float32(128),
            np.sin(point_index / np.float32(67)),
            np.cos(point_index / np.float32(131)),
        )
    ).astype(np.float32, copy=False)
    point_normals = np.zeros((point_count, 3), dtype=np.float32)
    point_normals[:, 1] = 1
    widths = (
        np.float32(0.01)
        + (point_index % np.float32(13)) * np.float32(0.001)
    ).astype(np.float32, copy=False)
    ids = np.arange(point_count, dtype=np.int64)
    velocities = np.column_stack(
        (
            np.ones(point_count, dtype=np.float32),
            np.zeros(point_count, dtype=np.float32),
            point_index % np.float32(7),
        )
    )
    point_colors = np.column_stack(
        (
            point_index % np.float32(11) / np.float32(10),
            point_index % np.float32(19) / np.float32(18),
            point_index % np.float32(31) / np.float32(30),
        )
    ).astype(np.float32, copy=False)
    cloud = _core.point_cloud(
        point_positions,
        normals=point_normals,
        display_colors=point_colors,
        widths=widths,
        ids=ids,
        velocities=velocities,
        display_color_space="linear",
        coordinate_frame="opengl",
        scale_to_meters=1.0,
    )
    scene = _core.scene_graph(
        ["Surface", "Samples"],
        node_child_offsets=np.array([0, 0, 0], np.uint64),
        node_children=np.empty(0, np.uint64),
        node_payload_kinds=["mesh", "point_cloud"],
        node_payload_indices=np.array([0, 0], np.uint64),
        meshes=[mesh],
        point_clouds=[cloud],
        up_axis="y",
        meters_per_unit=1.0,
        default_prim=0,
    )
    payload_bytes = sum(
        array.nbytes
        for array in (
            positions,
            normals,
            uvs,
            colors,
            face_offsets,
            face_indices,
            point_positions,
            point_normals,
            widths,
            ids,
            velocities,
            point_colors,
        )
    )
    return scene, payload_bytes


def _cold_cache_supported() -> bool:
    return hasattr(os, "posix_fadvise") and hasattr(
        os,
        "POSIX_FADV_DONTNEED",
    )


def _evict_file_cache(path: Path) -> bool:
    if not (
        _cold_cache_supported()
    ):
        return False
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(
            descriptor,
            0,
            0,
            os.POSIX_FADV_DONTNEED,
        )
    finally:
        os.close(descriptor)
    return True


def _metrics(operation, *, runs: int) -> dict[str, float]:
    elapsed, traced_peak = measure(operation, runs)
    rss_peak = measure_in_process_rss(operation)
    return {
        "ms": elapsed * 1000,
        "traced_peak_mb": traced_peak / 1e6,
        "rss_peak_mb": rss_peak / 1e6,
    }


def _verify(
    path: Path,
    *,
    expected,
) -> None:
    full = sceneio.read_scene(path)
    selected = sceneio.read_scene(path, prims=("/Samples",))
    inspected = sceneio.inspect(path)
    if (
        full.num_meshes != 1
        or full.num_point_clouds != 1
        or full.mesh_at(0).num_faces != expected.mesh_at(0).num_faces
        or (
            full.point_cloud_at(0).num_points
            != expected.point_cloud_at(0).num_points
        )
    ):
        raise AssertionError("rich USD full-read counts differ")
    if (
        selected.node_names != ["Samples"]
        or selected.num_meshes != 0
        or selected.num_point_clouds != 1
        or (
            selected.point_cloud_at(0).num_points
            != expected.point_cloud_at(0).num_points
        )
    ):
        raise AssertionError("rich USD selected-prim result differs")
    if (
        inspected.count != 2
        or inspected.shape
        != (
            expected.mesh_at(0).num_vertices
            + expected.point_cloud_at(0).num_points,
            3,
        )
    ):
        raise AssertionError("rich USD inspection counts differ")
    for name in (
        "positions",
        "face_offsets",
        "face_indices",
        "vertex_normals",
        "corner_uvs",
        "vertex_display_colors",
    ):
        np.testing.assert_array_equal(
            getattr(full.mesh_at(0), name),
            getattr(expected.mesh_at(0), name),
        )
    for name in (
        "positions",
        "normals",
        "widths",
        "ids",
        "velocities",
        "display_colors",
    ):
        np.testing.assert_array_equal(
            getattr(full.point_cloud_at(0), name),
            getattr(expected.point_cloud_at(0), name),
        )
    np.testing.assert_array_equal(
        selected.point_cloud_at(0).positions,
        expected.point_cloud_at(0).positions,
    )


def run_benchmark(
    directory: str | os.PathLike[str],
    *,
    runs: int,
    face_count: int,
    point_count: int,
    encodings: tuple[str, ...] = ("usda", "usdz"),
    cold_cache: bool = False,
) -> list[dict[str, object]]:
    """Measure generated rich USDA/USDZ write, read, inspect, and selection."""

    if runs < 1:
        raise ValueError("runs must be positive")
    if not encodings or any(item not in {"usda", "usdz"} for item in encodings):
        raise ValueError("encodings must contain only usda and usdz")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    scene, payload_bytes = build_scene(face_count, point_count)
    payload_mb = payload_bytes / 1e6
    cold_cache_supported = _cold_cache_supported()
    results: list[dict[str, object]] = []

    for encoding in encodings:
        path = root / f"rich-geometry.{encoding}"

        def write() -> None:
            sceneio.write_scene(scene, path)

        write()

        def read_full():
            if cold_cache:
                _evict_file_cache(path)
            return sceneio.read_scene(path)

        def inspect():
            if cold_cache:
                _evict_file_cache(path)
            return sceneio.inspect(path)

        def read_selected():
            if cold_cache:
                _evict_file_cache(path)
            return sceneio.read_scene(path, prims=("/Samples",))

        write_metrics = _metrics(write, runs=runs)
        full_metrics = _metrics(read_full, runs=runs)
        inspect_metrics = _metrics(inspect, runs=runs)
        selected_metrics = _metrics(read_selected, runs=runs)
        _verify(
            path,
            expected=scene,
        )
        results.append(
            {
                "encoding": encoding,
                "faces": face_count,
                "points": point_count,
                "payload_mb": payload_mb,
                "file_mb": path.stat().st_size / 1e6,
                "write": write_metrics,
                "full_read": full_metrics,
                "inspect": inspect_metrics,
                "selected_read": selected_metrics,
                "write_mbps": payload_mb / (write_metrics["ms"] / 1000),
                "full_read_mbps": payload_mb
                / (full_metrics["ms"] / 1000),
                "cold_cache_requested": cold_cache,
                "cold_cache_supported": cold_cache_supported,
                "cold_cache_applied": cold_cache and cold_cache_supported,
            }
        )
        gc.collect()
    return results


def render_results(results: list[dict[str, object]]) -> str:
    return json.dumps(results, indent=2, sort_keys=True)


__all__ = ["build_scene", "render_results", "run_benchmark"]
