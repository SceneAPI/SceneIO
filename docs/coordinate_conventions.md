# Coordinate conventions

SceneIO uses the COLMAP camera convention as its canonical conversion target.
This is a default for explicit conversion and for canonical reconstruction
records; it is not a claim that every file on disk uses COLMAP coordinates.
Readers expose the convention they actually return, and writers reject a
record when the destination format cannot represent that convention.

The machine-checked inventories are:

- [`representation_normalization.md`](representation_normalization.md), which
  gives every public in-memory representation a versioned structural,
  scaling, coordinate-source, conversion, and refusal contract;
- [`tests/contracts/coordinate_systems_v1.toml`](../tests/contracts/coordinate_systems_v1.toml),
  which covers all 74 built-in format ids in registry order; and
- [`tests/contracts/coordinate_conversions_v1.toml`](../tests/contracts/coordinate_conversions_v1.toml),
  which pins the qualified record types, transform direction and units,
  converted fields, preserved fields, refusal rules, and a registry-ordered
  file-to-record/record-to-file oracle ledger for every built-in format.

Adding a built-in codec without classifying its coordinate behavior fails the
contract tests. Changing conversion semantics requires an explicit update to
the versioned conversion contract and its executable tests.

The representation contract is intentionally one layer above this format
ledger. A canonical dtype/layout does not establish meters, and a fixed camera
frame does not imply that samples, descriptors, Gaussian activations, or world
scale were normalized.

## Canonical COLMAP convention

`sceneio.COLMAP_COORDINATES` means:

| Property | Value |
|---|---|
| camera axes | OpenCV: +X right, +Y down, +Z forward |
| handedness | right-handed |
| pose | world-to-camera |
| quaternion | Hamilton, WXYZ |
| image coordinates | origin at upper-left corner, +x right, +y down |
| first pixel center | `(0.5, 0.5)` |
| depth | camera Z |
| world frame | arbitrary |
| scale | arbitrary/non-metric unless separately anchored |

This agrees with the camera conventions documented by
[COLMAP](https://colmap.github.io/cameras.html) and the OpenCV/COLMAP transform
relationships documented by
[CamTools](https://camtools.readthedocs.io/en/stable/camera.html). CamTools is
reference material only: SceneIO does not copy its implementation and does not
depend on it at runtime.

## Public contract

The same immutable `CoordinateConvention` value is available at each discovery
level:

```python
import sceneio

static = sceneio.coordinate_contract("tum")
assert static.status == "fixed"

capability = sceneio.capabilities("tum")
assert capability.coordinates is static

info = sceneio.inspect("trajectory.txt", format="tum")
trajectory = sceneio.read("trajectory.txt", format="tum")
assert info.coordinates == trajectory.coordinates
```

- `coordinate_contract(format_id)` describes the format before a file is
  opened.
- `capabilities(format_id).coordinates` exposes the same registry contract.
- `inspect(path).coordinates` reports the convention determinable without
  decoding bulk arrays.
- `record.coordinates` reports the convention of the returned record.
- `coordinate_convention(record)` is the functional equivalent for callers
  that prefer not to use the property.
- `convert_coordinates(record, target=COLMAP_COORDINATES)` performs a requested
  conversion only for qualified record types.

`CoordinateConvention.name` is descriptive and does not affect equality. The
semantic fields—axes, pose direction, quaternion layout, world frame, scale,
image origin, pixel center, depth interpretation, CRS, and reference frame—do.

## Format status

Each `FormatCoordinateContract` has one of four statuses:

- `fixed`: the format/profile or returned record has one known convention.
- `file_declared`: the file carries convention metadata; inspection and decode
  derive the concrete value from that metadata.
- `unspecified`: the format has no portable convention field. SceneIO returns
  explicit unknown metadata and will not guess.
- `not_applicable`: the payload contains indices or values with no independent
  coordinate interpretation.

The table groups all built-ins by status and coordinate domain. The TOML file
above is the exact per-id source of truth.

| Status | Domains | Formats |
|---|---|---|
| fixed | camera, image, spatial; canonical `Reconstruction` | `colmap_sparse`, `colmap_sparse_txt`, `bundler`, `bal`, `nvm`, `openmvg` |
| fixed | camera, image, spatial | `transforms_json` |
| fixed | camera, trajectory | `tum`, `kitti`, `euroc_state` |
| fixed | camera, image | `opencv_yaml`, `opencv_xml`, `ros_camera_info`, `kalibr`, `colmap_db`, `colmap_mvs_normal` |
| fixed | camera, spatial | `gltf`, `glb` |
| fixed | spatial, trajectory | `g2o` |
| fixed | image | `netpbm`, `png`, `jpeg`, `bmp`, `tga`, `hdr`, `exr`, `webp`, `avif`, `y4m`, `webm`, `theora`, `animated_webp`, `apng`, `animated_avif`, `image_sequence`, `flo`, `colmap_mvs_consistency`, `hloc_features`, `tiff` |
| fixed | depth, image | `colmap_mvs_depth` |
| fixed | camera, depth, image, spatial | `rtmv` |
| file-declared | spatial | `ply_mesh`, `las`, `laz`, `e57` |
| file-declared | camera, spatial | `usd`, `usdz` |
| file-declared | camera, image, trajectory | `euroc_dataset` |
| file-declared | tensor | `ncore_v4` |
| file-declared | spatial, tensor | `openvdb` |
| unspecified | spatial | `gaussian_ply`, `compressed_ply`, `sog`, `ksplat`, `obj`, `stl`, `off`, `ply`, `pcd`, `spz`, `xyz`, `pts`, `splat` |
| unspecified | depth, image | `pfm`, `dmb` |
| unspecified | tensor | `npy`, `npz`, `safetensors`, `hdf5`, `zarr`, `parquet`, `arrow_ipc` |
| not applicable | — | `colmap_fused_visibility`, `hloc_matches` |

Ordinary reads do not silently convert source-native records. The established
`Reconstruction` adapters are the deliberate exception: COLMAP binary/text,
Bundler, BAL, NVM, and OpenMVG already decode into SceneIO's canonical COLMAP
`Reconstruction` representation. Their format parity suites verify that
normalization against independent parsers or project oracles.

Typed dense-label records are image rasters: `SemanticMap`, `InstanceMap`, and
`PanopticMap` use the same upper-left origin, rightward x, downward y, and
`(0.5, 0.5)` first-pixel center as `IMAGE_COORDINATES`. Their numeric ids have
identity semantics and no physical scale. Raw NPZ/Zarr `TensorDict`, TIFF
image/stack, and NCore component reads retain their carrier-native contracts.
The image-raster label convention is attached only by the exact
`sceneio.label_map/1` NPZ/Zarr/TIFF declaration (or an explicit TIFF caller
contract), or by an NCore `SEGMENTATION` descriptor whose owned extension
declares that same schema. No adapter infers label meaning from observed ids.

### ASL/EuRoC visual-inertial datasets

The bounded `euroc_dataset` adapter preserves the file-declared sensor graph.
In the ASL schema, `T_BS` maps coordinates from sensor frame `S` into body
frame `B`. SceneIO therefore stores camera rows as `camera_to_reference` and
IMU rows as `sensor_to_reference`, with the shared reference frame named
`rig`; it does not invert either transform during ordinary I/O. Optional
ground truth preserves `p_RS_R` and Hamilton `q_RS` in WXYZ order as a
sensor-to-reference trajectory.

Translations use metres, angular velocity uses radians per second, linear
acceleration uses metres per second squared, and sample instants are exact
signed `int64` nanoseconds. A camera clock offset follows
`reference_time = camera_time + timeshift_cam_imu`. The adapter never aligns,
interpolates, rescales, or relabels clocks implicitly, and its writer rejects
records whose frame, unit, quaternion, epoch, or clock conventions the ASL
directory cannot preserve. PyYAML, the Python CSV parser, SciPy rotations,
Kalibr semantics, and CamTools equations provide independent executable and
reference evidence.

## File-to-record and record-to-file directions

The per-format ledger in `coordinate_conversions_v1.toml` distinguishes the
two I/O directions from the separate public conversion API. Its vocabulary is:

| Direction | Contract values | Meaning |
|---|---|---|
| file to record | `normalize_to_colmap` | a reconstruction adapter converts the file-native pose representation to canonical COLMAP fields |
| file to record | `preserve_fixed`, `preserve_declared`, `preserve_unspecified` | decode retains the format's known, file-authored, or explicitly unknown convention |
| record to file | `encode_from_colmap` | a reconstruction adapter performs the inverse file-native mapping |
| record to file | `require_fixed`, `preserve_declared`, `require_unspecified` | the writer guards the record convention before encoding rather than silently changing it |
| either | `not_applicable` | the payload has no independent coordinate transform, for example index-only matches |
| record to file | `unsupported` | the registry has no writer; currently this is only the read-only RTMV dataset adapter |

All 74 entries name their independent oracle and the executable parity suite
that exercises it. The contract test requires exact registry order, no missing
or duplicate id, agreement with the static coordinate status and direct
conversion policy, agreement with actual writer availability, an existing
test path, and read plus write evidence where the format is writable. The
authoritative format/specification link remains
`FormatCoordinateContract.reference`; the executable oracle is deliberately a
separate implementation, a specification-derived parser, or a pinned upstream
vector. Consequently, the ledger does not overstate RTMV as bidirectional and
does not mislabel reconstruction adapter normalization as direct
`convert_coordinates` support.

The repository-wide enforcement policy lives in
`tests/contracts/io_oracles_v1.toml` and is tested independently of the
coordinate API by `tests/test_io_oracle_contract.py`. It also distinguishes
lossless equality from bounded lossy/quantized comparison and adds the USD
Gaussian schema suite to the USD/USDZ evidence. This separation matters:
ordinary file parity proves the stored representation, while a semantic
normalization claim additionally needs an attribute-level oracle.
The contract names the exact decode and encode test for every row, including
an independent PyYAML interpretation of Kalibr writer output, so a shared test
module cannot satisfy the wrong format accidentally.

For Gaussian data, the attribute-level evidence proves log/linear scale,
logit/linear opacity, WXYZ/XYZW component order, quaternion unit state, the
3DGS real-SH basis/phase/coefficient order, SH memory-layout transposition,
coordinate/scale provenance, and format quantization. The companion
`tests/contracts/gaussian_semantics_v1.toml` freezes the per-carrier mapping and
closed vocabularies; `tests/contracts/gaussian_oracles_v1.toml` pins the
repository revision, license, role, and execution mode of every Gaussian
reference. In particular,
SplatTransform 3.1.6 is executed against all six legacy wire formats on the
Windows, Linux, and macOS splat lanes; gsply 0.4.6 provides a second live
implementation for PLY and SPZ; and GaussianSplats3D supplies pinned KSplat
vectors. The official Niantic SPZ 3.0.0 oracle now executes official-writer to
SceneIO-reader checks for SPZ v2, v3, and v4, and SceneIO-writer to
official-reader checks for v3 and v4, for every SceneIO-supported SH degree.
Its obsolete v1 profile remains excluded from that upstream claim while
SceneIO's existing v1 parity evidence is retained. The focused OpenUSD 26.08
oracle executes both USDA and USDZ Gaussian cross-read directions. gsplat and
Brush are retained only as covariance/SH/rendering
semantic references because they do not implement the entire wire-format
matrix. USD Gaussian orientations are required to be unit quaternions, with a
precision-aware float/half tolerance. SPZ's extension-free wire profile is
tagged as right-handed OpenGL/RUB; generic Gaussian PLY and the other legacy
carriers remain coordinate-unknown because their bytes do not declare a frame.
`convert_gaussian_conventions()` can explicitly normalize quaternion magnitude
and can retarget source precision and rendering hints when preparing a record
for a different writer; it refuses float32-to-float16 retagging because that
would require numeric quantization.
Logit-to-linear conversion follows the exact float32 sigmoid, so sufficiently
large finite logits can saturate to 0 or 1 and cannot then be inverted without
loss. All universal semantic properties are represented, but the record does
not invent values: color space remains `unknown` for carriers without a
normative transfer-function claim, scale remains unqualified without file or
caller evidence, and incompatible/nonlinear semantic retagging is refused.
SPZ extension flags and non-default coordinate profiles remain outside the
qualified profile rather than being silently relabeled.

The post-review local gate collects 4,599 tests and passes 4,583 with 17
documented optional/platform skips. The independently built Niantic source
lane passes 51 official-provider cases with one gsply-v2 writer skip, while the
local OpenUSD lane passes all four USDA/USDZ cross-read cases. These results
qualify the mappings above. The G1 semantic contract adds explicit fields and
refusal behavior without turning an `unknown` carrier property into a canonical
claim.

The broader upstream-source qualification ledger is
`tests/contracts/oracle_sources_v1.toml`. It allows permissive and weak
file-level copyleft sources, including MPL-2.0, BSL-1.0, and TOST-1.0, in
separately installed test or hosted-oracle lanes while keeping the base
runtime NumPy-only. Each row records the pinned revision, license expression,
star-count snapshot, authority, shared-implementation lineage, execution
role, and exact evidence tests. Star count is a project-maturity signal only;
an official format owner or standards body remains the preferred authority,
and correlated forks are counted as one lineage.

## Pixel coordinates, features, matches, and tracks

Pixel coordinates require an origin and a first-pixel-center offset. The offset
is record metadata, not an inferred property of the numeric values.

- SceneIO images and COLMAP features use first pixel center `(0.5, 0.5)`.
- Native HLoc feature files use first pixel center `(0.0, 0.0)`. HLoc shifts
  those keypoints by `+0.5` when importing them into COLMAP.
- `FeatureSet.pixel_center` preserves this distinction. The COLMAP database and
  HLoc writers each reject the other's pixel-center convention rather than
  shifting keypoints.
- Coordinate-mode `PairCorrespondences` use image coordinates. Indexed pairs,
  match graphs, and tracks carry indices and inherit the coordinate convention
  of their endpoint feature/image records; index-only HLoc match storage has no
  independent convention.
- Masks, confidence maps, flow, ray maps, and image-sized dense records expose
  their image convention. Depth and normal records additionally expose their
  depth or camera-frame interpretation when known.

## Explicit conversion

Conversion is opt-in:

```python
canonical_views = sceneio.convert_coordinates(source_views)

canonical_cloud = sceneio.convert_coordinates(
    source_cloud,
    world_transform=source_world_to_target_world,
)
```

`world_transform` maps source-world coordinates to target-world coordinates;
its translation is expressed in meters. For posed views it must be a proper
rigid transform. Point clouds accept an invertible affine transform, except
that scalar widths require a similarity transform because anisotropic scale
cannot be represented by one diameter. Meshes accept an invertible,
orientation-preserving affine transform; reflections require a caller-defined
winding policy and are refused by this API. A target with arbitrary scale
retains the source record's stronger unit scale rather than discarding that
metadata. The qualified direct converters are:

- native `PosedViewSet`: OpenCV/OpenGL axes, WXYZ/XYZW Hamilton quaternions,
  world-to-camera/camera-to-world poses, and unit scale; camera associations
  and intrinsics are retained;
- native `PointCloud`: positions, origin, normals, scalar widths, velocities,
  accelerations, and scale;
- native `GaussianCloud`: means, scale magnitudes, rotations, quaternion order
  and unit state, coordinate frame, and unit scale under an
  orientation-preserving similarity. Directional SH coefficients may pass
  only when the spatial rotation is identity;
- native `Mesh`: positions, normals, local transform, and scale.

OpenCV/OpenGL and ENU/NED have defined direct basis changes. Other frame pairs
require `world_transform`. A posed-view change between named/reference world
frames also requires that explicit map, even when camera axes are otherwise
compatible. Identity conversion returns the same object only when a qualified
record already carries the target semantics. An explicit `source=` refinement
of an unknown record rebuilds and retags that record even when source and target
are equal. An unsupported record never becomes convertible merely because its
source and target convention values compare equal. The optional `source=`
argument may refine unknown or arbitrary record metadata, but it may not
contradict axes, scale, pixel placement, or other fields already declared by
the record. A single point/mesh frame field cannot simultaneously encode known
camera axes and a named ENU/NED world frame, so mixed declarations are refused.

The converter refuses incomplete cases instead of inventing policy. Examples
include unknown frames without a caller transform, non-rigid pose transforms,
mesh reflections without a winding policy, non-default acquisition viewpoints,
opaque LAS waveform sidecars, Gaussian reflections/nonsimilar transforms or
directional-SH rotations, and reconstruction/scene conversions whose semantics
are not fully qualified. `FormatCoordinateContract.conversion`
is `supported` only where the public decoded record is directly convertible;
`requires_context` means the caller needs a format-specific adapter or policy.
`RtmvDataset` is likewise unqualified as a whole; callers may convert its
`views` only while explicitly preserving its path-backed layers and metadata.

## Verification contract

`tests/test_coordinate_systems.py` and the per-codec parity suites enforce:

- exact 74-format manifest coverage and registry order;
- exact 74-format forward/backward directionality and one independent-oracle
  evidence path per format;
- executable cross-repository decode of all six legacy Gaussian formats and
  cross-repository encode of compressed PLY, SOG, and SPZ, comparing decoded
  attributes with quantization and quaternion-sign equivalence;
- agreement between registry capabilities, inspection, and decoded records;
- asymmetric pose conversion against a hand-derived matrix and `pycolmap`;
- the full 64-case product of OpenGL/OpenCV, W2C/C2W, and WXYZ/XYZW against an
  independent matrix oracle;
- ENU/NED, scale, scalar-width, normal, origin, mesh-local-transform, and
  optional-field preservation behavior;
- Gaussian quaternion rotation equivalence, degree-0/1 3DGS SH equations,
  seeded unit directions, scale provenance, similarity conversion, and refusal
  boundaries;
- conversion round trips and explicit refusal cases;
- COLMAP/HLoc pixel-center preservation and writer guards;
- all-format installed-wheel smoke with no coordinate-property exemptions.

The machine contract is versioned. Any semantic change must update the code,
TOML contract, focused parity test, public documentation, and installed-wheel
smoke together.
