from __future__ import annotations

import gc
import subprocess
import sys
import tracemalloc
from pathlib import Path

import h5py
import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import _hdf5 as hdf5_adapter


def _official_hloc_pair_name(name0: str, name1: str) -> str:
    """Mirror hloc.utils.parsers.names_to_pair's current default separator."""

    return "/".join((name0.replace("/", "-"), name1.replace("/", "-")))


def _feature(
    name: str,
    *,
    descriptor_dtype: np.dtype | type = np.float16,
) -> _core.FeatureSet:
    return _core.feature_set(
        np.array([[1.25, 2.5], [10.5, 20.75], [30.0, 40.0]], np.float32),
        np.arange(12, dtype=descriptor_dtype).reshape(3, 4),
        np.array([0.25, 0.5, 0.75], np.float32),
        image_name=name,
        image_size=(640, 480),
        pixel_center=(0.0, 0.0),
    )


def _match_store(*, mixed_scores: bool = False) -> sceneio.HlocMatchStore:
    image_names = ("db/a.jpg", "db/c.jpg", "query/b.jpg")
    pair_names = (
        ("query/b.jpg", "db/a.jpg"),
        ("db/c.jpg", "query/b.jpg"),
    )
    scores = np.array([0.5, 0.75, 0.25], np.float32)
    if mixed_scores:
        scores[:2] = 0
    graph = _core.match_graph(
        np.array([[1, 3], [2, 3]], np.uint32),
        np.array([0, 2, 3], np.uint64),
        np.array([[1, 0], [3, 2], [1, 4]], np.uint32),
        np.array([0, 0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        scores=scores,
        match_score_present=np.array(
            [0 if mixed_scores else 1, 1],
            np.uint8,
        ),
        match_present=np.ones(2, np.uint8),
        geometry_present=np.zeros(2, np.uint8),
    )
    return sceneio.HlocMatchStore(
        image_names,
        pair_names,
        (5, 3),
        ("int16", "int32"),
        (None if mixed_scores else "float16", "float32"),
        graph,
    )


def test_generic_hdf5_reads_independent_h5py_fixture(tmp_path: Path) -> None:
    path = tmp_path / "oracle.h5"
    expected_a = np.arange(24, dtype=np.float32).reshape(4, 6)
    expected_b = np.array([1, 5, 9], dtype=">i4")
    with h5py.File(path, "w") as handle:
        handle.attrs["producer"] = "independent-h5py"
        handle.create_dataset("dense/a", data=expected_a)
        handle.create_dataset("ids", data=expected_b)

    assert sceneio.detect(path) == "hdf5"
    decoded = sceneio.read(path)
    np.testing.assert_array_equal(decoded["dense/a"], expected_a)
    np.testing.assert_array_equal(decoded["ids"], expected_b)
    assert decoded["ids"].dtype == np.dtype(np.int32)
    assert decoded.attrs == {"producer": "independent-h5py"}
    path.unlink()
    gc.collect()
    np.testing.assert_array_equal(decoded["dense/a"], expected_a)


def test_hdf5_canonical_array_reuses_native_contiguous_storage() -> None:
    native = np.arange(24, dtype=np.float32).reshape(4, 6)
    assert hdf5_adapter._canonical_array(native, "native") is native

    strided = native[:, ::2]
    contiguous = hdf5_adapter._canonical_array(strided, "strided")
    assert contiguous.flags.c_contiguous
    assert not np.shares_memory(contiguous, strided)
    np.testing.assert_array_equal(contiguous, strided)

    big_endian = np.arange(8, dtype=">i4")
    converted = hdf5_adapter._canonical_array(big_endian, "big-endian")
    assert converted.dtype == np.dtype(np.int32)
    assert converted.flags.c_contiguous
    assert not np.shares_memory(converted, big_endian)
    np.testing.assert_array_equal(converted, np.arange(8, dtype=np.int32))


def test_generic_hdf5_write_is_h5py_ground_truth_and_partial(tmp_path: Path) -> None:
    path = tmp_path / "written.hdf5"
    value = _core.tensor_dict(
        {
            "dense/a": np.arange(30, dtype=np.float64).reshape(5, 6),
            "mask": np.array([True, False, True], dtype=np.bool_),
        },
        {"producer": "SceneIO", "profile": "numeric-v1"},
    )

    sceneio.write(value, path, format="hdf5")
    assert sceneio.detect(path) == "hdf5"
    with h5py.File(path, "r") as handle:
        np.testing.assert_array_equal(handle["dense/a"][...], value["dense/a"])
        np.testing.assert_array_equal(handle["mask"][...], value["mask"])
        assert handle.attrs["sceneio_format"] == "hdf5"
        assert handle.attrs["producer"] == "SceneIO"

    selected = sceneio.read_partial(path, tensors=("mask",))
    assert selected.keys() == ["mask"]
    np.testing.assert_array_equal(selected["mask"], value["mask"])
    sliced = sceneio.read_partial(path, slices={"dense/a": (1, 4)})
    np.testing.assert_array_equal(sliced["dense/a"], value["dense/a"][1:4])
    inspected = sceneio.inspect(path)
    assert inspected.count == 2
    assert {item.name for item in inspected.arrays} == {"dense/a", "mask"}


def test_hdf5_partial_read_does_not_materialize_unselected_dataset(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset(
            "large",
            shape=(32, 1024, 1024),
            dtype=np.float32,
            fillvalue=2.0,
        )
        handle.create_dataset("small", data=np.arange(8, dtype=np.int32))

    tracemalloc.start()
    selected = sceneio.read_partial(path, tensors=("small",), format="hdf5")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    np.testing.assert_array_equal(selected["small"], np.arange(8, dtype=np.int32))
    assert peak < 2 * 1024 * 1024


def test_hdf5_partial_read_does_not_walk_unselected_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "many-datasets.h5"
    with h5py.File(path, "w") as handle:
        for index in range(512):
            handle.create_dataset(
                f"group-{index // 64}/value-{index}",
                data=np.int32(index),
            )

    def fail_global_walk(*_args, **_kwargs):
        raise AssertionError("selected HDF5 read performed a global walk")

    monkeypatch.setattr(h5py.Group, "visititems_links", fail_global_walk)
    selected = sceneio.read_partial(
        path,
        format="hdf5",
        tensors=("group-7/value-511",),
    )
    assert selected.keys() == ["group-7/value-511"]
    assert int(selected["group-7/value-511"]) == 511


def test_hdf5_refuses_unrepresented_dataset_and_attribute_types(
    tmp_path: Path,
) -> None:
    string_path = tmp_path / "string.h5"
    with h5py.File(string_path, "w") as handle:
        handle.create_dataset("labels", data=np.asarray([b"a", b"b"]))
    with pytest.raises(sceneio.FormatError, match="unsupported"):
        sceneio.read(string_path, format="hdf5")
    with pytest.raises(sceneio.FormatError, match="unsupported"):
        sceneio.inspect(string_path, format="hdf5")

    attr_path = tmp_path / "numeric-attr.h5"
    with h5py.File(attr_path, "w") as handle:
        handle.attrs["count"] = 3
        handle.create_dataset("values", data=np.arange(2))
    with pytest.raises(sceneio.FormatError, match="string attribute"):
        sceneio.read(attr_path, format="hdf5")

    metadata_path = tmp_path / "metadata.h5"
    with h5py.File(metadata_path, "w") as handle:
        group = handle.create_group("nested")
        group.attrs["units"] = "pixels"
        values = group.create_dataset("values", data=np.arange(2))
        values.attrs["meaning"] = "unrepresented"
    for operation in (
        lambda: sceneio.read(metadata_path, format="hdf5"),
        lambda: sceneio.inspect(metadata_path, format="hdf5"),
        lambda: sceneio.read_partial(
            metadata_path,
            format="hdf5",
            tensors=("nested/values",),
        ),
    ):
        with pytest.raises(sceneio.FormatError, match="outside the file root"):
            operation()

    dataset_metadata_path = tmp_path / "dataset-metadata.h5"
    with h5py.File(dataset_metadata_path, "w") as handle:
        values = handle.create_dataset("values", data=np.arange(2))
        values.attrs["meaning"] = "unrepresented"
    for operation in (
        lambda: sceneio.read(dataset_metadata_path, format="hdf5"),
        lambda: sceneio.inspect(dataset_metadata_path, format="hdf5"),
        lambda: sceneio.read_partial(
            dataset_metadata_path,
            format="hdf5",
            tensors=("values",),
        ),
    ):
        with pytest.raises(sceneio.FormatError, match="unsupported attributes"):
            operation()

    schema_path = tmp_path / "future-schema.h5"
    with h5py.File(schema_path, "w") as handle:
        handle.attrs["sceneio_schema_version"] = np.uint32(2)
        handle.create_dataset("values", data=np.arange(2))
    with pytest.raises(sceneio.FormatError, match="must be the integer 1"):
        sceneio.read(schema_path, format="hdf5")

    declared_path = tmp_path / "declared-hloc.h5"
    with h5py.File(declared_path, "w") as handle:
        handle.attrs["sceneio_format"] = "hloc_features"
        handle.create_dataset("values", data=np.arange(2))
    with pytest.raises(sceneio.FormatError, match="not 'hdf5'"):
        sceneio.read(declared_path, format="hdf5")


def test_hdf5_full_reads_refuse_links_and_partial_validates_selected_paths(
    tmp_path: Path,
) -> None:
    linked = tmp_path / "linked.h5"
    with h5py.File(linked, "w") as handle:
        handle.create_dataset("values", data=np.arange(4))
        handle["alias"] = h5py.SoftLink("/values")
    for operation in (
        lambda: sceneio.read(linked, format="hdf5"),
        lambda: sceneio.inspect(linked, format="hdf5"),
    ):
        with pytest.raises(sceneio.FormatError, match="links are unsupported"):
            operation()
    selected = sceneio.read_partial(
        linked,
        format="hdf5",
        tensors=("values",),
    )
    np.testing.assert_array_equal(selected["values"], np.arange(4))
    with pytest.raises(sceneio.FormatError, match="links are unsupported"):
        sceneio.read_partial(
            linked,
            format="hdf5",
            tensors=("alias",),
        )

    aliased = tmp_path / "hard-linked.h5"
    with h5py.File(aliased, "w") as handle:
        values = handle.create_dataset("values", data=np.arange(4))
        handle["alias"] = values
    with pytest.raises(sceneio.FormatError, match="links are unsupported"):
        sceneio.read(aliased, format="hdf5")
    selected = sceneio.read_partial(
        aliased,
        format="hdf5",
        tensors=("values",),
    )
    np.testing.assert_array_equal(selected["values"], np.arange(4))
    with pytest.raises(sceneio.FormatError, match="links are unsupported"):
        sceneio.read_partial(
            aliased,
            format="hdf5",
            tensors=("values", "alias"),
        )

    source = tmp_path / "virtual-source.h5"
    virtual = tmp_path / "virtual.h5"
    with h5py.File(source, "w") as handle:
        handle.create_dataset("values", data=np.arange(4, dtype=np.float32))
    layout = h5py.VirtualLayout(shape=(4,), dtype=np.float32)
    layout[:] = h5py.VirtualSource(str(source), "values", shape=(4,))
    with h5py.File(virtual, "w") as handle:
        handle.create_virtual_dataset("values", layout)
    for operation in (
        lambda: sceneio.read(virtual, format="hdf5"),
        lambda: sceneio.inspect(virtual, format="hdf5"),
        lambda: sceneio.read_partial(
            virtual,
            format="hdf5",
            tensors=("values",),
        ),
    ):
        with pytest.raises(sceneio.FormatError, match="virtual datasets"):
            operation()


@pytest.mark.parametrize(
    "dtype",
    [np.uint8, np.int8, np.float16, np.float32, np.float64],
)
def test_native_feature_factory_preserves_hloc_descriptor_dtypes(dtype) -> None:
    feature = _feature("image.jpg", descriptor_dtype=dtype)
    assert feature.descriptors.dtype == np.dtype(dtype)
    assert feature.descriptor_dtype == np.dtype(dtype).name


def test_hloc_features_reads_official_layout_from_h5py(tmp_path: Path) -> None:
    path = tmp_path / "features.h5"
    keypoints = np.array([[1.25, 2.5], [10.5, 20.75]], np.float16)
    descriptors = np.arange(8, dtype=np.float16).reshape(4, 2)
    scores = np.array([0.25, 0.75], np.float16)
    with h5py.File(path, "w", libver="latest") as handle:
        group = handle.create_group("db/one.jpg")
        dataset = group.create_dataset("keypoints", data=keypoints)
        dataset.attrs["uncertainty"] = 0.625
        group.create_dataset("descriptors", data=descriptors)
        group.create_dataset("scores", data=scores)
        group.create_dataset("image_size", data=np.array([640, 480], np.int32))

    assert sceneio.detect(path) == "hloc_features"
    store = sceneio.read(path)
    assert isinstance(store, sceneio.HlocFeatureStore)
    feature = store["db/one.jpg"]
    np.testing.assert_array_equal(feature.keypoints, keypoints.astype(np.float32))
    np.testing.assert_array_equal(feature.descriptors, descriptors.T)
    np.testing.assert_array_equal(feature.scores, scores.astype(np.float32))
    assert feature.descriptors.dtype == np.float16
    assert feature.image_size == [640, 480]
    assert feature.pixel_center == (0.0, 0.0)
    assert feature.coordinates.pixel_center == (0.0, 0.0)
    assert store.coordinates.pixel_center == (0.0, 0.0)
    assert store.uncertainties["db/one.jpg"] == 0.625
    path.unlink()
    gc.collect()
    np.testing.assert_array_equal(feature.descriptors, descriptors.T)


def test_hloc_feature_write_matches_h5py_layout_and_roundtrips(
    tmp_path: Path,
) -> None:
    path = tmp_path / "features.h5"
    feature = _feature("db/a.jpg")
    source = sceneio.HlocFeatureStore(
        {"db/a.jpg": feature},
        {"db/a.jpg": 0.75},
    )

    sceneio.write(source, path)
    assert sceneio.detect(path) == "hloc_features"
    with h5py.File(path, "r") as handle:
        group = handle["db/a.jpg"]
        np.testing.assert_array_equal(group["keypoints"][...], feature.keypoints)
        np.testing.assert_array_equal(
            group["descriptors"][...],
            np.asarray(feature.descriptors).T,
        )
        np.testing.assert_array_equal(group["scores"][...], feature.scores)
        np.testing.assert_array_equal(group["image_size"][...], [640, 480])
        assert group["keypoints"].attrs["uncertainty"] == 0.75
        assert handle.attrs["sceneio_format"] == "hloc_features"

    decoded = sceneio.read(path)
    np.testing.assert_array_equal(
        decoded["db/a.jpg"].descriptors,
        feature.descriptors,
    )
    inspected = sceneio.inspect(path)
    assert inspected.count == 3
    assert inspected.metadata["image_count"] == 1
    assert inspected.coordinates.pixel_center == (0.0, 0.0)


def test_hloc_feature_writer_refuses_colmap_pixel_centers_atomically(
    tmp_path: Path,
) -> None:
    feature = _core.feature_set(
        np.array([[10.5, 20.5]], np.float32),
        image_name="a.jpg",
        image_size=(640, 480),
    )
    assert feature.pixel_center == (0.5, 0.5)
    destination = tmp_path / "existing.h5"
    destination.write_bytes(b"unchanged")

    with pytest.raises(sceneio.FormatError, match="cannot represent"):
        sceneio.write(
            sceneio.HlocFeatureStore({"a.jpg": feature}),
            destination,
            format="hloc_features",
        )
    assert destination.read_bytes() == b"unchanged"


def test_hloc_feature_guards_unrepresented_fields_and_datasets(
    tmp_path: Path,
) -> None:
    path = tmp_path / "extra.h5"
    with h5py.File(path, "w") as handle:
        group = handle.create_group("a.jpg")
        group.create_dataset("keypoints", data=np.zeros((2, 2), np.float32))
        group.create_dataset("image_size", data=np.array([10, 20], np.int32))
        group.create_dataset("scales", data=np.ones(2, np.float32))
    with pytest.raises(sceneio.FormatError, match="not a supported"):
        sceneio.read(path, format="hloc_features")

    feature = _core.feature_set(
        np.zeros((2, 2), np.float32),
        image_id=7,
        image_name="a.jpg",
        image_size=(10, 20),
    )
    destination = tmp_path / "existing.h5"
    destination.write_bytes(b"unchanged")
    with pytest.raises(sceneio.FormatError, match="cannot represent"):
        sceneio.write(
            sceneio.HlocFeatureStore({"a.jpg": feature}),
            destination,
            format="hloc_features",
        )
    assert destination.read_bytes() == b"unchanged"


@pytest.mark.parametrize("operation", [sceneio.read, sceneio.inspect])
def test_hloc_features_read_and_inspect_refuse_unrepresented_metadata(
    tmp_path: Path,
    operation,
) -> None:
    root_attr = tmp_path / "root-attr.h5"
    with h5py.File(root_attr, "w") as handle:
        handle.attrs["producer"] = "not-represented"
        group = handle.create_group("a.jpg")
        group.create_dataset("keypoints", data=np.zeros((1, 2), np.float32))
        group.create_dataset("image_size", data=np.array([10, 20], np.int32))
    with pytest.raises(sceneio.FormatError, match="root attributes"):
        operation(root_attr, format="hloc_features")

    dataset_attr = tmp_path / "dataset-attr.h5"
    with h5py.File(dataset_attr, "w") as handle:
        group = handle.create_group("a.jpg")
        group.create_dataset("keypoints", data=np.zeros((1, 2), np.float32))
        image_size = group.create_dataset(
            "image_size",
            data=np.array([10, 20], np.int32),
        )
        image_size.attrs["units"] = "pixels"
    with pytest.raises(sceneio.FormatError, match="unsupported attributes"):
        operation(dataset_attr, format="hloc_features")

    narrowed = tmp_path / "float64-keypoints.h5"
    with h5py.File(narrowed, "w") as handle:
        group = handle.create_group("a.jpg")
        group.create_dataset("keypoints", data=np.zeros((1, 2), np.float64))
        group.create_dataset("image_size", data=np.array([10, 20], np.int32))
    with pytest.raises(sceneio.FormatError, match="float16/float32"):
        operation(narrowed, format="hloc_features")

    with h5py.File(narrowed, "w") as handle:
        group = handle.create_group("a.jpg")
        group.create_dataset("keypoints", data=np.zeros((1, 2), np.float32))
        group.create_dataset("scores", data=np.ones(1, np.float64))
        group.create_dataset("image_size", data=np.array([10, 20], np.int32))
    with pytest.raises(sceneio.FormatError, match="float16/float32"):
        operation(narrowed, format="hloc_features")


def test_hloc_matches_reads_official_layout_and_reverses_to_native_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "matches.h5"
    dense = np.array([2, -1, 0, -1, 3], np.int16)
    scores = np.array([0.5, 0.0, 0.75, 0.0, 0.25], np.float16)
    with h5py.File(path, "w", libver="latest") as handle:
        pair_name = _official_hloc_pair_name(
            "query/b.jpg",
            "db/a.jpg",
        )
        assert pair_name == "query-b.jpg/db-a.jpg"
        group = handle.create_group(pair_name)
        group.create_dataset("matches0", data=dense)
        group.create_dataset("matching_scores0", data=scores)

    assert sceneio.detect(path) == "hloc_matches"
    store = sceneio.read(path)
    assert store.pair_names == (("query-b.jpg", "db-a.jpg"),)
    assert store.image_names == ("db-a.jpg", "query-b.jpg")
    assert store.source_keypoint_counts == (5,)
    assert store.match_dtypes == ("int16",)
    assert store.score_dtypes == ("float16",)
    np.testing.assert_array_equal(
        store.graph.matches,
        np.array([[2, 0], [0, 2], [3, 4]], np.uint32),
    )
    np.testing.assert_array_equal(
        store.graph.scores,
        np.array([0.5, 0.75, 0.25], np.float32),
    )
    path.unlink()
    gc.collect()
    np.testing.assert_array_equal(
        store.graph.matches,
        np.array([[2, 0], [0, 2], [3, 4]], np.uint32),
    )


def test_native_hloc_match_graph_converts_wire_dtypes_and_owns_results() -> None:
    dense_rows = [
        np.array([2, -1, 0], np.int16),
        np.array([-1, 3], np.int32),
        np.array([4, -1], np.int64),
    ]
    score_rows = [
        np.array([0.5, 0.0, 0.25], np.float16),
        None,
        np.array([0.75, 0.0], np.float32),
    ]
    graph = _core.hloc_match_graph(
        np.array([[1, 2], [1, 3], [2, 3]], np.uint32),
        dense_rows,
        score_rows,
        np.array([0, 1, 0], np.uint8),
    )
    del dense_rows, score_rows
    gc.collect()

    np.testing.assert_array_equal(graph.match_offsets, [0, 2, 3, 4])
    np.testing.assert_array_equal(
        graph.matches,
        np.array([[0, 2], [2, 0], [3, 1], [0, 4]], np.uint32),
    )
    np.testing.assert_array_equal(graph.match_score_present, [1, 0, 1])
    np.testing.assert_array_equal(
        graph.scores,
        np.array([0.5, 0.25, 0.0, 0.75], np.float32),
    )

    with pytest.raises(ValueError, match="outside uint32"):
        _core.hloc_match_graph(
            np.array([[1, 2]], np.uint32),
            [np.array([0x1_0000_0000], np.int64)],
            [None],
            np.array([0], np.uint8),
        )
    with pytest.raises(ValueError, match="finite"):
        _core.hloc_match_graph(
            np.array([[1, 2]], np.uint32),
            [np.array([0], np.int16)],
            [np.array([np.nan], np.float32)],
            np.array([0], np.uint8),
        )
    with pytest.raises(ValueError, match="unmatched"):
        _core.hloc_match_graph(
            np.array([[1, 2]], np.uint32),
            [np.array([-1], np.int16)],
            [np.array([0.5], np.float16)],
            np.array([0], np.uint8),
        )


def test_hloc_match_write_matches_h5py_and_preserves_mixed_scores(
    tmp_path: Path,
) -> None:
    path = tmp_path / "matches.h5"
    source = _match_store(mixed_scores=True)

    sceneio.write(source, path)
    assert sceneio.detect(path) == "hloc_matches"
    with h5py.File(path, "r") as handle:
        first = handle["query-b.jpg/db-a.jpg"]
        np.testing.assert_array_equal(
            first["matches0"][...],
            np.array([1, -1, 3, -1, -1], np.int16),
        )
        assert "matching_scores0" not in first
        assert first.attrs["name0"] == "query/b.jpg"
        assert first.attrs["name1"] == "db/a.jpg"

        second = handle["db-c.jpg/query-b.jpg"]
        np.testing.assert_array_equal(
            second["matches0"][...],
            np.array([-1, 4, -1], np.int32),
        )
        np.testing.assert_array_equal(
            second["matching_scores0"][...],
            np.array([0.0, 0.25, 0.0], np.float32),
        )

    decoded = sceneio.read(path)
    assert decoded.pair_names == source.pair_names
    np.testing.assert_array_equal(decoded.graph.matches, source.graph.matches)
    np.testing.assert_array_equal(
        decoded.graph.match_score_present,
        source.graph.match_score_present,
    )
    inspected = sceneio.inspect(path)
    assert inspected.count == 2
    assert inspected.metadata["scored_pair_count"] == 1


@pytest.mark.parametrize(
    ("indices", "expected"),
    [
        ([], False),
        ([7], False),
        ([0, 1, 4, 9], False),
        ([4, 0, 9, 1], False),
        ([0, 1, 1, 9], True),
        ([4, 1, 9, 4], True),
    ],
)
def test_hloc_duplicate_index_check_handles_orderings(
    indices: list[int],
    expected: bool,
) -> None:
    values = np.asarray(indices, dtype=np.uint32)
    assert hdf5_adapter._has_duplicate_indices(values) is expected


def test_hloc_match_write_handles_shuffled_sources_and_refuses_duplicates(
    tmp_path: Path,
) -> None:
    def store(matches: np.ndarray) -> sceneio.HlocMatchStore:
        graph = _core.match_graph(
            np.array([[1, 2]], np.uint32),
            np.array([0, len(matches)], np.uint64),
            matches,
            np.zeros(2, np.uint64),
            np.empty((0, 2), np.uint32),
            match_present=np.ones(1, np.uint8),
            geometry_present=np.zeros(1, np.uint8),
        )
        return sceneio.HlocMatchStore(
            ("a.jpg", "b.jpg"),
            (("a.jpg", "b.jpg"),),
            (4,),
            ("int16",),
            (None,),
            graph,
        )

    path = tmp_path / "shuffled.h5"
    sceneio.write(
        store(np.array([[2, 3], [0, 1], [3, 2]], np.uint32)),
        path,
        format="hloc_matches",
    )
    with h5py.File(path, "r") as handle:
        np.testing.assert_array_equal(
            handle["a.jpg/b.jpg/matches0"][...],
            np.array([1, -1, 3, 2], np.int16),
        )

    with pytest.raises(sceneio.FormatError, match="multiple matches"):
        sceneio.write(
            store(np.array([[0, 1], [2, 3], [0, 2]], np.uint32)),
            tmp_path / "duplicate.h5",
            format="hloc_matches",
        )


def test_hloc_matches_guards_malformed_and_unrepresented_values(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.h5"
    with h5py.File(malformed, "w") as handle:
        group = handle.create_group("a.jpg/b.jpg")
        group.create_dataset("matches0", data=np.array([1, -1], np.int16))
        group.create_dataset(
            "matching_scores0",
            data=np.array([0.5, 0.25], np.float16),
        )
    with pytest.raises(sceneio.FormatError, match="unmatched"):
        sceneio.read(malformed, format="hloc_matches")

    graph = _core.match_graph(
        np.array([[1, 2]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 1]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 1]], np.uint32),
        match_present=np.ones(1, np.uint8),
        geometry_present=np.ones(1, np.uint8),
    )
    store = sceneio.HlocMatchStore(
        ("a.jpg", "b.jpg"),
        (("a.jpg", "b.jpg"),),
        (2,),
        ("int16",),
        (None,),
        graph,
    )
    existing = tmp_path / "existing.h5"
    existing.write_bytes(b"unchanged")
    with pytest.raises(sceneio.FormatError, match="cannot represent"):
        sceneio.write(store, existing, format="hloc_matches")
    assert existing.read_bytes() == b"unchanged"


@pytest.mark.parametrize("operation", [sceneio.read, sceneio.inspect])
def test_hloc_matches_read_and_inspect_refuse_unrepresented_metadata(
    tmp_path: Path,
    operation,
) -> None:
    path = tmp_path / "matches-metadata.h5"
    with h5py.File(path, "w") as handle:
        handle.attrs["producer"] = "not-represented"
        group = handle.create_group("a.jpg/b.jpg")
        matches = group.create_dataset(
            "matches0",
            data=np.array([0], np.int16),
        )
        matches.attrs["meaning"] = "not-represented"
    with pytest.raises(sceneio.FormatError, match="root attributes"):
        operation(path, format="hloc_matches")

    with h5py.File(path, "a") as handle:
        del handle.attrs["producer"]
    with pytest.raises(sceneio.FormatError, match="unsupported attributes"):
        operation(path, format="hloc_matches")


def test_hdf5_public_capabilities_and_models_are_explicit(monkeypatch) -> None:
    assert sceneio.HlocFeatureStore.__module__ == "sceneio.io._hdf5"
    assert sceneio.HlocMatchStore.__module__ == "sceneio.io._hdf5"
    assert sceneio.capabilities("hdf5").partial_selectors == ("tensors", "slices")
    assert sceneio.capabilities("hloc_features").record_type == "HlocFeatureStore"
    assert sceneio.capabilities("hloc_matches").record_type == "HlocMatchStore"
    assert sceneio.capabilities("hdf5").requires_features == ("h5py",)

    from sceneio.io._registry import model

    original_find_spec = model.importlib.util.find_spec
    monkeypatch.setattr(
        model.importlib.util,
        "find_spec",
        lambda name: None if name == "h5py" else original_find_spec(name),
    )
    for format_id in ("hdf5", "hloc_features", "hloc_matches"):
        capability = sceneio.capabilities(format_id)
        assert not capability.available
        assert not capability.can_read
        assert not capability.can_write

    code = (
        "import sys; import sceneio; "
        "from bench.io_bench.oracles import containers; "
        "assert 'h5py' not in sys.modules; "
        "assert containers.H5PY_AVAILABLE"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[2],
        check=True,
    )
