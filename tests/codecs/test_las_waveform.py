from __future__ import annotations

import io
import struct

import laspy
import numpy as np
import pytest

import sceneio
from sceneio import _core


def _fixed(value: str, size: int) -> bytes:
    return value.encode("ascii").ljust(size, b"\0")


def _descriptor() -> bytes:
    payload = struct.pack("<BBIIdd", 8, 0, 4, 1000, 2.0, -1.0)
    return struct.pack(
        "<H16sHH32s",
        0,
        _fixed("LASF_Spec", 16),
        100,
        len(payload),
        _fixed("waveform descriptor", 32),
    ) + payload


def _packet_record() -> bytes:
    payload = b"\x01\x02\x03\x04"
    return struct.pack(
        "<H16sHQ32s",
        0,
        _fixed("LASF_Spec", 16),
        65535,
        len(payload),
        _fixed("waveform packets", 32),
    ) + payload


def _format_layout(point_format: int) -> tuple[int, int, int | None]:
    return {
        4: (57, 28, None),
        5: (63, 34, 28),
        9: (59, 30, None),
        10: (67, 38, 30),
    }[point_format]


def _fixture(point_format: int, count: int = 3) -> tuple[bytes, np.ndarray]:
    record_length, wave_offset, color_offset = _format_layout(point_format)
    version_minor = 3 if point_format < 6 else 4
    header_size = 235 if version_minor == 3 else 375
    descriptor = _descriptor()
    offset_to_points = header_size + len(descriptor)
    points_end = offset_to_points + count * record_length
    records = np.zeros((count, record_length), np.uint8)
    xyz = np.array(
        [[10, 20, 30], [11, 18, 35], [9, 25, 27]],
        np.int32,
    )[:count]

    for row in range(count):
        record = records[row]
        struct.pack_into("<iiiH", record, 0, *xyz[row], 100 + row)
        if point_format < 6:
            struct.pack_into("<BBbBHd", record, 14, 0x09, 2, -3, 7, 100, 42.5 + row)
        else:
            struct.pack_into(
                "<BBBBhHd",
                record,
                14,
                0x11,
                0x10,
                2,
                7,
                100,
                100,
                42.5 + row,
            )
        if color_offset is not None:
            struct.pack_into(
                "<HHH",
                record,
                color_offset,
                1000 + row,
                2000 + row,
                3000 + row,
            )
        if point_format == 10:
            struct.pack_into("<H", record, 36, 4000 + row)
        struct.pack_into(
            "<BQIffff",
            record,
            wave_offset,
            1,
            60,
            4,
            0.25 + row,
            1.0,
            2.0,
            3.0,
        )

    header = bytearray(header_size)
    header[:4] = b"LASF"
    struct.pack_into("<H", header, 6, 2)
    struct.pack_into("<BB", header, 24, 1, version_minor)
    header[58:90] = _fixed("sceneio waveform fixture", 32)
    struct.pack_into("<HII", header, 94, header_size, offset_to_points, 1)
    legacy_count = count if point_format < 6 else 0
    struct.pack_into("<BHI", header, 104, point_format, record_length, legacy_count)
    if point_format < 6:
        struct.pack_into("<I", header, 111, count)
    struct.pack_into("<ddd", header, 131, 0.01, 0.02, 0.05)
    struct.pack_into("<ddd", header, 155, 600000.0, 5000000.0, 50.0)
    true_xyz = xyz * np.array([0.01, 0.02, 0.05]) + np.array(
        [600000.0, 5000000.0, 50.0]
    )
    struct.pack_into(
        "<dddddd",
        header,
        179,
        true_xyz[:, 0].max(),
        true_xyz[:, 0].min(),
        true_xyz[:, 1].max(),
        true_xyz[:, 1].min(),
        true_xyz[:, 2].max(),
        true_xyz[:, 2].min(),
    )
    struct.pack_into("<Q", header, 227, points_end)
    if version_minor == 4:
        struct.pack_into("<QI", header, 235, points_end, 1)
        struct.pack_into("<Q", header, 247, count)
        struct.pack_into("<Q", header, 255, count)

    encoded = (
        bytes(header)
        + descriptor
        + records.tobytes()
        + _packet_record()
    )
    return encoded, records


def _true_positions(cloud) -> np.ndarray:
    return cloud.positions.astype(np.float64) + np.asarray(cloud.origin)


@pytest.mark.parametrize("point_format", [4, 5, 9, 10])
def test_reads_waveform_formats_with_lossless_sidecar_and_laspy_oracle(
    point_format,
):
    encoded, records = _fixture(point_format)

    actual = _core.read_las(encoded)
    from_view = _core.read_las(memoryview(encoded))
    oracle = laspy.read(io.BytesIO(encoded))

    np.testing.assert_allclose(
        _true_positions(actual),
        np.column_stack((oracle.x, oracle.y, oracle.z)),
        atol=1e-6,
    )
    np.testing.assert_array_equal(actual.intensities, oracle.intensity)
    np.testing.assert_array_equal(from_view.positions, actual.positions)
    assert actual.has_las_waveform
    assert actual.las_waveform.point_format == point_format
    assert actual.las_waveform.point_records.tobytes() == records.tobytes()
    assert actual.las_waveform.descriptor_vlrs.tobytes() == _descriptor()
    assert (
        actual.las_waveform.waveform_packet_record.tobytes()
        == _packet_record()
    )
    if point_format in (5, 10):
        np.testing.assert_array_equal(
            actual.colors16,
            np.column_stack((oracle.red, oracle.green, oracle.blue)),
        )
    else:
        assert not actual.has_rgb16


@pytest.mark.parametrize("point_format", [4, 5, 9, 10])
def test_waveform_partial_read_preserves_selected_records(point_format):
    encoded, records = _fixture(point_format)

    full = _core.read_las(encoded)
    selected = _core.read_las_points(encoded, 1, 3)

    np.testing.assert_array_equal(selected.positions, full.positions[1:3])
    np.testing.assert_array_equal(
        selected.intensities, full.intensities[1:3]
    )
    assert (
        selected.las_waveform.point_records.tobytes()
        == records[1:3].tobytes()
    )
    assert (
        selected.las_waveform.waveform_packet_record.tobytes()
        == full.las_waveform.waveform_packet_record.tobytes()
    )


@pytest.mark.parametrize("point_format", [4, 5, 9, 10])
def test_waveform_writer_roundtrips_with_laspy_and_preserves_opaque_data(
    point_format,
):
    encoded, _ = _fixture(point_format)
    source = _core.read_las(encoded)

    first = bytes(_core.write_las(source, 0.01))
    second = bytes(_core.write_las(source, 0.01))
    actual = _core.read_las(first)
    oracle = laspy.read(io.BytesIO(first))

    assert first == second
    assert oracle.header.point_format.id == point_format
    np.testing.assert_allclose(
        _true_positions(actual),
        _true_positions(source),
        atol=1e-6,
    )
    np.testing.assert_array_equal(actual.intensities, source.intensities)
    np.testing.assert_allclose(
        _true_positions(actual),
        np.column_stack((oracle.x, oracle.y, oracle.z)),
        atol=1e-6,
    )
    assert (
        actual.las_waveform.descriptor_vlrs.tobytes()
        == source.las_waveform.descriptor_vlrs.tobytes()
    )
    assert (
        actual.las_waveform.waveform_packet_record.tobytes()
        == source.las_waveform.waveform_packet_record.tobytes()
    )
    np.testing.assert_array_equal(
        actual.las_waveform.point_records[:, 12:],
        source.las_waveform.point_records[:, 12:],
    )
    _, wave_offset, _ = _format_layout(point_format)
    np.testing.assert_array_equal(
        actual.las_waveform.point_records[:, wave_offset : wave_offset + 29],
        source.las_waveform.point_records[:, wave_offset : wave_offset + 29],
    )
    if point_format in (5, 10):
        np.testing.assert_array_equal(actual.colors16, source.colors16)
        np.testing.assert_array_equal(
            actual.colors16,
            np.column_stack((oracle.red, oracle.green, oracle.blue)),
        )


@pytest.mark.parametrize("point_format", [4, 5, 9, 10])
def test_waveform_partial_cloud_can_be_written(point_format):
    encoded, _ = _fixture(point_format)
    source = _core.read_las_points(encoded, 1, 3)

    actual = _core.read_las(_core.write_las(source, 0.01))

    assert actual.positions.shape == (2, 3)
    np.testing.assert_allclose(
        _true_positions(actual),
        _true_positions(source),
        atol=1e-6,
    )
    np.testing.assert_array_equal(actual.intensities, source.intensities)
    assert (
        actual.las_waveform.waveform_packet_record.tobytes()
        == source.las_waveform.waveform_packet_record.tobytes()
    )


@pytest.mark.parametrize("point_format", [4, 5, 9, 10])
def test_empty_waveform_cloud_roundtrips(point_format):
    record_length, _, _ = _format_layout(point_format)
    version_minor = 3 if point_format < 6 else 4
    sidecar = _core.las_waveform_sidecar(
        point_format,
        version_minor,
        2,
        np.empty((0, record_length), np.uint8),
        np.frombuffer(_descriptor(), np.uint8),
        np.frombuffer(_packet_record(), np.uint8),
    )
    source = _core.point_cloud(
        np.empty((0, 3), np.float32),
        las_waveform=sidecar,
    )

    encoded = bytes(_core.write_las(source))
    actual = _core.read_las(encoded)
    oracle = laspy.read(io.BytesIO(encoded))

    assert actual.positions.shape == (0, 3)
    assert actual.las_waveform.point_format == point_format
    assert len(oracle.points) == 0


def test_waveform_file_sink_is_byte_identical(tmp_path):
    source = _core.read_las(_fixture(10)[0])
    expected = bytes(_core.write_las(source, 0.01))
    path = tmp_path / "waveform.las"

    _core._write_to_file(
        lambda cloud: _core.write_las(cloud, 0.01),
        source,
        path,
        _max_chunk=17,
    )

    assert path.read_bytes() == expected


@pytest.mark.parametrize("point_format", [4, 5, 9, 10])
def test_waveform_public_api_inspect_partial_and_write(tmp_path, point_format):
    source_path = tmp_path / f"source-{point_format}.las"
    source_path.write_bytes(_fixture(point_format)[0])

    full = sceneio.read(source_path)
    partial = sceneio.read_partial(source_path, points=(1, 3))
    info = sceneio.inspect(source_path)
    output_path = tmp_path / f"output-{point_format}.las"
    sceneio.write(full, output_path)
    back = sceneio.read(output_path)

    assert sceneio.detect(source_path) == "las"
    assert info.shape == (3, 3)
    assert info.dtype == "float32"
    assert info.metadata == {
        "point_format": point_format,
        "has_color": point_format in {5, 10},
        "has_intensity": True,
        "has_waveform": True,
    }
    np.testing.assert_array_equal(partial.positions, full.positions[1:3])
    np.testing.assert_array_equal(
        partial.las_waveform.point_records,
        full.las_waveform.point_records[1:3],
    )
    assert back.las_waveform.point_format == point_format
    assert (
        back.las_waveform.waveform_packet_record.tobytes()
        == full.las_waveform.waveform_packet_record.tobytes()
    )


def test_waveform_writer_revalidates_mutable_sidecar():
    source = _core.read_las(_fixture(9)[0])
    source.las_waveform.descriptor_vlrs[18] = 101

    with pytest.raises(ValueError, match=r"descriptor|missing"):
        _core.write_las(source)


def test_waveform_writer_requires_format_color_convention():
    color_source = _core.read_las(_fixture(5)[0])
    without_color = _core.point_cloud(
        color_source.positions,
        intensity=color_source.intensities,
        intensity_range="u16",
        origin=np.asarray(color_source.origin, np.float64),
        las_waveform=color_source.las_waveform,
    )

    with pytest.raises(ValueError, match="requires colors16"):
        _core.write_las(without_color)


def test_external_waveform_packets_reject_explicitly():
    encoded, _ = _fixture(9)
    malformed = bytearray(encoded)
    struct.pack_into("<H", malformed, 6, 4)

    with pytest.raises(ValueError, match="internally"):
        _core.read_las(bytes(malformed))


def test_unrelated_waveform_vlr_rejects_instead_of_being_dropped():
    encoded, _ = _fixture(9)
    malformed = bytearray(encoded)
    malformed[375 + 2 : 375 + 18] = _fixed("OTHER", 16)

    with pytest.raises(ValueError, match=r"descriptor|LASF_Spec"):
        _core.read_las(bytes(malformed))


def test_waveform_packet_extent_is_validated():
    encoded, _ = _fixture(9)
    malformed = bytearray(encoded)
    point_offset = struct.unpack_from("<I", malformed, 96)[0]
    struct.pack_into("<Q", malformed, point_offset + 31, 10_000)

    with pytest.raises(ValueError, match="out of bounds"):
        _core.read_las(bytes(malformed))


@pytest.mark.parametrize("point_format", [4, 5, 9, 10])
def test_every_waveform_truncation_rejects(point_format):
    encoded, _ = _fixture(point_format)

    for cut in range(len(encoded)):
        with pytest.raises(ValueError):
            _core.read_las(encoded[:cut])
