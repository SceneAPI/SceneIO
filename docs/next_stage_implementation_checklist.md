# Next-stage implementation checklist

Status: N0.1-N0.5 remain validated at immutable implementation commit
`a5e7fa4` on `phase0-nanobind-core`, including the nonpublishing
three-platform source/wheel build. R1.1-R1.4 are complete at `95061c6`. At that
exact R1 implementation commit, local MSVC collects 2,955 tests and passes
2,951 with four documented skips; Ruff, the retained 50-codec performance
guard, a Windows abi3 wheel built from the exact `95061c6` source archive, and
its fresh NumPy-only smoke pass. [Normal CI run
30187895845][r1-current-ci] passes the full suite,
retained performance guard, pinned GCC 10 job, and the
Ubuntu/Windows/macOS portability matrix. [Instrumented run
30187895838][r1-current-instrumented] passes the complete suite and focused
native lifetime job. [Build-only release run
30189483142][r1-current-release] builds the source archive and builds and
smoke-tests all three platform wheel sets, with its PyPI job skipped. Three
independent architecture, format/correctness, and test/benchmark reviews are
clear.

R2.0 is complete at `40d5412`. The image-sequence adapter receives its
image-extension catalog and metadata inspector through a lower-level contract
instead of importing the registry or public I/O facade at runtime. Its exact
source archive and Windows abi3 wheel pass content-identity, license-inventory,
layout, and fresh NumPy-only installed-wheel checks. R2.1 is complete at
`ccfeea4`. The calibration reference family is complete and pushed at
`b2bda1d`; the shared-inspection substrate is complete and pushed at
`29af9de`; and the six-codec mesh extraction is complete and pushed at
`975533f`. The shared image helpers are complete at `8040bc7`, and the
eight-codec image extraction is complete and pushed at `68c47d6`. The
two-codec sequence extraction is complete and pushed at `14bf53b`; arrays
close at `d99dcf0`, and points close at `686f42e`. The reconstruction
inspector checkpoint is pushed at `49fd976`, with its cross-platform
fingerprint correction at `6e94614`. Normal CI run 30214058828 and
compiler-instrumented run 30214058885 pass that exact corrected checkpoint.
The reconstruction registry extraction and both platform follow-ups close
through `aa5b624`; normal run 30218232248 and compiler-instrumented run
30218232246 pass that combined implementation. Splats close at registry
implementation `3e46d82` plus platform-contract repair `9928c6d`; normal run
30228235491 and compiler-instrumented run 30228235535 pass the final R2 tree.
R2 is closed. R3.1a is complete in the current tree. R3.1b closes at follow-up
commit `0bdfe0f`; normal run `30234796010` and
compiler-instrumented run `30234796025` pass. R3.2 family extraction is
active.

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
[r2-shared-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30195153288
[r2-shared-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30195153277
[r2-splat-parent-exposing]: https://github.com/SceneAPI/SceneIO/actions/runs/30220612832
[r2-splat-parent-corrected]: https://github.com/SceneAPI/SceneIO/actions/runs/30221945705
[r2-splat-parent-corrected-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30221945731

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

- [x] Move the image-extension catalog and inspector dispatch contract to a
      lower-level internal module that neither imports `REGISTRY` nor the
      public `sceneio` package.
- [x] Inject those dependencies into the image-sequence adapter instead of
      resolving them through deferred upward imports.
- [x] Exercise `_image_extensions()` and `_frame_metadata()` at runtime in an
      isolated import-cycle test; a static import graph alone is insufficient.
- [x] Preserve sequence detection order, selected-frame semantics, metadata,
      normalized errors, and import/startup measurements.

R2.0 local completion evidence:

- `ImageFrameAccess` lives in a dedicated stdlib-only lower-level module;
  `inspect_codec` remains the shared lower-level inspection dispatcher. The
  public inspector and the registry-injected image-frame inspector use the same
  dispatch and result-type contract.
- The extension catalog is an injected callable rather than a frozen copy, so
  third-party image codec registration and removal remain visible to image
  sequences exactly as before.
- The image-sequence `Codec` binds the dependency explicitly with positional,
  pre-bound `partial` adapters whose exposed signatures remain unchanged. A
  fresh-process runtime test blocks upward imports while
  exercising `_image_extensions()` and `_frame_metadata()`.
- The focused architecture, compatibility, image-sequence, capability, and
  public E2E set passes 80 tests. The complete local suite collects 2,957 tests
  and passes 2,953 with four documented skips; Ruff and the editable
  NumPy-only smoke pass.
- The one-run 50-codec structural smoke and unchanged five-run O4/O5
  performance/memory guard pass. The representative image-sequence row retains
  bounded traced allocation, with 1.43x inspection and 1.76x selected-frame
  speedups in this run.

### R2.1 — extract shared model and adapters

- [x] Move codec/capability value types, mmap/path/sink adapters, detection,
      and native-feature metadata behind the existing facade.
- [x] Keep import direction acyclic:
      family definitions -> shared model/adapters; facade -> family aggregate.
- [x] Do not let family modules import the public `sceneio` package.
- [x] Add import-cycle and import-isolation tests.
- [x] Preserve public value-type identity, `__module__`, `__qualname__`, repr,
      and pickle compatibility; leave definitions in the facade when moving
      them would create an avoidable compatibility break.

R2.1 implementation contract:

- Use the planned `sceneio.io._registry` package with focused `model`,
  `adapters`, `detection`, and `native_features` modules; do not create a
  miscellaneous utility module.
- Re-export the exact shared model objects from `registry.py`. Preserve their
  historical `sceneio.io.registry` module identity so existing repr and pickle
  contracts remain unchanged.
- Keep the live `REGISTRY` object and built-in installation in the facade for
  this unit. Side-effect-free family tuples and validate-before-install
  aggregation begin in R2.2, so R2.1 does not mix state-lifecycle changes into
  the mechanical extraction.
- Make detection operate on an injected ordered codec collection. The facade
  supplies its live registry values, preserving directory, filename, PLY,
  extension, LAS/LAZ, and magic precedence exactly.
- Let lower-level typed adapters import shared model/adapters directly rather
  than importing adapter helpers through the registry facade. No family or
  shared module imports the public `sceneio.io` facade.
- Freeze the eager-module delta, public symbol/type snapshot, callable
  signatures, detection/error outcomes, and adapter ownership in focused
  tests before running the complete suite and performance guard.

R2.1 local implementation evidence:

- `model.py`, `adapters.py`, `detection.py`, and `native_features.py` now live
  under the inert `sceneio.io._registry` package. The moved model and adapter
  definitions are AST-identical to `40d5412`; the facade re-exports their exact
  objects and preserves the original adapter factory names.
- `Codec`, `CodecCapabilities`, and `NativeFeatureCapabilities` deliberately
  retain historical `sceneio.io.registry` module identities. Checked protocol
  4 payloads emitted by pre-move commit `40d5412` load as the current exact
  types, and current emission remains byte-identical.
- Ordered detection receives a snapshot of the live registry values per call;
  native-feature resolution reads `_core.__native_features__` per call. Public
  registry, capability, type, repr, pickle, signature, error, and import
  snapshots are unchanged except for the five expected private eager modules.
- The complete local suite collects 2,974 tests and passes 2,970 with four
  documented skips; the focused path/mmap/zero-copy/partial/depth/flow/sequence
  set passes 445 tests. Ruff, workflow parsing, editable NumPy-only smoke, and
  `git diff --check` pass.
- The one-run 50-codec structural smoke and five-run retained O4/O5 and
  allocation guard pass. The 15-sample Windows `sceneio.io` median is
  71.79 ms, below the unchanged 220.05 ms alert threshold.
- The exact staged source archive contains all 21 changed files byte-identical
  to the workspace. Its derived Windows abi3 wheel contains 60 files, all 15
  indexed licenses, exactly one native module, and no top-level
  include/lib/share/bin content. All five `_registry` runtime files are
  byte-identical across workspace/archive/wheel; a fresh NumPy-only install
  passes `_wheel_smoke` and the shared-model identity/pickle probe.

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

### R2 calibration reference-family unit

Implementation:

- [x] Add inert `_registry/families` and `_inspectors` packages.
- [x] Export the four calibration codec definitions (`opencv_yaml`,
      `opencv_xml`, `ros_camera_info`, and `kalibr`) as one immutable,
      side-effect-free tuple; no family module imports `REGISTRY`,
      `registry.py`, `_inspection.py`, or a public facade.
- [x] Install that tuple at its exact canonical position through a facade-owned
      helper that validates types, exact family ids/order, uniqueness, and
      existing collisions before the first registry mutation.
- [x] Keep the inspection value types and shared buffer inspector in
      `_inspection.py` for the first family, preserving their exact source/type
      identities. Inject them into the lower family inspector; extract shared
      inspector infrastructure only after a second family proves the invariant.
- [x] Move camera-rig metadata inspection into
      `_inspectors/calibration.py`; retain the original private signature as a
      thin calibration dispatch and dependency-injection wrapper within the
      `_inspection.py` compatibility facade.

Focused verification:

- [x] Prove the family tuple is immutable, side-effect free under reload, and
      exactly matches `FAMILY_MEMBERS["calibration"]`.
- [x] Prove invalid type/id/order/duplicate/collision families fail atomically;
      prove the facade installs the exact tuple objects between `euroc_state`
      and `g2o` without changing `REGISTRY` identity.
- [x] Compare registry, public-type, import, capability, and callable
      snapshots byte-for-byte except for the expected private-module additions.
- [x] Run calibration parity, public E2E, detect, mmap/sink, inspection/full,
      malformed-input, bounded-allocation, import-cycle, and reload tests.
- [x] Run the complete suite, Ruff, one-run 50-codec smoke, five-run retained
      O4/O5/allocation guard, and fresh-process import timing.

Validation and documentation:

- [x] Update current architecture and organization diagrams with the actual
      first-family dependency direction and preserved inspection source/type
      identities.
- [x] Build the exact staged source archive, build the Windows abi3 wheel from
      it, compare every new runtime file across workspace/archive/wheel,
      inspect the license/native/layout inventory, and pass a fresh NumPy-only
      installed-wheel smoke.
- [x] Complete three independent architecture/correctness, test/performance,
      and platform/documentation reviews before committing.

Local verification evidence:

- The calibration family tuple contains the exact canonical ids and object
  identities between `euroc_state` and `g2o`. Fresh-process reload tests prove
  that the family module is side-effect free, repeated registry reloads are
  idempotent, and invalid family inputs leave the live registry unchanged.
- Public inspection for all four carriers succeeds after replacing the
  corresponding full decoder with a failing sentinel. A generated
  1 MiB-class OpenCV YAML fixture keeps traced inspection allocation below 10%
  of file size and can be renamed and removed while its retained `Inspection`
  remains valid.
- The focused architecture, calibration parity, CameraRig, registry,
  compatibility, capability, public E2E, and mmap set passes 281 tests. The
  complete local suite collects 2,999 tests and passes 2,995 with four
  documented skips; Ruff and `git diff --check` pass.
- The five-run four-codec comparison preserves exact mmap/sink allocation
  bounds. The one-run 50-codec structural sweep and five-run retained
  O4/O5/allocation guard pass. Fifteen-sample Windows medians are 5.68 ms for
  `sceneio`, 74.25 ms for `sceneio.io`, and 7.56 ms for `_core`, all below
  their unchanged alerts.
- Three independent final reviews are clear after strengthening malformed
  inspection parity, lower-layer import enforcement, native inspector-table
  identity, workflow collection synchronization, and documentation wording.
- The staged source-to-wheel gate contains 291 source members and produces a
  64-file Windows cp312-abi3 wheel with all 15 indexed license files, exactly
  one native module, and no top-level build-layout directories. All four new
  runtime modules are byte-identical across workspace, source archive, and
  wheel; a fresh environment containing only NumPy and SceneIO passes the
  expanded installed-wheel smoke.

Completion checkpoint:

- The calibration reference-family unit is committed and pushed as
  `b2bda1d`. Its exact source archive SHA-256 is
  `171a0d87acdbd5208cdf92416f85a0eac5fe31031214233f235d98dbb2590a56`;
  the derived Windows cp312-abi3 wheel SHA-256 is
  `1df68651617a88ab4d9309fcf290e65ab3a8d2b8e9dd7a8a76c58aa6b7a4184f`.

### R2 shared inspection substrate and mesh second-family unit

Decision:

- [x] Select meshes as the second family: `ply_mesh`, `obj`, `stl`, `off`,
      `gltf`, and `glb` are one contiguous canonical block between `ksplat`
      and point `ply`.
- [x] Keep the unit in two independently green commits. First lower the shared
      inspection model and the one proven common mmap helper; then move the
      mesh definitions and three facade-owned mesh inspectors.
- [x] Defer the larger image-parser move until this static-family pattern is
      proven. Defer sequences until the live `ImageFrameAccess` family-factory
      contract is explicit; do not freeze the image-extension catalog.

Shared inspection substrate:

- [x] Add `_inspectors/model.py` for `MetadataValue`, `ArrayInspection`, and
      `Inspection`.
- [x] Re-export the exact model objects from `_inspection.py`; preserve their
      historical `sceneio.io._inspection` module, qualnames, signatures, repr,
      equality, and pickle behavior.
- [x] Add the initial `_inspectors/common.py` containing only
      `_compiled_buffer_inspect`; the later image-helper unit extends it with
      proven cross-family primitives. Preserve `ACCESS_READ`, same-open-stream
      fallback, caught exception types, and prompt mapping closure.
- [x] Make calibration consume the lower model/helper directly while
      retaining `_inspection._inspect_camera_rig(path, format_id, datatype)`
      as the same-signature compatibility wrapper.
- [x] Lower the `Inspection` imports in `_obj.py`, `_gltf.py`, and
      `_image_sequence.py`. Keep `_depth.py` on the facade dispatcher while
      importing the model type directly where practical.
- [x] Pin a protocol-4 `ArrayInspection` payload emitted by `b2bda1d`; require
      byte-identical current emission and successful legacy loading.
- [x] Preserve `Inspection`'s existing
      `TypeError: cannot pickle 'mappingproxy' object` outcome.
- [x] Prove facade/lower object identity, helper identity, import direction,
      fresh-process reload behavior, public snapshots, and unchanged
      lightweight import boundaries.

Mesh family implementation:

- [x] Add side-effect-free `_registry/families/meshes.py` exporting one
      immutable six-codec tuple in exact `FAMILY_MEMBERS["meshes"]` order.
- [x] Keep PLY-mesh, OBJ, STL, OFF, glTF, and GLB codec field values and
      callable identities unchanged, including multi-file OBJ/glTF adapters
      and face/mesh/primitive selectors.
- [x] Install the complete tuple atomically at its canonical position through
      the validated facade helper. Family-only reload must not mutate the live
      registry; repeated registry reload must adopt the current exact tuple
      objects without duplicates.
- [x] Add `_inspectors/meshes.py` for PLY-mesh, STL, and OFF metadata
      conversion. Keep OBJ, glTF, and GLB inspectors in their bespoke path
      adapter modules.
- [x] Retain same-signature `_inspection.py` wrappers for PLY-mesh, STL, and
      OFF. Do not move point-PLY classification, point-PLY inspection, or
      shared PLY header ownership.

Focused verification:

- [x] Freeze exact family ids, canonical neighbors, registry and
      `BUILTIN_DEFINITIONS` object identity, capabilities, detection
      precedence, selector identities, and OBJ/glTF/GLB inspector identities.
- [x] Strictly reject upward, relative, public-package, registry, facade, and
      sibling-family imports from lower modules; validate imported symbol
      names, not only module names.
- [x] Prove public inspection never calls a full decoder and that the lower
      mesh inspector table contains only metadata entry points.
- [x] Prove representative malformed inspection preserves native/public cause
      type and text, inspect/full metadata agrees, allocation stays bounded,
      and retained inspections own no file handle.
- [x] Run mesh parity, mesh record, public E2E, PLY ambiguity, mmap/sink,
      face/mesh/primitive partial reads, capability, compatibility, import,
      reload, image-sequence, and documentation-consistency suites.
- [x] Run the complete suite and Ruff; update the compiler-instrumented exact
      collection pin only from the final `pytest --collect-only` result.

Shared-substrate local evidence:

- The exact collection gate is 3,006 tests; the complete local MSVC suite
  passes 3,002 with four documented skips. The focused shared/calibration
  contract set passes 91 tests, and the broad inspection, registry, public
  API, mmap, partial, capability, calibration, OBJ, glTF, image-sequence,
  typed-depth, and record consumer set passes 530 tests.
- The six-row five-run mesh comparison preserves row order, payload/file
  sizes, and every traced mmap/sink allocation bound. Because no timed mesh
  path changed, the observed per-row timing movement is treated as sampling
  variance and no speedup is claimed.
- The one-run 50-codec structural sweep and five-run retained O4/O5/allocation
  guard pass. Fifteen-sample Windows medians are 7.81 ms for `sceneio`,
  76.47 ms for `sceneio.io`, and 9.53 ms for `_core`, below the unchanged
  100/220.05/100 ms alerts.
- `ArrayInspection` loads and re-emits the protocol-4 `b2bda1d` fixture
  byte-identically. `Inspection` retains its historical mapping-proxy pickle
  rejection. Empty-file mmap fallback, prompt mapping closure, facade/lower
  object identity, helper identity, and fresh-process facade reload are
  covered by the checked shared-inspection contract.
- Review found and closed two compatibility-test gaps: the facade again
  exposes `Mapping` so historical annotation resolution succeeds, and the
  lower-import guard now examines imported names as well as modules while
  allowing only the required `from sceneio import _core` form. The exact
  3,006-node workflow pin is reconciled as the hosted 2,999-node baseline plus
  five new contract tests and two repository-wide package-file cases for the
  two new runtime modules.
- The isolated shared-substrate package gate produces a 295-member source
  archive and a 66-file Windows cp312-abi3 wheel. All nine changed runtime
  files are byte-identical across workspace, archive, and wheel; the wheel
  contains all 15 indexed attribution files, exactly one native module, no
  excluded top-level build-layout directories, and only NumPy as an
  unconditional dependency. A fresh NumPy-only environment passes
  `sceneio._wheel_smoke` and the installed type, annotation, pickle, helper,
  and 50-codec identity probe.
- The architecture/correctness, test/performance, and
  platform/package/documentation reviews are clear after those fixes. The
  shared substrate is committed and pushed as `29af9de`. Its exact staged tree
  is `fa2aecb82b0efde2fc1b29dce3adac6efd337e62`; the source archive SHA-256 is
  `7411ed1196b053c708b1b37fde8317f503703860d9bdeb96fcab3a62c2c32d96`,
  and the derived wheel SHA-256 is
  `2993a3ce89675e9e67925b22db79397c59aec5535e6d61cc8a0cc85a0ab1f0d8`.
  [Normal CI run 30195153288][r2-shared-ci] and [compiler-instrumented
  run 30195153277][r2-shared-instrumented] pass at that immutable commit.

Mesh-family local evidence:

- The 16 focused architecture cases prove exact six-codec ordering and object
  identity, canonical `ksplat`/point-PLY neighbors, bespoke OBJ/glTF/GLB
  callable identities, face/mesh/primitive selectors, lower import
  direction, facade wrapper signatures, family/registry reload behavior,
  metadata-only entry points, malformed public causes, bounded 36 MB sparse
  PLY inspection, released file handles, and unchanged point-PLY ownership.
- The broad mesh parity/record/public API/mmap/partial/capability/
  compatibility/registry/shared-inspection/calibration/image-sequence/docs
  sweep passes 604 tests. The complete local suite collects 3,024 tests and
  passes 3,020 with four documented skips; the exact workflow pin is the
  preceding 3,006 nodes plus 16 mesh architecture nodes and two package-file
  cases for the new runtime modules.
- The five-run six-row comparison is structurally exact against both the
  pre-move and shared-substrate captures: codec order, payload/file sizes,
  bytes/mmap/sink/inspection/partial traced allocation fields are unchanged.
  Path-read, sink-write, inspection, and partial timing ratios stay within
  sampling movement for unchanged implementations, so no speedup is claimed.
- The one-pass 50-codec structural sweep and strict five-run retained
  O4/O5/allocation guard pass. Fifteen-sample Windows medians are 7.71 ms for
  `sceneio`, 76.61 ms for `sceneio.io`, and 9.71 ms for `_core`, below the
  unchanged 100/220.05/100 ms alerts.
- The isolated package gate contains 298 source members and produces a
  68-file Windows cp312-abi3 wheel. All 12 staged files are byte-identical in
  the source archive, all four changed runtime files are byte-identical across
  workspace/archive/wheel, and the wheel contains all 15 attribution files,
  exactly one native module, and no excluded layout directories. A fresh
  NumPy-only environment passes `sceneio._wheel_smoke` and the installed
  six-codec family/order/callable/inspector identity probe.
- Three independent architecture/correctness, test/performance, and
  platform/package/documentation reviews are clear. They independently
  confirmed AST-equivalent codec definitions, exact collection arithmetic,
  structural benchmark identity, unchanged Windows path/mmap behavior,
  accurate ownership/docs, and the package inventory.
- The mesh family is committed and pushed as `975533f`. Its exact staged tree
  is `fb9e4a90d04165a95ba63458bbac05251aae07c9`; the source archive SHA-256 is
  `54f8c4023c3acb83db9a8d1283e5f53688fbf989fd4f09ca183c283ca6290df6`,
  and the derived wheel SHA-256 is
  `cc3a8fe6afc0cdb2f6ca12581aa24bfdd39bcd83fb8a478bf0abbcd1168b8a7c`.

Performance, package, and review:

- [x] Capture the five-run pre-move mesh rows in
      `build/r2-meshes-before.json`.
- [x] Run the identical six-row five-run command after each commit; require
      identical row order/file sizes/allocation bounds and investigate any
      sustained public-path, inspection, or partial-read regression.
- [x] Run the one-pass 50-codec structural sweep, five-run retained
      O4/O5/allocation guard, and 15-sample fresh-process import timings.
- [x] Update the six repository-coverage inspection owners accurately:
      PLY-mesh/STL/OFF move to `_inspectors/meshes.py`; OBJ/glTF/GLB remain in
      `_obj.py`/`_gltf.py`.
- [x] Build an exact staged source archive and derive the Windows abi3 wheel
      only from it. Compare every new runtime file across workspace/archive/
      wheel; require all 15 licenses, one native module, no layout leakage,
      and a fresh NumPy-only installed-wheel smoke.
  - [x] Shared-inspection substrate commit.
  - [x] Mesh-family commit.
- [x] Complete three independent architecture/correctness, test/performance,
      and platform/documentation reviews for each of the two commits.
  - [x] Shared-inspection substrate commit.
  - [x] Mesh-family commit.

### R2 shared image helpers and image third-family unit

This unit follows the mesh checkpoint in two independently green commits. The
first lowers only already-shared inspection primitives. The second moves the
eight static image registrations and their metadata inspectors. Neither commit
changes a codec field, payload, public signature, selector, detection rule, or
backend.

Shared-helper commit:

- [x] Promote `_HEADER_LIMIT`, `_IMAGE_PIXEL_CAP`, `_exact`,
      `_unsigned_decimal`, and `_image` into `_inspectors/common.py`; retain
      `_compiled_buffer_inspect` unchanged.
- [x] Re-export the exact helper objects and constants from `_inspection.py`
      so PFM, FLO, Gaussian PLY, ZIP/NPY, point, splat, and reconstruction
      inspectors continue through the same implementation.
- [x] Keep `_size`, Netpbm tokenization, EXR C-string parsing, JPEG/HDR
      constants, line iterators, ZIP helpers, and NumPy helpers out of the
      shared module.
- [x] Prove helper identity, annotations, exact short-read/integer grammar,
      image shape and limit policy, metadata preservation, and unchanged
      PFM/FLO inspection behavior.
- [x] Run the complete inspection/mmap/partial/public suite, exact collection,
      full suite, Ruff, all-codec guard, and import thresholds.
- [x] Build the exact staged source archive and its derived Windows abi3
      wheel; validate package contents and a fresh NumPy-only install.
- [x] Obtain three independent architecture/correctness, test/performance, and
      platform/package/documentation reviews before commit.

Shared-helper local evidence:

- Four new focused nodes cover exact helper behavior plus PFM/FLO consumers.
  The exact collection gate is 3,028 tests, reconciled as the immutable
  3,024-node mesh checkpoint plus those four nodes; the complete local MSVC
  suite passes 3,024 with four documented skips.
- The focused shared/mmap/partial set passes 176 tests. The eight-row five-run
  image comparison preserves exact codec order, payload/file sizes, all
  bytes/mmap/sink/inspection/partial traced allocation fields, and typed
  adapter/O4 identity fields against `build/r2-images-before.json`.
- The one-pass 50-codec structural sweep and strict five-run retained
  O4/O5/allocation guard pass. Fifteen-sample Windows medians are 5.80 ms for
  `sceneio`, 75.03 ms for `sceneio.io`, and 7.77 ms for `_core`, below the
  unchanged 100/220.05/100 ms alerts.
- No registry value, codec implementation, eager module set, C++/CMake source,
  native dependency, ABI, license, or performance-ledger entry changes in
  this helper-only unit.
- The candidate package gate retains 298 source members and a 68-file Windows
  cp312-abi3 wheel. All eight staged-tree files match the source archive; both
  changed runtime files match the staged tree, archive, and wheel. The wheel
  has all 15 attribution files, exactly one native module, no excluded layout
  directories, and only NumPy as an unconditional dependency. A fresh
  NumPy-only install passes `_wheel_smoke`, facade/common identity and
  annotation checks, PFM/FLO inspection, and the 50-codec inventory probe.
- Three independent reviews are clear. They confirmed exact helper ASTs and
  facade identities, collection arithmetic and benchmark structure, package
  contents, and Windows mapping behavior. The reviews found two stale
  documentation statements—the current facade line count and the historical
  initial contents of `common.py`; both are corrected in the final staged
  tree.
- The helper unit is committed and pushed as `8040bc7`. Its exact staged tree
  is `e5b51f1b389a872a29d289bc915e256c61c742fb`; the source archive SHA-256 is
  `b0a59bea1036198d1001e30244d4368eb031f9f993526d2afb3211a86c510773`,
  and the derived wheel SHA-256 is
  `e032a08583085cc7afc819999ede6b6b4a5b21ba1efb0de23a06974df33ee002`.

Image-family implementation:

- [x] Add side-effect-free `_registry/families/images.py` exporting immutable
      `IMAGE_CODECS` in exact `netpbm`, `png`, `jpeg`, `bmp`, `tga`, `hdr`,
      `exr`, `webp` order.
- [x] Preserve every `Codec` field and callable identity, including
      Netpbm/WebP window selectors, JPEG/HDR/WebP lossy flags, TGA/WebP
      extension-only detection, and all magic/capability tuples.
- [x] Install the complete tuple atomically between `safetensors` and `y4m`.
      Construct `_IMAGE_FRAME_ACCESS` afterward in `registry.py` with its
      existing live registry callbacks; do not freeze the image extension set
      or move sequence state into the family module.
- [x] Add `_inspectors/images.py` containing the eight existing bounded
      header/container parsers. Keep Netpbm token scanning, JPEG marker sets,
      HDR resolution parsing, and EXR C-string parsing local to that module.
- [x] Retain eight same-signature `_inspection.py` wrappers and the existing
      `inspect_path` branches. Only BMP/TGA may call compiled metadata
      entry points; no lower image inspector may call a full decoder or
      writer.

Image-family verification:

- [x] Freeze exact valid inspection metadata and representative malformed
      cause type/text for all eight codecs before the move; compare the final
      lower and public paths against that evidence.
- [x] Prove canonical neighbors, registry/definition object identity, exact
      adapter closure targets, immutable side-effect-free family reload, and
      duplicate-free registry reload.
- [x] Enforce lower import allowlists and reject public, facade, registry,
      image-sequence, frame-access, relative, and sibling-family imports.
- [x] Prove inspect/full agreement, unchanged public errors, no full decode,
      bounded traced allocation on generated large padded headers, and prompt
      Windows rename/delete while retaining every `Inspection`.
- [x] Re-run the live image-extension registration/removal and
      image-sequence reload/dispatch tests so third-party image extensions
      remain visible immediately.
- [x] Run all raw image parity suites, typed PNG/EXR depth, Image and
      ImageSequence records, public E2E, detection, mmap/lifetime, sink,
      partial-window, capability, compatibility, import, and documentation
      suites.
- [x] Compare the eight five-run rows against
      `build/r2-images-before.json`; require exact row order, payload/file
      sizes, and traced bytes/mmap/sink/inspection/partial fields. Treat timing
      movement as sampling variance and claim no speedup.
- [x] Run the one-pass 50-codec structural sweep, strict five-run retained
      O4/O5/allocation guard, 15-sample imports, exact collection, full suite,
      and Ruff.
- [x] Update only the two intended eager import entries, all eight inspection
      ownership rows, final exact workflow collection pin, measured facade
      line counts, and current architecture/status documentation.
- [x] Build the source archive from the exact staged tree and derive the
      Windows abi3 wheel only from it. Require staged/archive/runtime identity,
      all 15 attribution files, one native module, no excluded layout
      directories, NumPy-only metadata, and an installed all-eight-codec probe
      including Netpbm/WebP windows and PNG/EXR typed depth.
- [x] Obtain independent architecture/correctness, test/performance, and
      platform/package/documentation reviews; resolve findings before commit.

Image-family candidate evidence:

- The 34-node focused architecture and parent-contract suite passes. The
  broader image, typed-depth, record, sequence, mmap, partial, parallel,
  public-API, capability, compatibility, registry, inspection, documentation,
  and import set passes 644 tests.
- The exact local collection is 3,064 tests, reconciled as the immutable
  3,028-node helper checkpoint plus 34 focused nodes and two package-file
  guard nodes. The complete local MSVC suite passes 3,060 with the same four
  documented skips, and repository-wide Ruff is clean.
- The eight-row five-run result is structurally exact against both
  `build/r2-images-before.json` and
  `build/r2-images-shared-after.json`: codec order, payload/file sizes, every
  traced bytes/mmap/sink/inspection/partial field, and typed-adapter schema
  plus traced-allocation fields match. Timing and RSS are retained as
  diagnostics and treated only as sampling variability.
- The one-pass 50-codec structural sweep and strict five-run retained
  O4/O5/allocation guard pass. Fifteen-sample Windows medians are 7.66 ms for
  `sceneio`, 77.48 ms for `sceneio.io`, and 9.53 ms for `_core`, below the
  unchanged 100/220.05/100 ms alerts.
- No codec payload implementation, public signature, C++/CMake source,
  backend, dependency, ABI, license, or performance-ledger row changes in this
  organization-only candidate.
- The package candidate from staged tree
  `07e5e361999012836100cf10f9726e429f52ab70` contains 302 source files and
  derives a 70-file Windows cp312-abi3 wheel. All 13 staged files match the
  archive, and all four changed runtime files are byte-identical across the
  workspace, archive, and wheel. The wheel includes all 15 attribution files,
  exactly one native module, no excluded layout directories, and only NumPy
  as an unconditional dependency. A fresh NumPy-only install passes
  `_wheel_smoke` plus an explicit eight-codec write/detect/inspect/read probe,
  Netpbm/WebP windows, and PNG/EXR typed depth. The candidate source SHA-256 is
  `89c0671aed72e8010b4d9d2a0f68325b9d93ef3d7b2900bdc83ff536fa917d28`;
  the wheel SHA-256 is
  `e250fafdb0d0ec12d6a2d28c445ed868145da47961d72fee870bd1adbc4e349e`.
- Three independent reviews are clear. Architecture/correctness confirmed
  exact move fidelity, dependency direction, facade compatibility, and live
  sequence access. Test/performance independently reconciled collection,
  focused/integration coverage, allocation bounds, and benchmark structure.
  Platform/package/documentation reconciled imports, ownership, line counts,
  workflow collection, package layout, and candidate artifact contents. The
  test/performance review found one overbroad statement that called all typed
  adapter fields exact; it is corrected above to distinguish exact
  schema/traced-allocation fields from diagnostic timing/RSS values.
- The final post-review exact-tree package confirmation is intentionally run
  only after this documentation is frozen. Its tree and artifact hashes are
  reported with the commit evidence rather than self-referenced here.

- The image-family unit is committed and pushed as `68c47d6`. Its exact commit
  tree is `cefb66c41fefcc0e7fb7828ef0a8cc11e863cecf`; the final source archive
  SHA-256 is
  `35024bc81c334701fd25b1b3182f22a1b670f093bebfe4fac717fe2583896fc1`,
  and the derived wheel SHA-256 is
  `fbded8d96e8002e938c16676788ea3fc3d95f7e00299f25b65f96ce97dc8c4ba`.

### R2 sequence fourth-family unit

This unit moves the last contiguous family: `y4m` and `image_sequence`.
R2.0 already made the directory adapter accept `ImageFrameAccess` explicitly;
this unit consumes that boundary without moving or freezing live registry
state. It is an organization-only change: no YUV conversion, video framework,
codec option, payload, public signature, or backend change is in scope.

Sequence-family implementation:

- [x] Add side-effect-free `_registry/families/sequences.py` with a typed
      `build_sequence_codecs(frame_access)` factory returning an immutable
      `y4m`, `image_sequence` tuple in exact order.
- [x] Preserve the Y4M mmap/sink/frame-selector adapters, magic, record,
      datatype, and supported/unsupported feature tuples exactly.
- [x] Preserve each image-sequence `partial` target, bound
      `ImageFrameAccess`, directory marker, record, datatype, features, and
      lazy/transactional directory behavior exactly.
- [x] Construct `_IMAGE_FRAME_ACCESS` in `registry.py` only after all image
      codecs are installed, then validate and atomically install the built
      sequence tuple between `webp` and `colmap_sparse_txt`.
- [x] Keep the family module free of `REGISTRY`, registration side effects,
      public-I/O imports, and inspection-facade imports. Repeated factory calls
      must not mutate the live registry or share an incorrectly bound access
      object.
- [x] Add `_inspectors/sequences.py` containing only the existing Y4M metadata
      conversion. Retain the same-signature `_inspect_y4m` facade wrapper and
      unchanged `inspect_path` branch.
- [x] Keep image-sequence manifest parsing, metadata inspection, bounded frame
      validation, and path/sink behavior in `_image_sequence.py`; do not
      duplicate them in the family inspector.

Sequence-family verification:

- [x] Freeze parent `68c47d6` registry structure, Y4M valid metadata, and
      representative malformed cause type/text before the move.
- [x] Prove exact canonical neighbors, registry/definition identity, Y4M
      closure targets, image-sequence `partial` targets and bound-access
      identity, factory re-entrancy, family reload isolation, and registry
      reload idempotence.
- [x] Re-run third-party image registration/removal with existing and newly
      reloaded access objects; every directory callback must observe the live
      extension catalog immediately.
- [x] Enforce lower import allowlists and reject public, registry, inspection
      facade, sibling-family, and relative imports.
- [x] Prove lower/public Y4M inspection matches the frozen parent and full
      decode, does not call a full decoder, has bounded traced allocation on a
      generated large sparse payload, and releases the mapped path promptly
      while retaining its `Inspection`.
- [x] Run the complete Y4M and image-sequence parity suites, ImageSequence
      record tests, public E2E, detection, registry/reload, mmap/lifetime,
      sink, frame-selection, capability, compatibility, import, and
      documentation suites.
- [x] Compare five-run `y4m` and `image_sequence` benchmark rows against a
      parent capture. Require exact row order, payload/file sizes, traced
      allocation fields, and nested schema; treat timing and RSS as
      diagnostics and claim no speedup.
- [x] Run the one-pass 50-codec structural sweep, strict five-run retained
      O4/O5/allocation guard, 15-sample imports, exact collection, full suite,
      and Ruff.
- [x] Update only the two intended eager import entries, the Y4M inspection
      ownership row, exact workflow collection pin, measured facade line
      counts, and current architecture/status documentation.
- [x] Build the source archive from the exact staged tree and derive the
      Windows abi3 wheel only from it. Require staged/archive/runtime identity,
      all 15 attribution files, one native module, no excluded layout
      directories, NumPy-only metadata, and an installed sequence probe
      covering Y4M full/selected frames plus lazy directory read/inspect/write.
- [x] Obtain independent architecture/correctness, test/performance, and
      platform/package/documentation reviews; resolve findings before commit.

Sequence-family candidate evidence:

- The 17 focused architecture contracts pass. Exact collection is 3,083
  tests; the complete local MSVC suite passes 3,079 with the same four
  documented skips, and repository-wide Ruff is clean.
- The five-run parent/candidate comparison preserves row order, payload and
  file sizes, every Y4M traced field, the directory sink peak, and the nested
  schema exactly. Directory read, inspection, and selected-frame traced peaks
  differ by at most 102 bytes, inside the predeclared 128-byte allocator-noise
  tolerance. Timing and RSS remain diagnostic; no speedup is claimed.
- The one-pass 50-codec structural sweep and strict five-run retained
  O4/O5/allocation guard pass. Cold-cache mode reports the unavailable Windows
  eviction hint explicitly and remains diagnostic.
- Fifteen-sample Windows medians are 5.70 ms for `sceneio`, 75.14 ms for
  `sceneio.io`, and 7.29 ms for `_core`, below the unchanged
  100/220.05/100 ms alerts.
- This candidate changes no C++, CMake, native symbol, codec backend, runtime
  dependency, or attribution inventory.
- The exact package candidate from staged tree
  `690f65715dd45ff8f66afb0c848105253826c74c` contains 306 source files and
  derives a 72-file Windows cp312-abi3 wheel. All 13 staged files match the
  source archive, and all four changed runtime files are byte-identical across
  staged tree, archive, and wheel. The wheel contains all 15 attribution
  files, exactly one native module, no excluded layout directories, and only
  NumPy as an unconditional dependency. A fresh NumPy-only installation passes
  `_wheel_smoke` plus explicit imports of both new modules and hand-authored
  Y4M and image-directory write/detect/inspect/read/selected-frame probes. The
  candidate source SHA-256 is
  `9975a4d294b71ca0b6b07738b24fa057fb3effbdac1960548eef8a9bf4740649`;
  the wheel SHA-256 is
  `320a55411cdd249b4f84761634cfdea18f2eb07b7eb22d022174b5fdb765ac65`.
- Three independent reviews are clear after findings were resolved.
  Architecture/correctness confirmed exact normalized parent fidelity,
  dependency direction, static/dynamic codec identity, and live frame access.
  Test/performance caught a self-referential image-sequence AST hash and a
  malformed-path lifetime gap; the contract now records its single intentional
  name normalization, regenerates the hash from parent `68c47d6`, and retains
  both lower and public errors across rename/deletion. It also removed an
  affected-suite count that lacked a recorded command. Platform/package/docs
  caught checkout line-ending ambiguity and missing explicit directory
  inspection in the installed probe; packaging now begins from a Git-object
  archive with checkout conversion disabled, and the expanded probe covers
  directory inspection.
- A final exact-tree package confirmation is run after this documentation is
  frozen and immediately before commit. Its hashes are reported with the
  commit evidence rather than self-referenced here.

The sequence-family unit is committed and pushed as `14bf53b`. Its exact
commit tree is `fcb64bee4f4fe782e027fe8e1b0505094c57dfdf`; the final source
archive SHA-256 is
`a11884789573cec7a69e5ca953e7776fbb416a7aa34b56ba4eb4ee0a7c73ee25`,
and the derived wheel SHA-256 is
`0b6fcd42ec7221622bde14f364ae9c5d14f8907a464390307c9f9e37c984e44b`.
Normal CI run 30200316679 and compiler-instrumented run 30200316665 pass.

### R2 aggregate built-in staging boundary

The four remaining families are interleaved in canonical detection order, so
they cannot use the contiguous install-at-call-site pattern without splitting
family ownership or temporarily reordering the registry. This unit changes
only built-in assembly: it stages definitions outside the public registry,
validates the complete aggregate, and publishes the same 50 objects in the
same order once. Parent behavior is frozen at `14bf53b`.

The active candidate now implements that boundary. Parent-derived contracts
freeze all 50 normalized `Codec` AST values and every non-`None` runtime
operation binding; both reproduce exactly from the raw parent tree and the
candidate. Fresh-process profiling observes
`finalize-return -> dict.update-call -> dict.update-return`, registry sizes
only zero then 50, no subscription store, and the initial empty
`ImageFrameAccess` probe followed by the complete live catalog. The exact
candidate collection is 3,095: all 3,083 parent nodes, 11 assembly contracts,
and the automatic package-file node, with no removal or rename; the normalized
sorted-node digest is
`ead83e74ffc13fa62528e19c1e6c95bfacac767a2ef0bc0753d62cf768d84076`.
The complete local MSVC suite passes 3,091 tests with four documented skips.

The two parent benchmark captures and the candidate all reproduce portable
structural projection hash
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`;
the checked comparator keeps all allocation keys but normalizes their
runtime-dependent values, and now runs after a matching `--skip-oracles` CI
benchmark smoke. The separate strict guard retains the top-level O1/O3/O5
allocation acceptance checks, while typed-adapter allocation paths retain
focused memory tests. Fifteen
interleaved same-host samples show candidate/parent import medians of
5.632/5.659 ms for `import sceneio`, 75.163/75.218 ms for the I/O facade, and
7.394/7.464 ms for `_core`. The only facade eager-module delta is
`_registry.assembly`.

The exact-tree package preflight contains 310 source files and a 73-file
Windows cp312-abi3 wheel. All 13 staged files match the source archive; both
changed runtime files match index, archive, and wheel; the sole wheel-member
delta from `14bf53b` is `_registry/assembly.py`. The wheel retains all 15
attribution files, exactly one native module, no excluded layout, NumPy as its
only unconditional dependency, and only Python/Windows runtime native
dependencies. A fresh outside-repository environment containing exactly
SceneIO and NumPy passes the complete installed smoke and the explicit
aggregate, live-extension, NPY, Y4M, and directory-sequence probe. All three
independent preflight reviews are clear. The same gates are repeated after
this documentation-only closure edit before the final-artifact review.

Aggregate implementation:

- [x] Add a focused lower `_registry/assembly.py` service that imports only the
      immutable manifest and lower `Codec` model. It must not import
      `registry.py`, `sceneio.io`, inspection modules, family modules, or own a
      public registry.
- [x] Keep the `BuiltinAssembly` class in the lower module and only its
      instance/lifecycle facade-owned. Give it separate
      `add_codec(codec)` and `add_family(family_name, codecs)` methods.
      `add_family` validates directly against
      `FAMILY_MEMBERS[family_name]`; both methods reject unknown canonical ids,
      validate exact `Codec` type, order, uniqueness, and collisions, and use
      copy-on-success state updates.
- [x] Make production finalization require the exact
      `CANONICAL_BUILTIN_IDS` set and return the definitions in canonical order
      regardless of the order in which interleaved families were staged. A
      reduced canonical tuple is an explicitly private isolated-test seam; the
      facade always constructs the manifest default, and publication
      independently revalidates the exact 50 ids. Seal the builder after
      successful finalization; repeated `finalize()` calls return the same
      tuple object, while every subsequent add fails. Failed finalization
      leaves the builder unsealed and unchanged so missing definitions can
      still be supplied.
- [x] Replace built-in `register(Codec(...))` call sites with private staging
      calls and route the four extracted families through the same builder.
      Keep every `Codec` field, closure target, object identity within
      `BUILTIN_DEFINITIONS`, and definition source unchanged.
- [x] Populate the existing facade-owned `REGISTRY` only after successful
      finalization and in one validated operation. Preflight that initialization
      sees an empty registry and no collisions; any pre-seeded entry fails with
      registry contents and object identity unchanged. Preserve public
      `register()`, `get()`, detection, third-party extension, duplicate-id,
      and mutable-registry behavior exactly.
- [x] Construct `ImageFrameAccess` after image definitions are staged and
      before the sequence family is staged. Its `__post_init__` probe is
      expected to observe the still-empty live registry; prove this empty
      result is not cached. After the single aggregate publication, the same
      access object and newly created access objects must see all image
      definitions plus immediate third-party additions/removals. Never publish
      images early or fall back permanently to staged definitions.
- [x] Preserve `_install_builtin_family` completely until its existing
      architecture consumer is migrated: signature, successful mutation and
      order, `None` return, and every current failure. Built-in module
      initialization must use only the new aggregate path.
- [x] Change no codec implementation, inspection parser, C++, CMake, native
      symbol, backend, dependency, attribution file, public signature, or
      payload behavior. Add no FFmpeg/libav source, build hook, subprocess
      path, runtime dependency, package member, metadata entry, native symbol,
      or native dependency.

Aggregate verification:

- [x] Freeze parent `14bf53b` registry/capability/import/public-symbol
      snapshots, all 50 normalized `Codec` AST values, canonical object
      identities, representative detection outcomes, duplicate errors, and
      live image-sequence extension behavior before implementation.
- [x] Freeze every non-`None` runtime operation binding for all 50 codecs in a
      parent-only contract. Recursively describe callable module/qualname,
      `partial` target/arguments/keywords, closure free-variable targets, and
      normalized `ImageFrameAccess` callbacks; record parent commit/tree and
      the exact normalization map. Candidate code may reproduce descriptor
      hashes but must never generate its expected values.
- [x] Add isolated builder contracts for wrong types, wrong family order,
      duplicate ids, staged collisions, missing/extra canonical ids,
      failed-finalization rollback, same-object finalization idempotence, and
      add-after-finalize rejection. Every failing case must leave prior builder
      state unchanged. Prove observable recovery by staging the remaining valid
      definitions after each rejected add/finalize and reaching the exact same
      finalized tuple.
- [x] Prove the facade performs no public-registry mutation before aggregate
      finalization, publishes exactly once, rejects a pre-seeded target without
      mutation, retains the `REGISTRY` object, and produces the exact canonical
      order even when family members are non-contiguous.
- [x] Make one-publish evidence independent of the new helper. In a fresh
      process, install a profile/trace hook before importing the facade and
      record `BuiltinAssembly.finalize()` return, the actual `dict.update`
      call/return on the facade registry, compressed observed registry sizes,
      object ids, `register()` calls, and subscription stores. Require
      finalize-return before exactly one update, sizes only zero then 50, one
      registry object id, and no built-in `register()` or subscription
      mutation. Fault the publication seam with a pre-seeded target and prove
      exact items/object identity survive rejection.
- [x] Prove public `register()` is independent of the sealed builder, returns
      the supplied object, preserves immediate append and duplicate behavior,
      and retains its current acceptance of subclass or duck-typed objects.
      Exercise the full successful and failing `_install_builtin_family`
      compatibility surface separately.
- [x] Prove all 50 built-in `REGISTRY` values are the exact objects in
      `BUILTIN_DEFINITIONS`; family reload remains inert; registry reload is
      repeatable; third-party registration/removal remains immediate for old
      and new `ImageFrameAccess` objects. Extend the existing sequence contract:
      after adding an image extension, perform read, inspect, selected-frame
      read, and write through both old and new already-bound sequence codecs;
      after removal, require every operation through both codecs to fail.
- [x] Enforce lower import allowlists and prohibit aggregate ownership from
      leaking into family modules. Reconcile only the intended eager import
      addition and source-ownership changes. Codec coverage rows remain
      unchanged; `_registry/assembly.py` is the only intended new eager
      runtime module and planned wheel-member delta.
- [x] Run registry, compatibility, capability, detection, public E2E,
      image-sequence live-access, mmap/lifetime, sink, partial, inspection,
      zero-copy, family architecture, import, documentation, and attribution
      suites.
- [x] Compare one-pass 50-codec structure and strict five-run retained
      O4/O5/allocation results against `14bf53b`. Before coding, take two
      parent captures with identical commands and fixture seed, record the
      deterministic structural projection and predeclare any observed traced
      allocation tolerances. Candidate comparison requires exact codec order,
      payload/file sizes, nested schema, and exact-or-toleranced traced fields;
      timing and RSS remain diagnostic and the strict candidate guard runs
      separately. Preserve an auditable deterministic projection in a checked
      contract rather than relying on ignored raw JSON.
- [x] Freeze the parent 3,083 sorted pytest node ids, parameters, count, and
      digest. Candidate verification permits no removal or rename; additions
      must be exactly the predeclared aggregate-contract nodes plus the single
      assembly package-file guard node. Derive the final count from that set
      and then update the workflow pin.
- [x] Run 15-sample interleaved parent/candidate fresh-process imports.
      Require the exact eager-module delta of only `_registry.assembly`, every
      existing Windows alert, and no median increase above the greater of
      2 ms or 15% for any boundary. Then run the complete suite, Ruff,
      workflow parsing, and `git diff --check`.
- [x] Update architecture, organization, format-status, import, ownership,
      workflow-count, and benchmark documentation with measured evidence
      before freezing the final package tree. Final tree/archive/wheel hashes
      stay in commit evidence outside this self-referential source tree.
- [x] Obtain independent architecture/correctness and test/performance
      reviews of the frozen implementation and evidence; resolve their
      findings before the final package build.
- [x] Require zero unstaged files, record `git write-tree`, and materialize
      that exact tree with `git -c core.autocrlf=false archive <tree>` or an
      equivalent Git-object procedure. Build the source archive from the
      extracted object tree, compare every changed index blob byte-for-byte
      with its archive member, and derive the Windows cp312-abi3 wheel only
      from that source archive.
- [x] Measure rather than pre-pin the source-archive count. Require a 73-file
      wheel if `_registry/assembly.py` is the only new runtime member; assert
      that module is present while tests/contracts remain source-only. Require
      all changed runtime files to match index, archive, and wheel; retain all
      15 attribution files, one native module, no excluded layout directories,
      NumPy-only unconditional metadata, and no FFmpeg/libav additions.
- [x] In a fresh environment outside the repository containing only SceneIO
      and NumPy, run the complete installed-wheel smoke and an explicit
      aggregate probe: exact canonical registry order; `REGISTRY`/
      `BUILTIN_DEFINITIONS` identity for all 50 ids; public third-party
      add/remove and duplicate behavior; representative detection; immediate
      added/removed image-extension visibility through an already-bound
      image-sequence codec; and Y4M plus directory
      write/detect/inspect/read/frame-range behavior.
- [x] Obtain the independent platform/package/documentation review against
      those exact final artifacts. Any finding that requires a source edit
      invalidates the frozen tree and repeats all affected tests and package
      gates; otherwise make no source edit before commit.
- [x] Commit and push only after every local gate is green. Wait for normal
      CI and compiler-instrumented validation before moving arrays.

The aggregate boundary is committed as `1ec0550`, with exact commit tree
`24becc0d8b954a8d21511ae480092cad5818657e`. The final reviewed source
archive contains 310 files and has SHA-256
`bac56c42262379b2479c5e26d533366561cd61c5a0e35750aa150798dac87ffb`;
its 73-file Windows cp312-abi3 wheel has SHA-256
`3beb3560f7c1a2dc89a9830baabf3cdf512d3bacc2e47d4cbef344e40a069daa`.
The portable benchmark-structure correction is committed separately as
`6086315`; it changes no runtime or wheel member. Normal CI run 30204352767
and compiler-instrumented run 30204352744 pass the exact corrected commit.

### R2 arrays fifth-family unit

Parent behavior is frozen at commit
`6086315ea877c5e85136e05d47da3fe41f524d5a`, tree
`01c7425ac2ae1a9e4f36d98f9a15100f0f93a406`. This organization-only unit
moves the non-contiguous `pfm`, `npy`, `npz`, `safetensors`, `flo`, and `dmb`
definitions and their metadata inspectors. It changes no encoded bytes,
decoded values, mapped-view lifetime, selector semantics, or public API.

Arrays implementation:

- [x] Add a side-effect-free `_registry/families/arrays.py` factory whose only
      inputs are the existing facade-owned `_canon` and
      `_prepare_tensor_dict` callbacks. Keep those callback definitions and
      their module/qualified names in `registry.py` so the frozen writer
      operation descriptors remain byte-for-byte exact.
- [x] Move the six `Codec(...)` expressions without changing their AST,
      closure topology, adapter constructor, native target, field value, or
      relative family order. Build one immutable tuple in manifest order
      `pfm`, `npy`, `npz`, `safetensors`, `flo`, `dmb`.
- [x] Stage that complete tuple once through
      `_define_builtin_family("arrays", ...)`. Remove the six scattered
      `_define_builtin` blocks and preserve final canonical positions
      0/25/26/27/43/44 through aggregate finalization; do not install the
      family as one contiguous public-registry slice.
- [x] Preserve PFM copy decode/native window; NPY mapped-view/fallback;
      NPZ copy decode; safetensors full/tensor/slice mapped-view pairs; FLO
      full mapped view plus its separately constructed nested window reader;
      DMB copy decode/native window; and all existing sink preparation.
- [x] Add `_inspectors/arrays.py` for PFM, NPY/NPZ, safetensors, FLO, and DMB.
      Move `_npy_header` with the NPZ parser, keep SOG ZIP-extent ownership in
      the facade, use only lower common/model services, and call no full
      reader or writer.
- [x] Keep `_inspection.py` dispatch branches and historical wrapper
      signatures, including a compatible private `_npy_header` delegate.
      Keep every array-family `Codec.inspect` field `None`.
- [x] Change no C++, CMake, native symbol, backend, dependency, attribution,
      public signature, record convention, codec grammar, or payload behavior.
      Add no FFmpeg/libav source, runtime path, package member, or linkage.

Arrays parent contracts and focused verification:

- [x] Freeze the exact parent commit/tree, 3,095-node collection, six
      non-contiguous canonical positions, existing global Codec AST hashes,
      operation descriptors, helper identities, and eager-module sets before
      implementation.
- [x] Capture two parent all-codec benchmark runs with
      `--runs 1 --scale 0.001 --skip-oracles`; both reproduce portable
      all-codec hash
      `2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
      and arrays-only projection hash
      `5c0104dc8a0372ede12a86f48c8c57a7426718b030c95ec9d7088a9b26364aac`.
- [x] Freeze deterministic valid fixture bytes and normalized inspection
      values plus representative malformed cause type/text for all six
      formats from the parent, before candidate code exists.
- [x] Add one checked parent-derived arrays contract and an architecture suite
      covering exact ids, non-contiguous object identity, definition ASTs,
      nested callable targets, helper behavior/identity, one family-staging
      call, family/registry reload, and lower import allowlists.
- [x] Prove `_canon` preserves native contiguous input, canonicalizes
      non-contiguous/opposite-endian input, and that tensor preparation keeps
      exact `TensorDict` identity, mapping order, dtypes, and failure timing.
- [x] Compare lower and public inspection against the parent contract and full
      reads. Patch both already-captured registry readers and dynamic native
      reader attributes so the test cannot pass by intercepting only one
      decoder reference.
- [x] Preserve malformed outcomes and deliberate format distinctions:
      header-only inspection versus full payload validation, FLO trailing-byte
      acceptance, DMB exact extent, NPZ local/central metadata checks, and
      safetensors alignment fallback.
- [x] Exercise PFM gray/RGB and endian metadata; NPY dtype/shape/order cases;
      NPZ stored/deflate/order cases; safetensors metadata/tensor/slice cases;
      FLO raw/typed conventions; and DMB typed depth/window behavior.
- [x] Run mapped-view lifetime, derived-view ownership, readonly/mutation
      isolation, immediate rename/delete, fallback-copy, retained-exception
      release, and selector validation-order tests across the applicable
      NPY/safetensors/FLO paths. Confirm PFM/NPZ/DMB release their mappings
      after decode.
- [x] Use byte fingerprints rather than numeric equality for NaN payloads,
      signed zero, and dtype/order-sensitive cases.
- [x] Prove bounded metadata inspection on generated large/sparse fixtures,
      prompt path release, and retained-result validity; keep large fixtures
      outside Git.
- [x] Update the six repository inspection-owner rows, exact import contract,
      aggregate source paths, and measured pytest collection/digest without
      regenerating any parent expected value from candidate code.

Arrays performance, documentation, package, and validation:

- [x] Compare candidate A/B against both frozen parent captures. Require the
      exact all-codec and six-row portable structures, exact payload/file
      sizes, retained mmap/sink/inspect/partial memory relationships, and no
      claimed speedup for this mechanical move.
- [x] Run the strict five-run all-codec guard and a large safetensors
      full/inspect/tensor/slice allocation check. Keep timing and same-host RSS
      diagnostic.
- [x] Run the six codec parity suites, typed PFM/FLO suites, depth/flow/tensor
      record suites, mmap, zero-copy, sink, partial, inspection, detection,
      capability, compatibility, public E2E, aggregate, import, documentation,
      complete pytest, and Ruff checks.
- [x] Measure 15 interleaved same-host parent/candidate imports. Require the
      only I/O-facade eager-module additions to be
      `_registry.families.arrays` and `_inspectors.arrays`; `import sceneio`
      and direct `_core` module sets remain exact.
- [x] Update current architecture, organization, coverage, benchmark, import,
      ownership, workflow-count, and active-checklist documentation. Leave
      historical plans, public API docs, CMake, dependency metadata, and
      attribution unchanged unless verification finds a factual mismatch.
- [x] Obtain independent architecture/correctness, test/performance, and
      platform/package/documentation reviews and resolve every finding.
- [x] Freeze an exact Git-object tree, build the source archive from it, and
      build the Windows cp312-abi3 wheel only from that archive. Require the
      final inventory to distinguish 313 tracked Git files from 314 regular
      sdist files (the build backend adds `PKG-INFO`), and require the two new
      runtime modules as the only wheel-member additions (73 to 75), all
      changed runtime blobs identical across index/archive/wheel, 15
      attribution files, one native extension, NumPy as the only
      unconditional dependency, and unchanged native dependencies.
- [x] In a fresh outside-repository NumPy-only environment, run the complete
      wheel smoke plus explicit all-six write/detect/inspect/read probes,
      PFM/DMB/FLO windows, NPY/safetensors mapped lifetime, safetensors
      tensor/slice selectors, and NPZ name/dtype ordering.
- [x] Commit and push only after every local gate and final artifact review is
      clear. Exact commit `d99dcf0` is pushed; normal CI run 30207617248 and
      compiler-instrumented run 30207617253 pass before moving points.

The three independent reviews are clear after two test-soundness findings and
one package-evidence wording finding were resolved. Candidate benchmark,
import, and collection outcomes are no longer re-asserted from
candidate-authored contract values; the checked arrays contract contains only
parent-derived expectations, while the CI comparator and strict benchmark
guard remain the mechanical candidate gates. Safetensors tensor and slice
selectors now prove readonly mapped-view identity, derived views outliving
their returned records, Windows path locking through the last live view,
post-release deletion, and mapping cleanup while invalid-selector exceptions
remain retained. Package evidence now distinguishes the 313 tracked Git files
from the generated 314-file sdist.

The post-review package confirmation used staged tree
`4a5c0a4dab9937138e6fecb36429c3fe3b69d474`: 313 tracked files produce a
314-file sdist whose only generated member is `PKG-INFO`; every tracked file
is present byte-identically. The 75-file Windows cp312-abi3 wheel adds only
`_registry/families/arrays.py` and `_inspectors/arrays.py` relative to the
aggregate wheel. All four changed runtime files match Git, sdist, and wheel;
the wheel contains 15 attribution members, one native module, no excluded
layout, and NumPy as its only unconditional dependency. Its native dependency
list contains only Python and Windows runtimes. A fresh external environment
containing only SceneIO and NumPy passes `_wheel_smoke` and the explicit
all-six codec, window, mapped-lifetime, tensor/slice, and name/order probe.
The documentation-only checkbox closure is followed by one final exact-tree
artifact confirmation immediately before commit.

The final committed tree is
`750f1fce1fdc95974ec54b4ce7e0e01298fcca8c` at exact commit `d99dcf0`.
Normal CI run 30207617248 and compiler-instrumented run 30207617253 pass that
commit, including Windows/macOS/Linux mmap coverage, pinned GCC 10, the full
suite, the retained benchmark guard, and the instrumented lifetime/full-suite
jobs. The arrays unit is closed and the points family is active next.

### R2 points sixth-family unit

Parent behavior is frozen at commit
`efb106e9f1264c5666b37578972a4e902bc642a0`, tree
`fdaa2ced61b9aae9da9e32872bff16d20a80de9f`. This organization-only unit
moves `ply`, `pcd`, `xyz`, `pts`, `las`, and `laz` plus their metadata
inspectors. It changes no encoded bytes, decoded values, point-range behavior,
backend, public API, or supported format convention.

Points implementation:

- [x] Add immutable `_registry/families/points.py` definitions for the exact
      manifest tuple `ply`, `pcd`, `xyz`, `pts`, `las`, `laz`.
- [x] Move the six `Codec(...)` expressions without changing adapter
      constructors, native targets, feature declarations, lossy flags, or
      nested point-range closures.
- [x] Stage the family once through `_define_builtin_family("points", ...)`
      and preserve canonical positions 12, 13, 39, 40, 41, and 42 after
      aggregate finalization.
- [x] Add `_inspectors/points.py` for PLY, PCD, XYZ, PTS, LAS, and LAZ
      metadata-only inspection. Keep parsing helpers below `_inspection.py`
      and keep the facade dispatch and same-signature wrappers compatible.
- [x] Preserve PLY ASCII/binary distinctions, PCD ASCII/binary/compressed
      distinctions, XYZ streamed count/columns, count-prefixed PTS, LAS
      waveform-sidecar metadata, and LAZ chunk-table validation.
- [x] Change no C++, CMake, dependency, package metadata, codec backend,
      attribution, public signature, record convention, or payload behavior.
      Add no FFmpeg/libav source, runtime path, package member, or linkage.

Points contract and correctness verification:

- [x] Freeze the exact parent commit/tree, 3,134-node collection, manifest
      members, six non-contiguous positions, feature declarations, and
      partial-reader availability before implementation.
- [x] Capture two parent all-codec benchmark runs with
      `--runs 1 --scale 0.001 --skip-oracles`; both reproduce all-codec hash
      `2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
      and points-only hash
      `8282b574166aeb88d0eb51ded126566d7a4f21b0752244ea0c987dcee06437bd`.
- [x] Freeze deterministic valid fixtures, normalized inspection values, and
      representative malformed outcomes for all six formats from the parent.
- [x] Add a parent-derived points contract and architecture suite covering
      exact ids/positions/object identity, definition/callable descriptors,
      one family-staging call, reload/idempotence, lower import allowlists,
      and inspector ownership.
- [x] Prove lower/public inspection agrees with parent contracts and full
      reads without calling a full decoder.
- [x] Exercise PLY ASCII/little-endian/big-endian, PCD
      ASCII/binary/binary-compressed, XYZ/PTS text layouts, LAS supported
      versions/point formats/waveform metadata, and LAZ supported point
      formats/chunk layouts.
- [x] Run exact full-versus-point-range differential tests for every
      advertised partial path, including empty/boundary ranges and formats
      that deliberately refuse non-bounded encodings.
- [x] Run mmap/path-release, retained-exception release, readonly input,
      malformed/truncated extent, and generated large-file allocation checks.
      Keep generated large fixtures outside Git.
- [x] Update import, assembly, collection, ownership, workflow, architecture,
      coverage, benchmark, and active-checklist contracts with measured
      candidate evidence only.

Points performance, package, and validation:

- [x] Compare candidate output with both frozen parent captures. Require exact
      50-row and six-row structural projections, payload/file sizes, and
      mmap/sink/inspect/partial memory relationships; claim no speedup for the
      mechanical move.
- [x] Run the strict five-run all-codec guard plus point-family large-fixture
      inspection and partial-read allocation checks.
- [x] Run all six parity suites, LAS waveform and LAZ chunk suites, mmap,
      sink, inspection, detection, partial, public E2E, architecture,
      documentation, complete pytest, and Ruff checks.
- [x] Compare interleaved parent/candidate imports and require only
      `_registry.families.points` and `_inspectors.points` as intentional
      I/O-facade additions.
- [x] Build an exact-tree source archive and Windows cp312-abi3 wheel; verify
      source/archive/wheel identity, license inventory, NumPy-only
      unconditional dependency, one native extension, and unchanged native
      dependencies.
- [x] In a fresh external NumPy-only environment, run complete wheel smoke
      plus all-six write/detect/inspect/read and point-range probes.
- [x] Obtain independent architecture/correctness, test/performance, and
      platform/package/documentation reviews; resolve every finding.
- [x] Commit and push only after local and artifact gates are clear. Wait for
      normal CI and compiler-instrumented validation before moving
      reconstruction.

Current candidate evidence: 48 points-architecture nodes pass; the six parity
suites plus LAS waveform, mmap, partial, inspection, public E2E, registry, and
documentation checks pass as a 687-test focused matrix. The complete local
suite passes 3,180 tests with four documented skips, and Ruff is clean. The
exact collection is 3,184 nodes with sorted normalized SHA-256
`76d13c72f8b3b4903bc05112dd3f1446fb64ed17e18a2e9cead2fecb58c44cab`.
Parent A/B and candidate benchmark structures match both checked hashes, and
the strict five-run O4/O5 guard passes. Fifteen interleaved Windows samples
measure candidate/parent medians of 17.565/18.287 ms for `import sceneio`,
89.031/87.407 ms for the I/O facade, and 19.725/19.734 ms for direct `_core`;
only the two intended lower point modules are added.

Pre-review package evidence uses staged tree
`942314b30d5e21a62420a0c1ff1332356046792b`. Its 317 tracked files produce a
318-file sdist with only generated `PKG-INFO` extra and no missing or differing
tracked blob; the sdist SHA-256 is
`2cd51368e13c5f93fb98e53214861c9d0356686f9a727bda5f23157cc14a4405`.
The Windows cp312-abi3 wheel has 77 members, SHA-256
`8310dfb7102cb4dd1b6e8390a9b803831ae3bd7877273aa3c5c418f76694aa5c`,
and adds only `_registry/families/points.py` and `_inspectors/points.py`
relative to the arrays wheel. All four changed runtime files are identical
across Git, sdist, and wheel. The wheel contains 15 attribution members, one
native extension, no excluded build layout, and NumPy as its only
unconditional dependency; native dependencies are Python and Windows
runtimes only. A fresh external environment containing exactly SceneIO and
NumPy passes `_wheel_smoke` plus all-six write/detect/inspect/read,
point-range, retained-result, and path-release probes. A final exact-tree
artifact confirmation follows review-driven edits and checklist closure.

All three independent reviews are clear for staged tree
`442093b402db2af290c9a19a61747b6691e2af1c`. Architecture/correctness
confirmed exact parent ASTs, canonical order and bindings, metadata behavior,
partial slices, reload behavior, and path release. Test/performance
independently reproduced the parent fixtures, 3,184-node collection and
digest, both benchmark projections, and strict five-run guard; its focused
matrix passed 729 tests. Platform/package/documentation reproduced the
pre-review source and wheel inventories, runtime-file identity, attribution
inventory, NumPy-only dependency closure, native dependency set, installed
smoke, and six-format public probe. No review required a source change.

The final exact-tree confirmation used tree
`688f0a4caa81edf6e499f7b72e1bc03117a4ddf0`. Its 317 tracked blobs are
byte-identical in the 318-file source archive, whose only extra is generated
`PKG-INFO`; the archive SHA-256 is
`cad77d9a9b311c686279d150cc2a68c4a4221f21db1b1cdc2473af38d96ce3ab`.
The 77-member Windows cp312-abi3 wheel SHA-256 is
`171aa3ff0b6e28a59ca45489b72818289a2dbb7f8bf63dd5e666be9b9221676a`;
its non-native, non-`RECORD` members are byte-identical to the reviewed
pre-review wheel. Commit `686f42e177e0706ec7a543c6bb2644fa39f97a23`
has that exact tree and is pushed. Normal CI run 30210055913 and
compiler-instrumented run 30210055930 pass the exact commit. The points unit
is closed; reconstruction is next.

### R2 reconstruction seventh-family unit

The mechanical extraction keeps the existing 12-member
`FAMILY_MEMBERS["reconstruction"]` partition intact across documentation and
parent freeze, inspector extraction, registry extraction, and evidence
closure. Those moves change no codec algorithm, encoded payload, decoded
value, public API, C++, CMake, dependency, backend, or format convention.
Hosted validation additionally required a test-fingerprint correction,
BAL exact-zero quaternion canonicalization, and an isolated GCC-10 invocation
repair. The BAL follow-up intentionally changes only platform-dependent
signed-zero component bits; the represented rotation, format conventions,
and every nonzero coefficient remain unchanged.

Parent behavior is frozen before the documentation commit at exact commit
`074d8d9b33711658423de8e7787a97f43bf09982`, tree
`b329d05eabea9387e51efa1edcf2a29535c5c802`. The parent collects 3,184 nodes
with normalized collection SHA-256
`76d13c72f8b3b4903bc05112dd3f1446fb64ed17e18a2e9cead2fecb58c44cab`.
The current 50-row benchmark projection is
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`;
the ordered 12-row reconstruction projection is
`92d354dfd4aa415cbd908168d55310902e56fd21541c94d66fc740c1915540d9`.
Two captures from an extracted exact parent tree must reproduce both hashes
before source movement begins.

| Format | Position | Carrier and unchanged adapter | Partial operation |
|---|---:|---|---|
| `colmap_sparse` | 1 | directory, direct native path I/O, `cameras.bin` marker | image |
| `transforms_json` | 15 | named `transforms.json`, mmap reader/file sink | none |
| `tum` | 16 | explicit-format file, mmap reader/file sink | none |
| `kitti` | 17 | explicit-format file, mmap reader/file sink | none |
| `euroc_state` | 18 | magic-detected file, mmap reader/file sink | state range |
| `g2o` | 23 | extension/magic file, mmap reader/file sink | none |
| `colmap_db` | 24 | `.db`/`database.db`, direct native SQLite path I/O | image and pair |
| `colmap_sparse_txt` | 38 | directory, direct native path I/O, `cameras.txt` marker | image |
| `bundler` | 45 | extension/magic file, mmap reader/file sink | none |
| `bal` | 46 | extension file, mmap reader/file sink | none |
| `nvm` | 47 | extension/magic file, mmap reader/file sink | none |
| `openmvg` | 48 | named `sfm_data.json`, mmap reader/file sink | none |

Documentation and exact-parent freeze:

- [x] Extract exact parent source at commit `074d8d9` with
      `core.autocrlf=false`; run two all-codec
      `--runs 1 --scale 0.001 --skip-oracles` captures and independently
      reproduce the 50-row and ordered 12-row hashes above.
- [x] Add `tests/contracts/io_reconstruction_family_v1.json` using parent-only
      evidence: exact ids/positions, record/datatype/container properties,
      extensions/filenames/magic/markers, feature tuples, adapter and selector
      targets, valid fixtures, logical full-read fingerprints, normalized
      inspections, and representative malformed causes.
- [x] For both COLMAP directories, store ordered member-name to byte-size and
      SHA-256 maps. For `colmap_db`, use a canonical logical schema/row/BLOB
      fingerprint as the primary contract; keep the raw database hash only as
      secondary same-host evidence.
- [x] Fingerprint substantive values, not counts alone: array
      dtype/shape/byte hashes; camera models/parameters; image ids/names/poses;
      point arrays; trajectory fields; graph endpoints, information matrices,
      and fixed flags; database optional/empty distinctions; match geometry;
      ordering; and convention metadata. Track CSR is internal to the native
      Reconstruction carrier, so its fidelity remains pinned by the dedicated
      COLMAP parity and roundtrip suites rather than this public-record
      fingerprint.
- [x] Record missing/truncated COLMAP members, invalid database schema, and one
      representative malformed parent outcome for every family member.
      Preserve deliberate inspect/full distinctions, including metadata-only
      COLMAP binary and BAL inputs that a full decode may reject.
- [x] Obtain three independent planning reviews. All recommend one intact
      manifest family, inspector-first and registry-second implementation
      commits, and a separate evidence-closure commit. The focused baseline is
      631 passed with two documented skips.
- [x] Commit and push this documentation/freeze checkpoint only after
      documentation consistency, link, Ruff, and diff checks pass.

Inspector extraction checkpoint:

- [x] Add `_inspectors/reconstruction.py` and mechanically move the existing
      implementations for COLMAP binary/text/database, transforms JSON,
      TUM/KITTI pose text, EuRoC state, g2o, Bundler, BAL, NVM, and OpenMVG.
      Move reconstruction-exclusive `_directory_size` and `_iter_data_lines`
      helpers with them; retain a local `_size` where each remaining owner
      needs it.
- [x] Restrict the lower module to `pathlib`, `struct`, `_core`,
      `_inspectors.common`, and `_inspectors.model`. It must not import the
      registry, `_inspection.py`, another family, or an oracle package.
- [x] Keep `inspect_path` dispatch in `_inspection.py` and retain
      same-signature compatibility wrappers for every moved function. Prove
      exact signatures and direct delegation.
- [x] Preserve binary COLMAP count-header reads, text COLMAP native metadata
      scanning and immediate-directory sizing, database inspection without
      feature/match BLOB fetches, streamed TUM/KITTI field validation, Bundler
      registered-camera counting, NVM/native JSON parser behavior, and exact
      EuRoC/g2o convention metadata.
- [x] Update all 12 inspection-ownership rows, the import contract, collection
      contract and workflow pin. At this checkpoint, the I/O import set may
      add exactly `_inspectors.reconstruction`; `import sceneio` and direct
      `_core` sets remain unchanged.
- [x] Add the inspection half of
      `test_io_reconstruction_family_architecture.py`: lower import allowlist,
      inert reload, facade signatures/delegates, parent valid/malformed parity,
      inspect/full agreement, metadata-only operation, bounded large
      inspection, and success/exception path release.
- [x] Exercise large valid pose text, g2o, transforms/OpenMVG JSON, COLMAP
      header/member files, and large database BLOBs without constructing full
      records. Generated fixtures remain outside Git.
- [x] On Windows, prove retained inspection results and retained exceptions do
      not prevent rename/removal of single files, COLMAP member files and
      directories, or the database. Database inspection must not create
      journal or WAL side files.
- [x] Run the 11 codec suites, record suites, mmap, partial, public E2E,
      registry/inspection/capability/snapshot/import/documentation checks,
      complete pytest, Ruff, benchmark structure comparison, and retained
      five-run guard.
- [x] Build an exact-tree source archive and wheel; run the current packaged
      smoke in a fresh NumPy-only environment. Obtain independent
      architecture/correctness, test/performance, and
      platform/package/documentation reviews before committing and pushing.
      Require green normal and compiler-instrumented hosted runs before the
      registry checkpoint.

Inspector candidate evidence: all 53 reconstruction architecture nodes pass;
the 11 codec suites pass 436 tests with the two documented Windows/oracle
skips. The complete suite passes 3,234 tests with four documented skips, Ruff
and diff checks are clean, and the exact 3,238-node collection has normalized
SHA-256
`8c23d3f28a347583ddec643e1f6431c14766f046cb406acf4af775f2c839f4e4`.
Two candidate benchmark captures reproduce the all-50 hash
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered 12-row hash
`92d354dfd4aa415cbd908168d55310902e56fd21541c94d66fc740c1915540d9`;
the strict default-scale five-run O4/O5 guard passes. Fifteen interleaved
Windows samples measure candidate/parent medians of 5.577/5.793 ms for
`import sceneio`, 74.896/75.579 ms for the I/O facade, and 7.398/7.410 ms for
direct `_core`. Only `_inspectors.reconstruction` is added to the I/O module
set; the other module sets are exact. Large-fixture memory values in this
checkpoint are traced Python allocations; native parser working memory is
diagnostic and is not described by the 2 MiB `tracemalloc` bound.

Registry extraction checkpoint:

- [x] Add immutable, side-effect-free
      `_registry/families/reconstruction.py` with the exact 12
      `RECONSTRUCTION_CODECS` above. Move each `Codec(...)` expression
      mechanically without changing values.
- [x] Stage the complete tuple exactly once through
      `_define_builtin_family("reconstruction", RECONSTRUCTION_CODECS)`.
      Preserve canonical positions, registry object identity, aggregate
      identity, reload/idempotence, and binary-before-text COLMAP directory
      detection precedence.
- [x] Preserve direct native path operations for both COLMAP directories and
      `colmap_db`. Preserve the nine mmap/file-sink closures, EuRoC's mmap
      state-range selector, both COLMAP image selectors, and both database
      image/pair selectors with their exact native targets.
- [x] Preserve explicit-format-only TUM/KITTI behavior, named-file detection
      for `transforms.json`, `database.db`, and `sfm_data.json`, all
      extension/magic neighbors, and suffixless default `Reconstruction`
      writer selection.
- [x] Add the family source to the authoritative Codec AST scan. Prove exact
      tuple order, positions, object identities, ASTs, callables/closure
      targets, record classes, capabilities, flags, and one staging call with
      no remaining inline family definitions.
- [x] Add a uniform all-12 public test covering write, each format's promised
      detection or explicit-format rule, inspect, read, and logical record
      equality. Hand-built COLMAP binary fixtures must keep the NumPy-only
      path independent of optional `pycolmap`.
- [x] Differentially test all persisted binary/text COLMAP image ids,
      first/middle/last and complete EuRoC half-open ranges, and database image
      and unordered-pair selection. Cover missing/negative ids, invalid ranges,
      sparse ids, reversed pairs, absent versus present-empty database rows,
      duplicate endpoints, and unselected malformed content.
- [x] Prove nine mmap-decoded records own their results after mapping closure;
      EuRoC partial success/failure releases its mapping; both COLMAP
      directory full/image/inspection paths release every member; and database
      full/image/pair/inspection success and failure release all handles while
      retained arrays remain valid.
- [x] Extend the NumPy-only installed-wheel smoke so every one of the 12
      members maps to an executed smoke helper, replacing the eight current
      family exemptions without duplicating already-covered EuRoC, g2o, BAL,
      and database cases.
- [x] Update import/assembly/ownership/collection/workflow contracts. The final
      I/O import set must add exactly `_inspectors.reconstruction` and
      `_registry.families.reconstruction` to the 41-module parent set;
      `import sceneio` and direct `_core` remain at their exact parent sets.
- [x] Add a dedicated three-OS reconstruction CI job for the architecture and
      11 codec suites; include the architecture suite in the manylinux2014
      GCC-10 lane. Update the compiler-instrumented collection pin only from a
      final `pytest --collect-only` result.
- [x] Repeat focused/full/Ruff, two-parent-versus-candidate benchmark
      structure, retained five-run, import, exact-tree package, installed
      wheel, three-review, commit/push, and hosted-run gates.

Registry checkpoint evidence: the 12 definitions now come from the
immutable, inert `_registry/families/reconstruction.py` tuple and are staged
once. Their Codec AST hashes and native/wrapper callable descriptors remain
identical to the frozen parent. The expanded architecture suite passes 70
tests; the architecture plus 11 codec suites pass 506 tests with two
documented platform/oracle skips. The complete local suite passes 3,252 tests
with four documented skips, and the exact collection is 3,256 nodes with
sorted normalized SHA-256
`156a06a5fb3b801073253892d9d584f8a9dcb230ccd42babf056b2a020c71347`.
Ruff and diff checks pass. Both one-run candidate captures reproduce all-50
SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered 12-row SHA-256
`92d354dfd4aa415cbd908168d55310902e56fd21541c94d66fc740c1915540d9`;
the strict default-scale five-run guard passes. A three-run scale-1
family-only capture exercises encoded files up to 35.2 MiB and confirms
bounded Python mmap/sink allocation plus retained inspection/partial
directions. Windows reports the requested cold-cache hint as unavailable
because it has no `POSIX_FADV_DONTNEED`; those measurements are warm-cache
diagnostics, not cold-cache claims. The I/O facade now imports exactly 43
SceneIO modules, adding only `_registry.families.reconstruction` to the
inspector checkpoint; `import sceneio` and direct `_core` remain at seven and
eight modules. Fifteen interleaved exact-export samples, isolated from the
editable finder with `python -S` and an explicit `PYTHONPATH`, measure
18.687/18.771 ms for `import sceneio`, 96.710/96.938 ms for the I/O facade,
and 21.696/21.711 ms for direct `_core` (parent/candidate medians). Module-set
equality, not these diagnostic timings, is the acceptance contract.
The reviewed exact tree has 321 tracked files, a 322-file source archive with
only generated `PKG-INFO`, and a 79-member wheel. Changed runtime files match
byte-for-byte, the NumPy-only installed-wheel smoke exercises all 12 members,
and all three independent reviews are clear after resolving one stale
checklist-status finding. The registry extraction is pushed at `be836a0`.
Hosted normal run `30216568265` then exposed two platform-only follow-ups:
AppleClang retained `-0.0` in BAL's canonical 180-degree quaternion where the
contract requires `+0.0`, and the GCC-10 command changed to `/tmp` without
keeping `/work` importable. The BAL repair normalizes only exact-zero
quaternion components after sign selection. The separate workflow repair keeps
the installed-package test isolation at `/tmp` while setting command-scoped
`PYTHONPATH=/work` so the architecture test can import its benchmark fixture
module. Those repairs are committed at `1f32b49` and `aa5b624`.

The final combined implementation tree is
`06f89e8b685c3536af0e67a462d9cff90a86bc9c`. Its source archive SHA-256 is
`89304b849aeef699fadb79c2fed8c211b6bd84150ff4bfe313b9b7547ff7bccb`
and its Windows cp312-abi3 wheel SHA-256 is
`ffbc561b547423cb6266db2540afdb698f75b5f30785077bd1cead7f8570b87b`.
All three independent repair reviews are clear. Normal run `30218232248` and
compiler-instrumented run `30218232246` pass the combined tree, including
macOS BAL bytes, the isolated GCC-10 command, all three reconstruction
operating systems, the complete suite and retained benchmark guard, all mmap
lanes, and both compiler-instrumented jobs. The reconstruction registry
checkpoint is closed; splats are the only remaining R2 family.

Final evidence and documentation closure:

- [x] Require candidate equality with both parent captures for all 50 rows and
      the ordered 12-row reconstruction projection. Run the strict five-run
      guard and measured family-only large/cold-cache cases; record unavailable
      cold-cache behavior honestly on platforms that cannot provide it. Claim
      no speedup for this mechanical extraction.
- [x] Run 15 interleaved parent/candidate import samples. Treat exact module
      sets as the contract and timings as diagnostic evidence.
- [x] Freeze a zero-unstaged staged tree, export it with
      `core.autocrlf=false`, build the source archive from that tree, and build
      the wheel only from the exact archive. Compare every staged blob and all
      changed packaged runtime files byte-for-byte across Git, archive, and
      wheel.
- [x] Measure the final inventory rather than forcing an estimate: 321 tracked
      files, 322 source-archive files including generated `PKG-INFO`, and 79
      wheel members.
- [x] Verify 15 license/attribution members, one native extension, no packaged
      build/include/lib/share/bin layout, NumPy as the sole unconditional
      dependency, and unchanged native dependencies. Add no FFmpeg/libav code,
      linkage, subprocess path, runtime member, or attribution.
- [x] Install the exact wheel outside the repository with only NumPy and run
      `_wheel_smoke` plus the all-12 detection/explicit-format, inspect, read,
      partial, retained-result, and path-release probes.
- [x] After the extraction and both repair commits are independently reviewed
      and hosted green, update `core_architecture.md`,
      `repository_organization_plan.md`, `format_coverage.md`, this checklist,
      and `bench/BASELINE.md` with exact line counts, collection/import counts,
      hashes, artifact inventories, review resolutions, commit ids, and
      workflow ids.
- [x] Stage this evidence closure for the next branch commit and push. Do not
      trigger the publish workflow, create a tag, or publish a package. After
      closure, splats are the only remaining R2 family.

### R2 splats eighth-family unit

Splats are the eighth and final R2 family. The unit keeps the existing
six-member `FAMILY_MEMBERS["splats"]` partition intact:
`gaussian_ply`, `compressed_ply`, `sog`, `ksplat`, `spz`, and `splat`.
This is an ownership-only extraction. It changes no codec algorithm, encoded
payload, decoded value, public API, C++, CMake, dependency, backend, or format
convention, and it claims no speedup.

The exact parent is commit
`0696533e515b5f8e65cbb676df28d852f9d0a049`, tree
`62a844b198dfd05d5d6d435a8e2aa22bf6bb898e`. It collects 3,256 tests with
sorted normalized node-id SHA-256
`156a06a5fb3b801073253892d9d584f8a9dcb230ccd42babf056b2a020c71347`.
Two independent parent captures using
`--runs 1 --scale 0.001 --skip-oracles` reproduce the all-50 structural
projection SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered six-row splat projection SHA-256
`5c6adc3584ba25050c885b37313d009311e2253b0c841cbc8738b806cb090bfd`.

| Format | Position | Carrier and unchanged adapter | Detection and partial operation |
|---|---:|---|---|
| `gaussian_ply` | 2 | file, mmap reader/file sink | PLY schema; point range |
| `compressed_ply` | 3 | file, mmap reader/file sink | `.compressed.ply` plus PLY schema; point range |
| `sog` | 4 | ZIP file or directory/`meta.json`, hybrid path adapter | `.sog`, `meta.json`, or directory marker; point range |
| `ksplat` | 5 | file, mmap reader/file sink | `.ksplat`; point range |
| `spz` | 14 | file, mmap reader/file sink | legacy gzip or `NGSP`; no partial selector |
| `splat` | 49 | headerless file, mmap reader/file sink | `.splat` only; point range |

Three independent planning reviews are complete. Their common priorities are
the parent contract, inspector-first and registry-second commits, exact PLY
and SOG routing, retained-result/path-release coverage, self-contained
Gaussian PLY and SPZ fixtures, all-six installed-wheel smoke, and focused
cross-platform validation. The review-specific findings are incorporated
below.

Documentation and exact-parent freeze:

- [x] Add `tests/contracts/io_splat_family_v1.json` from exact-parent evidence.
      Freeze all six Codec ASTs, canonical positions and neighbors, object and
      operation identities, callable/closure descriptors, extensions,
      filenames, magic values, directory markers, flags, feature tuples,
      valid fixtures, normalized inspections, logical full-record
      fingerprints, partial results against frozen full-record slices where
      supported, and one representative invalid-input outcome per codec.
- [x] Freeze both SOG representations and all accepted entry paths: `.sog`
      archive, directory, direct `meta.json`, and explicit-format reads from
      suffixless or alternate-suffix archive paths. Preserve archive versus
      directory inspection metadata and byte-size behavior.
- [x] Freeze PLY classification independently of registry order:
      compressed-chunk schema, mesh/list schema, exact Gaussian SH schema, and
      generic point PLY. Include `.compressed.ply`, ordinary `.ply`, and
      extensionless PLY-magic cases.
- [x] Freeze SPZ legacy versions 1-3 and v4 separately. Preserve the current
      gzip-header and `NGSP` routing, inspection metadata, and normalized
      invalid/truncated outcomes without changing the two implementations.
- [x] Add an oracle-independent architecture fixture for Gaussian PLY and SPZ.
      Their dedicated parity modules currently collect five and 13 tests but
      skip as modules when `gsply` is unavailable. The new fixture must keep
      the GCC-10 and NumPy-only installed-wheel paths self-contained while the
      existing oracle tests remain the parity authority.
- [x] Make the oracle-independent invalid-input matrix substantive:
      Gaussian PLY truncated headers, malformed format/property schemas, and
      invalid declared extents; SPZ raw and gzip header truncation,
      unsupported version/degree/fractional-bits values, and invalid declared
      count extents; and SPLAT sizes not divisible by 32.
- [x] Add `tests/test_io_splat_family_architecture.py`, initially against the
      exact parent. Prove the six-member manifest partition, parent
      definitions, inspections, full records, partial slices, invalid-input
      behavior, SOG representations, and detection rules before source moves.
- [x] Record the focused parent surface: five Gaussian PLY, 21 compressed PLY,
      28 SOG, 35 KSplat, 13 SPZ, and 11 splat codec nodes, plus the common
      mmap, partial, capability, registry, inspection, and public-API suites.
      Do not pre-compute the candidate collection count; derive its exact
      count and digest after the final test set exists.
- [x] Commit and push the validated documentation/parent-freeze checkpoint
      only after
      documentation consistency, link, Ruff, architecture-contract, and diff
      checks pass. Initial commit
      `93fcf1b39350a3a0080a7b87ead65d0d9343d354` exposed the platform
      variants. Corrected commit
      `18643595ef538f5c9d5803ef20218a3327de04ef` is pushed; normal
      [run 30221945705][r2-splat-parent-corrected] passes every lane,
      including all three splat OS jobs and pinned manylinux2014/GCC-10, and
      compiler-instrumented
      [run 30221945731][r2-splat-parent-corrected-instrumented] passes both
      native lifetime jobs.

Parent-freeze evidence: the oracle-independent architecture suite
passes all 31 nodes. The architecture plus registry-assembly contract passes
42 tests, and the focused family/common matrix passes 385 tests with one
documented `gsply` v2-writer skip. The exact candidate collection is 3,287
nodes with sorted normalized SHA-256
`190733ef6fbf1dd99cdd721ddc19277fc22dca3643154f11bf9738aa52dbc294`;
the assembly contract and compiler-instrumented workflow pin match it. The
checked six-row benchmark projection artifact reproduces both parent captures
and SHA-256
`5c6adc3584ba25050c885b37313d009311e2253b0c841cbc8738b806cb090bfd`.
Hosted [run 30220612832][r2-splat-parent-exposing] and the pinned
manylinux2014/GCC-10 reproduction completed the platform investigation.
Gaussian PLY, compressed PLY, KSplat, SPZ, and SPLAT encoded bytes are exact
across the observed MSVC, hosted AppleClang, hosted glibc, and GCC-10 builds.
SOG has two deterministic parent profiles: Windows/MSVC and
macOS/AppleClang serialize
`means.mins[2]` as `-0x1.193ea7aad030bp+0`; hosted glibc and the pinned
GCC-10 image serialize the adjacent double
`-0x1.193ea7aad030ap+0`. That one JSON digit and its two ZIP CRC copies are
the complete archive difference; all five lossless-WebP layers, member order,
sizes, inspections, and decoded records are exact.

The same run exposed three decoded-only parent variants while their encoded
bytes remained exact: KSplat and SPLAT scales differ by at most one float32
ULP through platform `logf`, and SPZ v3/v4 quaternions differ by at most one
float32 ULP on AppleClang/ARM through floating-point contraction. The contract
therefore keeps unaffected fields bit-exact, applies a maximum-one-ULP check
only to those named arrays, and retains exact whole-record fingerprints for
all four build profiles. This is evidence about existing parent behavior, not
a codec change or a claim that SOG archives are globally byte-canonical.
Corrected normal [run 30221945705][r2-splat-parent-corrected] passes all
three splat OS profiles and the pinned manylinux2014/GCC-10 profile.
Compiler-instrumented
[run 30221945731][r2-splat-parent-corrected-instrumented] passes both jobs.

Inspector extraction checkpoint:

- [x] Add `_inspectors/splats.py` and mechanically move
      `_inspect_gaussian_ply`, `_inspect_compressed_ply`, `_inspect_sog`,
      `_inspect_ksplat`, `_inspect_spz`, and `_inspect_splat`. Move the
      SOG-only classic-ZIP extent helper with them. Keep shared PLY parsing and
      classification in `_ply.py`.
- [x] Keep `inspect_path` dispatch in `_inspection.py` and retain
      same-signature compatibility wrappers for all six private inspector
      names. Prove exact signatures and direct delegation.
- [x] Keep the lower inspector independent of the registry, compatibility
      facade, other family inspectors, and optional oracle packages. Prove an
      explicit lower import allowlist and inert reload.
- [x] Preserve Gaussian little- and big-endian binary PLY inspection,
      compressed PLY extent checks, SOG bounded `meta.json` and exact member
      validation, KSplat bounded header/section metadata reads, SPZ
      16-byte legacy and 32-byte v4 header inspection, and the headerless
      SPLAT 32-byte record count.
- [x] Prove inspector extraction parity for valid and invalid inputs and prove
      that metadata inspection does not invoke a full decoder.
- [x] Add generated large-file inspection cases for all six formats. Assert
      bounded traced Python allocation and immediate path release; treat
      native working memory and timing as diagnostics, not acceptance claims.
- [x] On Windows, prove retained `Inspection` results and retained exceptions
      do not prevent rename/removal. Cover all six files plus the SOG archive,
      directory, direct `meta.json`, declared layers, and whole-directory
      replacement/removal.
- [x] Update all six `repository_coverage_v1.toml` inspection owners and the
      import contract. The I/O facade may add exactly `_inspectors.splats` to
      the 43-module parent set; `import sceneio` and direct `_core` remain at
      seven and eight modules.
- [x] Run the new architecture suite, six codec suites, mmap/partial,
      inspection/capability/public/registry/repository contracts, complete
      pytest, Ruff, two structural captures, and the retained five-run guard.
      Build and smoke the exact-tree package before committing and pushing the
      inspector checkpoint.

Inspector candidate evidence: `_inspectors/splats.py` now owns the six
metadata implementations and the SOG-only classic-ZIP extent helper;
`_inspection.py` retains dispatch, same-signature wrappers, and historical
shared-helper identities. The architecture suite collects 44 nodes. Its
Windows lifecycle cases retain successful results and failures while renaming
or removing all six files, SOG archives, SOG directories, direct
`meta.json` paths, each declared layer, and whole directories followed by
same-name replacement. The complete candidate collection is 3,301 nodes with
sorted normalized SHA-256
`ab9ab8c698e005032aeea52d69703b5b32ee29998fdd77c24970f6a198b7c176`.

Two candidate captures reproduce the all-50 structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered six-row SHA-256
`5c6adc3584ba25050c885b37313d009311e2253b0c841cbc8738b806cb090bfd`;
the strict default-scale five-run guard passes. An inspector-specific
comparison loads the exact parent implementation from `0696533`, uses the
same generated 36 MiB-plus fixtures, and takes 15 randomized interleaved
timing plus 15 traced-allocation samples per implementation and codec.
Candidate median increase must not exceed the maximum of 10 percent of the
parent median, three times the sum of both median absolute deviations, or
0.05 ms. Parent/candidate medians in milliseconds are 0.0343/0.0355
(`gaussian_ply`), 0.0852/0.0841 (`compressed_ply`), 0.3667/0.3642 (`sog`),
0.0292/0.0297 (`ksplat`), 0.0324/0.0324 (`spz`), and 0.0057/0.0059
(`splat`). Maximum traced bytes match the parent exactly at 11,650, 15,339,
1,059,105, 14,394, 10,012, and 1,320 in the same order. This closes the
all-six inspector timing/allocation review finding; the broader
read/write/partial comparator remains part of registry closure.

Fifteen fresh-process Windows candidate samples retain exact module sets of
7, 44, and 8 for `import sceneio`, the I/O facade, and direct `_core`.
Candidate medians are 4.659, 71.611, and 6.579 ms respectively; timing is
diagnostic and exact module membership is the contract.

The finalized focused family/common matrix passes 401 tests with the one
documented `gsply` v2-writer skip. The complete local suite passes 3,297 tests
with four documented skips; Ruff, documentation, license, collection, and
diff checks pass. Pre-final package tree
`301fd6693fe758dfd555337708bf7bd0ca73384a` has 325 tracked files. Its
326-file source archive adds only generated `PKG-INFO`, has no missing or
differing tracked file, and has SHA-256
`f04fc37d7b79ecc41d19744dee7195746ab306e78f626a1dc387e48ef3a29606`.
The derived 80-member Windows cp312-abi3 wheel has SHA-256
`c6a7248a0eb88a5920c7f11f28e745d66dc42f8b442c0c680162d1481a8d5904`;
it contains one native extension, all 15 attribution members, no packaged
build/include/lib/share/bin tree, and NumPy as its sole unconditional
dependency. The extracted inspector is byte-identical across Git, source
archive, and wheel. A fresh external NumPy-only environment passes
`sceneio._wheel_smoke` plus explicit all-six
write/detect-or-explicit/inspect/lower-inspect/read/partial/path-release
coverage.

The package record uses two passes: the hashes above make the pre-final
inventory reproducible, then a no-further-edit rebuild repeats source/archive
identity, the derived wheel inventory, and the external NumPy-only smoke after
this documentation is staged. That final artifact evidence stays outside the
source tree; copying its hashes back into this file would change the exact
tree just verified.

Registry extraction checkpoint:

- [x] Add side-effect-free `_registry/families/splats.py` with one immutable
      six-codec tuple or a `build_splat_codecs(...)` factory. Inject the
      facade-owned SOG reader, writer, and point-reader callbacks so the
      existing archive/directory behavior and callable identities remain
      exact.
- [x] Move each `Codec(...)` definition mechanically and stage the complete
      tuple exactly once through
      `_define_builtin_family("splats", SPLAT_CODECS)`. Preserve canonical
      positions 2/3/4/5/14/49; aggregate finalization, not source order,
      restores the public 50-codec order.
- [x] Preserve the four direct mmap point-selector closures, SOG's exact
      facade-owned hybrid point-reader callable, and SPZ's deliberate lack of
      a selector. Preserve all mmap readers, file sinks, record/datatype
      identities, loss flags, container kind, and supported/unsupported
      feature tuples.
- [x] Preserve SOG path decisions exactly: an existing directory, direct
      `meta.json`, or suffixless output uses the directory adapter. Every
      other read path uses the archive adapter regardless of suffix, and every
      other output with a nonempty suffix uses the archive adapter.
- [x] Preserve PLY detection precedence and ownership in `_ply.py`; do not
      make Gaussian/compressed/mesh/point classification depend on the new
      family module's import or registration order.
- [x] Add the family source to the authoritative Codec AST scan. Prove exact
      tuple order, positions, Codec identities, ASTs, operation
      callables/closures, atomic staging, reload/idempotence, unchanged
      registry/capability/public snapshots, and no inline splat definitions in
      the facade.
- [x] Add one uniform all-six public path covering write, promised detection
      or explicit-format behavior, inspect, read, logical equality, and point
      selection where supported.
- [x] Add explicit retained-result/path-release cases after full reads for all
      six, after partial reads for the five selectors, and after inspection
      success/failure for all six. Exercise SOG archive, directory, and direct
      metadata entry paths.
- [x] Extend `_wheel_smoke.py` to execute all six formats. Retain the existing
      compressed PLY, SOG, and KSplat coverage; add Gaussian PLY, SPZ, and
      SPLAT write/detect/inspect/read probes, Gaussian/SPLAT partial probes,
      and an assertion that SPZ exposes no partial capability. Replace the
      three current repository-coverage exemptions with one all-six smoke
      helper.
- [x] Update import/assembly/ownership/collection/workflow contracts. The
      final I/O set may add exactly `_inspectors.splats` and
      `_registry.families.splats`, reaching 45 modules; the other two import
      boundaries remain exact.
- [x] Add the oracle-independent architecture suite as the mandatory all-six
      three-OS splat gate. Run the six codec parity suites in that job with
      the test-only oracles installed, and report their skips separately so an
      unavailable oracle is not described as codec coverage. Include the
      architecture suite in the manylinux2014/GCC-10 lane. Update the
      compiler-instrumented collection pin only from the final
      `pytest --collect-only` output.

Verification, validation, and evidence closure:

- [x] Run the six codec suites plus `test_io_mmap.py`, `test_io_partial.py`,
      capabilities, public E2E, registry/assembly/snapshot/import,
      repository-coverage, package, license, and documentation suites.
      Then run complete pytest and Ruff with `.venv/Scripts/python.exe`.
- [x] Differentially compare bytes and mmap decoding for all six; sink and
      buffer bytes for all six; complete and partial logical records for the
      five selectors; SOG archive and directory records; and valid/invalid
      inspector outcomes before and after extraction.
- [x] Repeat two
      `--runs 1 --scale 0.001 --skip-oracles` candidate captures. Require the
      exact all-50 and ordered six-row hashes above, then run the strict
      default-scale five-run guard.
- [x] Add an interleaved parent/candidate all-six comparator for read, write,
      inspect, and each supported point-range operation. Use 15 samples per
      operation and reject a candidate median increase larger than the maximum
      of 10 percent of the parent median, three times the combined median
      absolute deviation, or 0.05 ms. Keep every traced-allocation result
      within its parent bound. Investigate and review any rejection rather
      than averaging it away. Report accepted deltas as diagnostic evidence
      and claim no gain for this mechanical move.
- [x] Run generated large/cold-cache family diagnostics without committing
      their fixtures. Record the Windows cold-cache hint as unavailable when
      applicable rather than describing a warm-cache measurement as cold.
- [x] Run 15 interleaved exact-export parent/candidate samples for
      `import sceneio`, the I/O facade, and direct `_core`. Exact module sets
      are the contract; timings are diagnostic.

Registry candidate evidence: all six definitions now come from the
side-effect-free `build_splat_codecs(...)` factory and are staged once as one
family. The facade keeps the exact SOG callbacks; the parent Codec AST and
operation descriptors remain unchanged. The family/common matrix passes 444
tests with one documented SPZ-oracle skip, and the complete 3,309-node
collection passes 3,305 tests with four documented skips. Its sorted
normalized node-id SHA-256 is
`cd0a8c1a273dd87d72c9a08edf39d45f93b562295e8c3216e09b076b4dd65a43`.
Ruff is clean.

Both small captures reproduce all-50 SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered-splat SHA-256
`5c6adc3584ba25050c885b37313d009311e2253b0c841cbc8738b806cb090bfd`;
the strict five-run guard passes. Fifteen randomized interleaved
parent/candidate samples cover read, write, inspect, and each supported point
range. All 23 operation medians satisfy the planned bound, and candidate
maximum traced allocations equal the parent maxima for every operation.
The scale-1 six-format diagnostic uses 11.2 MiB logical clouds and files from
2.9 to 11.2 MiB; Windows reports the requested POSIX cache-eviction hint as
unavailable, so the readings are warm-cache diagnostics.

Fifteen randomized interleaved fresh-process import samples retain exact
seven-module `sceneio` and eight-module direct `_core` sets. The I/O facade
moves from 43 to 45 modules by adding only `_inspectors.splats` and
`_registry.families.splats`; parent/candidate medians are 5.230/4.452 ms,
75.253/69.788 ms, and 7.013/6.271 ms for the three boundaries. Timing is
diagnostic; exact module sets are the contract.

Pre-final package tree `7ab4f960dcb43ac95c4cf7269fed7d733bad71cc`
contains 326 tracked files. Its 327-file source archive adds only generated
`PKG-INFO`, has no missing or differing tracked blob, and has SHA-256
`47211c9a22d05e673265daaa99a813ac74ac1607116d3b5c9331d9accaf1e04c`.
The wheel derived only from that archive has 81 members and SHA-256
`b3cd1f1046297339c7fc88c0f89c66deb4e6a4cc78cc96bce9ce99565c06fb2a`.
It retains all 15 attribution members, one native extension, NumPy as its
sole unconditional dependency, no packaged build/include/lib/share/bin tree,
and only Python/standard Windows runtime native dependencies. The three
changed runtime files match across Git, archive, and wheel. A fresh external
environment containing only pip, NumPy, and this exact wheel passes the
complete installed smoke, including all six splat helpers and their declared
partial/lifetime/path-release behavior.

The architecture/correctness review verified inert family reload, failure
atomicity, live public-dictionary identity, canonical rebuild order, and
runtime-extension preservation. The test/performance review led to explicit
three-OS six-suite parity steps and an AST contract proving every splat smoke
helper is invoked once. The platform/package/documentation review is clear;
its inferred focused-matrix count change was withdrawn because it was not
measured. The final 69-test architecture/assembly matrix and complete
3,309-node suite pass after all findings.

The first hosted run of the new full parity lane found one previously
unexercised parent behavior: the large compressed-PLY PlayCanvas vector has a
distinct body hash on the characterized hosted macOS AppleClang/ARM profile.
Hosted Windows/MSVC and Ubuntu/glibc remain byte-identical to the pinned
PlayCanvas body. Native exp/log rounding is the inferred cause consistent
with the one changed lossy quantization boundary, not a universal platform
claim. The corrected parity contract pins both parent fingerprints and
retains the independent NumPy layout/decode oracle; no codec source or output
changed.

- [x] Freeze a zero-unstaged tree, export it with `core.autocrlf=false`, build
      the source archive from that tree, and build the wheel only from the
      exact archive. Compare every Git blob and all changed packaged runtime
      files byte-for-byte across Git, archive, and wheel.
- [x] Measure the final artifact inventory rather than forcing an estimate.
      Verify the complete existing license/attribution set, one native
      extension, no packaged build/include/lib/share/bin tree, NumPy as the
      sole unconditional dependency, unchanged shared-library dependencies,
      and no FFmpeg/libav code, linkage, process invocation, runtime member,
      or attribution.
- [x] Install the exact wheel outside the repository with only NumPy and run
      the complete installed smoke, including all six splat formats,
      detection, inspection, reads, supported partial reads, retained-result
      lifetime, and path release.
- [x] Obtain separate architecture/correctness, test/performance, and
      platform/package/documentation reviews for each implementation
      checkpoint. Resolve every finding before its commit.
- [x] Commit and push only green, Ruff-clean units with the required co-author
      trailer. Require green normal and compiler-instrumented hosted runs for
      the exact final implementation tree.
- [x] Update `core_architecture.md`, `repository_organization_plan.md`,
      `format_coverage.md`, this checklist, and `bench/BASELINE.md` with exact
      final line counts, collection/import counts, benchmark hashes, artifact
      inventories, commit ids, and workflow ids. Update the roadmap only if
      its active status changes.
- [x] Do not trigger `publish.yml`, create a tag, or publish a package. The
      cross-platform wheel dry run remains user-triggered. After this evidence
      closure, mark R2 complete and begin R3.1a.

R2 closes at registry implementation `3e46d82` plus the unchanged-codec
platform-contract repair `9928c6d`. Exact repair tree
`79819558208fdb8099b23d3c38fd1afee3ee2f7c` repeats the measured
326/327/81 Git/source/wheel inventory and external installed smoke. Normal
run `30228235491` passes the full suite, retained performance guard, all three
splat jobs, mmap/reconstruction matrices, and GCC-10 lane.
Compiler-instrumented run `30228235535` passes both jobs. `publish.yml` was
not triggered; no tag or package was published. R3.1a is complete in the
current tree. R3.1b closes at `0bdfe0f`; normal run `30234796010` and
compiler-instrumented run `30234796025` pass. R3.2 is active.

## 7. R3 — split benchmark and cross-codec tests

### R3.1a — mechanical benchmark model/measurement/reporting split

- [x] Extract data models, timing, traced allocation, the existing warmed
      parent-process RSS sampler, and reporting without changing behavior.
- [x] Pin JSON output schema and representative fixture hashes.
- [x] Compare old/new output from the same commit and fixture seed.
- [x] Preserve the existing metric under an explicit `in_process_rss` name;
      do not relabel it as fresh-process evidence.

R3.1a leaves the family sweep orchestration in the compatible facade. Moving
that function before its family builders and oracles have lower ownership
would introduce a reverse dependency back into the facade. R3.2 moves those
dependencies first and then moves the remaining sweep into
`io_bench/runner.py`. This staging keeps each commit mechanical while still
ending R3 with a thin CLI facade.

R3.1a evidence:

- parent commit/tree/blob are
  `683ae483a3a2407dc192fb32cdcf964eb3b1fe9a` /
  `5dfe9bbd36940bfa4b03a322a2b452b38d3f463e` /
  `bcb502936cc8ccce4a52b843a1220f27cdddba1f`;
- the checked benchmark contract records the exact capture command, parent
  JSON SHA-256, both candidate JSON SHA-256 values, and common structural
  projection
  `2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`;
- the parent and candidate fixture-builder AST projection is identical, and
  eight record-aware fixture fingerprints cover arrays plus semantic metadata,
  mesh topology, camera conventions, and reconstruction structure;
- a checked deterministic reporting transcript covers ordinary, typed,
  encoding-variant, COLMAP database, directory, error, O3/O4/O5, notice, and
  JSON output;
- the first exact five-run complete guard rejected only a noisy LAS read
  comparator. A seven-run LAS diagnostic measured 1.41x, the complete
  no-oracle repeat passed, and an unchanged complete confirming command passed
  with LAS read at 2,882 versus 2,178 MB/s (1.32x). The confirming JSON
  SHA-256 is
  `b426086aaf02483d4a36bb4e4297fba4c7ac85b8786d849cd4de3ff07726dc3b`;
- direct execution, module execution, synthetic importlib loading, and
  canonical `bench.bench_io` loading work from outside the checkout; repeated
  loads do not duplicate the repository root in `sys.path`;
- local MSVC collects 3,309 nodes, passes 3,305 with the same four documented
  skips, and passes Ruff plus the focused documentation/architecture suites;
- exact-commit normal run
  [30231629465](https://github.com/SceneAPI/SceneIO/actions/runs/30231629465)
  passes the complete suite, 50-codec smoke, retained performance guard,
  three-platform splat/mmap/reconstruction jobs, and GCC-10 lane. Exact-commit
  compiler-instrumented run
  [30231629496](https://github.com/SceneAPI/SceneIO/actions/runs/30231629496)
  passes its complete and lifetime jobs.

### R3.1b — qualification-grade memory protocol

- [x] Add a child-process protocol that imports and warms SceneIO, records its
      baseline, performs exactly one measured operation, and reports peak and
      delta RSS.
- [x] Repeat across payload sizes and samples; report baseline, delta, payload
      size, platform, and sampler availability.
- [x] Make `psutil` mandatory in strict qualification mode. Missing RSS
      support is `unavailable` and fails qualification; it is never numeric
      zero.
- [x] Keep throughput timing outside tracemalloc and memory sampling.
- [x] Add fixtures proving a bounded operation passes and an intentional
      full-payload allocation fails.

`bench/io_bench/memory_protocol.py` now owns the parent API, versioned result
model, strict/unavailable behavior, repeated size/sample matrix, and
payload-growth assessment. Each sample launches
`bench.io_bench.memory_child`, imports SceneIO, performs one explicit warm-up,
collects a post-warm baseline, aligns retained current RSS with the platform
high-water mark, starts the 0.5 ms `psutil` sampler, confirms its first sample,
and performs exactly one measured operation. Warm-up payload size is fixed at
zero. The result includes current-RSS and platform-high-water
baselines/peaks/deltas, calibration/headroom, platform and sampler metadata,
and canonical warm/measured operation signatures. Strict qualification needs
at least three samples per size, requires zero residual high-water headroom,
binds every echoed field to the request, and compares every larger size with
the smallest. The checked `memory_protocol_v1.json` contract rejects a
numeric RSS value for an unavailable sampler, accepts only the three declared
platform high-water backends, derives residual headroom from the reported
baseline counters, and requires the lifetime value to envelope every observed
current-RSS sample. The sampler stops before the final envelope is captured
while measured and calibration values remain alive. Instrumented runtimes are
explicitly unavailable for this RSS protocol and continue to exercise the
ordinary codec suite separately.

The generated control corpus uses 8 MiB and 48 MiB sparse files with three
fresh children per size. A 64 KiB bounded read reports median deltas of
208,896 and 192,512 bytes and passes with zero measured growth. The
full-payload control reports 8,523,776 and 50,462,720 bytes, measures
41,938,944 bytes of growth, and fails the 10 MiB bound. Raw control evidence
is development output, not committed fixture data. A mutation-sensitive unit
test proves that the bounded operation returns the requested 64 KiB; semantic
operation signatures reject mismatched formats, selectors, read extents, or
allocation controls. Existing codec-test-local child snippets remain
unchanged until their consumer-by-consumer R3.3 migration; the benchmark
protocol is already independently exercised with real NPY read and inspect
operations. The protocol test is included in the existing Linux, Windows, and
macOS mmap/partial CI lane.

R3.1b local exit evidence:

- exact collection is 3,320 nodes with sorted normalized SHA-256
  `b055375c118a024858d42b9111649d95587d51ad79c089f2ec492fc84edf4dfb`;
  the complete MSVC run passes 3,316 with the same four documented skips;
- the unchanged complete five-run O4/O5 and mmap/sink guard passes. Its JSON
  SHA-256 is
  `a8c5366a999cbe90b7f29ca7f6face5584612cb021708b99644496ceb08951bc`;
  XYZ write is 4.87x, LAS read/write are 2.23x/2.07x, and both WebP
  comparators remain positive;
- all three independent reviews are clear after replaying mismatched
  operations, request echoes, fabricated sampler backends, hidden high-water
  headroom, insufficient samples, intermediate-size spikes, and a no-op
  bounded read;
- the exact working-tree source archive has 337 file members: 336 are
  byte-identical repository files and one is generated `PKG-INFO`. Its derived
  Windows abi3 wheel has 81 members, one native module, 15 attribution files,
  no benchmark/test/build content, and NumPy as its sole unconditional
  dependency. A fresh environment containing only the wheel and NumPy passes
  `python -m sceneio._wheel_smoke`;
- Ruff, documentation consistency, JSON/YAML parsing, and `git diff --check`
  pass. No release workflow, tag, or publication action was triggered.

The first exact hosted attempt, `aafd283`, exposed a Linux accounting boundary:
`/proc` current RSS can briefly exceed `ru_maxrss`, and the sampler could
record one final current value after the native lifetime counter was captured.
Normal run `30234117571` therefore rejected two incoherent child responses;
compiler-instrumented run `30234117580` passes. The follow-up takes a monotonic
envelope of the native counter and observed current values only after sampler
shutdown. Deterministic controls reproduce both the low-native-counter case
and a higher sample arriving during `join()`. The full 3,316-test local suite,
Ruff, all three reviews, and the 11-test protocol suite in the pinned
manylinux2014 GCC-10 image pass. Follow-up commit `0bdfe0f` closes R3.1b:
normal run
[30234796010](https://github.com/SceneAPI/SceneIO/actions/runs/30234796010)
passes the complete suite, benchmark smoke/structure/performance guard,
GCC-10 build, and all platform lanes; compiler-instrumented run
[30234796025](https://github.com/SceneAPI/SceneIO/actions/runs/30234796025)
passes both jobs. No release workflow, tag, or publication was triggered.

### R3.2 — family fixtures, oracles, and sweep runner

- [ ] Move builders/oracles one family at a time:
  - [x] arrays;
  - [x] calibration;
  - [ ] images;
  - [ ] meshes;
  - [ ] points;
  - [ ] reconstruction;
  - [ ] sequences;
  - [ ] splats.
- [ ] After the family hooks have lower ownership, move the remaining complete
      sweep orchestration to `bench/io_bench/runner.py`; keep
      `bench/bench_io.py` as a thin compatible CLI and helper-export facade.
- [ ] Keep oracle dependencies test-only.
- [ ] Fail if a built-in codec is silently absent; prove an extra runtime
      registration does not enter repository fixture/oracle completeness.
- [ ] Add a strict qualification mode in which every declared oracle must be
      installed and runnable; optional `_try(...)` behavior is allowed only
      for developer smoke runs.
- [ ] When no library oracle exists, require an independent spec-level parser
      or a reviewed exemption with the exact unverified property recorded.
- [ ] Keep generated 100 MiB-class fixtures out of Git.

The arrays checkpoint moves all six array `Spec` builders and their
deterministic fixtures behind `io_bench/families/arrays.py`, with the DMB
fixture and NumPy/NPZ/DMB independent oracles under
`io_bench/{fixtures,oracles}/arrays.py`. Optional safetensors bindings have the
same lower owner. `bench_io.py` continues to export the same private helpers
for compatibility and now splices the complete family hook into the unchanged
result order. The checked benchmark contract maps representative builders to
their owning source files, pins AST hashes for every lower function, and pins
facade identity for every compatibility export. Direct execution controls
cover NumPy, NPZ, DMB, and all five safetensors buffer/file/open bindings when
installed; PFM and FLO record the exact independent benchmark comparison they
do not provide.
The one-run 50-codec smoke retains the exact structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused array/parity/compatibility validation passes 334 tests with one
documented optional OpenCV skip. Adding the typed PFM/FLO suites expands that
run to 445 passes with the same skip. The complete suite passes 3,316 tests
with the same four documented skips, and Ruff is clean. A fresh exact-tree
source archive has 343 members and contains all six new benchmark
family/fixture/oracle modules without generated cache files. Its derived
81-member wheel contains no benchmark, test, or safetensors module, retains
all 15 attribution files, and keeps `numpy>=1.26` as its sole unconditional
dependency.

Exact arrays commit `6d9ec34` passes normal run
[30236069971](https://github.com/SceneAPI/SceneIO/actions/runs/30236069971)
and compiler-instrumented run
[30236069959](https://github.com/SceneAPI/SceneIO/actions/runs/30236069959).

The calibration checkpoint moves the complete `opencv_yaml`, `opencv_xml`,
`ros_camera_info`, and `kalibr` hook to
`io_bench/families/calibration.py`; both rig fixtures move to
`fixtures/calibration.py`, and the PyYAML/XML comparisons move to
`oracles/calibration.py`. The unchanged `_record_nbytes` helper moves once to
`families/common.py` for calibration and the later pose/reconstruction hooks.
The facade keeps exact compatibility aliases and splices the four specs at
their original position. All seven moved helper ASTs match the parent.
Contract controls pin exact `make`, `w`, `r`, `ow`, `orr`, and logical-size
behavior, execute the installed PyYAML/XML pairs through the actual specs,
and prove in a fresh process that absent PyYAML removes only the three YAML
pairs. Lower modules do not load the facade. The four-codec live benchmark
produces non-null oracle metrics for every row, and the complete 50-codec
smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused calibration/contract validation passes 117 tests; the complete suite
passes 3,316 with the same four documented skips, Ruff is clean, and the
three independent reviews are clear. A fresh
347-member exact-tree source archive contains exactly the four new
calibration/common benchmark modules and no generated cache files. Its
81-member derived wheel contains no benchmark, test, or YAML module, retains
all 15 attribution files, and keeps `numpy>=1.26` as its sole unconditional
dependency; `pyyaml>=6.0` remains test-extra only. A fresh environment with
that wheel and NumPy, but without PyYAML, passes
`python -m sceneio._wheel_smoke`.

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

- [x] R3.1a one-run all-codec smoke produces the same codec set and JSON
      fields.
- [x] R3.1a five-run O4/O5 controls retain direction and memory relationships
      after the required confirming complete run.
- [x] R3.1b protocol coverage is wired into the existing Linux, Windows, and
      macOS mmap/partial lane; exact-commit normal run `30234796010` and
      compiler-instrumented run `30234796025` pass.
- [ ] Strict qualification mode fails on an absent required oracle or RSS
      sampler instead of silently dropping evidence.
- [ ] Full suite and Ruff pass after each family.
- [x] `bench/bench_io.py` remains the compatible CLI entry point through
      R3.1a; repeat this gate after every remaining R3 unit.

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
