from __future__ import annotations

import numpy as np
import pytest

from bench.io_bench import e57_multiscan
from sceneio import _core


def _typed_fc3_available() -> bool:
    return all(
        getattr(_core, name, None) is not None
        for name in ("point_scan", "scan_set")
    )


def test_e57_multiscan_fixture_is_deterministic():
    first = e57_multiscan.build_payloads(scale=0.01, scan_count=2)
    second = e57_multiscan.build_payloads(scale=0.01, scan_count=2)
    assert len(first) == len(second) == 2
    for left, right in zip(first, second, strict=True):
        for name in (
            "positions",
            "colors",
            "intensity",
            "invalid_states",
            "row_indices",
            "column_indices",
            "viewpoint",
        ):
            np.testing.assert_array_equal(
                getattr(left, name), getattr(right, name)
            )
        assert left.scan_id == right.scan_id
        assert left.name == right.name
        assert left.valid_count < left.stored_count


def test_e57_multiscan_pye57_oracle_roundtrip(tmp_path):
    pytest.importorskip("pye57")
    payloads = e57_multiscan.build_payloads(scale=0.01, scan_count=2)
    path = tmp_path / "oracle.e57"
    e57_multiscan.oracle_write(payloads, path)
    observed = e57_multiscan.oracle_read(path)
    e57_multiscan._assert_oracle_scans(observed, payloads)
    headers = e57_multiscan.oracle_inspect(path)
    assert len(headers) == 2
    assert [row["stored_count"] for row in headers] == [
        item.stored_count for item in payloads
    ]
    assert all("cartesianX" in row["fields"] for row in headers)
    assert all("rowIndex" in row["fields"] for row in headers)


@pytest.mark.skipif(
    not _typed_fc3_available(),
    reason="FC3 typed PointScan/ScanSet records are not built yet",
)
def test_e57_multiscan_benchmark_smoke(tmp_path):
    pytest.importorskip("pye57")
    result = e57_multiscan.run_benchmark(
        tmp_path,
        runs=1,
        scale=0.01,
        scan_count=2,
    )
    assert result["schema_version"] == "e57-multiscan-benchmark-v1"
    assert result["fixture"]["scan_count"] == 2
    assert result["files"]["native_bytes"] > 0
    assert result["files"]["oracle_bytes"] > 0
    assert result["selection"]["stored_points"] > 0
    assert result["inspect_provider"] in {"sceneio", "pye57-header"}
    for metrics in result["metrics"].values():
        assert metrics["ms"] >= 0
        assert metrics["traced_peak_mb"] >= 0
        assert metrics["rss_peak_mb"] >= 0
