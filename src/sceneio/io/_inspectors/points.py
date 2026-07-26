"""Metadata-only inspection for point-cloud formats."""

from __future__ import annotations

import math
import struct
from pathlib import Path

from sceneio import _core
from sceneio.io._inspectors.common import _compiled_buffer_inspect, _exact
from sceneio.io._inspectors.model import Inspection
from sceneio.io._pcd import parse_pcd_header, validate_point_pcd_header
from sceneio.io._ply import parse_ply_header, validate_point_ply_header


def _size(path: Path) -> int:
    return path.stat().st_size


def inspect_las(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    with path.open("rb") as stream:
        header = _exact(stream, min(255, file_size), "LAS public header")
    if len(header) < 227 or header[:4] != b"LASF":
        raise ValueError("las: bad or truncated public header")
    major, minor = header[24], header[25]
    if major != 1 or minor not in {1, 2, 3, 4}:
        raise ValueError("las: supported versions are 1.1 through 1.4")
    required_header = 375 if minor == 4 else 235 if minor == 3 else 227
    if file_size < required_header or len(header) < min(required_header, 255):
        raise ValueError("las: truncated public header")
    header_size = struct.unpack_from("<H", header, 94)[0]
    point_format = header[104]
    if point_format & 0xC0:
        raise ValueError("las: compressed LAZ is unsupported")
    format_id = point_format
    if format_id not in set(range(11)):
        raise ValueError(f"las: unsupported point format {format_id}")
    if format_id in {4, 5} and minor < 3:
        raise ValueError("las: point formats 4/5 require LAS 1.3 or newer")
    if format_id in {6, 7, 8, 9, 10} and minor < 4:
        raise ValueError("las: point formats 6-10 require LAS 1.4")
    if major == 1 and minor >= 4:
        if len(header) < 255:
            raise ValueError("las: truncated LAS 1.4 header")
        count = struct.unpack_from("<Q", header, 247)[0]
    else:
        count = struct.unpack_from("<I", header, 107)[0]
    offset_to_points = struct.unpack_from("<I", header, 96)[0]
    record_length = struct.unpack_from("<H", header, 105)[0]
    scales = struct.unpack_from("<ddd", header, 131)
    offsets = struct.unpack_from("<ddd", header, 155)
    if any(not math.isfinite(value) or value <= 0 for value in scales):
        raise ValueError("las: coordinate scales must be finite and positive")
    if any(not math.isfinite(value) for value in offsets):
        raise ValueError("las: coordinate offsets must be finite")
    minimum_length = {
        0: 20,
        1: 28,
        2: 26,
        3: 34,
        4: 57,
        5: 63,
        6: 30,
        7: 36,
        8: 38,
        9: 59,
        10: 67,
    }[format_id]
    if record_length < minimum_length:
        raise ValueError("las: point record length is too short")
    if count > 4_000_000_000:
        raise ValueError("las: point count exceeds the supported limit")
    if (
        header_size < required_header
        or offset_to_points < required_header
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
            "has_color": format_id in {2, 3, 5, 7, 8, 10},
            "has_intensity": True,
            "has_waveform": format_id in {4, 5, 9, 10},
        },
    )


def inspect_laz(path: Path, datatype: str) -> Inspection:
    """Inspect the LAS public header and LASzip VLR without decoding chunks."""

    file_size = _size(path)
    with path.open("rb") as stream:
        header = _exact(stream, min(375, file_size), "LAZ public header")
        if len(header) < 227 or header[:4] != b"LASF":
            raise ValueError("laz: bad or truncated public header")
        major, minor = header[24], header[25]
        if major != 1 or minor not in {1, 2, 3, 4}:
            raise ValueError("laz: supported versions are 1.1 through 1.4")
        required_header = 375 if minor == 4 else 235 if minor == 3 else 227
        if file_size < required_header or len(header) < required_header:
            raise ValueError("laz: truncated public header")
        global_encoding = struct.unpack_from("<H", header, 6)[0]
        if global_encoding & 0xFFFE:
            raise ValueError("laz: global-encoding metadata is not representable")

        header_size = struct.unpack_from("<H", header, 94)[0]
        point_offset = struct.unpack_from("<I", header, 96)[0]
        vlr_count = struct.unpack_from("<I", header, 100)[0]
        encoded_format = header[104]
        if encoded_format & 0xC0 != 0x80:
            raise ValueError("laz: header does not use supported compression bits")
        point_format = encoded_format & 0x3F
        if point_format not in {0, 1, 2, 3, 6, 7, 8}:
            raise ValueError(f"laz: unsupported point format {point_format}")
        if point_format >= 6 and minor < 4:
            raise ValueError("laz: point formats 6-8 require LAS 1.4")
        if header_size != required_header:
            raise ValueError("laz: extended public headers are not representable")
        if vlr_count != 1:
            raise ValueError("laz: exactly one LASzip VLR is required")
        if point_offset < header_size + 54 or point_offset > file_size:
            raise ValueError("laz: truncated or malformed VLR region")

        record_length = struct.unpack_from("<H", header, 105)[0]
        expected_length = {0: 20, 1: 28, 2: 26, 3: 34, 6: 30, 7: 36, 8: 38}[
            point_format
        ]
        if record_length != expected_length:
            raise ValueError(
                "laz: extra bytes and nonstandard point strides are not representable"
            )
        count = (
            struct.unpack_from("<Q", header, 247)[0]
            if minor == 4
            else struct.unpack_from("<I", header, 107)[0]
        )
        scales = struct.unpack_from("<ddd", header, 131)
        offsets = struct.unpack_from("<ddd", header, 155)
        if any(not math.isfinite(value) or value <= 0 for value in scales):
            raise ValueError("laz: coordinate scales must be finite and positive")
        if any(not math.isfinite(value) for value in offsets):
            raise ValueError("laz: coordinate offsets must be finite")
        if minor >= 3 and struct.unpack_from("<Q", header, 227)[0] != 0:
            raise ValueError("laz: waveform packet records are not representable")
        if minor >= 4:
            evlr_offset = struct.unpack_from("<Q", header, 235)[0]
            evlr_count = struct.unpack_from("<I", header, 243)[0]
            if evlr_offset != 0 or evlr_count != 0:
                raise ValueError("laz: EVLR metadata is not representable")
        if count > 4_000_000_000:
            raise ValueError("laz: point count exceeds the supported limit")

        stream.seek(header_size)
        vlr_header = _exact(stream, 54, "LAZ LASzip VLR header")
        reserved = struct.unpack_from("<H", vlr_header, 0)[0]
        user_id = vlr_header[2:18].rstrip(b"\0 ")
        record_id = struct.unpack_from("<H", vlr_header, 18)[0]
        payload_size = struct.unpack_from("<H", vlr_header, 20)[0]
        if reserved != 0 or user_id != b"laszip encoded" or record_id != 22204:
            raise ValueError("laz: the sole VLR must be the LASzip VLR")
        if header_size + 54 + payload_size != point_offset:
            raise ValueError("laz: VLR extent disagrees with point-data offset")
        payload = _exact(stream, payload_size, "LAZ LASzip VLR payload")
        stream.seek(point_offset)
        table_offset = struct.unpack(
            "<q", _exact(stream, 8, "LAZ chunk-table pointer")
        )[0]
        if table_offset < point_offset + 8 or table_offset > file_size - 8:
            raise ValueError("laz: chunk-table offset is out of bounds")
        stream.seek(table_offset)
        table_version, chunk_count = struct.unpack(
            "<II", _exact(stream, 8, "LAZ chunk-table header")
        )

    if payload_size < 34:
        raise ValueError("laz: LASzip VLR is truncated")
    compressor, coder, _version_major, _version_minor = struct.unpack_from(
        "<HHBB", payload
    )
    expected_compressor = 2 if point_format <= 3 else 3
    if compressor != expected_compressor or coder != 0:
        raise ValueError("laz: unsupported LASzip codec metadata")
    options = struct.unpack_from("<I", payload, 8)[0]
    chunk_size = struct.unpack_from("<I", payload, 12)[0]
    item_count = struct.unpack_from("<H", payload, 32)[0]
    if options != 0 or chunk_size == 0:
        raise ValueError("laz: unsupported LASzip options or chunk size")
    if table_version != 0:
        raise ValueError("laz: unsupported chunk-table version")
    if chunk_count > 4_000_000:
        raise ValueError("laz: chunk count exceeds the supported limit")
    if chunk_size != 0xFFFFFFFF:
        expected_chunks = 0 if count == 0 else 1 + (count - 1) // chunk_size
        if chunk_count != expected_chunks:
            raise ValueError("laz: fixed chunk count disagrees with point count")
    if count == 0 and table_offset + 8 != file_size:
        raise ValueError("laz: trailing bytes after empty chunk table")
    if payload_size != 34 + item_count * 6:
        raise ValueError("laz: malformed LASzip item table")
    expected_items = {
        0: ((6, 20, 2),),
        1: ((6, 20, 2), (7, 8, 2)),
        2: ((6, 20, 2), (8, 6, 2)),
        3: ((6, 20, 2), (7, 8, 2), (8, 6, 2)),
        6: ((10, 30, 3),),
        7: ((10, 30, 3), (11, 6, 3)),
        8: ((10, 30, 3), (12, 8, 3)),
    }[point_format]
    items = tuple(
        struct.unpack_from("<HHH", payload, 34 + index * 6)
        for index in range(item_count)
    )
    if items != expected_items:
        raise ValueError("laz: LASzip item schema disagrees with point format")
    if count and point_offset + 8 > file_size:
        raise ValueError("laz: truncated compressed point data")

    return Inspection(
        "laz",
        datatype,
        file_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={
            "point_format": point_format,
            "has_color": point_format in {2, 3, 7, 8},
            "has_intensity": True,
            "has_waveform": False,
            "chunk_size": chunk_size,
        },
    )


def inspect_ply(path: Path, datatype: str) -> Inspection:
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


def inspect_pcd(path: Path, datatype: str) -> Inspection:
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


def inspect_xyz(path: Path, datatype: str) -> Inspection:
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


def inspect_pts(path: Path, datatype: str) -> Inspection:
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
