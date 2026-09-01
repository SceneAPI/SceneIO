"""Bounded WebM/VP8 parity against an independent EBML and Pillow oracle."""

from __future__ import annotations

import gc
import io
import mmap
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PillowImage

import sceneio
from sceneio import _core


def _sequence(
    frames: np.ndarray,
    durations_ms: tuple[int, ...] = (40, 70, 30),
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
        "none",
        None,
        None,
        None,
    )


def _frames() -> np.ndarray:
    y, x = np.mgrid[:18, :26]
    frames = np.empty((3, 18, 26, 3), np.uint8)
    frames[0] = np.stack((x * 9, y * 13, (x + y) * 5), axis=-1)
    frames[1] = np.stack(((25 - x) * 7, (17 - y) * 11, x * y), axis=-1)
    frames[2] = np.stack((x ^ y, x * 3 + y * 2, 255 - x * 4), axis=-1)
    return frames


def _temporal_sequence(frames: int = 8, height: int = 24, width: int = 32):
    frame, row, column = np.indices((frames, height, width))
    y = ((16 + 3 * column + 2 * row + 11 * frame) % 220).astype(np.uint8)
    chroma_shape = (frames, (height + 1) // 2, (width + 1) // 2)
    cframe, crow, ccolumn = np.indices(chroma_shape)
    u = ((70 + 2 * ccolumn + 3 * crow + 5 * cframe) % 170).astype(np.uint8)
    v = ((100 + 3 * ccolumn + 2 * crow + 4 * cframe) % 150).astype(np.uint8)
    durations = np.full(frames, 40_000_000, np.int64)
    timestamps = np.arange(frames, dtype=np.int64) * durations[0]
    return _core.image_sequence_yuv(
        y,
        u,
        v,
        timestamps,
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


def _id(value: int) -> bytes:
    return value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")


def _size(value: int) -> bytes:
    width = 1
    while value > (1 << (7 * width)) - 2:
        width += 1
    return (value | (1 << (7 * width))).to_bytes(width, "big")


def _element(element_id: int, payload: bytes) -> bytes:
    return _id(element_id) + _size(len(payload)) + payload


def _uint(element_id: int, value: int) -> bytes:
    width = max(1, (value.bit_length() + 7) // 8)
    return _element(element_id, value.to_bytes(width, "big"))


def _text(element_id: int, value: str) -> bytes:
    return _element(element_id, value.encode("ascii"))


def _read_vint(data: bytes, position: int, *, keep_marker: bool):
    first = data[position]
    marker = 0x80
    width = 1
    while not first & marker:
        marker >>= 1
        width += 1
    raw = int.from_bytes(data[position : position + width], "big")
    if keep_marker:
        return raw, width, False
    value = first & (0xFF >> width)
    for byte in data[position + 1 : position + width]:
        value = (value << 8) | byte
    return value, width, value == (1 << (7 * width)) - 1


def _elements(data: bytes, start: int, stop: int):
    position = start
    while position < stop:
        element_id, id_width, _ = _read_vint(
            data, position, keep_marker=True
        )
        size, size_width, unknown = _read_vint(
            data, position + id_width, keep_marker=False
        )
        body = position + id_width + size_width
        end = stop if unknown else body + size
        assert body <= end <= stop
        yield element_id, body, end
        position = end
    assert position == stop


def _value(data: bytes, start: int, stop: int) -> int:
    return int.from_bytes(data[start:stop], "big")


def _vp8_from_webp(payload: bytes) -> bytes:
    assert payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    position = 12
    packets = []
    while position < len(payload):
        fourcc = payload[position : position + 4]
        size = int.from_bytes(payload[position + 4 : position + 8], "little")
        position += 8
        chunk = payload[position : position + size]
        position += size + (size & 1)
        if fourcc == b"VP8 ":
            packets.append(chunk)
    assert len(packets) == 1
    return packets[0]


def _webp_from_vp8(packet: bytes) -> bytes:
    chunk = b"VP8 " + len(packet).to_bytes(4, "little") + packet
    if len(packet) & 1:
        chunk += b"\0"
    return b"RIFF" + (len(chunk) + 4).to_bytes(4, "little") + b"WEBP" + chunk


def _pillow_packet(frame: np.ndarray, *, quality: int = 82) -> bytes:
    output = io.BytesIO()
    PillowImage.fromarray(frame, "RGB").save(
        output,
        format="WEBP",
        lossless=False,
        quality=quality,
        method=4,
    )
    return _vp8_from_webp(output.getvalue())


def _decode_packet(packet: bytes) -> np.ndarray:
    with PillowImage.open(io.BytesIO(_webp_from_vp8(packet))) as image:
        return np.asarray(image.convert("RGB")).copy()


def _independent_simpleblock_webm(
    packets: tuple[bytes, ...],
    *,
    width: int,
    height: int,
    duration_ms: int,
) -> bytes:
    ebml = b"".join(
        (
            _uint(0x4286, 1),
            _uint(0x42F7, 1),
            _uint(0x42F2, 4),
            _uint(0x42F3, 8),
            _text(0x4282, "webm"),
            _uint(0x4287, 2),
            _uint(0x4285, 2),
        )
    )
    info = b"".join(
        (
            _uint(0x2AD7B1, 1_000_000),
            _text(0x4D80, "oracle"),
            _text(0x5741, "oracle"),
        )
    )
    video = b"".join(
        (
            _uint(0x9A, 2),
            _uint(0xB0, width),
            _uint(0xBA, height),
        )
    )
    track = b"".join(
        (
            _uint(0xD7, 1),
            _uint(0x73C5, 9),
            _uint(0x83, 1),
            _uint(0x9C, 0),
            _uint(0x23E383, duration_ms * 1_000_000),
            _text(0x86, "V_VP8"),
            _element(0xE0, video),
        )
    )
    blocks = []
    for index, packet in enumerate(packets):
        timestamp = index * duration_ms
        block = b"\x81" + struct.pack(">hB", timestamp, 0x80) + packet
        blocks.append(_element(0xA3, block))
    cluster = _uint(0xE7, 0) + b"".join(blocks)
    segment = b"".join(
        (
            _element(0x1549A966, info),
            _element(0x1654AE6B, _element(0xAE, track)),
            _element(0x1F43B675, cluster),
        )
    )
    return _element(0x1A45DFA3, ebml) + _element(0x18538067, segment)


def _oracle_demux(data: bytes):
    roots = list(_elements(data, 0, len(data)))
    assert [item[0] for item in roots] == [0x1A45DFA3, 0x18538067]
    _, segment_start, segment_stop = roots[1]
    width = height = None
    default_duration_ms = None
    packets = []
    for element_id, start, stop in _elements(data, segment_start, segment_stop):
        if element_id == 0x1654AE6B:
            entries = list(_elements(data, start, stop))
            assert len(entries) == 1 and entries[0][0] == 0xAE
            for track_id, track_start, track_stop in _elements(
                data, entries[0][1], entries[0][2]
            ):
                if track_id == 0x23E383:
                    default_duration_ms = (
                        _value(data, track_start, track_stop) // 1_000_000
                    )
                elif track_id == 0xE0:
                    for video_id, video_start, video_stop in _elements(
                        data, track_start, track_stop
                    ):
                        if video_id == 0xB0:
                            width = _value(data, video_start, video_stop)
                        elif video_id == 0xBA:
                            height = _value(data, video_start, video_stop)
        elif element_id == 0x1F43B675:
            cluster_timestamp = None
            for cluster_id, cluster_start, cluster_stop in _elements(
                data, start, stop
            ):
                if cluster_id == 0xE7:
                    cluster_timestamp = _value(
                        data, cluster_start, cluster_stop
                    )
                elif cluster_id == 0xA0:
                    block = None
                    duration = None
                    for group_id, group_start, group_stop in _elements(
                        data, cluster_start, cluster_stop
                    ):
                        if group_id == 0xA1:
                            block = data[group_start:group_stop]
                        elif group_id == 0x9B:
                            duration = _value(data, group_start, group_stop)
                    assert cluster_timestamp is not None
                    assert block is not None and duration is not None
                    relative = int.from_bytes(block[1:3], "big", signed=True)
                    packets.append((cluster_timestamp + relative, duration, block[4:]))
                elif cluster_id == 0xA3:
                    assert cluster_timestamp is not None
                    block = data[cluster_start:cluster_stop]
                    relative = int.from_bytes(block[1:3], "big", signed=True)
                    packets.append((cluster_timestamp + relative, None, block[4:]))
    assert width is not None and height is not None and packets
    resolved = []
    for index, (timestamp, duration, packet) in enumerate(packets):
        if duration is None:
            duration = (
                packets[index + 1][0] - timestamp
                if index + 1 < len(packets)
                else default_duration_ms
            )
        assert duration is not None
        resolved.append((timestamp, duration, packet))
    return width, height, tuple(resolved)


def _oracle_temporal_profile(data: bytes):
    roots = list(_elements(data, 0, len(data)))
    _, segment_start, segment_stop = roots[1]
    codec = matrix = color_range = None
    keyframes = []
    references = []
    for element_id, start, stop in _elements(data, segment_start, segment_stop):
        if element_id == 0x1654AE6B:
            entries = list(_elements(data, start, stop))
            assert len(entries) == 1 and entries[0][0] == 0xAE
            for track_id, track_start, track_stop in _elements(
                data, entries[0][1], entries[0][2]
            ):
                if track_id == 0x86:
                    codec = data[track_start:track_stop].decode("ascii")
                elif track_id == 0xE0:
                    for video_id, video_start, video_stop in _elements(
                        data, track_start, track_stop
                    ):
                        if video_id != 0x55B0:
                            continue
                        for color_id, color_start, color_stop in _elements(
                            data, video_start, video_stop
                        ):
                            if color_id == 0x55B1:
                                matrix = _value(data, color_start, color_stop)
                            elif color_id == 0x55B9:
                                color_range = _value(
                                    data, color_start, color_stop
                                )
        elif element_id == 0x1F43B675:
            for cluster_id, cluster_start, cluster_stop in _elements(
                data, start, stop
            ):
                if cluster_id != 0xA0:
                    continue
                child_ids = {
                    child_id
                    for child_id, _child_start, _child_stop in _elements(
                        data, cluster_start, cluster_stop
                    )
                }
                keyframes.append(0xFB not in child_ids)
                reference = None
                for child_id, child_start, child_stop in _elements(
                    data, cluster_start, cluster_stop
                ):
                    if child_id == 0xFB:
                        reference = int.from_bytes(
                            data[child_start:child_stop], "big", signed=True
                        )
                references.append(reference)
    assert codec in {"V_VP8", "V_VP9", "V_AV1"}
    assert matrix in {1, 6, 9}
    assert color_range in {1, 2}
    assert keyframes and keyframes[0]
    return codec, matrix, color_range, tuple(keyframes), tuple(references)


def _replace_first_block_duration(data: bytes, value: int) -> bytes:
    changed = bytearray(data)
    roots = list(_elements(data, 0, len(data)))
    _, segment_start, segment_stop = roots[1]
    for element_id, start, stop in _elements(data, segment_start, segment_stop):
        if element_id != 0x1F43B675:
            continue
        for cluster_id, cluster_start, cluster_stop in _elements(
            data, start, stop
        ):
            if cluster_id != 0xA0:
                continue
            for group_id, group_start, group_stop in _elements(
                data, cluster_start, cluster_stop
            ):
                if group_id == 0x9B:
                    assert group_stop - group_start == 1
                    changed[group_start] = value
                    return bytes(changed)
    raise AssertionError("fixture has no BlockDuration")


def _replace_first_reference(data: bytes, value: int) -> bytes:
    changed = bytearray(data)
    roots = list(_elements(data, 0, len(data)))
    _, segment_start, segment_stop = roots[1]
    for element_id, start, stop in _elements(data, segment_start, segment_stop):
        if element_id != 0x1F43B675:
            continue
        for cluster_id, cluster_start, cluster_stop in _elements(
            data, start, stop
        ):
            if cluster_id != 0xA0:
                continue
            for group_id, group_start, group_stop in _elements(
                data, cluster_start, cluster_stop
            ):
                if group_id == 0xFB:
                    width = group_stop - group_start
                    changed[group_start:group_stop] = value.to_bytes(
                        width, "big", signed=True
                    )
                    return bytes(changed)
    raise AssertionError("fixture has no ReferenceBlock")


def test_sceneio_writer_is_deterministic_and_oracle_decodable():
    sequence = _sequence(_frames())
    encoded = _core.write_webm(sequence, quality=87)

    assert encoded == _core.write_webm(sequence, quality=87)
    width, height, packets = _oracle_demux(encoded)
    assert (width, height) == (26, 18)
    assert [(timestamp, duration) for timestamp, duration, _ in packets] == [
        (0, 40),
        (40, 70),
        (110, 30),
    ]
    oracle = np.stack([_decode_packet(packet) for _, _, packet in packets])
    decoded = _core.read_webm(encoded)
    np.testing.assert_array_equal(decoded.pixels, oracle)
    assert decoded.timestamps_ns.tolist() == [0, 40_000_000, 110_000_000]
    assert decoded.durations_ns.tolist() == [40_000_000, 70_000_000, 30_000_000]


def test_independent_simpleblock_writer_is_sceneio_readable():
    frames = _frames()
    packets = tuple(_pillow_packet(frame) for frame in frames)
    encoded = _independent_simpleblock_webm(
        packets,
        width=26,
        height=18,
        duration_ms=40,
    )

    metadata = dict(_core._inspect_webm(encoded))
    assert metadata == {
        "width": 26,
        "height": 18,
        "frames": 3,
        "channels": 3,
        "dtype": "uint8",
        "color_space": "srgb",
        "alpha_mode": "none",
        "codec": "vp8",
        "profile": "all_keyframe",
        "storage_mode": "packed",
        "matrix": "unknown",
        "color_range": "unknown",
        "keyframes": 3,
        "duration_ns": 120_000_000,
    }
    decoded = _core.read_webm(memoryview(encoded))
    oracle = np.stack([_decode_packet(packet) for packet in packets])
    np.testing.assert_array_equal(decoded.pixels, oracle)
    assert decoded.timestamps_ns.tolist() == [0, 40_000_000, 80_000_000]
    assert decoded.durations_ns.tolist() == [40_000_000] * 3


def test_public_detect_read_write_inspect_partial_and_direct_sink(tmp_path):
    sequence = _sequence(_frames())
    expected = _core.write_webm(sequence)
    path = tmp_path / "video.webm"
    sceneio.write(sequence, path, format="webm")

    assert path.read_bytes() == expected
    assert sceneio.detect(path) == "webm"
    inspection = sceneio.inspect(path)
    assert inspection.format == "webm"
    assert inspection.shape == (3, 18, 26, 3)
    assert inspection.metadata == {
        "storage_mode": "packed",
        "color_space": "srgb",
        "alpha_mode": "none",
        "codec": "vp8",
        "profile": "all_keyframe",
        "matrix": "unknown",
        "color_range": "unknown",
        "keyframes": 3,
        "duration_ns": 140_000_000,
    }
    full = sceneio.read(path)
    partial = sceneio.read_partial(path, frames=(1, 3))
    np.testing.assert_array_equal(partial.pixels, full.pixels[1:3])
    assert partial.timestamps_ns.tolist() == [40_000_000, 110_000_000]

    direct = tmp_path / "direct.webm"
    calls = _core._write_to_file(_core.write_webm, sequence, direct)
    assert calls >= 4
    assert direct.read_bytes() == expected


def test_mapped_decode_owns_pixels_after_mapping_closes(tmp_path):
    path = tmp_path / "mapped.webm"
    path.write_bytes(_core.write_webm(_sequence(_frames())))
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        decoded = _core.read_webm(mapped)
        snapshot = np.array(decoded.pixels, copy=True)
        mapped.close()
    gc.collect()
    np.testing.assert_array_equal(decoded.pixels, snapshot)


def test_thread_modes_produce_identical_bytes_and_pixels():
    sequence = _sequence(_frames())
    threaded = _core.write_webm(sequence, _threads=True)
    single = _core.write_webm(sequence, _threads=False)
    assert threaded == single
    np.testing.assert_array_equal(
        _core.read_webm(threaded).pixels,
        _core.read_webm(single).pixels,
    )


@pytest.mark.parametrize("codec", ["vp8", "vp9", "av1"])
def test_temporal_writer_has_independent_container_oracle_and_partial(codec):
    sequence = _temporal_sequence()
    source_planes = tuple(
        np.array(plane, copy=True) for plane in (sequence.y, sequence.u, sequence.v)
    )
    encoded = bytes(
        _core.write_webm_temporal(
            sequence,
            codec=codec,
            quality=82,
            threads=1,
            keyframe_interval=4,
        )
    )
    for actual, expected in zip(
        (sequence.y, sequence.u, sequence.v), source_planes, strict=True
    ):
        np.testing.assert_array_equal(actual, expected)
    oracle_codec, matrix, color_range, keyframes, references = (
        _oracle_temporal_profile(encoded)
    )
    assert oracle_codec == f"V_{codec.upper()}"
    assert (matrix, color_range) == (6, 1)
    assert keyframes == (True, False, False, False, True, False, False, False)
    assert references == (None, -40, -40, -40, None, -40, -40, -40)

    metadata = dict(_core._inspect_webm(encoded))
    assert metadata == {
        "width": 32,
        "height": 24,
        "frames": 8,
        "channels": 3,
        "dtype": "uint8",
        "alpha_mode": "none",
        "color_space": "ycbcr",
        "color_range": "limited",
        "matrix": "bt601",
        "codec": codec,
        "profile": "temporal",
        "storage_mode": "yuv_planar",
        "keyframes": 2,
        "duration_ns": 320_000_000,
    }
    full = _core.read_webm(encoded)
    partial = _core.read_webm_frames(encoded, 2, 7)
    assert full.storage_mode == partial.storage_mode == "yuv_planar"
    assert full.matrix == partial.matrix == "bt601"
    assert full.color_range == partial.color_range == "limited"
    np.testing.assert_array_equal(partial.y, full.y[2:7])
    np.testing.assert_array_equal(partial.u, full.u[2:7])
    np.testing.assert_array_equal(partial.v, full.v[2:7])
    assert partial.timestamps_ns.tolist() == [
        80_000_000,
        120_000_000,
        160_000_000,
        200_000_000,
        240_000_000,
    ]


@pytest.mark.parametrize(
    "profile", ["vp8-temporal", "vp9-temporal", "av1-temporal"]
)
def test_public_temporal_profiles_stream_and_own_decoded_planes(
    tmp_path, profile
):
    path = tmp_path / f"{profile}.webm"
    sequence = _temporal_sequence()
    expected = bytes(
        _core.write_webm_temporal(sequence, codec=profile[:3])
    )
    sceneio.write(sequence, path, format="webm", profile=profile)
    assert path.read_bytes() == expected
    inspection = sceneio.inspect(path)
    assert inspection.metadata["codec"] == profile[:3]
    assert inspection.metadata["profile"] == "temporal"
    assert inspection.metadata["storage_mode"] == "yuv_planar"
    assert [array.name for array in inspection.arrays] == ["y", "u", "v"]

    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        decoded = _core.read_webm(mapped)
        snapshot = tuple(
            np.array(plane, copy=True)
            for plane in (decoded.y, decoded.u, decoded.v)
        )
        mapped.close()
    gc.collect()
    for actual, expected in zip(
        (decoded.y, decoded.u, decoded.v), snapshot, strict=True
    ):
        np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize("codec", ["vp8", "vp9", "av1"])
def test_temporal_worker_modes_are_repeatable_and_decode_same_timeline(codec):
    sequence = _temporal_sequence(frames=10, height=48, width=64)
    one = bytes(_core.write_webm_temporal(sequence, codec=codec, threads=1))
    one_repeat = bytes(
        _core.write_webm_temporal(sequence, codec=codec, threads=1)
    )
    many = bytes(_core.write_webm_temporal(sequence, codec=codec, threads=4))
    many_repeat = bytes(
        _core.write_webm_temporal(sequence, codec=codec, threads=4)
    )
    assert one == one_repeat
    assert many == many_repeat
    one_decoded = _core.read_webm(one)
    many_decoded = _core.read_webm(many)
    assert one_decoded.timestamps_ns.tolist() == many_decoded.timestamps_ns.tolist()
    assert one_decoded.durations_ns.tolist() == many_decoded.durations_ns.tolist()
    for first, second in zip(
        (one_decoded.y, one_decoded.u, one_decoded.v),
        (many_decoded.y, many_decoded.u, many_decoded.v),
        strict=True,
    ):
        difference = np.abs(
            np.asarray(first, dtype=np.int16)
            - np.asarray(second, dtype=np.int16)
        )
        assert float(difference.mean()) < 1.0
        assert int(difference.max()) <= 16


def test_temporal_writer_refuses_unrepresented_options():
    sequence = _temporal_sequence()
    with pytest.raises(ValueError, match="codec"):
        _core.write_webm_temporal(sequence, codec="vp10")
    with pytest.raises(ValueError, match="threads"):
        _core.write_webm_temporal(sequence, threads=9)
    with pytest.raises(ValueError, match="keyframe_interval"):
        _core.write_webm_temporal(sequence, keyframe_interval=1)

    bt709_full = _core.image_sequence_yuv(
        sequence.y,
        sequence.u,
        sequence.v,
        sequence.timestamps_ns,
        sequence.durations_ns,
        "420",
        "unspecified",
        "full",
        "bt709",
        "progressive",
        25,
        1,
        1,
        1,
    )
    vp9 = bytes(_core.write_webm_temporal(bt709_full, codec="vp9", threads=1))
    _, matrix, color_range, _, _ = _oracle_temporal_profile(vp9)
    assert (matrix, color_range) == (1, 2)
    decoded = _core.read_webm(vp9)
    assert (decoded.matrix, decoded.color_range) == ("bt709", "full")
    with pytest.raises(ValueError, match="bt601"):
        _core.write_webm_temporal(bt709_full, codec="vp8")

    with pytest.raises(sceneio.FormatError, match="unknown profile"):
        sceneio.write(
            sequence,
            "unused.webm",
            format="webm",
            profile="vp10-temporal",
        )


@pytest.mark.parametrize("codec", ["vp8", "vp9", "av1"])
def test_temporal_rgb_conversion_preserves_input_and_exact_timing(codec):
    frames = _frames()
    snapshot = frames.copy()
    sequence = _sequence(frames)
    encoded = _core.write_webm_temporal(sequence, codec=codec, threads=1)
    np.testing.assert_array_equal(frames, snapshot)
    np.testing.assert_array_equal(sequence.pixels, snapshot)
    decoded = _core.read_webm(encoded)
    assert decoded.storage_mode == "yuv_planar"
    assert decoded.matrix == "bt601"
    assert decoded.color_range == "limited"
    assert decoded.timestamps_ns.tolist() == [0, 40_000_000, 110_000_000]
    assert decoded.durations_ns.tolist() == [
        40_000_000,
        70_000_000,
        30_000_000,
    ]
    *_, references = _oracle_temporal_profile(bytes(encoded))
    assert references == (None, -40, -70)
    malformed_reference = _replace_first_reference(bytes(encoded), -1)
    for function in (_core.read_webm, _core._inspect_webm):
        with pytest.raises(ValueError, match="earlier frame"):
            function(malformed_reference)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frames, timestamps, durations: frames[..., :1], "RGB"),
        (
            lambda frames, timestamps, durations: np.concatenate(
                (frames, np.full((*frames.shape[:-1], 1), 255, np.uint8)),
                axis=-1,
            ),
            "RGB",
        ),
    ],
)
def test_writer_refuses_unrepresented_pixel_layouts(mutation, message):
    frames = _frames()
    changed = mutation(frames, None, None)
    alpha = "straight" if changed.shape[-1] == 4 else "none"
    durations = np.array([40, 70, 30], np.int64) * 1_000_000
    timestamps = np.array([0, 40, 110], np.int64) * 1_000_000
    sequence = _core.image_sequence_packed(
        changed,
        timestamps,
        durations,
        "srgb" if changed.shape[-1] != 1 else "gray",
        alpha,
        None,
        None,
        None,
    )
    with pytest.raises(ValueError, match=message):
        _core.write_webm(sequence)


@pytest.mark.parametrize(
    ("timestamps", "durations", "message"),
    [
        ([1, 41, 111], [40, 70, 30], "start at zero"),
        ([0, 41, 111], [40, 70, 30], "contiguous"),
        ([0, 40, 110], [40, 70, 30.5], "milliseconds"),
    ],
)
def test_writer_refuses_unrepresentable_timing(
    timestamps,
    durations,
    message,
):
    timestamps_ns = np.asarray(timestamps, np.float64) * 1_000_000
    durations_ns = np.asarray(durations, np.float64) * 1_000_000
    sequence = _core.image_sequence_packed(
        _frames(),
        timestamps_ns.astype(np.int64),
        durations_ns.astype(np.int64),
        "srgb",
        "none",
        None,
        None,
        None,
    )
    with pytest.raises(ValueError, match=message):
        _core.write_webm(sequence)


def test_truncated_wrong_codec_and_interframe_inputs_are_rejected():
    encoded = _core.write_webm(_sequence(_frames()))
    _, _, packets = _oracle_demux(encoded)
    first_packet = packets[0][2]
    packet_offset = encoded.index(first_packet)

    wrong_codec = encoded.replace(b"V_VP8", b"V_VP9", 1)
    interframe = bytearray(encoded)
    interframe[packet_offset] |= 1
    cases = (
        b"",
        b"\x1a\x45\xdf\xa3",
        encoded[:-1],
        wrong_codec,
        bytes(interframe),
    )
    for payload in cases:
        with pytest.raises(ValueError):
            _core.read_webm(payload)
        with pytest.raises(ValueError):
            _core._inspect_webm(payload)


def test_reader_refuses_noncontiguous_blockgroup_timing():
    encoded = _core.write_webm(_sequence(_frames()))
    malformed = _replace_first_block_duration(encoded, 39)
    for function in (_core.read_webm, _core._inspect_webm):
        with pytest.raises(ValueError, match="contiguous"):
            function(malformed)


def test_partial_bounds_reject(tmp_path):
    path = Path(tmp_path) / "bounds.webm"
    path.write_bytes(_core.write_webm(_sequence(_frames())))
    for bounds in ((0, 0), (2, 2), (2, 4), (4, 5)):
        with pytest.raises(sceneio.FormatError):
            sceneio.read_partial(path, format="webm", frames=bounds)
