# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic transactional writers for repository-owned NCore V4 data."""

from __future__ import annotations

import hashlib
import json
import lzma
import os
import shutil
import struct
import tarfile
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import suppress
from itertools import product
from pathlib import Path

import numpy as np

from sceneio.io._ncore.component_io import materialize_ncore_v4
from sceneio.io._ncore.model import (
    JsonValue,
    NCoreComponentData,
    NCoreDataset,
    NCoreDatasetData,
)

_METADATA_KEY = ".zmetadata.cbor.xz"
_TAR_HEADER = struct.Struct("<4sIQI")
_TAR_BLOCK_SIZE = 512
_CHUNK_BYTES = 128 * 512


def _require_storage_dependencies():
    try:
        import cbor2
        from numcodecs import Blosc
    except ModuleNotFoundError:
        raise RuntimeError(
            "NCore writing requires the optional dependency; install sceneio[ncore]"
        ) from None
    return cbor2, Blosc


def _plain_json(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {
            name: _plain_json(value[name])
            for name in sorted(value)
        }
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _component_root_attributes(data: NCoreComponentData) -> dict[str, object]:
    attributes = _plain_json(data.group().attributes)
    assert isinstance(attributes, dict)
    required = {
        "component_instance_name": data.component.instance,
        "component_name": data.component.name,
        "component_version": data.component.version,
        "generic_meta_data": _plain_json(data.component.generic_metadata),
    }
    for name, expected in required.items():
        if name in attributes and attributes[name] != expected:
            raise ValueError(
                f"NCore component {data.component.id}: root attribute {name!r} "
                "disagrees with the component catalog"
            )
        attributes[name] = expected
    return {name: attributes[name] for name in sorted(attributes)}


def _validate_path_part(value: str, context: str) -> None:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{context} must be one non-empty path segment")


def _validate_component_layout(data: NCoreComponentData) -> None:
    _validate_path_part(data.component.name, "NCore component name")
    _validate_path_part(data.component.instance, "NCore component instance")
    arrays = set(data.arrays)
    groups = {group.name for group in data.groups if group.name}
    conflicts = arrays & groups
    if conflicts:
        name = min(conflicts)
        raise ValueError(
            f"NCore component {data.component.id}: {name!r} cannot be both an "
            "array and a group"
        )
    for array_name in sorted(arrays):
        marker = array_name + "/"
        descendant = next(
            (
                name
                for name in sorted(arrays | groups)
                if name.startswith(marker)
            ),
            None,
        )
        if descendant is not None:
            raise ValueError(
                f"NCore component {data.component.id}: array {array_name!r} "
                f"cannot contain {descendant!r}"
            )


def _write_consolidated_metadata(store: Path) -> None:
    cbor2, _blosc = _require_storage_dependencies()
    metadata: dict[str, object] = {}
    for path in sorted(store.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.name not in {".zarray", ".zattrs", ".zgroup"}:
            continue
        key = path.relative_to(store).as_posix()
        metadata[key] = json.loads(path.read_text(encoding="utf-8"))
    document = {
        "zarr_consolidated_format": 1,
        "metadata": metadata,
    }
    encoded = cbor2.dumps(document, canonical=True)
    (store / _METADATA_KEY).write_bytes(
        lzma.compress(encoded, format=lzma.FORMAT_XZ, preset=0)
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _dtype_document(dtype: np.dtype) -> object:
    if dtype.fields is None:
        return dtype.str

    def plain(value: object) -> object:
        if isinstance(value, tuple):
            return [plain(item) for item in value]
        if isinstance(value, list):
            return [plain(item) for item in value]
        return value

    return plain(dtype.descr)


def _chunk_coordinates(
    shape: tuple[int, ...],
    chunks: tuple[int, ...],
):
    if not shape:
        yield ()
        return
    if any(size == 0 for size in shape):
        return
    yield from product(
        *(
            range((size + chunk - 1) // chunk)
            for size, chunk in zip(shape, chunks, strict=True)
        )
    )


def _write_array(
    root: Path,
    name: str,
    value: np.ndarray,
    chunks: tuple[int, ...],
    attributes: Mapping[str, JsonValue],
    compressor,
) -> None:
    target = root.joinpath(*name.split("/"))
    target.mkdir(parents=True, exist_ok=False)
    _write_json(
        target / ".zarray",
        {
            "chunks": list(chunks),
            "compressor": compressor.get_config(),
            "dimension_separator": ".",
            "dtype": _dtype_document(value.dtype),
            "fill_value": None,
            "filters": None,
            "order": "C",
            "shape": list(value.shape),
            "zarr_format": 2,
        },
    )
    plain_attributes = _plain_json(attributes)
    assert isinstance(plain_attributes, dict)
    if plain_attributes:
        _write_json(target / ".zattrs", plain_attributes)
    for coordinates in _chunk_coordinates(value.shape, chunks):
        source_slices = tuple(
            slice(index * chunk, min((index + 1) * chunk, size))
            for index, chunk, size in zip(
                coordinates,
                chunks,
                value.shape,
                strict=True,
            )
        )
        chunk = np.zeros(chunks, dtype=value.dtype, order="C")
        if coordinates:
            edge_slices = tuple(
                slice(0, selected.stop - selected.start)
                for selected in source_slices
            )
            chunk[edge_slices] = value[source_slices]
            chunk_name = ".".join(map(str, coordinates))
        else:
            chunk[...] = value
            chunk_name = "0"
        encoded = compressor.encode(chunk.tobytes(order="C"))
        (target / chunk_name).write_bytes(bytes(encoded))


def _write_store_directory(
    components: tuple[NCoreComponentData, ...],
    destination: Path,
    dataset: NCoreDatasetData,
    group_name: str,
) -> None:
    _cbor2, Blosc = _require_storage_dependencies()
    root_attributes = {
        "component_group_name": group_name,
        "generic_meta_data": _plain_json(dataset.generic_metadata),
        "sequence_id": dataset.sequence_id,
        "sequence_timestamp_interval_us": {
            "start": dataset.timestamp_interval_us[0],
            "stop": dataset.timestamp_interval_us[1],
        },
        "version": "v4",
    }
    destination.mkdir()
    _write_json(destination / ".zgroup", {"zarr_format": 2})
    _write_json(destination / ".zattrs", root_attributes)
    compressor = Blosc(cname="lz4", clevel=5, shuffle=Blosc.BITSHUFFLE)
    for data in sorted(
        components,
        key=lambda value: (value.component.name, value.component.instance),
    ):
        _validate_component_layout(data)
        component_name_root = destination / data.component.name
        component_root = component_name_root / data.component.instance
        if not component_name_root.exists():
            component_name_root.mkdir()
            _write_json(
                component_name_root / ".zgroup",
                {"zarr_format": 2},
            )
        component_root.mkdir()
        _write_json(component_root / ".zgroup", {"zarr_format": 2})
        _write_json(
            component_root / ".zattrs",
            _component_root_attributes(data),
        )
        array_names = set(data.arrays)
        for group in sorted(data.groups, key=lambda value: value.name):
            if not group.name:
                continue
            target = component_root.joinpath(*group.name.split("/"))
            target.mkdir(parents=True, exist_ok=True)
            cursor = target
            while cursor != component_root:
                marker = cursor / ".zgroup"
                if not marker.exists():
                    _write_json(marker, {"zarr_format": 2})
                cursor = cursor.parent
            attributes = _plain_json(group.attributes)
            assert isinstance(attributes, dict)
            if attributes:
                _write_json(target / ".zattrs", attributes)
        descriptors = {item.name: item for item in data.component.arrays}
        for name in sorted(data.arrays):
            value = data.arrays[name]
            descriptor = descriptors[name]
            parent = "/".join(name.split("/")[:-1])
            if parent:
                cursor = component_root.joinpath(*parent.split("/"))
                cursor.mkdir(parents=True, exist_ok=True)
                while cursor != component_root:
                    marker = cursor / ".zgroup"
                    if not marker.exists() and cursor.relative_to(
                        component_root
                    ).as_posix() not in array_names:
                        _write_json(marker, {"zarr_format": 2})
                    cursor = cursor.parent
            _write_array(
                component_root,
                name,
                value,
                descriptor.chunks,
                descriptor.attributes,
                compressor,
            )
    _write_consolidated_metadata(destination)


def _append_index(path: Path) -> None:
    cbor2, _blosc = _require_storage_dependencies()
    with tarfile.open(path, mode="r") as archive:
        records = tuple(
            sorted(
                (
                    (member.name, member.offset_data, member.size)
                    for member in archive.getmembers()
                    if member.isfile()
                ),
                key=lambda item: item[1],
            )
        )
    table = {
        "items": [item[0] for item in records],
        "offset_datas": [item[1] for item in records],
        "sizes": [item[2] for item in records],
    }
    encoded = lzma.compress(
        cbor2.dumps(table, canonical=True),
        format=lzma.FORMAT_XZ,
        preset=0,
    )
    with path.open("ab") as stream:
        index_offset = stream.tell()
        stream.write(encoded)
        remainder = stream.tell() % _TAR_BLOCK_SIZE
        if remainder:
            stream.write(bytes(_TAR_BLOCK_SIZE - remainder))
        stream.write(_TAR_HEADER.pack(b"itar", 1, index_offset, len(encoded)))
        remainder = stream.tell() % _TAR_BLOCK_SIZE
        if remainder:
            stream.write(bytes(_TAR_BLOCK_SIZE - remainder))


def _write_indexed_tar(source: Path, destination: Path) -> None:
    with tarfile.open(destination, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            name = path.relative_to(source).as_posix()
            info = tarfile.TarInfo(name)
            info.size = path.stat().st_size
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            with path.open("rb") as stream:
                archive.addfile(info, stream)
    _append_index(destination)


def _update_file_digest(path: Path, digest) -> None:
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
            digest.update(chunk)


def _store_checksum(path: Path) -> str:
    digest = hashlib.md5()
    if path.is_file():
        _update_file_digest(path, digest)
    else:
        def update_directory(directory: Path) -> None:
            for child in sorted(
                directory.iterdir(),
                key=lambda item: (item.name.lower(), item.name),
            ):
                digest.update(child.name.encode())
                if child.is_file():
                    _update_file_digest(child, digest)
                elif child.is_dir():
                    update_directory(child)

        update_directory(path)
    return digest.hexdigest()


def _component_manifest(
    components: tuple[NCoreComponentData, ...],
) -> dict[str, object]:
    names = sorted({value.component.name for value in components})
    return {
        name: {
            value.component.instance: {
                "version": value.component.version,
                "generic_meta_data": _plain_json(
                    value.component.generic_metadata
                ),
            }
            for value in sorted(
                components,
                key=lambda item: item.component.instance,
            )
            if value.component.name == name
        }
        for name in names
    }


def _replace_path(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _install_directory(stage: Path, destination: Path) -> None:
    backup: Path | None = None
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError(
                f"NCore: destination {str(destination)!r} exists and is not a directory"
            )
        backup = destination.with_name(
            f".{destination.name}.sceneio-previous-{uuid.uuid4().hex}"
        )
        _replace_path(destination, backup)
    try:
        _replace_path(stage, destination)
    except BaseException:
        if backup is not None and not destination.exists():
            _replace_path(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def _as_dataset_data(value: NCoreDataset | NCoreDatasetData) -> NCoreDatasetData:
    if isinstance(value, NCoreDatasetData):
        return value
    if isinstance(value, NCoreDataset):
        return materialize_ncore_v4(value.source)
    raise TypeError("NCore writer expects NCoreDataset or NCoreDatasetData")


def write_ncore_v4(
    value: NCoreDataset | NCoreDatasetData,
    path: str | Path,
    *,
    storage: str = "itar",
) -> None:
    """Write a complete V4 dataset directory using directory or indexed-tar stores."""

    if storage not in {"directory", "itar"}:
        raise ValueError("NCore writer storage must be 'directory' or 'itar'")
    dataset = _as_dataset_data(value)
    destination = Path(path)
    destination.parent.mkdir(parents=False, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.sceneio-stage-",
            dir=destination.parent,
        )
    )
    try:
        grouped = {
            group: tuple(
                item
                for item in dataset.components
                if item.component.group == group
            )
            for group in sorted(
                {item.component.group for item in dataset.components}
            )
        }
        manifest_stores: list[dict[str, object]] = []
        multiple = len(grouped) > 1
        for index, (group_name, components) in enumerate(grouped.items()):
            suffix = f"-{index:04d}" if multiple else ""
            directory_name = f"dataset.ncore4{suffix}.zarr"
            directory_store = stage / directory_name
            _write_store_directory(
                components,
                directory_store,
                dataset,
                group_name,
            )
            if storage == "itar":
                store_path = stage / f"{directory_name}.itar"
                _write_indexed_tar(directory_store, store_path)
                shutil.rmtree(directory_store)
            else:
                store_path = directory_store
            manifest_stores.append(
                {
                    "path": store_path.name,
                    "md5": _store_checksum(store_path),
                    "components": _component_manifest(components),
                }
            )
        manifest = {
            "sequence_id": dataset.sequence_id,
            "sequence_timestamp_interval_us": {
                "start": dataset.timestamp_interval_us[0],
                "stop": dataset.timestamp_interval_us[1],
            },
            "generic_meta_data": _plain_json(dataset.generic_metadata),
            "version": "v4",
            "component_stores": manifest_stores,
        }
        (stage / "dataset.ncore4.json").write_bytes(_json_bytes(manifest))
        _install_directory(stage, destination)
    finally:
        with suppress(FileNotFoundError):
            shutil.rmtree(stage)


__all__ = ["write_ncore_v4"]
