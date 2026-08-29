"""Generated USD material/asset benchmark for the C2 closure ledger."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path

import numpy as np

import sceneio
from bench.io_bench.measure import measure, measure_in_process_rss
from sceneio import _core

_WRITE_CHUNK_SIZE = 1024 * 1024


def _write_generated_asset(path: Path, byte_count: int) -> None:
    """Create a deterministic opaque asset without a whole-asset allocation."""

    chunk = bytes(_WRITE_CHUNK_SIZE)
    with path.open("wb") as stream:
        remaining = byte_count
        while remaining:
            count = min(remaining, len(chunk))
            stream.write(chunk[:count])
            remaining -= count


def build_scene(
    directory: str | os.PathLike[str],
    *,
    face_count: int,
    material_count: int,
    texture_bytes: int,
):
    """Build a deterministic multi-material mesh and one streamed asset."""

    if face_count < 0:
        raise ValueError("face_count must be nonnegative")
    if material_count < 1:
        raise ValueError("material_count must be positive")
    if texture_bytes < 0:
        raise ValueError("texture_bytes must be nonnegative")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    texture = root / "generated-texture.png"
    _write_generated_asset(texture, texture_bytes)

    vertex_count = face_count * 3
    vertex = np.arange(vertex_count, dtype=np.float32)
    positions = np.column_stack(
        (
            vertex / np.float32(1024),
            np.sin(vertex / np.float32(127)),
            np.cos(vertex / np.float32(251)),
        )
    ).astype(np.float32, copy=False)
    face_offsets = np.arange(0, vertex_count + 1, 3, dtype=np.uint64)
    face_indices = np.arange(vertex_count, dtype=np.uint64)
    primitive_offsets = np.arange(face_count + 1, dtype=np.uint64)
    primitive_materials = (
        np.arange(face_count, dtype=np.int32) % material_count
    )
    mesh = _core.mesh(
        positions,
        face_offsets,
        face_indices,
        primitive_offsets=primitive_offsets,
        primitive_materials=primitive_materials,
        coordinate_frame="opengl",
        scale_to_meters=1.0,
    )

    names = [f"material_{index}" for index in range(material_count)]
    colors = np.ones((material_count, 4), dtype=np.float32)
    if material_count > 1:
        values = np.arange(1, material_count, dtype=np.float32)
        colors[1:, 0] = values / np.float32(material_count)
        colors[1:, 1] = np.float32(0.5)
        colors[1:, 2] = np.float32(0.25)
    materials = _core.material_set(
        names,
        base_colors=colors,
        texture_materials=np.array([0], np.uint64),
        texture_semantics=["base_color"],
        texture_paths=["generated-texture.png"],
    )
    scene = _core.scene_graph(
        ["Surface"],
        node_child_offsets=np.array([0, 0], np.uint64),
        node_children=np.empty(0, np.uint64),
        node_payload_kinds=["mesh"],
        node_payload_indices=np.array([0], np.uint64),
        meshes=[mesh],
        materials=materials,
        external_asset_uris=["generated-texture.png"],
        external_asset_kinds=["texture"],
        external_asset_sources=[str(texture)],
        up_axis="y",
        meters_per_unit=1.0,
    )
    payload_bytes = sum(
        array.nbytes
        for array in (
            positions,
            face_offsets,
            face_indices,
            primitive_offsets,
            primitive_materials,
            colors,
        )
    ) + texture_bytes
    return scene, payload_bytes


def _metrics(operation, *, runs: int) -> dict[str, float]:
    elapsed, traced_peak = measure(operation, runs)
    rss_peak = measure_in_process_rss(operation)
    return {
        "ms": elapsed * 1000,
        "traced_peak_mb": traced_peak / 1e6,
        "rss_peak_mb": rss_peak / 1e6,
    }


def _verify(path: Path, *, expected, face_count: int, material_count: int) -> None:
    actual = sceneio.read_scene(path)
    inspected = sceneio.inspect(path)
    if (
        actual.num_meshes != 1
        or actual.mesh_at(0).num_faces != face_count
        or actual.materials.num_materials != material_count
        or actual.external_asset_kinds != ["texture"]
        or inspected.metadata["num_materials"] != material_count
        or inspected.metadata["num_textures"] != 1
    ):
        raise AssertionError("rich USD material benchmark counts differ")
    np.testing.assert_array_equal(
        actual.mesh_at(0).primitive_offsets,
        expected.mesh_at(0).primitive_offsets,
    )
    np.testing.assert_array_equal(
        actual.mesh_at(0).primitive_materials,
        expected.mesh_at(0).primitive_materials,
    )
    np.testing.assert_array_equal(
        actual.materials.base_colors,
        expected.materials.base_colors,
    )


def run_benchmark(
    directory: str | os.PathLike[str],
    *,
    runs: int,
    face_count: int,
    material_count: int,
    texture_bytes: int,
    encodings: tuple[str, ...] = ("usda", "usdz"),
) -> list[dict[str, object]]:
    """Measure multi-material write/read/inspect and streamed asset copying."""

    if runs < 1:
        raise ValueError("runs must be positive")
    if not encodings or any(item not in {"usda", "usdz"} for item in encodings):
        raise ValueError("encodings must contain only usda and usdz")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    scene, payload_bytes = build_scene(
        root,
        face_count=face_count,
        material_count=material_count,
        texture_bytes=texture_bytes,
    )
    payload_mb = payload_bytes / 1e6
    results: list[dict[str, object]] = []
    for encoding in encodings:
        path = root / f"rich-materials.{encoding}"

        def write() -> None:
            sceneio.write_scene(scene, path)

        write()

        def read_full():
            return sceneio.read_scene(path)

        def inspect():
            return sceneio.inspect(path)

        write_metrics = _metrics(write, runs=runs)
        full_metrics = _metrics(read_full, runs=runs)
        inspect_metrics = _metrics(inspect, runs=runs)
        _verify(
            path,
            expected=scene,
            face_count=face_count,
            material_count=material_count,
        )
        results.append(
            {
                "encoding": encoding,
                "faces": face_count,
                "materials": material_count,
                "texture_mb": texture_bytes / 1e6,
                "payload_mb": payload_mb,
                "stage_file_mb": path.stat().st_size / 1e6,
                "write": write_metrics,
                "full_read": full_metrics,
                "inspect": inspect_metrics,
                "write_mbps": payload_mb / (write_metrics["ms"] / 1000),
                "full_read_mbps": payload_mb
                / (full_metrics["ms"] / 1000),
            }
        )
        gc.collect()
    return results


def render_results(results: list[dict[str, object]]) -> str:
    return json.dumps(results, indent=2, sort_keys=True)


__all__ = ["build_scene", "render_results", "run_benchmark"]
