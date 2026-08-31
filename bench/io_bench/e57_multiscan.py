"""FC3 E57 scan-set benchmark and provider differential.

The ordinary ``e57`` row uses the canonical ``ScanSet`` path. This module adds
stored-row selection and detailed provider comparisons that do not fit the
ordinary ``PathSpec`` interface.

The fixture is deterministic and generated in memory.  pye57/libE57Format is
used as the format oracle: SceneIO output is reopened by pye57, and a pye57
output is reopened by SceneIO.  No fixture bytes are checked into the
repository.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

import sceneio
from bench.io_bench.measure import measure, measure_in_process_rss
from sceneio import _core


@dataclass(frozen=True)
class E57ScanPayload:
    """Canonical arrays and pose used by both providers."""

    positions: np.ndarray
    colors: np.ndarray
    intensity: np.ndarray
    invalid_states: np.ndarray
    row_indices: np.ndarray
    column_indices: np.ndarray
    viewpoint: np.ndarray
    scan_id: int
    name: str
    row_minimum: int
    row_maximum: int
    column_minimum: int
    column_maximum: int

    @property
    def stored_count(self) -> int:
        return int(self.positions.shape[0])

    @property
    def valid_count(self) -> int:
        return int(np.count_nonzero(self.invalid_states == 0))

    @property
    def logical_bytes(self) -> int:
        return int(
            sum(
                value.nbytes
                for value in (
                    self.positions,
                    self.colors,
                    self.intensity,
                    self.invalid_states,
                    self.row_indices,
                    self.column_indices,
                    self.viewpoint,
                )
            )
        )


@dataclass(frozen=True)
class E57MultiScanFixture:
    """Canonical record plus payloads for a deterministic multi-scan case."""

    record: Any
    scans: tuple[E57ScanPayload, ...]

    @property
    def stored_count(self) -> int:
        return sum(scan.stored_count for scan in self.scans)

    @property
    def logical_bytes(self) -> int:
        return sum(scan.logical_bytes for scan in self.scans)


def build_payloads(
    scale: float = 1.0,
    *,
    scan_count: int = 3,
) -> tuple[E57ScanPayload, ...]:
    """Build deterministic Cartesian scans without requiring the FC3 record."""

    if scale <= 0:
        raise ValueError("scale must be positive")
    if scan_count < 1:
        raise ValueError("scan_count must be positive")
    count = max(32, int(4096 * scale))
    scans: list[E57ScanPayload] = []
    for scan_index in range(scan_count):
        sample = np.arange(count, dtype=np.float32)
        offset = np.float32(scan_index * 0.25)
        positions = np.column_stack(
            (
                sample / np.float32(8) + offset,
                np.sin(sample / np.float32(257) + offset),
                np.cos(sample / np.float32(509) - offset),
            )
        ).astype(np.float32, copy=False)
        colors = np.column_stack(
            (
                (np.arange(count, dtype=np.uint32) + scan_index) % 251,
                (np.arange(count, dtype=np.uint32) * 3 + scan_index) % 253,
                (np.arange(count, dtype=np.uint32) * 7 + scan_index) % 255,
            )
        ).astype(np.uint8, copy=False)
        intensity = np.linspace(
            -2 + scan_index,
            3 + scan_index,
            count,
            dtype=np.float32,
        )
        invalid_states = np.zeros(count, dtype=np.uint8)
        invalid = np.arange(count) % (19 + scan_index)
        invalid_states[invalid == 0] = np.uint8(1 + scan_index % 2)
        # Keep at least one valid point even for a future tiny-count change.
        invalid_states[0] = 0

        grid_width = max(1, math.ceil(math.sqrt(count * 1.25)))
        row_indices = (np.arange(count, dtype=np.int64) // grid_width).astype(
            np.int64,
            copy=False,
        )
        column_indices = (
            np.arange(count, dtype=np.int64) % grid_width
        ).astype(np.int64, copy=False)
        row_minimum = 0
        row_maximum = int(row_indices.max(initial=0))
        column_minimum = 0
        column_maximum = int(column_indices.max(initial=0))

        angle = (scan_index + 1) * math.pi / 8.0
        viewpoint = np.array(
            [
                1.25 * scan_index,
                -2.5 + 0.5 * scan_index,
                3.75 - 0.25 * scan_index,
                math.cos(angle / 2.0),
                0.0,
                math.sin(angle / 2.0),
                0.0,
            ],
            dtype=np.float64,
        )
        scans.append(
            E57ScanPayload(
                positions=positions,
                colors=colors,
                intensity=intensity,
                invalid_states=invalid_states,
                row_indices=row_indices,
                column_indices=column_indices,
                viewpoint=viewpoint,
                # E57 has an ordered scan index but no portable scan-id field;
                # use that stable index as the record identifier.
                scan_id=scan_index,
                name=f"sceneio-benchmark-{scan_index}",
                row_minimum=row_minimum,
                row_maximum=row_maximum,
                column_minimum=column_minimum,
                column_maximum=column_maximum,
            )
        )
    return tuple(scans)


def build_fixture(
    scale: float = 1.0,
    *,
    scan_count: int = 3,
) -> E57MultiScanFixture:
    """Build the canonical ``ScanSet`` and its payload description."""

    point_scan = getattr(_core, "point_scan", None)
    scan_set = getattr(_core, "scan_set", None)
    if point_scan is None or scan_set is None:
        raise RuntimeError(
            "FC3 E57 benchmark requires _core.point_scan and _core.scan_set"
        )
    scans = build_payloads(scale, scan_count=scan_count)
    point_scans = []
    for payload in scans:
        cloud = _core.point_cloud(
            payload.positions,
            colors=payload.colors,
            intensity=payload.intensity,
        )
        point_scans.append(
            point_scan(
                cloud,
                scan_id=payload.scan_id,
                invalid_states=payload.invalid_states,
                row_indices=payload.row_indices,
                column_indices=payload.column_indices,
                row_minimum=payload.row_minimum,
                row_maximum=payload.row_maximum,
                column_minimum=payload.column_minimum,
                column_maximum=payload.column_maximum,
                name=payload.name,
                guid="",
                # pye57 always authors acquisitionStart; a represented zero
                # keeps the presence contract exact in both directions.
                timestamp=0.0,
                viewpoint=payload.viewpoint,
            )
        )
    return E57MultiScanFixture(scan_set(point_scans), scans)


def _pye57():
    try:
        import pye57
    except ModuleNotFoundError:
        raise RuntimeError(
            "E57 benchmark oracle requires the optional pye57 package"
        ) from None
    return pye57


def _payload_data(payload: E57ScanPayload) -> dict[str, np.ndarray]:
    return {
        "cartesianX": payload.positions[:, 0],
        "cartesianY": payload.positions[:, 1],
        "cartesianZ": payload.positions[:, 2],
        "colorRed": payload.colors[:, 0],
        "colorGreen": payload.colors[:, 1],
        "colorBlue": payload.colors[:, 2],
        "intensity": payload.intensity,
        "cartesianInvalidState": payload.invalid_states,
        "rowIndex": payload.row_indices,
        "columnIndex": payload.column_indices,
    }


def oracle_write(payloads: tuple[E57ScanPayload, ...], path: str | Path) -> None:
    """Write the same payload using pye57/libE57Format."""

    pye57 = _pye57()
    with pye57.E57(str(path), mode="w") as destination:
        for payload in payloads:
            destination.write_scan_raw(
                _payload_data(payload),
                name=payload.name,
                translation=payload.viewpoint[:3],
                rotation=payload.viewpoint[3:],
            )


def _header_pose(header) -> np.ndarray:
    return np.concatenate(
        (
            np.asarray(header.translation, dtype=np.float64),
            np.asarray(header.rotation, dtype=np.float64),
        )
    )


def oracle_read(path: str | Path) -> tuple[dict[str, np.ndarray], ...]:
    """Read every raw scan through pye57 for differential verification."""

    pye57 = _pye57()
    scans: list[dict[str, np.ndarray]] = []
    with pye57.E57(str(path)) as source:
        for scan_index in range(source.scan_count):
            raw = source.read_scan_raw(scan_index)
            header = source.get_header(scan_index)
            scans.append(
                {
                    "positions": np.column_stack(
                        (
                            raw["cartesianX"],
                            raw["cartesianY"],
                            raw["cartesianZ"],
                        )
                    ).astype(np.float32, copy=False),
                    "colors": np.column_stack(
                        (
                            raw["colorRed"],
                            raw["colorGreen"],
                            raw["colorBlue"],
                        )
                    ).astype(np.uint8, copy=False),
                    "intensity": np.asarray(
                        raw["intensity"], dtype=np.float32
                    ),
                    "invalid_states": np.asarray(
                        raw["cartesianInvalidState"], dtype=np.uint8
                    ),
                    "row_indices": np.asarray(
                        raw["rowIndex"], dtype=np.int64
                    ),
                    "column_indices": np.asarray(
                        raw["columnIndex"], dtype=np.int64
                    ),
                    "viewpoint": _header_pose(header),
                }
            )
    return tuple(scans)


def oracle_inspect(path: str | Path) -> tuple[dict[str, object], ...]:
    """Inspect E57 headers without reading point payloads."""

    pye57 = _pye57()
    result: list[dict[str, object]] = []
    with pye57.E57(str(path)) as source:
        for scan_index in range(source.scan_count):
            header = source.get_header(scan_index)
            result.append(
                {
                    "scan_index": scan_index,
                    "stored_count": int(header.point_count),
                    "fields": tuple(sorted(header.point_fields)),
                    "row_minimum": int(header.rowMinimum),
                    "row_maximum": int(header.rowMaximum),
                    "column_minimum": int(header.columnMinimum),
                    "column_maximum": int(header.columnMaximum),
                    "viewpoint": _header_pose(header),
                }
            )
    return tuple(result)


def _write(value, path: Path) -> None:
    sceneio.write(value, path, format="e57")


def _read_scans(path: Path):
    return sceneio.read(path, format="e57")


def _read_scan(path: Path, scan_index: int, stored_point_range):
    return sceneio.read_e57_scan(
        path,
        scan_index=scan_index,
        stored_point_range=stored_point_range,
    )


def _inspect(path: Path):
    return sceneio.inspect(path, format="e57"), "sceneio"


def _scans(value) -> tuple[Any, ...]:
    scans = getattr(value, "scans", None)
    if scans is None:
        raise AssertionError("ScanSet does not expose scans")
    return tuple(scans)


def _scan_cloud(scan):
    for name in ("point_cloud", "cloud"):
        value = getattr(scan, name, None)
        if value is not None and hasattr(value, "positions"):
            return value
    raise AssertionError("PointScan does not expose its PointCloud")


def _scan_array(scan, name: str):
    value = getattr(scan, name, None)
    return None if value is None else np.asarray(value)


def _scan_viewpoint(scan) -> np.ndarray:
    value = getattr(scan, "viewpoint", None)
    if value is None:
        raise AssertionError("PointScan does not expose viewpoint")
    return np.asarray(value, dtype=np.float64)


def _assert_scan(scan, expected: E57ScanPayload) -> None:
    cloud = _scan_cloud(scan)
    assert int(scan.scan_id) == expected.scan_id
    assert str(scan.name) == expected.name
    assert bool(scan.has_invalid_states)
    assert bool(scan.has_row_column_indices)
    assert scan.pose_convention == "scan_to_reference"
    assert scan.quaternion_order == "wxyz"
    assert int(scan.row_minimum) == expected.row_minimum
    assert int(scan.row_maximum) == expected.row_maximum
    assert int(scan.column_minimum) == expected.column_minimum
    assert int(scan.column_maximum) == expected.column_maximum
    invalid = _scan_array(scan, "invalid_states")
    if invalid is None:
        raise AssertionError("E57 scan lost invalid states")
    np.testing.assert_array_equal(invalid, expected.invalid_states)
    valid = expected.invalid_states == 0
    np.testing.assert_array_equal(
        np.asarray(cloud.positions)[valid], expected.positions[valid]
    )
    np.testing.assert_array_equal(np.asarray(cloud.colors), expected.colors)
    np.testing.assert_array_equal(
        np.asarray(cloud.intensities), expected.intensity
    )
    np.testing.assert_array_equal(
        _scan_array(scan, "row_indices"), expected.row_indices
    )
    np.testing.assert_array_equal(
        _scan_array(scan, "column_indices"), expected.column_indices
    )
    np.testing.assert_allclose(_scan_viewpoint(scan), expected.viewpoint, rtol=0, atol=0)
    projected = scan.valid_point_cloud()
    np.testing.assert_array_equal(
        np.asarray(projected.positions), expected.positions[valid]
    )
    np.testing.assert_allclose(
        np.asarray(projected.viewpoint), expected.viewpoint, rtol=0, atol=0
    )


def _assert_oracle_scans(
    actual: tuple[dict[str, np.ndarray], ...],
    expected: tuple[E57ScanPayload, ...],
) -> None:
    if len(actual) != len(expected):
        raise AssertionError("E57 oracle scan count differs")
    for observed, wanted in zip(actual, expected, strict=True):
        valid = wanted.invalid_states == 0
        np.testing.assert_array_equal(
            observed["positions"][valid], wanted.positions[valid]
        )
        np.testing.assert_array_equal(observed["colors"], wanted.colors)
        np.testing.assert_array_equal(observed["intensity"], wanted.intensity)
        np.testing.assert_array_equal(
            observed["invalid_states"], wanted.invalid_states
        )
        np.testing.assert_array_equal(
            observed["row_indices"], wanted.row_indices
        )
        np.testing.assert_array_equal(
            observed["column_indices"], wanted.column_indices
        )
        np.testing.assert_allclose(
            observed["viewpoint"], wanted.viewpoint, rtol=0, atol=0
        )


def _assert_oracle_headers(
    actual: tuple[dict[str, object], ...],
    expected: tuple[E57ScanPayload, ...],
) -> None:
    if len(actual) != len(expected):
        raise AssertionError("E57 oracle header count differs")
    for index, (observed, wanted) in enumerate(
        zip(actual, expected, strict=True)
    ):
        assert observed["scan_index"] == index
        assert observed["stored_count"] == wanted.stored_count
        assert observed["row_minimum"] == wanted.row_minimum
        assert observed["row_maximum"] == wanted.row_maximum
        assert observed["column_minimum"] == wanted.column_minimum
        assert observed["column_maximum"] == wanted.column_maximum
        np.testing.assert_allclose(
            observed["viewpoint"], wanted.viewpoint, rtol=0, atol=0
        )


def _assert_selected(scan, expected: E57ScanPayload, start: int, stop: int) -> None:
    cloud = _scan_cloud(scan)
    invalid = expected.invalid_states[start:stop]
    valid = invalid == 0
    np.testing.assert_array_equal(
        np.asarray(cloud.positions)[valid], expected.positions[start:stop][valid]
    )
    np.testing.assert_array_equal(
        np.asarray(cloud.colors), expected.colors[start:stop]
    )
    np.testing.assert_array_equal(
        np.asarray(cloud.intensities), expected.intensity[start:stop]
    )
    np.testing.assert_array_equal(
        _scan_array(scan, "invalid_states"), expected.invalid_states[start:stop]
    )
    np.testing.assert_array_equal(
        _scan_array(scan, "row_indices"), expected.row_indices[start:stop]
    )
    np.testing.assert_array_equal(
        _scan_array(scan, "column_indices"),
        expected.column_indices[start:stop],
    )


def _logical_slice_bytes(payload: E57ScanPayload, start: int, stop: int) -> int:
    return int(
        sum(
            value[start:stop].nbytes
            for value in (
                payload.positions,
                payload.colors,
                payload.intensity,
                payload.invalid_states,
                payload.row_indices,
                payload.column_indices,
            )
        )
    )


def _metrics(operation, *, runs: int) -> dict[str, float]:
    elapsed, traced_peak = measure(operation, runs)
    rss_peak = measure_in_process_rss(operation)
    return {
        "ms": elapsed * 1000,
        "traced_peak_mb": traced_peak / 1e6,
        "rss_peak_mb": rss_peak / 1e6,
    }


def _cold_cache_supported() -> bool:
    return hasattr(os, "posix_fadvise") and hasattr(
        os, "POSIX_FADV_DONTNEED"
    )


def _evict_file_cache(path: Path) -> bool:
    if not _cold_cache_supported():
        return False
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(descriptor)
    return True


def run_benchmark(
    directory: str | os.PathLike[str],
    *,
    runs: int = 3,
    scale: float = 1.0,
    scan_count: int = 3,
    selection_scan: int = 1,
    stored_point_range: tuple[int, int] | None = None,
    cold_cache: bool = False,
) -> dict[str, object]:
    """Measure E57 full/selected reads, write, and inspection.

    ``stored_point_range`` is a half-open range over stored rows, not valid
    points.  The result retains traced Python allocation and sampled RSS for
    every operation.  The benchmark does not claim bounded allocation for a
    provider that materializes a complete scan before slicing.
    """

    if runs < 1:
        raise ValueError("runs must be positive")
    fixture = build_fixture(scale, scan_count=scan_count)
    if not 0 <= selection_scan < len(fixture.scans):
        raise ValueError("selection_scan is outside the fixture")
    selected_payload = fixture.scans[selection_scan]
    if stored_point_range is None:
        start = max(1, selected_payload.stored_count // 3)
        stop = min(
            selected_payload.stored_count,
            start + max(8, selected_payload.stored_count // 10),
        )
        stored_point_range = (start, stop)
    start, stop = stored_point_range
    if not (0 <= start <= stop <= selected_payload.stored_count):
        raise ValueError("stored_point_range is outside the selected scan")

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    native_path = root / "e57-multiscan-native.e57"
    oracle_path = root / "e57-multiscan-oracle.e57"

    def native_write():
        _write(fixture.record, native_path)

    def oracle_write_operation():
        oracle_write(fixture.scans, oracle_path)

    native_write()
    oracle_write_operation()

    def native_full_read():
        if cold_cache:
            _evict_file_cache(native_path)
        return _read_scans(native_path)

    def oracle_full_read():
        if cold_cache:
            _evict_file_cache(oracle_path)
        return oracle_read(oracle_path)

    def native_selected_read():
        if cold_cache:
            _evict_file_cache(native_path)
        return _read_scan(
            native_path,
            selection_scan,
            stored_point_range,
        )

    def oracle_selected_read():
        if cold_cache:
            _evict_file_cache(oracle_path)
        return tuple(
            {
                name: value[start:stop]
                if isinstance(value, np.ndarray) and value.ndim > 0
                else value
                for name, value in scan.items()
            }
            for scan in oracle_read(oracle_path)[selection_scan : selection_scan + 1]
        )

    def native_inspect():
        if cold_cache:
            _evict_file_cache(native_path)
        return _inspect(native_path)

    metrics = {
        "write": _metrics(native_write, runs=runs),
        "oracle_write": _metrics(oracle_write_operation, runs=runs),
        "full_read": _metrics(native_full_read, runs=runs),
        "oracle_full_read": _metrics(oracle_full_read, runs=runs),
        "selected_read": _metrics(native_selected_read, runs=runs),
        "oracle_selected_read": _metrics(oracle_selected_read, runs=runs),
        "inspect": _metrics(native_inspect, runs=runs),
    }

    native_record = _read_scans(native_path)
    oracle_record = _read_scans(oracle_path)
    if len(_scans(native_record)) != len(fixture.scans):
        raise AssertionError("native output scan count differs")
    if len(_scans(oracle_record)) != len(fixture.scans):
        raise AssertionError("oracle output scan count differs")
    for native_scan, oracle_scan, expected in zip(
        _scans(native_record), _scans(oracle_record), fixture.scans, strict=True
    ):
        _assert_scan(native_scan, expected)
        _assert_scan(oracle_scan, expected)
    _assert_selected(
        _read_scan(native_path, selection_scan, stored_point_range),
        selected_payload,
        start,
        stop,
    )
    native_oracle = oracle_read(native_path)
    oracle_oracle = oracle_read(oracle_path)
    _assert_oracle_scans(native_oracle, fixture.scans)
    _assert_oracle_scans(oracle_oracle, fixture.scans)
    _assert_oracle_headers(oracle_inspect(native_path), fixture.scans)
    _assert_oracle_headers(oracle_inspect(oracle_path), fixture.scans)
    inspect_value = native_inspect()
    if (
        isinstance(inspect_value, tuple)
        and len(inspect_value) == 2
        and isinstance(inspect_value[1], str)
    ):
        inspect_provider = inspect_value[1]
    else:
        inspect_provider = "sceneio"

    selection_bytes = _logical_slice_bytes(selected_payload, start, stop)
    for operation, logical_bytes in (
        ("write", fixture.logical_bytes),
        ("oracle_write", fixture.logical_bytes),
        ("full_read", fixture.logical_bytes),
        ("oracle_full_read", fixture.logical_bytes),
        ("selected_read", selection_bytes),
        ("oracle_selected_read", selection_bytes),
    ):
        metrics[operation]["logical_mbps"] = logical_bytes / 1e6 / (
            metrics[operation]["ms"] / 1000
        )

    return {
        "schema_version": "e57-multiscan-benchmark-v1",
        "fixture": {
            "scan_count": len(fixture.scans),
            "stored_points": fixture.stored_count,
            "valid_points": sum(scan.valid_count for scan in fixture.scans),
            "logical_bytes": fixture.logical_bytes,
            "scale": scale,
        },
        "files": {
            "native_bytes": native_path.stat().st_size,
            "oracle_bytes": oracle_path.stat().st_size,
        },
        "selection": {
            "scan_index": selection_scan,
            "stored_point_range": [start, stop],
            "stored_points": stop - start,
        },
        "inspect_provider": inspect_provider,
        "cold_cache_requested": cold_cache,
        "cold_cache_supported": _cold_cache_supported(),
        "metrics": metrics,
    }


def render_results(result: dict[str, object]) -> str:
    """Render one benchmark result as stable JSON."""

    return json.dumps(result, indent=2, sort_keys=True, default=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("bench-out"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--scan-count", type=int, default=3)
    parser.add_argument("--cold-cache", action="store_true")
    args = parser.parse_args(argv)
    print(
        render_results(
            run_benchmark(
                args.directory,
                runs=args.runs,
                scale=args.scale,
                scan_count=args.scan_count,
                cold_cache=args.cold_cache,
            )
        )
    )
    gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "E57MultiScanFixture",
    "E57ScanPayload",
    "build_fixture",
    "build_payloads",
    "oracle_inspect",
    "oracle_read",
    "oracle_write",
    "render_results",
    "run_benchmark",
]
