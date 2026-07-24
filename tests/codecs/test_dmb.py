"""Independent parity, malformed-input, partial, memory, and sink tests for DMB."""

from __future__ import annotations

import gc
import mmap
import struct
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def oracle_write(values: np.ndarray) -> bytes:
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or min(values.shape) < 1:
        raise ValueError("expected non-empty HxW")
    height, width = values.shape
    return (
        struct.pack("<4i", 1, height, width, 1)
        + values.astype("<f4", copy=False).tobytes(order="C")
    )


def oracle_read(data: bytes) -> np.ndarray:
    if len(data) < 16:
        raise ValueError("truncated")
    image_type, height, width, channels = struct.unpack("<4i", data[:16])
    if image_type != 1 or height < 1 or width < 1 or channels != 1:
        raise ValueError("unsupported header")
    expected = 16 + height * width * 4
    if len(data) != expected:
        raise ValueError("payload size")
    return np.frombuffer(data, dtype="<f4", offset=16).reshape(height, width)


def _record(values):
    return _core.depth_map(
        np.asarray(values, np.float32),
        unit="unknown",
        invalid_policy="zero",
    )


def _assert_depth(record, expected):
    assert isinstance(record, _core.DepthMap)
    assert (record.height, record.width) == expected.shape
    assert record.unit == "unknown"
    assert record.scale_to_meters == 0.0
    assert record.invalid_policy == "zero"
    assert not record.has_confidence
    assert record.depth.dtype == np.dtype("float32")
    assert record.depth.tobytes() == np.asarray(expected, np.float32).tobytes()


def test_oracle_write_sceneio_read_bit_exact():
    values = np.array(
        [[0.0, -0.0, 1.5], [np.inf, -np.inf, np.nan]], np.float32
    )
    _assert_depth(_core.read_dmb(oracle_write(values)), values)


def test_sceneio_write_oracle_read_and_golden_bytes():
    values = np.array([[1.0, 2.5], [-3.0, 0.0]], np.float32)
    encoded = bytes(_core.write_dmb(_record(values)))
    assert encoded == oracle_write(values)
    assert encoded[:16] == struct.pack("<4i", 1, 2, 2, 1)
    assert oracle_read(encoded).tobytes() == values.tobytes()


def test_roundtrip_random_payload_bit_exact():
    rng = np.random.default_rng(20260724)
    values = rng.standard_normal((31, 47)).astype(np.float32)
    encoded = _core.write_dmb(_record(values))
    _assert_depth(_core.read_dmb(encoded), values)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "truncated header"),
        (b"\0" * 15, "truncated header"),
        (struct.pack("<4i", 2, 1, 1, 1) + b"\0" * 4, "type"),
        (struct.pack("<4i", 1, 0, 1, 1), "positive"),
        (struct.pack("<4i", 1, 1, -1, 1), "dimensions"),
        (struct.pack("<4i", 1, 1_000_001, 1, 1), "dimensions"),
        (struct.pack("<4i", 1, 1, 1, 3) + b"\0" * 12, "channels=1"),
        (struct.pack("<4i", 1, 20_000, 20_000, 1), "pixel count"),
        (struct.pack("<4i", 1, 2, 2, 1) + b"\0" * 15, "truncated"),
        (struct.pack("<4i", 1, 1, 1, 1) + b"\0" * 5, "trailing"),
    ],
)
def test_malformed_inputs_reject(data, message):
    for reader in (_core.read_dmb, _core._inspect_dmb):
        with pytest.raises(ValueError, match=message):
            reader(data)


def test_public_detect_read_write_inspect_and_window(tmp_path):
    values = np.arange(8 * 11, dtype=np.float32).reshape(8, 11)
    path = tmp_path / "depth.dmb"
    path.write_bytes(oracle_write(values))
    assert sceneio.detect(path) == "dmb"
    _assert_depth(sceneio.read(path), values)

    info = sceneio.inspect(path)
    assert info.format == "dmb"
    assert info.shape == values.shape
    assert info.dtype == "float32"
    assert info.count == values.size
    assert info.metadata == {
        "channels": 1,
        "image_type": 1,
        "unit": "unknown",
        "scale_to_meters": 0.0,
        "invalid_policy": "zero",
    }

    window = sceneio.read_partial(path, window=(2, 7, 3, 9))
    _assert_depth(window, values[2:7, 3:9])

    output = tmp_path / "copy.dmb"
    sceneio.write(_record(values), output)
    assert output.read_bytes() == oracle_write(values)


@pytest.mark.parametrize(
    "window",
    [
        (0, 0, 0, 1),
        (0, 1, 1, 1),
        (2, 1, 0, 1),
        (0, 1, 2, 1),
        (0, 9, 0, 1),
        (0, 1, 0, 12),
    ],
)
def test_window_bounds_reject_without_full_decode(tmp_path, window):
    values = np.arange(8 * 11, dtype=np.float32).reshape(8, 11)
    path = tmp_path / "depth.dmb"
    path.write_bytes(oracle_write(values))
    with pytest.raises(sceneio.FormatError, match="range"):
        sceneio.read_partial(path, window=window)


def test_mmap_equals_bytes_and_decode_releases_mapping(tmp_path):
    values = np.arange(63, dtype=np.float32).reshape(7, 9)
    data = oracle_write(values)
    path = tmp_path / "mapped.dmb"
    path.write_bytes(data)
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        actual = _core.read_dmb(mapped)
        mapped.close()
    _assert_depth(actual, values)


def test_sparse_large_inspect_and_window_have_bounded_traced_memory(tmp_path):
    height = width = 4096
    path = tmp_path / "large.dmb"
    with path.open("wb") as stream:
        stream.write(struct.pack("<4i", 1, height, width, 1))
        stream.truncate(16 + height * width * 4)

    for operation in (
        lambda: sceneio.inspect(path),
        lambda: sceneio.read_partial(path, window=(2000, 2008, 3000, 3008)),
    ):
        gc.collect()
        tracemalloc.start()
        try:
            result = operation()
            _, peak = tracemalloc.get_traced_memory()
            del result
        finally:
            tracemalloc.stop()
        assert peak < 1024 * 1024


def test_writer_guards_unrepresentable_metadata_and_confidence():
    values = np.ones((3, 4), np.float32)
    with pytest.raises(ValueError, match="unit/scale"):
        _core.write_dmb(_core.depth_map(values))
    with pytest.raises(ValueError, match="invalid_policy"):
        _core.write_dmb(
            _core.depth_map(values, unit="unknown", invalid_policy="none")
        )
    with pytest.raises(ValueError, match="confidence"):
        _core.write_dmb(
            _core.depth_map(
                values,
                confidence=np.ones_like(values),
                unit="unknown",
                invalid_policy="zero",
            )
        )


def test_file_sink_is_byte_identical_with_short_writes(tmp_path):
    values = np.arange(120, dtype=np.float32).reshape(10, 12)
    record = _record(values)
    expected = bytes(_core.write_dmb(record))
    path = tmp_path / "sink.dmb"
    calls = _core._write_to_file(
        _core.write_dmb,
        record,
        path,
        _max_chunk=7,
        _test_short_write=3,
    )
    assert calls > 3
    assert path.read_bytes() == expected


def test_random_single_byte_mutations_match_independent_parser():
    values = np.arange(64, dtype=np.float32).reshape(8, 8)
    valid = oracle_write(values)
    rng = np.random.default_rng(193)

    def outcome(reader, data):
        try:
            value = reader(data)
        except Exception:
            return ("error",)
        if isinstance(value, _core.DepthMap):
            value = value.depth
        return ("ok", value.shape, value.dtype.str, value.tobytes())

    for _ in range(100):
        mutated = bytearray(valid)
        index = int(rng.integers(0, len(mutated)))
        mutated[index] ^= int(rng.integers(1, 256))
        data = bytes(mutated)
        assert outcome(_core.read_dmb, data) == outcome(oracle_read, data)
