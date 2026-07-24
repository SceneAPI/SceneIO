"""Typed scalar OpenEXR depth over the unchanged raw Image codec."""

from __future__ import annotations

import gc
import os
import tempfile
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core

OpenEXR = pytest.importorskip("OpenEXR")


def _encoding(
    *,
    unit: str = "meters",
    scale_to_meters: float = 1.0,
    invalid_policy: str = "none",
    channel_name: str | None = "Z",
) -> sceneio.DepthEncoding:
    return sceneio.DepthEncoding(
        unit,
        scale_to_meters,
        invalid_policy,
        channel_name,
    )


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
        _core.write_exr_depth(
            depth,
            selected.unit,
            selected.scale_to_meters,
            selected.invalid_policy,
            selected.channel_name,
            _lanes=lanes,
        )
    )


def _read_core(data, encoding=None, *, lanes=0):
    selected = encoding or _encoding()
    return _core.read_exr_depth(
        data,
        selected.unit,
        selected.scale_to_meters,
        selected.invalid_policy,
        selected.channel_name,
        _lanes=lanes,
    )


def _tmp() -> str:
    handle, path = tempfile.mkstemp(suffix=".exr")
    os.close(handle)
    return path


def _oracle_write(
    channels: dict[str, np.ndarray],
    *,
    compression=None,
) -> bytes:
    header = {
        "compression": compression or OpenEXR.ZIP_COMPRESSION,
        "type": OpenEXR.scanlineimage,
    }
    contiguous = {
        name: np.ascontiguousarray(values)
        for name, values in channels.items()
    }
    path = _tmp()
    try:
        with OpenEXR.File(header, contiguous) as exr:
            exr.write(path)
        with open(path, "rb") as stream:
            return stream.read()
    finally:
        os.remove(path)


def _oracle_read(data: bytes) -> dict[str, np.ndarray]:
    path = _tmp()
    try:
        with open(path, "wb") as stream:
            stream.write(data)
        with OpenEXR.File(path) as exr:
            return {
                name: np.asarray(channel.pixels)
                for name, channel in exr.parts[0].channels.items()
            }
    finally:
        os.remove(path)


def _assert_bits_equal(actual, expected) -> None:
    np.testing.assert_array_equal(
        np.asarray(actual).view(np.uint32),
        np.asarray(expected).view(np.uint32),
    )


def _special_values() -> np.ndarray:
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
            0x7F7FFFFF,
            0x41200000,
            0xC1200000,
        ],
        dtype=np.uint32,
    ).view(np.float32).reshape(3, 4)


def _invoke_public(operation, path, encoding) -> None:
    if operation == "read":
        sceneio.read_depth(path, encoding=encoding)
    elif operation == "inspect":
        sceneio.inspect_depth(path, encoding=encoding)
    else:
        sceneio.write_depth(
            _depth(np.ones((2, 2), np.float32), encoding),
            path,
            encoding=encoding,
        )


def test_core_float_read_matches_raw_and_oracle_bit_exact():
    values = _special_values()
    encoded = _oracle_write({"Z": values})

    raw = _core.read_exr(encoded)
    typed = _read_core(memoryview(encoded))

    _assert_bits_equal(raw.pixels, values)
    _assert_bits_equal(typed.depth, values)
    assert (
        typed.unit,
        typed.scale_to_meters,
        typed.invalid_policy,
        typed.row_order,
    ) == ("meters", 1.0, "none", "top_to_bottom")


def test_core_half_read_widens_exactly_like_raw():
    values = np.array(
        [[-0.0, 0.0, 1.0, -2.0], [0.5, 65504.0, np.inf, np.nan]],
        dtype=np.float16,
    )
    encoded = _oracle_write({"Z": values})
    expected = values.astype(np.float32)

    raw = _core.read_exr(encoded)
    typed = _read_core(encoded)
    np.testing.assert_array_equal(raw.pixels, expected)
    np.testing.assert_array_equal(typed.depth, expected)
    assert np.array_equal(np.signbit(typed.depth), np.signbit(expected))


@pytest.mark.parametrize("channel_name", ["Z", "Y", "depth.Z"])
def test_typed_writer_emits_exact_requested_channel_for_oracle(channel_name):
    encoding = _encoding(channel_name=channel_name)
    values = _special_values()
    encoded = _write_core(_depth(values, encoding), encoding)
    decoded = _oracle_read(encoded)

    assert set(decoded) == {channel_name}
    _assert_bits_equal(decoded[channel_name], values)


def test_raw_scalar_writer_remains_y_and_byte_identical():
    values = _special_values()
    raw = bytes(
        _core.write_exr(
            _core.image(values, color_space="linear"),
        )
    )
    typed_y = _write_core(
        _depth(values, _encoding(channel_name="Y")),
        _encoding(channel_name="Y"),
    )

    assert typed_y == raw
    assert set(_oracle_read(raw)) == {"Y"}


def test_typed_channel_name_supports_utf8_and_255_byte_boundary(tmp_path):
    values = np.arange(6, dtype=np.float32).reshape(2, 3)
    unicode_encoding = _encoding(channel_name="depth.µ")
    unicode_path = tmp_path / "unicode.exr"
    sceneio.write_depth(
        _depth(values, unicode_encoding),
        unicode_path,
        encoding=unicode_encoding,
    )
    _assert_bits_equal(
        sceneio.read_depth(
            unicode_path,
            encoding=unicode_encoding,
        ).depth,
        values,
    )
    assert (
        sceneio.inspect_depth(
            unicode_path,
            encoding=unicode_encoding,
        ).metadata["channel_name"]
        == "depth.µ"
    )

    boundary = _encoding(channel_name="z" * 255)
    encoded = _write_core(_depth(values, boundary), boundary)
    _assert_bits_equal(_read_core(encoded, boundary).depth, values)


def test_depth_encoding_and_core_reject_overlong_channel_name():
    with pytest.raises(ValueError, match="255 UTF-8 bytes"):
        _encoding(channel_name="z" * 256)
    with pytest.raises(ValueError, match="255 UTF-8 bytes"):
        _core.write_exr_depth(
            _depth(np.ones((1, 1), np.float32)),
            "meters",
            1.0,
            "none",
            "z" * 256,
        )
    with pytest.raises(ValueError, match="valid UTF-8"):
        _encoding(channel_name="\ud800")


def test_typed_read_requires_exact_channel_but_raw_accepts_scalar():
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    encoded = _oracle_write({"distance": values})
    np.testing.assert_array_equal(_core.read_exr(encoded).pixels, values)

    with pytest.raises(ValueError, match="does not match"):
        _read_core(encoded, _encoding(channel_name="Z"))
    np.testing.assert_array_equal(
        _read_core(encoded, _encoding(channel_name="distance")).depth,
        values,
    )


def test_typed_rejects_multichannel_but_raw_rgb_is_unchanged():
    rgb = np.arange(36, dtype=np.float32).reshape(3, 4, 3)
    encoded = _oracle_write(
        {name: rgb[:, :, index] for index, name in enumerate("RGB")}
    )
    np.testing.assert_array_equal(_core.read_exr(encoded).pixels, rgb)
    with pytest.raises(ValueError, match="exactly one"):
        _read_core(encoded)


def test_typed_rejects_uint_like_raw():
    values = np.arange(12, dtype=np.uint32).reshape(3, 4)
    encoded = _oracle_write({"Z": values})
    with pytest.raises(ValueError, match=r"UINT|integer"):
        _core.read_exr(encoded)
    with pytest.raises(ValueError, match=r"UINT|integer"):
        _read_core(encoded)


@pytest.mark.parametrize("compression", ["ZIP", "ZIPS", "RLE", "PIZ", "NO"])
def test_typed_reads_all_supported_lossless_compressions(compression):
    values = (
        np.random.default_rng(20260724)
        .random((33, 19), dtype=np.float32)
        .astype(np.float32)
    )
    encoded = _oracle_write(
        {"Z": values},
        compression=getattr(OpenEXR, f"{compression}_COMPRESSION"),
    )
    _assert_bits_equal(_read_core(encoded).depth, values)


def test_typed_core_validates_external_encoding_and_metadata():
    values = np.ones((2, 3), np.float32)
    depth = _depth(values)
    with pytest.raises(ValueError, match="unit/scale"):
        _core.write_exr_depth(depth, "meters", 0.001, "none", "Z")
    with pytest.raises(ValueError, match="invalid_policy"):
        _core.read_exr_depth(
            _write_core(depth),
            "meters",
            1.0,
            "sentinel",
            "Z",
        )

    mismatch = _core.depth_map(
        values,
        unit="meters",
        invalid_policy="zero",
    )
    with pytest.raises(ValueError, match="does not match"):
        _write_core(mismatch)

    confidence = np.ones((2, 3), np.float32)
    with pytest.raises(ValueError, match="confidence"):
        _write_core(_depth(values, confidence=confidence))


def test_typed_core_lane_counts_are_byte_and_value_identical():
    values = np.random.default_rng(17).random(
        (1024, 1024), dtype=np.float32
    )
    depth = _depth(values)
    serial = _write_core(depth, lanes=1)
    parallel = _write_core(depth, lanes=0)

    assert serial == parallel
    _assert_bits_equal(
        _read_core(serial, lanes=1).depth,
        _read_core(parallel, lanes=0).depth,
    )


def test_public_read_write_inspect_and_raw_api_unchanged(tmp_path):
    values = _special_values()
    encoding = _encoding(
        unit="custom",
        scale_to_meters=1 / 5000,
        invalid_policy="nonfinite",
        channel_name="depth.Z",
    )
    path = tmp_path / "depth.exr"

    sceneio.write_depth(_depth(values, encoding), path, encoding=encoding)
    typed = sceneio.read_depth(path, encoding=encoding)
    info = sceneio.inspect_depth(path, encoding=encoding)
    raw = sceneio.read(path)

    _assert_bits_equal(typed.depth, values)
    assert isinstance(raw, _core.Image)
    _assert_bits_equal(raw.pixels, values)
    assert info.format == "exr"
    assert info.datatype == "depth_map"
    assert info.shape == values.shape
    assert info.dtype == "float32"
    assert info.channels == 1
    assert info.byte_size == path.stat().st_size
    assert dict(info.metadata) == {
        "channel_names": ("depth.Z",),
        "channel_name_encodings": ("utf8",),
        "channel_dtypes": ("float32",),
        "stored_dtype": "float32",
        "decoded_dtype": "float32",
        "row_order": "top_to_bottom",
        "unit": "custom",
        "scale_to_meters": 1 / 5000,
        "invalid_policy": "nonfinite",
        "channel_name": "depth.Z",
    }


def test_typed_inspect_reports_half_storage_without_decoding(tmp_path):
    values = np.arange(12, dtype=np.float16).reshape(3, 4)
    path = tmp_path / "half.exr"
    path.write_bytes(_oracle_write({"Z": values}))

    info = sceneio.inspect_depth(path, encoding=_encoding())
    assert info.dtype == "float32"
    assert info.metadata["stored_dtype"] == "float16"
    assert info.metadata["decoded_dtype"] == "float32"


def test_public_explicit_format_and_magic_detection_without_extension(tmp_path):
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    path = tmp_path / "depth"
    encoding = _encoding(channel_name="distance")
    sceneio.write_depth(
        _depth(values, encoding),
        path,
        encoding=encoding,
        format="exr",
    )

    _assert_bits_equal(
        sceneio.read_depth(path, encoding=encoding).depth,
        values,
    )
    assert sceneio.inspect_depth(
        path,
        encoding=encoding,
        format="exr",
    ).shape == values.shape


@pytest.mark.parametrize("operation", ["read", "inspect", "write"])
def test_exr_requires_named_depth_channel(operation, tmp_path):
    path = tmp_path / "depth.exr"
    path.write_bytes(_oracle_write({"Z": np.ones((2, 2), np.float32)}))
    encoding = _encoding(channel_name=None)
    with pytest.raises(ValueError, match=r"requires.*channel_name"):
        _invoke_public(operation, path, encoding)


def test_typed_window_rejects_before_compressed_decode(tmp_path, monkeypatch):
    path = tmp_path / "depth.exr"
    path.write_bytes(_oracle_write({"Z": np.ones((2, 3), np.float32)}))

    def must_not_decode(*args, **kwargs):
        raise AssertionError("compressed EXR should not be fully decoded")

    monkeypatch.setattr(
        "sceneio.io._depth._EXR_DEPTH_READER",
        must_not_decode,
    )
    with pytest.raises(sceneio.FormatError, match=r"does not support.*window"):
        sceneio.read_depth(
            path,
            encoding=_encoding(),
            window=(0, 1, 0, 1),
        )


def test_typed_inspect_rejects_wrong_channel_and_multichannel(tmp_path):
    wrong = tmp_path / "wrong.exr"
    wrong.write_bytes(_oracle_write({"distance": np.ones((2, 3), np.float32)}))
    with pytest.raises(sceneio.FormatError, match="selected channel"):
        sceneio.inspect_depth(wrong, encoding=_encoding())

    rgb = np.ones((2, 3, 3), np.float32)
    multi = tmp_path / "multi.exr"
    multi.write_bytes(
        _oracle_write(
            {name: rgb[:, :, index] for index, name in enumerate("RGB")}
        )
    )
    with pytest.raises(sceneio.FormatError, match="selected channel"):
        sceneio.inspect_depth(multi, encoding=_encoding())


def test_typed_inspect_rejects_non_utf8_stored_channel_name(tmp_path):
    encoded = bytearray(
        _oracle_write({"Z": np.ones((2, 3), np.float32)})
    )
    channel_list = encoded.index(b"channels\x00chlist\x00")
    channel_name = encoded.index(b"Z\x00", channel_list)
    encoded[channel_name] = 0xFF
    path = tmp_path / "non-utf8-channel.exr"
    path.write_bytes(encoded)

    raw_info = sceneio.inspect(path)
    assert raw_info.metadata["channel_names"] == ("ÿ",)
    assert raw_info.metadata["channel_name_encodings"] == ("latin1",)
    with pytest.raises(sceneio.FormatError, match="not valid UTF-8"):
        sceneio.inspect_depth(
            path,
            encoding=_encoding(channel_name="ÿ"),
        )
    with pytest.raises(ValueError, match="does not match"):
        _read_core(
            bytes(encoded),
            _encoding(channel_name="ÿ"),
        )


def test_public_writer_guards_before_destination_truncation(tmp_path):
    path = tmp_path / "depth.exr"
    path.write_bytes(b"keep")
    mismatch = _core.depth_map(
        np.ones((2, 2), np.float32),
        unit="meters",
        invalid_policy="zero",
    )
    with pytest.raises(sceneio.FormatError, match="does not match"):
        sceneio.write_depth(mismatch, path, encoding=_encoding())
    assert path.read_bytes() == b"keep"

    confidence = np.ones((2, 2), np.float32)
    with pytest.raises(sceneio.FormatError, match="confidence"):
        sceneio.write_depth(
            _depth(np.ones((2, 2)), confidence=confidence),
            path,
            encoding=_encoding(),
        )
    assert path.read_bytes() == b"keep"


def test_public_rejects_wrong_object_without_touching_destination(tmp_path):
    path = tmp_path / "depth.exr"
    path.write_bytes(b"keep")
    with pytest.raises(TypeError, match="DepthMap"):
        sceneio.write_depth(
            np.ones((2, 2), np.float32),
            path,
            encoding=_encoding(),
        )
    assert path.read_bytes() == b"keep"


def test_result_and_view_outlive_mapping_and_path(tmp_path):
    values = np.arange(256 * 256, dtype=np.float32).reshape(256, 256)
    path = tmp_path / "depth.exr"
    path.write_bytes(_oracle_write({"Z": values}))
    depth = sceneio.read_depth(path, encoding=_encoding())
    view = depth.depth

    del depth
    gc.collect()
    path.unlink()
    churn = [np.full(values.shape, index, np.float32) for index in range(32)]
    assert churn[-1][0, 0] == 31
    _assert_bits_equal(view, values)


def test_typed_decode_is_isolated_from_mutable_source():
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    source = bytearray(_oracle_write({"Z": values}))
    readonly = memoryview(source).toreadonly()
    depth = _read_core(readonly)
    readonly.release()
    source[:] = b"\xff" * len(source)
    _assert_bits_equal(depth.depth, values)


def test_mmap_failure_uses_stream_fallback(monkeypatch, tmp_path):
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    path = tmp_path / "depth.exr"
    path.write_bytes(_oracle_write({"Z": values}))

    def unavailable(*args, **kwargs):
        raise OSError("mapping unavailable")

    monkeypatch.setattr("sceneio.io.registry.mmap.mmap", unavailable)
    _assert_bits_equal(
        sceneio.read_depth(path, encoding=_encoding()).depth,
        values,
    )


def test_every_truncated_prefix_fails_raw_and_typed():
    encoded = _oracle_write(
        {"Z": np.arange(12, dtype=np.float32).reshape(3, 4)}
    )
    for stop in range(len(encoded)):
        prefix = encoded[:stop]
        with pytest.raises(ValueError):
            _core.read_exr(prefix)
        with pytest.raises(ValueError):
            _read_core(prefix)


def test_random_mutations_typed_acceptance_refines_raw_acceptance():
    rng = np.random.default_rng(23)
    values = rng.random((31, 37), dtype=np.float32)
    encoded = bytearray(_oracle_write({"Z": values}))
    for _ in range(100):
        mutated = bytearray(encoded)
        index = int(rng.integers(0, len(mutated)))
        mutated[index] ^= int(rng.integers(1, 256))
        payload = bytes(mutated)
        try:
            raw = _core.read_exr(payload)
        except ValueError:
            with pytest.raises(ValueError):
                _read_core(payload)
            continue
        try:
            typed = _read_core(payload)
        except ValueError:
            continue
        _assert_bits_equal(typed.depth, raw.pixels)


def test_random_valid_oracle_raw_typed_triangulation():
    rng = np.random.default_rng(29)
    encodings = [
        _encoding(),
        _encoding(
            unit="custom",
            scale_to_meters=1 / 5000,
            invalid_policy="zero",
        ),
        _encoding(
            unit="millimeters",
            scale_to_meters=0.001,
            invalid_policy="negative",
        ),
        _encoding(
            unit="unknown",
            scale_to_meters=0.0,
            invalid_policy="nonfinite",
        ),
    ]
    compressions = [
        OpenEXR.ZIP_COMPRESSION,
        OpenEXR.ZIPS_COMPRESSION,
        OpenEXR.RLE_COMPRESSION,
        OpenEXR.PIZ_COMPRESSION,
        OpenEXR.NO_COMPRESSION,
    ]
    for index in range(50):
        height = int(rng.integers(1, 40))
        width = int(rng.integers(1, 40))
        values = rng.standard_normal((height, width), dtype=np.float32)
        encoding = encodings[index % len(encodings)]
        encoded = _oracle_write(
            {encoding.channel_name: values},
            compression=compressions[index % len(compressions)],
        )
        raw = _core.read_exr(encoded)
        typed = _read_core(encoded, encoding)
        _assert_bits_equal(raw.pixels, values)
        _assert_bits_equal(typed.depth, values)


def test_dimension_bomb_rejected_before_typed_decode():
    data = bytearray(_write_core(_depth(np.ones((8, 8), np.float32))))
    marker = b"dataWindow\x00box2i\x00"
    offset = data.index(marker) + len(marker) + 4
    data[offset + 8 : offset + 12] = (60000).to_bytes(
        4, "little", signed=True
    )
    data[offset + 12 : offset + 16] = (60000).to_bytes(
        4, "little", signed=True
    )
    with pytest.raises(ValueError, match=r"exceed|limit"):
        _read_core(bytes(data))


def test_deep_multipart_and_tiled_flags_reject_in_typed_preflight():
    valid = bytearray(_write_core(_depth(np.ones((8, 8), np.float32))))
    for bit, word in [(0x08, "deep"), (0x10, "multipart"), (0x02, "tiled")]:
        mutated = bytearray(valid)
        mutated[5] |= bit
        with pytest.raises(ValueError, match=word):
            _read_core(bytes(mutated))


def test_large_public_paths_avoid_whole_file_python_bytes(tmp_path):
    values = np.random.default_rng(31).random(
        (2048, 4096), dtype=np.float32
    )
    depth = _depth(values)
    path = tmp_path / "large.exr"
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

    output = tmp_path / "large-output.exr"
    tracemalloc.start()
    sceneio.write_depth(depth, output, encoding=_encoding())
    _, write_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert output.stat().st_size == len(expected)
    assert output.read_bytes() == expected
    assert write_peak < file_size / 8


def test_large_inspection_is_header_bounded(tmp_path):
    values = np.random.default_rng(37).random(
        (2048, 2048), dtype=np.float32
    )
    path = tmp_path / "large.exr"
    path.write_bytes(_write_core(_depth(values)))

    tracemalloc.start()
    info = sceneio.inspect_depth(path, encoding=_encoding())
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.shape == values.shape
    assert info.dtype == "float32"
    assert peak < 1024 * 1024


def test_typed_sink_handles_forced_short_writes(tmp_path):
    values = np.arange(64 * 96, dtype=np.float32).reshape(64, 96)
    encoding = _encoding(channel_name="distance")
    depth = _depth(values, encoding)
    request = (
        depth,
        encoding.unit,
        encoding.scale_to_meters,
        encoding.invalid_policy,
        encoding.channel_name,
    )
    path = tmp_path / "short-write.exr"
    calls = _core._write_to_file(
        _core._write_exr_depth_request,
        request,
        path,
        _max_chunk=31,
        _test_short_write=7,
    )
    assert calls > 1
    assert path.read_bytes() == _write_core(depth, encoding)
    _assert_bits_equal(
        _oracle_read(path.read_bytes())["distance"],
        values,
    )


def test_private_sink_request_validates_arity():
    with pytest.raises(ValueError, match="five values"):
        _core._write_exr_depth_request(())


def test_public_capability_marker():
    capabilities = sceneio.capabilities("exr")
    assert "typed_depth_adapter" in capabilities.supported_features
    assert "half_to_float" in capabilities.supported_features
