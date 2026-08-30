# USD provider qualification

Status: provider matrix and FC6 selected-time state B complete locally and in
the SceneIO 0.3.0 release gate
Date: 2026-08-29
Local provider: TinyUSDZ 0.9.4
Standards pins: AOUSD Core 1.0.1 `2f9e746c4fbd`, supplemental
1.0.1.post0 `c15ae0cad3ed` (tag object `404e2bde49c1`), OpenUSD 26.08
`ee47c679abde`

This report records observed provider behavior used to choose the implementation
boundary for `sceneio.usd.3dcv/1`. It is evidence, not a broader capability
claim. The target profile and phase checklist are in
[`usd_3d_cv_implementation_plan.md`](usd_3d_cv_implementation_plan.md).

## Local probe results

| Behavior | Result | Consequence |
|---|---|---|
| USDA load and save | qualified by existing mesh cross-reads | retain TinyUSDZ path parser and repository-owned writer |
| `.usd` forwarding | TinyUSDZ detects USDA content through a `.usd` path; repository save selects USDA | retain existing deterministic ASCII compatibility default |
| USDC crate 10 load | the pinned AOUSD 1.0.1 fixture loads and exposes all sample times, but its Python values are invalid placeholders | qualify only static values that the binding exposes exactly; selected-time reads need another implementation |
| USDC crate 11/12 load | official AOUSD relocation/spline probes terminate a fresh TinyUSDZ process | SceneIO refuses crate versions above 10 before provider dispatch |
| USDC save | emits crate 0.8 in the local probe | do not expose as a qualified writer yet |
| USDZ load/save | supported; current SceneIO writer independently checks stored/aligned layout | retain repository-owned package writer |
| unknown typed prim | preserved as a generic `Prim` with typed attributes | sufficient for direct schema mapping without generated provider bindings |
| `ParticleField3DGaussianSplat` | all required OpenUSD 26.08 attributes parse | use direct typed-attribute extraction |
| `quatf[]` NumPy view | exposed as XYZW | reorder explicitly to SceneIO WXYZ |
| asset values | authored asset attributes parse, but the Python value is an invalid placeholder even when the target exists | inspect the authored dependency separately; do not claim provider asset resolution |
| sublayers | arc parses, but `load()` does not populate referenced prims | inspect and refuse in profile v1 |
| references | arc parses, but referenced children are not populated | inspect and refuse in profile v1 |
| payloads | arc parses, but payload children are not populated | inspect and refuse in profile v1 |
| variants | definitions and selection parse, but selected children are not populated | inspect and refuse in profile v1 |
| inherits/specializes | provider evaluation is not qualified | inspect and refuse in profile v1 |
| USDA matrix samples | sample times enumerate but values are invalid placeholders | repository-owned bounded parser evaluates only direct `matrix4d xformOp:transform.timeSamples` |
| USDA visibility samples | Python binding exposes neither typed values nor sample times | the same bounded parser evaluates only inherited/invisible held tokens |
| USDA-root USDZ samples | root text has the same provider-normalized direct representation | qualify the same selected-time subset after USDZ layout validation |
| selected-time interpolation | TinyUSDZ has no typed evaluation route | match exact/between/endpoints to test-only OpenUSD 26.8; keep USDC excluded |

The composition probes use one external layer with a mesh and separate root
layers containing a sublayer, reference, payload, or two-choice variant. Direct
`tinyusdz.load()` traversal returns only locally authored prims. The asset
probe likewise retains the authored property shell but not a usable Python
asset value. SceneIO must not describe that raw traversal as a
composed/evaluated or asset-resolving stage.

## Pinned fixture inventory

| Fixture | Source | License | SHA-256 | Result |
|---|---|---|---|---|
| crate-10 time samples | AOUSD supplemental `1.0.1.post0`, peeled commit `c15ae0cad3ed`, `releases/1.0.1/file_formats/tests/assets/binary/gen_timesamples.usdc` | Apache-2.0 | `0155f5e4e9b8839a685728131c6c35d32981fcc74b8cb23cb8abead8a49cd420` | container and 11 sample times parse; values are unavailable |
| crate-11 relocates probe | same release, `releases/1.0.1/file_formats/tests/assets/binary/gen_relocates.usdc` | Apache-2.0 | `3f5824329d66961af9e3f85c4a75f4a22d64842291501813b8324bd1b2518e38` | fresh TinyUSDZ process terminates; not dispatched by SceneIO |
| crate-12 splines probe | same release, `releases/1.0.1/file_formats/tests/assets/binary/gen_splines.usdc` | Apache-2.0 | `597487f35c26525f0cedec4cc6f18106d56e40706cf2d2e962e48ea3509ea1e5` | fresh TinyUSDZ process terminates; not dispatched by SceneIO |

The crate-10 bytes are base64-embedded without modification in
`tests/test_usd_provider_qualification.py`. Distribution attribution is in
`LICENSES/aousd-core-spec-supplemental.txt`; the complete Apache-2.0 terms are
the repository-root `LICENSE`. The crate-11/12 rows are pinned reproducible
external probes and are not copied into the repository.

## Selected boundary

TinyUSDZ remains the cross-platform raw USDA and bounded historical-USDC/USDZ
parser. Its qualified USDC ceiling is crate version 10, and that ceiling does
not imply that every crate-10 value type is usable. SceneIO owns:

- the accepted schema vocabulary and validation;
- conversion from provider values to compiled records;
- stage metadata and dependency inspection;
- deterministic USDA and USDZ serialization;
- bounded selected-time parsing/evaluation for direct USDA matrix and
  visibility sample tables;
- explicit inspection and refusal of unevaluated composition/value-resolution
  behavior.

USDC writing and current crate 11-15 reading stay unavailable until output and
input are accepted by an approved current OpenUSD reference and the AOUSD
format checks. A provider self-round-trip does not qualify either direction.

OpenUSD 26.08 remains a separately installed, test-only standards oracle under
the repository's recorded TOST policy. The focused workflow installs
`usd-core==26.8` only for executable cross-checks; `pxr` is never imported by
ordinary SceneIO code, is not a runtime dependency, and is not bundled in the
abi3 wheel. This oracle role does not change TinyUSDZ's runtime boundary.

## Provider closure evidence

- [x] Explicit TOST outcome and test-only oracle role recorded in the source
      catalog/license policy; no runtime or bundled use.
- [x] AOUSD Core 1.0.1 plus supplemental 1.0.1.post0 license and fixture
      inventory.
- [x] Current USDC comparison branch closed as unavailable for profile v1;
      current reads and all USDC writes remain refused.
- [x] Generated TinyUSDZ/repository-writer performance and peak-RSS comparison
      in `bench/BASELINE.md`.
- [x] Linux/macOS/Windows TinyUSDZ optional-provider package run
      `30703473199` at implementation source `47eb2e1`; publication skipped.
- [x] Final correction source `b16ee1c` passes compiler run `30705438179` and
      CI `30705438186`, including the 67-row five-run allocation guard.
- [x] FC6 state-B grammar and limits frozen in
      `tests/contracts/usd_selected_time_v1.toml`; direct USDA and USDA-root
      USDZ exact/between/endpoint values match OpenUSD 26.8.
- [x] Selected-time scale evidence retained in
      `docs/usd_animation_benchmark.md`; preservation/write are marked not
      applicable rather than inferred from value materialization.

Public capability metadata and every USD-family inspection now report
`current_usdc` and `composition` as unavailable and `selected_time` as
available for the named direct-USDA subset. Inspection records the selected
profile, representation support, property list, sample count, and time range.
It still reports authored samples as not preservable when no `time` is given.
Dynamic writing, USDC selected time, composition, arbitrary sampled xform
stacks, and sampled payloads remain explicit unsupported features.
