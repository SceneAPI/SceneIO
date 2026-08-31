"""Closed payload-kind vocabulary for SceneIO-owned built-in codecs.

``Codec.payload_kind`` remains open for runtime extensions. This module
classifies only the repository-owned built-in tokens; it does not expand or
reinterpret the cross-repository logical ``CORE_DATA_TYPES`` vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str | bytes):
        raise TypeError(f"{field_name} must be an iterable of strings")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"{field_name} must be an iterable of strings") from exc
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"{field_name} entries must be non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} entries must be unique")
    return values


@dataclass(frozen=True, slots=True)
class CodecPayloadKind:
    """One repository-owned built-in ``Codec.payload_kind`` token."""

    id: str
    title: str
    description: str
    public_types: tuple[str, ...]
    format_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    logical_data_type_id: str | None = None
    dynamic_output_rule: str | None = None

    def __post_init__(self) -> None:
        _text(self.id, "CodecPayloadKind.id")
        _text(self.title, "CodecPayloadKind.title")
        _text(self.description, "CodecPayloadKind.description")
        public_types = _strings(self.public_types, "CodecPayloadKind.public_types")
        if any(not item.startswith("sceneio.") for item in public_types):
            raise ValueError("CodecPayloadKind.public_types must be public paths")
        object.__setattr__(self, "public_types", public_types)
        format_ids = _strings(self.format_ids, "CodecPayloadKind.format_ids")
        if not format_ids:
            raise ValueError("CodecPayloadKind.format_ids must not be empty")
        object.__setattr__(self, "format_ids", format_ids)
        evidence = _strings(self.evidence, "CodecPayloadKind.evidence")
        if not evidence or any(
            not node_id.startswith("tests/") or "::" not in node_id for node_id in evidence
        ):
            raise ValueError("CodecPayloadKind.evidence must contain exact test node ids")
        object.__setattr__(self, "evidence", evidence)
        if self.logical_data_type_id is not None:
            _text(
                self.logical_data_type_id,
                "CodecPayloadKind.logical_data_type_id",
            )
        if self.dynamic_output_rule is not None:
            _text(
                self.dynamic_output_rule,
                "CodecPayloadKind.dynamic_output_rule",
            )
        if not public_types and self.dynamic_output_rule is None:
            raise ValueError("payload kinds without public types require a dynamic output rule")

    @property
    def dynamic_output(self) -> bool:
        """Whether record identity depends on a typed API or file profile."""

        return self.dynamic_output_rule is not None


def _payload(
    id: str,
    title: str,
    description: str,
    public_types: tuple[str, ...],
    format_ids: tuple[str, ...],
    *,
    logical_data_type_id: str | None = None,
    dynamic_output_rule: str | None = None,
) -> CodecPayloadKind:
    return CodecPayloadKind(
        id=id,
        title=title,
        description=description,
        public_types=public_types,
        format_ids=format_ids,
        evidence=(
            "tests/test_public_type_contracts.py::"
            "test_payload_catalog_exactly_covers_builtin_registry",
        ),
        logical_data_type_id=logical_data_type_id,
        dynamic_output_rule=dynamic_output_rule,
    )


_PAYLOADS = (
    _payload(
        "camera_rig",
        "Camera rig",
        "Calibrated camera collections and their relative transforms.",
        ("sceneio.CameraRig",),
        ("opencv_yaml", "opencv_xml", "ros_camera_info", "kalibr"),
    ),
    _payload(
        "consistency_graph",
        "Consistency graph",
        "COLMAP dense-MVS ordered consistency observations.",
        ("sceneio.ConsistencyGraph",),
        ("colmap_mvs_consistency",),
    ),
    _payload(
        "depth_map",
        "Depth map",
        "Stored or explicitly typed depth rasters.",
        ("sceneio.DepthMap",),
        ("pfm", "dmb", "colmap_mvs_depth"),
        dynamic_output_rule=(
            "Generic PFM may return an image-shaped value; typed depth APIs "
            "return the declared DepthMap contract."
        ),
    ),
    _payload(
        "feature_set",
        "Feature set",
        "Per-image features or a named feature store.",
        ("sceneio.FeatureSet", "sceneio.HlocFeatureStore"),
        ("hloc_features",),
        logical_data_type_id="feature_set",
    ),
    _payload(
        "flow",
        "Optical flow",
        "Convention-tagged two-component pixel displacement fields.",
        ("sceneio.FlowField",),
        ("flo",),
    ),
    _payload(
        "image",
        "Image",
        "One decoded image with explicit stored-sample metadata.",
        ("sceneio.Image",),
        ("netpbm", "png", "jpeg", "bmp", "tga", "hdr", "exr", "webp", "avif"),
    ),
    _payload(
        "image_sequence",
        "Image sequence",
        "Ordered encoded or decoded image/video frames with timing metadata.",
        ("sceneio.ImageSequence",),
        (
            "y4m",
            "webm",
            "theora",
            "animated_webp",
            "apng",
            "animated_avif",
            "image_sequence",
        ),
        logical_data_type_id="image_sequence",
    ),
    _payload(
        "match_graph",
        "Match graph",
        "Feature and match stores indexed by images or image pairs.",
        (
            "sceneio.ColmapDatabase",
            "sceneio.HlocMatchStore",
            "sceneio.CorrespondenceGraph",
        ),
        ("colmap_db", "hloc_matches"),
        logical_data_type_id="match_graph",
    ),
    _payload(
        "mesh",
        "Mesh",
        "Indexed or triangle-soup polygonal surface geometry.",
        ("sceneio.Mesh",),
        ("ply_mesh", "obj", "stl", "off"),
    ),
    _payload(
        "scene_graph",
        "Scene graph",
        "Typed scene hierarchy, logical mesh groups, named scenes, and bounded material associations.",
        ("sceneio.SceneGraph",),
        ("gltf", "glb", "usd", "usdz"),
    ),
    _payload(
        "ncore_dataset",
        "NCore dataset",
        "Owned NCore V4 catalog, components, items, and arrays.",
        ("sceneio.NCoreDataset", "sceneio.NCoreDatasetData"),
        ("ncore_v4",),
    ),
    _payload(
        "normal_map",
        "Normal map",
        "Dense camera-space surface-normal raster.",
        ("sceneio.NormalMap",),
        ("colmap_mvs_normal",),
    ),
    _payload(
        "numeric_table",
        "Numeric table",
        "Named fixed-width numeric columns without inferred semantics.",
        ("sceneio.TensorDict",),
        ("parquet", "arrow_ipc"),
    ),
    _payload(
        "point_cloud",
        "Point cloud",
        "Unstructured or organized point samples and attributes.",
        ("sceneio.PointCloud",),
        ("ply", "pcd", "xyz", "pts", "las", "laz"),
    ),
    _payload(
        "point_visibility",
        "Point visibility",
        "Ordered point-to-image visibility adjacency.",
        ("sceneio.PointVisibility",),
        ("colmap_fused_visibility",),
    ),
    _payload(
        "pose_graph",
        "Pose graph",
        "Pose vertices and relative-pose constraints.",
        ("sceneio.PoseGraph",),
        ("g2o",),
    ),
    _payload(
        "posed_views",
        "Posed views",
        "Ordered camera poses with frame and scale declarations.",
        ("sceneio.PosedViewSet",),
        ("transforms_json", "tum", "kitti"),
    ),
    _payload(
        "raster_collection",
        "Raster collection",
        "Ordered TIFF series and homogeneous pyramid levels with typed payloads.",
        ("sceneio.RasterCollection",),
        ("tiff",),
    ),
    _payload(
        "rtmv_dataset",
        "RTMV dataset",
        "Read-only RTMV camera/image/depth dataset aggregate.",
        ("sceneio.RtmvDataset",),
        ("rtmv",),
    ),
    _payload(
        "scan_set",
        "Scan set",
        "Ordered point scans with stored-row validity, organization, and pose metadata.",
        ("sceneio.ScanSet",),
        ("e57",),
    ),
    _payload(
        "sparse_model",
        "Sparse model",
        "Sparse reconstruction cameras, images, observations, and points.",
        ("sceneio.Reconstruction",),
        ("colmap_sparse", "colmap_sparse_txt", "bundler", "bal", "nvm", "openmvg"),
        logical_data_type_id="sparse_model",
    ),
    _payload(
        "sparse_volume",
        "Sparse volume",
        "One bounded scalar sparse-volume grid.",
        ("sceneio.TensorDict", "sceneio.VolumeAsset"),
        ("openvdb",),
    ),
    _payload(
        "splat",
        "Gaussian splat",
        "Gaussian positions, covariance parameters, opacity, and appearance.",
        ("sceneio.GaussianCloud",),
        ("gaussian_ply", "compressed_ply", "sog", "ksplat", "spz", "splat"),
    ),
    _payload(
        "state_trajectory",
        "State trajectory",
        "Timestamped poses, velocity, and optional inertial biases.",
        ("sceneio.StateTrajectory",),
        ("euroc_state",),
    ),
    _payload(
        "tensor",
        "Tensor",
        "One numeric ndarray preserving dtype and shape.",
        (),
        ("npy",),
        dynamic_output_rule=(
            "The public value is a NumPy ndarray rather than a SceneIO class; "
            "dtype and shape are governed by the NPY codec contract."
        ),
    ),
    _payload(
        "tensor_dict",
        "Tensor dictionary",
        "Named fixed-size numeric arrays without inferred domain semantics.",
        ("sceneio.TensorDict",),
        ("npz", "safetensors", "hdf5", "zarr"),
    ),
    _payload(
        "visual_inertial_dataset",
        "Visual-inertial dataset",
        "Camera, IMU, calibration, and optional state streams on exact clocks.",
        ("sceneio.VisualInertialDataset",),
        ("euroc_dataset",),
    ),
)

BUILTIN_CODEC_PAYLOAD_KINDS = MappingProxyType({payload.id: payload for payload in _PAYLOADS})

if len(BUILTIN_CODEC_PAYLOAD_KINDS) != len(_PAYLOADS):
    raise RuntimeError("built-in codec payload-kind ids must be unique")


def _build_format_index(
    payloads: tuple[CodecPayloadKind, ...],
) -> MappingProxyType[str, str]:
    """Map each built-in format to its sole payload-kind owner."""

    result: dict[str, str] = {}
    for payload in payloads:
        for format_id in payload.format_ids:
            if format_id in result:
                raise ValueError("a built-in format is assigned to multiple payload kinds")
            result[format_id] = payload.id
    return MappingProxyType(result)


_BUILTIN_PAYLOAD_IDS_BY_FORMAT = _build_format_index(_PAYLOADS)


def builtin_payload_kind(payload_id: str) -> CodecPayloadKind:
    """Return one SceneIO-owned built-in payload-kind contract."""

    try:
        return BUILTIN_CODEC_PAYLOAD_KINDS[payload_id]
    except KeyError:
        raise KeyError(f"unknown built-in codec payload kind {payload_id!r}") from None


def is_builtin_payload_kind(payload_id: str) -> bool:
    """Return whether a token belongs to SceneIO's built-in vocabulary."""

    return payload_id in BUILTIN_CODEC_PAYLOAD_KINDS


__all__ = [
    "BUILTIN_CODEC_PAYLOAD_KINDS",
    "CodecPayloadKind",
    "builtin_payload_kind",
    "is_builtin_payload_kind",
]
