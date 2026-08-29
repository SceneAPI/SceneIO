"""Bounded computer-vision TIFF adapter backed by upstream ``tifffile``.

The provider handles classic TIFF and BigTIFF directly from file paths. The
legacy projection intentionally supports one unambiguous image/mask/stack;
the additive typed API preserves bounded CV series and homogeneous pyramids.
"""

from __future__ import annotations

import json
import operator
import os
import tempfile
from collections.abc import Mapping
from contextlib import nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.data import (
    InstanceMap,
    LabelTaxonomy,
    Mask,
    PanopticMap,
    RasterCollection,
    RasterLevel,
    RasterSeries,
    SemanticMap,
)
from sceneio.io._inspectors.model import ArrayInspection, Inspection

LABEL_MAP_SCHEMA = "sceneio.label_map/1"
_LABEL_PRIMARY_ROLES = {"semantic": "semantic_ids", "instance": "instance_ids"}
_LABEL_KINDS = frozenset({"semantic", "instance", "panoptic"})
_LABEL_PAGE_KEYS = frozenset({"schema", "kind", "role", "shape", "dtype"})
_LABEL_HEADER_COMMON = frozenset(
    {
        "schema",
        "kind",
        "roles",
        "shape",
        "dtypes",
        "taxonomy",
        "table_instance_ids",
        "table_semantic_ids",
    }
)
_MAX_LABEL_DESCRIPTION_BYTES = 1 << 20

_IMAGE_DTYPES = frozenset({"uint8", "uint16", "float32"})
_STACK_DTYPES = frozenset({"bool", "uint8", "uint16", "float32"})
_STACK_AXES = frozenset({"CYX", "IYX", "QYX", "TYX", "ZYX"})


def _require_tifffile():
    try:
        import tifffile
    except ModuleNotFoundError:
        raise RuntimeError(
            "TIFF support requires the optional dependency; install sceneio[tiff]"
        ) from None
    return tifffile


def _native_c_array(value: object, context: str) -> np.ndarray:
    array = np.asarray(value)
    if not array.dtype.isnative:
        array = array.byteswap().view(array.dtype.newbyteorder("="))
    if array.flags.c_contiguous:
        return array
    return np.ascontiguousarray(array)


def _metadata_page(page):
    """Return the tag-owning page for a TiffPage or lightweight TiffFrame."""

    return page if hasattr(page, "tags") else page.keyframe


def _classify_raster(
    axes: str,
    shape: tuple[int, ...],
    dtype: np.dtype,
) -> tuple[str, str, int]:
    if dtype.fields is not None or dtype.subdtype is not None:
        raise ValueError("TIFF: structured and subarray dtypes are unsupported")
    if any(dimension <= 0 for dimension in shape):
        raise ValueError("TIFF: empty raster dimensions are unsupported")
    if axes == "YX" and len(shape) == 2:
        if dtype.name not in _STACK_DTYPES:
            raise ValueError(f"TIFF image: unsupported dtype {dtype.name!r}")
        return ("mask" if dtype.name == "bool" else "image"), "YX", 1
    if axes in {"YXS", "YXC"} and len(shape) == 3 and shape[-1] in {3, 4}:
        if dtype.name not in _IMAGE_DTYPES:
            raise ValueError(f"TIFF image: unsupported dtype {dtype.name!r}")
        return "image", "YXC", shape[-1]
    if axes in _STACK_AXES and len(shape) == 3:
        if dtype.name not in _STACK_DTYPES:
            raise ValueError(f"TIFF stack: unsupported dtype {dtype.name!r}")
        return "stack", axes, 1
    raise ValueError(f"TIFF: unsupported or ambiguous axes {axes!r} and shape {shape!r}")


def _validate_file_layout(tiff):
    if len(tiff.series) != 1:
        raise ValueError("TIFF: exactly one image series is supported")
    series = tiff.series[0]
    if len(series.levels) != 1:
        raise ValueError("TIFF: pyramidal image series are unsupported")
    axes = str(series.axes)
    shape = tuple(int(value) for value in series.shape)
    dtype = np.dtype(series.dtype)
    if not series.pages:
        raise ValueError("TIFF: image series has no pages")
    for page in series.pages:
        page = _metadata_page(page)
        orientation = page.tags.get("Orientation")
        if orientation is not None and int(orientation.value) != 1:
            raise ValueError("TIFF: only top-left orientation is supported")
        planar = page.planarconfig
        if planar is not None and int(planar) != 1:
            raise ValueError("TIFF: planar-separate samples are unsupported")
    kind, _normalized_axes, channels = _classify_raster(axes, shape, dtype)
    return series, axes, shape, dtype, kind, channels


def _image_metadata(series, channels: int) -> tuple[str, str]:
    return _image_metadata_from_page(_metadata_page(series.pages[0]), channels)


def _image_metadata_from_page(page, channels: int) -> tuple[str, str]:
    photometric = int(page.photometric)
    if channels == 1:
        if photometric not in {0, 1}:
            raise ValueError("TIFF image: grayscale samples require min-is-black/white")
        return "gray", "none"
    if photometric != 2:
        raise ValueError("TIFF image: RGB samples require RGB photometric data")
    if channels == 3:
        return "srgb", "none"
    extras = tuple(int(value) for value in page.extrasamples)
    if extras == (1,):
        return "srgb", "premultiplied"
    if extras == (2,):
        return "srgb", "straight"
    raise ValueError("TIFF image: RGBA samples require associated or unassociated alpha")


def read_tiff(path: str | Path):
    """Read one bounded CV TIFF series."""

    tifffile = _require_tifffile()
    with tifffile.TiffFile(path) as tiff:
        series, axes, _shape, _dtype, kind, channels = _validate_file_layout(tiff)
        if kind == "image":
            color_space, alpha_mode = _image_metadata(series, channels)
        decoded = _native_c_array(series.asarray(), "TIFF")
    if kind == "mask":
        return Mask(decoded)
    if kind == "stack":
        return _core.tensor_dict({"pages": decoded}, attrs={"axes": axes})
    return _core.image(
        decoded,
        color_space=color_space,
        alpha_mode=alpha_mode,
    )


def _image_write_args(image) -> tuple[np.ndarray, dict[str, object]]:
    pixels = _native_c_array(image.pixels, "TIFF image")
    if pixels.dtype.name not in _IMAGE_DTYPES:
        raise ValueError(f"TIFF image: unsupported dtype {pixels.dtype.name!r}")
    channels = 1 if pixels.ndim == 2 else pixels.shape[-1]
    expected_maxval = {
        "uint8": 255,
        "uint16": 65535,
        "float32": 0,
    }[pixels.dtype.name]
    if image.maxval != expected_maxval:
        raise ValueError("TIFF image: only the dtype's full-range maxval is representable")
    if channels == 1:
        if image.color_space != "gray" or image.alpha_mode != "none":
            raise ValueError("TIFF image: grayscale requires gray color and no alpha")
        return pixels, {"photometric": "minisblack"}
    if image.color_space != "srgb":
        raise ValueError("TIFF image: RGB/RGBA requires srgb color")
    if channels == 3:
        if image.alpha_mode != "none":
            raise ValueError("TIFF image: RGB requires no alpha")
        return pixels, {"photometric": "rgb"}
    if channels == 4 and image.alpha_mode in {"straight", "premultiplied"}:
        alpha = "unassalpha" if image.alpha_mode == "straight" else "assocalpha"
        return pixels, {"photometric": "rgb", "extrasamples": (alpha,)}
    raise ValueError("TIFF image: RGBA requires straight or premultiplied alpha")


def _stack_write_args(tensors) -> tuple[np.ndarray, dict[str, object]]:
    if tuple(tensors.keys()) != ("pages",):
        raise ValueError("TIFF stack: TensorDict must contain only 'pages'")
    attrs = dict(tensors.attrs)
    if set(attrs) != {"axes"} or attrs["axes"] not in _STACK_AXES:
        raise ValueError("TIFF stack: attrs must contain one supported 'axes' value")
    array = _native_c_array(tensors["pages"], "TIFF stack")
    if array.ndim != 3 or array.dtype.name not in _STACK_DTYPES:
        raise ValueError("TIFF stack: pages must be a rank-3 bool/uint8/uint16/float32 array")
    return array, {
        "photometric": "minisblack",
        "metadata": {"axes": attrs["axes"]},
    }


def write_tiff(
    value,
    path: str | Path,
    *,
    bigtiff: bool | None = None,
) -> None:
    """Write one Image, Mask, or bounded grayscale TensorDict stack."""

    if isinstance(value, _core.Image):
        array, kwargs = _image_write_args(value)
    elif isinstance(value, Mask):
        array = _native_c_array(value.mask, "TIFF mask")
        kwargs = {"photometric": "minisblack"}
    elif isinstance(value, _core.TensorDict):
        array, kwargs = _stack_write_args(value)
    else:
        raise TypeError("TIFF: expected an Image, Mask, or TensorDict stack")

    tifffile = _require_tifffile()
    destination = Path(path)
    destination.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        tifffile.imwrite(
            temporary,
            array,
            bigtiff=bigtiff,
            software="SceneIO",
            **kwargs,
        )
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def inspect_tiff(path: str | Path) -> Inspection:
    """Inspect bounded TIFF metadata without decoding sample payloads."""

    tifffile = _require_tifffile()
    source = Path(path)
    with tifffile.TiffFile(source) as tiff:
        series, axes, shape, dtype, kind, channels = _validate_file_layout(tiff)
        if kind == "image":
            _image_metadata(series, channels)
        page_count = len(series.pages)
        bigtiff = bool(tiff.is_bigtiff)
    if kind == "stack":
        return Inspection(
            format="tiff",
            datatype="image_stack",
            byte_size=source.stat().st_size,
            shape=shape,
            dtype=dtype.name,
            count=shape[0],
            channels=1,
            arrays=(ArrayInspection("pages", shape, dtype.name),),
            metadata={
                "axes": axes,
                "bigtiff": bigtiff,
                "page_count": page_count,
            },
        )
    return Inspection(
        format="tiff",
        datatype="mask" if kind == "mask" else "image",
        byte_size=source.stat().st_size,
        shape=shape,
        dtype=dtype.name,
        channels=channels,
        metadata={
            "axes": axes,
            "bigtiff": bigtiff,
            "page_count": page_count,
        },
    )


@dataclass(frozen=True)
class _CollectionLevel:
    index: int
    source_axes: str
    axes: str
    shape: tuple[int, ...]
    dtype: str
    payload_kind: str
    channels: int
    page_count: int
    layout: str
    tile_shape: tuple[int, int] | None
    rows_per_strip: tuple[int, ...]
    compression: tuple[str, ...]
    photometric: str
    planar_config: str
    orientation: int
    color_space: str
    alpha_mode: str


@dataclass(frozen=True)
class _CollectionSeries:
    index: int
    name: str | None
    levels: tuple[_CollectionLevel, ...]


def _enum_label(value: object) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.lower()
    return str(int(value))


def _ordered_unique(values) -> tuple:
    return tuple(dict.fromkeys(values))


def _spatial_axis_indices(axes: str) -> tuple[int, int]:
    return (0, 1) if axes == "YXC" else (-2, -1)


def _spatial_shape(axes: str, shape: tuple[int, ...]) -> tuple[int, int]:
    row_axis, column_axis = _spatial_axis_indices(axes)
    return shape[row_axis], shape[column_axis]


def _non_spatial_shape(axes: str, shape: tuple[int, ...]) -> tuple[int, ...]:
    if axes == "YXC":
        return shape[2:]
    return shape[:-2]


def _describe_collection_level(level, index: int, *, is_ome: bool) -> _CollectionLevel:
    source_axes = str(level.axes)
    shape = tuple(int(value) for value in level.shape)
    dtype = np.dtype(level.dtype)
    if not level.pages:
        raise ValueError("TIFF collection: raster level has no pages")

    pages = tuple(_metadata_page(page) for page in level.pages)
    orientations = []
    planar_configs = []
    photometrics = []
    tiled = []
    tile_shapes = []
    rows_per_strip = []
    compressions = []
    extrasamples = []
    for page in pages:
        orientation_tag = page.tags.get("Orientation")
        orientations.append(1 if orientation_tag is None else int(orientation_tag.value))
        planar_configs.append(1 if page.planarconfig is None else int(page.planarconfig))
        photometrics.append(int(page.photometric))
        tiled.append(bool(page.is_tiled))
        if page.is_tiled:
            tile_shapes.append((int(page.tilelength), int(page.tilewidth)))
        else:
            rows_per_strip.append(int(page.rowsperstrip))
        compressions.append(_enum_label(page.compression))
        extrasamples.append(tuple(int(value) for value in page.extrasamples))

    if set(orientations) != {1}:
        raise ValueError("TIFF collection: only top-left orientation is supported")
    if set(planar_configs) != {1}:
        raise ValueError("TIFF collection: planar-separate samples are unsupported")
    if len(set(photometrics)) != 1 or len(set(extrasamples)) != 1:
        raise ValueError("TIFF collection: mixed photometric interpretations are unsupported")
    if is_ome:
        raise ValueError(
            "TIFF collection: OME-XML and OME axes "
            f"{source_axes!r} are outside the bounded CV profile"
        )

    kind, axes, channels = _classify_raster(source_axes, shape, dtype)
    first = pages[0]
    if kind == "image":
        color_space, alpha_mode = _image_metadata_from_page(first, channels)
    else:
        if photometrics[0] not in {0, 1}:
            raise ValueError("TIFF collection: masks and stacks require grayscale photometric data")
        color_space, alpha_mode = "not_applicable", "not_applicable"
    if all(tiled):
        layout = "tiled"
        unique_tiles = _ordered_unique(tile_shapes)
        tile_shape = unique_tiles[0] if len(unique_tiles) == 1 else None
    elif not any(tiled):
        layout = "stripped"
        tile_shape = None
    else:
        layout = "mixed"
        tile_shape = None
    return _CollectionLevel(
        index=index,
        source_axes=source_axes,
        axes=axes,
        shape=shape,
        dtype=dtype.name,
        payload_kind="tensor" if kind == "stack" else kind,
        channels=channels,
        page_count=len(pages),
        layout=layout,
        tile_shape=tile_shape,
        rows_per_strip=_ordered_unique(rows_per_strip),
        compression=_ordered_unique(compressions),
        photometric=_enum_label(first.photometric),
        planar_config="contiguous",
        orientation=1,
        color_space=color_space,
        alpha_mode=alpha_mode,
    )


def _validate_collection_series(series: _CollectionSeries) -> None:
    first = series.levels[0]
    previous = first
    for level in series.levels[1:]:
        if (
            level.axes != first.axes
            or level.dtype != first.dtype
            or level.payload_kind != first.payload_kind
            or level.channels != first.channels
            or level.color_space != first.color_space
            or level.alpha_mode != first.alpha_mode
            or _non_spatial_shape(level.axes, level.shape)
            != _non_spatial_shape(first.axes, first.shape)
        ):
            raise ValueError("TIFF collection: pyramid levels must have homogeneous semantics")
        if (
            _spatial_shape(level.axes, level.shape)[0]
            > _spatial_shape(previous.axes, previous.shape)[0]
            or _spatial_shape(level.axes, level.shape)[1]
            > _spatial_shape(previous.axes, previous.shape)[1]
            or _spatial_shape(level.axes, level.shape)
            == _spatial_shape(previous.axes, previous.shape)
        ):
            raise ValueError("TIFF collection: pyramid spatial dimensions must decrease")
        previous = level


def _describe_tiff_collection(tiff) -> tuple[_CollectionSeries, ...]:
    if not tiff.series:
        raise ValueError("TIFF collection: file has no image series")
    result = []
    for series_index, provider_series in enumerate(tiff.series):
        provider_levels = tuple(provider_series.levels)
        if not provider_levels:
            raise ValueError("TIFF collection: image series has no levels")
        name = str(provider_series.name or "") or None
        levels = tuple(
            _describe_collection_level(
                level,
                level_index,
                is_ome=bool(tiff.is_ome),
            )
            for level_index, level in enumerate(provider_levels)
        )
        series = _CollectionSeries(series_index, name, levels)
        _validate_collection_series(series)
        result.append(series)
    return tuple(result)


def _selector_index(value: object | None, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a non-negative integer or None")
    try:
        selected = operator.index(value)
    except TypeError:
        raise TypeError(f"{name} must be a non-negative integer or None") from None
    if selected < 0:
        raise ValueError(f"{name} must be non-negative")
    return int(selected)


def _bounded_range(
    value: object | None,
    *,
    name: str,
    limit: int,
    length: int,
) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != length:
        raise TypeError(f"{name} must be a length-{length} tuple or list")
    result = []
    for item in value:
        if isinstance(item, bool):
            raise TypeError(f"{name} values must be integers")
        try:
            result.append(int(operator.index(item)))
        except TypeError:
            raise TypeError(f"{name} values must be integers") from None
    pairs = zip(result[::2], result[1::2], strict=True)
    if any(start < 0 or start >= stop or stop > limit for start, stop in pairs):
        raise ValueError(f"{name} must contain non-empty half-open in-range bounds")
    return tuple(result)


def _selected_collection_infos(
    series: tuple[_CollectionSeries, ...],
    *,
    series_index: object | None,
    level_index: object | None,
    page_range: object | None,
    window: object | None,
) -> tuple[
    tuple[tuple[_CollectionSeries, tuple[_CollectionLevel, ...]], ...],
    tuple[int, int] | None,
    tuple[int, int, int, int] | None,
]:
    selected_series = _selector_index(series_index, "series_index")
    selected_level = _selector_index(level_index, "level_index")
    if selected_level is not None and selected_series is None:
        raise ValueError("level_index requires series_index")
    if (page_range is not None or window is not None) and selected_level is None:
        raise ValueError("page_range and window require series_index and level_index")
    if selected_series is not None and selected_series >= len(series):
        raise IndexError("TIFF collection series_index out of range")

    selected: list[tuple[_CollectionSeries, tuple[_CollectionLevel, ...]]] = []
    source_series = series if selected_series is None else (series[selected_series],)
    for series_info in source_series:
        if selected_level is None:
            levels = series_info.levels
        else:
            if selected_level >= len(series_info.levels):
                raise IndexError("TIFF collection level_index out of range")
            levels = (series_info.levels[selected_level],)
        selected.append((series_info, levels))

    page_bounds = None
    window_bounds = None
    if selected_level is not None:
        level = selected[0][1][0]
        if page_range is not None:
            if level.axes not in _STACK_AXES:
                raise ValueError("page_range is supported only for rank-3 stacks")
            page_bounds = _bounded_range(
                page_range,
                name="page_range",
                limit=level.shape[0],
                length=2,
            )
        if window is not None:
            spatial_shape = _spatial_shape(level.axes, level.shape)
            window_bounds = _bounded_range(
                window,
                name="window",
                limit=max(spatial_shape),
                length=4,
            )
            assert window_bounds is not None
            _row_start, row_stop, _column_start, column_stop = window_bounds
            if row_stop > spatial_shape[0] or column_stop > spatial_shape[1]:
                raise ValueError("window must contain non-empty half-open in-range bounds")
    return tuple(selected), page_bounds, window_bounds


def _zarr_selected_array(
    provider_series,
    level_index: int,
    selection: tuple[slice, ...],
) -> np.ndarray:
    try:
        import zarr
    except ModuleNotFoundError:
        raise RuntimeError(
            "TIFF collection page/window selection requires zarr; install sceneio[tiff]"
        ) from None
    store = provider_series.aszarr(level=level_index)
    try:
        array = zarr.open(store, mode="r")
        return np.asarray(array[selection])
    finally:
        store.close()


def _level_payload(info: _CollectionLevel, array: np.ndarray):
    array = _native_c_array(array, "TIFF collection")
    if info.payload_kind == "mask":
        return Mask(array)
    if info.payload_kind == "tensor":
        return _core.tensor_dict({"pages": array}, attrs={"axes": info.axes})
    return _core.image(
        array,
        color_space=info.color_space,
        alpha_mode=info.alpha_mode,
    )


def read_tiff_collection(
    path: str | Path,
    *,
    series_index: int | None = None,
    level_index: int | None = None,
    page_range: tuple[int, int] | None = None,
    window: tuple[int, int, int, int] | None = None,
) -> RasterCollection:
    """Read all or a bounded selection of TIFF series and pyramid levels."""

    tifffile = _require_tifffile()
    with tifffile.TiffFile(path) as tiff:
        infos = _describe_tiff_collection(tiff)
        selected, page_bounds, window_bounds = _selected_collection_infos(
            infos,
            series_index=series_index,
            level_index=level_index,
            page_range=page_range,
            window=window,
        )
        decoded_series = []
        for series_info, levels in selected:
            decoded_levels = []
            for level_info in levels:
                provider_level = tiff.series[series_info.index].levels[level_info.index]
                selected_shape = list(level_info.shape)
                if page_bounds is None and window_bounds is None:
                    array = provider_level.asarray()
                else:
                    selection = [slice(None)] * len(level_info.shape)
                    if page_bounds is not None:
                        selection[0] = slice(*page_bounds)
                        selected_shape[0] = page_bounds[1] - page_bounds[0]
                    if window_bounds is not None:
                        row_start, row_stop, column_start, column_stop = window_bounds
                        row_axis, column_axis = _spatial_axis_indices(level_info.axes)
                        selection[row_axis] = slice(row_start, row_stop)
                        selection[column_axis] = slice(column_start, column_stop)
                        selected_shape[row_axis] = row_stop - row_start
                        selected_shape[column_axis] = column_stop - column_start
                    provider_series = tiff.series[series_info.index]
                    array = _zarr_selected_array(
                        provider_series,
                        level_info.index,
                        tuple(selection),
                    )
                payload = _level_payload(level_info, array)
                decoded_levels.append(
                    RasterLevel(
                        level_info.index,
                        level_info.axes,
                        tuple(selected_shape),
                        level_info.dtype,
                        level_info.payload_kind,
                        payload,
                    )
                )
            decoded_series.append(
                RasterSeries(
                    series_info.index,
                    series_info.name,
                    tuple(decoded_levels),
                )
            )
    return RasterCollection(tuple(decoded_series))


def _inspection_level(info: _CollectionLevel) -> dict[str, object]:
    return {
        "index": info.index,
        "axes": info.axes,
        "source_axes": info.source_axes,
        "shape": info.shape,
        "dtype": info.dtype,
        "payload_kind": info.payload_kind,
        "page_count": info.page_count,
        "layout": info.layout,
        "tile_shape": info.tile_shape,
        "rows_per_strip": info.rows_per_strip,
        "compression": info.compression,
        "photometric": info.photometric,
        "planar_config": info.planar_config,
        "orientation": info.orientation,
    }


def inspect_tiff_collection(path: str | Path) -> Inspection:
    """Inspect every supported series and level without decoding samples."""

    tifffile = _require_tifffile()
    source = Path(path)
    with tifffile.TiffFile(source) as tiff:
        infos = _describe_tiff_collection(tiff)
        bigtiff = bool(tiff.is_bigtiff)
        byteorder = str(tiff.byteorder)
    arrays = tuple(
        ArrayInspection(
            f"series[{series.index}].level[{level.index}]",
            level.shape,
            level.dtype,
        )
        for series in infos
        for level in series.levels
    )
    return Inspection(
        format="tiff",
        datatype="raster_collection",
        byte_size=source.stat().st_size,
        count=len(infos),
        arrays=arrays,
        metadata={
            "schema": "sceneio.raster_collection/1",
            "bigtiff": bigtiff,
            "byteorder": byteorder,
            "series": tuple(
                {
                    "index": series.index,
                    "name": series.name,
                    "levels": tuple(_inspection_level(level) for level in series.levels),
                }
                for series in infos
            ),
        },
    )


def _collection_write_options(
    value: RasterCollection,
    *,
    bigtiff: bool | None,
    byteorder: str | None,
    tile: tuple[int, int] | None,
    rowsperstrip: int | None,
) -> tuple[bool, str | None, tuple[int, int] | None, int | None]:
    if not isinstance(value, RasterCollection):
        raise TypeError("TIFF collection: expected RasterCollection")
    if bigtiff is not None and not isinstance(bigtiff, bool):
        raise TypeError("bigtiff must be bool or None")
    byteorders = {None: None, "native": None, "little": "<", "big": ">", "<": "<", ">": ">"}
    if byteorder not in byteorders:
        raise ValueError("byteorder must be native, little, big, '<', '>', or None")
    if tile is not None:
        if (
            not isinstance(tile, (tuple, list))
            or len(tile) != 2
            or any(isinstance(item, bool) for item in tile)
        ):
            raise TypeError("tile must be a pair of positive integer multiples of 16")
        try:
            tile = tuple(int(operator.index(item)) for item in tile)
        except TypeError:
            raise TypeError("tile must be a pair of positive integer multiples of 16") from None
        if any(item <= 0 or item % 16 for item in tile):
            raise ValueError("tile dimensions must be positive multiples of 16")
    if rowsperstrip is not None:
        if isinstance(rowsperstrip, bool):
            raise TypeError("rowsperstrip must be a positive integer or None")
        try:
            rowsperstrip = int(operator.index(rowsperstrip))
        except TypeError:
            raise TypeError("rowsperstrip must be a positive integer or None") from None
        if rowsperstrip <= 0:
            raise ValueError("rowsperstrip must be positive")
    if tile is not None and rowsperstrip is not None:
        raise ValueError("tile and rowsperstrip are mutually exclusive")
    if tuple(series.index for series in value.series) != tuple(range(value.num_series)):
        raise ValueError("TIFF collection writer requires contiguous series indices")
    for series in value.series:
        if series.name is not None:
            raise ValueError("TIFF collection writer does not support series names")
        if tuple(level.index for level in series.levels) != tuple(range(series.num_levels)):
            raise ValueError("TIFF collection writer requires contiguous level indices")
        if value.num_series > 1 and series.levels[0].payload_kind == "tensor":
            raise ValueError("TIFF collection writer does not support multi-series stacks")
        if series.num_levels > 1 and series.levels[0].payload_kind == "tensor":
            raise ValueError("TIFF collection writer does not support stack pyramids")
    logical_bytes = sum(level.array.nbytes for series in value.series for level in series.levels)
    selected_bigtiff = logical_bytes >= (1 << 32) - (1 << 25) if bigtiff is None else bigtiff
    return selected_bigtiff, byteorders[byteorder], tile, rowsperstrip


def _collection_level_write_args(level: RasterLevel) -> tuple[np.ndarray, dict[str, object]]:
    if level.payload_kind == "image":
        return _image_write_args(level.payload)
    if level.payload_kind == "mask":
        return _native_c_array(level.array, "TIFF collection mask"), {"photometric": "minisblack"}
    return _stack_write_args(level.payload)


def _assert_reopened_collection(
    expected: RasterCollection,
    actual: tuple[_CollectionSeries, ...],
) -> None:
    if len(actual) != expected.num_series:
        raise RuntimeError("TIFF collection reopen changed the series count")
    for expected_series, actual_series in zip(expected.series, actual, strict=True):
        if len(actual_series.levels) != expected_series.num_levels:
            raise RuntimeError("TIFF collection reopen changed the level count")
        for expected_level, actual_level in zip(
            expected_series.levels,
            actual_series.levels,
            strict=True,
        ):
            if (
                actual_level.axes != expected_level.axes
                or actual_level.shape != expected_level.shape
                or actual_level.dtype != expected_level.dtype
                or actual_level.payload_kind != expected_level.payload_kind
            ):
                raise RuntimeError("TIFF collection reopen changed raster topology")


def write_tiff_collection(
    value: RasterCollection,
    path: str | Path,
    *,
    bigtiff: bool | None = None,
    byteorder: str | None = None,
    tile: tuple[int, int] | None = None,
    rowsperstrip: int | None = None,
) -> None:
    """Atomically write the portable bounded TIFF collection subset."""

    selected_bigtiff, selected_byteorder, tile, rowsperstrip = _collection_write_options(
        value,
        bigtiff=bigtiff,
        byteorder=byteorder,
        tile=tile,
        rowsperstrip=rowsperstrip,
    )
    tifffile = _require_tifffile()
    destination = Path(path)
    destination.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with tifffile.TiffWriter(
            temporary,
            bigtiff=selected_bigtiff,
            byteorder=selected_byteorder,
        ) as writer:
            for series in value.series:
                for level_index, level in enumerate(series.levels):
                    array, kwargs = _collection_level_write_args(level)
                    writer.write(
                        array,
                        software="SceneIO",
                        subifds=(
                            series.num_levels - 1
                            if level_index == 0 and series.num_levels > 1
                            else None
                        ),
                        subfiletype=(0 if level_index == 0 else 1),
                        tile=tile,
                        rowsperstrip=rowsperstrip,
                        **kwargs,
                    )
        with tifffile.TiffFile(temporary) as reopened:
            actual = _describe_tiff_collection(reopened)
            _assert_reopened_collection(value, actual)
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _label_kind(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("TIFF label-map kind must be a string")
    if value not in _LABEL_KINDS:
        raise ValueError("TIFF label-map kind must be semantic, instance, or panoptic")
    return value


def _json_integer(value: object, name: str, dtype: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"TIFF label-map {name} must be an integer")
    try:
        selected = operator.index(value)
    except TypeError:
        raise ValueError(f"TIFF label-map {name} must be an integer") from None
    bounds = np.iinfo(dtype)
    if selected < bounds.min or selected > bounds.max:
        raise ValueError(f"TIFF label-map {name} is outside {np.dtype(dtype).name}")
    return int(selected)


def _json_integer_vector(
    value: object,
    name: str,
    dtype: object,
) -> np.ndarray:
    if isinstance(value, (str, bytes)) or value is None:
        raise ValueError(f"TIFF label-map {name} must be an integer vector")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError(f"TIFF label-map {name} must be an integer vector") from None
    result = np.empty(len(values), dtype=dtype)
    for index, item in enumerate(values):
        result[index] = _json_integer(item, f"{name}[{index}]", dtype)
    return result


def _json_bool_vector(value: object, name: str) -> np.ndarray:
    if isinstance(value, (str, bytes)) or value is None:
        raise ValueError(f"TIFF label-map {name} must be a boolean vector")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError(f"TIFF label-map {name} must be a boolean vector") from None
    if any(not isinstance(item, bool) for item in values):
        raise ValueError(f"TIFF label-map {name} must contain booleans")
    return np.asarray(values, dtype=np.bool_)


def _json_color_array(value: object, name: str, count: int) -> np.ndarray:
    if isinstance(value, (str, bytes)) or value is None:
        raise ValueError(f"TIFF label-map {name} must be a uint8 (K,3) array")
    try:
        rows = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError(f"TIFF label-map {name} must be a uint8 (K,3) array") from None
    if len(rows) != count:
        raise ValueError(f"TIFF label-map {name} has incompatible shape")
    result = np.empty((count, 3), dtype=np.uint8)
    for row_index, row in enumerate(rows):
        if isinstance(row, (str, bytes)):
            raise ValueError(f"TIFF label-map {name} must be a uint8 (K,3) array")
        try:
            columns = tuple(row)  # type: ignore[arg-type]
        except TypeError:
            raise ValueError(f"TIFF label-map {name} must be a uint8 (K,3) array") from None
        if len(columns) != 3:
            raise ValueError(f"TIFF label-map {name} has incompatible shape")
        for column_index, item in enumerate(columns):
            result[row_index, column_index] = _json_integer(
                item, f"{name}[{row_index},{column_index}]", np.uint8
            )
    return result


def _taxonomy_metadata(taxonomy: LabelTaxonomy | None) -> dict[str, object] | None:
    if taxonomy is None:
        return None
    return {
        "semantic_ids": [int(value) for value in taxonomy.semantic_ids],
        "names": list(taxonomy.names),
        "identity": taxonomy.identity,
        "version": taxonomy.version,
        "display_colors": (
            None
            if taxonomy.display_colors is None
            else taxonomy.display_colors.astype(np.uint8, copy=False).tolist()
        ),
        "is_thing": (
            None
            if taxonomy.is_thing is None
            else taxonomy.is_thing.astype(np.bool_, copy=False).tolist()
        ),
    }


def _taxonomy_from_metadata(value: object) -> LabelTaxonomy | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("TIFF label-map taxonomy must be an object or null")
    allowed = {
        "semantic_ids",
        "names",
        "identity",
        "version",
        "display_colors",
        "is_thing",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(
            "TIFF label-map taxonomy contains unknown fields "
            + ", ".join(sorted(repr(item) for item in unknown))
        )
    required = {"semantic_ids", "names", "identity", "version"}
    missing = required - set(value)
    if missing:
        raise ValueError(
            "TIFF label-map taxonomy is incomplete; missing " + ", ".join(sorted(missing))
        )
    ids = _json_integer_vector(value["semantic_ids"], "taxonomy.semantic_ids", np.int32)
    names_value = value["names"]
    if isinstance(names_value, (str, bytes)) or names_value is None:
        raise ValueError("TIFF label-map taxonomy.names must be a string vector")
    try:
        names = tuple(names_value)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError("TIFF label-map taxonomy.names must be a string vector") from None
    if any(not isinstance(item, str) for item in names):
        raise ValueError("TIFF label-map taxonomy.names must contain strings")
    colors = value.get("display_colors")
    if colors is not None:
        colors = _json_color_array(colors, "taxonomy.display_colors", len(ids))
    thing = value.get("is_thing")
    if thing is not None:
        thing = _json_bool_vector(thing, "taxonomy.is_thing")
        if thing.shape != (len(ids),):
            raise ValueError("TIFF label-map taxonomy.is_thing has incompatible shape")
    try:
        return LabelTaxonomy(
            ids,
            names,
            value["identity"],
            value["version"],
            colors,
            thing,
        )
    except Exception as exc:
        raise ValueError(f"invalid TIFF label-map taxonomy: {exc}") from exc


def _contract_metadata(
    contract: object,
    kind: str | None = None,
) -> dict[str, object]:
    """Normalize a caller-provided TIFF label contract.

    The public typed dispatcher intentionally keeps the contract opaque.  A
    mapping with ``kind`` and only the fields relevant to that kind is the
    stable wire shape.
    """

    if not isinstance(contract, Mapping):
        raise TypeError("TIFF label-map label_contract must be a mapping")
    source = dict(contract)
    unknown = set(source) - {
        "kind",
        "roles",
        "void_id",
        "background_id",
        "taxonomy",
        "table_instance_ids",
        "table_semantic_ids",
    }
    if unknown:
        raise ValueError(
            "TIFF label-map contract contains unknown fields "
            + ", ".join(sorted(repr(item) for item in unknown))
        )
    selected_kind = _label_kind(source.get("kind", kind))
    if kind is not None and selected_kind != kind:
        raise ValueError(f"TIFF label-map contract kind {selected_kind!r} disagrees with {kind!r}")
    incompatible = {
        "semantic": {"background_id", "table_instance_ids", "table_semantic_ids"},
        "instance": {"void_id", "taxonomy"},
        "panoptic": set(),
    }[selected_kind] & set(source)
    if incompatible:
        raise ValueError(
            f"TIFF {selected_kind} label-map contract contains incompatible fields "
            + ", ".join(sorted(repr(item) for item in incompatible))
        )
    metadata: dict[str, object] = {
        "kind": selected_kind,
        "roles": source.get("roles"),
        "taxonomy": source.get("taxonomy"),
        "table_instance_ids": source.get("table_instance_ids"),
        "table_semantic_ids": source.get("table_semantic_ids"),
    }
    if selected_kind in {"semantic", "panoptic"}:
        if "void_id" not in source:
            raise ValueError("TIFF label-map explicit semantic contract requires void_id")
        metadata["void_id"] = _json_integer(source["void_id"], "void_id", np.int32)
    if selected_kind in {"instance", "panoptic"}:
        if "background_id" not in source:
            raise ValueError("TIFF label-map explicit instance contract requires background_id")
        metadata["background_id"] = _json_integer(
            source["background_id"], "background_id", np.int64
        )
    taxonomy = source.get("taxonomy")
    if isinstance(taxonomy, LabelTaxonomy):
        metadata["taxonomy"] = _taxonomy_metadata(taxonomy)
    elif taxonomy is not None:
        # Validate mappings now, before any pixel decode.
        metadata["taxonomy"] = _taxonomy_metadata(_taxonomy_from_metadata(taxonomy))
    for name, dtype in (
        ("table_instance_ids", np.int64),
        ("table_semantic_ids", np.int32),
    ):
        value = metadata[name]
        if value is not None:
            metadata[name] = _json_integer_vector(value, name, dtype).tolist()
    if (metadata["table_instance_ids"] is None) != (metadata["table_semantic_ids"] is None):
        raise ValueError("TIFF label-map instance table must declare both vectors")
    roles = metadata["roles"]
    if roles is not None:
        if isinstance(roles, (str, bytes)):
            raise ValueError("TIFF label-map contract roles must be a string vector")
        try:
            roles = tuple(roles)  # type: ignore[arg-type]
        except TypeError:
            raise ValueError("TIFF label-map contract roles must be a string vector") from None
        if any(not isinstance(role, str) for role in roles):
            raise ValueError("TIFF label-map contract roles must contain strings")
        metadata["roles"] = list(roles)
    return metadata


def _map_metadata(value: object) -> tuple[str, dict[str, object], list[tuple[str, np.ndarray]]]:
    if isinstance(value, PanopticMap):
        kind = "panoptic"
        semantic = value.semantic
        instance = value.instance
    elif isinstance(value, SemanticMap):
        kind = "semantic"
        semantic = value
        instance = None
    elif isinstance(value, InstanceMap):
        kind = "instance"
        semantic = None
        instance = value
    else:
        raise TypeError(
            "TIFF typed label-map writer expects a SemanticMap, InstanceMap, or PanopticMap"
        )
    metadata: dict[str, object] = {
        "schema": LABEL_MAP_SCHEMA,
        "kind": kind,
        "roles": [],
        "shape": list((semantic or instance).shape),
        "dtypes": {},
        "taxonomy": None,
        "table_instance_ids": None,
        "table_semantic_ids": None,
    }
    pages: list[tuple[str, np.ndarray]] = []
    if semantic is not None:
        pages.append(("semantic_ids", _native_c_array(semantic.class_ids, "TIFF semantic labels")))
        metadata["void_id"] = int(semantic.void_id)
        metadata["taxonomy"] = _taxonomy_metadata(semantic.taxonomy)
    if instance is not None:
        pages.append(
            ("instance_ids", _native_c_array(instance.instance_ids, "TIFF instance labels"))
        )
        metadata["background_id"] = int(instance.background_id)
        if instance.table_instance_ids is not None:
            metadata["table_instance_ids"] = [int(item) for item in instance.table_instance_ids]
            metadata["table_semantic_ids"] = [int(item) for item in instance.table_semantic_ids]
    valid = semantic.valid if semantic is not None else instance.valid
    if valid is not None:
        pages.append(("valid", _native_c_array(valid, "TIFF label validity")))
    metadata["roles"] = [role for role, _array in pages]
    metadata["dtypes"] = {role: array.dtype.name for role, array in pages}
    return kind, metadata, pages


class _DuplicateDescriptionKey(ValueError):
    pass


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateDescriptionKey(key)
        result[key] = value
    return result


def _description(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("TIFF label-map ImageDescription is not UTF-8") from None
    if not isinstance(value, str):
        raise ValueError("TIFF label-map ImageDescription must be text")
    text = value.strip("\x00 \t\r\n")
    if not text:
        return None
    encoded_size = len(text.encode("utf-8"))
    if encoded_size > _MAX_LABEL_DESCRIPTION_BYTES:
        if "sceneio.label_map" in text:
            raise ValueError("TIFF label-map ImageDescription exceeds 1 MiB")
        return None
    try:
        decoded = json.loads(text, object_pairs_hook=_unique_json_object)
    except _DuplicateDescriptionKey as exc:
        raise ValueError(f"TIFF label-map ImageDescription repeats key {str(exc)!r}") from None
    except (TypeError, ValueError):
        if "sceneio.label_map" in text:
            raise ValueError("TIFF label-map ImageDescription is not valid JSON") from None
        return None
    if not isinstance(decoded, dict):
        return None
    schema = decoded.get("schema")
    if not isinstance(schema, str) or not schema.startswith("sceneio.label_map/"):
        return None
    return decoded


def _page_roles(kind: str, page_count: int, roles: object | None) -> list[str]:
    if roles is None:
        primary = (
            ["semantic_ids", "instance_ids"] if kind == "panoptic" else [_LABEL_PRIMARY_ROLES[kind]]
        )
        if kind == "panoptic":
            primary += ["valid"] if page_count == 3 else []
        elif page_count == 2:
            primary.append("valid")
        if len(primary) != page_count:
            raise ValueError("TIFF label-map page count requires an explicit roles contract")
        return primary
    if isinstance(roles, (str, bytes)):
        raise ValueError("TIFF label-map roles must be a string vector")
    try:
        selected = list(roles)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError("TIFF label-map roles must be a string vector") from None
    if len(selected) != page_count or any(not isinstance(role, str) for role in selected):
        raise ValueError("TIFF label-map roles do not match TIFF page count")
    expected = {
        "semantic": {"semantic_ids", "valid"},
        "instance": {"instance_ids", "valid"},
        "panoptic": {"semantic_ids", "instance_ids", "valid"},
    }[kind]
    if set(selected) - expected or len(set(selected)) != len(selected):
        raise ValueError("TIFF label-map roles contain unknown or duplicate pages")
    required = (
        {"semantic_ids"}
        if kind == "semantic"
        else ({"instance_ids"} if kind == "instance" else {"semantic_ids", "instance_ids"})
    )
    if not required <= set(selected):
        raise ValueError("TIFF label-map roles omit a required raster")
    return selected


def _validate_header(
    header: Mapping[str, object],
    page_count: int,
    contract: object | None,
) -> tuple[str, dict[str, object], list[str], bool]:
    if header.get("schema") != LABEL_MAP_SCHEMA:
        raise ValueError(f"TIFF label-map does not declare {LABEL_MAP_SCHEMA}")
    kind = _label_kind(header.get("kind"))
    required = set(_LABEL_HEADER_COMMON) | {"role"}
    if kind in {"semantic", "panoptic"}:
        required.add("void_id")
    if kind in {"instance", "panoptic"}:
        required.add("background_id")
    missing = required - set(header)
    if missing:
        raise ValueError(
            "TIFF label-map description is incomplete; missing " + ", ".join(sorted(missing))
        )
    unknown = set(header) - required
    if unknown:
        raise ValueError(
            "TIFF label-map description contains unknown fields "
            + ", ".join(sorted(repr(item) for item in unknown))
        )
    metadata: dict[str, object] = dict(header)
    if kind in {"semantic", "panoptic"}:
        metadata["void_id"] = _json_integer(metadata["void_id"], "void_id", np.int32)
    if kind in {"instance", "panoptic"}:
        metadata["background_id"] = _json_integer(
            metadata["background_id"], "background_id", np.int64
        )
    metadata["taxonomy"] = _taxonomy_metadata(_taxonomy_from_metadata(metadata.get("taxonomy")))
    for name, dtype in (("table_instance_ids", np.int64), ("table_semantic_ids", np.int32)):
        selected = metadata.get(name)
        if selected is not None:
            metadata[name] = _json_integer_vector(selected, name, dtype).tolist()
    if (metadata.get("table_instance_ids") is None) != (metadata.get("table_semantic_ids") is None):
        raise ValueError("TIFF label-map instance table must declare both vectors")
    if kind == "semantic" and metadata.get("table_instance_ids") is not None:
        raise ValueError("TIFF semantic label-map cannot declare an instance table")
    if kind == "instance" and metadata.get("taxonomy") is not None:
        raise ValueError("TIFF instance label-map cannot declare a semantic taxonomy")
    roles = _page_roles(kind, page_count, metadata.get("roles"))
    metadata["roles"] = list(roles)
    if metadata["role"] != roles[0]:
        raise ValueError("TIFF label-map first page role disagrees with description")
    declared = metadata.get("shape")
    if isinstance(declared, (str, bytes)):
        raise ValueError("TIFF label-map description has invalid shape")
    try:
        declared_shape = tuple(declared)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError("TIFF label-map description has invalid shape") from None
    if len(declared_shape) != 2 or any(
        _json_integer(item, "shape", np.int64) <= 0 for item in declared_shape
    ):
        raise ValueError("TIFF label-map description has invalid shape")
    metadata["shape"] = [int(item) for item in declared_shape]
    dtypes = metadata.get("dtypes")
    if not isinstance(dtypes, Mapping):
        raise ValueError("TIFF label-map description dtypes must be an object")
    expected_dtypes = {
        role: {
            "semantic_ids": "int32",
            "instance_ids": "int64",
            "valid": "bool",
        }[role]
        for role in roles
    }
    if dict(dtypes) != expected_dtypes:
        raise ValueError("TIFF label-map description dtypes disagree with page roles")
    metadata["dtypes"] = expected_dtypes

    if contract is not None:
        contract_metadata = _contract_metadata(contract, kind)
        for name, expected in contract_metadata.items():
            if expected is None:
                continue
            actual = metadata.get(name)
            if name == "taxonomy":
                expected = _taxonomy_metadata(_taxonomy_from_metadata(expected))
            if actual != expected:
                raise ValueError(f"TIFF label-map contract {name} disagrees with description")
    return kind, metadata, roles, True


def _tiff_label_pages(source, label_contract: object | None):
    tifffile = _require_tifffile()
    context = (
        nullcontext(source)
        if hasattr(source, "pages") and hasattr(source, "is_bigtiff")
        else tifffile.TiffFile(source)
    )
    with context as tiff:
        pages = tuple(tiff.pages)
        if not pages:
            raise ValueError("TIFF label-map has no pages")
        descriptions = [_description(page.tags.get("ImageDescription")) for page in pages]
        first = descriptions[0]
        tagged = first is not None
        if tagged:
            if any(description is None for description in descriptions):
                raise ValueError("TIFF label-map pages have incomplete descriptions")
            assert first is not None
            kind, metadata, roles, _ = _validate_header(first, len(pages), label_contract)
            for index, description in enumerate(descriptions[1:], start=1):
                assert description is not None
                if set(description) != _LABEL_PAGE_KEYS:
                    raise ValueError(
                        "TIFF label-map page description fields are incomplete or unknown"
                    )
                if (
                    description.get("schema") != LABEL_MAP_SCHEMA
                    or _label_kind(description.get("kind")) != kind
                ):
                    raise ValueError("TIFF label-map page description disagrees with header")
                role = roles[index]
                if description.get("role") != role:
                    raise ValueError("TIFF label-map page roles are out of order")
                if description.get("shape") != metadata["shape"]:
                    raise ValueError("TIFF label-map page shape disagrees with header")
                if description.get("dtype") != metadata["dtypes"][role]:
                    raise ValueError("TIFF label-map page dtype disagrees with header")
        else:
            if any(description is not None for description in descriptions):
                raise ValueError("TIFF label-map pages have malformed descriptions")
            if label_contract is None:
                raise ValueError(f"TIFF label-map does not declare {LABEL_MAP_SCHEMA}")
            # The explicit contract is itself the activation marker.
            raw = _contract_metadata(label_contract)
            kind = _label_kind(raw["kind"])
            metadata = dict(raw)
            roles = _page_roles(kind, len(pages), metadata.get("roles"))
        shape = None
        arrays = []
        for index, (role, page) in enumerate(zip(roles, pages, strict=True)):
            if page.subifds:
                raise ValueError("TIFF label-map does not support pyramid SubIFDs")
            orientation = page.tags.get("Orientation")
            if orientation is not None and int(orientation.value) != 1:
                raise ValueError("TIFF label-map requires top-left page orientation")
            planar = page.planarconfig
            if planar is not None and int(planar) != 1:
                raise ValueError("TIFF label-map does not support planar-separate pages")
            if int(page.samplesperpixel) != 1 or int(page.photometric) not in {0, 1}:
                raise ValueError("TIFF label-map pages must contain one grayscale sample")
            page_shape = tuple(int(item) for item in page.shape)
            page_dtype = np.dtype(page.dtype)
            if page_dtype.fields is not None or page_dtype.subdtype is not None:
                raise ValueError("TIFF label-map pages require plain dtypes")
            if len(page_shape) != 2:
                raise ValueError("TIFF label-map pages must be rank-2 rasters")
            if shape is None:
                shape = page_shape
            elif page_shape != shape:
                raise ValueError("TIFF label-map pages have inconsistent shapes")
            expected_dtype = {
                "semantic_ids": np.dtype("int32"),
                "instance_ids": np.dtype("int64"),
                "valid": np.dtype("bool"),
            }[role]
            if tagged:
                if page_dtype.newbyteorder("=") != expected_dtype:
                    raise ValueError(
                        f"TIFF label-map {role} page must have dtype {expected_dtype.name}"
                    )
            elif role == "valid":
                if page_dtype not in {np.dtype("bool"), np.dtype("uint8")}:
                    raise ValueError("TIFF label-map validity must be bool or uint8")
            elif not np.issubdtype(page_dtype, np.integer):
                raise ValueError(f"TIFF label-map {role} page must have an integer dtype")
            arrays.append((role, index, page_dtype))
        assert shape is not None
        if metadata.get("shape") is not None and tuple(metadata["shape"]) != shape:
            raise ValueError("TIFF label-map description shape disagrees with pages")
        metadata["shape"] = list(shape)
        metadata["roles"] = list(roles)
        return tiff.is_bigtiff, kind, metadata, arrays, tagged


def _map_from_tiff_pages(path: str | Path, label_contract: object | None):
    tifffile = _require_tifffile()
    with tifffile.TiffFile(path) as tiff:
        _bigtiff, kind, metadata, pages, _tagged = _tiff_label_pages(tiff, label_contract)
        decoded = {}
        for role, index, _dtype in pages:
            array = _native_c_array(tiff.pages[index].asarray(), f"TIFF label-map {role}")
            if not _tagged:
                if role == "semantic_ids":
                    bounds = np.iinfo(np.int32)
                    if array.size and (
                        int(array.min()) < bounds.min or int(array.max()) > bounds.max
                    ):
                        raise ValueError("TIFF label-map semantic ids exceed int32")
                elif role == "instance_ids":
                    bounds = np.iinfo(np.int64)
                    if array.size and (
                        int(array.min()) < bounds.min or int(array.max()) > bounds.max
                    ):
                        raise ValueError("TIFF label-map instance ids exceed int64")
                elif array.dtype == np.dtype("uint8") and array.size and int(array.max()) > 1:
                    raise ValueError("TIFF label-map validity must contain only 0/1")
            decoded[role] = array.astype(
                {"semantic_ids": np.int32, "instance_ids": np.int64, "valid": np.bool_}[role],
                copy=False,
            )
    valid = decoded.get("valid")
    taxonomy = _taxonomy_from_metadata(metadata.get("taxonomy"))
    semantic = None
    if kind in {"semantic", "panoptic"}:
        semantic = SemanticMap(
            decoded["semantic_ids"],
            int(metadata["void_id"]),
            valid,
            taxonomy,
        )
    instance = None
    if kind in {"instance", "panoptic"}:
        table_instances = metadata.get("table_instance_ids")
        table_semantics = metadata.get("table_semantic_ids")
        instance = InstanceMap(
            decoded["instance_ids"],
            int(metadata["background_id"]),
            valid,
            None if table_instances is None else np.asarray(table_instances, dtype=np.int64),
            None if table_semantics is None else np.asarray(table_semantics, dtype=np.int32),
        )
    if semantic is not None and instance is not None:
        return PanopticMap(semantic, instance)
    return semantic if semantic is not None else instance


def read_tiff_label_map(
    path: str | Path,
    *,
    label_contract: object | None = None,
):
    """Read a versioned TIFF label map or an explicitly contracted raster."""

    return _map_from_tiff_pages(path, label_contract)


def inspect_tiff_label_map(
    path: str | Path,
    *,
    label_contract: object | None = None,
) -> Inspection:
    """Inspect TIFF label metadata without decoding raster samples."""

    tifffile = _require_tifffile()
    with tifffile.TiffFile(path) as tiff:
        bigtiff, kind, metadata, pages, tagged = _tiff_label_pages(tiff, label_contract)
        byte_size = int(tiff.filehandle.size)
    shape = tuple(metadata["shape"])
    primary_role = _LABEL_PRIMARY_ROLES[
        "semantic" if kind in {"semantic", "panoptic"} else "instance"
    ]
    dtype = {"semantic_ids": "int32", "instance_ids": "int64"}[primary_role]
    arrays = tuple(
        ArrayInspection(
            role,
            shape,
            {
                "semantic_ids": "int32",
                "instance_ids": "int64",
                "valid": "bool",
            }[role],
        )
        for role, _page_index, _page_dtype in pages
    )
    return Inspection(
        format="tiff",
        datatype=f"{kind}_map",
        byte_size=byte_size,
        shape=shape,
        dtype=None if kind == "panoptic" else dtype,
        count=shape[0] * shape[1],
        channels=1,
        arrays=arrays,
        metadata={
            "schema": LABEL_MAP_SCHEMA,
            "schema_source": "description" if tagged else "caller_contract",
            "kind": kind,
            "has_validity": "valid" in metadata["roles"],
            "has_taxonomy": metadata.get("taxonomy") is not None,
            "has_instance_table": metadata.get("table_instance_ids") is not None,
            "bigtiff": bool(bigtiff),
            **({"void_id": int(metadata["void_id"])} if "void_id" in metadata else {}),
            **(
                {"background_id": int(metadata["background_id"])}
                if "background_id" in metadata
                else {}
            ),
        },
    )


def write_tiff_label_map(
    value,
    path: str | Path,
    *,
    bigtiff: bool | None = None,
) -> None:
    """Write Semantic/Instance/Panoptic maps with explicit page roles."""

    if bigtiff is not None and not isinstance(bigtiff, bool):
        raise TypeError("bigtiff must be bool or None")
    kind, metadata, pages = _map_metadata(value)
    selected_bigtiff = (
        sum(array.nbytes for _role, array in pages) > 2**32 - 2**25 if bigtiff is None else bigtiff
    )
    encoded_pages: list[tuple[np.ndarray, str]] = []
    for index, (role, array) in enumerate(pages):
        page_metadata = dict(metadata)
        page_metadata["role"] = role
        if index:
            page_metadata = {
                "schema": LABEL_MAP_SCHEMA,
                "kind": kind,
                "role": role,
                "shape": metadata["shape"],
                "dtype": array.dtype.name,
            }
        description = json.dumps(
            page_metadata,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(description.encode("utf-8")) > _MAX_LABEL_DESCRIPTION_BYTES:
            raise ValueError("TIFF label-map ImageDescription exceeds 1 MiB")
        encoded_pages.append((array, description))

    destination = Path(path)
    destination.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    writer = None
    try:
        tifffile = _require_tifffile()
        writer = tifffile.TiffWriter(
            temporary,
            bigtiff=selected_bigtiff,
        )
        for array, description in encoded_pages:
            writer.write(
                array,
                photometric="minisblack",
                metadata=None,
                description=description,
            )
        writer.close()
        writer = None
        os.replace(temporary, destination)
    finally:
        with suppress(Exception):
            if writer is not None:
                writer.close()
        with suppress(FileNotFoundError):
            temporary.unlink()


__all__ = [
    "LABEL_MAP_SCHEMA",
    "inspect_tiff",
    "inspect_tiff_collection",
    "inspect_tiff_label_map",
    "read_tiff",
    "read_tiff_collection",
    "read_tiff_label_map",
    "write_tiff",
    "write_tiff_collection",
    "write_tiff_label_map",
]
