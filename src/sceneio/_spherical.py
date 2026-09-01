"""Canonical equirectangular image geometry.

The raster remains :class:`sceneio.Image`; spherical interpretation is
metadata on that one representation.  Pixel/ray transforms deliberately
match COLMAP's EQUIRECTANGULAR camera model: +X right, +Y down, +Z forward,
with the longitude seam at -Z.
"""

from __future__ import annotations

import math
import operator

import numpy as np

from sceneio import _core
from sceneio.errors import ContractViolation


def image(
    pixels: object,
    *,
    color_space: str | None = None,
    alpha_mode: str | None = None,
    maxval: int | None = None,
    projection: str = "unknown",
    projection_canvas_width: int | None = None,
    projection_canvas_height: int | None = None,
    projection_crop_left: int | None = None,
    projection_crop_top: int | None = None,
) -> _core.Image:
    """Build the canonical image record, optionally with GPano geometry."""

    try:
        return _core.image(
            pixels,
            color_space=color_space,
            alpha_mode=alpha_mode,
            maxval=maxval,
            projection=projection,
            projection_canvas_width=projection_canvas_width,
            projection_canvas_height=projection_canvas_height,
            projection_crop_left=projection_crop_left,
            projection_crop_top=projection_crop_top,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractViolation(f"Image: {exc}") from None


def as_equirectangular(
    value: _core.Image | _core.ImageSequence,
    *,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
    crop_left: int | None = None,
    crop_top: int | None = None,
) -> _core.Image | _core.ImageSequence:
    """Return an image or sequence with an equirectangular interpretation.

    Existing matching metadata returns the same record.  Declaring or changing
    the interpretation creates an owned copy, keeping :class:`Image` immutable.
    """

    if not isinstance(value, (_core.Image, _core.ImageSequence)):
        raise ContractViolation(
            f"as_equirectangular: expected Image or ImageSequence, got {type(value).__name__}"
        )
    existing = value.projection == "equirectangular"
    defaults = (
        (
            value.projection_canvas_width,
            value.projection_canvas_height,
            value.projection_crop_left,
            value.projection_crop_top,
        )
        if existing
        else (value.width, value.height, 0, 0)
    )
    overrides = (canvas_width, canvas_height, crop_left, crop_top)
    (
        resolved_canvas_width,
        resolved_canvas_height,
        resolved_crop_left,
        resolved_crop_top,
    ) = tuple(
        default if override is None else override
        for default, override in zip(defaults, overrides, strict=True)
    )
    if (
        existing
        and resolved_canvas_width == value.projection_canvas_width
        and resolved_canvas_height == value.projection_canvas_height
        and resolved_crop_left == value.projection_crop_left
        and resolved_crop_top == value.projection_crop_top
    ):
        return value
    if isinstance(value, _core.ImageSequence):
        try:
            return _core.image_sequence_with_projection(
                value,
                "equirectangular",
                resolved_canvas_width,
                resolved_canvas_height,
                resolved_crop_left,
                resolved_crop_top,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractViolation(f"ImageSequence: {exc}") from None
    return image(
        value.pixels,
        color_space=value.color_space,
        alpha_mode=value.alpha_mode,
        maxval=value.maxval,
        projection="equirectangular",
        projection_canvas_width=resolved_canvas_width,
        projection_canvas_height=resolved_canvas_height,
        projection_crop_left=resolved_crop_left,
        projection_crop_top=resolved_crop_top,
    )


def _positive_extent(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ContractViolation(f"{name}: expected a positive finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ContractViolation(f"{name}: expected a positive finite number") from None
    if not math.isfinite(result) or result <= 0:
        raise ContractViolation(f"{name}: expected a positive finite number")
    return result


def _coordinates(value: object, width: int, name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        raise ContractViolation(f"{name}: expected a numeric (..., {width}) array") from None
    if result.ndim == 0 or result.shape[-1] != width:
        raise ContractViolation(f"{name}: expected shape (..., {width}), got {result.shape}")
    if not bool(np.all(np.isfinite(result))):
        raise ContractViolation(f"{name}: values must be finite")
    return result


def spherical_pixels_to_rays(
    spherical_xy: object,
    spherical_width: object,
    spherical_height: object,
) -> np.ndarray:
    """Map full-canvas equirectangular coordinates to COLMAP camera rays."""

    xy = _coordinates(spherical_xy, 2, "spherical_xy")
    width = _positive_extent(spherical_width, "spherical_width")
    height = _positive_extent(spherical_height, "spherical_height")
    longitude = (xy[..., 0] / width - 0.5) * (2.0 * np.pi)
    latitude = (0.5 - xy[..., 1] / height) * np.pi
    cos_latitude = np.cos(latitude)
    return np.stack(
        (
            cos_latitude * np.sin(longitude),
            -np.sin(latitude),
            cos_latitude * np.cos(longitude),
        ),
        axis=-1,
    )


def rays_to_spherical_pixels(
    rays: object,
    spherical_width: object,
    spherical_height: object,
) -> np.ndarray:
    """Project non-zero camera rays onto a full equirectangular canvas."""

    values = _coordinates(rays, 3, "rays")
    width = _positive_extent(spherical_width, "spherical_width")
    height = _positive_extent(spherical_height, "spherical_height")
    norms = np.linalg.norm(values, axis=-1)
    if bool(np.any(norms == 0)):
        raise ContractViolation("rays: values must be non-zero")
    normalized = values / norms[..., None]
    longitude = np.arctan2(normalized[..., 0], normalized[..., 2])
    latitude = np.arcsin(np.clip(-normalized[..., 1], -1.0, 1.0))
    x = np.mod((longitude / (2.0 * np.pi) + 0.5) * width, width)
    y = (0.5 - latitude / np.pi) * height
    return np.stack((x, y), axis=-1)


def _equirectangular_raster(
    value: object,
) -> _core.Image | _core.ImageSequence:
    if not isinstance(value, (_core.Image, _core.ImageSequence)):
        raise ContractViolation(
            f"equirectangular geometry: expected Image or ImageSequence, got {type(value).__name__}"
        )
    if value.projection != "equirectangular":
        raise ContractViolation("equirectangular geometry requires projection='equirectangular'")
    return value


def equirectangular_pixels_to_rays(
    value: _core.Image | _core.ImageSequence,
    image_xy: object,
) -> np.ndarray:
    """Map crop-local image coordinates to rays using the image metadata."""

    selected = _equirectangular_raster(value)
    xy = _coordinates(image_xy, 2, "image_xy").copy()
    xy[..., 0] += selected.projection_crop_left
    xy[..., 1] += selected.projection_crop_top
    return spherical_pixels_to_rays(
        xy,
        selected.projection_canvas_width,
        selected.projection_canvas_height,
    )


def rays_to_equirectangular_pixels(
    value: _core.Image | _core.ImageSequence,
    rays: object,
) -> np.ndarray:
    """Project rays into crop-local coordinates; results may lie outside it."""

    selected = _equirectangular_raster(value)
    xy = rays_to_spherical_pixels(
        rays,
        selected.projection_canvas_width,
        selected.projection_canvas_height,
    )
    xy[..., 0] -= selected.projection_crop_left
    xy[..., 1] -= selected.projection_crop_top
    return xy


def _positive_integer(value: object, name: str) -> int:
    try:
        result = operator.index(value)
    except TypeError:
        raise ContractViolation(f"{name}: expected a positive integer") from None
    if isinstance(value, bool) or result <= 0:
        raise ContractViolation(f"{name}: expected a positive integer")
    return result


def equirectangular_camera(
    image_or_width: _core.Image | _core.ImageSequence | int,
    height: int | None = None,
) -> _core.CameraIntrinsics:
    """Build COLMAP model 17 for a full-sphere image or explicit dimensions."""

    if isinstance(image_or_width, (_core.Image, _core.ImageSequence)):
        if height is not None:
            raise ContractViolation(
                "equirectangular_camera: height is invalid when a raster record is supplied"
            )
        selected = _equirectangular_raster(image_or_width)
        if not selected.is_full_sphere:
            raise ContractViolation(
                "equirectangular_camera: cropped panoramas require resampling to their full canvas"
            )
        width = selected.width
        resolved_height = selected.height
    else:
        width = _positive_integer(image_or_width, "width")
        if height is None:
            raise ContractViolation("equirectangular_camera: height is required")
        resolved_height = _positive_integer(height, "height")
    params = np.array((width, resolved_height), dtype=np.float64)
    try:
        return _core.camera_intrinsics(17, width, resolved_height, params)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractViolation(f"equirectangular_camera: {exc}") from None


__all__ = [
    "as_equirectangular",
    "equirectangular_camera",
    "equirectangular_pixels_to_rays",
    "image",
    "rays_to_equirectangular_pixels",
    "rays_to_spherical_pixels",
    "spherical_pixels_to_rays",
]
