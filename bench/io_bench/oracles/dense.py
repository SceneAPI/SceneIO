"""Independent struct/NumPy oracles for COLMAP dense-MVS payloads."""

from __future__ import annotations

import struct

import numpy as np


def _matrix_header(width: int, height: int, depth: int) -> bytes:
    return f"{width}&{height}&{depth}&".encode("ascii")


def depth_write(values) -> bytes:
    array = np.asarray(values, dtype=np.float32)
    height, width = array.shape
    return _matrix_header(width, height, 1) + array.astype(
        "<f4", copy=False
    ).tobytes()


def depth_read(data: bytes):
    width, height, depth, payload = _matrix_parts(data)
    if depth != 1 or len(payload) != width * height * 4:
        raise ValueError("invalid COLMAP depth matrix")
    return np.frombuffer(payload, "<f4").reshape(height, width)


def normal_write(values) -> bytes:
    array = np.asarray(values, dtype=np.float32)
    height, width, depth = array.shape
    if depth != 3:
        raise ValueError("normal map must have three components")
    planar = array.transpose(2, 0, 1)
    return _matrix_header(width, height, 3) + planar.astype(
        "<f4", copy=False
    ).tobytes()


def normal_read(data: bytes):
    width, height, depth, payload = _matrix_parts(data)
    if depth != 3 or len(payload) != width * height * depth * 4:
        raise ValueError("invalid COLMAP normal matrix")
    return (
        np.frombuffer(payload, "<f4")
        .reshape(3, height, width)
        .transpose(1, 2, 0)
    )


def _matrix_parts(data: bytes):
    parts = data.split(b"&", 3)
    if len(parts) != 4 or any(not item.isdigit() for item in parts[:3]):
        raise ValueError("invalid COLMAP matrix header")
    return *(int(item) for item in parts[:3]), parts[3]


def consistency_write(payload) -> bytes:
    width, height, rows, columns, offsets, indices = payload
    output = bytearray(_matrix_header(width, height, 1))
    for entry in range(len(rows)):
        start = int(offsets[entry])
        stop = int(offsets[entry + 1])
        output.extend(
            struct.pack(
                "<3i",
                int(columns[entry]),
                int(rows[entry]),
                stop - start,
            )
        )
        output.extend(np.asarray(indices[start:stop], "<i4").tobytes())
    return bytes(output)


def consistency_read(data: bytes):
    width, height, depth, payload = _matrix_parts(data)
    if depth != 1 or len(payload) % 4:
        raise ValueError("invalid COLMAP consistency graph")
    values = np.frombuffer(payload, "<i4")
    position = 0
    entries = []
    while position < values.size:
        if values.size - position < 3:
            raise ValueError("truncated consistency entry")
        column, row, count = (int(item) for item in values[position : position + 3])
        position += 3
        if count < 0 or count > values.size - position:
            raise ValueError("invalid consistency count")
        entries.append(
            (column, row, tuple(int(item) for item in values[position : position + count]))
        )
        position += count
    return width, height, entries


def visibility_write(payload) -> bytes:
    offsets, indices = payload
    output = bytearray(struct.pack("<Q", len(offsets) - 1))
    for point in range(len(offsets) - 1):
        start = int(offsets[point])
        stop = int(offsets[point + 1])
        output.extend(struct.pack("<I", stop - start))
        output.extend(np.asarray(indices[start:stop], "<u4").tobytes())
    return bytes(output)


def visibility_read(data: bytes):
    if len(data) < 8:
        raise ValueError("truncated visibility header")
    points = struct.unpack_from("<Q", data)[0]
    position = 8
    rows = []
    for _ in range(points):
        if len(data) - position < 4:
            raise ValueError("truncated visibility count")
        count = struct.unpack_from("<I", data, position)[0]
        position += 4
        size = count * 4
        if size > len(data) - position:
            raise ValueError("truncated visibility row")
        rows.append(
            tuple(np.frombuffer(data, "<u4", count, position).tolist())
        )
        position += size
    if position != len(data):
        raise ValueError("trailing visibility data")
    return rows


__all__ = [
    "consistency_read",
    "consistency_write",
    "depth_read",
    "depth_write",
    "normal_read",
    "normal_write",
    "visibility_read",
    "visibility_write",
]

