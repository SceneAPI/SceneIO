"""O5 partial-read differential, bounds, lifetime, and memory coverage."""

from __future__ import annotations

import gc
import os
import struct
import tracemalloc

import numpy as np
import pytest
from _support.partial_read import (
    _assert_image_window,
    _assert_point_range,
    _fresh_process_partial_rss,
    _pixels,
)

import sceneio
from sceneio import FormatError, _core


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
        ("flo", bytes(_core.write_flo(_core.flow_field(flow)))),
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


def _splat_case(cloud):
    return _core.gaussian_cloud(
        np.asarray(cloud.means),
        np.asarray(cloud.scales),
        np.asarray(cloud.quaternions),
        np.asarray(cloud.opacities),
        np.asarray(cloud.sh_dc),
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
        ("splat", bytes(_core.write_splat(_splat_case(gaussians)))),
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
                    _core.flow_field(
                        rng.standard_normal((7, 9, 2)).astype(np.float32)
                    )
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
            bytes(_core.write_splat(_splat_case(gaussians))) + b"\x00",
            {"points": (0, 1)},
        ),
    )
    for index, (format_id, encoded, selector) in enumerate(cases):
        path = tmp_path / f"truncated-{index}.data"
        path.write_bytes(encoded)
        with pytest.raises(FormatError):
            sceneio.read_partial(path, format=format_id, **selector)


def _traced_peak(call):
    gc.collect()
    tracemalloc.start()
    try:
        value = call()
        _, peak = tracemalloc.get_traced_memory()
        return value, peak
    finally:
        tracemalloc.stop()


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
    valid_splat = struct.pack(
        "<6f8B",
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        1.0,
        128,
        128,
        128,
        255,
        255,
        128,
        128,
        128,
    )
    with splat.open("wb") as stream:
        stream.truncate(3_200_000 * 32)
        stream.seek(1_000_000 * 32)
        stream.write(valid_splat * 8)
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
