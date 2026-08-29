"""O1 mmap differential, allocation, and edge coverage."""

from __future__ import annotations

import gc
import mmap
import os
from pathlib import Path

import numpy as np
import pytest
from _support.buffer_codec_cases import build_buffer_codec_cases
from _support.memory_measurement import traced_peak

import sceneio
from sceneio import _core
from sceneio.io._registry import adapters


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
    elif isinstance(value, _core.ImageSequence):
        fields = (
            value.num_frames,
            value.height,
            value.width,
            value.channels,
            value.chroma_height,
            value.chroma_width,
            value.storage_mode,
            value.frame_dtype,
            value.color_space,
            value.alpha_mode,
            value.chroma_subsampling,
            value.chroma_siting,
            value.color_range,
            value.matrix,
            value.interlace,
            value.frame_rate_numerator,
            value.frame_rate_denominator,
            value.pixel_aspect_numerator,
            value.pixel_aspect_denominator,
            tuple(value.frame_paths),
            tuple(value.frame_names),
            _array_fingerprint(value.timestamps_ns),
            _array_fingerprint(value.durations_ns),
            _array_fingerprint(value.y),
            _array_fingerprint(value.u),
            _array_fingerprint(value.v),
        )
    elif isinstance(value, _core.DepthMap):
        fields = (
            value.height,
            value.width,
            value.has_confidence,
            value.unit,
            value.scale_to_meters,
            value.invalid_policy,
            value.depth_convention,
            value.row_order,
            _array_fingerprint(value.depth),
            (
                _array_fingerprint(value.confidence)
                if value.has_confidence
                else None
            ),
        )
    elif isinstance(value, _core.NormalMap):
        fields = (
            value.height,
            value.width,
            value.coordinate_system,
            value.component_order,
            value.row_order,
            value.invalid_policy,
            value.orientation,
            _array_fingerprint(value.normals),
        )
    elif isinstance(value, _core.ConsistencyGraph):
        fields = (
            value.height,
            value.width,
            value.num_entries,
            value.num_image_indices,
            value.index_domain,
            _array_fingerprint(value.rows),
            _array_fingerprint(value.columns),
            _array_fingerprint(value.offsets),
            _array_fingerprint(value.image_indices),
        )
    elif isinstance(value, _core.PointVisibility):
        fields = (
            value.num_points,
            value.num_image_indices,
            value.index_domain,
            _array_fingerprint(value.offsets),
            _array_fingerprint(value.image_indices),
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
            value.width,
            value.height,
            value.is_organized,
            value.viewpoint,
            *(
                _array_fingerprint(getattr(value, name))
                for name in ("positions", "colors", "colors16", "normals", "intensities")
            ),
        )
    elif isinstance(value, _core.Mesh):
        fields = (
            value.num_vertices,
            value.num_faces,
            value.num_corners,
            value.num_primitives,
            value.coordinate_frame,
            value.scale_to_meters,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "positions",
                    "face_offsets",
                    "face_indices",
                    "vertex_normals",
                    "corner_normals",
                    "vertex_uvs",
                    "corner_uvs",
                    "vertex_colors",
                    "corner_colors",
                    "primitive_offsets",
                    "primitive_materials",
                    "local_transform",
                )
            ),
        )
    elif isinstance(value, _core.MeshScene):
        materials = value.materials
        material_fields = (
            tuple(materials.names),
            tuple(materials.alpha_modes),
            tuple(materials.texture_semantics),
            tuple(materials.texture_paths),
            *(
                _array_fingerprint(getattr(materials, name))
                for name in (
                    "base_colors",
                    "emissive_colors",
                    "metallic",
                    "roughness",
                    "alpha_cutoffs",
                    "texture_materials",
                    "texture_uv_sets",
                    "texture_wrap_s_codes",
                    "texture_wrap_t_codes",
                    "texture_min_filter_codes",
                    "texture_mag_filter_codes",
                )
            ),
        )
        fields = (
            value.num_meshes,
            value.num_primitives,
            value.num_nodes,
            value.num_scenes,
            value.has_materials,
            value.default_scene,
            tuple(value.mesh_names),
            tuple(value.node_names),
            tuple(value.scene_names),
            material_fields,
            tuple(
                _fingerprint(value.primitive_at(index))
                for index in range(value.num_primitives)
            ),
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "mesh_primitive_offsets",
                    "node_meshes",
                    "node_child_offsets",
                    "node_children",
                    "node_local_transforms",
                    "scene_root_offsets",
                    "scene_roots",
                )
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
    elif isinstance(value, _core.StateTrajectory):
        fields = (
            value.num_states,
            value.quaternion_order,
            value.quaternion_sign,
            value.pose_convention,
            value.position_frame,
            value.velocity_frame,
            value.bias_frame,
            value.position_unit,
            value.velocity_unit,
            value.gyro_bias_unit,
            value.accel_bias_unit,
            value.timestamp_unit,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "timestamps_ns",
                    "positions",
                    "quaternions",
                    "velocities",
                    "gyro_biases",
                    "accel_biases",
                )
            ),
        )
    elif isinstance(value, _core.CameraRig):
        fields = (
            value.num_cameras,
            tuple(value.names),
            tuple(value.projection_models),
            tuple(value.distortion_models),
            tuple(value.topics),
            value.quaternion_order,
            value.quaternion_sign,
            value.transform_convention,
            value.axis_frame,
            value.reference_frame,
            value.scale_to_meters,
            value.time_offset_convention,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "camera_ids",
                    "resolutions",
                    "intrinsic_offsets",
                    "intrinsics",
                    "distortion_offsets",
                    "distortion_coefficients",
                    "quaternions",
                    "translations",
                    "has_extrinsics",
                    "camera_matrices",
                    "has_camera_matrix",
                    "rectification_matrices",
                    "has_rectification",
                    "projection_matrices",
                    "has_projection_matrix",
                    "binning",
                    "roi",
                    "roi_do_rectify",
                    "has_operational",
                    "time_offsets",
                    "has_time_offset",
                )
            ),
        )
    elif isinstance(value, _core.PoseGraph):
        fields = (
            value.num_nodes,
            value.num_edges,
            tuple(value.node_types),
            tuple(value.edge_types),
            value.quaternion_order,
            value.quaternion_sign,
            value.node_transform_convention,
            value.edge_transform_convention,
            value.translation_unit,
            value.information_variable_order,
            value.information_storage,
            *(
                _array_fingerprint(getattr(value, name))
                for name in (
                    "node_ids",
                    "node_translations",
                    "node_quaternions",
                    "fixed",
                    "edge_endpoints",
                    "edge_translations",
                    "edge_quaternions",
                    "information_matrices",
                )
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
    return build_buffer_codec_cases()


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
    """All 52 buffer codecs decode mmap and bytes to bit-exact records."""
    assert len(buffer_codecs) == 52
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

    monkeypatch.setattr(adapters.mmap, "mmap", tracked_mmap)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    for spec, path in zip(buffer_codecs, paths, strict=True):
        value = sceneio.codecs()[spec.id].read(str(path))
        gc.collect()
        assert _fingerprint(value) == _fingerprint(spec.reader(spec.data))
    assert mapped_paths == len(buffer_codecs) == 52


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

    monkeypatch.setattr(adapters.mmap, "mmap", unavailable)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    np.testing.assert_array_equal(sceneio.read(path), array)
    assert attempts == 1


def test_mmap_read_does_not_allocate_whole_file_bytes(tmp_path):
    """A 16 MiB .npy proves the adapter/caster do not copy the input buffer."""
    array = np.arange(4 * 1024 * 1024, dtype=np.float32)
    path = tmp_path / "large.npy"
    path.write_bytes(_core.write_npy(array))
    file_size = path.stat().st_size

    slow, bytes_peak = traced_peak(lambda: _core.read_npy(path.read_bytes()))
    fast, mmap_peak = traced_peak(lambda: sceneio.read(path))
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
    # LAS and LAZ share LASF; byte 104 carries their compression distinction.
    assert reads == [105]
