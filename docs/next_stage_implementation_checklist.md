# Next-stage implementation checklist

## Post-R6 APNG checkpoint (2026-07-29)

- [x] Add a repository-owned APNG chunk/state layer over pinned lodepng with
      uint8 RGB/RGBA composited frames, exact accepted-profile timing, loop
      count, source/over blend, and none/background/previous disposal.
- [x] Add mmap input, direct sinks, metadata-only inspection, `.png`/`.apng`
      routing, installed-surface smoke, and cross-codec transport coverage.
- [x] Validate SceneIO writes with Pillow and SceneIO reads with both Pillow
      output and a separate specification-derived chunk/compositing oracle.
- [x] Expand the live registry to 56 codecs and the buffer-backed differential,
      mmap, sink, and inspection sweeps to 50.
- [x] Record the focused benchmark and the 56-row structural capture:
      `2295f9ab10dbf141c76ef6f7cbf4561ad656a1dde3cc7c8dcbff8b5bc23d6927`.
- [x] Record the complete local suite, Ruff, and installed-surface smoke for
      the final APNG tree: 3,905 passed, five documented skips, Ruff clean,
      `_wheel_smoke` returned `2`, and the 56-row structure check passed.
- [ ] Obtain normal and build-only cross-platform results for the reviewed
      branch head before calling APNG package-validated.
- [ ] Implement RTMV next, reusing canonical `Mask`, `CameraRig`, track,
      `PairCorrespondences`, `FeatureSet`, and `MatchGraph` models.
- [x] Implement HDF5/hloc ahead of RTMV by mapping hloc feature and match
      groups directly into `FeatureSet` and `MatchGraph`; no duplicate models
      were added.

## Post-R6 animated WebP checkpoint (2026-07-29)

- [x] Add packed uint8/uint16/float32 `ImageSequence` storage with parent-pinned
      read-only views and explicit timing, loop, background, and max-value
      metadata.
- [x] Add repository-pinned libwebp animated read/write, mmap input, direct
      sink, metadata-only inspection, still-versus-animated detection, and
      independent Pillow cross-read/write tests.
- [x] Expand the live registry to 55 codecs and the buffer-backed differential,
      mmap, sink, and inspection sweeps to 49.
- [x] Record the local 55-row structural capture and focused animated-WebP
      benchmark in `bench/BASELINE.md`.
- [x] Record the final complete local suite and lint result for this exact
      tree: 3,895 passed, five documented skips, Ruff clean, installed-surface
      smoke passed, and the 55-row structural capture matched.
- [ ] Obtain normal and build-only cross-platform results for the reviewed
      branch head before calling animated WebP package-validated.
- [x] Implement APNG next, then RTMV. Reuse the canonical `Mask`,
      `CameraRig`, track, pair, feature, and match models rather than creating
      format-specific duplicates.

This checkpoint resumes the format queue after the completed R6 organization
stage. It does not alter the historical R6 scope statements and evidence below.

> **Stable-ABI evidence correction (2026-07-28):** references below to local
> Windows “abi3 wheels” before the R6 closure record the wheel filename/tag,
> package inventory, and Python 3.12 smoke result. They do not prove that the
> embedded extension used Python’s stable ABI. The R6 review found that CMake
> requested only `Development.Module`, allowing nanobind to fall back to a
> CPython-specific binary. Those older artifacts remain valid for their source,
> codec, inventory, and Python 3.12 results but are superseded as ABI evidence.
> The corrected build requires `Python::SABIModule`, checks the selected
> nanobind target and suffix during configuration, and separately verifies the
> resulting Windows `_core.pyd` and Unix `_core.abi3.so`.

## Lean R6 closure decision (2026-07-28)

This section is the active closure policy and supersedes later historical
language that makes exhaustive alternative-backend qualification a prerequisite
for R6. The goal is to close the verified stable tier, not to prove that every
codec/profile/direction is globally fastest.

The current backends are accepted as the R6 release baseline because their
format parity, public-path behavior, retained performance guard, package
inventory, and local installed-wheel smoke pass. The 124 `provisional`
operation rows remain honest optimization-backlog entries; this batch
acceptance does not relabel them `qualified`, erase their evidence gaps, or
claim that every possible replacement was measured. The two JPEG `known_gap`
rows remain explained by the completed, rejected libjpeg-turbo comparison.
The 14 specialized rows without a profile-specific current-backend measurement
are accepted for correctness and compatibility only; R6 makes no performance
claim for those profiles, and they are first in the trigger-based backlog.

The bounded path to full R6 closure is:

- [x] Finish N0-R4 organization, the bounded R5 candidate decision, R6 source
      intake, local stable-ABI package proof, complete local suite, strict
      50-codec guard, NumPy-only smoke, and three independent reviews.
- [x] Finish the single Windows packaging correction exposed by the build-only
      matrix: repair from the Visual Studio redistributable directory, retain
      the original runtime filename and bytes, include the required notices,
      and prove the repaired wheel installs and passes the existing smoke test.
- [x] Run the focused and complete local gates plus the required three-lens
      review, then commit and push one implementation checkpoint. Require green
      automatic CI and native-runtime validation at that exact commit.
- [x] Dispatch `publish.yml` once more at that reviewed branch head. The manual
      run is build-only and cannot publish.
- [x] Download and inspect its one sdist and three abi3 wheels. Require the
      existing inventory, license, stable-ABI, NumPy-only, native-dependency,
      and all-50 installed-smoke checks to pass.
- [x] Record the workflow URL and artifact hashes, run the focused
      documentation/ledger contracts, obtain one final three-lens review, and
      commit the documentation-only closure record. Record both the packaged
      source SHA and the closure-record SHA.

Closure is deliberately bounded:

- do not start another backend search, new codec, benchmark expansion, release
  tag, or package publication before R6 closes;
- candidate comparisons resume only after R6 when a measured regression,
  material hotspot, or concrete replacement proposal justifies one;
- from this checkpoint, permit one final build-only matrix plus at most one
  retry for a documented hosted-run interruption;
- if that matrix exposes another reproducible product defect, make at most one
  narrowly scoped packaging fix and one confirming exact-head run; if it still
  fails, record the concrete blocker and stop rather than opening another
  workstream;
- the documentation-only closure record does not invalidate or recursively
  repeat the package matrix for the recorded packaged source SHA;
- PyPI configuration, tagging, and publication are release-time actions, not
  R6 validation gates.

The five items above pass. R6 and this repository-organization stage are
complete. The remaining provisional ledger rows continue as an optional,
prioritized optimization backlog. This is a hard stop: no post-R6 backlog item
is pulled into the closure path.

### R6 closure evidence

The packaged source is exact commit
`105b3017dae37345a6974f289e661d9173186a2a`. Automatic
[CI run 30405666674](https://github.com/SceneAPI/SceneIO/actions/runs/30405666674)
and
[native-runtime run 30405666673](https://github.com/SceneAPI/SceneIO/actions/runs/30405666673)
pass at that commit. Build-only
[release run 30406706115](https://github.com/SceneAPI/SceneIO/actions/runs/30406706115)
then builds one exact source distribution and three wheels from it; its combined
inventory passes and its PyPI job is skipped.

| Artifact | Verified result |
|---|---|
| Source distribution | 834 exact source files plus generated `PKG-INFO`; 835 members; 24 license assets; source-tree SHA-256 `3e353c2b6cd14d044bc71a0280091ab0f6396e2c649262061e26c015049ffcf4`; archive SHA-256 `cf8673ec3db22a8fa5d6bd13e23b5ce132680204c8d1f2e3c2e22874f61d410d` |
| macOS AppleClang arm64 | `sceneio-0.2.0-cp312-abi3-macosx_11_0_arm64.whl`; 90 members; SHA-256 `30bcb3799fe45f60c055d11e95ef2c41c9d188c779391f629a508dc709da1e8c` |
| manylinux2014 GCC 10 x86-64 | `sceneio-0.2.0-cp312-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`; 90 members; SHA-256 `b13edb065fa3260656cadeac0a792ee7dc7d86fd4293373c57d7ec889fa69266` |
| Windows MSVC amd64 | `sceneio-0.2.0-cp312-abi3-win_amd64.whl`; 92 members; SHA-256 `0107fe62e4e3b7f7732b234eb0b8923c396d2f924b8acefeec4e05047c37d17d` |

Every wheel has all 24 notices, 62 Python runtime files, and
`numpy>=1.26` as its sole Python runtime requirement. Each hosted wheel job
passes strict stable-ABI inspection and the installed all-50-codec smoke.
macOS and manylinux contain only `_core.abi3.so` as native payload. Windows
contains `_core.pyd` plus unmodified `sceneio.libs/msvcp140.dll`; the hosted
repair selects Visual Studio 2022 Enterprise VC143
`14.44.35112/x64/Microsoft.VC143.CRT`, and both the hosted log and an
independent downloaded-artifact check record the DLL SHA-256 as
`0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9`.
The source and build configuration contain no FFmpeg/libav implementation or
dependency.

The documentation-only commit containing this section is the closure-record
commit; its SHA is reported by Git after creation rather than embedded
recursively. No tag, release, or package publication is part of this closure.

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
compiler-instrumented run `30234796025` pass. R3.2 closes at `0e54cf5`;
normal run `30263506366` and compiler-instrumented run `30263506270` pass.
R3.3 is complete and pushed at `811cb0d`. Its normal run `30300122309` and
compiler-instrumented run `30300122324` pass. R3.4 is complete and pushed at
`9ca6bb8`; normal run `30305201847` and compiler-instrumented run
`30305201756` pass that exact checkpoint. Its installed-wheel smoke is driven
by the exact 50 built-in definitions, exercises public write/read/inspect,
pairs successful public path calls with both declared stream-capability
directions, and exercises all 32 selectors across 28 partial-capable codecs
without an operation exemption. R4.1 is complete and pushed at `b2cf5d4`. Its
3,352-node local gate passes 3,348 tests with four documented skips; Ruff, the
strict five-run guard, exact-tree package qualification, fresh NumPy-only
installed smoke, and three independent reviews pass. Normal run `30310780347`
and compiler-instrumented run `30310780355` pass that exact commit.

R4.2 is complete and pushed at `81e0e1c`. Ten family/assembly translation
units plus one descriptor header own the 16 record and 40 codec registration
functions. The private
`_core.__codec_inventory__` projects all 49 native/hybrid built-ins from those
family tables; the Python-owned `image_sequence` adapter remains separately
validated. MSVC and manylinux2014 GCC 10.2.1 builds, a 416-test I/O and
architecture sweep, exact 3,354-node collection, and the unchanged strict
five-run guard pass. The complete suite passes 3,350 tests with four documented
skips, and Ruff is clean. A 398-file staged tree produces a 399-file sdist with
only `PKG-INFO` generated and an 81-member Windows ABI3 wheel with one native
module, all 15 notices, no excluded build payload, and NumPy as the sole
unconditional dependency. The complete smoke returns `2` in a fresh
SceneIO-plus-NumPy environment. All three independent reviews are clear after
their findings were resolved. Normal run `30316577366` and
compiler-instrumented run `30316577369` pass that exact commit.

R4.3 and final R4 qualification close at pushed commit `da1d709`. All 40
native codec sources now live under the eight family directories, with no flat
codec source left. Every executable body is unchanged by the moves; only
pre-existing source-location comments follow their new paths. MSVC and
manylinux2014 GCC 10.2.1 builds, the complete 3,354-node suite (3,350
passed/four skipped), Ruff, the 232-name/49-entry native surface, the complete
five-run strict all-50-codec guard, and 319 public/API/architecture/license
checks pass. The exact 398-file Git tree produces a blob-identical 399-file
sdist and an unchanged-layout 81-member Windows ABI3 wheel; fresh
SceneIO-plus-NumPy smoke returns `2`. All three independent reviews are clear.
Normal run `30326256230` and instrumented run `30326256137` pass exact commit
`da1d709`.

R5.1 is complete and pushed at `cf208d8`. The R5.2 harness is pushed at
`bd68dc2`, and managed-Python worker identity/cleanup closes at `7a88e7c`.
The exact `7a88e7c` clean-wheel, remote-inclusive MSVC report is complete:
1,596 of 1,597 frozen gates pass, but libjpeg-turbo 3.2.0 misses the
`rgb8_q95_444` comparative-quality floor (`-0.058242 dB` observed versus
`-0.05 dB` required). Its report SHA-256 is
`f32b7c60f19956438023c51cc9c0b07f44ace79c66dff4a43c30fc7cfdcd80b1`.
The candidate is therefore rejected as the combined stable JPEG default,
stb remains unchanged, and the user-gated GCC 10/AppleClang comparison was not
  dispatched for a candidate that had already failed a frozen local gate. R5 has
  a negative selection result. All six R6 source-intake units are complete and
  pushed. The clean `8ef2537` run proves disconnected source construction,
  package inventory, 22-license inclusion, and all-50 Python 3.12 smoke, but
  its wheel is withdrawn as stable-ABI evidence by the correction above. The
  corrected CMake build now selects and verifies nanobind’s stable-ABI target
  on Windows and Ubuntu. `publish.yml` makes its three wheel jobs
  verify and unpack one sdist, use a hash-locked build wheelhouse, and run the
  same inventory/smoke gates. Final build-only run `30406706115` rebuilds the
  corrected exact-tree package on MSVC, GCC 10, and AppleClang; its inspected
  artifact hashes are retained in the closure record.

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
- at this checklist's initial snapshot, six default native dependencies still
  arrived through CMake `FetchContent`; the live R6 ledger below supersedes
  that historical count;
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
- benchmark mature permissive upstream backends before selecting a replacement
  kernel; retain the verified current R6 baseline without an exhaustive search;
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
  -> R5 bounded measured candidate decision
  -> R6 selected-source closure
  -> one exact-head package matrix and closure review
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

- [x] Move one family's built-in `Codec` definitions without changing values
      or canonical ordering.
- [x] Keep family exports immutable and side-effect free; only the aggregate
      populates the existing `REGISTRY` object.
- [x] Compare serialized capability snapshots byte-for-byte.
- [x] Run family parity, public E2E, detection, mmap/sink, inspection, partial,
      and capability tests.

### R2.3 — move family inspectors

- [x] Keep `_inspection.py` as a compatibility facade.
- [x] Move common parsing helpers only after two families use the same
      invariant; avoid a new miscellaneous helper module.
- [x] Prove inspect/full agreement, malformed errors, bounded allocation, and
      no full decode.

### R2.4 — per-family exit

- [x] Full suite and Ruff pass.
- [x] Benchmark smoke and retained guards pass.
- [x] Import/startup and public symbols show no regression.
- [x] Diff is a behavior-preserving move plus focused architecture tests.

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
The parent SOG writer had two deterministic profiles: Windows/MSVC and
macOS/AppleClang serialized one adjacent `std::log1p` result differently from
hosted glibc and pinned GCC 10. That historical evidence remains attached to
run `30220612832`. The C3/C4 CI correction supersedes that writer behavior
with a repository-contained, pinned musl/fdlibm-derived transform. The active
contract now requires one exact archive, metadata hash, and hexadecimal bound
on all four profiles. MSVC and GCC agree across five million deterministic
float32 inputs and the complete local Windows/Ubuntu SOG suites; the former
counterexample and tiny relative ranges have dedicated assertions. Final
hosted AppleClang and GCC-10 confirmation remains in the exact-head gate.

The same run exposed three decoded-only parent variants while their encoded
bytes remained exact: KSplat and SPLAT scales differ by at most one float32
ULP through platform `logf`, and SPZ v3/v4 quaternions differ by at most one
float32 ULP on AppleClang/ARM through floating-point contraction. The contract
therefore keeps unaffected fields bit-exact, applies a maximum-one-ULP check
only to those named arrays, and retains exact whole-record fingerprints for
all four build profiles. Those decoded-only tolerances are unchanged; only
the SOG metadata writer is now canonicalized.
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
compiler-instrumented run `30234796025` pass. R3.2 later closes at
`0e54cf5`; R3.3 closes at `811cb0d`, and R3.4 is implemented locally.

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

- [x] Move builders/oracles one family at a time:
  - [x] arrays;
  - [x] calibration;
  - [x] images;
  - [x] meshes;
  - [x] points;
  - [x] reconstruction;
  - [x] sequences;
  - [x] splats.
- [x] After the family hooks have lower ownership, move the remaining complete
      sweep orchestration to `bench/io_bench/runner.py`; keep
      `bench/bench_io.py` as a thin compatible CLI and helper-export facade.
- [x] Keep oracle dependencies test-only.
- [x] Fail if a built-in codec is silently absent; prove an extra runtime
      registration does not enter repository fixture/oracle completeness.
- [x] Add a strict qualification mode in which every declared oracle must be
      installed and runnable; optional `_try(...)` behavior is allowed only
      for developer smoke runs.
- [x] When no library oracle exists, require an independent spec-level parser
      or a reviewed exemption with the exact unverified property recorded.
- [x] Keep generated 100 MiB-class fixtures out of Git.

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

Exact calibration commit `5dc03f4` passes normal run
[30237676629](https://github.com/SceneAPI/SceneIO/actions/runs/30237676629)
and compiler-instrumented run
[30237676648](https://github.com/SceneAPI/SceneIO/actions/runs/30237676648).

The raster-image checkpoint moves all eight `png`, `jpeg`, `bmp`, `tga`,
`webp`, `hdr`, `exr`, and `netpbm` specs to
`io_bench/families/images.py`; unchanged uint8/float32 fixtures move to
`fixtures/images.py`, and optional Pillow/imageio/OpenEXR comparisons move to
`oracles/images.py`. The facade keeps exact compatibility identities and
splices the hook around the unchanged interleaved `y4m` row. All nine moved
helper ASTs match the parent. Installed, absent, and fallback controls cover
every optional provider, and real oracle writer-to-reader pairs execute for
every available non-HDR row. Packed and planar EXR results are normalized to
RGB and compared exactly for oracle- and core-produced bytes. Portable
independent Radiance HDR benchmark encode/decode throughput is a reviewed
exemption in this environment; the NumPy RGBE parser/serializer in
`tests/codecs/test_hdr.py` continues to provide independent format parity.

Seven of eight live image rows have non-null independent metrics, and the
complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused raster/contract validation passes 352 tests; the complete suite passes
3,316 with the same four documented skips, Ruff is clean, and all three
independent reviews are clear. The fresh exact-tree source archive has 350
members and exactly the three new image modules without generated caches. Its
81-member wheel excludes benchmark/test/Pillow/imageio/OpenEXR modules,
retains all 15 attribution files, and keeps NumPy as the sole unconditional
dependency; those comparison libraries remain test-extra only. A fresh
NumPy-only environment without them passes the installed-wheel smoke.

Exact raster-image commit `6572a76` passes normal run
[30239455960](https://github.com/SceneAPI/SceneIO/actions/runs/30239455960)
and compiler-instrumented run
[30239455952](https://github.com/SceneAPI/SceneIO/actions/runs/30239455952).

The mesh checkpoint moves the five buffer-backed `ply_mesh`, `obj`, `stl`,
`off`, and `glb` specs to `io_bench/families/meshes.py`. Five unchanged
mesh/scene fixtures move to `fixtures/meshes.py`; 12 optional trimesh
comparison helpers, including the multi-file glTF pair, move to
`oracles/meshes.py`. The specialized `gltf` row remains in
`bench_io.py::_benchmark_gltf` pending the final runner extraction and consumes
the lower helpers through exact compatibility aliases. All 17 moved helper
ASTs and all five standard `Spec` ASTs match the raster checkpoint.

Contract controls pin core callbacks, payload sizes, lower/facade identities,
installed and absent trimesh behavior, and unchanged result placement. They
execute real trimesh writer-to-reader and core-to-trimesh paths for the five
standard rows and specialized glTF, canonicalize transformed scene triangles,
and compare positions/connectivity within `1e-6`. All six live rows have
non-null independent metrics. The complete 50-codec smoke retains structural
projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused mesh/contract validation passes 336 tests; the complete suite passes
3,316 with the same four documented skips, and Ruff is clean. The fresh
exact-tree source archive has 353 members and exactly the three new mesh
modules without generated caches. Its 81-member wheel excludes
benchmark/test/trimesh/pygltflib modules, retains all 15 attribution files,
and keeps NumPy as the sole unconditional dependency; trimesh and pygltflib
remain test-extra only. A fresh NumPy-only environment without them passes the
installed-wheel smoke.

Exact mesh commit `613fd26` passes normal run
[30241711640](https://github.com/SceneAPI/SceneIO/actions/runs/30241711640)
and compiler-instrumented run
[30241711620](https://github.com/SceneAPI/SceneIO/actions/runs/30241711620).

The point checkpoint moves the non-contiguous `xyz`, `pts`, point `ply`,
`pcd`, `las`, and `laz` specs to `io_bench/families/points.py`. Three
unchanged deterministic fixtures move to `fixtures/points.py`, and nine PTS,
Open3D, and LASpy comparison helpers move to `oracles/points.py`. The facade
retains exact compatibility identities and slices the hook around the five
mesh specs. The 11 unaffected moved helper ASTs and five unaffected standard
`Spec` ASTs match the mesh checkpoint. Review found and repaired the historical
LAS comparison's unequal payloads: LASpy previously encoded XYZ-only point
format 0 while SceneIO encoded point format 2 with RGB and intensity. LAS and
LAZ now use the same point-format-2 payload on both sides and retain one
positions-equivalent throughput denominator.

Contract controls pin callbacks, scale arguments, logical sizes, lower/facade
identities, installed providers, each provider absent independently, and
real oracle writer-to-reader plus core-to-reader execution. PTS arrays compare
exactly; PLY/PCD geometry and attributes compare within `1e-6`; LAS/LAZ
positions compare within half the declared `0.001` scale while RGB and
intensity remain exact. Five of six live rows have non-null independent
metrics. XYZ explicitly exempts only independent benchmark encode/decode
throughput; the independent NumPy parser and serializer in
`tests/codecs/test_xyz.py` retain format parity.

The complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused point/contract validation passes 449 tests; the complete suite passes
3,316 with the same four documented skips, Ruff is clean, and all three
independent reviews are clear. The fresh exact-tree source archive has 356
members and exactly the three new point modules without generated caches. Its
81-member wheel excludes benchmark/test/Open3D/LASpy/LAZ-backend modules,
retains all 15 attribution files, and keeps NumPy as the sole unconditional
dependency; those comparison packages remain test-extra only. A fresh
NumPy-only environment without them passes the installed-wheel smoke.

Exact point commit `45e2757` passes normal run
[30244892746](https://github.com/SceneAPI/SceneIO/actions/runs/30244892746)
and compiler-instrumented run
[30244892600](https://github.com/SceneAPI/SceneIO/actions/runs/30244892600).

The reconstruction checkpoint moves the nine buffer-backed
`transforms_json`, `tum`, `kitti`, `euroc_state`, `g2o`, `bundler`, `bal`,
`nvm`, and `openmvg` specs to `io_bench/families/reconstruction.py`.
Deterministic pose, state, graph, and reconstruction fixtures move to
`fixtures/reconstruction.py`; portable EuRoC, g2o, and BAL pairs move to
`oracles/reconstruction.py`. The facade retains exact compatibility aliases
and slices the reconstruction hook around the four calibration specs.
Specialized `colmap_sparse`, `colmap_sparse_txt`, and `colmap_db`
orchestration remains facade-owned until the runner extraction.

All nine `Spec` ASTs and 12 of 13 moved helper ASTs match the point
checkpoint. Review intentionally strengthens `_g2o_oracle_read`, the sole
helper difference, to return node ids/translations/quaternions, fixed-node
ids, edge endpoints/translations/quaternions, and reconstructed symmetric
information matrices. Compatibility controls compare every field from
oracle- and core-produced bytes. EuRoC, g2o, and BAL have live portable
comparison metrics. The other six rows record the exact unverified property,
independent benchmark encode/decode throughput, and point to independent
codec parity suites.

The complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused reconstruction/contract validation passes 505 tests with one existing
optional PyCOLMAP skip; the complete suite passes 3,316 with the same four
documented skips, Ruff is clean, and all three independent reviews are clear.
The exact-tree source archive has 359 members and exactly the three new
reconstruction modules. Its 81-member wheel excludes benchmark, test, and
PyCOLMAP modules, retains all 15 attribution files, and keeps NumPy as the
sole unconditional dependency; PyCOLMAP remains test-extra only. A fresh
NumPy-only environment without PyCOLMAP passes the installed-wheel smoke.

Exact reconstruction commit `76ed21b` passes normal run
[30247662591](https://github.com/SceneAPI/SceneIO/actions/runs/30247662591)
and compiler-instrumented run
[30247662622](https://github.com/SceneAPI/SceneIO/actions/runs/30247662622).

The sequence checkpoint moves the buffer-backed `y4m` spec to
`io_bench/families/sequences.py`, the Y4M and image-directory fixtures to
`fixtures/sequences.py`, and the portable Y4M parser/writer to
`oracles/sequences.py`. The facade retains exact compatibility aliases and
keeps Y4M between WebP and HDR. The `image_sequence` `DirectorySpec` remains
facade-owned until runner extraction, consuming the lower fixture through its
alias.

The Y4M `Spec`, directory orchestration, and three of four moved helper ASTs
match the reconstruction checkpoint. Review intentionally strengthens
`_y4m_oracle_read`, the sole helper difference, to validate and return all
planes, dimensions, frame rate, pixel aspect, chroma configuration, range,
matrix, and interlace. Y4M has live portable comparison metrics.
`image_sequence` records only the missing independent benchmark directory
encode/decode throughput; independent manifest and PGM payload parity remain
in `tests/codecs/test_image_sequence.py`. The direct directory round trip pins
dimensions, channels, frame dtype, resolved paths, timing, and byte-identical
frame copies.

The complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused sequence/contract validation passes 225 tests; the complete suite
passes 3,316 with four documented skips, Ruff is clean, and all three
independent reviews are clear. The exact-tree source archive has 362 members
and exactly the three new sequence modules. Its 81-member wheel excludes
benchmark and test modules, retains all 15 attribution files, and keeps NumPy
as its sole unconditional dependency. A fresh NumPy-only environment passes
the installed-wheel smoke.

Exact sequence commit `4b8c829` passes normal run
[30250394890](https://github.com/SceneAPI/SceneIO/actions/runs/30250394890)
and compiler-instrumented run
[30250394906](https://github.com/SceneAPI/SceneIO/actions/runs/30250394906).

The splat checkpoint moves the exact six-row family to
`io_bench/families/splats.py`, the deterministic Gaussian fixture to
`fixtures/splats.py`, and the optional `gsply` PLY/SPZ adapters to
`oracles/splats.py`. The facade retains exact compatibility aliases and keeps
the canonical `gaussian_ply`, `compressed_ply`, `sog`, `ksplat`, `spz`,
`splat` block between points and arrays.

All six `Spec` ASTs and all five moved helper ASTs match the sequence
checkpoint. Gaussian PLY and SPZ retain live `gsply` encode/decode metrics.
Compressed PLY, SOG, KSplat, and `.splat` each record only the missing
independent benchmark encode/decode throughput; their corresponding codec
suites retain independent format parity. Installed-oracle tests compare all
five logical Gaussian fields in both producer directions, with SPZ values
compared after quantization. A blocked-oracle process proves every SceneIO row
remains while only the two optional comparison pairs disappear.

The six live rows run successfully, and the complete 50-codec smoke retains
structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused splat/contract validation passes 176 tests with one documented SPZ-v2
writer skip; the complete suite passes 3,316 with four documented skips, Ruff
is clean, and all three independent reviews are clear. The exact-tree source
archive has 365 members and exactly the three new splat modules. Its
sdist-derived 81-member Windows wheel excludes benchmark, test, and `gsply`
payloads, retains all 15 attribution files, and keeps NumPy as its sole
unconditional dependency. A fresh NumPy-only installation passes
`sceneio._wheel_smoke`.

Exact splat commit `cd32268` passes normal run
[30253301819](https://github.com/SceneAPI/SceneIO/actions/runs/30253301819)
and compiler-instrumented run
[30253301871](https://github.com/SceneAPI/SceneIO/actions/runs/30253301871).

The runner checkpoint moves the complete sweep, specialized
glTF/COLMAP/image-directory orchestration, CLI parser, and supporting helpers
to `io_bench/runner.py`. `bench_io.py` remains the compatible direct entry
point and re-exports every historical non-dunder helper.

All 20 moved function ASTs match the splat checkpoint. The parent and
candidate expose the same 166 helper names with checked SHA-256
`0c26c90b0d3ee10cb216e5baf3b0502a446f55805c89a437ea71790bd39be33a`.
Every facade attribute is the lower runner object, facade rebinding propagates
to runner globals, and star imports retain the parent 67-name public surface.
Importing the runner does not load the facade, importing the facade does not
replace an already initialized runner's objects, and explicit facade reload
restores source definitions. Direct execution retains the CLI program name,
options, defaults, rejection behavior, output order, row schemas, and JSON
envelope.
The complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
This checkpoint changes ownership only. Repository-built-in completeness,
extra runtime registration isolation, and strict comparison-provider
qualification are implemented in the separate behavior unit below.

Focused runner/contract validation passes 145 tests; the complete suite
passes 3,316 with four documented skips, and Ruff is clean. The exact staged
tree has 365 tracked files and produces a 366-member source archive with only
generated `PKG-INFO` extra. Its sdist-derived 81-member Windows wheel excludes
benchmark and test modules, retains all 15 attribution files, keeps NumPy as
its sole unconditional dependency, and passes a fresh NumPy-only
`sceneio._wheel_smoke`.

Runner commit `cf8d117` passes normal run `30257105454` and
compiler-instrumented run `30257105468`. The final R3.2 behavior implementation
adds `io_bench/qualification.py`: its immutable ledger covers all 50 canonical
built-ins with 33 timed comparisons and 17 reviewed exemptions. Coverage
validation runs before filtering or measurement, and a registered runtime
extension is proven absent from repository qualification. `--strict-oracles`
rejects partial/disabled sweeps, preflights every timed callback binding,
bypasses the optional failure-masking path, and audits every declared metric
after the complete sweep. A one-run strict sweep returns 50 successful rows
and all 33 timed comparison pairs; the independent skip-comparison smoke
retains structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
The complete five-run strict O4/O5 guard passes; the exact local tree collects
3,339 tests and passes 3,335 with four documented skips, and Ruff is clean. No
tracked file reaches 100 MiB. All three independent closure reviews are clear.
The exact staged tree has 367 tracked files and produces a 368-file sdist whose
only generated file is `PKG-INFO`; its sdist-derived 81-member Windows abi3
wheel contains one native module and all 15 attribution files, excludes
benchmark/test/build payloads, and installs only SceneIO plus NumPy in a fresh
environment. `sceneio._wheel_smoke` returns `2`.

### R3.3 — cross-codec test support

- [x] Commit a centralized buffer/path/directory catalog in
      `tests/_support/codec_cases.py` without consuming it.
- [x] Migrate mmap consumers while retaining the old matrix until exact
      equivalence is demonstrated.
- [x] Migrate streaming consumers in a separate commit under the same rule.
- [x] Migrate inspection consumers in a separate commit under the same rule.
- [x] Migrate partial consumers one family at a time under the same rule.
  - [x] Move the three array-specific DMB/FLO behavior tests unchanged into
        `tests/test_io_partial_arrays.py`; retain cross-family window tests in
        the shared suite.
  - [x] Move the 10 parameterized Netpbm/WebP image nodes unchanged into
        `tests/test_io_partial_images.py` and lower their two shared window
        assertions under `tests/_support/partial_read.py`.
  - [x] Move the mesh face-range behavior unchanged into
        `tests/test_io_partial_meshes.py`.
  - [x] Move the 13 XYZ/LAS point-specific nodes unchanged into
        `tests/test_io_partial_points.py` and lower their shared range
        assertion under `tests/_support/partial_read.py`.
  - [x] Move the 15 COLMAP reconstruction-specific nodes unchanged into
        `tests/test_io_partial_reconstruction.py` and lower the shared
        cross-family RSS helper under `tests/_support/partial_read.py`.
  - [x] Audit sequence and splat consumers. Their dedicated partial behavior
        was already family-owned by the sequence/splat architecture and codec
        suites before R3.3, so no node-path move is warranted; retain the
        deliberately cross-family point/splat invariants in
        `tests/test_io_partial.py`.
- [x] Remove each superseded local matrix only after its replacement is proven
      equivalent; retain the shared partial suite because its seven behavior
      tests are cross-family contracts rather than a duplicate family matrix.
  - [x] Remove the mmap matrix after exact local and hosted equivalence.
- [x] Preserve parameter ids so CI failures remain attributable.
- [x] Avoid snapshot-only assertions for numeric values, conventions, or
      malformed inputs.
- [x] Compare sorted pytest node ids, parameters, and skip reasons before and
      after. Record an explicit rename mapping; test count alone is
      insufficient.
  - [x] Record and enforce the exact 16-node streaming path rename while
        preserving all test names and the `npy`/`pfm`/`flo` parameter ids.
  - [x] Record and enforce the exact 76-node inspection path rename while
        preserving every test name and parameter id.
  - [x] Record the three array partial paths and all 10 image partial
        parameterized paths; pin their destination function AST projections.
  - [x] Record the mesh partial path and pin its destination function AST
        projection.
  - [x] Record all 13 point partial paths and pin their destination function
        AST projection.
  - [x] Record all 15 reconstruction partial paths and pin their test, private
        helper, and lower shared-helper AST projections.
  - [x] Record the lower move of the two shared image-window assertions so
        family modules never import sibling test modules.

R3.2 closes at exact commit `0e54cf5`: normal run `30263506366` and
compiler-instrumented run `30263506270` pass. The first R3.3 unit adds an
immutable catalog in canonical order with 44 buffer, three path, and three
directory definitions plus the exact projection of 28 partial-capable codecs
and 32 selector declarations. Six focused
architecture controls prove completeness, family ownership, live capability
agreement, runtime-extension isolation, and the initial non-consuming
boundary. Its complete local tree collects 3,345 tests and passes 3,341 with
four documented skips; Ruff and all three independent reviews are clear.
Exact catalog commit `81f143b` passes normal run `30266501529` and
compiler-instrumented run `30266501618`.

The mmap suite now consumes the deterministic
`tests/_support/buffer_codec_cases.py` builder. The retained
`_legacy_buffer_codecs` builder proves exact 44-case order, reader/writer
identity, encoded bytes, and full record fingerprints before the existing
mutation-sensitive consumers run. The mmap suite passes 114 tests; the
complete local tree collects 3,346 tests and passes 3,342 with four documented
skips. Ruff and all three independent reviews are clear. The one-run 50-codec
benchmark smoke retains structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
The exact staged tree has 371 tracked files and produces a 372-file sdist
whose only generated file is `PKG-INFO`; its sdist-derived 81-member Windows
abi3 wheel contains one native module and all 15 attribution files, and a
fresh SceneIO-plus-NumPy environment passes `sceneio._wheel_smoke`.

Exact mmap migration commit `9a73892` passes normal run `30268797350` and
compiler-instrumented run `30268797374`, including all three mmap platforms,
GCC 10, the full suite, and the five-run guard. The duplicated
`_legacy_buffer_codecs` matrix is therefore removed. The architecture contract
retains its exact 44-case order, live reader/writer identities, and
43-codec portable encoded-fixture projection SHA-256
`b21a55c6cbde2a46d89bf2bc013b6e81ffe3d58565922dcd690c2605f31143ab`.
Compressed PLY is excluded from that universal byte hash because its
quantization has an established AppleClang profile; its shared semantic
Gaussian input and platform-profiled parity test remain checked. The unchanged
mmap behavior suite retains semantic, lifetime, protocol, truncation, and
mutation coverage. The original candidate node set is restored exactly: 3,345
nodes with sorted normalized SHA-256
`fc4934cb3fcf4a1a37fb5a087dcf0b13821df1f926f12412931b8ce040b93a05`.
The complete local suite passes 3,341 tests with four documented skips, and
the one-run 50-codec benchmark smoke retains structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Exact removal commit `fc86f44` passes normal run `30271311308` and
compiler-instrumented run `30271309916`.

The streaming consumers now live in `tests/test_io_streaming.py`. Fourteen
function bodies produce the same 16 collected tests as at `fc86f44`; the only
node-id change is the explicit `test_io_mmap.py` to `test_io_streaming.py`
path mapping pinned in `io_registry_assembly_v1.json`. The shared
`tests/_support/memory_measurement.py` helper avoids duplicating the
allocation probe. The focused streaming, mmap, and assembly suites pass 124
tests. The complete local suite remains 3,341 passed and four skipped from
3,345 collected, with normalized collection SHA-256
`1131f211bb324c4d6800350b71364eb1f95efd13acef5a6dc4e984d708a88d53`;
Ruff is clean and the 50-codec benchmark structure remains
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
The exact staged tree has 373 files and produces a 374-file sdist whose only
generated member is `PKG-INFO`. Its sdist-derived 81-member Windows abi3 wheel
contains one native module and all 15 attribution files, excludes repository
test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in a fresh
SceneIO-plus-NumPy environment. The three-platform mmap job includes
`test_io_streaming.py` explicitly.

Exact streaming migration commit `914702d` passes normal run `30274413815`
and compiler-instrumented run `30274413693`. Inspection behavior now lives in
`tests/test_io_inspection.py`: 47 tests plus three helpers are AST-identical
to the `914702d` definitions, and the same 76 collected suffixes are pinned in
a reusable rename group. The focused mmap, inspection, assembly, and catalog
suites pass 114 tests; the complete collection remains 3,345 with normalized
SHA-256
`f90c2f368fa8d5f976291cc8af3c7038c740893ac1abc78ec9b1bcf4ca5af959`.
Both platform commands name the inspection module explicitly. Exact package
verification records 374 staged files, a 375-file sdist, and the unchanged
81-member wheel; its fresh SceneIO-plus-NumPy environment passes
`sceneio._wheel_smoke`.

Exact inspection migration commit `0e21e27` passes normal run `30278777267`
and compiler-instrumented run `30278777173`. The first partial-family unit
moves the DMB window test plus both FLO mapped-window lifetime/error-release
tests unchanged into `tests/test_io_partial_arrays.py`. Its three exact
path-only renames and function AST projection are contract-pinned, while the
cross-family window differential remains in `tests/test_io_partial.py`.
Windows and non-Windows platform commands include both partial modules
explicitly. The complete collection remains 3,345 with normalized SHA-256
`ae4ab66a375c9c130ddf10682eb37e2ba21a0433ba2fb454ecce4358ef616414`.
Exact package verification records 375 source files, a 376-file sdist with
only generated `PKG-INFO`, and the unchanged 81-member Windows abi3 wheel.
Its fresh SceneIO-plus-NumPy environment passes `sceneio._wheel_smoke`.

Exact array partial migration commit `5009ea0` passes normal run `30282057346`
and compiler-instrumented run `30282056576`. The image-family unit moves the
binary Netpbm branch matrix, ASCII Netpbm rejection matrix, and lossy-WebP
rejection matrix unchanged into `tests/test_io_partial_images.py`. Their
three function bodies produce the same 10 parameterized suffixes. The
unchanged `_pixels` and `_assert_image_window` helpers move once into
`tests/_support/partial_read.py` and remain shared with the cross-family
window differential. Function/node projections and both platform commands
are contract-pinned. The complete collection remains 3,345 with normalized
SHA-256
`c9db2c71c11f6af8d4fcd5a08a5bf75a2428ea915805e3671c5cadb2ef581cc4`.
Exact package verification records 377 source files, a 378-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.
Exact image partial migration commit `d198560` passes normal run
`30285128366` and compiler-instrumented run `30285128448`.

The mesh-family unit moves the unchanged face-range semantic and mapping-close
test into `tests/test_io_partial_meshes.py`. Its single exact path-only rename
and destination function AST projection are contract-pinned, and both platform
commands name the focused module. The complete collection remains 3,345 with
normalized SHA-256
`c658cb0d7353ad5c6cf4f6e38b01a02418f693b121e6d8f4bba887945821cc9d`.
Exact package verification records 378 source files, a 379-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.
Exact mesh partial migration commit `4294dbe` passes normal run `30287854716`
and compiler-instrumented run `30287854692`.

The point-family unit moves three unchanged XYZ/LAS functions producing 13
parameterized nodes into `tests/test_io_partial_points.py`. The unchanged
`_assert_point_range` helper moves once into
`tests/_support/partial_read.py`, where the shared point/splat differential
continues to consume it. Function, node, and helper projections plus both
platform commands are contract-pinned. The complete collection remains 3,345
with normalized SHA-256
`2451c9bb2606ac1587011eafeb2345fc9f34f7e08df7ea17b239b5a1e78a624f`.
Exact package verification records 379 source files, a 380-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.
Exact point partial migration commit `ac1a4d1` passes normal run `30290617469`
and compiler-instrumented run `30290617607`.

The reconstruction-family unit moves 12 unchanged COLMAP functions producing
15 nodes plus nine private helpers into
`tests/test_io_partial_reconstruction.py`. The unchanged
`_fresh_process_partial_rss` helper moves once into
`tests/_support/partial_read.py`, where the retained cross-family large-read
test and the reconstruction suite both consume it. Test, node, private-helper,
and lower-helper projections plus both platform commands are contract-pinned.
The complete collection remains 3,345 with normalized SHA-256
`217c227e566a6767fc59b031b1217202ced5ba0dc6a14b3b7fa2d27c0f9314f4`.
Exact package verification records 380 source files, a 381-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.
The first hosted normal run `30294120621` exposed four explicit manylinux
selectors that still named the pre-move shared module. The focused module
paths are corrected and the assembly suite now rejects both a missing new
selector and any retained stale selector. Compiler-instrumented run
`30294120444` passed the exact reconstruction commit. Follow-up commit
`b5e5c55` passes normal run `30296172958` and compiler-instrumented run
`30296174522`.

The sequence/splat disposition audit closes the last R3.3 ownership question
without creating empty or misleading suites. The assembly contract pins eight
sequence partial-behavior functions across the existing sequence architecture
and codec suites, three splat-family partial/unsupported-selector functions,
their exact 21 collected node ids and parameter ids, and all seven retained
shared partial functions by AST projection. An AST-derived per-function
format mapping proves the shared tests contain no sequence format and retain
both splat and non-splat formats, so their point/splat, endian, truncation,
validation, and large-read checks remain genuine cross-family invariants. This
closure adds no pytest node and changes no codec path.

The closure candidate collects 3,345 tests and passes 3,341 with four
documented skips. Ruff and the complete five-run strict O4/O5 guard pass. Its
exact staged tree contains 380 source files and produces a 381-file sdist whose
only generated member is `PKG-INFO`; the sdist-derived 81-member Windows ABI3
wheel contains one native module and all 15 attribution files, excludes
repository test/benchmark/build payloads, and keeps NumPy as its sole
unconditional dependency. A fresh SceneIO-plus-NumPy installation returns
`2` from `sceneio._wheel_smoke`.

### R3.4 — complete installed-wheel smoke

- [x] Drive wheel smoke from `BUILTIN_DEFINITIONS`, not a hand-maintained
      helper list.
- [x] Assert the smoke-case id union equals the exact installed built-in
      registry id set.
- [x] Perform a NumPy-only write/read/inspect operation for each of the 50
      built-ins, plus streaming and selectors where the manifest declares
      them.
- [x] Require a reviewed, property-specific exemption for any operation a
      minimal generated fixture cannot exercise.

The manifest-driven runner derives canonical order from
`BUILTIN_DEFINITIONS`, requires exact equality with `_SMOKE_RUNNERS`,
`REGISTRY`, and `sceneio.codecs()`, and observes successful public operations
rather than inferring coverage from helper names. Expected properties are
derived from each live capability record. Missing, unexpected, malformed, or
stale exemptions fail with a codec/property diagnostic. The current immutable
exemption mapping is empty: all 50 built-ins exercise public
write/read/inspect, every codec declaring a streaming direction completes its
corresponding public path operation, and all 32 selector declarations are
exercised. Dedicated mmap and sink suites independently prove the allocation
semantics behind the stream-capability flags. The exact collection is 3,348
nodes with sorted normalized
SHA-256
`d9d54514509003ae3b9c4d1d1a6aac470ab16068641dcd452953483744d4741f`;
the complete suite passes 3,344 tests with four documented skips. Ruff,
`git diff --check`, the source-tree smoke, and the complete five-run strict
O4/O5 guard pass.

The first exact-tree package qualification has 380 source files and a
381-file sdist whose only generated member is `PKG-INFO`. Every source member
matches its staged Git blob. The sdist-derived 81-member Windows ABI3 wheel
contains one native module and all 15 attribution files, excludes repository
test/benchmark/build and native development payloads, and keeps NumPy as its
sole unconditional dependency. A fresh outside-repository environment
contains only SceneIO 0.2.0 and NumPy 2.5.1 and returns `2` from the complete
installed smoke. The final documented tree repeats this package gate before
review.

R3 verification and validation:

- [x] R3.1a one-run all-codec smoke produces the same codec set and JSON
      fields.
- [x] R3.1a five-run O4/O5 controls retain direction and memory relationships
      after the required confirming complete run.
- [x] R3.1b protocol coverage is wired into the existing Linux, Windows, and
      macOS mmap/partial lane; exact-commit normal run `30234796010` and
      compiler-instrumented run `30234796025` pass.
- [x] Strict qualification mode fails on an absent required oracle or RSS
      sampler instead of silently dropping evidence.
- [x] Full suite and Ruff pass after each family.
- [x] `bench/bench_io.py` remains the compatible CLI entry point through
      R3.1a; repeat this gate after every remaining R3 unit.
- [x] R3.4 exact 50-codec wheel-smoke coverage, complete local suite, Ruff,
      five-run strict guard, and source-derived package qualification pass.

## 8. R4 — organize CMake, bindings, and native files

### R4.1 — split build configuration

- [x] Extract dependency declarations, SceneIO source lists, instrumented
      options, and third-party targets into focused `cmake/` files.
- [x] Preserve every option default, compile definition, source, link target,
      visibility setting, and platform conditional.
- [x] Add configure-time assertions for missing/duplicate SceneIO sources.
- [x] Compare CMake cache variables and verbose compile/link commands before
      and after on MSVC and GCC 10.

The R3.4 parent is `9ca6bb8`. The root build file now contains only the
project language/standard setup and ordered includes for
`SceneIOInstrumentation.cmake`, `SceneIOSources.cmake`,
`SceneIODependencies.cmake`, and `SceneIOTargets.cmake`. The extracted
840-line dependency/third-party block is byte-identical to the parent
(normalized SHA-256
`1444db21844c5bb43314496f4cd5c2bf9dd4a586a9fb88a3e474b1c1cca9768e`).
The source module partitions all 40 codec translation units across the eight
manifest families, lists all 16 record translation units, retains the exact
historical 59-source `_core` order, and stops configuration for missing or
duplicate ownership.

Fresh MSVC parent/candidate configurations each expose 321 cache entries with
no non-path difference. Their 60 normalized `_core` compile/link commands are
exact, with SHA-256
`37678e397c075cbfdaffd08b37cecc1be4f62cbcec542e274818163b4741217b`.
Fresh manylinux2014 GCC 10.2.1 configurations each expose 370 cache entries
with no non-path difference. Their 59 `_core` compile commands are exact,
with SHA-256
`e8b8599fbd2549fb07c0caff08e438a9fd881044fe85a02a8028523366f8b797`,
and the final link commands are exact. The MSVC editable build and complete
GCC 10 `_core` target build pass. Four new architecture tests freeze the
module split, family ownership, record set, target linkage, and option
defaults; the complete collection is 3,352 nodes with sorted normalized
SHA-256
`074944e367045763b8f4b9afa090411010a81348cb5661f08eb75f3d51c2e4d8`.
The unchanged strict five-run all-50-codec performance/allocation guard passes
and records `build/r4_1_strict_guard.json`; no timed implementation changed
and no speedup is claimed.

The staged 386-file source tree produces a 387-file sdist whose only generated
member is `PKG-INFO`; every repository member is byte-identical to its staged
Git blob after disabling checkout line-ending conversion for archive
construction. Its sdist-derived Windows ABI3 wheel retains 81 members, exactly
one native module, all 15 attribution files, no excluded native development
payload, and NumPy as the sole unconditional dependency. A fresh
outside-repository environment contains only SceneIO 0.2.0 and NumPy 2.5.1
and returns `2` from the complete installed smoke.

R4.1 is pushed at `b2cf5d4`. Normal run `30310780347` and
compiler-instrumented run `30310780355` pass that exact commit.

### R4.2 — split binding registration

- [x] Add family registration functions under `src/cpp/bindings/`.
- [x] Preserve record-before-codec construction and the `_core` symbol
      snapshot.
- [x] Keep one declaration/definition owner for every registration function.
- [x] Generate a private machine-readable `_core.__codec_inventory__` from the
      same native family tables. Include built-in id, family, and available
      read/write/inspect/stream/partial symbols.
- [x] Compare the native inventory exactly with the `native`/`hybrid`
      projection of `BUILTIN_DEFINITIONS`; separately resolve and validate the
      declared symbols for `python`/`hybrid` adapters.
- [x] Fail on an orphaned, multiply owned, or owner-mismatched codec.
- [x] Rebuild the aggregate candidate and run an explicit import/symbol smoke.

The committed implementation preserves the historical record-before-codec order through
explicit ordinals, validates unique names, function pointers, manifest
positions, family ownership, and symbol resolution, and leaves the 232-name
non-dunder `_core` snapshot unchanged. Its inventory is a canonical-order
49-entry tuple of read-only mapping rows: every native/hybrid built-in has
required read, write, and stream symbols; optional inspect and partial symbols
agree exactly with the Python ownership manifest and live capability
selectors. A separate `native_inventory_v1.json` contract freezes every
ordered operation tuple and requires each symbol to resolve to a callable.
Full-path recursive source contracts remain valid after the R4.3 moves. The
Python-only `image_sequence` id is intentionally absent. MSVC and
manylinux2014 GCC 10.2.1 build the 69-translation-unit `_core`; the focused
416-test sweep and unchanged strict five-run performance/allocation guard pass.
The complete 3,354-node suite passes 3,350 tests with four documented skips,
and Ruff is clean. All three confirmation reviews are clear. The 398/399/81 exact-tree
source/sdist/wheel package gate and fresh NumPy-only smoke pass.
Commit `81e0e1c`, normal run `30316577366`, and compiler-instrumented run
`30316577369` close the hosted gate.

The first three-lens review found no native lifetime defect. Its two shared
test-soundness findings and one maintainability finding are implemented:
operation categories now have an independent exact contract, runtime and tests
require callable symbols, inventory rows are read-only, and source ownership is
recursive and path-exact. The architecture/lifetime, test/performance, and
platform/package/documentation confirmation reviews are clear.

### R4.3 — move native codecs by family

- [x] Move files mechanically; do not split cohesive parsers solely because
      they are large.
- [x] Fix include paths/build lists only.
- [x] Maintain explicit per-family CMake source manifests and assert that
      every SceneIO native codec source has exactly one owner.
- [x] Run family parity, bytes/mmap, sink, inspect, partial, lifetime, and
      malformed-input tests after each move.
- [x] Confirm no exported native symbol or wheel member-set change.

Arrays-family candidate:

- [x] Move PFM, NPY/NPZ, Safetensors, FLO, and DMB under
      `src/cpp/codecs/arrays/`.
- [x] Preserve implementation blobs, update the one embedded source-location
      comment, and update CMake, native-build contracts, and performance-ledger
      paths.
- [x] Rebuild on MSVC and pass the 561-node (560-pass/one-skip)
      array-family/cross-I/O sweep,
      Ruff, the 232-name `_core` symbol check, and the 49-entry native
      inventory check.
- [x] Pass the complete five-run strict all-50-codec O4/O5 and mmap/sink
      regression guard.
- [x] Complete the three independent reviews.
- [x] Commit and push the arrays unit at `f57c677`.

Calibration-family candidate:

- [x] Move the shared OpenCV/ROS/Kalibr source under
      `src/cpp/codecs/calibration/` and update path contracts only.
- [x] Rebuild on MSVC and pass 223 focused tests, the complete
      3,350-pass/four-skip suite, Ruff, and the 232-name/49-entry native
      surface checks.
- [x] Pass the complete five-run strict all-50-codec O4/O5 and mmap/sink
      guard.
- [x] Complete the three independent reviews.
- [x] Commit and push the calibration unit at `366aac0`.

Images-family candidate:

- [x] Move Netpbm, PNG, JPEG, BMP/TGA, HDR, EXR, and WebP under
      `src/cpp/codecs/images/` and update path contracts only.
- [x] Rebuild on MSVC and pass 493 focused tests, the complete
      3,350-pass/four-skip suite, Ruff, and the 232-name/49-entry native
      surface checks.
- [x] Pass the complete five-run strict all-50-codec O4/O5 and mmap/sink
      guard.
- [x] Complete the three independent reviews.
- [x] Commit and push the images unit at `aff2a37`.

Meshes-family candidate:

- [x] Move PLY-mesh, OBJ/MTL, STL/OFF, and glTF under
      `src/cpp/codecs/meshes/` and update path contracts only.
- [x] Rebuild on MSVC and pass 419 focused tests, the complete
      3,350-pass/four-skip suite, Ruff, and the 232-name/49-entry native
      surface checks.
- [x] Pass the complete five-run strict all-50-codec O4/O5 and mmap/sink
      guard.
- [x] Complete the three independent reviews.
- [x] Commit and push the meshes unit at `c5de24b`.

Points-family candidate:

- [x] Move PLY-point, PCD, XYZ/PTS, LAS, and LAZ under
      `src/cpp/codecs/points/` and update path contracts only.
- [x] Rebuild on MSVC and pass 583 focused tests, the complete
      3,350-pass/four-skip suite, Ruff, and the 232-name/49-entry native
      surface checks.
- [x] Pass the complete five-run strict all-50-codec O4/O5 and mmap/sink
      guard.
- [x] Complete the three independent reviews.
- [x] Commit and push the points unit at `97b24e2`.

Reconstruction-family candidate:

- [x] Move all eleven native reconstruction sources under
      `src/cpp/codecs/reconstruction/` and update path contracts only.
- [x] Rebuild on MSVC and pass 691 focused tests with two documented skips,
      the complete 3,350-pass/four-skip suite, Ruff, and the
      232-name/49-entry native surface checks.
- [x] Pass the complete five-run strict all-50-codec O4/O5 and mmap/sink
      guard.
- [x] Complete the three independent reviews.
- [x] Commit and push the reconstruction unit at `25f74bb`.

Sequence-family candidate:

- [x] Move Y4M under `src/cpp/codecs/sequences/` and update path contracts
      only.
- [x] Rebuild on MSVC and pass 245 focused tests, the complete
      3,350-pass/four-skip suite, Ruff, and the 232-name/49-entry native
      surface checks.
- [x] Pass the complete five-run strict all-50-codec O4/O5 and mmap/sink
      guard.
- [x] Complete the three independent reviews.
- [x] Commit and push the sequence unit at `2e30e9f`.

Splats-family candidate:

- [x] Move all six native splat sources under `src/cpp/codecs/splats/` and
      update path contracts only.
- [x] Rebuild on MSVC and pass 332 focused tests with one documented skip,
      the complete 3,350-pass/four-skip suite, Ruff, and the
      232-name/49-entry native surface checks.
- [x] Confirm all 40 native codec sources are nested under the eight family
      directories and no flat codec source remains.
- [x] Pass the complete five-run strict all-50-codec guard.
- [x] Complete the three independent reviews.
- [x] Commit and push the splats unit at `da1d709`.

R4 verification and validation:

- [x] Editable builds pass on MSVC and GCC 10.
- [x] Full local suite, Ruff, all-codec benchmark guard, sdist, wheel, and
      NumPy-only smoke pass.
- [x] Windows/macOS mmap and Linux normal/instrumented jobs pass at the final
      R4 commit.
- [x] The public/API snapshots remain unchanged.

Final R4 evidence: the exact 398-file `da1d709` Git archive and every one of
its blobs reappear unchanged in the 399-file sdist; generated `PKG-INFO` is the
only addition. The sdist SHA-256 is
`2b6d46e71fc4cf28b9d5b9ca2886e7b66a41a93d352bba6a16ab65384fe35afb`.
Its 81-member Windows ABI3 wheel has SHA-256
`51d658366be1a0f7f06bb9a8082a97d137470250649904d39ce75d62c2f8390b`,
the same member set as R4.2, one native module, all 15 attribution files, and
no excluded native-development payload. The exact source and package artifacts
contain no FFmpeg/libav source, linkage, executable, or payload. A fresh
environment contains only SceneIO 0.2.0 and NumPy 2.5.1 and returns `2` from
the installed smoke. Normal run
[30326256230](https://github.com/SceneAPI/SceneIO/actions/runs/30326256230) and
instrumented run
[30326256137](https://github.com/SceneAPI/SceneIO/actions/runs/30326256137)
pass exact commit `da1d709`. All three final R4 reviews are clear.

## 9. R5 — bounded candidate decision and reusable qualification mechanism

R5 is performed one codec, performance profile, and applicable direction at a
time only when a measured regression, material hotspot, or concrete replacement
proposal triggers it. Popularity is candidate-discovery evidence, not
performance evidence. For the current stage, JPEG was the single bounded
candidate funnel and its negative result closes active R5 work.

### R5.1 — candidate intake

- [x] List every viable mature permissive candidate and its exact version/SHA,
      license, maintenance status, supported subset, build system, SIMD/thread
      support, and supported compilers.
- [x] Record why a candidate is excluded.
- [x] Confirm the candidate can be pinned, built statically/offline, hidden
      inside `_core`, and attributed.
- [x] Integrate candidate source only in a non-default qualification target
      with a test-only selector; default wheels and the public API must not
      expose the candidate before selection.
- [x] Assert qualification-only options, symbols, and sources are absent from
      default wheels.
- [x] Start with the JPEG encode/decode comparison against libjpeg-turbo and
      any other viable permissive finalist.

R5.1 local evidence (2026-07-28): `bench/BACKEND_CANDIDATES.toml`
records the retained stb revision, libjpeg-turbo 3.2.0 finalist, and the
objective exclusions for mozjpeg 4.1.1 and the evaluated untagged jpegli
revision. `SCENEIO_BUILD_BACKEND_QUALIFICATION` defaults off and a non-stb
override is rejected unless it is explicitly enabled. A separate
source-controlled internal default remains `stb`; the effective-backend graph
adds `src/cpp/qualification/jpeg_turbo.cpp` only for libjpeg-turbo. The two
qualification builds exercise the same `read_jpeg`/`write_jpeg` implementation
seam and add only a private build-identification hook; the ordinary build
retains the frozen 232-name core surface.

The accelerated MSVC build used the official libjpeg-turbo 3.2.0 archive
(`c85e6b905bf237038faa936dab160ebfc5da0344`, SHA-256
`6f30092cef9fb839779646608f4ee14ae3cbac989c47fa05e841b0841f09878e`)
with required x86-64 SIMD through NASM 3.02 and the dynamic MSVC runtime.
Visual Studio and MSVC-Ninja builds both pass, covering multi-configuration
and flat archive layouts. The generated evidence manifest records the
generator, compilers, runtime choice, external cache path, option fingerprint,
SIMD architecture, and NASM version/executable hash. Exact upstream
libjpeg-turbo and IJG notices plus the required IJG acknowledgement are
packaged for every candidate artifact. Fresh wheel hashes and member counts
are: ordinary stb
`533ae7e3dba3de866324efc411a0bdf932c4a6f03c29a424fcf30964befee798`,
explicit stb
`a2385d468804dd139b082d639c9eb185b7e790d98d87d97b3794b7935dfa0855`,
and libjpeg-turbo
`63f33e635ff0b20547cc93fb7f48642b722ec1c612e1be0e72bf9f6e76ca20a9`.
Each wheel has 83 members, 17 attribution members, one native module, and no
header, static-library, CMake, or package-config payload. Their minimal
SceneIO-plus-NumPy environments all return `2` from `_wheel_smoke`; after
pytest and Pillow are added, focused installed tests pass 21 with one
environment-only absent-torch skip for ordinary and explicit stb and 20 with
the absent-torch plus retained-byte skips for turbo. The turbo native module
adds 659,456 uncompressed bytes and 195,056 wheel bytes, depends only
on CPython and standard Windows/MSVC runtimes, preserves the retained
module's Windows export set, and adds no JPEG or libjpeg-turbo export.

CMake 3.18.6, the now-accurate project floor, configures and builds the full
optimized candidate core with MSVC and Ninja Multi-Config. Concrete
per-configuration byproducts keep the multi-config path valid at that floor,
and the exact wheel verifies the shortened external-project prefix needed to
stay within Windows path limits.
The manifest records the configuring CMake version and target processor; the
generated candidate header records `SIMD_ARCHITECTURE X86_64`. This proves
intake and isolation only: no backend has been selected, and no candidate
performance row has been promoted.

The retained seam has a paired non-regression result. After restoring the
original string callback and reserving the known raw input size, four
interleaved processes per backend with 15 timed runs each measured R4 versus
current core writes at 60.420 versus 60.538 MB/s (+0.19%). The two
filesystem-inclusive paths differed by -1.00% and -1.03% within their noisier
envelopes, while their Python paths and all six locked encoded-byte vectors
remain unchanged.

The default-backend five-run all-50-codec sweep retains strict comparison
providers and the O4/O5 partial guards. Its 50-row JSON has SHA-256
`faf64165be690e221fd01cb233bd9c4079f0da6248d5c15ab9d819cc93198d68`;
the exact O5 inspection predicates applied to those same rows pass, including
the historically marginal `transforms_json` control at 2.435x. A preceding
fully gated run and paired focused repetitions of the untouched R4 wheel show
that control can cross 3x on this host (R4: 3.136x--3.265x). No JSON codec,
registry, or benchmark path changed in R5.1, so the threshold remains intact
and the variance is retained rather than normalized away.

### R5.2 — fair production-path benchmark

- [x] Benchmark through SceneIO's actual public/core adapter, not an isolated
      library microbenchmark.
- [x] Define the full codec × profile × direction matrix before running. Do
      not let one easy encoding mode qualify materially different paths.
- [x] Use identical canonical records, output subset, quality/subsampling,
      thread/lane policy, compiler mode, and warm/cold methodology.
- [x] For decoder comparisons, feed every candidate the same hashed encoded
      corpus. Never compare decoder throughput when each encoder produced
      different bytes.
- [x] Record each decoder fixture's producer, version, settings, provenance,
      hash, and accepted-subset coverage. Include streams from the retained
      writer and an independent reference/spec fixture where possible; a
      candidate's own output is never its sole decode corpus.
- [x] Implement separate encode/decode collection for:
  - [x] throughput/latency for small, representative, and generated large
        fixtures;
  - [x] public mmap/path read and direct-sink write;
  - [x] traced allocation and fresh-process RSS after a fixed small-fixture
        warm-up, measuring the first target-fixture operation;
  - [x] a fixed one-lane policy, with bounded automatic lanes recorded as
        not applicable because neither selected JPEG API exposes a lane
        control;
  - [x] output size and, for lossy codecs, decoded quality under the existing
        parity metric;
  - [x] deterministic bytes where the format/backend contract permits them;
  - [x] wheel size, SceneIO-only import time, and independent fresh-process
        encode-first/decode-first startup.
- [x] Record raw JSON, fixture hashes, CPU/toolchain, compiler flags, library
      revisions, settings, sample order, sample count, median, MAD, and paired
      candidate/baseline ratios.
- [x] Randomize or interleave candidate order after fixed warmups, repeat
      sessions on the same machine, and predeclare the noise/outlier policy.
      Retain raw samples; do not delete inconvenient outliers after inspection.
- [x] Label cold-cache data valid only when cache eviction is confirmed.
      Advisory cache hints are reported as best-effort, not cold-cache proof.
- [x] Execute the clean full local matrix and retain the complete result,
      including a failed frozen gate. The candidate passed throughput,
      allocation/RSS, startup, repeatability, compatibility, and package-size
      gates but failed `quality-profile:rgb8_q95_444`.
- [x] Apply the platform funnel before selection. The only finalist failed on
      MSVC, leaving no conforming candidate to advance to the user-gated
      manylinux2014 GCC 10 and AppleClang comparison.

R5.2 harness implementation evidence (2026-07-28):

- `bench/BACKEND_QUALIFICATION.toml` freezes 97 local and 122
  remote-inclusive JPEG production-path cells before the official run. It
  covers q90 4:2:0 and q95 4:4:4 writes, core buffer/core sink/public sink,
  same-corpus core bytes/core mmap/public path reads, baseline 4:2:0 and
  4:4:4, progressive, restart-marker, grayscale, CMYK, and YCCK streams.
- The deterministic generated corpus includes retained and Pillow producers
  plus a pinned true-YCCK fixture whose encoded SHA-256 is
  `2a3223d511c8750927237bd7b3b0d1d6e2aeb7bfe14e96197f00632907ef01c0`.
  Independent marker parsing verifies sampling, progressive mode, restart
  markers, component count, and the Adobe transform before timing.
- Isolated installed-wheel workers preserve every integer sample. Six local
  or eight remote paired sessions use a balanced seeded order; reports retain
  per-cell medians, MAD, paired ratios, a robust lower bound, output size,
  PSNR, decoded parity, traced allocation, fresh-process RSS, process startup,
  first calls, repeatability, and package size.
- The CMake candidate build now emits a separate receipt derived from
  libjpeg-turbo's generated `jconfigint.h`; the local MSVC probe records
  `SIMD_ARCHITECTURE X86_64` and binds the receipt to the header hash.
- A current complete quick protocol run exercises 19 cells, four
  installed-wheel sessions, eight independent startup processes, and two
  repeatability workers. Its report
  SHA-256 is
  `159f1fe98df290d3952bba9cab95b102eb7a16127193001d242ec1ee7b7e5166`
  and is explicitly labeled `smoke_only`; dirty-source allowance cannot
  produce an official report. The installed Python package members and native
  module are both bound to the supplied wheel, every declared session/cell/raw
  sample is required, and prior decoded results are released between timed
  samples. Fresh-process RSS warms only `small_odd`, then measures the first
  target-fixture operation so retained large-case memory remains visible.
- `.github/workflows/backend-qualification.yml` is manual and
  nonpublishing. It prepares paired wheels and full remote-inclusive evidence
  on MSVC x86-64, the pinned manylinux2014 GCC 10 image with a hash-pinned
  NASM 3.02 source build, and AppleClang arm64, then accepts only a passing
  exact-source/configuration set. The workflow has not been dispatched; no
  three-toolchain result or backend selection is claimed.
- The binding clean-wheel MSVC run uses source commit
  `7a88e7c726eed5bdd4ff0ad05b381c9795af9dfe`, eight paired sessions over all
  122 cells, 24 startup observations, six repeatability observations, and 24
  fresh-process memory observations. libjpeg-turbo records 4.787x encode and
  1.782x decode median geomeans, while its q95 4:4:4 median comparative PSNR
  delta is `-0.058242 dB`, below the frozen `-0.05 dB` floor. Exactly one of
  1,597 gates fails. Both 83-member wheels retain NumPy as their sole runtime
  requirement; package, native-size, memory, output-size, parity,
  repeatability, and startup gates pass. The report SHA-256 is
  `f32b7c60f19956438023c51cc9c0b07f44ace79c66dff4a43c30fc7cfdcd80b1`.
  Its checked compact receipt is
  `bench/results/backend_qualification/jpeg-rgb8-v1-windows-msvc-7a88e7c.json`.

### R5.3 — correctness and compatibility gate implementation

- [x] Decoder parity uses the same encoded corpus and requires exact canonical
      output for lossless/raw paths or the pinned tolerance for lossy decode.
- [x] A lossless writer is accepted when an independent decoder recovers the
      exact canonical record. Encoded-byte identity is required only where
      frozen deterministic bytes are already part of the contract.
- [x] A lossy writer uses a pinned corpus covering quality, output size,
      metadata, alpha handling, and subsampling, and must be non-inferior under
      the documented parity metric. A smaller or lower-quality output is not a
      valid speed win.
- [x] Predeclare per-profile comparative quality metrics, non-inferiority
      margins versus the retained backend, corpus aggregation/confidence
      rules, and file-size matching bounds before measurement. Both candidates
      passing an older absolute tolerance is not sufficient.
- [x] Malformed/truncated inputs, convention guards, and unsupported features
      retain the same normalized behavior.
- [x] Require the exact declared repeat count across fresh processes and exact
      sink identity where the backend contract permits it.
- [x] Record multi-lane comparison as not applicable for this decision because
      neither selected JPEG API exposes an intra-file lane control.
- [x] Execute the clean full matrix and retain passing compatibility,
      determinism, and repeatability evidence.
- [x] No backend migration was selected, so retained deterministic bytes and
      goldens remain unchanged.
- [x] Existing Python/runtime dependency remains NumPy-only.

For this JPEG decision, neither candidate exposes an intra-file lane control
through the selected API. The frozen policy therefore measures one lane and
records that no many-lane variant exists; it does not infer a threaded result.
CMYK and YCCK remain compatibility-only retained-fallback cells and do not
contribute candidate throughput.

### R5.4 — selection and ledger update

- N/A — no conforming candidate exists to select per profile/direction.
- N/A — no platform winners exist to compare or dispatch.
- N/A — no default switch or three-platform selection commit exists.
- N/A — no superseded backend exists, so a replacement regression workflow
  and scheduled old/new comparison are not installed.
- N/A — no retained backend is removed.
- [x] Record retained, replaced, and rejected candidates in
      `PERFORMANCE_STATUS.toml` and `bench/BASELINE.md`.
- [x] A profile/direction becomes `qualified` only when candidate discovery,
      three-toolchain measurement, correctness, build, and maintenance gates
      are complete. No JPEG row is promoted by this failed result.
- [x] Do not use `native_by_necessity` for this result; the JPEG row remains a
      measured `known_gap`.

R5.4 negative-selection outcome (2026-07-28):

- [x] Record libjpeg-turbo 3.2.0 as rejected for the combined stable default
      in `bench/PERFORMANCE_STATUS.toml` and `bench/BASELINE.md`.
- [x] Retain the repository-owned stb default without a source, ABI, symbol,
      byte-contract, or packaging change.
- [x] Preserve the frozen threshold and raw result; do not reinterpret the
      4.787x/1.782x speed gains as qualification after the q95 quality failure.
- [x] Do not dispatch the user-gated remote workflow because there is no
      conforming candidate or selection commit to validate.

The selection/removal gates above are not applicable because the candidate
failed before selection.
The JPEG performance row remains `known_gap`, with no active candidate and the
evaluated rejection recorded explicitly. This negative decision closes the
current R5 candidate funnel and does not claim that the JPEG gap itself has
been eliminated.

Selected-backend exit: N/A. It applies only to a conforming candidate and an
actual default-selection commit.

R5 negative-candidate exit:

- [x] Focused installed-wheel parity, malformed-input, determinism, and
      backend-isolation tests pass.
- [x] The complete same-run report is bound by a checked receipt that
      records the failed frozen gate without deleting raw samples or changing
      the threshold.
- [x] Full suite, Ruff, ledger/document contracts, paired wheels, and clean
      installed-wheel smoke pass.
- [x] The stable default, public/core surface, ABI, encoded-byte contract, and
      NumPy-only runtime dependency remain unchanged.
- [x] Three-lens review has no unresolved finding.
- [x] The user-gated workflow is not dispatched because there is no
      conforming candidate or selection commit; no remote pass is claimed.

## 10. R6 — close selected default sources

Perform one dependency per commit.

### R6 progress ledger

| Dependency | Selected revision | Repository source | Local build | Local verification | Commit |
|---|---|---:|---:|---:|---|
| miniz | 3.0.2 / `293d4db1b7d0ffee9756d035b9ac6f7431ef8492` | ✅ exact archive files and hashes recorded | ✅ direct hidden static target; no miniz fetch | ✅ local rebuild, parity, strict benchmark, sdist-derived wheel, installed smoke, and three reviews | `dd87233` |
| nlohmann/json | 3.11.3 / `9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03` | ✅ exact 45-header tree and license hashes recorded | ✅ local interface target; no nlohmann/json fetch | ✅ rebuild, parity, strict benchmark, sdist-derived wheel, installed smoke, and three reviews | `e5f705f` |
| zstd | 1.5.6 / `794ea1b0afca0f020f4e57b6732332231fb23c70` | ✅ exact selected library/build files and hashes recorded | ✅ local upstream static target; no zstd fetch | ✅ rebuild, dual-profile SPZ benchmark, strict sweep, exact package, isolated smoke, and three reviews | `ae2122d` |
| fast_float | 6.1.6 / `00c8c7b0d5c722d2212568d915a39ea73b08b973` | ✅ exact nine-header tree and MIT license hashes recorded | ✅ local interface target; no fast_float fetch | ✅ rebuild, parity, strict benchmark, exact package, isolated smoke, and three reviews | `7f24094` |
| LAZperf | 3.4.0 / `b7bbe26109dc986f42d4fc80b8de3d2b6ca634ce` | ✅ exact 47-file tree, pristine/final manifests, and seven-file patch recorded | ✅ explicit hidden static target; no LAZperf fetch | ✅ rebuild, parity, strict benchmark, exact package, isolated smoke, and three reviews | `801190e` |
| libwebp | 1.5.0 / `a4d7a715337ded4451fec90ff8ce79728e04126c` | ✅ exact 203-file core/build closure and notices recorded | ✅ local unmodified upstream CMake/SIMD static target; no libwebp fetch | ✅ rebuild, parity, strict benchmark, exact package, isolated smoke, and three reviews | `8ef2537` |

All six rows satisfy R6.1 and R6.2 in separate green commits. Final build-only
run `30406706115` completes R6.3 across MSVC, GCC 10, and AppleClang; its
downloaded artifacts pass the closure inspection recorded above.

Miniz local evidence at the reviewed tree:

- exact staged upstream-file hashes match `COMMIT.txt`, including the
  99,268-byte release archive SHA-256
  `ada38db0b703a56d3dd6d57bf84a9c5d664921d870d8fea4db153979fb5332c5`;
- editable MSVC rebuild and symbol import pass; affected codec/API parity is
  `160 passed, 1 skipped`, targeted mmap/streaming coverage is `43 passed`,
  and source/build contracts are `17 passed`;
- the complete suite is `3401 passed, 4 skipped`, the exact collection is
  3,405 nodes, Ruff passes, and both diff checks pass;
- the strict 50-codec five-run benchmark passes every retained O4/O5 and
  mmap/sink allocation gate. Its uncommitted JSON is 50,259 bytes with
  SHA-256
  `652c12619b436723c61ffeba81ae11d91a1de71be55d665e2d2c412aaa6b487b`;
- the final 4,478,322-byte sdist contains 428 files, including all six miniz
  intake files and both miniz notices (SHA-256
  `943e785023e4d80472859b7047cff3126a728a00e2b122069d4ffbb645cb938e`);
  its sdist-derived 2,196,335-byte Windows abi3 wheel contains 84 files, one
  extension, no native-source payload, NumPy as its only unconditional
  dependency, all 16 indexed notices, and no FFmpeg/libav package entries
  (SHA-256
  `2788c69ead9a0992bc4b968cdc7ca167de84fc8f52ffafa9ed700e6d39552209`).
  The wheel passes smoke through an isolated installed-package path rather
  than the editable import hook.
- the architecture, test/performance, and platform/package/documentation
  reviews are clear after adding the source-derived ZIP notice, correcting
  stale R6 wording, pinning notice bytes, and strengthening the all-CMake
  local-source contract.

Nlohmann/json local evidence at the reviewed candidate:

- the 110,988-byte official 3.11.3 release archive has SHA-256
  `d6c65aca6b1ed68e7a182f4757257b107ae403032760ed6ef121c9d55e81757d`;
  all 46 selected upstream files—45 multi-header files plus `LICENSE.MIT`—match
  the 5,041-byte `SOURCE_MANIFEST.sha256`, whose SHA-256 is
  `7c67147cb0569a82381f7452ef87085c0fd0195bda96f7db7eeb3bb81df4a88b`;
- the editable MSVC rebuild and native-symbol import pass. The four JSON-backed
  codec suites plus public mmap, streaming, inspection, and partial paths are
  `486 passed`; source/build contracts are `17 passed`;
- the complete suite is unchanged at `3401 passed, 4 skipped`; Ruff and both
  diff checks pass;
- the strict all-50 five-run benchmark passes every retained O4/O5 and
  mmap/sink allocation gate. Its 50,264-byte JSON has SHA-256
  `f486ee74e89290a1f12e84ccb3311fa76b7329616987e6cee17fc9e829e36c68`;
- the 4,622,734-byte sdist contains 477 files, all 48 nlohmann/json source and
  metadata members, byte-validates every selected upstream file against its
  manifest, and includes all 17 indexed notices (SHA-256
  `554efddd55aea7359ad5de9308a1026403ec5ed5142ffdf949a47544de6f11f4`);
  its sdist-derived 2,197,183-byte Windows abi3 wheel contains 85 files, one
  extension, no native-source or build-layout payload, NumPy as its only
  unconditional dependency, all 17 indexed notices, and no FFmpeg/libav
  package entries (SHA-256
  `1716e1a43a06966d10399cee7d500166a7c7489dadf2a872e7cdfba131fb63e7`);
- the isolated installed-wheel smoke imports both Python and native modules
  from the target directory and returns phase `2`. Native inspection reports
  only Python and standard Windows runtime libraries.
- the architecture/correctness, test/performance, and
  platform/package/documentation reviews are clear after correcting the
  selected-file wording to distinguish the 45 headers from `LICENSE.MIT`.

Zstd local evidence at the review candidate:

- the 2,406,875-byte official 1.5.6 release archive has SHA-256
  `8c29e06cf42aacc1eafc4077ae2ec6c6fcb96a626157e0593d5e82a34fd403c1`;
  all 78 selected library/build/license files match the 7,310-byte
  `SOURCE_MANIFEST.sha256`, whose SHA-256 is
  `f94a91b60a5a9b69beb5978d3b58467c60b33eead1d29f12e7e8d9a20ecb5b24`;
- the selected upstream CMake files are stored byte-exact under
  `zstd/cmake/upstream/`, preserving their two-level path from the zstd root
  while avoiding the repository build-output exclusion. The generated MSVC
  target names only repository-contained zstd sources. SceneIO explicitly
  selects compression, decompression, dictionary building, multithreading,
  disabled deprecated APIs, position-independent code, and hidden C symbol
  visibility;
- the editable MSVC rebuild and native-symbol import pass. SPZ parity plus
  public mmap, streaming, inspection, partial, and architecture coverage is
  `205 passed, 1 skipped` after the review corrections; source/build contracts
  are `17 passed`;
- the complete suite is unchanged at `3401 passed, 4 skipped`. A review found
  that the first focused benchmark measured only the default v3 gzip path.
  The corrected harness now defines and validates separate
  `legacy_v3_gzip`/miniz and `ngsp_v4_zstd`/Zstd profiles on the same cloud;
- the confirming strict sweep records 105/769 MB/s encode/decode for v3 and
  257/1,391 MB/s for v4. Both profile signatures and settings are locked, and
  their decoded arrays are identical. The v3 public-path row preserves the
  3.4 MB bytes-versus-zero mmap allocation delta;
- the strict all-50 five-run benchmark passes every retained O4/O5 and
  mmap/sink allocation gate. Its 52,067-byte JSON has SHA-256
  `b3d4666ad09aa60419ca980c658519fcbe72691528fecf3a176f40e965e278d0`;
  the intentional `spz_profiles` result shape has structural SHA-256
  `8f218ff77bcf2ea1e918d4ed164f7184fa2662eb252508c387b5f131a053a8e7`;
- review corrections explicitly pin the selected zstd modules, hide its C
  symbols, and record the v4 SPZ directions as repository-vendored Zstd
  operations while retaining the v3 miniz operations in
  `bench/PERFORMANCE_STATUS.toml`; contracts now lock those choices;
- the exact-index source archive contains 558 files, including all 80 zstd
  source/metadata members, validates all 78 selected upstream files against
  the manifest, and includes all 18 indexed notices. Its sdist-derived Windows
  abi3 wheel contains 86 files, one extension, no native-source or build-layout
  payload, NumPy as its only unconditional dependency, and all 18 notices;
- the isolated installed-wheel smoke imports both Python and native modules
  from the target directory and returns phase `2`. Native inspection reports
  only Python and standard Windows runtime libraries, and the extension
  exports no zstd API symbols;
- the architecture/correctness, test/performance, and
  platform/package/documentation reviews are clear after correcting explicit
  build settings, symbol visibility, backend ownership, and the separate
  v3/miniz versus v4/Zstd benchmark profiles.

fast_float local evidence at the review candidate:

- the 101,727-byte official 6.1.6 tag archive has SHA-256
  `4458aae4b0eb55717968edda42987cabf5f7fc737aee8fede87a70035dba9ab0`;
  its tag resolves to commit
  `00c8c7b0d5c722d2212568d915a39ea73b08b973`;
- all ten selected upstream files—the nine public headers required by
  `fast_float/fast_float.h` plus `LICENSE-MIT`—match the 989-byte
  `SOURCE_MANIFEST.sha256`, whose SHA-256 is
  `dd075e6dfb33eef1eac73af549cda6094b43f6ea64ae3528e1b25034f66767b5`;
- the local CMake target is header-only, exposes only the selected include
  directory, requires C++11 or newer, retains upstream's conditional MSVC
  `/permissive-` consumer option, and replaces the fast_float `FetchContent`
  declaration. Tests, examples, fuzzers, benchmarks, scripts, install/export
  rules, and package configuration are neither stored nor configured;
- the editable MSVC rebuild and native import pass. The text-backed codec and
  native/source contract sweep is `682 passed, 1 skipped`; the complete suite
  remains `3401 passed, 4 skipped`;
- the strict all-50 five-run benchmark passes every retained O4/O5,
  mapped-read, and file-sink gate. Its 52,081-byte JSON has SHA-256
  `e9847667ed9849b2de9832997c59069dd0077e7c6ebfc5bdf293437844d96fca`
  and retains structural projection SHA-256
  `8f218ff77bcf2ea1e918d4ed164f7184fa2662eb252508c387b5f131a053a8e7`;
- representative fast_float-backed decode measurements are 83 MB/s for XYZ,
  81 MB/s for PTS, 115 MB/s for ASCII PLY, 114 MB/s for ASCII PCD,
  204 MB/s for EuRoC state, 313 MB/s for g2o, 369 MB/s for Bundler,
  204 MB/s for BAL, and 362 MB/s for NVM;
- the pre-review package candidate sdist is 5,152,724 bytes with SHA-256
  `cf7042d422b365586771ab8610230dcc617f2ed83e24aa59969cd7e783e3679a`.
  It contains 570 files—including all 12 fast_float source/metadata members
  and all 18 indexed notices—and differs from its then-current 569-file index
  only by generated `PKG-INFO`. Its
  sdist-derived 2,197,947-byte Windows abi3 wheel has SHA-256
  `dd9a639f9cb37c47e88d98f77605c197783298c9a21b57419f12bd9568fb0efd`,
  contains 86 files and one extension, includes all 18 notices, carries no
  native source/build payload, and keeps NumPy as its only unconditional
  dependency;
- isolated installed-wheel smoke imports the package and extension from the
  target directory, exercises a fast_float-backed XYZ read, and completes all
  50 built-in smoke cases at phase `2`. Native inspection reports only Python
  and standard Windows runtime libraries. The unfiltered extension export set
  also contains pre-existing LAZperf/nanobind C++ exports; the following
  single-dependency LAZperf unit owns their visibility correction and contract.
- after the review corrections, the 5,154,142-byte exact-index sdist has
  SHA-256
  `c6f73ae1a8f5f8977cd629f8dd7d8d128a90949471643734a4dbf268d5f0d71a`
  and matches all 569 staged files byte-for-byte with only generated
  `PKG-INFO` added. Its sdist-derived 2,197,511-byte wheel has SHA-256
  `50cdc17531bbd322a58825a04c487e9cacda17d3fa5b07ac33a7ebb2b66127ed`,
  86 files, one extension, all 18 notices, no native-source/build payload,
  NumPy as its only unconditional dependency, and a passing isolated phase-2
  smoke. These hashes bind the exact review snapshot; the post-review
  exact-index package proof is necessarily recorded outside the package so
  that inserting its own hash cannot change the artifact being described.
- the architecture/correctness, test/performance, and
  platform/package/documentation reviews are clear after restoring and locking
  the upstream MSVC conformance option, correcting the extension-export
  wording, and regenerating the exact staged-index package.

LAZperf local evidence at the corrected review snapshot:

- the 4,993,241-byte archive for tag 3.4.0/commit
  `b7bbe26109dc986f42d4fc80b8de3d2b6ca634ce` has SHA-256
  `17df34ca64cc60e107f0c214db4729c54a514df4e32de5bc1b8b7b7c5a805a56`;
- the selected closure is the exact upstream `COPYING` plus the complete
  47-file `cpp/lazperf/**` library/header tree. The 4,546-byte pristine and
  final path-sorted manifests have SHA-256
  `25dec34174ea9ec01899bc7299724819eb94659de264ae1dbce046ff9c7be737`
  and
  `f7811663db8e3af8a8e02f264855da57c1ed34bca7be56f8024a6d272e002ab2`.
  Exactly seven files differ, each carries a prominent SceneIO modification
  notice, and the 13,917-byte reviewable patch has SHA-256
  `d35a90f323511ddb371547c4c420bac6390ef90b498d9ccec244f496a9cceb04`.
  The selected-source notice also restores the Mathias Panzenböck
  `portable_endian` public-domain statement and BSD/MIT/Apache fallback;
- CMake names exactly 15 translation units from the repository source and
  configures a position-independent hidden static target.
  `LAZPERF_VENDORED` propagates to `_core`; the generated project contains no
  `_deps/lazperf-src` path;
- editable rebuild and native-symbol import pass. Focused LAZ/source/build
  coverage is `79 passed`; the complete suite remains
  `3401 passed, 4 skipped`, and Ruff and diff checks pass;
- the strict all-50 five-run benchmark passes every retained O4/O5,
  mapped-read, and file-sink gate. Its 52,069-byte JSON has SHA-256
  `f80ca7015254975f0066df2b157b34b0a3f4c529edc1e25f21d972542c707683`
  and retains structural projection
  `8f218ff77bcf2ea1e918d4ed164f7184fa2662eb252508c387b5f131a053a8e7`.
  LAZ records 64 MB/s encode, 232 MB/s buffer decode, 231 MB/s mapped path
  read, a 14.6 MB versus 0.01 MB traced read-allocation delta, a 0.0006 MB
  file-sink allocation, and a 3.15x partial-read speedup;
- exact staged-index tree `08665e3777dbb218b33183d0e85d05382654d138`
  produces a 5,219,332-byte source archive with SHA-256
  `1b520ffd178aa3eb2509dad20a2e07605b59042a308a7f8a4a308884c36e1900`.
  All 621 staged Git blobs match their archive members byte-for-byte; the
  archive adds only generated `PKG-INFO` and includes all 53 LAZperf
  source/provenance members. Its sdist-derived 2,186,905-byte Windows abi3
  wheel has SHA-256
  `2f231a79bb2490431aea337ce8db93d08291a7b489281d1249287ea4fe045649`,
  contains 87 files, one extension, all 21 license assets, no source/build
  payload, and NumPy as its only unconditional runtime dependency;
- isolated installed-wheel smoke imports both Python and native modules from
  the target directory and completes all 50 built-in cases at phase `2`.
  Native inspection reports only Python and standard Windows runtime
  libraries. The extension export table is reduced from the prior 239 entries
  to 21: `PyInit__core` plus 20 nanobind exception-runtime symbols, with zero
  LAZperf exports;
- the architecture/correctness, test/performance, and
  platform/package/documentation reviews are clear.

The artifact hashes above bind the exact pre-documentation review tree. The
post-review staged-index package is rebuilt and reported outside its own
packaged checklist so the artifact is not required to contain its own hash.

libwebp local evidence at the reviewed candidate:

- the 3,821,241-byte official v1.5.0 archive for commit
  `a4d7a715337ded4451fec90ff8ce79728e04126c` has SHA-256
  `668c9aba45565e24c27e17f7aaf7060a399f7f31dba6c97a044e1feacb930f37`;
- the repository stores the exact 203-file, 2,940,103-byte core-library,
  mux/demux, SIMD, CMake, license, patent-grant, attribution, and release-note
  closure. Its 17,959-byte case-insensitive path-sorted manifest has SHA-256
  `17e0a0e557d3b80e464da8ad5832836d992a7882ec365ff58b33d1fda16f4ba8`.
  No upstream source file is modified;
- CMake configures the repository directory through `EXCLUDE_FROM_ALL`, keeps
  `WEBP_ENABLE_SIMD=ON`, disables tools and optional utilities, and gives every
  linked core target PIC and hidden C visibility. The active `_core` project
  references the local `libwebp/webp` target and contains no
  `_deps/libwebp-src` input;
- editable MSVC rebuild and native-symbol import pass. Focused WebP,
  parallel-worker, image-window, source/build, and performance coverage is
  `59 passed`;
- the strict all-50 five-run benchmark passes every retained O4/O5,
  mapped-read, and file-sink gate. Its 52,081-byte JSON has SHA-256
  `b719008899536b47900ed20f658200f1311f4426ced03899e605aa5898414829`
  and retains structural projection
  `8f218ff77bcf2ea1e918d4ed164f7184fa2662eb252508c387b5f131a053a8e7`.
  WebP measures 35 MB/s write, 285 MB/s buffer decode, 258 MB/s mapped-path
  read, a 2.70x balanced-config gain over the retained effort-100 control, a
  measured worker-on gain, and a 2.01x lossless-window speedup;
- the complete suite is `3401 passed, 4 skipped`; Ruff and both diff checks
  pass;
- exact staged-index tree `d2fc4417cd9951c948983f7b37abad036b4c22ca`
  contains 827 files and produces a 5,817,872-byte source archive with SHA-256
  `ee9f54a73f636aabeea2ec4b6acb7a127973c01a9aee5881007508548fd5c93d`.
  Every staged Git blob matches its archive member byte-for-byte, and generated
  `PKG-INFO` is the sole extra file;
- the sdist-derived 2,187,869-byte Windows abi3 wheel has SHA-256
  `6ae7f9a614b81360d1e61429c1b09186bc1bfd0aeb9b4ef329fa298e5c8c9f7c`.
  It contains 88 files, one extension, all 22 license assets, no
  source/build/development payload, NumPy as its only unconditional runtime
  dependency, and no FFmpeg/libav package entry. Isolated installed smoke
  imports both modules from the target directory and completes all 50 built-in
  cases at phase `2`;
- the sdist-generated WebP project contains only repository source paths.
  Native inspection reports only Python and standard Windows runtime
  libraries; `_core` has 21 exports—`PyInit__core` plus 20 nanobind
  exception-runtime symbols—with zero libwebp, SharpYUV, or LAZperf exports;
- the architecture/correctness, test/performance, and
  platform/package/documentation reviews are clear.

The artifact hashes above bind the exact pre-documentation review tree. The
post-review staged-index package is rebuilt and reported outside its own
packaged checklist so the artifact is not required to contain its own hash.

Shared disconnected-source/package diagnostic evidence at exact commit
`8ef25375cc9b47a8e7b67f11d4714ab88f4e4d82`:

- a clean 827-file commit export with fresh source, build, distribution, and
  installation directories built with `PIP_NO_INDEX=1`, `UV_OFFLINE=1`,
  `UV_NO_INDEX=1`, disabled PEP 517 isolation, preinstalled pinned build
  tools, and `FETCHCONTENT_FULLY_DISCONNECTED=ON`;
- the sdist was built first, then the Windows cp312-abi3 wheel was built only
  from its unpacked source. The 5,818,092-byte, 828-member sdist has SHA-256
  `674423c13196e1a2aee7c67c6c85877684bf4c6f0573b387679fe24058aad466`;
  all 827 commit blobs match and generated `PKG-INFO` is the sole additional
  member;
- the superseded 2,187,867-byte, 88-member wheel has SHA-256
  `f045b52e334298ad7cbdf336c70356140df5b1a05ceace42954b3f313ccf9595`.
  It contains one `_core` extension, all 22 distribution license assets, no
  source/build payload or additional native library, and NumPy is its sole
  unconditional runtime requirement. Although its filename was tagged
  `cp312-abi3`, its `_core.cp312-win_amd64.pyd` member linked `python312.dll`;
  it is not stable-ABI package evidence;
- isolated installed smoke returns phase `2` for all 50 built-ins. Windows
  inspection reports only Python and standard Windows runtime libraries, and
  the extension exports 21 names—`PyInit__core` plus 20 nanobind exception
  runtime names—with no libwebp, SharpYUV, or LAZperf exports. This remains a
  valid Python 3.12 functional result, not an ABI result;
- implementation/build/package scanning finds no FFmpeg or libav component.
  Those projects remain reference-only and are not part of SceneIO source,
  build logic, metadata, or artifacts;
- the final local five-run strict sweep passes every retained O4/O5,
  mapped-read, and file-sink gate. Its 52,092-byte JSON has SHA-256
  `0b06954e0d31dea6e34a9ae796a20fe9cd4ffb52bffea4ab1e288cd397a8eb43`
  and structural projection
  `8f218ff77bcf2ea1e918d4ed164f7184fa2662eb252508c387b5f131a053a8e7`;
- `tools/verify_distribution.py` turns the license/runtime/native-payload
  assertions into a reusable stdlib-only gate. It compares every Git-tracked
  source byte from the checkout with the sdist, permits only generated
  `PKG-INFO`, compares every indexed license and Python runtime byte, and
  applies an explicit wheel-member inventory around the one `_core` extension.
  It also requires the project name/version plus `cp312-abi3` filename tags,
  exact Windows/manylinux2014/macOS platform tags, matching internal `WHEEL`
  tags, singleton project identity and `Root-Is-Purelib: false` fields, and
  either one platform artifact or the exact three-platform matrix.
  `tools/r6-wheelhouse.lock` pins and hashes the four build tools plus the three
  CPython 3.12 platform NumPy wheels. The sdist producer pins `uv` 0.8.6. The
  prepared `publish.yml` verifies the repository-to-sdist closure, publishes
  its inventory separately, verifies one sdist hash, unpacks that artifact for
  each wheel job, builds with package-index access disabled, runs all-50 smoke,
  and performs per-wheel plus combined inventory checks. Each platform job
  accepts its one expected wheel, while the combined job invokes the strict
  matrix mode and requires exactly one Windows, manylinux, and macOS wheel;
- the corrected CMake graph requires `Development.SABIModule`, fails configure
  unless `Python::SABIModule` exists, and checks that `_core` selected
  `nanobind-static-abi3` plus `NB_SUFFIX_S`. A clean MSVC rebuild emits
  `_core.pyd`, compiles with `Py_LIMITED_API=0x030C0000`, links `python3.lib`,
  imports against `python3.dll`, and exports `PyInit__core`. A separate Ubuntu
  22.04/CMake 3.22/GCC 11 rebuild exercises scikit-build-core’s FindPython
  backport, emits `_core.abi3.so`, has no libpython dependency, exports
  `PyInit__core`, imports, and passes the native-build architecture suite.
  This Linux check confirms the corrected Unix build path but does not replace
  the user-gated manylinux2014 GCC 10 or AppleClang jobs;
- a fresh five-run all-50 benchmark against the corrected build passes every
  retained O4/O5, mapped-read, and file-sink gate. The 52,064-byte result has
  SHA-256
  `19a379668f6180dc8570d5dbc83b0ca7267e93058f5c0749fb658819c14ed307`
  and retains structural projection
  `8f218ff77bcf2ea1e918d4ed164f7184fa2662eb252508c387b5f131a053a8e7`;
- the complete local suite is `3446 passed, 4 skipped`; exact collection is
  3,450 nodes with normalized node-id SHA-256
  `1bf1ff9b85ef0ac8f1ad62d26e872666deff8594434feb045f8a03feff11583e`.
  Ruff and both diff checks pass. The final corrected staged tree is rebuilt
  from an exact export after review, with its non-self-referential artifact
  hashes and installed-smoke result retained in the commit record;
- exact commit `3747447` passed every automatic portability/codec job,
  including manylinux2014 GCC 10, but its main job exposed a stale benchmark
  contract: the exact CI command
  `--runs 1 --scale 0.001 --skip-oracles` produces structural projection
  `97c98367e8ea602e9b9c1682b8c6ef1ca8fd483a66b233cd64dbc5976d0c7948`
  on both Windows and hosted Linux, while the contract incorrectly held the
  full-size strict-run projection
  `8f218ff77bcf2ea1e918d4ed164f7184fa2662eb252508c387b5f131a053a8e7`.
  The smoke/family contracts now bind the scale-0.001 projection; the retained
  five-run strict evidence and its projection remain unchanged. Correction
  commit `7d51423` passes exact-commit normal run
  [30390986854](https://github.com/SceneAPI/SceneIO/actions/runs/30390986854):
  the corrected deterministic structure step, complete suite, five-run
  performance guard, every three-OS codec shard, and pinned GCC 10 portability
  are green. Compiler-instrumented run
  [30390986672](https://github.com/SceneAPI/SceneIO/actions/runs/30390986672)
  passes the full ASan/UBSan suite and LSan lifetime shard. These automatic
  runs do not replace the user-gated build-only package matrix.

### R6.1 — provenance and source intake

- [x] Store the exact selected source under
      `src/cpp/third_party/<project>/`.
- [x] Add `COMMIT.txt` with upstream URL, tag/SHA, archive/source hashes,
      source files built, disabled components, build options, and local
      patches.
- [x] Copy the exact upstream license/notice into `LICENSES/` and update its
      index.
- [x] Preserve local changes as reviewable patch files or narrowly marked
      source edits.
- [x] Disable tools, examples, tests, shared libraries, install rules, and
      unused codecs.

### R6.2 — local-source build switch

- [x] Switch only that dependency from `FetchContent` to the in-tree source.
- [x] Verify compile definitions, hidden visibility, static linkage, and
      enabled source files match the selected benchmark build.
- [x] Prove focused codec goldens/parity and benchmark results remain within
      the recorded variance.
- [x] Run the complete rebuild/test/lint/wheel smoke gate.

### R6.3 — offline and package closure

- [x] Start from a clean checkout and empty CMake/download caches. Either
      disable PEP 517 build isolation and use pinned preinstalled build tools,
      or provide a locked, pre-populated `PIP_FIND_LINKS` wheelhouse inside
      every build container.
- [x] Set `PIP_NO_INDEX=1`, configure with
      `FETCHCONTENT_FULLY_DISCONNECTED=ON`, and deny network access during the
      native-source build.
- [x] Build the sdist first. Make every wheel job depend on that sdist,
      download and unpack the exact artifact, and build its wheel from the
      unpacked sdist rather than a fresh repository checkout.
- [x] Inspect the wheel for unexpected headers, static archives, build trees,
      undeclared DLLs/shared objects, or duplicate native libraries.
- [x] Verify NumPy remains the only unconditional runtime dependency.
- [x] Assert the root license and every file indexed by `LICENSES/README.md`
      are present in both the sdist and every wheel.
- [x] Verify no FFmpeg/libav source, symbol, library, executable, build hook,
      or package metadata entered the repository or wheel.

R6 exits when:

- [x] all selected default sources are repository-contained;
- [x] no default CMake configure path downloads native source;
- [x] every dependency has current provenance/license/patch metadata;
- [x] native-source-offline MSVC, manylinux2014 GCC 10, and AppleClang
      sdist-to-wheel builds pass (NumPy is separately pre-provisioned for
      installed-wheel smoke, not required to compile the package);
- [x] all 50 codecs pass the installed-wheel smoke locally; the exact same
      manifest-driven command is mandatory in each hosted wheel job.

## 11. Documentation checklist for every unit

Review every surface below for each unit, update only the surfaces affected by
the change, and always update this checklist. Unrelated documents do not
receive churn solely to touch every file.

- [x] `docs/format_coverage.md`: current capability and validation status.
- [x] `docs/coverage_roadmap.md`: declared destination/policy only.
- [x] `docs/format_gap_implementation_plan.md`: active queue and package
      status.
- [x] `docs/repository_organization_plan.md`: architecture/performance gate
      status.
- [x] This checklist: completed boxes, commit SHA, test counts, benchmark
      evidence, workflow links, and remaining blockers.
- [x] `docs/core_architecture.md`: actual current layout, not the future layout.
- [x] `docs/io_optimization_plan.md`: historical O0-O5 facts plus current
      qualification distinction.
- [x] `bench/BASELINE.md` and `bench/PERFORMANCE_STATUS.toml`: measurements and
      backend state.
- [x] `README.md`: reviewed; no public command or API changed in this closure,
      so no edit is required.
- [x] `src/cpp/third_party/*/COMMIT.txt` and `LICENSES/`: provenance,
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
.venv/Scripts/python.exe bench/bench_io.py --runs 5 --strict-oracles --require-o4-gains --require-o5-inspect-gains --require-o5-partial-gains
.venv/Scripts/python.exe -m sceneio._wheel_smoke
```

Additional unit-specific commands and fixture hashes are recorded in the
commit and this checklist. A near-threshold or noisy benchmark is rerun with
more samples; it is not rounded into a claimed win.

## 13. Stage exit and user-gated remote validation

Local exit:

- [x] N0 and R1-R6 are complete in green commits.
- [x] Worktree is clean and all authoritative documents agree.
- [x] Full local MSVC suite, Ruff, 50-codec benchmark guard, sdist/wheel, and
      NumPy-only smoke pass.
- [x] The user-directed lean closure policy accepts the verified current
      backends as the R6 release baseline. The 124 provisional rows remain an
      explicit post-R6 optimization backlog rather than 124 release blockers;
      no `qualified` claim is inferred. The two JPEG `known_gap` rows are
      explained by the rejected libjpeg-turbo comparison.
- [x] Default native builds are offline from repository-contained source.

Remote validation checkpoints, only after explicit user authorization:

- [x] At N0, push the reviewed candidate and require green normal,
      instrumented, and focused three-OS portability workflows at the exact
      SHA.
- N/A for the current R5 result — no backend was selected. A future selection
  must dispatch the nonpublishing old/new A/B matrix on MSVC, manylinux2014
  GCC 10, and AppleClang.
- [x] At final R6 exit, push the reviewed branch and dispatch the build-only
      `publish.yml` workflow. Its wheel jobs consume the exact sdist produced
      by its sdist job.
- [x] Download and inspect manylinux2014 x86-64, macOS arm64, Windows amd64
      abi3 wheels, plus the sdist.
- [x] Record workflow URLs, artifact hashes, wheel tags, dependency closure,
      installed capabilities, and smoke results.
- [x] Do not create or push a release tag during validation.
- [x] Keep PyPI trusted-publisher/environment re-verification, tagging, and
      publication outside R6. They remain explicit user-controlled release
      actions.
- [x] Obtain one final three-lens review and commit the closure record; do not
      start another candidate sweep or format wave first.

This stage is validated. The format queue resumed with animation-capable
`ImageSequence`, animated WebP, and APNG; RTMV is next.

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

## 15. COLMAP ecosystem closure

The user-owned `colmap_mod` repository was audited at the original
database/dense pin `de15b08a2dba98b55d6ddfb7cedac147838afbb4` and the compact
adapter pin `a3cfdd784d16a493878877f445fd1e27333fd8fc` by three independent
agents. The
complete matrix and lean boundary are in
[`colmap_ecosystem_coverage.md`](colmap_ecosystem_coverage.md). Encoded video is
reference-only: no FFmpeg/libav implementation or runtime/build dependency is
permitted.

### C0 - modern sparse models

- [x] Preserve paired binary `rigs.bin`/`frames.bin` and legacy absence.
- [x] Preserve paired text `rigs.txt`/`frames.txt` and legacy absence.
- [x] Expose lossless rig/frame SoA and CSR views from `Reconstruction`.
- [x] Support camera models 0-17.
- [x] Replace output-sized binary strings with a bounded direct-file writer.
- [x] Prove modern five-file byte identity against pycolmap 4.1.1.
- [x] Add multi-sensor, pose-present/absent, paired-file, legacy-inventory,
      all-camera-model, conversion-loss, and fork-sidecar refusal tests.
- [x] Add COLMAP and OpsiClear attribution records.
- [x] Run full pytest, Ruff, diff check, benchmark, and wheel smoke.
- [x] Complete the three-agent final review and resolve every finding.
- [x] Commit and push the green C0 implementation at `801bd77`.
- [x] Run the nonpublishing MSVC/GCC10/AppleClang validation at exact
      correction commit `7046761`.

Local C0 evidence for pushed implementation commit `801bd77` on 2026-07-28:

- complete suite: `3573 passed, 4 skipped`; focused closure gate:
  `197 passed`;
- Ruff, `git diff --check`, editable wheel smoke (`2`), collection contract,
  and license inventory pass;
- legacy direct writer: 1,058 MB/s median, 2.20x the pre-C0 writer; modern
  five-file writer: 286 MB/s median; the fresh-child RSS scaling guard passes;
- final independent reviews are clear: Ampere
  (`lean_r6_arch_review`), Epicurus (`lean_r6_test_review`), and Lagrange
  (`lean_r6_platform_docs_review`).

Remote C0 evidence:

- [standard CI run 30421438904](https://github.com/SceneAPI/SceneIO/actions/runs/30421438904)
  passed all 11 jobs at `7046761`;
- [instrumented run 30421438926](https://github.com/SceneAPI/SceneIO/actions/runs/30421438926)
  passed the full ASan/UBSan suite and lifetime job;
- [nonpublishing distribution run 30422291891](https://github.com/SceneAPI/SceneIO/actions/runs/30422291891)
  passed its exact source archive, three platform wheels, and combined
  inventory; its PyPI job was skipped;
- source, macOS, Windows, and manylinux artifact SHA-256 digests are recorded
  in [`colmap_ecosystem_coverage.md`](colmap_ecosystem_coverage.md).

### Remaining lean closure

- [x] C1: exact stock 3.13, stock 4.1.1, current-upstream, and current-MAXX
      database profiles with complete typed field preservation and safe
      in-place behavior.
  - [x] C1a: freeze the four exact profile identities, compare complete
        normalized SQLite structure rather than version alone, expose
        profile/application identity on inspection and decoded records, and
        correct the Python schema contract. Treat migration-derived MAXX
        pre-ownership databases as legacy until C4's import classifier.
  - [x] C1b: recovered `camera1`/`camera2` payloads. Preserve SQL NULL
        independently for each endpoint, expose typed `Camera` values and
        prior-focal flags on `MatchGraph`, and keep the legacy writer guarded
        until C1e emits the exact current profile.
  - [x] C1c: populated stock rigs, frames, frame data, and both stock
        pose-prior layouts.
  - [x] C1d: extended MAXX pose priors plus
        descriptor/color/score/provenance/marker/quality/source fields.
  - [x] C1e: exact selected-profile writers and explicit conversion reports.
- [x] C2 implementation: COLMAP MVS depth/normal matrices, consistency graphs,
      fused visibility, canonical workspace/config access, PMVS/CMP projection
      inventories, raw-domain PMVS visibility, and Bundler image-name
      companions; Gipuma DMB remains distinct.
  - [x] Four repo-owned native codecs with mmap, direct sinks, inspection,
        bounded depth/normal windows, independent goldens, and benchmark rows.
  - [x] Lazy `sceneio.colmap_mvs` adapter with no encoded-media decoding.
  - [x] Cross-file dimension, MVS-index-domain, and fused point-count checks.
  - [x] Record the final complete local gate, benchmark confirmation, and
        three-review sign-off at the C2 commit.
  - [x] Run automatic CI and the user-triggered nonpublishing three-platform
        package validation on the exact final tree containing C2; packaged
        source `2253e0f` passes runs `30469273173`, `30469271293`, and
        `30470889876`.
- [x] C3 implementation: marker/time/point-frame/ChArUco sidecars,
      rig/pair/cap/feature/match/Sim3 text, MappingInput v1/v2, and MegaLoc
      adapters. Bundler list support was already complete in C2.
  - [x] Keep the standard sparse registry route guarded; require the explicit
        `sceneio.colmap` extended adapter to own every companion.
  - [x] Map MappingInput and MegaLoc numeric payloads and retain array
        lifetime without whole-file Python copies.
  - [x] Stream atomic writes and pin exact independent binary/text/JSON
        fixtures, malformed extents, references, dtypes, and conventions.
  - [x] Add the focused million-row performance/memory baseline.
  - [x] Run the complete local gate and final three-review pass.
- [x] C4 classification: public API/docs/benchmark/license coverage and a
      row-by-row decision for every audited surface.
  - [x] Keep TIFF and EXIF/XMP as optional generic image/metadata work rather
        than COLMAP closure dependencies.
  - [x] Classify lossy CAM/Recon3D as optional write helpers and VRML as
        visualization outside closure.
  - [x] Keep project documents, runtime engines, retrieval indices, reports,
        caches, and encoded containers outside closure.
  - [x] Run the exact-tree nonpublishing package validation after the pushed
        commit. Release run `30470889876` passes with publication skipped;
        release/tag/publication remain user-triggered.

Runtime engines, solver logs, reports, decoded/staged caches, and encoded-video
implementations do not become core codecs. This is the explicit stop condition
that keeps full ecosystem closure finite.

### C3/C4 final local evidence (2026-07-29)

- The exact collection contract contains 3,879 normalized nodes with SHA-256
  `39fe1dc507ed2faea06a75dcc823515ff550dfa742813b89cdcd24a7584ad4f6`.
- The complete suite passes 3,874 tests with five documented
  optional/platform skips; the COLMAP adapter suite passes 38 tests and the
  focused closure gate passes 131 tests.
- The editable native build, installed-wheel smoke (`__phase__ == 2`), Ruff,
  and `git diff --check` pass.
- The committed benchmark baseline proves mapped reads without a whole-file
  Python allocation and atomic streaming writes for the two large compact
  transports.
- The first automatic run exposed a Linux RSS allowance mismatch and
  platform-dependent SOG/catalog bytes. The correction pins exact
  consistency-reader ownership, uses a mapped-input-plus-owned-vector RSS
  bound, and makes SOG metadata deterministic through an attributed
  repository-contained transform. Windows and Ubuntu local reproductions
  agree exactly; the 132-test correction sweep and the final 143-test
  architecture review sweep pass.
- Ampere, Epicurus, and Lagrange signed off the final architecture,
  correctness/test, and platform/documentation correction. The exact SOG
  composite source identity and historical platform tuples are pinned, and
  the measured 24-byte-per-point cache tradeoff is explicit.
- Pushed commit `952bb8d` passes the pinned GCC 10 job plus all Windows,
  Ubuntu, and macOS codec-family lanes in run `30467712842`. Its comprehensive
  job exposed only a stale evidence contract: the current benchmark produced
  54 rows while the comparator still required the historical 50. The
  uploaded Ubuntu capture and a new local MSVC capture have identical
  normalized structural SHA-256
  `fd3cf4a663e737971526afe5884f229237630a0f126b21a1c8ffcde9a6015e4e`.
  The active contract now pins those 54 rows while historical R2/R3 contracts
  remain unchanged.
- Final source `2253e0f` passes normal run `30469273173`, including the
  complete suite, all platform lanes, exact 54-row structure, and retained
  performance guard. Instrumented run `30469271293` passes both jobs.
  Nonpublishing release run `30470889876` passes exact-sdist closure, MSVC,
  manylinux2014 GCC 10, AppleClang/ARM64 wheel builds and installed smokes,
  and combined inventory; the publication job is skipped.
- The sdist SHA-256 is
  `3bffc64b75ea751617923f19ca6f6935bd433dd23882af0ca4f1bc26a62cf826`.
  macOS, manylinux2014, and Windows wheel SHA-256 values are
  `779ff0db0bc516b8b05dfb67a0fe81dc9ba53f556204575b34a7ac4e1b8aaf0a`,
  `ece92774dc88cc5c657bc1215044d34f70958b78e6b7f66892ea21464baa2506`,
  and
  `80f2a75aa7ac2f7a0a3b97291c7019122d2880d0068b89caaeab9bb09f290b6b`.
  All contain 27 attribution assets; wheels retain NumPy as the sole runtime
  requirement and the downloaded exact matrix passes independent inventory
  verification.
- This documentation-only closure record names the already validated
  packaged source and does not recursively require a second package matrix.
  Release, tag, and publication stay user-triggered.

### C2 implementation checkpoint (2026-07-29)

- [x] Registry/build ownership expands from 50/40/16 to 54 built-ins,
      41 codec-registration functions, and 17 record-registration functions
      through the new `dense` family.
- [x] `DepthMap` gains additive `depth_convention="camera_z"` and
      `invalid_policy="nonpositive"` vocabulary without weakening writers for
      formats that cannot preserve those conventions.
- [x] `NormalMap`, `ConsistencyGraph`, and `PointVisibility` expose owned
      zero-copy NumPy views and explicit coordinate/index conventions.
- [x] Exact little-endian readers/writers cover COLMAP depth, normal,
      consistency, and fused visibility payloads. Matrix dimensions, checked
      products, counts, coordinates, index wire domains, truncation, and
      trailing bytes are guarded before a record is returned.
- [x] All four formats participate in the 48-buffer differential, mmap,
      streaming, inspection, benchmark-qualification, native-inventory,
      installed-wheel-smoke, and repository-coverage contracts.
- [x] Canonical COLMAP workspaces retain legacy sparse image order, while
      modern rig/frame models derive the MVS positional table from registered
      frame/camera data order exactly as COLMAP does. Config order and nested
      image names are preserved, and dense payloads decode only on demand.
- [x] PMVS and CMP-MVS adapters inventory only numbered encoded-media paths
      and 3x4 `CONTOUR` projection text. PMVS `vis.dat` values are preserved
      in a declared raw domain because the authorized producer and consumer
      assign them different meanings.
- [x] No new native/runtime dependency, system library, or encoded-media
      implementation is added. NumPy remains the sole Python runtime
      dependency.
- [x] Final review corrections centralize identical reader/factory/writer
      entry and link bounds, perform checked encoded-size arithmetic before
      addition, replace payload-maximum decoder reservations with a validating
      exact-count pass, and release the GIL through all four pure native
      encodes while reacquiring only for sink emission.
- [x] PMVS raw visibility uses a two-pass fixed-chunk numeric scanner and
      chunked row writer, rejects COLMAP's invalid uint32 image sentinel, and
      retains all other raw-domain values. Its permutation check uses a compact
      chunked NumPy bitmap rather than boxed Python integers. Bundler-profile
      PMVS workspaces no longer require raw-PMVS projection/visibility
      companions and require the bundle image count to match `visualize`.
- [x] Patch-match parsing accepts the upstream comma/semicolon separators and
      skips empty repeated/trailing fields like upstream, while rejecting
      zero-source auto limits, duplicates, and reference-as-source problems
      before writing.
- [x] Benchmark qualification is cross-differential before timing: native and
      independent bytes must match, and both cross-decode directions must
      match the fixture for every dense format.
- [x] The final 3,832-node local gate passes 3,827 tests with five documented
      optional/platform skips. Ruff, `git diff --check`, installed-extension
      smoke, the independent-oracle benchmark, and all three reviews are
      clear. The final three-run sample records 3.47-57.96 GB/s core reads,
      2.17-3.33 GB/s mapped reads, 0.85-1.70 GB/s direct sinks, and no
      output-sized traced allocation on any sink.

C1b local evidence on 2026-07-29:

- the current-upstream `camera1`/`camera2` layout is decoded explicitly as
  little-endian `u32 id`, `i32 model`, `u64 width`, `u64 height`, `u8 prior`,
  `u64 parameter_count`, then `float64 parameters`;
- full and indexed pair reads agree exactly, SQL NULL remains distinct from a
  present camera, and returned camera parameter views retain their owner;
- the record/factory accepts endpoint-local `Camera | None` values and the
  producer's full non-sentinel uint32-id/positive-uint64-dimension domain;
- independent `struct` fixtures cover valid endpoint cameras plus truncated,
  trailing, wrong-type, invalid-flag, model/count, dimension, and non-finite
  cases; the input database handle is released on every rejected case;
- legacy/core database profiles continue to refuse field-dropping writes until
  exact-profile writers land in C1e;
- the unchanged legacy-fixture regression benchmark records 1,137 MB/s full
  read, 154 MB/s direct write, 1.81 ms inspection, and 0.59-0.60 ms indexed
  selectors with no Python-sized staging allocation; the dedicated current
  profile tests, not that legacy row, prove recovered-camera behavior;
- complete local validation covers 3,620 tests: 3,616 passed and four skips;
  the focused
  gate passes 24 tests, Ruff and wheel smoke pass, and all three independent
  review lenses report no remaining blocker after their findings were fixed.

C1c implementation and release checklist:

- [x] Add public nested `ColmapRigFrameSet` and `ColmapPosePriorSet` records
      without conflating database frames with posed sparse-reconstruction
      frames.
- [x] Decode populated stock 3.13, 4.1.1, and current rig/frame tables and
      their image-linked/generalized pose-prior layouts.
- [x] Preserve SQL NULL separately from exact-size float64 BLOBs, including
      signed zero and producer NaN payload bits; expose covariance in logical
      row-major order after an explicit Eigen column-major wire transpose.
- [x] Validate non-sentinel uint32 rig/frame/sensor/prior IDs, non-negative
      signed-SQLite-range uint64 data IDs, enum codes, CSR structure, rig
      ownership, frame membership, quaternion
      normalization, exact BLOB sizes/types, and legacy image/camera links.
- [x] Keep modern orphan prior correlations representable because the stock
      schema has no foreign key; retain exact triple uniqueness.
- [x] Keep image/pair selectors local while full reads validate all companion
      rows; cover rejected-row handle release and nested-array lifetime.
- [x] Extend low-level and public inspection with companion counts and the
      prior layout without decoding BLOBs.
- [x] Re-export both records, update public symbol/snapshot/wheel contracts,
      and guard the legacy writer before destination creation or mutation.
- [x] Keep every populated MAXX pose-prior row guarded until C1d and every
      exact-profile write guarded until C1e.
- [x] Record final full-suite, collection, benchmark, wheel, Ruff, diff,
      three-review, and commit evidence below.

C1c final local evidence on 2026-07-29:

- the exact collection is 3,659 nodes with sorted normalized SHA-256
  `d98dd314db7a05ab87d392864988de8a7fab52cde37605216b121af6e9ca2d6d`;
- the complete suite passes 3,655 tests with four documented skips; the final
  focused codec suite passes 127 tests with the one expected Windows filename
  skip, and the assembly/compatibility/reconstruction gate passes 95 tests;
- the unchanged 9.9 MB legacy benchmark fixture measures 1,092 MB/s full
  read, 166 MB/s direct write, 1.823 ms inspection, 0.784 ms image selection,
  and 0.735 ms pair selection, with no Python-sized staging allocation;
- wheel smoke, Ruff, diff checks, and the public compatibility snapshots pass;
- Ampere, Epicurus, and Lagrange signed off the lifetime/ABI, correctness and
  test-soundness, and platform/public-API/documentation lenses after the
  permanent regression assertions were completed;
- the green C1c commit includes the required co-author trailer. This paragraph
  remains local evidence for that commit; the later final-tree runs
  `30469271293` and `30470889876` validate the accumulated C1c behavior under
  instrumentation and across all three package toolchains.

C1d implementation checklist:

- [x] Add owned nested marker, metadata-only video, and MAXX ownership records
      with zero-copy views and explicit presence arrays.
- [x] Decode all five descriptor wire dtypes with independent dtype, logical
      dimension, and extractor-name SQL presence.
- [x] Decode keypoint colors, image quality, match scores, raw pair provenance
      flags, and provenance-only pairs without inventing endpoints.
- [x] Decode extended pose rotations and 3x3/6x6 covariance matrices with
      explicit XYZW/cam-from-world, variable-order, storage, and unit tags.
- [x] Preserve marker optional BLOB bits, SQL sentinels, projection metadata,
      video NULL-versus-empty strings, PTS values, and independent frame/image
      time IDs. Keep source paths inert and metadata-only.
- [x] Extend full/indexed reads and metadata-only inspection; prove selected
      reads ignore unrelated malformed BLOBs.
- [x] Add exact layout checks, aggregate relationships, handle-release and
      nested-array lifetime tests, public exports/constants, wheel smoke, and
      compatibility fingerprints.
- [x] Refuse every C1d field from the legacy writer before destination creation
      or mutation; leave exact profile emission explicitly to C1e.
- [x] Record final benchmark, full-suite, Ruff, diff, wheel, collection, and
      three-review evidence after the implementation stabilizes.
- [x] Run remote instrumentation and three-toolchain/package validation on the
      exact final tree containing C1d. Runs `30469271293` and `30470889876`
      pass at packaged source `2253e0f`.

C1d final local evidence on 2026-07-29:

- the exact collection is 3,732 nodes with sorted normalized SHA-256
  `8bff7ec31351760721181e4f1314ade1ba8438c26b08bb4090b8aebf93101368`;
  the complete suite passes 3,727 tests with five documented skips;
- the final focused codec/contract/architecture gate passes 286 tests with two
  expected skips. The expanded matrix includes frozen de15 DDL, 41 malformed
  row cases, selected-versus-unselected partial failures, 49 retained ndarray
  paths, nine independent writer guards, and stale MAXX destination cleanup;
- the three-run 9.9 MB database benchmark measures 1,067 MB/s full/path read,
  158 MB/s direct write, 2.192 ms metadata inspection, 0.999 ms image
  selection, and 0.949 ms pair selection. Mapped reads and direct writes add
  no payload-sized traced Python allocation; inspection is 4.12x faster and
  partial reads are 9.05x/9.53x faster than full decode;
- Ruff and diff checks pass. A wheel rebuilt from the generated source
  archive installs in a clean NumPy-only CPython 3.12 environment, completes
  the 50-codec installed-wheel smoke with result `2`, and passes distribution
  inventory verification;
- Ampere, Epicurus, and Lagrange signed off the format/architecture,
  lifetime/test, and platform/public/documentation reviews after their
  findings were corrected;
- the locally installed `colmap_mod` binding identifies itself as
  `a3cfdd784`, not the pinned de15 producer. Therefore no live exact-de15
  producer result is claimed; frozen pinned DDL and independently constructed
  row bytes remain the local oracle until an exact producer build is supplied.

C1e exact-writer implementation checklist:

- [x] Execute the frozen 3.13, 4.1.1, current, or MAXX DDL verbatim and set
      the profile's fixed application/user identity.
- [x] Write every represented camera, image, feature, match, rig/frame,
      pose-prior, recovered-camera, MAXX descriptor/score/provenance,
      marker/projection, metadata-only video/frame, quality, and ownership
      row with the exact wire layout and SQL presence state.
- [x] Transpose row-major public 3x3/6x6 covariance arrays back to the
      producer's column-major SQLite BLOB order; keep F/E/H row-major and
      recovered-camera fields explicitly little-endian.
- [x] Analyze profile representability before filesystem inspection,
      including fixed descriptor rules, pose layout, recovered cameras,
      MAXX ownership, and every uint64-to-SQLite domain bound.
- [x] Add immutable public conversion reports and explicit-profile writes;
      preserve a decoded exact profile through ordinary public writes while
      retaining the constructed-record hybrid compatibility route.
- [x] Reject unrepresented tables, views, triggers, and indexes before
      mutation; validate allowed indexes by table, uniqueness, ordered
      columns, collation, and shape; re-identify canonical schema, ownership,
      PRAGMAs, foreign keys, and SQLite integrity before commit.
- [x] Reject NaN in SQL REAL fields where SQLite would otherwise turn a
      represented value into NULL; retain representable positive and negative
      infinity where the source contract permits it.
- [x] Prove new/existing destination rollback at schema, row, and
      post-verification stages, with no new-file or SQLite-sidecar residue.
- [x] Differentially round-trip populated independent fixtures for all four
      profiles and verify full, indexed, inspection, schema, scalar, SQL
      presence, BLOB, source-immutability, and conversion-refusal behavior.
- [x] Extend installed-wheel smoke and the benchmark harness with exact
      profile selection, including MAXX without any new runtime dependency.
- [x] Record the exactness boundary: canonical present-empty dynamic BLOBs,
      producer-semantic float32 retrieval scores, and no historical SQLite
      page/sequence-state promise.
- [x] Move migration-derived pre-ownership classification explicitly to C4;
      do not label an unknown schema during exact writing.
- [x] Run remote instrumentation plus Linux/macOS/Windows package validation
      on the exact final tree containing C1e. Runs `30469271293` and
      `30470889876` pass at packaged source `2253e0f`; publication remains a
      separate user-triggered action.

C1e local evidence on 2026-07-29:

- populated same-profile round-trips pass for 3.13, 4.1.1, current, and MAXX,
  including all C1b-C1d companion fields and exact structural inspection;
- the focused database suite collects 222 nodes and passes with two documented
  optional producer/platform skips after public API, full refusal-matrix,
  SQL-presence mutation, structural-index, unknown-table, and three-stage
  rollback cases were added;
- the complete local suite passes 3,749 tests with five documented optional
  skips; all 95 compatibility/public/schema/benchmark checks, Ruff,
  `git diff --check`, and installed-extension smoke pass;
- all four exact outputs compare table-for-table and row-for-row through
  Python's independent SQLite binding, and the exact 4.1.1 output is consumed
  by the installed pycolmap binding;
- the benchmark now accepts `--colmap-db-profile` for the hybrid and all four
  exact profiles. Three-run 9.65 MB local medians are 153/1,141 MB/s
  write/read for 3.13, 153/1,118 for 4.1.1, 160/1,131 for current, and
  150/1,018 for MAXX. Traced write allocation rounds to 0.000 MB and mapped
  read allocation to 0.003 MB for every profile; inspection remains
  metadata-only and indexed image/pair reads remain bounded;
- the final post-review sample remains in the same qualitative band at
  144-149 MB/s write and 964-1,063 MB/s read, with zero rounded Python staging
  allocation and 3.53x-4.53x inspection / 7.31x-9.15x indexed-read gains;
- Ampere, Epicurus, and Lagrange reviewed architecture/wire correctness,
  test/oracle soundness, and platform/public/docs behavior. Ownership
  invariants, SQLite integer bounds, structural schema-object checks,
  SQL-presence guards, independent output oracles, pre-commit verification,
  report behavior, and compatibility routing were incorporated.

## H1 — optional HDF5 and hloc stores (2026-07-29)

Implementation:

- [x] Add the `sceneio[hdf5]` extra while retaining NumPy as the only
      unconditional dependency and avoiding provider import at base import
      time.
- [x] Add the lower-owned `containers` registry family with `hdf5`,
      `hloc_features`, and `hloc_matches`.
- [x] Keep generic HDF5 numeric/bool schemas, nested names, text root attrs,
      metadata inspection, named reads, hyperslabs, and atomic replacement in
      SceneIO.
- [x] Collapse full HDF5 link/object enumeration to one pass and make named
      and sliced reads validate only their selected paths and ancestors.
- [x] Map documented hloc features and matches into native `FeatureSet` and
      `MatchGraph` records without losing descriptor dtype/orientation,
      uncertainty, endpoints, dense extents, row order, or score presence.
- [x] Replace temporary masks/stacks/concatenations in hloc match reads with
      direct native dense-to-ragged construction while the GIL is released.
- [x] Refuse unsupported attributes, dataset types, indirect links, virtual
      datasets, and unrepresentable native fields.
- [x] Extend native feature-descriptor construction to every dtype already
      supported by the `FeatureSet` record and expose per-pair score presence.

Verification and documentation:

- [x] Add independent h5py producer/consumer ground truth for all three
      codecs, malformed and transactional cases, a large unselected-dataset
      allocation bound, public capability/snapshot checks, and installed
      wheel smoke.
- [x] Add three path-native benchmark rows and the 59-codec qualification
      ledger. Representative local measurements are recorded in
      `bench/BASELINE.md`.
- [x] Add a generated 5,000-dataset cardinality measurement and a structural
      selected-read guard; record the 447.016-to-0.522 ms named-read delta and
      retain `bench/bench_hdf5_cardinality.py` as its repeatable entry point.
- [x] Add exact h5py and HDF5 notices to `LICENSES/` and document that neither
      provider is bundled.
- [x] Update format coverage, roadmap, architecture, optimization, gap-plan,
      performance-ledger, registry, and benchmark contracts.
- [x] Record the final full-suite/Ruff/diff results and three review lenses.
- [x] Commit and push the green unit.
- [ ] User-trigger the nonpublishing Linux/macOS/Windows package workflow to
      validate the optional extra; this remains a user-gated action.

H1 local closure evidence:

- the exact collection has 3,948 nodes; local MSVC passes 3,943 with five
  documented optional skips, the 123-test focused gate passes, Ruff and
  `git diff --check` are clean, and the manifest-driven installed-surface
  smoke completes;
- the 59-row structural benchmark capture has normalized SHA-256
  `ff176c7296bfa45e4c1536346fb542f176c05ce00385fbdc3ae3336dd4044099`;
  the three-run provider comparison and allocation deltas are recorded in
  `bench/BASELINE.md`;
- the resource/lifetime review confirms every h5py handle is lexically closed,
  returned arrays and native records own their storage, and values remain
  valid after the source file is deleted and collection is forced;
- the format-correctness review confirms the current hloc `names_to_pair`
  layout, D-by-N descriptor wire orientation, exact supported dtypes,
  endpoint reversal, dense extents, pair order, and mixed score presence.
  It also added refusal for schema-version mismatch, non-root metadata,
  indirect datasets, and float narrowing;
- the test-soundness review confirms independent h5py producer/consumer
  assertions, official hloc naming semantics, native/file cross-reads,
  malformed-input refusal, atomic destination preservation, bounded partial
  reads, optional-provider import isolation, and compatibility snapshots.

Zarr v2/v3 numeric CV directory stores are now implemented as codec 60 through
the optional MIT-licensed Zarr/numcodecs provider. SceneIO owns validation,
`TensorDict` mapping, metadata inspection, named/leading-axis partial reads,
directory replacement, capability reporting, wheel smoke, benchmarks, and
v2/v3 oracle parity. The NumPy-only base install is unchanged.

## 67-format optional-provider closure

- [x] Keep stable format contracts in repository-owned adapters while using
      established permissive providers for their optimized storage kernels.
- [x] Add bounded TIFF CV raster, mask, and grayscale-stack support through
      tifffile with provider cross-reads and atomic writes.
- [x] Add bounded single-scan E57 support through pye57/libE57Format with
      position, intensity, RGB, pose, and invalid-point parity.
- [x] Add numeric Parquet and Arrow IPC tables through PyArrow, including
      fixed-width vector columns, inspection, and Parquet column selection.
- [x] Add bounded scalar float32 OpenVDB through TinyVDB and preserve the
      exact packaged template source identity.
- [x] Add bounded static mesh USD and aligned USDZ through TinyUSDZ with
      deterministic repository-owned writers and hierarchy-preserving reads.
- [x] Keep the base installation NumPy-only; provider imports remain lazy and
      capability reporting distinguishes installed from unavailable extras.
- [x] Add provider license/notice files, dependency inventory checks, public
      exports, registry contracts, installed-surface smoke, and benchmark rows.
- [x] Prove USD inspection does not construct a full `MeshScene`.
- [x] Record the three-run benchmark capture in `bench/BASELINE.md`.
- [x] Pass the focused integration gate, complete local suite, Ruff,
      installed-surface smoke, and `git diff --check`.
- [x] Complete the resource/lifetime, format-correctness, and test-soundness
      review and commit the green unit.
- [ ] User-trigger the nonpublishing Linux/macOS/Windows optional-package
      workflow before treating these providers as cross-platform qualified.

The bounded implementations close the requested format ids. Broader
multi-series TIFF, multi-scan E57, nested/nullable Arrow, multi-grid or
transformed OpenVDB, and composed/animated/material USD semantics are explicit
future profiles, not silent fallbacks.

### Planned USD 3D-CV profile expansion

The 2026-07-30 standards review is captured in
[`usd_3d_cv_implementation_plan.md`](usd_3d_cv_implementation_plan.md).
It pins AOUSD Core 1.0.1, supplemental 1.0.1.post0, and tagged OpenUSD 26.08,
and freezes a finite `sceneio.usd.3dcv/1` scope with a commit-sized U0-U7
checklist. No unchecked item below is a current USD I/O capability claim:

- [ ] U0: explicit TOST decision plus AOUSD/OpenUSD/TinyUSDZ provider
      qualification.
- [x] U1: additive `SceneGraph`/`InstanceSet` records and convention-bearing
      mesh, point, and Gaussian payloads.
- [x] U2: compatible rich-scene API, `.usdc` routing, stage metadata,
      inspection, and selection.
- [x] U3: mixed meshes, points, bounded materials, and texture assets. C1 and
      C2 are committed through `917d48e`; the hosted three-OS run remains
      pending the next user-authorized push.
- [x] U4: official `ParticleField3DGaussianSplat` mapping. C3 is committed at
      `a633477`
      with exact float/half, degree 0--3 SH, convention, transform, inspection,
      benchmark, and legacy-codec evidence.
- [ ] U5: cameras/render products are implemented in the C4 worktree and their
      focused gate is green; OpenVDB references, semantic labels, and point
      instancing remain C5.
- [ ] U6: qualified USDC/USDZ, evaluated composition subset, and explicitly
      selected time.
- [ ] U7: complete verification, benchmarks, cross-platform package run, and
      documentation closure.

The existing static `MeshScene` behavior remains supported throughout. Full
USD, authoring-layer preservation, arbitrary shader/custom schemas, rendering,
and non-3D-CV media are fixed exclusions.

Progress:

- [x] U0a records TinyUSDZ 0.9.4's raw-stage boundary, official Gaussian
      attribute parsing, XYZW provider quaternion view, crate-0.8 writer probe,
      and currently unevaluated composition arcs. TOST and current OpenUSD
      comparison gates remain open.
- [x] The current standards review corrects the AOUSD baseline to Core 1.0.1
      plus Apache-2.0 supplemental 1.0.1.post0, pins OpenUSD 26.08
      (`ee47c679abde`), AOUSD specifications (`2f9e746c4fbd`), and supplemental
      materials (`c15ae0cad3ed`, annotated tag object `404e2bde49c1`), and
      records USDA 1.3/USDC 0.15.0 as the current output versions. TOST is
      Apache-2.0-derived but remains a separate narrow policy decision.
- [x] U0b inventories and embeds the unmodified Apache-2.0 AOUSD crate-10
      time-sample fixture, records exact provenance, and closes the local
      provider matrix. TinyUSDZ exposes the sample times but not their values;
      official crate-11/12 feature probes terminate a fresh provider process,
      so SceneIO refuses crate versions above 10 before dispatch. Current
      crate-15 and executable OpenUSD comparison remain behind the TOST
      decision.
- [x] U1a makes `GaussianCloud` convention-bearing, adds explicit conversion,
      validates structure before conversion/writes, and keeps all six legacy
      splat writers on their exact prior conventions.
- [x] U1b adds public compiled `SceneGraph`, `InstanceSet`, and `VolumeAsset`
      records without changing `MeshScene`. The node and instance numeric
      tables are owner-retaining read-only views; hierarchy, payload,
      prototype, convention, semantic, time, and dependency invariants are
      checked at construction.
- [x] U1c adds the accepted USD point and mesh payload fields and makes every
      existing point/mesh writer refuse fields it cannot represent. Six
      focused payload tests, 675 affected codec/API tests, the exact contracts,
      the complete local suite, Ruff, and the 15-format benchmark control are
      green.
- [x] U2 replaces the former `_usd.py` monolith with a facade and bounded
      provider/stage/geometry/package/payload-vocabulary modules, registers
      qualified historical `.usdc`, adds `read_scene()` plus hierarchy-only
      `write_scene()`, maps the bounded stage skeleton, and reports/refuses
      composition features that are not yet evaluated.
- [x] C1 maps static polygon meshes and points with exact interpolation,
      convention, inspection, selection, lifetime, and generated-path gates.
- [x] C2 maps bounded PreviewSurface constants/textures, direct/subset
      bindings, and streamed PNG/JPEG/EXR sources into deterministic USDA
      sidecars or aligned USDZ packages. Its exact 4,183-node local gate passes
      4,177 tests with 6 expected skips; benchmark, exact contracts, docs,
      Ruff, and all three review lenses are green. The existing three-OS
      focused workflow includes all USD suites but has not run at this commit
      because it remains pending a user-authorized push.
- [x] C3 implementation maps the official OpenUSD 26.08 float/half Gaussian
      particle schema, degree 0--3 SH, rendering hints, extent, and static
      transforms. Its focused 62-test mapping suite, 222-test legacy control,
      generated 1k/100k/1M benchmark, exact 4,231-node contract, and focused
      workflow entry are green. The complete local gate passes 4,225 tests
      with 6 documented skips, full Ruff and diff checks are clean, and all
      three review lenses sign off. Hosted execution remains user-gated.
- [x] C4 local closure: the isolated camera adapter maps static perspective and
      orthographic `Camera` prims, one unambiguous `RenderProduct` resolution,
      all five conform policies, local camera-to-parent/OpenGL pose,
      inspection, selection, and deterministic USDA/USDZ writes. The 43 camera
      tests pass; the affected USD/CameraRig run passes 196 with one platform
      skip; 4,275 tests collect; touched files pass Ruff; and generated
      1,000-camera USDA/USDZ measurements are complete. Baseline, workflow,
      contract, coverage, architecture, and plan docs are updated; 259
      calibration/COLMAP controls and 40 docs/contracts pass; the full local
      gate passes 4,269 with 6 documented skips; full Ruff and diff checks are
      clean; and all three review lenses sign off. This closure unit records
      the completed C4 result.

Completed U1 evidence:

- the exact collection is 4,106 nodes; the complete local MSVC run passes
  4,101 with five documented optional skips, while all 39 new rich-scene and
  payload record tests and the existing point-cloud record suite pass;
- nested payloads and numeric views remain valid after the original scene
  variable is deleted and collection runs, factory inputs are copied, numeric
  views are read-only, and unsupported copying/pickling is explicit;
- the native source manifest, record registration order, compiled-symbol
  snapshot, public re-export snapshot, and exact collection ledger include
  the additive record surface;
- the resource/lifetime review confirms owner-retaining array and nested
  payload access across collection and a sub-256 KiB traced peak for two
  views over a 100,000-row instance transform buffer; the format/convention
  review added one shared material table plus complete texture/OpenVDB
  dependency references; the test-soundness review preserved historical
  `PointCloud` NaN bit patterns and added nested attribute lifetime coverage;
- the existing USD/USDZ registry rows remain the bounded static `MeshScene`
  profile. Rich-scene USD mapping begins at U2 and is not yet a capability
  claim.
- all legacy point and mesh outputs retain their parity fixtures; the new
  float display fields, widths, ids, motion fields, orientation, and explicit
  double-sided state are each refused before a path destination is replaced;
- the U1c control in `bench/BASELINE.md` covers all 15 touched point, mesh,
  E57, glTF, and static USD/USDZ paths with three medians.

Completed U2 evidence:

- the exact collection is 4,132 nodes and the complete local MSVC run passes
  4,127 with five documented optional skips;
- TinyUSDZ cross-reads repository-authored USDA/USDZ hierarchy fixtures,
  legacy mesh bytes and return types remain exact, and rich mesh reads return
  `SceneGraph`;
- selected prims retain ancestors without constructing unselected mesh
  payloads; retained numeric views survive source removal; all rejected or
  injected writer failures preserve existing destinations;
- inspection exposes representation/crate version, typed prim counts,
  axes/units/time range, dependencies, variants, unsupported features, and
  mesh-projection availability without constructing a compiled scene;
- the three-median compatibility control remains within 10–13 MB/s, direct
  USDA and stored-USDZ inspection retain 0.2 MB traced Python storage, and a
  generated 16 MiB root-layer scan remains below 512 KiB.

Pre-U1 optional-provider closure evidence:

- the exact collection has 4,049 nodes; local MSVC passes 4,044 with five
  documented optional skips, all 79 focused TIFF/E57/Arrow/OpenVDB/USD tests
  pass, Ruff and `git diff --check` are clean, and the manifest-driven
  installed-surface smoke returns `2`;
- the three-run scale-1 provider comparison covers all seven new file-format
  ids and is recorded in `bench/BASELINE.md`; the 67-row qualification ledger
  has 50 timed paths, 17 reviewed exemptions, and normalized SHA-256
  `5941120e40ce72d174222c939698b11c318fae3d1e2e5d993e7eb7f0e1e8481f`;
- the resource/lifetime review confirms provider handles and temporary paths
  are closed on every exit, Arrow IPC and OpenVDB provider buffers are copied
  before closure, and retained TIFF, E57, Arrow, OpenVDB, USD, and USDZ
  records remain valid after source removal and collection;
- the format-correctness review added exact E57 valid-point inspection counts,
  refusal of nonintegral RGB values, a USD inspection path that does not build
  `MeshScene`, and a pre-replacement OpenVDB active-voxel preservation guard;
- the test-soundness review confirms direct-provider writes are read by
  SceneIO, SceneIO writes are read directly by the providers, unsupported
  semantics refuse, existing destinations survive provider failure, optional
  imports stay lazy, and historical native-family evidence remains a tested
  subsequence of the expanded registry.
