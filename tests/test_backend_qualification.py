"""Build and intake contracts for qualification-only codec backends."""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

from sceneio import _core

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "bench" / "BACKEND_CANDIDATES.toml"
RECEIPT = (
    ROOT
    / "bench"
    / "results"
    / "backend_qualification"
    / "jpeg-rgb8-v1-windows-msvc-7a88e7c.json"
)
QUALIFICATION_CMAKE = ROOT / "cmake" / "SceneIOBackendQualification.cmake"
TARGETS_CMAKE = ROOT / "cmake" / "SceneIOTargets.cmake"
SIMD_CMAKE = ROOT / "cmake" / "SceneIORecordJpegSimd.cmake"


def _candidate_ledger():
    return tomllib.loads(CANDIDATES.read_text(encoding="utf-8"))


def test_backend_candidate_ledger_has_complete_jpeg_intake():
    ledger = _candidate_ledger()
    assert ledger["schema_version"] == 1
    assert ledger["policy"]["default_build"] == "retained backend only"
    assert ledger["policy"]["runtime_dependencies"] == ["numpy"]
    assert ledger["policy"]["required_toolchains"] == [
        "Windows MSVC x64",
        "manylinux2014 GCC 10 x86_64",
        "macOS AppleClang arm64",
    ]

    decisions = ledger["decision"]
    assert [item["id"] for item in decisions] == ["jpeg-rgb8-v1"]
    decision = decisions[0]
    assert decision["status"] == "rejected"
    assert decision["result_commit"] == (
        "7a88e7c726eed5bdd4ff0ad05b381c9795af9dfe"
    )
    assert decision["report_sha256"] == (
        "f32b7c60f19956438023c51cc9c0b07f"
        "44ace79c66dff4a43c30fc7cfdcd80b1"
    )
    assert decision["failed_gate"] == "quality-profile:rgb8_q95_444"
    assert decision["observed_delta_db"] == -0.05824218633100031
    assert decision["required_delta_db"] == -0.05
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["source"]["commit"] == decision["result_commit"]
    assert receipt["full_report"]["sha256"] == decision["report_sha256"]
    assert receipt["validation"] == {
        "status": "failed",
        "passed": False,
        "gate_count": 1597,
        "passed_gate_count": 1596,
        "failed_gate_count": 1,
        "failed_gates": [
            {
                "name": decision["failed_gate"],
                "median_delta_db": decision["observed_delta_db"],
                "required_delta_db": decision["required_delta_db"],
            }
        ],
    }
    assert receipt["decision"] == {
        "candidate": "libjpeg-turbo 3.2.0",
        "outcome": "rejected_quality_gate",
        "stable_backend": "stb",
        "remote_workflow_dispatched": False,
    }
    assert len(decision["profiles"]) == 6
    assert {
        "quality_boundary_q90_q91",
        "cmyk",
        "ycck",
        "malformed_and_truncated",
    } <= set(decision["compatibility_profiles"])

    candidates = decision["candidate"]
    assert [item["id"] for item in candidates] == [
        "stb",
        "libjpeg-turbo",
        "mozjpeg",
        "jpegli",
    ]
    assert [item["outcome"] for item in candidates] == [
        "retained_baseline",
        "rejected_quality_gate",
        "excluded",
        "excluded",
    ]
    required = {
        "version",
        "commit",
        "source",
        "license",
        "maintenance",
        "supported_subset",
        "build_system",
        "simd",
        "threading",
        "compilers",
        "static_offline",
        "hidden_in_core",
        "outcome",
        "reason",
    }
    for candidate in candidates:
        assert required <= candidate.keys()
        assert len(candidate["commit"]) == 40
        assert candidate["static_offline"] is True
        assert candidate["hidden_in_core"] is True
        assert candidate["reason"]


def test_libjpeg_turbo_intake_matches_the_build_pin():
    decision = _candidate_ledger()["decision"][0]
    candidate = next(item for item in decision["candidate"] if item["id"] == "libjpeg-turbo")
    cmake = QUALIFICATION_CMAKE.read_text(encoding="utf-8")
    for value in (
        candidate["version"],
        candidate["commit"],
        candidate["archive_sha256"],
    ):
        assert value in cmake
    assert candidate["source"].split("/releases/download/")[0] in cmake
    assert "CMake >=3.18" in candidate["build_system"]
    root_cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    assert root_cmake.startswith("cmake_minimum_required(VERSION 3.18")
    assert "-DREQUIRE_SIMD:BOOL=ON" in cmake
    assert "-DWITH_SIMD:BOOL=ON" in cmake
    assert "-DENABLE_SHARED:BOOL=OFF" in cmake
    assert "-DWITH_TOOLS:BOOL=OFF" in cmake
    assert "-DWITH_TESTS:BOOL=OFF" in cmake
    assert "-DWITH_CRT_DLL:BOOL=ON" in cmake
    assert "-DCMAKE_C_VISIBILITY_PRESET:STRING=hidden" in cmake
    assert "-DCMAKE_VISIBILITY_INLINES_HIDDEN:BOOL=ON" in cmake
    assert "-DCMAKE_BUILD_TYPE:STRING=" in cmake
    assert "-DCMAKE_C_COMPILER:FILEPATH=" in cmake
    assert "-DCMAKE_TOOLCHAIN_FILE:FILEPATH=" in cmake
    assert 'if(CMAKE_VERSION VERSION_GREATER_EQUAL "3.24")' in cmake


def test_qualification_selector_is_default_off_and_rejects_implicit_switch():
    cmake = QUALIFICATION_CMAKE.read_text(encoding="utf-8")
    assert re.search(
        r"option\(\s*SCENEIO_BUILD_BACKEND_QUALIFICATION\s+"
        r'"[^"]+"\s+OFF\s*\)',
        cmake,
    )
    assert re.search(
        r'set\(\s*SCENEIO_INTERNAL_JPEG_DEFAULT_BACKEND\s+"stb"\s*\)',
        cmake,
    )
    assert re.search(
        r'set\(\s*SCENEIO_QUALIFICATION_JPEG_BACKEND\s+""',
        cmake,
    )
    assert "A JPEG qualification override requires " in cmake
    conditional = cmake.index('if(SCENEIO_EFFECTIVE_JPEG_BACKEND STREQUAL "libjpeg-turbo")')
    external = cmake.index("ExternalProject_Add(sceneio_libjpeg_turbo")
    assert conditional < external


def test_runtime_backend_marker_exists_only_in_explicit_qualification_build():
    expected = os.environ.get("SCENEIO_EXPECT_JPEG_BACKEND")
    marker = getattr(_core, "_jpeg_backend_id", None)
    if expected is None:
        assert marker is None
        native = Path(_core.__file__).read_bytes()
        assert b"libjpeg-turbo-3.2.0" not in native
        assert b"tj3Compress8" not in native
        return
    assert marker is not None
    assert marker() == expected


def test_jpeg_backend_sources_are_private_and_split_from_bindings():
    common = (ROOT / "src/cpp/codecs/images/jpeg.cpp").read_text(encoding="utf-8")
    retained = (ROOT / "src/cpp/codecs/images/jpeg_stb.cpp").read_text(encoding="utf-8")
    candidate = (ROOT / "src/cpp/qualification/jpeg_turbo.cpp").read_text(encoding="utf-8")
    sources = (ROOT / "cmake/SceneIOSources.cmake").read_text(encoding="utf-8")
    targets = (ROOT / "cmake/SceneIOTargets.cmake").read_text(encoding="utf-8")
    cmake = QUALIFICATION_CMAKE.read_text(encoding="utf-8")
    assert "void register_jpeg" in common
    assert "validate_stream" in common
    assert "validate_write" in common
    assert "void guard_dimensions" in common
    assert "stbi_load_from_memory" not in common
    assert "tj3Decompress8" not in common
    assert "stbi_load_from_memory" in retained
    assert "void guard_dimensions" not in retained
    assert "#ifndef SCENEIO_USE_LIBJPEG_TURBO" in retained
    assert '#error "jpeg_turbo.cpp requires SCENEIO_USE_LIBJPEG_TURBO"' in candidate
    assert "tj3Decompress8" in candidate
    assert "tj3Compress8" in candidate
    assert "src/cpp/qualification/jpeg_turbo.cpp" not in sources
    assert "src/cpp/qualification/jpeg_turbo.cpp" in cmake
    assert "target_sources(_core PRIVATE ${SCENEIO_SELECTED_BACKEND_SOURCES})" in targets


def test_qualification_manifest_records_reproducible_toolchain_inputs():
    cmake = QUALIFICATION_CMAKE.read_text(encoding="utf-8")
    required_fields = {
        "schema_version",
        "jpeg_backend",
        "internal_jpeg_default",
        "qualification_jpeg_override",
        "generator",
        "generator_platform",
        "generator_toolset",
        "cmake_version",
        "multi_config",
        "outer_configuration",
        "external_build_type",
        "system_name",
        "system_processor",
        "c_compiler",
        "c_compiler_id",
        "c_compiler_version",
        "candidate_crt",
        "external_cmake_cache",
        "option_fingerprint_sha256",
        "symbol_export_policy",
        "simd_required",
        "simd_architecture",
        "nasm_compiler",
        "nasm_version",
        "nasm_sha256",
    }
    for field in required_fields:
        assert f'\\"{field}\\"' in cmake
    assert "if(_sceneio_generator_is_multi_config)" in cmake
    assert "$<CONFIG>/" not in cmake
    assert "BUILD_BYPRODUCTS ${_sceneio_jpeg_turbo_byproducts}" in cmake
    assert "IMPORTED_CONFIGURATIONS" in cmake
    assert "CMAKE_CONFIGURATION_TYPES" in cmake
    assert "if(WIN32)" not in cmake
    assert "LINKER:--exclude-libs,ALL" in cmake
    assert "LINKER:-exported_symbol,_PyInit__core" in cmake


def test_candidate_build_records_generated_simd_configuration():
    qualification = QUALIFICATION_CMAKE.read_text(encoding="utf-8")
    targets = TARGETS_CMAKE.read_text(encoding="utf-8")
    recorder = SIMD_CMAKE.read_text(encoding="utf-8")

    assert "SCENEIO_SELECTED_BACKEND_SIMD_HEADER" in qualification
    assert "SCENEIO_SELECTED_BACKEND_SIMD_EVIDENCE" in qualification
    assert "jconfigint.h" in qualification
    assert "SceneIORecordJpegSimd.cmake" in targets
    assert "POST_BUILD" in targets
    assert "SIMD_ARCHITECTURE" in recorder
    assert "generated_header_sha256" in recorder
    assert "file(SHA256" in recorder
