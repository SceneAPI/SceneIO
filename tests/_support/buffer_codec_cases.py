"""Deterministic buffer-codec cases shared by cross-codec behavior suites."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from _support.codec_cases import BUFFER_CASES
from sceneio import _core
from sceneio._posed_views import posed_views_from_storage


@dataclass(frozen=True, slots=True)
class BufferCodecCase:
    """One complete in-memory codec round-trip case."""

    id: str
    reader: object
    writer: object
    value: object
    public_value: object
    data: bytes


# Preserve the original test_io_mmap.py traversal order while the shared
# builder is adopted by each behavior suite. Some mutation tests consume one
# seeded random stream across this order, so reordering would change coverage.
BUFFER_CODEC_CASE_IDS = (
    "pfm",
    "gaussian_ply",
    "compressed_ply",
    "sog",
    "ksplat",
    "spz",
    "transforms_json",
    "tum",
    "kitti",
    "euroc_state",
    "opencv_yaml",
    "opencv_xml",
    "ros_camera_info",
    "kalibr",
    "g2o",
    "npy",
    "npz",
    "safetensors",
    "netpbm",
    "png",
    "jpeg",
    "bmp",
    "tga",
    "hdr",
    "exr",
    "webp",
    "y4m",
    "webm",
    "theora",
    "animated_webp",
    "apng",
    "xyz",
    "pts",
    "ply",
    "ply_mesh",
    "stl",
    "off",
    "glb",
    "pcd",
    "las",
    "laz",
    "flo",
    "dmb",
    "bundler",
    "bal",
    "nvm",
    "openmvg",
    "splat",
    "colmap_mvs_depth",
    "colmap_mvs_normal",
    "colmap_mvs_consistency",
    "colmap_fused_visibility",
)


def build_buffer_codec_cases() -> tuple[BufferCodecCase, ...]:
    """Build the 52 deterministic cases used by buffer behavior sweeps."""
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
    image_rgba = _core.image(
        rgba,
        color_space="srgb",
        alpha_mode="straight",
    )
    image_u16 = _core.image(rgb16, color_space="srgb")
    image_rgba16 = _core.image(
        rgba16,
        color_space="srgb",
        alpha_mode="straight",
    )
    image_f32 = _core.image(linear, color_space="linear")
    image_f32_rgba = _core.image(
        linear_rgba,
        color_space="linear",
        alpha_mode="premultiplied",
    )
    positions = rng.random((13, 3), dtype=np.float32) * 10
    points_xyz = _core.point_cloud(
        positions,
        colors=rng.integers(0, 256, (13, 3), dtype=np.uint8),
    )
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
    mesh = _core.mesh(
        rng.standard_normal((13, 3)).astype(np.float32),
        np.array([0, 4, 7], np.uint64),
        np.array([0, 1, 2, 3, 0, 3, 4], np.uint64),
        vertex_normals=rng.standard_normal((13, 3)).astype(np.float32),
        corner_normals=rng.standard_normal((7, 3)).astype(np.float32),
        vertex_uvs=rng.standard_normal((13, 2)).astype(np.float32),
        corner_uvs=rng.standard_normal((7, 2)).astype(np.float32),
        vertex_colors=rng.integers(0, 256, (13, 4), dtype=np.uint8),
        corner_colors=rng.integers(0, 256, (7, 4), dtype=np.uint8),
        primitive_offsets=np.array([0, 1, 2], np.uint64),
        primitive_materials=np.array([2, -1], np.int32),
        coordinate_frame="opengl",
        scale_to_meters=0.01,
    )
    mesh_stl = _core.mesh(
        np.array(
            [
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
                [0, 0, 1],
                [1, 0, 1],
                [0, 1, 1],
            ],
            np.float32,
        ),
        np.array([0, 3, 6], np.uint64),
        np.arange(6, dtype=np.uint64),
        corner_normals=np.array(
            [[0, 0, 1]] * 3 + [[0, 0, -1]] * 3,
            np.float32,
        ),
    )
    mesh_off = _core.mesh(
        np.array(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            np.float32,
        ),
        np.array([0, 4], np.uint64),
        np.array([0, 1, 2, 3], np.uint64),
        vertex_normals=np.array([[0, 0, 1]] * 4, np.float32),
        vertex_uvs=np.array(
            [[0, 0], [1, 0], [1, 1], [0, 1]],
            np.float32,
        ),
        vertex_colors=np.array(
            [
                [255, 0, 0, 255],
                [0, 255, 0, 255],
                [0, 0, 255, 255],
                [255, 255, 255, 255],
            ],
            np.uint8,
        ),
    )
    mesh_glb = _core.mesh(
        np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            np.float32,
        ),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        vertex_normals=np.array([[0, 0, 1]] * 3, np.float32),
        vertex_uvs=np.array([[0, 0], [1, 0], [0, 1]], np.float32),
        vertex_colors=np.array(
            [
                [255, 0, 0, 255],
                [0, 255, 0, 255],
                [0, 0, 255, 255],
            ],
            np.uint8,
        ),
        coordinate_frame="opengl",
    )
    scene_graph = _core.scene_graph(
        ["node"],
        meshes=[mesh_glb],
        mesh_primitive_offsets=np.array([0, 1], np.uint64),
        mesh_names=["triangle"],
        node_payload_kinds=["mesh"],
        node_payload_indices=np.array([0], np.uint64),
        node_child_offsets=np.array([0, 0], np.uint64),
        node_children=np.array([], np.uint64),
        node_local_transforms=np.eye(4, dtype=np.float64)[None],
        scene_root_offsets=np.array([0, 1], np.uint64),
        scene_roots=np.array([0], np.uint64),
        scene_names=["scene"],
        default_scene=0,
    )
    flow = rng.standard_normal((5, 6, 2)).astype(np.float32)
    flow_field = _core.flow_field(flow)
    depth = _core.depth_map(
        rng.standard_normal((5, 6)).astype(np.float32),
        unit="unknown",
        invalid_policy="zero",
    )
    colmap_depth = _core.depth_map(
        rng.standard_normal((5, 6)).astype(np.float32),
        unit="unknown",
        invalid_policy="nonpositive",
        depth_convention="camera_z",
    )
    colmap_normal = _core.normal_map(
        rng.standard_normal((5, 6, 3)).astype(np.float32)
    )
    colmap_consistency = _core.consistency_graph(
        5,
        6,
        np.array([0, 2, 4], np.uint32),
        np.array([1, 3, 5], np.uint32),
        np.array([0, 2, 2, 5], np.uint64),
        np.array([4, 1, 7, 2, 0], np.uint32),
    )
    colmap_visibility = _core.point_visibility(
        np.array([0, 2, 2, 3], np.uint64),
        np.array([3, 1, 7], np.uint32),
    )
    sequence_y = rng.integers(0, 256, (4, 5, 7), dtype=np.uint8)
    sequence_u = rng.integers(0, 256, (4, 3, 4), dtype=np.uint8)
    sequence_v = rng.integers(0, 256, (4, 3, 4), dtype=np.uint8)
    empty_timing = np.empty(0, np.int64)
    image_sequence = _core.image_sequence_yuv(
        sequence_y,
        sequence_u,
        sequence_v,
        empty_timing,
        empty_timing,
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
    image_sequence_theora = _core.image_sequence_yuv(
        sequence_y,
        sequence_u,
        sequence_v,
        empty_timing,
        empty_timing,
        "420",
        "unspecified",
        "unknown",
        "unknown",
        "progressive",
        25,
        1,
        1,
        1,
    )
    packed_frames = rng.integers(
        0, 256, (4, 5, 7, 4), dtype=np.uint8
    )
    packed_frames[..., 3] = rng.integers(
        1, 256, (4, 5, 7), dtype=np.uint8
    )
    packed_durations = (
        np.arange(1, 5, dtype=np.int64) * 10_000_000
    )
    packed_timestamps = np.concatenate(
        [
            np.zeros(1, np.int64),
            np.cumsum(packed_durations[:-1]),
        ]
    )
    packed_sequence = _core.image_sequence_packed(
        packed_frames,
        packed_timestamps,
        packed_durations,
        "srgb",
        "straight",
        None,
        2,
        np.array([1, 2, 3, 4], np.uint8),
    )
    packed_sequence_apng = _core.image_sequence_packed(
        packed_frames,
        packed_timestamps,
        packed_durations,
        "srgb",
        "straight",
        None,
        2,
    )
    packed_sequence_webm = _core.image_sequence_packed(
        np.ascontiguousarray(packed_frames[..., :3]),
        packed_timestamps,
        packed_durations,
        "srgb",
        "none",
        None,
        None,
        None,
    )
    tensor = rng.standard_normal((4, 5, 3)).astype(np.float32)
    tensors = _core.tensor_dict(
        {"a": tensor, "b": np.arange(9, dtype=np.int16)}
    )
    gaussians = _core.gaussian_cloud(
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 4)).astype(np.float32),
        rng.standard_normal(11).astype(np.float32),
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 45)).astype(np.float32),
    )
    gaussians_ksplat = _core.gaussian_cloud(
        np.asarray(gaussians.means),
        np.asarray(gaussians.scales),
        np.asarray(gaussians.quaternions),
        np.asarray(gaussians.opacities),
        np.asarray(gaussians.sh_dc),
        np.asarray(gaussians.sh_rest)[:, :24],
    )
    gaussians_splat = _core.gaussian_cloud(
        np.asarray(gaussians.means),
        np.asarray(gaussians.scales),
        np.asarray(gaussians.quaternions),
        np.asarray(gaussians.opacities),
        np.asarray(gaussians.sh_dc),
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
        b'{"camera_model":"PINHOLE","fl_x":500,"fl_y":510,"cx":320,'
        b'"cy":240,"w":640,"h":480,"frames":[{"file_path":"a.png",'
        b'"transform_matrix":[[1,0,0,1],[0,1,0,2],[0,0,1,3],'
        b"[0,0,0,1]]}]}"
    )
    tum = _core.read_tum(b"0 1 2 3 0 0 0 1\n")
    kitti = _core.read_kitti(b"1 0 0 1 0 1 0 2 0 0 1 3\n")
    public_poses = {
        "transforms_json": posed_views_from_storage(
            transforms, source_profile="transforms_json"
        ),
        "tum": posed_views_from_storage(tum, source_profile="tum"),
        "kitti": posed_views_from_storage(kitti, source_profile="kitti"),
    }
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
        [
            [
                [500.0, 0.0, 320.0],
                [0.0, 510.0, 240.0],
                [0.0, 0.0, 1.0],
            ]
        ]
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
            [
                [
                    [500.0, 0.0, 320.0, 0.0],
                    [0.0, 510.0, 240.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ]
            ]
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

    def case(codec_id, reader, writer, value, *, public_value=None):
        return BufferCodecCase(
            codec_id,
            reader,
            writer,
            value,
            value if public_value is None else public_value,
            bytes(writer(value)),
        )

    cases = (
        case("pfm", _core.read_pfm, _core.write_pfm, tensor),
        case(
            "gaussian_ply",
            _core.read_gaussian_ply,
            _core.write_gaussian_ply,
            gaussians,
        ),
        case(
            "compressed_ply",
            _core.read_compressed_ply,
            _core.write_compressed_ply,
            gaussians,
        ),
        case("sog", _core.read_sog, _core.write_sog, gaussians),
        case(
            "ksplat",
            _core.read_ksplat,
            _core.write_ksplat,
            gaussians_ksplat,
        ),
        case("spz", _core.read_spz, _core.write_spz, gaussians),
        case(
            "transforms_json",
            _core.read_transforms_json,
            _core.write_transforms_json,
            transforms,
            public_value=public_poses["transforms_json"],
        ),
        case(
            "tum",
            _core.read_tum,
            _core.write_tum,
            tum,
            public_value=public_poses["tum"],
        ),
        case(
            "kitti",
            _core.read_kitti,
            _core.write_kitti,
            kitti,
            public_value=public_poses["kitti"],
        ),
        case(
            "euroc_state",
            _core.read_euroc_state,
            _core.write_euroc_state,
            state_trajectory,
        ),
        case(
            "opencv_yaml",
            _core.read_opencv_yaml,
            _core.write_opencv_yaml,
            camera_rig,
        ),
        case(
            "opencv_xml",
            _core.read_opencv_xml,
            _core.write_opencv_xml,
            camera_rig,
        ),
        case(
            "ros_camera_info",
            _core.read_ros_camera_info,
            _core.write_ros_camera_info,
            ros_camera_rig,
        ),
        case(
            "kalibr",
            _core.read_kalibr,
            _core.write_kalibr,
            kalibr_rig,
        ),
        case("g2o", _core.read_g2o, _core.write_g2o, pose_graph),
        case("npy", _core.read_npy, _core.write_npy, tensor),
        case("npz", _core.read_npz, _core.write_npz, tensors),
        case(
            "safetensors",
            _core.read_safetensors,
            _core.write_safetensors,
            tensors,
        ),
        case(
            "netpbm",
            _core.read_netpbm,
            _core.write_netpbm,
            image_u16,
        ),
        case("png", _core.read_png, _core.write_png, image_rgba16),
        case("jpeg", _core.read_jpeg, _core.write_jpeg, image_u8),
        case("bmp", _core.read_bmp, _core.write_bmp, image_rgba),
        case("tga", _core.read_tga, _core.write_tga, image_rgba),
        case("hdr", _core.read_hdr, _core.write_hdr, image_f32),
        case("exr", _core.read_exr, _core.write_exr, image_f32_rgba),
        case("webp", _core.read_webp, _core.write_webp, image_rgba),
        case("y4m", _core.read_y4m, _core.write_y4m, image_sequence),
        case("webm", _core.read_webm, _core.write_webm, packed_sequence_webm),
        case(
            "theora",
            _core.read_theora,
            _core.write_theora,
            image_sequence_theora,
        ),
        case(
            "animated_webp",
            _core.read_animated_webp,
            _core.write_animated_webp,
            packed_sequence,
        ),
        case(
            "apng",
            _core.read_apng,
            _core.write_apng,
            packed_sequence_apng,
        ),
        case("xyz", _core.read_xyz, _core.write_xyz, points_xyz),
        case("pts", _core.read_pts, _core.write_pts, points_pts),
        case("ply", _core.read_ply, _core.write_ply, points_ply),
        case("ply_mesh", _core.read_ply_mesh, _core.write_ply_mesh, mesh),
        case("stl", _core.read_stl, _core.write_stl, mesh_stl),
        case("off", _core.read_off, _core.write_off, mesh_off),
        case("glb", _core.read_glb, _core.write_glb, scene_graph),
        case("pcd", _core.read_pcd, _core.write_pcd, points_pcd),
        case("las", _core.read_las, _core.write_las, points_las),
        case("laz", _core.read_laz, _core.write_laz, points_las),
        case("flo", _core.read_flo, _core.write_flo, flow_field),
        case("dmb", _core.read_dmb, _core.write_dmb, depth),
        case(
            "bundler",
            _core.read_bundler,
            _core.write_bundler,
            reconstruction,
        ),
        case(
            "bal",
            _core.read_bal,
            _core.write_bal,
            bal_reconstruction,
        ),
        case("nvm", _core.read_nvm, _core.write_nvm, reconstruction),
        case(
            "openmvg",
            _core.read_openmvg,
            _core.write_openmvg,
            reconstruction,
        ),
        case("splat", _core.read_splat, _core.write_splat, gaussians_splat),
        case(
            "colmap_mvs_depth",
            _core.read_colmap_mvs_depth,
            _core.write_colmap_mvs_depth,
            colmap_depth,
        ),
        case(
            "colmap_mvs_normal",
            _core.read_colmap_mvs_normal,
            _core.write_colmap_mvs_normal,
            colmap_normal,
        ),
        case(
            "colmap_mvs_consistency",
            _core.read_colmap_mvs_consistency,
            _core.write_colmap_mvs_consistency,
            colmap_consistency,
        ),
        case(
            "colmap_fused_visibility",
            _core.read_colmap_fused_visibility,
            _core.write_colmap_fused_visibility,
            colmap_visibility,
        ),
    )
    observed = tuple(item.id for item in cases)
    if observed != BUFFER_CODEC_CASE_IDS:
        raise RuntimeError("buffer case traversal order changed")
    if frozenset(observed) != frozenset(item.id for item in BUFFER_CASES):
        raise RuntimeError("buffer case catalog coverage changed")
    return cases


__all__ = [
    "BUFFER_CODEC_CASE_IDS",
    "BufferCodecCase",
    "build_buffer_codec_cases",
]
