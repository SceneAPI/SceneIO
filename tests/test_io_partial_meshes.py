"""Mesh-family O5 partial-read behavior coverage."""

from __future__ import annotations

import gc

import numpy as np

import sceneio
from sceneio import _core


def test_mesh_face_range_equals_full_domain_slice_and_closes_mapping(tmp_path):
    positions = np.arange(24, dtype=np.float32).reshape(8, 3) / 7
    face_offsets = np.array([0, 3, 6, 10, 13, 17, 20], np.uint64)
    face_indices = np.array(
        [
            0,
            1,
            2,
            0,
            2,
            3,
            0,
            3,
            4,
            5,
            1,
            5,
            6,
            0,
            1,
            6,
            7,
            2,
            6,
            7,
        ],
        np.uint64,
    )
    mesh = _core.mesh(
        positions,
        face_offsets,
        face_indices,
        vertex_normals=np.arange(24, dtype=np.float32).reshape(8, 3) / 23,
        corner_normals=np.arange(60, dtype=np.float32).reshape(20, 3) / 59,
        vertex_uvs=np.arange(16, dtype=np.float32).reshape(8, 2) / 15,
        corner_uvs=np.arange(40, dtype=np.float32).reshape(20, 2) / 39,
        vertex_colors=np.arange(32, dtype=np.uint8).reshape(8, 4),
        corner_colors=np.arange(80, dtype=np.uint8).reshape(20, 4),
        primitive_offsets=np.array([0, 2, 5, 6], np.uint64),
        primitive_materials=np.array([2, 3, -1], np.int32),
        coordinate_frame="opengl",
        scale_to_meters=0.01,
    )
    path = tmp_path / "faces.ply"
    sceneio.write(mesh, path)

    partial = sceneio.read_partial(path, faces=(1, 5))
    corner_start, corner_stop = 3, 17
    np.testing.assert_array_equal(partial.positions, mesh.positions)
    np.testing.assert_array_equal(partial.vertex_normals, mesh.vertex_normals)
    np.testing.assert_array_equal(partial.vertex_uvs, mesh.vertex_uvs)
    np.testing.assert_array_equal(partial.vertex_colors, mesh.vertex_colors)
    np.testing.assert_array_equal(
        partial.face_offsets, face_offsets[1:6] - corner_start
    )
    np.testing.assert_array_equal(
        partial.face_indices, face_indices[corner_start:corner_stop]
    )
    for name in ("corner_normals", "corner_uvs", "corner_colors"):
        np.testing.assert_array_equal(
            getattr(partial, name),
            getattr(mesh, name)[corner_start:corner_stop],
        )
    np.testing.assert_array_equal(partial.primitive_offsets, [0, 1, 4])
    np.testing.assert_array_equal(partial.primitive_materials, [2, 3])
    assert partial.coordinate_frame == "opengl"
    assert partial.scale_to_meters == 0.01

    gc.collect()
    replacement = tmp_path / "faces-replaced.ply"
    path.replace(replacement)
    path.write_bytes(b"replacement")
    np.testing.assert_array_equal(
        partial.face_indices, face_indices[corner_start:corner_stop]
    )
