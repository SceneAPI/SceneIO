from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSES = ROOT / "LICENSES"

EXPECTED_NOTICES = {
    "cgltf.txt",
    "fast-float.txt",
    "lazperf.txt",
    "libwebp.txt",
    "lodepng.txt",
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
    "miniz": "miniz.txt",
    "nlohmann_json": "nlohmann-json.txt",
    "zstd": "zstd.txt",
}

VENDORED_NOTICE = {
    "cgltf": "cgltf.txt",
    "lodepng": "lodepng.txt",
    "sqlite": "sqlite.txt",
    "stb": "stb.txt",
    "tinyexr": "tinyexr.txt",
    "tinyobjloader": "tinyobjloader.txt",
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

    third_party_references = set(
        re.findall(r"src/cpp/third_party/([A-Za-z0-9_]+)", cmake)
    )
    assert third_party_references == set(VENDORED_NOTICE)

    index = (LICENSES / "README.md").read_text(encoding="utf-8")
    for notice in {
        "nanobind.txt",
        *FETCHCONTENT_NOTICE.values(),
        *VENDORED_NOTICE.values(),
    }:
        assert f"]({notice})" in index


def test_notice_files_are_nonempty_utf8_text() -> None:
    for name in EXPECTED_NOTICES:
        text = (LICENSES / name).read_text(encoding="utf-8")
        assert len(text) >= 250
        assert text.endswith("\n")
        assert "Copyright" in text or "copyright" in text or "public domain" in text
