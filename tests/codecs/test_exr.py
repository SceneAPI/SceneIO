"""Parity suite for the OpenEXR codec (exr.cpp -> Image, via vendored tinyexr).

Oracle: the OpenEXR python package (independent of tinyexr). EXR FLOAT is lossless,
so the checks are strict value equality both directions; HALF widens to FLOAT
(also exact). The modern OpenEXR API groups R/G/B(/A) into one "RGB"/"RGBA" entry
on read and ignores numpy strides on write, so oracle channels are made contiguous.
"""

from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")
OpenEXR = pytest.importorskip("OpenEXR")


def _tmp():
    fd, p = tempfile.mkstemp(suffix=".exr")
    os.close(fd)
    return p


def oracle_write(channels, **hdr):
    h = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}
    h.update(hdr)
    ch = {k: np.ascontiguousarray(v) for k, v in channels.items()}  # OpenEXR ignores strides
    p = _tmp()
    try:
        with OpenEXR.File(h, ch) as f:
            f.write(p)
        with open(p, "rb") as fh:
            return fh.read()
    finally:
        os.remove(p)


def oracle_read(data):
    p = _tmp()
    try:
        with open(p, "wb") as fh:
            fh.write(data)
        with OpenEXR.File(p) as f:
            return {k: np.asarray(v.pixels) for k, v in f.parts[0].channels.items()}
    finally:
        os.remove(p)


def _px(img):
    return np.asarray(img.pixels)


def _lin(arr, am="none"):
    return _core.image(arr, color_space="linear", alpha_mode=am)


def _rand(shape, seed):
    return (np.random.default_rng(seed).random(shape, np.float32) * 100.0).astype(np.float32)


CELLS = [((5, 7), 1, "none"), ((5, 7, 3), 3, "none"), ((5, 7, 4), 4, "premultiplied")]


# --- FLOAT is lossless: our write.read is exact across the supported matrix -----
@pytest.mark.parametrize(("shape", "c", "am"), CELLS)
def test_roundtrip_exact(shape, c, am):
    arr = _rand(shape, c)
    back = _core.read_exr(_core.write_exr(_lin(arr, am)))
    np.testing.assert_array_equal(_px(back), arr)
    assert back.dtype == "float32" and back.channels == c
    assert back.color_space == "linear" and back.alpha_mode == am and back.maxval == 0


# --- our reader vs the OpenEXR oracle (independent), FLOAT channels -------------
def test_reads_oracle_rgb():
    rgb = _rand((4, 6, 3), 10)
    data = oracle_write({c: rgb[:, :, i] for i, c in enumerate("RGB")})
    im = _core.read_exr(data)
    assert im.channels == 3
    np.testing.assert_array_equal(_px(im), rgb)


def test_reads_oracle_rgba_premultiplied():
    rgba = _rand((4, 6, 4), 11)
    data = oracle_write({c: rgba[:, :, i] for i, c in enumerate("RGBA")})
    im = _core.read_exr(data)
    assert im.channels == 4 and im.alpha_mode == "premultiplied"  # EXR associated-alpha convention
    np.testing.assert_array_equal(_px(im), rgba)


def test_reads_oracle_single_channel():
    y = _rand((4, 6), 12)
    im = _core.read_exr(oracle_write({"Y": y}))
    assert im.channels == 1
    np.testing.assert_array_equal(_px(im), y)


def test_reads_half_widened_to_float():
    # HALF channels must widen to float32 losslessly (every half is exact in f32)
    h = _rand((4, 6, 3), 13).astype(np.float16)
    data = oracle_write({c: h[:, :, i].astype(np.float16) for i, c in enumerate("RGB")})
    im = _core.read_exr(data)
    assert im.dtype == "float32"
    np.testing.assert_array_equal(_px(im), h.astype(np.float32))


# --- OpenEXR reads OUR writer's output (independent), incl. channel naming ------
@pytest.mark.parametrize(
    ("shape", "c", "am", "key"),
    [(c[0], c[1], c[2], k) for c, k in zip(CELLS, ["Y", "RGB", "RGBA"], strict=True)],
)
def test_oracle_reads_our_writer(shape, c, am, key):
    arr = _rand(shape, c + 20)
    got = oracle_read(bytes(_core.write_exr(_lin(arr, am))))
    assert set(got.keys()) == {key}  # our channel naming (Y / R,G,B / R,G,B,A -> grouped)
    np.testing.assert_array_equal(got[key], arr)


# --- rejections: never a silent lossy conversion -------------------------------
def test_reject_uint_channels():
    z = np.ascontiguousarray((np.random.default_rng(0).random((4, 6)) * 1000).astype(np.uint32))
    with pytest.raises(ValueError, match=r"UINT|integer"):
        _core.read_exr(oracle_write({"Z": z}))


def test_reject_extra_channels():
    # {R,G,B,Z}: R/G/B present but a Z channel too -> must reject, not silently drop Z
    rgb = _rand((4, 6, 3), 38)
    z = _rand((4, 6), 39)
    data = oracle_write({"R": rgb[:, :, 0], "G": rgb[:, :, 1], "B": rgb[:, :, 2], "Z": z})
    with pytest.raises(ValueError, match="channel set"):
        _core.read_exr(data)


def test_reject_deep_multipart_tiled():
    # deterministic: flip the version flag bits (byte 5: 0x02 tiled, 0x08 deep, 0x10 multipart)
    valid = bytearray(bytes(_core.write_exr(_lin(_rand((8, 8, 3), 33)))))
    for bit, word in [(0x08, "deep"), (0x10, "multipart"), (0x02, "tiled")]:
        v = bytearray(valid)
        v[5] |= bit
        with pytest.raises(ValueError, match=word):
            _core.read_exr(bytes(v))


@pytest.mark.parametrize("comp", ["ZIP", "ZIPS", "RLE", "PIZ", "NO"])
def test_reads_oracle_compressions(comp):
    # every accepted compression is lossless -> exact equality (only ZIP was covered before)
    rgb = _rand((20, 12, 3), 35)  # > 16 rows: exercises multi-chunk decode (PIZ especially)
    data = oracle_write(
        {c: rgb[:, :, i] for i, c in enumerate("RGB")},
        compression=getattr(OpenEXR, comp + "_COMPRESSION"),
    )
    np.testing.assert_array_equal(_px(_core.read_exr(data)), rgb)


def test_reject_dwaa_compression():
    rgb = _rand((8, 8, 3), 36)
    try:
        data = oracle_write({c: rgb[:, :, i] for i, c in enumerate("RGB")}, compression=OpenEXR.DWAA_COMPRESSION)
    except Exception:
        pytest.skip("OpenEXR could not write DWAA in this environment")
    with pytest.raises(ValueError):  # tinyexr rejects DWAA at header parse
        _core.read_exr(data)


def test_reads_decreasing_y():
    # DECREASING_Y is spec-legal; tinyexr places scanlines by absolute y, so it must
    # decode top-to-bottom the same as INCREASING_Y (> 16 rows so chunk order differs)
    rgb = _rand((20, 8, 3), 37)
    data = oracle_write(
        {c: rgb[:, :, i] for i, c in enumerate("RGB")}, lineOrder=OpenEXR.LineOrder.DECREASING_Y
    )
    np.testing.assert_array_equal(_px(_core.read_exr(data)), rgb)


def test_special_float_values():
    # EXR is float: negatives, -0.0, denormals, NaN, +-Inf, huge magnitudes survive exactly
    special = np.array([-1.5, -0.0, 0.0, 1e-40, np.nan, np.inf, -np.inf, 3e38, 65504.0], np.float32)
    arr = np.tile(special, (4, 1)).astype(np.float32)  # (4,9) single channel
    back = _px(_core.read_exr(_core.write_exr(_lin(arr))))
    np.testing.assert_array_equal(back, arr)  # assert_array_equal treats NaN as equal by position
    assert np.array_equal(np.signbit(back), np.signbit(arr))  # -0.0 sign preserved


def test_dimension_bomb():
    # patch the dataWindow attribute to claim 60000x60000 (3.6e9 px) -> refused by the cap
    data = bytearray(bytes(_core.write_exr(_lin(_rand((8, 8, 3), 34)))))
    import struct as _struct

    k = data.index(b"dataWindow\x00box2i\x00")
    off = k + len(b"dataWindow\x00box2i\x00") + 4  # skip the 4-byte attr size -> min_x
    data[off + 8 : off + 12] = _struct.pack("<i", 60000)  # max_x
    data[off + 12 : off + 16] = _struct.pack("<i", 60000)  # max_y
    with pytest.raises(ValueError, match=r"exceed|limit"):
        _core.read_exr(bytes(data))


def test_malformed_raises():
    with pytest.raises(ValueError):
        _core.read_exr(b"not an exr file at all")
    valid = bytes(_core.write_exr(_lin(_rand((8, 8, 3), 40))))
    with pytest.raises(ValueError):
        _core.read_exr(valid[:30])  # truncated


# --- writer guards -------------------------------------------------------------
def test_write_guards():
    rgb = _rand((3, 3, 3), 50)
    with pytest.raises(ValueError, match="float32"):
        _core.write_exr(_core.image((rgb * 0).astype(np.uint8), color_space="linear"))
    with pytest.raises(ValueError, match="float32"):
        _core.write_exr(_core.image((rgb * 0).astype(np.uint16), color_space="linear"))
    with pytest.raises(ValueError, match="linear"):
        _core.write_exr(_core.image(rgb, color_space="srgb"))
    with pytest.raises(ValueError, match="premultiplied"):
        _core.write_exr(_core.image(_rand((3, 3, 4), 51), color_space="linear", alpha_mode="straight"))


def test_torch_interop():
    torch = pytest.importorskip("torch")
    img = _core.read_exr(_core.write_exr(_lin(_rand((3, 4, 4), 60), "premultiplied")))
    assert np.array_equal(torch.from_dlpack(img.pixels).numpy(), _px(img))
