from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pye57
import pytest

import sceneio
from sceneio import _core
from sceneio.io import _e57


def _fixture(count: int = 23):
    positions = (
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 8
    )
    colors = np.arange(count * 3, dtype=np.uint8).reshape(count, 3)
    intensity = np.linspace(-2, 3, count, dtype=np.float32)
    viewpoint = np.array(
        [1.25, -2.5, 3.75, 0.9238795325, 0.0, 0.3826834324, 0.0],
        dtype=np.float64,
    )
    return (
        _core.point_cloud(
            positions,
            colors=colors,
            intensity=intensity,
        ),
        positions,
        colors,
        intensity,
        viewpoint,
    )


def _scan_set(cloud, *, timestamp: float = 0.0, viewpoint=None):
    if viewpoint is None:
        viewpoint = cloud.viewpoint
    return _core.scan_set(
        (
            _core.point_scan(
                cloud,
                scan_id=0,
                timestamp=timestamp,
                viewpoint=np.asarray(viewpoint, dtype=np.float64),
            ),
        )
    )


def _raw_payload(positions, colors=None, intensity=None):
    result = {
        "cartesianX": positions[:, 0],
        "cartesianY": positions[:, 1],
        "cartesianZ": positions[:, 2],
    }
    if colors is not None:
        result.update(
            {
                "colorRed": colors[:, 0],
                "colorGreen": colors[:, 1],
                "colorBlue": colors[:, 2],
            }
        )
    if intensity is not None:
        result["intensity"] = intensity
    return result


def _structured_fixture():
    positions = np.array(
        [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
            [10.0, 11.0, 12.0],
            [13.0, 14.0, 15.0],
        ],
        dtype=np.float32,
    )
    colors = np.array(
        [[10, 20, 30], [11, 21, 31], [12, 22, 32], [13, 23, 33], [14, 24, 34]],
        dtype=np.uint8,
    )
    intensity = np.arange(5, dtype=np.float32) / 2
    invalid = np.array([0, 1, 2, 0, 0], dtype=np.uint8)
    rows = np.array([10, 11, 10, 12, 11], dtype=np.int64)
    columns = np.array([4, 4, 5, 5, 6], dtype=np.int64)
    return positions, colors, intensity, invalid, rows, columns


def test_sceneio_e57_write_is_exact_for_direct_upstream_reader(tmp_path):
    cloud, positions, colors, intensity, viewpoint = _fixture()
    path = tmp_path / "sceneio.e57"

    sceneio.write(_scan_set(cloud, viewpoint=viewpoint), path)

    assert sceneio.detect(path) == "e57"
    with pye57.E57(str(path)) as oracle:
        assert oracle.scan_count == 1
        raw = oracle.read_scan_raw(0)
        header = oracle.get_header(0)
        translation = np.array(header.translation, copy=True)
        rotation = np.array(header.rotation, copy=True)
    np.testing.assert_array_equal(
        np.column_stack([raw[name] for name in (
            "cartesianX",
            "cartesianY",
            "cartesianZ",
        )]),
        positions,
    )
    np.testing.assert_array_equal(
        np.column_stack([raw[name] for name in (
            "colorRed",
            "colorGreen",
            "colorBlue",
        )]),
        colors,
    )
    np.testing.assert_array_equal(raw["intensity"], intensity)
    np.testing.assert_allclose(translation, viewpoint[:3], rtol=0, atol=0)
    np.testing.assert_allclose(rotation, viewpoint[3:], rtol=0, atol=0)


def test_sceneio_reads_direct_upstream_e57_exactly(tmp_path):
    _cloud, positions, colors, intensity, viewpoint = _fixture()
    path = tmp_path / "oracle.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions, colors, intensity),
            translation=viewpoint[:3],
            rotation=viewpoint[3:],
        )

    scans = sceneio.read(path)
    assert isinstance(scans, _core.ScanSet)
    assert scans.num_scans == 1
    scan = scans.scans[0]
    cloud = scan.point_cloud
    np.testing.assert_array_equal(np.asarray(cloud.positions), positions)
    np.testing.assert_array_equal(np.asarray(cloud.colors), colors)
    np.testing.assert_array_equal(np.asarray(cloud.intensities), intensity)
    np.testing.assert_allclose(scan.viewpoint, viewpoint, rtol=0, atol=0)
    assert cloud.coordinate_frame == "unknown"
    assert cloud.scale_to_meters == 1.0
    assert cloud.intensity_range == "unknown"


def test_e57_invalid_cartesian_states_and_valid_projection_are_preserved(tmp_path):
    _cloud, positions, colors, intensity, _viewpoint = _fixture(8)
    invalid = np.array([0, 1, 0, 0, 2, 0, 0, 0], dtype=np.int8)
    payload = _raw_payload(positions, colors, intensity)
    payload["cartesianInvalidState"] = invalid
    path = tmp_path / "invalid.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(payload)

    scan = sceneio.read(path).scans[0]

    selected = invalid == 0
    np.testing.assert_array_equal(scan.invalid_states, invalid)
    np.testing.assert_array_equal(
        np.asarray(scan.point_cloud.positions),
        np.where(selected[:, None], positions, 0.0),
    )
    valid = scan.valid_point_cloud()
    np.testing.assert_array_equal(np.asarray(valid.positions), positions[selected])
    np.testing.assert_array_equal(np.asarray(valid.colors), colors[selected])
    np.testing.assert_array_equal(
        np.asarray(valid.intensities),
        intensity[selected],
    )
    info = sceneio.inspect(path)
    assert info.shape == (1,)
    assert info.count == len(invalid)
    assert info.metadata["stored_point_count"] == len(invalid)


def test_e57_inspect_does_not_decode_points(tmp_path, monkeypatch):
    cloud, *_ = _fixture(5)
    path = tmp_path / "inspect.e57"
    sceneio.write(_scan_set(cloud), path)

    def fail_read(*_args, **_kwargs):
        raise AssertionError("point decode was called")

    monkeypatch.setattr(pye57.E57, "read_scan_raw", fail_read)
    info = sceneio.inspect(path)

    assert info.format == "e57"
    assert info.payload_kind == "scan_set"
    assert info.shape == (1,)
    assert info.count == 5
    assert info.metadata["scan_count"] == 1
    assert info.metadata["stored_point_count"] == 5
    scan = info.metadata["scans"][0]
    assert scan["has_colors"] is True
    assert scan["has_intensity"] is True
    assert scan["has_invalid_state"] is False
    assert scan["stored_point_count"] == 5


def test_e57_reads_multiple_scans(tmp_path):
    _cloud, positions, *_ = _fixture(3)
    path = tmp_path / "two.e57"
    translations = (
        np.array([1.0, 2.0, 3.0], np.float64),
        np.array([-4.0, 5.0, -6.0], np.float64),
    )
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions), translation=translations[0]
        )
        oracle.write_scan_raw(
            _raw_payload(positions + np.float32(1)),
            translation=translations[1],
        )

    with pye57.E57(str(path)) as oracle:
        assert oracle.scan_count == 2
        for index, expected_translation in enumerate(translations):
            raw = oracle.read_scan_raw(index)
            np.testing.assert_array_equal(
                np.column_stack(
                    [
                        raw["cartesianX"],
                        raw["cartesianY"],
                        raw["cartesianZ"],
                    ]
                ),
                positions + np.float32(index),
            )
            np.testing.assert_allclose(
                oracle.get_header(index).translation,
                expected_translation,
                rtol=0,
                atol=0,
            )

    scans = sceneio.read(path)
    assert isinstance(scans, _core.ScanSet)
    assert scans.num_scans == 2
    assert scans.scan_ids.tolist() == [0, 1]
    for index, scan in enumerate(scans.scans):
        assert isinstance(scan, _core.PointScan)
        assert scan.scan_id == index
        np.testing.assert_array_equal(
            np.asarray(scan.point_cloud.positions),
            positions + np.float32(index),
        )
        np.testing.assert_allclose(
            scan.viewpoint[:3], translations[index], rtol=0, atol=0
        )


def test_e57_scan_preserves_stored_rows_invalid_states_and_indices(tmp_path):
    positions, colors, intensity, invalid, rows, columns = _structured_fixture()
    path = tmp_path / "structured.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions, colors, intensity)
            | {
                "cartesianInvalidState": invalid,
                "rowIndex": rows,
                "columnIndex": columns,
            },
            name="structured",
            translation=np.array([2.0, -3.0, 4.0], dtype=np.float64),
            rotation=np.array(
                [0.9238795325, 0.0, 0.3826834324, 0.0],
                dtype=np.float64,
            ),
        )

    scan = sceneio.read_e57_scan(path)
    assert isinstance(scan, _core.PointScan)
    assert scan.num_stored_points == len(positions)
    assert scan.num_valid_points == int(np.count_nonzero(invalid == 0))
    np.testing.assert_array_equal(np.asarray(scan.invalid_states), invalid)
    np.testing.assert_array_equal(np.asarray(scan.row_indices), rows)
    np.testing.assert_array_equal(np.asarray(scan.column_indices), columns)
    assert (scan.row_minimum, scan.row_maximum) == (10, 12)
    assert (scan.column_minimum, scan.column_maximum) == (4, 6)
    assert scan.name == "structured"
    assert scan.pose_convention == "scan_to_reference"
    assert scan.quaternion_order == "wxyz"
    stored = np.asarray(scan.point_cloud.positions)
    np.testing.assert_array_equal(stored[invalid != 0], 0.0)
    np.testing.assert_array_equal(stored[invalid == 0], positions[invalid == 0])
    valid = scan.valid_point_cloud()
    np.testing.assert_array_equal(
        np.asarray(valid.positions), positions[invalid == 0]
    )
    np.testing.assert_array_equal(
        np.asarray(valid.colors), colors[invalid == 0]
    )
    np.testing.assert_array_equal(
        np.asarray(valid.intensities), intensity[invalid == 0]
    )


def test_e57_pose_is_scan_to_reference_wxyz(tmp_path):
    positions = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    rotation = np.array(
        [np.sqrt(0.5), 0.0, 0.0, np.sqrt(0.5)], dtype=np.float64
    )
    translation = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    path = tmp_path / "pose.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions),
            rotation=rotation,
            translation=translation,
        )

    scan = _e57.read_e57_scan(path)
    assert scan.pose_convention == "scan_to_reference"
    assert scan.quaternion_order == "wxyz"
    np.testing.assert_allclose(scan.viewpoint, np.concatenate((translation, rotation)))
    projected = scan.valid_point_cloud()
    np.testing.assert_allclose(projected.viewpoint, scan.viewpoint, rtol=0, atol=0)
    with pye57.E57(str(path)) as oracle:
        expected = oracle.to_global(positions, rotation, translation)
    np.testing.assert_allclose(
        expected,
        np.array([[10.0, 21.0, 30.0], [9.0, 20.0, 30.0]]),
        rtol=0,
        atol=1e-6,
    )


def test_e57_scan_owns_buffers_after_source_close(tmp_path):
    positions, colors, intensity, invalid, rows, columns = _structured_fixture()
    path = tmp_path / "owned.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions, colors, intensity)
            | {
                "cartesianInvalidState": invalid,
                "rowIndex": rows,
                "columnIndex": columns,
            }
        )
    scan = _e57.read_e57_scan(path, stored_point_range=(1, 5))
    path.unlink()
    gc.collect()
    np.testing.assert_array_equal(
        np.asarray(scan.point_cloud.colors), colors[1:5]
    )
    np.testing.assert_array_equal(np.asarray(scan.row_indices), rows[1:5])


def test_e57_stored_range_streams_without_read_scan_raw(tmp_path, monkeypatch):
    positions, colors, intensity, invalid, rows, columns = _structured_fixture()
    path = tmp_path / "range.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions, colors, intensity)
            | {
                "cartesianInvalidState": invalid,
                "rowIndex": rows,
                "columnIndex": columns,
            }
        )

    def fail_read(*_args, **_kwargs):
        raise AssertionError("full read_scan_raw must not be used for a range")

    monkeypatch.setattr(pye57.E57, "read_scan_raw", fail_read)
    selected = _e57.read_e57_scan(path, stored_point_range=(1, 4))
    assert selected.num_stored_points == 3
    np.testing.assert_array_equal(
        np.asarray(selected.row_indices), rows[1:4]
    )
    np.testing.assert_array_equal(
        np.asarray(selected.point_cloud.positions),
        np.where((invalid[1:4] == 0)[:, None], positions[1:4], 0.0),
    )
    with pytest.raises(ValueError, match="at least one row"):
        _e57.read_e57_scan(path, stored_point_range=(2, 2))
    with pytest.raises(ValueError, match="half-open"):
        _e57.read_e57_scan(path, stored_point_range=(1,))
    with pytest.raises(TypeError, match="must be integers"):
        _e57.read_e57_scan(path, stored_point_range=(1.0, 2.0))
    with pytest.raises(sceneio.FormatError, match="outside"):
        sceneio.read_e57_scan(path, scan_index=1)
    with pytest.raises(sceneio.FormatError, match="outside"):
        sceneio.read_e57_scan(path, stored_point_range=(0, len(positions) + 1))


def test_e57_stored_range_crosses_provider_chunk_boundary(tmp_path, monkeypatch):
    count = _e57._RANGE_BUFFER_CAPACITY + 3
    axis = np.arange(count, dtype=np.float32)
    positions = np.column_stack((axis / 4, axis / 8, -axis / 16))
    invalid = (np.arange(count, dtype=np.uint32) % 3).astype(np.uint8)
    path = tmp_path / "cross-chunk.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions) | {"cartesianInvalidState": invalid}
        )

    def fail_read(*_args, **_kwargs):
        raise AssertionError("full read_scan_raw must not be used for a range")

    monkeypatch.setattr(pye57.E57, "read_scan_raw", fail_read)
    start = _e57._RANGE_BUFFER_CAPACITY - 3
    selected = sceneio.read_e57_scan(
        path,
        stored_point_range=(start, count),
    )
    expected_positions = np.where(
        (invalid[start:] == 0)[:, None], positions[start:], 0.0
    )
    np.testing.assert_array_equal(
        np.asarray(selected.point_cloud.positions), expected_positions
    )
    np.testing.assert_array_equal(selected.invalid_states, invalid[start:])


def test_e57_all_invalid_scan_has_empty_valid_projection(
    tmp_path, monkeypatch
):
    positions = np.arange(12, dtype=np.float32).reshape(4, 3)
    invalid = np.ones(4, dtype=np.uint8)
    path = tmp_path / "all-invalid.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions)
            | {
                "cartesianInvalidState": np.array(
                    [0, 1, 1, 1], dtype=np.uint8
                )
            }
        )

    # pye57 cannot author an all-invalid scan because its writer computes
    # Cartesian bounds from valid rows. Exercise SceneIO's reader boundary
    # with the provider-shaped raw mapping after obtaining a real header.
    raw = _raw_payload(positions) | {"cartesianInvalidState": invalid}
    monkeypatch.setattr(pye57.E57, "read_scan_raw", lambda *_args: raw)

    scan = sceneio.read_e57_scan(path)
    assert scan.num_stored_points == 4
    assert scan.num_valid_points == 0
    projected = scan.valid_point_cloud()
    assert projected.num_points == 0
    assert np.asarray(projected.positions).shape == (0, 3)
    decoded = sceneio.read(path).scans[0]
    assert decoded.num_stored_points == 4
    assert decoded.num_valid_points == 0

    authored = _core.point_scan(
        _core.point_cloud(positions),
        scan_id=0,
        invalid_states=invalid,
        timestamp=0.0,
    )
    with pytest.raises(sceneio.FormatError, match="no valid Cartesian points"):
        sceneio.write(_core.scan_set((authored,)), tmp_path / "refused.e57")


def test_e57_inspect_reports_all_scans_without_decoding(tmp_path, monkeypatch):
    positions, colors, intensity, invalid, rows, columns = _structured_fixture()
    path = tmp_path / "inspect.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions, colors, intensity)
            | {
                "cartesianInvalidState": invalid,
                "rowIndex": rows,
                "columnIndex": columns,
            }
        )

    def fail_read(*_args, **_kwargs):
        raise AssertionError("inspect must not decode point payloads")

    monkeypatch.setattr(pye57.E57, "read_scan_raw", fail_read)
    info = sceneio.inspect(path)
    assert info.payload_kind == "scan_set"
    assert info.shape == (1,)
    assert info.count == len(positions)
    assert info.dtype is None
    assert info.metadata["valid_point_count"] is None
    assert info.metadata["scans"][0]["stored_point_count"] == len(positions)


def test_e57_guards_reject_non_e57_states_ids_and_empty_files(tmp_path):
    positions = np.arange(6, dtype=np.float32).reshape(2, 3)
    invalid_path = tmp_path / "invalid-state.e57"
    with pye57.E57(str(invalid_path), mode="w") as oracle:
        oracle.write_scan_raw(
            _raw_payload(positions)
            | {"cartesianInvalidState": np.array([0, 3], dtype=np.uint8)}
        )
    with pytest.raises(ValueError, match="E57 states"):
        _e57.read_e57_scan(invalid_path)
    cloud = _core.point_cloud(positions)
    bad_state = _core.point_scan(
        cloud,
        invalid_states=np.array([0, 3], dtype=np.uint8),
        timestamp=1.0,
    )
    with pytest.raises(sceneio.FormatError, match="E57 states"):
        sceneio.write(_core.scan_set((bad_state,)), tmp_path / "bad-state.e57")
    with pytest.raises(ValueError, match="must fit int64"):
        _e57._exact_int64(
            np.array([2**63], dtype=np.uint64), "rowIndex"
        )

    custom_id = _core.point_scan(
        cloud,
        scan_id=9,
        timestamp=1.0,
    )
    with pytest.raises(sceneio.FormatError, match="scan_id is not representable"):
        sceneio.write(_core.scan_set((custom_id,)), tmp_path / "custom-id.e57")
    missing_timestamp = _core.point_scan(cloud, scan_id=0)
    with pytest.raises(sceneio.FormatError, match="require a timestamp"):
        sceneio.write(
            _core.scan_set((missing_timestamp,)),
            tmp_path / "missing-timestamp.e57",
        )

    empty_path = tmp_path / "empty.e57"
    with pye57.E57(str(empty_path), mode="w"):
        pass
    with pytest.raises(ValueError, match="no data3D scans"):
        _e57.read_e57(empty_path)
    with pytest.raises(ValueError, match="no data3D scans"):
        _e57.inspect_e57(empty_path)


def test_e57_scan_set_write_reopens_with_provider_oracle(tmp_path):
    positions, colors, intensity, invalid, rows, columns = _structured_fixture()
    cloud = _core.point_cloud(positions, colors=colors, intensity=intensity)
    scan = _core.point_scan(
        cloud,
        scan_id=0,
        invalid_states=invalid,
        row_indices=rows,
        column_indices=columns,
        row_minimum=10,
        row_maximum=12,
        column_minimum=4,
        column_maximum=6,
        name="authored",
        timestamp=123.5,
        viewpoint=np.array(
            [2.0, -3.0, 4.0, 0.9238795325, 0.0, 0.3826834324, 0.0],
            dtype=np.float64,
        ),
    )
    output = tmp_path / "authored.e57"
    sceneio.write(_core.scan_set((scan,)), output)

    with pye57.E57(str(output)) as oracle:
        assert oracle.scan_count == 1
        raw = oracle.read_scan_raw(0)
        header = oracle.get_header(0)
        np.testing.assert_array_equal(raw["cartesianInvalidState"], invalid)
        np.testing.assert_array_equal(raw["rowIndex"], rows)
        np.testing.assert_array_equal(raw["columnIndex"], columns)
        np.testing.assert_array_equal(
            np.column_stack(
                [raw["cartesianX"], raw["cartesianY"], raw["cartesianZ"]]
            )[invalid == 0],
            positions[invalid == 0],
        )
        assert header["name"].value() == "authored"
        assert header.acquisitionStart_dateTimeValue == 123.5
        np.testing.assert_allclose(header.translation, [2.0, -3.0, 4.0])
        np.testing.assert_allclose(
            header.rotation,
            [0.9238795325, 0.0, 0.3826834324, 0.0],
            rtol=0,
            atol=1e-12,
        )

    for label, value in (("cloud", cloud), ("scan", scan)):
        with pytest.raises(sceneio.FormatError, match="expected a ScanSet"):
            sceneio.write(value, tmp_path / f"noncanonical-{label}.e57")


def test_e57_writer_refuses_unrepresentable_guid_and_bounds(tmp_path):
    positions, _colors, _intensity, invalid, rows, columns = _structured_fixture()
    cloud = _core.point_cloud(positions)
    with_guid = _core.point_scan(
        cloud,
        invalid_states=invalid,
        row_indices=rows,
        column_indices=columns,
        row_minimum=10,
        row_maximum=12,
        column_minimum=4,
        column_maximum=6,
        guid="{caller-guid}",
        timestamp=1.0,
    )
    with pytest.raises(sceneio.FormatError, match="scan GUIDs"):
        sceneio.write(_core.scan_set((with_guid,)), tmp_path / "guid.e57")

    wide_bounds = _core.point_scan(
        cloud,
        invalid_states=invalid,
        row_indices=rows,
        column_indices=columns,
        row_minimum=9,
        row_maximum=12,
        column_minimum=4,
        column_maximum=6,
        timestamp=1.0,
    )
    with pytest.raises(sceneio.FormatError, match="row bounds"):
        sceneio.write(_core.scan_set((wide_bounds,)), tmp_path / "wide.e57")


def test_e57_multi_scan_write_is_transactional(tmp_path, monkeypatch):
    positions, _colors, _intensity, invalid, rows, columns = _structured_fixture()
    base = _core.point_cloud(positions)
    first = _core.point_scan(
        base,
        scan_id=0,
        invalid_states=invalid,
        row_indices=rows,
        column_indices=columns,
        row_minimum=10,
        row_maximum=12,
        column_minimum=4,
        column_maximum=6,
        timestamp=1.0,
    )
    second = _core.point_scan(
        _core.point_cloud(positions + np.float32(1)),
        scan_id=1,
        invalid_states=invalid,
        row_indices=rows,
        column_indices=columns,
        row_minimum=10,
        row_maximum=12,
        column_minimum=4,
        column_maximum=6,
        timestamp=2.0,
    )
    output = tmp_path / "transactional.e57"
    output.write_bytes(b"previous")
    original = pye57.E57.write_scan_raw
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second scan failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pye57.E57, "write_scan_raw", fail_second)
    with pytest.raises(sceneio.FormatError, match="injected second scan failure"):
        sceneio.write(_core.scan_set([first, second]), output)
    assert output.read_bytes() == b"previous"
    assert not tuple(tmp_path.glob(".transactional.e57.*"))


def test_e57_rejects_coordinates_that_pointcloud_cannot_preserve(
    tmp_path, monkeypatch
):
    positions = np.array([[0, 0, 0], [1, 2, 3]], dtype=np.float32)
    path = tmp_path / "double.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(_raw_payload(positions))

    original = pye57.E57.read_scan_raw

    def nonexact_read(source, index):
        raw = original(source, index)
        raw["cartesianX"] = np.array([0.1, 1.0], dtype=np.float64)
        return raw

    monkeypatch.setattr(pye57.E57, "read_scan_raw", nonexact_read)
    with pytest.raises(sceneio.FormatError, match="not exactly representable"):
        sceneio.read(path)


def test_e57_rejects_nonintegral_colors(tmp_path, monkeypatch):
    _cloud, positions, colors, *_ = _fixture(2)
    path = tmp_path / "fractional-color.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(_raw_payload(positions, colors))

    original = pye57.E57.read_scan_raw

    def nonintegral_read(source, index):
        raw = original(source, index)
        raw["colorRed"] = np.array([1.5, 2.0], dtype=np.float64)
        return raw

    monkeypatch.setattr(pye57.E57, "read_scan_raw", nonintegral_read)
    with pytest.raises(sceneio.FormatError, match="representable as uint8"):
        sceneio.read(path)


def test_e57_record_outlives_closed_and_removed_source(tmp_path):
    cloud, positions, *_ = _fixture(5)
    path = tmp_path / "lifetime.e57"
    sceneio.write(_scan_set(cloud), path)

    decoded = sceneio.read(path)
    path.unlink()
    gc.collect()

    np.testing.assert_array_equal(
        np.asarray(decoded.scans[0].point_cloud.positions),
        positions,
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"coordinate_frame": "enu"},
            "coordinate_frame",
        ),
        (
            {"normals": np.ones((2, 3), np.float32)},
            "normals",
        ),
        (
            {"colors16": np.ones((2, 3), np.uint16)},
            "16-bit colors",
        ),
        (
            {
                "intensity": np.ones(2, np.float32),
                "intensity_range": "unit",
            },
            "intensity_range",
        ),
    ],
    ids=[
        "cloud0-coordinate_frame",
        "cloud1-normals",
        "cloud2-16-bit colors",
        "cloud3-intensity_range",
    ],
)
def test_e57_writer_refuses_unrepresentable_cloud_conventions(
    tmp_path, kwargs, message
):
    cloud = _core.point_cloud(np.ones((2, 3), np.float32), **kwargs)
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.write(_scan_set(cloud), tmp_path / "bad.e57")


def test_e57_failed_provider_write_preserves_destination(
    tmp_path, monkeypatch
):
    cloud, *_ = _fixture(3)
    path = tmp_path / "preserve.e57"
    path.write_bytes(b"previous")

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("injected provider failure")

    monkeypatch.setattr(pye57.E57, "write_scan_raw", fail_write)
    with pytest.raises(sceneio.FormatError, match="injected provider failure"):
        sceneio.write(_scan_set(cloud), path)

    assert path.read_bytes() == b"previous"
    assert not tuple(tmp_path.glob(".preserve.e57.*"))


def test_e57_capability_and_open_license_inventory():
    capabilities = sceneio.capabilities("e57")
    assert capabilities.available
    assert capabilities.requires_features == ("pye57",)
    assert "multiple_scans" in capabilities.supported_features
    assert "organized_row_column" in capabilities.supported_features
    assert "stored_point_ranges" in capabilities.supported_features

    license_root = Path(__file__).resolve().parents[2] / "LICENSES"
    assert "Permission is hereby granted" in (
        license_root / "pye57.txt"
    ).read_text(encoding="utf-8")
    assert "Boost Software License" in (
        license_root / "libe57format.txt"
    ).read_text(encoding="utf-8")
