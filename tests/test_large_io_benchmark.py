"""Contract tests for the large-file benchmark harness.

Fixtures are generated in ``tmp_path``; no network acquisition or large file
is required for the test tier.
"""

from __future__ import annotations

import numpy as np
import pytest

from bench.io_bench.large import cases_arrays_points
from bench.io_bench.large.measure import measure_memory, measure_timing
from bench.io_bench.large.model import CaseArtifact
from bench.io_bench.large.runner import report_markdown, run_benchmark
from bench.io_bench.large.worker import run_request


def test_array_point_registry_has_split_scan_and_common_contract(tmp_path):
    definitions = cases_arrays_points.case_definitions()
    assert set(definitions) == {"npy_depth_stack", "laz_autzen"}
    assert definitions["npy_depth_stack"].operations[:2] == ("map_open", "full_scan")
    assert definitions["npy_depth_stack"].providers == ("sceneio", "numpy")
    assert definitions["laz_autzen"].source_id == "pdal_autzen_laz"

    laspy = pytest.importorskip("laspy")
    artifact = cases_arrays_points.prepare_case(
        "laz_autzen", "smoke", tmp_path / "cache", {}
    )
    values = laspy.read(artifact.path)
    values.points = values.points[:17].copy()
    values.write(artifact.path, do_compress=True)
    diagnostics = []
    for provider in ("sceneio", "laspy"):
        result = run_request(
            {
                "case_id": artifact.case_id,
                "tier": artifact.tier,
                "provider": provider,
                "operation": "inspect",
                "artifact": artifact.to_dict(),
                "path": str(artifact.path),
                "runs": 1,
                "mode": "timing",
                "output_dir": str(tmp_path / "outputs"),
            }
        )
        assert result["status"] == "ok"
        diagnostics.append(result["diagnostic"])
    assert diagnostics == [
        {
            "count": 17,
            "shape": [17, 3],
            "dtype": "float32",
            "point_format": 2,
            "has_color": True,
            "has_intensity": True,
        }
    ] * 2


def test_measurement_protocol_has_independent_timing_and_memory_passes():
    value = np.arange(128, dtype=np.float64)
    timing = measure_timing(lambda: value.sum(), runs=2)
    memory = measure_memory(lambda: value.copy())
    assert len(timing.raw_seconds) == 2
    assert timing.traced_peak_bytes is None
    assert timing.rss_delta_bytes is None
    assert len(memory.raw_seconds) == 1
    assert memory.traced_peak_bytes is not None


def test_worker_npy_full_scan_matches_fixed_oracle(tmp_path):
    artifact = cases_arrays_points.prepare_case(
        "npy_depth_stack", "smoke", tmp_path, {}
    )
    result = run_request(
        {
            "case_id": artifact.case_id,
            "tier": artifact.tier,
            "provider": "numpy",
            "operation": "full_scan",
            "artifact": artifact.to_dict(),
            "path": str(artifact.path),
            "runs": 1,
            "mode": "timing",
            "output_dir": str(tmp_path / "outputs"),
        }
    )
    assert result["status"] == "ok"
    assert result["diagnostic"]["reduction"] == cases_arrays_points._npy_scan(artifact.path)


def test_runner_smoke_npy_is_complete_and_cleans_outputs(tmp_path):
    document = run_benchmark(
        tier="smoke", runs=1, cache=tmp_path, only=["npy_depth_stack"]
    )
    assert document["schema_version"] == "large-io-v1"
    assert document["complete"] is True
    assert document["correctness_passed"] is True
    assert document["cross_reads"]
    assert all(row["status"] == "pass" for row in document["cross_reads"])
    directional = {
        (row["writer_provider"], row["reader_provider"])
        for row in document["cross_reads"]
        if row["kind"] == "provider_output_cross_read"
    }
    assert directional == {
        ("sceneio", "sceneio"),
        ("sceneio", "numpy"),
        ("numpy", "sceneio"),
        ("numpy", "numpy"),
    }
    assert document["cleanup"] == [
        {
            "path": str(tmp_path / "outputs" / "npy_depth_stack" / "smoke"),
            "status": "pass",
        }
    ]
    assert not list((tmp_path / "outputs").rglob("*.npy"))


def test_standard_requires_three_timed_samples(tmp_path):
    with pytest.raises(ValueError, match="exactly 3"):
        run_benchmark(
            tier="standard",
            runs=2,
            cache=tmp_path,
            only=["npy_depth_stack"],
        )


def test_npy_cross_matrix_rejects_fortran_order(tmp_path):
    artifact = cases_arrays_points.prepare_case(
        "npy_depth_stack", "smoke", tmp_path, {}
    )
    wrong = tmp_path / "fortran.npy"
    expected = np.load(artifact.path, allow_pickle=False)
    np.save(wrong, np.asfortranarray(expected), allow_pickle=False)
    rows = cases_arrays_points.cross_read_matrix(
        artifact,
        {"sceneio": wrong, "numpy": wrong},
    )
    assert rows
    assert all(row["status"] == "fail" for row in rows)


def test_report_keeps_provenance_raw_samples_and_matching_ratios(tmp_path):
    document = run_benchmark(
        tier="smoke", runs=1, cache=tmp_path, only=["npy_depth_stack"]
    )
    report = report_markdown(document)
    assert "Fixture provenance" in report
    assert "Raw samples" in report
    assert "Encoded MiB/s" in report
    assert "Matching-operation ratios" in report
    assert "Reproduction" in report


def test_case_artifact_roundtrip_is_json_safe(tmp_path):
    artifact = CaseArtifact(
        case_id="example",
        tier="smoke",
        path=tmp_path / "fixture.bin",
        logical_bytes=12,
        encoded_bytes=16,
        metadata={"shape": [3, 4]},
    )
    restored = CaseArtifact.from_dict(artifact.to_dict())
    assert restored == artifact
