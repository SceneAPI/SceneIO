"""Bounded PCD 0.7 header parsing and PointCloud-subset validation."""

from __future__ import annotations

import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

_HEADER_LIMIT = 1024 * 1024


@dataclass(frozen=True)
class PcdHeader:
    header_size: int
    fields: tuple[str, ...]
    sizes: tuple[int, ...]
    types: tuple[str, ...]
    counts: tuple[int, ...]
    width: int
    height: int
    viewpoint: tuple[float, ...]
    points: int
    storage: str

    @property
    def stride(self) -> int:
        return sum(size * count for size, count in zip(self.sizes, self.counts, strict=True))


def _line(stream, total: int) -> tuple[bytes, int]:
    remaining = _HEADER_LIMIT + 1 - total
    if remaining <= 0:
        raise ValueError("PCD: header exceeds 1 MiB")
    line = stream.readline(remaining)
    if not line:
        raise ValueError("PCD: missing DATA header")
    total += len(line)
    if total > _HEADER_LIMIT or not line.endswith(b"\n"):
        raise ValueError("PCD: header exceeds 1 MiB or has an unterminated line")
    line = line[:-1]
    if line.endswith(b"\r"):
        line = line[:-1]
    if b"\0" in line:
        raise ValueError("PCD: NUL byte in header")
    return line, total


def _uint(token: bytes, what: str) -> int:
    if not token or not token.isdigit():
        raise ValueError(f"PCD: malformed {what}")
    value = int(token)
    if value > sys.maxsize:
        raise ValueError(f"PCD: {what} exceeds addressable size")
    return value


def parse_pcd_header(path: str | Path) -> PcdHeader:
    expected = [
        b"VERSION",
        b"FIELDS",
        b"SIZE",
        b"TYPE",
        b"COUNT",
        b"WIDTH",
        b"HEIGHT",
        b"VIEWPOINT",
        b"POINTS",
        b"DATA",
    ]
    values: dict[bytes, tuple[bytes, ...]] = {}
    total = 0
    index = 0
    with Path(path).open("rb") as stream:
        while index < len(expected):
            raw, total = _line(stream, total)
            stripped = raw.strip()
            if not stripped or stripped.startswith(b"#"):
                continue
            tokens = tuple(stripped.split())
            if tokens[0] == b"COLUMNS":
                tokens = (b"FIELDS", *tokens[1:])
            if tokens[0] != expected[index]:
                raise ValueError(
                    f"PCD: expected {expected[index].decode()} header, "
                    f"found {tokens[0]!r}"
                )
            if tokens[0] in values:
                raise ValueError(f"PCD: duplicate {tokens[0].decode()} header")
            values[tokens[0]] = tokens[1:]
            index += 1

    if values[b"VERSION"] not in {(b".7",), (b"0.7",)}:
        raise ValueError("PCD: only VERSION .7 is supported")
    fields = tuple(token.decode("ascii") for token in values[b"FIELDS"])
    if not fields or len(fields) != len(set(fields)):
        raise ValueError("PCD: FIELDS must be nonempty and unique")
    sizes = tuple(_uint(token, "SIZE") for token in values[b"SIZE"])
    types = tuple(token.decode("ascii") for token in values[b"TYPE"])
    counts = tuple(_uint(token, "COUNT") for token in values[b"COUNT"])
    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise ValueError("PCD: FIELDS/SIZE/TYPE/COUNT lengths differ")
    if any(count < 1 for count in counts):
        raise ValueError("PCD: COUNT values must be positive")
    for size, kind in zip(sizes, types, strict=True):
        if kind == "F" and size not in {4, 8}:
            raise ValueError("PCD: floating fields require SIZE 4 or 8")
        if kind in {"I", "U"} and size not in {1, 2, 4, 8}:
            raise ValueError("PCD: integer fields require SIZE 1, 2, 4, or 8")
        if kind not in {"F", "I", "U"}:
            raise ValueError(f"PCD: unsupported TYPE {kind!r}")
    width_values = values[b"WIDTH"]
    height_values = values[b"HEIGHT"]
    points_values = values[b"POINTS"]
    if len(width_values) != 1 or len(height_values) != 1 or len(points_values) != 1:
        raise ValueError("PCD: WIDTH, HEIGHT, and POINTS require one value")
    width = _uint(width_values[0], "WIDTH")
    height = _uint(height_values[0], "HEIGHT")
    points = _uint(points_values[0], "POINTS")
    if height < 1 or (width == 0 and height != 1) or width * height != points:
        raise ValueError("PCD: WIDTH*HEIGHT must equal POINTS")
    if len(values[b"VIEWPOINT"]) != 7:
        raise ValueError("PCD: VIEWPOINT requires tx ty tz qw qx qy qz")
    try:
        viewpoint = tuple(float(token) for token in values[b"VIEWPOINT"])
    except ValueError:
        raise ValueError("PCD: malformed VIEWPOINT") from None
    if not all(math.isfinite(value) for value in viewpoint):
        raise ValueError("PCD: VIEWPOINT must be finite")
    if len(values[b"DATA"]) != 1:
        raise ValueError("PCD: DATA requires one storage mode")
    storage = values[b"DATA"][0].decode("ascii")
    if storage not in {"ascii", "binary", "binary_compressed"}:
        raise ValueError(f"PCD: unsupported DATA mode {storage!r}")
    return PcdHeader(
        total,
        fields,
        sizes,
        types,
        counts,
        width,
        height,
        viewpoint,
        points,
        storage,
    )


def validate_point_pcd_header(header: PcdHeader, path: str | Path) -> dict[str, object]:
    field_map = {name: index for index, name in enumerate(header.fields)}
    required = {"x", "y", "z"}
    missing = required - field_map.keys()
    if missing:
        raise ValueError(f"PCD: missing field {min(missing)!r}")
    known = required | {
        "normal_x",
        "normal_y",
        "normal_z",
        "rgb",
        "intensity",
    }
    unknown = field_map.keys() - known
    if unknown:
        raise ValueError(f"PCD: unsupported field {min(unknown)!r}")
    if any(count != 1 for count in header.counts):
        raise ValueError("PCD: mapped PointCloud fields require COUNT 1")
    normals = {"normal_x", "normal_y", "normal_z"} & field_map.keys()
    if normals and normals != {"normal_x", "normal_y", "normal_z"}:
        raise ValueError("PCD: normals require normal_x, normal_y, and normal_z")
    if "rgb" in field_map:
        index = field_map["rgb"]
        if header.sizes[index] != 4 or header.types[index] not in {"F", "U"}:
            raise ValueError("PCD: rgb must be packed SIZE 4 TYPE F or U")
    file_size = Path(path).stat().st_size
    body_size = file_size - header.header_size
    raw_size = header.points * header.stride
    compressed_size = None
    if header.storage == "ascii":
        scalar_count = sum(header.counts)
        max_tokens = (body_size + 1) // 2
        if header.points > max_tokens // scalar_count:
            raise ValueError("PCD: declared ASCII point count exceeds payload")
    elif header.storage == "binary":
        if body_size != raw_size:
            adjective = "truncated" if body_size < raw_size else "trailing"
            raise ValueError(f"PCD: {adjective} binary payload")
    else:
        if raw_size > 0xFFFF_FFFF:
            raise ValueError("PCD: compressed payload exceeds the format's 32-bit size")
        with Path(path).open("rb") as stream:
            stream.seek(header.header_size)
            sizes = stream.read(8)
        if len(sizes) != 8:
            raise ValueError("PCD: truncated compressed-size header")
        compressed_size, uncompressed_size = struct.unpack("<II", sizes)
        if uncompressed_size != raw_size:
            raise ValueError("PCD: compressed uncompressed-size does not match schema")
        if body_size != 8 + compressed_size:
            adjective = "truncated" if body_size < 8 + compressed_size else "trailing"
            raise ValueError(f"PCD: {adjective} compressed payload")
    intensity_range = "unknown"
    if "intensity" in field_map:
        index = field_map["intensity"]
        if header.types[index] == "U" and header.sizes[index] == 1:
            intensity_range = "u8"
        elif header.types[index] == "U" and header.sizes[index] == 2:
            intensity_range = "u16"
    return {
        "storage": header.storage,
        "fields": header.fields,
        "sizes": header.sizes,
        "types": header.types,
        "counts": header.counts,
        "width": header.width,
        "height": header.height,
        "organized": header.height > 1,
        "viewpoint": header.viewpoint,
        "has_normals": bool(normals),
        "has_color": "rgb" in field_map,
        "has_intensity": "intensity" in field_map,
        "intensity_range": intensity_range,
        "point_stride": header.stride,
        "compressed_size": compressed_size or 0,
    }
