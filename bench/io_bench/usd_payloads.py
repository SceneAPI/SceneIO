"""Generated USD volume-dependency and point-instancer benchmark."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path

import numpy as np

import sceneio
from bench.io_bench.measure import measure, measure_in_process_rss
from sceneio import _core


def build_instance_scene(*, instance_count: int):
    """Build one compact instancer without duplicating prototype geometry."""

    if instance_count < 1:
        raise ValueError("instance_count must be positive")
    prototype_indices = np.zeros(instance_count, np.uint64)
    translations = np.zeros((instance_count, 3), np.float32)
    translations[:, 0] = np.arange(instance_count, dtype=np.float32)
    value = _core.instance_set(
        np.array([1], np.uint64),
        prototype_indices,
        translations,
    )
    no_payload = np.iinfo(np.uint64).max
    scene = _core.scene_graph(
        ["Copies", "Prototype"],
        node_payload_kinds=["instances", "none"],
        node_payload_indices=np.array([0, no_payload], np.uint64),
        instances=[value],
    )
    payload_bytes = sum(
        np.asarray(getattr(value, name)).nbytes
        for name in (
            "prototype_nodes",
            "prototype_indices",
            "translations",
            "orientations",
            "scales",
            "ids",
            "invisible_ids",
            "invisible_mask",
        )
    )
    return scene, payload_bytes


def build_volume_fixture(directory: Path, *, vdb_size_bytes: int) -> Path:
    """Create a sparse dependency and a stage that only references its grid."""

    if vdb_size_bytes < 1:
        raise ValueError("vdb_size_bytes must be positive")
    vdb = directory / "large.vdb"
    with vdb.open("wb") as stream:
        stream.seek(vdb_size_bytes - 1)
        stream.write(b"\0")
    stage = directory / "large-volume.usda"
    stage.write_text(
        '''#usda 1.0
def Volume "Fog"
{
    rel field:density = </Fog/Grid>
    def OpenVDBAsset "Grid"
    {
        token fieldClass = "unknown"
        token fieldDataType = "float"
        token fieldName = "density"
        asset filePath = @large.vdb@
        token vectorDataRoleHint = "None"
    }
}
''',
        encoding="utf-8",
    )
    return stage


def _metrics(operation, *, runs: int) -> dict[str, float]:
    elapsed, traced_peak = measure(operation, runs)
    rss_peak = measure_in_process_rss(operation)
    return {
        "ms": elapsed * 1000,
        "traced_peak_mb": traced_peak / 1e6,
        "rss_peak_mb": rss_peak / 1e6,
    }


def run_benchmark(
    directory: str | os.PathLike[str],
    *,
    runs: int,
    instance_counts: tuple[int, ...],
    vdb_size_mib: int,
) -> list[dict[str, object]]:
    """Measure compact instancers and metadata-only OpenVDB resolution."""

    if runs < 1:
        raise ValueError("runs must be positive")
    if not instance_counts or any(count < 1 for count in instance_counts):
        raise ValueError("instance_counts must contain positive values")
    if vdb_size_mib < 1:
        raise ValueError("vdb_size_mib must be positive")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []

    for count in instance_counts:
        scene, payload_bytes = build_instance_scene(instance_count=count)
        path = root / f"instances-{count}.usda"

        def write() -> None:
            sceneio.write_scene(scene, path)

        def read():
            return sceneio.read_scene(path)

        def inspect():
            return sceneio.inspect(path)

        write()
        decoded = read()
        inspected = inspect()
        if (
            decoded.num_nodes != 2
            or decoded.num_instance_sets != 1
            or decoded.instance_set_at(0).num_instances != count
            or decoded.instance_set_at(0).num_prototypes != 1
            or inspected.metadata["num_instances"] != count
            or inspected.metadata["num_instance_prototypes"] != 1
        ):
            raise AssertionError("USD instance benchmark result differs")
        payload_mb = payload_bytes / 1e6
        results.append(
            {
                "case": "point_instancer",
                "instances": count,
                "prototypes": 1,
                "payload_mb": payload_mb,
                "file_mb": path.stat().st_size / 1e6,
                "write": _metrics(write, runs=runs),
                "full_read": _metrics(read, runs=runs),
                "inspect": _metrics(inspect, runs=runs),
            }
        )
        del decoded, inspected
        gc.collect()

    vdb_size_bytes = vdb_size_mib * 1024 * 1024
    volume_path = build_volume_fixture(root, vdb_size_bytes=vdb_size_bytes)

    def read_volume():
        return sceneio.read_scene(volume_path)

    def inspect_volume():
        return sceneio.inspect(volume_path)

    decoded_volume = read_volume()
    inspected_volume = inspect_volume()
    if (
        decoded_volume.num_volumes != 1
        or inspected_volume.metadata["num_volumes"] != 1
        or inspected_volume.metadata["dependencies"] != ("large.vdb",)
    ):
        raise AssertionError("USD volume benchmark result differs")
    results.append(
        {
            "case": "openvdb_dependency",
            "vdb_file_mb": vdb_size_bytes / 1e6,
            "stage_file_mb": volume_path.stat().st_size / 1e6,
            "full_read": _metrics(read_volume, runs=runs),
            "inspect": _metrics(inspect_volume, runs=runs),
        }
    )
    return results


def render_results(results: list[dict[str, object]]) -> str:
    return json.dumps(results, indent=2, sort_keys=True)


__all__ = [
    "build_instance_scene",
    "build_volume_fixture",
    "render_results",
    "run_benchmark",
]
