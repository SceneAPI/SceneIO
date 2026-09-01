"""Codec registry — the single place a format is wired into ``sceneio.io``.

Each :class:`sceneio.Codec` binds a format id to its file extensions, a
magic-byte sniff, a reader, an optional writer, the record type it yields, and
its payload kind. ``read()`` / ``write()`` / ``detect()`` dispatch
through this registry, so **adding a format is one** :func:`register` call
(plus the compiled codec). See ``docs/core_architecture.md``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.errors import SceneIoError
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._hdf5 import classify_hdf5
from sceneio.io._inspection import inspect_codec
from sceneio.io._ply import classify_ply
from sceneio.io._registry.adapters import (
    _file_sink_writer,
    _mmap_reader,
    _mmap_selector_reader,
)
from sceneio.io._registry.assembly import BuiltinAssembly as _BuiltinAssembly
from sceneio.io._registry.assembly import (
    publish_builtin_definitions as _publish_builtin_definitions,
)
from sceneio.io._registry.detection import detect_path as _detect_path
from sceneio.io._registry.families.arrays import build_array_codecs
from sceneio.io._registry.families.calibration import CALIBRATION_CODECS
from sceneio.io._registry.families.containers import CONTAINER_CODECS
from sceneio.io._registry.families.datasets import build_dataset_codecs
from sceneio.io._registry.families.dense import DENSE_CODECS
from sceneio.io._registry.families.images import IMAGE_CODECS
from sceneio.io._registry.families.meshes import MESH_CODECS
from sceneio.io._registry.families.points import POINT_CODECS
from sceneio.io._registry.families.reconstruction import RECONSTRUCTION_CODECS
from sceneio.io._registry.families.sequences import build_sequence_codecs
from sceneio.io._registry.families.splats import build_splat_codecs
from sceneio.io._registry.model import (
    Codec as _Codec,
)
from sceneio.io._registry.model import (
    NativeFeatureCapabilities as _NativeFeatureCapabilities,
)
from sceneio.io._registry.native_features import (
    native_feature_snapshots as _native_feature_snapshots,
)


class FormatError(SceneIoError):
    """A file could not be detected, read, or written in its format."""


def native_feature_capabilities(
    name: str | None = None,
) -> _NativeFeatureCapabilities | dict[str, _NativeFeatureCapabilities]:
    """Return immutable compiled-state metadata for optional native features."""

    return _native_feature_snapshots(
        _core.__native_features__,
        name,
        unknown_feature=lambda feature: FormatError(f"unknown native feature {feature!r}"),
    )


REGISTRY: dict[str, _Codec]
_IS_REGISTRY_RELOAD = "REGISTRY" in globals()
if not _IS_REGISTRY_RELOAD:
    REGISTRY = {}
_RUNTIME_EXTENSIONS = tuple(
    (format_id, codec)
    for format_id, codec in REGISTRY.items()
    if format_id not in CANONICAL_BUILTIN_IDS
)
_BUILTIN_ASSEMBLY = _BuiltinAssembly()


def register(codec: _Codec) -> _Codec:
    if codec.id in REGISTRY:
        raise ValueError(f"codec id already registered: {codec.id!r}")
    REGISTRY[codec.id] = codec
    return codec


def _define_builtin_family(
    family_name: str,
    codecs: tuple[_Codec, ...],
) -> tuple[_Codec, ...]:
    """Stage one complete built-in family without mutating ``REGISTRY``."""

    return _BUILTIN_ASSEMBLY.add_family(family_name, codecs)


def _install_builtin_family(
    codecs: tuple[_Codec, ...],
    expected_ids: tuple[str, ...],
) -> None:
    """Validate one complete built-in family before installing any member."""

    definitions = tuple(codecs)
    if any(type(codec) is not _Codec for codec in definitions):
        raise TypeError("built-in family entries must be Codec instances")
    actual_ids = tuple(codec.id for codec in definitions)
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError(f"built-in family ids must be unique: {actual_ids!r}")
    if actual_ids != tuple(expected_ids):
        raise ValueError(f"built-in family ids {actual_ids!r} do not match {tuple(expected_ids)!r}")
    collisions = tuple(format_id for format_id in actual_ids if format_id in REGISTRY)
    if collisions:
        raise ValueError(f"built-in codec ids already registered: {collisions!r}")
    for codec in definitions:
        REGISTRY[codec.id] = codec


def get(format_id: str) -> _Codec:
    try:
        return REGISTRY[format_id]
    except KeyError:
        raise FormatError(f"unknown format id {format_id!r}") from None


def detect(path) -> str:
    """Return the format id for ``path`` (directory check, then extension,
    then a magic-byte sniff for extensionless files)."""
    return _detect_path(
        path,
        REGISTRY.values(),
        classify_ply=classify_ply,
        classify_hdf5=classify_hdf5,
        format_error=FormatError,
    )


def _inspect_registered_image_path(path: str | Path):
    """Resolve and inspect one canonical still-image frame."""

    fmt = detect(path)
    codec = get(fmt)
    if codec.record is not _core.Image or codec.payload_kind != "image":
        record_name = getattr(codec.record, "__name__", "None")
        raise ValueError(
            f"image frame {Path(path).name!r} resolves to format {fmt!r} "
            f"with payload {codec.payload_kind!r}/{record_name}, not Image"
        )
    try:
        result = inspect_codec(path, fmt, codec.payload_kind, codec.inspect)
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(f"inspecting {str(path)!r} as {fmt!r}: {exc}") from exc
    if result.format != fmt or result.payload_kind != "image":
        raise ValueError(f"image frame inspector for {fmt!r} returned an inconsistent contract")
    return result


def _registered_image_extensions() -> frozenset[str]:
    return frozenset(
        extension
        for codec in REGISTRY.values()
        if codec.record is _core.Image and codec.payload_kind == "image"
        for extension in codec.extensions
    )


_SOG_ARCHIVE_READER = _mmap_reader(_core.read_sog)
_SOG_ARCHIVE_POINT_READER = _mmap_selector_reader(_core.read_sog_points)
_SOG_ARCHIVE_WRITER = _file_sink_writer(_core.write_sog)


def _sog_metadata_path(path: str) -> Path:
    value = Path(path)
    return value / "meta.json" if value.name != "meta.json" else value


def _sog_reader(path: str):
    value = Path(path)
    if value.is_dir() or value.name == "meta.json":
        return _core.read_sog_directory(str(_sog_metadata_path(path)))
    return _SOG_ARCHIVE_READER(path)


def _sog_point_reader(path: str, start: int, stop: int):
    value = Path(path)
    if value.is_dir() or value.name == "meta.json":
        return _core.read_sog_directory_points(str(_sog_metadata_path(path)), start, stop)
    return _SOG_ARCHIVE_POINT_READER(path, start, stop)


def _sog_writer(obj, path: str) -> None:
    value = Path(path)
    if value.is_dir() or value.name == "meta.json" or value.suffix == "":
        _core.write_sog_directory(obj, str(_sog_metadata_path(path)))
    else:
        _SOG_ARCHIVE_WRITER(obj, path)


# --- npy/npz adapters: the compiled writers require C-contiguous, native-endian
# input, and .npz accepts either a TensorDict or a plain {name: array} dict.
def _canon(a):
    a = np.ascontiguousarray(a)
    if a.dtype.byteorder == ">":
        a = a.astype(a.dtype.newbyteorder("="))
    return a


def _prepare_tensor_dict(obj):
    if isinstance(obj, _core.TensorDict):
        return obj
    return _core.tensor_dict({k: _canon(v) for k, v in dict(obj).items()})


# --- built-in codecs (the compiled `_core` functions, uniformly wrapped) ---
_ARRAY_CODECS = build_array_codecs(_canon, _prepare_tensor_dict)
_define_builtin_family(
    "arrays",
    _ARRAY_CODECS,
)
_define_builtin_family("reconstruction", RECONSTRUCTION_CODECS)
_SPLAT_CODECS = build_splat_codecs(
    _sog_reader,
    _sog_writer,
    _sog_point_reader,
)
_define_builtin_family("splats", _SPLAT_CODECS)
_define_builtin_family("meshes", MESH_CODECS)
_define_builtin_family("points", POINT_CODECS)
_define_builtin_family("calibration", CALIBRATION_CODECS)
_define_builtin_family("containers", CONTAINER_CODECS)
_define_builtin_family("dense", DENSE_CODECS)
_define_builtin_family("images", IMAGE_CODECS)
_IMAGE_FRAME_ACCESS = ImageFrameAccess(
    extensions=_registered_image_extensions,
    inspect=_inspect_registered_image_path,
)
_define_builtin_family(
    "datasets",
    build_dataset_codecs(_IMAGE_FRAME_ACCESS),
)
_define_builtin_family(
    "sequences",
    build_sequence_codecs(_IMAGE_FRAME_ACCESS),
)

# This immutable tuple is the repository-owned completeness boundary. Built-ins
# become visible only after the complete canonical set validates successfully.
# The same mutable REGISTRY then remains the public extension point.
BUILTIN_DEFINITIONS: tuple[_Codec, ...] = _BUILTIN_ASSEMBLY.finalize()
_PUBLICATION_TARGET: dict[str, _Codec] = {} if _IS_REGISTRY_RELOAD else REGISTRY
_publish_builtin_definitions(_PUBLICATION_TARGET, BUILTIN_DEFINITIONS)
if _IS_REGISTRY_RELOAD:
    _PENDING_REGISTRY = _PUBLICATION_TARGET
    _PENDING_REGISTRY.update(_RUNTIME_EXTENSIONS)
    _PUBLISHED_IDS = tuple(_PENDING_REGISTRY)
else:
    _PUBLISHED_IDS = tuple(REGISTRY)
if _PUBLISHED_IDS[: len(CANONICAL_BUILTIN_IDS)] != CANONICAL_BUILTIN_IDS:
    raise RuntimeError("built-in codec publication order differs from its manifest")
if _IS_REGISTRY_RELOAD:
    REGISTRY.clear()
    REGISTRY.update(_PENDING_REGISTRY)
