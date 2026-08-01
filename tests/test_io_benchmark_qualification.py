"""Repository-complete comparison qualification for the I/O benchmark."""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from bench.io_bench import qualification, runner
from bench.io_bench import usd_cameras as usd_camera_benchmark
from bench.io_bench import usd_gaussians as usd_gaussian_benchmark
from bench.io_bench import usd_materials as usd_material_benchmark
from bench.io_bench import usd_payloads as usd_payload_benchmark
from bench.io_bench import usd_scene as usd_scene_benchmark
from bench.io_bench.families.dense import validate_dense_oracle_parity
from bench.io_bench.model import Spec
from sceneio.io import registry
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests" / "contracts" / "bench_io_v1.json").read_text(
        encoding="utf-8"
    )
)


def test_rich_usd_geometry_benchmark_smoke(tmp_path):
    results = usd_scene_benchmark.run_benchmark(
        tmp_path,
        runs=1,
        face_count=2,
        point_count=3,
        encodings=("usda",),
    )

    assert len(results) == 1
    result = results[0]
    assert result["encoding"] == "usda"
    assert result["faces"] == 2
    assert result["points"] == 3
    assert result["payload_mb"] > 0
    assert result["file_mb"] > 0
    assert result["cold_cache_requested"] is False
    assert result["cold_cache_applied"] is False
    assert isinstance(result["cold_cache_supported"], bool)
    for operation in ("write", "full_read", "inspect", "selected_read"):
        assert result[operation]["ms"] >= 0
        assert result[operation]["traced_peak_mb"] >= 0
        assert result[operation]["rss_peak_mb"] >= 0


def test_rich_usd_material_benchmark_smoke(tmp_path):
    results = usd_material_benchmark.run_benchmark(
        tmp_path,
        runs=1,
        face_count=4,
        material_count=2,
        texture_bytes=1024,
        encodings=("usda",),
    )

    assert len(results) == 1
    result = results[0]
    assert result["encoding"] == "usda"
    assert result["faces"] == 4
    assert result["materials"] == 2
    assert result["texture_mb"] > 0
    assert result["payload_mb"] > 0
    assert result["stage_file_mb"] > 0
    for operation in ("write", "full_read", "inspect"):
        assert result[operation]["ms"] >= 0
        assert result[operation]["traced_peak_mb"] >= 0
        assert result[operation]["rss_peak_mb"] >= 0


def test_rich_usd_gaussian_benchmark_smoke(tmp_path):
    results = usd_gaussian_benchmark.run_benchmark(
        tmp_path,
        runs=1,
        gaussian_counts=(4,),
        degree=1,
        precision="float32",
        encodings=("usda", "gaussian_ply"),
    )

    assert [result["encoding"] for result in results] == [
        "usda",
        "gaussian_ply",
    ]
    for result in results:
        assert result["gaussians"] == 4
        assert result["degree"] == 1
        assert result["payload_mb"] > 0
        assert result["file_mb"] > 0
        for operation in ("write", "full_read", "inspect"):
            assert result[operation]["ms"] >= 0
            assert result[operation]["traced_peak_mb"] >= 0
            assert result[operation]["rss_peak_mb"] >= 0


def test_rich_usd_camera_benchmark_smoke(tmp_path):
    results = usd_camera_benchmark.run_benchmark(
        tmp_path,
        runs=1,
        camera_counts=(4,),
        encodings=("usda",),
    )

    assert len(results) == 1
    result = results[0]
    assert result["encoding"] == "usda"
    assert result["cameras"] == 4
    assert result["payload_mb"] > 0
    assert result["file_mb"] > 0
    for operation in ("write", "full_read", "inspect", "selected_read"):
        assert result[operation]["ms"] >= 0
        assert result[operation]["traced_peak_mb"] >= 0
        assert result[operation]["rss_peak_mb"] >= 0


def test_rich_usd_remaining_payload_benchmark_smoke(tmp_path):
    results = usd_payload_benchmark.run_benchmark(
        tmp_path,
        runs=1,
        instance_counts=(4,),
        vdb_size_mib=1,
    )

    assert [result["case"] for result in results] == [
        "point_instancer",
        "openvdb_dependency",
    ]
    assert results[0]["instances"] == 4
    assert results[0]["prototypes"] == 1
    assert results[1]["vdb_file_mb"] > 1
    for result in results:
        for operation in set(result) & {"write", "full_read", "inspect"}:
            assert result[operation]["ms"] >= 0
            assert result[operation]["traced_peak_mb"] >= 0
            assert result[operation]["rss_peak_mb"] >= 0


def _assembled_specs():
    pose_bundle = runner._poses_and_reconstruction(0.001)
    with tempfile.TemporaryDirectory() as tmp:
        specs = runner._specs(0.001, pose_bundle)
        directory_specs = runner._directory_specs(
            pose_bundle[0],
            0.001,
            tmp,
        )
        for spec in directory_specs:
            if spec.id.startswith("colmap_sparse"):
                record, _ = spec.make()
                assert record.has_rig_frame_model
                assert record.num_rigs == record.num_frames == 1
    return specs, directory_specs


def _assembled_ids(specs, directory_specs):
    path_specs = runner.build_container_specs(0.001)
    return (
        *(spec.id for spec in specs),
        "gltf",
        "colmap_db",
        *(spec.id for spec in directory_specs),
        *(spec.id for spec in path_specs),
    )


def _ledger_payload() -> str:
    return json.dumps(
        {
            format_id: dataclasses.asdict(item)
            for format_id, item in (
                qualification.COMPARISON_QUALIFICATIONS.items()
            )
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _valid_spz_profile_metrics():
    return {
        "legacy_v3_gzip": {
            "version": 3,
            "fractional_bits": 12,
            "zstd_level": None,
            "container_magic": "1f8b",
            "backend": "miniz",
            "file_mb": 1.0,
            "write_mbps": 1.0,
            "read_mbps": 1.0,
        },
        "ngsp_v4_zstd": {
            "version": 4,
            "fractional_bits": 12,
            "zstd_level": 12,
            "container_magic": "4e475350",
            "backend": "zstd",
            "file_mb": 1.0,
            "write_mbps": 1.0,
            "read_mbps": 1.0,
        },
    }


def test_qualification_ledger_is_complete_immutable_and_checked():
    ledger = qualification.COMPARISON_QUALIFICATIONS
    assert tuple(ledger) == CANONICAL_BUILTIN_IDS
    assert len(ledger) == 67
    assert sum(item.mode == "timed" for item in ledger.values()) == 50
    assert (
        sum(
            item.mode == "reviewed_exemption"
            for item in ledger.values()
        )
        == 17
    )
    with pytest.raises(TypeError):
        ledger["npy"] = ledger["npy"]

    for item in ledger.values():
        assert (ROOT / item.verification_path).is_file()

    checked = CONTRACT["r3_2_qualification"]
    assert checked["source"] == "bench/io_bench/qualification.py"
    assert checked["builtin_count"] == len(ledger)
    assert checked["timed_count"] == 50
    assert checked["reviewed_exemption_count"] == 17
    assert hashlib.sha256(_ledger_payload().encode()).hexdigest() == (
        checked["ledger_sha256"]
    )


def test_reviewed_exemptions_match_the_family_contract_exactly():
    contracted = {}
    for family in CONTRACT["r3_2_family_extraction"].values():
        contracted.update(family["no_oracle_exemptions"])
    observed = {
        format_id: item
        for format_id, item in (
            qualification.COMPARISON_QUALIFICATIONS.items()
        )
        if item.mode == "reviewed_exemption"
    }
    assert set(observed) == set(contracted)
    for format_id, item in observed.items():
        assert contracted[format_id]["unverified_property"] == (
            item.unverified_property
        )
        assert item.verification_path in contracted[format_id][
            "verification"
        ]


def test_assembled_sweep_is_exactly_the_repository_builtins():
    specs, directory_specs = _assembled_specs()
    observed = _assembled_ids(specs, directory_specs)
    assert qualification.validate_benchmark_coverage(observed) == observed
    assert set(observed) == set(CANONICAL_BUILTIN_IDS)
    assert len(observed) == len(set(observed)) == 67

    spec = next(item for item in specs if item.id == "spz")
    record, _ = spec.make()

    legacy = bytes(spec.w(record))
    assert legacy[:2] == b"\x1f\x8b"
    assert gzip.decompress(legacy)[:8] == b"NGSP\x03\x00\x00\x00"

    ngsp = bytes(
        runner.splat_family.write_spz_profile(
            record,
            "ngsp_v4_zstd",
        )
    )
    assert ngsp[:8] == b"NGSP\x04\x00\x00\x00"
    legacy_decoded = spec.r(legacy)
    ngsp_decoded = spec.r(ngsp)
    for field in (
        "means",
        "scales",
        "quaternions",
        "opacities",
        "sh_dc",
        "sh_rest",
    ):
        np.testing.assert_array_equal(
            np.asarray(getattr(legacy_decoded, field)),
            np.asarray(getattr(ngsp_decoded, field)),
        )


def test_dense_benchmark_oracles_are_cross_differential():
    specs, _ = _assembled_specs()
    dense_ids = {
        "colmap_fused_visibility",
        "colmap_mvs_consistency",
        "colmap_mvs_depth",
        "colmap_mvs_normal",
    }
    for spec in specs:
        if spec.id not in dense_ids:
            continue
        record, payload = spec.make()
        encoded = bytes(spec.w(record))
        validate_dense_oracle_parity(spec, record, payload, encoded)
        with pytest.raises(AssertionError):
            validate_dense_oracle_parity(
                spec,
                record,
                payload,
                encoded + b"\0",
            )
    runner_source = (
        ROOT / "bench/io_bench/runner.py"
    ).read_text(encoding="utf-8")
    assert "qualification.validate_dense_oracle_parity(" in runner_source


def test_o5_directional_allocation_controls_are_narrow_and_accept_gains():
    assert {
        "usd",
        "usdz",
    } == set(qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS)
    assert {
        "parquet",
    } == set(qualification.O5_PARTIAL_DIRECTIONAL_ALLOCATION_LIMITS)
    assert dict(qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS) == {
        "usd": (8.0, 0.8),
        "usdz": (8.0, 0.8),
    }
    assert dict(qualification.O5_PARTIAL_DIRECTIONAL_ALLOCATION_LIMITS) == {
        "parquet": (2.0, 0.25),
    }
    qualification.validate_o5_allocation_controls(
        "inspection",
        {
            "png": (3.2, 0.01),
            "usd": (8.5, 5.7),
            "usdz": (8.5, 5.7),
        },
        directional_limits=(
            qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS
        ),
    )
    qualification.validate_o5_allocation_controls(
        "partial read",
        {"png": (3.2, 0.01), "parquet": (18.4, 1.6)},
        directional_limits=(
            qualification.O5_PARTIAL_DIRECTIONAL_ALLOCATION_LIMITS
        ),
    )


@pytest.mark.parametrize(
    ("peaks", "directional_limits", "message"),
    [
        (
            {"png": (3.2, 1.0), "usd": (8.5, 5.7), "usdz": (8.5, 5.7)},
            qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS,
            "inspection exceeded 1 MB traced allocation: png",
        ),
        (
            {"png": (3.2, 0.01), "usd": (8.5, 7.0), "usdz": (8.5, 5.7)},
            qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS,
            "inspection failed directional traced-allocation guard: usd",
        ),
        (
            {
                "png": (3.2, 0.01),
                "usd": (1000.0, 999.0),
                "usdz": (8.5, 5.7),
            },
            qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS,
            "inspection failed directional traced-allocation guard: usd",
        ),
        (
            {
                "png": (3.2, 0.01),
                "usd": (100.0, 8.0),
                "usdz": (8.5, 5.7),
            },
            qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS,
            "inspection failed directional traced-allocation guard: usd",
        ),
        (
            {"png": (3.2, 0.01), "usd": (8.5, 5.7)},
            qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS,
            "missing O5 inspection directional allocation rows: usdz",
        ),
        (
            {
                "png": (3.2, float("nan")),
                "usd": (8.5, 5.7),
                "usdz": (8.5, 5.7),
            },
            qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS,
            "invalid O5 inspection traced allocation metrics: png",
        ),
    ],
)
def test_o5_inspection_allocation_controls_reject_regressions(
    peaks,
    directional_limits,
    message,
):
    with pytest.raises(RuntimeError, match=message):
        qualification.validate_o5_allocation_controls(
            "inspection",
            peaks,
            directional_limits=directional_limits,
        )


@pytest.mark.parametrize(
    ("ids", "fragment"),
    [
        (CANONICAL_BUILTIN_IDS[1:], "missing=pfm"),
        (
            (*CANONICAL_BUILTIN_IDS, "npy"),
            "duplicates=npy",
        ),
        (
            (*CANONICAL_BUILTIN_IDS, "runtime-format"),
            "unexpected=runtime-format",
        ),
    ],
)
def test_coverage_validation_rejects_incomplete_or_noncanonical_sweeps(
    ids,
    fragment,
):
    with pytest.raises(RuntimeError, match=fragment):
        qualification.validate_benchmark_coverage(ids)


def test_runtime_registration_does_not_enter_repository_qualification():
    specs, directory_specs = _assembled_specs()
    observed = _assembled_ids(specs, directory_specs)
    extension = dataclasses.replace(
        registry.REGISTRY["npy"],
        id="runtime-benchmark-extension",
        extensions=(".runtime-benchmark-extension",),
    )
    before = tuple(registry.REGISTRY.items())
    try:
        registry.register(extension)
        assert registry.REGISTRY[extension.id] is extension
        assert extension.id not in observed
        assert qualification.validate_benchmark_coverage(observed) == observed
    finally:
        registry.REGISTRY.pop(extension.id, None)
    assert tuple(registry.REGISTRY.items()) == before


def test_runner_checks_builtins_before_measurement(monkeypatch, tmp_path):
    specs, _ = _assembled_specs()
    monkeypatch.setattr(
        runner,
        "_specs",
        lambda scale, pose_bundle: [
            spec for spec in specs if spec.id != "npy"
        ],
    )
    args = SimpleNamespace(
        scale=0.001,
        strict_oracles=False,
        only=None,
    )
    with pytest.raises(RuntimeError, match="missing=npy"):
        runner._run_benchmark(args, tmp_path)


def test_strict_preflight_names_every_unavailable_provider():
    specs, _ = _assembled_specs()
    unavailable_numpy = [
        dataclasses.replace(spec, ow=None, orr=None)
        if spec.id == "npy"
        else spec
        for spec in specs
    ]
    with pytest.raises(RuntimeError) as caught:
        qualification.validate_strict_providers(
            unavailable_numpy,
            special_available={"gltf": False, "colmap_db": True},
            path_specs=runner.build_container_specs(0.001),
        )
    message = str(caught.value)
    assert "npy (NumPy)" in message
    assert "gltf (trimesh)" in message


def test_strict_spec_measurement_propagates_and_never_uses_optional_try():
    calls = []

    def encode(payload):
        calls.append(("encode", payload))
        return b"encoded"

    def decode(payload):
        calls.append(("decode", payload))
        return object()

    spec = Spec(
        "npy",
        lambda: None,
        lambda value: b"",
        lambda value: None,
        encode,
        decode,
        lambda record, payload: 1,
    )

    def measure(operation, runs):
        assert runs == 3
        operation()
        return 2.0, 0

    def forbidden_optional_try(operation):
        raise AssertionError("strict mode used the optional path")

    assert qualification.measure_spec_comparison(
        spec,
        "payload",
        8.0,
        3,
        strict=True,
        measure=measure,
        optional_try=forbidden_optional_try,
    ) == (4.0, 4.0)
    assert calls == [
        ("encode", "payload"),
        ("encode", "payload"),
        ("decode", b"encoded"),
    ]

    failing = dataclasses.replace(
        spec,
        ow=lambda payload: (_ for _ in ()).throw(
            ValueError("provider failed")
        ),
    )
    with pytest.raises(ValueError, match="provider failed"):
        qualification.measure_spec_comparison(
            failing,
            "payload",
            8.0,
            1,
            strict=True,
            measure=measure,
            optional_try=forbidden_optional_try,
        )


def test_strict_spec_measurement_rejects_missing_payload():
    specs, _ = _assembled_specs()
    spec = next(item for item in specs if item.id == "npy")
    with pytest.raises(
        RuntimeError,
        match="strict comparison payload unavailable for 'npy'",
    ):
        qualification.measure_spec_comparison(
            spec,
            None,
            1.0,
            1,
            strict=True,
            measure=lambda operation, runs: (1.0, None),
            optional_try=lambda operation: operation(),
        )
    assert qualification.measure_spec_comparison(
        spec,
        None,
        1.0,
        1,
        strict=False,
        measure=lambda operation, runs: (1.0, None),
        optional_try=lambda operation: operation(),
    ) == (None, None)


@pytest.mark.parametrize(
    ("codec_id", "metric"),
    [
        ("npy", "oracle_write_mbps"),
        ("npy", "oracle_read_mbps"),
        ("colmap_db", "oracle_inspect_ms"),
        ("colmap_db", "oracle_image_ms"),
        ("colmap_db", "oracle_pair_ms"),
    ],
)
def test_strict_result_validation_requires_every_declared_metric(
    codec_id,
    metric,
):
    results = []
    for format_id, item in (
        qualification.COMPARISON_QUALIFICATIONS.items()
    ):
        result = {"codec": format_id}
        if item.mode == "timed":
            result.update(
                oracle_write_mbps=1.0,
                oracle_read_mbps=1.0,
            )
            if "inspect" in item.operations:
                result["oracle_inspect_ms"] = 1.0
            if "partial" in item.operations:
                result["oracle_image_ms"] = 1.0
                result["oracle_pair_ms"] = 1.0
        if format_id == "spz":
            result["spz_profiles"] = _valid_spz_profile_metrics()
        results.append(result)

    qualification.validate_strict_results(results)
    result = next(item for item in results if item["codec"] == codec_id)
    expected = (
        "strict comparison evidence incomplete: "
        f"{codec_id}:{metric}"
    )
    original = result.pop(metric)
    with pytest.raises(RuntimeError, match=expected):
        qualification.validate_strict_results(results)
    for invalid in (None, 0.0, float("nan"), True):
        result[metric] = invalid
        with pytest.raises(RuntimeError, match=expected):
            qualification.validate_strict_results(results)
    result[metric] = original
    qualification.validate_strict_results(results)

    if codec_id == "npy" and metric == "oracle_write_mbps":
        spz = next(item for item in results if item["codec"] == "spz")
        profiles = spz["spz_profiles"]
        ngsp = profiles.pop("ngsp_v4_zstd")
        with pytest.raises(RuntimeError, match="spz:profile-set"):
            qualification.validate_strict_results(results)
        profiles["ngsp_v4_zstd"] = ngsp
        ngsp["container_magic"] = "1f8b"
        with pytest.raises(
            RuntimeError,
            match="spz:ngsp_v4_zstd:settings",
        ):
            qualification.validate_strict_results(results)


@pytest.mark.parametrize(
    "arguments",
    [
        ("--strict-oracles", "--skip-oracles"),
        ("--strict-oracles", "--only", "npy"),
        ("--strict-oracles", "--large-safetensors-mib", "1"),
    ],
)
def test_strict_cli_rejects_partial_or_disabled_comparisons(arguments):
    result = subprocess.run(
        [sys.executable, "bench/bench_io.py", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "cannot be combined" in result.stderr
