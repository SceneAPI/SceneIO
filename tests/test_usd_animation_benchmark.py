"""Executable contract for the USD selected-time benchmark."""

from __future__ import annotations

from bench.io_bench import usd_animation
from bench.io_bench.usd_animation import run_benchmark


def test_usd_animation_benchmark_small_fixture_is_exact(
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
        usd_animation,
        "measure_fresh_process_rss",
        fake_fresh_process_rss,
    )
    result = run_benchmark(
        tmp_path,
        runs=1,
        node_count=4,
        samples_per_node=5,
        selected_time=1.25,
        fresh_rss_samples=3,
        fresh_rss_timeout_seconds=75,
    )

    assert result["schema_version"] == "usd-selected-time-benchmark-v1"
    assert result["close_state"] == "B_selected_time_read_only"
    assert result["fixture"]["node_count"] == 4
    assert result["fixture"]["authored_sample_count"] == 32
    assert set(result["metrics"]) == {
        "selected_time_read",
        "inspect",
        "static_control_read",
    }
    for metrics in result["metrics"].values():
        assert metrics["ms"] >= 0
        assert metrics["traced_peak_mb"] >= 0
        assert metrics["rss_peak_mb"] >= 0
    assert result["not_applicable"] == [
        "full_animation_preservation_read",
        "authored_animation_write",
    ]
    assert result["fresh_process_rss"] == {
        "protocol": "test-fresh-child"
    }
    assert captured["samples"] == 3
    assert captured["timeout_seconds"] == 75
    assert [case.label for case in captured["cases"]] == [
        "selected_time_read",
        "inspect",
        "static_control_read",
    ]
    assert [case.operation.kind for case in captured["cases"]] == [
        "sceneio_read_scene",
        "sceneio_inspect",
        "sceneio_read_scene",
    ]
