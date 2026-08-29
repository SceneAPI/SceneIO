"""Qualification tests for bounded typed TIFF collections."""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest
import tifffile

import sceneio
import sceneio.data
import sceneio.io
from sceneio import _core
from sceneio.data import Mask, RasterCollection, RasterLevel, RasterSeries
from sceneio.io import _tiff


def _image_level(index: int, values: np.ndarray) -> RasterLevel:
    axes = "YX" if values.ndim == 2 else "YXC"
    return RasterLevel(
        index,
        axes,
        values.shape,
        values.dtype.name,
        "image",
        _core.image(values),
    )


def _mask_level(index: int, values: np.ndarray) -> RasterLevel:
    return RasterLevel(
        index,
        "YX",
        values.shape,
        "bool",
        "mask",
        Mask(values),
    )


def _stack_level(index: int, values: np.ndarray, axes: str = "ZYX") -> RasterLevel:
    return RasterLevel(
        index,
        axes,
        values.shape,
        values.dtype.name,
        "tensor",
        _core.tensor_dict({"pages": values}, attrs={"axes": axes}),
    )


def _oracle_multi_pyramid(
    path: Path,
    *,
    bigtiff: bool = False,
    byteorder: str = "<",
    tiled: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    full = np.arange(64 * 80, dtype=np.uint16).reshape(64, 80)
    reduced = full[::2, ::2].copy()
    rgb = np.arange(48 * 56 * 3, dtype=np.uint8).reshape(48, 56, 3)
    layout = {"tile": (16, 16)} if tiled else {"rowsperstrip": 7}
    with tifffile.TiffWriter(path, bigtiff=bigtiff, byteorder=byteorder) as writer:
        writer.write(
            full,
            photometric="minisblack",
            metadata=None,
            subifds=1,
            **layout,
        )
        writer.write(
            reduced,
            photometric="minisblack",
            metadata=None,
            subfiletype=1,
            **layout,
        )
        writer.write(rgb, photometric="rgb", metadata=None, **layout)
    return full, reduced, rgb


def _portable_collection() -> tuple[RasterCollection, tuple[np.ndarray, ...]]:
    full = np.arange(64 * 80, dtype=np.uint16).reshape(64, 80)
    reduced = full[::2, ::2].copy()
    rgb = np.arange(48 * 56 * 3, dtype=np.uint8).reshape(48, 56, 3)
    mask = np.ascontiguousarray(np.indices((33, 45)).sum(axis=0) % 3 == 0)
    value = RasterCollection(
        (
            RasterSeries(0, None, (_image_level(0, full), _image_level(1, reduced))),
            RasterSeries(1, None, (_image_level(0, rgb),)),
            RasterSeries(2, None, (_mask_level(0, mask),)),
        )
    )
    return value, (full, reduced, rgb, mask)


def test_tiff_collection_public_surface_is_additive_and_shared_records_are_neutral():
    assert sceneio.RasterCollection is sceneio.data.RasterCollection
    assert sceneio.RasterLevel is sceneio.data.RasterLevel
    assert sceneio.RasterSeries is sceneio.data.RasterSeries
    assert not hasattr(sceneio.io, "RasterCollection")
    assert sceneio.read_tiff_collection is sceneio.io.read_tiff_collection
    assert sceneio.inspect_tiff_collection is sceneio.io.inspect_tiff_collection
    assert sceneio.write_tiff_collection is sceneio.io.write_tiff_collection
    assert str(inspect.signature(sceneio.read_tiff_collection)) == (
        "(path, *, series_index: 'int | None' = None, "
        "level_index: 'int | None' = None, "
        "page_range: 'tuple[int, int] | None' = None, "
        "window: 'tuple[int, int, int, int] | None' = None) "
        "-> 'RasterCollection'"
    )


@pytest.mark.parametrize(
    ("bigtiff", "byteorder", "tiled"),
    [(False, "<", False), (False, ">", True), (True, "<", True), (True, ">", False)],
)
def test_typed_tiff_reads_independent_classic_bigtiff_endian_and_layout_oracle(
    tmp_path,
    bigtiff,
    byteorder,
    tiled,
):
    path = tmp_path / f"oracle-{bigtiff}-{byteorder == '>'}-{tiled}.tif"
    full, reduced, rgb = _oracle_multi_pyramid(
        path,
        bigtiff=bigtiff,
        byteorder=byteorder,
        tiled=tiled,
    )

    actual = sceneio.read_tiff_collection(path)

    assert actual.num_series == 2
    assert [series.num_levels for series in actual.series] == [2, 1]
    np.testing.assert_array_equal(actual.series_at(0).level_at(0).array, full)
    np.testing.assert_array_equal(actual.series_at(0).level_at(1).array, reduced)
    np.testing.assert_array_equal(actual.series_at(1).level_at(0).array, rgb)
    assert all(level.array.dtype.isnative for series in actual.series for level in series.levels)
    info = sceneio.inspect_tiff_collection(path)
    assert info.count == 2
    assert info.metadata["bigtiff"] is bigtiff
    assert info.metadata["byteorder"] == byteorder
    assert [len(series["levels"]) for series in info.metadata["series"]] == [2, 1]
    assert info.metadata["series"][0]["levels"][0]["layout"] == ("tiled" if tiled else "stripped")
    with pytest.raises(sceneio.FormatError, match="exactly one image series"):
        sceneio.read(path)


def test_tiff_collection_inspection_reads_metadata_without_sample_decode(tmp_path, monkeypatch):
    path = tmp_path / "metadata-only.tif"
    _oracle_multi_pyramid(path)

    def fail_decode(*_args, **_kwargs):
        raise AssertionError("sample decode was called")

    monkeypatch.setattr(tifffile.TiffPage, "asarray", fail_decode)
    monkeypatch.setattr(tifffile.TiffPageSeries, "asarray", fail_decode)

    info = sceneio.inspect_tiff_collection(path)

    assert [(array.name, array.shape) for array in info.arrays] == [
        ("series[0].level[0]", (64, 80)),
        ("series[0].level[1]", (32, 40)),
        ("series[1].level[0]", (48, 56, 3)),
    ]


def test_tiff_collection_series_level_and_yxc_window_selection_are_exact(tmp_path):
    path = tmp_path / "selectors.tif"
    full, reduced, rgb = _oracle_multi_pyramid(path)

    selected_series = sceneio.read_tiff_collection(path, series_index=1)
    assert tuple(series.index for series in selected_series.series) == (1,)
    np.testing.assert_array_equal(selected_series.series_at(1).level_at(0).array, rgb)

    selected_level = sceneio.read_tiff_collection(
        path,
        series_index=0,
        level_index=1,
    )
    assert tuple(level.index for level in selected_level.series_at(0).levels) == (1,)
    np.testing.assert_array_equal(selected_level.series_at(0).level_at(1).array, reduced)

    selected_window = sceneio.read_tiff_collection(
        path,
        series_index=1,
        level_index=0,
        window=(3, 31, 7, 42),
    )
    level = selected_window.series_at(1).level_at(0)
    assert level.shape == (28, 35, 3)
    np.testing.assert_array_equal(level.array, rgb[3:31, 7:42, :])
    np.testing.assert_array_equal(full, np.arange(full.size, dtype=full.dtype).reshape(full.shape))


@pytest.mark.parametrize("tiled", [False, True])
def test_tiff_collection_compound_page_window_selection_uses_chunk_store(
    tmp_path, monkeypatch, tiled
):
    path = tmp_path / f"stack-{tiled}.tif"
    values = np.arange(7 * 64 * 80, dtype=np.uint16).reshape(7, 64, 80)
    kwargs = {"tile": (16, 16)} if tiled else {"rowsperstrip": 5}
    tifffile.imwrite(
        path,
        values,
        photometric="minisblack",
        metadata={"axes": "ZYX"},
        **kwargs,
    )

    def fail_full_decode(*_args, **_kwargs):
        raise AssertionError("full-series decode was called")

    monkeypatch.setattr(tifffile.TiffPageSeries, "asarray", fail_full_decode)
    actual = sceneio.read_tiff_collection(
        path,
        series_index=0,
        level_index=0,
        page_range=(2, 6),
        window=(9, 47, 11, 69),
    )

    level = actual.series_at(0).level_at(0)
    assert level.shape == (4, 38, 58)
    np.testing.assert_array_equal(level.array, values[2:6, 9:47, 11:69])


@pytest.mark.parametrize(
    ("bigtiff", "byteorder", "layout"),
    [
        (False, "little", "strip"),
        (False, "big", "tile"),
        (True, "little", "tile"),
        (True, "big", "strip"),
    ],
)
def test_tiff_collection_writer_reopens_with_sceneio_and_provider_oracles(
    tmp_path,
    bigtiff,
    byteorder,
    layout,
):
    expected, arrays = _portable_collection()
    path = tmp_path / f"written-{bigtiff}-{byteorder}-{layout}.tiff"
    kwargs = {"tile": (16, 16)} if layout == "tile" else {"rowsperstrip": 7}

    sceneio.write_tiff_collection(
        expected,
        path,
        bigtiff=bigtiff,
        byteorder=byteorder,
        **kwargs,
    )

    with tifffile.TiffFile(path) as oracle:
        assert oracle.is_bigtiff is bigtiff
        assert oracle.byteorder == ("<" if byteorder == "little" else ">")
        assert len(oracle.series) == 3
        assert [len(series.levels) for series in oracle.series] == [2, 1, 1]
        observed = [
            oracle.series[0].levels[0].asarray(),
            oracle.series[0].levels[1].asarray(),
            oracle.series[1].levels[0].asarray(),
            oracle.series[2].levels[0].asarray(),
        ]
    for actual, wanted in zip(observed, arrays, strict=True):
        np.testing.assert_array_equal(actual, wanted)

    decoded = sceneio.read_tiff_collection(path)
    decoded_arrays = [
        decoded.series[0].levels[0].array,
        decoded.series[0].levels[1].array,
        decoded.series[1].levels[0].array,
        decoded.series[2].levels[0].array,
    ]
    for actual, wanted in zip(decoded_arrays, arrays, strict=True):
        np.testing.assert_array_equal(actual, wanted)


def test_tiff_collection_writer_is_byte_deterministic(tmp_path):
    value, _arrays = _portable_collection()
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"

    sceneio.write_tiff_collection(value, first, tile=(16, 16), byteorder="little")
    sceneio.write_tiff_collection(value, second, tile=(16, 16), byteorder="little")

    assert first.read_bytes() == second.read_bytes()


def test_tiff_collection_writer_supports_one_stack_and_refuses_nonportable_topology(
    tmp_path,
):
    values = np.arange(4 * 20 * 24, dtype=np.float32).reshape(4, 20, 24)
    stack = RasterCollection((RasterSeries(0, None, (_stack_level(0, values, "TYX"),)),))
    path = tmp_path / "stack.tif"
    sceneio.write_tiff_collection(stack, path)
    actual = sceneio.read_tiff_collection(path)
    np.testing.assert_array_equal(actual.series_at(0).level_at(0).array, values)
    assert actual.series_at(0).level_at(0).axes == "TYX"

    named = RasterCollection((RasterSeries(0, "named", (_image_level(0, values[0]),)),))
    with pytest.raises(sceneio.FormatError, match="does not support series names"):
        sceneio.write_tiff_collection(named, tmp_path / "named.tif")

    multiple_with_stack = RasterCollection(
        (
            RasterSeries(0, None, (_stack_level(0, values),)),
            RasterSeries(1, None, (_image_level(0, values[0]),)),
        )
    )
    with pytest.raises(sceneio.FormatError, match="multi-series stacks"):
        sceneio.write_tiff_collection(multiple_with_stack, tmp_path / "multi-stack.tif")


def test_tiff_collection_writer_is_transactional_on_provider_failure(tmp_path, monkeypatch):
    value, _arrays = _portable_collection()
    path = tmp_path / "preserve.tif"
    path.write_bytes(b"previous")

    def fail_reopen(*_args, **_kwargs):
        raise RuntimeError("injected reopen failure")

    monkeypatch.setattr(_tiff, "_assert_reopened_collection", fail_reopen)
    with pytest.raises(sceneio.FormatError, match="injected reopen failure"):
        sceneio.write_tiff_collection(value, path)

    assert path.read_bytes() == b"previous"
    assert not tuple(tmp_path.glob(".preserve.tif.*.tmp"))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"level_index": 0}, "requires series_index"),
        ({"series_index": 9}, "series_index out of range"),
        ({"series_index": 0, "level_index": 9}, "level_index out of range"),
        (
            {"series_index": 0, "level_index": 0, "page_range": (0, 1)},
            "only for rank-3 stacks",
        ),
        (
            {"series_index": 0, "level_index": 0, "window": (0, 99, 0, 1)},
            "in-range bounds",
        ),
    ],
)
def test_tiff_collection_selector_failures_are_deterministic(tmp_path, kwargs, message):
    path = tmp_path / "selectors-invalid.tif"
    _oracle_multi_pyramid(path)

    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_tiff_collection(path, **kwargs)


def test_tiff_collection_truncated_payload_failure_is_normalized(tmp_path):
    source = tmp_path / "source.tif"
    broken = tmp_path / "broken.tif"
    values = np.arange(32 * 40, dtype=np.uint16).reshape(32, 40)
    tifffile.imwrite(source, values, photometric="minisblack", metadata=None)
    broken.write_bytes(source.read_bytes()[:-128])

    with pytest.raises(sceneio.FormatError, match="reading TIFF collection"):
        sceneio.read_tiff_collection(broken)


def test_tiff_collection_singleton_is_exact_and_empty_dimensions_refuse(tmp_path):
    singleton = tmp_path / "singleton.tif"
    values = np.array([[17]], dtype=np.uint16)
    tifffile.imwrite(singleton, values, photometric="minisblack", metadata=None)
    actual = sceneio.read_tiff_collection(singleton)
    np.testing.assert_array_equal(actual.series_at(0).level_at(0).array, values)

    empty = tmp_path / "empty.tif"
    with pytest.warns(UserWarning, match="zero-size array"):
        tifffile.imwrite(
            empty,
            np.empty((0, 4), dtype=np.uint8),
            photometric="minisblack",
            metadata=None,
        )
    with pytest.raises(sceneio.FormatError, match="empty raster dimensions"):
        sceneio.inspect_tiff_collection(empty)
