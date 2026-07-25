"""PoseGraph contract, validation, zero-copy views, and lifetime coverage."""

from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _arrays(nodes: int = 3, edges: int = 2):
    node_ids = np.arange(10, 10 + nodes, dtype=np.int64)
    node_translations = np.arange(nodes * 3, dtype=np.float64).reshape(nodes, 3)
    node_quaternions = np.zeros((nodes, 4), dtype=np.float64)
    node_quaternions[:, 3] = 1.0
    if edges:
        edge_endpoints = np.column_stack(
            (
                node_ids[np.arange(edges) % nodes],
                node_ids[(np.arange(edges) + 1) % nodes],
            )
        ).astype(np.int64)
    else:
        edge_endpoints = np.empty((0, 2), dtype=np.int64)
    edge_translations = np.arange(edges * 3, dtype=np.float64).reshape(edges, 3)
    edge_quaternions = np.zeros((edges, 4), dtype=np.float64)
    edge_quaternions[:, 3] = 1.0
    information = np.zeros((edges, 6, 6), dtype=np.float64)
    for edge in range(edges):
        upper = np.arange(1, 22, dtype=np.float64) + edge * 100
        index = 0
        for row in range(6):
            for column in range(row, 6):
                information[edge, row, column] = upper[index]
                information[edge, column, row] = upper[index]
                index += 1
    return (
        node_ids,
        node_translations,
        node_quaternions,
        edge_endpoints,
        edge_translations,
        edge_quaternions,
        information,
    )


def _make(nodes: int = 3, edges: int = 2, **kwargs):
    return _core.pose_graph(
        *_arrays(nodes, edges),
        fixed=np.arange(nodes, dtype=np.uint8) % 2,
        **kwargs,
    )


def test_public_type_shapes_dtypes_and_metadata():
    graph = _make()
    assert isinstance(graph, sceneio.PoseGraph)
    assert isinstance(graph, sceneio.io.PoseGraph)
    assert graph.num_nodes == 3
    assert graph.num_edges == 2
    assert graph.node_ids.shape == (3,)
    assert graph.node_ids.dtype == np.int64
    assert graph.node_translations.shape == (3, 3)
    assert graph.node_quaternions.shape == (3, 4)
    assert graph.fixed.shape == (3,)
    assert graph.fixed.dtype == np.uint8
    assert graph.edge_endpoints.shape == (2, 2)
    assert graph.edge_endpoints.dtype == np.int64
    assert graph.edge_translations.shape == (2, 3)
    assert graph.edge_quaternions.shape == (2, 4)
    assert graph.information_matrices.shape == (2, 6, 6)
    assert graph.node_types == ["se3"] * 3
    assert graph.edge_types == ["se3"] * 2
    assert graph.quaternion_order == "xyzw"
    assert graph.quaternion_sign == "preserved"
    assert graph.node_transform_convention == "node_to_reference"
    assert graph.edge_transform_convention == "source_inverse_times_target"
    assert graph.translation_unit == "unspecified"
    assert graph.information_variable_order == "tx_ty_tz_qx_qy_qz"
    assert graph.information_storage == "symmetric_6x6"
    assert "PoseGraph nodes=3 edges=2" in repr(graph)


def test_factory_copies_sources_and_views_keep_record_alive():
    arrays = list(_arrays())
    source_ids = arrays[0]
    source_information = arrays[6]
    expected_ids = source_ids.copy()
    expected_information = source_information.copy()
    graph = _core.pose_graph(*arrays)
    source_ids[:] = 0
    source_information[:] = 0
    np.testing.assert_array_equal(graph.node_ids, expected_ids)
    np.testing.assert_array_equal(graph.information_matrices, expected_information)

    view = graph.information_matrices
    del graph
    gc.collect()
    np.testing.assert_array_equal(view, expected_information)


def test_all_array_views_export_dlpack():
    graph = _make()
    for name in (
        "node_ids",
        "node_translations",
        "node_quaternions",
        "fixed",
        "edge_endpoints",
        "edge_translations",
        "edge_quaternions",
        "information_matrices",
    ):
        view = getattr(graph, name)
        assert hasattr(view, "__dlpack__")
        assert np.from_dlpack(view).shape == view.shape


def test_empty_graph_has_non_null_views_and_default_types():
    graph = _core.pose_graph(*_arrays(0, 0))
    assert graph.num_nodes == graph.num_edges == 0
    assert graph.node_ids.shape == (0,)
    assert graph.node_translations.shape == (0, 3)
    assert graph.edge_endpoints.shape == (0, 2)
    assert graph.information_matrices.shape == (0, 6, 6)
    assert graph.node_types == []
    assert graph.edge_types == []
    assert graph.node_ids.__array_interface__["data"][0] != 0
    assert graph.information_matrices.__array_interface__["data"][0] != 0


def test_explicit_empty_optional_fields_are_safe():
    graph = _core.pose_graph(
        *_arrays(0, 0),
        fixed=np.empty(0, np.uint8),
        node_types=[],
        edge_types=[],
    )
    assert graph.num_nodes == graph.num_edges == 0


@pytest.mark.parametrize(
    ("index", "replacement", "message"),
    [
        (0, np.zeros((2, 1), np.int64), "node_ids"),
        (1, np.zeros((3, 2), np.float64), "node_translations"),
        (2, np.zeros((3, 3), np.float64), "node_quaternions"),
        (3, np.zeros((2, 3), np.int64), "edge_endpoints"),
        (4, np.zeros((2, 2), np.float64), "edge_translations"),
        (5, np.zeros((2, 3), np.float64), "edge_quaternions"),
        (6, np.zeros((2, 6, 5), np.float64), "information_matrices"),
    ],
)
def test_shape_validation(index, replacement, message):
    arrays = list(_arrays())
    arrays[index] = replacement
    with pytest.raises((TypeError, ValueError), match=message):
        _core.pose_graph(*arrays)


def test_duplicate_ids_and_missing_endpoints_reject():
    arrays = list(_arrays())
    arrays[0][1] = arrays[0][0]
    with pytest.raises(ValueError, match="unique"):
        _core.pose_graph(*arrays)

    arrays = list(_arrays())
    arrays[3][0, 1] = 999
    with pytest.raises(ValueError, match="endpoint"):
        _core.pose_graph(*arrays)


@pytest.mark.parametrize("value", [2, 255])
def test_noncanonical_fixed_flags_reject(value):
    with pytest.raises(ValueError, match="canonical 0 or 1"):
        _core.pose_graph(
            *_arrays(),
            fixed=np.array([0, value, 0], np.uint8),
        )


def test_type_counts_empty_names_and_controls_reject():
    with pytest.raises(ValueError, match="node_types"):
        _core.pose_graph(*_arrays(), node_types=["se3"])
    with pytest.raises(ValueError, match="non-empty"):
        _core.pose_graph(*_arrays(), edge_types=["", "se3"])
    with pytest.raises(ValueError, match="control"):
        _core.pose_graph(*_arrays(), node_types=["se3", "bad\n", "se3"])


@pytest.mark.parametrize("array_index", [1, 4, 6])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_numeric_values_reject(array_index, value):
    arrays = list(_arrays())
    arrays[array_index].flat[0] = value
    with pytest.raises(ValueError, match="finite"):
        _core.pose_graph(*arrays)


@pytest.mark.parametrize("array_index", [2, 5])
def test_nonunit_quaternions_reject(array_index):
    arrays = list(_arrays())
    arrays[array_index][0] = [0, 0, 0, 2]
    with pytest.raises(ValueError, match="unit length"):
        _core.pose_graph(*arrays)


def test_asymmetric_information_rejects_without_symmetrizing():
    arrays = list(_arrays())
    arrays[6][0, 1, 0] += 1
    with pytest.raises(ValueError, match="symmetric"):
        _core.pose_graph(*arrays)


def test_signed_zero_information_must_be_bitwise_symmetric():
    arrays = list(_arrays())
    arrays[6][0, 0, 1] = -0.0
    arrays[6][0, 1, 0] = 0.0
    with pytest.raises(ValueError, match="bitwise symmetric"):
        _core.pose_graph(*arrays)

    arrays[6][0, 1, 0] = -0.0
    graph = _core.pose_graph(*arrays)
    assert np.signbit(graph.information_matrices[0, 0, 1])
    assert np.signbit(graph.information_matrices[0, 1, 0])


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("quaternion_order", "bad", "quaternion_order"),
        ("quaternion_sign", "bad", "quaternion_sign"),
        ("node_transform_convention", "bad", "node_transform_convention"),
        ("edge_transform_convention", "bad", "edge_transform_convention"),
        ("translation_unit", "feet", "translation_unit"),
        ("information_variable_order", "rotation_first", "information_variable_order"),
    ],
)
def test_closed_metadata_validation(keyword, value, message):
    with pytest.raises(ValueError, match=message):
        _make(**{keyword: value})


def test_canonical_positive_w_policy_uses_declared_order():
    arrays = list(_arrays())
    arrays[2][0] = [0, 0, 0, -1]
    with pytest.raises(ValueError, match="nonnegative W"):
        _core.pose_graph(
            *arrays,
            quaternion_sign="canonical_positive_w",
        )

    arrays = list(_arrays())
    arrays[2] = np.roll(arrays[2], 1, axis=1)
    arrays[5] = np.roll(arrays[5], 1, axis=1)
    arrays[2][0, 0] = -1
    with pytest.raises(ValueError, match="nonnegative W"):
        _core.pose_graph(
            *arrays,
            quaternion_order="wxyz",
            quaternion_sign="canonical_positive_w",
        )
