"""O1 mmap and O3 file-sink differential, memory, and edge coverage."""

from __future__ import annotations

import gc
import mmap
import os
import subprocess
import sys
import tracemalloc
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import registry


@dataclass(frozen=True)
class BufferCodec:
    id: str
    reader: object
    writer: object
    value: object
    data: bytes


def _array_fingerprint(value):
    array = np.asarray(value)
    return array.dtype.str, array.shape, array.tobytes()


def _camera_fingerprint(camera):
    return (
        camera.id,
        camera.model_id,
        camera.width,
        camera.height,
        _array_fingerprint(camera.params),
    )


def _fingerprint(value):
    """Capture every exposed field of a decoded record."""
    if isinstance(value, np.ndarray):
        fields = _array_fingerprint(value)
    elif isinstance(value, _core.Image):
        fields = (
            value.height,
            value.width,
            value.channels,
            value.dtype,
            value.color_space,
            value.alpha_mode,
            value.maxval,
            value.channel_order,
            value.row_order,
            _array_fingerprint(value.pixels),
        )
    elif isinstance(value, _core.GaussianCloud):
        fields = (
            value.num_gaussians,
            value.sh_degree,
            value.num_rest,
            value.quaternion_order,
            value.scale_space,
            value.opacity_space,
            value.sh_layout,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "means",
                    "scales",
                    "quaternions",
                    "opacities",
                    "sh_dc",
                    "sh_rest",
                )
            ),
        )
    elif isinstance(value, _core.PointCloud):
        fields = (
            value.num_points,
            value.has_rgb,
            value.has_rgb16,
            value.has_normals,
            value.has_intensity,
            value.coordinate_frame,
            value.scale_to_meters,
            value.intensity_range,
            value.origin,
            *(
                _array_fingerprint(getattr(value, name))
                for name in ("positions", "colors", "colors16", "normals", "intensities")
            ),
        )
    elif isinstance(value, _core.PosedViewSet):
        fields = (
            value.num_views,
            value.num_cameras,
            value.quaternion_order,
            value.pose_convention,
            value.axis_frame,
            value.scale_to_meters,
            tuple(value.names),
            tuple(_camera_fingerprint(camera) for camera in value.cameras),
            *(
                _array_fingerprint(getattr(value, name))
                for name in ("quaternions", "translations", "camera_indices", "timestamps")
            ),
        )
    elif isinstance(value, _core.Reconstruction):
        fields = (
            value.num_cameras,
            value.num_images,
            value.num_points3D,
            value.quaternion_order,
            value.pose_convention,
            tuple(value.image_names),
            tuple(_camera_fingerprint(camera) for camera in value.cameras),
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "image_ids",
                    "quaternions",
                    "translations",
                    "image_camera_ids",
                    "point3D_ids",
                    "xyz",
                    "rgb",
                    "errors",
                )
            ),
        )
    elif isinstance(value, _core.TensorDict):
        fields = (
            tuple(value.keys()),
            tuple((key, _array_fingerprint(value[key])) for key in value),
            value.attrs,
            value.byte_order,
            value.order,
        )
    else:  # pragma: no cover - every registered O1 codec is represented above
        raise AssertionError(f"unhandled result type {type(value)!r}")
    # O2 raw mapped arrays use a private ndarray subtype solely to make DLPack
    # export copy-safe; normalize it to the same public ndarray record kind.
    result_type = np.ndarray if isinstance(value, np.ndarray) else type(value)
    return result_type, fields


@pytest.fixture(scope="module")
def buffer_codecs():
    rng = np.random.default_rng(91)
    rgb = rng.integers(0, 256, (7, 9, 3), dtype=np.uint8)
    rgba = rng.integers(0, 256, (7, 9, 4), dtype=np.uint8)
    rgba[..., 3] = np.arange(7 * 9, dtype=np.uint8).reshape(7, 9) * 4
    rgb16 = rng.integers(0, 65536, (7, 9, 3), dtype=np.uint16)
    rgba16 = rng.integers(0, 65536, (7, 9, 4), dtype=np.uint16)
    linear = rng.random((7, 9, 3), dtype=np.float32) * 4
    linear_rgba = rng.random((7, 9, 4), dtype=np.float32) * 4
    linear_rgba[..., 3] = rng.random((7, 9), dtype=np.float32)
    image_u8 = _core.image(rgb, color_space="srgb")
    image_rgba = _core.image(rgba, color_space="srgb", alpha_mode="straight")
    image_u16 = _core.image(rgb16, color_space="srgb")
    image_rgba16 = _core.image(rgba16, color_space="srgb", alpha_mode="straight")
    image_f32 = _core.image(linear, color_space="linear")
    image_f32_rgba = _core.image(linear_rgba, color_space="linear", alpha_mode="premultiplied")
    positions = rng.random((13, 3), dtype=np.float32) * 10
    points_xyz = _core.point_cloud(positions, colors=rng.integers(0, 256, (13, 3), dtype=np.uint8))
    points_las = _core.point_cloud(
        positions,
        colors16=rng.integers(0, 65536, (13, 3), dtype=np.uint16),
        intensity=rng.integers(0, 65536, 13).astype(np.float32),
        intensity_range="u16",
    )
    flow = rng.standard_normal((5, 6, 2)).astype(np.float32)
    tensor = rng.standard_normal((4, 5, 3)).astype(np.float32)
    tensors = _core.tensor_dict({"a": tensor, "b": np.arange(9, dtype=np.int16)})
    gaussians = _core.gaussian_cloud(
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 4)).astype(np.float32),
        rng.standard_normal(11).astype(np.float32),
        rng.standard_normal((11, 3)).astype(np.float32),
        rng.standard_normal((11, 45)).astype(np.float32),
    )
    reconstruction = _core.read_nvm(
        b"NVM_V3\n1\na.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\n"
        b"1\n1.5 -2.5 3.5 10 20 30 1 0 0 4.5 -5.5\n0\n"
    )
    transforms = _core.read_transforms_json(
        b'{"camera_model":"PINHOLE","fl_x":500,"fl_y":510,"cx":320,"cy":240,'
        b'"w":640,"h":480,"frames":[{"file_path":"a.png","transform_matrix":'
        b"[[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]]}]}"
    )
    tum = _core.read_tum(b"0 1 2 3 0 0 0 1\n")
    kitti = _core.read_kitti(b"1 0 0 1 0 1 0 2 0 0 1 3\n")

    def spec(codec_id, reader, writer, value):
        return BufferCodec(codec_id, reader, writer, value, bytes(writer(value)))

    return [
        spec("pfm", _core.read_pfm, _core.write_pfm, tensor),
        spec("gaussian_ply", _core.read_gaussian_ply, _core.write_gaussian_ply, gaussians),
        spec("spz", _core.read_spz, _core.write_spz, gaussians),
        spec(
            "transforms_json",
            _core.read_transforms_json,
            _core.write_transforms_json,
            transforms,
        ),
        spec("tum", _core.read_tum, _core.write_tum, tum),
        spec("kitti", _core.read_kitti, _core.write_kitti, kitti),
        spec("npy", _core.read_npy, _core.write_npy, tensor),
        spec("npz", _core.read_npz, _core.write_npz, tensors),
        spec("netpbm", _core.read_netpbm, _core.write_netpbm, image_u16),
        spec("png", _core.read_png, _core.write_png, image_rgba16),
        spec("jpeg", _core.read_jpeg, _core.write_jpeg, image_u8),
        spec("hdr", _core.read_hdr, _core.write_hdr, image_f32),
        spec("exr", _core.read_exr, _core.write_exr, image_f32_rgba),
        spec("webp", _core.read_webp, _core.write_webp, image_rgba),
        spec("xyz", _core.read_xyz, _core.write_xyz, points_xyz),
        spec("las", _core.read_las, _core.write_las, points_las),
        spec("flo", _core.read_flo, _core.write_flo, flow),
        spec("bundler", _core.read_bundler, _core.write_bundler, reconstruction),
        spec("nvm", _core.read_nvm, _core.write_nvm, reconstruction),
        spec("openmvg", _core.read_openmvg, _core.write_openmvg, reconstruction),
        spec("splat", _core.read_splat, _core.write_splat, gaussians),
    ]


def _decode_outcome(call, argument):
    try:
        return "ok", call(argument)
    except Exception as exc:  # malformed-input parity includes exception text
        return "error", type(exc), str(exc)


def _finish_outcome(decoded):
    if decoded[0] == "error":
        return decoded
    return "ok", _fingerprint(decoded[1])


def _outcome(call, argument):
    return _finish_outcome(_decode_outcome(call, argument))


def test_all_single_file_codecs_mmap_equal_bytes_bit_exact(tmp_path, buffer_codecs):
    """All 21 buffer codecs decode mmap and bytes to bit-exact records."""
    assert len(buffer_codecs) == 21
    for spec in buffer_codecs:
        expected = _fingerprint(spec.reader(spec.data))
        path = tmp_path / f"sample-{spec.id}.bin"
        path.write_bytes(spec.data)
        with (
            path.open("rb") as stream,
            mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
        ):
            actual_value = spec.reader(mapped)

        # Force collection after the mmap and file handle close: O1 results must
        # own every decoded byte and remain valid without their input exporter.
        gc.collect()
        assert _fingerprint(actual_value) == expected, spec.id


def test_all_single_file_sinks_are_byte_identical(tmp_path, buffer_codecs):
    """All 21 compiled encoders emit the exact bytes their buffer API returns."""
    assert len(buffer_codecs) == 21
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
    path = tmp_path / "流-é.npy"
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


def test_registry_uses_mmap_for_every_nonempty_single_file_codec(
    tmp_path, buffer_codecs, monkeypatch
):
    paths = []
    for index, spec in enumerate(buffer_codecs):
        path = tmp_path / f"registry-{index}-{spec.id}.bin"
        path.write_bytes(spec.data)
        paths.append(path)

    original_mmap = mmap.mmap
    mapped_paths = 0

    def tracked_mmap(*args, **kwargs):
        nonlocal mapped_paths
        mapped_paths += 1
        return original_mmap(*args, **kwargs)

    def forbidden_read_bytes(self):
        raise AssertionError(f"whole-file bytes fallback used for {self}")

    monkeypatch.setattr(registry.mmap, "mmap", tracked_mmap)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    for spec, path in zip(buffer_codecs, paths, strict=True):
        value = sceneio.codecs()[spec.id].read(str(path))
        gc.collect()
        assert _fingerprint(value) == _fingerprint(spec.reader(spec.data))
    assert mapped_paths == len(buffer_codecs) == 21


def test_all_buffer_entries_accept_readonly_protocol_exporters(buffer_codecs):
    for spec in buffer_codecs:
        expected = _fingerprint(spec.reader(spec.data))
        readonly_array = np.frombuffer(spec.data, dtype=np.uint8)
        assert not readonly_array.flags.writeable
        for view in (memoryview(spec.data), readonly_array):
            assert _fingerprint(spec.reader(view)) == expected, spec.id


def test_buffer_entry_rejects_writable_wrong_dtype_and_noncontiguous(buffer_codecs):
    spec = buffer_codecs[0]
    wrong = [
        bytearray(spec.data),
        np.frombuffer(spec.data, dtype=np.uint8).copy(),
        np.frombuffer(spec.data, dtype=np.uint8)[::2],
        np.frombuffer(spec.data, dtype=np.uint8).astype(np.int8),
        np.frombuffer(spec.data, dtype=np.uint8).astype(np.uint16),
    ]
    for value in wrong:
        with pytest.raises(ValueError, match="read-only, C-contiguous unsigned-byte buffer"):
            spec.reader(value)


def test_buffer_entry_aliases_exporter_without_native_copy(tmp_path):
    path = tmp_path / "address.bin"
    path.write_bytes(bytes(range(251)) * 4096)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        numpy_view = np.frombuffer(mapped, dtype=np.uint8)
        assert _core._buffer_address(mapped) == numpy_view.__array_interface__["data"][0]
        del numpy_view


def test_all_single_file_codecs_truncated_mmap_matches_bytes(tmp_path, buffer_codecs):
    for spec in buffer_codecs:
        truncated = spec.data[: max(1, len(spec.data) // 3)]
        expected = _outcome(spec.reader, truncated)
        path = tmp_path / f"truncated-{spec.id}.bin"
        path.write_bytes(truncated)
        with (
            path.open("rb") as stream,
            mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
        ):
            decoded = _decode_outcome(spec.reader, mapped)
        gc.collect()
        actual = _finish_outcome(decoded)
        assert actual == expected, spec.id


def test_all_single_file_codecs_mutation_fuzz_mmap_matches_bytes(tmp_path, buffer_codecs):
    """Random malformed inputs cannot become backing-store-dependent.

    Normal CI uses three mutations per codec. The scheduled sanitizer workflow
    raises SCENEIO_MMAP_FUZZ_CASES for the nightly differential fuzz pass.
    """
    cases = int(os.environ.get("SCENEIO_MMAP_FUZZ_CASES", "3"))
    rng = np.random.default_rng(20260723)
    for spec in buffer_codecs:
        for case in range(cases):
            mutated = bytearray(spec.data)
            operation = case % 3
            if operation == 0 and mutated:
                mutated[rng.integers(0, len(mutated))] ^= int(rng.integers(1, 256))
            elif operation == 1 and len(mutated) > 1:
                del mutated[int(rng.integers(1, len(mutated))) :]
            else:
                mutated.extend(rng.integers(0, 256, 7, dtype=np.uint8).tobytes())
            data = bytes(mutated)
            try:
                expected = _outcome(spec.reader, data)
            except Exception as exc:
                raise AssertionError(
                    f"{spec.id} mutation {case} returned an inaccessible record"
                ) from exc
            path = tmp_path / f"fuzz-{spec.id}-{case}.bin"
            path.write_bytes(data)
            with (
                path.open("rb") as stream,
                mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
            ):
                decoded = _decode_outcome(spec.reader, mapped)
            gc.collect()
            actual = _finish_outcome(decoded)
            assert actual == expected, (spec.id, case, operation)


def test_all_single_file_codecs_empty_path_matches_empty_bytes(tmp_path, buffer_codecs):
    """The portable empty-file fallback preserves each codec's exact behavior."""
    for spec in buffer_codecs:
        path = tmp_path / f"empty-{spec.id}.bin"
        path.touch()
        expected = _outcome(spec.reader, b"")
        actual = _outcome(sceneio.codecs()[spec.id].read, str(path))
        assert actual == expected, spec.id


@pytest.mark.parametrize(
    "header",
    [
        b"ply\nformat\nend_header\n",
        b"ply\nelement\nend_header\n",
        b"ply\nelement vertex nope\nend_header\n",
        b"ply\nelement vertex 1\nproperty\nend_header\n",
    ],
)
def test_gaussian_ply_short_header_lines_raise(header):
    with pytest.raises(ValueError, match="PLY: malformed"):
        _core.read_gaussian_ply(header)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (b"element vertex 11", b"element vertex 11junk", "malformed vertex count"),
        (
            b"format binary_little_endian 1.0",
            b"format binary_little_endian 9.9",
            "unsupported format version",
        ),
        (
            b"format binary_little_endian 1.0\n",
            b"",
            "missing format header",
        ),
        (
            b"format binary_little_endian 1.0\n",
            b"format binary_little_endian 1.0\nformat binary_little_endian 1.0\n",
            "duplicate format header",
        ),
    ],
)
def test_gaussian_ply_rejects_malformed_format_declarations(
    buffer_codecs, old, new, message
):
    spec = next(item for item in buffer_codecs if item.id == "gaussian_ply")
    assert old in spec.data
    payload = spec.data.replace(old, new, 1)
    with pytest.raises(ValueError, match=message):
        _core.read_gaussian_ply(payload)


@pytest.mark.parametrize("failure", [OSError, ValueError])
def test_mmap_failure_falls_back_to_same_open_stream(tmp_path, monkeypatch, failure):
    array = np.arange(24, dtype=np.float32).reshape(4, 6)
    path = tmp_path / "fallback.npy"
    path.write_bytes(_core.write_npy(array))
    attempts = 0

    def unavailable(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise failure("mapping unavailable")

    def forbidden_read_bytes(self):
        raise AssertionError(f"path was reopened through read_bytes: {self}")

    monkeypatch.setattr(registry.mmap, "mmap", unavailable)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    np.testing.assert_array_equal(sceneio.read(path), array)
    assert attempts == 1


def _traced_peak(call):
    tracemalloc.start()
    try:
        value = call()
        _, peak = tracemalloc.get_traced_memory()
        return value, peak
    finally:
        tracemalloc.stop()


def test_file_sink_does_not_allocate_output_sized_python_bytes(tmp_path):
    array = np.arange(4 * 1024 * 1024, dtype=np.float32)
    expected = bytes(_core.write_npy(array))
    path = tmp_path / "large-write.npy"

    buffered, bytes_peak = _traced_peak(lambda: _core.write_npy(array))
    _, sink_peak = _traced_peak(
        lambda: _core._write_to_file(_core.write_npy, array, path)
    )
    assert bytes(buffered) == expected
    assert path.read_bytes() == expected
    assert bytes_peak >= len(expected) * 0.9
    assert sink_peak < len(expected) / 8


def test_mmap_read_does_not_allocate_whole_file_bytes(tmp_path):
    """A 16 MiB .npy proves the adapter/caster do not copy the input buffer."""
    array = np.arange(4 * 1024 * 1024, dtype=np.float32)
    path = tmp_path / "large.npy"
    path.write_bytes(_core.write_npy(array))
    file_size = path.stat().st_size

    slow, bytes_peak = _traced_peak(lambda: _core.read_npy(path.read_bytes()))
    fast, mmap_peak = _traced_peak(lambda: sceneio.read(path))
    np.testing.assert_array_equal(fast, slow)
    assert bytes_peak >= file_size * 0.9
    assert mmap_peak < file_size / 8


@pytest.mark.skipif(os.name != "nt", reason="Windows share-mode locked-file edge")
def test_locked_file_fails_cleanly_on_windows(tmp_path):
    import ctypes
    from ctypes import wintypes

    path = tmp_path / "locked.npy"
    path.write_bytes(_core.write_npy(np.arange(4, dtype=np.float32)))
    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(str(path), 0x80000000, 0, None, 3, 0x80, None)
    invalid = wintypes.HANDLE(-1).value
    assert handle != invalid
    try:
        with pytest.raises(sceneio.FormatError) as caught:
            sceneio.read(path)
        assert isinstance(caught.value.__cause__, PermissionError)
    finally:
        assert close_handle(handle)


def test_magic_detection_reads_only_prefix(tmp_path, monkeypatch):
    path = tmp_path / "extensionless"
    path.write_bytes(_core.write_npy(np.arange(8, dtype=np.float32)))
    original = Path.open
    reads = []

    class TrackingReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            reads.append(size)
            return self.stream.read(size)

    def tracked_open(self, *args, **kwargs):
        stream = original(self, *args, **kwargs)
        return TrackingReader(stream) if self == path else stream

    monkeypatch.setattr(Path, "open", tracked_open)
    assert sceneio.detect(path) == "npy"
    assert reads == [16]
