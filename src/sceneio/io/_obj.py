"""Path adapters for the multi-file Wavefront OBJ/MTL codec."""

from __future__ import annotations

import mmap
import os
import tempfile
from contextlib import ExitStack
from functools import partial
from pathlib import Path, PurePosixPath, PureWindowsPath

from sceneio import _core
from sceneio.io._inspectors.model import Inspection


def _mapped_or_bytes(stack: ExitStack, path: Path):
    stream = stack.enter_context(path.open("rb"))
    try:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
    except (OSError, ValueError):
        stream.seek(0)
        return stream.read()
    return stack.enter_context(mapped)


def _material_path(obj_path: Path, reference: str) -> Path:
    relative = Path(reference)
    if (
        relative.is_absolute()
        or PurePosixPath(reference).is_absolute()
        or PureWindowsPath(reference).is_absolute()
    ):
        raise ValueError("OBJ material-library path must be relative")
    return obj_path.parent / relative


def read_obj(path: str):
    """Read an OBJ and its single referenced MTL through read-only mappings."""

    obj_path = Path(path)
    with ExitStack() as stack:
        obj_data = _mapped_or_bytes(stack, obj_path)
        reference = _core.obj_material_library(obj_data)
        if reference is None:
            return _core.read_obj(obj_data)
        mtl_data = _mapped_or_bytes(
            stack, _material_path(obj_path, reference)
        )
        return _core.read_obj(obj_data, mtl_data)


def inspect_obj(path: str) -> Inspection:
    """Inspect OBJ/MTL counts without constructing canonical record arrays."""

    obj_path = Path(path)
    with ExitStack() as stack:
        obj_data = _mapped_or_bytes(stack, obj_path)
        obj_size = len(obj_data)
        values = _core.inspect_obj(obj_data)
        reference = values["material_library"]
        material_count = 0
        texture_count = 0
        mtl_size = 0
        if reference is not None:
            mtl_path = _material_path(obj_path, reference)
            mtl_data = _mapped_or_bytes(stack, mtl_path)
            mtl_size = len(mtl_data)
            material_values = _core.inspect_mtl(mtl_data)
            material_count = material_values["num_materials"]
            texture_count = material_values["num_textures"]
    vertices = values["num_vertices"]
    return Inspection(
        format="obj",
        payload_kind="mesh",
        byte_size=obj_size + mtl_size,
        shape=(vertices, 3),
        dtype="float32",
        count=vertices,
        metadata={
            "num_faces": values["num_faces"],
            "num_corners": values["num_corners"],
            "num_normals": values["num_normals"],
            "num_texcoords": values["num_texcoords"],
            "has_vertex_colors": values["has_vertex_colors"],
            "has_smoothing_groups": values["has_smoothing_groups"],
            "material_library": reference or "",
            "num_materials": material_count,
            "num_textures": texture_count,
        },
    )


def _temporary_peer(target: Path) -> Path:
    descriptor, value = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.sceneio-",
        suffix=".tmp",
    )
    os.close(descriptor)
    return Path(value)


def _install_outputs(outputs: list[tuple[Path, Path]]) -> None:
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        # Remove the entry-point OBJ before its MTL, then publish in the
        # caller-provided order (MTL before OBJ). A concurrent observer cannot
        # see a newly published OBJ that still lacks its material library.
        for _, target in reversed(outputs):
            if not target.exists():
                continue
            backup = _temporary_peer(target)
            backup.unlink()
            try:
                os.replace(target, backup)
            except BaseException:
                backup.unlink(missing_ok=True)
                raise
            backups.append((target, backup))
        for temporary, target in outputs:
            os.replace(temporary, target)
            installed.append(target)
    except BaseException:
        for target in reversed(installed):
            target.unlink(missing_ok=True)
        for target, backup in reversed(backups):
            if backup.exists():
                os.replace(backup, target)
        raise
    else:
        for _, backup in backups:
            backup.unlink(missing_ok=True)


def write_obj(mesh, path: str) -> None:
    """Write an OBJ and optional sibling MTL without Python-sized byte buffers."""

    obj_path = Path(path)
    outputs: list[tuple[Path, Path]] = []
    temporaries: list[Path] = []
    try:
        obj_temporary = _temporary_peer(obj_path)
        temporaries.append(obj_temporary)
        if mesh.has_materials:
            mtl_path = obj_path.with_suffix(".mtl")
            if mtl_path == obj_path:
                raise ValueError(
                    "OBJ and generated MTL destinations must be distinct"
                )
            _core._write_to_file(
                partial(_core.write_obj, mtl_filename=mtl_path.name),
                mesh,
                obj_temporary,
            )
            mtl_temporary = _temporary_peer(mtl_path)
            temporaries.append(mtl_temporary)
            _core._write_to_file(
                _core.write_mtl, mesh.materials, mtl_temporary
            )
            outputs.append((mtl_temporary, mtl_path))
        else:
            _core._write_to_file(_core.write_obj, mesh, obj_temporary)
        outputs.append((obj_temporary, obj_path))
        _install_outputs(outputs)
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
