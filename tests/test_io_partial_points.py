"""Point-family O5 partial-read behavior coverage."""

from __future__ import annotations

import io

import numpy as np
import pytest
from _support.partial_read import _assert_point_range

import sceneio
from sceneio import _core


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
