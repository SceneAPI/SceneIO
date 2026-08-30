from __future__ import annotations

import copy
import pickle

import numpy as np
import pytest

from sceneio import _core


def _mesh(*, material: int = -1):
    return _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        primitive_materials=np.array([material], np.int32),
        primitive_offsets=np.array([0, 1], np.uint64),
        coordinate_frame="opengl",
    )


def _scene():
    materials = _core.material_set([""])
    transforms = np.stack(
        [
            np.eye(4, dtype=np.float64),
            np.array(
                [
                    [1, 0, 0, 2],
                    [0, 1, 0, 3],
                    [0, 0, 1, 4],
                    [0, 0, 0, 1],
                ],
                np.float64,
            ),
        ]
    )
    return _core.scene_graph(
        ["root", "child"],
        meshes=[_mesh(material=0), _mesh(material=-1)],
        mesh_primitive_offsets=np.array([0, 1, 2], np.uint64),
        mesh_names=["first", ""],
        node_payload_kinds=["mesh", "mesh"],
        node_payload_indices=np.array([0, 1], np.uint64),
        node_child_offsets=np.array([0, 1, 1], np.uint64),
        node_children=np.array([1], np.uint64),
        node_local_transforms=transforms,
        scene_root_offsets=np.array([0, 1], np.uint64),
        scene_roots=np.array([0], np.uint64),
        scene_names=["main"],
        default_scene=0,
        materials=materials,
        source_representation="gltf",
    )


def test_scene_graph_mesh_group_surface_and_zero_copy_views():
    scene = _scene()

    assert repr(scene) == "<SceneGraph nodes=2 meshes=2 points=0 gaussians=0>"
    assert scene.num_meshes == 2
    assert scene.num_mesh_primitives == 2
    assert scene.num_nodes == 2
    assert scene.num_scenes == 1
    assert scene.mesh_names == ["first", ""]
    assert scene.node_names == ["root", "child"]
    assert scene.scene_names == ["main"]
    assert scene.default_scene == 0
    assert scene.has_materials
    assert scene.materials.names == [""]
    assert scene.mesh_primitive_at(0).num_faces == 1
    assert np.shares_memory(
        scene.node_local_transforms, scene.node_local_transforms
    )
    assert not scene.node_local_transforms.flags.writeable
    assert not scene.mesh_primitive_offsets.flags.writeable


def test_nested_record_and_array_lifetimes_outlive_parent_name():
    scene = _scene()
    primitive = scene.mesh_primitive_at(1)
    transforms = scene.node_local_transforms
    del scene

    np.testing.assert_array_equal(primitive.face_indices, [0, 1, 2])
    np.testing.assert_array_equal(transforms[1, :3, 3], [2, 3, 4])


def test_factory_owns_primitive_and_node_array_copies():
    primitive = _mesh()
    node_payload_indices = np.array([0], np.uint64)
    transforms = np.eye(4, dtype=np.float64)[None]
    scene = _core.scene_graph(
        [""],
        meshes=[primitive],
        mesh_primitive_offsets=np.array([0, 1], np.uint64),
        node_payload_kinds=["mesh"],
        node_payload_indices=node_payload_indices,
        node_child_offsets=np.array([0, 0], np.uint64),
        node_children=np.array([], np.uint64),
        node_local_transforms=transforms,
    )

    primitive.positions[0, 0] = 99
    node_payload_indices[0] = 99
    transforms[0, 0, 0] = 7

    assert scene.mesh_primitive_at(0).positions[0, 0] == 0
    assert scene.node_payload_indices[0] == 0
    assert scene.node_local_transforms[0, 0, 0] == 1


@pytest.mark.parametrize("operation", [copy.copy, copy.deepcopy, pickle.dumps])
def test_copy_and_pickle_policy_is_explicit_rejection(operation):
    with pytest.raises(TypeError):
        operation(_scene())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"mesh_primitive_offsets": np.array([0, 0, 2], np.uint64)},
            "non-empty",
        ),
        (
            {"node_payload_indices": np.array([0, 99], np.uint64)},
            "payload index",
        ),
        (
            {"node_children": np.array([2], np.uint64)},
            "child index",
        ),
        (
            {
                "node_child_offsets": np.array([0, 1, 2], np.uint64),
                "node_children": np.array([1, 0], np.uint64),
            },
            "cyclic|multiple parents",
        ),
        (
            {"scene_roots": np.array([1], np.uint64)},
            "roots cannot have parents",
        ),
        ({"default_scene": 4}, "default scene"),
    ],
)
def test_scene_graph_mesh_group_validation(kwargs, message):
    values = {
        "meshes": [_mesh(), _mesh()],
        "mesh_primitive_offsets": np.array([0, 1, 2], np.uint64),
        "mesh_names": ["a", "b"],
        "node_payload_kinds": ["mesh", "mesh"],
        "node_payload_indices": np.array([0, 1], np.uint64),
        "node_child_offsets": np.array([0, 1, 1], np.uint64),
        "node_children": np.array([1], np.uint64),
        "node_local_transforms": np.stack(
            [np.eye(4), np.eye(4)]
        ).astype(np.float64),
        "node_names": ["a", "b"],
        "scene_root_offsets": np.array([0, 1], np.uint64),
        "scene_roots": np.array([0], np.uint64),
        "scene_names": ["main"],
        "default_scene": 0,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        _core.scene_graph(**values)


def test_gltf_writer_rejects_noncanonical_primitive():
    mesh = _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
    )
    scene = _core.scene_graph(
        [],
        meshes=[mesh],
        mesh_primitive_offsets=np.array([0, 1], np.uint64),
    )
    with pytest.raises(ValueError, match="canonical glTF"):
        _core.write_glb(scene)


def test_zero_dimensional_node_payload_array_is_rejected_before_shape_access():
    with pytest.raises(ValueError, match=r"node_payload_indices.*\(N,\)"):
        _core.scene_graph(
            ["node"],
            meshes=[_mesh()],
            node_payload_kinds=["mesh"],
            node_payload_indices=np.array(0, np.uint64),
        )


def test_deep_node_hierarchy_uses_iterative_cycle_validation():
    count = 20_000
    child_offsets = np.minimum(
        np.arange(count + 1, dtype=np.uint64), count - 1
    )
    scene = _core.scene_graph(
        [f"n{index}" for index in range(count)],
        meshes=[_mesh()],
        mesh_primitive_offsets=np.array([0, 1], np.uint64),
        node_child_offsets=child_offsets,
        node_children=np.arange(1, count, dtype=np.uint64),
        node_local_transforms=np.broadcast_to(
            np.eye(4, dtype=np.float64), (count, 4, 4)
        ).copy(),
        scene_root_offsets=np.array([0, 1], np.uint64),
        scene_roots=np.array([0], np.uint64),
    )

    assert scene.num_nodes == count
