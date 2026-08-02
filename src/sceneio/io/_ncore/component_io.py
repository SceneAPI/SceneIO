"""Owned NCore V4 component-array materialization and selection."""

from __future__ import annotations

import contextlib
import itertools
import math
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import numpy as np

from sceneio.io._ncore.itar import IndexedTarReader
from sceneio.io._ncore.model import (
    NCoreComponent,
    NCoreComponentData,
    NCoreGroup,
    NCoreSelection,
)
from sceneio.io._ncore.schema import (
    _directory_metadata,
    _itar_metadata,
    _numpy_dtype,
    _object,
    read_ncore_v4,
)

_ReadKey = Callable[[str], bytes | None]


def _require_numcodecs():
    try:
        import numcodecs
    except ModuleNotFoundError:
        raise RuntimeError(
            "NCore component loading requires the optional dependency; "
            "install sceneio[ncore]"
        ) from None
    return numcodecs


def _chunk_grid(
    shape: tuple[int, ...], chunks: tuple[int, ...]
) -> Iterator[tuple[int, ...]]:
    if not shape:
        yield ()
        return
    if any(size == 0 for size in shape):
        return
    yield from itertools.product(
        *(range((size + chunk - 1) // chunk) for size, chunk in zip(shape, chunks, strict=True))
    )


def _fill_array(array: np.ndarray, fill_value: object) -> None:
    if fill_value is None:
        array.fill(0)
        return
    if isinstance(fill_value, str):
        normalized = fill_value.lower()
        if normalized == "nan":
            fill_value = np.nan
        elif normalized == "infinity":
            fill_value = np.inf
        elif normalized == "-infinity":
            fill_value = -np.inf
    elif (
        array.dtype.kind == "c"
        and isinstance(fill_value, (list, tuple))
        and len(fill_value) == 2
    ):
        try:
            fill_value = complex(fill_value[0], fill_value[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("NCore array has an invalid fill_value") from exc
    try:
        array.fill(fill_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("NCore array has an invalid fill_value") from exc


def _decode_codecs(payload: bytes, document: Mapping[str, object]) -> bytes:
    decoded: object = payload
    compressor = document.get("compressor")
    filters = document.get("filters")
    try:
        if compressor is not None:
            if not isinstance(compressor, dict):
                raise ValueError("compressor must be an object or null")
            decoded = _require_numcodecs().get_codec(compressor).decode(decoded)
        if filters is not None:
            if not isinstance(filters, list):
                raise ValueError("filters must be an array or null")
            for configuration in reversed(filters):
                if not isinstance(configuration, dict):
                    raise ValueError("filter entries must be objects")
                decoded = _require_numcodecs().get_codec(configuration).decode(
                    decoded
                )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"NCore array chunk codec failed: {exc}") from exc
    if isinstance(decoded, np.ndarray):
        return decoded.tobytes(order="A")
    try:
        return bytes(decoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("NCore array chunk codec returned non-bytes data") from exc


def _array_document(metadata: Mapping[str, object], full_name: str) -> dict[str, object]:
    return _object(
        metadata.get(f"{full_name}/.zarray"),
        f"NCore array {full_name!r}",
    )


def _decode_array(
    metadata: Mapping[str, object],
    full_name: str,
    read_key: _ReadKey,
) -> np.ndarray:
    document = _array_document(metadata, full_name)
    if document.get("zarr_format") != 2:
        raise ValueError(f"NCore array {full_name!r}: expected Zarr V2 metadata")
    raw_shape = document.get("shape")
    raw_chunks = document.get("chunks")
    if not isinstance(raw_shape, list) or not isinstance(raw_chunks, list):
        raise ValueError(f"NCore array {full_name!r}: shape/chunks must be arrays")
    shape = tuple(raw_shape)
    chunks = tuple(raw_chunks)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in shape):
        raise ValueError(f"NCore array {full_name!r}: invalid shape")
    if len(chunks) != len(shape) or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in chunks
    ):
        raise ValueError(f"NCore array {full_name!r}: invalid chunks")
    dtype = _numpy_dtype(document.get("dtype"), f"NCore array {full_name!r}")
    if dtype.hasobject:
        raise ValueError(f"NCore array {full_name!r}: object dtype is unsupported")
    order = document.get("order")
    if order not in {"C", "F"}:
        raise ValueError(f"NCore array {full_name!r}: order must be 'C' or 'F'")
    separator = document.get("dimension_separator", ".")
    if separator not in {".", "/"}:
        raise ValueError(
            f"NCore array {full_name!r}: invalid dimension_separator"
        )
    try:
        count = math.prod(shape)
        if count > np.iinfo(np.intp).max // max(1, dtype.itemsize):
            raise ValueError(f"NCore array {full_name!r}: byte extent is too large")
        result = np.empty(shape, dtype=dtype, order=order)
    except (MemoryError, OverflowError, ValueError) as exc:
        if isinstance(exc, ValueError) and "byte extent" in str(exc):
            raise
        raise ValueError(f"NCore array {full_name!r}: cannot allocate shape") from exc
    _fill_array(result, document.get("fill_value"))
    for coordinates in _chunk_grid(shape, chunks):
        chunk_id = "0" if not coordinates else separator.join(map(str, coordinates))
        chunk_key = f"{full_name}/{chunk_id}"
        payload = read_key(chunk_key)
        if payload is None:
            continue
        decoded = _decode_codecs(payload, document)
        slices = tuple(
            slice(index * chunk, min((index + 1) * chunk, size))
            for index, chunk, size in zip(coordinates, chunks, shape, strict=True)
        )
        chunk_shape = chunks
        expected = math.prod(chunk_shape) * dtype.itemsize
        if len(decoded) != expected:
            raise ValueError(
                f"NCore array {full_name!r}: chunk {chunk_id!r} has "
                f"{len(decoded)} decoded bytes, expected {expected}"
            )
        chunk = np.frombuffer(decoded, dtype=dtype).reshape(
            chunk_shape,
            order=order,
        )
        edge_slices = tuple(
            slice(0, value.stop - value.start) for value in slices
        )
        result[slices] = chunk[edge_slices]
    return np.array(result, copy=True, order="C")


@contextlib.contextmanager
def _store_reader(path: Path) -> Iterator[tuple[dict[str, object], _ReadKey]]:
    if path.is_dir():
        metadata = _directory_metadata(path)

        def read_key(key: str) -> bytes | None:
            target = path.joinpath(*key.split("/"))
            if not target.is_file():
                return None
            size = target.stat().st_size
            with target.open("rb") as stream:
                payload = stream.read(size + 1)
            if len(payload) != size:
                raise ValueError(f"NCore payload {key!r} changed while being read")
            return payload

        yield metadata, read_key
        return
    with IndexedTarReader(path) as reader:
        metadata = _itar_metadata(path)

        def read_key(key: str) -> bytes | None:
            if key not in reader:
                return None
            return reader.read(key)

        yield metadata, read_key


def _component_prefix(component: NCoreComponent) -> str:
    return f"{component.name}/{component.instance}"


def _relative_group_attributes(
    metadata: Mapping[str, object],
    component: NCoreComponent,
) -> dict[str, dict[str, object]]:
    prefix = _component_prefix(component)
    result: dict[str, dict[str, object]] = {}
    for key, value in metadata.items():
        if key == f"{prefix}/.zattrs":
            relative = ""
            metadata_prefix = prefix
        elif key.startswith(f"{prefix}/") and key.endswith("/.zattrs"):
            relative = key[len(prefix) + 1 : -len("/.zattrs")]
            metadata_prefix = key[: -len("/.zattrs")]
        else:
            continue
        if f"{metadata_prefix}/.zarray" in metadata:
            continue
        result[relative] = _object(
            value,
            f"NCore group {component.id}/{relative} attributes",
        )
    return result


def _validate_index_range(value: tuple[int, int], count: int, context: str) -> range:
    start, stop = value
    if stop > count:
        raise ValueError(f"{context} range exceeds the available count {count}")
    return range(start, stop)


def _sensor_frame_ids(
    attributes: Mapping[str, object], selection: NCoreSelection
) -> tuple[str, ...]:
    raw = attributes.get("frames_timestamps_us")
    if not isinstance(raw, (list, tuple)):
        raise ValueError("NCore sensor frames lack frames_timestamps_us metadata")
    intervals: list[tuple[int, int]] = []
    for index, value in enumerate(raw):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(
                f"NCore sensor frame interval {index} must contain start/stop"
            )
        start, stop = value
        if (
            isinstance(start, bool)
            or isinstance(stop, bool)
            or not isinstance(start, int)
            or not isinstance(stop, int)
            or start < 0
            or stop < start
            or stop > np.iinfo(np.uint64).max
        ):
            raise ValueError(f"NCore sensor frame interval {index} is invalid")
        intervals.append((start, stop))
    if any(
        left[0] >= right[0] or left[1] >= right[1]
        for left, right in itertools.pairwise(intervals)
    ):
        raise ValueError("NCore sensor frame timestamps must be increasing")
    if selection.frames is not None:
        indices = _validate_index_range(
            selection.frames,
            len(intervals),
            "NCore frame",
        )
    elif selection.timestamps_us is not None:
        start, stop = selection.timestamps_us
        indices = (
            index
            for index, (frame_start, frame_stop) in enumerate(intervals)
            if frame_start < stop and frame_stop > start
        )
    else:
        indices = range(len(intervals))
    return tuple(str(intervals[index][1]) for index in indices)


def _timestamp_item_ids(
    values: np.ndarray,
    selection: NCoreSelection,
    context: str,
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    if values.dtype != np.dtype("uint64") or values.ndim != 1:
        raise ValueError(f"{context} timestamps must be a uint64 vector")
    if len(values) > 1 and not np.all(values[:-1] < values[1:]):
        raise ValueError(f"{context} timestamps must be strictly increasing")
    if selection.frames is not None:
        indices = tuple(
            _validate_index_range(selection.frames, len(values), context)
        )
    elif selection.timestamps_us is not None:
        start, stop = selection.timestamps_us
        indices = tuple(
            int(index)
            for index in np.flatnonzero((values >= start) & (values < stop))
        )
    else:
        indices = tuple(range(len(values)))
    return indices, tuple(str(int(values[index])) for index in indices)


def _selection_plan(
    component: NCoreComponent,
    selection: NCoreSelection,
    metadata: Mapping[str, object],
    read_key: _ReadKey,
) -> tuple[Callable[[str], bool], dict[str, np.ndarray], tuple[str, ...]]:
    if selection.frames is None and selection.timestamps_us is None:
        return lambda _name: True, {}, ()
    prefix = _component_prefix(component)
    if component.name in {"cameras", "lidars", "radars"}:
        groups = _relative_group_attributes(metadata, component)
        frame_ids = _sensor_frame_ids(groups.get("frames", {}), selection)
        selected = set(frame_ids)

        def include(name: str) -> bool:
            if not name.startswith("frames/"):
                return True
            parts = name.split("/")
            return len(parts) >= 2 and parts[1] in selected

        return include, {}, frame_ids
    if component.name == "point_clouds":
        full_name = f"{prefix}/pc_timestamps_us"
        timestamps = _decode_array(metadata, full_name, read_key)
        indices, _item_ids = _timestamp_item_ids(
            timestamps, selection, "NCore point-cloud"
        )
        selected = set(indices)

        def include(name: str) -> bool:
            if not name.startswith("pcs/"):
                return True
            parts = name.split("/")
            return len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) in selected

        return include, {"pc_timestamps_us": timestamps[list(indices)]}, tuple(
            str(index) for index in indices
        )
    if component.name == "camera_labels":
        full_name = f"{prefix}/timestamps_us"
        timestamps = _decode_array(metadata, full_name, read_key)
        indices, item_ids = _timestamp_item_ids(
            timestamps, selection, "NCore camera-label"
        )
        selected = set(item_ids)

        def include(name: str) -> bool:
            if not name.startswith("labels/"):
                return True
            parts = name.split("/")
            return len(parts) >= 2 and parts[1] in selected

        return include, {"timestamps_us": timestamps[list(indices)]}, item_ids
    raise ValueError(
        f"NCore component {component.id} does not define frame/timestamp selection"
    )


def read_ncore_component(
    path: str | Path,
    selection: NCoreSelection,
) -> NCoreComponentData:
    """Load one component into owned, read-only NumPy arrays."""

    if not isinstance(selection, NCoreSelection):
        raise TypeError("selection must be an NCoreSelection")
    dataset = read_ncore_v4(path)
    component = dataset.find_component(selection.component, selection.instance)
    if selection.group is not None and selection.group != component.group:
        raise KeyError(
            f"NCore component {component.id} does not exist in group "
            f"{selection.group!r}"
        )
    store = dataset.stores[component.store_index]
    store_path = Path(store.path)
    prefix = _component_prefix(component)
    with _store_reader(store_path) as (metadata, read_key):
        include, replacements, selected_items = _selection_plan(
            component,
            selection,
            metadata,
            read_key,
        )
        arrays: dict[str, np.ndarray] = {}
        for descriptor in component.arrays:
            if not include(descriptor.name):
                continue
            if descriptor.name in replacements:
                value = replacements[descriptor.name]
            else:
                value = _decode_array(
                    metadata,
                    f"{prefix}/{descriptor.name}",
                    read_key,
                )
            arrays[descriptor.name] = value
        group_attributes = _relative_group_attributes(metadata, component)
        groups = tuple(
            NCoreGroup(name, attributes)
            for name, attributes in sorted(group_attributes.items())
            if include(name)
        )
    return NCoreComponentData(
        component=component,
        selection=selection,
        arrays=arrays,
        groups=groups,
        selected_items=selected_items,
    )


__all__ = ["read_ncore_component"]
