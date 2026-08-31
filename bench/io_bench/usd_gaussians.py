"""Generated USD Gaussian benchmark for the C3 closure ledger."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path

import numpy as np

import sceneio
from bench.io_bench.measure import measure, measure_in_process_rss
from sceneio import _core


def build_scene(
    *,
    gaussian_count: int,
    degree: int,
    precision: str,
):
    """Build one deterministic official-schema Gaussian payload."""

    if gaussian_count < 0:
        raise ValueError("gaussian_count must be nonnegative")
    if degree not in {0, 1, 2, 3}:
        raise ValueError("degree must be in [0, 3]")
    if precision not in {"float16", "float32"}:
        raise ValueError("precision must be float16 or float32")

    index = np.arange(gaussian_count, dtype=np.float32)
    position_index = (
        index
        if precision == "float32"
        else index % np.float32(4096)
    )
    positions = np.empty((gaussian_count, 3), np.float32)
    positions[:, 0] = position_index * np.float32(0.25)
    positions[:, 1] = (index % np.float32(257)) * np.float32(0.125)
    positions[:, 2] = (index % np.float32(17)) - np.float32(8)
    scales = np.ones((gaussian_count, 3), np.float32)
    scales[:, 1] = np.float32(0.5)
    scales[:, 2] = np.float32(2)
    quaternions = np.zeros((gaussian_count, 4), np.float32)
    quaternions[:, 0] = 1
    opacities = np.full(gaussian_count, 0.5, np.float32)
    sh_dc = np.zeros((gaussian_count, 3), np.float32)
    sh_dc[:, 0] = (index % np.float32(9)) * np.float32(0.125)
    sh_rest = np.zeros(
        (gaussian_count, ((degree + 1) ** 2 - 1) * 3),
        np.float32,
    )
    if sh_rest.shape[1]:
        sh_rest[:, 0] = (index % np.float32(5)) * np.float32(0.0625)
    if precision == "float16":
        arrays = (positions, scales, quaternions, opacities, sh_dc, sh_rest)
        positions, scales, quaternions, opacities, sh_dc, sh_rest = (
            value.astype(np.float16).astype(np.float32) for value in arrays
        )

    cloud = _core.gaussian_cloud(
        positions,
        scales,
        quaternions,
        opacities,
        sh_dc,
        sh_rest,
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
        source_precision=precision,
    )
    scene = _core.scene_graph(
        ["Cloud"],
        node_payload_kinds=["gaussian_cloud"],
        node_payload_indices=np.array([0], np.uint64),
        gaussian_clouds=[cloud],
        up_axis="y",
        meters_per_unit=1.0,
        default_prim=0,
    )
    payload_bytes = sum(
        np.asarray(getattr(cloud, name)).nbytes
        for name in (
            "means",
            "scales",
            "quaternions",
            "opacities",
            "sh_dc",
            "sh_rest",
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


def _assert_cloud_bits(actual, expected) -> None:
    for name in (
        "means",
        "scales",
        "quaternions",
        "opacities",
        "sh_dc",
        "sh_rest",
    ):
        if (
            np.asarray(getattr(actual, name)).tobytes()
            != np.asarray(getattr(expected, name)).tobytes()
        ):
            raise AssertionError(f"USD Gaussian benchmark differs at {name}")
    if (
        actual.sh_degree != expected.sh_degree
        or actual.source_precision != expected.source_precision
        or actual.projection_mode_hint != expected.projection_mode_hint
        or actual.sorting_mode_hint != expected.sorting_mode_hint
    ):
        raise AssertionError("USD Gaussian benchmark metadata differs")


def _three_dgs_cloud(cloud):
    return sceneio.convert_gaussian_conventions(
        cloud,
        scale_space="log",
        opacity_space="logit",
        sh_layout="channel_grouped",
    )


def run_benchmark(
    directory: str | os.PathLike[str],
    *,
    runs: int,
    gaussian_counts: tuple[int, ...],
    degree: int,
    precision: str,
    encodings: tuple[str, ...] = ("usda", "usdz", "gaussian_ply"),
) -> list[dict[str, object]]:
    """Measure Gaussian write, full read, and metadata inspection."""

    if runs < 1:
        raise ValueError("runs must be positive")
    if not gaussian_counts or any(count < 0 for count in gaussian_counts):
        raise ValueError("gaussian_counts must contain nonnegative values")
    allowed = {"usda", "usdz", "gaussian_ply"}
    if not encodings or any(item not in allowed for item in encodings):
        raise ValueError(
            "encodings must contain only usda, usdz, and gaussian_ply"
        )
    if precision != "float32" and "gaussian_ply" in encodings:
        raise ValueError("gaussian_ply control requires float32 precision")

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for gaussian_count in gaussian_counts:
        scene, payload_bytes = build_scene(
            gaussian_count=gaussian_count,
            degree=degree,
            precision=precision,
        )
        cloud = scene.gaussian_cloud_at(0)
        payload_mb = payload_bytes / 1e6
        for encoding in encodings:
            if encoding == "gaussian_ply":
                path = root / f"gaussians-{gaussian_count}.ply"
                expected = _three_dgs_cloud(cloud)

                def write() -> None:
                    sceneio.write(expected, path, format="gaussian_ply")

                def read_full():
                    return sceneio.read(path, format="gaussian_ply")

                def inspect():
                    return sceneio.inspect(path, format="gaussian_ply")

            else:
                path = root / f"gaussians-{gaussian_count}.{encoding}"
                expected = cloud

                def write() -> None:
                    sceneio.write_scene(scene, path)

                def read_full():
                    return sceneio.read_scene(path).gaussian_cloud_at(0)

                def inspect():
                    return sceneio.inspect(path)

            write()
            actual = read_full()
            inspected = inspect()
            _assert_cloud_bits(actual, expected)
            if encoding == "gaussian_ply":
                if inspected.count != gaussian_count:
                    raise AssertionError(
                        "Gaussian PLY inspection count differs"
                    )
            elif (
                inspected.shape != (gaussian_count, 3)
                or inspected.metadata["num_gaussian_clouds"] != 1
                or inspected.metadata["unsupported_features"] != ()
            ):
                raise AssertionError("USD Gaussian inspection metadata differs")

            write_metrics = _metrics(write, runs=runs)
            full_metrics = _metrics(read_full, runs=runs)
            inspect_metrics = _metrics(inspect, runs=runs)
            results.append(
                {
                    "encoding": encoding,
                    "gaussians": gaussian_count,
                    "degree": degree,
                    "precision": precision,
                    "payload_mb": payload_mb,
                    "file_mb": path.stat().st_size / 1e6,
                    "write": write_metrics,
                    "full_read": full_metrics,
                    "inspect": inspect_metrics,
                    "write_mbps": payload_mb / (write_metrics["ms"] / 1000),
                    "full_read_mbps": payload_mb
                    / (full_metrics["ms"] / 1000),
                }
            )
            del actual, inspected
            gc.collect()
        gc.collect()
    return results


def render_results(results: list[dict[str, object]]) -> str:
    return json.dumps(results, indent=2, sort_keys=True)


__all__ = ["build_scene", "render_results", "run_benchmark"]
