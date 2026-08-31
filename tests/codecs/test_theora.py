"""Ogg/Theora parity against an independent Ogg framing oracle.

The codec payload is produced and consumed through the upstream libtheora
reference API. Container correctness is triangulated independently here: this
module parses page headers/lacing/checksums, reconstructs packets, and remuxes
those packets into a distinct valid page layout without calling SceneIO's Ogg
implementation.
"""

from __future__ import annotations

import gc
import mmap
import struct
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _crc(payload: bytes | bytearray) -> int:
    value = 0
    for byte in payload:
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04C11DB7 if value & 0x80000000 else 0))
            value &= 0xFFFFFFFF
    return value


def _oracle_packets(data: bytes):
    """Validate one Ogg stream and return (packet, granule) rows."""

    offset = 0
    expected_sequence = 0
    serial = None
    pending = bytearray()
    packets: list[list[bytes | int]] = []
    saw_eos = False
    while offset < len(data):
        assert data[offset : offset + 4] == b"OggS"
        assert offset + 27 <= len(data)
        version, flags = struct.unpack_from("<BB", data, offset + 4)
        granule, page_serial, sequence, checksum = struct.unpack_from(
            "<qIII", data, offset + 6
        )
        assert version == 0
        segments = data[offset + 26]
        assert offset + 27 + segments <= len(data)
        lacing = data[offset + 27 : offset + 27 + segments]
        body_size = sum(lacing)
        end = offset + 27 + segments + body_size
        assert end <= len(data)
        page = bytearray(data[offset:end])
        page[22:26] = b"\0\0\0\0"
        assert _crc(page) == checksum
        assert sequence == expected_sequence
        expected_sequence += 1
        if serial is None:
            serial = page_serial
            assert flags & 0x02
        else:
            assert page_serial == serial
            assert not flags & 0x02
        assert bool(flags & 0x01) is bool(pending)
        body = memoryview(data)[offset + 27 + segments : end]
        position = 0
        completed = []
        for amount in lacing:
            pending += body[position : position + amount]
            position += amount
            if amount < 255:
                completed.append(len(packets))
                packets.append([bytes(pending), -1])
                pending.clear()
        if completed:
            packets[completed[-1]][1] = granule
        saw_eos = bool(flags & 0x04)
        if saw_eos:
            assert end == len(data)
        offset = end
    assert offset == len(data) and not pending and saw_eos and packets
    return [(bytes(packet), int(granule)) for packet, granule in packets]


def _page(
    packet: bytes,
    granule: int,
    *,
    serial: int,
    sequence: int,
    bos: bool,
    eos: bool,
) -> bytes:
    lacing = bytes([255] * (len(packet) // 255) + [len(packet) % 255])
    assert len(lacing) <= 255
    header = bytearray(b"OggS\0")
    header.append((0x02 if bos else 0) | (0x04 if eos else 0))
    header += struct.pack("<qIII", granule, serial, sequence, 0)
    header.append(len(lacing))
    header += lacing
    payload = header + packet
    struct.pack_into("<I", payload, 22, _crc(payload))
    return bytes(payload)


def _oracle_remux(packets, *, replace_comment: bytes | None = None) -> bytes:
    output = bytearray()
    for index, (packet, granule) in enumerate(packets):
        if index == 1 and replace_comment is not None:
            packet = replace_comment
        output += _page(
            packet,
            granule,
            serial=0x4F52434C,
            sequence=index,
            bos=index == 0,
            eos=index + 1 == len(packets),
        )
    return bytes(output)


def _timing(count: int, numerator: int, denominator: int):
    period = 1_000_000_000 * denominator
    base, remainder = divmod(period, numerator)
    timestamp = 0
    accumulator = 0
    timestamps = []
    durations = []
    for _ in range(count):
        duration = base
        accumulator += remainder
        if accumulator >= numerator:
            accumulator -= numerator
            duration += 1
        timestamps.append(timestamp)
        durations.append(duration)
        timestamp += duration
    return np.asarray(timestamps, np.int64), np.asarray(durations, np.int64)


def _record(
    *, frames: int = 4, height: int = 18, width: int = 22, timing: bool = True
):
    frame, row, column = np.indices((frames, height, width))
    y = ((16 + 3 * column + 5 * row + 7 * frame) % 220).astype(np.uint8)
    chroma_shape = (frames, (height + 1) // 2, (width + 1) // 2)
    cframe, crow, ccolumn = np.indices(chroma_shape)
    u = ((80 + 2 * ccolumn + 3 * crow + 5 * cframe) % 170).astype(np.uint8)
    v = ((110 + 3 * ccolumn + 2 * crow + 4 * cframe) % 150).astype(np.uint8)
    timestamps, durations = (
        _timing(frames, 30_000, 1_001)
        if timing
        else (np.empty(0, np.int64), np.empty(0, np.int64))
    )
    return (
        _core.image_sequence_yuv(
            y,
            u,
            v,
            timestamps,
            durations,
            "420",
            "unspecified",
            "unknown",
            "unknown",
            "progressive",
            30_000,
            1_001,
            4,
            3,
        ),
        (y, u, v),
    )


def _assert_decoded(actual, expected_planes) -> None:
    assert actual.storage_mode == "yuv_planar"
    assert actual.frame_dtype == "uint8"
    assert actual.color_space == "ycbcr"
    assert actual.chroma_subsampling == "420"
    assert actual.chroma_siting == "unspecified"
    assert actual.color_range == actual.matrix == "unknown"
    assert actual.interlace == "progressive"
    assert (actual.pixel_aspect_numerator, actual.pixel_aspect_denominator) == (
        4,
        3,
    )
    for decoded, expected in zip(
        (np.asarray(actual.y), np.asarray(actual.u), np.asarray(actual.v)),
        expected_planes,
        strict=True,
    ):
        error = np.abs(decoded.astype(np.int16) - expected.astype(np.int16))
        assert float(error.mean()) < 3.0
        assert int(error.max()) <= 20


def test_sceneio_write_is_valid_for_independent_ogg_oracle_and_remux(tmp_path):
    sequence, planes = _record()
    encoded = bytes(_core.write_theora(sequence, quality=63))
    packets = _oracle_packets(encoded)
    assert [packet[:7] for packet, _granule in packets[:3]] == [
        b"\x80theora",
        b"\x81theora",
        b"\x82theora",
    ]
    assert len(packets) == sequence.num_frames + 3

    remuxed = _oracle_remux(packets)
    decoded = _core.read_theora(remuxed)
    _assert_decoded(decoded, planes)
    original = _core.read_theora(encoded)
    np.testing.assert_array_equal(np.asarray(decoded.y), np.asarray(original.y))
    np.testing.assert_array_equal(np.asarray(decoded.u), np.asarray(original.u))
    np.testing.assert_array_equal(np.asarray(decoded.v), np.asarray(original.v))

    path = tmp_path / "oracle.ogv"
    path.write_bytes(remuxed)
    assert sceneio.detect(path) == "theora"
    public = sceneio.read(path)
    np.testing.assert_array_equal(np.asarray(public.y), np.asarray(decoded.y))


def test_public_write_inspect_and_direct_sink_are_exact(tmp_path):
    sequence, _planes = _record()
    expected = bytes(_core.write_theora(sequence))
    path = tmp_path / "sequence.ogv"
    sceneio.write(sequence, path)
    assert path.read_bytes() == expected
    assert _oracle_packets(path.read_bytes())
    info = sceneio.inspect(path)
    assert info.format == "theora"
    assert info.payload_kind == "image_sequence"
    assert info.shape == (4, 18, 22, 3)
    assert info.dtype == "uint8" and info.channels == 3
    assert [array.name for array in info.arrays] == ["y", "u", "v"]
    assert dict(info.metadata) == {
        "storage_mode": "yuv_planar",
        "codec": "theora",
        "version": "3.2.1",
        "chroma_subsampling": "420",
        "chroma_siting": "unspecified",
        "color_range": "unknown",
        "matrix": "unknown",
        "interlace": "progressive",
        "frame_rate_numerator": 30_000,
        "frame_rate_denominator": 1_001,
        "pixel_aspect_numerator": 4,
        "pixel_aspect_denominator": 3,
        "frame_width": 32,
        "frame_height": 32,
        "picture_x": 0,
        "picture_y": 0,
        "keyframe_granule_shift": 6,
    }


def test_partial_is_bit_exact_slice_and_preserves_global_timing(tmp_path):
    sequence, _planes = _record(frames=6)
    path = tmp_path / "range.ogg"
    sceneio.write(sequence, path, format="theora")
    full = sceneio.read(path)
    selected = sceneio.read_partial(path, frames=(2, 5))
    np.testing.assert_array_equal(np.asarray(selected.y), np.asarray(full.y)[2:5])
    np.testing.assert_array_equal(np.asarray(selected.u), np.asarray(full.u)[2:5])
    np.testing.assert_array_equal(np.asarray(selected.v), np.asarray(full.v)[2:5])
    np.testing.assert_array_equal(
        np.asarray(selected.timestamps_ns), np.asarray(full.timestamps_ns)[2:5]
    )
    np.testing.assert_array_equal(
        np.asarray(selected.durations_ns), np.asarray(full.durations_ns)[2:5]
    )
    with pytest.raises(sceneio.FormatError, match="frame range"):
        sceneio.read_partial(path, frames=(5, 7))


def test_buffer_protocol_mmap_and_lifetime(tmp_path):
    sequence, _planes = _record(frames=12, height=64, width=96)
    encoded = bytes(_core.write_theora(sequence, quality=63))
    path = tmp_path / "mapped.ogv"
    path.write_bytes(encoded)
    from_bytes = _core.read_theora(encoded)
    with path.open("rb") as stream, mmap.mmap(
        stream.fileno(), 0, access=mmap.ACCESS_READ
    ) as mapped:
        from_map = _core.read_theora(mapped)
        np.testing.assert_array_equal(
            np.asarray(from_map.y), np.asarray(from_bytes.y)
        )
        assert _core._buffer_address(mapped) == np.frombuffer(mapped, np.uint8).ctypes.data
    path.unlink()
    del from_bytes
    gc.collect()
    assert int(np.asarray(from_map.y).sum()) > 0


def test_inspection_does_not_allocate_encoded_or_decoded_payload(tmp_path):
    sequence, _planes = _record(frames=96, height=128, width=192)
    path = tmp_path / "large.ogv"
    sceneio.write(sequence, path)
    decoded_bytes = sequence.num_frames * sequence.height * sequence.width * 3 // 2
    tracemalloc.start()
    info = sceneio.inspect(path)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.count == sequence.num_frames
    assert peak < 512 * 1024
    assert peak < decoded_bytes / 4


def test_rejects_bad_framing_checksum_chaining_comments_and_writer_projection():
    sequence, _planes = _record()
    encoded = bytes(_core.write_theora(sequence))
    for payload, message in (
        (b"", "truncated|no video|Ogg"),
        (encoded[:-1], "truncated|end-of-stream"),
        (encoded + encoded, "follows end|trailing|multiple|chained"),
    ):
        with pytest.raises(ValueError, match=message):
            _core.read_theora(payload)

    damaged = bytearray(encoded)
    damaged[-1] ^= 1
    with pytest.raises(ValueError, match=r"checksum|framing"):
        _core.read_theora(bytes(damaged))

    packets = _oracle_packets(encoded)
    comment = packets[1][0]
    vendor_size = struct.unpack_from("<I", comment, 7)[0]
    vendor_end = 11 + vendor_size
    replacement = (
        comment[:vendor_end]
        + struct.pack("<I", 1)
        + struct.pack("<I", 7)
        + b"TITLE=x"
    )
    commented = _oracle_remux(packets, replace_comment=replacement)
    with pytest.raises(ValueError, match="comments are not represented"):
        _core.read_theora(commented)

    bad_granule = list(packets)
    last_packet, last_granule = bad_granule[-1]
    bad_granule[-1] = (last_packet, last_granule + 1)
    with pytest.raises(ValueError, match="granule position"):
        _core.read_theora(_oracle_remux(bad_granule))

    explicit = _core.image_sequence_yuv(
        np.asarray(sequence.y),
        np.asarray(sequence.u),
        np.asarray(sequence.v),
        np.asarray(sequence.timestamps_ns),
        np.asarray(sequence.durations_ns),
        "420",
        "unspecified",
        "limited",
        "bt601",
        "progressive",
        30_000,
        1_001,
        4,
        3,
    )
    with pytest.raises(ValueError, match="range or matrix"):
        _core.write_theora(explicit)
