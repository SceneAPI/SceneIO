"""Raw concatenated-JPEG (MJPEG) codec coverage."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image as PillowImage

import sceneio
from sceneio import _core


def _sequence(*, grayscale: bool = False):
    frame, row, column = np.indices((4, 19, 27))
    if grayscale:
        pixels = ((column * 7 + row * 5 + frame * 29) % 256).astype(np.uint8)[
            ..., None
        ]
        color_space = "gray"
    else:
        pixels = np.stack(
            (
                (column * 7 + frame * 29) % 256,
                (row * 11 + frame * 13) % 256,
                (column * 3 + row * 5 + frame * 17) % 256,
            ),
            axis=-1,
        ).astype(np.uint8)
        color_space = "srgb"
    empty = np.empty(0, np.int64)
    return _core.image_sequence_packed(
        pixels, empty, empty, color_space, "none", None, None, None
    )


def _jpeg_frames(data: bytes) -> tuple[bytes, ...]:
    frames = []
    position = 0
    while position < len(data):
        assert data[position : position + 2] == b"\xff\xd8"
        end = data.index(b"\xff\xd9", position + 2) + 2
        frames.append(data[position:end])
        position = end
    return tuple(frames)


@pytest.mark.parametrize("grayscale", [False, True])
def test_native_round_trip_matches_independent_pillow_decode(grayscale):
    sequence = _sequence(grayscale=grayscale)
    if grayscale:
        encoded_frames = []
        for pixels in sequence.pixels:
            output = io.BytesIO()
            PillowImage.fromarray(pixels, "L").save(
                output, format="JPEG", quality=91
            )
            encoded_frames.append(output.getvalue())
        encoded = b"".join(encoded_frames)
    else:
        encoded = bytes(_core.write_mjpeg(sequence, quality=91))
    frames = _jpeg_frames(encoded)
    assert len(frames) == 4
    mode = "L" if grayscale else "RGB"
    oracle = []
    for frame in frames:
        with PillowImage.open(io.BytesIO(frame)) as image:
            decoded = np.asarray(image.convert(mode)).copy()
            oracle.append(decoded)
    expected = np.stack(oracle)
    actual = _core.read_mjpeg(encoded)
    # Pillow and stb_image use slightly different integer IDCT rounding.
    np.testing.assert_allclose(actual.pixels, expected, rtol=0, atol=2)
    assert actual.timestamps_ns.size == actual.durations_ns.size == 0

    partial = _core.read_mjpeg_frames(encoded, 1, 3)
    np.testing.assert_array_equal(partial.pixels, actual.pixels[1:3])


def test_public_detect_inspect_read_write_and_range(tmp_path):
    path = tmp_path / "frames.mjpeg"
    sceneio.write(_sequence(), path, format="mjpeg")

    assert sceneio.detect(path) == "mjpeg"
    inspection = sceneio.inspect(path)
    assert inspection.format == "mjpeg"
    assert inspection.shape == (4, 19, 27, 3)
    assert inspection.metadata == {
        "storage_mode": "packed",
        "codec": "mjpeg",
        "color_space": "srgb",
        "alpha_mode": "none",
        "timing": "absent",
    }
    full = sceneio.read(path)
    partial = sceneio.read_partial(path, frames=(2, 4))
    np.testing.assert_array_equal(partial.pixels, full.pixels[2:4])


def test_mjpeg_rejects_truncation_junk_and_timed_input():
    encoded = bytes(_core.write_mjpeg(_sequence()))
    for malformed in (b"", encoded[:-1], encoded + b"junk"):
        with pytest.raises(ValueError):
            _core._inspect_mjpeg(malformed)
        with pytest.raises(ValueError):
            _core.read_mjpeg(malformed)

    assert b"\xff\xc0" in encoded
    unsupported_sof = encoded.replace(b"\xff\xc0", b"\xff\xc9", 1)
    with pytest.raises(ValueError, match="supported frame header"):
        _core._inspect_mjpeg(unsupported_sof)
    with pytest.raises(ValueError, match="supported frame header"):
        _core.read_mjpeg(unsupported_sof)

    pixels = np.asarray(_sequence().pixels)
    durations = np.full(4, 40_000_000, np.int64)
    timed = _core.image_sequence_packed(
        pixels,
        np.arange(4, dtype=np.int64) * durations[0],
        durations,
        "srgb",
        "none",
        None,
        None,
        None,
    )
    with pytest.raises(ValueError, match="timing"):
        _core.write_mjpeg(timed)
    with pytest.raises(ValueError, match="sRGB"):
        _core.write_mjpeg(_sequence(grayscale=True))
