"""Typed PFM depth contracts over the unchanged raw ndarray codec."""

from __future__ import annotations

import dataclasses
import gc
import struct
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _encoding(
    *,
    unit: str = "meters",
    scale_to_meters: float = 1.0,
    invalid_policy: str = "nonfinite",
    channel_name: str | None = None,
) -> sceneio.DepthEncoding:
    return sceneio.DepthEncoding(
        unit,
        scale_to_meters,
        invalid_policy,
        channel_name,
    )


def _bits() -> np.ndarray:
    return np.array(
        [
            0x00000000,
            0x80000000,
            0x3F800000,
            0xBF800000,
            0x00000001,
            0x7F800000,
            0xFF800000,
            0x7FC12345,
            0xFFC54321,
            0x41200000,
            0xC1200000,
            0x7F7FFFFF,
        ],
        dtype=np.uint32,
    ).view(np.float32).reshape(3, 4)


def _oracle_write(
    values: np.ndarray,
    *,
    header_scale: float = -1.0,
    color: bool = False,
) -> bytes:
    values = np.ascontiguousarray(values, dtype=np.float32)
    if color:
        height, width, channels = values.shape
        assert channels == 3
    else:
        height, width = values.shape
    endian = "<" if np.signbit(header_scale) else ">"
    payload = np.flipud(values).astype(f"{endian}f4").tobytes()
    magic = "PF" if color else "Pf"
    return (
        f"{magic}\n{width} {height}\n{header_scale}\n".encode("ascii")
        + payload
    )


def _assert_bits_equal(actual, expected) -> None:
    np.testing.assert_array_equal(
        np.asarray(actual).view(np.uint32),
        np.asarray(expected).view(np.uint32),
    )


def _invoke_public_depth(operation, path, encoding) -> None:
    if operation == "read":
        sceneio.read_depth(path, encoding=encoding)
    elif operation == "inspect":
        sceneio.inspect_depth(path, encoding=encoding)
    else:
        depth = _core.depth_map(np.ones((2, 2), np.float32))
        sceneio.write_depth(depth, path, encoding=encoding)


def test_depth_encoding_is_frozen_and_normalized():
    encoding = _encoding()
    assert encoding.scale_to_meters == 1.0
    assert type(encoding.scale_to_meters) is float
    assert encoding.channel_name is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        encoding.unit = "unknown"


@pytest.mark.parametrize(
    ("unit", "scale"),
    [
        ("meters", 1.0),
        ("millimeters", 0.001),
        ("custom", 1 / 5000),
        ("custom", 1.0),
        ("unitless", 0.0),
        ("unknown", 0.0),
    ],
)
@pytest.mark.parametrize(
    "invalid_policy",
    ["none", "zero", "nonfinite", "negative"],
)
def test_depth_encoding_accepts_record_vocabulary(unit, scale, invalid_policy):
    encoding = _encoding(
        unit=unit,
        scale_to_meters=scale,
        invalid_policy=invalid_policy,
    )
    assert (encoding.unit, encoding.scale_to_meters, encoding.invalid_policy) == (
        unit,
        scale,
        invalid_policy,
    )


@pytest.mark.parametrize(
    ("unit", "scale"),
    [
        ("metres", 1.0),
        ("meters", 0.001),
        ("millimeters", 1.0),
        ("custom", 0.0),
        ("custom", -1.0),
        ("custom", np.inf),
        ("unitless", 1.0),
        ("unknown", np.nan),
    ],
)
def test_depth_encoding_rejects_bad_unit_scale_pairs(unit, scale):
    with pytest.raises((TypeError, ValueError), match=r"unit|scale"):
        _encoding(unit=unit, scale_to_meters=scale)


@pytest.mark.parametrize("scale", [True, None, "1.0", object()])
def test_depth_encoding_rejects_non_real_scale(scale):
    with pytest.raises(TypeError, match="real number"):
        _encoding(scale_to_meters=scale)


@pytest.mark.parametrize("policy", ["", "nan", "sentinel", None])
def test_depth_encoding_rejects_unknown_invalid_policy(policy):
    with pytest.raises(ValueError, match="invalid_policy"):
        _encoding(invalid_policy=policy)


@pytest.mark.parametrize("channel", ["", "Z\0extra", 7])
def test_depth_encoding_rejects_invalid_channel_name(channel):
    error = TypeError if channel == 7 else ValueError
    with pytest.raises(error, match="channel_name"):
        _encoding(channel_name=channel)


@pytest.mark.parametrize("header_scale", [-1.0, 1.0])
def test_typed_core_matches_raw_and_oracle_bit_exact(header_scale):
    values = _bits()
    encoded = _oracle_write(values, header_scale=header_scale)
    encoding = _encoding()

    typed = _core.read_pfm_depth(
        memoryview(encoded),
        encoding.unit,
        encoding.scale_to_meters,
        encoding.invalid_policy,
    )
    raw = _core.read_pfm(encoded)

    _assert_bits_equal(typed.depth, values)
    _assert_bits_equal(typed.depth, raw)
    assert (
        typed.unit,
        typed.scale_to_meters,
        typed.invalid_policy,
        typed.row_order,
    ) == ("meters", 1.0, "nonfinite", "top_to_bottom")
    assert not typed.has_confidence


def test_typed_writer_is_byte_identical_to_raw_and_oracle():
    values = _bits()
    encoding = _encoding()
    depth = _core.depth_map(
        values,
        unit=encoding.unit,
        scale_to_meters=encoding.scale_to_meters,
        invalid_policy=encoding.invalid_policy,
    )
    actual = bytes(
        _core.write_pfm_depth(
            depth,
            encoding.unit,
            encoding.scale_to_meters,
            encoding.invalid_policy,
        )
    )
    assert actual == bytes(_core.write_pfm(values))
    assert actual == _oracle_write(values)


def test_hand_computable_row_order_and_no_rescale():
    stored = np.array([[0.0, 5000.0], [10000.0, -1.0]], np.float32)
    encoding = _encoding(
        unit="custom",
        scale_to_meters=1 / 5000,
        invalid_policy="negative",
    )
    typed = _core.read_pfm_depth(
        _oracle_write(stored),
        encoding.unit,
        encoding.scale_to_meters,
        encoding.invalid_policy,
    )
    np.testing.assert_array_equal(typed.depth, stored)
    assert typed.depth[0, 1] == 5000.0
    assert typed.depth[0, 1] * typed.scale_to_meters == 1.0
    assert typed.depth[-1, -1] == -1.0


@pytest.mark.parametrize("header_scale", [-2.0, 2.0, -0.5, 0.5])
def test_typed_reader_rejects_ambiguous_scale_magnitude_but_raw_stays_compatible(
    header_scale,
):
    encoded = _oracle_write(np.ones((2, 3), np.float32), header_scale=header_scale)
    np.testing.assert_array_equal(_core.read_pfm(encoded), 1.0)
    with pytest.raises(ValueError, match=r"magnitude.*1\.0"):
        _core.read_pfm_depth(encoded, "meters", 1.0, "none")
    with pytest.raises(ValueError, match=r"magnitude.*1\.0"):
        _core._inspect_pfm_depth(encoded)


def test_typed_reader_rejects_rgb_but_raw_stays_compatible():
    values = np.arange(18, dtype=np.float32).reshape(2, 3, 3)
    encoded = _oracle_write(values, color=True)
    np.testing.assert_array_equal(_core.read_pfm(encoded), values)
    with pytest.raises(ValueError, match="one-channel"):
        _core.read_pfm_depth(encoded, "meters", 1.0, "none")
    with pytest.raises(ValueError, match="one-channel"):
        _core._inspect_pfm_depth(encoded)


@pytest.mark.parametrize(
    ("unit", "scale", "policy", "match"),
    [
        ("meters", 0.001, "none", "unit/scale"),
        ("invalid", 1.0, "none", "unit"),
        ("meters", 1.0, "nan", "invalid_policy"),
    ],
)
def test_typed_core_validates_external_encoding(unit, scale, policy, match):
    encoded = _oracle_write(np.ones((2, 2), np.float32))
    with pytest.raises(ValueError, match=match):
        _core.read_pfm_depth(encoded, unit, scale, policy)


def test_typed_core_writer_rejects_mismatch_and_confidence():
    values = np.ones((2, 3), np.float32)
    depth = _core.depth_map(values, invalid_policy="zero")
    with pytest.raises(ValueError, match="does not match"):
        _core.write_pfm_depth(depth, "meters", 1.0, "none")

    with_confidence = _core.depth_map(
        values,
        np.ones_like(values),
        invalid_policy="zero",
    )
    with pytest.raises(ValueError, match="confidence"):
        _core.write_pfm_depth(with_confidence, "meters", 1.0, "zero")


def test_public_read_write_inspect_and_raw_api_unchanged(tmp_path):
    values = _bits()
    encoding = _encoding()
    depth = _core.depth_map(values, invalid_policy="nonfinite")
    path = tmp_path / "depth.pfm"

    sceneio.write_depth(depth, path, encoding=encoding)
    typed = sceneio.read_depth(path, encoding=encoding)
    info = sceneio.inspect_depth(path, encoding=encoding)
    raw = sceneio.read(path)

    _assert_bits_equal(typed.depth, values)
    assert isinstance(raw, np.ndarray)
    _assert_bits_equal(raw, values)
    assert info.format == "pfm"
    assert info.datatype == "depth_map"
    assert info.shape == values.shape
    assert info.dtype == "float32"
    assert info.channels == 1
    assert dict(info.metadata) == {
        "byte_order": "little",
        "header_scale": -1.0,
        "row_order": "top_to_bottom",
        "unit": "meters",
        "scale_to_meters": 1.0,
        "invalid_policy": "nonfinite",
    }


def test_public_explicit_format_supports_extensionless_path(tmp_path):
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    encoding = _encoding(invalid_policy="zero")
    depth = _core.depth_map(values, invalid_policy="zero")
    path = tmp_path / "depth"

    sceneio.write_depth(depth, path, encoding=encoding, format="pfm")
    np.testing.assert_array_equal(
        sceneio.read_depth(path, encoding=encoding, format="pfm").depth,
        values,
    )
    assert sceneio.inspect_depth(path, encoding=encoding, format="pfm").shape == (
        3,
        4,
    )


def test_public_detects_extensionless_pfm_on_read(tmp_path):
    path = tmp_path / "depth"
    path.write_bytes(_oracle_write(np.ones((2, 3), np.float32)))
    assert sceneio.read_depth(path, encoding=_encoding()).depth.shape == (2, 3)


@pytest.mark.parametrize("operation", ["read", "inspect"])
def test_public_wrong_format_is_clear(operation, tmp_path):
    path = tmp_path / "values.npy"
    np.save(path, np.ones((2, 3), np.float32))
    function = sceneio.read_depth if operation == "read" else sceneio.inspect_depth
    with pytest.raises(sceneio.FormatError, match=r"supports typed depth.*pfm"):
        function(path, encoding=_encoding())


def test_public_write_wrong_extension_does_not_touch_destination(tmp_path):
    path = tmp_path / "depth.bin"
    path.write_bytes(b"keep")
    depth = _core.depth_map(np.ones((2, 2), np.float32))
    with pytest.raises(sceneio.FormatError, match=r"supports typed depth.*pfm"):
        sceneio.write_depth(depth, path, encoding=_encoding())
    assert path.read_bytes() == b"keep"


@pytest.mark.parametrize("operation", ["read", "inspect", "write"])
def test_public_requires_depth_encoding(operation, tmp_path):
    path = tmp_path / "depth.pfm"
    path.write_bytes(_oracle_write(np.ones((2, 2), np.float32)))
    with pytest.raises(TypeError, match="DepthEncoding"):
        _invoke_public_depth(operation, path, None)


@pytest.mark.parametrize("operation", ["read", "inspect", "write"])
def test_pfm_rejects_named_depth_channel(operation, tmp_path):
    path = tmp_path / "depth.pfm"
    path.write_bytes(_oracle_write(np.ones((2, 2), np.float32)))
    encoding = _encoding(channel_name="Z")
    with pytest.raises(ValueError, match="no named channel"):
        _invoke_public_depth(operation, path, encoding)


def test_public_writer_guards_before_destination_truncation(tmp_path):
    path = tmp_path / "depth.pfm"
    path.write_bytes(b"keep")
    encoding = _encoding(invalid_policy="zero")
    mismatched = _core.depth_map(np.ones((2, 2), np.float32))
    with pytest.raises(sceneio.FormatError, match="does not match"):
        sceneio.write_depth(mismatched, path, encoding=encoding)
    assert path.read_bytes() == b"keep"

    confidence = _core.depth_map(
        np.ones((2, 2), np.float32),
        np.ones((2, 2), np.float32),
        invalid_policy="zero",
    )
    with pytest.raises(sceneio.FormatError, match="confidence"):
        sceneio.write_depth(confidence, path, encoding=encoding)
    assert path.read_bytes() == b"keep"


def test_typed_window_equals_full_slice_with_metadata(tmp_path):
    values = np.arange(8 * 11, dtype=np.float32).reshape(8, 11)
    encoding = _encoding(
        unit="millimeters",
        scale_to_meters=0.001,
        invalid_policy="zero",
    )
    path = tmp_path / "depth.pfm"
    path.write_bytes(_oracle_write(values))

    full = sceneio.read_depth(path, encoding=encoding)
    partial = sceneio.read_depth(
        path,
        encoding=encoding,
        window=(2, 7, 3, 10),
    )
    np.testing.assert_array_equal(partial.depth, full.depth[2:7, 3:10])
    assert (
        partial.unit,
        partial.scale_to_meters,
        partial.invalid_policy,
        partial.row_order,
    ) == (
        full.unit,
        full.scale_to_meters,
        full.invalid_policy,
        full.row_order,
    )


@pytest.mark.parametrize(
    ("window", "error"),
    [
        ((0, 1, 2), ValueError),
        ("0,1,0,1", TypeError),
        ((False, 1, 0, 1), TypeError),
        ((0.0, 1, 0, 1), TypeError),
        ((0, 0, 0, 1), sceneio.FormatError),
        ((0, 3, 0, 1), sceneio.FormatError),
    ],
)
def test_typed_window_validation(window, error, tmp_path):
    path = tmp_path / "depth.pfm"
    path.write_bytes(_oracle_write(np.ones((2, 3), np.float32)))
    with pytest.raises(error):
        sceneio.read_depth(path, encoding=_encoding(), window=window)


def test_typed_result_owns_values_after_mapping_closes_and_path_unlinks(tmp_path):
    values = _bits()
    path = tmp_path / "depth.pfm"
    path.write_bytes(_oracle_write(values))
    depth = sceneio.read_depth(path, encoding=_encoding())
    view = depth.depth

    del depth
    gc.collect()
    path.unlink()
    churn = [np.full(values.shape, index, np.float32) for index in range(128)]
    assert churn[-1][0, 0] == 127
    _assert_bits_equal(view, values)


def test_typed_decode_is_isolated_from_mutable_source():
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    source = bytearray(_oracle_write(values))
    readonly = memoryview(source).toreadonly()
    depth = _core.read_pfm_depth(readonly, "meters", 1.0, "none")
    readonly.release()
    source[:] = b"\xff" * len(source)
    np.testing.assert_array_equal(depth.depth, values)


def test_mmap_failure_uses_same_stream_fallback(monkeypatch, tmp_path):
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    path = tmp_path / "depth.pfm"
    path.write_bytes(_oracle_write(values))

    def unavailable(*args, **kwargs):
        raise OSError("mapping unavailable")

    monkeypatch.setattr("sceneio.io._registry.adapters.mmap.mmap", unavailable)
    np.testing.assert_array_equal(
        sceneio.read_depth(path, encoding=_encoding()).depth,
        values,
    )
    assert sceneio.inspect_depth(path, encoding=_encoding()).shape == (3, 4)


def test_every_truncated_prefix_fails_raw_and_typed():
    encoded = _oracle_write(_bits())
    for stop in range(len(encoded)):
        prefix = encoded[:stop]
        with pytest.raises(ValueError):
            _core.read_pfm(prefix)
        with pytest.raises(ValueError):
            _core.read_pfm_depth(prefix, "meters", 1.0, "none")


def test_random_payload_mutations_match_raw_bit_exact():
    rng = np.random.default_rng(20260724)
    values = rng.standard_normal((17, 19)).astype(np.float32)
    encoded = bytearray(_oracle_write(values))
    payload_start = encoded.index(b"\n", encoded.index(b"\n") + 1) + 1
    payload_start = encoded.index(b"\n", payload_start) + 1
    for _ in range(100):
        mutated = bytearray(encoded)
        index = int(rng.integers(payload_start, len(mutated)))
        mutated[index] ^= int(rng.integers(1, 256))
        raw = _core.read_pfm(bytes(mutated))
        typed = _core.read_pfm_depth(bytes(mutated), "meters", 1.0, "none")
        _assert_bits_equal(typed.depth, raw)


def test_random_valid_oracle_raw_typed_triangulation():
    rng = np.random.default_rng(37)
    encodings = [
        _encoding(invalid_policy="none"),
        _encoding(
            unit="millimeters",
            scale_to_meters=0.001,
            invalid_policy="zero",
        ),
        _encoding(
            unit="custom",
            scale_to_meters=1 / 5000,
            invalid_policy="negative",
        ),
        _encoding(
            unit="unknown",
            scale_to_meters=0.0,
            invalid_policy="nonfinite",
        ),
    ]
    for index in range(75):
        height = int(rng.integers(1, 24))
        width = int(rng.integers(1, 24))
        values = rng.integers(
            0,
            2**32,
            size=(height, width),
            dtype=np.uint32,
        ).view(np.float32)
        encoding = encodings[index % len(encodings)]
        encoded = _oracle_write(
            values,
            header_scale=-1.0 if index % 2 == 0 else 1.0,
        )
        raw = _core.read_pfm(encoded)
        typed = _core.read_pfm_depth(
            encoded,
            encoding.unit,
            encoding.scale_to_meters,
            encoding.invalid_policy,
        )
        _assert_bits_equal(raw, values)
        _assert_bits_equal(typed.depth, values)


def test_large_public_paths_avoid_whole_file_python_bytes(tmp_path):
    height, width = 2048, 4096
    path = tmp_path / "large.pfm"
    header = f"Pf\n{width} {height}\n-1.0\n".encode()
    expected_size = len(header) + height * width * 4
    with path.open("wb") as stream:
        stream.write(header)
        stream.seek(expected_size - 1)
        stream.write(b"\0")

    tracemalloc.start()
    depth = sceneio.read_depth(path, encoding=_encoding())
    _, read_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert depth.depth.shape == (height, width)
    assert read_peak < expected_size / 8

    output = tmp_path / "large-output.pfm"
    tracemalloc.start()
    sceneio.write_depth(depth, output, encoding=_encoding())
    _, write_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert output.stat().st_size == expected_size
    assert write_peak < expected_size / 8


def test_sparse_inspection_and_window_are_payload_bounded(tmp_path):
    height, width = 8192, 4096
    path = tmp_path / "sparse.pfm"
    header = f"Pf\n{width} {height}\n-1.0\n".encode()
    expected_size = len(header) + height * width * 4
    with path.open("wb") as stream:
        stream.write(header)
        stream.seek(expected_size - 1)
        stream.write(b"\0")

    tracemalloc.start()
    info = sceneio.inspect_depth(path, encoding=_encoding())
    window = sceneio.read_depth(
        path,
        encoding=_encoding(),
        window=(4090, 4098, 2000, 2008),
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.shape == (height, width)
    assert window.depth.shape == (8, 8)
    assert peak < 1024 * 1024


def test_typed_sink_handles_forced_short_writes(tmp_path):
    values = np.arange(64 * 96, dtype=np.float32).reshape(64, 96)
    encoding = _encoding(invalid_policy="zero")
    depth = _core.depth_map(values, invalid_policy="zero")
    request = (
        depth,
        encoding.unit,
        encoding.scale_to_meters,
        encoding.invalid_policy,
    )
    path = tmp_path / "short-write.pfm"
    calls = _core._write_to_file(
        _core._write_pfm_depth_request,
        request,
        path,
        _max_chunk=31,
        _test_short_write=7,
    )
    assert calls > 1
    assert path.read_bytes() == _oracle_write(values)


def test_inspector_exposes_signed_header_token(tmp_path):
    values = np.ones((2, 3), np.float32)
    for header_scale in (-1.0, 1.0):
        path = tmp_path / f"{header_scale}.pfm"
        path.write_bytes(_oracle_write(values, header_scale=header_scale))
        info = sceneio.inspect_depth(path, encoding=_encoding())
        assert info.metadata["header_scale"] == header_scale
        expected = "little" if header_scale < 0 else "big"
        assert info.metadata["byte_order"] == expected


def test_public_exports_and_capability_marker():
    assert sceneio.DepthEncoding is sceneio.io.DepthEncoding
    assert sceneio.read_depth is sceneio.io.read_depth
    assert sceneio.write_depth is sceneio.io.write_depth
    assert sceneio.inspect_depth is sceneio.io.inspect_depth
    assert "DepthEncoding" in sceneio.__all__
    assert "read_depth" in sceneio.__all__
    assert "typed_depth_adapter" in sceneio.capabilities(
        "pfm"
    ).supported_features


def test_raw_writer_now_rejects_empty_dimensions():
    with pytest.raises(ValueError, match="non-positive"):
        _core.write_pfm(np.empty((0, 3), np.float32))


def test_header_scale_token_is_not_reinterpreted_as_depth_scale():
    values = np.array([[2.0]], np.float32)
    encoding = _encoding(
        unit="custom",
        scale_to_meters=0.25,
        invalid_policy="none",
    )
    encoded = b"Pf\n1 1\n-1e0\n" + struct.pack("<f", 2.0)
    depth = _core.read_pfm_depth(
        encoded,
        encoding.unit,
        encoding.scale_to_meters,
        encoding.invalid_policy,
    )
    assert depth.depth[0, 0] == values[0, 0]
    assert depth.scale_to_meters == 0.25
