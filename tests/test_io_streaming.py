"""O3 file-sink differential, allocation, and edge coverage."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest
from _support.buffer_codec_cases import build_buffer_codec_cases
from _support.memory_measurement import traced_peak

import sceneio
from sceneio import _core
from sceneio.io import registry


@pytest.fixture(scope="module")
def buffer_codecs():
    return build_buffer_codec_cases()


def test_all_single_file_sinks_are_byte_identical(tmp_path, buffer_codecs):
    """All 48 buffer encoders emit the exact bytes their buffer API returns."""
    assert len(buffer_codecs) == 48
    for spec in buffer_codecs:
        direct = tmp_path / f"direct-{spec.id}.bin"
        _core._write_to_file(spec.writer, spec.value, direct)
        assert direct.read_bytes() == spec.data, spec.id

        public = tmp_path / f"public-{spec.id}.bin"
        sceneio.write(spec.value, public, format=spec.id)
        assert public.read_bytes() == spec.data, spec.id

        # The thread-local sink scope must never leak into a later buffer call.
        assert bytes(spec.writer(spec.value)) == spec.data, spec.id


def test_directory_codec_writers_remain_byte_identical_file_sinks(
    tmp_path, buffer_codecs
):
    """The two COLMAP directory writers were already direct file sinks."""
    nvm = next(spec for spec in buffer_codecs if spec.id == "nvm")
    reconstruction = nvm.reader(nvm.data)
    for format_id, writer in (
        ("colmap_sparse", _core.write_colmap_sparse),
        ("colmap_sparse_txt", _core.write_colmap_txt),
    ):
        expected = tmp_path / f"direct-{format_id}"
        actual = tmp_path / f"public-{format_id}"
        expected.mkdir()
        actual.mkdir()
        writer(reconstruction, str(expected))
        sceneio.write(reconstruction, actual, format=format_id)
        expected_files = {
            item.name: item.read_bytes() for item in expected.iterdir() if item.is_file()
        }
        actual_files = {
            item.name: item.read_bytes() for item in actual.iterdir() if item.is_file()
        }
        assert actual_files == expected_files


def test_file_sink_guard_failure_does_not_truncate_destination(tmp_path):
    path = tmp_path / "existing.npy"
    path.write_bytes(b"keep this")
    non_contiguous = np.arange(24, dtype=np.float32).reshape(4, 6)[:, ::2]
    with pytest.raises(ValueError):
        _core._write_to_file(_core.write_npy, non_contiguous, path)
    assert path.read_bytes() == b"keep this"

    # The failed scope must restore ordinary buffer output.
    expected = np.arange(8, dtype=np.int32)
    assert bytes(_core.write_npy(expected)).startswith(b"\x93NUMPY")


def test_file_sink_supports_unicode_paths(tmp_path):
    value = np.arange(8, dtype=np.int32)
    path = tmp_path / "\u6d41-\u00e9.npy"
    _core._write_to_file(_core.write_npy, value, path)
    assert path.read_bytes() == bytes(_core.write_npy(value))


def test_file_sink_completes_multiple_native_write_chunks(tmp_path):
    value = np.arange(1024, dtype=np.float32)
    expected = bytes(_core.write_npy(value))
    path = tmp_path / "chunked.npy"
    chunk = 31
    calls = _core._write_to_file(
        _core.write_npy, value, path, _max_chunk=chunk
    )
    assert calls == (len(expected) + chunk - 1) // chunk
    assert path.read_bytes() == expected


def test_file_sink_accounts_for_partial_native_write_returns(tmp_path):
    value = np.arange(1024, dtype=np.float32)
    expected = bytes(_core.write_npy(value))
    path = tmp_path / "short-write.npy"
    limit = 31
    calls = _core._write_to_file(
        _core.write_npy, value, path, _test_short_write=limit
    )
    assert calls == (len(expected) + limit - 1) // limit
    assert path.read_bytes() == expected


def test_file_sink_closes_and_restores_after_native_error(tmp_path):
    value = np.arange(1024, dtype=np.float32)
    path = tmp_path / "native-error.npy"
    with pytest.raises(RuntimeError, match="file sink write failed"):
        _core._write_to_file(
            _core.write_npy,
            value,
            path,
            _test_short_write=31,
            _test_fail_after=1,
        )
    assert 0 < path.stat().st_size < len(bytes(_core.write_npy(value)))
    assert bytes(_core.write_npy(value)).startswith(b"\x93NUMPY")


def test_file_sink_closes_after_descriptor_failure(tmp_path, monkeypatch):
    class BadFile:
        closed = False

        def fileno(self):
            raise OSError("injected descriptor failure")

        def close(self):
            self.closed = True

    sink = BadFile()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: sink)
    with pytest.raises(OSError, match="injected descriptor failure"):
        _core._write_to_file(
            _core.write_npy, np.arange(8, dtype=np.int32), tmp_path / "bad.npy"
        )
    assert sink.closed
    assert bytes(_core.write_npy(np.arange(8, dtype=np.int32))).startswith(
        b"\x93NUMPY"
    )


def test_file_sink_never_exposes_encoder_buffer_to_python(tmp_path):
    script = """
import builtins
import pathlib
import sys
import numpy as np
from sceneio import _core
real_open = builtins.open
retained = []
class Wrapper:
    def __init__(self, path):
        self.file = real_open(path, "wb", buffering=0)
    def fileno(self):
        return self.file.fileno()
    def write(self, data):
        retained.append(memoryview(data))
        return len(data)
    def close(self):
        self.file.close()
path = pathlib.Path(sys.argv[1])
builtins.open = lambda *args, **kwargs: Wrapper(path)
value = np.arange(1024 * 1024, dtype=np.float32)
expected = bytes(_core.write_npy(value))
_core._write_to_file(_core.write_npy, value, path)
assert not retained
assert path.read_bytes() == expected
"""
    path = tmp_path / "native-sink.npy"
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_file_sink_suppresses_reentrant_path_callbacks(tmp_path):
    script = """
import builtins
import pathlib
import sys
import numpy as np
from sceneio import _core
real_open = builtins.open
events = []
inner = np.arange(17, dtype=np.int16)
inner_bytes = bytes(_core.write_npy(inner))
def reenter(label):
    encoded = _core.write_npy(inner)
    assert bytes(encoded) == inner_bytes
    events.append(label)
class Wrapper:
    def __init__(self, path):
        self.file = real_open(path, "wb", buffering=0)
    def fileno(self):
        reenter("fileno")
        return self.file.fileno()
    def close(self):
        reenter("close")
        self.file.close()
def wrapped_open(path, *args, **kwargs):
    reenter("open")
    return Wrapper(path)
path = pathlib.Path(sys.argv[1])
builtins.open = wrapped_open
outer = np.arange(1024 * 1024, dtype=np.float32)
expected = bytes(_core.write_npy(outer))
_core._write_to_file(_core.write_npy, outer, path)
assert events == ["open", "fileno", "close"]
assert path.read_bytes() == expected
"""
    path = tmp_path / "reentrant.npy"
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("format_id", ["npy", "pfm", "flo"])
def test_registry_prepares_array_protocols_before_file_sink(tmp_path, format_id):
    inner = np.arange(17, dtype=np.int16)
    inner_bytes = bytes(_core.write_npy(inner))
    if format_id == "flo":
        outer = np.arange(24, dtype=np.float32).reshape(3, 4, 2)
        encoder = _core.write_flo
    elif format_id == "pfm":
        outer = np.arange(12, dtype=np.float32).reshape(3, 4)
        encoder = _core.write_pfm
    else:
        outer = np.arange(12, dtype=np.float32).reshape(3, 4)
        encoder = _core.write_npy
    nested = []

    class ReentrantArray:
        def __array__(self, dtype=None, copy=None):
            del dtype, copy
            nested.append(bytes(_core.write_npy(inner)))
            return outer

    path = tmp_path / f"reentrant.{format_id}"
    sceneio.write(ReentrantArray(), path, format=format_id)
    assert nested == [inner_bytes]
    assert path.read_bytes() == bytes(encoder(outer))


def test_registry_prepares_npz_protocols_before_file_sink(tmp_path):
    inner = np.arange(17, dtype=np.int16)
    inner_bytes = bytes(_core.write_npy(inner))
    outer = np.arange(12, dtype=np.float32).reshape(3, 4)
    nested = []

    class ReentrantArray:
        def __array__(self, dtype=None, copy=None):
            del dtype, copy
            nested.append(bytes(_core.write_npy(inner)))
            return outer

    path = tmp_path / "reentrant.npz"
    sceneio.write({"outer": ReentrantArray()}, path, format="npz")
    expected = _core.write_npz(_core.tensor_dict({"outer": outer}))
    assert nested == [inner_bytes]
    assert path.read_bytes() == bytes(expected)


def test_registry_prepare_failure_does_not_truncate_destination(tmp_path):
    class BadArray:
        def __array__(self, dtype=None, copy=None):
            del dtype, copy
            raise RuntimeError("prepare failed")

    path = tmp_path / "existing.npy"
    path.write_bytes(b"keep this")
    with pytest.raises(registry.FormatError, match="prepare failed"):
        sceneio.write(BadArray(), path, format="npy")
    assert path.read_bytes() == b"keep this"
    assert bytes(_core.write_npy(np.arange(4, dtype=np.float32))).startswith(
        b"\x93NUMPY"
    )


def test_file_sink_does_not_allocate_output_sized_python_bytes(tmp_path):
    array = np.arange(4 * 1024 * 1024, dtype=np.float32)
    expected = bytes(_core.write_npy(array))
    path = tmp_path / "large-write.npy"

    buffered, bytes_peak = traced_peak(lambda: _core.write_npy(array))
    _, sink_peak = traced_peak(
        lambda: _core._write_to_file(_core.write_npy, array, path)
    )
    assert bytes(buffered) == expected
    assert path.read_bytes() == expected
    assert bytes_peak >= len(expected) * 0.9
    assert sink_peak < len(expected) / 8
