from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pye57
import pytest

import sceneio
from sceneio import _core


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
            viewpoint=viewpoint,
        ),
        positions,
        colors,
        intensity,
        viewpoint,
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


def test_sceneio_e57_write_is_exact_for_direct_upstream_reader(tmp_path):
    cloud, positions, colors, intensity, viewpoint = _fixture()
    path = tmp_path / "sceneio.e57"

    sceneio.write(cloud, path)

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

    cloud = sceneio.read(path)

    assert isinstance(cloud, _core.PointCloud)
    np.testing.assert_array_equal(np.asarray(cloud.positions), positions)
    np.testing.assert_array_equal(np.asarray(cloud.colors), colors)
    np.testing.assert_array_equal(np.asarray(cloud.intensities), intensity)
    np.testing.assert_allclose(cloud.viewpoint, viewpoint, rtol=0, atol=0)
    assert cloud.coordinate_frame == "unknown"
    assert cloud.scale_to_meters == 1.0
    assert cloud.intensity_range == "unknown"


def test_e57_invalid_cartesian_points_are_explicitly_filtered(tmp_path):
    _cloud, positions, colors, intensity, _viewpoint = _fixture(8)
    invalid = np.array([0, 1, 0, 0, 2, 0, 0, 0], dtype=np.int8)
    payload = _raw_payload(positions, colors, intensity)
    payload["cartesianInvalidState"] = invalid
    path = tmp_path / "invalid.e57"
    with pye57.E57(str(path), mode="w") as oracle:
        oracle.write_scan_raw(payload)

    cloud = sceneio.read(path)

    selected = invalid == 0
    np.testing.assert_array_equal(np.asarray(cloud.positions), positions[selected])
    np.testing.assert_array_equal(np.asarray(cloud.colors), colors[selected])
    np.testing.assert_array_equal(
        np.asarray(cloud.intensities),
        intensity[selected],
    )
    info = sceneio.inspect(path)
    assert info.shape == (int(np.count_nonzero(selected)), 3)
    assert info.count == int(np.count_nonzero(selected))
    assert info.metadata["stored_point_count"] == len(invalid)


def test_e57_inspect_does_not_decode_points(tmp_path, monkeypatch):
    cloud, *_ = _fixture(5)
    path = tmp_path / "inspect.e57"
    sceneio.write(cloud, path)

    def fail_read(*_args, **_kwargs):
        raise AssertionError("point decode was called")

    monkeypatch.setattr(pye57.E57, "read_scan_raw", fail_read)
    info = sceneio.inspect(path)

    assert info.format == "e57"
    assert info.shape == (5, 3)
    assert info.count == 5
    assert info.metadata == {
        "scan_count": 1,
        "has_colors": True,
        "has_intensity": True,
        "has_invalid_state": False,
        "stored_point_count": 5,
    }


def test_e57_rejects_multiple_scans(tmp_path):
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

    with pytest.raises(sceneio.FormatError, match="exactly one data3D scan"):
        sceneio.read(path)


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
    sceneio.write(cloud, path)

    decoded = sceneio.read(path)
    path.unlink()
    gc.collect()

    np.testing.assert_array_equal(np.asarray(decoded.positions), positions)


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
        sceneio.write(cloud, tmp_path / "bad.e57")


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
        sceneio.write(cloud, path)

    assert path.read_bytes() == b"previous"
    assert not tuple(tmp_path.glob(".preserve.e57.*"))


def test_e57_capability_and_open_license_inventory():
    capabilities = sceneio.capabilities("e57")
    assert capabilities.available
    assert capabilities.requires_features == ("pye57",)
    assert "single_scan" in capabilities.supported_features
    assert "multiple_scans" in capabilities.unsupported_features

    license_root = Path(__file__).resolve().parents[2] / "LICENSES"
    assert "Permission is hereby granted" in (
        license_root / "pye57.txt"
    ).read_text(encoding="utf-8")
    assert "Boost Software License" in (
        license_root / "libe57format.txt"
    ).read_text(encoding="utf-8")
