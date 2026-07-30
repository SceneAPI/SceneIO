"""Complete comparison-provider qualification for the I/O benchmark."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS


@dataclass(frozen=True, slots=True)
class ComparisonQualification:
    """Independent comparison coverage for one repository-owned codec."""

    runner_kind: str
    mode: str
    provider: str
    operations: tuple[str, ...]
    verification_path: str
    unverified_property: str | None = None


def _timed(
    provider: str,
    verification_path: str,
    *,
    runner_kind: str = "spec",
    operations: tuple[str, ...] = ("encode", "decode"),
) -> ComparisonQualification:
    return ComparisonQualification(
        runner_kind=runner_kind,
        mode="timed",
        provider=provider,
        operations=operations,
        verification_path=verification_path,
    )


def _exemption(
    unverified_property: str,
    verification_path: str,
    *,
    runner_kind: str = "spec",
) -> ComparisonQualification:
    return ComparisonQualification(
        runner_kind=runner_kind,
        mode="reviewed_exemption",
        provider="independent parity suite",
        operations=(),
        verification_path=verification_path,
        unverified_property=unverified_property,
    )


COMPARISON_QUALIFICATIONS = MappingProxyType(
    {
        "pfm": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_pfm.py",
        ),
        "colmap_sparse": _exemption(
            "independent benchmark directory encode/decode throughput",
            "tests/codecs/test_colmap.py",
            runner_kind="directory",
        ),
        "gaussian_ply": _timed(
            "gsply",
            "bench/io_bench/oracles/splats.py",
        ),
        "compressed_ply": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_compressed_ply.py",
        ),
        "sog": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_sog.py",
        ),
        "ksplat": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_ksplat.py",
        ),
        "ply_mesh": _timed(
            "trimesh",
            "bench/io_bench/oracles/meshes.py",
        ),
        "obj": _timed(
            "trimesh",
            "bench/io_bench/oracles/meshes.py",
        ),
        "stl": _timed(
            "trimesh",
            "bench/io_bench/oracles/meshes.py",
        ),
        "off": _timed(
            "trimesh",
            "bench/io_bench/oracles/meshes.py",
        ),
        "gltf": _timed(
            "trimesh",
            "bench/io_bench/oracles/meshes.py",
            runner_kind="special",
        ),
        "glb": _timed(
            "trimesh",
            "bench/io_bench/oracles/meshes.py",
        ),
        "ply": _timed(
            "Open3D",
            "bench/io_bench/oracles/points.py",
        ),
        "pcd": _timed(
            "Open3D",
            "bench/io_bench/oracles/points.py",
        ),
        "spz": _timed(
            "gsply",
            "bench/io_bench/oracles/splats.py",
        ),
        "transforms_json": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_transforms_json.py",
        ),
        "tum": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_pose_text.py",
        ),
        "kitti": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_pose_text.py",
        ),
        "euroc_state": _timed(
            "independent CSV/NumPy implementation",
            "bench/io_bench/oracles/reconstruction.py",
        ),
        "opencv_yaml": _timed(
            "PyYAML",
            "bench/io_bench/oracles/calibration.py",
        ),
        "opencv_xml": _timed(
            "stdlib ElementTree",
            "bench/io_bench/oracles/calibration.py",
        ),
        "ros_camera_info": _timed(
            "PyYAML",
            "bench/io_bench/oracles/calibration.py",
        ),
        "kalibr": _timed(
            "PyYAML",
            "bench/io_bench/oracles/calibration.py",
        ),
        "g2o": _timed(
            "independent text/NumPy implementation",
            "bench/io_bench/oracles/reconstruction.py",
        ),
        "colmap_db": _timed(
            "stdlib sqlite3 reference implementation",
            "bench/io_bench/runner.py",
            runner_kind="special",
            operations=("encode", "decode", "inspect", "partial"),
        ),
        "npy": _timed(
            "NumPy",
            "bench/io_bench/oracles/arrays.py",
        ),
        "npz": _timed(
            "NumPy",
            "bench/io_bench/oracles/arrays.py",
        ),
        "safetensors": _timed(
            "safetensors",
            "bench/io_bench/oracles/arrays.py",
        ),
        "netpbm": _timed(
            "imageio or Pillow",
            "bench/io_bench/oracles/images.py",
        ),
        "png": _timed(
            "Pillow",
            "bench/io_bench/oracles/images.py",
        ),
        "jpeg": _timed(
            "Pillow",
            "bench/io_bench/oracles/images.py",
        ),
        "bmp": _timed(
            "Pillow",
            "bench/io_bench/oracles/images.py",
        ),
        "tga": _timed(
            "Pillow",
            "bench/io_bench/oracles/images.py",
        ),
        "hdr": _exemption(
            (
                "portable independent benchmark encode/decode throughput "
                "for Radiance HDR"
            ),
            "tests/codecs/test_hdr.py",
        ),
        "exr": _timed(
            "OpenEXR",
            "bench/io_bench/oracles/images.py",
        ),
        "webp": _timed(
            "Pillow",
            "bench/io_bench/oracles/images.py",
        ),
        "y4m": _timed(
            "independent NumPy implementation",
            "bench/io_bench/oracles/sequences.py",
        ),
        "animated_webp": _timed(
            "Pillow",
            "bench/io_bench/oracles/sequences.py",
        ),
        "apng": _timed(
            "Pillow + specification-derived chunk oracle",
            "bench/io_bench/oracles/sequences.py",
        ),
        "image_sequence": _exemption(
            "independent benchmark directory encode/decode throughput",
            "tests/codecs/test_image_sequence.py",
            runner_kind="directory",
        ),
        "colmap_sparse_txt": _exemption(
            "independent benchmark directory encode/decode throughput",
            "tests/codecs/test_colmap_txt.py",
            runner_kind="directory",
        ),
        "xyz": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_xyz.py",
        ),
        "pts": _timed(
            "independent text/NumPy implementation",
            "bench/io_bench/oracles/points.py",
        ),
        "las": _timed(
            "laspy",
            "bench/io_bench/oracles/points.py",
        ),
        "laz": _timed(
            "laspy with lazrs",
            "bench/io_bench/oracles/points.py",
        ),
        "flo": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_flo.py",
        ),
        "dmb": _timed(
            "independent struct/NumPy implementation",
            "bench/io_bench/oracles/arrays.py",
        ),
        "bundler": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_bundler.py",
        ),
        "bal": _timed(
            "independent text/NumPy implementation",
            "bench/io_bench/oracles/reconstruction.py",
        ),
        "nvm": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_nvm.py",
        ),
        "openmvg": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_openmvg.py",
        ),
        "splat": _exemption(
            "independent benchmark encode/decode throughput",
            "tests/codecs/test_splat.py",
        ),
        "colmap_mvs_depth": _timed(
            "independent struct/NumPy implementation",
            "bench/io_bench/oracles/dense.py",
        ),
        "colmap_mvs_normal": _timed(
            "independent struct/NumPy implementation",
            "bench/io_bench/oracles/dense.py",
        ),
        "colmap_mvs_consistency": _timed(
            "independent struct/NumPy implementation",
            "bench/io_bench/oracles/dense.py",
        ),
        "colmap_fused_visibility": _timed(
            "independent struct/NumPy implementation",
            "bench/io_bench/oracles/dense.py",
        ),
        "hdf5": _timed(
            "h5py",
            "bench/io_bench/oracles/containers.py",
            runner_kind="path",
        ),
        "hloc_features": _timed(
            "h5py with documented hloc feature layout",
            "bench/io_bench/oracles/containers.py",
            runner_kind="path",
        ),
        "hloc_matches": _timed(
            "h5py with documented hloc match layout",
            "bench/io_bench/oracles/containers.py",
            runner_kind="path",
        ),
        "zarr": _timed(
            "zarr-python",
            "bench/io_bench/oracles/containers.py",
            runner_kind="path",
        ),
    }
)


def validate_benchmark_coverage(format_ids) -> tuple[str, ...]:
    """Require the assembled sweep to cover every repository built-in once."""

    observed = tuple(format_ids)
    duplicates = sorted(
        format_id
        for format_id in set(observed)
        if observed.count(format_id) > 1
    )
    missing = sorted(set(CANONICAL_BUILTIN_IDS) - set(observed))
    unexpected = sorted(set(observed) - set(CANONICAL_BUILTIN_IDS))
    if duplicates or missing or unexpected:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        if duplicates:
            details.append("duplicates=" + ",".join(duplicates))
        raise RuntimeError(
            "repository benchmark coverage differs from canonical built-ins: "
            + "; ".join(details)
        )
    return observed


def validate_strict_providers(
    specs,
    *,
    special_available: dict[str, bool],
    path_specs=(),
) -> None:
    """Fail before measurement when a timed comparison is unavailable."""

    by_id = {spec.id: spec for spec in specs}
    path_by_id = {spec.id: spec for spec in path_specs}
    unavailable = []
    for format_id, qualification in COMPARISON_QUALIFICATIONS.items():
        if qualification.mode != "timed":
            continue
        if qualification.runner_kind == "spec":
            spec = by_id.get(format_id)
            available = (
                spec is not None
                and spec.ow is not None
                and spec.orr is not None
            )
        elif qualification.runner_kind == "special":
            available = special_available.get(format_id, False)
        elif qualification.runner_kind == "path":
            spec = path_by_id.get(format_id)
            available = (
                spec is not None
                and spec.ow is not None
                and spec.orr is not None
            )
        else:
            available = False
        if not available:
            unavailable.append(
                f"{format_id} ({qualification.provider})"
            )
    if unavailable:
        raise RuntimeError(
            "strict comparison providers unavailable: "
            + ", ".join(unavailable)
        )


def measure_spec_comparison(
    spec,
    payload,
    payload_mb,
    runs,
    *,
    strict: bool,
    measure,
    optional_try,
) -> tuple[float | None, float | None]:
    """Measure one spec comparison without masking strict-mode failures."""

    qualification = COMPARISON_QUALIFICATIONS[spec.id]
    if qualification.mode != "timed":
        return None, None
    if payload is None:
        if strict:
            raise RuntimeError(
                f"strict comparison payload unavailable for {spec.id!r}"
            )
        return None, None
    if strict:
        encoded = bytes(spec.ow(payload))
        write_time = measure(lambda: spec.ow(payload), runs)[0]
        read_time = measure(lambda: spec.orr(encoded), runs)[0]
        return payload_mb / write_time, payload_mb / read_time
    if spec.ow is None or spec.orr is None:
        return None, None
    encoded = optional_try(lambda: bytes(spec.ow(payload)))
    if encoded is None:
        return None, None
    measured_write = optional_try(
        lambda: measure(lambda: spec.ow(payload), runs)
    )
    measured_read = optional_try(
        lambda: measure(lambda: spec.orr(encoded), runs)
    )
    return (
        payload_mb / measured_write[0] if measured_write else None,
        payload_mb / measured_read[0] if measured_read else None,
    )


def validate_dense_oracle_parity(
    spec,
    record,
    payload,
    native_encoded: bytes,
) -> None:
    """Run the dense family's independent cross-differential check."""

    from bench.io_bench.families.dense import (
        validate_dense_oracle_parity as validate,
    )

    validate(spec, record, payload, native_encoded)


def validate_strict_results(results) -> None:
    """Require every declared strict comparison metric in the final sweep."""

    by_id = {result.get("codec"): result for result in results}
    operation_keys = {
        "encode": ("oracle_write_mbps",),
        "decode": ("oracle_read_mbps",),
        "inspect": ("oracle_inspect_ms",),
        "partial": ("oracle_image_ms", "oracle_pair_ms"),
    }
    missing = []
    for format_id, qualification in COMPARISON_QUALIFICATIONS.items():
        if qualification.mode != "timed":
            continue
        result = by_id.get(format_id)
        if result is None:
            missing.append(f"{format_id}:row")
            continue
        if result.get("error"):
            missing.append(f"{format_id}:successful-row")
            continue
        for operation in qualification.operations:
            for key in operation_keys[operation]:
                value = result.get(key)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    missing.append(f"{format_id}:{key}")
    spz_profiles = (by_id.get("spz") or {}).get("spz_profiles")
    expected_spz_profiles = {
        "legacy_v3_gzip": {
            "version": 3,
            "fractional_bits": 12,
            "zstd_level": None,
            "container_magic": "1f8b",
            "backend": "miniz",
        },
        "ngsp_v4_zstd": {
            "version": 4,
            "fractional_bits": 12,
            "zstd_level": 12,
            "container_magic": "4e475350",
            "backend": "zstd",
        },
    }
    if not isinstance(spz_profiles, dict):
        missing.append("spz:profiles")
    else:
        if set(spz_profiles) != set(expected_spz_profiles):
            missing.append("spz:profile-set")
        for profile_id, expected in expected_spz_profiles.items():
            profile = spz_profiles.get(profile_id)
            if not isinstance(profile, dict):
                missing.append(f"spz:{profile_id}")
                continue
            if any(profile.get(key) != value for key, value in expected.items()):
                missing.append(f"spz:{profile_id}:settings")
            for metric in ("file_mb", "write_mbps", "read_mbps"):
                value = profile.get(metric)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    missing.append(f"spz:{profile_id}:{metric}")
    if missing:
        raise RuntimeError(
            "strict comparison evidence incomplete: "
            + ", ".join(missing)
        )


def _validate_qualification_manifest() -> None:
    canonical = set(CANONICAL_BUILTIN_IDS)
    if set(COMPARISON_QUALIFICATIONS) != canonical:
        raise RuntimeError(
            "comparison qualifications must cover the canonical built-ins"
        )
    for format_id, qualification in COMPARISON_QUALIFICATIONS.items():
        if qualification.runner_kind not in {
            "spec",
            "special",
            "directory",
            "path",
        }:
            raise RuntimeError(
                f"invalid runner kind for {format_id!r}"
            )
        if qualification.mode not in {"timed", "reviewed_exemption"}:
            raise RuntimeError(
                f"invalid comparison mode for {format_id!r}"
            )
        if qualification.mode == "timed" and (
            not qualification.operations
            or not set(qualification.operations)
            <= {"encode", "decode", "inspect", "partial"}
            or qualification.unverified_property is not None
            or qualification.runner_kind == "directory"
        ):
            raise RuntimeError(
                f"inconsistent timed comparison for {format_id!r}"
            )
        if qualification.mode == "reviewed_exemption" and (
            qualification.operations
            or not qualification.unverified_property
        ):
            raise RuntimeError(
                f"inconsistent reviewed exemption for {format_id!r}"
            )


_validate_qualification_manifest()


__all__ = [
    "COMPARISON_QUALIFICATIONS",
    "ComparisonQualification",
    "measure_spec_comparison",
    "validate_benchmark_coverage",
    "validate_strict_providers",
    "validate_strict_results",
]
