# Representation normalization and scaling

SceneIO has a versioned, machine-readable numeric contract for every public
data-bearing class in `sceneio.io`, `sceneio.data`, `sceneio.colmap`, and
`sceneio.colmap_mvs`. Version 1 covers 98 representations. Registry helpers,
errors, capability/inspection results, and enums are not data representations
and are excluded by an exact test allowlist.

The source of truth is `sceneio.REPRESENTATION_CONTRACTS`. A contract answers
four separate questions that must not be collapsed into the word
"normalized":

1. **Structural normalization:** are dtype, shape, layout, ordering, or value
   bounds canonical, preserved, metadata-declared, mixed, or delegated to
   children?
2. **Scale:** are values dimensionless, pixels, known metric values, arbitrary
   world units, record-declared, child-declared, mixed, or not applicable?
3. **Coordinates:** are axes/frame semantics fixed, declared on the record,
   inherited from a parent/child, unknown, or not applicable?
4. **Conversion:** can the public converter act directly, does a format/profile
   adapter own the conversion, is caller context required, or is conversion
   meaningless?

Canonical storage is not a metric claim. In particular, float32 positions,
unit quaternions, contiguous arrays, and a COLMAP camera convention do not by
themselves establish meters.

## Public API

```python
import sceneio

image_contract = sceneio.representation_contract(sceneio.Image)
assert image_contract.profile.id == "image_samples"
assert image_contract.normalization == "preserve"

cloud_contract = sceneio.representation_contract("sceneio.PointCloud")
assert cloud_contract.scale_fields == (
    "scale_to_meters",
    "coordinate_frame",
    "intensity_range",
    "display_color_space",
)

# The compiled and neutral DepthMap records intentionally have different
# contracts, so a bare ambiguous name is refused.
compiled = sceneio.representation_contract("sceneio.DepthMap")
neutral = sceneio.representation_contract("sceneio.data.DepthMap")
```

`REPRESENTATION_PROFILES` is an immutable mapping of reusable standard
profiles. `REPRESENTATION_CONTRACTS` is an immutable mapping from public import
path to `RepresentationNormalizationContract`. Each entry names executable
repository evidence. The API accepts a record instance, record class, exact
public path, or an unambiguous short name.

`REPRESENTATION_UNIT_VOCABULARY` is the closed set of unit/category tokens used
by version 1. Profile construction rejects an unregistered token, so spelling
drift cannot quietly create two meanings for the same quantity.

## Policy vocabulary

### Structural normalization

| Value | Meaning |
|---|---|
| `canonical` | The record enforces the stated dtype/layout/order or bounded numeric form. |
| `preserve` | Values retain their source meaning; the record does not activate, color-convert, rescale, or renormalize them. |
| `declared` | Metadata fields provide the interpretation; the values are unchanged. |
| `mixed` | Different fields have different canonical/preserved/declared rules, enumerated by the profile. |
| `aggregate` | Child records remain authoritative for their payloads. |
| `not_applicable` | The class has no numeric payload to normalize. |

### Scale

| Value | Meaning |
|---|---|
| `identity` | Dimensionless or index values need no physical scaling. |
| `pixel` | Quantities use image pixels and require the declared origin/first-pixel center. |
| `metric` | The profile fixes the relevant physical unit; its rules name that unit. |
| `arbitrary` | A consistent world/source unit may exist, but it is not meters. |
| `record_declared` | A field such as `scale_to_meters`, `meters_per_unit`, or a unit tag controls conversion. |
| `component_declared` | A child/profile/owning frame controls each component's scale. |
| `mixed` | The representation combines several scale domains. |
| `not_applicable` | There is no scaled numeric quantity. |

For qualified fields governed by `scale_to_meters`, the standard equation is
`meters = stored_length * scale_to_meters`. A default numeric value on an
unknown-frame point or mesh record is not by itself a metric claim. For a USD stage it is
`meters = stage_length * meters_per_unit`. A zero/absent/unknown scale is not
convertible. `FrameMeta(scale="metric")` establishes meters for its neutral
contract; `normalized` and `arbitrary` do not.

## Important representation rules

- `Image` preserves stored samples. `color_space`, `alpha_mode`, and `maxval`
  describe them; construction does not rescale or color-convert pixels.
- `Mask` is canonical HxW bool, with `True` meaning the pixel participates.
  `ConfidenceMap` is finite float32 in `[0, 1]`; arbitrary scores cannot be
  relabeled as confidence.
- `sceneio.data.LabelTaxonomy` gives semantic `int32` ids an explicit identity
  and version. `sceneio.data.SemanticMap` keeps those ids separate from its
  void id; `sceneio.data.InstanceMap` keeps `int64` instance ids separate from
  its background id and optional class table. `sceneio.data.PanopticMap`
  composes the two child rasters without packing or copying them. Packing is an
  explicit checked conversion with a caller-supplied divisor and output dtype.
- Compiled `DepthMap` preserves raw float32 depth and supplies
  `scale_to_meters`, unit, invalid-value, and depth-interpretation metadata.
  Neutral `sceneio.data.DepthMap` inherits length scale from its owning
  `FrameMeta`.
- `PointCloud` and `Mesh` carry an explicit frame and `scale_to_meters`; their
  public coordinate conversion is direct and refuses fields it cannot preserve.
- `Reconstruction` is canonical COLMAP—OpenCV axes, WXYZ world-to-camera
  poses, upper-left image coordinates—but its world scale remains arbitrary.
- `PosedViewSet` records pose direction, axis frame, quaternion order, and
  `scale_to_meters`; it is the third directly convertible compiled record.
- `ImuCalibration` fixes sensor-to-reference translation to meters, preserves
  optional SI-derived noise terms without replacing absence by zero, and uses
  `reference_time_ns = sensor_time_ns + time_offset_ns`. `ImuSequence` keeps
  exact nanosecond sample times, declared measurement units, sensor axes, and
  clock domain; it never synchronizes, resamples, or converts units implicitly.
- `VisualInertialDataset` is an aggregate: camera rigs, lazy image streams,
  IMU calibrations/samples, and optional state trajectories retain their child
  contracts. Exact per-stream clock domains and epochs are preserved; no
  synchronization or interpolation is inferred.
- `ImageSequence` acquisition metadata uses exact nanosecond durations. A
  declared timestamp reference and readout direction make rolling exposure
  timing interpretable; unsupported writers refuse it rather than dropping it.
- `GaussianCloud` declares log/linear scale space, logit/linear opacity,
  WXYZ/XYZW quaternion layout, SH memory layout, and source precision. Its mean
  positions have no coordinate-frame or meters-per-unit field. Explicit
  Gaussian conversion therefore covers represented activation/layout/order
  semantics, not a universal world-frame, color-space, SH-basis/phase, or
  physical-scale normalization.
- `TensorDict`, HDF5/hloc, NCore, and workspace/container records never infer
  numeric semantics from array names. Recognized profiles or child records
  declare units; unknown arrays remain lossless and unqualified.

## Exact version-1 coverage

Profiles are reusable so the contract remains manageable as formats and data
models grow. Every public representation still has its own mapping entry.

| Profile | Public representations |
|---|---|
| `camera_intrinsics` | `sceneio.Camera`, `sceneio.data.CameraIntrinsics` |
| `camera_rig` | `sceneio.CameraRig` |
| `imu_calibration` | `sceneio.ImuCalibration` |
| `imu_sequence` | `sceneio.ImuSequence` |
| `visual_inertial_dataset` | `sceneio.VisualInertialDataset` |
| `colmap_database` | `sceneio.ColmapDatabase` |
| `colmap_marker_companion` | `sceneio.ColmapMarkerSet`, `sceneio.colmap.SparseMarker` |
| `colmap_pose_prior_companion` | `sceneio.ColmapPosePriorSet` |
| `colmap_rig_frame_companion` | `sceneio.ColmapRigFrameSet` |
| `structural_metadata` | `sceneio.ColmapMaxxSchemaInfo`, `sceneio.colmap.IdTags`, `sceneio.colmap.MegaLocImage`, `sceneio.colmap_mvs.LegacyMvsImageRef`, `sceneio.colmap_mvs.PatchMatchProblem` |
| `video_metadata` | `sceneio.ColmapVideoMetadataSet` |
| `index_graph` | `sceneio.ConsistencyGraph`, `sceneio.PointVisibility`, `sceneio.colmap_mvs.PmvsVisibilityGraph` |
| `depth_declared` | `sceneio.DepthMap` |
| `features` | `sceneio.FeatureSet`, `sceneio.data.FeatureSet` |
| `optical_flow` | `sceneio.FlowField` |
| `gaussian_cloud` | `sceneio.GaussianCloud` |
| `hloc_features` | `sceneio.HlocFeatureStore` |
| `hloc_matches` | `sceneio.HlocMatchStore` |
| `image_samples` | `sceneio.Image` |
| `image_sequence` | `sceneio.ImageSequence` |
| `instances` | `sceneio.InstanceSet` |
| `matches` | `sceneio.MatchGraph`, `sceneio.data.CorrespondenceGraph`, `sceneio.data.PairCorrespondences`, `sceneio.data.TwoViewGeometry` |
| `materials` | `sceneio.MaterialSet` |
| `mesh` | `sceneio.Mesh` |
| `mesh_scene` | `sceneio.MeshScene` |
| `ncore_schema` | `sceneio.NCoreArray`, `sceneio.NCoreComponent`, `sceneio.NCoreDataset`, `sceneio.NCoreGroup`, `sceneio.NCoreSelection`, `sceneio.NCoreStore` |
| `ncore_payload` | `sceneio.NCoreComponentData`, `sceneio.NCoreDatasetData`, `sceneio.NCoreItem`, `sceneio.NCoreSemanticComponent` |
| `normal_vectors` | `sceneio.NormalMap` |
| `point_cloud` | `sceneio.PointCloud` |
| `pose_graph` | `sceneio.PoseGraph` |
| `posed_views` | `sceneio.PosedViewSet` |
| `reconstruction_colmap` | `sceneio.Reconstruction` |
| `rtmv_dataset` | `sceneio.RtmvDataset` |
| `scene_graph` | `sceneio.SceneGraph` |
| `state_trajectory` | `sceneio.StateTrajectory` |
| `tensor_container` | `sceneio.TensorDict` |
| `volume_reference` | `sceneio.VolumeAsset` |
| `se3` | `sceneio.data.SE3` |
| `calibration_union` | `sceneio.data.Calibration` |
| `confidence_unit_interval` | `sceneio.data.ConfidenceMap` |
| `depth_parent_scale` | `sceneio.data.DepthMap` |
| `frame_meta` | `sceneio.data.FrameMeta` |
| `binary_mask` | `sceneio.data.Mask` |
| `label_taxonomy` | `sceneio.data.LabelTaxonomy` |
| `semantic_labels` | `sceneio.data.SemanticMap` |
| `instance_labels` | `sceneio.data.InstanceMap` |
| `panoptic_labels` | `sceneio.data.PanopticMap` |
| `pointmap_parent_scale` | `sceneio.data.Pointmap` |
| `pose_prior` | `sceneio.data.PosePrior` |
| `posed_views_parent` | `sceneio.data.PosedViewSet` |
| `unit_ray_map` | `sceneio.data.RayMap` |
| `sim3` | `sceneio.data.Sim3` |
| `track_observation` | `sceneio.data.TrackObservation` |
| `tracked_point_cloud` | `sceneio.data.TrackedPointCloud` |
| `view_input` | `sceneio.data.ViewInput` |
| `colmap_adapter_calibration` | `sceneio.colmap.CharucoBoard`, `sceneio.colmap.CharucoCalibration`, `sceneio.colmap.MappingCamera` |
| `colmap_adapter_scene` | `sceneio.colmap.ExtendedSparseModel`, `sceneio.colmap.MappingInput`, `sceneio.colmap.SparseExtensions` |
| `megaloc_artifacts` | `sceneio.colmap.MegaLocArtifacts` |
| `retrieval_pair` | `sceneio.colmap.MegaLocPair` |
| `colmap_adapter_features` | `sceneio.colmap.MappingImage`, `sceneio.colmap.MappingMatch`, `sceneio.colmap.NamedMatches`, `sceneio.colmap.SiftFeatures`, `sceneio.colmap.SparseMarkerProjection` |
| `colmap_rig_configuration` | `sceneio.colmap.RigConfigCamera`, `sceneio.colmap.RigConfiguration` |
| `colmap_adapter_sim3` | `sceneio.colmap.SimilarityTransform` |
| `time_metadata` | `sceneio.colmap.TimeFrame` |
| `mvs_workspace` | `sceneio.colmap_mvs.ColmapMvsWorkspace`, `sceneio.colmap_mvs.DenseMapSet`, `sceneio.colmap_mvs.LegacyMvsWorkspace`, `sceneio.colmap_mvs.WorkspaceInspection`, `sceneio.colmap_mvs.WorkspaceValidation` |
| `mvs_projection` | `sceneio.colmap_mvs.ProjectionMatrix` |

## Verification and change policy

`tests/test_representation_contracts.py` discovers exported classes from all
four namespaces and requires exact equality with the 98-entry catalog. It also
checks profile vocabulary, immutable lookup behavior, live evidence paths,
ambiguous-name refusal, the exact three direct-conversion records, narrow
metric claims, compiled/neutral record distinctions, and Gaussian limitations.

Format-specific decode/encode normalization remains governed by the 74-row
oracle ledger in
[`tests/contracts/coordinate_conversions_v1.toml`](../tests/contracts/coordinate_conversions_v1.toml)
and the independent I/O ledger in
[`tests/contracts/io_oracles_v1.toml`](../tests/contracts/io_oracles_v1.toml).
Those prove file-to-record behavior; this document defines the in-memory
meaning after decode.

Adding a public representation requires an additive version-1 entry and
evidence. Adding fields or a new profile is additive. Changing the meaning of
an existing field, unit equation, default, or refusal rule requires a new
schema version or a compatibility-preserving migration API; existing values
are never silently reinterpreted in place.
