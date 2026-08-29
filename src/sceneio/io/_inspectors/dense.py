"""Metadata-only inspection for dense-MVS formats."""

from __future__ import annotations

from pathlib import Path

from sceneio import _core
from sceneio.io._inspectors.common import _compiled_buffer_inspect
from sceneio.io._inspectors.model import Inspection


def inspect_colmap_mvs_depth(path: Path, datatype: str) -> Inspection:
    height, width, channels = _compiled_buffer_inspect(
        path, _core._inspect_colmap_mvs_depth
    )
    return Inspection(
        "colmap_mvs_depth",
        datatype,
        path.stat().st_size,
        shape=(height, width),
        dtype="float32",
        count=height * width,
        channels=channels,
        metadata={
            "wire_layout": "planar_chw",
            "record_layout": "row_major_hw",
            "byte_order": "little",
            "unit": "unknown",
            "scale_to_meters": 0.0,
            "invalid_policy": "nonpositive",
            "depth_convention": "camera_z",
        },
    )


def inspect_colmap_mvs_normal(path: Path, datatype: str) -> Inspection:
    height, width, channels = _compiled_buffer_inspect(
        path, _core._inspect_colmap_mvs_normal
    )
    return Inspection(
        "colmap_mvs_normal",
        datatype,
        path.stat().st_size,
        shape=(height, width, channels),
        dtype="float32",
        count=height * width,
        channels=channels,
        metadata={
            "wire_layout": "planar_chw",
            "record_layout": "interleaved_hwc",
            "byte_order": "little",
            "coordinate_system": "opencv_camera",
            "component_order": "xyz",
            "invalid_policy": "zero_vector",
            "orientation": "opposes_camera_to_surface_ray",
        },
    )


def inspect_colmap_mvs_consistency(path: Path, datatype: str) -> Inspection:
    height, width, entries, links = _compiled_buffer_inspect(
        path, _core._inspect_colmap_mvs_consistency
    )
    return Inspection(
        "colmap_mvs_consistency",
        datatype,
        path.stat().st_size,
        shape=(height, width),
        dtype="int32",
        count=entries,
        metadata={
            "image_index_count": links,
            "index_domain": "mvs_sequential_image_index",
            "byte_order": "little",
        },
    )


def inspect_colmap_fused_visibility(
    path: Path, datatype: str
) -> Inspection:
    points, links = _compiled_buffer_inspect(
        path, _core._inspect_colmap_fused_visibility
    )
    return Inspection(
        "colmap_fused_visibility",
        datatype,
        path.stat().st_size,
        count=points,
        metadata={
            "image_index_count": links,
            "index_domain": "mvs_sequential_image_index",
            "byte_order": "little",
        },
    )
