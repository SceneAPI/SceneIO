from __future__ import annotations

import copy
import gc
import pickle

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _mesh(*, material: int = -1, materials=None):
    return _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        primitive_offsets=np.array([0, 1], np.uint64),
        primitive_materials=np.array([material], np.int32),
        materials=materials,
    )


def _point_cloud():
    return _core.point_cloud(
        np.array([[2, 3, 4]], np.float32),
        coordinate_frame="opengl",
    )


def _gaussians():
    return _core.gaussian_cloud(
        np.array([[0, 0, 0]], np.float32),
        np.array([[0, 0, 0]], np.float32),
        np.array([[1, 0, 0, 0]], np.float32),
        np.array([0], np.float32),
        np.array([[0.1, 0.2, 0.3]], np.float32),
    )


def _instances():
    return _core.instance_set(
        np.array([0], np.uint64),
        np.array([0, 0], np.uint64),
        np.zeros((2, 3), np.float32),
    )


def _scene(**changes):
    no_payload = np.iinfo(np.uint64).max
    values = {
        "node_names": ["prototype", "points", "gaussians", "fog", "copies"],
        "node_child_offsets": np.array([0, 4, 4, 4, 4, 4], np.uint64),
        "node_children": np.array([1, 2, 3, 4], np.uint64),
        "node_local_transforms": np.broadcast_to(
            np.eye(4, dtype=np.float64), (5, 4, 4)
        ).copy(),
        "node_resets_transform_stack": np.array([0, 1, 0, 0, 0], np.uint8),
        "node_payload_kinds": [
            "mesh",
            "point_cloud",
            "gaussian_cloud",
            "volume",
            "instances",
        ],
        "node_payload_indices": np.array([0, 0, 0, 0, 0], np.uint64),
        "node_visibility": [
            "visible",
            "inherited",
            "invisible",
            "visible",
            "visible",
        ],
        "node_purpose": ["default", "render", "proxy", "guide", "default"],
        "node_semantic_taxonomies": ["", "", "class", "", ""],
        "node_semantic_labels": ["", "", "vegetation", "", ""],
        "meshes": [_mesh()],
        "point_clouds": [_point_cloud()],
        "gaussian_clouds": [_gaussians()],
        "volumes": [_core.volume_asset("density.vdb", "density")],
        "instances": [_instances()],
        "external_asset_uris": ["density.vdb"],
        "external_asset_kinds": ["openvdb"],
        "external_asset_sources": ["C:/assets/density.vdb"],
        "up_axis": "z",
        "meters_per_unit": 0.01,
        "source_representation": "usdc",
        "default_prim": 0,
        "selected_time": 2.5,
        "start_time_code": 1.0,
        "end_time_code": 5.0,
        "time_codes_per_second": 30.0,
    }
    values.update(changes)
    if values["node_payload_kinds"] is None:
        values["node_payload_indices"] = np.full(5, no_payload, np.uint64)
    return _core.scene_graph(**values)


def test_scene_graph_public_surface_and_typed_payloads():
    scene = _scene()

    assert isinstance(scene, sceneio.SceneGraph)
    assert sceneio.InstanceSet is _core.InstanceSet
    assert sceneio.VolumeAsset is _core.VolumeAsset
    assert repr(scene) == (
        "<SceneGraph nodes=5 meshes=1 points=1 gaussians=1>"
    )
    assert scene.num_nodes == 5
    assert scene.num_meshes == 1
    assert scene.num_point_clouds == 1
    assert scene.num_gaussian_clouds == 1
    assert scene.num_cameras == 0
    assert scene.num_volumes == 1
    assert scene.num_instance_sets == 1
    assert scene.node_names == [
        "prototype",
        "points",
        "gaussians",
        "fog",
        "copies",
    ]
    np.testing.assert_array_equal(scene.node_parents, [-1, 0, 0, 0, 0])
    assert scene.node_payload_kinds == [
        "mesh",
        "point_cloud",
        "gaussian_cloud",
        "volume",
        "instances",
    ]
    assert scene.node_visibility[2] == "invisible"
    assert scene.node_resets_transform_stack.tolist() == [0, 1, 0, 0, 0]
    assert scene.node_purpose[3] == "guide"
    assert scene.node_semantic_labels[2] == "vegetation"
    assert scene.mesh_primitive_at(0).num_faces == 1
    assert scene.point_cloud_at(0).num_points == 1
    assert scene.gaussian_cloud_at(0).num_gaussians == 1
    assert scene.volume_at(0).grid_name == "density"
    assert scene.instance_set_at(0).num_instances == 2
    assert scene.up_axis == "z"
    assert scene.meters_per_unit == 0.01
    assert scene.source_representation == "usdc"
    assert scene.default_prim == 0
    assert scene.selected_time == 2.5
    assert scene.start_time_code == 1.0
    assert scene.end_time_code == 5.0
    assert scene.time_codes_per_second == 30.0
    assert scene.external_asset_uris == ["density.vdb"]
    assert scene.external_asset_sources == ["C:/assets/density.vdb"]

    rig = _core.camera_rig(
        np.array([7], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500, 500, 320, 240], np.float64),
        [""],
        np.array([0, 0], np.uint64),
        np.array([], np.float64),
        np.array([[1, 0, 0, 0]], np.float64),
        np.zeros((1, 3), np.float64),
    )
    camera_scene = _core.scene_graph(
        ["camera"],
        node_payload_kinds=["camera"],
        node_payload_indices=np.array([0], np.uint64),
        cameras=rig,
        materials=_core.material_set(["default"]),
    )
    assert camera_scene.has_cameras
    assert camera_scene.num_cameras == 1
    assert camera_scene.cameras.camera_ids.tolist() == [7]
    assert camera_scene.has_materials
    assert camera_scene.materials.names == ["default"]

    material_scene = _core.scene_graph(
        ["mesh"],
        node_payload_kinds=["mesh"],
        node_payload_indices=np.array([0], np.uint64),
        meshes=[_mesh(material=0)],
        materials=_core.material_set(["surface"]),
    )
    assert material_scene.mesh_primitive_at(0).primitive_materials.tolist() == [0]
    assert material_scene.materials.names == ["surface"]


def test_scene_graph_numeric_views_and_nested_payload_outlive_parent_name():
    scene = _scene()
    children = scene.node_children
    transforms = scene.node_local_transforms
    transforms_again = scene.node_local_transforms
    resets = scene.node_resets_transform_stack
    mesh = scene.mesh_primitive_at(0)
    instances = scene.instance_set_at(0)
    del scene
    gc.collect()

    np.testing.assert_array_equal(children, [1, 2, 3, 4])
    np.testing.assert_array_equal(transforms[0], np.eye(4))
    np.testing.assert_array_equal(mesh.face_indices, [0, 1, 2])
    np.testing.assert_array_equal(instances.prototype_indices, [0, 0])
    assert not children.flags.writeable
    assert not transforms.flags.writeable
    assert not resets.flags.writeable
    assert np.shares_memory(transforms, transforms_again)


def test_empty_and_hierarchy_only_scene_defaults_are_canonical():
    empty = _core.scene_graph([])
    assert empty.num_nodes == 0
    assert empty.node_child_offsets.tolist() == [0]
    assert empty.selected_time is None
    assert empty.start_time_code is None
    assert empty.end_time_code is None

    hierarchy = _core.scene_graph(["left", "right"])
    np.testing.assert_array_equal(hierarchy.node_parents, [-1, -1])
    assert hierarchy.node_payload_kinds == ["none", "none"]
    np.testing.assert_array_equal(
        hierarchy.node_payload_indices,
        np.full(2, np.iinfo(np.uint64).max, np.uint64),
    )
    np.testing.assert_array_equal(
        hierarchy.node_local_transforms,
        np.broadcast_to(np.eye(4), (2, 4, 4)),
    )
    np.testing.assert_array_equal(
        hierarchy.node_resets_transform_stack,
        np.zeros(2, np.uint8),
    )


def test_scene_graph_factory_owns_array_and_payload_copies():
    transforms = np.broadcast_to(np.eye(4), (5, 4, 4)).copy()
    mesh = _mesh()
    scene = _scene(node_local_transforms=transforms, meshes=[mesh])
    transforms[0, 0, 0] = 9
    mesh.positions[0, 0] = 9

    assert scene.node_local_transforms[0, 0, 0] == 1
    assert scene.mesh_primitive_at(0).positions[0, 0] == 0


@pytest.mark.parametrize("operation", [copy.copy, copy.deepcopy, pickle.dumps])
def test_scene_graph_copy_and_pickle_policy_is_explicit_rejection(operation):
    with pytest.raises(TypeError):
        operation(_scene())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "node_child_offsets": np.array(
                    [0, 1, 2, 3, 4, 5], np.uint64
                ),
                "node_children": np.array([1, 2, 3, 4, 0], np.uint64),
            },
            "multiple parents|acyclic",
        ),
        (
            {"node_payload_indices": np.array([1, 0, 0, 0, 0], np.uint64)},
            "payload index",
        ),
        (
            {
                "node_semantic_taxonomies": ["", "", "class", "", ""],
                "node_semantic_labels": ["", "", "", "", ""],
            },
            "taxonomy and label",
        ),
        ({"default_prim": 1}, "default prim"),
        ({"up_axis": "x"}, "up_axis"),
        ({"meters_per_unit": 0.0}, "meters_per_unit"),
        (
            {"source_representation": "usd"},
            "source_representation",
        ),
        (
            {"start_time_code": 6.0, "end_time_code": 5.0},
            "time range",
        ),
        (
            {"external_asset_kinds": ["video"]},
            "external asset kind",
        ),
        (
            {"external_asset_sources": []},
            "source and URI counts",
        ),
    ],
)
def test_scene_graph_validation(changes, message):
    with pytest.raises(ValueError, match=message):
        _scene(**changes)


def test_scene_graph_instance_prototype_indices_are_graph_checked():
    instances = _core.instance_set(
        np.array([99], np.uint64),
        np.array([0], np.uint64),
        np.zeros((1, 3), np.float32),
    )
    with pytest.raises(ValueError, match="prototype node"):
        _scene(instances=[instances])


def test_scene_graph_shape_guards_run_before_shape_access():
    with pytest.raises(ValueError, match=r"node_local_transforms.*\(N,4,4\)"):
        _core.scene_graph(
            ["node"],
            node_local_transforms=np.array(0, np.float64),
        )
    with pytest.raises(ValueError, match="child offsets"):
        _core.scene_graph(
            ["node"],
            node_child_offsets=np.array([0, 2], np.uint64),
            node_children=np.array([0], np.uint64),
        )
    with pytest.raises(ValueError, match="monotonic"):
        _core.scene_graph(
            ["left", "right"],
            node_child_offsets=np.array([0, 1, 0], np.uint64),
            node_children=np.array([], np.uint64),
        )
    with pytest.raises(ValueError, match="visibility"):
        _core.scene_graph(["node"], node_visibility=["hidden"])
    with pytest.raises(ValueError, match="reset-transform-stack"):
        _core.scene_graph(
            ["node"],
            node_resets_transform_stack=np.array([2], np.uint8),
        )
    with pytest.raises(ValueError, match="node_resets_transform_stack"):
        _core.scene_graph(
            ["node"],
            node_resets_transform_stack=np.zeros((1, 1), np.uint8),
        )
    with pytest.raises(ValueError, match="payload kinds"):
        _core.scene_graph(["node"], node_payload_kinds=["light"])
    with pytest.raises(ValueError, match="uri"):
        _core.volume_asset("", "density")
    with pytest.raises(ValueError, match="OpenVDB assets"):
        _core.scene_graph(
            ["volume"],
            node_payload_kinds=["volume"],
            node_payload_indices=np.array([0], np.uint64),
            volumes=[_core.volume_asset("density.vdb", "density")],
        )
    with pytest.raises(ValueError, match="scene-shared"):
        _core.scene_graph(
            ["mesh"],
            node_payload_kinds=["mesh"],
            node_payload_indices=np.array([0], np.uint64),
            meshes=[
                _mesh(
                    material=0,
                    materials=_core.material_set(["local"]),
                )
            ],
        )
