"""Parity and boundary suite for LAZperf-backed LAZ point clouds.

laspy with its independent lazrs backend is the interoperability oracle.
SceneIO deliberately projects point formats 0-3 and 6-8 to XYZ, intensity,
and RGB16; GPS time, NIR, CRS metadata, extra bytes, and waveform formats are
rejected or documented as unrepresented.
"""

from __future__ import annotations

import gc
import io
import mmap
import struct
import subprocess
import sys
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core

laspy = pytest.importorskip("laspy")
pytest.importorskip("lazrs")

_FORMATS = (0, 1, 2, 3, 6, 7, 8)
_COLOR_FORMATS = {2, 3, 7, 8}


def _sample(seed: int, count: int = 257):
    rng = np.random.default_rng(seed)
    origin = np.array([500_000.0, 4_000_000.0, 100.0])
    # Values lie exactly on the anisotropic oracle grid.
    raw = rng.integers(-100_000, 100_001, (count, 3), dtype=np.int32)
    scales = np.array([0.001, 0.002, 0.005])
    xyz = origin + raw * scales
    intensity = rng.integers(0, 65_536, count, dtype=np.uint16)
    rgb = rng.integers(0, 65_536, (count, 3), dtype=np.uint16)
    return xyz, intensity, rgb, origin, scales


def _oracle_bytes(point_format: int, count: int = 257) -> tuple[bytes, object]:
    xyz, intensity, rgb, origin, scales = _sample(100 + point_format, count)
    header = laspy.LasHeader(
        version="1.4" if point_format >= 6 else "1.2",
        point_format=point_format,
    )
    header.scales = scales
    header.offsets = origin
    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    las.intensity = intensity
    if point_format in _COLOR_FORMATS:
        las.red, las.green, las.blue = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    if point_format in {1, 3, 6, 7, 8}:
        las.gps_time = np.arange(count, dtype=np.float64) + 1_000.25
    if point_format == 8:
        las.nir = np.arange(count, dtype=np.uint16) + 17
    output = io.BytesIO()
    las.write(output, do_compress=True)
    return output.getvalue(), las


def _full_range_oracle_bytes(point_format: int) -> tuple[bytes, object]:
    header = laspy.LasHeader(
        version="1.4" if point_format >= 6 else "1.2",
        point_format=point_format,
    )
    header.scales = np.ones(3)
    header.offsets = np.zeros(3)
    las = laspy.LasData(header)
    limits = np.iinfo(np.int32)
    edge = np.array(
        [0, limits.max, limits.min, limits.max - 1, limits.min + 1, -1, 1],
        dtype=np.int32,
    )
    las.X = edge
    las.Y = edge[::-1]
    las.Z = np.roll(edge, 1)
    las.intensity = np.arange(edge.size, dtype=np.uint16)
    if point_format >= 6:
        las.gps_time = np.arange(edge.size, dtype=np.float64)
    output = io.BytesIO()
    las.write(output, do_compress=True)
    return output.getvalue(), las


def _true_positions(cloud) -> np.ndarray:
    return np.asarray(cloud.positions, dtype=np.float64) + np.asarray(cloud.origin)


def _cloud(point_format: int, count: int = 257):
    xyz, intensity, rgb, origin, _scales = _sample(200 + point_format, count)
    return _core.point_cloud(
        (xyz - origin).astype(np.float32),
        colors16=rgb if point_format in _COLOR_FORMATS else None,
        intensity=intensity.astype(np.float32),
        intensity_range="u16",
        origin=origin,
    )


def _assert_cloud_matches_las(cloud, las) -> None:
    expected_xyz = np.column_stack((las.x, las.y, las.z))
    # PointCloud stores coordinates relative to its f64 origin in float32.
    np.testing.assert_allclose(_true_positions(cloud), expected_xyz, atol=5e-5)
    np.testing.assert_array_equal(
        np.asarray(cloud.intensities),
        np.asarray(las.intensity, dtype=np.float32),
    )
    has_color = las.header.point_format.id in _COLOR_FORMATS
    assert cloud.has_rgb16 == has_color
    if has_color:
        np.testing.assert_array_equal(
            np.asarray(cloud.colors16),
            np.column_stack((las.red, las.green, las.blue)),
        )


@pytest.mark.parametrize("point_format", _FORMATS)
def test_reads_lazrs_all_supported_point_formats(point_format):
    data, expected = _oracle_bytes(point_format)
    cloud = _core.read_laz(data)
    assert cloud.num_points == len(expected.points)
    assert cloud.intensity_range == "u16"
    _assert_cloud_matches_las(cloud, expected)


@pytest.mark.parametrize("point_format", [0, 6])
def test_reads_lazrs_full_int32_coordinate_transitions(point_format):
    data, expected = _full_range_oracle_bytes(point_format)
    cloud = _core.read_laz(data)
    raw = np.column_stack((expected.X, expected.Y, expected.Z))
    expected_origin = raw[0].astype(np.float64)
    expected_positions = (raw.astype(np.float64) - expected_origin).astype(
        np.float32
    )
    np.testing.assert_array_equal(cloud.origin, expected_origin)
    np.testing.assert_array_equal(cloud.positions, expected_positions)
    np.testing.assert_array_equal(cloud.intensities, expected.intensity)


@pytest.mark.parametrize("point_format", [0, 1, 2, 3])
def test_reads_legacy_point_formats_in_las_1_4_container(point_format):
    xyz, intensity, rgb, origin, scales = _sample(150 + point_format)
    header = laspy.LasHeader(version="1.4", point_format=point_format)
    header.scales = scales
    header.offsets = origin
    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    las.intensity = intensity
    if point_format in _COLOR_FORMATS:
        las.red, las.green, las.blue = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    output = io.BytesIO()
    las.write(output, do_compress=True)
    _assert_cloud_matches_las(_core.read_laz(output.getvalue()), las)


@pytest.mark.parametrize("point_format", _FORMATS)
def test_lazrs_reads_sceneio_all_supported_point_formats(point_format):
    cloud = _cloud(point_format)
    data = bytes(_core.write_laz(cloud, 0.001, _point_format=point_format))
    decoded = laspy.read(io.BytesIO(data))
    assert decoded.header.point_format.id == point_format
    assert len(decoded.points) == cloud.num_points
    np.testing.assert_allclose(
        np.column_stack((decoded.x, decoded.y, decoded.z)),
        _true_positions(cloud),
        atol=0.0005,
    )
    np.testing.assert_array_equal(
        np.asarray(decoded.intensity),
        np.asarray(cloud.intensities, dtype=np.uint16),
    )
    if point_format in _COLOR_FORMATS:
        np.testing.assert_array_equal(
            np.column_stack((decoded.red, decoded.green, decoded.blue)),
            np.asarray(cloud.colors16),
        )
    if point_format in {1, 3, 6, 7, 8}:
        np.testing.assert_array_equal(decoded.gps_time, 0.0)
    if point_format == 8:
        np.testing.assert_array_equal(decoded.nir, 0)


@pytest.mark.parametrize(("with_color", "expected_format"), [(False, 0), (True, 2)])
def test_public_writer_selects_plain_legacy_format(with_color, expected_format):
    cloud = _cloud(2 if with_color else 0)
    decoded = laspy.read(io.BytesIO(bytes(_core.write_laz(cloud))))
    assert decoded.header.version == "1.2"
    assert decoded.header.point_format.id == expected_format


@pytest.mark.parametrize("point_format", _FORMATS)
def test_empty_files_roundtrip_with_oracle(point_format):
    cloud = _cloud(point_format, count=0)
    data = bytes(_core.write_laz(cloud, _point_format=point_format))
    oracle = laspy.read(io.BytesIO(data))
    decoded = _core.read_laz(data)
    assert len(oracle.points) == decoded.num_points == 0
    assert oracle.header.point_format.id == point_format
    # Empty optional arrays have no representable presence bit in PointCloud.
    assert decoded.has_rgb16 is False


def test_public_api_detect_inspect_read_partial_and_lifetime(tmp_path):
    cloud = _cloud(2, count=100_003)
    path = tmp_path / "points.laz"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "laz"

    extensionless = tmp_path / "extensionless"
    extensionless.write_bytes(path.read_bytes())
    assert sceneio.detect(extensionless) == "laz"

    info = sceneio.inspect(path)
    assert info.format == "laz"
    assert info.shape == (cloud.num_points, 3)
    assert info.dtype == "float32"
    assert info.count == cloud.num_points
    assert info.metadata["point_format"] == 2
    assert info.metadata["has_color"] is True
    assert info.metadata["chunk_size"] == 50_000

    full = sceneio.read(path)
    partial = sceneio.read_partial(path, points=(49_997, 50_006))
    np.testing.assert_array_equal(
        np.asarray(partial.positions),
        np.asarray(full.positions)[49_997:50_006],
    )
    np.testing.assert_array_equal(
        np.asarray(partial.colors16),
        np.asarray(full.colors16)[49_997:50_006],
    )
    np.testing.assert_array_equal(
        np.asarray(partial.intensities),
        np.asarray(full.intensities)[49_997:50_006],
    )
    np.testing.assert_array_equal(partial.origin, full.origin)

    # The mmap adapter must close before returning an owning decode. On
    # Windows this unlink also proves no mapping/file handle escaped.
    del full, partial
    gc.collect()
    path.unlink()
    assert not path.exists()


@pytest.mark.parametrize("point_format", _FORMATS)
def test_bytes_memoryview_mmap_and_lanes_are_bit_exact(tmp_path, point_format):
    data, _expected = _oracle_bytes(point_format, count=50_003)
    path = tmp_path / f"format-{point_format}.laz"
    path.write_bytes(data)
    one = _core.read_laz(data, _lanes=1)
    view = _core.read_laz(memoryview(data), _lanes=4)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        mapped_result = _core.read_laz(mapped, _lanes=4)
    gc.collect()
    for actual in (view, mapped_result):
        np.testing.assert_array_equal(actual.positions, one.positions)
        np.testing.assert_array_equal(actual.intensities, one.intensities)
        np.testing.assert_array_equal(actual.origin, one.origin)
        if one.has_rgb16:
            np.testing.assert_array_equal(actual.colors16, one.colors16)


def test_partial_decodes_only_requested_chunk_domain():
    data, _expected = _oracle_bytes(7, count=120_003)
    full = _core.read_laz(data, _lanes=1)
    for start, stop in ((0, 1), (49_999, 50_002), (100_001, 120_003)):
        partial = _core.read_laz_points(data, start, stop, _lanes=4)
        np.testing.assert_array_equal(
            partial.positions, np.asarray(full.positions)[start:stop]
        )
        np.testing.assert_array_equal(
            partial.intensities, np.asarray(full.intensities)[start:stop]
        )
        np.testing.assert_array_equal(
            partial.colors16, np.asarray(full.colors16)[start:stop]
        )
        np.testing.assert_array_equal(partial.origin, full.origin)


def test_partial_does_not_decode_corrupt_unselected_chunk():
    data, _expected = _oracle_bytes(7, count=120_003)
    point_offset = struct.unpack_from("<I", data, 96)[0]
    record_length = struct.unpack_from("<H", data, 105)[0]
    chunk_start = point_offset + 8
    chunks = []
    for _ in range(3):
        stored_count = struct.unpack_from("<I", data, chunk_start + record_length)[0]
        assert stored_count in {20_003, 50_000}
        sizes = struct.unpack_from(
            "<10I", data, chunk_start + record_length + 4
        )
        prefix = record_length + 4 + 10 * 4
        chunks.append((chunk_start, prefix, sizes))
        chunk_start += prefix + sum(sizes)

    expected = _core.read_laz(data)
    third_start, prefix, sizes = chunks[2]
    assert sizes[0] > 16
    for stream_offset in (4, sizes[0] // 3, sizes[0] // 2):
        corrupted = bytearray(data)
        corrupted[third_start + prefix + stream_offset] ^= 0x5A
        candidate = bytes(corrupted)
        partial = _core.read_laz_points(candidate, 0, 10)
        np.testing.assert_array_equal(partial.positions, expected.positions[:10])
        try:
            full = _core.read_laz(candidate)
        except ValueError:
            return
        if not np.array_equal(full.positions, expected.positions):
            return
    pytest.fail("mutating the unselected coordinate stream did not alter full decode")


def test_format_14_layer_mutations_never_terminate_the_process(tmp_path):
    candidate_count = 0
    for point_format in (6, 7, 8):
        data, _expected = _oracle_bytes(point_format, count=257)
        point_offset = struct.unpack_from("<I", data, 96)[0]
        record_length = struct.unpack_from("<H", data, 105)[0]
        stream_count = 9 + (point_format == 7) + 2 * (point_format == 8)
        chunk_start = point_offset + 8
        stored_count = struct.unpack_from("<I", data, chunk_start + record_length)[0]
        assert stored_count == 257
        sizes = struct.unpack_from(
            f"<{stream_count}I",
            data,
            chunk_start + record_length + 4,
        )
        stream_start = chunk_start + record_length + 4 + stream_count * 4
        for stream_index, stream_size in enumerate(sizes):
            if stream_size == 0:
                continue
            corrupted = bytearray(data)
            corrupted[stream_start + stream_size // 2] ^= 0xA5
            (tmp_path / f"f{point_format}-s{stream_index}.laz").write_bytes(corrupted)
            candidate_count += 1
            stream_start += stream_size
    assert candidate_count >= 15

    # Keep this resilience sweep in a child process so a regression in a
    # native decoder is reported as an ordinary test failure, not as a lost
    # test session. A mutation may decode to different points or be rejected,
    # but it must not terminate the interpreter.
    script = """
from pathlib import Path
import sys
from sceneio import _core

for path in Path(sys.argv[1]).glob("*.laz"):
    try:
        _core.read_laz(path.read_bytes())
    except ValueError:
        pass
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (
        f"mutated LAZ layer terminated the decoder process: "
        f"{completed.stdout}{completed.stderr}"
    )


def test_format_14_integer_layer_overflow_mutation_is_rejected(tmp_path):
    data, _expected = _oracle_bytes(6, count=257)
    point_offset = struct.unpack_from("<I", data, 96)[0]
    record_length = struct.unpack_from("<H", data, 105)[0]
    stream_count = 9
    chunk_start = point_offset + 8
    sizes = struct.unpack_from(
        f"<{stream_count}I",
        data,
        chunk_start + record_length + 4,
    )
    assert sizes == (1338, 627, 0, 0, 525, 0, 0, 0, 1320)
    stream_index = 8
    stream_start = (
        chunk_start
        + record_length
        + 4
        + stream_count * 4
        + sum(sizes[:stream_index])
    )
    mutation_offset = stream_start + sizes[stream_index] // 2
    assert data[mutation_offset] == 0x0B
    corrupted = bytearray(data)
    corrupted[mutation_offset] ^= 0xA5
    candidate = bytes(corrupted)

    with pytest.raises(ValueError, match="laz: point decompression failed"):
        _core.read_laz(candidate)

    path = tmp_path / "integer-overflow-mutation.laz"
    path.write_bytes(candidate)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
        pytest.raises(ValueError, match="laz: point decompression failed"),
    ):
        _core.read_laz(mapped)


def test_direct_sink_is_byte_identical_and_oracle_readable(tmp_path):
    cloud = _cloud(2, count=80_003)
    expected = bytes(_core.write_laz(cloud, _lanes=4))
    path = tmp_path / "sink.laz"
    _core._write_to_file(
        lambda value: _core.write_laz(value, _lanes=4),
        cloud,
        path,
    )
    assert path.read_bytes() == expected
    assert len(laspy.read(path).points) == cloud.num_points


def test_direct_sink_handles_short_writes_and_restores_after_error(tmp_path):
    cloud = _cloud(2, count=80_003)
    expected = bytes(_core.write_laz(cloud))
    short_path = tmp_path / "short-write.laz"
    calls = _core._write_to_file(
        _core.write_laz,
        cloud,
        short_path,
        _test_short_write=97,
    )
    assert calls > 1
    assert short_path.read_bytes() == expected

    failed_path = tmp_path / "failed.laz"
    with pytest.raises(RuntimeError, match="file sink write failed"):
        _core._write_to_file(
            _core.write_laz,
            cloud,
            failed_path,
            _test_short_write=97,
            _test_fail_after=1,
        )
    assert 0 < failed_path.stat().st_size < len(expected)
    assert bytes(_core.write_laz(cloud)) == expected


def _traced_peak(call):
    tracemalloc.start()
    try:
        value = call()
        return value, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_mmap_read_and_file_sink_avoid_whole_file_python_bytes(tmp_path):
    cloud = _cloud(2, count=300_003)
    encoded = bytes(_core.write_laz(cloud))
    source = tmp_path / "large.laz"
    source.write_bytes(encoded)
    file_size = source.stat().st_size

    slow, bytes_peak = _traced_peak(lambda: _core.read_laz(source.read_bytes()))
    fast, mmap_peak = _traced_peak(lambda: sceneio.read(source))
    np.testing.assert_array_equal(fast.positions, slow.positions)
    assert bytes_peak >= file_size * 0.9
    assert mmap_peak < file_size / 8

    sink = tmp_path / "streamed.laz"
    _, sink_peak = _traced_peak(
        lambda: _core._write_to_file(_core.write_laz, cloud, sink)
    )
    assert sink.read_bytes() == encoded
    assert sink_peak < len(encoded) / 8


def test_every_truncated_prefix_rejects():
    data = bytes(_core.write_laz(_cloud(2, count=1)))
    for stop in range(len(data)):
        with pytest.raises(ValueError):
            _core.read_laz(data[:stop])


@pytest.mark.parametrize(
    ("offset", "replacement", "message"),
    [
        (104, 2, "compression bits"),
        (104, 0x84, "point format"),
        (105, 27, "extra bytes"),
        (131, None, "scales"),
        (155, None, "offsets"),
    ],
)
def test_reader_rejects_unrepresentable_or_invalid_headers(
    tmp_path, offset, replacement, message
):
    data = bytearray(bytes(_core.write_laz(_cloud(2, count=17))))
    if replacement is None:
        struct.pack_into("<d", data, offset, float("nan"))
    elif offset == 105:
        struct.pack_into("<H", data, offset, replacement)
    else:
        data[offset] = replacement
    with pytest.raises(ValueError, match=message):
        _core.read_laz(bytes(data))
    path = tmp_path / f"invalid-{offset}.laz"
    path.write_bytes(data)
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.inspect(path)


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    [
        (227, 1, "waveform"),
        (235, 1, "EVLR"),
        (243, 1, "EVLR"),
    ],
)
def test_reader_and_inspector_reject_unrepresented_las_14_metadata(
    tmp_path, offset, value, message
):
    data = bytearray(bytes(_core.write_laz(_cloud(6, count=17), _point_format=6)))
    if offset in {227, 235}:
        struct.pack_into("<Q", data, offset, value)
    else:
        struct.pack_into("<I", data, offset, value)
    with pytest.raises(ValueError, match=message):
        _core.read_laz(bytes(data))
    path = tmp_path / f"invalid-metadata-{offset}.laz"
    path.write_bytes(data)
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.inspect(path)


def test_reader_rejects_appended_or_corrupt_chunk_metadata():
    data = bytearray(bytes(_core.write_laz(_cloud(2, count=50_003))))
    with pytest.raises(ValueError, match=r"trailing|padding"):
        _core.read_laz(bytes(data) + b"\x00")

    table_offset = struct.unpack_from("<Q", data, struct.unpack_from("<I", data, 96)[0])[0]
    corrupted = bytearray(data)
    struct.pack_into("<I", corrupted, table_offset, 1)
    with pytest.raises(ValueError, match="table version"):
        _core.read_laz(bytes(corrupted))

    corrupted = bytearray(data)
    struct.pack_into("<I", corrupted, table_offset + 4, 4_000_001)
    with pytest.raises(ValueError, match="chunk count"):
        _core.read_laz(bytes(corrupted))


def test_inspector_rejects_truncated_or_invalid_chunk_table(tmp_path):
    data = bytearray(bytes(_core.write_laz(_cloud(2, count=50_003))))
    point_offset = struct.unpack_from("<I", data, 96)[0]
    table_offset = struct.unpack_from("<Q", data, point_offset)[0]

    truncated = tmp_path / "truncated-table.laz"
    truncated.write_bytes(data[: table_offset + 7])
    with pytest.raises(sceneio.FormatError, match="chunk-table"):
        sceneio.inspect(truncated)

    invalid = bytearray(data)
    struct.pack_into("<I", invalid, table_offset, 1)
    path = tmp_path / "invalid-table.laz"
    path.write_bytes(invalid)
    with pytest.raises(sceneio.FormatError, match="table version"):
        sceneio.inspect(path)


@pytest.mark.parametrize("bit", [1, 2, 3, 4])
def test_reader_and_inspector_reject_unrepresented_global_encoding(
    tmp_path, bit
):
    data = bytearray(bytes(_core.write_laz(_cloud(2, count=17))))
    struct.pack_into("<H", data, 6, 1 << bit)
    with pytest.raises(ValueError, match="global-encoding"):
        _core.read_laz(bytes(data))
    path = tmp_path / f"global-{bit}.laz"
    path.write_bytes(data)
    with pytest.raises(sceneio.FormatError, match="global-encoding"):
        sceneio.inspect(path)


def test_reader_rejects_plain_las_waveform_and_metadata():
    plain = bytes(_core.write_las(_cloud(0, count=3)))
    with pytest.raises(ValueError, match="compression bits"):
        _core.read_laz(plain)
    with pytest.raises(ValueError, match="point_format"):
        _core.write_laz(_cloud(0, count=3), _point_format=4)

    descriptor_payload = struct.pack("<BBIIdd", 8, 0, 4, 1000, 2.0, -1.0)
    descriptor = struct.pack(
        "<H16sHH32s",
        0,
        b"LASF_Spec".ljust(16, b"\0"),
        100,
        len(descriptor_payload),
        b"waveform descriptor".ljust(32, b"\0"),
    ) + descriptor_payload
    packet_payload = b"\x01\x02\x03\x04"
    packet = struct.pack(
        "<H16sHQ32s",
        0,
        b"LASF_Spec".ljust(16, b"\0"),
        65535,
        len(packet_payload),
        b"waveform packets".ljust(32, b"\0"),
    ) + packet_payload
    waveform = _core.las_waveform_sidecar(
        9,
        4,
        2,
        np.zeros((3, 59), dtype=np.uint8),
        np.frombuffer(descriptor, np.uint8),
        np.frombuffer(packet, np.uint8),
    )
    cloud = _core.point_cloud(
        np.zeros((3, 3), dtype=np.float32),
        las_waveform=waveform,
    )
    with pytest.raises(ValueError, match="waveform"):
        _core.write_laz(cloud)


def test_writer_guards_unrepresentable_fields_and_invalid_values():
    xyz = np.arange(12, dtype=np.float32).reshape(4, 3)
    with pytest.raises(ValueError, match="normals"):
        _core.write_laz(_core.point_cloud(xyz, normals=xyz))
    with pytest.raises(ValueError, match="colors16"):
        _core.write_laz(_core.point_cloud(xyz, colors=np.zeros((4, 3), np.uint8)))
    with pytest.raises(ValueError, match="intensity"):
        _core.write_laz(
            _core.point_cloud(
                xyz,
                intensity=np.full(4, 0.5, np.float32),
                intensity_range="unit",
            )
        )
    with pytest.raises(ValueError, match="scale"):
        _core.write_laz(_core.point_cloud(xyz), 0.0)
    invalid = xyz.copy()
    invalid[-1, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        _core.write_laz(_core.point_cloud(invalid), _lanes=4)
    for invalid_intensity in (
        np.nan,
        np.inf,
        -1.0,
        0.5,
        65536.0,
        np.float32("-0.0"),
    ):
        intensities = np.zeros(4, np.float32)
        intensities[-1] = invalid_intensity
        with pytest.raises(ValueError, match="exact unsigned 16-bit"):
            _core.write_laz(
                _core.point_cloud(
                    xyz,
                    intensity=intensities,
                    intensity_range="u16",
                ),
                _lanes=4,
            )

    boundary = np.array([0, 1, 65534, 65535], np.float32)
    encoded = _core.write_laz(
        _core.point_cloud(
            xyz,
            intensity=boundary,
            intensity_range="u16",
        ),
        _lanes=4,
    )
    np.testing.assert_array_equal(_core.read_laz(encoded).intensities, boundary)


def test_partial_range_validation():
    data = bytes(_core.write_laz(_cloud(0, count=9)))
    for start, stop in ((1, 1), (3, 2), (0, 10)):
        with pytest.raises(ValueError, match="range"):
            _core.read_laz_points(data, start, stop)
