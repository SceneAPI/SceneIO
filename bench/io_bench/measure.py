"""Timing and warmed-process allocation measurements for the I/O benchmark."""

from __future__ import annotations

import gc
import statistics
import threading
import time
import tracemalloc
import warnings
from collections.abc import Callable, Sequence

from bench.io_bench.memory_protocol import (
    MemoryCase,
    measure_memory_cases,
)

try:
    import psutil
except Exception:
    psutil = None


def measure(fn: Callable[[], object], runs: int) -> tuple[float, int]:
    """Return median wall time and a separate peak traced-allocation pass.

    Keeping tracemalloc out of the timing loop matters for Python metadata
    scanners: tracing each small token allocation can otherwise dominate the
    operation and invert the measured O5 latency relationship.
    """

    fn()  # warm
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        result = fn()
        dt = time.perf_counter() - t0
        times.append(dt)
        del result
    gc.collect()
    tracemalloc.start()
    try:
        result = fn()
        _, peak = tracemalloc.get_traced_memory()
        del result
    finally:
        tracemalloc.stop()
    return statistics.median(times), peak


def try_measure(fn: Callable[[], object]):
    """Run an oracle closure; return ``None`` on any oracle failure."""

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return fn()
    except Exception:
        return None


def measure_in_process_rss(fn: Callable[[], object]) -> int:
    """Sample peak RSS growth for one call in the warmed parent process.

    This preserves the benchmark's original metric. It is useful for exploratory
    deltas but is not a fresh-process peak measurement. When psutil is absent,
    the legacy value of zero is returned.
    """

    if psutil is None:
        return 0
    gc.collect()
    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = baseline
    running = True

    def sample():
        nonlocal peak
        while running:
            peak = max(peak, process.memory_info().rss)
            time.sleep(0.0005)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        value = fn()
        peak = max(peak, process.memory_info().rss)
        del value
    finally:
        running = False
        sampler.join()
    return max(0, peak - baseline)


def measure_fresh_process_rss(
    cases: Sequence[MemoryCase],
    *,
    samples: int,
    timeout_seconds: float,
) -> dict[str, object]:
    """Measure qualification-grade RSS in one fresh child per sample."""

    measured = measure_memory_cases(
        cases,
        samples=samples,
        strict=True,
        timeout_seconds=timeout_seconds,
    )
    operations: dict[str, object] = {}
    for case in cases:
        case_samples = [
            sample for sample in measured if sample.case_label == case.label
        ]
        deltas = [sample.delta_rss_bytes for sample in case_samples]
        if not deltas or any(delta is None for delta in deltas):
            raise RuntimeError(
                f"fresh-process RSS is unavailable for {case.label!r}"
            )
        integer_deltas = [int(delta) for delta in deltas if delta is not None]
        operations[case.label] = {
            "median_delta_rss_bytes": int(statistics.median(integer_deltas)),
            "samples": [
                {
                    "baseline_rss_bytes": sample.baseline_rss_bytes,
                    "baseline_high_water_rss_bytes": (
                        sample.baseline_high_water_rss_bytes
                    ),
                    "peak_rss_bytes": sample.peak_rss_bytes,
                    "peak_high_water_rss_bytes": (
                        sample.peak_high_water_rss_bytes
                    ),
                    "sampled_delta_rss_bytes": (
                        sample.sampled_delta_rss_bytes
                    ),
                    "high_water_delta_rss_bytes": (
                        sample.high_water_delta_rss_bytes
                    ),
                    "delta_rss_bytes": sample.delta_rss_bytes,
                    "sampler_backend": sample.sampler["backend"],
                }
                for sample in case_samples
            ],
        }
    return {
        "protocol": "sceneio-fresh-child-memory-v1",
        "samples_per_operation": samples,
        "operations": operations,
    }
