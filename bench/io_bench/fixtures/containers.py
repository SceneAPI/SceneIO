"""Deterministic path-native container and interchange fixtures."""

from __future__ import annotations

import numpy as np

import sceneio
from sceneio import _core


def _hdf5_fixture(scale):
    side = max(8, int(512 * scale**0.5))
    arrays = {
        "dense/values": np.random.default_rng(80)
        .standard_normal((side, side))
        .astype(np.float32),
        "ids": np.arange(side, dtype=np.int64),
        "valid": np.arange(side, dtype=np.uint32) % 3 == 0,
    }
    attrs = {"producer": "SceneIO benchmark", "schema": "numeric-v1"}
    return _core.tensor_dict(arrays, attrs), {
        "arrays": arrays,
        "attrs": attrs,
    }


def _hloc_feature_fixture(scale):
    count = max(16, int(8192 * scale))
    rng = np.random.default_rng(81)
    keypoints = np.column_stack(
        (
            rng.random(count, dtype=np.float32) * 1920,
            rng.random(count, dtype=np.float32) * 1080,
        )
    )
    descriptors = rng.standard_normal((count, 64)).astype(np.float16)
    scores = rng.random(count, dtype=np.float32)
    name = "benchmark-image.jpg"
    feature = _core.feature_set(
        keypoints,
        descriptors,
        scores,
        image_name=name,
        image_size=(1920, 1080),
    )
    payload = {
        name: {
            "keypoints": keypoints,
            "descriptors": descriptors,
            "scores": scores,
            "image_size": np.array([1920, 1080], np.int64),
            "uncertainty": 0.5,
        }
    }
    return sceneio.HlocFeatureStore(
        {name: feature},
        {name: 0.5},
    ), payload


def _hloc_match_fixture(scale):
    source_count = max(32, int(262_144 * scale))
    source_indices = np.arange(0, source_count, 4, dtype=np.uint32)
    target_indices = source_indices[::-1].copy()
    matches = np.column_stack((source_indices, target_indices))
    scores = np.linspace(
        0.25,
        1.0,
        len(matches),
        dtype=np.float32,
    )
    graph = _core.match_graph(
        np.array([[1, 2]], np.uint32),
        np.array([0, len(matches)], np.uint64),
        matches,
        np.zeros(2, np.uint64),
        np.empty((0, 2), np.uint32),
        scores=scores,
        match_score_present=np.ones(1, np.uint8),
        match_present=np.ones(1, np.uint8),
        geometry_present=np.zeros(1, np.uint8),
    )
    names = ("benchmark-a.jpg", "benchmark-b.jpg")
    pair = (names,)
    store = sceneio.HlocMatchStore(
        names,
        pair,
        (source_count,),
        ("int32",),
        ("float32",),
        graph,
    )
    dense = np.full(source_count, -1, dtype=np.int32)
    dense[source_indices] = target_indices.astype(np.int32)
    dense_scores = np.zeros(source_count, dtype=np.float32)
    dense_scores[source_indices] = scores
    payload = {
        pair[0]: {
            "matches0": dense,
            "matching_scores0": dense_scores,
        }
    }
    return store, payload


def _e57_fixture(scale):
    count = max(16, int(262_144 * scale))
    index = np.arange(count, dtype=np.float32)
    positions = np.column_stack(
        (
            index / np.float32(8),
            np.sin(index / np.float32(257)),
            np.cos(index / np.float32(509)),
        )
    ).astype(np.float32, copy=False)
    colors = np.column_stack(
        (
            np.arange(count, dtype=np.uint32) % 251,
            np.arange(count, dtype=np.uint32) * 3 % 253,
            np.arange(count, dtype=np.uint32) * 7 % 255,
        )
    ).astype(np.uint8)
    intensity = np.linspace(-2, 3, count, dtype=np.float32)
    viewpoint = np.array(
        [1.25, -2.5, 3.75, 0.9238795325, 0.0, 0.3826834324, 0.0],
        dtype=np.float64,
    )
    record = _core.point_cloud(
        positions,
        colors=colors,
        intensity=intensity,
        viewpoint=viewpoint,
    )
    return record, {
        "positions": positions,
        "colors": colors,
        "intensity": intensity,
        "viewpoint": viewpoint,
    }


def _columnar_fixture(scale):
    count = max(32, int(131_072 * scale))
    rng = np.random.default_rng(82)
    arrays = {
        "image_id": np.arange(count, dtype=np.uint32),
        "xy": rng.random((count, 2), dtype=np.float32),
        "descriptor": rng.standard_normal((count, 32)).astype(np.float32),
        "inlier": np.arange(count, dtype=np.uint32) % 3 == 0,
    }
    attrs = {"coordinate_order": "xy", "role": "features"}
    return _core.tensor_dict(arrays, attrs), {
        "arrays": arrays,
        "attrs": attrs,
    }


def _openvdb_fixture(scale):
    # TinyVDB 0.9's sparse builder currently has a topology-size limit.
    # Keep the timed fixture inside its exact-preservation range; the adapter
    # verifies the rebuilt active count and refuses any provider voxel loss.
    count = max(16, min(4_096, int(32_768 * scale)))
    linear = np.arange(count, dtype=np.int32)
    side = np.int32(128)
    coords = np.column_stack(
        (
            linear % side,
            (linear // side) % side,
            linear // (side * side),
        )
    ).astype(np.int32, copy=False)
    values = np.sin(linear.astype(np.float32) / np.float32(97))
    record = _core.tensor_dict(
        {"coords": coords, "values": values},
        attrs={"name": "tsdf"},
    )
    return record, {
        "arrays": {"coords": coords, "values": values},
        "attrs": {"name": "tsdf"},
    }


def _usd_fixture(scale):
    face_count = max(1, int(25_000 * scale))
    vertex_count = face_count * 3
    positions = np.arange(vertex_count * 3, dtype=np.float32).reshape(
        vertex_count, 3
    )
    positions /= np.float32(1024)
    normals = np.zeros((vertex_count, 3), dtype=np.float32)
    normals[:, 2] = 1
    uvs = np.arange(vertex_count * 2, dtype=np.float32).reshape(
        vertex_count, 2
    )
    uvs /= np.float32(max(1, vertex_count))
    face_offsets = np.arange(
        0, vertex_count + 1, 3, dtype=np.uint64
    )
    face_indices = np.arange(vertex_count, dtype=np.uint64)
    mesh = _core.mesh(
        positions,
        face_offsets,
        face_indices,
        vertex_normals=normals,
        vertex_uvs=uvs,
        coordinate_frame="opengl",
    )
    scene = _core.mesh_scene(
        [mesh],
        np.array([0, 1], dtype=np.uint64),
        node_meshes=np.array([0], dtype=np.int64),
        node_child_offsets=np.array([0, 0], dtype=np.uint64),
        node_children=np.empty(0, dtype=np.uint64),
        node_local_transforms=np.eye(4, dtype=np.float64)[None],
        node_names=["Surface"],
        scene_root_offsets=np.array([0, 1], dtype=np.uint64),
        scene_roots=np.array([0], dtype=np.uint64),
        default_scene=0,
    )
    return scene, {
        "arrays": {
            "positions": positions,
            "face_offsets": face_offsets,
            "face_indices": face_indices,
            "vertex_normals": normals,
            "vertex_uvs": uvs,
        },
        "attrs": {"node_name": "Surface"},
    }


__all__ = [
    "_columnar_fixture",
    "_e57_fixture",
    "_hdf5_fixture",
    "_hloc_feature_fixture",
    "_hloc_match_fixture",
    "_openvdb_fixture",
    "_usd_fixture",
]
