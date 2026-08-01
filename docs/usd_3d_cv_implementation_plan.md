# USD 3D-CV profile implementation plan

Status: U0-U5 are committed through C5 (`6eeae8e`). C6 closes through Exit B
under the current permissive-license allow-list: OpenUSD is not installed,
invoked, copied, or bundled; current USDC, evaluated composition, and animated
selected-time evaluation are explicit unavailable provider flags. The direct
static profile detects and refuses sublayers, references, payloads, variants,
inherits, and specializes before projecting a raw stage. C7 local release
qualification is complete: the exact 4,307-node local gate passes 4,301 with
six documented skips; Ruff, focused docs/contracts, the C6 paired-parent
benchmark, source-archive closure, and installed NumPy-only/TinyUSDZ wheel
smokes are green. The prepared three-platform workflow repeats the TinyUSDZ
profile smoke with pinned binary packages. Compiler-instrumented and hosted
Linux/macOS/Windows execution, pushing, and publication remain user-gated.
Review date: 2026-08-01
Standards baseline: AOUSD Core Specification 1.0.1, supplemental
1.0.1.post0, and OpenUSD 26.08 (`v26.08`, `ee47c679abde`)

## Decision summary

SceneIO will target a named, bounded **USD 3D-CV profile**, not claim complete
USD implementation. The required profile is complete when SceneIO can
exchange directly authored static 3D-CV stages containing meshes,
point clouds, Gaussian splats, cameras, bounded materials, semantic labels,
instances, and OpenVDB references in USDA and USD. USDA/USDZ cover the other
payloads, but standards-conforming USDZ output refuses OpenVDB because it is
not an allowed package member type. Historical USDC input is bounded through
crate 10. Current USDC and composed or time-sampled inputs are explicitly
unavailable in profile version 1.

The closure boundary is intentionally finite:

- reads return one directly authored static snapshot; a finite `time=` value
  may annotate a static snapshot but does not evaluate animated samples;
- writes produce a self-contained layer or package rather than reconstructing
  an input layer stack;
- the accepted material vocabulary is a documented `UsdPreviewSurface`
  subset;
- unsupported authored data is reported, not silently discarded;
- arbitrary shader graphs, lights, physics, skeletons, curves, NURBS,
  subdivision evaluation, authoring-layer preservation, arbitrary custom
  schemas, and non-3D-CV media are outside the profile.

This boundary keeps closure finite. SceneIO will not implement a second USD
composition engine or a repository-owned USDC crate codec. Direct USDA
serialization and USDZ packaging remain repository-owned. A future profile
version may add a separately qualified upstream provider for current USDC and
evaluated composition/time; version 1 does not imply it.

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
OpenUSD 26.08 documentation is a standards reference. The current literal
allow-list does not approve TOST 1.0 as an executable dependency. TinyUSDZ
remains the independent Apache-2.0 implementation used by the optional
provider. Observed local
provider behavior is recorded in
[`usd_provider_qualification.md`](usd_provider_qualification.md).

## 2026-07-31 review findings

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

### Current code-state audit

The implementation review distinguishes committed capability from remaining
work:

| Area | State on 2026-08-01 | Evidence or remaining gate |
|---|---|---|
| U0 provider baseline | committed, bounded | TinyUSDZ 0.9.4 is qualified for USDA/USD/USDZ and historical USDC through crate 10; the current allow-list closes executable TOST/OpenUSD use as unavailable |
| U1 records | committed, complete | `SceneGraph`, `InstanceSet`, `VolumeAsset`, and additive mesh/point/Gaussian fields have parity and lifetime coverage |
| U2 stage skeleton | committed, complete | hierarchy, metadata, static transforms, selection, inspection, deterministic USDA/USDZ writes |
| U3 mesh | C1 committed, complete | indexed primvars; constant/uniform/vertex/varying/face-varying domains; float display fields; orientation; double-sided state; transforms; extent; USDA/USDZ read/write |
| U3 points | C1 committed, complete | points, normals, widths-as-diameters, ids, velocities, accelerations, display fields, indexed primvars, extent; USDA/USDZ read/write |
| U3 materials/assets | C2 committed (`917d48e`) | bounded PreviewSurface constants/textures, direct/subset bindings, streamed asset transactions, independent fixtures, refusal/lifetime tests, benchmarks, exact contracts, complete suite, and all three review lenses are green; hosted three-OS execution remains user-gated |
| U4 Gaussian schema | C3 committed (`a633477`) | official float/half read/write, raw-layout mapping, inspection, selection, extent, refusal coverage, generated benchmark, contracts, legacy controls, and full local qualification are green |
| U5 camera/volume/semantics/instances | complete through C5 | camera/render-product pairs, direct scalar-float OpenVDB dependencies, one effective taxonomy/label pair, static PointInstancer data, mixed-stage coexistence, generated large-case evidence, and the complete local gate are green |
| U6 current USDC/composition/time | Exit B complete | explicit false provider flags; all six composition arc families and authored time samples report/refuse; no OpenUSD executable dependency |
| U7 release closure | local closure complete; hosted pending | exact local suite, benchmark ledger, docs/contracts, verified source archive, Windows cp312-abi3 wheel, base and `sceneio[usd]` installed smokes; hosted compiler/package matrix remains user-gated |

### 2026-07-31 C2 closure evidence

The initial three-lens review found the following blockers, all now fixed in
the working tree:

- refuse non-default constant normals and indistinguishable unit-opacity
  `blend` materials;
- reject connected authored fallbacks, duplicate material leaf names, and
  every unconsumed shading descendant (`NodeGraph` is outside the profile);
- make prim selection resolve only reachable materials/assets and keep
  inspection/`load_payloads=False` from opening texture bytes;
- add O(1) unbound/direct-binding paths and linear, chunked subset writing;
- require unpackaged USDA assets to resolve beside the destination to the
  recorded source;
- reject duplicate/noncanonical USDZ members and direct-layer paths that leave
  the root-layer directory after canonical resolution;
- reject inherited material bindings on descendant renderable prims in full
  reads, selected reads, and inspection rather than accepting and dropping
  the inherited assignment;
- add the independent material/texture fixtures, write-failure matrix,
  lifetime checks, deterministic package checks, and generated allocation
  measurements listed in C2 below.

The unit adds 35 focused material/package nodes plus one benchmark node and
one `SceneGraph` source-locator validation node. It passes 4,177 tests with
6 expected skips from the exact 4,183-node local tree, full Ruff, rebuilt
compiled-symbol verification, and the exact assembly contract. The 100k-face/eight-
material/100 MiB asset benchmark records 118.8/130.0 MB/s USDA/USDZ writes
with 12.2 MB traced allocation and 71.3/70.2 MB/s full reads. A control caught
and removed a full-mesh normalization regression; the material-free C1 read is
back to 44.03 MB traced versus its 43.95 MB baseline. The resource/lifetime,
format/correctness, and test-soundness reviewers all sign off with no remaining
blocker. The existing Linux/Windows/macOS CI matrix now includes all three USD
suites; hosted execution remains pending the user-authorized push.

Focused review command:

```powershell
.venv\Scripts\python.exe -m pytest -q `
  tests\codecs\test_usd_scene.py tests\codecs\test_usd.py
.venv\Scripts\python.exe -m ruff check `
  src\sceneio\io\_usd tests\codecs\test_usd_scene.py
```

Current focused result: **46 tests pass and Ruff is clean** for the rich and
compatibility USD suites plus the generated benchmark smoke. The post-review
affected gate passes **57 tests**. The exact contract now matches the current
4,146-test tree with normalized collection hash
`f363c9148b0665ecc2e3dc1b52a06bfd1e2c3948d0670a595ef907db942f0b84`;
the sanitizer collection assertion matches it. All three final C1 review
lenses sign off with no remaining blocker. The final repository gate passes
**4,141 tests with 5 expected skips** and full Ruff is clean. Commit
`feat(usd): close rich mesh and points` closes C1.

### C1 closure audit

| Gate | Current evidence | Required action |
|---|---|---|
| implementation | mesh/point readers, writers, inspection, selection, and provider normalization are present | no new scope; fix only review or validation findings |
| focused correctness | 46 focused tests pass | retain as the fast pre-commit gate |
| resource/lifetime | final review signs off: provider text and arrays release before descendant traversal; inspection stays bounded; returned views retain owners; excluded payloads are not decoded | retain the focused lifetime/allocation cases through the final suite |
| format/convention | final review signs off: exact USD role types, indexed primvars, direct metadata parsing, extent, axes/units/transforms, and selected-sibling behavior are correct | retain the exact role/domain/convention cases through the final suite |
| test soundness | final review signs off: both cross-read directions, malformed inputs, writer guards, exact contracts, and generated benchmark value checks are effective | retain the exact contracts and generated benchmark smoke through the final suite |
| exact contracts | contract and sanitizer assertion match the 4,146-node tree and exact hash | retain through the final full-suite run |
| measurement | final one-run 100k-face/100k-point USDA/USDZ rows are recorded; duplicate normalized text and `str.strip()` allocation regressions were found and removed | retain the observational wording; repeatable comparison ledger remains C7 |
| repository gate | 57 affected tests and 4,141 complete-suite tests pass; 5 expected skips; full Ruff is clean; `git diff --check` reports only cosmetic Windows line-ending warnings | retain this exact checkpoint through commit |
| delivery | the `feat(usd): close rich mesh and points` commit contains the complete green C1 unit | do not push without a user request |

## Current implementation and measured review

The current `sceneio[usd]` profile uses TinyUSDZ 0.9.4 for qualified loading
and repository-owned deterministic USDA/USDZ writers. The compatibility path
supports:

- `.usd` and `.usda` ASCII layers, historical `.usdc` through crate 10, and
  single-root-layer `.usdz`;
- `Xform`, `Scope`, and polygonal `Mesh` prims;
- positions, face topology, vertex/corner normals and UVs;
- hierarchy, static matrix transforms, and one scene;
- metadata-only inspection, transactional path writes, and lifetime-safe
  owned results.

The additive `read_scene()` path now returns `SceneGraph`, maps Y/Z up-axis,
positive units, default prim, hierarchy, evaluated static transforms,
reset-transform-stack state, visibility, purpose, stage time metadata, and a
selected static snapshot. Prim selection retains required ancestors and does
not construct unselected mesh records. `write_scene()` transactionally writes
hierarchy, polygon mesh, and point-cloud `SceneGraph` values as USDA/USDZ.
Bounded materials/assets are the active C2 unit; current-crate and selected
animated-value work remains U6.
Inspection reports representation/crate version, typed prim counts, time
range, authored dependencies/variants, unsupported features, and whether the
legacy mesh projection is available.

The compatibility `sceneio.read()` path still requires Y-up and one meter per
unit and returns `MeshScene`; its deterministic bytes are unchanged. Both
paths refuse data outside their stated mapping. TinyUSDZ is locally qualified
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

| Property | TOST 1.0 | Apache-2.0 | MIT/BSD/zlib | Public domain |
|---|---|---|---|---|
| permissive, non-copyleft | yes | yes | yes | no license conditions |
| source disclosure required | no | no | no | no |
| explicit patent grant/termination | yes | yes | generally no | no license grant needed |
| modified-file notice | yes | yes | generally no | no |
| NOTICE handling | yes, when supplied | yes, when supplied | generally no | no |
| trademark permission | only what notice compliance requires | limited customary origin description plus notice compliance | varies, usually no grant | not applicable as a license term |
| same license as TOST | yes | no | no | no |

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
Compared with Apache-2.0 it grants less trademark permission. The 2026-08-01
review compared the official OpenUSD 26.08 license at `ee47c679abde` with the
Apache Software Foundation's Apache-2.0 text and confirmed that OpenUSD itself
identifies section 6 as the difference. SPDX License List 3.28.0 catalogs the
materially equivalent older text as `Pixar`, notes that it is essentially
Apache-2.0 with a modified section 6, and does not mark it OSI-approved. The
TOST name itself has no standard SPDX identifier; current `usd-core` metadata
uses `LicenseRef-TOST-1.0`.

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

That last distinction is material for SceneIO's strict allow-list. The
official OpenUSD license bundle includes third-party notices in addition to
TOST. It specifically notes that RapidJSON's `bin/jsonchecker/` is the only
part carrying the old JSON license and says excluding that directory avoids
that term. The JSON license has a use restriction, so it does not satisfy this
repository's MIT/BSD/zlib/Apache/public-domain-only policy. C6 must therefore
inspect the exact installed wheel contents and prove that component is absent;
similarity of the top-level TOST terms is not sufficient approval.

This plan does not change the allow-list. Until that decision is made,
OpenUSD is a standards reference only and TinyUSDZ remains the executable
oracle/provider. The C4 review did not install, invoke, link, vendor, or copy
OpenUSD code.

Recommended project decision: approve a narrow exception for unmodified
official OpenUSD packages under TOST 1.0, only as an optional development/test
oracle at first. Do not bundle or link OpenUSD into the SceneIO wheel. Promote
it to an optional runtime provider only if the provider inventory, platform
availability, and performance comparison justify doing so. This keeps the
NumPy-only base runtime and manylinux2014 wheel contract intact.

This recommendation is a project policy assessment, not legal advice. A
practical policy entry would approve only:

```text
LicenseRef-TOST-1.0 (materially equivalent SPDX: Pixar):
official unmodified OpenUSD packages only; optional oracle/provider only;
never bundled in SceneIO wheels; complete package notice inventory required.
```

Package availability is a separate gate from source-release availability. As
of 2026-07-31, PyPI publishes official `usd-core 26.8` wheels for CPython
3.9-3.14 on Windows x86-64, manylinux glibc 2.27/2.28 x86-64, and macOS
universal2. This makes an exact-version C6 oracle feasible, but it does not
approve the TOST license or make OpenUSD part of SceneIO's abi3/manylinux2014
wheel. If the narrow policy entry is not approved, close current
USDC/composition/time as unavailable instead of waiting or adding a
repository-owned composition/crate implementation.

If that narrow entry is not approved, SceneIO still closes the direct static
profile with TinyUSDZ and repository-owned USDA/USDZ output. It reports
current USDC, composition, and selected-time evaluation as unavailable rather
than extending the project indefinitely.

## Target profile contract

### File and container behavior

| Surface | Required behavior |
|---|---|
| `.usda` | read and deterministic repository-owned write |
| `.usdc` | historical crate read through the qualified base provider; current read and any write require the optional current OpenUSD provider |
| `.usd` | detect forwarded USDA/USDC representation; preserve current ASCII write default for compatibility |
| `.usdz` | read/write uncompressed, unencrypted, 64-byte-aligned packages with a valid first USD layer |
| assets | resolve/package relative PNG/JPEG/EXR textures; resolve OpenVDB only for USDA/USD and refuse volume-bearing USDZ output; composed layer dependencies are optional-provider input only |
| inspection | report actual representation, version, prim counts/types, time range, dependencies, variants, and unsupported profile features without decoding bulk arrays |

The logical registry ids remain `usd` and `usdz`. `.usdc` joins the `usd`
extension set, and inspection records `representation="usda"|"usdc"` plus
the provider capability that accepted it. This avoids breaking code that
already treats `.usd` and `.usda` as one USD codec family while keeping
current-crate claims exact.

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
| `UsdGeomCamera` + `UsdRenderProduct` | `CameraRig` rows | projection-equivalent intrinsics and one unambiguous positive resolution; unrepresented physical-camera fields must remain at schema defaults; no distortion |
| `UsdVolVolume` + `UsdVolOpenVDBAsset` | volume asset payload | named OpenVDB grid reference, transform, purpose, dependency |
| `UsdGeomPointInstancer` | `InstanceSet` | prototype references plus ids, transforms, masks, and known per-instance primvars |

### Materials

The accepted material network is deliberately bounded:

- `UsdShadeMaterial` and `MaterialBindingAPI`;
- `GeomSubset` face material assignments;
- `UsdPreviewSurface` base color, emissive, metallic, roughness, opacity,
  opacity threshold, and normal;
- `UsdUVTexture` with an explicit `st` primvar, explicit repeat/clamp/mirror
  wraps, explicit supported source color space, and unspecified filtering;
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
When both half and float variants of one attribute family are authored, the
float attribute wins as specified by OpenUSD. A stage whose selected families
mix half and float precision is refused because the record has one precision
field. Float16 output requires every stored value to survive a float16
round-trip exactly. Missing orientation, scale, opacity, and radiance arrays
use the schema's identity, one, fully opaque, and degree-zero 0.5 DC defaults.
The profile accepts projection hints `perspective` and `tangential`, and
sorting hints `zDepth`, `cameraDistance`, and `rayHitDistance`. SceneIO is
deliberately stricter than the renderer fallback: authored per-particle arrays
must have exact counts instead of being truncated or discarded.

### Cameras

USD cameras always use a Y-up local camera frame looking down negative Z with
positive X to the right. Camera mapping must explicitly handle:

- OpenCV versus OpenGL axes;
- camera-to-world versus world-to-camera transforms;
- projection-equivalent focal/aperture ratios and aperture offsets;
- pixel resolution supplied by exactly one associated `UsdRenderProduct`.

`CameraRig` does not preserve independent physical filmback/focal values,
clipping, focus distance, f-stop, exposure, or shutter metadata. The bounded
profile therefore preserves the evaluated pinhole/orthographic projection and
requires those other authored properties to remain at schema defaults. A
camera with no usable render-product resolution, or with more than one
plausible resolution, is refused.

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
- external authored URI/type tables plus separate source locators used for
  streamed copying from direct files or USDZ members;
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

The work is finite and ordered. U0-U2 are already committed. Do not start a
later unit while an earlier unit has uncommitted or failing changes.

| Commit unit | Deliverable | Required evidence | Closure rule |
|---|---|---|---|
| C1 (done) | close current U3 mesh + point worktree | focused differential/count/interpolation/lifetime tests, existing USD compatibility bytes, selected-prim proof, generated medium mesh/point measurement, full suite, Ruff, contracts | one green commit; material fields still refuse explicitly |
| C2 (done, `917d48e`) | U3 materials + texture assets | PreviewSurface constants and texture graph, direct and subset bindings, transactional USDA/USDZ assets, independent cross-read, missing/collision/path cases, generated packaged-texture measurement | one green commit; arbitrary networks/UDIM remain explicit exclusions; hosted three-OS run is deferred to the next authorized push |
| C3 (done, `a633477`) | U4 official Gaussian schema | locally authored, standards-derived 26.08 schema fixtures; exact quaternion/SH/precision assertions; 1k/100k/1M generated measurements; legacy splat parity | one green commit; exact schema mapping with no implicit log/logit conversion |
| C4 (done, `d1ee8ea`) | U5 cameras | camera/render-product association, projection-equivalent intrinsics and pose convention tests, default-only unrepresented fields, mixed-resolution and ambiguity refusals, camera-stage measurement | one green closure unit; hosted three-OS execution remains deferred to the next authorized push |
| C5 (done, `6eeae8e`) | U5 volumes + semantics + instances | direct OpenVDB dependency resolution, one taxonomy/label pair, prototype identity/order/masks, mixed-stage round-trip and dependency tests; refuse volume-bearing USDZ writes | focused/complete gates, docs, and large-case measurement are green |
| C6 (done, `fa321c1`) | U6 provider capability | Exit B: TOST remains outside the literal allow-list; current USDC, evaluated composition, and selected time are explicit unavailable flags | no OpenUSD install/invocation and no repository-owned composition/crate implementation |
| C7 (local closure complete) | U7 release closure | full local tests, benchmark ledger, docs/contracts, exact source archive, repaired Windows wheel, NumPy-only and pinned TinyUSDZ installed smokes; nonpublishing platform matrix prepared | claim exactly `sceneio.usd.3dcv/1`; hosted compiler/package evidence still requires a user-authorized push/run |

Execution is intentionally capped at seven commits. C1-C6 are committed and
the local portion of C7 is complete. One bounded action remains: after the
user authorizes a push, run the prepared nonpublishing compiler and package
matrix once against that exact tree and record the hosted result. Publication
is a separate tag-driven workflow action.

No later unit may expand an earlier unit's public profile merely to accept an
unrepresentable input. The correct result is an explicit unsupported feature.

Stop rules prevent the project from becoming open-ended:

- if the optional OpenUSD provider is not approved or unavailable, close with
  historical USDC read only and report current USDC/composition/time as
  unavailable;
- if a composition arc is outside the qualified optional provider behavior,
  report it through inspection and refuse the rich read;
- if a schema cannot map exactly to a SceneIO record, keep it outside the
  profile instead of adding an opaque preservation system;
- do not add rendering, full layer editing, or unrelated USD schema domains to
  close this profile.

### File ownership for the remaining work

Keep schema logic isolated so the repository remains expandable:

| Concern | Repository owner |
|---|---|
| stage traversal, selection, payload dispatch | `src/sceneio/io/_usd/stage.py` |
| mesh primvars/topology | `src/sceneio/io/_usd/geometry.py` |
| points arrays/interpolation | `src/sceneio/io/_usd/points.py` |
| PreviewSurface, bindings, subsets | `src/sceneio/io/_usd/materials.py` |
| asset resolution and USDZ entries | `src/sceneio/io/_usd/package.py` |
| Gaussian schema | `src/sceneio/io/_usd/gaussians.py` |
| camera schema | `src/sceneio/io/_usd/cameras.py` |
| volume dependencies | `src/sceneio/io/_usd/volumes.py` |
| inherited semantic labels | `src/sceneio/io/_usd/semantics.py` |
| point instances | `src/sceneio/io/_usd/instances.py` |
| provider selection/version ceiling | `src/sceneio/io/_usd/provider.py` |
| compatibility `MeshScene` behavior | `src/sceneio/io/_usd/legacy.py`; do not mix rich payload behavior back into it |

Provider adapters may normalize upstream API quirks, but the in-memory mapping,
validation, deterministic USDA writer, USDZ packager, capability reporting,
and public behavior remain SceneIO-owned.

### Remaining implementation audit and exact execution map

The 2026-08-01 code review confirms that the remaining work is localized.
C3 and C4 are committed. The current worktree implements C5 in three focused
schema modules and keeps traversal, selection, and payload dispatch in
`stage.py`.

#### 2026-08-01 C3 closure checkpoint

| Evidence | Observed result | Required action before C3 closure |
|---|---|---|
| focused Gaussian record + USD tests | 62 passed | retain the standards-derived, float/half, degree 0--3, transform, refusal, lifetime, and allocation cases in the final gate |
| transform behavior | fixed: a payload-free Xform shadow sends only authored Gaussian xformOps back through TinyUSDZ's qualified transform evaluator | the differential translate/rotate/scale/reset test must remain equal to an ordinary Xform; do not replace it with repository-owned transform math |
| public refusal tests | fixed: the public cases assert `sceneio.FormatError` while retaining exact domain diagnostics | keep internal `ValueError` private to the adapter boundary |
| legacy compatibility | 222 passed with one documented SPZ-v2 oracle skip | retain Gaussian PLY, compressed PLY, SOG, KSplat, SPZ, SPLAT, record, and public API controls |
| allocation/performance | generated 1k/100k degree-3 and 1M degree-0 USDA/USDZ plus Gaussian PLY controls are bit-exact; large write RSS stays below logical payload | retain chunked extent reduction, 1,024-row SH serialization, and separate chunked float16 SH validation; document TinyUSDZ's full-layer read/inspect RSS rather than claiming lazy provider decode |
| contracts/workflow/docs | exact collection contract is 4,231 nodes; Gaussian tests are in both focused three-OS commands; baseline, coverage, architecture, and plan are updated | rerun contract/document tests after final edits |
| complete local gate | exact collection 4,231; 4,225 passed and 6 documented skips; full Ruff and diff check clean | hosted three-OS execution remains user-gated and is not implied by this local result |
| resource/lifetime review | green after removing the SH concatenation and payload-sized extent intermediates; Gaussian records own their arrays, shadow stages do not escape the read call, and returned views survive provider/source release | retain the chunk-boundary and lifetime cases |
| format/correctness review | green after fixing direct Gaussian xform evaluation; exact schema names, float-over-half rules, WXYZ mapping, degree/metadata rules, three-sigma extent, hints, and explicit convention refusals are covered | keep the multi-Gaussian path-keyed transform differential |
| test-soundness review | green: locally authored standards-derived literals and direct TinyUSDZ property assertions precede self-round-trip; malformed/refusal, destination, lifetime, legacy, benchmark, and public-contract cases are independent | OpenUSD executable comparison remains additive C6 evidence only if TOST use is approved |

#### 2026-08-01 C4 implementation review

| Evidence | Observed result | Required action before C4 closure |
|---|---|---|
| camera implementation | `cameras.py` maps static `Camera` plus exactly one `RenderProduct`, all five aspect-conformance policies, perspective/orthographic projection, local rigid pose, inspection, selection, and deterministic USDA/USDZ writes | retain the narrow profile: no distortion, depth of field, motion blur, stereo, nondefault clipping/exposure/shutter, or independent physical-camera preservation |
| focused camera tests | 43 passed | retain literal standards-derived fixtures, direct TinyUSDZ cross-read, independent projection/pose math, malformed/refusal cases, source lifetime, mutation isolation, and destination preservation |
| affected USD/CameraRig tests | 196 passed and one platform symlink skip; 259 COLMAP/calibration controls pass | retain these controls in the final release gate |
| collection and style | exact 4,275-node contract; 4,269 passed with 6 documented skips; full Ruff and diff checks clean | preserve the count and focused workflow entry |
| generated measurement | 1,000 cameras measured for USDA and USDZ across write, full read, inspection, and selected read | measured rows are recorded in `bench/BASELINE.md`; TinyUSDZ still parses the complete layer, so selected reads are adapter-bounded rather than provider-lazy |
| resource/lifetime review | green: owned `CameraRig` arrays survive source/provider release; no provider-backed camera view escapes; write validation precedes destination replacement | retain lifetime and failed-write cases; do not claim low provider RSS from the selected-read timing |
| format/correctness review | green: official 26.08 schema names/defaults, tenths-of-scene-unit optics, five conform policies, OpenGL local frame, WXYZ pose, and one-product association are covered | retain the documented camera-to-parent/local pose and USD-float projection-equivalence boundary |
| test-soundness review | green: literal inputs and independently calculated K/pose expectations precede self-round-trip; TinyUSDZ validates emitted prim types/properties; 259 calibration/COLMAP controls and 40 docs/contracts pass | executable OpenUSD comparison is outside profile v1 under the current allow-list; it was not a C4 blocker |

#### 2026-08-01 C5 implementation review

| Evidence | Observed result | Closure requirement |
|---|---|---|
| schema adapters | `volumes.py`, `semantics.py`, and `instances.py` isolate the three schema families; `stage.py` owns only traversal, selection, dependency expansion, payload dispatch, and deterministic authoring integration | retain these ownership boundaries; do not move OpenVDB decoding or USD composition into the adapters |
| direct volumes | one `field:<name>` relationship maps to one scalar-float `OpenVDBAsset`; shared URI/grid resources remain shared; read and inspection do not open VDB bytes; volume-bearing USDZ writes refuse because VDB is outside USDZ 1.3 | retain exact `.vdb`, data type, role/class, missing-source, shared-source, selection, and destination-preservation cases |
| semantics | exact `SemanticsLabelsAPI:<taxonomy>` and `semantics:labels:<taxonomy>` names are used; inherited values follow USD union behavior; the bounded record accepts one effective taxonomy and one effective label per node | retain multiple-taxonomy/label refusals and inheritance-consistent writer guards |
| point instances | ordered prototype relationships, indices, positions, float/half orientations, scales, signed ids, invisible ids, and a closed set of per-instance motion/display arrays map to owning `InstanceSet` records | retain default-value, unit-quaternion, count/type/interpolation, inactive-id, missing-prototype, prototype-cycle, selection, and lifetime checks |
| mixed-stage evidence | one TinyUSDZ-readable USDA contains Mesh, Points, official Gaussian splats, Camera, Volume/OpenVDBAsset, PointInstancer, and inherited semantic labels; all records round-trip together | keep this as the additive public-profile coexistence test |
| focused verification | 185 USD-family cases pass with one platform symlink skip; the post-review affected gate passes 45 tests | retain in the three-OS focused workflow |
| allocation/performance | a 1M-instance, one-prototype layer is 51.78 MB; write is 3.75 s/80.01 MB traced, full read 10.20 s/167.79 MB traced, and inspect 6.99 s/51.79 MB traced. A sparse 1 GiB VDB dependency reads in 1.03 ms/0.024 MB traced and inspects in 0.55 ms/0.020 MB traced | describe TinyUSDZ full-layer materialization honestly; the required wins are no prototype geometry expansion and no VDB-byte decode |
| resource/lifetime review | green after adding the large-VDB allocation bound; records own numeric arrays and strings; provider objects, source handles, and VDB files do not back returned views; sidecar transactions close before replacement | retain source-release, missing-source, selected-sibling, and failed-write cases |
| format/correctness review | green after adding prototype-cycle parity to inspection; relationship order, signed ids, WXYZ quaternions, inheritance union, absolute prototype paths, direct asset provenance, and USDZ boundaries are explicit | keep unsupported authored values as precise refusals rather than conversions |
| test-soundness review | green: locally authored standards-derived literals and TinyUSDZ property/type reads precede self-round-trip; allocation, malformed, lifetime, selection, mixed-payload, transaction, and generated large-case checks exercise independent outcomes | OpenUSD executable comparison remains optional C6 evidence only after the license decision |

| Unit | Current seam | Implementation work | Focused verification | Validation and documentation exit |
|---|---|---|---|---|
| C3 Gaussian | committed at `a633477` | preserve the exact official mapping and bounded provider transform fallback; no additional schema scope | 62 focused mapping/record tests; 222 legacy passes plus one expected skip; exact 4,231-node full gate; generated 1k/100k/1M rows | hosted execution remains deferred to the next authorized push |
| C4 Camera | done in this closure unit | keep `UsdGeomCamera`/`UsdRenderProduct` mapping isolated in `cameras.py`; preserve camera-to-parent/OpenGL conventions and float-precision projection equivalence | 43 camera tests; 196 affected USD/CameraRig passes; 259 calibration/COLMAP controls; 40 docs/contracts; exact 4,275-node full suite | hosted three-OS execution remains deferred to the next authorized push |
| C5 Remaining payloads | locally complete in focused `volumes.py`, `semantics.py`, and `instances.py` modules | preserve the direct scalar-float VDB reference, one effective semantic pair, and static PointInstancer boundary; keep prototype geometry shared and volume-bearing USDZ unavailable | 20 family nodes plus benchmark smoke, existing USD regression family, literal relationships/attributes, missing/shared VDB, inheritance, ids/masks/order, cycle, lifetime, selection, and destination preservation are green | generated 1 GiB VDB and 1M-instance evidence recorded; exact 4,299-node gate passes 4,293 with 6 documented skips; full Ruff and docs/contracts are clean |
| C6 Static-provider closure | complete through Exit B | preserve direct USDA/USDZ and historical crate reads; expose profile id plus false `current_usdc`, `composition`, and `selected_time` flags; scan/refuse sublayer/reference/payload/variant/inherit/specialize inputs and authored samples | capability, inspection, direct arc, selected-time, crate ceiling, provider-boundary, import-isolation, registry, and static TinyUSDZ controls | no OpenUSD package installed or invoked; capabilities/provider report/docs exact; C7 supplies artifact and hosted platform evidence |
| C7 Release closure | local closure complete; hosted exact-tree run still user-gated | no new format scope; capability manifests, public docs, installed-package surfaces, benchmark ledger, and release metadata are reconciled | 4,307-node local collection; 4,301 pass/6 skip; Ruff; generated malformed/differential cases; verified sdist-to-Windows-wheel chain; NumPy-only and TinyUSDZ installed smokes | nonpublishing Windows/Linux/macOS matrix is prepared with a pinned `sceneio[usd]` smoke; ask before push/run; publish separately through the approved tag workflow |

Each unit has a stop rule: if an authored property cannot be represented
exactly by the named SceneIO record, refuse it with a specific diagnostic. Do
not add opaque preservation, a second composition engine, or new non-3D-CV
schema domains to make the unit pass.

### U0 — freeze profile and qualify providers

- [x] Compare the TOST 1.0 and Apache-2.0 texts and record the exact project
      consequence.
- [x] Apply the current literal allow-list: TOST 1.0 is permissive and
      Apache-2.0-derived but distinct, so executable OpenUSD use is not
      approved for profile version 1.
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
- [x] Compare TinyUSDZ against the accepted direct-static fixtures and close
      the conditional `usd-core` comparison branch as not applicable under
      the current allow-list.
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

- [x] Split `_usd.py` into a facade plus bounded modules:
      `_usd/provider.py`, `_usd/stage.py`, `_usd/geometry.py`,
      `_usd/materials.py`, `_usd/gaussians.py`, `_usd/cameras.py`, and
      `_usd/package.py`; compatibility mesh behavior is isolated in
      `_usd/legacy.py`.
- [x] Add `.usdc` routing under the existing `usd` codec id, bounded by the
      qualified crate-10 ceiling.
- [x] Implement `read_scene()` and hierarchy-only `write_scene()` without
      changing the old mesh-only return contract; typed payload writes remain
      their U3-U5 units.
- [x] Map `defaultPrim`, Y/Z up-axis, units, provider-evaluated ordered static
      transforms, reset-transform-stack state, visibility, purpose,
      validated finite mesh extent (with record bounds derived from positions),
      and one selected static time. Animated value evaluation remains
      explicitly U6.
- [x] Extend inspection with representation/version, typed prim counts,
      time range, dependencies, variants, and unsupported features.
- [x] Add path/prim selection that avoids constructing unselected payload
      records.
- [x] Preserve destinations on every validation/provider/write failure.

Exit: an empty/hierarchy-only stage round-trips and existing static mesh USD
tests remain byte exact.

Local U2 evidence: TinyUSDZ independently cross-reads both repository-authored
USDA and aligned USDZ hierarchy fixtures; rich reads and legacy mesh reads are
tested side by side; a selected branch proves that an unselected mesh decoder
is never called; owner-retaining transform views survive source removal; and
injected package, validation, and unavailable-USDC failures preserve existing
destinations. The exact local collection is 4,132 nodes and the complete MSVC
run passes 4,127 with five documented optional skips. Two three-run legacy
controls span 8–13 MB/s, with paired SceneIO/direct-read ratios of
0.95–1.13; rich inspection retains 0.2 MB traced Python storage for both USDA
and stored USDZ, and the generated 16 MiB feature scan stays below 512 KiB.

The U2 three-part review is clear. The resource/lifetime pass verifies that
mapped direct layers and exact stored-USDZ root extents close before the path
is renamed or removed, compressed package roots use a bounded temporary map,
and every returned record owns its arrays. The format/correctness pass found
and fixed a fast-scan ambiguity: composition words and asset delimiters inside
comments or quoted metadata are now ignored, while arbitrary whitespace
around real arcs remains accepted. The test-strength pass covers both
provider cross-read directions, legacy/rich API separation, skipped-payload
construction, destination preservation, unsupported operation boundaries,
source removal, and the generated allocation control.

### U3 — meshes, points, materials, and texture assets

- [x] Close the worktree mesh mapping on `SceneGraph`.
- [x] Close indexed mesh primvars and all five interpolation domains, float
      display colors/opacities, orientation, double-sided state, and extent;
      material subsets remain in the next commit unit.
- [x] Close `UsdGeomPoints` positions, normals, widths-as-diameters, ids,
      velocities, accelerations, display fields, interpolation/count guards,
      indexed primvars, and derived extent.
- [x] Implement the bounded `UsdPreviewSurface` graph and `MaterialSet`
      mapping.
- [x] Resolve/package PNG, JPEG, and EXR textures with collision-free relative
      names; reject escaping or missing dependencies.
- [x] Cross-read standards-derived and SceneIO-authored fixtures with
      TinyUSDZ plus independent image decoders. OpenUSD comparison remains a
      future-profile option only after a separate policy change.
- [x] Add large mesh and point-cloud path benchmarks and selected-prim reads.

Exit: mixed mesh/point scenes and their accepted materials are semantically
identical through both directions.

#### C1 implementation checklist — geometry closure

1. Keep the TinyUSDZ `UsdGeomPoints` built-in-array normalization in
   `points.py`; do not leak provider-specific parsing into `stage.py`.
2. Preserve indexed primvar meaning by flattening values with indices before
   validating interpolation-domain counts.
3. Continue mapping stage Y-up to `opengl`, Z-up to `enu`, and
   `metersPerUnit` to payload scale without numeric coordinate conversion.
4. Keep node transforms on the node and require payload-local transforms to be
   identity on write.
5. Keep rich `Points` stages out of the legacy `sceneio.read()` projection and
   direct users to `read_scene()` rather than dropping data.
6. Update inspection without constructing `Mesh` or `PointCloud` records.
7. Update exact test-collection/contracts and the relevant public capability
   snapshot before commit.

Focused verification:

- provider-authored bytes → rich read → exact arrays and metadata;
- SceneIO write → TinyUSDZ cross-read → exact arrays and authored tokens;
- rich read → write → rich read semantic equality;
- indexed and constant/vertex/varying/face-varying cases;
- empty arrays, mismatched counts, invalid indices, unsupported color space,
  time samples, non-finite values, and topology range guards;
- source removal plus garbage collection with returned arrays still valid;
- selection proving an unselected payload constructor is not called;
- existing legacy USD bytes and mesh projection unchanged.

Measurement:

- generated 100k-point and 100k-face USDA/USDZ write/read/inspect rows;
- report wall time, throughput, peak RSS, traced Python allocation, and output
  size;
- compare full read with selected-prim and inspect paths;
- record the result in `bench/BASELINE.md`; improvement is qualitative, but a
  real regression must be corrected or explained.

#### C2 implementation checklist — materials and assets

1. Traverse `Material`, `Shader`, `NodeGraph`, and `GeomSubset` as resource
   prims, not SceneGraph hierarchy nodes.
2. Require exactly one `Material.outputs:surface` connection to a descendant
   `UsdPreviewSurface` shader.
3. Map only base color, emissive, metallic, roughness, opacity,
   opacity-threshold, and normal inputs. Apply documented PreviewSurface
   defaults only when unauthored; refuse authored unsupported inputs or
   non-default values that `MaterialSet` cannot preserve. `MaterialSet` has no
   constant-normal field, so accept only the default constant normal or a
   supported normal texture.
4. Map direct `material:binding` and face `GeomSubset` assignments. Validate
   face indices, non-overlap, complete primitive runs, and material index
   bounds.
5. Map only one `UsdUVTexture` hop per accepted material input, one `st`
   primvar source, repeat/clamp/mirror wrap modes, and explicit supported
   color-space tokens. Refuse explicit filtering. Require identity scale/bias
   for ordinary textures and the PreviewSurface canonical normal transform
   `scale=(2,2,2,1)`, `bias=(-1,-1,-1,0)` for normal textures.
6. Resolve direct-layer assets relative to the root layer. For USDZ, resolve
   package-relative entries. Accept PNG/JPEG/EXR only.
7. Copy/package assets in chunks, derive collision-free stable relative names,
   and complete the entire write transaction before replacing a destination.
8. Keep texture bytes out of `MaterialSet`; store normalized relative
   references and the SceneGraph external-asset table.
9. Refuse missing assets, absolute paths where portability is required,
   parent-directory escapes, UDIM patterns, procedural nodes, unsupported
   connection fan-in, and unrepresented scale/bias/color operations.
10. Validate every reachable resource descendant. Refuse unused
    `Shader`/`NodeGraph` data within a selected material rather than excluding
    it silently. A connected PreviewSurface input may not also author a
    fallback value that SceneIO cannot preserve.
11. Reject duplicate material leaf names on read so every accepted
    `MaterialSet` remains writable without renaming.
12. A full payload read validates and returns the complete stage material
    library. A prim-selected read remaps only materials reachable from the
    included meshes, so an unrelated selected payload does not open textures.
    `load_payloads=False` and inspection may report asset URIs but do not open
    or require asset bytes.
13. Add O(1) binding fast paths for unbound meshes and direct-only bindings.
    Allocate per-face state only when subsets exist. Group writable primitive
    ranges once and emit numeric indices in fixed-size chunks rather than
    rescanning materials or writing one Python scalar at a time.
14. Reject duplicate or noncanonical USDZ member names before asset lookup.
    A direct-layer asset's resolved path must remain within the root-layer
    directory, including after symlink resolution.
15. Define `package_assets=False` narrowly: every authored URI must resolve
    beside the destination to the same recorded source; otherwise refuse
    before creating or replacing output.
16. Refuse `alpha_mode="blend"` when opacity is one and there is no alpha
    texture, because that state is indistinguishable from opaque in the
    accepted PreviewSurface mapping.

Ground-truth cases:

- small standards-derived constant, textured, direct-binding, and subset
  USDA fixtures with literal expected values and relationships;
- SceneIO-authored USDA/USDZ accepted by TinyUSDZ;
- independent PNG/JPEG/EXR decoders confirm packaged asset bytes and image
  content;
- executable OpenUSD comparison remains a future-profile option only after a
  separate policy change; it does not block the direct-static profile;
- self-round-trip is supplementary and never the only evidence.

Write-failure cases must prove the old destination and any pre-existing asset
directory remain unchanged. Generated texture packages cover duplicate base
names, shared assets, nested source paths, missing inputs, a 100 MB streamed
asset, and a 100k-face multi-material mesh. Measurements must show bounded
Python allocation, linear subset serialization, inspection without asset
decode/copy, and no material-free C1 read regression.

### U4 — official Gaussian splats

- [x] Read/write `ParticleField3DGaussianSplat`, required built-in APIs, and
      official attribute names.
- [x] Support float and half `positions`, `orientations`, `scales`,
      `opacities`, and SH-coefficient attributes; degree 0-3 SH, projection
      hint, sorting hint, extent, visibility, purpose, and transforms. Do not
      accept non-schema `velocities` as a Gaussian built-in.
- [x] Apply float-over-half precedence per attribute family, schema defaults
      for omitted optional families, mixed-selected-precision refusal, and
      exact float16 round-trippability on write.
- [x] Pin the TinyUSDZ XYZW provider view to SceneIO WXYZ mapping.
- [x] Prove coefficient reordering by raw float-bit comparison.
- [x] Refuse count mismatches, unsupported degrees/dtypes, non-finite values,
      non-positive linear scales, and opacity outside `[0, 1]`.
- [x] Test explicit log/logit conversion separately from USD I/O.
- [x] Add generated 1k, 100k, and 1M Gaussian benchmarks for USDA and USDZ;
      do not commit the large artifacts. Current USDC rows belong to C6.
- [x] Prove prim selection avoids unselected Gaussian record construction.
      TinyUSDZ still parses the complete layer, so C3 does not claim a row
      range or lazy provider read that it cannot deliver.
- [x] Prove returned arrays remain valid after provider objects and source
      files are released, and rerun every legacy splat-codec control.

Exit: standards-derived official-schema fixtures read bit-exactly, SceneIO
USDA/USDZ cross-read through TinyUSDZ, and all legacy splat codecs remain
unchanged. An approved OpenUSD executable comparison is additive C6 evidence,
not a C3 prerequisite.

### U5 — cameras, volumes, semantics, and instances

- [x] Map supported `UsdGeomCamera` optics and transforms to `CameraRig`.
- [x] Pair cameras with `UsdRenderProduct` resolution and refuse ambiguous
      pixel-intrinsic reconstruction.
- [x] Add explicit OpenCV/OpenGL and pose-direction tests.
- [x] Prove selected-camera reads do not enter unrelated geometry adapters,
      camera
      arrays outlive provider/source release, and write failures preserve the
      destination.
- [x] Measure a generated 1,000-camera stage, including inspection and
      selected-camera reads.
- [x] Map `UsdVolVolume`/`UsdVolOpenVDBAsset` references to the existing
      bounded OpenVDB profile for USDA/USD. Refuse volume-bearing USDZ writes;
      `.vdb` is not an allowed USDZ 1.3 member type.
- [x] Map inherited semantic labels without treating them as image masks.
      Accept at most one taxonomy/label pair per evaluated node, matching the
      current `SceneGraph`; refuse multiple labels or taxonomies.
- [x] Map `UsdGeomPointInstancer` to `InstanceSet`; retain prototype identity
      and per-instance ordering.
- [x] Test missing assets, shared assets, instance prototypes, inactive ids,
      prototype cycles, and mixed camera/geometry stages.
- [x] Reuse C2 direct-asset provenance for OpenVDB without decoding grid bytes;
      prove shared/missing VDB sources, inherited-label ownership, masks, ids,
      prototype order, and provider/source lifetime.
- [x] Measure a generated 1 GiB VDB dependency and 1M instances without
      expanding prototype geometry per instance.

Exit: the complete set of accepted 3D-CV payload kinds round-trips in one mixed
stage.

### U6 — static-profile provider closure

- [x] Apply the current literal allow-list: TOST 1.0 is not approved for an
      executable dependency, so do not install or invoke OpenUSD.
- [x] Close the conditional `usd-core` inventory branch as not applicable to
      profile version 1. Reopen it only after a separate policy change.
- [x] Keep current USDC read and USDC write unavailable. Retain qualified
      historical crate 10 input and refuse later crates before provider
      dispatch.
- [x] Keep repository-owned USDZ output to one flattened root layer plus
      assets: stored entries, first/default layer, 64-byte data alignment,
      relative paths, no encryption, and no unsupported media.
- [x] Detect sublayers, references, payloads, variants, inherits, and
      specializes; report them in `inspect()` and refuse reads instead of
      exposing TinyUSDZ's unevaluated raw traversal.
- [x] Refuse non-empty variant selections because evaluated variants are
      unavailable.
- [x] Detect authored time samples and refuse reads, including explicit
      `time=` requests. A finite time on a wholly static stage is metadata,
      not animated-value evaluation.
- [x] Write only the directly authored flattened static snapshot.
- [x] Report authored asset dependencies, unsupported arcs, profile id, and
      the three false provider flags in `inspect()`.

Exit B is selected: direct static profile closure proceeds, and both
capabilities and inspection explicitly report `current_usdc`, `composition`,
and `selected_time` as unavailable. Layer-stack authoring remains out of
scope. C6 does not change SceneIO's base wheel contract.

Provider validation must run in a separately installed environment because
`usd-core` has CPython/platform-specific wheels and a newer Linux floor than
SceneIO's abi3/manylinux2014 contract. It must never become an import-time
dependency of `sceneio`, be bundled into SceneIO wheels, or be required for
the NumPy-only smoke test.

### U7 — qualification and documentation closure

- [x] Run the complete suite and Ruff with the required interpreter.
- [ ] Run compiler-instrumented memory/undefined-behavior checks.
- [x] Run generated malformed/truncated/provider-differential cases.
- [x] Run the three review lenses:
      resource/lifetime, format/convention correctness, and test soundness.
- [x] Record benchmark deltas in `bench/BASELINE.md`.
- [x] Update `format_coverage.md`, `coverage_roadmap.md`,
      `io_optimization_plan.md`, public API docs, capability snapshots, wheel
      smoke, and `LICENSES/README.md`.
- [x] Build the sdist and installed-wheel smoke with NumPy only, TinyUSDZ, and
      each approved optional provider configuration.
- [x] Prepare the nonpublishing Windows/Linux/macOS package matrix, including
      a pinned binary TinyUSDZ profile smoke on each wheel host.
- [x] Keep pushing and the hosted cross-platform run user-gated.
- [ ] Run the prepared hosted compiler/package matrix after user authorization
      and record the exact-tree run ids.

Local C7 evidence uses one verified source archive as the wheel source. The
Windows `cp312-abi3` wheel passes the exact distribution inventory, a fresh
NumPy-only isolated smoke, and a fresh `sceneio[usd]` smoke with NumPy 2.2.6
and TinyUSDZ 0.9.4. The optional smoke checks the public profile id, all three
false provider flags, rich static reads, inspection, and composition refusal.
The wheel inventory retains NumPy as the only unconditional requirement and
the complete license directory. SceneIO's Linux wheel retains manylinux2014;
the separately installed TinyUSDZ 0.9.4 x86-64 binary is tagged manylinux
2.27/2.28, so the hosted optional-provider smoke intentionally runs on the
Ubuntu 24.04 wheel host. It is not evidence that the TinyUSDZ binary supports
glibc 2.17. No codec implementation or measured path changed in C7, so the C6
paired-parent row remains the applicable performance control.

The C7 three-lens review is green after one test-soundness correction: the
generic smoke deliberately skips unavailable optional providers, so the hosted
`sceneio[usd]` job now first requires `capabilities("usd").available` rather
than allowing a failed provider import to pass as a skip. The resource/lifetime
lens additionally removes each installed USD/USDZ source and collects garbage
before re-reading the retained rich-scene positions. The format/convention
lens retains exact profile/provider metadata and requires composition refusal.

Exit: the docs claim exactly `sceneio.usd.3dcv/1`, separately report
`current_usdc`, `composition`, and `selected_time` provider flags, and no
document says “full USD.”

### Per-commit documentation checklist

Each C1-C7 commit updates the same small set of sources of truth:

- this implementation plan: checked items, evidence, and next unit;
- `docs/format_coverage.md`: public read/write level, provider, and limits;
- `docs/coverage_roadmap.md`: one-line status only;
- `docs/core_architecture.md`: module/record ownership when architecture
  changes;
- `docs/io_optimization_plan.md` and `bench/BASELINE.md`: only when measured
  behavior changes;
- `LICENSES/README.md` plus an exact license/notice file for any newly used
  implementation or fixture;
- capability and repository-organization snapshots when their exact contents
  change.

Do not create parallel USD roadmaps. This file is the single detailed
implementation checklist; the coverage documents summarize it.

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
