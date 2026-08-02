"""Immutable ownership metadata for SceneIO's repository-owned codecs.

This module deliberately describes ownership only.  Runtime dispatch remains
defined by :class:`sceneio.io.registry.Codec`; keeping the two concerns
separate lets repository checks reason about built-ins without changing the
public registration contract or excluding third-party registrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class BuiltinOwnership:
    """Repository ownership for one built-in format implementation."""

    id: str
    family: str
    implementation_owner: str
    native_symbols: tuple[str, ...]
    python_symbols: tuple[str, ...] = ()


CANONICAL_BUILTIN_IDS = (
    "pfm",
    "colmap_sparse",
    "gaussian_ply",
    "compressed_ply",
    "sog",
    "ksplat",
    "ply_mesh",
    "obj",
    "stl",
    "off",
    "gltf",
    "glb",
    "usd",
    "usdz",
    "ply",
    "pcd",
    "spz",
    "transforms_json",
    "tum",
    "kitti",
    "euroc_state",
    "opencv_yaml",
    "opencv_xml",
    "ros_camera_info",
    "kalibr",
    "g2o",
    "colmap_db",
    "npy",
    "npz",
    "safetensors",
    "netpbm",
    "png",
    "jpeg",
    "bmp",
    "tga",
    "hdr",
    "exr",
    "webp",
    "avif",
    "y4m",
    "webm",
    "theora",
    "animated_webp",
    "apng",
    "animated_avif",
    "rtmv",
    "image_sequence",
    "colmap_sparse_txt",
    "xyz",
    "pts",
    "las",
    "laz",
    "flo",
    "dmb",
    "bundler",
    "bal",
    "nvm",
    "openmvg",
    "splat",
    "colmap_mvs_depth",
    "colmap_mvs_normal",
    "colmap_mvs_consistency",
    "colmap_fused_visibility",
    "hdf5",
    "hloc_features",
    "hloc_matches",
    "ncore_v4",
    "zarr",
    "tiff",
    "e57",
    "parquet",
    "arrow_ipc",
    "openvdb",
)

FAMILY_MEMBERS = MappingProxyType(
    {
        "arrays": ("pfm", "npy", "npz", "safetensors", "flo", "dmb"),
        "calibration": (
            "opencv_yaml",
            "opencv_xml",
            "ros_camera_info",
            "kalibr",
        ),
        "containers": (
            "hdf5",
            "hloc_features",
            "hloc_matches",
            "zarr",
            "parquet",
            "arrow_ipc",
            "openvdb",
        ),
        "dense": (
            "colmap_mvs_depth",
            "colmap_mvs_normal",
            "colmap_mvs_consistency",
            "colmap_fused_visibility",
        ),
        "datasets": ("ncore_v4",),
        "images": (
            "netpbm",
            "png",
            "jpeg",
            "bmp",
            "tga",
            "hdr",
            "exr",
            "webp",
            "avif",
            "tiff",
        ),
        "meshes": (
            "ply_mesh",
            "obj",
            "stl",
            "off",
            "gltf",
            "glb",
            "usd",
            "usdz",
        ),
        "points": ("ply", "pcd", "xyz", "pts", "las", "laz", "e57"),
        "reconstruction": (
            "colmap_sparse",
            "transforms_json",
            "tum",
            "kitti",
            "euroc_state",
            "g2o",
            "colmap_db",
            "colmap_sparse_txt",
            "bundler",
            "bal",
            "nvm",
            "openmvg",
        ),
        "sequences": (
            "y4m",
            "webm",
            "theora",
            "animated_webp",
            "apng",
            "animated_avif",
            "rtmv",
            "image_sequence",
        ),
        "splats": (
            "gaussian_ply",
            "compressed_ply",
            "sog",
            "ksplat",
            "spz",
            "splat",
        ),
    }
)

_NATIVE_SYMBOLS = {
    "pfm": ("_inspect_pfm", "read_pfm", "write_pfm", "read_pfm_window"),
    "colmap_sparse": (
        "read_colmap_sparse",
        "write_colmap_sparse",
        "read_colmap_sparse_image",
    ),
    "gaussian_ply": (
        "read_gaussian_ply",
        "write_gaussian_ply",
        "read_gaussian_ply_points",
    ),
    "compressed_ply": (
        "read_compressed_ply",
        "write_compressed_ply",
        "read_compressed_ply_points",
    ),
    "sog": (
        "_inspect_sog_metadata",
        "read_sog",
        "write_sog",
        "read_sog_points",
        "read_sog_directory",
        "write_sog_directory",
        "read_sog_directory_points",
    ),
    "ksplat": (
        "_inspect_ksplat_metadata",
        "read_ksplat",
        "write_ksplat",
        "read_ksplat_points",
    ),
    "ply_mesh": ("read_ply_mesh", "write_ply_mesh", "read_ply_mesh_faces"),
    "obj": (
        "obj_material_library",
        "read_obj",
        "write_obj",
        "write_mtl",
        "inspect_obj",
        "inspect_mtl",
    ),
    "stl": ("_inspect_stl", "read_stl", "write_stl", "read_stl_faces"),
    "off": ("_inspect_off", "read_off", "write_off", "read_off_faces"),
    "gltf": (
        "gltf_external_buffer_uris",
        "read_gltf",
        "write_gltf",
        "_write_gltf_to_files",
        "inspect_gltf",
        "read_gltf_mesh",
        "read_gltf_primitive",
    ),
    "glb": (
        "read_glb",
        "write_glb",
        "inspect_glb",
        "read_glb_mesh",
        "read_glb_primitive",
    ),
    "usd": (),
    "usdz": (),
    "ply": ("read_ply", "write_ply", "read_ply_points"),
    "pcd": ("read_pcd", "write_pcd", "read_pcd_points"),
    "spz": ("read_spz", "write_spz"),
    "transforms_json": (
        "_inspect_transforms_json",
        "read_transforms_json",
        "write_transforms_json",
    ),
    "tum": ("read_tum", "write_tum"),
    "kitti": ("read_kitti", "write_kitti"),
    "euroc_state": (
        "_inspect_euroc_state",
        "read_euroc_state",
        "write_euroc_state",
        "read_euroc_state_states",
    ),
    "opencv_yaml": (
        "_inspect_opencv_yaml",
        "read_opencv_yaml",
        "write_opencv_yaml",
    ),
    "opencv_xml": (
        "_inspect_opencv_xml",
        "read_opencv_xml",
        "write_opencv_xml",
    ),
    "ros_camera_info": (
        "_inspect_ros_camera_info",
        "read_ros_camera_info",
        "write_ros_camera_info",
    ),
    "kalibr": ("_inspect_kalibr", "read_kalibr", "write_kalibr"),
    "g2o": ("_inspect_g2o", "read_g2o", "write_g2o"),
    "colmap_db": (
        "inspect_colmap_db",
        "read_colmap_db",
        "write_colmap_db",
        "read_colmap_db_image",
        "read_colmap_db_pair",
    ),
    "npy": ("_inspect_npy", "read_npy", "read_npy_view", "write_npy"),
    "npz": ("read_npz", "write_npz"),
    "safetensors": (
        "_inspect_safetensors",
        "read_safetensors",
        "read_safetensors_view",
        "write_safetensors",
        "read_safetensors_tensors",
        "read_safetensors_tensors_view",
        "read_safetensors_slices",
        "read_safetensors_slices_view",
    ),
    "netpbm": ("read_netpbm", "write_netpbm", "read_netpbm_window"),
    "png": ("read_png", "write_png"),
    "jpeg": ("read_jpeg", "write_jpeg"),
    "bmp": ("_inspect_bmp", "read_bmp", "write_bmp"),
    "tga": ("_inspect_tga", "read_tga", "write_tga"),
    "hdr": ("read_hdr", "write_hdr"),
    "exr": ("read_exr", "write_exr"),
    "tiff": (),
    "e57": (),
    "parquet": (),
    "arrow_ipc": (),
    "openvdb": (),
    "webp": ("read_webp", "write_webp", "read_webp_window"),
    "avif": (),
    "y4m": ("_inspect_y4m", "read_y4m", "write_y4m", "read_y4m_frames"),
    "webm": (
        "_inspect_webm",
        "read_webm",
        "write_webm",
        "write_webm_temporal",
        "read_webm_frames",
    ),
    "theora": (
        "_inspect_theora",
        "read_theora",
        "write_theora",
        "read_theora_frames",
    ),
    "animated_webp": (
        "_inspect_animated_webp",
        "read_animated_webp",
        "write_animated_webp",
    ),
    "apng": ("_inspect_apng", "read_apng", "write_apng"),
    "animated_avif": (),
    "rtmv": (),
    "image_sequence": ("image_sequence_paths",),
    "colmap_sparse_txt": (
        "_inspect_colmap_txt",
        "read_colmap_txt",
        "write_colmap_txt",
        "read_colmap_txt_image",
    ),
    "xyz": (
        "_inspect_xyz",
        "_inspect_xyz_file",
        "read_xyz",
        "write_xyz",
        "read_xyz_points",
    ),
    "pts": ("_inspect_pts", "read_pts", "write_pts", "read_pts_points"),
    "las": ("read_las", "write_las", "read_las_points"),
    "laz": ("read_laz", "write_laz", "read_laz_points"),
    "flo": ("read_flo", "read_flo_view", "write_flo"),
    "dmb": ("_inspect_dmb", "read_dmb", "write_dmb", "read_dmb_window"),
    "bundler": ("_inspect_bundler", "read_bundler", "write_bundler"),
    "bal": ("_inspect_bal", "read_bal", "write_bal"),
    "nvm": ("_inspect_nvm", "read_nvm", "write_nvm"),
    "openmvg": ("_inspect_openmvg", "read_openmvg", "write_openmvg"),
    "splat": ("read_splat", "write_splat", "read_splat_points"),
    "colmap_mvs_depth": (
        "_inspect_colmap_mvs_depth",
        "read_colmap_mvs_depth",
        "write_colmap_mvs_depth",
        "read_colmap_mvs_depth_window",
    ),
    "colmap_mvs_normal": (
        "_inspect_colmap_mvs_normal",
        "read_colmap_mvs_normal",
        "write_colmap_mvs_normal",
        "read_colmap_mvs_normal_window",
    ),
    "colmap_mvs_consistency": (
        "_inspect_colmap_mvs_consistency",
        "read_colmap_mvs_consistency",
        "write_colmap_mvs_consistency",
    ),
    "colmap_fused_visibility": (
        "_inspect_colmap_fused_visibility",
        "read_colmap_fused_visibility",
        "write_colmap_fused_visibility",
    ),
    "hdf5": (),
    "hloc_features": (),
    "hloc_matches": (),
    "ncore_v4": (),
    "zarr": (),
}

_PYTHON_SYMBOLS = {
    "sog": (
        "sceneio.io.registry._sog_reader",
        "sceneio.io.registry._sog_writer",
        "sceneio.io.registry._sog_point_reader",
    ),
    "obj": (
        "sceneio.io._obj.read_obj",
        "sceneio.io._obj.write_obj",
        "sceneio.io._obj.inspect_obj",
    ),
    "gltf": (
        "sceneio.io._gltf.read_gltf",
        "sceneio.io._gltf.write_gltf",
        "sceneio.io._gltf.inspect_gltf",
        "sceneio.io._gltf.read_gltf_mesh",
        "sceneio.io._gltf.read_gltf_primitive",
    ),
    "glb": (
        "sceneio.io._gltf.read_glb",
        "sceneio.io._gltf.write_glb",
        "sceneio.io._gltf.inspect_glb",
        "sceneio.io._gltf.read_glb_mesh",
        "sceneio.io._gltf.read_glb_primitive",
    ),
    "usd": (
        "sceneio.io._usd.read_usd",
        "sceneio.io._usd.write_usd",
        "sceneio.io._usd.inspect_usd",
    ),
    "usdz": (
        "sceneio.io._usd.read_usd",
        "sceneio.io._usd.write_usd",
        "sceneio.io._usd.inspect_usdz",
    ),
    "image_sequence": (
        "sceneio.io._image_sequence.read_image_sequence_directory",
        "sceneio.io._image_sequence.write_image_sequence_directory",
        "sceneio.io._image_sequence.inspect_image_sequence_directory",
        "sceneio.io._image_sequence.read_image_sequence_directory_frames",
    ),
    "avif": (
        "sceneio.io._avif.read_avif",
        "sceneio.io._avif.write_avif",
        "sceneio.io._avif.inspect_avif",
    ),
    "animated_avif": (
        "sceneio.io._avif.read_animated_avif",
        "sceneio.io._avif.write_animated_avif",
        "sceneio.io._avif.inspect_animated_avif",
        "sceneio.io._avif.read_animated_avif_frames",
    ),
    "rtmv": (
        "sceneio.io._rtmv.read_rtmv_directory",
        "sceneio.io._rtmv.inspect_rtmv_directory",
        "sceneio.io._rtmv.read_rtmv_directory_frames",
    ),
    "hdf5": (
        "sceneio.io._hdf5.read_hdf5",
        "sceneio.io._hdf5.write_hdf5",
        "sceneio.io._hdf5.inspect_hdf5",
        "sceneio.io._hdf5.read_hdf5_tensors",
        "sceneio.io._hdf5.read_hdf5_slices",
    ),
    "hloc_features": (
        "sceneio.io._hdf5.read_hloc_features",
        "sceneio.io._hdf5.write_hloc_features",
        "sceneio.io._hdf5.inspect_hloc_features",
    ),
    "hloc_matches": (
        "sceneio.io._hdf5.read_hloc_matches",
        "sceneio.io._hdf5.write_hloc_matches",
        "sceneio.io._hdf5.inspect_hloc_matches",
    ),
    "ncore_v4": (
        "sceneio.io._ncore.read_ncore_v4",
        "sceneio.io._ncore.write_ncore_v4",
        "sceneio.io._ncore.inspect_ncore_v4",
    ),
    "zarr": (
        "sceneio.io._zarr.read_zarr",
        "sceneio.io._zarr.write_zarr",
        "sceneio.io._zarr.inspect_zarr",
        "sceneio.io._zarr.read_zarr_tensors",
        "sceneio.io._zarr.read_zarr_slices",
    ),
    "tiff": (
        "sceneio.io._tiff.read_tiff",
        "sceneio.io._tiff.write_tiff",
        "sceneio.io._tiff.inspect_tiff",
    ),
    "e57": (
        "sceneio.io._e57.read_e57",
        "sceneio.io._e57.write_e57",
        "sceneio.io._e57.inspect_e57",
    ),
    "parquet": (
        "sceneio.io._arrow.read_parquet",
        "sceneio.io._arrow.write_parquet",
        "sceneio.io._arrow.inspect_parquet",
        "sceneio.io._arrow.read_parquet_tensors",
    ),
    "arrow_ipc": (
        "sceneio.io._arrow.read_arrow_ipc",
        "sceneio.io._arrow.write_arrow_ipc",
        "sceneio.io._arrow.inspect_arrow_ipc",
    ),
    "openvdb": (
        "sceneio.io._openvdb.read_openvdb",
        "sceneio.io._openvdb.write_openvdb",
        "sceneio.io._openvdb.inspect_openvdb",
    ),
}

_OWNERS = {
    "sog": "hybrid",
    "obj": "hybrid",
    "gltf": "hybrid",
    "glb": "hybrid",
    "usd": "python",
    "usdz": "python",
    "image_sequence": "python",
    "avif": "python",
    "animated_avif": "python",
    "rtmv": "python",
    "hdf5": "python",
    "hloc_features": "python",
    "hloc_matches": "python",
    "ncore_v4": "python",
    "zarr": "python",
    "tiff": "python",
    "e57": "python",
    "parquet": "python",
    "arrow_ipc": "python",
    "openvdb": "python",
}

_FAMILY_BY_ID = {
    format_id: family
    for family, format_ids in FAMILY_MEMBERS.items()
    for format_id in format_ids
}

BUILTIN_OWNERSHIP = MappingProxyType(
    {
        format_id: BuiltinOwnership(
            id=format_id,
            family=_FAMILY_BY_ID[format_id],
            implementation_owner=_OWNERS.get(format_id, "native"),
            native_symbols=_NATIVE_SYMBOLS[format_id],
            python_symbols=_PYTHON_SYMBOLS.get(format_id, ()),
        )
        for format_id in CANONICAL_BUILTIN_IDS
    }
)


def _validate_manifest() -> None:
    canonical = set(CANONICAL_BUILTIN_IDS)
    expected_families = {
        "arrays",
        "calibration",
        "containers",
        "dense",
        "datasets",
        "images",
        "meshes",
        "points",
        "reconstruction",
        "sequences",
        "splats",
    }
    if len(canonical) != len(CANONICAL_BUILTIN_IDS):
        raise RuntimeError("built-in codec ids must be unique")
    if set(FAMILY_MEMBERS) != expected_families:
        raise RuntimeError("built-in codec family taxonomy differs from its contract")
    family_ids = [
        format_id for members in FAMILY_MEMBERS.values() for format_id in members
    ]
    if len(family_ids) != len(set(family_ids)) or set(family_ids) != canonical:
        raise RuntimeError("codec families must partition the canonical built-ins")
    if (
        set(BUILTIN_OWNERSHIP) != canonical
        or set(_NATIVE_SYMBOLS) != canonical
        or not set(_PYTHON_SYMBOLS) <= canonical
        or not set(_OWNERS) <= canonical
    ):
        raise RuntimeError("built-in ownership metadata is incomplete")
    if any(
        item.id != format_id
        or item.implementation_owner not in {"native", "python", "hybrid"}
        for format_id, item in BUILTIN_OWNERSHIP.items()
    ):
        raise RuntimeError("built-in ownership metadata is inconsistent")
    for format_id, item in BUILTIN_OWNERSHIP.items():
        has_python_owner = bool(item.python_symbols)
        if item.implementation_owner == "native" and has_python_owner:
            raise RuntimeError(f"native codec {format_id!r} declares Python adapters")
        if item.implementation_owner in {"python", "hybrid"} and not has_python_owner:
            raise RuntimeError(f"{item.implementation_owner} codec {format_id!r} lacks Python adapters")


_validate_manifest()
