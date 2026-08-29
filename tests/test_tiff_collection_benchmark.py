"""Executable contract for the typed TIFF collection benchmark."""

from __future__ import annotations

from bench.io_bench import tiff_collections
from bench.io_bench.tiff_collections import run_benchmark


def test_tiff_collection_benchmark_small_fixture_is_exact(
    tmp_path,
    monkeypatch,
):
    captured = {}

    def fake_fresh_process_rss(cases, *, samples, timeout_seconds):
        captured["cases"] = cases
        captured["samples"] = samples
        captured["timeout_seconds"] = timeout_seconds
        return {"protocol": "test-fresh-child"}

    monkeypatch.setattr(
        tiff_collections,
        "measure_fresh_process_rss",
        fake_fresh_process_rss,
    )
    result = run_benchmark(
        tmp_path,
        runs=1,
        shape=(4, 128, 160),
        page_range=(1, 3),
        window=(17, 89, 23, 131),
        tile=(32, 32),
        fresh_rss_samples=3,
        fresh_rss_timeout_seconds=75,
    )

    assert result["schema_version"] == "tiff-collection-benchmark-v1"
    assert result["fixture"]["logical_bytes"] == 4 * 128 * 160 * 2
    assert result["selection"]["shape"] == [2, 72, 108]
    assert set(result["metrics"]) == {
        "typed_full_read",
        "typed_selected_read",
        "provider_full_then_slice",
        "typed_inspect",
    }
    for metrics in result["metrics"].values():
        assert metrics["ms"] >= 0
        assert metrics["traced_peak_mb"] >= 0
        assert metrics["rss_peak_mb"] >= 0
    assert result["fresh_process_rss"] == {
        "protocol": "test-fresh-child"
    }
    assert captured["samples"] == 3
    assert captured["timeout_seconds"] == 75
    assert [case.label for case in captured["cases"]] == [
        "typed_full_read",
        "typed_selected_read",
        "typed_inspect",
    ]
    assert [case.operation.kind for case in captured["cases"]] == [
        "sceneio_read_tiff_collection",
        "sceneio_read_tiff_collection",
        "sceneio_inspect_tiff_collection",
    ]
