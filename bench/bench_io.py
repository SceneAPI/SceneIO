"""O0-O5 I/O benchmark harness for docs/io_optimization_plan.md.

Measures, per codec, encode (write) + decode (read) throughput (MB/s over the raw
payload) and peak Python allocation (tracemalloc), for sceneio._core vs the oracle
library where one exists, on representative payloads for all 50 codecs. Read
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
import sys
import tempfile
import xml.etree.ElementTree as ET
from functools import partial
from itertools import pairwise
from pathlib import Path

import numpy as np

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sceneio
from bench.io_bench import measure as benchmark_measure
from bench.io_bench.families.arrays import build_array_specs
from bench.io_bench.fixtures import arrays as array_fixtures
from bench.io_bench.model import DirectorySpec, Spec
from bench.io_bench.oracles import arrays as array_oracles
from bench.io_bench.reporting import (
    print_cold_cache_unavailable,
    print_colmap_db_row,
    print_directory_row,
    print_encoding_variants,
    print_json_result,
    print_primary_error,
    print_primary_header,
    print_primary_row,
    print_regression_guard_passed,
    print_summary,
    print_typed_adapter,
)
from sceneio import _core

_depth_map = array_fixtures._depth_map
_dmb_oracle_read = array_oracles._dmb_oracle_read
_dmb_oracle_write = array_oracles._dmb_oracle_write
_load_npz_oracle = array_oracles._load_npz_oracle
_np_r = array_oracles._np_r
_np_w = array_oracles._np_w
_save_npz_oracle = array_oracles._save_npz_oracle
safetensors_load = array_oracles.safetensors_load
safetensors_load_file = array_oracles.safetensors_load_file
safetensors_open = array_oracles.safetensors_open
safetensors_save = array_oracles.safetensors_save
safetensors_save_file = array_oracles.safetensors_save_file

_measure = benchmark_measure.measure
_measure_in_process_rss = benchmark_measure.measure_in_process_rss
_try = benchmark_measure.try_measure

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
    import trimesh
except Exception:
    trimesh = None
try:
    import yaml
except Exception:
    yaml = None
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


def _y4m_fixture(side):
    frames = 4
    rng = np.random.default_rng(31)
    y = rng.integers(
        0, 256, (frames, side, side), dtype=np.uint8
    )
    chroma_side = (side + 1) // 2
    u = rng.integers(
        0, 256, (frames, chroma_side, chroma_side), dtype=np.uint8
    )
    v = rng.integers(
        0, 256, (frames, chroma_side, chroma_side), dtype=np.uint8
    )
    empty = np.empty(0, np.int64)
    record = _core.image_sequence_yuv(
        y,
        u,
        v,
        empty,
        empty,
        "420",
        "jpeg",
        "limited",
        "bt709",
        "progressive",
        25,
        1,
        1,
        1,
    )
    return record, {"y": y, "u": u, "v": v}


def _y4m_oracle_write(payload):
    """Independent serializer for the benchmark's fixed raw 4:2:0 fixture."""

    y = np.asarray(payload["y"], np.uint8)
    u = np.asarray(payload["u"], np.uint8)
    v = np.asarray(payload["v"], np.uint8)
    frames, height, width = y.shape
    expected_chroma = (frames, (height + 1) // 2, (width + 1) // 2)
    if u.shape != expected_chroma or v.shape != expected_chroma:
        raise ValueError("benchmark Y4M oracle: chroma shape mismatch")
    output = bytearray(
        (
            f"YUV4MPEG2 W{width} H{height} F25:1 Ip A1:1 "
            "C420jpeg XYSCSS=420JPEG XCOLORRANGE=LIMITED "
            "XCOLORSPACE=BT709\n"
        ).encode("ascii")
    )
    for index in range(frames):
        output += b"FRAME\n"
        output += y[index].tobytes()
        output += u[index].tobytes()
        output += v[index].tobytes()
    return bytes(output)


def _y4m_oracle_read(data):
    """Independent parser for the benchmark's fixed raw 4:2:0 fixture."""

    header, payload = bytes(data).split(b"\n", 1)
    fields = header.decode("ascii").split()
    if not fields or fields[0] != "YUV4MPEG2":
        raise ValueError("benchmark Y4M oracle: bad magic")
    tokens = {
        field[0]: field[1:]
        for field in fields[1:]
        if not field.startswith("X")
    }
    width = int(tokens["W"])
    height = int(tokens["H"])
    if (
        tokens["F"] != "25:1"
        or tokens["I"] != "p"
        or tokens["A"] != "1:1"
        or tokens["C"] != "420jpeg"
    ):
        raise ValueError("benchmark Y4M oracle: unexpected metadata")
    y_bytes = height * width
    chroma_height = (height + 1) // 2
    chroma_width = (width + 1) // 2
    chroma_bytes = chroma_height * chroma_width
    frame_bytes = y_bytes + 2 * chroma_bytes
    y_planes = []
    u_planes = []
    v_planes = []
    while payload:
        if not payload.startswith(b"FRAME\n"):
            raise ValueError("benchmark Y4M oracle: bad frame marker")
        frame = payload[6 : 6 + frame_bytes]
        if len(frame) != frame_bytes:
            raise ValueError("benchmark Y4M oracle: truncated frame")
        payload = payload[6 + frame_bytes :]
        y_planes.append(
            np.frombuffer(frame[:y_bytes], np.uint8).reshape(height, width)
        )
        u_planes.append(
            np.frombuffer(
                frame[y_bytes : y_bytes + chroma_bytes], np.uint8
            ).reshape(chroma_height, chroma_width)
        )
        v_planes.append(
            np.frombuffer(frame[y_bytes + chroma_bytes :], np.uint8).reshape(
                chroma_height, chroma_width
            )
        )
    return {
        "y": np.asarray(y_planes),
        "u": np.asarray(u_planes),
        "v": np.asarray(v_planes),
    }


def _pc(n, color):
    rng = np.random.default_rng(0)
    xyz = (rng.random((n, 3), dtype=np.float32) * 100.0).astype(np.float32)
    kw = {}
    if color:
        kw["colors16"] = (rng.random((n, 3)) * 65535).astype(np.uint16)
        kw["intensity"] = (rng.random(n) * 60000).astype(np.float32)
    return _core.point_cloud(xyz, **kw), xyz


def _pc_laz(n):
    rng = np.random.default_rng(29)
    positions = (rng.random((n, 3), dtype=np.float32) * 100.0).astype(np.float32)
    colors16 = rng.integers(0, 65_536, (n, 3), dtype=np.uint16)
    intensity = rng.integers(0, 65_536, n, dtype=np.uint16)
    payload = {
        "positions": positions,
        "colors16": colors16,
        "intensity": intensity,
    }
    return (
        _core.point_cloud(
            positions,
            colors16=colors16,
            intensity=intensity.astype(np.float32),
            intensity_range="u16",
        ),
        payload,
    )


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


def _mesh_ply(n):
    rng = np.random.default_rng(23)
    n = max(3, n)
    faces = max(1, n // 2)
    corners = faces * 3
    positions = rng.standard_normal((n, 3)).astype(np.float32)
    indices = (np.arange(corners, dtype=np.uint64) % n).reshape(faces, 3)
    offsets = np.arange(0, corners + 1, 3, dtype=np.uint64)
    vertex_normals = rng.standard_normal((n, 3)).astype(np.float32)
    vertex_uvs = rng.random((n, 2), dtype=np.float32)
    vertex_colors = rng.integers(0, 256, (n, 4), dtype=np.uint8)
    corner_normals = rng.standard_normal((corners, 3)).astype(np.float32)
    corner_uvs = rng.random((corners, 2), dtype=np.float32)
    corner_colors = rng.integers(0, 256, (corners, 4), dtype=np.uint8)
    primitive_offsets = (
        np.array([0, faces], np.uint64)
        if faces == 1
        else np.array([0, faces // 2, faces], np.uint64)
    )
    primitive_materials = np.arange(
        len(primitive_offsets) - 1, dtype=np.int32
    )
    payload = {
        "positions": positions,
        "faces": indices,
        "vertex_normals": vertex_normals,
        "vertex_uvs": vertex_uvs,
        "vertex_colors": vertex_colors,
        "corner_normals": corner_normals,
        "corner_uvs": corner_uvs,
        "corner_colors": corner_colors,
        "primitive_offsets": primitive_offsets,
        "primitive_materials": primitive_materials,
    }
    return (
        _core.mesh(
            positions,
            offsets,
            indices.reshape(-1),
            vertex_normals=vertex_normals,
            corner_normals=corner_normals,
            vertex_uvs=vertex_uvs,
            corner_uvs=corner_uvs,
            vertex_colors=vertex_colors,
            corner_colors=corner_colors,
            primitive_offsets=primitive_offsets,
            primitive_materials=primitive_materials,
        ),
        payload,
    )


def _mesh_obj(n):
    rng = np.random.default_rng(29)
    vertices = max(3, n)
    faces = max(1, vertices // 3)
    corners = faces * 3
    positions = rng.standard_normal((vertices, 3)).astype(np.float32)
    indices = (
        np.arange(corners, dtype=np.uint64) % vertices
    ).reshape(faces, 3)
    offsets = np.arange(0, corners + 1, 3, dtype=np.uint64)
    vertex_normals = rng.standard_normal((vertices, 3)).astype(np.float32)
    vertex_uvs = rng.random((vertices, 2), dtype=np.float32)
    vertex_colors = rng.integers(0, 256, (vertices, 4), dtype=np.uint8)
    vertex_colors[:, 3] = 255
    payload = {
        "positions": positions,
        "faces": indices,
        "vertex_normals": vertex_normals,
        "vertex_uvs": vertex_uvs,
        "vertex_colors": vertex_colors,
    }
    return (
        _core.mesh(
            positions,
            offsets,
            indices.reshape(-1),
            vertex_normals=vertex_normals,
            vertex_uvs=vertex_uvs,
            vertex_colors=vertex_colors,
        ),
        payload,
    )


def _mesh_stl(n):
    rng = np.random.default_rng(31)
    faces = max(1, n // 3)
    corners = faces * 3
    positions = rng.standard_normal((corners, 3)).astype(np.float32)
    indices = np.arange(corners, dtype=np.uint64).reshape(faces, 3)
    offsets = np.arange(0, corners + 1, 3, dtype=np.uint64)
    face_normals = rng.standard_normal((faces, 3)).astype(np.float32)
    corner_normals = np.repeat(face_normals, 3, axis=0)
    payload = {
        "positions": positions,
        "faces": indices,
        "face_normals": face_normals,
    }
    return (
        _core.mesh(
            positions,
            offsets,
            indices.reshape(-1),
            corner_normals=corner_normals,
        ),
        payload,
    )


def _mesh_off(n):
    rng = np.random.default_rng(37)
    # Indexed formats commonly reuse a much smaller vertex domain across many
    # faces. Keep face records dominant so bounded face selection measures the
    # work and allocations it is designed to remove.
    vertices = max(3, n // 10)
    faces = max(1, n)
    positions = rng.standard_normal((vertices, 3)).astype(np.float32)
    indices = (
        np.arange(faces * 3, dtype=np.uint64) % vertices
    ).reshape(faces, 3)
    offsets = np.arange(0, faces * 3 + 1, 3, dtype=np.uint64)
    payload = {"positions": positions, "faces": indices}
    return (
        _core.mesh(positions, offsets, indices.reshape(-1)),
        payload,
    )


def _mesh_scene(n):
    rng = np.random.default_rng(41)
    vertices = max(3, (n // 3) * 3)
    faces = max(1, vertices // 3)
    corners = vertices
    positions = rng.standard_normal((vertices, 3)).astype(np.float32)
    normals = rng.standard_normal((vertices, 3)).astype(np.float32)
    uvs = rng.random((vertices, 2), dtype=np.float32)
    colors = rng.integers(0, 256, (vertices, 4), dtype=np.uint8)
    indices = np.arange(corners, dtype=np.uint64)
    primitive_count = min(4, faces)
    face_bounds = np.linspace(
        0, faces, primitive_count + 1, dtype=np.int64
    )
    primitives = []
    for start_face, stop_face in pairwise(face_bounds):
        start = int(start_face) * 3
        stop = int(stop_face) * 3
        local_vertices = stop - start
        primitives.append(
            _core.mesh(
                positions[start:stop],
                np.arange(
                    0, local_vertices + 1, 3, dtype=np.uint64
                ),
                np.arange(local_vertices, dtype=np.uint64),
                vertex_normals=normals[start:stop],
                vertex_uvs=uvs[start:stop],
                vertex_colors=colors[start:stop],
                coordinate_frame="opengl",
            )
        )
    scene = _core.mesh_scene(
        primitives,
        np.array([0, primitive_count], np.uint64),
        mesh_names=["mesh"],
        node_meshes=np.array([0], np.int64),
        node_child_offsets=np.array([0, 0], np.uint64),
        node_children=np.array([], np.uint64),
        node_local_transforms=np.eye(4, dtype=np.float64)[None],
        node_names=["node"],
        scene_root_offsets=np.array([0, 1], np.uint64),
        scene_roots=np.array([0], np.uint64),
        scene_names=["scene"],
        default_scene=0,
    )
    payload = {
        "positions": positions,
        "faces": indices.reshape(faces, 3),
        "normals": normals,
        "uvs": uvs,
        "colors": colors,
    }
    return scene, payload


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


def _trimesh_ply_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        vertex_normals=payload["vertex_normals"],
        vertex_colors=payload["vertex_colors"],
        process=False,
    )
    return trimesh.exchange.ply.export_ply(
        mesh, encoding="binary_little_endian"
    )


def _trimesh_ply_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="ply",
        process=False,
        maintain_order=True,
        force="mesh",
    )


def _trimesh_obj_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        vertex_normals=payload["vertex_normals"],
        vertex_colors=payload["vertex_colors"],
        process=False,
    )
    return trimesh.exchange.obj.export_obj(
        mesh,
        include_normals=True,
        include_color=True,
    ).encode()


def _trimesh_obj_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="obj",
        process=False,
        maintain_order=True,
        force="mesh",
    )


def _trimesh_stl_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        process=False,
    )
    return trimesh.exchange.stl.export_stl(mesh)


def _trimesh_stl_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="stl",
        process=False,
        maintain_order=True,
        force="mesh",
    )


def _trimesh_off_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        process=False,
    )
    exported = mesh.export(file_type="off")
    return exported.encode() if isinstance(exported, str) else exported


def _trimesh_off_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="off",
        process=False,
        maintain_order=True,
        force="mesh",
    )


def _trimesh_glb_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        vertex_normals=payload["normals"],
        vertex_colors=payload["colors"],
        process=False,
    )
    return trimesh.exchange.gltf.export_glb(
        trimesh.Scene(mesh)
    )


def _trimesh_glb_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="glb",
        process=False,
        maintain_order=True,
        force="scene",
    )


def _trimesh_gltf_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        vertex_normals=payload["normals"],
        vertex_colors=payload["colors"],
        process=False,
    )
    return trimesh.exchange.gltf.export_gltf(
        trimesh.Scene(mesh)
    )


def _trimesh_gltf_r(files):
    document = next(
        name for name in files if name.endswith(".gltf")
    )
    return trimesh.load(
        io.BytesIO(files[document]),
        file_type="gltf",
        resolver=files,
        process=False,
        maintain_order=True,
        force="scene",
    )


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
    reconstruction, transforms, tum, kitti = pose_bundle or _poses_and_reconstruction(scale)
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
            "y4m",
            lambda: _y4m_fixture(side),
            _core.write_y4m,
            _core.read_y4m,
            _y4m_oracle_write,
            _y4m_oracle_read,
            lambda rec, p: sum(value.nbytes for value in p.values()),
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
            "ply_mesh",
            lambda: _mesh_ply(max(3, points // 3)),
            _core.write_ply_mesh,
            _core.read_ply_mesh,
            (_trimesh_ply_w if trimesh else None),
            (_trimesh_ply_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "obj",
            lambda: _mesh_obj(max(3, points // 3)),
            _core.write_obj,
            _core.read_obj,
            (_trimesh_obj_w if trimesh else None),
            (_trimesh_obj_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "stl",
            lambda: _mesh_stl(max(3, points // 3)),
            _core.write_stl,
            _core.read_stl,
            (_trimesh_stl_w if trimesh else None),
            (_trimesh_stl_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "off",
            lambda: _mesh_off(max(3, points // 3)),
            _core.write_off,
            _core.read_off,
            (_trimesh_off_w if trimesh else None),
            (_trimesh_off_r if trimesh else None),
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "glb",
            lambda: _mesh_scene(max(3, points // 3)),
            _core.write_glb,
            _core.read_glb,
            (_trimesh_glb_w if trimesh else None),
            (_trimesh_glb_r if trimesh else None),
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
            "laz",
            lambda: _pc_laz(points),
            lambda pc: _core.write_laz(pc, 0.001),
            _core.read_laz,
            (_laspy_laz_w if laspy else None),
            (_laspy_r if laspy else None),
            lambda rec, p: p["positions"].nbytes,
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
            "ksplat",
            lambda: _gauss(gaussians),
            _core.write_ksplat,
            _core.read_ksplat,
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
        *build_array_specs(scale),
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


def _image_sequence_directory_fixture(root, scale):
    source = Path(root) / "_image_sequence_input"
    source.mkdir()
    frame_count = 32
    side = max(8, int(256 * scale**0.5))
    rng = np.random.default_rng(37)
    paths = []
    names = []
    for index in range(frame_count):
        name = f"frame{index:04d}.ppm"
        path = source / name
        pixels = rng.integers(
            0, 256, (side, side, 3), dtype=np.uint8
        )
        path.write_bytes(
            f"P6\n{side} {side}\n255\n".encode("ascii")
            + pixels.tobytes()
        )
        paths.append(str(path))
        names.append(name)
    duration = 40_000_000
    timestamps = (
        np.arange(frame_count, dtype=np.int64) * duration
    )
    durations = np.full(frame_count, duration, np.int64)
    record = _core.image_sequence_paths(
        paths,
        names,
        timestamps,
        durations,
        side,
        side,
        3,
        "uint8",
        "unknown",
        "none",
    )
    return record, frame_count * side * side * 3


def _directory_specs(reconstruction, scale, root):
    return [
        DirectorySpec(
            "colmap_sparse",
            lambda: (reconstruction, reconstruction),
            _core.write_colmap_sparse,
            _core.read_colmap_sparse,
            lambda record, payload: _record_nbytes(payload),
        ),
        DirectorySpec(
            "colmap_sparse_txt",
            lambda: (reconstruction, reconstruction),
            _core.write_colmap_txt,
            _core.read_colmap_txt,
            lambda record, payload: _record_nbytes(payload),
        ),
        DirectorySpec(
            "image_sequence",
            partial(
                _image_sequence_directory_fixture,
                root,
                scale,
            ),
            lambda value, path: sceneio.write(
                value, path, format="image_sequence"
            ),
            lambda path: sceneio.read(
                path, format="image_sequence"
            ),
            lambda record, payload: payload,
        ),
    ]


def _directory_size(path):
    return sum(entry.stat().st_size for entry in Path(path).iterdir() if entry.is_file())


def _partial_request(codec_id, info, full_record=None):
    if codec_id in {"gltf", "glb"}:
        return {"primitive_id": 0}
    if codec_id in {"ply_mesh", "stl", "off"}:
        faces = info.metadata["num_faces"]
        if faces == 0:
            return None
        selected = max(1, faces // 16)
        start = (faces - selected) // 2
        return {"faces": (start, start + selected)}
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
        "laz",
        "gaussian_ply",
        "compressed_ply",
        "sog",
        "ksplat",
        "splat",
    }:
        selected = max(1, info.count // 16)
        start = (info.count - selected) // 2
        return {"points": (start, start + selected)}
    if codec_id in {"colmap_sparse", "colmap_sparse_txt"}:
        image_ids = np.asarray(full_record.image_ids)
        return {"image_id": int(image_ids[len(image_ids) // 2])}
    if codec_id in {"image_sequence", "y4m"}:
        selected = max(1, info.count // 16)
        start = (info.count - selected) // 2
        return {"frames": (start, start + selected)}
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
    write_rss = _measure_in_process_rss(write_sceneio)

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
    full_rss = _measure_in_process_rss(full_read)
    inspect_time, inspect_peak = _measure(inspect_read, args.runs)
    inspect_rss = _measure_in_process_rss(inspect_read)
    selected_time, selected_peak = _measure(selected_read, args.runs)
    selected_rss = _measure_in_process_rss(selected_read)

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
        oracle_write_rss = _measure_in_process_rss(
            lambda: safetensors_save_file(arrays, oracle_path)
        )
        oracle_full_time, oracle_full_peak = _measure(
            oracle_full, args.runs
        )
        oracle_full_rss = _measure_in_process_rss(oracle_full)

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
        oracle_inspect_rss = _measure_in_process_rss(oracle_inspect)
        oracle_selected_time, oracle_selected_peak = _measure(
            oracle_selected, args.runs
        )
        oracle_selected_rss = _measure_in_process_rss(oracle_selected)
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
    print_json_result(result)
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
    native_write_rss = _measure_in_process_rss(native_write)
    oracle_write_time = oracle_write_peak = oracle_write_rss = None
    if not args.skip_oracles:
        oracle_write_time, oracle_write_peak = _measure(
            oracle_write, args.runs
        )
        oracle_write_rss = _measure_in_process_rss(oracle_write)

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
    native_full_rss = _measure_in_process_rss(native_full_read)
    inspect_time, inspect_peak = _measure(native_inspect, args.runs)
    inspect_rss = _measure_in_process_rss(native_inspect)
    image_time, image_peak = _measure(native_image_read, args.runs)
    image_rss = _measure_in_process_rss(native_image_read)
    pair_time, pair_peak = _measure(native_pair_read, args.runs)
    pair_rss = _measure_in_process_rss(native_pair_read)

    oracle_metrics = {}
    oracle_full_time = None
    if not args.skip_oracles:
        oracle_full_time, oracle_full_peak = _measure(
            oracle_full_read, args.runs
        )
        oracle_full_rss = _measure_in_process_rss(oracle_full_read)
        oracle_inspect_time, oracle_inspect_peak = _measure(
            oracle_inspect, args.runs
        )
        oracle_inspect_rss = _measure_in_process_rss(oracle_inspect)
        oracle_image_time, oracle_image_peak = _measure(
            oracle_image_read, args.runs
        )
        oracle_image_rss = _measure_in_process_rss(oracle_image_read)
        oracle_pair_time, oracle_pair_peak = _measure(
            oracle_pair_read, args.runs
        )
        oracle_pair_rss = _measure_in_process_rss(oracle_pair_read)
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


def _benchmark_gltf(args, tmp):
    points = max(3, int(300_000 * args.scale))
    record, payload = _mesh_scene(points)
    payload_bytes = sum(value.nbytes for value in payload.values())
    payload_mb = payload_bytes / 1e6
    path = Path(tmp) / "gltf_scene.gltf"
    peer = path.with_suffix(".bin")
    buffer_uri = peer.name

    def _encode():
        return _core.write_gltf(record, buffer_uri)

    json_bytes, binary_bytes = _encode()
    json_bytes = bytes(json_bytes)
    binary_bytes = bytes(binary_bytes)
    file_mb = (len(json_bytes) + len(binary_bytes)) / 1e6

    core_write_time, bytes_write_peak = _measure(
        _encode, args.runs
    )
    bytes_write_rss = _measure_in_process_rss(_encode)

    def _buffer_write():
        document, binary = _encode()
        path.write_bytes(document)
        peer.write_bytes(binary)

    def _sink_write():
        return sceneio.write(record, path, format="gltf")

    bytes_path_write_time, _ = _measure(
        _buffer_write, args.runs
    )
    sink_write_time, sink_write_peak = _measure(
        _sink_write, args.runs
    )
    sink_write_rss = _measure_in_process_rss(_sink_write)
    if (
        path.read_bytes() != json_bytes
        or peer.read_bytes() != binary_bytes
    ):
        raise AssertionError(
            "glTF file sink output differs from buffer encoder")

    def _core_read():
        return _core.read_gltf(
            json_bytes, {buffer_uri: binary_bytes})

    core_read_time, _ = _measure(_core_read, args.runs)

    def _bytes_read():
        return _core.read_gltf(
            path.read_bytes(), {buffer_uri: peer.read_bytes()})

    def _path_read():
        if args.cold_cache:
            _evict_file_cache(path)
            _evict_file_cache(peer)
        return sceneio.read(path, format="gltf")

    _, bytes_peak = _measure(_bytes_read, args.runs)
    path_read_time, mmap_peak = _measure(
        _path_read, args.runs
    )
    bytes_rss = _measure_in_process_rss(_bytes_read)
    mmap_rss = _measure_in_process_rss(_path_read)

    def _inspect():
        if args.cold_cache:
            _evict_file_cache(path)
        return sceneio.inspect(path, format="gltf")

    inspect_time, inspect_peak = _measure(
        _inspect, args.runs
    )
    inspect_rss = _measure_in_process_rss(_inspect)

    def _partial():
        if args.cold_cache:
            _evict_file_cache(path)
            _evict_file_cache(peer)
        return sceneio.read_partial(
            path, format="gltf", primitive_id=0)

    partial_time, partial_peak = _measure(
        _partial, args.runs
    )
    partial_rss = _measure_in_process_rss(_partial)

    oracle_write_time = None
    oracle_read_time = None
    if trimesh is not None and not args.skip_oracles:
        oracle_files = _try(
            lambda: _trimesh_gltf_w(payload))
        if oracle_files is not None:
            measured = _try(
                lambda: _measure(
                    lambda: _trimesh_gltf_w(payload),
                    args.runs,
                ))
            oracle_write_time = measured[0] if measured else None
            measured = _try(
                lambda: _measure(
                    lambda: _trimesh_gltf_r(oracle_files),
                    args.runs,
                ))
            oracle_read_time = measured[0] if measured else None

    result = {
        "codec": "gltf",
        "payload_mb": payload_mb,
        "file_mb": file_mb,
        "write_mbps": payload_mb / core_write_time,
        "bytes_path_write_mbps": (
            payload_mb / bytes_path_write_time),
        "path_write_mbps": payload_mb / sink_write_time,
        "read_mbps": payload_mb / core_read_time,
        "path_read_mbps": payload_mb / path_read_time,
        "oracle_write_mbps": (
            payload_mb / oracle_write_time
            if oracle_write_time is not None else None),
        "oracle_read_mbps": (
            payload_mb / oracle_read_time
            if oracle_read_time is not None else None),
        "bytes_peak_mb": bytes_peak / 1e6,
        "mmap_peak_mb": mmap_peak / 1e6,
        "bytes_rss_mb": bytes_rss / 1e6,
        "mmap_rss_mb": mmap_rss / 1e6,
        "inspect_ms": inspect_time * 1000,
        "inspect_peak_mb": inspect_peak / 1e6,
        "inspect_rss_mb": inspect_rss / 1e6,
        "partial_ms": partial_time * 1000,
        "partial_peak_mb": partial_peak / 1e6,
        "partial_rss_mb": partial_rss / 1e6,
        "bytes_write_peak_mb": bytes_write_peak / 1e6,
        "sink_write_peak_mb": sink_write_peak / 1e6,
        "bytes_write_rss_mb": bytes_write_rss / 1e6,
        "sink_write_rss_mb": sink_write_rss / 1e6,
    }
    write_row = (
        "gltf",
        payload_mb,
        file_mb,
        payload_mb / bytes_path_write_time,
        payload_mb / sink_write_time,
        bytes_write_peak / 1e6,
        sink_write_peak / 1e6,
        bytes_write_rss / 1e6,
        sink_write_rss / 1e6,
    )
    inspect_row = (
        "gltf",
        path_read_time,
        inspect_time,
        mmap_peak / 1e6,
        inspect_peak / 1e6,
        mmap_rss / 1e6,
        inspect_rss / 1e6,
    )
    partial_row = (
        "gltf",
        path_read_time,
        partial_time,
        mmap_peak / 1e6,
        partial_peak / 1e6,
        mmap_rss / 1e6,
        partial_rss / 1e6,
    )
    display = (
        payload_mb,
        file_mb,
        payload_mb / core_write_time,
        payload_mb / core_read_time,
        payload_mb / path_read_time,
        result["oracle_write_mbps"],
        result["oracle_read_mbps"],
        bytes_peak / 1e6,
        mmap_peak / 1e6,
        bytes_rss / 1e6,
        mmap_rss / 1e6,
    )
    return result, write_row, inspect_row, partial_row, display


def _run_benchmark(args, tmp):
    pose_bundle = _poses_and_reconstruction(args.scale)
    reconstruction = pose_bundle[0]
    specs = _specs(args.scale, pose_bundle)
    directory_specs = _directory_specs(
        reconstruction, args.scale, tmp
    )
    include_colmap_db = True
    include_gltf = True
    if args.only:
        requested = set(args.only)
        known = {spec.id for spec in specs} | {
            spec.id for spec in directory_specs
        } | {"colmap_db", "gltf"}
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
        include_gltf = "gltf" in requested
    failures = []
    results = []
    write_rows = []
    o4_rows = []
    inspect_rows = []
    partial_rows = []

    print_primary_header()
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
            bytes_write_rss = _measure_in_process_rss(_bytes_write)
            sink_time, sink_write_peak = _measure(_sink_write, args.runs)
            sink_write_rss = _measure_in_process_rss(_sink_write)
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
            bytes_rss = _measure_in_process_rss(_bytes_read)
            mmap_rss = _measure_in_process_rss(_mmap_read)
            path_read = pmb / path_time

            def _inspect(fp=fp, codec_id=s.id):
                if args.cold_cache:
                    _evict_file_cache(fp)
                return sceneio.inspect(fp, format=codec_id)

            inspect_time, inspect_peak = _measure(_inspect, args.runs)
            inspect_rss = _measure_in_process_rss(_inspect)
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
                typed_read_rss = _measure_in_process_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_in_process_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_in_process_rss(_typed_inspect)
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
                typed_read_rss = _measure_in_process_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_in_process_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_in_process_rss(_typed_inspect)
                typed_partial_time, typed_partial_peak = _measure(
                    _typed_partial, args.runs
                )
                typed_partial_rss = _measure_in_process_rss(_typed_partial)
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
                typed_read_rss = _measure_in_process_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_in_process_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_in_process_rss(_typed_inspect)
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
                typed_read_rss = _measure_in_process_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_in_process_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_in_process_rss(_typed_inspect)
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
                partial_rss = _measure_in_process_rss(_partial_read)
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
            print_primary_row(
                s.id,
                pmb,
                fmb,
                sioW,
                sioR,
                path_read,
                oraW,
                oraR,
                bytes_peak / 1e6,
                mmap_peak / 1e6,
                bytes_rss / 1e6,
                mmap_rss / 1e6,
                ratio,
            )
            if typed_adapter_metrics is not None:
                print_typed_adapter(typed_adapter_metrics)
            if ply_variant_metrics is not None:
                print_encoding_variants("PLY", ply_variant_metrics)
            if pcd_variant_metrics is not None:
                print_encoding_variants("PCD", pcd_variant_metrics)
        except Exception as e:
            failures.append(s.id)
            results.append({"codec": s.id, "error": f"{type(e).__name__}: {e}"})
            print_primary_error(s.id, e)

    if include_gltf:
        try:
            (
                gltf_result,
                gltf_write_row,
                gltf_inspect_row,
                gltf_partial_row,
                gltf_display,
            ) = _benchmark_gltf(args, tmp)
            results.append(gltf_result)
            write_rows.append(gltf_write_row)
            inspect_rows.append(gltf_inspect_row)
            partial_rows.append(gltf_partial_row)
            (
                payload_mb,
                file_mb,
                write_mbps,
                read_mbps,
                path_read_mbps,
                oracle_write_mbps,
                oracle_read_mbps,
                bytes_peak_mb,
                mmap_peak_mb,
                bytes_rss_mb,
                mmap_rss_mb,
            ) = gltf_display
            ratio = (
                read_mbps / oracle_read_mbps
                if oracle_read_mbps else 0)
            print_primary_row(
                "gltf",
                payload_mb,
                file_mb,
                write_mbps,
                read_mbps,
                path_read_mbps,
                oracle_write_mbps,
                oracle_read_mbps,
                bytes_peak_mb,
                mmap_peak_mb,
                bytes_rss_mb,
                mmap_rss_mb,
                ratio,
            )
        except Exception as e:
            failures.append("gltf")
            results.append(
                {
                    "codec": "gltf",
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            print_primary_error("gltf", e)

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
            print_colmap_db_row(database_display)
        except Exception as e:
            failures.append("colmap_db")
            results.append(
                {
                    "codec": "colmap_db",
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            print_primary_error("colmap_db", e)

    for spec in directory_specs:
        try:
            value, payload = spec.make()
            path = Path(tmp) / spec.id
            path.mkdir()
            spec.w(value, str(path))
            file_bytes = _directory_size(path)
            payload_bytes = spec.nbytes(value, payload)
            pmb = payload_bytes / 1e6
            fmb = file_bytes / 1e6
            write_time, write_peak = _measure(
                lambda: spec.w(value, str(path)), args.runs
            )
            write_rss = _measure_in_process_rss(
                lambda: spec.w(value, str(path))
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
            read_rss = _measure_in_process_rss(_directory_read)

            def _directory_inspect(path=path, codec_id=spec.id):
                if args.cold_cache:
                    for entry in path.iterdir():
                        if entry.is_file():
                            _evict_file_cache(entry)
                return sceneio.inspect(path, format=codec_id)

            inspect_time, inspect_peak = _measure(
                _directory_inspect, args.runs
            )
            inspect_rss = _measure_in_process_rss(_directory_inspect)
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
                spec.id, _directory_inspect(), value
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
            partial_rss = _measure_in_process_rss(_directory_partial)
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
            print_directory_row(
                spec.id,
                pmb,
                fmb,
                pmb / write_time,
                pmb / core_read_time,
                pmb / path_read_time,
                read_peak / 1e6,
                read_rss / 1e6,
            )
        except Exception as e:
            failures.append(spec.id)
            results.append({"codec": spec.id, "error": f"{type(e).__name__}: {e}"})
            print_primary_error(spec.id, e)

    if not args.only:
        assert (
            len(specs)
            + len(directory_specs)
            + int(include_colmap_db)
            + int(include_gltf)
            == 50
        )
    print_summary(write_rows, o4_rows, inspect_rows, partial_rows)
    if args.require_o5_inspect_gains:
        stable = {
            "exr",
            "gaussian_ply",
            "las",
            "laz",
            "off",
            "png",
            "spz",
            "stl",
            "y4m",
        }
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
            "ply_mesh",
            "stl",
            "off",
            "las",
            "laz",
            "gaussian_ply",
            "splat",
            "colmap_sparse",
            "colmap_sparse_txt",
            "y4m",
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
            for codec_id in stable - {"xyz", "ply_mesh"}
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
        # A mesh face selection validates the complete mapped file and retains
        # the complete vertex domain by contract. The benchmark's vertex-domain
        # output is about 12 MB, so allow the file mapping plus 20 MB of record
        # and allocator overhead while still rejecting full corner-domain
        # materialization.
        mesh_file_mb = next(
            result["file_mb"]
            for result in results
            if result.get("codec") == "ply_mesh" and "file_mb" in result
        )
        if by_codec["ply_mesh"][4] > mesh_file_mb + 20.0:
            rss_gain_regressions.append("ply_mesh")
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
            print_regression_guard_passed()
    if args.cold_cache and not (
        hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED")
    ):
        print_cold_cache_unavailable()
    return failures, results


if __name__ == "__main__":
    main()
