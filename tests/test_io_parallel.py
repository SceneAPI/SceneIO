"""O4 deterministic worker-lane and transform-loop coverage."""

from __future__ import annotations

import hashlib
import struct

import numpy as np
import pytest

from sceneio import _core


def _pixels(image):
    return np.asarray(image.pixels)


def _webp_palette_image():
    palette = np.array(
        [
            [0, 0, 0],
            [255, 255, 255],
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
            [255, 0, 255],
            [0, 255, 255],
        ],
        dtype=np.uint8,
    )
    yy, xx = np.indices((257, 257))
    array = palette[((xx // 7) + (yy // 11)) % len(palette)]
    return array, _core.image(array, color_space="srgb")


def test_webp_workers_are_byte_identical_and_reach_side_worker():
    array, image = _webp_palette_image()
    _core._install_webp_worker_counter()
    _core._install_webp_worker_counter()
    before = _core._webp_worker_launch_count()
    serial = bytes(
        _core.write_webp(
            image,
            lossless=True,
            _threads=False,
        )
    )
    assert _core._webp_worker_launch_count() == before
    parallel = bytes(_core.write_webp(image))
    assert _core._webp_worker_launch_count() > before
    assert parallel == serial
    np.testing.assert_array_equal(_pixels(_core.read_webp(serial)), array)


def test_webp_default_balanced_config_differs_from_old_config_losslessly():
    array, image = _webp_palette_image()
    balanced = bytes(_core.write_webp(image))
    old_config = bytes(
        _core.write_webp(
            image,
            lossless=True,
            _threads=False,
            _effort=100,
            _method=4,
        )
    )

    assert balanced != old_config
    np.testing.assert_array_equal(_pixels(_core.read_webp(balanced)), array)
    np.testing.assert_array_equal(
        _pixels(_core.read_webp(old_config)), array
    )


def test_webp_lossy_ignores_lossless_worker_controls():
    _, image = _webp_palette_image()
    prior = bytes(
        _core.write_webp(
            image,
            lossless=False,
            quality=90,
            _threads=False,
            _method=4,
        )
    )
    ignored_controls = bytes(
        _core.write_webp(
            image,
            lossless=False,
            quality=90,
            _threads=True,
            _effort=0,
            _method=6,
        )
    )
    assert ignored_controls == prior


@pytest.mark.parametrize("effort", [-1, 101])
def test_webp_rejects_invalid_lossless_effort(effort):
    image = _core.image(
        np.zeros((2, 2, 3), dtype=np.uint8), color_space="srgb"
    )
    with pytest.raises(ValueError, match="effort"):
        _core.write_webp(image, _effort=effort)


@pytest.mark.parametrize("method", [-1, 7])
def test_webp_rejects_invalid_method(method):
    image = _core.image(
        np.zeros((2, 2, 3), dtype=np.uint8), color_space="srgb"
    )
    with pytest.raises(ValueError, match="method"):
        _core.write_webp(image, _method=method)


def test_xyz_one_and_many_lanes_are_byte_identical():
    rng = np.random.default_rng(41)
    positions = rng.standard_normal((50_000, 3)).astype(np.float32)
    positions[0] = np.array([-0.0, np.inf, -np.inf], dtype=np.float32)
    colors = rng.integers(0, 256, positions.shape, dtype=np.uint8)
    cloud = _core.point_cloud(positions, colors=colors)

    serial = bytes(_core.write_xyz(cloud, _lanes=1))
    parallel = bytes(_core.write_xyz(cloud, _lanes=4))
    assert parallel == serial
    decoded = np.asarray(_core.read_xyz(parallel).positions)
    np.testing.assert_array_equal(decoded, positions)
    assert np.array_equal(np.signbit(decoded), np.signbit(positions))


def test_png16_one_and_many_lanes_are_byte_identical():
    values = (
        (np.arange(193 * 257 * 4, dtype=np.uint32) * 40503) & 0xFFFF
    ).astype(np.uint16).reshape(193, 257, 4)
    image = _core.image(
        values, color_space="srgb", alpha_mode="straight"
    )

    serial = bytes(_core.write_png(image, _lanes=1))
    parallel = bytes(_core.write_png(image, _lanes=4))
    assert parallel == serial
    np.testing.assert_array_equal(
        _pixels(_core.read_png(serial, _lanes=1)), values
    )
    np.testing.assert_array_equal(
        _pixels(_core.read_png(serial, _lanes=4)), values
    )


def _exr_values():
    values = (
        (np.arange(64 * 48 * 3, dtype=np.uint32) * 2654435761)
        & 0x00FFFFFF
    ).astype(np.float32)
    return values.reshape(48, 64, 3) / np.float32(0x01000000)


def test_exr_workers_preserve_serial_bytes_and_lane_results():
    values = _exr_values()
    image = _core.image(values, color_space="linear")
    serial = bytes(_core.write_exr(image, _lanes=1))
    parallel = bytes(_core.write_exr(image, _lanes=4))

    # Captured from the pre-O4 serial tinyexr build. Threaded scanline-block
    # compression must preserve byte-for-byte output, not merely decoded pixels.
    assert hashlib.sha256(parallel).hexdigest() == (
        "7e9c6c25705bb1be825ed25c2b01704a17074758941005820ebf849182a4ab1c"
    )
    assert parallel == serial
    np.testing.assert_array_equal(
        _pixels(_core.read_exr(serial, _lanes=1)), values
    )
    np.testing.assert_array_equal(
        _pixels(_core.read_exr(serial, _lanes=4)), values
    )


def _duplicate_exr_scanline_destinations(data):
    blob = bytearray(data)
    pos = 8  # magic + version
    while True:
        name_end = blob.index(0, pos)
        if name_end == pos:
            pos += 1
            break
        pos = name_end + 1
        pos = blob.index(0, pos) + 1  # skip attribute type
        attr_size = struct.unpack_from("<I", blob, pos)[0]
        pos += 4 + attr_size

    # _exr_values() has 48 rows; ZIP uses 16-row chunks.
    offsets = [
        struct.unpack_from("<Q", blob, pos + 8 * i)[0] for i in range(3)
    ]
    lines = [struct.unpack_from("<i", blob, off)[0] for off in offsets]
    assert lines == [0, 16, 32]
    for off in offsets[1:]:
        struct.pack_into("<i", blob, off, lines[0])
    return bytes(blob)


def test_exr_rejects_overlapping_scanline_chunks():
    image = _core.image(_exr_values(), color_space="linear")
    valid = bytes(_core.write_exr(image, _lanes=1))
    malformed = _duplicate_exr_scanline_destinations(valid)
    with pytest.raises(ValueError, match="Invalid/Corrupted"):
        _core.read_exr(malformed, _lanes=4)


def _las_cloud(n=50_000):
    rng = np.random.default_rng(42)
    positions = rng.uniform(-100.0, 100.0, (n, 3)).astype(np.float32)
    colors = rng.integers(0, 65536, (n, 3), dtype=np.uint16)
    intensity = rng.integers(0, 65536, n, dtype=np.uint16).astype(np.float32)
    return _core.point_cloud(
        positions,
        colors16=colors,
        intensity=intensity,
        intensity_range="u16",
        origin=np.array([500000.0, 4000000.0, 10.0]),
    )


def test_las_one_and_many_lanes_are_byte_identical():
    cloud = _las_cloud()
    serial = bytes(_core.write_las(cloud, _lanes=1))
    parallel = bytes(_core.write_las(cloud, _lanes=4))
    assert parallel == serial

    one = _core.read_las(serial, _lanes=1)
    many = _core.read_las(serial, _lanes=4)
    np.testing.assert_array_equal(
        np.asarray(many.positions), np.asarray(one.positions)
    )
    np.testing.assert_array_equal(
        np.asarray(many.colors16), np.asarray(one.colors16)
    )
    np.testing.assert_array_equal(
        np.asarray(many.intensities), np.asarray(one.intensities)
    )
    np.testing.assert_array_equal(many.origin, one.origin)


def test_parallel_worker_exception_is_rethrown_and_workers_join():
    positions = np.zeros((10_000, 3), dtype=np.float32)
    positions[-1, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        _core.write_las(_core.point_cloud(positions), _lanes=4)

    valid = _core.point_cloud(np.zeros((8, 3), dtype=np.float32))
    assert bytes(_core.write_las(valid, _lanes=4)).startswith(b"LASF")


def test_parallel_lane_count_is_bounded():
    cloud = _core.point_cloud(np.zeros((8, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="lane count"):
        _core.write_xyz(cloud, _lanes=65)
    with pytest.raises(ValueError, match="lane count"):
        _core._parallel_lane_count(0, 65, 1)


def test_automatic_lane_selection_reaches_parallel_branch_above_threshold():
    cap = _core._parallel_hardware_lane_cap()
    assert 1 <= cap <= 8
    assert _core._parallel_lane_count(9_999, 0, 10_000) == 1
    assert _core._parallel_lane_count(40_000, 0, 10_000) == min(cap, 4)
