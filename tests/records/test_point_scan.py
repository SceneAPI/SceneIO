"""Native stored-row PointScan and ordered ScanSet record contracts."""

from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
import sceneio.io
from sceneio import _core
from sceneio.representations import representation_contract


def _cloud(n: int = 4, **kwargs):
    positions = np.arange(n * 3, dtype=np.float32).reshape(n, 3)
    colors = np.arange(n * 3, dtype=np.uint8).reshape(n, 3)
    intensity = np.arange(n, dtype=np.float32)
    return _core.point_cloud(positions, colors=colors, intensity=intensity, **kwargs)


def test_point_scan_preserves_stored_rows_and_metadata():
    cloud = _cloud(
        coordinate_frame="enu",
        scale_to_meters=0.01,
        intensity_range="u16",
        origin=np.array([1000.0, 2000.0, 3.0], dtype=np.float64),
    )
    invalid = np.array([0, 3, 0, 255], dtype=np.uint8)
    rows = np.array([10, 11, 15, 20], dtype=np.int64)
    columns = np.array([4, 5, 4, 8], dtype=np.int64)
    scan = _core.point_scan(
        cloud,
        scan_id=2**63 - 1,
        invalid_states=invalid,
        row_indices=rows,
        column_indices=columns,
        row_minimum=None,
        row_maximum=None,
        column_minimum=None,
        column_maximum=None,
        name="scan-2",
        guid="guid-2",
        timestamp=123.5,
        viewpoint=np.array([1.0, 2.0, 3.0, 1.0, 0.0, 0.0, 0.0]),
    )
    assert scan.scan_id == 2**63 - 1
    assert scan.name == "scan-2" and scan.guid == "guid-2"
    assert scan.has_timestamp and scan.timestamp == 123.5
    assert scan.has_invalid_states and scan.has_row_column_indices
    assert scan.row_minimum == 10 and scan.row_maximum == 20
    assert scan.column_minimum == 4 and scan.column_maximum == 8
    assert scan.num_stored_points == 4 and scan.num_valid_points == 2
    np.testing.assert_array_equal(scan.invalid_states, invalid)
    np.testing.assert_array_equal(scan.row_indices, rows)
    np.testing.assert_array_equal(scan.column_indices, columns)
    assert scan.point_cloud.viewpoint == (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
    assert scan.coordinate_frame == "enu"
    assert scan.scale_to_meters == 0.01
    assert scan.intensity_range == "u16"
    assert scan.origin == (1000.0, 2000.0, 3.0)
    assert scan.pose_convention == "scan_to_reference"
    assert scan.quaternion_order == "wxyz"


def test_absent_stored_row_arrays_are_shaped_empty_and_presence_is_explicit():
    scan = _core.point_scan(_cloud(3))
    assert not scan.has_invalid_states
    assert not scan.has_row_indices and not scan.has_column_indices
    assert not scan.has_row_column_indices
    assert scan.invalid_states.shape == (0,)
    assert scan.row_indices.shape == (0,)
    assert scan.column_indices.shape == (0,)
    with pytest.raises(IndexError):
        _ = scan.invalid_states[0]


def test_empty_scan_can_retain_explicit_source_bounds():
    empty = _core.point_cloud(np.empty((0, 3), dtype=np.float32))
    scan = _core.point_scan(
        empty,
        invalid_states=np.empty(0, dtype=np.uint8),
        row_indices=np.empty(0, dtype=np.int64),
        column_indices=np.empty(0, dtype=np.int64),
        row_minimum=100,
        row_maximum=200,
        column_minimum=20,
        column_maximum=40,
    )
    assert scan.has_invalid_states and scan.has_row_column_indices
    assert scan.row_minimum == 100 and scan.row_maximum == 200
    assert scan.column_minimum == 20 and scan.column_maximum == 40
    assert scan.invalid_states.shape == (0,)
    assert scan.valid_point_cloud().num_points == 0


def test_dense_bounds_use_row_extent_and_single_column():
    scan = _core.point_scan(_cloud(4))
    assert (scan.row_minimum, scan.row_maximum) == (0, 3)
    assert (scan.column_minimum, scan.column_maximum) == (0, 0)


def test_valid_projection_is_owned_and_preserves_fields():
    cloud = _cloud(
        coordinate_frame="opencv",
        scale_to_meters=0.25,
        intensity_range="unit",
        origin=np.array([5.0, 6.0, 7.0], dtype=np.float64),
        display_colors=np.ones((4, 3), dtype=np.float32),
        display_opacities=np.full(4, 0.5, dtype=np.float32),
        widths=np.arange(4, dtype=np.float32),
        ids=np.arange(4, dtype=np.int64),
        velocities=np.ones((4, 3), dtype=np.float32),
        accelerations=np.full((4, 3), 2.0, dtype=np.float32),
        display_color_space="srgb",
    )
    scan = _core.point_scan(
        cloud,
        invalid_states=np.array([0, 9, 0, 0], dtype=np.uint8),
        viewpoint=np.array([9.0, 8.0, 7.0, 1.0, 0.0, 0.0, 0.0]),
    )
    projected = scan.valid_point_cloud()
    assert projected is not scan.point_cloud
    assert projected.positions.ctypes.data != scan.point_cloud.positions.ctypes.data
    np.testing.assert_array_equal(projected.positions, cloud.positions[[0, 2, 3]])
    np.testing.assert_array_equal(projected.colors, cloud.colors[[0, 2, 3]])
    np.testing.assert_array_equal(projected.intensities, cloud.intensities[[0, 2, 3]])
    np.testing.assert_array_equal(projected.display_colors, cloud.display_colors[[0, 2, 3]])
    np.testing.assert_array_equal(projected.ids, cloud.ids[[0, 2, 3]])
    assert projected.coordinate_frame == "opencv"
    assert projected.scale_to_meters == 0.25
    assert projected.origin == (5.0, 6.0, 7.0)
    assert projected.viewpoint == scan.viewpoint
    # The projection has independent storage and does not mutate the child.
    projected.positions[0, 0] = -100.0
    assert scan.point_cloud.positions[0, 0] != -100.0


def test_point_scan_view_owns_scan_after_gc():
    expected = np.array([0, 1, 2], dtype=np.uint8)
    states = _core.point_scan(
        _cloud(3), invalid_states=expected
    ).invalid_states
    gc.collect()
    np.testing.assert_array_equal(states, expected)


def test_point_scan_rejects_conflicting_or_invalid_inputs():
    nonneutral_pose = _core.point_cloud(
        np.zeros((1, 3), dtype=np.float32), viewpoint=np.array([1, 0, 0, 1, 0, 0, 0], np.float64)
    )
    with pytest.raises(ValueError, match=r"viewpoint.*neutral"):
        _core.point_scan(nonneutral_pose)
    organized = _core.point_cloud(
        np.zeros((4, 3), dtype=np.float32), width=2, height=2
    )
    with pytest.raises(ValueError, match="organization"):
        _core.point_scan(organized)
    with pytest.raises(ValueError, match="provided together"):
        _core.point_scan(_cloud(2), row_indices=np.zeros(2, np.int64))
    with pytest.raises(ValueError, match="outside declared"):
        _core.point_scan(
            _cloud(2),
            row_indices=np.array([4, 9], np.int64),
            column_indices=np.array([0, 0], np.int64),
            row_minimum=4,
            row_maximum=8,
        )
    with pytest.raises(ValueError, match="unit"):
        _core.point_scan(
            _cloud(1), viewpoint=np.array([0, 0, 0, 2, 0, 0, 0], np.float64)
        )
    with pytest.raises(ValueError, match="timestamp"):
        _core.point_scan(_cloud(1), timestamp=np.inf)


def test_scan_set_is_ordered_and_rejects_duplicate_ids_or_guids():
    first = _core.point_scan(_cloud(1), scan_id=9, guid="g9", name="first")
    second = _core.point_scan(_cloud(1), scan_id=3, guid="g3", name="second")
    scans = _core.scan_set([first, second])
    assert scans.num_scans == 2 and len(scans) == 2
    np.testing.assert_array_equal(scans.scan_ids, [9, 3])
    assert [scan.scan_id for scan in scans.scans] == [9, 3]
    assert scans.scan_at(0).name == "first"
    with pytest.raises(IndexError):
        scans.scan_at(2)
    with pytest.raises(ValueError, match="scan ids"):
        _core.scan_set([first, _core.point_scan(_cloud(1), scan_id=9)])
    with pytest.raises(ValueError, match="guids"):
        _core.scan_set([first, _core.point_scan(_cloud(1), scan_id=10, guid="g9")])
    empty = _core.scan_set([])
    assert empty.num_scans == 0 and empty.scans == []


def test_public_exports_coordinates_and_normalization_contracts():
    assert sceneio.PointScan is _core.PointScan
    assert sceneio.ScanSet is _core.ScanSet
    assert not hasattr(sceneio.io, "PointScan")
    assert not hasattr(sceneio.io, "ScanSet")
    scan = _core.point_scan(_cloud(1))
    assert scan.coordinates.pose_direction == "sensor_to_reference"
    assert scan.coordinates.quaternion_order == "wxyz"
    assert _core.scan_set([scan]).coordinates.name == "scan_set"
    assert representation_contract(sceneio.PointScan).profile.id == "point_scan"
    assert representation_contract(sceneio.ScanSet).profile.id == "scan_set"
