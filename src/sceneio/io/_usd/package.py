"""USDZ container and atomic destination helpers."""

from __future__ import annotations

import mmap
import os
import shutil
import struct
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path


def root_layer_prefix(path: str | os.PathLike[str]) -> bytes:
    """Return the first ten bytes of a direct layer or first USDZ entry."""

    with open(path, "rb") as source:
        prefix = source.read(10)
    if not prefix.startswith(b"PK\x03\x04"):
        return prefix
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or entries[0].is_dir():
                return b""
            with archive.open(entries[0]) as root_layer:
                return root_layer.read(10)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        return b""


def iter_root_layer_chunks(
    path: str | os.PathLike[str],
    *,
    chunk_size: int = 1024 * 1024,
):
    """Yield a direct layer or first USDZ entry without a whole-layer copy."""

    if chunk_size <= 0:
        raise ValueError("USD: root-layer chunk size must be positive")
    with open(path, "rb") as source:
        prefix = source.read(4)
    if not prefix.startswith(b"PK\x03\x04"):
        with open(path, "rb") as source:
            while chunk := source.read(chunk_size):
                yield chunk
        return
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if not entries or entries[0].is_dir():
            return
        with archive.open(entries[0]) as root_layer:
            while chunk := root_layer.read(chunk_size):
                yield chunk


@contextmanager
def mapped_root_layer(path: str | os.PathLike[str]):
    """Map a direct layer or stored USDZ root as ``(map, start, end)``."""

    with open(path, "rb") as source:
        mapped = None
        try:
            size = source.seek(0, os.SEEK_END)
            source.seek(0)
            if not size:
                yield None
                return
            mapped = mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ)
            if not mapped[:4].startswith(b"PK\x03\x04"):
                yield mapped, 0, size
                return
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if not entries or entries[0].is_dir():
                    yield None
                    return
                info = entries[0]
                if info.compress_type != zipfile.ZIP_STORED:
                    mapped.close()
                    mapped = None
                    with tempfile.TemporaryFile() as extracted:
                        with archive.open(info) as root_layer:
                            shutil.copyfileobj(
                                root_layer,
                                extracted,
                                length=1024 * 1024,
                            )
                        extracted_size = extracted.tell()
                        if not extracted_size:
                            yield None
                            return
                        extracted.flush()
                        extracted_map = mmap.mmap(
                            extracted.fileno(),
                            0,
                            access=mmap.ACCESS_READ,
                        )
                        try:
                            yield extracted_map, 0, extracted_size
                        finally:
                            extracted_map.close()
                    return
                header = info.header_offset
                if mapped[header : header + 4] != b"PK\x03\x04":
                    raise ValueError("USDZ: invalid root local-file header")
                name_length, extra_length = struct.unpack_from(
                    "<HH", mapped, header + 26
                )
                start = header + 30 + name_length + extra_length
                end = start + info.file_size
                if end > size:
                    raise ValueError("USDZ: root layer exceeds the archive")
                yield mapped, start, end
        finally:
            if mapped is not None:
                mapped.close()


def temporary_path(destination: Path, suffix: str) -> Path:
    """Create a sibling temporary path suitable for atomic replacement."""

    fd, name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=suffix,
        dir=destination.parent,
    )
    os.close(fd)
    return Path(name)


def write_usdz_archive(source: Path, destination: Path) -> None:
    """Store one 64-byte-aligned root USDA layer in a USDZ archive."""

    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=zipfile.ZIP_STORED,
        allowZip64=True,
    ) as archive:
        name = "root.usda"
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.file_size = source.stat().st_size
        base = archive.fp.tell() + 30 + len(name.encode("utf-8")) + 4
        padding = (-base) % 64
        info.extra = struct.pack("<HH", 0xFFFF, padding) + bytes(padding)
        with source.open("rb") as input_stream, archive.open(
            info, mode="w", force_zip64=source.stat().st_size >= 0xFFFFFFFF
        ) as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


__all__ = [
    "iter_root_layer_chunks",
    "mapped_root_layer",
    "root_layer_prefix",
    "temporary_path",
    "write_usdz_archive",
]
