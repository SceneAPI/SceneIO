# I/O Optimization, Testing & Verification Plan

Status: complete for the original 23-codec O0-O5 scope. Its mmap, direct-sink,
inspection, differential, memory, and partial-read capability contracts now
cover the live 74-format registry; 37 formats expose 43 bounded selectors. This
status describes optimized I/O transport and bounded access; it does **not**
claim that every compression/parser kernel is the fastest viable backend.
Backend qualification remains available as a trigger-based post-R6 mechanism in
[`repository_organization_plan.md`](repository_organization_plan.md). The
measured libjpeg-turbo comparison is complete on MSVC and rejected for the
combined default after missing the frozen q95 comparative-quality floor; the
JPEG encode/decode gap therefore remains explicit with stb retained. The
reviewed, commit-sized verification checklist is
[`next_stage_implementation_checklist.md`](next_stage_implementation_checklist.md).
The finite, five-workload large-file comparison against pinned independent
providers is specified in
[`large_file_io_benchmark_spec.md`](large_file_io_benchmark_spec.md); its
machine-readable runs and consolidated report are the final local evidence
unit.
The remaining COLMAP large-model gap closed at `8a2b917`: removing exact
per-record vector reservations restored amortized-linear binary parsing without
changing the wire or record contract. The clean 256 MiB-class run completes
all seven operations and nine validation rows, including PyCOLMAP-backed
cross-read rows and a SceneIO partial-read check; SceneIO's read/write medians
are 2.397/1.067 seconds versus PyCOLMAP's 2.704/2.059 seconds. The earlier
bounded timeouts remain recorded as before-change evidence.
The user-directed lean closure policy accepts the verified R6 backends as
that release baseline without promoting its 124 provisional rows to
`qualified`; exhaustive candidate comparison is not an R6 prerequisite.
The post-R6 COLMAP dense, HDF5/hloc, Zarr, TIFF, E57, Parquet/Arrow,
OpenVDB, USD/USDZ, AVIF, WebM, RTMV, Ogg/Theora, NCore V4, and the bounded
EuRoC/ASL dataset unit bring the current ledger to 175 provisional, two
known-gap, and seven not-applicable operations without changing
that policy.

The 2026-08-03 EuRoC/ASL addition applies the same transport contract to a new
multi-file dataset adapter. Native IMU CSV accepts a contiguous mapped buffer,
returns owned vectors before the mapping closes, and streams deterministic CSV
directly to a file sink. Dataset inspection is metadata-only; typed
camera/IMU/time selection leaves image bytes lazy. On the generated 6.858 MB
five-run MSVC fixture, public mapped read reaches 319.7 MB/s with 0.118 MB
traced overhead, inspection uses 0.047 MB, and selection takes 2.081 ms versus
about 16.65 ms for full public read. This is the initial baseline for format
74, not a before/after throughput claim or a numeric release threshold.
The 2026-08-02 72-format correction changes no transport, compression kernel,
capability, or timing claim. It makes Theora/WebM/COLMAP DB inspection results
portable across the supported compilers, hashes libvpx's source manifest using
its canonical repository bytes, and measures three suite-order-sensitive
allocation paths by a three-operation median while preserving their strict
payload-relative ceilings. The exact local suite now passes 4,372 tests with
six documented skips after adding three benchmark-evidence tests. Commit
`5387350` passes hosted compiler run `30738228920`
and every dedicated platform job in CI run `30738228914`; that CI run's full
suite and 72-row smoke also pass. Its final strict guard exposed a benchmark
schema omission, not an I/O failure: animated AVIF's direct Pillow
inspect/selected-frame comparisons were declared but not emitted by the
generic path runner. The follow-up records those timings and gives path-range
and COLMAP DB image/pair selectors distinct required metric keys. The first
follow-up compiler run `30739519901` collects all 4,378 tests but its full job
stops at the stale 4,375 count assertion; the lifetime shard passes. At the
count-correction commit `67acc7b`, compiler-instrumented run `30740026804`
passes the exact 4,378-test suite and lifetime shard. CI run `30740026814`
passes the full suite, all platform/compiler shards, and the 72-row structural
smoke. Its terminal five-run guard measures animated AVIF frame selection at
16.8 MB versus 25.2 MB for full decode, then rejects that owned two-frame
result under the blanket 1 MB selector cap. The current narrow correction
requires animated AVIF selection to stay below both 18 MB and 75% of full-read
allocation; every other existing cap remains unchanged. A three-run local
remeasurement records 1.33x partial-read speedup and the same 25.2/16.8 MB
allocation reduction. At correction commit `54925ea`, compiler-instrumented
run `30741117526` passes the exact suite and lifetime shard, while CI run
`30741117473` passes every job and the five-run guard. Its animated AVIF row is
1.32x faster for the selected range with 25.2/16.8 MB full/partial allocation.
This closes hosted confirmation for the 72-format branch head. The one-pass
all-format smoke completes 72
rows with normalized structural SHA-256
`9d010021697a301eff99ac21203b9f66d042e66b81ccfd0bea7ebdce313b2851`;
this replaces the stale 67-row parent contract without changing a timing gate.
The first hosted correction run passed all dedicated platform shards but found
that libvpx's per-file rows had been generated from a stale CRLF worktree and
that upstream libtheora left-shifted a negative edge delta during the first
instrumented encode. An all-manifest audit found the same stale-CRLF provenance
issue in libogg and libtheora, so all three affected closures now hash canonical
LF blobs throughout. The documented three-file libtheora patch gives defined
arithmetic to bounded signed edge/motion deltas and 64-bit trellis masks; its
six-test parity module passes under the same local compiler instrumentation.
Normal optimized build selection is unchanged, as are public I/O behavior and
performance configuration.
The C3/C4 CI correction keeps those operation counts unchanged. Its SOG
writer uses a pinned deterministic transform and caches transformed
coordinates: repeated seven-run measurements on the 11.2 MB fixture report
34 MB/s for both the exact pre-correction build and the candidate, while the
candidate makes archive metadata byte-identical across the local MSVC/GCC
reproduction. The cache uses exactly 24 bytes per point and raised sampled
sink RSS by 4.8 MB on the 200,000-point fixture while traced Python allocation
remained 0.0 MB; this is the measured working-memory cost of retaining
throughput and deterministic bytes. The COLMAP consistency reader retains
mapped input plus exact owned vectors without an entry-count-sized link
reservation. The 54-codec checkpoint's deterministic benchmark-structure
guard covered all 54 then-live rows with normalized SHA-256
`fd3cf4a663e737971526afe5884f229237630a0f126b21a1c8ffcde9a6015e4e`;
the earlier 50-row family-extraction fingerprints remain historical evidence.
Exact-head normal run `30469273173`, instrumented run `30469271293`, and
nonpublishing three-platform package run `30470889876` pass at packaged source
`2253e0f`; this closed that 54-codec transport checkpoint.
Animated WebP subsequently extends the local transport contracts to 55 rows
and the buffer-backed differential/sink sweeps to 49. Its 55-row deterministic
structure capture has normalized SHA-256
`91fff73b8f1e8e599a4400a7de1f22c053704e89c0fef1ecee55a07703c44e80`;
cross-platform package evidence remains pending for that addition.
The then-current benchmark ownership work did not reopen O0-O5 or change codec
capabilities or implementation-performance claims. Points close at `45e2757`
with normal run `30244892746` and compiler-instrumented run `30244892600`.
Reconstruction closes at `76ed21b` with normal run `30247662591` and
compiler-instrumented run `30247662622`. Sequences close at `4b8c829` with
normal run `30250394890` and compiler-instrumented run `30250394906`. Splats
close at `cd32268` with normal run `30253301819` and compiler-instrumented run
`30253301871`. The complete sweep and specialized glTF/COLMAP/
image-directory orchestration are lower-owned by `io_bench/runner.py`;
`bench_io.py` is now an import-and-call CLI shim; `io_bench/runner.py` owns the
benchmark implementation. Runner commit `cf8d117`
passes normal run `30257105454` and compiler-instrumented run `30257105468`.
The final R3.2 behavior checkpoint is implemented locally: every sweep checks
the immutable 50 built-ins, runtime extensions are excluded from repository
qualification, and the 50-entry comparison ledger contains 33 timed providers
plus 17 reviewed property-specific exemptions. Strict mode propagates required
comparison failures and is now part of the retained CI performance guard.
The complete five-run strict guard passes; the exact local tree collects 3,339
tests and passes 3,335 with four documented skips, and Ruff is clean. All three
independent closure reviews and the exact 367-file-tree to 368-file-sdist to
81-member-wheel gate pass; a fresh installed environment contains only SceneIO
and NumPy. PyCOLMAP and `gsply` remain test-only parity support.

R6 package closure is complete at packaged source commit `105b301`. Exact-head
CI `30405666674`, native-runtime validation `30405666673`, and build-only
MSVC/manylinux2014 GCC 10/AppleClang package run `30406706115` pass; the PyPI
job is skipped. Independent inspection confirms one exact sdist and three
cp312-abi3 wheels, the NumPy-only Python runtime contract, all notices, and the
expected native payloads. The artifact hashes are recorded in
[`next_stage_implementation_checklist.md`](next_stage_implementation_checklist.md#r6-closure-evidence).
O0-O5 and the repository-organization gate are therefore closed; provisional
backend comparisons remain optional trigger-based work.
R3.3 closes at `811cb0d`; normal run `30300122309` and
compiler-instrumented run `30300122324` pass. The R3.4 candidate makes the
NumPy-only installed-wheel gate complete rather than representative: all 50
built-ins perform public write/read/inspect, every declared stream-capability
direction is paired with a successful corresponding public path call, and all
32 declared selectors across 28 partial-capable codecs run with zero
property-specific exemptions. Dedicated mmap and sink suites independently
prove the allocation semantics. The runner and expected operation set are
both derived from the installed built-in definitions and live capabilities.
The complete local suite passes 3,344 tests with four documented skips; Ruff
and the retained five-run strict O4/O5 guard pass. The first frozen 380-file
source tree produces a 381-file sdist and 81-member Windows ABI3 wheel, and a
fresh outside-repository SceneIO-plus-NumPy environment passes the complete
installed smoke.

R4.1 subsequently reorganizes only the native build description. Its four
focused CMake modules preserve the exact dependency block, compiler options,
source/link order, and generated MSVC/GCC 10 `_core` commands. The complete
five-run strict O4/O5 and mmap/sink allocation guard passes unchanged; no
timed implementation changed and no additional performance claim is made.
R4.1 is pushed at `b2cf5d4`; normal run `30310780347` and
compiler-instrumented run `30310780355` pass.

R4.2 closes at pushed commit `81e0e1c` and changes binding ownership only. One record table and
eight codec-family tables retain the exact registration order and expose a
validated private inventory for the 49 native/hybrid built-ins. MSVC,
manylinux2014 GCC 10.2.1, a focused 416-test I/O/architecture sweep, exact
3,354-node collection, and the same five-run guard pass. No codec loop,
transport adapter, fixture, or benchmark implementation changed, so R4.2 makes
no throughput claim. The complete suite passes 3,350 tests with four documented
skips, and Ruff is clean. The exact 398/399/81 source/sdist/wheel package gate
and fresh NumPy-only installed smoke pass. All three confirmation reviews are
clear. Normal run `30316577366` and compiler-instrumented run `30316577369`
pass that exact commit. R4.3 and final R4 qualification close at pushed commit
`da1d709`. All 40 native codec sources are family-nested; exact-tree MSVC/GCC
10, 398/399/81 package, public-snapshot, normal CI `30326256230`, and
instrumented `30326256137` gates pass. No codec loop changed and no throughput
claim is made.

R5.1 is complete after that R4 checkpoint. It introduces a
default-off, configure-time JPEG comparison seam and exact candidate ledger.
The ordinary wheel remains stb-only with its frozen public/core surface.
Isolated stb and SIMD-required libjpeg-turbo 3.2.0 qualification wheels build
and pass focused parity plus installed smoke on MSVC.

R5.2's production-path measurement implementation is complete. A frozen
97-cell local/122-cell remote-inclusive JPEG matrix compares installed stb and
libjpeg-turbo wheels against the same hashed corpus, retains raw paired
samples, and measures the direct/public mmap and sink surfaces alongside
quality, size, startup, repeatability, traced allocation, RSS, and package
cost. Fresh-process RSS uses a fixed small-fixture warm-up and measures the
first target-fixture operation. A generated receipt binds the candidate build
to its configured SIMD header. The binding clean-wheel MSVC report at
`7a88e7c` passes 1,596 of 1,597 frozen gates and records 4.787x encode and
1.782x decode median geomeans. libjpeg-turbo fails the q95 4:4:4 comparative
quality floor (`-0.058242 dB` versus required `-0.05 dB`) and is rejected as
the combined stable default. stb remains unchanged. The manual remote workflow
was not dispatched because no conforming candidate advanced beyond MSVC.

Scope: the compiled `sceneio._core` I/O path on `phase0-nanobind-core`.
Companion to `coverage_roadmap.md` (this makes its "Phase 7" hardening/perf work
concrete). Phase landing notes below are historical evidence from the commit at
which each phase closed. At the 2026-07-25 `a5e7fa4` implementation
checkpoint, local MSVC passes 2,919 tests with 4 skips. Normal CI
[30181287022](https://github.com/SceneAPI/SceneIO/actions/runs/30181287022)
passes the Linux suite, retained 50-codec performance guard, pinned GCC 10
job, and Linux/Windows/macOS portability matrix. Compiler-instrumented run
[30181287161](https://github.com/SceneAPI/SceneIO/actions/runs/30181287161)
collects all 2,923 tests and passes its complete and focused native jobs.
Nonpublishing release run
[30181286675](https://github.com/SceneAPI/SceneIO/actions/runs/30181286675)
builds and smoke-tests all three platform wheel sets plus the source archive.
The expanded transport/access tier is therefore cross-platform validated.
Per-codec backend qualification is tracked separately from O0-O5. The selected
default native-source intake is complete. Unmeasured candidate comparisons
remain an optional post-R6 backlog rather than a stage-exit gate. R6 package
review corrected and configure-checked the stable-ABI build path; local Windows
and Ubuntu builds use the expected stable extension names. Final build-only run
`30406706115` passes the exact-tree MSVC, GCC 10, and AppleClang package jobs
and downloaded-artifact inspection.

Post-0.2 format expansion inherits the same gates. The registry currently has
74 formats: 64 single-file containers, five directories, and five multi-file
formats. COLMAP SQLite
remains path-native; SOG, OBJ/MTL, and glTF/external buffers have explicit
multi-file adapters.
Generic HDF5 and the two documented hloc layouts are also path-native. They
use the optional optimized h5py/HDF5 provider while SceneIO owns schema
validation, native-record mapping, inspection, partial selection, and atomic
replacement. On representative 1.1/1.1/2.1 MB logical fixtures, three-run
local MSVC measurements recorded 515/531/337 MB/s writes and 919/422/871 MB/s
full reads for HDF5/hloc-features/hloc-matches. Metadata inspection was
1.93x/2.42x/2.93x faster than full materialization; the generic HDF5 named
read was 2.44x faster and avoided loading the 1 MiB unselected dataset.
Direct h5py provider timings remain visible in the committed harness rather
than being described as equivalent wrapper work.
Zarr, TIFF, E57, Parquet/Arrow IPC, OpenVDB, and USD/USDZ use the same
repository-owned path-adapter pattern. Their established permissive providers
perform optimized storage/parsing; SceneIO retains validation, record mapping,
inspection, transactional destination replacement, and partial-selection
policy. Every new path row runs direct provider cross-reads and reports
write/read throughput, traced allocation, resident growth, and inspection
latency in `bench/bench_io.py`. Parquet additionally reports named-column
selection. No new compressed payload is routed through a Python whole-file
`bytes` copy.

FC3 adds a dedicated E57 multi-scan harness for the canonical `ScanSet` path.
The selected reader uses a fixed 65,536-row libE57Format buffer and copies only the requested
half-open stored-row overlap. On the 113.25 MB logical local fixture this cut
traced peak from 151.00 MB to 11.33 MB versus direct `read_scan_raw` plus slice;
header inspection used 0.024 MB. Full reads and writes remain provider-buffered
and are reported without an optimization claim. See
[`e57_multiscan_benchmark.md`](e57_multiscan_benchmark.md).

The RTMV directory adapter extends the same O1/O5 path discipline to a fifth
directory format. It validates camera JSON and OpenEXR headers without decoding
pixels, retains owned absolute paths for RGB, depth, and optional segmentation
layers, and exposes bounded frame selection. A 25.2 MB synthetic eight-frame
fixture measured 3.79 GB/s path reads with effectively zero traced allocation,
while inspection and two-frame selection were 1.52x and 4.84x faster than full
metadata construction. RTMV is intentionally read-only because no canonical
SceneIO record preserves every source object and encoded layer byte-for-byte.

The Ogg/Theora extension applies the same O1/O3/O5 transport to pinned native
libogg/libtheora: mapped input is fed to libogg in bounded chunks, decoded
planes are owned, Ogg pages stream directly to file sinks, metadata inspection
allocates no frame arrays, and frame selection allocates only requested output.
The five-run 6.3 MB fixture measured 16 MB/s encode, 78 MB/s decode, effectively
zero traced mmap/sink allocation, 16.5x faster inspection, and 1.76x faster
selected-frame reads. Upstream x86-64 MMX/SSE2 dispatch is enabled on
GCC/AppleClang; MSVC x64 and non-x86 targets use the upstream portable kernel.

The expanded WebM path retains the established libwebp all-keyframe default
and adds direct libvpx temporal VP8/VP9 profiles. Input is still mapped,
decoded 4:2:0 planes are record-owned, file writes stream one header and one
cluster per encoded packet, inspection parses only EBML/frame tables, and a
selected range begins at the nearest preceding keyframe while allocating only
the requested output planes. The pinned portable upstream implementation uses
its native worker lanes without a system codec or general media framework.
Five local MSVC runs over 3.15 MB of RGB input measured temporal VP8 at
30.2 MB/s with one lane and 42.9 MB/s with automatic lanes (1.42x), temporal
VP9 at 20.0/38.6 MB/s (1.93x), and temporal decode at 58.5/98.1 MB/s. The VP8
and VP9 outputs were 0.906/0.794 MB versus 0.880 MB for the compatible
all-keyframe VP8 path. Same-configuration output is deterministic; because
libvpx worker partitioning may change lossy coding decisions, cross-lane
verification requires identical timing/layout and bounded decoded-sample
deltas rather than identical compressed bytes.

The AVIF extension inherits the O1/O5 read rules through a repository-owned
path adapter over the optional Pillow 12.3/libavif 1.4.2 provider. A read-only
mmap is retained until libavif finishes metadata or frame work; decoded pixels
are then owned by SceneIO. Still and animated inspection do not request a
frame, and animated reads expose a bounded frame-range selector. The provider
uses dav1d's decoder and libaom's threaded encoder. Pillow currently returns a
completed encoded payload before its path write, so AVIF correctly advertises
`streams_write = false`; a direct sink remains an explicit optimization gap
rather than an O3 claim. The base wheel remains NumPy-only and no FFmpeg/libav
path is added.

The bounded USD C2 asset path follows the same rule: texture sources stream in
1 MiB chunks into content-addressed USDA sidecars or stored USDZ members. A
generated 100,000-face/eight-material fixture with a 100 MiB asset measured
118.8/130.0 MB/s USDA/USDZ writes with 12.2 MB traced allocation, and
71.3/70.2 MB/s full reads on the local MSVC host. Inspection did not open the
asset. These are observational C2 rows, not cross-host numeric thresholds.
The same run found and removed a material-free allocation regression: binding
inspection had normalized the complete mesh even when no binding existed.
The unbound/direct paths now avoid mesh text entirely, restoring the generated
C1 full-read control from 47.15 MB to 44.03 MB traced (43.95 MB baseline).

The USD C7 release unit changes no USD codec kernel or data path. It retains the
paired C6 USD/USDZ measurement in `bench/BASELINE.md` as its no-regression
control and adds artifact-only checks: one verified source archive feeds the
wheel build, exact runtime assets are inventoried, and fresh NumPy-only plus
pinned TinyUSDZ environments run the installed public smoke. The prepared
hosted wheel matrix repeats the optional-provider smoke on Windows, Linux, and
macOS. Authorized build-only run `30701260601` passes that complete package
matrix at source `04a1749` with publication skipped. Primary CI run
`30701254315` passed its complete test step and every platform shard, then the
all-codec benchmark exposed Zarr 3.3 rejecting Linux's platform-native integer
dtype class during provider inference. SceneIO now presents supported
platform/generic numeric aliases to Zarr as fixed-width zero-copy views; v2/v3
oracle round-trips and the all-codec harness cover the repair before the final
exact-head hosted rerun.

At the C7 checkpoint, the refreshed local CI smoke completed without error for
all 67 then-live formats under Zarr 3.3.0. Its deterministic structural
projection contains 67
rows with normalized SHA-256
`817b355a8fb752025e51b3afe658524ebfa40cd6caffc8cd9e927a7117e07f65`.
The exact 4,310-node local suite passes 4,304 tests with six documented skips;
Ruff, workflow parsing, diff checks, and all three review lenses are clean.
Final implementation source `47eb2e1` passes exact package run `30703473199`
and compiler run `30703469313`. CI run `30703469317` passes the suite,
67-format smoke, deterministic structure, and every platform shard. The full
five-run guard completes and reproduces the documented TinyUSDZ boundary:
USD/USdz full reads retain 8.5 MB traced while inspection retains 5.7 MB; it
also measures Parquet full/selected at 18.4/1.6 MB. The globalized guard had
incorrectly applied the legacy 1 MB metadata/selection cap to those logical
provider/output allocations. The correction retains that absolute cap for
every other applicable row. USD/USdz inspection must remain below 8 MB and 80%
of full; Parquet selection must remain below 2 MB and 25% of full. The exact
4,317-node local suite passes 4,311 tests with six documented skips. At
correction source `b16ee1c`, final CI `30705438186` passes the complete suite,
all platform shards, 67-row smoke, deterministic structure, and five-run
guard; compiler run `30705438179` passes both jobs. Its downloaded guard has
67 successful rows and reproduces the qualified 8.510/5.718 MB USD full/inspect
and 18.354/1.577 MB Parquet full/selected relationships.

The 2026-07-30 scale-16 profiling follow-up removed two wrapper hot spots.
Already-native contiguous HDF5 arrays now pass directly to the native record
or h5py dataset constructor, reducing traced full-read peak from 33.6 MB to
16.8 MB and improving the measured five-run read/write medians from
1,658/1,777 MB/s to 2,266/2,921 MB/s. The hloc match writer replaced its
full-array `numpy.unique` validation with an ordered fast path plus a
sort-and-adjacent fallback, improving the same fixture from 95 to 1,417 MB/s.
Output validation remains unchanged. Native hloc decode conversion and
high-cardinality metadata traversal were measured separately rather than
being hidden behind the aggregate payload benchmark. The generic HDF5
follow-up now resolves selected paths without a global walk and combines full
link/object validation into one traversal. On a generated 5,000-dataset file,
one named read changed from 447.016 ms to 0.522 ms and full inspection changed
from 459.803 ms to 363.624 ms. Partial reads validate root metadata plus each
selected path and its ancestors; unrelated objects are outside that partial
result. Dense hloc match rows now convert directly into final native ragged
storage without Python masks, stacks, or concatenation. On the scale-16
fixture, read throughput changed from 843 to 1,194 MB/s, traced peak from
62.9 to 33.6 MB, and sampled RSS growth from 69.3 to 45.7 MB.
High-group-count hloc object enumeration and native feature-descriptor
transposition remain measured follow-up work.
The latest record waves add the four calibration formats over `CameraRig`, g2o
over `PoseGraph`, `colmap_db` over
`ColmapDatabase`/`FeatureSet`/`MatchGraph`, polygonal PLY over `Mesh`, and
OBJ/MTL over `Mesh` + `MaterialSet`, STL/OFF over `Mesh`, plain glTF/GLB over
`MeshScene`, and LAZperf-backed LAZ over `PointCloud`; each inherits direct
file sinks, metadata inspection, partial reads where meaningful, and the
all-codec differential/memory harness.
The latest dense family adds COLMAP MVS depth/normal matrices, consistency
graphs, and fused visibility. All four have mmap buffer reads, direct sinks,
metadata inspection, and independent binary oracles; depth and normal expose
bounded windows. Their lazy canonical/PMVS/CMP workspace coordinator remains
outside the codec registry and never decodes encoded image payloads.

The C1d MAXX database read expansion retains the same optimized path-native
transport. On the representative 9.9 MB database, three-run local MSVC medians
measure 1,067 MB/s full/path read and 158 MB/s direct write with no
payload-sized traced Python allocation. Metadata inspection is 4.12x faster
than full decode, while indexed image and pair reads are 9.05x and 9.53x
faster. The MAXX field expansion therefore adds no measured I/O-path
regression. C1e now adds exact 3.13/4.1.1/current/MAXX profile sinks on the
same path-native SQLite route, with bounded traced allocation, explicit
conversion analysis before destination access, and in-transaction
schema/integrity verification. The harness exposes
`--colmap-db-profile` so each exact writer branch is measured independently.
On the 9.65 MB generated fixture, three-run exact-profile medians range from
150-160 MB/s write and 1,018-1,141 MB/s read. Traced write allocation rounds
to 0.000 MB and mapped read allocation to 0.003 MB for every profile.

The latest sequence wave adds owned `ImageSequence` storage, lazy image
directories, and an original dependency-free raw Y4M codec. On representative
6.3 MB fixtures, Y4M measured 2,574 MB/s public mmap read while removing the
full 6.3 MB traced input copy; its direct sink removed the matching output
copy. Metadata inspection was 33.48x faster than full decode and a middle
one-sixteenth frame range was 4.19x faster with bounded selected-frame RSS.
The lazy directory adapter retained encoded paths, used bounded 1 MiB copying,
and measured 1.45x inspection / 1.61x selected-range gains without decoding
pixels.
Animated WebP adds packed owner-safe RGB/RGBA frames over the pinned libwebp
animation APIs. Its mapped public read and direct sink remove the encoded-size
Python copies, while metadata-only inspection avoids frame decode. Exact
timing, loop/background metadata, and independent Pillow cross-read/write
parity are part of the codec gate.
APNG uses a repository-owned animation container/state layer over the pinned
lodepng/deflate substrate. It has the same mmap and direct-sink transport,
metadata-only inspection, exact accepted-profile timing, and independently
checked compositing semantics. The benchmark keeps its measured Pillow
comparison visible instead of treating backend throughput as equivalent.

The representative LAZ point fixture uses a 12.0 MB positions-equivalent
throughput denominator while both compared records also carry matching RGB
and intensity arrays; it encodes to 14.6 MB. Five-run local MSVC medians
measure 66 MB/s direct-sink write, 235 MB/s buffer decode, and 184 MB/s public
mmap decode on that denominator. The mapped read and seekable direct sink each
remove the entire 14.6 MB traced Python allocation. Header inspection is
1,335× faster than full decode and a middle one-sixteenth point selection is
3.17× faster while materializing only overlapping 50,000-point chunks.

The representative COLMAP database fixture contains 9.65 MB of logical
features and match data in a 9.92 MB SQLite file. On local MSVC it measured
1.41 GB/s full native read, 0.81 ms metadata inspection (8.50× faster), and
0.53/0.42 ms one-image/one-pair reads (13.10×/16.31× faster), while traced
Python allocation stayed below 0.05 MB on every native path.

The representative OBJ fixture contains 14.7 MB of canonical mesh arrays and
encodes to 53.8 MB. Its mapped public read removes the entire 53.8 MB Python
input allocation, its direct sink removes the matching output allocation, and
metadata inspection is 2.12× faster with sampled RSS reduced from 265.5 MB to
53.8 MB. Replacing per-scalar stream construction with bounded canonical float
appends under an explicit C numeric locale improved deterministic write
throughput from 7.4 to 20.4 MB/s without changing round-trip values or output
when the process uses a comma-decimal locale.

The representative STL/OFF fixtures extend the same guarantees to mesh
triangle soup and indexed polygons. Five-run local MSVC medians measured STL
at 1,021 MB/s write and 935 MB/s public mmap read, and OFF at 206 MB/s write
and 396 MB/s public mmap read. Mmap/direct-sink traced allocation drops from
5.57/5.57 MB to about 0.01/0.001 MB for STL and from 7.56/7.56 MB to the same
bounded overhead for OFF. Inspection is 3.67Ã—/1.98Ã— faster than full read,
and 1/16 face selection is 3.26Ã—/1.21Ã— faster.

Plain glTF/GLB extends the same contract to a scene-preserving multi-primitive
record. On 13.2/14.7 MB canonical fixtures, five-run local MSVC medians measured
904/948 MB/s in-memory decode and 739/751 MB/s public mmap decode, close to the
trimesh oracle. Mmap removes 12.0/13.3 MB of traced Python allocation. Native
file sinks remove the same output-sized allocation and use one encode for the
paired JSON/BIN output. Metadata inspection is 220x/201x faster than full read;
one-of-four primitive selection is 4.29x/3.87x faster and reduces sampled RSS
from 26.4/29.2 MB to 5.1/5.7 MB.

**Committed historical scope (decided):** the **full O0-O5 program**, applied
**uniformly to the original 23 codecs**, with **qualitative** success criteria
— every step must show a
*measured* improvement with *no regression* and *bit-exact correctness*; no hard
numeric SLAs are bound. Measurement orders the work and proves each gain; it does
**not** gate whether a phase happens (all phases are in scope).

## 0. Guiding principle — measure to order & verify (not to gate)

The representation layer is already near-optimal (zero-copy SoA records →
numpy/torch/DLPack; native decoders; GIL released). **Before O1**, the
file-I/O model used the deliberately simple whole-file `_bytes_reader`: read
materialized the whole file as Python `bytes` before decode, while writes still
materialize the whole output as `bytes` before disk. O1 replaced the read side,
O3 removed the Python output copy, and O5 added metadata and bounded subset
access.

So the harness comes first — but because scope is full and uniform, it decides the
*order* of the sweep (worst `sceneio/oracle` ratios first) and supplies the
before/after numbers, not whether a codec or phase is included.

Every work item follows the same loop: **implement → differential + memory test →
benchmark delta → fable memory-safety review → commit.**

---

## Phase O0 — Baseline & measurement harness (first)

Permanent verification tool and the ordering input for the sweep.

| Piece | What | Where |
|---|---|---|
| Throughput bench | read+write MB/s, Mpix/s (images), Mpts/s (clouds), **original 23-codec scope** | `bench/bench_io.py` |
| Peak-memory bench | `tracemalloc` peak + RSS for read & write | same harness |
| Oracle comparison | same op via Pillow / laspy / OpenEXR / numpy / pycolmap / gsply | reuse `[test]` oracles |
| Fixtures | small (typical) + large (100 MB–1 GB synthetic) per format | generated builders under `bench/io_bench/{fixtures,oracles}/`, with specialized cases temporarily facade-owned |

**Exit criteria:** baseline table across the original 23 codecs, committed and reproducible
(pinned methodology: warm/cold split, median of N). It orders the O1+ sweep
(worst-ratio codecs first); every codec and phase proceeds regardless.

---

## Phase O1 — mmap-backed reader (complete)

Replace the whole-file `Path.read_bytes()` with a memory-map handed to the codec as
a **zero-copy buffer view**, removing one full-file copy on read and letting the OS
page lazily.

- **Adapter:** `_mmap_reader` (Python `mmap`, cross-platform) becomes the default
  for every single-file codec; mmap-unavailable and empty files use a
  same-open-stream bytes fallback. `_bytes_reader` remains only as a legacy
  comparison helper.
- **Core signature:** every `_core.read_X` accepts an exact read-only,
  C-contiguous unsigned-byte **buffer-protocol** object (mmap / memoryview /
  numpy `uint8`), not only `nb::bytes`, verified to NOT copy. One shared
  buffer-accepting entry per codec.
- **Lifetime:** decode-into-vectors codecs release the mmap after decode (record
  owns copies) — the safe O1 default. Raw formats keep it alive in O2.
- **Uniform application:** all 21 single-file codecs get the mmap path and the
  differential + memory sweep; the two COLMAP directory codecs already consume
  paths directly. The payoff is largest on the big binary formats
  (LAS/EXR/PLY/SPZ/npy), but all original 23 remain in the harness and API E2E
  coverage.

**Testing (per codec):** `read(mmap) == read(bytes)` **bit-exact**; a peak-memory
test asserting the mmap path does not allocate a whole-file `bytes`; empty/
truncated/locked file over the mmap path. **Verify:** harness delta (read peak-
memory drops by ~file-size). fable **memory-safety** review is mandatory (mmap
use-after-unmap is the top risk).

**Landed:** the 21 single-file codecs accept the shared read-only contiguous
`sio::ByteView` and use `_mmap_reader`; the COLMAP binary/text directory codecs
already take paths and read their component files directly in C++, so no Python
whole-file `bytes` exists there. Empty files and mmap-unavailable files use the
same already-open stream for their bytes fallback. Extensionless detection now
reads only its 16-byte prefix. The differential sweep covers bit-exact bytes/mmap results,
post-unmap lifetime, empty/truncated/mutated data, Windows exclusive locks, and a
16 MiB `tracemalloc` bound plus exact exporter/core pointer identity. The
23-codec harness includes public-path throughput, traced allocation, sampled
RSS, cold-cache hints, and generated scaling; every mapped read peak changed
from the encoded file size (up to 56.5 MB normally and 113 MB generated) to
below 0.05 MB. A local Linux run passed the full in-tree suite under ASan/UBSan
and an explicit pre-shutdown LSan check, excluding the unsanitized gsply/Numba
and pycolmap native oracle stacks that normal CI retains. The committed workflow repeats it and raises
the backing-store mutation sweep from 3 to 100 cases on its schedule. Scheduled
execution begins once this workflow reaches the default branch. The branch
workflow has also passed remotely with the full suite and explicit pre-shutdown
leak check.

---

## Phase O2 — Zero-copy decode for raw/uncompressed formats (complete)

Evaluated uniformly; applies where the on-disk payload *is* the array — mmap +
return an ndarray **view** over the mapped bytes, mmap kept alive by the array.
The owner is a private, read-only buffer exporter that retains the exact
`Py_buffer`; this both blocks `mmap.close()` while a view exists and avoids
exposing a manually releasable `memoryview` as `ndarray.base`.
The public adapter maps these raw formats with private copy-on-write access but
presents a read-only memoryview to C++; this is a last-resort guard for consumers
such as `torch.from_numpy` that may ignore NumPy's non-writeable flag. The private
`_MappedArray` subtype exports DLPack through an isolated C-contiguous copy,
because DLPack has no read-only bit.

| Format | Zero-copy? | Note |
|---|---|---|
| `.npy` | ✅ high value | contiguous typed array; view directly (endianness/contiguity permitting) |
| `.flo` | ❌ canonical record owns values | `FlowField` carries format semantics that a bare mapped ndarray cannot represent |
| `.pfm` | ❌ | mandated bottom-to-top rows require a row flip; a negative-stride mapped view is unsafe for common DLPack normalization |
| uncompressed `.las` | ❌ | needs quantize→f32 + origin rebase (a real transform) |
| png/jpeg/webp/exr/spz/npz | ❌ | compressed — a decode is physically unavoidable |

The compressed codecs pass through O2 unchanged (nothing to view); the raw ones get
the zero-copy path. Uniform *evaluation*, format-nature-limited *application*.

**Testing:** view equals copy-decode bit-exact; **lifetime test** — the array
outlives the file handle (`gc.collect()` then still-valid, the Image lifetime
pattern); mutation isolation. **Verify:** npy read peak-memory → ~0 above the mmap.

**Landed:** `_core.read_npy_view` backs the public NPY registry path. It views
native-endian C-order payloads and preserves all 12 supported dtypes;
byte-swapped and multi-dimensional Fortran payloads retain the canonical
owned-copy fallback. Every direct view is read-only, aliases
the exact mapped payload address, pins the export until all derived views die,
and remains valid after the file handle closes and `gc.collect()` runs.
On Windows this intentionally keeps the mapped file locked for the array's
lifetime. The mmap-unavailable/empty-file fallback remains the copy decoder.
Writable Torch interop is process-safe and file-isolated: DLPack receives an
owned copy, while the private mapping prevents a `torch.from_numpy` alias from
writing through to the source file. PFM was evaluated but keeps its canonical
owned, positive-stride row-flip decode: exposing the stored row order as a
negative-stride view can make ordinary `np.asarray` + DLPack consumers abort.

The historical local MSVC benchmark measured public-path throughput of 63.6
GB/s for warm mapped NPY fixtures. FLO was subsequently consolidated onto the
owning `FlowField` representation, so its former mapped-ndarray result is no
longer part of the API. The 16 MiB NPY traced-allocation bound plus exact
address identity remained green. The final
Windows gate passed 1,133 tests (3 optional skips); the full instrumented Linux
gate passed 1,070 tests (44 expected oracle/platform skips) under
ASan/UBSan/LSan. The memory-safety, correctness, and test-soundness review
lenses all signed off with no remaining blockers.

---

## Phase O3 — Streaming writes (all codecs) (complete)

The 21 single-file writers now share a compiled file-sink path. Each existing
encoder still constructs the native C++ output required by its library/format,
but `emit_bytes()` writes that buffer directly through the lazily opened file's
native descriptor instead of exposing its pointer to Python or copying it into
a second, output-sized Python `bytes`.
The low-level `write_X(record) -> bytes` APIs remain unchanged. The two COLMAP
directory writers already wrote their three outputs directly and are covered by
the same 23-codec differential sweep.

The sink opens the Unicode Python path lazily only after validation/encoding
succeeds, so guard failures do not truncate an existing destination. It handles
partial writes, closes on every exception path, and restores its thread-local
scope after success or failure. The raw encoder pointer is never handed to an
overridable Python `write()` method. Overridable `open`/`fileno`/`close`
callbacks run with sink interception suppressed. NPY, NPZ, and PFM finish all
NumPy/DLPack/mapping protocol conversion before activating the sink, so those
arbitrary Python callbacks can re-enter an encoder without interleaving the
outer file. FLO accepts an already validated `FlowField` directly.

**Testing:** sink-written file is byte-identical to the buffer writer for all 21
single-file codecs; direct/public directory outputs are identical for the other
two. Cross-platform tests cover Unicode paths, descriptor failures,
deterministic short native returns and failure after partial progress,
native-sink pointer isolation, callback/protocol reentrancy, scope restoration,
and non-truncation after rejected conversion or encoding. A 16 MiB NPY write
proves the sink does not allocate an output-sized Python object. Final local
gates: 1,150 passed / 3 skipped on MSVC and 1,087 passed / 44 optional-platform
skips under ASan/UBSan/LSan on Linux. The memory-safety, correctness, and
test-soundness review lenses all signed off with no remaining blockers.
The current repository-organization checkpoint gives these O3 behaviors
focused ownership in `tests/test_io_streaming.py`; the canonical FLO sink is
covered with its `FlowField` integration tests and the shared deterministic
buffer-codec builder.

**Measured:** every single-file `tracemalloc` peak fell by approximately the
encoded size (largest: XYZ 56.5 MB → 0.0 MB, LAS 26.0 → 0.0, EXR 12.5 → 0.0,
Gaussian PLY 11.2 → 0.0, NPY/FLO 8.4 → 0.0). The final seven-run MSVC sweep
showed no material throughput regression against the legacy
`bytes + Path.write_bytes` route; representative sink gains were NPY
1.94→2.88 GB/s, FLO 2.07→2.96 GB/s, Gaussian PLY 1.47→2.00 GB/s, and PNG
45→46 MB/s.

---

## Phase O4 — Intra-file parallelism / SIMD (complete)

The measured hot paths now use deterministic bounded work partitioning. A shared
helper selects at most eight automatic lanes, keeps small inputs serial, joins
every started worker on both success and exception paths, and rethrows worker
errors only after joining. Private lane controls retain a true one-lane
differential reference.

- **XYZ:** rows are formatted independently into fixed-capacity blocks, then
  compacted in order. This preserves the previous bytes exactly while avoiding
  synchronized appends.
- **LAS:** decode, quantized bounds, and fixed-record packing run over disjoint
  point ranges. The writer pre-sizes its record area instead of repeatedly
  growing it.
- **EXR:** large planar/interleaved transforms use bounded lanes, and TinyEXR's
  independent ZIP scanline blocks use up to eight workers.
- **PNG16:** endian transforms use contiguous, branch-light blocks. Whole-codec
  throughput is compression-dominated, so the measured write gain is small and
  read throughput remains neutral within run-to-run noise.
- **WebP lossless:** the old method-4/effort-100 configuration is now method 5
  with balanced effort 75, while `thread_level` is enabled. Libwebp schedules a
  side worker only when its analyzed lossless configuration has independent
  candidates; a structured palette fixture and a private launch counter prove
  that real branch under the production defaults. The lossy path retains its
  prior method-4/worker-off behavior.

Enabling TinyEXR workers exposed an upstream malformed-input race: distinct
offset-table entries could name the same destination scanline block. The local
vendored patch atomically claims aligned destinations before decode, rejects
duplicates/overlaps, joins already-started workers if thread construction
throws, publishes channel ownership before later allocations can fail, reserves
worker vectors before in-place thread construction, and uses per-block encode
error strings. `tinyexr/COMMIT.txt` pins these changes so a re-vendor cannot
silently drop them.

**Testing:** encoded bytes are identical for 1 vs N lanes for XYZ, PNG16, EXR,
and LAS; decoded arrays/metadata are bit-exact; WebP worker-off/on bytes match
and the launch counter proves the side-worker branch; the pre-O4 EXR SHA-256 is
pinned; malformed overlapping EXR scanline chunks must reject. Automatic
threshold selection and background-worker exception propagation are directly
covered. The 23-codec parity/E2E suite is unchanged.

**Measured:** the final seven-run MSVC sweep recorded the WebP balanced default
12→34 MB/s (2.75×), WebP default-config palette worker-off/on
10→19 MB/s (1.93×), XYZ formatting 20→101 MB/s (5.16×), LAS write
347→1,054 MB/s (3.03×) and read 1,997→2,765 MB/s (1.38×), and EXR
planar read 1,133→1,293 MB/s (1.14×). PNG16 write/read measured
68→69 / 417→421 MB/s (1.02× / 1.01×) in that run. PNG16 and EXR
planar-write deltas cross 1.0 under ordinary run-to-run noise and are treated as
neutral rather than claimed speedups; TinyEXR scanline workers still account for
the large whole-codec EXR improvement over O3. Final local gates passed 1,165
tests / 3 optional skips on MSVC and 1,102 / 44 optional-platform skips under
ASan/UBSan/LSan on Linux. CI retains the all-format smoke artifact and adds a
paired directional guard for the stable high-signal O4 rows plus deterministic
mmap/file-sink traced-allocation bounds.

---

## Phase O5 — Partial / lazy reads (complete)

The current repository-organization checkpoint moves retained inspection
verification into `tests/test_io_inspection.py`. Its 47 tests and three local
helpers are unchanged, preserve all 76 collected suffixes, consume the shared
44-codec case builder, and remain explicit in the Windows/Linux/macOS
platform job. Exact commit `0e21e27` passes normal run `30278777267` and
compiler-instrumented run `30278777173`. Partial-family organization begins
with unchanged DMB/FLO behavior in `tests/test_io_partial_arrays.py`; the
cross-family differential remains shared. The following image unit moves 10
Netpbm/WebP nodes unchanged into `tests/test_io_partial_images.py` and lowers
two shared window assertions without changing the optimized I/O paths. Exact
image commit `d198560` passes normal run `30285128366` and
compiler-instrumented run `30285128448`. The mesh unit moves its unchanged
face-range semantic and mapping-close behavior into
`tests/test_io_partial_meshes.py`. Exact mesh commit `4294dbe` passes normal
run `30287854716` and compiler-instrumented run `30287854692`. The point unit
moves 13 unchanged XYZ/LAS nodes into `tests/test_io_partial_points.py` and
lowers their shared range assertion. Exact point commit `ac1a4d1` passes
normal run `30290617469` and compiler-instrumented run `30290617607`. The
reconstruction unit moves 15 unchanged COLMAP nodes into
`tests/test_io_partial_reconstruction.py` and lowers the one fresh-process RSS
helper shared with the broad suite. Follow-up selector commit `b5e5c55` passes
normal run `30296172958` and compiler-instrumented run `30296174522`. The final
sequence/splat ownership audit contract-pins their already family-owned
partial behavior and the seven deliberately cross-family tests that remain
shared. The optimized I/O paths remain unchanged.

New public surface, applied to every format for which it's meaningful:
- header-only `inspect(path)` → dims/count/dtype/channels without a full decode
  (all formats have a cheap header);
- pixel-window (images), point-subset (clouds), single-image (COLMAP) reads where
  the container permits.

**Testing:** partial read equals the slice of the full read; `inspect` matches the
decoded record's shape/dtype. **Verify:** header-only/partial peak-memory and
latency vs the full read.

**Inspection landed:** `sceneio.inspect(path, format=None)` covered all original
23 codecs at O5 closure
and returns frozen `Inspection` / `ArrayInspection` metadata. Binary codecs read
only public headers (NPZ decompresses member headers only; legacy SPZ inflates
its 16-byte prefix), while headerless text is streamed. XYZ, transforms.json,
OpenMVG, and COLMAP text use small GIL-released compiled metadata paths so the
probe does not create Python-sized mirrors of the file. The all-codec
differential compares shape/dtype/counts with a full decode, a generated 128 MiB
NPY fixture holds peak Python allocation below 256 KiB, fresh-process RSS bounds
cover large NPY/XYZ/COLMAP, valid/malformed JSON, and capped text-token/line
scanners, and format-specific malformed/truncated header matrices normalize to
`FormatError`. JSON scene metadata uses bounded SAX passes rather than a
document DOM. The benchmark times operations without tracemalloc, measures
traced allocation separately, and records sampled RSS beside full reads; CI
directionally guards latency, traced allocation, and RSS on the stable large
binary rows. Transforms/OpenMVG full-read latency also has a coarse
full-read/SAX ratio sanity bound, which catches severe decode-path regressions
rather than allowing a much slower denominator to inflate the inspection gain;
the committed five-run baseline remains the historical control for smaller
timing movement.

**Partial reads landed:** `sceneio.read_partial()` requires exactly one
half-open pixel `window`, half-open point/face/state range, persisted COLMAP
`image_id`, unordered database `pair`, or safetensors name/slice selector.
Bounded pixel paths cover PFM, binary P5/P6 Netpbm, lossless VP8L WebP, FLO,
and scalar DMB; point paths include XYZ, PTS, binary PLY/PCD, LAS, Gaussian
PLY, and SPLAT. Binary/text COLMAP return one image and its camera; COLMAP
SQLite returns one `FeatureSet` or one pair `MatchGraph`; safetensors returns
only requested tensors or leading-axis slices. Unsupported compressed/text
variants reject rather than disguising a full decode as a partial read.

Mesh PLY, STL, and OFF additionally accept `faces=(start, stop)`. Mesh PLY
retains the complete vertex domain, slices every face/corner field, clips and
renormalizes primitive ranges, and validates skipped faces. OFF likewise
retains its complete indexed vertex domain; STL returns a local canonical
triangle soup. On the 28.0 MB canonical mesh-PLY
fixture, the five-run MSVC median improves from 96.918 ms full decode to
72.240 ms for a 1/16 face selection (1.34x); sampled RSS falls from 63.4 MB to
42.1 MB with no traced Python payload allocation. A generated 50.0 MB fixture
proves that a skipped 12.5-million-corner face is not retained.

The 52-case focused suite compares values, dtypes, and convention metadata
against full-read slices across binary Netpbm type/channel combinations,
lossless RGB/RGBA WebP windows, every automatic XYZ layout plus forced normals,
and LAS point formats 0–10, including lossless internal waveform sidecars for
4/5/9/10. It also covers non-native-endian payloads,
empty/out-of-range/truncated selectors, mapping lifetime and retained-exception
lock release, COLMAP names over 1 MiB, missing point containers, and bounded
malformed observation/name handling. COLMAP text applies the same 1 MiB limit
to non-name tokens in full and partial readers while leaving selected image
names unbounded.

The final post-fix five-run MSVC sweep recorded directional latency gains for
every guarded partial row: 1.70×–85.11× on material operations, with the
already-zero-copy FLO path effectively tied at displayed precision.
Representative results were Netpbm 8.35×, LAS 11.21×, Gaussian PLY 19.55×,
SPLAT 18.79×, PFM 10.25×, binary COLMAP 53.19×, and text COLMAP 85.11×.
Sampled RSS fell to 0.0–1.4 MB for those material binary paths.
XYZ still scans mapped text to validate record boundaries, so kernels may
charge the entire file mapping to RSS even though no input copy is made. Its
guard caps resident growth at the encoded file size plus 8 MB instead of
requiring a platform-dependent full/partial delta. FLO and
COLMAP are too small for a stable RSS signal but retain directional latency and
allocation checks. Final gates passed 1,289 tests / 3 optional skips on Windows
and 1,208 / 62 expected oracle, interop, platform, and RSS skips under the
instrumented Linux ASan/UBSan/LSan build. The correctness, memory-safety, and
test-soundness review lenses signed off with no remaining blockers.

---

## Testing strategy (correctness bar never moves)

The original 23 per-codec **parity suites + the public-API E2E test remain the
ground-truth oracle**. Optimizations added exactly these guards across the
**original 23-codec scope**; the registry-driven equivalents now cover all 74
built-ins and all 43 selectors exposed by 37 formats:

1. **Differential (path-equivalence) tests** — for every fast path: `fast == slow`
   **bit-exact** (mmap==bytes, zero-copy==copy, sink==buffer, partial==slice). One
   parametrized sweep; the parity suites already prove `slow == oracle`.
2. **Memory-bound tests** — peak allocation for a large-file read/write stays
   bounded (mmap must NOT materialize a whole-file `bytes`); `tracemalloc` asserts.
3. **Large-file tests** — a generated multi-hundred-MB fixture per format; bounded
   memory + correctness.
4. **Lifetime/ownership tests** — zero-copy arrays outlive their file handle; no
   use-after-unmap.
5. **Edge/fuzz** — mmap on empty/truncated/locked files; existing malformed suites
   re-run through every fast path.

---

## Verification (prove it helped AND stayed correct)

| Instrument | Proves | Cadence |
|---|---|---|
| Benchmark harness (O0) | measured improvement and comparable throughput | per-item; all-format smoke + stable-gain guard in CI |
| `tracemalloc`/RSS deltas | peak-memory dropped as expected | per-item |
| Differential correctness | fast-path == slow-path == oracle, bit-exact, all codecs | CI, every run |
| **ASan/UBSan/LSan CI job** | no mmap-lifetime/leak/UB (the class the reviews caught by hand) | CI (landed O1) |
| Differential fuzzer | malformed bytes/mmap backing-store equivalence | scheduled CI (landed O1) |
| Randomized oracle triangulation | random valid/malformed fast==slow==oracle | pending nightly expansion |
| fable adversarial review | memory-safety of each mmap/lifetime/sink change | per-item |

Success is **qualitative**: a *measured* improvement (direction, not a bound) with
**zero regression** and bit-exact correctness — not a numeric SLA. The **sanitizer
CI job is the linchpin**: it de-risks the mmap/lifetime/sink work and retroactively
guards the whole tree (it would have caught the NaN→cast UB and the stb short-read
mechanically).

---

## Sequencing & effort

```
O0 harness+baseline ─┬─► O1 mmap reader (all codecs) ─► O2 raw-format zero-copy ─► (re-measure)
                     └─► ASan/UBSan/LSan CI (lands with O1)                            │
                                                                                       ▼
                                              O3 streaming writes (all) ─► O4 threads/SIMD (hot paths)
                                                                                       │
                                                                                       ▼
                                                                         O5 partial/lazy-read API
```

- **O0** ~1 unit. Harness + baseline; orders the sweep.
- **O1 + ASan CI** ~2–3 units. Structural read win + the safety net, all
  original 23 codecs.
- **O2** ~1–2 units. Zero-copy for the raw formats.
- **O3** ~2 units. Sink writers, all original 23.
- **O4** ~1–2 units. Thread flags + SIMD on the flagged loops.
- **O5** ~2–3 units. New inspect/partial API.

The harness re-measures between phases so the sweep order stays honest, but all
phases are committed.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| mmap use-after-unmap (top risk) | ASan CI + lifetime tests + fable memory-safety review, every O1/O2 item |
| concurrent input mutation / POSIX shrink → race or `SIGBUS` | byte-stable input required through every mapped array/derived-view lifetime; atomic path replacement is safe |
| Windows vs POSIX mmap | drive mmap from Python's cross-platform `mmap` at the adapter; keep the C++ side buffer-agnostic |
| binding copies or accepts a mutable exporter | strict pinned `Py_buffer`, pointer-identity and memory-bound tests |
| Zero-copy record lifetime (O2) | retain an uncloseable private `Py_buffer` owner; test original + derived views outlive the handle |
| Sink writers diverge from buffer writers | byte-identical differential test per codec (O3) |
| Uniform sweep = large surface | the parametrized differential/memory tests scale across codecs; harness auto-covers all |
| Benchmark noise → wrong order | pinned methodology (warm/cold split, median of N); commit the harness |

## Definition of done (per item)

**Bit-exact vs the slow path and the oracle**, a *measured* throughput/memory
improvement in the committed harness with **no regression**, green under
ASan/UBSan/LSan, and a fable memory-safety sign-off. Correctness is never traded
for speed.

For the expanded stable tier, this per-item gate is necessary but not
sufficient: every codec also needs a `bench/PERFORMANCE_STATUS.toml` entry and
a measured comparison against the best viable permissive upstream backend
before its kernel can be marked `qualified`.
