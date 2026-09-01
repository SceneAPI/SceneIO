"""Read-only classic ISO BMFF AV1 coverage with a bounded container oracle."""

from __future__ import annotations

import struct

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _full_box(kind: bytes, payload: bytes, *, version: int = 0) -> bytes:
    return _box(kind, bytes((version, 0, 0, 0)) + payload)


def _source_sequence(frames: int = 5):
    frame, row, column = np.indices((frames, 24, 32))
    y = ((16 + column * 5 + row * 3 + frame * 17) % 220).astype(np.uint8)
    cframe, crow, ccolumn = np.indices((frames, 12, 16))
    u = ((70 + ccolumn * 3 + crow * 2 + cframe * 7) % 170).astype(np.uint8)
    v = ((90 + ccolumn * 2 + crow * 5 + cframe * 11) % 160).astype(np.uint8)
    durations = np.full(frames, 40_000_000, np.int64)
    return _core.image_sequence_yuv(
        y,
        u,
        v,
        np.arange(frames, dtype=np.int64) * durations[0],
        durations,
        "420",
        "unspecified",
        "limited",
        "bt601",
        "progressive",
        25,
        1,
        1,
        1,
    )


def _ivf_packets(data: bytes) -> tuple[bytes, ...]:
    assert data[:4] == b"DKIF" and data[8:12] == b"AV01"
    count = int.from_bytes(data[24:28], "little")
    packets = []
    position = 32
    for _ in range(count):
        size = int.from_bytes(data[position : position + 4], "little")
        position += 12
        packets.append(data[position : position + size])
        position += size
    assert position == len(data)
    return tuple(packets)


def _minimal_av1_mp4(
    sequence=None,
    *,
    pixel_aspect: tuple[int, int] | None = None,
    edit: tuple[int, int, int] | None = None,
) -> bytes:
    sequence = _source_sequence() if sequence is None else sequence
    packets = _ivf_packets(bytes(_core.write_ivf(sequence, codec="av1", threads=1)))
    sample_payload = b"".join(packets)

    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isomav01")
    mdat = _box(b"mdat", sample_payload)
    sample_offset = len(ftyp) + 8

    visual_entry = bytearray(78)
    visual_entry[6:8] = struct.pack(">H", 1)
    visual_entry[24:28] = struct.pack(">HH", sequence.width, sequence.height)
    # AV1CodecConfigurationRecord: profile 0, 8-bit, 4:2:0. The first media
    # sample carries the sequence-header OBU, so no config OBUs are duplicated.
    color = _box(
        b"colr",
        b"nclx" + struct.pack(">HHHB", 1, 1, 6, 0),
    )
    aspect = (
        b""
        if pixel_aspect is None
        else _box(b"pasp", struct.pack(">II", *pixel_aspect))
    )
    av01 = _box(
        b"av01",
        bytes(visual_entry)
        + _box(b"av1C", b"\x81\x00\x0c\x00")
        + color
        + aspect,
    )
    stsd = _full_box(b"stsd", struct.pack(">I", 1) + av01)
    stsz = _full_box(
        b"stsz",
        struct.pack(">II", 0, len(packets))
        + b"".join(struct.pack(">I", len(packet)) for packet in packets),
    )
    stsc = _full_box(b"stsc", struct.pack(">IIII", 1, 1, len(packets), 1))
    stco = _full_box(b"stco", struct.pack(">II", 1, sample_offset))
    stts = _full_box(b"stts", struct.pack(">III", 1, len(packets), 1))
    stbl = _box(b"stbl", stsd + stsz + stsc + stco + stts)
    minf = _box(b"minf", stbl)
    mdhd = _full_box(
        b"mdhd", struct.pack(">IIII", 0, 0, 25, len(packets))
    )
    hdlr = _full_box(b"hdlr", b"\0\0\0\0vide")
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    edit_box = b""
    if edit is not None:
        leading_duration, media_duration, media_start = edit
        entries = b"".join(
            (
                struct.pack(">IiHH", leading_duration, -1, 1, 0),
                struct.pack(">IiHH", media_duration, media_start, 1, 0),
            )
        )
        edit_box = _box(
            b"edts",
            _full_box(b"elst", struct.pack(">I", 2) + entries),
        )
    trak = _box(b"trak", edit_box + mdia)
    mvhd = _full_box(
        b"mvhd", struct.pack(">IIII", 0, 0, 1000, len(packets) * 40)
    )
    moov = _box(b"moov", mvhd + trak)
    return ftyp + mdat + moov


def test_minimal_container_inspects_decodes_and_ranges():
    encoded = _minimal_av1_mp4()
    assert encoded[4:8] == b"ftyp"
    assert encoded.find(b"av01") > 0
    metadata = dict(_core._inspect_mp4(encoded))
    assert metadata == {
        "width": 32,
        "height": 24,
        "frames": 5,
        "channels": 3,
        "dtype": "uint8",
        "source_bit_depth": 8,
        "color_space": "ycbcr",
        "color_range": "limited",
        "matrix": "bt601",
        "alpha_mode": "none",
        "storage_mode": "yuv_planar",
        "chroma_subsampling": "420",
        "codec": "av1",
        "frame_rate_numerator": 25,
        "frame_rate_denominator": 1,
        "pixel_aspect_numerator": 0,
        "pixel_aspect_denominator": 0,
        "duration_ns": 200_000_000,
        "timing_projection": "nearest_nanosecond",
    }
    full = _core.read_mp4(encoded)
    partial = _core.read_mp4_frames(encoded, 1, 4)
    for selected, complete in zip(
        (partial.y, partial.u, partial.v),
        (full.y, full.u, full.v),
        strict=True,
    ):
        np.testing.assert_array_equal(selected, complete[1:4])
    assert full.timestamps_ns.tolist() == [
        0,
        40_000_000,
        80_000_000,
        120_000_000,
        160_000_000,
    ]


def test_edit_list_and_pixel_aspect_select_the_display_timeline():
    baseline = _core.read_mp4(_minimal_av1_mp4())
    encoded = _minimal_av1_mp4(
        pixel_aspect=(4, 3),
        # Movie timescale is 1000 and media timescale is 25. Retain media
        # ticks [1, 4), preceded by a 40 ms empty edit.
        edit=(40, 120, 1),
    )
    metadata = dict(_core._inspect_mp4(encoded))
    assert metadata["frames"] == 3
    assert metadata["pixel_aspect_numerator"] == 4
    assert metadata["pixel_aspect_denominator"] == 3

    edited = _core.read_mp4(encoded)
    assert edited.timestamps_ns.tolist() == [40_000_000, 80_000_000, 120_000_000]
    assert edited.durations_ns.tolist() == [40_000_000] * 3
    assert (edited.pixel_aspect_numerator, edited.pixel_aspect_denominator) == (
        4,
        3,
    )
    for actual, expected in zip(
        (edited.y, edited.u, edited.v),
        (baseline.y[1:4], baseline.u[1:4], baseline.v[1:4]),
        strict=True,
    ):
        np.testing.assert_array_equal(actual, expected)

    partial = _core.read_mp4_frames(encoded, 1, 3)
    np.testing.assert_array_equal(partial.y, edited.y[1:3])


def test_public_detect_inspect_read_and_read_only_contract(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(_minimal_av1_mp4())

    assert sceneio.detect(path) == "mp4"
    inspection = sceneio.inspect(path)
    assert inspection.format == "mp4"
    assert inspection.shape == (5, 24, 32, 3)
    assert inspection.metadata["source_bit_depth"] == 8
    full = sceneio.read(path)
    partial = sceneio.read_partial(path, frames=(2, 5))
    np.testing.assert_array_equal(partial.y, full.y[2:5])
    assert sceneio.capabilities("mp4").can_write is False
    with pytest.raises(sceneio.FormatError, match="read-only"):
        sceneio.write(full, tmp_path / "output.mp4", format="mp4")


def test_mp4_rejects_truncation_fragmentation_and_out_of_mdat_offset():
    encoded = _minimal_av1_mp4()
    stco = encoded.index(b"stco")
    offset_position = stco + 12
    outside = bytearray(encoded)
    outside[offset_position : offset_position + 4] = struct.pack(">I", len(encoded))
    fragmented = encoded + _box(b"moof", b"")
    for malformed in (b"", encoded[:-1], bytes(outside), fragmented):
        with pytest.raises(ValueError):
            _core._inspect_mp4(malformed)
        with pytest.raises(ValueError):
            _core.read_mp4(malformed)
