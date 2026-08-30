# Oracle validation and normalization qualification plan

Status: complete locally and hosted, 2026-08-04. Build-only Release run
[`30914739031`](https://github.com/SceneAPI/SceneIO/actions/runs/30914739031)
validated exact commit `50172b5eeb6f3df2d642c80e3fbff43850000d3f` across the
three wheel targets and both focused oracle lanes. PyPI publication was
skipped in that qualification run; the accumulated validated profile later
shipped in SceneIO 0.3.0.

The completed 2026-08-29 G1 follow-on in the
[`archived remaining-gap implementation plan`](plans/completed/remaining_gap_implementation_plan_2026-08-29.md)
supersedes only this historical unit's deliberately unrepresented Gaussian
field boundary. Its original validation evidence remains unchanged.

## Outcome

SceneIO already has a directional oracle ledger for all 74 built-in formats:
74 readable formats, 73 writable formats, and RTMV as the only declared
read-only format. This unit strengthens that evidence without expanding the
runtime dependency surface or reopening completed format coverage.

The closure target is:

1. every oracle claim names a pinned upstream project or an independently
   implemented specification parser;
2. conversion and normalization claims use an implementation independent from
   the SceneIO code under test;
3. related forks or shared implementations count as one oracle lineage;
4. official SPZ and OpenUSD implementations execute against SceneIO outputs
   and produce inputs SceneIO reads; and
5. any mismatch found by those checks is either corrected with a regression
   test or recorded as an explicit, bounded unsupported profile.

The final semantic refinement also distinguishes represented operations from
universal claims. SciPy independently checks Gaussian quaternion rotations and
opacity activation; scalar math checks scale activation; an index-addressed
oracle checks SH storage permutation for every supported degree. The G1
follow-on adds explicit quaternion-state, SH-basis/phase/layout, color-space,
coordinate-frame, source-precision, and rendering-hint fields to
`GaussianCloud`; carriers either populate their qualified values or preserve
an explicit `unknown`, and unsupported conversions refuse.

This is a finite qualification unit. It does not add new file formats, make
OpenUSD or Niantic SPZ runtime dependencies, or require every reference
application to run in the normal test suite.

## Dependency and license boundary

NumPy remains the sole base runtime dependency. External implementations are
assigned one of four distribution roles:

| Role | Permitted use |
|---|---|
| `runtime_required` | The repository's declared base dependency; currently NumPy only |
| `runtime_optional` | Separately installed provider behind a named extra; never copied into the base wheel |
| `test_executable` | Installed only in a focused local or hosted test environment |
| `generated_vector` | Upstream executable produces a small attributed fixture; its runtime is not distributed |
| `reference_only` | Specification or implementation is inspected, but no code is copied, imported, linked, or distributed |

MIT, BSD, Apache-2.0, ISC, zlib, BSL-1.0, MPL-2.0, TOST-1.0, and comparable
permissive or weak file-level copyleft licenses are eligible. LGPL components
may be separately installed or invoked for tests when the boundary stays
clear. Strong project-wide copyleft implementations remain reference-only or
external command-line comparators; their source is not copied into SceneIO.
Source-available, noncommercial, or research-only terms do not qualify as an
open-source implementation source.

Repository popularity is a maturity signal, not a correctness proof. The
official owner of a format or schema takes precedence over star count. A
popular independent consumer is preferred when several equivalent secondary
oracles exist.

## Versioned source-catalog contract

Add `tests/contracts/oracle_sources_v1.toml`. Each project row must contain:

- stable project id, project name, repository URL, pinned 40-character
  revision, and optional release/distribution version;
- star-count snapshot and snapshot date for selection provenance;
- SPDX license expression, license class, and distribution role;
- authority (`format_owner`, `standards_body`, `independent_implementation`,
  or `semantic_reference`);
- lineage id so correlated implementations cannot be counted twice;
- exact formats, semantic roles, execution mode, and evidence test paths; and
- a qualification state of `executed`, `captured`, `reference`, or `candidate`.

The contract test must reject duplicate ids, malformed revisions, unknown
licenses/roles, missing evidence paths, and executable claims without a real
test. It must also require every built-in format in
`CANONICAL_BUILTIN_IDS` to retain directional evidence in
`io_oracles_v1.toml`.

The first catalog covers these high-value upstream families:

| Domain | Primary upstream sources | Qualification role |
|---|---|---|
| COLMAP sparse/database/dense and camera conventions | COLMAP, pycolmap, CamTools | executable plus semantic reference |
| Bundler/BAL/NVM/OpenMVG | RootBA, OpenMVG, AliceVision | executable where already practical; otherwise pinned reference |
| TUM/KITTI/EuRoC/Kalibr/g2o | evo or a permissive trajectory implementation, pykitti, Kalibr, g2o core | independent matrix/layout evidence; mixed-license repositories are scoped to eligible components |
| features/matches/pairs/tracks | HLoc and COLMAP | executable layout evidence |
| point clouds and meshes | Open3D, PCL, PDAL, trimesh, Khronos glTF Validator | existing executable consumers plus pinned standards references |
| Gaussian PLY/SPZ/SPLAT/KSplat/SOG | Niantic SPZ, SplatTransform, gsply, GaussianSplats3D | official and independent executable evidence with lineage separation |
| Gaussian USD and semantic normalization | OpenUSD, Khronos `KHR_gaussian_splatting`, NVIDIA 3DGRUT/NCore, gsplat, Brush | OpenUSD executable; others standards/semantic references unless a lightweight executable lane is justified |
| arrays, scientific containers, images, and sequences | NumPy, HDF5/h5py, Zarr, Arrow, OpenEXR, Pillow, tifffile and existing native providers | retain the existing direct cross-read/write evidence |

## Executable oracle specifications

### Official Niantic SPZ

- Pin one Niantic SPZ revision and record its MIT notice.
- Build/install it only in a focused oracle environment.
- For supported SH degrees, check official writer -> SceneIO reader for v2,
  v3, and v4, and SceneIO writer -> official reader for the writable v3 and
  v4 profiles.
- Compare positions, scales, rotations, opacity, DC color, higher-order SH,
  point count, degree, and version using tolerances derived from SPZ's declared
  quantization. Quaternion comparison is sign-invariant.
- Exercise asymmetric values so XYZW/WXYZ swaps and SH channel/order mistakes
  cannot pass.
- Check the official v4 default coordinate declaration. Until SceneIO stores
  and converts all named SPZ axis families, it must not claim those conversions.
  Unsupported extension profiles are refused or explicitly classified; they
  are never silently relabeled.

### Official OpenUSD

- Pin an OpenUSD `usd-core` release/revision and record its TOST-1.0 notice.
- Install `usd-core` only in a focused oracle environment.
- Open SceneIO-written USDA/USDZ with `pxr.Usd` and verify stage metadata,
  prim types, Gaussian property names/types, array lengths, quaternion order,
  scale/opacity domains, SH coefficient order, source precision, and authored
  rendering hints.
- Author a minimal stage with the official API and require SceneIO to read the
  same semantics. Keep USDC writing and unimplemented composition behavior out
  of scope.
- Compare quaternion orientation sign-invariantly and require unit length for
  schema profiles that mandate unit quaternions.

### Mathematical conversion oracle

- Use a permissively licensed, separately installed rotation implementation
  such as SciPy for randomized quaternion/matrix composition and inversion.
- Cover WXYZ/XYZW, W2C/C2W, OpenCV/OpenGL, ENU/NED, unit scaling, points,
  vectors, normals, and similarity-only scalar widths.
- Use asymmetric rotations/translations and compare both the forward result
  and inverse round trip. Expected values must not call SceneIO conversion
  helpers.

## Implementation packets

### L1 — source catalog, license policy, and mathematical oracle

Owned files: the new source catalog and its contract test, license-policy
documentation/notices, and a standalone mathematical-oracle test. Do not edit
the SPZ or USD codec suites.

Acceptance:

- catalog and policy tests pass;
- every external source has an explicit lineage and role;
- current restrictive OpenUSD wording is replaced by the approved TOST/MPL/BSL
  policy; and
- the mathematical test catches deliberate quaternion-order, pose-direction,
  and basis-change mutations.

### L2 — official OpenUSD executable oracle

Owned files: a standalone OpenUSD oracle suite and the focused hosted-test
workflow wiring. Only touch USD implementation files if the upstream oracle
demonstrates a mismatch. Do not change the source catalog structure.

Acceptance:

- both cross-read directions execute when `pxr` is installed;
- the normal NumPy-only installation imports without `pxr`;
- absent optional oracle tooling produces a documented skip, not false pass;
  and
- any behavior correction has a minimal regression test.

### L3 — official Niantic SPZ executable oracle

Owned files: a standalone Niantic SPZ oracle suite and focused hosted-test
workflow wiring. Only touch SPZ/Gaussian implementation files when required by
an observed mismatch. Do not change the source catalog structure.

Acceptance:

- both cross-read directions execute against the pinned official library;
- comparisons cover every SceneIO-supported SH degree and both legacy/current
  containers where the official library supports them;
- coordinate behavior is stated precisely; and
- the existing gsply and SplatTransform evidence remains green.

## Integration and validation checklist

- [x] Preserve and verify the inherited coordinate/Gaussian hardening changes.
- [x] Add and contract-test `oracle_sources_v1.toml`.
- [x] Update the license inventory for newly executed or captured sources.
- [x] Add the independent mathematical conversion suite.
- [x] Add official OpenUSD cross-read/write tests.
- [x] Extend the official OpenUSD lane with bounded USDA/USDZ selected-time
      matrix/visibility evaluation for FC6 state B.
- [x] Add official Niantic SPZ v2/v3/v4 read and v3/v4 write tests.
- [x] Lock the PlayCanvas test-only npm closure and execute all ten external
      reader/writer cases from that lock.
- [x] Add executable Gaussian operation oracles while retaining explicit
      negative contracts for the four unrepresented universal semantics.
- [x] Pin RTMV's XYZW-to-WXYZ quaternion interpretation and preserve its
      read-only, whole-dataset-conversion refusal.
- [x] Run the existing per-codec oracle suites for every touched format.
- [x] Rebuild the editable extension after every C++ change.
- [x] Run the focused contract/oracle tests, full pytest suite, and Ruff.
- [x] Run `git diff --check` and the installed public-surface smoke.
- [x] Run the affected benchmark row and
      confirm no throughput or allocation regression.
- [x] Perform the required three-lens review: lifetime/ownership,
      conversion/normalization correctness, and test independence/soundness.
- [x] Update `format_coverage.md`, `coordinate_conventions.md`, this plan, and
      the active checklist with measured results rather than forecasts.
- [x] Prepare the green unit for a commit with the required co-author trailer.
- [x] Push and execute the hosted workflows only with separate user approval.

## Validation record

- Editable MSVC build completed with `uv pip install -e ".[dev,test]"`; the
  installed `_core` exposes the SPZ and SPLAT read/write symbols.
- The exact local collection is 4,599 nodes with sorted normalized SHA-256
  `67c8abc6c66b676d27dd7263e4fd48e87bcaa57fea5f00ee73586c9652d7cb7f`.
  The complete post-correction run passes 4,583 tests with 17 documented
  skips. The focused touched-format/oracle gate passes 292 tests with two
  expected optional-provider skips.
- OpenUSD `usd-core==26.8` executes the original four Gaussian USDA/USDZ
  cross-read tests plus 22 FC6 selected-time authored/evaluation cases locally.
  Its v26.08 Git revision is recorded as source-release provenance because the
  wheel exposes its distribution version, not a Git SHA. A Luna environment
  built the pinned Niantic SPZ 3.0.0 source and passed 51 official-provider
  cases with one unrelated gsply-v2 writer skip.
- The locked PlayCanvas 3.1.6 closure installs with `npm ci`, reports gitHead
  `04b6d15`, and passes all ten SplatTransform cross-implementation cases.
  The focused Gaussian/RTMV/contract/documentation gate passes 128 tests. The
  complete local suite passes 4,648 tests with 16 documented optional/platform
  skips; no runtime or C++ implementation changed in this refinement.
- The three review lenses found and corrected bounded SPZ decode allocation,
  uint32 point-count narrowing, non-representable SPLAT scales, and SPZ
  inspect/read header-profile disagreement. The final lifetime, mathematical,
  and evidence audits report no remaining implementation mismatch.
- A five-run `--scale 0.1 --only spz` benchmark records 582 MB/s legacy-v3
  read, 1,655 MB/s v4 read, 555 MB/s public path read, and 111 MB/s write on a
  1.1 MB raw payload. Direct-to-final-buffer inflate improves the first bounded
  implementation's 574 MB/s legacy result while retaining identical valid
  output and the new decoded-size limits.
- Ruff, `uv pip check`, `git diff --check`, the documentation/contracts, and
  `python -m sceneio._wheel_smoke` are clean; the smoke returns `2`.
- User-authorized build-only Release run
  [`30914739031`](https://github.com/SceneAPI/SceneIO/actions/runs/30914739031)
  passed the exact source-distribution closure, manylinux2014 GCC 10 x86-64,
  Windows MSVC AMD64, macOS AppleClang ARM64, combined distribution inventory,
  OpenUSD 26.08 USDA/USDZ oracle, and official Niantic SPZ oracle jobs. Each
  wheel ran the manifest-driven 74-format installed smoke; the host smoke also
  installed the USD, AVIF, NCore, and TIFF extras. The tag-only PyPI job was
  skipped, so no package was published.
- Compiler-instrumented run
  [`30914599398`](https://github.com/SceneAPI/SceneIO/actions/runs/30914599398)
  passed the exact provider-independent collection and full instrumented suite
  plus the isolated native-lifetime shard at the same commit.
- The preceding run `30913751835` isolated the Niantic provider-build failure
  to Ubuntu CMake selecting a non-PIC system `libzstd.a`. Commit `50172b5`
  scopes `CMAKE_DISABLE_FIND_PACKAGE_zstd=ON` to that external build so the
  pinned SPZ project uses its SHA-verified, PIC-enabled zstd fallback. A clean
  Ubuntu 24.04 container build passed before the successful replacement run;
  SceneIO's runtime and vendored-source set were unchanged.

## Closure rule

This unit is complete when the catalog and all three executable oracle suites
are green locally where their providers are available, their hosted lanes are
prepared, the normal full suite and lint pass, and every discovered mismatch
is either fixed or represented by an explicit unsupported-profile test. A
candidate project is not a blocker merely because it is too heavy to run in
normal CI; it remains a pinned reference until a concrete coverage gap requires
promotion.
