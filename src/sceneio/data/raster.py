"""Format-neutral bounded raster collection records.

The records describe independently meaningful computer-vision images, masks,
and grayscale page stacks. They intentionally do not model arbitrary OME
microscopy axes or TIFF metadata.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from sceneio.data.dense import Mask
from sceneio.errors import ContractViolation

RASTER_AXES: frozenset[str] = frozenset({"YX", "YXC", "CYX", "IYX", "QYX", "TYX", "ZYX"})
RASTER_DTYPES: frozenset[str] = frozenset({"bool", "uint8", "uint16", "float32"})
RASTER_PAYLOAD_KINDS: frozenset[str] = frozenset({"image", "mask", "tensor"})
_STACK_AXES = RASTER_AXES - {"YX", "YXC"}


def _index(name: str, value: object) -> int:
    if isinstance(value, bool):
        raise ContractViolation(f"{name}: expected a non-negative integer")
    try:
        result = operator.index(value)
    except TypeError:
        raise ContractViolation(f"{name}: expected a non-negative integer") from None
    if result < 0:
        raise ContractViolation(f"{name}: expected a non-negative integer")
    return int(result)


def _shape(value: object) -> tuple[int, ...]:
    if not isinstance(value, (tuple, list)):
        raise ContractViolation("RasterLevel.shape: expected a tuple or list")
    result: list[int] = []
    for dimension in value:
        if isinstance(dimension, bool):
            raise ContractViolation("RasterLevel.shape: dimensions must be positive integers")
        try:
            size = operator.index(dimension)
        except TypeError:
            raise ContractViolation(
                "RasterLevel.shape: dimensions must be positive integers"
            ) from None
        if size <= 0:
            raise ContractViolation("RasterLevel.shape: dimensions must be positive integers")
        result.append(int(size))
    if len(result) not in {2, 3}:
        raise ContractViolation("RasterLevel.shape: expected rank 2 or 3")
    return tuple(result)


def _payload_array(kind: str, payload: object) -> np.ndarray:
    type_name = type(payload).__name__
    if kind == "image":
        if type_name != "Image" or not hasattr(payload, "pixels"):
            raise ContractViolation("RasterLevel.payload: image kind requires Image")
        return np.asarray(payload.pixels)
    if kind == "mask":
        if not isinstance(payload, Mask):
            raise ContractViolation("RasterLevel.payload: mask kind requires Mask")
        return np.asarray(payload.mask)
    if type_name != "TensorDict" or not hasattr(payload, "keys"):
        raise ContractViolation("RasterLevel.payload: tensor kind requires TensorDict")
    if tuple(payload.keys()) != ("pages",):
        raise ContractViolation("RasterLevel.payload: TensorDict must contain only 'pages'")
    return np.asarray(payload["pages"])


def _spatial_shape(level: RasterLevel) -> tuple[int, int]:
    if level.axes == "YXC":
        return level.shape[0], level.shape[1]
    return level.shape[-2], level.shape[-1]


def _non_spatial_shape(level: RasterLevel) -> tuple[int, ...]:
    if level.axes == "YXC":
        return level.shape[2:]
    return level.shape[:-2]


@dataclass(frozen=True)
class RasterLevel:
    """One decoded raster or pyramid level with explicit array semantics."""

    index: int
    axes: str
    shape: tuple[int, ...]
    dtype: str
    payload_kind: str
    payload: object

    def __post_init__(self) -> None:
        index = _index("RasterLevel.index", self.index)
        if self.axes not in RASTER_AXES:
            raise ContractViolation(f"RasterLevel.axes: expected one of {sorted(RASTER_AXES)!r}")
        shape = _shape(self.shape)
        if self.dtype not in RASTER_DTYPES:
            raise ContractViolation(f"RasterLevel.dtype: expected one of {sorted(RASTER_DTYPES)!r}")
        if self.payload_kind not in RASTER_PAYLOAD_KINDS:
            raise ContractViolation("RasterLevel.payload_kind: expected image, mask, or tensor")
        array = _payload_array(self.payload_kind, self.payload)
        if tuple(array.shape) != shape:
            raise ContractViolation(
                "RasterLevel.payload: array shape does not match declared shape"
            )
        if array.dtype.name != self.dtype:
            raise ContractViolation(
                "RasterLevel.payload: array dtype does not match declared dtype"
            )
        if not array.dtype.isnative or not array.flags.c_contiguous:
            raise ContractViolation(
                "RasterLevel.payload: array must be native-endian and C-contiguous"
            )
        if self.payload_kind == "image":
            if self.axes == "YX" and len(shape) == 2:
                if self.payload.color_space != "gray" or self.payload.alpha_mode != "none":
                    raise ContractViolation(
                        "RasterLevel.payload: YX images require gray color and no alpha"
                    )
            elif self.axes == "YXC" and len(shape) == 3 and shape[-1] in {3, 4}:
                if self.payload.color_space != "srgb":
                    raise ContractViolation("RasterLevel.payload: YXC images require srgb color")
                allowed_alpha = {3: {"none"}, 4: {"straight", "premultiplied"}}
                if self.payload.alpha_mode not in allowed_alpha[shape[-1]]:
                    raise ContractViolation(
                        "RasterLevel.payload: image alpha mode does not match channels"
                    )
            else:
                raise ContractViolation(
                    "RasterLevel.payload: image kind requires YX or 3/4-channel YXC"
                )
            if self.dtype == "bool":
                raise ContractViolation("RasterLevel.payload: boolean samples require mask kind")
        elif self.payload_kind == "mask":
            if self.axes != "YX" or len(shape) != 2 or self.dtype != "bool":
                raise ContractViolation("RasterLevel.payload: mask kind requires bool YX")
        else:
            if self.axes not in _STACK_AXES or len(shape) != 3:
                raise ContractViolation(
                    "RasterLevel.payload: tensor kind requires a supported rank-3 stack"
                )
            if dict(self.payload.attrs) != {"axes": self.axes}:
                raise ContractViolation(
                    "RasterLevel.payload: TensorDict attrs must declare the same axes"
                )
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "shape", shape)

    @property
    def array(self) -> np.ndarray:
        """Return the payload's owned sample array."""

        return _payload_array(self.payload_kind, self.payload)

    @property
    def page_count(self) -> int:
        """Return the represented page count (one for ordinary images)."""

        return self.shape[0] if self.axes in _STACK_AXES else 1


@dataclass(frozen=True)
class RasterSeries:
    """One ordered, homogeneous image or stack pyramid."""

    index: int
    name: str | None
    levels: tuple[RasterLevel, ...]

    def __post_init__(self) -> None:
        index = _index("RasterSeries.index", self.index)
        if self.name is not None:
            if not isinstance(self.name, str) or not self.name or "\0" in self.name:
                raise ContractViolation(
                    "RasterSeries.name: expected None or non-empty text without NUL"
                )
            try:
                self.name.encode("utf-8")
            except UnicodeEncodeError:
                raise ContractViolation("RasterSeries.name: expected valid UTF-8 text") from None
        if not isinstance(self.levels, (tuple, list)) or not self.levels:
            raise ContractViolation("RasterSeries.levels: expected at least one level")
        levels = tuple(self.levels)
        if any(not isinstance(level, RasterLevel) for level in levels):
            raise ContractViolation("RasterSeries.levels: expected only RasterLevel values")
        level_indices = tuple(level.index for level in levels)
        if any(left >= right for left, right in pairwise(level_indices)):
            raise ContractViolation(
                "RasterSeries.levels: level indices must be strictly increasing"
            )
        first = levels[0]
        previous = first
        first_image_semantics = (
            (
                first.payload.color_space,
                first.payload.alpha_mode,
                first.payload.maxval,
            )
            if first.payload_kind == "image"
            else None
        )
        for level in levels[1:]:
            level_image_semantics = (
                (
                    level.payload.color_space,
                    level.payload.alpha_mode,
                    level.payload.maxval,
                )
                if level.payload_kind == "image"
                else None
            )
            if (
                level.axes != first.axes
                or level.dtype != first.dtype
                or level.payload_kind != first.payload_kind
                or _non_spatial_shape(level) != _non_spatial_shape(first)
                or level_image_semantics != first_image_semantics
            ):
                raise ContractViolation(
                    "RasterSeries.levels: pyramid semantics must be homogeneous"
                )
            if (
                _spatial_shape(level)[0] > _spatial_shape(previous)[0]
                or _spatial_shape(level)[1] > _spatial_shape(previous)[1]
                or _spatial_shape(level) == _spatial_shape(previous)
            ):
                raise ContractViolation(
                    "RasterSeries.levels: spatial pyramid dimensions must decrease"
                )
            previous = level
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "levels", levels)

    @property
    def num_levels(self) -> int:
        return len(self.levels)

    def level_at(self, index: int) -> RasterLevel:
        selected = _index("RasterSeries.level_at index", index)
        for level in self.levels:
            if level.index == selected:
                return level
        raise IndexError("RasterSeries level index out of range")


@dataclass(frozen=True)
class RasterCollection:
    """An ordered collection of independently valid raster series."""

    series: tuple[RasterSeries, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.series, (tuple, list)) or not self.series:
            raise ContractViolation("RasterCollection.series: expected at least one series")
        series = tuple(self.series)
        if any(not isinstance(item, RasterSeries) for item in series):
            raise ContractViolation("RasterCollection.series: expected only RasterSeries values")
        series_indices = tuple(item.index for item in series)
        if any(left >= right for left, right in pairwise(series_indices)):
            raise ContractViolation(
                "RasterCollection.series: series indices must be strictly increasing"
            )
        object.__setattr__(self, "series", series)

    @property
    def num_series(self) -> int:
        return len(self.series)

    def series_at(self, index: int) -> RasterSeries:
        selected = _index("RasterCollection.series_at index", index)
        for series in self.series:
            if series.index == selected:
                return series
        raise IndexError("RasterCollection series index out of range")


__all__ = [
    "RASTER_AXES",
    "RASTER_DTYPES",
    "RASTER_PAYLOAD_KINDS",
    "RasterCollection",
    "RasterLevel",
    "RasterSeries",
]
