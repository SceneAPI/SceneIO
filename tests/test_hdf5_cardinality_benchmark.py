from __future__ import annotations

import pytest

from bench.io_bench.cardinality import run_hdf5_cardinality


def test_hdf5_cardinality_benchmark_is_reproducible() -> None:
    result = run_hdf5_cardinality(
        dataset_count=16,
        group_count=4,
        runs=1,
    )
    assert result["dataset_count"] == 16
    assert result["group_count"] == 4
    assert result["selected_name"] == "group-0003/value-00000015"
    assert result["file_mb"] > 0
    assert result["sceneio_partial_ms"] > 0
    assert result["sceneio_inspect_ms"] > 0
    assert result["h5py_direct_ms"] > 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dataset_count": 0},
        {"dataset_count": 4, "group_count": 0},
        {"dataset_count": 4, "group_count": 5},
        {"runs": 0},
    ],
)
def test_hdf5_cardinality_benchmark_rejects_invalid_sizes(kwargs) -> None:
    with pytest.raises(ValueError):
        run_hdf5_cardinality(**kwargs)
