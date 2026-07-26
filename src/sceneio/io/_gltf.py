"""Path adapters for glTF JSON/external buffers and single-file GLB."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit

from sceneio import _core
from sceneio.io._inspectors.model import Inspection
from sceneio.io._obj import (
    _install_outputs,
    _mapped_or_bytes,
    _temporary_peer,
)


def _mapped_reader(function):
    def read(path: str, *args):
        with ExitStack() as stack:
            return function(_mapped_or_bytes(stack, Path(path)), *args)

    return read


def _sink_writer(function):
    def write(value, path: str) -> None:
        _core._write_to_file(function, value, path)

    return write


def _buffer_path(document: Path, uri: str) -> Path:
    parsed = urlsplit(uri)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(
            f"glTF external buffer URI must be a local relative path: {uri!r}"
        )
    decoded = unquote(parsed.path, errors="strict")
    relative = Path(*PurePosixPath(decoded).parts)
    if (
        relative.is_absolute()
        or PurePosixPath(decoded).is_absolute()
        or PureWindowsPath(decoded).is_absolute()
    ):
        raise ValueError(
            f"glTF external buffer URI must be relative: {uri!r}"
        )
    return document.parent / relative


def _mapped_document(stack: ExitStack, path: Path):
    data = _mapped_or_bytes(stack, path)
    resources = {
        uri: _mapped_or_bytes(stack, _buffer_path(path, uri))
        for uri in _core.gltf_external_buffer_uris(data)
    }
    return data, resources


def read_gltf(path: str):
    """Read JSON glTF and its external buffers through read-only mappings."""

    document = Path(path)
    with ExitStack() as stack:
        data, resources = _mapped_document(stack, document)
        return _core.read_gltf(data, resources)


def read_gltf_mesh(path: str, index: int):
    """Decode one source glTF mesh without materializing other primitives."""

    document = Path(path)
    with ExitStack() as stack:
        data, resources = _mapped_document(stack, document)
        return _core.read_gltf_mesh(data, resources, index)


def read_gltf_primitive(path: str, index: int):
    """Decode one source glTF primitive by flattened source order."""

    document = Path(path)
    with ExitStack() as stack:
        data, resources = _mapped_document(stack, document)
        return _core.read_gltf_primitive(data, resources, index)


def inspect_gltf(path: str) -> Inspection:
    """Inspect glTF structure without loading external binary payloads."""

    document = Path(path)
    with ExitStack() as stack:
        data = _mapped_or_bytes(stack, document)
        values = _core.inspect_gltf(data)
    byte_size = (
        document.stat().st_size + values["external_buffer_bytes"]
    )
    return _inspection("gltf", byte_size, values)


def inspect_glb(path: str) -> Inspection:
    """Inspect a GLB container without decoding its accessor payloads."""

    document = Path(path)
    with ExitStack() as stack:
        data = _mapped_or_bytes(stack, document)
        values = _core.inspect_glb(data)
    return _inspection("glb", document.stat().st_size, values)


def _inspection(format_id: str, byte_size: int, values: dict) -> Inspection:
    vertices = values["num_vertices"]
    return Inspection(
        format=format_id,
        datatype="mesh_scene",
        byte_size=byte_size,
        shape=(vertices, 3),
        dtype=values["dtype"],
        count=vertices,
        metadata={
            key: value for key, value in values.items() if key != "dtype"
        },
    )


def write_gltf(scene, path: str) -> None:
    """Publish a JSON glTF and its sibling binary buffer as one output unit."""

    document = Path(path)
    binary = document.with_suffix(".bin")
    if document == binary:
        raise ValueError("glTF JSON and binary destinations must be distinct")
    temporaries: list[Path] = []
    try:
        binary_temporary = _temporary_peer(binary)
        temporaries.append(binary_temporary)
        document_temporary = _temporary_peer(document)
        temporaries.append(document_temporary)
        _core._write_gltf_to_files(
            scene,
            binary.name,
            document_temporary,
            binary_temporary,
        )
        _install_outputs(
            [
                (binary_temporary, binary),
                (document_temporary, document),
            ]
        )
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)


read_glb = _mapped_reader(_core.read_glb)
read_glb_mesh = _mapped_reader(_core.read_glb_mesh)
read_glb_primitive = _mapped_reader(_core.read_glb_primitive)
write_glb = _sink_writer(_core.write_glb)
