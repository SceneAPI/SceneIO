"""Fresh-child timing and memory measurements for the large-file harness."""

from __future__ import annotations

import gc
import importlib.metadata
import json
import os
import platform
import statistics
import sys
import threading
import time
import tracemalloc
from collections.abc import Callable, Iterable

try:
    import psutil
except Exception:  # pragma: no cover - optional benchmark metric
    psutil = None

from .model import Measurement, ProviderInfo


def _rss() -> int | None:
    if psutil is None:
        return None
    return int(psutil.Process().memory_info().rss)


def _sample_peak(stop: threading.Event, peak: list[int]) -> None:
    """Sample RSS until ``stop`` is set; a list keeps this closure mutable."""

    while not stop.is_set():
        current = _rss()
        if current is not None:
            peak[0] = max(peak[0], current)
        stop.wait(0.0005)


def measure_callable(
    fn: Callable[[], object],
    *,
    runs: int = 3,
    cache_mode: str = "warm",
    after_call: Callable[[object], None] | None = None,
) -> Measurement:
    """Measure one operation after an untimed warm-up.

    The timed samples stay intentionally free of tracemalloc and RSS sampling;
    a separate final invocation records those metrics while retaining its
    result until sampling observes the operation's peak.
    """

    if runs < 1:
        raise ValueError("runs must be positive")
    warm = fn()
    if after_call is not None:
        after_call(warm)
    del warm
    gc.collect()

    raw: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        value = fn()
        raw.append(time.perf_counter() - started)
        if after_call is not None:
            after_call(value)
        del value
    gc.collect()

    baseline = _rss()
    peak = [baseline or 0]
    stop = threading.Event()
    sampler = threading.Thread(target=_sample_peak, args=(stop, peak), daemon=True)
    tracemalloc.start()
    sampler.start()
    measured = None
    traced_peak = 0
    try:
        measured = fn()
        # Give the sampler one opportunity while the decoded result is still live.
        stop.wait(0.001)
        _, traced_peak = tracemalloc.get_traced_memory()
    finally:
        try:
            if measured is not None and after_call is not None:
                after_call(measured)
        finally:
            del measured
            stop.set()
            sampler.join(timeout=5.0)
            tracemalloc.stop()
    if sampler.is_alive():
        raise RuntimeError("RSS sampler did not stop within 5 seconds")
    gc.collect()

    rss_delta = None if baseline is None else max(0, peak[0] - baseline)
    return Measurement(
        raw_seconds=tuple(raw),
        median_seconds=float(statistics.median(raw)),
        traced_peak_bytes=int(traced_peak),
        rss_delta_bytes=rss_delta,
        cache_mode=cache_mode,
    )


def measure_timing(
    fn: Callable[[], object],
    *,
    runs: int = 3,
    cache_mode: str = "warm",
    after_call: Callable[[object], None] | None = None,
) -> Measurement:
    """Run only warm-up and timed samples.

    The parent combines this result with :func:`measure_memory` from a fresh
    worker so allocator residency from timing cannot hide the memory delta.
    """

    if runs < 1:
        raise ValueError("runs must be positive")
    warm = fn()
    if after_call is not None:
        after_call(warm)
    del warm
    gc.collect()
    raw: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        value = fn()
        raw.append(time.perf_counter() - started)
        if after_call is not None:
            after_call(value)
        del value
    return Measurement(
        raw_seconds=tuple(raw),
        median_seconds=float(statistics.median(raw)),
        traced_peak_bytes=None,
        rss_delta_bytes=None,
        cache_mode=cache_mode,
    )


def measure_memory(
    fn: Callable[[], object],
    *,
    cache_mode: str = "warm",
    after_call: Callable[[object], None] | None = None,
) -> Measurement:
    """Measure one target call in a fresh process with no prior warm call."""

    gc.collect()
    baseline = _rss()
    peak = [baseline or 0]
    stop = threading.Event()
    sampler = threading.Thread(target=_sample_peak, args=(stop, peak), daemon=True)
    tracemalloc.start()
    sampler.start()
    measured = None
    elapsed = 0.0
    traced_peak = 0
    try:
        started = time.perf_counter()
        measured = fn()
        elapsed = time.perf_counter() - started
        stop.wait(0.001)
        _, traced_peak = tracemalloc.get_traced_memory()
    finally:
        try:
            if measured is not None and after_call is not None:
                after_call(measured)
        finally:
            del measured
            stop.set()
            sampler.join(timeout=5.0)
            tracemalloc.stop()
    if sampler.is_alive():
        raise RuntimeError("RSS sampler did not stop within 5 seconds")
    rss_delta = None if baseline is None else max(0, peak[0] - baseline)
    return Measurement(
        raw_seconds=(elapsed,),
        median_seconds=elapsed,
        traced_peak_bytes=int(traced_peak),
        rss_delta_bytes=rss_delta,
        cache_mode=cache_mode,
    )


def provider_infos(names: Iterable[str]) -> dict[str, ProviderInfo]:
    """Capture installed provider versions without importing optional modules."""

    distributions = {
        "sceneio": "sceneio",
        "numpy": "numpy",
        "laspy": "laspy",
        "lazrs": "lazrs",
        "niantic_spz": "spz",
        "gsply": "gsply",
        "trimesh": "trimesh",
        "pycolmap": "pycolmap",
    }
    modules = {
        "sceneio": "sceneio",
        "numpy": "numpy",
        "laspy": "laspy",
        "lazrs": "lazrs",
        "niantic_spz": "spz",
        "gsply": "gsply",
        "trimesh": "trimesh",
        "pycolmap": "pycolmap",
    }
    result: dict[str, ProviderInfo] = {}
    for name in names:
        distribution = distributions.get(name, name)
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = None
        revision = None
        if name == "niantic_spz":
            try:
                direct_url = importlib.metadata.distribution(distribution).read_text(
                    "direct_url.json"
                )
                if direct_url:
                    revision = json.loads(direct_url).get("vcs_info", {}).get("commit_id")
            except (importlib.metadata.PackageNotFoundError, json.JSONDecodeError):
                revision = None
            revision = revision or "5bf2945de1a003cee07133b1e495fe9c6ffdc7e7"
        result[name] = ProviderInfo(
            name,
            version,
            modules.get(name),
            revision=revision,
            build=("distribution version; revision recorded separately" if revision else None),
        )
    return result


def environment_snapshot() -> dict[str, object]:
    """Return reproducibility metadata for the parent result document."""

    memory = None
    available_memory = None
    if psutil is not None:
        try:
            virtual = psutil.virtual_memory()
            memory = int(virtual.total)
            available_memory = int(virtual.available)
        except Exception:  # pragma: no cover - platform-specific psutil issue
            memory = None
    thread_variables = {
        name: os.environ.get(name, "provider defaults")
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "WEBP_THREAD_LEVEL",
        )
    }
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "python_implementation": platform.python_implementation(),
        "compiler": platform.python_compiler(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": memory,
        "available_ram_bytes": available_memory,
        "psutil_available": psutil is not None,
        "thread_policy": "environment values when set; otherwise provider defaults",
        "thread_variables": thread_variables,
    }


__all__ = [
    "environment_snapshot",
    "measure_callable",
    "measure_memory",
    "measure_timing",
    "provider_infos",
]
