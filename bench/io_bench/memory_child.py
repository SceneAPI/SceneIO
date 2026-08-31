"""Internal child process for :mod:`bench.io_bench.memory_protocol`."""

from __future__ import annotations

import gc
import json
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Any

from bench.io_bench.memory_protocol import (
    SCHEMA_VERSION,
    operation_signature,
)

_RSS_FIELD_DEFAULTS = {
    "baseline_rss_bytes": None,
    "baseline_high_water_rss_bytes": None,
    "peak_rss_bytes": None,
    "peak_high_water_rss_bytes": None,
    "sampled_delta_rss_bytes": None,
    "high_water_delta_rss_bytes": None,
    "delta_rss_bytes": None,
    "high_water_headroom_bytes": None,
    "high_water_calibration_bytes": None,
}


def _platform_metadata() -> dict[str, str]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }


def _sampler_metadata(
    *,
    available: bool,
    backend: str | None,
    interval_seconds: float,
) -> dict[str, Any]:
    return {
        "available": available,
        "backend": backend,
        "interval_seconds": interval_seconds,
    }


def _base_response(
    request: dict[str, Any],
    *,
    status: str,
    sampler: dict[str, Any],
    warmup_operation_count: int,
    measured_operation_count: int,
    error: Exception | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "case_label": request["case_label"],
        "sample_index": request["sample_index"],
        "payload_bytes": request["payload_bytes"],
        "platform": _platform_metadata(),
        "sampler": sampler,
        "warmup_operation": request["warmup_operation"]["kind"],
        "warmup_operation_signature": operation_signature(
            request["warmup_operation"],
            include_path=True,
        ),
        "measured_operation": request["measured_operation"]["kind"],
        "measured_operation_signature": operation_signature(
            request["measured_operation"]
        ),
        "warmup_operation_count": warmup_operation_count,
        "measured_operation_count": measured_operation_count,
        **_RSS_FIELD_DEFAULTS,
        "error_type": type(error).__name__ if error is not None else None,
        "error_message": str(error) if error is not None else None,
    }


def _validate_operation(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if set(value) != {"kind", "arguments"}:
        raise ValueError(
            f"{name} fields must be exactly ['arguments', 'kind']"
        )
    if not isinstance(value["kind"], str) or not value["kind"]:
        raise ValueError(f"{name}.kind must be a non-empty string")
    if not isinstance(value["arguments"], dict):
        raise ValueError(f"{name}.arguments must be an object")
    return value


def _validate_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("memory protocol request must be an object")
    expected = {
        "schema_version",
        "case_label",
        "sample_index",
        "payload_bytes",
        "sampling_interval_seconds",
        "warmup_operation",
        "measured_operation",
    }
    if set(value) != expected:
        raise ValueError(
            "memory protocol request fields do not match schema: "
            f"missing={sorted(expected.difference(value))}, "
            f"extra={sorted(set(value).difference(expected))}"
        )
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported memory protocol schema {value['schema_version']!r}"
        )
    if not isinstance(value["case_label"], str) or not value["case_label"]:
        raise ValueError("case_label must be a non-empty string")
    for name in ("sample_index", "payload_bytes"):
        item = value[name]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    interval = value["sampling_interval_seconds"]
    if (
        isinstance(interval, bool)
        or not isinstance(interval, int | float)
        or interval <= 0
    ):
        raise ValueError("sampling_interval_seconds must be positive")
    value["warmup_operation"] = _validate_operation(
        value["warmup_operation"], "warmup_operation"
    )
    value["measured_operation"] = _validate_operation(
        value["measured_operation"], "measured_operation"
    )
    return value


def _require_arguments(
    operation: dict[str, Any],
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    arguments = operation["arguments"]
    expected = required | (optional or set())
    missing = sorted(required.difference(arguments))
    extra = sorted(set(arguments).difference(expected))
    if missing or extra:
        raise ValueError(
            f"{operation['kind']} arguments do not match: "
            f"missing={missing}, extra={extra}"
        )
    return arguments


def _execute_operation(
    operation: dict[str, Any],
    *,
    sceneio: Any,
    payload_bytes: int,
    allocation_headroom_bytes: int,
) -> object:
    kind = operation["kind"]
    if kind == "sceneio_registry":
        _require_arguments(operation, set())
        return sceneio.codecs()
    if kind == "bounded_file_read":
        arguments = _require_arguments(operation, {"path", "read_bytes"})
        read_bytes = arguments["read_bytes"]
        if (
            isinstance(read_bytes, bool)
            or not isinstance(read_bytes, int)
            or read_bytes < 0
        ):
            raise ValueError("bounded_file_read read_bytes must be non-negative")
        with Path(arguments["path"]).open("rb") as stream:
            if stream.seek(0, 2) != payload_bytes:
                raise ValueError(
                    "bounded_file_read source size does not match payload_bytes"
                )
            stream.seek(0)
            value = stream.read(read_bytes)
        if len(value) != read_bytes:
            raise ValueError(
                "bounded_file_read source is shorter than read_bytes"
            )
        return value
    if kind == "allocate_payload":
        arguments = _require_arguments(operation, set(), {"extra_bytes"})
        extra_bytes = arguments.get("extra_bytes", 0)
        if (
            isinstance(extra_bytes, bool)
            or not isinstance(extra_bytes, int)
            or extra_bytes < 0
        ):
            raise ValueError("allocate_payload extra_bytes must be non-negative")
        value = bytearray(
            allocation_headroom_bytes + payload_bytes + extra_bytes
        )
        for offset in range(0, len(value), 4096):
            value[offset] = 1
        if value:
            value[-1] = 1
        return value
    if kind == "sceneio_read":
        arguments = _require_arguments(operation, {"path"}, {"format"})
        return sceneio.read(
            arguments["path"],
            format=arguments.get("format"),
        )
    if kind == "sceneio_inspect":
        arguments = _require_arguments(operation, {"path"}, {"format"})
        return sceneio.inspect(
            arguments["path"],
            format=arguments.get("format"),
        )
    if kind == "sceneio_read_scene":
        arguments = _require_arguments(
            operation,
            {"path"},
            {"time", "load_payloads"},
        )
        keywords = {}
        if "time" in arguments:
            keywords["time"] = arguments["time"]
        if "load_payloads" in arguments:
            load_payloads = arguments["load_payloads"]
            if not isinstance(load_payloads, bool):
                raise ValueError(
                    "sceneio_read_scene load_payloads must be boolean"
                )
            keywords["load_payloads"] = load_payloads
        return sceneio.read_scene(arguments["path"], **keywords)
    if kind == "sceneio_read_tiff_collection":
        arguments = _require_arguments(
            operation,
            {"path"},
            {
                "series_index",
                "level_index",
                "page_range",
                "window",
            },
        )
        keywords = {
            name: arguments[name]
            for name in ("series_index", "level_index")
            if name in arguments
        }
        for name, size in (("page_range", 2), ("window", 4)):
            if name not in arguments:
                continue
            value = arguments[name]
            if (
                not isinstance(value, list)
                or len(value) != size
                or any(
                    isinstance(item, bool) or not isinstance(item, int)
                    for item in value
                )
            ):
                raise ValueError(
                    f"sceneio_read_tiff_collection {name} must contain "
                    f"{size} integers"
                )
            keywords[name] = tuple(value)
        return sceneio.read_tiff_collection(arguments["path"], **keywords)
    if kind == "sceneio_read_partial":
        arguments = _require_arguments(
            operation,
            {"path", "selectors"},
            {"format"},
        )
        selectors = arguments["selectors"]
        if not isinstance(selectors, dict):
            raise ValueError(
                "sceneio_read_partial selectors must be an object"
            )
        return sceneio.read_partial(
            arguments["path"],
            format=arguments.get("format"),
            **selectors,
        )
    if kind == "sceneio_read_label_map":
        arguments = _require_arguments(operation, {"path"}, {"format"})
        return sceneio.read_label_map(
            arguments["path"],
            format=arguments.get("format"),
        )
    if kind == "sceneio_inspect_label_map":
        arguments = _require_arguments(operation, {"path"}, {"format"})
        return sceneio.inspect_label_map(
            arguments["path"],
            format=arguments.get("format"),
        )
    raise ValueError(f"unknown memory operation kind {kind!r}")


def _high_water_rss(
    process: Any,
    *,
    observed_current_rss: int = 0,
) -> tuple[int, str]:
    """Return a coherent lifetime RSS peak and its native backend.

    ``psutil`` current RSS and the platform lifetime counter do not
    necessarily use an identical kernel accounting boundary.  In particular,
    Linux ``/proc`` RSS can briefly exceed ``ru_maxrss`` even though a
    lifetime maximum cannot logically be below an observed current value.
    Preserve the native counter as the named backend while taking the
    monotonic envelope of it and every current-RSS observation.
    """

    memory = process.memory_info()
    peak_wset = getattr(memory, "peak_wset", None)
    if peak_wset is not None:
        return (
            max(int(peak_wset), int(memory.rss), observed_current_rss),
            "psutil_peak_wset",
        )
    try:
        import resource
    except ImportError:
        return (
            max(int(memory.rss), observed_current_rss),
            "psutil_current_only",
        )
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        value *= 1024
    return (
        max(int(value), int(memory.rss), observed_current_rss),
        "resource_ru_maxrss",
    )


def _calibrate_high_water(
    process: Any,
    *,
    attempts: int = 4,
) -> tuple[list[bytearray], int, int, int, str]:
    retained: list[bytearray] = []
    calibration_bytes = 0
    backend = ""
    for _ in range(attempts):
        current = int(process.memory_info().rss)
        high_water, backend = _high_water_rss(
            process,
            observed_current_rss=current,
        )
        headroom = max(0, high_water - current)
        if headroom == 0:
            return retained, calibration_bytes, current, high_water, backend
        extent = headroom + 1024 * 1024
        padding = bytearray(extent)
        for offset in range(0, extent, 4096):
            padding[offset] = 1
        padding[-1] = 1
        retained.append(padding)
        calibration_bytes += extent
    current = int(process.memory_info().rss)
    high_water, backend = _high_water_rss(
        process,
        observed_current_rss=current,
    )
    return retained, calibration_bytes, current, high_water, backend


def _run_available(
    request: dict[str, Any],
    *,
    sceneio: Any,
    psutil: Any,
) -> dict[str, Any]:
    interval_seconds = float(request["sampling_interval_seconds"])
    process = psutil.Process()
    warmup_count = 0
    measured_count = 0
    try:
        warm_value = _execute_operation(
            request["warmup_operation"],
            sceneio=sceneio,
            payload_bytes=0,
            allocation_headroom_bytes=0,
        )
        warmup_count = 1
        del warm_value
        process.memory_info()
        gc.collect()
        (
            calibration_values,
            calibration_bytes,
            baseline,
            baseline_high_water,
            high_water_backend,
        ) = _calibrate_high_water(process)
        headroom = max(0, baseline_high_water - baseline)
        peak = [baseline]
        running = threading.Event()
        running.set()
        ready = threading.Event()
        sampler_errors: list[Exception] = []

        def sample() -> None:
            try:
                while running.is_set():
                    peak[0] = max(peak[0], int(process.memory_info().rss))
                    ready.set()
                    time.sleep(interval_seconds)
            except Exception as exc:
                sampler_errors.append(exc)

        thread = threading.Thread(
            target=sample,
            name="sceneio-memory-sampler",
            daemon=True,
        )
        thread.start()
        if not ready.wait(timeout=5):
            raise RuntimeError("RSS sampler thread did not start")
        try:
            measured_value = _execute_operation(
                request["measured_operation"],
                sceneio=sceneio,
                payload_bytes=request["payload_bytes"],
                allocation_headroom_bytes=(
                    headroom
                    if request["measured_operation"]["kind"]
                    == "allocate_payload"
                    else 0
                ),
            )
            measured_count = 1
            peak[0] = max(peak[0], int(process.memory_info().rss))
        finally:
            running.clear()
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("RSS sampler thread did not stop")
        if sampler_errors:
            raise RuntimeError(
                f"RSS sampler failed: {sampler_errors[0]}"
            ) from sampler_errors[0]
        peak[0] = max(peak[0], int(process.memory_info().rss))
        peak_high_water, _ = _high_water_rss(
            process,
            observed_current_rss=peak[0],
        )
        del measured_value
        del calibration_values
    except Exception as exc:
        return _base_response(
            request,
            status="error",
            sampler=_sampler_metadata(
                available=True,
                backend="psutil_thread",
                interval_seconds=interval_seconds,
            ),
            warmup_operation_count=warmup_count,
            measured_operation_count=measured_count,
            error=exc,
        )

    sampled_delta = max(0, peak[0] - baseline)
    high_water_delta = max(
        0,
        peak_high_water - baseline_high_water,
    )
    response = _base_response(
        request,
        status="available",
        sampler=_sampler_metadata(
            available=True,
            backend=f"psutil_thread+{high_water_backend}",
            interval_seconds=interval_seconds,
        ),
        warmup_operation_count=warmup_count,
        measured_operation_count=measured_count,
    )
    response.update(
        {
            "baseline_rss_bytes": baseline,
            "baseline_high_water_rss_bytes": baseline_high_water,
            "peak_rss_bytes": peak[0],
            "peak_high_water_rss_bytes": peak_high_water,
            "sampled_delta_rss_bytes": sampled_delta,
            "high_water_delta_rss_bytes": high_water_delta,
            "delta_rss_bytes": max(sampled_delta, high_water_delta),
            "high_water_headroom_bytes": headroom,
            "high_water_calibration_bytes": calibration_bytes,
        }
    )
    return response


def _run(request: dict[str, Any]) -> dict[str, Any]:
    interval_seconds = float(request["sampling_interval_seconds"])
    import sceneio

    if os.environ.get("ASAN_OPTIONS") or "libasan" in os.environ.get(
        "LD_PRELOAD", ""
    ):
        error = RuntimeError(
            "instrumented runtime is not comparable for RSS qualification"
        )
        return _base_response(
            request,
            status="unavailable",
            sampler=_sampler_metadata(
                available=False,
                backend=None,
                interval_seconds=interval_seconds,
            ),
            warmup_operation_count=0,
            measured_operation_count=0,
            error=error,
        )
    try:
        import psutil
    except Exception as exc:
        return _base_response(
            request,
            status="unavailable",
            sampler=_sampler_metadata(
                available=False,
                backend=None,
                interval_seconds=interval_seconds,
            ),
            warmup_operation_count=0,
            measured_operation_count=0,
            error=exc,
        )
    return _run_available(request, sceneio=sceneio, psutil=psutil)


def main() -> int:
    try:
        request = _validate_request(json.loads(sys.stdin.read()))
        response = _run(request)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "protocol_error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(response, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
