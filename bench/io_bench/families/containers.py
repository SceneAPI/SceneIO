"""Path-native benchmark specifications for optional I/O providers."""

from __future__ import annotations

import numpy as np

import sceneio
from bench.io_bench.fixtures.containers import (
    _columnar_fixture,
    _e57_fixture,
    _hdf5_fixture,
    _hloc_feature_fixture,
    _hloc_match_fixture,
    _openvdb_fixture,
    _usd_fixture,
)
from bench.io_bench.fixtures.images import _img_u8
from bench.io_bench.model import PathSpec
from bench.io_bench.oracles.containers import (
    H5PY_AVAILABLE,
    PYARROW_AVAILABLE,
    PYE57_AVAILABLE,
    TINYUSDZ_AVAILABLE,
    TINYVDB_AVAILABLE,
    ZARR_AVAILABLE,
    _columnar_oracle_read,
    _columnar_oracle_write,
    _e57_oracle_read,
    _e57_oracle_write,
    _hdf5_oracle_read,
    _hdf5_oracle_write,
    _hloc_features_oracle_read,
    _hloc_features_oracle_write,
    _hloc_matches_oracle_read,
    _hloc_matches_oracle_write,
    _openvdb_oracle_read,
    _openvdb_oracle_write,
    _usd_oracle_read,
    _usd_oracle_write,
    _zarr_oracle_read,
    _zarr_oracle_write,
)
from bench.io_bench.oracles.images import PILImage


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
        graph_pairs = actual.correspondences.pairs
        if pair in graph_pairs:
            correspondences = graph_pairs[pair]
            source_column, target_column = 0, 1
        else:
            correspondences = graph_pairs[(pair[1], pair[0])]
            source_column, target_column = 1, 0
        sparse = np.asarray(correspondences.indices)
        dense = np.full(len(values["matches0"]), -1, dtype=np.int64)
        dense[sparse[:, source_column]] = sparse[:, target_column]
        np.testing.assert_array_equal(dense, values["matches0"])
        expected_scores = values["matching_scores0"]
        if expected_scores is not None:
            dense_scores = np.zeros(len(dense), dtype=np.float32)
            dense_scores[sparse[:, source_column]] = np.asarray(
                correspondences.scores
            )
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


def _partial_parquet(path):
    return sceneio.read_partial(
        path,
        format="parquet",
        tensors=("image_id", "xy"),
    )


def _assert_partial_parquet(actual, payload) -> None:
    assert actual.keys() == ["image_id", "xy"]
    for name in actual:
        np.testing.assert_array_equal(actual[name], payload["arrays"][name])


def _tiff_fixture(scale):
    side = max(1, int(1024 * scale**0.5))
    image, pixels = _img_u8(side, side)
    level = sceneio.RasterLevel(
        0,
        "YXC",
        pixels.shape,
        pixels.dtype.name,
        "image",
        image,
    )
    collection = sceneio.RasterCollection(
        (sceneio.RasterSeries(0, None, (level,)),)
    )
    return collection, pixels


def _tiff_oracle_write(array, path) -> None:
    PILImage.fromarray(array).save(path, format="TIFF", compression="raw")


def _tiff_oracle_read(path):
    with PILImage.open(path) as image:
        return np.asarray(image)


def _assert_tiff_collection(actual, expected) -> None:
    np.testing.assert_array_equal(actual.series[0].levels[0].array, expected)


def _assert_tiff_array(actual, expected) -> None:
    np.testing.assert_array_equal(actual, expected)


def _assert_e57_scan_set(actual, expected) -> None:
    assert actual.num_scans == 1
    scan = actual.scans[0]
    np.testing.assert_array_equal(scan.point_cloud.positions, expected["positions"])
    np.testing.assert_array_equal(scan.point_cloud.colors, expected["colors"])
    np.testing.assert_array_equal(scan.point_cloud.intensities, expected["intensity"])
    np.testing.assert_array_equal(scan.viewpoint, expected["viewpoint"])


def _assert_e57_payload(actual, expected) -> None:
    for name in ("positions", "colors", "intensity", "viewpoint"):
        np.testing.assert_array_equal(actual[name], expected[name])


def _sort_sparse(arrays):
    coords = np.asarray(arrays["coords"])
    order = np.lexsort((coords[:, 2], coords[:, 1], coords[:, 0]))
    return coords[order], np.asarray(arrays["values"])[order]


def _assert_sparse_tensor(actual, expected) -> None:
    actual_coords, actual_values = _sort_sparse(
        {"coords": actual["coords"], "values": actual["values"]}
    )
    expected_coords, expected_values = _sort_sparse(expected["arrays"])
    np.testing.assert_array_equal(actual_coords, expected_coords)
    assert actual_values.tobytes() == expected_values.tobytes()
    assert actual.attrs["name"] == expected["attrs"]["name"]


def _assert_sparse_payload(actual, expected) -> None:
    actual_coords, actual_values = _sort_sparse(actual["arrays"])
    expected_coords, expected_values = _sort_sparse(expected["arrays"])
    np.testing.assert_array_equal(actual_coords, expected_coords)
    assert actual_values.tobytes() == expected_values.tobytes()
    assert actual["attrs"] == expected["attrs"]


def _assert_usd_scene(actual, expected) -> None:
    assert actual.num_meshes == actual.num_mesh_primitives == 1
    assert actual.num_nodes == 1
    assert list(actual.node_names) == [expected["attrs"]["node_name"]]
    mesh = actual.mesh_primitive_at(0)
    for name, value in expected["arrays"].items():
        observed = np.asarray(getattr(mesh, name))
        assert observed.dtype == value.dtype
        assert observed.shape == value.shape
        assert observed.tobytes() == value.tobytes()


def _assert_usd_payload(actual, expected) -> None:
    assert actual["attrs"] == expected["attrs"]
    for name, value in expected["arrays"].items():
        observed = actual["arrays"][name]
        assert observed.dtype == value.dtype
        assert observed.shape == value.shape
        assert observed.tobytes() == value.tobytes()


def _mapping_nbytes(_record, payload) -> int:
    return sum(value.nbytes for value in payload["arrays"].values())


def _e57_nbytes(_record, payload) -> int:
    return sum(
        payload[name].nbytes
        for name in ("positions", "colors", "intensity", "viewpoint")
    )


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
    e57_write = _e57_oracle_write if PYE57_AVAILABLE else None
    e57_read = _e57_oracle_read if PYE57_AVAILABLE else None
    columnar_write = (
        _columnar_oracle_write if PYARROW_AVAILABLE else None
    )
    columnar_read = _columnar_oracle_read if PYARROW_AVAILABLE else None
    openvdb_write = (
        _openvdb_oracle_write if TINYVDB_AVAILABLE else None
    )
    openvdb_read = _openvdb_oracle_read if TINYVDB_AVAILABLE else None
    usd_write = _usd_oracle_write if TINYUSDZ_AVAILABLE else None
    usd_read = _usd_oracle_read if TINYUSDZ_AVAILABLE else None
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
        PathSpec(
            "tiff",
            ".tiff",
            lambda: _tiff_fixture(scale),
            lambda value, path: _write(value, path, "tiff"),
            lambda path: _read(path, "tiff"),
            (_tiff_oracle_write if PILImage else None),
            (_tiff_oracle_read if PILImage else None),
            lambda _record, payload: payload.nbytes,
            _assert_tiff_collection,
            _assert_tiff_array,
        ),
        PathSpec(
            "e57",
            ".e57",
            lambda: _e57_fixture(scale),
            lambda value, path: _write(value, path, "e57"),
            lambda path: _read(path, "e57"),
            e57_write,
            e57_read,
            _e57_nbytes,
            _assert_e57_scan_set,
            _assert_e57_payload,
        ),
        PathSpec(
            "parquet",
            ".parquet",
            lambda: _columnar_fixture(scale),
            lambda value, path: _write(value, path, "parquet"),
            lambda path: _read(path, "parquet"),
            (
                (
                    lambda payload, path: columnar_write(
                        payload, path, format_id="parquet"
                    )
                )
                if columnar_write
                else None
            ),
            (
                (
                    lambda path: columnar_read(path, format_id="parquet")
                )
                if columnar_read
                else None
            ),
            _mapping_nbytes,
            _assert_tensor_dict,
            _assert_tensor_payload,
            _partial_parquet,
            _assert_partial_parquet,
        ),
        PathSpec(
            "arrow_ipc",
            ".arrow",
            lambda: _columnar_fixture(scale),
            lambda value, path: _write(value, path, "arrow_ipc"),
            lambda path: _read(path, "arrow_ipc"),
            (
                (
                    lambda payload, path: columnar_write(
                        payload, path, format_id="arrow_ipc"
                    )
                )
                if columnar_write
                else None
            ),
            (
                (
                    lambda path: columnar_read(path, format_id="arrow_ipc")
                )
                if columnar_read
                else None
            ),
            _mapping_nbytes,
            _assert_tensor_dict,
            _assert_tensor_payload,
        ),
        PathSpec(
            "openvdb",
            ".vdb",
            lambda: _openvdb_fixture(scale),
            lambda value, path: _write(value, path, "openvdb"),
            lambda path: _read(path, "openvdb"),
            openvdb_write,
            openvdb_read,
            _mapping_nbytes,
            _assert_sparse_tensor,
            _assert_sparse_payload,
        ),
        PathSpec(
            "usd",
            ".usd",
            lambda: _usd_fixture(scale),
            lambda value, path: _write(value, path, "usd"),
            lambda path: _read(path, "usd"),
            usd_write,
            usd_read,
            _mapping_nbytes,
            _assert_usd_scene,
            _assert_usd_payload,
        ),
        PathSpec(
            "usdz",
            ".usdz",
            lambda: _usd_fixture(scale),
            lambda value, path: _write(value, path, "usdz"),
            lambda path: _read(path, "usdz"),
            usd_write,
            usd_read,
            _mapping_nbytes,
            _assert_usd_scene,
            _assert_usd_payload,
        ),
    ]


__all__ = ["build_container_specs"]
