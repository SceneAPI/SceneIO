"""Metadata-only inspection for SceneIO's built-in file formats.

The parsers in this module stop at container headers whenever the format has
one. Headerless text formats are streamed line by line, and JSON scene formats
parse only their metadata document (they do not construct compiled records or
pixel/point arrays).
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping as Mapping
from pathlib import Path
from typing import BinaryIO

from sceneio.io._inspectors.arrays import (
    inspect_dmb as _inspect_array_dmb,
)
from sceneio.io._inspectors.arrays import (
    inspect_flo as _inspect_array_flo,
)
from sceneio.io._inspectors.arrays import (
    inspect_npy as _inspect_array_npy,
)
from sceneio.io._inspectors.arrays import (
    inspect_npz as _inspect_array_npz,
)
from sceneio.io._inspectors.arrays import (
    inspect_pfm as _inspect_array_pfm,
)
from sceneio.io._inspectors.arrays import (
    inspect_safetensors as _inspect_array_safetensors,
)
from sceneio.io._inspectors.arrays import (
    npy_header as _inspect_array_npy_header,
)
from sceneio.io._inspectors.calibration import (
    inspect_camera_rig as _inspect_calibration_camera_rig,
)
from sceneio.io._inspectors.common import _HEADER_LIMIT as _HEADER_LIMIT
from sceneio.io._inspectors.common import _IMAGE_PIXEL_CAP as _IMAGE_PIXEL_CAP
from sceneio.io._inspectors.common import (
    _compiled_buffer_inspect as _compiled_buffer_inspect,
)
from sceneio.io._inspectors.common import _exact as _exact
from sceneio.io._inspectors.common import _image as _image
from sceneio.io._inspectors.common import _unsigned_decimal as _unsigned_decimal
from sceneio.io._inspectors.images import (
    inspect_bmp as _inspect_image_bmp,
)
from sceneio.io._inspectors.images import (
    inspect_exr as _inspect_image_exr,
)
from sceneio.io._inspectors.images import (
    inspect_hdr as _inspect_image_hdr,
)
from sceneio.io._inspectors.images import (
    inspect_jpeg as _inspect_image_jpeg,
)
from sceneio.io._inspectors.images import (
    inspect_netpbm as _inspect_image_netpbm,
)
from sceneio.io._inspectors.images import (
    inspect_png as _inspect_image_png,
)
from sceneio.io._inspectors.images import (
    inspect_tga as _inspect_image_tga,
)
from sceneio.io._inspectors.images import (
    inspect_webp as _inspect_image_webp,
)
from sceneio.io._inspectors.meshes import (
    inspect_off as _inspect_mesh_off,
)
from sceneio.io._inspectors.meshes import (
    inspect_ply_mesh as _inspect_mesh_ply,
)
from sceneio.io._inspectors.meshes import (
    inspect_stl as _inspect_mesh_stl,
)
from sceneio.io._inspectors.model import ArrayInspection as ArrayInspection
from sceneio.io._inspectors.model import Inspection
from sceneio.io._inspectors.model import MetadataValue as MetadataValue
from sceneio.io._inspectors.points import (
    inspect_las as _inspect_point_las,
)
from sceneio.io._inspectors.points import (
    inspect_laz as _inspect_point_laz,
)
from sceneio.io._inspectors.points import (
    inspect_pcd as _inspect_point_pcd,
)
from sceneio.io._inspectors.points import (
    inspect_ply as _inspect_point_ply,
)
from sceneio.io._inspectors.points import (
    inspect_pts as _inspect_point_pts,
)
from sceneio.io._inspectors.points import (
    inspect_xyz as _inspect_point_xyz,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_bal as _inspect_reconstruction_bal,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_bundler as _inspect_reconstruction_bundler,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_colmap_binary as _inspect_reconstruction_colmap_binary,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_colmap_db as _inspect_reconstruction_colmap_db,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_colmap_text as _inspect_reconstruction_colmap_text,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_euroc_state as _inspect_reconstruction_euroc_state,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_g2o as _inspect_reconstruction_g2o,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_nvm as _inspect_reconstruction_nvm,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_openmvg as _inspect_reconstruction_openmvg,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_pose_text as _inspect_reconstruction_pose_text,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_transforms as _inspect_reconstruction_transforms,
)
from sceneio.io._inspectors.sequences import (
    inspect_animated_webp as _inspect_sequence_animated_webp,
)
from sceneio.io._inspectors.sequences import (
    inspect_apng as _inspect_sequence_apng,
)
from sceneio.io._inspectors.sequences import (
    inspect_y4m as _inspect_sequence_y4m,
)
from sceneio.io._inspectors.splats import (
    inspect_compressed_ply as _inspect_splat_compressed_ply,
)
from sceneio.io._inspectors.splats import (
    inspect_gaussian_ply as _inspect_splat_gaussian_ply,
)
from sceneio.io._inspectors.splats import (
    inspect_ksplat as _inspect_splat_ksplat,
)
from sceneio.io._inspectors.splats import (
    inspect_sog as _inspect_splat_sog,
)
from sceneio.io._inspectors.splats import (
    inspect_splat as _inspect_splat_splat,
)
from sceneio.io._inspectors.splats import (
    inspect_spz as _inspect_splat_spz,
)


def inspect_path(path: str | Path, format_id: str, datatype: str) -> Inspection:
    """Inspect one built-in format without constructing its decoded record."""

    p = Path(path)
    if format_id == "pfm":
        return _inspect_pfm(p, datatype)
    if format_id == "colmap_sparse":
        return _inspect_colmap_binary(p, datatype)
    if format_id == "gaussian_ply":
        return _inspect_gaussian_ply(p, datatype)
    if format_id == "compressed_ply":
        return _inspect_compressed_ply(p, datatype)
    if format_id == "sog":
        return _inspect_sog(p, datatype)
    if format_id == "ksplat":
        return _inspect_ksplat(p, datatype)
    if format_id == "ply":
        return _inspect_ply(p, datatype)
    if format_id == "ply_mesh":
        return _inspect_ply_mesh(p, datatype)
    if format_id == "stl":
        return _inspect_stl(p, datatype)
    if format_id == "off":
        return _inspect_off(p, datatype)
    if format_id == "pcd":
        return _inspect_pcd(p, datatype)
    if format_id == "spz":
        return _inspect_spz(p, datatype)
    if format_id == "transforms_json":
        return _inspect_transforms(p, datatype)
    if format_id in {"tum", "kitti"}:
        return _inspect_pose_text(p, format_id, datatype)
    if format_id == "euroc_state":
        return _inspect_euroc_state(p, datatype)
    if format_id in {
        "opencv_yaml",
        "opencv_xml",
        "ros_camera_info",
        "kalibr",
    }:
        return _inspect_camera_rig(p, format_id, datatype)
    if format_id == "g2o":
        return _inspect_g2o(p, datatype)
    if format_id == "colmap_db":
        return _inspect_colmap_db(p, datatype)
    if format_id == "npy":
        return _inspect_npy(p, datatype)
    if format_id == "npz":
        return _inspect_npz(p, datatype)
    if format_id == "safetensors":
        return _inspect_safetensors(p, datatype)
    if format_id == "netpbm":
        return _inspect_netpbm(p, datatype)
    if format_id == "png":
        return _inspect_png(p, datatype)
    if format_id == "jpeg":
        return _inspect_jpeg(p, datatype)
    if format_id == "bmp":
        return _inspect_bmp(p, datatype)
    if format_id == "tga":
        return _inspect_tga(p, datatype)
    if format_id == "hdr":
        return _inspect_hdr(p, datatype)
    if format_id == "exr":
        return _inspect_exr(p, datatype)
    if format_id == "webp":
        return _inspect_webp(p, datatype)
    if format_id == "y4m":
        return _inspect_y4m(p, datatype)
    if format_id == "animated_webp":
        return _inspect_animated_webp(p, datatype)
    if format_id == "apng":
        return _inspect_apng(p, datatype)
    if format_id == "colmap_sparse_txt":
        return _inspect_colmap_text(p, datatype)
    if format_id == "xyz":
        return _inspect_xyz(p, datatype)
    if format_id == "pts":
        return _inspect_pts(p, datatype)
    if format_id == "las":
        return _inspect_las(p, datatype)
    if format_id == "laz":
        return _inspect_laz(p, datatype)
    if format_id == "flo":
        return _inspect_flo(p, datatype)
    if format_id == "dmb":
        return _inspect_dmb(p, datatype)
    if format_id == "bundler":
        return _inspect_bundler(p, datatype)
    if format_id == "bal":
        return _inspect_bal(p, datatype)
    if format_id == "nvm":
        return _inspect_nvm(p, datatype)
    if format_id == "openmvg":
        return _inspect_openmvg(p, datatype)
    if format_id == "splat":
        return _inspect_splat(p, datatype)
    raise ValueError(f"format {format_id!r} does not provide metadata inspection")


def inspect_codec(
    path: str | Path,
    format_id: str,
    datatype: str,
    inspector: Callable[[str], object] | None,
) -> Inspection:
    """Dispatch one already-resolved codec inspector without registry imports."""

    result = (
        inspect_path(path, format_id, datatype)
        if inspector is None
        else inspector(str(path))
    )
    if not isinstance(result, Inspection):
        raise TypeError(
            f"format {format_id!r} inspector returned {type(result).__name__}, "
            "expected Inspection"
        )
    return result


def _inspect_colmap_db(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_colmap_db(path, datatype)


def _inspect_pfm(path: Path, datatype: str) -> Inspection:
    return _inspect_array_pfm(path, datatype)


def _npy_header(stream: BinaryIO) -> tuple[tuple[int, ...], str, bool]:
    return _inspect_array_npy_header(stream)


def _inspect_npy(path: Path, datatype: str) -> Inspection:
    return _inspect_array_npy(path, datatype)


def _inspect_npz(path: Path, datatype: str) -> Inspection:
    return _inspect_array_npz(path, datatype)


def _inspect_safetensors(path: Path, datatype: str) -> Inspection:
    return _inspect_array_safetensors(path, datatype)


def _inspect_netpbm(path: Path, datatype: str) -> Inspection:
    return _inspect_image_netpbm(path, datatype)


def _inspect_png(path: Path, datatype: str) -> Inspection:
    return _inspect_image_png(path, datatype)


def _inspect_jpeg(path: Path, datatype: str) -> Inspection:
    return _inspect_image_jpeg(path, datatype)


def _inspect_bmp(path: Path, datatype: str) -> Inspection:
    return _inspect_image_bmp(path, datatype)


def _inspect_tga(path: Path, datatype: str) -> Inspection:
    return _inspect_image_tga(path, datatype)


def _inspect_hdr(path: Path, datatype: str) -> Inspection:
    return _inspect_image_hdr(path, datatype)


def _inspect_exr(path: Path, datatype: str) -> Inspection:
    return _inspect_image_exr(path, datatype)


def _inspect_webp(path: Path, datatype: str) -> Inspection:
    return _inspect_image_webp(path, datatype)

def _inspect_y4m(path: Path, datatype: str) -> Inspection:
    return _inspect_sequence_y4m(path, datatype)


def _inspect_animated_webp(path: Path, datatype: str) -> Inspection:
    return _inspect_sequence_animated_webp(path, datatype)


def _inspect_apng(path: Path, datatype: str) -> Inspection:
    return _inspect_sequence_apng(path, datatype)


def _inspect_flo(path: Path, datatype: str) -> Inspection:
    return _inspect_array_flo(path, datatype)


def _inspect_dmb(path: Path, datatype: str) -> Inspection:
    return _inspect_array_dmb(path, datatype)


def _inspect_las(path: Path, datatype: str) -> Inspection:
    return _inspect_point_las(path, datatype)


def _inspect_laz(path: Path, datatype: str) -> Inspection:
    return _inspect_point_laz(path, datatype)


def _inspect_gaussian_ply(path: Path, datatype: str) -> Inspection:
    return _inspect_splat_gaussian_ply(path, datatype)


def _inspect_compressed_ply(path: Path, datatype: str) -> Inspection:
    return _inspect_splat_compressed_ply(path, datatype)


def _inspect_sog(path: Path, datatype: str) -> Inspection:
    return _inspect_splat_sog(path, datatype)


def _inspect_ksplat(path: Path, datatype: str) -> Inspection:
    return _inspect_splat_ksplat(path, datatype)


def _inspect_ply(path: Path, datatype: str) -> Inspection:
    return _inspect_point_ply(path, datatype)


def _inspect_ply_mesh(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_ply(path, datatype)


def _inspect_stl(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_stl(path, datatype)


def _inspect_off(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_off(path, datatype)


def _inspect_pcd(path: Path, datatype: str) -> Inspection:
    return _inspect_point_pcd(path, datatype)


def _inspect_spz(path: Path, datatype: str) -> Inspection:
    return _inspect_splat_spz(path, datatype)


def _inspect_splat(path: Path, datatype: str) -> Inspection:
    return _inspect_splat_splat(path, datatype)


def _inspect_xyz(path: Path, datatype: str) -> Inspection:
    return _inspect_point_xyz(path, datatype)


def _inspect_pts(path: Path, datatype: str) -> Inspection:
    return _inspect_point_pts(path, datatype)


def _inspect_pose_text(path: Path, format_id: str, datatype: str) -> Inspection:
    return _inspect_reconstruction_pose_text(path, format_id, datatype)


def _inspect_euroc_state(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_euroc_state(path, datatype)


def _inspect_camera_rig(
    path: Path, format_id: str, datatype: str
) -> Inspection:
    return _inspect_calibration_camera_rig(
        path,
        format_id,
        datatype,
    )


def _inspect_g2o(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_g2o(path, datatype)


def _inspect_bundler(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_bundler(path, datatype)


def _inspect_bal(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_bal(path, datatype)


def _inspect_nvm(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_nvm(path, datatype)


def _inspect_transforms(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_transforms(path, datatype)


def _inspect_openmvg(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_openmvg(path, datatype)


def _inspect_colmap_binary(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_colmap_binary(path, datatype)


def _inspect_colmap_text(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_colmap_text(path, datatype)
