"""Benchmark specifications for the point-cloud codec family."""

from __future__ import annotations

from bench.io_bench.fixtures.points import _pc, _pc_laz, _pc_ply
from bench.io_bench.model import Spec
from bench.io_bench.oracles.points import (
    _laspy_laz_w,
    _laspy_r,
    _laspy_w,
    _open3d_pcd_r,
    _open3d_pcd_w,
    _open3d_ply_r,
    _open3d_ply_w,
    _pts_oracle_read,
    _pts_oracle_write,
    laspy,
    o3d,
)
from sceneio import _core


def build_point_specs(scale):
    points = max(1, int(1_000_000 * scale))
    return [
        Spec(
            "xyz",
            lambda: _pc(points, False),
            _core.write_xyz,
            _core.read_xyz,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "pts",
            lambda: _pc(points, False),
            _core.write_pts,
            _core.read_pts,
            _pts_oracle_write,
            _pts_oracle_read,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "ply",
            lambda: _pc_ply(points),
            _core.write_ply,
            _core.read_ply,
            (_open3d_ply_w if o3d else None),
            (_open3d_ply_r if o3d else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "pcd",
            lambda: _pc_ply(points),
            _core.write_pcd,
            _core.read_pcd,
            (_open3d_pcd_w if o3d else None),
            (_open3d_pcd_r if o3d else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "las",
            lambda: _pc_laz(points),
            lambda pc: _core.write_las(pc, 0.001),
            _core.read_las,
            (_laspy_w if laspy else None),
            (_laspy_r if laspy else None),
            lambda rec, p: p["positions"].nbytes,
        ),
        Spec(
            "laz",
            lambda: _pc_laz(points),
            lambda pc: _core.write_laz(pc, 0.001),
            _core.read_laz,
            (_laspy_laz_w if laspy else None),
            (_laspy_r if laspy else None),
            lambda rec, p: p["positions"].nbytes,
        ),
    ]


__all__ = ["build_point_specs"]
