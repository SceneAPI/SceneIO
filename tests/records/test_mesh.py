"""Canonical Mesh record validation, zero-copy views, and lifetime coverage."""

from __future__ import annotations

import copy
import gc
import pickle

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _arrays():
    positions = np.arange(18, dtype=np.float32).reshape(6, 3)
    offsets = np.array([0, 4, 7, 10], dtype=np.uint64)
    indices = np.array([0, 1, 2, 3, 0, 3, 4, 1, 4, 5], dtype=np.uint64)
    return positions, offsets, indices


def _full_mesh():
    positions, offsets, indices = _arrays()
    corners = len(indices)
    return _core.mesh(
        positions,
        offsets,
        indices,
        vertex_normals=np.arange(18, dtype=np.float32).reshape(6, 3) / 10,
        corner_normals=np.arange(corners * 3, dtype=np.float32).reshape(
            corners, 3
        )
        / 20,
        vertex_uvs=np.arange(12, dtype=np.float32).reshape(6, 2) / 11,
        corner_uvs=np.arange(corners * 2, dtype=np.float32).reshape(
            corners, 2
        )
        / 17,
        vertex_colors=np.arange(24, dtype=np.uint8).reshape(6, 4),
        corner_colors=np.arange(corners * 4, dtype=np.uint8).reshape(
            corners, 4
        ),
        primitive_offsets=np.array([0, 1, 3], dtype=np.uint64),
        primitive_materials=np.array([4, -1], dtype=np.int32),
        coordinate_frame="opengl",
        scale_to_meters=0.01,
        local_transform=np.array(
            [
                [1, 0, 0, 5],
                [0, 1, 0, 6],
                [0, 0, 1, 7],
                [0, 0, 0, 1],
            ],
            dtype=np.float64,
        ),
    )


def test_required_and_optional_shapes_and_metadata():
    mesh = _full_mesh()
    assert mesh.num_vertices == 6
    assert mesh.num_faces == 3
    assert mesh.num_corners == 10
    assert mesh.num_primitives == 2
    assert mesh.positions.shape == (6, 3)
    assert mesh.face_offsets.shape == (4,)
    assert mesh.face_indices.shape == (10,)
    assert mesh.vertex_normals.shape == (6, 3)
    assert mesh.corner_normals.shape == (10, 3)
    assert mesh.vertex_uvs.shape == (6, 2)
    assert mesh.corner_uvs.shape == (10, 2)
    assert mesh.vertex_colors.shape == (6, 4)
    assert mesh.corner_colors.shape == (10, 4)
    assert mesh.primitive_offsets.tolist() == [0, 1, 3]
    assert mesh.primitive_materials.tolist() == [4, -1]
    assert mesh.coordinate_frame == "opengl"
    assert mesh.scale_to_meters == 0.01
    np.testing.assert_array_equal(
        mesh.local_transform,
        [[1, 0, 0, 5], [0, 1, 0, 6], [0, 0, 1, 7], [0, 0, 0, 1]],
    )


def test_minimal_and_empty_records_have_canonical_primitive_ranges():
    positions, offsets, indices = _arrays()
    mesh = _core.mesh(positions, offsets, indices)
    assert mesh.primitive_offsets.tolist() == [0, 3]
    assert mesh.primitive_materials.tolist() == [-1]
    assert mesh.vertex_normals.shape == (0, 3)
    assert mesh.corner_uvs.shape == (0, 2)
    assert mesh.vertex_colors.shape == (0, 4)

    empty = _core.mesh(
        np.empty((0, 3), np.float32),
        np.array([0], np.uint64),
        np.empty(0, np.uint64),
    )
    assert empty.num_vertices == empty.num_faces == empty.num_corners == 0
    assert empty.num_primitives == 0
    assert empty.primitive_offsets.tolist() == [0]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("positions", np.empty((2, 2), np.float32), "positions"),
        ("face_offsets", np.empty(0, np.uint64), "face_offsets"),
        ("face_indices", np.empty((1, 1), np.uint64), "face_indices"),
    ],
)
def test_required_shape_guards(field, value, message):
    positions, offsets, indices = _arrays()
    values = {
        "positions": positions,
        "face_offsets": offsets,
        "face_indices": indices,
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        _core.mesh(**values)


@pytest.mark.parametrize(
    ("offsets", "indices", "message"),
    [
        ([1, 4], [0, 1, 2, 3], "start at zero"),
        ([0, 4, 3], [0, 1, 2], "monotonic"),
        ([0, 2], [0, 1], "at least three"),
        ([0, 4], [0, 1, 2], "end at num_corners"),
    ],
)
def test_face_topology_guards(offsets, indices, message):
    with pytest.raises(ValueError, match=message):
        _core.mesh(
            np.zeros((4, 3), np.float32),
            np.asarray(offsets, np.uint64),
            np.asarray(indices, np.uint64),
        )


def test_face_index_must_reference_vertex():
    with pytest.raises(ValueError, match="outside the vertex"):
        _core.mesh(
            np.zeros((3, 3), np.float32),
            np.array([0, 3], np.uint64),
            np.array([0, 1, 3], np.uint64),
        )


@pytest.mark.parametrize(
    ("name", "shape", "message"),
    [
        ("vertex_normals", (5, 3), "vertex_normals"),
        ("corner_normals", (9, 3), "corner_normals"),
        ("vertex_uvs", (6, 3), "vertex_uvs"),
        ("corner_uvs", (10, 3), "corner_uvs"),
        ("vertex_colors", (6, 3), "vertex_colors"),
        ("corner_colors", (9, 4), "corner_colors"),
    ],
)
def test_optional_domain_shape_guards(name, shape, message):
    positions, offsets, indices = _arrays()
    dtype = np.uint8 if "colors" in name else np.float32
    with pytest.raises(ValueError, match=message):
        _core.mesh(
            positions,
            offsets,
            indices,
            **{name: np.zeros(shape, dtype=dtype)},
        )


@pytest.mark.parametrize(
    ("offsets", "materials", "message"),
    [
        ([0, 2], None, "partition every face"),
        ([0, 2, 1, 3], None, "non-empty"),
        ([0, 1, 1, 3], None, "non-empty"),
        ([0, 1, 3], [2], "primitive_materials"),
        ([0, 1, 3], [-2, 0], "material indices"),
    ],
)
def test_primitive_range_guards(offsets, materials, message):
    positions, face_offsets, indices = _arrays()
    kwargs = {
        "primitive_offsets": np.asarray(offsets, np.uint64),
    }
    if materials is not None:
        kwargs["primitive_materials"] = np.asarray(materials, np.int32)
    with pytest.raises(ValueError, match=message):
        _core.mesh(positions, face_offsets, indices, **kwargs)


def test_primitive_materials_require_offsets():
    positions, offsets, indices = _arrays()
    with pytest.raises(ValueError, match="requires primitive_offsets"):
        _core.mesh(
            positions,
            offsets,
            indices,
            primitive_materials=np.array([0], np.int32),
        )


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("positions", np.nan, "position"),
        ("vertex_normals", np.inf, "vertex normal"),
        ("corner_normals", -np.inf, "corner normal"),
        ("vertex_uvs", np.nan, "vertex UV"),
        ("corner_uvs", np.inf, "corner UV"),
    ],
)
def test_nonfinite_numeric_attributes_reject(name, value, message):
    positions, offsets, indices = _arrays()
    kwargs = {}
    if name == "positions":
        positions = positions.copy()
        positions[0, 0] = value
    else:
        rows = 6 if name.startswith("vertex") else 10
        columns = 3 if "normals" in name else 2
        array = np.zeros((rows, columns), np.float32)
        array[0, 0] = value
        kwargs[name] = array
    with pytest.raises(ValueError, match=message):
        _core.mesh(positions, offsets, indices, **kwargs)


@pytest.mark.parametrize("frame", ["bad", "", "world"])
def test_coordinate_frame_closed_vocabulary(frame):
    positions, offsets, indices = _arrays()
    with pytest.raises(ValueError, match="coordinate_frame"):
        _core.mesh(
            positions,
            offsets,
            indices,
            coordinate_frame=frame,
        )


@pytest.mark.parametrize("scale", [0.0, -1.0, np.nan, np.inf])
def test_scale_must_be_finite_positive(scale):
    positions, offsets, indices = _arrays()
    with pytest.raises(ValueError, match="scale_to_meters"):
        _core.mesh(
            positions,
            offsets,
            indices,
            scale_to_meters=scale,
        )


def test_transform_shape_and_finiteness():
    positions, offsets, indices = _arrays()
    with pytest.raises(ValueError, match="local_transform"):
        _core.mesh(
            positions,
            offsets,
            indices,
            local_transform=np.eye(3),
        )
    transform = np.eye(4)
    transform[0, 0] = np.nan
    with pytest.raises(ValueError, match="local_transform"):
        _core.mesh(
            positions,
            offsets,
            indices,
            local_transform=transform,
        )


def test_constructor_owns_copies_and_accepts_noncontiguous_foreign_dtypes():
    positions = np.arange(36, dtype=np.float64).reshape(6, 6)[:, ::2]
    offsets = np.array([0, 4, 7, 10], dtype=np.int32)
    indices = np.array([0, 1, 2, 3, 0, 3, 4, 1, 4, 5], dtype=np.int32)
    expected = positions.astype(np.float32)
    mesh = _core.mesh(positions, offsets, indices)
    positions[:] = -1
    offsets[:] = 0
    indices[:] = 0
    np.testing.assert_array_equal(mesh.positions, expected)
    np.testing.assert_array_equal(mesh.face_offsets, [0, 4, 7, 10])
    np.testing.assert_array_equal(
        mesh.face_indices, [0, 1, 2, 3, 0, 3, 4, 1, 4, 5]
    )


@pytest.mark.parametrize(
    "name",
    [
        "positions",
        "face_offsets",
        "face_indices",
        "vertex_normals",
        "corner_normals",
        "vertex_uvs",
        "corner_uvs",
        "vertex_colors",
        "corner_colors",
        "primitive_offsets",
        "primitive_materials",
        "local_transform",
    ],
)
def test_views_are_zero_copy_writable_and_export_dlpack(name):
    mesh = _full_mesh()
    first = getattr(mesh, name)
    second = getattr(mesh, name)
    assert first.ctypes.data == second.ctypes.data
    assert first.flags.writeable
    assert hasattr(first, "__dlpack__")
    assert np.from_dlpack(first).shape == first.shape
    if first.size:
        flat = first.reshape(-1)
        original = flat[0].item()
        flat[0] = original + 1
        assert second.reshape(-1)[0] == original + 1


def test_view_keeps_parent_alive():
    mesh = _full_mesh()
    view = mesh.corner_uvs
    expected = view.copy()
    del mesh
    gc.collect()
    np.testing.assert_array_equal(view, expected)


def test_copy_deepcopy_and_pickle_are_explicitly_unsupported():
    mesh = _full_mesh()
    with pytest.raises(TypeError, match="pickle"):
        copy.copy(mesh)
    with pytest.raises(TypeError, match="pickle"):
        copy.deepcopy(mesh)
    with pytest.raises(TypeError, match="pickle"):
        pickle.dumps(mesh)


def test_public_export_and_repr():
    mesh = _full_mesh()
    assert sceneio.Mesh is _core.Mesh
    assert sceneio.io.Mesh is _core.Mesh
    assert repr(mesh) == (
        "<Mesh vertices=6 faces=3 corners=10 primitives=2>"
    )
