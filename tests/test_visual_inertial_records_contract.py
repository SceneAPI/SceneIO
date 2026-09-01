"""Machine-checked FC1 visual-inertial record contract."""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

import numpy as np

import sceneio
import sceneio.io
from sceneio import _core
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/visual_inertial_records_v1.toml").read_text(
        encoding="utf-8"
    )
)


def test_fc1_public_surface_and_registry_boundary():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["status"] == "dataset_qualified"
    assert date.fromisoformat(CONTRACT["contract_date"]).isoformat() == CONTRACT[
        "contract_date"
    ]
    assert CONTRACT["builtin_count"] == 74
    assert len(CANONICAL_BUILTIN_IDS) >= CONTRACT["builtin_count"]
    assert "euroc_dataset" in CANONICAL_BUILTIN_IDS
    assert CONTRACT["public_symbols"] == [
        "ImuCalibration",
        "ImuSequence",
        "VisualInertialDataset",
    ]
    assert CONTRACT["core_factories"] == ["imu_calibration", "imu_sequence"]
    for name in ("ImuCalibration", "ImuSequence"):
        assert getattr(sceneio, name) is getattr(_core, name)
        assert not hasattr(sceneio.io, name)
        assert sceneio.representation_contract(name).representation == (
            f"sceneio.{name}"
        )
    assert not hasattr(sceneio.io, "VisualInertialDataset")
    assert sceneio.representation_contract(
        "VisualInertialDataset"
    ).representation == "sceneio.VisualInertialDataset"
    for name in CONTRACT["core_factories"]:
        assert callable(getattr(_core, name))
    for name in CONTRACT["core_io_functions"]:
        assert callable(getattr(_core, name))


def test_calibration_contract_matches_live_record():
    spec = CONTRACT["imu_calibration"]
    calibration = _core.imu_calibration(
        4,
        "imu0",
        "/imu0",
        np.array([1.0, 0.0, 0.0, 0.0]),
        np.zeros(3),
        nominal_rate_hz=200.0,
        gyroscope_noise_density=0.0,
        gyroscope_random_walk=0.0,
        accelerometer_noise_density=0.0,
        accelerometer_random_walk=0.0,
        time_offset_ns=0,
    )
    for name in (*spec["required_fields"], *spec["optional_fields"]):
        assert hasattr(calibration, name)
    assert calibration.transform_convention == spec["transform_convention"]
    assert calibration.translation_unit == spec["translation_unit"]
    assert calibration.nominal_rate_unit == spec["nominal_rate_unit"]
    assert calibration.time_offset_convention == spec["time_offset_equation"]
    assert calibration.time_offset_unit == spec["time_offset_unit"]
    for name in (
        "gyroscope_noise_density_unit",
        "gyroscope_random_walk_unit",
        "accelerometer_noise_density_unit",
        "accelerometer_random_walk_unit",
    ):
        assert getattr(calibration, name) == spec[name]
    assert calibration.sensor_axis_frame in spec["axis_frames"]
    assert calibration.quaternion_order in spec["quaternion_orders"]
    assert calibration.quaternion_sign in spec["quaternion_signs"]


def test_sample_and_acquisition_equations_match_live_records():
    sample_spec = CONTRACT["imu_sequence"]
    samples = _core.imu_sequence(
        4,
        np.array([100, 200], np.int64),
        np.zeros((2, 3)),
        np.zeros((2, 3)),
    )
    for name in sample_spec["array_fields"]:
        assert hasattr(samples, name)
    assert samples.timestamp_unit == sample_spec["timestamp_unit"]
    assert samples.timestamp_reference == sample_spec["timestamp_reference"]
    assert samples.angular_velocity_unit in sample_spec["angular_velocity_units"]
    assert samples.linear_acceleration_unit in sample_spec[
        "linear_acceleration_units"
    ]
    assert samples.sensor_axis_frame in sample_spec["axis_frames"]

    acquisition = CONTRACT["image_sequence_acquisition"]
    sequence = _core.image_sequence_packed(
        np.zeros((2, 2, 3, 3), np.uint8),
        np.array([100, 200], np.int64),
        np.array([100, 100], np.int64),
        exposure_durations_ns=np.array([20, 20], np.int64),
        readout_step_durations_ns=np.array([3, 3], np.int64),
        readout_directions=["bottom_to_top", "bottom_to_top"],
        timestamp_reference="exposure_midpoint",
    )
    for name in acquisition["optional_fields"]:
        assert hasattr(sequence, name)
    assert sequence.timestamp_reference in acquisition["timestamp_references"]
    assert set(sequence.readout_directions) <= set(acquisition["readout_directions"])
    assert sequence.acquisition_timing_convention == acquisition["equation"]
    assert int(sequence.timestamps_ns[0]) - int(
        sequence.readout_step_durations_ns[0]
    ) == 97  # d=-1 for bottom-to-top at raster row i=1.
