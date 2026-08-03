"""Independent SciPy-backed oracles for coordinate conversion semantics.

The formulas in this module intentionally do not import SceneIO's private
conversion helpers.  SciPy stores quaternions in XYZW order and exposes the
usual active rotation matrix, which gives this suite an independent check for
component order, pose direction, basis changes, and unit scaling.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import product

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

import sceneio
from sceneio import _core


def _as_xyzw(quaternion: np.ndarray, order: str) -> np.ndarray:
    if order == "xyzw":
        return np.asarray(quaternion, dtype=np.float64)
    if order == "wxyz":
        return np.asarray(quaternion, dtype=np.float64)[[1, 2, 3, 0]]
    raise AssertionError(order)


def _as_order(quaternion: np.ndarray, order: str) -> np.ndarray:
    if order == "xyzw":
        return np.asarray(quaternion, dtype=np.float64)
    if order == "wxyz":
        return np.asarray(quaternion, dtype=np.float64)[[3, 0, 1, 2]]
    raise AssertionError(order)


def _pose_matrix(
    quaternion: np.ndarray,
    translation: np.ndarray,
    order: str,
    direction: str,
    scale: float,
) -> np.ndarray:
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = Rotation.from_quat(_as_xyzw(quaternion, order)).as_matrix()
    matrix[:3, 3] = np.asarray(translation, dtype=np.float64) * scale
    if direction == "camera_to_world":
        return np.linalg.inv(matrix)
    assert direction == "world_to_camera"
    return matrix


def _record_matrix(record: object) -> np.ndarray:
    """Return a record's physical world-to-camera matrix."""

    return _pose_matrix(
        np.asarray(record.quaternions)[0],
        np.asarray(record.translations)[0],
        str(record.quaternion_order),
        str(record.pose_convention),
        float(record.scale_to_meters),
    )


def _basis(source: str, target: str) -> np.ndarray:
    if source == target:
        return np.eye(4, dtype=np.float64)
    assert {source, target} == {"opencv", "opengl"}
    return np.diag((1.0, -1.0, -1.0, 1.0))


@pytest.mark.parametrize(
    ("source_axes", "target_axes", "source_direction", "target_direction", "source_order", "target_order"),
    tuple(
        product(
            ("opencv", "opengl"),
            ("opencv", "opengl"),
            ("world_to_camera", "camera_to_world"),
            ("world_to_camera", "camera_to_world"),
            ("wxyz", "xyzw"),
            ("wxyz", "xyzw"),
        )
    ),
)
def test_scipy_pose_oracle_covers_axis_pose_and_quaternion_layout(
    source_axes,
    target_axes,
    source_direction,
    target_direction,
    source_order,
    target_order,
):
    source_scale = 0.02
    target_scale = 0.125
    source_w2c = np.eye(4, dtype=np.float64)
    source_w2c[:3, :3] = Rotation.from_euler("xyz", (23.0, -37.0, 61.0), degrees=True).as_matrix()
    source_w2c[:3, 3] = (1.25, -2.5, 4.75)
    source_pose = (
        source_w2c
        if source_direction == "world_to_camera"
        else np.linalg.inv(source_w2c)
    )
    source_xyzw = Rotation.from_matrix(source_pose[:3, :3]).as_quat()
    source_quaternion = _as_order(source_xyzw, source_order)
    source = _core.posed_view_set(
        source_quaternion[None],
        (source_pose[:3, 3] / source_scale)[None],
        quaternion_order=source_order,
        pose_convention=source_direction,
        axis_frame=source_axes,
        scale_to_meters=source_scale,
    )
    target = replace(
        sceneio.COLMAP_COORDINATES,
        name="scipy_oracle_target",
        camera_axes=target_axes,
        pose_direction=target_direction,
        quaternion_order=target_order,
        scale_class="metric",
        scale_to_meters=target_scale,
    )

    converted = sceneio.convert_coordinates(source, target=target)
    expected_w2c = _basis(source_axes, target_axes) @ source_w2c
    np.testing.assert_allclose(
        _record_matrix(converted), expected_w2c, atol=2e-12, rtol=0.0
    )

    restored = sceneio.convert_coordinates(converted, target=source.coordinates)
    np.testing.assert_allclose(
        _record_matrix(restored), source_w2c, atol=2e-12, rtol=0.0
    )


def test_scipy_pose_oracle_checks_world_transform_composition():
    source_scale = 0.01
    target_scale = 0.25
    source_w2c = np.eye(4, dtype=np.float64)
    source_w2c[:3, :3] = Rotation.from_euler("zyx", (-19.0, 31.0, 47.0), degrees=True).as_matrix()
    source_w2c[:3, 3] = (-3.0, 1.75, 9.25)
    source_pose = np.linalg.inv(source_w2c)
    source_xyzw = Rotation.from_matrix(source_pose[:3, :3]).as_quat()
    source = _core.posed_view_set(
        _as_order(source_xyzw, "xyzw")[None],
        (source_pose[:3, 3] / source_scale)[None],
        quaternion_order="xyzw",
        pose_convention="camera_to_world",
        axis_frame="opengl",
        scale_to_meters=source_scale,
    )
    target = replace(
        sceneio.COLMAP_COORDINATES,
        name="scipy_world_target",
        scale_class="metric",
        scale_to_meters=target_scale,
    )
    world_transform = np.eye(4, dtype=np.float64)
    world_transform[:3, :3] = Rotation.from_euler("xyz", (11.0, 29.0, -13.0), degrees=True).as_matrix()
    world_transform[:3, 3] = (0.3, -0.4, 0.7)

    converted = sceneio.convert_coordinates(
        source,
        target=target,
        world_transform=world_transform,
    )
    expected_w2c = (
        _basis("opengl", "opencv")
        @ source_w2c
        @ np.linalg.inv(world_transform)
    )
    np.testing.assert_allclose(_record_matrix(converted), expected_w2c, atol=2e-12, rtol=0.0)


def test_scipy_spatial_oracle_checks_enu_ned_points_normals_and_widths():
    source = _core.point_cloud(
        np.array(
            [[1.25, -2.5, 4.75], [-3.0, 0.5, 2.0]],
            dtype=np.float64,
        ),
        normals=np.array([[0.2, 0.7, 0.6], [-0.9, 0.1, 0.4]], dtype=np.float32),
        widths=np.array([2.0, 3.5], dtype=np.float32),
        coordinate_frame="enu",
        scale_to_meters=0.01,
    )
    target = sceneio.CoordinateConvention(
        name="scipy_ned_target",
        camera_axes="unknown",
        handedness="right_handed",
        world_frame="ned",
        up_axis="unknown",
        scale_class="metric",
        scale_to_meters=0.1,
    )
    converted = sceneio.convert_coordinates(source, target=target)
    basis = np.array(
        ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
        dtype=np.float64,
    )
    expected_positions = np.asarray(source.positions, dtype=np.float32) @ (
        basis * 0.1
    ).T
    np.testing.assert_allclose(
        converted.positions, expected_positions, atol=2e-7, rtol=0.0
    )

    expected_normals = np.asarray(source.normals, dtype=np.float64) @ basis.T
    expected_normals /= np.linalg.norm(expected_normals, axis=1, keepdims=True)
    np.testing.assert_allclose(converted.normals, expected_normals, atol=2e-7, rtol=0.0)
    np.testing.assert_allclose(converted.widths, np.asarray(source.widths) * 0.1, atol=1e-7, rtol=0.0)
    assert converted.coordinate_frame == "ned"
    assert converted.scale_to_meters == target.scale_to_meters
