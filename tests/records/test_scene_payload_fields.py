from __future__ import annotations

import gc

import numpy as np
import pytest

from sceneio import _core
from sceneio.io._e57 import write_e57
from sceneio.io._gltf import write_gltf
from sceneio.io._obj import write_obj
from sceneio.io._usd import write_usd


def _extended_points(**changes):
    count = 3
    values = {
        "positions": np.arange(count * 3, dtype=np.float32).reshape(count, 3),
        "display_colors": np.array(
            [[0.1, 0.2, 0.3], [1.5, 0.5, 0.25], [0.0, 0.0, 0.0]],
            np.float32,
        ),
        "display_opacities": np.array([1.0, 0.5, 0.0], np.float32),
        "widths": np.array([0.0, 0.1, 2.0], np.float32),
        "ids": np.array([10, -4, 99], np.int64),
        "velocities": np.arange(count * 3, dtype=np.float32).reshape(count, 3)
        / 10,
        "accelerations": np.arange(
            count * 3, dtype=np.float32
        ).reshape(count, 3)
        / 100,
        "display_color_space": "linear",
    }
    values.update(changes)
    return _core.point_cloud(**values)


def _extended_mesh(**changes):
    values = {
        "positions": np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32
        ),
        "face_offsets": np.array([0, 3], np.uint64),
        "face_indices": np.array([0, 1, 2], np.uint64),
        "coordinate_frame": "opengl",
        "vertex_display_colors": np.array(
            [[0.1, 0.2, 0.3], [2.0, 1.0, 0.0], [0.5, 0.5, 0.5]],
            np.float32,
        ),
        "corner_display_colors": np.array(
            [[0.0, 0.0, 0.0], [0.25, 0.5, 0.75], [1.0, 1.0, 1.0]],
            np.float32,
        ),
        "vertex_display_opacities": np.array([1.0, 0.5, 0.0], np.float32),
        "corner_display_opacities": np.array([0.2, 0.4, 0.6], np.float32),
        "display_color_space": "linear",
        "orientation": "right_handed",
        "double_sided": True,
    }
    values.update(changes)
    return _core.mesh(**values)


def _mesh_scene(mesh):
    return _core.mesh_scene(
        [mesh],
        np.array([0, 1], np.uint64),
        node_meshes=np.array([0], np.int64),
        node_child_offsets=np.array([0, 0], np.uint64),
        node_children=np.array([], np.uint64),
        node_local_transforms=np.eye(4, dtype=np.float64)[None],
        node_names=["mesh"],
        scene_root_offsets=np.array([0, 1], np.uint64),
        scene_roots=np.array([0], np.uint64),
        default_scene=0,
    )


def test_point_scene_fields_are_exact_owned_and_owner_retaining():
    source_colors = np.ones((3, 3), np.float32)
    source_widths = np.array([0.0, 0.1, 2.0], np.float32)
    source_ids = np.array([10, -4, 99], np.int64)
    source_velocities = (
        np.arange(9, dtype=np.float32).reshape(3, 3) / 10
    )
    cloud = _extended_points(
        display_colors=source_colors,
        widths=source_widths,
        ids=source_ids,
        velocities=source_velocities,
    )
    source_colors[:] = 9
    source_widths[:] = 9
    source_ids[:] = 9
    source_velocities[:] = 9

    assert cloud.has_display_colors
    assert cloud.has_display_opacities
    assert cloud.has_widths
    assert cloud.has_ids
    assert cloud.has_velocities
    assert cloud.has_accelerations
    assert cloud.display_color_space == "linear"
    np.testing.assert_array_equal(cloud.display_colors, np.ones((3, 3)))
    np.testing.assert_array_equal(cloud.display_opacities, [1.0, 0.5, 0.0])
    np.testing.assert_array_equal(
        cloud.widths, np.array([0.0, 0.1, 2.0], np.float32)
    )
    np.testing.assert_array_equal(cloud.ids, [10, -4, 99])

    views = {
        "display_colors": cloud.display_colors,
        "display_opacities": cloud.display_opacities,
        "widths": cloud.widths,
        "ids": cloud.ids,
        "velocities": cloud.velocities,
        "accelerations": cloud.accelerations,
    }
    del cloud
    gc.collect()
    np.testing.assert_array_equal(views["ids"], [10, -4, 99])
    np.testing.assert_array_equal(
        views["velocities"][:, 0],
        np.array([0.0, 0.3, 0.6], np.float32),
    )

    legacy = _core.point_cloud(
        np.zeros((0, 3), np.float32),
        display_colors=np.zeros((0, 3), np.float32),
        display_opacities=np.zeros((0,), np.float32),
        widths=np.zeros((0,), np.float32),
        ids=np.zeros((0,), np.int64),
        velocities=np.zeros((0, 3), np.float32),
        accelerations=np.zeros((0, 3), np.float32),
    )
    assert legacy.display_colors.shape == (0, 3)
    assert legacy.display_opacities.shape == (0,)
    assert legacy.widths.shape == (0,)
    assert legacy.ids.shape == (0,)
    assert legacy.velocities.shape == (0, 3)
    assert legacy.accelerations.shape == (0, 3)
    assert legacy.display_color_space == "unknown"


def test_point_scene_field_validation_is_closed_and_shape_exact():
    invalid = [
        (
            {"display_colors": np.zeros((3, 4), np.float32)},
            r"display_colors.*\(N,3\)",
        ),
        (
            {"display_opacities": np.array([1.0, 0.5, 1.1], np.float32)},
            "opacity",
        ),
        (
            {"widths": np.array([1.0, -0.1, 2.0], np.float32)},
            "width",
        ),
        ({"ids": np.array([1, 1, 2], np.int64)}, "ids must be unique"),
        (
            {
                "velocities": np.array(
                    [[0, 0, 0], [0, np.nan, 0], [0, 0, 0]],
                    np.float32,
                )
            },
            "velocity",
        ),
        (
            {"display_color_space": "acescg"},
            "display_color_space must be unknown",
        ),
    ]
    for changes, message in invalid:
        with pytest.raises(ValueError, match=message):
            _extended_points(**changes)


def test_mesh_scene_fields_are_exact_owned_and_owner_retaining():
    source_colors = np.ones((3, 3), np.float32)
    source_opacities = np.array([0.2, 0.4, 0.6], np.float32)
    mesh = _extended_mesh(
        vertex_display_colors=source_colors,
        corner_display_opacities=source_opacities,
    )
    source_colors[:] = 9
    source_opacities[:] = 9

    assert mesh.has_vertex_display_colors
    assert mesh.has_corner_display_colors
    assert mesh.has_vertex_display_opacities
    assert mesh.has_corner_display_opacities
    assert mesh.display_color_space == "linear"
    assert mesh.orientation == "right_handed"
    assert mesh.has_double_sided
    assert mesh.double_sided is True
    np.testing.assert_array_equal(
        mesh.vertex_display_colors, np.ones((3, 3))
    )
    np.testing.assert_array_equal(
        mesh.corner_display_opacities,
        np.array([0.2, 0.4, 0.6], np.float32),
    )

    views = {
        "vertex_display_colors": mesh.vertex_display_colors,
        "corner_display_colors": mesh.corner_display_colors,
        "vertex_display_opacities": mesh.vertex_display_opacities,
        "corner_display_opacities": mesh.corner_display_opacities,
    }
    del mesh
    gc.collect()
    np.testing.assert_array_equal(
        views["vertex_display_colors"], np.ones((3, 3))
    )

    legacy = _core.mesh(
        np.zeros((0, 3), np.float32),
        np.array([0], np.uint64),
        np.array([], np.uint64),
        vertex_display_colors=np.zeros((0, 3), np.float32),
        corner_display_colors=np.zeros((0, 3), np.float32),
        vertex_display_opacities=np.zeros((0,), np.float32),
        corner_display_opacities=np.zeros((0,), np.float32),
    )
    assert legacy.vertex_display_colors.shape == (0, 3)
    assert legacy.corner_display_colors.shape == (0, 3)
    assert legacy.vertex_display_opacities.shape == (0,)
    assert legacy.corner_display_opacities.shape == (0,)
    assert legacy.display_color_space == "unknown"
    assert legacy.orientation == "unknown"
    assert not legacy.has_double_sided
    assert legacy.double_sided is None


def test_mesh_scene_field_validation_is_closed_and_shape_exact():
    invalid = [
        (
            {"corner_display_colors": np.zeros((2, 3), np.float32)},
            r"corner_display_colors.*\(3,3\)",
        ),
        (
            {
                "vertex_display_opacities": np.array(
                    [0.0, -0.1, 1.0], np.float32
                )
            },
            "opacity",
        ),
        ({"display_color_space": "raw"}, "display_color_space"),
        ({"orientation": "clockwise"}, "orientation"),
    ]
    for changes, message in invalid:
        with pytest.raises(ValueError, match=message):
            _extended_mesh(**changes)

    explicit_false = _extended_mesh(double_sided=False)
    assert explicit_false.has_double_sided
    assert explicit_false.double_sided is False


def test_existing_point_and_mesh_writers_refuse_extended_fields(tmp_path):
    point_writers = [
        _core.write_xyz,
        _core.write_pts,
        _core.write_ply,
        _core.write_pcd,
        _core.write_las,
        _core.write_laz,
    ]
    point_fields = {
        "display_colors": np.zeros((3, 3), np.float32),
        "display_opacities": np.ones((3,), np.float32),
        "widths": np.ones((3,), np.float32),
        "ids": np.arange(3, dtype=np.int64),
        "velocities": np.zeros((3, 3), np.float32),
        "accelerations": np.zeros((3, 3), np.float32),
        "display_color_space": "linear",
    }
    positions = np.zeros((3, 3), np.float32)
    for field, value in point_fields.items():
        cloud = _core.point_cloud(positions, **{field: value})
        for writer in point_writers:
            with pytest.raises(ValueError, match="cannot represent"):
                writer(cloud)
        with pytest.raises(ValueError, match="unsupported"):
            write_e57(cloud, tmp_path / f"{field}.e57")

    mesh_writers = [
        _core.write_ply_mesh,
        _core.write_obj,
        _core.write_stl,
        _core.write_off,
    ]
    mesh_fields = {
        "vertex_display_colors": np.zeros((3, 3), np.float32),
        "corner_display_colors": np.zeros((3, 3), np.float32),
        "vertex_display_opacities": np.ones((3,), np.float32),
        "corner_display_opacities": np.ones((3,), np.float32),
        "display_color_space": "linear",
        "orientation": "right_handed",
        "double_sided": False,
    }
    for field, value in mesh_fields.items():
        changes = {
            "vertex_display_colors": None,
            "corner_display_colors": None,
            "vertex_display_opacities": None,
            "corner_display_opacities": None,
            "display_color_space": "unknown",
            "orientation": "unknown",
            "double_sided": None,
        }
        changes[field] = value
        mesh = _extended_mesh(**changes)
        for writer in mesh_writers:
            with pytest.raises(ValueError, match="cannot represent"):
                writer(mesh)
        scene = _mesh_scene(mesh)
        with pytest.raises(ValueError, match="cannot represent"):
            _core.write_gltf(scene)
        with pytest.raises(ValueError, match="cannot represent"):
            _core.write_glb(scene)
        with pytest.raises(ValueError, match="unsupported"):
            write_usd(scene, tmp_path / f"{field}.usda")


def test_extended_field_path_writers_preserve_destinations(tmp_path):
    mesh = _extended_mesh()
    scene = _mesh_scene(mesh)
    obj = tmp_path / "scene.obj"
    gltf = tmp_path / "scene.gltf"
    binary = tmp_path / "scene.bin"
    usd = tmp_path / "scene.usda"
    e57 = tmp_path / "scene.e57"
    for path in (obj, gltf, binary, usd, e57):
        path.write_bytes(b"sentinel")

    with pytest.raises(ValueError, match="cannot represent"):
        write_obj(mesh, obj)
    with pytest.raises(ValueError, match="cannot represent"):
        write_gltf(scene, gltf)
    with pytest.raises(ValueError, match="unsupported"):
        write_usd(scene, usd)
    with pytest.raises(ValueError, match="unsupported"):
        write_e57(_extended_points(), e57)

    for path in (obj, gltf, binary, usd, e57):
        assert path.read_bytes() == b"sentinel"
