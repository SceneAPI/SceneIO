"""Independent parity suite for repository-owned COLMAP dense-MVS codecs."""

from __future__ import annotations

import gc
import json
import mmap
import os
import struct
import subprocess
import sys
import textwrap
import threading
import time
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _depth_golden() -> bytes:
    return b"3&2&1&" + struct.pack(
        "<6I",
        0x3F800000,
        0x80000000,
        0x7FC00042,
        0x7F800000,
        0xFF800000,
        0x00000001,
    )


def _normal_golden() -> bytes:
    return b"2&2&3&" + struct.pack("<12f", *range(1, 13))


def _consistency_golden() -> bytes:
    return b"3&2&1&" + struct.pack(
        "<12i", 0, 0, 2, 7, 3, 2, 0, 1, 5, 1, 1, 0
    )


def _visibility_golden() -> bytes:
    return (
        struct.pack("<Q", 4)
        + struct.pack("<3I", 2, 0, 2)
        + struct.pack("<I", 0)
        + struct.pack("<2I", 1, 7)
        + struct.pack("<4I", 3, 1, 3, 5)
    )


def _assert_depth(record):
    assert isinstance(record, _core.DepthMap)
    assert record.depth.shape == (2, 3)
    assert record.depth.view(np.uint32).tolist() == [
        [0x3F800000, 0x80000000, 0x7FC00042],
        [0x7F800000, 0xFF800000, 0x00000001],
    ]
    assert record.unit == "unknown"
    assert record.scale_to_meters == 0.0
    assert record.invalid_policy == "nonpositive"
    assert record.depth_convention == "camera_z"


def _assert_normal(record):
    assert isinstance(record, _core.NormalMap)
    np.testing.assert_array_equal(
        record.normals,
        np.array(
            [
                [[1, 5, 9], [2, 6, 10]],
                [[3, 7, 11], [4, 8, 12]],
            ],
            np.float32,
        ),
    )


def _assert_consistency(record):
    assert isinstance(record, _core.ConsistencyGraph)
    assert record.columns.tolist() == [0, 2, 1]
    assert record.rows.tolist() == [0, 0, 1]
    assert record.offsets.tolist() == [0, 2, 3, 3]
    assert record.image_indices.tolist() == [7, 3, 5]


def _assert_visibility(record):
    assert isinstance(record, _core.PointVisibility)
    assert record.offsets.tolist() == [0, 2, 2, 3, 6]
    assert record.image_indices.tolist() == [0, 2, 7, 1, 3, 5]


@pytest.mark.parametrize(
    ("payload", "reader", "writer", "assert_record"),
    [
        (
            _depth_golden(),
            _core.read_colmap_mvs_depth,
            _core.write_colmap_mvs_depth,
            _assert_depth,
        ),
        (
            _normal_golden(),
            _core.read_colmap_mvs_normal,
            _core.write_colmap_mvs_normal,
            _assert_normal,
        ),
        (
            _consistency_golden(),
            _core.read_colmap_mvs_consistency,
            _core.write_colmap_mvs_consistency,
            _assert_consistency,
        ),
        (
            _visibility_golden(),
            _core.read_colmap_fused_visibility,
            _core.write_colmap_fused_visibility,
            _assert_visibility,
        ),
    ],
)
def test_hand_built_goldens_are_bit_exact(
    payload, reader, writer, assert_record
):
    record = reader(payload)
    assert_record(record)
    assert writer(record) == payload


@pytest.mark.parametrize(
    ("payload", "reader", "assert_record"),
    [
        (_depth_golden(), _core.read_colmap_mvs_depth, _assert_depth),
        (_normal_golden(), _core.read_colmap_mvs_normal, _assert_normal),
        (
            _consistency_golden(),
            _core.read_colmap_mvs_consistency,
            _assert_consistency,
        ),
        (
            _visibility_golden(),
            _core.read_colmap_fused_visibility,
            _assert_visibility,
        ),
    ],
)
def test_bytes_and_mmap_are_identical_and_mapping_can_close(
    tmp_path, payload, reader, assert_record
):
    path = tmp_path / "source.bin"
    path.write_bytes(payload)
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        record = reader(mapped)
        mapped.close()
    assert_record(record)
    path.rename(tmp_path / "renamed.bin")


def test_normal_hostile_float_bits_preserve_planes_exactly():
    bits = np.array(
        [
            0x80000000,
            0x7FC00042,
            0x00000001,
            0xFF800000,
            0x3F800000,
            0xBF800000,
            0x7F800000,
            0xFFC00011,
            0x00800000,
            0x80800000,
            0x00000000,
            0x40490FDB,
        ],
        np.uint32,
    )
    payload = b"2&2&3&" + bits.astype("<u4").tobytes()
    record = _core.read_colmap_mvs_normal(payload)
    expected = bits.reshape(3, 2, 2).transpose(1, 2, 0)
    np.testing.assert_array_equal(record.normals.view(np.uint32), expected)
    assert _core.write_colmap_mvs_normal(record) == payload


def test_window_reads_match_full_slices():
    depth = _core.read_colmap_mvs_depth(_depth_golden())
    depth_window = _core.read_colmap_mvs_depth_window(
        _depth_golden(), 0, 2, 1, 3
    )
    np.testing.assert_array_equal(depth_window.depth, depth.depth[:, 1:3])
    assert depth_window.depth_convention == "camera_z"

    normal = _core.read_colmap_mvs_normal(_normal_golden())
    normal_window = _core.read_colmap_mvs_normal_window(
        _normal_golden(), 0, 2, 1, 2
    )
    np.testing.assert_array_equal(
        normal_window.normals, normal.normals[:, 1:2]
    )


@pytest.mark.parametrize(
    ("reader", "payload"),
    [
        (_core.read_colmap_mvs_depth, b""),
        (_core.read_colmap_mvs_depth, b"2&2&"),
        (_core.read_colmap_mvs_depth, b"x&2&1&"),
        (_core.read_colmap_mvs_depth, b"0&2&1&"),
        (_core.read_colmap_mvs_depth, b"2&2&3&" + b"\0" * 48),
        (_core.read_colmap_mvs_depth, b"2&2&1&" + b"\0" * 15),
        (_core.read_colmap_mvs_depth, b"2&2&1&" + b"\0" * 17),
        (_core.read_colmap_mvs_normal, b"2&2&1&" + b"\0" * 16),
        (_core.read_colmap_mvs_consistency, b"2&2&1&\0"),
        (
            _core.read_colmap_mvs_consistency,
            b"2&2&1&" + struct.pack("<2i", 0, 0),
        ),
        (
            _core.read_colmap_mvs_consistency,
            b"2&2&1&" + struct.pack("<3i", -1, 0, 0),
        ),
        (
            _core.read_colmap_mvs_consistency,
            b"2&2&1&" + struct.pack("<3i", 2, 0, 0),
        ),
        (
            _core.read_colmap_mvs_consistency,
            b"2&2&1&" + struct.pack("<3i", 0, 0, -1),
        ),
        (
            _core.read_colmap_mvs_consistency,
            b"2&2&1&" + struct.pack("<3i", 0, 0, 1),
        ),
        (_core.read_colmap_fused_visibility, b"\0" * 7),
        (
            _core.read_colmap_fused_visibility,
            struct.pack("<Q", 1),
        ),
        (
            _core.read_colmap_fused_visibility,
            struct.pack("<QI", 1, 1),
        ),
        (
            _core.read_colmap_fused_visibility,
            struct.pack("<QII", 1, 1, 2**31),
        ),
        (
            _core.read_colmap_fused_visibility,
            struct.pack("<QI", 0, 1),
        ),
    ],
)
def test_malformed_payloads_reject(reader, payload):
    with pytest.raises(ValueError):
        reader(payload)


def test_empty_visibility_is_valid():
    record = _core.read_colmap_fused_visibility(struct.pack("<Q", 0))
    assert record.num_points == 0
    assert record.offsets.tolist() == [0]
    assert _core.write_colmap_fused_visibility(record) == struct.pack("<Q", 0)


@pytest.mark.parametrize(
    ("payload", "reader", "writer"),
    [
        (
            _depth_golden(),
            _core.read_colmap_mvs_depth,
            _core.write_colmap_mvs_depth,
        ),
        (
            _normal_golden(),
            _core.read_colmap_mvs_normal,
            _core.write_colmap_mvs_normal,
        ),
        (
            _consistency_golden(),
            _core.read_colmap_mvs_consistency,
            _core.write_colmap_mvs_consistency,
        ),
        (
            _visibility_golden(),
            _core.read_colmap_fused_visibility,
            _core.write_colmap_fused_visibility,
        ),
    ],
)
def test_direct_sink_matches_bytes_and_short_writes(
    tmp_path, payload, reader, writer
):
    record = reader(payload)
    path = tmp_path / "output.bin"
    _core._write_to_file(writer, record, path, _max_chunk=3)
    assert path.read_bytes() == payload


def test_public_registry_detect_inspect_partial_and_write(tmp_path):
    depth_path = (
        tmp_path
        / "stereo"
        / "depth_maps"
        / "nested"
        / "frame.geometric.bin"
    )
    depth_path.parent.mkdir(parents=True)
    depth_path.write_bytes(_depth_golden())
    assert sceneio.detect(depth_path) == "colmap_mvs_depth"
    decoded = sceneio.read(depth_path)
    _assert_depth(decoded)
    inspection = sceneio.inspect(depth_path)
    assert inspection.shape == (2, 3)
    assert inspection.dtype == "float32"
    assert inspection.metadata["depth_convention"] == "camera_z"
    window = sceneio.read_partial(
        depth_path, window=(0, 2, 1, 3)
    )
    np.testing.assert_array_equal(window.depth, decoded.depth[:, 1:3])

    normal_path = (
        tmp_path / "stereo" / "normal_maps" / "frame.photometric.bin"
    )
    normal_path.parent.mkdir(parents=True)
    normal_path.write_bytes(_normal_golden())
    assert sceneio.detect(normal_path) == "colmap_mvs_normal"
    _assert_normal(sceneio.read(normal_path))

    graph_path = (
        tmp_path
        / "stereo"
        / "consistency_graphs"
        / "frame.geometric.bin"
    )
    graph_path.parent.mkdir(parents=True)
    graph_path.write_bytes(_consistency_golden())
    assert sceneio.detect(graph_path) == "colmap_mvs_consistency"
    _assert_consistency(sceneio.read(graph_path))

    visibility_path = tmp_path / "fused.ply.vis"
    visibility_path.write_bytes(_visibility_golden())
    assert sceneio.detect(visibility_path) == "colmap_fused_visibility"
    _assert_visibility(sceneio.read(visibility_path))

    output = tmp_path / "copy.vis"
    sceneio.write(
        sceneio.read(visibility_path),
        output,
        format="colmap_fused_visibility",
    )
    assert output.read_bytes() == _visibility_golden()


def test_generic_bin_and_vis_names_require_explicit_format(tmp_path):
    matrix = tmp_path / "matrix.bin"
    matrix.write_bytes(_depth_golden())
    with pytest.raises(sceneio.FormatError):
        sceneio.detect(matrix)
    _assert_depth(sceneio.read(matrix, format="colmap_mvs_depth"))

    visibility = tmp_path / "generic.vis"
    visibility.write_bytes(_visibility_golden())
    with pytest.raises(sceneio.FormatError):
        sceneio.detect(visibility)
    _assert_visibility(
        sceneio.read(visibility, format="colmap_fused_visibility")
    )


def test_large_mmap_read_has_no_whole_file_python_bytes(tmp_path):
    height = width = 2048
    payload = (
        f"{width}&{height}&1&".encode()
        + np.zeros((height, width), dtype="<f4").tobytes()
    )
    path = tmp_path / "large.bin"
    path.write_bytes(payload)
    del payload
    gc.collect()
    tracemalloc.start()
    record = sceneio.read(path, format="colmap_mvs_depth")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert record.depth.shape == (height, width)
    assert peak < 1024 * 1024


def test_sparse_large_consistency_decode_does_not_reserve_link_payload():
    if "libasan" in os.environ.get("LD_PRELOAD", ""):
        pytest.skip("RSS bound excludes compiler-instrumented allocator state")
    script = textwrap.dedent(
        """
        import gc
        import json
        import pathlib
        import psutil
        import struct
        import tempfile

        import sceneio

        entries = 2_000_000
        row = struct.pack("<3i", 0, 0, 0)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "graph.bin"
            with path.open("wb") as stream:
                stream.write(b"1&1&1&")
                block = row * 8192
                for _ in range(entries // 8192):
                    stream.write(block)
                stream.write(row * (entries % 8192))
            encoded = path.stat().st_size
            gc.collect()
            process = psutil.Process()
            baseline = process.memory_info().rss
            graph = sceneio.read(
                path,
                format="colmap_mvs_consistency",
            )
            current = process.memory_info().rss
            print(json.dumps({
                "encoded": encoded,
                "delta": current - baseline,
                "entries": graph.num_entries,
                "links": graph.num_image_indices,
            }))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    measured = json.loads(result.stdout)
    assert measured["entries"] == 2_000_000
    assert measured["links"] == 0
    assert measured["delta"] < measured["encoded"] * 2


def test_pycolmap_depth_producer_and_consumer(tmp_path):
    pycolmap = pytest.importorskip("pycolmap")
    source = np.array(
        [[0.0, 1.25, -0.0], [2.5, 4.0, -1.0]], np.float32
    )
    upstream = pycolmap.DepthMap.from_array(source, -1.0, 4.0)
    upstream_path = tmp_path / "upstream.bin"
    upstream.write(upstream_path)
    ours = sceneio.read(upstream_path, format="colmap_mvs_depth")
    np.testing.assert_array_equal(
        ours.depth.view(np.uint32), source.view(np.uint32)
    )

    ours_path = tmp_path / "ours.bin"
    sceneio.write(ours, ours_path, format="colmap_mvs_depth")
    consumed = pycolmap.DepthMap()
    consumed.read(ours_path)
    np.testing.assert_array_equal(
        consumed.to_array().view(np.uint32), source.view(np.uint32)
    )


def test_normal_pycolmap_roundtrip_is_wire_only_oracle(tmp_path):
    pycolmap = pytest.importorskip("pycolmap")
    source = tmp_path / "normal.bin"
    source.write_bytes(_normal_golden())
    upstream = pycolmap.NormalMap()
    upstream.read(source)
    copy = tmp_path / "copy.bin"
    upstream.write(copy)
    assert copy.read_bytes() == _normal_golden()


def test_invalid_write_does_not_create_destination(tmp_path):
    depth = _core.depth_map(
        np.ones((2, 2), np.float32),
        unit="unknown",
        invalid_policy="nonpositive",
        depth_convention="ray_distance",
    )
    path = tmp_path / "should-not-exist.bin"
    with pytest.raises(ValueError, match="camera_z"):
        _core._write_to_file(_core.write_colmap_mvs_depth, depth, path)
    assert not path.exists()


@pytest.mark.parametrize("direct_sink", [False, True])
def test_large_native_normal_encode_releases_gil(tmp_path, direct_sink):
    normal = _core.normal_map(
        np.zeros((1024, 1024, 3), dtype=np.float32)
    )
    ready = threading.Event()
    start = threading.Event()
    stop = threading.Event()
    progress = [0]

    def worker():
        ready.set()
        start.wait()
        while not stop.is_set():
            progress[0] += 1
            time.sleep(0)

    thread = threading.Thread(target=worker)
    thread.start()
    assert ready.wait(timeout=5)
    previous_interval = sys.getswitchinterval()
    try:
        sys.setswitchinterval(10.0)
        start.set()
        if direct_sink:
            _core._write_to_file(
                _core.write_colmap_mvs_normal,
                normal,
                tmp_path / "normal.bin",
            )
        else:
            _core.write_colmap_mvs_normal(normal)
    finally:
        stop.set()
        sys.setswitchinterval(previous_interval)
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert progress[0] > 0
