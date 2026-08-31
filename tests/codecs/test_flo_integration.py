"""Public-path and streaming coverage for the canonical FLO codec."""

from __future__ import annotations

import gc
import mmap
import struct
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io._registry import adapters


def _values(height: int = 5, width: int = 7) -> np.ndarray:
    values = np.random.default_rng(height * 100 + width).standard_normal(
        (height, width, 2)
    ).astype(np.float32)
    bits = values.reshape(-1).view(np.uint32)
    if bits.size >= 8:
        bits[:8] = np.array(
            [
                0x00000000,
                0x80000000,
                0x7F800000,
                0xFF800000,
                0x7FC01234,
                0x7F800001,
                0x501502F9,
                0xD01502F9,
            ],
            np.uint32,
        )
    return values


def _oracle_write(values: np.ndarray) -> bytes:
    values = np.ascontiguousarray(values, dtype=np.float32)
    height, width, channels = values.shape
    assert channels == 2
    return (
        b"PIEH"
        + struct.pack("<ii", width, height)
        + values.astype("<f4", copy=False).tobytes()
    )


def _field(values: np.ndarray) -> _core.FlowField:
    return _core.flow_field(values)


def _assert_canonical(flow: _core.FlowField, expected: np.ndarray) -> None:
    assert isinstance(flow, _core.FlowField)
    assert flow.vectors.tobytes() == expected.tobytes()
    assert (
        flow.component_order,
        flow.u_axis,
        flow.v_axis,
        flow.row_order,
        flow.unit,
        flow.invalid_policy,
    ) == (
        "uv",
        "right",
        "down",
        "top_to_bottom",
        "pixels",
        "component_abs_gt_1e9",
    )


def test_public_read_write_inspect_and_partial_use_flow_field(tmp_path):
    expected = _values()
    path = tmp_path / "field.flo"

    sceneio.write(_field(expected), path)
    assert path.read_bytes() == _oracle_write(expected)
    _assert_canonical(sceneio.read(path), expected)

    window = (1, 5, 2, 7)
    partial = sceneio.read_partial(path, window=window)
    _assert_canonical(partial, expected[1:5, 2:7])

    info = sceneio.inspect(path)
    assert info.format == "flo"
    assert info.payload_kind == "flow"
    assert info.shape == expected.shape
    assert info.dtype == "float32"
    assert info.channels == 2
    assert dict(info.metadata) == {
        "component_order": "uv",
        "u_axis": "right",
        "v_axis": "down",
        "row_order": "top_to_bottom",
        "unit": "pixels",
        "invalid_policy": "component_abs_gt_1e9",
    }


def test_extensionless_explicit_write_and_magic_detection(tmp_path):
    expected = _values()
    path = tmp_path / "extensionless"
    sceneio.write(_field(expected), path, format="flo")
    assert sceneio.detect(path) == "flo"
    _assert_canonical(sceneio.read(path), expected)


def test_writer_guard_does_not_truncate_destination(tmp_path):
    destination = tmp_path / "preserve.flo"
    destination.write_bytes(b"keep-existing-content")
    bad = _core.flow_field(
        np.zeros((2, 3, 2), np.float32),
        u_axis="left",
    )
    with pytest.raises(sceneio.FormatError, match="u_axis"):
        sceneio.write(bad, destination, format="flo")
    assert destination.read_bytes() == b"keep-existing-content"

    with pytest.raises(sceneio.FormatError):
        sceneio.write(np.zeros((2, 3, 2), np.float32), destination, format="flo")
    assert destination.read_bytes() == b"keep-existing-content"


def test_public_reader_uses_temporary_mmap_and_owns_values(tmp_path, monkeypatch):
    expected = _values(32, 48)
    path = tmp_path / "mapped.flo"
    path.write_bytes(_oracle_write(expected))

    calls = 0
    original = mmap.mmap

    def tracked(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(adapters.mmap, "mmap", tracked)
    flow = sceneio.read(path)
    assert calls == 1
    path.unlink()
    gc.collect()
    _assert_canonical(flow, expected)


def test_public_reader_mmap_failure_uses_stream_fallback(tmp_path, monkeypatch):
    expected = _values(8, 9)
    path = tmp_path / "fallback.flo"
    path.write_bytes(_oracle_write(expected))

    def unavailable(*args, **kwargs):
        raise OSError("mmap unavailable")

    monkeypatch.setattr(adapters.mmap, "mmap", unavailable)
    _assert_canonical(sceneio.read(path), expected)


def test_large_public_io_avoids_whole_file_python_bytes(tmp_path):
    values = np.zeros((2048, 2048, 2), np.float32)
    path = tmp_path / "large.flo"
    path.write_bytes(_oracle_write(values))
    file_size = path.stat().st_size
    del values
    gc.collect()

    tracemalloc.start()
    flow = sceneio.read(path)
    _, read_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert flow.vectors.shape == (2048, 2048, 2)
    assert read_peak < file_size / 8

    output = tmp_path / "large-output.flo"
    tracemalloc.start()
    sceneio.write(flow, output)
    _, write_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert output.stat().st_size == file_size
    assert write_peak < file_size / 8


def test_core_sink_handles_forced_short_writes(tmp_path):
    values = _values(64, 96)
    flow = _field(values)
    path = tmp_path / "short-write.flo"
    calls = _core._write_to_file(
        _core.write_flo,
        flow,
        path,
        _max_chunk=31,
        _test_short_write=7,
    )
    assert calls > 1
    assert path.read_bytes() == _oracle_write(values)


def test_inspect_is_header_bounded_on_sparse_file(tmp_path):
    height = 8192
    width = 4096
    expected_size = 12 + height * width * 2 * 4
    path = tmp_path / "sparse.flo"
    with path.open("wb") as stream:
        stream.write(b"PIEH" + struct.pack("<ii", width, height))
        stream.seek(expected_size - 1)
        stream.write(b"\0")

    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.shape == (height, width, 2)
    assert info.byte_size == expected_size
    assert peak < 1 << 20


def test_public_surface_has_one_flow_io_path():
    for name in ("read_flow", "write_flow", "inspect_flow"):
        assert not hasattr(sceneio, name)
        assert not hasattr(sceneio.io, name)
        assert name not in sceneio.__all__
        assert name not in sceneio.io.__all__

    capability = sceneio.capabilities("flo")
    assert capability.record_type == "FlowField"
    assert capability.partial_selectors == ("window",)
    assert capability.supported_features == (
        "float32",
        "fixed_uv_conventions",
        "pixel_windows",
    )
