"""Timing and warmed-process allocation measurements for the I/O benchmark."""

from __future__ import annotations

import gc
import statistics
import threading
import time
import tracemalloc
import warnings
from collections.abc import Callable

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
