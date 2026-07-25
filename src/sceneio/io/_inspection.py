"""Metadata-only inspection for SceneIO's built-in file formats.

The parsers in this module stop at container headers whenever the format has
one. Headerless text formats are streamed line by line, and JSON scene formats
parse only their metadata document (they do not construct compiled records or
pixel/point arrays).
"""

from __future__ import annotations

import binascii
import gzip
import math
import mmap
import re
import struct
import zipfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO

import numpy as np

from sceneio import _core
from sceneio.io._pcd import parse_pcd_header, validate_point_pcd_header
from sceneio.io._ply import (
    parse_ply_header,
    validate_compressed_ply_header,
    validate_mesh_ply_header,
    validate_point_ply_header,
)

MetadataValue = (
    str
    | int
    | float
    | bool
    | tuple[int, ...]
    | tuple[float, ...]
    | tuple[str, ...]
)
_HEADER_LIMIT = 1024 * 1024
_IMAGE_PIXEL_CAP = 250_000_000


@dataclass(frozen=True)
class ArrayInspection:
    """The name, shape, and dtype of one array in a multi-array container."""

    name: str
    shape: tuple[int, ...]
    dtype: str


@dataclass(frozen=True)
class Inspection:
    """Metadata available without decoding a format's bulk payload.

    ``shape`` describes the primary decoded array when a format has one.
    ``count`` is the primary repeated-record count for point, Gaussian, pose,
    reconstruction, and tensor-container formats. Image formats use ``shape``
    and ``channels`` instead. Format-specific scalar metadata is exposed through
    the read-only ``metadata`` mapping.
    """

    format: str
    datatype: str
    byte_size: int
    shape: tuple[int, ...] | None = None
    dtype: str | None = None
    count: int | None = None
    channels: int | None = None
    arrays: tuple[ArrayInspection, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.shape is not None:
            object.__setattr__(self, "shape", tuple(self.shape))
        object.__setattr__(self, "arrays", tuple(self.arrays))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def inspect_path(path: str | Path, format_id: str, datatype: str) -> Inspection:
    """Inspect one built-in format without constructing its decoded record."""

    p = Path(path)
    if format_id == "pfm":
        return _inspect_pfm(p, datatype)
    if format_id == "colmap_sparse":
        return _inspect_colmap_binary(p, datatype)
    if format_id == "gaussian_ply":
        return _inspect_gaussian_ply(p, datatype)
    if format_id == "compressed_ply":
        return _inspect_compressed_ply(p, datatype)
    if format_id == "sog":
        return _inspect_sog(p, datatype)
    if format_id == "ksplat":
        return _inspect_ksplat(p, datatype)
    if format_id == "ply":
        return _inspect_ply(p, datatype)
    if format_id == "ply_mesh":
        return _inspect_ply_mesh(p, datatype)
    if format_id == "pcd":
        return _inspect_pcd(p, datatype)
    if format_id == "spz":
        return _inspect_spz(p, datatype)
    if format_id == "transforms_json":
        return _inspect_transforms(p, datatype)
    if format_id in {"tum", "kitti"}:
        return _inspect_pose_text(p, format_id, datatype)
    if format_id == "euroc_state":
        return _inspect_euroc_state(p, datatype)
    if format_id in {
        "opencv_yaml",
        "opencv_xml",
        "ros_camera_info",
        "kalibr",
    }:
        return _inspect_camera_rig(p, format_id, datatype)
    if format_id == "g2o":
        return _inspect_g2o(p, datatype)
    if format_id == "colmap_db":
        return _inspect_colmap_db(p, datatype)
    if format_id == "npy":
        return _inspect_npy(p, datatype)
    if format_id == "npz":
        return _inspect_npz(p, datatype)
    if format_id == "safetensors":
        return _inspect_safetensors(p, datatype)
    if format_id == "netpbm":
        return _inspect_netpbm(p, datatype)
    if format_id == "png":
        return _inspect_png(p, datatype)
    if format_id == "jpeg":
        return _inspect_jpeg(p, datatype)
    if format_id == "bmp":
        return _inspect_bmp(p, datatype)
    if format_id == "tga":
        return _inspect_tga(p, datatype)
    if format_id == "hdr":
        return _inspect_hdr(p, datatype)
    if format_id == "exr":
        return _inspect_exr(p, datatype)
    if format_id == "webp":
        return _inspect_webp(p, datatype)
    if format_id == "colmap_sparse_txt":
        return _inspect_colmap_text(p, datatype)
    if format_id == "xyz":
        return _inspect_xyz(p, datatype)
    if format_id == "pts":
        return _inspect_pts(p, datatype)
    if format_id == "las":
        return _inspect_las(p, datatype)
    if format_id == "flo":
        return _inspect_flo(p, datatype)
    if format_id == "dmb":
        return _inspect_dmb(p, datatype)
    if format_id == "bundler":
        return _inspect_bundler(p, datatype)
    if format_id == "bal":
        return _inspect_bal(p, datatype)
    if format_id == "nvm":
        return _inspect_nvm(p, datatype)
    if format_id == "openmvg":
        return _inspect_openmvg(p, datatype)
    if format_id == "splat":
        return _inspect_splat(p, datatype)
    raise ValueError(f"format {format_id!r} does not provide metadata inspection")


def _size(path: Path) -> int:
    return path.stat().st_size


def _inspect_colmap_db(path: Path, datatype: str) -> Inspection:
    """Inspect SQL metadata without fetching any feature/match BLOB."""

    values = _core.inspect_colmap_db(str(path))
    arrays = []
    for image_id, keypoint_count, keypoint_dim, descriptor_count, descriptor_dim in zip(
        values["image_ids"],
        values["keypoint_counts"],
        values["keypoint_dimensions"],
        values["descriptor_counts"],
        values["image_descriptor_dimensions"],
        strict=True,
    ):
        if keypoint_count >= 0:
            arrays.append(
                ArrayInspection(
                    f"{image_id}/keypoints",
                    (keypoint_count, keypoint_dim),
                    "float32",
                )
            )
        if descriptor_count >= 0:
            arrays.append(
                ArrayInspection(
                    f"{image_id}/descriptors",
                    (descriptor_count, descriptor_dim),
                    "uint8",
                )
            )
    return Inspection(
        format="colmap_db",
        datatype=datatype,
        byte_size=_size(path),
        shape=(values["num_images"],),
        count=values["num_images"],
        arrays=tuple(arrays),
        metadata={
            "user_version": values["user_version"],
            "sqlite_version": values["sqlite_version"],
            "num_cameras": values["num_cameras"],
            "num_images": values["num_images"],
            "num_keypoint_rows": values["num_keypoint_rows"],
            "num_descriptor_rows": values["num_descriptor_rows"],
            "num_match_pairs": values["num_match_pairs"],
            "num_verified_pairs": values["num_verified_pairs"],
            "num_matches": values["num_matches"],
            "num_verified_matches": values["num_verified_matches"],
            "descriptor_dimensions": tuple(values["descriptor_dimensions"]),
            "image_ids": tuple(values["image_ids"]),
            "image_names": tuple(values["image_names"]),
        },
    )


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.iterdir() if item.is_file())


def _compiled_buffer_inspect(path: Path, function):
    with path.open("rb") as stream:
        try:
            mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        except (OSError, ValueError):
            stream.seek(0)
            return function(stream.read())
        with mapped:
            return function(mapped)


def _exact(stream: BinaryIO, length: int, what: str) -> bytes:
    data = stream.read(length)
    if len(data) != length:
        raise ValueError(f"truncated {what}")
    return data


def _validate_classic_zip_extent(path: Path, format_name: str) -> None:
    size = _size(path)
    if size < 22:
        raise ValueError(f"{format_name}: malformed or empty ZIP archive")
    with path.open("rb") as stream:
        if _exact(stream, 4, f"{format_name} ZIP signature") != b"PK\x03\x04":
            raise ValueError(f"{format_name}: malformed or empty ZIP archive")
        tail_size = min(size, 22 + 65535)
        stream.seek(size - tail_size)
        tail = stream.read(tail_size)
    tail_base = size - tail_size
    eocd = None
    for offset in range(len(tail) - 22, -1, -1):
        if tail[offset : offset + 4] != b"PK\x05\x06":
            continue
        comment_size = struct.unpack_from("<H", tail, offset + 20)[0]
        if tail_base + offset + 22 + comment_size == size:
            eocd = tail_base + offset
            values = struct.unpack_from("<HHHHII", tail, offset + 4)
            break
    if eocd is None:
        raise ValueError(
            f"{format_name}: ZIP end record is missing or has trailing bytes"
        )
    disk, central_disk, disk_entries, entries, directory_size, directory_offset = (
        values
    )
    if disk != 0 or central_disk != 0:
        raise ValueError(f"{format_name}: multi-disk ZIP archives are unsupported")
    if (
        disk_entries == 0xFFFF
        or entries == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        raise ValueError(f"{format_name}: ZIP64 archives are unsupported")
    if (
        disk_entries != entries
        or directory_offset + directory_size != eocd
    ):
        raise ValueError(
            f"{format_name}: inconsistent ZIP central-directory extent"
        )


def _unsigned_decimal(token: bytes, what: str) -> int:
    if not token or not token.isdigit():
        raise ValueError(f"{what}: expected an unsigned decimal integer")
    return int(token)


def _image(
    format_id: str,
    datatype: str,
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
        datatype,
        byte_size,
        shape=shape,
        dtype=dtype,
        channels=channels,
        metadata=metadata,
    )


def _binary_tokens(
    stream: BinaryIO,
    *,
    allow_comments: bool = True,
    extended_whitespace: bool = False,
) -> Iterator[bytes]:
    token = bytearray()
    comment = False
    whitespace = b" \t\r\n\v\f" if extended_whitespace else b" \t\r\n"
    while chunk := stream.read(65536):
        for value in chunk:
            if allow_comments and comment:
                if value in (10, 13):
                    comment = False
                continue
            if allow_comments and value == 35:  # Netpbm comments may follow a number
                if token:
                    yield bytes(token)
                    token.clear()
                comment = True
            elif value in whitespace:
                if token:
                    yield bytes(token)
                    token.clear()
            else:
                token.append(value)
                if len(token) > _HEADER_LIMIT:
                    raise ValueError("metadata token exceeds 1 MiB")
    if token:
        yield bytes(token)


def _next_tokens(
    path: Path,
    count: int,
    *,
    allow_comments: bool = True,
    extended_whitespace: bool = False,
) -> list[bytes]:
    with path.open("rb") as stream:
        tokens = _binary_tokens(
            stream,
            allow_comments=allow_comments,
            extended_whitespace=extended_whitespace,
        )
        result = []
        for _ in range(count):
            try:
                result.append(next(tokens))
            except StopIteration:
                raise ValueError("truncated header") from None
        return result


def _iter_data_lines(path: Path):
    with path.open("rb") as stream:
        while line := stream.readline(_HEADER_LIMIT + 2):
            content_size = len(line) - int(line.endswith(b"\n"))
            if content_size > _HEADER_LIMIT:
                raise ValueError("metadata line exceeds 1 MiB")
            stripped = line.strip()
            if stripped and not stripped.startswith(b"#"):
                yield stripped


def _inspect_pfm(path: Path, datatype: str) -> Inspection:
    height, width, channels, little_endian = _compiled_buffer_inspect(
        path, _core._inspect_pfm
    )
    return _image(
        "pfm",
        datatype,
        _size(path),
        height,
        width,
        channels,
        "float32",
        byte_order="little" if little_endian else "big",
    )


def _npy_header(stream: BinaryIO) -> tuple[tuple[int, ...], str, bool]:
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


def _inspect_npy(path: Path, datatype: str) -> Inspection:
    shape, dtype, fortran = _compiled_buffer_inspect(path, _core._inspect_npy)
    shape = tuple(shape)
    count = math.prod(shape)
    return Inspection(
        "npy",
        datatype,
        _size(path),
        shape=shape,
        dtype=dtype,
        count=count,
        metadata={"fortran_order": fortran},
    )


def _inspect_npz(path: Path, datatype: str) -> Inspection:
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
                raise ValueError("npz: member filename is not valid UTF-8") from None
            if method not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError("npz: only stored and deflate members are supported")
            if flags & 1:
                raise ValueError("npz: encrypted members are not supported")
            if filename.endswith("/"):
                continue
            name = filename.removesuffix(".npy")
            if name in seen:
                raise ValueError(f"npz: duplicate tensor name {name!r}")
            seen.add(name)
            with archive.open(member) as stream:
                shape, dtype, _ = _npy_header(stream)
            arrays.append(ArrayInspection(name, shape, dtype))
    return Inspection(
        "npz",
        datatype,
        _size(path),
        count=len(arrays),
        arrays=tuple(arrays),
    )


def _inspect_safetensors(path: Path, datatype: str) -> Inspection:
    arrays_raw, attrs = _compiled_buffer_inspect(
        path, _core._inspect_safetensors
    )
    arrays = tuple(
        ArrayInspection(name, tuple(shape), dtype)
        for name, shape, dtype in arrays_raw
    )
    return Inspection(
        "safetensors",
        datatype,
        _size(path),
        count=len(arrays),
        arrays=arrays,
        metadata={"metadata_keys": tuple(attrs)},
    )


def _inspect_netpbm(path: Path, datatype: str) -> Inspection:
    magic, width_raw, height_raw, maxval_raw = _next_tokens(
        path, 4, extended_whitespace=True
    )
    if magic not in {b"P2", b"P3", b"P5", b"P6"}:
        raise ValueError("netpbm: bad magic")
    width = _unsigned_decimal(width_raw, "netpbm width")
    height = _unsigned_decimal(height_raw, "netpbm height")
    maxval = _unsigned_decimal(maxval_raw, "netpbm maxval")
    if width < 1 or height < 1 or not 1 <= maxval <= 65535:
        raise ValueError("netpbm: invalid dimensions or maxval")
    channels = 1 if magic in {b"P2", b"P5"} else 3
    return _image(
        "netpbm",
        datatype,
        _size(path),
        height,
        width,
        channels,
        "uint8" if maxval <= 255 else "uint16",
        ascii=magic in {b"P2", b"P3"},
        maxval=maxval,
    )


def _inspect_png(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    with path.open("rb") as stream:
        if _exact(stream, 8, "PNG signature") != b"\x89PNG\r\n\x1a\n":
            raise ValueError("png: bad signature")
        length, kind = struct.unpack(">I4s", _exact(stream, 8, "PNG IHDR chunk"))
        if length != 13 or kind != b"IHDR":
            raise ValueError("png: missing IHDR")
        ihdr = _exact(stream, 13, "PNG IHDR")
        width, height, bitdepth, color_type, compression, filtering, interlace = (
            struct.unpack(">IIBBBBB", ihdr)
        )
        ihdr_crc = struct.unpack(">I", _exact(stream, 4, "PNG IHDR CRC"))[0]
        if binascii.crc32(b"IHDR" + ihdr) != ihdr_crc:
            raise ValueError("png: invalid IHDR CRC")
        if compression != 0 or filtering != 0 or interlace not in {0, 1}:
            raise ValueError("png: unsupported IHDR")
        if color_type == 3 and bitdepth not in {1, 2, 4, 8}:
            raise ValueError("png: unsupported palette bit depth")
        palette_alpha = False
        has_trns = False
        palette_entries = None
        saw_idat = False
        while True:
            length_raw = stream.read(4)
            if not length_raw:
                break
            length = struct.unpack(">I", length_raw)[0]
            kind = _exact(stream, 4, "PNG chunk type")
            if length > file_size - stream.tell() - 4:
                raise ValueError("png: chunk runs past end of file")
            metadata_payload = None
            if kind == b"PLTE":
                if palette_entries is not None or length == 0 or length > 768 or length % 3:
                    raise ValueError("png: invalid PLTE chunk")
                palette_entries = length // 3
                if color_type == 3 and palette_entries > 2**bitdepth:
                    raise ValueError("png: palette has too many entries")
                metadata_payload = _exact(stream, length, "PNG PLTE")
            elif kind == b"tRNS":
                if has_trns:
                    raise ValueError("png: duplicate tRNS chunk")
                has_trns = True
                if color_type == 3:
                    if palette_entries is None or length > palette_entries:
                        raise ValueError("png: invalid palette tRNS chunk")
                    metadata_payload = _exact(stream, length, "PNG tRNS")
                    palette_alpha = any(
                        value != 255
                        for value in metadata_payload
                    )
                else:
                    raise ValueError("png: non-palette tRNS is unsupported")
            elif kind == b"IEND":
                stream.seek(length, 1)
            elif kind != b"IDAT" and not kind[0] & 0x20:
                raise ValueError(
                    f"png: unsupported critical chunk {kind!r}"
                )
            else:
                stream.seek(length, 1)
            chunk_crc = struct.unpack(
                ">I", _exact(stream, 4, "PNG chunk CRC")
            )[0]
            if (
                metadata_payload is not None
                and binascii.crc32(kind + metadata_payload) != chunk_crc
            ):
                raise ValueError(f"png: invalid {kind.decode()} CRC")
            if kind == b"IDAT":
                saw_idat = True
                break
            if kind == b"IEND":
                break
        if not saw_idat:
            raise ValueError("png: missing IDAT")
        if color_type == 3 and palette_entries is None:
            raise ValueError("png: palette image is missing PLTE")
    if color_type == 0:
        if bitdepth not in {8, 16} or has_trns:
            raise ValueError("png: unsupported grayscale mode")
        channels = 1
    elif color_type == 2:
        if bitdepth not in {8, 16} or has_trns:
            raise ValueError("png: unsupported RGB mode")
        channels = 3
    elif color_type == 3:
        channels = 4 if palette_alpha else 3
        bitdepth = 8
    elif color_type == 6:
        if bitdepth not in {8, 16} or has_trns:
            raise ValueError("png: unsupported RGBA bit depth")
        channels = 4
    else:
        raise ValueError("png: unsupported color type")
    return _image(
        "png",
        datatype,
        file_size,
        height,
        width,
        channels,
        "uint16" if bitdepth == 16 else "uint8",
        interlaced=bool(interlace),
    )


_JPEG_SOF = {0xC0, 0xC1, 0xC2}
_JPEG_ALL_SOF = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _inspect_jpeg(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    with path.open("rb") as stream:
        if _exact(stream, 2, "JPEG SOI") != b"\xff\xd8":
            raise ValueError("jpeg: bad signature")
        image_info = None
        while True:
            value = _exact(stream, 1, "JPEG marker")[0]
            while value != 0xFF:
                value = _exact(stream, 1, "JPEG marker")[0]
            while value == 0xFF:
                value = _exact(stream, 1, "JPEG marker")[0]
            marker = value
            if marker == 0xD9:
                raise ValueError("jpeg: reached EOI before a scan")
            if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            length = struct.unpack(">H", _exact(stream, 2, "JPEG segment length"))[0]
            if length < 2:
                raise ValueError("jpeg: invalid segment length")
            if marker in _JPEG_SOF:
                if image_info is not None:
                    raise ValueError("jpeg: duplicate SOF marker")
                body = _exact(stream, length - 2, "JPEG SOF")
                if len(body) < 6:
                    raise ValueError("jpeg: truncated SOF")
                precision, height, width, components = struct.unpack(">BHHB", body[:6])
                if precision != 8 or components not in {1, 3, 4}:
                    raise ValueError("jpeg: unsupported precision or component count")
                if len(body) != 6 + 3 * components:
                    raise ValueError("jpeg: SOF length does not match component count")
                channels = 1 if components == 1 else 3
                image_info = (
                    height,
                    width,
                    channels,
                    precision,
                    marker == 0xC2,
                )
                continue
            if marker in _JPEG_ALL_SOF:
                raise ValueError(
                    f"jpeg: unsupported SOF marker 0x{marker:02x}"
                )
            stream.seek(length - 2, 1)
            if marker == 0xDA:
                if stream.tell() > file_size:
                    raise ValueError("jpeg: SOS segment runs past end of file")
                if image_info is None:
                    raise ValueError("jpeg: scan appears before SOF")
                height, width, channels, precision, progressive = image_info
                return _image(
                    "jpeg",
                    datatype,
                    file_size,
                    height,
                    width,
                    channels,
                    "uint8",
                    precision=precision,
                    progressive=progressive,
                )


def _inspect_bmp(path: Path, datatype: str) -> Inspection:
    (
        height,
        width,
        channels,
        bits_per_pixel,
        compression,
        palette,
        top_down,
    ) = _compiled_buffer_inspect(path, _core._inspect_bmp)
    return _image(
        "bmp",
        datatype,
        _size(path),
        height,
        width,
        channels,
        "uint8",
        bits_per_pixel=bits_per_pixel,
        compression={0: "BI_RGB", 3: "BI_BITFIELDS"}[compression],
        palette=palette,
        top_down=top_down,
    )


def _inspect_tga(path: Path, datatype: str) -> Inspection:
    (
        height,
        width,
        channels,
        bits_per_pixel,
        rle,
        palette,
        top_origin,
    ) = _compiled_buffer_inspect(path, _core._inspect_tga)
    return _image(
        "tga",
        datatype,
        _size(path),
        height,
        width,
        channels,
        "uint8",
        bits_per_pixel=bits_per_pixel,
        rle=rle,
        palette=palette,
        origin="top_left" if top_origin else "bottom_left",
    )


_HDR_RESOLUTION = re.compile(rb"^-Y\s+(\d+)\s+\+X\s+(\d+)\s*$")


def _inspect_hdr(path: Path, datatype: str) -> Inspection:
    with path.open("rb") as stream:
        signature = stream.readline(_HEADER_LIMIT + 1).rstrip(b"\r\n")
        if signature not in {b"#?RADIANCE", b"#?RGBE"}:
            raise ValueError("hdr: bad signature")
        format_seen = False
        while line := stream.readline(_HEADER_LIMIT + 1):
            if len(line) > _HEADER_LIMIT:
                raise ValueError("hdr: metadata line exceeds 1 MiB")
            stripped = line.strip()
            if not stripped:
                break
            if stripped.startswith(b"FORMAT="):
                format_seen |= stripped == b"FORMAT=32-bit_rle_rgbe"
        resolution = stream.readline(_HEADER_LIMIT + 1)
        if len(resolution) > _HEADER_LIMIT:
            raise ValueError("hdr: resolution line exceeds 1 MiB")
        match = _HDR_RESOLUTION.match(resolution.strip())
        if not match:
            raise ValueError("hdr: missing or unsupported resolution line")
        if not format_seen:
            raise ValueError("hdr: unsupported or missing FORMAT")
        height, width = (int(value) for value in match.groups())
        return _image(
            "hdr", datatype, _size(path), height, width, 3, "float32"
        )


def _cstr(stream: BinaryIO, what: str, limit: int = 4096) -> bytes:
    result = bytearray()
    while len(result) <= limit:
        value = stream.read(1)
        if not value:
            raise ValueError(f"truncated {what}")
        if value == b"\0":
            return bytes(result)
        result += value
    raise ValueError(f"{what} is too long")


def _inspect_exr(path: Path, datatype: str) -> Inspection:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        file_size = stream.tell()
        stream.seek(0)
        if _exact(stream, 4, "EXR magic") != b"\x76\x2f\x31\x01":
            raise ValueError("exr: bad signature")
        version = struct.unpack("<I", _exact(stream, 4, "EXR version"))[0]
        if (version & 0xFF) != 2:
            raise ValueError("exr: unsupported version")
        if version & (0x200 | 0x800 | 0x1000):
            raise ValueError("exr: tiled, deep, and multipart images are unsupported")
        data_window = None
        channel_names = []
        channel_name_encodings = []
        channel_types = []
        channels_seen = False
        while name := _cstr(stream, "EXR attribute name"):
            attr_type = _cstr(stream, "EXR attribute type")
            attr_size = struct.unpack("<I", _exact(stream, 4, "EXR attribute size"))[0]
            if name == b"dataWindow" and attr_type == b"box2i" and attr_size == 16:
                value = _exact(stream, attr_size, "EXR dataWindow attribute")
                data_window = struct.unpack("<4i", value)
            elif name == b"channels" and attr_type == b"chlist":
                if channels_seen:
                    raise ValueError("exr: duplicate channels attribute")
                channels_seen = True
                if attr_size > _HEADER_LIMIT:
                    raise ValueError("exr: channel list exceeds 1 MiB")
                value = _exact(stream, attr_size, "EXR channels attribute")
                offset = 0
                while offset < len(value) and value[offset] != 0:
                    end = value.find(b"\0", offset)
                    if end < 0 or end + 17 > len(value):
                        raise ValueError("exr: malformed channel list")
                    raw_name = value[offset:end]
                    try:
                        channel_name = raw_name.decode("utf-8")
                    except UnicodeDecodeError:
                        channel_name = raw_name.decode("latin1")
                        channel_name_encoding = "latin1"
                    else:
                        channel_name_encoding = "utf8"
                    channel_names.append(channel_name)
                    channel_name_encodings.append(channel_name_encoding)
                    channel_types.append(struct.unpack_from("<i", value, end + 1)[0])
                    if len(channel_names) > 4:
                        raise ValueError("exr: unsupported channel set")
                    offset = end + 17
                if offset >= len(value) or value[offset] != 0 or offset + 1 != len(value):
                    raise ValueError("exr: malformed channel list terminator")
            else:
                remaining = file_size - stream.tell()
                if attr_size > remaining:
                    raise ValueError(f"truncated EXR {name!r} attribute")
                stream.seek(attr_size, 1)
        if data_window is None or not channel_names:
            raise ValueError("exr: missing dataWindow or channels")
    min_x, min_y, max_x, max_y = data_window
    width, height = max_x - min_x + 1, max_y - min_y + 1
    if any(pixel_type not in {1, 2} for pixel_type in channel_types):
        raise ValueError("exr: only HALF and FLOAT channels are supported")
    names = set(channel_names)
    if len(channel_names) == 1:
        channels = 1
    elif len(channel_names) == 3 and names == {"R", "G", "B"}:
        channels = 3
    elif len(channel_names) == 4 and names == {"R", "G", "B", "A"}:
        channels = 4
    else:
        raise ValueError("exr: unsupported channel set")
    return _image(
        "exr",
        datatype,
        file_size,
        height,
        width,
        channels,
        "float32",
        channel_names=tuple(channel_names),
        channel_name_encodings=tuple(channel_name_encodings),
        channel_dtypes=tuple(
            "float16" if pixel_type == 1 else "float32"
            for pixel_type in channel_types
        ),
    )


def _inspect_webp(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    with path.open("rb") as stream:
        header = _exact(stream, 12, "WebP RIFF header")
        if header[:4] != b"RIFF" or header[8:] != b"WEBP":
            raise ValueError("webp: bad RIFF/WEBP signature")
        riff_size = struct.unpack_from("<I", header, 4)[0] + 8
        if riff_size < 12 or riff_size > file_size:
            raise ValueError("webp: truncated RIFF")
        alpha_chunk = False
        canvas = None
        bitstream = None
        while stream.tell() < riff_size:
            if riff_size - stream.tell() < 8:
                raise ValueError("webp: truncated chunk header")
            kind, length = struct.unpack("<4sI", _exact(stream, 8, "WebP chunk header"))
            padded = length + (length & 1)
            if padded > riff_size - stream.tell():
                raise ValueError("webp: chunk runs past RIFF boundary")
            prefix = _exact(stream, min(length, 16), f"WebP {kind!r} chunk")
            if length > len(prefix):
                stream.seek(length - len(prefix), 1)
            if length & 1:
                stream.seek(1, 1)
            if kind == b"ALPH":
                alpha_chunk = True
                continue
            if kind == b"VP8X":
                if len(prefix) < 10:
                    raise ValueError("webp: truncated VP8X")
                flags = prefix[0]
                if flags & 0x02:
                    raise ValueError("webp: animated WebP is unsupported")
                width = 1 + int.from_bytes(prefix[4:7], "little")
                height = 1 + int.from_bytes(prefix[7:10], "little")
                if canvas is None:
                    canvas = (height, width)
                continue
            if kind == b"VP8L":
                if len(prefix) < 5 or prefix[0] != 0x2F:
                    raise ValueError("webp: malformed VP8L header")
                if prefix[4] & 0xE0:
                    raise ValueError("webp: unsupported VP8L version")
                width = 1 + prefix[1] + ((prefix[2] & 0x3F) << 8)
                height = 1 + (prefix[2] >> 6) + (prefix[3] << 2) + ((prefix[4] & 0xF) << 10)
                if bitstream is None:
                    bitstream = (height, width, bool(prefix[4] & 0x10))
                continue
            if kind == b"VP8 ":
                if len(prefix) < 10 or prefix[3:6] != b"\x9d\x01\x2a":
                    raise ValueError("webp: malformed VP8 header")
                width = int.from_bytes(prefix[6:8], "little") & 0x3FFF
                height = int.from_bytes(prefix[8:10], "little") & 0x3FFF
                if bitstream is None:
                    bitstream = (height, width, alpha_chunk)
        if bitstream is None:
            raise ValueError("webp: missing image bitstream")
        height, width, bitstream_alpha = bitstream
        if canvas is not None:
            if canvas != (height, width):
                raise ValueError("webp: VP8X canvas does not match bitstream")
            height, width = canvas
        return _image(
            "webp",
            datatype,
            file_size,
            height,
            width,
            4 if bitstream_alpha else 3,
            "uint8",
        )


def _inspect_flo(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    with path.open("rb") as stream:
        header = _exact(stream, 12, "FLO header")
    if header[:4] != b"PIEH":
        raise ValueError("flo: bad magic")
    width, height = struct.unpack_from("<ii", header, 4)
    expected = 12 + width * height * 2 * 4
    if width < 1 or height < 1 or expected > file_size:
        raise ValueError("flo: invalid dimensions or payload size")
    return _image("flo", datatype, file_size, height, width, 2, "float32")


def _inspect_dmb(path: Path, datatype: str) -> Inspection:
    height, width, channels, image_type = _compiled_buffer_inspect(
        path, _core._inspect_dmb
    )
    return Inspection(
        "dmb",
        datatype,
        _size(path),
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


def _inspect_las(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    with path.open("rb") as stream:
        header = _exact(stream, min(255, file_size), "LAS public header")
    if len(header) < 227 or header[:4] != b"LASF":
        raise ValueError("las: bad or truncated public header")
    major, minor = header[24], header[25]
    point_format = header[104]
    if point_format & 0x80:
        raise ValueError("las: compressed LAZ is unsupported")
    format_id = point_format & 0x7F
    if format_id not in {0, 1, 2, 3, 6, 7, 8}:
        raise ValueError(f"las: unsupported point format {format_id}")
    if major == 1 and minor >= 4:
        if len(header) < 255:
            raise ValueError("las: truncated LAS 1.4 header")
        count = struct.unpack_from("<Q", header, 247)[0]
    else:
        count = struct.unpack_from("<I", header, 107)[0]
    offset_to_points = struct.unpack_from("<I", header, 96)[0]
    record_length = struct.unpack_from("<H", header, 105)[0]
    rgb_offset = {2: 20, 3: 28, 7: 30, 8: 30}.get(format_id)
    minimum_length = rgb_offset + 6 if rgb_offset is not None else 14
    if record_length < minimum_length:
        raise ValueError("las: point record length is too short")
    if count > 4_000_000_000:
        raise ValueError("las: point count exceeds the supported limit")
    if (
        offset_to_points < 227
        or offset_to_points + count * record_length > file_size
    ):
        raise ValueError("las: truncated or malformed point data")
    return Inspection(
        "las",
        datatype,
        file_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={
            "point_format": format_id,
            "has_color": format_id in {2, 3, 7, 8},
            "has_intensity": True,
        },
    )


def _inspect_gaussian_ply(path: Path, datatype: str) -> Inspection:
    count = None
    required_names = {
        b"x",
        b"y",
        b"z",
        b"f_dc_0",
        b"f_dc_1",
        b"f_dc_2",
        b"opacity",
        b"scale_0",
        b"scale_1",
        b"scale_2",
        b"rot_0",
        b"rot_1",
        b"rot_2",
        b"rot_3",
    }
    seen_required = set()
    rest_indices = set()
    current_element = None
    byte_order = None
    line_limit = 4096
    with path.open("rb") as stream:
        first = stream.readline(line_limit + 1)
        if len(first) > line_limit:
            raise ValueError("PLY: header line is too long")
        if first.rstrip(b"\r\n") != b"ply":
            raise ValueError("PLY: bad magic")
        while True:
            line = stream.readline(line_limit + 1)
            if not line:
                raise ValueError("PLY: missing end_header")
            if len(line) > line_limit:
                raise ValueError("PLY: header line is too long")
            tokens = line.strip().split(maxsplit=3)
            if not tokens or tokens[0] == b"comment":
                continue
            if tokens[0] == b"format":
                if len(tokens) != 3 or tokens[2] != b"1.0" or byte_order is not None:
                    raise ValueError("PLY: malformed or duplicate format header")
                if tokens[1] == b"binary_little_endian":
                    byte_order = "little"
                elif tokens[1] == b"binary_big_endian":
                    byte_order = "big"
                else:
                    raise ValueError("PLY: unsupported format")
            elif tokens[0] == b"element":
                if len(tokens) != 3:
                    raise ValueError("PLY: malformed element header")
                current_element = tokens[1]
                if current_element == b"vertex":
                    count = _unsigned_decimal(tokens[2], "PLY vertex count")
                    if count > np.iinfo(np.uintp).max:
                        raise ValueError("PLY: malformed vertex count")
            elif tokens[0] == b"property" and current_element == b"vertex":
                if len(tokens) != 3 or tokens[1] not in {b"float", b"float32"}:
                    raise ValueError("PLY: only float32 vertex properties are supported")
                name = tokens[2]
                if name in required_names:
                    seen_required.add(name)
                elif name.startswith(b"f_rest_"):
                    suffix = name[len(b"f_rest_") :]
                    if suffix.isdigit():
                        index = int(suffix)
                        if suffix == str(index).encode() and index <= 45:
                            rest_indices.add(index)
            elif tokens[0] == b"end_header":
                if tokens != [b"end_header"]:
                    raise ValueError("PLY: malformed end_header")
                break
    if byte_order is None or count is None:
        raise ValueError("PLY: missing binary format or vertex count")
    missing = required_names - seen_required
    if missing:
        raise ValueError(f"PLY: missing Gaussian property {min(missing).decode()!r}")
    rest = 0
    while rest in rest_indices:
        rest += 1
    if rest not in {0, 9, 24, 45}:
        raise ValueError("PLY: unsupported SH property count")
    degree = {0: 0, 9: 1, 24: 2, 45: 3}[rest]
    return Inspection(
        "gaussian_ply",
        datatype,
        _size(path),
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={
            "sh_degree": degree,
            "num_rest": rest,
            "byte_order": byte_order,
        },
    )


def _inspect_compressed_ply(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    header = parse_ply_header(path)
    metadata = validate_compressed_ply_header(header, file_size)
    vertex = next(
        element for element in header.elements if element.name == b"vertex"
    )
    return Inspection(
        "compressed_ply",
        datatype,
        file_size,
        shape=(vertex.count,),
        dtype="float32",
        count=vertex.count,
        metadata=metadata,
    )


def _inspect_sog(path: Path, datatype: str) -> Inspection:
    metadata_path = path / "meta.json" if path.is_dir() else path
    if metadata_path.name == "meta.json":
        if metadata_path.stat().st_size > _HEADER_LIMIT:
            raise ValueError("sog: meta.json exceeds 1 MiB")
        with metadata_path.open("rb") as stream:
            metadata_bytes = stream.read(_HEADER_LIMIT + 1)
        if len(metadata_bytes) > _HEADER_LIMIT:
            raise ValueError("sog: meta.json exceeds 1 MiB")
        count, bands, rest, palette_count, declared = (
            _core._inspect_sog_metadata(metadata_bytes)
        )
        declared = set(declared)
        parent = metadata_path.parent
        missing = [
            name
            for name in declared
            if not (parent / name).is_file()
        ]
        if missing:
            raise ValueError(
                f"sog: missing declared layer {min(missing)!r}"
            )
        byte_size = sum((parent / name).stat().st_size for name in declared)
        packaging = "directory"
    else:
        _validate_classic_zip_extent(path, "sog")
        with path.open("rb") as raw, zipfile.ZipFile(path) as archive:
            members = {}
            for member in archive.infolist():
                raw.seek(member.header_offset)
                local = _exact(raw, 30, "SOG local member header")
                if local[:4] != b"PK\x03\x04":
                    raise ValueError("sog: malformed local ZIP member header")
                flags, method = struct.unpack_from("<HH", local, 6)
                name_size = struct.unpack_from("<H", local, 26)[0]
                raw_name = _exact(raw, name_size, "SOG member filename")
                encoding = "utf-8" if member.flag_bits & 0x800 else "cp437"
                if raw_name != member.filename.encode(encoding):
                    raise ValueError(
                        "sog: local and central ZIP filenames disagree"
                    )
                if flags != member.flag_bits or method != member.compress_type:
                    raise ValueError(
                        "sog: local and central ZIP metadata disagree"
                    )
                if member.is_dir():
                    raise ValueError("sog: directory ZIP entries are unsupported")
                if flags & 1:
                    raise ValueError("sog: encrypted ZIP members are unsupported")
                if method not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError(
                        "sog: only stored and deflated ZIP members are supported"
                    )
                try:
                    name = raw_name.decode("utf-8")
                except UnicodeDecodeError:
                    raise ValueError(
                        "sog: ZIP member filename is not valid UTF-8"
                    ) from None
                if name in members:
                    raise ValueError(f"sog: duplicate ZIP member {name!r}")
                members[name] = member
            try:
                meta_member = members["meta.json"]
            except KeyError:
                raise ValueError("sog: missing ZIP member 'meta.json'") from None
            if meta_member.file_size > _HEADER_LIMIT:
                raise ValueError("sog: meta.json exceeds 1 MiB")
            metadata_bytes = archive.read(meta_member)
            count, bands, rest, palette_count, declared = (
                _core._inspect_sog_metadata(metadata_bytes)
            )
            if set(members) != set(declared):
                raise ValueError(
                    "sog: ZIP members do not exactly match declared layers"
                )
        byte_size = _size(path)
        packaging = "zip"
    return Inspection(
        "sog",
        datatype,
        byte_size,
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={
            "version": 2,
            "sh_degree": bands,
            "num_rest": rest,
            "palette_count": palette_count,
            "packaging": packaging,
            "texture_codec": "lossless_webp",
        },
    )


def _inspect_ksplat(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    if file_size < 4096:
        raise ValueError("ksplat: truncated 4096-byte header")
    with path.open("rb") as stream:
        base = _exact(stream, 4096, "KSplat header")
        section_count = struct.unpack_from("<I", base, 4)[0]
        header_extent = 4096 + section_count * 1024
        if header_extent > file_size:
            raise ValueError("ksplat: truncated section headers")
        section_headers = _exact(
            stream,
            header_extent - 4096,
            "KSplat section headers",
        )
    (
        count,
        degree,
        compression,
        declared_sections,
        loaded_sections,
        loaded_count,
        scene_x,
        scene_y,
        scene_z,
        sh_min,
        sh_max,
    ) = _core._inspect_ksplat_metadata(
        base + section_headers,
        file_size,
    )
    return Inspection(
        "ksplat",
        datatype,
        file_size,
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={
            "version": "0.1",
            "compression_level": compression,
            "sh_degree": degree,
            "num_rest": (0, 9, 24)[degree],
            "section_count": declared_sections,
            "loaded_section_count": loaded_sections,
            "loaded_count": loaded_count,
            "scene_center": (scene_x, scene_y, scene_z),
            "sh_quantization_range": (sh_min, sh_max),
        },
    )


def _inspect_ply(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    header = parse_ply_header(path)
    metadata = validate_point_ply_header(header, file_size)
    count = header.vertex.count
    return Inspection(
        "ply",
        datatype,
        file_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata=metadata,
    )


def _inspect_ply_mesh(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    header = parse_ply_header(path)
    metadata = validate_mesh_ply_header(header, file_size)
    count = header.vertex.count
    return Inspection(
        "ply_mesh",
        datatype,
        file_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata=metadata,
    )


def _inspect_pcd(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    header = parse_pcd_header(path)
    metadata = validate_point_pcd_header(header, path)
    return Inspection(
        "pcd",
        datatype,
        file_size,
        shape=(header.points, 3),
        dtype="float32",
        count=header.points,
        metadata=metadata,
    )


def _inspect_spz(path: Path, datatype: str) -> Inspection:
    with path.open("rb") as stream:
        prefix = _exact(stream, min(32, _size(path)), "SPZ header")
    if prefix.startswith(b"\x1f\x8b"):
        with gzip.open(path, "rb") as stream:
            header = _exact(stream, 16, "legacy SPZ header")
        magic, version, count = struct.unpack_from("<III", header)
        degree = header[12]
        fractional_bits = header[13]
        if magic != 0x5053474E or version not in {1, 2, 3}:
            raise ValueError("SPZ: bad legacy header")
    else:
        if len(prefix) < 32:
            raise ValueError("SPZ: truncated v4 header")
        magic, version, count = struct.unpack_from("<III", prefix)
        degree = prefix[12]
        fractional_bits = prefix[13]
        if magic != 0x5053474E or version != 4:
            raise ValueError("SPZ: bad v4 header")
    if degree not in {0, 1, 2, 3}:
        raise ValueError("SPZ: unsupported SH degree")
    if not 1 <= fractional_bits <= 24:
        raise ValueError("SPZ: invalid fractional_bits")
    return Inspection(
        "spz",
        datatype,
        _size(path),
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={
            "version": version,
            "sh_degree": degree,
            "fractional_bits": fractional_bits,
        },
    )


def _inspect_splat(path: Path, datatype: str) -> Inspection:
    size = _size(path)
    if size % 32:
        raise ValueError("splat: size is not a multiple of 32")
    count = size // 32
    return Inspection(
        "splat",
        datatype,
        size,
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={"sh_degree": 0},
    )


def _inspect_xyz(path: Path, datatype: str) -> Inspection:
    count, columns = _core._inspect_xyz_file(path)
    return Inspection(
        "xyz",
        datatype,
        _size(path),
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={
            "columns": columns,
            "has_color": columns in {6, 7, 9},
            "has_intensity": columns in {4, 7},
            "has_normals": columns == 9,
        },
    )


def _inspect_pts(path: Path, datatype: str) -> Inspection:
    count = _compiled_buffer_inspect(path, _core._inspect_pts)
    return Inspection(
        "pts",
        datatype,
        _size(path),
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={"declared_count": count},
    )


def _inspect_pose_text(path: Path, format_id: str, datatype: str) -> Inspection:
    expected = 8 if format_id == "tum" else 12
    count = 0
    for line in _iter_data_lines(path):
        if len(line.split(maxsplit=expected)) < expected:
            raise ValueError(f"{format_id}: expected at least {expected} fields per data line")
        count += 1
    return Inspection(
        format_id,
        datatype,
        _size(path),
        shape=(count,),
        dtype="float64",
        count=count,
    )


def _inspect_euroc_state(path: Path, datatype: str) -> Inspection:
    count, first_timestamp, last_timestamp = _compiled_buffer_inspect(
        path, _core._inspect_euroc_state
    )
    metadata: dict[str, MetadataValue] = {
        "timestamp_unit": "nanoseconds",
        "quaternion_order": "wxyz",
        "quaternion_sign": "preserved",
        "pose_convention": "sensor_to_reference",
        "position_frame": "reference",
        "velocity_frame": "reference",
        "bias_frame": "sensor",
        "position_unit": "meters",
        "velocity_unit": "meters_per_second",
        "gyro_bias_unit": "radians_per_second",
        "accel_bias_unit": "meters_per_second_squared",
    }
    if count:
        metadata["first_timestamp_ns"] = first_timestamp
        metadata["last_timestamp_ns"] = last_timestamp
    return Inspection(
        "euroc_state",
        datatype,
        _size(path),
        shape=(count,),
        dtype="float64",
        count=count,
        metadata=metadata,
    )


def _inspect_camera_rig(
    path: Path, format_id: str, datatype: str
) -> Inspection:
    function = {
        "opencv_yaml": _core._inspect_opencv_yaml,
        "opencv_xml": _core._inspect_opencv_xml,
        "ros_camera_info": _core._inspect_ros_camera_info,
        "kalibr": _core._inspect_kalibr,
    }[format_id]
    count, flat_resolutions = _compiled_buffer_inspect(path, function)
    resolutions = tuple(int(value) for value in flat_resolutions)
    return Inspection(
        format_id,
        datatype,
        _size(path),
        shape=(count,),
        dtype="float64",
        count=count,
        metadata={
            "resolutions": resolutions,
            "axis_frame": "opencv",
        },
    )


def _inspect_g2o(path: Path, datatype: str) -> Inspection:
    nodes, edges, fixed = _compiled_buffer_inspect(path, _core._inspect_g2o)
    return Inspection(
        "g2o",
        datatype,
        _size(path),
        shape=(nodes,),
        dtype="float64",
        count=nodes,
        metadata={
            "num_nodes": nodes,
            "num_edges": edges,
            "num_fixed_nodes": fixed,
            "quaternion_order": "xyzw",
            "quaternion_sign": "preserved",
            "node_transform_convention": "node_to_reference",
            "edge_transform_convention": "source_inverse_times_target",
            "translation_unit": "unspecified",
            "information_variable_order": "tx_ty_tz_qx_qy_qz",
        },
    )


def _inspect_bundler(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    cameras, points = _compiled_buffer_inspect(
        path, _core._inspect_bundler
    )
    return Inspection(
        "bundler",
        datatype,
        file_size,
        shape=(cameras,),
        dtype="float64",
        count=cameras,
        metadata={
            "num_cameras": cameras,
            "num_images": cameras,
            "num_points3D": points,
        },
    )


def _inspect_bal(path: Path, datatype: str) -> Inspection:
    cameras, points, observations = _compiled_buffer_inspect(
        path, _core._inspect_bal
    )
    return Inspection(
        "bal",
        datatype,
        _size(path),
        shape=(cameras,),
        dtype="float64",
        count=cameras,
        metadata={
            "num_cameras": cameras,
            "num_images": cameras,
            "num_points3D": points,
            "num_observations": observations,
        },
    )


def _inspect_nvm(path: Path, datatype: str) -> Inspection:
    cameras, points = _compiled_buffer_inspect(path, _core._inspect_nvm)
    return Inspection(
        "nvm",
        datatype,
        _size(path),
        shape=(cameras,),
        dtype="float64",
        count=cameras,
        metadata={
            "num_cameras": cameras,
            "num_images": cameras,
            "num_points3D": points,
        },
    )


def _inspect_transforms(path: Path, datatype: str) -> Inspection:
    views, cameras = _compiled_buffer_inspect(
        path, _core._inspect_transforms_json
    )
    return Inspection(
        "transforms_json",
        datatype,
        _size(path),
        shape=(views,),
        dtype="float64",
        count=views,
        metadata={"num_views": views, "num_cameras": cameras},
    )


def _inspect_openmvg(path: Path, datatype: str) -> Inspection:
    cameras, images, points = _compiled_buffer_inspect(
        path, _core._inspect_openmvg
    )
    return Inspection(
        "openmvg",
        datatype,
        _size(path),
        shape=(images,),
        dtype="float64",
        count=images,
        metadata={
            "num_cameras": cameras,
            "num_images": images,
            "num_points3D": points,
        },
    )


def _inspect_colmap_binary(path: Path, datatype: str) -> Inspection:
    counts = {}
    for filename, key in (
        ("cameras.bin", "num_cameras"),
        ("images.bin", "num_images"),
        ("points3D.bin", "num_points3D"),
    ):
        with (path / filename).open("rb") as stream:
            counts[key] = struct.unpack("<Q", _exact(stream, 8, filename))[0]
    return Inspection(
        "colmap_sparse",
        datatype,
        _directory_size(path),
        shape=(counts["num_images"],),
        dtype="float64",
        count=counts["num_images"],
        metadata=counts,
    )


def _inspect_colmap_text(path: Path, datatype: str) -> Inspection:
    cameras, images, points = _core._inspect_colmap_txt(str(path))
    counts = {
        "num_cameras": cameras,
        "num_images": images,
        "num_points3D": points,
    }
    return Inspection(
        "colmap_sparse_txt",
        datatype,
        _directory_size(path),
        shape=(counts["num_images"],),
        dtype="float64",
        count=counts["num_images"],
        metadata=counts,
    )
