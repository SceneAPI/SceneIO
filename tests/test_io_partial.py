"""O5 partial-read differential, bounds, lifetime, and memory coverage."""

from __future__ import annotations

import gc
import io
import os
import struct
import subprocess
import sys
import tracemalloc

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


def test_dmb_pixel_windows_equal_full_depth_slices(tmp_path):
    values = np.arange(7 * 9, dtype=np.float32).reshape(7, 9)
    record = _core.depth_map(
        values,
        unit="unknown",
        invalid_policy="zero",
    )
    path = tmp_path / "window.dmb"
    sceneio.write(record, path)
    full = sceneio.read(path)
    for window in (
        (0, 1, 0, 1),
        (1, 6, 1, 8),
        (6, 7, 8, 9),
        (0, 7, 0, 9),
    ):
        row_start, row_stop, col_start, col_stop = window
        partial = sceneio.read_partial(path, window=window)
        assert isinstance(partial, _core.DepthMap)
        np.testing.assert_array_equal(
            partial.depth,
            full.depth[row_start:row_stop, col_start:col_stop],
        )
        assert (
            partial.unit,
            partial.scale_to_meters,
            partial.invalid_policy,
            partial.row_order,
            partial.has_confidence,
        ) == (
            full.unit,
            full.scale_to_meters,
            full.invalid_policy,
            full.row_order,
            False,
        )


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


def _assert_point_range(partial, full, start, stop):
    if isinstance(full, _core.PointCloud):
        assert isinstance(partial, _core.PointCloud)
        assert partial.num_points == stop - start
        assert (
            partial.coordinate_frame,
            partial.scale_to_meters,
            partial.intensity_range,
            partial.origin,
        ) == (
            full.coordinate_frame,
            full.scale_to_meters,
            full.intensity_range,
            full.origin,
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
        ("las", bytes(_core.write_las(las))),
        ("gaussian_ply", bytes(_core.write_gaussian_ply(gaussians))),
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
            path, format="png", window=(0, 1, 0, 1), points=(0, 1)
        )
    with pytest.raises(TypeError, match="integers"):
        sceneio.read_partial(path, format="png", window=(False, 1, 0, 1))
    with pytest.raises(ValueError, match="exactly 4"):
        sceneio.read_partial(path, format="png", window=(0, 1, 2))
    with pytest.raises(FormatError, match="does not support pixel-window"):
        sceneio.read_partial(path, format="png", window=(0, 1, 0, 1))


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
            "ply",
            bytes(_core.write_ply(point_cloud))[:-1],
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
    else:
        value = sceneio.read_partial(
            sys.argv[1], format=sys.argv[2], points=(1000000, 1000008)
        )
    if isinstance(value, _core.Image):
        np.asarray(value.pixels).sum()
    elif isinstance(value, _core.GaussianCloud):
        np.asarray(value.means).sum()
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


def _fresh_process_colmap_error_rss(path, format_id, image_id):
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
        sceneio.read_partial(
            sys.argv[1], format=sys.argv[2], image_id=int(sys.argv[3])
        )
    except sceneio.FormatError:
        pass
    else:
        raise AssertionError("malformed model unexpectedly decoded")
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
            str(image_id),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(completed.stdout.strip())


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


def test_colmap_binary_checks_selected_observation_bytes_before_allocating(
    tmp_path,
):
    directory = tmp_path / "malformed-binary-model"
    directory.mkdir()
    source = _three_view_reconstruction()
    _core.write_colmap_sparse(source, str(directory))
    image_id = int(np.asarray(source.image_ids)[0])
    images_path = directory / "images.bin"
    encoded = bytearray(images_path.read_bytes())
    name_start = 8 + 4 + 4 * 8 + 3 * 8 + 4
    name_end = encoded.index(0, name_start)
    count_offset = name_end + 1
    encoded[count_offset : count_offset + 8] = struct.pack("<Q", 2_000_000)
    del encoded[count_offset + 8 :]
    images_path.write_bytes(encoded)
    with pytest.raises(FormatError, match="truncated image observations"):
        sceneio.read_partial(
            directory, format="colmap_sparse", image_id=image_id
        )
    assert (
        _fresh_process_colmap_error_rss(
            directory, "colmap_sparse", image_id
        )
        < 16 * 1024 * 1024
    )


def test_colmap_binary_validates_selected_name_terminator_before_allocating(
    tmp_path,
):
    directory = tmp_path / "unterminated-binary-name"
    directory.mkdir()
    source = _three_view_reconstruction()
    _core.write_colmap_sparse(source, str(directory))
    image_id = int(np.asarray(source.image_ids)[0])
    images_path = directory / "images.bin"
    prefix = images_path.read_bytes()[: 8 + 4 + 4 * 8 + 3 * 8 + 4]
    with images_path.open("wb") as stream:
        stream.write(prefix)
        block = b"x" * 65536
        for _ in range(512):
            stream.write(block)
    with pytest.raises(FormatError, match="truncated image name"):
        sceneio.read_partial(
            directory, format="colmap_sparse", image_id=image_id
        )
    assert (
        _fresh_process_colmap_error_rss(
            directory, "colmap_sparse", image_id
        )
        < 16 * 1024 * 1024
    )


def test_colmap_text_selected_malformed_token_is_memory_bounded(tmp_path):
    directory = tmp_path / "malformed-text-model"
    directory.mkdir()
    (directory / "cameras.txt").write_text(
        "1 PINHOLE 640 480 500 500 320 240\n",
        encoding="utf-8",
    )
    images_path = directory / "images.txt"
    with images_path.open("wb") as stream:
        stream.write(b"1 1 0 0 0 0 0 0 1 image.jpg\n")
        stream.seek(32 * 1024 * 1024, 1)
        stream.write(b"x\n")
    (directory / "points3D.txt").write_bytes(b"")
    with pytest.raises(FormatError, match="token exceeds 1 MiB"):
        sceneio.read_partial(
            directory, format="colmap_sparse_txt", image_id=1
        )
    assert (
        _fresh_process_colmap_error_rss(
            directory, "colmap_sparse_txt", 1
        )
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


def test_partial_flo_window_retains_mapping_and_is_read_only(tmp_path):
    path = tmp_path / "flow.flo"
    height, width = 6, 7
    values = np.arange(height * width * 2, dtype=np.float32).reshape(
        height, width, 2
    )
    path.write_bytes(
        b"PIEH" + struct.pack("<ii", width, height) + values.tobytes()
    )
    window = sceneio.read_partial(
        path, format="flo", window=(1, 5, 2, 6)
    )
    gc.collect()
    np.testing.assert_array_equal(window, values[1:5, 2:6])
    assert not window.flags.writeable
    with pytest.raises(ValueError):
        window[0, 0, 0] = 123.0


def test_invalid_flo_window_releases_mapping_with_retained_exception(
    tmp_path,
):
    path = tmp_path / "flow.flo"
    values = np.zeros((6, 7, 2), dtype=np.float32)
    path.write_bytes(b"PIEH" + struct.pack("<ii", 7, 6) + values.tobytes())
    retained = None
    try:
        sceneio.read_partial(
            path, format="flo", window=(0, 7, 0, 1)
        )
    except FormatError as error:
        retained = error
    assert retained is not None
    replacement = tmp_path / "flow-replaced.flo"
    path.replace(replacement)
    path.write_bytes(b"replacement")
