"""Versioned normalization and scaling contracts for public representations.

The contracts in this module describe in-memory values, not file encodings.
They deliberately separate structural normalization from physical scaling:
canonical dtypes or array layouts do not imply metric coordinates, normalized
colors, unit vectors, or activated Gaussian attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

NormalizationPolicy = Literal[
    "canonical",
    "preserve",
    "declared",
    "mixed",
    "aggregate",
    "not_applicable",
]
ScalePolicy = Literal[
    "identity",
    "pixel",
    "metric",
    "arbitrary",
    "record_declared",
    "component_declared",
    "mixed",
    "not_applicable",
]
CoordinatePolicy = Literal[
    "fixed",
    "record_declared",
    "parent_declared",
    "component_declared",
    "unknown",
    "not_applicable",
]
ConversionPolicy = Literal[
    "direct",
    "adapter",
    "requires_context",
    "not_applicable",
]

REPRESENTATION_CONTRACT_SCHEMA_VERSION = 1

REPRESENTATION_UNIT_VOCABULARY = frozenset(
    {
        "activation_value",
        "arbitrary_length_unit",
        "arbitrary_world_unit",
        "array_declared",
        "boolean",
        "component_declared",
        "confidence_score",
        "depth_length_unit",
        "descriptor_value",
        "dimensionless",
        "frame_index",
        "frame_length_unit",
        "feature_score",
        "grid_declared",
        "hertz",
        "index",
        "instance_id",
        "information_weight",
        "keypoint_attribute",
        "match_score",
        "meter",
        "meter_per_second",
        "meter_per_second_squared",
        "meter_per_second_squared_per_sqrt_hertz",
        "meter_per_second_cubed_per_sqrt_hertz",
        "microsecond",
        "nanosecond",
        "not_applicable",
        "parent_length_unit",
        "pixel",
        "pose_length_unit",
        "profile_declared",
        "projective_coefficient",
        "radian_per_second",
        "radian_per_second_per_sqrt_hertz",
        "radian_per_second_squared_per_sqrt_hertz",
        "record_length_unit",
        "scale_ratio",
        "second",
        "semantic_id",
        "source_length_unit",
        "stage_unit",
        "stored_depth",
        "stored_sample",
        "target_length_unit",
        "tangent_covariance",
        "texture_sample",
        "time_code",
        "unit_interval",
    }
)

_NORMALIZATION_POLICIES = frozenset(
    {"canonical", "preserve", "declared", "mixed", "aggregate", "not_applicable"}
)
_SCALE_POLICIES = frozenset(
    {
        "identity",
        "pixel",
        "metric",
        "arbitrary",
        "record_declared",
        "component_declared",
        "mixed",
        "not_applicable",
    }
)
_COORDINATE_POLICIES = frozenset(
    {
        "fixed",
        "record_declared",
        "parent_declared",
        "component_declared",
        "unknown",
        "not_applicable",
    }
)
_CONVERSION_POLICIES = frozenset(
    {"direct", "adapter", "requires_context", "not_applicable"}
)


@dataclass(frozen=True, slots=True)
class NormalizationProfile:
    """Reusable numeric interpretation shared by one or more records."""

    id: str
    normalization: NormalizationPolicy
    scale: ScalePolicy
    coordinates: CoordinatePolicy
    conversion: ConversionPolicy
    canonical_units: tuple[str, ...]
    scale_fields: tuple[str, ...]
    rules: tuple[str, ...]
    refusal: str

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise ValueError("NormalizationProfile.id must be non-empty")
        if self.normalization not in _NORMALIZATION_POLICIES:
            raise ValueError(f"invalid normalization policy {self.normalization!r}")
        if self.scale not in _SCALE_POLICIES:
            raise ValueError(f"invalid scale policy {self.scale!r}")
        if self.coordinates not in _COORDINATE_POLICIES:
            raise ValueError(f"invalid coordinate policy {self.coordinates!r}")
        if self.conversion not in _CONVERSION_POLICIES:
            raise ValueError(f"invalid conversion policy {self.conversion!r}")
        if not self.canonical_units or any(not value for value in self.canonical_units):
            raise ValueError("canonical_units must contain non-empty unit names")
        if not set(self.canonical_units) <= REPRESENTATION_UNIT_VOCABULARY:
            unknown = sorted(set(self.canonical_units) - REPRESENTATION_UNIT_VOCABULARY)
            raise ValueError(f"unknown canonical unit names: {unknown!r}")
        if len(self.canonical_units) != len(set(self.canonical_units)):
            raise ValueError("canonical_units must be unique")
        if len(self.scale_fields) != len(set(self.scale_fields)):
            raise ValueError("scale_fields must be unique")
        if not self.rules or any(not value for value in self.rules):
            raise ValueError("rules must contain non-empty statements")
        if not self.refusal:
            raise ValueError("refusal must be non-empty")


@dataclass(frozen=True, slots=True)
class RepresentationNormalizationContract:
    """Normalization/scaling contract for one public record type."""

    representation: str
    profile: NormalizationProfile
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.representation.startswith("sceneio."):
            raise ValueError("representation must be a public sceneio import path")
        if not self.evidence or any(not value for value in self.evidence):
            raise ValueError("evidence must contain repository-relative test paths")

    @property
    def normalization(self) -> NormalizationPolicy:
        return self.profile.normalization

    @property
    def scale(self) -> ScalePolicy:
        return self.profile.scale

    @property
    def coordinates(self) -> CoordinatePolicy:
        return self.profile.coordinates

    @property
    def conversion(self) -> ConversionPolicy:
        return self.profile.conversion

    @property
    def canonical_units(self) -> tuple[str, ...]:
        return self.profile.canonical_units

    @property
    def scale_fields(self) -> tuple[str, ...]:
        return self.profile.scale_fields

    @property
    def rules(self) -> tuple[str, ...]:
        return self.profile.rules

    @property
    def refusal(self) -> str:
        return self.profile.refusal


def _profile(
    profile_id: str,
    normalization: NormalizationPolicy,
    scale: ScalePolicy,
    coordinates: CoordinatePolicy,
    conversion: ConversionPolicy,
    units: tuple[str, ...],
    *,
    scale_fields: tuple[str, ...] = (),
    rules: tuple[str, ...],
    refusal: str,
) -> NormalizationProfile:
    return NormalizationProfile(
        profile_id,
        normalization,
        scale,
        coordinates,
        conversion,
        units,
        scale_fields,
        rules,
        refusal,
    )


_PROFILES = {
    profile.id: profile
    for profile in (
        _profile(
            "image_samples",
            "preserve",
            "mixed",
            "fixed",
            "not_applicable",
            ("stored_sample", "pixel"),
            scale_fields=("maxval",),
            rules=(
                "Pixels are top-to-bottom interleaved gray, RGB, or RGBA in their stored dtype.",
                "color_space, alpha_mode, and maxval describe samples; values are never rescaled or color-converted implicitly.",
            ),
            refusal="Color, alpha, or sample-range changes require an explicit caller conversion.",
        ),
        _profile(
            "image_sequence",
            "aggregate",
            "mixed",
            "fixed",
            "not_applicable",
            ("stored_sample", "pixel", "nanosecond"),
            scale_fields=("maxval", "timestamps_ns", "durations_ns"),
            rules=(
                "Packed decoded frames follow image_samples; planar YUV frames preserve declared chroma sampling/siting, range, and matrix metadata.",
                "Encoded paths retain their codec-owned sample contract until a frame is explicitly decoded.",
                "Timing uses exact signed int64 nanoseconds when present and is never rate-resampled.",
                "Optional exposure/readout durations remain exact int64 nanoseconds; timestamp_reference and readout direction declare their interpretation without resampling.",
            ),
            refusal="Frame color/range conversion or timing resampling must be requested outside the record.",
        ),
        _profile(
            "binary_mask",
            "canonical",
            "identity",
            "fixed",
            "not_applicable",
            ("boolean", "pixel"),
            rules=("The canonical payload is HxW bool and True means the pixel participates.",),
            refusal="Non-boolean label or probability rasters require a different representation.",
        ),
        _profile(
            "label_taxonomy",
            "canonical",
            "identity",
            "not_applicable",
            "requires_context",
            ("semantic_id", "stored_sample", "boolean"),
            scale_fields=("identity", "version", "semantic_ids"),
            rules=(
                "Unique int32 semantic ids are authoritative; ordered names, optional RGB display colors, and thing/stuff flags are metadata rows in the same order.",
                "Taxonomy identity and version are explicit UTF-8 strings and are never inferred from class names or numeric range.",
            ),
            refusal="Merging, renumbering, or translating taxonomies requires an explicit caller-supplied id mapping.",
        ),
        _profile(
            "semantic_labels",
            "canonical",
            "identity",
            "fixed",
            "requires_context",
            ("semantic_id", "boolean", "pixel"),
            scale_fields=("void_id", "taxonomy.identity", "taxonomy.version"),
            rules=(
                "Class ids are C-contiguous int32 HxW values in top-to-bottom image raster order; optional bool validity is independent of the explicit void id.",
                "When present, the taxonomy declares every valid non-void id without renumbering values.",
            ),
            refusal="Class ids are never normalized by range or remapped without an explicit taxonomy conversion.",
        ),
        _profile(
            "instance_labels",
            "canonical",
            "identity",
            "fixed",
            "requires_context",
            ("instance_id", "semantic_id", "boolean", "pixel"),
            scale_fields=("background_id", "instance_to_semantic_table"),
            rules=(
                "Instance ids are C-contiguous int64 HxW values with an explicit background id and optional bool validity.",
                "An optional unique int64-to-int32 table declares instance-to-semantic association without narrowing large instance ids.",
            ),
            refusal="Background meaning, instance identity, and class association are never inferred from zero, contiguity, or numeric range.",
        ),
        _profile(
            "panoptic_labels",
            "aggregate",
            "identity",
            "fixed",
            "requires_context",
            ("semantic_id", "instance_id", "boolean", "pixel"),
            scale_fields=("semantic.void_id", "instance.background_id", "packed_divisor"),
            rules=(
                "The semantic int32 and instance int64 child maps retain identical shape and validity without copying child arrays.",
                "No packed divisor is implicit; explicit checked conversion names its divisor and output dtype.",
            ),
            refusal="Packed ids, void/background rules, or taxonomy mappings are never guessed from pixel values.",
        ),
        _profile(
            "confidence_unit_interval",
            "canonical",
            "identity",
            "fixed",
            "not_applicable",
            ("unit_interval", "pixel"),
            rules=("Values are finite float32 in the closed interval [0, 1].",),
            refusal="Unbounded scores must not be relabeled as confidence without explicit calibration.",
        ),
        _profile(
            "depth_declared",
            "preserve",
            "record_declared",
            "record_declared",
            "requires_context",
            ("stored_depth", "meter", "pixel", "confidence_score"),
            scale_fields=("unit", "scale_to_meters", "depth_convention", "invalid_policy"),
            rules=(
                "Depth is HxW float32 in raw stored values; stored_depth * scale_to_meters yields meters only when scale_to_meters is positive.",
                "Depth interpretation and invalid samples are metadata and are not rewritten by construction.",
                "Optional confidence is raw float32 and deliberately unbounded; it is not the neutral [0,1] ConfidenceMap contract.",
            ),
            refusal="Unknown/unitless scale or unspecified depth interpretation needs external context before metric conversion.",
        ),
        _profile(
            "depth_parent_scale",
            "canonical",
            "component_declared",
            "parent_declared",
            "requires_context",
            ("parent_length_unit", "pixel"),
            scale_fields=("FrameMeta.scale",),
            rules=(
                "Valid depth is positive finite HxW float32; invalid values are selected by the bool validity mask.",
                "Length units come from the owning PosedViewSet FrameMeta and are not stored on the map.",
            ),
            refusal="A detached map cannot be converted to meters unless its owning frame supplies metric scale.",
        ),
        _profile(
            "normal_vectors",
            "preserve",
            "identity",
            "fixed",
            "requires_context",
            ("dimensionless", "pixel"),
            rules=("Normals are HxWx3 float32 in the declared camera frame and are not silently renormalized.",),
            refusal="Frame changes require an explicit rotation; non-unit inputs remain visible to the caller.",
        ),
        _profile(
            "optical_flow",
            "preserve",
            "pixel",
            "fixed",
            "requires_context",
            ("pixel",),
            scale_fields=("component_order", "u_axis", "v_axis", "row_order", "unit"),
            rules=("Vectors are HxWx2 float32 raw displacements interpreted by their recorded component and axis tags.",),
            refusal="Axis, component, row-order, or unit changes require an explicit flow transform.",
        ),
        _profile(
            "index_graph",
            "canonical",
            "identity",
            "not_applicable",
            "not_applicable",
            ("index",),
            rules=("CSR offsets and indices are canonical structural identities with no independent physical scale.",),
            refusal="Endpoint coordinates, when needed, are interpreted by their owning image or point representation.",
        ),
        _profile(
            "point_cloud",
            "mixed",
            "mixed",
            "record_declared",
            "direct",
            ("record_length_unit", "meter", "stored_sample", "dimensionless", "unit_interval", "index"),
            scale_fields=("scale_to_meters", "coordinate_frame", "intensity_range", "display_color_space"),
            rules=(
                "Positions are float32 plus a float64 origin; for a qualified scale, (position + origin) * scale_to_meters yields meters.",
                "Normals, intensities, colors, widths, and display fields retain their recorded semantics; motion fields have no independent time-base field.",
                "Optional track CSR columns preserve exact image identities and nonnegative keypoint indices for every point observation.",
                "Explicit coordinate conversion transforms positions/origin/motion, scales widths under a similarity, and unit-normalizes nonzero normals.",
            ),
            refusal="An unknown frame/default scale is not metric, motion timing needs source context, and formats without observation tracks refuse tracked clouds rather than discarding them.",
        ),
        _profile(
            "point_scan",
            "mixed",
            "record_declared",
            "record_declared",
            "requires_context",
            ("stored_sample", "index", "record_length_unit", "meter", "second", "dimensionless"),
            scale_fields=(
                "coordinate_frame",
                "scale_to_meters",
                "intensity_range",
                "row_minimum",
                "row_maximum",
                "column_minimum",
                "column_maximum",
                "pose_convention",
                "quaternion_order",
            ),
            rules=(
                "Stored rows, raw uint8 invalid states, and optional int64 row/column indices retain their source values and declared bounds.",
                "The scan-level wxyz pose is authoritative; valid_point_cloud returns an owned valid-row PointCloud with that viewpoint and preserves representable child fields.",
                "Positions, origin, and scalar fields follow the child PointCloud coordinate and scale metadata; timestamps remain optional source seconds.",
            ),
            refusal="Sparse row/column bounds, invalid-state semantics, and scan pose are not inferred across scans; conversion requires explicit preservation of stored-row metadata.",
        ),
        _profile(
            "scan_set",
            "aggregate",
            "mixed",
            "component_declared",
            "requires_context",
            ("stored_sample", "index", "record_length_unit", "meter", "second", "dimensionless"),
            scale_fields=("scans",),
            rules=(
                "Children retain insertion order and stable scan identifiers; duplicate identifiers are refused.",
                "An aggregate convention is available only when all children agree; mixed or empty sets remain unknown.",
            ),
            refusal="Scan selection, frame reconciliation, and cross-scan normalization require an explicit typed adapter.",
        ),
        _profile(
            "pointmap_parent_scale",
            "canonical",
            "component_declared",
            "parent_declared",
            "requires_context",
            ("parent_length_unit", "pixel"),
            scale_fields=("frame", "FrameMeta.scale"),
            rules=("Points are HxWx3 float32 in the declared world or camera frame; NaN may mark invalid pixels.",),
            refusal="Metric conversion requires the owning frame scale and, for camera-frame points, the owning pose.",
        ),
        _profile(
            "gaussian_cloud",
            "declared",
            "mixed",
            "record_declared",
            "direct",
            ("record_length_unit", "dimensionless", "activation_value"),
            scale_fields=(
                "scale_space",
                "opacity_space",
                "quaternion_order",
                "quaternion_norm",
                "sh_layout",
                "sh_basis",
                "sh_phase",
                "sh_coefficient_order",
                "color_space",
                "source_precision",
                "coordinate_frame",
                "scale_to_meters",
                "scale_to_meters_source",
            ),
            rules=(
                "Means and scales retain record units; coordinate_frame plus a qualified scale_to_meters maps those lengths to a declared frame and meters.",
                "Activation spaces, quaternion order/unit state, SH basis/phase/coefficient and memory order, color space, precision, and scale provenance are explicit metadata.",
                "convert_gaussian_conventions changes only qualified activation/layout/order values; convert_coordinates applies orientation-preserving similarities and refuses directional-SH rotations.",
            ),
            refusal="Unknown frames require caller context; reflections, nonsimilar transforms, nonlinear color/SH changes, and directional-SH rotations require an explicit policy.",
        ),
        _profile(
            "mesh",
            "mixed",
            "mixed",
            "record_declared",
            "direct",
            ("record_length_unit", "meter", "unit_interval", "index"),
            scale_fields=("scale_to_meters", "coordinate_frame", "local_transform", "orientation"),
            rules=(
                "Positions and transform translations use record units; a qualified scale_to_meters maps those lengths to meters.",
                "Topology and attribute domains are canonical; colors, UVs, normals, and display primvars retain their declared domains.",
                "Explicit coordinate conversion transforms positions/local transforms and unit-normalizes nonzero normals while preserving topology.",
            ),
            refusal="An unknown frame with the default numeric scale is not a metric claim; reflections, winding changes, and unsupported fields need explicit policy.",
        ),
        _profile(
            "scene_graph",
            "aggregate",
            "record_declared",
            "record_declared",
            "requires_context",
            ("stage_unit", "meter", "time_code", "index"),
            scale_fields=("meters_per_unit", "up_axis", "time_codes_per_second"),
            rules=(
                "Stage geometry and transform translations use stage units; value * meters_per_unit yields meters.",
                "Child payloads retain their own activation, sample, and attribute contracts.",
                "Logical mesh groups preserve heterogeneous glTF primitives, while named scene root sets preserve multi-scene documents.",
            ),
            refusal="A child with unknown spatial semantics is not relabeled from stage metadata without an explicit adapter rule.",
        ),
        _profile(
            "volume_reference",
            "aggregate",
            "component_declared",
            "parent_declared",
            "requires_context",
            ("grid_declared", "stage_unit"),
            rules=("The record identifies an external grid/field; voxel values and transforms are defined by the referenced volume and owning scene.",),
            refusal="No scalar, voxel, or spatial normalization is inferred from URI text alone.",
        ),
        _profile(
            "instances",
            "mixed",
            "component_declared",
            "parent_declared",
            "requires_context",
            ("stage_unit", "dimensionless", "index"),
            rules=("Instance transforms inherit the owning scene unit; orientations and scales retain authored values.",),
            refusal="Detached instances need a prototype and parent-stage convention before spatial conversion.",
        ),
        _profile(
            "materials",
            "preserve",
            "identity",
            "not_applicable",
            "not_applicable",
            ("unit_interval", "dimensionless", "texture_sample"),
            rules=("Base/emissive factors use canonical linear values; scalar factors, texture bindings, UV sets, and sampler state are preserved without baking textures.",),
            refusal="Texture decoding, color conversion, and shader-network approximation are separate explicit operations.",
        ),
        _profile(
            "camera_intrinsics",
            "canonical",
            "pixel",
            "fixed",
            "requires_context",
            ("pixel", "dimensionless"),
            scale_fields=("model", "params", "pixel_center"),
            rules=("Focal lengths and principal points use pixels in the model-defined COLMAP parameter order; distortion terms retain model units.",),
            refusal="Changing image size, pixel-center convention, or camera model requires an explicit calibration transform.",
        ),
        _profile(
            "camera_rig",
            "declared",
            "record_declared",
            "record_declared",
            "requires_context",
            ("pixel", "record_length_unit", "meter", "second"),
            scale_fields=("scale_to_meters", "axis_frame", "transform_convention", "quaternion_order"),
            rules=(
                "Intrinsics remain in pixels and rig translations use record units; translation * scale_to_meters yields meters.",
                "Kalibr time offsets are seconds with reference_time = camera_time + time_offset_seconds.",
            ),
            refusal="Axis, transform direction, quaternion order, or scale changes require an explicit rig adapter.",
        ),
        _profile(
            "imu_calibration",
            "canonical",
            "metric",
            "record_declared",
            "requires_context",
            (
                "meter",
                "nanosecond",
                "hertz",
                "radian_per_second_per_sqrt_hertz",
                "radian_per_second_squared_per_sqrt_hertz",
                "meter_per_second_squared_per_sqrt_hertz",
                "meter_per_second_cubed_per_sqrt_hertz",
            ),
            scale_fields=(
                "sensor_axis_frame",
                "reference_frame",
                "quaternion_order",
                "time_offset_ns",
            ),
            rules=(
                "The stored unit quaternion and meter translation map sensor coordinates into the named reference frame.",
                "Noise densities and random walks use the fixed SI-derived units exposed by the record; absent values remain distinct from zero.",
                "Clock offsets use reference_time_ns = sensor_time_ns + time_offset_ns.",
            ),
            refusal="Axis, reference-frame, transform-direction, or clock-domain changes require an explicit calibrated adapter.",
        ),
        _profile(
            "imu_sequence",
            "declared",
            "record_declared",
            "record_declared",
            "requires_context",
            (
                "nanosecond",
                "radian_per_second",
                "meter_per_second_squared",
            ),
            scale_fields=(
                "angular_velocity_unit",
                "linear_acceleration_unit",
                "sensor_axis_frame",
                "clock_domain",
            ),
            rules=(
                "Timestamps are exact int64 nanoseconds in the declared clock domain and identify measurement instants.",
                "Angular velocity and linear acceleration retain their declared closed units and sensor-axis frame without conversion.",
            ),
            refusal="Unit, axis-frame, gravity, clock synchronization, interpolation, and resampling changes require explicit caller context.",
        ),
        _profile(
            "visual_inertial_dataset",
            "aggregate",
            "component_declared",
            "component_declared",
            "requires_context",
            (
                "nanosecond",
                "meter",
                "pixel",
                "radian_per_second",
                "meter_per_second_squared",
            ),
            scale_fields=(
                "rig",
                "imu_calibrations",
                "camera_clock_domains",
                "camera_timestamp_epochs",
                "imu_timestamp_epochs",
            ),
            rules=(
                "Camera, IMU, image-sequence, and state-trajectory children retain their own normalization and coordinate contracts.",
                "Each stream preserves exact int64 nanosecond timestamps plus an explicit clock domain and epoch; the aggregate never aligns or interpolates clocks.",
            ),
            refusal="Cross-sensor synchronization, pose-frame conversion, resampling, and unit conversion require an explicit calibrated adapter.",
        ),
        _profile(
            "posed_views",
            "canonical",
            "component_declared",
            "parent_declared",
            "requires_context",
            ("frame_length_unit", "meter", "second", "pixel"),
            scale_fields=("FrameMeta.scale", "FrameMeta.scale_provenance", "SE3.convention"),
            rules=(
                "Every pose is a proper float64 OpenCV camera-to-world SE3; source axis, quaternion-order, and pose-direction encodings are normalized at codec boundaries.",
                "Names, timestamps, image references, and calibrations are index-aligned optional metadata; the shared FrameMeta declares world frame and scale class.",
            ),
            refusal="Only scale='metric' establishes meters; normalized or arbitrary scale must not be treated as metric.",
        ),
        _profile(
            "view_input",
            "aggregate",
            "component_declared",
            "component_declared",
            "requires_context",
            ("stored_sample", "pixel", "pose_length_unit", "depth_length_unit"),
            scale_fields=("calibration", "pose_prior", "depth_prior", "mask"),
            rules=(
                "Image, calibration, pose prior, depth prior, and mask retain their own contracts and must agree on image dimensions.",
            ),
            refusal="A ViewInput does not promote an arbitrary pose/depth scale to metric or normalize image samples.",
        ),
        _profile(
            "reconstruction_colmap",
            "canonical",
            "arbitrary",
            "fixed",
            "adapter",
            ("arbitrary_world_unit", "pixel", "index"),
            rules=("Cameras, WXYZ world-to-camera poses, observations, points, and tracks use the canonical COLMAP representation.",),
            refusal="COLMAP world scale is arbitrary; a metric claim requires an independent scale anchor.",
        ),
        _profile(
            "state_trajectory",
            "declared",
            "record_declared",
            "record_declared",
            "requires_context",
            ("nanosecond", "meter", "meter_per_second", "radian_per_second", "meter_per_second_squared"),
            scale_fields=(
                "position_unit",
                "velocity_unit",
                "gyro_bias_unit",
                "accel_bias_unit",
                "quaternion_order",
                "quaternion_sign",
            ),
            rules=("Timestamps are exact int64 nanoseconds; every vector channel carries a closed unit/frame vocabulary.",),
            refusal="Unit, frame, sign, or pose-direction conversion is never inferred during I/O.",
        ),
        _profile(
            "pose_graph",
            "declared",
            "record_declared",
            "record_declared",
            "requires_context",
            ("record_length_unit", "dimensionless", "information_weight", "index"),
            scale_fields=("translation_unit", "quaternion_order", "quaternion_sign", "information_variable_order"),
            rules=("Node/edge SE3 values and full symmetric information matrices preserve their declared order and units.",),
            refusal="Information matrices cannot be rescaled safely without an explicit tangent-space unit transform.",
        ),
        _profile(
            "se3",
            "canonical",
            "arbitrary",
            "record_declared",
            "requires_context",
            ("arbitrary_length_unit", "dimensionless"),
            scale_fields=("convention",),
            rules=("Rotation is a proper float64 matrix and translation is float64 in the owning frame's length unit.",),
            refusal="SE3 has no metric scale field; metric conversion requires owning-frame context.",
        ),
        _profile(
            "sim3",
            "canonical",
            "record_declared",
            "record_declared",
            "requires_context",
            ("scale_ratio", "source_length_unit", "dimensionless"),
            scale_fields=("scale", "convention"),
            rules=("scale is a finite positive source-to-target ratio; rotation is proper and translation uses target/owning-frame units.",),
            refusal="A similarity ratio alone does not establish meters or a world-frame identity.",
        ),
        _profile(
            "frame_meta",
            "declared",
            "record_declared",
            "record_declared",
            "requires_context",
            ("frame_length_unit",),
            scale_fields=("scale", "scale_provenance", "world_frame"),
            rules=("The scale class is exactly arbitrary, normalized, or metric and provenance remains distinct from the claim.",),
            refusal="normalized is not metric; only a metric declaration establishes one meter per unit in this contract.",
        ),
        _profile(
            "pose_prior",
            "aggregate",
            "component_declared",
            "parent_declared",
            "requires_context",
            ("pose_length_unit", "information_weight", "tangent_covariance"),
            scale_fields=("is_metric", "SE3.convention"),
            rules=(
                "The SE3 carries pose direction; is_metric explicitly states whether translation is in meters.",
                "The optional 6x6 covariance is ordered rotation then translation and inherits the pose's angular/length units.",
            ),
            refusal="An unanchored prior must not promote an owning reconstruction to metric scale.",
        ),
        _profile(
            "calibration_union",
            "aggregate",
            "component_declared",
            "component_declared",
            "requires_context",
            ("pixel", "dimensionless"),
            rules=("Exactly one child contract applies: parametric camera_intrinsics or unit_ray_map.",),
            refusal="The two calibration forms cannot be combined or silently approximated.",
        ),
        _profile(
            "unit_ray_map",
            "canonical",
            "identity",
            "fixed",
            "requires_context",
            ("dimensionless", "pixel"),
            rules=("Directions are finite float32/float64 OpenCV-camera vectors with norm one within the declared tolerance.",),
            refusal="The record validates but does not silently normalize non-unit input rays.",
        ),
        _profile(
            "features",
            "mixed",
            "pixel",
            "record_declared",
            "requires_context",
            ("pixel", "keypoint_attribute", "descriptor_value", "feature_score", "index"),
            scale_fields=("pixel_center", "descriptor_dtype", "descriptor_dim"),
            rules=(
                "Keypoint x,y values use float32 pixels with an explicit first-pixel center; any additional detector columns remain schema-defined attributes.",
                "Descriptor values/dtype and unbounded feature scores are preserved rather than normalized.",
            ),
            refusal="Pixel-center shifts, descriptor normalization, and score calibration require explicit adapters.",
        ),
        _profile(
            "matches",
            "mixed",
            "mixed",
            "component_declared",
            "requires_context",
            ("index", "pixel", "match_score", "projective_coefficient", "source_length_unit", "dimensionless"),
            rules=(
                "Indexed matches preserve endpoint identities; coordinate matches inherit image pixel conventions; geometry matrices retain authored scale.",
                "Optional relative-pose translations inherit endpoint/reconstruction length units and do not establish meters.",
            ),
            refusal="Projective matrices have no unique scalar normalization and are never renormalized implicitly.",
        ),
        _profile(
            "track_observation",
            "canonical",
            "identity",
            "parent_declared",
            "not_applicable",
            ("index",),
            rules=("Each observation is the exact image identity plus non-negative keypoint index.",),
            refusal="Spatial and pixel meaning comes from the owning point and feature records.",
        ),
        _profile(
            "tensor_container",
            "preserve",
            "component_declared",
            "component_declared",
            "requires_context",
            ("array_declared",),
            scale_fields=("dtype", "shape", "attrs"),
            rules=("Each named array preserves its canonical supported dtype, shape, byte order, and explicit attributes.",),
            refusal="Tensor names do not imply units, axes, normalization, or coordinate frames.",
        ),
        _profile(
            "ncore_schema",
            "declared",
            "component_declared",
            "component_declared",
            "requires_context",
            ("profile_declared", "microsecond"),
            scale_fields=("dtype", "shape", "attributes", "reference_frame_id"),
            rules=("NCore schema metadata declares array and frame semantics; values are not projected or rescaled by catalog records.",),
            refusal="Only a recognized semantic profile may project to a narrower SceneIO record.",
        ),
        _profile(
            "ncore_payload",
            "aggregate",
            "component_declared",
            "component_declared",
            "requires_context",
            ("profile_declared", "microsecond"),
            scale_fields=("profile", "attributes", "reference_frame_id"),
            rules=("Owned arrays preserve exact dtype/value and each semantic item retains timestamps, frame id, and profile metadata.",),
            refusal="Unknown/custom components remain lossless generic items and are not assigned standard units.",
        ),
        _profile(
            "hloc_features",
            "mixed",
            "pixel",
            "fixed",
            "requires_context",
            ("pixel", "descriptor_value", "feature_score"),
            scale_fields=("pixel_center",),
            rules=("Native HLoc keypoints use first pixel center (0,0); descriptors and uncertainty values are preserved.",),
            refusal="Import to COLMAP requires the explicit HLoc +0.5 pixel-center adapter.",
        ),
        _profile(
            "hloc_matches",
            "aggregate",
            "identity",
            "component_declared",
            "not_applicable",
            ("index", "match_score"),
            rules=("Pair names, match indices, optional scores, and source keypoint counts are preserved exactly.",),
            refusal="Index-only matches have no independent pixel or spatial coordinate convention.",
        ),
        _profile(
            "rtmv_dataset",
            "aggregate",
            "metric",
            "fixed",
            "adapter",
            ("meter", "pixel", "stored_sample"),
            rules=("RTMV cameras/poses use the dataset's fixed convention; RGB, depth, and segmentation retain their typed child contracts.",),
            refusal="The read-only dataset adapter does not invent missing per-frame metadata or a writer profile.",
        ),
        _profile(
            "colmap_database",
            "aggregate",
            "mixed",
            "fixed",
            "adapter",
            ("pixel", "arbitrary_world_unit", "index", "second"),
            scale_fields=("profile", "application_id", "user_version"),
            rules=("The exact database profile controls schema identity while child cameras, features, matches, rigs, and priors keep their own contracts.",),
            refusal="Writing a different database profile requires an explicit compatibility report and selected target profile.",
        ),
        _profile(
            "colmap_rig_frame_companion",
            "canonical",
            "component_declared",
            "parent_declared",
            "requires_context",
            ("parent_length_unit", "dimensionless", "index"),
            scale_fields=("rig_sensor_qvecs", "rig_sensor_tvecs"),
            rules=("Rig sensor poses are WXYZ sensor_from_rig transforms; translations inherit the owning reconstruction length unit.",),
            refusal="Rig/frame rows contain no world pose or independent meter anchor.",
        ),
        _profile(
            "colmap_pose_prior_companion",
            "declared",
            "component_declared",
            "record_declared",
            "requires_context",
            ("source_length_unit", "dimensionless", "index", "tangent_covariance"),
            scale_fields=("coordinate_systems", "positions", "rotations", "pose_covariances"),
            rules=("Prior positions/covariances retain the declared coordinate-system id; rotations are XYZW cam_from_world and presence is explicit.",),
            refusal="An unknown coordinate-system id or absent position cannot establish metric scale.",
        ),
        _profile(
            "colmap_marker_companion",
            "preserve",
            "component_declared",
            "parent_declared",
            "requires_context",
            ("parent_length_unit", "pixel", "index", "tangent_covariance"),
            scale_fields=("world_positions", "world_covariances", "projection_xy", "projection_sizes"),
            rules=("Marker world values inherit reconstruction units while projections use top-left image pixels; presence and links remain exact.",),
            refusal="Markers do not independently establish world scale or a camera pose.",
        ),
        _profile(
            "video_metadata",
            "preserve",
            "mixed",
            "not_applicable",
            "not_applicable",
            ("pixel", "second", "frame_index"),
            scale_fields=("fps", "duration_seconds", "pts_seconds", "time_id"),
            rules=("Dimensions, rates, durations, PTS values, frame ids, and SQL presence are preserved as metadata only.",),
            refusal="Metadata does not decode, resample, or reinterpret encoded video payloads.",
        ),
        _profile(
            "structural_metadata",
            "preserve",
            "not_applicable",
            "not_applicable",
            "not_applicable",
            ("not_applicable",),
            rules=("The representation carries identities, paths, schema metadata, or grouping only and has no independent numeric scale.",),
            refusal="Numeric meaning belongs to referenced or child representations.",
        ),
        _profile(
            "colmap_adapter_calibration",
            "mixed",
            "mixed",
            "record_declared",
            "requires_context",
            ("pixel", "source_length_unit", "dimensionless"),
            scale_fields=("camera_model", "camera_params", "square_length", "marker_length"),
            rules=("Camera parameters retain COLMAP ordering; board lengths remain in their authored common source unit.",),
            refusal="Board lengths have no implicit meter conversion without a declared acquisition unit.",
        ),
        _profile(
            "colmap_adapter_features",
            "mixed",
            "pixel",
            "fixed",
            "requires_context",
            ("pixel", "keypoint_attribute", "descriptor_value", "index", "source_length_unit", "dimensionless"),
            scale_fields=("pixel_center", "descriptor_dtype", "relative_pose"),
            rules=(
                "COLMAP/SIFT keypoints and matches preserve canonical endpoint ids, pixel convention, and descriptor values.",
                "MappingInput relative poses are canonical SE3 second-from-first transforms; their translation inherits reconstruction units.",
            ),
            refusal="Descriptor or keypoint normalization is not inferred from file names or extractor labels.",
        ),
        _profile(
            "colmap_rig_configuration",
            "declared",
            "component_declared",
            "record_declared",
            "requires_context",
            ("pixel", "source_length_unit", "dimensionless"),
            scale_fields=("cam_from_rig", "camera_model_name", "camera_params"),
            rules=("Optional unit WXYZ cam_from_rig transforms and model-ordered intrinsics are preserved without axis or unit conversion.",),
            refusal="The rig JSON carries no universal axis frame or meters-per-unit declaration.",
        ),
        _profile(
            "colmap_adapter_scene",
            "aggregate",
            "arbitrary",
            "component_declared",
            "adapter",
            ("arbitrary_world_unit", "pixel", "index"),
            rules=("The aggregate retains canonical reconstruction children and source-specific companion records.",),
            refusal="Portable COLMAP artifacts do not establish metric world scale by themselves.",
        ),
        _profile(
            "colmap_adapter_sim3",
            "canonical",
            "record_declared",
            "record_declared",
            "requires_context",
            ("scale_ratio", "target_length_unit", "dimensionless"),
            scale_fields=("scale", "quaternion_wxyz"),
            rules=("The positive similarity ratio, unit WXYZ quaternion, and translation are preserved in the adapter's declared direction.",),
            refusal="The scale ratio and translation have no meter meaning without source/target frame context.",
        ),
        _profile(
            "megaloc_artifacts",
            "declared",
            "identity",
            "not_applicable",
            "not_applicable",
            ("descriptor_value", "index"),
            scale_fields=("descriptors_normalized",),
            rules=(
                "The descriptor matrix preserves float values and descriptors_normalized states whether row normalization has already been applied.",
            ),
            refusal="Descriptor normalization is never inferred from model paths, dimensions, or numeric range.",
        ),
        _profile(
            "retrieval_pair",
            "preserve",
            "identity",
            "not_applicable",
            "not_applicable",
            ("index", "match_score"),
            rules=("Pair endpoint identities, score, and retrieval/sequential provenance are preserved exactly.",),
            refusal="The score has no calibrated probability or distance meaning beyond its producing retrieval profile.",
        ),
        _profile(
            "time_metadata",
            "preserve",
            "metric",
            "not_applicable",
            "not_applicable",
            ("second", "index"),
            scale_fields=("timestamp_seconds",),
            rules=("Timestamp seconds and identity tags are preserved without clock conversion.",),
            refusal="Clock domain, epoch, and synchronization are not inferred from a numeric timestamp.",
        ),
        _profile(
            "mvs_projection",
            "preserve",
            "arbitrary",
            "record_declared",
            "requires_context",
            ("projective_coefficient",),
            rules=("The 3x4 projection matrix is preserved coefficient-for-coefficient; projective scalar normalization is not imposed.",),
            refusal="Camera decomposition and metric scale require calibration and frame context.",
        ),
        _profile(
            "mvs_workspace",
            "aggregate",
            "component_declared",
            "component_declared",
            "requires_context",
            ("component_declared",),
            rules=("Workspace paths and indices coordinate child reconstruction, depth, normal, consistency, and visibility contracts.",),
            refusal="Opening or inspecting a workspace does not normalize its child numeric payloads.",
        ),
        _profile(
            "raster_collection",
            "aggregate",
            "component_declared",
            "component_declared",
            "requires_context",
            ("component_declared", "stored_sample", "pixel"),
            rules=(
                "RasterLevel preserves a native-endian C-contiguous sample array with explicit axes, dtype, and payload kind.",
                "RasterSeries requires homogeneous semantics and strictly decreasing spatial pyramid dimensions.",
                "RasterCollection orders independently meaningful series without inferring a shared scale or coordinate frame.",
            ),
            refusal="Cross-series normalization, arbitrary OME axes, and physical scaling require application context outside this bounded aggregate.",
        ),
    )
}


def _build_contracts() -> dict[str, RepresentationNormalizationContract]:
    contracts: dict[str, RepresentationNormalizationContract] = {}

    def register(profile_id: str, evidence: tuple[str, ...], *representations: str) -> None:
        profile = _PROFILES[profile_id]
        for representation in representations:
            if representation in contracts:
                raise RuntimeError(f"duplicate representation contract {representation!r}")
            contracts[representation] = RepresentationNormalizationContract(
                representation,
                profile,
                evidence,
            )

    register("camera_rig", ("tests/records/test_camera_rig.py",), "sceneio.CameraRig")
    register("colmap_database", ("tests/codecs/test_colmap_db.py",), "sceneio.ColmapDatabase")
    register("colmap_marker_companion", ("tests/codecs/test_colmap_db.py",), "sceneio.ColmapMarkerSet")
    register("colmap_pose_prior_companion", ("tests/codecs/test_colmap_db.py",), "sceneio.ColmapPosePriorSet")
    register("colmap_rig_frame_companion", ("tests/codecs/test_colmap_db.py",), "sceneio.ColmapRigFrameSet")
    register("structural_metadata", ("tests/codecs/test_colmap_db.py",), "sceneio.ColmapMaxxSchemaInfo")
    register("video_metadata", ("tests/codecs/test_colmap_db.py",), "sceneio.ColmapVideoMetadataSet")
    register("index_graph", ("tests/records/test_dense_mvs.py",), "sceneio.ConsistencyGraph", "sceneio.PointVisibility")
    register("depth_declared", ("tests/records/test_depth_map.py",), "sceneio.DepthMap")
    register("features", ("tests/codecs/test_colmap_db.py",), "sceneio.FeatureSet")
    register("optical_flow", ("tests/records/test_flow_field.py",), "sceneio.FlowField")
    register("gaussian_cloud", ("tests/records/test_gaussian_semantic_oracles.py",), "sceneio.GaussianCloud")
    register("hloc_features", ("tests/codecs/test_hdf5_hloc.py",), "sceneio.HlocFeatureStore")
    register("hloc_matches", ("tests/codecs/test_hdf5_hloc.py",), "sceneio.HlocMatchStore")
    register("image_samples", ("tests/records/test_image.py",), "sceneio.Image")
    register("image_sequence", ("tests/records/test_image_sequence_record.py",), "sceneio.ImageSequence")
    register("imu_calibration", ("tests/records/test_imu.py",), "sceneio.ImuCalibration")
    register("imu_sequence", ("tests/records/test_imu.py",), "sceneio.ImuSequence")
    register(
        "visual_inertial_dataset",
        ("tests/codecs/test_euroc_dataset.py",),
        "sceneio.VisualInertialDataset",
    )
    register("instances", ("tests/records/test_instance_set.py",), "sceneio.InstanceSet")
    register("materials", ("tests/records/test_material_set.py",), "sceneio.MaterialSet")
    register("mesh", ("tests/records/test_mesh.py",), "sceneio.Mesh")
    register(
        "ncore_schema",
        ("tests/codecs/test_ncore_v4.py",),
        "sceneio.NCoreArray",
        "sceneio.NCoreComponent",
        "sceneio.NCoreDataset",
        "sceneio.NCoreGroup",
        "sceneio.NCoreSelection",
        "sceneio.NCoreStore",
    )
    register(
        "ncore_payload",
        ("tests/codecs/test_ncore_v4.py",),
        "sceneio.NCoreComponentData",
        "sceneio.NCoreDatasetData",
        "sceneio.NCoreItem",
        "sceneio.NCoreSemanticComponent",
    )
    register("normal_vectors", ("tests/records/test_dense_mvs.py",), "sceneio.NormalMap")
    register("point_cloud", ("tests/records/test_point_cloud.py",), "sceneio.PointCloud")
    register("point_scan", ("tests/records/test_point_scan.py",), "sceneio.PointScan")
    register("pose_graph", ("tests/records/test_pose_graph.py",), "sceneio.PoseGraph")
    register("posed_views", ("tests/test_coordinate_math_oracle.py",), "sceneio.PosedViewSet")
    register("reconstruction_colmap", ("tests/codecs/test_colmap.py",), "sceneio.Reconstruction")
    register("rtmv_dataset", ("tests/codecs/test_rtmv.py",), "sceneio.RtmvDataset")
    register(
        "scene_graph",
        (
            "tests/records/test_scene_graph.py",
            "tests/records/test_scene_graph_mesh_groups.py",
        ),
        "sceneio.SceneGraph",
    )
    register("scan_set", ("tests/records/test_point_scan.py",), "sceneio.ScanSet")
    register("state_trajectory", ("tests/records/test_state_trajectory.py",), "sceneio.StateTrajectory")
    register("tensor_container", ("tests/records/test_tensor_dict.py",), "sceneio.TensorDict")
    register("volume_reference", ("tests/records/test_scene_graph.py",), "sceneio.VolumeAsset")

    register("se3", ("tests/test_data_transforms.py",), "sceneio.SE3")
    register("calibration_union", ("tests/test_data_calibration.py",), "sceneio.Calibration")
    register("camera_intrinsics", ("tests/test_data_calibration.py",), "sceneio.CameraIntrinsics")
    register("confidence_unit_interval", ("tests/test_data_dense.py",), "sceneio.ConfidenceMap")
    register("matches", ("tests/test_data_features.py",), "sceneio.CorrespondenceGraph", "sceneio.PairCorrespondences", "sceneio.TwoViewGeometry")
    register("frame_meta", ("tests/test_data_views.py",), "sceneio.FrameMeta")
    register(
        "instance_labels",
        ("tests/test_data_label_maps.py", "tests/codecs/test_label_map_carriers.py"),
        "sceneio.InstanceMap",
    )
    register(
        "label_taxonomy",
        ("tests/test_data_label_maps.py", "tests/codecs/test_label_map_carriers.py"),
        "sceneio.LabelTaxonomy",
    )
    register("binary_mask", ("tests/test_data_dense.py",), "sceneio.Mask")
    register(
        "raster_collection",
        ("tests/records/test_raster_collection.py",),
        "sceneio.RasterCollection",
        "sceneio.RasterLevel",
        "sceneio.RasterSeries",
    )
    register(
        "panoptic_labels",
        ("tests/test_data_label_maps.py", "tests/codecs/test_label_map_carriers.py"),
        "sceneio.PanopticMap",
    )
    register("pointmap_parent_scale", ("tests/test_data_dense.py",), "sceneio.Pointmap")
    register("pose_prior", ("tests/test_data_pointcloud_priors.py",), "sceneio.PosePrior")
    register("unit_ray_map", ("tests/test_data_calibration.py",), "sceneio.RayMap")
    register(
        "semantic_labels",
        ("tests/test_data_label_maps.py", "tests/codecs/test_label_map_carriers.py"),
        "sceneio.SemanticMap",
    )
    register("sim3", ("tests/test_data_transforms.py",), "sceneio.Sim3")
    register("track_observation", ("tests/test_data_pointcloud_priors.py",), "sceneio.TrackObservation")
    register("view_input", ("tests/test_data_views.py",), "sceneio.ViewInput")

    colmap_evidence = ("tests/test_colmap_ecosystem_adapters.py",)
    register("colmap_adapter_calibration", colmap_evidence, "sceneio.colmap.CharucoBoard", "sceneio.colmap.CharucoCalibration")
    register("colmap_adapter_scene", colmap_evidence, "sceneio.colmap.ExtendedSparseModel", "sceneio.colmap.MappingInput", "sceneio.colmap.SparseExtensions")
    register("megaloc_artifacts", colmap_evidence, "sceneio.colmap.MegaLocArtifacts")
    register("structural_metadata", colmap_evidence, "sceneio.colmap.IdTags", "sceneio.colmap.MegaLocImage")
    register("retrieval_pair", colmap_evidence, "sceneio.colmap.MegaLocPair")
    register("colmap_adapter_features", colmap_evidence, "sceneio.colmap.SparseMarkerProjection")
    register("colmap_rig_configuration", colmap_evidence, "sceneio.colmap.RigConfigCamera", "sceneio.colmap.RigConfiguration")
    register("colmap_marker_companion", colmap_evidence, "sceneio.colmap.SparseMarker")
    register("time_metadata", colmap_evidence, "sceneio.colmap.TimeFrame")

    mvs_evidence = ("tests/test_colmap_mvs_workspace.py",)
    register("mvs_workspace", mvs_evidence, "sceneio.colmap_mvs.ColmapMvsWorkspace", "sceneio.colmap_mvs.DenseMapSet", "sceneio.colmap_mvs.LegacyMvsWorkspace", "sceneio.colmap_mvs.WorkspaceInspection", "sceneio.colmap_mvs.WorkspaceValidation")
    register("structural_metadata", mvs_evidence, "sceneio.colmap_mvs.LegacyMvsImageRef", "sceneio.colmap_mvs.PatchMatchProblem")
    register("index_graph", mvs_evidence, "sceneio.colmap_mvs.PmvsVisibilityGraph")
    register("mvs_projection", mvs_evidence, "sceneio.colmap_mvs.ProjectionMatrix")
    return contracts


REPRESENTATION_PROFILES = MappingProxyType(_PROFILES)
REPRESENTATION_CONTRACTS = MappingProxyType(_build_contracts())


def _public_path(value: object) -> str:
    cls = value if isinstance(value, type) else type(value)
    module = cls.__module__
    name = cls.__qualname__
    if (
        module in {"sceneio._core", "sceneio.io"}
        or module.startswith("sceneio.io._")
    ):
        return f"sceneio.{name}"
    if module.startswith("sceneio._data."):
        return f"sceneio.{name}"
    if module.startswith("sceneio.colmap."):
        return f"sceneio.colmap.{name}"
    if module == "sceneio.colmap_mvs":
        return f"sceneio.colmap_mvs.{name}"
    return f"{module}.{name}"


def representation_contract(
    value: object | type | str,
) -> RepresentationNormalizationContract:
    """Return the normalization/scaling contract for a record or public name.

    A bare class name is accepted only when it is unambiguous. Canonical
    qualified names use the sole public representation path, ``sceneio.<Type>``
    (or a retained source-specific aggregate namespace).
    """

    if isinstance(value, str):
        key = value
        contract = REPRESENTATION_CONTRACTS.get(key)
        if contract is not None:
            return contract
        matches = [
            item
            for name, item in REPRESENTATION_CONTRACTS.items()
            if name.rsplit(".", 1)[-1] == key
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            choices = ", ".join(item.representation for item in matches)
            raise ValueError(f"ambiguous representation {value!r}; choose one of {choices}")
        raise KeyError(f"unknown SceneIO representation {value!r}")
    key = _public_path(value)
    try:
        return REPRESENTATION_CONTRACTS[key]
    except KeyError:
        raise TypeError(
            f"no normalization/scaling contract for {key}; "
            "use a public SceneIO representation type"
        ) from None


__all__ = [
    "REPRESENTATION_CONTRACTS",
    "REPRESENTATION_CONTRACT_SCHEMA_VERSION",
    "REPRESENTATION_PROFILES",
    "REPRESENTATION_UNIT_VOCABULARY",
    "NormalizationProfile",
    "RepresentationNormalizationContract",
    "representation_contract",
]
