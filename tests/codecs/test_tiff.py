from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pytest
import tifffile

import sceneio
from sceneio import _core
from sceneio.data import Mask


def _pixels(image) -> np.ndarray:
    return np.asarray(image.pixels)


def test_tiff_record_outlives_closed_and_removed_source(tmp_path):
    values = np.arange(7 * 9 * 3, dtype=np.uint16).reshape(7, 9, 3)
    path = tmp_path / "lifetime.tiff"
    sceneio.write(_core.image(values, color_space="srgb"), path)

    decoded = sceneio.read(path)
    path.unlink()
    gc.collect()

    np.testing.assert_array_equal(_pixels(decoded), values)


@pytest.mark.parametrize(
    ("shape", "dtype"),
    [
        ((7, 9), np.uint8),
        ((7, 9), np.uint16),
        ((7, 9), np.float32),
        ((7, 9, 3), np.uint8),
        ((7, 9, 3), np.uint16),
        ((7, 9, 4), np.uint8),
    ],
)
def test_sceneio_tiff_write_is_exact_for_independent_oracle(
    tmp_path, shape, dtype
):
    values = np.arange(np.prod(shape), dtype=np.float64).reshape(shape)
    if dtype == np.float32:
        values = (values / max(values.size - 1, 1)).astype(dtype)
    else:
        values = values.astype(dtype)
    image = _core.image(values)
    path = tmp_path / "sceneio.tiff"

    sceneio.write(image, path)

    oracle = tifffile.imread(path)
    np.testing.assert_array_equal(oracle, values)
    assert sceneio.detect(path) == "tiff"
    decoded = sceneio.read(path)
    assert isinstance(decoded, _core.Image)
    np.testing.assert_array_equal(_pixels(decoded), values)
    assert decoded.color_space == image.color_space
    assert decoded.alpha_mode == image.alpha_mode


@pytest.mark.parametrize("byteorder", ["<", ">"])
def test_sceneio_reads_oracle_tiff_endianness_exactly(tmp_path, byteorder):
    path = tmp_path / f"oracle-{byteorder == '>'}.tif"
    values = np.array(
        [[0, 1, 255, 256], [4096, 32768, 60000, 65535]],
        dtype=np.dtype(f"{byteorder}u2"),
    )
    tifffile.imwrite(
        path,
        values,
        byteorder=byteorder,
        photometric="minisblack",
        metadata=None,
    )

    decoded = sceneio.read(path)

    np.testing.assert_array_equal(_pixels(decoded), values)
    assert _pixels(decoded).dtype.isnative


def test_tiff_boolean_mask_roundtrip_and_oracle(tmp_path):
    path = tmp_path / "mask.tif"
    values = (np.indices((8, 11)).sum(axis=0) % 3) == 0

    sceneio.write(Mask(values), path)

    np.testing.assert_array_equal(tifffile.imread(path), values)
    decoded = sceneio.read(path)
    assert isinstance(decoded, Mask)
    np.testing.assert_array_equal(decoded.mask, values)
    info = sceneio.inspect(path)
    assert info.datatype == "mask"
    assert info.shape == values.shape
    assert info.dtype == "bool"


@pytest.mark.parametrize("axes", ["ZYX", "TYX"])
def test_tiff_grayscale_stack_roundtrip_and_oracle(tmp_path, axes):
    path = tmp_path / "stack.tiff"
    values = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)
    stack = _core.tensor_dict({"pages": values}, attrs={"axes": axes})

    sceneio.write(stack, path)

    np.testing.assert_array_equal(tifffile.imread(path), values)
    with tifffile.TiffFile(path) as oracle:
        assert oracle.series[0].axes == axes
    decoded = sceneio.read(path)
    assert isinstance(decoded, _core.TensorDict)
    np.testing.assert_array_equal(decoded["pages"], values)
    assert dict(decoded.attrs) == {"axes": axes}
    info = sceneio.inspect(path)
    assert info.datatype == "image_stack"
    assert info.shape == values.shape
    assert info.count == values.shape[0]
    assert info.arrays[0].name == "pages"


def test_tiff_bigtiff_profile_is_oracle_readable(tmp_path):
    path = tmp_path / "small-bigtiff.tif"
    values = np.arange(30, dtype=np.uint16).reshape(5, 6)

    sceneio.write_tiff(_core.image(values), path, bigtiff=True)

    with tifffile.TiffFile(path) as oracle:
        assert oracle.is_bigtiff
        np.testing.assert_array_equal(oracle.asarray(), values)
    assert path.read_bytes()[:4] in {b"II+\x00", b"MM\x00+"}
    assert sceneio.inspect(path).metadata["bigtiff"] is True


@pytest.mark.parametrize(
    ("alpha_mode", "expected_extra"),
    [("straight", 2), ("premultiplied", 1)],
)
def test_tiff_alpha_semantics_roundtrip(tmp_path, alpha_mode, expected_extra):
    path = tmp_path / f"{alpha_mode}.tif"
    values = np.arange(5 * 6 * 4, dtype=np.uint8).reshape(5, 6, 4)
    image = _core.image(values, alpha_mode=alpha_mode)

    sceneio.write(image, path)

    with tifffile.TiffFile(path) as oracle:
        assert tuple(int(item) for item in oracle.pages[0].extrasamples) == (
            expected_extra,
        )
    decoded = sceneio.read(path)
    assert decoded.alpha_mode == alpha_mode
    np.testing.assert_array_equal(_pixels(decoded), values)


def test_tiff_inspect_does_not_decode_pixels(tmp_path, monkeypatch):
    path = tmp_path / "metadata.tif"
    values = np.arange(12, dtype=np.uint8).reshape(3, 4)
    tifffile.imwrite(path, values, photometric="minisblack", metadata=None)

    def fail_decode(*_args, **_kwargs):
        raise AssertionError("pixel decode was called")

    monkeypatch.setattr(tifffile.TiffPageSeries, "asarray", fail_decode)
    info = sceneio.inspect(path)

    assert info.shape == values.shape
    assert info.dtype == "uint8"
    assert info.channels == 1


def test_tiff_rejects_multiple_series_without_decoding(tmp_path):
    path = tmp_path / "multi-series.tif"
    first = np.arange(4 * 5, dtype=np.uint8).reshape(4, 5)
    second = (np.arange(3 * 7, dtype=np.uint8) + 100).reshape(3, 7)
    with tifffile.TiffWriter(path) as writer:
        writer.write(
            first,
            photometric="minisblack",
            metadata=None,
        )
        writer.write(
            second,
            photometric="minisblack",
            metadata=None,
        )

    with tifffile.TiffFile(path) as oracle:
        assert len(oracle.series) == 2
        assert [tuple(series.shape) for series in oracle.series] == [
            (4, 5),
            (3, 7),
        ]
        np.testing.assert_array_equal(oracle.series[0].asarray(), first)
        np.testing.assert_array_equal(oracle.series[1].asarray(), second)
    with pytest.raises(sceneio.FormatError, match="exactly one image series"):
        sceneio.read(path)


def test_tifffile_provider_pyramid_surface_and_sceneio_boundary(tmp_path):
    path = tmp_path / "pyramid.tif"
    full = np.arange(8 * 10, dtype=np.uint8).reshape(8, 10)
    reduced = full[::2, ::2].copy()
    with tifffile.TiffWriter(path) as writer:
        writer.write(
            full,
            photometric="minisblack",
            metadata=None,
            subifds=1,
        )
        writer.write(
            reduced,
            photometric="minisblack",
            metadata=None,
            subfiletype=1,
        )

    with tifffile.TiffFile(path) as oracle:
        assert len(oracle.series) == 1
        assert len(oracle.series[0].levels) == 2
        np.testing.assert_array_equal(oracle.series[0].levels[0].asarray(), full)
        np.testing.assert_array_equal(
            oracle.series[0].levels[1].asarray(), reduced
        )
    with pytest.raises(sceneio.FormatError, match="pyramidal image series"):
        sceneio.read(path)


def test_tiff_rejects_ambiguous_channel_and_stack_layouts(tmp_path):
    path = tmp_path / "two-channel.tif"
    tifffile.imwrite(
        path,
        np.zeros((4, 5, 2), dtype=np.uint8),
        photometric="minisblack",
        metadata={"axes": "YXS"},
    )

    with pytest.raises(sceneio.FormatError, match="unsupported or ambiguous"):
        sceneio.read(path)

    bad_stack = _core.tensor_dict(
        {"pages": np.zeros((2, 3, 4), dtype=np.float32)},
        attrs={"axes": "YXS"},
    )
    with pytest.raises(sceneio.FormatError, match="supported 'axes'"):
        sceneio.write(bad_stack, tmp_path / "bad-stack.tif")


def test_tiff_rejects_nondefault_image_conventions(tmp_path):
    linear = _core.image(
        np.zeros((3, 4, 3), dtype=np.float32),
        color_space="linear",
    )
    limited = _core.image(
        np.zeros((3, 4), dtype=np.uint16),
        color_space="gray",
        maxval=1000,
    )

    with pytest.raises(sceneio.FormatError, match="requires srgb"):
        sceneio.write(linear, tmp_path / "linear.tif")
    with pytest.raises(sceneio.FormatError, match="full-range maxval"):
        sceneio.write(limited, tmp_path / "limited.tif")


def test_tiff_failed_provider_write_preserves_destination(
    tmp_path, monkeypatch
):
    path = tmp_path / "preserve.tif"
    path.write_bytes(b"previous")

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("injected provider failure")

    monkeypatch.setattr(tifffile, "imwrite", fail_write)
    with pytest.raises(sceneio.FormatError, match="injected provider failure"):
        sceneio.write(_core.image(np.zeros((2, 3), np.uint8)), path)

    assert path.read_bytes() == b"previous"
    assert not tuple(tmp_path.glob(".preserve.tif.*.tmp"))


def test_tiff_capabilities_and_license_contract():
    capabilities = sceneio.capabilities("tiff")
    assert capabilities.available
    assert capabilities.requires_features == ("tifffile",)
    assert capabilities.streams_read
    assert capabilities.streams_write
    assert "bigtiff" in capabilities.supported_features
    assert "pyramids" in capabilities.unsupported_features

    license_text = (
        Path(__file__).resolve().parents[2] / "LICENSES" / "tifffile.txt"
    ).read_text(encoding="utf-8")
    assert "BSD-3-Clause" in license_text
    assert "Christoph Gohlke" in license_text
