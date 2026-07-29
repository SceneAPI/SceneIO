"""Schema and completeness checks for the codec performance ledger."""

from __future__ import annotations

import tomllib
from collections import Counter, defaultdict
from pathlib import Path

from sceneio.io._builtin_manifest import (
    BUILTIN_OWNERSHIP,
    CANONICAL_BUILTIN_IDS,
)

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "bench" / "PERFORMANCE_STATUS.toml"

_ALLOWED_STATES = {
    "qualified",
    "provisional",
    "known_gap",
    "native_by_necessity",
    "not_applicable",
}
_DIRECTIONS = {"encode", "decode"}
_SPECIAL_PROFILES = {
    "png": {"rgb8_default", "rgb16_default"},
    "webp": {"lossless_rgb8_default", "lossy_rgb8_q90"},
    "ply": {
        "point_binary_little_endian",
        "point_binary_big_endian",
        "point_ascii",
    },
    "pcd": {"binary", "binary_compressed", "ascii"},
    "exr": {
        "scanline_float32_zip",
        "scanline_float32_no",
        "scanline_float32_rle",
        "scanline_float32_zips",
        "scanline_float32_piz",
    },
    "las": {
        "fresh_standard_formats_0_2",
        "legacy_decode_formats_1_3",
        "extended_decode_formats_6_8",
        "preserved_waveform_formats_4_5",
        "preserved_waveform_formats_9_10",
    },
    "laz": {"legacy_formats_0_3", "layered_formats_6_8"},
    "spz": {"legacy_v3_gzip", "ngsp_v4_zstd"},
}


def _ledger():
    return tomllib.loads(LEDGER.read_text(encoding="utf-8"))


def test_performance_ledger_has_stable_schema_and_exact_builtin_coverage():
    ledger = _ledger()
    assert ledger["schema_version"] == 1
    assert (ROOT / ledger["baseline_document"]).is_file()
    assert set(ledger["status_definitions"]) == _ALLOWED_STATES
    assert ledger["r6_release_decision"] == (
        "user-directed lean full-closure plan, 2026-07-28"
    )
    assert ledger["r6_release_policy"] == (
        "verified current backends are accepted as the R6 release baseline; "
        "provisional candidate-comparison gaps remain an optional post-R6 "
        "backlog and do not claim qualification"
    )
    assert ledger["r6_unmeasured_profile_policy"] == (
        "14 specialized provisional rows are accepted for correctness and "
        "compatibility only; R6 makes no profile-specific performance claim "
        "for them"
    )

    codecs = ledger["codec"]
    assert tuple(item["id"] for item in codecs) == CANONICAL_BUILTIN_IDS
    assert len({item["id"] for item in codecs}) == 54
    for item in codecs:
        ownership = BUILTIN_OWNERSHIP[item["id"]]
        assert item["family"] == ownership.family
        assert item["implementation_owner"] == ownership.implementation_owner
        assert item["adapter"] == "repo"
        assert item["sources"]
        assert item["accepted_subset"]
        for path in (
            *item["sources"],
            item["source_suite"],
            *item.get("additional_source_suites", ()),
            item["documentation"],
        ):
            assert (ROOT / path).exists(), f"{item['id']}: {path}"


def test_performance_operations_cover_required_profiles_and_directions():
    operations = _ledger()["operation"]
    assert len(operations) == 140
    keys = [
        (item["codec_id"], item["profile"], item["direction"])
        for item in operations
    ]
    assert len(keys) == len(set(keys))
    assert {item["codec_id"] for item in operations} == set(CANONICAL_BUILTIN_IDS)

    profiles: dict[str, set[str]] = defaultdict(set)
    directions: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in operations:
        profiles[item["codec_id"]].add(item["profile"])
        directions[item["codec_id"], item["profile"]].add(item["direction"])
    for codec_id in CANONICAL_BUILTIN_IDS:
        assert profiles[codec_id] == _SPECIAL_PROFILES.get(codec_id, {"default"})
    assert all(actual == _DIRECTIONS for actual in directions.values())


def test_performance_rows_are_honest_about_initial_evidence():
    operations = _ledger()["operation"]
    states = Counter(item["status"] for item in operations)
    assert states == {
        "provisional": 132,
        "known_gap": 2,
        "not_applicable": 6,
    }
    provisional = [
        item for item in operations if item["status"] == "provisional"
    ]
    assert Counter(
        tuple(item["evidence_gaps"]) for item in provisional
    ) == {
        ("candidate comparison on all required toolchains",): 118,
        (
            "profile-specific current-backend measurement missing",
            "candidate comparison on all required toolchains",
        ): 14,
    }
    assert all(item["candidate_backends"] == [] for item in provisional)
    for item in operations:
        assert item["direction"] in _DIRECTIONS
        assert item["status"] in _ALLOWED_STATES
        assert item["transport_status"] == (
            "not_applicable"
            if item["status"] == "not_applicable"
            else "qualified"
        )
        assert isinstance(item["settings"], dict)
        assert item["fidelity"]
        assert item["comparator"]
        assert item["fixture"]
        assert item["backend"]
        assert item["backend_owner"] in {"repo", "vendored", "fetched"}
        assert (ROOT / item["backend_source"]).exists()
        assert item["backend_version"]
        assert item["correctness_evidence"]
        assert item["evidence_gaps"]
        for path in (*item["correctness_evidence"], *item["benchmark_evidence"]):
            assert (ROOT / path).is_file()
        if (
            item["status"] != "not_applicable"
            and not item["benchmark_evidence"]
        ):
            assert (
                "profile-specific current-backend measurement missing"
                in item["evidence_gaps"]
            )
        if item["status"] == "known_gap":
            assert item["codec_id"] == "jpeg"
            assert item["candidate_backends"] == []
            assert item["rejected_backends"] == [
                {
                    "id": "libjpeg-turbo",
                    "version": "3.2.0",
                    "scope": "combined_default",
                    "platform": "windows_msvc_x86_64",
                    "source_commit": (
                        "7a88e7c726eed5bdd4ff0ad05b381c9795af9dfe"
                    ),
                    "report_sha256": (
                        "f32b7c60f19956438023c51cc9c0b07f"
                        "44ace79c66dff4a43c30fc7cfdcd80b1"
                    ),
                    "gate": "quality-profile:rgb8_q95_444",
                    "observed_delta_db": -0.05824218633100031,
                    "required_delta_db": -0.05,
                }
            ]
        elif item["status"] in {"native_by_necessity", "not_applicable"}:
            assert item["candidate_backends"] == []


def test_performance_ledger_pins_material_backend_dependencies():
    operations = _ledger()["operation"]
    fast_float_default_decoders = {
        "bal",
        "bundler",
        "colmap_sparse_txt",
        "euroc_state",
        "g2o",
        "kalibr",
        "nvm",
        "off",
        "opencv_xml",
        "opencv_yaml",
        "ply_mesh",
        "pts",
        "ros_camera_info",
        "stl",
        "xyz",
    }
    json_codecs = {"openmvg", "safetensors", "transforms_json"}

    for item in operations:
        expected = set()
        if item["codec_id"] == "sog":
            expected.update(
                {
                    "libwebp 1.5.0",
                    "miniz 3.0.2",
                    "nlohmann_json 3.11.3",
                }
            )
        if item["codec_id"] == "exr":
            expected.add("miniz 3.0.2")
        if item["codec_id"] in json_codecs:
            expected.add("nlohmann_json 3.11.3")
        if item["direction"] == "decode" and (
            item["codec_id"] in fast_float_default_decoders
            or (
                item["codec_id"] == "ply"
                and item["profile"] == "point_ascii"
            )
            or (
                item["codec_id"] == "pcd"
                and item["profile"] == "ascii"
            )
        ):
            expected.add("fast_float 6.1.6")
        assert set(item.get("backend_dependencies", ())) == expected, (
            item["codec_id"],
            item["profile"],
            item["direction"],
        )


def test_performance_backend_versions_match_pinned_sources():
    operations = _ledger()["operation"]
    pins = {
        "lodepng": (
            "ed6fe5825c6a4fbb7f58ab35a4231c7543cd452a",
            "src/cpp/third_party/lodepng/COMMIT.txt",
        ),
        "stb": (
            "31c1ad37456438565541f4919958214b6e762fb4",
            "src/cpp/third_party/stb/COMMIT.txt",
        ),
        "tinyexr": (
            "1b106618644dbf8a0935c2348ba51a2d863dd7c2",
            "src/cpp/third_party/tinyexr/COMMIT.txt",
        ),
        "sceneio-native+tinyobjloader": (
            "45636bdcef1a4fec140346b90c0b50bf0bc3e23b",
            "src/cpp/third_party/tinyobjloader/COMMIT.txt",
        ),
        "sceneio-native+cgltf": (
            "360db1a95480fe102ae9c69b27c5d101167ff5ba",
            "src/cpp/third_party/cgltf/COMMIT.txt",
        ),
        "sqlite": (
            "bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc",
            "src/cpp/third_party/sqlite/COMMIT.txt",
        ),
        "libwebp": ("1.5.0", "src/cpp/third_party/libwebp/COMMIT.txt"),
        "lazperf": (
            "b7bbe26109dc986f42d4fc80b8de3d2b6ca634ce",
            "src/cpp/third_party/lazperf/COMMIT.txt",
        ),
        "miniz": ("3.0.2", "src/cpp/third_party/miniz/COMMIT.txt"),
        "zstd": (
            "1.5.6",
            "src/cpp/third_party/zstd/COMMIT.txt",
        ),
    }
    for backend, (revision, source_path) in pins.items():
        rows = [item for item in operations if item["backend"] == backend]
        assert rows, backend
        source = (ROOT / source_path).read_text(encoding="utf-8")
        assert revision in source
        assert all(revision in item["backend_version"] for item in rows)

    zstd_rows = [item for item in operations if item["backend"] == "zstd"]
    assert all(item["backend_owner"] == "vendored" for item in zstd_rows)
    assert all(
        item["backend_source"] == "src/cpp/third_party/zstd"
        for item in zstd_rows
    )

    spz_rows = [item for item in operations if item["codec_id"] == "spz"]
    expected_profiles = {
        "legacy_v3_gzip": {
            "settings": {
                "version": 3,
                "fractional_bits": 12,
                "container_magic": "1f8b",
            },
            "fixture": "spz:v3_gzip",
            "backend": "miniz",
            "backend_source": "src/cpp/third_party/miniz",
            "backend_version": "miniz-3.0.2",
        },
        "ngsp_v4_zstd": {
            "settings": {
                "version": 4,
                "fractional_bits": 12,
                "zstd_level": 12,
                "container_magic": "4e475350",
            },
            "fixture": "spz:v4_ngsp",
            "backend": "zstd",
            "backend_source": "src/cpp/third_party/zstd",
            "backend_version": "zstd-1.5.6",
        },
    }
    assert len(spz_rows) == 4
    for row in spz_rows:
        expected = expected_profiles[row["profile"]]
        assert {
            key: row[key]
            for key in (
                "settings",
                "fixture",
                "backend",
                "backend_source",
                "backend_version",
            )
        } == expected
        assert row["backend_owner"] == "vendored"

    patch_sets = {
        "stb": "sceneio-stb-3-local-patches-v1",
        "tinyexr": "sceneio-tinyexr-threaded-integration-v1",
        "lazperf": "sceneio-lazperf-portability-v1",
    }
    for backend, patch_set in patch_sets.items():
        rows = [item for item in operations if item["backend"] == backend]
        assert rows
        assert all(item.get("backend_patch_set") == patch_set for item in rows)
    unpatched = [
        item
        for item in operations
        if item["backend"] not in patch_sets
    ]
    assert all("backend_patch_set" not in item for item in unpatched)

    stb_commit = (
        ROOT / "src/cpp/third_party/stb/COMMIT.txt"
    ).read_text(encoding="utf-8")
    assert stb_commit.count("- stb_") == 3
    tinyexr_commit = (
        ROOT / "src/cpp/third_party/tinyexr/COMMIT.txt"
    ).read_text(encoding="utf-8")
    assert "Local integration configuration:" in tinyexr_commit
    assert "Local correctness patch:" in tinyexr_commit
    lazperf_commit = (
        ROOT / "src/cpp/third_party/lazperf/COMMIT.txt"
    ).read_text(encoding="utf-8")
    assert "Local correctness patch:" in lazperf_commit

    cmake = (ROOT / "cmake/SceneIODependencies.cmake").read_text(
        encoding="utf-8"
    )
    for dependency in (
        "libwebp 1.5.0",
        "miniz 3.0.2",
        "nlohmann_json 3.11.3",
        "fast_float 6.1.6",
    ):
        _, version = dependency.split()
        assert version in cmake
