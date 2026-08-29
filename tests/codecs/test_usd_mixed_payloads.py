from __future__ import annotations

import numpy as np
import pytest

import sceneio
from sceneio import _core

tinyusdz = pytest.importorskip("tinyusdz")


def _mixed_scene(vdb_source):
    mesh = _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        coordinate_frame="opengl",
        scale_to_meters=1.0,
    )
    points = _core.point_cloud(
        np.array([[1, 2, 3]], np.float32),
        coordinate_frame="opengl",
        scale_to_meters=1.0,
    )
    gaussian = _core.gaussian_cloud(
        np.array([[0, 0, 0]], np.float32),
        np.array([[1, 1, 1]], np.float32),
        np.array([[1, 0, 0, 0]], np.float32),
        np.array([0.5], np.float32),
        np.array([[0.1, 0.2, 0.3]], np.float32),
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
    )
    rig = _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500, 500, 320, 240], np.float64),
        ["none"],
        np.array([0, 0], np.uint64),
        np.empty(0, np.float64),
        np.array([[1, 0, 0, 0]], np.float64),
        np.zeros((1, 3), np.float64),
        has_extrinsics=np.array([1], np.uint8),
        names=["/World/Camera"],
        camera_matrices=np.array(
            [[[500, 0, 320], [0, 500, 240], [0, 0, 1]]], np.float64
        ),
        has_camera_matrix=np.array([1], np.uint8),
        quaternion_sign="canonical_positive_w",
        transform_convention="camera_to_reference",
        axis_frame="opengl",
        reference_frame="unknown",
        scale_to_meters=1.0,
    )
    instance_set = _core.instance_set(
        np.array([1], np.uint64),
        np.array([0, 0], np.uint64),
        np.array([[2, 0, 0], [4, 0, 0]], np.float32),
    )
    no_payload = np.iinfo(np.uint64).max
    return _core.scene_graph(
        ["World", "Surface", "Points", "Gaussian", "Camera", "Fog", "Copies"],
        node_child_offsets=np.array([0, 6, 6, 6, 6, 6, 6, 6], np.uint64),
        node_children=np.arange(1, 7, dtype=np.uint64),
        node_payload_kinds=[
            "none",
            "mesh",
            "point_cloud",
            "gaussian_cloud",
            "camera",
            "volume",
            "instances",
        ],
        node_payload_indices=np.array(
            [no_payload, 0, 0, 0, 0, 0, 0], np.uint64
        ),
        node_semantic_taxonomies=["class"] * 7,
        node_semantic_labels=["scene"] * 7,
        meshes=[mesh],
        point_clouds=[points],
        gaussian_clouds=[gaussian],
        cameras=rig,
        volumes=[_core.volume_asset("density.vdb", "density", "density")],
        instances=[instance_set],
        external_asset_uris=["density.vdb"],
        external_asset_kinds=["openvdb"],
        external_asset_sources=[str(vdb_source)],
        default_prim=0,
    )


def test_all_typed_3d_cv_payloads_coexist_in_one_stage(tmp_path):
    vdb = tmp_path / "density.vdb"
    vdb.write_bytes(b"dependency-only")
    path = tmp_path / "mixed.usda"

    sceneio.write_scene(
        _mixed_scene(vdb),
        path,
        package_assets=False,
    )

    oracle = tinyusdz.load(str(path))
    type_names = [prim.type_name for prim in tinyusdz.traverse(oracle)]
    for expected in (
        "Mesh",
        "Points",
        "ParticleField3DGaussianSplat",
        "Camera",
        "Volume",
        "OpenVDBAsset",
        "PointInstancer",
    ):
        assert type_names.count(expected) == 1
    decoded = sceneio.read_scene(path)
    assert decoded.num_meshes == 1
    assert decoded.num_point_clouds == 1
    assert decoded.num_gaussian_clouds == 1
    assert decoded.num_cameras == 1
    assert decoded.num_volumes == 1
    assert decoded.num_instance_sets == 1
    assert decoded.node_semantic_labels == ["scene"] * 7
    assert decoded.instance_set_at(0).prototype_nodes.tolist() == [1]
