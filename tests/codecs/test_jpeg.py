"""Parity suite for the JPEG codec (jpeg.cpp -> Image, via vendored stb).

JPEG is LOSSY, so the checks are: our decoder agrees with libjpeg (Pillow) on the
same bytes to within a few LSB; our encoder produces JPEGs libjpeg decodes close
to the source (PSNR bound); round-trips are bounded and re-encode-idempotent; and
higher quality means larger files + higher PSNR. The reader supports grayscale
(C=1) and color (C=3); the writer is RGB-only (stb can't emit true grayscale JPEG).
"""

from __future__ import annotations

import hashlib
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


def gradient_rgb(h=48, w=64):  # smooth -> JPEG-friendly, deterministic
    y, x = np.mgrid[0:h, 0:w]
    return np.stack([x * 255 // w, y * 255 // h, (x + y) * 255 // (w + h)], -1).astype(np.uint8)


def pil_jpeg(arr, q=90):
    buf = io.BytesIO()
    PIL.fromarray(arr).save(buf, "JPEG", quality=q)
    return buf.getvalue()


def pil_decode(data):
    return np.asarray(PIL.open(io.BytesIO(data)))


def _px(img):
    return np.asarray(img.pixels)


def test_read_matches_pillow_decode():
    # our decoder vs libjpeg on the SAME bytes: differ by only a few LSB (IDCT/upsample)
    data = pil_jpeg(gradient_rgb(), 92)
    ours, ref = _px(_core.read_jpeg(data)), pil_decode(data)
    assert ours.shape == ref.shape and ours.dtype == np.uint8
    assert int(np.abs(ours.astype(int) - ref.astype(int)).max()) <= 4


def test_write_decodes_close_via_pillow():
    arr = gradient_rgb()
    dec = pil_decode(bytes(_core.write_jpeg(_core.image(arr, color_space="srgb"), 95)))
    assert psnr(dec, arr) >= 34.0  # our encoder produces a spec-correct, high-fidelity JPEG


def test_roundtrip_bounded_and_idempotent():
    arr = gradient_rgb()
    once = _core.read_jpeg(_core.write_jpeg(_core.image(arr, color_space="srgb"), 90))
    a1 = _px(once)
    assert psnr(a1, arr) >= 32.0
    # a second generation at the same quality barely moves (JPEG converges)
    a2 = _px(_core.read_jpeg(_core.write_jpeg(once, 90)))
    assert int(np.abs(a2.astype(int) - a1.astype(int)).max()) <= 4


def test_quality_tradeoff():
    img = _core.image(gradient_rgb(), color_space="srgb")
    lo, hi = bytes(_core.write_jpeg(img, 20)), bytes(_core.write_jpeg(img, 95))
    assert len(hi) > len(lo)
    assert psnr(pil_decode(hi), gradient_rgb()) > psnr(pil_decode(lo), gradient_rgb())


def test_retained_stb_encoder_bytes_match_the_locked_vectors():
    marker = getattr(_core, "_jpeg_backend_id", None)
    if marker is not None and marker() != "stb":
        pytest.skip("retained-backend byte contract")

    cases = [
        ((1, 1, 1, 0), 614, "963bc82ec790b2024b6baa2bd3e2cc1502523ea39dd1000776cdc9bf16b23f00"),
        ((2, 3, 50, 1), 637, "b9a2097cc0dcac2b1732429978cfffc6e01764d44de5cbc42f6ed49e5993de24"),
        ((5, 7, 90, 2), 739, "0197d0dfd1087e534a9fede5f8b51c5e32d9799e30e722bb30701f89f3d64f37"),
        ((5, 7, 91, 2), 710, "97436523e5cf3ceeaec13a233bc3a7bb132d21917269e0ab3e51c17e386571b8"),
        ((9, 17, 95, 3), 1043, "7ddea83c48332d052680286734e93f1c53429c77b8fb72c6b2307a64bc6a8545"),
        (
            (13, 11, 100, 4),
            1525,
            "9646ca4f35562ec998b90eae0c0bda326dfabcebdd88e0f6e5316d786ebe9e3a",
        ),
    ]
    for (height, width, quality, seed), expected_size, expected_sha256 in cases:
        y, x = np.mgrid[0:height, 0:width]
        pixels = np.stack(
            (
                (x * 31 + y * 17 + seed * 13) % 256,
                (x * 7 + y * 47 + seed * 29) % 256,
                (x * 59 + y * 3 + seed * 11) % 256,
            ),
            axis=-1,
        ).astype(np.uint8)
        encoded = bytes(
            _core.write_jpeg(
                _core.image(pixels, color_space="srgb"),
                quality,
            )
        )
        assert len(encoded) == expected_size
        assert hashlib.sha256(encoded).hexdigest() == expected_sha256


def test_read_grayscale_jpeg():
    gray = (np.add.outer(np.arange(16), np.arange(16)) * 7 % 256).astype(np.uint8)
    buf = io.BytesIO()
    PIL.fromarray(gray, "L").save(buf, "JPEG", quality=95)
    g = _core.read_jpeg(buf.getvalue())
    assert g.channels == 1 and g.dtype == "uint8" and g.color_space == "gray"
    # pixels, not just metadata: grayscale has no chroma subsampling -> tight bound
    ref = np.asarray(PIL.open(io.BytesIO(buf.getvalue())))
    assert int(np.abs(_px(g).astype(int) - ref.astype(int)).max()) <= 2


def test_read_progressive_jpeg():
    arr = gradient_rgb()
    buf = io.BytesIO()
    PIL.fromarray(arr).save(buf, "JPEG", quality=90, progressive=True)
    ours, ref = _px(_core.read_jpeg(buf.getvalue())), pil_decode(buf.getvalue())
    assert ours.shape == ref.shape
    assert int(np.abs(ours.astype(int) - ref.astype(int)).max()) <= 4


def test_read_rejects_hdr_bytes():
    # stb compiles JPEG + HDR into one lib; a .hdr must not decode here as tone-mapped u8
    hdr = b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n\x80\x40\x20\x81"
    with pytest.raises(ValueError, match=r"SOI|JPEG"):
        _core.read_jpeg(hdr)


def test_corrupt_dht_is_rejected_instead_of_returning_uninitialized_pixels():
    # Regression for the pinned stb revision's decode_jpeg_image bug: a failed
    # process_marker call returned success, so an overlong Huffman table reached
    # color conversion with partially uninitialized component buffers.
    data = bytearray(_core.write_jpeg(_core.image(gradient_rgb(), color_space="srgb"), 95))
    dht = data.index(b"\xff\xc4")
    first_code_length_count = dht + 5  # marker(2), length(2), table id(1)
    data[first_code_length_count] = 255  # total symbol count > 256 => invalid DHT
    immutable = bytes(data)
    for view in (immutable, memoryview(immutable)):
        with pytest.raises(ValueError, match=r"DHT|Corrupt JPEG|jpeg"):
            _core.read_jpeg(view)


def test_missing_eoi_is_rejected_before_decode():
    data = bytes(_core.write_jpeg(_core.image(gradient_rgb(), color_space="srgb"), 95))
    assert data.endswith(b"\xff\xd9")
    with pytest.raises(ValueError, match=r"missing FF D9 EOI"):
        _core.read_jpeg(data[:-2])


def test_write_rejects_oversized():
    # JPEG SOF dims are 16-bit; a >65535 axis would silently truncate to a corrupt file
    with pytest.raises(ValueError, match=r"16-bit|65535"):
        _core.write_jpeg(_core.image(np.zeros((1, 70000, 3), np.uint8), color_space="srgb"))


def test_read_dimension_bomb():
    # patch a real JPEG's SOF0 to claim 60000x60000 (3.6e9 px) -> refused by the cap
    data = bytearray(pil_jpeg(gradient_rgb(8, 8), 90))
    k = data.index(b"\xff\xc0")  # SOF0: FF C0 len(2) precision(1) height(2) width(2)
    data[k + 5 : k + 7] = (60000).to_bytes(2, "big")
    data[k + 7 : k + 9] = (60000).to_bytes(2, "big")
    with pytest.raises(ValueError, match=r"exceed|limit|dimensions"):
        _core.read_jpeg(bytes(data))


def test_write_rejects_grayscale():
    # stb can't emit true grayscale JPEG -> refuse rather than silently expand to RGB
    with pytest.raises(ValueError, match="grayscale"):
        _core.write_jpeg(_core.image(np.zeros((4, 4), np.uint8), color_space="gray"))


def test_write_guards():
    rgb = gradient_rgb(8, 8)
    with pytest.raises(ValueError, match="8-bit"):
        _core.write_jpeg(_core.image((rgb.astype(np.uint16) * 257), color_space="srgb"))
    with pytest.raises(ValueError, match="8-bit"):
        _core.write_jpeg(_core.image(rgb.astype(np.float32), color_space="srgb"))
    with pytest.raises(ValueError, match="srgb"):
        _core.write_jpeg(_core.image(rgb, color_space="linear"))
    with pytest.raises(ValueError, match=r"alpha|RGB"):
        _core.write_jpeg(_core.image(np.zeros((4, 4, 4), np.uint8), alpha_mode="straight"))
    for q in (0, 101):
        with pytest.raises(ValueError, match="quality"):
            _core.write_jpeg(_core.image(rgb, color_space="srgb"), q)


def test_malformed_raises():
    with pytest.raises(ValueError):
        _core.read_jpeg(b"not a jpeg at all")
    with pytest.raises(ValueError):
        _core.read_jpeg(bytes(pil_jpeg(gradient_rgb(8, 8)))[:20])  # truncated


def test_torch_interop():
    torch = pytest.importorskip("torch")
    img = _core.read_jpeg(pil_jpeg(gradient_rgb(8, 8), 90))
    assert np.array_equal(torch.from_dlpack(img.pixels).numpy(), _px(img))
