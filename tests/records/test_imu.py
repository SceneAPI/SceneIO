"""Compiled IMU calibration, sample, unit, and lifetime contracts."""

from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _calibration(**kwargs):
    values = {
        "sensor_id": 7,
        "name": "imu0",
        "topic": "/imu0",
        "quaternion": np.array([1.0, 0.0, 0.0, 0.0]),
        "translation": np.array([0.1, -0.2, 0.3]),
    }
    values.update(kwargs)
    return _core.imu_calibration(**values)


def _samples(count: int = 4):
    timestamps = 1_403_636_580_000_000_000 + np.arange(
        count, dtype=np.int64
    )
    angular = np.arange(count * 3, dtype=np.float64).reshape(count, 3) / 10
    acceleration = angular + np.array([0.0, 0.0, 9.81])
    return timestamps, angular, acceleration


def _sequence(count: int = 4, **metadata):
    return _core.imu_sequence(7, *_samples(count), **metadata)


def test_calibration_preserves_euroc_asl_quantities_and_exact_units():
    calibration = _calibration(
        nominal_rate_hz=200.0,
        gyroscope_noise_density=1.6968e-4,
        gyroscope_random_walk=1.9393e-5,
        accelerometer_noise_density=2.0e-3,
        accelerometer_random_walk=3.0e-3,
        time_offset_ns=-2_000_000,
    )

    assert isinstance(calibration, sceneio.ImuCalibration)
    assert isinstance(calibration, sceneio.io.ImuCalibration)
    assert (calibration.sensor_id, calibration.name, calibration.topic) == (
        7,
        "imu0",
        "/imu0",
    )
    assert calibration.nominal_rate_hz == 200.0
    assert calibration.nominal_rate_unit == "hertz"
    assert calibration.gyroscope_noise_density == 1.6968e-4
    assert calibration.gyroscope_random_walk == 1.9393e-5
    assert calibration.accelerometer_noise_density == 2.0e-3
    assert calibration.accelerometer_random_walk == 3.0e-3
    assert calibration.time_offset_ns == -2_000_000
    assert calibration.transform_convention == "sensor_to_reference"
    assert calibration.translation_unit == "meters"
    assert (
        calibration.gyroscope_noise_density_unit
        == "radians_per_second_per_sqrt_hertz"
    )
    assert (
        calibration.gyroscope_random_walk_unit
        == "radians_per_second_squared_per_sqrt_hertz"
    )
    assert (
        calibration.accelerometer_noise_density_unit
        == "meters_per_second_squared_per_sqrt_hertz"
    )
    assert (
        calibration.accelerometer_random_walk_unit
        == "meters_per_second_cubed_per_sqrt_hertz"
    )
    assert calibration.time_offset_convention == (
        "reference_time_ns = sensor_time_ns + time_offset_ns"
    )
    assert calibration.time_offset_unit == "nanoseconds"
    assert 1_000_000_000 + calibration.time_offset_ns == 998_000_000


def test_calibration_absence_is_distinct_from_zero():
    absent = _calibration()
    present = _calibration(
        gyroscope_noise_density=0.0,
        accelerometer_random_walk=0.0,
        time_offset_ns=0,
    )
    for name in (
        "nominal_rate_hz",
        "gyroscope_noise_density",
        "gyroscope_random_walk",
        "accelerometer_noise_density",
        "accelerometer_random_walk",
        "time_offset_ns",
    ):
        assert getattr(absent, name) is None
    assert present.gyroscope_noise_density == 0.0
    assert present.accelerometer_random_walk == 0.0
    assert present.time_offset_ns == 0


def test_calibration_transform_is_owned_read_only_and_lifetime_safe():
    quaternion = np.array([1.0, 0.0, 0.0, 0.0])
    translation = np.array([0.1, 0.2, 0.3])
    calibration = _calibration(
        quaternion=quaternion,
        translation=translation,
    )
    quaternion[:] = 0
    translation[:] = 0
    np.testing.assert_array_equal(calibration.quaternion, [1, 0, 0, 0])
    np.testing.assert_array_equal(calibration.translation, [0.1, 0.2, 0.3])
    assert not calibration.quaternion.flags.writeable
    assert not calibration.translation.flags.writeable

    first = calibration.translation
    second = calibration.translation
    assert first.__array_interface__["data"][0] == second.__array_interface__["data"][0]
    del calibration
    gc.collect()
    np.testing.assert_array_equal(first, [0.1, 0.2, 0.3])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": ""}, "name"),
        ({"topic": "bad\0topic"}, "topic"),
        ({"quaternion": np.ones(3)}, "quaternion"),
        ({"translation": np.ones(4)}, "translation"),
        ({"quaternion": np.array([2.0, 0.0, 0.0, 0.0])}, "unit norm"),
        ({"translation": np.array([np.inf, 0.0, 0.0])}, "finite"),
        ({"nominal_rate_hz": 0.0}, "nominal_rate_hz"),
        ({"gyroscope_noise_density": -1.0}, "nonnegative"),
        ({"accelerometer_random_walk": np.inf}, "nonnegative"),
        ({"quaternion_order": "zwxy"}, "quaternion_order"),
        ({"quaternion_sign": "random"}, "quaternion_sign"),
        ({"sensor_axis_frame": "camera"}, "sensor_axis_frame"),
        ({"reference_frame": ""}, "reference_frame"),
    ],
)
def test_calibration_rejects_invalid_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        _calibration(**kwargs)


def test_calibration_enforces_declared_quaternion_sign_and_coordinates():
    with pytest.raises(ValueError, match="canonical_positive_w"):
        _calibration(
            quaternion=np.array([-1.0, 0.0, 0.0, 0.0]),
            quaternion_sign="canonical_positive_w",
        )
    calibration = _calibration(
        quaternion=np.array([0.0, 0.0, 0.0, 1.0]),
        quaternion_order="xyzw",
        quaternion_sign="canonical_positive_w",
        sensor_axis_frame="enu",
        reference_frame="rig",
    )
    assert calibration.coordinates.pose_direction == "sensor_to_reference"
    assert calibration.coordinates.handedness == "right_handed"
    assert calibration.coordinates.quaternion_order == "xyzw"
    assert calibration.coordinates.scale_to_meters == 1.0
    assert calibration.coordinates.reference_frame == "rig"
    assert _calibration().coordinates.handedness == "unknown"


def test_sequence_public_type_shapes_units_and_input_ownership():
    arrays = _samples()
    expected = tuple(value.copy() for value in arrays)
    sequence = _core.imu_sequence(7, *arrays)
    for value in arrays:
        value[...] = 0

    assert isinstance(sequence, sceneio.ImuSequence)
    assert isinstance(sequence, sceneio.io.ImuSequence)
    assert sequence.sensor_id == 7
    assert sequence.num_samples == 4
    assert sequence.timestamps_ns.dtype == np.int64
    assert sequence.timestamps_ns.shape == (4,)
    assert sequence.angular_velocities.dtype == np.float64
    assert sequence.angular_velocities.shape == (4, 3)
    assert sequence.linear_accelerations.shape == (4, 3)
    np.testing.assert_array_equal(sequence.timestamps_ns, expected[0])
    np.testing.assert_array_equal(sequence.angular_velocities, expected[1])
    np.testing.assert_array_equal(sequence.linear_accelerations, expected[2])
    assert sequence.angular_velocity_unit == "radians_per_second"
    assert sequence.linear_acceleration_unit == "meters_per_second_squared"
    assert sequence.sensor_axis_frame == "sensor"
    assert sequence.timestamp_reference == "measurement"
    assert sequence.timestamp_unit == "nanoseconds"
    assert sequence.clock_domain == "sensor"
    assert "ImuSequence sensor_id=7 n=4" in repr(sequence)


def test_sequence_views_are_read_only_aliases_that_keep_owner_alive():
    sequence = _sequence()
    first = sequence.angular_velocities
    second = sequence.angular_velocities
    assert not first.flags.writeable
    assert first.__array_interface__["data"][0] == second.__array_interface__["data"][0]
    dlpack = np.from_dlpack(first)
    assert dlpack.__array_interface__["data"][0] == first.__array_interface__["data"][0]
    np.testing.assert_array_equal(dlpack, _samples()[1])
    del sequence, second
    gc.collect()
    np.testing.assert_array_equal(first, _samples()[1])


def test_empty_singleton_and_noncontiguous_constructor_inputs():
    empty = _sequence(0)
    assert empty.timestamps_ns.shape == (0,)
    assert empty.angular_velocities.shape == (0, 3)
    assert empty.angular_velocities.__array_interface__["data"][0] != 0

    singleton = _sequence(1)
    assert singleton.num_samples == 1

    timestamps = np.arange(8, dtype=np.int32)[::2]
    angular = np.arange(24, dtype=np.float32).reshape(8, 3)[::2]
    acceleration = (angular + 1)[::-1][::-1]
    converted = _core.imu_sequence(3, timestamps, angular, acceleration)
    assert converted.timestamps_ns.dtype == np.int64
    assert converted.angular_velocities.dtype == np.float64
    assert converted.angular_velocities.flags.c_contiguous
    np.testing.assert_array_equal(converted.angular_velocities, angular)


@pytest.mark.parametrize(
    ("index", "value", "message"),
    [
        (0, np.array([1, 1], np.int64), "strictly increasing"),
        (0, np.array([-1, 2], np.int64), "nonnegative"),
        (1, np.zeros((2, 2)), "angular_velocities"),
        (2, np.zeros((3, 3)), "linear_accelerations"),
    ],
)
def test_sequence_rejects_bad_timestamps_and_shapes(index, value, message):
    arrays = list(_samples(2))
    arrays[index] = value
    with pytest.raises(ValueError, match=message):
        _core.imu_sequence(7, *arrays)


@pytest.mark.parametrize("field", [1, 2])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_sequence_rejects_nonfinite_measurements(field, value):
    arrays = list(_samples(2))
    arrays[field][0, 0] = value
    with pytest.raises(ValueError, match="finite"):
        _core.imu_sequence(7, *arrays)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("angular_velocity_unit", "turns_per_second"),
        ("linear_acceleration_unit", "feet_per_second_squared"),
        ("sensor_axis_frame", "camera"),
        ("timestamp_reference", "arrival"),
        ("clock_domain", ""),
    ],
)
def test_sequence_rejects_unknown_metadata(name, value):
    with pytest.raises(ValueError, match=name):
        _sequence(**{name: value})


def test_sequence_preserves_declared_alternate_units_and_axis_frame():
    sequence = _sequence(
        angular_velocity_unit="degrees_per_second",
        linear_acceleration_unit="standard_gravity",
        sensor_axis_frame="ned",
        clock_domain="hardware_clock_0",
    )
    assert sequence.angular_velocity_unit == "degrees_per_second"
    assert sequence.linear_acceleration_unit == "standard_gravity"
    assert sequence.sensor_axis_frame == "ned"
    assert sequence.clock_domain == "hardware_clock_0"
    assert sequence.coordinates.camera_axes == "ned"
    assert sequence.coordinates.world_frame == "ned"


def test_record_metadata_is_keyword_only():
    with pytest.raises(TypeError):
        _core.imu_sequence(7, *_samples(), "degrees_per_second")
    with pytest.raises(TypeError):
        _core.imu_calibration(
            7,
            "imu0",
            "/imu0",
            np.array([1.0, 0.0, 0.0, 0.0]),
            np.zeros(3),
            200.0,
        )
