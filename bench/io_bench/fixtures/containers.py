"""Deterministic HDF5 and hloc benchmark fixtures."""

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


__all__ = [
    "_hdf5_fixture",
    "_hloc_feature_fixture",
    "_hloc_match_fixture",
]
