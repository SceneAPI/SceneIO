"""Parity suite for the Radiance HDR codec (hdr.cpp -> Image, via vendored stb).

RGBE decode is exact; RGBE encode quantizes each channel to an 8-bit mantissa
under a shared exponent. Oracle: a self-contained numpy RGBE decoder + a flat-HDR
builder/parser (stb writes the flat, non-RLE layout for width < 8, which the probe
confirmed as per-pixel R,G,B,E after the resolution line). That gives an external
anchor for the reader and an independent decode of the writer's bytes; wider
images exercise stb's RLE path via the codec round-trip.
"""

from __future__ import annotations

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")


# --- independent numpy RGBE oracle (Radiance/stb convention) -----------------
def rgbe_decode(rgbe):  # (H,W,4) u8 -> (H,W,3) f32
    rgbe = np.asarray(rgbe, np.uint8)
    e = rgbe[..., 3].astype(np.int32)
    f = np.ldexp(np.float32(1.0), e - 136).astype(np.float32)  # 2^(e - (128+8))
    out = (rgbe[..., :3].astype(np.float32) * f[..., None]).astype(np.float32)
    out[e == 0] = 0.0
    return out


def make_flat_hdr(rgbe):  # a hand-built flat .hdr from known RGBE bytes
    rgbe = np.asarray(rgbe, np.uint8)
    h, w = rgbe.shape[:2]
    return b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n" + f"-Y {h} +X {w}\n".encode() + rgbe.tobytes()


def parse_flat_hdr(data):  # our writer emits flat RGBE for width < 8
    i = data.index(b"\n\n") + 2
    j = data.index(b"\n", i)
    parts = data[i:j].split()
    h, w = int(parts[1]), int(parts[3])
    body = np.frombuffer(data[j + 1 : j + 1 + h * w * 4], np.uint8).reshape(h, w, 4)
    return rgbe_decode(body)


def assert_rgbe_close(orig, dec):
    # each channel's error is bounded by the pixel's max component * one mantissa
    # step (stb truncates the 8-bit mantissa under the shared exponent)
    orig, dec = np.asarray(orig, np.float32), np.asarray(dec, np.float32)
    maxc = np.max(np.abs(orig), axis=-1, keepdims=True)  # (H,W,1) broadcasts over channels
    err = np.abs(dec - orig)
    assert np.all(err <= maxc * (1.0 / 128.0) + 1e-6), f"max err {err.max()} exceeds RGBE tolerance"


def _px(img):
    return np.asarray(img.pixels)


# --- reader: external anchor with hand-derived exact values ------------------
def test_read_anchor():
    rgbe = np.array([[[128, 64, 32, 129], [32, 64, 128, 132]]], np.uint8)  # e129->2^-7, e132->2^-4
    img = _core.read_hdr(make_flat_hdr(rgbe))
    assert img.dtype == "float32" and img.channels == 3
    assert img.color_space == "linear" and img.alpha_mode == "none" and img.maxval == 0
    np.testing.assert_array_equal(_px(img), [[[1.0, 0.5, 0.25], [2.0, 4.0, 8.0]]])


# --- writer: our RGBE bytes decoded by the independent oracle recover the floats
def test_write_decodes_correctly():
    rng = np.random.default_rng(0)
    img = (rng.random((3, 6, 3), np.float32) * 10.0).astype(np.float32)  # width 6 < 8 -> flat
    dec = parse_flat_hdr(bytes(_core.write_hdr(_core.image(img, color_space="linear"))))
    assert_rgbe_close(img, dec)


@pytest.mark.parametrize("shape", [(4, 6, 3), (5, 40, 3)])  # 40 wide -> stb RLE path
def test_roundtrip_within_quant(shape):
    img = (np.random.default_rng(1).random(shape, np.float32) * 100.0).astype(np.float32)
    back = _px(_core.read_hdr(_core.write_hdr(_core.image(img, color_space="linear"))))
    assert_rgbe_close(img, back)


def test_roundtrip_idempotent():
    img = _core.image(
        (np.random.default_rng(2).random((4, 20, 3), np.float32) * 50).astype(np.float32),
        color_space="linear",
    )
    a = _core.read_hdr(_core.write_hdr(img))
    b = _core.read_hdr(_core.write_hdr(a))
    np.testing.assert_array_equal(_px(a), _px(b))  # RGBE is a fixed point after one encode


def test_high_dynamic_range():
    img = np.array([[[0.001, 0.001, 0.001], [1000.0, 500.0, 250.0]]], np.float32)
    back = _px(_core.read_hdr(_core.write_hdr(_core.image(img, color_space="linear"))))
    assert_rgbe_close(img, back)


def test_write_guards():
    with pytest.raises(ValueError, match="float32"):
        _core.write_hdr(_core.image(np.zeros((4, 4, 3), np.uint8), color_space="srgb"))
    with pytest.raises(ValueError, match=r"3-channel|RGB"):
        _core.write_hdr(_core.image(np.zeros((4, 4), np.float32)))  # C=1
    with pytest.raises(ValueError, match=r"3-channel|RGB"):
        _core.write_hdr(_core.image(np.zeros((4, 4, 4), np.float32), alpha_mode="straight"))  # C=4
    with pytest.raises(ValueError, match="linear"):
        _core.write_hdr(_core.image(np.zeros((4, 4, 3), np.float32), color_space="srgb"))


def test_malformed_raises():
    with pytest.raises(ValueError):
        _core.read_hdr(b"not a radiance file")


def test_read_rejects_jpeg_bytes():
    # stb compiles JPEG + HDR into one lib; a .jpg must not decode here as gamma-expanded f32
    with pytest.raises(ValueError, match=r"Radiance|signature"):
        _core.read_hdr(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01")


def test_write_rejects_out_of_range():
    # RGBE can't store negatives (float->uchar UB), non-finite, or >= 2^127
    for bad in ([[-1.0, 0.5, 0.5]], [[np.nan, 0.5, 0.5]], [[np.inf, 0.5, 0.5]], [[2e38, 0.5, 0.5]]):
        with pytest.raises(ValueError, match="RGBE"):
            _core.write_hdr(_core.image(np.array([bad], np.float32), color_space="linear"))


def test_read_truncated_body_raises():
    # exercises the vendored-stb short-read patch: a truncated .hdr must error, not
    # decode uninitialized stack bytes into pixels.
    full = make_flat_hdr(np.array([[[128, 64, 32, 129], [32, 64, 128, 132]]], np.uint8))
    with pytest.raises(ValueError):
        _core.read_hdr(full[:-4])  # drop the last pixel's RGBE


def test_write_byte_anchor():
    # writer byte-pin (independent of the reader): (1.0,0.5,0.25) -> RGBE (128,64,32,129).
    # frexp(1.0)=(0.5,1); norm=0.5*256/1=128; -> (1*128, .5*128, .25*128, 1+128).
    data = bytes(_core.write_hdr(_core.image(np.array([[[1.0, 0.5, 0.25]]], np.float32), color_space="linear")))
    assert data[-4:] == bytes([128, 64, 32, 129])


def test_read_dimension_bomb():
    with pytest.raises(ValueError, match=r"exceed|limit|dimensions"):
        _core.read_hdr(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 50000 +X 50000\n")


def test_torch_interop():
    torch = pytest.importorskip("torch")
    img = _core.read_hdr(_core.write_hdr(_core.image(np.ones((3, 4, 3), np.float32), color_space="linear")))
    assert np.array_equal(torch.from_dlpack(img.pixels).numpy(), _px(img))
