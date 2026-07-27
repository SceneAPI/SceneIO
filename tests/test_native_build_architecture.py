"""Contracts for the modular native build and source ownership."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests/contracts/native_build_v1.json").read_text(encoding="utf-8")
)
SOURCES = (ROOT / "cmake/SceneIOSources.cmake").read_text(encoding="utf-8")


def _normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _cmake_source_set(name: str) -> tuple[str, ...]:
    match = re.search(rf"set\({re.escape(name)}\s+(.*?)\)", SOURCES, re.DOTALL)
    assert match is not None, name
    return tuple(re.findall(r"src/cpp/[^\s)]+", match.group(1)))


def _basenames(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(Path(path).name for path in paths)


def test_root_cmake_is_only_the_ordered_build_assembly() -> None:
    root_cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    for relative_path, expected_hash in CONTRACT["cmake_file_sha256"].items():
        assert _normalized_sha256(ROOT / relative_path) == expected_hash

    includes = re.findall(r"^include\((cmake/[^)]+)\)$", root_cmake, re.MULTILINE)
    assert includes == CONTRACT["cmake_modules"]
    assert "project(sceneio_core LANGUAGES C CXX)" in root_cmake
    assert "set(CMAKE_CXX_STANDARD 17)" in root_cmake
    assert not re.search(
        r"\b(?:FetchContent_Declare|add_library|nanobind_add_module|"
        r"target_link_libraries)\s*\(",
        root_cmake,
    )


def test_codec_family_manifests_partition_native_sources() -> None:
    variable_by_family = {
        "arrays": "SCENEIO_ARRAY_CODEC_SOURCES",
        "calibration": "SCENEIO_CALIBRATION_CODEC_SOURCES",
        "images": "SCENEIO_IMAGE_CODEC_SOURCES",
        "meshes": "SCENEIO_MESH_CODEC_SOURCES",
        "points": "SCENEIO_POINT_CODEC_SOURCES",
        "reconstruction": "SCENEIO_RECONSTRUCTION_CODEC_SOURCES",
        "sequences": "SCENEIO_SEQUENCE_CODEC_SOURCES",
        "splats": "SCENEIO_SPLAT_CODEC_SOURCES",
    }
    owned_paths = []
    for family, variable in variable_by_family.items():
        paths = _cmake_source_set(variable)
        assert _basenames(paths) == tuple(
            CONTRACT["codec_source_owners"][family]
        )
        owned_paths.extend(paths)

    discovered = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/cpp/codecs").rglob("*.cpp")
    }
    assert len(owned_paths) == len(set(owned_paths))
    assert set(owned_paths) == discovered
    assert (
        "_sceneio_assert_unique_sources(\n"
        '  "SCENEIO_CODEC_SOURCES" ${SCENEIO_CODEC_SOURCES})'
    ) in SOURCES
    assert "SCENEIO_CODEC_SOURCES must own every codec source exactly once" in SOURCES


def test_record_and_link_manifests_match_the_frozen_native_layout() -> None:
    record_paths = _cmake_source_set("SCENEIO_RECORD_SOURCES")
    discovered_records = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/cpp/records").rglob("*.cpp")
    }
    assert _basenames(record_paths) == tuple(CONTRACT["record_sources"])
    assert set(record_paths) == discovered_records

    core_paths = _cmake_source_set("SCENEIO_CORE_SOURCES")
    assert _basenames(core_paths) == tuple(CONTRACT["core_link_order"])
    assert len(core_paths) == len(set(core_paths))
    assert all((ROOT / path).is_file() for path in core_paths)


def test_target_and_instrumentation_contracts_remain_explicit() -> None:
    targets = (ROOT / "cmake/SceneIOTargets.cmake").read_text(encoding="utf-8")
    link_block = re.search(
        r"target_link_libraries\(\s*_core\s+PRIVATE\s+(.*?)\)",
        targets,
        re.DOTALL,
    )
    assert link_block is not None
    assert tuple(link_block.group(1).split()) == tuple(CONTRACT["core_link_targets"])
    assert "nanobind_add_module(_core STABLE_ABI NB_STATIC" in targets
    assert "install(TARGETS _core LIBRARY DESTINATION sceneio)" in targets

    instrumentation = (
        ROOT / "cmake/SceneIOInstrumentation.cmake"
    ).read_text(encoding="utf-8")
    assert re.search(
        r"option\(\s*SCENEIO_ENABLE_SANITIZERS\s+"
        r'"[^"]+"\s+OFF\s*\)',
        instrumentation,
    )
    assert re.search(
        r"option\(\s*SCENEIO_BUILD_NATIVE_TEST_HOOKS\s+"
        r'"[^"]+"\s+OFF\s*\)',
        instrumentation,
    )
