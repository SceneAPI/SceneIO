"""NCore V4 camera, lidar, and radar sensor profiles."""

from __future__ import annotations

import numpy as np

from sceneio.io._ncore.model import (
    NCoreComponentData,
    NCoreItem,
    NCoreSemanticComponent,
)
from sceneio.io._ncore.profiles.common import (
    array_attributes,
    arrays_below,
    frame_intervals,
    integer,
    non_empty_string,
    require_group,
    require_version,
)


def _encoded_bytes(array: np.ndarray, context: str) -> None:
    if array.ndim == 0 and array.dtype.kind in {"S", "V"}:
        return
    if array.ndim == 1 and array.dtype == np.dtype("uint8"):
        return
    raise ValueError(f"{context} must be scalar bytes or a uint8 vector")


def read_camera_profile(
    data: NCoreComponentData,
    sequence_interval_us: tuple[int, int],
) -> NCoreSemanticComponent:
    require_version(data)
    items: list[NCoreItem] = []
    for frame_id, interval in frame_intervals(data, sequence_interval_us):
        require_group(data, f"frames/{frame_id}")
        generic = require_group(data, f"frames/{frame_id}/generic_data")
        arrays = arrays_below(data, f"frames/{frame_id}")
        try:
            image = arrays["image"]
        except KeyError:
            raise ValueError(f"NCore camera frame {frame_id} lacks image data") from None
        _encoded_bytes(image, f"NCore camera frame {frame_id} image")
        image_attributes = array_attributes(data, f"frames/{frame_id}/image")
        image_format = non_empty_string(
            image_attributes.get("format"),
            f"NCore camera frame {frame_id} image format",
        )
        items.append(
            NCoreItem(
                kind="camera_frame",
                id=frame_id,
                arrays=arrays,
                attributes={
                    "image_format": image_format,
                    "generic_meta_data": dict(generic.attributes),
                },
                timestamp_interval_us=interval,
                timestamp_us=interval[1],
            )
        )
    return NCoreSemanticComponent(
        raw=data,
        profile="cameras/v1",
        items=tuple(items),
    )


def _required_array(
    arrays: dict[str, np.ndarray], name: str, context: str
) -> np.ndarray:
    try:
        return arrays[name]
    except KeyError:
        raise ValueError(f"{context} lacks array {name!r}") from None


def _validate_ray_frame(
    data: NCoreComponentData,
    frame_id: str,
    interval: tuple[int, int],
    *,
    lidar: bool,
) -> NCoreItem:
    kind = "lidar" if lidar else "radar"
    context = f"NCore {kind} frame {frame_id}"
    require_group(data, f"frames/{frame_id}")
    generic = require_group(data, f"frames/{frame_id}/generic_data")
    ray_group = require_group(data, f"frames/{frame_id}/ray_bundle")
    return_group = require_group(
        data, f"frames/{frame_id}/ray_bundle_returns"
    )
    n_rays = integer(ray_group.attributes.get("n_rays"), f"{context} n_rays")
    n_returns = integer(
        return_group.attributes.get("n_returns"), f"{context} n_returns"
    )
    arrays = arrays_below(data, f"frames/{frame_id}")
    direction = _required_array(arrays, "ray_bundle/direction", context)
    if direction.dtype != np.dtype("float32") or direction.shape != (n_rays, 3):
        raise ValueError(f"{context} direction must be float32 (N, 3)")
    if n_rays and not np.all(
        np.abs(np.sum(direction**2, axis=1) - 1.0) < 1e-4
    ):
        raise ValueError(f"{context} directions must be unit-norm")
    timestamps = _required_array(arrays, "ray_bundle/timestamp_us", context)
    if timestamps.dtype != np.dtype("uint64") or timestamps.shape != (n_rays,):
        raise ValueError(f"{context} timestamps must be uint64 (N,)")
    if n_rays and (
        int(timestamps.min()) < interval[0]
        or int(timestamps.max()) > interval[1]
    ):
        raise ValueError(f"{context} ray timestamps lie outside the frame")
    model_element = arrays.get("ray_bundle/model_element")
    if model_element is not None and (
        not lidar
        or model_element.dtype != np.dtype("uint16")
        or model_element.shape != (n_rays, 2)
    ):
        raise ValueError(f"{context} model_element must be lidar uint16 (N, 2)")

    distance = _required_array(
        arrays, "ray_bundle_returns/distance_m", context
    )
    if distance.dtype != np.dtype("float32") or distance.shape != (
        n_returns,
        n_rays,
    ):
        raise ValueError(f"{context} distance_m must be float32 (R, N)")
    finite_distance = distance[np.isfinite(distance)]
    if np.any(finite_distance < 0):
        raise ValueError(f"{context} distance_m cannot be negative")
    absent = np.isnan(distance)
    if lidar:
        intensity = _required_array(
            arrays, "ray_bundle_returns/intensity", context
        )
        if intensity.dtype != np.dtype("float32") or intensity.shape != (
            n_returns,
            n_rays,
        ):
            raise ValueError(f"{context} intensity must be float32 (R, N)")
        finite_intensity = intensity[np.isfinite(intensity)]
        if np.any((finite_intensity < 0) | (finite_intensity > 1)):
            raise ValueError(f"{context} intensity must lie in [0, 1]")
        if not np.array_equal(absent, np.isnan(intensity)):
            raise ValueError(f"{context} return arrays disagree on absent values")

    packed_name = "ray_bundle_returns_valid_mask_packed"
    packed = _required_array(arrays, packed_name, context)
    if packed.dtype != np.dtype("uint8") or packed.ndim != 1:
        raise ValueError(f"{context} valid mask must be a uint8 vector")
    mask_attributes = array_attributes(data, f"frames/{frame_id}/{packed_name}")
    if (
        mask_attributes.get("n_returns") != n_returns
        or mask_attributes.get("n_rays") != n_rays
    ):
        raise ValueError(f"{context} valid-mask dimensions disagree")
    valid = np.unpackbits(packed, count=n_returns * n_rays).reshape(
        (n_returns, n_rays)
    )
    if not np.array_equal(valid.astype(bool), ~absent):
        raise ValueError(f"{context} valid mask disagrees with return data")
    return NCoreItem(
        kind=f"{kind}_frame",
        id=frame_id,
        arrays=arrays,
        attributes={
            "n_rays": n_rays,
            "n_returns": n_returns,
            "generic_meta_data": dict(generic.attributes),
        },
        timestamp_interval_us=interval,
        timestamp_us=interval[1],
        reference_frame_id=data.component.instance,
    )


def _read_ray_profile(
    data: NCoreComponentData,
    sequence_interval_us: tuple[int, int],
    *,
    lidar: bool,
) -> NCoreSemanticComponent:
    require_version(data)
    items = tuple(
        _validate_ray_frame(data, frame_id, interval, lidar=lidar)
        for frame_id, interval in frame_intervals(data, sequence_interval_us)
    )
    name = "lidars" if lidar else "radars"
    return NCoreSemanticComponent(
        raw=data,
        profile=f"{name}/v1",
        items=items,
    )


def read_lidar_profile(
    data: NCoreComponentData,
    _sequence_interval_us: tuple[int, int],
) -> NCoreSemanticComponent:
    return _read_ray_profile(data, _sequence_interval_us, lidar=True)


def read_radar_profile(
    data: NCoreComponentData,
    _sequence_interval_us: tuple[int, int],
) -> NCoreSemanticComponent:
    return _read_ray_profile(data, _sequence_interval_us, lidar=False)


__all__ = ["read_camera_profile", "read_lidar_profile", "read_radar_profile"]
