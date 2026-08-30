"""Deterministic fixtures for mesh and mesh-scene benchmark codecs."""

from __future__ import annotations

from itertools import pairwise

import numpy as np

from sceneio import _core


def _mesh_ply(n):
    rng = np.random.default_rng(23)
    n = max(3, n)
    faces = max(1, n // 2)
    corners = faces * 3
    positions = rng.standard_normal((n, 3)).astype(np.float32)
    indices = (np.arange(corners, dtype=np.uint64) % n).reshape(faces, 3)
    offsets = np.arange(0, corners + 1, 3, dtype=np.uint64)
    vertex_normals = rng.standard_normal((n, 3)).astype(np.float32)
    vertex_uvs = rng.random((n, 2), dtype=np.float32)
    vertex_colors = rng.integers(0, 256, (n, 4), dtype=np.uint8)
    corner_normals = rng.standard_normal((corners, 3)).astype(np.float32)
    corner_uvs = rng.random((corners, 2), dtype=np.float32)
    corner_colors = rng.integers(0, 256, (corners, 4), dtype=np.uint8)
    primitive_offsets = (
        np.array([0, faces], np.uint64)
        if faces == 1
        else np.array([0, faces // 2, faces], np.uint64)
    )
    primitive_materials = np.arange(
        len(primitive_offsets) - 1, dtype=np.int32
    )
    payload = {
        "positions": positions,
        "faces": indices,
        "vertex_normals": vertex_normals,
        "vertex_uvs": vertex_uvs,
        "vertex_colors": vertex_colors,
        "corner_normals": corner_normals,
        "corner_uvs": corner_uvs,
        "corner_colors": corner_colors,
        "primitive_offsets": primitive_offsets,
        "primitive_materials": primitive_materials,
    }
    return (
        _core.mesh(
            positions,
            offsets,
            indices.reshape(-1),
            vertex_normals=vertex_normals,
            corner_normals=corner_normals,
            vertex_uvs=vertex_uvs,
            corner_uvs=corner_uvs,
            vertex_colors=vertex_colors,
            corner_colors=corner_colors,
            primitive_offsets=primitive_offsets,
            primitive_materials=primitive_materials,
        ),
        payload,
    )


def _mesh_obj(n):
    rng = np.random.default_rng(29)
    vertices = max(3, n)
    faces = max(1, vertices // 3)
    corners = faces * 3
    positions = rng.standard_normal((vertices, 3)).astype(np.float32)
    indices = (
        np.arange(corners, dtype=np.uint64) % vertices
    ).reshape(faces, 3)
    offsets = np.arange(0, corners + 1, 3, dtype=np.uint64)
    vertex_normals = rng.standard_normal((vertices, 3)).astype(np.float32)
    vertex_uvs = rng.random((vertices, 2), dtype=np.float32)
    vertex_colors = rng.integers(0, 256, (vertices, 4), dtype=np.uint8)
    vertex_colors[:, 3] = 255
    payload = {
        "positions": positions,
        "faces": indices,
        "vertex_normals": vertex_normals,
        "vertex_uvs": vertex_uvs,
        "vertex_colors": vertex_colors,
    }
    return (
        _core.mesh(
            positions,
            offsets,
            indices.reshape(-1),
            vertex_normals=vertex_normals,
            vertex_uvs=vertex_uvs,
            vertex_colors=vertex_colors,
        ),
        payload,
    )


def _mesh_stl(n):
    rng = np.random.default_rng(31)
    faces = max(1, n // 3)
    corners = faces * 3
    positions = rng.standard_normal((corners, 3)).astype(np.float32)
    indices = np.arange(corners, dtype=np.uint64).reshape(faces, 3)
    offsets = np.arange(0, corners + 1, 3, dtype=np.uint64)
    face_normals = rng.standard_normal((faces, 3)).astype(np.float32)
    corner_normals = np.repeat(face_normals, 3, axis=0)
    payload = {
        "positions": positions,
        "faces": indices,
        "face_normals": face_normals,
    }
    return (
        _core.mesh(
            positions,
            offsets,
            indices.reshape(-1),
            corner_normals=corner_normals,
        ),
        payload,
    )


def _mesh_off(n):
    rng = np.random.default_rng(37)
    # Indexed formats commonly reuse a much smaller vertex domain across many
    # faces. Keep face records dominant so bounded face selection measures the
    # work and allocations it is designed to remove.
    vertices = max(3, n // 10)
    faces = max(1, n)
    positions = rng.standard_normal((vertices, 3)).astype(np.float32)
    indices = (
        np.arange(faces * 3, dtype=np.uint64) % vertices
    ).reshape(faces, 3)
    offsets = np.arange(0, faces * 3 + 1, 3, dtype=np.uint64)
    payload = {"positions": positions, "faces": indices}
    return (
        _core.mesh(positions, offsets, indices.reshape(-1)),
        payload,
    )


def _scene_graph(n):
    rng = np.random.default_rng(41)
    vertices = max(3, (n // 3) * 3)
    faces = max(1, vertices // 3)
    corners = vertices
    positions = rng.standard_normal((vertices, 3)).astype(np.float32)
    normals = rng.standard_normal((vertices, 3)).astype(np.float32)
    uvs = rng.random((vertices, 2), dtype=np.float32)
    colors = rng.integers(0, 256, (vertices, 4), dtype=np.uint8)
    indices = np.arange(corners, dtype=np.uint64)
    primitive_count = min(4, faces)
    face_bounds = np.linspace(
        0, faces, primitive_count + 1, dtype=np.int64
    )
    primitives = []
    for start_face, stop_face in pairwise(face_bounds):
        start = int(start_face) * 3
        stop = int(stop_face) * 3
        local_vertices = stop - start
        primitives.append(
            _core.mesh(
                positions[start:stop],
                np.arange(
                    0, local_vertices + 1, 3, dtype=np.uint64
                ),
                np.arange(local_vertices, dtype=np.uint64),
                vertex_normals=normals[start:stop],
                vertex_uvs=uvs[start:stop],
                vertex_colors=colors[start:stop],
                coordinate_frame="opengl",
            )
        )
    scene = _core.scene_graph(
        ["node"],
        meshes=primitives,
        mesh_primitive_offsets=np.array([0, primitive_count], np.uint64),
        mesh_names=["mesh"],
        node_payload_kinds=["mesh"],
        node_payload_indices=np.array([0], np.uint64),
        node_child_offsets=np.array([0, 0], np.uint64),
        node_children=np.array([], np.uint64),
        node_local_transforms=np.eye(4, dtype=np.float64)[None],
        scene_root_offsets=np.array([0, 1], np.uint64),
        scene_roots=np.array([0], np.uint64),
        scene_names=["scene"],
        default_scene=0,
    )
    payload = {
        "positions": positions,
        "faces": indices.reshape(faces, 3),
        "normals": normals,
        "uvs": uvs,
        "colors": colors,
    }
    return scene, payload


__all__ = [
    "_mesh_obj",
    "_mesh_off",
    "_mesh_ply",
    "_mesh_stl",
    "_scene_graph",
]
