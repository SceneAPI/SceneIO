"""Bounded PLY header parsing shared by detection and metadata inspection."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_HEADER_LIMIT = 1024 * 1024
_SCALAR_SIZES = {
    b"char": 1,
    b"int8": 1,
    b"uchar": 1,
    b"uint8": 1,
    b"short": 2,
    b"int16": 2,
    b"ushort": 2,
    b"uint16": 2,
    b"int": 4,
    b"int32": 4,
    b"uint": 4,
    b"uint32": 4,
    b"float": 4,
    b"float32": 4,
    b"double": 8,
    b"float64": 8,
}
_GAUSSIAN_REQUIRED = frozenset(
    {
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
)
_COMPRESSED_CHUNK_BASE = (
    b"min_x",
    b"min_y",
    b"min_z",
    b"max_x",
    b"max_y",
    b"max_z",
    b"min_scale_x",
    b"min_scale_y",
    b"min_scale_z",
    b"max_scale_x",
    b"max_scale_y",
    b"max_scale_z",
)
_COMPRESSED_CHUNK_COLOR = (
    b"min_r",
    b"min_g",
    b"min_b",
    b"max_r",
    b"max_g",
    b"max_b",
)
_COMPRESSED_VERTEX = (
    b"packed_position",
    b"packed_rotation",
    b"packed_scale",
    b"packed_color",
)


@dataclass(frozen=True)
class PlyProperty:
    name: bytes
    scalar_type: bytes | None
    list_count_type: bytes | None = None
    list_item_type: bytes | None = None


@dataclass(frozen=True)
class PlyElement:
    name: bytes
    count: int
    properties: tuple[PlyProperty, ...]


@dataclass(frozen=True)
class PlyHeader:
    encoding: str
    header_size: int
    elements: tuple[PlyElement, ...]

    @property
    def vertex(self) -> PlyElement:
        vertices = tuple(element for element in self.elements if element.name == b"vertex")
        if len(vertices) != 1:
            raise ValueError("PLY: requires exactly one vertex element")
        return vertices[0]


def _header_line(stream, total: int) -> tuple[bytes, int]:
    remaining = _HEADER_LIMIT + 1 - total
    if remaining <= 0:
        raise ValueError("PLY: header exceeds 1 MiB")
    line = stream.readline(remaining)
    if not line:
        raise ValueError("PLY: missing end_header")
    total += len(line)
    if total > _HEADER_LIMIT or not line.endswith(b"\n"):
        raise ValueError("PLY: header exceeds 1 MiB or has an unterminated line")
    line = line[:-1]
    if line.endswith(b"\r"):
        line = line[:-1]
    if b"\0" in line:
        raise ValueError("PLY: NUL byte in header")
    return line, total


def _count(token: bytes, what: str) -> int:
    if not token or not token.isdigit():
        raise ValueError(f"PLY: malformed {what}")
    value = int(token)
    if value > sys.maxsize:
        raise ValueError(f"PLY: {what} exceeds addressable size")
    return value


def parse_ply_header(path: str | Path) -> PlyHeader:
    """Parse at most 1 MiB and stop immediately after ``end_header``."""

    elements: list[tuple[bytes, int, list[PlyProperty]]] = []
    encoding = None
    current = None
    total = 0
    with Path(path).open("rb") as stream:
        first, total = _header_line(stream, total)
        if first != b"ply":
            raise ValueError("PLY: missing 'ply' magic")
        while True:
            line, total = _header_line(stream, total)
            tokens = line.split()
            if not tokens:
                raise ValueError("PLY: blank header directive")
            directive = tokens[0]
            if directive in {b"comment", b"obj_info"}:
                continue
            if directive == b"format":
                if (
                    len(tokens) != 3
                    or tokens[2] != b"1.0"
                    or encoding is not None
                    or elements
                ):
                    raise ValueError("PLY: malformed, duplicate, or misplaced format header")
                formats = {
                    b"ascii": "ascii",
                    b"binary_little_endian": "binary_little_endian",
                    b"binary_big_endian": "binary_big_endian",
                }
                try:
                    encoding = formats[tokens[1]]
                except KeyError:
                    raise ValueError("PLY: unsupported format") from None
            elif directive == b"element":
                if len(tokens) != 3 or encoding is None:
                    raise ValueError("PLY: malformed or misplaced element header")
                name = tokens[1]
                if not name:
                    raise ValueError("PLY: empty element name")
                if any(existing[0] == name for existing in elements):
                    raise ValueError(f"PLY: duplicate element {name!r}")
                elements.append((name, _count(tokens[2], "element count"), []))
                current = elements[-1]
            elif directive == b"property":
                if current is None:
                    raise ValueError("PLY: property appears before an element")
                if len(tokens) == 3:
                    scalar_type, name = tokens[1:]
                    if scalar_type not in _SCALAR_SIZES:
                        raise ValueError(f"PLY: unsupported scalar type {scalar_type!r}")
                    prop = PlyProperty(name, scalar_type)
                elif len(tokens) == 5 and tokens[1] == b"list":
                    count_type, item_type, name = tokens[2:]
                    if count_type not in _SCALAR_SIZES or item_type not in _SCALAR_SIZES:
                        raise ValueError("PLY: unsupported list scalar type")
                    prop = PlyProperty(name, None, count_type, item_type)
                else:
                    raise ValueError("PLY: malformed property header")
                if not prop.name:
                    raise ValueError("PLY: empty property name")
                if any(existing.name == prop.name for existing in current[2]):
                    raise ValueError(f"PLY: duplicate property {prop.name!r}")
                current[2].append(prop)
            elif directive == b"end_header":
                if tokens != [b"end_header"]:
                    raise ValueError("PLY: malformed end_header")
                break
            else:
                raise ValueError(f"PLY: unsupported header directive {directive!r}")
    if encoding is None:
        raise ValueError("PLY: missing format header")
    if not elements:
        raise ValueError("PLY: missing element header")
    return PlyHeader(
        encoding,
        total,
        tuple(PlyElement(name, count, tuple(properties)) for name, count, properties in elements),
    )


def _property_map(element: PlyElement) -> dict[bytes, PlyProperty]:
    return {prop.name: prop for prop in element.properties}


def _require_scalar_properties(
    element: PlyElement,
    expected_names: tuple[bytes, ...],
    expected_types: frozenset[bytes],
) -> None:
    properties = _property_map(element)
    if set(properties) != set(expected_names):
        raise ValueError(
            f"compressed PLY: unsupported {element.name.decode()} property set"
        )
    if any(
        prop.scalar_type not in expected_types
        for prop in properties.values()
    ):
        raise ValueError(
            f"compressed PLY: invalid {element.name.decode()} property type"
        )


def validate_compressed_ply_header(
    header: PlyHeader, file_size: int
) -> dict[str, object]:
    """Validate the current/legacy PlayCanvas compressed-Ply schemas."""

    if header.encoding != "binary_little_endian":
        raise ValueError("compressed PLY: binary little-endian encoding required")
    if len(header.elements) not in {2, 3}:
        raise ValueError(
            "compressed PLY: requires chunk, vertex, and optional sh elements"
        )
    names = tuple(element.name for element in header.elements)
    if names not in {(b"chunk", b"vertex"), (b"chunk", b"vertex", b"sh")}:
        raise ValueError(
            "compressed PLY: elements must be ordered chunk, vertex, optional sh"
        )
    chunk, vertex = header.elements[:2]
    chunk_names = tuple(prop.name for prop in chunk.properties)
    current = _COMPRESSED_CHUNK_BASE + _COMPRESSED_CHUNK_COLOR
    if set(chunk_names) == set(current):
        chunk_colors = True
        expected_chunk = current
    elif set(chunk_names) == set(_COMPRESSED_CHUNK_BASE):
        chunk_colors = False
        expected_chunk = _COMPRESSED_CHUNK_BASE
    else:
        raise ValueError(
            "compressed PLY: chunk schema must contain 12 or 18 float properties"
        )
    _require_scalar_properties(
        chunk, expected_chunk, frozenset({b"float", b"float32"})
    )
    _require_scalar_properties(
        vertex, _COMPRESSED_VERTEX, frozenset({b"uint", b"uint32"})
    )
    expected_chunks = vertex.count // 256 + bool(vertex.count % 256)
    if chunk.count != expected_chunks:
        raise ValueError(
            "compressed PLY: chunk count does not equal ceil(vertex/256)"
        )

    rest = 0
    if len(header.elements) == 3:
        sh = header.elements[2]
        if sh.count != vertex.count:
            raise ValueError(
                "compressed PLY: sh count does not equal vertex count"
            )
        rest = len(sh.properties)
        if rest not in {9, 24, 45}:
            raise ValueError(
                "compressed PLY: sh element requires 9, 24, or 45 properties"
            )
        _require_scalar_properties(
            sh,
            tuple(f"f_rest_{index}".encode() for index in range(rest)),
            frozenset({b"uchar", b"uint8"}),
        )

    chunk_stride = sum(
        _SCALAR_SIZES[prop.scalar_type] for prop in chunk.properties
    )
    vertex_stride = sum(
        _SCALAR_SIZES[prop.scalar_type] for prop in vertex.properties
    )
    expected_size = (
        header.header_size
        + chunk.count * chunk_stride
        + vertex.count * vertex_stride
        + vertex.count * rest
    )
    if expected_size != file_size:
        adjective = "truncated" if expected_size > file_size else "trailing"
        raise ValueError(f"compressed PLY: {adjective} binary payload")
    return {
        "encoding": "binary_little_endian",
        "byte_order": "little",
        "chunk_size": 256,
        "num_chunks": chunk.count,
        "sh_degree": {0: 0, 9: 1, 24: 2, 45: 3}[rest],
        "num_rest": rest,
        "chunk_color_ranges": chunk_colors,
        "position_bits": (11, 10, 11),
        "scale_bits": (11, 10, 11),
        "quaternion_bits": (2, 10, 10, 10),
        "color_bits": (8, 8, 8, 8),
    }


def classify_ply(path: str | Path) -> str:
    """Classify point, Gaussian, compressed-Gaussian, or mesh PLY."""

    header = parse_ply_header(path)
    if any(element.name == b"chunk" for element in header.elements):
        validate_compressed_ply_header(header, Path(path).stat().st_size)
        return "compressed_ply"
    vertex = header.vertex
    names = {prop.name for prop in vertex.properties}
    if any(element.name == b"face" for element in header.elements):
        return "ply_mesh"
    if len(header.elements) != 1:
        return "ply_mesh"
    if any(prop.scalar_type is None for prop in vertex.properties):
        return "ply_mesh"
    if names >= _GAUSSIAN_REQUIRED:
        normals = names & {b"nx", b"ny", b"nz"}
        if normals and normals != {b"nx", b"ny", b"nz"}:
            raise ValueError("PLY: incomplete Gaussian normal property group")
        rest_indices = set()
        allowed = _GAUSSIAN_REQUIRED | {b"nx", b"ny", b"nz"}
        for name in names - allowed:
            if not name.startswith(b"f_rest_"):
                raise ValueError(
                    f"PLY: unsupported Gaussian vertex property {name!r}"
                )
            suffix = name[len(b"f_rest_") :]
            if not suffix.isdigit():
                raise ValueError(f"PLY: malformed Gaussian property {name!r}")
            index = int(suffix)
            if suffix != str(index).encode() or index > 45:
                raise ValueError(f"PLY: malformed Gaussian property {name!r}")
            rest_indices.add(index)
        rest = 0
        while rest in rest_indices:
            rest += 1
        if rest_indices != set(range(rest)) or rest not in {0, 9, 24, 45}:
            raise ValueError("PLY: unsupported Gaussian SH property set")
        return "gaussian_ply"
    return "ply"


def validate_point_ply_header(header: PlyHeader, file_size: int) -> dict[str, object]:
    """Validate the PointCloud subset and return inspection metadata."""

    vertex = header.vertex
    if len(header.elements) != 1:
        raise ValueError("PLY point cloud: non-vertex elements require the mesh codec")
    properties = {prop.name: prop for prop in vertex.properties}
    required = {b"x", b"y", b"z"}
    missing = required - properties.keys()
    if missing:
        raise ValueError(f"PLY point cloud: missing property {min(missing)!r}")
    known = required | {
        b"nx",
        b"ny",
        b"nz",
        b"red",
        b"green",
        b"blue",
        b"intensity",
    }
    unknown = properties.keys() - known
    if unknown:
        raise ValueError(
            f"PLY point cloud: unsupported vertex property {min(unknown)!r}"
        )
    if any(prop.scalar_type is None for prop in vertex.properties):
        raise ValueError("PLY point cloud: list-valued vertex properties are unsupported")
    normal_names = {b"nx", b"ny", b"nz"} & properties.keys()
    if normal_names and normal_names != {b"nx", b"ny", b"nz"}:
        raise ValueError("PLY point cloud: normals require nx, ny, and nz")
    color_names = {b"red", b"green", b"blue"} & properties.keys()
    if color_names and color_names != {b"red", b"green", b"blue"}:
        raise ValueError("PLY point cloud: colors require red, green, and blue")
    color_dtype = None
    if color_names:
        color_types = {properties[name].scalar_type for name in color_names}
        if len(color_types) != 1 or color_types.pop() not in {
            b"uchar",
            b"uint8",
            b"ushort",
            b"uint16",
        }:
            raise ValueError("PLY point cloud: RGB must be uniformly uint8 or uint16")
        color_dtype = (
            "uint8"
            if properties[b"red"].scalar_type in {b"uchar", b"uint8"}
            else "uint16"
        )
    stride = sum(_SCALAR_SIZES[prop.scalar_type] for prop in vertex.properties)
    if not stride:
        raise ValueError("PLY point cloud: empty vertex schema")
    if header.encoding == "ascii":
        body_size = file_size - header.header_size
        max_tokens = (body_size + 1) // 2
        if vertex.count > max_tokens // len(vertex.properties):
            raise ValueError(
                "PLY point cloud: declared ASCII vertex count exceeds payload"
            )
    else:
        expected = header.header_size + vertex.count * stride
        if expected != file_size:
            adjective = "truncated" if expected > file_size else "trailing"
            raise ValueError(f"PLY point cloud: {adjective} binary vertex payload")
    intensity_type = (
        properties[b"intensity"].scalar_type if b"intensity" in properties else None
    )
    return {
        "encoding": header.encoding,
        "byte_order": (
            "little"
            if header.encoding == "binary_little_endian"
            else "big"
            if header.encoding == "binary_big_endian"
            else "text"
        ),
        "properties": tuple(prop.name.decode("ascii") for prop in vertex.properties),
        "property_types": tuple(
            prop.scalar_type.decode("ascii") for prop in vertex.properties
        ),
        "has_normals": bool(normal_names),
        "has_color": bool(color_names),
        "color_dtype": color_dtype or "none",
        "has_intensity": intensity_type is not None,
        "intensity_range": (
            "u8"
            if intensity_type in {b"uchar", b"uint8"}
            else "u16"
            if intensity_type in {b"ushort", b"uint16"}
            else "unknown"
        ),
        "vertex_stride": stride,
    }
