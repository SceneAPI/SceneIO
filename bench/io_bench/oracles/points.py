"""Independent or library-backed oracles for point-cloud codecs."""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import numpy as np

try:
    import laspy
except Exception:
    laspy = None
try:
    import open3d as o3d
except Exception:
    o3d = None


def _laspy_w(payload):
    hdr = laspy.LasHeader(version="1.2", point_format=2)
    hdr.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(hdr)
    positions = payload["positions"]
    colors16 = payload["colors16"]
    las.x, las.y, las.z = positions[:, 0], positions[:, 1], positions[:, 2]
    las.red, las.green, las.blue = (
        colors16[:, 0],
        colors16[:, 1],
        colors16[:, 2],
    )
    las.intensity = payload["intensity"]
    b = io.BytesIO()
    las.write(b)
    return b.getvalue()


def _laspy_laz_w(payload):
    hdr = laspy.LasHeader(version="1.2", point_format=2)
    hdr.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(hdr)
    positions = payload["positions"]
    colors16 = payload["colors16"]
    las.x, las.y, las.z = positions[:, 0], positions[:, 1], positions[:, 2]
    las.red, las.green, las.blue = (
        colors16[:, 0],
        colors16[:, 1],
        colors16[:, 2],
    )
    las.intensity = payload["intensity"]
    b = io.BytesIO()
    las.write(b, do_compress=True)
    return b.getvalue()


def _laspy_r(data):
    return laspy.read(io.BytesIO(data))


def _open3d_ply_w(payload):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(payload["positions"])
    cloud.normals = o3d.utility.Vector3dVector(payload["normals"])
    cloud.colors = o3d.utility.Vector3dVector(
        payload["colors"].astype(np.float64) / 255.0
    )
    fd, path = tempfile.mkstemp(suffix=".ply")
    os.close(fd)
    try:
        if not o3d.io.write_point_cloud(
            path, cloud, write_ascii=False, compressed=False
        ):
            raise RuntimeError("Open3D rejected PLY write")
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _open3d_ply_r(data):
    fd, path = tempfile.mkstemp(suffix=".ply")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        return o3d.io.read_point_cloud(path)
    finally:
        os.remove(path)


def _open3d_pcd_w(payload):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(payload["positions"])
    cloud.normals = o3d.utility.Vector3dVector(payload["normals"])
    cloud.colors = o3d.utility.Vector3dVector(
        payload["colors"].astype(np.float64) / 255.0
    )
    fd, path = tempfile.mkstemp(suffix=".pcd")
    os.close(fd)
    try:
        if not o3d.io.write_point_cloud(
            path, cloud, write_ascii=False, compressed=False
        ):
            raise RuntimeError("Open3D rejected PCD write")
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _open3d_pcd_r(data):
    fd, path = tempfile.mkstemp(suffix=".pcd")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        return o3d.io.read_point_cloud(path)
    finally:
        os.remove(path)


def _pts_oracle_write(points):
    text = io.StringIO()
    text.write(f"{len(points)}\n")
    np.savetxt(text, points, fmt="%.9g")
    return text.getvalue().encode()


def _pts_oracle_read(data):
    first, _, body = data.partition(b"\n")
    declared = int(first)
    points = np.loadtxt(
        io.BytesIO(body), dtype=np.float32, ndmin=2
    ).reshape(-1, 3)
    if len(points) != declared:
        raise ValueError("PTS count mismatch")
    return points


__all__ = [
    "_laspy_laz_w",
    "_laspy_r",
    "_laspy_w",
    "_open3d_pcd_r",
    "_open3d_pcd_w",
    "_open3d_ply_r",
    "_open3d_ply_w",
    "_pts_oracle_read",
    "_pts_oracle_write",
    "laspy",
    "o3d",
]
