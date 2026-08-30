"""Architecture contracts for staged cross-codec case ownership."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from _support import codec_cases
from _support.buffer_codec_cases import build_buffer_codec_cases

import sceneio
from sceneio import _core
from sceneio.io import registry
from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_case_catalog_is_complete_ordered_and_immutable():
    definitions = codec_cases.CODEC_CASE_DEFINITIONS
    assert tuple(case.id for case in definitions) == CANONICAL_BUILTIN_IDS
    assert tuple(codec_cases.CASES_BY_ID) == CANONICAL_BUILTIN_IDS
    assert len(definitions) == len(codec_cases.CASES_BY_ID) == 74
    assert all(dataclasses.is_dataclass(case) for case in definitions)
    with pytest.raises(dataclasses.FrozenInstanceError):
        definitions[0].id = "changed"
    with pytest.raises(TypeError):
        codec_cases.CASES_BY_ID["changed"] = definitions[0]


def test_case_catalog_preserves_the_legacy_fixture_partitions():
    assert tuple(case.id for case in codec_cases.BUFFER_CASES) == (
        "pfm",
        "gaussian_ply",
        "compressed_ply",
        "sog",
        "ksplat",
        "ply_mesh",
        "stl",
        "off",
        "glb",
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
        "y4m",
        "webm",
        "theora",
        "animated_webp",
        "apng",
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
    )
    assert tuple(case.id for case in codec_cases.PATH_CASES) == (
        "obj",
        "gltf",
        "usd",
        "usdz",
        "colmap_db",
        "avif",
        "animated_avif",
        "hdf5",
        "hloc_features",
        "hloc_matches",
        "tiff",
        "e57",
        "parquet",
        "arrow_ipc",
        "openvdb",
    )
    assert tuple(case.id for case in codec_cases.DIRECTORY_CASES) == (
        "colmap_sparse",
        "rtmv",
        "image_sequence",
        "colmap_sparse_txt",
        "ncore_v4",
        "euroc_dataset",
        "zarr",
    )
    assert {
        case.id
        for cases in (
            codec_cases.BUFFER_CASES,
            codec_cases.PATH_CASES,
            codec_cases.DIRECTORY_CASES,
        )
        for case in cases
    } == set(CANONICAL_BUILTIN_IDS)
    built_cases = build_buffer_codec_cases()
    assert tuple(case.id for case in built_cases) == (
        "pfm",
        "gaussian_ply",
        "compressed_ply",
        "sog",
        "ksplat",
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
        "y4m",
        "webm",
        "theora",
        "animated_webp",
        "apng",
        "xyz",
        "pts",
        "ply",
        "ply_mesh",
        "stl",
        "off",
        "glb",
        "pcd",
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
    )
    for case in built_cases:
        assert case.reader is getattr(_core, f"read_{case.id}")
        assert case.writer is getattr(_core, f"write_{case.id}")
    portable_fixture_projection = [
        (case.id, len(case.data), hashlib.sha256(case.data).hexdigest())
        for case in built_cases
        if case.id != "compressed_ply"
    ]
    assert len(portable_fixture_projection) == 51
    assert next(
        item for item in portable_fixture_projection if item[0] == "sog"
    ) == (
        "sog",
        16916,
        "a69dc48f2fa90ad685a6a46af9f56b0705e6e917e5e281181cb9872222f4cd1f",
    )
    assert next(
        item
        for item in portable_fixture_projection
        if item[0] == "animated_webp"
    ) == (
        "animated_webp",
        1124,
        "f0a298ad93b9f6f44f6defc2bc6a7eb27544e934211893a1d1e429894dd1b071",
    )
    assert next(
        item for item in portable_fixture_projection if item[0] == "webm"
    ) == (
        "webm",
        822,
        "07cc5a95580ddd861331d3dc6cb0b6fd3c5ec7613191141d1715ed8a39b2629b",
    )
    fixture_payload = json.dumps(
        portable_fixture_projection,
        separators=(",", ":"),
    )
    assert hashlib.sha256(fixture_payload.encode()).hexdigest() == (
        "ae4dc5b567ffa8c6c22f010f8951337a7c007332ce827154c0b6b8ef30972548"
    )
    cases_by_id = {case.id: case for case in built_cases}
    assert (
        cases_by_id["compressed_ply"].value
        is cases_by_id["gaussian_ply"].value
    )


def test_case_catalog_family_ownership_matches_the_builtin_manifest():
    observed = {
        family: tuple(
            case.id
            for case in codec_cases.CODEC_CASE_DEFINITIONS
            if case.family == family
        )
        for family in FAMILY_MEMBERS
    }
    assert observed == dict(FAMILY_MEMBERS)


def test_case_catalog_selectors_match_live_builtin_capabilities():
    capabilities = sceneio.capabilities()
    assert set(capabilities) == set(CANONICAL_BUILTIN_IDS)
    for case in codec_cases.CODEC_CASE_DEFINITIONS:
        capability = capabilities[case.id]
        assert capability.available
        assert capability.can_read
        assert capability.can_write is (case.id != "rtmv")
        assert capability.can_inspect
        assert capability.streams_read
        assert capability.streams_write is (
            case.id not in {"avif", "animated_avif", "rtmv"}
        )
        assert case.partial_selectors == capability.partial_selectors
    assert tuple(case.id for case in codec_cases.PARTIAL_CASES) == (
        "pfm",
        "colmap_sparse",
        "gaussian_ply",
        "compressed_ply",
        "sog",
        "ksplat",
        "ply_mesh",
        "stl",
        "off",
        "gltf",
        "glb",
        "ply",
        "pcd",
        "euroc_state",
        "colmap_db",
        "safetensors",
        "netpbm",
        "webp",
        "y4m",
        "webm",
        "theora",
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
        "splat",
        "colmap_mvs_depth",
        "colmap_mvs_normal",
        "hdf5",
        "zarr",
        "parquet",
    )
    assert sum(
        len(case.partial_selectors)
        for case in codec_cases.PARTIAL_CASES
    ) == 43


def test_runtime_extensions_do_not_enter_repository_case_completeness():
    extension = dataclasses.replace(
        registry.REGISTRY["npy"],
        id="runtime-case-extension",
        extensions=(".runtime-case-extension",),
    )
    before = tuple(registry.REGISTRY.items())
    try:
        registry.register(extension)
        assert extension.id in registry.REGISTRY
        assert extension.id not in codec_cases.CASES_BY_ID
        assert tuple(codec_cases.CASES_BY_ID) == CANONICAL_BUILTIN_IDS
    finally:
        registry.REGISTRY.pop(extension.id, None)
    assert tuple(registry.REGISTRY.items()) == before


def test_case_catalog_has_lower_ownership_and_no_consumer_imports():
    source_path = ROOT / "tests/_support/codec_cases.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {
        "__future__",
        "dataclasses",
        "sceneio.io._builtin_manifest",
        "types",
    }
    builder_path = ROOT / "tests/_support/buffer_codec_cases.py"
    builder_tree = ast.parse(builder_path.read_text(encoding="utf-8"))
    builder_imports = set()
    for node in ast.walk(builder_tree):
        if isinstance(node, ast.Import):
            builder_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            builder_imports.add(node.module)
    assert builder_imports == {
        "__future__",
        "_support.codec_cases",
        "dataclasses",
        "numpy",
        "sceneio",
        "sceneio._posed_views",
    }
    for consumer in (
        "test_io_mmap.py",
        "test_io_streaming.py",
        "test_io_inspection.py",
    ):
        consumer_source = (ROOT / "tests" / consumer).read_text(encoding="utf-8")
        assert (
            "from _support.buffer_codec_cases import build_buffer_codec_cases"
            in consumer_source
        )
        assert "from _support.codec_cases import" not in consumer_source
    assert "codec_cases" not in (
        ROOT / "tests/test_io_partial.py"
    ).read_text(encoding="utf-8")
