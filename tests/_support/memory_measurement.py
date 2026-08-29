"""Small allocation-measurement helpers shared by I/O behavior suites."""

from __future__ import annotations

import gc
import tracemalloc


def traced_peak(call):
    """Return a callable's value and peak traced Python allocation."""
    tracemalloc.start()
    try:
        value = call()
        _, peak = tracemalloc.get_traced_memory()
        return value, peak
    finally:
        tracemalloc.stop()


def stable_traced_peak(call, *, samples: int = 3):
    """Return the median peak from repeated equivalent operations."""
    if samples < 1 or samples % 2 == 0:
        raise ValueError("samples must be a positive odd integer")
    peaks = []
    value = None
    for _ in range(samples):
        value = None
        gc.collect()
        value, peak = traced_peak(call)
        peaks.append(peak)
    peaks.sort()
    return value, peaks[len(peaks) // 2]


__all__ = ["stable_traced_peak", "traced_peak"]
