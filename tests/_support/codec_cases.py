"""Canonical case ownership for cross-codec I/O behavior tests.

This module is initially non-consuming: existing behavior suites keep their
current local matrices until each migration proves exact pytest-node,
parameter-id, and skip-reason equivalence.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)


@dataclass(frozen=True, slots=True)
class CodecCaseDefinition:
    """Repository-owned fixture classification for one built-in codec."""

    id: str
    family: str
    fixture_kind: str
    partial_selectors: tuple[str, ...] = ()


_FAMILY_BY_ID = {
    format_id: family
    for family, format_ids in FAMILY_MEMBERS.items()
    for format_id in format_ids
}


def _case(
    format_id: str,
    fixture_kind: str,
    partial_selectors: tuple[str, ...],
) -> CodecCaseDefinition:
    return CodecCaseDefinition(
        id=format_id,
        family=_FAMILY_BY_ID[format_id],
        fixture_kind=fixture_kind,
        partial_selectors=partial_selectors,
    )


CODEC_CASE_DEFINITIONS = (
    _case("pfm", "buffer", ("window",)),
    _case("colmap_sparse", "directory", ("image_id",)),
    _case("gaussian_ply", "buffer", ("points",)),
    _case("compressed_ply", "buffer", ("points",)),
    _case("sog", "buffer", ("points",)),
    _case("ksplat", "buffer", ("points",)),
    _case("ply_mesh", "buffer", ("faces",)),
    _case("obj", "path", ()),
    _case("stl", "buffer", ("faces",)),
    _case("off", "buffer", ("faces",)),
    _case("gltf", "path", ("mesh_id", "primitive_id")),
    _case("glb", "buffer", ("mesh_id", "primitive_id")),
    _case("ply", "buffer", ("points",)),
    _case("pcd", "buffer", ("points",)),
    _case("spz", "buffer", ()),
    _case("transforms_json", "buffer", ()),
    _case("tum", "buffer", ()),
    _case("kitti", "buffer", ()),
    _case("euroc_state", "buffer", ("states",)),
    _case("opencv_yaml", "buffer", ()),
    _case("opencv_xml", "buffer", ()),
    _case("ros_camera_info", "buffer", ()),
    _case("kalibr", "buffer", ()),
    _case("g2o", "buffer", ()),
    _case("colmap_db", "path", ("image_id", "pair")),
    _case("npy", "buffer", ()),
    _case("npz", "buffer", ()),
    _case("safetensors", "buffer", ("tensors", "slices")),
    _case("netpbm", "buffer", ("window",)),
    _case("png", "buffer", ()),
    _case("jpeg", "buffer", ()),
    _case("bmp", "buffer", ()),
    _case("tga", "buffer", ()),
    _case("hdr", "buffer", ()),
    _case("exr", "buffer", ()),
    _case("webp", "buffer", ("window",)),
    _case("y4m", "buffer", ("frames",)),
    _case("animated_webp", "buffer", ()),
    _case("apng", "buffer", ()),
    _case("image_sequence", "directory", ("frames",)),
    _case("colmap_sparse_txt", "directory", ("image_id",)),
    _case("xyz", "buffer", ("points",)),
    _case("pts", "buffer", ("points",)),
    _case("las", "buffer", ("points",)),
    _case("laz", "buffer", ("points",)),
    _case("flo", "buffer", ("window",)),
    _case("dmb", "buffer", ("window",)),
    _case("bundler", "buffer", ()),
    _case("bal", "buffer", ()),
    _case("nvm", "buffer", ()),
    _case("openmvg", "buffer", ()),
    _case("splat", "buffer", ("points",)),
    _case("colmap_mvs_depth", "buffer", ("window",)),
    _case("colmap_mvs_normal", "buffer", ("window",)),
    _case("colmap_mvs_consistency", "buffer", ()),
    _case("colmap_fused_visibility", "buffer", ()),
    _case("hdf5", "path", ("tensors", "slices")),
    _case("hloc_features", "path", ()),
    _case("hloc_matches", "path", ()),
)

CASES_BY_ID = MappingProxyType(
    {case.id: case for case in CODEC_CASE_DEFINITIONS}
)
BUFFER_CASES = tuple(
    case
    for case in CODEC_CASE_DEFINITIONS
    if case.fixture_kind == "buffer"
)
PATH_CASES = tuple(
    case
    for case in CODEC_CASE_DEFINITIONS
    if case.fixture_kind == "path"
)
DIRECTORY_CASES = tuple(
    case
    for case in CODEC_CASE_DEFINITIONS
    if case.fixture_kind == "directory"
)
PARTIAL_CASES = tuple(
    case for case in CODEC_CASE_DEFINITIONS if case.partial_selectors
)


def _validate_case_definitions() -> None:
    observed = tuple(case.id for case in CODEC_CASE_DEFINITIONS)
    if observed != CANONICAL_BUILTIN_IDS:
        raise RuntimeError(
            "cross-codec cases must match canonical built-in order"
        )
    if len(CASES_BY_ID) != len(CODEC_CASE_DEFINITIONS):
        raise RuntimeError("cross-codec case ids must be unique")
    if {case.fixture_kind for case in CODEC_CASE_DEFINITIONS} != {
        "buffer",
        "path",
        "directory",
    }:
        raise RuntimeError("cross-codec fixture kinds are incomplete")
    if (len(BUFFER_CASES), len(PATH_CASES), len(DIRECTORY_CASES)) != (
        50,
        6,
        3,
    ):
        raise RuntimeError("cross-codec fixture partitions changed")


_validate_case_definitions()


__all__ = [
    "BUFFER_CASES",
    "CASES_BY_ID",
    "CODEC_CASE_DEFINITIONS",
    "DIRECTORY_CASES",
    "PARTIAL_CASES",
    "PATH_CASES",
    "CodecCaseDefinition",
]
