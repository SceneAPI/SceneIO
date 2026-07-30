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
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from sceneio import _core
from sceneio.colmap_db import ColmapDatabaseConversionReport
from sceneio.io._depth import DepthEncoding, inspect_depth, read_depth, write_depth
from sceneio.io._hdf5 import HlocFeatureStore, HlocMatchStore
from sceneio.io._inspection import inspect_codec
from sceneio.io._inspectors.model import ArrayInspection, Inspection
from sceneio.io._registry.adapters import _file_sink_writer, _mmap_reader
from sceneio.io._zarr import write_zarr
from sceneio.io.registry import (
    REGISTRY,
    Codec,
    CodecCapabilities,
    FormatError,
    NativeFeatureCapabilities,
    detect,
    get,
    native_feature_capabilities,
    register,
)

# Record types produced by the codecs (re-exported for convenience/isinstance).
Reconstruction = _core.Reconstruction
GaussianCloud = _core.GaussianCloud
PosedViewSet = _core.PosedViewSet
StateTrajectory = _core.StateTrajectory
TensorDict = _core.TensorDict
Image = _core.Image
ImageSequence = _core.ImageSequence
PointCloud = _core.PointCloud
MaterialSet = _core.MaterialSet
Mesh = _core.Mesh
MeshScene = _core.MeshScene
PoseGraph = _core.PoseGraph
FeatureSet = _core.FeatureSet
MatchGraph = _core.MatchGraph
ColmapDatabase = _core.ColmapDatabase
ColmapRigFrameSet = _core.ColmapRigFrameSet
ColmapPosePriorSet = _core.ColmapPosePriorSet
ColmapMarkerSet = _core.ColmapMarkerSet
ColmapVideoMetadataSet = _core.ColmapVideoMetadataSet
ColmapMaxxSchemaInfo = _core.ColmapMaxxSchemaInfo
DepthMap = _core.DepthMap
FlowField = _core.FlowField
NormalMap = _core.NormalMap
ConsistencyGraph = _core.ConsistencyGraph
PointVisibility = _core.PointVisibility
Camera = _core.Camera
CameraRig = _core.CameraRig

_FLOW_READER = _mmap_reader(_core.read_flo_field)
_FLOW_WRITER = _file_sink_writer(_core.write_flo_field)
_EXACT_COLMAP_DB_PROFILES = frozenset(
    item["name"] for item in _core._colmap_db_profiles()
)


def _resolve_flow_format(path, format: str | None, *, writing: bool) -> str:
    if format is not None:
        selected = format
    elif writing:
        selected = "flo" if Path(path).suffix.lower() == ".flo" else ""
    else:
        selected = detect(path)
    if selected != "flo":
        operation = "write" if writing else "read"
        rendered = selected or Path(path).suffix.lower() or "<none>"
        raise FormatError(
            f"{operation}_flow supports only Middlebury 'flo' "
            f"(selected {rendered!r})"
        )
    return selected


def read_flow(path, *, format: str | None = None) -> FlowField:
    """Read Middlebury ``.flo`` into a convention-tagged :class:`FlowField`.

    The file is decoded through a read-only mmap into record-owned storage.
    Existing :func:`read` behavior is unchanged and continues to return the raw
    mapped ``(H,W,2)`` ndarray.
    """

    _resolve_flow_format(path, format, writing=False)
    try:
        return _FLOW_READER(str(path))
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(f"reading {str(path)!r} as typed flow: {exc}") from exc


def write_flow(
    flow: FlowField,
    path,
    *,
    format: str | None = None,
) -> None:
    """Write a canonical Middlebury-convention :class:`FlowField`.

    The writer refuses component, axis, row, unit, or invalid-value
    conventions that ``.flo`` cannot preserve. It uses the direct native file
    sink and does not materialize an output-sized Python ``bytes`` object.
    """

    _resolve_flow_format(path, format, writing=True)
    try:
        _FLOW_WRITER(flow, str(path))
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(f"writing {str(path)!r} as typed flow: {exc}") from exc


def inspect_flow(path, *, format: str | None = None) -> Inspection:
    """Inspect a ``.flo`` header and attach its fixed semantic conventions."""

    selected = _resolve_flow_format(path, format, writing=False)
    result = inspect(path, format=selected)
    return replace(
        result,
        metadata={
            **result.metadata,
            "component_order": "uv",
            "u_axis": "right",
            "v_axis": "down",
            "row_order": "top_to_bottom",
            "unit": "pixels",
            "invalid_policy": "component_abs_gt_1e9",
        },
    )


def read(path, *, format: str | None = None):
    """Read ``path`` into a record, dispatching on ``format`` or detection.

    Single-file codecs use a read-only mmap. The file must remain byte-stable
    during decoding. Native-endian, C-order NPY and FLO results are read-only
    views that retain the mapping. Safetensors returns a ``TensorDict`` whose
    aligned tensors are likewise read-only mapped views. Their backing file must
    not be modified or truncated until the record, returned arrays, and all
    derived views are released; a POSIX shrink can otherwise cause ``SIGBUS`` on
    later access. Atomic path replacement is safe because the live mapping
    retains the old file. On Windows the mapped file remains locked for the same
    lifetime. DLPack export makes an isolated contiguous copy because writable
    tensor consumers cannot safely alias a read-only file mapping. PFM remains
    an owned, positive-stride decode because its bottom-to-top row order requires
    a real transform.
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
        return inspect_codec(path, fmt, codec.datatype, codec.inspect)
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(f"inspecting {str(path)!r} as {fmt!r}: {exc}") from exc


def read_partial(
    path,
    *,
    window=None,
    points=None,
    faces=None,
    mesh_id=None,
    primitive_id=None,
    states=None,
    frames=None,
    image_id=None,
    pair=None,
    tensors=None,
    slices=None,
    format: str | None = None,
):
    """Read only one file-backed region while preserving the normal record type.

    Exactly one selector is required. ``window`` is the half-open pixel box
    ``(row_start, row_stop, column_start, column_stop)``. ``points``, ``faces``,
    ``states``, and ``frames`` are half-open record ranges ``(start, stop)``.
    A mesh face
    selection retains the complete vertex domain and slices all face/corner
    domains. ``mesh_id`` selects one glTF mesh object; ``primitive_id`` selects
    one glTF primitive in flattened source order. Both return a ``MeshScene``
    geometry projection with the shared material table and no node/scene rows.
    ``image_id`` selects one COLMAP image by its persisted id. ``pair``
    selects one unordered pair of persisted COLMAP image ids. ``tensors``
    selects complete named tensors.
    ``slices`` maps tensor names to half-open leading-axis ``(start, stop)``
    ranges. A format that cannot access the selected region without a full
    payload decode raises :class:`FormatError`.
    """

    selected = sum(
        value is not None
        for value in (
            window,
            points,
            faces,
            mesh_id,
            primitive_id,
            states,
            frames,
            image_id,
            pair,
            tensors,
            slices,
        )
    )
    if selected != 1:
        raise ValueError(
            "read_partial requires exactly one selector family"
        )
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
    elif faces is not None:
        values = _selector_ints(faces, 2, "faces")
        if codec.read_faces is None:
            raise FormatError(f"format {fmt!r} does not support face-subset reads")
        operation = codec.read_faces
    elif mesh_id is not None:
        selected_mesh = _selector_int(mesh_id, "mesh_id")
        if selected_mesh < 0:
            raise ValueError("mesh_id must be non-negative")
        if codec.read_mesh is None:
            raise FormatError(
                f"format {fmt!r} does not support mesh-subset reads"
            )
        operation = codec.read_mesh
        values = (selected_mesh,)
    elif primitive_id is not None:
        selected_primitive = _selector_int(primitive_id, "primitive_id")
        if selected_primitive < 0:
            raise ValueError("primitive_id must be non-negative")
        if codec.read_primitive is None:
            raise FormatError(
                f"format {fmt!r} does not support primitive-subset reads"
            )
        operation = codec.read_primitive
        values = (selected_primitive,)
    elif states is not None:
        values = _selector_ints(states, 2, "states")
        if codec.read_states is None:
            raise FormatError(
                f"format {fmt!r} does not support state-subset reads"
            )
        operation = codec.read_states
    elif frames is not None:
        values = _selector_ints(frames, 2, "frames")
        if codec.read_frames is None:
            raise FormatError(
                f"format {fmt!r} does not support frame-subset reads"
            )
        operation = codec.read_frames
    elif image_id is not None:
        selected_image = _selector_int(image_id, "image_id")
        if selected_image < 0 or selected_image > 0xFFFFFFFF:
            raise ValueError("image_id must be in 0..4294967295")
        if codec.read_image is None:
            raise FormatError(f"format {fmt!r} does not support single-image reads")
        operation = codec.read_image
        values = (selected_image,)
    elif pair is not None:
        image_a, image_b = _selector_ints(pair, 2, "pair")
        if (
            image_a < 0
            or image_a >= 2_147_483_647
            or image_b < 0
            or image_b >= 2_147_483_647
        ):
            raise ValueError(
                "pair image ids must be in 0..2147483646"
            )
        if image_a == image_b:
            raise ValueError("pair image ids must be distinct")
        if codec.read_pair is None:
            raise FormatError(
                f"format {fmt!r} does not support image-pair reads"
            )
        operation = codec.read_pair
        values = (image_a, image_b)
    elif tensors is not None:
        selected_tensors = _tensor_names(tensors)
        if codec.read_tensors is None:
            raise FormatError(
                f"format {fmt!r} does not support named-tensor reads"
            )
        operation = codec.read_tensors
        values = (selected_tensors,)
    else:
        selected_slices = _tensor_slices(slices)
        if codec.read_slices is None:
            raise FormatError(
                f"format {fmt!r} does not support tensor-slice reads"
            )
        operation = codec.read_slices
        values = (selected_slices,)
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


def _tensor_names(value) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("tensors must be a non-empty iterable of names")
    try:
        names = tuple(value)
    except TypeError:
        raise TypeError(
            "tensors must be a non-empty iterable of names"
        ) from None
    if not names:
        raise ValueError("tensors must contain at least one name")
    if any(not isinstance(name, str) for name in names):
        raise TypeError("tensor names must be strings")
    if len(names) != len(set(names)):
        raise ValueError("tensor names must be unique")
    return names


def _tensor_slices(value) -> tuple[tuple[str, int, int], ...]:
    if not isinstance(value, Mapping):
        raise TypeError(
            "slices must be a non-empty mapping of tensor names to ranges"
        )
    if not value:
        raise ValueError("slices must contain at least one tensor")
    result = []
    for name, bounds in value.items():
        if not isinstance(name, str):
            raise TypeError("tensor slice names must be strings")
        start, stop = _selector_ints(bounds, 2, f"slice for {name!r}")
        if start < 0 or start >= stop:
            raise ValueError(
                f"slice for {name!r} must satisfy 0 <= start < stop"
            )
        result.append((name, start, stop))
    return tuple(result)


def colmap_database_conversion_report(
    database: ColmapDatabase,
    *,
    profile: str,
) -> ColmapDatabaseConversionReport:
    """Analyze an exact COLMAP database target without opening a path."""

    if profile not in _EXACT_COLMAP_DB_PROFILES:
        raise ValueError(
            f"COLMAP database writer: unknown target profile {profile!r}"
        )
    raw = _core._colmap_db_conversion_report(database, profile)
    changes = raw["identity_changes"]
    order = ("profile", "application_id", "user_version")
    return ColmapDatabaseConversionReport(
        source_profile=raw["source_profile"],
        target_profile=raw["target_profile"],
        writable=raw["writable"],
        identity_changes=tuple(
            (name, changes[name][0], changes[name][1])
            for name in order
            if name in changes
        ),
        incompatibilities=tuple(raw["incompatibilities"]),
    )


def write_colmap_db(
    database: ColmapDatabase,
    path,
    *,
    profile: str,
) -> None:
    """Write one explicitly selected exact COLMAP SQLite profile."""

    try:
        if profile not in _EXACT_COLMAP_DB_PROFILES:
            raise ValueError(
                f"COLMAP database writer: unknown target profile {profile!r}"
            )
        _core.write_colmap_db(database, str(path), profile=profile)
    except Exception as exc:
        raise FormatError(
            f"writing {str(path)!r} as colmap_db profile {profile!r}: {exc}"
        ) from exc


def write(
    obj,
    path,
    *,
    format: str | None = None,
    profile: str | None = None,
) -> None:
    """Write a record to ``path``, dispatching on ``format``, the object
    type, and the extension.

    Single-file codecs write their C++ encoder buffer directly to the file
    without materializing a second output-sized Python ``bytes`` object. The
    file opens lazily after validation and encoding, so a rejected record does
    not truncate an existing destination. ``profile`` selects an exact
    COLMAP SQLite schema and is rejected for every other format. Omitting it
    preserves an exact profile carried by a decoded database; constructed
    hybrid records retain the established hybrid-writer behavior.
    """
    fmt = format or _detect_write(obj, path)
    codec = get(fmt)
    if codec.write is None:
        raise FormatError(f"format {fmt!r} is read-only (no writer)")
    if profile is not None and fmt != "colmap_db":
        raise FormatError(
            "profile is supported only when writing format 'colmap_db'"
        )
    if (
        profile is not None
        and fmt == "colmap_db"
        and profile not in _EXACT_COLMAP_DB_PROFILES
    ):
        raise FormatError(
            f"COLMAP database writer: unknown target profile {profile!r}"
        )
    try:
        selected_profile = profile
        if (
            selected_profile is None
            and fmt == "colmap_db"
            and getattr(obj, "profile", None) in _EXACT_COLMAP_DB_PROFILES
        ):
            selected_profile = obj.profile
        if selected_profile is None:
            codec.write(obj, str(path))
        else:
            codec.write(obj, str(path), profile=selected_profile)
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(f"writing {str(path)!r} as {fmt!r}: {exc}") from exc


def codecs() -> dict[str, Codec]:
    """The registered codecs, keyed by format id."""
    return dict(REGISTRY)


def capabilities(
    format: str | None = None,
) -> CodecCapabilities | dict[str, CodecCapabilities]:
    """Return immutable discovery metadata for one or every registered codec.

    The no-argument form returns a new dictionary, so changing the mapping
    cannot mutate the registry. Each :class:`CodecCapabilities` value is frozen.
    """

    if format is not None:
        return get(format).capabilities()
    return {format_id: codec.capabilities() for format_id, codec in REGISTRY.items()}


def native_features(
    name: str | None = None,
) -> NativeFeatureCapabilities | dict[str, NativeFeatureCapabilities]:
    """Return compiled-state metadata for optional native integrations.

    Known integrations remain present with ``available=False`` when the
    extension was built without their ``SCENEIO_WITH_*`` option. The
    no-argument mapping is detached and its values are frozen.
    """

    return native_feature_capabilities(name)


def _detect_write(obj, path) -> str:
    # dispatch by extension (or directory) first, then disambiguate on the
    # record type if several writable codecs share an extension. Compound
    # extensions (notably `.compressed.ply`) outrank their shorter suffix.
    name = Path(path).name
    lower_name = name.lower()
    extension_matches = {
        c.id: max(
            (
                len(extension)
                for extension in c.extensions
                if lower_name.endswith(extension.lower())
            ),
            default=0,
        )
        for c in REGISTRY.values()
        if c.write is not None
    }
    longest_extension = max(extension_matches.values(), default=0)
    cands = [
        c
        for c in REGISTRY.values()
        if c.write is not None
        and (
            (
                longest_extension
                and extension_matches.get(c.id) == longest_extension
            )
            or name in c.filenames
            or (c.is_directory and Path(path).suffix == "")
        )
    ]
    if not cands:
        ext = Path(path).suffix.lower()
        raise FormatError(
            f"no writer for {type(obj).__name__} at {str(path)!r} "
            f"(ext {ext!r})"
        )
    if len(cands) > 1:
        for c in cands:
            if c.record is type(obj):
                return c.id
    return cands[0].id


__all__ = [
    "ArrayInspection",
    "Camera",
    "CameraRig",
    "Codec",
    "CodecCapabilities",
    "ColmapDatabase",
    "ColmapDatabaseConversionReport",
    "ColmapMarkerSet",
    "ColmapMaxxSchemaInfo",
    "ColmapPosePriorSet",
    "ColmapRigFrameSet",
    "ColmapVideoMetadataSet",
    "ConsistencyGraph",
    "DepthEncoding",
    "DepthMap",
    "FeatureSet",
    "FlowField",
    "FormatError",
    "GaussianCloud",
    "HlocFeatureStore",
    "HlocMatchStore",
    "Image",
    "ImageSequence",
    "Inspection",
    "MatchGraph",
    "MaterialSet",
    "Mesh",
    "MeshScene",
    "NativeFeatureCapabilities",
    "NormalMap",
    "PointCloud",
    "PointVisibility",
    "PoseGraph",
    "PosedViewSet",
    "Reconstruction",
    "StateTrajectory",
    "TensorDict",
    "capabilities",
    "codecs",
    "colmap_database_conversion_report",
    "detect",
    "inspect",
    "inspect_depth",
    "inspect_flow",
    "native_features",
    "read",
    "read_depth",
    "read_flow",
    "read_partial",
    "register",
    "write",
    "write_colmap_db",
    "write_depth",
    "write_flow",
    "write_zarr",
]
