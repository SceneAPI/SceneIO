"""Strict configuration, scheduling, and statistics for backend qualification."""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_ID = "sceneio.backend-qualification.v1"
SCHEMA_VERSION = 1
_SCALED_MAD = 1.4826
_PPM = 1_000_000


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str,
) -> None:
    expected = required | (optional or set())
    missing = sorted(required.difference(value))
    extra = sorted(set(value).difference(expected))
    if missing or extra:
        raise ValueError(
            f"{label} keys do not match: missing={missing}, extra={extra}"
        )


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(
            f"{label} must be a non-empty list of unique strings"
        )
    return tuple(value)


def _unique_ids(items: Sequence[Any], label: str) -> None:
    ids = [item.id for item in items]
    duplicates = sorted(
        item for item in set(ids) if ids.count(item) > 1
    )
    if duplicates:
        raise ValueError(f"{label} ids must be unique: {duplicates}")


@dataclass(frozen=True, slots=True)
class Methodology:
    local_sessions: int
    remote_sessions: int
    memory_samples: int
    startup_processes: int
    order_seed: int
    clock: str
    sample_policy: str
    summary: str
    cache_mode: str
    lane_policy: str


@dataclass(frozen=True, slots=True)
class Fixture:
    id: str
    fixture_class: str
    height: int
    width: int
    seed: int
    warmups: int
    samples: int
    iterations_per_sample: int
    remote_only: bool

    @property
    def raw_bytes(self) -> int:
        return self.height * self.width * 3


@dataclass(frozen=True, slots=True)
class EncodeProfile:
    id: str
    quality: int
    subsampling: str
    fixtures: tuple[str, ...]
    paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecodeProfile:
    id: str
    kind: str
    quality: int
    subsampling: str
    progressive: bool
    restart_marker_blocks: int
    producers: tuple[str, ...]
    fixtures: tuple[str, ...]
    paths: tuple[str, ...]
    reference: str


@dataclass(frozen=True, slots=True)
class MemoryCase:
    id: str
    operation: str
    path: str
    profile: str
    fixture: str
    producer: str | None


@dataclass(frozen=True, slots=True)
class MatrixCell:
    operation: str
    profile: str
    producer: str | None
    fixture: str
    path: str

    @property
    def id(self) -> str:
        parts = [self.operation, self.profile]
        if self.producer is not None:
            parts.append(self.producer)
        parts.extend((self.fixture, self.path))
        return "/".join(parts)


@dataclass(frozen=True, slots=True)
class QualificationConfig:
    path: Path
    sha256: str
    decision_id: str
    codec_id: str
    retained_backend: str
    candidate_backend: str
    retained_marker: str
    candidate_marker: str
    methodology: Methodology
    thresholds: Mapping[str, int | float]
    fixtures: tuple[Fixture, ...]
    encode_profiles: tuple[EncodeProfile, ...]
    decode_profiles: tuple[DecodeProfile, ...]
    memory_cases: tuple[MemoryCase, ...]

    def fixture(self, fixture_id: str) -> Fixture:
        try:
            return next(item for item in self.fixtures if item.id == fixture_id)
        except StopIteration as exc:
            raise KeyError(fixture_id) from exc

    def encode_profile(self, profile_id: str) -> EncodeProfile:
        try:
            return next(
                item for item in self.encode_profiles if item.id == profile_id
            )
        except StopIteration as exc:
            raise KeyError(profile_id) from exc

    def decode_profile(self, profile_id: str) -> DecodeProfile:
        try:
            return next(
                item for item in self.decode_profiles if item.id == profile_id
            )
        except StopIteration as exc:
            raise KeyError(profile_id) from exc

    def cells(self, *, include_remote: bool) -> tuple[MatrixCell, ...]:
        allowed = {
            fixture.id
            for fixture in self.fixtures
            if include_remote or not fixture.remote_only
        }
        cells: list[MatrixCell] = []
        for profile in self.encode_profiles:
            for fixture in profile.fixtures:
                if fixture not in allowed:
                    continue
                cells.extend(
                    MatrixCell("encode", profile.id, None, fixture, path)
                    for path in profile.paths
                )
        for profile in self.decode_profiles:
            for fixture in profile.fixtures:
                if fixture != "ycck_16x16" and fixture not in allowed:
                    continue
                for producer in profile.producers:
                    cells.extend(
                        MatrixCell(
                            "decode",
                            profile.id,
                            producer,
                            fixture,
                            path,
                        )
                        for path in profile.paths
                    )
        return tuple(cells)


def _parse_methodology(value: Mapping[str, Any]) -> Methodology:
    fields = {
        "local_sessions",
        "remote_sessions",
        "memory_samples",
        "startup_processes",
        "order_seed",
        "clock",
        "sample_policy",
        "summary",
        "cache_mode",
        "lane_policy",
    }
    _require_exact_keys(
        value, required=fields, label="methodology"
    )
    order_seed = value["order_seed"]
    if isinstance(order_seed, bool) or not isinstance(order_seed, int):
        raise ValueError("methodology.order_seed must be an integer")
    return Methodology(
        local_sessions=_positive_int(
            value["local_sessions"], "methodology.local_sessions"
        ),
        remote_sessions=_positive_int(
            value["remote_sessions"], "methodology.remote_sessions"
        ),
        memory_samples=_positive_int(
            value["memory_samples"], "methodology.memory_samples"
        ),
        startup_processes=_positive_int(
            value["startup_processes"],
            "methodology.startup_processes",
        ),
        order_seed=order_seed,
        clock=_nonempty_string(value["clock"], "methodology.clock"),
        sample_policy=_nonempty_string(
            value["sample_policy"], "methodology.sample_policy"
        ),
        summary=_nonempty_string(
            value["summary"], "methodology.summary"
        ),
        cache_mode=_nonempty_string(
            value["cache_mode"], "methodology.cache_mode"
        ),
        lane_policy=_nonempty_string(
            value["lane_policy"], "methodology.lane_policy"
        ),
    )


def _parse_fixture(value: Mapping[str, Any], index: int) -> Fixture:
    required = {
        "id",
        "class",
        "height",
        "width",
        "seed",
        "warmups",
        "samples",
        "iterations_per_sample",
        "remote_only",
    }
    label = f"fixture[{index}]"
    _require_exact_keys(value, required=required, label=label)
    seed = value["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"{label}.seed must be a non-negative integer")
    remote_only = value["remote_only"]
    if not isinstance(remote_only, bool):
        raise ValueError(f"{label}.remote_only must be a boolean")
    return Fixture(
        id=_nonempty_string(value["id"], f"{label}.id"),
        fixture_class=_nonempty_string(
            value["class"], f"{label}.class"
        ),
        height=_positive_int(value["height"], f"{label}.height"),
        width=_positive_int(value["width"], f"{label}.width"),
        seed=seed,
        warmups=_positive_int(value["warmups"], f"{label}.warmups"),
        samples=_positive_int(value["samples"], f"{label}.samples"),
        iterations_per_sample=_positive_int(
            value["iterations_per_sample"],
            f"{label}.iterations_per_sample",
        ),
        remote_only=remote_only,
    )


def _parse_encode_profile(
    value: Mapping[str, Any], index: int
) -> EncodeProfile:
    required = {"id", "quality", "subsampling", "fixtures", "paths"}
    label = f"encode_profile[{index}]"
    _require_exact_keys(value, required=required, label=label)
    quality = _positive_int(value["quality"], f"{label}.quality")
    if quality > 100:
        raise ValueError(f"{label}.quality must be at most 100")
    return EncodeProfile(
        id=_nonempty_string(value["id"], f"{label}.id"),
        quality=quality,
        subsampling=_nonempty_string(
            value["subsampling"], f"{label}.subsampling"
        ),
        fixtures=_string_tuple(
            value["fixtures"], f"{label}.fixtures"
        ),
        paths=_string_tuple(value["paths"], f"{label}.paths"),
    )


def _parse_decode_profile(
    value: Mapping[str, Any], index: int
) -> DecodeProfile:
    required = {
        "id",
        "kind",
        "quality",
        "subsampling",
        "progressive",
        "restart_marker_blocks",
        "producers",
        "fixtures",
        "paths",
        "reference",
    }
    label = f"decode_profile[{index}]"
    _require_exact_keys(value, required=required, label=label)
    quality = _positive_int(value["quality"], f"{label}.quality")
    progressive = value["progressive"]
    if not isinstance(progressive, bool):
        raise ValueError(f"{label}.progressive must be a boolean")
    restart = value["restart_marker_blocks"]
    if isinstance(restart, bool) or not isinstance(restart, int) or restart < 0:
        raise ValueError(
            f"{label}.restart_marker_blocks must be non-negative"
        )
    return DecodeProfile(
        id=_nonempty_string(value["id"], f"{label}.id"),
        kind=_nonempty_string(value["kind"], f"{label}.kind"),
        quality=quality,
        subsampling=_nonempty_string(
            value["subsampling"], f"{label}.subsampling"
        ),
        progressive=progressive,
        restart_marker_blocks=restart,
        producers=_string_tuple(
            value["producers"], f"{label}.producers"
        ),
        fixtures=_string_tuple(
            value["fixtures"], f"{label}.fixtures"
        ),
        paths=_string_tuple(value["paths"], f"{label}.paths"),
        reference=_nonempty_string(
            value["reference"], f"{label}.reference"
        ),
    )


def _parse_memory_case(
    value: Mapping[str, Any], index: int
) -> MemoryCase:
    required = {"id", "operation", "path", "profile", "fixture"}
    optional = {"producer"}
    label = f"memory_case[{index}]"
    _require_exact_keys(
        value, required=required, optional=optional, label=label
    )
    producer = value.get("producer")
    if producer is not None:
        producer = _nonempty_string(producer, f"{label}.producer")
    return MemoryCase(
        id=_nonempty_string(value["id"], f"{label}.id"),
        operation=_nonempty_string(
            value["operation"], f"{label}.operation"
        ),
        path=_nonempty_string(value["path"], f"{label}.path"),
        profile=_nonempty_string(
            value["profile"], f"{label}.profile"
        ),
        fixture=_nonempty_string(
            value["fixture"], f"{label}.fixture"
        ),
        producer=producer,
    )


def _validate_config(config: QualificationConfig) -> None:
    if config.codec_id != "jpeg":
        raise ValueError("v1 qualification config supports only JPEG")
    if config.retained_backend == config.candidate_backend:
        raise ValueError("retained and candidate backends must differ")
    _unique_ids(config.fixtures, "fixture")
    _unique_ids(config.encode_profiles, "encode profile")
    _unique_ids(config.decode_profiles, "decode profile")
    _unique_ids(config.memory_cases, "memory case")

    fixture_ids = {fixture.id for fixture in config.fixtures}
    special_fixture_ids = {"ycck_16x16"}
    encode_ids = {profile.id for profile in config.encode_profiles}
    decode_ids = {profile.id for profile in config.decode_profiles}
    for profile in config.encode_profiles:
        missing = set(profile.fixtures).difference(fixture_ids)
        if missing:
            raise ValueError(
                f"encode profile {profile.id!r} has unknown fixtures "
                f"{sorted(missing)}"
            )
        if not set(profile.paths) <= {
            "core_buffer",
            "core_sink",
            "public_sink",
        }:
            raise ValueError(
                f"encode profile {profile.id!r} has unsupported paths"
            )
    for profile in config.decode_profiles:
        missing = set(profile.fixtures).difference(
            fixture_ids | special_fixture_ids
        )
        if missing:
            raise ValueError(
                f"decode profile {profile.id!r} has unknown fixtures "
                f"{sorted(missing)}"
            )
        if not set(profile.paths) <= {
            "core_bytes",
            "core_mmap",
            "public_path",
        }:
            raise ValueError(
                f"decode profile {profile.id!r} has unsupported paths"
            )
        if profile.producers == (config.candidate_backend,):
            raise ValueError(
                f"decode profile {profile.id!r} is candidate-only"
            )
    q90 = config.encode_profile("rgb8_q90_420")
    if q90.quality != 90 or q90.paths != ("core_buffer",):
        raise ValueError(
            "q90 is core-buffer-only because the public sink fixes quality 95"
        )
    q95 = config.encode_profile("rgb8_q95_444")
    if q95.quality != 95 or set(q95.paths) != {
        "core_buffer",
        "core_sink",
        "public_sink",
    }:
        raise ValueError("q95 must cover core buffer and both sink surfaces")
    expected_decode = {
        "baseline_rgb_420",
        "baseline_rgb_444",
        "progressive_rgb",
        "restart_markers",
        "grayscale",
        "cmyk",
        "ycck",
    }
    if decode_ids != expected_decode or encode_ids != {
        "rgb8_q90_420",
        "rgb8_q95_444",
    }:
        raise ValueError("JPEG qualification profile set is incomplete")
    for case in config.memory_cases:
        if case.fixture not in fixture_ids:
            raise ValueError(
                f"memory case {case.id!r} has unknown fixture"
            )
        if case.operation == "encode":
            if case.profile not in encode_ids or case.producer is not None:
                raise ValueError(
                    f"encode memory case {case.id!r} is inconsistent"
                )
        elif case.operation == "decode":
            if case.profile not in decode_ids or case.producer is None:
                raise ValueError(
                    f"decode memory case {case.id!r} is inconsistent"
                )
        else:
            raise ValueError(
                f"memory case {case.id!r} has invalid operation"
            )


def load_config(path: str | Path) -> QualificationConfig:
    """Load and validate the frozen backend-qualification matrix."""

    resolved = Path(path).resolve()
    raw = resolved.read_bytes()
    payload = tomllib.loads(raw.decode("utf-8"))
    required = {
        "schema_version",
        "decision_id",
        "codec_id",
        "retained_backend",
        "candidate_backend",
        "retained_marker",
        "candidate_marker",
        "methodology",
        "thresholds",
        "fixture",
        "encode_profile",
        "decode_profile",
        "memory_case",
    }
    _require_exact_keys(payload, required=required, label="configuration")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported qualification schema {payload['schema_version']!r}"
        )
    thresholds = payload["thresholds"]
    if not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("thresholds must be a non-empty table")
    if any(
        not isinstance(name, str)
        or isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        for name, value in thresholds.items()
    ):
        raise ValueError("thresholds must contain finite numeric values")
    config = QualificationConfig(
        path=resolved,
        sha256=hashlib.sha256(raw).hexdigest(),
        decision_id=_nonempty_string(
            payload["decision_id"], "decision_id"
        ),
        codec_id=_nonempty_string(payload["codec_id"], "codec_id"),
        retained_backend=_nonempty_string(
            payload["retained_backend"], "retained_backend"
        ),
        candidate_backend=_nonempty_string(
            payload["candidate_backend"], "candidate_backend"
        ),
        retained_marker=_nonempty_string(
            payload["retained_marker"], "retained_marker"
        ),
        candidate_marker=_nonempty_string(
            payload["candidate_marker"], "candidate_marker"
        ),
        methodology=_parse_methodology(payload["methodology"]),
        thresholds=dict(sorted(thresholds.items())),
        fixtures=tuple(
            _parse_fixture(value, index)
            for index, value in enumerate(payload["fixture"])
        ),
        encode_profiles=tuple(
            _parse_encode_profile(value, index)
            for index, value in enumerate(payload["encode_profile"])
        ),
        decode_profiles=tuple(
            _parse_decode_profile(value, index)
            for index, value in enumerate(payload["decode_profile"])
        ),
        memory_cases=tuple(
            _parse_memory_case(value, index)
            for index, value in enumerate(payload["memory_case"])
        ),
    )
    _validate_config(config)
    return config


def paired_schedule(
    *,
    retained: str,
    candidate: str,
    sessions: int,
    seed: int,
) -> tuple[dict[str, Any], ...]:
    """Return seeded, balanced paired rounds with both backends exactly once."""

    _positive_int(sessions, "sessions")
    if sessions % 2:
        raise ValueError("paired qualification requires an even session count")
    randomizer = random.Random(seed)
    starts = [retained] * (sessions // 2) + [candidate] * (sessions // 2)
    randomizer.shuffle(starts)
    rounds = []
    for index, first in enumerate(starts):
        second = candidate if first == retained else retained
        rounds.append(
            {
                "round": index,
                "order": [first, second],
                "seed": seed + index,
            }
        )
    return tuple(rounds)


def median_mad_ns(samples: Sequence[int]) -> dict[str, int]:
    """Return exact integer median and unscaled MAD for positive durations."""

    if not samples or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in samples
    ):
        raise ValueError("timing samples must be positive integers")
    median = int(statistics.median(samples))
    deviations = [abs(value - median) for value in samples]
    return {
        "count": len(samples),
        "median_ns": median,
        "mad_ns": int(statistics.median(deviations)),
    }


def paired_ratio_summary(
    retained_session_medians: Sequence[int],
    candidate_session_medians: Sequence[int],
) -> dict[str, int]:
    """Summarize paired retained/candidate speed ratios in integer ppm."""

    if (
        not retained_session_medians
        or len(retained_session_medians) != len(candidate_session_medians)
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in (
                *retained_session_medians,
                *candidate_session_medians,
            )
        )
    ):
        raise ValueError("paired medians must be equal positive integer lists")
    logs = [
        math.log(retained / candidate)
        for retained, candidate in zip(
            retained_session_medians,
            candidate_session_medians,
            strict=True,
        )
    ]
    center = statistics.median(logs)
    scaled_mad = _SCALED_MAD * statistics.median(
        abs(value - center) for value in logs
    )
    robust_lower = math.exp(center - 2 * scaled_mad)
    return {
        "pairs": len(logs),
        "median_ratio_ppm": round(math.exp(center) * _PPM),
        "scaled_log_mad_ppm": round(scaled_mad * _PPM),
        "robust_lower_ratio_ppm": round(robust_lower * _PPM),
    }


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize strict canonical JSON with a trailing newline."""

    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "SCHEMA_ID",
    "SCHEMA_VERSION",
    "DecodeProfile",
    "EncodeProfile",
    "Fixture",
    "MatrixCell",
    "MemoryCase",
    "Methodology",
    "QualificationConfig",
    "canonical_json_bytes",
    "load_config",
    "median_mad_ns",
    "paired_ratio_summary",
    "paired_schedule",
]
