from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSES = ROOT / "LICENSES"

EXPECTED_NOTICES = {
    "aousd-core-spec-supplemental.txt",
    "apache-arrow-license.txt",
    "apache-arrow-notice.txt",
    "brush.txt",
    "cgltf.txt",
    "chromium.txt",
    "cbor2.txt",
    "colmap.txt",
    "dav1d.txt",
    "delvewheel.txt",
    "fast-float.txt",
    "gaussian-splats-3d.txt",
    "gsplat.txt",
    "gsply.txt",
    "h5py.txt",
    "hdf5.txt",
    "lazperf-source.txt",
    "lazperf.txt",
    "libjpeg-turbo-IJG.txt",
    "libjpeg-turbo.txt",
    "libe57format.txt",
    "libaom-patents.txt",
    "libaom.txt",
    "libavif.txt",
    "ogg.txt",
    "theora.txt",
    "libwebp-patents.txt",
    "libwebp.txt",
    "libvpx-patents.txt",
    "libvpx.txt",
    "large-io-benchmark-sources.txt",
    "kubric.txt",
    "lodepng.txt",
    "miniz-zip.txt",
    "miniz.txt",
    "microsoft-vc-runtime.txt",
    "musl-log1p.txt",
    "nanobind.txt",
    "nlohmann-json-source.txt",
    "nlohmann-json.txt",
    "ncore.txt",
    "niantic-spz.txt",
    "numcodecs.txt",
    "openusd.txt",
    "opsiclear-colmap-mod.txt",
    "pillow.txt",
    "pye57.txt",
    "pyyaml.txt",
    "pyquaternion.txt",
    "scipy.txt",
    "sqlite.txt",
    "splat-transform.txt",
    "stb.txt",
    "tinyexr.txt",
    "tinyobjloader.txt",
    "tifffile.txt",
    "tinyusdz.txt",
    "tinyvdb.txt",
    "xerces-c-notice.txt",
    "zstd-source.txt",
    "zstd.txt",
    "zarr.txt",
}

FETCHCONTENT_NOTICE = {}

VENDORED_NOTICE = {
    "cgltf": "cgltf.txt",
    "fast_float": "fast-float.txt",
    "lazperf": "lazperf.txt",
    "libwebp": "libwebp.txt",
    "libvpx": "libvpx.txt",
    "ogg": "ogg.txt",
    "theora": "theora.txt",
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
    "libvpx": {
        "version": "v1.16.0-178-g4780fac96",
        "commit": "4780fac9612992f8584227ea508c298fe8c01d05",
        "archive_sha256": (
            "729c623b8038c5cd68abacdb5171f4126"
            "dfc4e86bb09d0da63be7639c440638b"
        ),
        "notice": "libvpx.txt",
        "license": "LICENSE",
        "manifest": "SOURCE_MANIFEST.sha256",
        "path_sorted_manifest": True,
        "manifest_sha256": (
            "74539bb9a912b58afc11278a52efe95c"
            "aea47539045c82bc1e44ae88f495aaa5"
        ),
        "cmake_patterns": (
            (
                r'^set\(libvpx_SOURCE_DIR '
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/libvpx"\)$'
            ),
            (
                r"add_subdirectory\(\s*"
                r'"\$\{libvpx_SOURCE_DIR\}"\s*'
                r'"\$\{CMAKE_CURRENT_BINARY_DIR\}/libvpx"\s*'
                r"EXCLUDE_FROM_ALL\)"
            ),
            (
                r"set_property\(TARGET sceneio_vpx PROPERTY "
                r"C_VISIBILITY_PRESET hidden\)"
            ),
        ),
    },
    "ogg": {
        "version": "1.3.6",
        "commit": "be05b13e98b048f0b5a0f5fa8ce514d56db5f822",
        "archive_sha256": (
            "4463e305bd1d733db08ecd02404384951"
            "57e4501d41efedf4b8e38ce1522718a"
        ),
        "notice": "ogg.txt",
        "license": "COPYING",
        "manifest": "SOURCE_MANIFEST.sha256",
        "path_sorted_manifest": True,
        "manifest_sha256": (
            "504822196a6557883062aa6e93fde7da"
            "0f2677b71b6bd4c1b2a61d39b640767f"
        ),
        "cmake_patterns": (
            (
                r'^set\(libogg_SOURCE_DIR '
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/ogg"\)$'
            ),
            (
                r"add_subdirectory\(\s*"
                r'"\$\{libogg_SOURCE_DIR\}"\s*'
                r'"\$\{CMAKE_CURRENT_BINARY_DIR\}/libogg"\s*'
                r"EXCLUDE_FROM_ALL\)"
            ),
            r"set_property\(TARGET ogg PROPERTY POSITION_INDEPENDENT_CODE ON\)",
        ),
    },
    "theora": {
        "version": "1.2.0",
        "commit": "8e4808736e9c181b971306cc3f05df9e61354004",
        "archive_sha256": (
            "c3e5af504d1393f4e93a9fc371b553cf"
            "e953644568fecb76dd9a8ae2df62cd1c"
        ),
        "notice": "theora.txt",
        "license": "COPYING",
        "manifest": "SOURCE_MANIFEST.sha256",
        "path_sorted_manifest": True,
        "manifest_sha256": (
            "99b328e5a9d97aeb577be8355e57101f"
            "9288b36af1a7eca38331ea5d356a5b37"
        ),
        "upstream_manifest": "UPSTREAM_MANIFEST.sha256",
        "upstream_manifest_sha256": (
            "49d68df1d5aabd055112319d927dd657d"
            "ee3bddef0238839e2743d90c0900219"
        ),
        "patch": "LOCAL_CHANGES.patch",
        "patch_sha256": (
            "790a9423f4e308e9d6971c7796dae473"
            "95618c1f35b42d3361ebe14cc7a13bc2"
        ),
        "patched_files": (
            "lib/analyze.c",
            "lib/mcenc.c",
            "lib/tokenize.c",
        ),
        "auxiliary_files": (
            "LOCAL_CHANGES.patch",
            "UPSTREAM_MANIFEST.sha256",
        ),
        "cmake_patterns": (
            (
                r'^set\(libtheora_SOURCE_DIR '
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/theora"\)$'
            ),
            r"^add_library\(theora_static STATIC \$\{_sceneio_theora_sources\}\)$",
            r"^target_link_libraries\(theora_static PUBLIC ogg\)$",
            (
                r"target_compile_definitions\(\s*theora_static PRIVATE "
                r"OC_X86_ASM OC_X86_64_ASM\)"
            ),
            (
                r"set_property\(TARGET theora_static PROPERTY "
                r"POSITION_INDEPENDENT_CODE ON\)"
            ),
        ),
    },
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
    "lazperf": {
        "version": "3.4.0",
        "commit": "b7bbe26109dc986f42d4fc80b8de3d2b6ca634ce",
        "archive_sha256": (
            "17df34ca64cc60e107f0c214db4729c5"
            "4a514df4e32de5bc1b8b7b7c5a805a56"
        ),
        "notice": "lazperf.txt",
        "source_notice": "lazperf-source.txt",
        "source_notice_file": "NOTICE.txt",
        "source_notice_markers": (
            "Mathias Panzenböck",
            "http://github.com/panzi/mathfun/blob/master/examples/portable_endian.h",
        ),
        "source_notice_sources": ("cpp/lazperf/portable_endian.hpp",),
        "packaged_notice_markers": (
            '"License": Public Domain',
            "place this file hereby into the public domain",
            '"dual licensed" under the BSD,',
        ),
        "license": "COPYING",
        "manifest": "SOURCE_MANIFEST.sha256",
        "path_sorted_manifest": True,
        "manifest_sha256": (
            "f7811663db8e3af8a8e02f264855da57"
            "c1ed34bca7be56f8024a6d272e002ab2"
        ),
        "upstream_manifest": "UPSTREAM_MANIFEST.sha256",
        "upstream_manifest_sha256": (
            "25dec34174ea9ec01899bc7299724819e"
            "b94659de264ae1dbce046ff9c7be737"
        ),
        "patch": "LOCAL_CHANGES.patch",
        "patch_sha256": (
            "d35a90f323511ddb371547c4c420bac6"
            "390ef90b498d9ccec244f496a9cceb04"
        ),
        "patched_files": (
            "cpp/lazperf/compressor.hpp",
            "cpp/lazperf/decompressor.hpp",
            "cpp/lazperf/detail/field_point10.cpp",
            "cpp/lazperf/detail/field_point14.cpp",
            "cpp/lazperf/detail/field_xyz.hpp",
            "cpp/lazperf/streams.hpp",
            "cpp/lazperf/utils.hpp",
        ),
        "auxiliary_files": (
            "LOCAL_CHANGES.patch",
            "NOTICE.txt",
            "UPSTREAM_MANIFEST.sha256",
        ),
        "cmake_sources": (
            "cpp/lazperf/charbuf.cpp",
            "cpp/lazperf/detail/field_byte10.cpp",
            "cpp/lazperf/detail/field_byte14.cpp",
            "cpp/lazperf/detail/field_gpstime10.cpp",
            "cpp/lazperf/detail/field_nir14.cpp",
            "cpp/lazperf/detail/field_point10.cpp",
            "cpp/lazperf/detail/field_point14.cpp",
            "cpp/lazperf/detail/field_rgb10.cpp",
            "cpp/lazperf/detail/field_rgb14.cpp",
            "cpp/lazperf/filestream.cpp",
            "cpp/lazperf/header.cpp",
            "cpp/lazperf/lazperf.cpp",
            "cpp/lazperf/readers.cpp",
            "cpp/lazperf/vlr.cpp",
            "cpp/lazperf/writers.cpp",
        ),
        "cmake_patterns": (
            (
                r"set\(lazperf_SOURCE_DIR\s*"
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/lazperf"\)'
            ),
            r"^add_library\(lazperf_static STATIC \$\{LAZPERF_SOURCES\}\)$",
            (
                r"target_compile_definitions\(\s*lazperf_static\s*"
                r"PUBLIC LAZPERF_VENDORED"
            ),
            (
                r"set_target_properties\(\s*lazperf_static\s*PROPERTIES\s*"
                r"POSITION_INDEPENDENT_CODE ON\s*"
                r"CXX_VISIBILITY_PRESET hidden\s*"
                r"VISIBILITY_INLINES_HIDDEN ON\)"
            ),
        ),
    },
    "libwebp": {
        "version": "1.5.0",
        "commit": "a4d7a715337ded4451fec90ff8ce79728e04126c",
        "archive_sha256": (
            "668c9aba45565e24c27e17f7aaf7060a"
            "399f7f31dba6c97a044e1feacb930f37"
        ),
        "notice": "libwebp.txt",
        "source_notice": "libwebp-patents.txt",
        "source_notice_file": "PATENTS",
        "packaged_notice_markers": (
            "Additional IP Rights Grant (Patents)",
            "perpetual, worldwide, non-exclusive, no-charge,",
            "royalty-free, irrevocable",
        ),
        "license": "COPYING",
        "manifest": "SOURCE_MANIFEST.sha256",
        "path_sorted_manifest": True,
        "manifest_sha256": (
            "17e0a0e557d3b80e464da8ad5832836d"
            "992a7882ec365ff58b33d1fda16f4ba8"
        ),
        "cmake_patterns": (
            (
                r'^set\(libwebp_SOURCE_DIR '
                r'"\$\{PROJECT_SOURCE_DIR\}/src/cpp/third_party/libwebp"\)$'
            ),
            r"^set\(WEBP_BUILD_LIBWEBPMUX ON CACHE BOOL \"\" FORCE\)$",
            r"^set\(WEBP_ENABLE_SIMD ON CACHE BOOL \"\" FORCE\)$",
            (
                r"add_subdirectory\(\s*\"\$\{libwebp_SOURCE_DIR\}\"\s*"
                r"\"\$\{CMAKE_CURRENT_BINARY_DIR\}/libwebp\"\s*"
                r"EXCLUDE_FROM_ALL\)"
            ),
            (
                r"foreach\(_webp_target\s*sharpyuv\s*"
                r"webpdecode webpdspdecode webputilsdecode webpdecoder\s*"
                r"webpencode webpdsp webputils webp webpdemux libwebpmux\)"
            ),
            (
                r"set_target_properties\(\s*\$\{_webp_target\}\s*"
                r"PROPERTIES\s*POSITION_INDEPENDENT_CODE ON\s*"
                r"C_VISIBILITY_PRESET hidden\)"
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


def _reverse_unified_file_patch(final_bytes: bytes, patch_section: str) -> bytes:
    final_lines = final_bytes.decode("utf-8").splitlines(keepends=True)
    patch_lines = patch_section.splitlines(keepends=True)
    original_lines: list[str] = []
    cursor = 0
    index = 0
    hunk_count = 0
    hunk_pattern = re.compile(
        r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
    )

    while index < len(patch_lines):
        match = hunk_pattern.match(patch_lines[index])
        if match is None:
            index += 1
            continue
        hunk_count += 1
        old_count = int(match.group(2) or 1)
        new_start = int(match.group(3))
        new_count = int(match.group(4) or 1)
        new_index = new_start - 1
        assert new_index >= cursor
        original_lines.extend(final_lines[cursor:new_index])
        cursor = new_index
        old_seen = 0
        new_seen = 0
        index += 1

        while index < len(patch_lines) and not patch_lines[index].startswith("@@"):
            line = patch_lines[index]
            if line.startswith(" "):
                assert cursor < len(final_lines)
                assert final_lines[cursor] == line[1:]
                original_lines.append(line[1:])
                cursor += 1
                old_seen += 1
                new_seen += 1
            elif line.startswith("+"):
                assert cursor < len(final_lines)
                assert final_lines[cursor] == line[1:]
                cursor += 1
                new_seen += 1
            elif line.startswith("-"):
                original_lines.append(line[1:])
                old_seen += 1
            elif line.startswith("\\"):
                raise AssertionError("LAZperf patch must preserve final newlines")
            else:
                break
            index += 1
        assert old_seen == old_count
        assert new_seen == new_count

    assert hunk_count
    original_lines.extend(final_lines[cursor:])
    return "".join(original_lines).encode("utf-8")


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
        assert (
            "Copyright" in text
            or "copyright" in text
            or "public domain" in text
            or "patent license" in text
        )


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
            if entry.get("path_sorted_manifest"):
                assert list(expected_files) == sorted(expected_files, key=str.casefold)
            actual_files = {
                path.relative_to(source_root).as_posix()
                for path in source_root.rglob("*")
                if path.is_file()
                and path.name
                not in {
                    "COMMIT.txt",
                    entry["manifest"],
                    *entry.get("auxiliary_files", ()),
                }
            }
            assert actual_files == set(expected_files)

            upstream_manifest_name = entry.get("upstream_manifest")
            if upstream_manifest_name is not None:
                upstream_manifest = source_root / upstream_manifest_name
                upstream_bytes = upstream_manifest.read_bytes()
                assert (
                    hashlib.sha256(upstream_bytes).hexdigest()
                    == entry["upstream_manifest_sha256"]
                )
                assert entry["upstream_manifest_sha256"] in provenance
                upstream_files = {}
                for line in upstream_bytes.decode("utf-8").splitlines():
                    expected_hash, relative_path = line.split("  ", 1)
                    upstream_files[relative_path] = expected_hash
                if entry.get("path_sorted_manifest"):
                    assert list(upstream_files) == sorted(
                        upstream_files, key=str.casefold
                    )
                assert set(upstream_files) == set(expected_files)
                assert {
                    path
                    for path in expected_files
                    if expected_files[path] != upstream_files[path]
                } == set(entry["patched_files"])

                patch = source_root / entry["patch"]
                patch_bytes = patch.read_bytes()
                assert (
                    hashlib.sha256(patch_bytes).hexdigest()
                    == entry["patch_sha256"]
                )
                assert entry["patch_sha256"] in provenance
                patch_text = patch_bytes.decode("utf-8")
                headers = tuple(
                    re.finditer(
                        r"^diff --git a/(.+?) b/\1$",
                        patch_text,
                        re.MULTILINE,
                    )
                )
                assert tuple(match.group(1) for match in headers) == entry[
                    "patched_files"
                ]
                for index, match in enumerate(headers):
                    relative_path = match.group(1)
                    end = (
                        headers[index + 1].start()
                        if index + 1 < len(headers)
                        else len(patch_text)
                    )
                    reconstructed = _reverse_unified_file_patch(
                        (source_root / relative_path).read_bytes(),
                        patch_text[match.start() : end],
                    )
                    assert (
                        hashlib.sha256(reconstructed).hexdigest()
                        == upstream_files[relative_path]
                    )
                    assert "MODIFIED BY SCENEIO (2026)" in (
                        source_root / relative_path
                    ).read_text(encoding="utf-8")
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
        source_notice_file = entry.get("source_notice_file")
        if source_notice_file is not None:
            assert packaged_notice == (
                ROOT / "src/cpp/third_party" / project / source_notice_file
            ).read_bytes().decode("utf-8")
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
        for marker in entry.get("packaged_notice_markers", ()):
            assert marker in packaged_notice

    assert (
        ROOT / "src/cpp/third_party/libvpx/PATENTS"
    ).read_bytes() == (LICENSES / "libvpx-patents.txt").read_bytes()
    libvpx_provenance = (
        ROOT / "src/cpp/third_party/libvpx/COMMIT.txt"
    ).read_text(encoding="utf-8")
    assert "d3345aa1656fdfce4861a2d7080cac649d45e814" in libvpx_provenance
    assert "dbc238fcd68680db2f1d3d9e6257b03a4f42c81e6a3fd3cef6617371d66ffd29" in (
        libvpx_provenance
    )

    musl_root = ROOT / "src/cpp/third_party/musl"
    provenance = (musl_root / "COMMIT.txt").read_text(encoding="utf-8")
    assert "v1.2.5" in provenance
    assert "0784374d561435f7c787a555aeab8ede699ed298" in provenance
    assert (
        "a9a118bbe84d8764da0ea0d28b3ab3fa"
        "e8477fc7e4085d90102b8596fc7c75e4"
    ) in provenance
    header = musl_root / "log1p.hpp"
    header_sha256 = hashlib.sha256(header.read_bytes()).hexdigest()
    assert header_sha256 == (
        "bc02df5cacaf9d563e1fc29729d9f7d3"
        "31e62e709f070f6b19e5c3bc51fd2062"
    )
    assert header_sha256 in provenance
    assert (
        musl_root / "LICENSE.txt"
    ).read_bytes() == (LICENSES / "musl-log1p.txt").read_bytes()
    header_text = header.read_text(encoding="utf-8")
    assert "Copyright (C) 1993 by Sun Microsystems, Inc." in header_text
    assert "Permission to use, copy, modify, and distribute" in header_text
    assert '#include "third_party/musl/log1p.hpp"' in (
        ROOT / "src/cpp/codecs/splats/sog.cpp"
    ).read_text(encoding="utf-8")


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

        expected_sources = entry.get("cmake_sources")
        if expected_sources is not None:
            source_block = re.search(
                rf"set\({project.upper()}_SOURCES\s+(.*?)\)",
                dependencies,
                re.DOTALL,
            )
            assert source_block is not None
            assert tuple(
                re.findall(
                    rf'"\$\{{{project}_SOURCE_DIR\}}/(.+?)"',
                    source_block.group(1),
                )
            ) == expected_sources
