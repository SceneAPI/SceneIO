"""ASL/EuRoC dataset adapter parity, selection, and resource contracts."""

from __future__ import annotations

import csv
import gc
import io
import tomllib
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy.spatial.transform import Rotation

import sceneio
from sceneio import _core
from sceneio.io._euroc_dataset import codec as adapter
from sceneio.io._frame_access import ImageFrameAccess

CONTRACT = tomllib.loads(
    (Path(__file__).parents[1] / "contracts/euroc_dataset_v1.toml").read_text(
        encoding="utf-8"
    )
)

CAMERA_HEADER = "#timestamp [ns],filename"
IMU_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],"
    "a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]"
)
STATE_HEADER = (
    "#timestamp [ns],p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],"
    "q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z [],"
    "v_RS_R_x [m s^-1],v_RS_R_y [m s^-1],v_RS_R_z [m s^-1],"
    "b_w_RS_S_x [rad s^-1],b_w_RS_S_y [rad s^-1],"
    "b_w_RS_S_z [rad s^-1],b_a_RS_S_x [m s^-2],"
    "b_a_RS_S_y [m s^-2],b_a_RS_S_z [m s^-2]"
)


def _matrix(index: int) -> np.ndarray:
    angle = index * np.pi / 2.0
    cosine = float(np.cos(angle))
    sine = float(np.sin(angle))
    return np.array(
        [
            [cosine, -sine, 0.0, index + 0.25],
            [sine, cosine, 0.0, index + 0.5],
            [0.0, 0.0, 1.0, index + 0.75],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def _matrix_yaml(matrix: np.ndarray) -> str:
    values = ", ".join(format(float(value), ".17g") for value in matrix.flat)
    return (
        "T_BS: !!opencv-matrix\n"
        "  rows: 4\n"
        "  cols: 4\n"
        "  dt: d\n"
        f"  data: [{values}]\n"
    )


def _pgm(value: int, width: int = 4, height: int = 3) -> bytes:
    pixels = bytes((value + index) % 256 for index in range(width * height))
    return f"P5\n{width} {height}\n255\n".encode() + pixels


def _write_camera(root: Path, index: int) -> None:
    sensor = root / "mav0" / f"cam{index}"
    data = sensor / "data"
    data.mkdir(parents=True)
    timestamps = (100 + index * 10, 200 + index * 10, 300 + index * 10)
    names = tuple(f"{timestamp}.pgm" for timestamp in timestamps)
    for frame_index, name in enumerate(names):
        (data / name).write_bytes(_pgm(10 * index + frame_index))
    (sensor / "data.csv").write_text(
        CAMERA_HEADER
        + "\n"
        + "".join(
            f"{timestamp},{name}\n"
            for timestamp, name in zip(timestamps, names, strict=True)
        ),
        encoding="utf-8",
        newline="\n",
    )
    (sensor / "sensor.yaml").write_text(
        "%YAML:1.0\n"
        "---\n"
        "sensor_type: camera\n"
        + _matrix_yaml(_matrix(index))
        + f"rate_hz: {20 + index}\n"
        "resolution: [4, 3]\n"
        "camera_model: pinhole\n"
        f"intrinsics: [{400 + index}, {401 + index}, 2, 1.5]\n"
        "distortion_model: radtan\n"
        f"distortion_coefficients: [0.0, 0.0, {index / 100}, 0.0]\n"
        f"rostopic: /cam{index}/image_raw\n"
        f"timeshift_cam_imu: {-0.001 * (index + 1)}\n",
        encoding="utf-8",
        newline="\n",
    )


def _imu_rows(index: int) -> tuple[tuple[int, tuple[float, ...]], ...]:
    return tuple(
        (
            timestamp,
            tuple(index * 100.0 + row * 10.0 + component / 8.0 for component in range(6)),
        )
        for row, timestamp in enumerate((90, 150, 210, 270, 330))
    )


def _write_imu(root: Path, index: int) -> None:
    sensor = root / "mav0" / f"imu{index}"
    sensor.mkdir(parents=True)
    (sensor / "sensor.yaml").write_text(
        "%YAML:1.0\n"
        "---\n"
        "sensor_type: imu\n"
        + _matrix_yaml(_matrix(index + 2))
        + f"rate_hz: {200 + index}\n"
        f"rostopic: /imu{index}\n"
        f"gyroscope_noise_density: {0.001 + index / 1000}\n"
        f"gyroscope_random_walk: {0.002 + index / 1000}\n"
        f"accelerometer_noise_density: {0.003 + index / 1000}\n"
        f"accelerometer_random_walk: {0.004 + index / 1000}\n",
        encoding="utf-8",
        newline="\n",
    )
    lines = [IMU_HEADER]
    for timestamp, values in _imu_rows(index):
        lines.append(
            ",".join((str(timestamp), *(format(value, ".17g") for value in values)))
        )
    (sensor / "data.csv").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_ground_truth(root: Path) -> None:
    sensor = root / "mav0" / "state_groundtruth_estimate0"
    sensor.mkdir(parents=True)
    (sensor / "sensor.yaml").write_text(
        "%YAML:1.0\n---\nsensor_type: ground_truth\n",
        encoding="utf-8",
        newline="\n",
    )
    rows = [STATE_HEADER]
    for index, timestamp in enumerate((100, 200, 300)):
        values = (
            index + 0.25,
            index + 0.5,
            index + 0.75,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            2.0,
            3.0,
            0.01,
            0.02,
            0.03,
            0.1,
            0.2,
            0.3,
        )
        rows.append(
            ",".join((str(timestamp), *(format(value, ".17g") for value in values)))
        )
    (sensor / "data.csv").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _fixture(
    path: Path,
    *,
    camera_count: int = 2,
    imu_count: int = 2,
    ground_truth: bool = True,
) -> Path:
    for index in range(camera_count):
        _write_camera(path, index)
    for index in range(imu_count):
        _write_imu(path, index)
    if ground_truth:
        _write_ground_truth(path)
    return path


def _yaml_oracle(path: Path) -> dict[str, object]:
    class OpenCvSafeLoader(yaml.SafeLoader):
        pass

    OpenCvSafeLoader.add_constructor(
        "tag:yaml.org,2002:opencv-matrix",
        lambda loader, node: loader.construct_mapping(node, deep=True),
    )
    text = path.read_text(encoding="utf-8").removeprefix("%YAML:1.0\n")
    return yaml.load(text, Loader=OpenCvSafeLoader)


def _csv_oracle(path: Path, width: int) -> tuple[list[str], np.ndarray]:
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    assert len(rows[0]) == width
    payload = [row for row in rows[1:] if row and not row[0].lstrip().startswith("#")]
    assert all(len(row) == width for row in payload)
    return rows[0], np.asarray(payload, dtype=object)


def _assert_float_bits_equal(left: np.ndarray, right: np.ndarray) -> None:
    np.testing.assert_array_equal(left.view(np.uint64), right.view(np.uint64))


def _assert_datasets_equal(expected, actual) -> None:
    assert actual.camera_names == expected.camera_names
    assert actual.imu_names == expected.imu_names
    assert actual.camera_rates_hz == expected.camera_rates_hz
    assert actual.camera_clock_domains == expected.camera_clock_domains
    assert actual.camera_timestamp_epochs == expected.camera_timestamp_epochs
    assert actual.imu_timestamp_epochs == expected.imu_timestamp_epochs
    for field in (
        "camera_ids",
        "resolutions",
        "intrinsic_offsets",
        "intrinsics",
        "distortion_offsets",
        "distortion_coefficients",
        "quaternions",
        "translations",
        "has_extrinsics",
        "time_offsets",
        "has_time_offset",
    ):
        np.testing.assert_array_equal(
            np.asarray(getattr(actual.rig, field)),
            np.asarray(getattr(expected.rig, field)),
        )
    for field in (
        "projection_models",
        "distortion_models",
        "topics",
        "quaternion_order",
        "quaternion_sign",
        "transform_convention",
        "axis_frame",
        "reference_frame",
        "scale_to_meters",
    ):
        assert getattr(actual.rig, field) == getattr(expected.rig, field)
    for left, right in zip(
        expected.camera_streams, actual.camera_streams, strict=True
    ):
        assert right.frame_names == left.frame_names
        assert right.frame_dtype == left.frame_dtype
        assert right.channels == left.channels
        assert (right.height, right.width) == (left.height, left.width)
        for left_path, right_path in zip(
            left.frame_paths, right.frame_paths, strict=True
        ):
            assert Path(right_path).read_bytes() == Path(left_path).read_bytes()
    for left, right in zip(
        expected.camera_timestamps_ns,
        actual.camera_timestamps_ns,
        strict=True,
    ):
        np.testing.assert_array_equal(right, left)
    for left, right in zip(
        expected.imu_calibrations,
        actual.imu_calibrations,
        strict=True,
    ):
        for field in (
            "sensor_id",
            "name",
            "topic",
            "nominal_rate_hz",
            "gyroscope_noise_density",
            "gyroscope_random_walk",
            "accelerometer_noise_density",
            "accelerometer_random_walk",
            "time_offset_ns",
            "quaternion_order",
            "quaternion_sign",
            "sensor_axis_frame",
            "reference_frame",
        ):
            assert getattr(right, field) == getattr(left, field)
        np.testing.assert_array_equal(right.quaternion, left.quaternion)
        np.testing.assert_array_equal(right.translation, left.translation)
    for left, right in zip(expected.imu_streams, actual.imu_streams, strict=True):
        for field in (
            "sensor_id",
            "angular_velocity_unit",
            "linear_acceleration_unit",
            "sensor_axis_frame",
            "timestamp_reference",
            "clock_domain",
        ):
            assert getattr(right, field) == getattr(left, field)
        np.testing.assert_array_equal(right.timestamps_ns, left.timestamps_ns)
        _assert_float_bits_equal(
            np.asarray(right.angular_velocities),
            np.asarray(left.angular_velocities),
        )
        _assert_float_bits_equal(
            np.asarray(right.linear_accelerations),
            np.asarray(left.linear_accelerations),
        )
    assert (actual.ground_truth is None) is (expected.ground_truth is None)
    assert (
        actual.ground_truth_timestamp_epoch
        == expected.ground_truth_timestamp_epoch
    )
    if expected.ground_truth is not None:
        for field in (
            "timestamps_ns",
            "positions",
            "quaternions",
            "velocities",
            "gyro_biases",
            "accel_biases",
        ):
            np.testing.assert_array_equal(
                np.asarray(getattr(actual.ground_truth, field)),
                np.asarray(getattr(expected.ground_truth, field)),
            )


def test_versioned_profile_contract_matches_the_live_codec():
    assert CONTRACT["format_id"] == "euroc_dataset"
    assert CONTRACT["datatype"] == "visual_inertial_dataset"
    assert CONTRACT["coordinates"] == {
        "t_bs_direction": "sensor_to_body",
        "sceneio_reference_frame": "rig",
        "camera_transform_convention": "camera_to_reference",
        "imu_transform_convention": "sensor_to_reference",
        "camera_axis_frame": "opencv",
        "ground_truth_pose_convention": "sensor_to_reference",
        "quaternion_order": "wxyz",
        "writer_quaternion_sign": "canonical_positive_w",
        "translation_unit": "meters",
    }
    assert CONTRACT["time"]["timestamp_unit"] == "nanoseconds"
    assert CONTRACT["time"]["clock_alignment"] == "never_implicit"
    capabilities = sceneio.capabilities("euroc_dataset")
    assert (
        capabilities.can_read
        and capabilities.can_write
        and capabilities.can_inspect
    )
    assert capabilities.coordinates.status == "file_declared"
    assert capabilities.coordinates.domains == ("camera", "image", "trajectory")


def test_oracle_authored_directory_decodes_exact_calibration_and_samples(tmp_path):
    root = _fixture(tmp_path / "source")
    dataset = sceneio.read(root)

    assert isinstance(dataset, sceneio.VisualInertialDataset)
    assert dataset.camera_names == ("cam0", "cam1")
    assert dataset.imu_names == ("imu0", "imu1")
    assert dataset.num_camera_frames == 6
    assert dataset.num_imu_samples == 10
    assert dataset.has_ground_truth
    assert dataset.camera_clock_domains == ("cam0", "cam1")
    assert dataset.camera_timestamp_epochs == ("dataset", "dataset")
    assert dataset.imu_timestamp_epochs == ("dataset", "dataset")

    for index, yaml_path in enumerate(sorted(root.glob("mav0/cam*/sensor.yaml"))):
        oracle = _yaml_oracle(yaml_path)
        matrix = np.asarray(oracle["T_BS"]["data"], np.float64).reshape(4, 4)
        actual_rotation = Rotation.from_quat(
            np.asarray(dataset.rig.quaternions[index])[[1, 2, 3, 0]]
        ).as_matrix()
        np.testing.assert_allclose(actual_rotation, matrix[:3, :3], atol=1e-15)
        np.testing.assert_array_equal(dataset.rig.translations[index], matrix[:3, 3])
        assert dataset.rig.transform_convention == "camera_to_reference"
        assert dataset.rig.reference_frame == "rig"
        assert dataset.camera_rates_hz[index] == oracle["rate_hz"]
        np.testing.assert_array_equal(
            dataset.rig.resolutions[index], oracle["resolution"]
        )
        assert dataset.rig.projection_models[index] == oracle["camera_model"]
        begin = int(dataset.rig.intrinsic_offsets[index])
        end = int(dataset.rig.intrinsic_offsets[index + 1])
        np.testing.assert_array_equal(
            dataset.rig.intrinsics[begin:end], oracle["intrinsics"]
        )
        assert (
            dataset.rig.distortion_models[index]
            == oracle["distortion_model"]
        )
        begin = int(dataset.rig.distortion_offsets[index])
        end = int(dataset.rig.distortion_offsets[index + 1])
        np.testing.assert_array_equal(
            dataset.rig.distortion_coefficients[begin:end],
            oracle["distortion_coefficients"],
        )
        assert dataset.rig.topics[index] == oracle["rostopic"]
        assert bool(dataset.rig.has_time_offset[index])
        assert dataset.rig.time_offsets[index] == oracle["timeshift_cam_imu"]

    for index, (calibration, stream) in enumerate(
        zip(dataset.imu_calibrations, dataset.imu_streams, strict=True)
    ):
        oracle = _yaml_oracle(root / "mav0" / f"imu{index}" / "sensor.yaml")
        matrix = np.asarray(oracle["T_BS"]["data"], np.float64).reshape(4, 4)
        actual_rotation = Rotation.from_quat(
            np.asarray(calibration.quaternion)[[1, 2, 3, 0]]
        ).as_matrix()
        np.testing.assert_allclose(actual_rotation, matrix[:3, :3], atol=1e-15)
        np.testing.assert_array_equal(calibration.translation, matrix[:3, 3])
        assert calibration.sensor_id == index
        assert calibration.name == f"imu{index}"
        assert calibration.topic == oracle["rostopic"]
        assert calibration.nominal_rate_hz == oracle["rate_hz"]
        for field in (
            "gyroscope_noise_density",
            "gyroscope_random_walk",
            "accelerometer_noise_density",
            "accelerometer_random_walk",
        ):
            assert getattr(calibration, field) == oracle[field]
        _header, oracle_rows = _csv_oracle(
            root / "mav0" / f"imu{index}" / "data.csv", 7
        )
        np.testing.assert_array_equal(
            stream.timestamps_ns,
            oracle_rows[:, 0].astype(np.int64),
        )
        _assert_float_bits_equal(
            np.asarray(stream.angular_velocities),
            oracle_rows[:, 1:4].astype(np.float64),
        )
        _assert_float_bits_equal(
            np.asarray(stream.linear_accelerations),
            oracle_rows[:, 4:7].astype(np.float64),
        )

    _header, oracle_rows = _csv_oracle(
        root / "mav0" / "state_groundtruth_estimate0" / "data.csv", 17
    )
    values = oracle_rows[:, 1:].astype(np.float64)
    np.testing.assert_array_equal(
        dataset.ground_truth.timestamps_ns,
        oracle_rows[:, 0].astype(np.int64),
    )
    for field, expected in (
        ("positions", values[:, 0:3]),
        ("quaternions", values[:, 3:7]),
        ("velocities", values[:, 7:10]),
        ("gyro_biases", values[:, 10:13]),
        ("accel_biases", values[:, 13:16]),
    ):
        _assert_float_bits_equal(
            np.asarray(getattr(dataset.ground_truth, field)), expected
        )


def test_public_detect_inspect_write_and_oracle_readback(tmp_path):
    source = _fixture(tmp_path / "source")
    expected = sceneio.read(source)
    inspection = sceneio.inspect(source)
    assert sceneio.detect(source) == "euroc_dataset"
    assert inspection.format == "euroc_dataset"
    assert inspection.datatype == "visual_inertial_dataset"
    assert inspection.count == 16
    assert inspection.metadata == {
        "camera_names": ("cam0", "cam1"),
        "imu_names": ("imu0", "imu1"),
        "camera_counts": (3, 3),
        "imu_counts": (5, 5),
        "camera_resolutions": (4, 3, 4, 3),
        "first_timestamp_ns": 90,
        "last_timestamp_ns": 330,
        "has_ground_truth": True,
        "ground_truth_count": 3,
    }

    destination = tmp_path / "copy"
    sceneio.write(expected, destination, format="euroc_dataset")
    actual = sceneio.read_euroc_dataset(destination)
    _assert_datasets_equal(expected, actual)

    for yaml_path in destination.glob("mav0/*/sensor.yaml"):
        assert _yaml_oracle(yaml_path)["sensor_type"] in {
            "camera",
            "imu",
            "ground_truth",
        }
        source_yaml = source / yaml_path.relative_to(destination)
        expected_yaml = _yaml_oracle(source_yaml)
        actual_yaml = _yaml_oracle(yaml_path)
        expected_matrix = expected_yaml.pop("T_BS", None)
        actual_matrix = actual_yaml.pop("T_BS", None)
        assert actual_yaml == expected_yaml
        if expected_matrix is not None:
            np.testing.assert_allclose(
                actual_matrix["data"], expected_matrix["data"], atol=1e-15
            )
    for csv_path in destination.glob("mav0/*/data.csv"):
        source_csv = source / csv_path.relative_to(destination)
        assert csv_path.read_text(encoding="utf-8") == source_csv.read_text(
            encoding="utf-8"
        )
    for source_frame in source.glob("mav0/cam*/data/*.pgm"):
        relative = source_frame.relative_to(source)
        assert (destination / relative).read_bytes() == source_frame.read_bytes()


def test_typed_selection_equals_slices_of_full_read(tmp_path):
    root = _fixture(tmp_path / "source")
    full = sceneio.read_euroc_dataset(root)

    sensors = sceneio.read_euroc_dataset(
        root,
        cameras=["cam1"],
        imus=["imu0"],
        include_ground_truth=False,
    )
    assert sensors.camera_names == ("cam1",)
    assert sensors.imu_names == ("imu0",)
    assert not sensors.has_ground_truth
    np.testing.assert_array_equal(
        sensors.camera_timestamps_ns[0], full.camera_timestamps_ns[1]
    )
    np.testing.assert_array_equal(
        sensors.imu_streams[0].angular_velocities,
        full.imu_streams[0].angular_velocities,
    )

    frames = sceneio.read_euroc_dataset(root, frame_range=(1, 3))
    for index in range(2):
        np.testing.assert_array_equal(
            frames.camera_timestamps_ns[index],
            full.camera_timestamps_ns[index][1:3],
        )
        assert frames.camera_streams[index].frame_names == (
            full.camera_streams[index].frame_names[1:3]
        )
    assert frames.num_imu_samples == full.num_imu_samples

    timed = sceneio.read_euroc_dataset(root, time_range_ns=(190, 280))
    np.testing.assert_array_equal(timed.camera_timestamps_ns[0], [200])
    np.testing.assert_array_equal(timed.camera_timestamps_ns[1], [210])
    for stream in timed.imu_streams:
        np.testing.assert_array_equal(stream.timestamps_ns, [210, 270])
    np.testing.assert_array_equal(timed.ground_truth.timestamps_ns, [200])

    imu_only = sceneio.read_euroc_dataset(root, cameras=[])
    assert imu_only.num_cameras == 0
    assert imu_only.imu_names == full.imu_names
    camera_only = sceneio.read_euroc_dataset(root, imus=[])
    assert camera_only.camera_names == full.camera_names
    assert camera_only.num_imus == 0


def test_mmap_is_released_and_child_views_remain_owned(tmp_path):
    root = _fixture(tmp_path / "source", camera_count=1, imu_count=1)
    dataset = sceneio.read(root)
    angular = dataset.imu_streams[0].angular_velocities
    camera_timestamps = dataset.camera_timestamps_ns[0]
    source = Path(dataset.camera_streams[0].frame_paths[0])
    del dataset
    gc.collect()

    np.testing.assert_array_equal(angular[0], _imu_rows(0)[0][1][:3])
    np.testing.assert_array_equal(camera_timestamps, [100, 200, 300])
    assert not angular.flags.writeable
    assert not camera_timestamps.flags.writeable
    source.rename(source.with_suffix(".moved"))


def test_inspection_does_not_decode_image_payloads(tmp_path):
    root = _fixture(tmp_path / "source", camera_count=1, imu_count=1)

    def fail(_path: Path):
        raise AssertionError("image decoder was reached")

    access = ImageFrameAccess(
        extensions=lambda: frozenset({".pgm"}),
        inspect=fail,
    )
    result = adapter.inspect_euroc_dataset(access, root)
    assert result.metadata["camera_counts"] == (3,)
    assert result.metadata["imu_counts"] == (5,)


def test_native_imu_buffer_sink_oracle_and_input_ownership(tmp_path):
    path = _fixture(
        tmp_path / "source", camera_count=1, imu_count=1, ground_truth=False
    ) / "mav0" / "imu0" / "data.csv"
    payload = bytearray(path.read_bytes())
    sequence = _core.read_euroc_imu(
        memoryview(payload).toreadonly(),
        12,
        "imu-clock",
    )
    payload[:] = b"x" * len(payload)
    np.testing.assert_array_equal(sequence.timestamps_ns, [90, 150, 210, 270, 330])
    assert sequence.sensor_id == 12
    assert sequence.clock_domain == "imu-clock"

    encoded = bytes(_core.write_euroc_imu(sequence))
    header, rows = _csv_oracle_bytes(encoded, 7)
    assert ",".join(header) == IMU_HEADER
    np.testing.assert_array_equal(rows[:, 0].astype(np.int64), sequence.timestamps_ns)
    _assert_float_bits_equal(
        rows[:, 1:].astype(np.float64),
        np.column_stack(
            (sequence.angular_velocities, sequence.linear_accelerations)
        ),
    )

    output = tmp_path / "streamed.csv"
    _core._write_to_file(_core.write_euroc_imu, sequence, str(output))
    assert output.read_bytes() == encoded


def _csv_oracle_bytes(payload: bytes, width: int) -> tuple[list[str], np.ndarray]:
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    assert all(len(row) == width for row in rows)
    return rows[0], np.asarray(rows[1:], dtype=object)


def test_native_imu_mmap_avoids_whole_file_python_bytes(tmp_path):
    path = tmp_path / "large.csv"
    count = 60_000
    rows = [IMU_HEADER]
    rows.extend(
        f"{index + 1},{index / 7},{index / 11},0,1,2,3" for index in range(count)
    )
    path.write_text("\n".join(rows) + "\n", encoding="ascii", newline="\n")

    tracemalloc.start()
    mapped_result = adapter._mapped_call(path, _core.read_euroc_imu)
    _current, mapped_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    bytes_result = _core.read_euroc_imu(path.read_bytes())
    _current, bytes_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert mapped_result.num_samples == bytes_result.num_samples == count
    assert bytes_peak - mapped_peak > path.stat().st_size * 0.8


@pytest.mark.parametrize(
    ("relative", "old", "new", "message"),
    [
        ("mav0/cam0/data.csv", "200,200.pgm", "100,200.pgm", "strictly increasing"),
        ("mav0/cam0/data.csv", "200.pgm", "../200.pgm", "single path"),
        ("mav0/cam0/sensor.yaml", "sensor_type: camera", "sensor_type: lidar", "sensor_type"),
        ("mav0/imu0/data.csv", "150,10", "90,10", "strictly increasing"),
        (
            "mav0/imu0/data.csv",
            "90,0,0.125,0.25,0.375,0.5,0.625",
            "90,0,0.125,nan,0.375,0.5,0.625",
            "non-finite",
        ),
        ("mav0/cam0/sensor.yaml", "  rows: 4", "  rows: 3", "4x4"),
    ],
)
def test_invalid_directory_rows_are_refused(
    tmp_path,
    relative,
    old,
    new,
    message,
):
    root = _fixture(tmp_path / "source", camera_count=1, imu_count=1)
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read(root)


def test_missing_frame_and_noncontiguous_sensor_indices_are_refused(tmp_path):
    missing = _fixture(
        tmp_path / "missing", camera_count=1, imu_count=1, ground_truth=False
    )
    (missing / "mav0" / "cam0" / "data" / "200.pgm").unlink()
    with pytest.raises(sceneio.FormatError, match="regular file"):
        sceneio.read(missing)

    gap = _fixture(tmp_path / "gap", camera_count=2, imu_count=1)
    (gap / "mav0" / "cam1").rename(gap / "mav0" / "cam2")
    with pytest.raises(sceneio.FormatError, match="indices must be contiguous"):
        sceneio.read(gap, format="euroc_dataset")
    with pytest.raises(sceneio.FormatError, match="no directory format"):
        sceneio.detect(gap)


def test_selection_validation_and_empty_ranges_are_explicit(tmp_path):
    root = _fixture(tmp_path / "source", camera_count=1, imu_count=1)
    with pytest.raises(ValueError, match="mutually exclusive"):
        sceneio.read_euroc_dataset(
            root,
            frame_range=(0, 1),
            time_range_ns=(0, 1),
        )
    with pytest.raises(ValueError, match="selected camera"):
        sceneio.read_euroc_dataset(root, cameras=[], frame_range=(0, 1))
    with pytest.raises(ValueError, match="empty for camera"):
        sceneio.read_euroc_dataset(root, time_range_ns=(1_000, 2_000))
    with pytest.raises(ValueError, match="unknown camera"):
        sceneio.read_euroc_dataset(root, cameras=["cam9"])


def test_failed_staging_preserves_existing_destination(tmp_path, monkeypatch):
    source = _fixture(tmp_path / "source", camera_count=1, imu_count=1)
    dataset = sceneio.read(source)
    destination = tmp_path / "destination"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("unchanged", encoding="utf-8")

    def fail_copy(_source: Path, _destination: Path) -> None:
        raise OSError("injected copy failure")

    monkeypatch.setattr(adapter, "_copy_file", fail_copy)
    with pytest.raises(sceneio.FormatError, match="injected copy failure"):
        sceneio.write(dataset, destination, format="euroc_dataset")
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert tuple(destination.iterdir()) == (marker,)


def test_writer_refuses_metadata_the_directory_cannot_preserve(tmp_path):
    root = _fixture(tmp_path / "source", camera_count=1, imu_count=1)
    dataset = sceneio.read(root)
    incompatible_imu = _core.imu_sequence(
        0,
        np.asarray(dataset.imu_streams[0].timestamps_ns),
        np.asarray(dataset.imu_streams[0].angular_velocities),
        np.asarray(dataset.imu_streams[0].linear_accelerations),
        angular_velocity_unit="degrees_per_second",
        clock_domain="imu0",
    )
    incompatible = sceneio.VisualInertialDataset(
        root=dataset.root,
        rig=dataset.rig,
        camera_streams=dataset.camera_streams,
        camera_timestamps_ns=dataset.camera_timestamps_ns,
        camera_rates_hz=dataset.camera_rates_hz,
        camera_clock_domains=dataset.camera_clock_domains,
        camera_timestamp_epochs=dataset.camera_timestamp_epochs,
        imu_calibrations=dataset.imu_calibrations,
        imu_streams=(incompatible_imu,),
        imu_timestamp_epochs=dataset.imu_timestamp_epochs,
        ground_truth=dataset.ground_truth,
        ground_truth_timestamp_epoch=dataset.ground_truth_timestamp_epoch,
    )
    with pytest.raises(sceneio.FormatError, match="not representable"):
        sceneio.write(incompatible, tmp_path / "output", format="euroc_dataset")

    calibration = dataset.imu_calibrations[0]
    duplicate_id = _core.imu_calibration(
        calibration.sensor_id,
        "imu_duplicate",
        "/imu_duplicate",
        np.asarray(calibration.quaternion),
        np.asarray(calibration.translation),
    )
    with pytest.raises(ValueError, match="IMU sensor ids must be unique"):
        sceneio.VisualInertialDataset(
            root=dataset.root,
            rig=dataset.rig,
            camera_streams=dataset.camera_streams,
            camera_timestamps_ns=dataset.camera_timestamps_ns,
            camera_rates_hz=dataset.camera_rates_hz,
            camera_clock_domains=dataset.camera_clock_domains,
            camera_timestamp_epochs=dataset.camera_timestamp_epochs,
            imu_calibrations=(calibration, duplicate_id),
            imu_streams=(dataset.imu_streams[0], dataset.imu_streams[0]),
            imu_timestamp_epochs=(
                dataset.imu_timestamp_epochs[0],
                dataset.imu_timestamp_epochs[0],
            ),
            ground_truth=dataset.ground_truth,
            ground_truth_timestamp_epoch=dataset.ground_truth_timestamp_epoch,
        )


def test_yaml_subset_rejects_duplicate_and_unsupported_values(tmp_path):
    sensor = tmp_path / "sensor.yaml"
    sensor.write_text("sensor_type: camera\nsensor_type: imu\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate YAML key"):
        adapter.parse_sensor_yaml(sensor)
    sensor.write_text("sensor_type: &anchor camera\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported construct"):
        adapter.parse_sensor_yaml(sensor)


def test_native_imu_rejects_invalid_schema_and_conventions():
    with pytest.raises(ValueError, match=r"header|columns"):
        _core.read_euroc_imu(b"a,b\n1,2\n")
    with pytest.raises(ValueError, match="strictly increasing"):
        _core.read_euroc_imu(
            (IMU_HEADER + "\n2,0,0,0,0,0,0\n1,0,0,0,0,0,0\n").encode()
        )
    incompatible = _core.imu_sequence(
        0,
        np.array([1], np.int64),
        np.zeros((1, 3)),
        np.zeros((1, 3)),
        linear_acceleration_unit="standard_gravity",
    )
    with pytest.raises(ValueError, match="not representable"):
        _core.write_euroc_imu(incompatible)
