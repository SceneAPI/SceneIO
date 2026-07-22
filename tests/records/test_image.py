"""Record-level suite for the Image raster record (reconciled design:
PixelType {U8,U16,F32} + color_space/alpha_mode conventions + the netpbm
`maxval` sample-range field).

Mirrors tests/codecs/test_pfm.py: numpy is the self-contained oracle (the
factory + ``pixels`` round-trip must reproduce the source array bit-exactly),
plus convention pins, zero-copy/lifetime checks, and numpy/torch interop.

This is a *record* (not a codec), so there are no read_*/write_* here. The
three codec-tier parity kinds ride on this record once the netpbm codec lands
(tests/codecs/test_netpbm.py); this file pins the record contract those codecs
build on.
"""

from __future__ import annotations

import gc

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception as exc:  # pragma: no cover - exercised only in a non-built tree
    _core = None
    _import_error = exc

pytestmark = pytest.mark.skipif(
    _core is None,
    reason="sceneio._core not built (compiled-only package — build the extension first)",
)


@pytest.fixture
def samples() -> dict[str, np.ndarray]:
    """One color (H,W,3) array per supported dtype."""
    rng = np.random.default_rng(0)
    return {
        "u8": rng.integers(0, 256, size=(5, 7, 3)).astype(np.uint8),
        "u16": rng.integers(0, 65536, size=(4, 6, 3)).astype(np.uint16),
        "f32": rng.standard_normal((3, 5, 3)).astype(np.float32),
    }


# --- factory round-trip identity (numpy is the oracle) ---------------------
def test_factory_roundtrip_per_dtype(samples):
    for arr in samples.values():
        im = _core.image(arr)
        np.testing.assert_array_equal(im.pixels, arr)  # bit-exact, rtol=atol=0
        assert im.pixels.dtype == arr.dtype
        assert im.pixels.shape == arr.shape
        assert (im.height, im.width, im.channels) == arr.shape


def test_dtype_string_is_numpy_compatible(samples):
    for arr in samples.values():
        im = _core.image(arr)
        assert np.dtype(im.dtype) == arr.dtype
        assert np.dtype(im.dtype) == im.pixels.dtype
        # __repr__ carries "HxWxC dtype color_space"
        h, w, c = arr.shape
        assert repr(im) == f"<Image {h}x{w}x{c} {im.dtype} {im.color_space}>"


# --- grayscale / color / alpha representation ------------------------------
def test_grayscale_representation():
    rng = np.random.default_rng(1)
    gray = rng.integers(0, 256, size=(5, 7)).astype(np.uint8)
    im = _core.image(gray)
    assert im.channels == 1
    assert im.pixels.shape == (5, 7)  # gray surfaces as 2-D (H,W), like read_pfm
    assert im.channel_order == "gray"
    assert im.color_space == "gray"  # default for C==1
    np.testing.assert_array_equal(im.pixels, gray)

    # (H,W,1) normalizes to channels==1 and a 2-D (H,W) view
    im1 = _core.image(gray[:, :, None])
    assert im1.channels == 1
    assert im1.pixels.shape == (5, 7)
    np.testing.assert_array_equal(im1.pixels, gray)


def test_color_and_alpha_shapes():
    rng = np.random.default_rng(2)
    rgb = rng.integers(0, 256, size=(4, 6, 3)).astype(np.uint8)
    im = _core.image(rgb)
    assert im.channels == 3
    assert im.channel_order == "rgb"
    assert im.alpha_mode == "none"
    assert im.color_space == "srgb"  # default for C!=1

    rgba = rng.integers(0, 256, size=(4, 6, 4)).astype(np.uint8)
    ima = _core.image(rgba)
    assert ima.channels == 4
    assert ima.pixels.shape == (4, 6, 4)
    assert ima.channel_order == "rgba"
    assert ima.alpha_mode == "straight"  # default for C==4


# --- convention pins (fixed canon) -----------------------------------------
def test_convention_rows_top_to_bottom():
    arr = np.arange(12, dtype=np.uint8).reshape(3, 4)  # arr[0,0]==0 in the top-left
    im = _core.image(arr)
    assert im.row_order == "top_to_bottom"  # always fixed
    assert im.pixels[0, 0] == 0  # top-left origin preserved
    assert im.pixels[-1, -1] == 11
    np.testing.assert_array_equal(im.pixels, arr)


# --- metadata recording + factory validation -------------------------------
def test_metadata_recording():
    rgb = np.zeros((3, 4, 3), np.uint8)
    assert _core.image(rgb, color_space="linear").color_space == "linear"
    assert _core.image(rgb, color_space="unknown").color_space == "unknown"
    rgba = np.zeros((3, 4, 4), np.uint8)
    assert _core.image(rgba, alpha_mode="premultiplied").alpha_mode == "premultiplied"


def test_validation_errors():
    u8_rgb = np.zeros((3, 4, 3), np.uint8)
    u8_rgba = np.zeros((3, 4, 4), np.uint8)
    with pytest.raises(ValueError):  # unknown color_space vocabulary
        _core.image(u8_rgb, color_space="bt709")
    with pytest.raises(ValueError):  # straight alpha needs C==4
        _core.image(u8_rgb, alpha_mode="straight")
    with pytest.raises(ValueError):  # C==4 may not be 'none'
        _core.image(u8_rgba, alpha_mode="none")
    with pytest.raises(ValueError):  # unsupported dtype float64
        _core.image(np.zeros((3, 4, 3), np.float64))
    with pytest.raises(ValueError):  # unsupported dtype int32
        _core.image(np.zeros((3, 4, 3), np.int32))
    with pytest.raises(ValueError):  # C==2 (gray+alpha not representable)
        _core.image(np.zeros((3, 4, 2), np.uint8))
    with pytest.raises(ValueError):  # C==5
        _core.image(np.zeros((3, 4, 5), np.uint8))
    with pytest.raises(ValueError):  # zero-size
        _core.image(np.zeros((0, 4), np.uint8))
    with pytest.raises(ValueError):  # 1-D
        _core.image(np.zeros((4,), np.uint8))
    with pytest.raises(ValueError):  # 4-D
        _core.image(np.zeros((2, 3, 4, 3), np.uint8))


# --- maxval sample-range field (reconciled from the netpbm design) ---------
def test_maxval_defaults():
    assert _core.image(np.zeros((2, 2), np.uint8)).maxval == 255
    assert _core.image(np.zeros((2, 2), np.uint16)).maxval == 65535
    assert _core.image(np.zeros((2, 2), np.float32)).maxval == 0


def test_maxval_override_and_validation():
    # explicit maxval within the dtype's storable range is recorded verbatim
    assert _core.image(np.zeros((2, 2), np.uint16), maxval=1023).maxval == 1023
    assert _core.image(np.zeros((2, 2), np.uint8), maxval=200).maxval == 200
    with pytest.raises(ValueError):  # > 255 cannot be stored in uint8
        _core.image(np.zeros((2, 2), np.uint8), maxval=1000)
    with pytest.raises(ValueError):  # maxval 0 is degenerate for an integer dtype
        _core.image(np.zeros((2, 2), np.uint8), maxval=0)


# --- zero-copy + lifetime (the sio::view owner keepalive gate) -------------
def test_zero_copy_two_views_share_buffer(samples):
    im = _core.image(samples["u8"])
    a = im.pixels
    b = im.pixels
    assert a.ctypes.data == b.ctypes.data  # no copy; both view the record's buffer
    np.testing.assert_array_equal(a, b)


def test_pixels_keeps_image_alive_after_gc(samples):
    # The Image is never bound to a name — only the returned view references it
    # (through the sio::view owner). If the keepalive is wrong, gc frees the
    # record and px then reads freed memory.
    for arr in samples.values():
        expected = arr.copy()
        px = _core.image(arr).pixels
        gc.collect()
        gc.collect()
        np.testing.assert_array_equal(px, expected)  # buffer intact after collection

    ramp = np.arange(24, dtype=np.uint8).reshape(2, 4, 3)
    px = _core.image(ramp).pixels
    gc.collect()
    assert px[0, 0, 0] == 0
    assert px[-1, -1, -1] == 23
    assert int(px.sum()) == sum(range(24))


# --- cross-framework interop (torch, optional) -----------------------------
def test_torch_from_dlpack(samples):
    torch = pytest.importorskip("torch")
    for arr in samples.values():
        out = _core.image(arr).pixels
        try:
            back = torch.from_dlpack(out)
        except (RuntimeError, TypeError):
            continue  # this torch build lacks the dtype (e.g. uint16) — skip it
        assert np.array_equal(back.numpy(), np.asarray(out))


def test_factory_accepts_torch_input(samples):
    torch = pytest.importorskip("torch")
    for arr in samples.values():
        try:
            tensor = torch.from_numpy(arr).contiguous()
        except (RuntimeError, TypeError):
            continue  # torch lacks this dtype (e.g. uint16 on older builds)
        im = _core.image(tensor)  # nb::ndarray accepts numpy OR torch
        np.testing.assert_array_equal(im.pixels, arr)
