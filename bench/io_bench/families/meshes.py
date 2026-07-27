"""Benchmark specifications for the buffer-backed mesh codec family."""

from __future__ import annotations

from bench.io_bench.fixtures.meshes import (
    _mesh_obj,
    _mesh_off,
    _mesh_ply,
    _mesh_scene,
    _mesh_stl,
)
from bench.io_bench.model import Spec
from bench.io_bench.oracles.meshes import (
    _trimesh_glb_r,
    _trimesh_glb_w,
    _trimesh_obj_r,
    _trimesh_obj_w,
    _trimesh_off_r,
    _trimesh_off_w,
    _trimesh_ply_r,
    _trimesh_ply_w,
    _trimesh_stl_r,
    _trimesh_stl_w,
    trimesh,
)
from sceneio import _core


def build_mesh_specs(scale):
    points = max(1, int(1_000_000 * scale))
    return [
        Spec(
            "ply_mesh",
            lambda: _mesh_ply(max(3, points // 3)),
            _core.write_ply_mesh,
            _core.read_ply_mesh,
            (_trimesh_ply_w if trimesh else None),
            (_trimesh_ply_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "obj",
            lambda: _mesh_obj(max(3, points // 3)),
            _core.write_obj,
            _core.read_obj,
            (_trimesh_obj_w if trimesh else None),
            (_trimesh_obj_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "stl",
            lambda: _mesh_stl(max(3, points // 3)),
            _core.write_stl,
            _core.read_stl,
            (_trimesh_stl_w if trimesh else None),
            (_trimesh_stl_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "off",
            lambda: _mesh_off(max(3, points // 3)),
            _core.write_off,
            _core.read_off,
            (_trimesh_off_w if trimesh else None),
            (_trimesh_off_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "glb",
            lambda: _mesh_scene(max(3, points // 3)),
            _core.write_glb,
            _core.read_glb,
            (_trimesh_glb_w if trimesh else None),
            (_trimesh_glb_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
    ]


__all__ = ["build_mesh_specs"]
