"""Lazy image-directory sequence parity, ordering, and bounded-copy tests."""

from __future__ import annotations

import gc
import json
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import _image_sequence as adapter
from sceneio.io import registry


def _frame_contract(
    *,
    height: int = 3,
    width: int = 4,
    channels: int = 1,
    dtype: str = "uint8",
    color_space: str = "gray",
    alpha_mode: str = "none",
    maxval: int = 255,
    projection: str = "unknown",
    projection_canvas_width: int = 0,
    projection_canvas_height: int = 0,
    projection_crop_left: int = 0,
    projection_crop_top: int = 0,
):
    return {
        "height": height,
        "width": width,
        "channels": channels,
        "dtype": dtype,
        "color_space": color_space,
        "alpha_mode": alpha_mode,
        "maxval": maxval,
        "projection": projection,
        "projection_canvas_width": projection_canvas_width,
        "projection_canvas_height": projection_canvas_height,
        "projection_crop_left": projection_crop_left,
        "projection_crop_top": projection_crop_top,
    }


def _manifest(frames, *, contract=None, version=2, **extra):
    return {
        "sceneio_image_sequence": version,
        "frame_contract": _frame_contract() if contract is None else contract,
        "frames": frames,
        **extra,
    }


def _pgm(values: np.ndarray) -> bytes:
    values = np.asarray(values, np.uint8)
    height, width = values.shape
    return f"P5\n{width} {height}\n255\n".encode("ascii") + values.tobytes()


def _write_frames(directory: Path, names: list[str], *, shape=(3, 4)):
    directory.mkdir()
    payloads = {}
    for index, name in enumerate(names):
        values = np.arange(shape[0] * shape[1], dtype=np.uint8).reshape(shape) + index * 17
        payloads[name] = _pgm(values)
        (directory / name).write_bytes(payloads[name])
    return payloads


def _path_record(
    paths: list[Path],
    names: list[str],
    *,
    timestamps: np.ndarray | None = None,
    durations: np.ndarray | None = None,
    height: int = 3,
    width: int = 4,
):
    empty = np.empty(0, np.int64)
    return _core.image_sequence_paths(
        [str(path) for path in paths],
        names,
        empty if timestamps is None else timestamps,
        empty if durations is None else durations,
        height,
        width,
        1,
        "uint8",
        "gray",
        "none",
    )


def test_unmanifested_directory_uses_deterministic_natural_order(tmp_path):
    directory = tmp_path / "frames"
    payloads = _write_frames(
        directory,
        ["frame10.pgm", "frame2.pgm", "frame1.pgm"],
    )
    (directory / "notes.txt").write_text("ignored", encoding="utf-8")

    sequence = sceneio.read(directory, format="image_sequence")
    assert isinstance(sequence, sceneio.ImageSequence)
    assert sequence.storage_mode == "encoded_paths"
    assert sequence.frame_names == [
        "frame1.pgm",
        "frame2.pgm",
        "frame10.pgm",
    ]
    assert all(Path(value).is_absolute() for value in sequence.frame_paths)
    assert (sequence.num_frames, sequence.height, sequence.width) == (3, 3, 4)
    assert sequence.channels == 1
    assert sequence.frame_dtype == "uint8"
    assert not sequence.has_timing
    assert sequence.y.shape == (0, 0, 0)

    # Frames remain encoded and independently readable through their owned paths.
    for name, path in zip(sequence.frame_names, sequence.frame_paths, strict=True):
        assert Path(path).read_bytes() == payloads[name]
        assert sceneio.read(path).pixels.tobytes() == payloads[name][-12:]


def test_manifest_order_exact_timing_inspect_and_partial(tmp_path):
    directory = tmp_path / "timed"
    payloads = _write_frames(directory, ["a.pgm", "b.pgm", "c.pgm"])
    document = _manifest(
        [
            {"file": "c.pgm", "timestamp_ns": 100, "duration_ns": 40},
            {"file": "a.pgm", "timestamp_ns": 140, "duration_ns": 41},
            {"file": "b.pgm", "timestamp_ns": 181, "duration_ns": 39},
        ]
    )
    (directory / "sceneio_sequence.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )

    assert sceneio.detect(directory) == "image_sequence"
    sequence = sceneio.read(directory)
    assert sequence.frame_names == ["c.pgm", "a.pgm", "b.pgm"]
    assert sequence.timestamps_ns.tolist() == [100, 140, 181]
    assert sequence.durations_ns.tolist() == [40, 41, 39]
    assert sequence.has_timing
    for name, path in zip(sequence.frame_names, sequence.frame_paths, strict=True):
        assert Path(path).read_bytes() == payloads[name]

    info = sceneio.inspect(directory)
    assert info.format == "image_sequence"
    assert info.payload_kind == "image_sequence"
    assert info.shape == (3, 3, 4, 1)
    assert info.dtype == "uint8"
    assert info.count == 3
    assert info.channels == 1
    assert info.metadata == {
        "storage_mode": "encoded_paths",
        "has_timing": True,
        "manifest": True,
        "manifest_version": 2,
        "frame_names": ("c.pgm", "a.pgm", "b.pgm"),
        "frame_formats": ("netpbm", "netpbm", "netpbm"),
        "color_space": "gray",
        "alpha_mode": "none",
        "maxval": 255,
        "projection": "unknown",
        "projection_canvas_width": 0,
        "projection_canvas_height": 0,
        "projection_crop_left": 0,
        "projection_crop_top": 0,
        "is_full_sphere": False,
    }

    selected = sceneio.read_partial(directory, frames=(1, 3))
    assert selected.frame_names == ["a.pgm", "b.pgm"]
    assert selected.timestamps_ns.tolist() == [140, 181]
    assert selected.durations_ns.tolist() == [41, 39]


def test_directory_write_copies_encoded_bytes_and_is_deterministic(tmp_path):
    source = tmp_path / "source"
    payloads = _write_frames(source, ["f1.pgm", "f2.pgm"])
    sequence = _path_record(
        [source / "f1.pgm", source / "f2.pgm"],
        ["f1.pgm", "f2.pgm"],
        timestamps=np.array([0, 50], np.int64),
        durations=np.array([50, 50], np.int64),
    )

    destination = tmp_path / "output"
    sceneio.write(sequence, destination)
    assert sceneio.detect(destination) == "image_sequence"
    assert (destination / "f1.pgm").read_bytes() == payloads["f1.pgm"]
    assert (destination / "f2.pgm").read_bytes() == payloads["f2.pgm"]
    expected_manifest = _manifest(
        [
            {"duration_ns": 50, "file": "f1.pgm", "timestamp_ns": 0},
            {"duration_ns": 50, "file": "f2.pgm", "timestamp_ns": 50},
        ]
    )
    assert (destination / "sceneio_sequence.json").read_text(encoding="utf-8") == (
        json.dumps(
            expected_manifest,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    decoded = sceneio.read(destination)
    assert decoded.frame_names == sequence.frame_names
    assert decoded.timestamps_ns.tolist() == [0, 50]

    # Replacing an existing output removes stale files and keeps source bytes.
    (destination / "stale.txt").write_text("old", encoding="utf-8")
    sceneio.write(sequence, destination)
    assert not (destination / "stale.txt").exists()
    assert (source / "f1.pgm").read_bytes() == payloads["f1.pgm"]


def test_rewriting_the_same_directory_stages_all_reads_before_replace(tmp_path):
    directory = tmp_path / "frames"
    payloads = _write_frames(directory, ["a.pgm", "b.pgm"])
    sequence = sceneio.read(directory, format="image_sequence")
    sceneio.write(sequence, directory, format="image_sequence")
    assert (directory / "a.pgm").read_bytes() == payloads["a.pgm"]
    assert (directory / "b.pgm").read_bytes() == payloads["b.pgm"]
    assert sceneio.detect(directory) == "image_sequence"


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"sceneio_image_sequence": 2, "frames": [{"file": "a.pgm"}]},
        _manifest([{"file": "a.pgm"}], version=1),
        _manifest([]),
        _manifest([{"file": "a.pgm"}], extra=1),
        _manifest([{"file": "../a.pgm"}]),
        _manifest([{"file": "a.txt"}]),
        _manifest([{"file": "a.tif"}]),
        _manifest([{"file": "a.pgm"}, {"file": "a.pgm"}]),
        _manifest(
            [
                {"file": "a.pgm", "timestamp_ns": 0, "duration_ns": 1},
                {"file": "b.pgm"},
            ]
        ),
        _manifest(
            [
                {"file": "a.pgm", "timestamp_ns": True, "duration_ns": 1},
            ]
        ),
        _manifest([{"file": "missing.pgm"}]),
        _manifest(
            [{"file": "a.pgm"}],
            contract=_frame_contract(projection_canvas_width=4),
        ),
    ],
)
def test_manifest_schema_and_references_are_strict(tmp_path, document):
    directory = tmp_path / "invalid"
    _write_frames(directory, ["a.pgm", "b.pgm"])
    (directory / "sceneio_sequence.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )
    with pytest.raises(sceneio.FormatError):
        sceneio.read(directory)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(directory)


def test_invalid_json_oversized_manifest_and_heterogeneous_frames_reject(tmp_path):
    invalid = tmp_path / "invalid_json"
    _write_frames(invalid, ["a.pgm"])
    (invalid / "sceneio_sequence.json").write_text("{", encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="manifest"):
        sceneio.read(invalid)

    duplicate = tmp_path / "duplicate_json"
    _write_frames(duplicate, ["a.pgm"])
    (duplicate / "sceneio_sequence.json").write_text(
        '{"sceneio_image_sequence":1,"frames":[{"file":"a.pgm","file":"a.pgm"}]}',
        encoding="utf-8",
    )
    with pytest.raises(sceneio.FormatError, match="duplicate manifest key"):
        sceneio.read(duplicate)

    oversized = tmp_path / "oversized"
    _write_frames(oversized, ["a.pgm"])
    (oversized / "sceneio_sequence.json").write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(sceneio.FormatError, match="1 MiB"):
        sceneio.read(oversized)

    mixed = tmp_path / "mixed"
    _write_frames(mixed, ["a.pgm"], shape=(3, 4))
    (mixed / "b.pgm").write_bytes(_pgm(np.zeros((4, 4), np.uint8)))
    with pytest.raises(sceneio.FormatError, match="heterogeneous"):
        sceneio.read(mixed, format="image_sequence")


def test_partial_bounds_and_unsupported_directory_detection(tmp_path):
    directory = tmp_path / "frames"
    _write_frames(directory, ["a.pgm", "b.pgm"])
    with pytest.raises(sceneio.FormatError, match="no directory format"):
        sceneio.detect(directory)
    for bounds in ((0, 0), (-1, 1), (1, 3), (2, 1)):
        with pytest.raises((ValueError, sceneio.FormatError)):
            sceneio.read_partial(
                directory,
                frames=bounds,
                format="image_sequence",
            )


def test_writer_guards_storage_empty_and_referenced_metadata(tmp_path):
    output = tmp_path / "output"
    empty = np.empty(0, np.int64)
    with pytest.raises(sceneio.FormatError, match="at least one"):
        sceneio.write(
            _core.image_sequence_paths(
                [],
                [],
                empty,
                empty,
                0,
                0,
                1,
                "uint8",
                "gray",
                "none",
            ),
            output,
            format="image_sequence",
        )

    y = np.zeros((1, 2, 2), np.uint8)
    with pytest.raises(sceneio.FormatError, match="encoded paths"):
        sceneio.write(
            _core.image_sequence_yuv(
                y,
                None,
                None,
                empty,
                empty,
                "mono",
                "none",
                "unknown",
                "unknown",
                "progressive",
                25,
                1,
                1,
                1,
            ),
            output,
            format="image_sequence",
        )

    source = tmp_path / "source"
    _write_frames(source, ["a.pgm"])
    wrong_shape = _path_record(
        [source / "a.pgm"],
        ["a.pgm"],
        height=9,
        width=9,
    )
    with pytest.raises(sceneio.FormatError, match="metadata disagrees"):
        sceneio.write(wrong_shape, output, format="image_sequence")


def test_failed_staging_preserves_existing_destination(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _write_frames(source, ["a.pgm", "b.pgm"])
    sequence = _path_record(
        [source / "a.pgm", source / "b.pgm"],
        ["a.pgm", "b.pgm"],
    )
    destination = tmp_path / "destination"
    destination.mkdir()
    sentinel = destination / "existing.txt"
    sentinel.write_text("keep", encoding="utf-8")

    original = adapter._copy_file
    calls = 0

    def fail_second(source_path, destination_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected copy failure")
        original(source_path, destination_path)

    monkeypatch.setattr(adapter, "_copy_file", fail_second)
    with pytest.raises(sceneio.FormatError, match="injected copy failure"):
        sceneio.write(sequence, destination, format="image_sequence")
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert sorted(item.name for item in destination.iterdir()) == ["existing.txt"]


@pytest.mark.parametrize(
    ("format_id", "extension", "dtype", "channels"),
    [
        ("netpbm", ".ppm", "uint8", 3),
        ("netpbm", ".pgm", "uint8", 1),
        ("netpbm", ".pnm", "uint8", 3),
        ("png", ".png", "uint8", 3),
        ("jpeg", ".jpg", "uint8", 3),
        ("jpeg", ".jpeg", "uint8", 3),
        ("bmp", ".bmp", "uint8", 3),
        ("tga", ".tga", "uint8", 3),
        ("hdr", ".hdr", "float32", 3),
        ("exr", ".exr", "float32", 3),
        ("webp", ".webp", "uint8", 3),
        ("avif", ".avif", "uint8", 3),
    ],
)
def test_every_canonical_image_extension_is_a_folder_frame(
    tmp_path, format_id, extension, dtype, channels
):
    if not sceneio.capabilities(format_id).available:
        pytest.skip(f"{format_id} provider is unavailable")
    folder = tmp_path / f"frames-{format_id}-{extension[1:]}"
    folder.mkdir()
    if dtype == "float32":
        pixels = np.linspace(0.0, 1.0, 36, dtype=np.float32).reshape(3, 4, 3)
        image = sceneio.image(pixels, color_space="linear")
    elif channels == 1:
        image = sceneio.image(np.arange(12, dtype=np.uint8).reshape(3, 4))
    else:
        image = sceneio.image(
            np.arange(36, dtype=np.uint8).reshape(3, 4, 3),
            color_space="srgb",
        )
    sceneio.write(image, folder / f"frame001{extension}", format=format_id)

    sequence = sceneio.read_image_folder(folder)
    assert sequence.storage_mode == "encoded_paths"
    assert sequence.num_frames == 1
    assert (sequence.height, sequence.width, sequence.channels) == (3, 4, channels)
    assert sequence.frame_dtype == dtype


@pytest.mark.parametrize(
    ("format_id", "extension"),
    [
        ("apng", ".png"),
        ("animated_webp", ".webp"),
        ("animated_avif", ".avif"),
    ],
)
def test_shared_extension_animations_are_not_folder_frames(tmp_path, format_id, extension):
    if not sceneio.capabilities(format_id).available:
        pytest.skip(f"{format_id} provider is unavailable")
    frames = np.zeros((2, 3, 4, 4), np.uint8)
    frames[0, ...] = (255, 0, 0, 255)
    frames[1, ...] = (0, 255, 0, 255)
    sequence = _core.image_sequence_packed(
        frames,
        np.array([0, 40_000_000], np.int64),
        np.array([40_000_000, 40_000_000], np.int64),
        "srgb",
        "straight",
    )
    folder = tmp_path / format_id
    folder.mkdir()
    sceneio.write(sequence, folder / f"frame{extension}", format=format_id)

    with pytest.raises(sceneio.FormatError, match="not Image"):
        sceneio.read_image_folder(folder)


def test_mixed_static_formats_share_one_contract(tmp_path):
    folder = tmp_path / "mixed-static"
    folder.mkdir()
    image = sceneio.image(
        np.arange(36, dtype=np.uint8).reshape(3, 4, 3),
        color_space="srgb",
    )
    sceneio.write(image, folder / "frame1.png")
    sceneio.write(image, folder / "frame2.bmp")

    sequence = sceneio.read_image_folder(folder)
    assert sequence.frame_names == ["frame1.png", "frame2.bmp"]
    assert sceneio.inspect(folder, format="image_sequence").metadata["frame_formats"] == (
        "png",
        "bmp",
    )


def test_projection_manifest_and_packed_folder_encoding(tmp_path):
    pixels = np.zeros((2, 4, 8, 3), np.uint8)
    sequence = _core.image_sequence_packed(
        pixels,
        np.array([0, 50], np.int64),
        np.array([50, 50], np.int64),
        "srgb",
        "none",
        projection="equirectangular",
    )

    png_folder = tmp_path / "png-pano"
    sceneio.write_image_folder(sequence, png_folder, frame_format="png")
    decoded_png = sceneio.read(png_folder)
    assert decoded_png.projection == "equirectangular"
    assert decoded_png.is_full_sphere
    assert sceneio.read(png_folder / "frame000000.png").projection == "unknown"
    manifest = json.loads((png_folder / "sceneio_sequence.json").read_text(encoding="utf-8"))
    assert manifest["sceneio_image_sequence"] == 2
    assert manifest["frame_contract"]["projection"] == "equirectangular"

    jpeg_folder = tmp_path / "jpeg-pano"
    sceneio.write_image_folder(sequence, jpeg_folder, frame_format="jpeg")
    assert sceneio.read(jpeg_folder / "frame000000.jpg").projection == "equirectangular"
    assert sceneio.read(jpeg_folder).projection == "equirectangular"

    with pytest.raises(sceneio.FormatError, match="one canonical Image"):
        sceneio.write_image_folder(sequence, tmp_path / "bad", frame_format="tiff")


def test_gpano_folder_inference_requires_homogeneous_embedded_claims(tmp_path):
    folder = tmp_path / "gpano"
    folder.mkdir()
    pixels = np.zeros((4, 8, 3), np.uint8)
    pano = sceneio.image(pixels, color_space="srgb", projection="equirectangular")
    sceneio.write(pano, folder / "a.jpg")
    sceneio.write(pano, folder / "b.jpg")
    sequence = sceneio.read_image_folder(folder)
    assert sequence.projection == "equirectangular"
    assert sceneio.equirectangular_camera(sequence).model_id == 17
    assert sceneio.read_image_folder(folder, projection="equirectangular").is_full_sphere
    with pytest.raises(sceneio.FormatError, match="conflicts with the stored"):
        sceneio.read_image_folder(folder, projection="unknown")
    with pytest.raises(sceneio.FormatError, match="geometry conflicts"):
        sceneio.read_image_folder(
            folder,
            projection="equirectangular",
            canvas_width=9,
        )

    sceneio.write(sceneio.image(pixels, color_space="srgb"), folder / "c.jpg")
    with pytest.raises(sceneio.FormatError, match="heterogeneous frame contracts"):
        sceneio.read_image_folder(folder)


def test_typed_read_declares_metadata_free_panorama(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    sceneio.write(
        sceneio.image(np.zeros((4, 8, 3), np.uint8), color_space="srgb"),
        folder / "frame.png",
    )
    sequence = sceneio.read_image_folder(folder, projection="equirectangular")
    assert sequence.projection == "equirectangular"
    assert sequence.is_full_sphere
    np.testing.assert_allclose(
        sceneio.equirectangular_pixels_to_rays(sequence, [[4.0, 2.0]]),
        [[0.0, 0.0, 1.0]],
        atol=1e-15,
    )


def test_live_registered_image_codec_becomes_a_folder_frame(tmp_path):
    format_id = "__image_folder_probe__"
    extension = ".sceneioframe"
    codec = sceneio.Codec(
        format_id,
        (extension,),
        lambda _path: sceneio.image(np.zeros((2, 3), np.uint8)),
        None,
        record=sceneio.Image,
        payload_kind="image",
        inspect=lambda path: sceneio.Inspection(
            format_id,
            "image",
            Path(path).stat().st_size,
            shape=(2, 3),
            dtype="uint8",
            channels=1,
        ),
    )
    sceneio.io.register(codec)
    try:
        folder = tmp_path / "plugin"
        folder.mkdir()
        (folder / f"frame{extension}").write_bytes(b"probe")
        sequence = sceneio.read_image_folder(folder)
        assert sequence.frame_names == [f"frame{extension}"]
        assert sequence.color_space == "gray"
    finally:
        registry.REGISTRY.pop(format_id, None)


def test_tiff_and_animated_only_extensions_are_outside_frame_catalog():
    extensions = registry._IMAGE_FRAME_ACCESS.image_extensions()
    assert {".tif", ".tiff", ".apng", ".avifs"}.isdisjoint(extensions)


def test_large_encoded_frame_copy_has_bounded_python_memory(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    frame = source / "large.pgm"
    header = b"P5\n4096 4096\n255\n"
    with frame.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + 4096 * 4096)
    sequence = _path_record(
        [frame],
        ["large.pgm"],
        height=4096,
        width=4096,
    )

    gc.collect()
    tracemalloc.start()
    try:
        sceneio.write(
            sequence,
            tmp_path / "output",
            format="image_sequence",
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    assert (tmp_path / "output" / "large.pgm").stat().st_size == frame.stat().st_size
