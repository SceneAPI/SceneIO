"""Metadata-only inspection for image-sequence containers."""

from __future__ import annotations

from pathlib import Path

from sceneio import _core
from sceneio.io._inspectors.common import _compiled_buffer_inspect
from sceneio.io._inspectors.model import ArrayInspection, Inspection


def inspect_apng(path: Path, payload_kind: str) -> Inspection:
    values = dict(_compiled_buffer_inspect(path, _core._inspect_apng))
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    channels = values["channels"]
    shape = (frames, height, width, channels)
    return Inspection(
        format="apng",
        payload_kind=payload_kind,
        byte_size=path.stat().st_size,
        shape=shape,
        dtype="uint8",
        count=frames,
        channels=channels,
        arrays=(ArrayInspection("pixels", shape, "uint8"),),
        metadata={
            "storage_mode": "packed",
            "color_space": values["color_space"],
            "alpha_mode": values["alpha_mode"],
            "loop_count": values["loop_count"],
            "duration_ns": values["duration_ns"],
        },
    )


def inspect_animated_webp(path: Path, payload_kind: str) -> Inspection:
    values = dict(
        _compiled_buffer_inspect(path, _core._inspect_animated_webp)
    )
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    channels = values["channels"]
    shape = (frames, height, width, channels)
    return Inspection(
        format="animated_webp",
        payload_kind=payload_kind,
        byte_size=path.stat().st_size,
        shape=shape,
        dtype="uint8",
        count=frames,
        channels=channels,
        arrays=(ArrayInspection("pixels", shape, "uint8"),),
        metadata={
            "storage_mode": "packed",
            "color_space": values["color_space"],
            "alpha_mode": values["alpha_mode"],
            "loop_count": values["loop_count"],
            "duration_ns": values["duration_ns"],
            "background_rgba": values["background_rgba"],
        },
    )


def inspect_y4m(path: Path, payload_kind: str) -> Inspection:
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
        payload_kind=payload_kind,
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


def inspect_webm(path: Path, payload_kind: str) -> Inspection:
    values = dict(_compiled_buffer_inspect(path, _core._inspect_webm))
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    channels = values["channels"]
    shape = (frames, height, width, channels)
    storage_mode = values["storage_mode"]
    chroma_shape = (frames, (height + 1) // 2, (width + 1) // 2)
    arrays = (
        (ArrayInspection("pixels", shape, "uint8"),)
        if storage_mode == "packed"
        else (
            ArrayInspection("y", (frames, height, width), "uint8"),
            ArrayInspection("u", chroma_shape, "uint8"),
            ArrayInspection("v", chroma_shape, "uint8"),
        )
    )
    return Inspection(
        format="webm",
        payload_kind=payload_kind,
        byte_size=path.stat().st_size,
        shape=shape,
        dtype="uint8",
        count=frames,
        channels=channels,
        arrays=arrays,
        metadata={
            "storage_mode": storage_mode,
            "color_space": values["color_space"],
            "alpha_mode": values["alpha_mode"],
            "codec": values["codec"],
            "profile": values["profile"],
            "matrix": values["matrix"],
            "color_range": values["color_range"],
            "keyframes": values["keyframes"],
            "duration_ns": values["duration_ns"],
        },
    )


def inspect_ivf(path: Path, payload_kind: str) -> Inspection:
    values = dict(_compiled_buffer_inspect(path, _core._inspect_ivf))
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    chroma_shape = (frames, (height + 1) // 2, (width + 1) // 2)
    return Inspection(
        format="ivf",
        payload_kind=payload_kind,
        byte_size=path.stat().st_size,
        shape=(frames, height, width, 3),
        dtype="uint8",
        count=frames,
        channels=3,
        arrays=(
            ArrayInspection("y", (frames, height, width), "uint8"),
            ArrayInspection("u", chroma_shape, "uint8"),
            ArrayInspection("v", chroma_shape, "uint8"),
        ),
        metadata={
            "storage_mode": "yuv_planar",
            "codec": values["codec"],
            "color_space": values["color_space"],
            "alpha_mode": values["alpha_mode"],
            "chroma_subsampling": "420",
            "frame_rate_numerator": values["frame_rate_numerator"],
            "frame_rate_denominator": values["frame_rate_denominator"],
        },
    )


def inspect_mjpeg(path: Path, payload_kind: str) -> Inspection:
    values = dict(_compiled_buffer_inspect(path, _core._inspect_mjpeg))
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    channels = values["channels"]
    shape = (frames, height, width, channels)
    return Inspection(
        format="mjpeg",
        payload_kind=payload_kind,
        byte_size=path.stat().st_size,
        shape=shape,
        dtype="uint8",
        count=frames,
        channels=channels,
        arrays=(ArrayInspection("pixels", shape, "uint8"),),
        metadata={
            "storage_mode": values["storage_mode"],
            "codec": values["codec"],
            "color_space": values["color_space"],
            "alpha_mode": values["alpha_mode"],
            "timing": values["timing"],
        },
    )


def inspect_mp4(path: Path, payload_kind: str) -> Inspection:
    values = dict(_compiled_buffer_inspect(path, _core._inspect_mp4))
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    channels = values["channels"]
    arrays = [ArrayInspection("y", (frames, height, width), "uint8")]
    subsampling = values["chroma_subsampling"]
    if channels == 3:
        if subsampling == "420":
            chroma_shape = (frames, (height + 1) // 2, (width + 1) // 2)
        elif subsampling == "422":
            chroma_shape = (frames, height, (width + 1) // 2)
        else:
            chroma_shape = (frames, height, width)
        arrays.extend(
            (
                ArrayInspection("u", chroma_shape, "uint8"),
                ArrayInspection("v", chroma_shape, "uint8"),
            )
        )
    return Inspection(
        format="mp4",
        payload_kind=payload_kind,
        byte_size=path.stat().st_size,
        shape=(frames, height, width, channels),
        dtype="uint8",
        count=frames,
        channels=channels,
        arrays=tuple(arrays),
        metadata={
            "storage_mode": values["storage_mode"],
            "codec": values["codec"],
            "source_bit_depth": values["source_bit_depth"],
            "color_space": values["color_space"],
            "color_range": values["color_range"],
            "matrix": values["matrix"],
            "alpha_mode": values["alpha_mode"],
            "chroma_subsampling": subsampling,
            "frame_rate_numerator": values["frame_rate_numerator"],
            "frame_rate_denominator": values["frame_rate_denominator"],
            "pixel_aspect_numerator": values["pixel_aspect_numerator"],
            "pixel_aspect_denominator": values["pixel_aspect_denominator"],
            "duration_ns": values["duration_ns"],
            "timing_projection": values["timing_projection"],
        },
    )


def inspect_theora(path: Path, payload_kind: str) -> Inspection:
    values = dict(_compiled_buffer_inspect(path, _core._inspect_theora))
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    chroma_shape = (
        frames,
        values["chroma_height"],
        values["chroma_width"],
    )
    return Inspection(
        format="theora",
        payload_kind=payload_kind,
        byte_size=path.stat().st_size,
        shape=(frames, height, width, 3),
        dtype="uint8",
        count=frames,
        channels=3,
        arrays=(
            ArrayInspection("y", (frames, height, width), "uint8"),
            ArrayInspection("u", chroma_shape, "uint8"),
            ArrayInspection("v", chroma_shape, "uint8"),
        ),
        metadata={
            "storage_mode": "yuv_planar",
            "codec": "theora",
            "version": values["version"],
            "chroma_subsampling": values["chroma_subsampling"],
            "chroma_siting": values["chroma_siting"],
            "color_range": values["color_range"],
            "matrix": values["matrix"],
            "interlace": values["interlace"],
            "frame_rate_numerator": values["frame_rate_numerator"],
            "frame_rate_denominator": values["frame_rate_denominator"],
            "pixel_aspect_numerator": values["pixel_aspect_numerator"],
            "pixel_aspect_denominator": values["pixel_aspect_denominator"],
            "frame_width": values["frame_width"],
            "frame_height": values["frame_height"],
            "picture_x": values["picture_x"],
            "picture_y": values["picture_y"],
            "keyframe_granule_shift": values["keyframe_granule_shift"],
        },
    )
