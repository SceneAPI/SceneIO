"""Record tests for lazy-path, packed-raster, and planar ImageSequence storage."""

from __future__ import annotations

import gc

import numpy as np
import pytest

from sceneio import _core


def _empty_timing() -> np.ndarray:
    return np.empty(0, np.int64)


def _path_sequence(
    *,
    paths: list[str] | None = None,
    names: list[str] | None = None,
    timestamps: np.ndarray | None = None,
    durations: np.ndarray | None = None,
    height: int = 5,
    width: int = 7,
    channels: int = 3,
    dtype: str = "uint8",
    color_space: str = "unknown",
    alpha_mode: str = "none",
):
    paths = ["a.png", "b.png"] if paths is None else paths
    names = ["a.png", "b.png"] if names is None else names
    timestamps = _empty_timing() if timestamps is None else timestamps
    durations = _empty_timing() if durations is None else durations
    return _core.image_sequence_paths(
        paths,
        names,
        timestamps,
        durations,
        height,
        width,
        channels,
        dtype,
        color_space,
        alpha_mode,
    )


def _yuv_sequence(
    y: np.ndarray,
    u: np.ndarray | None = None,
    v: np.ndarray | None = None,
    *,
    timestamps: np.ndarray | None = None,
    durations: np.ndarray | None = None,
    subsampling: str = "420",
    siting: str = "jpeg",
    color_range: str = "limited",
    matrix: str = "bt709",
    interlace: str = "progressive",
    frame_rate: tuple[int, int] = (30, 1),
    pixel_aspect: tuple[int, int] = (1, 1),
):
    timestamps = _empty_timing() if timestamps is None else timestamps
    durations = _empty_timing() if durations is None else durations
    return _core.image_sequence_yuv(
        y,
        u,
        v,
        timestamps,
        durations,
        subsampling,
        siting,
        color_range,
        matrix,
        interlace,
        frame_rate[0],
        frame_rate[1],
        pixel_aspect[0],
        pixel_aspect[1],
    )


def _packed_sequence(
    pixels: np.ndarray,
    *,
    timestamps: np.ndarray | None = None,
    durations: np.ndarray | None = None,
    color_space: str = "srgb",
    alpha_mode: str = "none",
    maxval: int | None = None,
    loop_count: int | None = None,
    background_rgba: np.ndarray | None = None,
):
    timestamps = _empty_timing() if timestamps is None else timestamps
    durations = _empty_timing() if durations is None else durations
    return _core.image_sequence_packed(
        pixels,
        timestamps,
        durations,
        color_space,
        alpha_mode,
        maxval,
        loop_count,
        background_rgba,
    )


def test_encoded_path_record_owns_references_and_metadata():
    paths = ["relative/frame1.png", "relative/frame2.png"]
    names = ["frame1.png", "frame2.png"]
    sequence = _path_sequence(paths=paths, names=names)
    paths[0] = "changed.png"
    names[0] = "changed.png"

    assert sequence.frame_paths == ["relative/frame1.png", "relative/frame2.png"]
    assert sequence.frame_names == ["frame1.png", "frame2.png"]
    assert sequence.num_frames == 2
    assert (sequence.height, sequence.width, sequence.channels) == (5, 7, 3)
    assert sequence.storage_mode == "encoded_paths"
    assert sequence.frame_dtype == "uint8"
    assert sequence.color_space == "unknown"
    assert sequence.alpha_mode == "none"
    assert not sequence.has_timing
    assert sequence.has_paths
    assert not sequence.has_pixels
    assert not sequence.has_chroma
    assert sequence.pixels.shape == (0, 0, 0)
    assert sequence.y.shape == sequence.u.shape == sequence.v.shape == (0, 0, 0)
    assert repr(sequence) == "<ImageSequence n=2 shape=(5,7) encoded_paths>"


@pytest.mark.parametrize(
    ("dtype", "maxval"),
    [
        (np.uint8, 255),
        (np.uint16, 65535),
        (np.float32, 0),
    ],
)
def test_packed_frames_own_dtype_exact_samples_and_metadata(dtype, maxval):
    pixels = np.arange(2 * 3 * 5 * 3, dtype=dtype).reshape(2, 3, 5, 3)
    expected = pixels.copy()
    sequence = _packed_sequence(
        pixels,
        timestamps=np.array([0, 17_000_000], np.int64),
        durations=np.array([17_000_000, 23_000_000], np.int64),
        loop_count=4,
        background_rgba=np.array([1, 2, 3, 4], np.uint8),
    )
    pixels[...] = 0

    assert sequence.storage_mode == "packed"
    assert sequence.has_pixels
    assert not sequence.has_paths
    assert not sequence.has_chroma
    assert sequence.frame_dtype == np.dtype(dtype).name
    assert sequence.maxval == maxval
    assert sequence.color_space == "srgb"
    assert sequence.alpha_mode == "none"
    assert sequence.has_loop_count
    assert sequence.loop_count == 4
    assert sequence.has_background
    assert sequence.background_rgba.tolist() == [1, 2, 3, 4]
    assert not sequence.background_rgba.flags.writeable
    np.testing.assert_array_equal(sequence.pixels, expected)
    assert not sequence.pixels.flags.writeable
    assert sequence.y.shape == sequence.u.shape == sequence.v.shape == (0, 0, 0)


def test_packed_rgba_and_grayscale_shapes_and_lifetime():
    rgba = np.arange(2 * 3 * 4 * 4, dtype=np.uint8).reshape(2, 3, 4, 4)
    sequence = _packed_sequence(rgba, alpha_mode="straight")
    assert sequence.pixels.shape == (2, 3, 4, 4)
    assert sequence.channels == 4

    gray = np.arange(2 * 3 * 4, dtype=np.uint16).reshape(2, 3, 4)
    view = _packed_sequence(gray, color_space="gray").pixels
    gc.collect()
    gc.collect()
    assert view.shape == (2, 3, 4)
    np.testing.assert_array_equal(view, gray)


@pytest.mark.parametrize(
    ("pixels", "kwargs", "message"),
    [
        (np.zeros((2, 3), np.uint8), {}, "packed pixels"),
        (np.zeros((1, 2, 3, 2), np.uint8), {}, "1, 3, or 4"),
        (np.zeros((1, 2, 3, 4), np.uint8), {}, "alpha_mode"),
        (
            np.zeros((1, 2, 3, 3), np.uint8),
            {"alpha_mode": "straight"},
            "alpha_mode",
        ),
        (
            np.zeros((1, 2, 3, 3), np.uint8),
            {"maxval": 256},
            "maxval",
        ),
        (
            np.zeros((1, 2, 3, 3), np.float32),
            {"maxval": 1},
            "maxval",
        ),
        (
            np.zeros((1, 2, 3, 3), np.uint8),
            {"background_rgba": np.zeros(3, np.uint8)},
            "background_rgba",
        ),
    ],
)
def test_packed_validation(pixels, kwargs, message):
    with pytest.raises(ValueError, match=message):
        _packed_sequence(pixels, **kwargs)


def test_exact_timing_is_owned_read_only_and_lifetime_safe():
    timestamps = np.array([0, 33_366_666], np.int64)
    durations = np.array([33_366_666, 33_366_667], np.int64)
    sequence = _path_sequence(timestamps=timestamps, durations=durations)
    timestamps[:] = -1
    durations[:] = -1

    assert sequence.has_timing
    assert sequence.timestamps_ns.tolist() == [0, 33_366_666]
    assert sequence.durations_ns.tolist() == [33_366_666, 33_366_667]
    assert not sequence.timestamps_ns.flags.writeable
    assert not sequence.durations_ns.flags.writeable

    kept = _path_sequence(
        timestamps=np.array([10, 20], np.int64),
        durations=np.array([5, 5], np.int64),
    ).timestamps_ns
    gc.collect()
    gc.collect()
    assert kept.tolist() == [10, 20]


@pytest.mark.parametrize(
    ("subsampling", "siting", "chroma_shape"),
    [
        ("420", "jpeg", (2, 3, 4)),
        ("420", "mpeg2", (2, 3, 4)),
        ("420", "paldv", (2, 3, 4)),
        ("422", "unspecified", (2, 5, 4)),
        ("444", "unspecified", (2, 5, 7)),
    ],
)
def test_planar_layouts_preserve_odd_dimensions_bit_exact(
    subsampling, siting, chroma_shape
):
    y = np.arange(2 * 5 * 7, dtype=np.uint8).reshape(2, 5, 7)
    u = (np.arange(np.prod(chroma_shape), dtype=np.uint8) + 71).reshape(
        chroma_shape
    )
    v = (np.arange(np.prod(chroma_shape), dtype=np.uint8) + 139).reshape(
        chroma_shape
    )
    expected_y = y.copy()
    expected_u = u.copy()
    expected_v = v.copy()
    sequence = _yuv_sequence(
        y,
        u,
        v,
        subsampling=subsampling,
        siting=siting,
    )
    y[:] = 0
    u[:] = 0
    v[:] = 0

    assert sequence.storage_mode == "yuv_planar"
    assert not sequence.has_pixels
    assert not sequence.has_paths
    assert sequence.color_space == "ycbcr"
    assert sequence.channels == 3
    assert sequence.has_chroma
    assert (sequence.chroma_height, sequence.chroma_width) == chroma_shape[1:]
    assert sequence.chroma_subsampling == subsampling
    assert sequence.chroma_siting == siting
    assert sequence.color_range == "limited"
    assert sequence.matrix == "bt709"
    assert sequence.frame_rate_numerator == 30
    assert sequence.frame_rate_denominator == 1
    assert sequence.pixel_aspect_numerator == 1
    assert sequence.pixel_aspect_denominator == 1
    assert sequence.y.tobytes() == expected_y.tobytes()
    assert sequence.u.tobytes() == expected_u.tobytes()
    assert sequence.v.tobytes() == expected_v.tobytes()
    assert not sequence.y.flags.writeable
    assert not sequence.u.flags.writeable
    assert not sequence.v.flags.writeable


def test_monochrome_planes_and_view_outlive_temporary_record():
    expected = np.arange(2 * 3 * 5, dtype=np.uint8).reshape(2, 3, 5)
    sequence = _yuv_sequence(
        expected,
        subsampling="mono",
        siting="none",
        matrix="unknown",
    )
    assert sequence.channels == 1
    assert sequence.color_space == "gray"
    assert not sequence.has_chroma
    assert sequence.u.shape == sequence.v.shape == (2, 0, 0)

    view = _yuv_sequence(
        expected,
        subsampling="mono",
        siting="none",
        matrix="unknown",
    ).y
    gc.collect()
    gc.collect()
    np.testing.assert_array_equal(view, expected)


@pytest.mark.parametrize(
    ("timestamps", "durations", "message"),
    [
        (np.array([0], np.int64), np.empty(0, np.int64), "both be empty"),
        (np.array([-1, 2], np.int64), np.ones(2, np.int64), "nonnegative"),
        (np.array([0, 0], np.int64), np.ones(2, np.int64), "strictly"),
        (np.array([0, 2], np.int64), np.array([1, 0], np.int64), "positive"),
    ],
)
def test_timing_validation(timestamps, durations, message):
    with pytest.raises(ValueError, match=message):
        _path_sequence(timestamps=timestamps, durations=durations)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"paths": ["a.png"], "names": ["a.png", "b.png"]}, "equal length"),
        ({"names": ["same.png", "same.png"]}, "unique"),
        ({"paths": ["a\0.png", "b.png"]}, "NUL"),
        ({"height": 0}, "positive"),
        ({"channels": 2}, "1, 3, or 4"),
        ({"dtype": "float16"}, "frame_dtype"),
        ({"color_space": "bt709"}, "color_space"),
        ({"channels": 4, "alpha_mode": "none"}, "alpha_mode"),
        ({"channels": 3, "alpha_mode": "straight"}, "alpha_mode"),
    ],
)
def test_encoded_path_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        _path_sequence(**kwargs)


def test_planar_shape_and_metadata_validation():
    y = np.zeros((2, 5, 7), np.uint8)
    chroma = np.zeros((2, 3, 4), np.uint8)
    with pytest.raises(ValueError, match="requires"):
        _yuv_sequence(y, None, None)
    with pytest.raises(ValueError, match="shapes"):
        _yuv_sequence(y, chroma[:, :, :3], chroma)
    with pytest.raises(ValueError, match="monochrome"):
        _yuv_sequence(
            y,
            chroma,
            chroma,
            subsampling="mono",
            siting="none",
            matrix="unknown",
        )
    with pytest.raises(ValueError, match="subsampling"):
        _yuv_sequence(y, chroma, chroma, subsampling="411")
    with pytest.raises(ValueError, match="chroma_siting"):
        _yuv_sequence(y, chroma, chroma, siting="left")
    with pytest.raises(ValueError, match="color_range"):
        _yuv_sequence(y, chroma, chroma, color_range="studio")
    with pytest.raises(ValueError, match="matrix"):
        _yuv_sequence(y, chroma, chroma, matrix="xyz")
    with pytest.raises(ValueError, match="interlace"):
        _yuv_sequence(y, chroma, chroma, interlace="mixed")
    with pytest.raises(ValueError, match="frame-rate"):
        _yuv_sequence(y, chroma, chroma, frame_rate=(1, 0))
    with pytest.raises(ValueError, match="pixel-aspect"):
        _yuv_sequence(y, chroma, chroma, pixel_aspect=(1, 0))


def test_planar_factory_rejects_wrong_dtype_or_rank():
    with pytest.raises((TypeError, ValueError)):
        _yuv_sequence(np.zeros((1, 2, 3), np.uint16))
    with pytest.raises(ValueError, match=r"Y plane.*N,H,W"):
        _yuv_sequence(np.zeros((2, 3), np.uint8))
