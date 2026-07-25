# Repository organization and codec-performance gate

Status: required before the next format implementation.

This plan keeps SceneIO manageable as the registry grows beyond 50 codecs. It
is a behavior-preserving architecture and evidence pass: no format is added,
removed, or semantically changed while this gate is open.

## Current checkpoint

The codec-per-file C++ layer remains reasonably isolated, but orchestration and
verification have accumulated in a few large modules:

| Area | Current shape | Growth risk |
|---|---|---|
| C++ codecs | 40 files for 50 format ids | flat source list and manual binding declarations |
| C++ records | 32 source/header files | still manageable; new table/animation/scene records will add pressure |
| Python registry | `registry.py`, about 1,600 lines | data model, adapters, detection, native features, and 50 registrations share one file |
| Inspection | `_inspection.py`, about 1,950 lines | unrelated format-family parsers and result conversion share one module |
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

The current registry is already the runtime source of truth. The organization
pass adds a small declarative internal manifest boundary so one family module
owns each codec registration and reusable test/benchmark metadata can be
joined by format id.

Required invariants:

1. Every format id is registered exactly once and belongs to exactly one
   family.
2. The union of family registrations is the same 50-id set before and after
   migration.
3. Detection precedence remains explicitly tested, especially PLY and generic
   text/directory formats.
4. Capability and native-feature snapshots remain byte-identical.
5. The benchmark and cross-codec fixture catalogs fail when a new available
   codec lacks an explicit inclusion or documented exemption.
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
3. Run representative small, normal, and generated 100 MiB-class fixtures.
4. Verify the candidate on MSVC, manylinux2014 GCC 10, and AppleClang.
5. Select the fastest candidate that also satisfies fidelity, deterministic
   behavior, permissive licensing, static/offline buildability, maintenance,
   and artifact-size constraints.
6. Record the candidates, results, selection, and any accepted tradeoff in
   `bench/PERFORMANCE_STATUS.toml` and `bench/BASELINE.md`.

Prefer the upstream optimized kernel. Write a SceneIO-native kernel only when
no suitable upstream project meets the format contract, or when measurement
proves the bounded native implementation is materially better and maintainable.

The performance ledger contains one entry per live codec:

```toml
[[codec]]
id = "jpeg"
adapter = "repo"
read_backend = "stb_image"
write_backend = "stb_image_write"
backend_source = "third_party"
transport_status = "qualified"
decode_status = "known_gap"
encode_status = "known_gap"
evidence = "bench/BASELINE.md#o0-baseline"
next_candidate = "libjpeg-turbo"
```

Encode and decode are qualified separately; read-only/write-only formats use
`not_applicable` for the missing direction. Allowed operation states are:

- `qualified`: the viable candidate set and exclusions are recorded, the
  finalists are measured through SceneIO on all supported toolchains, and the
  best conforming candidate is selected;
- `provisional`: correct and benchmarked, but the candidate comparison is
  incomplete;
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
- Add the performance ledger schema and enforce one entry per registry id.
- Add import-cycle and family-ownership tests.
- Give each documentation surface one job: keep current status in
  `format_coverage.md`, active work in `format_gap_implementation_plan.md`, and
  move closed wave evidence to `docs/plans/completed/` with stable links.

### R2. Split Python orchestration

- Extract registry value types, shared adapters, detection, and native-feature
  metadata behind the existing `registry.py` facade.
- Move registrations one family at a time; run capability and full public API
  tests after each family.
- Split `_inspection.py` by family behind its existing facade.

### R3. Split benchmark and cross-codec fixtures

- Move fixture builders and oracles by family.
- Keep `bench/bench_io.py` as a compatible CLI entry.
- Centralize buffer/path/directory codec cases in `tests/_support/codec_cases.py`.
- Split large behavior tests without duplicating parameter matrices.

### R4. Organize native build and bindings

- Split dependency configuration and source manifests out of the root
  `CMakeLists.txt`.
- Replace manual declarations in `module.cpp` with family registration
  functions while preserving binding order.
- Move codecs by family in mechanical commits; do not mix semantic edits with
  moves.

### R5. Qualify performance

- Populate the 50-codec ledger from existing baseline evidence.
- Re-run missing candidate comparisons.
- Resolve `known_gap` entries, beginning with JPEG encode/decode.
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
| R1a | Add contract snapshots, family ownership, manifest schema, and the 50-entry performance-ledger skeleton without moving behavior | capability/document snapshot; extension/magic precedence; public imports; `_core` symbols; one ledger row per id and applicable direction | focused architecture tests, full local suite, Ruff, benchmark smoke; zero snapshot delta |
| R1b | Separate active documentation from completed wave evidence while preserving the three authoritative entry points | relative-link/anchor check; live capability table and current checkpoint remain generated/validated; no historical result is rewritten | documentation-consistency tests, full link check, Ruff, `git diff --check`; active plan is concise and every archived wave is reachable |
| R2a-R2h | Move one Python registry family at a time behind `registry.py`; then move its inspectors behind `_inspection.py` | family ids/capabilities, detect ambiguity, bytes/mmap/path, inspect/full agreement, selector validation order | full public API E2E after each family; import-cycle test; no import/startup regression outside the recorded noise band |
| R3a-R3h | Move one benchmark/fixture/oracle family at a time; centralize cross-codec cases | old and new CLI JSON schemas match; the exact 50 ids are included or explicitly exempted; representative fixture bytes/hashes match | one-run all-codec smoke after each family, then five-run retained O4/O5 guards; no missing oracle or silently skipped row |
| R4a | Extract CMake dependency/source manifests without moving native files | configure option/cache equivalence; compiled source list and feature macros match | rebuild editable wheel on MSVC; `_core` symbol snapshot and full suite pass |
| R4b-R4h | Move native codec files and binding registration by family; preserve record-before-codec order | byte/mmap/sink/inspect/partial differential for the moved family; symbol visibility and registration order | rebuild after every family; full local suite and benchmark guard; no semantic diff mixed into move commits |
| R5a | Populate existing evidence per codec and mark every unproved direction `provisional`, never `qualified` by inference | ledger schema/id coverage; evidence links resolve; current backend and build source match CMake | reviewable 50-codec matrix committed before candidate replacement starts |
| R5b+ | Research and benchmark viable permissive candidates one codec/backend at a time, starting with JPEG | same production API, fixtures, settings, output-quality/subset, warm/cold runs, sinks, memory, determinism, size/startup; oracle parity and malformed-input equivalence | build the shortlist on MSVC, then compare finalists on GCC 10 and AppleClang before selection; commit selection/rejection evidence and update baseline/ledger |
| R6a+ | Store each selected fetched dependency in-tree with provenance, license, hashes, options, and patches; switch only that dependency to local source | golden output, focused codec parity, dependency revision/options, benchmark within recorded variance | editable rebuild/full suite/Ruff per dependency; `FETCHCONTENT_FULLY_DISCONNECTED=ON` configure and sdist build |
| R6-final | Remove all default native-source network fetches and validate the packaged result | clean source checkout, offline sdist-to-wheel, wheel contents/native dependencies, NumPy-only install smoke | local MSVC plus user-authorized manylinux2014 and macOS build-only wheel matrix; docs and license inventory synchronized |

Candidate comparisons use repeated same-process medians for hot-path
throughput and fresh-process samples for RSS/startup. Record raw JSON,
toolchain/CPU/library revisions, fixture hashes, codec settings, output size or
quality, and confidence/noise. A backend wins only when correctness and the
format subset are equal; a smaller or differently lossy output is not a valid
speed comparison.

## Exit gate

No animated, RTMV, optional-library, or heavyweight codec starts until:

- current Linux normal and instrumented CI blockers are closed;
- the registry, inspection, benchmark, and cross-codec tests have the target
  family boundaries or an explicitly accepted smaller equivalent;
- the 50-id API/capability/detection snapshots are unchanged;
- default native dependencies build offline from repository-contained source;
- every current codec has a performance-ledger entry and no unexplained
  `known_gap`;
- local MSVC, Linux normal, Linux instrumented, Windows/macOS mmap, Ruff,
  sdist, wheel, and NumPy-only installed smoke all pass;
- `format_coverage.md`, `coverage_roadmap.md`, and
  `format_gap_implementation_plan.md` agree with the live registry.

This gate is about maintainability, reproducibility, and measured performance;
it does not add a separate cybersecurity workstream.
