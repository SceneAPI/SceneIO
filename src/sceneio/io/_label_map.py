"""Typed, versioned dense-label adapters over NPZ, Zarr, and TIFF."""

from __future__ import annotations

import io
import itertools
import operator
import os
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio._data.dense import (
    InstanceMap,
    LabelTaxonomy,
    PanopticMap,
    SemanticMap,
)
from sceneio.io._inspection import inspect_path
from sceneio.io._inspectors.model import ArrayInspection, Inspection
from sceneio.io._zarr import (
    _write_zarr_arrays,
    _ZarrArrayReader,
    inspect_zarr,
)
from sceneio.io.registry import FormatError, detect

LABEL_MAP_SCHEMA = "sceneio.label_map/1"
_MARKER = "__sceneio_label_map_v1__"
_SEMANTIC = "semantic_ids"
_VOID = "semantic_void_id"
_INSTANCE = "instance_ids"
_BACKGROUND = "instance_background_id"
_VALID = "valid"
_TAXONOMY_IDS = "taxonomy_semantic_ids"
_TAXONOMY_NAMES = "taxonomy_names_utf8"
_TAXONOMY_OFFSETS = "taxonomy_name_offsets"
_TAXONOMY_IDENTITY = "taxonomy_identity_utf8"
_TAXONOMY_VERSION = "taxonomy_version_utf8"
_TAXONOMY_COLORS = "taxonomy_display_colors"
_TAXONOMY_IS_THING = "taxonomy_is_thing"
_TABLE_INSTANCES = "table_instance_ids"
_TABLE_SEMANTICS = "table_semantic_ids"
_TAXONOMY_REQUIRED = frozenset(
    {
        _TAXONOMY_IDS,
        _TAXONOMY_NAMES,
        _TAXONOMY_OFFSETS,
        _TAXONOMY_IDENTITY,
        _TAXONOMY_VERSION,
    }
)
_TAXONOMY_ALL = _TAXONOMY_REQUIRED | {
    _TAXONOMY_COLORS,
    _TAXONOMY_IS_THING,
}
_TABLE = frozenset({_TABLE_INSTANCES, _TABLE_SEMANTICS})
_ALL_NAMES = (
    {_MARKER, _SEMANTIC, _VOID, _INSTANCE, _BACKGROUND, _VALID}
    | _TAXONOMY_ALL
    | _TABLE
)
_SMALL_ARRAY_LIMIT = 1 << 20


def _utf8_array(value: str) -> np.ndarray:
    return np.frombuffer(value.encode("utf-8"), dtype=np.uint8).copy()


def _taxonomy_arrays(taxonomy: LabelTaxonomy) -> dict[str, np.ndarray]:
    encoded_names = [value.encode("utf-8") for value in taxonomy.names]
    offsets = np.empty(len(encoded_names) + 1, np.int64)
    offsets[0] = 0
    cursor = 0
    for index, value in enumerate(encoded_names, start=1):
        cursor += len(value)
        offsets[index] = cursor
    names = np.frombuffer(b"".join(encoded_names), dtype=np.uint8).copy()
    result = {
        _TAXONOMY_IDS: taxonomy.semantic_ids,
        _TAXONOMY_NAMES: names,
        _TAXONOMY_OFFSETS: offsets,
        _TAXONOMY_IDENTITY: _utf8_array(taxonomy.identity),
        _TAXONOMY_VERSION: _utf8_array(taxonomy.version),
    }
    if taxonomy.display_colors is not None:
        result[_TAXONOMY_COLORS] = taxonomy.display_colors
    if taxonomy.is_thing is not None:
        result[_TAXONOMY_IS_THING] = taxonomy.is_thing
    return result


def _schema_arrays(value: object) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {_MARKER: np.array(1, np.uint8)}
    if isinstance(value, PanopticMap):
        semantic = value.semantic
        instance = value.instance
    elif isinstance(value, SemanticMap):
        semantic = value
        instance = None
    elif isinstance(value, InstanceMap):
        semantic = None
        instance = value
    else:
        raise TypeError(
            "label_map must be a SemanticMap, InstanceMap, or PanopticMap"
        )
    if semantic is not None:
        result[_SEMANTIC] = semantic.class_ids
        result[_VOID] = np.array(semantic.void_id, np.int32)
        if semantic.taxonomy is not None:
            result.update(_taxonomy_arrays(semantic.taxonomy))
    if instance is not None:
        result[_INSTANCE] = instance.instance_ids
        result[_BACKGROUND] = np.array(instance.background_id, np.int64)
        if instance.table_instance_ids is not None:
            result[_TABLE_INSTANCES] = instance.table_instance_ids
            result[_TABLE_SEMANTICS] = instance.table_semantic_ids
    valid = semantic.valid if semantic is not None else instance.valid
    if valid is not None:
        result[_VALID] = valid
    return result


def _mapping(tensors) -> dict[str, np.ndarray]:
    return {name: np.asarray(tensors[name]) for name in tensors}


def _scalar(array: np.ndarray, name: str, dtype: object) -> int:
    expected = np.dtype(dtype)
    if array.shape != () or array.dtype != expected:
        raise ValueError(
            f"label-map array {name!r} must be scalar {expected.name}"
        )
    return int(array)


def _text(array: np.ndarray, name: str) -> str:
    if array.dtype != np.dtype("uint8") or array.ndim != 1:
        raise ValueError(f"label-map array {name!r} must be a uint8 vector")
    try:
        return array.tobytes().decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"label-map array {name!r} is not valid UTF-8") from None


def _taxonomy_from_arrays(arrays: Mapping[str, np.ndarray]) -> LabelTaxonomy | None:
    present = set(arrays) & _TAXONOMY_ALL
    if not present:
        return None
    if not present >= _TAXONOMY_REQUIRED:
        missing = ", ".join(sorted(_TAXONOMY_REQUIRED - present))
        raise ValueError(f"label-map taxonomy is incomplete; missing {missing}")
    ids = arrays[_TAXONOMY_IDS]
    names = arrays[_TAXONOMY_NAMES]
    offsets = arrays[_TAXONOMY_OFFSETS]
    if ids.dtype != np.dtype("int32") or ids.ndim != 1:
        raise ValueError("label-map taxonomy ids must be an int32 vector")
    if names.dtype != np.dtype("uint8") or names.ndim != 1:
        raise ValueError("label-map taxonomy names must be a uint8 vector")
    if offsets.dtype != np.dtype("int64") or offsets.shape != (len(ids) + 1,):
        raise ValueError(
            "label-map taxonomy offsets must be int64 with one terminal offset"
        )
    if (
        int(offsets[0]) != 0
        or int(offsets[-1]) != len(names)
        or np.any(offsets[1:] < offsets[:-1])
    ):
        raise ValueError("label-map taxonomy name offsets are inconsistent")
    decoded_names = []
    for start, stop in itertools.pairwise(offsets):
        try:
            decoded_names.append(names[int(start) : int(stop)].tobytes().decode("utf-8"))
        except UnicodeDecodeError:
            raise ValueError("label-map taxonomy name is not valid UTF-8") from None
    return LabelTaxonomy(
        ids,
        tuple(decoded_names),
        _text(arrays[_TAXONOMY_IDENTITY], _TAXONOMY_IDENTITY),
        _text(arrays[_TAXONOMY_VERSION], _TAXONOMY_VERSION),
        arrays.get(_TAXONOMY_COLORS),
        arrays.get(_TAXONOMY_IS_THING),
    )


def _from_arrays(arrays: Mapping[str, np.ndarray]):
    names = set(arrays)
    if _MARKER not in arrays or _scalar(arrays[_MARKER], _MARKER, np.uint8) != 1:
        raise ValueError(f"label-map carrier does not declare {LABEL_MAP_SCHEMA}")
    unknown = names - _ALL_NAMES
    if unknown:
        raise ValueError(
            "label-map schema contains unknown arrays "
            + ", ".join(sorted(repr(name) for name in unknown))
        )
    has_semantic = _SEMANTIC in arrays or _VOID in arrays
    has_instance = _INSTANCE in arrays or _BACKGROUND in arrays
    if not has_semantic and not has_instance:
        raise ValueError("label-map carrier has no semantic or instance raster")
    if has_semantic and not {_SEMANTIC, _VOID} <= names:
        raise ValueError("label-map semantic raster/id declaration is incomplete")
    if has_instance and not {_INSTANCE, _BACKGROUND} <= names:
        raise ValueError("label-map instance raster/id declaration is incomplete")
    if bool(names & _TABLE) and not names >= _TABLE:
        raise ValueError("label-map instance table is incomplete")
    if names & _TAXONOMY_ALL and not has_semantic:
        raise ValueError("label-map taxonomy requires a semantic raster")
    if names & _TABLE and not has_instance:
        raise ValueError("label-map instance table requires an instance raster")
    valid = arrays.get(_VALID)
    taxonomy = _taxonomy_from_arrays(arrays)
    semantic = None
    if has_semantic:
        semantic = SemanticMap(
            arrays[_SEMANTIC],
            _scalar(arrays[_VOID], _VOID, np.int32),
            valid,
            taxonomy,
        )
    instance = None
    if has_instance:
        instance = InstanceMap(
            arrays[_INSTANCE],
            _scalar(arrays[_BACKGROUND], _BACKGROUND, np.int64),
            valid,
            arrays.get(_TABLE_INSTANCES),
            arrays.get(_TABLE_SEMANTICS),
        )
    if semantic is not None and instance is not None:
        return PanopticMap(semantic, instance)
    return semantic if semantic is not None else instance


def _resolve(path, format: str | None, *, writing: bool) -> str:
    if format is not None:
        selected = format
    elif writing:
        selected = Path(path).suffix.lower().removeprefix(".")
    else:
        selected = detect(path)
    if selected == "tif":
        selected = "tiff"
    if selected not in {"npz", "tiff", "zarr"}:
        operation = "write" if writing else "read"
        rendered = selected or Path(path).suffix.lower() or "<none>"
        raise FormatError(
            f"{operation}_label_map supports typed labels for npz, tiff, and zarr "
            f"(selected {rendered!r})"
        )
    return selected


def read_label_map(
    path,
    *,
    format: str | None = None,
    label_contract: object | None = None,
):
    """Read ``sceneio.label_map/1`` or an explicitly contracted TIFF."""

    selected = _resolve(path, format, writing=False)
    try:
        if selected == "tiff":
            from sceneio.io._tiff import read_tiff_label_map

            return read_tiff_label_map(path, label_contract=label_contract)
        if label_contract is not None:
            raise ValueError("label_contract is a TIFF-only label-map option")
        if selected == "npz":
            _preflight(path, selected)
            from sceneio.io.registry import get

            tensors = get("npz").read(str(path))
            arrays = _mapping(tensors)
        else:
            reader = _ZarrArrayReader(path)
            _preflight_arrays(reader.inspections, reader.read)
            arrays = reader.read()
        return _from_arrays(arrays)
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(
            f"reading {str(path)!r} as typed {selected!r} label map: {exc}"
        ) from exc


def _write_npz(
    tensors,
    path: str | Path,
    *,
    compress: bool,
) -> None:
    destination = Path(path)
    if not destination.parent.is_dir():
        raise ValueError("label-map NPZ destination parent does not exist")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        def encode(value):
            return _core.write_npz(value, compress)

        _core._write_to_file(encode, tensors, str(temporary))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _chunk_shape(value: object | None) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise TypeError("chunks must contain two positive integers")
    try:
        selected = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        raise TypeError("chunks must contain two positive integers") from None
    if len(selected) != 2:
        raise ValueError("chunks must contain two positive integers")
    normalized = []
    for item in selected:
        if isinstance(item, bool):
            raise TypeError("chunks must contain two positive integers")
        try:
            dimension = operator.index(item)
        except TypeError:
            raise TypeError("chunks must contain two positive integers") from None
        if dimension <= 0:
            raise ValueError("chunks must contain two positive integers")
        normalized.append(int(dimension))
    return (normalized[0], normalized[1])


def write_label_map(
    label_map,
    path,
    *,
    format: str | None = None,
    compress: bool = False,
    zarr_format: int = 3,
    chunks: tuple[int, int] | None = None,
    bigtiff: bool | None = None,
) -> None:
    """Write a versioned lossless label map without changing raw carrier APIs."""

    selected = _resolve(path, format, writing=True)
    if not isinstance(compress, bool):
        raise TypeError("compress must be bool")
    selected_chunks = _chunk_shape(chunks)
    if isinstance(zarr_format, bool):
        raise TypeError("zarr_format must be 2 or 3")
    try:
        selected_zarr_format = operator.index(zarr_format)
    except TypeError:
        raise TypeError("zarr_format must be 2 or 3") from None
    if selected_zarr_format not in {2, 3}:
        raise ValueError("zarr_format must be 2 or 3")
    if selected == "npz" and selected_chunks is not None:
        raise ValueError("NPZ label maps do not support chunk shapes")
    if selected == "npz" and selected_zarr_format != 3:
        raise ValueError("zarr_format is a Zarr-only label-map option")
    if selected == "zarr" and compress:
        raise ValueError("compress is an NPZ-only label-map option")
    if selected == "tiff" and compress:
        raise ValueError("compress is an NPZ-only label-map option")
    if selected == "tiff" and selected_chunks is not None:
        raise ValueError("TIFF label maps do not support Zarr chunk shapes")
    if selected == "tiff" and selected_zarr_format != 3:
        raise ValueError("zarr_format is a Zarr-only label-map option")
    if selected != "tiff" and bigtiff is not None:
        raise ValueError("bigtiff is a TIFF-only label-map option")
    try:
        if selected == "tiff":
            from sceneio.io._tiff import write_tiff_label_map

            write_tiff_label_map(label_map, path, bigtiff=bigtiff)
            return
        arrays = _schema_arrays(label_map)
        if selected == "npz":
            tensors = _core.tensor_dict(arrays)
            _write_npz(tensors, path, compress=compress)
            return
        chunk_map = None
        if selected_chunks is not None:
            chunk_map = {
                name: selected_chunks
                for name in (_SEMANTIC, _INSTANCE, _VALID)
                if name in arrays
            }
        _write_zarr_arrays(
            arrays,
            path,
            zarr_format=selected_zarr_format,
            chunks=chunk_map,
        )
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(
            f"writing {str(path)!r} as typed {selected!r} label map: {exc}"
        ) from exc


def _inspection_structure(
    arrays: tuple[ArrayInspection, ...],
) -> tuple[str, tuple[int, int], str | None, bool, bool]:
    by_name = {item.name: item for item in arrays}
    if len(by_name) != len(arrays):
        raise ValueError("label-map carrier has duplicate array names")
    if _MARKER not in by_name:
        raise ValueError(f"label-map carrier does not declare {LABEL_MAP_SCHEMA}")
    unknown = set(by_name) - _ALL_NAMES
    if unknown:
        raise ValueError(
            "label-map schema contains unknown arrays "
            + ", ".join(sorted(repr(name) for name in unknown))
        )

    def require(name: str, dtype: str, shape: tuple[int | None, ...]) -> ArrayInspection:
        try:
            item = by_name[name]
        except KeyError:
            raise ValueError(f"label-map schema lacks array {name!r}") from None
        if item.dtype != dtype or len(item.shape) != len(shape) or any(
            expected is not None and actual != expected
            for actual, expected in zip(item.shape, shape, strict=True)
        ):
            raise ValueError(
                f"label-map array {name!r} has incompatible shape or dtype"
            )
        return item

    require(_MARKER, "uint8", ())
    has_semantic = _SEMANTIC in by_name or _VOID in by_name
    has_instance = _INSTANCE in by_name or _BACKGROUND in by_name
    if not has_semantic and not has_instance:
        raise ValueError("label-map carrier has no semantic or instance raster")
    if has_semantic and not {_SEMANTIC, _VOID} <= set(by_name):
        raise ValueError("label-map semantic raster/id declaration is incomplete")
    if has_instance and not {_INSTANCE, _BACKGROUND} <= set(by_name):
        raise ValueError("label-map instance raster/id declaration is incomplete")
    shape: tuple[int, int] | None = None
    primary_dtype = None
    if has_semantic:
        semantic = require(_SEMANTIC, "int32", (None, None))
        require(_VOID, "int32", ())
        shape = (semantic.shape[0], semantic.shape[1])
        primary_dtype = "int32"
    if has_instance:
        instance = require(_INSTANCE, "int64", (None, None))
        require(_BACKGROUND, "int64", ())
        instance_shape = (instance.shape[0], instance.shape[1])
        if shape is not None and instance_shape != shape:
            raise ValueError("label-map semantic and instance shapes disagree")
        shape = instance_shape
        primary_dtype = None if has_semantic else "int64"
    assert shape is not None
    if _VALID in by_name:
        require(_VALID, "bool", shape)
    taxonomy_names = set(by_name) & _TAXONOMY_ALL
    if taxonomy_names:
        if not has_semantic or not taxonomy_names >= _TAXONOMY_REQUIRED:
            raise ValueError("label-map taxonomy declaration is incomplete")
        ids = require(_TAXONOMY_IDS, "int32", (None,))
        count = ids.shape[0]
        require(_TAXONOMY_NAMES, "uint8", (None,))
        require(_TAXONOMY_OFFSETS, "int64", (count + 1,))
        require(_TAXONOMY_IDENTITY, "uint8", (None,))
        require(_TAXONOMY_VERSION, "uint8", (None,))
        if _TAXONOMY_COLORS in by_name:
            require(_TAXONOMY_COLORS, "uint8", (count, 3))
        if _TAXONOMY_IS_THING in by_name:
            require(_TAXONOMY_IS_THING, "bool", (count,))
    table_names = set(by_name) & _TABLE
    if table_names:
        if not has_instance or table_names != _TABLE:
            raise ValueError("label-map instance table declaration is incomplete")
        ids = require(_TABLE_INSTANCES, "int64", (None,))
        require(_TABLE_SEMANTICS, "int32", (ids.shape[0],))
    kind = "panoptic" if has_semantic and has_instance else (
        "semantic" if has_semantic else "instance"
    )
    return kind, shape, primary_dtype, bool(taxonomy_names), bool(table_names)


def _read_npz_small(path: str | Path, names: tuple[str, ...]) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    with zipfile.ZipFile(path) as archive:
        members = {
            member.filename.removesuffix(".npy"): member
            for member in archive.infolist()
            if not member.is_dir()
        }
        for name in names:
            try:
                member = members[name]
            except KeyError:
                raise ValueError(f"label-map schema lacks array {name!r}") from None
            if member.file_size > _SMALL_ARRAY_LIMIT:
                raise ValueError(f"label-map metadata array {name!r} is unexpectedly large")
            payload = archive.read(member)
            result[name] = np.load(io.BytesIO(payload), allow_pickle=False)
    return result


def _small_arrays(
    path: str | Path,
    format_id: str,
    names: tuple[str, ...],
) -> dict[str, np.ndarray]:
    if format_id == "npz":
        return _read_npz_small(path, names)
    return _ZarrArrayReader(path).read(names)


def _base_inspection(path: str | Path, format_id: str) -> Inspection:
    if format_id == "npz":
        return inspect_path(path, "npz", "tensor_dict")
    return inspect_zarr(path)


def _validate_marker_metadata(arrays: tuple[ArrayInspection, ...]) -> None:
    markers = [item for item in arrays if item.name == _MARKER]
    if not markers:
        raise ValueError(f"label-map carrier does not declare {LABEL_MAP_SCHEMA}")
    if len(markers) != 1:
        raise ValueError("label-map carrier has duplicate array names")
    marker = markers[0]
    if marker.dtype != "uint8" or marker.shape != ():
        raise ValueError(
            f"label-map array {_MARKER!r} has incompatible shape or dtype"
        )


def _preflight_arrays(
    arrays: tuple[ArrayInspection, ...],
    read_small,
    *,
    include_ids: bool = False,
) -> tuple[
    tuple[str, tuple[int, int], str | None, bool, bool],
    dict[str, np.ndarray],
]:
    _validate_marker_metadata(arrays)
    names = {item.name for item in arrays}
    scalar_names = [_MARKER]
    if include_ids and _VOID in names:
        scalar_names.append(_VOID)
    if include_ids and _BACKGROUND in names:
        scalar_names.append(_BACKGROUND)
    scalars = read_small(tuple(scalar_names))
    if _scalar(scalars[_MARKER], _MARKER, np.uint8) != 1:
        raise ValueError(f"label-map carrier does not declare {LABEL_MAP_SCHEMA}")
    structure = _inspection_structure(arrays)
    return structure, scalars


def _preflight(
    path: str | Path,
    format_id: str,
    *,
    include_ids: bool = False,
) -> tuple[
    Inspection,
    tuple[str, tuple[int, int], str | None, bool, bool],
    dict[str, np.ndarray],
]:
    """Validate schema metadata and its marker before decoding raster arrays."""

    base = _base_inspection(path, format_id)
    structure, scalars = _preflight_arrays(
        base.arrays,
        lambda names: _small_arrays(path, format_id, names),
        include_ids=include_ids,
    )
    return base, structure, scalars


def inspect_label_map(
    path,
    *,
    format: str | None = None,
    label_contract: object | None = None,
) -> Inspection:
    """Inspect a typed label schema without decoding its raster payloads."""

    selected = _resolve(path, format, writing=False)
    try:
        if selected == "tiff":
            from sceneio.io._tiff import inspect_tiff_label_map

            return inspect_tiff_label_map(path, label_contract=label_contract)
        if label_contract is not None:
            raise ValueError("label_contract is a TIFF-only label-map option")
        base, structure, scalars = _preflight(
            path,
            selected,
            include_ids=True,
        )
        kind, shape, dtype, has_taxonomy, has_table = structure
        names = {item.name for item in base.arrays}
        metadata = {
            **base.metadata,
            "schema": LABEL_MAP_SCHEMA,
            "kind": kind,
            "has_validity": _VALID in names,
            "has_taxonomy": has_taxonomy,
            "has_instance_table": has_table,
        }
        if _VOID in scalars:
            metadata["void_id"] = _scalar(scalars[_VOID], _VOID, np.int32)
        if _BACKGROUND in scalars:
            metadata["background_id"] = _scalar(
                scalars[_BACKGROUND], _BACKGROUND, np.int64
            )
        return Inspection(
            selected,
            f"{kind}_map",
            base.byte_size,
            shape=shape,
            dtype=dtype,
            count=shape[0] * shape[1],
            channels=1,
            arrays=base.arrays,
            metadata=metadata,
        )
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(
            f"inspecting {str(path)!r} as typed {selected!r} label map: {exc}"
        ) from exc


__all__ = [
    "LABEL_MAP_SCHEMA",
    "inspect_label_map",
    "read_label_map",
    "write_label_map",
]
