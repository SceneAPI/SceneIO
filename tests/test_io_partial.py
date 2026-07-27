"""O5 partial-read differential, bounds, lifetime, and memory coverage."""

from __future__ import annotations

import gc
import io
import json
import os
import struct
import subprocess
import sys
import tracemalloc
from statistics import median

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import FormatError


def _pixels(value):
    return np.asarray(value.pixels if isinstance(value, _core.Image) else value)


def _assert_image_window(partial, full, window):
    row_start, row_stop, col_start, col_stop = window
    np.testing.assert_array_equal(
        _pixels(partial),
        _pixels(full)[row_start:row_stop, col_start:col_stop, ...],
    )
    if isinstance(full, _core.Image):
        assert isinstance(partial, _core.Image)
        assert (
            partial.dtype,
            partial.color_space,
            partial.alpha_mode,
            partial.maxval,
            partial.channels,
            partial.channel_order,
            partial.row_order,
        ) == (
            full.dtype,
            full.color_space,
            full.alpha_mode,
            full.maxval,
            full.channels,
            full.channel_order,
            full.row_order,
        )


def test_pixel_windows_equal_full_read_slices(tmp_path):
    rng = np.random.default_rng(501)
    rgb = rng.integers(0, 256, (7, 9, 3), dtype=np.uint8)
    gray16 = rng.integers(0, 65536, (7, 9), dtype=np.uint16)
    pfm = rng.standard_normal((7, 9, 3)).astype(np.float32)
    flow = rng.standard_normal((7, 9, 2)).astype(np.float32)
    rgba = rng.integers(0, 256, (7, 9, 4), dtype=np.uint8)
    rgba[..., 3] = np.arange(63, dtype=np.uint8).reshape(7, 9) * 4
    cases = (
        ("netpbm", bytes(_core.write_netpbm(_core.image(gray16), False))),
        ("netpbm", bytes(_core.write_netpbm(_core.image(rgb), False))),
        ("pfm", bytes(_core.write_pfm(pfm))),
        ("flo", bytes(_core.write_flo(flow))),
        (
            "webp",
            bytes(
                _core.write_webp(
                    _core.image(rgb, color_space="srgb"), True
                )
            ),
        ),
        (
            "webp",
            bytes(
                _core.write_webp(
                    _core.image(
                        rgba, color_space="srgb", alpha_mode="straight"
                    ),
                    True,
                )
            ),
        ),
    )
    for index, (format_id, encoded) in enumerate(cases):
        path = tmp_path / f"window-{index}.data"
        path.write_bytes(encoded)
        full = sceneio.read(path, format=format_id)
        for window in (
            (0, 1, 0, 1),
            (1, 6, 1, 8),
            (6, 7, 8, 9),
            (0, 7, 0, 9),
        ):
            partial = sceneio.read_partial(
                path, format=format_id, window=window
            )
            _assert_image_window(partial, full, window)


@pytest.mark.parametrize("channels", [1, 3])
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_binary_netpbm_window_branch_matrix(tmp_path, channels, dtype):
    rng = np.random.default_rng(510 + channels + np.dtype(dtype).itemsize)
    shape = (7, 9) if channels == 1 else (7, 9, channels)
    high = 256 if dtype == np.uint8 else 65536
    values = rng.integers(0, high, shape, dtype=dtype)
    path = tmp_path / f"binary-{channels}-{np.dtype(dtype).name}.pnm"
    path.write_bytes(
        bytes(_core.write_netpbm(_core.image(values), False))
    )
    full = sceneio.read(path, format="netpbm")
    for window in ((0, 3, 0, 4), (1, 6, 1, 8), (2, 7, 3, 9)):
        _assert_image_window(
            sceneio.read_partial(
                path, format="netpbm", window=window
            ),
            full,
            window,
        )


@pytest.mark.parametrize("channels", [1, 3])
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_ascii_netpbm_windows_reject_complete_payload_decode(
    tmp_path, channels, dtype
):
    shape = (3, 4) if channels == 1 else (3, 4, channels)
    values = np.arange(np.prod(shape), dtype=dtype).reshape(shape)
    path = tmp_path / f"ascii-{channels}-{np.dtype(dtype).name}.pnm"
    path.write_bytes(bytes(_core.write_netpbm(_core.image(values), True)))
    with pytest.raises(FormatError, match="binary P5/P6"):
        sceneio.read_partial(
            path, format="netpbm", window=(0, 2, 1, 4)
        )


@pytest.mark.parametrize("channels", [3, 4])
def test_lossy_webp_windows_reject_non_slice_exact_decode(
    tmp_path, channels
):
    rng = np.random.default_rng(520 + channels)
    values = rng.integers(0, 256, (31, 37, channels), dtype=np.uint8)
    if channels == 4:
        values[..., 3] = rng.integers(0, 255, (31, 37), dtype=np.uint8)
    image = _core.image(
        values,
        color_space="srgb",
        alpha_mode="straight" if channels == 4 else None,
    )
    path = tmp_path / f"lossy-{channels}.webp"
    path.write_bytes(bytes(_core.write_webp(image, False, 50.0)))
    with pytest.raises(FormatError, match="lossless VP8L"):
        sceneio.read_partial(
            path, format="webp", window=(3, 26, 5, 30)
        )


def _point_cloud_case(rng):
    positions = rng.standard_normal((13, 3)).astype(np.float32)
    return _core.point_cloud(
        positions,
        colors=rng.integers(0, 256, (13, 3), dtype=np.uint8),
    )


def _las_case(rng):
    return _core.point_cloud(
        rng.uniform(-10, 10, (13, 3)).astype(np.float32),
        colors16=rng.integers(0, 65536, (13, 3), dtype=np.uint16),
        intensity=rng.integers(0, 65536, 13).astype(np.float32),
        intensity_range="u16",
        origin=np.array([500_000.0, 4_000_000.0, 100.0], dtype=np.float64),
    )


def _gaussian_case(rng):
    return _core.gaussian_cloud(
        rng.standard_normal((13, 3)).astype(np.float32),
        rng.standard_normal((13, 3)).astype(np.float32),
        rng.standard_normal((13, 4)).astype(np.float32),
        rng.standard_normal(13).astype(np.float32),
        rng.standard_normal((13, 3)).astype(np.float32),
        rng.standard_normal((13, 45)).astype(np.float32),
    )


def _ksplat_case(cloud):
    return _core.gaussian_cloud(
        np.asarray(cloud.means),
        np.asarray(cloud.scales),
        np.asarray(cloud.quaternions),
        np.asarray(cloud.opacities),
        np.asarray(cloud.sh_dc),
        np.asarray(cloud.sh_rest)[:, :24],
    )


def _assert_point_range(partial, full, start, stop):
    if isinstance(full, _core.PointCloud):
        assert isinstance(partial, _core.PointCloud)
        assert partial.num_points == stop - start
        assert (
            partial.coordinate_frame,
            partial.scale_to_meters,
            partial.intensity_range,
            partial.origin,
            partial.viewpoint,
        ) == (
            full.coordinate_frame,
            full.scale_to_meters,
            full.intensity_range,
            full.origin,
            full.viewpoint,
        )
        for name in (
            "positions",
            "colors",
            "colors16",
            "normals",
            "intensities",
        ):
            expected = np.asarray(getattr(full, name))
            actual = np.asarray(getattr(partial, name))
            if expected.shape[0] == 0:
                assert actual.shape == expected.shape
            else:
                np.testing.assert_array_equal(actual, expected[start:stop])
    else:
        assert isinstance(partial, _core.GaussianCloud)
        assert partial.num_gaussians == stop - start
        assert (partial.sh_degree, partial.num_rest) == (
            full.sh_degree,
            full.num_rest,
        )
        assert (
            partial.quaternion_order,
            partial.scale_space,
            partial.opacity_space,
            partial.sh_layout,
        ) == (
            full.quaternion_order,
            full.scale_space,
            full.opacity_space,
            full.sh_layout,
        )
        for name in (
            "means",
            "scales",
            "quaternions",
            "opacities",
            "sh_dc",
            "sh_rest",
        ):
            np.testing.assert_array_equal(
                np.asarray(getattr(partial, name)),
                np.asarray(getattr(full, name))[start:stop],
            )


def test_point_ranges_equal_full_read_slices(tmp_path):
    rng = np.random.default_rng(502)
    xyz = _point_cloud_case(rng)
    las = _las_case(rng)
    gaussians = _gaussian_case(rng)
    cases = (
        ("xyz", bytes(_core.write_xyz(xyz))),
        ("pts", bytes(_core.write_pts(xyz))),
        ("ply", bytes(_core.write_ply(xyz))),
        ("pcd", bytes(_core.write_pcd(xyz))),
        ("las", bytes(_core.write_las(las))),
        ("gaussian_ply", bytes(_core.write_gaussian_ply(gaussians))),
        ("compressed_ply", bytes(_core.write_compressed_ply(gaussians))),
        ("sog", bytes(_core.write_sog(gaussians))),
        ("ksplat", bytes(_core.write_ksplat(_ksplat_case(gaussians)))),
        ("splat", bytes(_core.write_splat(gaussians))),
    )
    for index, (format_id, encoded) in enumerate(cases):
        path = tmp_path / f"points-{index}.data"
        path.write_bytes(encoded)
        full = sceneio.read(path, format=format_id)
        for start, stop in ((0, 1), (3, 10), (12, 13), (0, 13)):
            partial = sceneio.read_partial(
                path, format=format_id, points=(start, stop)
            )
            _assert_point_range(partial, full, start, stop)


@pytest.mark.parametrize(
    "row",
    [
        "1 2 3",
        "1 2 3 0.25",
        "1 2 3 10 20 30",
        "1 2 3 0.25 10 20 30",
        "1 2 3 10 20 30 0.1 0.2 0.3",
    ],
)
def test_xyz_automatic_layout_partial_parity(tmp_path, row):
    columns = len(row.split())
    data = ("\n".join(row for _ in range(6)) + "\n").encode()
    path = tmp_path / f"xyz-{columns}.xyz"
    path.write_bytes(data)
    full = sceneio.read(path, format="xyz")
    partial = sceneio.read_partial(
        path, format="xyz", points=(1, 5)
    )
    _assert_point_range(partial, full, 1, 5)


def test_xyz_forced_normals_layout_partial_parity():
    data = b"\n".join(
        f"{i} {i + 1} {i + 2} 0.1 0.2 0.3".encode()
        for i in range(6)
    )
    full = _core.read_xyz(data, "xyzn")
    partial = _core.read_xyz_points(data, 1, 5, "xyzn")
    _assert_point_range(partial, full, 1, 5)


@pytest.mark.parametrize("point_format", [0, 1, 2, 3, 6, 7, 8])
def test_las_point_format_partial_parity(tmp_path, point_format):
    laspy = pytest.importorskip("laspy")
    rng = np.random.default_rng(540 + point_format)
    xyz = rng.random((13, 3)) * 100 + [600000.0, 5000000.0, 50.0]
    rgb = rng.integers(0, 65536, (13, 3), dtype=np.uint16)
    intensity = rng.integers(0, 65536, 13, dtype=np.uint16)
    header = laspy.LasHeader(
        version="1.4" if point_format >= 6 else "1.2",
        point_format=point_format,
    )
    header.scales = [0.001, 0.001, 0.001]
    header.offsets = [600000.0, 5000000.0, 50.0]
    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    las.intensity = intensity
    if point_format in (2, 3, 7, 8):
        las.red, las.green, las.blue = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    encoded = io.BytesIO()
    las.write(encoded)
    path = tmp_path / f"format-{point_format}.las"
    path.write_bytes(encoded.getvalue())
    full = sceneio.read(path, format="las")
    partial = sceneio.read_partial(
        path, format="las", points=(2, 11)
    )
    _assert_point_range(partial, full, 2, 11)

def test_partial_reads_handle_non_native_endian_payloads(tmp_path):
    pfm_values = np.arange(4 * 5, dtype=np.float32).reshape(4, 5)
    pfm_path = tmp_path / "big-endian.pfm"
    pfm_path.write_bytes(
        b"Pf\n5 4\n1.0\n"
        + np.flipud(pfm_values).astype(">f4").tobytes()
    )
    _assert_image_window(
        sceneio.read_partial(
            pfm_path, format="pfm", window=(1, 4, 1, 5)
        ),
        sceneio.read(pfm_path, format="pfm"),
        (1, 4, 1, 5),
    )

    rng = np.random.default_rng(503)
    little = bytes(_core.write_gaussian_ply(_gaussian_case(rng)))
    header_end = little.index(b"end_header\n") + len(b"end_header\n")
    header = little[:header_end].replace(
        b"binary_little_endian", b"binary_big_endian"
    )
    body = little[header_end:]
    big_body = b"".join(
        body[offset : offset + 4][::-1] for offset in range(0, len(body), 4)
    )
    ply_path = tmp_path / "big-endian.ply"
    ply_path.write_bytes(header + big_body)
    full = sceneio.read(ply_path, format="gaussian_ply")
    partial = sceneio.read_partial(
        ply_path, format="gaussian_ply", points=(2, 11)
    )
    _assert_point_range(partial, full, 2, 11)

    point_cloud = _point_cloud_case(rng)
    point_ply_path = tmp_path / "big-endian-points.ply"
    point_ply_path.write_bytes(
        bytes(_core.write_ply(point_cloud, "binary_big_endian"))
    )
    point_full = sceneio.read(point_ply_path, format="ply")
    point_partial = sceneio.read_partial(
        point_ply_path, format="ply", points=(2, 11)
    )
    _assert_point_range(point_partial, point_full, 2, 11)


def _three_view_reconstruction():
    return _core.read_nvm(
        b"NVM_V3\n3\n"
        b"a.jpg 800 1 0 0 0 0 0 0 0 0\n"
        b"b.jpg 810 1 0 0 0 1 2 3 0 0\n"
        b"c.jpg 820 1 0 0 0 4 5 6 0 0\n"
        b"1\n1.5 -2.5 3.5 10 20 30 3 "
        b"0 0 4.5 -5.5 1 0 6.5 -7.5 2 0 8.5 -9.5\n0\n"
    )


@pytest.mark.parametrize("format_id", ["colmap_sparse", "colmap_sparse_txt"])
def test_single_colmap_image_equals_full_image_slice(tmp_path, format_id):
    directory = tmp_path / format_id
    directory.mkdir()
    source = _three_view_reconstruction()
    writer = (
        _core.write_colmap_sparse
        if format_id == "colmap_sparse"
        else _core.write_colmap_txt
    )
    writer(source, str(directory))
    full = sceneio.read(directory, format=format_id)
    for row in range(full.num_images):
        image_id = int(np.asarray(full.image_ids)[row])
        partial = sceneio.read_partial(
            directory, format=format_id, image_id=image_id
        )
        assert (
            partial.num_cameras,
            partial.num_images,
            partial.num_points3D,
        ) == (1, 1, 0)
        assert (
            partial.quaternion_order,
            partial.pose_convention,
        ) == (
            full.quaternion_order,
            full.pose_convention,
        )
        assert partial.image_names == [full.image_names[row]]
        np.testing.assert_array_equal(
            np.asarray(partial.image_ids),
            np.asarray(full.image_ids)[row : row + 1],
        )
        np.testing.assert_array_equal(
            np.asarray(partial.quaternions),
            np.asarray(full.quaternions)[row : row + 1],
        )
        np.testing.assert_array_equal(
            np.asarray(partial.translations),
            np.asarray(full.translations)[row : row + 1],
        )
        np.testing.assert_array_equal(
            np.asarray(partial.image_camera_ids),
            np.asarray(full.image_camera_ids)[row : row + 1],
        )
        camera = partial.cameras[0]
        expected_camera = next(
            item
            for item in full.cameras
            if item.id == int(np.asarray(full.image_camera_ids)[row])
        )
        assert (
            camera.id,
            camera.model_id,
            camera.width,
            camera.height,
        ) == (
            expected_camera.id,
            expected_camera.model_id,
            expected_camera.width,
            expected_camera.height,
        )
        np.testing.assert_array_equal(
            np.asarray(camera.params), np.asarray(expected_camera.params)
        )


def test_partial_selector_validation_and_unsupported_formats(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(
        bytes(
            _core.write_png(
                _core.image(np.zeros((3, 4, 3), dtype=np.uint8))
            )
        )
    )
    with pytest.raises(ValueError, match="exactly one"):
        sceneio.read_partial(path, format="png")
    with pytest.raises(ValueError, match="exactly one"):
        sceneio.read_partial(
            path, format="png", window=(0, 1, 0, 1), faces=(0, 1)
        )
    with pytest.raises(TypeError, match="integers"):
        sceneio.read_partial(path, format="png", window=(False, 1, 0, 1))
    with pytest.raises(ValueError, match="exactly 4"):
        sceneio.read_partial(path, format="png", window=(0, 1, 2))
    with pytest.raises(FormatError, match="does not support pixel-window"):
        sceneio.read_partial(path, format="png", window=(0, 1, 0, 1))
    with pytest.raises(FormatError, match="does not support face-subset"):
        sceneio.read_partial(path, format="png", faces=(0, 1))


def test_mesh_face_range_equals_full_domain_slice_and_closes_mapping(tmp_path):
    positions = np.arange(24, dtype=np.float32).reshape(8, 3) / 7
    face_offsets = np.array([0, 3, 6, 10, 13, 17, 20], np.uint64)
    face_indices = np.array(
        [
            0,
            1,
            2,
            0,
            2,
            3,
            0,
            3,
            4,
            5,
            1,
            5,
            6,
            0,
            1,
            6,
            7,
            2,
            6,
            7,
        ],
        np.uint64,
    )
    mesh = _core.mesh(
        positions,
        face_offsets,
        face_indices,
        vertex_normals=np.arange(24, dtype=np.float32).reshape(8, 3) / 23,
        corner_normals=np.arange(60, dtype=np.float32).reshape(20, 3) / 59,
        vertex_uvs=np.arange(16, dtype=np.float32).reshape(8, 2) / 15,
        corner_uvs=np.arange(40, dtype=np.float32).reshape(20, 2) / 39,
        vertex_colors=np.arange(32, dtype=np.uint8).reshape(8, 4),
        corner_colors=np.arange(80, dtype=np.uint8).reshape(20, 4),
        primitive_offsets=np.array([0, 2, 5, 6], np.uint64),
        primitive_materials=np.array([2, 3, -1], np.int32),
        coordinate_frame="opengl",
        scale_to_meters=0.01,
    )
    path = tmp_path / "faces.ply"
    sceneio.write(mesh, path)

    partial = sceneio.read_partial(path, faces=(1, 5))
    corner_start, corner_stop = 3, 17
    np.testing.assert_array_equal(partial.positions, mesh.positions)
    np.testing.assert_array_equal(partial.vertex_normals, mesh.vertex_normals)
    np.testing.assert_array_equal(partial.vertex_uvs, mesh.vertex_uvs)
    np.testing.assert_array_equal(partial.vertex_colors, mesh.vertex_colors)
    np.testing.assert_array_equal(
        partial.face_offsets, face_offsets[1:6] - corner_start
    )
    np.testing.assert_array_equal(
        partial.face_indices, face_indices[corner_start:corner_stop]
    )
    for name in ("corner_normals", "corner_uvs", "corner_colors"):
        np.testing.assert_array_equal(
            getattr(partial, name),
            getattr(mesh, name)[corner_start:corner_stop],
        )
    np.testing.assert_array_equal(partial.primitive_offsets, [0, 1, 4])
    np.testing.assert_array_equal(partial.primitive_materials, [2, 3])
    assert partial.coordinate_frame == "opengl"
    assert partial.scale_to_meters == 0.01

    gc.collect()
    replacement = tmp_path / "faces-replaced.ply"
    path.replace(replacement)
    path.write_bytes(b"replacement")
    np.testing.assert_array_equal(
        partial.face_indices, face_indices[corner_start:corner_stop]
    )


@pytest.mark.parametrize(
    ("format_id", "selector", "message"),
    [
        ("netpbm", {"window": (1, 1, 0, 1)}, "non-empty"),
        ("netpbm", {"window": (0, 4, 0, 1)}, "available extent"),
        ("xyz", {"points": (2, 2)}, "non-empty"),
        ("xyz", {"points": (0, 9)}, "available extent"),
        ("pts", {"points": (2, 2)}, "non-empty"),
        ("pts", {"points": (0, 9)}, "declared point count"),
    ],
)
def test_partial_ranges_reject_empty_or_out_of_bounds(
    tmp_path, format_id, selector, message
):
    if format_id == "netpbm":
        encoded = bytes(
            _core.write_netpbm(
                _core.image(np.arange(12, dtype=np.uint8).reshape(3, 4))
            )
        )
    elif format_id == "xyz":
        encoded = b"0 0 0\n1 1 1\n"
    else:
        encoded = b"2\n0 0 0\n1 1 1\n"
    path = tmp_path / f"bounds-{format_id}.data"
    path.write_bytes(encoded)
    with pytest.raises(FormatError, match=message):
        sceneio.read_partial(path, format=format_id, **selector)


def test_partial_paths_reject_truncated_selected_payloads(tmp_path):
    rng = np.random.default_rng(504)
    point_cloud = _point_cloud_case(rng)
    las = _las_case(rng)
    gaussians = _gaussian_case(rng)
    rgba = rng.integers(0, 256, (7, 9, 4), dtype=np.uint8)
    rgba[..., 3] = np.arange(63, dtype=np.uint8).reshape(7, 9) * 4
    cases = (
        (
            "pfm",
            bytes(
                _core.write_pfm(
                    rng.standard_normal((7, 9)).astype(np.float32)
                )
            )[:-4],
            {"window": (0, 1, 0, 1)},
        ),
        (
            "flo",
            bytes(
                _core.write_flo(
                    rng.standard_normal((7, 9, 2)).astype(np.float32)
                )
            )[:-4],
            {"window": (0, 1, 0, 1)},
        ),
        (
            "netpbm",
            bytes(
                _core.write_netpbm(
                    _core.image(
                        rng.integers(0, 256, (7, 9), dtype=np.uint8)
                    )
                )
            )[:-1],
            {"window": (0, 1, 0, 1)},
        ),
        (
            "webp",
            bytes(
                _core.write_webp(
                    _core.image(
                        rgba, color_space="srgb", alpha_mode="straight"
                    )
                )
            )[:-3],
            {"window": (0, 1, 0, 1)},
        ),
        (
            "xyz",
            bytes(_core.write_xyz(point_cloud)) + b"not a valid point\n",
            {"points": (13, 14)},
        ),
        (
            "las",
            bytes(_core.write_las(las))[:-1],
            {"points": (0, 1)},
        ),
        (
            "gaussian_ply",
            bytes(_core.write_gaussian_ply(gaussians))[:-1],
            {"points": (0, 1)},
        ),
        (
            "compressed_ply",
            bytes(_core.write_compressed_ply(gaussians))[:-1],
            {"points": (0, 1)},
        ),
        (
            "sog",
            bytes(_core.write_sog(gaussians))[:-1],
            {"points": (0, 1)},
        ),
        (
            "ksplat",
            bytes(_core.write_ksplat(_ksplat_case(gaussians)))[:-1],
            {"points": (0, 1)},
        ),
        (
            "ply",
            bytes(_core.write_ply(point_cloud))[:-1],
            {"points": (0, 1)},
        ),
        (
            "pcd",
            bytes(_core.write_pcd(point_cloud))[:-1],
            {"points": (0, 1)},
        ),
        (
            "splat",
            bytes(_core.write_splat(gaussians)) + b"\x00",
            {"points": (0, 1)},
        ),
    )
    for index, (format_id, encoded, selector) in enumerate(cases):
        path = tmp_path / f"truncated-{index}.data"
        path.write_bytes(encoded)
        with pytest.raises(FormatError):
            sceneio.read_partial(path, format=format_id, **selector)


def test_single_colmap_image_rejects_unknown_id(tmp_path):
    directory = tmp_path / "model"
    directory.mkdir()
    _core.write_colmap_sparse(_three_view_reconstruction(), str(directory))
    with pytest.raises(FormatError, match="image id 4294967295 not found"):
        sceneio.read_partial(
            directory, format="colmap_sparse", image_id=0xFFFFFFFF
        )
    with pytest.raises(ValueError, match=r"0\.\.4294967295"):
        sceneio.read_partial(directory, format="colmap_sparse", image_id=-1)


@pytest.mark.parametrize("format_id", ["colmap_sparse", "colmap_sparse_txt"])
def test_single_colmap_image_does_not_open_the_point_container(
    tmp_path, format_id
):
    directory = tmp_path / format_id
    directory.mkdir()
    source = _three_view_reconstruction()
    if format_id == "colmap_sparse":
        _core.write_colmap_sparse(source, str(directory))
        (directory / "points3D.bin").unlink()
    else:
        _core.write_colmap_txt(source, str(directory))
        (directory / "points3D.txt").unlink()
    partial = sceneio.read_partial(directory, format=format_id, image_id=1)
    assert (partial.num_images, partial.num_points3D) == (1, 0)


@pytest.mark.parametrize("format_id", ["colmap_sparse", "colmap_sparse_txt"])
def test_single_colmap_image_skips_unselected_names_over_one_mib(
    tmp_path, format_id
):
    directory = tmp_path / format_id
    directory.mkdir()
    source = _three_view_reconstruction()
    long_name = b"x" * (1024 * 1024 + 17)
    if format_id == "colmap_sparse":
        _core.write_colmap_sparse(source, str(directory))
        images_path = directory / "images.bin"
        encoded = images_path.read_bytes()
        name_start = 8 + 4 + 4 * 8 + 3 * 8 + 4
        name_end = encoded.index(b"\0", name_start)
        images_path.write_bytes(
            encoded[:name_start] + long_name + encoded[name_end:]
        )
    else:
        _core.write_colmap_txt(source, str(directory))
        images_path = directory / "images.txt"
        encoded = images_path.read_bytes()
        images_path.write_bytes(encoded.replace(b"a.jpg", long_name, 1))

    # The full reader establishes that this is a valid accepted name. The
    # partial reader must skip it without allocating or imposing a new limit.
    full = sceneio.read(directory, format=format_id)
    long_id = int(np.asarray(full.image_ids)[0])
    selected = sceneio.read_partial(
        directory, format=format_id, image_id=long_id
    )
    assert selected.image_names == [full.image_names[0]]
    target_id = int(np.asarray(full.image_ids)[1])
    partial = sceneio.read_partial(
        directory, format=format_id, image_id=target_id
    )
    assert partial.image_names == [full.image_names[1]]


def _traced_peak(call):
    gc.collect()
    tracemalloc.start()
    try:
        value = call()
        _, peak = tracemalloc.get_traced_memory()
        return value, peak
    finally:
        tracemalloc.stop()


def _fresh_process_partial_rss(path, format_id, mode):
    if os.environ.get("ASAN_OPTIONS") or "libasan" in os.environ.get(
        "LD_PRELOAD", ""
    ):
        pytest.skip("RSS measurements include AddressSanitizer shadow memory")
    script = """
import gc
import sys
import threading
import time

import numpy as np
import psutil
import sceneio
from sceneio import _core

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
    if sys.argv[3] == "full":
        value = sceneio.read(sys.argv[1], format=sys.argv[2])
    elif sys.argv[2] == "netpbm":
        value = sceneio.read_partial(
            sys.argv[1], format=sys.argv[2], window=(5000, 5008, 6000, 6008)
        )
    elif sys.argv[2] == "colmap_sparse_txt":
        value = sceneio.read_partial(
            sys.argv[1], format=sys.argv[2], image_id=2
        )
    elif sys.argv[2] == "ply_mesh":
        value = sceneio.read_partial(
            sys.argv[1], format=sys.argv[2], faces=(1, 2)
        )
    else:
        value = sceneio.read_partial(
            sys.argv[1], format=sys.argv[2], points=(1000000, 1000008)
        )
    if isinstance(value, _core.Image):
        np.asarray(value.pixels).sum()
    elif isinstance(value, _core.GaussianCloud):
        np.asarray(value.means).sum()
    elif isinstance(value, _core.Mesh):
        np.asarray(value.face_indices).sum()
    peak[0] = max(peak[0], process.memory_info().rss)
finally:
    running[0] = False
    thread.join()
print(max(0, peak[0] - baseline))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(path), format_id, mode],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(completed.stdout.strip())


def _fresh_process_colmap_error_rss(
    path,
    format_id,
    image_id,
    *,
    warm_path,
    mode="sceneio",
    repeats=3,
):
    if os.environ.get("ASAN_OPTIONS") or "libasan" in os.environ.get(
        "LD_PRELOAD", ""
    ):
        pytest.skip("RSS measurements include AddressSanitizer shadow memory")
    script = """
import gc
import json
import sys
import threading
import time
from pathlib import Path

import psutil
import sceneio

process = psutil.Process()
control_headroom = 0

def high_water_rss():
    memory = process.memory_info()
    peak_wset = getattr(memory, "peak_wset", None)
    if peak_wset is not None:
        return peak_wset
    try:
        import resource
    except ImportError:
        return memory.rss
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024

def sceneio_error(target):
    try:
        sceneio.read_partial(
            target, format=sys.argv[2], image_id=int(sys.argv[3])
        )
    except sceneio.FormatError:
        return
    raise AssertionError("malformed model unexpectedly decoded")

def operation():
    if sys.argv[5] == "allocate":
        payload_size = (Path(sys.argv[1]) / "images.bin").stat().st_size
        value = bytearray(control_headroom + payload_size)
        for offset in range(0, len(value), 4096):
            value[offset] = 1
        if value:
            value[-1] = 1
        del value
        return
    sceneio_error(sys.argv[1])

# Warm lazy imports, native dispatch, filesystem metadata, and allocator pools
# with a fixed tiny malformed fixture. The first size-dependent operation is
# always inside the measured window.
sceneio_error(sys.argv[4])
process.memory_info()
gc.collect()
baseline = process.memory_info().rss
baseline_high_water = high_water_rss()
# Make the transient control clear any high-water established by imports, then
# add exactly one file-controlled extent above it.
control_headroom = max(0, baseline_high_water - baseline)
peak = [baseline]
running = [True]

def sample():
    while running[0]:
        peak[0] = max(peak[0], process.memory_info().rss)
        time.sleep(0.0005)

thread = threading.Thread(target=sample, daemon=True)
thread.start()
try:
    operation()
    peak[0] = max(peak[0], process.memory_info().rss)
finally:
    running[0] = False
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("RSS sampler thread did not stop")
peak_current = peak[0]
peak_high_water = high_water_rss()
current_delta = max(0, peak_current - baseline)
high_water_delta = max(0, peak_high_water - baseline_high_water)
print(json.dumps({
    "baseline": baseline,
    "baseline_high_water": baseline_high_water,
    "peak_current": peak_current,
    "peak_high_water": peak_high_water,
    "current_delta": current_delta,
    "high_water_delta": high_water_delta,
    "delta": max(current_delta, high_water_delta),
}))
"""
    measurements = []
    for _ in range(repeats):
        command = [
            sys.executable,
            "-c",
            script,
            str(path),
            format_id,
            str(image_id),
            str(warm_path),
            mode,
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            pytest.fail(
                "RSS child timed out: "
                f"mode={mode}, path={path}, warm_path={warm_path}, "
                f"stdout={exc.stdout!r}, stderr={exc.stderr!r}"
            )
        measurements.append(json.loads(completed.stdout))
    return measurements


def _assert_payload_relative_rss(
    small_size,
    small_measurements,
    large_size,
    large_measurements,
    *,
    metric="delta",
):
    small_delta = median(item[metric] for item in small_measurements)
    large_delta = median(item[metric] for item in large_measurements)
    payload_growth = large_size - small_size
    measured_growth = max(0, large_delta - small_delta)
    assert measured_growth < payload_growth // 4, (
        "payload-relative RSS growth is too steep: "
        f"metric={metric}, "
        f"sizes=({small_size}, {large_size}), "
        f"deltas=({small_delta}, {large_delta}), "
        f"samples=({small_measurements}, {large_measurements})"
    )


def _assert_colmap_error_rss_is_sublinear(
    cases,
    format_id,
    image_id,
    *,
    warm_path,
):
    assert len(cases) == 2
    sceneio_measurements = [
        (
            size,
            _fresh_process_colmap_error_rss(
                path,
                format_id,
                image_id,
                warm_path=warm_path,
            ),
        )
        for size, path in cases
    ]
    _assert_payload_relative_rss(
        sceneio_measurements[0][0],
        sceneio_measurements[0][1],
        sceneio_measurements[1][0],
        sceneio_measurements[1][1],
    )

    allocation_controls = [
        (
            size,
            _fresh_process_colmap_error_rss(
                path,
                format_id,
                image_id,
                warm_path=warm_path,
                mode="allocate",
            ),
        )
        for size, path in cases
    ]
    with pytest.raises(
        AssertionError,
        match="payload-relative RSS growth is too steep",
    ):
        _assert_payload_relative_rss(
            allocation_controls[0][0],
            allocation_controls[0][1],
            allocation_controls[1][0],
            allocation_controls[1][1],
            metric="high_water_delta",
        )


def _traced_format_error_peak(operation, *, match):
    gc.collect()
    tracemalloc.start()
    try:
        with pytest.raises(FormatError, match=match):
            operation()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


def test_large_partial_reads_do_not_allocate_payload_sized_python_objects(
    tmp_path,
):
    width = height = 10_240
    netpbm = tmp_path / "large.pgm"
    header = f"P5\n{width} {height}\n255\n".encode()
    with netpbm.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + width * height)
    window, peak = _traced_peak(
        lambda: sceneio.read_partial(
            netpbm,
            format="netpbm",
            window=(5_000, 5_008, 6_000, 6_008),
        )
    )
    assert _pixels(window).shape == (8, 8)
    assert peak < 1024 * 1024

    splat = tmp_path / "large.splat"
    with splat.open("wb") as stream:
        stream.truncate(3_200_000 * 32)
    cloud, peak = _traced_peak(
        lambda: sceneio.read_partial(
            splat, format="splat", points=(1_000_000, 1_000_008)
        )
    )
    assert cloud.num_gaussians == 8
    assert peak < 1024 * 1024

    partial_rss = _fresh_process_partial_rss(netpbm, "netpbm", "partial")
    full_rss = _fresh_process_partial_rss(netpbm, "netpbm", "full")
    assert full_rss > 64 * 1024 * 1024
    assert partial_rss < min(16 * 1024 * 1024, full_rss // 4)
    assert (
        _fresh_process_partial_rss(splat, "splat", "partial")
        < 16 * 1024 * 1024
    )

    mesh = tmp_path / "large-face-mesh.ply"
    corners = 12_500_000
    mesh_header = b"""ply
format binary_little_endian 1.0
element vertex 1
property float x
property float y
property float z
element face 2
property list uint uint vertex_indices
property int material_index
property uint primitive_index
end_header
"""
    with mesh.open("wb") as stream:
        stream.write(mesh_header)
        stream.write(b"\0" * 12)
        stream.write(struct.pack("<I", corners))
        stream.seek(corners * 4, os.SEEK_CUR)
        stream.write(struct.pack("<iI", -1, 0))
        stream.write(struct.pack("<I3IiI", 3, 0, 0, 0, -1, 1))
    selected_mesh, peak = _traced_peak(
        lambda: sceneio.read_partial(mesh, format="ply_mesh", faces=(1, 2))
    )
    assert selected_mesh.num_faces == 1
    assert selected_mesh.face_indices.tolist() == [0, 0, 0]
    assert peak < 1024 * 1024
    mesh_partial_rss = _fresh_process_partial_rss(
        mesh, "ply_mesh", "partial"
    )
    mesh_full_rss = _fresh_process_partial_rss(mesh, "ply_mesh", "full")
    assert mesh_full_rss > 80 * 1024 * 1024
    assert mesh_partial_rss < mesh_full_rss * 3 // 5


def test_colmap_text_skips_unselected_large_observation_line_bounded(
    tmp_path,
):
    directory = tmp_path / "large-text-model"
    directory.mkdir()
    (directory / "cameras.txt").write_text(
        "1 PINHOLE 640 480 500 500 320 240\n"
        "2 PINHOLE 640 480 500 500 320 240\n",
        encoding="utf-8",
    )
    images = directory / "images.txt"
    with images.open("wb") as stream:
        stream.write(b"1 1 0 0 0 0 0 0 1 first.jpg\n")
        stream.seek(64 * 1024 * 1024, 1)
        stream.write(b"\n2 1 0 0 0 0 0 0 2 second.jpg\n\n")
    partial = sceneio.read_partial(
        directory, format="colmap_sparse_txt", image_id=2
    )
    assert partial.image_names == ["second.jpg"]
    assert partial.num_points3D == 0
    assert (
        _fresh_process_partial_rss(
            directory, "colmap_sparse_txt", "partial"
        )
        < 16 * 1024 * 1024
    )


def _write_malformed_observation_model(tmp_path, label, payload_size):
    source = _three_view_reconstruction()
    image_id = int(np.asarray(source.image_ids)[0])
    directory = tmp_path / f"malformed-binary-model-{label}"
    directory.mkdir()
    _core.write_colmap_sparse(source, str(directory))
    images_path = directory / "images.bin"
    encoded = bytearray(images_path.read_bytes())
    name_start = 8 + 4 + 4 * 8 + 3 * 8 + 4
    name_end = encoded.index(0, name_start)
    count_offset = name_end + 1
    observation_count = payload_size // 24 + 1
    encoded[count_offset : count_offset + 8] = struct.pack(
        "<Q", observation_count
    )
    del encoded[count_offset + 8 :]
    with images_path.open("wb") as stream:
        stream.write(encoded)
        stream.truncate(stream.tell() + payload_size)
    return directory, image_id, images_path.stat().st_size


def _write_unterminated_name_model(tmp_path, label, payload_size):
    source = _three_view_reconstruction()
    image_id = int(np.asarray(source.image_ids)[0])
    directory = tmp_path / f"unterminated-binary-name-{label}"
    directory.mkdir()
    _core.write_colmap_sparse(source, str(directory))
    images_path = directory / "images.bin"
    prefix = images_path.read_bytes()[: 8 + 4 + 4 * 8 + 3 * 8 + 4]
    with images_path.open("wb") as stream:
        stream.write(prefix)
        block = b"x" * 65536
        complete_blocks, remainder = divmod(payload_size, len(block))
        for _ in range(complete_blocks):
            stream.write(block)
        stream.write(block[:remainder])
    return directory, image_id, images_path.stat().st_size


def test_colmap_binary_checks_selected_observation_bytes_before_allocating(
    tmp_path,
):
    directory, image_id, _size = _write_malformed_observation_model(
        tmp_path,
        "semantic",
        64,
    )
    with pytest.raises(
        FormatError,
        match="truncated image observations",
    ):
        sceneio.read_partial(
            directory,
            format="colmap_sparse",
            image_id=image_id,
        )


def test_colmap_binary_validates_selected_name_terminator_before_allocating(
    tmp_path,
):
    directory, image_id, _size = _write_unterminated_name_model(
        tmp_path,
        "semantic",
        64,
    )
    with pytest.raises(FormatError, match="truncated image name"):
        sceneio.read_partial(
            directory,
            format="colmap_sparse",
            image_id=image_id,
        )


def _instrumented_rss_measurement():
    return bool(
        os.environ.get("ASAN_OPTIONS")
        or "libasan" in os.environ.get("LD_PRELOAD", "")
    )


@pytest.mark.skipif(
    _instrumented_rss_measurement(),
    reason="RSS measurements include AddressSanitizer shadow memory",
)
def test_colmap_observation_error_rss_growth_is_payload_relative(tmp_path):
    warm_path, image_id, _size = _write_malformed_observation_model(
        tmp_path,
        "warm",
        64,
    )
    cases = []
    for payload_size in (8 * 1024 * 1024, 32 * 1024 * 1024):
        directory, case_image_id, size = _write_malformed_observation_model(
            tmp_path,
            str(payload_size),
            payload_size,
        )
        assert case_image_id == image_id
        assert (
            _traced_format_error_peak(
                lambda directory=directory: sceneio.read_partial(
                    directory,
                    format="colmap_sparse",
                    image_id=image_id,
                ),
                match="truncated image observations",
            )
            < 1024 * 1024
        )
        cases.append((size, directory))
    _assert_colmap_error_rss_is_sublinear(
        cases,
        "colmap_sparse",
        image_id,
        warm_path=warm_path,
    )


@pytest.mark.skipif(
    _instrumented_rss_measurement(),
    reason="RSS measurements include AddressSanitizer shadow memory",
)
def test_colmap_name_error_rss_growth_is_payload_relative(tmp_path):
    warm_path, image_id, _size = _write_unterminated_name_model(
        tmp_path,
        "warm",
        64,
    )
    cases = []
    for payload_size in (8 * 1024 * 1024, 32 * 1024 * 1024):
        directory, case_image_id, size = _write_unterminated_name_model(
            tmp_path,
            str(payload_size),
            payload_size,
        )
        assert case_image_id == image_id
        assert (
            _traced_format_error_peak(
                lambda directory=directory: sceneio.read_partial(
                    directory,
                    format="colmap_sparse",
                    image_id=image_id,
                ),
                match="truncated image name",
            )
            < 1024 * 1024
        )
        cases.append((size, directory))
    _assert_colmap_error_rss_is_sublinear(
        cases,
        "colmap_sparse",
        image_id,
        warm_path=warm_path,
    )


def _write_malformed_text_token_model(tmp_path, label, payload_size):
    directory = tmp_path / f"malformed-text-model-{label}"
    directory.mkdir()
    (directory / "cameras.txt").write_text(
        "1 PINHOLE 640 480 500 500 320 240\n",
        encoding="utf-8",
    )
    images_path = directory / "images.txt"
    with images_path.open("wb") as stream:
        stream.write(b"1 1 0 0 0 0 0 0 1 image.jpg\n")
        stream.seek(payload_size, 1)
        stream.write(b"x\n")
    (directory / "points3D.txt").write_bytes(b"")
    return directory


def test_colmap_text_selected_malformed_token_is_memory_bounded(tmp_path):
    warm_path = _write_malformed_text_token_model(tmp_path, "warm", 64)
    directory = _write_malformed_text_token_model(
        tmp_path,
        "measured",
        32 * 1024 * 1024,
    )
    with pytest.raises(FormatError, match="token exceeds 1 MiB"):
        sceneio.read_partial(
            directory, format="colmap_sparse_txt", image_id=1
        )
    measurements = _fresh_process_colmap_error_rss(
        directory,
        "colmap_sparse_txt",
        1,
        warm_path=warm_path,
    )
    assert (
        median(item["delta"] for item in measurements)
        # Hosted Linux allocators vary by several MiB. This remains below the
        # malformed 32 MiB token and therefore catches a whole-line mirror.
        < 24 * 1024 * 1024
    )


def test_colmap_text_oversized_numeric_token_policy_matches_full_read(
    tmp_path,
):
    directory = tmp_path / "oversized-text-token"
    directory.mkdir()
    (directory / "cameras.txt").write_text(
        "1 PINHOLE 640 480 500 500 320 240\n",
        encoding="utf-8",
    )
    (directory / "images.txt").write_bytes(
        b"1 1 0 0 0 0 0 0 1 image.jpg\n"
        + b"0" * (1024 * 1024 + 1)
        + b" 0 -1\n"
    )
    (directory / "points3D.txt").write_bytes(b"")
    for call in (
        lambda: sceneio.read(directory, format="colmap_sparse_txt"),
        lambda: sceneio.read_partial(
            directory, format="colmap_sparse_txt", image_id=1
        ),
    ):
        with pytest.raises(FormatError, match="token exceeds 1 MiB"):
            call()


def test_colmap_text_stream_skips_oversized_comment_line(tmp_path):
    directory = tmp_path / "large-text-comment"
    directory.mkdir()
    (directory / "cameras.txt").write_bytes(
        b"#" + b"x" * (2 * 1024 * 1024) + b"\n"
        b"1 PINHOLE 640 480 500 500 320 240\n"
    )
    (directory / "images.txt").write_bytes(
        b"#" + b"x" * (2 * 1024 * 1024) + b"\n"
        b"1 1 0 0 0 0 0 0 1 image.jpg\n\n"
    )
    (directory / "points3D.txt").write_bytes(b"")
    full = sceneio.read(directory, format="colmap_sparse_txt")
    partial = sceneio.read_partial(
        directory, format="colmap_sparse_txt", image_id=1
    )
    assert partial.image_names == full.image_names == ["image.jpg"]
