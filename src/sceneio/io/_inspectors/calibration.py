"""Metadata-only inspection for camera-calibration formats."""

from __future__ import annotations

from pathlib import Path

from sceneio import _core
from sceneio.io._inspectors.common import _compiled_buffer_inspect
from sceneio.io._inspectors.model import Inspection

_INSPECTORS = {
    "opencv_yaml": _core._inspect_opencv_yaml,
    "opencv_xml": _core._inspect_opencv_xml,
    "ros_camera_info": _core._inspect_ros_camera_info,
    "kalibr": _core._inspect_kalibr,
}


def inspect_camera_rig(
    path: Path,
    format_id: str,
    payload_kind: str,
) -> Inspection:
    """Inspect one calibration file using lower shared primitives."""

    count, flat_resolutions = _compiled_buffer_inspect(
        path,
        _INSPECTORS[format_id],
    )
    resolutions = tuple(int(value) for value in flat_resolutions)
    return Inspection(
        format_id,
        payload_kind,
        path.stat().st_size,
        shape=(count,),
        dtype="float64",
        count=count,
        metadata={
            "resolutions": resolutions,
            "axis_frame": "opencv",
        },
    )
