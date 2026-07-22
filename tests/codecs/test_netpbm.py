"""Parity suite for the netpbm codec (PGM P5/P2, PPM P6/P3 -> Image record).

Follows the reference pattern of tests/codecs/test_pfm.py: a tiny self-contained
pure-Python numpy oracle (primary), the three io_implementation_plan.md §6 parity
kinds (cross-impl both directions + round-trip identity), hand-derived convention
pins (16-bit big-endian samples, comment skipping, the exactly-one-delimiter rule,
maxval-is-metadata, top-to-bottom rows), a golden writer blob, writer guards, an
optional imageio cross-check, malformed-input fuzz, and numpy/torch interop.

The Image record here is the reconciled one (records/image.hpp): PixelType
{U8,U16,F32}, channels in {1,3,4}, color_space in {srgb,linear,gray,unknown},
plus a netpbm `maxval` metadata field. netpbm covers only integer gray (C=1,
"gray") and rgb (C=3, "srgb"); float32 and RGBA are refused by the *writer*, and
the factory (accepting C in {1,3,4}) admits shapes netpbm then rejects — hence
the split between factory-level and writer-level guard tests below.
"""

from __future__ import annotations

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


# --- oracle: a minimal, independent pure-Python netpbm codec ----------------
def oracle_write_netpbm(
    arr: np.ndarray, maxval: int | None = None, as_ascii: bool = False
) -> bytes:
    a = np.asarray(arr)
    color = a.ndim == 3
    if maxval is None:
        maxval = 255 if a.dtype == np.uint8 else 65535
    magic = (b"P3" if as_ascii else b"P6") if color else (b"P2" if as_ascii else b"P5")
    head = magic + f"\n{a.shape[1]} {a.shape[0]}\n{maxval}\n".encode()
    if as_ascii:
        rows = a.reshape(a.shape[0], -1)
        body = b"\n".join(b" ".join(b"%d" % int(v) for v in row) for row in rows) + b"\n"
    else:
        body = a.astype(">u2" if maxval > 255 else np.uint8).tobytes()  # ">u2" = big-endian on disk
    return head + body


def oracle_read_netpbm(data: bytes) -> tuple[np.ndarray, int]:
    kind = data[1:2]
    ascii_mode = kind in (b"2", b"3")
    color = kind in (b"3", b"6")
    C = 3 if color else 1
    pos = 2
    ws = b" \t\n\r\x0b\x0c"

    def skip_ws_comments() -> None:
        nonlocal pos
        while pos < len(data):
            while pos < len(data) and data[pos] in ws:
                pos += 1
            if pos < len(data) and data[pos] == 0x23:  # '#'
                while pos < len(data) and data[pos] not in b"\n\r":
                    pos += 1
            else:
                break

    def read_uint() -> int:
        nonlocal pos
        skip_ws_comments()
        start = pos
        while pos < len(data) and 48 <= data[pos] <= 57:
            pos += 1
        return int(data[start:pos])

    w, h, maxval = read_uint(), read_uint(), read_uint()
    wide = maxval > 255
    if ascii_mode:
        vals = [read_uint() for _ in range(w * h * C)]
        arr = np.array(vals, dtype=np.uint16 if wide else np.uint8)
    else:
        pos += 1  # exactly one delimiter byte after maxval (our writer emits one '\n')
        raster = data[pos : pos + w * h * C * (2 if wide else 1)]
        arr = np.frombuffer(raster, dtype=">u2" if wide else np.uint8).astype(
            np.uint16 if wide else np.uint8
        )
    return arr.reshape((h, w, 3) if color else (h, w)), maxval


@pytest.fixture
def samples() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(0)
    return {
        "gray_u8": rng.integers(0, 256, (5, 7), dtype=np.uint8),
        "rgb_u8": rng.integers(0, 256, (4, 6, 3), dtype=np.uint8),
        "gray_u16": rng.integers(0, 65536, (5, 7), dtype=np.uint16),
        "rgb_u16": rng.integers(0, 65536, (4, 6, 3), dtype=np.uint16),
        # an asymmetric gray ramp: catches a row-flip / transpose bug
        "ramp": np.arange(3 * 4, dtype=np.uint8).reshape(3, 4),
    }


# --- parity kind 3: round-trip identity (ours.read(ours.write)) -------------
@pytest.mark.parametrize("as_ascii", [False, True])
def test_roundtrip_identity(samples, as_ascii):
    for arr in samples.values():
        img = _core.image(arr)
        rec = _core.read_netpbm(_core.write_netpbm(img, as_ascii))
        np.testing.assert_array_equal(np.asarray(rec.pixels), arr)
        assert rec.dtype == img.dtype
        assert rec.color_space == img.color_space
        assert rec.maxval == img.maxval


def test_pixels_dtype_shape_and_type(samples):
    for arr in samples.values():
        rec = _core.read_netpbm(_core.write_netpbm(_core.image(arr)))
        px = np.asarray(rec.pixels)
        assert isinstance(px, np.ndarray)
        assert px.dtype == arr.dtype
        assert px.shape == arr.shape


# --- parity kind 1: cross-impl (oracle writes, our reader recovers) ---------
@pytest.mark.parametrize("as_ascii", [False, True])
def test_parity_oracle_write_ours_read(samples, as_ascii):
    for arr in samples.values():
        rec = _core.read_netpbm(oracle_write_netpbm(arr, as_ascii=as_ascii))
        np.testing.assert_array_equal(np.asarray(rec.pixels), arr)


# --- parity kind 2: writer spec-correctness (ours writes, oracle recovers) --
@pytest.mark.parametrize("as_ascii", [False, True])
def test_parity_ours_write_oracle_read(samples, as_ascii):
    for arr in samples.values():
        got, maxval = oracle_read_netpbm(_core.write_netpbm(_core.image(arr), as_ascii))
        np.testing.assert_array_equal(got, arr)
        assert maxval == (255 if arr.dtype == np.uint8 else 65535)


def test_imageio_cross_check(samples):
    # Secondary named oracle; canonical maxval-255 u8 only (Pillow/imageio 16-bit
    # and odd-maxval behavior is version-dependent — the pure-Python oracle above
    # is authoritative for those).
    iio = pytest.importorskip("imageio.v3")
    for key, ext in (("rgb_u8", ".ppm"), ("gray_u8", ".pgm")):
        arr = samples[key]
        ref = np.squeeze(
            np.asarray(iio.imread(_core.write_netpbm(_core.image(arr)), extension=ext))
        )
        np.testing.assert_array_equal(ref.astype(arr.dtype), arr)


# --- convention pins (hand-derived external ground truth) -------------------
def test_pin_16bit_big_endian():
    # 0x0102 == 258 (big-endian), NOT 0x0201 == 513.
    rec = _core.read_netpbm(b"P5\n1 1\n65535\n\x01\x02")
    assert int(np.asarray(rec.pixels)[0, 0]) == 258
    assert rec.dtype == "uint16"
    # and the writer emits big-endian (hi byte first)
    out = _core.write_netpbm(_core.image(np.array([[258]], dtype=np.uint16)))
    assert out.endswith(b"\x01\x02")


def test_pin_comment_skipping():
    data = b"P6 #c\n#c2\n2 1\n#c3\n255\n" + bytes([10, 20, 30, 40, 50, 60])
    rec = _core.read_netpbm(data)
    assert (rec.width, rec.height, rec.channels) == (2, 1, 3)
    np.testing.assert_array_equal(
        np.asarray(rec.pixels), np.array([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8)
    )
    # a comment glued to maxval: its terminating newline is the single delimiter
    rec2 = _core.read_netpbm(b"P5\n1 1\n255#trailing comment\n\x2a")
    assert int(np.asarray(rec2.pixels)[0, 0]) == 42


def test_pin_exactly_one_delimiter():
    # after the '\n' delimiter, the next bytes '\n'(10) and ' '(32) are raster DATA
    rec = _core.read_netpbm(b"P5\n2 1\n255\n\n\x20")
    np.testing.assert_array_equal(np.asarray(rec.pixels), np.array([[10, 32]], dtype=np.uint8))


def test_pin_maxval_is_metadata():
    # a sample below a non-canonical maxval is stored RAW, never rescaled
    rec = _core.read_netpbm(b"P2\n1 1\n100\n50\n")
    assert int(np.asarray(rec.pixels)[0, 0]) == 50
    assert rec.maxval == 100
    assert rec.dtype == "uint8"


def test_pin_rows_top_to_bottom():
    arr = np.arange(12, dtype=np.uint8).reshape(3, 4)  # arr[0,0] == 0 at top-left
    got = np.asarray(_core.read_netpbm(_core.write_netpbm(_core.image(arr))).pixels)
    assert got[0, 0] == 0
    assert got[-1, -1] == 11
    np.testing.assert_array_equal(got, arr)


def test_golden_writer_blob():
    img = _core.image(np.arange(12, dtype=np.uint8).reshape(2, 2, 3))
    assert _core.write_netpbm(img) == b"P6\n2 2\n255\n" + bytes(range(12))


# --- malformed input raises (FormatError-mappable ValueError), never crashes -
@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"P1\n1 1\n0", "not supported"),  # PBM ascii
        (b"P4\n1 1\n\x00", "not supported"),  # PBM binary
        (b"P7\nfoo", "not supported"),  # PAM
        (b"PX\n1 1\n255\n\x00", "bad magic"),
        (b"XY", "bad magic"),
        (b"", "bad magic"),
        (b"P5", "expected a number"),  # header truncated after magic
        (b"P5\nX 2\n255\n", "expected a number"),  # non-digit width token
        (b"P5\n1 1\n0\n\x00", "maxval"),  # maxval 0
        (b"P5\n1 1\n65536\n\x00\x00", "out of range"),  # maxval > 65535
        (b"P5\n2 2\n255\n\x01", "truncated"),  # binary raster truncated
        (b"P2\n1 1\n255\n300\n", "out of range"),  # ascii sample overflows dtype
        (b"P5\n999999999 999999999\n255\n", "truncated"),  # huge header, must not allocate
    ],
)
def test_malformed_raises(data, match):
    with pytest.raises(ValueError, match=match):
        _core.read_netpbm(data)


# --- writer guards (refuse foreign conventions rather than convert) ---------
def test_writer_guard_float32():
    img = _core.image(np.zeros((2, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="float32"):
        _core.write_netpbm(img)


def test_writer_guard_rgba():
    img = _core.image(np.zeros((2, 2, 4), dtype=np.uint8))  # factory accepts C=4; writer refuses it
    with pytest.raises(ValueError, match=r"RGBA|4-channel"):
        _core.write_netpbm(img)


def test_writer_guard_linear_colorspace():
    img = _core.image(np.zeros((2, 2, 3), dtype=np.uint8), color_space="linear")
    with pytest.raises(ValueError, match="srgb"):
        _core.write_netpbm(img)


def test_writer_guard_dtype_maxval_mismatch():
    # u16 buffer declaring an 8-bit maxval is a foreign pairing, not auto-narrowed
    img = _core.image(np.zeros((2, 2), dtype=np.uint16), maxval=200)
    with pytest.raises(ValueError, match="maxval"):
        _core.write_netpbm(img)


def test_writer_guard_sample_exceeds_maxval():
    img = _core.image(np.array([[251]], dtype=np.uint8), maxval=250)
    with pytest.raises(ValueError, match="exceeds declared maxval"):
        _core.write_netpbm(img)


def test_factory_rejects_bad_shapes_and_maxval():
    with pytest.raises(ValueError, match="C in"):
        _core.image(np.zeros((2, 2, 2), dtype=np.uint8))
    with pytest.raises(ValueError, match="C in"):
        _core.image(np.zeros((2, 2, 5), dtype=np.uint8))
    with pytest.raises(ValueError, match="maxval"):
        _core.image(np.zeros((2, 2), dtype=np.uint8), maxval=1000)
    with pytest.raises(ValueError, match="maxval"):
        _core.image(np.zeros((2, 2), dtype=np.uint16), maxval=0)


# --- numpy/torch interop (test_pfm.py:100 pattern) --------------------------
def test_torch_interop(samples):
    torch = pytest.importorskip("torch")
    arr = samples["rgb_u8"]
    # write path accepts a torch tensor (numpy OR torch on input)
    img = _core.image(torch.from_numpy(arr).contiguous())
    rec = _core.read_netpbm(_core.write_netpbm(img))
    np.testing.assert_array_equal(np.asarray(rec.pixels), arr)
    # read output -> torch via DLPack, values agree with numpy (zero-copy CPU)
    out = np.asarray(rec.pixels)
    back = torch.from_dlpack(rec.pixels)
    assert np.array_equal(back.numpy(), out)
