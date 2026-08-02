"""Explicit coordinate conversion for qualified SceneIO records."""

from __future__ import annotations

import math

import numpy as np

from sceneio.coordinates import (
    COLMAP_COORDINATES,
    CoordinateConvention,
    coordinate_convention,
)


def _as_transform(value: object | None) -> np.ndarray:
    if value is None:
        return np.eye(4, dtype=np.float64)
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (4, 4) or not np.isfinite(result).all():
        raise ValueError("world_transform must be a finite (4,4) matrix")
    if not np.allclose(result[3], (0.0, 0.0, 0.0, 1.0), atol=1e-12):
        raise ValueError("world_transform must have bottom row [0,0,0,1]")
    determinant = float(np.linalg.det(result[:3, :3]))
    if not math.isfinite(determinant) or abs(determinant) < 1e-12:
        raise ValueError("world_transform must be invertible")
    return np.ascontiguousarray(result)


def _basis(source: str, target: str) -> np.ndarray:
    if source == target:
        return np.eye(4, dtype=np.float64)
    if {source, target} == {"opencv", "opengl"}:
        return np.diag((1.0, -1.0, -1.0, 1.0))
    raise ValueError(
        f"coordinate conversion from axes {source!r} to {target!r} "
        "requires world_transform"
    )


def _scale_pair(
    source: CoordinateConvention,
    target: CoordinateConvention,
    fallback: float,
) -> tuple[float, float]:
    source_scale = source.scale_to_meters
    if source_scale is None:
        source_scale = fallback
    target_scale = target.scale_to_meters
    if target_scale is None:
        target_scale = source_scale
    if source_scale <= 0.0 or target_scale <= 0.0:
        raise ValueError("coordinate conversion requires positive unit scales")
    return float(source_scale), float(target_scale)


def _quaternion_matrix(value: np.ndarray, order: str) -> np.ndarray:
    if order == "wxyz":
        w, x, y, z = (float(item) for item in value)
    elif order == "xyzw":
        x, y, z, w = (float(item) for item in value)
    else:
        raise ValueError(f"unsupported quaternion order {order!r}")
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("cannot convert a zero or non-finite quaternion")
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return np.array(
        (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
        ),
        dtype=np.float64,
    )


def _matrix_quaternion(rotation: np.ndarray, order: str) -> np.ndarray:
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
        w = (rotation[2, 1] - rotation[1, 2]) / scale
        x = 0.25 * scale
        y = (rotation[0, 1] + rotation[1, 0]) / scale
        z = (rotation[0, 2] + rotation[2, 0]) / scale
    elif rotation[1, 1] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
        w = (rotation[0, 2] - rotation[2, 0]) / scale
        x = (rotation[0, 1] + rotation[1, 0]) / scale
        y = 0.25 * scale
        z = (rotation[1, 2] + rotation[2, 1]) / scale
    else:
        scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
        w = (rotation[1, 0] - rotation[0, 1]) / scale
        x = (rotation[0, 2] + rotation[2, 0]) / scale
        y = (rotation[1, 2] + rotation[2, 1]) / scale
        z = 0.25 * scale
    quaternion = np.array((w, x, y, z), dtype=np.float64)
    quaternion /= np.linalg.norm(quaternion)
    if quaternion[0] < 0.0:
        quaternion = -quaternion
    if order == "wxyz":
        return quaternion
    if order == "xyzw":
        return quaternion[[1, 2, 3, 0]]
    raise ValueError(f"unsupported quaternion order {order!r}")


def _invert_rigid(matrix: np.ndarray) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = matrix[:3, :3].T
    result[:3, 3] = -result[:3, :3] @ matrix[:3, 3]
    return result


def _require_rigid_transform(matrix: np.ndarray) -> None:
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-10):
        raise ValueError("posed-view world_transform must be rigid")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-10):
        raise ValueError("posed-view world_transform must preserve handedness")


def _convert_posed_views(
    record: object,
    source: CoordinateConvention,
    target: CoordinateConvention,
    world_transform: np.ndarray,
) -> object:
    from sceneio import _core

    _require_rigid_transform(world_transform)
    if source.camera_axes not in {"opencv", "opengl"}:
        raise ValueError("posed-view source camera axes must be opencv or opengl")
    if target.camera_axes not in {"opencv", "opengl"}:
        raise ValueError("posed-view target camera axes must be opencv or opengl")
    if source.pose_direction not in {"world_to_camera", "camera_to_world"}:
        raise ValueError("posed-view source pose direction is not convertible")
    if target.pose_direction not in {"world_to_camera", "camera_to_world"}:
        raise ValueError("posed-view target pose direction is not convertible")
    for role, convention in (("source", source), ("target", target)):
        if convention.handedness != "right_handed":
            raise ValueError(f"posed-view {role} handedness must be right_handed")
        if convention.quaternion_algebra != "hamilton":
            raise ValueError(f"posed-view {role} quaternion algebra must be Hamilton")
        if (
            convention.image_origin != "upper_left"
            or convention.image_x_axis != "right"
            or convention.image_y_axis != "down"
            or convention.pixel_center != (0.5, 0.5)
        ):
            raise ValueError(
                f"posed-view {role} pixel convention is not representable"
            )
    if target.world_frame != "arbitrary" or target.reference_frame is not None:
        raise ValueError("posed-view target world frame is not representable")
    if target.crs is not None:
        raise ValueError("posed-view target CRS is not representable")
    source_scale, target_scale = _scale_pair(
        source,
        target,
        float(record.scale_to_meters),
    )
    camera_basis = _basis(source.camera_axes, target.camera_axes)
    inverse_world = np.linalg.inv(world_transform)
    source_quaternions = np.asarray(record.quaternions)
    source_translations = np.asarray(record.translations)
    quaternions = np.empty_like(source_quaternions, dtype=np.float64)
    translations = np.empty_like(source_translations, dtype=np.float64)
    for index, (quaternion, translation) in enumerate(
        zip(source_quaternions, source_translations, strict=True)
    ):
        pose = np.eye(4, dtype=np.float64)
        pose[:3, :3] = _quaternion_matrix(quaternion, source.quaternion_order)
        pose[:3, 3] = np.asarray(translation, dtype=np.float64) * source_scale
        world_to_camera = (
            pose if source.pose_direction == "world_to_camera" else _invert_rigid(pose)
        )
        converted = camera_basis @ world_to_camera @ inverse_world
        output = (
            converted
            if target.pose_direction == "world_to_camera"
            else _invert_rigid(converted)
        )
        quaternions[index] = _matrix_quaternion(
            output[:3, :3],
            target.quaternion_order,
        )
        translations[index] = output[:3, 3] / target_scale
    timestamps = np.asarray(record.timestamps)
    camera_indices = np.asarray(record.camera_indices)
    cameras = list(record.cameras)
    return _core.posed_view_set(
        np.ascontiguousarray(quaternions),
        np.ascontiguousarray(translations),
        names=list(record.names) or None,
        timestamps=(np.ascontiguousarray(timestamps) if timestamps.size else None),
        quaternion_order=target.quaternion_order,
        pose_convention=target.pose_direction,
        axis_frame=target.camera_axes,
        scale_to_meters=target_scale,
        camera_indices=(
            np.ascontiguousarray(camera_indices, dtype=np.int32)
            if camera_indices.size or cameras
            else None
        ),
        cameras=cameras or None,
    )


def _coordinate_transform(
    source: CoordinateConvention,
    target: CoordinateConvention,
    fallback_scale: float,
    world_transform: object | None,
) -> tuple[np.ndarray, float]:
    source_scale, target_scale = _scale_pair(source, target, fallback_scale)
    if world_transform is None:
        if source.camera_axes not in {"opencv", "opengl"}:
            raise ValueError(
                "an unknown or world coordinate frame requires world_transform"
            )
        if target.camera_axes not in {"opencv", "opengl"}:
            raise ValueError("target coordinate axes are not convertible")
        transform = _basis(source.camera_axes, target.camera_axes)
    else:
        transform = _as_transform(world_transform)
    scaled = transform.copy()
    scaled[:3, :3] *= source_scale / target_scale
    scaled[:3, 3] /= target_scale
    return scaled, target_scale


def _optional_array(record: object, name: str, predicate: str) -> np.ndarray | None:
    if not bool(getattr(record, predicate)):
        return None
    return np.ascontiguousarray(np.asarray(getattr(record, name)))


def _transform_vectors(values: np.ndarray | None, matrix: np.ndarray) -> np.ndarray | None:
    if values is None:
        return None
    return np.ascontiguousarray(values @ matrix[:3, :3].T, dtype=values.dtype)


def _transform_normals(values: np.ndarray | None, matrix: np.ndarray) -> np.ndarray | None:
    if values is None:
        return None
    normal_matrix = np.linalg.inv(matrix[:3, :3]).T
    converted = np.asarray(values, dtype=np.float64) @ normal_matrix.T
    lengths = np.linalg.norm(converted, axis=1)
    nonzero = lengths > 0.0
    converted[nonzero] /= lengths[nonzero, None]
    return np.ascontiguousarray(converted, dtype=values.dtype)


def _target_frame(target: CoordinateConvention, record_name: str) -> str:
    if target.crs is not None or target.reference_frame is not None:
        raise ValueError(f"{record_name} target reference frame is not representable")
    if target.camera_axes in {"opencv", "opengl"}:
        result = target.camera_axes
    elif target.world_frame in {"enu", "ned"}:
        result = target.world_frame
    elif target.camera_axes in {"unknown", "not_applicable"} and target.world_frame in {
        "unknown",
        "arbitrary",
        "not_applicable",
    }:
        result = "unknown"
    else:
        raise ValueError(f"{record_name} target coordinate frame is not representable")
    if result != "unknown" and target.handedness != "right_handed":
        raise ValueError(f"{record_name} target handedness must be right_handed")
    return result


def _convert_point_cloud(
    record: object,
    source: CoordinateConvention,
    target: CoordinateConvention,
    world_transform: object | None,
) -> object:
    from sceneio import _core

    if record.has_las_waveform:
        raise ValueError(
            "coordinate conversion cannot preserve an opaque LAS waveform sidecar"
        )
    default_viewpoint = np.array(
        (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
        dtype=np.float64,
    )
    if not np.array_equal(np.asarray(record.viewpoint), default_viewpoint):
        raise ValueError(
            "coordinate conversion of a non-default acquisition viewpoint "
            "is not qualified"
        )
    transform, target_scale = _coordinate_transform(
        source,
        target,
        float(record.scale_to_meters),
        world_transform,
    )
    positions = np.asarray(record.positions)
    converted_positions = _transform_vectors(positions, transform)
    origin_h = np.ones(4, dtype=np.float64)
    origin_h[:3] = np.asarray(record.origin, dtype=np.float64)
    converted_origin = transform @ origin_h
    normals = _transform_normals(
        _optional_array(record, "normals", "has_normals"),
        transform,
    )
    return _core.point_cloud(
        converted_positions,
        colors=_optional_array(record, "colors", "has_rgb"),
        normals=normals,
        intensity=_optional_array(record, "intensities", "has_intensity"),
        coordinate_frame=_target_frame(target, "point cloud"),
        scale_to_meters=target_scale,
        intensity_range=record.intensity_range,
        colors16=_optional_array(record, "colors16", "has_rgb16"),
        origin=np.ascontiguousarray(converted_origin[:3]),
        width=record.width if record.is_organized else None,
        height=record.height if record.is_organized else None,
        viewpoint=default_viewpoint,
        display_colors=_optional_array(record, "display_colors", "has_display_colors"),
        display_opacities=_optional_array(
            record,
            "display_opacities",
            "has_display_opacities",
        ),
        widths=_optional_array(record, "widths", "has_widths"),
        ids=_optional_array(record, "ids", "has_ids"),
        velocities=_transform_vectors(
            _optional_array(record, "velocities", "has_velocities"),
            transform,
        ),
        accelerations=_transform_vectors(
            _optional_array(record, "accelerations", "has_accelerations"),
            transform,
        ),
        display_color_space=record.display_color_space,
    )


def _convert_mesh(
    record: object,
    source: CoordinateConvention,
    target: CoordinateConvention,
    world_transform: object | None,
) -> object:
    from sceneio import _core

    transform, target_scale = _coordinate_transform(
        source,
        target,
        float(record.scale_to_meters),
        world_transform,
    )
    if np.linalg.det(transform[:3, :3]) < 0.0:
        raise ValueError(
            "mesh coordinate conversion with a reflection requires an "
            "explicit winding policy"
        )
    inverse_transform = np.linalg.inv(transform)
    local_transform = transform @ np.asarray(record.local_transform) @ inverse_transform
    positions = np.asarray(record.positions)
    positions_h = np.column_stack((positions, np.ones(len(positions))))
    converted_positions = np.ascontiguousarray(
        (positions_h @ transform.T)[:, :3],
        dtype=np.float32,
    )
    def optional(name: str, predicate: str) -> np.ndarray | None:
        return _optional_array(record, name, predicate)

    return _core.mesh(
        converted_positions,
        np.ascontiguousarray(np.asarray(record.face_offsets)),
        np.ascontiguousarray(np.asarray(record.face_indices)),
        vertex_normals=_transform_normals(
            optional("vertex_normals", "has_vertex_normals"),
            transform,
        ),
        corner_normals=_transform_normals(
            optional("corner_normals", "has_corner_normals"),
            transform,
        ),
        vertex_uvs=optional("vertex_uvs", "has_vertex_uvs"),
        corner_uvs=optional("corner_uvs", "has_corner_uvs"),
        vertex_colors=optional("vertex_colors", "has_vertex_colors"),
        corner_colors=optional("corner_colors", "has_corner_colors"),
        primitive_offsets=np.ascontiguousarray(np.asarray(record.primitive_offsets)),
        primitive_materials=np.ascontiguousarray(np.asarray(record.primitive_materials)),
        face_smoothing_groups=optional(
            "face_smoothing_groups",
            "has_face_smoothing_groups",
        ),
        primitive_object_names=list(record.primitive_object_names),
        primitive_group_names=list(record.primitive_group_names),
        materials=record.materials if record.has_materials else None,
        coordinate_frame=_target_frame(target, "mesh"),
        scale_to_meters=target_scale,
        local_transform=np.ascontiguousarray(local_transform),
        vertex_display_colors=optional(
            "vertex_display_colors",
            "has_vertex_display_colors",
        ),
        corner_display_colors=optional(
            "corner_display_colors",
            "has_corner_display_colors",
        ),
        vertex_display_opacities=optional(
            "vertex_display_opacities",
            "has_vertex_display_opacities",
        ),
        corner_display_opacities=optional(
            "corner_display_opacities",
            "has_corner_display_opacities",
        ),
        display_color_space=record.display_color_space,
        orientation=record.orientation,
        double_sided=record.double_sided,
    )


def convert_coordinates(
    record: object,
    target: CoordinateConvention = COLMAP_COORDINATES,
    *,
    source: CoordinateConvention | None = None,
    world_transform: object | None = None,
) -> object:
    """Explicitly convert a qualified record to ``target`` coordinates.

    Ordinary I/O never calls this function.  Unknown spatial frames require a
    caller-supplied ``source`` convention or ``world_transform``.
    """

    if not isinstance(target, CoordinateConvention):
        raise TypeError("target must be a CoordinateConvention")
    actual_source = source or coordinate_convention(record)
    if actual_source is None:
        raise TypeError(f"{type(record).__name__} has no coordinate semantics")
    if not isinstance(actual_source, CoordinateConvention):
        raise TypeError("source must be a CoordinateConvention")
    if actual_source == target and world_transform is None:
        return record
    type_name = type(record).__name__
    if type_name == "PosedViewSet":
        return _convert_posed_views(
            record,
            actual_source,
            target,
            _as_transform(world_transform),
        )
    if type_name == "PointCloud":
        return _convert_point_cloud(record, actual_source, target, world_transform)
    if type_name == "Mesh":
        return _convert_mesh(record, actual_source, target, world_transform)
    raise TypeError(
        f"coordinate conversion for {type_name} is not qualified; "
        "use its format-specific adapter"
    )


__all__ = ["convert_coordinates"]
