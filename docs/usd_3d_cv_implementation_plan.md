# USD 3D-CV profile implementation plan

Status: reviewed plan, implementation not started  
Review date: 2026-07-30  
Standards baseline: AOUSD Core Specification 1.0 and OpenUSD 26.08

## Decision summary

SceneIO will target a named, bounded **USD 3D-CV profile**, not claim complete
USD implementation. The profile is complete when SceneIO can exchange static
or explicitly sampled 3D-CV stages containing meshes, point clouds, Gaussian
splats, cameras, bounded materials, semantic labels, and OpenVDB references in
USDA, USDC, USD, and USDZ.

The closure boundary is intentionally finite:

- reads return one evaluated snapshot at an explicitly selected time;
- writes produce a self-contained layer or package rather than reconstructing
  an input layer stack;
- the accepted material vocabulary is a documented `UsdPreviewSurface`
  subset;
- unsupported authored data is reported, not silently discarded;
- arbitrary shader graphs, lights, physics, skeletons, curves, NURBS,
  subdivision evaluation, authoring-layer preservation, arbitrary custom
  schemas, and non-3D-CV media are outside the profile.

The existing static `MeshScene` API remains compatible. Rich USD scenes use a
new `SceneGraph` API; a mesh-only projection continues to support current
`sceneio.read()` callers.

## Authoritative references

- [AOUSD Core Specification 1.0](https://aousd.org/usd-core-specification/)
- [OpenUSD 26.08 documentation](https://openusd.org/release/)
- [OpenUSD release changelog](https://raw.githubusercontent.com/PixarAnimationStudios/OpenUSD/release/CHANGELOG.md)
- [USDZ file-format specification](https://openusd.org/release/spec_usdz.html)
- [UsdGeomPoints](https://openusd.org/release/api/class_usd_geom_points.html)
- [UsdGeomCamera](https://openusd.org/release/api/class_usd_geom_camera.html)
- [UsdVol ParticleField3DGaussianSplat](https://openusd.org/release/user_guides/schemas/usdVol/ParticleField3DGaussianSplat.html)
- [UsdVol particle-field overview](https://openusd.org/release/user_guides/schemas/usdVol/overview.html)

The AOUSD compliance samples and an unmodified OpenUSD 26.08 installation are
the normative core-format and composition references. TinyUSDZ remains the
independent permissively licensed implementation used by the current optional
provider. Observed local provider behavior is recorded in
[`usd_provider_qualification.md`](usd_provider_qualification.md).

## Current implementation and measured review

The current `sceneio[usd]` profile uses TinyUSDZ 0.9.4 for loading and a
repository-owned deterministic USDA/USDZ writer. It supports:

- `.usd` and `.usda` ASCII layers plus single-root-layer `.usdz`;
- `Xform`, `Scope`, and polygonal `Mesh` prims;
- positions, face topology, vertex/corner normals and UVs;
- hierarchy, static matrix transforms, and one scene;
- metadata-only inspection, transactional path writes, and lifetime-safe
  owned results.

It currently requires Y-up, one meter per unit, and refuses colors, materials,
cameras, time samples, composition arcs, variants, instancing, and custom
metadata. `.usdc` is not a registered extension even though TinyUSDZ can read
binary layers.

The review command

```powershell
.venv\Scripts\python.exe -m pytest -q tests\codecs\test_usd.py tests\test_io_capabilities.py tests\test_io_api.py
```

passes 56 tests locally.

Two provider probes were also run:

1. TinyUSDZ 0.9.4 parses the OpenUSD 26.08
   `ParticleField3DGaussianSplat` type and all required attributes as generic
   typed USD data.
2. Its NumPy view exposes `quatf[]` as XYZW even though USDA writes the
   quaternion as real/i/j/k. SceneIO must reorder this explicitly.
3. `Stage.save()` writes `.usdc`, but the observed crate is version 0.8 and
   TinyUSDZ still describes USDC writing as experimental. USDC writing is
   therefore a qualification item, not a current capability claim.

No current capability row changes merely because the provider can parse or
emit a file in a probe.

## License decision: TOST 1.0

TOST 1.0 is operationally closest to Apache-2.0. Its copyright grant, explicit
patent grant, patent-claim termination, redistribution conditions, NOTICE
handling, warranty disclaimer, and liability terms are the Apache-2.0 text.
The material difference is section 6:

- Apache-2.0 permits reasonable and customary trademark use when describing
  the work's origin.
- TOST does not grant that permission; trademark use is limited to retaining
  required notices and reproducing NOTICE content.

TOST is therefore non-copyleft and does not require SceneIO source disclosure.
It is not, however, literally MIT, BSD, zlib, Apache-2.0, or public domain.
The equivalent older text is catalogued by SPDX as the `Pixar` license and is
not marked OSI-approved; current `usd-core` metadata uses
`LicenseRef-TOST-1.0`.

Project consequence:

- the current allow-list does **not** include TOST merely because its terms
  are close to Apache-2.0;
- using OpenUSD as a linked, bundled, optional, or test dependency requires an
  explicit narrow policy decision;
- if approved, the policy entry should be
  “TOST-1.0/Pixar, only for official OpenUSD,” not a general allowance for
  arbitrary `LicenseRef-*` packages;
- the exact OpenUSD wheel contents and their third-party notices still need a
  separate inventory. Approval of TOST alone does not approve every component
  that might be present in a distribution.

This plan does not change the allow-list. Until that decision is made,
OpenUSD is a standards reference only and TinyUSDZ remains the executable
oracle/provider.

## Target profile contract

### File and container behavior

| Surface | Required behavior |
|---|---|
| `.usda` | read and deterministic repository-owned write |
| `.usdc` | read; write only after current-version oracle qualification |
| `.usd` | detect forwarded USDA/USDC representation; preserve current ASCII write default for compatibility |
| `.usdz` | read/write uncompressed, unencrypted, 64-byte-aligned packages with a valid first USD layer |
| assets | resolve and package relative USD layers, PNG/JPEG/EXR textures, and OpenVDB assets |
| inspection | report actual representation, version, prim counts/types, time range, dependencies, variants, and unsupported profile features without decoding bulk arrays |

The logical registry ids remain `usd` and `usdz`. `.usdc` joins the `usd`
extension set, and inspection records `representation="usda"|"usdc"`.
This avoids breaking code that already treats `.usd` and `.usda` as one USD
codec family.

### Stage and node behavior

The profile supports:

- `defaultPrim`;
- Y-up and Z-up;
- finite positive `metersPerUnit`;
- ordered xform operations, reset stacks, hierarchy, visibility, purpose, and
  extent;
- one selected time code plus stage time metadata;
- known variant selections;
- semantic labels through `UsdSemanticsLabelsAPI`;
- explicit dependency reporting.

SceneIO records source units and axes. Codec writers do not silently normalize
coordinates or units.

### Typed payloads

| USD schema | SceneIO payload | Accepted profile |
|---|---|---|
| `UsdGeomMesh` | `Mesh` | polygon mesh; known primvar domains; no subdivision evaluation |
| `UsdGeomPoints` | `PointCloud` | positions, normals, colors/opacity, widths, ids, velocities, accelerations |
| `UsdVolParticleField3DGaussianSplat` | `GaussianCloud` | degree 0-3 SH, float16/float32 source precision, official hints |
| `UsdGeomCamera` + `UsdRenderProduct` | `CameraRig` rows | pinhole and orthographic, resolution, physical filmback/focal metadata, no unrepresented distortion |
| `UsdVolVolume` + `UsdVolOpenVDBAsset` | volume asset payload | named OpenVDB grid reference, transform, purpose, dependency |
| `UsdGeomPointInstancer` | `InstanceSet` | prototype references plus ids, transforms, masks, and known per-instance primvars |

### Materials

The accepted material network is deliberately bounded:

- `UsdShadeMaterial` and `MaterialBindingAPI`;
- `GeomSubset` face material assignments;
- `UsdPreviewSurface` base color, emissive, metallic, roughness, opacity,
  opacity threshold, and normal;
- `UsdUVTexture` with `st` primvars and the wrap/filter vocabulary already
  represented by `MaterialSet`;
- PNG, JPEG, and EXR texture assets.

Other shader nodes, MaterialX networks, UDIM sets, procedural textures, and
unrepresented color-management operations are reported as unsupported.

### Gaussian conventions

USD stores linear scales and linear opacities. SceneIO currently fixes log
scales and logit opacities. The record must become convention-bearing:

- `scale_space = "linear" | "log"`;
- `opacity_space = "linear" | "logit"`;
- `sh_layout = "channel_grouped" | "coefficient_rgb"`;
- `source_precision = "float16" | "float32"`;
- quaternion order remains explicit.

Existing constructors default to the current log/logit/channel-grouped/WXYZ
contract. Existing splat writers must reject incompatible conventions.
`sceneio.convert_gaussian_conventions()` is an explicit, separately tested
conversion utility; a USD writer never activates values implicitly.

USD SH coefficients are particle-major RGB coefficient rows. Reordering to or
from SceneIO's split DC/channel-grouped storage must preserve every float bit.

### Cameras

USD cameras always use a Y-up local camera frame looking down negative Z with
positive X to the right. Camera mapping must explicitly handle:

- OpenCV versus OpenGL axes;
- camera-to-world versus world-to-camera transforms;
- focal length, horizontal/vertical aperture, aperture offsets, clipping,
  projection, focus, f-stop, exposure, and shutter metadata;
- pixel resolution supplied by an associated `UsdRenderProduct`.

Portable `UsdGeomCamera` has no general OpenCV distortion model. Nonzero
radial, tangential, fisheye, or thin-prism distortion is refused unless a
future separately documented schema is selected.

## Public API

Additive API:

```python
scene = sceneio.read_scene(
    path,
    time=None,
    prims=None,
    purposes=("default", "render", "proxy"),
    variants=None,
    load_payloads=True,
)

sceneio.write_scene(
    scene,
    path,
    encoding=None,          # extension-selected usda/usdc/usdz
    package_assets=True,
    profile="usd-3dcv-1",
)
```

Compatibility rules:

- `sceneio.read()` continues returning `MeshScene` for an accepted mesh-only
  stage.
- `sceneio.read()` refuses a stage containing supported non-mesh 3D-CV payloads
  and directs callers to `read_scene()`; it never drops those prims.
- `read_scene()` always returns `SceneGraph`, including for mesh-only stages.
- `write()` retains its current deterministic `.usd` ASCII behavior.
- `write_scene()` selects `.usda`, `.usdc`, or `.usdz` from the extension;
  `.usd` remains ASCII unless `encoding="usdc"` is explicitly requested.
- `inspect()` remains common to both paths and reports whether the mesh-only
  projection is available.

## Record design

### `SceneGraph`

Add a compiled, zero-copy-friendly record containing:

- stage axes, scale, time metadata, default prim, source representation, and
  selected time;
- node names, parent/child CSR, local transforms, visibility, purpose, and
  payload kind/index;
- typed payload tables for meshes, point clouds, Gaussian clouds, camera rows,
  volumes, and instances;
- one shared `MaterialSet`;
- external asset URI/type tables;
- semantic taxonomy/label tables.

Known values receive closed vocabularies. Unknown authored properties are
listed by inspection and cause a read refusal when they affect a supported
payload. SceneIO does not preserve arbitrary USD specs as opaque dictionaries.

### Additive payload changes

`PointCloud` needs optional float colors/opacity, widths, signed 64-bit ids,
velocities, accelerations, and color-space metadata. Existing uint8/uint16
color members remain compatible.

`Mesh` needs optional float vertex/corner display colors plus color-space
metadata. Existing RGBA8 members remain compatible.

`GaussianCloud` needs the convention and source-precision fields described
above. All current six splat families retain their existing defaults and
bit-exact outputs.

`InstanceSet` is a new compact record for prototype node indices, ids,
translations, orientations, scales, inactive ids/mask, and supported numeric
per-instance attributes.

## Commit-sized implementation checklist

Every unit follows: implement, focused differential tests, allocation/lifetime
checks, benchmark delta, three-lens review, full tests/Ruff, then commit with
the required co-author trailer.

### U0 — freeze profile and qualify providers

- [ ] Obtain the explicit TOST policy decision; do not infer it.
- [ ] Pin AOUSD Core 1.0 compliance inputs and OpenUSD 26.08 schema fixtures,
      recording the license of every committed fixture.
- [ ] Build a generated provider matrix covering USDA, current and historical
      USDC crates, USD forwarding, USDZ, unknown typed prims, time samples,
      sublayers, references, payloads, variants, and asset resolution.
- [ ] Record TinyUSDZ's actual supported composition subset rather than relying
      on upstream feature labels.
- [ ] Compare TinyUSDZ and, if approved, `usd-core` for correctness,
      throughput, peak RSS, package availability, and supported platforms.
- [ ] Decide the USDC writer:
      use TinyUSDZ only if OpenUSD 26.08 cross-read and AOUSD format checks pass;
      otherwise use an approved optional OpenUSD provider or leave USDC
      writing unavailable with a precise capability flag.
- [ ] Add the selected dependency/fixture licenses and notices to `LICENSES/`.

Exit: a checked-in qualification report selects a provider per operation and
no public capability is overstated.

### U1 — additive records and compatibility

- [ ] Add `SceneGraph` and `InstanceSet` C++ records and nanobind views.
- [ ] Extend `PointCloud`, `Mesh`, and `GaussianCloud` additively.
- [ ] Keep old factory calls and property defaults byte-for-byte compatible.
- [ ] Make every existing point, mesh, and splat writer guard new fields it
      cannot represent.
- [ ] Add explicit Gaussian convention conversion outside codec writers.
- [ ] Add construction, validation, zero-copy view, owner-lifetime, pickle
      policy, and invalid-offset/index tests.
- [ ] Re-run every existing mesh, point, splat, calibration, and reconstruction
      parity suite.

Exit: the new records are public and stable; all existing codec outputs remain
unchanged.

### U2 — USD family API and stage skeleton

- [ ] Split `_usd.py` into bounded modules:
      `_usd/provider.py`, `_usd/stage.py`, `_usd/geometry.py`,
      `_usd/materials.py`, `_usd/gaussians.py`, `_usd/cameras.py`, and
      `_usd/package.py`.
- [ ] Add `.usdc` routing under the existing `usd` codec id.
- [ ] Implement `read_scene()` and `write_scene()` without changing the old
      mesh-only return contract.
- [ ] Map `defaultPrim`, Y/Z up-axis, units, ordered/reset transforms,
      visibility, purpose, extent, and one selected time.
- [ ] Extend inspection with representation/version, typed prim counts,
      time range, dependencies, variants, and unsupported features.
- [ ] Add path/prim selection that avoids constructing unselected payload
      records.
- [ ] Preserve destinations on every validation/provider/write failure.

Exit: an empty/hierarchy-only stage round-trips and existing static mesh USD
tests remain byte exact.

### U3 — meshes, points, materials, and texture assets

- [ ] Move current mesh mapping onto `SceneGraph`.
- [ ] Add all accepted mesh primvar domains, float display colors, orientation,
      double-sided state, and material subsets.
- [ ] Add `UsdGeomPoints` fields with exact count/interpolation guards.
- [ ] Implement the bounded `UsdPreviewSurface` graph and `MaterialSet`
      mapping.
- [ ] Resolve/package PNG, JPEG, and EXR textures with collision-free relative
      names; reject escaping or missing dependencies.
- [ ] Cross-read provider-authored and SceneIO-authored fixtures with both
      TinyUSDZ and the approved OpenUSD reference.
- [ ] Add large mesh and point-cloud path benchmarks and selected-prim reads.

Exit: mixed mesh/point scenes and their accepted materials are semantically
identical through both directions.

### U4 — official Gaussian splats

- [ ] Read/write `ParticleField3DGaussianSplat`, required built-in APIs, and
      official attribute names.
- [ ] Support degree 0-3 SH, float16/float32 source precision, projection hint,
      sorting hint, extent, visibility, purpose, and transforms.
- [ ] Pin the TinyUSDZ XYZW provider view to SceneIO WXYZ mapping.
- [ ] Prove coefficient reordering by raw float-bit comparison.
- [ ] Refuse count mismatches, unsupported degrees/dtypes, non-finite values,
      non-positive linear scales, and opacity outside `[0, 1]`.
- [ ] Test explicit log/logit conversion separately from USD I/O.
- [ ] Add generated 1k, 100k, and 1M Gaussian benchmarks for USDA, USDC, and
      USDZ; do not commit the large artifacts.
- [ ] Add prim-selected/row-range reads where the chosen provider can avoid
      full payload materialization.

Exit: OpenUSD-authored Gaussian stages read correctly, SceneIO output passes
the independent schema checks, and all legacy splat codecs remain unchanged.

### U5 — cameras, volumes, semantics, and instances

- [ ] Map supported `UsdGeomCamera` optics and transforms to `CameraRig`.
- [ ] Pair cameras with `UsdRenderProduct` resolution and refuse ambiguous
      pixel-intrinsic reconstruction.
- [ ] Add explicit OpenCV/OpenGL and pose-direction tests.
- [ ] Map `UsdVolVolume`/`UsdVolOpenVDBAsset` references to the existing
      bounded OpenVDB profile.
- [ ] Map inherited semantic labels by taxonomy without treating them as image
      masks.
- [ ] Map `UsdGeomPointInstancer` to `InstanceSet`; retain prototype identity
      and per-instance ordering.
- [ ] Test missing assets, shared assets, instance prototypes, inactive ids,
      and camera stages with and without render products.

Exit: the complete set of accepted 3D-CV payload kinds round-trips in one mixed
stage.

### U6 — containers, evaluated composition, and selected time

- [ ] Validate current OpenUSD 26.08 USDC read/write plus the historical crate
      versions selected in U0.
- [ ] Package multiple layers and assets under USDZ rules: stored entries,
      first/default layer, 64-byte data alignment, relative paths, no
      encryption, and no unsupported media.
- [ ] Support evaluated reads for the U0-qualified subset of sublayers,
      references, payloads, variants, inherits, and specializes.
- [ ] Require explicit variant choices when multiple results are plausible.
- [ ] Read default or explicitly selected time samples for transforms, mesh
      points, point clouds, Gaussian attributes, cameras, and asset paths.
- [ ] Write a flattened, self-contained selected snapshot only.
- [ ] Report composition dependencies and unresolved arcs in `inspect()`.

Exit: supported composed inputs produce the same evaluated `SceneGraph` as the
approved OpenUSD reference at the selected time. Layer-stack authoring remains
out of scope.

### U7 — qualification and documentation closure

- [ ] Run the complete suite and Ruff with the required interpreter.
- [ ] Run compiler-instrumented memory/undefined-behavior checks.
- [ ] Run generated malformed/truncated/provider-differential cases.
- [ ] Run the three review lenses:
      resource/lifetime, format/convention correctness, and test soundness.
- [ ] Record benchmark deltas in `bench/BASELINE.md`.
- [ ] Update `format_coverage.md`, `coverage_roadmap.md`,
      `io_optimization_plan.md`, public API docs, capability snapshots, wheel
      smoke, and `LICENSES/README.md`.
- [ ] Build the sdist and installed-wheel smoke with NumPy only, TinyUSDZ, and
      each approved optional provider configuration.
- [ ] Prepare the nonpublishing Windows/Linux/macOS package matrix.
- [ ] Ask the user before pushing or triggering the hosted cross-platform run.

Exit: the docs claim exactly `sceneio.usd.3dcv/1`; no document says “full USD.”

## Verification matrix

### Ground truth

1. AOUSD Core 1.0 compliance samples for file/container behavior and the
   composition subset.
2. OpenUSD 26.08 `usdchecker`, `usdcat`, and Python schema APIs, if the narrow
   TOST use is approved.
3. TinyUSDZ as an independent cross-reader/cross-writer.
4. SceneIO's existing Mesh/PointCloud/GaussianCloud/CameraRig codec oracles for
   in-memory payload truth.

The same fixture must be exercised in both directions where the provider can
write. A self-round-trip alone is never sufficient.

### Required test groups

- representation detection: USDA/USDC forwarded through `.usd`, explicit
  `.usda`/`.usdc`, and USDZ;
- exact stage metadata and transform evaluation;
- mixed typed scene topology and shared payload identity;
- all mesh primvar domains and material subset partitioning;
- point optional-field presence, interpolation, ids, and widths-as-diameter;
- Gaussian convention, quaternion, SH ordering, precision, and count tests;
- camera axes, pose direction, filmback/focal units, projection, and
  resolution;
- package alignment, first layer, asset paths, duplicate names, and
  dependencies;
- selected time, variant, prim, and payload behavior;
- empty, truncated, internally inconsistent, and unsupported-feature inputs;
- records and array views remaining valid after provider objects and source
  files are released;
- destination preservation when a write cannot complete.

### Performance and allocation

Extend the benchmark harness with:

- static mesh, point, Gaussian, camera, mixed scene, and packaged-texture
  builders;
- small functional, medium comparative, and generated large stress sizes;
- warm and cold path reads;
- USDA versus USDC versus USDZ;
- full scene versus inspect versus selected prim;
- TinyUSDZ versus approved OpenUSD reference rows.

Record wall time, throughput, peak RSS, Python allocation peak, output size,
and provider startup. Optimization changes require a measured improvement on
their target case and no material regression elsewhere; there is no arbitrary
numeric SLA.

High-volume serialization must avoid Python scalar loops. Prefer a qualified
upstream binary writer for USDC and a repository-owned native chunked
formatter for large USDA numeric arrays. USDZ creation copies assets in chunks
and never builds the complete package as Python `bytes`.

## Cross-platform validation

Local development remains Windows/MSVC with `.venv/Scripts/python.exe`.
Any C++ change requires an editable rebuild before tests.

The required package matrix is:

- manylinux2014, GCC 10, CPython 3.12 abi3 SceneIO wheel;
- macOS AppleClang, CPython 3.12 abi3 SceneIO wheel;
- Windows MSVC, CPython 3.12 abi3 SceneIO wheel.

TinyUSDZ must support the complete base profile on all three. The official
`usd-core` wheel currently has its own CPython/platform tags and a newer
manylinux floor, so it cannot become a requirement of the SceneIO
manylinux2014 wheel. If approved, it is a separately installed optional
reference/composition provider and is validated in a compatible job.

The hosted package workflow remains user-triggered. PyPI publication and
trusted-publisher configuration remain separate user-gated actions.

## Fixed exclusions

The following do not reopen this plan:

- FFmpeg or encoded video/audio;
- AVIF, JPEG-XL, or Draco assets;
- arbitrary MaterialX or shader networks;
- lights, physics, behavior, UI, or application schemas;
- skeletons, blend shapes, hair, curves, NURBS, and subdivision evaluation;
- layer editing, edit-target preservation, or byte-identical reconstruction
  of an input layer stack;
- arbitrary custom schema preservation;
- rendering or Hydra integration.

Future work needs a separate request and profile revision.
