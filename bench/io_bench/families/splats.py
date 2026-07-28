"""Benchmark specifications for the complete splat codec family."""

from __future__ import annotations

from types import MappingProxyType

from bench.io_bench.fixtures.splats import _gauss
from bench.io_bench.model import Spec
from bench.io_bench.oracles.splats import (
    _gsply_ply_r,
    _gsply_ply_w,
    _gsply_spz_r,
    _gsply_spz_w,
    gsply,
)
from sceneio import _core

SPZ_PROFILE_SETTINGS = MappingProxyType(
    {
        "legacy_v3_gzip": MappingProxyType(
            {
                "version": 3,
                "fractional_bits": 12,
                "zstd_level": None,
                "container_magic": "1f8b",
                "backend": "miniz",
            }
        ),
        "ngsp_v4_zstd": MappingProxyType(
            {
                "version": 4,
                "fractional_bits": 12,
                "zstd_level": 12,
                "container_magic": "4e475350",
                "backend": "zstd",
            }
        ),
    }
)


def write_spz_profile(cloud, profile: str):
    """Encode one explicitly selected SPZ benchmark profile."""

    settings = SPZ_PROFILE_SETTINGS[profile]
    return _core.write_spz(
        cloud,
        version=settings["version"],
        fractional_bits=settings["fractional_bits"],
        zstd_level=settings["zstd_level"] or 12,
    )


def build_splat_specs(scale):
    gaussians = max(1, int(200_000 * scale))
    return [
        Spec(
            "gaussian_ply",
            lambda: _gauss(gaussians),
            _core.write_gaussian_ply,
            _core.read_gaussian_ply,
            (_gsply_ply_w if gsply else None),
            (_gsply_ply_r if gsply else None),
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "compressed_ply",
            lambda: _gauss(gaussians),
            _core.write_compressed_ply,
            _core.read_compressed_ply,
            None,
            None,
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "sog",
            lambda: _gauss(gaussians),
            _core.write_sog,
            _core.read_sog,
            None,
            None,
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "ksplat",
            lambda: _gauss(gaussians),
            _core.write_ksplat,
            _core.read_ksplat,
            None,
            None,
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "spz",
            lambda: _gauss(gaussians),
            _core.write_spz,
            _core.read_spz,
            (_gsply_spz_w if gsply else None),
            (_gsply_spz_r if gsply else None),
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "splat",
            lambda: _gauss(gaussians),
            _core.write_splat,
            _core.read_splat,
            None,
            None,
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
    ]


__all__ = [
    "SPZ_PROFILE_SETTINGS",
    "build_splat_specs",
    "write_spz_profile",
]
