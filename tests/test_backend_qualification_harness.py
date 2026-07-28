"""Contract and soundness tests for installed-wheel backend qualification."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import inspect
import io
import json
import math
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from bench.io_bench.backend_qualification import child
from bench.io_bench.backend_qualification import runner as qualification_runner
from bench.io_bench.backend_qualification.model import (
    SCHEMA_ID,
    SCHEMA_VERSION,
    canonical_json_bytes,
    load_config,
    median_mad_ns,
    paired_ratio_summary,
    paired_schedule,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (
        ROOT
        / "tests"
        / "contracts"
        / "backend_qualification_v1.json"
    ).read_text(encoding="utf-8")
)
CONFIG_PATH = ROOT / CONTRACT["config_path"]


def _config():
    return load_config(CONFIG_PATH)


def test_declared_jpeg_matrix_matches_the_frozen_contract_and_candidate_ledger():
    config = _config()
    candidates = (
        ROOT / "bench" / "BACKEND_CANDIDATES.toml"
    ).read_text(encoding="utf-8")

    assert config.sha256 == CONTRACT["config_sha256"]
    assert config.decision_id == CONTRACT["decision_id"]
    assert config.retained_backend == CONTRACT["retained_backend"]
    assert config.candidate_backend == CONTRACT["candidate_backend"]
    assert [item.id for item in config.fixtures] == CONTRACT["fixture_ids"]
    assert [item.id for item in config.encode_profiles] == CONTRACT[
        "encode_profile_ids"
    ]
    assert [item.id for item in config.decode_profiles] == CONTRACT[
        "decode_profile_ids"
    ]
    assert len(config.cells(include_remote=False)) == CONTRACT[
        "local_cell_count"
    ]
    assert len(config.cells(include_remote=True)) == CONTRACT[
        "remote_cell_count"
    ]
    assert config.methodology.local_sessions == CONTRACT["local_sessions"]
    assert config.methodology.remote_sessions == CONTRACT["remote_sessions"]
    assert (
        config.methodology.startup_processes
        == CONTRACT["startup_processes"]
    )
    for profile_id in (
        "encode/rgb8_q90_420",
        "encode/rgb8_q95_444",
        "decode/baseline_rgb_420",
        "decode/baseline_rgb_444",
        "decode/progressive_rgb",
        "decode/grayscale",
    ):
        assert f'"{profile_id}"' in candidates


def test_q90_is_core_buffer_only_and_q95_covers_real_sink_surfaces():
    config = _config()
    assert config.encode_profile("rgb8_q90_420").paths == ("core_buffer",)
    assert set(config.encode_profile("rgb8_q95_444").paths) == {
        "core_buffer",
        "core_sink",
        "public_sink",
    }
    worker = qualification_runner._worker_config(
        config, include_remote=False, quick=False
    )
    q90 = next(
        item
        for item in worker["encode_profiles"]
        if item["id"] == "rgb8_q90_420"
    )
    assert q90["paths"] == ["core_buffer"]


def test_matrix_loader_rejects_duplicate_cells_and_candidate_only_decode(
    tmp_path,
):
    source = CONFIG_PATH.read_text(encoding="utf-8")
    duplicate = source.replace(
        'paths = ["core_buffer"]',
        'paths = ["core_buffer", "core_buffer"]',
        1,
    )
    path = tmp_path / "duplicate.toml"
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ValueError, match="unique strings"):
        load_config(path)

    candidate_only = source.replace(
        'producers = ["pillow"]',
        'producers = ["libjpeg-turbo"]',
        1,
    )
    path = tmp_path / "candidate-only.toml"
    path.write_text(candidate_only, encoding="utf-8")
    with pytest.raises(ValueError, match="candidate-only"):
        load_config(path)


def test_schedule_is_seeded_balanced_interleaved_and_complete():
    config = _config()
    first = paired_schedule(
        retained=config.retained_backend,
        candidate=config.candidate_backend,
        sessions=config.methodology.local_sessions,
        seed=config.methodology.order_seed,
    )
    second = paired_schedule(
        retained=config.retained_backend,
        candidate=config.candidate_backend,
        sessions=config.methodology.local_sessions,
        seed=config.methodology.order_seed,
    )
    assert first == second
    assert len(first) == config.methodology.local_sessions
    assert all(
        sorted(item["order"])
        == sorted((config.retained_backend, config.candidate_backend))
        for item in first
    )
    assert sum(
        item["order"][0] == config.retained_backend for item in first
    ) == len(first) // 2

    with pytest.raises(ValueError, match="even session"):
        paired_schedule(
            retained="a", candidate="b", sessions=3, seed=1
        )


def test_statistics_are_recomputable_from_preserved_integer_samples():
    assert median_mad_ns([100, 110, 120, 130, 900]) == {
        "count": 5,
        "median_ns": 120,
        "mad_ns": 10,
    }
    summary = paired_ratio_summary(
        [200, 210, 220, 230, 240, 250],
        [100, 105, 110, 115, 120, 125],
    )
    assert summary == {
        "pairs": 6,
        "median_ratio_ppm": 2_000_000,
        "scaled_log_mad_ppm": 0,
        "robust_lower_ratio_ppm": 2_000_000,
    }
    with pytest.raises(ValueError, match="equal positive"):
        paired_ratio_summary([1, 2], [1])


def _complete_quick_sessions():
    config = _config()
    worker_config = qualification_runner._worker_config(
        config, include_remote=False, quick=True
    )
    cells = qualification_runner._worker_cells(worker_config)
    schedule = paired_schedule(
        retained=config.retained_backend,
        candidate=config.candidate_backend,
        sessions=2,
        seed=config.methodology.order_seed,
    )
    fixture_measurements = {
        fixture["id"]: (
            fixture["class"],
            fixture["samples"],
            fixture["iterations_per_sample"],
        )
        for fixture in worker_config["fixtures"]
    }
    fixture_measurements["ycck_16x16"] = ("small", 1, 1)
    markers = {
        config.retained_backend: config.retained_marker,
        config.candidate_backend: config.candidate_marker,
    }
    sessions = []
    pid = 1000
    for round_spec in schedule:
        ordered = list(cells)
        qualification_runner.random.Random(
            round_spec["seed"]
        ).shuffle(ordered)
        for backend in round_spec["order"]:
            pid += 1
            results = []
            for cell in ordered:
                fixture_class, samples, iterations = (
                    fixture_measurements[cell["fixture"]]
                )
                results.append(
                    {
                        "cell": cell["id"],
                        "operation": cell["operation"],
                        "profile": cell["profile"],
                        "producer": cell["producer"],
                        "fixture": cell["fixture"],
                        "fixture_class": fixture_class,
                        "path": cell["path"],
                        "samples": [
                            {
                                "total_ns": iterations * 100,
                                "iterations": iterations,
                                "per_operation_ns": 100,
                            }
                            for _ in range(samples)
                        ],
                    }
                )
            sessions.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "action": "session",
                    "status": "ok",
                    "pid": pid,
                    "backend": backend,
                    "round": round_spec["round"],
                    "marker": markers[backend],
                    "cell_order": [cell["id"] for cell in ordered],
                    "results": results,
                }
            )
    return config, worker_config, cells, schedule, sessions


def test_session_completeness_requires_exact_schedule_cells_samples_and_pids():
    config, worker_config, cells, schedule, sessions = (
        _complete_quick_sessions()
    )
    qualification_runner._validate_session_completeness(
        config,
        sessions,
        expected_cells=cells,
        schedule=schedule,
        worker_config=worker_config,
    )

    missing_session = json.loads(json.dumps(sessions[:-1]))
    with pytest.raises(ValueError, match="declared schedule"):
        qualification_runner._validate_session_completeness(
            config,
            missing_session,
            expected_cells=cells,
            schedule=schedule,
            worker_config=worker_config,
        )

    missing_cell = json.loads(json.dumps(sessions))
    missing_cell[0]["results"].pop()
    with pytest.raises(ValueError, match="exact requested cells"):
        qualification_runner._validate_session_completeness(
            config,
            missing_cell,
            expected_cells=cells,
            schedule=schedule,
            worker_config=worker_config,
        )

    missing_sample = json.loads(json.dumps(sessions))
    missing_sample[0]["results"][0]["samples"].clear()
    with pytest.raises(ValueError, match="result shape"):
        qualification_runner._validate_session_completeness(
            config,
            missing_sample,
            expected_cells=cells,
            schedule=schedule,
            worker_config=worker_config,
        )

    reused_pid = json.loads(json.dumps(sessions))
    reused_pid[1]["pid"] = reused_pid[0]["pid"]
    with pytest.raises(ValueError, match="fresh worker"):
        qualification_runner._validate_session_completeness(
            config,
            reused_pid,
            expected_cells=cells,
            schedule=schedule,
            worker_config=worker_config,
        )

    invalid_timing = json.loads(json.dumps(sessions))
    invalid_timing[0]["results"][0]["samples"][0][
        "per_operation_ns"
    ] = 101
    with pytest.raises(ValueError, match="invalid raw timing"):
        qualification_runner._validate_session_completeness(
            config,
            invalid_timing,
            expected_cells=cells,
            schedule=schedule,
            worker_config=worker_config,
        )


def test_canonical_json_rejects_nonfinite_values_and_has_trailing_newline():
    payload = canonical_json_bytes({"b": 2, "a": 1})
    assert payload == b'{"a":1,"b":2}\n'
    with pytest.raises(ValueError):
        canonical_json_bytes({"invalid": math.nan})


def test_corpus_manifest_is_embedded_and_bound_to_report_identity(tmp_path):
    config = _config()
    source = {"commit": "a" * 40}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": config.decision_id,
        "source_commit": source["commit"],
        "config_sha256": config.sha256,
        "raw_fixtures": [],
        "encoded_fixtures": [],
    }
    path = tmp_path / "corpus_manifest.json"
    payload = canonical_json_bytes(manifest)
    path.write_bytes(payload)
    embedded = qualification_runner._embed_corpus_manifest(
        {
            "manifest_path": str(path),
            "manifest_sha256": hashlib.sha256(payload).hexdigest(),
            "raw_fixture_count": 0,
            "encoded_fixture_count": 0,
        },
        config=config,
        source=source,
    )
    assert embedded["manifest"] == manifest

    manifest["decision_id"] = "different"
    path.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(ValueError, match="identity"):
        qualification_runner._embed_corpus_manifest(
            {
                "manifest_path": str(path),
                "manifest_sha256": hashlib.sha256(
                    path.read_bytes()
                ).hexdigest(),
            },
            config=config,
            source=source,
        )


def test_integer_fixture_generator_is_stable():
    for fixture_id, expected in CONTRACT["generator_hashes"].items():
        fixture = _config().fixture(fixture_id)
        pixels = child._fixture_pixels(
            fixture.id, fixture.height, fixture.width, fixture.seed
        )
        assert pixels.shape == (fixture.height, fixture.width, 3)
        assert str(pixels.dtype) == "uint8"
        assert (
            child._sha256_bytes(pixels.tobytes(order="C")) == expected
        )


def test_ycck_fixture_is_true_ycck_with_pinned_provenance():
    path = (
        ROOT
        / "bench"
        / "fixtures"
        / "jpeg"
        / "ycck_16x16_q90_420.b64"
    )
    data = base64.b64decode(path.read_bytes(), validate=False)
    assert child._sha256_bytes(data) == CONTRACT["ycck_fixture_sha256"]
    header = child._jpeg_header(data)
    assert header == {
        "marker": "0xc0",
        "progressive": False,
        "precision": 8,
        "height": 16,
        "width": 16,
        "components": 4,
        "sampling": [
            {"id": 1, "h": 2, "v": 2},
            {"id": 2, "h": 1, "v": 1},
            {"id": 3, "h": 1, "v": 1},
            {"id": 4, "h": 2, "v": 2},
        ],
        "restart_interval": 0,
        "restart_markers": 0,
        "adobe_transform": 2,
    }
    with Image.open(io.BytesIO(data)) as image:
        assert image.mode == "CMYK"
        assert image.size == (16, 16)
    readme = path.with_name("README.md").read_text(encoding="utf-8")
    assert CONTRACT["ycck_fixture_sha256"] in readme
    assert "c85e6b905bf237038faa936dab160ebfc5da0344" in readme


def test_independent_header_parser_confirms_sampling_progressive_and_restart():
    pixels = child._fixture_pixels("small_odd", 255, 257, 11)
    cases = [
        (
            {
                "kind": "rgb",
                "quality": 90,
                "subsampling": "420",
                "progressive": False,
                "restart_marker_blocks": 4,
            },
            [(2, 2), (1, 1), (1, 1)],
            False,
            True,
        ),
        (
            {
                "kind": "rgb",
                "quality": 95,
                "subsampling": "444",
                "progressive": True,
                "restart_marker_blocks": 0,
            },
            [(1, 1), (1, 1), (1, 1)],
            True,
            False,
        ),
    ]
    fixture = {"height": 255, "width": 257}
    for profile, sampling, progressive, restarted in cases:
        data = child._save_pillow_jpeg(pixels, profile=profile)
        header = child._jpeg_header(data)
        child._assert_header(header, profile=profile, fixture=fixture)
        assert [
            (item["h"], item["v"]) for item in header["sampling"]
        ] == sampling
        assert header["progressive"] is progressive
        assert (header["restart_interval"] > 0) is restarted


def test_worker_protocol_rejects_unknown_action_and_wrong_marker():
    with pytest.raises(ValueError, match="unknown worker action"):
        child._validate_request(
            {
                "schema_version": 1,
                "action": "invented",
                "expected_marker": "stb",
            }
        )
    with pytest.raises(ValueError, match="non-empty"):
        child._validate_request(
            {
                "schema_version": 1,
                "action": "probe",
                "expected_marker": "",
            }
        )


def test_controller_invokes_absolute_interpreter_in_isolated_mode(
    tmp_path,
    monkeypatch,
):
    python = tmp_path / "python.exe"
    wheel = tmp_path / "sceneio-0.2.0-cp312-abi3-win_amd64.whl"
    manifest = tmp_path / "manifest.json"
    worker = tmp_path / "worker.py"
    for path in (python, wheel, manifest, worker):
        path.write_bytes(b"x")
    backend = qualification_runner.BackendSpec(
        "stb", "stb", python.resolve(), wheel, manifest, None
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "schema_version": 1,
                    "status": "ok",
                    "action": "probe",
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("PYTHONPATH", "checkout")
    monkeypatch.setenv("PYTHONHOME", "other")
    monkeypatch.setattr(subprocess, "run", fake_run)
    response = qualification_runner._run_worker(
        backend,
        worker,
        {
            "schema_version": 1,
            "action": "probe",
            "expected_marker": "stb",
        },
        timeout_seconds=1,
    )
    assert response["status"] == "ok"
    assert captured["command"] == [
        str(python.resolve()),
        "-I",
        str(worker),
    ]
    assert "PYTHONPATH" not in captured["kwargs"]["env"]
    assert "PYTHONHOME" not in captured["kwargs"]["env"]
    assert captured["kwargs"]["env"]["PYTHONNOUSERSITE"] == "1"


def test_preflight_requires_matching_runtime_environments():
    retained = {
        "package_version": "0.2.0",
        "numpy_version": "2.4.6",
        "pillow_version": "12.3.0",
        "platform": {
            "system": "Windows",
            "release": "11",
            "machine": "AMD64",
            "python": "3.12.10",
            "implementation": "CPython",
        },
    }
    candidate = json.loads(json.dumps(retained))
    qualification_runner._matching_environment_identity(
        {"stb": retained, "libjpeg-turbo": candidate}
    )

    candidate["numpy_version"] = "2.3.0"
    with pytest.raises(ValueError, match="numpy_version"):
        qualification_runner._matching_environment_identity(
            {"stb": retained, "libjpeg-turbo": candidate}
        )


def test_startup_uses_separate_fresh_encode_and_decode_processes(
    tmp_path, monkeypatch
):
    config = _config()
    backends = [
        qualification_runner.BackendSpec(
            config.retained_backend,
            config.retained_marker,
            tmp_path / "retained-python.exe",
            tmp_path / "retained.whl",
            tmp_path / "retained.json",
            None,
        ),
        qualification_runner.BackendSpec(
            config.candidate_backend,
            config.candidate_marker,
            tmp_path / "candidate-python.exe",
            tmp_path / "candidate.whl",
            tmp_path / "candidate.json",
            tmp_path / "simd.json",
        ),
    ]
    calls = []

    def fake_worker(backend, worker, request, *, timeout_seconds):
        del worker, timeout_seconds
        calls.append((backend.id, dict(request)))
        return {
            "pid": 2000 + len(calls),
            "operation": request["operation"],
        }

    monkeypatch.setattr(qualification_runner, "_run_worker", fake_worker)
    worker_config = qualification_runner._worker_config(
        config, include_remote=False, quick=True
    )
    results = qualification_runner._measure_startup(
        config,
        backends,
        tmp_path / "worker.py",
        worker_config,
        {
            "manifest_path": str(tmp_path / "corpus.json"),
            "manifest_sha256": "a" * 64,
        },
        quick=True,
    )
    assert len(results) == 8
    assert len({item["pid"] for item in results}) == 8
    for backend in (config.retained_backend, config.candidate_backend):
        for round_index in range(2):
            matching = [
                item
                for item in results
                if item["backend"] == backend
                and item["round"] == round_index
            ]
            assert {item["operation"] for item in matching} == {
                "encode",
                "decode",
            }
            assert len({item["pid"] for item in matching}) == 2

    runtime_source = inspect.getsource(child._runtime)
    assert runtime_source.index("import sceneio") < runtime_source.index(
        "from PIL import Image"
    )
    assert runtime_source.index("sceneio_import_ns =") < runtime_source.index(
        "from PIL import Image"
    )


def test_mmap_and_public_decode_cells_do_not_preload_file_bytes():
    source = inspect.getsource(child._decode_cell)
    assert (
        'if path == "core_bytes":\n'
        "        data = encoded_path.read_bytes()"
    ) in source
    assert (
        'elif path == "core_mmap":\n'
        "        data = encoded_path.read_bytes()"
    ) not in source
    assert (
        'elif path == "public_path":\n'
        "        data = encoded_path.read_bytes()"
    ) not in source


def test_timed_samples_release_the_prior_result_before_the_next_sample():
    live = 0
    peak = 0

    class Result:
        def __init__(self):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)

        def __del__(self):
            nonlocal live
            live -= 1

    samples, last = child._timed_samples(
        Result, warmups=0, samples=3, iterations=1
    )
    assert len(samples) == 3
    assert peak == 1
    assert live == 1
    del last
    assert live == 0


def test_dirty_source_allowance_cannot_produce_an_official_report():
    with pytest.raises(ValueError, match="restricted to smoke"):
        qualification_runner.run(
            SimpleNamespace(
                config=str(CONFIG_PATH),
                quick=False,
                allow_dirty=True,
            )
        )


def _write_test_wheel(
    path: Path,
    *,
    include_development_payload: bool = False,
) -> bytes:
    native = b"native-module"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sceneio/__init__.py", "from . import registry\n")
        archive.writestr("sceneio/registry.py", "FORMATS = ()\n")
        archive.writestr("sceneio/_core.cp312-win_amd64.pyd", native)
        archive.writestr(
            "sceneio-0.2.0.dist-info/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: sceneio\n"
            "Version: 0.2.0\n"
            "Requires-Dist: numpy>=1.26\n",
        )
        for index in range(17):
            archive.writestr(
                f"sceneio-0.2.0.dist-info/licenses/notice-{index}.txt",
                f"notice {index}",
            )
        if include_development_payload:
            archive.writestr("include/unexpected.h", "header")
    return native


def test_wheel_inspection_requires_one_native_numpy_only_and_no_dev_payload(
    tmp_path,
):
    wheel = tmp_path / "sceneio-0.2.0-cp312-abi3-win_amd64.whl"
    native = _write_test_wheel(wheel)
    backend = qualification_runner.BackendSpec(
        "stb",
        "stb",
        tmp_path / "python.exe",
        wheel,
        tmp_path / "manifest.json",
        None,
    )
    result = qualification_runner._inspect_wheel(backend)
    assert result["native_sha256"] == child._sha256_bytes(native)
    assert result["package_members_sha256"] == {
        "sceneio/__init__.py": child._sha256_bytes(
            b"from . import registry\n"
        ),
        "sceneio/registry.py": child._sha256_bytes(b"FORMATS = ()\n"),
    }
    assert result["notice_members"] == 17
    assert result["runtime_requirements"] == ["numpy>=1.26"]

    bad = tmp_path / "bad-cp312-abi3-win_amd64.whl"
    _write_test_wheel(bad, include_development_payload=True)
    with pytest.raises(ValueError, match="development payload"):
        qualification_runner._inspect_wheel(
            dataclasses.replace(backend, wheel=bad)
        )


def test_installed_python_package_is_bound_to_the_supplied_wheel(tmp_path):
    package = tmp_path / "sceneio"
    package.mkdir()
    core = package / "_core.cp312-win_amd64.pyd"
    core.write_bytes(b"native")
    (package / "__init__.py").write_bytes(b"VALUE = 1\n")
    pycache = package / "__pycache__"
    pycache.mkdir()
    (pycache / "__init__.pyc").write_bytes(b"generated")
    members = child._installed_package_members(package, core)
    expected = {
        "sceneio/__init__.py": child._sha256_bytes(b"VALUE = 1\n")
    }
    assert members == expected

    wheel = {
        "native_sha256": child._sha256_bytes(b"native"),
        "package_members_sha256": expected,
    }
    probe = {
        "core_sha256": child._sha256_bytes(b"native"),
        "package_members_sha256": expected,
    }
    qualification_runner._validate_installed_wheel("stb", wheel, probe)
    probe["package_members_sha256"] = {
        "sceneio/__init__.py": "0" * 64
    }
    with pytest.raises(ValueError, match="Python package"):
        qualification_runner._validate_installed_wheel(
            "stb", wheel, probe
        )


def test_simd_evidence_is_derived_from_and_bound_to_the_generated_header(
    tmp_path,
):
    header = tmp_path / "jconfigint.h"
    header.write_text(
        "#define SIMD_ARCHITECTURE X86_64\n", encoding="utf-8"
    )
    evidence = tmp_path / "sceneio-jpeg-simd-Release.json"
    evidence.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "simd_required": True,
                "simd_architecture": "X86_64",
                "generated_header": str(header),
                "generated_header_sha256": hashlib.sha256(
                    header.read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    backend = qualification_runner.BackendSpec(
        "libjpeg-turbo",
        "libjpeg-turbo-3.2.0",
        tmp_path / "python.exe",
        tmp_path / "sceneio-cp312-abi3.whl",
        tmp_path / "manifest.json",
        evidence,
    )

    result = qualification_runner._load_simd_evidence(backend)
    assert result is not None
    assert result["simd_architecture"] == "X86_64"

    header.write_text(
        "#define SIMD_ARCHITECTURE NONE\n", encoding="utf-8"
    )
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["simd_architecture"] = "NONE"
    payload["generated_header_sha256"] = hashlib.sha256(
        header.read_bytes()
    ).hexdigest()
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="SIMD evidence"):
        qualification_runner._load_simd_evidence(backend)


def test_effective_rss_uses_the_larger_sampled_or_exact_delta():
    sampled = qualification_runner._rss_deltas(
        controller_baseline=100,
        controller_peak=180,
        worker_baseline=110,
        worker_after=150,
    )
    assert sampled["effective_delta_rss_bytes"] == 80
    exact = qualification_runner._rss_deltas(
        controller_baseline=100,
        controller_peak=120,
        worker_baseline=110,
        worker_after=190,
    )
    assert exact["effective_delta_rss_bytes"] == 80


def test_memory_sampler_accepts_direct_or_verified_child_interpreter_pid():
    direct = SimpleNamespace(parents=lambda: [])
    child_process = SimpleNamespace(
        parents=lambda: [SimpleNamespace(pid=100)]
    )
    unrelated = SimpleNamespace(
        parents=lambda: [SimpleNamespace(pid=999)]
    )

    class FakePsutil:
        NoSuchProcess = RuntimeError
        ZombieProcess = RuntimeError

        def __init__(self, processes):
            self.processes = processes

        def Process(self, pid):
            return self.processes[pid]

    psutil = FakePsutil(
        {100: direct, 101: child_process, 102: unrelated}
    )
    assert (
        qualification_runner._memory_worker_process(
            psutil, launcher_pid=100, worker_pid=100
        )
        is direct
    )
    assert (
        qualification_runner._memory_worker_process(
            psutil, launcher_pid=100, worker_pid=101
        )
        is child_process
    )
    with pytest.raises(RuntimeError, match="invalid process ID"):
        qualification_runner._memory_worker_process(
            psutil, launcher_pid=100, worker_pid="101"
        )
    with pytest.raises(RuntimeError, match="not a child"):
        qualification_runner._memory_worker_process(
            psutil, launcher_pid=100, worker_pid=102
        )


def test_memory_process_tree_cleanup_stops_launcher_worker_and_descendant():
    events = []

    class MissingProcess(Exception):
        pass

    class FakeZombieProcess(Exception):
        pass

    class CleanupFailure(Exception):
        pass

    class FakeProcess:
        def __init__(self, pid, children=()):
            self.pid = pid
            self._children = list(children)

        def children(self, *, recursive):
            assert recursive is True
            result = list(self._children)
            for descendant_process in self._children:
                result.extend(
                    descendant_process.children(recursive=True)
                )
            return result

        def terminate(self):
            events.append(("terminate", self.pid))

        def kill(self):
            events.append(("kill", self.pid))

    descendant = FakeProcess(102)
    worker = FakeProcess(101, [descendant])
    launcher = FakeProcess(100, [worker])

    class FakePsutil:
        NoSuchProcess = MissingProcess
        ZombieProcess = FakeZombieProcess
        fail_wait = False

        @staticmethod
        def Process(pid):
            assert pid == launcher.pid
            return launcher

        @staticmethod
        def wait_procs(processes, *, timeout):
            assert timeout == 5
            events.append(("wait", tuple(item.pid for item in processes)))
            if FakePsutil.fail_wait:
                raise CleanupFailure("wait failed")
            if descendant in processes and ("kill", descendant.pid) not in events:
                return [], [descendant]
            return list(processes), []

    class FakePopen:
        pid = launcher.pid

        @staticmethod
        def poll():
            return None

        @staticmethod
        def kill():
            events.append(("popen-kill", launcher.pid))

        @staticmethod
        def wait(*, timeout):
            assert timeout == 5
            events.append(("popen-wait", launcher.pid))
            return 1

    qualification_runner._terminate_memory_process_tree(
        FakePsutil(),
        FakePopen(),
        sampled=worker,
    )

    terminated = {
        pid for action, pid in events if action == "terminate"
    }
    assert terminated == {launcher.pid, worker.pid, descendant.pid}
    assert ("kill", descendant.pid) in events
    assert ("popen-kill", launcher.pid) in events
    assert ("popen-wait", launcher.pid) in events

    events.clear()
    FakePsutil.fail_wait = True
    with pytest.raises(RuntimeError, match="wait failed"):
        qualification_runner._terminate_memory_process_tree(
            FakePsutil(),
            FakePopen(),
            sampled=worker,
        )
    assert ("popen-kill", launcher.pid) in events
    assert ("popen-wait", launcher.pid) in events


def test_memory_worker_failure_invokes_process_tree_cleanup(
    tmp_path, monkeypatch
):
    backend = qualification_runner.BackendSpec(
        "stb",
        "stb",
        tmp_path / "python.exe",
        tmp_path / "retained.whl",
        tmp_path / "manifest.json",
        None,
    )

    class FakePopen:
        pid = 100

        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO()
            self.stderr = io.StringIO()

    processes = []

    def fake_popen(*args, **kwargs):
        process = FakePopen()
        processes.append(process)
        return process

    cleanup = []
    monkeypatch.setattr(
        qualification_runner.subprocess,
        "Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        qualification_runner,
        "_readline_with_timeout",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            TimeoutError("worker response timed out")
        ),
    )
    monkeypatch.setattr(
        qualification_runner,
        "_terminate_memory_process_tree",
        lambda psutil_module, launched, *, sampled: cleanup.append(
            (launched, sampled)
        ),
    )

    with pytest.raises(TimeoutError, match="worker response timed out"):
        qualification_runner._run_memory_worker(
            backend,
            tmp_path / "worker.py",
            {"action": "memory"},
            timeout_seconds=0.1,
        )

    assert cleanup == [(processes[0], None)]

    def fail_cleanup(psutil_module, launched, *, sampled):
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(
        qualification_runner,
        "_terminate_memory_process_tree",
        fail_cleanup,
    )
    with pytest.raises(TimeoutError) as error:
        qualification_runner._run_memory_worker(
            backend,
            tmp_path / "worker.py",
            {"action": "memory"},
            timeout_seconds=0.1,
        )
    assert error.value.__notes__ == [
        "memory worker cleanup also failed: cleanup failed"
    ]


def test_memory_worker_warms_small_then_measures_first_large_operation(
    tmp_path, monkeypatch
):
    import psutil

    retained_bytes = 0
    calls = []

    def fake_operation(
        request, *, fixture_override=None, output_label="measured"
    ):
        del request
        calls.append((fixture_override, output_label))
        allocation = 10 if fixture_override == "small_odd" else 100

        def operation():
            nonlocal retained_bytes
            retained_bytes += allocation
            return object()

        return operation, [], {"logical_bytes": 1, "encoded_bytes": None}

    class FakeProcess:
        def memory_info(self):
            return SimpleNamespace(rss=1000 + retained_bytes)

    monkeypatch.setattr(child, "_memory_operation", fake_operation)
    monkeypatch.setattr(psutil, "Process", FakeProcess)
    monkeypatch.setattr(
        child,
        "_runtime",
        lambda: {
            "core": SimpleNamespace(
                _jpeg_backend_id=lambda: "stb"
            )
        },
    )
    monkeypatch.setattr(
        child.sys, "stdin", io.StringIO('{"command":"go"}\n')
    )
    result = child._memory(
        {
            "output_dir": str(tmp_path),
            "case": {
                "id": "case",
                "operation": "encode",
                "profile": "rgb8_q95_444",
                "producer": None,
                "fixture": "texture_4k",
                "path": "core_buffer",
            },
        }
    )
    assert calls == [
        ("small_odd", "warmup"),
        (None, "measured"),
    ]
    assert result["worker_baseline_rss_bytes"] == 1010
    assert result["worker_after_rss_bytes"] == 1110


def test_timing_variability_gate_rejects_an_unstable_cell():
    config = _config()
    cell = "encode/rgb8_q90_420/small_odd/core_buffer"
    retained = {
        "backend": config.retained_backend,
        "round": 0,
        "results": [
            {
                "cell": cell,
                "encoded_sha256": "a" * 64,
                "psnr_db": 50.0,
                "encoded_bytes": 100,
            }
        ],
    }
    candidate = {
        "backend": config.candidate_backend,
        "round": 0,
        "results": [
            {
                "cell": cell,
                "encoded_sha256": "b" * 64,
                "psnr_db": 50.0,
                "encoded_bytes": 100,
            }
        ],
    }
    validation = qualification_runner._validate_results(
        config,
        [retained, candidate],
        [
            {
                "cell": cell,
                "median_ratio_ppm": 1_000_000,
                "scaled_log_mad_ppm": 90_000,
                "robust_lower_ratio_ppm": 1_000_000,
            }
        ],
    )
    gate = next(
        item
        for item in validation["gates"]
        if item["name"] == f"measurement-noise:{cell}"
    )
    assert gate["passed"] is False
    assert validation["passed"] is False


def test_public_encode_and_decode_surfaces_have_independent_gates():
    config = _config()
    aggregates = [
        {
            "cell": "encode/rgb8_q95_444/photo_fhd/public_sink",
            "median_ratio_ppm": 1_000_000,
            "scaled_log_mad_ppm": 0,
            "robust_lower_ratio_ppm": 1_000_000,
        }
    ]
    validation = qualification_runner._validate_results(
        config, [], aggregates
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert "public-surface:encode/public_sink" in gates
    assert "public-surface:decode/public_path" not in gates
    assert gates["public-surface:encode/public_sink"]["passed"] is False


def test_each_profile_and_public_robust_ratio_must_pass_independently():
    config = _config()
    q90 = "encode/rgb8_q90_420/photo_fhd/core_buffer"
    q95 = "encode/rgb8_q95_444/photo_fhd/public_sink"
    sessions = [
        {
            "backend": config.retained_backend,
            "results": [
                {
                    "cell": q90,
                    "encoded_sha256": "a" * 64,
                    "psnr_db": 50.0,
                    "encoded_bytes": 100,
                }
            ],
        },
        {
            "backend": config.candidate_backend,
            "results": [
                {
                    "cell": q90,
                    "encoded_sha256": "b" * 64,
                    "psnr_db": 50.0,
                    "encoded_bytes": 100,
                }
            ],
        },
    ]
    aggregates = [
        {
            "cell": q90,
            "median_ratio_ppm": 950_000,
            "scaled_log_mad_ppm": 0,
            "robust_lower_ratio_ppm": 950_000,
        },
        {
            "cell": q95,
            "median_ratio_ppm": 1_500_000,
            "scaled_log_mad_ppm": 0,
            "robust_lower_ratio_ppm": 1_500_000,
        },
    ]
    validation = qualification_runner._validate_results(
        config, sessions, aggregates
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert gates["encode-profile-geomean:rgb8_q90_420"][
        "passed"
    ] is False
    assert validation["passed"] is False

    robust_public = [
        {
            "cell": q95,
            "median_ratio_ppm": 1_200_000,
            "scaled_log_mad_ppm": 0,
            "robust_lower_ratio_ppm": 990_000,
        }
    ]
    validation = qualification_runner._validate_results(
        config, [], robust_public
    )
    gate = next(
        item
        for item in validation["gates"]
        if item["name"] == "public-surface:encode/public_sink"
    )
    assert gate["passed"] is False
    assert gate["geomean_ratio"] == pytest.approx(1.2)
    assert gate["robust_geomean_ratio"] == pytest.approx(0.99)


def test_remote_8k_encode_enters_quality_and_primary_performance_gates():
    config = _config()
    cell = "encode/rgb8_q90_420/photo_8k/core_buffer"
    sessions = [
        {
            "backend": config.retained_backend,
            "results": [
                {
                    "cell": cell,
                    "encoded_sha256": "a" * 64,
                    "psnr_db": 50.0,
                    "encoded_bytes": 100,
                }
            ],
        },
        {
            "backend": config.candidate_backend,
            "results": [
                {
                    "cell": cell,
                    "encoded_sha256": "b" * 64,
                    "psnr_db": 49.0,
                    "encoded_bytes": 100,
                }
            ],
        },
    ]
    validation = qualification_runner._validate_results(
        config,
        sessions,
        [
            {
                "cell": cell,
                "median_ratio_ppm": 1_300_000,
                "scaled_log_mad_ppm": 0,
                "robust_lower_ratio_ppm": 1_200_000,
            }
        ],
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert f"performance-cell:{cell}" in gates
    assert gates["quality:rgb8_q90_420:photo_8k"]["passed"] is False
    assert "encode-profile-geomean:rgb8_q90_420" in gates


def test_repeatability_requires_the_declared_number_of_hashes():
    config = _config()
    expected_decoders = [
        f"{profile.id}--{producer}--{fixture}"
        for profile in config.decode_profiles
        for producer in profile.producers
        for fixture in profile.fixtures
        if fixture in {"small_odd", "ycck_16x16"}
    ]
    encoders = []
    for profile in config.encode_profiles:
        encoder = {
            "profile": profile.id,
            "quality": profile.quality,
            "hashes": ["a" * 64],
        }
        if profile.quality == 95:
            encoder.update(
                {
                    "buffer_sha256": "a" * 64,
                    "core_sink_sha256": "a" * 64,
                    "public_sink_sha256": "a" * 64,
                }
            )
        encoders.append(encoder)
    determinism = [
        {
            "schema_version": SCHEMA_VERSION,
            "action": "determinism",
            "status": "ok",
            "backend": config.retained_backend,
            "pid": 100,
            "process_index": 0,
            "marker": config.retained_marker,
            "fixture": "small_odd",
            "repeats": int(config.thresholds["determinism_repeats"]),
            "encoders": encoders,
            "decoders": [
                {
                    "fixture": fixture,
                    "encoded_sha256": "c" * 64,
                    "pixel_hashes": ["b" * 64],
                }
                for fixture in expected_decoders
            ],
            "rss_plateau": {
                "encode_q95_core_buffer": [100] * 50,
                "decode_420_core_bytes": [100] * 50,
            },
        }
    ]
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=[],
        determinism=determinism,
        memory=[],
        sessions=[],
        wheels={
            config.retained_backend: {"bytes": 100, "native_bytes": 100},
            config.candidate_backend: {"bytes": 100, "native_bytes": 100},
        },
        quick=False,
    )
    gate = next(
        item
        for item in validation["gates"]
        if item["name"].startswith(
            f"determinism:{config.retained_backend}:0:"
        )
    )
    assert gate["passed"] is False
    assert gate["observations"] == 1
    assert gate["required"] == config.thresholds["determinism_repeats"]
    shape = next(
        item
        for item in validation["gates"]
        if item["name"]
        == f"determinism-shape:{config.retained_backend}:0"
    )
    assert shape["passed"] is True

    invalid = json.loads(json.dumps(determinism))
    invalid[0]["marker"] = "wrong"
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=[],
        determinism=invalid,
        memory=[],
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    shape = next(
        item
        for item in validation["gates"]
        if item["name"]
        == f"determinism-shape:{config.retained_backend}:0"
    )
    assert shape["passed"] is False

    extra_backend = json.loads(json.dumps(determinism))
    extra_backend.append({"backend": "extra"})
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=[],
        determinism=extra_backend,
        memory=[],
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gate = next(
        item
        for item in validation["gates"]
        if item["name"] == "determinism-observation-set"
    )
    assert gate["passed"] is False

    string_pids = []
    for process_index in range(
        int(config.thresholds["determinism_processes"])
    ):
        item = json.loads(json.dumps(determinism[0]))
        item["process_index"] = process_index
        item["pid"] = f"pid-{process_index}"
        string_pids.append(item)
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=[],
        determinism=string_pids,
        memory=[],
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gate = next(
        item
        for item in validation["gates"]
        if item["name"] == f"fresh-processes:{config.retained_backend}"
    )
    assert gate["passed"] is False


def test_auxiliary_validation_fails_closed_when_measurements_are_missing():
    config = _config()
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=[],
        determinism=[],
        memory=[],
        sessions=[],
        wheels={
            config.retained_backend: {"bytes": 100, "native_bytes": 100},
            config.candidate_backend: {"bytes": 100, "native_bytes": 100},
        },
        quick=False,
    )
    failed = {
        item["name"]
        for item in validation["gates"]
        if not item["passed"]
    }
    assert {
        "startup-completeness:stb",
        "startup-completeness:libjpeg-turbo",
        "fresh-processes:stb",
        "fresh-processes:libjpeg-turbo",
        "memory-completeness:encode_large_q95_core_buffer",
    } <= failed
    assert validation["status"] == "failed"


def _minimal_wheels(config):
    return {
        config.retained_backend: {"bytes": 100, "native_bytes": 100},
        config.candidate_backend: {"bytes": 100, "native_bytes": 100},
    }


def test_startup_evidence_requires_exact_tuples_and_stable_hashes():
    config = _config()
    startup = []
    pid = 3000
    markers = {
        config.retained_backend: config.retained_marker,
        config.candidate_backend: config.candidate_marker,
    }
    schedule = paired_schedule(
        retained=config.retained_backend,
        candidate=config.candidate_backend,
        sessions=config.methodology.startup_processes,
        seed=config.methodology.order_seed + 10_000,
    )
    for round_spec in schedule:
        operations = (
            ("encode", "decode")
            if round_spec["round"] % 2 == 0
            else ("decode", "encode")
        )
        for backend in round_spec["order"]:
            for operation in operations:
                pid += 1
                startup.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "action": "startup",
                        "status": "ok",
                        "pid": pid,
                        "backend": backend,
                        "round": round_spec["round"],
                        "marker": markers[backend],
                        "fixture": "photo_fhd",
                        "operation": operation,
                        "import_ns": 100,
                        "first_call_ns": 200,
                        "encoded_sha256": "a" * 64,
                        "output_sha256": (
                            "b" * 64
                            if operation == "encode"
                            else "c" * 64
                        ),
                    }
                )
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=startup,
        determinism=[],
        memory=[],
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert gates["startup-completeness:stb"]["passed"] is True
    assert gates["startup-input-identity"]["passed"] is True
    assert gates["startup-output-identity:stb:decode"]["passed"] is True

    extra_backend = json.loads(json.dumps(startup))
    extra_backend.append({"backend": "extra"})
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=extra_backend,
        determinism=[],
        memory=[],
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert gates["startup-observation-set"]["passed"] is False

    string_pids = json.loads(json.dumps(startup))
    for index, item in enumerate(string_pids):
        item["pid"] = f"pid-{index}"
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=string_pids,
        determinism=[],
        memory=[],
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert gates["startup-observation-set"]["passed"] is True
    assert gates["startup-completeness:stb"]["passed"] is False

    wrong_round = json.loads(json.dumps(startup))
    wrong_round[0]["round"] = 1
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=wrong_round,
        determinism=[],
        memory=[],
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert gates["startup-observation-set"]["passed"] is False

    unstable = json.loads(json.dumps(startup))
    changed = next(
        item
        for item in unstable
        if item["backend"] == config.retained_backend
        and item["operation"] == "encode"
    )
    changed["output_sha256"] = "d" * 64
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=unstable,
        determinism=[],
        memory=[],
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gate = next(
        item
        for item in validation["gates"]
        if item["name"] == "startup-output-identity:stb:encode"
    )
    assert gate["passed"] is False


def test_memory_evidence_requires_exact_cases_samples_metadata_and_fresh_pids():
    config = _config()
    memory = []
    pid = 4000
    markers = {
        config.retained_backend: config.retained_marker,
        config.candidate_backend: config.candidate_marker,
    }
    for case in config.memory_cases:
        for sample_index in range(config.methodology.memory_samples):
            order = (
                (config.retained_backend, config.candidate_backend)
                if sample_index % 2 == 0
                else (config.candidate_backend, config.retained_backend)
            )
            for backend in order:
                pid += 1
                memory.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "action": "memory",
                        "status": "ok",
                        "pid": pid,
                        "backend": backend,
                        "marker": markers[backend],
                        "case": case.id,
                        "sample_index": sample_index,
                        "operation": case.operation,
                        "profile": case.profile,
                        "producer": case.producer,
                        "fixture": case.fixture,
                        "path": case.path,
                        "duration_ns": 100,
                        "controller_baseline_rss_bytes": 1000,
                        "controller_peak_rss_bytes": 2024,
                        "controller_delta_rss_bytes": 1024,
                        "worker_baseline_rss_bytes": 1000,
                        "worker_after_rss_bytes": 1500,
                        "worker_delta_rss_bytes": 500,
                        "effective_delta_rss_bytes": 1024,
                        "sampling_interval_seconds": 0.0005,
                    }
                )
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=[],
        determinism=[],
        memory=memory,
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert gates["memory-fresh-processes"]["passed"] is True
    assert all(
        gates[f"memory-completeness:{case.id}"]["passed"]
        for case in config.memory_cases
    )

    repeated = json.loads(json.dumps(memory))
    repeated[1]["pid"] = repeated[0]["pid"]
    repeated[2]["sample_index"] = 0
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=[],
        determinism=[],
        memory=repeated,
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert gates["memory-fresh-processes"]["passed"] is False
    assert gates[
        f"memory-completeness:{config.memory_cases[0].id}"
    ]["passed"] is False

    understated = json.loads(json.dumps(memory))
    understated[0]["effective_delta_rss_bytes"] = 0
    validation = qualification_runner._validate_auxiliary(
        config,
        startup=[],
        determinism=[],
        memory=understated,
        sessions=[],
        wheels=_minimal_wheels(config),
        quick=False,
    )
    gates = {item["name"]: item for item in validation["gates"]}
    assert gates[
        f"memory-completeness:{config.memory_cases[0].id}"
    ]["passed"] is False


def test_backend_qualification_workflow_is_manual_nonpublishing_and_complete():
    workflow = (
        ROOT / ".github" / "workflows" / "backend-qualification.yml"
    ).read_text(encoding="utf-8")

    assert "on:\n  workflow_dispatch:\n" in workflow
    assert "\n  push:" not in workflow
    assert "id-token:" not in workflow
    assert "gh-action-pypi-publish" not in workflow
    assert "twine" not in workflow
    assert "permissions:\n  contents: read\n" in workflow
    for profile in CONTRACT["platform_profiles"]:
        assert f"--platform-profile {profile}" in workflow
    assert (
        "quay.io/pypa/manylinux2014_x86_64@sha256:"
        "92f4005bb23138b89ed22ba1491ddbedb0564747e7ce44b33c52aa6f1a786d23"
        in workflow
    )
    assert (
        "04ec2385879f7e1c45dbe76c4020970555de48eeb97c23f59620ede061328f51"
        in workflow
    )
    assert (
        "87336eba53b4acfe917424ab5d500d2b0054d9f5148d35c2273ccf2cfb712f0d"
        in workflow
    )
    assert "git config --global --add safe.directory /src" in workflow
    assert workflow.count("--include-remote") == 3
    assert "validate-set" in workflow


def _platform_report(profile):
    config = _config()
    requirement = qualification_runner._PLATFORM_REQUIREMENTS[profile]
    package_members = {"sceneio/__init__.py": "1" * 64}
    backend_ids = (config.retained_backend, config.candidate_backend)
    markers = {
        config.retained_backend: config.retained_marker,
        config.candidate_backend: config.candidate_marker,
    }
    environments = {}
    wheels = {}
    manifests = {}
    machine = sorted(requirement["machines"])[0]
    version = (
        "10.2.1"
        if requirement["compiler"] == "GNU"
        else "19.44"
    )
    for backend in backend_ids:
        environments[backend] = {
            "schema_version": SCHEMA_VERSION,
            "action": "probe",
            "status": "ok",
            "isolated": True,
            "marker": markers[backend],
            "core_sha256": "2" * 64,
            "package_members_sha256": package_members,
            "platform": {
                "system": requirement["system"],
                "machine": machine,
            },
        }
        wheels[backend] = {
            "sha256": "3" * 64,
            "native_sha256": "2" * 64,
            "package_members_sha256": package_members,
        }
        manifests[backend] = {
            "schema_version": 1,
            "qualification_build": True,
            "jpeg_backend": backend,
            "internal_jpeg_default": config.retained_backend,
            "system_name": requirement["cmake_system"],
            "system_processor": machine,
            "c_compiler_id": requirement["compiler"],
            "cxx_compiler_id": requirement["compiler"],
            "c_compiler_version": version,
            "cxx_compiler_version": version,
            "simd_required": backend == config.candidate_backend,
        }
    primary = {
        "status": "passed",
        "passed": True,
        "gates": [{"name": "primary", "passed": True}],
    }
    auxiliary = {
        "status": "passed",
        "passed": True,
        "gates": [{"name": "auxiliary", "passed": True}],
    }
    report = {
        "decision_id": config.decision_id,
        "codec_id": config.codec_id,
        "platform_profile": profile,
        "configuration": {
            "sha256": config.sha256,
            "methodology": dataclasses.asdict(config.methodology),
            "thresholds": dict(config.thresholds),
            "include_remote": True,
            "quick": False,
        },
        "environments": environments,
        "wheels": wheels,
        "cmake_manifests": manifests,
        "simd_evidence": {
            config.candidate_backend: {
                "schema_version": 1,
                "simd_required": True,
                "simd_architecture": requirement["simd_architecture"],
                "generated_header_sha256": "4" * 64,
                "evidence_sha256": "5" * 64,
            }
        },
        "schedule": list(
            paired_schedule(
                retained=config.retained_backend,
                candidate=config.candidate_backend,
                sessions=config.methodology.remote_sessions,
                seed=config.methodology.order_seed,
            )
        ),
        "raw_sessions": [],
        "startup": [],
        "determinism": [],
        "memory": [],
        "aggregates": [],
        "validation": qualification_runner._merge_validation(
            primary, auxiliary
        ),
    }
    return report, primary, auxiliary


@pytest.mark.parametrize("profile", CONTRACT["platform_profiles"])
def test_platform_report_binds_label_full_config_toolchain_and_validation(
    profile, monkeypatch
):
    report, primary, auxiliary = _platform_report(profile)
    config = _config()
    monkeypatch.setattr(
        qualification_runner,
        "_worker_config",
        lambda config, include_remote, quick: {},
    )
    monkeypatch.setattr(
        qualification_runner, "_worker_cells", lambda config: []
    )
    monkeypatch.setattr(
        qualification_runner,
        "_aggregate",
        lambda config,
        sessions,
        *,
        expected_cells,
        schedule,
        worker_config: ([], primary),
    )
    monkeypatch.setattr(
        qualification_runner,
        "_validate_auxiliary",
        lambda config,
        *,
        startup,
        determinism,
        memory,
        sessions,
        wheels,
        quick: auxiliary,
    )
    qualification_runner._validate_platform_report(report, config)

    mutations = []
    local_only = json.loads(json.dumps(report))
    local_only["configuration"]["include_remote"] = False
    mutations.append(local_only)
    wrong_system = json.loads(json.dumps(report))
    wrong_system["environments"][config.retained_backend]["platform"][
        "system"
    ] = "Other"
    mutations.append(wrong_system)
    wrong_compiler = json.loads(json.dumps(report))
    wrong_compiler["cmake_manifests"][config.candidate_backend][
        "c_compiler_id"
    ] = "Other"
    mutations.append(wrong_compiler)
    no_simd = json.loads(json.dumps(report))
    no_simd["simd_evidence"][config.candidate_backend][
        "simd_architecture"
    ] = "NONE"
    mutations.append(no_simd)
    incoherent = json.loads(json.dumps(report))
    incoherent["validation"]["status"] = "failed"
    incoherent["validation"]["gates"][0]["passed"] = False
    mutations.append(incoherent)
    for mutation in mutations:
        with pytest.raises(ValueError):
            qualification_runner._validate_platform_report(
                mutation, config
            )


def test_qualification_set_rejects_duplicates_and_dirty_reports(tmp_path):
    base = dict.fromkeys(qualification_runner.REPORT_KEYS)
    base.update(
        {
            "schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "result_state": "measurement_complete",
            "validation": {"passed": True},
            "source": {
                "commit": "a" * 40,
                "tree": "b" * 40,
                "clean": False,
            },
            "configuration": {"sha256": "c" * 64},
            "decision_id": "jpeg-rgb8-v1",
        }
    )
    paths = []
    for profile in CONTRACT["platform_profiles"]:
        report = {**base, "platform_profile": profile}
        path = tmp_path / f"{profile}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        paths.append(str(path))

    with pytest.raises(ValueError, match="incomplete or failed"):
        qualification_runner.validate_set(
            SimpleNamespace(
                report=paths,
                output=str(tmp_path / "summary.json"),
            )
        )
    with pytest.raises(ValueError, match="set profiles"):
        qualification_runner.validate_set(
            SimpleNamespace(
                report=[*paths, paths[0]],
                output=str(tmp_path / "summary.json"),
            )
        )


def test_worker_actions_and_report_keys_are_frozen_by_the_schema_contract():
    assert CONTRACT["schema"] == SCHEMA_ID
    assert CONTRACT["schema_version"] == SCHEMA_VERSION
    assert sorted(child.WORKER_ACTIONS) == CONTRACT["worker_actions"]
    assert sorted(qualification_runner.REPORT_KEYS) == CONTRACT["report_keys"]
