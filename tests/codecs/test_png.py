"""Parity suite for the PNG codec (png.cpp -> Image, via vendored lodepng).

Oracles (test-only): Pillow for 8-bit gray/RGB/RGBA/palette, and pypng for exact
16-bit RGB/RGBA (Pillow's rgb48 handling is lossy/awkward). PNG is lossless, so
the checks are strict value equality in both directions. Endianness is pinned
implicitly: our writer emits big-endian 16-bit, and pypng (which expects BE)
decoding our bytes to the right values proves the native<->BE swap both ways.
"""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")
PIL = pytest.importorskip("PIL.Image")
png = pytest.importorskip("png")  # pypng


# --- oracle helpers ---------------------------------------------------------
def pil_encode(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    PIL.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def pil_decode(data: bytes) -> np.ndarray:
    return np.asarray(PIL.open(io.BytesIO(data)))


def pypng_encode(arr: np.ndarray) -> bytes:
    h, w = arr.shape[:2]
    c = 1 if arr.ndim == 2 else arr.shape[2]
    buf = io.BytesIO()
    png.Writer(
        w, h, greyscale=(c == 1), alpha=(c == 4),
        bitdepth=16 if arr.dtype == np.uint16 else 8,
    ).write(buf, arr.reshape(h, w * c).tolist())
    return buf.getvalue()


def pypng_decode(data: bytes) -> np.ndarray:
    w, h, rows, info = png.Reader(bytes=data).read()
    dt = np.uint16 if info["bitdepth"] == 16 else np.uint8
    a = np.vstack([np.asarray(r, dtype=dt) for r in rows]).reshape(h, w, info["planes"])
    return a[:, :, 0] if info["planes"] == 1 else a


def _px(img):
    return np.asarray(img.pixels)


def _sample(seed, shape, dtype):
    rng = np.random.default_rng(seed)
    hi = 65536 if dtype == np.uint16 else 256
    return rng.integers(0, hi, size=shape, dtype=np.uint32).astype(dtype)


# supported matrix: (channels, color_space, alpha_mode)
CELLS_U8 = [((5, 7), "gray", "none"), ((5, 7, 3), "srgb", "none"), ((5, 7, 4), "srgb", "straight")]
CELLS_U16 = CELLS_U8


# --- round-trip identity across the whole supported matrix (self-consistency) -
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_roundtrip_all_modes(dtype):
    cells = CELLS_U16 if dtype == np.uint16 else CELLS_U8
    for i, (shape, cs, am) in enumerate(cells):
        arr = _sample(i, shape, dtype)
        img = _core.image(arr, color_space=cs, alpha_mode=am)
        back = _core.read_png(_core.write_png(img))
        np.testing.assert_array_equal(_px(back), arr)
        assert back.dtype == ("uint16" if dtype == np.uint16 else "uint8")
        assert back.color_space == cs and back.alpha_mode == am


# --- 8-bit parity vs Pillow, both directions --------------------------------
@pytest.mark.parametrize("shape", [(6, 9), (6, 9, 3), (6, 9, 4)])
def test_u8_reads_pillow(shape):
    arr = _sample(10, shape, np.uint8)
    img = _core.read_png(pil_encode(arr))
    np.testing.assert_array_equal(_px(img), arr)
    assert img.dtype == "uint8" and img.channels == (1 if len(shape) == 2 else shape[-1])
    assert img.color_space == ("gray" if len(shape) == 2 else "srgb")
    assert img.alpha_mode == ("straight" if shape[-1] == 4 else "none")


@pytest.mark.parametrize("shape", [(6, 9), (6, 9, 3), (6, 9, 4)])
def test_pillow_reads_u8_writer(shape):
    arr = _sample(11, shape, np.uint8)
    cs = "gray" if len(shape) == 2 else "srgb"
    am = "straight" if shape[-1] == 4 else "none"
    got = pil_decode(_core.write_png(_core.image(arr, color_space=cs, alpha_mode=am)))
    np.testing.assert_array_equal(got, arr)


# --- 16-bit parity vs pypng (exact; also pins BE-on-disk both ways) ----------
@pytest.mark.parametrize("shape", [(4, 5), (4, 5, 3), (4, 5, 4), (1, 4096, 3)])  # wide case exercises be16 indexing
def test_u16_reads_pypng(shape):
    arr = _sample(20, shape, np.uint16)
    img = _core.read_png(pypng_encode(arr))
    np.testing.assert_array_equal(_px(img), arr)
    assert img.dtype == "uint16" and img.channels == (1 if len(shape) == 2 else shape[-1])


@pytest.mark.parametrize("shape", [(4, 5), (4, 5, 3), (4, 5, 4), (1, 4096, 3)])
def test_pypng_reads_u16_writer(shape):
    arr = _sample(21, shape, np.uint16)
    cs = "gray" if len(shape) == 2 else "srgb"
    am = "straight" if shape[-1] == 4 else "none"
    got = pypng_decode(_core.write_png(_core.image(arr, color_space=cs, alpha_mode=am)))
    np.testing.assert_array_equal(got, arr)


def test_16bit_depth_values_survive():
    # depth-map workhorse: decode OUR writer's bytes with the independent pypng
    # oracle, so full-range 16-bit values + big-endian-on-disk are pinned externally.
    arr = np.array([[0, 1, 255, 256], [4096, 32768, 60000, 65535]], np.uint16)
    data = bytes(_core.write_png(_core.image(arr, color_space="gray")))
    np.testing.assert_array_equal(pypng_decode(data), arr)


@pytest.mark.parametrize(("shape", "dtype"), [((6, 9, 3), np.uint8), ((4, 5), np.uint16)])
def test_reads_interlaced(shape, dtype):
    # Adam7-interlaced decode path (no oracle here writes interlaced by default)
    arr = _sample(90, shape, dtype)
    h, w = arr.shape[:2]
    c = 1 if arr.ndim == 2 else arr.shape[2]
    buf = io.BytesIO()
    png.Writer(
        w, h, greyscale=(c == 1), alpha=(c == 4),
        bitdepth=16 if dtype == np.uint16 else 8, interlace=True,
    ).write(buf, arr.reshape(h, w * c).tolist())
    np.testing.assert_array_equal(_px(_core.read_png(buf.getvalue())), arr)


# --- palette expansion (decode semantics, not a lossy conversion) ------------
def test_palette_expands_to_rgb():
    pal = [(10, 20, 30), (200, 100, 50), (0, 0, 0), (255, 255, 255)]
    idx = np.array([[0, 1], [2, 3]], np.uint8)
    p = PIL.new("P", (2, 2))
    p.putpalette([c for rgb in pal for c in rgb])
    p.putdata(idx.flatten().tolist())
    buf = io.BytesIO()
    p.save(buf, format="PNG")
    img = _core.read_png(buf.getvalue())
    assert img.channels == 3 and img.color_space == "srgb"
    expected = np.array([[pal[0], pal[1]], [pal[2], pal[3]]], np.uint8)
    np.testing.assert_array_equal(_px(img), expected)


def test_transparent_palette_expands_to_rgba():
    p = PIL.new("P", (3, 1))
    p.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255])  # r, g, b
    p.putdata([0, 1, 2])
    buf = io.BytesIO()
    p.save(buf, format="PNG", transparency=bytes([0, 128]))  # entry0 transparent, entry1 half; entry2 default opaque
    img = _core.read_png(buf.getvalue())
    assert img.channels == 4 and img.alpha_mode == "straight"
    px = _px(img)
    assert tuple(px[0, 0]) == (255, 0, 0, 0)  # explicit alpha 0
    assert tuple(px[0, 1]) == (0, 255, 0, 128)  # partial alpha pins the propagated value
    assert tuple(px[0, 2]) == (0, 0, 255, 255)  # entry beyond tRNS -> default opaque


# --- writer guards: refuse what PNG can't represent, never convert -----------
def test_writer_guards():
    rgb = _sample(30, (3, 3, 3), np.uint8)
    rgba = _sample(31, (3, 3, 4), np.uint8)
    with pytest.raises(ValueError, match="float32"):
        _core.write_png(_core.image(np.zeros((2, 2), np.float32)))
    with pytest.raises(ValueError, match="srgb"):
        _core.write_png(_core.image(rgb, color_space="linear"))
    with pytest.raises(ValueError, match="gray"):  # C1 must be gray, not srgb
        _core.write_png(_core.image(_sample(34, (2, 2), np.uint8), color_space="srgb"))
    with pytest.raises(ValueError, match="srgb"):  # C4 linear refused before the alpha check
        _core.write_png(_core.image(rgba, color_space="linear"))
    with pytest.raises(ValueError, match="straight"):
        _core.write_png(_core.image(rgba, alpha_mode="premultiplied"))
    with pytest.raises(ValueError, match="maxval"):
        _core.write_png(_core.image(_sample(32, (2, 2), np.uint8), color_space="gray", maxval=100))
    with pytest.raises(ValueError, match="maxval"):
        _core.write_png(_core.image(_sample(33, (2, 2), np.uint16), color_space="gray", maxval=1000))


# --- reader rejects (clear error, no silent lossy conversion) ----------------
def test_reader_rejects_gray_alpha():
    buf = io.BytesIO()
    PIL.fromarray(_sample(40, (3, 3, 2), np.uint8), mode="LA").save(buf, format="PNG")
    with pytest.raises(ValueError, match=r"grayscale.*alpha|2-channel"):
        _core.read_png(buf.getvalue())


def test_reader_rejects_sub8_gray():
    buf = io.BytesIO()
    png.Writer(4, 2, greyscale=True, bitdepth=1).write(buf, [[0, 1, 0, 1], [1, 0, 1, 0]])
    with pytest.raises(ValueError, match="sub-8-bit"):
        _core.read_png(buf.getvalue())


def test_reader_rejects_colorkey_trns():
    buf = io.BytesIO()  # RGB8 with a single-color tRNS key
    png.Writer(2, 1, greyscale=False, bitdepth=8, transparent=(0, 0, 0)).write(
        buf, [[0, 0, 0, 255, 255, 255]]
    )
    with pytest.raises(ValueError, match="colorkey"):
        _core.read_png(buf.getvalue())
    # gray16 + colorkey: the flagship depth-map case where a botched guard would
    # silently drop transparency; the reject must cover it too.
    buf16 = io.BytesIO()
    png.Writer(2, 1, greyscale=True, bitdepth=16, transparent=(30000,)).write(buf16, [[30000, 60000]])
    with pytest.raises(ValueError, match="colorkey"):
        _core.read_png(buf16.getvalue())


# --- malformed input raises cleanly, never crashes ---------------------------
def test_malformed_raises():
    valid = _core.write_png(_core.image(_sample(50, (8, 8, 3), np.uint8), color_space="srgb"))
    with pytest.raises(ValueError):
        _core.read_png(b"not a png at all")
    with pytest.raises(ValueError):
        _core.read_png(bytes(valid)[:20])  # truncated (header only)
    with pytest.raises(ValueError):
        _core.read_png(bytes(valid)[:-8])  # truncated IDAT/IEND
    corrupt = bytearray(valid)
    corrupt[40] ^= 0xFF  # flip a byte mid-stream -> zlib/CRC error
    with pytest.raises(ValueError):
        _core.read_png(bytes(corrupt))


def _png_ihdr_only(w, h):
    # a valid-CRC IHDR (RGB8) with no IDAT, so lodepng_inspect succeeds and the
    # DIMENSION CAP (not a CRC error) is what must reject the image.
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    crc = zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", crc)


def test_bomb_dimensions_rejected():
    # exercises png.cpp's cap (checked after inspect, before the pixel alloc);
    # match= ensures the DIMENSION guard fires, not lodepng's CRC/decode error.
    with pytest.raises(ValueError, match=r"exceed|dimensions|limit"):
        _core.read_png(_png_ihdr_only(50000, 50000))  # pixel-count cap (2.5e9 > 2.5e8)
    with pytest.raises(ValueError, match=r"exceed|dimensions|limit"):
        _core.read_png(_png_ihdr_only(300000, 1))  # per-axis cap (300000 > 200000)


# --- determinism + interop ---------------------------------------------------
def test_writer_deterministic():
    img = _core.image(_sample(60, (5, 5, 3), np.uint8), color_space="srgb")
    assert bytes(_core.write_png(img)) == bytes(_core.write_png(img))


def test_empty_and_dtype_metadata():
    img = _core.read_png(_core.write_png(_core.image(_sample(70, (2, 2), np.uint16), color_space="gray")))
    assert img.maxval == 65535 and img.row_order == "top_to_bottom"


def test_torch_interop():
    torch = pytest.importorskip("torch")
    img = _core.read_png(_core.write_png(_core.image(_sample(80, (3, 4, 4), np.uint8), alpha_mode="straight")))
    assert np.array_equal(torch.from_dlpack(img.pixels).numpy(), _px(img))
