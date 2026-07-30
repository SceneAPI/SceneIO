# USD 3D-CV profile implementation plan

Status: U1 implemented and locally verified; U0 provider qualification is next
Review date: 2026-07-30  
Standards baseline: AOUSD Core Specification 1.0.1, supplemental
1.0.1.post0, and OpenUSD 26.08 (`v26.08`, `ee47c679abde`)

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

- [AOUSD Core Specification 1.0.1](https://github.com/aousd/specifications-public/tree/2f9e746c4fbd7f48d6d2c9ac568133fe398bbfc0/core/1.0.1)
- [AOUSD Core 1.0.1 supplemental/compliance materials](https://github.com/aousd/core-spec-supplemental-public/tree/c15ae0cad3ed9e07a25dffd6699627d2c166cab0/releases/1.0.1)
- [OpenUSD 26.08 documentation](https://openusd.org/release/)
- [OpenUSD 26.08 release](https://github.com/PixarAnimationStudios/OpenUSD/releases/tag/v26.08)
- [OpenUSD TOST 1.0 license text](https://github.com/PixarAnimationStudios/OpenUSD/blob/v26.08/LICENSE.txt)
- [Apache License 2.0 text](https://www.apache.org/licenses/LICENSE-2.0)
- [OpenUSD release changelog](https://raw.githubusercontent.com/PixarAnimationStudios/OpenUSD/release/CHANGELOG.md)
- [USDZ file-format specification](https://openusd.org/release/spec_usdz.html)
- [UsdGeomPoints](https://openusd.org/release/api/class_usd_geom_points.html)
- [UsdGeomCamera](https://openusd.org/release/api/class_usd_geom_camera.html)
- [UsdVol ParticleField3DGaussianSplat](https://openusd.org/release/user_guides/schemas/usdVol/ParticleField3DGaussianSplat.html)
- [UsdVol particle-field overview](https://openusd.org/release/user_guides/schemas/usdVol/overview.html)

The AOUSD 1.0.1 specification is the normative core-format and composition
reference. Its 1.0.1.post0 supplemental package is the executable compliance
reference and is Apache-2.0; the specification documents themselves are
CC-BY-ND-4.0 and must be referenced or copied unchanged. An unmodified
OpenUSD 26.08 installation is the implementation oracle when the narrow TOST
policy decision permits it. TinyUSDZ remains the independent permissively
licensed implementation used by the current optional provider. Observed local
provider behavior is recorded in
[`usd_provider_qualification.md`](usd_provider_qualification.md).

## 2026-07-30 review findings

The current standards review changes four planning details:

1. The published AOUSD baseline is Core Specification **1.0.1**, not the
   earlier shorthand “1.0.” The matching supplemental release is
   `1.0.1.post0`. The reviewed source pins are specification commit
   `2f9e746c4fbd`, supplemental peeled release commit `c15ae0cad3ed`
   (annotated tag object `404e2bde49c1`), and OpenUSD tag target
   `ee47c679abde`.
2. OpenUSD **26.08** is the current tagged release. It writes USDA version 1.3
   and USDC crate version 0.15.0. Current-version USDC qualification must use
   those versions; TinyUSDZ's observed crate 0.8 output is historical output,
   not a current writer oracle.
3. `ParticleField3DGaussianSplat` is an official OpenUSD 26.08 schema. Its
   built-in APIs define float and half positions, orientations, linear scales,
   linear opacities, and particle-major RGB spherical-harmonic coefficients.
   Float attributes take precedence when both precisions are present. Accepted
   sorting hints are `zDepth`, `cameraDistance`, and `rayHitDistance`.
4. OpenUSD's TOST 1.0 text is Apache-2.0-derived but is a distinct license.
   The implementation plan may use OpenUSD documentation and fixtures as
   references now; adding `usd-core` as an installed oracle or provider still
   requires the explicit narrow project decision described below.

Repository review also found that U1 is already partly implemented:

- U1a (`bf6f374`) added explicit Gaussian storage conventions and conversion.
- U1b (`cca1479`) added compiled `SceneGraph`, `InstanceSet`, and
  `VolumeAsset` records with owner-retaining views.
- U1c adds the accepted point/mesh fields and exact refusal guards to every
  existing writer that cannot represent them. Its focused record tests,
  affected-codec parity sweep, exact suite contract, compatibility snapshots,
  full local suite, Ruff pass, and 15-format benchmark control are green.

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
metadata. `.usdc` is not a registered extension. TinyUSDZ is locally qualified
only through crate version 10, and the official crate-10 time-sample fixture
exposes timestamps but not values; SceneIO refuses later crate versions before
provider dispatch.

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

**Short answer:** yes, TOST 1.0 is generally similar to the project's
permissive-license family, and specifically is much closer to Apache-2.0 than
to MIT, BSD, or zlib. It is not public domain and it is not literally
Apache-2.0.

TOST 1.0's copyright grant, explicit patent grant, patent-claim termination,
redistribution conditions, NOTICE handling, warranty disclaimer, and liability
terms are the Apache-2.0 text. OpenUSD's own license file says that section 6
is the difference:

- Apache-2.0 permits reasonable and customary trademark use when describing
  the work's origin.
- TOST does not grant that permission; trademark use is limited to retaining
  required notices and reproducing NOTICE content.

TOST is therefore non-copyleft and does not require SceneIO source disclosure.
Compared with MIT/BSD/zlib it has the extra Apache-style patent grant,
patent-claim termination, modified-file notice, and NOTICE obligations.
Compared with Apache-2.0 it grants less trademark permission. The equivalent
older text is catalogued by SPDX as the `Pixar` license and is not marked
OSI-approved; as of SPDX License List 3.28.0, TOST does not have a standard
identifier, and current `usd-core` metadata uses `LicenseRef-TOST-1.0`.

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

Recommended project decision: approve a narrow exception for unmodified
official OpenUSD packages under TOST 1.0, only as an optional development/test
oracle at first. Do not bundle or link OpenUSD into the SceneIO wheel. Promote
it to an optional runtime provider only if the provider inventory, platform
availability, and performance comparison justify doing so. This keeps the
NumPy-only base runtime and manylinux2014 wheel contract intact.

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
When both half and float attributes are authored, the float attribute wins as
specified by OpenUSD. The profile accepts projection hints `perspective` and
`tangential`, and sorting hints `zDepth`, `cameraDistance`, and
`rayHitDistance`. SceneIO is deliberately stricter than the renderer fallback:
per-particle arrays must have exact counts instead of being truncated or
discarded.

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

The U1b implementation uses stable numeric storage codes while exposing their
string names: payload kinds from `none` through `instances` map to `0..6`;
visibility `inherited/visible/invisible` maps to `0..2`; and purpose
`default/render/proxy/guide` maps to `0..3`. A
payload-free node stores `UINT64_MAX` as its payload index. Child CSR is the
source of truth and the validated parent array is stored redundantly for
constant-time traversal. Payload accessors retain the parent `SceneGraph`;
all node-domain numeric arrays are read-only owner-retaining views.

### Additive payload changes

`PointCloud` now carries optional float colors/opacity, widths (diameters),
signed 64-bit ids, velocities, accelerations, and color-space metadata.
Existing uint8/uint16 color members remain compatible.

`Mesh` now carries optional float vertex/corner display colors and opacities
plus color-space metadata, orientation, and tri-state double-sidedness.
Existing RGBA8 members remain compatible. Internal orientation tokens
`right_handed|left_handed` map to USD's `rightHanded|leftHanded` tokens in the
future U3 codec mapping.

`GaussianCloud` needs the convention and source-precision fields described
above. All current six splat families retain their existing defaults and
bit-exact outputs.

`InstanceSet` is a new compact record for prototype node indices, ids,
translations, orientations, scales, invisible ids/mask, and supported numeric
per-instance attributes.

The U1b record stores `prototype_nodes` in the `SceneGraph` node domain and
`prototype_indices` in that table's row domain. IDs are unique signed
64-bit values; omitted IDs become `0..N-1`. Invisible IDs are retained in
authored order and also materialized as a canonical `uint8` mask. Optional
numeric attributes use a `TensorDict` whose tensors must have `N` leading
rows. The `wxyz|xyzw` quaternion convention is explicit, and omitted
orientations/scales receive convention-correct identity/one defaults.

## Commit-sized implementation checklist

Every unit follows: implement, focused differential tests, allocation/lifetime
checks, benchmark delta, three-lens review, full tests/Ruff, then commit with
the required co-author trailer.

### Lean closure sequence

The work is finite and ordered. Do not start a later unit while an earlier unit
has uncommitted or failing changes.

| Unit | Deliverable | Required evidence | Closure rule |
|---|---|---|---|
| 1 | Finish U1c point/mesh fields and writer refusals | focused record tests, every affected codec suite, unchanged default bytes, full suite, Ruff, record benchmark | one green commit; no USD mapping yet |
| 2 | Finish U0 provider qualification | pinned AOUSD 1.0.1 inputs, OpenUSD 26.08 fixtures, provider matrix, license inventory, read/write/performance comparison | select one provider per operation; unsupported USDC write remains unavailable |
| 3 | U2 stage API and hierarchy | `read_scene`/`write_scene`, representation routing, metadata, selection, inspection | hierarchy-only stages cross-read and old mesh API remains exact |
| 4 | U3 mesh/point/material payloads | mixed fixtures, texture packages, selected-prim and large-payload measurements | semantic equality through independent readers |
| 5 | U4 official Gaussian schema | official 26.08 fixtures, raw-bit convention tests, generated 1k/100k/1M measurements | exact schema mapping; no implicit activations |
| 6 | U5 camera/volume/semantics/instances | axis/pose optics cases, OpenVDB asset cases, inherited-label and prototype cases | one mixed 3D-CV stage round-trips |
| 7 | U6 selected-time/container/composition subset | AOUSD compliance cases, current/historical crate reads, USDZ layout checks, selected-time comparison | evaluated snapshot equals the reference; authoring stacks stay out of scope |
| 8 | U7 release closure | full tests, review lenses, benchmark ledger, docs/contracts, sdist/wheel smoke, hosted matrix with user approval | capability claim is exactly `sceneio.usd.3dcv/1` |

Stop rules prevent the project from becoming open-ended:

- if no qualified cross-platform USDC writer is available, ship USDC read-only;
- if a composition arc is outside the AOUSD cases implemented in U6, report it
  through inspection and refuse the rich read;
- if a schema cannot map exactly to a SceneIO record, keep it outside the
  profile instead of adding an opaque preservation system;
- do not add rendering, full layer editing, or unrelated USD schema domains to
  close this profile.

### U0 — freeze profile and qualify providers

- [x] Compare the TOST 1.0 and Apache-2.0 texts and record the exact project
      consequence.
- [ ] Obtain the explicit narrow TOST policy decision; do not infer approval
      from license similarity.
- [x] Pin AOUSD Core 1.0.1 (`2f9e746c4fbd`), supplemental 1.0.1.post0
      (`c15ae0cad3ed`, tag object `404e2bde49c1`), and OpenUSD 26.08
      (`ee47c679abde`) source baselines.
- [x] Select the exact compliance/schema fixtures to commit, recording the
      source path, source commit, and license of every fixture.
- [x] Build a generated local provider matrix covering USDA, historical
      USDC crates, USD forwarding, USDZ, unknown typed prims, time samples,
      sublayers, references, payloads, variants, and asset resolution.
- [x] Record TinyUSDZ's actual supported composition subset rather than relying
      on upstream feature labels.
- [ ] Compare TinyUSDZ and, if approved, `usd-core` for correctness,
      throughput, peak RSS, package availability, and supported platforms.
- [x] Decide the current USDC writer:
      use TinyUSDZ only if OpenUSD 26.08 cross-read and AOUSD format checks pass;
      otherwise use an approved optional OpenUSD provider or leave USDC
      writing unavailable with a precise capability flag. It remains
      unavailable.
- [x] Add the selected dependency/fixture licenses and notices to `LICENSES/`.

Exit: a checked-in qualification report selects a provider per operation and
no public capability is overstated.

### U1 — additive records and compatibility

- [x] Add `SceneGraph`, `InstanceSet`, and `VolumeAsset` C++ records and
      owner-retaining nanobind views.
- [x] Extend `PointCloud` and `Mesh` additively.
- [x] Extend `GaussianCloud` additively with explicit convention and source
      precision fields.
- [x] Keep old factory calls and property defaults byte-for-byte compatible.
- [x] Make every existing point, mesh, and splat writer guard new fields it
      cannot represent.
- [x] Add explicit Gaussian convention conversion outside codec writers.
- [x] Add construction, validation, zero-copy view, owner-lifetime, pickle
      policy, and invalid-offset/index tests for the new records.
- [x] Re-run every existing mesh, point, splat, calibration, and reconstruction
      parity suite.

Exit: the new records are public and stable; all existing codec outputs remain
unchanged.

Local U1c evidence: 6 focused payload tests pass; all 675 affected
point/mesh/USD/API tests pass; the exact 4,106-node collection, compatibility,
and performance-status contracts pass; and the complete local MSVC run passes
4,101 tests with five documented optional skips. The 15-format benchmark
control is recorded in `bench/BASELINE.md`. The resource/lifetime review
removed native records from module-level parametrization, the
format/convention review made widths-as-diameter and orientation mapping
explicit, and the test-soundness review exercises every new field
independently plus destination preservation.

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

### Per-unit local gate

Run from the repository root with the project interpreter:

```powershell
uv pip install -e ".[dev,test]"
.venv\Scripts\python.exe -m pytest -q <focused tests>
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check
git diff --check
```

For optional-provider units, install the selected extra in the same editable
environment and run the provider's direct comparison suite. C++ changes are
not tested until the editable rebuild completes. The focused set must include
the changed record tests, every affected codec parity suite, API/registry
contracts, destination-preservation cases, and lifetime/allocation cases.

The benchmark command is scoped to the changed family first, then the static
USD/USDZ control is rerun. A unit records the command, fixture scale, run
count, median wall time, throughput, peak RSS, Python allocation peak, and
output size in `bench/BASELINE.md`. A noisy result is rerun; a real regression
must be explained or corrected before commit.

The three required review lenses are:

1. **resource and lifetime:** owners, buffer/view lifetime, provider release,
   temporary files, package assets, and write completion;
2. **format and convention correctness:** axes, units, transforms, domains,
   quaternion/SH layout, precision, stage evaluation, and unsupported-data
   refusals;
3. **test soundness:** independent cross-read/cross-write evidence, exact
   assertions where required, malformed/edge cases, and proof that tests would
   fail if the optimized or selected path were bypassed.

Only a green unit is committed. Each commit includes the required co-author
trailer. Pushing and the hosted package matrix remain user-gated.

### Ground truth

1. AOUSD Core 1.0.1 plus supplemental 1.0.1.post0 compliance cases for
   file/container behavior and the composition subset.
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
