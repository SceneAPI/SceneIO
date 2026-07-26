"""Typed FlowField adapters layered over the unchanged raw FLO codec."""

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


def _oracle_write(values: np.ndarray) -> bytes:
    values = np.ascontiguousarray(values, dtype=np.float32)
    height, width, channels = values.shape
    assert channels == 2
    return (
        b"PIEH"
        + struct.pack("<ii", width, height)
        + values.astype("<f4", copy=False).tobytes()
    )


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


def _assert_canonical(flow, expected):
    assert isinstance(flow, _core.FlowField)
    assert flow.vectors.tobytes() == expected.tobytes()
    assert flow.component_order == "uv"
    assert flow.u_axis == "right"
    assert flow.v_axis == "down"
    assert flow.row_order == "top_to_bottom"
    assert flow.unit == "pixels"
    assert flow.invalid_policy == "component_abs_gt_1e9"


def test_compiled_typed_reader_equals_raw_copy_bit_exact():
    expected = _values()
    encoded = _oracle_write(expected)
    raw = np.asarray(_core.read_flo(encoded))
    typed = _core.read_flo_field(encoded)

    assert typed.vectors.tobytes() == raw.tobytes() == expected.tobytes()
    _assert_canonical(typed, expected)

    for source in (
        encoded,
        memoryview(encoded),
        memoryview(bytearray(encoded)).toreadonly(),
    ):
        _assert_canonical(_core.read_flo_field(source), expected)


def test_compiled_typed_writer_is_raw_and_oracle_byte_identical():
    expected = _values()
    flow = _core.flow_field(expected)
    typed = bytes(_core.write_flo_field(flow))
    raw = bytes(_core.write_flo(expected))
    oracle = _oracle_write(expected)

    assert typed == raw == oracle
    _assert_canonical(_core.read_flo_field(typed), expected)


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("component_order", "vu", "component_order"),
        ("u_axis", "left", "u_axis"),
        ("v_axis", "up", "v_axis"),
        ("row_order", "bottom_to_top", "row_order"),
        ("unit", "unknown", "unit"),
        ("invalid_policy", "none", "invalid_policy"),
        ("invalid_policy", "nonfinite", "invalid_policy"),
    ],
)
def test_typed_writer_guards_foreign_conventions(keyword, value, message):
    flow = _core.flow_field(
        np.zeros((2, 3, 2), np.float32),
        **{keyword: value},
    )
    with pytest.raises(ValueError, match=message):
        _core.write_flo_field(flow)


def test_public_read_write_inspect_and_raw_compatibility(tmp_path):
    expected = _values()
    flow = _core.flow_field(expected)
    path = tmp_path / "field.flo"

    sceneio.write_flow(flow, path)
    assert path.read_bytes() == _oracle_write(expected)
    _assert_canonical(sceneio.read_flow(path), expected)
    _assert_canonical(sceneio.read_flow(path, format="flo"), expected)

    raw = sceneio.read(path)
    assert isinstance(raw, np.ndarray)
    assert not isinstance(raw, _core.FlowField)
    assert raw.tobytes() == expected.tobytes()

    info = sceneio.inspect_flow(path)
    assert info.format == "flo"
    assert info.datatype == "flow"
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


def test_extensionless_explicit_format_and_wrong_format_guards(tmp_path):
    flow = _core.flow_field(_values())
    path = tmp_path / "extensionless"
    sceneio.write_flow(flow, path, format="flo")
    _assert_canonical(sceneio.read_flow(path), flow.vectors)

    with pytest.raises(sceneio.FormatError, match="supports only"):
        sceneio.write_flow(flow, tmp_path / "wrong.bin")
    with pytest.raises(sceneio.FormatError, match="supports only"):
        sceneio.write_flow(flow, tmp_path / "wrong.bin", format="png")
    with pytest.raises(sceneio.FormatError, match="supports only"):
        sceneio.read_flow(path, format="png")
    with pytest.raises(sceneio.FormatError, match="supports only"):
        sceneio.inspect_flow(path, format="png")


def test_public_writer_guard_does_not_truncate_destination(tmp_path):
    destination = tmp_path / "preserve.flo"
    destination.write_bytes(b"keep-existing-content")
    bad = _core.flow_field(
        np.zeros((2, 3, 2), np.float32),
        u_axis="left",
    )
    with pytest.raises(sceneio.FormatError, match="u_axis"):
        sceneio.write_flow(bad, destination)
    assert destination.read_bytes() == b"keep-existing-content"

    with pytest.raises(sceneio.FormatError):
        sceneio.write_flow(np.zeros((2, 3, 2), np.float32), destination)
    assert destination.read_bytes() == b"keep-existing-content"


def test_public_reader_uses_temporary_mmap_and_result_owns_values(
    tmp_path, monkeypatch
):
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
    flow = sceneio.read_flow(path)
    assert calls == 1
    path.unlink()
    gc.collect()
    gc.collect()
    _assert_canonical(flow, expected)


def test_public_reader_mmap_failure_uses_same_stream_fallback(
    tmp_path, monkeypatch
):
    expected = _values(8, 9)
    path = tmp_path / "fallback.flo"
    path.write_bytes(_oracle_write(expected))

    def unavailable(*args, **kwargs):
        raise OSError("mmap unavailable")

    monkeypatch.setattr(adapters.mmap, "mmap", unavailable)
    _assert_canonical(sceneio.read_flow(path), expected)


def test_every_truncated_prefix_matches_raw_rejection():
    encoded = _oracle_write(_values(3, 4))
    for stop in range(len(encoded)):
        candidate = encoded[:stop]
        with pytest.raises(ValueError):
            _core.read_flo(candidate)
        with pytest.raises(ValueError):
            _core.read_flo_field(candidate)


def test_random_mutations_match_raw_success_or_failure():
    rng = np.random.default_rng(1701)
    encoded = bytearray(_oracle_write(_values(6, 7)))
    for _ in range(100):
        candidate = encoded.copy()
        offset = int(rng.integers(0, len(candidate)))
        candidate[offset] ^= int(rng.integers(1, 256))

        try:
            raw = np.asarray(_core.read_flo(bytes(candidate)))
        except ValueError:
            with pytest.raises(ValueError):
                _core.read_flo_field(bytes(candidate))
        else:
            typed = _core.read_flo_field(bytes(candidate))
            assert typed.vectors.tobytes() == raw.tobytes()


def test_randomized_typed_raw_oracle_differential():
    rng = np.random.default_rng(260724)
    for _ in range(75):
        height = int(rng.integers(1, 18))
        width = int(rng.integers(1, 18))
        values = rng.standard_normal((height, width, 2)).astype(np.float32)
        if rng.random() < 0.25:
            values.reshape(-1)[0] = np.float32(1e10)
        encoded = _oracle_write(values)
        typed = _core.read_flo_field(encoded)
        raw = np.asarray(_core.read_flo(encoded))
        assert typed.vectors.tobytes() == raw.tobytes() == values.tobytes()
        assert bytes(_core.write_flo_field(typed)) == encoded


def test_large_public_read_has_no_whole_file_python_bytes(tmp_path):
    values = np.zeros((2048, 2048, 2), np.float32)
    path = tmp_path / "large.flo"
    path.write_bytes(_oracle_write(values))
    file_size = path.stat().st_size
    del values
    gc.collect()

    tracemalloc.start()
    flow = sceneio.read_flow(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert flow.vectors.shape == (2048, 2048, 2)
    assert peak < file_size / 8

    output = tmp_path / "large-output.flo"
    tracemalloc.start()
    sceneio.write_flow(flow, output)
    _, write_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert output.stat().st_size == file_size
    assert write_peak < file_size / 8


def test_typed_core_sink_handles_forced_short_writes(tmp_path):
    values = _values(64, 96)
    flow = _core.flow_field(values)
    path = tmp_path / "short-write.flo"
    calls = _core._write_to_file(
        _core.write_flo_field,
        flow,
        path,
        _max_chunk=31,
        _test_short_write=7,
    )
    assert calls > 1
    assert path.read_bytes() == _oracle_write(values)


def test_typed_inspect_is_header_bounded_on_sparse_file(tmp_path):
    height = 8192
    width = 4096
    expected_size = 12 + height * width * 2 * 4
    path = tmp_path / "sparse.flo"
    with path.open("wb") as stream:
        stream.write(b"PIEH" + struct.pack("<ii", width, height))
        stream.seek(expected_size - 1)
        stream.write(b"\0")

    tracemalloc.start()
    info = sceneio.inspect_flow(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert info.shape == (height, width, 2)
    assert info.byte_size == expected_size
    assert peak < 1 << 20


def test_public_exports_and_capability_marker():
    assert sceneio.read_flow is sceneio.io.read_flow
    assert sceneio.write_flow is sceneio.io.write_flow
    assert sceneio.inspect_flow is sceneio.io.inspect_flow
    assert "read_flow" in sceneio.__all__
    assert "write_flow" in sceneio.__all__
    assert "inspect_flow" in sceneio.__all__
    assert "read_flow" in sceneio.io.__all__
    assert "write_flow" in sceneio.io.__all__
    assert "inspect_flow" in sceneio.io.__all__
    assert "typed_flow_adapter" in sceneio.capabilities(
        "flo"
    ).supported_features
