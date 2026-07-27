"""Small allocation-measurement helpers shared by I/O behavior suites."""

from __future__ import annotations

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


__all__ = ["traced_peak"]
