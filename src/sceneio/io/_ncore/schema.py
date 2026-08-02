"""NCore V4 store discovery and metadata-only catalog construction."""

from __future__ import annotations

import json
import lzma
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from sceneio.io._inspectors.model import ArrayInspection, Inspection
from sceneio.io._ncore.itar import IndexedTarReader
from sceneio.io._ncore.model import (
    NCoreArray,
    NCoreComponent,
    NCoreDataset,
    NCoreStore,
)

_METADATA_KEY = ".zmetadata.cbor.xz"
_ROOT_ATTRIBUTES_KEY = ".zattrs"
_ROOT_GROUP_KEY = ".zgroup"
_MAX_JSON_BYTES = 16 << 20
_MAX_COMPRESSED_METADATA_BYTES = 256 << 20
_MAX_DECODED_METADATA_BYTES = 512 << 20
_MAX_METADATA_ENTRIES = 5_000_000
_STORE_DIRECTORY_SUFFIX = ".zarr"
_STORE_FILE_SUFFIX = ".zarr.itar"

STANDARD_COMPONENTS = frozenset(
    {
        "poses",
        "intrinsics",
        "masks",
        "cameras",
        "lidars",
        "radars",
        "cuboids",
        "point_clouds",
        "camera_labels",
    }
)


def _require_cbor2():
    try:
        import cbor2
    except ModuleNotFoundError:
        raise RuntimeError(
            "NCore support requires the optional dependency; install sceneio[ncore]"
        ) from None
    return cbor2


def _duplicate_checked_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _decode_json(payload: bytes, context: str) -> object:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_duplicate_checked_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON token {token}")
            ),
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"{context}: invalid JSON: {exc}") from exc


def _read_small_file(path: Path, limit: int, context: str) -> bytes:
    size = path.stat().st_size
    if size > limit:
        raise ValueError(f"{context}: file exceeds the supported metadata limit")
    with path.open("rb") as stream:
        payload = stream.read(size + 1)
    if len(payload) != size:
        raise ValueError(f"{context}: file changed while being read")
    return payload


def _decode_consolidated(payload: bytes, context: str) -> dict[str, object]:
    if len(payload) > _MAX_COMPRESSED_METADATA_BYTES:
        raise ValueError(f"{context}: compressed metadata exceeds the supported limit")
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    try:
        decoded = decompressor.decompress(
            payload,
            max_length=_MAX_DECODED_METADATA_BYTES + 1,
        )
    except lzma.LZMAError as exc:
        raise ValueError(f"{context}: invalid compressed metadata: {exc}") from exc
    if len(decoded) > _MAX_DECODED_METADATA_BYTES or not decompressor.eof:
        raise ValueError(f"{context}: decoded metadata exceeds the supported limit")
    try:
        document = _require_cbor2().loads(decoded)
    except Exception as exc:
        raise ValueError(f"{context}: invalid CBOR metadata: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{context}: consolidated metadata must be an object")
    if document.get("zarr_consolidated_format") != 1:
        raise ValueError(f"{context}: unsupported consolidated metadata version")
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"{context}: consolidated metadata lacks an object table")
    if len(metadata) > _MAX_METADATA_ENTRIES:
        raise ValueError(f"{context}: metadata entry count exceeds the supported limit")
    result: dict[str, object] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError(f"{context}: metadata entries must map paths to objects")
        if key in result:
            raise ValueError(f"{context}: duplicate metadata path {key!r}")
        result[key] = value
    return result


def _directory_metadata(path: Path) -> dict[str, object]:
    consolidated = path / _METADATA_KEY
    if consolidated.is_file():
        return _decode_consolidated(
            _read_small_file(
                consolidated,
                _MAX_COMPRESSED_METADATA_BYTES,
                f"NCore store {path.name!r}",
            ),
            f"NCore store {path.name!r}",
        )
    result: dict[str, object] = {}
    for metadata_path in path.rglob("*"):
        if not metadata_path.is_file() or metadata_path.name not in {
            ".zattrs",
            ".zarray",
            ".zgroup",
        }:
            continue
        if len(result) >= _MAX_METADATA_ENTRIES:
            raise ValueError("NCore store: metadata entry count exceeds the supported limit")
        key = metadata_path.relative_to(path).as_posix()
        result[key] = _decode_json(
            _read_small_file(metadata_path, _MAX_JSON_BYTES, f"NCore metadata {key!r}"),
            f"NCore metadata {key!r}",
        )
    return result


def _itar_metadata(path: Path) -> dict[str, object]:
    with IndexedTarReader(path) as store:
        if _METADATA_KEY in store:
            return _decode_consolidated(
                store.read(_METADATA_KEY),
                f"NCore store {path.name!r}",
            )
        result: dict[str, object] = {}
        for key in store:
            if key.rsplit("/", 1)[-1] not in {".zattrs", ".zarray", ".zgroup"}:
                continue
            if len(result) >= _MAX_METADATA_ENTRIES:
                raise ValueError(
                    "NCore store: metadata entry count exceeds the supported limit"
                )
            result[key] = _decode_json(
                store.read(key),
                f"NCore metadata {key!r}",
            )
        return result


def _object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {name: _plain_json(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _string(value: object, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise ValueError(f"{context} must be {qualifier}")
    return value


def _timestamp_interval(value: object, context: str) -> tuple[int, int]:
    interval = _object(value, context)
    if set(interval) != {"start", "stop"}:
        raise ValueError(f"{context} must contain exactly start and stop")
    start, stop = interval["start"], interval["stop"]
    if (
        isinstance(start, bool)
        or isinstance(stop, bool)
        or not isinstance(start, int)
        or not isinstance(stop, int)
        or start < 0
        or stop <= start
        or stop > np.iinfo(np.uint64).max
    ):
        raise ValueError(f"{context} must satisfy uint64 0 <= start < stop")
    return start, stop


def _array_descriptor(
    relative_name: str,
    full_name: str,
    metadata: Mapping[str, object],
    array_metadata: object,
) -> NCoreArray:
    document = _object(array_metadata, f"NCore array {relative_name!r}")
    if document.get("zarr_format") != 2:
        raise ValueError(f"NCore array {relative_name!r}: expected Zarr V2 metadata")
    raw_shape = document.get("shape")
    raw_chunks = document.get("chunks")
    if not isinstance(raw_shape, list) or not isinstance(raw_chunks, list):
        raise ValueError(f"NCore array {relative_name!r}: shape/chunks must be arrays")
    shape = tuple(raw_shape)
    chunks = tuple(raw_chunks)
    try:
        dtype = np.dtype(document.get("dtype")).str
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NCore array {relative_name!r}: invalid dtype") from exc
    attrs_key = f"{full_name}/.zattrs"
    attributes = metadata.get(attrs_key, {})
    return NCoreArray(
        name=relative_name,
        shape=shape,
        dtype=dtype,
        chunks=chunks,
        attributes=_object(attributes, f"NCore array {relative_name!r} attributes"),
    )


def _parse_store(path: Path, store_index: int) -> tuple[dict[str, object], NCoreStore]:
    if path.is_dir():
        storage = "directory"
        metadata = _directory_metadata(path)
        byte_size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    elif path.is_file() and path.name.endswith(_STORE_FILE_SUFFIX):
        storage = "itar"
        metadata = _itar_metadata(path)
        byte_size = path.stat().st_size
    else:
        raise ValueError(
            f"NCore store {str(path)!r}: expected a .zarr directory or .zarr.itar file"
        )
    root_group = _object(metadata.get(_ROOT_GROUP_KEY), "NCore root .zgroup")
    if root_group.get("zarr_format") != 2:
        raise ValueError("NCore V4 stores must use Zarr V2 metadata")
    root = _object(metadata.get(_ROOT_ATTRIBUTES_KEY), "NCore root attributes")
    version = _string(root.get("version"), "NCore root version")
    if version != "v4":
        raise ValueError(f"NCore store: expected version 'v4', got {version!r}")
    sequence_id = _string(root.get("sequence_id"), "NCore sequence_id")
    interval = _timestamp_interval(
        root.get("sequence_timestamp_interval_us"),
        "NCore sequence_timestamp_interval_us",
    )
    generic_metadata = _object(
        root.get("generic_meta_data"), "NCore generic_meta_data"
    )
    group = _string(
        root.get("component_group_name"),
        "NCore component_group_name",
        allow_empty=True,
    )
    component_attrs: list[tuple[str, str, str, dict[str, object]]] = []
    for key, raw_attributes in metadata.items():
        if not key.endswith("/.zattrs") or key.count("/") != 2:
            continue
        component_name, instance, _ = key.split("/")
        attributes = _object(raw_attributes, f"NCore component {component_name}:{instance}")
        if not {"component_name", "component_instance_name", "component_version"} <= set(attributes):
            continue
        declared_name = _string(
            attributes.get("component_name"), "NCore component_name"
        )
        declared_instance = _string(
            attributes.get("component_instance_name"),
            "NCore component_instance_name",
        )
        if declared_name != component_name or declared_instance != instance:
            raise ValueError(
                f"NCore component path {component_name}:{instance} disagrees with its attributes"
            )
        component_attrs.append((component_name, instance, key, attributes))
    components: list[NCoreComponent] = []
    for component_name, instance, key, attributes in sorted(component_attrs):
        prefix = key[: -len(".zattrs")]
        arrays: list[NCoreArray] = []
        for metadata_key, array_metadata in metadata.items():
            if not metadata_key.startswith(prefix) or not metadata_key.endswith("/.zarray"):
                continue
            full_name = metadata_key[: -len("/.zarray")]
            relative_name = full_name[len(prefix) :]
            arrays.append(
                _array_descriptor(
                    relative_name,
                    full_name,
                    metadata,
                    array_metadata,
                )
            )
        generic = attributes.get("generic_meta_data", {})
        component_version = _string(
            attributes.get("component_version"),
            f"NCore component {component_name}:{instance} version",
        )
        if component_name in STANDARD_COMPONENTS and component_version != "v1":
            raise ValueError(
                f"NCore component {component_name}:{instance}: unsupported "
                f"standard version {component_version!r}"
            )
        components.append(
            NCoreComponent(
                name=component_name,
                instance=instance,
                version=component_version,
                group=group,
                store_index=store_index,
                generic_metadata=_object(
                    generic,
                    f"NCore component {component_name}:{instance} generic_meta_data",
                ),
                arrays=tuple(sorted(arrays, key=lambda item: item.name)),
            )
        )
    store = NCoreStore(
        path=str(path.resolve()),
        group=group,
        storage=storage,
        byte_size=byte_size,
        components=tuple(components),
    )
    return {
        "sequence_id": sequence_id,
        "timestamp_interval_us": interval,
        "generic_metadata": generic_metadata,
        "version": version,
    }, store


def _manifest_store_paths(
    path: Path,
) -> tuple[tuple[Path, ...], dict[str, object], tuple[dict[str, object], ...]]:
    document = _decode_json(
        _read_small_file(path, _MAX_JSON_BYTES, "NCore sequence manifest"),
        "NCore sequence manifest",
    )
    root = _object(document, "NCore sequence manifest")
    if root.get("version") != "v4":
        raise ValueError("NCore sequence manifest must declare version 'v4'")
    expected_root = {
        "sequence_id": _string(
            root.get("sequence_id"), "NCore sequence manifest sequence_id"
        ),
        "timestamp_interval_us": _timestamp_interval(
            root.get("sequence_timestamp_interval_us"),
            "NCore sequence manifest sequence_timestamp_interval_us",
        ),
        "generic_metadata": _object(
            root.get("generic_meta_data"),
            "NCore sequence manifest generic_meta_data",
        ),
        "version": "v4",
    }
    stores = root.get("component_stores")
    if not isinstance(stores, list) or not stores:
        raise ValueError("NCore sequence manifest component_stores must be non-empty")
    result: list[Path] = []
    store_documents: list[dict[str, object]] = []
    for index, raw_store in enumerate(stores):
        store = _object(raw_store, f"NCore component_stores[{index}]")
        relative = _string(store.get("path"), f"NCore component_stores[{index}].path")
        child = Path(relative)
        if child.is_absolute() or any(part in {"", ".", ".."} for part in child.parts):
            raise ValueError("NCore manifest store paths must be normalized relative paths")
        resolved = (path.parent / child).resolve()
        if resolved.parent != path.parent.resolve():
            raise ValueError("NCore manifest stores must be siblings of the manifest")
        _string(store.get("md5"), f"NCore component_stores[{index}].md5", allow_empty=True)
        _object(store.get("components"), f"NCore component_stores[{index}].components")
        result.append(resolved)
        store_documents.append(store)
    if len(result) != len(set(result)):
        raise ValueError("NCore sequence manifest lists a store more than once")
    return tuple(result), expected_root, tuple(store_documents)


def _discover_store_paths(source: Path) -> tuple[Path, ...]:
    if source.is_file() and source.suffix.lower() == ".json":
        return _manifest_store_paths(source)[0]
    if source.is_file() or (source / _ROOT_GROUP_KEY).is_file():
        return (source,)
    if source.is_dir():
        children = tuple(
            sorted(
                (
                    child.resolve()
                    for child in source.iterdir()
                    if (
                        child.is_dir()
                        and child.name.endswith(_STORE_DIRECTORY_SUFFIX)
                        and ".ncore4" in child.name
                    )
                    or (
                        child.is_file()
                        and child.name.endswith(_STORE_FILE_SUFFIX)
                        and ".ncore4" in child.name
                    )
                ),
                key=lambda item: item.name,
            )
        )
        if children:
            return children
    raise ValueError("NCore: path does not identify a local V4 dataset or component store")


def read_ncore_v4(path: str | Path) -> NCoreDataset:
    """Open a local NCore V4 dataset without materializing component arrays."""

    source = Path(path).resolve()
    manifest_root: dict[str, object] | None = None
    manifest_stores: tuple[dict[str, object], ...] = ()
    if source.is_file() and source.suffix.lower() == ".json":
        store_paths, manifest_root, manifest_stores = _manifest_store_paths(source)
    else:
        store_paths = _discover_store_paths(source)
    parsed = tuple(_parse_store(store_path, index) for index, store_path in enumerate(store_paths))
    first_root = parsed[0][0]
    for root, _store in parsed[1:]:
        if root != first_root:
            raise ValueError("NCore component stores describe different sequences")
    if manifest_root is not None and manifest_root != first_root:
        raise ValueError("NCore sequence manifest disagrees with its component stores")
    for index, (_root, store) in enumerate(parsed):
        if not manifest_stores:
            break
        declared = manifest_stores[index]["components"]
        assert isinstance(declared, dict)
        actual = {
            name: {
                component.instance: {
                    "version": component.version,
                    "generic_meta_data": _plain_json(component.generic_metadata),
                }
                for component in store.components
                if component.name == name
            }
            for name in sorted({component.name for component in store.components})
        }
        if declared != actual:
            raise ValueError(
                f"NCore sequence manifest component catalog disagrees for store {index}"
            )
    return NCoreDataset(
        source=str(source),
        sequence_id=first_root["sequence_id"],
        timestamp_interval_us=first_root["timestamp_interval_us"],
        generic_metadata=first_root["generic_metadata"],
        stores=tuple(store for _, store in parsed),
        version=first_root["version"],
    )


def inspect_ncore_v4(path: str | Path) -> Inspection:
    """Inspect NCore stores and arrays without decoding component payloads."""

    dataset = read_ncore_v4(path)
    arrays = tuple(
        ArrayInspection(
            name=f"{component.id}/{array.name}",
            shape=array.shape,
            dtype=array.dtype,
        )
        for component in dataset.components
        for array in component.arrays
    )
    return Inspection(
        format="ncore_v4",
        datatype="ncore_dataset",
        byte_size=dataset.byte_size,
        count=len(dataset.components),
        arrays=arrays,
        metadata={
            "version": dataset.version,
            "sequence_id": dataset.sequence_id,
            "timestamp_interval_us": dataset.timestamp_interval_us,
            "component_groups": tuple(store.group for store in dataset.stores),
            "component_ids": tuple(component.id for component in dataset.components),
            "standard_component_count": sum(
                component.name in STANDARD_COMPONENTS
                for component in dataset.components
            ),
            "custom_component_count": sum(
                component.name not in STANDARD_COMPONENTS
                for component in dataset.components
            ),
            "storage_modes": tuple(store.storage for store in dataset.stores),
        },
    )


def is_ncore_v4_path(path: str | Path) -> bool:
    """Return whether a local path has a valid bounded NCore V4 root schema."""

    try:
        read_ncore_v4(path)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


__all__ = [
    "STANDARD_COMPONENTS",
    "inspect_ncore_v4",
    "is_ncore_v4_path",
    "read_ncore_v4",
]
