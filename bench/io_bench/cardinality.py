"""Supplemental container-cardinality benchmarks."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

import sceneio


def _median_ms(callback: Callable[[], object], runs: int) -> float:
    samples: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        callback()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def run_hdf5_cardinality(
    *,
    dataset_count: int = 5_000,
    group_count: int = 50,
    runs: int = 5,
) -> dict[str, Any]:
    """Measure selected and metadata-only access with many HDF5 objects."""

    if dataset_count < 1:
        raise ValueError("dataset_count must be positive")
    if group_count < 1 or group_count > dataset_count:
        raise ValueError("group_count must be between 1 and dataset_count")
    if runs < 1:
        raise ValueError("runs must be positive")

    import h5py

    with tempfile.TemporaryDirectory(prefix="sceneio-hdf5-cardinality-") as directory:
        path = Path(directory) / "many.h5"
        with h5py.File(path, "w") as handle:
            for index in range(dataset_count):
                group_index = index % group_count
                handle.create_dataset(
                    f"group-{group_index:04d}/value-{index:08d}",
                    data=np.int32(index),
                )
        selected_name = (
            f"group-{(dataset_count - 1) % group_count:04d}/"
            f"value-{dataset_count - 1:08d}"
        )

        def selected_read():
            value = sceneio.read_partial(
                path,
                format="hdf5",
                tensors=(selected_name,),
            )
            if int(value[selected_name]) != dataset_count - 1:
                raise AssertionError("SceneIO selected-read value mismatch")
            return value

        def inspect_all():
            inspection = sceneio.inspect(path, format="hdf5")
            if inspection.count != dataset_count:
                raise AssertionError("SceneIO inspection count mismatch")
            return inspection

        def direct_read():
            with h5py.File(path, "r") as handle:
                value = int(handle[selected_name][...])
            if value != dataset_count - 1:
                raise AssertionError("h5py selected-read value mismatch")
            return value

        result = {
            "dataset_count": dataset_count,
            "group_count": group_count,
            "runs": runs,
            "file_mb": path.stat().st_size / 1_000_000.0,
            "selected_name": selected_name,
            "sceneio_partial_ms": _median_ms(selected_read, runs),
            "sceneio_inspect_ms": _median_ms(inspect_all, runs),
            "h5py_direct_ms": _median_ms(direct_read, runs),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure SceneIO HDF5 scaling with many datasets",
    )
    parser.add_argument("--datasets", type=int, default=5_000)
    parser.add_argument("--groups", type=int, default=50)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = run_hdf5_cardinality(
        dataset_count=args.datasets,
        group_count=args.groups,
        runs=args.runs,
    )
    print(
        "datasets={dataset_count} groups={group_count} fileMB={file_mb:.3f} "
        "partial_ms={sceneio_partial_ms:.3f} "
        "inspect_ms={sceneio_inspect_ms:.3f} "
        "h5py_ms={h5py_direct_ms:.3f}".format_map(result)
    )
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


__all__ = ["main", "run_hdf5_cardinality"]
