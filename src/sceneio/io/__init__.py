"""Public format I/O for SceneIO — format-dispatched ``read`` / ``write``
over the compiled codecs, plus the record types.

    import sceneio
    recon = sceneio.read("sparse/0")     # -> Reconstruction  (COLMAP dir)
    cloud = sceneio.read("scene.ply")    # -> GaussianCloud
    sceneio.write(cloud, "out.ply")

Dispatch, error normalization, and detection are handled here; a new format
is one :func:`sceneio.io.register` call over a compiled codec. See
``docs/core_architecture.md``.
"""

from __future__ import annotations

from pathlib import Path

from sceneio import _core
from sceneio.io.registry import REGISTRY, Codec, FormatError, detect, get, register

# Record types produced by the codecs (re-exported for convenience/isinstance).
Reconstruction = _core.Reconstruction
GaussianCloud = _core.GaussianCloud
PosedViewSet = _core.PosedViewSet
TensorDict = _core.TensorDict
Image = _core.Image
Camera = _core.Camera


def read(path, *, format: str | None = None):
    """Read ``path`` into a record, dispatching on ``format`` or detection."""
    fmt = format or detect(path)
    codec = get(fmt)
    try:
        return codec.read(str(path))
    except FormatError:
        raise
    except Exception as exc:  # normalize codec faults to FormatError
        raise FormatError(f"reading {str(path)!r} as {fmt!r}: {exc}") from exc


def write(obj, path, *, format: str | None = None) -> None:
    """Write a record to ``path``, dispatching on ``format``, the object
    type, and the extension."""
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
    "Camera",
    "Codec",
    "FormatError",
    "GaussianCloud",
    "Image",
    "PosedViewSet",
    "Reconstruction",
    "TensorDict",
    "codecs",
    "detect",
    "read",
    "register",
    "write",
]
