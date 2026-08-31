"""Metadata-only inspection for array, tensor, depth, and flow formats."""

from __future__ import annotations

import math
import struct
import zipfile
from pathlib import Path
from typing import BinaryIO

from sceneio import _core
from sceneio.io._inspectors.common import (
    _HEADER_LIMIT,
    _compiled_buffer_inspect,
    _exact,
    _image,
)
from sceneio.io._inspectors.model import ArrayInspection, Inspection


def inspect_pfm(path: Path, payload_kind: str) -> Inspection:
    height, width, channels, little_endian = _compiled_buffer_inspect(
        path, _core._inspect_pfm
    )
    return _image(
        "pfm",
        payload_kind,
        path.stat().st_size,
        height,
        width,
        channels,
        "float32",
        byte_order="little" if little_endian else "big",
    )


def npy_header(stream: BinaryIO) -> tuple[tuple[int, ...], str, bool]:
    magic = _exact(stream, 6, "NPY magic")
    if magic != b"\x93NUMPY":
        raise ValueError("npy: bad magic")
    version = _exact(stream, 2, "NPY version")
    major, minor = version
    if major == 1:
        length_bytes = _exact(stream, 2, "NPY header length")
        header_size = struct.unpack("<H", length_bytes)[0]
    elif major in {2, 3}:
        length_bytes = _exact(stream, 4, "NPY header length")
        header_size = struct.unpack("<I", length_bytes)[0]
    else:
        raise ValueError(f"npy: unsupported format version {major}.{minor}")
    if header_size > _HEADER_LIMIT:
        raise ValueError("npy: header exceeds 1 MiB")
    header = _exact(stream, header_size, "NPY header")
    shape, dtype, fortran = _core._inspect_npy(
        magic + version + length_bytes + header
    )
    return tuple(shape), dtype, fortran


def inspect_npy(path: Path, payload_kind: str) -> Inspection:
    shape, dtype, fortran = _compiled_buffer_inspect(path, _core._inspect_npy)
    shape = tuple(shape)
    count = math.prod(shape)
    return Inspection(
        "npy",
        payload_kind,
        path.stat().st_size,
        shape=shape,
        dtype=dtype,
        count=count,
        metadata={"fortran_order": fortran},
    )


def inspect_npz(path: Path, payload_kind: str) -> Inspection:
    arrays = []
    with path.open("rb") as raw, zipfile.ZipFile(path) as archive:
        seen = set()
        for member in archive.infolist():
            raw.seek(member.header_offset)
            local = _exact(raw, 30, "NPZ local member header")
            if local[:4] != b"PK\x03\x04":
                raise ValueError("npz: malformed local member header")
            flags, method = struct.unpack_from("<HH", local, 6)
            name_size = struct.unpack_from("<H", local, 26)[0]
            raw_name = _exact(raw, name_size, "NPZ member filename")
            encoding = "utf-8" if member.flag_bits & 0x800 else "cp437"
            central_name = member.filename.encode(encoding)
            if raw_name != central_name:
                raise ValueError(
                    "npz: local and central member filenames disagree"
                )
            if flags != member.flag_bits:
                raise ValueError(
                    "npz: local and central member metadata disagree"
                )
            if method != member.compress_type:
                raise ValueError(
                    "npz: local and central member metadata disagree"
                )
            if member.is_dir():
                continue
            if b"\0" in raw_name:
                raise ValueError("npz: member filename contains NUL")
            try:
                filename = raw_name.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(
                    "npz: member filename is not valid UTF-8"
                ) from None
            if method not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError(
                    "npz: only stored and deflate members are supported"
                )
            if flags & 1:
                raise ValueError("npz: encrypted members are not supported")
            if filename.endswith("/"):
                continue
            name = filename.removesuffix(".npy")
            if name in seen:
                raise ValueError(f"npz: duplicate tensor name {name!r}")
            seen.add(name)
            with archive.open(member) as stream:
                shape, dtype, _ = npy_header(stream)
            arrays.append(ArrayInspection(name, shape, dtype))
    return Inspection(
        "npz",
        payload_kind,
        path.stat().st_size,
        count=len(arrays),
        arrays=tuple(arrays),
    )


def inspect_safetensors(path: Path, payload_kind: str) -> Inspection:
    arrays_raw, attrs = _compiled_buffer_inspect(
        path, _core._inspect_safetensors
    )
    arrays = tuple(
        ArrayInspection(name, tuple(shape), dtype)
        for name, shape, dtype in arrays_raw
    )
    return Inspection(
        "safetensors",
        payload_kind,
        path.stat().st_size,
        count=len(arrays),
        arrays=arrays,
        metadata={"metadata_keys": tuple(attrs)},
    )


def inspect_flo(path: Path, payload_kind: str) -> Inspection:
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        header = _exact(stream, 12, "FLO header")
    if header[:4] != b"PIEH":
        raise ValueError("flo: bad magic")
    width, height = struct.unpack_from("<ii", header, 4)
    expected = 12 + width * height * 2 * 4
    if width < 1 or height < 1 or expected > file_size:
        raise ValueError("flo: invalid dimensions or payload size")
    return _image(
        "flo",
        payload_kind,
        file_size,
        height,
        width,
        2,
        "float32",
        component_order="uv",
        u_axis="right",
        v_axis="down",
        row_order="top_to_bottom",
        unit="pixels",
        invalid_policy="component_abs_gt_1e9",
    )


def inspect_dmb(path: Path, payload_kind: str) -> Inspection:
    height, width, channels, image_type = _compiled_buffer_inspect(
        path, _core._inspect_dmb
    )
    return Inspection(
        "dmb",
        payload_kind,
        path.stat().st_size,
        shape=(height, width),
        dtype="float32",
        count=height * width,
        channels=channels,
        metadata={
            "channels": channels,
            "image_type": image_type,
            "unit": "unknown",
            "scale_to_meters": 0.0,
            "invalid_policy": "zero",
        },
    )
