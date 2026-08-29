"""NCore V4 poses, intrinsics, and sensor-mask profiles."""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping

import numpy as np

from sceneio.io._ncore.model import (
    NCoreComponentData,
    NCoreItem,
    NCoreSemanticComponent,
)
from sceneio.io._ncore.profiles.common import (
    array_attributes,
    child_group_names,
    finite_number,
    groups,
    integer,
    mapping,
    non_empty_string,
    numeric_vector,
    require_group,
    require_version,
    sequence,
    validate_sequence_timestamp,
)

_CAMERA_MODELS = {
    "ftheta",
    "ideal-pinhole",
    "opencv-fisheye",
    "opencv-pinhole",
    "pinhole",
}
_SHUTTER_TYPES = {
    "GLOBAL",
    "ROLLING_BOTTOM_TO_TOP",
    "ROLLING_LEFT_TO_RIGHT",
    "ROLLING_RIGHT_TO_LEFT",
    "ROLLING_TOP_TO_BOTTOM",
}


def _frame_pair(value: object, context: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError(f"{context} key must be a string-encoded frame pair")
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        raise ValueError(f"{context} key is not a frame pair") from None
    if not isinstance(parsed, tuple) or len(parsed) != 2:
        raise ValueError(f"{context} key is not a frame pair")
    return (
        non_empty_string(parsed[0], f"{context} source frame"),
        non_empty_string(parsed[1], f"{context} target frame"),
    )


def _pose_array(value: object, dtype_value: object, context: str) -> np.ndarray:
    try:
        dtype = np.dtype(dtype_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} has an invalid dtype") from exc
    if dtype not in {np.dtype("float32"), np.dtype("float64")}:
        raise ValueError(f"{context} dtype must be float32 or float64")
    try:
        result = np.array(value, dtype=dtype)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{context} has invalid matrix values") from exc
    if result.ndim < 2 or result.shape[-2:] != (4, 4):
        raise ValueError(f"{context} matrices must end in shape (4, 4)")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{context} matrices must be finite")
    expected_bottom = np.array([0, 0, 0, 1], dtype=dtype)
    if not np.allclose(result[..., 3, :], expected_bottom, atol=1e-6):
        raise ValueError(f"{context} matrices must be homogeneous SE(3)")
    rotations = result[..., :3, :3].astype(np.float64, copy=False)
    identity = np.eye(3)
    residual = rotations @ np.swapaxes(rotations, -1, -2) - identity
    if residual.size and float(np.abs(residual).max()) > 1e-4:
        raise ValueError(f"{context} rotations must be orthonormal")
    determinants = np.linalg.det(rotations)
    if determinants.size and float(np.abs(determinants - 1).max()) > 1e-4:
        raise ValueError(f"{context} rotations must have determinant +1")
    result = np.ascontiguousarray(result)
    result.setflags(write=False)
    return result


def read_poses_profile(
    data: NCoreComponentData,
    sequence_interval_us: tuple[int, int],
) -> NCoreSemanticComponent:
    require_version(data)
    items: list[NCoreItem] = []
    seen: dict[str, set[tuple[str, str]]] = {
        "static_pose": set(),
        "dynamic_pose": set(),
    }
    for kind, group_name in (
        ("static_pose", "static_poses"),
        ("dynamic_pose", "dynamic_poses"),
    ):
        entries = require_group(data, group_name).attributes
        for encoded_pair, raw_entry in sorted(entries.items()):
            pair = _frame_pair(encoded_pair, f"NCore {kind}")
            if pair in seen[kind] or pair[::-1] in seen[kind]:
                raise ValueError(f"NCore {kind} contains an inverse duplicate")
            seen[kind].add(pair)
            entry = mapping(raw_entry, f"NCore {kind} {pair}")
            matrices_key = "pose" if kind == "static_pose" else "poses"
            matrices = _pose_array(
                entry.get(matrices_key),
                entry.get("dtype"),
                f"NCore {kind} {pair}",
            )
            arrays: dict[str, np.ndarray] = {"transforms": matrices}
            if kind == "static_pose":
                if matrices.shape != (4, 4):
                    raise ValueError("NCore static pose must have shape (4, 4)")
            else:
                if matrices.ndim != 3 or len(matrices) < 2:
                    raise ValueError(
                        "NCore dynamic pose requires at least two (4, 4) matrices"
                    )
                raw_timestamps = sequence(
                    entry.get("timestamps_us"),
                    f"NCore dynamic pose {pair} timestamps",
                )
                normalized_timestamps = []
                for index, value in enumerate(raw_timestamps):
                    timestamp = integer(
                        value,
                        f"NCore dynamic pose {pair} timestamp {index}",
                    )
                    if timestamp > np.iinfo(np.uint64).max:
                        raise ValueError("NCore dynamic pose timestamp exceeds uint64")
                    normalized_timestamps.append(timestamp)
                timestamps = np.array(normalized_timestamps, dtype=np.uint64)
                if timestamps.shape != (len(matrices),):
                    raise ValueError(
                        "NCore dynamic pose timestamps must align with transforms"
                    )
                if len(timestamps) > 1 and not np.all(
                    timestamps[:-1] < timestamps[1:]
                ):
                    raise ValueError(
                        "NCore dynamic pose timestamps must be strictly increasing"
                    )
                for timestamp in timestamps:
                    validate_sequence_timestamp(
                        int(timestamp),
                        sequence_interval_us,
                        "NCore dynamic pose timestamp",
                    )
                timestamps.setflags(write=False)
                arrays["timestamps_us"] = timestamps
            items.append(
                NCoreItem(
                    kind=kind,
                    id=f"{pair[0]}->{pair[1]}",
                    arrays=arrays,
                    attributes={
                        "source_frame_id": pair[0],
                        "target_frame_id": pair[1],
                        "dtype": matrices.dtype.name,
                    },
                )
            )
    return NCoreSemanticComponent(
        raw=data,
        profile="poses/v1",
        items=tuple(items),
        attributes={"sequence_timestamp_interval_us": sequence_interval_us},
    )


def _positive_vector(
    parameters: Mapping[str, object], name: str, length: int, context: str
) -> np.ndarray:
    value = numeric_vector(parameters.get(name), length, f"{context}.{name}")
    if np.any(value <= 0):
        raise ValueError(f"{context}.{name} must be positive")
    return value


def _camera_parameters(attributes: Mapping[str, object], context: str) -> None:
    model = attributes.get("camera_model_type")
    if model not in _CAMERA_MODELS:
        raise ValueError(f"{context} has an unsupported camera model")
    parameters = mapping(attributes.get("camera_model_parameters"), context)
    resolution = sequence(parameters.get("resolution"), f"{context}.resolution")
    if len(resolution) != 2:
        raise ValueError(f"{context}.resolution must contain width/height")
    for index, value in enumerate(resolution):
        integer(value, f"{context}.resolution[{index}]", minimum=1)
        if value > np.iinfo(np.uint64).max:
            raise ValueError(f"{context}.resolution exceeds uint64")
    if parameters.get("shutter_type") not in _SHUTTER_TYPES:
        raise ValueError(f"{context} has an unsupported shutter type")
    principal = numeric_vector(
        parameters.get("principal_point"), 2, f"{context}.principal_point"
    )
    if not np.all(np.isfinite(principal)):
        raise ValueError(f"{context}.principal_point must be finite")
    if model in {"ideal-pinhole", "opencv-pinhole", "pinhole", "opencv-fisheye"}:
        _positive_vector(parameters, "focal_length", 2, context)
    if model in {"opencv-pinhole", "pinhole"}:
        numeric_vector(parameters.get("radial_coeffs"), 6, f"{context}.radial_coeffs")
        numeric_vector(
            parameters.get("tangential_coeffs"),
            2,
            f"{context}.tangential_coeffs",
        )
        numeric_vector(
            parameters.get("thin_prism_coeffs"),
            4,
            f"{context}.thin_prism_coeffs",
        )
    elif model == "opencv-fisheye":
        numeric_vector(parameters.get("radial_coeffs"), 4, f"{context}.radial_coeffs")
        if finite_number(parameters.get("max_angle"), f"{context}.max_angle") <= 0:
            raise ValueError(f"{context}.max_angle must be positive")
    elif model == "ftheta":
        if parameters.get("reference_poly") not in {
            "ANGLE_TO_PIXELDIST",
            "PIXELDIST_TO_ANGLE",
        }:
            raise ValueError(f"{context}.reference_poly is invalid")
        for name in ("pixeldist_to_angle_poly", "angle_to_pixeldist_poly"):
            value = numeric_vector(parameters.get(name), None, f"{context}.{name}")
            if len(value) > 6:
                raise ValueError(f"{context}.{name} has too many coefficients")
        numeric_vector(parameters.get("linear_cde"), 3, f"{context}.linear_cde")
        if finite_number(parameters.get("max_angle"), f"{context}.max_angle") <= 0:
            raise ValueError(f"{context}.max_angle must be positive")
    external_type = attributes.get("external_distortion_type")
    external = parameters.get("external_distortion_parameters")
    if external_type is None:
        if external is not None:
            raise ValueError(f"{context} external distortion lacks a type")
    elif external_type == "bivariate-windshield":
        distortion = mapping(external, f"{context}.external_distortion")
        if distortion.get("reference_poly") not in {"FORWARD", "BACKWARD"}:
            raise ValueError(f"{context} external reference polynomial is invalid")
        for name in (
            "horizontal_poly",
            "vertical_poly",
            "horizontal_poly_inverse",
            "vertical_poly_inverse",
        ):
            numeric_vector(
                distortion.get(name), None, f"{context}.external_distortion.{name}"
            )
    else:
        raise ValueError(f"{context} external distortion type is unsupported")


def _relative_angles(values: np.ndarray, direction: str) -> np.ndarray:
    delta = values - values[0] if direction == "ccw" else values[0] - values
    return np.mod(delta, 2 * math.pi)


def _lidar_parameters(attributes: Mapping[str, object], context: str) -> None:
    if attributes.get("lidar_model_type") != "row-offset-spinning":
        raise ValueError(f"{context} has an unsupported lidar model")
    parameters = mapping(attributes.get("lidar_model_parameters"), context)
    if finite_number(
        parameters.get("spinning_frequency_hz"),
        f"{context}.spinning_frequency_hz",
    ) <= 0:
        raise ValueError(f"{context}.spinning_frequency_hz must be positive")
    direction = parameters.get("spinning_direction")
    if direction not in {"cw", "ccw"}:
        raise ValueError(f"{context}.spinning_direction is invalid")
    rows = integer(parameters.get("n_rows"), f"{context}.n_rows", minimum=1)
    columns = integer(
        parameters.get("n_columns"), f"{context}.n_columns", minimum=1
    )
    elevations = numeric_vector(
        parameters.get("row_elevations_rad"), rows, f"{context}.row_elevations_rad"
    )
    offsets = numeric_vector(
        parameters.get("row_azimuth_offsets_rad"),
        rows,
        f"{context}.row_azimuth_offsets_rad",
    )
    azimuths = numeric_vector(
        parameters.get("column_azimuths_rad"),
        columns,
        f"{context}.column_azimuths_rad",
    )
    if len(elevations) > 1 and not np.all(
        np.diff(_relative_angles(elevations, "cw")) > 0
    ):
        raise ValueError(f"{context}.row_elevations_rad order is invalid")
    if len(azimuths) > 1 and not np.all(
        np.diff(_relative_angles(azimuths, str(direction))) > 0
    ):
        raise ValueError(f"{context}.column_azimuths_rad order is invalid")
    if not np.all(np.isfinite(offsets)):
        raise ValueError(f"{context}.row_azimuth_offsets_rad must be finite")


def read_intrinsics_profile(
    data: NCoreComponentData,
) -> NCoreSemanticComponent:
    require_version(data)
    require_group(data, "cameras")
    require_group(data, "lidars")
    items: list[NCoreItem] = []
    for parent, kind, validator in (
        ("cameras", "camera_intrinsics", _camera_parameters),
        ("lidars", "lidar_intrinsics", _lidar_parameters),
    ):
        for sensor_id in child_group_names(data, parent):
            non_empty_string(sensor_id, f"NCore {kind} id")
            attributes = require_group(data, f"{parent}/{sensor_id}").attributes
            validator(attributes, f"NCore {kind} {sensor_id!r}")
            items.append(
                NCoreItem(
                    kind=kind,
                    id=sensor_id,
                    attributes=attributes,
                )
            )
    return NCoreSemanticComponent(
        raw=data,
        profile="intrinsics/v1",
        items=tuple(items),
    )


def _encoded_mask(array: np.ndarray, context: str) -> None:
    if array.ndim == 0 and array.dtype.kind in {"S", "V"}:
        return
    if array.ndim == 1 and array.dtype == np.dtype("uint8"):
        return
    raise ValueError(f"{context} must be encoded bytes")


def read_masks_profile(data: NCoreComponentData) -> NCoreSemanticComponent:
    require_version(data)
    require_group(data, "cameras")
    items: list[NCoreItem] = []
    group_map = groups(data)
    for camera_id in child_group_names(data, "cameras"):
        camera_group = group_map[f"cameras/{camera_id}"]
        raw_names = sequence(
            camera_group.attributes.get("mask_names", ()),
            f"NCore masks {camera_id!r} names",
        )
        names = tuple(
            non_empty_string(name, f"NCore mask {camera_id!r} name")
            for name in raw_names
        )
        if len(names) != len(set(names)):
            raise ValueError(f"NCore masks {camera_id!r} names must be unique")
        for name in names:
            path = f"cameras/{camera_id}/{name}"
            try:
                array = data.arrays[path]
            except KeyError:
                raise ValueError(f"NCore mask array {path!r} is missing") from None
            _encoded_mask(array, f"NCore mask {path!r}")
            attributes = array_attributes(data, path)
            if attributes.get("format") != "png":
                raise ValueError(f"NCore mask {path!r} must use PNG")
            items.append(
                NCoreItem(
                    kind="camera_mask",
                    id=f"{camera_id}/{name}",
                    arrays={"data": array},
                    attributes={
                        "camera_id": camera_id,
                        "mask_name": name,
                        "format": "png",
                    },
                )
            )
    return NCoreSemanticComponent(
        raw=data,
        profile="masks/v1",
        items=tuple(items),
    )


__all__ = [
    "read_intrinsics_profile",
    "read_masks_profile",
    "read_poses_profile",
]
