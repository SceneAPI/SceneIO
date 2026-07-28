"""Controller for paired installed-wheel JPEG backend qualification."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import dataclasses
import hashlib
import json
import math
import os
import random
import shutil
import statistics
import subprocess
import threading
import time
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.io_bench.backend_qualification.model import (
    SCHEMA_ID,
    SCHEMA_VERSION,
    QualificationConfig,
    canonical_json_bytes,
    load_config,
    median_mad_ns,
    paired_ratio_summary,
    paired_schedule,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "bench" / "BACKEND_QUALIFICATION.toml"
WORKER_SOURCE = Path(__file__).with_name("child.py")
YCCK_SOURCE = (
    ROOT
    / "bench"
    / "fixtures"
    / "jpeg"
    / "ycck_16x16_q90_420.b64"
)
_PPM = 1_000_000
_MEMORY_SAMPLING_INTERVAL_SECONDS = 0.0005
REPORT_KEYS = frozenset(
    {
        "schema",
        "schema_version",
        "result_state",
        "decision_id",
        "codec_id",
        "platform_profile",
        "source",
        "configuration",
        "worker",
        "environments",
        "wheels",
        "cmake_manifests",
        "simd_evidence",
        "corpus",
        "schedule",
        "raw_sessions",
        "startup",
        "determinism",
        "memory",
        "aggregates",
        "validation",
    }
)
_PLATFORM_REQUIREMENTS = {
    "windows_msvc_x86_64": {
        "system": "Windows",
        "cmake_system": "Windows",
        "machines": {"amd64", "x86_64"},
        "compiler": "MSVC",
        "compiler_major": None,
        "simd_architecture": "X86_64",
    },
    "manylinux2014_gcc10_x86_64": {
        "system": "Linux",
        "cmake_system": "Linux",
        "machines": {"amd64", "x86_64"},
        "compiler": "GNU",
        "compiler_major": "10",
        "simd_architecture": "X86_64",
    },
    "macos_appleclang_arm64": {
        "system": "Darwin",
        "cmake_system": "Darwin",
        "machines": {"aarch64", "arm64"},
        "compiler": "AppleClang",
        "compiler_major": None,
        "simd_architecture": "ARM64",
    },
}


@dataclass(frozen=True, slots=True)
class BackendSpec:
    id: str
    expected_marker: str
    python: Path
    wheel: Path
    cmake_manifest: Path
    simd_evidence: Path | None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_file(value: str | Path, label: str) -> Path:
    path = Path(value).resolve()
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_identity(*, allow_dirty: bool) -> dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    clean = not status
    if not clean and not allow_dirty:
        raise RuntimeError(
            "official qualification requires a clean source tree"
        )
    return {
        "commit": commit,
        "tree": tree,
        "clean": clean,
        "dirty_status_sha256": (
            None if clean else _sha256_bytes(status.encode("utf-8"))
        ),
    }


def _worker_config(
    config: QualificationConfig,
    *,
    include_remote: bool,
    quick: bool,
) -> dict[str, Any]:
    allowed = {
        fixture.id
        for fixture in config.fixtures
        if include_remote or not fixture.remote_only
    }
    if quick:
        allowed = {"small_odd"}
    fixtures = []
    for item in config.fixtures:
        if item.id not in allowed:
            continue
        fixtures.append(
            {
                "id": item.id,
                "class": item.fixture_class,
                "height": item.height,
                "width": item.width,
                "seed": item.seed,
                "warmups": 1 if quick else item.warmups,
                "samples": 1 if quick else item.samples,
                "iterations_per_sample": (
                    1 if quick else item.iterations_per_sample
                ),
                "remote_only": item.remote_only,
            }
        )
    encode_profiles = [
        {
            "id": item.id,
            "quality": item.quality,
            "subsampling": item.subsampling,
            "fixtures": [
                fixture
                for fixture in item.fixtures
                if fixture in allowed
            ],
            "paths": list(item.paths),
        }
        for item in config.encode_profiles
    ]
    decode_profiles = []
    for item in config.decode_profiles:
        fixtures_for_profile = [
            fixture
            for fixture in item.fixtures
            if fixture in allowed or fixture == "ycck_16x16"
        ]
        if quick and item.id not in {
            "baseline_rgb_420",
            "grayscale",
            "cmyk",
            "ycck",
        }:
            fixtures_for_profile = []
        if not fixtures_for_profile:
            continue
        decode_profiles.append(
            {
                "id": item.id,
                "kind": item.kind,
                "quality": item.quality,
                "subsampling": item.subsampling,
                "progressive": item.progressive,
                "restart_marker_blocks": item.restart_marker_blocks,
                "producers": list(item.producers),
                "fixtures": fixtures_for_profile,
                "paths": list(item.paths),
                "reference": item.reference,
            }
        )
    return {
        "quick": bool(quick),
        "fixtures": fixtures,
        "encode_profiles": encode_profiles,
        "decode_profiles": decode_profiles,
    }


def _worker_cells(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for profile in config["encode_profiles"]:
        for fixture in profile["fixtures"]:
            for path in profile["paths"]:
                cell_id = f"encode/{profile['id']}/{fixture}/{path}"
                cells.append(
                    {
                        "id": cell_id,
                        "operation": "encode",
                        "profile": profile["id"],
                        "producer": None,
                        "fixture": fixture,
                        "path": path,
                    }
                )
    for profile in config["decode_profiles"]:
        for producer in profile["producers"]:
            for fixture in profile["fixtures"]:
                for path in profile["paths"]:
                    cell_id = (
                        f"decode/{profile['id']}/{producer}/"
                        f"{fixture}/{path}"
                    )
                    cells.append(
                        {
                            "id": cell_id,
                            "operation": "decode",
                            "profile": profile["id"],
                            "producer": producer,
                            "fixture": fixture,
                            "path": path,
                        }
                    )
    ids = [cell["id"] for cell in cells]
    if len(ids) != len(set(ids)):
        raise RuntimeError("worker matrix contains duplicate cells")
    return cells


def _copy_worker(directory: Path) -> Path:
    destination = directory / "sceneio_backend_worker.py"
    shutil.copyfile(WORKER_SOURCE, destination)
    return destination


def _embed_corpus_manifest(
    response: Mapping[str, Any],
    *,
    config: QualificationConfig,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_path = _resolve_file(
        response["manifest_path"], "corpus manifest"
    )
    raw = manifest_path.read_bytes()
    if _sha256_bytes(raw) != response["manifest_sha256"]:
        raise ValueError("corpus manifest hash differs from worker response")
    manifest = json.loads(raw)
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("decision_id") != config.decision_id
        or manifest.get("source_commit") != source["commit"]
        or manifest.get("config_sha256") != config.sha256
    ):
        raise ValueError("corpus manifest identity is inconsistent")
    return {**response, "manifest": manifest}


def _run_worker(
    backend: BackendSpec,
    worker: Path,
    request: Mapping[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    started = time.perf_counter_ns()
    completed = subprocess.run(
        [str(backend.python), "-I", str(worker)],
        input=canonical_json_bytes(request).decode("utf-8"),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=timeout_seconds,
    )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{backend.id} worker returned invalid JSON: "
            f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
        ) from exc
    if (
        completed.returncode != 0
        or response.get("status") != "ok"
        or response.get("schema_version") != SCHEMA_VERSION
    ):
        raise RuntimeError(
            f"{backend.id} worker failed: returncode={completed.returncode}, "
            f"response={response!r}, stderr={completed.stderr!r}"
        )
    response["controller_wall_ns"] = (
        time.perf_counter_ns() - started
    )
    return response


def _readline_with_timeout(
    stream,
    *,
    timeout_seconds: float,
) -> str:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(stream.readline)
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError:
        raise TimeoutError("worker response timed out") from None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _memory_worker_process(
    psutil_module: Any,
    *,
    launcher_pid: int,
    worker_pid: Any,
) -> Any:
    if not _is_positive_int(worker_pid):
        raise RuntimeError("memory worker reported an invalid process ID")
    sampled = psutil_module.Process(worker_pid)
    if worker_pid != launcher_pid:
        try:
            ancestor_pids = {parent.pid for parent in sampled.parents()}
        except (
            psutil_module.NoSuchProcess,
            psutil_module.ZombieProcess,
        ) as exc:
            raise RuntimeError(
                "memory worker exited before process identity was verified"
            ) from exc
        if launcher_pid not in ancestor_pids:
            raise RuntimeError(
                "memory worker is not a child of the launched interpreter"
            )
    return sampled


def _terminate_memory_process_tree(
    psutil_module: Any,
    process: subprocess.Popen[str],
    *,
    sampled: Any | None,
) -> None:
    """Stop the launcher, its descendants, and the verified worker tree."""
    targets: dict[int, Any] = {}
    cleanup_errors: list[str] = []

    def add_tree(root: Any) -> None:
        try:
            descendants = root.children(recursive=True)
        except (
            psutil_module.NoSuchProcess,
            psutil_module.ZombieProcess,
        ):
            descendants = []
        except Exception as exc:
            cleanup_errors.append(
                f"could not inspect process {root.pid}: {exc}"
            )
            descendants = []
        for descendant in reversed(descendants):
            targets.setdefault(descendant.pid, descendant)
        targets.setdefault(root.pid, root)

    try:
        try:
            add_tree(psutil_module.Process(process.pid))
        except (
            psutil_module.NoSuchProcess,
            psutil_module.ZombieProcess,
        ):
            pass
        except Exception as exc:
            cleanup_errors.append(
                f"could not open launcher process {process.pid}: {exc}"
            )
        if sampled is not None:
            add_tree(sampled)

        candidates = list(targets.values())
        for candidate in candidates:
            try:
                candidate.terminate()
            except (
                psutil_module.NoSuchProcess,
                psutil_module.ZombieProcess,
            ):
                pass
            except Exception as exc:
                cleanup_errors.append(
                    f"could not terminate process {candidate.pid}: {exc}"
                )
        alive = []
        if candidates:
            try:
                _, alive = psutil_module.wait_procs(
                    candidates, timeout=5
                )
            except Exception as exc:
                cleanup_errors.append(
                    f"could not wait for terminated processes: {exc}"
                )
                alive = candidates
        for candidate in alive:
            try:
                candidate.kill()
            except (
                psutil_module.NoSuchProcess,
                psutil_module.ZombieProcess,
            ):
                pass
            except Exception as exc:
                cleanup_errors.append(
                    f"could not kill process {candidate.pid}: {exc}"
                )
        survivors = []
        if alive:
            try:
                _, survivors = psutil_module.wait_procs(alive, timeout=5)
            except Exception as exc:
                cleanup_errors.append(
                    f"could not wait for killed processes: {exc}"
                )
                survivors = alive
        if survivors:
            cleanup_errors.append(
                "processes remained after kill: "
                + ", ".join(str(item.pid) for item in survivors)
            )
    finally:
        try:
            if process.poll() is None:
                process.kill()
        except Exception as exc:
            cleanup_errors.append(
                f"could not kill launcher process {process.pid}: {exc}"
            )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cleanup_errors.append(
                f"launcher process {process.pid} did not exit after kill"
            )
        except Exception as exc:
            cleanup_errors.append(
                f"could not wait for launcher process {process.pid}: {exc}"
            )

    if cleanup_errors:
        raise RuntimeError("; ".join(cleanup_errors))


def _run_memory_worker(
    backend: BackendSpec,
    worker: Path,
    request: Mapping[str, Any],
    *,
    timeout_seconds: float,
    sampling_interval_seconds: float = _MEMORY_SAMPLING_INTERVAL_SECONDS,
) -> dict[str, Any]:
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError(
            "memory qualification requires psutil in the controller"
        ) from exc
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    process = subprocess.Popen(
        [str(backend.python), "-I", str(worker)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    sampled = None
    try:
        process.stdin.write(
            canonical_json_bytes(request).decode("utf-8")
        )
        process.stdin.flush()
        ready_line = _readline_with_timeout(
            process.stdout, timeout_seconds=timeout_seconds
        )
        ready = json.loads(ready_line)
        if (
            ready.get("status") != "ready"
            or ready.get("action") != "memory"
            or ready.get("schema_version") != SCHEMA_VERSION
        ):
            raise RuntimeError(
                f"{backend.id} memory worker did not become ready: {ready!r}"
            )
        worker_pid = ready.get("pid")
        sampled = _memory_worker_process(
            psutil,
            launcher_pid=process.pid,
            worker_pid=worker_pid,
        )
        baseline = max(
            int(sampled.memory_info().rss),
            int(ready["baseline_rss_bytes"]),
        )
        peak = [baseline]
        running = threading.Event()
        running.set()
        errors: list[Exception] = []

        def sample() -> None:
            try:
                while running.is_set():
                    peak[0] = max(
                        peak[0], int(sampled.memory_info().rss)
                    )
                    time.sleep(sampling_interval_seconds)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                pass
            except Exception as exc:
                errors.append(exc)

        sampler = threading.Thread(
            target=sample,
            name="sceneio-backend-memory-sampler",
            daemon=True,
        )
        sampler.start()
        process.stdin.write('{"command":"go"}\n')
        process.stdin.flush()
        final_line = _readline_with_timeout(
            process.stdout, timeout_seconds=timeout_seconds
        )
        running.clear()
        sampler.join(timeout=5)
        if sampler.is_alive():
            raise RuntimeError("memory sampler did not stop")
        if errors:
            raise RuntimeError(f"memory sampler failed: {errors[0]}")
        with contextlib.suppress(
            psutil.NoSuchProcess, psutil.ZombieProcess
        ):
            peak[0] = max(peak[0], int(sampled.memory_info().rss))
        final = json.loads(final_line)
        returncode = process.wait(timeout=5)
        stderr = process.stderr.read()
        if (
            returncode != 0
            or final.get("status") != "ok"
            or final.get("action") != "memory"
            or final.get("pid") != worker_pid
        ):
            raise RuntimeError(
                f"{backend.id} memory worker failed: "
                f"returncode={returncode}, response={final!r}, "
                f"stderr={stderr!r}"
            )
        rss = _rss_deltas(
            controller_baseline=baseline,
            controller_peak=peak[0],
            worker_baseline=final["worker_baseline_rss_bytes"],
            worker_after=final["worker_after_rss_bytes"],
        )
        final.update(rss)
        final["sampling_interval_seconds"] = sampling_interval_seconds
        return final
    except Exception as worker_error:
        try:
            _terminate_memory_process_tree(
                psutil,
                process,
                sampled=sampled,
            )
        except Exception as cleanup_error:
            worker_error.add_note(
                f"memory worker cleanup also failed: {cleanup_error}"
            )
        raise
    finally:
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


def _rss_deltas(
    *,
    controller_baseline: int,
    controller_peak: int,
    worker_baseline: int,
    worker_after: int,
) -> dict[str, int]:
    values = (
        controller_baseline,
        controller_peak,
        worker_baseline,
        worker_after,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in values
    ):
        raise ValueError("RSS measurements must be non-negative integers")
    controller_delta = max(0, controller_peak - controller_baseline)
    worker_delta = max(0, worker_after - worker_baseline)
    return {
        "controller_baseline_rss_bytes": controller_baseline,
        "controller_peak_rss_bytes": controller_peak,
        "controller_delta_rss_bytes": controller_delta,
        "worker_delta_rss_bytes": worker_delta,
        "effective_delta_rss_bytes": max(controller_delta, worker_delta),
    }


def _memory_measurement_consistent(item: Mapping[str, Any]) -> bool:
    try:
        expected = _rss_deltas(
            controller_baseline=item["controller_baseline_rss_bytes"],
            controller_peak=item["controller_peak_rss_bytes"],
            worker_baseline=item["worker_baseline_rss_bytes"],
            worker_after=item["worker_after_rss_bytes"],
        )
    except (KeyError, TypeError, ValueError):
        return False
    return (
        all(item.get(key) == value for key, value in expected.items())
        and item.get("sampling_interval_seconds")
        == _MEMORY_SAMPLING_INTERVAL_SECONDS
    )


def _inspect_wheel(backend: BackendSpec) -> dict[str, Any]:
    wheel_bytes = backend.wheel.read_bytes()
    with zipfile.ZipFile(backend.wheel) as archive:
        names = archive.namelist()
        native = [
            name
            for name in names
            if name.endswith((".pyd", ".so", ".dylib", ".dll"))
        ]
        if len(native) != 1 or "/_core." not in f"/{native[0]}":
            raise ValueError(
                f"{backend.id} wheel must contain exactly one _core module"
            )
        native_bytes = archive.read(native[0])
        package_member_names = [
            name
            for name in names
            if name.startswith("sceneio/")
            and not name.endswith("/")
            and name != native[0]
        ]
        if len(package_member_names) != len(set(package_member_names)):
            raise ValueError(
                f"{backend.id} wheel has duplicate package members"
            )
        package_members = {
            name: _sha256_bytes(archive.read(name))
            for name in sorted(package_member_names)
        }
        notices = [
            name
            for name in names
            if ".dist-info/licenses/" in name.lower()
        ]
        if len(notices) != 17:
            raise ValueError(
                f"{backend.id} wheel has {len(notices)} notices, expected 17"
            )
        forbidden = [
            name
            for name in names
            if name.lower().endswith(
                (
                    ".a",
                    ".lib",
                    ".h",
                    ".hpp",
                    ".cmake",
                    ".pc",
                    ".exe",
                )
            )
            or any(
                part in name.lower()
                for part in (
                    "tests/",
                    "bench/",
                    "docs/",
                    "src/cpp/",
                    ".github/",
                )
            )
        ]
        if forbidden:
            raise ValueError(
                f"{backend.id} wheel has development payload: {forbidden}"
            )
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError("wheel must contain exactly one METADATA file")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
        requirements = [
            line.removeprefix("Requires-Dist: ").strip()
            for line in metadata.splitlines()
            if line.startswith("Requires-Dist: ")
            and "extra ==" not in line
        ]
        if len(requirements) != 1 or not requirements[0].startswith("numpy"):
            raise ValueError(
                f"{backend.id} runtime requirements are {requirements!r}"
            )
    if "cp312-abi3" not in backend.wheel.name:
        raise ValueError(f"{backend.id} wheel is not cp312 abi3")
    return {
        "path": str(backend.wheel),
        "filename": backend.wheel.name,
        "sha256": _sha256_bytes(wheel_bytes),
        "bytes": len(wheel_bytes),
        "members": len(names),
        "notice_members": len(notices),
        "native_member": native[0],
        "native_sha256": _sha256_bytes(native_bytes),
        "native_bytes": len(native_bytes),
        "package_members_sha256": package_members,
        "runtime_requirements": requirements,
    }


def _load_cmake_manifest(
    backend: BackendSpec,
) -> dict[str, Any]:
    manifest = json.loads(backend.cmake_manifest.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != 1
        or manifest.get("qualification_build") is not True
        or manifest.get("jpeg_backend") != backend.id
        or manifest.get("internal_jpeg_default") != "stb"
    ):
        raise ValueError(
            f"{backend.id} CMake qualification manifest is inconsistent"
        )
    return manifest


def _load_simd_evidence(
    backend: BackendSpec,
) -> dict[str, Any] | None:
    if backend.simd_evidence is None:
        return None
    evidence = json.loads(
        backend.simd_evidence.read_text(encoding="utf-8")
    )
    architecture = evidence.get("simd_architecture")
    header_path = Path(evidence.get("generated_header", "")).resolve()
    header_architectures = []
    if header_path.is_file():
        for line in header_path.read_text(encoding="utf-8").splitlines():
            tokens = line.strip().split()
            if (
                len(tokens) == 3
                and tokens[:2] == ["#define", "SIMD_ARCHITECTURE"]
            ):
                header_architectures.append(tokens[2])
    if (
        evidence.get("schema_version") != 1
        or evidence.get("simd_required") is not True
        or not isinstance(architecture, str)
        or architecture not in {"X86_64", "ARM64"}
        or not header_path.is_file()
        or header_architectures != [architecture]
        or _sha256_file(header_path)
        != evidence.get("generated_header_sha256")
    ):
        raise ValueError(
            f"{backend.id} generated SIMD evidence is inconsistent"
        )
    return {
        **evidence,
        "evidence_path": str(backend.simd_evidence),
        "evidence_sha256": _sha256_file(backend.simd_evidence),
    }


def _validate_installed_wheel(
    backend_id: str,
    wheel: Mapping[str, Any],
    probe: Mapping[str, Any],
) -> None:
    if probe.get("core_sha256") != wheel.get("native_sha256"):
        raise ValueError(
            f"{backend_id} installed core differs from supplied wheel"
        )
    if probe.get("package_members_sha256") != wheel.get(
        "package_members_sha256"
    ):
        raise ValueError(
            f"{backend_id} installed Python package differs from supplied wheel"
        )


def _matching_environment_identity(
    environments: Mapping[str, Mapping[str, Any]],
) -> None:
    values = list(environments.items())
    if len(values) != 2:
        raise ValueError("qualification requires exactly two environments")
    retained_id, retained = values[0]
    candidate_id, candidate = values[1]
    fields = (
        "package_version",
        "numpy_version",
        "pillow_version",
    )
    platform_fields = (
        "system",
        "release",
        "machine",
        "python",
        "implementation",
    )
    mismatches = [
        field
        for field in fields
        if retained.get(field) != candidate.get(field)
    ]
    mismatches.extend(
        f"platform.{field}"
        for field in platform_fields
        if retained.get("platform", {}).get(field)
        != candidate.get("platform", {}).get(field)
    )
    if mismatches:
        raise ValueError(
            f"{retained_id} and {candidate_id} environments differ in: "
            + ", ".join(mismatches)
        )


def _normalized_machine(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_positive_int(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and value > 0
    )


def _validate_platform_report(
    report: Mapping[str, Any],
    config: QualificationConfig,
) -> None:
    profile = report.get("platform_profile")
    requirements = _PLATFORM_REQUIREMENTS.get(profile)
    if requirements is None:
        raise ValueError(f"unknown qualification platform {profile!r}")
    configuration = report.get("configuration", {})
    if (
        report.get("decision_id") != config.decision_id
        or report.get("codec_id") != config.codec_id
        or configuration.get("sha256") != config.sha256
        or configuration.get("methodology")
        != dataclasses.asdict(config.methodology)
        or configuration.get("thresholds") != dict(config.thresholds)
        or configuration.get("include_remote") is not True
        or configuration.get("quick") is not False
    ):
        raise ValueError(
            f"{profile} report does not use the full frozen configuration"
        )

    backend_ids = {config.retained_backend, config.candidate_backend}
    environments = report.get("environments", {})
    wheels = report.get("wheels", {})
    manifests = report.get("cmake_manifests", {})
    if (
        set(environments) != backend_ids
        or set(wheels) != backend_ids
        or set(manifests) != backend_ids
    ):
        raise ValueError(f"{profile} backend evidence is incomplete")

    markers = {
        config.retained_backend: config.retained_marker,
        config.candidate_backend: config.candidate_marker,
    }
    for backend_id in sorted(backend_ids):
        environment = environments[backend_id]
        wheel = wheels[backend_id]
        platform_evidence = environment.get("platform", {})
        package_members = environment.get("package_members_sha256")
        if (
            environment.get("schema_version") != SCHEMA_VERSION
            or environment.get("action") != "probe"
            or environment.get("status") != "ok"
            or environment.get("isolated") is not True
            or environment.get("marker") != markers[backend_id]
            or platform_evidence.get("system")
            != requirements["system"]
            or _normalized_machine(platform_evidence.get("machine"))
            not in requirements["machines"]
            or not isinstance(package_members, dict)
            or not package_members
            or package_members != wheel.get("package_members_sha256")
            or environment.get("core_sha256")
            != wheel.get("native_sha256")
            or not _is_sha256(wheel.get("sha256"))
        ):
            raise ValueError(
                f"{profile}/{backend_id} installed-wheel evidence "
                "is inconsistent"
            )

        manifest = manifests[backend_id]
        compiler = requirements["compiler"]
        if (
            manifest.get("schema_version") != 1
            or manifest.get("qualification_build") is not True
            or manifest.get("jpeg_backend") != backend_id
            or manifest.get("internal_jpeg_default")
            != config.retained_backend
            or manifest.get("system_name")
            != requirements["cmake_system"]
            or _normalized_machine(manifest.get("system_processor"))
            not in requirements["machines"]
            or manifest.get("c_compiler_id") != compiler
            or manifest.get("cxx_compiler_id") != compiler
        ):
            raise ValueError(
                f"{profile}/{backend_id} CMake evidence is inconsistent"
            )
        compiler_major = requirements["compiler_major"]
        if compiler_major is not None and (
            str(manifest.get("c_compiler_version", "")).split(".", 1)[0]
            != compiler_major
            or str(manifest.get("cxx_compiler_version", "")).split(
                ".", 1
            )[0]
            != compiler_major
        ):
            raise ValueError(
                f"{profile}/{backend_id} compiler version is inconsistent"
            )

    retained_manifest = manifests[config.retained_backend]
    candidate_manifest = manifests[config.candidate_backend]
    simd = report.get("simd_evidence", {})
    evidence = simd.get(config.candidate_backend, {})
    if (
        set(simd) != {config.candidate_backend}
        or retained_manifest.get("simd_required") is not False
        or candidate_manifest.get("simd_required") is not True
        or evidence.get("schema_version") != 1
        or evidence.get("simd_required") is not True
        or evidence.get("simd_architecture")
        != requirements["simd_architecture"]
        or not _is_sha256(evidence.get("generated_header_sha256"))
        or not _is_sha256(evidence.get("evidence_sha256"))
    ):
        raise ValueError(f"{profile} SIMD evidence is inconsistent")

    worker_config = _worker_config(
        config, include_remote=True, quick=False
    )
    expected_cells = _worker_cells(worker_config)
    expected_schedule = list(
        paired_schedule(
            retained=config.retained_backend,
            candidate=config.candidate_backend,
            sessions=config.methodology.remote_sessions,
            seed=config.methodology.order_seed,
        )
    )
    if report.get("schedule") != expected_schedule:
        raise ValueError(f"{profile} session schedule is inconsistent")
    aggregates, primary = _aggregate(
        config,
        report.get("raw_sessions", []),
        expected_cells=expected_cells,
        schedule=expected_schedule,
        worker_config=worker_config,
    )
    auxiliary = _validate_auxiliary(
        config,
        startup=report.get("startup", []),
        determinism=report.get("determinism", []),
        memory=report.get("memory", []),
        sessions=report.get("raw_sessions", []),
        wheels=wheels,
        quick=False,
    )
    validation = _merge_validation(primary, auxiliary)
    if (
        report.get("aggregates") != aggregates
        or report.get("validation") != validation
        or validation["status"] != "passed"
        or validation["passed"] is not True
        or not validation["gates"]
        or not all(gate["passed"] for gate in validation["gates"])
    ):
        raise ValueError(f"{profile} report validation is inconsistent")


def _preflight(
    backends: Sequence[BackendSpec],
    worker: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    environments: dict[str, Any] = {}
    wheels: dict[str, Any] = {}
    manifests: dict[str, Any] = {}
    simd_evidence: dict[str, Any] = {}
    for backend in backends:
        wheel = _inspect_wheel(backend)
        probe = _run_worker(
            backend,
            worker,
            {
                "schema_version": SCHEMA_VERSION,
                "action": "probe",
                "expected_marker": backend.expected_marker,
            },
            timeout_seconds=60,
        )
        if not probe["isolated"]:
            raise ValueError(f"{backend.id} worker did not run isolated")
        if Path(probe["python_executable"]) != backend.python:
            raise ValueError(
                f"{backend.id} resolved a different Python executable"
            )
        sceneio_path = Path(probe["sceneio_path"]).resolve()
        if sceneio_path.is_relative_to((ROOT / "src" / "sceneio").resolve()):
            raise ValueError(
                f"{backend.id} imported SceneIO from the checkout"
            )
        _validate_installed_wheel(backend.id, wheel, probe)
        if probe["marker"] != backend.expected_marker:
            raise ValueError(f"{backend.id} marker differs from request")
        forbidden_dispatch = {
            key: value
            for key, value in probe["dispatch_environment"].items()
            if key.startswith(("JSIMD_", "TJ"))
        }
        if forbidden_dispatch:
            raise ValueError(
                f"{backend.id} has forced JPEG dispatch settings: "
                f"{forbidden_dispatch}"
            )
        environments[backend.id] = probe
        wheels[backend.id] = wheel
        manifests[backend.id] = _load_cmake_manifest(backend)
        evidence = _load_simd_evidence(backend)
        if evidence is not None:
            simd_evidence[backend.id] = evidence
    core_paths = {
        Path(value["core_path"]).resolve()
        for value in environments.values()
    }
    if len(core_paths) != len(backends):
        raise ValueError("backend environments reuse one native module")
    _matching_environment_identity(environments)
    identity_fields = (
        "generator",
        "generator_platform",
        "generator_toolset",
        "cmake_version",
        "multi_config",
        "outer_configuration",
        "system_name",
        "system_processor",
        "c_compiler_id",
        "c_compiler_version",
        "cxx_compiler_id",
        "cxx_compiler_version",
        "outer_msvc_runtime",
    )
    retained = manifests[backends[0].id]
    candidate = manifests[backends[1].id]
    mismatches = [
        field
        for field in identity_fields
        if retained.get(field) != candidate.get(field)
    ]
    if mismatches:
        raise ValueError(
            "paired build manifests differ in toolchain fields: "
            + ", ".join(mismatches)
        )
    return environments, wheels, manifests, simd_evidence


def _session_medians(
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, list[int]]]:
    by_backend: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    seen: set[tuple[int, str]] = set()
    for session in sessions:
        identity = (session["round"], session["backend"])
        if identity in seen:
            raise ValueError(f"duplicate session {identity!r}")
        seen.add(identity)
        for result in session["results"]:
            samples = [
                item["per_operation_ns"] for item in result["samples"]
            ]
            summary = median_mad_ns(samples)
            by_backend[session["backend"]][result["cell"]].append(
                summary["median_ns"]
            )
    return {
        backend: dict(cells) for backend, cells in by_backend.items()
    }


def _validate_session_completeness(
    config: QualificationConfig,
    sessions: Sequence[Mapping[str, Any]],
    *,
    expected_cells: Sequence[Mapping[str, Any]],
    schedule: Sequence[Mapping[str, Any]],
    worker_config: Mapping[str, Any],
) -> None:
    expected_execution = [
        (round_spec["round"], backend)
        for round_spec in schedule
        for backend in round_spec["order"]
    ]
    observed_execution = [
        (session.get("round"), session.get("backend"))
        for session in sessions
    ]
    if observed_execution != expected_execution:
        raise ValueError(
            "session execution differs from the declared schedule"
        )
    pids = [session.get("pid") for session in sessions]
    if (
        any(
            isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
            for pid in pids
        )
        or len(set(pids)) != len(pids)
    ):
        raise ValueError("each session must use one fresh worker process")

    fixture_measurements = {
        fixture["id"]: (
            fixture["class"],
            fixture["samples"],
            fixture["iterations_per_sample"],
        )
        for fixture in worker_config["fixtures"]
    }
    fixture_measurements["ycck_16x16"] = (
        "small",
        1 if worker_config["quick"] else 15,
        1 if worker_config["quick"] else 32,
    )
    cells_by_id = {cell["id"]: cell for cell in expected_cells}
    if len(cells_by_id) != len(expected_cells):
        raise ValueError("expected worker cells are not unique")
    schedule_by_round = {
        round_spec["round"]: round_spec for round_spec in schedule
    }
    markers = {
        config.retained_backend: config.retained_marker,
        config.candidate_backend: config.candidate_marker,
    }
    for session in sessions:
        round_spec = schedule_by_round[session["round"]]
        ordered = list(expected_cells)
        random.Random(round_spec["seed"]).shuffle(ordered)
        expected_order = [cell["id"] for cell in ordered]
        result_order = [
            result.get("cell") for result in session.get("results", [])
        ]
        if (
            session.get("schema_version") != SCHEMA_VERSION
            or session.get("action") != "session"
            or session.get("status") != "ok"
            or session.get("marker") != markers[session["backend"]]
            or session.get("cell_order") != expected_order
            or result_order != expected_order
        ):
            raise ValueError(
                f"session {session['round']}/{session['backend']} "
                "does not contain the exact requested cells"
            )
        for result in session["results"]:
            cell = cells_by_id[result["cell"]]
            fixture_class, sample_count, iterations = (
                fixture_measurements[cell["fixture"]]
            )
            if (
                result.get("operation") != cell["operation"]
                or result.get("profile") != cell["profile"]
                or result.get("producer") != cell["producer"]
                or result.get("fixture") != cell["fixture"]
                or result.get("fixture_class") != fixture_class
                or result.get("path") != cell["path"]
                or len(result.get("samples", [])) != sample_count
            ):
                raise ValueError(
                    f"session result shape differs for {cell['id']}"
                )
            for sample in result["samples"]:
                total = sample.get("total_ns")
                if (
                    isinstance(total, bool)
                    or not isinstance(total, int)
                    or total <= 0
                    or sample.get("iterations") != iterations
                    or sample.get("per_operation_ns")
                    != max(1, round(total / iterations))
                ):
                    raise ValueError(
                        f"invalid raw timing sample for {cell['id']}"
                    )


def _aggregate(
    config: QualificationConfig,
    sessions: Sequence[Mapping[str, Any]],
    *,
    expected_cells: Sequence[Mapping[str, Any]],
    schedule: Sequence[Mapping[str, Any]],
    worker_config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _validate_session_completeness(
        config,
        sessions,
        expected_cells=expected_cells,
        schedule=schedule,
        worker_config=worker_config,
    )
    medians = _session_medians(sessions)
    retained_cells = medians[config.retained_backend]
    candidate_cells = medians[config.candidate_backend]
    if set(retained_cells) != set(candidate_cells):
        raise ValueError("paired backends measured different cells")
    aggregates = []
    for cell in sorted(retained_cells):
        retained = retained_cells[cell]
        candidate = candidate_cells[cell]
        ratio = paired_ratio_summary(retained, candidate)
        aggregates.append(
            {
                "cell": cell,
                "retained_session_median_ns": retained,
                "candidate_session_median_ns": candidate,
                **ratio,
            }
        )
    return aggregates, _validate_results(config, sessions, aggregates)


def _measure_startup(
    config: QualificationConfig,
    backends: Sequence[BackendSpec],
    worker: Path,
    worker_config: Mapping[str, Any],
    corpus: Mapping[str, Any],
    *,
    quick: bool,
) -> list[dict[str, Any]]:
    by_id = {backend.id: backend for backend in backends}
    count = 2 if quick else config.methodology.startup_processes
    schedule = paired_schedule(
        retained=config.retained_backend,
        candidate=config.candidate_backend,
        sessions=count,
        seed=config.methodology.order_seed + 10_000,
    )
    fixture = (
        "small_odd"
        if quick
        else next(
            item["id"]
            for item in worker_config["fixtures"]
            if item["id"] == "photo_fhd"
        )
    )
    results = []
    for round_spec in schedule:
        for backend_id in round_spec["order"]:
            backend = by_id[backend_id]
            operations = (
                ("encode", "decode")
                if round_spec["round"] % 2 == 0
                else ("decode", "encode")
            )
            for operation in operations:
                response = _run_worker(
                    backend,
                    worker,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "action": "startup",
                        "expected_marker": backend.expected_marker,
                        "corpus_manifest_path": corpus["manifest_path"],
                        "corpus_manifest_sha256": corpus[
                            "manifest_sha256"
                        ],
                        "fixture": fixture,
                        "operation": operation,
                    },
                    timeout_seconds=300,
                )
                response.update(
                    {
                        "backend": backend_id,
                        "round": round_spec["round"],
                    }
                )
                results.append(response)
    return results


def _measure_determinism(
    config: QualificationConfig,
    backends: Sequence[BackendSpec],
    worker: Path,
    worker_config: Mapping[str, Any],
    corpus: Mapping[str, Any],
    *,
    work_dir: Path,
    quick: bool,
) -> list[dict[str, Any]]:
    by_id = {backend.id: backend for backend in backends}
    processes = (
        1
        if quick
        else int(config.thresholds["determinism_processes"])
    )
    repeats = (
        2
        if quick
        else int(config.thresholds["determinism_repeats"])
    )
    results = []
    for process_index in range(processes):
        order = (
            [config.retained_backend, config.candidate_backend]
            if process_index % 2 == 0
            else [config.candidate_backend, config.retained_backend]
        )
        for backend_id in order:
            backend = by_id[backend_id]
            response = _run_worker(
                backend,
                worker,
                {
                    "schema_version": SCHEMA_VERSION,
                    "action": "determinism",
                    "expected_marker": backend.expected_marker,
                    "config": worker_config,
                    "corpus_manifest_path": corpus["manifest_path"],
                    "corpus_manifest_sha256": corpus["manifest_sha256"],
                    "fixture": "small_odd",
                    "repeats": repeats,
                    "output_dir": str(
                        work_dir
                        / "determinism"
                        / f"{process_index}-{backend_id}"
                    ),
                },
                timeout_seconds=600,
            )
            response.update(
                {
                    "backend": backend_id,
                    "process_index": process_index,
                }
            )
            results.append(response)
    return results


def _measure_memory(
    config: QualificationConfig,
    backends: Sequence[BackendSpec],
    worker: Path,
    worker_config: Mapping[str, Any],
    corpus: Mapping[str, Any],
    *,
    work_dir: Path,
    quick: bool,
) -> list[dict[str, Any]]:
    if quick:
        return []
    by_id = {backend.id: backend for backend in backends}
    results = []
    for case in config.memory_cases:
        case_payload = {
            "id": case.id,
            "operation": case.operation,
            "path": case.path,
            "profile": case.profile,
            "fixture": case.fixture,
            "producer": case.producer,
        }
        for sample_index in range(config.methodology.memory_samples):
            order = (
                [config.retained_backend, config.candidate_backend]
                if sample_index % 2 == 0
                else [config.candidate_backend, config.retained_backend]
            )
            for backend_id in order:
                backend = by_id[backend_id]
                response = _run_memory_worker(
                    backend,
                    worker,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "action": "memory",
                        "expected_marker": backend.expected_marker,
                        "config": worker_config,
                        "corpus_manifest_path": corpus["manifest_path"],
                        "corpus_manifest_sha256": corpus[
                            "manifest_sha256"
                        ],
                        "case": case_payload,
                        "output_dir": str(
                            work_dir
                            / "memory"
                            / case.id
                            / f"{sample_index}-{backend_id}"
                        ),
                    },
                    timeout_seconds=600,
                )
                response.update(
                    {
                        "backend": backend_id,
                        "sample_index": sample_index,
                    }
                )
                results.append(response)
    return results


def _validate_auxiliary(
    config: QualificationConfig,
    *,
    startup: Sequence[Mapping[str, Any]],
    determinism: Sequence[Mapping[str, Any]],
    memory: Sequence[Mapping[str, Any]],
    sessions: Sequence[Mapping[str, Any]],
    wheels: Mapping[str, Mapping[str, Any]],
    quick: bool,
) -> dict[str, Any]:
    thresholds = config.thresholds
    gates: list[dict[str, Any]] = []

    def gate(name: str, passed: bool, **evidence: Any) -> None:
        gates.append({"name": name, "passed": bool(passed), **evidence})

    if quick:
        return {"status": "smoke_only", "passed": True, "gates": gates}

    backend_ids = (
        config.retained_backend,
        config.candidate_backend,
    )
    startup_by_backend = {
        backend: [item for item in startup if item["backend"] == backend]
        for backend in backend_ids
    }
    startup_by_backend_operation = {
        (backend, operation): [
            item
            for item in startup_by_backend[backend]
            if item.get("operation") == operation
        ]
        for backend in backend_ids
        for operation in ("encode", "decode")
    }
    startup_schedule = paired_schedule(
        retained=config.retained_backend,
        candidate=config.candidate_backend,
        sessions=config.methodology.startup_processes,
        seed=config.methodology.order_seed + 10_000,
    )
    expected_startup_execution = [
        (round_spec["round"], backend, operation)
        for round_spec in startup_schedule
        for backend in round_spec["order"]
        for operation in (
            ("encode", "decode")
            if round_spec["round"] % 2 == 0
            else ("decode", "encode")
        )
    ]
    observed_startup_execution = [
        (
            item.get("round"),
            item.get("backend"),
            item.get("operation"),
        )
        for item in startup
    ]
    startup_complete = (
        len(startup)
        == config.methodology.startup_processes * len(backend_ids) * 2
        and all(item.get("backend") in backend_ids for item in startup)
        and observed_startup_execution == expected_startup_execution
    )
    gate(
        "startup-observation-set",
        startup_complete,
        observations=len(startup),
        required=(
            config.methodology.startup_processes
            * len(backend_ids)
            * 2
        ),
    )
    all_startup_pids: set[int] = set()
    for backend in backend_ids:
        values = startup_by_backend[backend]
        pids = [item["pid"] for item in values]
        expected_rounds = set(
            range(config.methodology.startup_processes)
        )
        complete = (
            len(values) == config.methodology.startup_processes * 2
            and len(set(pids)) == len(values)
            and not all_startup_pids.intersection(pids)
            and all(_is_positive_int(pid) for pid in pids)
            and all(
                item.get("schema_version") == SCHEMA_VERSION
                and item.get("action") == "startup"
                and item.get("status") == "ok"
                and item.get("marker")
                == (
                    config.retained_marker
                    if backend == config.retained_backend
                    else config.candidate_marker
                )
                and item.get("fixture") == "photo_fhd"
                and _is_positive_int(item.get("import_ns"))
                and _is_positive_int(item.get("first_call_ns"))
                and _is_sha256(item.get("encoded_sha256"))
                and _is_sha256(item.get("output_sha256"))
                for item in values
            )
        )
        all_startup_pids.update(pids)
        startup_complete = startup_complete and complete
        gate(
            f"startup-completeness:{backend}",
            complete,
            observations=len(values),
            unique_processes=len(set(pids)),
            required=config.methodology.startup_processes * 2,
        )
        for operation in ("encode", "decode"):
            operation_values = startup_by_backend_operation[
                (backend, operation)
            ]
            operation_complete = (
                len(operation_values)
                == config.methodology.startup_processes
                and {item.get("round") for item in operation_values}
                == expected_rounds
            )
            startup_complete = startup_complete and operation_complete
            gate(
                f"startup-completeness:{backend}:{operation}",
                operation_complete,
                observations=len(operation_values),
                required=config.methodology.startup_processes,
            )
    startup_inputs = {
        item.get("encoded_sha256") for item in startup
    }
    gate(
        "startup-input-identity",
        len(startup_inputs) == 1
        and all(_is_sha256(item) for item in startup_inputs),
        hashes=sorted(
            item for item in startup_inputs if isinstance(item, str)
        ),
    )
    for backend in backend_ids:
        for operation in ("encode", "decode"):
            hashes = {
                item.get("output_sha256")
                for item in startup_by_backend_operation[
                    (backend, operation)
                ]
            }
            gate(
                f"startup-output-identity:{backend}:{operation}",
                len(hashes) == 1
                and all(_is_sha256(item) for item in hashes),
                hashes=sorted(
                    item for item in hashes if isinstance(item, str)
                ),
            )
    startup_metrics = (
        (
            "import",
            "import_ns",
            "import_ratio_max",
            "import_allowance_ns",
            startup_by_backend,
        ),
        (
            "first_encode",
            "first_call_ns",
            "first_call_ratio_max",
            "first_call_allowance_ns",
            {
                backend: startup_by_backend_operation[(backend, "encode")]
                for backend in backend_ids
            },
        ),
        (
            "first_decode",
            "first_call_ns",
            "first_call_ratio_max",
            "first_call_allowance_ns",
            {
                backend: startup_by_backend_operation[(backend, "decode")]
                for backend in backend_ids
            },
        ),
    )
    for name, metric, ratio_key, allowance_key, values_by_backend in (
        startup_metrics
    ):
        if not startup_complete:
            continue
        retained_value = statistics.median(
            item[metric]
            for item in values_by_backend[config.retained_backend]
        )
        candidate_value = statistics.median(
            item[metric]
            for item in values_by_backend[config.candidate_backend]
        )
        maximum = max(
            retained_value * thresholds[ratio_key],
            retained_value + thresholds[allowance_key],
        )
        gate(
            f"startup:{name}",
            candidate_value <= maximum,
            retained_median_ns=retained_value,
            candidate_median_ns=candidate_value,
            maximum_ns=maximum,
        )

    expected_processes = int(
        thresholds["determinism_processes"]
    )
    expected_repeats = int(thresholds["determinism_repeats"])
    expected_encoders = {
        profile.id for profile in config.encode_profiles
    }
    expected_encoder_quality = {
        profile.id: profile.quality for profile in config.encode_profiles
    }
    expected_decoders = {
        f"{profile.id}--{producer}--{fixture}"
        for profile in config.decode_profiles
        for producer in profile.producers
        for fixture in profile.fixtures
        if fixture in {"small_odd", "ycck_16x16"}
    }
    expected_plateau = {
        "encode_q95_core_buffer",
        "decode_420_core_bytes",
    }
    determinism_observation_set = (
        len(determinism) == expected_processes * len(backend_ids)
        and all(
            item.get("backend") in backend_ids for item in determinism
        )
        and [
            (item.get("process_index"), item.get("backend"))
            for item in determinism
        ]
        == [
            (process_index, backend)
            for process_index in range(expected_processes)
            for backend in (
                backend_ids
                if process_index % 2 == 0
                else tuple(reversed(backend_ids))
            )
        ]
    )
    gate(
        "determinism-observation-set",
        determinism_observation_set,
        observations=len(determinism),
        required=expected_processes * len(backend_ids),
    )
    all_determinism_pids: set[int] = set()
    for backend in (config.retained_backend, config.candidate_backend):
        values = [
            item for item in determinism if item["backend"] == backend
        ]
        encoder_by_profile: dict[str, set[str]] = defaultdict(set)
        decoder_by_fixture: dict[str, set[str]] = defaultdict(set)
        decoder_inputs_by_fixture: dict[str, set[str]] = defaultdict(set)
        pids = set()
        for value in values:
            pids.add(value["pid"])
            protocol_valid = (
                value.get("schema_version") == SCHEMA_VERSION
                and value.get("action") == "determinism"
                and value.get("status") == "ok"
                and value.get("marker")
                == (
                    config.retained_marker
                    if backend == config.retained_backend
                    else config.candidate_marker
                )
                and value.get("fixture") == "small_odd"
            )
            encoder_ids = {
                encoder["profile"] for encoder in value["encoders"]
            }
            decoder_ids = {
                decoder["fixture"] for decoder in value["decoders"]
            }
            gate(
                f"determinism-shape:{backend}:"
                f"{value['process_index']}",
                value["repeats"] == expected_repeats
                and protocol_valid
                and len(value["encoders"]) == len(expected_encoders)
                and len(value["decoders"]) == len(expected_decoders)
                and encoder_ids == expected_encoders
                and all(
                    encoder.get("quality")
                    == expected_encoder_quality.get(
                        encoder.get("profile")
                    )
                    for encoder in value["encoders"]
                )
                and decoder_ids == expected_decoders
                and set(value["rss_plateau"]) == expected_plateau,
                repeats=value["repeats"],
                encoder_profiles=sorted(encoder_ids),
                decoder_fixtures=sorted(decoder_ids),
                plateau_operations=sorted(value["rss_plateau"]),
            )
            for encoder in value["encoders"]:
                raw_hashes = encoder["hashes"]
                hashes = set(raw_hashes)
                gate(
                    f"determinism:{backend}:{value['process_index']}:"
                    f"{encoder['profile']}",
                    len(raw_hashes) == expected_repeats
                    and len(hashes) == 1
                    and all(_is_sha256(item) for item in raw_hashes),
                    observations=len(raw_hashes),
                    required=expected_repeats,
                    hashes=sorted(hashes),
                )
                encoder_by_profile[encoder["profile"]].update(hashes)
                if encoder["quality"] == 95:
                    gate(
                        f"sink-identity:{backend}:"
                        f"{value['process_index']}",
                        encoder["buffer_sha256"]
                        == encoder["core_sink_sha256"]
                        == encoder["public_sink_sha256"]
                        and _is_sha256(encoder["buffer_sha256"]),
                    )
            for decoder in value["decoders"]:
                raw_hashes = decoder["pixel_hashes"]
                hashes = set(raw_hashes)
                gate(
                    f"decode-repeat:{backend}:"
                    f"{value['process_index']}:{decoder['fixture']}",
                    len(raw_hashes) == expected_repeats
                    and len(hashes) == 1
                    and all(_is_sha256(item) for item in raw_hashes),
                    observations=len(raw_hashes),
                    required=expected_repeats,
                )
                decoder_by_fixture[decoder["fixture"]].update(hashes)
                decoder_inputs_by_fixture[decoder["fixture"]].add(
                    decoder.get("encoded_sha256")
                )
            for operation, rss in value["rss_plateau"].items():
                gate(
                    f"rss-samples:{backend}:"
                    f"{value['process_index']}:{operation}",
                    len(rss) == 50
                    and all(
                        not isinstance(item, bool)
                        and isinstance(item, int)
                        and item >= 0
                        for item in rss
                    ),
                    observed=len(rss),
                    required=50,
                )
                if len(rss) < 10:
                    continue
                growth = statistics.median(rss[-10:]) - statistics.median(
                    rss[:10]
                )
                gate(
                    f"rss-plateau:{backend}:{value['process_index']}:"
                    f"{operation}",
                    growth
                    <= thresholds["memory_plateau_allowance_bytes"],
                    growth_bytes=growth,
                    maximum_bytes=thresholds[
                        "memory_plateau_allowance_bytes"
                    ],
                )
        gate(
            f"fresh-processes:{backend}",
            len(values) == expected_processes
            and len(pids) == expected_processes
            and all(_is_positive_int(pid) for pid in pids)
            and not all_determinism_pids.intersection(pids)
            and {item["process_index"] for item in values}
            == set(range(expected_processes)),
            pids=sorted(pids),
            process_indices=sorted(
                item["process_index"] for item in values
            ),
        )
        all_determinism_pids.update(pids)
        for profile, hashes in encoder_by_profile.items():
            gate(
                f"cross-process-encode:{backend}:{profile}",
                len(hashes) == 1,
                hashes=sorted(hashes),
            )
        for fixture, hashes in decoder_by_fixture.items():
            gate(
                f"cross-process-decode:{backend}:{fixture}",
                len(hashes) == 1,
            )
        for fixture, hashes in decoder_inputs_by_fixture.items():
            gate(
                f"cross-process-decode-input:{backend}:{fixture}",
                len(hashes) == 1
                and all(_is_sha256(item) for item in hashes),
                hashes=sorted(
                    item for item in hashes if isinstance(item, str)
                ),
            )

    expected_memory_execution = [
        (case.id, sample_index, backend)
        for case in config.memory_cases
        for sample_index in range(config.methodology.memory_samples)
        for backend in (
            backend_ids
            if sample_index % 2 == 0
            else tuple(reversed(backend_ids))
        )
    ]
    observed_memory_execution = [
        (
            item.get("case"),
            item.get("sample_index"),
            item.get("backend"),
        )
        for item in memory
    ]
    gate(
        "memory-observation-set",
        observed_memory_execution == expected_memory_execution,
        observations=len(memory),
        required=len(expected_memory_execution),
    )
    memory_pids = [item.get("pid") for item in memory]
    gate(
        "memory-fresh-processes",
        len(memory)
        == len(config.memory_cases)
        * config.methodology.memory_samples
        * 2
        and all(_is_positive_int(pid) for pid in memory_pids)
        and len(set(memory_pids)) == len(memory_pids),
        observations=len(memory),
        unique_processes=len(set(memory_pids)),
    )
    for case in config.memory_cases:
        values = {
            backend: [
                item
                for item in memory
                if item.get("backend") == backend
                and item.get("case") == case.id
            ]
            for backend in (
                config.retained_backend,
                config.candidate_backend,
            )
        }
        complete = all(
            len(items) == config.methodology.memory_samples
            and {item.get("sample_index") for item in items}
            == set(range(config.methodology.memory_samples))
            and all(
                item.get("schema_version") == SCHEMA_VERSION
                and item.get("action") == "memory"
                and item.get("status") == "ok"
                and item.get("marker")
                == (
                    config.retained_marker
                    if backend == config.retained_backend
                    else config.candidate_marker
                )
                and item.get("operation") == case.operation
                and item.get("profile") == case.profile
                and item.get("producer") == case.producer
                and item.get("fixture") == case.fixture
                and item.get("path") == case.path
                and _is_positive_int(item.get("duration_ns"))
                and _memory_measurement_consistent(item)
                for item in items
            )
            for backend, items in values.items()
        )
        gate(
            f"memory-completeness:{case.id}",
            complete,
            observations={
                backend: len(items) for backend, items in values.items()
            },
            required=config.methodology.memory_samples,
        )
        if not complete:
            continue
        deltas = {
            backend: [
                item["effective_delta_rss_bytes"] for item in items
            ]
            for backend, items in values.items()
        }
        retained_value = statistics.median(
            deltas[config.retained_backend]
        )
        candidate_value = statistics.median(
            deltas[config.candidate_backend]
        )
        fixture = config.fixture(case.fixture)
        if fixture.fixture_class == "generated_large":
            ratio = thresholds["memory_large_ratio_max"]
            allowance = thresholds["memory_large_allowance_bytes"]
        else:
            ratio = thresholds["memory_representative_ratio_max"]
            allowance = thresholds[
                "memory_representative_allowance_bytes"
            ]
        maximum = max(retained_value * ratio, retained_value + allowance)
        gate(
            f"fresh-rss:{case.id}",
            candidate_value <= maximum,
            retained_median_bytes=retained_value,
            candidate_median_bytes=candidate_value,
            maximum_bytes=maximum,
        )

    result_by_backend_cell: dict[
        tuple[str, str], list[Mapping[str, Any]]
    ] = defaultdict(list)
    for session in sessions:
        for result in session["results"]:
            result_by_backend_cell[
                (session["backend"], result["cell"])
            ].append(result)
            if result["path"] in {"core_sink", "public_sink"}:
                maximum = max(
                    thresholds["traced_sink_min_allowance_bytes"],
                    result["encoded_bytes"]
                    * thresholds[
                        "traced_sink_output_fraction_max"
                    ],
                )
                gate(
                    f"traced-sink:{session['backend']}:{result['cell']}:"
                    f"{session['round']}",
                    result["traced_peak_bytes"] < maximum,
                    observed_bytes=result["traced_peak_bytes"],
                    maximum_bytes=maximum,
                )
            elif result["path"] == "core_mmap":
                maximum = max(
                    thresholds["traced_mmap_min_allowance_bytes"],
                    result["encoded_bytes"]
                    * thresholds[
                        "traced_mmap_file_fraction_max"
                    ],
                )
                gate(
                    f"traced-mmap:{session['backend']}:{result['cell']}:"
                    f"{session['round']}",
                    result["traced_peak_bytes"] < maximum,
                    observed_bytes=result["traced_peak_bytes"],
                    maximum_bytes=maximum,
                )
    cell_ids = {
        cell
        for _, cell in result_by_backend_cell
    }
    for cell in cell_ids:
        retained_values = result_by_backend_cell[
            (config.retained_backend, cell)
        ]
        candidate_values = result_by_backend_cell[
            (config.candidate_backend, cell)
        ]
        retained_peak = statistics.median(
            item["traced_peak_bytes"] for item in retained_values
        )
        candidate_peak = statistics.median(
            item["traced_peak_bytes"] for item in candidate_values
        )
        gate(
            f"traced-relative:{cell}",
            candidate_peak
            <= retained_peak
            + thresholds["traced_candidate_extra_bytes_max"],
            retained_median_bytes=retained_peak,
            candidate_median_bytes=candidate_peak,
        )

    retained_wheel = wheels[config.retained_backend]
    candidate_wheel = wheels[config.candidate_backend]
    gate(
        "wheel-size",
        candidate_wheel["bytes"]
        <= retained_wheel["bytes"] * thresholds["wheel_ratio_max"]
        and candidate_wheel["bytes"] - retained_wheel["bytes"]
        <= thresholds["wheel_extra_bytes_max"],
    )
    gate(
        "native-size",
        candidate_wheel["native_bytes"]
        <= retained_wheel["native_bytes"] * thresholds["native_ratio_max"]
        and candidate_wheel["native_bytes"]
        - retained_wheel["native_bytes"]
        <= thresholds["native_extra_bytes_max"],
    )
    return {
        "status": (
            "passed" if all(item["passed"] for item in gates) else "failed"
        ),
        "passed": all(item["passed"] for item in gates),
        "gates": gates,
    }


def _merge_validation(
    primary: Mapping[str, Any],
    auxiliary: Mapping[str, Any],
) -> dict[str, Any]:
    gates = [*primary["gates"], *auxiliary["gates"]]
    passed = bool(primary["passed"] and auxiliary["passed"])
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "gates": gates,
    }


def _unique_result(
    sessions: Sequence[Mapping[str, Any]],
    backend: str,
    cell: str,
) -> list[Mapping[str, Any]]:
    return [
        result
        for session in sessions
        if session["backend"] == backend
        for result in session["results"]
        if result["cell"] == cell
    ]


def _geomean(values: Iterable[float]) -> float:
    items = list(values)
    if not items or any(value <= 0 for value in items):
        raise ValueError("geometric mean requires positive values")
    return math.exp(statistics.fmean(math.log(value) for value in items))


def _validate_results(
    config: QualificationConfig,
    sessions: Sequence[Mapping[str, Any]],
    aggregates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    thresholds = config.thresholds
    gates: list[dict[str, Any]] = []

    def gate(name: str, passed: bool, **evidence: Any) -> None:
        gates.append({"name": name, "passed": bool(passed), **evidence})

    aggregate_by_cell = {item["cell"]: item for item in aggregates}
    fixture_class = {
        fixture.id: fixture.fixture_class for fixture in config.fixtures
    }
    fixture_class["ycck_16x16"] = "small"
    for aggregate in aggregates:
        parts = aggregate["cell"].split("/")
        operation = parts[0]
        if operation == "decode":
            profile = parts[1]
            fixture = parts[3]
            if profile in {"cmyk", "ycck"}:
                continue
        else:
            fixture = parts[2]
        maximum_noise = (
            thresholds["normalized_mad_small_max"]
            if fixture_class[fixture] == "small"
            else thresholds["normalized_mad_other_max"]
        )
        observed_noise = aggregate["scaled_log_mad_ppm"] / _PPM
        gate(
            f"measurement-noise:{aggregate['cell']}",
            observed_noise <= maximum_noise,
            observed=observed_noise,
            maximum=maximum_noise,
        )
        minimum = (
            thresholds["small_cell_robust_ratio_min"]
            if fixture_class[fixture] == "small"
            else thresholds["representative_cell_robust_ratio_min"]
        )
        observed = aggregate["robust_lower_ratio_ppm"] / _PPM
        gate(
            f"performance-cell:{aggregate['cell']}",
            observed >= minimum,
            observed=observed,
            required=minimum,
        )

    for profile in config.encode_profiles:
        psnr_deltas = []
        size_ratios = []
        for fixture in profile.fixtures:
            cell = f"encode/{profile.id}/{fixture}/core_buffer"
            if cell not in aggregate_by_cell:
                continue
            retained = _unique_result(
                sessions, config.retained_backend, cell
            )
            candidate = _unique_result(
                sessions, config.candidate_backend, cell
            )
            retained_hashes = {item["encoded_sha256"] for item in retained}
            candidate_hashes = {
                item["encoded_sha256"] for item in candidate
            }
            gate(
                f"deterministic:{config.retained_backend}:{profile.id}:{fixture}",
                len(retained_hashes) == 1,
                hashes=sorted(retained_hashes),
            )
            gate(
                f"deterministic:{config.candidate_backend}:{profile.id}:{fixture}",
                len(candidate_hashes) == 1,
                hashes=sorted(candidate_hashes),
            )
            retained_psnr = statistics.median(
                item["psnr_db"] for item in retained
            )
            candidate_psnr = statistics.median(
                item["psnr_db"] for item in candidate
            )
            delta = candidate_psnr - retained_psnr
            ratio = statistics.median(
                item["encoded_bytes"] for item in candidate
            ) / statistics.median(
                item["encoded_bytes"] for item in retained
            )
            psnr_deltas.append(delta)
            size_ratios.append(ratio)
            gate(
                f"quality:{profile.id}:{fixture}",
                delta
                >= thresholds[
                    "encode_psnr_per_fixture_delta_min_db"
                ],
                delta_db=delta,
                required_delta_db=thresholds[
                    "encode_psnr_per_fixture_delta_min_db"
                ],
            )
            gate(
                f"encoded-size:{profile.id}:{fixture}",
                ratio
                <= thresholds["encoded_size_per_fixture_ratio_max"],
                ratio=ratio,
                maximum=thresholds[
                    "encoded_size_per_fixture_ratio_max"
                ],
            )
        if psnr_deltas:
            gate(
                f"quality-profile:{profile.id}",
                statistics.median(psnr_deltas)
                >= thresholds["encode_psnr_profile_median_delta_min_db"],
                median_delta_db=statistics.median(psnr_deltas),
                required_delta_db=thresholds[
                    "encode_psnr_profile_median_delta_min_db"
                ],
            )
            gate(
                f"encoded-size-profile:{profile.id}",
                _geomean(size_ratios)
                <= thresholds["encoded_size_profile_geomean_ratio_max"],
                geomean_ratio=_geomean(size_ratios),
                maximum=thresholds[
                    "encoded_size_profile_geomean_ratio_max"
                ],
            )

    for aggregate in aggregates:
        if not aggregate["cell"].startswith("decode/"):
            continue
        _, profile_id, _, _, _ = aggregate["cell"].split("/")
        retained = _unique_result(
            sessions, config.retained_backend, aggregate["cell"]
        )
        candidate = _unique_result(
            sessions, config.candidate_backend, aggregate["cell"]
        )
        for backend, values in (
            (config.retained_backend, retained),
            (config.candidate_backend, candidate),
        ):
            max_abs = max(
                item["max_abs_vs_reference"] for item in values
            )
            min_psnr = min(
                item["psnr_vs_reference_db"] for item in values
            )
            if profile_id in {"cmyk", "ycck"}:
                passed = max_abs <= thresholds[
                    "retained_fallback_max_abs"
                ]
                gate(
                    f"fallback-parity:{backend}:{aggregate['cell']}",
                    passed,
                    max_abs=max_abs,
                    maximum=thresholds["retained_fallback_max_abs"],
                )
            elif profile_id == "grayscale":
                gate(
                    f"decode-parity:{backend}:{aggregate['cell']}",
                    max_abs
                    <= thresholds["grayscale_decode_max_abs"]
                    and min_psnr
                    >= thresholds["grayscale_decode_psnr_min_db"],
                    max_abs=max_abs,
                    minimum_psnr_db=min_psnr,
                )
            else:
                gate(
                    f"decode-parity:{backend}:{aggregate['cell']}",
                    max_abs <= thresholds["rgb_decode_max_abs"]
                    and min_psnr
                    >= thresholds["rgb_decode_psnr_min_db"],
                    max_abs=max_abs,
                    minimum_psnr_db=min_psnr,
                )
        retained_metadata = {
            canonical_json_bytes(item["metadata"]) for item in retained
        }
        candidate_metadata = {
            canonical_json_bytes(item["metadata"]) for item in candidate
        }
        gate(
            f"decode-metadata:{aggregate['cell']}",
            retained_metadata == candidate_metadata
            and len(retained_metadata) == 1,
        )
        if profile_id in {"cmyk", "ycck"}:
            gate(
                f"fallback-output:{aggregate['cell']}",
                {item["pixel_sha256"] for item in retained}
                == {item["pixel_sha256"] for item in candidate},
            )

    primary = []
    for item in aggregates:
        parts = item["cell"].split("/")
        profile = parts[1]
        fixture = parts[3] if parts[0] == "decode" else parts[2]
        if (
            profile not in {"cmyk", "ycck"}
            and fixture_class[fixture] != "small"
        ):
            primary.append(item)
    for operation in ("encode", "decode"):
        rows_by_profile: dict[str, list[Mapping[str, Any]]] = defaultdict(
            list
        )
        for item in primary:
            parts = item["cell"].split("/")
            if parts[0] == operation:
                rows_by_profile[parts[1]].append(item)
        if not rows_by_profile:
            continue
        profile_medians = []
        profile_robust = []
        for profile, rows in sorted(rows_by_profile.items()):
            median_geomean = _geomean(
                item["median_ratio_ppm"] / _PPM for item in rows
            )
            robust_geomean = _geomean(
                item["robust_lower_ratio_ppm"] / _PPM for item in rows
            )
            profile_medians.append(median_geomean)
            profile_robust.append(robust_geomean)
            gate(
                f"{operation}-profile-geomean:{profile}",
                median_geomean
                >= thresholds[f"{operation}_geomean_ratio_min"]
                and robust_geomean
                >= thresholds[
                    f"{operation}_geomean_robust_ratio_min"
                ],
                median_geomean=median_geomean,
                robust_geomean=robust_geomean,
            )
        median_geomean = _geomean(profile_medians)
        robust_geomean = _geomean(profile_robust)
        gate(
            f"{operation}-geomean",
            median_geomean
            >= thresholds[f"{operation}_geomean_ratio_min"]
            and robust_geomean
            >= thresholds[f"{operation}_geomean_robust_ratio_min"],
            median_geomean=median_geomean,
            robust_geomean=robust_geomean,
        )
    public_rows = [
        item
        for item in primary
        if item["cell"].endswith(("/public_sink", "/public_path"))
    ]
    public_groups = {
        "encode/public_sink": [
            item
            for item in public_rows
            if item["cell"].startswith("encode/")
            and item["cell"].endswith("/public_sink")
        ],
        "decode/public_path": [
            item
            for item in public_rows
            if item["cell"].startswith("decode/")
            and item["cell"].endswith("/public_path")
        ],
    }
    for group, rows in public_groups.items():
        if not rows:
            continue
        ratio = _geomean(
            item["median_ratio_ppm"] / _PPM for item in rows
        )
        robust_ratio = _geomean(
            item["robust_lower_ratio_ppm"] / _PPM for item in rows
        )
        gate(
            f"public-surface:{group}",
            ratio >= thresholds["public_surface_ratio_min"]
            and robust_ratio
            >= thresholds["public_surface_robust_ratio_min"],
            geomean_ratio=ratio,
            robust_geomean_ratio=robust_ratio,
            minimum=thresholds["public_surface_ratio_min"],
            robust_minimum=thresholds[
                "public_surface_robust_ratio_min"
            ],
        )
    return {
        "status": (
            "passed" if all(item["passed"] for item in gates) else "failed"
        ),
        "passed": all(item["passed"] for item in gates),
        "gates": gates,
    }


def _write_report(path: Path, report: Mapping[str, Any]) -> str:
    payload = canonical_json_bytes(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.quick and not args.allow_dirty:
        raise ValueError("--quick requires --allow-dirty")
    if args.allow_dirty and not args.quick:
        raise ValueError("--allow-dirty is restricted to smoke runs")
    source = _source_identity(allow_dirty=args.allow_dirty)
    retained = BackendSpec(
        config.retained_backend,
        config.retained_marker,
        _resolve_file(args.retained_python, "retained Python"),
        _resolve_file(args.retained_wheel, "retained wheel"),
        _resolve_file(args.retained_cmake_manifest, "retained manifest"),
        None,
    )
    if not args.quick and args.candidate_simd_evidence is None:
        raise ValueError(
            "official candidate qualification requires generated SIMD evidence"
        )
    candidate = BackendSpec(
        config.candidate_backend,
        config.candidate_marker,
        _resolve_file(args.candidate_python, "candidate Python"),
        _resolve_file(args.candidate_wheel, "candidate wheel"),
        _resolve_file(args.candidate_cmake_manifest, "candidate manifest"),
        (
            None
            if args.candidate_simd_evidence is None
            else _resolve_file(
                args.candidate_simd_evidence,
                "candidate SIMD evidence",
            )
        ),
    )
    backends = (retained, candidate)
    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=False)
    worker = _copy_worker(work_dir)
    worker_sha256 = _sha256_file(worker)
    (
        environments,
        wheels,
        cmake_manifests,
        simd_evidence,
    ) = _preflight(backends, worker)
    worker_config = _worker_config(
        config,
        include_remote=args.include_remote,
        quick=args.quick,
    )
    corpus = _run_worker(
        retained,
        worker,
        {
            "schema_version": SCHEMA_VERSION,
            "action": "prepare_corpus",
            "expected_marker": retained.expected_marker,
            "output_dir": str(work_dir / "corpus"),
            "config": worker_config,
            "ycck_base64_path": str(YCCK_SOURCE),
            "decision_id": config.decision_id,
            "source_commit": source["commit"],
            "config_sha256": config.sha256,
        },
        timeout_seconds=1800,
    )
    corpus = _embed_corpus_manifest(
        corpus, config=config, source=source
    )
    startup = _measure_startup(
        config,
        backends,
        worker,
        worker_config,
        corpus,
        quick=args.quick,
    )
    determinism = _measure_determinism(
        config,
        backends,
        worker,
        worker_config,
        corpus,
        work_dir=work_dir,
        quick=args.quick,
    )
    memory = _measure_memory(
        config,
        backends,
        worker,
        worker_config,
        corpus,
        work_dir=work_dir,
        quick=args.quick,
    )
    cells = _worker_cells(worker_config)
    session_count = (
        2
        if args.quick
        else (
            config.methodology.remote_sessions
            if args.include_remote
            else config.methodology.local_sessions
        )
    )
    schedule = paired_schedule(
        retained=retained.id,
        candidate=candidate.id,
        sessions=session_count,
        seed=config.methodology.order_seed,
    )
    by_id = {backend.id: backend for backend in backends}
    raw_sessions: list[dict[str, Any]] = []
    for round_spec in schedule:
        ordered_cells = list(cells)
        random.Random(round_spec["seed"]).shuffle(ordered_cells)
        for backend_id in round_spec["order"]:
            backend = by_id[backend_id]
            response = _run_worker(
                backend,
                worker,
                {
                    "schema_version": SCHEMA_VERSION,
                    "action": "session",
                    "expected_marker": backend.expected_marker,
                    "backend": backend.id,
                    "round": round_spec["round"],
                    "config": worker_config,
                    "config_sha256": config.sha256,
                    "corpus_manifest_path": corpus["manifest_path"],
                    "corpus_manifest_sha256": corpus["manifest_sha256"],
                    "output_dir": str(
                        work_dir
                        / "sessions"
                        / f"round-{round_spec['round']}-{backend.id}"
                    ),
                    "cells": ordered_cells,
                },
                timeout_seconds=args.session_timeout,
            )
            raw_sessions.append(response)
    aggregates, primary_validation = _aggregate(
        config,
        raw_sessions,
        expected_cells=cells,
        schedule=schedule,
        worker_config=worker_config,
    )
    auxiliary_validation = _validate_auxiliary(
        config,
        startup=startup,
        determinism=determinism,
        memory=memory,
        sessions=raw_sessions,
        wheels=wheels,
        quick=args.quick,
    )
    validation = (
        {
            "status": "smoke_only",
            "passed": bool(primary_validation["passed"]),
            "gates": primary_validation["gates"],
        }
        if args.quick
        else _merge_validation(primary_validation, auxiliary_validation)
    )
    report = {
        "schema": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "result_state": (
            "smoke_only" if args.quick else "measurement_complete"
        ),
        "decision_id": config.decision_id,
        "codec_id": config.codec_id,
        "platform_profile": args.platform_profile,
        "source": source,
        "configuration": {
            "path": str(config.path),
            "sha256": config.sha256,
            "methodology": dataclasses.asdict(config.methodology),
            "thresholds": dict(config.thresholds),
            "include_remote": bool(args.include_remote),
            "quick": bool(args.quick),
        },
        "worker": {
            "source": str(WORKER_SOURCE.relative_to(ROOT)),
            "sha256": worker_sha256,
        },
        "environments": environments,
        "wheels": wheels,
        "cmake_manifests": cmake_manifests,
        "simd_evidence": simd_evidence,
        "corpus": corpus,
        "schedule": list(schedule),
        "raw_sessions": raw_sessions,
        "startup": startup,
        "determinism": determinism,
        "memory": memory,
        "aggregates": aggregates,
        "validation": validation,
    }
    if set(report) != REPORT_KEYS:
        raise RuntimeError("qualification report keys differ from schema")
    output = Path(args.output).resolve()
    report_sha256 = _write_report(output, report)
    print(
        json.dumps(
            {
                "output": str(output),
                "sha256": report_sha256,
                "state": report["result_state"],
                "validation": validation["status"],
                "sessions": len(raw_sessions),
                "cells": len(cells),
            },
            sort_keys=True,
        )
    )
    return 0 if args.quick or validation["passed"] else 1


def validate_set(args: argparse.Namespace) -> int:
    config = load_config(DEFAULT_CONFIG)
    reports = [
        json.loads(_resolve_file(path, "report").read_text(encoding="utf-8"))
        for path in args.report
    ]
    required_profiles = set(_PLATFORM_REQUIREMENTS)
    observed = {report.get("platform_profile") for report in reports}
    if len(reports) != len(required_profiles) or observed != required_profiles:
        raise ValueError(
            f"qualification set profiles are {sorted(observed)!r}"
        )
    for report in reports:
        if (
            set(report) != REPORT_KEYS
            or report.get("schema") != SCHEMA_ID
            or report.get("schema_version") != SCHEMA_VERSION
            or report.get("result_state") != "measurement_complete"
            or report.get("validation", {}).get("passed") is not True
            or report.get("source", {}).get("clean") is not True
        ):
            raise ValueError("qualification report is incomplete or failed")
        _validate_platform_report(report, config)
        corpus = report.get("corpus", {})
        manifest = corpus.get("manifest")
        if (
            not isinstance(manifest, dict)
            or _sha256_bytes(canonical_json_bytes(manifest))
            != corpus.get("manifest_sha256")
            or manifest.get("decision_id") != report["decision_id"]
            or manifest.get("source_commit")
            != report["source"]["commit"]
            or manifest.get("config_sha256")
            != report["configuration"]["sha256"]
        ):
            raise ValueError("qualification report corpus is inconsistent")
    identity = {
        (
            report["source"]["commit"],
            report["source"]["tree"],
            report["configuration"]["sha256"],
            report["decision_id"],
        )
        for report in reports
    }
    if len(identity) != 1:
        raise ValueError("qualification reports do not share one source/config")
    summary = {
        "schema": "sceneio.backend-qualification-set.v1",
        "schema_version": 1,
        "result_state": "measurement_complete",
        "decision_id": reports[0]["decision_id"],
        "source": reports[0]["source"],
        "config_sha256": reports[0]["configuration"]["sha256"],
        "platforms": {
            report["platform_profile"]: {
                "report_sha256": _sha256_file(
                    _resolve_file(path, "report")
                ),
                "validation": report["validation"]["status"],
            }
            for path, report in zip(args.report, reports, strict=True)
        },
    }
    output = Path(args.output).resolve()
    digest = _write_report(output, summary)
    print(json.dumps({"output": str(output), "sha256": digest}))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SceneIO installed-wheel backend qualification"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    run_parser.add_argument("--retained-python", required=True)
    run_parser.add_argument("--retained-wheel", required=True)
    run_parser.add_argument("--retained-cmake-manifest", required=True)
    run_parser.add_argument("--candidate-python", required=True)
    run_parser.add_argument("--candidate-wheel", required=True)
    run_parser.add_argument("--candidate-cmake-manifest", required=True)
    run_parser.add_argument("--candidate-simd-evidence")
    run_parser.add_argument("--platform-profile", required=True)
    run_parser.add_argument("--work-dir", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--session-timeout", type=float, default=3600)
    run_parser.add_argument("--include-remote", action="store_true")
    run_parser.add_argument("--quick", action="store_true")
    run_parser.add_argument("--allow-dirty", action="store_true")
    run_parser.set_defaults(handler=run)

    validate_parser = commands.add_parser("validate-set")
    validate_parser.add_argument("--report", action="append", required=True)
    validate_parser.add_argument("--output", required=True)
    validate_parser.set_defaults(handler=validate_set)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
