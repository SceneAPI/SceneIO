"""Generated multi-sensor dataset fixtures for the I/O benchmark."""

from __future__ import annotations

from pathlib import Path

import numpy as np

import sceneio

_CAMERA_HEADER = "#timestamp [ns],filename"
_IMU_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],"
    "a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]"
)
_STATE_HEADER = (
    "#timestamp [ns],p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],"
    "q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z [],"
    "v_RS_R_x [m s^-1],v_RS_R_y [m s^-1],v_RS_R_z [m s^-1],"
    "b_w_RS_S_x [rad s^-1],b_w_RS_S_y [rad s^-1],"
    "b_w_RS_S_z [rad s^-1],b_a_RS_S_x [m s^-2],"
    "b_a_RS_S_y [m s^-2],b_a_RS_S_z [m s^-2]"
)
_IDENTITY = (
    "T_BS: !!opencv-matrix\n"
    "  rows: 4\n"
    "  cols: 4\n"
    "  dt: d\n"
    "  data: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]\n"
)


def _euroc_dataset_fixture(root: Path, scale: float):
    source = Path(root) / "_euroc_dataset_input"
    camera = source / "mav0" / "cam0"
    image_directory = camera / "data"
    imu = source / "mav0" / "imu0"
    ground_truth = source / "mav0" / "state_groundtruth_estimate0"
    image_directory.mkdir(parents=True)
    imu.mkdir()
    ground_truth.mkdir()

    frame_count = max(3, int(64 * scale))
    sample_count = max(16, int(20_000 * scale))
    side = max(8, int(256 * scale**0.5))
    rng = np.random.default_rng(83)
    camera_timestamps = (
        1_000_000_000
        + np.arange(frame_count, dtype=np.int64) * 50_000_000
    )
    camera_rows = [_CAMERA_HEADER]
    for timestamp in camera_timestamps:
        name = f"{int(timestamp)}.pgm"
        pixels = rng.integers(0, 256, (side, side), dtype=np.uint8)
        (image_directory / name).write_bytes(
            f"P5\n{side} {side}\n255\n".encode() + pixels.tobytes()
        )
        camera_rows.append(f"{int(timestamp)},{name}")
    (camera / "data.csv").write_text(
        "\n".join(camera_rows) + "\n",
        encoding="ascii",
        newline="\n",
    )
    (camera / "sensor.yaml").write_text(
        "%YAML:1.0\n---\nsensor_type: camera\n"
        + _IDENTITY
        + "rate_hz: 20\n"
        + f"resolution: [{side}, {side}]\n"
        + f"camera_model: pinhole\nintrinsics: [{side}, {side}, "
        + f"{side / 2}, {side / 2}]\n"
        + "distortion_model: radtan\n"
        + "distortion_coefficients: [0, 0, 0, 0]\n"
        + "rostopic: /cam0/image_raw\n",
        encoding="ascii",
        newline="\n",
    )

    imu_timestamps = (
        1_000_000_000
        + np.arange(sample_count, dtype=np.int64) * 5_000_000
    )
    samples = rng.normal(size=(sample_count, 6))
    imu_rows = [_IMU_HEADER]
    imu_rows.extend(
        ",".join(
            (
                str(int(timestamp)),
                *(format(float(value), ".17g") for value in row),
            )
        )
        for timestamp, row in zip(imu_timestamps, samples, strict=True)
    )
    (imu / "data.csv").write_text(
        "\n".join(imu_rows) + "\n",
        encoding="ascii",
        newline="\n",
    )
    (imu / "sensor.yaml").write_text(
        "%YAML:1.0\n---\nsensor_type: imu\n"
        + _IDENTITY
        + "rate_hz: 200\n"
        + "rostopic: /imu0\n"
        + "gyroscope_noise_density: 0.001\n"
        + "gyroscope_random_walk: 0.002\n"
        + "accelerometer_noise_density: 0.003\n"
        + "accelerometer_random_walk: 0.004\n",
        encoding="ascii",
        newline="\n",
    )

    state_count = min(frame_count, 64)
    state_rows = [_STATE_HEADER]
    for index, timestamp in enumerate(camera_timestamps[:state_count]):
        values = (
            float(index),
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        )
        state_rows.append(
            ",".join(
                (
                    str(int(timestamp)),
                    *(format(value, ".17g") for value in values),
                )
            )
        )
    (ground_truth / "data.csv").write_text(
        "\n".join(state_rows) + "\n",
        encoding="ascii",
        newline="\n",
    )
    (ground_truth / "sensor.yaml").write_text(
        "%YAML:1.0\n---\nsensor_type: ground_truth\n",
        encoding="ascii",
        newline="\n",
    )

    dataset = sceneio.read_euroc_dataset(source)
    logical_bytes = (
        frame_count * side * side
        + camera_timestamps.nbytes
        + imu_timestamps.nbytes
        + samples.nbytes
        + state_count * (8 + 16 * 8)
    )
    return dataset, logical_bytes


__all__ = ["_euroc_dataset_fixture"]
