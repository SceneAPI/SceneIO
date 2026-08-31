"""Typed uint16 PNG depth adapters over the unchanged Image codec."""

from __future__ import annotations

import gc
import io
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core

png = pytest.importorskip("png")


def _encoding(
    *,
    unit: str = "millimeters",
    scale_to_meters: float = 0.001,
    invalid_policy: str = "zero",
    channel_name: str | None = None,
) -> sceneio.DepthEncoding:
    return sceneio.DepthEncoding(
        unit,
        scale_to_meters,
        invalid_policy,
        channel_name,
    )


def _oracle_write(
    values: np.ndarray,
    *,
    bitdepth: int = 16,
    color: bool = False,
    alpha: bool = False,
    interlace: bool = False,
) -> bytes:
    values = np.asarray(values)
    height, width = values.shape[:2]
    channels = 1 if values.ndim == 2 else values.shape[2]
    expected_channels = (2 if alpha else 1) if not color else (4 if alpha else 3)
    assert channels == expected_channels
    output = io.BytesIO()
    png.Writer(
        width,
        height,
        greyscale=not color,
        alpha=alpha,
        bitdepth=bitdepth,
        interlace=interlace,
    ).write(output, values.reshape(height, width * channels).tolist())
    return output.getvalue()


def _oracle_read(data: bytes) -> np.ndarray:
    width, height, rows, info = png.Reader(bytes=data).read()
    dtype = np.uint16 if info["bitdepth"] == 16 else np.uint8
    values = np.vstack([np.asarray(row, dtype=dtype) for row in rows])
    values = values.reshape(height, width, info["planes"])
    return values[:, :, 0] if info["planes"] == 1 else values


def _depth(values: np.ndarray, encoding=None, confidence=None):
    selected = encoding or _encoding()
    return _core.depth_map(
        np.ascontiguousarray(values, dtype=np.float32),
        confidence,
        unit=selected.unit,
        scale_to_meters=selected.scale_to_meters,
        invalid_policy=selected.invalid_policy,
    )


def _write_core(depth, encoding=None, *, lanes=0) -> bytes:
    selected = encoding or _encoding()
    return bytes(
        _core.write_png_depth(
            depth,
            selected.unit,
            selected.scale_to_meters,
            selected.invalid_policy,
            _lanes=lanes,
        )
    )


def _read_core(data, encoding=None, *, lanes=0):
    selected = encoding or _encoding()
    return _core.read_png_depth(
        data,
        selected.unit,
        selected.scale_to_meters,
        selected.invalid_policy,
        _lanes=lanes,
    )


def _invoke_public(operation, path, encoding) -> None:
    if operation == "read":
        sceneio.read_depth(path, encoding=encoding)
    elif operation == "inspect":
        sceneio.inspect_depth(path, encoding=encoding)
    else:
        sceneio.write_depth(_depth(np.ones((2, 2))), path, encoding=encoding)


def test_core_read_exactly_widens_raw_grayscale_u16():
    stored = np.array(
        [[0, 1, 255, 256], [4096, 32768, 60000, 65535]],
        dtype=np.uint16,
    )
    encoded = _oracle_write(stored)
    raw = _core.read_png(encoded)
    typed = _read_core(memoryview(encoded))

    assert raw.dtype == "uint16"
    np.testing.assert_array_equal(raw.pixels, stored)
    assert typed.depth.dtype == np.float32
    np.testing.assert_array_equal(typed.depth, stored.astype(np.float32))
    assert (
        typed.unit,
        typed.scale_to_meters,
        typed.invalid_policy,
        typed.row_order,
    ) == ("millimeters", 0.001, "zero", "top_to_bottom")


def test_core_writer_matches_raw_writer_and_pypng():
    stored = np.array(
        [[0, 1, 255, 256], [4096, 32768, 60000, 65535]],
        dtype=np.uint16,
    )
    typed_bytes = _write_core(_depth(stored))
    raw_bytes = bytes(
        _core.write_png(_core.image(stored, color_space="gray"))
    )
    assert typed_bytes == raw_bytes
    np.testing.assert_array_equal(_oracle_read(typed_bytes), stored)


@pytest.mark.parametrize(
    ("encoding", "stored", "meters"),
    [
        (
            sceneio.DepthEncoding("custom", 1 / 5000, "zero"),
            5000,
            1.0,
        ),
        (
            sceneio.DepthEncoding("millimeters", 0.001, "zero"),
            1500,
            1.5,
        ),
    ],
)
def test_named_depth_profiles_are_explicit_and_never_rescaled(
    encoding,
    stored,
    meters,
):
    values = np.array([[0, stored, 65535]], np.uint16)
    typed = _read_core(_oracle_write(values), encoding)
    np.testing.assert_array_equal(typed.depth, values.astype(np.float32))
    assert typed.depth[0, 1] == stored
    assert float(typed.depth[0, 1]) * typed.scale_to_meters == meters


def test_interlaced_grayscale_u16_is_supported():
    values = np.arange(13 * 17, dtype=np.uint16).reshape(13, 17)
    encoded = _oracle_write(values, interlace=True)
    typed = _read_core(encoded)
    np.testing.assert_array_equal(typed.depth, values.astype(np.float32))


@pytest.mark.parametrize(
    ("values", "kwargs"),
    [
        (np.arange(6, dtype=np.uint8).reshape(2, 3), {"bitdepth": 8}),
        (
            np.arange(18, dtype=np.uint16).reshape(2, 3, 3),
            {"color": True},
        ),
        (
            np.arange(24, dtype=np.uint16).reshape(2, 3, 4),
            {"color": True, "alpha": True},
        ),
    ],
)
def test_typed_read_rejects_wrong_dtype_or_channel_count_but_raw_accepts(
    values,
    kwargs,
):
    encoded = _oracle_write(values, **kwargs)
    raw = _core.read_png(encoded)
    np.testing.assert_array_equal(raw.pixels, values)
    with pytest.raises(ValueError, match="grayscale uint16"):
        _read_core(encoded)


def test_typed_read_rejects_palette_but_raw_expands_it():
    pillow = pytest.importorskip("PIL.Image")
    image = pillow.new("P", (2, 2))
    image.putpalette([0, 0, 0, 255, 255, 255])
    image.putdata([0, 1, 1, 0])
    output = io.BytesIO()
    image.save(output, format="PNG")
    encoded = output.getvalue()

    assert _core.read_png(encoded).channels == 3
    with pytest.raises(ValueError, match="grayscale uint16"):
        _read_core(encoded)


@pytest.mark.parametrize(
    "value",
    [
        -1.0,
        65536.0,
        0.5,
        1.25,
        np.nan,
        np.inf,
        -np.inf,
        np.array([0x80000000], np.uint32).view(np.float32)[0],
    ],
)
def test_typed_writer_rejects_unrepresentable_float(value):
    values = np.array([[0.0, value]], np.float32)
    with pytest.raises(ValueError, match=r"integer.*\[0,65535\]"):
        _write_core(_depth(values))


@pytest.mark.parametrize("value", [0.0, 1.0, 65535.0])
def test_typed_writer_accepts_exact_boundary_integer(value):
    values = np.array([[value]], np.float32)
    encoded = _write_core(_depth(values))
    np.testing.assert_array_equal(
        _oracle_read(encoded),
        values.astype(np.uint16),
    )


def test_typed_writer_rejects_metadata_mismatch_and_confidence():
    encoding = _encoding()
    mismatch = _core.depth_map(
        np.ones((2, 3), np.float32),
        unit="meters",
        invalid_policy="zero",
    )
    with pytest.raises(ValueError, match="does not match"):
        _write_core(mismatch, encoding)

    confidence = np.ones((2, 3), np.float32)
    with pytest.raises(ValueError, match="confidence"):
        _write_core(_depth(np.ones((2, 3)), confidence=confidence), encoding)


def test_typed_core_lane_counts_are_identical():
    rng = np.random.default_rng(20260724)
    values = rng.integers(
        0,
        65536,
        size=(1024, 1024),
        dtype=np.uint16,
    )
    depth = _depth(values)
    serial = _write_core(depth, lanes=1)
    parallel = _write_core(depth, lanes=0)
    assert serial == parallel
    np.testing.assert_array_equal(
        _read_core(serial, lanes=1).depth,
        _read_core(parallel, lanes=0).depth,
    )


def test_public_read_write_inspect_and_raw_api_unchanged(tmp_path):
    values = np.array([[0, 1, 5000], [1500, 65535, 7]], np.uint16)
    encoding = sceneio.DepthEncoding("custom", 1 / 5000, "zero")
    depth = _depth(values, encoding)
    path = tmp_path / "depth.png"

    sceneio.write_depth(depth, path, encoding=encoding)
    typed = sceneio.read_depth(path, encoding=encoding)
    info = sceneio.inspect_depth(path, encoding=encoding)
    raw = sceneio.read(path)

    np.testing.assert_array_equal(typed.depth, values.astype(np.float32))
    assert isinstance(raw, _core.Image)
    assert raw.dtype == "uint16" and raw.channels == 1
    np.testing.assert_array_equal(raw.pixels, values)
    assert info.format == "png"
    assert info.payload_kind == "depth_map"
    assert info.shape == values.shape
    assert info.dtype == "float32"
    assert info.channels == 1
    assert info.byte_size == path.stat().st_size
    assert dict(info.metadata) == {
        "interlaced": False,
        "stored_dtype": "uint16",
        "decoded_dtype": "float32",
        "row_order": "top_to_bottom",
        "unit": "custom",
        "scale_to_meters": 1 / 5000,
        "invalid_policy": "zero",
    }


def test_public_explicit_format_supports_extensionless_path(tmp_path):
    values = np.arange(12, dtype=np.uint16).reshape(3, 4)
    path = tmp_path / "depth"
    sceneio.write_depth(
        _depth(values),
        path,
        encoding=_encoding(),
        format="png",
    )
    np.testing.assert_array_equal(
        sceneio.read_depth(
            path,
            encoding=_encoding(),
            format="png",
        ).depth,
        values.astype(np.float32),
    )
    assert sceneio.inspect_depth(
        path,
        encoding=_encoding(),
        format="png",
    ).shape == (3, 4)


def test_public_detects_extensionless_png_on_read(tmp_path):
    path = tmp_path / "depth"
    path.write_bytes(_oracle_write(np.ones((2, 3), np.uint16)))
    assert sceneio.read_depth(path, encoding=_encoding()).depth.shape == (2, 3)


@pytest.mark.parametrize("operation", ["read", "inspect", "write"])
def test_png_rejects_named_depth_channel(operation, tmp_path):
    path = tmp_path / "depth.png"
    path.write_bytes(_oracle_write(np.ones((2, 2), np.uint16)))
    encoding = _encoding(channel_name="Z")
    with pytest.raises(ValueError, match="no named channel"):
        _invoke_public(operation, path, encoding)


def test_png_typed_window_is_explicitly_unsupported(tmp_path, monkeypatch):
    path = tmp_path / "depth.png"
    path.write_bytes(_oracle_write(np.ones((2, 3), np.uint16)))

    def must_not_decode(*args, **kwargs):
        raise AssertionError("compressed PNG should not be fully decoded")

    monkeypatch.setattr("sceneio.io._depth._PNG_DEPTH_READER", must_not_decode)
    with pytest.raises(sceneio.FormatError, match=r"does not support.*window"):
        sceneio.read_depth(
            path,
            encoding=_encoding(),
            window=(0, 1, 0, 1),
        )


@pytest.mark.parametrize(
    ("window", "error"),
    [
        ((0, 1, 2), ValueError),
        ("0,1,0,1", TypeError),
        ((False, 1, 0, 1), TypeError),
        ((0.0, 1, 0, 1), TypeError),
    ],
)
def test_png_window_selector_validation_precedes_capability_error(
    window,
    error,
    tmp_path,
):
    path = tmp_path / "depth.png"
    path.write_bytes(_oracle_write(np.ones((2, 3), np.uint16)))
    with pytest.raises(error):
        sceneio.read_depth(path, encoding=_encoding(), window=window)


def test_public_writer_guards_before_destination_truncation(tmp_path):
    path = tmp_path / "depth.png"
    path.write_bytes(b"keep")
    mismatch = _core.depth_map(
        np.ones((2, 2), np.float32),
        unit="meters",
        invalid_policy="zero",
    )
    with pytest.raises(sceneio.FormatError, match="does not match"):
        sceneio.write_depth(mismatch, path, encoding=_encoding())
    assert path.read_bytes() == b"keep"

    invalid = _depth(np.array([[0.5]], np.float32))
    with pytest.raises(sceneio.FormatError, match="exact non-negative integer"):
        sceneio.write_depth(invalid, path, encoding=_encoding())
    assert path.read_bytes() == b"keep"


def test_public_rejects_wrong_object_without_touching_destination(tmp_path):
    path = tmp_path / "depth.png"
    path.write_bytes(b"keep")
    with pytest.raises(TypeError, match="DepthMap"):
        sceneio.write_depth(
            np.ones((2, 2), np.float32),
            path,
            encoding=_encoding(),
        )
    assert path.read_bytes() == b"keep"


@pytest.mark.parametrize(
    ("values", "kwargs"),
    [
        (np.ones((2, 3), np.uint8), {"bitdepth": 8}),
        (
            np.ones((2, 3, 3), np.uint16),
            {"color": True},
        ),
    ],
)
def test_typed_inspect_rejects_unsupported_png_subset(
    values,
    kwargs,
    tmp_path,
):
    path = tmp_path / "depth.png"
    path.write_bytes(_oracle_write(values, **kwargs))
    raw_info = sceneio.inspect(path)
    assert raw_info.shape == values.shape
    with pytest.raises(sceneio.FormatError, match="grayscale uint16"):
        sceneio.inspect_depth(path, encoding=_encoding())


def test_typed_result_owns_values_after_mapping_closes_and_path_unlinks(tmp_path):
    values = np.arange(256 * 256, dtype=np.uint16).reshape(256, 256)
    path = tmp_path / "depth.png"
    path.write_bytes(_oracle_write(values))
    depth = sceneio.read_depth(path, encoding=_encoding())
    view = depth.depth

    del depth
    gc.collect()
    path.unlink()
    churn = [np.full(values.shape, index, np.float32) for index in range(32)]
    assert churn[-1][0, 0] == 31
    np.testing.assert_array_equal(view, values.astype(np.float32))


def test_typed_decode_is_isolated_from_mutable_source():
    values = np.arange(12, dtype=np.uint16).reshape(3, 4)
    source = bytearray(_oracle_write(values))
    readonly = memoryview(source).toreadonly()
    depth = _read_core(readonly)
    readonly.release()
    source[:] = b"\xff" * len(source)
    np.testing.assert_array_equal(depth.depth, values.astype(np.float32))


def test_mmap_failure_uses_same_stream_fallback(monkeypatch, tmp_path):
    values = np.arange(12, dtype=np.uint16).reshape(3, 4)
    path = tmp_path / "depth.png"
    path.write_bytes(_oracle_write(values))

    def unavailable(*args, **kwargs):
        raise OSError("mapping unavailable")

    monkeypatch.setattr("sceneio.io._registry.adapters.mmap.mmap", unavailable)
    np.testing.assert_array_equal(
        sceneio.read_depth(path, encoding=_encoding()).depth,
        values.astype(np.float32),
    )


def test_every_truncated_prefix_fails_raw_and_typed():
    encoded = _oracle_write(np.arange(12, dtype=np.uint16).reshape(3, 4))
    for stop in range(len(encoded)):
        prefix = encoded[:stop]
        with pytest.raises(ValueError):
            _core.read_png(prefix)
        with pytest.raises(ValueError):
            _read_core(prefix)


def test_random_mutations_typed_outcome_refines_raw_outcome():
    rng = np.random.default_rng(41)
    values = rng.integers(0, 65536, size=(31, 37), dtype=np.uint16)
    encoded = bytearray(_oracle_write(values))
    for _ in range(100):
        mutated = bytearray(encoded)
        index = int(rng.integers(0, len(mutated)))
        mutated[index] ^= int(rng.integers(1, 256))
        payload = bytes(mutated)
        try:
            raw = _core.read_png(payload)
        except ValueError:
            with pytest.raises(ValueError):
                _read_core(payload)
            continue
        if raw.channels == 1 and raw.dtype == "uint16":
            typed = _read_core(payload)
            np.testing.assert_array_equal(
                typed.depth,
                np.asarray(raw.pixels, dtype=np.float32),
            )
        else:
            with pytest.raises(ValueError, match="grayscale uint16"):
                _read_core(payload)


def test_random_valid_oracle_raw_typed_triangulation():
    rng = np.random.default_rng(43)
    encodings = [
        _encoding(),
        sceneio.DepthEncoding("custom", 1 / 5000, "zero"),
        sceneio.DepthEncoding("meters", 1.0, "none"),
        sceneio.DepthEncoding("unknown", 0.0, "nonfinite"),
    ]
    for index in range(50):
        height = int(rng.integers(1, 40))
        width = int(rng.integers(1, 40))
        values = rng.integers(
            0,
            65536,
            size=(height, width),
            dtype=np.uint16,
        )
        encoded = _oracle_write(values, interlace=index % 2 == 0)
        raw = _core.read_png(encoded)
        typed = _read_core(encoded, encodings[index % len(encodings)])
        np.testing.assert_array_equal(raw.pixels, values)
        np.testing.assert_array_equal(
            typed.depth,
            values.astype(np.float32),
        )


def test_large_public_paths_avoid_whole_file_python_bytes(tmp_path):
    rng = np.random.default_rng(47)
    values = rng.integers(
        0,
        65536,
        size=(2048, 4096),
        dtype=np.uint16,
    )
    depth = _depth(values)
    path = tmp_path / "large.png"
    expected = _write_core(depth)
    path.write_bytes(expected)
    file_size = path.stat().st_size
    del values
    gc.collect()

    tracemalloc.start()
    decoded = sceneio.read_depth(path, encoding=_encoding())
    _, read_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert decoded.depth.shape == (2048, 4096)
    assert read_peak < file_size / 8

    output = tmp_path / "large-output.png"
    tracemalloc.start()
    sceneio.write_depth(depth, output, encoding=_encoding())
    _, write_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert output.stat().st_size == len(expected)
    assert output.read_bytes() == expected
    assert write_peak < file_size / 8


def test_large_inspection_is_header_bounded(tmp_path):
    rng = np.random.default_rng(53)
    values = rng.integers(
        0,
        65536,
        size=(2048, 2048),
        dtype=np.uint16,
    )
    path = tmp_path / "large.png"
    path.write_bytes(_write_core(_depth(values)))

    tracemalloc.start()
    info = sceneio.inspect_depth(path, encoding=_encoding())
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.shape == values.shape
    assert info.dtype == "float32"
    assert peak < 1024 * 1024


def test_typed_sink_handles_forced_short_writes(tmp_path):
    values = np.arange(64 * 96, dtype=np.uint16).reshape(64, 96)
    encoding = _encoding()
    depth = _depth(values)
    request = (
        depth,
        encoding.unit,
        encoding.scale_to_meters,
        encoding.invalid_policy,
    )
    path = tmp_path / "short-write.png"
    calls = _core._write_to_file(
        _core._write_png_depth_request,
        request,
        path,
        _max_chunk=31,
        _test_short_write=7,
    )
    assert calls > 1
    assert path.read_bytes() == _write_core(depth)
    np.testing.assert_array_equal(_oracle_read(path.read_bytes()), values)


def test_public_capability_marker():
    assert "typed_depth_adapter" in sceneio.capabilities(
        "png"
    ).supported_features
