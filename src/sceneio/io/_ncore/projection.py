"""Exact NCore-item projections into existing SceneIO record types."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from sceneio import _core
from sceneio.data.dense import Mask
from sceneio.io._ncore.model import NCoreItem

_IMAGE_READERS = {
    "exr": _core.read_exr,
    "hdr": _core.read_hdr,
    "jpeg": _core.read_jpeg,
    "jpg": _core.read_jpeg,
    "pgm": _core.read_netpbm,
    "png": _core.read_png,
    "pnm": _core.read_netpbm,
    "ppm": _core.read_netpbm,
    "webp": _core.read_webp,
}


def _encoded_bytes(value: np.ndarray, context: str) -> bytes:
    if value.ndim == 0 and value.dtype.kind in {"S", "V"}:
        return bytes(value)
    if value.ndim == 1 and value.dtype == np.dtype("uint8"):
        return value.tobytes()
    raise ValueError(f"{context} does not contain encoded bytes")


def _image(item: NCoreItem, array_name: str, format_name: str):
    try:
        reader = _IMAGE_READERS[format_name.lower()]
    except KeyError:
        raise ValueError(
            f"NCore image format {format_name!r} has no SceneIO projection"
        ) from None
    return reader(memoryview(_encoded_bytes(item.array(array_name), "NCore image")))


def _mask(item: NCoreItem) -> Mask:
    image = _image(item, "data", str(item.attributes["format"]))
    pixels = np.asarray(image.pixels)
    if pixels.ndim == 3:
        first = pixels[..., 0]
        if not np.all(pixels == first[..., None]):
            raise ValueError(
                "NCore camera mask channels disagree and cannot form one boolean mask"
            )
        pixels = first
    return Mask(np.array(pixels != 0, dtype=bool, copy=True, order="C"))


def _point_cloud(item: NCoreItem):
    if item.attributes.get("coordinate_unit") != "METERS":
        raise ValueError(
            "NCore point-cloud projection requires metric coordinates"
        )
    raw_schemas = item.attributes.get("attribute_schemas", {})
    if not isinstance(raw_schemas, Mapping):
        raise ValueError("NCore point-cloud attribute schemas are invalid")
    arrays = item.arrays
    if any(name.startswith("generic_data/") for name in arrays):
        raise ValueError(
            "NCore point-cloud generic arrays have no exact PointCloud payload projection"
        )
    recognized = {"color", "colors", "intensity", "normal", "normals", "rgb"}
    unknown = set(raw_schemas) - recognized
    if unknown:
        raise ValueError(
            "NCore point-cloud attributes have no exact PointCloud payload projection: "
            + ", ".join(sorted(unknown))
        )
    unexpected_arrays = set(arrays) - {"xyz", *raw_schemas}
    if unexpected_arrays:
        raise ValueError(
            "NCore point-cloud arrays have no exact PointCloud payload projection: "
            + ", ".join(sorted(unexpected_arrays))
        )
    color_names = tuple(name for name in ("rgb", "colors", "color") if name in arrays)
    normal_names = tuple(name for name in ("normals", "normal") if name in arrays)
    if len(color_names) > 1 or len(normal_names) > 1:
        raise ValueError("NCore point-cloud projection has duplicate standard channels")
    colors = arrays[color_names[0]] if color_names else None
    normals = arrays[normal_names[0]] if normal_names else None
    intensity = arrays.get("intensity")
    if colors is not None and (
        colors.dtype != np.dtype("uint8")
        or colors.shape != (len(item.array("xyz")), 3)
    ):
        raise ValueError("NCore point-cloud colors must be uint8 (N, 3)")
    if normals is not None and (
        normals.dtype != np.dtype("float32")
        or normals.shape != (len(item.array("xyz")), 3)
    ):
        raise ValueError("NCore point-cloud normals must be float32 (N, 3)")
    if intensity is not None and (
        intensity.dtype != np.dtype("float32")
        or intensity.shape != (len(item.array("xyz")),)
    ):
        raise ValueError("NCore point-cloud intensity must be float32 (N,)")
    return _core.point_cloud(
        item.array("xyz"),
        colors=colors,
        normals=normals,
        intensity=intensity,
        coordinate_frame="unknown",
        scale_to_meters=1.0,
        intensity_range="unknown",
    )


def project_ncore_item(item: NCoreItem):
    """Project an exact item payload while its NCore metadata stays on ``item``."""

    if not isinstance(item, NCoreItem):
        raise TypeError("item must be an NCoreItem")
    if item.kind == "camera_frame":
        return _image(item, "image", str(item.attributes["image_format"]))
    if item.kind == "camera_mask":
        return _mask(item)
    if item.kind == "point_cloud":
        return _point_cloud(item)
    raise ValueError(
        f"NCore item kind {item.kind!r} has no exact SceneIO payload projection"
    )


__all__ = ["project_ncore_item"]
