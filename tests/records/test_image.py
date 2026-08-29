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
    """One color (H,W,3) array per supported dtype.

    The f32 sample splices hand-stamped special bit patterns into its first six
    elements (payload qNaN, negative qNaN with payload, sNaN with payload, -0.0,
    smallest positive denormal, +inf) so the round-trip pins bit-exact float
    preservation via ``.tobytes()`` -- ``assert_array_equal`` alone is blind to
    NaN payload bits and the sign of zero. Draw order is preserved so the u8/u16
    values are unchanged.
    """
    rng = np.random.default_rng(0)
    u8 = rng.integers(0, 256, size=(5, 7, 3)).astype(np.uint8)
    u16 = rng.integers(0, 65536, size=(4, 6, 3)).astype(np.uint16)
    f32 = rng.standard_normal(3 * 5 * 3).astype(np.float32)
    f32[:6] = np.array(
        [0x7FC00ABC, 0xFFC00001, 0x7F800001, 0x80000000, 0x00000001, 0x7F800000],
        np.uint32,
    ).view(np.float32)
    return {"u8": u8, "u16": u16, "f32": f32.reshape(3, 5, 3)}


# --- factory round-trip identity (numpy is the oracle) ---------------------
def test_factory_roundtrip_per_dtype(samples):
    for arr in samples.values():
        im = _core.image(arr)
        np.testing.assert_array_equal(im.pixels, arr)  # values (NaN-position aware)
        assert im.pixels.tobytes() == arr.tobytes()  # bit-exact incl. NaN payloads / -0.0
        assert im.pixels.dtype == arr.dtype
        assert im.pixels.shape == arr.shape
        assert (im.height, im.width, im.channels) == arr.shape


def test_noncontiguous_input_is_copied():
    # nanobind's c_contig conversion copies strided / negative-stride views
    # (image.cpp: "non-contiguous input is copied by nb"); the logical values
    # must survive the copy, not be read with the wrong strides.
    base = np.arange(48, dtype=np.uint8).reshape(4, 12)
    for nc in (base[:, ::2], base[::-1]):  # strided columns; reversed rows
        np.testing.assert_array_equal(_core.image(nc).pixels, nc)


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
    # match= pins each error to the check that must raise it (a mis-routed
    # generic message would otherwise satisfy a bare pytest.raises).
    u8_rgb = np.zeros((3, 4, 3), np.uint8)
    u8_rgba = np.zeros((3, 4, 4), np.uint8)
    with pytest.raises(ValueError, match="color_space"):  # unknown color_space vocabulary
        _core.image(u8_rgb, color_space="bt709")
    with pytest.raises(ValueError, match="alpha_mode"):  # straight alpha needs C==4
        _core.image(u8_rgb, alpha_mode="straight")
    with pytest.raises(ValueError, match="alpha_mode"):  # C==4 may not be 'none'
        _core.image(u8_rgba, alpha_mode="none")
    with pytest.raises(ValueError, match=r"C in|channels"):  # C==2 (gray+alpha not representable)
        _core.image(np.zeros((3, 4, 2), np.uint8))
    with pytest.raises(ValueError, match=r"C in|channels"):  # C==5
        _core.image(np.zeros((3, 4, 5), np.uint8))
    with pytest.raises(ValueError, match="H,W"):  # zero-size, H==0 (2-D)
        _core.image(np.zeros((0, 4), np.uint8))
    with pytest.raises(ValueError, match="H,W"):  # zero-size, W==0 (2-D)
        _core.image(np.zeros((4, 0), np.uint8))
    with pytest.raises(ValueError, match="H,W"):  # zero-size, H==0 (3-D)
        _core.image(np.zeros((0, 4, 3), np.uint8))
    with pytest.raises(ValueError, match="H,W"):  # 1-D
        _core.image(np.zeros((4,), np.uint8))
    with pytest.raises(ValueError, match="H,W"):  # 4-D
        _core.image(np.zeros((2, 3, 4, 3), np.uint8))


@pytest.mark.parametrize(
    "dt",
    [
        np.bool_,
        np.int8,  # same width as uint8 -- must not be mistaken for it
        np.int16,
        np.int64,
        np.uint32,
        np.uint64,
        np.float16,  # the planned F16 slot: must still raise TODAY
        np.float64,
        np.int32,
        np.complex64,
    ],
)
def test_unsupported_dtype_rejected(dt):
    with pytest.raises(ValueError, match="dtype"):
        _core.image(np.zeros((3, 4, 3), dt))


def test_big_endian_input_rejected_or_byte_preserved(samples):
    # '>u2' rasters come straight from np.frombuffer on 16-bit PGM data. Today
    # numpy refuses the non-native-endian DLPack/buffer export and nanobind
    # raises TypeError; if a future version accepted it, the values must be
    # preserved (native), never silently byteswap-misread.
    be = samples["u16"].astype(">u2")
    try:
        im = _core.image(be)
    except (TypeError, ValueError):
        pass  # rejection is the pinned-safe outcome
    else:
        np.testing.assert_array_equal(im.pixels, samples["u16"])


# --- maxval sample-range field (reconciled from the netpbm design) ---------
def test_maxval_defaults():
    assert _core.image(np.zeros((2, 2), np.uint8)).maxval == 255
    assert _core.image(np.zeros((2, 2), np.uint16)).maxval == 65535
    assert _core.image(np.zeros((2, 2), np.float32)).maxval == 0


def test_maxval_override_and_validation():
    # explicit maxval within the dtype's storable range is recorded verbatim
    assert _core.image(np.zeros((2, 2), np.uint16), maxval=1023).maxval == 1023
    assert _core.image(np.zeros((2, 2), np.uint8), maxval=200).maxval == 200
    # u16 with a small maxval (< 256) is stored verbatim as metadata; the netpbm
    # writer re-guards the dtype<->maxval pairing, not the record factory.
    assert _core.image(np.zeros((2, 2), np.uint16), maxval=200).maxval == 200
    with pytest.raises(ValueError, match="maxval"):  # > 255 cannot be stored in uint8
        _core.image(np.zeros((2, 2), np.uint8), maxval=1000)
    with pytest.raises(ValueError, match="maxval"):  # > 65535 cannot be stored in uint16
        _core.image(np.zeros((2, 2), np.uint16), maxval=70000)
    with pytest.raises(ValueError, match="maxval"):  # maxval 0 is degenerate for uint8
        _core.image(np.zeros((2, 2), np.uint8), maxval=0)
    with pytest.raises(ValueError, match="maxval"):  # maxval 0 is degenerate for uint16
        _core.image(np.zeros((2, 2), np.uint16), maxval=0)
    with pytest.raises(ValueError, match="maxval"):  # maxval is N/A for float32 (sentinel 0)
        _core.image(np.zeros((2, 2), np.float32), maxval=255)


# --- zero-copy + lifetime (the sio::view owner keepalive gate) -------------
def test_zero_copy_two_views_share_buffer(samples):
    im = _core.image(samples["u8"])
    a = im.pixels
    b = im.pixels
    assert a.ctypes.data == b.ctypes.data  # no copy; both view the record's buffer
    np.testing.assert_array_equal(a, b)
    # A mutation through one view is visible through the other and through a
    # fresh view -> they alias the record's storage, not a per-call cached copy.
    before = int(np.asarray(im.pixels)[0, 0, 0])
    sentinel = (before + 1) & 0xFF  # guaranteed != before
    a[0, 0, 0] = sentinel
    assert b[0, 0, 0] == sentinel
    assert int(np.asarray(im.pixels)[0, 0, 0]) == sentinel


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

    # The small samples above (<= ~180 B) can survive a broken keepalive by
    # luck: freed small blocks keep their contents on the UCRT heap until reuse.
    # A multi-MiB buffer is returned to the OS on free (VirtualFree), so a
    # missing owner faults deterministically instead of reading stale heap.
    big = np.arange(3 << 20, dtype=np.uint8).reshape(1024, 1024, 3)
    expected_big = big.copy()
    px = _core.image(big).pixels
    del big
    gc.collect()
    gc.collect()
    scribble = [np.full(1 << 20, 0xAB, np.uint8) for _ in range(4)]  # churn the heap
    np.testing.assert_array_equal(px, expected_big)
    assert scribble[0][0] == 0xAB  # keep the churn alive until after the compare


# --- cross-framework interop (torch, optional) -----------------------------
def test_torch_from_dlpack(samples):
    torch = pytest.importorskip("torch")
    for arr in samples.values():
        out = _core.image(arr).pixels
        try:
            back = torch.from_dlpack(out)
        except (RuntimeError, TypeError):
            # only uint16 may be missing from an older torch build; a broken
            # u8/f32 DLPack export must hard-fail the test, not be skipped.
            assert arr.dtype == np.uint16, f"from_dlpack must work for {arr.dtype}"
            continue
        # bit-exact (NaN-payload / -0.0 aware), unlike np.array_equal
        assert back.numpy().tobytes() == np.asarray(out).tobytes()


def test_factory_accepts_torch_input(samples):
    torch = pytest.importorskip("torch")
    for arr in samples.values():
        try:
            tensor = torch.from_numpy(arr).contiguous()
        except (RuntimeError, TypeError):
            continue  # torch lacks this dtype (e.g. uint16 on older builds)
        im = _core.image(tensor)  # nb::ndarray accepts numpy OR torch
        np.testing.assert_array_equal(im.pixels, arr)
