"""Metadata-only inspection for image-sequence containers."""

from __future__ import annotations

from pathlib import Path

from sceneio import _core
from sceneio.io._inspectors.common import _compiled_buffer_inspect
from sceneio.io._inspectors.model import ArrayInspection, Inspection


def inspect_y4m(path: Path, datatype: str) -> Inspection:
    values = dict(_compiled_buffer_inspect(path, _core._inspect_y4m))
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    channels = values["channels"]
    arrays = [
        ArrayInspection("y", (frames, height, width), "uint8"),
    ]
    if channels == 3:
        chroma_shape = (
            frames,
            values["chroma_height"],
            values["chroma_width"],
        )
        arrays.extend(
            (
                ArrayInspection("u", chroma_shape, "uint8"),
                ArrayInspection("v", chroma_shape, "uint8"),
            )
        )
    return Inspection(
        format="y4m",
        datatype=datatype,
        byte_size=path.stat().st_size,
        shape=(frames, height, width, channels),
        dtype="uint8",
        count=frames,
        channels=channels,
        arrays=tuple(arrays),
        metadata={
            "storage_mode": "yuv_planar",
            "chroma_subsampling": values["chroma_subsampling"],
            "chroma_siting": values["chroma_siting"],
            "color_range": values["color_range"],
            "matrix": values["matrix"],
            "interlace": values["interlace"],
            "frame_rate_numerator": values["frame_rate_numerator"],
            "frame_rate_denominator": values["frame_rate_denominator"],
            "pixel_aspect_numerator": values["pixel_aspect_numerator"],
            "pixel_aspect_denominator": values["pixel_aspect_denominator"],
            "frame_bytes": values["frame_bytes"],
        },
    )
