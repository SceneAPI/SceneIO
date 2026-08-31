"""O2 zero-copy decode coverage for the raw NPY format."""

from __future__ import annotations

import gc
import io
import mmap
import subprocess
import sys
import tracemalloc
from dataclasses import dataclass

import numpy as np
import pytest

import sceneio
from sceneio import _core


@dataclass(frozen=True)
class RawCase:
    id: str
    value: np.ndarray
    data: bytes
    copy_reader: object
    view_reader: object


def _raw_cases():
    tensor = np.arange(3 * 8, dtype=np.int32).reshape(3, 8)
    return [
        RawCase("npy", tensor, bytes(_core.write_npy(tensor)), _core.read_npy, _core.read_npy_view),
    ]


@pytest.fixture(params=_raw_cases(), ids=lambda case: case.id)
def raw_case(request):
    return request.param


def _npy_data_offset(data):
    if data[6] == 1:
        return 10 + int.from_bytes(data[8:10], "little")
    return 12 + int.from_bytes(data[8:12], "little")


def _pfm_data_offset(data):
    pos = 0
    for _ in range(3):
        pos = data.index(b"\n", pos) + 1
    return pos


def _logical_data_offset(case):
    if case.id == "npy":
        return _npy_data_offset(case.data)
    raise AssertionError(f"unknown raw view format {case.id}")


def _fingerprint(array):
    value = np.asarray(array)
    return value.dtype.str, value.shape, value.tobytes(order="C")


def _outcome(reader, data):
    try:
        return "ok", _fingerprint(reader(data))
    except Exception as exc:
        return "error", type(exc), str(exc)


def _assert_mutation_equivalence(data, copy_reader, view_reader):
    rng = np.random.default_rng(713)
    for case in range(40):
        mutated = bytearray(data)
        operation = case % 4
        if operation == 0:
            mutated = mutated[: int(rng.integers(0, len(mutated) + 1))]
        elif operation == 1 and mutated:
            for index in rng.integers(0, len(mutated), min(4, len(mutated))):
                mutated[int(index)] ^= int(rng.integers(1, 256))
        elif operation == 2:
            mutated.extend(rng.integers(0, 256, 7, dtype=np.uint8).tobytes())
        elif mutated:
            start = int(rng.integers(0, len(mutated)))
            del mutated[start : start + int(rng.integers(1, 9))]
        payload = bytes(mutated)
        assert _outcome(view_reader, payload) == _outcome(copy_reader, payload), (
            case,
            operation,
        )


def test_raw_view_is_bit_exact_and_aliases_mmap(tmp_path, raw_case):
    path = tmp_path / f"raw.{raw_case.id}"
    path.write_bytes(raw_case.data)
    expected = raw_case.copy_reader(raw_case.data)
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        address = _core._buffer_address(mapped)
        actual = raw_case.view_reader(mapped)

    assert _fingerprint(actual) == _fingerprint(expected)
    assert actual.__array_interface__["data"][0] == address + _logical_data_offset(raw_case)
    assert actual.flags.owndata is False
    assert actual.flags.writeable is False
    assert type(actual).__name__ == "_MappedArray"
    assert type(actual.base).__name__ == "_PinnedBuffer"
    assert not hasattr(actual.base, "close")
    assert not hasattr(actual.base, "release")

    # The retained Py_buffer export mechanically prevents an early unmap.
    with pytest.raises(BufferError):
        mapped.close()
    derived = actual[..., :1]
    del actual
    gc.collect()
    with pytest.raises(BufferError):
        mapped.close()
    assert _fingerprint(derived) == _fingerprint(np.asarray(expected)[..., :1])
    del derived
    gc.collect()
    mapped.close()


def test_raw_view_mutations_match_copy_decoder(raw_case):
    _assert_mutation_equivalence(
        raw_case.data, raw_case.copy_reader, raw_case.view_reader
    )


def test_view_owner_type_cannot_be_invalidated_through_module_attributes():
    script = """
import numpy as np
from sceneio import _core
_core._PinnedBuffer = object()
del _core._PinnedBuffer
npy = np.arange(8, dtype=np.int32)
for expected, data, reader in (
    (npy, _core.write_npy(npy), _core.read_npy_view),
):
    actual = reader(data)
    np.testing.assert_array_equal(actual, expected)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_mapped_array_dlpack_requests_an_isolated_copy(tmp_path, raw_case):
    path = tmp_path / f"copy.{raw_case.id}"
    path.write_bytes(raw_case.data)
    actual = sceneio.read(path)
    with pytest.raises(BufferError):
        actual.__dlpack__(copy=False)
    copied = np.from_dlpack(actual)
    np.testing.assert_array_equal(copied, raw_case.value)
    assert not np.shares_memory(copied, actual)
    del actual, copied
    gc.collect()


def test_torch_writable_interop_cannot_crash_or_mutate_files(tmp_path):
    pytest.importorskip("torch")
    script = """
import sys
import warnings
from pathlib import Path
import numpy as np
import torch
import sceneio
from sceneio import _core
root = Path(sys.argv[1])
values = {
    "npy": np.arange(12, dtype=np.int32).reshape(3, 4),
    "pfm": np.arange(18, dtype=np.float32).reshape(2, 3, 3),
}
writers = {"npy": _core.write_npy, "pfm": _core.write_pfm}
for format_id, expected in values.items():
    path = root / ("mapped." + format_id)
    encoded = bytes(writers[format_id](expected))
    path.write_bytes(encoded)
    actual = sceneio.read(path, format=format_id)
    snapshot = np.array(actual, copy=True)
    tensor = torch.from_dlpack(actual)
    tensor.reshape(-1)[0] = tensor.reshape(-1)[0] + 7
    if format_id != "pfm":
        np.testing.assert_array_equal(actual, snapshot)
    assert path.read_bytes() == encoded
    base = np.asarray(actual)
    base_tensor = torch.from_dlpack(base)
    base_tensor.reshape(-1)[0] = base_tensor.reshape(-1)[0] + 5
    assert path.read_bytes() == encoded
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            alias = torch.from_numpy(actual)
    except (ValueError, RuntimeError):
        pass
    else:
        alias.reshape(-1)[0] = alias.reshape(-1)[0] + 11
        assert path.read_bytes() == encoded
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_public_raw_view_outlives_file_handle_and_is_read_only(tmp_path, raw_case):
    path = tmp_path / f"public.{raw_case.id}"
    path.write_bytes(raw_case.data)
    actual = sceneio.read(path, format=raw_case.id)
    gc.collect()
    assert _fingerprint(actual) == _fingerprint(raw_case.value)
    with pytest.raises(ValueError):
        actual.flat[0] = 0
    with pytest.raises(ValueError):
        actual.setflags(write=True)
    del actual
    gc.collect()


def test_pfm_public_result_is_positive_stride_owned_decode(tmp_path):
    expected = np.arange(24, dtype=np.float32).reshape(2, 4, 3)
    path = tmp_path / "owned.pfm"
    path.write_bytes(_core.write_pfm(expected))
    actual = sceneio.read(path)
    np.testing.assert_array_equal(actual, expected)
    assert actual.flags.c_contiguous
    assert all(stride >= 0 for stride in actual.strides)
    # PFM's required bottom-to-top row reversal is a real transform. Keeping
    # the owned copy also makes ordinary np.asarray/DLPack normalization safe.
    path.unlink()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mapping lock semantics")
def test_public_view_holds_windows_lock_through_derived_lifetime(tmp_path):
    path = tmp_path / "locked.npy"
    path.write_bytes(_core.write_npy(np.arange(12, dtype=np.float32)))
    original = sceneio.read(path)
    derived = original[::2]
    with pytest.raises(PermissionError):
        path.unlink()
    del original
    gc.collect()
    with pytest.raises(PermissionError):
        path.unlink()
    del derived
    gc.collect()
    path.unlink()


@pytest.mark.parametrize("format_id", ["npy", "pfm", "flo"])
def test_failed_public_view_releases_mapping_while_exception_is_retained(
    tmp_path, format_id
):
    path = tmp_path / f"malformed.{format_id}"
    path.write_bytes(b"not a valid file")
    caught = None
    try:
        sceneio.read(path, format=format_id)
    except sceneio.FormatError as exc:
        caught = exc
    assert caught is not None
    path.unlink()
    assert caught.__cause__ is not None


def test_view_setup_failure_releases_mapping_while_exception_is_retained(
    tmp_path, monkeypatch
):
    path = tmp_path / "setup.npy"
    path.write_bytes(_core.write_npy(np.arange(8, dtype=np.int32)))

    def fail_memoryview(_mapped):
        raise MemoryError("injected view setup failure")

    monkeypatch.setattr(
        "sceneio.io._registry.adapters.memoryview",
        fail_memoryview,
        raising=False,
    )
    caught = None
    try:
        sceneio.read(path)
    except sceneio.FormatError as exc:
        caught = exc
    assert caught is not None
    path.unlink()


@pytest.mark.parametrize(
    "dtype",
    [
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
    ],
)
def test_npy_view_preserves_every_supported_dtype(dtype):
    values = np.arange(12).reshape(3, 4)
    if dtype is np.bool_:
        values = values % 2
    expected = values.astype(dtype)
    data = bytes(_core.write_npy(expected))
    actual = _core.read_npy_view(data)
    assert _fingerprint(actual) == _fingerprint(expected)
    assert actual.__array_interface__["data"][0] == (
        _core._buffer_address(data) + _npy_data_offset(data)
    )
    assert actual.flags.c_contiguous
    assert not actual.flags.writeable


@pytest.mark.parametrize("shape", [(), (0,), (0, 3), (2, 0, 4)])
def test_npy_view_handles_scalars_and_empty_shapes(shape):
    expected = np.zeros(shape, dtype=np.float32)
    actual = _core.read_npy_view(bytes(_core.write_npy(expected)))
    assert _fingerprint(actual) == _fingerprint(expected)
    assert not actual.flags.writeable


@pytest.mark.parametrize("kind", ["fortran", "non_native"])
def test_npy_view_canonicalization_falls_back_to_owned_copy(tmp_path, kind):
    expected = np.arange(24, dtype=np.int32).reshape(4, 6)
    stored = np.asfortranarray(expected)
    if kind == "non_native":
        stored = expected.astype(">i4" if sys.byteorder == "little" else "<i4")
    sink = io.BytesIO()
    np.save(sink, stored, allow_pickle=False)
    path = tmp_path / f"{kind}.npy"
    path.write_bytes(sink.getvalue())

    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        actual = _core.read_npy_view(mapped)
    np.testing.assert_array_equal(actual, expected)
    assert actual.dtype.isnative
    assert actual.flags.c_contiguous
    # The fallback does not retain an unrelated mapping.
    mapped.close()


def test_pfm_non_native_payload_falls_back_to_owned_copy(tmp_path):
    expected = np.arange(24, dtype=np.float32).reshape(2, 4, 3)
    native = bytes(_core.write_pfm(expected))
    offset = _pfm_data_offset(native)
    body = np.frombuffer(native, dtype="<f4", offset=offset).byteswap().tobytes()
    non_native = native[:offset].replace(b"-1.0", b"1.0") + body
    path = tmp_path / "big-endian.pfm"
    path.write_bytes(non_native)

    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        actual = _core.read_pfm(mapped)
    np.testing.assert_array_equal(actual, expected)
    mapped.close()


@pytest.mark.parametrize(
    ("dimensions", "scale"),
    [
        (b"4junk 2", b"-1.0"),
        (b"0 2", b"-1.0"),
        (b"4 2", b"0"),
        (b"4 2", b"nan"),
        (b"4 2", b"inf"),
        (b"4 2", b"-1junk"),
    ],
)
def test_pfm_rejects_invalid_dimension_and_scale_tokens(dimensions, scale):
    value = np.arange(24, dtype=np.float32).reshape(2, 4, 3)
    valid = bytes(_core.write_pfm(value))
    offset = _pfm_data_offset(valid)
    payload = b"PF\n" + dimensions + b"\n" + scale + b"\n" + valid[offset:]
    for reader in (_core.read_pfm,):
        with pytest.raises(ValueError):
            reader(payload)


def test_large_npy_public_view_has_no_file_sized_python_allocation(tmp_path):
    expected = np.arange(4 * 1024 * 1024, dtype=np.float32)
    path = tmp_path / "large.npy"
    path.write_bytes(_core.write_npy(expected))
    tracemalloc.start()
    try:
        actual = sceneio.read(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert _fingerprint(actual) == _fingerprint(expected)
    assert peak < path.stat().st_size // 16
    del actual
    gc.collect()
