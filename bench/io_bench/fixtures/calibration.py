"""Deterministic fixtures for calibration-family benchmark codecs."""

from __future__ import annotations

import numpy as np

from sceneio import _core


def _single_calibration(*, ros=False):
    matrix = np.array(
        [[500.0, 0.0, 320.0], [0.0, 510.0, 240.0], [0.0, 0.0, 1.0]]
    )
    distortion = np.array([0.1, -0.2, 0.01, 0.02, -0.001])
    kwargs = {
        "names": ["benchmark"],
        "camera_matrices": matrix[None],
    }
    if ros:
        kwargs.update(
            rectification_matrices=np.eye(3)[None],
            projection_matrices=np.array(
                [
                    [
                        [500.0, 0.0, 320.0, 0.0],
                        [0.0, 510.0, 240.0, 0.0],
                        [0.0, 0.0, 1.0, 0.0],
                    ]
                ]
            ),
            binning=np.zeros((1, 2), np.uint32),
            roi=np.zeros((1, 4), np.uint32),
            has_operational=np.ones(1, np.uint8),
        )
    rig = _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 5], np.uint64),
        distortion,
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
        has_extrinsics=np.zeros(1, np.uint8),
        **kwargs,
    )
    payload = {
        "image_width": 640,
        "image_height": 480,
        "camera_name": "benchmark",
        "camera_matrix": {
            "rows": 3,
            "cols": 3,
            "dt": "d",
            "data": matrix.ravel().tolist(),
        },
        "distortion_model": "plumb_bob",
        "distortion_coefficients": {
            "rows": 1,
            "cols": 5,
            "dt": "d",
            "data": distortion.tolist(),
        },
    }
    if ros:
        payload["camera_matrix"].pop("dt")
        payload["distortion_coefficients"].pop("dt")
        payload.update(
            rectification_matrix={
                "rows": 3,
                "cols": 3,
                "data": np.eye(3).ravel().tolist(),
            },
            projection_matrix={
                "rows": 3,
                "cols": 4,
                "data": np.asarray(
                    rig.projection_matrices
                ).ravel().tolist(),
            },
            binning_x=0,
            binning_y=0,
            roi={
                "x_offset": 0,
                "y_offset": 0,
                "height": 0,
                "width": 0,
                "do_rectify": False,
            },
        )
    return rig, payload


def _kalibr_calibration(scale):
    count = max(1, min(256, int(64 * scale)))
    matrix = np.array(
        [[500.0, 0.0, 320.0], [0.0, 510.0, 240.0], [0.0, 0.0, 1.0]]
    )
    rig = _core.camera_rig(
        np.arange(count, dtype=np.uint32),
        np.tile(np.array([[640, 480]], np.uint64), (count, 1)),
        ["pinhole"] * count,
        np.arange(count + 1, dtype=np.uint64) * 4,
        np.tile(np.array([500.0, 510.0, 320.0, 240.0]), count),
        ["radtan"] * count,
        np.arange(count + 1, dtype=np.uint64) * 4,
        np.tile(np.array([0.1, -0.2, 0.01, 0.02]), count),
        np.tile(
            np.array([[1.0, 0.0, 0.0, 0.0]]),
            (count, 1),
        ),
        np.column_stack(
            (
                np.arange(count, dtype=np.float64) * 0.01,
                np.zeros(count),
                np.zeros(count),
            )
        ),
        names=[f"cam{index}" for index in range(count)],
        camera_matrices=np.tile(matrix, (count, 1, 1)),
        topics=[
            f"/cam{index}/image_raw"
            for index in range(count)
        ],
        time_offsets=np.arange(count, dtype=np.float64) * 1e-6,
        quaternion_sign="canonical_positive_w",
        reference_frame="imu",
    )
    payload = {}
    for index in range(count):
        camera = {
            "camera_model": "pinhole",
            "intrinsics": [500.0, 510.0, 320.0, 240.0],
            "distortion_model": "radtan",
            "distortion_coeffs": [0.1, -0.2, 0.01, 0.02],
            "resolution": [640, 480],
            "rostopic": f"/cam{index}/image_raw",
            "timeshift_cam_imu": index * 1e-6,
        }
        transform = np.eye(4)
        transform[0, 3] = 0.0 if index == 0 else 0.01
        camera[
            "T_cam_imu" if index == 0 else "T_cn_cnm1"
        ] = transform.tolist()
        payload[f"cam{index}"] = camera
    return rig, payload


__all__ = ["_kalibr_calibration", "_single_calibration"]
