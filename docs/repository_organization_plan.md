# Repository organization and codec-performance gate

Status: required before the next format implementation.

This plan keeps SceneIO manageable as the registry grows beyond 50 codecs. It
is a behavior-preserving architecture and evidence pass: no format is added,
removed, or semantically changed while this gate is open.

The commit-sized execution order, tests, verification, validation, and
documentation checklist is
[`next_stage_implementation_checklist.md`](next_stage_implementation_checklist.md).

## Current checkpoint

N0 closes at validated implementation commit `a5e7fa4`: local MSVC, normal
Linux CI, pinned GCC 10, the Linux/Windows/macOS focused matrix, the complete
and focused compiler-instrumented native jobs, the 50-codec performance guard,
and the nonpublishing three-platform wheel/source build all pass. The R1
implementation and validation checkpoint is exact commit `95061c6`. Its
immutable ownership manifest,
compatibility fixtures, repository completeness checks, 50-codec/130-operation
performance ledger, completed-plan archive, and documentation consistency
checks pass locally and in normal CI run 30187895845 plus instrumented run
30187895838. Local MSVC collects 2,955 tests and passes 2,951 with four
documented skips; the Windows abi3 wheel built from the exact `95061c6` source
archive passes a fresh NumPy-only installed-wheel smoke. Build-only release run
30189483142 also builds the source archive and builds and smoke-tests the Linux,
macOS, and Windows wheel sets with publication skipped. No new format starts
while R2-R6 remain open.

R2.0 is complete at `40d5412`. Image-sequence frame
extensions and metadata inspection are injected through the lower-level
`ImageFrameAccess` contract, and both public and injected inspection paths use
the same `inspect_codec` dispatcher. The catalog remains live for third-party
image registrations, while the adapter no longer imports the registry or
public I/O facade at runtime. The exact source archive and Windows abi3 wheel
pass content-identity, package-layout, attribution, and fresh NumPy-only smoke
checks.

R2.1 is complete at `ccfeea4` behind the unchanged `registry.py` facade.
Shared model, mmap/path/sink adapter, ordered detection, and native-feature
services now live in focused `sceneio.io._registry` modules. The calibration
family (`opencv_yaml`, `opencv_xml`, `ros_camera_info`, and `kalibr`) is
complete and pushed at `b2bda1d`. Its immutable definition tuple,
validate-before-install facade boundary, family inspector, and exact
source-to-wheel checks establish the reference pattern. The complete local
suite collects 2,999 tests and passes 2,995 with four documented skips; the
all-codec structural sweep, retained five-run performance/allocation guard,
Ruff, fresh-process import thresholds, and three independent reviews pass.
Normal CI run 30193628676 and compiler-instrumented run 30193628672 are green.

The shared inspection substrate is complete and pushed at `29af9de`.
`ArrayInspection`, `Inspection`, and the proven common mmap-buffer bridge now
live below the compatibility facade with historical type, repr, annotation,
and pickle behavior preserved. The complete local suite collects 3,006 tests
and passes 3,002 with four documented skips; the isolated 295-member
source-to-66-file-wheel gate, retained all-codec guard, fresh import thresholds,
and three independent reviews pass.

Meshes are complete and pushed at `975533f`. The six ids remain one
contiguous canonical block behind an immutable tuple, while PLY-mesh/STL/OFF
metadata inspection lives below the compatibility facade and OBJ/glTF/GLB
retain their bespoke adapters. The complete local suite collects 3,024 tests
and passes 3,020 with four documented skips. The exact 298-member
source-to-68-file-wheel gate, retained all-codec guard, fresh import
thresholds, and three independent reviews pass.

Images are complete and pushed at `68c47d6`. The eight ids remain one
contiguous canonical block behind an immutable tuple and retain their exact
static mmap/sink/window adapters. Their bounded metadata parsers now live in
`_inspectors/images.py` behind same-signature facade wrappers. The shared
metadata limits, exact-read and unsigned-decimal grammar, and common
image-result constructor were lowered in the independently green `8040bc7`
helper commit. The complete local suite collects 3,064 tests and passes 3,060
with four documented skips. The exact 302-member source-to-70-file-wheel gate,
retained all-codec guard, fresh import thresholds, installed all-image probe,
and three independent reviews pass.

Sequences are complete and pushed at `14bf53b`. Y4M and the image-sequence
directory are the fourth extracted family and the last contiguous canonical
family. The lower family module accepts the facade-created
`ImageFrameAccess` explicitly, keeps the static Y4M codec, and returns an
immutable two-codec tuple containing a freshly bound directory codec. It owns
no registry state and never freezes the live image-extension catalog. Only
the Y4M metadata converter moved to a family inspector. The directory manifest
parser and inspector remain in `_image_sequence.py`, where R2.0 removed upward
dependencies. The complete local suite collects 3,083 tests and passes 3,079
with four documented skips; exact source-to-wheel validation, retained
all-codec guards, three independent reviews, normal CI run 30200316679, and
compiler-instrumented run 30200316665 pass.

The aggregate staging boundary is complete at `1ec0550`, with its portable
benchmark-structure follow-up at `6086315`. It supports the four remaining
interleaved families. The lower
`_registry/assembly.py` collector validates single definitions and complete
family tuples without importing the facade or mutating the public registry.
The facade stages every built-in, finalizes the exact 50-id canonical tuple,
then publishes it to the existing `REGISTRY` object in one update. Public
third-party `register()` behavior, the compatibility family installer, and
the live `ImageFrameAccess` callbacks remain unchanged. Parent/candidate AST
and callable-descriptor contracts are exact, all 50 benchmark rows retain
their deterministic structure, and the complete local suite passes 3,091
tests with four documented skips. The exact-tree package preflight contains
310 source files and a 73-file wheel whose sole runtime-member delta is the
assembly module; the installed NumPy-only smoke and explicit aggregate/live
sequence probe pass, and all three reviews are clear. Normal CI run
30204352767 and compiler-instrumented run 30204352744 pass at `6086315`.

Arrays are complete and pushed at `d99dcf0`. The non-contiguous `pfm`, `npy`,
`npz`, `safetensors`, `flo`, and `dmb` definitions now come from a
side-effect-free family factory while retaining their six canonical positions
and exact adapter/native callable descriptors. Their metadata parsers live in
`_inspectors/arrays.py` behind same-signature facade wrappers. The complete
local suite collects 3,134 tests and passes 3,130 with four documented skips.
Parent-derived valid/malformed contracts, bounded large-fixture inspections,
the exact 50-row and six-row benchmark projections, the five-run retained
guard, Ruff, exact-tree source/wheel validation, a fresh NumPy-only installed
probe, and all three independent reviews pass. Normal CI run 30207617248 and
compiler-instrumented run 30207617253 are green for the exact commit. Points
are the active sixth family; reconstruction and splats follow.

The points candidate moves `ply`, `pcd`, `xyz`, `pts`, `las`, and `laz` to
one immutable lower family tuple while preserving their six non-contiguous
canonical positions and exact mmap/sink/point-range targets. Their metadata
parsers now live in `_inspectors/points.py`; the compatibility facade retains
same-signature wrappers. Parent-derived valid/malformed contracts, exact
full-versus-partial slices, path-release checks, generated 50,000-point
inspection bounds, the exact 50-row and six-row benchmark projections, the
strict five-run guard, a 3,184-node collection, Ruff, and a 687-test focused
matrix pass. Fifteen same-host samples add only the two intended lower modules
to the I/O facade, with no `sceneio` or direct `_core` module-set change.
The complete local suite passes 3,180 tests with four documented skips.
The exact 317-file staged tree produces a byte-identical 318-file sdist whose
only generated file is `PKG-INFO`; its 77-member Windows abi3 wheel adds only
the two lower point modules. Attribution, NumPy-only metadata, native
dependencies, full installed smoke, and explicit all-six point probes pass in
a clean external environment. All three independent reviews are clear for
staged tree `442093b402db2af290c9a19a61747b6691e2af1c`; their largest focused
matrix passes 729 tests and no review required a source change. Final
exact-tree artifact, commit/push, and hosted validation gates remain before
this unit closes.

The codec-per-file C++ layer remains reasonably isolated, but orchestration and
verification have accumulated in a few large modules:

| Area | Current shape | Growth risk |
|---|---|---|
| C++ codecs | 40 files for 50 format ids | flat source list and manual binding declarations |
| C++ records | 32 source/header files | still manageable; new table/animation/scene records will add pressure |
| Python registry | `registry.py`, 573 lines; `_registry/assembly.py`, 148 lines; focused `_registry/{model,adapters,detection,native_features}.py` modules; and `_registry/families/{arrays,calibration,images,meshes,points,sequences}.py` definition modules | reconstruction and splats still share the facade until their R2.2 units |
| Inspection | `_inspection.py`, 978 lines, plus `_inspectors/{model,common,arrays,calibration,images,meshes,points,sequences}.py`; `common.py` is 75 lines | reconstruction and splat metadata still share the facade; the proven shared model, mmap bridge, metadata bounds, exact-read/integer grammar, and image-result constructor are lower services |
| Benchmark | `bench_io.py`, about 4,660 lines | CLI, fixtures, oracles, runners, metrics, and reporting are coupled |
| Cross-codec tests | `test_io_mmap.py`, about 2,400 lines; `test_io_partial.py`, about 1,100 | reusable codec cases and behavior assertions are difficult to extend independently |
| Execution plan | `format_gap_implementation_plan.md`, about 2,500 lines | historical evidence and the active queue are easy to confuse |
| Native dependencies | six source-complete in-tree projects, one LAZperf integration/provenance directory, and six `FetchContent` projects | stable builds are not yet fully offline/repository-contained |

The public API and native ABI remain stable throughout the reorganization.

## Ownership and implementation policy

SceneIO owns and maintains each stable format's:

- public codec registration and detection contract;
- record mapping and conventions;
- input validation and unsupported-feature guards;
- mmap/path adapter, metadata inspection, partial-read semantics, and direct
  sink;
- normalized errors, tests, benchmarks, documentation, and packaging.

A mature upstream codec kernel should be used directly when it is the best
permissively licensed, cross-platform implementation that satisfies SceneIO's
fidelity contract. SceneIO does not rewrite compression or entropy algorithms
merely to call them repo-owned. For default stable formats, the chosen exact
upstream source is pinned and stored under `src/cpp/third_party/`, built into
the extension, attributed in `LICENSES/`, and wrapped by the repo-maintained
adapter. Optional system integrations remain accurately labeled optional.

An upstream library becomes a production kernel only after this performance
and portability gate selects it and its pinned source is built into the
extension. Separately installed implementations and command-line tools remain
test/reference oracles and are never runtime delegates.

## Target layout

The exact filenames may adjust during migration, but the ownership boundaries
are fixed:

```text
cmake/
  Dependencies.cmake
  SceneIOSources.cmake
  Sanitizers.cmake
  third_party/
    <dependency>.cmake

src/cpp/
  bindings/
    records.hpp
    codecs.hpp
    register_records.cpp
    register_codecs.cpp
  codecs/
    arrays/
    calibration/
    images/
    meshes/
    points/
    reconstruction/
    sequences/
    splats/
  io/
  records/
  third_party/
    <project>/
      COMMIT.txt
      LICENSE
      patches/

src/sceneio/io/
  registry.py                 # compatibility facade
  _registry/
    assembly.py               # validated one-update built-in publication
    model.py                  # Codec and capability value types
    adapters.py               # shared mmap/path/sink adapters
    detection.py
    native_features.py
    families/
      arrays.py
      calibration.py
      images.py
      meshes.py
      points.py
      reconstruction.py
      sequences.py
      splats.py
  _inspection.py              # compatibility facade
  _inspectors/
    common.py
    arrays.py
    calibration.py
    images.py
    meshes.py
    points.py
    reconstruction.py
    sequences.py
    splats.py

bench/
  bench_io.py                 # thin CLI
  _io/
    model.py
    runner.py
    metrics.py
    reporting.py
    fixtures/
    oracles/
    families/
  PERFORMANCE_STATUS.toml

tests/
  _support/
    codec_cases.py            # one registry-driven test/fixture catalog
    memory.py
    subprocess.py
  codecs/
  records/
  io/
    test_mmap.py
    test_streaming.py
    test_inspection.py
    test_partial_<family>.py

docs/
  format_coverage.md          # current generated/validated status
  coverage_roadmap.md         # policy and declared destination
  format_gap_implementation_plan.md
  repository_organization_plan.md
  plans/
    completed/                # immutable historical wave evidence
```

`sceneio.io.registry`, `sceneio.io._inspection`, public imports, codec ids,
extension detection order, error text families, and `_core` symbol names remain
compatible facades. Moving files is not permission to redesign contracts.

## One manifest, several consumers

The mutable registry remains the runtime extension surface. The organization
pass adds immutable built-in family definitions and a canonical aggregate so
one family module owns each built-in codec registration and reusable
test/benchmark metadata can be joined by format id. Repository completeness
rules apply to built-ins, not third-party codecs registered at runtime.

Required invariants:

1. Every built-in format id is registered exactly once and belongs to exactly
   one family; third-party runtime registrations are not required to appear in
   repository manifests.
2. The union of family registrations is the same 50-id set before and after
   migration.
3. Detection precedence remains explicitly tested, especially PLY and generic
   text/directory formats.
4. Capability and native-feature snapshots remain byte-identical.
5. The benchmark and cross-codec fixture catalogs fail when a new available
   built-in codec lacks an explicit inclusion or documented exemption; runtime
   extension registrations remain outside repository-completeness checks.
6. Coverage documents fail when their current-status inventory disagrees with
   the live manifest.
7. Every default native dependency has provenance, license, patch, and offline
   build metadata.

Do not generate Python or C++ source at package import time. A checked-in
manifest or ordinary family modules remain readable and debuggable.

## Performance qualification before backend selection

Optimized transport and an optimized codec kernel are separate claims.
All current codecs have mmap/path-native input, inspection, and direct sinks;
28 have bounded partial reads. That proves the I/O layer is optimized, not that
every encoder/decoder backend is the fastest suitable implementation.

Before selecting or retaining a stable backend:

1. Identify the mature permissive candidates and the format subset each can
   preserve.
2. Benchmark production-call paths, not isolated library functions, on the
   same canonical fixtures:
   - encode and decode throughput;
   - warm mmap and cold/path read;
   - direct-sink throughput;
   - traced allocation and fresh-process RSS;
   - one lane and bounded automatic lanes where supported;
   - deterministic bytes or semantic equality;
   - binary size and import/startup impact.
   Decoder candidates consume the same hashed encoded corpus, with producer,
   settings, provenance, and accepted-subset coverage recorded. Where
   possible, that corpus includes both retained-writer and independent
   reference/spec fixtures.
3. Run representative small, normal, and generated 100 MiB-class fixtures.
4. Verify the candidate on MSVC, manylinux2014 GCC 10, and AppleClang.
5. Select the fastest candidate that also satisfies fidelity, deterministic
   behavior, permissive licensing, static/offline buildability, maintenance,
   and artifact-size constraints.
   Lossy profiles use predeclared comparative non-inferiority margins,
   aggregation/confidence rules, and file-size matching bounds against the
   retained backend.
6. Record the candidates, results, selection, and any accepted tradeoff in
   `bench/PERFORMANCE_STATUS.toml` and `bench/BASELINE.md`.

Prefer the upstream optimized kernel. Write a SceneIO-native kernel only when
no suitable upstream project meets the format contract, or when measurement
proves the bounded native implementation is materially better and maintainable.

The performance ledger contains one entry per built-in codec, performance
profile, and direction cell:

```toml
schema_version = 1

[[operation]]
codec_id = "jpeg"
profile = "rgb8_q90_420"
direction = "encode"
adapter = "repo"
backend = "stb_image_write"
backend_source = "src/cpp/third_party/stb"
transport_status = "qualified"
status = "known_gap"
evidence = "bench/BASELINE.md#o0-baseline"
next_candidate = "libjpeg-turbo"
```

Encode and decode are qualified separately for every materially different
profile; a declared direction that a codec does not expose uses
`not_applicable`. Allowed operation states are:

- `qualified`: the viable candidate set and exclusions are recorded, the
  finalists are measured through SceneIO on all supported toolchains, and the
  best conforming candidate is selected;
- `provisional`: the implementation is correctness-tested, but backend
  qualification is incomplete; profile-specific measurement or candidate
  comparison may still be missing and must be named in `evidence_gaps`;
- `known_gap`: a viable conforming candidate is materially faster;
- `native_by_necessity`: no suitable upstream kernel exists and the
  repo-maintained parser is independently verified;
- `not_applicable`: the codec does not expose that operation.

The current known exception is the JPEG backend: the committed baseline
measured stb write/read at 60/154 MB/s versus Pillow's libjpeg-backed reference
at 924/541 MB/s on the same fixture. The stable-tier gate must evaluate
libjpeg-turbo or another approved permissive candidate for both directions;
micro-optimizing stb is not an adequate closure. XYZ formatting and WebP
lossless were already improved materially, but still receive explicit ledger
entries rather than inheriting a blanket claim.

## Behavior-preserving migration sequence

### R1. Freeze contracts and add architecture tests

- Snapshot the 50 ids, capabilities, native features, detection precedence,
  public imports, and `_core` symbol set.
- Add the performance ledger schema and enforce required operation cells for
  every id in `BUILTIN_DEFINITIONS`.
- Add family-ownership, extension-boundary, import-surface, and repository
  completeness tests. Actual family `Codec` extraction and aggregate
  reload/idempotence begin in R2 after shared state is separated.
- Give each documentation surface one job: keep current status in
  `format_coverage.md`, active work in `format_gap_implementation_plan.md`, and
  move closed wave evidence to `docs/plans/completed/` with stable links.

### R2. Split Python orchestration

- Invert the sequence adapter's deferred imports of registry/inspection
  services before moving families; inject lower-level catalogs and dispatchers.
- Extract registry value types, shared adapters, detection, and native-feature
  metadata behind the existing `registry.py` facade.
- Move registrations one family at a time; run capability and full public API
  tests after each family.
- Split `_inspection.py` by family behind its existing facade.

### R3. Split benchmark and cross-codec fixtures

- Move fixture builders and oracles by family.
- Keep `bench/bench_io.py` as a compatible CLI entry.
- Centralize buffer/path/directory codec cases in `tests/_support/codec_cases.py`.
- Split large behavior tests one behavior/family at a time without duplicating
  parameter matrices, and compare exact pytest node ids and skip reasons.
- Preserve the current warmed-process RSS metric during the mechanical split,
  then add a separately tested child-process RSS protocol for qualification.
- Make required oracles and RSS sampling strict in qualification mode.

### R4. Organize native build and bindings

- Split dependency configuration and source manifests out of the root
  `CMakeLists.txt`.
- Replace manual declarations in `module.cpp` with family registration
  functions while preserving binding order.
- Expose a private machine-readable native codec inventory from those same
  family tables and compare it with the native/hybrid projection of the
  built-in Python manifest. Built-in definitions declare whether their adapter
  owner is native, Python, or hybrid.
- Move codecs by family in mechanical commits; do not mix semantic edits with
  moves.

### R5. Qualify performance

- Populate the 50-codec ledger from existing baseline evidence.
- Re-run missing candidate comparisons per performance profile and direction,
  using one provenance-recorded, accepted-subset corpus from retained and
  independent producers for every decoder candidate.
- Resolve `known_gap` entries, beginning with JPEG encode/decode.
- Integrate candidates behind non-default qualification targets, switch a
  selected default in a dedicated revertible commit, and retain the old
  backend until a user-authorized three-platform A/B matrix passes.
- Before removing an old backend, install a persistent same-run regression
  guard against the ledger's pinned qualified commit.
- Keep a backend only when the evidence supports `qualified`,
  `native_by_necessity`, or an explicit documented provisional exception.

### R6. Close stable native sources

- Vendor the selected exact revisions for the six currently fetched
  dependencies; a performance result may change a backend before its source is
  embedded.
- Apply local changes as documented patch files or narrowly marked source
  changes.
- Prove `FETCHCONTENT_FULLY_DISCONNECTED=ON` and network-disabled
  sdist-to-wheel builds.

## Execution, verification, and validation matrix

The sequence starts only after the current Linux normal and instrumented CI
blockers in `format_gap_implementation_plan.md` section 12.1.1 are green.
Each row is a separate green commit; a later row does not absorb an unfinished
earlier gate.

| Unit | Implementation boundary | Focused verification | Validation and exit evidence |
|---|---|---|---|
| R1a | Add contract snapshots, built-in family ownership, manifest schema, and the performance-ledger skeleton without moving behavior | capability/document snapshot; extension/magic precedence; public imports; `_core` symbols; one ledger row per required profile and direction | focused architecture tests, full local suite, Ruff, benchmark smoke; zero snapshot delta |
| R1b | Separate the active queue from the completed Waves A-C evidence while preserving the three authoritative entry points; retain the format-level G2-G4.2 contract/status ledger until its later archive unit | relative-link/anchor check; live capability table and current checkpoint remain generated/validated; no historical result is rewritten | documentation-consistency tests, full link check, Ruff, `git diff --check`; Wave A-C stubs are concise and every archived wave is reachable |
| R2a-R2h | Move one Python registry family at a time behind `registry.py`; then move its inspectors behind `_inspection.py` | family ids/capabilities, detect ambiguity, bytes/mmap/path, inspect/full agreement, selector validation order | full public API E2E after each family; import-cycle test; no import/startup regression outside the recorded noise band |
| R3a-R3h | Move one benchmark/fixture/oracle family at a time; centralize cross-codec cases in staged consumer migrations | old and new CLI JSON schemas match; exact pytest node ids/parameters/skips match; the exact 50 built-ins are included or explicitly exempted; representative fixture bytes/hashes match | one-run all-codec smoke after each family, then five-run retained O4/O5 guards; strict qualification rejects a missing oracle/RSS sampler |
| R4a | Extract CMake dependency/source manifests without moving native files | configure option/cache equivalence; compiled source list and feature macros match | rebuild editable wheel on MSVC; `_core` symbol snapshot and full suite pass |
| R4b-R4h | Move native codec files and binding registration by family; preserve record-before-codec order | byte/mmap/sink/inspect/partial differential for the moved family; native inventory, source ownership, symbol visibility, and registration order | rebuild after every family; full local suite and benchmark guard; no semantic diff mixed into move commits |
| R5a | Populate existing evidence per codec and mark every unproved direction `provisional`, never `qualified` by inference | ledger schema/id coverage; evidence links resolve; current backend and build source match CMake | reviewable 50-codec matrix committed before candidate replacement starts |
| R5b+ | Research and benchmark viable permissive candidates one profile/direction at a time, starting with JPEG | same production API, provenance-complete hashed decode corpus, predeclared lossy non-inferiority bounds, warm/cold runs, sinks, child-process RSS, determinism, size/startup; oracle parity and malformed-input equivalence | build the shortlist on MSVC, then run a user-authorized nonpublishing A/B matrix on GCC 10 and AppleClang before final selection; switch defaults in revertible commits, add the persistent qualified-commit guard, and update baseline/ledger |
| R6a+ | Store each selected fetched dependency in-tree with provenance, license, hashes, options, and patches; switch only that dependency to local source | golden output, focused codec parity, dependency revision/options, benchmark within recorded variance | editable rebuild/full suite/Ruff per dependency; `FETCHCONTENT_FULLY_DISCONNECTED=ON` configure and sdist build |
| R6-final | Remove all default native-source network fetches and validate the packaged result | clean source checkout, empty native caches, `PIP_NO_INDEX=1`, offline sdist, wheels built from that exact sdist, wheel contents/native dependencies, exact 50-id NumPy-only smoke, positive license inventory | local MSVC plus user-authorized manylinux2014 and macOS build-only wheel matrix; docs and license inventory synchronized |

Candidate comparisons use randomized/interleaved repeated samples for hot-path
throughput and child-process samples for RSS/startup. Record raw JSON,
toolchain/CPU/library revisions, fixture hashes, codec settings, output size or
quality, median, MAD, paired ratios, and a predeclared no-deletion/outlier
policy. Decoder candidates consume the same encoded bytes. A backend wins only
when correctness and the format subset are equal; a smaller or differently
lossy output is not a valid speed comparison. After selection, affected
codec/backend/build changes and a scheduled workflow compare the current
checkout with the ledger's pinned qualified commit on the same runner; noisy
failures require a confirming rerun.

## Exit gate

No animated, RTMV, optional-library, or heavyweight codec starts until:

- current Linux normal and instrumented CI blockers are closed;
- the registry, inspection, benchmark, and cross-codec tests have the target
  family boundaries or an explicitly accepted smaller equivalent;
- the 50-id API/capability/detection snapshots are unchanged;
- default native dependencies build offline from repository-contained source;
- every current built-in codec/profile/direction has a performance-ledger
  entry and no unexplained `known_gap`;
- local MSVC, Linux normal, Linux instrumented, Windows/macOS mmap, Ruff,
  sdist, wheel, and NumPy-only installed smoke all pass;
- `format_coverage.md`, `coverage_roadmap.md`, and
  `format_gap_implementation_plan.md` agree with the live registry.

This gate is about maintainability, reproducibility, and measured performance;
it does not add a separate cybersecurity workstream.
