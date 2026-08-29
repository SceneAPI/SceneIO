"""NCore V4 storage/catalog contracts grounded in the upstream V4 layout."""

from __future__ import annotations

import io
import json
import lzma
import shutil
import struct
import tarfile
import tracemalloc
from dataclasses import replace
from pathlib import Path

import cbor2
import numcodecs
import numpy as np
import pytest
import zarr

import sceneio
from sceneio.io._ncore.component_io import read_ncore_component
from sceneio.io._ncore.itar import IndexedTarReader, as_zarr_store
from sceneio.io._ncore.model import NCoreDataset, NCoreSelection
from sceneio.io._ncore.schema import inspect_ncore_v4, read_ncore_v4

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _metadata(*, group: str = "", sequence_id: str = "sequence-a") -> dict[str, object]:
    return {
        ".zgroup": {"zarr_format": 2},
        ".zattrs": {
            "sequence_id": sequence_id,
            "sequence_timestamp_interval_us": {"start": 100, "stop": 200},
            "generic_meta_data": {"weather": "clear", "run": 7},
            "version": "v4",
            "component_group_name": group,
        },
        "poses/.zgroup": {"zarr_format": 2},
        "poses/rig/.zgroup": {"zarr_format": 2},
        "poses/rig/.zattrs": {
            "component_name": "poses",
            "component_instance_name": "rig",
            "component_version": "v1",
            "generic_meta_data": {"source": "fixture"},
        },
        "poses/rig/value/.zarray": {
            "chunks": [4],
            "compressor": None,
            "dtype": "<i4",
            "fill_value": 0,
            "filters": None,
            "order": "C",
            "shape": [4],
            "zarr_format": 2,
        },
        "poses/rig/value/.zattrs": {"unit": "index"},
    }


def _consolidated(metadata: dict[str, object]) -> bytes:
    document = {"zarr_consolidated_format": 1, "metadata": metadata}
    return lzma.compress(cbor2.dumps(document), format=lzma.FORMAT_XZ)


def _write_directory(path: Path, metadata: dict[str, object]) -> None:
    path.mkdir()
    (path / ".zgroup").write_text(json.dumps(metadata[".zgroup"]), encoding="utf-8")
    (path / ".zattrs").write_text(json.dumps(metadata[".zattrs"]), encoding="utf-8")
    (path / ".zmetadata.cbor.xz").write_bytes(_consolidated(metadata))
    payload = path / "poses" / "rig" / "value"
    payload.mkdir(parents=True)
    (payload / "0").write_bytes(np.arange(4, dtype=np.int32).tobytes())


def _write_custom_directory(
    path: Path,
    metadata: dict[str, object],
    chunks: dict[str, bytes],
) -> None:
    path.mkdir()
    for key, value in metadata.items():
        target = path / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(value, separators=(",", ":")),
            encoding="utf-8",
        )
    (path / ".zmetadata.cbor.xz").write_bytes(_consolidated(metadata))
    for key, value in chunks.items():
        target = path / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)


def _write_itar(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, mode="w") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    with tarfile.open(path, mode="r") as archive:
        indexed = tuple(
            (member.name, member.offset_data, member.size)
            for member in archive.getmembers()
        )
    with path.open("ab") as stream:
        index_offset = stream.tell()
        index = {
            "items": [item[0] for item in indexed],
            "offset_datas": [item[1] for item in indexed],
            "sizes": [item[2] for item in indexed],
        }
        encoded = lzma.compress(cbor2.dumps(index), format=lzma.FORMAT_XZ)
        stream.write(encoded)
        remainder = stream.tell() % tarfile.BLOCKSIZE
        if remainder:
            stream.write(bytes(tarfile.BLOCKSIZE - remainder))
        stream.write(struct.pack("<4sIQI", b"itar", 1, index_offset, len(encoded)))
        remainder = stream.tell() % tarfile.BLOCKSIZE
        if remainder:
            stream.write(bytes(tarfile.BLOCKSIZE - remainder))


def _itar_members(metadata: dict[str, object]) -> dict[str, bytes]:
    return {
        key: json.dumps(value, separators=(",", ":")).encode()
        for key, value in metadata.items()
    } | {
        ".zmetadata.cbor.xz": _consolidated(metadata),
        "poses/rig/value/0": np.arange(4, dtype=np.int32).tobytes(),
    }


def test_directory_catalog_and_inspection_are_metadata_only(tmp_path):
    path = tmp_path / "sample.ncore4.zarr"
    _write_directory(path, _metadata())

    dataset = read_ncore_v4(path)
    assert isinstance(dataset, NCoreDataset)
    assert dataset.sequence_id == "sequence-a"
    assert dataset.timestamp_interval_us == (100, 200)
    assert dataset.generic_metadata == {"weather": "clear", "run": 7}
    assert tuple(component.id for component in dataset.components) == ("poses:rig",)
    assert dataset.components[0].arrays[0].name == "value"
    assert dataset.components[0].arrays[0].shape == (4,)
    assert dataset.components[0].arrays[0].dtype == "<i4"
    assert dataset.components[0].arrays[0].attributes == {"unit": "index"}

    info = inspect_ncore_v4(path)
    assert info.format == "ncore_v4"
    assert info.datatype == "ncore_dataset"
    assert info.count == 1
    assert info.arrays[0].name == "poses:rig/value"
    assert info.metadata["standard_component_count"] == 1
    assert info.metadata["custom_component_count"] == 0

    assert sceneio.detect(path) == "ncore_v4"
    public_dataset = sceneio.read(path)
    assert isinstance(public_dataset, sceneio.NCoreDataset)
    assert public_dataset.sequence_id == dataset.sequence_id
    assert sceneio.inspect(path) == info


def test_indexed_tar_direct_reads_ranges_and_zarr_chunks(tmp_path):
    path = tmp_path / "sample.ncore4.zarr.itar"
    metadata = _metadata()
    _write_itar(path, _itar_members(metadata))

    with IndexedTarReader(path, tail_size=512) as reader:
        assert reader.read("poses/rig/value/0", (4, 12)) == np.array(
            [1, 2], dtype=np.int32
        ).tobytes()
        group = zarr.open_group(
            store=as_zarr_store(reader),
            mode="r",
            use_consolidated=False,
        )
        np.testing.assert_array_equal(group["poses/rig/value"][:], np.arange(4))

    with pytest.raises(ValueError, match="closed"):
        reader.read(".zgroup")
    assert sceneio.detect(path) == "ncore_v4"


def test_directory_and_itar_catalogs_are_logically_identical(tmp_path):
    metadata = _metadata(group="calibration")
    directory = tmp_path / "sample.ncore4-calibration.zarr"
    archive = tmp_path / "sample.ncore4-calibration.zarr.itar"
    _write_directory(directory, metadata)
    _write_itar(archive, _itar_members(metadata))

    from_directory = read_ncore_v4(directory)
    from_archive = read_ncore_v4(archive)
    assert from_directory.sequence_id == from_archive.sequence_id
    assert from_directory.timestamp_interval_us == from_archive.timestamp_interval_us
    assert from_directory.generic_metadata == from_archive.generic_metadata
    assert from_directory.components == from_archive.components
    assert from_directory.stores[0].group == "calibration"
    assert from_archive.stores[0].group == "calibration"
    assert from_directory.stores[0].storage == "directory"
    assert from_archive.stores[0].storage == "itar"
    assert sceneio.detect(tmp_path) == "ncore_v4"


def test_large_directory_catalog_does_not_materialize_payload(tmp_path):
    path = tmp_path / "large.ncore4.zarr"
    metadata = _metadata()
    metadata["poses/rig/value/.zarray"] = {
        **metadata["poses/rig/value/.zarray"],
        "chunks": [25_000_000],
        "shape": [25_000_000],
    }
    _write_directory(path, metadata)
    payload = path / "poses" / "rig" / "value" / "0"
    with payload.open("r+b") as stream:
        stream.truncate(100_000_000)

    tracemalloc.start()
    dataset = read_ncore_v4(path)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert dataset.components[0].arrays[0].shape == (25_000_000,)
    assert dataset.byte_size >= 100_000_000
    # XZ's metadata dictionary accounts for roughly 8 MiB; the bound remains
    # independent of the 100 MB component payload.
    assert peak < 12 * 1024 * 1024


def test_sequence_manifest_combines_consistent_component_groups(tmp_path):
    first = tmp_path / "sample.ncore4-calibration.zarr"
    second = tmp_path / "sample.ncore4-sensors.zarr"
    _write_directory(first, _metadata(group="calibration"))
    sensor_metadata = _metadata(group="sensors")
    sensor_metadata["poses/rig/.zattrs"] = {
        **sensor_metadata["poses/rig/.zattrs"],
        "component_instance_name": "world",
    }
    sensor_metadata["poses/world/.zgroup"] = sensor_metadata.pop(
        "poses/rig/.zgroup"
    )
    sensor_metadata["poses/world/.zattrs"] = sensor_metadata.pop(
        "poses/rig/.zattrs"
    )
    sensor_metadata["poses/world/value/.zarray"] = sensor_metadata.pop(
        "poses/rig/value/.zarray"
    )
    sensor_metadata["poses/world/value/.zattrs"] = sensor_metadata.pop(
        "poses/rig/value/.zattrs"
    )
    _write_directory(second, sensor_metadata)
    manifest = tmp_path / "sample.json"
    manifest.write_text(
        json.dumps(
            {
                "sequence_id": "sequence-a",
                "sequence_timestamp_interval_us": {"start": 100, "stop": 200},
                "generic_meta_data": {"weather": "clear", "run": 7},
                "version": "v4",
                "component_stores": [
                    {
                        "path": first.name,
                        "md5": "",
                        "components": {
                            "poses": {
                                "rig": {
                                    "version": "v1",
                                    "generic_meta_data": {"source": "fixture"},
                                }
                            }
                        },
                    },
                    {
                        "path": second.name,
                        "md5": "",
                        "components": {
                            "poses": {
                                "world": {
                                    "version": "v1",
                                    "generic_meta_data": {"source": "fixture"},
                                }
                            }
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    dataset = read_ncore_v4(manifest)
    assert tuple(store.group for store in dataset.stores) == (
        "calibration",
        "sensors",
    )
    assert tuple(component.id for component in dataset.components) == (
        "poses:rig",
        "poses:world",
    )
    assert sceneio.detect(manifest) == "ncore_v4"
    assert sceneio.read(manifest).components == dataset.components


def test_schema_probe_leaves_generic_zarr_and_json_authoritative(tmp_path):
    generic = tmp_path / "generic.zarr"
    generic.mkdir()
    (generic / ".zgroup").write_text('{"zarr_format":2}', encoding="utf-8")
    (generic / ".zattrs").write_text("{}", encoding="utf-8")
    assert sceneio.detect(generic) == "zarr"

    document = tmp_path / "transforms.json"
    document.write_text('{"camera_angle_x":0.7,"frames":[]}', encoding="utf-8")
    assert sceneio.detect(document) == "transforms_json"

    overflow = tmp_path / "overflow.zarr"
    overflow_metadata = _metadata()
    overflow_metadata[".zattrs"] = {
        **overflow_metadata[".zattrs"],
        "sequence_timestamp_interval_us": {
            "start": 1,
            "stop": 1 << 64,
        },
    }
    _write_directory(overflow, overflow_metadata)
    assert sceneio.detect(overflow) == "zarr"


def test_rejects_inconsistent_store_roots_and_component_identity(tmp_path):
    root = tmp_path / "dataset"
    root.mkdir()
    _write_directory(
        root / "sample.ncore4-a.zarr",
        _metadata(group="a"),
    )
    _write_directory(
        root / "sample.ncore4-b.zarr",
        _metadata(group="b", sequence_id="sequence-b"),
    )
    with pytest.raises(ValueError, match="different sequences"):
        read_ncore_v4(root)

    malformed = tmp_path / "malformed.ncore4.zarr"
    metadata = _metadata()
    metadata["poses/rig/.zattrs"] = {
        **metadata["poses/rig/.zattrs"],
        "component_name": "cameras",
    }
    _write_directory(malformed, metadata)
    with pytest.raises(ValueError, match="disagrees"):
        read_ncore_v4(malformed)


def test_rejects_invalid_index_headers_and_ranges(tmp_path):
    path = tmp_path / "bad.zarr.itar"
    _write_itar(path, _itar_members(_metadata()))
    with path.open("r+b") as stream:
        stream.seek(-tarfile.BLOCKSIZE, 2)
        stream.write(b"nope")
    with pytest.raises(ValueError, match="header magic"):
        IndexedTarReader(path)

    valid = tmp_path / "valid.zarr.itar"
    _write_itar(valid, _itar_members(_metadata()))
    with IndexedTarReader(valid) as reader, pytest.raises(ValueError, match="outside"):
        reader.read(".zgroup", (0, 10_000))


def test_selection_contract_has_one_optional_range_family():
    assert NCoreSelection("cameras", "front", frames=(2, 4)).frames == (2, 4)
    with pytest.raises(ValueError, match="not both"):
        NCoreSelection(
            "cameras",
            "front",
            frames=(2, 4),
            timestamps_us=(100, 200),
        )
    with pytest.raises(ValueError, match="start < stop"):
        NCoreSelection("cameras", "front", frames=(3, 3))


def test_component_arrays_are_owned_exact_and_directory_itar_equivalent(tmp_path):
    metadata = _metadata()
    compressor = numcodecs.Blosc(
        cname="lz4",
        clevel=5,
        shuffle=numcodecs.Blosc.BITSHUFFLE,
    )
    metadata["poses/rig/value/.zarray"] = {
        **metadata["poses/rig/value/.zarray"],
        "compressor": compressor.get_config(),
    }
    raw = np.arange(4, dtype=np.int32).tobytes()
    encoded = bytes(compressor.encode(raw))
    directory = tmp_path / "owned.ncore4.zarr"
    archive = tmp_path / "owned.ncore4.zarr.itar"
    _write_custom_directory(
        directory,
        metadata,
        {"poses/rig/value/0": encoded},
    )
    _write_itar(
        archive,
        {
            **_itar_members(metadata),
            "poses/rig/value/0": encoded,
        },
    )
    selection = NCoreSelection("poses", "rig")
    from_directory = read_ncore_component(directory, selection)
    from_archive = sceneio.read_ncore_component(archive, selection)
    for loaded in (from_directory, from_archive):
        np.testing.assert_array_equal(loaded.array("value"), np.arange(4))
        assert loaded.array("value").flags.owndata
        assert not loaded.array("value").flags.writeable
        assert loaded.group().attributes["component_name"] == "poses"
        assert loaded.selected_items == ()
    shutil.rmtree(directory)
    archive.unlink()
    np.testing.assert_array_equal(from_directory.array("value"), np.arange(4))
    np.testing.assert_array_equal(from_archive.array("value"), np.arange(4))


def test_component_decoder_preserves_zarr_v2_chunk_and_dtype_semantics(tmp_path):
    metadata = _metadata()
    metadata["poses/rig/matrix/.zarray"] = {
        "chunks": [2, 3],
        "compressor": None,
        "dimension_separator": "/",
        "dtype": ">i2",
        "fill_value": -7,
        "filters": None,
        "order": "F",
        "shape": [3, 5],
        "zarr_format": 2,
    }
    delta = numcodecs.Delta(dtype="<i4")
    metadata["poses/rig/delta/.zarray"] = {
        "chunks": [4],
        "compressor": None,
        "dtype": "<i4",
        "fill_value": 0,
        "filters": [delta.get_config()],
        "order": "C",
        "shape": [6],
        "zarr_format": 2,
    }
    structured_dtype = np.dtype([("xy", "<f4", (2,)), ("id", "<u2")])
    metadata["poses/rig/structured/.zarray"] = {
        "chunks": [2],
        "compressor": None,
        "dtype": [["xy", "<f4", [2]], ["id", "<u2"]],
        "fill_value": 0,
        "filters": None,
        "order": "C",
        "shape": [2],
        "zarr_format": 2,
    }
    nested_dtype = np.dtype([("position", [("x", "<f4"), ("y", "<f4")])])
    metadata["poses/rig/nested/.zarray"] = {
        "chunks": [1],
        "compressor": None,
        "dtype": [["position", [["x", "<f4"], ["y", "<f4"]]]],
        "fill_value": 0,
        "filters": None,
        "order": "C",
        "shape": [1],
        "zarr_format": 2,
    }
    metadata["poses/rig/complex_fill/.zarray"] = {
        "chunks": [2],
        "compressor": None,
        "dtype": "<c8",
        "fill_value": [1.25, -2.5],
        "filters": None,
        "order": "C",
        "shape": [2],
        "zarr_format": 2,
    }
    matrix_00 = np.array(
        [[1, 2, 3], [4, 5, 6]], dtype=">i2", order="F"
    )
    matrix_11 = np.array(
        [[90, 91, 92], [93, 94, 95]], dtype=">i2", order="F"
    )
    delta_0 = np.array([0, 1, 4, 9], dtype="<i4")
    delta_1 = np.array([16, 25, 0, 0], dtype="<i4")
    structured = np.array(
        [([1.5, 2.5], 7), ([3.5, 4.5], 8)], dtype=structured_dtype
    )
    nested = np.array([((6.5, 7.5),)], dtype=nested_dtype)
    path = tmp_path / "zarr-semantics.ncore4.zarr"
    _write_custom_directory(
        path,
        metadata,
        {
            "poses/rig/value/0": np.arange(4, dtype=np.int32).tobytes(),
            "poses/rig/matrix/0/0": matrix_00.tobytes(order="F"),
            "poses/rig/matrix/1/1": matrix_11.tobytes(order="F"),
            "poses/rig/delta/0": bytes(delta.encode(delta_0)),
            "poses/rig/delta/1": bytes(delta.encode(delta_1)),
            "poses/rig/structured/0": structured.tobytes(),
            "poses/rig/nested/0": nested.tobytes(),
        },
    )

    loaded = sceneio.read_ncore_component(
        path, sceneio.NCoreSelection("poses", "rig")
    )
    expected_matrix = np.full((3, 5), -7, dtype=">i2")
    expected_matrix[:2, :3] = matrix_00
    expected_matrix[2, 3:] = matrix_11[0, :2]
    np.testing.assert_array_equal(loaded.array("matrix"), expected_matrix)
    assert loaded.array("matrix").dtype == np.dtype(">i2")
    np.testing.assert_array_equal(
        loaded.array("delta"), np.array([0, 1, 4, 9, 16, 25])
    )
    np.testing.assert_array_equal(loaded.array("structured"), structured)
    assert loaded.array("structured").dtype == structured_dtype
    np.testing.assert_array_equal(loaded.array("nested"), nested)
    assert loaded.array("nested").dtype == nested_dtype
    np.testing.assert_array_equal(
        loaded.array("complex_fill"),
        np.full(2, 1.25 - 2.5j, dtype=np.complex64),
    )

    complete = sceneio.materialize_ncore_v4(path)
    rewritten = tmp_path / "rewritten-zarr-semantics"
    sceneio.write_ncore_v4(complete, rewritten, storage="itar")
    round_trip = sceneio.materialize_ncore_v4(rewritten)
    for name, expected in complete.components[0].arrays.items():
        actual = round_trip.components[0].arrays[name]
        assert actual.dtype == expected.dtype
        assert actual.shape == expected.shape
        assert actual.tobytes() == expected.tobytes()


def _sensor_metadata() -> tuple[dict[str, object], dict[str, bytes]]:
    metadata = _metadata()
    for key in tuple(metadata):
        if key.startswith("poses/"):
            del metadata[key]
    metadata.update(
        {
            "cameras/.zgroup": {"zarr_format": 2},
            "cameras/front/.zgroup": {"zarr_format": 2},
            "cameras/front/.zattrs": {
                "component_name": "cameras",
                "component_instance_name": "front",
                "component_version": "v1",
                "generic_meta_data": {},
            },
            "cameras/front/frames/.zgroup": {"zarr_format": 2},
            "cameras/front/frames/.zattrs": {
                "frames_timestamps_us": [
                    [100, 110],
                    [110, 120],
                    [120, 130],
                ]
            },
        }
    )
    chunks: dict[str, bytes] = {}
    for index, timestamp in enumerate((110, 120, 130)):
        base = f"cameras/front/frames/{timestamp}"
        metadata[f"{base}/.zgroup"] = {"zarr_format": 2}
        metadata[f"{base}/.zattrs"] = {"frame": index}
        metadata[f"{base}/data/.zarray"] = {
            "chunks": [2, 2],
            "compressor": None,
            "dtype": "|u1",
            "fill_value": 0,
            "filters": None,
            "order": "C",
            "shape": [2, 2],
            "zarr_format": 2,
        }
        metadata[f"{base}/data/.zattrs"] = {"format": "raw"}
        chunks[f"{base}/data/0.0"] = np.full(
            (2, 2), index, dtype=np.uint8
        ).tobytes()
    return metadata, chunks


def _profile_metadata(
    component_name: str,
    *,
    instance: str = "default",
) -> dict[str, object]:
    metadata = _metadata()
    for key in tuple(metadata):
        if key.startswith("poses/"):
            del metadata[key]
    metadata.update(
        {
            f"{component_name}/.zgroup": {"zarr_format": 2},
            f"{component_name}/{instance}/.zgroup": {"zarr_format": 2},
            f"{component_name}/{instance}/.zattrs": {
                "component_name": component_name,
                "component_instance_name": instance,
                "component_version": "v1",
                "generic_meta_data": {"oracle": "ncore-v4"},
            },
        }
    )
    return metadata


def _add_array(
    metadata: dict[str, object],
    payloads: dict[str, bytes],
    name: str,
    value: np.ndarray,
    *,
    attributes: dict[str, object] | None = None,
) -> None:
    value = np.asarray(value)
    if value.ndim:
        value = np.ascontiguousarray(value)
    chunks = [max(1, int(size)) for size in value.shape]
    metadata[f"{name}/.zarray"] = {
        "chunks": chunks,
        "compressor": None,
        "dtype": value.dtype.str,
        "fill_value": 0,
        "filters": None,
        "order": "C",
        "shape": list(value.shape),
        "zarr_format": 2,
    }
    metadata[f"{name}/.zattrs"] = attributes or {}
    if value.size or value.ndim == 0:
        chunk_id = ".".join("0" for _ in value.shape) or "0"
        payloads[f"{name}/{chunk_id}"] = value.tobytes()


def test_semantic_poses_profile_preserves_named_static_and_dynamic_edges(tmp_path):
    metadata = _profile_metadata("poses", instance="rig")
    static = np.eye(4, dtype=np.float32)
    static[0, 3] = 2
    dynamic = np.stack((np.eye(4), np.eye(4))).astype(np.float64)
    dynamic[1, 1, 3] = 3
    metadata.update(
        {
            "poses/rig/static_poses/.zgroup": {"zarr_format": 2},
            "poses/rig/static_poses/.zattrs": {
                "('camera', 'rig')": {
                    "pose": static.tolist(),
                    "dtype": "float32",
                }
            },
            "poses/rig/dynamic_poses/.zgroup": {"zarr_format": 2},
            "poses/rig/dynamic_poses/.zattrs": {
                "('rig', 'world')": {
                    "poses": dynamic.tolist(),
                    "timestamps_us": [100, 199],
                    "dtype": "float64",
                }
            },
        }
    )
    path = tmp_path / "poses-profile.ncore4.zarr"
    _write_custom_directory(path, metadata, {})

    semantic = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection("poses", "rig")
    )
    assert isinstance(semantic, sceneio.NCoreSemanticComponent)
    assert semantic.profile == "poses/v1"
    np.testing.assert_array_equal(
        semantic.item("static_pose", "camera->rig").array("transforms"),
        static,
    )
    trajectory = semantic.item("dynamic_pose", "rig->world")
    np.testing.assert_array_equal(trajectory.array("transforms"), dynamic)
    np.testing.assert_array_equal(
        trajectory.array("timestamps_us"), np.array([100, 199], dtype=np.uint64)
    )
    assert all(
        not array.flags.writeable
        for item in semantic.items
        for array in item.arrays.values()
    )


def test_semantic_poses_profile_rejects_inverse_duplicate(tmp_path):
    metadata = _profile_metadata("poses", instance="rig")
    entry = {"pose": np.eye(4).tolist(), "dtype": "float64"}
    metadata.update(
        {
            "poses/rig/static_poses/.zgroup": {"zarr_format": 2},
            "poses/rig/static_poses/.zattrs": {
                "('a', 'b')": entry,
                "('b', 'a')": entry,
            },
            "poses/rig/dynamic_poses/.zgroup": {"zarr_format": 2},
            "poses/rig/dynamic_poses/.zattrs": {},
        }
    )
    path = tmp_path / "bad-poses.ncore4.zarr"
    _write_custom_directory(path, metadata, {})
    with pytest.raises(ValueError, match="inverse duplicate"):
        sceneio.read_ncore_semantic_component(
            path, sceneio.NCoreSelection("poses", "rig")
        )


def test_semantic_intrinsics_profile_validates_camera_and_lidar_models(tmp_path):
    metadata = _profile_metadata("intrinsics")
    metadata.update(
        {
            "intrinsics/default/cameras/.zgroup": {"zarr_format": 2},
            "intrinsics/default/lidars/.zgroup": {"zarr_format": 2},
            "intrinsics/default/cameras/front/.zgroup": {"zarr_format": 2},
            "intrinsics/default/cameras/front/.zattrs": {
                "camera_model_type": "opencv-fisheye",
                "camera_model_parameters": {
                    "resolution": [640, 480],
                    "shutter_type": "GLOBAL",
                    "external_distortion_parameters": None,
                    "principal_point": [320.0, 240.0],
                    "focal_length": [410.0, 411.0],
                    "radial_coeffs": [0.1, -0.01, 0.0, 0.0],
                    "max_angle": 1.4,
                },
            },
            "intrinsics/default/lidars/top/.zgroup": {"zarr_format": 2},
            "intrinsics/default/lidars/top/.zattrs": {
                "lidar_model_type": "row-offset-spinning",
                "lidar_model_parameters": {
                    "spinning_frequency_hz": 10.0,
                    "spinning_direction": "ccw",
                    "n_rows": 2,
                    "n_columns": 3,
                    "row_elevations_rad": [0.2, -0.2],
                    "column_azimuths_rad": [-1.0, 0.0, 1.0],
                    "row_azimuth_offsets_rad": [0.0, 0.01],
                },
            },
        }
    )
    path = tmp_path / "intrinsics-profile.ncore4.zarr"
    _write_custom_directory(path, metadata, {})

    semantic = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection("intrinsics", "default")
    )
    assert semantic.profile == "intrinsics/v1"
    assert semantic.item("camera_intrinsics", "front").attributes[
        "camera_model_type"
    ] == "opencv-fisheye"
    assert semantic.item("lidar_intrinsics", "top").attributes[
        "lidar_model_type"
    ] == "row-offset-spinning"


def test_semantic_masks_and_unknown_component_profiles_are_lossless(tmp_path):
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    image[..., 1] = 255
    encoded = bytes(sceneio._core.write_png(sceneio._core.image(image)))
    metadata = _profile_metadata("masks")
    dtype = f"|S{len(encoded)}"
    metadata.update(
        {
            "masks/default/cameras/.zgroup": {"zarr_format": 2},
            "masks/default/cameras/front/.zgroup": {"zarr_format": 2},
            "masks/default/cameras/front/.zattrs": {"mask_names": ["valid"]},
            "masks/default/cameras/front/valid/.zarray": {
                "chunks": [],
                "compressor": None,
                "dtype": dtype,
                "fill_value": "",
                "filters": None,
                "order": "C",
                "shape": [],
                "zarr_format": 2,
            },
            "masks/default/cameras/front/valid/.zattrs": {"format": "png"},
        }
    )
    path = tmp_path / "masks-profile.ncore4.zarr"
    _write_custom_directory(
        path,
        metadata,
        {"masks/default/cameras/front/valid/0": encoded},
    )
    semantic = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection("masks", "default")
    )
    mask = semantic.item("camera_mask", "front/valid")
    assert semantic.profile == "masks/v1"
    assert bytes(mask.array("data")) == encoded

    custom_metadata = _profile_metadata("velocity", instance="rig")
    custom = tmp_path / "custom-profile.ncore4.zarr"
    _write_custom_directory(custom, custom_metadata, {})
    generic = sceneio.read_ncore_semantic_component(
        custom, sceneio.NCoreSelection("velocity", "rig")
    )
    assert generic.profile == "generic/v1"
    assert generic.items[0].attributes["groups"][""]["component_name"] == (
        "velocity"
    )


def _camera_profile_fixture() -> tuple[dict[str, object], dict[str, bytes]]:
    metadata = _profile_metadata("cameras", instance="front")
    metadata.update(
        {
            "cameras/front/frames/.zgroup": {"zarr_format": 2},
            "cameras/front/frames/.zattrs": {
                "frames_timestamps_us": [[100, 110], [110, 120]]
            },
        }
    )
    payloads: dict[str, bytes] = {}
    for timestamp, color in ((110, 32), (120, 64)):
        base = f"cameras/front/frames/{timestamp}"
        metadata[f"{base}/.zgroup"] = {"zarr_format": 2}
        metadata[f"{base}/generic_data/.zgroup"] = {"zarr_format": 2}
        metadata[f"{base}/generic_data/.zattrs"] = {"exposure": timestamp}
        pixels = np.full((2, 3, 3), color, dtype=np.uint8)
        encoded = bytes(sceneio._core.write_png(sceneio._core.image(pixels)))
        _add_array(
            metadata,
            payloads,
            f"{base}/image",
            np.array(encoded, dtype=f"|S{len(encoded)}"),
            attributes={"format": "png"},
        )
    return metadata, payloads


def test_semantic_camera_profile_handles_frames_selection_and_empty_sensor(tmp_path):
    metadata, payloads = _camera_profile_fixture()
    path = tmp_path / "camera-profile.ncore4.zarr"
    _write_custom_directory(path, metadata, payloads)

    semantic = sceneio.read_ncore_semantic_component(
        path,
        sceneio.NCoreSelection("cameras", "front", frames=(1, 2)),
    )
    assert semantic.profile == "cameras/v1"
    assert tuple(item.id for item in semantic.items) == ("120",)
    frame = semantic.items[0]
    assert frame.timestamp_interval_us == (110, 120)
    assert frame.attributes["image_format"] == "png"
    assert frame.attributes["generic_meta_data"] == {"exposure": 120}

    empty_metadata = _profile_metadata("cameras", instance="empty")
    empty_metadata.update(
        {
            "cameras/empty/frames/.zgroup": {"zarr_format": 2},
            "cameras/empty/frames/.zattrs": {"frames_timestamps_us": []},
        }
    )
    empty = tmp_path / "empty-camera.ncore4.zarr"
    _write_custom_directory(empty, empty_metadata, {})
    loaded = sceneio.read_ncore_semantic_component(
        empty, sceneio.NCoreSelection("cameras", "empty")
    )
    assert loaded.items == ()


def _ray_profile_fixture(
    component_name: str,
) -> tuple[dict[str, object], dict[str, bytes]]:
    metadata = _profile_metadata(component_name, instance="top")
    frame = f"{component_name}/top/frames/120"
    metadata.update(
        {
            f"{component_name}/top/frames/.zgroup": {"zarr_format": 2},
            f"{component_name}/top/frames/.zattrs": {
                "frames_timestamps_us": [[100, 120]]
            },
            f"{frame}/.zgroup": {"zarr_format": 2},
            f"{frame}/generic_data/.zgroup": {"zarr_format": 2},
            f"{frame}/generic_data/.zattrs": {"weather": "clear"},
            f"{frame}/ray_bundle/.zgroup": {"zarr_format": 2},
            f"{frame}/ray_bundle/.zattrs": {"n_rays": 2},
            f"{frame}/ray_bundle_returns/.zgroup": {"zarr_format": 2},
            f"{frame}/ray_bundle_returns/.zattrs": {"n_returns": 2},
        }
    )
    payloads: dict[str, bytes] = {}
    direction = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    timestamps = np.array([105, 118], dtype=np.uint64)
    distance = np.array([[1.0, 2.0], [3.0, np.nan]], dtype=np.float32)
    _add_array(metadata, payloads, f"{frame}/ray_bundle/direction", direction)
    _add_array(
        metadata, payloads, f"{frame}/ray_bundle/timestamp_us", timestamps
    )
    if component_name == "lidars":
        _add_array(
            metadata,
            payloads,
            f"{frame}/ray_bundle/model_element",
            np.array([[0, 1], [1, 1]], dtype=np.uint16),
        )
    _add_array(
        metadata,
        payloads,
        f"{frame}/ray_bundle_returns/distance_m",
        distance,
    )
    if component_name == "lidars":
        intensity = np.array([[0.1, 0.2], [0.3, np.nan]], dtype=np.float32)
        _add_array(
            metadata,
            payloads,
            f"{frame}/ray_bundle_returns/intensity",
            intensity,
        )
    valid = np.packbits(~np.isnan(distance))
    _add_array(
        metadata,
        payloads,
        f"{frame}/ray_bundle_returns_valid_mask_packed",
        valid,
        attributes={"n_returns": 2, "n_rays": 2},
    )
    return metadata, payloads


@pytest.mark.parametrize("component_name", ["lidars", "radars"])
def test_semantic_ray_sensor_profiles_validate_returns(tmp_path, component_name):
    metadata, payloads = _ray_profile_fixture(component_name)
    path = tmp_path / f"{component_name}.ncore4.zarr"
    _write_custom_directory(path, metadata, payloads)
    semantic = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection(component_name, "top")
    )
    assert semantic.profile == f"{component_name}/v1"
    frame = semantic.items[0]
    assert frame.attributes["n_rays"] == 2
    assert frame.attributes["n_returns"] == 2
    assert frame.reference_frame_id == "top"

    invalid = payloads.copy()
    invalid_distance = np.array(
        [[1.0, 2.0], [3.0, 4.0]], dtype=np.float32
    )
    invalid[
        f"{component_name}/top/frames/120/ray_bundle_returns/distance_m/0.0"
    ] = invalid_distance.tobytes()
    bad = tmp_path / f"bad-{component_name}.ncore4.zarr"
    _write_custom_directory(bad, metadata, invalid)
    with pytest.raises(ValueError, match=r"valid mask disagrees|absent values"):
        sceneio.read_ncore_semantic_component(
            bad, sceneio.NCoreSelection(component_name, "top")
        )


def _point_cloud_profile_fixture() -> tuple[dict[str, object], dict[str, bytes]]:
    metadata = _profile_metadata("point_clouds", instance="native")
    metadata.update(
        {
            "point_clouds/native/pcs/.zgroup": {"zarr_format": 2},
            "point_clouds/native/pcs/.zattrs": {
                "coordinate_unit": "METERS",
                "attribute_schemas": {
                    "confidence": {
                        "transform_type": "INVARIANT",
                        "dtype": "float32",
                        "shape_suffix": [],
                    }
                },
            },
        }
    )
    payloads: dict[str, bytes] = {}
    _add_array(
        metadata,
        payloads,
        "point_clouds/native/pc_timestamps_us",
        np.array([150, 120, 150], dtype=np.uint64),
    )
    for index in range(3):
        base = f"point_clouds/native/pcs/{index}"
        metadata[f"{base}/.zgroup"] = {"zarr_format": 2}
        metadata[f"{base}/.zattrs"] = {
            "reference_frame_id": "rig",
            "generic_meta_data": {"index": index},
        }
        metadata[f"{base}/generic_data/.zgroup"] = {"zarr_format": 2}
        _add_array(
            metadata,
            payloads,
            f"{base}/xyz",
            np.array([[index, 0, 1], [index, 2, 3]], dtype=np.float32),
        )
        _add_array(
            metadata,
            payloads,
            f"{base}/confidence",
            np.array([0.5, 0.75], dtype=np.float32),
        )
    return metadata, payloads


def test_semantic_point_cloud_profile_preserves_insertion_order_and_duplicates(tmp_path):
    metadata, payloads = _point_cloud_profile_fixture()
    path = tmp_path / "point-clouds.ncore4.zarr"
    _write_custom_directory(path, metadata, payloads)
    full = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection("point_clouds", "native")
    )
    assert tuple(item.timestamp_us for item in full.items) == (150, 120, 150)
    selected = sceneio.read_ncore_semantic_component(
        path,
        sceneio.NCoreSelection(
            "point_clouds", "native", timestamps_us=(140, 160)
        ),
    )
    assert tuple(item.id for item in selected.items) == ("0", "2")
    assert tuple(item.timestamp_us for item in selected.items) == (150, 150)
    np.testing.assert_array_equal(
        selected.items[1].array("xyz")[:, 0], np.array([2, 2])
    )


def test_semantic_cuboids_and_quantized_camera_labels(tmp_path):
    cuboid_metadata = _profile_metadata("cuboids")
    cuboid_metadata.update(
        {
            "cuboids/default/cuboids/.zgroup": {"zarr_format": 2},
            "cuboids/default/cuboids/.zattrs": {
                "cuboid_track_observations": [
                    {
                        "track_id": "car-7",
                        "class_id": "vehicle",
                        "timestamp_us": 130,
                        "reference_frame_id": "rig",
                        "reference_frame_timestamp_us": 125,
                        "bbox3": {
                            "centroid": [1.0, 2.0, 3.0],
                            "dim": [4.0, 2.0, 1.5],
                            "rot": [0.0, 0.0, 0.2],
                        },
                        "source": "GT_ANNOTATION",
                        "source_version": "v2",
                    }
                ]
            },
        }
    )
    cuboids = tmp_path / "cuboids.ncore4.zarr"
    _write_custom_directory(cuboids, cuboid_metadata, {})
    cuboid = sceneio.read_ncore_semantic_component(
        cuboids, sceneio.NCoreSelection("cuboids", "default")
    ).items[0]
    assert cuboid.attributes["track_id"] == "car-7"
    np.testing.assert_allclose(
        cuboid.array("bbox3"), [1, 2, 3, 4, 2, 1.5, 0, 0, 0.2]
    )

    label_metadata = _profile_metadata("camera_labels", instance="depth@front")
    label_metadata.update(
        {
            "camera_labels/depth@front/labels/.zgroup": {"zarr_format": 2},
            "camera_labels/depth@front/labels/.zattrs": {
                "descriptor": {
                    "camera_id": "front",
                    "label_type": {
                        "category": "DEPTH",
                        "qualifier": "z",
                        "unit": "METERS",
                    },
                    "label_schema": {
                        "dtype": "float32",
                        "shape_suffix": [],
                        "encoding": "RAW",
                        "encoded_format": None,
                        "quantization": {
                            "quantized_dtype": "uint16",
                            "scale": 0.01,
                            "offset": 0.0,
                        },
                    },
                    "label_source": "GT_SYNTHETIC",
                }
            },
        }
    )
    label_payloads: dict[str, bytes] = {}
    _add_array(
        label_metadata,
        label_payloads,
        "camera_labels/depth@front/timestamps_us",
        np.array([120, 160], dtype=np.uint64),
    )
    for timestamp, value in ((120, 100), (160, 250)):
        base = f"camera_labels/depth@front/labels/{timestamp}"
        label_metadata[f"{base}/.zgroup"] = {"zarr_format": 2}
        label_metadata[f"{base}/.zattrs"] = {
            "generic_meta_data": {"frame": timestamp}
        }
        _add_array(
            label_metadata,
            label_payloads,
            f"{base}/data",
            np.full((2, 3), value, dtype=np.uint16),
        )
    labels = tmp_path / "labels.ncore4.zarr"
    _write_custom_directory(labels, label_metadata, label_payloads)
    semantic = sceneio.read_ncore_semantic_component(
        labels,
        sceneio.NCoreSelection(
            "camera_labels", "depth@front", timestamps_us=(150, 170)
        ),
    )
    assert semantic.profile == "camera_labels/v1"
    assert tuple(item.id for item in semantic.items) == ("160",)
    assert semantic.items[0].attributes["logical_dtype"] == "float32"
    assert semantic.items[0].array("data").dtype == np.dtype("uint16")


def test_pinned_upstream_standard_profile_fixture_is_accepted_exactly():
    path = FIXTURES / "ncore_v4_standard_v1.ncore4.zarr.itar"
    assert sceneio.detect(path) == "ncore_v4"
    expected = {
        ("poses", "rig"): ("poses/v1", 2),
        ("intrinsics", "default"): ("intrinsics/v1", 2),
        ("masks", "default"): ("masks/v1", 1),
        ("cameras", "front"): ("cameras/v1", 1),
        ("lidars", "top"): ("lidars/v1", 1),
        ("radars", "radar"): ("radars/v1", 1),
        ("cuboids", "default"): ("cuboids/v1", 1),
        ("point_clouds", "native"): ("point_clouds/v1", 3),
        ("camera_labels", "depth@front"): ("camera_labels/v1", 2),
    }
    for (component, instance), (profile, count) in expected.items():
        semantic = sceneio.read_ncore_semantic_component(
            path, sceneio.NCoreSelection(component, instance)
        )
        assert semantic.profile == profile
        assert len(semantic.items) == count
    point_clouds = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection("point_clouds", "native")
    )
    assert tuple(item.timestamp_us for item in point_clouds.items) == (
        150,
        120,
        150,
    )
    labels = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection("camera_labels", "depth@front")
    )
    np.testing.assert_array_equal(
        labels.item("camera_label", "160").array("data"),
        np.full((2, 3), 250, dtype=np.uint16),
    )
    camera = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection("cameras", "front")
    ).items[0].to_sceneio()
    assert isinstance(camera, sceneio.Image)
    np.testing.assert_array_equal(camera.pixels, np.full((2, 3, 3), 64))
    mask = sceneio.read_ncore_semantic_component(
        path, sceneio.NCoreSelection("masks", "default")
    ).items[0].to_sceneio()
    assert isinstance(mask, sceneio.data.Mask)
    np.testing.assert_array_equal(mask.mask, [[False, True], [True, False]])

    point_item = sceneio.NCoreItem(
        kind="point_cloud",
        id="metric",
        arrays={"xyz": np.array([[1, 2, 3]], dtype=np.float32)},
        attributes={"coordinate_unit": "METERS", "attribute_schemas": {}},
        timestamp_us=120,
        reference_frame_id="rig",
    )
    cloud = sceneio.project_ncore_item(point_item)
    assert isinstance(cloud, sceneio.PointCloud)
    np.testing.assert_array_equal(cloud.positions, [[1, 2, 3]])
    with pytest.raises(ValueError, match="no exact PointCloud payload projection"):
        sceneio.project_ncore_item(point_clouds.items[0])


def test_sensor_component_frame_and_timestamp_selection(tmp_path):
    path = tmp_path / "camera.ncore4.zarr"
    metadata, chunks = _sensor_metadata()
    _write_custom_directory(path, metadata, chunks)

    frames = sceneio.read_ncore_component(
        path,
        NCoreSelection("cameras", "front", frames=(1, 3)),
    )
    assert frames.selected_items == ("120", "130")
    assert set(frames.arrays) == {
        "frames/120/data",
        "frames/130/data",
    }
    np.testing.assert_array_equal(
        frames.array("frames/120/data"),
        np.full((2, 2), 1, dtype=np.uint8),
    )
    assert {group.name for group in frames.groups} == {
        "",
        "frames",
        "frames/120",
        "frames/130",
    }

    timestamps = sceneio.read_ncore_component(
        path,
        NCoreSelection(
            "cameras",
            "front",
            timestamps_us=(111, 119),
        ),
    )
    assert timestamps.selected_items == ("120",)
    assert tuple(timestamps.arrays) == ("frames/120/data",)
    with pytest.raises(ValueError, match="available count"):
        sceneio.read_ncore_component(
            path,
            NCoreSelection("cameras", "front", frames=(2, 4)),
        )


def test_component_selection_rejects_non_temporal_component(tmp_path):
    path = tmp_path / "poses.ncore4.zarr"
    _write_directory(path, _metadata())
    with pytest.raises(ValueError, match="does not define"):
        sceneio.read_ncore_component(
            path,
            NCoreSelection("poses", "rig", frames=(0, 1)),
        )


def _tree_payloads(path: Path) -> dict[str, bytes]:
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def _assert_materialized_equal(expected, actual) -> None:
    assert expected.sequence_id == actual.sequence_id
    assert expected.timestamp_interval_us == actual.timestamp_interval_us
    assert expected.generic_metadata == actual.generic_metadata
    assert tuple(item.component.id for item in expected.components) == tuple(
        item.component.id for item in actual.components
    )
    for left, right in zip(expected.components, actual.components, strict=True):
        assert left.component.version == right.component.version
        assert left.component.group == right.component.group
        assert left.component.generic_metadata == right.component.generic_metadata
        assert tuple(
            (group.name, group.attributes) for group in left.groups
        ) == tuple((group.name, group.attributes) for group in right.groups)
        assert tuple(left.arrays) == tuple(right.arrays)
        for name in left.arrays:
            assert left.arrays[name].dtype == right.arrays[name].dtype
            assert left.arrays[name].shape == right.arrays[name].shape
            assert left.arrays[name].tobytes() == right.arrays[name].tobytes()


@pytest.mark.parametrize("storage", ["directory", "itar"])
def test_writer_round_trips_all_standard_profiles_and_is_deterministic(
    tmp_path,
    storage,
):
    source = FIXTURES / "ncore_v4_standard_v1.ncore4.zarr.itar"
    expected = sceneio.materialize_ncore_v4(source)
    first = tmp_path / f"first-{storage}"
    second = tmp_path / f"second-{storage}"

    sceneio.write_ncore_v4(expected, first, storage=storage)
    sceneio.write_ncore_v4(expected, second, storage=storage)

    assert _tree_payloads(first) == _tree_payloads(second)
    _assert_materialized_equal(expected, sceneio.materialize_ncore_v4(first))
    manifest = first / "dataset.ncore4.json"
    _assert_materialized_equal(
        expected,
        sceneio.materialize_ncore_v4(manifest),
    )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert document["sequence_id"] == expected.sequence_id
    assert len(document["component_stores"]) == 1
    assert len(document["component_stores"][0]["md5"]) == 32


def test_registry_writer_defaults_to_indexed_tar_and_reports_capability(tmp_path):
    source = FIXTURES / "ncore_v4_standard_v1.ncore4.zarr.itar"
    dataset = sceneio.read(source)
    destination = tmp_path / "export"

    sceneio.write(dataset, destination, format="ncore_v4")

    assert (destination / "dataset.ncore4.zarr.itar").is_file()
    assert sceneio.detect(destination) == "ncore_v4"
    capability = sceneio.capabilities("ncore_v4")
    assert capability.can_write
    assert capability.streams_write
    assert "deterministic_indexed_tar_write" in capability.supported_features


def test_writer_preserves_multiple_component_groups_and_manifest(tmp_path):
    calibration = tmp_path / "calibration.ncore4.zarr"
    sensors = tmp_path / "sensors.ncore4.zarr"
    _write_directory(calibration, _metadata(group="calibration"))
    metadata = _metadata(group="sensors")
    metadata["poses/rig/.zattrs"] = {
        **metadata["poses/rig/.zattrs"],
        "component_instance_name": "world",
    }
    for suffix in (".zgroup", ".zattrs"):
        metadata[f"poses/world/{suffix}"] = metadata.pop(
            f"poses/rig/{suffix}"
        )
    for suffix in (".zarray", ".zattrs"):
        metadata[f"poses/world/value/{suffix}"] = metadata.pop(
            f"poses/rig/value/{suffix}"
        )
    _write_directory(sensors, metadata)
    left = sceneio.materialize_ncore_v4(calibration)
    right = sceneio.materialize_ncore_v4(sensors)
    complete = sceneio.NCoreDatasetData(
        sequence_id=left.sequence_id,
        timestamp_interval_us=left.timestamp_interval_us,
        generic_metadata=left.generic_metadata,
        components=left.components + right.components,
    )

    destination = tmp_path / "grouped"
    sceneio.write_ncore_v4(complete, destination, storage="directory")

    catalog = sceneio.read(destination)
    assert tuple(store.group for store in catalog.stores) == (
        "calibration",
        "sensors",
    )
    assert tuple(component.id for component in catalog.components) == (
        "poses:rig",
        "poses:world",
    )
    assert len(tuple(destination.glob("*.zarr"))) == 2
    manifest = sceneio.read(destination / "dataset.ncore4.json")
    assert manifest.components == catalog.components


def test_writer_refuses_partial_components_and_preserves_destination(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.ncore4.zarr"
    metadata, chunks = _sensor_metadata()
    _write_custom_directory(source, metadata, chunks)
    full = sceneio.materialize_ncore_v4(source)
    partial = replace(
        full.components[0],
        selection=NCoreSelection("cameras", "front", frames=(0, 1)),
        selected_items=("110",),
    )
    with pytest.raises(ValueError, match="partial selection"):
        sceneio.NCoreDatasetData(
            sequence_id=full.sequence_id,
            timestamp_interval_us=full.timestamp_interval_us,
            generic_metadata=full.generic_metadata,
            components=(partial,),
        )

    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "marker.txt"
    marker.write_text("original", encoding="utf-8")
    from sceneio.io._ncore import writer as ncore_writer

    original_replace = ncore_writer._replace_path
    calls = 0

    def interrupted_replace(source_path, destination_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replacement interruption")
        original_replace(source_path, destination_path)

    monkeypatch.setattr(ncore_writer, "_replace_path", interrupted_replace)
    with pytest.raises(OSError, match="injected replacement"):
        sceneio.write_ncore_v4(full, destination)
    assert marker.read_text(encoding="utf-8") == "original"
    assert not tuple(tmp_path.glob(".existing.sceneio-previous-*"))


def _generic_dataset_data(
    arrays: dict[str, np.ndarray],
    chunks: dict[str, tuple[int, ...]],
):
    component = sceneio.NCoreComponent(
        "custom_arrays",
        "randomized",
        "v7",
        "",
        0,
        generic_metadata={"purpose": "writer-verification"},
        arrays=tuple(
            sceneio.NCoreArray(
                name,
                value.shape,
                value.dtype.str,
                chunks[name],
                {"index": index},
            )
            for index, (name, value) in enumerate(arrays.items())
        ),
    )
    data = sceneio.NCoreComponentData(
        component,
        sceneio.NCoreSelection("custom_arrays", "randomized", group=""),
        arrays,
        (
            sceneio.NCoreGroup(
                "",
                {
                    "component_name": "custom_arrays",
                    "component_instance_name": "randomized",
                    "component_version": "v7",
                    "generic_meta_data": {
                        "purpose": "writer-verification"
                    },
                },
            ),
        ),
    )
    return sceneio.NCoreDatasetData(
        "randomized-sequence",
        (10, 20),
        {"seed": 420},
        (data,),
    )


def test_writer_randomized_mixed_dtype_chunk_differential(tmp_path):
    rng = np.random.default_rng(420)
    structured = np.dtype([("xy", ">f4", (2,)), ("id", "<u2")])
    arrays = {
        "a_bool": rng.integers(0, 2, (7, 5), dtype=np.uint8).astype(bool),
        "b_u8": rng.integers(0, 256, 17, dtype=np.uint8),
        "c_be_i2": rng.integers(-2000, 2000, (9, 3), dtype=np.int16).astype(
            ">i2"
        ),
        "d_u64": rng.integers(0, 1 << 40, 11, dtype=np.uint64),
        "e_f32": rng.standard_normal((6, 4)).astype(np.float32),
        "f_c64": (
            rng.standard_normal(13) + 1j * rng.standard_normal(13)
        ).astype(np.complex64),
        "g_struct": np.array(
            [([1.25, 2.5], 7), ([3.75, 4.0], 9)], dtype=structured
        ),
        "h_scalar": np.array(23, dtype=np.int32),
        "i_empty": np.empty((0, 3), dtype=np.float64),
    }
    chunks = {
        "a_bool": (4, 3),
        "b_u8": (6,),
        "c_be_i2": (4, 2),
        "d_u64": (5,),
        "e_f32": (5, 3),
        "f_c64": (4,),
        "g_struct": (1,),
        "h_scalar": (),
        "i_empty": (2, 3),
    }
    expected = _generic_dataset_data(arrays, chunks)
    for storage in ("directory", "itar"):
        destination = tmp_path / storage
        sceneio.write_ncore_v4(expected, destination, storage=storage)
        _assert_materialized_equal(
            expected,
            sceneio.materialize_ncore_v4(destination),
        )

    conflict = replace(
        expected.components[0],
        groups=(*expected.components[0].groups, sceneio.NCoreGroup("a_bool")),
    )
    malformed = replace(expected, components=(conflict,))
    with pytest.raises(ValueError, match="both an array and a group"):
        sceneio.write_ncore_v4(malformed, tmp_path / "conflict")

    wrong_root = replace(
        expected.components[0],
        groups=(
            sceneio.NCoreGroup(
                "",
                {
                    "component_name": "different",
                    "component_instance_name": "randomized",
                    "component_version": "v7",
                    "generic_meta_data": {
                        "purpose": "writer-verification"
                    },
                },
            ),
        ),
    )
    with pytest.raises(ValueError, match="disagrees with the component catalog"):
        sceneio.write_ncore_v4(
            replace(expected, components=(wrong_root,)),
            tmp_path / "wrong-root",
        )
    with pytest.raises(ValueError, match="relative"):
        replace(
            expected.components[0].component.arrays[0],
            name=r"nested\array",
        )
    with pytest.raises(ValueError, match="relative"):
        sceneio.NCoreGroup(r"nested\group")


def test_writer_large_generated_payload_has_chunk_bounded_allocation(tmp_path):
    positions = np.arange(2_000_000 * 3, dtype=np.float32).reshape(
        2_000_000, 3
    )
    dataset = _generic_dataset_data(
        {"positions": positions},
        {"positions": (65_536, 3)},
    )
    warm = _generic_dataset_data(
        {"positions": positions[:1]},
        {"positions": (1, 3)},
    )
    sceneio.write_ncore_v4(warm, tmp_path / "warm")

    tracemalloc.start()
    sceneio.write_ncore_v4(dataset, tmp_path / "large")
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert positions.nbytes == 24_000_000
    assert peak < 8 * 1024 * 1024
    actual = sceneio.materialize_ncore_v4(tmp_path / "large")
    assert actual.components[0].array("positions").tobytes() == positions.tobytes()
