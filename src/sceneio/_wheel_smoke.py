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


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sceneio-wheel-smoke-") as directory:
        root = Path(directory)
        values = np.arange(12, dtype=np.float32).reshape(3, 4)
        _pfm_and_typed_depth(root, values)
        _mapped_safetensors(root, values)
        _point_depth_and_flow(root, values)
        _reconstruction_and_images(root)
    print(_core.__phase__)


if __name__ == "__main__":
    main()
