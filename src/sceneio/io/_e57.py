"""Cartesian E57 adapter for ordered, metadata-preserving scan sets."""

from __future__ import annotations

import operator
import os
import tempfile
from contextlib import suppress
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.model import Inspection

_CARTESIAN_FIELDS = ("cartesianX", "cartesianY", "cartesianZ")
_COLOR_FIELDS = ("colorRed", "colorGreen", "colorBlue")
_SUPPORTED_FIELDS = frozenset(
    {
        *_CARTESIAN_FIELDS,
        *_COLOR_FIELDS,
        "intensity",
        "cartesianInvalidState",
        "rowIndex",
        "columnIndex",
    }
)
_SUPPORTED_SCAN_FIELDS = frozenset(
    {
        "guid",
        "name",
        "temperature",
        "relativeHumidity",
        "atmosphericPressure",
        "description",
        "indexBounds",
        "cartesianBounds",
        "intensityLimits",
        "colorLimits",
        "pose",
        "acquisitionStart",
        "acquisitionEnd",
        "points",
    }
)
_RANGE_BUFFER_CAPACITY = 65_536


def _require_pye57():
    try:
        import pye57
    except ModuleNotFoundError:
        raise RuntimeError(
            "E57 support requires the optional dependency; "
            "install sceneio[e57]"
        ) from None
    return pye57


def _header_value(header, name: str, default=None):
    """Read one optional pye57 header value without decoding point data."""

    node = getattr(header, "node", None)
    if node is None:
        return default
    try:
        if not node.isDefined(name):
            return default
        return node[name].value()
    except (AttributeError, KeyError, RuntimeError):
        return default


def _scan_header(source, index: int):
    """Return and validate one Cartesian scan header."""

    try:
        index = operator.index(index)
    except TypeError:
        raise TypeError("E57: scan_index must be an integer") from None
    if isinstance(index, bool) or index < 0 or index >= source.scan_count:
        raise IndexError(
            f"E57: scan_index {index!r} is outside [0, {source.scan_count})"
        )
    header = source.get_header(index)
    unsupported_scan = set(getattr(header, "scan_fields", ())) - _SUPPORTED_SCAN_FIELDS
    if unsupported_scan:
        raise ValueError(
            "E57: unsupported scan metadata "
            + ", ".join(sorted(unsupported_scan))
        )
    try:
        if source.root["images2D"].childCount() > 0:
            raise ValueError("E57: imagery is unsupported")
    except (KeyError, AttributeError, RuntimeError):
        pass
    fields = frozenset(header.point_fields)
    missing = set(_CARTESIAN_FIELDS) - fields
    if missing:
        raise ValueError(
            "E57: Cartesian coordinates are required; missing "
            + ", ".join(sorted(missing))
        )
    unsupported = fields - _SUPPORTED_FIELDS
    if unsupported:
        raise ValueError(
            "E57: unsupported point fields "
            + ", ".join(sorted(unsupported))
        )
    color_count = sum(field in fields for field in _COLOR_FIELDS)
    if color_count not in {0, 3}:
        raise ValueError("E57: RGB color fields must be present together")
    row_count = sum(field in fields for field in ("rowIndex", "columnIndex"))
    if row_count not in {0, 2}:
        raise ValueError(
            "E57: rowIndex and columnIndex fields must be present together"
        )
    count = int(header.point_count)
    if count < 1:
        raise ValueError("E57: empty scans are unsupported")
    return header, fields


def _exact_float32(values: object, context: str) -> np.ndarray:
    source = np.asarray(values)
    result = np.ascontiguousarray(source, dtype=np.float32)
    if not np.array_equal(result.astype(source.dtype), source):
        raise ValueError(
            f"E57: {context} values are not exactly representable as float32"
        )
    return result


def _exact_uint8(values: object, context: str) -> np.ndarray:
    source = np.asarray(values)
    if source.size and (
        not np.isfinite(source).all()
        or np.any(source < 0)
        or np.any(source > 255)
    ):
        raise ValueError(f"E57: {context} values must lie in [0, 255]")
    result = np.ascontiguousarray(source, dtype=np.uint8)
    if not np.array_equal(result.astype(source.dtype), source):
        raise ValueError(
            f"E57: {context} values are not exactly representable as uint8"
        )
    return result


def _exact_invalid_state(values: object, context: str = "invalid_states") -> np.ndarray:
    result = _exact_uint8(values, context)
    if result.size and not np.isin(result, (0, 1, 2)).all():
        raise ValueError(f"E57: {context} values must be E57 states 0, 1, or 2")
    return result


def _exact_int64(values: object, context: str) -> np.ndarray:
    source = np.asarray(values)
    if source.ndim != 1:
        raise ValueError(f"E57: {context} values must be one-dimensional")
    if source.size and np.issubdtype(source.dtype, np.floating) and (
        not np.isfinite(source).all()
        or not np.equal(source, np.floor(source)).all()
    ):
        raise ValueError(f"E57: {context} values must be integral")
    if source.size and np.issubdtype(source.dtype, np.unsignedinteger) and np.any(
        source > np.iinfo(np.int64).max
    ):
        raise ValueError(f"E57: {context} values must fit int64")
    if source.size and np.issubdtype(source.dtype, np.signedinteger) and np.any(
        source < np.iinfo(np.int64).min
    ):
        raise ValueError(f"E57: {context} values must fit int64")
    if source.size and np.issubdtype(source.dtype, np.floating):
        limits = np.iinfo(np.int64)
        if np.any(source < limits.min) or np.any(source > limits.max):
            raise ValueError(f"E57: {context} values must fit int64")
    try:
        result = np.ascontiguousarray(source, dtype=np.int64)
    except (OverflowError, ValueError):
        raise ValueError(f"E57: {context} values must fit int64") from None
    if not np.array_equal(result.astype(source.dtype), source):
        raise ValueError(
            f"E57: {context} values are not exactly representable as int64"
        )
    return result


def _scan_name(header) -> str:
    value = _header_value(header, "name", "")
    return "" if value is None else str(value)


def _scan_timestamp(header):
    node = getattr(header, "node", None)
    try:
        if node is None or not node.isDefined("acquisitionStart"):
            return None
    except (AttributeError, RuntimeError):
        return None
    try:
        return float(header.acquisitionStart_dateTimeValue)
    except (AttributeError, TypeError, ValueError):
        return None


def _scan_guid(header) -> str:
    try:
        return str(header.guid)
    except (AttributeError, TypeError, ValueError):
        return ""


def _scan_bounds(header) -> tuple[int, int, int, int]:
    try:
        values = (
            int(header.rowMinimum),
            int(header.rowMaximum),
            int(header.columnMinimum),
            int(header.columnMaximum),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("E57: scan index bounds are unavailable") from exc
    if values[0] > values[1] or values[2] > values[3]:
        raise ValueError("E57: scan index bounds are inverted")
    if min(values) < 0:
        raise ValueError("E57: scan index bounds must be nonnegative")
    return values


def _selected_range(count: int, stored_point_range):
    if stored_point_range is None:
        return 0, count
    if not isinstance(stored_point_range, (tuple, list)) or len(stored_point_range) != 2:
        raise ValueError(
            "E57: stored_point_range must be a half-open (start, stop) pair"
        )
    try:
        start, stop = (
            operator.index(stored_point_range[0]),
            operator.index(stored_point_range[1]),
        )
    except TypeError:
        raise TypeError(
            "E57: stored_point_range values must be integers"
        ) from None
    if isinstance(stored_point_range[0], bool) or isinstance(stored_point_range[1], bool):
        raise TypeError("E57: stored_point_range values must be integers")
    if start < 0 or stop < start or stop > count:
        raise ValueError(
            f"E57: stored_point_range {(start, stop)!r} is outside [0, {count}]"
        )
    if start == stop:
        raise ValueError("E57: stored_point_range must select at least one row")
    return int(start), int(stop)


def _copy_raw_arrays(raw: dict[str, object], fields, count: int):
    result = {}
    for field in fields:
        if field not in raw:
            raise ValueError(f"E57: provider omitted required point field {field!r}")
        array = np.asarray(raw[field])
        if array.ndim != 1 or len(array) != count:
            raise ValueError(
                f"E57: provider returned malformed {field!r} point field"
            )
        result[field] = np.ascontiguousarray(array).copy()
    return result


def _read_raw_range(source, header, fields, start: int, stop: int):
    """Read one stored-row range through a fixed-capacity E57 stream."""

    capacity = min(_RANGE_BUFFER_CAPACITY, int(header.point_count))
    arrays, buffers = source.make_buffers(tuple(fields), capacity)
    reader = header.points.reader(buffers)
    output = {}
    try:
        for field, array in arrays.items():
            output[field] = np.empty(stop - start, dtype=np.asarray(array).dtype)
        offset = 0
        copied = 0
        while offset < stop:
            read_count = int(reader.read())
            if read_count <= 0:
                break
            chunk_start = max(start, offset)
            chunk_stop = min(stop, offset + read_count)
            if chunk_start < chunk_stop:
                source_start = chunk_start - offset
                source_stop = source_start + (chunk_stop - chunk_start)
                destination_start = chunk_start - start
                destination_stop = destination_start + (chunk_stop - chunk_start)
                for field, array in arrays.items():
                    output[field][destination_start:destination_stop] = np.asarray(
                        array[source_start:source_stop]
                    )
                copied = destination_stop
            offset += read_count
        if copied != stop - start:
            raise ValueError("E57: provider returned fewer rows than requested")
    finally:
        with suppress(Exception):
            reader.close()
    return output


def _scan_from_raw(
    header,
    fields,
    raw: dict[str, object],
    *,
    scan_index: int,
):
    count = len(np.asarray(raw["cartesianX"]))
    raw = _copy_raw_arrays(raw, fields, count)
    invalid_states = None
    valid = np.ones(count, dtype=np.bool_)
    if "cartesianInvalidState" in fields:
        invalid_states = _exact_invalid_state(
            raw["cartesianInvalidState"], "cartesianInvalidState"
        )
        valid = invalid_states == 0

    positions = np.zeros((count, 3), dtype=np.float32)
    for axis, field in enumerate(_CARTESIAN_FIELDS):
        # Invalid rows carry no Cartesian meaning.  Canonicalize them to zero
        # while retaining exact float32 validation for every valid row.
        positions[valid, axis] = _exact_float32(
            np.asarray(raw[field])[valid], field
        )

    colors = None
    if all(field in fields for field in _COLOR_FIELDS):
        colors = np.column_stack(
            [_exact_uint8(raw[field], field) for field in _COLOR_FIELDS]
        )
    intensity = None
    if "intensity" in fields:
        intensity = _exact_float32(raw["intensity"], "intensity")

    row_indices = None
    column_indices = None
    row_minimum, row_maximum, column_minimum, column_maximum = _scan_bounds(
        header
    )
    if "rowIndex" in fields:
        row_indices = _exact_int64(raw["rowIndex"], "rowIndex")
        column_indices = _exact_int64(raw["columnIndex"], "columnIndex")
        if np.any(row_indices < 0) or np.any(column_indices < 0):
            raise ValueError("E57: row/column indices must be nonnegative")
        if np.any(row_indices < row_minimum) or np.any(row_indices > row_maximum):
            raise ValueError("E57: rowIndex values exceed declared row bounds")
        if np.any(
            (column_indices < column_minimum)
            | (column_indices > column_maximum)
        ):
            raise ValueError("E57: columnIndex values exceed declared column bounds")

    cloud = _core.point_cloud(
        positions,
        colors=colors,
        intensity=intensity,
        coordinate_frame="unknown",
        scale_to_meters=1.0,
        intensity_range="unknown",
    )
    translation = np.asarray(header.translation, dtype=np.float64)
    rotation = np.asarray(header.rotation, dtype=np.float64)
    viewpoint = np.concatenate((translation, rotation))
    return _core.point_scan(
        cloud,
        scan_id=int(scan_index),
        invalid_states=invalid_states,
        row_indices=row_indices,
        column_indices=column_indices,
        row_minimum=row_minimum,
        row_maximum=row_maximum,
        column_minimum=column_minimum,
        column_maximum=column_maximum,
        name=_scan_name(header),
        guid=_scan_guid(header),
        timestamp=_scan_timestamp(header),
        viewpoint=viewpoint,
    )


def _read_scan(source, index: int, stored_point_range=None):
    header, fields = _scan_header(source, index)
    count = int(header.point_count)
    start, stop = _selected_range(count, stored_point_range)
    if stored_point_range is None:
        raw = source.read_scan_raw(index)
    else:
        raw = _read_raw_range(source, header, fields, start, stop)
    return _scan_from_raw(
        header,
        fields,
        raw,
        scan_index=operator.index(index),
    )


def _is_point_scan(value) -> bool:
    return isinstance(value, _core.PointScan)


def _is_scan_set(value) -> bool:
    return isinstance(value, _core.ScanSet)


def read_e57(path: str | Path):
    """Read every stored scan into one ordered ScanSet."""

    pye57 = _require_pye57()
    with pye57.E57(str(path)) as source:
        if source.scan_count < 1:
            raise ValueError("E57: file contains no data3D scans")
        return _core.scan_set(
            tuple(_read_scan(source, index) for index in range(source.scan_count))
        )


def read_e57_scan(
    path: str | Path,
    *,
    scan_index: int = 0,
    stored_point_range: tuple[int, int] | None = None,
):
    """Read one E57 scan, optionally selecting stored rows."""

    pye57 = _require_pye57()
    with pye57.E57(str(path)) as source:
        return _read_scan(source, scan_index, stored_point_range)


def _cloud_payload(cloud) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    if not isinstance(cloud, _core.PointCloud):
        raise TypeError("E57: expected a PointCloud")
    if cloud.num_points < 1:
        raise ValueError("E57: empty point clouds are unsupported")
    if cloud.coordinate_frame != "unknown" or cloud.scale_to_meters != 1.0:
        raise ValueError(
            "E57: requires coordinate_frame='unknown' and scale_to_meters=1"
        )
    if cloud.is_organized:
        raise ValueError("E57: organized point clouds are unsupported")
    if cloud.has_normals:
        raise ValueError("E57: normals are unsupported")
    if cloud.has_rgb16:
        raise ValueError("E57: 16-bit colors are unsupported")
    if cloud.has_las_waveform:
        raise ValueError("E57: LAS waveform data are unsupported")
    if cloud.has_tracks:
        raise ValueError("E57: point observation tracks are unsupported")
    extended_fields = (
        "display_colors",
        "display_opacities",
        "widths",
        "ids",
        "velocities",
        "accelerations",
    )
    if any(getattr(cloud, f"has_{name}") for name in extended_fields) or (
        cloud.display_color_space != "unknown"
    ):
        raise ValueError(
            "E57: float display colors/opacities, widths, ids, velocities, "
            "accelerations, and display_color_space are unsupported"
        )
    if cloud.has_intensity and cloud.intensity_range != "unknown":
        raise ValueError("E57: intensity_range must be 'unknown'")
    if tuple(float(value) for value in cloud.origin) != (0.0, 0.0, 0.0):
        raise ValueError("E57: a separate georeference origin is unsupported")

    positions = np.asarray(cloud.positions)
    data = {
        "cartesianX": np.ascontiguousarray(positions[:, 0]),
        "cartesianY": np.ascontiguousarray(positions[:, 1]),
        "cartesianZ": np.ascontiguousarray(positions[:, 2]),
    }
    if cloud.has_rgb:
        colors = np.asarray(cloud.colors)
        data.update(
            {
                "colorRed": np.ascontiguousarray(colors[:, 0]),
                "colorGreen": np.ascontiguousarray(colors[:, 1]),
                "colorBlue": np.ascontiguousarray(colors[:, 2]),
            }
        )
    if cloud.has_intensity:
        data["intensity"] = np.ascontiguousarray(cloud.intensities)
    viewpoint = np.asarray(cloud.viewpoint, dtype=np.float64)
    return data, viewpoint[3:], viewpoint[:3]


def _point_scan_payload(scan):
    if not _is_point_scan(scan):
        raise TypeError("E57: expected a PointScan")
    cloud = scan.point_cloud
    data, _rotation, _translation = _cloud_payload(cloud)
    count = int(cloud.num_points)
    invalid = None
    if scan.has_invalid_states:
        invalid = scan.invalid_states
    if invalid is not None:
        invalid = _exact_invalid_state(invalid, "invalid_states")
        if len(invalid) != count:
            raise ValueError("E57: invalid_states must match stored point count")
        if not np.any(invalid == 0):
            raise ValueError("E57: scan contains no valid Cartesian points")
        for field in _CARTESIAN_FIELDS:
            values = np.array(data[field], copy=True)
            values[invalid != 0] = 0
            data[field] = values
        data["cartesianInvalidState"] = invalid

    row_indices = None
    column_indices = None
    if scan.has_row_column_indices:
        row_indices = scan.row_indices
        column_indices = scan.column_indices
    if (row_indices is None) != (column_indices is None):
        raise ValueError(
            "E57: row_indices and column_indices must be present together"
        )
    if row_indices is not None:
        row_indices = _exact_int64(row_indices, "row_indices")
        column_indices = _exact_int64(column_indices, "column_indices")
        if len(row_indices) != count or len(column_indices) != count:
            raise ValueError("E57: row/column indices must match stored point count")
        bounds = (
            int(scan.row_minimum),
            int(scan.row_maximum),
            int(scan.column_minimum),
            int(scan.column_maximum),
        )
        if bounds[0] > bounds[1] or bounds[2] > bounds[3]:
            raise ValueError("E57: scan index bounds are inverted")
        if np.any(row_indices < bounds[0]) or np.any(row_indices > bounds[1]):
            raise ValueError("E57: row_indices exceed declared row bounds")
        if np.any(
            (column_indices < bounds[2]) | (column_indices > bounds[3])
        ):
            raise ValueError("E57: column_indices exceed declared column bounds")
        if np.any(row_indices < 0) or np.any(column_indices < 0):
            raise ValueError("E57: pye57 index fields must be nonnegative")
        if bounds[0] != int(row_indices.min()) or bounds[1] != int(row_indices.max()):
            raise ValueError(
                "E57: pye57 can preserve row bounds only when they equal index extrema"
            )
        if bounds[2] != int(column_indices.min()) or bounds[3] != int(column_indices.max()):
            raise ValueError(
                "E57: pye57 can preserve column bounds only when they equal index extrema"
            )
        uint16 = np.iinfo(np.uint16)
        if (
            np.any(row_indices < uint16.min)
            or np.any(row_indices > uint16.max)
            or np.any(column_indices < uint16.min)
            or np.any(column_indices > uint16.max)
        ):
            raise ValueError("E57: pye57 index fields support only uint16 values")
        data["rowIndex"] = np.ascontiguousarray(row_indices, dtype=np.uint16)
        data["columnIndex"] = np.ascontiguousarray(column_indices, dtype=np.uint16)

    viewpoint = np.asarray(scan.viewpoint, dtype=np.float64)
    if viewpoint.shape != (7,) or not np.isfinite(viewpoint).all():
        raise ValueError("E57: PointScan viewpoint must be finite float64 (7,)")
    name = str(scan.name)
    guid = str(scan.guid)
    if guid:
        raise ValueError(
            "E57: pye57 generates scan GUIDs; non-empty PointScan.guid is not writable"
        )
    timestamp = scan.timestamp
    if timestamp is not None:
        try:
            timestamp = float(timestamp)
        except (TypeError, ValueError):
            raise ValueError("E57: PointScan.timestamp must be numeric") from None
        if not np.isfinite(timestamp):
            raise ValueError("E57: PointScan.timestamp must be finite")
    else:
        raise ValueError(
            "E57: writes require a timestamp because pye57 authors acquisitionStart"
        )

    # pye57 only accepts provider-defined index fields and always emits a
    # generated GUID.  The proxy supplies the metadata it can preserve while
    # keeping Cartesian bounds in the common/reference frame.
    valid = np.ones(count, dtype=np.bool_)
    if invalid is not None:
        valid = invalid == 0
    local = np.column_stack([data[name][valid] for name in _CARTESIAN_FIELDS])
    if not len(local):
        raise ValueError("E57: scan contains no valid Cartesian points")
    quaternion = viewpoint[3:]
    w, x, y, z = (float(value) for value in quaternion)
    rotation_matrix = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    global_points = local.astype(np.float64) @ rotation_matrix.T + viewpoint[:3]
    global_min = np.min(global_points, axis=0)
    global_max = np.max(global_points, axis=0)
    proxy = type("_E57HeaderProxy", (), {})()
    proxy.name = name or "Scan"
    proxy.temperature = 0.0
    proxy.relativeHumidity = 0.0
    proxy.atmosphericPressure = 0.0
    proxy.xMinimum, proxy.yMinimum, proxy.zMinimum = global_min
    proxy.xMaximum, proxy.yMaximum, proxy.zMaximum = global_max
    if "intensity" in data:
        proxy.intensityMinimum = float(np.min(data["intensity"]))
        proxy.intensityMaximum = float(np.max(data["intensity"]))
    proxy.acquisitionStart_dateTimeValue = timestamp
    proxy.acquisitionStart_isAtomicClockReferenced = False
    proxy.acquisitionEnd_dateTimeValue = timestamp
    proxy.acquisitionEnd_isAtomicClockReferenced = False
    return (
        data,
        np.ascontiguousarray(viewpoint[3:]),
        np.ascontiguousarray(viewpoint[:3]),
        proxy,
    )


def _write_scan(output, scan, scan_index: int) -> None:
    if int(scan.scan_id) != int(scan_index):
        raise ValueError(
            "E57: scan_id is not representable; it must equal output scan index"
        )
    data, rotation, translation, proxy = _point_scan_payload(scan)
    name = proxy.name or f"Scan {scan_index}"
    output.write_scan_raw(
        data,
        name=name,
        rotation=rotation,
        translation=translation,
        scan_header=proxy,
    )


def _write_scan_set(value, path: str | Path) -> None:
    if not _is_scan_set(value):
        raise TypeError("E57: expected a ScanSet")
    scans = tuple(value.scans)
    if not scans:
        raise ValueError("E57: empty ScanSet is unsupported")
    pye57 = _require_pye57()
    destination = Path(path)
    destination.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".e57.tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.unlink()
        with pye57.E57(str(temporary), mode="w") as output:
            for index, scan in enumerate(scans):
                _write_scan(output, scan, index)
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def write_e57(value, path: str | Path) -> None:
    """Write one ordered ScanSet atomically."""

    _write_scan_set(value, path)


def _scan_inspection(
    source_path: Path,
    header,
    fields,
    *,
    scan_index: int,
) -> Inspection:
    row_minimum, row_maximum, column_minimum, column_maximum = _scan_bounds(
        header
    )
    count = int(header.point_count)
    scan_metadata = {
        "scan_index": int(scan_index),
        "scan_id": int(scan_index),
        "name": _scan_name(header),
        "guid": _scan_guid(header),
        "timestamp": _scan_timestamp(header),
        "stored_point_count": count,
        "element_count": count,
        "valid_point_count": None,
        "fields": tuple(sorted(fields)),
        "point_fields": tuple(sorted(fields)),
        "has_colors": all(name in fields for name in _COLOR_FIELDS),
        "has_intensity": "intensity" in fields,
        "has_invalid_state": "cartesianInvalidState" in fields,
        "has_row_column": "rowIndex" in fields,
        "row_minimum": row_minimum,
        "row_maximum": row_maximum,
        "column_minimum": column_minimum,
        "column_maximum": column_maximum,
        "translation": tuple(float(value) for value in header.translation),
        "rotation": tuple(float(value) for value in header.rotation),
        "pose_convention": "scan_to_reference",
        "quaternion_order": "wxyz",
    }
    return Inspection(
        format="e57",
        payload_kind="scan_set",
        byte_size=source_path.stat().st_size,
        shape=(count, 3),
        dtype=None,
        count=count,
        metadata=scan_metadata,
    )


def inspect_e57(path: str | Path) -> Inspection:
    """Inspect E57 scan headers without decoding point payloads.

    ``dtype`` is ``None`` because this is a heterogeneous scan aggregate;
    exact coordinate and attribute fields are reported per scan in
    ``metadata["scans"]``.
    """

    pye57 = _require_pye57()
    source_path = Path(path)
    with pye57.E57(str(source_path)) as source:
        if source.scan_count < 1:
            raise ValueError("E57: file contains no data3D scans")
        headers = tuple(
            _scan_header(source, index)
            for index in range(source.scan_count)
        )
        scans = tuple(
            _scan_inspection(source_path, header, fields, scan_index=index)
            for index, (header, fields) in enumerate(headers)
        )
        count = sum(item.count or 0 for item in scans)
        return Inspection(
            format="e57",
            payload_kind="scan_set",
            byte_size=source_path.stat().st_size,
            shape=(len(scans),),
            dtype=None,
            count=count,
            metadata={
                "scan_count": len(scans),
                "stored_point_count": count,
                "element_count": count,
                "valid_point_count": None,
                "scans": tuple(dict(item.metadata) for item in scans),
            },
        )


__all__ = [
    "inspect_e57",
    "read_e57",
    "read_e57_scan",
    "write_e57",
]
