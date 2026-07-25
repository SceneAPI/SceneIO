"""O1 mmap and O3 file-sink differential, memory, and edge coverage."""

from __future__ import annotations

import binascii
import gc
import gzip
import io
import json
import mmap
import os
import struct
import subprocess
import sys
import tracemalloc
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import registry


@dataclass(frozen=True)
class BufferCodec:
    id: str
    reader: object
    writer: object
    value: object
    data: bytes


def _array_fingerprint(value):
    array = np.asarray(value)
    return array.dtype.str, array.shape, array.tobytes()


def _camera_fingerprint(camera):
    return (
        camera.id,
        camera.model_id,
        camera.width,
        camera.height,
        _array_fingerprint(camera.params),
    )


def _fingerprint(value):
    """Capture every exposed field of a decoded record."""
    if isinstance(value, np.ndarray):
        fields = _array_fingerprint(value)
    elif isinstance(value, _core.Image):
        fields = (
            value.height,
            value.width,
            value.channels,
            value.dtype,
            value.color_space,
            value.alpha_mode,
            value.maxval,
            value.channel_order,
            value.row_order,
            _array_fingerprint(value.pixels),
        )
    elif isinstance(value, _core.DepthMap):
        fields = (
            value.height,
            value.width,
            value.has_confidence,
            value.unit,
            value.scale_to_meters,
            value.invalid_policy,
            value.row_order,
            _array_fingerprint(value.depth),
            (
                _array_fingerprint(value.confidence)
                if value.has_confidence
                else None
            ),
        )
    elif isinstance(value, _core.GaussianCloud):
        fields = (
            value.num_gaussians,
            value.sh_degree,
            value.num_rest,
            value.quaternion_order,
            value.scale_space,
            value.opacity_space,
            value.sh_layout,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "means",
                    "scales",
                    "quaternions",
                    "opacities",
                    "sh_dc",
                    "sh_rest",
                )
            ),
        )
    elif isinstance(value, _core.PointCloud):
        fields = (
            value.num_points,
            value.has_rgb,
            value.has_rgb16,
            value.has_normals,
            value.has_intensity,
            value.coordinate_frame,
            value.scale_to_meters,
            value.intensity_range,
            value.origin,
            value.width,
            value.height,
            value.is_organized,
            value.viewpoint,
            *(
                _array_fingerprint(getattr(value, name))
                for name in ("positions", "colors", "colors16", "normals", "intensities")
            ),
        )
    elif isinstance(value, _core.PosedViewSet):
        fields = (
            value.num_views,
            value.num_cameras,
            value.quaternion_order,
            value.pose_convention,
            value.axis_frame,
            value.scale_to_meters,
            tuple(value.names),
            tuple(_camera_fingerprint(camera) for camera in value.cameras),
            *(
                _array_fingerprint(getattr(value, name))
                for name in ("quaternions", "translations", "camera_indices", "timestamps")
            ),
        )
    elif isinstance(value, _core.StateTrajectory):
        fields = (
            value.num_states,
            value.quaternion_order,
            value.quaternion_sign,
            value.pose_convention,
            value.position_frame,
            value.velocity_frame,
            value.bias_frame,
            value.position_unit,
            value.velocity_unit,
            value.gyro_bias_unit,
            value.accel_bias_unit,
            value.timestamp_unit,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "timestamps_ns",
                    "positions",
                    "quaternions",
                    "velocities",
                    "gyro_biases",
                    "accel_biases",
                )
            ),
        )
    elif isinstance(value, _core.CameraRig):
        fields = (
            value.num_cameras,
            tuple(value.names),
            tuple(value.projection_models),
            tuple(value.distortion_models),
            tuple(value.topics),
            value.quaternion_order,
            value.quaternion_sign,
            value.transform_convention,
            value.axis_frame,
            value.reference_frame,
            value.scale_to_meters,
            value.time_offset_convention,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "camera_ids",
                    "resolutions",
                    "intrinsic_offsets",
                    "intrinsics",
                    "distortion_offsets",
                    "distortion_coefficients",
                    "quaternions",
                    "translations",
                    "has_extrinsics",
                    "camera_matrices",
                    "has_camera_matrix",
                    "rectification_matrices",
                    "has_rectification",
                    "projection_matrices",
                    "has_projection_matrix",
                    "binning",
                    "roi",
                    "roi_do_rectify",
                    "has_operational",
                    "time_offsets",
                    "has_time_offset",
                )
            ),
        )
    elif isinstance(value, _core.PoseGraph):
        fields = (
            value.num_nodes,
            value.num_edges,
            tuple(value.node_types),
            tuple(value.edge_types),
            value.quaternion_order,
            value.quaternion_sign,
            value.node_transform_convention,
            value.edge_transform_convention,
            value.translation_unit,
            value.information_variable_order,
            value.information_storage,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "node_ids",
                    "node_translations",
                    "node_quaternions",
                    "fixed",
                    "edge_endpoints",
                    "edge_translations",
                    "edge_quaternions",
                    "information_matrices",
                )
            ),
        )
    elif isinstance(value, _core.Reconstruction):
        fields = (
            value.num_cameras,
            value.num_images,
            value.num_points3D,
            value.quaternion_order,
            value.pose_convention,
            tuple(value.image_names),
            tuple(_camera_fingerprint(camera) for camera in value.cameras),
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "image_ids",
                    "quaternions",
                    "translations",
                    "image_camera_ids",
                    "point3D_ids",
                    "xyz",
                    "rgb",
                    "errors",
                )
            ),
        )
    elif isinstance(value, _core.TensorDict):
        fields = (
            tuple(value.keys()),
            tuple((key, _array_fingerprint(value[key])) for key in value),
            value.attrs,
            value.byte_order,
            value.order,
        )
    else:  # pragma: no cover - every registered O1 codec is represented above
        raise AssertionError(f"unhandled result type {type(value)!r}")
    # O2 raw mapped arrays use a private ndarray subtype solely to make DLPack
    # export copy-safe; normalize it to the same public ndarray record kind.
    result_type = np.ndarray if isinstance(value, np.ndarray) else type(value)
    return result_type, fields


@pytest.fixture(scope="module")
def buffer_codecs():
    rng = np.random.default_rng(91)
    rgb = rng.integers(0, 256, (7, 9, 3), dtype=np.uint8)
    rgba = rng.integers(0, 256, (7, 9, 4), dtype=np.uint8)
    rgba[..., 3] = np.arange(7 * 9, dtype=np.uint8).reshape(7, 9) * 4
    rgb16 = rng.integers(0, 65536, (7, 9, 3), dtype=np.uint16)
    rgba16 = rng.integers(0, 65536, (7, 9, 4), dtype=np.uint16)
    linear = rng.random((7, 9, 3), dtype=np.float32) * 4
    linear_rgba = rng.random((7, 9, 4), dtype=np.float32) * 4
    linear_rgba[..., 3] = rng.random((7, 9), dtype=np.float32)
    image_u8 = _core.image(rgb, color_space="srgb")
    image_rgba = _core.image(rgba, color_space="srgb", alpha_mode="straight")
    image_u16 = _core.image(rgb16, color_space="srgb")
    image_rgba16 = _core.image(rgba16, color_space="srgb", alpha_mode="straight")
    image_f32 = _core.image(linear, color_space="linear")
    image_f32_rgba = _core.image(linear_rgba, color_space="linear", alpha_mode="premultiplied")
    positions = rng.random((13, 3), dtype=np.float32) * 10
    points_xyz = _core.point_cloud(positions, colors=rng.integers(0, 256, (13, 3), dtype=np.uint8))
    points_pts = _core.point_cloud(
        positions,
        colors=rng.integers(0, 256, (13, 3), dtype=np.uint8),
        intensity=rng.standard_normal(13).astype(np.float32),
    )
    points_ply = _core.point_cloud(
        positions,
        colors=rng.integers(0, 256, (13, 3), dtype=np.uint8),
        normals=rng.standard_normal((13, 3)).astype(np.float32),
        intensity=rng.standard_normal(13).astype(np.float32),
    )
    points_pcd = _core.point_cloud(
        positions,
        colors=rng.integers(0, 256, (13, 3), dtype=np.uint8),
        normals=rng.standard_normal((13, 3)).astype(np.float32),
        intensity=rng.integers(0, 65536, 13).astype(np.float32),
        intensity_range="u16",
        width=13,
        height=1,
        viewpoint=np.asarray(
            [1.0, 2.0, 3.0, 1.0, 0.0, 0.0, 0.0],
            dtype=np.float64,
        ),
    )
    points_las = _core.point_cloud(
        positions,
        colors16=rng.integers(0, 65536, (13, 3), dtype=np.uint16),
        intensity=rng.integers(0, 65536, 13).astype(np.float32),
        intensity_range="u16",
    )
    flow = rng.standard_normal((5, 6, 2)).astype(np.float32)
    depth = _core.depth_map(
        rng.standard_normal((5, 6)).astype(np.float32),
        unit="unknown",
        invalid_policy="zero",
    )
    tensor = rng.standard_normal((4, 5, 3)).astype(np.float32)
    tensors = _core.tensor_dict({"a": tensor, "b": np.arange(9, dtype=np.int16)})
    gaussians = _core.gaussian_cloud(
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 4)).astype(np.float32),
        rng.standard_normal(11).astype(np.float32),
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 45)).astype(np.float32),
    )
    reconstruction = _core.read_nvm(
        b"NVM_V3\n1\na.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\n"
        b"1\n1.5 -2.5 3.5 10 20 30 1 0 0 4.5 -5.5\n0\n"
    )
    bal_reconstruction = _core.read_bal(
        b"1 1 1\n"
        b"0 0 10.5 20.25\n"
        b"0\n0\n0\n1\n2\n3\n800\n0.5\n0.25\n"
        b"1.5\n-2.5\n3.5\n"
    )
    transforms = _core.read_transforms_json(
        b'{"camera_model":"PINHOLE","fl_x":500,"fl_y":510,"cx":320,"cy":240,'
        b'"w":640,"h":480,"frames":[{"file_path":"a.png","transform_matrix":'
        b"[[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]]}]}"
    )
    tum = _core.read_tum(b"0 1 2 3 0 0 0 1\n")
    kitti = _core.read_kitti(b"1 0 0 1 0 1 0 2 0 0 1 3\n")
    state_quaternions = rng.standard_normal((13, 4))
    state_trajectory = _core.state_trajectory(
        np.arange(13, dtype=np.int64) + 1_400_000_000_000_000_000,
        rng.standard_normal((13, 3)),
        state_quaternions,
        rng.standard_normal((13, 3)),
        rng.standard_normal((13, 3)),
        rng.standard_normal((13, 3)),
    )
    camera_matrix = np.array(
        [[[500.0, 0.0, 320.0], [0.0, 510.0, 240.0], [0.0, 0.0, 1.0]]]
    )
    camera_rig = _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 5], np.uint64),
        np.array([0.1, -0.2, 0.01, 0.02, -0.001]),
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
        has_extrinsics=np.zeros(1, np.uint8),
        camera_matrices=camera_matrix,
    )
    ros_camera_rig = _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 5], np.uint64),
        np.array([0.1, -0.2, 0.01, 0.02, -0.001]),
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
        has_extrinsics=np.zeros(1, np.uint8),
        camera_matrices=camera_matrix,
        rectification_matrices=np.eye(3)[None],
        projection_matrices=np.array(
            [[[500.0, 0.0, 320.0, 0.0],
              [0.0, 510.0, 240.0, 0.0],
              [0.0, 0.0, 1.0, 0.0]]]
        ),
        binning=np.array([[0, 0]], np.uint32),
        roi=np.array([[0, 0, 0, 0]], np.uint32),
        roi_do_rectify=np.array([0], np.uint8),
        has_operational=np.array([1], np.uint8),
    )
    kalibr_rig = _core.read_kalibr(
        b"cam0:\n"
        b"  camera_model: pinhole\n"
        b"  intrinsics: [500, 510, 320, 240]\n"
        b"  distortion_model: radtan\n"
        b"  distortion_coeffs: [0.1, -0.2, 0.01, 0.02]\n"
        b"  resolution: [640, 480]\n"
        b"  rostopic: /cam0/image_raw\n"
        b"  T_cam_imu:\n"
        b"  - [1, 0, 0, 0.1]\n"
        b"  - [0, 1, 0, 0.2]\n"
        b"  - [0, 0, 1, 0.3]\n"
        b"  - [0, 0, 0, 1]\n"
    )
    pose_information = np.tile(np.eye(6), (2, 1, 1))
    pose_graph = _core.pose_graph(
        np.array([3, 7, 11], np.int64),
        rng.standard_normal((3, 3)),
        np.array(
            [[0.0, 0.0, 0.0, 1.0]] * 3,
            np.float64,
        ),
        np.array([[3, 7], [7, 11]], np.int64),
        rng.standard_normal((2, 3)),
        np.array(
            [[0.0, 0.0, 0.0, 1.0]] * 2,
            np.float64,
        ),
        pose_information,
        fixed=np.array([1, 0, 0], np.uint8),
    )

    def spec(codec_id, reader, writer, value):
        return BufferCodec(codec_id, reader, writer, value, bytes(writer(value)))

    return [
        spec("pfm", _core.read_pfm, _core.write_pfm, tensor),
        spec("gaussian_ply", _core.read_gaussian_ply, _core.write_gaussian_ply, gaussians),
        spec(
            "compressed_ply",
            _core.read_compressed_ply,
            _core.write_compressed_ply,
            gaussians,
        ),
        spec("spz", _core.read_spz, _core.write_spz, gaussians),
        spec(
            "transforms_json",
            _core.read_transforms_json,
            _core.write_transforms_json,
            transforms,
        ),
        spec("tum", _core.read_tum, _core.write_tum, tum),
        spec("kitti", _core.read_kitti, _core.write_kitti, kitti),
        spec(
            "euroc_state",
            _core.read_euroc_state,
            _core.write_euroc_state,
            state_trajectory,
        ),
        spec(
            "opencv_yaml",
            _core.read_opencv_yaml,
            _core.write_opencv_yaml,
            camera_rig,
        ),
        spec(
            "opencv_xml",
            _core.read_opencv_xml,
            _core.write_opencv_xml,
            camera_rig,
        ),
        spec(
            "ros_camera_info",
            _core.read_ros_camera_info,
            _core.write_ros_camera_info,
            ros_camera_rig,
        ),
        spec(
            "kalibr",
            _core.read_kalibr,
            _core.write_kalibr,
            kalibr_rig,
        ),
        spec("g2o", _core.read_g2o, _core.write_g2o, pose_graph),
        spec("npy", _core.read_npy, _core.write_npy, tensor),
        spec("npz", _core.read_npz, _core.write_npz, tensors),
        spec(
            "safetensors",
            _core.read_safetensors,
            _core.write_safetensors,
            tensors,
        ),
        spec("netpbm", _core.read_netpbm, _core.write_netpbm, image_u16),
        spec("png", _core.read_png, _core.write_png, image_rgba16),
        spec("jpeg", _core.read_jpeg, _core.write_jpeg, image_u8),
        spec("bmp", _core.read_bmp, _core.write_bmp, image_rgba),
        spec("tga", _core.read_tga, _core.write_tga, image_rgba),
        spec("hdr", _core.read_hdr, _core.write_hdr, image_f32),
        spec("exr", _core.read_exr, _core.write_exr, image_f32_rgba),
        spec("webp", _core.read_webp, _core.write_webp, image_rgba),
        spec("xyz", _core.read_xyz, _core.write_xyz, points_xyz),
        spec("pts", _core.read_pts, _core.write_pts, points_pts),
        spec("ply", _core.read_ply, _core.write_ply, points_ply),
        spec("pcd", _core.read_pcd, _core.write_pcd, points_pcd),
        spec("las", _core.read_las, _core.write_las, points_las),
        spec("flo", _core.read_flo, _core.write_flo, flow),
        spec("dmb", _core.read_dmb, _core.write_dmb, depth),
        spec("bundler", _core.read_bundler, _core.write_bundler, reconstruction),
        spec("bal", _core.read_bal, _core.write_bal, bal_reconstruction),
        spec("nvm", _core.read_nvm, _core.write_nvm, reconstruction),
        spec("openmvg", _core.read_openmvg, _core.write_openmvg, reconstruction),
        spec("splat", _core.read_splat, _core.write_splat, gaussians),
    ]


def _decode_outcome(call, argument):
    try:
        return "ok", call(argument)
    except Exception as exc:  # malformed-input parity includes exception text
        return "error", type(exc), str(exc)


def _finish_outcome(decoded):
    if decoded[0] == "error":
        return decoded
    return "ok", _fingerprint(decoded[1])


def _outcome(call, argument):
    return _finish_outcome(_decode_outcome(call, argument))


def test_all_single_file_codecs_mmap_equal_bytes_bit_exact(tmp_path, buffer_codecs):
    """All 36 buffer codecs decode mmap and bytes to bit-exact records."""
    assert len(buffer_codecs) == 36
    for spec in buffer_codecs:
        expected = _fingerprint(spec.reader(spec.data))
        path = tmp_path / f"sample-{spec.id}.bin"
        path.write_bytes(spec.data)
        with (
            path.open("rb") as stream,
            mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
        ):
            actual_value = spec.reader(mapped)

        # Force collection after the mmap and file handle close: O1 results must
        # own every decoded byte and remain valid without their input exporter.
        gc.collect()
        assert _fingerprint(actual_value) == expected, spec.id


def test_all_single_file_sinks_are_byte_identical(tmp_path, buffer_codecs):
    """All 36 compiled encoders emit the exact bytes their buffer API returns."""
    assert len(buffer_codecs) == 36
    for spec in buffer_codecs:
        direct = tmp_path / f"direct-{spec.id}.bin"
        _core._write_to_file(spec.writer, spec.value, direct)
        assert direct.read_bytes() == spec.data, spec.id

        public = tmp_path / f"public-{spec.id}.bin"
        sceneio.write(spec.value, public, format=spec.id)
        assert public.read_bytes() == spec.data, spec.id

        # The thread-local sink scope must never leak into a later buffer call.
        assert bytes(spec.writer(spec.value)) == spec.data, spec.id


def test_directory_codec_writers_remain_byte_identical_file_sinks(
    tmp_path, buffer_codecs
):
    """The two COLMAP directory writers were already direct file sinks."""
    nvm = next(spec for spec in buffer_codecs if spec.id == "nvm")
    reconstruction = nvm.reader(nvm.data)
    for format_id, writer in (
        ("colmap_sparse", _core.write_colmap_sparse),
        ("colmap_sparse_txt", _core.write_colmap_txt),
    ):
        expected = tmp_path / f"direct-{format_id}"
        actual = tmp_path / f"public-{format_id}"
        expected.mkdir()
        actual.mkdir()
        writer(reconstruction, str(expected))
        sceneio.write(reconstruction, actual, format=format_id)
        expected_files = {
            item.name: item.read_bytes() for item in expected.iterdir() if item.is_file()
        }
        actual_files = {
            item.name: item.read_bytes() for item in actual.iterdir() if item.is_file()
        }
        assert actual_files == expected_files


def _assert_inspection_matches(info, decoded):
    if isinstance(decoded, np.ndarray):
        assert info.shape == decoded.shape
        assert info.dtype == decoded.dtype.name
    elif isinstance(decoded, _core.Image):
        assert info.shape == decoded.pixels.shape
        assert info.dtype == decoded.dtype
        assert info.channels == decoded.channels
    elif isinstance(decoded, _core.DepthMap):
        assert info.shape == decoded.depth.shape
        assert info.dtype == decoded.depth.dtype.name
        assert info.count == decoded.height * decoded.width
        assert info.channels == 1
    elif isinstance(decoded, _core.GaussianCloud):
        assert info.shape == (decoded.num_gaussians,)
        assert info.dtype == "float32"
        assert info.count == decoded.num_gaussians
        assert info.metadata["sh_degree"] == decoded.sh_degree
    elif isinstance(decoded, _core.PointCloud):
        assert info.shape == decoded.positions.shape
        assert info.dtype == decoded.positions.dtype.name
        assert info.count == decoded.num_points
    elif isinstance(decoded, _core.PosedViewSet):
        assert info.shape == (decoded.num_views,)
        assert info.dtype == decoded.quaternions.dtype.name
        assert info.count == decoded.num_views
        if "num_cameras" in info.metadata:
            assert info.metadata["num_cameras"] == decoded.num_cameras
    elif isinstance(decoded, _core.StateTrajectory):
        assert info.shape == (decoded.num_states,)
        assert info.dtype == "float64"
        assert info.count == decoded.num_states
        assert info.metadata["timestamp_unit"] == "nanoseconds"
        assert info.metadata["quaternion_order"] == "wxyz"
    elif isinstance(decoded, _core.CameraRig):
        assert info.shape == (decoded.num_cameras,)
        assert info.dtype == "float64"
        assert info.count == decoded.num_cameras
        assert info.metadata["resolutions"] == tuple(
            np.asarray(decoded.resolutions).ravel()
        )
        assert info.metadata["axis_frame"] == "opencv"
    elif isinstance(decoded, _core.PoseGraph):
        assert info.shape == (decoded.num_nodes,)
        assert info.dtype == "float64"
        assert info.count == decoded.num_nodes
        assert info.metadata["num_nodes"] == decoded.num_nodes
        assert info.metadata["num_edges"] == decoded.num_edges
        assert info.metadata["num_fixed_nodes"] == int(decoded.fixed.sum())
        assert info.metadata["quaternion_order"] == decoded.quaternion_order
        assert (
            info.metadata["edge_transform_convention"]
            == decoded.edge_transform_convention
        )
    elif isinstance(decoded, _core.Reconstruction):
        assert info.shape == (decoded.num_images,)
        assert info.dtype == decoded.quaternions.dtype.name
        assert info.count == decoded.num_images
        expected = {
            "num_cameras": decoded.num_cameras,
            "num_images": decoded.num_images,
            "num_points3D": decoded.num_points3D,
        }
        assert {
            key: info.metadata[key] for key in expected
        } == expected
        assert set(info.metadata) <= {*expected, "num_observations"}
    elif isinstance(decoded, _core.TensorDict):
        assert info.count == len(decoded)
        assert tuple((item.name, item.shape, item.dtype) for item in info.arrays) == tuple(
            (name, decoded[name].shape, decoded[name].dtype.name) for name in decoded
        )
    else:  # pragma: no cover - the all-codec fixture fixes the closed set
        raise AssertionError(f"unhandled inspected result {type(decoded)!r}")


def _fresh_process_inspect_rss(path, format_id, *, expect_error=False):
    if os.environ.get("ASAN_OPTIONS") or "libasan" in os.environ.get(
        "LD_PRELOAD", ""
    ):
        pytest.skip("RSS measurements include AddressSanitizer shadow memory")
    script = """
import gc
import sys
import threading
import time

import psutil
import sceneio
from sceneio.io import inspect as inspect_scene

process = psutil.Process()
gc.collect()
baseline = process.memory_info().rss
peak = [baseline]
running = [True]

def sample():
    while running[0]:
        peak[0] = max(peak[0], process.memory_info().rss)
        time.sleep(0.0005)

thread = threading.Thread(target=sample, daemon=True)
thread.start()
try:
    try:
        value = inspect_scene(sys.argv[1], format=sys.argv[2])
    except Exception:
        if sys.argv[3] != "error":
            raise
    else:
        if sys.argv[3] == "error":
            raise AssertionError("inspection unexpectedly succeeded")
        del value
    peak[0] = max(peak[0], process.memory_info().rss)
finally:
    running[0] = False
    thread.join()
print(max(0, peak[0] - baseline))
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(path),
            format_id,
            "error" if expect_error else "success",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(completed.stdout.strip())


def test_inspect_matches_decoded_metadata_all_39_codecs(tmp_path, buffer_codecs):
    assert len(buffer_codecs) == 36
    for spec in buffer_codecs:
        path = tmp_path / f"inspect-{spec.id}.data"
        path.write_bytes(spec.data)
        info = sceneio.inspect(path, format=spec.id)
        decoded = sceneio.read(path, format=spec.id)
        assert info.format == spec.id
        assert info.datatype == registry.get(spec.id).datatype
        assert info.byte_size == len(spec.data)
        _assert_inspection_matches(info, decoded)
        if spec.id == "pfm":
            assert info.metadata == {"byte_order": "little"}
        elif spec.id == "gaussian_ply":
            assert info.metadata == {
                "sh_degree": decoded.sh_degree,
                "num_rest": decoded.num_rest,
                "byte_order": "little",
            }
        elif spec.id == "compressed_ply":
            assert info.metadata == {
                "encoding": "binary_little_endian",
                "byte_order": "little",
                "chunk_size": 256,
                "num_chunks": 1,
                "sh_degree": decoded.sh_degree,
                "num_rest": decoded.num_rest,
                "chunk_color_ranges": True,
                "position_bits": (11, 10, 11),
                "scale_bits": (11, 10, 11),
                "quaternion_bits": (2, 10, 10, 10),
                "color_bits": (8, 8, 8, 8),
            }
        elif spec.id == "ply":
            assert info.metadata == {
                "encoding": "binary_little_endian",
                "byte_order": "little",
                "properties": (
                    "x",
                    "y",
                    "z",
                    "nx",
                    "ny",
                    "nz",
                    "red",
                    "green",
                    "blue",
                    "intensity",
                ),
                "property_types": (
                    "float",
                    "float",
                    "float",
                    "float",
                    "float",
                    "float",
                    "uchar",
                    "uchar",
                    "uchar",
                    "float",
                ),
                "has_normals": True,
                "has_color": True,
                "color_dtype": "uint8",
                "has_intensity": True,
                "intensity_range": "unknown",
                "vertex_stride": 31,
            }
        elif spec.id == "pcd":
            assert info.metadata == {
                "storage": "binary",
                "fields": (
                    "x",
                    "y",
                    "z",
                    "normal_x",
                    "normal_y",
                    "normal_z",
                    "rgb",
                    "intensity",
                ),
                "sizes": (4, 4, 4, 4, 4, 4, 4, 2),
                "types": ("F", "F", "F", "F", "F", "F", "U", "U"),
                "counts": (1, 1, 1, 1, 1, 1, 1, 1),
                "width": 13,
                "height": 1,
                "organized": False,
                "viewpoint": decoded.viewpoint,
                "has_normals": True,
                "has_color": True,
                "has_intensity": True,
                "intensity_range": "u16",
                "point_stride": 30,
                "compressed_size": 0,
            }
        elif spec.id == "spz":
            assert info.metadata == {
                "version": 3,
                "sh_degree": decoded.sh_degree,
                "fractional_bits": 12,
            }
        elif spec.id == "npy":
            assert info.metadata == {"fortran_order": False}
        elif spec.id == "netpbm":
            assert info.metadata == {"ascii": False, "maxval": decoded.maxval}
        elif spec.id == "png":
            assert info.metadata == {"interlaced": False}
        elif spec.id == "jpeg":
            assert info.metadata == {"precision": 8, "progressive": False}
        elif spec.id == "bmp":
            assert info.metadata == {
                "bits_per_pixel": 32,
                "compression": "BI_BITFIELDS",
                "palette": False,
                "top_down": False,
            }
        elif spec.id == "tga":
            assert info.metadata == {
                "bits_per_pixel": 32,
                "rle": True,
                "palette": False,
                "origin": "bottom_left",
            }
        elif spec.id == "exr":
            assert set(info.metadata["channel_names"]) == {"R", "G", "B", "A"}
        elif spec.id == "xyz":
            assert info.metadata == {
                "columns": 6,
                "has_color": True,
                "has_intensity": False,
                "has_normals": False,
            }
        elif spec.id == "las":
            assert info.metadata == {
                "point_format": 2,
                "has_color": True,
                "has_intensity": True,
            }
        elif spec.id == "splat":
            assert info.metadata == {"sh_degree": 0}
        elif spec.id == "dmb":
            assert info.metadata == {
                "channels": 1,
                "image_type": 1,
                "unit": "unknown",
                "scale_to_meters": 0.0,
                "invalid_policy": "zero",
            }
        elif spec.id == "bal":
            assert info.metadata == {
                "num_cameras": 1,
                "num_images": 1,
                "num_points3D": 1,
                "num_observations": 1,
            }

    nvm = next(spec for spec in buffer_codecs if spec.id == "nvm")
    reconstruction = nvm.reader(nvm.data)
    for format_id, writer in (
        ("colmap_sparse", _core.write_colmap_sparse),
        ("colmap_sparse_txt", _core.write_colmap_txt),
    ):
        path = tmp_path / f"inspect-{format_id}"
        path.mkdir()
        writer(reconstruction, str(path))
        info = sceneio.inspect(path, format=format_id)
        decoded = sceneio.read(path, format=format_id)
        assert info.byte_size == sum(item.stat().st_size for item in path.iterdir())
        _assert_inspection_matches(info, decoded)


def test_inspect_large_npy_reads_only_header(tmp_path):
    header = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        header,
        {"descr": "<f4", "fortran_order": False, "shape": (32 * 1024 * 1024,)},
    )
    path = tmp_path / "large.npy"
    with path.open("wb") as stream:
        stream.write(header.getvalue())
        stream.truncate(stream.tell() + 128 * 1024 * 1024)

    sceneio.inspect(path)
    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.shape == (32 * 1024 * 1024,)
    assert info.dtype == "float32"
    assert info.byte_size > 128 * 1024 * 1024
    assert peak < 256 * 1024
    assert _fresh_process_inspect_rss(path, "npy") < 8 * 1024 * 1024


def test_inspect_large_xyz_streams_with_bounded_python_memory(tmp_path):
    path = tmp_path / "large.xyz"
    block = b"0 0 0\n" * 8192
    repetitions = 256
    with path.open("wb") as stream:
        for _ in range(repetitions):
            stream.write(block)

    sceneio.inspect(path)
    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.count == repetitions * 8192
    assert info.shape == (repetitions * 8192, 3)
    assert info.byte_size == len(block) * repetitions
    assert peak < 256 * 1024
    assert _fresh_process_inspect_rss(path, "xyz") < 8 * 1024 * 1024


def test_inspection_is_immutable_and_bundler_counts_registered_cameras(tmp_path):
    npy_path = tmp_path / "immutable.npy"
    sceneio.write(np.arange(4, dtype=np.int16), npy_path)
    info = sceneio.inspect(npy_path)
    with pytest.raises(TypeError):
        info.metadata["fortran_order"] = True
    with pytest.raises(AttributeError):
        info.shape = (2, 2)

    bundler = tmp_path / "partial.out"
    bundler.write_bytes(
        b"# Bundle file v0.3\n2 0\n"
        + b"0 " * 14
        + b"0\n"
        + b"1 0 0 1 0 0 0 1 0 0 0 1 0 0 0\n"
    )
    decoded = sceneio.read(bundler)
    inspected = sceneio.inspect(bundler)
    assert decoded.num_images == decoded.num_cameras == 1
    assert inspected.count == 1
    assert inspected.metadata["num_images"] == inspected.metadata["num_cameras"] == 1


@pytest.mark.parametrize(
    ("format_id", "contents"),
    [
        ("npy", b"\x93NUMPY\x01"),
        ("npy", b"\x93NUMPY\x02\x00\x01\x00\x10\x00"),
        ("png", b"\x89PNG\r\n\x1a\n"),
        ("flo", b"PIEH"),
        ("splat", b"x"),
    ],
)
def test_inspect_normalizes_truncated_header_errors(tmp_path, format_id, contents):
    path = tmp_path / f"bad-{format_id}.data"
    path.write_bytes(contents)
    with pytest.raises(sceneio.FormatError, match=f"inspecting .* as '{format_id}'"):
        sceneio.inspect(path, format=format_id)


def test_inspect_all_single_file_codecs_reject_truncated_headers(
    tmp_path, buffer_codecs
):
    for spec in buffer_codecs:
        path = tmp_path / f"truncated-{spec.id}.bin"
        # PTS metadata is complete after its short decimal count line; use a
        # genuinely missing header rather than truncating into the first row.
        if spec.id == "pts":
            truncated = b""
        elif spec.id == "g2o":
            # The canonical prefix is a comment and an empty graph is valid;
            # truncate a data-record tag instead.
            truncated = b"VERT"
        else:
            truncated = spec.data[:4]
        path.write_bytes(truncated)
        with pytest.raises(sceneio.FormatError):
            sceneio.inspect(path, format=spec.id)


def test_inspect_colmap_directories_reject_truncated_or_missing_headers(
    tmp_path
):
    binary = tmp_path / "binary"
    binary.mkdir()
    for filename in ("cameras.bin", "images.bin", "points3D.bin"):
        (binary / filename).write_bytes(b"\0" * 4)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(binary, format="colmap_sparse")

    text = tmp_path / "text"
    text.mkdir()
    (text / "cameras.txt").write_bytes(b"# incomplete model\n")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(text, format="colmap_sparse_txt")


def _png_chunk(kind, payload):
    body = kind + payload
    return (
        struct.pack(">I", len(payload))
        + body
        + struct.pack(">I", binascii.crc32(body))
    )


@pytest.mark.parametrize(
    ("format_id", "contents"),
    [
        ("pfm", b"Pf\n1 1\nnan\n" + struct.pack("<f", 0.0)),
        ("hdr", b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n+Y 1 +X 1\n"),
        ("hdr", b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n-Y 1 +X 1\n"),
        (
            "png",
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 200_001, 1, 8, 2, 0, 0, 0))
            + _png_chunk(b"IDAT", b""),
        ),
        (
            "png",
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 16, 3, 0, 0, 0))
            + _png_chunk(b"PLTE", b"\0\0\0")
            + _png_chunk(b"IDAT", b""),
        ),
        (
            "webp",
            b"RIFF"
            + struct.pack("<I", 22)
            + b"WEBPVP8X"
            + struct.pack("<I", 10)
            + bytes(10),
        ),
    ],
)
def test_inspect_rejects_unsupported_header_semantics(tmp_path, format_id, contents):
    path = tmp_path / f"unsupported-{format_id}.data"
    path.write_bytes(contents)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format=format_id)


def test_inspect_rejects_npy_extra_fields_and_excess_dimensions(tmp_path):
    for index, header_dict in enumerate(
        (
            {
                "descr": "<f4",
                "fortran_order": False,
                "shape": (1,),
                "extra": 1,
            },
            {
                "descr": "<f4",
                "fortran_order": False,
                "shape": (1,) * 65,
            },
        )
    ):
        header = io.BytesIO()
        np.lib.format.write_array_header_2_0(header, header_dict)
        path = tmp_path / f"unsupported-{index}.npy"
        path.write_bytes(header.getvalue())
        with pytest.raises(sceneio.FormatError):
            sceneio.inspect(path)


def test_inspect_npy_reuses_core_header_grammar(tmp_path):
    header = (
        b"{'descr': '<f4', 'fortran_order': False, 'shape': (1), }\n"
    )
    path = tmp_path / "noncanonical-singleton.npy"
    path.write_bytes(
        b"\x93NUMPY\x01\x00"
        + struct.pack("<H", len(header))
        + header
        + struct.pack("<f", 3.0)
    )
    decoded = sceneio.read(path)
    info = sceneio.inspect(path)
    np.testing.assert_array_equal(decoded, np.array([3.0], dtype=np.float32))
    assert info.shape == decoded.shape == (1,)
    assert info.dtype == "float32"


def test_inspect_gaussian_ply_matches_big_endian_and_ignores_nonvertex_properties(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "gaussian_ply")
    header_end = spec.data.index(b"end_header\n") + len(b"end_header\n")
    header, body = spec.data[:header_end], spec.data[header_end:]
    big_endian = header.replace(
        b"format binary_little_endian 1.0",
        b"format binary_big_endian 1.0",
    ) + np.frombuffer(body, dtype="<f4").byteswap().tobytes()
    big_path = tmp_path / "big-endian.ply"
    big_path.write_bytes(big_endian)
    big_info = sceneio.inspect(big_path, format="gaussian_ply")
    _assert_inspection_matches(
        big_info, sceneio.read(big_path, format="gaussian_ply")
    )
    assert big_info.metadata["byte_order"] == "big"

    foreign_properties = b"element face 0\n" + b"".join(
        f"property float f_rest_{index}\n".encode() for index in range(9)
    )
    extra_path = tmp_path / "nonvertex-properties.ply"
    extra_path.write_bytes(
        spec.data.replace(b"end_header\n", foreign_properties + b"end_header\n", 1)
    )
    extra_info = sceneio.inspect(extra_path, format="gaussian_ply")
    decoded = sceneio.read(extra_path, format="gaussian_ply")
    _assert_inspection_matches(extra_info, decoded)
    assert extra_info.metadata["sh_degree"] == decoded.sh_degree == 3


@pytest.mark.parametrize(
    "replacement",
    [
        b"element vertex -1",
        b"element vertex 11\nproperty double x",
    ],
)
def test_inspect_gaussian_ply_rejects_invalid_vertex_headers(
    tmp_path, buffer_codecs, replacement
):
    spec = next(item for item in buffer_codecs if item.id == "gaussian_ply")
    payload = spec.data.replace(b"element vertex 11", replacement, 1)
    path = tmp_path / "bad.ply"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="gaussian_ply")


def test_inspect_spz_rejects_invalid_fractional_bits(tmp_path, buffer_codecs):
    spec = next(item for item in buffer_codecs if item.id == "spz")
    raw = bytearray(gzip.decompress(spec.data))
    raw[13] = 0
    path = tmp_path / "bad.spz"
    path.write_bytes(gzip.compress(raw))
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="spz")


@pytest.mark.parametrize("format_id", ["transforms_json", "openmvg"])
def test_inspect_json_error_messages_are_bounded(tmp_path, format_id):
    path = tmp_path / f"bad-{format_id}.json"
    path.write_bytes(b'{"unterminated":"' + b"x" * (32 * 1024 * 1024))
    with pytest.raises(sceneio.FormatError) as caught:
        sceneio.inspect(path, format=format_id)
    assert len(str(caught.value.__cause__)) < 512
    assert (
        _fresh_process_inspect_rss(path, format_id, expect_error=True)
        < 16 * 1024 * 1024
    )


@pytest.mark.parametrize(
    ("format_id", "prefix"),
    [
        ("transforms_json", b'{"frames":[],"padding":['),
        (
            "openmvg",
            b'{"views":[],"intrinsics":[],"extrinsics":[],"structure":[],'
            b'"padding":[',
        ),
    ],
)
def test_inspect_large_valid_json_streams_without_a_dom(
    tmp_path, format_id, prefix
):
    path = tmp_path / f"large-{format_id}.json"
    with path.open("wb") as stream:
        stream.write(prefix)
        for _ in range(1024):
            stream.write(b"0," * 4096)
        stream.write(b"0]}")
    info = sceneio.inspect(path, format=format_id)
    assert info.count == 0
    assert (
        _fresh_process_inspect_rss(path, format_id)
        < 24 * 1024 * 1024
    )


def test_inspect_bundler_header_allocation_is_bounded(tmp_path):
    path = tmp_path / "large.out"
    path.write_bytes(b"x" * (2 * 1024 * 1024))
    tracemalloc.start()
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="bundler")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 256 * 1024


@pytest.mark.parametrize(
    "format_id", ["bal", "bundler", "nvm", "pfm", "tum", "kitti"]
)
def test_inspect_text_token_or_line_caps_bound_mapped_rss(
    tmp_path, format_id
):
    path = tmp_path / f"large-{format_id}.txt"
    path.write_bytes(b"x" * (32 * 1024 * 1024))
    assert (
        _fresh_process_inspect_rss(path, format_id, expect_error=True)
        < 8 * 1024 * 1024
    )


def test_inspect_exr_duplicate_channel_attributes_are_bounded(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "exr")
    payload = spec.data
    offset = 8
    channel_attribute = None
    while payload[offset] != 0:
        start = offset
        name_end = payload.index(b"\0", offset)
        name = payload[offset:name_end]
        type_end = payload.index(b"\0", name_end + 1)
        size_offset = type_end + 1
        size = struct.unpack(
            "<I", payload[size_offset : size_offset + 4]
        )[0]
        offset = size_offset + 4 + size
        if name == b"channels":
            channel_attribute = payload[start:offset]
    assert channel_attribute is not None
    path = tmp_path / "duplicate-channels.exr"
    path.write_bytes(
        payload[:offset] + channel_attribute * 100_000 + payload[offset:]
    )
    with pytest.raises(sceneio.FormatError, match="duplicate channels"):
        sceneio.inspect(path, format="exr")
    assert (
        _fresh_process_inspect_rss(path, "exr", expect_error=True)
        < 8 * 1024 * 1024
    )


def test_inspect_xyz_supports_unicode_paths(tmp_path):
    path = tmp_path / "流-é-🙂.xyz"
    path.write_bytes(b"1 2 3\n")
    info = sceneio.inspect(path, format="xyz")
    assert info.count == 1
    assert info.shape == (1, 3)


def test_inspect_colmap_text_skips_unbounded_observation_lines(tmp_path):
    path = tmp_path / "sparse"
    path.mkdir()
    (path / "cameras.txt").write_bytes(b"# empty\n")
    (path / "images.txt").write_bytes(
        b"1 1 0 0 0 0 0 0 1 image.jpg\n"
        + b"0 " * (16 * 1024 * 1024)
    )
    (path / "points3D.txt").write_bytes(b"")
    info = sceneio.inspect(path, format="colmap_sparse_txt")
    assert info.metadata == {
        "num_cameras": 0,
        "num_images": 1,
        "num_points3D": 0,
    }
    assert (
        _fresh_process_inspect_rss(path, "colmap_sparse_txt")
        < 8 * 1024 * 1024
    )


def test_inspect_nvm_uses_the_formats_token_stream(tmp_path):
    path = tmp_path / "wrapped.nvm"
    path.write_bytes(b"NVM_V3\n1\na.jpg 800\n1 0 0 0 1 2 3 0 0\n0\n0\n")
    decoded = sceneio.read(path, format="nvm")
    info = sceneio.inspect(path, format="nvm")
    assert decoded.num_images == info.count == 1
    assert info.metadata["num_points3D"] == decoded.num_points3D == 0


def test_inspect_nvm_token_cap_matches_reader(tmp_path):
    path = tmp_path / "long-name.nvm"
    name = b"a" * (1024 * 1024 + 1)
    path.write_bytes(
        b"NVM_V3\n1\n"
        + name
        + b" 800 1 0 0 0 1 2 3 0 0\n0\n0\n"
    )
    with pytest.raises(sceneio.FormatError, match="token exceeds"):
        sceneio.read(path, format="nvm")
    with pytest.raises(sceneio.FormatError, match="token exceeds"):
        sceneio.inspect(path, format="nvm")


@pytest.mark.parametrize("format_id", ["transforms_json", "openmvg"])
def test_json_scene_duplicate_root_sections_use_last_value(
    tmp_path, buffer_codecs, format_id
):
    spec = next(item for item in buffer_codecs if item.id == format_id)
    document = spec.data.rstrip()
    suffix = (
        ',"frames":[]}'
        if format_id == "transforms_json"
        else ',"views":[],"structure":[]}'
    )
    payload = document[:-1] + suffix.encode()
    path = tmp_path / f"duplicate-{format_id}.json"
    path.write_bytes(payload)
    decoded = sceneio.read(path, format=format_id)
    info = sceneio.inspect(path, format=format_id)
    expected = decoded.num_images if format_id == "openmvg" else decoded.num_views
    assert info.count == expected == 0


@pytest.mark.parametrize(
    "section", ["views", "intrinsics", "extrinsics", "structure"]
)
def test_inspect_openmvg_rejects_duplicate_map_keys_like_reader(
    tmp_path, buffer_codecs, section
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    document[section].append(document[section][0])
    path = tmp_path / f"duplicate-{section}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="duplicate"):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


def test_inspect_openmvg_rejects_missing_intrinsic_like_reader(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    document["views"][0]["value"]["ptr_wrapper"]["data"]["id_intrinsic"] = (
        0xFFFFFFFE
    )
    path = tmp_path / "missing-intrinsic.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="missing intrinsic"):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


def test_inspect_openmvg_rejects_unknown_observation_view_like_reader(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    document["structure"][0]["value"]["observations"][0]["key"] = 999999
    path = tmp_path / "missing-observation-view.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="not a posed view"):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


@pytest.mark.parametrize("section", ["intrinsics", "extrinsics", "structure"])
def test_inspect_openmvg_requires_map_entry_value_like_reader(
    tmp_path, buffer_codecs, section
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    del document[section][0]["value"]
    path = tmp_path / f"missing-{section}-value.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="missing 'value'"):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


def test_inspect_openmvg_nested_duplicate_uses_last_value(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    value = document["views"][0]["value"]
    compact = json.dumps(document, separators=(",", ":"))
    encoded_value = json.dumps(value, separators=(",", ":"))
    invalid_last = encoded_value[:-1] + ',"ptr_wrapper":null}'
    path = tmp_path / "duplicate-ptr-wrapper.json"
    path.write_text(compact.replace(encoded_value, invalid_last, 1), encoding="utf-8")
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


@pytest.mark.parametrize("section", ["views", "intrinsics"])
def test_inspect_openmvg_nested_duplicate_can_recover_with_last_value(
    tmp_path, buffer_codecs, section
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    value = document[section][0]["value"]
    compact = json.dumps(document, separators=(",", ":"))
    encoded_value = json.dumps(value, separators=(",", ":"))
    needle = '"value":' + encoded_value
    replacement = (
        '"value":{"ptr_wrapper":null},"value":' + encoded_value
    )
    path = tmp_path / f"recover-{section}-value.json"
    path.write_text(compact.replace(needle, replacement, 1), encoding="utf-8")
    decoded = sceneio.read(path, format="openmvg")
    info = sceneio.inspect(path, format="openmvg")
    _assert_inspection_matches(info, decoded)


def test_inspect_openmvg_duplicate_observations_use_last_value(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    observations = document["structure"][0]["value"]["observations"]
    compact = json.dumps(document, separators=(",", ":"))
    encoded = json.dumps(observations, separators=(",", ":"))
    needle = '"observations":' + encoded
    invalid = '[{"key":999999,"value":{"x":[0,0]}}]'
    replacement = '"observations":' + invalid + ',"observations":' + encoded
    path = tmp_path / "recover-observations.json"
    path.write_text(compact.replace(needle, replacement, 1), encoding="utf-8")
    decoded = sceneio.read(path, format="openmvg")
    info = sceneio.inspect(path, format="openmvg")
    _assert_inspection_matches(info, decoded)


def test_inspect_npz_rejects_unsupported_compression_like_reader(tmp_path):
    path = tmp_path / "bzip2.npz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_BZIP2) as archive:
        archive.writestr("a.npy", bytes(_core.write_npy(np.arange(4))))
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="npz")
    with pytest.raises(sceneio.FormatError, match="stored and deflate"):
        sceneio.inspect(path, format="npz")


def test_inspect_npz_skips_unsupported_directory_members_like_reader(tmp_path):
    path = tmp_path / "directory-only.npz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_BZIP2) as archive:
        archive.writestr("folder/", b"")
    decoded = sceneio.read(path, format="npz")
    info = sceneio.inspect(path, format="npz")
    assert list(decoded.keys()) == []
    assert info.count == 0


def test_inspect_npz_rejects_raw_non_utf8_filename_like_reader(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("a.npy", bytes(_core.write_npy(np.arange(4))))
    payload = bytearray(stream.getvalue())
    payload[30] = 0x82
    central = payload.index(b"PK\x01\x02")
    payload[central + 46] = 0x82
    path = tmp_path / "non-utf8.npz"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match="UTF-8"):
        sceneio.read(path, format="npz")
    with pytest.raises(sceneio.FormatError, match="UTF-8"):
        sceneio.inspect(path, format="npz")


@pytest.mark.parametrize("mutate", ["central_name", "local_method"])
def test_inspect_npz_rejects_local_central_disagreement_like_reader(
    tmp_path, mutate
):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("a.npy", bytes(_core.write_npy(np.arange(4))))
    payload = bytearray(stream.getvalue())
    central = payload.index(b"PK\x01\x02")
    if mutate == "central_name":
        payload[central + 46] = ord("b")
    else:
        payload[8:10] = struct.pack("<H", zipfile.ZIP_DEFLATED)
    path = tmp_path / f"{mutate}.npz"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match="local and central"):
        sceneio.read(path, format="npz")
    with pytest.raises(sceneio.FormatError, match="local and central"):
        sceneio.inspect(path, format="npz")


@pytest.mark.parametrize(
    "payload",
    [
        b"P5\n1# width\n 1\n255\n\x00",
        b"P5\n1 1# height\n255\n\x00",
        b"P5\n1 1 255# maxval\n\x00",
    ],
)
def test_inspect_netpbm_matches_inline_comment_grammar(tmp_path, payload):
    path = tmp_path / "comment.pgm"
    path.write_bytes(payload)
    decoded = sceneio.read(path, format="netpbm")
    info = sceneio.inspect(path, format="netpbm")
    _assert_inspection_matches(info, decoded)


def test_inspect_flo_matches_reader_trailing_byte_tolerance(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "flo")
    path = tmp_path / "trailing.flo"
    path.write_bytes(spec.data + b"ignored")
    decoded = sceneio.read(path, format="flo")
    info = sceneio.inspect(path, format="flo")
    _assert_inspection_matches(info, decoded)
    assert info.byte_size == len(spec.data) + len(b"ignored")


def test_inspect_rejects_corrupt_png_metadata_crc(tmp_path, buffer_codecs):
    spec = next(item for item in buffer_codecs if item.id == "png")
    payload = bytearray(spec.data)
    payload[29] ^= 1
    path = tmp_path / "bad-crc.png"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match="CRC"):
        sceneio.inspect(path, format="png")


def test_inspect_png_rejects_duplicate_critical_chunk_like_reader(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "png")
    ihdr_chunk = spec.data[8:33]
    path = tmp_path / "duplicate-ihdr.png"
    path.write_bytes(spec.data[:33] + ihdr_chunk + spec.data[33:])
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="png")
    with pytest.raises(sceneio.FormatError, match="critical chunk"):
        sceneio.inspect(path, format="png")


def test_inspect_rejects_inconsistent_jpeg_sof_length(tmp_path, buffer_codecs):
    spec = next(item for item in buffer_codecs if item.id == "jpeg")
    payload = bytearray(spec.data)
    marker = payload.index(b"\xff\xc0")
    payload[marker + 2 : marker + 4] = struct.pack(">H", 8)
    path = tmp_path / "bad-sof.jpg"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match="SOF length"):
        sceneio.inspect(path, format="jpeg")


def test_inspect_jpeg_rejects_duplicate_sof_like_reader(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "jpeg")
    marker = spec.data.index(b"\xff\xc0")
    length = struct.unpack(">H", spec.data[marker + 2 : marker + 4])[0]
    segment = spec.data[marker : marker + 2 + length]
    path = tmp_path / "duplicate-sof.jpg"
    path.write_bytes(spec.data[:marker] + segment + spec.data[marker:])
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="jpeg")
    with pytest.raises(sceneio.FormatError, match="duplicate SOF"):
        sceneio.inspect(path, format="jpeg")


@pytest.mark.parametrize("mutation", ["long_sos", "unsupported_sof"])
def test_inspect_jpeg_rejects_unsupported_marker_topology_like_reader(
    tmp_path, buffer_codecs, mutation
):
    spec = next(item for item in buffer_codecs if item.id == "jpeg")
    payload = bytearray(spec.data)
    if mutation == "long_sos":
        marker = payload.index(b"\xff\xda")
        payload[marker + 2 : marker + 4] = b"\xff\xff"
    else:
        marker = payload.index(b"\xff\xc0")
        length = struct.unpack(">H", payload[marker + 2 : marker + 4])[0]
        segment = bytearray(payload[marker : marker + 2 + length])
        segment[1] = 0xC3
        payload[marker:marker] = segment
    path = tmp_path / f"{mutation}.jpg"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="jpeg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="jpeg")


def test_inspect_rejects_mismatched_webp_extended_canvas(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "webp")
    chunks = spec.data[12:]
    assert chunks[:4] == b"VP8L"
    height, width = spec.value.height, spec.value.width
    canvas = (
        b"\x10\0\0\0"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    extended_chunks = b"VP8X" + struct.pack("<I", 10) + canvas + chunks
    valid = b"RIFF" + struct.pack("<I", 4 + len(extended_chunks)) + b"WEBP" + extended_chunks
    valid_path = tmp_path / "valid-extended.webp"
    valid_path.write_bytes(valid)
    _assert_inspection_matches(
        sceneio.inspect(valid_path, format="webp"),
        sceneio.read(valid_path, format="webp"),
    )

    invalid = bytearray(valid)
    invalid[24:27] = (width + 10).to_bytes(3, "little")
    invalid_path = tmp_path / "bad-canvas.webp"
    invalid_path.write_bytes(invalid)
    with pytest.raises(sceneio.FormatError, match="canvas"):
        sceneio.inspect(invalid_path, format="webp")


def test_inspect_webp_uses_first_image_bitstream_like_reader(tmp_path):
    first = bytes(
        _core.write_webp(
            _core.image(np.zeros((2, 3, 3), dtype=np.uint8), color_space="srgb")
        )
    )
    second = bytes(
        _core.write_webp(
            _core.image(np.zeros((5, 7, 3), dtype=np.uint8), color_space="srgb")
        )
    )
    chunks = first[12:] + second[12:]
    payload = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WEBP" + chunks
    path = tmp_path / "duplicate-bitstream.webp"
    path.write_bytes(payload)
    decoded = sceneio.read(path, format="webp")
    info = sceneio.inspect(path, format="webp")
    assert (decoded.height, decoded.width) == info.shape[:2] == (2, 3)


def test_inspect_webp_uses_first_extended_canvas_like_reader(tmp_path):
    encoded = bytes(
        _core.write_webp(
            _core.image(np.zeros((2, 3, 3), dtype=np.uint8), color_space="srgb")
        )
    )

    def vp8x(height, width):
        payload = (
            b"\0\0\0\0"
            + (width - 1).to_bytes(3, "little")
            + (height - 1).to_bytes(3, "little")
        )
        return b"VP8X" + struct.pack("<I", len(payload)) + payload

    chunks = vp8x(2, 3) + vp8x(5, 7) + encoded[12:]
    valid = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WEBP" + chunks
    valid_path = tmp_path / "duplicate-canvas-valid.webp"
    valid_path.write_bytes(valid)
    decoded = sceneio.read(valid_path, format="webp")
    info = sceneio.inspect(valid_path, format="webp")
    assert (decoded.height, decoded.width) == info.shape[:2] == (2, 3)

    reversed_chunks = vp8x(5, 7) + vp8x(2, 3) + encoded[12:]
    invalid = (
        b"RIFF"
        + struct.pack("<I", 4 + len(reversed_chunks))
        + b"WEBP"
        + reversed_chunks
    )
    invalid_path = tmp_path / "duplicate-canvas-invalid.webp"
    invalid_path.write_bytes(invalid)
    with pytest.raises(sceneio.FormatError):
        sceneio.read(invalid_path, format="webp")
    with pytest.raises(sceneio.FormatError, match="canvas"):
        sceneio.inspect(invalid_path, format="webp")


def test_inspect_webp_ignores_advisory_extended_alpha_flag(tmp_path):
    encoded = bytes(
        _core.write_webp(
            _core.image(np.zeros((2, 3, 3), dtype=np.uint8), color_space="srgb")
        )
    )
    canvas = b"\x10\0\0\0" + (2).to_bytes(3, "little") + (1).to_bytes(
        3, "little"
    )
    chunks = b"VP8X" + struct.pack("<I", 10) + canvas + encoded[12:]
    payload = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WEBP" + chunks
    path = tmp_path / "advisory-alpha.webp"
    path.write_bytes(payload)
    decoded = sceneio.read(path, format="webp")
    info = sceneio.inspect(path, format="webp")
    assert decoded.channels == info.channels == 3


@pytest.mark.parametrize(
    ("offset", "value"),
    [
        (96, struct.pack("<I", 1)),
        (105, struct.pack("<H", 1)),
    ],
)
def test_inspect_rejects_invalid_las_record_header(
    tmp_path, buffer_codecs, offset, value
):
    spec = next(item for item in buffer_codecs if item.id == "las")
    payload = bytearray(spec.data)
    payload[offset : offset + len(value)] = value
    path = tmp_path / "bad.las"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="las")


def test_inspect_gaussian_ply_has_no_arbitrary_header_line_cap(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "gaussian_ply")
    comments = b"comment metadata\n" * 10_001
    path = tmp_path / "many-comments.ply"
    path.write_bytes(
        spec.data.replace(b"end_header\n", comments + b"end_header\n", 1)
    )
    decoded = sceneio.read(path, format="gaussian_ply")
    info = sceneio.inspect(path, format="gaussian_ply")
    _assert_inspection_matches(info, decoded)


def test_file_sink_guard_failure_does_not_truncate_destination(tmp_path):
    path = tmp_path / "existing.npy"
    path.write_bytes(b"keep this")
    non_contiguous = np.arange(24, dtype=np.float32).reshape(4, 6)[:, ::2]
    with pytest.raises(ValueError):
        _core._write_to_file(_core.write_npy, non_contiguous, path)
    assert path.read_bytes() == b"keep this"

    # The failed scope must restore ordinary buffer output.
    expected = np.arange(8, dtype=np.int32)
    assert bytes(_core.write_npy(expected)).startswith(b"\x93NUMPY")


def test_file_sink_supports_unicode_paths(tmp_path):
    value = np.arange(8, dtype=np.int32)
    path = tmp_path / "流-é.npy"
    _core._write_to_file(_core.write_npy, value, path)
    assert path.read_bytes() == bytes(_core.write_npy(value))


def test_file_sink_completes_multiple_native_write_chunks(tmp_path):
    value = np.arange(1024, dtype=np.float32)
    expected = bytes(_core.write_npy(value))
    path = tmp_path / "chunked.npy"
    chunk = 31
    calls = _core._write_to_file(
        _core.write_npy, value, path, _max_chunk=chunk
    )
    assert calls == (len(expected) + chunk - 1) // chunk
    assert path.read_bytes() == expected


def test_file_sink_accounts_for_partial_native_write_returns(tmp_path):
    value = np.arange(1024, dtype=np.float32)
    expected = bytes(_core.write_npy(value))
    path = tmp_path / "short-write.npy"
    limit = 31
    calls = _core._write_to_file(
        _core.write_npy, value, path, _test_short_write=limit
    )
    assert calls == (len(expected) + limit - 1) // limit
    assert path.read_bytes() == expected


def test_file_sink_closes_and_restores_after_native_error(tmp_path):
    value = np.arange(1024, dtype=np.float32)
    path = tmp_path / "native-error.npy"
    with pytest.raises(RuntimeError, match="file sink write failed"):
        _core._write_to_file(
            _core.write_npy,
            value,
            path,
            _test_short_write=31,
            _test_fail_after=1,
        )
    assert 0 < path.stat().st_size < len(bytes(_core.write_npy(value)))
    assert bytes(_core.write_npy(value)).startswith(b"\x93NUMPY")


def test_file_sink_closes_after_descriptor_failure(tmp_path, monkeypatch):
    class BadFile:
        closed = False

        def fileno(self):
            raise OSError("injected descriptor failure")

        def close(self):
            self.closed = True

    sink = BadFile()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: sink)
    with pytest.raises(OSError, match="injected descriptor failure"):
        _core._write_to_file(
            _core.write_npy, np.arange(8, dtype=np.int32), tmp_path / "bad.npy"
        )
    assert sink.closed
    assert bytes(_core.write_npy(np.arange(8, dtype=np.int32))).startswith(
        b"\x93NUMPY"
    )


def test_file_sink_never_exposes_encoder_buffer_to_python(tmp_path):
    script = """
import builtins
import pathlib
import sys
import numpy as np
from sceneio import _core
real_open = builtins.open
retained = []
class Wrapper:
    def __init__(self, path):
        self.file = real_open(path, "wb", buffering=0)
    def fileno(self):
        return self.file.fileno()
    def write(self, data):
        retained.append(memoryview(data))
        return len(data)
    def close(self):
        self.file.close()
path = pathlib.Path(sys.argv[1])
builtins.open = lambda *args, **kwargs: Wrapper(path)
value = np.arange(1024 * 1024, dtype=np.float32)
expected = bytes(_core.write_npy(value))
_core._write_to_file(_core.write_npy, value, path)
assert not retained
assert path.read_bytes() == expected
"""
    path = tmp_path / "native-sink.npy"
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_file_sink_suppresses_reentrant_path_callbacks(tmp_path):
    script = """
import builtins
import pathlib
import sys
import numpy as np
from sceneio import _core
real_open = builtins.open
events = []
inner = np.arange(17, dtype=np.int16)
inner_bytes = bytes(_core.write_npy(inner))
def reenter(label):
    encoded = _core.write_npy(inner)
    assert bytes(encoded) == inner_bytes
    events.append(label)
class Wrapper:
    def __init__(self, path):
        self.file = real_open(path, "wb", buffering=0)
    def fileno(self):
        reenter("fileno")
        return self.file.fileno()
    def close(self):
        reenter("close")
        self.file.close()
def wrapped_open(path, *args, **kwargs):
    reenter("open")
    return Wrapper(path)
path = pathlib.Path(sys.argv[1])
builtins.open = wrapped_open
outer = np.arange(1024 * 1024, dtype=np.float32)
expected = bytes(_core.write_npy(outer))
_core._write_to_file(_core.write_npy, outer, path)
assert events == ["open", "fileno", "close"]
assert path.read_bytes() == expected
"""
    path = tmp_path / "reentrant.npy"
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("format_id", ["npy", "pfm", "flo"])
def test_registry_prepares_array_protocols_before_file_sink(tmp_path, format_id):
    inner = np.arange(17, dtype=np.int16)
    inner_bytes = bytes(_core.write_npy(inner))
    if format_id == "flo":
        outer = np.arange(24, dtype=np.float32).reshape(3, 4, 2)
        encoder = _core.write_flo
    elif format_id == "pfm":
        outer = np.arange(12, dtype=np.float32).reshape(3, 4)
        encoder = _core.write_pfm
    else:
        outer = np.arange(12, dtype=np.float32).reshape(3, 4)
        encoder = _core.write_npy
    nested = []

    class ReentrantArray:
        def __array__(self, dtype=None, copy=None):
            del dtype, copy
            nested.append(bytes(_core.write_npy(inner)))
            return outer

    path = tmp_path / f"reentrant.{format_id}"
    sceneio.write(ReentrantArray(), path, format=format_id)
    assert nested == [inner_bytes]
    assert path.read_bytes() == bytes(encoder(outer))


def test_registry_prepares_npz_protocols_before_file_sink(tmp_path):
    inner = np.arange(17, dtype=np.int16)
    inner_bytes = bytes(_core.write_npy(inner))
    outer = np.arange(12, dtype=np.float32).reshape(3, 4)
    nested = []

    class ReentrantArray:
        def __array__(self, dtype=None, copy=None):
            del dtype, copy
            nested.append(bytes(_core.write_npy(inner)))
            return outer

    path = tmp_path / "reentrant.npz"
    sceneio.write({"outer": ReentrantArray()}, path, format="npz")
    expected = _core.write_npz(_core.tensor_dict({"outer": outer}))
    assert nested == [inner_bytes]
    assert path.read_bytes() == bytes(expected)


def test_registry_prepare_failure_does_not_truncate_destination(tmp_path):
    class BadArray:
        def __array__(self, dtype=None, copy=None):
            del dtype, copy
            raise RuntimeError("prepare failed")

    path = tmp_path / "existing.npy"
    path.write_bytes(b"keep this")
    with pytest.raises(registry.FormatError, match="prepare failed"):
        sceneio.write(BadArray(), path, format="npy")
    assert path.read_bytes() == b"keep this"
    assert bytes(_core.write_npy(np.arange(4, dtype=np.float32))).startswith(
        b"\x93NUMPY"
    )


def test_registry_uses_mmap_for_every_nonempty_single_file_codec(
    tmp_path, buffer_codecs, monkeypatch
):
    paths = []
    for index, spec in enumerate(buffer_codecs):
        path = tmp_path / f"registry-{index}-{spec.id}.bin"
        path.write_bytes(spec.data)
        paths.append(path)

    original_mmap = mmap.mmap
    mapped_paths = 0

    def tracked_mmap(*args, **kwargs):
        nonlocal mapped_paths
        mapped_paths += 1
        return original_mmap(*args, **kwargs)

    def forbidden_read_bytes(self):
        raise AssertionError(f"whole-file bytes fallback used for {self}")

    monkeypatch.setattr(registry.mmap, "mmap", tracked_mmap)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    for spec, path in zip(buffer_codecs, paths, strict=True):
        value = sceneio.codecs()[spec.id].read(str(path))
        gc.collect()
        assert _fingerprint(value) == _fingerprint(spec.reader(spec.data))
    assert mapped_paths == len(buffer_codecs) == 36


def test_all_buffer_entries_accept_readonly_protocol_exporters(buffer_codecs):
    for spec in buffer_codecs:
        expected = _fingerprint(spec.reader(spec.data))
        readonly_array = np.frombuffer(spec.data, dtype=np.uint8)
        assert not readonly_array.flags.writeable
        for view in (memoryview(spec.data), readonly_array):
            assert _fingerprint(spec.reader(view)) == expected, spec.id


def test_buffer_entry_rejects_writable_wrong_dtype_and_noncontiguous(buffer_codecs):
    spec = buffer_codecs[0]
    wrong = [
        bytearray(spec.data),
        np.frombuffer(spec.data, dtype=np.uint8).copy(),
        np.frombuffer(spec.data, dtype=np.uint8)[::2],
        np.frombuffer(spec.data, dtype=np.uint8).astype(np.int8),
        np.frombuffer(spec.data, dtype=np.uint8).astype(np.uint16),
    ]
    for value in wrong:
        with pytest.raises(ValueError, match="read-only, C-contiguous unsigned-byte buffer"):
            spec.reader(value)


def test_buffer_entry_aliases_exporter_without_native_copy(tmp_path):
    path = tmp_path / "address.bin"
    path.write_bytes(bytes(range(251)) * 4096)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        numpy_view = np.frombuffer(mapped, dtype=np.uint8)
        assert _core._buffer_address(mapped) == numpy_view.__array_interface__["data"][0]
        del numpy_view


def test_all_single_file_codecs_truncated_mmap_matches_bytes(tmp_path, buffer_codecs):
    for spec in buffer_codecs:
        truncated = spec.data[: max(1, len(spec.data) // 3)]
        expected = _outcome(spec.reader, truncated)
        path = tmp_path / f"truncated-{spec.id}.bin"
        path.write_bytes(truncated)
        with (
            path.open("rb") as stream,
            mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
        ):
            decoded = _decode_outcome(spec.reader, mapped)
        gc.collect()
        actual = _finish_outcome(decoded)
        assert actual == expected, spec.id


def test_all_single_file_codecs_mutation_fuzz_mmap_matches_bytes(tmp_path, buffer_codecs):
    """Random malformed inputs cannot become backing-store-dependent.

    Normal CI uses three mutations per codec. The scheduled sanitizer workflow
    raises SCENEIO_MMAP_FUZZ_CASES for the nightly differential fuzz pass.
    """
    cases = int(os.environ.get("SCENEIO_MMAP_FUZZ_CASES", "3"))
    rng = np.random.default_rng(20260723)
    for spec in buffer_codecs:
        for case in range(cases):
            mutated = bytearray(spec.data)
            operation = case % 3
            if operation == 0 and mutated:
                mutated[rng.integers(0, len(mutated))] ^= int(rng.integers(1, 256))
            elif operation == 1 and len(mutated) > 1:
                del mutated[int(rng.integers(1, len(mutated))) :]
            else:
                mutated.extend(rng.integers(0, 256, 7, dtype=np.uint8).tobytes())
            data = bytes(mutated)
            try:
                expected = _outcome(spec.reader, data)
            except Exception as exc:
                raise AssertionError(
                    f"{spec.id} mutation {case} returned an inaccessible record"
                ) from exc
            path = tmp_path / f"fuzz-{spec.id}-{case}.bin"
            path.write_bytes(data)
            with (
                path.open("rb") as stream,
                mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
            ):
                decoded = _decode_outcome(spec.reader, mapped)
            gc.collect()
            actual = _finish_outcome(decoded)
            assert actual == expected, (spec.id, case, operation)


def test_all_single_file_codecs_empty_path_matches_empty_bytes(tmp_path, buffer_codecs):
    """The portable empty-file fallback preserves each codec's exact behavior."""
    for spec in buffer_codecs:
        path = tmp_path / f"empty-{spec.id}.bin"
        path.touch()
        expected = _outcome(spec.reader, b"")
        actual = _outcome(sceneio.codecs()[spec.id].read, str(path))
        assert actual == expected, spec.id


@pytest.mark.parametrize(
    "header",
    [
        b"ply\nformat\nend_header\n",
        b"ply\nelement\nend_header\n",
        b"ply\nelement vertex nope\nend_header\n",
        b"ply\nelement vertex 1\nproperty\nend_header\n",
    ],
)
def test_gaussian_ply_short_header_lines_raise(header):
    with pytest.raises(ValueError, match="PLY: malformed"):
        _core.read_gaussian_ply(header)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (b"element vertex 11", b"element vertex 11junk", "malformed vertex count"),
        (
            b"format binary_little_endian 1.0",
            b"format binary_little_endian 9.9",
            "unsupported format version",
        ),
        (
            b"format binary_little_endian 1.0\n",
            b"",
            "missing format header",
        ),
        (
            b"format binary_little_endian 1.0\n",
            b"format binary_little_endian 1.0\nformat binary_little_endian 1.0\n",
            "duplicate format header",
        ),
    ],
)
def test_gaussian_ply_rejects_malformed_format_declarations(
    buffer_codecs, old, new, message
):
    spec = next(item for item in buffer_codecs if item.id == "gaussian_ply")
    assert old in spec.data
    payload = spec.data.replace(old, new, 1)
    with pytest.raises(ValueError, match=message):
        _core.read_gaussian_ply(payload)


@pytest.mark.parametrize("failure", [OSError, ValueError])
def test_mmap_failure_falls_back_to_same_open_stream(tmp_path, monkeypatch, failure):
    array = np.arange(24, dtype=np.float32).reshape(4, 6)
    path = tmp_path / "fallback.npy"
    path.write_bytes(_core.write_npy(array))
    attempts = 0

    def unavailable(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise failure("mapping unavailable")

    def forbidden_read_bytes(self):
        raise AssertionError(f"path was reopened through read_bytes: {self}")

    monkeypatch.setattr(registry.mmap, "mmap", unavailable)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    np.testing.assert_array_equal(sceneio.read(path), array)
    assert attempts == 1


def _traced_peak(call):
    tracemalloc.start()
    try:
        value = call()
        _, peak = tracemalloc.get_traced_memory()
        return value, peak
    finally:
        tracemalloc.stop()


def test_file_sink_does_not_allocate_output_sized_python_bytes(tmp_path):
    array = np.arange(4 * 1024 * 1024, dtype=np.float32)
    expected = bytes(_core.write_npy(array))
    path = tmp_path / "large-write.npy"

    buffered, bytes_peak = _traced_peak(lambda: _core.write_npy(array))
    _, sink_peak = _traced_peak(
        lambda: _core._write_to_file(_core.write_npy, array, path)
    )
    assert bytes(buffered) == expected
    assert path.read_bytes() == expected
    assert bytes_peak >= len(expected) * 0.9
    assert sink_peak < len(expected) / 8


def test_mmap_read_does_not_allocate_whole_file_bytes(tmp_path):
    """A 16 MiB .npy proves the adapter/caster do not copy the input buffer."""
    array = np.arange(4 * 1024 * 1024, dtype=np.float32)
    path = tmp_path / "large.npy"
    path.write_bytes(_core.write_npy(array))
    file_size = path.stat().st_size

    slow, bytes_peak = _traced_peak(lambda: _core.read_npy(path.read_bytes()))
    fast, mmap_peak = _traced_peak(lambda: sceneio.read(path))
    np.testing.assert_array_equal(fast, slow)
    assert bytes_peak >= file_size * 0.9
    assert mmap_peak < file_size / 8


@pytest.mark.skipif(os.name != "nt", reason="Windows share-mode locked-file edge")
def test_locked_file_fails_cleanly_on_windows(tmp_path):
    import ctypes
    from ctypes import wintypes

    path = tmp_path / "locked.npy"
    path.write_bytes(_core.write_npy(np.arange(4, dtype=np.float32)))
    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(str(path), 0x80000000, 0, None, 3, 0x80, None)
    invalid = wintypes.HANDLE(-1).value
    assert handle != invalid
    try:
        with pytest.raises(sceneio.FormatError) as caught:
            sceneio.read(path)
        assert isinstance(caught.value.__cause__, PermissionError)
    finally:
        assert close_handle(handle)


def test_magic_detection_reads_only_prefix(tmp_path, monkeypatch):
    path = tmp_path / "extensionless"
    path.write_bytes(_core.write_npy(np.arange(8, dtype=np.float32)))
    original = Path.open
    reads = []

    class TrackingReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            reads.append(size)
            return self.stream.read(size)

    def tracked_open(self, *args, **kwargs):
        stream = original(self, *args, **kwargs)
        return TrackingReader(stream) if self == path else stream

    monkeypatch.setattr(Path, "open", tracked_open)
    assert sceneio.detect(path) == "npy"
    assert reads == [16]
