"""Small primitives shared by independent metadata-inspector families."""

from __future__ import annotations

import mmap
from pathlib import Path
from typing import BinaryIO

from sceneio.io._inspectors.model import Inspection, MetadataValue

_HEADER_LIMIT = 1024 * 1024
_IMAGE_PIXEL_CAP = 250_000_000


def _exact(stream: BinaryIO, length: int, what: str) -> bytes:
    data = stream.read(length)
    if len(data) != length:
        raise ValueError(f"truncated {what}")
    return data


def _unsigned_decimal(token: bytes, what: str) -> int:
    if not token or not token.isdigit():
        raise ValueError(f"{what}: expected an unsigned decimal integer")
    return int(token)


def _image(
    format_id: str,
    payload_kind: str,
    byte_size: int,
    height: int,
    width: int,
    channels: int,
    dtype: str,
    **metadata: MetadataValue,
) -> Inspection:
    if height < 1 or width < 1:
        raise ValueError("zero-dimension image")
    axis_cap = {
        "png": 200_000,
        "tga": 65_535,
        "hdr": 1 << 24,
        "exr": 1 << 20,
        "netpbm": 1_000_000_000,
        "flo": 1_000_000_000,
    }.get(format_id)
    if axis_cap is not None and (height > axis_cap or width > axis_cap):
        raise ValueError(f"{format_id}: image dimensions exceed the supported limit")
    if (
        format_id in {"png", "jpeg", "bmp", "tga", "hdr", "exr", "webp"}
        and height * width > _IMAGE_PIXEL_CAP
    ):
        raise ValueError(f"{format_id}: image dimensions exceed the supported limit")
    shape = (height, width) if channels == 1 else (height, width, channels)
    return Inspection(
        format_id,
        payload_kind,
        byte_size,
        shape=shape,
        dtype=dtype,
        channels=channels,
        metadata=metadata,
    )


def _compiled_buffer_inspect(path: Path, function):
    with path.open("rb") as stream:
        try:
            mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        except (OSError, ValueError):
            stream.seek(0)
            return function(stream.read())
        with mapped:
            return function(mapped)
