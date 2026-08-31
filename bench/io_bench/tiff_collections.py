"""TIFF raster-collection selection benchmark.

The default deterministic fixture is a 64 MiB tiled uint16 ZYX stack.  The
benchmark compares SceneIO's Zarr-backed page/window selection with both a
full collection read and a direct tifffile full-decode-then-slice control.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import numpy as np
import tifffile

import sceneio
from bench.io_bench.measure import (
    measure,
    measure_fresh_process_rss,
    measure_in_process_rss,
)
from bench.io_bench.memory_protocol import MemoryCase, MemoryOperation


def build_values(shape: tuple[int, int, int]) -> np.ndarray:
    """Return a deterministic native uint16 ZYX fixture."""

    if len(shape) != 3 or any(dimension <= 0 for dimension in shape):
        raise ValueError("shape must contain three positive dimensions")
    return np.arange(np.prod(shape), dtype=np.uint16).reshape(shape)


def _metrics(operation, *, runs: int) -> dict[str, float]:
    elapsed, traced_peak = measure(operation, runs)
    rss_peak = measure_in_process_rss(operation)
    return {
        "ms": elapsed * 1000,
        "traced_peak_mb": traced_peak / 1e6,
        "rss_peak_mb": rss_peak / 1e6,
    }


def run_benchmark(
    directory: str | Path,
    *,
    runs: int = 3,
    shape: tuple[int, int, int] = (8, 2048, 2048),
    page_range: tuple[int, int] = (3, 4),
    window: tuple[int, int, int, int] = (256, 768, 512, 1024),
    tile: tuple[int, int] = (128, 128),
    fresh_rss_samples: int = 0,
    fresh_rss_timeout_seconds: float = 60.0,
) -> dict[str, object]:
    """Measure full, selected, control, and metadata-only TIFF operations."""

    if runs < 1:
        raise ValueError("runs must be positive")
    if fresh_rss_samples not in {0} and fresh_rss_samples < 3:
        raise ValueError("fresh_rss_samples must be zero or at least three")
    values = build_values(shape)
    page_start, page_stop = page_range
    row_start, row_stop, column_start, column_stop = window
    if not (0 <= page_start < page_stop <= shape[0]):
        raise ValueError("page_range is outside the fixture")
    if not (0 <= row_start < row_stop <= shape[1] and 0 <= column_start < column_stop <= shape[2]):
        raise ValueError("window is outside the fixture")

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "tiff-collection-selection.tif"
    tifffile.imwrite(
        path,
        values,
        photometric="minisblack",
        metadata={"axes": "ZYX"},
        tile=tile,
    )
    selection = np.s_[
        page_start:page_stop,
        row_start:row_stop,
        column_start:column_stop,
    ]
    expected = np.ascontiguousarray(values[selection])

    def full_read():
        return sceneio.read(path, format="tiff")

    def selected_read():
        return sceneio.read_tiff_collection(
            path,
            series_index=0,
            level_index=0,
            page_range=page_range,
            window=window,
        )

    def provider_full_then_slice():
        decoded = tifffile.imread(path)
        return np.ascontiguousarray(decoded[selection])

    def inspect_collection():
        return sceneio.inspect(path, format="tiff")

    metrics = {
        "full_read": _metrics(full_read, runs=runs),
        "selected_read": _metrics(selected_read, runs=runs),
        "provider_full_then_slice": _metrics(provider_full_then_slice, runs=runs),
        "inspect": _metrics(inspect_collection, runs=runs),
    }

    full = full_read().series_at(0).level_at(0).array
    selected = selected_read().series_at(0).level_at(0).array
    control = provider_full_then_slice()
    np.testing.assert_array_equal(full, values)
    np.testing.assert_array_equal(selected, expected)
    np.testing.assert_array_equal(control, expected)
    inspection = inspect_collection()
    if inspection.arrays[0].shape != shape:
        raise AssertionError("TIFF collection inspection changed fixture shape")

    selection_bytes = int(expected.nbytes)
    logical_bytes = int(values.nbytes)
    for operation, byte_count in (
        ("full_read", logical_bytes),
        ("selected_read", selection_bytes),
        ("provider_full_then_slice", selection_bytes),
    ):
        metrics[operation]["logical_mbps"] = byte_count / 1e6 / (metrics[operation]["ms"] / 1000)

    selected_peak = metrics["selected_read"]["traced_peak_mb"]
    control_peak = metrics["provider_full_then_slice"]["traced_peak_mb"]
    result = {
        "schema_version": "tiff-collection-benchmark-v1",
        "fixture": {
            "shape": list(shape),
            "dtype": "uint16",
            "axes": "ZYX",
            "logical_bytes": logical_bytes,
            "file_bytes": path.stat().st_size,
            "tile": list(tile),
        },
        "selection": {
            "page_range": list(page_range),
            "window": list(window),
            "shape": list(expected.shape),
            "logical_bytes": selection_bytes,
        },
        "metrics": metrics,
        "selection_advantage": {
            "traced_peak_ratio_vs_full_decode_control": (
                selected_peak / control_peak if control_peak else None
            ),
            "traced_peak_reduction_percent": (
                (1.0 - selected_peak / control_peak) * 100 if control_peak else None
            ),
        },
    }
    if fresh_rss_samples:
        resolved = str(path.resolve())
        result["fresh_process_rss"] = measure_fresh_process_rss(
            [
                MemoryCase(
                    "full_read",
                    path.stat().st_size,
                    MemoryOperation(
                        "sceneio_read",
                        {"path": resolved, "format": "tiff"},
                    ),
                ),
                MemoryCase(
                    "selected_read",
                    path.stat().st_size,
                    MemoryOperation(
                        "sceneio_read_tiff_collection",
                        {
                            "path": resolved,
                            "series_index": 0,
                            "level_index": 0,
                            "page_range": list(page_range),
                            "window": list(window),
                        },
                    ),
                ),
                MemoryCase(
                    "inspect",
                    path.stat().st_size,
                    MemoryOperation(
                        "sceneio_inspect",
                        {"path": resolved, "format": "tiff"},
                    ),
                ),
            ],
            samples=fresh_rss_samples,
            timeout_seconds=fresh_rss_timeout_seconds,
        )
    return result


def render_results(result: dict[str, object]) -> str:
    return json.dumps(result, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("bench-out"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--pages", type=int, default=8)
    parser.add_argument("--height", type=int, default=2048)
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--fresh-rss-samples", type=int, default=0)
    parser.add_argument(
        "--fresh-rss-timeout-seconds",
        type=float,
        default=60.0,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_benchmark(
        args.directory,
        runs=args.runs,
        shape=(args.pages, args.height, args.width),
        fresh_rss_samples=args.fresh_rss_samples,
        fresh_rss_timeout_seconds=args.fresh_rss_timeout_seconds,
    )
    rendered = render_results(result)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_values", "render_results", "run_benchmark"]
