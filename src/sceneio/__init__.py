"""sceneio — the contract plane for SceneAPI.

This is a *contract*, not an implementation. It owns both the **data
contracts** and the **procedure contracts** the SceneAPI family agrees
on, organized as import-isolated namespaces:

- Root exports own the numpy-native datatypes (calibration, SE3/Sim3,
  priors, dense maps, features, correspondences, views, and frame metadata).
- :mod:`sceneio.formats` — the disk/wire format-id registry.
- :mod:`sceneio.mapping` — the neutral `Mapper` contract + traits.
- :mod:`sceneio.matching` — `FeatureExtractor` / `PairMatcher` /
  `GeometricVerifier` + traits.
- :mod:`sceneio.testing` — conformance kits for implementations.
- :mod:`sceneio.contracts` — immutable generic public-type and built-in
  payload-kind discovery.

The root also exposes the ``application/x-sfm-points-v1`` wire codec
(``points_binary``), storage and image-source protocols, the extended COLMAP
scene-database schema, ``PCMAPIN`` checkpoint helpers, and the shared error
hierarchy. SceneIO 0.4 has one public path per data representation; private
implementation modules are not alternate API surfaces.

Concrete backends (blob stores, the FastAPI service, engine adapters,
the SceneMap / SceneMatch implementation bundles) live elsewhere; they
depend on this package for the contracts they must agree on. This
package is a leaf: it imports **nothing from the SceneAPI family**
(``sceneapi`` / ``sfm_hub`` / ``app``; guard-tested). numpy is its one
hard dependency — the contracts are numpy-native.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from sceneio.blobstore import BlobStore, validate_sha
from sceneio.colmap_db import (
    COLMAP_DATABASE_PROFILES,
    COLMAP_DATABASE_PROFILES_BY_NAME,
    COLMAP_DB_TABLES,
    COLMAP_DB_TABLES_BY_NAME,
    COLMAP_KNOWN_DESCRIPTOR_DTYPES,
    COLMAP_KNOWN_EXTRACTOR_TYPES,
    COLMAP_KNOWN_MARKER_TYPES,
    COLMAP_KNOWN_MATCH_SOURCE_FLAGS,
    COLMAP_KNOWN_MATCHER_TYPES,
    CONTRACT_NAME,
    CONTRACT_SCHEMA_VERSION,
    DATABASE_SCHEMA_REVISION,
    DATABASE_VERSION_NUMBER,
    EXTENSION_COLUMNS,
    EXTENSION_TABLES,
    MAX_NUM_IMAGES,
    MAXX_DATABASE_APPLICATION_ID,
    UNDEFINED_EXTRACTOR_TYPE,
    UPSTREAM_TABLES,
    ColmapDatabaseConversionReport,
    ColumnDef,
    DatabaseProfile,
    TableDef,
    contract_dict,
    image_pair_to_pair_id,
    is_colmap_native_extractor_type,
    is_extension_column,
    is_extension_table,
    make_database_version_number,
    matches_are_type_compatible,
    pair_id_to_image_pair,
)
from sceneio.errors import ContractViolation, SceneIoError
from sceneio.imagesource import ImageSourceImpl, MaterializedImage
from sceneio.mapping_input import (
    CheckpointRef,
    checkpoint_root,
    gc_checkpoints,
    latest_checkpoint,
    list_checkpoints,
    write_checkpoint,
)
from sceneio.points_binary import (
    HEADER_FMT,
    HEADER_SIZE,
    MAGIC,
    RECORD_FMT,
    RECORD_SIZE,
    Point3DRecord,
    decode_records,
    encode_all,
    read_header,
    read_record,
    write_header,
    write_record,
)

if TYPE_CHECKING:
    from sceneio import (
        colmap,
        colmap_mvs,
        contracts,
        formats,
        io,
        mapping,
        matching,
        testing,
    )

__version__ = "0.4.0"

# The contract namespaces are import-isolated: they are loaded lazily on
# first attribute access so that `import sceneio` alone stays cheap
# and no namespace ever depends on a sibling being imported.
_NAMESPACES = frozenset(
    {
        "colmap",
        "colmap_mvs",
        "contracts",
        "formats",
        "io",
        "mapping",
        "matching",
        "testing",
    }
)

# Names forwarded flat off `sceneio` from `sceneio.io`, kept lazy so the
# compiled codecs load on first use rather than at `import sceneio`.
_IO_FORWARDS = frozenset(
    {
        "capabilities",
        "camera_intrinsics",
        "codecs",
        "colmap_database_conversion_report",
        "COLMAP_COORDINATES",
        "convert_gaussian_conventions",
        "convert_coordinates",
        "coordinate_contract",
        "coordinate_convention",
        "depth_map",
        "detect",
        "feature_set",
        "IMAGE_COORDINATES",
        "inspect",
        "inspect_depth",
        "inspect_e57_scans",
        "inspect_flow",
        "inspect_label_map",
        "inspect_tiff_collection",
        "LABEL_MAP_SCHEMA",
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
        "UNKNOWN_COORDINATES",
        "UNSPECIFIED_FORMAT_COORDINATES",
        "write",
        "write_colmap_db",
        "write_depth",
        "write_e57_scans",
        "write_euroc_dataset",
        "write_flow",
        "write_label_map",
        "write_ncore_v4",
        "write_openvdb",
        "write_scene",
        "write_tiff",
        "write_tiff_collection",
        "write_usd",
        "write_usdz",
        "write_zarr",
    }
)

_DATA_FORWARDS = frozenset(
    {
        "CORRESPONDENCE_MODES",
        "DEFAULT_CONVENTION",
        "POINTMAP_FRAMES",
        "POSE_CONVENTIONS",
        "RASTER_AXES",
        "RASTER_DTYPES",
        "RASTER_PAYLOAD_KINDS",
        "SCALE_CLASSES",
        "SCALE_PROVENANCES",
        "Calibration",
        "CameraModel",
        "ConfidenceMap",
        "CorrespondenceGraph",
        "FrameMeta",
        "ImageRef",
        "InstanceMap",
        "LabelTaxonomy",
        "Mask",
        "PairCorrespondences",
        "PanopticMap",
        "Pointmap",
        "PosePrior",
        "PosedViewSet",
        "RasterCollection",
        "RasterLevel",
        "RasterSeries",
        "RayMap",
        "SE3",
        "SemanticMap",
        "Sim3",
        "TrackObservation",
        "TwoViewGeometry",
        "ViewInput",
    }
)

_REPRESENTATION_FORWARDS = frozenset(
    {
        "REPRESENTATION_CONTRACTS",
        "REPRESENTATION_CONTRACT_SCHEMA_VERSION",
        "REPRESENTATION_PROFILES",
        "REPRESENTATION_UNIT_VOCABULARY",
        "NormalizationProfile",
        "RepresentationNormalizationContract",
        "representation_contract",
    }
)

_CORE_FORWARDS = frozenset(
    {
        "CameraIntrinsics",
        "CameraRig",
        "ColmapDatabase",
        "ColmapMarkerSet",
        "ColmapMaxxSchemaInfo",
        "ColmapPosePriorSet",
        "ColmapRigFrameSet",
        "ColmapVideoMetadataSet",
        "ConsistencyGraph",
        "DepthMap",
        "FeatureSet",
        "FlowField",
        "GaussianCloud",
        "Image",
        "ImageSequence",
        "ImuCalibration",
        "ImuSequence",
        "InstanceSet",
        "MaterialSet",
        "Mesh",
        "NormalMap",
        "PointCloud",
        "PointScan",
        "PointVisibility",
        "PoseGraph",
        "Reconstruction",
        "ScanSet",
        "SceneGraph",
        "StateTrajectory",
        "TensorDict",
        "VolumeAsset",
    }
)

_IO_TYPE_FORWARDS = {
    "ArrayInspection": ("sceneio.io._inspectors.model", "ArrayInspection"),
    "Codec": ("sceneio.io.registry", "Codec"),
    "CodecCapabilities": ("sceneio.io.registry", "CodecCapabilities"),
    "CoordinateConvention": ("sceneio.coordinates", "CoordinateConvention"),
    "DepthEncoding": ("sceneio.io._depth", "DepthEncoding"),
    "FormatCoordinateContract": (
        "sceneio.coordinates",
        "FormatCoordinateContract",
    ),
    "FormatError": ("sceneio.io.registry", "FormatError"),
    "HlocFeatureStore": ("sceneio.io._hdf5", "HlocFeatureStore"),
    "HlocMatchStore": ("sceneio.io._hdf5", "HlocMatchStore"),
    "Inspection": ("sceneio.io._inspectors.model", "Inspection"),
    "NCoreArray": ("sceneio.io._ncore", "NCoreArray"),
    "NCoreComponent": ("sceneio.io._ncore", "NCoreComponent"),
    "NCoreComponentData": ("sceneio.io._ncore", "NCoreComponentData"),
    "NCoreDataset": ("sceneio.io._ncore", "NCoreDataset"),
    "NCoreDatasetData": ("sceneio.io._ncore", "NCoreDatasetData"),
    "NCoreGroup": ("sceneio.io._ncore", "NCoreGroup"),
    "NCoreItem": ("sceneio.io._ncore", "NCoreItem"),
    "NCoreSelection": ("sceneio.io._ncore", "NCoreSelection"),
    "NCoreSemanticComponent": ("sceneio.io._ncore", "NCoreSemanticComponent"),
    "NCoreStore": ("sceneio.io._ncore", "NCoreStore"),
    "NativeFeatureCapabilities": (
        "sceneio.io.registry",
        "NativeFeatureCapabilities",
    ),
    "RtmvDataset": ("sceneio.io._rtmv", "RtmvDataset"),
    "VisualInertialDataset": (
        "sceneio.io._euroc_dataset",
        "VisualInertialDataset",
    ),
}

_CONTRACT_FORWARDS = frozenset(
    {
        "PUBLIC_TYPE_CONTRACTS",
        "public_type_contract",
    }
)


def __getattr__(name: str) -> object:
    if name == "_core":
        module = importlib.import_module("sceneio._core")
        from sceneio.coordinates import install_core_coordinate_properties

        install_core_coordinate_properties(module)
        return module
    if name in _NAMESPACES:
        return importlib.import_module(f"sceneio.{name}")
    if name in _REPRESENTATION_FORWARDS:
        return getattr(importlib.import_module("sceneio.representations"), name)
    if name in _CONTRACT_FORWARDS:
        return getattr(importlib.import_module("sceneio.contracts"), name)
    if name in _DATA_FORWARDS:
        return getattr(importlib.import_module("sceneio._data"), name)
    if name in _CORE_FORWARDS:
        module = importlib.import_module("sceneio._core")
        from sceneio.coordinates import install_core_coordinate_properties

        install_core_coordinate_properties(module)
        return getattr(module, name)
    if name in _IO_TYPE_FORWARDS:
        module_name, attribute = _IO_TYPE_FORWARDS[name]
        return getattr(importlib.import_module(module_name), attribute)
    if name in _IO_FORWARDS:
        return getattr(importlib.import_module("sceneio.io"), name)
    raise AttributeError(f"module 'sceneio' has no attribute {name!r}")


__all__ = [
    "COLMAP_COORDINATES",
    "COLMAP_DATABASE_PROFILES",
    "COLMAP_DATABASE_PROFILES_BY_NAME",
    "COLMAP_DB_TABLES",
    "COLMAP_DB_TABLES_BY_NAME",
    "COLMAP_KNOWN_DESCRIPTOR_DTYPES",
    "COLMAP_KNOWN_EXTRACTOR_TYPES",
    "COLMAP_KNOWN_MARKER_TYPES",
    "COLMAP_KNOWN_MATCHER_TYPES",
    "COLMAP_KNOWN_MATCH_SOURCE_FLAGS",
    "CONTRACT_NAME",
    "CONTRACT_SCHEMA_VERSION",
    "CORRESPONDENCE_MODES",
    "DATABASE_SCHEMA_REVISION",
    "DATABASE_VERSION_NUMBER",
    "DEFAULT_CONVENTION",
    "EXTENSION_COLUMNS",
    "EXTENSION_TABLES",
    "HEADER_FMT",
    "HEADER_SIZE",
    "IMAGE_COORDINATES",
    "LABEL_MAP_SCHEMA",
    "MAGIC",
    "MAXX_DATABASE_APPLICATION_ID",
    "MAX_NUM_IMAGES",
    "POINTMAP_FRAMES",
    "POSE_CONVENTIONS",
    "PUBLIC_TYPE_CONTRACTS",
    "RASTER_AXES",
    "RASTER_DTYPES",
    "RASTER_PAYLOAD_KINDS",
    "RECORD_FMT",
    "RECORD_SIZE",
    "REPRESENTATION_CONTRACTS",
    "REPRESENTATION_CONTRACT_SCHEMA_VERSION",
    "REPRESENTATION_PROFILES",
    "REPRESENTATION_UNIT_VOCABULARY",
    "SCALE_CLASSES",
    "SCALE_PROVENANCES",
    "SE3",
    "UNDEFINED_EXTRACTOR_TYPE",
    "UNKNOWN_COORDINATES",
    "UNSPECIFIED_FORMAT_COORDINATES",
    "UPSTREAM_TABLES",
    "ArrayInspection",
    "BlobStore",
    "Calibration",
    "CameraIntrinsics",
    "CameraModel",
    "CameraRig",
    "CheckpointRef",
    "Codec",
    "CodecCapabilities",
    "ColmapDatabase",
    "ColmapDatabaseConversionReport",
    "ColmapMarkerSet",
    "ColmapMaxxSchemaInfo",
    "ColmapPosePriorSet",
    "ColmapRigFrameSet",
    "ColmapVideoMetadataSet",
    "ColumnDef",
    "ConfidenceMap",
    "ConsistencyGraph",
    "ContractViolation",
    "CoordinateConvention",
    "CorrespondenceGraph",
    "DatabaseProfile",
    "DepthEncoding",
    "DepthMap",
    "FeatureSet",
    "FlowField",
    "FormatCoordinateContract",
    "FormatError",
    "FrameMeta",
    "GaussianCloud",
    "HlocFeatureStore",
    "HlocMatchStore",
    "Image",
    "ImageRef",
    "ImageSequence",
    "ImageSourceImpl",
    "ImuCalibration",
    "ImuSequence",
    "Inspection",
    "InstanceMap",
    "InstanceSet",
    "LabelTaxonomy",
    "Mask",
    "MaterialSet",
    "MaterializedImage",
    "Mesh",
    "NCoreArray",
    "NCoreComponent",
    "NCoreComponentData",
    "NCoreDataset",
    "NCoreDatasetData",
    "NCoreGroup",
    "NCoreItem",
    "NCoreSelection",
    "NCoreSemanticComponent",
    "NCoreStore",
    "NativeFeatureCapabilities",
    "NormalMap",
    "NormalizationProfile",
    "PairCorrespondences",
    "PanopticMap",
    "Point3DRecord",
    "PointCloud",
    "PointScan",
    "PointVisibility",
    "Pointmap",
    "PoseGraph",
    "PosePrior",
    "PosedViewSet",
    "RasterCollection",
    "RasterLevel",
    "RasterSeries",
    "RayMap",
    "Reconstruction",
    "RepresentationNormalizationContract",
    "RtmvDataset",
    "ScanSet",
    "SceneGraph",
    "SceneIoError",
    "SemanticMap",
    "Sim3",
    "StateTrajectory",
    "TableDef",
    "TensorDict",
    "TrackObservation",
    "TwoViewGeometry",
    "ViewInput",
    "VisualInertialDataset",
    "VolumeAsset",
    "__version__",
    "camera_intrinsics",
    "capabilities",
    "checkpoint_root",
    "codecs",
    "colmap",
    "colmap_database_conversion_report",
    "colmap_mvs",
    "contract_dict",
    "contracts",
    "convert_coordinates",
    "convert_gaussian_conventions",
    "coordinate_contract",
    "coordinate_convention",
    "decode_records",
    "depth_map",
    "detect",
    "encode_all",
    "feature_set",
    "formats",
    "gc_checkpoints",
    "image_pair_to_pair_id",
    "inspect",
    "inspect_depth",
    "inspect_e57_scans",
    "inspect_flow",
    "inspect_label_map",
    "inspect_tiff_collection",
    "io",
    "is_colmap_native_extractor_type",
    "is_extension_column",
    "is_extension_table",
    "latest_checkpoint",
    "list_checkpoints",
    "make_database_version_number",
    "mapping",
    "matches_are_type_compatible",
    "matching",
    "materialize_ncore_v4",
    "native_features",
    "pair_id_to_image_pair",
    "point_cloud",
    "project_ncore_item",
    "public_type_contract",
    "read",
    "read_depth",
    "read_e57_scan",
    "read_e57_scans",
    "read_euroc_dataset",
    "read_flow",
    "read_header",
    "read_label_map",
    "read_ncore_component",
    "read_ncore_semantic_component",
    "read_partial",
    "read_record",
    "read_scene",
    "read_tiff_collection",
    "representation_contract",
    "testing",
    "validate_sha",
    "write",
    "write_checkpoint",
    "write_colmap_db",
    "write_depth",
    "write_e57_scans",
    "write_euroc_dataset",
    "write_flow",
    "write_header",
    "write_label_map",
    "write_ncore_v4",
    "write_openvdb",
    "write_record",
    "write_scene",
    "write_tiff",
    "write_tiff_collection",
    "write_usd",
    "write_usdz",
    "write_zarr",
]
