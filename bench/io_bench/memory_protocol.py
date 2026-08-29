"""Fresh-child resident-memory measurements for I/O qualification.

The ordinary benchmark table intentionally keeps its historical warmed-parent
RSS metric.  This module provides the separate, qualification-grade protocol:
each sample starts a new interpreter, warms SceneIO before the baseline, and
executes exactly one measured operation.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_SAMPLES = 3
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_SAMPLING_INTERVAL_SECONDS = 0.0005
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_RSS_FIELDS = (
    "baseline_rss_bytes",
    "baseline_high_water_rss_bytes",
    "peak_rss_bytes",
    "peak_high_water_rss_bytes",
    "sampled_delta_rss_bytes",
    "high_water_delta_rss_bytes",
    "delta_rss_bytes",
)
_PATH_ARGUMENTS = frozenset({"path"})
_AVAILABLE_SAMPLER_BACKENDS = frozenset(
    {
        "psutil_thread+psutil_peak_wset",
        "psutil_thread+resource_ru_maxrss",
        "psutil_thread+psutil_current_only",
    }
)


class MemoryProtocolError(RuntimeError):
    """The fresh-child measurement protocol could not produce valid evidence."""


class MemoryMeasurementUnavailable(MemoryProtocolError):
    """The requested child-process sampler is unavailable."""


class MemoryQualificationFailed(MemoryProtocolError):
    """Measured resident-memory growth exceeded the declared bound."""


@dataclass(frozen=True)
class MemoryOperation:
    """One controlled operation understood by the fresh-child runner."""

    kind: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError(
                "memory operation kind must be a non-empty string"
            )
        if not isinstance(self.arguments, Mapping):
            raise ValueError("memory operation arguments must be a mapping")
        try:
            json.dumps(self.arguments, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "memory operation arguments must be JSON-compatible"
            ) from exc

    def as_request(self) -> dict[str, Any]:
        """Return an isolated JSON-compatible operation object."""

        return {
            "kind": self.kind,
            "arguments": json.loads(
                json.dumps(self.arguments, allow_nan=False)
            ),
        }


def operation_signature(
    operation: Mapping[str, Any],
    *,
    include_path: bool = False,
) -> str:
    """Return a comparable operation identity.

    Measured series may vary only their carrier path. Warm-up identities
    include that path so independently collected matrices cannot hide a
    payload-dependent warm-up.
    """

    kind = operation.get("kind")
    arguments = operation.get("arguments")
    if not isinstance(kind, str) or not isinstance(arguments, Mapping):
        raise ValueError("operation signature requires kind and arguments")
    comparable = {
        key: value
        for key, value in arguments.items()
        if include_path or key not in _PATH_ARGUMENTS
    }
    if kind == "allocate_payload":
        comparable.setdefault("extra_bytes", 0)
    elif kind in {
        "sceneio_read",
        "sceneio_inspect",
        "sceneio_read_partial",
    }:
        comparable.setdefault("format", None)
    rendered = json.dumps(
        comparable,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{kind}:{rendered}"


@dataclass(frozen=True)
class MemoryCase:
    """One payload size and measured operation in a qualification matrix."""

    label: str
    payload_bytes: int
    operation: MemoryOperation

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("memory case label must be a non-empty string")
        if (
            isinstance(self.payload_bytes, bool)
            or not isinstance(self.payload_bytes, int)
            or self.payload_bytes < 0
        ):
            raise ValueError("payload_bytes must be a non-negative integer")


@dataclass(frozen=True)
class MemorySample:
    """One versioned result returned by a fresh child process."""

    schema_version: int
    status: str
    case_label: str
    sample_index: int
    payload_bytes: int
    platform: Mapping[str, str]
    sampler: Mapping[str, Any]
    warmup_operation: str
    warmup_operation_signature: str
    measured_operation: str
    measured_operation_signature: str
    warmup_operation_count: int
    measured_operation_count: int
    baseline_rss_bytes: int | None
    baseline_high_water_rss_bytes: int | None
    peak_rss_bytes: int | None
    peak_high_water_rss_bytes: int | None
    sampled_delta_rss_bytes: int | None
    high_water_delta_rss_bytes: int | None
    delta_rss_bytes: int | None
    high_water_headroom_bytes: int | None
    high_water_calibration_bytes: int | None
    error_type: str | None
    error_message: str | None

    @classmethod
    def from_response(cls, response: Mapping[str, Any]) -> MemorySample:
        """Validate and construct one child response."""

        required = {
            "schema_version",
            "status",
            "case_label",
            "sample_index",
            "payload_bytes",
            "platform",
            "sampler",
            "warmup_operation",
            "warmup_operation_signature",
            "measured_operation",
            "measured_operation_signature",
            "warmup_operation_count",
            "measured_operation_count",
            *_RSS_FIELDS,
            "high_water_headroom_bytes",
            "high_water_calibration_bytes",
            "error_type",
            "error_message",
        }
        missing = sorted(required.difference(response))
        extra = sorted(set(response).difference(required))
        if missing or extra:
            raise MemoryProtocolError(
                "child response fields do not match schema: "
                f"missing={missing}, extra={extra}"
            )
        if response["schema_version"] != SCHEMA_VERSION:
            raise MemoryProtocolError(
                "unsupported memory protocol schema "
                f"{response['schema_version']!r}"
            )
        status = response["status"]
        if status not in {"available", "unavailable", "error"}:
            raise MemoryProtocolError(
                f"invalid memory protocol status {status!r}"
            )
        if not isinstance(response["platform"], dict):
            raise MemoryProtocolError("child platform metadata must be an object")
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in response["platform"].items()
        ):
            raise MemoryProtocolError(
                "child platform metadata must contain string keys and values"
            )
        sampler = response["sampler"]
        if not isinstance(sampler, dict) or not isinstance(
            sampler.get("available"), bool
        ):
            raise MemoryProtocolError(
                "child sampler metadata must declare boolean availability"
            )
        interval = sampler.get("interval_seconds")
        if (
            isinstance(interval, bool)
            or not isinstance(interval, int | float)
            or interval <= 0
        ):
            raise MemoryProtocolError(
                "child sampler interval must be a positive number"
            )
        backend = sampler.get("backend")
        if backend is not None and not isinstance(backend, str):
            raise MemoryProtocolError(
                "child sampler backend must be a string or null"
            )
        for name in (
            "case_label",
            "warmup_operation",
            "warmup_operation_signature",
            "measured_operation",
            "measured_operation_signature",
        ):
            if not isinstance(response[name], str) or not response[name]:
                raise MemoryProtocolError(
                    f"child response {name} must be a non-empty string"
                )
        for name in ("sample_index", "payload_bytes"):
            value = response[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MemoryProtocolError(
                    f"child response {name} must be a non-negative integer"
                )
        for name in ("warmup_operation_count", "measured_operation_count"):
            value = response[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MemoryProtocolError(
                    f"child response {name} must be a non-negative integer"
                )
        rss_values = {name: response[name] for name in _RSS_FIELDS}
        if status == "available":
            if not sampler["available"]:
                raise MemoryProtocolError(
                    "available sample reports an unavailable sampler"
                )
            if not isinstance(backend, str) or not backend:
                raise MemoryProtocolError(
                    "available sample must report a non-empty sampler backend"
                )
            if backend not in _AVAILABLE_SAMPLER_BACKENDS:
                raise MemoryProtocolError(
                    f"available sample reports unknown sampler backend {backend!r}"
                )
            if any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in rss_values.values()
            ):
                raise MemoryProtocolError(
                    "available sample must report non-negative integer RSS values"
                )
            if response["measured_operation_count"] != 1:
                raise MemoryProtocolError(
                    "available sample must execute exactly one measured operation"
                )
            if response["warmup_operation_count"] != 1:
                raise MemoryProtocolError(
                    "available sample must execute exactly one warm-up operation"
                )
            if (
                response["baseline_high_water_rss_bytes"]
                < response["baseline_rss_bytes"]
                or response["peak_high_water_rss_bytes"]
                < response["peak_rss_bytes"]
            ):
                raise MemoryProtocolError(
                    "high-water RSS must not be below current RSS"
                )
            if (
                response["peak_rss_bytes"] < response["baseline_rss_bytes"]
                or response["peak_high_water_rss_bytes"]
                < response["baseline_high_water_rss_bytes"]
                or response["sampled_delta_rss_bytes"]
                != response["peak_rss_bytes"]
                - response["baseline_rss_bytes"]
                or response["high_water_delta_rss_bytes"]
                != response["peak_high_water_rss_bytes"]
                - response["baseline_high_water_rss_bytes"]
                or response["delta_rss_bytes"]
                != max(
                    response["sampled_delta_rss_bytes"],
                    response["high_water_delta_rss_bytes"],
                )
            ):
                raise MemoryProtocolError(
                    "available sample reports inconsistent RSS values"
                )
            headroom = response["high_water_headroom_bytes"]
            if (
                isinstance(headroom, bool)
                or not isinstance(headroom, int)
                or headroom < 0
            ):
                raise MemoryProtocolError(
                    "available sample must report non-negative high-water headroom"
                )
            if headroom != (
                response["baseline_high_water_rss_bytes"]
                - response["baseline_rss_bytes"]
            ):
                raise MemoryProtocolError(
                    "high-water headroom does not match the reported baselines"
                )
            calibration = response["high_water_calibration_bytes"]
            if (
                isinstance(calibration, bool)
                or not isinstance(calibration, int)
                or calibration < 0
            ):
                raise MemoryProtocolError(
                    "available sample must report non-negative high-water calibration"
                )
            if response["error_type"] is not None or response["error_message"] is not None:
                raise MemoryProtocolError(
                    "available sample must not report an error"
                )
        else:
            if sampler["available"] and status == "unavailable":
                raise MemoryProtocolError(
                    "unavailable sample reports an available sampler"
                )
            if status == "unavailable" and backend is not None:
                raise MemoryProtocolError(
                    "unavailable sample must report a null sampler backend"
                )
            if any(value is not None for value in rss_values.values()):
                raise MemoryProtocolError(
                    f"{status} sample must report RSS values as null"
                )
            if response["high_water_headroom_bytes"] is not None:
                raise MemoryProtocolError(
                    f"{status} sample must report high-water headroom as null"
                )
            if response["high_water_calibration_bytes"] is not None:
                raise MemoryProtocolError(
                    f"{status} sample must report high-water calibration as null"
                )
            if status == "unavailable" and (
                response["warmup_operation_count"] != 0
                or response["measured_operation_count"] != 0
            ):
                raise MemoryProtocolError(
                    "unavailable sample must not report executed operations"
                )
        return cls(**response)

    def as_dict(self) -> dict[str, Any]:
        """Return the stable JSON representation of this sample."""

        return asdict(self)


@dataclass(frozen=True)
class PayloadGrowthAssessment:
    """Payload-relative resident-memory result across two or more sizes."""

    status: str
    passed: bool
    payload_sizes_bytes: tuple[int, ...]
    samples_per_payload: int | None
    median_delta_rss_bytes: Mapping[int, int]
    comparisons: Mapping[int, Mapping[str, int | bool]]
    payload_growth_bytes: int | None
    measured_growth_bytes: int | None
    allowed_growth_bytes: int | None
    max_growth_fraction: float
    fixed_allowance_bytes: int
    reason: str


def _child_request(
    case: MemoryCase,
    warmup: MemoryOperation,
    sample_index: int,
    sampling_interval_seconds: float,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "case_label": case.label,
        "sample_index": sample_index,
        "payload_bytes": case.payload_bytes,
        "sampling_interval_seconds": sampling_interval_seconds,
        "warmup_operation": warmup.as_request(),
        "measured_operation": case.operation.as_request(),
    }


def _assert_response_matches_request(
    sample: MemorySample,
    request: Mapping[str, Any],
) -> None:
    expected_warmup = request["warmup_operation"]
    expected_measured = request["measured_operation"]
    mismatches = []
    if sample.case_label != request["case_label"]:
        mismatches.append("case_label")
    if sample.sample_index != request["sample_index"]:
        mismatches.append("sample_index")
    if sample.payload_bytes != request["payload_bytes"]:
        mismatches.append("payload_bytes")
    if sample.warmup_operation != expected_warmup["kind"]:
        mismatches.append("warmup_operation")
    if sample.warmup_operation_signature != operation_signature(
        expected_warmup,
        include_path=True,
    ):
        mismatches.append("warmup_operation_signature")
    if sample.measured_operation != expected_measured["kind"]:
        mismatches.append("measured_operation")
    if sample.measured_operation_signature != operation_signature(
        expected_measured
    ):
        mismatches.append("measured_operation_signature")
    if (
        sample.sampler["interval_seconds"]
        != request["sampling_interval_seconds"]
    ):
        mismatches.append("sampling_interval_seconds")
    if mismatches:
        raise MemoryProtocolError(
            "fresh-child response does not match its request: "
            f"{', '.join(mismatches)}"
        )


def _run_child(
    request: Mapping[str, Any],
    *,
    python_executable: str,
    timeout_seconds: float,
    child_environment: Mapping[str, str] | None,
) -> MemorySample:
    environment = os.environ.copy()
    if child_environment is not None:
        environment.update(child_environment)
    inherited_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(_REPOSITORY_ROOT)
        if not inherited_pythonpath
        else os.pathsep.join(
            (str(_REPOSITORY_ROOT), inherited_pythonpath)
        )
    )
    try:
        completed = subprocess.run(
            [
                python_executable,
                "-m",
                "bench.io_bench.memory_child",
            ],
            env=environment,
            input=json.dumps(request, allow_nan=False),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise MemoryProtocolError(
            "fresh-child memory sample timed out: "
            f"case={request['case_label']!r}, "
            f"sample={request['sample_index']}, "
            f"stdout={exc.stdout!r}, stderr={exc.stderr!r}"
        ) from exc
    if completed.returncode != 0:
        raise MemoryProtocolError(
            "fresh-child memory sample exited unsuccessfully: "
            f"case={request['case_label']!r}, "
            f"sample={request['sample_index']}, "
            f"returncode={completed.returncode}, "
            f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
        )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MemoryProtocolError(
            "fresh-child memory sample returned invalid JSON: "
            f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
        ) from exc
    if not isinstance(response, dict):
        raise MemoryProtocolError("fresh-child response must be a JSON object")
    sample = MemorySample.from_response(response)
    _assert_response_matches_request(sample, request)
    if sample.status == "error":
        raise MemoryProtocolError(
            "fresh-child operation failed: "
            f"{sample.error_type}: {sample.error_message}"
        )
    return sample


def measure_memory_cases(
    cases: Sequence[MemoryCase],
    *,
    warmup: MemoryOperation | None = None,
    samples: int = DEFAULT_SAMPLES,
    strict: bool = False,
    sampling_interval_seconds: float = DEFAULT_SAMPLING_INTERVAL_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    python_executable: str | os.PathLike[str] = sys.executable,
    child_environment: Mapping[str, str] | None = None,
) -> list[MemorySample]:
    """Measure each case repeatedly in a new, warmed child process.

    ``strict=True`` is the qualification mode: an unavailable sampler raises
    :class:`MemoryMeasurementUnavailable`.  Developer probes may use
    ``strict=False`` and retain explicit ``unavailable`` samples whose RSS
    fields are all ``None``.
    """

    if not cases:
        raise ValueError("at least one memory case is required")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("samples must be a positive integer")
    if strict and samples < DEFAULT_SAMPLES:
        raise ValueError(
            "strict qualification requires at least "
            f"{DEFAULT_SAMPLES} samples per payload"
        )
    if sampling_interval_seconds <= 0:
        raise ValueError("sampling_interval_seconds must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    labels = [case.label for case in cases]
    if len(set(labels)) != len(labels):
        raise ValueError("memory case labels must be unique")
    warmup = warmup or MemoryOperation("sceneio_registry")

    results: list[MemorySample] = []
    for case in cases:
        for sample_index in range(samples):
            request = _child_request(
                case,
                warmup,
                sample_index,
                sampling_interval_seconds,
            )
            sample = _run_child(
                request,
                python_executable=os.fspath(python_executable),
                timeout_seconds=timeout_seconds,
                child_environment=child_environment,
            )
            if sample.status == "unavailable" and strict:
                raise MemoryMeasurementUnavailable(
                    "fresh-child RSS sampler is unavailable: "
                    f"{sample.error_type}: {sample.error_message}"
                )
            if (
                sample.status == "available"
                and strict
                and sample.high_water_headroom_bytes
            ):
                raise MemoryMeasurementUnavailable(
                    "fresh-child sample is inconclusive because "
                    f"{sample.high_water_headroom_bytes} bytes remain below "
                    "the pre-measurement high-water mark"
                )
            if (
                sample.status == "available"
                and strict
                and "current_only" in sample.sampler["backend"]
            ):
                raise MemoryMeasurementUnavailable(
                    "fresh-child high-water sampler is unavailable on "
                    "this platform"
                )
            results.append(sample)
    return results


def assess_payload_growth(
    samples: Sequence[MemorySample],
    *,
    max_growth_fraction: float = 0.25,
    fixed_allowance_bytes: int = 8 * 1024 * 1024,
) -> PayloadGrowthAssessment:
    """Assess whether median RSS growth remains bounded as payload grows."""

    if not samples:
        raise ValueError("at least one memory sample is required")
    if not 0 <= max_growth_fraction < 1:
        raise ValueError("max_growth_fraction must be in [0, 1)")
    if (
        isinstance(fixed_allowance_bytes, bool)
        or not isinstance(fixed_allowance_bytes, int)
        or fixed_allowance_bytes < 0
    ):
        raise ValueError("fixed_allowance_bytes must be a non-negative integer")
    unavailable = [sample for sample in samples if sample.status != "available"]
    if unavailable:
        statuses = ", ".join(
            f"{sample.case_label}[{sample.sample_index}]={sample.status}"
            for sample in unavailable
        )
        return PayloadGrowthAssessment(
            status="unavailable",
            passed=False,
            payload_sizes_bytes=tuple(
                sorted({sample.payload_bytes for sample in samples})
            ),
            samples_per_payload=None,
            median_delta_rss_bytes={},
            comparisons={},
            payload_growth_bytes=None,
            measured_growth_bytes=None,
            allowed_growth_bytes=None,
            max_growth_fraction=max_growth_fraction,
            fixed_allowance_bytes=fixed_allowance_bytes,
            reason=f"one or more samples are unavailable: {statuses}",
        )

    current_only = [
        sample
        for sample in samples
        if "current_only" in sample.sampler["backend"]
    ]
    if current_only:
        return PayloadGrowthAssessment(
            status="unavailable",
            passed=False,
            payload_sizes_bytes=tuple(
                sorted({sample.payload_bytes for sample in samples})
            ),
            samples_per_payload=None,
            median_delta_rss_bytes={},
            comparisons={},
            payload_growth_bytes=None,
            measured_growth_bytes=None,
            allowed_growth_bytes=None,
            max_growth_fraction=max_growth_fraction,
            fixed_allowance_bytes=fixed_allowance_bytes,
            reason="platform high-water sampling is unavailable",
        )

    obscured = [
        sample
        for sample in samples
        if sample.high_water_headroom_bytes
    ]
    if obscured:
        statuses = ", ".join(
            f"{sample.case_label}[{sample.sample_index}]="
            f"{sample.high_water_headroom_bytes}"
            for sample in obscured
        )
        return PayloadGrowthAssessment(
            status="unavailable",
            passed=False,
            payload_sizes_bytes=tuple(
                sorted({sample.payload_bytes for sample in samples})
            ),
            samples_per_payload=None,
            median_delta_rss_bytes={},
            comparisons={},
            payload_growth_bytes=None,
            measured_growth_bytes=None,
            allowed_growth_bytes=None,
            max_growth_fraction=max_growth_fraction,
            fixed_allowance_bytes=fixed_allowance_bytes,
            reason=(
                "pre-measurement high-water headroom makes one or more "
                f"samples inconclusive: {statuses}"
            ),
        )

    measured_signatures = {
        sample.measured_operation_signature for sample in samples
    }
    if len(measured_signatures) != 1:
        raise ValueError(
            "payload growth assessment requires one measured operation signature"
        )
    warmup_signatures = {
        sample.warmup_operation_signature for sample in samples
    }
    if len(warmup_signatures) != 1:
        raise ValueError(
            "payload growth assessment requires one warm-up operation signature"
        )
    grouped: dict[int, list[int]] = defaultdict(list)
    sample_indexes: dict[int, list[int]] = defaultdict(list)
    for sample in samples:
        assert sample.delta_rss_bytes is not None
        grouped[sample.payload_bytes].append(sample.delta_rss_bytes)
        sample_indexes[sample.payload_bytes].append(sample.sample_index)
    payload_sizes = tuple(sorted(grouped))
    if len(payload_sizes) < 2:
        raise ValueError("payload growth assessment requires at least two sizes")
    counts = {len(grouped[size]) for size in payload_sizes}
    if len(counts) != 1:
        raise ValueError(
            "payload growth assessment requires equal samples per size"
        )
    expected_indexes = list(range(next(iter(counts))))
    if any(
        sorted(sample_indexes[size]) != expected_indexes
        for size in payload_sizes
    ):
        raise ValueError(
            "payload growth assessment requires contiguous unique sample indexes"
        )
    medians = {
        size: int(statistics.median(grouped[size]))
        for size in payload_sizes
    }
    smallest = payload_sizes[0]
    comparisons: dict[int, dict[str, int | bool]] = {}
    for size in payload_sizes[1:]:
        payload_growth = size - smallest
        measured_growth = max(0, medians[size] - medians[smallest])
        allowed_growth = max(
            fixed_allowance_bytes,
            int(payload_growth * max_growth_fraction),
        )
        comparisons[size] = {
            "payload_growth_bytes": payload_growth,
            "measured_growth_bytes": measured_growth,
            "allowed_growth_bytes": allowed_growth,
            "passed": measured_growth <= allowed_growth,
        }
    passed = all(
        bool(comparison["passed"])
        for comparison in comparisons.values()
    )
    selected_size = (
        max(
            comparisons,
            key=lambda size: (
                int(comparisons[size]["measured_growth_bytes"])
                - int(comparisons[size]["allowed_growth_bytes"])
            ),
        )
        if not passed
        else payload_sizes[-1]
    )
    selected = comparisons[selected_size]
    payload_growth = int(selected["payload_growth_bytes"])
    measured_growth = int(selected["measured_growth_bytes"])
    allowed_growth = int(selected["allowed_growth_bytes"])
    relation = "within" if passed else "above"
    return PayloadGrowthAssessment(
        status="passed" if passed else "failed",
        passed=passed,
        payload_sizes_bytes=payload_sizes,
        samples_per_payload=next(iter(counts)),
        median_delta_rss_bytes=medians,
        comparisons=comparisons,
        payload_growth_bytes=payload_growth,
        measured_growth_bytes=measured_growth,
        allowed_growth_bytes=allowed_growth,
        max_growth_fraction=max_growth_fraction,
        fixed_allowance_bytes=fixed_allowance_bytes,
        reason=(
            f"median RSS growth {measured_growth} bytes is {relation} "
            f"the {allowed_growth}-byte bound"
        ),
    )


def require_bounded_payload_growth(
    samples: Sequence[MemorySample],
    *,
    max_growth_fraction: float = 0.25,
    fixed_allowance_bytes: int = 8 * 1024 * 1024,
) -> PayloadGrowthAssessment:
    """Return a passing assessment or raise a qualification exception."""

    assessment = assess_payload_growth(
        samples,
        max_growth_fraction=max_growth_fraction,
        fixed_allowance_bytes=fixed_allowance_bytes,
    )
    if assessment.status == "unavailable":
        raise MemoryMeasurementUnavailable(assessment.reason)
    if (
        assessment.samples_per_payload is None
        or assessment.samples_per_payload < DEFAULT_SAMPLES
    ):
        raise MemoryQualificationFailed(
            "qualification requires at least "
            f"{DEFAULT_SAMPLES} samples per payload"
        )
    if not assessment.passed:
        raise MemoryQualificationFailed(assessment.reason)
    return assessment


__all__ = [
    "DEFAULT_SAMPLES",
    "DEFAULT_SAMPLING_INTERVAL_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "SCHEMA_VERSION",
    "MemoryCase",
    "MemoryMeasurementUnavailable",
    "MemoryOperation",
    "MemoryProtocolError",
    "MemoryQualificationFailed",
    "MemorySample",
    "PayloadGrowthAssessment",
    "assess_payload_growth",
    "measure_memory_cases",
    "operation_signature",
    "require_bounded_payload_growth",
]
