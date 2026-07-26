"""Parity, malformed-input, mmap-lifetime, partial-read, and sink tests."""

from __future__ import annotations

import gc
import json
import mmap
import os
import struct
import subprocess
import sys
import tracemalloc

import numpy as np
import pytest
from safetensors.numpy import load as oracle_load
from safetensors.numpy import save as oracle_save

import sceneio
from sceneio import _core

DTYPES = (
    np.bool_,
    np.int8,
    np.int16,
    np.int32,
    np.int64,
    np.uint8,
    np.uint16,
    np.uint32,
    np.uint64,
    np.float16,
    np.float32,
    np.float64,
)
SHAPES = ((), (0,), (7,), (2, 3), (2, 0, 3))


def _values(dtype, shape):
    dtype = np.dtype(dtype)
    size = int(np.prod(shape, dtype=np.int64)) if shape else 1
    if dtype.kind == "b":
        values = np.arange(size, dtype=np.uint8) % 2 == 0
    elif dtype.kind == "f":
        values = (np.arange(size, dtype=np.float64) - 2.5).astype(dtype)
    else:
        values = (np.arange(size, dtype=np.int64) - 2).astype(dtype)
    return values.reshape(shape)


def _assert_tensor_dict(actual, expected, *, keys=None, attrs=None):
    expected_keys = tuple(expected) if keys is None else tuple(keys)
    assert tuple(actual.keys()) == expected_keys
    assert actual.attrs == ({} if attrs is None else attrs)
    for name in expected_keys:
        value = np.asarray(actual[name])
        reference = expected[name]
        assert value.dtype == reference.dtype
        assert value.shape == reference.shape
        assert value.tobytes() == reference.tobytes()


def _encoded_header(header, payload=b"", *, pad=True):
    if isinstance(header, dict):
        header = json.dumps(
            header, ensure_ascii=False, separators=(",", ":")
        ).encode()
    if pad:
        header += b" " * (-len(header) % 8)
    return struct.pack("<Q", len(header)) + header + payload


def _single_descriptor(
    *,
    dtype="F32",
    shape=(1,),
    offsets=(0, 4),
    extra=None,
):
    value = {
        "dtype": dtype,
        "shape": list(shape),
        "data_offsets": list(offsets),
    }
    if extra is not None:
        value["extra"] = extra
    return {"x": value}


@pytest.mark.parametrize("dtype", DTYPES)
@pytest.mark.parametrize("shape", SHAPES)
def test_oracle_write_sceneio_read_all_supported_dtypes(dtype, shape):
    array = _values(dtype, shape)
    actual = _core.read_safetensors(oracle_save({"x": array}))
    _assert_tensor_dict(actual, {"x": array})


@pytest.mark.parametrize("dtype", DTYPES)
@pytest.mark.parametrize("shape", SHAPES)
def test_sceneio_write_oracle_read_all_supported_dtypes(dtype, shape):
    array = _values(dtype, shape)
    encoded = bytes(
        _core.write_safetensors(_core.tensor_dict({"x": array}))
    )
    actual = oracle_load(encoded)
    assert actual["x"].dtype == array.dtype
    assert actual["x"].shape == array.shape
    assert actual["x"].tobytes() == array.tobytes()


def test_roundtrip_metadata_unicode_and_embedded_nul_names():
    arrays = {
        "weight\0one": np.arange(12, dtype=np.float32).reshape(3, 4),
        "δ": np.arange(5, dtype=np.uint16),
    }
    attrs = {"author": "SceneIO", "unicode": "λ", "nul": "a\0b"}
    encoded = bytes(
        _core.write_safetensors(_core.tensor_dict(arrays, attrs))
    )
    actual = _core.read_safetensors(encoded)
    _assert_tensor_dict(actual, arrays, keys=("weight\0one", "δ"), attrs=attrs)
    oracle = oracle_load(encoded)
    for name, value in arrays.items():
        np.testing.assert_array_equal(oracle[name], value)


def test_writer_matches_oracle_canonical_bytes():
    arrays = {
        "z": np.array([1], np.uint8),
        "a": np.array([2], np.float64),
        "b": np.array([3], np.int16),
        "empty": np.empty((0, 3), np.float32),
        "scalar": np.array(4, np.int32),
    }
    actual = bytes(
        _core.write_safetensors(_core.tensor_dict(arrays))
    )
    assert actual == oracle_save(arrays)


def test_writer_golden_and_empty_container():
    expected = (
        b"8\0\0\0\0\0\0\0"
        b'{"x":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}  '
        b"\0\0\x80?"
    )
    assert (
        bytes(
            _core.write_safetensors(
                _core.tensor_dict({"x": np.array([1], np.float32)})
            )
        )
        == expected
    )
    assert bytes(_core.write_safetensors(_core.tensor_dict({}))) == (
        b"\x08\0\0\0\0\0\0\0{}      "
    )


def test_writer_is_deterministic_across_input_and_metadata_order():
    a = np.arange(4, dtype=np.float32)
    b = np.arange(3, dtype=np.int16)
    first = _core.tensor_dict(
        {"b": b, "a": a}, {"z": "last", "a": "first"}
    )
    second = _core.tensor_dict(
        {"a": a, "b": b}, {"a": "first", "z": "last"}
    )
    assert bytes(_core.write_safetensors(first)) == bytes(
        _core.write_safetensors(second)
    )


def test_writer_rejects_reserved_tensor_name():
    record = _core.tensor_dict(
        {"__metadata__": np.arange(2, dtype=np.uint8)}
    )
    with pytest.raises(ValueError, match="reserved"):
        _core.write_safetensors(record)


def test_inspector_matches_decoded_arrays_and_metadata():
    arrays = {
        "x": np.arange(12, dtype=np.float32).reshape(3, 4),
        "scalar": np.array(7, np.int64),
        "empty": np.empty((2, 0), np.uint8),
    }
    data = oracle_save(arrays, metadata={"kind": "fixture"})
    inspected, attrs = _core._inspect_safetensors(data)
    decoded = _core.read_safetensors(data)
    assert attrs == {"kind": "fixture"}
    assert tuple(
        (name, tuple(shape), dtype) for name, shape, dtype in inspected
    ) == tuple(
        (name, decoded[name].shape, decoded[name].dtype.name)
        for name in decoded
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "8-byte"),
        (b"\0" * 7, "8-byte"),
        (struct.pack("<Q", 100_000_001), "100,000,000"),
        (struct.pack("<Q", 0), "truncated"),
        (struct.pack("<Q", 8) + b"[]      ", "begin with"),
        (struct.pack("<Q", 8) + b"{bad}   ", "invalid"),
        (
            _encoded_header(b'{"x":\xff}'),
            "invalid",
        ),
        (
            _encoded_header({"__metadata__": []}),
            "__metadata__",
        ),
        (
            _encoded_header({"__metadata__": {"x": 1}}),
            "values must be strings",
        ),
        (
            _encoded_header({"x": {"dtype": "F32"}}),
            "exactly",
        ),
        (
            _encoded_header(
                _single_descriptor(extra="not representable"),
                b"\0" * 4,
            ),
            "exactly",
        ),
        (
            _encoded_header(_single_descriptor(dtype="BF16"), b"\0" * 2),
            "unsupported dtype",
        ),
        (
            _encoded_header(_single_descriptor(shape=(-1,), offsets=(0, 4))),
            "unsigned integer",
        ),
        (
            _encoded_header(
                _single_descriptor(shape=(1.5,), offsets=(0, 4))
            ),
            "unsigned integer",
        ),
        (
            _encoded_header(_single_descriptor(offsets=(4, 0)), b"\0" * 4),
            "outside",
        ),
        (
            _encoded_header(_single_descriptor(offsets=(0, 5)), b"\0" * 5),
            "disagrees",
        ),
        (
            _encoded_header(_single_descriptor(offsets=(0, 4)), b"\0" * 3),
            "outside",
        ),
        (
            _encoded_header(_single_descriptor(offsets=(0, 4)), b"\0" * 5),
            "complete payload",
        ),
        (
            _encoded_header(
                {
                    "a": {
                        "dtype": "U8",
                        "shape": [2],
                        "data_offsets": [0, 2],
                    },
                    "b": {
                        "dtype": "U8",
                        "shape": [2],
                        "data_offsets": [3, 5],
                    },
                },
                b"\0" * 5,
            ),
            "gap",
        ),
        (
            _encoded_header(
                {
                    "a": {
                        "dtype": "U8",
                        "shape": [3],
                        "data_offsets": [0, 3],
                    },
                    "b": {
                        "dtype": "U8",
                        "shape": [2],
                        "data_offsets": [2, 4],
                    },
                },
                b"\0" * 4,
            ),
            "overlap",
        ),
    ],
)
def test_malformed_inputs_reject_consistently(data, message):
    for reader in (
        _core.read_safetensors,
        _core.read_safetensors_view,
        _core._inspect_safetensors,
    ):
        with pytest.raises(ValueError, match=message):
            reader(data)


@pytest.mark.parametrize(
    "header",
    [
        b'{"x":{"dtype":"U8","shape":[1],"data_offsets":[0,1]},'
        b'"x":{"dtype":"U8","shape":[1],"data_offsets":[0,1]}}       ',
        b'{"x":{"dtype":"U8","dtype":"U8","shape":[1],'
        b'"data_offsets":[0,1]}}       ',
        b'{"__metadata__":{"x":"a","x":"b"}}       ',
    ],
)
def test_duplicate_json_keys_reject(header):
    header += b" " * (-len(header) % 8)
    data = struct.pack("<Q", len(header)) + header + b"\0"
    with pytest.raises(ValueError, match="duplicate JSON key"):
        _core.read_safetensors(data)


def test_unaligned_payload_falls_back_to_owned_storage():
    # The format accepts a non-padded JSON header, but a float64 payload at an
    # unaligned absolute address cannot become a portable ndarray view.
    header = json.dumps(
        _single_descriptor(dtype="F64", offsets=(0, 8)),
        separators=(",", ":"),
    ).encode()
    while (8 + len(header)) % 8 == 0:
        header += b" "
    data = _encoded_header(
        header, np.array([1.5], np.float64).tobytes(), pad=False
    )
    actual = _core.read_safetensors_view(data)
    array = actual["x"]
    assert type(array) is np.ndarray
    assert array.flags.writeable
    np.testing.assert_array_equal(array, np.array([1.5], np.float64))


def test_direct_mapped_view_aliases_and_pins_exporter(tmp_path):
    arrays = {"x": np.arange(30, dtype=np.float32).reshape(5, 6)}
    path = tmp_path / "alias.safetensors"
    path.write_bytes(oracle_save(arrays))
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        base = _core._buffer_address(mapped)
        header_size = struct.unpack("<Q", mapped[:8])[0]
        header = json.loads(mapped[8 : 8 + header_size])
        payload_offset = 8 + header_size
        tensor_offset = header["x"]["data_offsets"][0]
        record = _core.read_safetensors_view(mapped)

    array = record["x"]
    assert (
        array.__array_interface__["data"][0]
        == base + payload_offset + tensor_offset
    )
    assert type(array).__name__ == "_MappedArray"
    assert type(array.base).__name__ == "_PinnedBuffer"
    assert not array.flags.writeable
    with pytest.raises(BufferError):
        mapped.close()
    del record
    gc.collect()
    with pytest.raises(BufferError):
        mapped.close()
    np.testing.assert_array_equal(array, arrays["x"])
    del array
    gc.collect()
    mapped.close()


def test_public_mapped_record_and_array_lifetimes(tmp_path):
    arrays = {
        "x": np.arange(30, dtype=np.float32).reshape(5, 6),
        "y": np.arange(7, dtype=np.int16),
    }
    path = tmp_path / "lifetime.safetensors"
    path.write_bytes(oracle_save(arrays))
    record = sceneio.read(path)
    array = record["x"]
    del record
    gc.collect()
    np.testing.assert_array_equal(array, arrays["x"])
    with pytest.raises(ValueError):
        array[0, 0] = 99
    with pytest.raises(ValueError):
        array.setflags(write=True)
    del array
    gc.collect()
    path.unlink()


def test_mapped_record_reencodes_to_safetensors_and_npz(tmp_path):
    arrays = {
        "x": np.arange(30, dtype=np.float32).reshape(5, 6),
        "y": np.arange(7, dtype=np.int16),
    }
    source = tmp_path / "source.safetensors"
    source.write_bytes(oracle_save(arrays))
    mapped = sceneio.read(source)

    safe_copy = tmp_path / "copy.safetensors"
    sceneio.write(mapped, safe_copy)
    for name, expected in arrays.items():
        np.testing.assert_array_equal(
            oracle_load(safe_copy.read_bytes())[name], expected
        )

    npz_copy = tmp_path / "copy.npz"
    sceneio.write(mapped, npz_copy)
    copied = sceneio.read(npz_copy)
    for name, expected in arrays.items():
        np.testing.assert_array_equal(copied[name], expected)


def test_mapped_tensor_dlpack_is_an_isolated_copy(tmp_path):
    path = tmp_path / "dlpack.safetensors"
    expected = np.arange(12, dtype=np.float32).reshape(3, 4)
    path.write_bytes(oracle_save({"x": expected}))
    array = sceneio.read(path)["x"]
    with pytest.raises(BufferError):
        array.__dlpack__(copy=False)
    copied = np.from_dlpack(array)
    np.testing.assert_array_equal(copied, expected)
    assert not np.shares_memory(copied, array)
    del array, copied
    gc.collect()


def test_selected_tensors_and_leading_axis_slices(tmp_path):
    arrays = {
        "x": np.arange(60, dtype=np.float32).reshape(10, 6),
        "y": np.arange(12, dtype=np.int16),
        "scalar": np.array(7, np.int64),
        "zero_tail": np.empty((5, 0, 3), np.uint8),
    }
    path = tmp_path / "partial.safetensors"
    path.write_bytes(oracle_save(arrays, metadata={"kind": "partial"}))

    selected = sceneio.read_partial(path, tensors=("y", "x"))
    _assert_tensor_dict(
        selected,
        arrays,
        keys=("y", "x"),
        attrs={"kind": "partial"},
    )
    assert not selected["x"].flags.writeable

    sliced = sceneio.read_partial(
        path, slices={"x": (2, 7), "zero_tail": (1, 4)}
    )
    expected = {"x": arrays["x"][2:7], "zero_tail": arrays["zero_tail"][1:4]}
    _assert_tensor_dict(
        sliced,
        expected,
        attrs={"kind": "partial"},
    )
    assert not sliced["x"].flags.writeable


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {"tensors": ("x",)},
            np.arange(60, dtype=np.float32).reshape(10, 6),
        ),
        (
            {"slices": {"x": (2, 8)}},
            np.arange(60, dtype=np.float32).reshape(10, 6)[2:8],
        ),
    ],
    ids=("tensors", "slices"),
)
def test_selected_view_outlives_record_and_releases_path(
    tmp_path,
    kwargs,
    expected,
):
    path = tmp_path / "selected-lifetime.safetensors"
    path.write_bytes(
        oracle_save(
            {
                "x": np.arange(60, dtype=np.float32).reshape(10, 6),
                "other": np.arange(7, dtype=np.int16),
            }
        )
    )

    record = sceneio.read_partial(path, **kwargs)
    array = record["x"]
    derived = array[1:-1]
    assert type(array).__name__ == "_MappedArray"
    assert type(array.base).__name__ == "_PinnedBuffer"
    assert not array.flags.writeable
    with pytest.raises(ValueError):
        derived.flat[0] = 99
    with pytest.raises(ValueError):
        derived.setflags(write=True)

    del record, array
    gc.collect()
    np.testing.assert_array_equal(derived, expected[1:-1])
    if sys.platform == "win32":
        with pytest.raises(PermissionError):
            path.unlink()

    del derived
    gc.collect()
    path.unlink()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tensors": ("missing",)},
        {"slices": {"x": (0, 99)}},
    ],
    ids=("tensors", "slices"),
)
def test_invalid_selected_read_releases_mapping_while_exception_is_retained(
    tmp_path,
    kwargs,
):
    path = tmp_path / "selected-error.safetensors"
    path.write_bytes(
        oracle_save({"x": np.arange(12, dtype=np.float32).reshape(3, 4)})
    )
    caught = None
    try:
        sceneio.read_partial(path, **kwargs)
    except sceneio.FormatError as exc:
        caught = exc
    assert caught is not None
    assert caught.__cause__ is not None
    gc.collect()
    path.unlink()


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"tensors": ()}, ValueError, "at least one"),
        ({"tensors": "x"}, TypeError, "iterable"),
        ({"tensors": ("x", "x")}, ValueError, "unique"),
        ({"tensors": (1,)}, TypeError, "strings"),
        ({"tensors": ("missing",)}, sceneio.FormatError, "not found"),
        ({"slices": {}}, ValueError, "at least one"),
        ({"slices": (("x", (0, 1)),)}, TypeError, "mapping"),
        ({"slices": {1: (0, 1)}}, TypeError, "names"),
        ({"slices": {"x": (0,)}}, ValueError, "exactly 2"),
        ({"slices": {"x": (-1, 1)}}, ValueError, "0 <= start"),
        ({"slices": {"x": (1, 1)}}, ValueError, "0 <= start"),
        ({"slices": {"x": (0, 99)}}, sceneio.FormatError, "outside"),
        (
            {"slices": {"scalar": (0, 1)}},
            sceneio.FormatError,
            "no leading axis",
        ),
    ],
)
def test_partial_selector_validation(tmp_path, kwargs, error, message):
    path = tmp_path / "selectors.safetensors"
    path.write_bytes(
        oracle_save(
            {
                "x": np.arange(12, dtype=np.float32).reshape(3, 4),
                "scalar": np.array(1, np.int32),
            }
        )
    )
    with pytest.raises(error, match=message):
        sceneio.read_partial(path, **kwargs)


def test_selector_families_are_mutually_exclusive(tmp_path):
    path = tmp_path / "exclusive.safetensors"
    path.write_bytes(oracle_save({"x": np.arange(3, dtype=np.uint8)}))
    with pytest.raises(ValueError, match="exactly one"):
        sceneio.read_partial(path, tensors=("x",), slices={"x": (0, 1)})


def test_direct_empty_partial_selections_reject():
    data = oracle_save({"x": np.arange(3, dtype=np.uint8)})
    for reader in (
        _core.read_safetensors_tensors,
        _core.read_safetensors_tensors_view,
        _core.read_safetensors_slices,
        _core.read_safetensors_slices_view,
    ):
        with pytest.raises(ValueError, match="must not be empty"):
            reader(data, [])


def test_file_sink_is_byte_identical_and_handles_short_writes(tmp_path):
    record = _core.tensor_dict(
        {
            "x": np.arange(120, dtype=np.float32).reshape(20, 6),
            "y": np.arange(9, dtype=np.int16),
        },
        {"kind": "sink"},
    )
    expected = bytes(_core.write_safetensors(record))
    path = tmp_path / "sink.safetensors"
    calls = _core._write_to_file(
        _core.write_safetensors,
        record,
        path,
        _max_chunk=7,
        _test_short_write=3,
    )
    assert calls > 3
    assert path.read_bytes() == expected
    public = tmp_path / "public.safetensors"
    sceneio.write(record, public)
    assert public.read_bytes() == expected


def test_public_full_and_selected_reads_have_bounded_traced_memory(tmp_path):
    large = np.arange(8 * 1024 * 1024, dtype=np.float32)
    small = np.arange(1024, dtype=np.int16)
    path = tmp_path / "large.safetensors"
    sceneio.write({"large": large, "small": small}, path)

    peaks = []
    for operation in (
        lambda: sceneio.read(path),
        lambda: sceneio.read_partial(path, tensors=("small",)),
        lambda: sceneio.read_partial(path, slices={"large": (0, 1024)}),
        lambda: sceneio.inspect(path),
    ):
        gc.collect()
        tracemalloc.start()
        try:
            value = operation()
            _, peak = tracemalloc.get_traced_memory()
            peaks.append(peak)
            del value
        finally:
            tracemalloc.stop()
    assert max(peaks) < 2 * 1024 * 1024


def test_mapped_full_and_selected_reads_have_bounded_rss(tmp_path):
    if os.environ.get("ASAN_OPTIONS") or "libasan" in os.environ.get(
        "LD_PRELOAD", ""
    ):
        pytest.skip("RSS measurements include AddressSanitizer shadow memory")
    large = np.arange(16 * 1024 * 1024, dtype=np.float32)
    path = tmp_path / "rss.safetensors"
    sceneio.write(
        {"large": large, "small": np.arange(1024, dtype=np.int16)},
        path,
    )
    script = """
import gc
import sys
import threading
import time
import psutil
import sceneio

sceneio.capabilities("safetensors")  # load the extension before the RSS baseline
process = psutil.Process()
gc.collect()
baseline = process.memory_info().rss
peak = [baseline]
running = [True]

def sample():
    while running[0]:
        peak[0] = max(peak[0], process.memory_info().rss)
        time.sleep(0.0005)

thread = threading.Thread(target=sample, daemon=True)
thread.start()
try:
    if sys.argv[2] == "full":
        value = sceneio.read(sys.argv[1], format="safetensors")
    else:
        value = sceneio.read_partial(
            sys.argv[1], format="safetensors", tensors=("small",)
        )
    assert int(value["small"].sum()) == 523776
    peak[0] = max(peak[0], process.memory_info().rss)
    del value
finally:
    running[0] = False
    thread.join()
print(max(0, peak[0] - baseline))
"""
    for mode in ("full", "selected"):
        completed = subprocess.run(
            [sys.executable, "-c", script, str(path), mode],
            check=True,
            capture_output=True,
            text=True,
        )
        assert int(completed.stdout) < 8 * 1024 * 1024


def test_random_single_byte_mutations_match_copy_view_and_oracle():
    arrays = {
        "x": np.arange(64, dtype=np.float32).reshape(8, 8),
        "y": np.arange(17, dtype=np.int16),
    }
    valid = oracle_save(arrays, metadata={"kind": "mutation"})
    rng = np.random.default_rng(20260724)

    def outcome(reader, data):
        try:
            value = reader(data)
        except Exception:
            return ("error",)
        if isinstance(value, sceneio.TensorDict):
            return (
                "ok",
                tuple(
                    (
                        name,
                        value[name].dtype.str,
                        value[name].shape,
                        value[name].tobytes(),
                    )
                    for name in sorted(value.keys())
                ),
            )
        return (
            "ok",
            tuple(
                (
                    name,
                    value[name].dtype.str,
                    value[name].shape,
                    value[name].tobytes(),
                )
                for name in sorted(value)
            ),
        )

    for _ in range(100):
        mutated = bytearray(valid)
        index = int(rng.integers(0, len(mutated)))
        mutated[index] ^= int(rng.integers(1, 256))
        payload = bytes(mutated)
        copy = outcome(_core.read_safetensors, payload)
        view = outcome(_core.read_safetensors_view, payload)
        oracle = outcome(oracle_load, payload)
        assert copy == view
        assert copy[0] == oracle[0]
        if copy[0] == "ok":
            assert copy == oracle
