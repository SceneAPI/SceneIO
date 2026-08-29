"""Animated WebP parity against Pillow/libwebp's independent container path."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image as PillowImage

import sceneio
from sceneio import _core


def _sequence(
    frames: np.ndarray,
    durations_ms: tuple[int, ...] = (40, 70, 30),
    *,
    loop_count: int = 2,
):
    durations = np.asarray(durations_ms, dtype=np.int64) * 1_000_000
    timestamps = np.concatenate(
        [np.zeros(1, np.int64), np.cumsum(durations[:-1])]
    )
    return _core.image_sequence_packed(
        frames,
        timestamps,
        durations,
        "srgb",
        "straight" if frames.shape[-1] == 4 else "none",
        None,
        loop_count,
        np.array([1, 2, 3, 4], np.uint8),
    )


def _rgba_frames() -> np.ndarray:
    frames = np.zeros((3, 5, 7, 4), np.uint8)
    frames[0, ...] = (255, 0, 0, 255)
    frames[1, ...] = (0, 255, 0, 128)
    frames[2, ...] = (0, 0, 255, 255)
    frames[1, 1:4, 2:6] = (17, 29, 41, 0)
    return frames


def _pillow_decode(data: bytes):
    image = PillowImage.open(io.BytesIO(data))
    frames = []
    durations = []
    for index in range(image.n_frames):
        image.seek(index)
        frames.append(np.asarray(image.convert("RGBA")).copy())
        durations.append(int(image.info["duration"]))
    return np.stack(frames), tuple(durations), int(image.info["loop"])


def test_sceneio_writer_is_lossless_and_oracle_readable():
    frames = _rgba_frames()
    encoded = _core.write_animated_webp(_sequence(frames))

    assert _core._is_animated_webp(encoded)
    oracle_frames, oracle_durations, oracle_loop = _pillow_decode(encoded)
    np.testing.assert_array_equal(oracle_frames, frames)
    assert oracle_durations == (40, 70, 30)
    assert oracle_loop == 2

    decoded = _core.read_animated_webp(encoded)
    np.testing.assert_array_equal(decoded.pixels, frames)
    assert decoded.timestamps_ns.tolist() == [0, 40_000_000, 110_000_000]
    assert decoded.durations_ns.tolist() == [40_000_000, 70_000_000, 30_000_000]
    assert decoded.loop_count == 2
    assert decoded.background_rgba.tolist() == [1, 2, 3, 4]


def test_pillow_writer_is_sceneio_readable_bit_exact():
    frames = _rgba_frames()
    # The WebP model does not promise RGB preservation where alpha is zero.
    # Keep the independent writer fixture canonical on those samples.
    frames[frames[..., 3] == 0, :3] = 0
    images = [PillowImage.fromarray(frame, "RGBA") for frame in frames]
    output = io.BytesIO()
    images[0].save(
        output,
        format="WEBP",
        save_all=True,
        append_images=images[1:],
        duration=[35, 55, 75],
        loop=3,
        lossless=True,
        exact=True,
        minimize_size=True,
    )

    decoded = _core.read_animated_webp(output.getvalue())
    np.testing.assert_array_equal(decoded.pixels, frames)
    assert decoded.timestamps_ns.tolist() == [0, 35_000_000, 90_000_000]
    assert decoded.durations_ns.tolist() == [35_000_000, 55_000_000, 75_000_000]
    assert decoded.loop_count == 3


def test_metadata_inspection_does_not_decode_pixels():
    encoded = _core.write_animated_webp(_sequence(_rgba_frames()))
    metadata = _core._inspect_animated_webp(memoryview(encoded))
    assert metadata == {
        "width": 7,
        "height": 5,
        "frames": 3,
        "channels": 4,
        "dtype": "uint8",
        "color_space": "srgb",
        "alpha_mode": "straight",
        "loop_count": 2,
        "duration_ns": 140_000_000,
        "background_rgba": (1, 2, 3, 4),
    }


def test_public_path_detect_read_write_and_inspect(tmp_path):
    frames = _rgba_frames()
    sequence = _sequence(frames)
    expected = _core.write_animated_webp(sequence)
    path = tmp_path / "animation.webp"
    sceneio.write(sequence, path)

    assert path.read_bytes() == expected
    assert sceneio.detect(path) == "animated_webp"
    inspection = sceneio.inspect(path)
    assert inspection.format == "animated_webp"
    assert inspection.shape == (3, 5, 7, 4)
    assert inspection.count == 3
    assert inspection.metadata["duration_ns"] == 140_000_000
    np.testing.assert_array_equal(sceneio.read(path).pixels, frames)

    still_path = tmp_path / "still.webp"
    sceneio.write(
        _core.image(np.zeros((3, 4, 3), np.uint8)),
        still_path,
    )
    assert sceneio.detect(still_path) == "webp"
    assert isinstance(sceneio.read(still_path), _core.Image)


def test_rgb_and_worker_modes_have_identical_decoded_output():
    rgba = _rgba_frames()
    rgb = np.ascontiguousarray(rgba[..., :3])
    sequence = _sequence(rgb)
    threaded = _core.write_animated_webp(sequence, _threads=True)
    single = _core.write_animated_webp(sequence, _threads=False)

    assert threaded == single
    np.testing.assert_array_equal(
        _core.read_animated_webp(threaded).pixels[..., :3],
        rgb,
    )
    np.testing.assert_array_equal(
        _core.read_animated_webp(single).pixels[..., :3],
        rgb,
    )


def test_identical_frames_preserve_animation_length_and_timing(tmp_path):
    frame = _rgba_frames()[0]
    frames = np.stack((frame, frame))
    sequence = _sequence(frames, (25, 35))
    encoded = _core.write_animated_webp(sequence)

    decoded = _core.read_animated_webp(encoded)
    assert decoded.num_frames == 2
    assert decoded.durations_ns.tolist() == [25_000_000, 35_000_000]
    np.testing.assert_array_equal(decoded.pixels, frames)

    path = tmp_path / "identical.webp"
    path.write_bytes(encoded)
    assert sceneio.detect(path) == "animated_webp"


@pytest.mark.parametrize(
    ("timestamps", "durations", "message"),
    [
        ([1_000_000, 41_000_000, 111_000_000], [40, 70, 30], "start at zero"),
        ([0, 41_000_000, 111_000_000], [40, 70, 30], "contiguous"),
        ([0, 40_000_001, 110_000_001], [40, 70, 30], "milliseconds"),
    ],
)
def test_writer_refuses_unrepresentable_timing(timestamps, durations, message):
    frames = _rgba_frames()
    sequence = _core.image_sequence_packed(
        frames,
        np.asarray(timestamps, np.int64),
        np.asarray(durations, np.int64) * 1_000_000,
        "srgb",
        "straight",
    )
    with pytest.raises(ValueError, match=message):
        _core.write_animated_webp(sequence)


def test_still_truncated_and_corrupt_inputs_are_rejected():
    still = _core.write_webp(
        _core.image(np.zeros((3, 4, 3), np.uint8))
    )
    assert not _core._is_animated_webp(still)
    with pytest.raises(ValueError, match="not animated"):
        _core.read_animated_webp(still)

    encoded = _core.write_animated_webp(_sequence(_rgba_frames()))
    for malformed in (b"", encoded[:20], encoded[:-7], b"RIFF\x10\0\0\0WEBPANIM"):
        with pytest.raises(ValueError):
            _core.read_animated_webp(malformed)
