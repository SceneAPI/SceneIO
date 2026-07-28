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
while R3-R6 remain open.

R4.1 is complete and pushed at `b2cf5d4` after the R3.4 checkpoint. The root build file now owns
only project language/standard setup and the ordered inclusion of four focused
modules. Explicit manifests partition all 40 native codec sources across the
eight format families, list all 16 record sources, preserve the historical
59-translation-unit `_core` link order, and fail configuration on missing or
duplicate ownership. The 840-line dependency block is byte-identical to the
R3.4 parent. Fresh MSVC and manylinux2014 GCC 10 configurations have identical
non-path cache values and generate exact parent `_core` compile/link commands;
both toolchains build the candidate. Normal run `30310780347` and
compiler-instrumented run `30310780355` pass that exact commit.

R4.2 binding ownership is complete and pushed at `81e0e1c`. A records table
and eight codec-family tables own all 16 record and 40 codec registration
functions behind one validated assembler. The same codec-family tables expose
a private canonical 49-entry native/hybrid inventory; the Python-owned
`image_sequence` adapter remains outside that projection. MSVC and
manylinux2014 GCC 10.2.1 builds, a focused 416-test I/O/architecture sweep,
exact 3,354-node collection, the unchanged strict five-run guard, the complete
3,350-pass/four-skip suite, Ruff, the exact 398/399/81 package gate, and fresh
NumPy-only installed smoke pass. All three confirmation reviews are clear.
Normal run `30316577366` and compiler-instrumented run `30316577369` pass that
exact commit.

R4.3 and final R4 qualification are complete at pushed commit `da1d709`. All
40 native codec sources now live under the eight family directories, with no
flat codec source left. Every executable body is unchanged by the moves; only
pre-existing source-location comments follow their new paths. MSVC and
manylinux2014 GCC 10.2.1 builds, the complete 3,350-pass/four-skip suite, Ruff,
the unchanged 232/49 native surface, the complete five-run strict guard, and
319 public/API/architecture/license checks pass. The exact 398-file Git tree
produces a blob-identical 399-file sdist and unchanged-layout 81-member Windows
ABI3 wheel; the exact source and package artifacts contain no FFmpeg/libav
source, linkage, executable, or payload. Fresh SceneIO-plus-NumPy smoke returns
`2`. Normal run `30326256230` and instrumented run `30326256137` pass exact
commit `da1d709`. No timed codec loop changed and no speedup is claimed. All
three independent reviews are clear.

The first independent review pass found no native lifetime defect and required
stronger inventory/source contracts. The candidate now compares every ordered
read/write/inspect/stream/partial tuple with an independent 49-row fixture,
requires callable symbols, publishes read-only mapping rows, and checks source
ownership recursively by full path so R4.3 cannot hide a misplaced file.
The architecture/lifetime, test/performance, and
platform/package/documentation confirmation reviews are clear.

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
are the sixth family; reconstruction and splats follow.

Points are complete and pushed at `686f42e`. The unit moves `ply`, `pcd`,
`xyz`, `pts`, `las`, and `laz` to
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
exact-tree source/wheel validation passes at tree
`688f0a4caa81edf6e499f7b72e1bc03117a4ddf0`. Normal CI run 30210055913 and
compiler-instrumented run 30210055930 are green for the exact commit.
Reconstruction is the active seventh family; splats follow.

The reconstruction inspector checkpoint now keeps its 12 non-contiguous
codecs as one
manifest family but uses separate inspector and registry implementation
commits. A documentation/parent-freeze commit precedes them and an evidence
closure follows. This split isolates metadata and directory/database handle
behavior from adapter/order assembly while keeping the family atomic.
The exact parent is `074d8d9`, tree
`b329d05eabea9387e51efa1edcf2a29535c5c802`; its 3,184-node collection and
50-row benchmark hash remain unchanged, and the current ordered 12-row
projection is
`92d354dfd4aa415cbd908168d55310902e56fd21541c94d66fc740c1915540d9`.
Three independent planning reviews agree on the split and the parent-derived,
lifecycle, partial-read, package, platform, benchmark, and documentation
gates. Both exact-parent captures reproduce the hashes. The metadata
implementations now live in `_inspectors/reconstruction.py`; the compatibility
facade retains same-signature delegates and its historical shared-value/helper
exports. Parent valid/malformed artifacts and full logical records match for
all 12 formats, and generated files above 4 MiB confirm bounded traced Python
allocation and prompt file, directory, and database path release. Native
parser working memory remains diagnostic. The inspector and portable
absent-value fingerprint commits are pushed at `49fd976` and `6e94614`;
normal run 30214058828 and compiler-instrumented run 30214058885 are green.

The reconstruction registry extraction is complete. Its immutable
`RECONSTRUCTION_CODECS` tuple owns all 12 definitions, and the aggregate
stages that tuple once while restoring canonical positions
1/15/16/17/18/23/24/38/45/46/47/48. Codec ASTs, direct native directory and
database calls, mmap/sink closures, selectors, detection behavior, and public
record contracts remain exact. The expanded architecture suite passes 70
tests, the family matrix passes 506 tests with two documented skips, and the
  complete local suite passes 3,252 with four documented skips. Both benchmark
  projections and the strict five-run guard pass. Exact-tree packaging,
  external NumPy-only smoke, and three independent reviews pass for the
  extraction committed at `be836a0`. Its first hosted normal run exposed
  AppleClang preserving a negative-zero BAL quaternion component and the
  GCC-10 command dropping the repository root from its import path after
  changing directory. The BAL exact-zero canonicalization is isolated from the
  workflow repair, which keeps installed-package isolation at `/tmp` and adds
  command-scoped `PYTHONPATH=/work` for the benchmark fixture import. The
  combined implementation tree `06f89e8b685c3536af0e67a462d9cff90a86bc9c`
  passes repeated package and three-review gates. Normal run `30218232248` and
  compiler-instrumented run `30218232246` pass every final lane, including
  macOS reconstruction and the isolated GCC-10 invocation. The registry
  checkpoint is closed.
  Exact-export import sampling retains the seven-module `sceneio` and
  eight-module direct `_core` sets; the I/O facade's only added module is
  `_registry.families.reconstruction`. Splats are the final R2 family.

Splats are the eighth and final R2 family. Their exact parent is
`0696533e515b5f8e65cbb676df28d852f9d0a049`, tree
`62a844b198dfd05d5d6d435a8e2aa22bf6bb898e`. Two parent benchmark captures
reproduce the all-50 structural hash
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered six-row hash
`5c6adc3584ba25050c885b37313d009311e2253b0c841cbc8738b806cb090bfd`.
The split keeps all six ids as one non-contiguous manifest family. Their
metadata readers live in `_inspectors/splats.py`, and their Codec definitions
now come from the side-effect-free `build_splat_codecs(...)` factory in
`_registry/families/splats.py`. SOG's archive, directory, and
direct-`meta.json` adapters remain facade-injected, preserving their callable
and path behavior; shared PLY classification remains in `_ply.py`. Aggregate
publication restores canonical positions 2/3/4/5/14/49, and the facade no
longer contains any individual built-in definition. The exact-tree package
and all three independent-review gates pass. Registry implementation
`3e46d82` and platform-contract repair `9928c6d` are pushed; final normal run
`30228235491` and compiler-instrumented run `30228235535` pass. R2 is closed.
R3.1a is complete in the current tree. R3.1b closes at follow-up commit
`0bdfe0f`; normal run `30234796010` and compiler-instrumented run `30234796025`
pass. Arrays close at `6d9ec34`, and calibration closes at `5dc03f4`; the
raster-image family closes at `6572a76`, and the mesh benchmark family closes
at `613fd26`. Points close at `45e2757`; normal run `30244892746` and
compiler-instrumented run `30244892600` pass. The reconstruction benchmark
family closes at `76ed21b`; normal run `30247662591` and
compiler-instrumented run `30247662622` pass. The sequence benchmark family
closes at `4b8c829`; normal run `30250394890` and compiler-instrumented run
`30250394906` pass. The splat benchmark family closes at `cd32268`; normal run
`30253301819` and compiler-instrumented run `30253301871` pass. The shared
runner extraction is complete in the current local tree. Completeness and
strict comparison-provider controls remain in R3.2.
These changes alter no codec algorithm or public API and make no
codec-performance claim. Exact R3.1a normal run
[30231629465](https://github.com/SceneAPI/SceneIO/actions/runs/30231629465)
and compiler-instrumented run
[30231629496](https://github.com/SceneAPI/SceneIO/actions/runs/30231629496)
are green.

R3.1a is complete in the current tree. `bench/bench_io.py` remains the
compatible development CLI and fixture/oracle facade, while
`bench/io_bench/model.py`, `measure.py`, and `reporting.py` now own the shared
data models, timing/traced-allocation and warmed-parent RSS measurements, and
all console formatting. The existing `*_rss_mb` JSON fields remain unchanged;
their contract now explicitly identifies them as exploratory warmed-parent
deltas rather than fresh-process qualification evidence. R3.1b adds a
separate versioned protocol under `bench/io_bench/`: a fresh child imports and
warms SceneIO, records baseline/current and platform-high-water RSS, performs
exactly one measured operation, and reports sampler/platform availability.
Strict mode rejects unavailable sampling; non-strict probes retain null RSS
fields and never substitute zero. Qualification additionally binds the child
response to its request, compares one canonical operation/warm-up signature,
requires three samples and zero residual high-water headroom, and evaluates
every declared payload size. Headroom is derived from the baseline counters,
only the declared platform backends qualify, and instrumented runtimes remain
explicitly unavailable. The repeated generated 8/48 MiB controls pass a
bounded 64 KiB read and reject an intentional whole-payload allocation. R3.2
moves family fixtures/oracles and only then moves the sweep orchestration into
`runner.py`, avoiding a lower module that imports back through the facade.

The initial splat parent-freeze checkpoint is committed and pushed at
`93fcf1b39350a3a0080a7b87ead65d0d9343d354`; its
[hosted run 30220612832](https://github.com/SceneAPI/SceneIO/actions/runs/30220612832)
exposed the platform variants described below. The profile correction is
committed and pushed at
`18643595ef538f5c9d5803ef20218a3327de04ef`. Its
[normal run 30221945705](https://github.com/SceneAPI/SceneIO/actions/runs/30221945705)
passes every lane, including all three splat OS jobs and pinned
manylinux2014/GCC-10; its
[compiler-instrumented run 30221945731](https://github.com/SceneAPI/SceneIO/actions/runs/30221945731)
passes both native lifetime jobs. The 31-node,
oracle-independent architecture suite covers all six codecs, SOG archive and
directory entry paths, four-way PLY classification, SPZ v1-v4, partial
selectors, retained-result path release, and invalid-input behavior. The
parent-freeze candidate collects exactly 3,287 nodes with sorted normalized
SHA-256
`190733ef6fbf1dd99cdd721ddc19277fc22dca3643154f11bf9738aa52dbc294`.
The checked six-row benchmark projection reproduces both Windows/MSVC parent
captures. Platform reproduction is now characterized. Gaussian PLY,
compressed PLY, KSplat, SPZ, and SPLAT encoded bytes match exactly on MSVC,
hosted AppleClang/ARM, hosted glibc, and the pinned
manylinux2014/GCC-10 image. SOG's five WebP layers also match exactly, while
one `std::log1p` metadata bound is an adjacent double on glibc; the archive
differs only in that JSON digit and the corresponding CRC fields.
KSplat/SPLAT scales and AppleClang/ARM SPZ quaternions have isolated one-ULP
decoded variants. The parent contract keeps all unaffected fields exact,
bounds only those named arrays to one ULP, and records exact per-profile
fingerprints. The ownership-only inspector extraction is locally validated:
the lower module owns all six metadata readers while the compatibility facade
retains dispatch and same-signature wrappers. Its 44-node architecture suite
adds lower-layer import/reload, facade delegation, ownership, parity, and
generated 36 MiB-plus bounded-inspection coverage for every family member,
plus retained SOG results/failures during declared-layer release and
whole-directory replacement. The 3,301-node candidate collection has sorted
normalized SHA-256
`ab9ab8c698e005032aeea52d69703b5b32ee29998fdd77c24970f6a198b7c176`.
Both structural benchmark captures, the retained five-run guard, and a
15-sample randomized all-six exact-parent inspector comparison pass; traced
allocation maxima are byte-for-byte equal to the parent.
Universal SOG byte canonicalization would be a separate codec-behavior
change.

The final all-six parity lane additionally exposed that the larger pinned
compressed-PLY writer vector crosses one lossy quantization boundary on the
characterized hosted macOS AppleClang/ARM profile. Hosted Windows/MSVC and
Ubuntu/glibc retain the PlayCanvas-exact body hash; that macOS profile retains
its unchanged parent body hash. Native exp/log rounding is the inferred cause
consistent with the observed output, not a universal platform claim. Both
fingerprints are pinned and pass the independent layout/decode oracle. Making
their existing distinction explicit is a test-contract correction, not a
codec change; universal writer canonicalization remains a separately
benchmarked behavior decision.

Inspector commit `a4c968b` is pushed and passes
[normal run 30224059298](https://github.com/SceneAPI/SceneIO/actions/runs/30224059298)
and
[compiler-instrumented run 30224059282](https://github.com/SceneAPI/SceneIO/actions/runs/30224059282).
The registry candidate locally passes its 444-test family/common matrix and
the complete 3,309-node collection (3,305 passed, four documented skips);
the collection's sorted normalized SHA-256 is
`cd0a8c1a273dd87d72c9a08edf39d45f93b562295e8c3216e09b076b4dd65a43`.
Both structural captures reproduce the frozen hashes and the strict five-run
guard passes. A 15-sample randomized interleaved comparison covers all 23
read, write, inspect, and supported point-range operations: every timing
median is within the planned variation bound, and every candidate maximum
traced allocation equals its parent maximum. The scale-1 family diagnostic
uses 11.2 MiB logical clouds; Windows reports the requested cache-eviction
hint as unavailable, so these are warm-cache readings. Exact import sets
remain 7/7 for `sceneio`, 8/8 for direct `_core`, and 43/45 for the I/O
facade, whose only additions are the two splat lower modules.
Pre-final tree `7ab4f960dcb43ac95c4cf7269fed7d733bad71cc` has 326
tracked files and produces a 327-file source archive whose only addition is
generated `PKG-INFO`. Its sdist-derived 81-member Windows abi3 wheel has one
native extension, all 15 attribution members, NumPy as its only unconditional
dependency, and no packaged build/include/lib/share/bin tree. Git/archive/
wheel runtime identity, native dependency inspection, and the external
NumPy-only all-six installed smoke pass. All three independent reviews are
clear after resolving the three-OS oracle-parity, wheel-smoke ownership, and
reload-atomicity findings.
The exact platform-repair tree
`79819558208fdb8099b23d3c38fd1afee3ee2f7c` repeats the 326/327/81
Git/source/wheel inventory and external installed smoke. Normal run
`30228235491` passes the full suite, performance guard, all three splat jobs,
mmap matrix, reconstruction matrix, and GCC-10 lane; compiler-instrumented
run `30228235535` passes both jobs. R2 is complete.

The codec-per-file C++ layer remains reasonably isolated, but orchestration and
verification have accumulated in a few large modules:

| Area | Current shape | Growth risk |
|---|---|---|
| C++ codecs | 41 stable files for 50 format ids; eight explicit CMake family manifests; eight family-owned binding tables; one default-excluded candidate source under `src/cpp/qualification/`; one validated assembler | all stable sources are nested under their owning family; the R4 40-source organization checkpoint is closed at `da1d709`; R5 split the JPEG common and retained mechanics without changing the public API |
| C++ records | 32 source/header files | still manageable; new table/animation/scene records will add pressure |
| Python registry | `registry.py`, 205 lines; `_registry/assembly.py`, 148 lines; focused `_registry/{model,adapters,detection,native_features}.py` modules; and eight `_registry/families/*.py` definition modules | all built-ins are family-owned; R3 now splits the benchmark and cross-codec verification monoliths |
| Inspection | `_inspection.py` compatibility facade plus `_inspectors/{model,common,arrays,calibration,images,meshes,points,reconstruction,sequences,splats}.py`; all eight manifest families have lower inspector ownership | keep the proven shared model, mmap bridge, metadata bounds, exact-read/integer grammar, and image-result constructor as lower services |
| Benchmark | compatible `bench_io.py` entry point plus `io_bench/{model,measure,reporting,runner}.py`, all eight lower family modules, and shared `families/common.py` | all benchmark ownership is lower; the final R3.2 unit adds built-in completeness and strict comparison-provider controls |
| Cross-codec tests | shared 50-codec catalog and 44-case buffer builder; focused streaming, inspection, array-partial, and image-partial modules; lower partial assertions; `test_io_mmap.py`, about 680 lines; shared partial invariants | mmap, streaming, and inspection ownership is split; partial behavior is migrating one family at a time |
| Execution plan | `format_gap_implementation_plan.md`, about 2,500 lines | historical evidence and the active queue are easy to confuse |
| Native dependencies | nine source-complete in-tree projects, one LAZperf integration/provenance directory, and three `FetchContent` projects | miniz, nlohmann/json, and zstd are repository-contained; the three remaining source fetches keep stable builds from being fully offline |

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
  SceneIOBackendQualification.cmake
  SceneIODependencies.cmake
  SceneIOInstrumentation.cmake
  SceneIOSources.cmake
  SceneIOTargets.cmake

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
  qualification/
    jpeg_turbo.cpp
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
  __init__.py                 # development-only package marker
  bench_io.py                 # compatible CLI/helper facade; thin after R3.2
  io_bench/
    __init__.py
    model.py
    measure.py
    reporting.py
    runner.py                 # R3.2, after family hooks move
    qualification.py          # immutable built-in comparison ledger
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
candidate_backends = []
rejected_backends = [{ id = "libjpeg-turbo", version = "3.2.0", gate = "quality-profile:rgb8_q95_444" }]
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
- `known_gap`: the current backend has a measured performance gap, with
  evaluated, rejected, and remaining candidates stated explicitly;
- `native_by_necessity`: no suitable upstream kernel exists and the
  repo-maintained parser is independently verified;
- `not_applicable`: the codec does not expose that operation.

The current known exception is the JPEG backend: the committed baseline
measured stb write/read at 60/154 MB/s versus Pillow's libjpeg-backed reference
at 924/541 MB/s on the same fixture. The stable-tier gate evaluated
libjpeg-turbo 3.2.0 for both directions and rejected it as the combined
default after its q95 comparative-quality result missed the frozen floor.
The gap remains open with stb retained; micro-optimizing stb is not an
adequate closure. XYZ formatting and WebP
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

- Extract shared models, measurement primitives, and reporting first, while
  keeping JSON/CLI behavior and the warmed-parent RSS meaning unchanged.
- Move fixture builders and oracles by family.
- Keep `bench/bench_io.py` as a compatible CLI entry.
- Move the sweep runner only after its family dependencies have lower
  ownership, leaving the facade thin without creating a reverse import.
- Centralize buffer/path/directory codec cases in `tests/_support/codec_cases.py`.
- Split large behavior tests one behavior/family at a time without duplicating
  parameter matrices, and compare exact pytest node ids and skip reasons.
- Preserve the current warmed-process RSS metric during the mechanical split,
  then add a separately tested child-process RSS protocol for qualification.
- Make required oracles and RSS sampling strict in qualification mode.

The child-process portion is implemented in R3.1b. Its response schema,
supported controlled operations, three-sample default, null-unavailable
semantics, request binding, semantic operation identity, high-water
calibration, and every-size payload-growth rule are pinned by
`tests/contracts/memory_protocol_v1.json`. Existing test-local samplers move
only during R3.3's staged consumer migration so their current node ids and
coverage remain unchanged. The new protocol suite is part of the existing
Linux/Windows/macOS mmap CI lane.

R3.2 begins with the arrays benchmark family. Its complete six-codec `Spec`
hook now lives under `bench/io_bench/families/arrays.py`; fixture/oracle helpers
and safetensors oracle bindings have lower ownership under
`bench/io_bench/{fixtures,oracles}/arrays.py`, while `bench_io.py` retains
compatible aliases. `bench_io_v1.json` records source ownership and AST hashes,
and direct installed/absent-mode oracle controls cover the lower modules,
constructed `Spec` bindings, and facade aliases. A fresh exact-tree source
archive has 343 members and contains all six new benchmark modules without
generated cache files. Its 81-member derived wheel excludes development
benchmark/test modules, retains all 15 attribution files, and keeps NumPy as
its sole unconditional dependency. Exact arrays commit `6d9ec34` passes normal
run `30236069971` and compiler-instrumented run `30236069959`.

The calibration checkpoint adds the complete four-codec hook under
`families/calibration.py`, its deterministic rig builders under
`fixtures/calibration.py`, and its optional PyYAML plus standard-library XML
comparisons under `oracles/calibration.py`. The unchanged
`families/common.py::_record_nbytes` helper is now lower-owned once for
calibration and later pose/reconstruction hooks. Checked AST, facade identity,
Spec binding/argument/size, installed/absent PyYAML, XML execution, fresh lower
import, four-codec oracle, and 50-codec structure controls pass. The fresh
347-member exact-tree source archive contains the four new
calibration/common benchmark modules without generated cache files. Its
81-member wheel excludes benchmark/test/YAML modules, retains all 15
attribution files, keeps NumPy as the only unconditional dependency, and
keeps PyYAML test-extra only. A fresh NumPy-only, PyYAML-absent wheel
environment passes `python -m sceneio._wheel_smoke`; all three independent
reviews are clear. Exact calibration commit `5dc03f4` passes normal run
`30237676629` and compiler-instrumented run `30237676648`.

The raster-image checkpoint adds all eight PNG/JPEG/BMP/TGA/WebP/HDR/EXR/
Netpbm specs under `families/images.py`, their unchanged deterministic
uint8/float32 builders under `fixtures/images.py`, and optional Pillow,
imageio, and OpenEXR comparisons under `oracles/images.py`. The compatible
facade preserves historical helper identities and slices the hook around the
unchanged interleaved Y4M row. Exact moved-function AST, binding, logical-size,
installed/absent/fallback, real oracle-pair, EXR RGB normalization,
seven-of-eight live oracle, and 50-codec structure controls pass. Portable
independent Radiance HDR benchmark throughput is explicitly exempted while
the NumPy RGBE parity suite remains independent. The fresh 350-member
exact-tree source archive contains the three image modules without generated
caches. Its 81-member wheel excludes development and comparison-library
modules, retains all 15 attribution files, keeps NumPy as its only
unconditional dependency, and passes a fresh NumPy-only installed smoke
without Pillow, imageio, or OpenEXR. All three independent reviews are clear.
Exact raster commit `6572a76` passes normal run `30239455960` and
compiler-instrumented run `30239455952`.

The mesh checkpoint adds the five buffer-backed PLY-mesh/OBJ/STL/OFF/GLB specs
under `families/meshes.py`, five unchanged mesh/scene builders under
`fixtures/meshes.py`, and all 12 optional trimesh helpers under
`oracles/meshes.py`. The specialized multi-file glTF row remains in
`bench_io.py::_benchmark_gltf` until runner extraction and consumes the lower
helpers through exact facade aliases. Checked AST, binding, size,
installed/absent trimesh, oriented triangle geometry, all-six live oracle, and
50-codec structure controls pass. The fresh 353-member exact-tree source
archive contains the three mesh modules without generated caches. Its
81-member wheel excludes benchmark/test/trimesh/pygltflib modules, retains all
15 attribution files, keeps NumPy as its only unconditional dependency, and
passes a fresh NumPy-only installed smoke without either comparison library.
All three independent reviews are clear.

Exact mesh commit `613fd26` passes normal run `30241711640` and
compiler-instrumented run `30241711620`.

The point checkpoint adds the non-contiguous XYZ/PTS/point-PLY/PCD/LAS/LAZ
specs under `families/points.py`, their three unchanged deterministic builders
under `fixtures/points.py`, and nine PTS/Open3D/LASpy helpers under
`oracles/points.py`. The facade preserves exact helper and provider identities
and slices the family around the existing mesh block. Checked AST, binding,
scale, logical-size, installed/independently absent provider, real
writer-to-reader, and core-to-reader controls pass. Five of six live rows
produce independent metrics. Review corrected the historical unequal LAS
comparison so LAS and LAZ now use the same point-format-2 XYZ/RGB/intensity
payload for SceneIO and LASpy and retain one positions-equivalent throughput
denominator. XYZ explicitly exempts only benchmark encode/decode throughput while its
independent NumPy text parity remains covered. The fresh 356-member exact-tree
source archive contains the three point modules without generated caches. Its
81-member wheel excludes benchmark/test/Open3D/LASpy/LAZ-backend modules,
retains all 15 attribution files, keeps NumPy as its only unconditional
dependency, and passes a fresh NumPy-only installed smoke without those
comparison packages. All three independent reviews are clear.

Exact point commit `45e2757` passes normal run `30244892746` and
compiler-instrumented run `30244892600`.

The reconstruction checkpoint adds the nine buffer-backed transforms/TUM/
KITTI/EuRoC/g2o/Bundler/BAL/NVM/OpenMVG specs under
`families/reconstruction.py`, their deterministic builders under
`fixtures/reconstruction.py`, and portable EuRoC/g2o/BAL pairs under
`oracles/reconstruction.py`. The facade slices the family around calibration.
Specialized `colmap_sparse`, `colmap_sparse_txt`, and `colmap_db`
orchestration remains facade-owned until runner extraction. All nine `Spec`
ASTs and 12 of 13 moved helper ASTs are unchanged. The sole reviewed
difference strengthens the g2o reader from counts to complete semantic arrays
and reconstructed symmetric information matrices. Three live rows produce
portable comparison metrics; six exact benchmark-throughput exemptions point
to independent parity suites. The 50-row structure is unchanged.

Focused reconstruction/contract validation passes 505 tests with one existing
optional PyCOLMAP skip; the complete suite passes 3,316 with four documented
skips, and Ruff is clean. The fresh 359-member exact-tree source archive
contains exactly the three new reconstruction modules. Its 81-member wheel
excludes benchmark/test/PyCOLMAP modules, retains all 15 attribution files,
keeps NumPy as its only unconditional dependency, and passes a fresh
NumPy-only installed smoke without PyCOLMAP. All three independent reviews
are clear.

Exact reconstruction commit `76ed21b` passes normal run `30247662591` and
compiler-instrumented run `30247662622`.

The sequence checkpoint adds the buffer-backed Y4M spec under
`families/sequences.py`, the Y4M and image-directory fixtures under
`fixtures/sequences.py`, and the portable Y4M pair under
`oracles/sequences.py`. The Y4M `Spec` remains between WebP and HDR. The
image-directory `DirectorySpec` remains facade-owned until runner extraction
and consumes the lower fixture through an exact alias. The Y4M `Spec`,
directory orchestration, and three of four moved helper ASTs are unchanged.
The sole reviewed difference strengthens the Y4M reader to complete plane and
metadata semantics. Y4M has live portable comparison metrics; independent
image-directory throughput carries an exact exemption backed by
manifest/PGM parity.

Focused sequence/contract validation passes 225 tests; the complete suite
passes 3,316 with four documented skips, and Ruff is clean. The fresh
362-member exact-tree source archive contains exactly the three new sequence
modules. Its 81-member wheel excludes benchmark/test modules, retains all 15
attribution files, keeps NumPy as its only unconditional dependency, and
passes a fresh NumPy-only installed smoke. All three independent reviews are
clear.

Exact sequence commit `4b8c829` passes normal run `30250394890` and
compiler-instrumented run `30250394906`.

The splat checkpoint adds all six ordinary splat specs under
`families/splats.py`, the deterministic Gaussian builder under
`fixtures/splats.py`, and the optional `gsply` PLY/SPZ pair under
`oracles/splats.py`. All six `Spec` ASTs and all five moved helper ASTs are
unchanged. Canonical placement between points and arrays, facade identities,
and lower-to-facade import direction remain fixed. Gaussian PLY and SPZ retain
live independent comparisons; four exact benchmark-throughput exemptions
point to the Compressed PLY, SOG, KSplat, and `.splat` parity suites.

Focused splat/contract validation passes 176 tests with one documented SPZ-v2
writer skip; the complete suite passes 3,316 with four documented skips, and
Ruff is clean. The fresh 365-member exact-tree source archive contains exactly
the three new splat modules. Its sdist-derived 81-member wheel excludes
benchmark/test/`gsply` payloads, retains all 15 attribution files, keeps NumPy
as its only unconditional dependency, and passes a fresh NumPy-only installed
smoke. All three independent reviews are clear.

Exact splat commit `cd32268` passes normal run `30253301819` and
compiler-instrumented run `30253301871`.

The runner checkpoint moves the complete sweep, specialized
glTF/COLMAP/image-directory orchestration, CLI parser, and all 20 supporting
functions to `io_bench/runner.py`. `bench_io.py` becomes a small compatible
direct entry point and re-exports the runner's complete historical non-dunder
helper surface. Every moved function AST is unchanged; the parent and
candidate 166-name surfaces share checked SHA-256
`0c26c90b0d3ee10cb216e5baf3b0502a446f55805c89a437ea71790bd39be33a`.
Facade rebinding propagates to runner globals, star imports retain the exact
parent 67-name public surface, and the lower runner imports independently of
the facade. A first facade import preserves existing runner objects and
rebindings; explicit facade reload restores source definitions. The 50-row
structural projection remains unchanged. This is an ownership-only unit.
Focused runner/contract validation passes 145 tests; the complete suite
passes 3,316 with four documented skips, and Ruff is clean. The exact staged
tree has 365 tracked files and produces a 366-member source archive. Its
sdist-derived 81-member Windows wheel excludes benchmark/test modules, retains
all 15 attribution files, keeps NumPy as its only unconditional dependency,
and passes a fresh NumPy-only installed smoke.

Exact runner commit `cf8d117` passes normal run `30257105454` and
compiler-instrumented run `30257105468`.

The final R3.2 behavior checkpoint adds an immutable comparison qualification
ledger under `io_bench/qualification.py`. It owns exactly the canonical 50
built-in ids: 33 have timed comparison providers and 17 carry reviewed,
property-specific exemptions with exact verification paths. Assembly fails
before measurement for a missing, duplicate, or noncanonical built-in while
runtime extension registrations remain outside repository-completeness
checks. Strict qualification mode preflights every required provider binding
for a complete sweep, propagates provider failures, and audits every declared
metric instead of treating missing evidence as optional. The retained five-run
CI performance guard uses this strict mode. A local one-run strict sweep
returns 50 successful rows and all 33 timed comparison pairs; the independent
skip-comparison projection retains
SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
The complete five-run strict O4/O5 guard passes; the exact local tree collects
3,339 tests and passes 3,335 with four documented skips, and Ruff is clean. All
three independent closure reviews are clear. The exact staged tree has 367
tracked files and produces a 368-file sdist whose only generated file is
`PKG-INFO`; its sdist-derived 81-member Windows abi3 wheel contains one native
module and all 15 attribution files, excludes benchmark/test/build payloads,
and passes a fresh SceneIO-plus-NumPy installed-wheel smoke.

Exact qualification commit `0e54cf5` passes normal run `30263506366` and
compiler-instrumented run `30263506270`.

R3.3 starts with a lower-owned catalog under
`tests/_support/codec_cases.py`. Its immutable canonical-order definitions
partition all 50 built-ins into the existing 44 buffer fixtures, three
path-native fixtures, and three directory fixtures, and pin the live
28 partial-capable-codec projection with 32 selector declarations. Focused
controls prove family ownership and runtime-extension isolation. Exact catalog
commit `81f143b` passes normal run `30266501529` and compiler-instrumented run
`30266501618`.

The mmap suite now consumes the reusable deterministic builder in
`tests/_support/buffer_codec_cases.py`. Exact migration commit `9a73892` passes
normal run `30268797350` and compiler-instrumented run `30268797374`. The
duplicated local builder is removed only after that hosted equivalence; its
exact original 44-case traversal order, live callable identities, 43-codec
portable encoded-fixture projection, and platform-profiled compressed-PLY
semantic fixture remain contract-pinned. Partial consumers remain unchanged
until their family-by-family migrations. The complete local tree
collects 3,345 tests and passes 3,341 with four documented skips; Ruff and all
three independent reviews are clear. The independent one-run 50-codec
benchmark smoke retains structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
The exact staged tree has 371 tracked files and produces a 372-file sdist
whose only generated file is `PKG-INFO`; its sdist-derived 81-member Windows
abi3 wheel contains one native module and all 15 attribution files, and a
fresh SceneIO-plus-NumPy environment passes `sceneio._wheel_smoke`.
Exact legacy-matrix removal commit `fc86f44` passes normal run `30271311308`
and compiler-instrumented run `30271309916`.

The next R3.3 checkpoint moves the 14 streaming behavior functions into
`tests/test_io_streaming.py` without changing their bodies, test names, or
three parameter ids. The assembly contract records all 16 old and new node
paths explicitly, while `tests/_support/memory_measurement.py` supplies the
one small allocation helper shared with mmap coverage. The complete local
collection remains 3,345 nodes and the 50-codec benchmark structure remains
unchanged. The exact 373-file staged tree yields a 374-file sdist and
81-member Windows abi3 wheel; the fresh installed smoke contains only SceneIO
and NumPy. The Windows/Linux/macOS mmap job names the focused streaming suite
explicitly. Exact streaming commit `914702d` passes normal run `30274413815`
and compiler-instrumented run `30274413693`.

Inspection is the next focused consumer. Its 47 tests and three helpers move
unchanged to `tests/test_io_inspection.py`, preserving 76 node suffixes.
Reusable rename groups expand the exact streaming and inspection old/new
paths without mixing path-only moves into feature additions. The complete
collection remains 3,345, each platform command names inspection explicitly,
and the exact package inventory is 374/375/81. Exact commit `0e21e27` passes
normal run `30278777267` and compiler-instrumented run `30278777173`.

Partial-family migration starts with three unchanged array-specific DMB/FLO
tests in `tests/test_io_partial_arrays.py`. The broad array/image differential
and other cross-family invariants remain in the shared partial suite. The
assembly contract pins the three exact path-only renames and the destination
function AST projection, and each platform command names the new module.
The exact package inventory is 375 source files, 376 sdist members with only
generated `PKG-INFO`, and 81 wheel members; fresh NumPy-only smoke passes.
Exact array commit `5009ea0` passes normal run `30282057346` and
compiler-instrumented run `30282056576`.

The image partial unit moves three unchanged Netpbm/WebP functions producing
10 parameterized nodes into `tests/test_io_partial_images.py`. Their two
unchanged image-window assertion helpers move once into
`tests/_support/partial_read.py` so the cross-family differential does not
import a sibling test module. Exact node and function projections plus
Windows/non-Windows command inclusion are contract-pinned.
Exact package verification records 377 source files, a 378-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.
Exact image commit `d198560` passes normal run `30285128366` and
compiler-instrumented run `30285128448`.

The mesh partial unit moves the unchanged face-range semantic and mapping-close
test into `tests/test_io_partial_meshes.py`. Its exact path-only rename and
function AST projection are contract-pinned, and both platform commands name
the focused module. The complete collection remains 3,345 with normalized
SHA-256
`c658cb0d7353ad5c6cf4f6e38b01a02418f693b121e6d8f4bba887945821cc9d`.
Exact package verification records 378 source files, a 379-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.
Exact mesh commit `4294dbe` passes normal run `30287854716` and
compiler-instrumented run `30287854692`.

The point partial unit moves three unchanged XYZ/LAS functions producing 13
parameterized nodes into `tests/test_io_partial_points.py`. Their unchanged
point-range assertion moves once into `tests/_support/partial_read.py`, where
the cross-family point/splat differential continues to use it. Exact node,
function, and helper projections plus Windows/non-Windows command inclusion
are contract-pinned. The complete collection remains 3,345 with normalized
SHA-256
`2451c9bb2606ac1587011eafeb2345fc9f34f7e08df7ea17b239b5a1e78a624f`.
Exact package verification records 379 source files, a 380-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.
Exact point commit `ac1a4d1` passes normal run `30290617469` and
compiler-instrumented run `30290617607`.

The reconstruction partial unit moves 12 unchanged COLMAP functions producing
15 nodes plus nine private helpers into
`tests/test_io_partial_reconstruction.py`. The shared fresh-process RSS helper
moves once into `tests/_support/partial_read.py` for both the reconstruction
suite and retained cross-family large-read test. Exact node, test, private
helper, and lower-helper projections plus Windows/non-Windows command
inclusion are contract-pinned. Collection remains 3,345 with normalized
SHA-256
`217c227e566a6767fc59b031b1217202ced5ba0dc6a14b3b7fa2d27c0f9314f4`.
Exact package verification records 380 source files, a 381-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.
The first hosted normal run `30294120621` exposed four explicit manylinux
selectors that still named the pre-move shared module. The selectors now use
the focused reconstruction module, and the assembly suite rejects stale paths.
Compiler-instrumented run `30294120444` passed the reconstruction commit.
Follow-up commit `b5e5c55` passes normal run `30296172958` and
compiler-instrumented run `30296174522`.

The final R3.3 ownership audit finds no sequence-only consumer in the shared
partial suite: Y4M and directory-sequence partial behavior is already owned by
the sequence architecture and codec suites. Splat-family range behavior and
the deliberate no-selector SPZ contract are likewise already family-owned.
The remaining seven tests in `tests/test_io_partial.py` combine two or more
families and therefore remain shared. The assembly contract pins the relevant
sequence, splat, and shared function projections, all 21 exact family-owned
node/parameter ids, and an AST-derived per-function shared format mapping.
That mapping proves the shared suite contains both splat and non-splat formats
but no sequence format. No empty family module or artificial node split is
introduced.

The closure tree collects 3,345 tests and passes 3,341 with four
documented skips. Ruff and the complete five-run strict O4/O5 guard pass. Its
exact staged tree contains 380 source files and produces a 381-file sdist and
81-member Windows ABI3 wheel. The wheel contains one native module and all 15
attribution files, excludes repository test/benchmark/build payloads, keeps
NumPy as its sole unconditional dependency, and passes a fresh
SceneIO-plus-NumPy installed smoke.
Exact R3.3 closure commit `811cb0d` passes normal run `30300122309` and
compiler-instrumented run `30300122324`.

R3.4 replaces the hand-called installed-smoke helper list with an immutable
format-to-runner map whose ids and order must equal `BUILTIN_DEFINITIONS`,
`REGISTRY`, and the public codec listing. Successful public calls are observed
per format, and expected properties come from live capability records. The
current candidate covers write/read/inspect for all 50 built-ins, pairs each
declared stream-capability direction with a successful corresponding public
path call, and exercises all 32 selectors declared by 28 partial-capable
codecs. Dedicated mmap and sink suites separately prove the allocation
semantics behind those flags. The property-specific exemption contract is
present but empty; missing, unexpected, incomplete, or stale entries fail the
architecture check.
The candidate collects 3,348 tests and passes 3,344 with four documented
skips; Ruff and the complete five-run strict guard pass. Its first frozen
380-file tree produces a byte-identical 381-file sdist and an 81-member
Windows ABI3 wheel with one native module, all 15 attribution files, no
excluded layout payload, and NumPy as its sole unconditional dependency. A
fresh outside-repository SceneIO-plus-NumPy environment passes the complete
installed smoke.

### R4. Organize native build and bindings

- Split dependency configuration and source manifests out of the root
  `CMakeLists.txt`. **R4.1 complete:** the root is now a four-module assembly,
  family/source ownership is explicit, and parent-equivalent MSVC/GCC 10
  cache plus compile/link evidence is recorded.
- Replace manual declarations in `module.cpp` with family registration
  functions while preserving binding order. **R4.2 complete at `81e0e1c`:** one
  record table plus eight codec-family tables preserve the 16/40 historical
  order behind a validated assembler.
- Expose a private machine-readable native codec inventory from those same
  family tables and compare it with the native/hybrid projection of the
  built-in Python manifest. Built-in definitions declare whether their adapter
  owner is native, Python, or hybrid. **R4.2 complete at `81e0e1c`:** the
  canonical 49-entry projection resolves all declared operation symbols and
  excludes only Python-owned `image_sequence`.
- Move codecs by family in mechanical commits; do not mix semantic edits with
  moves. **R4.3 complete at `da1d709`:** all 40 native codec sources live
  under the eight family directories and final R4 qualification passes.

### R5. Qualify performance

- Populate the 50-codec ledger from existing baseline evidence.
- **R5.1 complete:** the machine-readable candidate intake records
  stb, libjpeg-turbo 3.2.0, mozjpeg 4.1.1, and the evaluated jpegli revision.
  A guarded, default-off CMake selector builds isolated stb and
  SIMD-required libjpeg-turbo variants through the same `_core` JPEG API.
  Default wheel and symbol isolation are proved.
- **R5.2 decision complete on MSVC:** the frozen 97-cell local/122-cell
  remote-inclusive matrix compares separate installed wheels through the
  core/public buffer, mmap, path, and sink surfaces against one hashed corpus.
  It retains paired raw timing samples and quality, size, startup,
  repeatability, allocation, RSS, wheel, toolchain, and configured-SIMD
  evidence. The exact `7a88e7c` clean-wheel report passes 1,596/1,597 gates
  and measures 4.787x encode / 1.782x decode median geomeans, but
  libjpeg-turbo misses the q95 quality floor (`-0.058242 dB` versus
  `-0.05 dB`). It is rejected as the combined default and stb remains
  unchanged. The manual nonpublishing workflow still covers MSVC, the pinned
  manylinux2014 GCC 10 image, and AppleClang arm64, but was not dispatched
  because no conforming candidate advanced beyond MSVC.
- Future candidate loops repeat the same per-profile/per-direction comparison
  with one provenance-recorded, accepted-subset corpus from retained and
  independent producers. The current JPEG loop is complete with a negative
  result and no active replacement candidate.
- Keep the JPEG `known_gap` explicit after the rejected comparison; evaluation
  completion is not the same as eliminating the performance gap.
- Selection-only work remains conditional: integrate a future conforming
  candidate behind the non-default target, switch it in a dedicated revertible
  commit, retain stb until a user-authorized three-platform A/B matrix passes,
  and only then install a persistent same-run guard before removal.
- Keep a backend only when the evidence supports `qualified`,
  `native_by_necessity`, an explicit documented provisional exception, or a
  measured `known_gap` whose evaluated/rejected candidates and remaining
  research are recorded. Final stage exit still requires every such gap to be
  explained rather than silently treated as qualified.

### R6. Close stable native sources

- Vendor the selected exact revisions for the three dependencies still fetched;
  miniz, nlohmann/json, and zstd are the first three completed rows of the
  six-dependency closure set. A
  performance result may change a backend before its source is embedded.
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
