"""O5 inspection differential, allocation, and edge coverage."""

from __future__ import annotations

import binascii
import gzip
import io
import json
import os
import struct
import subprocess
import sys
import tracemalloc
import zipfile

import numpy as np
import pytest
from _support.buffer_codec_cases import build_buffer_codec_cases

import sceneio
from sceneio import _core
from sceneio.io import registry


@pytest.fixture(scope="module")
def buffer_codecs():
    return build_buffer_codec_cases()


def _assert_inspection_matches(info, decoded):
    if isinstance(decoded, np.ndarray):
        assert info.shape == decoded.shape
        assert info.dtype == decoded.dtype.name
    elif isinstance(decoded, _core.Image):
        assert info.shape == decoded.pixels.shape
        assert info.dtype == decoded.dtype
        assert info.channels == decoded.channels
    elif isinstance(decoded, _core.ImageSequence):
        assert info.shape == (
            decoded.num_frames,
            decoded.height,
            decoded.width,
            decoded.channels,
        )
        assert info.dtype == decoded.frame_dtype
        assert info.count == decoded.num_frames
        assert info.channels == decoded.channels
        assert info.metadata["storage_mode"] == decoded.storage_mode
        if decoded.storage_mode == "yuv_planar":
            assert tuple(
                (item.name, item.shape, item.dtype) for item in info.arrays
            ) == tuple(
                (
                    name,
                    getattr(decoded, name).shape,
                    getattr(decoded, name).dtype.name,
                )
                for name in ("y", "u", "v")
                if getattr(decoded, name).size
            )
    elif isinstance(decoded, _core.DepthMap):
        assert info.shape == decoded.depth.shape
        assert info.dtype == decoded.depth.dtype.name
        assert info.count == decoded.height * decoded.width
        assert info.channels == 1
    elif isinstance(decoded, _core.NormalMap):
        assert info.shape == decoded.normals.shape
        assert info.dtype == decoded.normals.dtype.name
        assert info.count == decoded.height * decoded.width
        assert info.channels == 3
    elif isinstance(decoded, _core.ConsistencyGraph):
        assert info.shape == (decoded.height, decoded.width)
        assert info.dtype == "int32"
        assert info.count == decoded.num_entries
        assert (
            info.metadata["image_index_count"]
            == decoded.num_image_indices
        )
    elif isinstance(decoded, _core.PointVisibility):
        assert info.shape is None
        assert info.count == decoded.num_points
        assert (
            info.metadata["image_index_count"]
            == decoded.num_image_indices
        )
    elif isinstance(decoded, _core.GaussianCloud):
        assert info.shape == (decoded.num_gaussians,)
        assert info.dtype == "float32"
        assert info.count == decoded.num_gaussians
        assert info.metadata["sh_degree"] == decoded.sh_degree
    elif isinstance(decoded, _core.PointCloud):
        assert info.shape == decoded.positions.shape
        assert info.dtype == decoded.positions.dtype.name
        assert info.count == decoded.num_points
    elif isinstance(decoded, _core.Mesh):
        assert info.shape == decoded.positions.shape
        assert info.dtype == decoded.positions.dtype.name
        assert info.count == decoded.num_vertices
        assert info.metadata["num_vertices"] == decoded.num_vertices
        assert info.metadata["num_faces"] == decoded.num_faces
    elif isinstance(decoded, _core.SceneGraph):
        vertices = sum(
            decoded.mesh_primitive_at(index).num_vertices
            for index in range(decoded.num_mesh_primitives)
        )
        faces = sum(
            decoded.mesh_primitive_at(index).num_faces
            for index in range(decoded.num_mesh_primitives)
        )
        assert info.shape == (vertices, 3)
        assert info.dtype == "float32"
        assert info.count == vertices
        assert info.metadata["num_meshes"] == decoded.num_meshes
        assert (
            info.metadata["num_primitives"]
            == decoded.num_mesh_primitives
        )
        assert info.metadata["num_faces"] == faces
    elif isinstance(decoded, sceneio.PosedViewSet):
        assert info.shape == (len(decoded),)
        assert info.dtype == "float64"
        assert info.count == len(decoded)
        if "num_cameras" in info.metadata:
            storage = decoded._source_storage
            assert storage is not None
            assert info.metadata["num_cameras"] == storage.num_cameras
    elif isinstance(decoded, _core.StateTrajectory):
        assert info.shape == (decoded.num_states,)
        assert info.dtype == "float64"
        assert info.count == decoded.num_states
        assert info.metadata["timestamp_unit"] == "nanoseconds"
        assert info.metadata["quaternion_order"] == "wxyz"
    elif isinstance(decoded, _core.CameraRig):
        assert info.shape == (decoded.num_cameras,)
        assert info.dtype == "float64"
        assert info.count == decoded.num_cameras
        assert info.metadata["resolutions"] == tuple(
            np.asarray(decoded.resolutions).ravel()
        )
        assert info.metadata["axis_frame"] == "opencv"
    elif isinstance(decoded, _core.PoseGraph):
        assert info.shape == (decoded.num_nodes,)
        assert info.dtype == "float64"
        assert info.count == decoded.num_nodes
        assert info.metadata["num_nodes"] == decoded.num_nodes
        assert info.metadata["num_edges"] == decoded.num_edges
        assert info.metadata["num_fixed_nodes"] == int(decoded.fixed.sum())
        assert info.metadata["quaternion_order"] == decoded.quaternion_order
        assert (
            info.metadata["edge_transform_convention"]
            == decoded.edge_transform_convention
        )
    elif isinstance(decoded, _core.Reconstruction):
        assert info.shape == (decoded.num_images,)
        assert info.dtype == decoded.quaternions.dtype.name
        assert info.count == decoded.num_images
        expected = {
            "num_cameras": decoded.num_cameras,
            "num_images": decoded.num_images,
            "num_points3D": decoded.num_points3D,
        }
        assert {
            key: info.metadata[key] for key in expected
        } == expected
        assert set(info.metadata) <= {*expected, "num_observations"}
    elif isinstance(decoded, _core.TensorDict):
        assert info.count == len(decoded)
        assert tuple((item.name, item.shape, item.dtype) for item in info.arrays) == tuple(
            (name, decoded[name].shape, decoded[name].dtype.name) for name in decoded
        )
    else:  # pragma: no cover - the all-codec fixture fixes the closed set
        raise AssertionError(f"unhandled inspected result {type(decoded)!r}")


def _fresh_process_inspect_rss(path, format_id, *, expect_error=False):
    if os.environ.get("ASAN_OPTIONS") or "libasan" in os.environ.get(
        "LD_PRELOAD", ""
    ):
        pytest.skip("RSS measurements include AddressSanitizer shadow memory")
    script = """
import gc
import sys
import threading
import time

import psutil
import sceneio
from sceneio.io import inspect as inspect_scene

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
    try:
        value = inspect_scene(sys.argv[1], format=sys.argv[2])
    except Exception:
        if sys.argv[3] != "error":
            raise
    else:
        if sys.argv[3] == "error":
            raise AssertionError("inspection unexpectedly succeeded")
        del value
    peak[0] = max(peak[0], process.memory_info().rss)
finally:
    running[0] = False
    thread.join()
print(max(0, peak[0] - baseline))
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(path),
            format_id,
            "error" if expect_error else "success",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(completed.stdout.strip())


def test_inspect_matches_decoded_metadata_for_buffer_and_directory_codecs(
    tmp_path, buffer_codecs
):
    assert len(buffer_codecs) == 52
    for spec in buffer_codecs:
        path = tmp_path / f"inspect-{spec.id}.data"
        path.write_bytes(spec.data)
        info = sceneio.inspect(path, format=spec.id)
        decoded = sceneio.read(path, format=spec.id)
        assert info.format == spec.id
        assert info.datatype == registry.get(spec.id).datatype
        assert info.byte_size == len(spec.data)
        _assert_inspection_matches(info, decoded)
        if spec.id == "pfm":
            assert info.metadata == {"byte_order": "little"}
        elif spec.id == "gaussian_ply":
            assert info.metadata == {
                "sh_degree": decoded.sh_degree,
                "num_rest": decoded.num_rest,
                "byte_order": "little",
            }
        elif spec.id == "compressed_ply":
            assert info.metadata == {
                "encoding": "binary_little_endian",
                "byte_order": "little",
                "chunk_size": 256,
                "num_chunks": 1,
                "sh_degree": decoded.sh_degree,
                "num_rest": decoded.num_rest,
                "chunk_color_ranges": True,
                "position_bits": (11, 10, 11),
                "scale_bits": (11, 10, 11),
                "quaternion_bits": (2, 10, 10, 10),
                "color_bits": (8, 8, 8, 8),
            }
        elif spec.id == "sog":
            assert info.metadata == {
                "version": 2,
                "sh_degree": decoded.sh_degree,
                "num_rest": decoded.num_rest,
                "palette_count": 8,
                "packaging": "zip",
                "texture_codec": "lossless_webp",
            }
        elif spec.id == "ksplat":
            assert info.metadata == {
                "version": "0.1",
                "compression_level": 1,
                "sh_degree": decoded.sh_degree,
                "num_rest": decoded.num_rest,
                "section_count": 1,
                "loaded_section_count": 1,
                "loaded_count": decoded.num_gaussians,
                "scene_center": (0.0, 0.0, 0.0),
                "sh_quantization_range": (
                    float(np.min(np.asarray(spec.value.sh_rest))),
                    float(np.max(np.asarray(spec.value.sh_rest))),
                ),
            }
        elif spec.id == "ply":
            assert info.metadata == {
                "encoding": "binary_little_endian",
                "byte_order": "little",
                "properties": (
                    "x",
                    "y",
                    "z",
                    "nx",
                    "ny",
                    "nz",
                    "red",
                    "green",
                    "blue",
                    "intensity",
                ),
                "property_types": (
                    "float",
                    "float",
                    "float",
                    "float",
                    "float",
                    "float",
                    "uchar",
                    "uchar",
                    "uchar",
                    "float",
                ),
                "has_normals": True,
                "has_color": True,
                "color_dtype": "uint8",
                "has_intensity": True,
                "intensity_range": "unknown",
                "vertex_stride": 31,
            }
        elif spec.id == "ply_mesh":
            assert info.metadata == {
                "encoding": "binary_little_endian",
                "byte_order": "little",
                "num_vertices": decoded.num_vertices,
                "num_faces": decoded.num_faces,
                "vertex_properties": (
                    "x",
                    "y",
                    "z",
                    "nx",
                    "ny",
                    "nz",
                    "texture_u",
                    "texture_v",
                    "red",
                    "green",
                    "blue",
                    "alpha",
                ),
                "face_properties": (
                    "vertex_indices",
                    "texcoord",
                    "corner_normals",
                    "corner_colors",
                    "material_index",
                    "primitive_index",
                ),
                "has_vertex_normals": True,
                "has_vertex_uvs": True,
                "has_vertex_colors": True,
                "has_vertex_alpha": True,
                "has_corner_normals": True,
                "has_corner_uvs": True,
                "has_corner_colors": True,
                "has_material_indices": True,
                "has_primitive_indices": True,
                "coordinate_frame": decoded.coordinate_frame,
                "scale_to_meters": decoded.scale_to_meters,
                "local_transform": tuple(
                    np.asarray(decoded.local_transform).reshape(-1)
                ),
            }
        elif spec.id == "pcd":
            assert info.metadata == {
                "storage": "binary",
                "fields": (
                    "x",
                    "y",
                    "z",
                    "normal_x",
                    "normal_y",
                    "normal_z",
                    "rgb",
                    "intensity",
                ),
                "sizes": (4, 4, 4, 4, 4, 4, 4, 2),
                "types": ("F", "F", "F", "F", "F", "F", "U", "U"),
                "counts": (1, 1, 1, 1, 1, 1, 1, 1),
                "width": 13,
                "height": 1,
                "organized": False,
                "viewpoint": decoded.viewpoint,
                "has_normals": True,
                "has_color": True,
                "has_intensity": True,
                "intensity_range": "u16",
                "point_stride": 30,
                "compressed_size": 0,
            }
        elif spec.id == "spz":
            assert info.metadata == {
                "version": 3,
                "sh_degree": decoded.sh_degree,
                "fractional_bits": 12,
            }
        elif spec.id == "npy":
            assert info.metadata == {"fortran_order": False}
        elif spec.id == "netpbm":
            assert info.metadata == {"ascii": False, "maxval": decoded.maxval}
        elif spec.id == "png":
            assert info.metadata == {"interlaced": False}
        elif spec.id == "jpeg":
            assert info.metadata == {"precision": 8, "progressive": False}
        elif spec.id == "bmp":
            assert info.metadata == {
                "bits_per_pixel": 32,
                "compression": "BI_BITFIELDS",
                "palette": False,
                "top_down": False,
            }
        elif spec.id == "tga":
            assert info.metadata == {
                "bits_per_pixel": 32,
                "rle": True,
                "palette": False,
                "origin": "bottom_left",
            }
        elif spec.id == "exr":
            assert set(info.metadata["channel_names"]) == {"R", "G", "B", "A"}
        elif spec.id == "xyz":
            assert info.metadata == {
                "columns": 6,
                "has_color": True,
                "has_intensity": False,
                "has_normals": False,
            }
        elif spec.id == "las":
            assert info.metadata == {
                "point_format": 2,
                "has_color": True,
                "has_intensity": True,
                "has_waveform": False,
            }
        elif spec.id == "splat":
            assert info.metadata == {"sh_degree": 0}
        elif spec.id == "dmb":
            assert info.metadata == {
                "channels": 1,
                "image_type": 1,
                "unit": "unknown",
                "scale_to_meters": 0.0,
                "invalid_policy": "zero",
            }
        elif spec.id == "bal":
            assert info.metadata == {
                "num_cameras": 1,
                "num_images": 1,
                "num_points3D": 1,
                "num_observations": 1,
            }

    nvm = next(spec for spec in buffer_codecs if spec.id == "nvm")
    reconstruction = nvm.reader(nvm.data)
    for format_id, writer in (
        ("colmap_sparse", _core.write_colmap_sparse),
        ("colmap_sparse_txt", _core.write_colmap_txt),
    ):
        path = tmp_path / f"inspect-{format_id}"
        path.mkdir()
        writer(reconstruction, str(path))
        info = sceneio.inspect(path, format=format_id)
        decoded = sceneio.read(path, format=format_id)
        assert info.byte_size == sum(item.stat().st_size for item in path.iterdir())
        _assert_inspection_matches(info, decoded)


def test_inspect_large_npy_reads_only_header(tmp_path):
    header = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        header,
        {"descr": "<f4", "fortran_order": False, "shape": (32 * 1024 * 1024,)},
    )
    path = tmp_path / "large.npy"
    with path.open("wb") as stream:
        stream.write(header.getvalue())
        stream.truncate(stream.tell() + 128 * 1024 * 1024)

    sceneio.inspect(path)
    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.shape == (32 * 1024 * 1024,)
    assert info.dtype == "float32"
    assert info.byte_size > 128 * 1024 * 1024
    assert peak < 256 * 1024
    assert _fresh_process_inspect_rss(path, "npy") < 8 * 1024 * 1024


def test_inspect_large_xyz_streams_with_bounded_python_memory(tmp_path):
    path = tmp_path / "large.xyz"
    block = b"0 0 0\n" * 8192
    repetitions = 256
    with path.open("wb") as stream:
        for _ in range(repetitions):
            stream.write(block)

    sceneio.inspect(path)
    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.count == repetitions * 8192
    assert info.shape == (repetitions * 8192, 3)
    assert info.byte_size == len(block) * repetitions
    assert peak < 256 * 1024
    assert _fresh_process_inspect_rss(path, "xyz") < 8 * 1024 * 1024


def test_inspection_is_immutable_and_bundler_counts_registered_cameras(tmp_path):
    npy_path = tmp_path / "immutable.npy"
    sceneio.write(np.arange(4, dtype=np.int16), npy_path)
    info = sceneio.inspect(npy_path)
    with pytest.raises(TypeError):
        info.metadata["fortran_order"] = True
    with pytest.raises(AttributeError):
        info.shape = (2, 2)

    bundler = tmp_path / "partial.out"
    bundler.write_bytes(
        b"# Bundle file v0.3\n2 0\n"
        + b"0 " * 14
        + b"0\n"
        + b"1 0 0 1 0 0 0 1 0 0 0 1 0 0 0\n"
    )
    decoded = sceneio.read(bundler)
    inspected = sceneio.inspect(bundler)
    assert decoded.num_images == decoded.num_cameras == 1
    assert inspected.count == 1
    assert inspected.metadata["num_images"] == inspected.metadata["num_cameras"] == 1


@pytest.mark.parametrize(
    ("format_id", "contents"),
    [
        ("npy", b"\x93NUMPY\x01"),
        ("npy", b"\x93NUMPY\x02\x00\x01\x00\x10\x00"),
        ("png", b"\x89PNG\r\n\x1a\n"),
        ("flo", b"PIEH"),
        ("splat", b"x"),
    ],
)
def test_inspect_normalizes_truncated_header_errors(tmp_path, format_id, contents):
    path = tmp_path / f"bad-{format_id}.data"
    path.write_bytes(contents)
    with pytest.raises(sceneio.FormatError, match=f"inspecting .* as '{format_id}'"):
        sceneio.inspect(path, format=format_id)


def test_inspect_all_single_file_codecs_reject_truncated_headers(
    tmp_path, buffer_codecs
):
    for spec in buffer_codecs:
        path = tmp_path / f"truncated-{spec.id}.bin"
        # PTS metadata is complete after its short decimal count line; use a
        # genuinely missing header rather than truncating into the first row.
        if spec.id == "pts":
            truncated = b""
        elif spec.id == "g2o":
            # The canonical prefix is a comment and an empty graph is valid;
            # truncate a data-record tag instead.
            truncated = b"VERT"
        else:
            truncated = spec.data[:4]
        path.write_bytes(truncated)
        with pytest.raises(sceneio.FormatError):
            sceneio.inspect(path, format=spec.id)


def test_inspect_colmap_directories_reject_truncated_or_missing_headers(
    tmp_path
):
    binary = tmp_path / "binary"
    binary.mkdir()
    for filename in ("cameras.bin", "images.bin", "points3D.bin"):
        (binary / filename).write_bytes(b"\0" * 4)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(binary, format="colmap_sparse")

    text = tmp_path / "text"
    text.mkdir()
    (text / "cameras.txt").write_bytes(b"# incomplete model\n")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(text, format="colmap_sparse_txt")


def _png_chunk(kind, payload):
    body = kind + payload
    return (
        struct.pack(">I", len(payload))
        + body
        + struct.pack(">I", binascii.crc32(body))
    )


@pytest.mark.parametrize(
    ("format_id", "contents"),
    [
        ("pfm", b"Pf\n1 1\nnan\n" + struct.pack("<f", 0.0)),
        ("hdr", b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n+Y 1 +X 1\n"),
        ("hdr", b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n-Y 1 +X 1\n"),
        (
            "png",
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 200_001, 1, 8, 2, 0, 0, 0))
            + _png_chunk(b"IDAT", b""),
        ),
        (
            "png",
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 16, 3, 0, 0, 0))
            + _png_chunk(b"PLTE", b"\0\0\0")
            + _png_chunk(b"IDAT", b""),
        ),
        (
            "webp",
            b"RIFF"
            + struct.pack("<I", 22)
            + b"WEBPVP8X"
            + struct.pack("<I", 10)
            + bytes(10),
        ),
    ],
)
def test_inspect_rejects_unsupported_header_semantics(tmp_path, format_id, contents):
    path = tmp_path / f"unsupported-{format_id}.data"
    path.write_bytes(contents)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format=format_id)


def test_inspect_rejects_npy_extra_fields_and_excess_dimensions(tmp_path):
    for index, header_dict in enumerate(
        (
            {
                "descr": "<f4",
                "fortran_order": False,
                "shape": (1,),
                "extra": 1,
            },
            {
                "descr": "<f4",
                "fortran_order": False,
                "shape": (1,) * 65,
            },
        )
    ):
        header = io.BytesIO()
        np.lib.format.write_array_header_2_0(header, header_dict)
        path = tmp_path / f"unsupported-{index}.npy"
        path.write_bytes(header.getvalue())
        with pytest.raises(sceneio.FormatError):
            sceneio.inspect(path)


def test_inspect_npy_reuses_core_header_grammar(tmp_path):
    header = (
        b"{'descr': '<f4', 'fortran_order': False, 'shape': (1), }\n"
    )
    path = tmp_path / "noncanonical-singleton.npy"
    path.write_bytes(
        b"\x93NUMPY\x01\x00"
        + struct.pack("<H", len(header))
        + header
        + struct.pack("<f", 3.0)
    )
    decoded = sceneio.read(path)
    info = sceneio.inspect(path)
    np.testing.assert_array_equal(decoded, np.array([3.0], dtype=np.float32))
    assert info.shape == decoded.shape == (1,)
    assert info.dtype == "float32"


def test_inspect_gaussian_ply_matches_big_endian_and_ignores_nonvertex_properties(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "gaussian_ply")
    header_end = spec.data.index(b"end_header\n") + len(b"end_header\n")
    header, body = spec.data[:header_end], spec.data[header_end:]
    big_endian = header.replace(
        b"format binary_little_endian 1.0",
        b"format binary_big_endian 1.0",
    ) + np.frombuffer(body, dtype="<f4").byteswap().tobytes()
    big_path = tmp_path / "big-endian.ply"
    big_path.write_bytes(big_endian)
    big_info = sceneio.inspect(big_path, format="gaussian_ply")
    _assert_inspection_matches(
        big_info, sceneio.read(big_path, format="gaussian_ply")
    )
    assert big_info.metadata["byte_order"] == "big"

    foreign_properties = b"element face 0\n" + b"".join(
        f"property float f_rest_{index}\n".encode() for index in range(9)
    )
    extra_path = tmp_path / "nonvertex-properties.ply"
    extra_path.write_bytes(
        spec.data.replace(b"end_header\n", foreign_properties + b"end_header\n", 1)
    )
    extra_info = sceneio.inspect(extra_path, format="gaussian_ply")
    decoded = sceneio.read(extra_path, format="gaussian_ply")
    _assert_inspection_matches(extra_info, decoded)
    assert extra_info.metadata["sh_degree"] == decoded.sh_degree == 3


@pytest.mark.parametrize(
    "replacement",
    [
        b"element vertex -1",
        b"element vertex 11\nproperty double x",
    ],
)
def test_inspect_gaussian_ply_rejects_invalid_vertex_headers(
    tmp_path, buffer_codecs, replacement
):
    spec = next(item for item in buffer_codecs if item.id == "gaussian_ply")
    payload = spec.data.replace(b"element vertex 11", replacement, 1)
    path = tmp_path / "bad.ply"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="gaussian_ply")


def test_inspect_spz_rejects_invalid_fractional_bits(tmp_path, buffer_codecs):
    spec = next(item for item in buffer_codecs if item.id == "spz")
    raw = bytearray(gzip.decompress(spec.data))
    raw[13] = 0
    path = tmp_path / "bad.spz"
    path.write_bytes(gzip.compress(raw))
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="spz")


@pytest.mark.parametrize(
    ("container", "field", "value", "message"),
    [
        ("legacy", "flags", 0x01, "antialiased splats are unsupported"),
        ("legacy", "flags", 0x02, "header extensions are unsupported"),
        ("legacy", "flags", 0x80, "unsupported header flags"),
        ("legacy", "reserved", 1, "non-zero reserved header byte"),
        ("v4", "flags", 0x01, "antialiased splats are unsupported"),
        ("v4", "flags", 0x02, "header extensions are unsupported"),
        ("v4", "flags", 0x80, "unsupported header flags"),
        ("v4", "reserved", 1, "reserved header bytes must be zero"),
        ("v4", "toc_offset", 64, "unsupported header extension zone"),
    ],
)
def test_inspect_spz_rejects_profiles_that_read_rejects(
    tmp_path, buffer_codecs, container, field, value, message
):
    spec = next(item for item in buffer_codecs if item.id == "spz")
    if container == "legacy":
        raw = bytearray(gzip.decompress(spec.data))
        offset = 14 if field == "flags" else 15
        raw[offset] = value
        payload = gzip.compress(raw)
    else:
        payload = bytearray(_core.write_spz(spec.value, version=4))
        if field == "flags":
            payload[14] = value
        elif field == "reserved":
            payload[20] = value
        else:
            struct.pack_into("<I", payload, 16, value)

    path = tmp_path / f"unsupported-{container}-{field}-{value}.spz"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.inspect(path, format="spz")
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read(path, format="spz")


@pytest.mark.parametrize("format_id", ["transforms_json", "openmvg"])
def test_inspect_json_error_messages_are_bounded(tmp_path, format_id):
    path = tmp_path / f"bad-{format_id}.json"
    path.write_bytes(b'{"unterminated":"' + b"x" * (32 * 1024 * 1024))
    with pytest.raises(sceneio.FormatError) as caught:
        sceneio.inspect(path, format=format_id)
    assert len(str(caught.value.__cause__)) < 512
    assert (
        _fresh_process_inspect_rss(path, format_id, expect_error=True)
        < 16 * 1024 * 1024
    )


@pytest.mark.parametrize(
    ("format_id", "prefix"),
    [
        ("transforms_json", b'{"frames":[],"padding":['),
        (
            "openmvg",
            b'{"views":[],"intrinsics":[],"extrinsics":[],"structure":[],'
            b'"padding":[',
        ),
    ],
)
def test_inspect_large_valid_json_streams_without_a_dom(
    tmp_path, format_id, prefix
):
    path = tmp_path / f"large-{format_id}.json"
    with path.open("wb") as stream:
        stream.write(prefix)
        for _ in range(1024):
            stream.write(b"0," * 4096)
        stream.write(b"0]}")
    info = sceneio.inspect(path, format=format_id)
    assert info.count == 0
    assert (
        _fresh_process_inspect_rss(path, format_id)
        < 24 * 1024 * 1024
    )


def test_inspect_bundler_header_allocation_is_bounded(tmp_path):
    path = tmp_path / "large.out"
    path.write_bytes(b"x" * (2 * 1024 * 1024))
    tracemalloc.start()
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="bundler")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 256 * 1024


@pytest.mark.parametrize(
    "format_id", ["bal", "bundler", "nvm", "pfm", "tum", "kitti"]
)
def test_inspect_text_token_or_line_caps_bound_mapped_rss(
    tmp_path, format_id
):
    path = tmp_path / f"large-{format_id}.txt"
    path.write_bytes(b"x" * (32 * 1024 * 1024))
    assert (
        _fresh_process_inspect_rss(path, format_id, expect_error=True)
        < 8 * 1024 * 1024
    )


def test_inspect_exr_duplicate_channel_attributes_are_bounded(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "exr")
    payload = spec.data
    offset = 8
    channel_attribute = None
    while payload[offset] != 0:
        start = offset
        name_end = payload.index(b"\0", offset)
        name = payload[offset:name_end]
        type_end = payload.index(b"\0", name_end + 1)
        size_offset = type_end + 1
        size = struct.unpack(
            "<I", payload[size_offset : size_offset + 4]
        )[0]
        offset = size_offset + 4 + size
        if name == b"channels":
            channel_attribute = payload[start:offset]
    assert channel_attribute is not None
    path = tmp_path / "duplicate-channels.exr"
    path.write_bytes(
        payload[:offset] + channel_attribute * 100_000 + payload[offset:]
    )
    with pytest.raises(sceneio.FormatError, match="duplicate channels"):
        sceneio.inspect(path, format="exr")
    assert (
        _fresh_process_inspect_rss(path, "exr", expect_error=True)
        < 8 * 1024 * 1024
    )


def test_inspect_xyz_supports_unicode_paths(tmp_path):
    path = tmp_path / "流-é-🙂.xyz"
    path.write_bytes(b"1 2 3\n")
    info = sceneio.inspect(path, format="xyz")
    assert info.count == 1
    assert info.shape == (1, 3)


def test_inspect_colmap_text_skips_unbounded_observation_lines(tmp_path):
    path = tmp_path / "sparse"
    path.mkdir()
    (path / "cameras.txt").write_bytes(b"# empty\n")
    (path / "images.txt").write_bytes(
        b"1 1 0 0 0 0 0 0 1 image.jpg\n"
        + b"0 " * (16 * 1024 * 1024)
    )
    (path / "points3D.txt").write_bytes(b"")
    info = sceneio.inspect(path, format="colmap_sparse_txt")
    assert info.metadata == {
        "num_cameras": 0,
        "num_images": 1,
        "num_points3D": 0,
    }
    assert (
        _fresh_process_inspect_rss(path, "colmap_sparse_txt")
        < 8 * 1024 * 1024
    )


def test_inspect_nvm_uses_the_formats_token_stream(tmp_path):
    path = tmp_path / "wrapped.nvm"
    path.write_bytes(b"NVM_V3\n1\na.jpg 800\n1 0 0 0 1 2 3 0 0\n0\n0\n")
    decoded = sceneio.read(path, format="nvm")
    info = sceneio.inspect(path, format="nvm")
    assert decoded.num_images == info.count == 1
    assert info.metadata["num_points3D"] == decoded.num_points3D == 0


def test_inspect_nvm_token_cap_matches_reader(tmp_path):
    path = tmp_path / "long-name.nvm"
    name = b"a" * (1024 * 1024 + 1)
    path.write_bytes(
        b"NVM_V3\n1\n"
        + name
        + b" 800 1 0 0 0 1 2 3 0 0\n0\n0\n"
    )
    with pytest.raises(sceneio.FormatError, match="token exceeds"):
        sceneio.read(path, format="nvm")
    with pytest.raises(sceneio.FormatError, match="token exceeds"):
        sceneio.inspect(path, format="nvm")


@pytest.mark.parametrize("format_id", ["transforms_json", "openmvg"])
def test_json_scene_duplicate_root_sections_use_last_value(
    tmp_path, buffer_codecs, format_id
):
    spec = next(item for item in buffer_codecs if item.id == format_id)
    document = spec.data.rstrip()
    suffix = (
        ',"frames":[]}'
        if format_id == "transforms_json"
        else ',"views":[],"structure":[]}'
    )
    payload = document[:-1] + suffix.encode()
    path = tmp_path / f"duplicate-{format_id}.json"
    path.write_bytes(payload)
    decoded = sceneio.read(path, format=format_id)
    info = sceneio.inspect(path, format=format_id)
    expected = decoded.num_images if format_id == "openmvg" else decoded.num_views
    assert info.count == expected == 0


@pytest.mark.parametrize(
    "section", ["views", "intrinsics", "extrinsics", "structure"]
)
def test_inspect_openmvg_rejects_duplicate_map_keys_like_reader(
    tmp_path, buffer_codecs, section
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    document[section].append(document[section][0])
    path = tmp_path / f"duplicate-{section}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="duplicate"):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


def test_inspect_openmvg_rejects_missing_intrinsic_like_reader(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    document["views"][0]["value"]["ptr_wrapper"]["data"]["id_intrinsic"] = (
        0xFFFFFFFE
    )
    path = tmp_path / "missing-intrinsic.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="missing intrinsic"):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


def test_inspect_openmvg_rejects_unknown_observation_view_like_reader(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    document["structure"][0]["value"]["observations"][0]["key"] = 999999
    path = tmp_path / "missing-observation-view.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="not a posed view"):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


@pytest.mark.parametrize("section", ["intrinsics", "extrinsics", "structure"])
def test_inspect_openmvg_requires_map_entry_value_like_reader(
    tmp_path, buffer_codecs, section
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    del document[section][0]["value"]
    path = tmp_path / f"missing-{section}-value.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="missing 'value'"):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


def test_inspect_openmvg_nested_duplicate_uses_last_value(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    value = document["views"][0]["value"]
    compact = json.dumps(document, separators=(",", ":"))
    encoded_value = json.dumps(value, separators=(",", ":"))
    invalid_last = encoded_value[:-1] + ',"ptr_wrapper":null}'
    path = tmp_path / "duplicate-ptr-wrapper.json"
    path.write_text(compact.replace(encoded_value, invalid_last, 1), encoding="utf-8")
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="openmvg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="openmvg")


@pytest.mark.parametrize("section", ["views", "intrinsics"])
def test_inspect_openmvg_nested_duplicate_can_recover_with_last_value(
    tmp_path, buffer_codecs, section
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    value = document[section][0]["value"]
    compact = json.dumps(document, separators=(",", ":"))
    encoded_value = json.dumps(value, separators=(",", ":"))
    needle = '"value":' + encoded_value
    replacement = (
        '"value":{"ptr_wrapper":null},"value":' + encoded_value
    )
    path = tmp_path / f"recover-{section}-value.json"
    path.write_text(compact.replace(needle, replacement, 1), encoding="utf-8")
    decoded = sceneio.read(path, format="openmvg")
    info = sceneio.inspect(path, format="openmvg")
    _assert_inspection_matches(info, decoded)


def test_inspect_openmvg_duplicate_observations_use_last_value(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "openmvg")
    document = json.loads(spec.data)
    observations = document["structure"][0]["value"]["observations"]
    compact = json.dumps(document, separators=(",", ":"))
    encoded = json.dumps(observations, separators=(",", ":"))
    needle = '"observations":' + encoded
    invalid = '[{"key":999999,"value":{"x":[0,0]}}]'
    replacement = '"observations":' + invalid + ',"observations":' + encoded
    path = tmp_path / "recover-observations.json"
    path.write_text(compact.replace(needle, replacement, 1), encoding="utf-8")
    decoded = sceneio.read(path, format="openmvg")
    info = sceneio.inspect(path, format="openmvg")
    _assert_inspection_matches(info, decoded)


def test_inspect_npz_rejects_unsupported_compression_like_reader(tmp_path):
    path = tmp_path / "bzip2.npz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_BZIP2) as archive:
        archive.writestr("a.npy", bytes(_core.write_npy(np.arange(4))))
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="npz")
    with pytest.raises(sceneio.FormatError, match="stored and deflate"):
        sceneio.inspect(path, format="npz")


def test_inspect_npz_skips_unsupported_directory_members_like_reader(tmp_path):
    path = tmp_path / "directory-only.npz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_BZIP2) as archive:
        archive.writestr("folder/", b"")
    decoded = sceneio.read(path, format="npz")
    info = sceneio.inspect(path, format="npz")
    assert list(decoded.keys()) == []
    assert info.count == 0


def test_inspect_npz_rejects_raw_non_utf8_filename_like_reader(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("a.npy", bytes(_core.write_npy(np.arange(4))))
    payload = bytearray(stream.getvalue())
    payload[30] = 0x82
    central = payload.index(b"PK\x01\x02")
    payload[central + 46] = 0x82
    path = tmp_path / "non-utf8.npz"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match="UTF-8"):
        sceneio.read(path, format="npz")
    with pytest.raises(sceneio.FormatError, match="UTF-8"):
        sceneio.inspect(path, format="npz")


@pytest.mark.parametrize("mutate", ["central_name", "local_method"])
def test_inspect_npz_rejects_local_central_disagreement_like_reader(
    tmp_path, mutate
):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("a.npy", bytes(_core.write_npy(np.arange(4))))
    payload = bytearray(stream.getvalue())
    central = payload.index(b"PK\x01\x02")
    if mutate == "central_name":
        payload[central + 46] = ord("b")
    else:
        payload[8:10] = struct.pack("<H", zipfile.ZIP_DEFLATED)
    path = tmp_path / f"{mutate}.npz"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match="local and central"):
        sceneio.read(path, format="npz")
    with pytest.raises(sceneio.FormatError, match="local and central"):
        sceneio.inspect(path, format="npz")


@pytest.mark.parametrize(
    "payload",
    [
        b"P5\n1# width\n 1\n255\n\x00",
        b"P5\n1 1# height\n255\n\x00",
        b"P5\n1 1 255# maxval\n\x00",
    ],
)
def test_inspect_netpbm_matches_inline_comment_grammar(tmp_path, payload):
    path = tmp_path / "comment.pgm"
    path.write_bytes(payload)
    decoded = sceneio.read(path, format="netpbm")
    info = sceneio.inspect(path, format="netpbm")
    _assert_inspection_matches(info, decoded)


def test_inspect_flo_matches_reader_trailing_byte_tolerance(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "flo")
    path = tmp_path / "trailing.flo"
    path.write_bytes(spec.data + b"ignored")
    decoded = sceneio.read(path, format="flo")
    info = sceneio.inspect(path, format="flo")
    _assert_inspection_matches(info, decoded)
    assert info.byte_size == len(spec.data) + len(b"ignored")


def test_inspect_rejects_corrupt_png_metadata_crc(tmp_path, buffer_codecs):
    spec = next(item for item in buffer_codecs if item.id == "png")
    payload = bytearray(spec.data)
    payload[29] ^= 1
    path = tmp_path / "bad-crc.png"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match="CRC"):
        sceneio.inspect(path, format="png")


def test_inspect_png_rejects_duplicate_critical_chunk_like_reader(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "png")
    ihdr_chunk = spec.data[8:33]
    path = tmp_path / "duplicate-ihdr.png"
    path.write_bytes(spec.data[:33] + ihdr_chunk + spec.data[33:])
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="png")
    with pytest.raises(sceneio.FormatError, match="critical chunk"):
        sceneio.inspect(path, format="png")


def test_inspect_rejects_inconsistent_jpeg_sof_length(tmp_path, buffer_codecs):
    spec = next(item for item in buffer_codecs if item.id == "jpeg")
    payload = bytearray(spec.data)
    marker = payload.index(b"\xff\xc0")
    payload[marker + 2 : marker + 4] = struct.pack(">H", 8)
    path = tmp_path / "bad-sof.jpg"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError, match="SOF length"):
        sceneio.inspect(path, format="jpeg")


def test_inspect_jpeg_rejects_duplicate_sof_like_reader(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "jpeg")
    marker = spec.data.index(b"\xff\xc0")
    length = struct.unpack(">H", spec.data[marker + 2 : marker + 4])[0]
    segment = spec.data[marker : marker + 2 + length]
    path = tmp_path / "duplicate-sof.jpg"
    path.write_bytes(spec.data[:marker] + segment + spec.data[marker:])
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="jpeg")
    with pytest.raises(sceneio.FormatError, match="duplicate SOF"):
        sceneio.inspect(path, format="jpeg")


@pytest.mark.parametrize("mutation", ["long_sos", "unsupported_sof"])
def test_inspect_jpeg_rejects_unsupported_marker_topology_like_reader(
    tmp_path, buffer_codecs, mutation
):
    spec = next(item for item in buffer_codecs if item.id == "jpeg")
    payload = bytearray(spec.data)
    if mutation == "long_sos":
        marker = payload.index(b"\xff\xda")
        payload[marker + 2 : marker + 4] = b"\xff\xff"
    else:
        marker = payload.index(b"\xff\xc0")
        length = struct.unpack(">H", payload[marker + 2 : marker + 4])[0]
        segment = bytearray(payload[marker : marker + 2 + length])
        segment[1] = 0xC3
        payload[marker:marker] = segment
    path = tmp_path / f"{mutation}.jpg"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="jpeg")
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="jpeg")


def test_inspect_rejects_mismatched_webp_extended_canvas(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "webp")
    chunks = spec.data[12:]
    assert chunks[:4] == b"VP8L"
    height, width = spec.value.height, spec.value.width
    canvas = (
        b"\x10\0\0\0"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    extended_chunks = b"VP8X" + struct.pack("<I", 10) + canvas + chunks
    valid = b"RIFF" + struct.pack("<I", 4 + len(extended_chunks)) + b"WEBP" + extended_chunks
    valid_path = tmp_path / "valid-extended.webp"
    valid_path.write_bytes(valid)
    _assert_inspection_matches(
        sceneio.inspect(valid_path, format="webp"),
        sceneio.read(valid_path, format="webp"),
    )

    invalid = bytearray(valid)
    invalid[24:27] = (width + 10).to_bytes(3, "little")
    invalid_path = tmp_path / "bad-canvas.webp"
    invalid_path.write_bytes(invalid)
    with pytest.raises(sceneio.FormatError, match="canvas"):
        sceneio.inspect(invalid_path, format="webp")


def test_inspect_webp_uses_first_image_bitstream_like_reader(tmp_path):
    first = bytes(
        _core.write_webp(
            _core.image(np.zeros((2, 3, 3), dtype=np.uint8), color_space="srgb")
        )
    )
    second = bytes(
        _core.write_webp(
            _core.image(np.zeros((5, 7, 3), dtype=np.uint8), color_space="srgb")
        )
    )
    chunks = first[12:] + second[12:]
    payload = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WEBP" + chunks
    path = tmp_path / "duplicate-bitstream.webp"
    path.write_bytes(payload)
    decoded = sceneio.read(path, format="webp")
    info = sceneio.inspect(path, format="webp")
    assert (decoded.height, decoded.width) == info.shape[:2] == (2, 3)


def test_inspect_webp_uses_first_extended_canvas_like_reader(tmp_path):
    encoded = bytes(
        _core.write_webp(
            _core.image(np.zeros((2, 3, 3), dtype=np.uint8), color_space="srgb")
        )
    )

    def vp8x(height, width):
        payload = (
            b"\0\0\0\0"
            + (width - 1).to_bytes(3, "little")
            + (height - 1).to_bytes(3, "little")
        )
        return b"VP8X" + struct.pack("<I", len(payload)) + payload

    chunks = vp8x(2, 3) + vp8x(5, 7) + encoded[12:]
    valid = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WEBP" + chunks
    valid_path = tmp_path / "duplicate-canvas-valid.webp"
    valid_path.write_bytes(valid)
    decoded = sceneio.read(valid_path, format="webp")
    info = sceneio.inspect(valid_path, format="webp")
    assert (decoded.height, decoded.width) == info.shape[:2] == (2, 3)

    reversed_chunks = vp8x(5, 7) + vp8x(2, 3) + encoded[12:]
    invalid = (
        b"RIFF"
        + struct.pack("<I", 4 + len(reversed_chunks))
        + b"WEBP"
        + reversed_chunks
    )
    invalid_path = tmp_path / "duplicate-canvas-invalid.webp"
    invalid_path.write_bytes(invalid)
    with pytest.raises(sceneio.FormatError):
        sceneio.read(invalid_path, format="webp")
    with pytest.raises(sceneio.FormatError, match="canvas"):
        sceneio.inspect(invalid_path, format="webp")


def test_inspect_webp_ignores_advisory_extended_alpha_flag(tmp_path):
    encoded = bytes(
        _core.write_webp(
            _core.image(np.zeros((2, 3, 3), dtype=np.uint8), color_space="srgb")
        )
    )
    canvas = b"\x10\0\0\0" + (2).to_bytes(3, "little") + (1).to_bytes(
        3, "little"
    )
    chunks = b"VP8X" + struct.pack("<I", 10) + canvas + encoded[12:]
    payload = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WEBP" + chunks
    path = tmp_path / "advisory-alpha.webp"
    path.write_bytes(payload)
    decoded = sceneio.read(path, format="webp")
    info = sceneio.inspect(path, format="webp")
    assert decoded.channels == info.channels == 3


@pytest.mark.parametrize(
    ("offset", "value"),
    [
        (96, struct.pack("<I", 1)),
        (105, struct.pack("<H", 1)),
    ],
)
def test_inspect_rejects_invalid_las_record_header(
    tmp_path, buffer_codecs, offset, value
):
    spec = next(item for item in buffer_codecs if item.id == "las")
    payload = bytearray(spec.data)
    payload[offset : offset + len(value)] = value
    path = tmp_path / "bad.las"
    path.write_bytes(payload)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(path, format="las")


def test_inspect_gaussian_ply_has_no_arbitrary_header_line_cap(
    tmp_path, buffer_codecs
):
    spec = next(item for item in buffer_codecs if item.id == "gaussian_ply")
    comments = b"comment metadata\n" * 10_001
    path = tmp_path / "many-comments.ply"
    path.write_bytes(
        spec.data.replace(b"end_header\n", comments + b"end_header\n", 1)
    )
    decoded = sceneio.read(path, format="gaussian_ply")
    info = sceneio.inspect(path, format="gaussian_ply")
    _assert_inspection_matches(info, decoded)
