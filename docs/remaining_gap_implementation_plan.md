# Remaining-gap implementation plan

- **Status:** G1 and FC4-FC6 are validated as of 2026-08-29. Exact
  implementation candidate `9a20bc61f177c28ba228b89e80cff665e3f1b426`
  passed the complete nonpublishing Release, CI, and sanitizer matrices. FC7's
  technical and evidence gates are closed; only disposition of the existing
  draft PR remains a user review decision.
- **Baseline:** SceneIO 0.2.0 has 74 built-in formats; 74 read and inspect,
  73 write, and 37 expose 43 bounded selectors. FC0-FC6 are locally complete
  or evidence-backed excluded within their frozen profiles.
- **Purpose:** close the remaining qualified 3D-CV gaps without expanding
  SceneIO into a general scientific, media, or scene-authoring framework.
- **Authority:** current capabilities remain defined by
  [`format_coverage.md`](format_coverage.md). The detailed acceptance rules in
  [`remaining_3dcv_profile_checklist.md`](remaining_3dcv_profile_checklist.md)
  remain normative. This document is the ordered execution view.

## 1. Target outcome

The remaining program is complete only when all of the following are true:

1. The FC3 E57 head has exact-commit Linux, macOS, and Windows installed-wheel
   evidence.
2. Gaussian metadata either represents and converts the currently unqualified
   quaternion, spherical-harmonic, color, and coordinate semantics, or each
   source format has a tested explicit `unknown`/refusal state.
3. FC4 closes the bounded TIFF collection/pyramid profile while preserving the
   current simple-TIFF return types.
4. FC5 ends in one explicit state: qualified OpenVDB multi-grid read/select,
   a qualified provider replacement, or a documented evidence-backed
   exclusion. The current one-grid writer must remain compatible.
5. FC6 qualifies selected-time USD behavior through the existing
   `read_scene(..., time=...)` API. `SceneAnimation` and dynamic writing ship
   only if authored samples can be preserved and independently cross-read in
   both directions.
6. FC7 passes the full local, benchmark, distribution, installed-wheel, and
   hosted-oracle gates and reconciles every capability/documentation row.
7. The registry still contains exactly 74 built-ins, the base dependency stays
   NumPy-only, normal tests remain offline, and every unsupported direction has
   a stable tested refusal.

“Excluded with evidence” is a valid closed result. “Pending”, post-decode
selection advertised as bounded, or a record that silently drops source
semantics is not.

## 2. Gap inventory and order

| ID | Gap | Current state | Required close state | Relative size |
|---|---|---|---|---:|
| V0 | FC3 package evidence | Complete at exact commit `3fcdf8195e8909e3e1cc2a6091a237f89af3bc41` in nonpublishing Release run `33231962034` | Exact-head source archive and three installed wheels pass | complete |
| G1 | Gaussian semantic normalization | Validated 2026-08-29: universal fields, carrier mappings, conversions/refusals, official oracles, and installed-wheel semantics pass | Versioned per-format semantics, compatible record fields, explicit conversion/refusal, and independent oracles | complete |
| FC4 | TIFF series and pyramids | Validated: neutral collections, bounded selectors, the qualified writer subset, provider oracle, benchmark, and Linux/macOS/Windows write/reopen smoke pass | Neutral collection records plus bounded inspect/read/select and the provider-proven writable subset | complete |
| FC5 | OpenVDB expansion | Closed by evidence-backed exclusion: TinyVDB cannot qualify multi-grid enumeration, selection, or writing; the retained one-grid profile is hardened and hosted-wheel green | Multi-grid metadata/read/exact selection for proven types, or evidence-backed exclusion | excluded |
| FC6 | Dynamic USD | Validated in state B: bounded selected-time direct USDA and USDA-root USDZ matrix/visibility evaluation passes the official OpenUSD lane; preservation and dynamic writing are excluded | Qualified selected-time read, and conditional authored-sample preservation/write | complete |
| FC7 | Aggregate closure | Exact candidate passes local contracts, the 5,082-test suite, strict benchmark, exact source closure, three installed wheels, hosted oracles, CI, and sanitizers | Exact-head local/package/hosted evidence and reconciled docs | technical complete; draft disposition pending |

### Dependency graph

```text
V0 exact-head FC3 package validation
  |
  +-- recommended merge/review checkpoint for existing draft PR

G1 Gaussian semantic contract -------------------+
                                                   |
FC4 TIFF collections -----------------------------+-- FC7 aggregate closure
                                                   |
FC5 OpenVDB decision/implementation --> FC6 USD --+
```

FC4 can proceed independently after V0. G1 must finish before FC6 makes new
claims about animated Gaussian-bearing scenes. FC5 must at least reach its
explicit provider decision before FC6 finalizes volume-grid selection.

## 3. Rules applying to every work package

### 3.1 Compatibility

- Preserve existing positional constructor calls, defaults, properties, return
  types, byte output where deterministic, and generic `sceneio.read` behavior.
- Add record metadata as keyword-only fields with truthful legacy defaults.
- Add collection/specialized selectors to typed APIs first. Do not widen
  global `read_partial` until a selector is unambiguous across the format and
  has a measured bounded implementation.
- Never infer semantic labels, coordinate frames, units, color spaces, or SH
  conventions from observed numeric values.
- Conversion remains explicit. Writers either encode all represented fields or
  reject before touching the destination.

### 3.2 Provider qualification

- Probe the installed provider with tiny generated files before adding public
  types or flags.
- Separate metadata enumeration, payload decode, selected decode, and write
  capability; success in one does not imply another.
- Prove bounded selection through provider calls, allocation/RSS evidence, and
  a trap that fails if the full payload is requested.
- A provider change must pass the existing dependency-intake, license,
  packaging, wheel-availability, and benchmark process. Do not add full
  OpenVDB/Boost/TBB or OpenUSD to release wheels merely to satisfy a checklist.

### 3.3 Evidence

Each supported direction requires:

- independent producer -> SceneIO reader parity;
- SceneIO writer -> independent consumer parity;
- malformed, truncated, unsupported-profile, empty, singleton, and large
  cases;
- ownership after provider/file closure and transactional failure behavior;
- public `detect -> inspect -> read` and `write -> detect -> inspect -> read`;
- exact equality or a named tolerance for every represented field;
- capability, public-surface, coordinate, representation, fixture, oracle,
  license, distribution, and installed-wheel contract updates.

Self-round-trip is useful but never sufficient as the only correctness oracle.

### 3.4 Commit and review boundaries

- Land provider probes and contract decisions before public API code.
- Keep record/API commits adjacent to their first codec consumer.
- Keep fixtures/oracles, implementation, benchmarks, and documentation in
  reviewable slices; do not mix repository moves or unrelated optimization.
- End each slice green under its focused tests, Ruff, and `git diff --check`.
- Record the three review lenses for each unit: ownership/lifetime, behavior
  correctness, and test soundness.

## 4. V0 — qualify and checkpoint FC3

### 4.1 Local preflight

- [x] Confirm the candidate branch and remote both resolve to `3fcdf81`, or
      deliberately update this plan to the new exact candidate SHA.
- [x] Rebuild the editable native extension from that tree:

  ```powershell
  uv pip install -e ".[dev,test]"
  ```

- [x] Run the complete local gate:

  ```powershell
  .venv/Scripts/python.exe -m pytest -q
  .venv/Scripts/python.exe -m ruff check .
  .venv/Scripts/python.exe tools/documentation_contract.py
  git diff --check
  .venv/Scripts/python.exe bench/bench_io.py --runs 5 --strict-oracles --require-o4-gains --require-o5-inspect-gains --require-o5-partial-gains
  ```

- [x] Confirm the E57 focused suites, generated 113.25 MB logical fixture,
      selected-range equality, and allocation/RSS evidence are still green.

### 4.2 Exact-head package gate

- [x] With explicit authorization, trigger the nonpublishing Release workflow:

  ```powershell
  gh workflow run publish.yml --ref phase0-nanobind-core
  ```

- [x] Require one source archive and Linux, macOS, and Windows cp312-abi3
      wheels built from the same source archive.
- [x] Require base NumPy-only import, optional `sceneio[e57]` installation,
      manifest-driven installed smoke, source/wheel inventory, license checks,
      and exact artifact hashes.
- [x] Record the run URL, candidate SHA, source hash, wheel hashes, platform
      results, and documented skips in the finite checklist and coverage docs.

### 4.3 Checkpoint decision

The current draft PR is already very large. After V0 passes, the recommended
path is to mark the FC0-FC3 PR ready and merge it without rewriting its history,
then deliver G1, FC4, FC5, FC6, and FC7 as separate review units. If the PR must
remain open, do not combine the remaining implementations into one commit.

**V0 exit:** the FC3 row says hosted-wheel complete at an exact run, or contains
a concrete platform failure assigned to a focused correction commit.

**Completed 2026-08-29:** exact commit
`3fcdf8195e8909e3e1cc2a6091a237f89af3bc41` passed the 64-test focused FC3
gate, the complete local suite (4,962 passed, 16 skipped), repository lint and
documentation checks, and the retained five-run strict benchmark at
`build/v0-benchmark-3fcdf81.json`. Nonpublishing Release run
[`33231962034`](https://github.com/SceneAPI/SceneIO/actions/runs/33231962034)
passed the exact sdist, Linux/macOS/Windows wheels, combined inventory,
OpenUSD, and Niantic SPZ jobs; publishing was intentionally skipped. Artifact
hashes are emitted and verified by the run's inventory artifacts.

## 5. G1 — universal Gaussian semantic normalization

This is independent of the FC4-FC6 matrix but closes the remaining global
normalization caveat and must precede new USD animation claims.

### 5.1 Audit and freeze before code

- [x] Add `tests/contracts/gaussian_semantics_v1.toml` with one row for
      `gaussian_ply`, `compressed_ply`, `sog`, `ksplat`, `spz`, `splat`, and
      USD Gaussian payloads.
- [x] For each row, identify authoritative evidence for:
  - quaternion component order and whether magnitude is semantically required
    to be unit, normalized by the consumer, or merely stored;
  - real SH basis normalization, phase/sign convention, `(l,m)` coefficient
    order, channel packing, DC/color activation, and supported degrees;
  - linear/display color space and transfer function;
  - mean/rotation coordinate frame, handedness, axis directions, scale source,
    and meters-per-unit availability;
  - lossy quantization and whether an inverse is exact, approximate, or
    impossible.
- [x] Use official implementations/specifications plus hand-computable degree
      0/1 basis vectors and asymmetric rotations. Do not derive a format's
      semantics only from another SceneIO codec.
- [x] Freeze closed enum vocabularies only after every format row can map to a
      value or explicit `unknown`.

### 5.2 Compatible record extension

Primary files:

- `src/cpp/records/gaussian_cloud.hpp`
- `src/cpp/records/gaussian_cloud.cpp`
- `src/sceneio/representations.py`
- `src/sceneio/coordinates.py`
- `src/sceneio/__init__.py`
- `tests/records/test_gaussian_cloud_conventions.py`
- `tests/records/test_gaussian_semantic_oracles.py`

Candidate keyword-only metadata, with final names/vocabulary owned by the
contract audit:

- quaternion normalization state;
- SH basis, phase, and coefficient order, separate from memory `sh_layout`;
- SH/color transfer space;
- coordinate frame/convention and scale-to-meters source.

Implementation requirements:

- [x] Append keyword-only factory parameters; retain all existing defaults and
      positional calls.
- [x] Validate known enum values and field combinations without forcing an
      implicit normalization or color/coordinate conversion.
- [x] Keep legacy records truthful: use explicit `unknown` where historical
      data lacks evidence rather than assigning a canonical convention.
- [x] Extend `convert_gaussian_conventions` only for mathematically qualified
      conversions. Require caller policy for nonlinear color/SH transforms or
      coordinate changes that cannot be inferred.
- [x] Enable `coordinate_convention`/`convert_coordinates` for a GaussianCloud
      only when its frame and scale metadata are sufficient; otherwise retain
      the current refusal.
- [x] Preserve owner-retaining NumPy/DLPack views and constructor ABI behavior.

### 5.3 Codec mapping and refusal pass

- [x] Map all seven carrier profiles into the new metadata in their readers.
- [x] Make every writer require the exact semantics it emits. It may convert
      only when the caller explicitly requests a qualified conversion.
- [x] Preserve existing encoded bytes when the new metadata equals the legacy
      profile.
- [x] Add format-specific refusal tests for `unknown`, incompatible SH basis,
      unrepresentable color space, and coordinate metadata.
- [x] Update USD Gaussian projection only after the static carrier mapping is
      oracle-proven; do not couple this work to USD animation.

### 5.4 Oracle and performance gates

- [x] Verify quaternion rotations through SciPy matrices, comparing rotations
      rather than quaternion signs.
- [x] Verify SH degree 0/1 evaluations at hand-computable directions and at
      random unit directions against an independent implementation.
- [x] Verify explicit conversion round-trips where lossless and one-way status
      where activation or quantization loses information.
- [x] Re-run all splat codec suites, the official Niantic/SplatTransform lanes,
      USD Gaussian tests, the splat benchmark family, and installed-wheel
      public-surface smoke.

**G1 exit:** no Gaussian carrier relies on an undocumented assumption; each new
semantic property has per-format evidence, explicit conversion/refusal, and a
normalization-contract row.

Local qualification on 2026-08-29 rebuilt the native extension; passed the
289-test focused Gaussian/coordinate/representation slice (one documented
gsply-v2 skip), 185 mmap/stream/partial/inspection tests, 39 public-contract and
documentation tests, all 10 pinned PlayCanvas cases, and the available
Niantic/OpenUSD oracle cases. Repository-wide Ruff and `git diff --check` are
clean. The six-format, five-run result is retained at
`build/g1-gaussian-benchmark.json`; a fresh Windows abi3 wheel passed the
isolated NumPy-only manifest smoke. Cross-platform installed-wheel and oracle
confirmation passed later as part of FC7 Release run `33249900572`.

## 6. FC4 — bounded TIFF collections and pyramids

### 6.1 Provider feasibility packet

Add `tests/test_tiff_provider_qualification.py` before public API work.

- [x] Generate classic TIFF and BigTIFF cases with one/many pages, strips,
      tiles, endian variants, multiple series, SubIFD pyramids, and the pinned
      OME-TIFF 4D source.
- [x] Reproduce and isolate the current wrapped `TiffFrame.tags` failure.
- [x] Record which `tifffile` calls enumerate metadata without decoding sample
      payloads.
- [x] Measure provider granularity for series, level, page range, and tiled
      window reads. A post-decode slice does not qualify.
- [x] Confirm deterministic write/reopen support for the exact qualified
      multi-series and SubIFD layouts on Linux and macOS in the final hosted
      matrix; Windows write/reopen is green. If either hosted provider differs,
      narrow that layout to read/select-only before validation.

### 6.2 Neutral record model

Add `src/sceneio/data/raster.py` and export through
`src/sceneio/data/__init__.py` and `src/sceneio/__init__.py`:

- `RasterLevel`: explicit axes, shape, dtype, payload kind, and an owning
  `Image`, `Mask`, or `TensorDict` payload;
- `RasterSeries`: stable series identity/name and ordered levels;
- `RasterCollection`: ordered independently valid series.

Requirements:

- [x] Immutable Python records with exact shape/dtype/axis validation.
- [x] Limit axes and dtypes to the closed CV vocabulary already accepted by the
      simple TIFF adapter plus explicitly qualified collection cases.
- [x] Reject structured/subarray dtypes, ambiguous OME axes, mixed
      photometric interpretations, and metadata that the record would lose.
- [x] Keep current `Image`, `Mask`, `TensorDict`, and typed label-map results for
      a simple one-series/one-level file.
- [x] Add representation-normalization entries and public API snapshots before
      codec integration.

### 6.3 Typed TIFF collection API

Implement in `src/sceneio/io/_tiff.py` and re-export from
`src/sceneio/io/__init__.py`:

- `read_tiff_collection(...)`;
- `inspect_tiff_collection(...)`;
- `write_tiff_collection(...)` only for the provider-qualified write subset.

Selectors:

- `series_index`;
- `level_index`;
- half-open `page_range`;
- pixel `window=(r0, r1, c0, c1)`.

Requirements:

- [x] Define and test legal selector combinations and exact empty/range error
      behavior.
- [x] Inspect every series/level: axes, shape, dtype, pages, tile/strip layout,
      compression, photometric interpretation, and BigTIFF status without
      decoding samples.
- [x] Decode only the selected provider unit and return owned C-contiguous
      native-endian arrays after file/provider closure.
- [x] Write to a sibling temporary path, reopen with `tifffile`, compare the
      declared topology, and atomically replace the destination.
- [x] Keep arbitrary OME-XML editing and microscopy-specific semantics outside
      the profile.

### 6.4 Tests, fixtures, and benchmark

Add:

- `tests/records/test_raster_collection.py`;
- `tests/codecs/test_tiff_collections.py`;
- `bench/io_bench/tiff_collections.py`;
- `docs/tiff_collection_benchmark.md`;
- a versioned TIFF collection contract under `tests/contracts/`.

Required cases:

- [x] Full/selected equality for series, levels, pages, and windows.
- [x] Tiled selections crossing tile boundaries and stripped selections
      crossing strip boundaries.
- [x] Classic/BigTIFF, both endian orders, one/many pages, empty/singleton
      dimensions, malformed offsets, and unsupported OME axes.
- [x] Existing simple TIFF and dense-label suites remain byte/value compatible.
- [x] A generated 64-128 MiB logical fixture proves selected allocation/RSS is
      materially below full collection decode.
- [x] `tifffile` authors independent input and reopens every supported SceneIO
      output direction.

**FC4 exit:** the OME fixture reads under the bounded profile or fails at a
documented semantic boundary, never due to incidental provider traversal;
simple TIFF remains compatible; supported selectors are measured as bounded;
and write capabilities describe only portable, reopened layouts.

Qualification on 2026-08-29 covers the complete implementation and all three
wheel platforms. The generated provider/codec/record/benchmark slice passes,
the pinned 7,889,559-byte OME-TIFF matches SHA-256
`caf707ca2ba6c42c40ded92245432d350a781fcdd03c0b178834f5eb5e5b96f3` and
now reaches the deliberate `TCZYX` refusal, and the three-run 64 MiB benchmark
shows a 98.65% traced-peak reduction for selected decode. Final Release run
`33249900572` installed the TIFF provider and exercised the exact multi-series,
SubIFD, inspection, selected-window, and write/reopen smoke on macOS arm64,
manylinux x86-64, and Windows amd64.

## 7. FC5 — provider-constrained OpenVDB expansion

### 7.1 Feasibility gate before types

Extend provider qualification without modifying public records:

- [x] Produce official-OpenVDB fixtures containing multiple scalar grids and a
      three-component velocity group, distinct names/classes/backgrounds,
      affine transforms, empty grids, negative coordinates, duplicate names,
      and unsupported tree/value types.
- [x] Record TinyVDB 0.9.0 enumeration/type/metadata behavior for every grid.
- [x] Prove whether reading grid `i` avoids materializing other grid payloads.
- [x] Determine whether transforms/backgrounds/classes survive provider read
      with exact values and whether active coordinates/values are complete.
- [x] Reconfirm that `add_grid` and writable transforms remain unavailable.

At the end of the gate, record exactly one decision:

1. **Current-provider expansion:** TinyVDB qualifies multi-grid metadata/read
   and exact selected-grid decode for a closed type set.
2. **Provider replacement:** a replacement passes dependency intake,
   three-platform wheels, license, size, correctness, and performance gates.
3. **Exclusion (selected 2026-08-29):** multi-grid/vector/transformed support remains unsupported,
   with fixtures and provider observations retained as executable evidence.

Decision 3 is recorded in
`tests/contracts/openvdb_provider_limits_v1.toml`. TinyVDB exposes only
all-grid `read_grids()`, loses official vector payloads and empty-grid
transforms, has no `add_grid`, and exposes a read-only transform. `SparseGrid`
and `SparseVolumeSet` therefore remain deliberately absent.

### 7.2 Conditional record and API implementation

This conditional section was not activated because the gate selected
exclusion. If a future provider passes, add neutral immutable records in
`src/sceneio/data/sparse.py`:

- `SparseGrid`: name, grid class, value kind, background, tree type,
  float64 `(4,4)` index-to-world matrix, owned int32 active coordinates, and
  owned values for each proven value type;
- `SparseVolumeSet`: ordered uniquely named grids.

Add typed APIs in `src/sceneio/io/_openvdb.py` and the public I/O facade:

- `inspect_openvdb_grids(path)`;
- `read_openvdb_grid(path, *, grid_name=None, grid_index=None, bounds=None)`;
- `read_openvdb_grids(path)` only if aggregate decode is well-defined.

Requirements:

- [x] Do not expose `grid_name`, `grid_index`, or bounds selectors that would
      decode every grid before slicing.
- [x] Do not export an aggregate record while the provider loses candidate
      values and metadata.
- [x] Continue returning the legacy `TensorDict` for the existing nonempty one-grid
      identity scalar profile.
- [x] Keep the existing writer unchanged. `SparseVolumeSet` remains absent;
      multiple
      grids, vector values, or transformed writes with stable feature-specific
      errors until a writer provider qualifies them.
- [x] Make USD volume loading resolve the exact authored grid name and never
      default silently to the first grid.

### 7.3 Evidence and benchmark

- [x] Cross-read official-OpenVDB-authored provider vectors with TinyVDB
      locally; retain the generator for the hosted oracle lane.
- [x] Preserve the current SceneIO one-grid write -> TinyVDB/OpenVDB read
      evidence without relabeling it multi-grid write parity.
- [x] Add malformed/duplicate/empty-transform/nonfinite/unsupported cases and provider
      handle/file-release tests.
- [x] Record that a selected-grid benchmark cannot qualify: the provider has
      no selected-grid operation and a post-decode slice is disallowed.
- [x] Update capabilities to state the exact type/grid/transform and selection
      boundary, including an explicit exclusion if the gate fails.

**FC5 exit:** either multi-grid read and exact selection are oracle-proven for a
closed type set, or the feature is explicitly excluded with executable
provider evidence. The existing one-grid profile remains unchanged in either
case.

FC5 exited through exclusion on 2026-08-29. Official pyopenvdb 10.0.1
authored seven semantic vectors; TinyVDB 0.9.0 enumerated their headers but
exposed all-grid-only decode, vector/bool sparse-decode failure, vector payload
loss, empty-transform loss, duplicate-name ambiguity, no grid addition, and no
writable transform. The legacy nonempty identity scalar suite passes, and
empty grids now refuse before they can be silently relabeled.

## 8. FC6 — bounded dynamic USD

### 8.1 Provider and grammar decision

The current probe shows TinyUSDZ 0.9.4 can enumerate sample times for USDA and
historical USDC but returns untyped sample values. Close that uncertainty first.

- [x] Probe typed authored transform and visibility samples for USDA,
      USDA-root USDZ, and qualified historical USDC.
- [x] Probe selected-time evaluation at exact samples, between samples, and
      held endpoints.
- [x] Retain the qualified TinyUSDZ 0.9.4 pin; no opportunistic provider change
      was used for this unit.
- [x] Because the provider remains untyped, specify a repository-owned parser only
      for directly authored USDA matrix-transform and visibility timeSamples.
      It must use a bounded grammar with token/array/depth limits, not a loose
      regex scan, and must not claim USDC support.
- [x] Compare the selected route with OpenUSD for authored samples and
      evaluation before changing `provider_selected_time`.

Possible close states:

- **A — full dynamic profile:** authored-sample read and deterministic write
  qualify for USDA/USDZ; export `SceneAnimation` and a new profile id.
- **B — selected-time read only:** `read_scene(time=...)` qualifies for a named
  representation subset; animation preservation/writing stays unsupported.
- **C — explicit exclusion:** neither provider nor bounded parser can preserve
  semantics safely; retain current tested refusal and close with evidence.

Only state A activates sections 8.2 and 8.4 writing work.

### 8.2 Conditional `SceneAnimation` record

State B was selected, so this conditional record was deliberately not
activated. `SceneAnimation` remains absent and every validation item below is
not applicable to this close state:

- node-count identity with the owning scene;
- CSR offsets, float64 time codes, and float64 `(4,4)` local transforms;
- independent CSR offsets/times and closed visibility codes;
- stage start/end time and positive `timeCodesPerSecond`.

Attach it optionally to `SceneGraph`; do not duplicate static nodes or payloads.

The state-B parser instead validates finite/unique sample times, exact 4x4
finite matrices, the closed held-token vocabulary, empty/singleton tables, and
negative/fractional time codes without introducing a preservation record.
Static `SceneGraph` construction remains unchanged.

### 8.3 Selected-time read

- [x] Activate the existing `read_scene(path, time=...)` route; do not add a
      competing public method.
- [x] Materialize static node transforms/visibility exactly as OpenUSD does for
      the accepted interpolation/held-token profile.
- [x] Keep topology, mesh/point/Gaussian arrays, camera optics, materials,
      volumes, instances, and semantic payloads static.
- [x] Set `selected_time` only when evaluation actually occurred.
- [x] Keep current refusal for composition, clips, deforming payloads,
      time-varying topology/primvars/camera optics/materials, and any format the
      selected implementation cannot evaluate.

### 8.4 Conditional authored-sample write

State B does not activate authored-sample writing. Capabilities and tests keep
`dynamic_write` and `authored_animation_preservation` unsupported. Writing an
evaluated `SceneGraph` is tested only as an ordinary static snapshot; it emits
no `.timeSamples` declarations. USDC writes, clips, arbitrary sampled xform
stacks, composition, deformation, and sampled non-node properties remain
explicit refusals.

### 8.5 Fixtures, oracle, and benchmark

Add:

- `tests/records/test_scene_animation.py` for state A;
- `tests/codecs/test_usd_animation.py` for states A or B;
- a dynamic USD profile contract under `tests/contracts/`;
- `bench/io_bench/usd_animation.py` and a benchmark evidence document.

Required evidence:

- [x] A tiny permissive USDA stage with two nodes, three nonuniform transform
      samples, visibility changes, and one static Gaussian payload.
- [x] Exact and between-sample comparisons with OpenUSD, including negative and
      fractional time, non-24 rates, endpoints, and malformed samples.
- [x] Authored sample arrays cross-read both directions for state A; not
      applicable to the selected state B.
- [x] Selected-time/full-static equality at every tested time for states A/B.
- [x] Inspection reports time range/properties without decoding static bulk
      payloads.
- [x] Large node/sample tables measure selected-time read, inspect, an
      equal-node static control, allocation, and RSS. Full preservation read
      and authored write are explicitly not applicable to state B.

**FC6 exit:** the repository records state A, B, or C explicitly. It never marks
dynamic write complete based only on selected-time read or sample-time
enumeration.

**Completed 2026-08-29 in state B:** the bounded parser and limits are frozen in
`tests/contracts/usd_selected_time_v1.toml`. The direct USDA and USDA-root USDZ
suites cover 21 local cases; the optional OpenUSD 26.8 oracle covers 22 exact
authored/evaluation cases. The retained 256-node, 6,912-sample three-run
measurement is `build/fc6-usd-animation-benchmark.json` and is summarized in
`docs/usd_animation_benchmark.md`. Dynamic preservation/writing, USDC selected
time, composition, arbitrary sampled xform stacks, and sampled payload values
remain explicitly unsupported.

## 9. FC7 — aggregate qualification and closure

### 9.1 Contract reconciliation

- [x] Update `tests/contracts/core_symbols_v1.txt`, `io_public_v1.json`,
      `io_registry_v1.json`, `io_oracles_v1.toml`,
      `oracle_sources_v1.toml`, `public_fixture_sources_v1.toml`,
      `repository_coverage_v1.toml`, coordinate contracts, representation
      evidence, memory protocols, and native build inventories where affected.
- [x] Keep the canonical built-in id tuple and registry ordering unchanged.
- [x] Regenerate documentation snapshots only after reviewing their semantic
      diff:

  ```powershell
  .venv/Scripts/python.exe tools/documentation_contract.py --write
  git diff -- docs README.md tests/contracts
  ```

- [x] Mark every G1/FC4/FC5/FC6 capability `validated` or `excluded`; leave no
      unexplained pending row.

### 9.2 Local aggregate gate

Run in this order:

```powershell
uv pip install -e ".[dev,test]"
.venv/Scripts/python.exe -m pytest --collect-only -q
.venv/Scripts/python.exe -m pytest -q tests/records/test_gaussian_cloud_conventions.py tests/records/test_gaussian_semantic_oracles.py
.venv/Scripts/python.exe -m pytest -q tests/codecs/test_tiff.py tests/codecs/test_openvdb.py tests/test_usd_provider_qualification.py tests/codecs/test_usd_scene.py
.venv/Scripts/python.exe -m pytest -q tests/test_io_api.py tests/test_io_capabilities.py tests/test_io_partial.py tests/test_io_inspection.py tests/test_io_compatibility_snapshots.py
.venv/Scripts/python.exe -m pytest -q tests/test_distribution_verifier.py tests/test_documentation_consistency.py tests/test_license_inventory.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe tools/documentation_contract.py
git diff --check
.venv/Scripts/python.exe bench/bench_io.py --runs 5 --strict-oracles --require-o4-gains --require-o5-inspect-gains --require-o5-partial-gains
```

Add new focused files to the appropriate command as they land. Do not update
an expected collection count until the final collected node list and skip
reasons have been reviewed.

**Local result (2026-08-29):** the frozen registry assembly contains 5,066
collected nodes. The complete suite passes 5,082 tests with 19 reviewed
optional/platform skips. Repository-wide Ruff, the documentation contract,
the lock check, and `git diff --check` pass. The final retained five-run strict
result is `build/fc7-post-memory-strict-benchmark.json`; after restoring the static-stage
inspection fast path, USD/USDZ inspection peaks at 5.7 MB versus 8.5 MB for a
full read and every O4/O5 directional guard passes.

The universal large-profile gate additionally retains a 64 MiB TIFF
collection and a 65.89 MiB USD selected-time layer. Both use three strict
fresh children per operation under `sceneio-fresh-child-memory-v1`; TIFF
selection and inspection remain materially below full-read RSS, while USD
state B records the provider's full-layer materialization cost without
mislabeling it as a bounded-memory or full-animation comparison.

### 9.3 Distribution and hosted gate

- [x] Build and verify an exact source archive and clean Windows wheel locally.
- [x] Install the base wheel with NumPy only and prove all optional providers
      remain lazy.
- [x] Install each affected extra independently (`tiff`, `openvdb`, `usd`, and
      `ncore`/splat extras when G1 changes their public surface).
- [x] Run manifest-driven installed smoke and source/wheel license inventory.
- [x] Exercise affected providers during candidate hardening and keep focused
      hosted corrections separate from the implementation units.
- [x] Trigger the final nonpublishing Release matrix from the exact candidate
      SHA and retain source/wheel hashes.
- [x] Run hosted OpenUSD/OpenVDB and required large-data comparisons without
      adding those packages or datasets to normal offline CI.
- [x] Record every run URL, SHA, artifact hash, platform result, optional skip,
      and benchmark summary in the canonical coverage documents.

**Exact candidate result (2026-08-29):** commit
`9a20bc61f177c28ba228b89e80cff665e3f1b426` passed nonpublishing Release run
[`33249900572`](https://github.com/SceneAPI/SceneIO/actions/runs/33249900572).
The run rebuilt the exact sdist, verified 1,624 repository files plus the
generated `PKG-INFO`, built abi3 wheels on macOS arm64, manylinux x86-64, and
Windows amd64, and passed the combined USD/AVIF/NCore/TIFF/OpenVDB installed
smoke on every wheel host. The dedicated OpenUSD 26.08 and Niantic SPZ oracles
passed; the tag-only publication job was intentionally skipped.

The exact candidate also passed both standard CI copies
([push `33249897819`](https://github.com/SceneAPI/SceneIO/actions/runs/33249897819),
[PR `33249899654`](https://github.com/SceneAPI/SceneIO/actions/runs/33249899654))
and both instrumented sanitizer copies
([push `33249897883`](https://github.com/SceneAPI/SceneIO/actions/runs/33249897883),
[PR `33249899660`](https://github.com/SceneAPI/SceneIO/actions/runs/33249899660)).
This includes the five-run strict I/O/memory guard and the exact 5,066-node
provider-independent ASan/UBSan collection. The retained local strict result is
`build/fc7-post-memory-strict-benchmark.json`, SHA-256
`3b1bcdae188d111865826edc258e485c8a3ea4e645660d3cfab14fb4eb335bcb`.

Candidate-hardening Release runs
[`33248947262`](https://github.com/SceneAPI/SceneIO/actions/runs/33248947262)
and [`33249332793`](https://github.com/SceneAPI/SceneIO/actions/runs/33249332793)
proved the OpenVDB wheel smoke and source/wheel lanes while hosted collection
findings were corrected independently in commits `56d1922` and `9a20bc6`.

| Hosted artifact | Payload/file SHA-256 | GitHub artifact archive SHA-256 |
|---|---|---|
| `sdist` | `15eb2e13b44a84a423a9fe075c7a2265c4348f16ca45758a762376dcc10b9d1c` | `b038e1ceae5813127c762d3039b4adf38a5f2302a1ec5a5e169337c39d07a759` |
| `source-inventory` | `b6f92ac46d3443f7ff7ac4378f4896e161bb9788c7d67edbd8f760026802fcb4` | `8dba5d9c00314d1cd279b68e2c871c578f9a4eaf3a2a0098c00be765007439c4` |
| `wheels-macos-appleclang-arm64` | `3c4d95189bd5e01fc528d7918e1a5c668180ce67493069bddd789a3c224f6487` | `cd6cf34ca20fc59b84f3239ba97e1a63849fab9390509671038041c0360b87aa` |
| `inventory-macos-appleclang-arm64` | `c08163f0126363e035fbf80ea0f590cbc9dd7dfb2213808fa233816567bf6c05` | `a3b7843d30b2a75c781b240bce6e62eb35f2814a0e54ca4df6ba9ad9403f0c96` |
| `wheels-manylinux2014-gcc10-x86_64` | `4592504f971810d0e25f1719d34e683fac1ad758946905130ba91de157c3e08d` | `35ba1ac0f10b595b57a88f1a2156f90cda6e366e41e30b087e96d3faafd54211` |
| `inventory-manylinux2014-gcc10-x86_64` | `c967f84af9b1ba2fbe0b038e5cae352413261eedc55cb85ab1cabf6b5d7501ca` | `c4f61db16d967390982de9dbd6eee9ebe3b47d7fd663ec1b8d15abf9c4dac6ab` |
| `wheels-windows-msvc-amd64` | `bb567c00961e94ad784294861b5ebaee817296aacf68e81d394df04cc8715750` | `b0cb3cb73247464c39c29108eba51309a6c150226585bde5d52ad6a673f94541` |
| `inventory-windows-msvc-amd64` | `cd429fb0d74cf96f0ee4ff688d6d682da71d7218016fa796e5a5bf3f6f2648fb` | `e40ad154ba8465cff69e89b954ecde590f8e7f2da1899e5f133162a8d7b853f2` |
| `distribution-inventory` | `818af161b9033c58feede72240364d240cbd661b181d575f43745d43530cfaca` | `3c7eae5f664d26e375aa96983143cab6aaa63d90114691ef1e48901e169d36b6` |

The source inventory records source-tree SHA-256
`18587c6a573a306f54e8d49cba9e8623fb04183e4b948e7e713d74548922c95a`.
The distribution inventory independently re-records the sdist and three wheel
payload hashes above, 64 license assets per distribution, and the exact native
member and abi3 tag for each platform.

### 9.4 Final review

- [x] Ownership/lifetime: no provider handle, mapping pointer, temporary file,
      or child record has an invalid lifetime; all error paths close resources.
- [x] Behavior: every represented field is compared, conversions are explicit,
      and legacy outputs/return types are unchanged.
- [x] Test soundness: each oracle is independent for the property it proves,
      expected refusals cannot pass by skipping decode, and performance tests
      distinguish selected provider I/O from slicing.
- [x] Scope: no unrelated repository move, dependency expansion, generalized
      media/scientific support, or hidden base dependency entered the diff.

**FC7 exit:** the completion matrix is full or explicitly excluded where
allowed, exact-head packages and hosted oracles pass, the draft/PR state is
resolved, and publication remains a separate tag-driven user decision.

**Technical closeout complete:** the reviewable implementation units and hosted
corrections are committed and pushed, and the nonpublishing package/oracle/CI/
sanitizer evidence is recorded above. The existing PR remains a mergeable draft
until the user chooses to mark it ready or otherwise resolve its review state.
Publication remains a separate tag-driven user decision.

## 10. Recommended review/commit sequence

1. V0 exact-head Release evidence and FC3 documentation update.
2. G1 audit/contract only.
3. G1 compatible record/conversion implementation.
4. G1 codec mappings, oracles, benchmark, and docs.
5. FC4 provider probe and frozen raster API contract.
6. FC4 records and compatibility tests.
7. FC4 read/inspect/select implementation.
8. FC4 qualified writer subset, oracle, benchmark, and docs.
9. FC5 provider feasibility and explicit decision.
10. FC5 implementation slices if qualified, otherwise tested exclusion/docs.
11. FC6 provider/parser decision and selected-time oracle.
12. FC6 selected-time read.
13. FC6 `SceneAnimation` record and writer only for close state A.
14. Per-provider platform corrections as separate commits.
15. FC7 contracts, aggregate local gate, package/hosted evidence, and final docs.

Each numbered item is independently reviewable and revertible. Split an item
further when native record changes, provider code, and public API cannot be
reviewed safely together.

## 11. Principal risks and controls

| Risk | Control |
|---|---|
| Provider exposes a selector but decodes everything | Allocation/RSS measurement plus a full-decode trap; omit the selector if not bounded |
| Provider behavior differs across platforms | Run the affected optional-provider wheel lane immediately after the unit, not only at FC7 |
| New records break legacy construction or return types | Keyword-only additions, compatibility snapshots, old-fixture byte/value tests |
| Semantic metadata overclaims evidence | Per-format versioned ledger with `unknown` and stable refusal as valid states |
| Writer silently drops unsupported data | Validate the complete record before opening the destination; transactional replacement tests |
| Huge PR becomes unauditable | Close the current FC0-FC3 checkpoint after V0 and use one PR/work unit per remaining phase |
| Benchmark noise masks regressions | Five-run medians, retained directional limits, same-machine parent/candidate comparisons, and separate traced/RSS measures |
| Offline CI acquires large or restricted data | Keep generated compact fixtures checked in; acquisition and official-provider comparisons remain opt-in hosted jobs |

## 12. Stopping rule

Stop adding scope when the target outcome in section 1 is satisfied. In
particular, do not reopen general OME microscopy, E57 imagery/spherical data,
arbitrary Arrow schemas, OpenVDB point/nonlinear trees, USD composition or
deformation, FFmpeg/media tracks, JPEG-XL, Draco, or unrelated formats. A new
request for any of those requires a separate profile, provider review, and
implementation plan.
