"""Public format I/O for SceneIO — format-dispatched ``read`` / ``write`` /
``inspect`` / ``read_partial`` over the compiled codecs, plus the record types.

    import sceneio
    recon = sceneio.read("sparse/0")     # -> Reconstruction  (COLMAP dir)
    cloud = sceneio.read("scene.ply")    # -> GaussianCloud
    sceneio.write(cloud, "out.ply")

Dispatch, error normalization, and detection are handled here; a new format
is one :func:`sceneio.io.register` call over a compiled codec. See
``docs/core_architecture.md``.
"""

from __future__ import annotations

import operator
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from sceneio import _core
from sceneio._camera_models import CAMERA_MODEL_NAMES, CAMERA_MODEL_PARAMETER_NAMES
from sceneio._data.pointcloud import TrackObservation as _TrackObservation
from sceneio._data.views import PosedViewSet as _PosedViewSet
from sceneio.colmap_db import (
    ColmapDatabaseConversionReport as _ColmapDatabaseConversionReport,
)
from sceneio.coordinate_conversion import convert_coordinates
from sceneio.coordinates import (
    COLMAP_COORDINATES,
    IMAGE_COORDINATES,
    UNKNOWN_COORDINATES,
    UNSPECIFIED_FORMAT_COORDINATES,
    coordinate_convention,
    install_coordinate_properties,
)
from sceneio.errors import ContractViolation
from sceneio.io._arrow import write_arrow_ipc, write_parquet
from sceneio.io._depth import (
    inspect_depth,
    read_depth,
    write_depth,
)
from sceneio.io._e57 import inspect_e57_scans as _inspect_e57_scans
from sceneio.io._e57 import read_e57_scan as _read_e57_scan
from sceneio.io._e57 import read_e57_scans as _read_e57_scans
from sceneio.io._e57 import write_e57_scans as _write_e57_scans
from sceneio.io._euroc_dataset import (
    read_euroc_dataset,
    write_euroc_dataset,
)
from sceneio.io._hdf5 import (
    HlocFeatureStore as _HlocFeatureStore,
)
from sceneio.io._hdf5 import (
    HlocMatchStore as _HlocMatchStore,
)
from sceneio.io._inspection import inspect_codec
from sceneio.io._inspectors.model import (
    Inspection as _Inspection,
)
from sceneio.io._label_map import (
    LABEL_MAP_SCHEMA,
    inspect_label_map,
    read_label_map,
    write_label_map,
)
from sceneio.io._ncore import (
    NCoreDataset as _NCoreDataset,
)
from sceneio.io._ncore import (
    NCoreDatasetData as _NCoreDatasetData,
)
from sceneio.io._ncore import (
    materialize_ncore_v4,
    project_ncore_item,
    read_ncore_component,
    read_ncore_semantic_component,
    write_ncore_v4,
)
from sceneio.io._openvdb import write_openvdb
from sceneio.io._registry.adapters import _file_sink_writer, _mmap_reader
from sceneio.io._registry.coordinates import coordinate_contract
from sceneio.io._rtmv import RtmvDataset as _RtmvDataset
from sceneio.io._tiff import (
    inspect_tiff_collection as _inspect_tiff_collection,
)
from sceneio.io._tiff import read_tiff_collection as _read_tiff_collection
from sceneio.io._tiff import write_tiff
from sceneio.io._tiff import write_tiff_collection as _write_tiff_collection
from sceneio.io._usd import (
    read_scene as _read_usd_scene,
)
from sceneio.io._usd import (
    write_scene as _write_usd_scene,
)
from sceneio.io._usd import (
    write_usd,
    write_usdz,
)
from sceneio.io._zarr import write_zarr
from sceneio.io.registry import (
    REGISTRY,
    detect,
    get,
    native_feature_capabilities,
    register,
)
from sceneio.io.registry import (
    Codec as _Codec,
)
from sceneio.io.registry import (
    CodecCapabilities as _CodecCapabilities,
)
from sceneio.io.registry import (
    FormatError as _FormatError,
)
from sceneio.io.registry import (
    NativeFeatureCapabilities as _NativeFeatureCapabilities,
)

if TYPE_CHECKING:
    from sceneio._data import RasterCollection

convert_gaussian_conventions = _core.convert_gaussian_conventions


def _point_cloud_tracks(value: _core.PointCloud):
    if not value.has_tracks:
        return None
    offsets = np.asarray(value.track_offsets)
    image_ids = tuple(value.track_image_ids)
    keypoint_indices = np.asarray(value.track_keypoint_indices)
    return tuple(
        tuple(
            _TrackObservation(image_ids[index], int(keypoint_indices[index]))
            for index in range(int(offsets[point]), int(offsets[point + 1]))
        )
        for point in range(value.num_points)
    )


if not hasattr(_core.PointCloud, "tracks"):
    _core.PointCloud.tracks = property(_point_cloud_tracks)


def depth_map(
    depth: object,
    *,
    valid: object | None = None,
    confidence: object | None = None,
    unit: str | None = None,
    scale_to_meters: float | None = None,
    invalid_policy: str = "none",
    depth_convention: str = "unspecified",
) -> _core.DepthMap:
    """Build canonical depth with semantic validity and source encoding facts."""

    if not isinstance(depth, np.ndarray):
        raise ContractViolation(
            f"DepthMap.depth: expected numpy.ndarray, got {type(depth).__name__}"
        )
    if depth.dtype != np.float32:
        raise ContractViolation(
            "DepthMap.depth: expected dtype float32, "
            f"got {depth.dtype.name}"
        )
    if depth.ndim != 2:
        raise ContractViolation(
            f"DepthMap.depth: expected a 2-D array, got shape {depth.shape}"
        )
    if not all(depth.shape):
        raise ContractViolation("DepthMap.depth: dimensions must be positive")
    if valid is not None:
        if not isinstance(valid, np.ndarray):
            raise ContractViolation("DepthMap.valid: expected numpy.ndarray or None")
        if valid.dtype != np.bool_:
            raise ContractViolation(
                "DepthMap.valid: expected dtype bool, "
                f"got {valid.dtype.name}"
            )
        if valid.shape != depth.shape:
            raise ContractViolation(
                "DepthMap.valid: expected shape matching depth, "
                f"got {valid.shape}"
            )
    if confidence is not None and (
        not isinstance(confidence, np.ndarray)
        or confidence.dtype != np.float32
        or confidence.shape != depth.shape
    ):
        raise ContractViolation(
            "DepthMap.confidence: expected a float32 array matching depth"
        )
    if valid is not None:
        semantic_valid = valid
    elif invalid_policy == "zero":
        semantic_valid = depth != 0
    elif invalid_policy == "nonfinite":
        semantic_valid = np.isfinite(depth)
    elif invalid_policy == "negative":
        semantic_valid = depth >= 0
    elif invalid_policy == "nonpositive":
        semantic_valid = depth > 0
    else:
        semantic_valid = np.ones(depth.shape, dtype=np.bool_)
    observed = depth[semantic_valid]
    if observed.size and not bool(np.all(np.isfinite(observed))):
        raise ContractViolation(
            "DepthMap.depth: valid pixels contain non-finite values (NaN/Inf)"
        )
    if observed.size and float(observed.min()) <= 0.0:
        raise ContractViolation("DepthMap.depth: valid pixels must be > 0")
    try:
        return _core.depth_map(
            depth,
            confidence,
            unit=unit,
            scale_to_meters=scale_to_meters,
            invalid_policy=invalid_policy,
            depth_convention=depth_convention,
            valid=valid,
        )
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"DepthMap: {exc}") from None


def point_cloud(
    positions: object,
    colors: object | None = None,
    normals: object | None = None,
    intensity: object | None = None,
    *,
    coordinate_frame: str = "unknown",
    scale_to_meters: float = 1.0,
    intensity_range: str = "unknown",
    colors16: object | None = None,
    origin: object | None = None,
    width: int | None = None,
    height: int | None = None,
    viewpoint: object | None = None,
    las_waveform: object | None = None,
    display_colors: object | None = None,
    display_opacities: object | None = None,
    widths: object | None = None,
    ids: object | None = None,
    velocities: object | None = None,
    accelerations: object | None = None,
    display_color_space: str = "unknown",
    tracks: object | None = None,
    track_offsets: object | None = None,
    track_image_ids: object | None = None,
    track_keypoint_indices: object | None = None,
) -> _core.PointCloud:
    """Build one canonical point cloud, optionally with observation tracks.

    Tracks may be supplied either as per-point ``TrackObservation`` rows or as
    the three canonical CSR columns. The two forms are mutually exclusive.
    """

    if not isinstance(positions, np.ndarray):
        raise ContractViolation(
            f"PointCloud.positions: expected numpy.ndarray, got {type(positions).__name__}"
        )
    if positions.dtype != np.float32 or positions.ndim != 2 or positions.shape[1:] != (3,):
        raise ContractViolation(
            "PointCloud.positions: expected dtype float32 and shape (N, 3)"
        )
    if not positions.flags.c_contiguous:
        raise ContractViolation("PointCloud.positions: expected a C-contiguous array")

    def require_array(
        field: str,
        value: object | None,
        dtype: object,
        shape: tuple[int, ...],
    ) -> None:
        if value is None:
            return
        expected_dtype = np.dtype(dtype)
        if not isinstance(value, np.ndarray):
            raise ContractViolation(
                f"PointCloud.{field}: expected numpy.ndarray or None"
            )
        if value.dtype != expected_dtype or value.shape != shape:
            raise ContractViolation(
                f"PointCloud.{field}: expected dtype {expected_dtype.name} and "
                f"shape {shape}, got dtype {value.dtype.name} and shape {value.shape}"
            )
        if not value.flags.c_contiguous:
            raise ContractViolation(
                f"PointCloud.{field}: expected a C-contiguous array"
            )

    count = int(positions.shape[0])
    require_array("colors", colors, np.uint8, (count, 3))
    require_array("normals", normals, np.float32, (count, 3))
    require_array("intensity", intensity, np.float32, (count,))
    require_array("colors16", colors16, np.uint16, (count, 3))
    require_array("origin", origin, np.float64, (3,))
    require_array("viewpoint", viewpoint, np.float64, (7,))
    require_array("display_colors", display_colors, np.float32, (count, 3))
    require_array("display_opacities", display_opacities, np.float32, (count,))
    require_array("widths", widths, np.float32, (count,))
    require_array("ids", ids, np.int64, (count,))
    require_array("velocities", velocities, np.float32, (count, 3))
    require_array("accelerations", accelerations, np.float32, (count, 3))

    supplied_csr = (
        track_offsets is not None,
        track_image_ids is not None,
        track_keypoint_indices is not None,
    )
    if tracks is not None and any(supplied_csr):
        raise ContractViolation(
            "PointCloud: tracks and track CSR columns are mutually exclusive"
        )
    if any(supplied_csr) and not all(supplied_csr):
        raise ContractViolation(
            "PointCloud: track_offsets, track_image_ids, and "
            "track_keypoint_indices must be provided together"
        )
    if tracks is not None:
        if isinstance(tracks, str | bytes) or not isinstance(tracks, Sequence):
            raise ContractViolation("PointCloud.tracks: expected one sequence per point")
        if len(tracks) != positions.shape[0]:
            raise ContractViolation(
                f"PointCloud.tracks: expected one track per point ({positions.shape[0]}), "
                f"got {len(tracks)}"
            )
        offsets = [0]
        image_values: list[str] = []
        keypoint_values: list[int] = []
        for point_index, track in enumerate(tracks):
            if isinstance(track, str | bytes) or not isinstance(track, Sequence):
                raise ContractViolation(
                    f"PointCloud.tracks[{point_index}]: expected a sequence of "
                    "TrackObservation"
                )
            for observation in track:
                if not isinstance(observation, _TrackObservation):
                    raise ContractViolation(
                        f"PointCloud.tracks[{point_index}]: expected TrackObservation "
                        f"entries, got {type(observation).__name__}"
                    )
                image_values.append(observation.image_id)
                keypoint_values.append(observation.keypoint_idx)
            offsets.append(len(image_values))
        track_offsets = np.ascontiguousarray(offsets, dtype=np.uint64)
        track_image_ids = image_values
        track_keypoint_indices = np.ascontiguousarray(
            keypoint_values,
            dtype=np.uint64,
        )
    elif all(supplied_csr):
        if not isinstance(track_offsets, np.ndarray) or (
            track_offsets.dtype != np.uint64
            or track_offsets.ndim != 1
            or not track_offsets.flags.c_contiguous
        ):
            raise ContractViolation(
                "PointCloud.track_offsets: expected a C-contiguous uint64 vector"
            )
        if not isinstance(track_keypoint_indices, np.ndarray) or (
            track_keypoint_indices.dtype != np.uint64
            or track_keypoint_indices.ndim != 1
            or not track_keypoint_indices.flags.c_contiguous
        ):
            raise ContractViolation(
                "PointCloud.track_keypoint_indices: expected a C-contiguous uint64 vector"
            )
        if isinstance(track_image_ids, str | bytes) or not isinstance(
            track_image_ids, Sequence
        ):
            raise ContractViolation(
                "PointCloud.track_image_ids: expected a sequence of image identities"
            )
        track_image_ids = tuple(track_image_ids)
        if any(
            not isinstance(image_id, str) or not image_id or "\x00" in image_id
            for image_id in track_image_ids
        ):
            raise ContractViolation(
                "PointCloud.track_image_ids: identities must be non-empty strings without NUL"
            )

    try:
        return _core.point_cloud(
            positions,
            colors=colors,
            normals=normals,
            intensity=intensity,
            coordinate_frame=coordinate_frame,
            scale_to_meters=scale_to_meters,
            intensity_range=intensity_range,
            colors16=colors16,
            origin=origin,
            width=width,
            height=height,
            viewpoint=viewpoint,
            las_waveform=las_waveform,
            display_colors=display_colors,
            display_opacities=display_opacities,
            widths=widths,
            ids=ids,
            velocities=velocities,
            accelerations=accelerations,
            display_color_space=display_color_space,
            track_offsets=track_offsets,
            track_image_ids=track_image_ids,
            track_keypoint_indices=track_keypoint_indices,
        )
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"PointCloud: {exc}") from None


def camera_intrinsics(
    model_id: int,
    width: int,
    height: int,
    params: object,
) -> _core.CameraIntrinsics:
    """Build canonical camera intrinsics in COLMAP's model vocabulary."""

    try:
        selected_model = operator.index(model_id)
    except TypeError:
        raise ContractViolation("CameraIntrinsics.model_id must be an integer") from None
    if isinstance(model_id, bool) or not 0 <= selected_model < len(CAMERA_MODEL_NAMES):
        raise ContractViolation(f"unknown camera model id {selected_model!r}")

    dimensions: list[int] = []
    for name, value in (("width", width), ("height", height)):
        try:
            selected = operator.index(value)
        except TypeError:
            raise ContractViolation(f"CameraIntrinsics.{name} must be a positive integer") from None
        if isinstance(value, bool) or selected <= 0 or selected > np.iinfo(np.uint64).max:
            raise ContractViolation(f"CameraIntrinsics.{name} must be a positive integer")
        dimensions.append(selected)

    try:
        values = np.ascontiguousarray(params, dtype=np.float64)
    except (TypeError, ValueError):
        raise ContractViolation("CameraIntrinsics.params must be numeric") from None
    expected = len(CAMERA_MODEL_PARAMETER_NAMES[selected_model])
    if values.shape != (expected,):
        model_name = CAMERA_MODEL_NAMES[selected_model]
        raise ContractViolation(
            f"CameraIntrinsics.params: model {model_name} takes {expected} params, "
            f"got shape {values.shape}"
        )
    if not bool(np.all(np.isfinite(values))):
        raise ContractViolation("CameraIntrinsics.params contains non-finite values")
    return _core.camera_intrinsics(
        selected_model,
        dimensions[0],
        dimensions[1],
        values,
    )


def feature_set(
    keypoints: object,
    descriptors: object | None = None,
    scores: object | None = None,
    *,
    image_size: tuple[int, int] = (1, 1),
    extractor_type: int | None = None,
    extractor_type_name: str | None = None,
    keypoint_colors: object | None = None,
    quality: float | None = None,
    pixel_center: tuple[float, float] = (0.5, 0.5),
) -> _core.FeatureSet:
    """Build the canonical feature payload without collection identity."""

    if not isinstance(keypoints, np.ndarray):
        raise ContractViolation(
            "FeatureSet.keypoints: expected numpy.ndarray, "
            f"got {type(keypoints).__name__}"
        )
    if keypoints.dtype != np.float32:
        raise ContractViolation(
            "FeatureSet.keypoints: expected dtype float32, "
            f"got {keypoints.dtype.name}"
        )
    if keypoints.ndim != 2 or keypoints.shape[1] not in (2, 4, 6):
        raise ContractViolation(
            "FeatureSet.keypoints: expected shape (N, 2|4|6), "
            f"got {keypoints.shape}"
        )
    if keypoints.size and not bool(np.all(np.isfinite(keypoints))):
        raise ContractViolation(
            "FeatureSet.keypoints: array contains non-finite values (NaN/Inf)"
        )
    if not keypoints.flags.c_contiguous:
        raise ContractViolation("FeatureSet.keypoints: expected a C-contiguous array")

    descriptor_array: np.ndarray | None = None
    if descriptors is not None:
        if not isinstance(descriptors, np.ndarray):
            raise ContractViolation(
                "FeatureSet.descriptors: expected numpy.ndarray, "
                f"got {type(descriptors).__name__}"
            )
        supported = {
            np.dtype(np.int8),
            np.dtype(np.int16),
            np.dtype(np.int32),
            np.dtype(np.int64),
            np.dtype(np.uint8),
            np.dtype(np.uint16),
            np.dtype(np.uint32),
            np.dtype(np.uint64),
            np.dtype(np.float16),
            np.dtype(np.float32),
            np.dtype(np.float64),
        }
        if descriptors.dtype not in supported:
            raise ContractViolation(
                "FeatureSet.descriptors: expected a supported numeric dtype, "
                f"got {descriptors.dtype.name}"
            )
        if descriptors.ndim != 2 or descriptors.shape[0] != keypoints.shape[0]:
            raise ContractViolation(
                "FeatureSet.descriptors: expected shape (N, D) parallel to "
                f"keypoints, got {descriptors.shape}"
            )
        if not descriptors.flags.c_contiguous:
            raise ContractViolation(
                "FeatureSet.descriptors: expected a C-contiguous array"
            )
        descriptor_array = descriptors

    score_array: np.ndarray | None = None
    if scores is not None:
        if not isinstance(scores, np.ndarray):
            raise ContractViolation(
                "FeatureSet.scores: expected numpy.ndarray, "
                f"got {type(scores).__name__}"
            )
        if scores.dtype != np.float32:
            raise ContractViolation(
                "FeatureSet.scores: expected dtype float32, "
                f"got {scores.dtype.name}"
            )
        if scores.shape != (keypoints.shape[0],):
            raise ContractViolation(
                "FeatureSet.scores: expected shape (N,), "
                f"got {scores.shape}"
            )
        if scores.size and not bool(np.all(np.isfinite(scores))):
            raise ContractViolation(
                "FeatureSet.scores: array contains non-finite values (NaN/Inf)"
            )
        if not scores.flags.c_contiguous:
            raise ContractViolation("FeatureSet.scores: expected a C-contiguous array")
        score_array = scores

    if (
        not isinstance(pixel_center, tuple)
        or len(pixel_center) != 2
        or any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not np.isfinite(float(value))
            for value in pixel_center
        )
    ):
        raise ContractViolation("FeatureSet.pixel_center: expected two finite numbers")

    if (
        not isinstance(image_size, tuple)
        or len(image_size) != 2
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > np.iinfo(np.uint64).max
            for value in image_size
        )
    ):
        raise ContractViolation("FeatureSet.image_size: expected two positive integers")
    if extractor_type is not None and (
        isinstance(extractor_type, bool)
        or not isinstance(extractor_type, int)
        or not -(1 << 31) <= extractor_type < (1 << 31)
    ):
        raise ContractViolation("FeatureSet.extractor_type: expected an int32 or None")
    if extractor_type_name is not None and (
        not isinstance(extractor_type_name, str) or "\x00" in extractor_type_name
    ):
        raise ContractViolation(
            "FeatureSet.extractor_type_name: expected text without NUL or None"
        )

    color_array: np.ndarray | None = None
    if keypoint_colors is not None:
        if not isinstance(keypoint_colors, np.ndarray):
            raise ContractViolation(
                "FeatureSet.keypoint_colors: expected numpy.ndarray, "
                f"got {type(keypoint_colors).__name__}"
            )
        if keypoint_colors.dtype != np.uint8 or keypoint_colors.shape != (
            keypoints.shape[0],
            3,
        ):
            raise ContractViolation(
                "FeatureSet.keypoint_colors: expected dtype uint8 and shape (N, 3)"
            )
        if not keypoint_colors.flags.c_contiguous:
            raise ContractViolation(
                "FeatureSet.keypoint_colors: expected a C-contiguous array"
            )
        color_array = keypoint_colors

    if quality is not None and (
        isinstance(quality, bool)
        or not isinstance(quality, int | float)
        or not np.isfinite(float(quality))
    ):
        raise ContractViolation("FeatureSet.quality: expected a finite number or None")

    try:
        return _core.feature_set(
            keypoints,
            descriptor_array,
            score_array,
            image_size=image_size,
            extractor_type=-1 if extractor_type is None else extractor_type,
            pixel_center=pixel_center,
            extractor_type_name=extractor_type_name,
            keypoint_colors=color_array,
            quality=quality,
        )
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"FeatureSet: {exc}") from None

install_coordinate_properties(
    _core.Reconstruction,
    _core.GaussianCloud,
    _PosedViewSet,
    _core.StateTrajectory,
    _core.ImuCalibration,
    _core.ImuSequence,
    _core.TensorDict,
    _core.Image,
    _core.ImageSequence,
    _core.PointCloud,
    _core.PointScan,
    _core.ScanSet,
    _core.Mesh,
    _core.SceneGraph,
    _core.PoseGraph,
    _core.FeatureSet,
    _core.DepthMap,
    _core.FlowField,
    _core.NormalMap,
    _core.ConsistencyGraph,
    _core.PointVisibility,
    _core.CameraIntrinsics,
    _core.CameraRig,
    _RtmvDataset,
    _HlocFeatureStore,
    _HlocMatchStore,
    _NCoreDataset,
    _NCoreDatasetData,
    _core.ColmapDatabase,
)

_FLOW_READER = _mmap_reader(_core.read_flo_field)
_FLOW_WRITER = _file_sink_writer(_core.write_flo_field)
_EXACT_COLMAP_DB_PROFILES = frozenset(
    item["name"] for item in _core._colmap_db_profiles()
)


def _resolve_flow_format(path, format: str | None, *, writing: bool) -> str:
    if format is not None:
        selected = format
    elif writing:
        selected = "flo" if Path(path).suffix.lower() == ".flo" else ""
    else:
        selected = detect(path)
    if selected != "flo":
        operation = "write" if writing else "read"
        rendered = selected or Path(path).suffix.lower() or "<none>"
        raise _FormatError(
            f"{operation}_flow supports only Middlebury 'flo' "
            f"(selected {rendered!r})"
        )
    return selected


def read_flow(path, *, format: str | None = None) -> _core.FlowField:
    """Read Middlebury ``.flo`` into a convention-tagged :class:`FlowField`.

    The file is decoded through a read-only mmap into record-owned storage.
    Existing :func:`read` behavior is unchanged and continues to return the raw
    mapped ``(H,W,2)`` ndarray.
    """

    _resolve_flow_format(path, format, writing=False)
    try:
        return _FLOW_READER(str(path))
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(f"reading {str(path)!r} as typed flow: {exc}") from exc


def write_flow(
    flow: _core.FlowField,
    path,
    *,
    format: str | None = None,
) -> None:
    """Write a canonical Middlebury-convention :class:`FlowField`.

    The writer refuses component, axis, row, unit, or invalid-value
    conventions that ``.flo`` cannot preserve. It uses the direct native file
    sink and does not materialize an output-sized Python ``bytes`` object.
    """

    _resolve_flow_format(path, format, writing=True)
    try:
        _FLOW_WRITER(flow, str(path))
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(f"writing {str(path)!r} as typed flow: {exc}") from exc


def inspect_flow(path, *, format: str | None = None) -> _Inspection:
    """Inspect a ``.flo`` header and attach its fixed semantic conventions."""

    selected = _resolve_flow_format(path, format, writing=False)
    result = inspect(path, format=selected)
    return replace(
        result,
        metadata={
            **result.metadata,
            "component_order": "uv",
            "u_axis": "right",
            "v_axis": "down",
            "row_order": "top_to_bottom",
            "unit": "pixels",
            "invalid_policy": "component_abs_gt_1e9",
        },
    )


def read_e57_scan(
    path,
    *,
    scan_index: int = 0,
    stored_point_range: tuple[int, int] | None = None,
) -> _core.PointScan:
    """Read one E57 scan while preserving stored rows and scan metadata.

    ``stored_point_range`` is a half-open range over stored rows, including
    invalid rows. The result owns its arrays after the E57 file is closed.
    """

    try:
        return _read_e57_scan(
            path,
            scan_index=scan_index,
            stored_point_range=stored_point_range,
        )
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"reading E57 scan {scan_index!r} from {str(path)!r}: {exc}"
        ) from exc


def read_e57_scans(path) -> _core.ScanSet:
    """Read every supported Cartesian E57 scan in stored order."""

    try:
        return _read_e57_scans(path)
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"reading E57 scan set from {str(path)!r}: {exc}"
        ) from exc


def write_e57_scans(value, path) -> None:
    """Atomically write a PointCloud, PointScan, or ordered ScanSet as E57."""

    try:
        _write_e57_scans(value, path)
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"writing E57 scan set to {str(path)!r}: {exc}"
        ) from exc


def inspect_e57_scans(
    path,
    *,
    scan_index: int | None = None,
) -> _Inspection:
    """Inspect all E57 scan headers, or one selected header, without decoding."""

    try:
        return _inspect_e57_scans(path, scan_index=scan_index)
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"inspecting E57 scan headers in {str(path)!r}: {exc}"
        ) from exc


def read_tiff_collection(
    path,
    *,
    series_index: int | None = None,
    level_index: int | None = None,
    page_range: tuple[int, int] | None = None,
    window: tuple[int, int, int, int] | None = None,
) -> RasterCollection:
    """Read a typed TIFF series/level collection or a bounded selection."""

    try:
        return _read_tiff_collection(
            path,
            series_index=series_index,
            level_index=level_index,
            page_range=page_range,
            window=window,
        )
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"reading TIFF collection from {str(path)!r}: {exc}"
        ) from exc


def inspect_tiff_collection(path) -> _Inspection:
    """Inspect TIFF collection topology and storage without decoding samples."""

    try:
        return _inspect_tiff_collection(path)
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"inspecting TIFF collection in {str(path)!r}: {exc}"
        ) from exc


def write_tiff_collection(
    value: RasterCollection,
    path,
    *,
    bigtiff: bool | None = None,
    byteorder: str | None = None,
    tile: tuple[int, int] | None = None,
    rowsperstrip: int | None = None,
) -> None:
    """Atomically write SceneIO's portable typed TIFF collection subset."""

    try:
        _write_tiff_collection(
            value,
            path,
            bigtiff=bigtiff,
            byteorder=byteorder,
            tile=tile,
            rowsperstrip=rowsperstrip,
        )
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"writing TIFF collection to {str(path)!r}: {exc}"
        ) from exc


def read(path, *, format: str | None = None):
    """Read ``path`` into a record, dispatching on ``format`` or detection.

    Single-file codecs use a read-only mmap. The file must remain byte-stable
    during decoding. Native-endian, C-order NPY and FLO results are read-only
    views that retain the mapping. Safetensors returns a ``TensorDict`` whose
    aligned tensors are likewise read-only mapped views. Their backing file must
    not be modified or truncated until the record, returned arrays, and all
    derived views are released; a POSIX shrink can otherwise cause ``SIGBUS`` on
    later access. Atomic path replacement is safe because the live mapping
    retains the old file. On Windows the mapped file remains locked for the same
    lifetime. DLPack export makes an isolated contiguous copy because writable
    tensor consumers cannot safely alias a read-only file mapping. PFM remains
    an owned, positive-stride decode because its bottom-to-top row order requires
    a real transform.
    """
    fmt = format or detect(path)
    codec = get(fmt)
    try:
        return codec.read(str(path))
    except _FormatError:
        raise
    except Exception as exc:  # normalize codec faults to FormatError
        raise _FormatError(f"reading {str(path)!r} as {fmt!r}: {exc}") from exc


def read_scene(
    path,
    *,
    time: float | None = None,
    prims=None,
    purposes=("default", "render", "proxy"),
    variants=None,
    load_payloads: bool = True,
):
    """Read a bounded USD-family 3D-CV stage as a :class:`SceneGraph`."""

    fmt = detect(path)
    if fmt not in {"usd", "usdz"}:
        raise _FormatError(
            f"read_scene supports USD-family paths, not format {fmt!r}"
        )
    try:
        return _read_usd_scene(
            path,
            time=time,
            prims=prims,
            purposes=tuple(purposes),
            variants=variants,
            load_payloads=load_payloads,
        )
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"reading {str(path)!r} as a rich USD scene: {exc}"
        ) from exc


def inspect(path, *, format: str | None = None) -> _Inspection:
    """Return dimensions, dtype, and element counts without decoding bulk data.

    Binary image/array/cloud formats read only their container headers.
    Headerless text formats are streamed to count records, and JSON scene
    formats parse their metadata document without constructing compiled record
    arrays.
    """
    fmt = format or detect(path)
    codec = get(fmt)
    try:
        return inspect_codec(path, fmt, codec.datatype, codec.inspect)
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(f"inspecting {str(path)!r} as {fmt!r}: {exc}") from exc


def read_partial(
    path,
    *,
    window=None,
    points=None,
    faces=None,
    mesh_id=None,
    primitive_id=None,
    states=None,
    frames=None,
    image_id=None,
    pair=None,
    tensors=None,
    slices=None,
    format: str | None = None,
):
    """Read only one file-backed region while preserving the normal record type.

    Exactly one selector is required. ``window`` is the half-open pixel box
    ``(row_start, row_stop, column_start, column_stop)``. ``points``, ``faces``,
    ``states``, and ``frames`` are half-open record ranges ``(start, stop)``.
    A mesh face
    selection retains the complete vertex domain and slices all face/corner
    domains. ``mesh_id`` selects one glTF mesh object; ``primitive_id`` selects
    one glTF primitive in flattened source order. Both return a ``SceneGraph``
    geometry projection with the shared material table and no
    node/scene rows.
    ``image_id`` selects one COLMAP image by its persisted id. ``pair``
    selects one unordered pair of persisted COLMAP image ids. ``tensors``
    selects complete named tensors.
    ``slices`` maps tensor names to half-open leading-axis ``(start, stop)``
    ranges. A format that cannot access the selected region without a full
    payload decode raises :class:`sceneio.FormatError`.
    """

    selected = sum(
        value is not None
        for value in (
            window,
            points,
            faces,
            mesh_id,
            primitive_id,
            states,
            frames,
            image_id,
            pair,
            tensors,
            slices,
        )
    )
    if selected != 1:
        raise ValueError(
            "read_partial requires exactly one selector family"
        )
    fmt = format or detect(path)
    codec = get(fmt)
    if window is not None:
        values = _selector_ints(window, 4, "window")
        if codec.read_window is None:
            raise _FormatError(f"format {fmt!r} does not support pixel-window reads")
        operation = codec.read_window
    elif points is not None:
        values = _selector_ints(points, 2, "points")
        if codec.read_points is None:
            raise _FormatError(f"format {fmt!r} does not support point-subset reads")
        operation = codec.read_points
    elif faces is not None:
        values = _selector_ints(faces, 2, "faces")
        if codec.read_faces is None:
            raise _FormatError(f"format {fmt!r} does not support face-subset reads")
        operation = codec.read_faces
    elif mesh_id is not None:
        selected_mesh = _selector_int(mesh_id, "mesh_id")
        if selected_mesh < 0:
            raise ValueError("mesh_id must be non-negative")
        if codec.read_mesh is None:
            raise _FormatError(
                f"format {fmt!r} does not support mesh-subset reads"
            )
        operation = codec.read_mesh
        values = (selected_mesh,)
    elif primitive_id is not None:
        selected_primitive = _selector_int(primitive_id, "primitive_id")
        if selected_primitive < 0:
            raise ValueError("primitive_id must be non-negative")
        if codec.read_primitive is None:
            raise _FormatError(
                f"format {fmt!r} does not support primitive-subset reads"
            )
        operation = codec.read_primitive
        values = (selected_primitive,)
    elif states is not None:
        values = _selector_ints(states, 2, "states")
        if codec.read_states is None:
            raise _FormatError(
                f"format {fmt!r} does not support state-subset reads"
            )
        operation = codec.read_states
    elif frames is not None:
        values = _selector_ints(frames, 2, "frames")
        if codec.read_frames is None:
            raise _FormatError(
                f"format {fmt!r} does not support frame-subset reads"
            )
        operation = codec.read_frames
    elif image_id is not None:
        selected_image = _selector_int(image_id, "image_id")
        if selected_image < 0 or selected_image > 0xFFFFFFFF:
            raise ValueError("image_id must be in 0..4294967295")
        if codec.read_image is None:
            raise _FormatError(f"format {fmt!r} does not support single-image reads")
        operation = codec.read_image
        values = (selected_image,)
    elif pair is not None:
        image_a, image_b = _selector_ints(pair, 2, "pair")
        if (
            image_a < 0
            or image_a >= 2_147_483_647
            or image_b < 0
            or image_b >= 2_147_483_647
        ):
            raise ValueError(
                "pair image ids must be in 0..2147483646"
            )
        if image_a == image_b:
            raise ValueError("pair image ids must be distinct")
        if codec.read_pair is None:
            raise _FormatError(
                f"format {fmt!r} does not support image-pair reads"
            )
        operation = codec.read_pair
        values = (image_a, image_b)
    elif tensors is not None:
        selected_tensors = _tensor_names(tensors)
        if codec.read_tensors is None:
            raise _FormatError(
                f"format {fmt!r} does not support named-tensor reads"
            )
        operation = codec.read_tensors
        values = (selected_tensors,)
    else:
        selected_slices = _tensor_slices(slices)
        if codec.read_slices is None:
            raise _FormatError(
                f"format {fmt!r} does not support tensor-slice reads"
            )
        operation = codec.read_slices
        values = (selected_slices,)
    try:
        return operation(str(path), *values)
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"partially reading {str(path)!r} as {fmt!r}: {exc}"
        ) from exc


def _selector_int(value, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} values must be integers, not bool")
    try:
        return operator.index(value)
    except TypeError:
        raise TypeError(f"{name} values must be integers") from None


def _selector_ints(value, length: int, name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must contain {length} integers")
    try:
        values = tuple(value)
    except TypeError:
        raise TypeError(f"{name} must contain {length} integers") from None
    if len(values) != length:
        raise ValueError(f"{name} must contain exactly {length} integers")
    return tuple(_selector_int(item, name) for item in values)


def _tensor_names(value) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("tensors must be a non-empty iterable of names")
    try:
        names = tuple(value)
    except TypeError:
        raise TypeError(
            "tensors must be a non-empty iterable of names"
        ) from None
    if not names:
        raise ValueError("tensors must contain at least one name")
    if any(not isinstance(name, str) for name in names):
        raise TypeError("tensor names must be strings")
    if len(names) != len(set(names)):
        raise ValueError("tensor names must be unique")
    return names


def _tensor_slices(value) -> tuple[tuple[str, int, int], ...]:
    if not isinstance(value, Mapping):
        raise TypeError(
            "slices must be a non-empty mapping of tensor names to ranges"
        )
    if not value:
        raise ValueError("slices must contain at least one tensor")
    result = []
    for name, bounds in value.items():
        if not isinstance(name, str):
            raise TypeError("tensor slice names must be strings")
        start, stop = _selector_ints(bounds, 2, f"slice for {name!r}")
        if start < 0 or start >= stop:
            raise ValueError(
                f"slice for {name!r} must satisfy 0 <= start < stop"
            )
        result.append((name, start, stop))
    return tuple(result)


def colmap_database_conversion_report(
    database: _core.ColmapDatabase,
    *,
    profile: str,
) -> _ColmapDatabaseConversionReport:
    """Analyze an exact COLMAP database target without opening a path."""

    if profile not in _EXACT_COLMAP_DB_PROFILES:
        raise ValueError(
            f"COLMAP database writer: unknown target profile {profile!r}"
        )
    raw = _core._colmap_db_conversion_report(database, profile)
    changes = raw["identity_changes"]
    order = ("profile", "application_id", "user_version")
    return _ColmapDatabaseConversionReport(
        source_profile=raw["source_profile"],
        target_profile=raw["target_profile"],
        writable=raw["writable"],
        identity_changes=tuple(
            (name, changes[name][0], changes[name][1])
            for name in order
            if name in changes
        ),
        incompatibilities=tuple(raw["incompatibilities"]),
    )


def write_colmap_db(
    database: _core.ColmapDatabase,
    path,
    *,
    profile: str,
) -> None:
    """Write one explicitly selected exact COLMAP SQLite profile."""

    try:
        if profile not in _EXACT_COLMAP_DB_PROFILES:
            raise ValueError(
                f"COLMAP database writer: unknown target profile {profile!r}"
            )
        _core.write_colmap_db(database, str(path), profile=profile)
    except Exception as exc:
        raise _FormatError(
            f"writing {str(path)!r} as colmap_db profile {profile!r}: {exc}"
        ) from exc


def write(
    obj,
    path,
    *,
    format: str | None = None,
    profile: str | None = None,
) -> None:
    """Write a record to ``path``, dispatching on ``format``, the object
    type, and the extension.

    Single-file codecs write their C++ encoder buffer directly to the file
    without materializing a second output-sized Python ``bytes`` object. The
    file opens lazily after validation and encoding, so a rejected record does
    not truncate an existing destination. ``profile`` selects an exact
    COLMAP SQLite schema or one of the WebM ``vp8-keyframe``,
    ``vp8-temporal``, and ``vp9-temporal`` encoders. Omitting it preserves an
    exact profile carried by a decoded database and keeps WebM's compatible
    independent-frame VP8 default.
    """
    fmt = format or _detect_write(obj, path)
    codec = get(fmt)
    if codec.write is None:
        raise _FormatError(f"format {fmt!r} is read-only (no writer)")
    if profile is not None and fmt not in {"colmap_db", "webm"}:
        raise _FormatError(
            "profile is supported only when writing format 'colmap_db' "
            "or 'webm'"
        )
    if (
        profile is not None
        and fmt == "colmap_db"
        and profile not in _EXACT_COLMAP_DB_PROFILES
    ):
        raise _FormatError(
            f"COLMAP database writer: unknown target profile {profile!r}"
        )
    try:
        selected_profile = profile
        if (
            selected_profile is None
            and fmt == "colmap_db"
            and getattr(obj, "profile", None) in _EXACT_COLMAP_DB_PROFILES
        ):
            selected_profile = obj.profile
        if selected_profile is None:
            codec.write(obj, str(path))
        else:
            codec.write(obj, str(path), profile=selected_profile)
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(f"writing {str(path)!r} as {fmt!r}: {exc}") from exc


def write_scene(
    scene: _core.SceneGraph,
    path,
    *,
    encoding: str | None = None,
    package_assets: bool = True,
    profile: str = "usd-3dcv-1",
) -> None:
    """Write a bounded rich USD stage while preserving the destination."""

    try:
        _write_usd_scene(
            scene,
            path,
            encoding=encoding,
            package_assets=package_assets,
            profile=profile,
        )
    except _FormatError:
        raise
    except Exception as exc:
        raise _FormatError(
            f"writing {str(path)!r} as a rich USD scene: {exc}"
        ) from exc


def codecs() -> dict[str, _Codec]:
    """The registered codecs, keyed by format id."""
    return dict(REGISTRY)


def capabilities(
    format: str | None = None,
) -> _CodecCapabilities | dict[str, _CodecCapabilities]:
    """Return immutable discovery metadata for one or every registered codec.

    The no-argument form returns a new dictionary, so changing the mapping
    cannot mutate the registry. Each :class:`CodecCapabilities` value is frozen.
    """

    if format is not None:
        return get(format).capabilities()
    return {format_id: codec.capabilities() for format_id, codec in REGISTRY.items()}


def native_features(
    name: str | None = None,
) -> _NativeFeatureCapabilities | dict[str, _NativeFeatureCapabilities]:
    """Return compiled-state metadata for optional native integrations.

    Known integrations remain present with ``available=False`` when the
    extension was built without their ``SCENEIO_WITH_*`` option. The
    no-argument mapping is detached and its values are frozen.
    """

    return native_feature_capabilities(name)


def _detect_write(obj, path) -> str:
    # dispatch by extension (or directory) first, then disambiguate on the
    # record type if several writable codecs share an extension. Compound
    # extensions (notably `.compressed.ply`) outrank their shorter suffix.
    name = Path(path).name
    lower_name = name.lower()
    extension_matches = {
        c.id: max(
            (
                len(extension)
                for extension in c.extensions
                if lower_name.endswith(extension.lower())
            ),
            default=0,
        )
        for c in REGISTRY.values()
        if c.write is not None
    }
    longest_extension = max(extension_matches.values(), default=0)
    cands = [
        c
        for c in REGISTRY.values()
        if c.write is not None
        and (
            (
                longest_extension
                and extension_matches.get(c.id) == longest_extension
            )
            or name in c.filenames
            or (c.is_directory and Path(path).suffix == "")
        )
    ]
    if not cands:
        ext = Path(path).suffix.lower()
        raise _FormatError(
            f"no writer for {type(obj).__name__} at {str(path)!r} "
            f"(ext {ext!r})"
        )
    if len(cands) > 1:
        for c in cands:
            if c.record is type(obj):
                return c.id
    return cands[0].id


__all__ = [
    "COLMAP_COORDINATES",
    "IMAGE_COORDINATES",
    "LABEL_MAP_SCHEMA",
    "UNKNOWN_COORDINATES",
    "UNSPECIFIED_FORMAT_COORDINATES",
    "camera_intrinsics",
    "capabilities",
    "codecs",
    "colmap_database_conversion_report",
    "convert_coordinates",
    "convert_gaussian_conventions",
    "coordinate_contract",
    "coordinate_convention",
    "depth_map",
    "detect",
    "feature_set",
    "inspect",
    "inspect_depth",
    "inspect_e57_scans",
    "inspect_flow",
    "inspect_label_map",
    "inspect_tiff_collection",
    "materialize_ncore_v4",
    "native_features",
    "point_cloud",
    "project_ncore_item",
    "read",
    "read_depth",
    "read_e57_scan",
    "read_e57_scans",
    "read_euroc_dataset",
    "read_flow",
    "read_label_map",
    "read_ncore_component",
    "read_ncore_semantic_component",
    "read_partial",
    "read_scene",
    "read_tiff_collection",
    "register",
    "write",
    "write_arrow_ipc",
    "write_colmap_db",
    "write_depth",
    "write_e57_scans",
    "write_euroc_dataset",
    "write_flow",
    "write_label_map",
    "write_ncore_v4",
    "write_openvdb",
    "write_parquet",
    "write_scene",
    "write_tiff",
    "write_tiff_collection",
    "write_usd",
    "write_usdz",
    "write_zarr",
]
