"""Coordinate contracts for every repository-owned format.

The mapping is deliberately complete and ordered like the built-in registry.
Adding a codec without classifying its coordinate behavior is therefore a
checked contract change rather than an implicit assumption.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from sceneio.coordinates import (
    COLMAP_COORDINATES,
    IMAGE_COORDINATES,
    UNKNOWN_COORDINATES,
    CoordinateConvention,
    FormatCoordinateContract,
)
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS

_SCENEIO_DOC = "docs/coordinate_conventions.md"
_COLMAP_SPEC = "https://colmap.github.io/format.html"
_COLMAP_CAMERA_SPEC = "https://colmap.github.io/cameras.html"

_COLMAP_CAMERA = replace(
    IMAGE_COORDINATES,
    name="colmap_camera",
    camera_axes="opencv",
    handedness="right_handed",
)
_COLMAP_DEPTH = replace(
    _COLMAP_CAMERA,
    name="colmap_camera_z_depth",
    scale_class="arbitrary",
    depth_interpretation="camera_z",
)
_COLMAP_NORMAL = replace(
    _COLMAP_CAMERA,
    name="colmap_camera_normal",
)
_HLOC_IMAGE = replace(
    IMAGE_COORDINATES,
    name="hloc_image",
    pixel_center=(0.0, 0.0),
)
_OPENCV_METRIC = replace(
    _COLMAP_CAMERA,
    name="opencv_metric_rig",
    pose_direction="world_to_camera",
    quaternion_order="wxyz",
    quaternion_algebra="hamilton",
    world_frame="arbitrary",
    scale_class="metric",
    scale_to_meters=1.0,
)
_OPENCV_C2W = replace(
    _OPENCV_METRIC,
    name="opencv_camera_to_world_metric",
    pose_direction="camera_to_world",
)
_CANONICAL_POSED_VIEWS = replace(
    _OPENCV_C2W,
    name="canonical_posed_views",
    quaternion_order="wxyz",
)
_OPENGL_SCENE = CoordinateConvention(
    name="gltf_scene",
    camera_axes="opengl",
    handedness="right_handed",
    world_frame="reference",
    up_axis="y",
    scale_class="metric",
    scale_to_meters=1.0,
)
_EUROC = CoordinateConvention(
    name="euroc_state",
    handedness="right_handed",
    pose_direction="sensor_to_reference",
    quaternion_order="wxyz",
    quaternion_algebra="hamilton",
    world_frame="reference",
    scale_class="metric",
    scale_to_meters=1.0,
)
_G2O = CoordinateConvention(
    name="g2o_se3",
    camera_axes="unknown",
    handedness="right_handed",
    pose_direction="node_to_reference",
    quaternion_order="xyzw",
    quaternion_algebra="hamilton",
    world_frame="reference",
    scale_class="unknown",
)
_FLOW = replace(
    IMAGE_COORDINATES,
    name="middlebury_flow",
)


def _fixed(
    domains: tuple[str, ...],
    convention: CoordinateConvention,
    reference: str,
    *,
    conversion: str = "requires_context",
    writer_requirement: str = "record convention must match the format",
) -> FormatCoordinateContract:
    return FormatCoordinateContract(
        "fixed",
        domains,
        convention,
        writer_requirement,
        conversion,
        reference,
    )


def _declared(
    domains: tuple[str, ...],
    reference: str,
) -> FormatCoordinateContract:
    return FormatCoordinateContract(
        "file_declared",
        domains,
        None,
        "the writer preserves or explicitly authors file convention metadata",
        "requires_context",
        reference,
    )


def _unspecified(
    domains: tuple[str, ...],
    reference: str = _SCENEIO_DOC,
) -> FormatCoordinateContract:
    return FormatCoordinateContract(
        "unspecified",
        domains,
        UNKNOWN_COORDINATES,
        "only explicitly unknown conventions are accepted unless metadata is representable",
        "requires_context",
        reference,
    )


def _not_applicable(reference: str = _SCENEIO_DOC) -> FormatCoordinateContract:
    return FormatCoordinateContract(
        "not_applicable",
        (),
        None,
        "the format carries no coordinate semantics",
        "not_applicable",
        reference,
    )


_IMAGE = _fixed(("image",), IMAGE_COORDINATES, _SCENEIO_DOC, conversion="not_applicable")
_SEQUENCE = _fixed(
    ("image",),
    IMAGE_COORDINATES,
    _SCENEIO_DOC,
    conversion="not_applicable",
)
_COLMAP_RECONSTRUCTION = _fixed(
    ("camera", "image", "spatial"),
    COLMAP_COORDINATES,
    _COLMAP_SPEC,
    conversion="not_applicable",
)

_RAW: dict[str, FormatCoordinateContract] = {
    "pfm": _unspecified(("depth", "image")),
    "colmap_sparse": _COLMAP_RECONSTRUCTION,
    "gaussian_ply": _unspecified(("spatial",)),
    "compressed_ply": _unspecified(("spatial",)),
    "sog": _unspecified(("spatial",)),
    "ksplat": _unspecified(("spatial",)),
    "ply_mesh": _declared(("spatial",), _SCENEIO_DOC),
    "obj": _unspecified(("spatial",)),
    "stl": _unspecified(("spatial",)),
    "off": _unspecified(("spatial",)),
    "gltf": _fixed(("camera", "spatial"), _OPENGL_SCENE, "https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html"),
    "glb": _fixed(("camera", "spatial"), _OPENGL_SCENE, "https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html"),
    "usd": _declared(("camera", "spatial"), "https://openusd.org/release/api/group___usd_geom_linear_units__group.html"),
    "usdz": _declared(("camera", "spatial"), "https://openusd.org/release/api/group___usd_geom_linear_units__group.html"),
    "ply": _unspecified(("spatial",)),
    "pcd": _unspecified(("spatial",), "https://pointclouds.org/documentation/tutorials/pcd_file_format.html"),
    "spz": _unspecified(("spatial",)),
    "transforms_json": _fixed(
        ("camera", "image", "spatial"),
        _CANONICAL_POSED_VIEWS,
        _SCENEIO_DOC,
        conversion="supported",
        writer_requirement="canonical OpenCV camera-to-world poses are encoded in the format's OpenGL storage axes",
    ),
    "tum": _fixed(
        ("camera", "trajectory"),
        _CANONICAL_POSED_VIEWS,
        "https://cvg.cit.tum.de/data/datasets/rgbd-dataset/file_formats",
        conversion="supported",
        writer_requirement="canonical WXYZ poses are encoded in TUM's XYZW field order",
    ),
    "kitti": _fixed(
        ("camera", "trajectory"),
        _CANONICAL_POSED_VIEWS,
        "https://www.cvlibs.net/datasets/kitti/eval_odometry.php",
        conversion="supported",
        writer_requirement="canonical poses are encoded as KITTI camera-to-world matrices",
    ),
    "euroc_state": _fixed(("camera", "trajectory"), _EUROC, "https://projects.asl.ethz.ch/datasets/doku.php?id=kmavvisualinertialdatasets"),
    "opencv_yaml": _fixed(("camera", "image"), _OPENCV_METRIC, "https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html"),
    "opencv_xml": _fixed(("camera", "image"), _OPENCV_METRIC, "https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html"),
    "ros_camera_info": _fixed(("camera", "image"), _OPENCV_METRIC, "https://docs.ros.org/en/noetic/api/sensor_msgs/html/msg/CameraInfo.html"),
    "kalibr": _fixed(("camera", "image"), _OPENCV_METRIC, "https://github.com/ethz-asl/kalibr/wiki/yaml-formats"),
    "g2o": _fixed(("spatial", "trajectory"), _G2O, "https://github.com/RainerKuemmerle/g2o"),
    "colmap_db": _fixed(("camera", "image"), _COLMAP_CAMERA, _COLMAP_CAMERA_SPEC),
    "npy": _unspecified(("tensor",)),
    "npz": _unspecified(("tensor",)),
    "safetensors": _unspecified(("tensor",)),
    "netpbm": _IMAGE,
    "png": _IMAGE,
    "jpeg": _IMAGE,
    "bmp": _IMAGE,
    "tga": _IMAGE,
    "hdr": _IMAGE,
    "exr": _IMAGE,
    "webp": _IMAGE,
    "avif": _IMAGE,
    "y4m": _SEQUENCE,
    "webm": _SEQUENCE,
    "ivf": _SEQUENCE,
    "mjpeg": _SEQUENCE,
    "mp4": _SEQUENCE,
    "theora": _SEQUENCE,
    "animated_webp": _SEQUENCE,
    "apng": _SEQUENCE,
    "animated_avif": _SEQUENCE,
    "rtmv": _fixed(
        ("camera", "depth", "image", "spatial"),
        _CANONICAL_POSED_VIEWS,
        _SCENEIO_DOC,
        writer_requirement="RTMV is read-only; decoded poses use the canonical posed-view convention",
    ),
    "image_sequence": _SEQUENCE,
    "colmap_sparse_txt": _COLMAP_RECONSTRUCTION,
    "xyz": _unspecified(("spatial",)),
    "pts": _unspecified(("spatial",)),
    "las": _declared(("spatial",), "https://www.asprs.org/divisions-committees/lidar-division/laser-las-file-format-exchange-activities"),
    "laz": _declared(("spatial",), "https://www.asprs.org/divisions-committees/lidar-division/laser-las-file-format-exchange-activities"),
    "flo": _fixed(("image",), _FLOW, "https://vision.middlebury.edu/flow/code/flow-code/README.txt"),
    "dmb": _unspecified(("depth", "image")),
    "bundler": _COLMAP_RECONSTRUCTION,
    "bal": replace(
        _COLMAP_RECONSTRUCTION,
        reference="https://grail.cs.washington.edu/projects/bal/",
    ),
    "nvm": _COLMAP_RECONSTRUCTION,
    "openmvg": replace(
        _COLMAP_RECONSTRUCTION,
        reference="https://openmvg.readthedocs.io/en/latest/openMVG/sfm/sfm/",
    ),
    "splat": _unspecified(("spatial",)),
    "colmap_mvs_depth": _fixed(("depth", "image"), _COLMAP_DEPTH, _COLMAP_SPEC),
    "colmap_mvs_normal": _fixed(("camera", "image"), _COLMAP_NORMAL, _COLMAP_SPEC),
    "colmap_mvs_consistency": _fixed(("image",), IMAGE_COORDINATES, _COLMAP_SPEC, conversion="not_applicable"),
    "colmap_fused_visibility": _not_applicable(_COLMAP_SPEC),
    "hdf5": _unspecified(("tensor",)),
    "hloc_features": _fixed(("image",), _HLOC_IMAGE, "https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/triangulation.py"),
    "hloc_matches": _not_applicable("https://github.com/cvg/Hierarchical-Localization"),
    "ncore_v4": _declared(("tensor",), _SCENEIO_DOC),
    "euroc_dataset": _declared(
        ("camera", "image", "trajectory"),
        "https://projects.asl.ethz.ch/datasets/doku.php?id=kmavvisualinertialdatasets",
    ),
    "zarr": _unspecified(("tensor",)),
    "tiff": _IMAGE,
    "e57": _declared(("spatial",), "https://www.astm.org/e2807-11r19e01.html"),
    "parquet": _unspecified(("tensor",)),
    "arrow_ipc": _unspecified(("tensor",)),
    "openvdb": _declared(("spatial", "tensor"), "https://www.openvdb.org/documentation/doxygen/overview.html"),
}

if tuple(_RAW) != CANONICAL_BUILTIN_IDS:
    raise RuntimeError("coordinate manifest differs from the canonical built-in registry")

FORMAT_COORDINATE_CONTRACTS = MappingProxyType(_RAW)


def coordinate_contract(format_id: str) -> FormatCoordinateContract:
    """Return the immutable coordinate contract for a built-in format."""

    try:
        return FORMAT_COORDINATE_CONTRACTS[format_id]
    except KeyError as exc:
        raise ValueError(f"unknown coordinate contract {format_id!r}") from exc


__all__ = ["FORMAT_COORDINATE_CONTRACTS", "coordinate_contract"]
