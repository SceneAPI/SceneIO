from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

import sceneio
from sceneio import Mask, RasterCollection, RasterLevel, RasterSeries, _core
from sceneio.errors import ContractViolation


def _image_level(
    index: int = 0,
    *,
    shape: tuple[int, ...] = (8, 10),
    dtype: object = np.uint8,
) -> RasterLevel:
    pixels = np.arange(np.prod(shape), dtype=dtype).reshape(shape)
    image = _core.image(pixels)
    axes = "YX" if len(shape) == 2 else "YXC"
    return RasterLevel(index, axes, shape, pixels.dtype.name, "image", image)


def _mask_level(index: int = 0, *, shape=(8, 10)) -> RasterLevel:
    mask = Mask(np.ascontiguousarray(np.indices(shape).sum(axis=0) % 2 == 0))
    return RasterLevel(index, "YX", shape, "bool", "mask", mask)


def _stack_level(index: int = 0, *, axes="ZYX", shape=(3, 8, 10)) -> RasterLevel:
    values = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    payload = _core.tensor_dict({"pages": values}, attrs={"axes": axes})
    return RasterLevel(index, axes, shape, "float32", "tensor", payload)


def test_raster_records_are_frozen_ordered_and_expose_owned_payloads():
    full = _image_level(shape=(8, 10))
    reduced = _image_level(1, shape=(4, 5))
    series = RasterSeries(0, "camera", (full, reduced))
    collection = RasterCollection((series, RasterSeries(1, None, (_mask_level(),))))

    assert collection.num_series == 2
    assert collection.series_at(0) is series
    assert series.num_levels == 2
    assert series.level_at(1) is reduced
    assert full.page_count == 1
    assert np.shares_memory(full.array, np.asarray(full.payload.pixels))
    assert sceneio.coordinate_convention(full) == sceneio.IMAGE_COORDINATES
    assert sceneio.coordinate_convention(collection) == sceneio.IMAGE_COORDINATES
    with pytest.raises(FrozenInstanceError):
        collection.series = ()


def test_raster_stack_payload_and_coordinate_boundary():
    level = _stack_level()
    assert level.page_count == 3
    np.testing.assert_array_equal(level.array, level.payload["pages"])
    assert sceneio.coordinate_convention(level) == sceneio.UNKNOWN_COORDINATES


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("index", -1, "non-negative"),
        ("axes", "TZYX", "axes"),
        ("shape", (0, 4), "positive"),
        ("shape", (1, 2, 3, 4), "rank 2 or 3"),
        ("dtype", "int32", "dtype"),
        ("payload_kind", "volume", "payload_kind"),
    ],
)
def test_raster_level_rejects_invalid_declared_fields(field, value, message):
    kwargs = {
        "index": 0,
        "axes": "YX",
        "shape": (8, 10),
        "dtype": "uint8",
        "payload_kind": "image",
        "payload": _core.image(np.zeros((8, 10), np.uint8)),
    }
    kwargs[field] = value
    with pytest.raises(ContractViolation, match=message):
        RasterLevel(**kwargs)


def test_raster_level_rejects_payload_mismatch():
    with pytest.raises(ContractViolation, match="shape does not match"):
        RasterLevel(
            0,
            "YX",
            (3, 4),
            "uint8",
            "image",
            _core.image(np.zeros((2, 4), np.uint8)),
        )
    with pytest.raises(ContractViolation, match="mask kind requires"):
        RasterLevel(
            0,
            "YX",
            (2, 4),
            "bool",
            "mask",
            _core.image(np.zeros((2, 4), np.uint8)),
        )


def test_raster_series_requires_ordered_homogeneous_decreasing_levels():
    RasterSeries(0, None, (_image_level(1),))
    with pytest.raises(ContractViolation, match="strictly increasing"):
        RasterSeries(0, None, (_image_level(1), _image_level(0, shape=(4, 5))))
    with pytest.raises(ContractViolation, match="homogeneous"):
        RasterSeries(0, None, (_image_level(), _mask_level(1, shape=(4, 5))))
    with pytest.raises(ContractViolation, match="must decrease"):
        RasterSeries(0, None, (_image_level(), _image_level(1)))
    with pytest.raises(ContractViolation, match="must decrease"):
        RasterSeries(
            0,
            None,
            (_image_level(shape=(8, 10)), _image_level(1, shape=(9, 5))),
        )

    rgba_full = np.zeros((8, 10, 4), np.uint8)
    rgba_reduced = np.zeros((4, 5, 4), np.uint8)
    straight = RasterLevel(
        0,
        "YXC",
        rgba_full.shape,
        "uint8",
        "image",
        _core.image(rgba_full, alpha_mode="straight"),
    )
    premultiplied = RasterLevel(
        1,
        "YXC",
        rgba_reduced.shape,
        "uint8",
        "image",
        _core.image(rgba_reduced, alpha_mode="premultiplied"),
    )
    with pytest.raises(ContractViolation, match="semantics must be homogeneous"):
        RasterSeries(0, None, (straight, premultiplied))


def test_raster_collection_requires_nonempty_ordered_series():
    with pytest.raises(ContractViolation, match="at least one"):
        RasterCollection(())
    RasterCollection((RasterSeries(1, None, (_image_level(),)),))
    with pytest.raises(ContractViolation, match="strictly increasing"):
        RasterCollection(
            (
                RasterSeries(2, None, (_image_level(),)),
                RasterSeries(1, None, (_image_level(),)),
            )
        )
    with pytest.raises(IndexError, match="out of range"):
        RasterCollection((RasterSeries(0, None, (_image_level(),)),)).series_at(1)
