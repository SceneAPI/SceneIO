# Next-stage implementation checklist

Status: N0.1-N0.5 remain validated at immutable implementation commit
`a5e7fa4` on `phase0-nanobind-core`, including the nonpublishing
three-platform source/wheel build. R1.1-R1.4 are complete at `95061c6`.
At that exact R1 implementation commit, local MSVC collects 2,955 tests and passes
2,951 with four documented skips; Ruff, the retained 50-codec performance
guard, a Windows abi3 wheel built from the exact `95061c6` source archive, and
its fresh NumPy-only
smoke pass. [Normal CI run 30187895845][r1-current-ci] passes the full suite,
retained performance guard, pinned GCC 10 job, and the
Ubuntu/Windows/macOS portability matrix. [Instrumented run
30187895838][r1-current-instrumented] passes the complete suite and focused
native lifetime job. [Build-only release run
30189483142][r1-current-release] builds the source archive and builds and
smoke-tests all three platform wheel sets, with its PyPI job skipped. Three independent
architecture, format/correctness, and test/benchmark reviews are clear. R2 is
next.

This is the operational checklist for the repository-organization and
codec-performance stage defined in
[`repository_organization_plan.md`](repository_organization_plan.md). It turns
R1-R6 into commit-sized work packages with explicit implementation, testing,
verification, validation, documentation, and rollback gates.

No new file format starts during this stage.

## 1. Starting checkpoint

The starting code checkpoint is `d52c1e0` on 2026-07-25:

- the live registry has 50 readable, writable, inspectable, and streamed
  codecs; 28 expose bounded partial selectors;
- local MSVC passes 2,912 tests with 4 documented skips, the all-codec
  benchmark guard, Ruff, source/wheel rebuild, and the current representative
  NumPy-only wheel smoke;
- Windows and macOS mmap jobs pass;
- [normal Linux CI run 30167201539][normal-ci] fails six tests:
  - one SQLite lock expectation;
  - three Y4M inspection paths with `std::bad_cast`;
  - two absolute 16 MiB fresh-process RSS assertions at approximately
    18.4 MiB;
- [instrumented Linux run 30167201579][instrumented-ci] fails before useful
  native coverage because `pycolmap` is removed while
  `tests/codecs/test_colmap_db.py` imports it unconditionally; its explicit
  allocation-accounting check also reports 376 bytes rooted in CPython and
  pydantic-core rather than `sceneio._core`;
- six default native dependencies still arrive through CMake
  `FetchContent`;
- the last successful build-only release matrix, run 30163127394 at
  `daf991ab`, predates ImageSequence/Y4M and the centralized license inventory;
  current-head sdist/wheel-matrix validation is pending and user-gated;
- I/O transport is optimized across the registry, but codec kernels have not
  yet been qualified per encode/decode direction. JPEG is the first known
  backend gap.

[normal-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30167201539
[instrumented-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30167201579
[release-020]: https://github.com/SceneAPI/SceneIO/actions/runs/30097907487
[r1-current-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30187895845
[r1-current-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30187895838
[r1-current-release]: https://github.com/SceneAPI/SceneIO/actions/runs/30189483142

## 2. Scope and non-goals

This stage must:

- restore green current-head Linux normal and instrumented native-reliability
  lanes without weakening behavioral or payload-relative memory assertions;
- freeze the public/runtime contract before moving files;
- split orchestration, inspectors, benchmark fixtures, cross-codec tests,
  build wiring, and bindings by format family behind compatible facades;
- create one validated performance-ledger entry for every codec and each
  applicable encode/decode direction;
- benchmark mature permissive upstream backends before selecting or retaining
  a stable kernel;
- store every selected default native source in the repository and prove
  offline builds;
- keep coverage, architecture, benchmark, provenance, and release
  documentation synchronized with the live registry.

This stage does not:

- add animated WebP, APNG, RTMV, optional scientific formats, or any other
  codec;
- change a public codec id, public import, record ABI, selector, detection
  precedence, error category, convention, or supported fidelity subset;
- introduce a runtime subprocess, plugin, separately installed Python codec,
  or external executable;
- add FFmpeg/libav source, linkage, build hooks, subprocess use, or runtime
  dependency;
- add unrelated workstreams;
- publish a package, push a release tag, or dispatch a build-only release
  workflow without the user's explicit instruction.

## 3. Dependency order and commit policy

```text
N0 current-head closure
  -> R1 contract and evidence freeze
  -> R2 Python family boundaries
  -> R3 benchmark/test family boundaries
  -> R4 CMake/binding/native layout
  -> R5 per-profile/per-direction backend qualification
  -> R6 selected-source closure
  -> cross-platform stage exit
```

Rules for every checkbox group:

- one numbered unit is one reviewable commit unless the unit explicitly names
  smaller subcommits;
- mechanical moves and semantic changes never share a commit;
- preserve the compatibility facade first, move one family, verify, then
  continue;
- after any C++ or CMake change, rebuild with
  `uv pip install -e ".[dev,test]"`;
- use `.venv/Scripts/python.exe` for all local Python commands;
- run the required Fable three-lens review—native memory/lifetime, format/API
  correctness, and test/benchmark soundness—before commit and retain the
  disposition; if Fable is unavailable, record the blocker and obtain explicit
  approval before treating a three-agent substitute as equivalent;
- use this exact commit trailer:

  ```text
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

## 4. N0 — close current-head validation blockers

No R1 work starts until N0 is green on the branch.

### N0.1 — Y4M Linux inspection portability

Implementation:

- [x] Reproduce `_core._inspect_y4m(mmap)` under the manylinux2014/GCC 10
      toolchain or the closest supported Linux container before editing.
- [x] Add a focused regression that calls `_inspect_y4m` with `bytes`,
      read-only `memoryview`, NumPy `uint8`, and read-only `mmap`.
- [x] Isolate whether the exception originates in buffer acquisition,
      `parse_y4m`, metadata conversion, or nanobind dictionary construction.
- [x] Apply the smallest portable C++ fix; do not route Linux through a Python
      bytes copy or full decode.
- [x] Keep the GIL released only around pure C++ parsing and reacquire it
      before creating Python objects.
- [x] Preserve the exact Y4M supported subset, metadata, errors, and encoded
      bytes.

Testing and verification:

- [x] Focused Y4M parity suite passes for every chroma layout, odd dimensions,
      CRLF, malformed/truncated headers, large frame counts, and selected
      ranges.
- [x] `inspect(mmap) == inspect(bytes)` and inspection metadata equals full
      decode metadata.
- [x] A mapped fixture larger than 8 MiB retains bounded traced allocation and
      does not materialize a full-file `bytes`.
- [x] Repeated inspection releases mappings/handles; exception paths do not
      retain the file.
- [x] Local MSVC behavior and golden writer bytes are unchanged.

Validation and documentation:

- [x] Rebuild and run the focused test on MSVC, GCC 10, and AppleClang.
- [x] Record the root cause and platform evidence in the commit message and
      the N0 completion section of this document.
- [x] Update `format_coverage.md` only after the normal Linux lane passes.

Exit:

- [x] All three formerly failing Y4M CI cases pass without a fallback copy.

Local completion evidence (committed as `0534266`):

- `_inspect_y4m` was reproduced under the pinned manylinux2014 GCC 10.2 image.
  The failure was a missing nanobind `std::string` caster registration when
  building the Python metadata dictionary, not buffer acquisition or Y4M
  parsing.
- The binding now includes `nanobind/stl/string.h`; no bytes fallback or
  decode path was added.
- The regression covers bytes, read-only memoryview, read-only NumPy `uint8`,
  and read-only mmap inputs against independently constructed expected
  metadata.
- Focused GCC 10.2 and MSVC tests pass. The hosted Linux and AppleClang
  portability jobs pass at `a5e7fa4`.

### N0.2 — portable COLMAP SQLite lock contract

Implementation:

- [x] State the intended contract before changing the test: read-only SceneIO
      operations either observe a consistent committed snapshot or raise a
      normalized `FormatError` for an actual conflicting lock.
- [x] Characterize rollback-journal and WAL behavior with stdlib `sqlite3` on
      Windows, Linux, and macOS.
- [x] Replace the unqualified `BEGIN EXCLUSIVE` expectation with a fixture
      that establishes the journal/locking mode and performs the operation
      required to acquire the intended conflict.
- [x] Keep the Windows file-share/locked-handle test separate from SQLite
      transaction semantics.
- [x] Change production code only if the characterized contract reveals a
      real SceneIO defect; do not force platform-specific locking merely to
      satisfy the old assertion.

Testing and verification:

- [x] Test unlocked read, committed snapshot, genuine conflicting lock,
      timeout/error normalization, rollback, and successful read after release.
- [x] Verify failed reads finalize statements and close the native handle.
- [x] Confirm read-only operations do not change database bytes or create a
      journal.
- [x] Retain independent stdlib SQLite and pycolmap parity coverage.

Validation and documentation:

- [x] Focused COLMAP DB suite passes on all three operating systems.
- [x] Add Y4M inspection, COLMAP DB lock semantics, and paired RSS controls to
      a focused Windows/Linux/macOS portability matrix; the current
      Windows/macOS mmap job does not collect the complete codec suites.
- [x] Document the portable lock contract beside the test and in the COLMAP DB
      format notes.

Exit:

- [x] The test proves a specified behavior rather than one platform's default
      lock implementation.

Local completion evidence (committed as `a09917a`):

- A WAL test proves that full, partial, and inspect reads observe the committed
  snapshot while another connection has an uncommitted write, then verifies
  rollback.
- A separate child process establishes a real rollback-journal exclusive
  write lock; all three SceneIO read paths raise normalized `FormatError`, and
  the database fingerprint and decoded values match after release.
- Optional pycolmap oracle imports are isolated to their two oracle tests, so
  stdlib/native coverage remains collected in minimal environments.
- MSVC passes the full suite. The exact pinned manylinux2014 job and hosted
  Linux, Windows, and macOS portability jobs pass the focused Y4M and COLMAP
  DB suites at `a5e7fa4`.

### N0.3 — payload-relative COLMAP RSS assertions

Implementation:

- [x] Replace the two absolute `<16 MiB` assertions with paired, warmed
      fresh-process controls that measure payload-induced growth.
- [x] Measure at least two malformed payload sizes and assert the RSS slope is
      bounded and materially sublinear to the file-controlled extent.
- [x] Keep the semantic proof: a claimed observation count and an unterminated
      image name are rejected before allocating from those extents.
- [x] Record platform baselines separately from the payload-relative
      invariant; do not raise a constant until Linux happens to pass.

Testing and verification:

- [x] Tiny semantic/warm fixtures plus 8/32 MiB measured controls raise the
      same normalized error.
- [x] Traced Python allocation remains bounded.
- [x] Fresh-process RSS variance is measured over repeated samples; the test
      reports the baseline, operation delta, and payload size on failure.
- [x] The test fails against a deliberate allocate-from-count/name control.
- [x] Keep that negative control in test-only Python/subprocess code and assert
      its expected allocation signature; do not add an allocation hook to the
      production extension.

Validation and documentation:

- [x] Run the focused RSS tests on Windows, Linux, and macOS runners.
- [x] Record the measurement method and accepted relationship in
      `bench/BASELINE.md`; do not publish one machine's absolute RSS as a
      universal bound.

Exit:

- [x] Both Linux failures pass while retaining a payload-relative regression
      signal.

Implementation evidence in progress:

- Exact malformed-input semantics are tested independently on tiny fixtures,
  so instrumented jobs do not need to create large RSS fixtures.
- RSS qualification uses fresh processes, a fixed tiny warm-up fixture, three
  repetitions per size, current plus process high-water RSS, and the median
  delta between approximately 8 MiB and 32 MiB payloads.
- The invariant is payload-relative: additional resident growth must remain
  below one quarter of additional file-controlled payload. A test-only
  transient extent-sized allocation control must fail that same assertion
  through the process high-water metric.
- On local MSVC, median SceneIO growth was 164 KiB to 160 KiB for malformed
  observation extents and 144 KiB to 160 KiB for unterminated names. The
  transient high-water control grew from approximately 8.1 MiB to 32.2 MiB.
  These values describe this host only; the slope assertion is the portable
  contract.
- The clean pinned manylinux2014 GCC 10.2 source build passes 87 focused tests
  with two expected absent-pycolmap oracle skips. The hosted three-OS
  portability matrix passes at `a5e7fa4`.

### N0.4 — instrumented native-reliability lane

Test-environment implementation:

- [x] Remove the unconditional `pycolmap` import from the COLMAP DB core test
      module or move optional pycolmap oracle cases to a separately collected
      module; do not skip the stdlib/native COLMAP DB tests when pycolmap is
      absent.
- [x] Keep gsply/Numba/LLVM and pycolmap oracle parity enabled in normal CI.
- [x] Split the instrumented job into:
  - [x] a full-suite compiler-instrumented run with exit-time allocation
        accounting disabled and the normal oracle-enabled SceneIO test
        surface;
  - [x] a focused allocation-lifetime shard in a minimal environment that
        exercises `_core`, mmap owners, sinks, records, and exception cleanup
        without unrelated native registries.
- [x] Use no diagnostic exclusions; retain the rule that any future exclusion
      must be exact-symbol and dependency-version specific and must never hide
      a SceneIO-native frame or a broad allocator.
- [x] Preserve the scheduled 100-case mmap mutation sweep.

Testing and verification:

- [x] Prove the instrumented suite collects the intended test count before
      running it.
- [x] Build retained-allocation and released-allocation sibling controls only
      in a separate instrumented test target behind an off-by-default CMake
      option.
- [x] Run each negative control in its own expected-nonzero process and assert
      the retained-allocation signature/source frame, not only the exit code.
- [x] Assert the test-only source/symbol is absent from the default `_core` and
      every normal wheel.
- [x] Confirm the minimal CPython/NumPy process baseline does not fail the
      SceneIO allocation-lifetime shard; pydantic is deliberately absent from
      that shard.
- [x] Confirm a SceneIO-owned native allocation stack fails the job through
      the isolated `_native_test` target. Production `_core` deliberately
      contains no retained-allocation hook.
- [x] Keep compiler-runtime diagnostics configured to stop at the first error
      and preserve GIL/lifetime regression tests.

Validation and documentation:

- [x] The instrumented workflow passes twice: one push run and one explicit
      rerun or scheduled-equivalent run.
- [x] Record collected/passed/skipped counts and the exact minimal dependency
      set.
- [x] Update the CI status rows in `format_coverage.md`,
      `coverage_roadmap.md`, and `io_optimization_plan.md`.

Exit:

- [x] Normal Linux, instrumented Linux, Windows mmap, and macOS mmap jobs are
      all green at the same commit.

Local implementation evidence (committed as `0a2db6e`):

- The instrumented workflow now has separate full-suite compiler-diagnostic
  and focused allocation-lifetime jobs. The first installs the complete
  `[dev,test]` oracle surface plus CPU Torch, asserts gsply/Numba/LLVM and
  pycolmap imports, requires exactly 2,923 collected tests, and retains the
  scheduled 100-case mmap mutation sweep.
- The allocation-lifetime job installs SceneIO without dependencies into a
  runtime containing only CPython and NumPy. Its standalone shard exercises
  NPY buffer and mapped ownership, an array view outliving the source path and
  record, the direct sink, malformed-input cleanup, and a PointCloud view
  outliving its record.
- `SCENEIO_BUILD_NATIVE_TEST_HOOKS` is off by default and requires the
  instrumented build. It creates a separate `_native_test` extension with
  released and deliberately retained 12,345-byte allocation controls plus
  one controlled default LAZperf decoder; the compact decoder is exercised
  only in its separate executable. The module is never linked into `_core`.
  Default-source tests and installed-wheel smoke assert that the extension and
  all test symbols are absent.
- In isolated manylinux2014 GCC 10 processes, the lifetime shard and clean
  control return zero. The deliberate control returns nonzero and reports
  exactly 12,345 retained bytes with a SceneIO-owned frame in
  `native_test.cpp`.
- A reduced-oracle but otherwise complete local instrumented GCC 10 run
  finished 2,898 executed items: 2,825 passes and 73 expected skips, with no
  compiler-runtime diagnostic after the LAZ fix. A stale separate note had
  recorded 2,895 collected tests and is intentionally discarded rather than
  presented as exact evidence. The hosted full-oracle job is still required;
  a local attempt to install its complete dependency surface exceeded the
  15-minute diagnostic window and is not counted as evidence.
- The instrumented run found signed overflow in the pinned LAZperf
  malformed-layer integer path. The local patch now uses defined full-range
  arithmetic, and 62 LAZ tests pass on MSVC, including exact `INT32_MIN` and
  `INT32_MAX` transitions and a content-pinned bytes/mmap mutation. A clean
  CMake source configure patches both upstream text occurrences and a repeated
  configure preserves the fetched header timestamp.
- CMake now accepts only exactly two original corrector blocks or exactly two
  patched blocks; any mixed or changed upstream state fails configuration. A
  separate default-decoder translation unit and a
  `COMPRESS_ONLY_K` translation unit use controlled `k=31` symbols and require
  the exact `LAZperf integer corrector is out of range` result. The normal
  option-off MSVC rebuild and 108 focused default-build/LAZ tests pass. The
  manylinux2014 GCC 10.2 instrumented build compiles `lazperf_static`, the
  independent normal/compact arithmetic executables, and `_native_test`; the
  executables prove both rejection paths while the module repeats the normal
  check. Keeping the macro variants in separate binaries avoids differing
  LAZperf class definitions in one program.
- Three-agent re-review status: platform/provenance is clear; test/performance
  findings about fixture identity and benchmark arithmetic are resolved. The
  architecture lens identified three gaps: direct corrector-range proof,
  exact CMake occurrence counts, and compilation of the optional
  `COMPRESS_ONLY_K` branch. Implementations for all three are now present and
  pass instrumented GCC 10 execution. The final memory/lifetime,
  format/correctness, and test/benchmark re-reviews are clear.
- The exact option-off MSVC worktree collects 2,923 tests and passes 2,919
  with four documented skips. Ruff, workflow YAML parsing, installed-source
  wheel smoke, and `git diff --check` pass.
- The first complete hosted workflow execution at follow-up commit `a5e7fa4`
  passes. The exact run and repeat evidence is recorded under N0.5.

### N0.5 — closure regression and evidence commit

- [x] Run the complete local MSVC suite.
- [x] Run Ruff and `git diff --check`.
- [x] Run the 50-codec benchmark smoke and retained O4/O5 guard.
- [x] Rebuild an sdist and Windows cp312-abi3 wheel.
- [x] Install the wheel into a clean NumPy-only environment and run
      `sceneio._wheel_smoke`.
- [x] Create a locally green candidate commit; do not amend it after push.
- [x] With explicit user authorization, push the candidate commit and require
      normal Linux, instrumented Linux, and the focused three-OS portability
      matrix at that exact SHA.
- [x] Fix remote failures in follow-up commits and repeat; do not rewrite a
      pushed validation SHA.
- [x] Mark N0 complete and update the latest tested checkpoint/workflow links
      only after all required jobs are green at one exact commit.

Candidate and follow-up evidence:

- The exact option-off worktree collects 2,923 tests and passes 2,919 with four
  documented skips. Ruff, workflow YAML parsing, installed-source smoke, and
  `git diff --check` pass.
- The one-run, `--scale 0.001` 50-codec smoke passes. The first
  production-scale five-run guard reported one non-reproduced LAS
  parallel-read reversal at 0.75x. An immediate `--only las --runs 5`
  diagnostic measured 1.43x, and the complete 50-codec rerun measured 1.82x
  for the same row while passing every retained O4/O5 directional and
  mmap/sink memory guard. The isolated diagnostic changed only scope to LAS;
  the two complete guards used identical thresholds, fixtures, codec set, and
  lane counts.
- Reproduction sequence:
  `bench/bench_io.py --runs 1 --scale 0.001`,
  `bench/bench_io.py --runs 5 --require-o4-gains
  --require-o5-inspect-gains --require-o5-partial-gains`,
  `bench/bench_io.py --only las --runs 5`, then the unchanged complete
  five-run guard again. Each invocation also used `--json` to retain its
  result under `build/`.
- The sdist-first build from `c759f3c` produced
  `sceneio-0.2.0.tar.gz` (3,991,461 bytes,
  SHA-256 `ae88d34145de7e60c4d78bae2734b09a5f197c8db4502a1ffb60eeb53baf688c`).
  Building the Windows wheel from that exact archive produced
  `sceneio-0.2.0-cp312-abi3-win_amd64.whl` (2,155,051 bytes,
  SHA-256 `b8bc9019e2de94aa07a77596187b90275cdefb68b51a5267ebe669d5f59849d`).
- The wheel has 53 entries, exactly one native module (`sceneio._core`), no
  native test target, and no top-level build/include/lib/share/bin content.
  Its packaged `LICENSES/` set exactly equals the repository inventory, and
  NumPy is its only unconditional dependency.
- A fresh Python 3.12 environment resolved only SceneIO 0.2.0 and NumPy 2.5.1;
  `sceneio._wheel_smoke` passed. The installed `_core` depends only on
  `python312.dll`, standard Windows system libraries, and the Microsoft C/C++
  runtimes.
- At `c759f3c`, [normal CI run 30179410121](https://github.com/SceneAPI/SceneIO/actions/runs/30179410121)
  passed the full suite, retained benchmark guard, pinned GCC-10 job, and
  Ubuntu/Windows/macOS mmap matrix. The
  [wheel-build dry run 30179409882](https://github.com/SceneAPI/SceneIO/actions/runs/30179409882)
  built and smoke-tested all three platform wheels plus the sdist; its publish
  job was correctly skipped.
- The focused native job in
  [compiler-instrumented run 30179410118](https://github.com/SceneAPI/SceneIO/actions/runs/30179410118)
  passed. The full job exited twice at the first format-0
  `INT32_MAX`/`INT32_MIN` oracle transition. An isolated Linux reproduction
  identified signed coordinate reconstruction in LAZperf legacy and layered
  point paths.
- The follow-up uses a single documented modulo-2^32 helper for legacy and
  layered encode/decode coordinates, performs compressor folding in a wider
  intermediate, and adds direct addition, subtraction, magnitude, high-bit,
  and compressor boundary checks. It passes 2,919 local MSVC tests with four
  documented skips, the 62-test LAZ suite under focused GCC 13 instrumentation,
  and the same 62-test suite in a fresh manylinux2014 GCC-10 build.
- An uncontended five-run LAZ benchmark after the fix measured 229 MB/s
  in-memory read and 178 MB/s mmap-path read, versus the earlier 179/168 MB/s
  ordinary checkpoint. Inspection remained 1,091x faster than full read,
  partial read remained 3.24x faster, and bytes/sink writes both measured
  63 MB/s with the expected allocation reduction.
- The exact follow-up source archive is 3,997,331 bytes with SHA-256
  `c4e0491aee633944adc15130fbf53d1ad4f674a559d00de0c30120bb00d9406e`.
  Its Windows cp312-abi3 wheel is 2,155,107 bytes with SHA-256
  `372ff25738d89e3d1599c4a81895578540bdcf321b3538d9e5d8b08aa12eec3b`.
  A fresh Python 3.12 environment resolved only SceneIO 0.2.0 and NumPy 2.5.1,
  and `sceneio._wheel_smoke` returned 2.
- At immutable implementation commit `a5e7fa4`,
  [normal CI run 30181287022](https://github.com/SceneAPI/SceneIO/actions/runs/30181287022)
  passes 2,914 tests with nine documented platform/oracle skips, the retained
  50-codec performance guard, the pinned GCC 10 job, and the Linux, Windows,
  and macOS portability matrix. The hosted LAZ row retains zero traced
  whole-input/whole-output allocation on the mmap and sink paths; its
  inspection and partial selectors remain faster than full decode.
- The
  [nonpublishing release dry run 30181286675](https://github.com/SceneAPI/SceneIO/actions/runs/30181286675)
  builds and smoke-tests Linux, macOS, and Windows wheel sets plus the source
  archive. Its PyPI job is skipped, as required.
- The first execution of
  [compiler-instrumented run 30181287161](https://github.com/SceneAPI/SceneIO/actions/runs/30181287161)
  collects exactly 2,923 tests and passes 2,894 with 29 documented skips.
  Its focused native lifetime job also passes. Explicit attempt 2 at the same
  immutable commit repeats the exact 2,923-test collection, 2,894 passes and
  29 documented skips, and the focused native lifetime pass. N0 is closed;
  R1 contract and evidence freeze is next.

## 5. R1 — freeze contracts and evidence

R1 makes later moves observable. It may add internal immutable metadata and
checked fixtures, but it must not change codec adapters, dispatch, detection,
registration semantics, or public API behavior.

### R1.1 — codec manifest and family ownership

- [x] Keep the existing frozen `Codec` value type as the registration schema;
      do not create a parallel `CodecDefinition` abstraction.
- [x] Define immutable built-in definition tuples with one owning family per
      built-in codec: arrays, calibration, images, meshes, points,
      reconstruction, sequences, or splats.
- [x] Record `implementation_owner = native | python | hybrid` and the expected
      native/Python adapter symbols for every built-in definition.
- [x] Keep immutable `BUILTIN_DEFINITIONS` separate from the mutable runtime
      `REGISTRY`; repository family, documentation, benchmark, and source
      completeness rules apply to built-ins, not third-party registrations.
- [x] Keep `sceneio.io.registry` as the compatibility facade.
- [x] Keep R1 ownership metadata side-effect free and preserve the existing
      explicit canonical registration order. Actual side-effect-free family
      `Codec` tuples, validate-before-install aggregation, and aggregate
      reload/idempotence are R2 work because moving definitions in R1 would
      contradict the behavior-preserving boundary.
- [x] Add uniqueness tests for built-in codec id/family membership and
      `REGISTRY` object identity. Aggregate reload/idempotence remains an R2
      exit condition after shared state is extracted.
- [x] Assert the built-in family union is exactly the current 50-id built-in
      set in `BUILTIN_DEFINITIONS`; repository completeness checks deliberately
      ignore additional runtime registrations.
- [x] Assert every built-in codec has explicit benchmark, source-suite,
      installed-wheel smoke, and documentation inclusion or a documented
      exemption.
- [x] Prove a third-party codec can register without a SceneIO family, ledger,
      source-suite, or documentation row, while duplicate built-in IDs still
      fail.

### R1.2 — compatibility snapshots

- [x] Snapshot codec ids and ordering where order affects detection.
- [x] Snapshot capability fields, native features, public imports, and `_core`
      symbol names.
- [x] Pin the full canonical built-in order and every extension, magic,
      filename, and directory collision—not only known ambiguous formats such
      as point/mesh/Gaussian PLY and generic text.
- [x] Pin buffer/path/directory container kinds and selectors.
- [x] Pin public exception categories and representative message prefixes;
      avoid brittle full-message snapshots.
- [x] For registry, discovery, and inspection metadata value types, pin
      identity across re-export paths,
      `__module__`, `__qualname__`, normalized repr shape, and the current
      per-type pickle outcome. `Codec` currently contains local adapter
      closures and therefore has a pinned `AttributeError`; the other frozen
      metadata outcomes are recorded. Compiled record re-export identities are
      pinned separately without imposing a new repr/pickle contract.
- [x] Pin benchmark CLI arguments, rejection rules, result order, and existing
      heterogeneous bare-list JSON row shapes.
- [x] Add an architecture test that fails on an unowned built-in codec, missing
      inspector, missing benchmark row, missing test case, or missing
      documentation capability row.
- [x] Add a checked-in built-in-to-native symbol map and compare it with the
      current `_core` symbol snapshot until R4 replaces it with a
      machine-readable native inventory.

### R1.3 — performance-ledger skeleton

- [x] Add `bench/PERFORMANCE_STATUS.toml`.
- [x] Model `built-in codec × performance-relevant profile × direction`; each
      profile records settings, fidelity class, comparator, fixture corpus,
      backend, and one of these states:
      `qualified`, `provisional`, `known_gap`, `native_by_necessity`, or
      `not_applicable`.
- [x] Require profiles for materially different paths such as WebP
      lossless/lossy, PNG 8/16-bit, PLY encodings, PCD storage modes, EXR
      compression/layouts, and LAS/LAZ point-format families.
- [x] Mark unproved directions `provisional`; never infer `qualified` from
      correctness or optimized transport.
- [x] Record current adapter, backend, source location, version/SHA, evidence
      link, candidate set, and accepted subset.
- [x] Add a `tomllib` schema/id coverage test.
- [x] Seed only evidence already present in `bench/BASELINE.md`; record JPEG
      encode/decode as `known_gap`.
- [x] A codec is qualified only when every required profile/direction is
      qualified, `native_by_necessity`, `not_applicable`, or has an explicitly
      approved exemption.

### R1.4 — active versus historical documentation

- [x] Keep current capabilities/status in `format_coverage.md`.
- [x] Keep the active dependency queue in
      `format_gap_implementation_plan.md`.
- [x] Move the completed Waves A-C evidence without rewriting it to
      `docs/plans/completed/`; retain the format-level G2-G4.2 contract/status
      ledger until its later scheduled archive unit.
- [x] Preserve stable relative links or provide explicit replacement links.
- [x] Add a documentation consistency/link test for current-status entry
      points.
- [x] Update README development links.

R1 verification and validation:

- [x] Initial R1 snapshots match the unchanged runtime surface; subsequent R1
      and R2 changes must continue to match them.
- [x] Import boundaries are checked with three-sample fresh-process medians and
      an optional-oracle import exclusion. R1 adds only the
      approved lightweight `_builtin_manifest` module to the eager
      `sceneio.io` boundary and stays within the recorded Windows alert band.
- [x] R1a/R1b local verification passes 2,951 tests with four documented
      skips, Ruff, the 50-row all-format structural benchmark smoke, the
      five-run retained performance guard, documentation case/link/anchor and
      archive-digest checks, and the editable package smoke.
- [x] The retained five-run benchmark guard passes. A clean Windows abi3 wheel
      built from the exact `95061c6` source archive installs into a fresh
      NumPy-only environment, `_wheel_smoke` returns 2, and artifact inspection
      finds the compiled extension, all 15 license files, and no excluded
      build/development directories. The source archive includes both
      completed-plan files and every R1 contract/ledger fixture.
- [x] The R1 diff contains tests/docs/schema plus internal ownership metadata
      and the immutable `BUILTIN_DEFINITIONS` projection only—no codec adapter,
      dispatch, detection, or public behavior change.
- [x] Dispatch the user-authorized exact-R1-head build-only wheel matrix and
      require its source archive plus Linux, macOS, and Windows wheel jobs to
      pass with publication skipped.

R1 implementation-checkpoint closure evidence:

- [x] Follow-up commit `95061c6` normalizes the two equivalent CPython
      local-callable pickle messages without changing runtime or codec
      behavior.
- [x] Local MSVC collects exactly 2,955 tests and passes 2,951 with four
      documented skips. Ruff, `git diff --check`, the 50-codec smoke, and the
      retained five-run performance/memory guard pass.
- [x] The exact `95061c6` source archive produces a Windows cp312-abi3 wheel
      containing 54 files, all 15 indexed licenses, exactly one native module,
      and no excluded build directories. A fresh NumPy-only install passes
      `_wheel_smoke`.
- [x] Normal CI run 30187895845 and instrumented run 30187895838 pass at exact
      commit `95061c6`, including GCC 10 and focused
      Ubuntu/Windows/macOS portability jobs.
- [x] Build-only release run 30189483142 builds the source archive and builds
      and smoke-tests Linux, macOS, and Windows wheels at exact commit
      `95061c6`; its PyPI job is skipped.
- [x] Three independent reviewers report no unresolved R1 finding.

## 6. R2 — split Python orchestration by family

Complete R2.0 first, then repeat R2.1-R2.4 for one family per commit.

### R2.0 — remove sequence-to-registry upward dependencies

- [ ] Move the image-extension catalog and inspector dispatch contract to a
      lower-level internal module that neither imports `REGISTRY` nor the
      public `sceneio` package.
- [ ] Inject those dependencies into the image-sequence adapter instead of
      resolving them through deferred upward imports.
- [ ] Exercise `_image_extensions()` and `_frame_metadata()` at runtime in an
      isolated import-cycle test; a static import graph alone is insufficient.
- [ ] Preserve sequence detection order, selected-frame semantics, metadata,
      normalized errors, and import/startup measurements.

### R2.1 — extract shared model and adapters

- [ ] Move codec/capability value types, mmap/path/sink adapters, detection,
      and native-feature metadata behind the existing facade.
- [ ] Keep import direction acyclic:
      family definitions -> shared model/adapters; facade -> family aggregate.
- [ ] Do not let family modules import the public `sceneio` package.
- [ ] Add import-cycle and import-isolation tests.
- [ ] Preserve public value-type identity, `__module__`, `__qualname__`, repr,
      and pickle compatibility; leave definitions in the facade when moving
      them would create an avoidable compatibility break.

### R2.2 — move family registrations

- [ ] Move one family's built-in `Codec` definitions without changing values
      or canonical ordering.
- [ ] Keep family exports immutable and side-effect free; only the aggregate
      populates the existing `REGISTRY` object.
- [ ] Compare serialized capability snapshots byte-for-byte.
- [ ] Run family parity, public E2E, detection, mmap/sink, inspection, partial,
      and capability tests.

### R2.3 — move family inspectors

- [ ] Keep `_inspection.py` as a compatibility facade.
- [ ] Move common parsing helpers only after two families use the same
      invariant; avoid a new miscellaneous helper module.
- [ ] Prove inspect/full agreement, malformed errors, bounded allocation, and
      no full decode.

### R2.4 — per-family exit

- [ ] Full suite and Ruff pass.
- [ ] Benchmark smoke and retained guards pass.
- [ ] Import/startup and public symbols show no regression.
- [ ] Diff is a behavior-preserving move plus focused architecture tests.

R2 exits after all eight families move and the facade remains source
compatible.

## 7. R3 — split benchmark and cross-codec tests

### R3.1a — mechanical benchmark model/runner/reporting split

- [ ] Extract data models, timing, traced allocation, the existing warmed
      parent-process RSS sampler, and reporting without changing behavior.
- [ ] Pin JSON output schema and representative fixture hashes.
- [ ] Compare old/new output from the same commit and fixture seed.
- [ ] Preserve the existing metric under an explicit `in_process_rss` name;
      do not relabel it as fresh-process evidence.

### R3.1b — qualification-grade memory protocol

- [ ] Add a child-process protocol that imports and warms SceneIO, records its
      baseline, performs exactly one measured operation, and reports peak and
      delta RSS.
- [ ] Repeat across payload sizes and samples; report baseline, delta, payload
      size, platform, and sampler availability.
- [ ] Make `psutil` mandatory in strict qualification mode. Missing RSS
      support is `unavailable` and fails qualification; it is never numeric
      zero.
- [ ] Keep throughput timing outside tracemalloc and memory sampling.
- [ ] Add fixtures proving a bounded operation passes and an intentional
      full-payload allocation fails.

### R3.2 — family fixtures and oracles

- [ ] Move builders/oracles one family at a time.
- [ ] Keep oracle dependencies test-only.
- [ ] Fail if a built-in codec is silently absent; prove an extra runtime
      registration does not enter repository fixture/oracle completeness.
- [ ] Add a strict qualification mode in which every declared oracle must be
      installed and runnable; optional `_try(...)` behavior is allowed only
      for developer smoke runs.
- [ ] When no library oracle exists, require an independent spec-level parser
      or a reviewed exemption with the exact unverified property recorded.
- [ ] Keep generated 100 MiB-class fixtures out of Git.

### R3.3 — cross-codec test support

- [ ] Commit a centralized buffer/path/directory catalog in
      `tests/_support/codec_cases.py` without consuming it.
- [ ] Migrate mmap consumers while retaining the old matrix until exact
      equivalence is demonstrated.
- [ ] Migrate streaming consumers in a separate commit under the same rule.
- [ ] Migrate inspection consumers in a separate commit under the same rule.
- [ ] Migrate partial consumers one family at a time under the same rule.
- [ ] Remove an old matrix only after its replacement is proven equivalent.
- [ ] Preserve parameter ids so CI failures remain attributable.
- [ ] Avoid snapshot-only assertions for numeric values, conventions, or
      malformed inputs.
- [ ] Compare sorted pytest node ids, parameters, and skip reasons before and
      after. Record an explicit rename mapping; test count alone is
      insufficient.

### R3.4 — complete installed-wheel smoke

- [ ] Drive wheel smoke from `BUILTIN_DEFINITIONS`, not a hand-maintained
      helper list.
- [ ] Assert the smoke-case id union equals the exact installed built-in
      registry id set.
- [ ] Perform a NumPy-only write/read/inspect operation for each of the 50
      built-ins, plus streaming and selectors where the manifest declares
      them.
- [ ] Require a reviewed, property-specific exemption for any operation a
      minimal generated fixture cannot exercise.

R3 verification and validation:

- [ ] One-run all-codec smoke produces the same codec set and JSON fields.
- [ ] Five-run O4/O5 controls retain direction and memory relationships.
- [ ] Strict qualification mode fails on an absent required oracle or RSS
      sampler instead of silently dropping evidence.
- [ ] Full suite and Ruff pass after each family.
- [ ] `bench/bench_io.py` remains the compatible CLI entry point.

## 8. R4 — organize CMake, bindings, and native files

### R4.1 — split build configuration

- [ ] Extract dependency declarations, SceneIO source lists, instrumented
      options, and third-party targets into focused `cmake/` files.
- [ ] Preserve every option default, compile definition, source, link target,
      visibility setting, and platform conditional.
- [ ] Add configure-time assertions for missing/duplicate SceneIO sources.
- [ ] Compare CMake cache variables and verbose compile/link commands before
      and after on MSVC and GCC 10.

### R4.2 — split binding registration

- [ ] Add family registration functions under `src/cpp/bindings/`.
- [ ] Preserve record-before-codec construction and the `_core` symbol
      snapshot.
- [ ] Keep one declaration/definition owner for every registration function.
- [ ] Generate a private machine-readable `_core.__codec_inventory__` from the
      same native family tables. Include built-in id, family, and available
      read/write/inspect/stream/partial symbols.
- [ ] Compare the native inventory exactly with the `native`/`hybrid`
      projection of `BUILTIN_DEFINITIONS`; separately resolve and validate the
      declared symbols for `python`/`hybrid` adapters.
- [ ] Fail on an orphaned, multiply owned, or owner-mismatched codec.
- [ ] Rebuild after every family move and run an explicit import/symbol smoke.

### R4.3 — move native codecs by family

- [ ] Move files mechanically; do not split cohesive parsers solely because
      they are large.
- [ ] Fix include paths/build lists only.
- [ ] Maintain explicit per-family CMake source manifests and assert that
      every SceneIO native codec source has exactly one owner.
- [ ] Run family parity, bytes/mmap, sink, inspect, partial, lifetime, and
      malformed-input tests after each move.
- [ ] Confirm no exported native symbol or wheel content change.

R4 verification and validation:

- [ ] Editable builds pass on MSVC and GCC 10.
- [ ] Full local suite, Ruff, all-codec benchmark guard, sdist, wheel, and
      NumPy-only smoke pass.
- [ ] Windows/macOS mmap and Linux normal/instrumented jobs pass at the final
      R4 commit.
- [ ] The public/API snapshots remain unchanged.

## 9. R5 — qualify codec backends before selection

R5 is performed one codec, performance profile, and applicable direction at a
time. Popularity is candidate-discovery evidence, not performance evidence.

### R5.1 — candidate intake

- [ ] List every viable mature permissive candidate and its exact version/SHA,
      license, maintenance status, supported subset, build system, SIMD/thread
      support, and supported compilers.
- [ ] Record why a candidate is excluded.
- [ ] Confirm the candidate can be pinned, built statically/offline, hidden
      inside `_core`, and attributed.
- [ ] Integrate candidate source only in a non-default qualification target
      with a test-only selector; default wheels and the public API must not
      expose the candidate before selection.
- [ ] Assert qualification-only options, symbols, and sources are absent from
      default wheels.
- [ ] Start with the JPEG encode/decode comparison against libjpeg-turbo and
      any other viable permissive finalist.

### R5.2 — fair production-path benchmark

- [ ] Benchmark through SceneIO's actual public/core adapter, not an isolated
      library microbenchmark.
- [ ] Define the full codec × profile × direction matrix before running. Do
      not let one easy encoding mode qualify materially different paths.
- [ ] Use identical canonical records, output subset, quality/subsampling,
      thread/lane policy, compiler mode, and warm/cold methodology.
- [ ] For decoder comparisons, feed every candidate the same hashed encoded
      corpus. Never compare decoder throughput when each encoder produced
      different bytes.
- [ ] Record each decoder fixture's producer, version, settings, provenance,
      hash, and accepted-subset coverage. Include streams from the retained
      writer and an independent reference/spec fixture where possible; a
      candidate's own output is never its sole decode corpus.
- [ ] Measure encode and decode separately:
  - [ ] throughput/latency for small, representative, and generated large
        fixtures;
  - [ ] public mmap/path read and direct-sink write;
  - [ ] traced allocation and fresh-process RSS;
  - [ ] one lane and bounded automatic lanes where supported;
  - [ ] output size and, for lossy codecs, decoded quality under the existing
        parity metric;
  - [ ] deterministic bytes where the format/backend contract permits them;
  - [ ] wheel size, import time, and first-call startup.
- [ ] Record raw JSON, fixture hashes, CPU/toolchain, compiler flags, library
      revisions, settings, sample order, sample count, median, MAD, and paired
      candidate/baseline ratios.
- [ ] Randomize or interleave candidate order after fixed warmups, repeat
      sessions on the same machine, and predeclare the noise/outlier policy.
      Retain raw samples; do not delete inconvenient outliers after inspection.
- [ ] Label cold-cache data valid only when cache eviction is confirmed.
      Advisory cache hints are reported as best-effort, not cold-cache proof.
- [ ] Build the shortlist on MSVC, then compare finalists on manylinux2014
      GCC 10 and AppleClang before selection.

### R5.3 — correctness and compatibility gate

- [ ] Decoder parity uses the same encoded corpus and requires exact canonical
      output for lossless/raw paths or the pinned tolerance for lossy decode.
- [ ] A lossless writer is accepted when an independent decoder recovers the
      exact canonical record. Encoded-byte identity is required only where
      frozen deterministic bytes are already part of the contract.
- [ ] A lossy writer uses a pinned corpus covering quality, output size,
      metadata, alpha handling, and subsampling, and must be non-inferior under
      the documented parity metric. A smaller or lower-quality output is not a
      valid speed win.
- [ ] Predeclare per-profile comparative quality metrics, non-inferiority
      margins versus the retained backend, corpus aggregation/confidence
      rules, and file-size matching bounds before measurement. Both candidates
      passing an older absolute tolerance is not sufficient.
- [ ] Malformed/truncated inputs, convention guards, and unsupported features
      retain the same normalized behavior.
- [ ] Determinism is proved one versus many lanes and across repeated runs.
- [ ] If a backend migration changes deterministic encoded bytes, isolate it
      in a dedicated compatibility decision with updated goldens and release
      notes; never hide it inside a refactor.
- [ ] Existing Python/runtime dependency remains NumPy-only.

### R5.4 — selection and ledger update

- [ ] Select the fastest conforming candidate per profile/direction across the
      supported toolchains.
- [ ] If platform winners differ, prefer one portable backend unless the
      measured gain justifies a documented platform dispatch with identical
      behavior.
- [ ] Switch the default backend in a dedicated revertible commit and retain
      the old backend until the user-gated three-platform qualification matrix
      passes at that exact commit.
- [ ] Before removing the superseded backend, add a persistent qualification
      regression workflow for affected codec/backend/build changes and a
      scheduled run. On the same runner it compares the checkout with the
      ledger's pinned `qualified_commit`, using the same hashed corpus,
      interleaved subprocess samples, child-process RSS, and recorded noise
      envelope; a noisy failure requires a confirming rerun.
- [ ] Remove the superseded backend, if it has no other consumer, only in a
      later commit after remote validation and the persistent guard is green.
- [ ] Record retained, replaced, and rejected candidates in
      `PERFORMANCE_STATUS.toml` and `bench/BASELINE.md`.
- [ ] A profile/direction becomes `qualified` only when candidate discovery,
      three-toolchain measurement, correctness, build, and maintenance gates
      are complete.
- [ ] `native_by_necessity` requires documented candidate research and an
      independent oracle; it is not a synonym for “not benchmarked.”

R5 per-backend exit:

- [ ] Focused parity/malformed/lifetime/determinism tests pass.
- [ ] Same-run benchmark shows the selected gain with no retained-path
      regression.
- [ ] Full suite, Ruff, all-codec guard, local sdist/wheel, and clean smoke
      pass.
- [ ] Windows, Linux, and macOS build/benchmark evidence is linked.
- [ ] Three-lens review has no unresolved finding.
- [ ] With explicit user authorization, the nonpublishing backend
      qualification workflow passes the old/new A/B pair on MSVC,
      manylinux2014 GCC 10, and AppleClang at the exact selection commit.

## 10. R6 — close selected default sources

Perform one dependency per commit.

### R6.1 — provenance and source intake

- [ ] Store the exact selected source under
      `src/cpp/third_party/<project>/`.
- [ ] Add `COMMIT.txt` with upstream URL, tag/SHA, archive/source hashes,
      source files built, disabled components, build options, and local
      patches.
- [ ] Copy the exact upstream license/notice into `LICENSES/` and update its
      index.
- [ ] Preserve local changes as reviewable patch files or narrowly marked
      source edits.
- [ ] Disable tools, examples, tests, shared libraries, install rules, and
      unused codecs.

### R6.2 — local-source build switch

- [ ] Switch only that dependency from `FetchContent` to the in-tree source.
- [ ] Verify compile definitions, hidden visibility, static linkage, and
      enabled source files match the selected benchmark build.
- [ ] Prove focused codec goldens/parity and benchmark results remain within
      the recorded variance.
- [ ] Run the complete rebuild/test/lint/wheel smoke gate.

### R6.3 — offline and package closure

- [ ] Start from a clean checkout and empty CMake/download caches. Either
      disable PEP 517 build isolation and use pinned preinstalled build tools,
      or provide a locked, pre-populated `PIP_FIND_LINKS` wheelhouse inside
      every build container.
- [ ] Set `PIP_NO_INDEX=1`, configure with
      `FETCHCONTENT_FULLY_DISCONNECTED=ON`, and deny network access during the
      native-source build.
- [ ] Build the sdist first. Make every wheel job depend on that sdist,
      download and unpack the exact artifact, and build its wheel from the
      unpacked sdist rather than a fresh repository checkout.
- [ ] Inspect the wheel for unexpected headers, static archives, build trees,
      undeclared DLLs/shared objects, or duplicate native libraries.
- [ ] Verify NumPy remains the only unconditional runtime dependency.
- [ ] Assert the root license and every file indexed by `LICENSES/README.md`
      are present in both the sdist and every wheel.
- [ ] Verify no FFmpeg/libav source, symbol, library, executable, build hook,
      or package metadata entered the repository or wheel.

R6 exits when:

- [ ] all selected default sources are repository-contained;
- [ ] no default CMake configure path downloads native source;
- [ ] every dependency has current provenance/license/patch metadata;
- [ ] native-source-offline MSVC, manylinux2014 GCC 10, and AppleClang
      sdist-to-wheel builds pass (NumPy is separately pre-provisioned for
      installed-wheel smoke, not required to compile the package);
- [ ] all 50 codecs pass the installed-wheel smoke.

## 11. Documentation checklist for every unit

Review every surface below for each unit, update only the surfaces affected by
the change, and always update this checklist. Unrelated documents do not
receive churn solely to touch every file.

- [ ] `docs/format_coverage.md`: current capability and validation status.
- [ ] `docs/coverage_roadmap.md`: declared destination/policy only.
- [ ] `docs/format_gap_implementation_plan.md`: active queue and package
      status.
- [ ] `docs/repository_organization_plan.md`: architecture/performance gate
      status.
- [ ] This checklist: completed boxes, commit SHA, test counts, benchmark
      evidence, workflow links, and remaining blockers.
- [ ] `docs/core_architecture.md`: actual current layout, not the future layout.
- [ ] `docs/io_optimization_plan.md`: historical O0-O5 facts plus current
      qualification distinction.
- [ ] `bench/BASELINE.md` and `bench/PERFORMANCE_STATUS.toml`: measurements and
      backend state.
- [ ] `README.md`: only public commands/APIs and stable engineering entry
      points.
- [ ] `src/cpp/third_party/*/COMMIT.txt` and `LICENSES/`: provenance,
      attribution, and patches when dependencies change.

Documentation claims use these terms:

- **implemented locally**: code and focused tests exist;
- **verified locally**: full local suite, lint, differential/memory tests,
  benchmark, wheel smoke, and review pass;
- **validated**: required MSVC, GCC 10, AppleClang, instrumented, sdist, and
  wheel lanes pass;
- **qualified backend**: viable candidates were recorded and finalists passed
  three-toolchain performance/correctness/build comparison;
- **shipped**: matching-tag artifacts were published and smoke-tested.

## 12. Standard local verification commands

For a C++/CMake unit:

```powershell
uv pip install -e ".[dev,test]"
.venv/Scripts/python.exe -c "from sceneio import _core; print(_core)"
```

For every unit:

```powershell
.venv/Scripts/python.exe -m pytest -q <focused-tests>
.venv/Scripts/python.exe -m pytest -q tests/test_io_api.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check
git diff --check
.venv/Scripts/python.exe bench/bench_io.py --runs 5 --require-o4-gains --require-o5-inspect-gains --require-o5-partial-gains
.venv/Scripts/python.exe -m sceneio._wheel_smoke
```

Additional unit-specific commands and fixture hashes are recorded in the
commit and this checklist. A near-threshold or noisy benchmark is rerun with
more samples; it is not rounded into a claimed win.

## 13. Stage exit and user-gated remote validation

Local exit:

- [ ] N0 and R1-R6 are complete in green commits.
- [ ] Worktree is clean and all authoritative documents agree.
- [ ] Full local MSVC suite, Ruff, 50-codec benchmark guard, sdist/wheel, and
      NumPy-only smoke pass.
- [ ] Every required codec/profile/direction is `qualified`,
      `native_by_necessity`, or an explicitly approved `provisional`
      exception; no unexplained `known_gap` remains.
- [ ] Default native builds are offline from repository-contained source.

Remote validation checkpoints, only after explicit user authorization:

- [x] At N0, push the reviewed candidate and require green normal,
      instrumented, and focused three-OS portability workflows at the exact
      SHA.
- [ ] At each backend selection in R5, dispatch a nonpublishing old/new A/B
      qualification matrix on MSVC, manylinux2014 GCC 10, and AppleClang.
- [ ] At final R6 exit, push the reviewed branch and dispatch the build-only
      `publish.yml` workflow. Its wheel jobs consume the exact sdist produced
      by its sdist job.
- [ ] Download and inspect manylinux2014 x86-64, macOS arm64, Windows amd64
      abi3 wheels, plus the sdist.
- [ ] Record workflow URLs, artifact hashes, wheel tags, dependency closure,
      installed capabilities, and smoke results.
- [ ] Do not create or push a release tag during validation.
- [ ] Re-verify the PyPI trusted-publisher/environment configuration that
      successfully published SceneIO 0.2.0 in
      [release run 30097907487][release-020]; future tag pushes,
      publisher-setting changes, and publication remain explicit user actions.

Only after this stage is validated may the format queue resume with
animation-capable `ImageSequence`, animated WebP, APNG, and RTMV.

## 14. Review record

Reviewed on 2026-07-25 by three independent agents:

- [x] architecture and maintainability — Lovelace
      (`next_stage_arch_review`);
- [x] testing, benchmark, and correctness soundness — Banach
      (`next_stage_test_perf_review`);
- [x] portability, packaging, documentation, and release validation —
      Bernoulli (`next_stage_platform_docs_review`).

Each reviewer then audited the synthesized draft. The root synthesis accepted
every substantive initial and follow-up finding; overlapping findings were
merged and none was rejected. The resulting corrections include separate
built-in/runtime manifests, side-effect-free family ownership, sequence import
inversion, Python/native implementation ownership, native/source inventories,
exact pytest and wheel-smoke coverage, strict oracle/RSS qualification,
provenance-complete same-corpus decoder comparisons, profile-specific
non-inferiority rules, reproducible benchmark sampling, reversible backend
selection with persistent regression guards, focused three-OS gates, wheels
built from the exact sdist, offline-build isolation mechanics, and positive
artifact-license assertions.
