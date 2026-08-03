"""CLI and orchestration for the large-file benchmark closure run."""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import math
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import cases_arrays_points, cases_scene
from .measure import environment_snapshot, provider_infos
from .model import (
    MIB,
    SCHEMA_VERSION,
    CaseArtifact,
    CaseDefinition,
    Measurement,
    OperationResult,
    artifact_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKER_TIMEOUT_SECONDS = 300.0


def _case_modules():
    return (cases_arrays_points, cases_scene)


def case_definitions() -> dict[str, CaseDefinition]:
    result: dict[str, CaseDefinition] = {}
    for module in _case_modules():
        values = module.case_definitions()
        if isinstance(values, dict):
            result.update(values)
        else:
            result.update({item.id: item for item in values})
    return result


def _module_for(case_id: str):
    for module in _case_modules():
        if case_id in module.case_definitions():
            return module
    raise KeyError(case_id)


def _providers_for_operation(
    definition: CaseDefinition, operation: str
) -> tuple[str, ...]:
    if operation == "image":
        return tuple(
            provider for provider in definition.providers if provider == "sceneio"
        )
    if operation != "inspect":
        return definition.providers
    module = _module_for(definition.id)
    adapters_factory = getattr(module, "provider_adapters", None)
    if adapters_factory is None:
        return definition.providers
    adapters = adapters_factory(definition.id)
    return tuple(
        provider
        for provider in definition.providers
        if adapters[provider].inspect is not None
    )


def _validate_artifact_size(
    definition: CaseDefinition, artifact: CaseArtifact, tier: str
) -> None:
    target = definition.standard_logical_bytes
    if tier == "standard" and target > 0 and artifact.logical_bytes < target:
        raise ValueError(
            f"{definition.id} logical payload is {artifact.logical_bytes} bytes; "
            f"standard requires at least {target}"
        )


def _prepare_in_child(
    definition: CaseDefinition,
    tier: str,
    cache: Path,
    sources: dict[str, Any],
    timeout_seconds: float,
) -> CaseArtifact:
    source_paths = {
        source_id: str(getattr(source, "path", source))
        for source_id, source in sources.items()
    }
    result = _run_child(
        {
            "request_kind": "prepare",
            "case_id": definition.id,
            "tier": tier,
            "cache": str(cache),
            "sources": source_paths,
        },
        timeout_seconds,
    )
    if result.get("status") != "ok":
        raise RuntimeError(result.get("error", "fixture preparation worker failed"))
    return CaseArtifact.from_dict(dict(result["artifact"]))


def _selected_cases(only: Iterable[str] | None) -> list[CaseDefinition]:
    definitions = case_definitions()
    if not only:
        return list(definitions.values())
    wanted = set(only)
    selected = [
        definition
        for definition in definitions.values()
        if definition.id in wanted or definition.format in wanted
    ]
    unknown = wanted.difference({item.id for item in selected}).difference(
        {item.format for item in selected}
    )
    if unknown:
        raise ValueError(f"unknown large benchmark case(s): {', '.join(sorted(unknown))}")
    return selected


def _sources_api():
    from .sources import acquire_sources, load_sources, verify_sources

    return load_sources, acquire_sources, verify_sources


def acquire_sources(cache: Path, only: Iterable[str] | None = None):
    """Delegate source acquisition to the L1 immutable manifest layer."""

    _, acquire, _ = _sources_api()
    return acquire(cache, only=only)


def verify_sources(cache: Path, only: Iterable[str] | None = None):
    """Delegate source verification to the L1 manifest layer."""

    _, _, verify = _sources_api()
    return verify(cache, only=only)


def _git_identity() -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None
        return result.stdout.strip()

    status = run("status", "--porcelain")
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(status)}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    return str(value)


def _source_summary(source: Any) -> dict[str, Any]:
    spec = getattr(source, "spec", None)
    source_path = Path(getattr(source, "path", ""))
    try:
        portable_path = source_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        portable_path = str(source_path)
    result = {
        "source_id": getattr(spec, "id", None),
        "path": portable_path,
        "size_bytes": getattr(source, "size_bytes", None),
        "sha256": getattr(source, "sha256", None),
    }
    if spec is not None:
        result.update(
            {
                "url": getattr(spec, "url", None),
                "repository": getattr(spec, "repository", None),
                "revision": getattr(spec, "revision", None),
                "revision_type": getattr(spec, "revision_type", None),
                "source_path": getattr(spec, "source_path", None),
                "license": getattr(spec, "license", None),
                "license_url": getattr(spec, "license_url", None),
                "attribution": getattr(spec, "attribution", None),
                "media_type": getattr(spec, "media_type", None),
                "acquisition": getattr(spec, "acquisition", None),
                "derivation": getattr(spec, "derivation", None),
                "sceneio_direct_supported": getattr(
                    spec, "sceneio_direct_supported", None
                ),
                "sceneio_direct_reason": getattr(
                    spec, "sceneio_direct_reason", None
                ),
            }
        )
    return _json_safe(result)


def _run_child(
    request: dict[str, Any], timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS
) -> dict[str, Any]:
    command = [sys.executable, "-m", "bench.io_bench.large.worker"]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            input=json.dumps(request),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"worker exceeded {timeout_seconds:g} seconds",
            "timeout_seconds": timeout_seconds,
        }
    output = completed.stdout.strip().splitlines()
    if output:
        try:
            return json.loads(output[-1])
        except json.JSONDecodeError:
            pass
    return {
        "status": "error",
        "error": completed.stderr.strip() or "worker returned no JSON result",
        "returncode": completed.returncode,
    }


def _measurement(value: dict[str, Any]) -> Measurement:
    return Measurement(
        raw_seconds=tuple(float(item) for item in value.get("raw_seconds", [])),
        median_seconds=float(value.get("median_seconds", 0.0)),
        traced_peak_bytes=value.get("traced_peak_bytes"),
        rss_delta_bytes=value.get("rss_delta_bytes"),
        cache_mode=str(value.get("cache_mode", "warm")),
    )


def _path_size(path: Path) -> int:
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return path.stat().st_size


def _representative_encoded_size(
    operation: str, paths: Iterable[str], fallback: int
) -> int | None:
    if operation != "write":
        return fallback
    for value in paths:
        path = Path(value)
        try:
            if path.exists():
                size = _path_size(path)
                if size > 0:
                    return size
        except OSError:
            continue
    return None


def _common_read_check(artifact: CaseArtifact, module: Any) -> dict[str, Any]:
    """Validate one common fixture against every available provider."""

    checker = getattr(module, "common_read_check", None)
    if checker is not None:
        return checker(artifact)
    checker = getattr(module, "validate_common_input", None)
    if checker is not None:
        return checker(artifact)
    adapters_factory = getattr(module, "provider_adapters", None)
    if adapters_factory is None:
        return {"status": "skip", "profile": "no-common-provider-contract"}
    adapters = adapters_factory(artifact.case_id)
    try:
        reference = adapters["sceneio"].read(artifact.path)
    except Exception as exc:
        return {"status": "fail", "profile": "sceneio_common_decode", "error": str(exc)}
    checked: list[str] = []
    for provider, adapter in adapters.items():
        if provider == "sceneio":
            continue
        try:
            other = adapter.read(artifact.path)
            module.compare_case(artifact.case_id, reference, other)
        except Exception as exc:
            if isinstance(exc, getattr(module, "ProviderUnavailable", RuntimeError)):
                continue
            return {
                "status": "fail",
                "profile": f"{artifact.case_id}:common_provider_semantic-v1",
                "provider": provider,
                "error": str(exc),
            }
        checked.append(provider)
    if not checked:
        return {
            "status": "skip",
            "profile": f"{artifact.case_id}:common_provider_semantic-v1",
            "reason": "no independent provider available",
        }
    return {
        "status": "pass",
        "profile": f"{artifact.case_id}:common_provider_semantic-v1",
        "providers": ["sceneio", *checked],
    }


def _timed_operation(
    artifact: CaseArtifact,
    provider: str,
    operation: str,
    *,
    runs: int,
    output_dir: Path,
    cache_mode: str,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> OperationResult:
    base = {
        "case_id": artifact.case_id,
        "tier": artifact.tier,
        "provider": provider,
        "operation": operation,
        "artifact": artifact.to_dict(),
        "path": str(artifact.path),
        "runs": runs,
        "cache_mode": cache_mode,
        "output_root": str(output_dir),
    }
    timing = _run_child(
        {**base, "mode": "timing", "output_dir": str(output_dir / "timing")},
        timeout_seconds,
    )
    if timing.get("status") != "ok":
        measurement = Measurement((), 0.0, None, None, cache_mode)
        return OperationResult(
            artifact.case_id,
            provider,
            operation,
            measurement,
            artifact.logical_bytes,
            artifact.encoded_bytes,
            status=str(timing.get("status", "error")),
            error=timing.get("error"),
        )
    timing_paths = tuple(timing.get("output_paths", []))
    timing_encoded_bytes = _representative_encoded_size(
        operation, timing_paths, artifact.encoded_bytes
    )
    if operation == "write" and timing_encoded_bytes is None:
        return OperationResult(
            artifact.case_id,
            provider,
            operation,
            _measurement(timing["measurement"]),
            artifact.logical_bytes,
            0,
            status="error",
            output_paths=timing_paths,
            error="write worker returned no non-empty output",
        )
    memory = _run_child(
        {**base, "mode": "memory", "output_dir": str(output_dir / "memory")},
        timeout_seconds,
    )
    if memory.get("status") != "ok":
        measurement = _measurement(timing["measurement"])
        encoded_bytes = timing_encoded_bytes or artifact.encoded_bytes
        return OperationResult(
            artifact.case_id,
            provider,
            operation,
            measurement,
            artifact.logical_bytes,
            encoded_bytes,
            status=str(memory.get("status", "error")),
            diagnostic=dict(timing.get("diagnostic", {})),
            output_paths=timing_paths,
            error=memory.get("error"),
        )
    timed = _measurement(timing["measurement"])
    mem = _measurement(memory["measurement"])
    combined = Measurement(
        raw_seconds=timed.raw_seconds,
        median_seconds=timed.median_seconds,
        traced_peak_bytes=mem.traced_peak_bytes,
        rss_delta_bytes=mem.rss_delta_bytes,
        cache_mode=cache_mode,
    )
    output_paths = tuple(
        dict.fromkeys(
            [*timing.get("output_paths", []), *memory.get("output_paths", [])]
        )
    )
    encoded_bytes = (
        timing_encoded_bytes
        if operation == "write"
        else artifact.encoded_bytes
    )
    diagnostic = dict(timing.get("diagnostic", {}))
    diagnostic["memory_metrics"] = {
        "traced_peak_bytes": {
            "status": "available" if mem.traced_peak_bytes is not None else "unavailable",
            "reason": None if mem.traced_peak_bytes is not None else "worker returned no tracemalloc metric",
        },
        "rss_delta_bytes": {
            "status": "available" if mem.rss_delta_bytes is not None else "unavailable",
            "reason": None if mem.rss_delta_bytes is not None else "psutil RSS metric unavailable",
        },
    }
    if operation == "write":
        diagnostic["representative_encoded_bytes"] = encoded_bytes
    return OperationResult(
        artifact.case_id,
        provider,
        operation,
        combined,
        artifact.logical_bytes,
        encoded_bytes,
        diagnostic=diagnostic,
        output_paths=output_paths,
    )


def _cross_reads(artifact: CaseArtifact, operations: list[OperationResult]) -> list[dict[str, Any]]:
    module = _module_for(artifact.case_id)
    definitions = module.case_definitions()
    providers = definitions[artifact.case_id].providers
    outputs: dict[str, Path | None] = {}
    for provider in providers:
        write = next(
            (
                row
                for row in operations
                if row.operation == "write" and row.provider == provider
            ),
            None,
        )
        outputs[provider] = (
            next(
                (Path(value) for value in write.output_paths if Path(value).exists()),
                None,
            )
            if write is not None and write.status == "ok"
            else None
        )
    rows = list(module.cross_read_matrix(artifact, outputs))
    try:
        rows.append(
            {
                "case_id": artifact.case_id,
                "kind": "common_file_cross_read",
                **_common_read_check(artifact, module),
            }
        )
    except Exception as exc:
        rows.append(
            {
                "case_id": artifact.case_id,
                "kind": "common_file_cross_read",
                "status": "fail",
                "error": str(exc),
            }
        )
    partial_checker = getattr(module, "partial_read_check", None)
    if partial_checker is not None and any(
        row.operation in {"point_select", "image"} for row in operations
    ):
        try:
            rows.append(
                {
                    "case_id": artifact.case_id,
                    "kind": "partial_read",
                    **partial_checker(artifact),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "case_id": artifact.case_id,
                    "kind": "partial_read",
                    "status": "fail",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    read_rows = [item for item in operations if item.operation in {"read", "full_scan", "map_open"}]
    read_rows.extend(
        item
        for item in operations
        if item.operation in {"inspect", "point_select", "image"}
    )
    for operation in sorted({row.operation for row in read_rows}):
        selected = [row for row in read_rows if row.operation == operation and row.status == "ok"]
        if selected and operation == "full_scan":
            values = [row.diagnostic.get("reduction") for row in selected]
            equal = all(value == values[0] for value in values[1:])
            rows.append(
                {
                    "case_id": artifact.case_id,
                    "kind": "common_file_read",
                    "operation": operation,
                    "status": "pass" if equal else "fail",
                    "profile": "fixed_float64_reduction",
                    "values": values,
                }
            )
        elif selected and operation == "inspect":
            diagnostics = [row.diagnostic for row in selected]
            equal = all(value == diagnostics[0] for value in diagnostics[1:])
            rows.append(
                {
                    "case_id": artifact.case_id,
                    "kind": "common_file_read",
                    "operation": operation,
                    "status": "pass" if equal else "fail",
                    "profile": "normalized_provider_metadata",
                    "providers": [row.provider for row in selected],
                    "values": diagnostics,
                }
            )
        elif selected:
            rows.append(
                {
                    "case_id": artifact.case_id,
                    "kind": "common_file_read",
                    "operation": operation,
                    "status": "pass",
                    "profile": "provider_operations_completed",
                    "providers": [row.provider for row in selected],
                }
            )
    return rows


def _cross_reads_in_child(
    artifact: CaseArtifact,
    operations: list[OperationResult],
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """Run decode-heavy validation under the same timeout as timed workers."""

    result = _run_child(
        {
            "request_kind": "validation",
            "case_id": artifact.case_id,
            "artifact": artifact.to_dict(),
            "operations": [row.to_dict() for row in operations],
        },
        timeout_seconds,
    )
    if result.get("status") == "ok":
        return list(result.get("cross_reads", []))
    return [
        {
            "case_id": artifact.case_id,
            "kind": "validation_worker",
            "status": "fail",
            "error": result.get("error", "validation worker failed"),
        }
    ]


def _cleanup_output_dir(output_dir: Path, cache: Path) -> dict[str, Any]:
    """Remove one case's bounded output tree and report the result."""

    root = (cache / "outputs").resolve()
    resolved = output_dir.resolve()
    if root not in resolved.parents:
        return {
            "path": str(output_dir),
            "status": "fail",
            "error": "output path is outside the benchmark output root",
        }
    try:
        if resolved.exists():
            shutil.rmtree(resolved)
    except OSError as exc:
        return {
            "path": str(output_dir),
            "status": "fail",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"path": str(output_dir), "status": "pass"}


def _memory_evidence(
    operations: list[OperationResult], tier: str
) -> list[dict[str, Any]]:
    """Evaluate the no-file-sized-Python-copy contract for SceneIO full I/O."""

    checked_operations = {"map_open", "read", "full_scan", "write"}
    rows: list[dict[str, Any]] = []
    for operation in operations:
        if (
            operation.provider != "sceneio"
            or operation.operation not in checked_operations
            or operation.status != "ok"
        ):
            continue
        traced = operation.measurement.traced_peak_bytes
        bound = max(5 * MIB, int(operation.encoded_bytes * 0.25))
        conclusive = operation.encoded_bytes >= 20 * MIB
        if conclusive:
            status = "pass" if traced is not None and traced <= bound else "fail"
        else:
            status = "pass" if tier == "smoke" and traced is not None else "fail"
        rows.append(
            {
                "case_id": operation.case_id,
                "provider": operation.provider,
                "operation": operation.operation,
                "status": status,
                "traced_peak_bytes": traced,
                "bound_bytes": bound,
                "conclusive": conclusive,
                "profile": (
                    "no_approximately_file_sized_python_allocation"
                    if conclusive
                    else "small_fixture_allocation_diagnostic"
                ),
                "reason": (
                    "fixture is below the 20 MiB conclusive threshold"
                    if not conclusive
                    else None
                    if traced is not None
                    else "tracemalloc metric unavailable"
                ),
            }
        )
    return rows


def run_benchmark(
    *,
    tier: str = "smoke",
    runs: int = 3,
    cache: Path = Path("build/bench-data/large-io"),
    only: Iterable[str] | None = None,
    cold_cache: bool = False,
    worker_timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Prepare selected cases and run each provider operation in fresh children."""

    if tier not in {"smoke", "standard", "stress"}:
        raise ValueError("tier must be smoke, standard, or stress")
    if runs < 1:
        raise ValueError("runs must be positive")
    if runs > 20:
        raise ValueError("runs must not exceed 20")
    if tier == "standard" and runs != 3:
        raise ValueError("standard tier requires exactly 3 timed samples")
    if tier == "stress" and runs < 3:
        raise ValueError("stress tier requires at least 3 timed samples")
    if worker_timeout_seconds <= 0:
        raise ValueError("worker_timeout_seconds must be positive")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(cache)
    selected = _selected_cases(only)
    environment = environment_snapshot()
    required_free_bytes = {
        "smoke": 64 * MIB,
        "standard": 2 * 1024 * MIB,
        "stress": 6 * 1024 * MIB,
    }[tier]
    if disk.free < required_free_bytes:
        raise RuntimeError(
            f"large benchmark needs at least {required_free_bytes} free bytes; "
            f"cache volume has {disk.free}"
        )
    required_available_ram_bytes = {
        "smoke": 256 * MIB,
        "standard": 8 * 1024 * MIB,
        "stress": 16 * 1024 * MIB,
    }[tier]
    available_ram = environment.get("available_ram_bytes")
    if (
        isinstance(available_ram, int)
        and available_ram < required_available_ram_bytes
    ):
        raise RuntimeError(
            f"large benchmark needs at least {required_available_ram_bytes} bytes "
            f"of available RAM; host reports {available_ram}"
        )
    optional_smoke_source_ids = {
        item.source_id
        for item in selected
        if tier == "smoke" and item.id == "laz_autzen" and item.source_id
    }
    source_ids = [
        item.source_id
        for item in selected
        if item.source_id and item.source_id not in optional_smoke_source_ids
    ]
    cache_control = {
        "requested": bool(cold_cache),
        "applied": False,
        "status": "unavailable" if cold_cache else "not_requested",
        "reason": (
            "no portable cache-eviction operation is applied by this harness"
            if cold_cache
            else None
        ),
    }
    source_verification: dict[str, Any]
    try:
        sources = verify_sources(cache, only=source_ids) if source_ids else {}
        source_verification = {
            "status": "verified" if source_ids else "not_required",
            "required_source_ids": sorted(set(source_ids)),
            "optional_source_ids": sorted(optional_smoke_source_ids),
            "verified_source_ids": sorted(sources),
        }
    except Exception as exc:
        sources = {}
        source_verification = {
            "status": "failed",
            "required_source_ids": sorted(set(source_ids)),
            "optional_source_ids": sorted(optional_smoke_source_ids),
            "verified_source_ids": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    artifacts: list[CaseArtifact] = []
    skips: list[dict[str, Any]] = []
    operations: list[OperationResult] = []
    cross_reads: list[dict[str, Any]] = []
    cleanup_results: list[dict[str, Any]] = []
    preparations: list[dict[str, Any]] = []
    for definition in selected:
        output_dir = cache / "outputs" / definition.id / tier
        preparation_started = time.perf_counter()
        try:
            artifact = _prepare_in_child(
                definition,
                tier,
                cache,
                dict(sources),
                worker_timeout_seconds,
            )
            _validate_artifact_size(definition, artifact, tier)
        except Exception as exc:
            preparations.append(
                {
                    "case_id": definition.id,
                    "seconds": time.perf_counter() - preparation_started,
                    "status": "fail",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            skips.append({"case_id": definition.id, "reason": str(exc), "type": type(exc).__name__})
            cleanup_results.append(_cleanup_output_dir(output_dir, cache))
            continue
        preparations.append(
            {
                "case_id": definition.id,
                "seconds": time.perf_counter() - preparation_started,
                "status": "pass",
            }
        )
        artifacts.append(artifact)
        cache_mode = "cold-unavailable" if cold_cache else "warm"
        try:
            for operation in definition.operations:
                # Cross-read is a validation after all provider writes, not a
                # duplicate timed read.
                if operation == "cross_read":
                    continue
                for provider in _providers_for_operation(definition, operation):
                    row = _timed_operation(
                        artifact,
                        provider,
                        operation,
                        runs=runs,
                        output_dir=output_dir,
                        cache_mode=cache_mode,
                        timeout_seconds=worker_timeout_seconds,
                    )
                    operations.append(row)
                    if row.status != "ok":
                        skips.append(
                            {
                                "case_id": row.case_id,
                                "provider": row.provider,
                                "operation": row.operation,
                                "reason": row.error,
                                "type": row.status,
                            }
                        )
            case_operations = [
                item for item in operations if item.case_id == artifact.case_id
            ]
            cross_reads.extend(
                _cross_reads_in_child(
                    artifact,
                    case_operations,
                    worker_timeout_seconds,
                )
            )
        finally:
            cleanup_results.append(_cleanup_output_dir(output_dir, cache))

    provider_names = {
        provider for definition in selected for provider in definition.providers
    }
    if "laspy" in provider_names:
        provider_names.add("lazrs")
    provider_versions = {
        key: value.to_dict() for key, value in provider_infos(provider_names).items()
    }
    required_case_ids = {definition.id for definition in selected}
    artifact_case_ids = {artifact.case_id for artifact in artifacts}
    required_rows = {
        (definition.id, provider, operation)
        for definition in selected
        for operation in definition.operations
        if operation != "cross_read"
        for provider in _providers_for_operation(definition, operation)
    }
    row_keys = {
        (row.case_id, row.provider, row.operation)
        for row in operations
        if row.status == "ok"
    }
    cross_by_case: dict[str, list[dict[str, Any]]] = {}
    for row in cross_reads:
        cross_by_case.setdefault(str(row.get("case_id")), []).append(row)
    completion_reasons: list[str] = []
    if source_verification["status"] == "failed":
        completion_reasons.append("one or more required licensed sources failed verification")
    if artifact_case_ids != required_case_ids:
        completion_reasons.append("one or more required fixtures were not prepared")
    missing_rows = sorted(required_rows.difference(row_keys))
    if missing_rows:
        completion_reasons.append(f"missing provider operations: {missing_rows}")
    expected_directional = {
        (definition.id, writer, reader)
        for definition in selected
        for writer in definition.providers
        for reader in definition.providers
    }
    actual_directional = {
        (
            str(row.get("case_id")),
            str(row.get("writer_provider")),
            str(row.get("reader_provider")),
        )
        for row in cross_reads
        if row.get("kind") == "provider_output_cross_read"
    }
    missing_directional = sorted(expected_directional.difference(actual_directional))
    if missing_directional:
        completion_reasons.append(
            f"missing directional provider output reads: {missing_directional}"
        )
    common_check_cases = {
        str(row.get("case_id"))
        for row in cross_reads
        if row.get("kind") == "common_file_cross_read"
    }
    missing_common_checks = sorted(required_case_ids.difference(common_check_cases))
    if missing_common_checks:
        completion_reasons.append(
            f"missing common-input oracle checks: {missing_common_checks}"
        )
    failed_cross = [
        row
        for case_id in required_case_ids
        for row in cross_by_case.get(case_id, [])
        if row.get("status") != "pass"
    ]
    if any(case_id not in cross_by_case for case_id in required_case_ids):
        completion_reasons.append("one or more cases lack cross-read validation")
    if failed_cross:
        completion_reasons.append("one or more cross-read checks failed or were skipped")
    failed_cleanup = [row for row in cleanup_results if row.get("status") != "pass"]
    if failed_cleanup:
        completion_reasons.append(f"one or more output cleanups failed: {failed_cleanup}")
    sample_issues: list[str] = []
    for row in operations:
        if row.status != "ok":
            continue
        measurement = row.measurement
        if len(measurement.raw_seconds) != runs:
            sample_issues.append(
                f"{row.case_id}/{row.provider}/{row.operation}: expected {runs} samples"
            )
        if not math.isfinite(measurement.median_seconds) or measurement.median_seconds <= 0:
            sample_issues.append(
                f"{row.case_id}/{row.provider}/{row.operation}: invalid median"
            )
        if measurement.traced_peak_bytes is None or measurement.rss_delta_bytes is None:
            sample_issues.append(
                f"{row.case_id}/{row.provider}/{row.operation}: memory metric unavailable"
            )
    if sample_issues:
        completion_reasons.append(f"invalid measurement rows: {sample_issues}")
    memory_checks = _memory_evidence(operations, tier)
    if not memory_checks or any(row["status"] != "pass" for row in memory_checks):
        completion_reasons.append("one or more SceneIO allocation checks failed")
    correctness_passed = not completion_reasons
    complete = correctness_passed and not skips
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _datetime.datetime.now(_datetime.UTC).isoformat(),
        "sceneio": _git_identity(),
        "environment": environment,
        "providers": provider_versions,
        "source_verification": source_verification,
        "sources": {key: _source_summary(value) for key, value in sources.items()},
        "tier": tier,
        "runs": runs,
        "worker_timeout_seconds": worker_timeout_seconds,
        "cache_mode": "cold-unavailable" if cold_cache else "warm",
        "cache_control": cache_control,
        "cache_storage": {
            "path": str(cache),
            "volume_total_bytes": disk.total,
            "volume_free_bytes": disk.free,
            "required_free_bytes": required_free_bytes,
            "required_available_ram_bytes": required_available_ram_bytes,
            "fixture_policy": "generated or verified in cache; large inputs are not committed",
            "output_policy": "provider outputs retained through cross-read, then removed",
        },
        "cases": [artifact_summary(item) for item in artifacts],
        "preparations": preparations,
        "operations": [item.to_dict() for item in operations],
        "cross_reads": cross_reads,
        "memory_checks": memory_checks,
        "cleanup": cleanup_results,
        "skips": skips,
        "required_cases": sorted(required_case_ids),
        "correctness_passed": correctness_passed,
        "complete": complete,
        "completion_reasons": completion_reasons,
    }


def report_markdown(document: dict[str, Any]) -> str:
    """Render provenance, raw measurements, ratios, and validation status."""

    sceneio = document.get("sceneio", {})
    cache = document.get("cache_storage", {})
    lines = [
        "# Large-file I/O benchmark",
        "",
        f"Schema: `{document.get('schema_version')}`  ",
        f"Tier: `{document.get('tier')}`  ",
        f"Generated: `{document.get('generated_at_utc')}`  ",
        f"Commit: `{sceneio.get('commit')}` (dirty={sceneio.get('dirty')})  ",
        f"Cache mode: `{document.get('cache_mode')}`  ",
        f"Cache control: `{json.dumps(document.get('cache_control', {}), sort_keys=True)}`  ",
        f"Completion: **{document.get('complete')}**; correctness: **{document.get('correctness_passed')}**",
        f"Source verification: **{document.get('source_verification', {}).get('status', 'unknown')}**",
        "",
        f"Cache path: `{cache.get('path', '-')}`. {cache.get('fixture_policy', '')}",
        f"Outputs: {cache.get('output_policy', 'not recorded')}.",
        "",
        "## Fixture provenance",
        "",
        "| Case | Source | Acquisition | Prepare s | Logical MiB | Encoded MiB | Derivation |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    preparation_by_case = {
        row.get("case_id"): row for row in document.get("preparations", [])
    }
    for fixture in document.get("cases", []):
        preparation = preparation_by_case.get(fixture.get("case_id"), {})
        lines.append(
            "| {case_id} | {source} | {mode} | {prepare:.3f} | {logical:.3f} | {encoded:.3f} | {derivation} |".format(
                case_id=fixture.get("case_id"),
                source=fixture.get("source_id") or "synthetic",
                mode=fixture.get("acquisition_mode"),
                prepare=float(preparation.get("seconds", 0.0)),
                logical=(fixture.get("logical_bytes", 0) / MIB),
                encoded=(fixture.get("encoded_bytes", 0) / MIB),
                derivation=json.dumps(fixture.get("derivation", {}), sort_keys=True),
            )
        )
    if document.get("sources"):
        lines.extend(
            [
                "",
                "### Licensed sources",
                "",
                "| Source | Asset / repository | Pin type | License | Acquisition | Attribution | Size bytes | SHA-256 |",
                "| --- | --- | --- | --- | --- | --- | ---: | --- |",
            ]
        )
        for source_id, source in sorted(document["sources"].items()):
            lines.append(
                "| {source} | [asset]({url}) / [repository]({repository}) | `{revision}` ({revision_type}) | [{license}]({license_url}) | {acquisition} | {attribution} | {size} | `{sha}` |".format(
                    source=source_id,
                    url=source.get("url") or "-",
                    repository=source.get("repository") or source.get("url") or "-",
                    revision=source.get("revision") or "-",
                    revision_type=source.get("revision_type") or "-",
                    license=source.get("license") or "-",
                    license_url=source.get("license_url") or source.get("url") or "-",
                    acquisition=source.get("acquisition") or "-",
                    attribution=source.get("attribution") or "-",
                    size=source.get("size_bytes") or "-",
                    sha=source.get("sha256") or "-",
                )
            )
    lines.extend(
        [
            "",
            "## Environment and providers",
            "",
            f"Platform: `{document.get('environment', {}).get('platform')}`; Python: `{document.get('environment', {}).get('python_implementation')}`; compiler: `{document.get('environment', {}).get('compiler')}`.",
            f"CPU count: `{document.get('environment', {}).get('cpu_count')}`; RAM: `{(document.get('environment', {}).get('ram_bytes') or 0) / MIB:.1f} MiB`.",
            f"Thread policy: `{document.get('environment', {}).get('thread_policy', 'provider defaults')}`; variables: `{json.dumps(document.get('environment', {}).get('thread_variables', {}), sort_keys=True)}`.",
            "",
            "| Provider | Distribution version | Revision/build | Module |",
            "| --- | --- | --- | --- |",
        ]
    )
    for provider, info in sorted(document.get("providers", {}).items()):
        revision = info.get("revision") or info.get("build") or "-"
        lines.append(f"| {provider} | {info.get('version') or '-'} | {revision} | {info.get('module') or '-'} |")
    lines.extend(
        [
            "",
            "## Measurements",
            "",
            "Raw samples are seconds from a fresh timing child; memory is a separate fresh child.",
            "",
            "| Case | Provider | Operation | Median s | Raw samples | Logical MiB/s | Encoded MiB/s | RSS delta MiB | Trace peak MiB | Status |",
            "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in document.get("operations", []):
        measurement = row.get("measurement", {})
        lines.append(
            "| {case_id} | {provider} | {operation} | {median:.6g} | {raw} | {logical} | {encoded} | {rss} | {trace} | {status} |".format(
                case_id=row.get("case_id"),
                provider=row.get("provider"),
                operation=row.get("operation"),
                median=measurement.get("median_seconds") or 0.0,
                raw=json.dumps(measurement.get("raw_seconds", [])),
                logical=(
                    f"{row['logical_mib_s']:.3f}" if row.get("logical_mib_s") is not None else "-"
                ),
                encoded=(
                    f"{row['encoded_mib_s']:.3f}" if row.get("encoded_mib_s") is not None else "-"
                ),
                rss=(
                    f"{measurement['rss_delta_bytes'] / MIB:.3f}"
                    if measurement.get("rss_delta_bytes") is not None
                    else "-"
                ),
                trace=(
                    f"{measurement['traced_peak_bytes'] / MIB:.3f}"
                    if measurement.get("traced_peak_bytes") is not None
                    else "-"
                ),
                status=row.get("status"),
            )
        )
    matching_ops = {"read", "full_scan", "write"}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in document.get("operations", []):
        if row.get("operation") in matching_ops and row.get("status") == "ok":
            groups.setdefault((row.get("case_id"), row.get("operation")), []).append(row)
    lines.extend(["", "## Matching-operation ratios", "", "The SceneIO/reference speed ratio is reference seconds divided by SceneIO seconds within the same case and full operation; values above 1 favor SceneIO. Map-open, partial, and inspect rows are excluded.", "", "| Case | Operation | Reference | SceneIO/reference speed ratio |", "| --- | --- | --- | ---: |"])
    for (case_id, operation), rows in sorted(groups.items()):
        sceneio_row = next((row for row in rows if row.get("provider") == "sceneio"), None)
        if sceneio_row is None:
            continue
        sceneio_median = sceneio_row.get("measurement", {}).get("median_seconds") or 0.0
        for row in sorted(rows, key=lambda item: item.get("provider", "")):
            if row.get("provider") == "sceneio":
                continue
            median = row.get("measurement", {}).get("median_seconds") or 0.0
            ratio = median / sceneio_median if sceneio_median > 0 else None
            ratio_text = f"{ratio:.3f}" if ratio is not None else "-"
            lines.append(f"| {case_id} | {operation} | {row.get('provider')} | {ratio_text} |")
    lines.extend(["", "## Correctness validation", "", "| Case | Check | Writer | Reader/operation | Status | Profile |", "| --- | --- | --- | --- | --- | --- |"])
    for row in document.get("cross_reads", []):
        reader = row.get("reader_provider") or row.get("operation") or "-"
        lines.append(f"| {row.get('case_id')} | {row.get('kind')} | {row.get('writer_provider', '-')} | {reader} | {row.get('status')} | {row.get('profile', '-')} |")
    lines.extend(
        [
            "",
            "## SceneIO allocation checks",
            "",
            "| Case | Operation | Trace peak MiB | Bound MiB | Conclusive | Status | Profile / reason |",
            "| --- | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in document.get("memory_checks", []):
        trace = row.get("traced_peak_bytes")
        bound = row.get("bound_bytes")
        lines.append(
            "| {case} | {operation} | {trace} | {bound} | {conclusive} | {status} | {profile}{reason} |".format(
                case=row.get("case_id"),
                operation=row.get("operation"),
                trace=f"{trace / MIB:.3f}" if trace is not None else "-",
                bound=f"{bound / MIB:.3f}" if bound is not None else "-",
                conclusive=row.get("conclusive"),
                status=row.get("status"),
                profile=row.get("profile", "-"),
                reason=f"; {row['reason']}" if row.get("reason") else "",
            )
        )
    if document.get("skips"):
        lines.extend(["", "## Skips", ""])
        lines.extend(f"- {item}" for item in document["skips"])
    if document.get("completion_reasons"):
        lines.extend(["", "## Completion limits", ""])
        lines.extend(f"- {item}" for item in document["completion_reasons"])
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "These measurements describe this recorded machine, provider versions, fixture profiles, and warm-cache run. They are comparative evidence, not portable throughput guarantees. Licensed assets are provenance seeds; transformed cases are labeled derived fixtures.",
        ]
    )
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            f"`{sys.executable} bench/bench_large_io.py run --tier {document.get('tier', 'smoke')} --runs {document.get('runs', 3)} --cache {cache.get('path', 'build/bench-data/large-io')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Large-file SceneIO benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("acquire", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--cache", type=Path, default=Path("build/bench-data/large-io"))
        command.add_argument("--only", action="append")
    run = sub.add_parser("run")
    run.add_argument("--tier", choices=("smoke", "standard", "stress"), default="smoke")
    run.add_argument("--runs", type=int, default=3)
    run.add_argument("--cache", type=Path, default=Path("build/bench-data/large-io"))
    run.add_argument("--only", action="append")
    run.add_argument("--cold-cache", action="store_true")
    run.add_argument(
        "--worker-timeout",
        type=float,
        default=DEFAULT_WORKER_TIMEOUT_SECONDS,
        help="maximum seconds allowed for one provider operation child",
    )
    run.add_argument("--json", type=Path)
    report = sub.add_parser("report")
    report.add_argument("json", type=Path)
    report.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"acquire", "verify"}:
        values = acquire_sources(args.cache, args.only) if args.command == "acquire" else verify_sources(args.cache, args.only)
        print(json.dumps({key: _source_summary(value) for key, value in values.items()}, indent=2))
        return 0
    if args.command == "run":
        document = run_benchmark(
            tier=args.tier,
            runs=args.runs,
            cache=args.cache,
            only=args.only,
            cold_cache=args.cold_cache,
            worker_timeout_seconds=args.worker_timeout,
        )
        rendered = json.dumps(document, indent=2)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        if args.tier in {"standard", "stress"} and not document.get("complete", False):
            return 1
        return 0
    document = json.loads(args.json.read_text(encoding="utf-8"))
    rendered = report_markdown(document)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


__all__ = [
    "acquire_sources",
    "case_definitions",
    "main",
    "report_markdown",
    "run_benchmark",
    "verify_sources",
]
