"""Generated many-camera USD benchmark for the C4 closure ledger."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path

import numpy as np

import sceneio
from bench.io_bench.measure import measure, measure_in_process_rss
from sceneio import _core


def build_scene(*, camera_count: int):
    """Build a deterministic mixed perspective/orthographic CameraRig scene."""

    if camera_count < 1:
        raise ValueError("camera_count must be positive")
    node_count = camera_count + 1
    names = ["World", *(f"Camera_{index}" for index in range(camera_count))]
    child_offsets = np.empty(node_count + 1, np.uint64)
    child_offsets[0] = 0
    child_offsets[1] = camera_count
    child_offsets[2:] = camera_count
    children = np.arange(1, node_count, dtype=np.uint64)
    transforms = np.broadcast_to(np.eye(4), (node_count, 4, 4)).copy()
    translations = np.zeros((camera_count, 3), np.float64)
    translations[:, 0] = np.arange(camera_count) * 0.01
    translations[:, 1] = np.arange(camera_count) % 31
    transforms[1:, :3, 3] = translations
    quaternions = np.zeros((camera_count, 4), np.float64)
    quaternions[:, 0] = 1

    resolutions = np.empty((camera_count, 2), np.uint64)
    resolutions[:, 0] = 1920
    resolutions[:, 1] = 1080
    intrinsics = np.empty((camera_count, 4), np.float64)
    intrinsics[:, 0] = 960
    intrinsics[:, 1] = 960
    intrinsics[:, 2] = 960
    intrinsics[:, 3] = 540
    matrices = np.zeros((camera_count, 3, 3), np.float64)
    matrices[:, 0, 0] = intrinsics[:, 0]
    matrices[:, 1, 1] = intrinsics[:, 1]
    matrices[:, 0, 2] = intrinsics[:, 2]
    matrices[:, 1, 2] = intrinsics[:, 3]
    matrices[:, 2, 2] = 1
    models = [
        "pinhole" if index % 2 == 0 else "orthographic"
        for index in range(camera_count)
    ]
    rig = _core.camera_rig(
        np.arange(camera_count, dtype=np.uint32),
        resolutions,
        models,
        np.arange(0, 4 * camera_count + 1, 4, dtype=np.uint64),
        intrinsics.reshape(-1),
        ["none"] * camera_count,
        np.zeros(camera_count + 1, np.uint64),
        np.empty(0, np.float64),
        quaternions,
        translations,
        has_extrinsics=np.ones(camera_count, np.uint8),
        names=[f"/World/Camera_{index}" for index in range(camera_count)],
        camera_matrices=matrices,
        has_camera_matrix=np.ones(camera_count, np.uint8),
        quaternion_sign="canonical_positive_w",
        transform_convention="camera_to_reference",
        axis_frame="opengl",
        reference_frame="unknown",
    )
    payload_kinds = ["none", *("camera" for _ in range(camera_count))]
    payload_indices = np.full(node_count, np.iinfo(np.uint64).max, np.uint64)
    payload_indices[1:] = np.arange(camera_count, dtype=np.uint64)
    scene = _core.scene_graph(
        names,
        node_child_offsets=child_offsets,
        node_children=children,
        node_local_transforms=transforms,
        node_payload_kinds=payload_kinds,
        node_payload_indices=payload_indices,
        cameras=rig,
        default_prim=0,
    )
    payload_bytes = sum(
        np.asarray(getattr(rig, field)).nbytes
        for field in (
            "camera_ids",
            "resolutions",
            "intrinsic_offsets",
            "intrinsics",
            "distortion_offsets",
            "quaternions",
            "translations",
            "has_extrinsics",
            "camera_matrices",
            "has_camera_matrix",
        )
    )
    return scene, payload_bytes


def _metrics(operation, *, runs: int) -> dict[str, float]:
    elapsed, traced_peak = measure(operation, runs)
    rss_peak = measure_in_process_rss(operation)
    return {
        "ms": elapsed * 1000,
        "traced_peak_mb": traced_peak / 1e6,
        "rss_peak_mb": rss_peak / 1e6,
    }


def _assert_camera_rows(actual, expected) -> None:
    if (
        actual.names != expected.names
        or actual.projection_models != expected.projection_models
        or actual.distortion_models != expected.distortion_models
    ):
        raise AssertionError("USD camera benchmark string fields differ")
    for field in (
        "camera_ids",
        "resolutions",
        "intrinsic_offsets",
        "distortion_offsets",
        "quaternions",
        "translations",
    ):
        if not np.array_equal(getattr(actual, field), getattr(expected, field)):
            raise AssertionError(f"USD camera benchmark differs at {field}")
    if not np.allclose(
        actual.intrinsics, expected.intrinsics, rtol=2e-7, atol=2e-7
    ):
        raise AssertionError("USD camera benchmark intrinsics differ")


def run_benchmark(
    directory: str | os.PathLike[str],
    *,
    runs: int,
    camera_counts: tuple[int, ...],
    encodings: tuple[str, ...] = ("usda", "usdz"),
) -> list[dict[str, object]]:
    """Measure many-camera write, full read, inspection, and selected read."""

    if runs < 1:
        raise ValueError("runs must be positive")
    if not camera_counts or any(count < 1 for count in camera_counts):
        raise ValueError("camera_counts must contain positive values")
    if not encodings or any(item not in {"usda", "usdz"} for item in encodings):
        raise ValueError("encodings must contain only usda and usdz")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for camera_count in camera_counts:
        scene, payload_bytes = build_scene(camera_count=camera_count)
        expected = scene.cameras
        selected_path = f"/World/Camera_{camera_count - 1}"
        for encoding in encodings:
            path = root / f"cameras-{camera_count}.{encoding}"

            def write() -> None:
                sceneio.write_scene(scene, path)

            def read_full():
                return sceneio.read_scene(path)

            def inspect():
                return sceneio.inspect(path)

            def read_selected():
                return sceneio.read_scene(path, prims=selected_path)

            write()
            full = read_full()
            selected = read_selected()
            inspected = inspect()
            _assert_camera_rows(full.cameras, expected)
            if (
                selected.num_cameras != 1
                or selected.cameras.names != [selected_path]
                or inspected.metadata["num_cameras"] != camera_count
                or inspected.metadata["num_render_products"] != camera_count
                or inspected.metadata["unsupported_features"] != ()
            ):
                raise AssertionError("USD camera benchmark metadata differs")
            payload_mb = payload_bytes / 1e6
            write_metrics = _metrics(write, runs=runs)
            full_metrics = _metrics(read_full, runs=runs)
            inspect_metrics = _metrics(inspect, runs=runs)
            selected_metrics = _metrics(read_selected, runs=runs)
            results.append(
                {
                    "encoding": encoding,
                    "cameras": camera_count,
                    "payload_mb": payload_mb,
                    "file_mb": path.stat().st_size / 1e6,
                    "write": write_metrics,
                    "full_read": full_metrics,
                    "inspect": inspect_metrics,
                    "selected_read": selected_metrics,
                    "write_mbps": payload_mb / (write_metrics["ms"] / 1000),
                    "full_read_mbps": payload_mb
                    / (full_metrics["ms"] / 1000),
                }
            )
            del full, selected, inspected
            gc.collect()
        gc.collect()
    return results


def render_results(results: list[dict[str, object]]) -> str:
    return json.dumps(results, indent=2, sort_keys=True)


__all__ = ["build_scene", "render_results", "run_benchmark"]
