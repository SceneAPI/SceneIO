"""Codec registry — the single place a format is wired into ``sceneio.io``.

Each :class:`Codec` binds a format id to its file extensions, a magic-byte
sniff, a reader, an optional writer, the record type it yields, and the
DataType it serializes. ``read()`` / ``write()`` / ``detect()`` dispatch
through this registry, so **adding a format is one** :func:`register` call
(plus the compiled codec). See ``docs/core_architecture.md``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.errors import SceneIoError
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS, FAMILY_MEMBERS
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._inspection import inspect_codec
from sceneio.io._ply import classify_ply
from sceneio.io._registry import adapters as _shared_adapters
from sceneio.io._registry import model as _shared_model
from sceneio.io._registry import native_features as _shared_native_features
from sceneio.io._registry.detection import detect_path as _detect_path
from sceneio.io._registry.families.calibration import CALIBRATION_CODECS
from sceneio.io._registry.families.images import IMAGE_CODECS
from sceneio.io._registry.families.meshes import MESH_CODECS
from sceneio.io._registry.families.sequences import build_sequence_codecs

Codec = _shared_model.Codec
CodecCapabilities = _shared_model.CodecCapabilities
NativeFeatureCapabilities = _shared_model.NativeFeatureCapabilities
_array_window_reader = _shared_adapters._array_window_reader
_bytes_reader = _shared_adapters._bytes_reader
_file_sink_writer = _shared_adapters._file_sink_writer
_mmap_reader = _shared_adapters._mmap_reader
_mmap_selector_reader = _shared_adapters._mmap_selector_reader
_mmap_view_reader = _shared_adapters._mmap_view_reader
_NATIVE_FEATURE_FORMATS = _shared_native_features.NATIVE_FEATURE_FORMATS
_native_feature_snapshots = _shared_native_features.native_feature_snapshots


class FormatError(SceneIoError):
    """A file could not be detected, read, or written in its format."""


def native_feature_capabilities(
    name: str | None = None,
) -> NativeFeatureCapabilities | dict[str, NativeFeatureCapabilities]:
    """Return immutable compiled-state metadata for optional native features."""

    return _native_feature_snapshots(
        getattr(_core, "__native_features__", ()),
        name,
        unknown_feature=lambda feature: FormatError(
            f"unknown native feature {feature!r}"
        ),
    )


REGISTRY: dict[str, Codec] = {}


def register(codec: Codec) -> Codec:
    if codec.id in REGISTRY:
        raise ValueError(f"codec id already registered: {codec.id!r}")
    REGISTRY[codec.id] = codec
    return codec


def _install_builtin_family(
    codecs: tuple[Codec, ...],
    expected_ids: tuple[str, ...],
) -> None:
    """Validate one complete built-in family before installing any member."""

    definitions = tuple(codecs)
    if any(type(codec) is not Codec for codec in definitions):
        raise TypeError("built-in family entries must be Codec instances")
    actual_ids = tuple(codec.id for codec in definitions)
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError(f"built-in family ids must be unique: {actual_ids!r}")
    if actual_ids != tuple(expected_ids):
        raise ValueError(
            f"built-in family ids {actual_ids!r} do not match {tuple(expected_ids)!r}"
        )
    collisions = tuple(format_id for format_id in actual_ids if format_id in REGISTRY)
    if collisions:
        raise ValueError(f"built-in codec ids already registered: {collisions!r}")
    for codec in definitions:
        REGISTRY[codec.id] = codec


def get(format_id: str) -> Codec:
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
        format_error=FormatError,
    )


def _inspect_registered_path(path: str | Path):
    """Inspect through this registry without importing the public I/O facade."""

    fmt = detect(path)
    codec = get(fmt)
    try:
        return inspect_codec(path, fmt, codec.datatype, codec.inspect)
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(f"inspecting {str(path)!r} as {fmt!r}: {exc}") from exc


def _registered_image_extensions() -> frozenset[str]:
    return frozenset(
        extension
        for codec in REGISTRY.values()
        if codec.record is _core.Image
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
        return _core.read_sog_directory_points(
            str(_sog_metadata_path(path)), start, stop
        )
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
register(
    Codec(
        "pfm",
        (".pfm",),
        _mmap_reader(_core.read_pfm),
        _file_sink_writer(_core.write_pfm, prepare=_canon),
        record=None,
        datatype="depth_map",
        magic=(b"PF", b"Pf"),
        read_window=_mmap_selector_reader(_core.read_pfm_window),
        supported_features=(
            "grayscale",
            "rgb",
            "float32",
            "little_endian",
            "big_endian",
            "typed_depth_adapter",
        ),
        unsupported_features=("native_positive_stride_mmap_view",),
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
        read_image=_core.read_colmap_sparse_image,
        supported_features=("cameras", "images", "points3D", "tracks"),
    )
)
register(
    Codec(
        "gaussian_ply",
        (".ply",),
        _mmap_reader(_core.read_gaussian_ply),
        _file_sink_writer(_core.write_gaussian_ply),
        record=_core.GaussianCloud,
        datatype="splat",
        magic=(b"ply",),
        read_points=_mmap_selector_reader(_core.read_gaussian_ply_points),
    )
)
register(
    Codec(
        "compressed_ply",
        (".compressed.ply",),
        _mmap_reader(_core.read_compressed_ply),
        _file_sink_writer(_core.write_compressed_ply),
        record=_core.GaussianCloud,
        datatype="splat",
        magic=(b"ply",),
        read_points=_mmap_selector_reader(
            _core.read_compressed_ply_points
        ),
        lossy=True,
        supported_features=(
            "playcanvas_chunk_256",
            "legacy_direct_color_read",
            "position_11_10_11",
            "scale_11_10_11",
            "largest_three_quaternion",
            "rgba8",
            "sh_degrees_0_3",
            "morton_ordered_write",
        ),
        unsupported_features=(
            "ascii",
            "binary_big_endian",
            "unknown_elements",
            "unknown_properties",
        ),
    )
)
register(
    Codec(
        "sog",
        (".sog",),
        _sog_reader,
        _sog_writer,
        record=_core.GaussianCloud,
        datatype="splat",
        filenames=("meta.json",),
        is_directory=True,
        dir_marker="meta.json",
        read_points=_sog_point_reader,
        lossy=True,
        container_kind="multi_file",
        supported_features=(
            "playcanvas_v2",
            "bundled_zip",
            "unbundled_directory",
            "lossless_webp_layers",
            "position_16bit_log",
            "largest_three_quaternion",
            "shared_scale_dc_codebooks",
            "sh_degrees_0_3",
            "sh_palette",
            "morton_ordered_write",
        ),
        unsupported_features=(
            "legacy_v1",
            "lossy_webp_layers",
            "streamed_lod",
            "unknown_layers",
        ),
    )
)
register(
    Codec(
        "ksplat",
        (".ksplat",),
        _mmap_reader(_core.read_ksplat),
        _file_sink_writer(_core.write_ksplat),
        record=_core.GaussianCloud,
        datatype="splat",
        read_points=_mmap_selector_reader(_core.read_ksplat_points),
        lossy=True,
        supported_features=(
            "mkkellogg_v0_1",
            "compression_levels_0_2",
            "float16_scale_rotation",
            "bucketed_position_uint16",
            "rgba8",
            "sh_degrees_0_2",
            "sh_uint8_level_2",
            "multi_section_read",
            "deterministic_single_section_write",
        ),
        unsupported_features=(
            "sh_degree_3",
            "unknown_versions",
            "streamed_lod",
        ),
    )
)
_install_builtin_family(
    MESH_CODECS,
    FAMILY_MEMBERS["meshes"],
)
register(
    Codec(
        "ply",
        (".ply",),
        _mmap_reader(_core.read_ply),
        _file_sink_writer(_core.write_ply),
        record=_core.PointCloud,
        datatype="point_cloud",
        read_points=_mmap_selector_reader(_core.read_ply_points),
        supported_features=(
            "ascii",
            "binary_little_endian",
            "binary_big_endian",
            "standard_scalar_types_read",
            "normals",
            "rgb8",
            "rgb16",
            "intensity",
        ),
        unsupported_features=(
            "vertex_lists",
            "unknown_vertex_properties",
            "non_vertex_elements",
            "ascii_point_ranges",
        ),
    )
)
register(
    Codec(
        "pcd",
        (".pcd",),
        _mmap_reader(_core.read_pcd),
        _file_sink_writer(_core.write_pcd),
        record=_core.PointCloud,
        datatype="point_cloud",
        magic=(b"# .PCD",),
        read_points=_mmap_selector_reader(_core.read_pcd_points),
        supported_features=(
            "pcd_0_7",
            "ascii",
            "binary",
            "binary_compressed",
            "organized",
            "viewpoint",
            "standard_scalar_types_read",
            "normals",
            "packed_rgb8",
            "intensity",
        ),
        unsupported_features=(
            "unknown_fields",
            "multi_count_fields",
            "rgb16",
            "ascii_point_ranges",
            "compressed_point_ranges",
        ),
    )
)
register(
    Codec(
        "spz",
        (".spz",),
        _mmap_reader(_core.read_spz),
        _file_sink_writer(_core.write_spz),
        record=_core.GaussianCloud,
        datatype="splat",
        magic=(b"\x1f\x8b", b"NGSP"),
        lossy=True,
        supported_features=("v1_read", "v2_read", "v3_read_write", "v4_read_write"),
    )
)
# Camera-pose formats -> PosedViewSet. `datatype` here is informational; a
# vocabulary id is pending, like `splat` (see formats/datatypes.py). TUM/KITTI
# claim no extension (`.txt` is ambiguous) so they are explicit-`format=` only.
register(
    Codec(
        "transforms_json",
        (),
        _mmap_reader(_core.read_transforms_json),
        _file_sink_writer(_core.write_transforms_json),
        record=_core.PosedViewSet,
        datatype="posed_views",
        filenames=("transforms.json",),
    )
)
register(
    Codec(
        "tum",
        (),
        _mmap_reader(_core.read_tum),
        _file_sink_writer(_core.write_tum),
        record=_core.PosedViewSet,
        datatype="posed_views",
    )
)
register(
    Codec(
        "kitti",
        (),
        _mmap_reader(_core.read_kitti),
        _file_sink_writer(_core.write_kitti),
        record=_core.PosedViewSet,
        datatype="posed_views",
    )
)
register(
    Codec(
        "euroc_state",
        (),
        _mmap_reader(_core.read_euroc_state),
        _file_sink_writer(_core.write_euroc_state),
        record=_core.StateTrajectory,
        datatype="state_trajectory",
        magic=(b"#timestamp [ns],",),
        read_states=_mmap_selector_reader(
            _core.read_euroc_state_states
        ),
        supported_features=(
            "int64_nanosecond_timestamps",
            "position",
            "wxyz_orientation",
            "velocity",
            "gyroscope_bias",
            "accelerometer_bias",
            "state_ranges",
        ),
    )
)
_install_builtin_family(
    CALIBRATION_CODECS,
    FAMILY_MEMBERS["calibration"],
)
register(
    Codec(
        "g2o",
        (".g2o",),
        _mmap_reader(_core.read_g2o),
        _file_sink_writer(_core.write_g2o),
        record=_core.PoseGraph,
        datatype="pose_graph",
        magic=(
            b"# g2o pose graph",
            b"VERTEX_SE3:QUAT",
            b"EDGE_SE3:QUAT",
        ),
        supported_features=(
            "vertex_se3_quat",
            "edge_se3_quat",
            "fixed_vertices",
            "symmetric_information_6x6",
        ),
        unsupported_features=(
            "mixed_vertex_types",
            "mixed_edge_types",
            "parameters",
            "robust_kernels",
        ),
    )
)
register(
    Codec(
        "colmap_db",
        (".db",),
        _core.read_colmap_db,
        _core.write_colmap_db,
        record=_core.ColmapDatabase,
        datatype="match_graph",
        magic=(b"SQLite format 3\x00",),
        filenames=("database.db",),
        read_image=_core.read_colmap_db_image,
        read_pair=_core.read_colmap_db_pair,
        supported_features=(
            "cameras",
            "images",
            "keypoints_2_4_6",
            "uint8_descriptors",
            "extractor_type",
            "raw_matches",
            "verified_matches",
            "F_E_H",
            "relative_pose",
            "sparse_ids",
            "read_only_reads",
            "transactional_writes",
        ),
        unsupported_features=(
            "rigs",
            "frames",
            "pose_priors",
            "scores",
            "float_descriptors",
            "fork_extension_tables",
        ),
    )
)
# Array / tensor + raster-image formats (Tier-1, zero-dep). datatype ids are
# informational (vocabulary registration is Phase-C, like posed_views).
register(
    Codec(
        "npy",
        (".npy",),
        _mmap_view_reader(_core.read_npy_view, _core.read_npy),
        _file_sink_writer(_core.write_npy, prepare=_canon),
        record=None,
        datatype="tensor",
        magic=(b"\x93NUMPY",),
        supported_features=("v1", "c_order", "native_endian_mmap_view"),
        unsupported_features=("fortran_order", "object_dtype"),
    )
)
register(
    Codec(
        "npz",
        (".npz",),
        _mmap_reader(_core.read_npz),
        _file_sink_writer(_core.write_npz, prepare=_prepare_tensor_dict),
        record=_core.TensorDict,
        datatype="tensor_dict",
        supported_features=("stored", "deflate", "numeric_dtypes"),
        unsupported_features=("object_dtype",),
    )
)
register(
    Codec(
        "safetensors",
        (".safetensors",),
        _mmap_view_reader(
            _core.read_safetensors_view,
            _core.read_safetensors,
        ),
        _file_sink_writer(
            _core.write_safetensors,
            prepare=_prepare_tensor_dict,
        ),
        record=_core.TensorDict,
        datatype="tensor_dict",
        read_tensors=_mmap_view_reader(
            _core.read_safetensors_tensors_view,
            _core.read_safetensors_tensors,
        ),
        read_slices=_mmap_view_reader(
            _core.read_safetensors_slices_view,
            _core.read_safetensors_slices,
        ),
        supported_features=(
            "metadata",
            "bool",
            "signed_integers",
            "unsigned_integers",
            "float16",
            "float32",
            "float64",
            "mmap_views",
            "leading_axis_slices",
        ),
        unsupported_features=(
            "bfloat16",
            "float8",
            "complex64",
            "sub_byte_dtypes",
            "strided_tensors",
        ),
    )
)
_install_builtin_family(
    IMAGE_CODECS,
    FAMILY_MEMBERS["images"],
)
_IMAGE_FRAME_ACCESS = ImageFrameAccess(
    extensions=_registered_image_extensions,
    inspect=_inspect_registered_path,
)
_install_builtin_family(
    build_sequence_codecs(_IMAGE_FRAME_ACCESS),
    FAMILY_MEMBERS["sequences"],
)
# COLMAP text sparse (cameras.txt/images.txt/points3D.txt) — the text twin of
# colmap_sparse; a directory format distinguished by its cameras.txt marker.
register(
    Codec(
        "colmap_sparse_txt",
        (),
        _core.read_colmap_txt,
        _core.write_colmap_txt,
        record=_core.Reconstruction,
        datatype="sparse_model",
        is_directory=True,
        dir_marker="cameras.txt",
        read_image=_core.read_colmap_txt_image,
        supported_features=("cameras", "images", "points3D", "tracks"),
    )
)
register(
    Codec(
        "xyz",
        (".xyz",),
        _mmap_reader(_core.read_xyz),
        _file_sink_writer(_core.write_xyz),
        record=_core.PointCloud,
        datatype="point_cloud",
        read_points=_mmap_selector_reader(_core.read_xyz_points),
    )
)
register(
    Codec(
        "pts",
        (".pts",),
        _mmap_reader(_core.read_pts),
        _file_sink_writer(_core.write_pts),
        record=_core.PointCloud,
        datatype="point_cloud",
        read_points=_mmap_selector_reader(_core.read_pts_points),
        supported_features=(
            "count_header",
            "xyz",
            "intensity",
            "rgb8",
        ),
        unsupported_features=("normals", "rgb16", "georef"),
    )
)
# ASPRS LAS (hand-parsed binary, no library) -> PointCloud. The "LASF"
# signature is unambiguous. Waveform formats retain their descriptor VLRs,
# raw point fields, and internal packet EVLR in a lossless sidecar.
register(
    Codec(
        "las",
        (".las",),
        _mmap_reader(_core.read_las),
        _file_sink_writer(_core.write_las),
        record=_core.PointCloud,
        datatype="point_cloud",
        magic=(b"LASF",),
        read_points=_mmap_selector_reader(_core.read_las_points),
        lossy=True,
        supported_features=(
            "point_formats_0_5",
            "point_formats_6_10",
            "waveform_sidecar",
            "rgb16",
            "georef",
        ),
        unsupported_features=("external_waveform_packets", "laz"),
    )
)
# LASzip-compatible LAZ through pinned LAZperf. The decoded PointCloud model
# intentionally keeps only coordinates, intensity, and RGB; formats carrying
# GPS time or NIR therefore advertise a lossy projection.
register(
    Codec(
        "laz",
        (".laz",),
        _mmap_reader(_core.read_laz),
        _file_sink_writer(_core.write_laz),
        record=_core.PointCloud,
        datatype="point_cloud",
        read_points=_mmap_selector_reader(_core.read_laz_points),
        lossy=True,
        supported_features=(
            "point_formats_0_3",
            "point_formats_6_8",
            "chunked_point_ranges",
            "rgb16",
            "georef",
        ),
        unsupported_features=(
            "point_formats_4_5",
            "point_formats_9_10",
            "waveform",
            "extra_bytes",
            "vlr_metadata",
        ),
    )
)
register(
    Codec(
        "flo",
        (".flo",),
        _mmap_view_reader(_core.read_flo_view, _core.read_flo),
        _file_sink_writer(_core.write_flo, prepare=_canon),
        record=None,
        datatype="flow",
        magic=(b"PIEH",),
        read_window=_array_window_reader(
            _mmap_view_reader(_core.read_flo_view, _core.read_flo)
        ),
        supported_features=(
            "float32",
            "native_endian_mmap_view",
            "typed_flow_adapter",
        ),
    )
)
register(
    Codec(
        "dmb",
        (".dmb",),
        _mmap_reader(_core.read_dmb),
        _file_sink_writer(_core.write_dmb),
        record=_core.DepthMap,
        datatype="depth_map",
        read_window=_mmap_selector_reader(_core.read_dmb_window),
        supported_features=(
            "scalar_float32",
            "little_endian",
            "zero_invalid",
            "pixel_windows",
        ),
        unsupported_features=(
            "normal_maps",
            "confidence",
            "embedded_scale",
        ),
    )
)
# SfM pose formats -> Reconstruction (convention-converted to WXYZ/world_to_camera).
register(
    Codec(
        "bundler",
        (".out",),
        _mmap_reader(_core.read_bundler),
        _file_sink_writer(_core.write_bundler),
        record=_core.Reconstruction,
        datatype="sparse_model",
        magic=(b"# Bundle file",),
    )
)
register(
    Codec(
        "bal",
        (".bal",),
        _mmap_reader(_core.read_bal),
        _file_sink_writer(_core.write_bal),
        record=_core.Reconstruction,
        datatype="sparse_model",
        supported_features=(
            "angle_axis",
            "radial_k1_k2",
            "centered_observations",
            "deterministic_17_digit_writer",
        ),
        unsupported_features=(
            "bzip2",
            "image_names",
            "image_dimensions",
            "principal_points",
            "point_colors",
            "point_errors",
            "untriangulated_observations",
        ),
    )
)
register(
    Codec(
        "nvm",
        (".nvm",),
        _mmap_reader(_core.read_nvm),
        _file_sink_writer(_core.write_nvm),
        record=_core.Reconstruction,
        datatype="sparse_model",
        magic=(b"NVM_V3",),
    )
)
register(
    Codec(
        "openmvg",
        (),
        _mmap_reader(_core.read_openmvg),
        _file_sink_writer(_core.write_openmvg),
        record=_core.Reconstruction,
        datatype="sparse_model",
        filenames=("sfm_data.json",),
    )
)
# antimatter15 .splat -> GaussianCloud. Headerless (no magic), so ext-only; a
# down-converted, web-viewer sibling of spz (both carry the `splat` datatype).
register(
    Codec(
        "splat",
        (".splat",),
        _mmap_reader(_core.read_splat),
        _file_sink_writer(_core.write_splat),
        record=_core.GaussianCloud,
        datatype="splat",
        read_points=_mmap_selector_reader(_core.read_splat_points),
        lossy=True,
        supported_features=("rgb8", "opacity8", "scale8", "quaternion8"),
        unsupported_features=("spherical_harmonics",),
    )
)

# This immutable tuple is the repository-owned completeness boundary.  The
# mutable REGISTRY remains the public extension point and may contain
# third-party codecs registered later.
if tuple(REGISTRY) != CANONICAL_BUILTIN_IDS:
    raise RuntimeError("built-in codec registration order differs from its manifest")
BUILTIN_DEFINITIONS: tuple[Codec, ...] = tuple(
    REGISTRY[format_id] for format_id in CANONICAL_BUILTIN_IDS
)
