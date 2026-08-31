from __future__ import annotations

import json
import os
import sys
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from _support import memory_measurement

from bench.io_bench import memory_child
from bench.io_bench.memory_child import _execute_operation, _high_water_rss
from bench.io_bench.memory_protocol import (
    DEFAULT_SAMPLES,
    DEFAULT_SAMPLING_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    SCHEMA_VERSION,
    MemoryCase,
    MemoryMeasurementUnavailable,
    MemoryOperation,
    MemoryProtocolError,
    MemoryQualificationFailed,
    MemorySample,
    _assert_response_matches_request,
    _child_request,
    assess_payload_growth,
    measure_memory_cases,
    operation_signature,
    require_bounded_payload_growth,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests" / "contracts" / "memory_protocol_v1.json").read_text(
        encoding="utf-8"
    )
)
RSS_FIELDS = (
    "baseline_rss_bytes",
    "baseline_high_water_rss_bytes",
    "peak_rss_bytes",
    "peak_high_water_rss_bytes",
    "sampled_delta_rss_bytes",
    "high_water_delta_rss_bytes",
    "delta_rss_bytes",
    "high_water_headroom_bytes",
    "high_water_calibration_bytes",
)
RSS_RUNTIME = pytest.mark.skipif(
    bool(
        os.environ.get("ASAN_OPTIONS")
        or "libasan" in os.environ.get("LD_PRELOAD", "")
    ),
    reason="instrumented runtime is not comparable for RSS qualification",
)


def _sparse_file(path: Path, size: int) -> Path:
    with path.open("wb") as stream:
        stream.truncate(size)
    return path


def _bounded_case(label: str, path: Path, size: int) -> MemoryCase:
    return MemoryCase(
        label,
        size,
        MemoryOperation(
            "bounded_file_read",
            {
                "path": str(path),
                "read_bytes": 64 * 1024,
            },
        ),
    )


def _allocation_case(label: str, size: int) -> MemoryCase:
    return MemoryCase(
        label,
        size,
        MemoryOperation("allocate_payload"),
    )


@RSS_RUNTIME
def test_memory_protocol_contract_and_repeated_sceneio_measurement(
    tmp_path,
    monkeypatch,
):
    repeated_peaks = iter((15_000_000, 32_000, 48_000))
    repeated_calls = []

    def deterministic_peak(call):
        repeated_calls.append(None)
        return call(), next(repeated_peaks)

    monkeypatch.setattr(
        memory_measurement,
        "traced_peak",
        deterministic_peak,
    )
    repeated_value, repeated_peak = memory_measurement.stable_traced_peak(
        lambda: "measured"
    )
    assert repeated_value == "measured"
    assert repeated_peak == 48_000
    assert len(repeated_calls) == 3
    with pytest.raises(ValueError, match="positive odd"):
        memory_measurement.stable_traced_peak(lambda: None, samples=2)

    array = np.arange(256, dtype=np.float32).reshape(16, 16)
    path = tmp_path / "probe.npy"
    np.save(path, array)
    cases = [
        MemoryCase(
            "read",
            path.stat().st_size,
            MemoryOperation(
                "sceneio_read",
                {"path": path.name, "format": "npy"},
            ),
        ),
        MemoryCase(
            "inspect",
            path.stat().st_size,
            MemoryOperation(
                "sceneio_inspect",
                {"path": path.name, "format": "npy"},
            ),
        ),
    ]

    monkeypatch.chdir(tmp_path)
    samples = measure_memory_cases(cases, samples=2)

    assert [(sample.case_label, sample.sample_index) for sample in samples] == [
        ("read", 0),
        ("read", 1),
        ("inspect", 0),
        ("inspect", 1),
    ]
    assert all(sample.status == "available" for sample in samples)
    assert all(sample.warmup_operation == "sceneio_registry" for sample in samples)
    assert all(sample.warmup_operation_count == 1 for sample in samples)
    assert all(sample.measured_operation_count == 1 for sample in samples)
    assert all(sample.sampler["available"] for sample in samples)
    assert all(sample.sampler["backend"] for sample in samples)
    assert all(sample.delta_rss_bytes is not None for sample in samples)
    assert all(sample.high_water_headroom_bytes == 0 for sample in samples)
    assert samples[0].measured_operation_signature == (
        'sceneio_read:{"format":"npy"}'
    )
    assert samples[0].warmup_operation_signature == "sceneio_registry:{}"
    assert sorted(samples[0].as_dict()) == CONTRACT["response_keys"]
    assert sorted(samples[0].platform) == CONTRACT["platform_keys"]
    assert sorted(samples[0].sampler) == CONTRACT["sampler_keys"]
    assert sorted({"available", "unavailable", "error"}) == CONTRACT["statuses"]
    assert sorted(field.name for field in fields(MemorySample)) == CONTRACT[
        "response_keys"
    ]
    assert CONTRACT["schema_version"] == SCHEMA_VERSION
    assert CONTRACT["available_invariants"][
        "high_water_envelopes_observed_current_rss"
    ] is True
    assert CONTRACT["defaults"]["samples"] == DEFAULT_SAMPLES
    assert (
        CONTRACT["defaults"]["sampling_interval_seconds"]
        == DEFAULT_SAMPLING_INTERVAL_SECONDS
    )
    assert CONTRACT["defaults"]["timeout_seconds"] == DEFAULT_TIMEOUT_SECONDS

    malformed = samples[0].as_dict()
    malformed["measured_operation_count"] = 2
    with pytest.raises(
        MemoryProtocolError,
        match="exactly one measured operation",
    ):
        MemorySample.from_response(malformed)

    missing_backend = samples[0].as_dict()
    missing_backend["sampler"]["backend"] = None
    with pytest.raises(
        MemoryProtocolError,
        match="non-empty sampler backend",
    ):
        MemorySample.from_response(missing_backend)

    unknown_backend = samples[0].as_dict()
    unknown_backend["sampler"]["backend"] = "psutil_thread+fabricated"
    with pytest.raises(
        MemoryProtocolError,
        match="unknown sampler backend",
    ):
        MemorySample.from_response(unknown_backend)

    false_headroom = samples[0].as_dict()
    false_headroom["baseline_high_water_rss_bytes"] += 4096
    false_headroom["peak_high_water_rss_bytes"] += 4096
    with pytest.raises(
        MemoryProtocolError,
        match="headroom does not match",
    ):
        MemorySample.from_response(false_headroom)

    reversed_high_water = samples[0].as_dict()
    reversed_high_water["baseline_high_water_rss_bytes"] = (
        reversed_high_water["baseline_rss_bytes"] - 1
    )
    with pytest.raises(
        MemoryProtocolError,
        match="high-water RSS must not be below current RSS",
    ):
        MemorySample.from_response(reversed_high_water)

    request = _child_request(
        cases[0],
        MemoryOperation("sceneio_registry"),
        0,
        DEFAULT_SAMPLING_INTERVAL_SECONDS,
    )
    _assert_response_matches_request(samples[0], request)
    mismatches = {
        "warmup_operation": "other_warmup",
        "warmup_operation_signature": "other_warmup:{}",
        "measured_operation": "other_operation",
        "measured_operation_signature": "other_operation:{}",
    }
    for field_name, value in mismatches.items():
        with pytest.raises(
            MemoryProtocolError,
            match=field_name,
        ):
            _assert_response_matches_request(
                replace(samples[0], **{field_name: value}),
                request,
            )
    with pytest.raises(
        MemoryProtocolError,
        match="sampling_interval_seconds",
    ):
        _assert_response_matches_request(
            replace(
                samples[0],
                sampler={
                    **samples[0].sampler,
                    "interval_seconds": 42.0,
                },
            ),
            request,
        )


@RSS_RUNTIME
def test_missing_sampler_is_explicit_and_strict_mode_rejects_it(tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "psutil.py").write_text(
        "raise ImportError('deliberately unavailable')\n",
        encoding="utf-8",
    )
    inherited = os.environ.get("PYTHONPATH")
    pythonpath = (
        str(shadow)
        if not inherited
        else os.pathsep.join((str(shadow), inherited))
    )
    case = _bounded_case(
        "unavailable",
        _sparse_file(tmp_path / "payload.bin", 1024),
        1024,
    )

    [sample] = measure_memory_cases(
        [case],
        samples=1,
        child_environment={"PYTHONPATH": pythonpath},
    )

    assert sample.status == "unavailable"
    assert sample.sampler == {
        "available": False,
        "backend": None,
        "interval_seconds": DEFAULT_SAMPLING_INTERVAL_SECONDS,
    }
    assert sample.measured_operation_count == 0
    assert all(getattr(sample, name) is None for name in RSS_FIELDS)
    response = sample.as_dict()
    response["delta_rss_bytes"] = 0
    with pytest.raises(
        MemoryProtocolError,
        match="RSS values as null",
    ):
        MemorySample.from_response(response)

    with pytest.raises(
        MemoryMeasurementUnavailable,
        match="deliberately unavailable",
    ):
        measure_memory_cases(
            [case],
            samples=3,
            strict=True,
            child_environment={"PYTHONPATH": pythonpath},
        )
    with pytest.raises(
        ValueError,
        match="at least 3 samples",
    ):
        measure_memory_cases([case], samples=2, strict=True)

    [instrumented] = measure_memory_cases(
        [case],
        samples=1,
        child_environment={"ASAN_OPTIONS": "detect_leaks=0"},
    )
    assert instrumented.status == "unavailable"
    assert "instrumented runtime" in instrumented.error_message


@RSS_RUNTIME
def test_payload_controls_distinguish_bounded_and_full_allocation(tmp_path):
    small_size = 8 * 1024 * 1024
    large_size = 48 * 1024 * 1024
    small_path = _sparse_file(tmp_path / "small.bin", small_size)
    large_path = _sparse_file(tmp_path / "large.bin", large_size)

    bounded_samples = measure_memory_cases(
        [
            _bounded_case("bounded-small", small_path, small_size),
            _bounded_case("bounded-large", large_path, large_size),
        ],
        samples=3,
        strict=True,
    )
    bounded = require_bounded_payload_growth(bounded_samples)
    assert bounded.passed
    assert bounded.status == "passed"
    assert bounded.payload_sizes_bytes == (small_size, large_size)
    assert bounded.samples_per_payload == 3

    allocation_samples = measure_memory_cases(
        [
            _allocation_case("allocation-small", small_size),
            _allocation_case("allocation-large", large_size),
        ],
        samples=3,
        strict=True,
    )
    allocation = assess_payload_growth(allocation_samples)
    assert not allocation.passed
    assert allocation.status == "failed"
    assert allocation.measured_growth_bytes is not None
    assert allocation.allowed_growth_bytes is not None
    assert allocation.measured_growth_bytes > allocation.allowed_growth_bytes
    with pytest.raises(
        MemoryQualificationFailed,
        match="median RSS growth",
    ):
        require_bounded_payload_growth(allocation_samples)

    extra_signature = operation_signature(
        MemoryOperation(
            "allocate_payload",
            {"extra_bytes": large_size},
        ).as_request()
    )
    mixed_operations = [
        (
            replace(sample, measured_operation_signature=extra_signature)
            if sample.payload_bytes == small_size
            else sample
        )
        for sample in allocation_samples
    ]
    with pytest.raises(
        ValueError,
        match="one measured operation signature",
    ):
        assess_payload_growth(mixed_operations)

    with pytest.raises(
        MemoryQualificationFailed,
        match="at least 3 samples",
    ):
        require_bounded_payload_growth(
            [bounded_samples[0], bounded_samples[3]]
        )

    middle_size = 28 * 1024 * 1024

    def with_delta(sample, *, size, label, delta):
        return replace(
            sample,
            case_label=label,
            payload_bytes=size,
            peak_rss_bytes=sample.baseline_rss_bytes + delta,
            peak_high_water_rss_bytes=(
                sample.baseline_high_water_rss_bytes + delta
            ),
            sampled_delta_rss_bytes=delta,
            high_water_delta_rss_bytes=delta,
            delta_rss_bytes=delta,
        )

    middle_spike = [
        with_delta(
            sample,
            size=small_size,
            label="synthetic-small",
            delta=0,
        )
        for sample in bounded_samples[:3]
    ]
    middle_spike.extend(
        with_delta(
            sample,
            size=middle_size,
            label="synthetic-middle",
            delta=40 * 1024 * 1024,
        )
        for sample in bounded_samples[:3]
    )
    middle_spike.extend(
        with_delta(
            sample,
            size=large_size,
            label="synthetic-large",
            delta=0,
        )
        for sample in bounded_samples[3:]
    )
    intermediate = assess_payload_growth(middle_spike)
    assert not intermediate.passed
    assert intermediate.status == "failed"
    assert intermediate.comparisons[middle_size]["passed"] is False

    obscured = [
        replace(sample, high_water_headroom_bytes=4096)
        for sample in bounded_samples
    ]
    assert assess_payload_growth(obscured).status == "unavailable"
    current_only = [
        replace(
            sample,
            sampler={
                **sample.sampler,
                "backend": "psutil_thread+psutil_current_only",
            },
        )
        for sample in bounded_samples
    ]
    assert assess_payload_growth(current_only).status == "unavailable"

    mixed_warmups = [
        (
            replace(
                sample,
                warmup_operation_signature="sceneio_registry:{\"variant\":1}",
            )
            if sample.payload_bytes == small_size
            else sample
        )
        for sample in bounded_samples
    ]
    with pytest.raises(
        ValueError,
        match="one warm-up operation signature",
    ):
        assess_payload_growth(mixed_warmups)


def test_bounded_read_control_returns_the_requested_bytes(
    tmp_path,
    monkeypatch,
):
    expected = bytes(range(256)) * 256
    path = tmp_path / "bounded.bin"
    path.write_bytes(expected)
    operation = MemoryOperation(
        "bounded_file_read",
        {"path": str(path), "read_bytes": len(expected)},
    ).as_request()

    result = _execute_operation(
        operation,
        sceneio=object(),
        payload_bytes=len(expected),
        allocation_headroom_bytes=0,
    )

    assert result == expected
    operation["arguments"]["read_bytes"] += 1
    with pytest.raises(ValueError, match="shorter than read_bytes"):
        _execute_operation(
            operation,
            sceneio=object(),
            payload_bytes=len(expected),
            allocation_headroom_bytes=0,
        )

    class LowNativeHighWater:
        rss = 96 * 1024

    class Process:
        def memory_info(self):
            return LowNativeHighWater()

    resource = SimpleNamespace(
        RUSAGE_SELF=0,
        getrusage=lambda unused: SimpleNamespace(ru_maxrss=64),
    )
    monkeypatch.setitem(sys.modules, "resource", resource)
    monkeypatch.setattr(sys, "platform", "linux")
    high_water, backend = _high_water_rss(
        Process(),
        observed_current_rss=128 * 1024,
    )
    assert high_water == 128 * 1024
    assert backend == "resource_ru_maxrss"

    class FinalSampleThread:
        def __init__(self, *, target, **unused):
            captured = dict(
                zip(
                    target.__code__.co_freevars,
                    (
                        cell.cell_contents
                        for cell in target.__closure__
                    ),
                    strict=True,
                )
            )
            self.peak = captured["peak"]
            self.ready = captured["ready"]

        def start(self):
            self.ready.set()

        def join(self, timeout):
            self.peak[0] = 256 * 1024

        def is_alive(self):
            return False

    class Psutil:
        @staticmethod
        def Process():
            return Process()

    class Sceneio:
        @staticmethod
        def codecs():
            return ()

    monkeypatch.setattr(
        memory_child.threading,
        "Thread",
        FinalSampleThread,
    )
    case = MemoryCase(
        "final-sampler-peak",
        0,
        MemoryOperation("sceneio_registry"),
    )
    response = memory_child._run_available(
        _child_request(
            case,
            MemoryOperation("sceneio_registry"),
            0,
            DEFAULT_SAMPLING_INTERVAL_SECONDS,
        ),
        sceneio=Sceneio(),
        psutil=Psutil(),
    )
    assert response["peak_rss_bytes"] == 256 * 1024
    assert response["peak_high_water_rss_bytes"] >= 256 * 1024
    MemorySample.from_response(response)


def test_profile_specific_memory_operations_dispatch_exact_arguments():
    calls = []

    class Sceneio:
        @staticmethod
        def read_scene(path, **keywords):
            calls.append(("read_scene", path, keywords))
            return "scene"

        @staticmethod
        def read_tiff_collection(path, **keywords):
            calls.append(("read_tiff_collection", path, keywords))
            return "collection"

    def execute(operation):
        return _execute_operation(
            operation.as_request(),
            sceneio=Sceneio(),
            payload_bytes=0,
            allocation_headroom_bytes=0,
        )

    assert execute(
        MemoryOperation(
            "sceneio_read_scene",
            {"path": "stage.usda", "time": 1.25, "load_payloads": False},
        )
    ) == "scene"
    assert execute(
        MemoryOperation(
            "sceneio_read_tiff_collection",
            {
                "path": "collection.tif",
                "series_index": 1,
                "level_index": 2,
                "page_range": [3, 4],
                "window": [5, 6, 7, 8],
            },
        )
    ) == "collection"
    assert calls == [
        (
            "read_scene",
            "stage.usda",
            {"time": 1.25, "load_payloads": False},
        ),
        (
            "read_tiff_collection",
            "collection.tif",
            {
                "series_index": 1,
                "level_index": 2,
                "page_range": (3, 4),
                "window": (5, 6, 7, 8),
            },
        ),
    ]

    with pytest.raises(ValueError, match="load_payloads must be boolean"):
        execute(
            MemoryOperation(
                "sceneio_read_scene",
                {"path": "stage.usda", "load_payloads": 1},
            )
        )
    with pytest.raises(ValueError, match="page_range must contain 2 integers"):
        execute(
            MemoryOperation(
                "sceneio_read_tiff_collection",
                {"path": "collection.tif", "page_range": [0, True]},
            )
        )


@pytest.mark.parametrize(
    ("constructor", "message"),
    [
        (lambda: MemoryOperation(""), "non-empty string"),
        (lambda: MemoryOperation(1), "non-empty string"),
        (
            lambda: MemoryOperation("operation", []),
            "must be a mapping",
        ),
        (
            lambda: MemoryOperation("operation", {"value": object()}),
            "JSON-compatible",
        ),
        (
            lambda: MemoryCase("", 1, MemoryOperation("sceneio_registry")),
            "non-empty string",
        ),
        (
            lambda: MemoryCase(
                "bad",
                -1,
                MemoryOperation("sceneio_registry"),
            ),
            "payload_bytes",
        ),
        (
            lambda: MemoryCase(
                "bad",
                1.5,
                MemoryOperation("sceneio_registry"),
            ),
            "payload_bytes",
        ),
    ],
)
def test_memory_protocol_inputs_are_checked(constructor, message):
    with pytest.raises(ValueError, match=message):
        constructor()
