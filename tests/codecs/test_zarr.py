from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr

import sceneio
from sceneio import _core


def _sample() -> tuple[object, dict[str, np.ndarray]]:
    raw = np.array(
        [0x7FC00001, 0x80000000, 0x00000001, 0x3F800000],
        dtype=np.uint32,
    )
    arrays = {
        "features/descriptors": raw.view(np.float32).reshape(2, 2),
        "masks/valid": np.array([[True, False], [False, True]], dtype=np.bool_),
        "tracks/image_ids": np.arange(12, dtype=np.uint32).reshape(4, 3),
    }
    return _core.tensor_dict(arrays, attrs={"frame": "opencv", "unit": "pixel"}), arrays


def _assert_tensor_dict_equal(
    actual,
    expected: dict[str, np.ndarray],
    *,
    attrs: dict[str, str],
) -> None:
    assert actual.keys() == sorted(expected)
    assert actual.attrs == attrs
    for name, source in expected.items():
        decoded = np.asarray(actual[name])
        assert decoded.dtype == source.dtype
        assert decoded.shape == source.shape
        assert decoded.tobytes() == source.tobytes()


@pytest.mark.parametrize("zarr_format", [2, 3])
def test_zarr_v2_v3_roundtrip_and_independent_oracle(tmp_path, zarr_format):
    tensors, arrays = _sample()
    path = tmp_path / f"cv-v{zarr_format}.zarr"

    sceneio.write_zarr(
        tensors,
        path,
        zarr_format=zarr_format,
        chunks={
            "features/descriptors": (1, 2),
            "tracks/image_ids": (2, 3),
        },
    )

    assert sceneio.detect(path) == "zarr"
    decoded = sceneio.read(path)
    _assert_tensor_dict_equal(
        decoded,
        arrays,
        attrs={"frame": "opencv", "unit": "pixel"},
    )

    oracle = zarr.open_group(path, mode="r", use_consolidated=None)
    assert int(oracle.metadata.zarr_format) == zarr_format
    assert dict(oracle.attrs) == {"frame": "opencv", "unit": "pixel"}
    for name, expected in arrays.items():
        actual = np.asarray(oracle[name])
        assert actual.dtype == expected.dtype
        assert actual.shape == expected.shape
        assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize("zarr_format", [2, 3])
def test_zarr_reads_oracle_written_store(tmp_path, zarr_format):
    path = tmp_path / "oracle.zarr"
    root = zarr.open_group(
        path,
        mode="w",
        zarr_format=zarr_format,
        attributes={"purpose": "cv"},
    )
    expected = np.arange(60, dtype=np.float16).reshape(5, 4, 3)
    root.create_array("depth/pyramid_0", data=expected, chunks=(2, 2, 3))

    decoded = sceneio.read(path)

    assert decoded.keys() == ["depth/pyramid_0"]
    assert decoded.attrs == {"purpose": "cv"}
    actual = np.asarray(decoded["depth/pyramid_0"])
    assert actual.tobytes() == expected.tobytes()


def test_zarr_partial_reads_touch_selected_arrays_and_chunks(tmp_path):
    tensors, arrays = _sample()
    path = tmp_path / "partial.zarr"
    sceneio.write_zarr(
        tensors,
        path,
        chunks={"tracks/image_ids": (1, 3)},
    )

    selected = sceneio.read_partial(
        path,
        tensors=("masks/valid",),
    )
    sliced = sceneio.read_partial(
        path,
        slices={"tracks/image_ids": (1, 3)},
    )

    _assert_tensor_dict_equal(
        selected,
        {"masks/valid": arrays["masks/valid"]},
        attrs={"frame": "opencv", "unit": "pixel"},
    )
    _assert_tensor_dict_equal(
        sliced,
        {"tracks/image_ids": arrays["tracks/image_ids"][1:3]},
        attrs={"frame": "opencv", "unit": "pixel"},
    )


def test_zarr_inspection_reads_metadata_without_array_decode(tmp_path, monkeypatch):
    tensors, arrays = _sample()
    path = tmp_path / "inspect.zarr"
    sceneio.write_zarr(tensors, path, zarr_format=3)

    def forbidden_getitem(self, selection):
        raise AssertionError(f"array payload was decoded for {selection!r}")

    monkeypatch.setattr(zarr.Array, "__getitem__", forbidden_getitem)
    result = sceneio.inspect(path)

    assert result.format == "zarr"
    assert result.datatype == "tensor_dict"
    assert result.count == len(arrays)
    assert result.byte_size == sum(
        item.stat().st_size for item in path.rglob("*") if item.is_file()
    )
    assert result.metadata == {
        "zarr_format": 3,
        "root_attribute_count": 2,
    }
    assert [(item.name, item.shape, item.dtype) for item in result.arrays] == [
        ("features/descriptors", (2, 2), "float32"),
        ("masks/valid", (2, 2), "bool"),
        ("tracks/image_ids", (4, 3), "uint32"),
    ]


def test_zarr_registry_write_defaults_to_v3(tmp_path):
    tensors, arrays = _sample()
    path = tmp_path / "default.zarr"

    sceneio.write(tensors, path)

    assert (path / "zarr.json").is_file()
    _assert_tensor_dict_equal(
        sceneio.read(path),
        arrays,
        attrs={"frame": "opencv", "unit": "pixel"},
    )


def test_zarr_replace_existing_store(tmp_path):
    first = _core.tensor_dict({"old": np.arange(3, dtype=np.int16)})
    second = _core.tensor_dict({"new": np.arange(6, dtype=np.float32)})
    path = tmp_path / "replace.zarr"
    sceneio.write_zarr(first, path, zarr_format=2)

    sceneio.write_zarr(second, path, zarr_format=3)

    assert not (path / ".zgroup").exists()
    assert sceneio.read(path).keys() == ["new"]
    assert not tuple(tmp_path.glob(".replace.zarr.*.previous"))


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("../outside", "relative '/'-separated path"),
        ("/absolute", "relative '/'-separated path"),
        ("a//b", "relative '/'-separated path"),
    ],
)
def test_zarr_rejects_invalid_tensor_paths(tmp_path, name, message):
    tensors = _core.tensor_dict({name: np.arange(2, dtype=np.uint8)})

    with pytest.raises(ValueError, match=message):
        sceneio.write_zarr(tensors, tmp_path / "bad.zarr")


def test_zarr_rejects_unsupported_oracle_dtype(tmp_path):
    path = tmp_path / "complex.zarr"
    root = zarr.open_group(path, mode="w", zarr_format=3)
    root.create_array("values", data=np.array([1 + 2j], dtype=np.complex64))

    with pytest.raises(sceneio.FormatError, match="unsupported dtype"):
        sceneio.read(path)


def test_zarr_slice_validates_bounds_and_scalars(tmp_path):
    path = tmp_path / "bounds.zarr"
    tensors = _core.tensor_dict(
        {
            "rows": np.arange(6, dtype=np.float32).reshape(3, 2),
            "scalar": np.asarray(1, dtype=np.int32),
        }
    )
    sceneio.write_zarr(tensors, path)

    with pytest.raises(sceneio.FormatError, match="outside leading dimension"):
        sceneio.read_partial(path, slices={"rows": (2, 4)})
    with pytest.raises(sceneio.FormatError, match="scalar cannot be sliced"):
        sceneio.read_partial(path, slices={"scalar": (0, 1)})


def test_zarr_capabilities_and_markers(tmp_path):
    capabilities = sceneio.capabilities("zarr")
    assert capabilities.available
    assert capabilities.container_kind == "directory"
    assert capabilities.partial_selectors == ("tensors", "slices")
    assert capabilities.requires_features == ("zarr",)

    empty = tmp_path / "not-zarr"
    empty.mkdir()
    with pytest.raises(sceneio.FormatError, match="no directory format"):
        sceneio.detect(empty)


def test_zarr_public_path_is_directory(tmp_path):
    path = tmp_path / "file.zarr"
    path.write_bytes(b"not a directory")

    with pytest.raises(sceneio.FormatError, match="expected a directory store"):
        sceneio.read(path, format="zarr")


def test_zarr_no_staging_directories_remain_after_failure(tmp_path, monkeypatch):
    tensors = _core.tensor_dict({"x": np.arange(3, dtype=np.float32)})
    destination = tmp_path / "failed.zarr"

    def fail_replace(_temporary: Path, _destination: Path) -> None:
        raise RuntimeError("injected replacement failure")

    monkeypatch.setattr("sceneio.io._zarr._replace_directory", fail_replace)
    with pytest.raises(RuntimeError, match="injected replacement failure"):
        sceneio.write_zarr(tensors, destination)

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".failed.zarr.*.tmp"))
