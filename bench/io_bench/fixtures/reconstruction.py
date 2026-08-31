"""Deterministic fixtures for reconstruction-family benchmark codecs."""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import numpy as np

from bench.io_bench.oracles.reconstruction import _bal_oracle_write
from sceneio import _core
from sceneio._posed_views import posed_views_from_storage


def _poses_and_reconstruction(scale=1.0):
    points = max(1, int(10_000 * scale))
    views = max(1, int(10_000 * scale))
    reconstruction = _core.read_nvm(
        b"NVM_V3\n1\na.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\n"
        + str(points).encode()
        + b"\n"
        + b"1.5 -2.5 3.5 10 20 30 0\n" * points
        + b"0\n"
    )
    frame = b'{"file_path":"a.png","transform_matrix":[[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]]}'
    transforms = posed_views_from_storage(
        _core.read_transforms_json(
            b'{"camera_model":"PINHOLE","fl_x":500,"fl_y":510,"cx":320,"cy":240,'
            b'"w":640,"h":480,"frames":[' + b",".join([frame] * views) + b"]}"
        ),
        source_profile="transforms_json",
    )
    tum = posed_views_from_storage(
        _core.read_tum(b"0 1 2 3 0 0 0 1\n" * views),
        source_profile="tum",
    )
    kitti = posed_views_from_storage(
        _core.read_kitti(b"1 0 0 1 0 1 0 2 0 0 1 3\n" * views),
        source_profile="kitti",
    )
    return reconstruction, transforms, tum, kitti


def _modern_colmap_reconstruction(reconstruction):
    """Add a deterministic one-camera rig/frame envelope to a legacy model."""
    image_ids = np.asarray(reconstruction.image_ids)
    camera_ids = np.asarray(reconstruction.image_camera_ids)
    if image_ids.size != 1 or camera_ids.size != 1:
        raise ValueError(
            "modern COLMAP benchmark fixture requires one image"
        )
    image_id = int(image_ids[0])
    camera_id = int(camera_ids[0])
    quaternion = np.asarray(reconstruction.quaternions)[0]
    translation = np.asarray(reconstruction.translations)[0]
    rig_id = 1
    frame_id = 1
    rigs = struct.pack(
        "<QIIiI",
        1,
        rig_id,
        1,
        0,
        camera_id,
    )
    frames = struct.pack(
        "<QII7dIiIQ",
        1,
        frame_id,
        rig_id,
        *quaternion,
        *translation,
        1,
        0,
        camera_id,
        image_id,
    )
    with tempfile.TemporaryDirectory() as directory:
        _core.write_colmap_sparse(reconstruction, directory)
        root = Path(directory)
        (root / "rigs.bin").write_bytes(rigs)
        (root / "frames.bin").write_bytes(frames)
        modern = _core.read_colmap_sparse(directory)
    if not modern.has_rig_frame_model:
        raise AssertionError("modern COLMAP fixture lost its rig/frame model")
    return modern


def _euroc_fixture(scale):
    count = max(1, int(100_000 * scale))
    rng = np.random.default_rng(20260724)
    timestamps = (
        1_403_636_580_000_000_000
        + np.arange(count, dtype=np.int64) * 5_000_000
    )
    arrays = {
        "timestamps": timestamps,
        "positions": rng.standard_normal((count, 3)),
        "quaternions": rng.standard_normal((count, 4)),
        "velocities": rng.standard_normal((count, 3)),
        "gyro_biases": rng.standard_normal((count, 3)) * 0.01,
        "accel_biases": rng.standard_normal((count, 3)) * 0.1,
    }
    record = _core.state_trajectory(
        arrays["timestamps"],
        arrays["positions"],
        arrays["quaternions"],
        arrays["velocities"],
        arrays["gyro_biases"],
        arrays["accel_biases"],
    )
    return record, arrays


def _g2o_fixture(scale):
    count = max(2, int(25_000 * scale))
    ids = np.arange(count, dtype=np.int64) * 2 + 1
    node_translations = np.column_stack(
        (
            np.arange(count, dtype=np.float64) * 0.05,
            np.sin(np.arange(count, dtype=np.float64) * 0.01),
            np.zeros(count),
        )
    )
    node_quaternions = np.zeros((count, 4), np.float64)
    node_quaternions[:, 3] = 1
    edge_endpoints = np.column_stack((ids[:-1], ids[1:]))
    edges = len(edge_endpoints)
    edge_translations = np.column_stack(
        (
            np.full(edges, 0.05),
            np.diff(node_translations[:, 1]),
            np.zeros(edges),
        )
    )
    edge_quaternions = np.zeros((edges, 4), np.float64)
    edge_quaternions[:, 3] = 1
    information = np.tile(np.eye(6), (edges, 1, 1))
    fixed = np.zeros(count, np.uint8)
    fixed[0] = 1
    payload = {
        "node_ids": ids,
        "node_translations": node_translations,
        "node_quaternions": node_quaternions,
        "fixed": fixed,
        "edge_endpoints": edge_endpoints,
        "edge_translations": edge_translations,
        "edge_quaternions": edge_quaternions,
        "information_matrices": information,
    }
    return (
        _core.pose_graph(
            ids,
            node_translations,
            node_quaternions,
            edge_endpoints,
            edge_translations,
            edge_quaternions,
            information,
            fixed=fixed,
        ),
        payload,
    )


def _bal_fixture(scale):
    camera_count = max(1, int(1000 * scale))
    point_count = max(1, int(10_000 * scale))
    views_per_point = min(camera_count, 2)
    point_indices = np.repeat(
        np.arange(point_count, dtype=np.int32), views_per_point
    )
    camera_indices = np.tile(
        np.arange(views_per_point, dtype=np.int32), point_count
    )
    rng = np.random.default_rng(8)
    observations = rng.normal(
        0, 500, (len(point_indices), 2)
    ).astype(np.float64)
    cameras = np.zeros((camera_count, 9), dtype=np.float64)
    cameras[:, 2] = np.arange(camera_count) * 1e-5
    cameras[:, 3] = np.arange(camera_count) * 0.01
    cameras[:, 6] = 800 + np.arange(camera_count) % 200
    cameras[:, 7] = 0.01
    cameras[:, 8] = 0.001
    points = rng.normal(0, 100, (point_count, 3)).astype(np.float64)
    payload = {
        "camera_indices": camera_indices,
        "point_indices": point_indices,
        "observations": observations,
        "cameras": cameras,
        "points": points,
    }
    return _core.read_bal(_bal_oracle_write(payload)), payload


__all__ = [
    "_bal_fixture",
    "_euroc_fixture",
    "_g2o_fixture",
    "_modern_colmap_reconstruction",
    "_poses_and_reconstruction",
]
