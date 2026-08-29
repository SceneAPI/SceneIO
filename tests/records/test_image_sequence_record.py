"""Record tests for lazy-path, packed-raster, and planar ImageSequence storage."""

from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import _avif as avif_adapter


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
    exposure_durations_ns: np.ndarray | None = None,
    readout_step_durations_ns: np.ndarray | None = None,
    readout_directions: list[str] | None = None,
    timestamp_reference: str = "unknown",
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
        exposure_durations_ns=exposure_durations_ns,
        readout_step_durations_ns=readout_step_durations_ns,
        readout_directions=readout_directions,
        timestamp_reference=timestamp_reference,
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
    exposure_durations_ns: np.ndarray | None = None,
    readout_step_durations_ns: np.ndarray | None = None,
    readout_directions: list[str] | None = None,
    timestamp_reference: str = "unknown",
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
        exposure_durations_ns=exposure_durations_ns,
        readout_step_durations_ns=readout_step_durations_ns,
        readout_directions=readout_directions,
        timestamp_reference=timestamp_reference,
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
    exposure_durations_ns: np.ndarray | None = None,
    readout_step_durations_ns: np.ndarray | None = None,
    readout_directions: list[str] | None = None,
    timestamp_reference: str = "unknown",
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
        exposure_durations_ns=exposure_durations_ns,
        readout_step_durations_ns=readout_step_durations_ns,
        readout_directions=readout_directions,
        timestamp_reference=timestamp_reference,
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
    assert not sequence.has_acquisition_timing
    assert not sequence.has_exposure_timing
    assert not sequence.has_readout_timing
    assert sequence.exposure_durations_ns.shape == (0,)
    assert sequence.readout_step_durations_ns.shape == (0,)
    assert sequence.readout_directions == []
    assert sequence.timestamp_reference == "unknown"
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


def test_acquisition_timing_is_owned_exact_and_declares_equation():
    exposure = np.array([4_000_000, 5_000_000], np.int64)
    readout = np.array([10_000, 20_000], np.int64)
    directions = ["top_to_bottom", "top_to_bottom"]
    sequence = _path_sequence(
        timestamps=np.array([100_000_000, 200_000_000], np.int64),
        durations=np.array([100_000_000, 100_000_000], np.int64),
        exposure_durations_ns=exposure,
        readout_step_durations_ns=readout,
        readout_directions=directions,
        timestamp_reference="exposure_midpoint",
    )
    exposure[:] = -1
    readout[:] = -1
    directions[0] = "global"

    assert sequence.has_acquisition_timing
    assert sequence.has_exposure_timing
    assert sequence.has_readout_timing
    assert sequence.exposure_durations_ns.tolist() == [4_000_000, 5_000_000]
    assert sequence.readout_step_durations_ns.tolist() == [10_000, 20_000]
    assert sequence.readout_directions == ["top_to_bottom", "top_to_bottom"]
    assert sequence.timestamp_reference == "exposure_midpoint"
    assert sequence.acquisition_timing_convention == (
        "coordinate_reference_ns = frame_timestamp_ns + direction_sign * "
        "step_index * readout_step_duration_ns"
    )
    assert not sequence.exposure_durations_ns.flags.writeable
    assert not sequence.readout_step_durations_ns.flags.writeable

    # Top-to-bottom uses d=+1. The reference instant for raster row 3 is
    # therefore t + 3*r; exposure midpoint semantics are declared separately.
    assert sequence.timestamps_ns[0] + 3 * sequence.readout_step_durations_ns[0] == (
        100_030_000
    )


def test_global_acquisition_omits_step_durations_and_zero_is_present():
    sequence = _packed_sequence(
        np.zeros((2, 2, 3, 3), np.uint8),
        timestamps=np.array([0, 10], np.int64),
        durations=np.array([10, 10], np.int64),
        exposure_durations_ns=np.array([0, 0], np.int64),
        readout_directions=["global", "global"],
        timestamp_reference="exposure_start",
    )
    assert sequence.exposure_durations_ns.tolist() == [0, 0]
    assert sequence.readout_step_durations_ns.shape == (0,)
    assert sequence.readout_directions == ["global", "global"]


def test_acquisition_views_keep_temporary_record_alive():
    view = _path_sequence(
        timestamps=np.array([0, 10], np.int64),
        durations=np.array([10, 10], np.int64),
        exposure_durations_ns=np.array([1, 2], np.int64),
        timestamp_reference="exposure_end",
    ).exposure_durations_ns
    gc.collect()
    gc.collect()
    assert view.tolist() == [1, 2]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"timestamp_reference": "exposure_start"},
            "requires frame timing",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "exposure_durations_ns": np.array([1, 2], np.int64),
            },
            "declared timestamp_reference",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "exposure_durations_ns": np.array([1], np.int64),
                "timestamp_reference": "exposure_start",
            },
            "empty or",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "exposure_durations_ns": np.array([1, -1], np.int64),
                "timestamp_reference": "exposure_start",
            },
            "nonnegative",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "readout_step_durations_ns": np.array([1, 1], np.int64),
                "timestamp_reference": "exposure_start",
            },
            "require directions",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "readout_directions": ["top_to_bottom", "top_to_bottom"],
                "timestamp_reference": "exposure_start",
            },
            "requires N step durations",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "readout_step_durations_ns": np.array([-1, 1], np.int64),
                "readout_directions": ["top_to_bottom", "top_to_bottom"],
                "timestamp_reference": "exposure_start",
            },
            "nonnegative",
        ),
        (
            {
                "timestamps": np.array(
                    [np.iinfo(np.int64).max - 10, np.iinfo(np.int64).max - 5],
                    np.int64,
                ),
                "durations": np.array([1, 1], np.int64),
                "readout_step_durations_ns": np.array([10, 10], np.int64),
                "readout_directions": ["top_to_bottom", "top_to_bottom"],
                "timestamp_reference": "exposure_start",
            },
            "overflows int64",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "readout_step_durations_ns": np.array([1, 1], np.int64),
                "readout_directions": ["global", "global"],
                "timestamp_reference": "exposure_start",
            },
            "global readout",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "readout_step_durations_ns": np.array([1, 1], np.int64),
                "readout_directions": ["global", "top_to_bottom"],
                "timestamp_reference": "exposure_start",
            },
            "mixed global/rolling",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "readout_step_durations_ns": np.array([1, 1], np.int64),
                "readout_directions": ["diagonal", "diagonal"],
                "timestamp_reference": "exposure_start",
            },
            "readout direction",
        ),
        (
            {
                "timestamps": np.array([0, 10], np.int64),
                "durations": np.array([10, 10], np.int64),
                "timestamp_reference": "frame_start",
            },
            "timestamp_reference",
        ),
    ],
)
def test_acquisition_timing_rejects_ambiguous_or_invalid_combinations(
    kwargs, message
):
    with pytest.raises(ValueError, match=message):
        _path_sequence(**kwargs)


def test_acquisition_arguments_are_keyword_only():
    with pytest.raises(TypeError):
        _core.image_sequence_paths(
            ["a.png"],
            ["a.png"],
            np.array([0], np.int64),
            np.array([1], np.int64),
            2,
            3,
            3,
            "uint8",
            "srgb",
            "none",
            np.array([1], np.int64),
        )


@pytest.mark.parametrize(
    "writer_name",
    ["write_apng", "write_animated_webp", "write_webm"],
)
def test_sequence_writers_refuse_unrepresented_acquisition_timing(writer_name):
    sequence = _packed_sequence(
        np.zeros((2, 2, 3, 3), np.uint8),
        timestamps=np.array([0, 10_000_000], np.int64),
        durations=np.array([10_000_000, 10_000_000], np.int64),
        exposure_durations_ns=np.array([1, 1], np.int64),
        timestamp_reference="exposure_start",
    )
    with pytest.raises(ValueError, match="not representable"):
        getattr(_core, writer_name)(sequence)


def test_directory_writer_refuses_unrepresented_acquisition_timing(tmp_path):
    frame = tmp_path / "frame.pgm"
    frame.write_bytes(b"P5\n3 2\n255\n" + bytes(range(6)))
    sequence = _core.image_sequence_paths(
        [str(frame)],
        [frame.name],
        np.array([0], np.int64),
        np.array([10], np.int64),
        2,
        3,
        1,
        "uint8",
        "gray",
        "none",
        exposure_durations_ns=np.array([1], np.int64),
        timestamp_reference="exposure_start",
    )
    with pytest.raises(sceneio.FormatError, match="not representable"):
        sceneio.write(
            sequence,
            tmp_path / "copy",
            format="image_sequence",
        )


@pytest.mark.parametrize("writer_name", ["write_y4m", "write_theora"])
def test_planar_writers_refuse_unrepresented_acquisition_timing(writer_name):
    y = np.zeros((2, 2, 4), np.uint8)
    chroma = np.zeros((2, 1, 2), np.uint8)
    sequence = _yuv_sequence(
        y,
        chroma,
        chroma,
        timestamps=np.array([0, 40_000_000], np.int64),
        durations=np.array([40_000_000, 40_000_000], np.int64),
        siting="unspecified" if writer_name == "write_theora" else "jpeg",
        frame_rate=(25, 1),
        exposure_durations_ns=np.array([1, 1], np.int64),
        timestamp_reference="exposure_start",
    )
    with pytest.raises(ValueError, match="not representable"):
        getattr(_core, writer_name)(sequence)


def test_animated_avif_writer_refuses_unrepresented_acquisition_timing():
    sequence = _packed_sequence(
        np.zeros((2, 2, 3, 3), np.uint8),
        timestamps=np.array([0, 10_000_000], np.int64),
        durations=np.array([10_000_000, 10_000_000], np.int64),
        exposure_durations_ns=np.array([1, 1], np.int64),
        timestamp_reference="exposure_start",
    )
    with pytest.raises(ValueError, match="not representable"):
        avif_adapter._validate_sequence(sequence)


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
