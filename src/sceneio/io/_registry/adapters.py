"""Shared path, mmap, and file-sink adapters for codec families."""

from __future__ import annotations

import mmap
from collections.abc import Callable
from pathlib import Path

from sceneio import _core


def _bytes_reader(fn: Callable[[bytes], object]) -> Callable[[str], object]:
    def read(path: str):
        return fn(Path(path).read_bytes())

    return read


def _mmap_reader(fn: Callable[[object], object]) -> Callable[[str], object]:
    """Decode a file through a read-only mmap without materializing its bytes.

    Empty files cannot be mapped portably (notably on Windows), and a few
    filesystems do not support mmap. Those cases read from the same already-open
    stream as a compatibility fallback, preserving file identity across rename
    races. The current O1 decoders copy their payload into record-owned storage
    before returning, so the mapping can close here. Callers must not truncate a
    file or aliased backing storage during a read: changing bytes races the
    GIL-released decoder, and POSIX delivers SIGBUS for a shrunken live map.
    """

    def read(path: str):
        p = Path(path)
        with p.open("rb") as stream:
            try:
                mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                stream.seek(0)
                return fn(stream.read())
            with mapped:
                return fn(mapped)

    return read


def _mmap_selector_reader(fn: Callable[..., object]) -> Callable[..., object]:
    """Call a compiled partial decoder over a temporary read-only mapping."""

    def read(path: str, *selector):
        p = Path(path)
        with p.open("rb") as stream:
            try:
                mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                stream.seek(0)
                return fn(stream.read(), *selector)
            with mapped:
                return fn(mapped, *selector)

    return read


def _mmap_view_reader(
    view_fn: Callable[[object], object],
    fallback_fn: Callable[[object], object],
) -> Callable[..., object]:
    """Return mapped views whose owner keeps the mmap export alive.

    The compiled view reader pins the mmap's buffer export into the returned
    ndarray or record, so this adapter deliberately does not close a successful
    mapping. It is released automatically when the last owning record/array
    view is collected. Empty files and filesystems without mmap support use the
    established copy reader. The mapped file must not be modified or truncated
    for the lifetime of the returned views; atomic path replacement is safe. A
    private copy-on-write mapping is presented through a read-only memoryview so
    consumers that disregard NumPy's flag still cannot alter disk.
    """

    def read(path: str, *args):
        p = Path(path)
        with p.open("rb") as stream:
            try:
                # ACCESS_COPY is demand-paged like ACCESS_READ but supplies a
                # private writable backing as a last-resort safeguard for
                # consumers (notably torch.from_numpy) that ignore NumPy's
                # WRITEABLE=False flag. Present only a read-only memoryview to
                # the compiled parser; writes never reach the source file.
                mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_COPY)
            except (OSError, ValueError):
                stream.seek(0)
                return fallback_fn(stream.read(), *args)
            readonly = None
            try:
                readonly = memoryview(mapped).toreadonly()
                return view_fn(readonly, *args)
            except BaseException:
                # Do not let the chained FormatError traceback retain a live
                # mapping (and Windows file lock) after a failed decode.
                if readonly is not None:
                    readonly.release()
                mapped.close()
                raise

    return read


def _array_window_reader(reader: Callable[[str], object]) -> Callable[..., object]:
    """Slice a mapped raw raster while retaining its ndarray mapping owner."""

    def read(path: str, row_start: int, row_stop: int, col_start: int, col_stop: int):
        value = reader(path)
        if value.ndim < 2:
            raise ValueError("pixel-window reads require an array with at least two axes")
        height, width = value.shape[:2]
        if (
            row_start < 0
            or row_start >= row_stop
            or row_stop > height
            or col_start < 0
            or col_start >= col_stop
            or col_stop > width
        ):
            message = (
                f"window {(row_start, row_stop, col_start, col_stop)!r} "
                f"is outside raster shape {(height, width)!r}"
            )
            # The mapped ndarray owns the mmap. Remove this reference before
            # raising so a retained traceback cannot pin its Windows file lock.
            del value
            raise ValueError(message)
        return value[row_start:row_stop, col_start:col_stop, ...]

    return read


def _file_sink_writer(
    fn: Callable[[object], bytes],
    prepare: Callable[[object], object] | None = None,
) -> Callable[[object, str], None]:
    def write(obj, path: str):
        # Preparation must finish before the C++ sink becomes active: NumPy,
        # DLPack, and mapping protocols are arbitrary Python callbacks and may
        # re-enter an encoder. Only direct compiled encoders receive the
        # prepared value inside _write_to_file.
        if prepare is not None:
            obj = prepare(obj)
        _core._write_to_file(fn, obj, path)

    return write
