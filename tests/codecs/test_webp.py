"""Parity suite for the WebP codec (webp.cpp -> Image, via libwebp).

Oracle: Pillow (independent of the libwebp we vendor... Pillow bundles its own
libwebp, so cross-parity checks conformance, not self-agreement). Lossless WebP is
byte-exact both directions; lossy is PSNR-bounded. RGB or RGBA (straight alpha);
grayscale / 16-bit / float are refused (WebP has no such representation).
"""

from __future__ import annotations

import io

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")
PIL = pytest.importorskip("PIL.Image")


def psnr(a, b):
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return float("inf") if mse == 0 else 10.0 * np.log10(255.0**2 / mse)


def smooth_rgb(h=48, w=64, c=3):
    y, x = np.mgrid[0:h, 0:w]
    ch = [x * 255 // w, y * 255 // h, (x + y) * 255 // (w + h), (x * y) % 256][:c]
    return np.stack(ch, -1).astype(np.uint8)


def rand(shape, seed):
    return np.random.default_rng(seed).integers(0, 256, shape, dtype=np.uint8)


def pil_webp(arr, **kw):
    buf = io.BytesIO()
    PIL.fromarray(arr).save(buf, "WEBP", **kw)
    return buf.getvalue()


def pil_decode(data):
    return np.asarray(PIL.open(io.BytesIO(data)))


def _px(img):
    return np.asarray(img.pixels)


def _img(arr, am=None):
    am = am if am is not None else ("straight" if arr.shape[-1] == 4 else "none")
    return _core.image(arr, color_space="srgb", alpha_mode=am)


# --- lossless is byte-exact both ways ----------------------------------------
@pytest.mark.parametrize("c", [3, 4])
def test_lossless_roundtrip(c):
    arr = rand((10, 14, c), c)
    back = _core.read_webp(_core.write_webp(_img(arr), lossless=True))
    np.testing.assert_array_equal(_px(back), arr)
    assert back.channels == c and back.dtype == "uint8" and back.color_space == "srgb"
    assert back.alpha_mode == ("straight" if c == 4 else "none")


def test_exact_keeps_rgb_under_zero_alpha():
    # config.exact=1: RGB samples under alpha=0 must survive (no premultiply/zeroing)
    arr = rand((6, 8, 4), 99)
    arr[..., 3] = 0  # fully transparent, but RGB is non-zero
    back = _px(_core.read_webp(_core.write_webp(_img(arr), lossless=True)))
    np.testing.assert_array_equal(back, arr)


@pytest.mark.parametrize("c", [3, 4])
def test_reads_pillow_lossless(c):
    arr = rand((9, 11, c), c + 10)
    np.testing.assert_array_equal(_px(_core.read_webp(pil_webp(arr, lossless=True, exact=True))), arr)


@pytest.mark.parametrize("c", [3, 4])
def test_pillow_reads_our_lossless(c):
    arr = rand((9, 11, c), c + 20)
    got = pil_decode(bytes(_core.write_webp(_img(arr), lossless=True)))
    np.testing.assert_array_equal(got, arr)


# --- lossy is bounded --------------------------------------------------------
def test_lossy_bounded_and_quality_tradeoff():
    arr = smooth_rgb()
    lo = bytes(_core.write_webp(_img(arr), lossless=False, quality=20))
    hi = bytes(_core.write_webp(_img(arr), lossless=False, quality=95))
    assert len(hi) > len(lo)
    assert psnr(_px(_core.read_webp(hi)), arr) >= 35.0
    assert psnr(_px(_core.read_webp(hi)), arr) > psnr(_px(_core.read_webp(lo)), arr)


def test_lossy_rgba():
    # the VP8X/extended-container + lossy-alpha path (all lossless RGBA is plain VP8L).
    # SMOOTH data (random noise is worst-case for lossy); default alpha_quality=100
    # codes the alpha plane losslessly, so alpha is exact and RGB is PSNR-bounded.
    rgba = smooth_rgb(32, 48, 4)  # channel 3 = (x*y)%256, exercised as the alpha plane
    back = _core.read_webp(_core.write_webp(_img(rgba), lossless=False, quality=90))
    assert back.channels == 4 and back.alpha_mode == "straight"
    b = _px(back)
    np.testing.assert_array_equal(b[..., 3], rgba[..., 3])  # alpha lossless
    assert psnr(b[..., :3], rgba[..., :3]) >= 28.0
    assert pil_decode(bytes(_core.write_webp(_img(rgba), lossless=False, quality=90))).shape == (32, 48, 4)


def test_opaque_rgba_collapses_to_rgb():
    # documented format behavior: a fully-opaque (all-255) alpha is dropped, so an
    # opaque RGBA round-trips to 3-channel RGB with identical RGB values.
    rgba = rand((6, 8, 4), 88)
    rgba[..., 3] = 255
    back = _core.read_webp(_core.write_webp(_img(rgba), lossless=True))
    assert back.channels == 3
    np.testing.assert_array_equal(_px(back), rgba[..., :3])


@pytest.mark.parametrize("shape", [(1, 16383, 3), (16383, 1, 3)])
def test_max_dimension_accepted(shape):
    arr = rand(shape, 3)
    np.testing.assert_array_equal(_px(_core.read_webp(_core.write_webp(_img(arr), lossless=True))), arr)


def test_quality_extremes_and_determinism():
    arr = smooth_rgb()
    for q in (0.0, 100.0):  # valid boundary qualities encode + decode
        assert _core.read_webp(_core.write_webp(_img(arr), lossless=False, quality=q)).channels == 3
    a = bytes(_core.write_webp(_img(arr), lossless=True))
    assert a == bytes(_core.write_webp(_img(arr), lossless=True))  # deterministic (reproducible wheels)


# --- rejects -----------------------------------------------------------------
def test_reject_animated():
    frames = [PIL.fromarray(rand((8, 8, 3), i)) for i in range(3)]
    buf = io.BytesIO()
    try:
        frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=100)
    except Exception:
        pytest.skip("Pillow could not write an animated WebP in this environment")
    with pytest.raises(ValueError, match="animated"):
        _core.read_webp(buf.getvalue())


def test_malformed_raises():
    with pytest.raises(ValueError, match=r"valid WebP|WebP"):
        _core.read_webp(b"RIFF\x00\x00\x00\x00WEBPnope")
    with pytest.raises(ValueError):
        _core.read_webp(bytes(pil_webp(rand((8, 8, 3), 1), lossless=True))[:20])  # truncated


def test_writer_guards():
    rgb = rand((4, 4, 3), 5)
    with pytest.raises(ValueError, match="8-bit"):
        _core.write_webp(_core.image((rgb.astype(np.uint16) * 257), color_space="srgb"))
    with pytest.raises(ValueError, match="8-bit"):
        _core.write_webp(_core.image(rgb.astype(np.float32), color_space="srgb"))
    with pytest.raises(ValueError, match=r"grayscale|RGB"):
        _core.write_webp(_core.image(rand((4, 4), 6), color_space="gray"))
    with pytest.raises(ValueError, match="srgb"):
        _core.write_webp(_core.image(rgb, color_space="linear"))
    with pytest.raises(ValueError, match="straight"):
        _core.write_webp(_core.image(rand((4, 4, 4), 7), alpha_mode="premultiplied"))
    with pytest.raises(ValueError, match="maxval"):
        _core.write_webp(_core.image(rand((4, 4, 3), 9), color_space="srgb", maxval=100))
    with pytest.raises(ValueError, match="16383"):
        _core.write_webp(_core.image(np.zeros((1, 16384, 3), np.uint8), color_space="srgb"))
    for q in (-1.0, 101.0):
        with pytest.raises(ValueError, match="quality"):
            _core.write_webp(_img(rgb), lossless=False, quality=q)


def test_torch_interop():
    torch = pytest.importorskip("torch")
    img = _core.read_webp(_core.write_webp(_img(rand((5, 6, 4), 8)), lossless=True))
    assert np.array_equal(torch.from_dlpack(img.pixels).numpy(), _px(img))
