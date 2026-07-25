"""Private numpy-only smoke exercised against each built wheel.

Keep this module free of test-only dependencies: cibuildwheel installs only the
wheel and NumPy before invoking it on Windows, Linux, and macOS.
"""

from __future__ import annotations

import gc
import mmap
import tempfile
from pathlib import Path

import numpy as np

import sceneio
from sceneio import _core


def _pfm_and_typed_depth(root: Path, values: np.ndarray) -> None:
    encoded = _core.write_pfm(values)
    assert np.array_equal(_core.read_pfm(memoryview(encoded)), values)
    path = root / "values.pfm"
    path.write_bytes(encoded)
    assert np.array_equal(sceneio.read(path), values)
    info = sceneio.inspect(path)
    assert info.shape == values.shape
    assert info.dtype == "float32"
    partial = sceneio.read_partial(path, window=(1, 3, 1, 4))
    assert np.array_equal(partial, values[1:3, 1:4])
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        owned = _core.read_pfm(mapped)
    path.unlink()
    assert np.array_equal(owned, values)

    pfm_encoding = sceneio.DepthEncoding("meters", 1.0, "none")
    pfm_depth = _core.depth_map(values)
    typed_pfm = root / "typed.pfm"
    sceneio.write_depth(pfm_depth, typed_pfm, encoding=pfm_encoding)
    assert np.array_equal(
        sceneio.read_depth(typed_pfm, encoding=pfm_encoding).depth,
        values,
    )
    assert (
        sceneio.inspect_depth(typed_pfm, encoding=pfm_encoding).metadata[
            "header_scale"
        ]
        == -1.0
    )
    assert isinstance(sceneio.read(typed_pfm), np.ndarray)

    png_encoding = sceneio.DepthEncoding("millimeters", 0.001, "zero")
    png_depth = _core.depth_map(
        values,
        unit="millimeters",
        invalid_policy="zero",
    )
    typed_png = root / "typed.png"
    sceneio.write_depth(png_depth, typed_png, encoding=png_encoding)
    assert np.array_equal(
        sceneio.read_depth(typed_png, encoding=png_encoding).depth,
        values,
    )
    png_info = sceneio.inspect_depth(typed_png, encoding=png_encoding)
    assert png_info.dtype == "float32"
    assert png_info.metadata["stored_dtype"] == "uint16"
    assert isinstance(sceneio.read(typed_png), _core.Image)

    exr_encoding = sceneio.DepthEncoding("meters", 1.0, "none", "Z")
    typed_exr = root / "typed.exr"
    sceneio.write_depth(pfm_depth, typed_exr, encoding=exr_encoding)
    assert np.array_equal(
        sceneio.read_depth(typed_exr, encoding=exr_encoding).depth,
        values,
    )
    exr_info = sceneio.inspect_depth(typed_exr, encoding=exr_encoding)
    assert exr_info.dtype == "float32"
    assert exr_info.metadata["channel_name"] == "Z"
    assert isinstance(sceneio.read(typed_exr), _core.Image)


def _mapped_safetensors(root: Path, values: np.ndarray) -> None:
    path = root / "values.safetensors"
    sceneio.write({"x": values}, path)
    record = sceneio.read(path)
    assert np.array_equal(record["x"], values)
    assert not record["x"].flags.writeable
    assert sceneio.inspect(path).arrays[0].shape == values.shape
    selected = sceneio.read_partial(path, slices={"x": (1, 3)})
    assert np.array_equal(selected["x"], values[1:3])
    del record, selected
    gc.collect()
    path.unlink()


def _point_depth_and_flow(root: Path, values: np.ndarray) -> None:
    points = root / "points.pts"
    sceneio.write(_core.point_cloud(values[:, :3]), points)
    assert sceneio.inspect(points).count == 3
    selected = sceneio.read_partial(points, points=(1, 3))
    assert np.array_equal(selected.positions, values[1:3, :3])

    ply = root / "points.ply"
    ply_record = _core.point_cloud(
        values[:, :3],
        colors=np.arange(9, dtype=np.uint8).reshape(3, 3),
    )
    ply.write_bytes(_core.write_ply(ply_record, "binary_big_endian"))
    assert sceneio.detect(ply) == "ply"
    assert np.array_equal(sceneio.read(ply).positions, values[:, :3])
    assert np.array_equal(
        sceneio.read_partial(ply, points=(1, 3)).colors,
        ply_record.colors[1:3],
    )
    assert sceneio.inspect(ply).metadata["byte_order"] == "big"

    pcd = root / "points.pcd"
    pcd_record = _core.point_cloud(
        values[:, :3],
        colors=np.arange(9, dtype=np.uint8).reshape(3, 3),
        width=1,
        height=3,
        viewpoint=np.asarray(
            [1, 2, 3, 1, 0, 0, 0],
            dtype=np.float64,
        ),
    )
    pcd.write_bytes(_core.write_pcd(pcd_record, "binary_compressed"))
    assert sceneio.detect(pcd) == "pcd"
    pcd_decoded = sceneio.read(pcd)
    assert np.array_equal(pcd_decoded.positions, values[:, :3])
    assert np.array_equal(pcd_decoded.colors, pcd_record.colors)
    assert (pcd_decoded.width, pcd_decoded.height) == (1, 3)
    assert pcd_decoded.viewpoint == pcd_record.viewpoint
    assert sceneio.inspect(pcd).metadata["storage"] == "binary_compressed"

    pcd.write_bytes(_core.write_pcd(pcd_record, "binary"))
    assert np.array_equal(
        sceneio.read_partial(pcd, points=(1, 3)).colors,
        pcd_record.colors[1:3],
    )

    depth_values = np.arange(20, dtype=np.float32).reshape(4, 5)
    depth = _core.depth_map(
        depth_values,
        unit="unknown",
        invalid_policy="zero",
    )
    dmb = root / "depth.dmb"
    sceneio.write(depth, dmb)
    assert np.array_equal(sceneio.read(dmb).depth, depth_values)
    assert sceneio.inspect(dmb).shape == (4, 5)
    window = sceneio.read_partial(dmb, window=(1, 4, 2, 5))
    assert np.array_equal(window.depth, depth_values[1:4, 2:5])

    flow = _core.flow_field(np.zeros((2, 3, 2), np.float32))
    assert sceneio.FlowField is _core.FlowField
    assert flow.vectors.shape == (2, 3, 2)
    assert flow.component_order == "uv"
    flo = root / "flow.flo"
    sceneio.write_flow(flow, flo)
    decoded = sceneio.read_flow(flo)
    assert np.array_equal(decoded.vectors, flow.vectors)
    assert sceneio.inspect_flow(flo).metadata["unit"] == "pixels"


def _reconstruction_and_images(root: Path) -> None:
    bal_bytes = (
        b"1 1 1\n"
        b"0 0 10.5 20.25\n"
        b"0\n0\n0\n1\n2\n3\n800\n0.5\n0.25\n"
        b"1.5\n-2.5\n3.5\n"
    )
    reconstruction = _core.read_bal(bal_bytes)
    bal = root / "problem.bal"
    sceneio.write(reconstruction, bal)
    assert sceneio.inspect(bal).metadata["num_observations"] == 1
    assert sceneio.read(bal).num_points3D == 1

    pixels = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    image = _core.image(pixels, color_space="srgb")
    for suffix in (".bmp", ".tga"):
        path = root / f"image{suffix}"
        sceneio.write(image, path)
        assert np.array_equal(sceneio.read(path).pixels, pixels)
        assert sceneio.inspect(path).shape == (3, 4, 3)


def _state_trajectory(root: Path) -> None:
    timestamps = np.array(
        [1_403_636_580_000_000_000, 1_403_636_580_005_000_000],
        dtype=np.int64,
    )
    positions = np.arange(6, dtype=np.float64).reshape(2, 3)
    quaternions = np.array(
        [[1.0, 0.0, 0.0, 0.0], [0.5, 0.5, 0.5, 0.5]],
        dtype=np.float64,
    )
    zeros = np.zeros((2, 3), dtype=np.float64)
    trajectory = _core.state_trajectory(
        timestamps,
        positions,
        quaternions,
        zeros,
        zeros,
        zeros,
    )
    path = root / "euroc.csv"
    sceneio.write(trajectory, path, format="euroc_state")
    assert sceneio.detect(path) == "euroc_state"
    decoded = sceneio.read(path)
    assert np.array_equal(decoded.timestamps_ns, timestamps)
    assert np.array_equal(decoded.positions, positions)
    assert sceneio.inspect(path).count == 2
    selected = sceneio.read_partial(path, states=(1, 2))
    assert np.array_equal(selected.timestamps_ns, timestamps[1:2])


def _camera_calibration(root: Path) -> None:
    matrix = np.array(
        [[[500.0, 0.0, 320.0], [0.0, 510.0, 240.0], [0.0, 0.0, 1.0]]]
    )
    rig = _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 4], np.uint64),
        np.array([0.1, -0.2, 0.01, 0.02]),
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
        has_extrinsics=np.zeros(1, np.uint8),
        camera_matrices=matrix,
    )
    assert sceneio.CameraRig is _core.CameraRig
    for format_id in ("opencv_yaml", "opencv_xml"):
        path = root / format_id
        sceneio.write(rig, path, format=format_id)
        assert sceneio.detect(path) == format_id
        decoded = sceneio.read(path)
        assert np.array_equal(decoded.camera_matrices, matrix)
        assert sceneio.inspect(path).count == 1

    ros_rig = _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 4], np.uint64),
        np.array([0.1, -0.2, 0.01, 0.02]),
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
        has_extrinsics=np.zeros(1, np.uint8),
        camera_matrices=matrix,
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
    ros = root / "ros-camera-info"
    sceneio.write(ros_rig, ros, format="ros_camera_info")
    assert sceneio.detect(ros) == "ros_camera_info"
    assert np.array_equal(sceneio.read(ros).projection_matrices, ros_rig.projection_matrices)

    kalibr = root / "kalibr"
    kalibr.write_bytes(
        b"cam0:\n"
        b"  camera_model: pinhole\n"
        b"  intrinsics: [500, 510, 320, 240]\n"
        b"  distortion_model: radtan\n"
        b"  distortion_coeffs: [0.1, -0.2, 0.01, 0.02]\n"
        b"  resolution: [640, 480]\n"
        b"  rostopic: /cam0/image_raw\n"
        b"  T_cam_imu:\n"
        b"  - [1, 0, 0, 0]\n"
        b"  - [0, 1, 0, 0]\n"
        b"  - [0, 0, 1, 0]\n"
        b"  - [0, 0, 0, 1]\n"
    )
    decoded = sceneio.read(kalibr)
    assert decoded.reference_frame == "imu"
    sceneio.write(decoded, root / "kalibr-copy", format="kalibr")


def _pose_graph(root: Path) -> None:
    information = np.tile(np.eye(6), (1, 1, 1))
    graph = _core.pose_graph(
        np.array([3, 9], np.int64),
        np.array([[0.0, 0, 0], [1.0, 0, 0]]),
        np.array([[0.0, 0.0, 0.0, 1.0]] * 2),
        np.array([[3, 9]], np.int64),
        np.array([[1.0, 0, 0]]),
        np.array([[0.0, 0.0, 0.0, 1.0]]),
        information,
        fixed=np.array([1, 0], np.uint8),
    )
    assert sceneio.PoseGraph is _core.PoseGraph
    path = root / "graph.g2o"
    sceneio.write(graph, path)
    assert sceneio.detect(path) == "g2o"
    decoded = sceneio.read(path)
    assert np.array_equal(decoded.node_ids, graph.node_ids)
    assert np.array_equal(decoded.edge_endpoints, graph.edge_endpoints)
    assert np.array_equal(
        decoded.information_matrices, graph.information_matrices
    )
    inspected = sceneio.inspect(path)
    assert inspected.count == 2
    assert inspected.metadata["num_edges"] == 1
    assert inspected.metadata["num_fixed_nodes"] == 1


def _colmap_database(root: Path) -> None:
    camera = _core.camera(
        5,
        1,
        640,
        480,
        np.array([500.0, 501.0, 320.0, 240.0]),
    )
    features = [
        _core.feature_set(
            np.array([[10.0, 20.0], [30.0, 40.0]], np.float32),
            np.arange(8, dtype=np.uint8).reshape(2, 4) + image_id,
            image_id=image_id,
            image_name=f"{image_id}.jpg",
            camera_id=5,
            image_size=(640, 480),
            extractor_type=0,
        )
        for image_id in (2, 11)
    ]
    graph = _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 1]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 1]], np.uint32),
        configs=np.array([2], np.int32),
        fundamental_matrices=np.eye(3)[None],
        fundamental_present=np.array([1], np.uint8),
        geometry_present=np.array([1], np.uint8),
        match_present=np.array([1], np.uint8),
    )
    database = _core.colmap_database(
        [camera],
        features,
        graph,
        prior_focal_length=np.array([1], np.uint8),
    )
    assert sceneio.FeatureSet is _core.FeatureSet
    assert sceneio.MatchGraph is _core.MatchGraph
    assert sceneio.ColmapDatabase is _core.ColmapDatabase
    path = root / "database.db"
    sceneio.write(database, path)
    assert sceneio.detect(path) == "colmap_db"
    decoded = sceneio.read(path)
    assert decoded.num_images == 2
    assert decoded.match_graph.image_pairs.tolist() == [[2, 11]]
    selected_image = sceneio.read_partial(path, image_id=11)
    assert selected_image.image_name == "11.jpg"
    selected_pair = sceneio.read_partial(path, pair=(11, 2))
    assert selected_pair.matches.tolist() == [[0, 1]]
    inspected = sceneio.inspect(path)
    assert inspected.metadata["num_cameras"] == 1
    assert inspected.metadata["num_matches"] == 1


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sceneio-wheel-smoke-") as directory:
        root = Path(directory)
        values = np.arange(12, dtype=np.float32).reshape(3, 4)
        _pfm_and_typed_depth(root, values)
        _mapped_safetensors(root, values)
        _point_depth_and_flow(root, values)
        _reconstruction_and_images(root)
        _state_trajectory(root)
        _camera_calibration(root)
        _pose_graph(root)
        _colmap_database(root)
    print(_core.__phase__)


if __name__ == "__main__":
    main()
