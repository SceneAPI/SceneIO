"""Metadata-only inspection for camera-calibration formats."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sceneio import _core

_INSPECTORS = {
    "opencv_yaml": _core._inspect_opencv_yaml,
    "opencv_xml": _core._inspect_opencv_xml,
    "ros_camera_info": _core._inspect_ros_camera_info,
    "kalibr": _core._inspect_kalibr,
}


def inspect_camera_rig(
    path: Path,
    format_id: str,
    datatype: str,
    *,
    inspection_type: Callable[..., object],
    inspect_buffer: Callable[[Path, Callable[..., object]], object],
) -> object:
    """Inspect one calibration file using facade-owned shared primitives."""

    count, flat_resolutions = inspect_buffer(path, _INSPECTORS[format_id])
    resolutions = tuple(int(value) for value in flat_resolutions)
    return inspection_type(
        format_id,
        datatype,
        path.stat().st_size,
        shape=(count,),
        dtype="float64",
        count=count,
        metadata={
            "resolutions": resolutions,
            "axis_frame": "opencv",
        },
    )
