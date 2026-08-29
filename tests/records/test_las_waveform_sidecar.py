from __future__ import annotations

import gc
import struct

import numpy as np
import pytest

from sceneio import _core


def _fixed(value: str, size: int) -> bytes:
    return value.encode("ascii").ljust(size, b"\0")


def _descriptor(*, record_id: int = 100) -> bytes:
    payload = struct.pack("<BBIIdd", 8, 0, 4, 1000, 2.0, -1.0)
    return struct.pack(
        "<H16sHH32s",
        0,
        _fixed("LASF_Spec", 16),
        record_id,
        len(payload),
        _fixed("waveform descriptor", 32),
    ) + payload


def _packet_record(payload: bytes = b"\x01\x02\x03\x04") -> bytes:
    return struct.pack(
        "<H16sHQ32s",
        0,
        _fixed("LASF_Spec", 16),
        65535,
        len(payload),
        _fixed("waveform packets", 32),
    ) + payload


def _records(count: int = 2) -> np.ndarray:
    records = np.zeros((count, 59), np.uint8)
    for row in range(count):
        struct.pack_into(
            "<BQIffff",
            records[row],
            30,
            1,
            60,
            4,
            0.25 + row,
            1.0,
            2.0,
            3.0,
        )
    return records


def _sidecar(**overrides):
    values = {
        "point_format": 9,
        "version_minor": 4,
        "global_encoding": 2,
        "point_records": _records(),
        "descriptor_vlrs": np.frombuffer(_descriptor(), np.uint8),
        "waveform_packet_record": np.frombuffer(_packet_record(), np.uint8),
    }
    values.update(overrides)
    return _core.las_waveform_sidecar(**values)


def test_factory_roundtrip_copy_isolation_and_point_cloud_attachment():
    records = _records()
    descriptors = np.frombuffer(bytearray(_descriptor()), np.uint8)
    packets = np.frombuffer(bytearray(_packet_record()), np.uint8)
    sidecar = _sidecar(
        point_records=records,
        descriptor_vlrs=descriptors,
        waveform_packet_record=packets,
    )
    cloud = _core.point_cloud(
        np.zeros((2, 3), np.float32),
        las_waveform=sidecar,
    )

    records[:] = 0
    descriptors[:] = 0
    packets[:] = 0

    assert cloud.has_las_waveform
    actual = cloud.las_waveform
    assert actual.point_format == 9
    assert actual.version_minor == 4
    assert actual.global_encoding == 2
    assert actual.point_record_length == 59
    assert actual.point_records.shape == (2, 59)
    assert actual.point_records.dtype == np.uint8
    assert actual.descriptor_vlrs.tobytes() == _descriptor()
    assert actual.waveform_packet_record.tobytes() == _packet_record()
    assert actual.point_records[0, 30] == 1


def test_views_keep_the_sidecar_and_parent_cloud_alive():
    cloud = _core.point_cloud(
        np.zeros((2, 3), np.float32),
        las_waveform=_sidecar(),
    )
    records = cloud.las_waveform.point_records
    packets = cloud.las_waveform.waveform_packet_record

    del cloud
    gc.collect()

    assert records.shape == (2, 59)
    assert records[1, 30] == 1
    assert packets.tobytes() == _packet_record()


def test_absent_sidecar_is_none_and_has_flag_is_false():
    cloud = _core.point_cloud(np.zeros((3, 3), np.float32))

    assert not cloud.has_las_waveform
    assert cloud.las_waveform is None


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_point_cloud_origin_must_be_finite(value):
    with pytest.raises(ValueError, match="origin"):
        _core.point_cloud(
            np.zeros((1, 3), np.float32),
            origin=np.array([value, 0.0, 0.0], np.float64),
        )


def test_point_count_must_match_cloud():
    with pytest.raises(ValueError, match="point count"):
        _core.point_cloud(
            np.zeros((3, 3), np.float32),
            las_waveform=_sidecar(),
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"point_format": 8}, "point format"),
        ({"version_minor": 3}, "version"),
        ({"global_encoding": 0}, "internal"),
        ({"global_encoding": 6}, "internal"),
        (
            {"point_records": np.zeros((2, 58), np.uint8)},
            "too short",
        ),
        (
            {"descriptor_vlrs": np.empty(0, np.uint8)},
            "descriptor",
        ),
        (
            {
                "descriptor_vlrs": np.frombuffer(
                    _descriptor(record_id=101), np.uint8
                )
            },
            "missing",
        ),
        (
            {
                "waveform_packet_record": np.frombuffer(
                    _packet_record(b"\x01\x02"), np.uint8
                )
            },
            "out of bounds",
        ),
    ],
)
def test_structural_validation(overrides, message):
    with pytest.raises(ValueError, match=message):
        _sidecar(**overrides)


def test_zero_descriptor_requires_an_empty_packet_reference():
    records = _records()
    records[:, 30] = 0

    with pytest.raises(ValueError, match="non-empty packet"):
        _sidecar(point_records=records)


def test_waveform_geometry_must_be_finite():
    records = _records()
    struct.pack_into("<f", records[0], 43, float("nan"))

    with pytest.raises(ValueError, match="finite"):
        _sidecar(point_records=records)
