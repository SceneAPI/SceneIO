"""Explicit adapters between loaded native records and neutral contracts.

SceneIO intentionally keeps two layers:

* compiled records preserve what a file or database represented;
* :mod:`sceneio.data` records are the small, backend-neutral procedure floor.

The functions in this module are the only general bridge between those roles.
They preserve the shared semantic subset, reject unrepresentable meaning, and
require ``allow_loss=True`` before discarding storage-only metadata.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Literal

import numpy as np

from sceneio import _core
from sceneio.coordinate_conversion import convert_coordinates
from sceneio.coordinates import COLMAP_COORDINATES
from sceneio.data import (
    SE3,
    Calibration,
    CameraIntrinsics,
    CameraModel,
    CorrespondenceGraph,
    FrameMeta,
    PairCorrespondences,
    TwoViewGeometry,
    ViewInput,
)
from sceneio.data import (
    DepthMap as NeutralDepthMap,
)
from sceneio.data import (
    FeatureSet as NeutralFeatureSet,
)
from sceneio.data import (
    PosedViewSet as NeutralPosedViewSet,
)
from sceneio.errors import ContractViolation

MatchChannel = Literal["raw", "verified"]

_NATIVE_DESCRIPTOR_DTYPES = frozenset(
    np.dtype(dtype) for dtype in (np.uint8, np.int8, np.float16, np.float32, np.float64)
)


def _refuse_loss(kind: str, losses: Sequence[str], allow_loss: bool) -> None:
    unique = tuple(dict.fromkeys(losses))
    if unique and not allow_loss:
        raise ContractViolation(
            f"{kind} projection cannot preserve {', '.join(unique)}; "
            "pass allow_loss=True to acknowledge that metadata loss"
        )


def _native(value: object, expected: type[object], name: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(f"{name} expects {expected.__name__}, got {type(value).__name__}")


def _positive_scale(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ContractViolation(f"{name} must be finite and positive")
    return float(value)


def _match_channel(value: object) -> MatchChannel:
    if value == "raw":
        return "raw"
    if value == "verified":
        return "verified"
    raise ValueError("channel must be 'raw' or 'verified'")


def camera_intrinsics_from_native(value: object) -> CameraIntrinsics:
    """Project a native :class:`sceneio.Camera` to neutral intrinsics.

    ``Camera.id`` is contextual collection identity, not part of an intrinsic
    calibration, so it is intentionally outside this function's result.
    """

    _native(value, _core.Camera, "camera_intrinsics_from_native")
    try:
        model = CameraModel.from_id(value.model_id)
    except ValueError as exc:
        raise ContractViolation(str(exc)) from exc
    return CameraIntrinsics(
        model=model,
        width=int(value.width),
        height=int(value.height),
        params=np.array(value.params, dtype=np.float64, copy=True, order="C"),
    )


def camera_from_neutral(value: CameraIntrinsics, *, camera_id: int) -> object:
    """Build a native :class:`sceneio.Camera` from neutral intrinsics."""

    if not isinstance(value, CameraIntrinsics):
        raise TypeError(
            f"camera_from_neutral expects sceneio.data.CameraIntrinsics, got {type(value).__name__}"
        )
    try:
        selected_id = operator.index(camera_id)
    except TypeError:
        raise TypeError("camera_from_neutral.camera_id must be an integer") from None
    if selected_id < 0 or selected_id >= np.iinfo(np.uint32).max:
        raise ContractViolation(
            "camera_from_neutral.camera_id must fit uint32 and not be UINT32_MAX"
        )
    return _core.camera(
        selected_id,
        value.model.model_id,
        value.width,
        value.height,
        np.ascontiguousarray(value.params),
    )


def _feature_metadata_losses(value: object) -> list[str]:
    losses: list[str] = []
    if int(value.image_id) != 0:
        losses.append("image_id")
    if str(value.image_name) != "image":
        losses.append("image_name")
    if int(value.camera_id) != 0:
        losses.append("camera_id")
    if tuple(value.image_size) != (1, 1):
        losses.append("image_size")
    if value.time_id is not None:
        losses.append("time_id")
    if int(value.extractor_type) != -1:
        losses.append("extractor_type")
    if value.extractor_type_name is not None:
        losses.append("extractor_type_name")
    if bool(value.descriptor_dtype_present):
        losses.append("descriptor_dtype presence")
    if bool(value.descriptor_dim_present):
        losses.append("descriptor_dim presence")
    if value.keypoint_colors is not None:
        losses.append("keypoint_colors")
    if value.quality is not None:
        losses.append("quality")
    if not bool(value.keypoints_present):
        losses.append("keypoints presence")
    if int(value.keypoint_columns) != 2:
        losses.append("keypoint scale/orientation/affine columns")
    return losses


def feature_set_from_native(
    value: object,
    *,
    allow_loss: bool = False,
) -> NeutralFeatureSet:
    """Project a storage-faithful native feature record to neutral features."""

    _native(value, _core.FeatureSet, "feature_set_from_native")
    _refuse_loss("FeatureSet", _feature_metadata_losses(value), allow_loss)
    keypoints = np.asarray(value.keypoints)[:, :2]
    if int(value.keypoint_columns) != 2:
        keypoints = np.ascontiguousarray(keypoints)
    descriptors = value.descriptors
    scores = value.scores
    return NeutralFeatureSet(
        keypoints=keypoints,
        descriptors=None if descriptors is None else np.asarray(descriptors),
        scores=None if scores is None else np.asarray(scores),
        pixel_center=tuple(float(item) for item in value.pixel_center),
    )


def feature_set_from_neutral(
    value: NeutralFeatureSet,
    *,
    image_id: int = 0,
    image_name: str = "image",
    camera_id: int = 0,
    image_size: tuple[int, int] = (1, 1),
    extractor_type: int = -1,
    time_id: int | None = None,
    keypoints_present: bool = True,
) -> object:
    """Materialize neutral features as a native storage record.

    The optional arguments supply collection metadata absent from the neutral
    per-image payload.  Descriptor values are never silently cast.
    """

    if not isinstance(value, NeutralFeatureSet):
        raise TypeError(
            f"feature_set_from_neutral expects sceneio.data.FeatureSet, got {type(value).__name__}"
        )
    descriptors = value.descriptors
    if descriptors is not None:
        if descriptors.dtype not in _NATIVE_DESCRIPTOR_DTYPES:
            raise ContractViolation(
                "native FeatureSet descriptors require uint8, int8, float16, "
                f"float32, or float64; got {descriptors.dtype.name}"
            )
        descriptors = np.ascontiguousarray(descriptors)
    return _core.feature_set(
        np.ascontiguousarray(value.keypoints),
        descriptors,
        None if value.scores is None else np.ascontiguousarray(value.scores),
        image_id=image_id,
        image_name=image_name,
        camera_id=camera_id,
        image_size=image_size,
        extractor_type=extractor_type,
        time_id=time_id,
        keypoints_present=keypoints_present,
        pixel_center=value.pixel_center,
    )


def _image_name_map(value: Mapping[int, str] | Sequence[str]) -> dict[int, str]:
    if isinstance(value, Mapping):
        items = value.items()
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        items = enumerate(value, start=1)
    else:
        raise TypeError("image_names must be an integer-to-name mapping or ordered name sequence")
    result: dict[int, str] = {}
    for raw_id, name in items:
        try:
            image_id = operator.index(raw_id)
        except TypeError:
            raise TypeError(f"image id {raw_id!r} is not an integer") from None
        if image_id < 0 or not isinstance(name, str) or not name:
            raise ContractViolation("image_names requires non-negative ids and nonempty names")
        if image_id in result or name in result.values():
            raise ContractViolation("image_names ids and names must both be unique")
        result[image_id] = name
    return result


def _image_id_map(value: Mapping[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, raw_id in dict(value).items():
        if not isinstance(name, str) or not name:
            raise ContractViolation("image_ids requires nonempty image-name keys")
        try:
            image_id = operator.index(raw_id)
        except TypeError:
            raise TypeError(f"image id for {name!r} is not an integer") from None
        if image_id < 0 or image_id >= 2_147_483_647:
            raise ContractViolation("native match image ids must be in [0, 2147483647)")
        result[name] = image_id
    if len(set(result.values())) != len(result):
        raise ContractViolation("image_ids values must be unique")
    return result


def _optional_matrix_channel(
    values: Sequence[np.ndarray | None],
) -> tuple[np.ndarray | None, np.ndarray]:
    """Pack optional 3x3 matrices into native values plus a presence mask."""

    present = np.fromiter(
        (value is not None for value in values),
        dtype=np.uint8,
        count=len(values),
    )
    if not bool(present.any()):
        return None, present
    rows = (np.zeros((3, 3), dtype=np.float64) if value is None else value for value in values)
    return np.ascontiguousarray(tuple(rows), dtype=np.float64), present


def _graph_metadata_losses(value: object, channel: MatchChannel) -> list[str]:
    losses: list[str] = []
    if channel == "raw" and int(value.num_verified_matches):
        losses.append("verified correspondences")
    if channel == "verified" and int(value.num_matches):
        losses.append("raw correspondences")
    if np.any(np.asarray(value.configs) != 0):
        losses.append("two-view configuration codes")
    if np.any(np.asarray(value.pose_present)):
        losses.append("relative poses")
    if np.any(np.asarray(value.camera1_present)) or np.any(np.asarray(value.camera2_present)):
        losses.append("recovered endpoint cameras")
    if np.any(np.asarray(value.camera1_prior_focal_length)) or np.any(
        np.asarray(value.camera2_prior_focal_length)
    ):
        losses.append("endpoint focal-length-prior flags")
    if np.any(np.asarray(value.provenance_present)):
        losses.append("match provenance")
    if np.any(np.asarray(value.retrieval_score_present)):
        losses.append("retrieval scores")
    selected_presence = value.match_present if channel == "raw" else value.geometry_present
    if np.any(np.asarray(selected_presence) == 0):
        losses.append("absent-versus-empty match rows")
    return losses


def correspondence_graph_from_native(
    value: object,
    features: Mapping[str, object],
    *,
    image_names: Mapping[int, str] | Sequence[str],
    channel: MatchChannel = "raw",
    allow_loss: bool = False,
) -> CorrespondenceGraph:
    """Project one native match channel and its features to a neutral graph.

    A sequence ``image_names`` uses COLMAP/HLoc ids ``1..N``.  A mapping is
    required for sparse or otherwise non-positional ids.
    """

    _native(value, _core.MatchGraph, "correspondence_graph_from_native")
    channel = _match_channel(channel)
    names = _image_name_map(image_names)
    _refuse_loss("MatchGraph", _graph_metadata_losses(value, channel), allow_loss)

    neutral_features: dict[str, NeutralFeatureSet] = {}
    for name, feature in dict(features).items():
        if not isinstance(name, str) or not name:
            raise ContractViolation("features must use nonempty image-name keys")
        if isinstance(feature, NeutralFeatureSet):
            neutral_features[name] = feature
        elif isinstance(feature, _core.FeatureSet):
            neutral_features[name] = feature_set_from_native(feature, allow_loss=allow_loss)
        else:
            raise TypeError(
                f"feature {name!r} must be native or neutral FeatureSet, "
                f"got {type(feature).__name__}"
            )

    pairs: dict[tuple[str, str], PairCorrespondences] = {}
    image_pairs = np.asarray(value.image_pairs)
    if channel == "raw":
        offsets = np.asarray(value.match_offsets)
        all_matches = np.asarray(value.matches)
        all_scores = None if value.scores is None else np.asarray(value.scores)
    else:
        offsets = np.asarray(value.verified_offsets)
        all_matches = np.asarray(value.verified_matches)
        all_scores = None
    verified_offsets = np.asarray(value.verified_offsets)
    geometry_present = np.asarray(value.geometry_present)
    score_present = np.asarray(value.match_score_present)
    f_present = np.asarray(value.F_present)
    e_present = np.asarray(value.E_present)
    h_present = np.asarray(value.H_present)
    fundamental = np.asarray(value.fundamental_matrices)
    essential = np.asarray(value.essential_matrices)
    homographies = np.asarray(value.homographies)

    for index, pair_ids in enumerate(image_pairs):
        id_a, id_b = int(pair_ids[0]), int(pair_ids[1])
        if id_a not in names or id_b not in names:
            raise ContractViolation(f"MatchGraph pair ({id_a}, {id_b}) has no image_names entry")
        key = (names[id_a], names[id_b])
        if key in pairs:
            raise ContractViolation(f"MatchGraph contains duplicate neutral pair {key!r}")
        start, stop = int(offsets[index]), int(offsets[index + 1])
        geometry = None
        if bool(geometry_present[index]):
            geometry = TwoViewGeometry(
                E=essential[index] if bool(e_present[index]) else None,
                F=fundamental[index] if bool(f_present[index]) else None,
                H=homographies[index] if bool(h_present[index]) else None,
                num_inliers=int(verified_offsets[index + 1] - verified_offsets[index]),
            )
        scores = None
        if channel == "raw" and all_scores is not None and bool(score_present[index]):
            scores = all_scores[start:stop]
        pairs[key] = PairCorrespondences.from_indices(
            all_matches[start:stop],
            scores=scores,
            geometry=geometry,
        )
    return CorrespondenceGraph(neutral_features, pairs)


def match_graph_from_neutral(
    value: CorrespondenceGraph,
    *,
    image_ids: Mapping[str, int],
    channel: MatchChannel = "raw",
    allow_loss: bool = False,
) -> object:
    """Materialize one neutral correspondence channel as a native graph."""

    if not isinstance(value, CorrespondenceGraph):
        raise TypeError(
            "match_graph_from_neutral expects sceneio.data.CorrespondenceGraph, "
            f"got {type(value).__name__}"
        )
    channel = _match_channel(channel)
    ids = _image_id_map(image_ids)

    image_pair_rows: list[tuple[int, int]] = []
    selected_rows: list[np.ndarray] = []
    selected_offsets = [0]
    score_rows: list[np.ndarray] = []
    score_flags: list[int] = []
    f_values: list[np.ndarray | None] = []
    e_values: list[np.ndarray | None] = []
    h_values: list[np.ndarray | None] = []
    geometry_flags: list[int] = []
    losses: list[str] = []

    for key, pair in value.pairs.items():
        name_a, name_b = key
        if name_a not in ids or name_b not in ids:
            raise ContractViolation(f"neutral pair {key!r} has no image_ids entry")
        id_a, id_b = ids[name_a], ids[name_b]
        if id_a >= id_b:
            raise ContractViolation(
                f"native pair ids must increase in neutral pair order; {key!r} maps to "
                f"({id_a}, {id_b})"
            )
        if pair.mode != "indexed":
            raise ContractViolation("native MatchGraph cannot represent coordinate-mode pairs")
        assert pair.indices is not None
        indices = np.asarray(pair.indices)
        if indices.size and int(indices.max()) > np.iinfo(np.uint32).max:
            raise ContractViolation("native match indices must fit uint32")
        indices = np.ascontiguousarray(indices, dtype=np.uint32)
        image_pair_rows.append((id_a, id_b))
        selected_rows.append(indices)
        selected_offsets.append(selected_offsets[-1] + len(indices))

        if channel == "verified" and pair.scores is not None:
            losses.append(f"scores for verified pair {key!r}")
        score_flags.append(int(channel == "raw" and pair.scores is not None))
        if channel == "raw":
            score_rows.append(
                np.zeros(len(indices), dtype=np.float32)
                if pair.scores is None
                else np.ascontiguousarray(pair.scores)
            )

        geometry = pair.geometry
        if (
            geometry is not None
            and geometry.num_inliers is not None
            and (channel == "raw" or geometry.num_inliers != len(pair))
        ):
            losses.append(f"explicit num_inliers for pair {key!r}")
        f_value = None if geometry is None else geometry.F
        e_value = None if geometry is None else geometry.E
        h_value = None if geometry is None else geometry.H
        f_values.append(f_value)
        e_values.append(e_value)
        h_values.append(h_value)
        geometry_flags.append(int(channel == "verified" or geometry is not None))

    _refuse_loss("CorrespondenceGraph", losses, allow_loss)
    pair_count = len(image_pair_rows)
    empty_matches = np.empty((0, 2), dtype=np.uint32)
    selected = np.concatenate(selected_rows, axis=0) if selected_rows else empty_matches
    selected_offset_array = np.asarray(selected_offsets, dtype=np.uint64)
    zero_offsets = np.zeros(pair_count + 1, dtype=np.uint64)
    raw_matches = selected if channel == "raw" else empty_matches
    verified_matches = selected if channel == "verified" else empty_matches
    raw_offsets = selected_offset_array if channel == "raw" else zero_offsets
    verified_offsets = selected_offset_array if channel == "verified" else zero_offsets
    any_scores = channel == "raw" and any(score_flags)
    scores = np.concatenate(score_rows) if any_scores and score_rows else None
    image_pairs = np.asarray(image_pair_rows, dtype=np.uint32).reshape(pair_count, 2)
    f_array, f_present = _optional_matrix_channel(f_values)
    e_array, e_present = _optional_matrix_channel(e_values)
    h_array, h_present = _optional_matrix_channel(h_values)
    return _core.match_graph(
        image_pairs,
        raw_offsets,
        raw_matches,
        verified_offsets,
        verified_matches,
        scores=scores,
        configs=np.zeros(pair_count, dtype=np.int32),
        fundamental_matrices=f_array,
        fundamental_present=f_present,
        essential_matrices=e_array,
        essential_present=e_present,
        homographies=h_array,
        homography_present=h_present,
        match_present=np.full(pair_count, int(channel == "raw"), dtype=np.uint8),
        geometry_present=np.asarray(geometry_flags, dtype=np.uint8),
        match_score_present=np.asarray(score_flags, dtype=np.uint8),
    )


def _depth_validity(depth: np.ndarray, policy: str) -> np.ndarray:
    if policy == "none":
        invalid = np.zeros(depth.shape, dtype=np.bool_)
    elif policy == "zero":
        invalid = depth == 0
    elif policy == "nonfinite":
        invalid = ~np.isfinite(depth)
    elif policy == "negative":
        invalid = depth < 0
    elif policy == "nonpositive":
        invalid = depth <= 0
    else:
        raise ContractViolation(f"unknown native depth invalid policy {policy!r}")
    return ~invalid


def depth_map_from_native(
    value: object,
    *,
    scale_to_parent_units: float,
    allow_loss: bool = False,
) -> NeutralDepthMap:
    """Project stored depth values into the owning neutral frame's units.

    ``scale_to_parent_units`` is mandatory because neutral depth carries its
    scale on the parent :class:`FrameMeta`, not on the raster itself.
    """

    _native(value, _core.DepthMap, "depth_map_from_native")
    scale = _positive_scale(scale_to_parent_units, "scale_to_parent_units")
    convention = str(value.depth_convention)
    if convention == "ray_distance":
        raise ContractViolation(
            "ray-distance depth needs a ray calibration before it can become neutral camera depth"
        )
    losses: list[str] = []
    if convention == "unspecified":
        losses.append("unspecified depth convention")
    if bool(value.has_confidence):
        losses.append("confidence raster")
    _refuse_loss("DepthMap", losses, allow_loss)
    depth = np.asarray(value.depth)
    if scale != 1.0:
        depth = np.ascontiguousarray(depth * np.float32(scale), dtype=np.float32)
    valid = _depth_validity(depth, str(value.invalid_policy))
    return NeutralDepthMap(depth, None if bool(valid.all()) else np.ascontiguousarray(valid))


def depth_map_from_neutral(
    value: NeutralDepthMap,
    *,
    unit: str,
    scale_to_meters: float | None = None,
    invalid_policy: str = "nonpositive",
    depth_convention: str = "camera_z",
    confidence: np.ndarray | None = None,
) -> object:
    """Materialize neutral camera depth as a native stored-depth record.

    Numeric values are already assumed to use the requested stored unit.  The
    invalid mask is encoded with a policy-specific sentinel in a copy.
    """

    if not isinstance(value, NeutralDepthMap):
        raise TypeError(
            f"depth_map_from_neutral expects sceneio.data.DepthMap, got {type(value).__name__}"
        )
    if invalid_policy not in {"none", "zero", "nonfinite", "negative", "nonpositive"}:
        raise ValueError("invalid_policy must be none|zero|nonfinite|negative|nonpositive")
    if depth_convention != "camera_z":
        if depth_convention == "ray_distance":
            raise ContractViolation(
                "ray-distance materialization needs a ray calibration to convert neutral "
                "camera depth"
            )
        raise ContractViolation("neutral camera depth requires depth_convention='camera_z'")
    depth = np.ascontiguousarray(value.depth)
    if value.valid is not None and not bool(value.valid.all()):
        if invalid_policy == "none":
            raise ContractViolation("invalid_policy='none' cannot encode a neutral validity mask")
        depth = depth.copy()
        sentinel = {
            "zero": np.float32(0.0),
            "nonfinite": np.float32(np.nan),
            "negative": np.float32(-1.0),
            "nonpositive": np.float32(0.0),
        }[invalid_policy]
        depth[~value.valid] = sentinel
    return _core.depth_map(
        depth,
        confidence=None if confidence is None else np.ascontiguousarray(confidence),
        unit=unit,
        scale_to_meters=scale_to_meters,
        invalid_policy=invalid_policy,
        depth_convention=depth_convention,
    )


def _neutral_projection_scale(
    frame: FrameMeta,
    normalization_scale_to_meters: float | None,
) -> tuple[str, float | None]:
    if frame.scale == "normalized":
        if normalization_scale_to_meters is None:
            raise ContractViolation(
                "normalized neutral poses require normalization_scale_to_meters"
            )
        return (
            "metric",
            _positive_scale(
                normalization_scale_to_meters,
                "normalization_scale_to_meters",
            ),
        )
    if normalization_scale_to_meters is not None:
        raise ContractViolation(
            "normalization_scale_to_meters is only valid for a normalized frame"
        )
    return frame.scale, 1.0 if frame.scale == "metric" else None


def _neutral_source_scale(
    frame: FrameMeta,
    source_scale_to_meters: float | None,
) -> float:
    if frame.scale == "metric":
        if source_scale_to_meters is not None:
            raise ContractViolation(
                "source_scale_to_meters is only valid for arbitrary or normalized poses"
            )
        return 1.0
    if source_scale_to_meters is None:
        raise ContractViolation(f"{frame.scale} neutral poses require source_scale_to_meters")
    return _positive_scale(source_scale_to_meters, "source_scale_to_meters")


def _native_pose_losses(value: object, frame: FrameMeta) -> list[str]:
    losses: list[str] = []
    if len(value.timestamps):
        losses.append("timestamps")
    if frame.scale != "metric":
        losses.append("native metric scale")
    referenced_cameras = {
        int(camera_index)
        for camera_index in np.asarray(value.camera_indices)
        if int(camera_index) >= 0
    }
    if len(referenced_cameras) != len(value.cameras):
        losses.append("unreferenced cameras")
    return losses


def _neutral_pose_losses(value: NeutralPosedViewSet) -> tuple[list[str], tuple[str | None, ...]]:
    losses: list[str] = []
    if value.frame.scale_provenance != "unknown":
        losses.append("scale provenance")
    for index, view in enumerate(value.views):
        if view.pose_prior is not None:
            losses.append(f"pose prior for view {index}")
        if view.depth_prior is not None:
            losses.append(f"depth prior for view {index}")
        if view.mask is not None:
            losses.append(f"mask for view {index}")
        if view.calibration is not None and view.calibration.rays is not None:
            raise ContractViolation("native cameras cannot represent RayMap calibration")
    refs = tuple(view.ref for view in value.views)
    if any(ref is None for ref in refs) and any(ref is not None for ref in refs):
        losses.append("partially present view names")
    return losses, refs


def _camera_catalog_from_views(
    views: Sequence[ViewInput],
) -> tuple[tuple[object, ...] | None, np.ndarray | None]:
    """Build a minimal native camera catalog for equivalent intrinsics."""

    cameras: list[object] = []
    camera_indices = np.full(len(views), -1, dtype=np.int32)
    catalog_indices: dict[tuple[int, int, int, bytes], int] = {}
    for view_index, view in enumerate(views):
        if view.calibration is None:
            continue
        intrinsics = view.calibration.intrinsics
        assert intrinsics is not None
        key = (
            intrinsics.model.model_id,
            intrinsics.width,
            intrinsics.height,
            intrinsics.params.tobytes(order="C"),
        )
        camera_index = catalog_indices.get(key)
        if camera_index is None:
            camera_index = len(cameras)
            catalog_indices[key] = camera_index
            cameras.append(camera_from_neutral(intrinsics, camera_id=camera_index + 1))
        camera_indices[view_index] = camera_index
    if not cameras:
        return None, None
    return tuple(cameras), camera_indices


def posed_view_set_from_native(
    value: object,
    *,
    images: Sequence[object],
    frame: FrameMeta,
    pose_convention: Literal["opencv_cam2world", "opencv_world2cam"] = "opencv_cam2world",
    normalization_scale_to_meters: float | None = None,
    allow_loss: bool = False,
) -> NeutralPosedViewSet:
    """Attach image references and project a native pose record to neutral views.

    ``normalization_scale_to_meters`` is required when the requested neutral
    frame is normalized. It declares how many meters one normalized output
    unit represents; loss acknowledgement alone never invents that mapping.
    """

    _native(value, _core.PosedViewSet, "posed_view_set_from_native")
    if not isinstance(frame, FrameMeta):
        raise TypeError("frame must be sceneio.data.FrameMeta")
    if frame.world_frame != "arbitrary":
        raise ContractViolation(
            "native posed views have an arbitrary world frame; re-anchoring requires an "
            "explicit world transform before neutral projection"
        )
    if pose_convention not in {"opencv_cam2world", "opencv_world2cam"}:
        raise ValueError("pose_convention must be opencv_cam2world or opencv_world2cam")
    target_scale_class, target_scale = _neutral_projection_scale(
        frame,
        normalization_scale_to_meters,
    )
    image_values = tuple(images)
    if len(image_values) != int(value.num_views):
        raise ContractViolation(
            f"images must contain one reference per native view ({value.num_views})"
        )
    _refuse_loss("PosedViewSet", _native_pose_losses(value, frame), allow_loss)

    target = replace(
        COLMAP_COORDINATES,
        name="neutral_posed_views",
        scale_class=target_scale_class,
        scale_to_meters=target_scale,
    )
    canonical = convert_coordinates(value, target)
    names = tuple(canonical.names)
    camera_indices = np.asarray(canonical.camera_indices)
    cameras = tuple(canonical.cameras)
    quaternions = np.asarray(canonical.quaternions)
    translations = np.asarray(canonical.translations)

    views: list[ViewInput] = []
    poses: list[SE3] = []
    for index, image in enumerate(image_values):
        calibration = None
        if camera_indices.size:
            camera_index = int(camera_indices[index])
            if camera_index >= 0:
                calibration = Calibration.from_intrinsics(
                    camera_intrinsics_from_native(cameras[camera_index])
                )
        views.append(
            ViewInput(
                image=image,
                name=names[index] if names else None,
                calibration=calibration,
            )
        )
        poses.append(
            SE3.from_colmap_world2cam(
                quaternions[index],
                translations[index],
                convention=pose_convention,
            )
        )
    return NeutralPosedViewSet(tuple(views), tuple(poses), frame)


def posed_view_set_from_neutral(
    value: NeutralPosedViewSet,
    *,
    scale_to_meters: float = 1.0,
    source_scale_to_meters: float | None = None,
    quaternion_order: Literal["wxyz", "xyzw"] = "wxyz",
    pose_convention: Literal["camera_to_world", "world_to_camera"] = "camera_to_world",
    axis_frame: Literal["opencv", "opengl"] = "opencv",
    allow_loss: bool = False,
) -> object:
    """Materialize neutral poses/calibrations as a native pose-only record.

    Image payloads are contextual inputs and are intentionally not copied into
    the native pose record. Optional priors and masks require explicit loss
    acknowledgement. Metric neutral poses use meters. Arbitrary or normalized
    poses require ``source_scale_to_meters`` to map one source unit to meters.
    """

    if not isinstance(value, NeutralPosedViewSet):
        raise TypeError(
            "posed_view_set_from_neutral expects sceneio.data.PosedViewSet, "
            f"got {type(value).__name__}"
        )
    if value.frame.world_frame != "arbitrary":
        raise ContractViolation("native PosedViewSet can only label an arbitrary world frame")
    target_scale = _positive_scale(scale_to_meters, "scale_to_meters")
    source_scale = _neutral_source_scale(value.frame, source_scale_to_meters)
    losses, refs = _neutral_pose_losses(value)
    _refuse_loss("neutral PosedViewSet", losses, allow_loss)

    quaternions: list[np.ndarray] = []
    translations: list[np.ndarray] = []
    for pose in value.poses:
        quaternion, translation = pose.to_colmap_world2cam()
        translation = translation * (source_scale / target_scale)
        quaternions.append(quaternion)
        translations.append(translation)

    cameras, camera_indices = _camera_catalog_from_views(value.views)
    names = list(refs) if refs and all(ref is not None for ref in refs) else None
    base = _core.posed_view_set(
        np.ascontiguousarray(quaternions, dtype=np.float64),
        np.ascontiguousarray(translations, dtype=np.float64),
        names=names,
        quaternion_order="wxyz",
        pose_convention="world_to_camera",
        axis_frame="opencv",
        scale_to_meters=target_scale,
        camera_indices=camera_indices,
        cameras=cameras,
    )
    target = replace(
        COLMAP_COORDINATES,
        name="native_posed_views",
        camera_axes=axis_frame,
        pose_direction=pose_convention,
        quaternion_order=quaternion_order,
        scale_class="metric",
        scale_to_meters=target_scale,
    )
    return convert_coordinates(base, target)


__all__ = [
    "camera_from_neutral",
    "camera_intrinsics_from_native",
    "correspondence_graph_from_native",
    "depth_map_from_native",
    "depth_map_from_neutral",
    "feature_set_from_native",
    "feature_set_from_neutral",
    "match_graph_from_neutral",
    "posed_view_set_from_native",
    "posed_view_set_from_neutral",
]
