"""Codec registry — the single place a format is wired into ``sceneio.io``.

Each :class:`Codec` binds a format id to its file extensions, a magic-byte
sniff, a reader, an optional writer, the record type it yields, and the
DataType it serializes. ``read()`` / ``write()`` / ``detect()`` dispatch
through this registry, so **adding a format is one** :func:`register` call
(plus the compiled codec). See ``docs/core_architecture.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sceneio import _core
from sceneio.errors import SceneIoError


class FormatError(SceneIoError):
    """A file could not be detected, read, or written in its format."""


@dataclass(frozen=True)
class Codec:
    """One format's binding into the I/O layer."""

    id: str
    extensions: tuple[str, ...]
    read: Callable[[str], object]  # (path) -> record
    write: Callable[[object, str], None] | None  # (record, path) -> None
    record: type | None  # record type produced, for write dispatch
    datatype: str  # the DataType id this format serializes
    magic: tuple[bytes, ...] = ()  # leading-byte signatures (single-file formats)
    is_directory: bool = False  # reads/writes a directory (e.g. COLMAP)


REGISTRY: dict[str, Codec] = {}


def register(codec: Codec) -> Codec:
    if codec.id in REGISTRY:
        raise ValueError(f"codec id already registered: {codec.id!r}")
    REGISTRY[codec.id] = codec
    return codec


def get(format_id: str) -> Codec:
    try:
        return REGISTRY[format_id]
    except KeyError:
        raise FormatError(f"unknown format id {format_id!r}") from None


def detect(path) -> str:
    """Return the format id for ``path`` (directory check, then extension,
    then a magic-byte sniff for extensionless files)."""
    p = Path(path)
    if p.is_dir():
        for c in REGISTRY.values():
            if c.is_directory and (p / "cameras.bin").exists():
                return c.id
        raise FormatError(f"no directory format matches {str(path)!r}")
    ext = p.suffix.lower()
    for c in REGISTRY.values():
        if ext in c.extensions:
            return c.id
    try:
        head = p.read_bytes()[:16]
    except OSError:
        head = b""
    for c in REGISTRY.values():
        if any(head.startswith(m) for m in c.magic):
            return c.id
    raise FormatError(f"cannot detect a format for {str(path)!r} (ext {ext!r})")


# --- adapters: give every _core function a uniform (path) signature -------
def _bytes_reader(fn: Callable[[bytes], object]) -> Callable[[str], object]:
    def read(path: str):
        return fn(Path(path).read_bytes())

    return read


def _bytes_writer(fn: Callable[[object], bytes]) -> Callable[[object, str], None]:
    def write(obj, path: str):
        Path(path).write_bytes(fn(obj))

    return write


# --- built-in codecs (the compiled `_core` functions, uniformly wrapped) ---
register(
    Codec(
        "pfm",
        (".pfm",),
        _bytes_reader(_core.read_pfm),
        _bytes_writer(_core.write_pfm),
        record=None,
        datatype="depth_map",
        magic=(b"PF", b"Pf"),
    )
)
register(
    Codec(
        "colmap_sparse",
        (),
        _core.read_colmap_sparse,
        _core.write_colmap_sparse,
        record=_core.Reconstruction,
        datatype="sparse_model",
        is_directory=True,
    )
)
register(
    Codec(
        "gaussian_ply",
        (".ply",),
        _bytes_reader(_core.read_gaussian_ply),
        _bytes_writer(_core.write_gaussian_ply),
        record=_core.GaussianCloud,
        datatype="splat",
        magic=(b"ply",),
    )
)
register(
    Codec(
        "spz",
        (".spz",),
        _bytes_reader(_core.read_spz),
        None,
        record=_core.GaussianCloud,
        datatype="splat",
        magic=(b"\x1f\x8b", b"NGSP"),
    )
)
