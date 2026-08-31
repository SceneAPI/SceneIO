"""Metadata-only inspection for mesh formats."""

from __future__ import annotations

from pathlib import Path

from sceneio import _core
from sceneio.io._inspectors.common import _compiled_buffer_inspect
from sceneio.io._inspectors.model import Inspection
from sceneio.io._ply import parse_ply_header, validate_mesh_ply_header


def inspect_ply_mesh(path: Path, payload_kind: str) -> Inspection:
    file_size = path.stat().st_size
    header = parse_ply_header(path)
    metadata = validate_mesh_ply_header(header, file_size)
    count = header.vertex.count
    return Inspection(
        "ply_mesh",
        payload_kind,
        file_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata=metadata,
    )


def inspect_stl(path: Path, payload_kind: str) -> Inspection:
    metadata = dict(_compiled_buffer_inspect(path, _core._inspect_stl))
    return Inspection(
        "stl",
        payload_kind,
        path.stat().st_size,
        shape=(metadata["num_vertices"], 3),
        dtype="float32",
        count=metadata["num_vertices"],
        metadata=metadata,
    )


def inspect_off(path: Path, payload_kind: str) -> Inspection:
    metadata = dict(_compiled_buffer_inspect(path, _core._inspect_off))
    return Inspection(
        "off",
        payload_kind,
        path.stat().st_size,
        shape=(metadata["num_vertices"], 3),
        dtype="float32",
        count=metadata["num_vertices"],
        metadata=metadata,
    )
