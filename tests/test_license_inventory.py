from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSES = ROOT / "LICENSES"

EXPECTED_NOTICES = {
    "cgltf.txt",
    "fast-float.txt",
    "lazperf.txt",
    "libjpeg-turbo-IJG.txt",
    "libjpeg-turbo.txt",
    "libwebp.txt",
    "lodepng.txt",
    "miniz-zip.txt",
    "miniz.txt",
    "nanobind.txt",
    "nlohmann-json-source.txt",
    "nlohmann-json.txt",
    "sqlite.txt",
    "stb.txt",
    "tinyexr.txt",
    "tinyobjloader.txt",
    "zstd-source.txt",
    "zstd.txt",
}

FETCHCONTENT_NOTICE = {
    "lazperf": "lazperf.txt",
    "libwebp": "libwebp.txt",
}

VENDORED_NOTICE = {
    "cgltf": "cgltf.txt",
    "fast_float": "fast-float.txt",
    "lodepng": "lodepng.txt",
    "miniz": "miniz.txt",
    "nlohmann_json": "nlohmann-json.txt",
    "sqlite": "sqlite.txt",
    "stb": "stb.txt",
    "tinyexr": "tinyexr.txt",
    "tinyobjloader": "tinyobjloader.txt",
    "zstd": "zstd.txt",
}

SOURCE_CLOSURE = {
    "fast_float": {
        "version": "6.1.6",
        "commit": "00c8c7b0d5c722d2212568d915a39ea73b08b973",
        "archive_sha256": (
            "4458aae4b0eb55717968edda42987cabf"
            "5f7fc737aee8fede87a70035dba9ab0"
        ),
        "notice": "fast-float.txt",
        "license": "LICENSE-MIT",
        "manifest": "SOURCE_MANIFEST.sha256",
        "manifest_sha256": (
            "dd075e6dfb33eef1eac73af549cda609"
            "4b43f6ea64ae3528e1b25034f66767b5"
        ),
        "cmake_patterns": (
            (
                r"set\(fast_float_SOURCE_DIR\s*"
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/fast_float"\)'
            ),
            r"^add_library\(fast_float INTERFACE\)$",
            (
                r"^add_library\(FastFloat::fast_float "
                r"ALIAS fast_float\)$"
            ),
            (
                r"target_include_directories\(\s*fast_float INTERFACE "
                r'"\$\{fast_float_SOURCE_DIR\}/include"\)'
            ),
            r"^target_compile_features\(fast_float INTERFACE cxx_std_11\)$",
            (
                r"if\(MSVC_VERSION GREATER 1910\)\s*"
                r"target_compile_options\(fast_float INTERFACE /permissive-\)\s*"
                r"endif\(\)"
            ),
        ),
    },
    "miniz": {
        "version": "3.0.2",
        "commit": "293d4db1b7d0ffee9756d035b9ac6f7431ef8492",
        "archive_sha256": (
            "ada38db0b703a56d3dd6d57bf84a9c5d"
            "664921d870d8fea4db153979fb5332c5"
        ),
        "notice": "miniz.txt",
        "source_notice": "miniz-zip.txt",
        "license": "LICENSE",
        "cmake_patterns": (
            (
                r'^set\(miniz_SOURCE_DIR '
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/miniz"\)$'
            ),
            (
                r'^add_library\(miniz_static STATIC '
                r'"\$\{miniz_SOURCE_DIR\}/miniz\.c"\)$'
            ),
            (
                r"set_target_properties\(\s*miniz_static\s*PROPERTIES\s*"
                r"POSITION_INDEPENDENT_CODE ON\s*C_VISIBILITY_PRESET hidden\)"
            ),
        ),
        "files": {
            "ChangeLog.md": (
                "261c5cfb87942b5c47735b98ae2fa87b"
                "a5f3058d3c755838756b6117f3b0c0dd"
            ),
            "LICENSE": (
                "0115478d567121238cf6cc1c0c361926"
                "cf07a49d9e4c9e66da97fac6a01646b3"
            ),
            "miniz.c": (
                "0fcdc9888cb3a29ca8f176bac087e5fe"
                "6c7258a6ab06b1c271c1e109a11d3740"
            ),
            "miniz.h": (
                "295d1a0041aea09609598c0f1f35c197"
                "7ca05ad662acbadcfdaac44c140af37b"
            ),
            "readme.md": (
                "b4ea367be28a36e5386f65118b73962b"
                "c659a67936d248be68b7a7c03b8d359b"
            ),
        },
    },
    "nlohmann_json": {
        "version": "3.11.3",
        "commit": "9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03",
        "archive_sha256": (
            "d6c65aca6b1ed68e7a182f4757257b10"
            "7ae403032760ed6ef121c9d55e81757d"
        ),
        "notice": "nlohmann-json.txt",
        "source_notice": "nlohmann-json-source.txt",
        "source_notice_markers": (
            "2013-2023 Niels Lohmann",
            "2016-2021 Evan Nemerson",
            "2009 Florian Loitsch",
            "2008-2009 Björn Hoehrmann",
            "2018 The Abseil Authors",
            "10cb35e459f5ecca5b2ff107635da0bfa41011b4",
        ),
        "source_notice_sources": (
            "include/nlohmann/thirdparty/hedley/hedley.hpp",
            "include/nlohmann/detail/conversions/to_chars.hpp",
            "include/nlohmann/detail/output/serializer.hpp",
            "include/nlohmann/detail/meta/cpp_future.hpp",
        ),
        "license": "LICENSE.MIT",
        "manifest": "SOURCE_MANIFEST.sha256",
        "manifest_sha256": (
            "7c67147cb0569a82381f7452ef87085c"
            "0fd0195bda96f7db7eeb3bb81df4a88b"
        ),
        "cmake_patterns": (
            (
                r"set\(nlohmann_json_SOURCE_DIR\s*"
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/nlohmann_json"\)'
            ),
            r"^add_library\(nlohmann_json INTERFACE\)$",
            (
                r"^add_library\(nlohmann_json::nlohmann_json "
                r"ALIAS nlohmann_json\)$"
            ),
            (
                r"^target_compile_features\(nlohmann_json "
                r"INTERFACE cxx_std_11\)$"
            ),
            (
                r"target_include_directories\(\s*nlohmann_json INTERFACE "
                r'"\$\{nlohmann_json_SOURCE_DIR\}/include"\)'
            ),
        ),
    },
    "zstd": {
        "version": "1.5.6",
        "commit": "794ea1b0afca0f020f4e57b6732332231fb23c70",
        "archive_sha256": (
            "8c29e06cf42aacc1eafc4077ae2ec6c6"
            "fcb96a626157e0593d5e82a34fd403c1"
        ),
        "notice": "zstd.txt",
        "source_notice": "zstd-source.txt",
        "source_notice_markers": (
            "Copyright (c) 2003-2008 Yuta Mori All Rights Reserved.",
            "Copyright 2020 Jan Tojnar",
            "SPDX-License-Identifier: (MIT OR CC0-1.0)",
        ),
        "source_notice_sources": (
            "lib/dictBuilder/divsufsort.c",
            "cmake/upstream/CMakeModules/JoinPaths.cmake",
        ),
        "license": "LICENSE",
        "manifest": "SOURCE_MANIFEST.sha256",
        "manifest_sha256": (
            "f94a91b60a5a9b69beb5978d3b58467c"
            "60b33eead1d29f12e7e8d9a20ecb5b24"
        ),
        "cmake_patterns": (
            (
                r'^set\(zstd_SOURCE_DIR '
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/zstd"\)$'
            ),
            r'^set\(ZSTD_BUILD_SHARED OFF CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_BUILD_STATIC ON CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_BUILD_COMPRESSION ON CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_BUILD_DECOMPRESSION ON CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_BUILD_DICTBUILDER ON CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_BUILD_DEPRECATED OFF CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_BUILD_PROGRAMS OFF CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_BUILD_TESTS OFF CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_BUILD_CONTRIB OFF CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_LEGACY_SUPPORT OFF CACHE BOOL "" FORCE\)$',
            r'^set\(ZSTD_MULTITHREAD_SUPPORT ON CACHE BOOL "" FORCE\)$',
            (
                r'add_subdirectory\(\s*"\$\{zstd_SOURCE_DIR\}/cmake/upstream"\s*'
                r'"\$\{CMAKE_BINARY_DIR\}/_deps/zstd-build"\s*'
                r"EXCLUDE_FROM_ALL\)"
            ),
            (
                r"set_target_properties\(\s*libzstd_static\s*PROPERTIES\s*"
                r"POSITION_INDEPENDENT_CODE ON\s*"
                r"C_VISIBILITY_PRESET hidden\)"
            ),
        ),
    },
}

EXTERNAL_PROJECT_NOTICE = {
    "sceneio_libjpeg_turbo": {
        "libjpeg-turbo-IJG.txt",
        "libjpeg-turbo.txt",
    },
}


def test_license_directory_is_complete_and_packaged() -> None:
    actual = {path.name for path in LICENSES.glob("*.txt")}
    assert actual == EXPECTED_NOTICES
    assert (LICENSES / "README.md").is_file()

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = set(config["project"]["license-files"])
    assert {"LICENSE", "LICENSES/*.md", "LICENSES/*.txt"} <= patterns


def test_compiled_dependencies_have_attribution_entries() -> None:
    cmake = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "CMakeLists.txt",
            *sorted((ROOT / "cmake").glob("*.cmake")),
        )
    )
    fetched = set(re.findall(r"FetchContent_Declare\(\s*([A-Za-z0-9_]+)", cmake))
    assert fetched == set(FETCHCONTENT_NOTICE)

    external = set(re.findall(r"ExternalProject_Add\(\s*([A-Za-z0-9_]+)", cmake))
    assert external == set(EXTERNAL_PROJECT_NOTICE)

    third_party_references = set(re.findall(r"src/cpp/third_party/([A-Za-z0-9_]+)", cmake))
    assert third_party_references == set(VENDORED_NOTICE)

    index = (LICENSES / "README.md").read_text(encoding="utf-8")
    for notice in EXPECTED_NOTICES:
        assert f"]({notice})" in index

    assert ("This software is based in part on the work of the Independent JPEG Group.") in index


def test_notice_files_are_nonempty_utf8_text() -> None:
    for name in EXPECTED_NOTICES:
        text = (LICENSES / name).read_text(encoding="utf-8")
        assert len(text) >= 250
        assert text.endswith("\n")
        assert "Copyright" in text or "copyright" in text or "public domain" in text


def test_repository_contained_native_sources_match_recorded_hashes() -> None:
    for project, entry in SOURCE_CLOSURE.items():
        source_root = ROOT / "src/cpp/third_party" / project
        provenance = (source_root / "COMMIT.txt").read_text(encoding="utf-8")
        assert entry["version"] in provenance
        assert entry["commit"] in provenance
        assert entry["archive_sha256"] in provenance
        if "manifest" in entry:
            manifest = source_root / entry["manifest"]
            manifest_bytes = manifest.read_bytes()
            assert hashlib.sha256(manifest_bytes).hexdigest() == entry["manifest_sha256"]
            assert entry["manifest_sha256"] in provenance
            expected_files = {}
            for line in manifest_bytes.decode("utf-8").splitlines():
                expected_hash, relative_path = line.split("  ", 1)
                path = Path(relative_path)
                assert not path.is_absolute()
                assert ".." not in path.parts
                expected_files[relative_path] = expected_hash
            actual_files = {
                path.relative_to(source_root).as_posix()
                for path in source_root.rglob("*")
                if path.is_file()
                and path.name not in {"COMMIT.txt", entry["manifest"]}
            }
            assert actual_files == set(expected_files)
        else:
            expected_files = entry["files"]

        for relative_path, expected_hash in expected_files.items():
            source = source_root / relative_path
            actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            assert actual_hash == expected_hash, source
            if "manifest" not in entry:
                assert expected_hash in provenance


def test_repository_contained_native_licenses_are_exact_distribution_copies() -> None:
    for project, entry in SOURCE_CLOSURE.items():
        source_license = (
            ROOT / "src/cpp/third_party" / project / entry["license"]
        ).read_bytes()
        distribution_notice = (LICENSES / entry["notice"]).read_bytes()
        assert distribution_notice == source_license

        source_notice_name = entry.get("source_notice")
        if source_notice_name is None:
            continue
        packaged_notice = (LICENSES / source_notice_name).read_bytes().decode("utf-8")
        if project == "miniz":
            source_text = (
                ROOT / "src/cpp/third_party" / project / "miniz.c"
            ).read_bytes().decode("utf-8")
            blocks = re.findall(
                r"/\*{10,}\n(.*?)\*{10,}/", source_text, re.DOTALL
            )
            source_block = next(
                block for block in blocks if "Martin Raiber" in block
            )
            source_notice = "\n".join(
                line[3:] if line.startswith(" * ") else ""
                for line in source_block.splitlines()
            ).strip()
            assert packaged_notice == f"{source_notice}\n"

        selected_sources = "\n".join(
            (
                ROOT / "src/cpp/third_party" / project / relative_path
            ).read_bytes().decode("utf-8")
            for relative_path in entry.get("source_notice_sources", ())
        )
        for marker in entry.get("source_notice_markers", ()):
            assert marker in selected_sources
            assert marker in packaged_notice


def test_repository_contained_native_sources_replace_their_fetches() -> None:
    dependencies = (ROOT / "cmake/SceneIODependencies.cmake").read_text(
        encoding="utf-8"
    )
    all_cmake = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "CMakeLists.txt", *sorted((ROOT / "cmake").glob("*.cmake")))
    )
    for project, entry in SOURCE_CLOSURE.items():
        assert not re.search(
            rf"FetchContent_Declare\(\s*{re.escape(project)}\b",
            all_cmake,
        )
        for pattern in entry["cmake_patterns"]:
            assert re.search(pattern, dependencies, re.MULTILINE | re.DOTALL)
