"""StateTrajectory SoA contract, metadata, and lifetime tests."""

from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _arrays(count: int = 4):
    timestamps = 1_403_636_580_000_000_000 + np.arange(
        count, dtype=np.int64
    )
    positions = np.arange(count * 3, dtype=np.float64).reshape(count, 3)
    quaternions = np.zeros((count, 4), dtype=np.float64)
    quaternions[:, 0] = 1.0
    velocities = positions + 100.0
    gyro_biases = positions / 1000.0
    accel_biases = positions / 100.0
    return (
        timestamps,
        positions,
        quaternions,
        velocities,
        gyro_biases,
        accel_biases,
    )


def _make(count: int = 4, **metadata):
    return _core.state_trajectory(*_arrays(count), **metadata)


def test_public_type_and_fixed_shapes():
    trajectory = _make()
    assert isinstance(trajectory, sceneio.StateTrajectory)
    assert not hasattr(sceneio.io, "StateTrajectory")
    assert trajectory.num_states == 4
    assert trajectory.timestamps_ns.shape == (4,)
    assert trajectory.timestamps_ns.dtype == np.int64
    for name in (
        "positions",
        "velocities",
        "gyro_biases",
        "accel_biases",
    ):
        value = getattr(trajectory, name)
        assert value.shape == (4, 3)
        assert value.dtype == np.float64
    assert trajectory.quaternions.shape == (4, 4)
    assert trajectory.quaternions.dtype == np.float64


def test_factory_copies_inputs_and_exposes_record_owned_views():
    arrays = _arrays()
    trajectory = _core.state_trajectory(*arrays)
    expected = [value.copy() for value in arrays]
    for value in arrays:
        value[...] = 0
    for name, value in zip(
        (
            "timestamps_ns",
            "positions",
            "quaternions",
            "velocities",
            "gyro_biases",
            "accel_biases",
        ),
        expected,
        strict=True,
    ):
        np.testing.assert_array_equal(getattr(trajectory, name), value)


def test_view_keeps_record_alive():
    trajectory = _make()
    positions = trajectory.positions
    del trajectory
    gc.collect()
    np.testing.assert_array_equal(positions, _arrays()[1])


def test_empty_trajectory_has_non_null_shaped_views():
    trajectory = _make(0)
    assert trajectory.num_states == 0
    assert trajectory.timestamps_ns.shape == (0,)
    assert trajectory.positions.shape == (0, 3)
    assert trajectory.quaternions.shape == (0, 4)
    assert trajectory.positions.__array_interface__["data"][0] != 0


def test_dtype_and_noncontiguous_inputs_are_copied_to_canonical_storage():
    timestamps = np.arange(8, dtype=np.int32)[::2]
    source = np.arange(24, dtype=np.float32).reshape(8, 3)[::2]
    quaternions = np.zeros((8, 4), dtype=np.float32)[::2]
    quaternions[:, 0] = 1
    trajectory = _core.state_trajectory(
        timestamps,
        source,
        quaternions,
        source,
        source,
        source,
    )
    assert trajectory.timestamps_ns.dtype == np.int64
    assert trajectory.positions.dtype == np.float64
    assert trajectory.positions.flags.c_contiguous


@pytest.mark.parametrize(
    ("index", "shape"),
    [
        (0, (2, 1)),
        (1, (2, 2)),
        (2, (2, 3)),
        (3, (3, 3)),
        (4, (2, 4)),
        (5, (2,)),
    ],
)
def test_factory_rejects_bad_shapes(index, shape):
    arrays = list(_arrays(2))
    arrays[index] = np.zeros(shape)
    with pytest.raises(ValueError):
        _core.state_trajectory(*arrays)


@pytest.mark.parametrize(
    "timestamps",
    [
        np.array([-1, 2], dtype=np.int64),
        np.array([1, 1], dtype=np.int64),
        np.array([2, 1], dtype=np.int64),
    ],
)
def test_factory_rejects_invalid_timestamps(timestamps):
    arrays = list(_arrays(2))
    arrays[0] = timestamps
    with pytest.raises(ValueError, match="timestamp"):
        _core.state_trajectory(*arrays)


@pytest.mark.parametrize("field", range(1, 6))
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_factory_rejects_nonfinite_state_values(field, value):
    arrays = list(_arrays(2))
    arrays[field][0, 0] = value
    with pytest.raises(ValueError, match="finite"):
        _core.state_trajectory(*arrays)


def test_factory_rejects_zero_quaternion():
    arrays = list(_arrays(2))
    arrays[2][1] = 0.0
    with pytest.raises(ValueError, match="nonzero"):
        _core.state_trajectory(*arrays)


def test_factory_enforces_declared_quaternion_sign_in_either_order():
    arrays = list(_arrays(2))
    arrays[2][0, 0] = -1.0
    with pytest.raises(ValueError, match="canonical_positive_w"):
        _core.state_trajectory(
            *arrays, quaternion_sign="canonical_positive_w"
        )

    xyzw = np.roll(arrays[2], -1, axis=1)
    xyzw[:, 3] = np.abs(xyzw[:, 3])
    trajectory = _core.state_trajectory(
        arrays[0],
        arrays[1],
        xyzw,
        *arrays[3:],
        quaternion_order="xyzw",
        quaternion_sign="canonical_positive_w",
    )
    assert trajectory.quaternion_sign == "canonical_positive_w"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("quaternion_order", "zwxy"),
        ("quaternion_sign", "random"),
        ("pose_convention", "camera_to_world"),
        ("position_frame", "map"),
        ("velocity_frame", "body"),
        ("bias_frame", "imu"),
        ("position_unit", "feet"),
        ("velocity_unit", "knots"),
        ("gyro_bias_unit", "turns_per_second"),
        ("accel_bias_unit", "feet_per_second_squared"),
        ("timestamp_unit", "seconds"),
    ],
)
def test_factory_rejects_unknown_metadata(name, value):
    with pytest.raises(ValueError, match=name):
        _make(**{name: value})


def test_metadata_is_explicit_and_repr_is_informative():
    trajectory = _make()
    assert (
        trajectory.quaternion_order,
        trajectory.quaternion_sign,
        trajectory.pose_convention,
        trajectory.position_frame,
        trajectory.velocity_frame,
        trajectory.bias_frame,
        trajectory.position_unit,
        trajectory.velocity_unit,
        trajectory.gyro_bias_unit,
        trajectory.accel_bias_unit,
        trajectory.timestamp_unit,
    ) == (
        "wxyz",
        "preserved",
        "sensor_to_reference",
        "reference",
        "reference",
        "sensor",
        "meters",
        "meters_per_second",
        "radians_per_second",
        "meters_per_second_squared",
        "nanoseconds",
    )
    assert "StateTrajectory n=4" in repr(trajectory)


def test_numpy_dlpack_export_preserves_values():
    trajectory = _make()
    actual = np.from_dlpack(trajectory.positions)
    np.testing.assert_array_equal(actual, _arrays()[1])
