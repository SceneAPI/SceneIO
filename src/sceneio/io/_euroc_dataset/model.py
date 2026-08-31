"""Format-neutral aggregate for bounded visual-inertial datasets."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np

from sceneio import _core

if TYPE_CHECKING:
    from collections.abc import Mapping


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"VisualInertialDataset.{field} must be a non-empty string")
    if "\0" in value or any(ord(character) < 0x20 for character in value):
        raise ValueError(
            f"VisualInertialDataset.{field} cannot contain control characters"
        )
    return value


def _timestamp_array(value: object, field: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype != np.dtype(np.int64) or array.ndim != 1:
        raise TypeError(f"VisualInertialDataset.{field} must be a 1-D int64 array")
    owned = np.array(array, dtype=np.int64, order="C", copy=True)
    if np.any(owned < 0):
        raise ValueError(
            f"VisualInertialDataset.{field} timestamps must be nonnegative"
        )
    if owned.size > 1 and np.any(owned[1:] <= owned[:-1]):
        raise ValueError(
            f"VisualInertialDataset.{field} timestamps must be strictly increasing"
        )
    owned.setflags(write=False)
    return owned


def _relative_name(value: str, field: str) -> None:
    if "\\" in value:
        raise ValueError(
            f"VisualInertialDataset.{field} must use POSIX separators"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError(
            f"VisualInertialDataset.{field} must be a safe relative path"
        )


@dataclass(frozen=True, slots=True)
class VisualInertialDataset:
    """One immutable multi-camera/IMU dataset aggregate.

    Child records are retained directly, so their numeric arrays are not
    copied. Camera timestamps are separate because the bounded ASL camera CSV
    carries instants but no frame durations; SceneIO never fabricates the
    missing durations merely to populate ``ImageSequence`` timing.
    """

    root: str
    rig: _core.CameraRig
    camera_streams: tuple[_core.ImageSequence, ...]
    camera_timestamps_ns: tuple[np.ndarray, ...]
    camera_rates_hz: tuple[float, ...]
    camera_clock_domains: tuple[str, ...]
    camera_timestamp_epochs: tuple[str, ...]
    imu_calibrations: tuple[_core.ImuCalibration, ...]
    imu_streams: tuple[_core.ImuSequence, ...]
    imu_timestamp_epochs: tuple[str, ...]
    ground_truth: _core.StateTrajectory | None = None
    ground_truth_timestamp_epoch: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.root, str) or not Path(self.root).is_absolute():
            raise ValueError("VisualInertialDataset.root must be an absolute path")
        if not isinstance(self.rig, _core.CameraRig):
            raise TypeError("VisualInertialDataset.rig must be a CameraRig")

        tuple_fields = (
            "camera_streams",
            "camera_timestamps_ns",
            "camera_rates_hz",
            "camera_clock_domains",
            "camera_timestamp_epochs",
            "imu_calibrations",
            "imu_streams",
            "imu_timestamp_epochs",
        )
        for field in tuple_fields:
            object.__setattr__(self, field, tuple(getattr(self, field)))

        camera_count = self.rig.num_cameras
        camera_lengths = {
            len(self.camera_streams),
            len(self.camera_timestamps_ns),
            len(self.camera_rates_hz),
            len(self.camera_clock_domains),
            len(self.camera_timestamp_epochs),
        }
        if camera_lengths != {camera_count}:
            raise ValueError(
                "VisualInertialDataset camera fields must align with CameraRig"
            )
        imu_count = len(self.imu_calibrations)
        if len(self.imu_streams) != imu_count or len(self.imu_timestamp_epochs) != imu_count:
            raise ValueError("VisualInertialDataset IMU fields must have equal length")
        if camera_count == 0 and imu_count == 0:
            raise ValueError("VisualInertialDataset requires at least one sensor stream")

        camera_names = tuple(self.rig.names)
        imu_names = tuple(calibration.name for calibration in self.imu_calibrations)
        imu_ids = tuple(
            calibration.sensor_id for calibration in self.imu_calibrations
        )
        all_names = (*camera_names, *imu_names)
        if len(all_names) != len(set(all_names)):
            raise ValueError("VisualInertialDataset sensor names must be unique")
        if len(imu_ids) != len(set(imu_ids)):
            raise ValueError("VisualInertialDataset IMU sensor ids must be unique")

        owned_timestamps = []
        for index, (name, stream, timestamps, rate, clock, epoch) in enumerate(
            zip(
                camera_names,
                self.camera_streams,
                self.camera_timestamps_ns,
                self.camera_rates_hz,
                self.camera_clock_domains,
                self.camera_timestamp_epochs,
                strict=True,
            )
        ):
            if not isinstance(stream, _core.ImageSequence):
                raise TypeError(
                    "VisualInertialDataset.camera_streams must contain "
                    "ImageSequence records"
                )
            array = _timestamp_array(timestamps, f"camera_timestamps_ns[{index}]")
            if array.size != stream.num_frames:
                raise ValueError(
                    f"VisualInertialDataset camera {name!r} requires one "
                    "timestamp per frame"
                )
            if stream.has_timing and not np.array_equal(
                np.asarray(stream.timestamps_ns), array
            ):
                raise ValueError(
                    f"VisualInertialDataset camera {name!r} has conflicting "
                    "ImageSequence timestamps"
                )
            if (
                isinstance(rate, bool)
                or not isinstance(rate, int | float)
                or not math.isfinite(float(rate))
                or float(rate) <= 0.0
            ):
                raise ValueError(
                    "VisualInertialDataset.camera_rates_hz values must be "
                    "finite and positive"
                )
            for frame_name in stream.frame_names:
                _relative_name(frame_name, f"camera_streams[{index}].frame_names")
            if len(stream.frame_names) != len(set(stream.frame_names)):
                raise ValueError(
                    f"VisualInertialDataset camera {name!r} frame names "
                    "must be unique"
                )
            for frame_path in stream.frame_paths:
                if not Path(frame_path).is_absolute():
                    raise ValueError(
                        "VisualInertialDataset camera frame paths must be absolute"
                    )
            _text(clock, f"camera_clock_domains[{index}]")
            _text(epoch, f"camera_timestamp_epochs[{index}]")
            owned_timestamps.append(array)
        object.__setattr__(self, "camera_timestamps_ns", tuple(owned_timestamps))
        object.__setattr__(
            self, "camera_rates_hz", tuple(float(value) for value in self.camera_rates_hz)
        )

        for index, (calibration, stream, epoch) in enumerate(
            zip(
                self.imu_calibrations,
                self.imu_streams,
                self.imu_timestamp_epochs,
                strict=True,
            )
        ):
            if not isinstance(calibration, _core.ImuCalibration):
                raise TypeError(
                    "VisualInertialDataset.imu_calibrations must contain "
                    "ImuCalibration records"
                )
            if not isinstance(stream, _core.ImuSequence):
                raise TypeError(
                    "VisualInertialDataset.imu_streams must contain "
                    "ImuSequence records"
                )
            if calibration.sensor_id != stream.sensor_id:
                raise ValueError(
                    f"VisualInertialDataset IMU {calibration.name!r} sensor ids "
                    "must agree"
                )
            _text(stream.clock_domain, f"imu_streams[{index}].clock_domain")
            _text(epoch, f"imu_timestamp_epochs[{index}]")

        if self.ground_truth is not None and not isinstance(
            self.ground_truth, _core.StateTrajectory
        ):
            raise TypeError(
                "VisualInertialDataset.ground_truth must be a StateTrajectory or None"
            )
        if (self.ground_truth is None) != (self.ground_truth_timestamp_epoch is None):
            raise ValueError(
                "VisualInertialDataset ground truth and timestamp epoch must "
                "be present together"
            )
        if self.ground_truth_timestamp_epoch is not None:
            _text(self.ground_truth_timestamp_epoch, "ground_truth_timestamp_epoch")

    @property
    def camera_names(self) -> tuple[str, ...]:
        return tuple(self.rig.names)

    @property
    def imu_names(self) -> tuple[str, ...]:
        return tuple(value.name for value in self.imu_calibrations)

    @property
    def camera_stream_map(self) -> Mapping[str, _core.ImageSequence]:
        return MappingProxyType(dict(zip(self.camera_names, self.camera_streams, strict=True)))

    @property
    def imu_calibration_map(self) -> Mapping[str, _core.ImuCalibration]:
        return MappingProxyType(
            dict(zip(self.imu_names, self.imu_calibrations, strict=True))
        )

    @property
    def imu_stream_map(self) -> Mapping[str, _core.ImuSequence]:
        return MappingProxyType(dict(zip(self.imu_names, self.imu_streams, strict=True)))

    @property
    def num_cameras(self) -> int:
        return len(self.camera_streams)

    @property
    def num_imus(self) -> int:
        return len(self.imu_streams)

    @property
    def num_camera_frames(self) -> int:
        return sum(stream.num_frames for stream in self.camera_streams)

    @property
    def num_imu_samples(self) -> int:
        return sum(stream.num_samples for stream in self.imu_streams)

    @property
    def has_ground_truth(self) -> bool:
        return self.ground_truth is not None

__all__ = ["VisualInertialDataset"]
