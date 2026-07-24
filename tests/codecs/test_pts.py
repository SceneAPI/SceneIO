"""Independent parity, bounded-read, malformed-input, and sink tests for PTS."""

from __future__ import annotations

import gc
import mmap
import re
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _fmt(value: float) -> str:
    value = float(value)
    if np.isnan(value):
        return "-nan" if np.signbit(value) else "nan"
    if np.isposinf(value):
        return "inf"
    if np.isneginf(value):
        return "-inf"
    return format(value, ".17g")


def oracle_write(
    xyz: np.ndarray,
    *,
    intensity: np.ndarray | None = None,
    rgb: np.ndarray | None = None,
) -> bytes:
    xyz = np.asarray(xyz, dtype=np.float32)
    rows = [str(len(xyz))]
    for index, position in enumerate(xyz):
        fields = [_fmt(value) for value in position]
        if intensity is not None:
            fields.append(_fmt(np.asarray(intensity, np.float32)[index]))
        if rgb is not None:
            fields.extend(
                str(int(value)) for value in np.asarray(rgb, np.uint8)[index]
            )
        rows.append(" ".join(fields))
    return ("\n".join(rows) + "\n").encode()


def oracle_read(data: bytes) -> dict[str, np.ndarray | None]:
    lines = []
    for raw in data.split(b"\n"):
        stripped = raw.strip(b" \t\r")
        if stripped and not stripped.startswith(b"#"):
            lines.append(stripped.decode("ascii"))
    if not lines or not lines[0].isdigit():
        raise ValueError("missing or invalid count")
    declared = int(lines[0])
    rows = [re.split(r"[ \t,\r]+", line) for line in lines[1:]]
    if len(rows) != declared:
        raise ValueError("count mismatch")
    if not rows:
        return {
            "xyz": np.empty((0, 3), np.float32),
            "intensity": None,
            "rgb": None,
        }
    columns = len(rows[0])
    if columns not in {3, 4, 6, 7}:
        raise ValueError("unsupported columns")
    if any(len(row) != columns for row in rows):
        raise ValueError("inconsistent columns")
    values = np.asarray([[float(value) for value in row] for row in rows])
    rgb_start = 4 if columns == 7 else 3
    rgb = None
    if columns in {6, 7}:
        colors = values[:, rgb_start : rgb_start + 3]
        if (
            not np.isfinite(colors).all()
            or (colors != np.floor(colors)).any()
            or (colors < 0).any()
            or (colors > 255).any()
        ):
            raise ValueError("invalid rgb")
        rgb = colors.astype(np.uint8)
    return {
        "xyz": values[:, :3].astype(np.float32),
        "intensity": (
            values[:, 3].astype(np.float32)
            if columns in {4, 7}
            else None
        ),
        "rgb": rgb,
    }


def _assert_record(record, expected):
    np.testing.assert_array_equal(record.positions, expected["xyz"])
    assert record.has_intensity == (expected["intensity"] is not None)
    assert record.has_rgb == (expected["rgb"] is not None)
    if expected["intensity"] is not None:
        np.testing.assert_array_equal(
            record.intensities, expected["intensity"]
        )
    if expected["rgb"] is not None:
        np.testing.assert_array_equal(record.colors, expected["rgb"])


@pytest.fixture
def arrays():
    rng = np.random.default_rng(20260724)
    return {
        "xyz": rng.standard_normal((17, 3)).astype(np.float32),
        "intensity": rng.standard_normal(17).astype(np.float32),
        "rgb": rng.integers(0, 256, (17, 3), dtype=np.uint8),
    }


@pytest.mark.parametrize(
    ("with_intensity", "with_rgb"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_oracle_write_sceneio_read_supported_layouts(
    arrays, with_intensity, with_rgb
):
    data = oracle_write(
        arrays["xyz"],
        intensity=arrays["intensity"] if with_intensity else None,
        rgb=arrays["rgb"] if with_rgb else None,
    )
    _assert_record(_core.read_pts(data), oracle_read(data))


@pytest.mark.parametrize(
    ("with_intensity", "with_rgb"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_sceneio_write_oracle_read_supported_layouts(
    arrays, with_intensity, with_rgb
):
    record = _core.point_cloud(
        arrays["xyz"],
        intensity=arrays["intensity"] if with_intensity else None,
        colors=arrays["rgb"] if with_rgb else None,
    )
    encoded = bytes(_core.write_pts(record))
    assert encoded == oracle_write(
        arrays["xyz"],
        intensity=arrays["intensity"] if with_intensity else None,
        rgb=arrays["rgb"] if with_rgb else None,
    )
    _assert_record(
        _core.read_pts(encoded),
        oracle_read(encoded),
    )


def test_writer_is_canonical_and_empty_is_count_only():
    record = _core.point_cloud(
        np.array([[1.5, -2.25, 300]], np.float32),
        intensity=np.array([7.5], np.float32),
        colors=np.array([[10, 20, 30]], np.uint8),
    )
    assert _core.write_pts(record) == (
        b"1\n1.5 -2.25 300 7.5 10 20 30\n"
    )
    empty = _core.point_cloud(np.empty((0, 3), np.float32))
    assert _core.write_pts(empty) == b"0\n"
    assert _core.read_pts(b"0\n").num_points == 0


def test_comments_blank_lines_commas_crlf_and_no_final_newline():
    data = b"# exported\n\n2\r\n1,2,3,4,10,20,30\r\n4 5 6 7 40 50 60"
    record = _core.read_pts(data)
    assert record.num_points == 2
    np.testing.assert_array_equal(record.intensities, [4, 7])
    np.testing.assert_array_equal(
        record.colors, [[10, 20, 30], [40, 50, 60]]
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "missing"),
        (b"# only a comment\n", "missing"),
        (b"-1\n", "unsigned"),
        (b"1.0\n", "unsigned"),
        (b"1,\n1 2 3\n", "unsigned"),
        (b"1 2\n", "exactly one"),
        (b"2\n1 2 3\n", "does not match"),
        (b"1\n1 2 3\n4 5 6\n", "does not match"),
        (b"1\n1 2\n", "unsupported column"),
        (b"2\n1 2 3\n4 5 6 7\n", "expected 3"),
        (b"1\n1 2 3 4 5 6 7 8 9\n", "9-column"),
        (b"1\n1 2 3 4 5.5 6\n", "integers"),
        (b"1\n1 2 3 4 5 999\n", "0..255"),
    ],
)
def test_malformed_inputs_reject(data, message):
    with pytest.raises(ValueError, match=message):
        _core.read_pts(data)


def test_public_detect_read_write_inspect_and_partial(tmp_path, arrays):
    path = tmp_path / "cloud.pts"
    path.write_bytes(
        oracle_write(
            arrays["xyz"],
            intensity=arrays["intensity"],
            rgb=arrays["rgb"],
        )
    )
    assert sceneio.detect(path) == "pts"
    full = sceneio.read(path)
    _assert_record(full, arrays)
    info = sceneio.inspect(path)
    assert info.format == "pts"
    assert info.shape == (17, 3)
    assert info.count == info.metadata["declared_count"] == 17

    partial = sceneio.read_partial(path, points=(3, 9))
    _assert_record(
        partial,
        {
            "xyz": arrays["xyz"][3:9],
            "intensity": arrays["intensity"][3:9],
            "rgb": arrays["rgb"][3:9],
        },
    )

    output = tmp_path / "copy.pts"
    sceneio.write(full, output)
    _assert_record(sceneio.read(output), arrays)


def test_mmap_equals_bytes_and_decode_releases_mapping(tmp_path, arrays):
    data = oracle_write(arrays["xyz"], rgb=arrays["rgb"])
    expected = _core.read_pts(data)
    path = tmp_path / "mapped.pts"
    path.write_bytes(data)
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        actual = _core.read_pts(mapped)
        mapped.close()
    _assert_record(
        actual,
        {"xyz": expected.positions, "intensity": None, "rgb": expected.colors},
    )


def test_partial_read_has_bounded_traced_memory(tmp_path):
    count = 150_000
    path = tmp_path / "large.pts"
    row = b"1 2 3 4 5 6 7\n"
    path.write_bytes(str(count).encode() + b"\n" + row * count)
    gc.collect()
    tracemalloc.start()
    try:
        partial = sceneio.read_partial(
            path, format="pts", points=(count - 3, count)
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert partial.num_points == 3
    assert peak < 2 * 1024 * 1024


def test_writer_guards_unrepresentable_fields(arrays):
    with pytest.raises(ValueError, match="normals"):
        _core.write_pts(
            _core.point_cloud(
                arrays["xyz"],
                normals=np.zeros_like(arrays["xyz"]),
            )
        )
    with pytest.raises(ValueError, match="16-bit"):
        _core.write_pts(
            _core.point_cloud(
                arrays["xyz"],
                colors16=np.zeros((17, 3), np.uint16),
            )
        )
    with pytest.raises(ValueError, match="coordinate frame"):
        _core.write_pts(
            _core.point_cloud(arrays["xyz"], coordinate_frame="enu")
        )
    with pytest.raises(ValueError, match="intensity range"):
        _core.write_pts(
            _core.point_cloud(
                arrays["xyz"],
                intensity_range="u16",
            )
        )


def test_file_sink_is_byte_identical_with_short_writes(tmp_path, arrays):
    record = _core.point_cloud(
        arrays["xyz"], intensity=arrays["intensity"], colors=arrays["rgb"]
    )
    expected = bytes(_core.write_pts(record))
    path = tmp_path / "sink.pts"
    calls = _core._write_to_file(
        _core.write_pts,
        record,
        path,
        _max_chunk=5,
        _test_short_write=2,
    )
    assert calls > 3
    assert path.read_bytes() == expected


def test_parallel_writer_is_byte_identical(arrays):
    record = _core.point_cloud(
        arrays["xyz"], intensity=arrays["intensity"], colors=arrays["rgb"]
    )
    assert _core.write_pts(record, _lanes=1) == _core.write_pts(
        record, _lanes=8
    )


def test_random_single_byte_mutations_match_independent_parser(arrays):
    valid = oracle_write(
        arrays["xyz"], intensity=arrays["intensity"], rgb=arrays["rgb"]
    )
    rng = np.random.default_rng(9107)

    def outcome(reader, data):
        try:
            value = reader(data)
        except Exception:
            return ("error",)
        if isinstance(value, _core.PointCloud):
            return (
                "ok",
                value.positions.tobytes(),
                value.intensities.tobytes(),
                value.colors.tobytes(),
            )
        return (
            "ok",
            value["xyz"].tobytes(),
            value["intensity"].tobytes(),
            value["rgb"].tobytes(),
        )

    for _ in range(100):
        mutated = bytearray(valid)
        index = int(rng.integers(0, len(mutated)))
        mutated[index] ^= int(rng.integers(1, 128))
        data = bytes(mutated)
        assert outcome(_core.read_pts, data) == outcome(oracle_read, data)
