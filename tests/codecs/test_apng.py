"""APNG parity against Pillow and an independent stdlib chunk oracle."""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np
import pytest
from PIL import Image as PillowImage

import sceneio
from sceneio import _core


def _sequence(
    frames: np.ndarray,
    durations_ns: tuple[int, ...] = (
        40_000_000,
        70_000_000,
        30_000_000,
    ),
    *,
    loop_count: int = 2,
    background: np.ndarray | None = None,
):
    durations = np.asarray(durations_ns, dtype=np.int64)
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
        background,
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


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    body = chunk_type + payload
    return (
        struct.pack(">I", len(payload))
        + body
        + struct.pack(">I", zlib.crc32(body) & 0xFFFF_FFFF)
    )


def _frame_payload(frame: np.ndarray) -> bytes:
    rows = b"".join(b"\0" + row.tobytes() for row in frame)
    return zlib.compress(rows)


def _oracle_apng() -> bytes:
    """Build subrect/blend/disposal APNG without SceneIO or Pillow."""

    height, width = 3, 4
    first = np.empty((height, width, 4), np.uint8)
    first[...] = (240, 10, 20, 255)
    second = np.empty((2, 2, 4), np.uint8)
    second[...] = (10, 220, 30, 128)
    third = np.empty((3, 1, 4), np.uint8)
    third[...] = (15, 25, 245, 255)

    sequence = 0
    chunks = [
        _chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0),
        ),
        _chunk(b"acTL", struct.pack(">II", 3, 4)),
        _chunk(
            b"fcTL",
            struct.pack(
                ">IIIIIHHBB",
                sequence,
                width,
                height,
                0,
                0,
                1,
                20,
                0,
                0,
            ),
        ),
        _chunk(b"IDAT", _frame_payload(first)),
    ]
    sequence += 1
    chunks.extend(
        [
            _chunk(
                b"fcTL",
                struct.pack(
                    ">IIIIIHHBB",
                    sequence,
                    2,
                    2,
                    1,
                    0,
                    3,
                    100,
                    1,
                    1,
                ),
            ),
            _chunk(
                b"fdAT",
                struct.pack(">I", sequence + 1) + _frame_payload(second),
            ),
        ]
    )
    sequence += 2
    chunks.extend(
        [
            _chunk(
                b"fcTL",
                struct.pack(
                    ">IIIIIHHBB",
                    sequence,
                    1,
                    3,
                    0,
                    0,
                    1,
                    25,
                    2,
                    0,
                ),
            ),
            _chunk(
                b"fdAT",
                struct.pack(">I", sequence + 1) + _frame_payload(third),
            ),
            _chunk(b"IEND", b""),
        ]
    )
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def test_sceneio_writer_is_lossless_deterministic_and_oracle_readable():
    frames = _rgba_frames()
    sequence = _sequence(frames)
    encoded = bytes(_core.write_apng(sequence))

    assert encoded == bytes(_core.write_apng(sequence))
    assert _core._is_apng(encoded)
    oracle_frames, oracle_durations, oracle_loop = _pillow_decode(encoded)
    np.testing.assert_array_equal(oracle_frames, frames)
    assert oracle_durations == (40, 70, 30)
    assert oracle_loop == 2

    decoded = _core.read_apng(encoded)
    np.testing.assert_array_equal(decoded.pixels, frames)
    assert decoded.timestamps_ns.tolist() == [0, 40_000_000, 110_000_000]
    assert decoded.durations_ns.tolist() == [
        40_000_000,
        70_000_000,
        30_000_000,
    ]
    assert decoded.loop_count == 2
    assert not decoded.has_background


def test_pillow_writer_is_sceneio_readable_bit_exact():
    frames = _rgba_frames()
    images = [PillowImage.fromarray(frame, "RGBA") for frame in frames]
    output = io.BytesIO()
    images[0].save(
        output,
        format="PNG",
        save_all=True,
        append_images=images[1:],
        duration=[35, 55, 75],
        loop=3,
        disposal=[0, 0, 0],
        blend=[0, 0, 0],
    )

    decoded = _core.read_apng(output.getvalue())
    np.testing.assert_array_equal(decoded.pixels, frames)
    assert decoded.timestamps_ns.tolist() == [0, 35_000_000, 90_000_000]
    assert decoded.durations_ns.tolist() == [
        35_000_000,
        55_000_000,
        75_000_000,
    ]
    assert decoded.loop_count == 3


def test_independent_subrect_blend_and_disposal_match_pillow():
    encoded = _oracle_apng()
    oracle_frames, oracle_durations, oracle_loop = _pillow_decode(encoded)
    decoded = _core.read_apng(encoded)

    expected = np.empty((3, 3, 4, 4), np.uint8)
    expected[0, ...] = (240, 10, 20, 255)
    expected[1] = expected[0]
    expected[1, 0:2, 1:3] = (125, 115, 25, 255)
    expected[2] = expected[0]
    expected[2, 0:2, 1:3] = (0, 0, 0, 0)
    expected[2, :, 0] = (15, 25, 245, 255)
    np.testing.assert_array_equal(decoded.pixels, expected)
    # Pillow 11.3 produces the same composited color channels but retains
    # alpha=191 for the blend-over rectangle. The APNG source-over equation
    # gives alpha=255 over an opaque destination, as the stdlib/spec expected
    # array above asserts.
    np.testing.assert_array_equal(
        oracle_frames[..., :3], expected[..., :3]
    )
    assert decoded.durations_ns.tolist() == [
        value * 1_000_000 for value in oracle_durations
    ]
    assert decoded.loop_count == oracle_loop == 4


def test_exact_submillisecond_rational_timing():
    frames = _rgba_frames()[:2]
    sequence = _sequence(frames, (500_000, 1_500_000))
    encoded = _core.write_apng(sequence)
    decoded = _core.read_apng(encoded)

    assert decoded.durations_ns.tolist() == [500_000, 1_500_000]
    assert _core._inspect_apng(encoded)["duration_ns"] == 2_000_000


def test_metadata_inspection_does_not_decode_pixels():
    encoded = _core.write_apng(_sequence(_rgba_frames()))
    metadata = _core._inspect_apng(memoryview(encoded))
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
    }


def test_public_path_detect_read_write_and_inspect(tmp_path):
    frames = _rgba_frames()
    sequence = _sequence(frames)
    expected = _core.write_apng(sequence)
    path = tmp_path / "animation.png"
    sceneio.write(sequence, path)

    assert path.read_bytes() == expected
    assert sceneio.detect(path) == "apng"
    inspection = sceneio.inspect(path)
    assert inspection.format == "apng"
    assert inspection.shape == (3, 5, 7, 4)
    assert inspection.count == 3
    assert inspection.metadata["duration_ns"] == 140_000_000
    np.testing.assert_array_equal(sceneio.read(path).pixels, frames)

    extensionless = tmp_path / "animation"
    extensionless.write_bytes(expected)
    assert sceneio.detect(extensionless) == "apng"
    np.testing.assert_array_equal(sceneio.read(extensionless).pixels, frames)

    still_path = tmp_path / "still.png"
    sceneio.write(
        _core.image(np.zeros((3, 4, 4), np.uint8), alpha_mode="straight"),
        still_path,
    )
    assert sceneio.detect(still_path) == "png"
    assert isinstance(sceneio.read(still_path), _core.Image)


def test_direct_sink_streams_container_chunks_byte_identically(tmp_path):
    sequence = _sequence(_rgba_frames())
    expected = bytes(_core.write_apng(sequence))
    path = tmp_path / "streamed.apng"

    native_write_calls = _core._write_to_file(
        _core.write_apng, sequence, path
    )

    assert native_write_calls > sequence.num_frames
    assert path.read_bytes() == expected


def test_rgb_and_identical_frames_preserve_sequence():
    rgba = _rgba_frames()
    rgb = np.ascontiguousarray(rgba[..., :3])
    rgb_encoded = _core.write_apng(_sequence(rgb))
    np.testing.assert_array_equal(
        _core.read_apng(rgb_encoded).pixels[..., :3],
        rgb,
    )

    repeated = np.stack((rgba[0], rgba[0]))
    decoded = _core.read_apng(
        _core.write_apng(_sequence(repeated, (25_000_000, 35_000_000)))
    )
    assert decoded.num_frames == 2
    assert decoded.durations_ns.tolist() == [25_000_000, 35_000_000]
    np.testing.assert_array_equal(decoded.pixels, repeated)


def test_writer_refuses_unrepresented_metadata_and_timing():
    frames = _rgba_frames()
    with pytest.raises(ValueError, match="background"):
        _core.write_apng(
            _sequence(
                frames,
                background=np.array([1, 2, 3, 4], np.uint8),
            )
        )

    durations = np.array([1, 40_000_000, 70_000_000], np.int64)
    timestamps = np.array([0, 1, 40_000_001], np.int64)
    sequence = _core.image_sequence_packed(
        frames,
        timestamps,
        durations,
        "srgb",
        "straight",
    )
    with pytest.raises(ValueError, match="uint16 rational"):
        _core.write_apng(sequence)


def test_separate_default_image_and_malformed_inputs_are_rejected():
    frames = _rgba_frames()
    images = [PillowImage.fromarray(frame, "RGBA") for frame in frames]
    output = io.BytesIO()
    images[0].save(
        output,
        format="PNG",
        save_all=True,
        append_images=images[1:],
        duration=[40, 70],
        loop=1,
        default_image=True,
    )
    with pytest.raises(ValueError, match="default image"):
        _core.read_apng(output.getvalue())

    valid = bytes(_core.write_apng(_sequence(frames)))
    corrupt_crc = bytearray(valid)
    corrupt_crc[32] ^= 1
    for malformed in (
        b"",
        valid[:20],
        valid[:-7],
        bytes(corrupt_crc),
        _core.write_png(
            _core.image(
                np.zeros((3, 4, 4), np.uint8),
                alpha_mode="straight",
            )
        ),
    ):
        with pytest.raises(ValueError):
            _core.read_apng(malformed)
