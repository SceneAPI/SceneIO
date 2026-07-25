"""O0-O5 I/O benchmark harness for docs/io_optimization_plan.md.

Measures, per codec, encode (write) + decode (read) throughput (MB/s over the raw
payload) and peak Python allocation (tracemalloc), for sceneio._core vs the oracle
library where one exists, on representative payloads for all 40 codecs. Read
measurements retain the legacy whole-file bytes/copy-decode path beside the
public registry mmap path, so their peak delta captures the input copy O1
removes and, for NPY/FLO, the decoded-array copy O2 removes. Write measurements
retain the in-memory bytes encoder beside the public file sink, so their peak
delta captures the output-sized Python allocation O3 removes. Oracle failures
degrade to "-" so the SceneIO measurements always print.

Run: python bench/bench_io.py [--runs N] [--scale S] [--cold-cache]
Synthetic fixtures are generated in a temporary directory and never committed.
"""

from __future__ import annotations

import argparse
import csv
import gc
import io
import json
import os
import sqlite3
import statistics
import struct
import tempfile
import threading
import time
import tracemalloc
import warnings
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np

import sceneio
from sceneio import _core

# --- optional oracle libs (degrade gracefully) ------------------------------
try:
    from PIL import Image as PILImage
except Exception:
    PILImage = None
try:
    import laspy
except Exception:
    laspy = None
try:
    import gsply
except Exception:
    gsply = None
try:
    import imageio.v3 as iio
except Exception:
    iio = None
try:
    import OpenEXR
except Exception:
    OpenEXR = None
try:
    import open3d as o3d
except Exception:
    o3d = None
try:
    import psutil
except Exception:
    psutil = None
try:
    import yaml
except Exception:
    yaml = None
try:
    from safetensors import safe_open as safetensors_open
    from safetensors.numpy import load as safetensors_load
    from safetensors.numpy import load_file as safetensors_load_file
    from safetensors.numpy import save as safetensors_save
    from safetensors.numpy import save_file as safetensors_save_file
except Exception:
    safetensors_open = None
    safetensors_load = None
    safetensors_load_file = None
    safetensors_save = None
    safetensors_save_file = None


def _measure(fn: Callable[[], object], runs: int) -> tuple[float, int]:
    """Median wall time and a separate peak traced-allocation pass.

    Keeping tracemalloc out of the timing loop matters for Python metadata
    scanners: tracing each small token allocation can otherwise dominate the
    operation and invert the measured O5 latency relationship.
    """
    fn()  # warm
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        r = fn()
        dt = time.perf_counter() - t0
        times.append(dt)
        del r
    gc.collect()
    tracemalloc.start()
    try:
        r = fn()
        _, peak = tracemalloc.get_traced_memory()
        del r
    finally:
        tracemalloc.stop()
    return statistics.median(times), peak


def _try(fn):
    """Run an oracle closure; return (median_time, None) sentinel on any failure."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return fn()
    except Exception:
        return None


def _measure_rss(fn):
    """Peak resident-set growth sampled during one call (0 when psutil is absent)."""
    if psutil is None:
        return 0
    gc.collect()
    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = baseline
    running = True

    def sample():
        nonlocal peak
        while running:
            peak = max(peak, process.memory_info().rss)
            time.sleep(0.0005)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        value = fn()
        peak = max(peak, process.memory_info().rss)
        del value
    finally:
        running = False
        sampler.join()
    return max(0, peak - baseline)


# --- payload builders -------------------------------------------------------
def _img_u8(h, w):
    a = np.random.default_rng(0).integers(0, 256, (h, w, 3), dtype=np.uint8)
    return _core.image(a, color_space="srgb"), a


def _img_f32(h, w):
    a = (np.random.default_rng(0).random((h, w, 3), dtype=np.float32) * 10.0).astype(np.float32)
    return _core.image(a, color_space="linear"), a


def _img_webp_palette(h, w):
    palette = np.array(
        [
            [0, 0, 0],
            [255, 255, 255],
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
            [255, 0, 255],
            [0, 255, 255],
        ],
        dtype=np.uint8,
    )
    yy, xx = np.indices((h, w))
    a = palette[((xx // 7) + (yy // 11)) % len(palette)]
    return _core.image(a, color_space="srgb"), a


def _depth_map(h, w):
    values = np.random.default_rng(7).standard_normal((h, w)).astype(np.float32)
    return (
        _core.depth_map(
            values,
            unit="unknown",
            invalid_policy="zero",
        ),
        values,
    )


def _pc(n, color):
    rng = np.random.default_rng(0)
    xyz = (rng.random((n, 3), dtype=np.float32) * 100.0).astype(np.float32)
    kw = {}
    if color:
        kw["colors16"] = (rng.random((n, 3)) * 65535).astype(np.uint16)
        kw["intensity"] = (rng.random(n) * 60000).astype(np.float32)
    return _core.point_cloud(xyz, **kw), xyz


def _pc_ply(n):
    rng = np.random.default_rng(17)
    xyz = (rng.random((n, 3), dtype=np.float32) * 100.0).astype(np.float32)
    normals = rng.standard_normal((n, 3)).astype(np.float32)
    colors = rng.integers(0, 256, (n, 3), dtype=np.uint8)
    payload = {"positions": xyz, "normals": normals, "colors": colors}
    return (
        _core.point_cloud(xyz, colors=colors, normals=normals),
        payload,
    )


def _gauss(n):
    rng = np.random.default_rng(0)
    f = lambda *s: rng.standard_normal(s).astype(np.float32)  # noqa: E731
    payload = {
        "means": f(n, 3),
        "scales": f(n, 3),
        "quats": f(n, 4),
        "opacities": f(n),
        "sh0": f(n, 3),
    }
    return (
        _core.gaussian_cloud(
            payload["means"],
            payload["scales"],
            payload["quats"],
            payload["opacities"],
            payload["sh0"],
        ),
        payload,
    )


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
    transforms = _core.read_transforms_json(
        b'{"camera_model":"PINHOLE","fl_x":500,"fl_y":510,"cx":320,"cy":240,'
        b'"w":640,"h":480,"frames":[' + b",".join([frame] * views) + b"]}"
    )
    tum = _core.read_tum(b"0 1 2 3 0 0 0 1\n" * views)
    kitti = _core.read_kitti(b"1 0 0 1 0 1 0 2 0 0 1 3\n" * views)
    return reconstruction, transforms, tum, kitti


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
    total = sum(np.asarray(getattr(record, name)).nbytes for name in names if hasattr(record, name))
    total += sum(np.asarray(camera.params).nbytes for camera in getattr(record, "cameras", ()))
    return max(total, 1)


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
                "data": np.asarray(rig.projection_matrices).ravel().tolist(),
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
        np.tile(np.array([[1.0, 0.0, 0.0, 0.0]]), (count, 1)),
        np.column_stack(
            (
                np.arange(count, dtype=np.float64) * 0.01,
                np.zeros(count),
                np.zeros(count),
            )
        ),
        names=[f"cam{index}" for index in range(count)],
        camera_matrices=np.tile(matrix, (count, 1, 1)),
        topics=[f"/cam{index}/image_raw" for index in range(count)],
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
        camera["T_cam_imu" if index == 0 else "T_cn_cnm1"] = transform.tolist()
        payload[f"cam{index}"] = camera
    return rig, payload


def _yaml_oracle_write(payload):
    if yaml is None:
        raise RuntimeError("PyYAML unavailable")
    return yaml.safe_dump(payload, sort_keys=False).encode()


def _yaml_oracle_read(data):
    if yaml is None:
        raise RuntimeError("PyYAML unavailable")
    text = (
        data.decode()
        .replace("%YAML:1.0", "")
        .replace("!!opencv-matrix", "")
    )
    return yaml.safe_load(text)


def _xml_oracle_write(payload):
    root = ET.Element("opencv_storage")
    for name, value in payload.items():
        node = ET.SubElement(root, name)
        if isinstance(value, dict):
            node.set("type_id", "opencv-matrix")
            for child_name in ("rows", "cols", "dt", "data"):
                if child_name not in value:
                    continue
                child = ET.SubElement(node, child_name)
                child_value = value[child_name]
                child.text = (
                    " ".join(str(item) for item in child_value)
                    if isinstance(child_value, list)
                    else str(child_value)
                )
        else:
            node.text = str(value)
    return ET.tostring(root)


def _xml_oracle_read(data):
    return ET.fromstring(data)


_EUROC_HEADER = (
    "#timestamp [ns]",
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
    "q_RS_w []",
    "q_RS_x []",
    "q_RS_y []",
    "q_RS_z []",
    "v_RS_R_x [m s^-1]",
    "v_RS_R_y [m s^-1]",
    "v_RS_R_z [m s^-1]",
    "b_w_RS_S_x [rad s^-1]",
    "b_w_RS_S_y [rad s^-1]",
    "b_w_RS_S_z [rad s^-1]",
    "b_a_RS_S_x [m s^-2]",
    "b_a_RS_S_y [m s^-2]",
    "b_a_RS_S_z [m s^-2]",
)


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


def _euroc_oracle_write(payload):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_EUROC_HEADER)
    combined = np.concatenate(
        (
            payload["positions"],
            payload["quaternions"],
            payload["velocities"],
            payload["gyro_biases"],
            payload["accel_biases"],
        ),
        axis=1,
    )
    for timestamp, values in zip(
        payload["timestamps"], combined, strict=True
    ):
        writer.writerow((int(timestamp), *map(float, values)))
    return output.getvalue().encode()


def _euroc_oracle_read(data):
    reader = csv.reader(io.StringIO(data.decode()))
    header = tuple(next(reader))
    if header != _EUROC_HEADER:
        raise ValueError("unexpected EuRoC header")
    rows = list(reader)
    return {
        "timestamps": np.asarray([int(row[0]) for row in rows], np.int64),
        "states": np.asarray(
            [[float(value) for value in row[1:]] for row in rows],
            np.float64,
        ),
    }


def _euroc_payload_nbytes(payload):
    return sum(value.nbytes for value in payload.values())


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


def _g2o_oracle_write(payload):
    lines = ["# independent g2o oracle"]
    for node_id, translation, quaternion in zip(
        payload["node_ids"],
        payload["node_translations"],
        payload["node_quaternions"],
        strict=True,
    ):
        values = (*translation, *quaternion)
        lines.append(
            "VERTEX_SE3:QUAT "
            + str(int(node_id))
            + " "
            + " ".join(f"{float(value):.17g}" for value in values)
        )
    lines.extend(
        f"FIX {int(node_id)}"
        for node_id, fixed in zip(
            payload["node_ids"], payload["fixed"], strict=True
        )
        if fixed
    )
    for endpoints, translation, quaternion, information in zip(
        payload["edge_endpoints"],
        payload["edge_translations"],
        payload["edge_quaternions"],
        payload["information_matrices"],
        strict=True,
    ):
        upper = (
            information[row, column]
            for row in range(6)
            for column in range(row, 6)
        )
        values = (*translation, *quaternion, *upper)
        lines.append(
            "EDGE_SE3:QUAT "
            + f"{int(endpoints[0])} {int(endpoints[1])} "
            + " ".join(f"{float(value):.17g}" for value in values)
        )
    return ("\n".join(lines) + "\n").encode()


def _g2o_oracle_read(data):
    nodes = 0
    edges = 0
    fixed = 0
    for raw in data.splitlines():
        fields = raw.partition(b"#")[0].split()
        if not fields:
            continue
        if fields[0] == b"VERTEX_SE3:QUAT" and len(fields) == 9:
            int(fields[1])
            np.asarray([float(value) for value in fields[2:]])
            nodes += 1
        elif fields[0] == b"EDGE_SE3:QUAT" and len(fields) == 31:
            int(fields[1])
            int(fields[2])
            np.asarray([float(value) for value in fields[3:]])
            edges += 1
        elif fields[0] == b"FIX" and len(fields) == 2:
            int(fields[1])
            fixed += 1
        else:
            raise ValueError("unsupported g2o record")
    return {"nodes": nodes, "edges": edges, "fixed": fixed}


def _g2o_payload_nbytes(payload):
    return sum(value.nbytes for value in payload.values())


# --- codec specs: (id, build, sio_write, sio_read, oracle_write, oracle_read, payload_bytes) ---
@dataclass
class Spec:
    id: str
    make: Callable
    w: Callable  # record -> bytes
    r: Callable  # bytes -> record
    ow: Callable | None  # oracle: payload -> bytes
    orr: Callable | None  # oracle: bytes -> obj
    nbytes: Callable  # (record, payload) -> logical payload bytes


def _pil_w(mode):
    def enc(a):
        b = io.BytesIO()
        PILImage.fromarray(a).save(
            b, mode, lossless=True
        ) if mode == "WEBP" else PILImage.fromarray(a).save(b, mode)
        return b.getvalue()

    return enc


def _pil_r(data):
    return np.asarray(PILImage.open(io.BytesIO(data)))


def _imageio_w(extension):
    return lambda array: iio.imwrite("<bytes>", array, extension=extension)


def _imageio_r(extension):
    return lambda data: iio.imread(data, extension=extension)


def _openexr_w(array):
    fd, path = tempfile.mkstemp(suffix=".exr")
    os.close(fd)
    try:
        channels = {
            channel: np.ascontiguousarray(array[:, :, index]) for index, channel in enumerate("RGB")
        }
        with OpenEXR.File(
            {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage},
            channels,
        ) as output:
            output.write(path)
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _openexr_r(data):
    fd, path = tempfile.mkstemp(suffix=".exr")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        with OpenEXR.File(path) as source:
            return {
                key: np.asarray(value.pixels) for key, value in source.parts[0].channels.items()
            }
    finally:
        os.remove(path)


def _gsply_ply_w(payload):
    fd, path = tempfile.mkstemp(suffix=".ply")
    os.close(fd)
    try:
        gsply.plywrite(
            path,
            payload["means"],
            scales=payload["scales"],
            quats=payload["quats"],
            opacities=payload["opacities"],
            sh0=payload["sh0"],
        )
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _gsply_ply_r(data):
    fd, path = tempfile.mkstemp(suffix=".ply")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        return gsply.plyread(path)
    finally:
        os.remove(path)


def _gsply_spz_w(payload):
    fd, path = tempfile.mkstemp(suffix=".spz")
    os.close(fd)
    try:
        cloud = gsply.GSData.from_arrays(**payload, format="ply")
        gsply.write_spz(path, cloud, version=3)
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _gsply_spz_r(data):
    fd, path = tempfile.mkstemp(suffix=".spz")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        return gsply.read_spz(path)
    finally:
        os.remove(path)


def _laspy_w(payload):
    hdr = laspy.LasHeader(version="1.2", point_format=0)
    hdr.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(hdr)
    las.x, las.y, las.z = payload[:, 0], payload[:, 1], payload[:, 2]
    b = io.BytesIO()
    las.write(b)
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


def _np_w(a):
    b = io.BytesIO()
    np.save(b, a)
    return b.getvalue()


def _np_r(d):
    return np.load(io.BytesIO(d))


def _save_npz_oracle(arrays):
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    return buffer.getvalue()


def _load_npz_oracle(data):
    with np.load(io.BytesIO(data)) as archive:
        return {name: np.array(archive[name], copy=True) for name in archive.files}


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


def _dmb_oracle_write(values):
    values = np.asarray(values, dtype=np.float32)
    height, width = values.shape
    return (
        struct.pack("<4i", 1, height, width, 1)
        + values.astype("<f4", copy=False).tobytes()
    )


def _dmb_oracle_read(data):
    image_type, height, width, channels = struct.unpack_from("<4i", data)
    if image_type != 1 or channels != 1:
        raise ValueError("unsupported DMB header")
    expected = 16 + height * width * 4
    if height < 1 or width < 1 or len(data) != expected:
        raise ValueError("invalid DMB payload")
    return np.frombuffer(data, dtype="<f4", offset=16).reshape(height, width)


def _bal_oracle_write(payload):
    cameras = payload["cameras"]
    points = payload["points"]
    camera_indices = payload["camera_indices"]
    point_indices = payload["point_indices"]
    observations = payload["observations"]
    lines = [
        f"{len(cameras)} {len(points)} {len(observations)}",
    ]
    lines.extend(
        f"{int(camera)} {int(point)} {xy[0]:.17g} {xy[1]:.17g}"
        for camera, point, xy in zip(
            camera_indices,
            point_indices,
            observations,
            strict=True,
        )
    )
    lines.extend(f"{value:.17g}" for value in cameras.flat)
    lines.extend(f"{value:.17g}" for value in points.flat)
    return ("\n".join(lines) + "\n").encode()


def _bal_oracle_read(data):
    values = np.fromstring(data.decode("ascii"), sep=" ")
    if len(values) < 3:
        raise ValueError("truncated BAL header")
    cameras, points, observations = (
        int(values[0]),
        int(values[1]),
        int(values[2]),
    )
    expected = 3 + observations * 4 + cameras * 9 + points * 3
    if min(cameras, points, observations) < 0 or len(values) != expected:
        raise ValueError("invalid BAL token count")
    cursor = 3
    observed = values[cursor : cursor + observations * 4].reshape(
        observations, 4
    )
    cursor += observations * 4
    camera_values = values[cursor : cursor + cameras * 9].reshape(
        cameras, 9
    )
    cursor += cameras * 9
    point_values = values[cursor:].reshape(points, 3)
    return {
        "observations": observed,
        "cameras": camera_values,
        "points": point_values,
    }


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


def _bal_payload_nbytes(payload):
    return sum(value.nbytes for value in payload.values())


_COLMAP_PAIR_MULTIPLIER = 2_147_483_647


def _colmap_db_fixture(scale):
    image_count = 64
    feature_count = max(1, int(1024 * scale))
    match_count = min(feature_count, max(1, int(256 * scale)))
    descriptor_columns = 128
    camera = _core.camera(
        1,
        1,
        1920,
        1080,
        np.array([1200.0, 1200.0, 960.0, 540.0], np.float64),
    )
    keypoints = np.empty((feature_count, 4), np.float32)
    indices = np.arange(feature_count, dtype=np.float32)
    keypoints[:, 0] = np.remainder(indices * 17.0, 1920.0)
    keypoints[:, 1] = np.remainder(indices * 29.0, 1080.0)
    keypoints[:, 2] = 1.0 + np.remainder(indices, 8.0) * 0.125
    keypoints[:, 3] = np.remainder(indices * 0.01, 2.0 * np.pi)
    descriptor_template = np.arange(
        feature_count * descriptor_columns, dtype=np.uint32
    ).reshape(feature_count, descriptor_columns)
    features = [
        _core.feature_set(
            keypoints,
            np.asarray(
                descriptor_template + image_id * 31,
                dtype=np.uint8,
            ),
            image_id=image_id,
            image_name=f"images/frame_{image_id:06d}.jpg",
            camera_id=1,
            image_size=(1920, 1080),
            extractor_type=0,
        )
        for image_id in range(1, image_count + 1)
    ]
    image_pairs = np.column_stack(
        (
            np.arange(1, image_count, dtype=np.uint32),
            np.arange(2, image_count + 1, dtype=np.uint32),
        )
    )
    pair_count = len(image_pairs)
    one_pair = np.column_stack(
        (
            np.arange(match_count, dtype=np.uint32),
            np.arange(match_count, dtype=np.uint32),
        )
    )
    matches = np.tile(one_pair, (pair_count, 1))
    match_offsets = np.arange(
        0, (pair_count + 1) * match_count, match_count, dtype=np.uint64
    )
    verified_count = max(1, match_count // 2)
    verified_matches = np.tile(one_pair[:verified_count], (pair_count, 1))
    verified_offsets = np.arange(
        0,
        (pair_count + 1) * verified_count,
        verified_count,
        dtype=np.uint64,
    )
    identity = np.tile(np.eye(3, dtype=np.float64), (pair_count, 1, 1))
    qvecs = np.zeros((pair_count, 4), np.float64)
    qvecs[:, 0] = 1.0
    tvecs = np.zeros((pair_count, 3), np.float64)
    tvecs[:, 0] = np.arange(pair_count, dtype=np.float64) * 0.01
    present = np.ones(pair_count, np.uint8)
    graph = _core.match_graph(
        image_pairs,
        match_offsets,
        matches,
        verified_offsets,
        verified_matches,
        configs=np.full(pair_count, 2, np.int32),
        fundamental_matrices=identity,
        fundamental_present=present,
        essential_matrices=identity,
        essential_present=present,
        homographies=identity,
        homography_present=present,
        qvecs=qvecs,
        tvecs=tvecs,
        pose_present=present,
        match_present=present,
        geometry_present=present,
    )
    return _core.colmap_database(
        [camera],
        features,
        graph,
        prior_focal_length=np.array([1], np.uint8),
    )


def _colmap_db_payload_nbytes(value):
    total = sum(np.asarray(camera.params).nbytes for camera in value.cameras)
    total += np.asarray(value.prior_focal_length).nbytes
    for index in range(value.num_images):
        feature = value.feature_at(index)
        total += np.asarray(feature.keypoints).nbytes
        if feature.descriptors is not None:
            total += np.asarray(feature.descriptors).nbytes
        if feature.scores is not None:
            total += np.asarray(feature.scores).nbytes
    graph = value.match_graph
    for name in (
        "image_pairs",
        "match_offsets",
        "matches",
        "verified_offsets",
        "verified_matches",
        "configs",
        "fundamental_matrices",
        "essential_matrices",
        "homographies",
        "qvecs",
        "tvecs",
    ):
        total += np.asarray(getattr(graph, name)).nbytes
    return total


def _colmap_blob(value):
    return memoryview(np.asarray(value)).cast("B")


def _sqlite_reference_write_colmap_db(value, path):
    destination = Path(path)
    destination.unlink(missing_ok=True)
    connection = sqlite3.connect(destination)
    try:
        connection.executescript(
            """
            CREATE TABLE cameras(
              camera_id INTEGER PRIMARY KEY NOT NULL,
              model INTEGER NOT NULL,
              width INTEGER NOT NULL,
              height INTEGER NOT NULL,
              params BLOB,
              prior_focal_length INTEGER NOT NULL);
            CREATE TABLE images(
              image_id INTEGER PRIMARY KEY NOT NULL,
              name TEXT NOT NULL UNIQUE,
              camera_id INTEGER NOT NULL,
              time_id INTEGER);
            CREATE TABLE keypoints(
              image_id INTEGER PRIMARY KEY NOT NULL,
              rows INTEGER NOT NULL,
              cols INTEGER NOT NULL,
              data BLOB);
            CREATE TABLE descriptors(
              image_id INTEGER PRIMARY KEY NOT NULL,
              type INTEGER NOT NULL,
              rows INTEGER NOT NULL,
              cols INTEGER NOT NULL,
              data BLOB);
            CREATE TABLE matches(
              pair_id INTEGER PRIMARY KEY NOT NULL,
              rows INTEGER NOT NULL,
              cols INTEGER NOT NULL,
              data BLOB);
            CREATE TABLE two_view_geometries(
              pair_id INTEGER PRIMARY KEY NOT NULL,
              rows INTEGER NOT NULL,
              cols INTEGER NOT NULL,
              data BLOB,
              config INTEGER NOT NULL,
              F BLOB,
              E BLOB,
              H BLOB,
              qvec BLOB,
              tvec BLOB);
            """
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "INSERT INTO cameras VALUES(?,?,?,?,?,?)",
            (
                (
                    camera.id,
                    camera.model_id,
                    camera.width,
                    camera.height,
                    _colmap_blob(camera.params),
                    int(value.prior_focal_length[index]),
                )
                for index, camera in enumerate(value.cameras)
            ),
        )
        image_rows = []
        keypoint_rows = []
        descriptor_rows = []
        for index in range(value.num_images):
            feature = value.feature_at(index)
            image_rows.append(
                (
                    feature.image_id,
                    feature.image_name,
                    feature.camera_id,
                    feature.time_id,
                )
            )
            if feature.keypoints_present:
                keypoint_rows.append(
                    (
                        feature.image_id,
                        feature.num_keypoints,
                        feature.keypoint_columns,
                        _colmap_blob(feature.keypoints),
                    )
                )
            if feature.descriptors is not None:
                descriptor_rows.append(
                    (
                        feature.image_id,
                        feature.extractor_type,
                        feature.num_keypoints,
                        feature.descriptor_dim,
                        _colmap_blob(feature.descriptors),
                    )
                )
        connection.executemany(
            "INSERT INTO images VALUES(?,?,?,?)", image_rows
        )
        connection.executemany(
            "INSERT INTO keypoints VALUES(?,?,?,?)", keypoint_rows
        )
        connection.executemany(
            "INSERT INTO descriptors VALUES(?,?,?,?,?)", descriptor_rows
        )
        graph = value.match_graph
        match_rows = []
        geometry_rows = []
        for pair in range(graph.num_pairs):
            pair_id = int(graph.pair_ids[pair])
            match_begin = int(graph.match_offsets[pair])
            match_end = int(graph.match_offsets[pair + 1])
            if graph.match_present[pair]:
                match_rows.append(
                    (
                        pair_id,
                        match_end - match_begin,
                        2,
                        _colmap_blob(
                            graph.matches[match_begin:match_end]
                        ),
                    )
                )
            verified_begin = int(graph.verified_offsets[pair])
            verified_end = int(graph.verified_offsets[pair + 1])
            if graph.geometry_present[pair]:
                geometry_rows.append(
                    (
                        pair_id,
                        verified_end - verified_begin,
                        2,
                        _colmap_blob(
                            graph.verified_matches[
                                verified_begin:verified_end
                            ]
                        ),
                        int(graph.configs[pair]),
                        _colmap_blob(graph.fundamental_matrices[pair]),
                        _colmap_blob(graph.essential_matrices[pair]),
                        _colmap_blob(graph.homographies[pair]),
                        _colmap_blob(graph.qvecs[pair]),
                        _colmap_blob(graph.tvecs[pair]),
                    )
                )
        connection.executemany(
            "INSERT INTO matches VALUES(?,?,?,?)", match_rows
        )
        connection.executemany(
            "INSERT INTO two_view_geometries VALUES(?,?,?,?,?,?,?,?,?,?)",
            geometry_rows,
        )
        connection.execute(f"PRAGMA user_version={value.user_version}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _sqlite_reference_query(path, statements):
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        return tuple(
            connection.execute(statement, parameters).fetchall()
            for statement, parameters in statements
        )
    finally:
        connection.close()


def _sqlite_reference_read_colmap_db(path):
    return _sqlite_reference_query(
        path,
        (
            ("SELECT * FROM cameras ORDER BY camera_id", ()),
            ("SELECT * FROM images ORDER BY image_id", ()),
            ("SELECT * FROM keypoints ORDER BY image_id", ()),
            ("SELECT * FROM descriptors ORDER BY image_id", ()),
            ("SELECT * FROM matches ORDER BY pair_id", ()),
            (
                "SELECT * FROM two_view_geometries ORDER BY pair_id",
                (),
            ),
        ),
    )


def _sqlite_reference_inspect_colmap_db(path):
    return _sqlite_reference_query(
        path,
        (
            ("SELECT count(*) FROM cameras", ()),
            ("SELECT count(*) FROM images", ()),
            ("SELECT coalesce(sum(rows),0) FROM keypoints", ()),
            ("SELECT coalesce(sum(rows),0) FROM descriptors", ()),
            ("SELECT coalesce(sum(rows),0) FROM matches", ()),
            (
                "SELECT coalesce(sum(rows),0) "
                "FROM two_view_geometries",
                (),
            ),
            (
                "SELECT image_id,name,camera_id,time_id "
                "FROM images ORDER BY image_id",
                (),
            ),
            (
                "SELECT image_id,rows,cols "
                "FROM keypoints ORDER BY image_id",
                (),
            ),
            (
                "SELECT image_id,type,rows,cols "
                "FROM descriptors ORDER BY image_id",
                (),
            ),
        ),
    )


def _sqlite_reference_read_colmap_db_image(path, image_id):
    return _sqlite_reference_query(
        path,
        (
            (
                "SELECT * FROM images WHERE image_id=?",
                (image_id,),
            ),
            (
                "SELECT * FROM keypoints WHERE image_id=?",
                (image_id,),
            ),
            (
                "SELECT * FROM descriptors WHERE image_id=?",
                (image_id,),
            ),
        ),
    )


def _sqlite_reference_read_colmap_db_pair(path, image_id1, image_id2):
    low, high = sorted((image_id1, image_id2))
    pair_id = low * _COLMAP_PAIR_MULTIPLIER + high
    return _sqlite_reference_query(
        path,
        (
            ("SELECT * FROM matches WHERE pair_id=?", (pair_id,)),
            (
                "SELECT * FROM two_view_geometries WHERE pair_id=?",
                (pair_id,),
            ),
        ),
    )


def _assert_colmap_db_equal(actual, expected):
    assert actual.user_version == expected.user_version
    assert len(actual.cameras) == len(expected.cameras)
    for left, right in zip(actual.cameras, expected.cameras, strict=True):
        assert (
            left.id,
            left.model_id,
            left.width,
            left.height,
        ) == (
            right.id,
            right.model_id,
            right.width,
            right.height,
        )
        np.testing.assert_array_equal(left.params, right.params)
    np.testing.assert_array_equal(
        actual.prior_focal_length, expected.prior_focal_length
    )
    assert actual.num_images == expected.num_images
    for index in range(actual.num_images):
        left = actual.feature_at(index)
        right = expected.feature_at(index)
        assert (
            left.image_id,
            left.image_name,
            left.camera_id,
            tuple(left.image_size),
            left.time_id,
            left.extractor_type,
            left.keypoints_present,
        ) == (
            right.image_id,
            right.image_name,
            right.camera_id,
            tuple(right.image_size),
            right.time_id,
            right.extractor_type,
            right.keypoints_present,
        )
        np.testing.assert_array_equal(left.keypoints, right.keypoints)
        if left.descriptors is None or right.descriptors is None:
            assert left.descriptors is right.descriptors
        else:
            np.testing.assert_array_equal(
                left.descriptors, right.descriptors
            )
    left_graph = actual.match_graph
    right_graph = expected.match_graph
    for name in (
        "pair_ids",
        "image_pairs",
        "match_present",
        "geometry_present",
        "match_offsets",
        "matches",
        "verified_offsets",
        "verified_matches",
        "configs",
        "F_present",
        "E_present",
        "H_present",
        "fundamental_matrices",
        "essential_matrices",
        "homographies",
        "pose_present",
        "qvecs",
        "tvecs",
    ):
        np.testing.assert_array_equal(
            getattr(left_graph, name), getattr(right_graph, name)
        )


def _evict_file_cache(path):
    """Best-effort cold-cache hint (effective where POSIX_FADV_DONTNEED exists)."""
    if not hasattr(os, "posix_fadvise") or not hasattr(os, "POSIX_FADV_DONTNEED"):
        return False
    with open(path, "rb") as stream:
        os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    return True


def _specs(scale, pose_bundle=None):
    side = max(1, int(1024 * scale**0.5))
    points = max(1, int(1_000_000 * scale))
    gaussians = max(1, int(200_000 * scale))
    tensor_side = max(1, int(512 * scale**0.5))
    reconstruction, transforms, tum, kitti = pose_bundle or _poses_and_reconstruction(scale)
    flow = np.random.default_rng(4).standard_normal((side, side, 2)).astype(np.float32)
    pfm = np.random.default_rng(5).standard_normal((side, side)).astype(np.float32)
    npz_arrays = {
        "a": np.random.default_rng(6)
        .standard_normal((tensor_side, tensor_side))
        .astype(np.float32),
        "b": np.arange(max(1, tensor_side), dtype=np.int32),
    }
    tensors = _core.tensor_dict(npz_arrays)
    return [
        Spec(
            "png",
            lambda: _img_u8(side, side),
            _core.write_png,
            _core.read_png,
            (_pil_w("PNG") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "jpeg",
            lambda: _img_u8(side, side),
            lambda im: _core.write_jpeg(im, 95),
            _core.read_jpeg,
            (_pil_w("JPEG") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "bmp",
            lambda: _img_u8(side, side),
            _core.write_bmp,
            _core.read_bmp,
            (_pil_w("BMP") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "tga",
            lambda: _img_u8(side, side),
            _core.write_tga,
            _core.read_tga,
            (_pil_w("TGA") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "webp",
            lambda: _img_u8(side, side),
            lambda im: _core.write_webp(im, True),
            _core.read_webp,
            (_pil_w("WEBP") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "hdr",
            lambda: _img_f32(side, side),
            _core.write_hdr,
            _core.read_hdr,
            (_imageio_w(".hdr") if iio else None),
            (_imageio_r(".hdr") if iio else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "exr",
            lambda: _img_f32(side, side),
            _core.write_exr,
            _core.read_exr,
            (_openexr_w if OpenEXR else None),
            (_openexr_r if OpenEXR else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "netpbm",
            lambda: _img_u8(side, side),
            lambda im: _core.write_netpbm(im, False),
            _core.read_netpbm,
            (_imageio_w(".ppm") if iio else (_pil_w("PPM") if PILImage else None)),
            (_imageio_r(".ppm") if iio else (_pil_r if PILImage else None)),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "xyz",
            lambda: _pc(points, False),
            _core.write_xyz,
            _core.read_xyz,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "pts",
            lambda: _pc(points, False),
            _core.write_pts,
            _core.read_pts,
            _pts_oracle_write,
            _pts_oracle_read,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "ply",
            lambda: _pc_ply(points),
            _core.write_ply,
            _core.read_ply,
            (_open3d_ply_w if o3d else None),
            (_open3d_ply_r if o3d else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "pcd",
            lambda: _pc_ply(points),
            _core.write_pcd,
            _core.read_pcd,
            (_open3d_pcd_w if o3d else None),
            (_open3d_pcd_r if o3d else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "las",
            lambda: _pc(points, True),
            lambda pc: _core.write_las(pc, 0.001),
            _core.read_las,
            (_laspy_w if laspy else None),
            (_laspy_r if laspy else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "gaussian_ply",
            lambda: _gauss(gaussians),
            _core.write_gaussian_ply,
            _core.read_gaussian_ply,
            (_gsply_ply_w if gsply else None),
            (_gsply_ply_r if gsply else None),
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "compressed_ply",
            lambda: _gauss(gaussians),
            _core.write_compressed_ply,
            _core.read_compressed_ply,
            None,
            None,
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "sog",
            lambda: _gauss(gaussians),
            _core.write_sog,
            _core.read_sog,
            None,
            None,
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "spz",
            lambda: _gauss(gaussians),
            _core.write_spz,
            _core.read_spz,
            (_gsply_spz_w if gsply else None),
            (_gsply_spz_r if gsply else None),
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "splat",
            lambda: _gauss(gaussians),
            _core.write_splat,
            _core.read_splat,
            None,
            None,
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "npy",
            lambda: (lambda a: (a, a))(
                np.ascontiguousarray(
                    np.random.default_rng(0).random((tensor_side, tensor_side, 8), dtype=np.float32)
                )
            ),
            _core.write_npy,
            _core.read_npy,
            _np_w,
            _np_r,
            lambda rec, p: rec.nbytes,
        ),
        Spec(
            "pfm",
            lambda: (pfm, pfm),
            _core.write_pfm,
            _core.read_pfm,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "flo",
            lambda: (flow, flow),
            _core.write_flo,
            _core.read_flo,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "dmb",
            lambda: _depth_map(side, side),
            _core.write_dmb,
            _core.read_dmb,
            _dmb_oracle_write,
            _dmb_oracle_read,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "npz",
            lambda: (tensors, npz_arrays),
            _core.write_npz,
            _core.read_npz,
            lambda arrays: _save_npz_oracle(arrays),
            _load_npz_oracle,
            lambda rec, p: sum(array.nbytes for array in p.values()),
        ),
        Spec(
            "safetensors",
            lambda: (tensors, npz_arrays),
            _core.write_safetensors,
            _core.read_safetensors,
            (
                (lambda arrays: safetensors_save(arrays))
                if safetensors_save
                else None
            ),
            safetensors_load,
            lambda rec, p: sum(array.nbytes for array in p.values()),
        ),
        Spec(
            "transforms_json",
            lambda: (transforms, transforms),
            _core.write_transforms_json,
            _core.read_transforms_json,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "tum",
            lambda: (tum, tum),
            _core.write_tum,
            _core.read_tum,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "kitti",
            lambda: (kitti, kitti),
            _core.write_kitti,
            _core.read_kitti,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "euroc_state",
            lambda: _euroc_fixture(scale),
            _core.write_euroc_state,
            _core.read_euroc_state,
            _euroc_oracle_write,
            _euroc_oracle_read,
            lambda rec, payload: _euroc_payload_nbytes(payload),
        ),
        Spec(
            "opencv_yaml",
            _single_calibration,
            _core.write_opencv_yaml,
            _core.read_opencv_yaml,
            _yaml_oracle_write if yaml else None,
            _yaml_oracle_read if yaml else None,
            lambda rec, payload: _record_nbytes(rec),
        ),
        Spec(
            "opencv_xml",
            _single_calibration,
            _core.write_opencv_xml,
            _core.read_opencv_xml,
            _xml_oracle_write,
            _xml_oracle_read,
            lambda rec, payload: _record_nbytes(rec),
        ),
        Spec(
            "ros_camera_info",
            partial(_single_calibration, ros=True),
            _core.write_ros_camera_info,
            _core.read_ros_camera_info,
            _yaml_oracle_write if yaml else None,
            _yaml_oracle_read if yaml else None,
            lambda rec, payload: _record_nbytes(rec),
        ),
        Spec(
            "kalibr",
            partial(_kalibr_calibration, scale),
            _core.write_kalibr,
            _core.read_kalibr,
            _yaml_oracle_write if yaml else None,
            _yaml_oracle_read if yaml else None,
            lambda rec, payload: _record_nbytes(rec),
        ),
        Spec(
            "g2o",
            partial(_g2o_fixture, scale),
            _core.write_g2o,
            _core.read_g2o,
            _g2o_oracle_write,
            _g2o_oracle_read,
            lambda rec, payload: _g2o_payload_nbytes(payload),
        ),
        Spec(
            "bundler",
            lambda: (reconstruction, reconstruction),
            _core.write_bundler,
            _core.read_bundler,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "bal",
            lambda: _bal_fixture(scale),
            _core.write_bal,
            _core.read_bal,
            _bal_oracle_write,
            _bal_oracle_read,
            lambda rec, p: _bal_payload_nbytes(p),
        ),
        Spec(
            "nvm",
            lambda: (reconstruction, reconstruction),
            _core.write_nvm,
            _core.read_nvm,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "openmvg",
            lambda: (reconstruction, reconstruction),
            _core.write_openmvg,
            _core.read_openmvg,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
    ]


@dataclass
class DirectorySpec:
    id: str
    w: Callable
    r: Callable


def _directory_specs():
    return [
        DirectorySpec("colmap_sparse", _core.write_colmap_sparse, _core.read_colmap_sparse),
        DirectorySpec("colmap_sparse_txt", _core.write_colmap_txt, _core.read_colmap_txt),
    ]


def _directory_size(path):
    return sum(entry.stat().st_size for entry in Path(path).iterdir() if entry.is_file())


def _partial_request(codec_id, info, full_record=None):
    if codec_id in {"pfm", "netpbm", "webp", "flo", "dmb"}:
        height, width = info.shape[:2]
        out_height = max(1, height // 8)
        out_width = max(1, width // 8)
        row_start = (height - out_height) // 2
        col_start = (width - out_width) // 2
        return {
            "window": (
                row_start,
                row_start + out_height,
                col_start,
                col_start + out_width,
            )
        }
    if codec_id in {
        "xyz",
        "pts",
        "ply",
        "pcd",
        "las",
        "gaussian_ply",
        "compressed_ply",
        "sog",
        "splat",
    }:
        selected = max(1, info.count // 16)
        start = (info.count - selected) // 2
        return {"points": (start, start + selected)}
    if codec_id in {"colmap_sparse", "colmap_sparse_txt"}:
        image_ids = np.asarray(full_record.image_ids)
        return {"image_id": int(image_ids[len(image_ids) // 2])}
    if codec_id == "safetensors":
        return {"tensors": ("b",)}
    if codec_id == "euroc_state":
        selected = max(1, info.count // 16)
        start = (info.count - selected) // 2
        return {"states": (start, start + selected)}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="multiply logical payload sizes (e.g. 32 for generated large fixtures)",
    )
    ap.add_argument(
        "--cold-cache",
        action="store_true",
        help="request POSIX_FADV_DONTNEED before each path read when supported",
    )
    ap.add_argument(
        "--only",
        action="append",
        metavar="FORMAT",
        help=(
            "benchmark only this registered format id; repeat for multiple "
            "formats (the default remains the complete codec sweep)"
        ),
    )
    ap.add_argument(
        "--skip-oracles",
        action="store_true",
        help="skip independent-library timing while retaining SceneIO verification",
    )
    ap.add_argument(
        "--large-safetensors-mib",
        type=int,
        default=0,
        help=(
            "run only the generated safetensors full/inspect/single-tensor/"
            "stream-write fixture at this MiB size (use 128 or 1024)"
        ),
    )
    ap.add_argument(
        "--require-o4-gains",
        action="store_true",
        help=(
            "fail unless stable high-signal O4 controls improve and mmap/sink "
            "traced allocations remain bounded"
        ),
    )
    ap.add_argument(
        "--require-o5-inspect-gains",
        action="store_true",
        help="fail unless stable metadata-only inspections beat full reads",
    )
    ap.add_argument(
        "--require-o5-partial-gains",
        action="store_true",
        help="fail unless stable partial reads beat full record materialization",
    )
    ap.add_argument("--json", type=Path, help="write machine-readable results to this path")
    args = ap.parse_args()
    if args.scale <= 0:
        ap.error("--scale must be positive")
    if args.large_safetensors_mib < 0:
        ap.error("--large-safetensors-mib must be non-negative")
    if args.only and (
        args.require_o4_gains
        or args.require_o5_inspect_gains
        or args.require_o5_partial_gains
    ):
        ap.error("--only cannot be combined with complete-sweep regression guards")
    if args.only and args.large_safetensors_mib:
        ap.error("--only cannot be combined with --large-safetensors-mib")
    with tempfile.TemporaryDirectory(prefix="sceneio_bench_") as tmp:
        if args.large_safetensors_mib:
            failures, results = _run_large_safetensors(args, tmp)
        else:
            failures, results = _run_benchmark(args, tmp)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise RuntimeError("benchmark failures: " + ", ".join(failures))


def _run_large_safetensors(args, tmp):
    size_bytes = args.large_safetensors_mib * 1024 * 1024
    count = max(1, size_bytes // np.dtype(np.float32).itemsize)
    large = np.arange(count, dtype=np.float32)
    small = np.arange(1024, dtype=np.int16)
    arrays = {"large": large, "small": small}
    record = _core.tensor_dict(arrays, {"fixture": "generated"})
    path = Path(tmp) / "large.safetensors"
    oracle_path = Path(tmp) / "large-oracle.safetensors"

    def write_sceneio():
        sceneio.write(record, path, format="safetensors")

    write_time, write_peak = _measure(write_sceneio, args.runs)
    write_rss = _measure_rss(write_sceneio)

    def full_read():
        if args.cold_cache:
            _evict_file_cache(path)
        return sceneio.read(path, format="safetensors")

    def inspect_read():
        if args.cold_cache:
            _evict_file_cache(path)
        return sceneio.inspect(path, format="safetensors")

    def selected_read():
        if args.cold_cache:
            _evict_file_cache(path)
        return sceneio.read_partial(
            path, format="safetensors", tensors=("small",)
        )

    full_time, full_peak = _measure(full_read, args.runs)
    full_rss = _measure_rss(full_read)
    inspect_time, inspect_peak = _measure(inspect_read, args.runs)
    inspect_rss = _measure_rss(inspect_read)
    selected_time, selected_peak = _measure(selected_read, args.runs)
    selected_rss = _measure_rss(selected_read)

    oracle_metrics = {}
    if (
        safetensors_save_file
        and safetensors_load_file
        and safetensors_open
        and not args.skip_oracles
    ):
        def oracle_full():
            if args.cold_cache:
                _evict_file_cache(path)
            return safetensors_load_file(path)

        oracle_write_time, oracle_write_peak = _measure(
            lambda: safetensors_save_file(arrays, oracle_path), args.runs
        )
        oracle_write_rss = _measure_rss(
            lambda: safetensors_save_file(arrays, oracle_path)
        )
        oracle_full_time, oracle_full_peak = _measure(
            oracle_full, args.runs
        )
        oracle_full_rss = _measure_rss(oracle_full)

        def oracle_inspect():
            if args.cold_cache:
                _evict_file_cache(path)
            with safetensors_open(path, framework="np") as handle:
                return tuple(
                    (
                        name,
                        tuple(handle.get_slice(name).get_shape()),
                        handle.get_slice(name).get_dtype(),
                    )
                    for name in tuple(handle.keys())
                )

        def oracle_selected():
            if args.cold_cache:
                _evict_file_cache(path)
            with safetensors_open(path, framework="np") as handle:
                return handle.get_tensor("small")

        oracle_inspect_time, oracle_inspect_peak = _measure(
            oracle_inspect, args.runs
        )
        oracle_inspect_rss = _measure_rss(oracle_inspect)
        oracle_selected_time, oracle_selected_peak = _measure(
            oracle_selected, args.runs
        )
        oracle_selected_rss = _measure_rss(oracle_selected)
        oracle_metrics = {
            "oracle_write_ms": oracle_write_time * 1000,
            "oracle_write_peak_mb": oracle_write_peak / 1e6,
            "oracle_write_rss_mb": oracle_write_rss / 1e6,
            "oracle_full_ms": oracle_full_time * 1000,
            "oracle_full_peak_mb": oracle_full_peak / 1e6,
            "oracle_full_rss_mb": oracle_full_rss / 1e6,
            "oracle_inspect_ms": oracle_inspect_time * 1000,
            "oracle_inspect_peak_mb": oracle_inspect_peak / 1e6,
            "oracle_inspect_rss_mb": oracle_inspect_rss / 1e6,
            "oracle_selected_ms": oracle_selected_time * 1000,
            "oracle_selected_peak_mb": oracle_selected_peak / 1e6,
            "oracle_selected_rss_mb": oracle_selected_rss / 1e6,
        }

    decoded = full_read()
    selected = selected_read()
    np.testing.assert_array_equal(decoded["small"], small)
    np.testing.assert_array_equal(selected["small"], small)
    inspected = {array.name: array for array in inspect_read().arrays}
    assert inspected["large"].shape == large.shape
    del decoded, selected
    gc.collect()

    result = {
        "codec": "safetensors-large",
        "fixture_mib": args.large_safetensors_mib,
        "file_mb": path.stat().st_size / 1e6,
        "write_ms": write_time * 1000,
        "write_peak_mb": write_peak / 1e6,
        "write_rss_mb": write_rss / 1e6,
        "full_ms": full_time * 1000,
        "full_peak_mb": full_peak / 1e6,
        "full_rss_mb": full_rss / 1e6,
        "inspect_ms": inspect_time * 1000,
        "inspect_peak_mb": inspect_peak / 1e6,
        "inspect_rss_mb": inspect_rss / 1e6,
        "selected_ms": selected_time * 1000,
        "selected_peak_mb": selected_peak / 1e6,
        "selected_rss_mb": selected_rss / 1e6,
        **oracle_metrics,
    }
    print(json.dumps(result, indent=2))
    return [], [result]


def _benchmark_colmap_db(args, tmp):
    value = _colmap_db_fixture(args.scale)
    native_path = Path(tmp) / "colmap-database.db"
    oracle_path = Path(tmp) / "colmap-database-oracle.db"
    payload_bytes = _colmap_db_payload_nbytes(value)
    payload_mb = payload_bytes / 1e6
    selected_image_id = value.feature_at(value.num_images // 2).image_id
    selected_pair = tuple(
        int(item)
        for item in value.match_graph.image_pairs[
            value.match_graph.num_pairs // 2
        ]
    )

    def native_write():
        return sceneio.write(value, native_path, format="colmap_db")

    def oracle_write():
        return _sqlite_reference_write_colmap_db(value, oracle_path)

    native_write_time, native_write_peak = _measure(
        native_write, args.runs
    )
    native_write_rss = _measure_rss(native_write)
    oracle_write_time = oracle_write_peak = oracle_write_rss = None
    if not args.skip_oracles:
        oracle_write_time, oracle_write_peak = _measure(
            oracle_write, args.runs
        )
        oracle_write_rss = _measure_rss(oracle_write)

    def native_full_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.read(native_path, format="colmap_db")

    def oracle_full_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return _sqlite_reference_read_colmap_db(native_path)

    def native_inspect():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.inspect(native_path, format="colmap_db")

    def oracle_inspect():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return _sqlite_reference_inspect_colmap_db(native_path)

    def native_image_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.read_partial(
            native_path,
            format="colmap_db",
            image_id=selected_image_id,
        )

    def oracle_image_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return _sqlite_reference_read_colmap_db_image(
            native_path, selected_image_id
        )

    def native_pair_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.read_partial(
            native_path,
            format="colmap_db",
            pair=selected_pair,
        )

    def oracle_pair_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return _sqlite_reference_read_colmap_db_pair(
            native_path, *selected_pair
        )

    native_full_time, native_full_peak = _measure(
        native_full_read, args.runs
    )
    native_full_rss = _measure_rss(native_full_read)
    inspect_time, inspect_peak = _measure(native_inspect, args.runs)
    inspect_rss = _measure_rss(native_inspect)
    image_time, image_peak = _measure(native_image_read, args.runs)
    image_rss = _measure_rss(native_image_read)
    pair_time, pair_peak = _measure(native_pair_read, args.runs)
    pair_rss = _measure_rss(native_pair_read)

    oracle_metrics = {}
    oracle_full_time = None
    if not args.skip_oracles:
        oracle_full_time, oracle_full_peak = _measure(
            oracle_full_read, args.runs
        )
        oracle_full_rss = _measure_rss(oracle_full_read)
        oracle_inspect_time, oracle_inspect_peak = _measure(
            oracle_inspect, args.runs
        )
        oracle_inspect_rss = _measure_rss(oracle_inspect)
        oracle_image_time, oracle_image_peak = _measure(
            oracle_image_read, args.runs
        )
        oracle_image_rss = _measure_rss(oracle_image_read)
        oracle_pair_time, oracle_pair_peak = _measure(
            oracle_pair_read, args.runs
        )
        oracle_pair_rss = _measure_rss(oracle_pair_read)
        oracle_metrics = {
            "oracle_write_mbps": payload_mb / oracle_write_time,
            "oracle_write_peak_mb": oracle_write_peak / 1e6,
            "oracle_write_rss_mb": oracle_write_rss / 1e6,
            "oracle_read_mbps": payload_mb / oracle_full_time,
            "oracle_read_peak_mb": oracle_full_peak / 1e6,
            "oracle_read_rss_mb": oracle_full_rss / 1e6,
            "oracle_inspect_ms": oracle_inspect_time * 1000,
            "oracle_inspect_peak_mb": oracle_inspect_peak / 1e6,
            "oracle_inspect_rss_mb": oracle_inspect_rss / 1e6,
            "oracle_image_ms": oracle_image_time * 1000,
            "oracle_image_peak_mb": oracle_image_peak / 1e6,
            "oracle_image_rss_mb": oracle_image_rss / 1e6,
            "oracle_pair_ms": oracle_pair_time * 1000,
            "oracle_pair_peak_mb": oracle_pair_peak / 1e6,
            "oracle_pair_rss_mb": oracle_pair_rss / 1e6,
        }

    decoded = native_full_read()
    _assert_colmap_db_equal(decoded, value)
    if not args.skip_oracles:
        oracle_decoded = sceneio.read(oracle_path, format="colmap_db")
        _assert_colmap_db_equal(oracle_decoded, value)
        assert len(oracle_full_read()[1]) == value.num_images
    selected_feature = native_image_read()
    expected_feature = decoded.feature(selected_image_id)
    assert (
        selected_feature.image_id,
        selected_feature.image_name,
        selected_feature.camera_id,
    ) == (
        expected_feature.image_id,
        expected_feature.image_name,
        expected_feature.camera_id,
    )
    np.testing.assert_array_equal(
        selected_feature.keypoints, expected_feature.keypoints
    )
    np.testing.assert_array_equal(
        selected_feature.descriptors, expected_feature.descriptors
    )
    selected_graph = native_pair_read()
    expected_pair_index = value.match_graph.num_pairs // 2
    match_begin = int(value.match_graph.match_offsets[expected_pair_index])
    match_end = int(value.match_graph.match_offsets[expected_pair_index + 1])
    np.testing.assert_array_equal(
        selected_graph.matches,
        value.match_graph.matches[match_begin:match_end],
    )
    inspected = native_inspect()
    assert inspected.count == value.num_images
    assert inspected.metadata["num_matches"] == value.match_graph.num_matches

    file_mb = native_path.stat().st_size / 1e6
    result = {
        "codec": "colmap_db",
        "payload_mb": payload_mb,
        "file_mb": file_mb,
        "write_mbps": payload_mb / native_write_time,
        "path_write_mbps": payload_mb / native_write_time,
        "read_mbps": payload_mb / native_full_time,
        "path_read_mbps": payload_mb / native_full_time,
        "mmap_peak_mb": native_full_peak / 1e6,
        "mmap_rss_mb": native_full_rss / 1e6,
        "inspect_ms": inspect_time * 1000,
        "inspect_peak_mb": inspect_peak / 1e6,
        "inspect_rss_mb": inspect_rss / 1e6,
        "partial_ms": image_time * 1000,
        "partial_peak_mb": image_peak / 1e6,
        "partial_rss_mb": image_rss / 1e6,
        "partial_image_ms": image_time * 1000,
        "partial_image_peak_mb": image_peak / 1e6,
        "partial_image_rss_mb": image_rss / 1e6,
        "partial_pair_ms": pair_time * 1000,
        "partial_pair_peak_mb": pair_peak / 1e6,
        "partial_pair_rss_mb": pair_rss / 1e6,
        "sink_write_peak_mb": native_write_peak / 1e6,
        "sink_write_rss_mb": native_write_rss / 1e6,
        **oracle_metrics,
    }
    write_row = (
        "colmap_db",
        payload_mb,
        file_mb,
        None,
        payload_mb / native_write_time,
        None,
        native_write_peak / 1e6,
        None,
        native_write_rss / 1e6,
    )
    inspect_row = (
        "colmap_db",
        native_full_time,
        inspect_time,
        native_full_peak / 1e6,
        inspect_peak / 1e6,
        native_full_rss / 1e6,
        inspect_rss / 1e6,
    )
    partial_rows = [
        (
            "colmap_db:image",
            native_full_time,
            image_time,
            native_full_peak / 1e6,
            image_peak / 1e6,
            native_full_rss / 1e6,
            image_rss / 1e6,
        ),
        (
            "colmap_db:pair",
            native_full_time,
            pair_time,
            native_full_peak / 1e6,
            pair_peak / 1e6,
            native_full_rss / 1e6,
            pair_rss / 1e6,
        ),
    ]
    display = (
        payload_mb,
        file_mb,
        payload_mb / native_write_time,
        payload_mb / native_full_time,
        (
            payload_mb / oracle_write_time
            if oracle_write_time is not None
            else None
        ),
        (
            payload_mb / oracle_full_time
            if oracle_full_time is not None
            else None
        ),
        native_full_peak / 1e6,
        native_full_rss / 1e6,
    )
    return result, write_row, inspect_row, partial_rows, display


def _run_benchmark(args, tmp):
    pose_bundle = _poses_and_reconstruction(args.scale)
    reconstruction = pose_bundle[0]
    specs = _specs(args.scale, pose_bundle)
    directory_specs = _directory_specs()
    include_colmap_db = True
    if args.only:
        requested = set(args.only)
        known = {spec.id for spec in specs} | {
            spec.id for spec in directory_specs
        } | {"colmap_db"}
        unknown = requested - known
        if unknown:
            raise ValueError(
                "unknown --only format: " + ", ".join(sorted(unknown))
            )
        specs = [spec for spec in specs if spec.id in requested]
        directory_specs = [
            spec for spec in directory_specs if spec.id in requested
        ]
        include_colmap_db = "colmap_db" in requested
    failures = []
    results = []
    write_rows = []
    o4_rows = []
    inspect_rows = []
    partial_rows = []

    hdr = (
        f"{'codec':<14}{'payloadMB':>10}{'fileMB':>9}{'sioW':>9}{'sioR':>9}"
        f"{'pathR':>9}{'oraW':>9}{'oraR':>9}{'bPeakMB':>9}{'mPeakMB':>9}"
        f"{'bRSSMB':>9}{'mRSSMB':>9}{'sio/ora':>9}"
    )
    print(hdr)
    print("-" * len(hdr))
    for s in specs:
        try:
            rec, payload = s.make()
            enc = bytes(s.w(rec))
            pbytes = s.nbytes(rec, payload)
            pmb = pbytes / 1e6
            fmb = len(enc) / 1e6

            wt, _ = _measure(lambda: s.w(rec), args.runs)
            rt, _ = _measure(lambda: s.r(enc), args.runs)
            sioW, sioR = pmb / wt, pmb / rt
            o4_metrics = {}
            typed_adapter_metrics = None
            ply_variant_metrics = None
            pcd_variant_metrics = None

            if s.id == "ply":
                ply_variant_metrics = {
                    "binary_little_endian": {
                        "file_mb": fmb,
                        "write_mbps": sioW,
                        "read_mbps": sioR,
                    }
                }
                reference_fields = {
                    name: np.asarray(getattr(rec, name))
                    for name in ("positions", "colors", "normals")
                }
                for encoding in ("ascii", "binary_big_endian"):
                    writer = partial(_core.write_ply, rec, encoding)
                    variant_write_time, _ = _measure(writer, args.runs)
                    variant = bytes(writer())
                    reader = partial(_core.read_ply, variant)
                    variant_read_time, _ = _measure(reader, args.runs)
                    decoded = reader()
                    if not all(
                        np.array_equal(
                            np.asarray(getattr(decoded, name)), expected
                        )
                        for name, expected in reference_fields.items()
                    ):
                        raise AssertionError(
                            f"PLY {encoding} variant changed decoded values"
                        )
                    ply_variant_metrics[encoding] = {
                        "file_mb": len(variant) / 1e6,
                        "write_mbps": pmb / variant_write_time,
                        "read_mbps": pmb / variant_read_time,
                    }

            if s.id == "pcd":
                pcd_variant_metrics = {
                    "binary": {
                        "file_mb": fmb,
                        "write_mbps": sioW,
                        "read_mbps": sioR,
                    }
                }
                reference_fields = {
                    name: np.asarray(getattr(rec, name))
                    for name in ("positions", "colors", "normals")
                }
                for encoding in ("ascii", "binary_compressed"):
                    writer = partial(_core.write_pcd, rec, encoding)
                    variant_write_time, _ = _measure(writer, args.runs)
                    variant = bytes(writer())
                    reader = partial(_core.read_pcd, variant)
                    variant_read_time, _ = _measure(reader, args.runs)
                    decoded = reader()
                    if not all(
                        np.array_equal(
                            np.asarray(getattr(decoded, name)), expected
                        )
                        for name, expected in reference_fields.items()
                    ):
                        raise AssertionError(
                            f"PCD {encoding} variant changed decoded values"
                        )
                    pcd_variant_metrics[encoding] = {
                        "file_mb": len(variant) / 1e6,
                        "write_mbps": pmb / variant_write_time,
                        "read_mbps": pmb / variant_read_time,
                    }

            # O4 controls retain a deterministic one-lane/worker-off reference
            # beside the optimized defaults. WebP separately measures the old
            # forced effort=100 setting and a palette input on which libwebp
            # actually schedules its lossless side worker.
            if s.id == "webp":
                old_webp = partial(
                    _core.write_webp, rec, True, 90.0, False, 100, 4
                )
                old_time, _ = _measure(old_webp, args.runs)
                original = np.asarray(rec.pixels)
                if not np.array_equal(
                    np.asarray(_core.read_webp(old_webp()).pixels), original
                ):
                    raise AssertionError("lower WebP effort changed decoded pixels")

                palette_rec, palette_values = _img_webp_palette(
                    max(32, int(1024 * args.scale**0.5)),
                    max(32, int(1024 * args.scale**0.5)),
                )
                worker_off = partial(
                    _core.write_webp,
                    palette_rec,
                    True,
                    90.0,
                    False,
                )
                worker_on = partial(_core.write_webp, palette_rec)
                worker_off_time, _ = _measure(worker_off, args.runs)
                launch_count = _core._webp_worker_launch_count()
                worker_on_time, _ = _measure(worker_on, args.runs)
                if _core._webp_worker_launch_count() <= launch_count:
                    raise AssertionError("WebP side-worker path was not reached")
                worker_off_bytes = bytes(worker_off())
                worker_on_bytes = bytes(worker_on())
                if worker_off_bytes != worker_on_bytes:
                    raise AssertionError("WebP worker output differs")
                if not np.array_equal(
                    np.asarray(_core.read_webp(worker_on_bytes).pixels),
                    palette_values,
                ):
                    raise AssertionError("WebP worker decode differs")
                palette_mb = palette_values.nbytes / 1e6
                o4_rows.extend(
                    [
                        (
                            "webp",
                            "balanced-config",
                            pmb / old_time,
                            sioW,
                            "pixels",
                        ),
                        (
                            "webp",
                            "workers-palette",
                            palette_mb / worker_off_time,
                            palette_mb / worker_on_time,
                            "bytes",
                        ),
                    ]
                )
                o4_metrics.update(
                    {
                        "write_old_mbps": pmb / old_time,
                        "write_worker_off_mbps": palette_mb
                        / worker_off_time,
                        "write_optimized_mbps": sioW,
                        "write_worker_on_mbps": palette_mb / worker_on_time,
                    }
                )
            elif s.id in {"xyz", "exr", "las"}:
                if s.id == "xyz":
                    one_lane_write = partial(
                        _core.write_xyz, rec, _lanes=1
                    )
                    label = "format"
                elif s.id == "exr":
                    one_lane_write = partial(
                        _core.write_exr, rec, _lanes=1
                    )
                    label = "planar"
                else:
                    one_lane_write = partial(
                        _core.write_las, rec, _lanes=1
                    )
                    label = "points"
                one_write_time, _ = _measure(one_lane_write, args.runs)
                if bytes(one_lane_write()) != enc:
                    raise AssertionError(f"{s.id} lane output differs")
                o4_rows.append(
                    (s.id, f"{label}-write", pmb / one_write_time, sioW, "bytes")
                )
                o4_metrics.update(
                    {
                        "write_one_lane_mbps": pmb / one_write_time,
                        "write_optimized_mbps": sioW,
                    }
                )
                if s.id in {"exr", "las"}:
                    if s.id == "exr":
                        one_lane_read = partial(
                            _core.read_exr, enc, _lanes=1
                        )
                    else:
                        one_lane_read = partial(
                            _core.read_las, enc, _lanes=1
                        )
                    one_read_time, _ = _measure(one_lane_read, args.runs)
                    one_decoded = one_lane_read()
                    optimized_decoded = s.r(enc)
                    if s.id == "exr":
                        same_values = np.array_equal(
                            np.asarray(one_decoded.pixels),
                            np.asarray(optimized_decoded.pixels),
                        )
                        same_metadata = (
                            one_decoded.height,
                            one_decoded.width,
                            one_decoded.channels,
                            one_decoded.dtype,
                            one_decoded.color_space,
                            one_decoded.alpha_mode,
                            one_decoded.maxval,
                        ) == (
                            optimized_decoded.height,
                            optimized_decoded.width,
                            optimized_decoded.channels,
                            optimized_decoded.dtype,
                            optimized_decoded.color_space,
                            optimized_decoded.alpha_mode,
                            optimized_decoded.maxval,
                        )
                    else:
                        same_values = all(
                            np.array_equal(
                                np.asarray(getattr(one_decoded, field)),
                                np.asarray(getattr(optimized_decoded, field)),
                            )
                            for field in (
                                "positions",
                                "colors16",
                                "intensities",
                            )
                        ) and np.array_equal(
                            one_decoded.origin, optimized_decoded.origin
                        )
                        same_metadata = (
                            one_decoded.num_points,
                            one_decoded.coordinate_frame,
                            one_decoded.scale_to_meters,
                            one_decoded.intensity_range,
                        ) == (
                            optimized_decoded.num_points,
                            optimized_decoded.coordinate_frame,
                            optimized_decoded.scale_to_meters,
                            optimized_decoded.intensity_range,
                        )
                    if not same_values or not same_metadata:
                        raise AssertionError(
                            f"{s.id} lane decode differs"
                        )
                    o4_rows.append(
                        (
                            s.id,
                            f"{label}-read",
                            pmb / one_read_time,
                            sioR,
                            "values",
                        )
                    )
                    o4_metrics.update(
                        {
                            "read_one_lane_mbps": pmb / one_read_time,
                            "read_optimized_mbps": sioR,
                        }
                    )

            if s.id == "png":
                u16_side = max(1, int(1024 * args.scale**0.5))
                u16 = (
                    (
                        np.arange(u16_side * u16_side * 3, dtype=np.uint32)
                        * 40503
                    )
                    & 0xFFFF
                ).astype(np.uint16).reshape(u16_side, u16_side, 3)
                u16_image = _core.image(u16, color_space="srgb")
                png16_one_write = partial(
                    _core.write_png, u16_image, _lanes=1
                )
                png16_fast_write = partial(_core.write_png, u16_image)
                png16_one_time, _ = _measure(png16_one_write, args.runs)
                png16_fast_time, _ = _measure(png16_fast_write, args.runs)
                png16_data = bytes(png16_fast_write())
                if bytes(png16_one_write()) != png16_data:
                    raise AssertionError("PNG16 lane output differs")
                png16_one_read = partial(
                    _core.read_png, png16_data, _lanes=1
                )
                png16_fast_read = partial(_core.read_png, png16_data)
                png16_one_read_time, _ = _measure(png16_one_read, args.runs)
                png16_fast_read_time, _ = _measure(
                    png16_fast_read, args.runs
                )
                png16_one_values = np.asarray(png16_one_read().pixels)
                png16_fast_values = np.asarray(png16_fast_read().pixels)
                if not (
                    np.array_equal(png16_one_values, png16_fast_values)
                    and np.array_equal(png16_fast_values, u16)
                ):
                    raise AssertionError("PNG16 lane decode differs")
                png16_mb = u16.nbytes / 1e6
                o4_rows.extend(
                    [
                        (
                            "png16",
                            "swap-write",
                            png16_mb / png16_one_time,
                            png16_mb / png16_fast_time,
                            "bytes",
                        ),
                        (
                            "png16",
                            "swap-read",
                            png16_mb / png16_one_read_time,
                            png16_mb / png16_fast_read_time,
                            "values",
                        ),
                    ]
                )
                o4_metrics.update(
                    {
                        "png16_write_one_lane_mbps": png16_mb
                        / png16_one_time,
                        "png16_write_optimized_mbps": png16_mb
                        / png16_fast_time,
                        "png16_read_one_lane_mbps": png16_mb
                        / png16_one_read_time,
                        "png16_read_optimized_mbps": png16_mb
                        / png16_fast_read_time,
                    }
                )

            # Compare the legacy bytes+Path.write_bytes route with the public O3
            # file sink, then compare whole-file bytes + copy decode with the
            # public mmap path. NPY/FLO also expose the O2 mapped output view.
            fp = os.path.join(tmp, f"{s.id}.bin")

            def _bytes_write(fp=fp, w=s.w, value=rec):
                return Path(fp).write_bytes(w(value))

            def _sink_write(fp=fp, codec_id=s.id, value=rec):
                return sceneio.write(value, fp, format=codec_id)

            bytes_write_time, bytes_write_peak = _measure(
                _bytes_write, args.runs
            )
            bytes_write_rss = _measure_rss(_bytes_write)
            sink_time, sink_write_peak = _measure(_sink_write, args.runs)
            sink_write_rss = _measure_rss(_sink_write)
            with open(fp, "rb") as fh:
                if fh.read() != enc:
                    raise AssertionError("file sink output differs from buffer encoder")
            path_write = pmb / sink_time
            bytes_path_write = pmb / bytes_write_time
            write_rows.append(
                (
                    s.id,
                    pmb,
                    fmb,
                    bytes_path_write,
                    path_write,
                    bytes_write_peak / 1e6,
                    sink_write_peak / 1e6,
                    bytes_write_rss / 1e6,
                    sink_write_rss / 1e6,
                )
            )

            def _bytes_read(fp=fp, r=s.r):
                with open(fp, "rb") as fh:
                    return r(fh.read())

            def _mmap_read(fp=fp, codec_id=s.id):
                if args.cold_cache:
                    _evict_file_cache(fp)
                return sceneio.read(fp, format=codec_id)

            _, bytes_peak = _measure(_bytes_read, args.runs)
            path_time, mmap_peak = _measure(_mmap_read, args.runs)
            bytes_rss = _measure_rss(_bytes_read)
            mmap_rss = _measure_rss(_mmap_read)
            path_read = pmb / path_time

            def _inspect(fp=fp, codec_id=s.id):
                if args.cold_cache:
                    _evict_file_cache(fp)
                return sceneio.inspect(fp, format=codec_id)

            inspect_time, inspect_peak = _measure(_inspect, args.runs)
            inspect_rss = _measure_rss(_inspect)
            inspect_rows.append(
                (
                    s.id,
                    path_time,
                    inspect_time,
                    mmap_peak / 1e6,
                    inspect_peak / 1e6,
                    mmap_rss / 1e6,
                    inspect_rss / 1e6,
                )
            )
            if s.id == "flo":
                typed_record = _core.flow_field(rec)
                typed_path = os.path.join(tmp, "flo-typed.bin")

                def _typed_read(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_flow(fp, format="flo")

                def _typed_write(
                    destination=typed_path,
                    value=typed_record,
                ):
                    return sceneio.write_flow(
                        value, destination, format="flo"
                    )

                def _typed_inspect(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.inspect_flow(fp, format="flo")

                typed_read_time, typed_read_peak = _measure(
                    _typed_read, args.runs
                )
                typed_read_rss = _measure_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_rss(_typed_inspect)
                typed_decoded = _typed_read()
                if not np.array_equal(
                    np.asarray(typed_decoded.vectors), rec, equal_nan=True
                ):
                    raise AssertionError("typed FLO values differ")
                if Path(typed_path).read_bytes() != enc:
                    raise AssertionError("typed FLO sink bytes differ")
                typed_info = _typed_inspect()
                if (
                    typed_info.shape != rec.shape
                    or typed_info.metadata.get("component_order") != "uv"
                ):
                    raise AssertionError("typed FLO inspection differs")
                typed_adapter_metrics = {
                    "format": "flo",
                    "read_mbps": pmb / typed_read_time,
                    "read_peak_mb": typed_read_peak / 1e6,
                    "read_rss_mb": typed_read_rss / 1e6,
                    "write_mbps": pmb / typed_write_time,
                    "write_peak_mb": typed_write_peak / 1e6,
                    "write_rss_mb": typed_write_rss / 1e6,
                    "inspect_ms": typed_inspect_time * 1000,
                    "inspect_peak_mb": typed_inspect_peak / 1e6,
                    "inspect_rss_mb": typed_inspect_rss / 1e6,
                }
            elif s.id == "pfm":
                depth_encoding = sceneio.DepthEncoding(
                    "meters", 1.0, "none"
                )
                typed_record = _core.depth_map(rec)
                typed_path = os.path.join(tmp, "pfm-typed.bin")
                height, width = rec.shape
                typed_window = (
                    height // 4,
                    max(height // 4 + 1, 3 * height // 4),
                    width // 4,
                    max(width // 4 + 1, 3 * width // 4),
                )

                def _typed_read(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_depth(
                        fp,
                        format="pfm",
                        encoding=depth_encoding,
                    )

                def _typed_write(
                    destination=typed_path,
                    value=typed_record,
                ):
                    return sceneio.write_depth(
                        value,
                        destination,
                        format="pfm",
                        encoding=depth_encoding,
                    )

                def _typed_inspect(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.inspect_depth(
                        fp,
                        format="pfm",
                        encoding=depth_encoding,
                    )

                def _typed_partial(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_depth(
                        fp,
                        format="pfm",
                        encoding=depth_encoding,
                        window=typed_window,
                    )

                typed_read_time, typed_read_peak = _measure(
                    _typed_read, args.runs
                )
                typed_read_rss = _measure_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_rss(_typed_inspect)
                typed_partial_time, typed_partial_peak = _measure(
                    _typed_partial, args.runs
                )
                typed_partial_rss = _measure_rss(_typed_partial)
                typed_decoded = _typed_read()
                if not np.array_equal(
                    np.asarray(typed_decoded.depth), rec, equal_nan=True
                ):
                    raise AssertionError("typed PFM values differ")
                if Path(typed_path).read_bytes() != enc:
                    raise AssertionError("typed PFM sink bytes differ")
                typed_info = _typed_inspect()
                if (
                    typed_info.shape != rec.shape
                    or typed_info.metadata.get("scale_to_meters") != 1.0
                ):
                    raise AssertionError("typed PFM inspection differs")
                row_start, row_stop, col_start, col_stop = typed_window
                if not np.array_equal(
                    np.asarray(_typed_partial().depth),
                    rec[row_start:row_stop, col_start:col_stop],
                    equal_nan=True,
                ):
                    raise AssertionError("typed PFM window differs")
                typed_adapter_metrics = {
                    "format": "pfm",
                    "read_mbps": pmb / typed_read_time,
                    "read_peak_mb": typed_read_peak / 1e6,
                    "read_rss_mb": typed_read_rss / 1e6,
                    "write_mbps": pmb / typed_write_time,
                    "write_peak_mb": typed_write_peak / 1e6,
                    "write_rss_mb": typed_write_rss / 1e6,
                    "inspect_ms": typed_inspect_time * 1000,
                    "inspect_peak_mb": typed_inspect_peak / 1e6,
                    "inspect_rss_mb": typed_inspect_rss / 1e6,
                    "partial_ms": typed_partial_time * 1000,
                    "partial_peak_mb": typed_partial_peak / 1e6,
                    "partial_rss_mb": typed_partial_rss / 1e6,
                }
            elif s.id == "exr":
                typed_side = max(1, int(1024 * args.scale**0.5))
                depth_values = np.random.default_rng(20260724).standard_normal(
                    (typed_side, typed_side),
                    dtype=np.float32,
                )
                depth_encoding = sceneio.DepthEncoding(
                    "meters", 1.0, "nonfinite", "Z"
                )
                typed_record = _core.depth_map(
                    depth_values,
                    invalid_policy="nonfinite",
                )
                typed_source = os.path.join(tmp, "exr-depth-source.bin")
                typed_path = os.path.join(tmp, "exr-depth-output.bin")
                typed_bytes = bytes(
                    _core.write_exr_depth(
                        typed_record,
                        depth_encoding.unit,
                        depth_encoding.scale_to_meters,
                        depth_encoding.invalid_policy,
                        depth_encoding.channel_name,
                    )
                )
                Path(typed_source).write_bytes(typed_bytes)
                typed_mb = depth_values.nbytes / 1e6

                def _typed_read(fp=typed_source):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_depth(
                        fp,
                        format="exr",
                        encoding=depth_encoding,
                    )

                def _typed_write(
                    destination=typed_path,
                    value=typed_record,
                ):
                    return sceneio.write_depth(
                        value,
                        destination,
                        format="exr",
                        encoding=depth_encoding,
                    )

                def _typed_inspect(fp=typed_source):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.inspect_depth(
                        fp,
                        format="exr",
                        encoding=depth_encoding,
                    )

                typed_read_time, typed_read_peak = _measure(
                    _typed_read, args.runs
                )
                typed_read_rss = _measure_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_rss(_typed_inspect)
                if not np.array_equal(
                    np.asarray(_typed_read().depth).view(np.uint32),
                    depth_values.view(np.uint32),
                ):
                    raise AssertionError("typed EXR depth values differ")
                if Path(typed_path).read_bytes() != typed_bytes:
                    raise AssertionError("typed EXR depth sink bytes differ")
                typed_info = _typed_inspect()
                if (
                    typed_info.shape != depth_values.shape
                    or typed_info.dtype != "float32"
                    or typed_info.metadata.get("stored_dtype") != "float32"
                    or typed_info.metadata.get("channel_name") != "Z"
                ):
                    raise AssertionError("typed EXR depth inspection differs")
                typed_adapter_metrics = {
                    "format": "exr",
                    "read_mbps": typed_mb / typed_read_time,
                    "read_peak_mb": typed_read_peak / 1e6,
                    "read_rss_mb": typed_read_rss / 1e6,
                    "write_mbps": typed_mb / typed_write_time,
                    "write_peak_mb": typed_write_peak / 1e6,
                    "write_rss_mb": typed_write_rss / 1e6,
                    "inspect_ms": typed_inspect_time * 1000,
                    "inspect_peak_mb": typed_inspect_peak / 1e6,
                    "inspect_rss_mb": typed_inspect_rss / 1e6,
                }
            elif s.id == "png":
                typed_side = max(1, int(1024 * args.scale**0.5))
                stored_depth = (
                    (
                        np.arange(
                            typed_side * typed_side,
                            dtype=np.uint32,
                        )
                        * 40503
                    )
                    & 0xFFFF
                ).astype(np.uint16).reshape(typed_side, typed_side)
                depth_values = stored_depth.astype(np.float32)
                depth_encoding = sceneio.DepthEncoding(
                    "millimeters", 0.001, "zero"
                )
                typed_record = _core.depth_map(
                    depth_values,
                    unit="millimeters",
                    invalid_policy="zero",
                )
                typed_source = os.path.join(tmp, "png-depth-source.bin")
                typed_path = os.path.join(tmp, "png-depth-output.bin")
                typed_bytes = bytes(
                    _core.write_png(
                        _core.image(stored_depth, color_space="gray")
                    )
                )
                Path(typed_source).write_bytes(typed_bytes)
                typed_mb = depth_values.nbytes / 1e6

                def _typed_read(fp=typed_source):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_depth(
                        fp,
                        format="png",
                        encoding=depth_encoding,
                    )

                def _typed_write(
                    destination=typed_path,
                    value=typed_record,
                ):
                    return sceneio.write_depth(
                        value,
                        destination,
                        format="png",
                        encoding=depth_encoding,
                    )

                def _typed_inspect(fp=typed_source):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.inspect_depth(
                        fp,
                        format="png",
                        encoding=depth_encoding,
                    )

                typed_read_time, typed_read_peak = _measure(
                    _typed_read, args.runs
                )
                typed_read_rss = _measure_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_rss(_typed_inspect)
                if not np.array_equal(
                    np.asarray(_typed_read().depth),
                    depth_values,
                ):
                    raise AssertionError("typed PNG depth values differ")
                if Path(typed_path).read_bytes() != typed_bytes:
                    raise AssertionError("typed PNG depth sink bytes differ")
                typed_info = _typed_inspect()
                if (
                    typed_info.shape != depth_values.shape
                    or typed_info.dtype != "float32"
                    or typed_info.metadata.get("stored_dtype") != "uint16"
                ):
                    raise AssertionError("typed PNG depth inspection differs")
                typed_adapter_metrics = {
                    "format": "png",
                    "read_mbps": typed_mb / typed_read_time,
                    "read_peak_mb": typed_read_peak / 1e6,
                    "read_rss_mb": typed_read_rss / 1e6,
                    "write_mbps": typed_mb / typed_write_time,
                    "write_peak_mb": typed_write_peak / 1e6,
                    "write_rss_mb": typed_write_rss / 1e6,
                    "inspect_ms": typed_inspect_time * 1000,
                    "inspect_peak_mb": typed_inspect_peak / 1e6,
                    "inspect_rss_mb": typed_inspect_rss / 1e6,
                }
            partial_request = _partial_request(s.id, _inspect())
            partial_metrics = None
            if partial_request is not None:

                def _partial_read(
                    fp=fp,
                    codec_id=s.id,
                    request=partial_request,
                ):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_partial(
                        fp, format=codec_id, **request
                    )

                partial_time, partial_peak = _measure(
                    _partial_read, args.runs
                )
                partial_rss = _measure_rss(_partial_read)
                partial_metrics = (
                    partial_time,
                    partial_peak / 1e6,
                    partial_rss / 1e6,
                )
                partial_rows.append(
                    (
                        s.id,
                        path_time,
                        partial_time,
                        mmap_peak / 1e6,
                        partial_peak / 1e6,
                        mmap_rss / 1e6,
                        partial_rss / 1e6,
                    )
                )

            oraW = oraR = None
            if s.ow and payload is not None and not args.skip_oracles:
                ob = _try(lambda: bytes(s.ow(payload)))
                if ob is not None:
                    m = _try(lambda: _measure(lambda: s.ow(payload), args.runs))
                    oraW = pmb / m[0] if m else None
                    mr = _try(lambda: _measure(lambda: s.orr(ob), args.runs))
                    oraR = pmb / mr[0] if mr else None

            ratio = (sioR / oraR) if oraR else None
            results.append(
                {
                    "codec": s.id,
                    "payload_mb": pmb,
                    "file_mb": fmb,
                    "write_mbps": sioW,
                    "bytes_path_write_mbps": bytes_path_write,
                    "path_write_mbps": path_write,
                    "read_mbps": sioR,
                    "path_read_mbps": path_read,
                    "oracle_write_mbps": oraW,
                    "oracle_read_mbps": oraR,
                    "bytes_peak_mb": bytes_peak / 1e6,
                    "mmap_peak_mb": mmap_peak / 1e6,
                    "bytes_rss_mb": bytes_rss / 1e6,
                    "mmap_rss_mb": mmap_rss / 1e6,
                    "inspect_ms": inspect_time * 1000,
                    "inspect_peak_mb": inspect_peak / 1e6,
                    "inspect_rss_mb": inspect_rss / 1e6,
                    "partial_ms": (
                        partial_metrics[0] * 1000
                        if partial_metrics is not None
                        else None
                    ),
                    "partial_peak_mb": (
                        partial_metrics[1]
                        if partial_metrics is not None
                        else None
                    ),
                    "partial_rss_mb": (
                        partial_metrics[2]
                        if partial_metrics is not None
                        else None
                    ),
                    "bytes_write_peak_mb": bytes_write_peak / 1e6,
                    "sink_write_peak_mb": sink_write_peak / 1e6,
                    "bytes_write_rss_mb": bytes_write_rss / 1e6,
                    "sink_write_rss_mb": sink_write_rss / 1e6,
                    "o4": o4_metrics or None,
                    "typed_adapter": typed_adapter_metrics,
                    "ply_variants": ply_variant_metrics,
                    "pcd_variants": pcd_variant_metrics,
                }
            )
            print(
                f"{s.id:<14}{pmb:>10.1f}{fmb:>9.1f}{sioW:>9.0f}{sioR:>9.0f}"
                f"{path_read:>9.0f}{(oraW if oraW else 0):>9.0f}"
                f"{(oraR if oraR else 0):>9.0f}"
                f"{bytes_peak / 1e6:>9.1f}{mmap_peak / 1e6:>9.1f}"
                f"{bytes_rss / 1e6:>9.1f}{mmap_rss / 1e6:>9.1f}"
                f"{(ratio if ratio else 0):>9.2f}"
            )
            if typed_adapter_metrics is not None:
                print(
                    f"  {typed_adapter_metrics['format']} typed adapter:"
                    f" read={typed_adapter_metrics['read_mbps']:.0f} MB/s"
                    f" write={typed_adapter_metrics['write_mbps']:.0f} MB/s"
                    f" inspect={typed_adapter_metrics['inspect_ms']:.3f} ms"
                    f" traced read/write="
                    f"{typed_adapter_metrics['read_peak_mb']:.3f}/"
                    f"{typed_adapter_metrics['write_peak_mb']:.3f} MB"
                )
            if ply_variant_metrics is not None:
                summary = ", ".join(
                    f"{encoding}: W={metrics['write_mbps']:.0f}/"
                    f"R={metrics['read_mbps']:.0f} MB/s"
                    for encoding, metrics in ply_variant_metrics.items()
                )
                print(f"  PLY encodings: {summary}")
            if pcd_variant_metrics is not None:
                summary = ", ".join(
                    f"{encoding}: W={metrics['write_mbps']:.0f}/"
                    f"R={metrics['read_mbps']:.0f} MB/s"
                    for encoding, metrics in pcd_variant_metrics.items()
                )
                print(f"  PCD encodings: {summary}")
        except Exception as e:
            failures.append(s.id)
            results.append({"codec": s.id, "error": f"{type(e).__name__}: {e}"})
            print(f"{s.id:<14} ERROR: {type(e).__name__}: {e}")

    if include_colmap_db:
        try:
            (
                database_result,
                database_write_row,
                database_inspect_row,
                database_partial_rows,
                database_display,
            ) = _benchmark_colmap_db(args, tmp)
            results.append(database_result)
            write_rows.append(database_write_row)
            inspect_rows.append(database_inspect_row)
            partial_rows.extend(database_partial_rows)
            (
                payload_mb,
                file_mb,
                write_mbps,
                read_mbps,
                oracle_write_mbps,
                oracle_read_mbps,
                read_peak_mb,
                read_rss_mb,
            ) = database_display
            print(
                f"{'colmap_db':<14}{payload_mb:>10.1f}{file_mb:>9.1f}"
                f"{write_mbps:>9.0f}{read_mbps:>9.0f}"
                f"{read_mbps:>9.0f}"
                f"{(oracle_write_mbps or 0):>9.0f}"
                f"{(oracle_read_mbps or 0):>9.0f}"
                f"{'-':>9}{read_peak_mb:>9.1f}"
                f"{'-':>9}{read_rss_mb:>9.1f}{'-':>9}"
            )
        except Exception as e:
            failures.append("colmap_db")
            results.append(
                {
                    "codec": "colmap_db",
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            print(f"{'colmap_db':<14} ERROR: {type(e).__name__}: {e}")

    for spec in directory_specs:
        try:
            path = Path(tmp) / spec.id
            path.mkdir()
            spec.w(reconstruction, str(path))
            file_bytes = _directory_size(path)
            payload_bytes = _record_nbytes(reconstruction)
            pmb = payload_bytes / 1e6
            fmb = file_bytes / 1e6
            write_time, write_peak = _measure(
                lambda: spec.w(reconstruction, str(path)), args.runs
            )
            write_rss = _measure_rss(
                lambda: spec.w(reconstruction, str(path))
            )
            write_rows.append(
                (
                    spec.id,
                    pmb,
                    fmb,
                    None,
                    pmb / write_time,
                    None,
                    write_peak / 1e6,
                    None,
                    write_rss / 1e6,
                )
            )

            def _directory_read(path=path, codec_id=spec.id):
                if args.cold_cache:
                    for entry in path.iterdir():
                        if entry.is_file():
                            _evict_file_cache(entry)
                return sceneio.read(path, format=codec_id)

            core_read_time, _ = _measure(lambda: spec.r(str(path)), args.runs)
            path_read_time, read_peak = _measure(_directory_read, args.runs)
            read_rss = _measure_rss(_directory_read)

            def _directory_inspect(path=path, codec_id=spec.id):
                if args.cold_cache:
                    for entry in path.iterdir():
                        if entry.is_file():
                            _evict_file_cache(entry)
                return sceneio.inspect(path, format=codec_id)

            inspect_time, inspect_peak = _measure(
                _directory_inspect, args.runs
            )
            inspect_rss = _measure_rss(_directory_inspect)
            inspect_rows.append(
                (
                    spec.id,
                    path_read_time,
                    inspect_time,
                    read_peak / 1e6,
                    inspect_peak / 1e6,
                    read_rss / 1e6,
                    inspect_rss / 1e6,
                )
            )
            partial_request = _partial_request(
                spec.id, _directory_inspect(), reconstruction
            )

            def _directory_partial(
                path=path,
                codec_id=spec.id,
                request=partial_request,
            ):
                if args.cold_cache:
                    for entry in path.iterdir():
                        if entry.is_file():
                            _evict_file_cache(entry)
                return sceneio.read_partial(
                    path, format=codec_id, **request
                )

            partial_time, partial_peak = _measure(
                _directory_partial, args.runs
            )
            partial_rss = _measure_rss(_directory_partial)
            partial_rows.append(
                (
                    spec.id,
                    path_read_time,
                    partial_time,
                    read_peak / 1e6,
                    partial_peak / 1e6,
                    read_rss / 1e6,
                    partial_rss / 1e6,
                )
            )
            results.append(
                {
                    "codec": spec.id,
                    "payload_mb": pmb,
                    "file_mb": fmb,
                    "write_mbps": pmb / write_time,
                    "path_write_mbps": pmb / write_time,
                    "read_mbps": pmb / core_read_time,
                    "path_read_mbps": pmb / path_read_time,
                    "mmap_peak_mb": read_peak / 1e6,
                    "mmap_rss_mb": read_rss / 1e6,
                    "inspect_ms": inspect_time * 1000,
                    "inspect_peak_mb": inspect_peak / 1e6,
                    "inspect_rss_mb": inspect_rss / 1e6,
                    "partial_ms": partial_time * 1000,
                    "partial_peak_mb": partial_peak / 1e6,
                    "partial_rss_mb": partial_rss / 1e6,
                    "sink_write_peak_mb": write_peak / 1e6,
                    "sink_write_rss_mb": write_rss / 1e6,
                }
            )
            print(
                f"{spec.id:<14}{pmb:>10.1f}{fmb:>9.1f}{pmb / write_time:>9.0f}"
                f"{pmb / core_read_time:>9.0f}{pmb / path_read_time:>9.0f}"
                f"{'-':>9}{'-':>9}{'-':>9}{read_peak / 1e6:>9.1f}"
                f"{'-':>9}{read_rss / 1e6:>9.1f}{'-':>9}"
            )
        except Exception as e:
            failures.append(spec.id)
            results.append({"codec": spec.id, "error": f"{type(e).__name__}: {e}"})
            print(f"{spec.id:<14} ERROR: {type(e).__name__}: {e}")

    if not args.only:
        assert len(specs) + len(directory_specs) + int(include_colmap_db) == 40
    print("\nMB/s over raw payload; fileMB = encoded size (= the whole-file copy O1/O3 remove).")
    print("sioR = in-memory copy decode; pathR = public registry mmap read/view.")
    print("bPeakMB/mPeakMB = peak Python allocation for bytes/mmap reads (O1 delta).")
    print("bRSSMB/mRSSMB = sampled resident-set growth for bytes/mmap reads.")
    print("\nO3 write-path delta:")
    write_header = (
        f"{'codec':<18}{'payloadMB':>10}{'fileMB':>9}{'bytesW':>9}{'sinkW':>9}"
        f"{'bPeakMB':>9}{'sPeakMB':>9}{'bRSSMB':>9}{'sRSSMB':>9}"
    )
    print(write_header)
    print("-" * len(write_header))
    for row in write_rows:
        codec_id, pmb, fmb, bufw, sinkw, bpeak, speak, brss, srss = row
        print(
            f"{codec_id:<18}{pmb:>10.1f}{fmb:>9.1f}"
            f"{(f'{bufw:.0f}' if bufw is not None else '-'):>9}"
            f"{sinkw:>9.0f}"
            f"{(f'{bpeak:.1f}' if bpeak is not None else '-'):>9}"
            f"{speak:>9.1f}"
            f"{(f'{brss:.1f}' if brss is not None else '-'):>9}"
            f"{srss:>9.1f}"
        )
    print("bytesW/sinkW = legacy bytes+file/public file-sink write MB/s.")
    print("bPeakMB/sPeakMB = peak Python allocation for bytes/file-sink writes (O3 delta).")
    print("bRSSMB/sRSSMB = sampled resident-set growth for bytes/file-sink writes.")
    print("\nO4 one-lane/old-setting delta:")
    o4_header = (
        f"{'codec':<12}{'operation':<18}{'base MB/s':>12}"
        f"{'opt MB/s':>12}{'gain':>9}{'identity':>11}"
    )
    print(o4_header)
    print("-" * len(o4_header))
    for codec_id, operation, base, optimized, identity in o4_rows:
        print(
            f"{codec_id:<12}{operation:<18}{base:>12.0f}"
            f"{optimized:>12.0f}{optimized / base:>8.2f}x"
            f"{identity:>11}"
        )
    print(
        "Identity is encoded bytes where compression settings are unchanged; "
        "otherwise decoded values/pixels."
    )
    print("\nO5 metadata-only inspection delta:")
    inspect_header = (
        f"{'codec':<18}{'full ms':>11}{'inspect ms':>12}{'speedup':>10}"
        f"{'fullPeak':>11}{'inspPeak':>10}{'fullRSS':>10}{'inspRSS':>9}"
    )
    print(inspect_header)
    print("-" * len(inspect_header))
    for codec_id, full, inspected, full_peak, inspected_peak, full_rss, inspected_rss in (
        inspect_rows
    ):
        print(
            f"{codec_id:<18}{full * 1000:>11.3f}{inspected * 1000:>12.3f}"
            f"{full / inspected:>9.2f}x{full_peak:>11.1f}{inspected_peak:>10.1f}"
            f"{full_rss:>10.1f}{inspected_rss:>9.1f}"
        )
    print("Inspection reads headers/streamed metadata and constructs no compiled record arrays.")
    print("\nO5 partial-read delta:")
    partial_header = (
        f"{'codec':<18}{'full ms':>11}{'partial ms':>12}{'speedup':>10}"
        f"{'fullPeak':>11}{'partPeak':>10}{'fullRSS':>10}{'partRSS':>9}"
    )
    print(partial_header)
    print("-" * len(partial_header))
    for codec_id, full, partial_time, full_peak, part_peak, full_rss, part_rss in (
        partial_rows
    ):
        print(
            f"{codec_id:<18}{full * 1000:>11.3f}{partial_time * 1000:>12.3f}"
            f"{full / partial_time:>9.2f}x{full_peak:>11.1f}{part_peak:>10.1f}"
            f"{full_rss:>10.1f}{part_rss:>9.1f}"
        )
    print(
        "Partial reads return the normal record type while materializing only "
        "the selected pixel, point, tensor, COLMAP-image, or match-pair subset."
    )
    if args.require_o5_inspect_gains:
        stable = {"exr", "gaussian_ply", "las", "png", "spz"}
        by_codec = {
            codec_id: (
                full,
                inspected,
                inspected_peak,
                full_rss,
                inspected_rss,
            )
            for (
                codec_id,
                full,
                inspected,
                _,
                inspected_peak,
                full_rss,
                inspected_rss,
            ) in inspect_rows
        }
        missing = stable - by_codec.keys()
        if missing:
            raise RuntimeError(
                "missing O5 inspect guard rows: " + ", ".join(sorted(missing))
            )
        regressions = [
            codec_id
            for codec_id in sorted(stable)
            if by_codec[codec_id][1] >= by_codec[codec_id][0]
        ]
        if regressions:
            raise RuntimeError(
                "O5 inspection failed directional latency guard: "
                + ", ".join(regressions)
            )
        json_controls = {"transforms_json", "openmvg"}
        missing_json = json_controls - by_codec.keys()
        if missing_json:
            raise RuntimeError(
                "missing O5 JSON read-control rows: "
                + ", ".join(sorted(missing_json))
            )
        json_read_regressions = sorted(
            codec_id
            for codec_id in json_controls
            if by_codec[codec_id][0] > 3.0 * by_codec[codec_id][1]
        )
        if json_read_regressions:
            raise RuntimeError(
                "O5 full JSON read exceeded 3x its independent metadata "
                "parser control: "
                + ", ".join(json_read_regressions)
            )
        allocation_regressions = sorted(
            codec_id
            for codec_id, (_, _, inspected_peak, _, _) in by_codec.items()
            if inspected_peak >= 1.0
        )
        if allocation_regressions:
            raise RuntimeError(
                "O5 inspection exceeded 1 MB traced allocation: "
                + ", ".join(allocation_regressions)
            )
        rss_regressions = sorted(
            codec_id
            for codec_id, (_, _, _, full_rss, inspected_rss) in by_codec.items()
            if inspected_rss > max(8.0, full_rss + 4.0)
        )
        if rss_regressions:
            raise RuntimeError(
                "O5 inspection exceeded the sampled RSS guard: "
                + ", ".join(rss_regressions)
            )
        rss_gain_regressions = sorted(
            codec_id
            for codec_id in stable
            if by_codec[codec_id][3] >= 8.0
            and by_codec[codec_id][4]
            >= max(4.0, 0.5 * by_codec[codec_id][3])
        )
        if rss_gain_regressions:
            raise RuntimeError(
                "O5 inspection failed the directional RSS gain guard: "
                + ", ".join(rss_gain_regressions)
            )
    if args.require_o5_partial_gains:
        stable = {
            "pfm",
            "netpbm",
            "webp",
            "xyz",
            "las",
            "gaussian_ply",
            "splat",
            "colmap_sparse",
            "colmap_sparse_txt",
        }
        by_codec = {
            codec_id: (
                full,
                partial_time,
                part_peak,
                full_rss,
                part_rss,
            )
            for (
                codec_id,
                full,
                partial_time,
                _,
                part_peak,
                full_rss,
                part_rss,
            ) in partial_rows
        }
        missing = stable - by_codec.keys()
        if missing:
            raise RuntimeError(
                "missing O5 partial guard rows: " + ", ".join(sorted(missing))
            )
        regressions = sorted(
            codec_id
            for codec_id in stable
            if by_codec[codec_id][1] >= by_codec[codec_id][0]
        )
        if regressions:
            raise RuntimeError(
                "O5 partial read failed directional latency guard: "
                + ", ".join(regressions)
            )
        allocation_regressions = sorted(
            codec_id
            for codec_id, (_, _, part_peak, _, _) in by_codec.items()
            if part_peak >= 1.0
        )
        if allocation_regressions:
            raise RuntimeError(
                "O5 partial read exceeded 1 MB traced allocation: "
                + ", ".join(allocation_regressions)
            )
        rss_gain_regressions = sorted(
            codec_id
            for codec_id in stable - {"xyz"}
            if by_codec[codec_id][3] >= 8.0
            and by_codec[codec_id][4]
            >= max(4.0, 0.5 * by_codec[codec_id][3])
        )
        # XYZ must scan every mapped line to validate record boundaries. Linux
        # therefore charges the whole file to RSS, while warmed allocator reuse
        # can make the full record's output vector invisible to this delta.
        # Bound resident growth above the unavoidable file mapping instead of
        # comparing two platform-dependent deltas. The selected vector is under
        # 1 MB here, so 8 MB allows page/allocator granularity but not a full
        # 12 MB output materialization.
        xyz_file_mb = next(
            result["file_mb"]
            for result in results
            if result.get("codec") == "xyz" and "file_mb" in result
        )
        if by_codec["xyz"][4] > xyz_file_mb + 8.0:
            rss_gain_regressions.append("xyz")
        if rss_gain_regressions:
            raise RuntimeError(
                "O5 partial read failed the directional RSS gain guard: "
                + ", ".join(rss_gain_regressions)
            )
    if args.require_o4_gains:
        guarded = {
            ("webp", "balanced-config"),
            ("webp", "workers-palette"),
            ("xyz", "format-write"),
            ("las", "points-write"),
            ("las", "points-read"),
        }
        measured = {
            (codec_id, operation): (base, optimized)
            for codec_id, operation, base, optimized, _ in o4_rows
        }
        for key in sorted(guarded):
            base, optimized = measured[key]
            if optimized <= base:
                failures.append(f"o4-regression:{key[0]}:{key[1]}")

        for result in results:
            if "error" in result or "bytes_peak_mb" not in result:
                continue
            bytes_peak = result["bytes_peak_mb"]
            mmap_peak = result["mmap_peak_mb"]
            if bytes_peak >= 0.5 and mmap_peak >= bytes_peak * 0.25:
                failures.append(
                    f"mmap-memory-regression:{result['codec']}"
                )
            bytes_write_peak = result["bytes_write_peak_mb"]
            sink_write_peak = result["sink_write_peak_mb"]
            if (
                bytes_write_peak >= 0.5
                and sink_write_peak >= bytes_write_peak * 0.25
            ):
                failures.append(
                    f"sink-memory-regression:{result['codec']}"
                )
        if not failures:
            print(
                "CI regression guard: stable O4 gains and mmap/sink memory "
                "bounds passed."
            )
    if args.cold_cache and not (
        hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED")
    ):
        print("WARNING: this platform has no POSIX_FADV_DONTNEED; cold-cache hint was unavailable.")
    return failures, results


if __name__ == "__main__":
    main()
