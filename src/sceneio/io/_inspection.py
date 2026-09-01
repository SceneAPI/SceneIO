"""Metadata-only inspection dispatch for SceneIO's built-in formats."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sceneio.io._inspectors import (
    arrays,
    calibration,
    images,
    meshes,
    points,
    reconstruction,
    sequences,
    splats,
)
from sceneio.io._inspectors.model import Inspection

type PathInspector = Callable[[Path, str], Inspection]
type FormatAwareInspector = Callable[[Path, str, str], Inspection]


_PATH_INSPECTORS: dict[str, PathInspector] = {
    "pfm": arrays.inspect_pfm,
    "npy": arrays.inspect_npy,
    "npz": arrays.inspect_npz,
    "safetensors": arrays.inspect_safetensors,
    "flo": arrays.inspect_flo,
    "dmb": arrays.inspect_dmb,
    "netpbm": images.inspect_netpbm,
    "png": images.inspect_png,
    "jpeg": images.inspect_jpeg,
    "bmp": images.inspect_bmp,
    "tga": images.inspect_tga,
    "hdr": images.inspect_hdr,
    "exr": images.inspect_exr,
    "webp": images.inspect_webp,
    "ply_mesh": meshes.inspect_ply_mesh,
    "stl": meshes.inspect_stl,
    "off": meshes.inspect_off,
    "ply": points.inspect_ply,
    "pcd": points.inspect_pcd,
    "xyz": points.inspect_xyz,
    "pts": points.inspect_pts,
    "las": points.inspect_las,
    "laz": points.inspect_laz,
    "colmap_sparse": reconstruction.inspect_colmap_binary,
    "colmap_sparse_txt": reconstruction.inspect_colmap_text,
    "colmap_db": reconstruction.inspect_colmap_db,
    "transforms_json": reconstruction.inspect_transforms,
    "euroc_state": reconstruction.inspect_euroc_state,
    "g2o": reconstruction.inspect_g2o,
    "bundler": reconstruction.inspect_bundler,
    "bal": reconstruction.inspect_bal,
    "nvm": reconstruction.inspect_nvm,
    "openmvg": reconstruction.inspect_openmvg,
    "y4m": sequences.inspect_y4m,
    "webm": sequences.inspect_webm,
    "ivf": sequences.inspect_ivf,
    "mjpeg": sequences.inspect_mjpeg,
    "mp4": sequences.inspect_mp4,
    "theora": sequences.inspect_theora,
    "animated_webp": sequences.inspect_animated_webp,
    "apng": sequences.inspect_apng,
    "gaussian_ply": splats.inspect_gaussian_ply,
    "compressed_ply": splats.inspect_compressed_ply,
    "sog": splats.inspect_sog,
    "ksplat": splats.inspect_ksplat,
    "spz": splats.inspect_spz,
    "splat": splats.inspect_splat,
}

_FORMAT_AWARE_INSPECTORS: dict[str, FormatAwareInspector] = {
    "tum": reconstruction.inspect_pose_text,
    "kitti": reconstruction.inspect_pose_text,
    "opencv_yaml": calibration.inspect_camera_rig,
    "opencv_xml": calibration.inspect_camera_rig,
    "ros_camera_info": calibration.inspect_camera_rig,
    "kalibr": calibration.inspect_camera_rig,
}


def inspect_path(path: str | Path, format_id: str, payload_kind: str) -> Inspection:
    """Inspect one built-in format without constructing its decoded record."""

    resolved_path = Path(path)
    inspector = _PATH_INSPECTORS.get(format_id)
    if inspector is not None:
        return inspector(resolved_path, payload_kind)

    format_aware_inspector = _FORMAT_AWARE_INSPECTORS.get(format_id)
    if format_aware_inspector is not None:
        return format_aware_inspector(resolved_path, format_id, payload_kind)

    raise ValueError(f"format {format_id!r} does not provide metadata inspection")


def inspect_codec(
    path: str | Path,
    format_id: str,
    payload_kind: str,
    inspector: Callable[[str], object] | None,
) -> Inspection:
    """Dispatch one already-resolved codec inspector without registry imports."""

    result = (
        inspect_path(path, format_id, payload_kind)
        if inspector is None
        else inspector(str(path))
    )
    if not isinstance(result, Inspection):
        raise TypeError(
            f"format {format_id!r} inspector returned {type(result).__name__}, "
            "expected Inspection"
        )
    return result
