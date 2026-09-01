# Public type contracts

This page is the current, generated coverage view for every public SceneIO
class identity. It complements the specialized numeric rules in
[Representation normalization](representation_normalization.md) and the
runtime codec inventory in [Format coverage](format_coverage.md). The
[standardization plan](plans/completed/public_type_contract_standardization_2026-08-29.md) records
the design decisions and implementation gates that produced this API.

<!-- sceneio-public-contract-summary:start -->
**Generated public-type contract:** SceneIO classifies all **131 public class
identities**: **90** representations, **21** descriptors, **5** procedure values, **6**
protocols, **3** vocabularies, **5** errors, and **1** wire record. The catalog records
canonical-only public identities and relates all **27 built-in payload kinds** to the
public types and formats they carry. Values come directly from
`sceneio.contracts.PUBLIC_TYPE_CONTRACTS` and
`sceneio.contracts.BUILTIN_CODEC_PAYLOAD_KINDS`.
<!-- sceneio-public-contract-summary:end -->

## Lookup API

Use the generic lookup when code needs to discover what a public class means,
what evidence owns it, or how it relates to an
operation, format, schema, or payload kind:

```python
import sceneio

contract = sceneio.public_type_contract(sceneio.Point3DRecord)
assert contract.canonical_path == "sceneio.Point3DRecord"
assert contract.kind == "wire_record"

same = sceneio.contracts.public_type_contract(
    "sceneio.points_binary.Point3DRecord"
)
assert same is contract
```

Canonical paths, classes, instances, and unambiguous short names are accepted.
Ambiguous short names, if introduced by an extension, require a qualified
path. Unknown strings and unsupported objects fail explicitly.

For normalization, scale, coordinate, or conversion details on one of the 90
data representations, continue to use `sceneio.representation_contract()`.
The generic representation envelope references the exact same specialized
contract object; it does not copy that authority.

`sceneio.contracts.catalog_dict()` returns a detached, deterministic,
JSON-serializable catalog. It is deliberately namespaced because the existing
`sceneio.contract_dict()` remains the version-3 COLMAP database contract
serializer.

## Contract model

Every entry has one canonical public path, a closed kind, stability, purpose,
member semantics, invariants, refusal behavior, executable evidence, and typed
relations. All model values and public mappings are immutable. Implementation
module paths are diagnostic lookup identities, not additional public paths.

The consolidated 0.4 catalog has no `adapts_to` relations.
Cameras, features, correspondence graphs, depth maps, posed views, point
tracks, and scenes each have one public owner. Format-specific storage carriers
remain private implementation details and cannot be discovered as alternative
public representations.

The catalog is provider-independent: importing `sceneio.contracts` does not
load NumPy, the compiled core, mapping or matching implementations, or optional
format providers.

## Public class coverage

The detail column contains the normalization profile for representations or
the machine-readable role for procedure values. A dash means that the generic
kind-specific contract is authoritative.

| Canonical public path | Kind | Specialized profile / procedure role |
|---|---|---|
<!-- sceneio-public-type-rows:start -->
| `sceneio.ArrayInspection` | `descriptor` | - |
| `sceneio.BlobStore` | `protocol` | - |
| `sceneio.Calibration` | `representation` | `calibration_union` |
| `sceneio.CameraIntrinsics` | `representation` | `camera_intrinsics` |
| `sceneio.CameraModel` | `vocabulary` | - |
| `sceneio.CameraRig` | `representation` | `camera_rig` |
| `sceneio.CheckpointRef` | `descriptor` | - |
| `sceneio.Codec` | `descriptor` | - |
| `sceneio.CodecCapabilities` | `descriptor` | - |
| `sceneio.ColmapDatabase` | `representation` | `colmap_database` |
| `sceneio.ColmapDatabaseConversionReport` | `descriptor` | - |
| `sceneio.ColmapMarkerSet` | `representation` | `colmap_marker_companion` |
| `sceneio.ColmapMaxxSchemaInfo` | `representation` | `structural_metadata` |
| `sceneio.ColmapPosePriorSet` | `representation` | `colmap_pose_prior_companion` |
| `sceneio.ColmapRigFrameSet` | `representation` | `colmap_rig_frame_companion` |
| `sceneio.ColmapVideoMetadataSet` | `representation` | `video_metadata` |
| `sceneio.ColumnDef` | `descriptor` | - |
| `sceneio.ConfidenceMap` | `representation` | `confidence_unit_interval` |
| `sceneio.ConsistencyGraph` | `representation` | `index_graph` |
| `sceneio.ContractViolation` | `error` | - |
| `sceneio.CoordinateConvention` | `descriptor` | - |
| `sceneio.CorrespondenceGraph` | `representation` | `matches` |
| `sceneio.DatabaseProfile` | `descriptor` | - |
| `sceneio.DepthEncoding` | `descriptor` | - |
| `sceneio.DepthMap` | `representation` | `depth_declared` |
| `sceneio.FeatureSet` | `representation` | `features` |
| `sceneio.FlowField` | `representation` | `optical_flow` |
| `sceneio.FormatCoordinateContract` | `descriptor` | - |
| `sceneio.FormatError` | `error` | - |
| `sceneio.FrameMeta` | `representation` | `frame_meta` |
| `sceneio.GaussianCloud` | `representation` | `gaussian_cloud` |
| `sceneio.HlocFeatureStore` | `representation` | `hloc_features` |
| `sceneio.HlocMatchStore` | `representation` | `hloc_matches` |
| `sceneio.Image` | `representation` | `image_samples` |
| `sceneio.ImageSequence` | `representation` | `image_sequence` |
| `sceneio.ImageSourceImpl` | `protocol` | - |
| `sceneio.ImuCalibration` | `representation` | `imu_calibration` |
| `sceneio.ImuSequence` | `representation` | `imu_sequence` |
| `sceneio.Inspection` | `descriptor` | - |
| `sceneio.InstanceMap` | `representation` | `instance_labels` |
| `sceneio.InstanceSet` | `representation` | `instances` |
| `sceneio.LabelTaxonomy` | `representation` | `label_taxonomy` |
| `sceneio.Mask` | `representation` | `binary_mask` |
| `sceneio.MaterialSet` | `representation` | `materials` |
| `sceneio.MaterializedImage` | `descriptor` | - |
| `sceneio.Mesh` | `representation` | `mesh` |
| `sceneio.NCoreArray` | `representation` | `ncore_schema` |
| `sceneio.NCoreComponent` | `representation` | `ncore_schema` |
| `sceneio.NCoreComponentData` | `representation` | `ncore_payload` |
| `sceneio.NCoreDataset` | `representation` | `ncore_schema` |
| `sceneio.NCoreDatasetData` | `representation` | `ncore_payload` |
| `sceneio.NCoreGroup` | `representation` | `ncore_schema` |
| `sceneio.NCoreItem` | `representation` | `ncore_payload` |
| `sceneio.NCoreSelection` | `representation` | `ncore_schema` |
| `sceneio.NCoreSemanticComponent` | `representation` | `ncore_payload` |
| `sceneio.NCoreStore` | `representation` | `ncore_schema` |
| `sceneio.NativeFeatureCapabilities` | `descriptor` | - |
| `sceneio.NormalMap` | `representation` | `normal_vectors` |
| `sceneio.NormalizationProfile` | `descriptor` | - |
| `sceneio.PairCorrespondences` | `representation` | `matches` |
| `sceneio.PanopticMap` | `representation` | `panoptic_labels` |
| `sceneio.Point3DRecord` | `wire_record` | - |
| `sceneio.PointCloud` | `representation` | `point_cloud` |
| `sceneio.PointScan` | `representation` | `point_scan` |
| `sceneio.PointVisibility` | `representation` | `index_graph` |
| `sceneio.Pointmap` | `representation` | `pointmap_parent_scale` |
| `sceneio.PoseGraph` | `representation` | `pose_graph` |
| `sceneio.PosePrior` | `representation` | `pose_prior` |
| `sceneio.PosedViewSet` | `representation` | `posed_views` |
| `sceneio.RasterCollection` | `representation` | `raster_collection` |
| `sceneio.RasterLevel` | `representation` | `raster_collection` |
| `sceneio.RasterSeries` | `representation` | `raster_collection` |
| `sceneio.RayMap` | `representation` | `unit_ray_map` |
| `sceneio.Reconstruction` | `representation` | `reconstruction_colmap` |
| `sceneio.RepresentationNormalizationContract` | `descriptor` | - |
| `sceneio.RtmvDataset` | `representation` | `rtmv_dataset` |
| `sceneio.SE3` | `representation` | `se3` |
| `sceneio.ScanSet` | `representation` | `scan_set` |
| `sceneio.SceneGraph` | `representation` | `scene_graph` |
| `sceneio.SceneIoError` | `error` | - |
| `sceneio.SemanticMap` | `representation` | `semantic_labels` |
| `sceneio.Sim3` | `representation` | `sim3` |
| `sceneio.StateTrajectory` | `representation` | `state_trajectory` |
| `sceneio.TableDef` | `descriptor` | - |
| `sceneio.TensorDict` | `representation` | `tensor_container` |
| `sceneio.TrackObservation` | `representation` | `track_observation` |
| `sceneio.TwoViewGeometry` | `representation` | `matches` |
| `sceneio.ViewInput` | `representation` | `view_input` |
| `sceneio.VisualInertialDataset` | `representation` | `visual_inertial_dataset` |
| `sceneio.VolumeAsset` | `representation` | `volume_reference` |
| `sceneio.colmap.CharucoBoard` | `representation` | `colmap_adapter_calibration` |
| `sceneio.colmap.CharucoCalibration` | `representation` | `colmap_adapter_calibration` |
| `sceneio.colmap.ColmapAdapterError` | `error` | - |
| `sceneio.colmap.ExtendedSparseModel` | `representation` | `colmap_adapter_scene` |
| `sceneio.colmap.IdTags` | `representation` | `structural_metadata` |
| `sceneio.colmap.MappingInput` | `representation` | `colmap_adapter_scene` |
| `sceneio.colmap.MegaLocArtifacts` | `representation` | `megaloc_artifacts` |
| `sceneio.colmap.MegaLocImage` | `representation` | `structural_metadata` |
| `sceneio.colmap.MegaLocPair` | `representation` | `retrieval_pair` |
| `sceneio.colmap.RigConfigCamera` | `representation` | `colmap_rig_configuration` |
| `sceneio.colmap.RigConfiguration` | `representation` | `colmap_rig_configuration` |
| `sceneio.colmap.SparseExtensions` | `representation` | `colmap_adapter_scene` |
| `sceneio.colmap.SparseMarker` | `representation` | `colmap_marker_companion` |
| `sceneio.colmap.SparseMarkerProjection` | `representation` | `colmap_adapter_features` |
| `sceneio.colmap.TimeFrame` | `representation` | `time_metadata` |
| `sceneio.colmap_mvs.ColmapMvsError` | `error` | - |
| `sceneio.colmap_mvs.ColmapMvsWorkspace` | `representation` | `mvs_workspace` |
| `sceneio.colmap_mvs.DenseMapSet` | `representation` | `mvs_workspace` |
| `sceneio.colmap_mvs.LegacyMvsImageRef` | `representation` | `structural_metadata` |
| `sceneio.colmap_mvs.LegacyMvsWorkspace` | `representation` | `mvs_workspace` |
| `sceneio.colmap_mvs.PatchMatchProblem` | `representation` | `structural_metadata` |
| `sceneio.colmap_mvs.PmvsVisibilityGraph` | `representation` | `index_graph` |
| `sceneio.colmap_mvs.ProjectionMatrix` | `representation` | `mvs_projection` |
| `sceneio.colmap_mvs.WorkspaceInspection` | `representation` | `mvs_workspace` |
| `sceneio.colmap_mvs.WorkspaceValidation` | `representation` | `mvs_workspace` |
| `sceneio.contracts.CodecPayloadKind` | `descriptor` | - |
| `sceneio.contracts.ContractEvidence` | `descriptor` | - |
| `sceneio.contracts.ContractMember` | `descriptor` | - |
| `sceneio.contracts.ContractRelation` | `descriptor` | - |
| `sceneio.contracts.PublicTypeContract` | `descriptor` | - |
| `sceneio.formats.DataType` | `vocabulary` | - |
| `sceneio.formats.FormatSpec` | `vocabulary` | - |
| `sceneio.mapping.Mapper` | `protocol` | - |
| `sceneio.mapping.MapperTraits` | `procedure_value` | `traits` |
| `sceneio.mapping.MappingOptions` | `procedure_value` | `options` |
| `sceneio.mapping.MappingResult` | `procedure_value` | `result` |
| `sceneio.matching.FeatureExtractor` | `protocol` | - |
| `sceneio.matching.GeometricVerifier` | `protocol` | - |
| `sceneio.matching.MatcherTraits` | `procedure_value` | `traits` |
| `sceneio.matching.MatchingOptions` | `procedure_value` | `options` |
| `sceneio.matching.PairMatcher` | `protocol` | - |
<!-- sceneio-public-type-rows:end -->

## Built-in codec payload kinds

`Codec.payload_kind` is the single stored codec payload field, and
`CodecCapabilities.payload_kind` exposes the same concept in discovery
metadata. The closed vocabulary below applies only to the 77 repository-owned
built-ins; runtime extensions may continue to use external tokens.

Logical DataType is shown only when the relationship is exact. It is not
inferred from token spelling. Dynamic payloads have an explicit output rule in
the machine-readable catalog because their return class depends on the detected
file profile or an explicitly selected semantic interpretation.

| Payload kind | Output | Public class contracts | Logical DataType | Built-in formats |
|---|---|---|---|---|
<!-- sceneio-payload-kind-rows:start -->
| `camera_rig` | static | `sceneio.CameraRig` | - | `opencv_yaml`, `opencv_xml`, `ros_camera_info`, `kalibr` |
| `consistency_graph` | static | `sceneio.ConsistencyGraph` | - | `colmap_mvs_consistency` |
| `depth_map` | dynamic | `sceneio.DepthMap` | - | `pfm`, `dmb`, `colmap_mvs_depth` |
| `feature_set` | static | `sceneio.FeatureSet`, `sceneio.HlocFeatureStore` | `feature_set` | `hloc_features` |
| `flow` | static | `sceneio.FlowField` | - | `flo` |
| `image` | static | `sceneio.Image` | - | `netpbm`, `png`, `jpeg`, `bmp`, `tga`, `hdr`, `exr`, `webp`, `avif` |
| `image_sequence` | static | `sceneio.ImageSequence` | `image_sequence` | `y4m`, `webm`, `ivf`, `mjpeg`, `mp4`, `theora`, `animated_webp`, `apng`, `animated_avif`, `image_sequence` |
| `match_graph` | static | `sceneio.ColmapDatabase`, `sceneio.HlocMatchStore`, `sceneio.CorrespondenceGraph` | `match_graph` | `colmap_db`, `hloc_matches` |
| `mesh` | static | `sceneio.Mesh` | - | `ply_mesh`, `obj`, `stl`, `off` |
| `scene_graph` | static | `sceneio.SceneGraph` | - | `gltf`, `glb`, `usd`, `usdz` |
| `ncore_dataset` | static | `sceneio.NCoreDataset`, `sceneio.NCoreDatasetData` | - | `ncore_v4` |
| `normal_map` | static | `sceneio.NormalMap` | - | `colmap_mvs_normal` |
| `numeric_table` | static | `sceneio.TensorDict` | - | `parquet`, `arrow_ipc` |
| `point_cloud` | static | `sceneio.PointCloud` | - | `ply`, `pcd`, `xyz`, `pts`, `las`, `laz` |
| `point_visibility` | static | `sceneio.PointVisibility` | - | `colmap_fused_visibility` |
| `pose_graph` | static | `sceneio.PoseGraph` | - | `g2o` |
| `posed_views` | static | `sceneio.PosedViewSet` | - | `transforms_json`, `tum`, `kitti` |
| `raster_collection` | static | `sceneio.RasterCollection` | - | `tiff` |
| `rtmv_dataset` | static | `sceneio.RtmvDataset` | - | `rtmv` |
| `scan_set` | static | `sceneio.ScanSet` | - | `e57` |
| `sparse_model` | static | `sceneio.Reconstruction` | `sparse_model` | `colmap_sparse`, `colmap_sparse_txt`, `bundler`, `bal`, `nvm`, `openmvg` |
| `sparse_volume` | static | `sceneio.TensorDict`, `sceneio.VolumeAsset` | - | `openvdb` |
| `splat` | static | `sceneio.GaussianCloud` | - | `gaussian_ply`, `compressed_ply`, `sog`, `ksplat`, `spz`, `splat` |
| `state_trajectory` | static | `sceneio.StateTrajectory` | - | `euroc_state` |
| `tensor` | dynamic | - | - | `npy` |
| `tensor_dict` | static | `sceneio.TensorDict` | - | `npz`, `safetensors`, `hdf5`, `zarr` |
| `visual_inertial_dataset` | static | `sceneio.VisualInertialDataset` | - | `euroc_dataset` |
<!-- sceneio-payload-kind-rows:end -->

## Evolution and extension rules

- SceneIO is pre-1: public classes and fields may change when a representation
  is canonicalized. Removed identities are not retained through aliases,
  synthetic module names, or pickle shims.
- Supported on-disk profiles and wire formats are independent codec contracts;
  changing the Python representation does not silently change encoded bytes.
- A new public class must be added to the catalog with kind-appropriate members
  and executable evidence in the same change.
- A new built-in codec must select one declared built-in payload kind. A new
  payload kind needs explicit public-type, format, dynamic-output, and logical
  DataType relationships.
- Runtime codec extensions remain open. An external payload token is valid but
  has no SceneIO-owned payload contract unless a future extension API adds one.
- The catalog serialization shape is versioned independently from catalog
  membership. Incompatible catalog-shape changes require an explicit schema
  review.
