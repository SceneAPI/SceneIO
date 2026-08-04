"""Coordinate-system contracts shared by SceneIO records and codecs.

SceneIO keeps decoded values in their source convention.  These immutable
objects describe how those values must be interpreted and make the COLMAP
camera convention available as an explicit conversion target.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal

CoordinateStatus = Literal["fixed", "file_declared", "unspecified", "not_applicable"]
CoordinateDomain = Literal[
    "camera",
    "depth",
    "image",
    "spatial",
    "tensor",
    "trajectory",
]

_COORDINATE_DOMAINS = frozenset(
    {"camera", "depth", "image", "spatial", "tensor", "trajectory"}
)
_CONVERSION_POLICIES = frozenset(
    {"supported", "requires_context", "not_applicable"}
)

_AXES = frozenset(
    {
        "opencv",
        "opengl",
        "enu",
        "ned",
        "ecef",
        "reference",
        "unknown",
        "not_applicable",
        "file_declared",
    }
)
_HANDEDNESS = frozenset(
    {"right_handed", "left_handed", "unknown", "not_applicable", "file_declared"}
)
_POSE_DIRECTIONS = frozenset(
    {
        "world_to_camera",
        "camera_to_world",
        "sensor_to_reference",
        "reference_to_sensor",
        "node_to_reference",
        "not_applicable",
        "unknown",
        "file_declared",
    }
)
_QUATERNION_ORDERS = frozenset(
    {"wxyz", "xyzw", "not_applicable", "unknown", "file_declared"}
)
_QUATERNION_ALGEBRAS = frozenset(
    {"hamilton", "not_applicable", "unknown", "file_declared"}
)
_WORLD_FRAMES = frozenset(
    {
        "arbitrary",
        "first_view",
        "enu",
        "ned",
        "ecef",
        "reference",
        "unknown",
        "not_applicable",
        "file_declared",
    }
)
_UP_AXES = frozenset(
    {"x", "y", "z", "unknown", "not_applicable", "file_declared"}
)
_SCALE_CLASSES = frozenset(
    {"arbitrary", "normalized", "metric", "unknown", "not_applicable", "file_declared"}
)
_IMAGE_ORIGINS = frozenset(
    {"upper_left", "lower_left", "unknown", "not_applicable", "file_declared"}
)
_DEPTH_INTERPRETATIONS = frozenset(
    {
        "camera_z",
        "ray_distance",
        "disparity",
        "unknown",
        "not_applicable",
        "file_declared",
    }
)


@dataclass(frozen=True, slots=True)
class CoordinateConvention:
    """Complete interpretation of one record's coordinate-bearing values.

    ``scale_to_meters`` is ``None`` when scale is arbitrary, unknown, or not
    applicable.  A metric convention must provide a finite positive value.
    ``pixel_center`` is measured from the upper-left image corner.
    """

    name: str = field(compare=False)
    camera_axes: str = "not_applicable"
    handedness: str = "not_applicable"
    pose_direction: str = "not_applicable"
    quaternion_order: str = "not_applicable"
    quaternion_algebra: str = "not_applicable"
    world_frame: str = "not_applicable"
    up_axis: str = "not_applicable"
    scale_class: str = "not_applicable"
    scale_to_meters: float | None = None
    image_origin: str = "not_applicable"
    image_x_axis: str = "not_applicable"
    image_y_axis: str = "not_applicable"
    pixel_center: tuple[float, float] | None = None
    depth_interpretation: str = "not_applicable"
    crs: str | None = None
    reference_frame: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("CoordinateConvention.name must be non-empty")
        choices = (
            ("camera_axes", self.camera_axes, _AXES),
            ("handedness", self.handedness, _HANDEDNESS),
            ("pose_direction", self.pose_direction, _POSE_DIRECTIONS),
            ("quaternion_order", self.quaternion_order, _QUATERNION_ORDERS),
            ("quaternion_algebra", self.quaternion_algebra, _QUATERNION_ALGEBRAS),
            ("world_frame", self.world_frame, _WORLD_FRAMES),
            ("up_axis", self.up_axis, _UP_AXES),
            ("scale_class", self.scale_class, _SCALE_CLASSES),
            ("image_origin", self.image_origin, _IMAGE_ORIGINS),
            ("depth_interpretation", self.depth_interpretation, _DEPTH_INTERPRETATIONS),
        )
        for field_name, value, accepted in choices:
            if value not in accepted:
                raise ValueError(
                    f"CoordinateConvention.{field_name} must be one of "
                    f"{sorted(accepted)!r}, got {value!r}"
                )
        for field_name, value, accepted in (
            ("image_x_axis", self.image_x_axis, {"right", "left", "unknown", "not_applicable", "file_declared"}),
            ("image_y_axis", self.image_y_axis, {"down", "up", "unknown", "not_applicable", "file_declared"}),
        ):
            if value not in accepted:
                raise ValueError(
                    f"CoordinateConvention.{field_name} must be one of "
                    f"{sorted(accepted)!r}, got {value!r}"
                )
        if self.scale_to_meters is not None:
            if (
                isinstance(self.scale_to_meters, bool)
                or not isinstance(self.scale_to_meters, int | float)
                or not math.isfinite(float(self.scale_to_meters))
                or self.scale_to_meters <= 0.0
            ):
                raise ValueError("scale_to_meters must be finite and positive")
            object.__setattr__(self, "scale_to_meters", float(self.scale_to_meters))
        if self.scale_class == "metric" and self.scale_to_meters is None:
            raise ValueError("metric conventions require scale_to_meters")
        if self.scale_class != "metric" and self.scale_to_meters is not None:
            raise ValueError("only metric conventions may define scale_to_meters")
        if self.pixel_center is not None:
            if self.image_origin in {"not_applicable", "unknown"}:
                raise ValueError("pixel_center requires a declared image origin")
            if (
                not isinstance(self.pixel_center, tuple)
                or len(self.pixel_center) != 2
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, int | float)
                    or not math.isfinite(float(value))
                    for value in self.pixel_center
                )
            ):
                raise ValueError("pixel_center must contain two finite numbers")
            object.__setattr__(
                self,
                "pixel_center",
                tuple(float(value) for value in self.pixel_center),
            )
        if (
            self.quaternion_order
            not in {"not_applicable", "unknown", "file_declared"}
            and self.quaternion_algebra != "hamilton"
        ):
            raise ValueError("stored quaternions require Hamilton algebra")
        if self.crs is not None and (not isinstance(self.crs, str) or not self.crs):
            raise ValueError("crs must be a non-empty string or None")
        if self.reference_frame is not None and (
            not isinstance(self.reference_frame, str) or not self.reference_frame
        ):
            raise ValueError("reference_frame must be a non-empty string or None")


@dataclass(frozen=True, slots=True)
class FormatCoordinateContract:
    """Static coordinate capabilities of one registered format."""

    status: CoordinateStatus
    domains: tuple[CoordinateDomain, ...]
    decoded: CoordinateConvention | None
    writer_requirement: str
    conversion: Literal["supported", "requires_context", "not_applicable"]
    reference: str

    def __post_init__(self) -> None:
        if self.status not in {"fixed", "file_declared", "unspecified", "not_applicable"}:
            raise ValueError(f"invalid coordinate status {self.status!r}")
        object.__setattr__(self, "domains", tuple(self.domains))
        if any(domain not in _COORDINATE_DOMAINS for domain in self.domains):
            raise ValueError("coordinate contract contains an invalid domain")
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("coordinate domains must be unique")
        if self.decoded is not None and not isinstance(
            self.decoded, CoordinateConvention
        ):
            raise TypeError("decoded must be a CoordinateConvention or None")
        if self.status == "fixed" and self.decoded is None:
            raise ValueError("fixed coordinate contracts require a decoded convention")
        if self.status == "file_declared" and self.decoded is not None:
            raise ValueError("file-declared contracts resolve conventions per file")
        if self.status == "not_applicable" and (self.domains or self.decoded is not None):
            raise ValueError("not-applicable contracts cannot define domains or a convention")
        if not isinstance(self.writer_requirement, str) or not self.writer_requirement:
            raise ValueError("writer_requirement must be non-empty")
        if self.conversion not in _CONVERSION_POLICIES:
            raise ValueError(f"invalid coordinate conversion policy {self.conversion!r}")
        if self.status == "not_applicable" and self.conversion != "not_applicable":
            raise ValueError("not-applicable coordinates require not-applicable conversion")
        if not isinstance(self.reference, str) or not self.reference:
            raise ValueError("reference must be non-empty")


COLMAP_COORDINATES = CoordinateConvention(
    name="colmap",
    camera_axes="opencv",
    handedness="right_handed",
    pose_direction="world_to_camera",
    quaternion_order="wxyz",
    quaternion_algebra="hamilton",
    world_frame="arbitrary",
    scale_class="arbitrary",
    image_origin="upper_left",
    image_x_axis="right",
    image_y_axis="down",
    pixel_center=(0.5, 0.5),
    depth_interpretation="camera_z",
)

UNKNOWN_COORDINATES = CoordinateConvention(
    name="unknown",
    camera_axes="unknown",
    handedness="unknown",
    pose_direction="unknown",
    quaternion_order="unknown",
    quaternion_algebra="unknown",
    world_frame="unknown",
    scale_class="unknown",
    image_origin="unknown",
    image_x_axis="unknown",
    image_y_axis="unknown",
    depth_interpretation="unknown",
)

IMAGE_COORDINATES = CoordinateConvention(
    name="sceneio_image",
    image_origin="upper_left",
    image_x_axis="right",
    image_y_axis="down",
    pixel_center=(0.5, 0.5),
)

_HLOC_IMAGE_COORDINATES = replace(
    IMAGE_COORDINATES,
    name="hloc_image",
    pixel_center=(0.0, 0.0),
)

_COLMAP_CAMERA_COORDINATES = replace(
    IMAGE_COORDINATES,
    name="colmap_camera",
    camera_axes="opencv",
    handedness="right_handed",
)

_COLMAP_DEPTH_COORDINATES = replace(
    _COLMAP_CAMERA_COORDINATES,
    name="colmap_camera_z_depth",
    scale_class="arbitrary",
    depth_interpretation="camera_z",
)

_COLMAP_NORMAL_COORDINATES = replace(
    _COLMAP_CAMERA_COORDINATES,
    name="colmap_camera_normal",
)

FILE_DECLARED_COORDINATES = CoordinateConvention(
    name="file_declared",
    camera_axes="file_declared",
    handedness="file_declared",
    pose_direction="file_declared",
    quaternion_order="file_declared",
    quaternion_algebra="file_declared",
    world_frame="file_declared",
    up_axis="file_declared",
    scale_class="file_declared",
    image_origin="file_declared",
    image_x_axis="file_declared",
    image_y_axis="file_declared",
    depth_interpretation="file_declared",
)

UNSPECIFIED_FORMAT_COORDINATES = FormatCoordinateContract(
    status="unspecified",
    domains=(),
    decoded=UNKNOWN_COORDINATES,
    writer_requirement="the extension must declare its coordinate behavior",
    conversion="requires_context",
    reference="third-party codec declaration",
)


def _spatial_convention(
    name: str,
    frame: str,
    scale_to_meters: float,
    *,
    pose_direction: str = "not_applicable",
    quaternion_order: str = "not_applicable",
    image: bool = False,
) -> CoordinateConvention:
    metric = frame != "unknown" or scale_to_meters != 1.0
    kwargs: dict[str, object] = {
        "name": name,
        "handedness": (
            "right_handed"
            if frame in {"opencv", "opengl", "enu", "ned", "ecef"}
            else "unknown"
        ),
        "pose_direction": pose_direction,
        "quaternion_order": quaternion_order,
        "quaternion_algebra": (
            "hamilton" if quaternion_order in {"wxyz", "xyzw"} else "not_applicable"
        ),
        "world_frame": frame if frame in {"enu", "ned", "ecef"} else "arbitrary",
        "up_axis": "z" if frame == "enu" else "unknown",
        "scale_class": "metric" if metric else "unknown",
        "scale_to_meters": float(scale_to_meters) if metric else None,
    }
    if frame in {"opencv", "opengl"}:
        kwargs["camera_axes"] = frame
    elif frame == "unknown":
        kwargs["camera_axes"] = "unknown"
        kwargs["world_frame"] = "unknown"
    if image:
        kwargs.update(
            image_origin="upper_left",
            image_x_axis="right",
            image_y_axis="down",
            pixel_center=(0.5, 0.5),
        )
    return CoordinateConvention(**kwargs)


def coordinate_convention(record: object) -> CoordinateConvention | None:
    """Return the coordinate interpretation recorded by ``record``.

    The function is intentionally type-name based so importing this lightweight
    contract module never loads the compiled codec extension.
    """

    type_name = type(record).__name__
    if type_name in {"Image", "ImageSequence", "Mask"}:
        return IMAGE_COORDINATES
    if type_name == "Reconstruction":
        return COLMAP_COORDINATES
    if type_name == "PosedViewSet" and hasattr(record, "axis_frame"):
        return _spatial_convention(
            "posed_view_set",
            str(record.axis_frame),
            float(record.scale_to_meters),
            pose_direction=str(record.pose_convention),
            quaternion_order=str(record.quaternion_order),
            image=True,
        )
    if type_name == "PosedViewSet" and hasattr(record, "frame"):
        conventions = {pose.convention for pose in record.poses}
        pose_direction = {
            "opencv_cam2world": "camera_to_world",
            "opencv_world2cam": "world_to_camera",
        }.get(next(iter(conventions), ""), "unknown")
        frame_name = str(record.frame.world_frame)
        world_frame = (
            frame_name
            if frame_name in {"arbitrary", "first_view", "enu", "ned", "ecef"}
            else "reference"
        )
        metric = record.frame.scale == "metric"
        return CoordinateConvention(
            name="contract_posed_view_set",
            camera_axes="opencv",
            handedness="right_handed",
            pose_direction=pose_direction,
            world_frame=world_frame,
            up_axis="z" if world_frame in {"enu", "ned"} else "unknown",
            scale_class=str(record.frame.scale),
            scale_to_meters=1.0 if metric else None,
            image_origin="upper_left",
            image_x_axis="right",
            image_y_axis="down",
            pixel_center=(0.5, 0.5),
            reference_frame=(
                None if world_frame == frame_name else frame_name
            ),
        )
    if type_name == "CameraRig":
        direction = {
            "reference_to_camera": "world_to_camera",
            "camera_to_reference": "camera_to_world",
        }.get(str(record.transform_convention), "unknown")
        return _spatial_convention(
            "camera_rig",
            str(record.axis_frame),
            float(record.scale_to_meters),
            pose_direction=direction,
            quaternion_order=str(record.quaternion_order),
            image=True,
        )
    if type_name == "ImuCalibration":
        axis_frame = str(record.sensor_axis_frame)
        return CoordinateConvention(
            name="imu_calibration",
            camera_axes=(
                axis_frame if axis_frame in {"enu", "ned"} else "unknown"
            ),
            handedness=(
                "right_handed" if axis_frame in {"enu", "ned"} else "unknown"
            ),
            pose_direction="sensor_to_reference",
            quaternion_order=str(record.quaternion_order),
            quaternion_algebra="hamilton",
            world_frame="reference",
            scale_class="metric",
            scale_to_meters=1.0,
            reference_frame=str(record.reference_frame),
        )
    if type_name == "ImuSequence":
        axis_frame = str(record.sensor_axis_frame)
        return CoordinateConvention(
            name="imu_sequence",
            camera_axes=(axis_frame if axis_frame in {"enu", "ned"} else "unknown"),
            handedness=(
                "right_handed" if axis_frame in {"enu", "ned"} else "unknown"
            ),
            world_frame=(axis_frame if axis_frame in {"enu", "ned"} else "unknown"),
        )
    if type_name in {"PointCloud", "Mesh"}:
        return _spatial_convention(
            type_name.lower(),
            str(record.coordinate_frame),
            float(record.scale_to_meters),
        )
    if type_name == "GaussianCloud":
        return UNKNOWN_COORDINATES
    if type_name == "SceneGraph":
        return CoordinateConvention(
            name="usd_stage",
            camera_axes="file_declared",
            handedness="right_handed",
            world_frame="reference",
            up_axis=str(record.up_axis),
            scale_class="metric",
            scale_to_meters=float(record.meters_per_unit),
        )
    if type_name == "MeshScene":
        return CoordinateConvention(
            name="gltf_scene",
            camera_axes="opengl",
            handedness="right_handed",
            world_frame="reference",
            up_axis="y",
            scale_class="metric",
            scale_to_meters=1.0,
        )
    if type_name == "StateTrajectory":
        scale = 1.0 if record.position_unit == "meters" else 0.001
        return CoordinateConvention(
            name="state_trajectory",
            handedness="right_handed",
            pose_direction=str(record.pose_convention),
            quaternion_order=str(record.quaternion_order),
            quaternion_algebra="hamilton",
            world_frame="reference",
            scale_class="metric",
            scale_to_meters=scale,
        )
    if type_name == "PoseGraph":
        metric = record.translation_unit != "unspecified"
        return CoordinateConvention(
            name="pose_graph",
            camera_axes="unknown",
            handedness="right_handed",
            pose_direction="node_to_reference",
            quaternion_order=str(record.quaternion_order),
            quaternion_algebra="hamilton",
            world_frame="reference",
            scale_class="metric" if metric else "unknown",
            scale_to_meters=1.0 if metric else None,
        )
    if type_name == "DepthMap" and hasattr(record, "depth_convention"):
        scale = float(record.scale_to_meters)
        metric = scale > 0.0
        return CoordinateConvention(
            name="depth_map",
            scale_class="metric" if metric else "unknown",
            scale_to_meters=scale if metric else None,
            image_origin="upper_left",
            image_x_axis="right",
            image_y_axis="down",
            pixel_center=(0.5, 0.5),
            depth_interpretation={
                "camera_z": "camera_z",
                "ray_distance": "ray_distance",
                "unspecified": "unknown",
            }.get(str(record.depth_convention), "unknown"),
        )
    if type_name == "DepthMap":
        return replace(
            IMAGE_COORDINATES,
            name="camera_depth_map",
            camera_axes="unknown",
            handedness="unknown",
            depth_interpretation="camera_z",
        )
    if type_name == "Pointmap":
        frame = str(record.frame)
        return CoordinateConvention(
            name=f"pointmap_{frame}",
            camera_axes="unknown" if frame == "camera" else "not_applicable",
            handedness="unknown",
            world_frame="arbitrary" if frame == "world" else "not_applicable",
            scale_class="unknown",
            image_origin="upper_left",
            image_x_axis="right",
            image_y_axis="down",
            pixel_center=(0.5, 0.5),
        )
    if type_name in {"CameraIntrinsics", "Calibration", "RayMap"}:
        return _COLMAP_CAMERA_COORDINATES
    if type_name == "ViewInput":
        return (
            IMAGE_COORDINATES
            if record.calibration is None
            else coordinate_convention(record.calibration)
        )
    if type_name in {"SE3", "Sim3"}:
        direction = {
            "opencv_cam2world": "camera_to_world",
            "opencv_world2cam": "world_to_camera",
        }.get(str(record.convention), "unknown")
        return CoordinateConvention(
            name=type_name.lower(),
            camera_axes="opencv",
            handedness="right_handed",
            pose_direction=direction,
            world_frame="arbitrary",
            scale_class="arbitrary",
        )
    if type_name == "PosePrior":
        convention = coordinate_convention(record.pose)
        if record.is_metric:
            return replace(
                convention,
                name="metric_pose_prior",
                scale_class="metric",
                scale_to_meters=1.0,
            )
        return convention
    if type_name == "FrameMeta":
        frame_name = str(record.world_frame)
        world_frame = (
            frame_name
            if frame_name in {"arbitrary", "first_view", "enu", "ned", "ecef"}
            else "reference"
        )
        metric = record.scale == "metric"
        return CoordinateConvention(
            name="frame_meta",
            handedness="unknown",
            world_frame=world_frame,
            up_axis="z" if world_frame in {"enu", "ned"} else "unknown",
            scale_class=str(record.scale),
            scale_to_meters=1.0 if metric else None,
            reference_frame=(
                None if world_frame == frame_name else frame_name
            ),
        )
    if type_name == "FlowField":
        return replace(
            IMAGE_COORDINATES,
            name="flow_field",
        )
    if type_name == "NormalMap":
        return _COLMAP_NORMAL_COORDINATES
    if type_name in {"Camera", "ColmapDatabase"}:
        return _COLMAP_CAMERA_COORDINATES
    if type_name == "FeatureSet" and hasattr(record, "pixel_center"):
        return replace(
            IMAGE_COORDINATES,
            name="feature_pixels",
            pixel_center=tuple(float(value) for value in record.pixel_center),
        )
    if type_name == "HlocFeatureStore":
        return _HLOC_IMAGE_COORDINATES
    if type_name == "HlocMatchStore":
        return None
    if type_name == "PairCorrespondences":
        return IMAGE_COORDINATES if record.mode == "coordinates" else None
    if type_name == "CorrespondenceGraph":
        conventions = {
            coordinate_convention(feature)
            for feature in record.features.values()
        }
        if any(pair.mode == "coordinates" for pair in record.pairs.values()):
            conventions.add(IMAGE_COORDINATES)
        conventions.discard(None)
        if not conventions:
            return None
        if len(conventions) == 1:
            return conventions.pop()
        return UNKNOWN_COORDINATES
    if type_name == "TwoViewGeometry":
        return None
    if type_name == "MatchGraph":
        return _COLMAP_CAMERA_COORDINATES
    if type_name in {"ConsistencyGraph", "FeatureSet"}:
        return IMAGE_COORDINATES
    if type_name in {"NCoreDataset", "NCoreDatasetData"}:
        return FILE_DECLARED_COORDINATES
    if type_name in {"ConfidenceMap", "Mask"}:
        return IMAGE_COORDINATES
    if type_name == "TrackedPointCloud":
        return CoordinateConvention(
            name="tracked_point_cloud",
            camera_axes="unknown",
            handedness="unknown",
            world_frame="unknown",
            scale_class="unknown",
        )
    if type_name in {"PointVisibility", "TensorDict", "_MappedArray", "ndarray"}:
        return None if type_name == "PointVisibility" else UNKNOWN_COORDINATES
    if type_name == "RtmvDataset":
        return coordinate_convention(record.views)
    return None


def inspection_coordinate_convention(
    format_id: str,
    metadata: object,
) -> CoordinateConvention | None:
    """Resolve a file inspection's convention without decoding bulk data."""

    from sceneio.io._registry.coordinates import codec_coordinate_contract

    contract = codec_coordinate_contract(format_id)
    if contract.status in {"fixed", "unspecified", "not_applicable"}:
        return contract.decoded
    if not hasattr(metadata, "get"):
        return FILE_DECLARED_COORDINATES
    up_axis = metadata.get("up_axis")
    meters_per_unit = metadata.get("meters_per_unit")
    if up_axis in {"y", "z"} and isinstance(meters_per_unit, int | float):
        return CoordinateConvention(
            name=f"{format_id}_stage",
            camera_axes="file_declared",
            handedness="right_handed",
            world_frame="reference",
            up_axis=str(up_axis),
            scale_class="metric",
            scale_to_meters=float(meters_per_unit),
        )
    frame = metadata.get("coordinate_frame")
    scale = metadata.get("scale_to_meters")
    if isinstance(frame, str) and isinstance(scale, int | float):
        return _spatial_convention(format_id, frame, float(scale))
    return FILE_DECLARED_COORDINATES


def install_coordinate_properties(*record_types: type) -> None:
    """Install the additive ``.coordinates`` view on extension records."""

    for record_type in record_types:
        if not hasattr(record_type, "coordinates"):
            record_type.coordinates = property(coordinate_convention)


def install_core_coordinate_properties(core: object) -> None:
    """Install coordinate views on all coordinate-bearing native records."""

    names = (
        "Reconstruction",
        "GaussianCloud",
        "PosedViewSet",
        "StateTrajectory",
        "ImuCalibration",
        "ImuSequence",
        "TensorDict",
        "Image",
        "ImageSequence",
        "PointCloud",
        "Mesh",
        "MeshScene",
        "SceneGraph",
        "PoseGraph",
        "FeatureSet",
        "MatchGraph",
        "DepthMap",
        "FlowField",
        "NormalMap",
        "ConsistencyGraph",
        "PointVisibility",
        "Camera",
        "CameraRig",
        "ColmapDatabase",
    )
    install_coordinate_properties(
        *(getattr(core, name) for name in names if hasattr(core, name))
    )


__all__ = [
    "COLMAP_COORDINATES",
    "FILE_DECLARED_COORDINATES",
    "IMAGE_COORDINATES",
    "UNKNOWN_COORDINATES",
    "UNSPECIFIED_FORMAT_COORDINATES",
    "CoordinateConvention",
    "FormatCoordinateContract",
    "coordinate_convention",
    "inspection_coordinate_convention",
    "install_coordinate_properties",
    "install_core_coordinate_properties",
]
