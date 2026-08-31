"""Oracle parity for the versioned NPZ/Zarr dense-label carriers."""

from __future__ import annotations

import gc
import io
import shutil
import tracemalloc
import zipfile
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import InstanceMap, LabelTaxonomy, PanopticMap, SemanticMap, _core
from sceneio.io import _label_map

SCHEMA = "sceneio.label_map/1"
MARKER = "__sceneio_label_map_v1__"
KUBRIC_REVISION = "61f2422c84bab75006df33c6989e0b483db3ccfe"


def _kubric_maps() -> tuple[SemanticMap, InstanceMap, PanopticMap]:
    # Hand-evaluated from Kubric adjust_segmentation_idxs at the pinned
    # revision: renderer ids start at one, output instance ids preserve that
    # ordering, and zero remains background.
    renderer_ids = np.array(
        [[0, 1, 1, 2], [0, 1, 2, 2], [0, 0, 2, 1]], np.int32
    )
    semantic_ids = np.zeros(renderer_ids.shape, np.int32)
    semantic_ids[renderer_ids == 1] = 4
    semantic_ids[renderer_ids == 2] = 9
    instance_ids = renderer_ids.astype(np.int64)
    valid = np.array(
        [[True, True, True, True], [True, True, True, True], [False, True, True, True]]
    )
    taxonomy = LabelTaxonomy(
        np.array([0, 4, 9], np.int32),
        ("background", "cube", "sphere"),
        "org.kubric.movi-a",
        KUBRIC_REVISION,
        np.array([[0, 0, 0], [220, 20, 60], [30, 144, 255]], np.uint8),
        np.array([False, True, True]),
    )
    semantic = SemanticMap(semantic_ids, -1, valid, taxonomy)
    instance = InstanceMap(
        instance_ids,
        0,
        valid,
        np.array([1, 2], np.int64),
        np.array([4, 9], np.int32),
    )
    return semantic, instance, PanopticMap(semantic, instance)


def _text(value: str) -> np.ndarray:
    return np.frombuffer(value.encode("utf-8"), np.uint8).copy()


def _oracle_arrays(value: object) -> dict[str, np.ndarray]:
    semantic, instance, _ = _kubric_maps()
    arrays: dict[str, np.ndarray] = {MARKER: np.array(1, np.uint8)}
    selected_semantic = value.semantic if isinstance(value, PanopticMap) else value
    selected_instance = value.instance if isinstance(value, PanopticMap) else value
    if isinstance(selected_semantic, SemanticMap):
        taxonomy = selected_semantic.taxonomy
        assert taxonomy is not None
        names = [name.encode("utf-8") for name in taxonomy.names]
        arrays.update(
            {
                "semantic_ids": selected_semantic.class_ids,
                "semantic_void_id": np.array(selected_semantic.void_id, np.int32),
                "taxonomy_semantic_ids": taxonomy.semantic_ids,
                "taxonomy_names_utf8": np.frombuffer(b"".join(names), np.uint8).copy(),
                "taxonomy_name_offsets": np.array(
                    [0, *np.cumsum([len(name) for name in names])], np.int64
                ),
                "taxonomy_identity_utf8": _text(taxonomy.identity),
                "taxonomy_version_utf8": _text(taxonomy.version),
                "taxonomy_display_colors": taxonomy.display_colors,
                "taxonomy_is_thing": taxonomy.is_thing,
            }
        )
    if isinstance(selected_instance, InstanceMap):
        arrays.update(
            {
                "instance_ids": selected_instance.instance_ids,
                "instance_background_id": np.array(
                    selected_instance.background_id, np.int64
                ),
                "table_instance_ids": selected_instance.table_instance_ids,
                "table_semantic_ids": selected_instance.table_semantic_ids,
            }
        )
    selected_valid = (
        semantic.valid if isinstance(value, SemanticMap) else instance.valid
    )
    arrays["valid"] = selected_valid
    assert all(isinstance(array, np.ndarray) for array in arrays.values())
    return arrays


def _assert_taxonomy(actual: LabelTaxonomy, expected: LabelTaxonomy) -> None:
    np.testing.assert_array_equal(actual.semantic_ids, expected.semantic_ids)
    assert actual.names == expected.names
    assert actual.identity == expected.identity
    assert actual.version == expected.version
    np.testing.assert_array_equal(actual.display_colors, expected.display_colors)
    np.testing.assert_array_equal(actual.is_thing, expected.is_thing)


def _assert_map(actual: object, expected: object) -> None:
    if isinstance(expected, SemanticMap):
        assert isinstance(actual, SemanticMap)
        np.testing.assert_array_equal(actual.class_ids, expected.class_ids)
        np.testing.assert_array_equal(actual.valid, expected.valid)
        assert actual.void_id == expected.void_id
        _assert_taxonomy(actual.taxonomy, expected.taxonomy)
        return
    if isinstance(expected, InstanceMap):
        assert isinstance(actual, InstanceMap)
        np.testing.assert_array_equal(actual.instance_ids, expected.instance_ids)
        np.testing.assert_array_equal(actual.valid, expected.valid)
        assert actual.background_id == expected.background_id
        np.testing.assert_array_equal(
            actual.table_instance_ids, expected.table_instance_ids
        )
        np.testing.assert_array_equal(
            actual.table_semantic_ids, expected.table_semantic_ids
        )
        return
    assert isinstance(actual, PanopticMap)
    assert isinstance(expected, PanopticMap)
    _assert_map(actual.semantic, expected.semantic)
    _assert_map(actual.instance, expected.instance)
    assert actual.semantic.valid is actual.instance.valid


@pytest.mark.parametrize("index", range(3), ids=("semantic", "instance", "panoptic"))
@pytest.mark.parametrize("compress", [False, True], ids=("stored", "deflate"))
def test_npz_sceneio_write_is_exact_for_numpy_oracle(
    tmp_path: Path, index: int, compress: bool
) -> None:
    value = _kubric_maps()[index]
    expected = _oracle_arrays(value)
    path = tmp_path / "labels.npz"
    sceneio.write_label_map(value, path, compress=compress)
    assert sceneio.detect(path) == "npz"
    info = sceneio.inspect_label_map(path)
    assert info.metadata["schema"] == SCHEMA
    assert info.shape == value.shape
    with np.load(path, allow_pickle=False) as archive:
        assert set(archive.files) == set(expected)
        for name, array in expected.items():
            np.testing.assert_array_equal(archive[name], array)
    _assert_map(sceneio.read_label_map(path), value)


@pytest.mark.parametrize("index", range(3), ids=("semantic", "instance", "panoptic"))
@pytest.mark.parametrize("compress", [False, True], ids=("stored", "deflate"))
def test_npz_reads_numpy_oracle_authored_schema(
    tmp_path: Path, index: int, compress: bool
) -> None:
    value = _kubric_maps()[index]
    arrays = _oracle_arrays(value)
    path = tmp_path / "oracle.npz"
    writer = np.savez_compressed if compress else np.savez
    writer(path, **arrays)
    _assert_map(sceneio.read_label_map(path), value)


@pytest.mark.parametrize("zarr_format", [2, 3])
@pytest.mark.parametrize("index", range(3), ids=("semantic", "instance", "panoptic"))
def test_zarr_roundtrip_and_independent_oracle(
    tmp_path: Path, zarr_format: int, index: int
) -> None:
    zarr = pytest.importorskip("zarr")
    value = _kubric_maps()[index]
    expected = _oracle_arrays(value)
    path = tmp_path / "labels.zarr"
    sceneio.write_label_map(
        value,
        path,
        zarr_format=zarr_format,
        chunks=(2, 3),
    )
    group = zarr.open_group(path, mode="r", use_consolidated=None)
    assert int(group.metadata.zarr_format) == zarr_format
    assert set(dict(group.members(max_depth=None))) == set(expected)
    for name, array in expected.items():
        np.testing.assert_array_equal(group[name][...], array)
    _assert_map(sceneio.read_label_map(path), value)


@pytest.mark.parametrize("zarr_format", [2, 3])
@pytest.mark.parametrize("index", range(3), ids=("semantic", "instance", "panoptic"))
def test_zarr_reads_oracle_authored_schema(
    tmp_path: Path, zarr_format: int, index: int
) -> None:
    zarr = pytest.importorskip("zarr")
    expected = _kubric_maps()[index]
    arrays = _oracle_arrays(expected)
    path = tmp_path / "oracle.zarr"
    group = zarr.open_group(path, mode="w", zarr_format=zarr_format)
    for name, array in arrays.items():
        group.create_array(name, data=array)
    _assert_map(sceneio.read_label_map(path), expected)


def test_typed_zarr_read_retains_numpy_arrays_without_tensordict_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("zarr")
    expected = _kubric_maps()[2]
    path = tmp_path / "labels.zarr"
    sceneio.write_label_map(expected, path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("typed Zarr read copied through TensorDict")

    monkeypatch.setattr(_core, "tensor_dict", forbidden)
    _assert_map(sceneio.read_label_map(path), expected)


def test_typed_zarr_write_does_not_copy_through_tensordict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("zarr")
    expected = _kubric_maps()[2]
    path = tmp_path / "labels.zarr"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("typed Zarr write copied through TensorDict")

    monkeypatch.setattr(_core, "tensor_dict", forbidden)
    sceneio.write_label_map(expected, path)
    _assert_map(sceneio.read_label_map(path), expected)


def test_zarr_lifetime_mutation_isolation_and_file_release(tmp_path: Path) -> None:
    pytest.importorskip("zarr")
    expected = _kubric_maps()[2]
    path = tmp_path / "labels.zarr"
    sceneio.write_label_map(expected, path)
    decoded = sceneio.read_label_map(path)
    gc.collect()
    shutil.rmtree(path)
    np.testing.assert_array_equal(decoded.semantic.class_ids, expected.semantic.class_ids)
    decoded.semantic.class_ids[0, 0] = 9
    assert int(expected.semantic.class_ids[0, 0]) == 0


@pytest.mark.parametrize("format_id", ["npz", "zarr"])
@pytest.mark.parametrize("index", range(3), ids=("semantic", "instance", "panoptic"))
def test_inspect_reports_contract_without_full_raster_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_id: str,
    index: int,
) -> None:
    expected = _kubric_maps()[index]
    path = tmp_path / f"labels.{format_id}"
    sceneio.write_label_map(expected, path, format=format_id)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("full raster decoder was called")

    original_read = _label_map._ZarrArrayReader.read

    def selected_only(self, names=None):
        if names is None:
            return forbidden()
        return original_read(self, names)

    monkeypatch.setattr(_label_map._ZarrArrayReader, "read", selected_only)
    monkeypatch.setattr(_core, "read_npz", forbidden)
    info = sceneio.inspect_label_map(path)
    expected_kind = ("semantic", "instance", "panoptic")[index]
    expected_dtype = ("int32", "int64", None)[index]
    assert info.format == format_id
    assert info.datatype == f"{expected_kind}_map"
    assert info.shape == (3, 4)
    assert info.dtype == expected_dtype
    assert info.count == 12
    assert info.metadata["schema"] == SCHEMA
    assert info.metadata["kind"] == expected_kind
    assert (info.metadata.get("void_id") == -1) is (index != 1)
    assert (info.metadata.get("background_id") == 0) is (index != 0)
    assert info.metadata["has_validity"] is True
    assert info.metadata["has_taxonomy"] is (index != 1)
    assert info.metadata["has_instance_table"] is (index != 0)


def test_raw_npz_api_remains_tensor_dict_and_untyped_npz_is_refused(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plain.npz"
    np.savez(path, values=np.arange(4, dtype=np.int32))
    raw = sceneio.read(path)
    assert isinstance(raw, sceneio.TensorDict)
    np.testing.assert_array_equal(raw["values"], np.arange(4, dtype=np.int32))
    with pytest.raises(sceneio.FormatError, match="does not declare"):
        sceneio.read_label_map(path)


def test_npz_bare_member_names_match_decoder_and_inspector(tmp_path: Path) -> None:
    expected = _kubric_maps()[0]
    path = tmp_path / "bare-members.npz"
    with zipfile.ZipFile(path, "w") as archive:
        for name, array in _oracle_arrays(expected).items():
            payload = io.BytesIO()
            np.save(payload, array, allow_pickle=False)
            archive.writestr(name, payload.getvalue())
    _assert_map(sceneio.read_label_map(path), expected)
    inspection = sceneio.inspect_label_map(path)
    assert inspection.datatype == "semantic_map"
    assert inspection.shape == expected.shape


def test_npz_lifetime_mutation_isolation_and_file_release(tmp_path: Path) -> None:
    expected = _kubric_maps()[2]
    path = tmp_path / "labels.npz"
    sceneio.write_label_map(expected, path)
    decoded = sceneio.read_label_map(path)
    gc.collect()
    path.unlink()
    np.testing.assert_array_equal(decoded.semantic.class_ids, expected.semantic.class_ids)
    decoded.semantic.class_ids[0, 0] = 9
    assert int(expected.semantic.class_ids[0, 0]) == 0


def test_npz_direct_sink_is_byte_identical_and_avoids_python_output_copy(
    tmp_path: Path,
) -> None:
    values = np.arange(2048 * 2048, dtype=np.int32).reshape(2048, 2048) % 7
    semantic = SemanticMap(values, -1)
    # _oracle_arrays uses the Kubric taxonomy for SemanticMap values; this
    # large fixture deliberately carries no taxonomy, so build the exact
    # schema independently here.
    arrays = {
        MARKER: np.array(1, np.uint8),
        "semantic_ids": values,
        "semantic_void_id": np.array(-1, np.int32),
    }
    expected_bytes = bytes(_core.write_npz(_core.tensor_dict(arrays)))
    path = tmp_path / "large.npz"
    tracemalloc.start()
    sceneio.write_label_map(semantic, path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert path.read_bytes() == expected_bytes
    assert peak < 2 * 1024 * 1024


def test_npz_replacement_is_transactional_on_encoder_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "labels.npz"
    original = b"existing destination"
    path.write_bytes(original)

    def fail(*_args, **_kwargs):
        raise OSError("injected write failure")

    monkeypatch.setattr(_core, "_write_to_file", fail)
    with pytest.raises(sceneio.FormatError, match="injected write failure"):
        sceneio.write_label_map(_kubric_maps()[0], path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_carrier_specific_options_are_explicit(tmp_path: Path) -> None:
    semantic = _kubric_maps()[0]
    with pytest.raises(ValueError, match="Zarr-only"):
        sceneio.write_label_map(semantic, tmp_path / "labels.npz", zarr_format=2)
    with pytest.raises(ValueError, match="chunk shapes"):
        sceneio.write_label_map(semantic, tmp_path / "labels.npz", chunks=(1, 1))
    with pytest.raises(ValueError, match="NPZ-only"):
        sceneio.write_label_map(
            semantic,
            tmp_path / "labels.zarr",
            format="zarr",
            compress=True,
        )


def test_zarr_options_accept_numpy_integer_scalars(tmp_path: Path) -> None:
    pytest.importorskip("zarr")
    path = tmp_path / "labels.zarr"
    sceneio.write_label_map(
        _kubric_maps()[0],
        path,
        zarr_format=np.int64(2),
        chunks=(np.int64(2), np.int32(3)),
    )
    assert sceneio.inspect_label_map(path).shape == (3, 4)


@pytest.mark.parametrize(
    ("arrays", "message"),
    [
        ({MARKER: np.array(2, np.uint8)}, "does not declare"),
        (
            {
                MARKER: np.array(1, np.uint8),
                "semantic_ids": np.zeros((2, 2), np.int32),
            },
            "incomplete",
        ),
        (
            {
                MARKER: np.array(1, np.uint8),
                "instance_ids": np.zeros((2, 2), np.int64),
                "instance_background_id": np.array(0, np.int64),
                "future_field": np.zeros(1, np.int32),
            },
            "unknown arrays",
        ),
    ],
)
def test_malformed_versioned_npz_is_refused(
    tmp_path: Path, arrays: dict[str, np.ndarray], message: str
) -> None:
    path = tmp_path / "bad.npz"
    np.savez(path, **arrays)
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_label_map(path)


@pytest.mark.parametrize("format_id", ["npz", "zarr"])
@pytest.mark.parametrize("failure", ["marker", "unknown"])
def test_schema_preflight_refuses_before_full_raster_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_id: str,
    failure: str,
) -> None:
    if format_id == "zarr":
        zarr = pytest.importorskip("zarr")
    arrays = _oracle_arrays(_kubric_maps()[0])
    if failure == "marker":
        arrays[MARKER] = np.array(2, np.uint8)
        message = "does not declare"
    else:
        arrays["future_field"] = np.zeros(1, np.int32)
        message = "unknown arrays"
    path = tmp_path / f"bad.{format_id}"
    if format_id == "npz":
        np.savez(path, **arrays)
    else:
        group = zarr.open_group(path, mode="w", zarr_format=3)
        for name, array in arrays.items():
            group.create_array(name, data=array)

    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("full raster decoder was called")

    if format_id == "npz":
        monkeypatch.setattr("sceneio.io.registry.get", forbidden)
    else:
        original_read = _label_map._ZarrArrayReader.read

        def forbid_full_read(self, names=None):
            if names is None:
                return forbidden()
            return original_read(self, names)

        monkeypatch.setattr(
            _label_map._ZarrArrayReader,
            "read",
            forbid_full_read,
        )
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_label_map(path)
    assert calls == 0


def test_zarr_preflight_rejects_nonscalar_marker_before_payload_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zarr = pytest.importorskip("zarr")
    arrays = _oracle_arrays(_kubric_maps()[0])
    arrays[MARKER] = np.zeros(1024, np.uint8)
    path = tmp_path / "bad-marker.zarr"
    group = zarr.open_group(path, mode="w", zarr_format=3)
    for name, array in arrays.items():
        group.create_array(name, data=array)

    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("marker payload was decoded")

    monkeypatch.setattr(_label_map._ZarrArrayReader, "read", forbidden)
    with pytest.raises(sceneio.FormatError, match="incompatible shape or dtype"):
        sceneio.read_label_map(path)
    assert calls == 0


def test_typed_public_surface_and_schema_constant() -> None:
    assert sceneio.LABEL_MAP_SCHEMA == SCHEMA
    assert sceneio.io.LABEL_MAP_SCHEMA == SCHEMA
    assert sceneio.read_label_map is sceneio.io.read_label_map
    assert sceneio.write_label_map is sceneio.io.write_label_map
    assert sceneio.inspect_label_map is sceneio.io.inspect_label_map
    for name in (
        "LABEL_MAP_SCHEMA",
        "read_label_map",
        "write_label_map",
        "inspect_label_map",
    ):
        assert name in sceneio.__all__
        assert name in sceneio.io.__all__
