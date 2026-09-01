"""Native IVF VP8/VP9/AV1 container and public-I/O coverage."""

from __future__ import annotations

import struct

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _sequence(frames: int = 5):
    frame, row, column = np.indices((frames, 24, 32))
    pixels = np.stack(
        (
            (column * 7 + frame * 19) % 256,
            (row * 11 + frame * 13) % 256,
            (column * 3 + row * 5 + frame * 17) % 256,
        ),
        axis=-1,
    ).astype(np.uint8)
    durations = np.full(frames, 40_000_000, np.int64)
    timestamps = np.arange(frames, dtype=np.int64) * durations[0]
    return _core.image_sequence_packed(
        pixels, timestamps, durations, "srgb", "none", None, None, None
    )


def _ivf_oracle(data: bytes):
    assert len(data) >= 32
    signature, version, header_size, fourcc = struct.unpack_from("<4sHH4s", data)
    width, height, rate, scale, frames, unused = struct.unpack_from(
        "<HHIIII", data, 12
    )
    assert (signature, version, header_size, unused) == (b"DKIF", 0, 32, 0)
    packets = []
    position = 32
    while position < len(data):
        size, timestamp = struct.unpack_from("<IQ", data, position)
        position += 12
        packets.append((timestamp, data[position : position + size]))
        position += size
    assert position == len(data)
    assert len(packets) == frames
    return fourcc, width, height, rate, scale, packets


@pytest.mark.parametrize(
    ("codec", "fourcc"),
    [("vp8", b"VP80"), ("vp9", b"VP90"), ("av1", b"AV01")],
)
def test_native_writer_and_reader_have_independent_container_oracle_and_range(
    codec, fourcc
):
    sequence = _sequence()
    encoded = bytes(_core.write_ivf(sequence, codec=codec, threads=1))
    actual_fourcc, width, height, rate, scale, packets = _ivf_oracle(encoded)
    assert (actual_fourcc, width, height, rate, scale) == (
        fourcc,
        32,
        24,
        25,
        1,
    )
    assert [timestamp for timestamp, _packet in packets] == list(range(5))
    assert all(packet for _timestamp, packet in packets)

    metadata = dict(_core._inspect_ivf(encoded))
    assert metadata == {
        "width": 32,
        "height": 24,
        "frames": 5,
        "channels": 3,
        "dtype": "uint8",
        "color_space": "ycbcr",
        "alpha_mode": "none",
        "storage_mode": "yuv_planar",
        "codec": codec,
        "frame_rate_numerator": 25,
        "frame_rate_denominator": 1,
    }
    full = _core.read_ivf(encoded)
    partial = _core.read_ivf_frames(encoded, 1, 4)
    for selected, complete in zip(
        (partial.y, partial.u, partial.v),
        (full.y, full.u, full.v),
        strict=True,
    ):
        np.testing.assert_array_equal(selected, complete[1:4])
    assert partial.timestamps_ns.tolist() == [40_000_000, 80_000_000, 120_000_000]


@pytest.mark.parametrize("profile", ["vp8", "vp9", "av1"])
def test_public_profiles_detect_inspect_and_stream(tmp_path, profile):
    path = tmp_path / f"video-{profile}.ivf"
    sequence = _sequence()
    sceneio.write(sequence, path, format="ivf", profile=profile)

    assert sceneio.detect(path) == "ivf"
    inspection = sceneio.inspect(path)
    assert inspection.format == "ivf"
    assert inspection.shape == (5, 24, 32, 3)
    assert inspection.metadata["codec"] == profile
    assert [array.name for array in inspection.arrays] == ["y", "u", "v"]
    full = sceneio.read(path)
    partial = sceneio.read_partial(path, frames=(2, 5))
    np.testing.assert_array_equal(partial.y, full.y[2:5])


def test_ivf_rejects_truncation_junk_and_unknown_public_profile(tmp_path):
    encoded = bytes(_core.write_ivf(_sequence(), codec="av1"))
    for malformed in (b"", encoded[:31], encoded[:-1], encoded + b"junk"):
        with pytest.raises(ValueError):
            _core._inspect_ivf(malformed)
        with pytest.raises(ValueError):
            _core.read_ivf(malformed)

    with pytest.raises(sceneio.FormatError, match="unknown profile"):
        sceneio.write(
            _sequence(), tmp_path / "unused.ivf", format="ivf", profile="vp10"
        )
