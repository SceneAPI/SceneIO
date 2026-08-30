# Public type contracts

This page is the current, generated coverage view for every public SceneIO
class identity. It complements the specialized numeric rules in
[Representation normalization](representation_normalization.md) and the
runtime codec inventory in [Format coverage](format_coverage.md). The
[standardization plan](plans/completed/public_type_contract_standardization_2026-08-29.md) records
the compatibility decisions and implementation gates that produced this API.

<!-- sceneio-public-contract-summary:start -->
**Generated public-type contract:** SceneIO classifies all **144 public class
identities**: **103** representations, **21** descriptors, **5** procedure values, **6**
protocols, **3** vocabularies, **5** errors, and **1** wire record. The catalog records
**60 supported alias paths** and relates all **26 built-in payload kinds** to the public
types and formats they carry. Values come directly from
`sceneio.contracts.PUBLIC_TYPE_CONTRACTS` and
`sceneio.contracts.BUILTIN_CODEC_PAYLOAD_KINDS`.
<!-- sceneio-public-contract-summary:end -->

## Lookup API

Use the generic lookup when code needs to discover what a public class means,
which aliases it supports, what evidence owns it, or how it relates to an
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

Canonical paths, supported aliases, classes, instances, and unambiguous short
names are accepted. Ambiguous short names, such as `DepthMap`, require a
qualified path. Unknown strings and unsupported objects fail explicitly.

For normalization, scale, coordinate, or conversion details on one of the 103
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
module paths are diagnostic lookup identities, not supported public aliases.

The `adapts_to` relation connects the distinct loaded and neutral camera,
feature, match, depth, and posed-view roles implemented by
`sceneio.canonical`. It records that an explicit checked adapter exists; it
does not assert universal losslessness. Adapter-specific context, loss, and
refusal rules are documented in
[Loaded records and neutral contracts](canonicalization.md).

The catalog is provider-independent: importing `sceneio.contracts` does not
load NumPy, the compiled core, mapping or matching implementations, or optional
format providers.

## Public class coverage

The detail column contains the normalization profile for representations or
the machine-readable role for procedure values. A dash means that the generic
kind-specific contract is authoritative.

| Canonical public path | Kind | Supported aliases | Specialized profile / procedure role |
|---|---|---|---|
<!-- sceneio-public-type-rows:start -->
| `sceneio.ArrayInspection` | `descriptor` | `sceneio.io.ArrayInspection` | - |
| `sceneio.BlobStore` | `protocol` | - | - |
| `sceneio.Camera` | `representation` | `sceneio.io.Camera` | `camera_intrinsics` |
| `sceneio.CameraRig` | `representation` | `sceneio.io.CameraRig` | `camera_rig` |
| `sceneio.CheckpointRef` | `descriptor` | - | - |
| `sceneio.CodecCapabilities` | `descriptor` | `sceneio.io.CodecCapabilities` | - |
| `sceneio.ColmapDatabase` | `representation` | `sceneio.io.ColmapDatabase` | `colmap_database` |
| `sceneio.ColmapDatabaseConversionReport` | `descriptor` | `sceneio.io.ColmapDatabaseConversionReport` | - |
| `sceneio.ColmapMarkerSet` | `representation` | `sceneio.io.ColmapMarkerSet` | `colmap_marker_companion` |
| `sceneio.ColmapMaxxSchemaInfo` | `representation` | `sceneio.io.ColmapMaxxSchemaInfo` | `structural_metadata` |
| `sceneio.ColmapPosePriorSet` | `representation` | `sceneio.io.ColmapPosePriorSet` | `colmap_pose_prior_companion` |
| `sceneio.ColmapRigFrameSet` | `representation` | `sceneio.io.ColmapRigFrameSet` | `colmap_rig_frame_companion` |
| `sceneio.ColmapVideoMetadataSet` | `representation` | `sceneio.io.ColmapVideoMetadataSet` | `video_metadata` |
| `sceneio.ColumnDef` | `descriptor` | - | - |
| `sceneio.ConsistencyGraph` | `representation` | `sceneio.io.ConsistencyGraph` | `index_graph` |
| `sceneio.ContractViolation` | `error` | - | - |
| `sceneio.CoordinateConvention` | `descriptor` | `sceneio.io.CoordinateConvention` | - |
| `sceneio.DatabaseProfile` | `descriptor` | - | - |
| `sceneio.DepthEncoding` | `descriptor` | `sceneio.io.DepthEncoding` | - |
| `sceneio.DepthMap` | `representation` | `sceneio.io.DepthMap` | `depth_declared` |
| `sceneio.FeatureSet` | `representation` | `sceneio.io.FeatureSet` | `features` |
| `sceneio.FlowField` | `representation` | `sceneio.io.FlowField` | `optical_flow` |
| `sceneio.FormatCoordinateContract` | `descriptor` | `sceneio.io.FormatCoordinateContract` | - |
| `sceneio.FormatError` | `error` | `sceneio.io.FormatError` | - |
| `sceneio.GaussianCloud` | `representation` | `sceneio.io.GaussianCloud` | `gaussian_cloud` |
| `sceneio.HlocFeatureStore` | `representation` | `sceneio.io.HlocFeatureStore` | `hloc_features` |
| `sceneio.HlocMatchStore` | `representation` | `sceneio.io.HlocMatchStore` | `hloc_matches` |
| `sceneio.Image` | `representation` | `sceneio.io.Image` | `image_samples` |
| `sceneio.ImageSequence` | `representation` | `sceneio.io.ImageSequence` | `image_sequence` |
| `sceneio.ImageSourceImpl` | `protocol` | - | - |
| `sceneio.ImuCalibration` | `representation` | `sceneio.io.ImuCalibration` | `imu_calibration` |
| `sceneio.ImuSequence` | `representation` | `sceneio.io.ImuSequence` | `imu_sequence` |
| `sceneio.Inspection` | `descriptor` | `sceneio.io.Inspection` | - |
| `sceneio.InstanceSet` | `representation` | `sceneio.io.InstanceSet` | `instances` |
| `sceneio.MatchGraph` | `representation` | `sceneio.io.MatchGraph` | `matches` |
| `sceneio.MaterialSet` | `representation` | `sceneio.io.MaterialSet` | `materials` |
| `sceneio.MaterializedImage` | `descriptor` | - | - |
| `sceneio.Mesh` | `representation` | `sceneio.io.Mesh` | `mesh` |
| `sceneio.MeshScene` | `representation` | `sceneio.io.MeshScene` | `mesh_scene` |
| `sceneio.NCoreArray` | `representation` | `sceneio.io.NCoreArray` | `ncore_schema` |
| `sceneio.NCoreComponent` | `representation` | `sceneio.io.NCoreComponent` | `ncore_schema` |
| `sceneio.NCoreComponentData` | `representation` | `sceneio.io.NCoreComponentData` | `ncore_payload` |
| `sceneio.NCoreDataset` | `representation` | `sceneio.io.NCoreDataset` | `ncore_schema` |
| `sceneio.NCoreDatasetData` | `representation` | `sceneio.io.NCoreDatasetData` | `ncore_payload` |
| `sceneio.NCoreGroup` | `representation` | `sceneio.io.NCoreGroup` | `ncore_schema` |
| `sceneio.NCoreItem` | `representation` | `sceneio.io.NCoreItem` | `ncore_payload` |
| `sceneio.NCoreSelection` | `representation` | `sceneio.io.NCoreSelection` | `ncore_schema` |
| `sceneio.NCoreSemanticComponent` | `representation` | `sceneio.io.NCoreSemanticComponent` | `ncore_payload` |
| `sceneio.NCoreStore` | `representation` | `sceneio.io.NCoreStore` | `ncore_schema` |
| `sceneio.NativeFeatureCapabilities` | `descriptor` | `sceneio.io.NativeFeatureCapabilities` | - |
| `sceneio.NormalMap` | `representation` | `sceneio.io.NormalMap` | `normal_vectors` |
| `sceneio.NormalizationProfile` | `descriptor` | - | - |
| `sceneio.Point3DRecord` | `wire_record` | - | - |
| `sceneio.PointCloud` | `representation` | `sceneio.io.PointCloud` | `point_cloud` |
| `sceneio.PointScan` | `representation` | `sceneio.io.PointScan` | `point_scan` |
| `sceneio.PointVisibility` | `representation` | `sceneio.io.PointVisibility` | `index_graph` |
| `sceneio.PoseGraph` | `representation` | `sceneio.io.PoseGraph` | `pose_graph` |
| `sceneio.PosedViewSet` | `representation` | `sceneio.io.PosedViewSet` | `posed_views` |
| `sceneio.Reconstruction` | `representation` | `sceneio.io.Reconstruction` | `reconstruction_colmap` |
| `sceneio.RepresentationNormalizationContract` | `descriptor` | - | - |
| `sceneio.RtmvDataset` | `representation` | `sceneio.io.RtmvDataset` | `rtmv_dataset` |
| `sceneio.ScanSet` | `representation` | `sceneio.io.ScanSet` | `scan_set` |
| `sceneio.SceneGraph` | `representation` | `sceneio.io.SceneGraph` | `scene_graph` |
| `sceneio.SceneIoError` | `error` | - | - |
| `sceneio.StateTrajectory` | `representation` | `sceneio.io.StateTrajectory` | `state_trajectory` |
| `sceneio.TableDef` | `descriptor` | - | - |
| `sceneio.TensorDict` | `representation` | `sceneio.io.TensorDict` | `tensor_container` |
| `sceneio.VisualInertialDataset` | `representation` | `sceneio.io.VisualInertialDataset` | `visual_inertial_dataset` |
| `sceneio.VolumeAsset` | `representation` | `sceneio.io.VolumeAsset` | `volume_reference` |
| `sceneio.colmap.CharucoBoard` | `representation` | - | `colmap_adapter_calibration` |
| `sceneio.colmap.CharucoCalibration` | `representation` | - | `colmap_adapter_calibration` |
| `sceneio.colmap.ColmapAdapterError` | `error` | - | - |
| `sceneio.colmap.ExtendedSparseModel` | `representation` | - | `colmap_adapter_scene` |
| `sceneio.colmap.IdTags` | `representation` | - | `structural_metadata` |
| `sceneio.colmap.MappingCamera` | `representation` | - | `colmap_adapter_calibration` |
| `sceneio.colmap.MappingImage` | `representation` | - | `colmap_adapter_features` |
| `sceneio.colmap.MappingInput` | `representation` | - | `colmap_adapter_scene` |
| `sceneio.colmap.MappingMatch` | `representation` | - | `colmap_adapter_features` |
| `sceneio.colmap.MegaLocArtifacts` | `representation` | - | `megaloc_artifacts` |
| `sceneio.colmap.MegaLocImage` | `representation` | - | `structural_metadata` |
| `sceneio.colmap.MegaLocPair` | `representation` | - | `retrieval_pair` |
| `sceneio.colmap.NamedMatches` | `representation` | - | `colmap_adapter_features` |
| `sceneio.colmap.RigConfigCamera` | `representation` | - | `colmap_rig_configuration` |
| `sceneio.colmap.RigConfiguration` | `representation` | - | `colmap_rig_configuration` |
| `sceneio.colmap.SiftFeatures` | `representation` | - | `colmap_adapter_features` |
| `sceneio.colmap.SimilarityTransform` | `representation` | - | `colmap_adapter_sim3` |
| `sceneio.colmap.SparseExtensions` | `representation` | - | `colmap_adapter_scene` |
| `sceneio.colmap.SparseMarker` | `representation` | - | `colmap_marker_companion` |
| `sceneio.colmap.SparseMarkerProjection` | `representation` | - | `colmap_adapter_features` |
| `sceneio.colmap.TimeFrame` | `representation` | - | `time_metadata` |
| `sceneio.colmap_mvs.ColmapMvsError` | `error` | - | - |
| `sceneio.colmap_mvs.ColmapMvsWorkspace` | `representation` | - | `mvs_workspace` |
| `sceneio.colmap_mvs.DenseMapSet` | `representation` | - | `mvs_workspace` |
| `sceneio.colmap_mvs.LegacyMvsImageRef` | `representation` | - | `structural_metadata` |
| `sceneio.colmap_mvs.LegacyMvsWorkspace` | `representation` | - | `mvs_workspace` |
| `sceneio.colmap_mvs.PatchMatchProblem` | `representation` | - | `structural_metadata` |
| `sceneio.colmap_mvs.PmvsVisibilityGraph` | `representation` | - | `index_graph` |
| `sceneio.colmap_mvs.ProjectionMatrix` | `representation` | - | `mvs_projection` |
| `sceneio.colmap_mvs.WorkspaceInspection` | `representation` | - | `mvs_workspace` |
| `sceneio.colmap_mvs.WorkspaceValidation` | `representation` | - | `mvs_workspace` |
| `sceneio.contracts.CodecPayloadKind` | `descriptor` | - | - |
| `sceneio.contracts.ContractEvidence` | `descriptor` | - | - |
| `sceneio.contracts.ContractMember` | `descriptor` | - | - |
| `sceneio.contracts.ContractRelation` | `descriptor` | - | - |
| `sceneio.contracts.PublicTypeContract` | `descriptor` | - | - |
| `sceneio.data.Calibration` | `representation` | - | `calibration_union` |
| `sceneio.data.CameraIntrinsics` | `representation` | - | `camera_intrinsics` |
| `sceneio.data.CameraModel` | `vocabulary` | - | - |
| `sceneio.data.ConfidenceMap` | `representation` | - | `confidence_unit_interval` |
| `sceneio.data.CorrespondenceGraph` | `representation` | - | `matches` |
| `sceneio.data.DepthMap` | `representation` | - | `depth_parent_scale` |
| `sceneio.data.FeatureSet` | `representation` | - | `features` |
| `sceneio.data.FrameMeta` | `representation` | - | `frame_meta` |
| `sceneio.data.InstanceMap` | `representation` | - | `instance_labels` |
| `sceneio.data.LabelTaxonomy` | `representation` | - | `label_taxonomy` |
| `sceneio.data.Mask` | `representation` | - | `binary_mask` |
| `sceneio.data.PairCorrespondences` | `representation` | - | `matches` |
| `sceneio.data.PanopticMap` | `representation` | - | `panoptic_labels` |
| `sceneio.data.Pointmap` | `representation` | - | `pointmap_parent_scale` |
| `sceneio.data.PosePrior` | `representation` | - | `pose_prior` |
| `sceneio.data.PosedViewSet` | `representation` | - | `posed_views_parent` |
| `sceneio.data.RasterCollection` | `representation` | `sceneio.RasterCollection` | `raster_collection` |
| `sceneio.data.RasterLevel` | `representation` | `sceneio.RasterLevel` | `raster_collection` |
| `sceneio.data.RasterSeries` | `representation` | `sceneio.RasterSeries` | `raster_collection` |
| `sceneio.data.RayMap` | `representation` | - | `unit_ray_map` |
| `sceneio.data.SE3` | `representation` | - | `se3` |
| `sceneio.data.SemanticMap` | `representation` | - | `semantic_labels` |
| `sceneio.data.Sim3` | `representation` | - | `sim3` |
| `sceneio.data.TrackObservation` | `representation` | - | `track_observation` |
| `sceneio.data.TrackedPointCloud` | `representation` | - | `tracked_point_cloud` |
| `sceneio.data.TwoViewGeometry` | `representation` | - | `matches` |
| `sceneio.data.ViewInput` | `representation` | - | `view_input` |
| `sceneio.formats.DataType` | `vocabulary` | - | - |
| `sceneio.formats.FormatSpec` | `vocabulary` | - | - |
| `sceneio.io.Codec` | `descriptor` | - | - |
| `sceneio.mapping.Mapper` | `protocol` | - | - |
| `sceneio.mapping.MapperTraits` | `procedure_value` | - | `traits` |
| `sceneio.mapping.MappingOptions` | `procedure_value` | - | `options` |
| `sceneio.mapping.MappingResult` | `procedure_value` | - | `result` |
| `sceneio.matching.FeatureExtractor` | `protocol` | - | - |
| `sceneio.matching.GeometricVerifier` | `protocol` | - | - |
| `sceneio.matching.MatcherTraits` | `procedure_value` | - | `traits` |
| `sceneio.matching.MatchingOptions` | `procedure_value` | - | `options` |
| `sceneio.matching.PairMatcher` | `protocol` | - | - |
<!-- sceneio-public-type-rows:end -->

## Built-in codec payload kinds

`Codec.datatype` remains the stable stored compatibility field. The read-only
`Codec.payload_kind` and `CodecCapabilities.payload_kind` properties give that
value its precise meaning without changing constructor, repr, equality, or
pickle shape. The closed vocabulary below applies only to the 74 repository-
owned built-ins; runtime extensions may continue to use external tokens.

Logical DataType is shown only when the relationship is exact. It is not
inferred from token spelling. Dynamic payloads have an explicit output rule in
the machine-readable catalog because their return class depends on a typed API
or detected file profile.

| Payload kind | Output | Public class contracts | Logical DataType | Built-in formats |
|---|---|---|---|---|
<!-- sceneio-payload-kind-rows:start -->
| `camera_rig` | static | `sceneio.CameraRig` | - | `opencv_yaml`, `opencv_xml`, `ros_camera_info`, `kalibr` |
| `consistency_graph` | static | `sceneio.ConsistencyGraph` | - | `colmap_mvs_consistency` |
| `depth_map` | dynamic | `sceneio.DepthMap`, `sceneio.data.DepthMap` | - | `pfm`, `dmb`, `colmap_mvs_depth` |
| `feature_set` | static | `sceneio.FeatureSet`, `sceneio.HlocFeatureStore` | `feature_set` | `hloc_features` |
| `flow` | dynamic | `sceneio.FlowField` | - | `flo` |
| `image` | static | `sceneio.Image` | - | `netpbm`, `png`, `jpeg`, `bmp`, `tga`, `hdr`, `exr`, `webp`, `avif` |
| `image_or_mask_or_stack` | dynamic | `sceneio.Image`, `sceneio.data.Mask`, `sceneio.data.RasterCollection`, `sceneio.TensorDict` | - | `tiff` |
| `image_sequence` | static | `sceneio.ImageSequence` | `image_sequence` | `y4m`, `webm`, `theora`, `animated_webp`, `apng`, `animated_avif`, `image_sequence` |
| `match_graph` | static | `sceneio.ColmapDatabase`, `sceneio.HlocMatchStore`, `sceneio.MatchGraph` | `match_graph` | `colmap_db`, `hloc_matches` |
| `mesh` | static | `sceneio.Mesh` | - | `ply_mesh`, `obj`, `stl`, `off` |
| `mesh_scene` | static | `sceneio.MeshScene`, `sceneio.SceneGraph` | - | `gltf`, `glb`, `usd`, `usdz` |
| `ncore_dataset` | static | `sceneio.NCoreDataset`, `sceneio.NCoreDatasetData` | - | `ncore_v4` |
| `normal_map` | static | `sceneio.NormalMap` | - | `colmap_mvs_normal` |
| `numeric_table` | static | `sceneio.TensorDict` | - | `parquet`, `arrow_ipc` |
| `point_cloud` | static | `sceneio.PointCloud`, `sceneio.PointScan`, `sceneio.ScanSet` | - | `ply`, `pcd`, `xyz`, `pts`, `las`, `laz`, `e57` |
| `point_visibility` | static | `sceneio.PointVisibility` | - | `colmap_fused_visibility` |
| `pose_graph` | static | `sceneio.PoseGraph` | - | `g2o` |
| `posed_views` | static | `sceneio.PosedViewSet` | - | `transforms_json`, `tum`, `kitti` |
| `rtmv_dataset` | static | `sceneio.RtmvDataset` | - | `rtmv` |
| `sparse_model` | static | `sceneio.Reconstruction` | `sparse_model` | `colmap_sparse`, `colmap_sparse_txt`, `bundler`, `bal`, `nvm`, `openmvg` |
| `sparse_volume` | static | `sceneio.TensorDict`, `sceneio.VolumeAsset` | - | `openvdb` |
| `splat` | static | `sceneio.GaussianCloud` | - | `gaussian_ply`, `compressed_ply`, `sog`, `ksplat`, `spz`, `splat` |
| `state_trajectory` | static | `sceneio.StateTrajectory` | - | `euroc_state` |
| `tensor` | dynamic | - | - | `npy` |
| `tensor_dict` | static | `sceneio.TensorDict` | - | `npz`, `safetensors`, `hdf5`, `zarr` |
| `visual_inertial_dataset` | static | `sceneio.VisualInertialDataset` | - | `euroc_dataset` |
<!-- sceneio-payload-kind-rows:end -->

## Compatibility and extension rules

- Existing canonical classes, aliases, constructors, fields, reprs, pickle
  outcomes, exceptions, wire formats, and normalization contracts are
  unchanged.
- A new public class must be added to the catalog with kind-appropriate members
  and executable evidence in the same change.
- A new built-in codec must select one declared built-in payload kind. A new
  payload kind needs explicit public-type, format, dynamic-output, and logical
  DataType relationships.
- Runtime codec extensions remain open. An external payload token is valid but
  has no SceneIO-owned payload contract unless a future extension API adds one.
- The catalog serialization shape is versioned independently from catalog
  membership. Incompatible changes require an explicit schema/version review.
