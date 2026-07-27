"""Benchmark specifications for the complete splat codec family."""

from __future__ import annotations

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


__all__ = ["build_splat_specs"]
