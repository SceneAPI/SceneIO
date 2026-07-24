"""Public format I/O for SceneIO — format-dispatched ``read`` / ``write`` /
``inspect`` / ``read_partial`` over the compiled codecs, plus the record types.

    import sceneio
    recon = sceneio.read("sparse/0")     # -> Reconstruction  (COLMAP dir)
    cloud = sceneio.read("scene.ply")    # -> GaussianCloud
    sceneio.write(cloud, "out.ply")

Dispatch, error normalization, and detection are handled here; a new format
is one :func:`sceneio.io.register` call over a compiled codec. See
``docs/core_architecture.md``.
"""

from __future__ import annotations

import operator
from pathlib import Path

from sceneio import _core
from sceneio.io._inspection import ArrayInspection, Inspection, inspect_path
from sceneio.io.registry import REGISTRY, Codec, FormatError, detect, get, register

# Record types produced by the codecs (re-exported for convenience/isinstance).
Reconstruction = _core.Reconstruction
GaussianCloud = _core.GaussianCloud
PosedViewSet = _core.PosedViewSet
TensorDict = _core.TensorDict
Image = _core.Image
PointCloud = _core.PointCloud
DepthMap = _core.DepthMap
Camera = _core.Camera


def read(path, *, format: str | None = None):
    """Read ``path`` into a record, dispatching on ``format`` or detection.

    Single-file codecs use a read-only mmap. The file must remain byte-stable
    during decoding. Native-endian, C-order NPY and FLO results are read-only
    views that retain the mapping, so their backing file must not be modified or
    truncated until the returned array and all derived views are released; a
    POSIX shrink can otherwise cause ``SIGBUS`` on later access. Atomic path
    replacement is safe because the live mapping retains the old file. On
    Windows the mapped file remains locked for the same lifetime. DLPack export
    makes an isolated contiguous copy because writable tensor consumers cannot
    safely alias a read-only file mapping. PFM remains an owned, positive-stride
    decode because its bottom-to-top row order requires a real transform.
    """
    fmt = format or detect(path)
    codec = get(fmt)
    try:
        return codec.read(str(path))
    except FormatError:
        raise
    except Exception as exc:  # normalize codec faults to FormatError
        raise FormatError(f"reading {str(path)!r} as {fmt!r}: {exc}") from exc


def inspect(path, *, format: str | None = None) -> Inspection:
    """Return dimensions, dtype, and element counts without decoding bulk data.

    Binary image/array/cloud formats read only their container headers.
    Headerless text formats are streamed to count records, and JSON scene
    formats parse their metadata document without constructing compiled record
    arrays.
    """
    fmt = format or detect(path)
    codec = get(fmt)
    try:
        result = (
            inspect_path(path, fmt, codec.datatype)
            if codec.inspect is None
            else codec.inspect(str(path))
        )
        if not isinstance(result, Inspection):
            raise TypeError(
                f"format {fmt!r} inspector returned {type(result).__name__}, "
                "expected Inspection"
            )
        return result
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(f"inspecting {str(path)!r} as {fmt!r}: {exc}") from exc


def read_partial(
    path,
    *,
    window=None,
    points=None,
    image_id=None,
    format: str | None = None,
):
    """Read only one file-backed region while preserving the normal record type.

    Exactly one selector is required. ``window`` is the half-open pixel box
    ``(row_start, row_stop, column_start, column_stop)``. ``points`` is the
    half-open record range ``(start, stop)``. ``image_id`` selects one COLMAP
    image by its persisted id. A format that cannot access the selected region
    without a full payload decode raises :class:`FormatError`.
    """

    selected = sum(value is not None for value in (window, points, image_id))
    if selected != 1:
        raise ValueError("read_partial requires exactly one of window, points, or image_id")
    fmt = format or detect(path)
    codec = get(fmt)
    if window is not None:
        values = _selector_ints(window, 4, "window")
        if codec.read_window is None:
            raise FormatError(f"format {fmt!r} does not support pixel-window reads")
        operation = codec.read_window
    elif points is not None:
        values = _selector_ints(points, 2, "points")
        if codec.read_points is None:
            raise FormatError(f"format {fmt!r} does not support point-subset reads")
        operation = codec.read_points
    else:
        selected_image = _selector_int(image_id, "image_id")
        if selected_image < 0 or selected_image > 0xFFFFFFFF:
            raise ValueError("image_id must be in 0..4294967295")
        if codec.read_image is None:
            raise FormatError(f"format {fmt!r} does not support single-image reads")
        operation = codec.read_image
        values = (selected_image,)
    try:
        return operation(str(path), *values)
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(
            f"partially reading {str(path)!r} as {fmt!r}: {exc}"
        ) from exc


def _selector_int(value, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} values must be integers, not bool")
    try:
        return operator.index(value)
    except TypeError:
        raise TypeError(f"{name} values must be integers") from None


def _selector_ints(value, length: int, name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must contain {length} integers")
    try:
        values = tuple(value)
    except TypeError:
        raise TypeError(f"{name} must contain {length} integers") from None
    if len(values) != length:
        raise ValueError(f"{name} must contain exactly {length} integers")
    return tuple(_selector_int(item, name) for item in values)


def write(obj, path, *, format: str | None = None) -> None:
    """Write a record to ``path``, dispatching on ``format``, the object
    type, and the extension.

    Single-file codecs write their C++ encoder buffer directly to the file
    without materializing a second output-sized Python ``bytes`` object. The
    file opens lazily after validation and encoding, so a rejected record does
    not truncate an existing destination.
    """
    fmt = format or _detect_write(obj, path)
    codec = get(fmt)
    if codec.write is None:
        raise FormatError(f"format {fmt!r} is read-only (no writer)")
    try:
        codec.write(obj, str(path))
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(f"writing {str(path)!r} as {fmt!r}: {exc}") from exc


def codecs() -> dict[str, Codec]:
    """The registered codecs, keyed by format id."""
    return dict(REGISTRY)


def _detect_write(obj, path) -> str:
    # dispatch by extension (or directory) first, then disambiguate on the
    # record type if several writable codecs share an extension.
    ext = Path(path).suffix.lower()
    name = Path(path).name
    cands = [
        c
        for c in REGISTRY.values()
        if c.write is not None
        and (ext in c.extensions or name in c.filenames or (c.is_directory and ext == ""))
    ]
    if not cands:
        raise FormatError(f"no writer for {type(obj).__name__} at {str(path)!r} (ext {ext!r})")
    if len(cands) > 1:
        for c in cands:
            if c.record is type(obj):
                return c.id
    return cands[0].id


__all__ = [
    "ArrayInspection",
    "Camera",
    "Codec",
    "DepthMap",
    "FormatError",
    "GaussianCloud",
    "Image",
    "Inspection",
    "PointCloud",
    "PosedViewSet",
    "Reconstruction",
    "TensorDict",
    "codecs",
    "detect",
    "inspect",
    "read",
    "read_partial",
    "register",
    "write",
]
