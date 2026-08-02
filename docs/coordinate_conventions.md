# Coordinate conventions

SceneIO uses the COLMAP camera convention as its canonical conversion target.
This is a default for explicit conversion and for canonical reconstruction
records; it is not a claim that every file on disk uses COLMAP coordinates.
Readers expose the convention they actually return, and writers reject a
record when the destination format cannot represent that convention.

The machine-checked inventory is
[`tests/contracts/coordinate_systems_v1.toml`](../tests/contracts/coordinate_systems_v1.toml).
It covers all 73 built-in format ids in registry order. Adding a built-in codec
without classifying its coordinate behavior fails the contract tests.

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
its translation is expressed in meters. A target with arbitrary scale retains
the source record's stronger unit scale rather than discarding that metadata.
The qualified direct converters are:

- native `PosedViewSet`: OpenCV/OpenGL axes, WXYZ/XYZW Hamilton quaternions,
  world-to-camera/camera-to-world poses, and unit scale; camera associations
  and intrinsics are retained;
- native `PointCloud`: positions, origin, normals, velocities, accelerations,
  and scale;
- native `Mesh`: positions, normals, local transform, and scale.

The converter refuses incomplete cases instead of inventing policy. Examples
include unknown frames without a caller transform, non-rigid pose transforms,
mesh reflections without a winding policy, non-default acquisition viewpoints,
opaque LAS waveform sidecars, and Gaussian/reconstruction/scene conversions
whose semantics are not fully qualified. `FormatCoordinateContract.conversion`
is `supported` only where the public decoded record is directly convertible;
`requires_context` means the caller needs a format-specific adapter or policy.

## Verification contract

`tests/test_coordinate_systems.py` and the per-codec parity suites enforce:

- exact 73-format manifest coverage and registry order;
- agreement between registry capabilities, inspection, and decoded records;
- asymmetric pose conversion against a hand-derived matrix and `pycolmap`;
- OpenGL/OpenCV, W2C/C2W, WXYZ/XYZW, scale, normal, and origin behavior;
- conversion round trips and explicit refusal cases;
- COLMAP/HLoc pixel-center preservation and writer guards;
- all-format installed-wheel smoke with no coordinate-property exemptions.

The machine contract is versioned. Any semantic change must update the code,
TOML contract, focused parity test, public documentation, and installed-wheel
smoke together.
