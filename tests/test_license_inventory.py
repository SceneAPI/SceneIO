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
    "nlohmann-json.txt",
    "sqlite.txt",
    "stb.txt",
    "tinyexr.txt",
    "tinyobjloader.txt",
    "zstd.txt",
}

FETCHCONTENT_NOTICE = {
    "fast_float": "fast-float.txt",
    "lazperf": "lazperf.txt",
    "libwebp": "libwebp.txt",
    "nlohmann_json": "nlohmann-json.txt",
    "zstd": "zstd.txt",
}

VENDORED_NOTICE = {
    "cgltf": "cgltf.txt",
    "lodepng": "lodepng.txt",
    "miniz": "miniz.txt",
    "sqlite": "sqlite.txt",
    "stb": "stb.txt",
    "tinyexr": "tinyexr.txt",
    "tinyobjloader": "tinyobjloader.txt",
}

SOURCE_CLOSURE = {
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
        for relative_path, expected_hash in entry["files"].items():
            source = source_root / relative_path
            actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            assert actual_hash == expected_hash, source
            assert expected_hash in provenance


def test_repository_contained_native_licenses_are_exact_distribution_copies() -> None:
    for project, entry in SOURCE_CLOSURE.items():
        source_license = (
            ROOT / "src/cpp/third_party" / project / entry["license"]
        ).read_bytes()
        distribution_notice = (LICENSES / entry["notice"]).read_bytes()
        assert distribution_notice == source_license

        source_text = (
            ROOT / "src/cpp/third_party" / project / "miniz.c"
        ).read_bytes().decode("utf-8")
        blocks = re.findall(r"/\*{10,}\n(.*?)\*{10,}/", source_text, re.DOTALL)
        source_block = next(block for block in blocks if "Martin Raiber" in block)
        source_notice = "\n".join(
            line[3:] if line.startswith(" * ") else ""
            for line in source_block.splitlines()
        ).strip()
        packaged_notice = (LICENSES / entry["source_notice"]).read_bytes().decode(
            "utf-8"
        )
        assert packaged_notice == f"{source_notice}\n"


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
