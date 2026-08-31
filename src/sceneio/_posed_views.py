"""Private translation between canonical posed views and codec storage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np

from sceneio import _core
from sceneio._data.calibration import Calibration
from sceneio._data.transforms import _se3_batch_from_quaternion_wxyz
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


def _semantic_signature(
    value: PosedViewSet,
    *,
    rotations: np.ndarray | None = None,
    translations: np.ndarray | None = None,
    calibration_catalog: tuple[Calibration, ...] | None = None,
    calibration_indices: np.ndarray | None = None,
) -> object:
    if rotations is None:
        rotations = np.asarray(
            [pose.rotation for pose in value.poses],
            dtype=np.float64,
        ).reshape((-1, 3, 3))
    if translations is None:
        translations = np.asarray(
            [pose.translation for pose in value.poses],
            dtype=np.float64,
        ).reshape((-1, 3))
    count = len(value.poses)
    if rotations.shape != (count, 3, 3) or translations.shape != (count, 3):
        raise ValueError("posed-view signature arrays are not index-aligned")

    if (calibration_catalog is None) != (calibration_indices is None):
        raise ValueError(
            "posed-view calibration catalog and indices must be provided together"
        )
    if calibration_catalog is not None and calibration_indices is not None:
        source_indices = np.asarray(calibration_indices, dtype=np.int32)
        if source_indices.shape != (count,):
            raise ValueError("posed-view calibration indices are not index-aligned")
        catalog: list[object] = []
        catalog_by_signature: dict[object, int] = {}
        source_to_canonical = np.empty(len(calibration_catalog), dtype=np.int32)
        for source_index, calibration in enumerate(calibration_catalog):
            calibration_signature = _calibration_signature(calibration)
            catalog_index = catalog_by_signature.get(calibration_signature)
            if catalog_index is None:
                catalog_index = len(catalog)
                catalog_by_signature[calibration_signature] = catalog_index
                catalog.append(calibration_signature)
            source_to_canonical[source_index] = catalog_index
        signature_indices = np.full(count, -1, dtype=np.int32)
        valid = (source_indices >= 0) & (source_indices < len(calibration_catalog))
        signature_indices[valid] = source_to_canonical[source_indices[valid]]
        catalog_signatures = tuple(catalog)
    else:
        catalog: list[object] = []
        catalog_by_signature: dict[object, int] = {}
        signature_indices = np.full(count, -1, dtype=np.int32)
        calibration_cache: dict[int, object] = {}
        for index, calibration in enumerate(value.calibrations):
            if calibration is None:
                continue
            key = id(calibration)
            signature = calibration_cache.get(key)
            if signature is None:
                signature = _calibration_signature(calibration)
                calibration_cache[key] = signature
            catalog_index = catalog_by_signature.get(signature)
            if catalog_index is None:
                catalog_index = len(catalog)
                catalog_by_signature[signature] = catalog_index
                catalog.append(signature)
            signature_indices[index] = catalog_index
        catalog_signatures = tuple(catalog)
    return (
        (
            count,
            "opencv_cam2world",
            rotations.tobytes(order="C"),
            translations.tobytes(order="C"),
        ),
        (
            value.frame.world_frame,
            value.frame.scale,
            value.frame.scale_provenance,
        ),
        value.names,
        value.timestamps,
        bytes(image is not None for image in value.images),
        (catalog_signatures, signature_indices.tobytes(order="C")),
    )


def _matches_semantic_signature(value: PosedViewSet, signature: object) -> bool:
    """Compare a pose set with its exact snapshot using bounded scratch memory."""

    if not isinstance(signature, tuple) or len(signature) != 6:
        return False
    (
        pose_signature,
        frame_signature,
        names,
        timestamps,
        image_presence,
        calibration_signature,
    ) = signature
    if not isinstance(pose_signature, tuple) or len(pose_signature) != 4:
        return False
    expected_count, expected_convention, rotation_bytes, translation_bytes = (
        pose_signature
    )
    count = len(value.poses)
    if (
        expected_count != count
        or len(rotation_bytes) != count * 9 * np.dtype(np.float64).itemsize
        or len(translation_bytes) != count * 3 * np.dtype(np.float64).itemsize
        or frame_signature
        != (
            value.frame.world_frame,
            value.frame.scale,
            value.frame.scale_provenance,
        )
        or names != value.names
        or timestamps != value.timestamps
        or len(image_presence) != count
        or not isinstance(calibration_signature, tuple)
        or len(calibration_signature) != 2
    ):
        return False

    calibration_catalog, calibration_index_bytes = calibration_signature
    if len(calibration_index_bytes) != count * np.dtype(np.int32).itemsize:
        return False
    expected_calibration_indices = np.frombuffer(
        calibration_index_bytes,
        dtype=np.int32,
    )
    calibration_index_by_signature = {
        item: index for index, item in enumerate(calibration_catalog)
    }
    rotation_view = memoryview(rotation_bytes)
    translation_view = memoryview(translation_bytes)
    rotation_stride = 9 * np.dtype(np.float64).itemsize
    translation_stride = 3 * np.dtype(np.float64).itemsize
    calibration_cache: dict[int, object] = {}
    for index, pose in enumerate(value.poses):
        if pose.convention != expected_convention:
            return False
        rotation_start = index * rotation_stride
        translation_start = index * translation_stride
        if pose.rotation.tobytes(order="C") != rotation_view[
            rotation_start : rotation_start + rotation_stride
        ]:
            return False
        if pose.translation.tobytes(order="C") != translation_view[
            translation_start : translation_start + translation_stride
        ]:
            return False
        if (value.images[index] is not None) != bool(image_presence[index]):
            return False
        calibration = value.calibrations[index]
        if calibration is None:
            current_calibration_index = -1
        else:
            key = id(calibration)
            current_calibration_signature = calibration_cache.get(key)
            if current_calibration_signature is None:
                current_calibration_signature = _calibration_signature(calibration)
                calibration_cache[key] = current_calibration_signature
            current_calibration_index = calibration_index_by_signature.get(
                current_calibration_signature,
                -2,
            )
        if current_calibration_index != int(expected_calibration_indices[index]):
            return False
    return True


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
    poses, rotations, translations = _se3_batch_from_quaternion_wxyz(
        quaternions,
        translations,
        convention="opencv_cam2world",
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
    calibration_catalog = tuple(
        Calibration.from_intrinsics(camera) for camera in cameras
    )
    calibrations = tuple(
        calibration_catalog[camera_index]
        if 0 <= camera_index < len(calibration_catalog)
        else None
        for camera_index in (
            camera_indices.astype(np.intp, copy=False)
            if camera_indices.shape == (count,)
            else np.full(count, -1, dtype=np.intp)
        )
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
        calibrations=calibrations,
    )
    object.__setattr__(result, "_source_storage", storage)
    object.__setattr__(result, "_source_profile", source_profile)
    aligned_camera_indices = (
        camera_indices
        if camera_indices.shape == (count,)
        else np.full(count, -1, dtype=np.int32)
    )
    signature_indices = np.where(
        (aligned_camera_indices >= 0)
        & (aligned_camera_indices < len(calibration_catalog)),
        aligned_camera_indices,
        -1,
    ).astype(np.int32, copy=False)
    object.__setattr__(
        result,
        "_source_signature",
        _semantic_signature(
            result,
            rotations=rotations,
            translations=translations,
            calibration_catalog=calibration_catalog,
            calibration_indices=signature_indices,
        ),
    )
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
        and _matches_semantic_signature(value, value._source_signature)
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
