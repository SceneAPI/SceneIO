# I/O Optimization, Testing & Verification Plan

Status: active — O0–O2 complete; O3–O5 pending. Scope: the compiled `sceneio._core` I/O path on
`phase0-nanobind-core`. Companion to `coverage_roadmap.md` (this makes its "Phase 7"
hardening/perf work concrete).

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
materialize the whole output as `bytes` before disk. O1 replaces the read side;
the remaining write copy/stream/partial limitations are O3/O5 work.

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
execution begins once this workflow reaches the default branch; the remote
workflow run remains user-gated.

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

## Phase O3 — Streaming writes (all codecs)

Writers build the full output then copy into `nb::bytes`. Add a **file-sink** write
path (`write_X_to_file(record, path)` or a sink callback) for every codec, so large
outputs stream to disk without a full in-memory copy. Swept across all 23 writers;
the harness orders which land first (largest write-memory first).

**Testing:** sink-written file byte-identical to the buffer-written one, per codec.
**Verify:** write peak-memory drops by ~output-size.

---

## Phase O4 — Intra-file parallelism / SIMD

Committed for the decode-bound hot paths the harness surfaces:
- Enable tinyexr/libwebp worker threads for large images (currently off).
- SIMD/vectorize the scalar transform loops: PNG 16-bit byteswap, EXR
  planar→interleave, LAS per-point unpack, and any others the harness flags.

**Testing:** identical output with threads on/off and 1 vs N lanes. **Verify:**
throughput delta on the large fixtures.

---

## Phase O5 — Partial / lazy reads (new API)

New public surface, applied to every format for which it's meaningful:
- header-only `inspect(path)` → dims/count/dtype/channels without a full decode
  (all formats have a cheap header);
- pixel-window (images), point-subset (clouds), single-image (COLMAP) reads where
  the container permits.

**Testing:** partial read equals the slice of the full read; `inspect` matches the
decoded record's shape/dtype. **Verify:** header-only/partial peak-memory and
latency vs the full read.

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
| Benchmark harness (O0) | measured improvement and comparable throughput | per-item; all-format smoke in CI |
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
