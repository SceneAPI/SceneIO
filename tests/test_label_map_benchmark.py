"""Smoke tests for the focused dense-label benchmark."""

from __future__ import annotations

import numpy as np
import pytest

from bench.io_bench.label_maps import label_map_fixture, run_benchmark
from bench.io_bench.memory_child import _execute_operation


def test_label_map_benchmark_fixture_is_deterministic() -> None:
    first = label_map_fixture(8)
    second = label_map_fixture(8)
    np.testing.assert_array_equal(first.class_ids, second.class_ids)
    assert first.class_ids.dtype == np.int32
    assert first.shape == (8, 8)
    assert first.taxonomy.identity == "sceneio.generated.label-benchmark"


@pytest.mark.parametrize("carrier", ["npz", "zarr"])
def test_label_map_benchmark_runs_oracle_comparison(tmp_path, carrier: str) -> None:
    if carrier == "zarr":
        pytest.importorskip("zarr")
    [result] = run_benchmark(
        tmp_path,
        side=16,
        runs=1,
        carriers=(carrier,),
        chunk_side=8,
        rss_samples=0,
    )
    assert result["carrier"].startswith(carrier)
    assert result["schema"] == "sceneio.label_map/1"
    assert result["logical_mib"] == 16 * 16 * 4 / (1024 * 1024)
    for name, value in result.items():
        if name.endswith(("_ms", "_mbps")):
            assert value > 0
        elif name.endswith("_traced_peak_mib"):
            assert value >= 0


def test_memory_child_dispatches_typed_label_operations() -> None:
    calls = []

    class Facade:
        def read_label_map(self, path, *, format=None):
            calls.append(("read", path, format))
            return "read-result"

        def inspect_label_map(self, path, *, format=None):
            calls.append(("inspect", path, format))
            return "inspect-result"

    facade = Facade()
    assert _execute_operation(
        {
            "kind": "sceneio_read_label_map",
            "arguments": {"path": "labels.npz", "format": "npz"},
        },
        sceneio=facade,
        payload_bytes=0,
        allocation_headroom_bytes=0,
    ) == "read-result"
    assert _execute_operation(
        {
            "kind": "sceneio_inspect_label_map",
            "arguments": {"path": "labels.zarr", "format": "zarr"},
        },
        sceneio=facade,
        payload_bytes=0,
        allocation_headroom_bytes=0,
    ) == "inspect-result"
    assert calls == [
        ("read", "labels.npz", "npz"),
        ("inspect", "labels.zarr", "zarr"),
    ]
