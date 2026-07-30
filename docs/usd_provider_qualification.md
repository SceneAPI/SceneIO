# USD provider qualification

Status: provisional U0 evidence  
Date: 2026-07-30  
Local provider: TinyUSDZ 0.9.4

This report records observed provider behavior used to choose the implementation
boundary for `sceneio.usd.3dcv/1`. It is evidence, not a broader capability
claim. The target profile and phase checklist are in
[`usd_3d_cv_implementation_plan.md`](usd_3d_cv_implementation_plan.md).

## Local probe results

| Behavior | Result | Consequence |
|---|---|---|
| USDA load and save | qualified by existing mesh cross-reads | retain TinyUSDZ path parser and repository-owned writer |
| `.usd` save | provider selects USDA | retain existing deterministic ASCII compatibility default |
| USDC load | supported for the existing upstream-written fixture | add `.usdc` routing only after a current-crate fixture is added |
| USDC save | emits crate 0.8 in the local probe | do not expose as a qualified writer yet |
| USDZ load/save | supported; current SceneIO writer independently checks stored/aligned layout | retain repository-owned package writer |
| unknown typed prim | preserved as a generic `Prim` with typed attributes | sufficient for direct schema mapping without generated provider bindings |
| `ParticleField3DGaussianSplat` | all required OpenUSD 26.08 attributes parse | use direct typed-attribute extraction |
| `quatf[]` NumPy view | exposed as XYZW | reorder explicitly to SceneIO WXYZ |
| sublayers | arc parses, but `load()` does not populate referenced prims | not an evaluated-stage provider |
| references | arc parses, but referenced children are not populated | implement/qualify separately in U6 |
| payloads | arc parses, but payload children are not populated | implement/qualify separately in U6 |
| variants | definitions and selection parse, but selected children are not populated | implement/qualify separately in U6 |

The composition probes use one external layer with a mesh and separate root
layers containing a sublayer, reference, payload, or two-choice variant. Direct
`tinyusdz.load()` traversal returns only locally authored prims. SceneIO must
not describe that raw traversal as a composed/evaluated stage.

## Selected boundary

TinyUSDZ remains the cross-platform raw USDA/USDC/USDZ parser. SceneIO owns:

- the accepted schema vocabulary and validation;
- conversion from provider values to compiled records;
- stage metadata and dependency inspection;
- deterministic USDA and USDZ serialization;
- explicit composition/value-resolution behavior that later passes the AOUSD
  comparison cases.

USDC writing stays unavailable until output is accepted by the current
OpenUSD reference and the AOUSD format checks. A provider self-round-trip does
not qualify it.

OpenUSD 26.08 remains a standards reference until the narrow TOST policy
decision in U0. No OpenUSD package or library was added by this qualification
unit.

## Remaining U0 evidence

- [ ] Explicit TOST policy decision.
- [ ] AOUSD Core 1.0 compliance sample license and fixture inventory.
- [ ] OpenUSD 26.08 current crate read/write comparison.
- [ ] Generated performance and peak-RSS comparison.
- [ ] Linux/macOS/Windows optional-provider package run.

The first four are prerequisites for claiming USDC writing or evaluated
composition. They do not block additive SceneIO records or direct official
Gaussian-schema work.
