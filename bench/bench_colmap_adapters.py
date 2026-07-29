"""Focused mapped-read/stream-write benchmark for ``sceneio.colmap`` adapters."""

from __future__ import annotations

import argparse
import gc
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

import numpy as np

from sceneio.colmap import (
    MappingCamera,
    MappingImage,
    MappingInput,
    MegaLocArtifacts,
    MegaLocImage,
    read_mapping_input,
    read_megaloc_artifacts,
    write_mapping_input,
    write_megaloc_artifacts,
)


def _measure(operation, repeats: int) -> tuple[float, int]:
    samples = []
    peak = 0
    for _ in range(repeats):
        gc.collect()
        tracemalloc.start()
        start = time.perf_counter()
        value = operation()
        elapsed = time.perf_counter() - start
        _, sample_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak = max(peak, sample_peak)
        samples.append(elapsed)
        del value
    return statistics.median(samples), peak


def _line(
    name: str,
    path: Path,
    operation,
    repeats: int,
) -> str:
    elapsed, peak = _measure(operation, repeats)
    size = path.stat().st_size
    throughput = size / elapsed / 1_000_000
    return (
        f"{name:24s} {throughput:10.1f} MB/s  "
        f"{elapsed * 1000:9.3f} ms  traced peak {peak / 1_000_000:7.3f} MB"
    )


def run(*, rows: int, repeats: int) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="sceneio-colmap-bench-") as raw_root:
        root = Path(raw_root)
        keypoints = np.arange(rows * 2, dtype=np.float32).reshape(rows, 2)
        mapping = MappingInput(
            2,
            (
                MappingCamera(
                    1,
                    1,
                    4096,
                    2160,
                    np.array([2000, 2000, 2048, 1080], dtype=np.float64),
                ),
            ),
            (MappingImage(1, 1, 1, "frame.png", keypoints),),
            (),
        )
        mapping_path = root / "mapping.pcmapin"
        write_mapping_input(mapping, mapping_path)

        descriptors = np.linspace(
            -1,
            1,
            rows * 2,
            dtype=np.float32,
        ).reshape(1, rows * 2)
        megaloc = MegaLocArtifacts(
            root,
            (MegaLocImage(1, "frame.png", "images/frame.png"),),
            (),
            descriptors,
            False,
            {"benchmark": True},
        )
        megaloc_root = root / "megaloc"
        write_megaloc_artifacts(megaloc, megaloc_root)
        descriptor_path = megaloc_root / "descriptors.f32"

        return [
            _line(
                "MappingInput mapped read",
                mapping_path,
                lambda: read_mapping_input(mapping_path),
                repeats,
            ),
            _line(
                "MappingInput stream write",
                mapping_path,
                lambda: write_mapping_input(mapping, root / "mapping-out.pcmapin"),
                repeats,
            ),
            _line(
                "MegaLoc mapped read",
                descriptor_path,
                lambda: read_megaloc_artifacts(megaloc_root),
                repeats,
            ),
            _line(
                "MegaLoc stream write",
                descriptor_path,
                lambda: write_megaloc_artifacts(
                    megaloc,
                    root / "megaloc-out",
                    overwrite=True,
                ),
                repeats,
            ),
        ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.rows <= 0 or args.repeats <= 0:
        parser.error("--rows and --repeats must be positive")
    for result in run(rows=args.rows, repeats=args.repeats):
        print(result)


if __name__ == "__main__":
    main()
