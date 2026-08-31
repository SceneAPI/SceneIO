"""Independent parity and fast-path tests for the raw YUV4MPEG2 tier."""

from __future__ import annotations

import gc
import mmap
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core

_LAYOUTS = {
    "mono": ("mono", "none", 1, 1),
    "420jpeg": ("420", "jpeg", 2, 2),
    "420mpeg2": ("420", "mpeg2", 2, 2),
    "420paldv": ("420", "paldv", 2, 2),
    "422": ("422", "unspecified", 2, 1),
    "444": ("444", "unspecified", 1, 1),
}
_XYSCSS = {
    "420jpeg": "420JPEG",
    "420mpeg2": "420MPEG2",
    "420paldv": "420PALDV",
    "422": "422",
    "444": "444",
}


def _empty_timing() -> np.ndarray:
    return np.empty(0, np.int64)


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
    return (
        np.asarray(timestamps, np.int64),
        np.asarray(durations, np.int64),
    )


def oracle_write(
    y: np.ndarray,
    u: np.ndarray | None,
    v: np.ndarray | None,
    *,
    chroma: str,
    rate: tuple[int, int] = (30_000, 1_001),
    aspect: tuple[int, int] = (1, 1),
    interlace: str = "p",
    color_range: str = "FULL",
    matrix: str = "BT709",
) -> bytes:
    """Small independent serializer for SceneIO's documented Y4M subset."""

    y = np.asarray(y, np.uint8)
    frames, height, width = y.shape
    fields = [
        "YUV4MPEG2",
        f"W{width}",
        f"H{height}",
        f"F{rate[0]}:{rate[1]}",
        f"I{interlace}",
        f"A{aspect[0]}:{aspect[1]}",
        f"C{chroma}",
    ]
    if chroma != "mono":
        fields.append(f"XYSCSS={_XYSCSS[chroma]}")
    if color_range:
        fields.append(f"XCOLORRANGE={color_range}")
    if matrix:
        fields.append(f"XCOLORSPACE={matrix}")
    output = bytearray((" ".join(fields) + "\n").encode("ascii"))
    for index in range(frames):
        output += b"FRAME\n"
        output += y[index].tobytes()
        if chroma != "mono":
            assert u is not None and v is not None
            output += np.asarray(u[index], np.uint8).tobytes()
            output += np.asarray(v[index], np.uint8).tobytes()
    return bytes(output)


def oracle_read(data: bytes):
    """Parse valid subset fixtures independently from the compiled parser."""

    line, payload = data.split(b"\n", 1)
    fields = line.decode("ascii").split(" ")
    assert fields.pop(0) == "YUV4MPEG2"
    values = {field[0]: field[1:] for field in fields if not field.startswith("X")}
    extensions = {
        field.split("=", 1)[0]: field.split("=", 1)[1]
        for field in fields
        if field.startswith("X")
    }
    width = int(values["W"])
    height = int(values["H"])
    chroma = values["C"]
    subsampling, siting, horizontal, vertical = _LAYOUTS[chroma]
    chroma_width = 0 if chroma == "mono" else (width + horizontal - 1) // horizontal
    chroma_height = (
        0 if chroma == "mono" else (height + vertical - 1) // vertical
    )
    y_bytes = height * width
    chroma_bytes = chroma_height * chroma_width
    frame_bytes = y_bytes + 2 * chroma_bytes
    y_planes = []
    u_planes = []
    v_planes = []
    while payload:
        assert payload.startswith(b"FRAME\n")
        frame = payload[6 : 6 + frame_bytes]
        assert len(frame) == frame_bytes
        payload = payload[6 + frame_bytes :]
        y_planes.append(
            np.frombuffer(frame[:y_bytes], np.uint8).reshape(height, width)
        )
        if chroma_bytes:
            u_planes.append(
                np.frombuffer(
                    frame[y_bytes : y_bytes + chroma_bytes], np.uint8
                ).reshape(chroma_height, chroma_width)
            )
            v_planes.append(
                np.frombuffer(frame[y_bytes + chroma_bytes :], np.uint8).reshape(
                    chroma_height, chroma_width
                )
            )
    return {
        "y": np.asarray(y_planes, np.uint8).reshape(-1, height, width),
        "u": (
            np.asarray(u_planes, np.uint8).reshape(
                -1, chroma_height, chroma_width
            )
            if chroma_bytes
            else np.empty((len(y_planes), 0, 0), np.uint8)
        ),
        "v": (
            np.asarray(v_planes, np.uint8).reshape(
                -1, chroma_height, chroma_width
            )
            if chroma_bytes
            else np.empty((len(y_planes), 0, 0), np.uint8)
        ),
        "subsampling": subsampling,
        "siting": siting,
        "rate": tuple(map(int, values["F"].split(":"))),
        "aspect": tuple(map(int, values["A"].split(":"))),
        "range": extensions.get("XCOLORRANGE", "unknown").lower(),
        "matrix": extensions.get("XCOLORSPACE", "unknown").lower(),
    }


def _planes(chroma: str, frames: int = 3, height: int = 5, width: int = 7):
    _subsampling, _siting, horizontal, vertical = _LAYOUTS[chroma]
    y = np.arange(frames * height * width, dtype=np.uint8).reshape(
        frames, height, width
    )
    if chroma == "mono":
        return y, None, None
    chroma_shape = (
        frames,
        (height + vertical - 1) // vertical,
        (width + horizontal - 1) // horizontal,
    )
    count = int(np.prod(chroma_shape))
    u = (np.arange(count, dtype=np.uint8) + 61).reshape(chroma_shape)
    v = (np.arange(count, dtype=np.uint8) + 137).reshape(chroma_shape)
    return y, u, v


def _record(
    y: np.ndarray,
    u: np.ndarray | None,
    v: np.ndarray | None,
    *,
    chroma: str,
    timing: bool = False,
    siting: str | None = None,
):
    subsampling, default_siting, _horizontal, _vertical = _LAYOUTS[chroma]
    timestamps, durations = (
        _timing(y.shape[0], 30_000, 1_001)
        if timing
        else (_empty_timing(), _empty_timing())
    )
    return _core.image_sequence_yuv(
        y,
        u,
        v,
        timestamps,
        durations,
        subsampling,
        default_siting if siting is None else siting,
        "full",
        "bt709",
        "progressive",
        30_000,
        1_001,
        1,
        1,
    )


def _assert_sequence(actual, expected, chroma: str):
    assert isinstance(actual, _core.ImageSequence)
    assert actual.storage_mode == "yuv_planar"
    assert actual.num_frames == expected["y"].shape[0]
    assert actual.y.tobytes() == expected["y"].tobytes()
    assert actual.u.tobytes() == expected["u"].tobytes()
    assert actual.v.tobytes() == expected["v"].tobytes()
    assert actual.chroma_subsampling == expected["subsampling"]
    assert actual.chroma_siting == expected["siting"]
    assert (
        actual.frame_rate_numerator,
        actual.frame_rate_denominator,
    ) == expected["rate"]
    assert (
        actual.pixel_aspect_numerator,
        actual.pixel_aspect_denominator,
    ) == expected["aspect"]
    assert actual.color_range == expected["range"]
    assert actual.matrix == expected["matrix"]
    assert actual.channels == (1 if chroma == "mono" else 3)


def test_exact_monochrome_golden_bytes():
    y = np.array([[[0, 1], [2, 255]]], np.uint8)
    sequence = _core.image_sequence_yuv(
        y,
        None,
        None,
        _empty_timing(),
        _empty_timing(),
        "mono",
        "none",
        "unknown",
        "unknown",
        "progressive",
        25,
        1,
        1,
        1,
    )
    expected = (
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 Cmono\n"
        b"FRAME\n\x00\x01\x02\xff"
    )
    assert bytes(_core.write_y4m(sequence)) == expected
    decoded = _core.read_y4m(expected)
    assert decoded.y.tobytes() == y.tobytes()
    assert decoded.timestamps_ns.tolist() == [0]
    assert decoded.durations_ns.tolist() == [40_000_000]


@pytest.mark.parametrize("chroma", tuple(_LAYOUTS))
def test_independent_oracle_bidirectional_parity_for_every_layout(chroma):
    y, u, v = _planes(chroma)
    expected_bytes = oracle_write(y, u, v, chroma=chroma)
    _assert_sequence(_core.read_y4m(expected_bytes), oracle_read(expected_bytes), chroma)

    actual_bytes = bytes(_core.write_y4m(_record(y, u, v, chroma=chroma)))
    assert actual_bytes == expected_bytes
    parsed = oracle_read(actual_bytes)
    assert parsed["y"].tobytes() == y.tobytes()
    if u is not None and v is not None:
        assert parsed["u"].tobytes() == u.tobytes()
        assert parsed["v"].tobytes() == v.tobytes()


def test_rational_timing_recurrence_is_exact_and_partial_keeps_global_time():
    y, u, v = _planes("420jpeg", frames=5)
    data = oracle_write(y, u, v, chroma="420jpeg")
    expected_timestamps, expected_durations = _timing(5, 30_000, 1_001)
    full = _core.read_y4m(data)
    assert full.timestamps_ns.tolist() == expected_timestamps.tolist()
    assert full.durations_ns.tolist() == expected_durations.tolist()

    selected = _core.read_y4m_frames(data, 1, 4)
    assert selected.y.tobytes() == y[1:4].tobytes()
    assert selected.u.tobytes() == u[1:4].tobytes()
    assert selected.v.tobytes() == v[1:4].tobytes()
    assert selected.timestamps_ns.tolist() == expected_timestamps[1:4].tolist()
    assert selected.durations_ns.tolist() == expected_durations[1:4].tolist()


def test_public_detect_read_write_inspect_and_partial(tmp_path):
    y, u, v = _planes("422")
    source = tmp_path / "source.y4m"
    source.write_bytes(oracle_write(y, u, v, chroma="422"))

    assert sceneio.detect(source) == "y4m"
    _assert_sequence(sceneio.read(source), oracle_read(source.read_bytes()), "422")
    info = sceneio.inspect(source)
    assert info.format == "y4m"
    assert info.payload_kind == "image_sequence"
    assert info.shape == (3, 5, 7, 3)
    assert info.dtype == "uint8"
    assert info.count == 3
    assert info.channels == 3
    assert [(item.name, item.shape) for item in info.arrays] == [
        ("y", (3, 5, 7)),
        ("u", (3, 5, 4)),
        ("v", (3, 5, 4)),
    ]
    assert info.metadata["chroma_subsampling"] == "422"
    assert info.metadata["frame_rate_numerator"] == 30_000
    assert info.metadata["frame_bytes"] == 75

    selected = sceneio.read_partial(source, frames=(1, 3))
    assert selected.y.tobytes() == y[1:3].tobytes()
    assert selected.u.tobytes() == u[1:3].tobytes()

    output = tmp_path / "output.y4m"
    sceneio.write(_record(y, u, v, chroma="422"), output)
    assert output.read_bytes() == source.read_bytes()


def test_bytes_memoryview_and_mmap_are_bit_exact_and_mapping_can_close(tmp_path):
    y, u, v = _planes("444")
    data = oracle_write(y, u, v, chroma="444")
    expected = _core.read_y4m(data)
    parsed = oracle_read(data)
    expected_info = {
        "width": parsed["y"].shape[2],
        "height": parsed["y"].shape[1],
        "frames": parsed["y"].shape[0],
        "channels": 3,
        "chroma_width": parsed["u"].shape[2],
        "chroma_height": parsed["u"].shape[1],
        "chroma_subsampling": parsed["subsampling"],
        "chroma_siting": parsed["siting"],
        "color_range": parsed["range"],
        "matrix": parsed["matrix"],
        "interlace": "progressive",
        "frame_rate_numerator": parsed["rate"][0],
        "frame_rate_denominator": parsed["rate"][1],
        "pixel_aspect_numerator": parsed["aspect"][0],
        "pixel_aspect_denominator": parsed["aspect"][1],
        "frame_bytes": y[0].nbytes + u[0].nbytes + v[0].nbytes,
    }
    assert dict(_core._inspect_y4m(data)) == expected_info
    viewed = _core.read_y4m(memoryview(data))
    assert viewed.y.tobytes() == expected.y.tobytes()
    assert viewed.u.tobytes() == expected.u.tobytes()
    assert dict(_core._inspect_y4m(memoryview(data))) == expected_info
    array = np.frombuffer(data, dtype=np.uint8)
    assert not array.flags.writeable
    assert dict(_core._inspect_y4m(array)) == expected_info

    path = tmp_path / "mapped.y4m"
    path.write_bytes(data)
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        decoded = _core.read_y4m(mapped)
        assert dict(_core._inspect_y4m(mapped)) == expected_info
        mapped.close()
    gc.collect()
    assert decoded.y.tobytes() == y.tobytes()
    assert decoded.v.tobytes() == v.tobytes()


def test_crlf_headers_are_accepted_without_changing_payload():
    y = np.arange(6, dtype=np.uint8).reshape(1, 2, 3)
    data = (
        b"YUV4MPEG2 W3 H2 F25:1 Ip A0:0 Cmono\r\n"
        b"FRAME\r\n"
        + y.tobytes()
    )
    decoded = _core.read_y4m(data)
    assert decoded.y.tobytes() == y.tobytes()


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"NOTY4M W2 H2 F25:1 Ip A1:1 Cmono\n",
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1\n",
        b"YUV4MPEG2 W2 W2 H2 F25:1 Ip A1:1 Cmono\n",
        b"YUV4MPEG2 W0 H2 F25:1 Ip A1:1 Cmono\n",
        b"YUV4MPEG2 W2 H2 F0:1 Ip A1:1 Cmono\n",
        b"YUV4MPEG2 W2 H2 F25:0 Ip A1:1 Cmono\n",
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:0 Cmono\n",
        b"YUV4MPEG2 W2 H2 F25:1 Im A1:1 Cmono\n",
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 C420\n",
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 Cmono XUNKNOWN=1\n",
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 Cmono XYSCSS=\n",
        (
            b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 C420jpeg "
            b"XYSCSS=420JPEG XYSCSS=420JPEG\n"
        ),
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 C420jpeg XYSCSS=422\n",
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 Cmono\nFRAME X=1\n",
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 Cmono\nFRAME\n\0\0\0",
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 Cmono\nFRAME\n\0\0\0\0x",
        b"YUV4MPEG2 W2 H2 F4294967295:1 Ip A1:1 Cmono\n",
    ],
)
def test_malformed_and_unrepresented_inputs_match_read_and_inspect(data):
    for function in (_core.read_y4m, _core._inspect_y4m):
        with pytest.raises(ValueError):
            function(data)


@pytest.mark.parametrize(
    "bounds",
    [(-1, 1), (0, 0), (2, 1), (0, 4), (3, 4)],
)
def test_partial_bounds_reject(bounds):
    y, u, v = _planes("420jpeg")
    data = oracle_write(y, u, v, chroma="420jpeg")
    with pytest.raises((TypeError, ValueError)):
        _core.read_y4m_frames(data, *bounds)


def test_writer_guards_unrepresentable_record_metadata():
    paths = _core.image_sequence_paths(
        ["frame.png"],
        ["frame.png"],
        _empty_timing(),
        _empty_timing(),
        2,
        2,
        3,
    )
    with pytest.raises(ValueError, match="planar"):
        _core.write_y4m(paths)

    y, u, v = _planes("420jpeg", frames=2)
    with pytest.raises(ValueError, match="positive frame rate"):
        _core.write_y4m(
            _core.image_sequence_yuv(
                y,
                u,
                v,
                _empty_timing(),
                _empty_timing(),
                "420",
                "jpeg",
                "full",
                "bt709",
                "progressive",
                0,
                1,
                1,
                1,
            )
        )
    with pytest.raises(ValueError, match="timing disagrees"):
        _core.write_y4m(
            _core.image_sequence_yuv(
                y,
                u,
                v,
                np.array([0, 1], np.int64),
                np.array([1, 1], np.int64),
                "420",
                "jpeg",
                "full",
                "bt709",
                "progressive",
                25,
                1,
                1,
                1,
            )
        )

    y422, u422, v422 = _planes("422")
    with pytest.raises(ValueError, match="requires unspecified"):
        _core.write_y4m(
            _record(y422, u422, v422, chroma="422", siting="jpeg")
        )


def test_file_sink_is_byte_identical_with_short_writes(tmp_path):
    y, u, v = _planes("420paldv", frames=9, height=11, width=13)
    sequence = _record(y, u, v, chroma="420paldv", timing=True)
    expected = bytes(_core.write_y4m(sequence))
    path = tmp_path / "sink.y4m"
    calls = _core._write_to_file(
        _core.write_y4m,
        sequence,
        path,
        _max_chunk=37,
        _test_short_write=11,
    )
    assert calls > sequence.num_frames
    assert path.read_bytes() == expected


def test_large_inspect_and_one_frame_partial_have_bounded_python_memory(tmp_path):
    frames = 8_192
    height = width = 32
    path = tmp_path / "large.y4m"
    header = b"YUV4MPEG2 W32 H32 F25:1 Ip A1:1 Cmono\n"
    with path.open("wb") as stream:
        stream.write(header)
        frame = b"FRAME\n" + bytes(height * width)
        for _ in range(frames):
            stream.write(frame)
    assert path.stat().st_size > 8 * 1024 * 1024

    for operation in (
        lambda: sceneio.inspect(path),
        lambda: sceneio.read_partial(path, frames=(4_000, 4_001)),
    ):
        gc.collect()
        tracemalloc.start()
        try:
            result = operation()
            _current, peak = tracemalloc.get_traced_memory()
            del result
        finally:
            tracemalloc.stop()
        assert peak < 1024 * 1024


def test_extensionless_magic_detection(tmp_path):
    y, u, v = _planes("mono", frames=1)
    path = Path(tmp_path) / "sequence"
    path.write_bytes(oracle_write(y, u, v, chroma="mono"))
    assert sceneio.detect(path) == "y4m"
