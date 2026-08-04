"""sceneio — the contract plane for SceneAPI.

This is a *contract*, not an implementation. It owns both the **data
contracts** and the **procedure contracts** the SceneAPI family agrees
on, organized as import-isolated namespaces:

- :mod:`sceneio.data` — numpy-native datatypes (calibration,
  SE3/Sim3, priors, depth/pointmaps/confidence/masks, features,
  correspondences, tracked point clouds, view inputs, frame metadata).
- :mod:`sceneio.formats` — the disk/wire format-id registry.
- :mod:`sceneio.mapping` — the neutral `Mapper` contract + traits.
- :mod:`sceneio.matching` — `FeatureExtractor` / `PairMatcher` /
  `GeometricVerifier` + traits.
- :mod:`sceneio.testing` — conformance kits for implementations.

Plus the pre-0.2 surface, unchanged and re-exported flat off this
module: the ``application/x-sfm-points-v1`` wire codec
(``points_binary``), the storage / image-source Protocols
(`BlobStore`, `ImageSourceImpl`), the extended COLMAP scene-database
schema (``colmap_db``), the ``PCMAPIN`` checkpoint helpers
(``mapping_input``), and the shared error base (`SceneIoError`, with
`ContractViolation` for contract breaches).

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
        data,
        formats,
        io,
        mapping,
        matching,
        testing,
    )

__version__ = "0.2.0"

# The contract namespaces are import-isolated: they are loaded lazily on
# first attribute access so that `import sceneio` alone stays cheap
# and no namespace ever depends on a sibling being imported.
_NAMESPACES = frozenset(
    {
        "colmap",
        "colmap_mvs",
        "data",
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
        "read",
        "read_depth",
        "read_flow",
        "read_label_map",
        "read_euroc_dataset",
        "read_ncore_component",
        "read_ncore_semantic_component",
        "materialize_ncore_v4",
        "project_ncore_item",
        "read_partial",
        "read_scene",
        "write",
        "write_arrow_ipc",
        "write_colmap_db",
        "colmap_database_conversion_report",
        "write_depth",
        "write_flow",
        "write_label_map",
        "write_euroc_dataset",
        "write_parquet",
        "write_openvdb",
        "write_ncore_v4",
        "write_tiff",
        "write_usd",
        "write_usdz",
        "write_scene",
        "write_zarr",
        "detect",
        "inspect",
        "inspect_depth",
        "inspect_flow",
        "inspect_label_map",
        "capabilities",
        "coordinate_contract",
        "coordinate_convention",
        "codecs",
        "convert_gaussian_conventions",
        "convert_coordinates",
        "native_features",
        "ArrayInspection",
        "Camera",
        "CameraRig",
        "ColmapDatabase",
        "ColmapMarkerSet",
        "ColmapMaxxSchemaInfo",
        "ColmapPosePriorSet",
        "ColmapRigFrameSet",
        "ColmapVideoMetadataSet",
        "ConsistencyGraph",
        "CodecCapabilities",
        "COLMAP_COORDINATES",
        "CoordinateConvention",
        "DepthMap",
        "DepthEncoding",
        "FlowField",
        "FormatCoordinateContract",
        "FeatureSet",
        "FormatError",
        "GaussianCloud",
        "HlocFeatureStore",
        "HlocMatchStore",
        "Image",
        "IMAGE_COORDINATES",
        "ImageSequence",
        "ImuCalibration",
        "ImuSequence",
        "InstanceSet",
        "LABEL_MAP_SCHEMA",
        "Inspection",
        "MatchGraph",
        "MaterialSet",
        "Mesh",
        "MeshScene",
        "NativeFeatureCapabilities",
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
        "NormalMap",
        "PointCloud",
        "PointVisibility",
        "PoseGraph",
        "PosedViewSet",
        "Reconstruction",
        "RtmvDataset",
        "SceneGraph",
        "StateTrajectory",
        "TensorDict",
        "UNKNOWN_COORDINATES",
        "UNSPECIFIED_FORMAT_COORDINATES",
        "VolumeAsset",
        "VisualInertialDataset",
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
    "DATABASE_SCHEMA_REVISION",
    "DATABASE_VERSION_NUMBER",
    "EXTENSION_COLUMNS",
    "EXTENSION_TABLES",
    "HEADER_FMT",
    "HEADER_SIZE",
    "IMAGE_COORDINATES",
    "LABEL_MAP_SCHEMA",
    "MAGIC",
    "MAXX_DATABASE_APPLICATION_ID",
    "MAX_NUM_IMAGES",
    "RECORD_FMT",
    "RECORD_SIZE",
    "REPRESENTATION_CONTRACTS",
    "REPRESENTATION_CONTRACT_SCHEMA_VERSION",
    "REPRESENTATION_PROFILES",
    "REPRESENTATION_UNIT_VOCABULARY",
    "UNDEFINED_EXTRACTOR_TYPE",
    "UNKNOWN_COORDINATES",
    "UNSPECIFIED_FORMAT_COORDINATES",
    "UPSTREAM_TABLES",
    "ArrayInspection",
    "BlobStore",
    "Camera",
    "CameraRig",
    "CheckpointRef",
    "CodecCapabilities",
    "ColmapDatabase",
    "ColmapDatabaseConversionReport",
    "ColmapMarkerSet",
    "ColmapMaxxSchemaInfo",
    "ColmapPosePriorSet",
    "ColmapRigFrameSet",
    "ColmapVideoMetadataSet",
    "ColumnDef",
    "ConsistencyGraph",
    "ContractViolation",
    "CoordinateConvention",
    "DatabaseProfile",
    "DepthEncoding",
    "DepthMap",
    "FeatureSet",
    "FlowField",
    "FormatCoordinateContract",
    "FormatError",
    "GaussianCloud",
    "HlocFeatureStore",
    "HlocMatchStore",
    "Image",
    "ImageSequence",
    "ImageSourceImpl",
    "ImuCalibration",
    "ImuSequence",
    "Inspection",
    "InstanceSet",
    "MatchGraph",
    "MaterialSet",
    "MaterializedImage",
    "Mesh",
    "MeshScene",
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
    "Point3DRecord",
    "PointCloud",
    "PointVisibility",
    "PoseGraph",
    "PosedViewSet",
    "Reconstruction",
    "RepresentationNormalizationContract",
    "RtmvDataset",
    "SceneGraph",
    "SceneIoError",
    "StateTrajectory",
    "TableDef",
    "TensorDict",
    "VisualInertialDataset",
    "VolumeAsset",
    "__version__",
    "capabilities",
    "checkpoint_root",
    "codecs",
    "colmap",
    "colmap_database_conversion_report",
    "colmap_mvs",
    "contract_dict",
    "convert_coordinates",
    "convert_gaussian_conventions",
    "coordinate_contract",
    "coordinate_convention",
    "data",
    "decode_records",
    "detect",
    "encode_all",
    "formats",
    "gc_checkpoints",
    "image_pair_to_pair_id",
    "inspect",
    "inspect_depth",
    "inspect_flow",
    "inspect_label_map",
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
    "project_ncore_item",
    "read",
    "read_depth",
    "read_euroc_dataset",
    "read_flow",
    "read_header",
    "read_label_map",
    "read_ncore_component",
    "read_ncore_semantic_component",
    "read_partial",
    "read_record",
    "read_scene",
    "representation_contract",
    "testing",
    "validate_sha",
    "write",
    "write_checkpoint",
    "write_colmap_db",
    "write_depth",
    "write_euroc_dataset",
    "write_flow",
    "write_header",
    "write_label_map",
    "write_ncore_v4",
    "write_openvdb",
    "write_record",
    "write_scene",
    "write_usd",
    "write_usdz",
    "write_zarr",
]
