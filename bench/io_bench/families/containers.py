"""Path-native benchmark specifications for HDF5 and hloc stores."""

from __future__ import annotations

import numpy as np

import sceneio
from bench.io_bench.fixtures.containers import (
    _hdf5_fixture,
    _hloc_feature_fixture,
    _hloc_match_fixture,
)
from bench.io_bench.model import PathSpec
from bench.io_bench.oracles.containers import (
    H5PY_AVAILABLE,
    ZARR_AVAILABLE,
    _hdf5_oracle_read,
    _hdf5_oracle_write,
    _hloc_features_oracle_read,
    _hloc_features_oracle_write,
    _hloc_matches_oracle_read,
    _hloc_matches_oracle_write,
    _zarr_oracle_read,
    _zarr_oracle_write,
)


def _assert_tensor_dict(actual, expected) -> None:
    assert actual.attrs == expected["attrs"]
    assert set(actual.keys()) == set(expected["arrays"])
    for name, value in expected["arrays"].items():
        np.testing.assert_array_equal(actual[name], value)


def _assert_tensor_payload(actual, expected) -> None:
    assert actual["attrs"] == expected["attrs"]
    assert set(actual["arrays"]) == set(expected["arrays"])
    for name, value in expected["arrays"].items():
        np.testing.assert_array_equal(actual["arrays"][name], value)


def _assert_feature_store(actual, expected) -> None:
    assert set(actual) == set(expected)
    for name, values in expected.items():
        feature = actual[name]
        np.testing.assert_array_equal(feature.keypoints, values["keypoints"])
        np.testing.assert_array_equal(
            feature.descriptors,
            values["descriptors"],
        )
        np.testing.assert_array_equal(feature.scores, values["scores"])
        assert feature.image_size == values["image_size"].tolist()
        assert actual.uncertainties[name] == values["uncertainty"]


def _assert_feature_payload(actual, expected) -> None:
    assert set(actual) == set(expected)
    for name, values in expected.items():
        for field in ("keypoints", "descriptors", "scores", "image_size"):
            np.testing.assert_array_equal(
                actual[name][field],
                values[field],
            )
        assert actual[name]["uncertainty"] == values["uncertainty"]


def _assert_match_store(actual, expected) -> None:
    assert set(actual.pair_names) == set(expected)
    for index, pair in enumerate(actual.pair_names):
        values = expected[pair]
        assert actual.source_keypoint_counts[index] == len(values["matches0"])
        begin = int(actual.graph.match_offsets[index])
        end = int(actual.graph.match_offsets[index + 1])
        sparse = np.asarray(actual.graph.matches)[begin:end]
        dense = np.full(len(values["matches0"]), -1, dtype=np.int64)
        dense[sparse[:, 0]] = sparse[:, 1]
        np.testing.assert_array_equal(dense, values["matches0"])
        expected_scores = values["matching_scores0"]
        if expected_scores is not None:
            dense_scores = np.zeros(len(dense), dtype=np.float32)
            dense_scores[sparse[:, 0]] = np.asarray(actual.graph.scores)[
                begin:end
            ]
            np.testing.assert_array_equal(dense_scores, expected_scores)


def _assert_match_payload(actual, expected) -> None:
    assert set(actual) == set(expected)
    for pair, values in expected.items():
        np.testing.assert_array_equal(
            actual[pair]["matches0"],
            values["matches0"],
        )
        np.testing.assert_array_equal(
            actual[pair]["matching_scores0"],
            values["matching_scores0"],
        )


def _tensor_payload_nbytes(_record, payload) -> int:
    return sum(value.nbytes for value in payload["arrays"].values())


def _feature_payload_nbytes(_record, payload) -> int:
    return sum(
        sum(
            values[name].nbytes
            for name in ("keypoints", "descriptors", "scores", "image_size")
        )
        for values in payload.values()
    )


def _match_payload_nbytes(_record, payload) -> int:
    return sum(
        values["matches0"].nbytes + values["matching_scores0"].nbytes
        for values in payload.values()
    )


def _write(value, path, format_id: str) -> None:
    sceneio.write(value, path, format=format_id)


def _read(path, format_id: str):
    return sceneio.read(path, format=format_id)


def _partial_hdf5(path):
    return sceneio.read_partial(
        path,
        format="hdf5",
        tensors=("ids",),
    )


def _partial_zarr(path):
    return sceneio.read_partial(
        path,
        format="zarr",
        tensors=("ids",),
    )


def _assert_partial_hdf5(actual, payload) -> None:
    assert actual.keys() == ["ids"]
    np.testing.assert_array_equal(actual["ids"], payload["arrays"]["ids"])


def build_container_specs(scale):
    hdf5_write = _hdf5_oracle_write if H5PY_AVAILABLE else None
    hdf5_read = _hdf5_oracle_read if H5PY_AVAILABLE else None
    feature_write = (
        _hloc_features_oracle_write if H5PY_AVAILABLE else None
    )
    feature_read = _hloc_features_oracle_read if H5PY_AVAILABLE else None
    match_write = _hloc_matches_oracle_write if H5PY_AVAILABLE else None
    match_read = _hloc_matches_oracle_read if H5PY_AVAILABLE else None
    zarr_write = _zarr_oracle_write if ZARR_AVAILABLE else None
    zarr_read = _zarr_oracle_read if ZARR_AVAILABLE else None
    return [
        PathSpec(
            "hdf5",
            ".h5",
            lambda: _hdf5_fixture(scale),
            lambda value, path: _write(value, path, "hdf5"),
            lambda path: _read(path, "hdf5"),
            hdf5_write,
            hdf5_read,
            _tensor_payload_nbytes,
            _assert_tensor_dict,
            _assert_tensor_payload,
            _partial_hdf5,
            _assert_partial_hdf5,
        ),
        PathSpec(
            "hloc_features",
            ".h5",
            lambda: _hloc_feature_fixture(scale),
            lambda value, path: _write(value, path, "hloc_features"),
            lambda path: _read(path, "hloc_features"),
            feature_write,
            feature_read,
            _feature_payload_nbytes,
            _assert_feature_store,
            _assert_feature_payload,
        ),
        PathSpec(
            "hloc_matches",
            ".h5",
            lambda: _hloc_match_fixture(scale),
            lambda value, path: _write(value, path, "hloc_matches"),
            lambda path: _read(path, "hloc_matches"),
            match_write,
            match_read,
            _match_payload_nbytes,
            _assert_match_store,
            _assert_match_payload,
        ),
        PathSpec(
            "zarr",
            ".zarr",
            lambda: _hdf5_fixture(scale),
            lambda value, path: _write(value, path, "zarr"),
            lambda path: _read(path, "zarr"),
            zarr_write,
            zarr_read,
            _tensor_payload_nbytes,
            _assert_tensor_dict,
            _assert_tensor_payload,
            _partial_zarr,
            _assert_partial_hdf5,
        ),
    ]


__all__ = ["build_container_specs"]
