"""Record-level contracts for dense-MVS normal and CSR carriers."""

from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def test_normal_map_factory_metadata_and_owner_lifetime():
    source = np.arange(24, dtype=np.float32).reshape(2, 4, 3)
    record = _core.normal_map(source)
    view = record.normals
    assert view.shape == (2, 4, 3)
    assert view.dtype == np.float32
    np.testing.assert_array_equal(view, source)
    assert record.coordinate_system == "opencv_camera"
    assert record.component_order == "xyz"
    assert record.row_order == "top_to_bottom"
    assert record.invalid_policy == "zero_vector"
    assert record.orientation == "opposes_camera_to_surface_ray"
    assert repr(record) == (
        "<NormalMap 2x4 opencv_camera xyz invalid=zero_vector>"
    )
    del record
    gc.collect()
    np.testing.assert_array_equal(view, source)


@pytest.mark.parametrize(
    ("source", "match"),
    [
        (np.zeros((2, 3), np.float32), r"\(H,W,3\)"),
        (np.zeros((2, 3, 2), np.float32), r"\(H,W,3\)"),
        (np.zeros((0, 3, 3), np.float32), "dimensions must be positive"),
        (np.zeros((2, 3, 3), np.float64), "must be float32"),
    ],
)
def test_normal_map_factory_guards(source, match):
    with pytest.raises(ValueError, match=match):
        _core.normal_map(source)


def test_consistency_graph_factory_preserves_order_zero_rows_and_duplicates():
    graph = _core.consistency_graph(
        2,
        3,
        np.array([0, 0, 1, 0], np.uint32),
        np.array([0, 2, 1, 0], np.uint32),
        np.array([0, 2, 3, 3, 4], np.uint64),
        np.array([7, 3, 5, 9], np.uint32),
    )
    assert graph.height == 2
    assert graph.width == 3
    assert graph.num_entries == 4
    assert graph.num_image_indices == 4
    assert graph.index_domain == "mvs_sequential_image_index"
    assert graph.rows.tolist() == [0, 0, 1, 0]
    assert graph.columns.tolist() == [0, 2, 1, 0]
    assert graph.offsets.tolist() == [0, 2, 3, 3, 4]
    assert graph.image_indices.tolist() == [7, 3, 5, 9]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        (
            {"height": 0},
            "dimensions must be positive",
        ),
        (
            {"rows": np.array([2], np.uint32)},
            "outside the raster",
        ),
        (
            {"offsets": np.array([1, 1], np.uint64)},
            "offsets must begin at zero",
        ),
        (
            {"image_indices": np.array([2**31], np.uint32)},
            "image index exceeds",
        ),
    ],
)
def test_consistency_graph_factory_guards(kwargs, match):
    values = {
        "height": 2,
        "width": 3,
        "rows": np.array([0], np.uint32),
        "columns": np.array([1], np.uint32),
        "offsets": np.array([0, 1], np.uint64),
        "image_indices": np.array([2], np.uint32),
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=match):
        _core.consistency_graph(**values)


def test_point_visibility_factory_empty_rows_and_owner_lifetime():
    record = _core.point_visibility(
        np.array([0, 2, 2, 3], np.uint64),
        np.array([4, 1, 7], np.uint32),
    )
    offsets = record.offsets
    indices = record.image_indices
    assert record.num_points == 3
    assert record.num_image_indices == 3
    assert record.index_domain == "mvs_sequential_image_index"
    del record
    gc.collect()
    assert offsets.tolist() == [0, 2, 2, 3]
    assert indices.tolist() == [4, 1, 7]


def test_dense_records_are_public():
    assert sceneio.NormalMap is _core.NormalMap
    assert sceneio.ConsistencyGraph is _core.ConsistencyGraph
    assert sceneio.PointVisibility is _core.PointVisibility
    assert not hasattr(sceneio.io, "NormalMap")


def test_depth_convention_is_additive_and_guarded():
    record = _core.depth_map(
        np.ones((1, 2), np.float32),
        unit="unknown",
        invalid_policy="nonpositive",
        depth_convention="camera_z",
    )
    assert record.depth_convention == "camera_z"
    with pytest.raises(ValueError, match="depth_convention"):
        _core.depth_map(
            np.ones((1, 1), np.float32),
            depth_convention="diagonal",
        )
