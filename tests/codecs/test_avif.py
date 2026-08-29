"""AVIF still/sequence parity against Pillow/libavif and BMFF structure."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import io
import struct
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PillowImage
from PIL import features

import sceneio
from sceneio import _core
from sceneio.io import _avif as avif_adapter
from sceneio.io._registry.detection import _avif_brand

pytestmark = pytest.mark.skipif(
    not features.check_module("avif"), reason="Pillow AVIF provider unavailable"
)


def _rgba() -> np.ndarray:
    yy, xx = np.mgrid[:11, :13]
    return np.stack(
        (
            (xx * 13 + yy * 3) % 256,
            (xx * 5 + yy * 17) % 256,
            (xx * 7 + yy * 11) % 256,
            64 + (xx * 9 + yy * 5) % 192,
        ),
        axis=-1,
    ).astype(np.uint8)


def _sequence():
    first = _rgba()
    frames = np.stack((first, np.roll(first, 2, axis=1), np.flip(first, axis=0)))
    durations = np.array([40, 70, 30], np.int64) * 1_000_000
    timestamps = np.array([0, 40, 110], np.int64) * 1_000_000
    return _core.image_sequence_packed(
        frames, timestamps, durations, "srgb", "straight"
    )


def _pillow_frames(path):
    with PillowImage.open(path) as image:
        frames = []
        durations = []
        timestamps = []
        for index in range(image.n_frames):
            image.seek(index)
            frames.append(np.asarray(image.convert("RGBA")).copy())
            durations.append(int(image.info["duration"]))
            timestamps.append(int(image.info["timestamp"]))
    return np.stack(frames), timestamps, durations


def test_still_cross_read_write_and_public_dispatch(tmp_path):
    source = _rgba()
    record = _core.image(source, color_space="srgb", alpha_mode="straight")
    path = tmp_path / "frame.avif"
    avif_adapter.write_avif(record, path, quality=100)

    assert _avif_brand(path) == "avif"
    assert sceneio.detect(path) == "avif"
    decoded = sceneio.read(path)
    oracle = np.asarray(PillowImage.open(path).convert("RGBA"))
    np.testing.assert_array_equal(decoded.pixels, oracle)
    assert np.abs(oracle.astype(np.int16) - source.astype(np.int16)).max() <= 3
    assert decoded.color_space == "unknown"
    assert decoded.alpha_mode == "straight"

    inspection = sceneio.inspect(path)
    assert inspection.format == "avif"
    assert inspection.shape == source.shape
    assert inspection.dtype == "uint8"
    assert inspection.metadata["provider"] == "Pillow/libavif"


def test_pillow_still_is_sceneio_readable(tmp_path):
    source = _rgba()[..., :3]
    path = tmp_path / "oracle.avif"
    PillowImage.fromarray(source, "RGB").save(
        path,
        "AVIF",
        quality=100,
        subsampling="4:4:4",
        range="full",
    )
    expected = np.asarray(PillowImage.open(path).convert("RGB"))
    np.testing.assert_array_equal(sceneio.read(path).pixels, expected)


def test_animated_cross_read_write_timing_and_partial(tmp_path):
    source = _sequence()
    path = tmp_path / "clip.avif"
    avif_adapter.write_animated_avif(source, path, quality=100)

    assert _avif_brand(path) == "avis"
    assert sceneio.detect(path) == "animated_avif"
    decoded = sceneio.read(path)
    oracle_pixels, oracle_timestamps, oracle_durations = _pillow_frames(path)
    np.testing.assert_array_equal(decoded.pixels, oracle_pixels)
    assert decoded.timestamps_ns.tolist() == [0, 40_000_000, 110_000_000]
    assert decoded.durations_ns.tolist() == [40_000_000, 70_000_000, 30_000_000]
    assert oracle_timestamps == [0, 40, 110]
    assert oracle_durations == [40, 70, 30]

    selected = sceneio.read_partial(path, frames=(1, 3))
    np.testing.assert_array_equal(selected.pixels, decoded.pixels[1:3])
    np.testing.assert_array_equal(
        selected.timestamps_ns, decoded.timestamps_ns[1:3]
    )
    np.testing.assert_array_equal(selected.durations_ns, decoded.durations_ns[1:3])

    inspection = sceneio.inspect(path)
    assert inspection.shape == (3, 11, 13, 4)
    assert inspection.count == 3


def test_avifs_extension_and_extensionless_detection(tmp_path):
    source = _sequence()
    avifs = tmp_path / "clip.avifs"
    avif_adapter.write_animated_avif(source, avifs)
    assert sceneio.detect(avifs) == "animated_avif"

    extensionless = tmp_path / "clip"
    extensionless.write_bytes(avifs.read_bytes())
    assert sceneio.detect(extensionless) == "animated_avif"

    prefixed = tmp_path / "prefixed"
    prefixed.write_bytes(struct.pack(">I4s", 8, b"free") + avifs.read_bytes())
    assert sceneio.detect(prefixed) == "animated_avif"


def test_mmap_input_does_not_allocate_a_whole_file_bytes(tmp_path):
    path = tmp_path / "padded.avif"
    avif_adapter.write_avif(
        _core.image(np.zeros((3, 4, 3), np.uint8), color_space="srgb"),
        path,
        quality=100,
    )
    padding_size = 12 * 1024 * 1024
    with path.open("ab") as stream:
        stream.write(struct.pack(">I4s", padding_size + 8, b"free"))
        stream.write(b"\0" * padding_size)

    tracemalloc.start()
    decoded = avif_adapter.read_avif(path)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert decoded.pixels.shape == (3, 4, 3)
    assert peak < path.stat().st_size // 4


def test_decoded_pixels_do_not_depend_on_open_file(tmp_path):
    path = tmp_path / "owned.avif"
    avif_adapter.write_avif(
        _core.image(_rgba(), color_space="srgb", alpha_mode="straight"),
        path,
        quality=100,
    )
    decoded = avif_adapter.read_avif(path)
    expected = decoded.pixels.copy()
    path.unlink()
    np.testing.assert_array_equal(decoded.pixels, expected)


def test_inspection_does_not_request_a_decoded_frame(tmp_path, monkeypatch):
    seen_threads = []

    class Decoder:
        def __init__(self, _data, _codec, threads):
            seen_threads.append(threads)

        def get_info(self):
            return ((7, 5), 1, "RGB", None, None, 1, None)

        def get_frame(self, _index):
            raise AssertionError("inspection decoded pixels")

    class Provider:
        AvifDecoder = Decoder

    path = tmp_path / "header.avif"
    path.write_bytes(b"not-empty")
    monkeypatch.setattr(
        avif_adapter,
        "_require_provider",
        lambda: (PillowImage, Provider),
    )
    monkeypatch.setattr(avif_adapter, "_validate_container_profile", lambda _data: None)
    assert avif_adapter.inspect_avif(path).shape == (5, 7, 3)
    assert seen_threads == [avif_adapter._default_max_threads()]


def test_provider_versions_and_attributions_are_pinned():
    pillow_version = tuple(
        int(part)
        for part in importlib.metadata.version("Pillow").split(".")[:2]
    )
    assert pillow_version == (12, 3)
    from PIL import _avif

    libavif_version = tuple(
        int(part) for part in _avif.libavif_version.split(".")[:2]
    )
    assert libavif_version >= (1, 4)
    versions = _avif.codec_versions()
    assert "dav1d [dec]:" in versions
    assert "aom [enc]:" in versions

    licenses = Path(__file__).resolve().parents[2] / "LICENSES"
    for name in (
        "pillow.txt",
        "libavif.txt",
        "libaom.txt",
        "libaom-patents.txt",
        "dav1d.txt",
    ):
        assert (licenses / name).stat().st_size >= 250


def test_official_libavif_12_bit_fixture_is_refused_before_projection(tmp_path):
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "avif_colors_animated_12bpc.b64"
    )
    payload = base64.b64decode(fixture.read_text(encoding="ascii"))
    assert hashlib.sha256(payload).hexdigest() == (
        "3bf9f91da471749e7df639ba7945d4d94c1c3e3968c26f3619fbbcfc92790576"
    )
    path = tmp_path / "colors-animated-12bpc-keyframes-0-2-3.avif"
    path.write_bytes(payload)
    assert _avif_brand(path) == "avis"
    with pytest.raises(ValueError, match="only 8-bit"):
        avif_adapter.read_animated_avif(path)


def test_profile_guards_and_malformed_inputs(tmp_path):
    destination = tmp_path / "kept.avif"
    destination.write_bytes(b"keep")
    invalid = _core.image(_rgba().astype(np.float32), color_space="srgb", alpha_mode="straight")
    with pytest.raises(ValueError, match="uint8"):
        avif_adapter.write_avif(invalid, destination)
    assert destination.read_bytes() == b"keep"

    looped = _core.image_sequence_packed(
        _sequence().pixels,
        _sequence().timestamps_ns,
        _sequence().durations_ns,
        "srgb",
        "straight",
        None,
        2,
    )
    with pytest.raises(ValueError, match="loop/background"):
        avif_adapter.write_animated_avif(looped, destination)

    source = PillowImage.fromarray(_rgba()[..., :3], "RGB")
    exif = PillowImage.Exif()
    exif[0x010E] = "not represented"
    exif_path = tmp_path / "exif.avif"
    source.save(exif_path, "AVIF", exif=exif)
    with pytest.raises(ValueError, match="EXIF"):
        avif_adapter.read_avif(exif_path)

    xmp_path = tmp_path / "xmp.avif"
    source.save(xmp_path, "AVIF", xmp=b"<x:xmpmeta>not represented</x:xmpmeta>")
    with pytest.raises(ValueError, match="XMP"):
        avif_adapter.read_avif(xmp_path)

    straight_path = tmp_path / "straight.avif"
    avif_adapter.write_avif(
        _core.image(_rgba(), color_space="srgb", alpha_mode="straight"),
        straight_path,
    )
    premultiplied = bytearray(straight_path.read_bytes())
    reference_offset = premultiplied.find(b"auxl")
    assert reference_offset >= 0
    premultiplied[reference_offset : reference_offset + 4] = b"prem"
    with pytest.raises(ValueError, match="prem structures"):
        avif_adapter._validate_container_profile(premultiplied)

    for index, payload in enumerate((b"", b"\0" * 12, b"\0\0\0\x20ftypavif")):
        path = tmp_path / f"bad-{index}.avif"
        path.write_bytes(payload)
        with pytest.raises((ValueError, OSError, RuntimeError)):
            avif_adapter.read_avif(path)


def test_spec_brand_parser_rejects_invalid_box_extents(tmp_path):
    cases = (
        b"\0\0\0\x08free\0\0\0\x18ftypavis\0\0\0\0avisavif",
        b"\0\0\0\x18ftypavif\0\0\0\0avifmif1",
        b"\0\0\0\x04ftyp",
        b"\0\0\x10\x00ftypavif",
    )
    expected = ("avis", "avif", None, None)
    for index, (payload, kind) in enumerate(zip(cases, expected, strict=True)):
        path = tmp_path / f"brand-{index}"
        path.write_bytes(payload)
        assert _avif_brand(path) == kind


def test_pillow_buffer_oracle_accepts_sceneio_output(tmp_path):
    path = tmp_path / "buffer.avif"
    avif_adapter.write_avif(
        _core.image(_rgba()[..., :3], color_space="srgb"),
        path,
        quality=100,
    )
    with PillowImage.open(io.BytesIO(path.read_bytes())) as oracle:
        oracle.load()
        assert oracle.format == "AVIF"
        assert oracle.size == (13, 11)
