"""Private translation between canonical posed views and codec storage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np

from sceneio import _core
from sceneio._data.calibration import Calibration
from sceneio._data.transforms import SE3
from sceneio._data.views import FrameMeta, PosedViewSet
from sceneio.coordinate_conversion import convert_coordinates
from sceneio.coordinates import COLMAP_COORDINATES
from sceneio.errors import ContractViolation

_CANONICAL_COORDINATES = replace(
    COLMAP_COORDINATES,
    name="canonical_posed_views",
    pose_direction="camera_to_world",
    quaternion_order="wxyz",
    scale_class="metric",
    scale_to_meters=1.0,
)
_TRANSFORMS_JSON_COORDINATES = replace(
    _CANONICAL_COORDINATES,
    name="transforms_json_storage",
    camera_axes="opengl",
)
_POSE_PROFILES = frozenset({"transforms_json", "tum", "kitti"})


def _calibration_signature(value: Calibration | None) -> object:
    if value is None:
        return None
    if value.intrinsics is not None:
        intrinsics = value.intrinsics
        return (
            "intrinsics",
            int(intrinsics.model_id),
            int(intrinsics.width),
            int(intrinsics.height),
            np.asarray(intrinsics.params).tobytes(order="C"),
        )
    assert value.rays is not None
    directions = value.rays.directions
    return ("rays", directions.dtype.str, directions.shape, directions.tobytes(order="C"))


def _semantic_signature(value: PosedViewSet) -> object:
    return (
        tuple(
            (
                pose.convention,
                pose.rotation.tobytes(order="C"),
                pose.translation.tobytes(order="C"),
            )
            for pose in value.poses
        ),
        (
            value.frame.world_frame,
            value.frame.scale,
            value.frame.scale_provenance,
        ),
        value.names,
        value.timestamps,
        tuple(image is None for image in value.images),
        tuple(_calibration_signature(item) for item in value.calibrations),
    )


def posed_views_from_storage(
    storage: object,
    *,
    source_profile: str,
    images: object = (),
) -> PosedViewSet:
    """Normalize one private native pose record into the public model."""

    if source_profile not in _POSE_PROFILES:
        raise ValueError(f"unknown posed-view source profile {source_profile!r}")
    if not isinstance(storage, _core.PoseStorage):
        raise TypeError(
            "posed-view storage must be sceneio._core.PoseStorage, "
            f"got {type(storage).__name__}"
        )
    normalized = convert_coordinates(storage, _CANONICAL_COORDINATES)
    quaternions = np.asarray(normalized.quaternions)
    translations = np.asarray(normalized.translations)
    poses = tuple(
        SE3.from_quaternion_wxyz(
            quaternion,
            translation,
            convention="opencv_cam2world",
        )
        for quaternion, translation in zip(quaternions, translations, strict=True)
    )
    count = len(poses)
    raw_names = tuple(normalized.names)
    names = (
        tuple(name if name else None for name in raw_names)
        if len(raw_names) == count
        else (None,) * count
    )
    raw_timestamps = np.asarray(normalized.timestamps)
    timestamps = (
        tuple(float(value) for value in raw_timestamps)
        if raw_timestamps.shape == (count,)
        else (None,) * count
    )
    camera_indices = np.asarray(normalized.camera_indices)
    cameras = tuple(normalized.cameras)
    calibrations: list[Calibration | None] = []
    for index in range(count):
        camera_index = int(camera_indices[index]) if camera_indices.shape == (count,) else -1
        calibrations.append(
            Calibration.from_intrinsics(cameras[camera_index])
            if 0 <= camera_index < len(cameras)
            else None
        )
    result = PosedViewSet(
        poses=poses,
        frame=FrameMeta(
            world_frame="arbitrary",
            scale="metric",
            scale_provenance="unknown",
        ),
        names=names,
        timestamps=timestamps,
        images=images,
        calibrations=tuple(calibrations),
    )
    object.__setattr__(result, "_source_storage", storage)
    object.__setattr__(result, "_source_profile", source_profile)
    object.__setattr__(result, "_source_signature", _semantic_signature(result))
    return result


def posed_view_reader(
    reader: Callable[[str], object],
    source_profile: str,
) -> Callable[[str], PosedViewSet]:
    """Wrap a native file reader with canonical pose normalization."""

    def read(path: str) -> PosedViewSet:
        return posed_views_from_storage(
            reader(path),
            source_profile=source_profile,
        )

    return read


def _require_absent(values: tuple[object | None, ...], field: str, profile: str) -> None:
    if any(value is not None for value in values):
        raise ContractViolation(f"{profile} cannot represent PosedViewSet.{field}")


def _camera_catalog(
    calibrations: tuple[Calibration | None, ...],
) -> tuple[list[object] | None, np.ndarray | None]:
    if not calibrations or all(value is None for value in calibrations):
        return None, None
    if any(value is None for value in calibrations):
        raise ContractViolation(
            "transforms_json requires calibrations to be either complete or absent"
        )
    cameras: list[object] = []
    indices = np.empty(len(calibrations), dtype=np.int32)
    catalog: dict[object, int] = {}
    for index, calibration in enumerate(calibrations):
        assert calibration is not None
        if calibration.intrinsics is None:
            raise ContractViolation("transforms_json cannot represent RayMap calibration")
        intrinsics = calibration.intrinsics
        key = (
            int(intrinsics.model_id),
            int(intrinsics.width),
            int(intrinsics.height),
            np.asarray(intrinsics.params).tobytes(order="C"),
        )
        camera_index = catalog.get(key)
        if camera_index is None:
            camera_index = len(cameras)
            catalog[key] = camera_index
            cameras.append(intrinsics)
        indices[index] = camera_index
    return cameras, indices


def posed_view_storage(value: object, *, profile: str) -> object:
    """Validate and lower a public pose set for one exact codec profile."""

    if profile not in _POSE_PROFILES:
        raise ValueError(f"unknown posed-view target profile {profile!r}")
    if not isinstance(value, PosedViewSet):
        raise TypeError(
            f"{profile} expects sceneio.PosedViewSet, got {type(value).__name__}"
        )
    if (
        value._source_profile == profile
        and value._source_storage is not None
        and value._source_signature == _semantic_signature(value)
    ):
        return value._source_storage
    if value.frame.world_frame != "arbitrary":
        raise ContractViolation(
            f"{profile} requires FrameMeta.world_frame='arbitrary'; "
            "re-anchor the poses explicitly first"
        )
    if value.frame.scale != "metric":
        raise ContractViolation(
            f"{profile} requires metric poses; an explicit scale conversion is required"
        )
    if value.frame.scale_provenance != "unknown":
        raise ContractViolation(
            f"{profile} cannot preserve FrameMeta.scale_provenance"
        )
    _require_absent(value.images, "images", profile)

    names: list[str] | None = None
    timestamps: np.ndarray | None = None
    cameras: list[object] | None = None
    camera_indices: np.ndarray | None = None
    target = _CANONICAL_COORDINATES
    if profile == "transforms_json":
        _require_absent(value.timestamps, "timestamps", profile)
        names = [name or "" for name in value.names]
        cameras, camera_indices = _camera_catalog(value.calibrations)
        target = _TRANSFORMS_JSON_COORDINATES
    elif profile == "tum":
        _require_absent(value.names, "names", profile)
        _require_absent(value.calibrations, "calibrations", profile)
        present = tuple(timestamp is not None for timestamp in value.timestamps)
        if any(present) and not all(present):
            raise ContractViolation(
                "tum requires timestamps to be either complete or absent"
            )
        if all(present) and present:
            timestamps = np.ascontiguousarray(value.timestamps, dtype=np.float64)
    else:
        _require_absent(value.names, "names", profile)
        _require_absent(value.timestamps, "timestamps", profile)
        _require_absent(value.calibrations, "calibrations", profile)

    quaternions = np.ascontiguousarray(
        [pose.to_quaternion_wxyz() for pose in value.poses],
        dtype=np.float64,
    ).reshape((-1, 4))
    translations = np.ascontiguousarray(
        [pose.translation for pose in value.poses],
        dtype=np.float64,
    ).reshape((-1, 3))
    storage = _core.pose_storage(
        quaternions,
        translations,
        names=names,
        timestamps=timestamps,
        quaternion_order="wxyz",
        pose_convention="camera_to_world",
        axis_frame="opencv",
        scale_to_meters=1.0,
        camera_indices=camera_indices,
        cameras=cameras,
    )
    return convert_coordinates(storage, target)


__all__: list[str] = []
