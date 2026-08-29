"""Large benchmark adapters for NPY depth stacks and Autzen LAZ points.

The builders are deterministic and keep fixture construction outside the timed
worker operation.  Optional ``laspy``/``lazrs`` imports stay local so the smoke
tier remains usable in a minimal development environment.
"""

from __future__ import annotations

import gc
import json
import math
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from .measure import measure_callable, measure_memory, measure_timing
from .model import CaseArtifact, CaseDefinition

NPY_CASE = CaseDefinition(
    id="npy_depth_stack",
    format="npy",
    source_id=None,
    description="Deterministic float32 depth stack with TUM 640x480 geometry.",
    standard_logical_bytes=256 * 1024 * 1024,
    operations=("map_open", "full_scan", "write", "inspect"),
    providers=("sceneio", "numpy"),
)
LAZ_CASE = CaseDefinition(
    id="laz_autzen",
    format="laz",
    source_id="pdal_autzen_laz",
    description="Autzen LAZ, canonicalized to SceneIO's supported point profile.",
    standard_logical_bytes=0,
    operations=("read", "write", "point_select", "inspect"),
    providers=("sceneio", "laspy"),
)

CASE_DEFINITIONS = {NPY_CASE.id: NPY_CASE, LAZ_CASE.id: LAZ_CASE}
NPY_FIXTURE_VERSION = "npy-depth-v2"
LAZ_FIXTURE_VERSION = "laz-pf2-origin-v2"


class CaseUnavailable(RuntimeError):
    """Raised when an optional provider or licensed source is unavailable."""


def case_definitions() -> dict[str, CaseDefinition]:
    """Return the array/point case registry."""

    return dict(CASE_DEFINITIONS)


def _tier_shape(tier: str) -> tuple[int, int, int]:
    if tier == "smoke":
        return (3, 32, 32)
    target = 1024 * 1024 * 1024 if tier == "stress" else 256 * 1024 * 1024
    frame_bytes = 640 * 480 * np.dtype(np.float32).itemsize
    frames = max(1, math.ceil(target / frame_bytes))
    return frames, 480, 640


def build_depth_stack(tier: str = "smoke") -> np.ndarray:
    """Build a C-contiguous float32 depth stack without random state."""

    frames, height, width = _tier_shape(tier)
    row = np.arange(height * width, dtype=np.float32).reshape(height, width)
    result = np.empty((frames, height, width), dtype=np.float32)
    for index in range(frames):
        result[index] = np.remainder(row + np.float32(index * 0.125), 4096.0) * 0.001
    return result


def _ensure_npy(cache: Path, tier: str) -> CaseArtifact:
    root = cache / NPY_CASE.id / tier
    root.mkdir(parents=True, exist_ok=True)
    path = root / "depth_stack.npy"
    marker = path.with_suffix(path.suffix + ".json")
    shape = _tier_shape(tier)
    current_version = None
    if marker.exists():
        try:
            current_version = json.loads(marker.read_text(encoding="utf-8")).get("version")
        except (OSError, json.JSONDecodeError):
            current_version = None
    if not path.exists() or current_version != NPY_FIXTURE_VERSION:
        np.save(path, build_depth_stack(tier), allow_pickle=False)
        marker.write_text(
            json.dumps({"version": NPY_FIXTURE_VERSION, "tier": tier}),
            encoding="utf-8",
        )
    # A stale cache from another tier is not silently reused.
    actual = np.load(path, mmap_mode="r", allow_pickle=False)
    if tuple(actual.shape) != shape or actual.dtype != np.dtype(np.float32):
        del actual
        gc.collect()
        actual = build_depth_stack(tier)
        np.save(path, actual, allow_pickle=False)
        marker.write_text(
            json.dumps({"version": NPY_FIXTURE_VERSION, "tier": tier}),
            encoding="utf-8",
        )
    else:
        del actual
    logical = int(np.prod(shape, dtype=np.int64) * np.dtype(np.float32).itemsize)
    return CaseArtifact(
        case_id=NPY_CASE.id,
        tier=tier,
        path=path,
        logical_bytes=logical,
        encoded_bytes=path.stat().st_size,
        metadata={
            "shape": list(shape),
            "dtype": "<f4",
            "order": "C",
            "reduction": "sum_float64",
        },
        acquisition_mode="synthetic_fallback",
        derivation={
            "seed": "arange-remainder-v1",
            "fixture_version": NPY_FIXTURE_VERSION,
            "geometry": [640, 480],
            "frames": shape[0],
        },
    )


def _laspy():
    try:
        import laspy
    except Exception as exc:  # pragma: no cover - optional provider
        raise CaseUnavailable("laspy/lazrs is unavailable") from exc
    return laspy


def build_laz_payload(count: int, seed: int = 29) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    # PointCloud stores relative float32 positions plus an f64 origin.  Keep
    # the georeference explicit so UTM-scale inputs do not lose centimetres
    # when converted to float32.
    origin = np.array([500_000.0, 4_000_000.0, 100.0], dtype=np.float64)
    positions = (rng.random((count, 3), dtype=np.float32) * 100.0).astype(np.float32)
    colors16 = rng.integers(0, 65_536, (count, 3), dtype=np.uint16)
    intensity = rng.integers(0, 65_536, count, dtype=np.uint16)
    return {
        "positions": positions,
        "origin": origin,
        "colors16": colors16,
        "intensity": intensity,
    }


def _write_laz(path: Path, payload: dict[str, np.ndarray]) -> None:
    _laspy_data(payload).write(path, do_compress=True)


def _laspy_data(payload: dict[str, np.ndarray]):
    """Build the provider-native value before a measured laspy write."""

    laspy = _laspy()
    header = laspy.LasHeader(version="1.2", point_format=2)
    header.scales = [0.001, 0.001, 0.001]
    origin = np.asarray(payload.get("origin", np.zeros(3)), dtype=np.float64)
    header.offsets = origin
    las = laspy.LasData(header)
    positions = np.asarray(payload["positions"], dtype=np.float32)
    absolute = positions.astype(np.float64) + origin
    las.x, las.y, las.z = absolute[:, 0], absolute[:, 1], absolute[:, 2]
    colors = payload["colors16"]
    las.red, las.green, las.blue = colors[:, 0], colors[:, 1], colors[:, 2]
    las.intensity = payload["intensity"]
    return las


def _payload_from_laz(path: Path) -> dict[str, np.ndarray]:
    las = _laspy().read(path)
    absolute = np.column_stack((las.x, las.y, las.z)).astype(np.float64)
    # Anchor at one encoded point and carry it separately in f64.  Casting
    # absolute UTM coordinates directly to float32 would erase low bits.
    origin = absolute[0] if len(absolute) else np.zeros(3, dtype=np.float64)
    return {
        "positions": (absolute - origin).astype(np.float32),
        "origin": origin,
        "colors16": np.column_stack((las.red, las.green, las.blue)).astype(np.uint16),
        "intensity": np.asarray(las.intensity, dtype=np.uint16),
    }


def _laz_coordinate_tolerance(payload: dict[str, np.ndarray]) -> float:
    """Bound LAS quantization plus float32 relative-coordinate rounding."""

    scale = 0.001
    local = np.asarray(payload["positions"], dtype=np.float32)
    if not local.size:
        return 0.5 * scale
    # ``spacing`` at one is a conservative upper bound for tiny values and
    # scales naturally with the largest local coordinate.
    ulp = float(np.max(np.spacing(np.maximum(np.abs(local), np.float32(1.0)))))
    return 0.5 * scale + ulp


def _sceneio_cloud(payload: dict[str, np.ndarray]):
    from sceneio import _core

    return _core.point_cloud(
        payload["positions"],
        colors16=payload["colors16"],
        intensity=payload["intensity"].astype(np.float32),
        intensity_range="u16",
        origin=np.asarray(payload.get("origin", np.zeros(3)), dtype=np.float64),
    )


def _ensure_laz(
    cache: Path,
    tier: str,
    source_path: Path | None,
) -> CaseArtifact:
    laspy = _laspy()
    root = cache / LAZ_CASE.id / tier
    root.mkdir(parents=True, exist_ok=True)
    path = root / "canonical.laz"
    marker = path.with_suffix(path.suffix + ".json")
    source_id = LAZ_CASE.source_id
    if tier == "smoke":
        count = 128
        marker_ok = False
        if marker.exists():
            try:
                marker_ok = (
                    json.loads(marker.read_text(encoding="utf-8")).get("version")
                    == LAZ_FIXTURE_VERSION
                )
            except (OSError, json.JSONDecodeError):
                marker_ok = False
        if not path.exists() or not marker_ok:
            _write_laz(path, build_laz_payload(count))
            marker.write_text(
                json.dumps({"version": LAZ_FIXTURE_VERSION, "tier": tier}),
                encoding="utf-8",
            )
        mode = "synthetic_fallback"
        derivation = {
            "seed": 29,
            "count": count,
            "profile": "las-1.2-pf2",
            "fixture_version": LAZ_FIXTURE_VERSION,
        }
    else:
        if source_path is None or not source_path.exists():
            raise CaseUnavailable("pdal_autzen_laz is not acquired; run acquire first")
        # The licensed source is a reference seed.  Canonicalization avoids
        # relying on source-specific LASzip VLRs that SceneIO intentionally
        # refuses, while retaining the source provenance in the artifact.
        marker_ok = False
        if marker.exists():
            try:
                marker_ok = (
                    json.loads(marker.read_text(encoding="utf-8")).get("version")
                    == LAZ_FIXTURE_VERSION
                )
            except (OSError, json.JSONDecodeError):
                marker_ok = False
        if not path.exists() or not marker_ok:
            _write_laz(path, _payload_from_laz(source_path))
            marker.write_text(
                json.dumps({"version": LAZ_FIXTURE_VERSION, "tier": tier}),
                encoding="utf-8",
            )
        with laspy.open(path) as handle:
            count = int(handle.header.point_count)
        mode = "derived_fixture"
        derivation = {
            "source_reason": "canonical SceneIO-compatible LAZ profile",
            "profile": "las-1.2-pf2",
            "count": count,
            "fixture_version": LAZ_FIXTURE_VERSION,
            "retained_fields": ["x", "y", "z", "intensity", "red", "green", "blue"],
            "omitted_source_fields": [
                "gps_time",
                "classification",
                "returns",
                "scan_angle",
                "user_data",
                "point_source_id",
                "extra_bytes",
                "waveform",
                "crs_metadata",
            ],
        }
    payload = _payload_from_laz(path)
    logical = int(payload["positions"].nbytes + payload["colors16"].nbytes + payload["intensity"].nbytes)
    return CaseArtifact(
        case_id=LAZ_CASE.id,
        tier=tier,
        path=path,
        logical_bytes=logical,
        encoded_bytes=path.stat().st_size,
        metadata={
            "count": int(count),
            "fields": ["x", "y", "z", "intensity", "red", "green", "blue"],
            "coordinate_frame": "unknown",
            "coordinate_representation": "relative-f32-plus-origin-f64",
            "coordinate_unit": "source LAS units; no coordinate conversion",
            "coordinate_scale": [0.001, 0.001, 0.001],
            "origin": payload["origin"].tolist(),
            "retained_fields": ["x", "y", "z", "intensity", "red", "green", "blue"],
        },
        source_id=(source_id if tier != "smoke" and source_path is not None else None),
        acquisition_mode=mode,
        derivation=derivation,
    )


def prepare_case(
    case_id: str,
    tier: str,
    cache: Path,
    sources: dict[str, Any] | None = None,
) -> CaseArtifact:
    """Construct/validate one common input outside the measured region."""

    if case_id == NPY_CASE.id:
        return _ensure_npy(cache, tier)
    if case_id == LAZ_CASE.id:
        source = (sources or {}).get(LAZ_CASE.source_id)
        source_path = getattr(source, "path", source)
        return _ensure_laz(cache, tier, Path(source_path) if source_path else None)
    raise KeyError(f"unknown large benchmark case {case_id!r}")


def _npy_scan(path: Path) -> float:
    values = np.load(path, mmap_mode="r", allow_pickle=False)
    # This exact reduction is shared by SceneIO and NumPy full_scan rows.
    return float(np.sum(np.asarray(values), dtype=np.float64))


def _npy_open(provider: str, path: Path, sceneio_module=None):
    if provider == "numpy":
        return np.load(path, mmap_mode="r", allow_pickle=False)
    if sceneio_module is None:
        import sceneio as sceneio_module

    return sceneio_module.read(path, format="npy")


def _npy_inspect(path: Path) -> dict[str, Any]:
    """Inspect the NPY header without decoding the payload.

    NumPy is the independent reference provider for this operation.  Loading
    with ``mmap_mode='r'`` parses the header and keeps the payload lazy, which
    mirrors the SceneIO inspect contract without making the two rows aliases.
    """

    values = np.load(path, mmap_mode="r", allow_pickle=False)
    return {
        "shape": list(values.shape),
        "dtype": str(values.dtype),
        "order": "F" if values.flags.f_contiguous and not values.flags.c_contiguous else "C",
    }


def _sceneio_npy_inspect(path: Path) -> dict[str, Any]:
    import sceneio

    result = sceneio.inspect(path, format="npy")
    return {
        "shape": list(result.shape),
        "dtype": str(result.dtype),
        "order": "F" if bool(result.metadata.get("fortran_order")) else "C",
    }


def _operation_paths(request: dict[str, Any], extension: str) -> list[Path]:
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
        for index in range(int(request["runs"]) + 3)
    ]


def _remove_output(value: object) -> None:
    if not isinstance(value, Path):
        return
    nonempty = value.is_file() and value.stat().st_size > 0
    try:
        if value.is_dir():
            shutil.rmtree(value)
        elif value.exists():
            value.unlink()
    except OSError:
        # Cleanup is outside the measured interval. The parent performs a
        # second bounded cleanup and records any remaining path.
        return
    if not nonempty:
        raise RuntimeError("measured writer produced an empty output")


def _measure(fn, request: dict[str, Any], *, after_call=None):
    mode = str(request.get("mode", "combined"))
    if mode == "timing":
        return measure_timing(
            fn,
            runs=int(request.get("runs", 3)),
            cache_mode=str(request.get("cache_mode", "warm")),
            after_call=after_call,
        )
    if mode == "memory":
        return measure_memory(
            fn,
            cache_mode=str(request.get("cache_mode", "warm")),
            after_call=after_call,
        )
    return measure_callable(
        fn,
        runs=int(request.get("runs", 3)),
        cache_mode=str(request.get("cache_mode", "warm")),
        after_call=after_call,
    )


def execute_case(request: dict[str, Any]) -> dict[str, Any]:
    """Execute one worker request and return JSON-safe measurements."""

    artifact = CaseArtifact.from_dict(dict(request["artifact"]))
    provider = str(request["provider"])
    operation = str(request["operation"])
    output_paths: list[Path] = []
    cursor = 0

    if artifact.case_id == NPY_CASE.id:
        path = artifact.path
        # Bind optional providers before entering the measured callable.  A
        # fresh worker should charge imports once, outside timing/RSS samples,
        # so provider rows measure I/O rather than import/cache setup.
        sceneio_module = None
        if provider == "sceneio":
            import sceneio as sceneio_module

        if operation == "map_open":
            def fn():
                return _npy_open(provider, path, sceneio_module)

        elif operation == "full_scan":
            def fn():
                return _npy_scan(path) if provider == "numpy" else _sceneio_npy_scan(
                    path, sceneio_module
                )

        elif operation == "inspect":
            def fn():
                return (
                    _npy_inspect(path)
                    if provider == "numpy"
                    else _sceneio_npy_inspect(path)
                )

        elif operation == "write":
            values = build_depth_stack(artifact.tier)
            output_paths = _operation_paths(request, ".npy")

            def fn():
                nonlocal cursor
                destination = output_paths[cursor]
                cursor += 1
                if provider == "numpy":
                    np.save(destination, values, allow_pickle=False)
                else:
                    sceneio_module.write(values, destination, format="npy")
                return destination

        else:
            raise ValueError(f"unsupported NPY operation {operation!r}")
        measurement = _measure(
            fn,
            request,
            after_call=_remove_output if operation == "write" else None,
        )
        if operation == "write" and request.get("mode", "combined") != "memory":
            output_paths = [fn()]
        elif operation == "write":
            output_paths = []
        diagnostic = {}
        if operation == "full_scan":
            diagnostic["reduction"] = _npy_scan(path) if provider == "numpy" else _sceneio_npy_scan(path)
        if operation == "inspect":
            diagnostic = (
                _npy_inspect(path)
                if provider == "numpy"
                else _sceneio_npy_inspect(path)
            )
    elif artifact.case_id == LAZ_CASE.id:
        path = artifact.path
        laspy_module = _laspy() if provider == "laspy" else None
        sceneio_module = None
        if provider == "sceneio":
            import sceneio as sceneio_module
        if operation == "read":
            if provider == "laspy":
                def fn():
                    return laspy_module.read(path)

            else:
                def fn():
                    return sceneio_module.read(path, format="laz")

        elif operation == "point_select":
            stop = min(256, int(artifact.metadata["count"]))
            if provider == "sceneio":
                def fn():
                    return sceneio_module.read_partial(path, points=(0, stop), format="laz")

            else:
                def fn():
                    return laspy_module.read(path).points[:stop]

        elif operation == "inspect":
            if provider == "sceneio":
                def fn():
                    return sceneio_module.inspect(path, format="laz")

            else:
                def fn():
                    with laspy_module.open(path) as handle:
                        dimensions = set(handle.header.point_format.dimension_names)
                        return {
                            "count": int(handle.header.point_count),
                            "shape": [int(handle.header.point_count), 3],
                            "dtype": "float32",
                            "point_format": int(handle.header.point_format.id),
                            "has_color": {"red", "green", "blue"} <= dimensions,
                            "has_intensity": "intensity" in dimensions,
                        }

        elif operation == "write":
            if provider == "sceneio":
                values = sceneio_module.read(path, format="laz")
            else:
                values = _laspy_data(_payload_from_laz(path))
            output_paths = _operation_paths(request, ".laz")

            def fn():
                nonlocal cursor
                destination = output_paths[cursor]
                cursor += 1
                if provider == "laspy":
                    values.write(destination, do_compress=True)
                else:
                    sceneio_module.write(values, destination, format="laz")
                return destination

        else:
            raise ValueError(f"unsupported LAZ operation {operation!r}")
        measurement = _measure(
            fn,
            request,
            after_call=_remove_output if operation == "write" else None,
        )
        if operation == "write" and request.get("mode", "combined") != "memory":
            output_paths = [fn()]
        elif operation == "write":
            output_paths = []
        diagnostic = {}
        if operation == "inspect":
            inspected = fn()
            if isinstance(inspected, dict):
                diagnostic = inspected
            else:
                metadata = inspected.metadata
                diagnostic = {
                    "count": int(inspected.count),
                    "shape": list(inspected.shape),
                    "dtype": str(inspected.dtype),
                    "point_format": int(metadata["point_format"]),
                    "has_color": bool(metadata["has_color"]),
                    "has_intensity": bool(metadata["has_intensity"]),
                }
        elif operation == "point_select":
            selected = fn()
            diagnostic = {
                "count": int(
                    selected.num_points
                    if hasattr(selected, "num_points")
                    else len(selected)
                )
            }
    else:
        raise KeyError(artifact.case_id)

    return {
        "measurement": measurement.to_dict(),
        "diagnostic": diagnostic,
        "output_paths": [str(item) for item in output_paths],
    }


def _sceneio_npy_scan(path: Path, sceneio_module=None) -> float:
    if sceneio_module is None:
        import sceneio as sceneio_module

    values = sceneio_module.read(path, format="npy")
    return float(np.sum(np.asarray(values), dtype=np.float64))


def common_read_check(artifact: CaseArtifact) -> dict[str, Any]:
    """Compare SceneIO against the independent common-file providers.

    This check intentionally runs outside timed workers and is included in the
    result document as a correctness gate for each common input fixture.
    """

    if artifact.case_id == NPY_CASE.id:
        import sceneio

        scene_values = sceneio.read(artifact.path, format="npy")
        numpy_values = np.load(artifact.path, mmap_mode="r", allow_pickle=False)
        scene_array = np.asarray(scene_values)
        equal = (
            scene_array.shape == numpy_values.shape
            and scene_array.dtype == numpy_values.dtype
            and scene_array.flags.c_contiguous == numpy_values.flags.c_contiguous
            and scene_array.flags.f_contiguous == numpy_values.flags.f_contiguous
            and np.array_equal(scene_array, numpy_values)
        )
        scene_reduction = float(np.sum(scene_array, dtype=np.float64))
        numpy_reduction = float(np.sum(np.asarray(numpy_values), dtype=np.float64))
        equal = equal and scene_reduction == numpy_reduction
        return {
            "status": "pass" if equal else "fail",
            "profile": "shape_dtype_fixed_float64_reduction",
            "shape": list(numpy_values.shape),
            "dtype": str(numpy_values.dtype),
            "reduction": [scene_reduction, numpy_reduction],
        }
    if artifact.case_id == LAZ_CASE.id:
        import sceneio

        scene_values = sceneio.read(artifact.path, format="laz")
        payload = _payload_from_laz(artifact.path)
        positions = np.asarray(scene_values.positions, dtype=np.float64) + np.asarray(
            scene_values.origin, dtype=np.float64
        )
        expected_positions = payload["positions"].astype(np.float64) + payload["origin"]
        colors = np.asarray(scene_values.colors16)
        intensity = np.asarray(scene_values.intensities)
        equal = (
            np.allclose(
                positions,
                expected_positions,
                rtol=0,
                atol=_laz_coordinate_tolerance(payload),
            )
            and np.array_equal(colors, payload["colors16"])
            and np.array_equal(intensity, payload["intensity"])
        )
        return {
            "status": "pass" if equal else "fail",
            "profile": "laspy_sceneio_scale_and_integer_attributes",
            "count": int(payload["positions"].shape[0]),
        }
    raise KeyError(artifact.case_id)


def compare_case(artifact: CaseArtifact, left: Path, right: Path) -> dict[str, Any]:
    """Semantic cross-read comparison for two provider-written artifacts."""

    if artifact.case_id == NPY_CASE.id:
        left_values = np.load(left, mmap_mode="r", allow_pickle=False)
        right_values = np.load(right, mmap_mode="r", allow_pickle=False)
        equal = (
            left_values.shape == right_values.shape
            and left_values.dtype == right_values.dtype
            and left_values.flags.c_contiguous == right_values.flags.c_contiguous
            and left_values.flags.f_contiguous == right_values.flags.f_contiguous
            and np.array_equal(left_values, right_values)
        )
        return {
            "status": "pass" if equal else "fail",
            "profile": "shape_dtype_order_exact",
            "shape": list(left_values.shape),
            "dtype": str(left_values.dtype),
        }
    if artifact.case_id == LAZ_CASE.id:
        left_payload = _payload_from_laz(left)
        right_payload = _payload_from_laz(right)
        left_absolute = left_payload["positions"].astype(np.float64) + left_payload["origin"]
        right_absolute = right_payload["positions"].astype(np.float64) + right_payload["origin"]
        tolerance = max(
            _laz_coordinate_tolerance(left_payload),
            _laz_coordinate_tolerance(right_payload),
        )
        equal = (
            left_payload["positions"].shape == right_payload["positions"].shape
            and np.allclose(left_absolute, right_absolute, rtol=0, atol=tolerance)
            and np.array_equal(left_payload["colors16"], right_payload["colors16"])
            and np.array_equal(left_payload["intensity"], right_payload["intensity"])
        )
        return {
            "status": "pass" if equal else "fail",
            "profile": "count_integer_attributes_scale_half_step",
            "count": int(left_payload["positions"].shape[0]),
        }
    raise KeyError(artifact.case_id)


def cross_read_matrix(
    artifact: CaseArtifact, outputs: dict[str, Path | None]
) -> list[dict[str, Any]]:
    """Read every provider output with every case reader and compare to common input."""

    rows: list[dict[str, Any]] = []
    providers = CASE_DEFINITIONS[artifact.case_id].providers
    if artifact.case_id == NPY_CASE.id:
        expected = np.load(artifact.path, mmap_mode="r", allow_pickle=False)
        for writer in providers:
            output = outputs.get(writer)
            for reader in providers:
                row = {
                    "case_id": artifact.case_id,
                    "kind": "provider_output_cross_read",
                    "writer_provider": writer,
                    "reader_provider": reader,
                    "profile": "shape_dtype_order_exact",
                }
                if output is None or not output.is_file() or output.stat().st_size == 0:
                    rows.append({**row, "status": "fail", "error": "writer output is missing or empty"})
                    continue
                try:
                    actual = _npy_open(reader, output)
                    actual_array = np.asarray(actual)
                    output_order = _npy_inspect(output)["order"]
                    equal = (
                        actual_array.shape == expected.shape
                        and actual_array.dtype == expected.dtype
                        and output_order == artifact.metadata["order"]
                        and actual_array.flags.c_contiguous
                        == expected.flags.c_contiguous
                        and actual_array.flags.f_contiguous
                        == expected.flags.f_contiguous
                        and np.array_equal(actual_array, expected)
                    )
                    rows.append({**row, "status": "pass" if equal else "fail"})
                except Exception as exc:
                    rows.append({**row, "status": "fail", "error": f"{type(exc).__name__}: {exc}"})
        return rows

    if artifact.case_id == LAZ_CASE.id:
        expected = _payload_from_laz(artifact.path)
        expected_absolute = expected["positions"].astype(np.float64) + expected["origin"]
        tolerance = _laz_coordinate_tolerance(expected)
        for writer in providers:
            output = outputs.get(writer)
            for reader in providers:
                row = {
                    "case_id": artifact.case_id,
                    "kind": "provider_output_cross_read",
                    "writer_provider": writer,
                    "reader_provider": reader,
                    "profile": "absolute_xyz_half_scale_plus_f32_ulp_and_integer_attributes",
                }
                if output is None or not output.is_file() or output.stat().st_size == 0:
                    rows.append({**row, "status": "fail", "error": "writer output is missing or empty"})
                    continue
                try:
                    if reader == "laspy":
                        actual = _payload_from_laz(output)
                        actual_absolute = (
                            actual["positions"].astype(np.float64) + actual["origin"]
                        )
                        colors = actual["colors16"]
                        intensity = actual["intensity"]
                        tolerance_value = max(tolerance, _laz_coordinate_tolerance(actual))
                    else:
                        import sceneio

                        cloud = sceneio.read(output, format="laz")
                        actual_absolute = np.asarray(
                            cloud.positions, dtype=np.float64
                        ) + np.asarray(cloud.origin, dtype=np.float64)
                        colors = np.asarray(cloud.colors16)
                        intensity = np.asarray(cloud.intensities, dtype=np.uint16)
                        tolerance_value = tolerance
                    equal = (
                        actual_absolute.shape == expected_absolute.shape
                        and np.allclose(
                            actual_absolute,
                            expected_absolute,
                            rtol=0.0,
                            atol=tolerance_value,
                        )
                        and np.array_equal(colors, expected["colors16"])
                        and np.array_equal(intensity, expected["intensity"])
                    )
                    rows.append({**row, "status": "pass" if equal else "fail"})
                except Exception as exc:
                    rows.append({**row, "status": "fail", "error": f"{type(exc).__name__}: {exc}"})
        return rows
    raise KeyError(artifact.case_id)


def partial_read_check(artifact: CaseArtifact) -> dict[str, Any]:
    """Verify LAZ point selection against the independent full-file slice."""

    if artifact.case_id != LAZ_CASE.id:
        return {
            "status": "pass",
            "profile": "not_applicable",
        }
    import sceneio

    stop = min(256, int(artifact.metadata["count"]))
    selected = sceneio.read_partial(
        artifact.path,
        points=(0, stop),
        format="laz",
    )
    expected = _payload_from_laz(artifact.path)
    actual_absolute = np.asarray(selected.positions, dtype=np.float64) + np.asarray(
        selected.origin, dtype=np.float64
    )
    expected_absolute = (
        expected["positions"][:stop].astype(np.float64) + expected["origin"]
    )
    equal = (
        int(selected.num_points) == stop
        and np.allclose(
            actual_absolute,
            expected_absolute,
            rtol=0.0,
            atol=_laz_coordinate_tolerance(expected),
        )
        and np.array_equal(np.asarray(selected.colors16), expected["colors16"][:stop])
        and np.array_equal(
            np.asarray(selected.intensities, dtype=np.uint16),
            expected["intensity"][:stop],
        )
    )
    return {
        "status": "pass" if equal else "fail",
        "profile": "sceneio_point_window_equals_laspy_full_slice",
        "count": stop,
    }


__all__ = [
    "CASE_DEFINITIONS",
    "LAZ_CASE",
    "NPY_CASE",
    "CaseUnavailable",
    "build_depth_stack",
    "build_laz_payload",
    "case_definitions",
    "common_read_check",
    "compare_case",
    "cross_read_matrix",
    "execute_case",
    "partial_read_check",
    "prepare_case",
]
