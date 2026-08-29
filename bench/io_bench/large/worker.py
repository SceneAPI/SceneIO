"""Fresh-child worker protocol for one large benchmark provider operation."""

from __future__ import annotations

import importlib
import json
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

from . import cases_arrays_points, cases_scene
from .cases_arrays_points import CaseUnavailable
from .measure import measure_memory, measure_timing
from .model import Measurement, OperationResult


def _scene_provider_import(provider: str) -> None:
    """Import an optional provider before entering a measured callable."""

    modules = {
        "sceneio": "sceneio",
        "niantic_spz": "spz",
        "gsply": "gsply",
        "trimesh": "trimesh",
        "pycolmap": "pycolmap",
    }
    module_name = modules.get(provider)
    if module_name is not None:
        importlib.import_module(module_name)


def _scene_output_paths(request: dict[str, Any], extension: str) -> list[Path]:
    output_dir = Path(
        request.get("output_dir", Path(request["path"]).parent / "outputs")
    ).resolve()
    output_root = Path(request.get("output_root", output_dir)).resolve()
    if output_dir != output_root and output_root not in output_dir.parents:
        raise ValueError("worker output directory is outside its declared root")
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{request['provider']}-{request['operation']}"
    return [
        output_dir / f"{stem}-{index}{extension}"
        for index in range(int(request.get("runs", 3)) + 3)
    ]


def _remove_output(value: object) -> None:
    """Remove one completed sample outside the measured write interval."""

    if not isinstance(value, Path):
        return
    nonempty = (
        value.stat().st_size > 0
        if value.is_file()
        else value.is_dir()
        and any(
            item.stat().st_size > 0 for item in value.rglob("*") if item.is_file()
        )
    )
    try:
        if value.is_dir():
            shutil.rmtree(value)
        elif value.exists():
            value.unlink()
    except OSError:
        # The parent owns the bounded final cleanup and records leftovers.
        return
    if not nonempty:
        raise RuntimeError("measured writer produced an empty output")


def _scene_operation(request: dict[str, Any]) -> dict[str, Any]:
    """Run a scene case, binding provider-native write inputs before timing."""

    case_id = str(request["case_id"])
    provider = str(request["provider"])
    operation = str(request["operation"])
    artifact = cases_scene.CaseArtifact.from_dict(dict(request["artifact"]))
    adapter = cases_scene.provider_adapters(case_id)[provider]
    _scene_provider_import(provider)
    output_paths: list[Path] = []
    cursor = 0

    if operation == "write":
        # Decode/materialize once outside the measured callable.  Otherwise
        # each timed write would include a provider read and measure the wrong
        # operation.
        value = cases_scene.provider_fixture(case_id, provider, artifact)
        suffix = {
            "spz": ".spz",
            "glb": ".glb",
            "colmap_sparse": "",
        }.get(cases_scene.CASE_DEFINITIONS[case_id].format, ".bin")
        output_paths = _scene_output_paths(request, suffix)

        def target():
            nonlocal cursor
            destination = output_paths[cursor]
            cursor += 1
            if destination.suffix == "":
                destination.mkdir(parents=True, exist_ok=True)
            adapter.write(value, destination)
            return destination

    elif operation in {"read", "cross_read"}:
        path = artifact.path

        def target():
            return adapter.read(path)

    elif operation == "inspect":
        path = artifact.path
        inspect = adapter.inspect
        if inspect is None:
            inspect = cases_scene.provider_adapters(case_id)["sceneio"].inspect
        if inspect is None:
            raise ValueError(f"provider {provider} has no inspect operation")

        def target():
            return inspect(path)

    elif operation == "image" and case_id == "colmap_tum_tracks":
        if provider != "sceneio":
            raise CaseUnavailable("single-image partial read is SceneIO-only")
        import sceneio

        path = artifact.path
        image_id = int(request.get("image_id", 1))

        def target():
            return sceneio.read_partial(
                path, format="colmap_sparse", image_id=image_id
            )

    else:
        raise ValueError(f"unsupported {case_id}/{provider}/{operation} operation")

    mode = str(request.get("mode", "timing"))
    if mode == "timing":
        measurement = measure_timing(
            target,
            runs=int(request.get("runs", 3)),
            cache_mode=str(request.get("cache_mode", "warm")),
            after_call=_remove_output if operation == "write" else None,
        )
        if operation == "write":
            output_paths = [target()]
    elif mode == "memory":
        measurement = measure_memory(
            target,
            cache_mode=str(request.get("cache_mode", "warm")),
            after_call=_remove_output if operation == "write" else None,
        )
        if operation == "write":
            output_paths = []
    else:
        raise ValueError(f"unsupported measurement mode {mode!r}")
    diagnostic: dict[str, Any] = {}
    if operation == "inspect":
        diagnostic = cases_scene.inspection_diagnostic(case_id, target())
    elif operation == "image":
        selected = target()
        diagnostic = {
            "num_cameras": int(selected.num_cameras),
            "num_images": int(selected.num_images),
            "num_points3D": int(selected.num_points3D),
            "image_ids": [int(item) for item in selected.image_ids],
            "image_names": list(selected.image_names),
        }
    return {
        "measurement": measurement.to_dict(),
        "diagnostic": diagnostic,
        "output_paths": [str(item) for item in output_paths],
    }


def _validation_request(request: dict[str, Any]) -> dict[str, Any]:
    """Run all decode-heavy semantic validation inside one bounded child."""

    from .runner import _cross_reads

    artifact = cases_scene.CaseArtifact.from_dict(dict(request["artifact"]))
    operations: list[OperationResult] = []
    for raw in request.get("operations", []):
        measured = raw["measurement"]
        measurement = Measurement(
            raw_seconds=tuple(float(item) for item in measured["raw_seconds"]),
            median_seconds=float(measured["median_seconds"]),
            traced_peak_bytes=measured.get("traced_peak_bytes"),
            rss_delta_bytes=measured.get("rss_delta_bytes"),
            cache_mode=str(measured.get("cache_mode", "warm")),
        )
        operations.append(
            OperationResult(
                case_id=str(raw["case_id"]),
                provider=str(raw["provider"]),
                operation=str(raw["operation"]),
                measurement=measurement,
                logical_bytes=int(raw["logical_bytes"]),
                encoded_bytes=int(raw["encoded_bytes"]),
                status=str(raw.get("status", "ok")),
                diagnostic=dict(raw.get("diagnostic", {})),
                output_paths=tuple(raw.get("output_paths", [])),
                error=raw.get("error"),
            )
        )
    return {"cross_reads": _cross_reads(artifact, operations)}


def _prepare_request(request: dict[str, Any]) -> dict[str, Any]:
    """Build and validate one persistent fixture in a bounded child."""

    case_id = str(request["case_id"])
    tier = str(request["tier"])
    cache = Path(request["cache"])
    sources = dict(request.get("sources", {}))
    module = (
        cases_arrays_points
        if case_id in cases_arrays_points.CASE_DEFINITIONS
        else cases_scene
    )
    artifact = module.prepare_case(case_id, tier, cache, sources)
    return {"artifact": artifact.to_dict()}


def run_request(request: dict[str, Any]) -> dict[str, Any]:
    """Execute a serializable request, returning structured status."""

    try:
        if request.get("request_kind") == "prepare":
            return {"status": "ok", **_prepare_request(request)}
        if request.get("request_kind") == "validation":
            return {"status": "ok", **_validation_request(request)}
        case_id = str(request.get("case_id", ""))
        if case_id in cases_arrays_points.CASE_DEFINITIONS:
            result = cases_arrays_points.execute_case(request)
        elif case_id in cases_scene.CASE_DEFINITIONS:
            result = _scene_operation(request)
        else:
            raise KeyError(f"unknown large benchmark case {case_id!r}")
        return {"status": "ok", **result}
    except (CaseUnavailable, cases_scene.ProviderUnavailable) as exc:
        return {"status": "skip", "error": str(exc)}
    except Exception as exc:  # pragma: no cover - exercised through subprocess
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }


def main() -> int:
    request = json.load(sys.stdin)
    result = run_request(request)
    json.dump(result, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0 if result.get("status") in {"ok", "skip"} else 1


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())


__all__ = ["main", "run_request"]
