"""Single-scan Cartesian E57 point-cloud adapter backed by ``pye57``."""

from __future__ import annotations

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
    }
)


def _require_pye57():
    try:
        import pye57
    except ModuleNotFoundError:
        raise RuntimeError(
            "E57 support requires the optional dependency; "
            "install sceneio[e57]"
        ) from None
    return pye57


def _single_header(source):
    if source.scan_count != 1:
        raise ValueError("E57: exactly one data3D scan is supported")
    header = source.get_header(0)
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
    if "rowIndex" in fields or "columnIndex" in fields:
        raise ValueError("E57: organized row/column scans are unsupported")
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


def read_e57(path: str | Path):
    """Read one Cartesian E57 scan into a convention-tagged PointCloud."""

    pye57 = _require_pye57()
    with pye57.E57(str(path)) as source:
        header, fields = _single_header(source)
        raw = source.read_scan_raw(0)
        count = int(header.point_count)
        valid = np.ones(count, dtype=bool)
        if "cartesianInvalidState" in fields:
            valid = np.asarray(raw["cartesianInvalidState"]) == 0
        if not np.any(valid):
            raise ValueError("E57: scan contains no valid Cartesian points")
        positions = np.column_stack(
            [_exact_float32(raw[name][valid], name) for name in _CARTESIAN_FIELDS]
        ).astype(np.float32, copy=False)
        colors = None
        if all(name in fields for name in _COLOR_FIELDS):
            colors = np.column_stack(
                [
                    _exact_uint8(raw[name][valid], name)
                    for name in _COLOR_FIELDS
                ]
            )
        intensity = None
        if "intensity" in fields:
            intensity = _exact_float32(raw["intensity"][valid], "intensity")
        translation = np.asarray(header.translation, dtype=np.float64)
        rotation = np.asarray(header.rotation, dtype=np.float64)
        viewpoint = np.concatenate((translation, rotation))
    return _core.point_cloud(
        positions,
        colors=colors,
        intensity=intensity,
        coordinate_frame="unknown",
        scale_to_meters=1.0,
        intensity_range="unknown",
        viewpoint=viewpoint,
    )


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


def write_e57(cloud, path: str | Path) -> None:
    """Write one Cartesian PointCloud as a single pye57/libE57Format scan."""

    data, rotation, translation = _cloud_payload(cloud)
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
    temporary.unlink()
    try:
        with pye57.E57(str(temporary), mode="w") as output:
            output.write_scan_raw(
                data,
                rotation=rotation,
                translation=translation,
            )
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def inspect_e57(path: str | Path) -> Inspection:
    """Inspect the single-scan E57 profile without decoding point buffers."""

    pye57 = _require_pye57()
    source_path = Path(path)
    with pye57.E57(str(source_path)) as source:
        header, fields = _single_header(source)
        count = int(header.point_count)
        if count < 1:
            raise ValueError("E57: empty scans are unsupported")
        has_colors = all(name in fields for name in _COLOR_FIELDS)
        has_intensity = "intensity" in fields
        has_invalid_state = "cartesianInvalidState" in fields
        stored_count = count
        if has_invalid_state:
            raw = source.read_scan_raw(0)
            invalid = np.asarray(raw["cartesianInvalidState"])
            if invalid.ndim != 1 or len(invalid) != stored_count:
                raise ValueError(
                    "E57: invalid-state count does not match the scan header"
                )
            count = int(np.count_nonzero(invalid == 0))
            if count < 1:
                raise ValueError("E57: scan contains no valid Cartesian points")
    return Inspection(
        format="e57",
        datatype="point_cloud",
        byte_size=source_path.stat().st_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={
            "scan_count": 1,
            "has_colors": has_colors,
            "has_intensity": has_intensity,
            "has_invalid_state": has_invalid_state,
            "stored_point_count": stored_count,
        },
    )


__all__ = ["inspect_e57", "read_e57", "write_e57"]
