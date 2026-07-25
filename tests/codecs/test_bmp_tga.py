"""Pillow parity, conventions, malformed, mmap, sink, and memory tests."""

from __future__ import annotations

import gc
import io
import mmap
import struct
import tracemalloc

import numpy as np
import pytest
from PIL import Image as PilImage

import sceneio
from sceneio import _core


def pil_encode(array, format_id, **options) -> bytes:
    stream = io.BytesIO()
    PilImage.fromarray(array).save(stream, format=format_id, **options)
    return stream.getvalue()


def pil_decode(data, mode=None) -> np.ndarray:
    with PilImage.open(io.BytesIO(data)) as image:
        image.load()
        if mode is not None:
            image = image.convert(mode)
        return np.asarray(image).copy()


def make_pixels(channels: int, *, height=7, width=9) -> np.ndarray:
    shape = (height, width) if channels == 1 else (height, width, channels)
    return (
        np.arange(np.prod(shape), dtype=np.uint32).reshape(shape) * 37 + 11
    ).astype(np.uint8)


def image_record(array):
    channels = 1 if array.ndim == 2 else array.shape[2]
    return _core.image(
        array,
        color_space="gray" if channels == 1 else "srgb",
        alpha_mode="straight" if channels == 4 else "none",
    )


def manual_bmp24(array: np.ndarray, *, top_down: bool) -> bytes:
    height, width, channels = array.shape
    assert channels == 3
    row_size = (width * 3 + 3) & ~3
    pixels = bytearray()
    rows = array if top_down else array[::-1]
    for row in rows:
        pixels.extend(row[:, ::-1].tobytes())
        pixels.extend(b"\0" * (row_size - width * 3))
    offset = 14 + 40
    size = offset + len(pixels)
    file_header = struct.pack("<2sIHHI", b"BM", size, 0, 0, offset)
    dib = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        -height if top_down else height,
        1,
        24,
        0,
        len(pixels),
        0,
        0,
        0,
        0,
    )
    return file_header + dib + pixels


def manual_bmp565() -> bytes:
    width, height = 2, 1
    masks = struct.pack("<III", 0xF800, 0x07E0, 0x001F)
    pixels = struct.pack("<HH", 0xF800, 0x07E0)
    offset = 14 + 40 + len(masks)
    size = offset + len(pixels)
    return (
        struct.pack("<2sIHHI", b"BM", size, 0, 0, offset)
        + struct.pack(
            "<IiiHHIIiiII",
            40,
            width,
            height,
            1,
            16,
            3,
            len(pixels),
            0,
            0,
            0,
            0,
        )
        + masks
        + pixels
    )


def manual_tga16() -> bytes:
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,
        0,
        2,
        0,
        0,
        0,
        0,
        0,
        2,
        1,
        16,
        0,
    )
    return header + struct.pack("<HH", 0x7C00, 0x03E0)


@pytest.mark.parametrize("top_down", [False, True])
def test_bmp_manual_orientation_and_pillow_parity(top_down):
    pixels = make_pixels(3, height=3, width=5)
    data = manual_bmp24(pixels, top_down=top_down)
    decoded = _core.read_bmp(data)
    np.testing.assert_array_equal(decoded.pixels, pixels)
    np.testing.assert_array_equal(decoded.pixels, pil_decode(data, "RGB"))
    assert decoded.color_space == "srgb"
    assert decoded.alpha_mode == "none"
    assert _core._inspect_bmp(data) == (
        3,
        5,
        3,
        24,
        0,
        False,
        top_down,
    )


def test_bmp_palette_and_one_bit_expand_like_pillow():
    indices = np.array([[0, 1, 2, 1], [2, 0, 1, 2]], dtype=np.uint8)
    palette_image = PilImage.fromarray(indices, mode="P")
    palette = [0] * 768
    palette[0:9] = [10, 20, 30, 200, 40, 50, 1, 240, 90]
    palette_image.putpalette(palette)
    stream = io.BytesIO()
    palette_image.save(stream, format="BMP")
    data = stream.getvalue()
    decoded = _core.read_bmp(data)
    np.testing.assert_array_equal(decoded.pixels, pil_decode(data, "RGB"))
    assert decoded.channels == 3
    assert _core._inspect_bmp(data)[5] is True

    mono = (indices & 1) * 255
    one_bit = pil_encode(mono, "BMP", bits=1)
    np.testing.assert_array_equal(
        _core.read_bmp(one_bit).pixels,
        pil_decode(one_bit, "RGB"),
    )


def test_bmp_16bit_bitfields_matches_pillow():
    data = manual_bmp565()
    expected = np.array([[[255, 0, 0], [0, 255, 0]]], dtype=np.uint8)
    np.testing.assert_array_equal(_core.read_bmp(data).pixels, expected)
    np.testing.assert_array_equal(pil_decode(data, "RGB"), expected)
    assert _core._inspect_bmp(data)[3:5] == (16, 3)


@pytest.mark.parametrize(
    "masks",
    [
        (0xF800, 0x07E0, 0x07E0),
        (0xF810, 0x07E0, 0x001F),
        (0xFFFF, 0x07E0, 0x001F),
    ],
)
def test_bmp_rejects_overlapping_noncontiguous_or_wide_masks(masks):
    data = bytearray(manual_bmp565())
    struct.pack_into("<III", data, 54, *masks)
    with pytest.raises(ValueError, match="masks"):
        _core.read_bmp(bytes(data))


def test_bmp_bi_rgb_32_ignores_unused_high_byte():
    rgba = make_pixels(4, height=3, width=4)
    data = pil_encode(rgba, "BMP")
    decoded = _core.read_bmp(data)
    assert decoded.channels == 3
    np.testing.assert_array_equal(decoded.pixels, pil_decode(data, "RGB"))
    np.testing.assert_array_equal(decoded.pixels, rgba[..., :3])


@pytest.mark.parametrize("channels", [3, 4])
def test_bmp_writer_is_deterministic_and_pillow_decodes_exactly(channels):
    pixels = make_pixels(channels)
    record = image_record(pixels)
    first = bytes(_core.write_bmp(record))
    second = bytes(_core.write_bmp(record))
    assert first == second
    np.testing.assert_array_equal(pil_decode(first), pixels)
    np.testing.assert_array_equal(_core.read_bmp(first).pixels, pixels)
    info = _core._inspect_bmp(first)
    assert info[:3] == (7, 9, channels)
    assert info[4] == (3 if channels == 4 else 0)


@pytest.mark.parametrize(
    ("channels", "compression", "orientation"),
    [
        (1, None, None),
        (1, "tga_rle", 1),
        (3, None, 1),
        (3, "tga_rle", None),
        (4, None, None),
        (4, "tga_rle", 1),
    ],
)
def test_tga_pillow_read_parity(channels, compression, orientation):
    pixels = make_pixels(channels)
    options = {}
    if compression is not None:
        options["compression"] = compression
    if orientation is not None:
        options["orientation"] = orientation
    data = pil_encode(pixels, "TGA", **options)
    decoded = _core.read_tga(data)
    np.testing.assert_array_equal(decoded.pixels, pixels)
    np.testing.assert_array_equal(decoded.pixels, pil_decode(data))
    info = _core._inspect_tga(data)
    assert info[:3] == (7, 9, channels)
    assert info[4] is (compression == "tga_rle")


def test_tga_palette_matches_pillow():
    indices = np.array([[0, 1, 2, 1], [2, 0, 1, 2]], dtype=np.uint8)
    image = PilImage.fromarray(indices, mode="P")
    palette = [0] * 768
    palette[0:9] = [10, 20, 30, 200, 40, 50, 1, 240, 90]
    image.putpalette(palette)
    stream = io.BytesIO()
    image.save(stream, format="TGA", compression="tga_rle")
    data = stream.getvalue()
    decoded = _core.read_tga(data)
    np.testing.assert_array_equal(decoded.pixels, pil_decode(data, "RGB"))
    assert decoded.channels == 3
    assert _core._inspect_tga(data)[5] is True


def test_tga_16bit_packed_color_matches_pillow():
    data = manual_tga16()
    expected = np.array([[[255, 0, 0], [0, 255, 0]]], dtype=np.uint8)
    np.testing.assert_array_equal(_core.read_tga(data).pixels, expected)
    np.testing.assert_array_equal(pil_decode(data, "RGB"), expected)


@pytest.mark.parametrize("channels", [1, 3, 4])
def test_tga_writer_is_deterministic_rle_and_pillow_exact(channels):
    pixels = make_pixels(channels)
    record = image_record(pixels)
    first = bytes(_core.write_tga(record))
    assert first == bytes(_core.write_tga(record))
    assert first[2] == (11 if channels == 1 else 10)
    np.testing.assert_array_equal(pil_decode(first), pixels)
    np.testing.assert_array_equal(_core.read_tga(first).pixels, pixels)
    info = _core._inspect_tga(first)
    assert info[:3] == (7, 9, channels)
    assert info[4] is True


def test_randomized_pillow_differential_reads():
    rng = np.random.default_rng(20260724)
    for _ in range(40):
        height = int(rng.integers(1, 13))
        width = int(rng.integers(1, 17))

        bmp_channels = int(rng.choice([1, 3, 4]))
        bmp_pixels = rng.integers(
            0,
            256,
            (
                (height, width)
                if bmp_channels == 1
                else (height, width, bmp_channels)
            ),
            dtype=np.uint8,
        )
        bmp = pil_encode(bmp_pixels, "BMP")
        np.testing.assert_array_equal(
            _core.read_bmp(bmp).pixels,
            pil_decode(bmp, "RGB"),
        )

        tga_channels = int(rng.choice([1, 3, 4]))
        tga_pixels = rng.integers(
            0,
            256,
            (
                (height, width)
                if tga_channels == 1
                else (height, width, tga_channels)
            ),
            dtype=np.uint8,
        )
        tga = pil_encode(
            tga_pixels,
            "TGA",
            compression=(
                "tga_rle" if bool(rng.integers(0, 2)) else None
            ),
            orientation=int(rng.integers(0, 2)),
            id_section=b"sceneio-differential",
        )
        np.testing.assert_array_equal(
            _core.read_tga(tga).pixels,
            pil_decode(tga),
        )


@pytest.mark.parametrize(
    ("format_id", "mutation", "message"),
    [
        ("bmp", lambda data: b"ZZ" + data[2:], "missing BM"),
        (
            "bmp",
            lambda data: data[:30] + struct.pack("<I", 1) + data[34:],
            "RLE",
        ),
        (
            "bmp",
            lambda data: data[:14] + struct.pack("<I", 12) + data[18:],
            "Windows DIB",
        ),
        (
            "tga",
            lambda data: data[:17] + bytes([data[17] | 0x10]) + data[18:],
            "right-to-left",
        ),
        (
            "tga",
            lambda data: data[:17] + bytes([data[17] | 0x40]) + data[18:],
            "interleaved",
        ),
    ],
)
def test_unsupported_headers_reject(format_id, mutation, message):
    pixels = make_pixels(3, height=2, width=3)
    data = (
        manual_bmp24(pixels, top_down=False)
        if format_id == "bmp"
        else bytes(_core.write_tga(image_record(pixels)))
    )
    with pytest.raises(ValueError, match=message):
        getattr(_core, f"read_{format_id}")(mutation(data))


def test_tga_rejects_nonzero_palette_origin_and_grayscale_alpha():
    indices = np.array([[0, 1]], dtype=np.uint8)
    image = PilImage.fromarray(indices, mode="P")
    stream = io.BytesIO()
    image.save(stream, format="TGA")
    palette = bytearray(stream.getvalue())
    palette[3:5] = struct.pack("<H", 1)
    with pytest.raises(ValueError, match="palette origins"):
        _core.read_tga(bytes(palette))

    la = bytearray(18 + 2)
    la[2] = 3
    la[12:14] = struct.pack("<H", 1)
    la[14:16] = struct.pack("<H", 1)
    la[16] = 16
    la[17] = 8
    with pytest.raises(ValueError, match="grayscale\\+alpha"):
        _core.read_tga(bytes(la))


@pytest.mark.parametrize("format_id", ["bmp", "tga"])
def test_every_truncated_writer_prefix_rejects(format_id):
    pixels = make_pixels(3, height=3, width=4)
    data = bytes(
        getattr(_core, f"write_{format_id}")(image_record(pixels))
    )
    reader = getattr(_core, f"read_{format_id}")
    for stop in range(len(data)):
        with pytest.raises(ValueError):
            reader(data[:stop])


def test_tga_rejects_rle_packet_overrun_and_short_packet():
    pixels = make_pixels(3, height=1, width=2)
    data = bytearray(_core.write_tga(image_record(pixels)))
    data[18] = 0x82  # three-pixel packet for a two-pixel raster
    with pytest.raises(ValueError, match="exceeds"):
        _core.read_tga(bytes(data))

    data = bytearray(_core.write_tga(image_record(pixels)))
    del data[-1]
    with pytest.raises(ValueError, match="truncated"):
        _core.read_tga(bytes(data))


def test_bmp_rejects_palette_index_out_of_range():
    indices = np.array([[0, 1]], dtype=np.uint8)
    image = PilImage.fromarray(indices, mode="P")
    image.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    stream = io.BytesIO()
    image.save(stream, format="BMP")
    data = bytearray(stream.getvalue())
    offset = struct.unpack_from("<I", data, 10)[0]
    data[offset] = 255
    struct.pack_into("<I", data, 46, 2)
    # Remove unused palette entries so header and offset still agree.
    compact = data[:54] + data[54:62] + data[offset:]
    struct.pack_into("<I", compact, 2, len(compact))
    struct.pack_into("<I", compact, 10, 62)
    with pytest.raises(ValueError, match="palette"):
        _core.read_bmp(bytes(compact))


@pytest.mark.parametrize(
    ("format_id", "record_factory", "message"),
    [
        (
            "bmp",
            lambda: image_record(make_pixels(1)),
            "channel count",
        ),
        (
            "bmp",
            lambda: _core.image(
                make_pixels(3).astype(np.uint16),
                color_space="srgb",
                maxval=255,
            ),
            "uint8",
        ),
        (
            "tga",
            lambda: _core.image(make_pixels(3), color_space="linear"),
            "srgb",
        ),
        (
            "tga",
            lambda: _core.image(
                make_pixels(4),
                color_space="srgb",
                alpha_mode="premultiplied",
            ),
            "straight",
        ),
        (
            "tga",
            lambda: _core.image(
                make_pixels(1), color_space="gray", maxval=100
            ),
            "maxval 255",
        ),
    ],
)
def test_writers_guard_unrepresentable_records(
    format_id, record_factory, message
):
    with pytest.raises(ValueError, match=message):
        getattr(_core, f"write_{format_id}")(record_factory())


@pytest.mark.parametrize("format_id", ["bmp", "tga"])
def test_mmap_equals_bytes_and_decoded_image_owns_pixels(tmp_path, format_id):
    pixels = make_pixels(4)
    data = bytes(
        getattr(_core, f"write_{format_id}")(image_record(pixels))
    )
    expected = getattr(_core, f"read_{format_id}")(data)
    path = tmp_path / f"mapped.{format_id}"
    path.write_bytes(data)
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        actual = getattr(_core, f"read_{format_id}")(mapped)
        mapped.close()
    gc.collect()
    np.testing.assert_array_equal(actual.pixels, expected.pixels)
    np.testing.assert_array_equal(actual.pixels, pixels)


@pytest.mark.parametrize("format_id", ["bmp", "tga"])
def test_public_detect_read_write_and_inspect(tmp_path, format_id):
    pixels = make_pixels(3)
    source = tmp_path / f"source.{format_id}"
    sceneio.write(image_record(pixels), source)
    assert sceneio.detect(source) == format_id
    np.testing.assert_array_equal(sceneio.read(source).pixels, pixels)
    info = sceneio.inspect(source)
    assert info.format == format_id
    assert info.shape == pixels.shape
    assert info.dtype == "uint8"
    assert info.channels == 3
    assert info.metadata["bits_per_pixel"] == 24


@pytest.mark.parametrize("format_id", ["bmp", "tga"])
def test_sparse_large_inspection_has_bounded_python_memory(
    tmp_path, format_id
):
    pixels = make_pixels(3, height=1, width=1)
    data = bytes(
        getattr(_core, f"write_{format_id}")(image_record(pixels))
    )
    path = tmp_path / f"large.{format_id}"
    with path.open("wb") as stream:
        stream.write(data)
        stream.truncate(64 * 1024 * 1024)
    gc.collect()
    tracemalloc.start()
    try:
        info = sceneio.inspect(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert info.shape == pixels.shape
    assert peak < 1024 * 1024


@pytest.mark.parametrize("format_id", ["bmp", "tga"])
def test_chunked_sink_is_identical_and_avoids_output_python_bytes(
    tmp_path, format_id
):
    rng = np.random.default_rng(20260724)
    pixels = rng.integers(0, 256, (1024, 1024, 3), dtype=np.uint8)
    record = image_record(pixels)
    writer = getattr(_core, f"write_{format_id}")

    gc.collect()
    tracemalloc.start()
    try:
        expected = bytes(writer(record))
        _, buffer_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    path = tmp_path / f"sink.{format_id}"
    gc.collect()
    tracemalloc.start()
    try:
        calls = _core._write_to_file(
            writer,
            record,
            path,
            _max_chunk=4096,
            _test_short_write=31,
        )
        _, sink_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert calls >= 10
    assert path.read_bytes() == expected
    assert buffer_peak > len(expected) * 0.8
    assert sink_peak < len(expected) * 0.2
