"""Typed records for repository-owned COLMAP ecosystem adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from sceneio import _core
from sceneio._camera_models import (
    CAMERA_MODEL_PARAMETER_COUNTS as _CAMERA_PARAMETER_COUNTS,
)
from sceneio._camera_models import (
    CAMERA_MODEL_PARAMETER_COUNTS_BY_NAME as _CAMERA_PARAMETER_COUNTS_BY_NAME,
)
from sceneio._data.features import CorrespondenceGraph

UINT32_MAX = 0xFFFFFFFF
UINT64_MAX = 0xFFFFFFFFFFFFFFFF
_VALIDATION_CHUNK = 65_536
_MAX_MEGALOC_VALUES = 1_000_000_000
_MAX_MEGALOC_RECORDS = 100_000_000


class ColmapAdapterError(ValueError):
    """A COLMAP ecosystem payload is malformed or cannot be represented."""


def _array(
    value,
    dtype,
    shape: tuple[int, ...],
    name: str,
    *,
    finite: bool = False,
) -> np.ndarray:
    result = np.asarray(value)
    expected = np.dtype(dtype)
    if result.dtype != expected or result.shape != shape:
        raise ColmapAdapterError(f"{name} must have dtype {expected} and shape {shape}")
    if not result.flags.c_contiguous:
        result = np.ascontiguousarray(result)
    if finite:
        flat = result.reshape(-1)
        for start in range(0, flat.size, _VALIDATION_CHUNK):
            if not bool(np.all(np.isfinite(flat[start : start + _VALIDATION_CHUNK]))):
                raise ColmapAdapterError(f"{name} must contain only finite values")
    result.setflags(write=False)
    return result


def _uint(value: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ColmapAdapterError(f"{name} must be an integer")
    if value < 0 or value > maximum:
        raise ColmapAdapterError(f"{name} is outside its unsigned wire domain")
    return value


def _nonempty_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ColmapAdapterError(f"{name} must be nonempty text")
    if "\x00" in value:
        raise ColmapAdapterError(f"{name} cannot contain NUL")
    return value


def _validate_metadata(value, name: str) -> None:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ColmapAdapterError(f"{name} object keys must be text")
        for child in value.values():
            _validate_metadata(child, name)
        return
    if isinstance(value, list):
        for child in value:
            _validate_metadata(child, name)
        return
    if value is None or isinstance(value, bool | int | str):
        return
    if isinstance(value, float) and np.isfinite(value):
        return
    raise ColmapAdapterError(f"{name} must contain finite JSON values")


@dataclass(frozen=True)
class MappingInput:
    """PCMAPIN aggregate composed only from canonical semantic records."""

    version: int
    cameras: Mapping[int, _core.CameraIntrinsics]
    camera_prior_focal_length: Mapping[int, bool]
    image_ids: Mapping[str, int]
    image_camera_ids: Mapping[str, int]
    image_time_ids: Mapping[str, int]
    correspondences: CorrespondenceGraph
    _owner: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.version not in (1, 2):
            raise ColmapAdapterError("MappingInput version must be 1 or 2")

        cameras = dict(self.cameras)
        for camera_id, intrinsics in cameras.items():
            _uint(camera_id, UINT32_MAX - 1, "camera_id")
            if camera_id == 0:
                raise ColmapAdapterError("camera_id must be positive")
            if not isinstance(intrinsics, _core.CameraIntrinsics):
                raise ColmapAdapterError("MappingInput cameras must be CameraIntrinsics")
        if len(cameras) != len(self.cameras):
            raise ColmapAdapterError("MappingInput camera ids must be unique")

        prior = dict(self.camera_prior_focal_length)
        if set(prior) != set(cameras) or any(not isinstance(value, bool) for value in prior.values()):
            raise ColmapAdapterError(
                "MappingInput camera prior flags must be boolean and align with cameras"
            )

        image_ids = dict(self.image_ids)
        if len(set(image_ids.values())) != len(image_ids):
            raise ColmapAdapterError("MappingInput image ids must be unique")
        for name, image_id in image_ids.items():
            _nonempty_text(name, "image name")
            _uint(image_id, UINT32_MAX - 1, "image_id")
            if image_id == 0:
                raise ColmapAdapterError("image_id must be positive")

        camera_refs = dict(self.image_camera_ids)
        time_ids = dict(self.image_time_ids)
        expected_names = set(image_ids)
        if set(camera_refs) != expected_names or set(time_ids) != expected_names:
            raise ColmapAdapterError("MappingInput image metadata must align by image name")
        for camera_id in camera_refs.values():
            _uint(camera_id, UINT32_MAX - 1, "image camera_id")
            if camera_id not in cameras:
                raise ColmapAdapterError(
                    "MappingInput images must reference a declared camera"
                )
        for time_id in time_ids.values():
            _uint(time_id, UINT32_MAX, "image time_id")

        if not isinstance(self.correspondences, CorrespondenceGraph):
            raise ColmapAdapterError(
                "MappingInput correspondences must be CorrespondenceGraph"
            )
        if set(self.correspondences.features) != expected_names:
            raise ColmapAdapterError(
                "MappingInput correspondence features must align with image metadata"
            )
        unordered_pairs = {
            frozenset(pair)
            for pair in self.correspondences.pairs
        }
        if len(unordered_pairs) != len(self.correspondences.pairs):
            raise ColmapAdapterError("MappingInput match pairs must be unique")
        if self.correspondences.index_validation != "eager":
            raise ColmapAdapterError(
                "MappingInput correspondences require eager feature-index validation"
            )

        object.__setattr__(self, "cameras", MappingProxyType(cameras))
        object.__setattr__(self, "camera_prior_focal_length", MappingProxyType(prior))
        object.__setattr__(self, "image_ids", MappingProxyType(image_ids))
        object.__setattr__(self, "image_camera_ids", MappingProxyType(camera_refs))
        object.__setattr__(self, "image_time_ids", MappingProxyType(time_ids))


@dataclass(frozen=True)
class SparseMarker:
    marker_id: int
    marker_type: int
    enabled: bool
    label: str
    world_position: np.ndarray
    world_covariance: np.ndarray
    point3D_id: int = UINT64_MAX

    def __post_init__(self) -> None:
        _uint(self.marker_id, UINT32_MAX - 1, "marker_id")
        if self.marker_type not in range(4):
            raise ColmapAdapterError("marker_type must be in 0..3")
        if not isinstance(self.enabled, bool):
            raise ColmapAdapterError("marker enabled must be boolean")
        _nonempty_text(self.label, "marker label")
        _uint(self.point3D_id, UINT64_MAX, "marker point3D_id")
        position = _array(
            self.world_position,
            np.float64,
            (3,),
            "marker world_position",
        )
        covariance = _array(
            self.world_covariance,
            np.float64,
            (3, 3),
            "marker world_covariance",
        )
        if not (bool(np.all(np.isfinite(position))) or bool(np.all(np.isnan(position)))):
            raise ColmapAdapterError("marker world_position must be fully finite or fully absent")
        if not (bool(np.all(np.isfinite(covariance))) or bool(np.all(np.isnan(covariance)))):
            raise ColmapAdapterError("marker covariance must be fully finite or fully absent")
        object.__setattr__(self, "world_position", position)
        object.__setattr__(self, "world_covariance", covariance)


@dataclass(frozen=True)
class SparseMarkerProjection:
    marker_id: int
    image_id: int
    xy: np.ndarray
    size: float
    pinned: bool
    point2D_idx: int = UINT32_MAX

    def __post_init__(self) -> None:
        _uint(self.marker_id, UINT32_MAX - 1, "projection marker_id")
        _uint(self.image_id, UINT32_MAX - 1, "projection image_id")
        _uint(self.point2D_idx, UINT32_MAX, "projection point2D_idx")
        object.__setattr__(
            self,
            "xy",
            _array(self.xy, np.float64, (2,), "projection xy", finite=True),
        )
        if not np.isfinite(self.size) or self.size < 0:
            raise ColmapAdapterError("projection size must be finite and non-negative")
        if not isinstance(self.pinned, bool):
            raise ColmapAdapterError("projection pinned must be boolean")


@dataclass(frozen=True)
class IdTags:
    ids: np.ndarray
    tags: np.ndarray

    def __post_init__(self) -> None:
        ids = np.asarray(self.ids)
        tags = np.asarray(self.tags)
        if ids.ndim != 1 or tags.shape != ids.shape:
            raise ColmapAdapterError("id tags must be parallel 1D arrays")
        object.__setattr__(self, "ids", _array(ids, np.uint64, ids.shape, "tag ids"))
        object.__setattr__(self, "tags", _array(tags, np.uint64, tags.shape, "tag values"))
        for start in range(0, tags.size, _VALIDATION_CHUNK):
            if bool(np.any(tags[start : start + _VALIDATION_CHUNK] >= UINT32_MAX)):
                raise ColmapAdapterError("tag values must be valid uint32 frame/time ids")
        if ids.size > 1:
            ordered_ids = np.sort(ids)
            for start in range(0, ordered_ids.size - 1, _VALIDATION_CHUNK):
                stop = min(start + _VALIDATION_CHUNK + 1, ordered_ids.size)
                if bool(np.any(ordered_ids[start : stop - 1] == ordered_ids[start + 1 : stop])):
                    raise ColmapAdapterError("tag ids must be unique")


@dataclass(frozen=True)
class TimeFrame:
    time_id: int
    timestamp_seconds: float
    sync_group: str
    label: str

    def __post_init__(self) -> None:
        _uint(self.time_id, UINT32_MAX - 1, "time_id")
        if not (np.isfinite(self.timestamp_seconds) or np.isnan(self.timestamp_seconds)):
            raise ColmapAdapterError("timestamp must be finite or NaN")
        if "\x00" in self.sync_group or "\x00" in self.label:
            raise ColmapAdapterError("time-frame text cannot contain NUL")


@dataclass(frozen=True)
class CharucoBoard:
    board_id: str
    dictionary: int
    squares_x: int
    squares_y: int
    square_length: float
    marker_length: float

    def __post_init__(self) -> None:
        _nonempty_text(self.board_id, "board_id")
        if self.dictionary not in range(20):
            raise ColmapAdapterError("ChArUco dictionary must be in 0..19")
        if self.squares_x < 2 or self.squares_y < 2:
            raise ColmapAdapterError("ChArUco board dimensions must each be at least 2")
        if (
            not np.isfinite(self.square_length)
            or not np.isfinite(self.marker_length)
            or self.marker_length <= 0
            or self.square_length <= self.marker_length
        ):
            raise ColmapAdapterError("ChArUco lengths require square_length > marker_length > 0")


@dataclass(frozen=True)
class CharucoCalibration:
    session_id: str
    board: CharucoBoard
    camera_model_id: int
    image_width: int
    image_height: int
    camera_params: np.ndarray
    overall_rmse_px: float
    image_names: tuple[str, ...]
    per_image_rmse_px: np.ndarray
    per_image_cam_from_board: np.ndarray

    def __post_init__(self) -> None:
        _nonempty_text(self.session_id, "session_id")
        if self.camera_model_id not in range(18):
            raise ColmapAdapterError("camera_model_id must be in 0..17")
        if self.image_width <= 0 or self.image_height <= 0:
            raise ColmapAdapterError("calibration image dimensions must be positive")
        params = np.asarray(self.camera_params)
        object.__setattr__(
            self,
            "camera_params",
            _array(
                params,
                np.float64,
                (params.size,),
                "calibration camera_params",
                finite=True,
            ),
        )
        if params.size != _CAMERA_PARAMETER_COUNTS[self.camera_model_id]:
            raise ColmapAdapterError("calibration camera model/parameter count disagrees")
        if not np.isfinite(self.overall_rmse_px) or self.overall_rmse_px < 0:
            raise ColmapAdapterError("overall calibration RMSE must be finite and non-negative")
        if any(not name or "\x00" in name for name in self.image_names):
            raise ColmapAdapterError("calibration image names must be nonempty and NUL-free")
        count = len(self.image_names)
        object.__setattr__(
            self,
            "per_image_rmse_px",
            _array(
                self.per_image_rmse_px,
                np.float64,
                (count,),
                "per-image RMSE",
                finite=True,
            ),
        )
        object.__setattr__(
            self,
            "per_image_cam_from_board",
            _array(
                self.per_image_cam_from_board,
                np.float64,
                (count, 7),
                "per-image camera poses",
                finite=True,
            ),
        )
        if bool(np.any(self.per_image_rmse_px < 0)):
            raise ColmapAdapterError("per-image RMSE cannot be negative")
        for start in range(0, count, _VALIDATION_CHUNK):
            quaternions = self.per_image_cam_from_board[
                start : start + _VALIDATION_CHUNK,
                :4,
            ]
            norms = np.linalg.norm(quaternions, axis=1)
            if bool(np.any(np.abs(norms - 1.0) > 1e-10)):
                raise ColmapAdapterError("per-image camera pose quaternions must be unit length")


@dataclass(frozen=True)
class SparseExtensions:
    markers: tuple[SparseMarker, ...] | None = None
    marker_projections: tuple[SparseMarkerProjection, ...] | None = None
    charuco_boards: tuple[CharucoBoard, ...] | None = None
    charuco_calibrations: tuple[CharucoCalibration, ...] | None = None
    time_frames: tuple[TimeFrame, ...] | None = None
    image_times: IdTags | None = None
    point3D_frames: IdTags | None = None

    def __post_init__(self) -> None:
        markers = self.markers or ()
        projections = self.marker_projections or ()
        marker_ids = {item.marker_id for item in markers}
        if len(marker_ids) != len(markers):
            raise ColmapAdapterError("marker ids must be unique")
        if len({item.label for item in markers}) != len(markers):
            raise ColmapAdapterError("marker labels must be unique")
        if any(item.marker_id not in marker_ids for item in projections):
            raise ColmapAdapterError("marker projections must reference declared markers")
        if len({(item.marker_id, item.image_id) for item in projections}) != len(projections):
            raise ColmapAdapterError("marker projection (marker,image) keys must be unique")
        boards = self.charuco_boards or ()
        if len({item.board_id for item in boards}) != len(boards):
            raise ColmapAdapterError("ChArUco board ids must be unique")
        calibrations = self.charuco_calibrations or ()
        if len({item.session_id for item in calibrations}) != len(calibrations):
            raise ColmapAdapterError("ChArUco calibration session ids must be unique")
        boards_by_id = {item.board_id: item for item in boards}
        if any(
            calibration.board.board_id in boards_by_id
            and calibration.board != boards_by_id[calibration.board.board_id]
            for calibration in calibrations
        ):
            raise ColmapAdapterError(
                "ChArUco calibration board geometry disagrees with the board table"
            )
        times = self.time_frames or ()
        if len({item.time_id for item in times}) != len(times):
            raise ColmapAdapterError("time-frame ids must be unique")


@dataclass(frozen=True)
class ExtendedSparseModel:
    reconstruction: Any
    extensions: SparseExtensions
    encoding: str

    def __post_init__(self) -> None:
        if self.encoding not in ("binary", "text"):
            raise ColmapAdapterError("sparse encoding must be binary or text")


@dataclass(frozen=True)
class MegaLocImage:
    image_id: int
    image_name: str
    image_path: str

    def __post_init__(self) -> None:
        _uint(self.image_id, UINT32_MAX - 1, "MegaLoc image_id")
        _nonempty_text(self.image_name, "MegaLoc image_name")
        _nonempty_text(self.image_path, "MegaLoc image_path")
        if any(char.isspace() for char in self.image_name):
            raise ColmapAdapterError("MegaLoc image names cannot contain whitespace")


@dataclass(frozen=True)
class MegaLocPair:
    image_id1: int
    image_id2: int
    score: float
    is_retrieval: bool
    is_sequential: bool
    image_name1: str
    image_name2: str

    def __post_init__(self) -> None:
        _uint(self.image_id1, UINT32_MAX - 1, "MegaLoc pair image_id1")
        _uint(self.image_id2, UINT32_MAX - 1, "MegaLoc pair image_id2")
        if self.image_id1 == self.image_id2:
            raise ColmapAdapterError("MegaLoc pair must use two images")
        with np.errstate(over="ignore", invalid="ignore"):
            canonical_score = np.float32(self.score).item()
        if np.isinf(canonical_score):
            raise ColmapAdapterError("MegaLoc pair score must be finite-float32 or NaN")
        object.__setattr__(self, "score", canonical_score)
        if not isinstance(self.is_retrieval, bool) or not isinstance(self.is_sequential, bool):
            raise ColmapAdapterError("MegaLoc pair flags must be boolean")
        _nonempty_text(self.image_name1, "MegaLoc pair image_name1")
        _nonempty_text(self.image_name2, "MegaLoc pair image_name2")
        if any(char.isspace() for name in (self.image_name1, self.image_name2) for char in name):
            raise ColmapAdapterError("MegaLoc pair image names cannot contain whitespace")


@dataclass(frozen=True)
class MegaLocArtifacts:
    root: Path
    images: tuple[MegaLocImage, ...]
    pairs: tuple[MegaLocPair, ...]
    descriptors: np.ndarray | None
    descriptors_normalized: bool
    metadata: Mapping[str, Any]
    image_root: str | None = None
    model_onnx_path: str | None = None
    model_engine_path: str | None = None
    _owner: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.images) > _MAX_MEGALOC_RECORDS or len(self.pairs) > _MAX_MEGALOC_RECORDS:
            raise ColmapAdapterError("MegaLoc record count exceeds its bound")
        if len({item.image_id for item in self.images}) != len(self.images):
            raise ColmapAdapterError("MegaLoc image ids must be unique")
        if len({item.image_name for item in self.images}) != len(self.images):
            raise ColmapAdapterError("MegaLoc image names must be unique")
        pair_keys = {
            (min(item.image_id1, item.image_id2), max(item.image_id1, item.image_id2))
            for item in self.pairs
        }
        if len(pair_keys) != len(self.pairs):
            raise ColmapAdapterError("MegaLoc image pairs must be unique")
        if self.descriptors is not None:
            descriptors = np.asarray(self.descriptors)
            if descriptors.ndim != 2 or descriptors.shape[0] != len(self.images):
                raise ColmapAdapterError("MegaLoc descriptors must have one row per image")
            if descriptors.shape[1] > _MAX_MEGALOC_VALUES or descriptors.size > _MAX_MEGALOC_VALUES:
                raise ColmapAdapterError("MegaLoc descriptor dimensions are outside bounds")
            object.__setattr__(
                self,
                "descriptors",
                _array(
                    descriptors,
                    np.float32,
                    descriptors.shape,
                    "MegaLoc descriptors",
                ),
            )
        if not isinstance(self.descriptors_normalized, bool):
            raise ColmapAdapterError("descriptors_normalized must be boolean")
        for name, value in (
            ("image_root", self.image_root),
            ("model_onnx_path", self.model_onnx_path),
            ("model_engine_path", self.model_engine_path),
        ):
            if value is not None and not isinstance(value, str):
                raise ColmapAdapterError(f"MegaLoc {name} must be text or null")
        metadata = dict(self.metadata)
        _validate_metadata(metadata, "MegaLoc metadata")
        object.__setattr__(self, "metadata", MappingProxyType(metadata))


@dataclass(frozen=True)
class RigConfigCamera:
    image_prefix: str
    ref_sensor: bool = False
    cam_from_rig: np.ndarray | None = None
    camera_model_name: str | None = None
    camera_params: np.ndarray | None = None

    def __post_init__(self) -> None:
        _nonempty_text(self.image_prefix, "rig image_prefix")
        if not isinstance(self.ref_sensor, bool):
            raise ColmapAdapterError("rig ref_sensor must be boolean")
        if self.cam_from_rig is not None:
            if self.ref_sensor:
                raise ColmapAdapterError("the rig reference sensor cannot have cam_from_rig")
            pose = _array(
                self.cam_from_rig,
                np.float64,
                (7,),
                "rig cam_from_rig",
                finite=True,
            )
            norm = float(np.linalg.norm(pose[:4]))
            if not np.isfinite(norm) or abs(norm - 1.0) > 1e-10:
                raise ColmapAdapterError("rig cam_from_rig quaternion must be unit length")
            object.__setattr__(self, "cam_from_rig", pose)
        if (self.camera_model_name is None) != (self.camera_params is None):
            raise ColmapAdapterError("rig camera model and parameters must occur together")
        if self.camera_model_name is not None:
            _nonempty_text(self.camera_model_name, "rig camera model")
            params = np.asarray(self.camera_params)
            expected = _CAMERA_PARAMETER_COUNTS_BY_NAME.get(self.camera_model_name)
            if expected is None or params.size != expected:
                raise ColmapAdapterError("rig camera model/parameter count disagrees")
            object.__setattr__(
                self,
                "camera_params",
                _array(
                    params,
                    np.float64,
                    (params.size,),
                    "rig camera params",
                    finite=True,
                ),
            )


@dataclass(frozen=True)
class RigConfiguration:
    cameras: tuple[RigConfigCamera, ...]

    def __post_init__(self) -> None:
        if not self.cameras:
            raise ColmapAdapterError("a rig must contain at least one camera")
        if sum(camera.ref_sensor for camera in self.cameras) != 1:
            raise ColmapAdapterError("a rig must have exactly one reference sensor")
        if len({camera.image_prefix for camera in self.cameras}) != len(self.cameras):
            raise ColmapAdapterError("rig image prefixes must be unique")
