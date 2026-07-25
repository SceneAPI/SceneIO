"""Parity suite for the LAS codec (las.cpp -> PointCloud).

Oracle: laspy (independent of our hand parser). LAS quantizes XYZ to an i32 grid
* scale, so position checks are within scale/2; intensity (u16) and RGB (u16) are
exact. Positions are stored RELATIVE to the header offset (kept as .origin) so a
large georef offset doesn't crush the f32 xyz precision — a property the tests pin.
"""

from __future__ import annotations

import io
import struct

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")
laspy = pytest.importorskip("laspy")


def laspy_write(xyz_true, point_format=3, scales=(0.001, 0.001, 0.001), offsets=(0.0, 0.0, 0.0),
                intensity=None, rgb=None):
    hdr = laspy.LasHeader(version="1.4" if point_format >= 6 else "1.2", point_format=point_format)
    hdr.scales = list(scales)
    hdr.offsets = list(offsets)
    las = laspy.LasData(hdr)
    las.x, las.y, las.z = xyz_true[:, 0], xyz_true[:, 1], xyz_true[:, 2]
    if intensity is not None:
        las.intensity = intensity
    if rgb is not None:
        las.red, las.green, las.blue = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    buf = io.BytesIO()
    las.write(buf)
    return buf.getvalue()


def _true_xyz(pc):  # local coords + georef origin = the LAS true coordinates
    return np.asarray(pc.positions).astype(np.float64) + np.asarray(pc.origin)


def _sample(seed, n=20, off=(0.0, 0.0, 0.0)):
    rng = np.random.default_rng(seed)
    xyz = rng.random((n, 3)) * 100.0 + np.array(off)
    rgb = (rng.random((n, 3)) * 65535).astype(np.uint16)
    inten = (rng.random(n) * 60000).astype(np.uint16)
    return xyz, rgb, inten


# --- our write -> read round-trip -------------------------------------------
def test_roundtrip():
    xyz, rgb, inten = _sample(1, off=(500000.0, 4000000.0, 100.0))
    pc = _core.point_cloud(
        (xyz - [500000.0, 4000000.0, 100.0]).astype(np.float32),
        colors16=rgb, intensity=inten.astype(np.float32),
        origin=np.array([500000.0, 4000000.0, 100.0]),
    )
    back = _core.read_las(_core.write_las(pc, 0.001))
    assert back.num_points == 20 and back.has_rgb16 and back.intensity_range == "u16"
    # the invariant is true = positions + origin (origin is rebased to the first point)
    np.testing.assert_allclose(_true_xyz(back), xyz, atol=0.0005)  # within scale/2
    np.testing.assert_array_equal(np.asarray(back.colors16), rgb)
    np.testing.assert_array_equal(np.asarray(back.intensities), inten.astype(np.float32))


# --- our reader vs laspy across point formats -------------------------------
@pytest.mark.parametrize("fmt", [0, 1, 2, 3, 6, 7, 8])
def test_reads_laspy(fmt):
    xyz, rgb, inten = _sample(fmt + 2, off=(600000.0, 5000000.0, 50.0))
    color = fmt in (2, 3, 7, 8)
    data = laspy_write(xyz, fmt, offsets=(600000.0, 5000000.0, 50.0), intensity=inten,
                       rgb=rgb if color else None)
    pc = _core.read_las(data)
    assert pc.num_points == len(xyz)
    np.testing.assert_allclose(_true_xyz(pc), xyz, atol=0.001)
    np.testing.assert_array_equal(np.asarray(pc.intensities), inten.astype(np.float32))
    assert pc.has_rgb16 == color
    if color:
        np.testing.assert_array_equal(np.asarray(pc.colors16), rgb)  # fmt 8 NIR must not bleed into RGB


def test_reads_unequal_scales():
    # per-axis scales must be applied independently (a Y*sx/Z*sx bug would slip past isotropic data)
    xyz = _sample(50)[0]
    data = laspy_write(xyz, 1, scales=(0.001, 0.01, 0.1), intensity=_sample(50)[2])
    np.testing.assert_allclose(_true_xyz(_core.read_las(data)), xyz, atol=0.05)  # coarsest scale/2


def test_writer_raw_grid_mixed_sign():
    # our-write -> laspy raw i32 grid: pins signedness AND round-half-away (not truncate)
    local = np.array([[-1.2367, 3.5, -0.4999], [12.3456, -6.7, 0.5001], [0.0, 0.0, 0.0]], np.float32)
    las = laspy.read(io.BytesIO(bytes(_core.write_las(_core.point_cloud(local), 0.001))))
    exp = np.round(local.astype(np.float64) / 0.001)
    np.testing.assert_array_equal(np.asarray(las.X), exp[:, 0].astype(np.int64))
    np.testing.assert_array_equal(np.asarray(las.Y), exp[:, 1].astype(np.int64))
    np.testing.assert_array_equal(np.asarray(las.Z), exp[:, 2].astype(np.int64))


# --- laspy reads our writer (independent writer check) ----------------------
def test_laspy_reads_our_writer():
    xyz, rgb, inten = _sample(9, off=(400000.0, 3000000.0, 0.0))
    pc = _core.point_cloud(
        (xyz - [400000.0, 3000000.0, 0.0]).astype(np.float32),
        colors16=rgb, intensity=inten.astype(np.float32),
        origin=np.array([400000.0, 3000000.0, 0.0]),
    )
    las = laspy.read(io.BytesIO(bytes(_core.write_las(pc, 0.001))))
    assert las.header.point_format.id == 2  # color present -> format 2
    np.testing.assert_allclose(np.asarray(las.x), xyz[:, 0], atol=0.001)
    np.testing.assert_array_equal(np.asarray(las.red), rgb[:, 0])
    np.testing.assert_array_equal(np.asarray(las.intensity), inten)


def test_georef_precision_preserved():
    # local coords kept in f32, offset in double -> a UTM-scale origin doesn't
    # destroy sub-mm local precision (the reason origin exists)
    local = np.array([[0.0, 0.0, 0.0], [1.2345, 6.789, 0.5]], np.float32)
    pc = _core.point_cloud(local, origin=np.array([500000.0, 4000000.0, 0.0]))
    back = _core.read_las(_core.write_las(pc, 0.001))
    np.testing.assert_allclose(np.asarray(back.positions), local, atol=0.001)


# --- rejections --------------------------------------------------------------
def test_reject_laz():
    data = bytearray(bytes(_core.write_las(_core.point_cloud(_sample(3)[0][:5].astype(np.float32)))))
    data[104] |= 0x80  # set the compressed (LAZ) high bit of the point-format byte
    with pytest.raises(ValueError, match="LAZ"):
        _core.read_las(bytes(data))


@pytest.mark.parametrize("fmt", [4, 5, 9, 10])
def test_reject_waveform_format(fmt):
    data = bytearray(bytes(_core.write_las(_core.point_cloud(_sample(4)[0][:5].astype(np.float32)))))
    data[104] = fmt  # waveform / unsupported format
    with pytest.raises(ValueError, match="format"):
        _core.read_las(bytes(data))


def test_reader_guards():
    valid = bytearray(bytes(_core.write_las(_core.point_cloud(_sample(55)[0].astype(np.float32)))))
    v = bytearray(valid)
    v[96:100] = struct.pack("<I", 100)  # offset_to_points < 227
    with pytest.raises(ValueError, match=r"truncated|malformed"):
        _core.read_las(bytes(v))
    v = bytearray(valid)
    v[104] = 2  # claim color format 2 (needs a 26-byte record) but keep the 20-byte record length
    with pytest.raises(ValueError, match=r"short|length"):
        _core.read_las(bytes(v))


def test_writer_guards():
    xyz = _sample(5, n=4)[0].astype(np.float32)
    with pytest.raises(ValueError, match="normals"):
        _core.write_las(_core.point_cloud(xyz, normals=xyz))
    with pytest.raises(ValueError, match="colors16"):
        _core.write_las(_core.point_cloud(xyz, colors=np.zeros((4, 3), np.uint8)))
    with pytest.raises(ValueError, match="intensity"):  # 'unit'-ranged intensity must be rescaled first
        _core.write_las(_core.point_cloud(xyz, intensity=np.ones(4, np.float32) * 0.5, intensity_range="unit"))
    with pytest.raises(ValueError, match="scale"):
        _core.write_las(_core.point_cloud(xyz), 0.0)
    with pytest.raises(ValueError, match="scale"):
        _core.write_las(_core.point_cloud(xyz), float("inf"))
    with pytest.raises(ValueError, match=r"32-bit|grid|finite"):
        _core.write_las(_core.point_cloud(np.array([[1e9, 0, 0]], np.float32)), 0.001)


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    [
        (131, float("nan"), "scales"),
        (139, 0.0, "scales"),
        (155, float("inf"), "offsets"),
    ],
)
def test_reader_rejects_invalid_coordinate_transform(offset, value, message):
    data = bytearray(
        bytes(
            _core.write_las(
                _core.point_cloud(_sample(56)[0].astype(np.float32))
            )
        )
    )
    struct.pack_into("<d", data, offset, value)

    with pytest.raises(ValueError, match=message):
        _core.read_las(bytes(data))


def test_intensity_extremes_and_bbox():
    xyz = _sample(52, n=6)[0].astype(np.float32)
    inten = np.array([0.0, 0.4, 0.6, 65535.0, 70000.0, -3.0], np.float32)  # round + clamp
    las = laspy.read(io.BytesIO(bytes(_core.write_las(
        _core.point_cloud(xyz, intensity=inten, intensity_range="u16"), 0.001))))
    np.testing.assert_array_equal(np.asarray(las.intensity), [0, 0, 1, 65535, 65535, 0])
    q = np.round(xyz.astype(np.float64) / 0.001) * 0.001  # header bbox = quantized true coords
    np.testing.assert_allclose(las.header.maxs, q.max(0), atol=1e-6)
    np.testing.assert_allclose(las.header.mins, q.min(0), atol=1e-6)


def test_xyz_writer_rejects_las_fields():
    # the PointCloud extension must not let write_xyz silently drop 16-bit color / georef
    xyz = _sample(53, n=4)[0].astype(np.float32)
    with pytest.raises(ValueError, match="colors16"):
        _core.write_xyz(_core.point_cloud(xyz, colors16=np.zeros((4, 3), np.uint16)))
    with pytest.raises(ValueError, match="origin"):
        _core.write_xyz(_core.point_cloud(xyz, origin=np.array([1000.0, 0.0, 0.0])))


def test_malformed_raises():
    with pytest.raises(ValueError, match=r"signature|LASF"):
        _core.read_las(b"NOPE" + b"\x00" * 300)
    with pytest.raises(ValueError, match="header"):
        _core.read_las(b"LASF" + b"\x00" * 50)  # too short for the header
    valid = bytes(_core.write_las(_core.point_cloud(_sample(6)[0].astype(np.float32))))
    with pytest.raises(ValueError, match=r"truncated|malformed"):
        _core.read_las(valid[:-40])  # drop point records


def test_empty_cloud():
    pc = _core.point_cloud(np.zeros((0, 3), np.float32))
    back = _core.read_las(_core.write_las(pc))
    assert back.num_points == 0


def test_torch_interop():
    torch = pytest.importorskip("torch")
    pc = _core.read_las(_core.write_las(_core.point_cloud(_sample(7)[0].astype(np.float32))))
    assert np.array_equal(torch.from_dlpack(pc.positions).numpy(), np.asarray(pc.positions))
