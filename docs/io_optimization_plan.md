# I/O Optimization, Testing & Verification Plan

Status: complete — O0–O5 landed. Scope: the compiled `sceneio._core` I/O path on
`phase0-nanobind-core`. Companion to `coverage_roadmap.md` (this makes its "Phase 7"
hardening/perf work concrete).

Post-0.2 format expansion inherits the same gates. The registry currently has
41 codecs (38 buffer-backed entries, one path-native SQLite database, and two
COLMAP directory-only entries; SOG also exposes an unbundled multi-file path).
The latest record wave adds the four calibration formats
over `CameraRig`, g2o over `PoseGraph`, and `colmap_db` over
`ColmapDatabase`/`FeatureSet`/`MatchGraph`; each inherits direct file sinks,
metadata inspection, partial reads where meaningful, and the all-codec
differential/memory harness.

The representative COLMAP database fixture contains 9.65 MB of logical
features and match data in a 9.92 MB SQLite file. On local MSVC it measured
1.41 GB/s full native read, 0.81 ms metadata inspection (8.50× faster), and
0.53/0.42 ms one-image/one-pair reads (13.10×/16.31× faster), while traced
Python allocation stayed below 0.05 MB on every native path.

**Committed scope (decided):** the **full O0–O5 program**, applied **uniformly to
all 23 codecs**, with **qualitative** success criteria — every step must show a
*measured* improvement with *no regression* and *bit-exact correctness*; no hard
numeric SLAs are bound. Measurement orders the work and proves each gain; it does
**not** gate whether a phase happens (all phases are in scope).

## 0. Guiding principle — measure to order & verify (not to gate)

The representation layer is already near-optimal (zero-copy SoA records → numpy/
torch/DLPack; per-format hand-tuned decoders; GIL released). **Before O1**, the
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
| Throughput bench | read+write MB/s, Mpix/s (images), Mpts/s (clouds), **all 23 codecs** | `bench/bench_io.py` |
| Peak-memory bench | `tracemalloc` peak + RSS for read & write | same harness |
| Oracle comparison | same op via Pillow / laspy / OpenEXR / numpy / pycolmap / gsply | reuse `[test]` oracles |
| Fixtures | small (typical) + large (100 MB–1 GB synthetic) per format | `bench/fixtures.py` (generated) |

**Exit criteria:** baseline table across all 23 codecs, committed and reproducible
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
  (LAS/EXR/PLY/SPZ/npy), but all 23 remain in the harness and API E2E coverage.

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
| `.flo` | ✅ | contiguous float payload after a small header |
| `.pfm` | ❌ | mandated bottom-to-top rows require a row flip; a negative-stride mapped view is unsafe for common DLPack normalization |
| uncompressed `.las` | ❌ | needs quantize→f32 + origin rebase (a real transform) |
| png/jpeg/webp/exr/spz/npz | ❌ | compressed — a decode is physically unavoidable |

The compressed codecs pass through O2 unchanged (nothing to view); the raw ones get
the zero-copy path. Uniform *evaluation*, format-nature-limited *application*.

**Testing:** view equals copy-decode bit-exact; **lifetime test** — the array
outlives the file handle (`gc.collect()` then still-valid, the Image lifetime
pattern); mutation isolation. **Verify:** npy read peak-memory → ~0 above the mmap.

**Landed:** `_core.read_npy_view` and `read_flo_view` back the public registry
path. NPY views native-endian C-order payloads and preserves all 12 supported
dtypes; byte-swapped and multi-dimensional Fortran payloads retain the canonical
owned-copy fallback. FLO directly views its little-endian interleaved payload on
the supported little-endian build matrix. Every direct view is read-only, aliases
the exact mapped payload address, pins the export until all derived views die,
and remains valid after the file handle closes and `gc.collect()` runs.
On Windows this intentionally keeps the mapped file locked for the array's
lifetime. The mmap-unavailable/empty-file fallback remains the copy decoder.
Writable Torch interop is process-safe and file-isolated: DLPack receives an
owned copy, while the private mapping prevents a `torch.from_numpy` alias from
writing through to the source file. PFM was evaluated but keeps its canonical
owned, positive-stride row-flip decode: exposing the stored row order as a
negative-stride view can make ordinary `np.asarray` + DLPack consumers abort.

The final local MSVC benchmark measured public-path throughput of 63.6 GB/s NPY
and 72.3 GB/s FLO for warm mapped fixtures (header parse + view construction),
versus 4.9/4.9 GB/s for the in-memory copy decoders. Sampled RSS growth fell
from 16.8/16.8 MB to 0.0 MB at table precision, and the 16 MiB NPY
traced-allocation bound plus exact address identity remained green. The final
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
callbacks run with sink interception suppressed. NPY, NPZ, PFM, and FLO finish
all NumPy/DLPack/mapping protocol conversion before activating the sink, so
those arbitrary Python callbacks can re-enter an encoder without interleaving
the outer file.

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

New public surface, applied to every format for which it's meaningful:
- header-only `inspect(path)` → dims/count/dtype/channels without a full decode
  (all formats have a cheap header);
- pixel-window (images), point-subset (clouds), single-image (COLMAP) reads where
  the container permits.

**Testing:** partial read equals the slice of the full read; `inspect` matches the
decoded record's shape/dtype. **Verify:** header-only/partial peak-memory and
latency vs the full read.

**Inspection landed:** `sceneio.inspect(path, format=None)` covers all 23 codecs
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
half-open pixel `window`, half-open point/state range, persisted COLMAP
`image_id`, unordered database `pair`, or safetensors name/slice selector.
Bounded pixel paths cover PFM, binary P5/P6 Netpbm, lossless VP8L WebP, FLO,
and scalar DMB; point paths include XYZ, PTS, binary PLY/PCD, LAS, Gaussian
PLY, and SPLAT. Binary/text COLMAP return one image and its camera; COLMAP
SQLite returns one `FeatureSet` or one pair `MatchGraph`; safetensors returns
only requested tensors or leading-axis slices. Unsupported compressed/text
variants reject rather than disguising a full decode as a partial read.

The 48-case focused suite compares values, dtypes, and convention metadata
against full-read slices across binary Netpbm type/channel combinations,
lossless RGB/RGBA WebP windows, every automatic XYZ layout plus forced normals,
and LAS point formats 0–3 and 6–8. It also covers non-native-endian payloads,
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

The 23 per-codec **parity suites + the public-API E2E test remain the ground-truth
oracle**. Optimizations add exactly these guards, **run across all 23 codecs**:

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
- **O1 + ASan CI** ~2–3 units. Structural read win + the safety net, all 23 codecs.
- **O2** ~1–2 units. Zero-copy for the raw formats.
- **O3** ~2 units. Sink writers, all 23.
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
