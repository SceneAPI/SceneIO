"""Repository-owned bounded ASL/EuRoC-style directory adapter."""

from __future__ import annotations

import json
import math
import mmap
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.coordinate_conversion import _matrix_quaternion, _quaternion_matrix
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._inspectors.model import Inspection

from .model import VisualInertialDataset
from .yaml_subset import parse_sensor_yaml

_CAMERA_NAME = re.compile(r"cam(?P<index>0|[1-9][0-9]*)")
_IMU_NAME = re.compile(r"imu(?P<index>0|[1-9][0-9]*)")
_GROUND_TRUTH_NAME = "state_groundtruth_estimate0"
_CAMERA_HEADER = b"#timestamp [ns],filename"
_LINE_LIMIT = 1024 * 1024
_COPY_CHUNK = 1024 * 1024
_RIGID_ATOL = 1e-7


@dataclass(frozen=True, slots=True)
class _Layout:
    root: Path
    cameras: tuple[tuple[str, Path], ...]
    imus: tuple[tuple[str, Path], ...]
    ground_truth: Path | None


@dataclass(frozen=True, slots=True)
class _CameraSensor:
    name: str
    sensor_id: int
    transform: np.ndarray
    rate_hz: float
    resolution: tuple[int, int]
    projection_model: str
    intrinsics: tuple[float, ...]
    distortion_model: str
    distortion_coefficients: tuple[float, ...]
    topic: str
    time_offset_seconds: float | None


@dataclass(frozen=True, slots=True)
class _ImuSensor:
    name: str
    sensor_id: int
    transform: np.ndarray
    rate_hz: float
    topic: str
    gyroscope_noise_density: float | None
    gyroscope_random_walk: float | None
    accelerometer_noise_density: float | None
    accelerometer_random_walk: float | None


@dataclass(frozen=True, slots=True)
class _CameraCsv:
    names: tuple[str, ...]
    timestamps_ns: np.ndarray
    total_count: int
    first_timestamp_ns: int
    last_timestamp_ns: int


def _regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"euroc_dataset: {label} must be a regular file")


def _sensor_directories(
    mav0: Path, pattern: re.Pattern[str]
) -> tuple[tuple[str, Path], ...]:
    rows = []
    for child in mav0.iterdir():
        match = pattern.fullmatch(child.name)
        if match is not None:
            if child.is_symlink() or not child.is_dir():
                raise ValueError(
                    f"euroc_dataset: sensor {child.name!r} must be a directory"
                )
            rows.append((int(match.group("index")), child.name, child))
    rows.sort()
    indices = [row[0] for row in rows]
    if indices and indices != list(range(len(indices))):
        kind = "camera" if pattern is _CAMERA_NAME else "IMU"
        raise ValueError(
            f"euroc_dataset: {kind} indices must be contiguous from zero"
        )
    return tuple((name, path) for _index, name, path in rows)


def _complete_camera(path: Path) -> bool:
    sensor_yaml = path / "sensor.yaml"
    data_csv = path / "data.csv"
    data = path / "data"
    return not any(value.is_symlink() for value in (sensor_yaml, data_csv, data)) and (
        sensor_yaml.is_file() and data_csv.is_file() and data.is_dir()
    )


def _complete_imu(path: Path) -> bool:
    sensor_yaml = path / "sensor.yaml"
    data_csv = path / "data.csv"
    return not sensor_yaml.is_symlink() and not data_csv.is_symlink() and (
        sensor_yaml.is_file() and data_csv.is_file()
    )


def is_euroc_dataset_directory(path: str | Path) -> bool:
    """Return whether ``path`` has at least one complete camera and IMU stream."""

    try:
        root = Path(path)
        if root.is_symlink() or not root.is_dir():
            return False
        mav0 = root / "mav0"
        if mav0.is_symlink() or not mav0.is_dir():
            return False
        cameras = _sensor_directories(mav0, _CAMERA_NAME)
        imus = _sensor_directories(mav0, _IMU_NAME)
        return bool(cameras and imus) and all(
            _complete_camera(sensor) for _name, sensor in cameras
        ) and all(_complete_imu(sensor) for _name, sensor in imus)
    except (OSError, ValueError):
        return False


def _discover(path: str | Path) -> _Layout:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("euroc_dataset: path must be a regular directory")
    root = root.resolve()
    mav0 = root / "mav0"
    if mav0.is_symlink() or not mav0.is_dir():
        raise ValueError("euroc_dataset: missing regular mav0 directory")
    cameras = _sensor_directories(mav0, _CAMERA_NAME)
    imus = _sensor_directories(mav0, _IMU_NAME)
    if not cameras or not imus:
        raise ValueError(
            "euroc_dataset: requires at least one camera and one IMU stream"
        )
    for name, sensor in cameras:
        if not _complete_camera(sensor):
            raise ValueError(f"euroc_dataset: incomplete camera stream {name!r}")
        _regular_file(sensor / "sensor.yaml", f"{name}/sensor.yaml")
        _regular_file(sensor / "data.csv", f"{name}/data.csv")
        if (sensor / "data").is_symlink():
            raise ValueError(f"euroc_dataset: {name}/data cannot be a symlink")
    for name, sensor in imus:
        if not _complete_imu(sensor):
            raise ValueError(f"euroc_dataset: incomplete IMU stream {name!r}")
        _regular_file(sensor / "sensor.yaml", f"{name}/sensor.yaml")
        _regular_file(sensor / "data.csv", f"{name}/data.csv")
    ground_truth = mav0 / _GROUND_TRUTH_NAME
    if ground_truth.exists():
        if ground_truth.is_symlink() or not ground_truth.is_dir():
            raise ValueError("euroc_dataset: ground-truth path must be a directory")
        _regular_file(
            ground_truth / "data.csv",
            f"{_GROUND_TRUTH_NAME}/data.csv",
        )
        _regular_file(
            ground_truth / "sensor.yaml",
            f"{_GROUND_TRUTH_NAME}/sensor.yaml",
        )
        ground_truth_document = parse_sensor_yaml(ground_truth / "sensor.yaml")
        _fields(
            ground_truth_document,
            {"sensor_type"},
            {"comment"},
            f"{_GROUND_TRUTH_NAME}/sensor.yaml",
        )
        if ground_truth_document["sensor_type"] != "ground_truth":
            raise ValueError(
                "euroc_dataset: ground-truth sensor_type must be ground_truth"
            )
    else:
        ground_truth = None
    return _Layout(root, cameras, imus, ground_truth)


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"euroc_dataset: {name} must be a mapping")
    return value


def _fields(
    document: dict[str, object],
    required: set[str],
    optional: set[str],
    name: str,
) -> None:
    missing = required - set(document)
    unknown = set(document) - required - optional
    if missing:
        raise ValueError(
            f"euroc_dataset: {name} is missing {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ValueError(
            f"euroc_dataset: {name} has unsupported fields "
            f"{', '.join(sorted(unknown))}"
        )


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"euroc_dataset: {name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        requirement = "finite and positive" if positive else "finite"
        raise ValueError(f"euroc_dataset: {name} must be {requirement}")
    return result


def _optional_nonnegative(document: dict[str, object], key: str) -> float | None:
    if key not in document:
        return None
    value = _number(document[key], key)
    if value < 0.0:
        raise ValueError(f"euroc_dataset: {key} must be nonnegative")
    return value


def _text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ValueError(f"euroc_dataset: {name} must be a string")
    if "\0" in value or any(ord(character) < 0x20 for character in value):
        raise ValueError(f"euroc_dataset: {name} contains control characters")
    return value


def _numbers(value: object, name: str) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise ValueError(f"euroc_dataset: {name} must be an inline list")
    return tuple(_number(item, f"{name}[{index}]") for index, item in enumerate(value))


def _transform(value: object, name: str) -> np.ndarray:
    if isinstance(value, dict):
        _fields(value, {"rows", "cols", "data"}, {"dt"}, name)
        if value["rows"] != 4 or value["cols"] != 4:
            raise ValueError(f"euroc_dataset: {name} must be a 4x4 matrix")
        if "dt" in value and value["dt"] not in {"d", "f"}:
            raise ValueError(f"euroc_dataset: {name}.dt must be 'd' or 'f'")
        data = _numbers(value["data"], f"{name}.data")
        if len(data) != 16:
            raise ValueError(f"euroc_dataset: {name}.data must contain 16 values")
        matrix = np.asarray(data, dtype=np.float64).reshape(4, 4)
    elif isinstance(value, list) and len(value) == 4:
        rows = [_numbers(row, f"{name}[{index}]") for index, row in enumerate(value)]
        if any(len(row) != 4 for row in rows):
            raise ValueError(f"euroc_dataset: {name} must be a 4x4 matrix")
        matrix = np.asarray(rows, dtype=np.float64)
    else:
        raise ValueError(f"euroc_dataset: {name} must be a 4x4 matrix")
    if not np.allclose(matrix[3], (0.0, 0.0, 0.0, 1.0), atol=_RIGID_ATOL, rtol=0.0):
        raise ValueError(f"euroc_dataset: {name} must be affine")
    rotation = matrix[:3, :3]
    if not np.allclose(
        rotation.T @ rotation,
        np.eye(3),
        atol=_RIGID_ATOL,
        rtol=0.0,
    ) or not math.isclose(
        float(np.linalg.det(rotation)), 1.0, abs_tol=_RIGID_ATOL
    ):
        raise ValueError(f"euroc_dataset: {name} must contain a proper rotation")
    return np.ascontiguousarray(matrix)


def _topic(document: dict[str, object], name: str) -> str:
    values = [key for key in ("rostopic", "topic") if key in document]
    if len(values) > 1:
        raise ValueError(f"euroc_dataset: {name} declares two topic fields")
    return _text(document[values[0]], f"{name}.{values[0]}", allow_empty=True) if values else ""


def _parse_camera(name: str, path: Path) -> _CameraSensor:
    document = parse_sensor_yaml(path / "sensor.yaml")
    required = {
        "sensor_type",
        "T_BS",
        "rate_hz",
        "resolution",
        "camera_model",
        "intrinsics",
        "distortion_model",
        "distortion_coefficients",
    }
    optional = {"comment", "rostopic", "topic", "timeshift_cam_imu"}
    _fields(document, required, optional, f"{name}/sensor.yaml")
    if document["sensor_type"] != "camera":
        raise ValueError(f"euroc_dataset: {name} sensor_type must be camera")
    resolution = document["resolution"]
    if (
        not isinstance(resolution, list)
        or len(resolution) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in resolution)
    ):
        raise ValueError(f"euroc_dataset: {name}.resolution must be [width,height]")
    intrinsics = _numbers(document["intrinsics"], f"{name}.intrinsics")
    if not intrinsics:
        raise ValueError(f"euroc_dataset: {name}.intrinsics cannot be empty")
    time_offset = (
        _number(document["timeshift_cam_imu"], f"{name}.timeshift_cam_imu")
        if "timeshift_cam_imu" in document
        else None
    )
    return _CameraSensor(
        name=name,
        sensor_id=int(_CAMERA_NAME.fullmatch(name).group("index")),
        transform=_transform(document["T_BS"], f"{name}.T_BS"),
        rate_hz=_number(document["rate_hz"], f"{name}.rate_hz", positive=True),
        resolution=(int(resolution[0]), int(resolution[1])),
        projection_model=_text(document["camera_model"], f"{name}.camera_model"),
        intrinsics=intrinsics,
        distortion_model=_text(
            document["distortion_model"], f"{name}.distortion_model"
        ),
        distortion_coefficients=_numbers(
            document["distortion_coefficients"],
            f"{name}.distortion_coefficients",
        ),
        topic=_topic(document, name),
        time_offset_seconds=time_offset,
    )


def _parse_imu(name: str, path: Path) -> _ImuSensor:
    document = parse_sensor_yaml(path / "sensor.yaml")
    required = {"sensor_type", "T_BS", "rate_hz"}
    optional = {
        "comment",
        "rostopic",
        "topic",
        "gyroscope_noise_density",
        "gyroscope_random_walk",
        "accelerometer_noise_density",
        "accelerometer_random_walk",
    }
    _fields(document, required, optional, f"{name}/sensor.yaml")
    if document["sensor_type"] != "imu":
        raise ValueError(f"euroc_dataset: {name} sensor_type must be imu")
    return _ImuSensor(
        name=name,
        sensor_id=int(_IMU_NAME.fullmatch(name).group("index")),
        transform=_transform(document["T_BS"], f"{name}.T_BS"),
        rate_hz=_number(document["rate_hz"], f"{name}.rate_hz", positive=True),
        topic=_topic(document, name),
        gyroscope_noise_density=_optional_nonnegative(
            document, "gyroscope_noise_density"
        ),
        gyroscope_random_walk=_optional_nonnegative(
            document, "gyroscope_random_walk"
        ),
        accelerometer_noise_density=_optional_nonnegative(
            document, "accelerometer_noise_density"
        ),
        accelerometer_random_walk=_optional_nonnegative(
            document, "accelerometer_random_walk"
        ),
    )


def _select_names(
    available: tuple[tuple[str, Path], ...],
    requested: tuple[str, ...] | list[str] | None,
    label: str,
) -> tuple[tuple[str, Path], ...]:
    if requested is None:
        return available
    if not isinstance(requested, tuple | list):
        raise TypeError(f"euroc_dataset: {label} selectors must be a list or tuple")
    names = tuple(requested)
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError(f"euroc_dataset: {label} selectors must be non-empty strings")
    if len(names) != len(set(names)):
        raise ValueError(f"euroc_dataset: {label} selectors must be unique")
    unknown = set(names) - {name for name, _path in available}
    if unknown:
        raise ValueError(
            f"euroc_dataset: unknown {label} selector(s): {', '.join(sorted(unknown))}"
        )
    selected = set(names)
    return tuple(row for row in available if row[0] in selected)


def _range(
    value: tuple[int, int] | None,
    label: str,
) -> tuple[int, int] | None:
    if value is None:
        return None
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise TypeError(f"euroc_dataset: {label} must be an integer pair")
    start, stop = value
    if start < 0 or start >= stop or stop > np.iinfo(np.int64).max:
        raise ValueError(f"euroc_dataset: {label} must be a valid half-open range")
    return start, stop


def _scan_camera_csv(
    sensor_path: Path,
    image_extensions: frozenset[str],
    frame_range: tuple[int, int] | None,
    time_range_ns: tuple[int, int] | None,
    *,
    collect: bool,
) -> _CameraCsv:
    csv_path = sensor_path / "data.csv"
    data_path = sensor_path / "data"
    _regular_file(csv_path, f"{sensor_path.name}/data.csv")
    if data_path.is_symlink() or not data_path.is_dir():
        raise ValueError(f"euroc_dataset: {sensor_path.name}/data must be a directory")
    names: list[str] = []
    timestamps: list[int] = []
    observed_names: set[str] = set()
    count = 0
    first = -1
    previous = -1
    header_seen = False
    with csv_path.open("rb") as stream:
        line_number = 0
        while True:
            raw = stream.readline(_LINE_LIMIT + 2)
            if not raw:
                break
            line_number += 1
            if len(raw.rstrip(b"\r\n")) > _LINE_LIMIT:
                raise ValueError("euroc_dataset: camera CSV line exceeds 1 MiB")
            line = raw.rstrip(b"\r\n")
            if b"\0" in line:
                raise ValueError("euroc_dataset: camera CSV contains a NUL byte")
            if not line.strip():
                continue
            if not header_seen:
                if line.startswith(b"\xef\xbb\xbf"):
                    line = line[3:]
                if line.strip() != _CAMERA_HEADER:
                    raise ValueError(
                        "euroc_dataset: camera CSV header does not match "
                        "#timestamp [ns],filename"
                    )
                header_seen = True
                continue
            if line.lstrip().startswith(b"#"):
                continue
            if line.count(b",") != 1:
                raise ValueError(
                    f"euroc_dataset: camera CSV line {line_number} must have 2 columns"
                )
            encoded_timestamp, encoded_name = (item.strip() for item in line.split(b",", 1))
            if not encoded_timestamp.isdigit():
                raise ValueError(
                    f"euroc_dataset: camera CSV line {line_number} has an invalid timestamp"
                )
            timestamp = int(encoded_timestamp)
            if timestamp > np.iinfo(np.int64).max or timestamp <= previous:
                raise ValueError(
                    "euroc_dataset: camera timestamps must be nonnegative and "
                    "strictly increasing"
                )
            try:
                filename = encoded_name.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("euroc_dataset: camera filenames must be UTF-8") from exc
            if (
                not filename
                or filename in {".", ".."}
                or Path(filename).name != filename
                or "/" in filename
                or "\\" in filename
                or "," in filename
            ):
                raise ValueError(
                    "euroc_dataset: camera filenames must be safe single path components"
                )
            if filename in observed_names:
                raise ValueError("euroc_dataset: camera filenames must be unique")
            observed_names.add(filename)
            if Path(filename).suffix.lower() not in image_extensions:
                raise ValueError(
                    f"euroc_dataset: unsupported camera image extension in {filename!r}"
                )
            source = data_path / filename
            _regular_file(source, f"{sensor_path.name}/data/{filename}")
            if count == 0:
                first = timestamp
            selected = (
                (frame_range is None or frame_range[0] <= count < frame_range[1])
                and (
                    time_range_ns is None
                    or time_range_ns[0] <= timestamp < time_range_ns[1]
                )
            )
            if collect and selected:
                names.append(filename)
                timestamps.append(timestamp)
            previous = timestamp
            count += 1
    if not header_seen:
        raise ValueError("euroc_dataset: camera CSV is missing its header")
    if count == 0:
        raise ValueError("euroc_dataset: camera streams cannot be empty")
    if frame_range is not None and frame_range[1] > count:
        raise ValueError("euroc_dataset: camera frame range exceeds the stream")
    return _CameraCsv(
        tuple(names),
        np.asarray(timestamps, dtype=np.int64),
        count,
        first,
        previous,
    )


def _frame_metadata(
    frame_access: ImageFrameAccess,
    paths: tuple[Path, ...],
    resolution: tuple[int, int],
) -> tuple[int, str]:
    expected: tuple[int, int, int, str] | None = None
    for path in paths:
        info = frame_access.inspect(path)
        if not isinstance(info, Inspection):
            raise TypeError(
                "euroc_dataset: frame inspector must return an Inspection"
            )
        if info.shape is None or info.channels is None or info.dtype is None:
            raise ValueError(f"euroc_dataset: {path.name!r} is not an image")
        current = (info.shape[0], info.shape[1], info.channels, info.dtype)
        if expected is None:
            expected = current
        elif current != expected:
            raise ValueError("euroc_dataset: camera frames must be homogeneous")
    if expected is None:
        raise ValueError("euroc_dataset: selected camera range is empty")
    width, height = resolution
    if expected[:2] != (height, width):
        raise ValueError(
            "euroc_dataset: camera frame dimensions disagree with sensor.yaml"
        )
    if expected[2] not in {1, 3, 4} or expected[3] not in {
        "uint8",
        "uint16",
        "float32",
    }:
        raise ValueError("euroc_dataset: camera frame dtype/channels are unsupported")
    return expected[2], expected[3]


def _build_rig(sensors: tuple[_CameraSensor, ...]):
    intrinsic_offsets = [0]
    distortion_offsets = [0]
    intrinsics: list[float] = []
    distortions: list[float] = []
    quaternions = []
    translations = []
    for sensor in sensors:
        intrinsics.extend(sensor.intrinsics)
        intrinsic_offsets.append(len(intrinsics))
        distortions.extend(sensor.distortion_coefficients)
        distortion_offsets.append(len(distortions))
        quaternions.append(_matrix_quaternion(sensor.transform[:3, :3], "wxyz"))
        translations.append(sensor.transform[:3, 3])
    count = len(sensors)
    time_offsets = np.asarray(
        [sensor.time_offset_seconds or 0.0 for sensor in sensors], np.float64
    )
    has_time_offset = np.asarray(
        [sensor.time_offset_seconds is not None for sensor in sensors], np.uint8
    )
    return _core.camera_rig(
        np.asarray([sensor.sensor_id for sensor in sensors], np.uint32),
        np.asarray([sensor.resolution for sensor in sensors], np.uint64).reshape(count, 2),
        [sensor.projection_model for sensor in sensors],
        np.asarray(intrinsic_offsets, np.uint64),
        np.asarray(intrinsics, np.float64),
        [sensor.distortion_model for sensor in sensors],
        np.asarray(distortion_offsets, np.uint64),
        np.asarray(distortions, np.float64),
        np.asarray(quaternions, np.float64).reshape(count, 4),
        np.asarray(translations, np.float64).reshape(count, 3),
        np.ones(count, np.uint8),
        names=[sensor.name for sensor in sensors],
        topics=[sensor.topic for sensor in sensors],
        time_offsets=time_offsets,
        has_time_offset=has_time_offset,
        quaternion_order="wxyz",
        quaternion_sign="canonical_positive_w",
        transform_convention="camera_to_reference",
        axis_frame="opencv",
        reference_frame="rig",
        scale_to_meters=1.0,
    )


def _build_calibration(sensor: _ImuSensor):
    return _core.imu_calibration(
        sensor.sensor_id,
        sensor.name,
        sensor.topic,
        _matrix_quaternion(sensor.transform[:3, :3], "wxyz"),
        sensor.transform[:3, 3],
        nominal_rate_hz=sensor.rate_hz,
        gyroscope_noise_density=sensor.gyroscope_noise_density,
        gyroscope_random_walk=sensor.gyroscope_random_walk,
        accelerometer_noise_density=sensor.accelerometer_noise_density,
        accelerometer_random_walk=sensor.accelerometer_random_walk,
        quaternion_order="wxyz",
        quaternion_sign="canonical_positive_w",
        sensor_axis_frame="sensor",
        reference_frame="rig",
    )


def _mapped_call(path: Path, function, *args):
    with path.open("rb") as stream:
        try:
            mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        except (OSError, ValueError):
            stream.seek(0)
            return function(stream.read(), *args)
        with mapped:
            return function(mapped, *args)


def _read_ground_truth(
    path: Path,
    time_range_ns: tuple[int, int] | None,
):
    trajectory = _mapped_call(path, _core.read_euroc_state)
    if time_range_ns is None:
        return trajectory
    timestamps = np.asarray(trajectory.timestamps_ns)
    start = int(np.searchsorted(timestamps, time_range_ns[0], side="left"))
    stop = int(np.searchsorted(timestamps, time_range_ns[1], side="left"))
    return _core.state_trajectory(
        np.asarray(trajectory.timestamps_ns)[start:stop],
        np.asarray(trajectory.positions)[start:stop],
        np.asarray(trajectory.quaternions)[start:stop],
        np.asarray(trajectory.velocities)[start:stop],
        np.asarray(trajectory.gyro_biases)[start:stop],
        np.asarray(trajectory.accel_biases)[start:stop],
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
    )


def read_euroc_dataset(
    frame_access: ImageFrameAccess,
    path: str | Path,
    *,
    cameras: tuple[str, ...] | list[str] | None = None,
    imus: tuple[str, ...] | list[str] | None = None,
    frame_range: tuple[int, int] | None = None,
    time_range_ns: tuple[int, int] | None = None,
    include_ground_truth: bool = True,
) -> VisualInertialDataset:
    """Read a bounded ASL directory with optional typed sensor selection."""

    if not isinstance(include_ground_truth, bool):
        raise TypeError("euroc_dataset: include_ground_truth must be bool")
    frame_range = _range(frame_range, "frame_range")
    time_range_ns = _range(time_range_ns, "time_range_ns")
    if frame_range is not None and time_range_ns is not None:
        raise ValueError(
            "euroc_dataset: frame_range and time_range_ns are mutually exclusive"
        )
    layout = _discover(path)
    selected_cameras = _select_names(layout.cameras, cameras, "camera")
    selected_imus = _select_names(layout.imus, imus, "IMU")
    if not selected_cameras and not selected_imus:
        raise ValueError("euroc_dataset: selection must retain at least one sensor")
    if frame_range is not None and not selected_cameras:
        raise ValueError("euroc_dataset: frame_range requires a selected camera")

    camera_sensors = tuple(
        _parse_camera(name, sensor_path)
        for name, sensor_path in selected_cameras
    )
    image_extensions = frame_access.image_extensions()
    camera_streams = []
    camera_timestamps = []
    for sensor, (_name, sensor_path) in zip(
        camera_sensors, selected_cameras, strict=True
    ):
        rows = _scan_camera_csv(
            sensor_path,
            image_extensions,
            frame_range,
            time_range_ns,
            collect=True,
        )
        if not rows.names:
            raise ValueError(
                f"euroc_dataset: selection is empty for camera {sensor.name!r}"
            )
        paths = tuple(sensor_path / "data" / name for name in rows.names)
        channels, dtype = _frame_metadata(
            frame_access, paths, sensor.resolution
        )
        relative_names = [
            f"mav0/{sensor.name}/data/{name}" for name in rows.names
        ]
        camera_streams.append(
            _core.image_sequence_paths(
                [str(value.resolve()) for value in paths],
                relative_names,
                np.empty(0, np.int64),
                np.empty(0, np.int64),
                sensor.resolution[1],
                sensor.resolution[0],
                channels,
                dtype,
                "gray" if channels == 1 else "unknown",
                "straight" if channels == 4 else "none",
            )
        )
        camera_timestamps.append(rows.timestamps_ns)

    imu_sensors = tuple(
        _parse_imu(name, sensor_path) for name, sensor_path in selected_imus
    )
    imu_calibrations = tuple(_build_calibration(sensor) for sensor in imu_sensors)
    imu_streams = []
    for sensor, (_name, sensor_path) in zip(imu_sensors, selected_imus, strict=True):
        csv_path = sensor_path / "data.csv"
        if time_range_ns is None:
            stream = _mapped_call(
                csv_path,
                _core.read_euroc_imu,
                sensor.sensor_id,
                sensor.name,
            )
        else:
            stream = _mapped_call(
                csv_path,
                _core.read_euroc_imu_time_range,
                time_range_ns[0],
                time_range_ns[1],
                sensor.sensor_id,
                sensor.name,
            )
        if stream.num_samples == 0:
            raise ValueError(
                f"euroc_dataset: selection is empty for IMU {sensor.name!r}"
            )
        imu_streams.append(stream)

    ground_truth = None
    ground_truth_epoch = None
    if include_ground_truth and layout.ground_truth is not None:
        ground_truth = _read_ground_truth(
            layout.ground_truth / "data.csv", time_range_ns
        )
        ground_truth_epoch = "dataset"

    return VisualInertialDataset(
        root=str(layout.root),
        rig=_build_rig(camera_sensors),
        camera_streams=tuple(camera_streams),
        camera_timestamps_ns=tuple(camera_timestamps),
        camera_rates_hz=tuple(sensor.rate_hz for sensor in camera_sensors),
        camera_clock_domains=tuple(sensor.name for sensor in camera_sensors),
        camera_timestamp_epochs=("dataset",) * len(camera_sensors),
        imu_calibrations=imu_calibrations,
        imu_streams=tuple(imu_streams),
        imu_timestamp_epochs=("dataset",) * len(imu_sensors),
        ground_truth=ground_truth,
        ground_truth_timestamp_epoch=ground_truth_epoch,
    )


def _directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_symlink():
            raise ValueError("euroc_dataset: symlink entries are unsupported")
        if item.is_file():
            total += item.stat().st_size
    return total


def inspect_euroc_dataset(
    frame_access: ImageFrameAccess,
    path: str | Path,
) -> Inspection:
    """Inspect sensor metadata and CSV values without decoding image pixels."""

    layout = _discover(path)
    extensions = frame_access.image_extensions()
    camera_sensors = tuple(_parse_camera(name, value) for name, value in layout.cameras)
    camera_rows = tuple(
        _scan_camera_csv(value, extensions, None, None, collect=False)
        for _name, value in layout.cameras
    )
    imu_sensors = tuple(_parse_imu(name, value) for name, value in layout.imus)
    imu_rows = tuple(
        _mapped_call(value / "data.csv", _core._inspect_euroc_imu)
        for _name, value in layout.imus
    )
    ground_truth_count = 0
    ground_truth_first = -1
    ground_truth_last = -1
    if layout.ground_truth is not None:
        ground_truth_count, ground_truth_first, ground_truth_last = _mapped_call(
            layout.ground_truth / "data.csv", _core._inspect_euroc_state
        )
    first_values = [row.first_timestamp_ns for row in camera_rows]
    first_values.extend(int(row[1]) for row in imu_rows if row[0])
    if ground_truth_count:
        first_values.append(int(ground_truth_first))
    last_values = [row.last_timestamp_ns for row in camera_rows]
    last_values.extend(int(row[2]) for row in imu_rows if row[0])
    if ground_truth_count:
        last_values.append(int(ground_truth_last))
    count = sum(row.total_count for row in camera_rows) + sum(
        int(row[0]) for row in imu_rows
    )
    return Inspection(
        format="euroc_dataset",
        datatype="visual_inertial_dataset",
        byte_size=_directory_size(layout.root),
        count=count,
        metadata={
            "camera_names": tuple(sensor.name for sensor in camera_sensors),
            "imu_names": tuple(sensor.name for sensor in imu_sensors),
            "camera_counts": tuple(row.total_count for row in camera_rows),
            "imu_counts": tuple(int(row[0]) for row in imu_rows),
            "camera_resolutions": tuple(
                value for sensor in camera_sensors for value in sensor.resolution
            ),
            "first_timestamp_ns": min(first_values),
            "last_timestamp_ns": max(last_values),
            "has_ground_truth": bool(layout.ground_truth),
            "ground_truth_count": int(ground_truth_count),
        },
    )


def _format_float(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("euroc_dataset: cannot write non-finite YAML values")
    return format(value, ".17g")


def _matrix_yaml(matrix: np.ndarray) -> list[str]:
    values = ", ".join(_format_float(float(value)) for value in matrix.reshape(-1))
    return [
        "T_BS: !!opencv-matrix",
        "  rows: 4",
        "  cols: 4",
        "  dt: d",
        f"  data: [{values}]",
    ]


def _yaml_text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _camera_yaml(dataset: VisualInertialDataset, index: int) -> str:
    rig = dataset.rig
    intrinsic_begin = int(rig.intrinsic_offsets[index])
    intrinsic_end = int(rig.intrinsic_offsets[index + 1])
    distortion_begin = int(rig.distortion_offsets[index])
    distortion_end = int(rig.distortion_offsets[index + 1])
    matrix = np.eye(4, dtype=np.float64)
    quaternion = np.asarray(rig.quaternions[index], dtype=np.float64)
    if not math.isclose(float(np.linalg.norm(quaternion)), 1.0, abs_tol=1e-9):
        raise ValueError("euroc_dataset: camera quaternions must have unit norm")
    matrix[:3, :3] = _quaternion_matrix(quaternion, rig.quaternion_order)
    matrix[:3, 3] = np.asarray(rig.translations[index], dtype=np.float64)
    lines = ["%YAML:1.0", "---", "sensor_type: camera"]
    lines.extend(_matrix_yaml(matrix))
    lines.append(f"rate_hz: {_format_float(dataset.camera_rates_hz[index])}")
    width, height = (int(value) for value in np.asarray(rig.resolutions[index]))
    lines.append(f"resolution: [{width}, {height}]")
    lines.append(f"camera_model: {_yaml_text(rig.projection_models[index])}")
    intrinsics = ", ".join(
        _format_float(float(value))
        for value in np.asarray(rig.intrinsics)[intrinsic_begin:intrinsic_end]
    )
    lines.append(f"intrinsics: [{intrinsics}]")
    lines.append(f"distortion_model: {_yaml_text(rig.distortion_models[index])}")
    distortion = ", ".join(
        _format_float(float(value))
        for value in np.asarray(rig.distortion_coefficients)[
            distortion_begin:distortion_end
        ]
    )
    lines.append(f"distortion_coefficients: [{distortion}]")
    if rig.topics[index]:
        lines.append(f"rostopic: {_yaml_text(rig.topics[index])}")
    if rig.has_time_offset[index]:
        lines.append(
            f"timeshift_cam_imu: {_format_float(float(rig.time_offsets[index]))}"
        )
    return "\n".join(lines) + "\n"


def _imu_yaml(calibration) -> str:
    matrix = np.eye(4, dtype=np.float64)
    quaternion = np.asarray(calibration.quaternion, dtype=np.float64)
    if not math.isclose(float(np.linalg.norm(quaternion)), 1.0, abs_tol=1e-9):
        raise ValueError("euroc_dataset: IMU quaternions must have unit norm")
    matrix[:3, :3] = _quaternion_matrix(quaternion, calibration.quaternion_order)
    matrix[:3, 3] = np.asarray(calibration.translation, dtype=np.float64)
    lines = ["%YAML:1.0", "---", "sensor_type: imu"]
    lines.extend(_matrix_yaml(matrix))
    if calibration.nominal_rate_hz is None:
        raise ValueError("euroc_dataset: IMU nominal_rate_hz is required for writing")
    lines.append(f"rate_hz: {_format_float(calibration.nominal_rate_hz)}")
    if calibration.topic:
        lines.append(f"rostopic: {_yaml_text(calibration.topic)}")
    for field in (
        "gyroscope_noise_density",
        "gyroscope_random_walk",
        "accelerometer_noise_density",
        "accelerometer_random_walk",
    ):
        value = getattr(calibration, field)
        if value is not None:
            lines.append(f"{field}: {_format_float(value)}")
    return "\n".join(lines) + "\n"


def _validate_write(dataset: VisualInertialDataset) -> None:
    if not isinstance(dataset, VisualInertialDataset):
        raise TypeError("euroc_dataset: writer requires VisualInertialDataset")
    if dataset.num_cameras == 0 or dataset.num_imus == 0:
        raise ValueError("euroc_dataset: writer requires camera and IMU streams")
    rig = dataset.rig
    if (
        rig.quaternion_order != "wxyz"
        or rig.quaternion_sign != "canonical_positive_w"
        or rig.transform_convention != "camera_to_reference"
        or rig.axis_frame != "opencv"
        or rig.reference_frame != "rig"
        or rig.scale_to_meters != 1.0
    ):
        raise ValueError("euroc_dataset: CameraRig conventions are not representable")
    if any(
        np.asarray(field).any()
        for field in (
            rig.has_camera_matrix,
            rig.has_rectification,
            rig.has_projection_matrix,
            rig.has_operational,
        )
    ):
        raise ValueError("euroc_dataset: CameraRig matrix/ROI metadata is not representable")
    for index, (name, stream, timestamps, clock, epoch) in enumerate(
        zip(
            dataset.camera_names,
            dataset.camera_streams,
            dataset.camera_timestamps_ns,
            dataset.camera_clock_domains,
            dataset.camera_timestamp_epochs,
            strict=True,
        )
    ):
        match = _CAMERA_NAME.fullmatch(name)
        if match is None or int(match.group("index")) != index:
            raise ValueError("euroc_dataset: camera names must be cam0..camN")
        if int(rig.camera_ids[index]) != index or not rig.has_extrinsics[index]:
            raise ValueError("euroc_dataset: camera ids/extrinsics are not representable")
        if clock != name or epoch != "dataset":
            raise ValueError("euroc_dataset: camera clock metadata is not representable")
        if stream.storage_mode != "encoded_paths" or stream.has_timing or stream.has_acquisition_timing:
            raise ValueError("euroc_dataset: camera stream metadata is not representable")
        if len(timestamps) != stream.num_frames or stream.num_frames == 0:
            raise ValueError("euroc_dataset: camera timestamps are inconsistent")
        prefix = f"mav0/{name}/data/"
        for frame_name in stream.frame_names:
            if not frame_name.startswith(prefix) or "/" in frame_name[len(prefix) :]:
                raise ValueError(
                    "euroc_dataset: frame names must be dataset-root-relative ASL paths"
                )
    for index, (name, calibration, stream, epoch) in enumerate(
        zip(
            dataset.imu_names,
            dataset.imu_calibrations,
            dataset.imu_streams,
            dataset.imu_timestamp_epochs,
            strict=True,
        )
    ):
        match = _IMU_NAME.fullmatch(name)
        if match is None or int(match.group("index")) != index:
            raise ValueError("euroc_dataset: IMU names must be imu0..imuN")
        if calibration.sensor_id != index or stream.sensor_id != index:
            raise ValueError("euroc_dataset: IMU sensor ids must match their indices")
        if (
            calibration.quaternion_order != "wxyz"
            or calibration.quaternion_sign != "canonical_positive_w"
            or calibration.sensor_axis_frame != "sensor"
            or calibration.reference_frame != "rig"
            or calibration.time_offset_ns is not None
        ):
            raise ValueError("euroc_dataset: IMU calibration is not representable")
        if stream.clock_domain != name or epoch != "dataset":
            raise ValueError("euroc_dataset: IMU clock metadata is not representable")
    if dataset.ground_truth is not None and dataset.ground_truth_timestamp_epoch != "dataset":
        raise ValueError("euroc_dataset: ground-truth epoch is not representable")


def _copy_file(source: Path, destination: Path) -> None:
    _regular_file(source, str(source))
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(_COPY_CHUNK):
            writer.write(chunk)


def _write_camera(
    frame_access: ImageFrameAccess,
    dataset: VisualInertialDataset,
    index: int,
    sensor_path: Path,
) -> None:
    stream = dataset.camera_streams[index]
    sources = tuple(Path(value) for value in stream.frame_paths)
    width = int(dataset.rig.resolutions[index, 0])
    height = int(dataset.rig.resolutions[index, 1])
    channels, dtype = _frame_metadata(frame_access, sources, (width, height))
    if (channels, dtype) != (stream.channels, stream.frame_dtype):
        raise ValueError("euroc_dataset: referenced frames disagree with ImageSequence")
    data_path = sensor_path / "data"
    data_path.mkdir(parents=True)
    rows = [_CAMERA_HEADER.decode("ascii")]
    for timestamp, relative_name, source in zip(
        dataset.camera_timestamps_ns[index],
        stream.frame_names,
        sources,
        strict=True,
    ):
        filename = relative_name.rsplit("/", 1)[-1]
        _copy_file(source, data_path / filename)
        rows.append(f"{int(timestamp)},{filename}")
    (sensor_path / "data.csv").write_text(
        "\n".join(rows) + "\n", encoding="utf-8", newline="\n"
    )
    (sensor_path / "sensor.yaml").write_text(
        _camera_yaml(dataset, index), encoding="utf-8", newline="\n"
    )


def _write_imu(dataset: VisualInertialDataset, index: int, sensor_path: Path) -> None:
    calibration = dataset.imu_calibrations[index]
    (sensor_path / "sensor.yaml").write_text(
        _imu_yaml(calibration), encoding="utf-8", newline="\n"
    )
    _core._write_to_file(
        _core.write_euroc_imu,
        dataset.imu_streams[index],
        str(sensor_path / "data.csv"),
    )


def _install_directory(stage: Path, destination: Path) -> None:
    backup: Path | None = None
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError(
                "euroc_dataset: destination exists and is not a regular directory"
            )
        backup = destination.with_name(
            f".{destination.name}.sceneio-previous-{uuid.uuid4().hex}"
        )
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except BaseException:
        if backup is not None and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def write_euroc_dataset(
    frame_access: ImageFrameAccess,
    dataset: VisualInertialDataset,
    path: str | Path,
) -> None:
    """Write a deterministic bounded ASL directory transactionally."""

    _validate_write(dataset)
    destination = Path(path)
    if not destination.parent.is_dir():
        raise ValueError("euroc_dataset: output parent does not exist")
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.sceneio-stage-",
            dir=destination.parent,
        )
    )
    try:
        mav0 = stage / "mav0"
        mav0.mkdir()
        for index, name in enumerate(dataset.camera_names):
            sensor_path = mav0 / name
            sensor_path.mkdir()
            _write_camera(frame_access, dataset, index, sensor_path)
        for index, name in enumerate(dataset.imu_names):
            sensor_path = mav0 / name
            sensor_path.mkdir()
            _write_imu(dataset, index, sensor_path)
        if dataset.ground_truth is not None:
            sensor_path = mav0 / _GROUND_TRUTH_NAME
            sensor_path.mkdir()
            (sensor_path / "sensor.yaml").write_text(
                "%YAML:1.0\n---\nsensor_type: ground_truth\n",
                encoding="utf-8",
                newline="\n",
            )
            _core._write_to_file(
                _core.write_euroc_state,
                dataset.ground_truth,
                str(sensor_path / "data.csv"),
            )
        _install_directory(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


__all__ = [
    "inspect_euroc_dataset",
    "is_euroc_dataset_directory",
    "read_euroc_dataset",
    "write_euroc_dataset",
]
