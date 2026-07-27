"""Shared helpers for benchmark codec-family specifications."""

from __future__ import annotations

import numpy as np


def _record_nbytes(record):
    names = (
        "quaternions",
        "translations",
        "camera_indices",
        "timestamps",
        "image_ids",
        "image_camera_ids",
        "point3D_ids",
        "xyz",
        "rgb",
        "errors",
        "positions",
        "velocities",
        "gyro_biases",
        "accel_biases",
        "timestamps_ns",
        "camera_ids",
        "resolutions",
        "intrinsic_offsets",
        "intrinsics",
        "distortion_offsets",
        "distortion_coefficients",
        "camera_matrices",
        "rectification_matrices",
        "projection_matrices",
        "binning",
        "roi",
        "time_offsets",
        "node_ids",
        "node_translations",
        "node_quaternions",
        "fixed",
        "edge_endpoints",
        "edge_translations",
        "edge_quaternions",
        "information_matrices",
    )
    total = sum(
        np.asarray(getattr(record, name)).nbytes
        for name in names
        if hasattr(record, name)
    )
    total += sum(
        np.asarray(camera.params).nbytes
        for camera in getattr(record, "cameras", ())
    )
    return max(total, 1)


__all__ = ["_record_nbytes"]
