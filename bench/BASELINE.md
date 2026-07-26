# O0 baseline — SceneIO I/O harness

Snapshot from `python bench/bench_io.py --runs 7`. **Indicative** (median of 7,
single machine, local **MSVC** build, warm cache); the *conclusions* below are what
order the O1+ sweep, not the exact MB/s. Regenerate on any machine — the harness is
the source of truth, this file is a dated reading.

This document is chronological benchmark evidence: later sections expand from
the original 23-codec O0 scope to the live 50-codec harness. Optimized mmap,
sink, inspection, and partial-read transport does not by itself prove every
codec kernel is the fastest viable backend. The per-codec qualification ledger
and candidate-selection gate are defined in
[`../docs/repository_organization_plan.md`](../docs/repository_organization_plan.md);
JPEG encode/decode remains the first known backend gap.

Columns: `payloadMB` raw array size · `fileMB` encoded size · `sioW/sioR` sceneio
write/read MB/s over the payload · `oraW/oraR` the oracle lib (0 = no oracle) ·
`rPeakMB` peak Python alloc on `read_bytes()->decode` · `sio/ora` read-throughput ratio.

```
codec          payloadMB   fileMB     sioW     sioR     oraW     oraR  rPeakMB  sio/ora
---------------------------------------------------------------------------------------
png                  3.1      3.1       47      235       44      330      3.2     0.71
jpeg                 3.1      2.5       60      154      924      541      2.5     0.28
webp                 3.1      3.1       14      290       36      196      3.2     1.48
hdr                 12.6      4.1      832     1265        -        -      4.1      -
exr                 12.6     12.5       55      327        -        -     12.5      -
netpbm               3.1      3.1     2511    10021        -        -      3.2      -
xyz                 12.0     56.5       21       82        -        -     56.5      -
las                 12.0     26.0      206     2713      271     3710     26.0     0.73
gaussian_ply        11.2     11.2     3154     5682        -        -     11.2      -
spz                 11.2      3.4      106      772        -        -      3.4      -
splat               11.2      6.4      978     2522        -        -      6.4      -
npy                  8.4      8.4     4474     8110     4147     5802      8.4     1.40
```
Oracles: Pillow (png/jpeg/webp), laspy (las), numpy (npy). hdr/exr/netpbm/xyz/
gaussian/spz/splat have no in-process oracle wired yet.

## Conclusions (these order the sweep)

1. **O1 (mmap) is a universal, confirmed win.** `rPeakMB == fileMB` for *every*
   codec — the read path allocates a whole-file `bytes` copy equal to the file
   size, exactly what mmap removes. Largest absolute savings: **xyz 56 MB, las 26,
   exr 12.5, gaussian_ply 11, npy 8.4** per read. O1 applies uniformly and the
   memory reduction is deterministic, not speculative. Do O1 first.

2. **Codec-kernel throughput has three real hotspots.** Decode is competitive
   with or faster than the available oracles for NPY and WebP and within the
   same order for LAS; JPEG is the clear bidirectional exception:
   - **JPEG write/read 60/154 MB/s vs the Pillow libjpeg-backed reference at
     924/541 MB/s.** SIMD/threads around stb will not fix an algorithmic backend
     gap; evaluate a faster permissive implementation such as libjpeg-turbo
     outside O4.
   - **xyz write 21 MB/s** — text float→string formatting bound, and 4.7× file
     bloat (56 MB for a 12 MB payload). O4 candidate (faster float formatter) —
     but text is inherently the slow/fat path.
   - **webp lossless write 14 MB/s** — libwebp lossless effort; O4 can lower the
     effort level or enable its worker threads.

3. **Read peak is dominated by the bytes copy, not decode** — confirming the
   optimization order: O1 (kill the copy) before O4 (speed the decode), because the
   copy is the bigger, universal cost.

## Harness coverage added with O1

The harness now builds non-empty `Reconstruction` and `PosedViewSet` inputs and
covers all original 23 codecs, including both COLMAP directory variants, Bundler, NVM,
OpenMVG, transforms.json, TUM, KITTI, and NPZ. ImageIO/OpenEXR-backed oracle
adapters are wired for Netpbm/HDR/EXR and degrade cleanly when the installed
ImageIO backend cannot handle Radiance HDR. `--scale` generates large fixtures,
`--cold-cache` requests `POSIX_FADV_DONTNEED` where supported, and the table
reports both `tracemalloc` and sampled RSS.

## O1 mmap delta — 2026-07-23

Local MSVC run after O1 (`bench_io.py --runs 3`). `bPeakMB` retains the legacy
`read_bytes()` measurement and `mPeakMB` measures the same decoder over a
read-only mmap. Throughput columns remain in-memory codec measurements and are
within baseline noise; the deterministic result is that the Python whole-file
allocation disappears for every single-file codec.

```
codec          fileMB  bPeakMB  mPeakMB
---------------------------------------
png                3.1       3.2       0.0
jpeg               2.5       2.5       0.0
webp               3.1       3.2       0.0
hdr                4.1       4.1       0.0
exr               12.5      12.5       0.0
netpbm             3.1       3.2       0.0
xyz               56.5      56.5       0.0
las               26.0      26.0       0.0
gaussian_ply      11.2      11.2       0.0
spz                3.4       3.4       0.0
splat              6.4       6.4       0.0
npy                8.4       8.4       0.0
pfm                4.2       4.2       0.0
flo                8.4       8.4       0.0
npz                1.1       1.1       0.0
transforms_json     0.0       0.0       0.0
tum                0.0       0.0       0.0
kitti              0.0       0.0       0.0
bundler            0.0       0.0       0.0
nvm                0.0       0.0       0.0
openmvg            0.0       0.0       0.0
```

The exact traced mmap peaks were below the table's 0.05 MB display precision.
The committed 16 MiB `.npy` memory test also requires mmap peak allocation below
one eighth of file size while the bytes path must account for at least 90% of
the file size. A generated `--scale 2 --runs 1` sweep exercised a 113.0 MB XYZ
file and retained a 0.0 MB displayed mmap peak. RSS columns include decoded
output, allocator reuse, and mmap page residency, so the input-copy proof is the
traced-allocation delta plus exact exporter/core pointer identity; RSS remains a
whole-process diagnostic rather than an isolated-copy assertion.

## O2 raw zero-copy delta — 2026-07-23

Local MSVC run after O2 (`bench_io.py --runs 3`). `sioR` is the unchanged
in-memory copy decoder; `pathR` is the public warm mmap path, which now parses
the small header and returns a pinned read-only ndarray view. `bRSSMB` includes
the legacy Python file bytes plus decoded C++ vector, while `mRSSMB` samples the
view path.

```
codec   payloadMB  sioR MB/s  pathR MB/s  bRSSMB  mRSSMB
--------------------------------------------------------
npy           8.4       4919       63647     16.8      0.0
flo           8.4       4936       72316     16.8      0.0
```

The throughput improvement is the expected removal of the payload-sized copy;
the path operation now measures header validation plus ndarray construction.
Exact mapped-address assertions are the copy-proof, while sampled RSS supplies
the process-level memory delta. NPY byte-swapped/Fortran inputs intentionally
retain the canonical copy fallback. PFM was evaluated but its mandatory
bottom-to-top row reversal remains an owned positive-stride decode: the rejected
negative-stride view could make ordinary NumPy-to-DLPack normalization abort.

## O3 direct file-sink delta — 2026-07-23

Local MSVC run after the signed-off O3 implementation (`bench_io.py --runs 7`).
`bytesW` is the former public
shape—encode to Python `bytes`, then `Path.write_bytes`—while `sinkW` writes the
encoder's existing C++ buffer directly to an unbuffered file descriptor without
exposing the pointer to Python. `bPeakMB`/`sPeakMB` are the corresponding peak
traced Python allocations.

```
codec              fileMB  bytesW MB/s  sinkW MB/s  bPeakMB  sPeakMB
--------------------------------------------------------------------
png                    3.1           45           46      3.2      0.0
jpeg                   2.5           57           57      2.5      0.0
webp                   3.1           13           13      3.2      0.0
hdr                    4.1          701          740      4.1      0.0
exr                   12.5           53           54     12.5      0.0
netpbm                 3.1         1316         1858      3.2      0.0
xyz                   56.5           18           18     56.5      0.0
las                   26.0          167          176     26.0      0.0
gaussian_ply          11.2         1468         1995     11.2      0.0
spz                    3.4           99          102      3.4      0.0
splat                  6.4          813          897      6.4      0.0
npy                    8.4         1941         2878      8.4      0.0
pfm                    4.2         1839         2456      4.2      0.0
flo                    8.4         2068         2956      8.4      0.0
npz                    1.1          408          407      1.1      0.0
transforms_json        1.2           29           32      1.2      0.0
tum                    0.2           69           71      0.2      0.0
kitti                  0.2           38           38      0.2      0.0
bundler                0.2           83           84      0.2      0.0
nvm                    0.2           80           80      0.2      0.0
openmvg                0.6           44           43      0.6      0.0
```

All 21 single-file outputs were byte-identical. The two COLMAP directory codecs
already used direct file sinks and remain byte-identical through the public
registry. At table precision every output-sized Python allocation disappeared;
the 16 MiB NPY bound asserts the exact property independent of timer/RSS noise.
Sink throughput was equal or faster within normal run noise (NPZ's 408 vs
407 MB/s and OpenMVG's 44 vs 43 MB/s are sub-millisecond-scale differences).

## O4 measured hot-path delta — 2026-07-23

Final local MSVC run (`bench_io.py --runs 7`). Each base is the retained
one-lane/worker-off or old-effort control measured in the same process. `bytes`
means encoded output is identical; `values`/`pixels` means decoded arrays and
record metadata are identical where compression settings intentionally changed.

```
codec   operation           base MB/s  optimized MB/s  gain   identity
----------------------------------------------------------------------
png16   swap-write                 68              69  1.02x  bytes
png16   swap-read                 417             421  1.01x  values
webp    balanced-config            12              34  2.75x  pixels
webp    workers-palette            10              19  1.93x  bytes
exr     planar-write              254             252  0.99x  bytes
exr     planar-read              1133            1293  1.14x  values
xyz     format-write               20             101  5.16x  bytes
las     points-write              347            1054  3.03x  bytes
las     points-read              1997            2765  1.38x  values
```

PNG16's conversion and the outer EXR planar write are small fractions of their
whole-codec costs. Repeated sweeps placed those ratios on both sides of 1.0, so
the table records the final run but makes no speedup claim for them. The larger
targets are stable and directional. WebP's balanced production default is
method 5 / effort 75 / workers enabled; the worker row uses a structured palette
case that makes libwebp create independent lossless candidates and verifies a
native side-worker launch rather than merely toggling `thread_level`. Lossy WebP
retains the pre-O4 method-4/worker-off configuration.

All controlled one-vs-many paths compare their actual bytes or decoded
values/metadata before reporting a row. TinyEXR output also matches a pinned
pre-O4 SHA-256, and a malformed duplicate-destination scanline fixture is
required to reject. Final verification: 1,165 passed / 3 optional skips on
Windows and 1,102 passed / 44 optional-platform skips under the instrumented
Linux ASan/UBSan/LSan build.

CI runs the original all-23-codec smoke and uploads its JSON. A second five-run sweep
fails when any retained stable high-signal O4 control (WebP balanced config and
palette workers, XYZ write, LAS read/write) loses its paired in-process gain, or
when mmap/file-sink traced allocation rises above one quarter of the retained
whole-file bytes control for material fixtures. Small compression-dominated
PNG16/EXR-planar timing deltas remain recorded but do not create a flaky timing
gate.

## O5 metadata-only inspection delta — 2026-07-24

Final local MSVC five-run sweep for the first O5 unit (`bench_io.py --runs 5
--require-o4-gains --require-o5-inspect-gains`). `full ms` is the public
mmap-backed full read; `inspect ms` constructs only immutable scalar metadata.
RSS is sampled process growth. Bounded compiled scans keep headerless text
inspection at effectively 0 MB growth, including malformed no-newline inputs.

```
codec               full ms  inspect ms  speedup  full RSS MB  inspect RSS MB
-----------------------------------------------------------------------------
png                    14.99        0.05  331.7x          10.9             0.0
jpeg                   23.59        0.04  581.1x           8.5             0.0
webp                   14.22        0.04  333.0x          10.5             0.0
hdr                    13.81        0.06  221.0x          28.0             0.0
exr                    11.09        0.09  128.8x          35.1             0.0
netpbm                  0.87        0.04   19.6x           6.3             0.0
xyz                   183.12       72.77    2.5x          68.5             0.0
las                     6.28        0.04  167.1x          43.8             0.0
gaussian_ply            5.46        0.05  108.6x          21.6             0.0
spz                    17.14        0.12  148.8x          13.8             0.0
splat                   7.68        0.01  745.7x          16.8             0.0
npy                     0.05        0.05    0.9x           0.0             0.0
pfm                     1.29        0.05   25.5x           7.4             0.0
flo                     0.05        0.03    1.4x           0.0             0.0
npz                     2.26        0.12   19.5x           2.1             0.0
transforms_json        27.60       10.69    2.6x           1.2             1.2
tum                    14.47        2.75    5.3x           0.2             0.0
kitti                  21.78        3.13    7.0x           0.3             0.0
bundler                 1.27        0.04   29.8x           0.2             0.0
nvm                     1.29        0.04   30.5x           0.2             0.0
openmvg                17.91       16.46    1.1x           0.6             0.6
colmap_sparse           2.28        0.15   15.2x           0.0             0.0
colmap_sparse_txt       2.88        0.37    7.8x           0.0             0.0
```

NPY and FLO full reads were already O2 header-parse + mapped-view construction,
so their complete public reads are as cheap as inspection within sub-millisecond
noise; inspection adds a Python metadata object but no payload allocation.
Transforms/OpenMVG are JSON metadata containers, so JSON parsing dominates both
paths and record-array avoidance is a smaller gain. The stable binary rows
(PNG/EXR/LAS/Gaussian PLY/SPZ) retain directional CI latency and RSS-gain
guards, every inspection must stay below 1 MB of traced Python allocation, and
the two JSON readers retain a coarse full-read/SAX ratio bound that catches
large decode-path regressions. This committed table remains the historical
control for smaller timing movement.

## O5 bounded partial-read delta — 2026-07-24

Final local MSVC five-run sweep (`bench_io.py --runs 5 --require-o4-gains
--require-o5-inspect-gains --require-o5-partial-gains`). `full ms` is the
normal public mmap-backed read and `partial ms` returns the normal record type
while materializing only the selected window, point range, or COLMAP image.

```
codec                 full ms  partial ms  speedup  full RSS MB  part RSS MB
----------------------------------------------------------------------------
webp                     11.84        6.14    1.93x          9.8          4.3
netpbm                    0.87        0.10    8.35x          6.3          0.0
xyz                     173.16      101.92    1.70x         68.5         56.5
las                       5.84        0.52   11.21x         47.3          1.4
gaussian_ply              5.16        0.26   19.55x         21.6          0.7
splat                      6.14        0.33   18.79x         16.7          0.2
pfm                        1.36        0.13   10.25x          8.0          0.4
flo                        0.04        0.04    1.00x          0.0          0.0
colmap_sparse              2.21        0.04   53.19x          0.0          0.0
colmap_sparse_txt          3.12        0.04   85.11x          0.0          0.0
```

Every partial traced-allocation peak remained below the table's 0.05 MB
display precision. WebP measures a lossless VP8L crop; binary P5/P6 is the
bounded Netpbm path. ASCII P2/P3 and lossy VP8 reject rather than performing a
non-bounded or non-slice-exact operation. XYZ must still scan mapped text to
find and validate row boundaries, so kernels may charge the whole encoded file
to RSS. Its guard caps resident growth at the encoded size plus 8 MB; the other
material rows require a directional ratio gain. The paired five-run CI guard
passed together with all retained O4 and O5
inspection controls. Final verification passed 1,289 tests / 3 optional skips
on Windows and 1,208 / 62 expected skips under ASan/UBSan/LSan on Linux.

## Safetensors expansion delta — 2026-07-24

The 24-codec harness now includes safetensors and its independent
`safetensors.numpy 0.8.0` oracle. The dedicated large-fixture mode generates
files in a temporary directory and commits no payload:

```text
python bench/bench_io.py --runs 3 --large-safetensors-mib 128
python bench/bench_io.py --runs 1 --large-safetensors-mib 1024
```

`full` is SceneIO's complete mapped `TensorDict` construction without touching
tensor pages. `selected` maps only the named 2 KiB tensor. Oracle full-read
numbers use `safetensors.numpy.load_file`, which materializes the arrays.
Write is SceneIO's native chunked file sink versus the oracle's file writer.

```text
fixture       write ms  full ms  inspect ms  selected ms  traced peak MB  RSS MB
-------------------------------------------------------------------------------
SceneIO 128M      76.76      0.12        0.11         0.05            0.01    0.02
oracle  128M      79.45     58.96        0.04         0.05          134.22  268.47
SceneIO   1G     673.91      0.21        0.11         0.08            0.01    0.02
oracle    1G     651.07    503.19        0.08         0.07         1073.75 2147.51
```

The measured result validates the intended qualitative target: SceneIO's
mapped full and selected paths remain effectively constant in traced
allocation/RSS as the fixture grows from 128 MiB to 1 GiB, while streaming
write throughput stays comparable to the reference writer. Inspection and
single-tensor selection are sub-millisecond for both implementations. The
ordinary all-codec smoke was also extended from 23 to 24 entries.

## Count-prefixed PTS expansion delta — 2026-07-24

PTS is measured by the 25-codec harness against an independent NumPy text
parser/writer. A three-run `--scale 0.1` fixture contains 100,000 XYZ points
(1.2 MB raw, 5.7 MB encoded):

```text
operation                         SceneIO          oracle / control
-------------------------------------------------------------------
write throughput                  55 MB/s          12 MB/s
buffer read throughput            81 MB/s          62 MB/s
public mmap read throughput       75 MB/s          -
buffer/mmap traced read peak      5.7 / 0.0 MB     -
buffer/sink traced write peak     5.7 / 0.0 MB     -
inspect latency                   0.056 ms          full read 15.903 ms
middle point-range latency        8.585 ms          full read 15.903 ms
```

The result validates the intended qualitative gains: mmap and file-sink paths
remove the encoded-size Python allocation, header-only inspection is roughly
282x faster than full parsing, and a bounded middle range is about 1.85x
faster while allocating only its selected records. The range reader still
scans the count-prefixed text to validate row structure and the declared total,
so resident pages can approach the encoded file size even though heap output
does not.

## Scalar DMB expansion delta — 2026-07-24

DMB extends the harness to 26 codecs and uses an independent little-endian
NumPy/`struct` oracle. The five-run CI-equivalent regression sweep uses a
1024x1024 scalar float32 depth map (4.194 MB raw and encoded):

```text
operation                         result
-------------------------------------------------------------
buffer / public mmap read         7,123 / 3,530 MB/s
buffer / public sink write        1,975 / 6,264 MB/s
oracle writer                     4,609 MB/s
buffer / mmap traced read peak    4.203 / 0.010 MB
buffer / sink traced write peak   4.205 / 0.001 MB
full / inspect latency            1.188 / 0.050 ms
128x128 middle-window latency     0.129 ms
inspect / partial traced peak     0.010 / 0.011 MB
```

The mmap and direct-sink paths remove the encoded-size Python allocation.
Header inspection is about 23.6x faster than full record construction and the
bounded middle window is about 9.2x faster. The generated 4096x4096 (64 MiB)
sparse-file test is the larger structural memory gate and keeps both inspection
and a selected 8x8 window below 1 MiB of traced allocation. All payloads are
generated during the run or test and are not committed. The complete
same-run O4/O5 regression guard passed with DMB included.

## BAL reconstruction expansion delta — 2026-07-24

BAL extends the harness to 27 codecs and is compared with an independent
NumPy/text parser and writer. The five-run CI-equivalent regression sweep uses
1,000 cameras, 10,000 points, and 20,000 observations (0.8 MB decoded numeric
payload, 1.6 MB encoded text):

```text
operation                         result
-------------------------------------------------------------
buffer / public mmap read         206 / 190 MB/s
buffer / public sink write        44 / 46 MB/s
independent writer / reader       21 / 38 MB/s
buffer / mmap traced read peak    1.6 / 0.0 MB
buffer / sink traced write peak   1.6 / 0.0 MB
full / inspect latency            4.161 / 0.045 ms
full / inspect RSS growth         1.2 / 0.0 MB
```

The mmap and direct-sink paths remove the encoded-size Python allocation while
preserving exact records and canonical bytes. Three-count header inspection is
about 92.9x faster than full reconstruction parsing. The compiled reader is
about 5.5x faster than the independent parser on the same numeric payload, and
the chunked sink retains buffer-writer throughput without returning an
output-sized `bytes`. A separate generated 64 MiB sparse-file test bounds
header-only inspection below 1 MiB traced allocation. The complete same-run
O4/O5 throughput and memory regression guard passed with BAL included.

## BMP/TGA image expansion delta — 2026-07-24

BMP and TGA extend the harness to 29 codecs with Pillow as the independent
pixel oracle. The five-run CI-equivalent sweep uses a 1024x1024 uint8 RGB image
(3.146 MB raw; 3.146 MB BMP and 3.154 MB RLE TGA):

```text
operation                    BMP result          TGA result
----------------------------------------------------------------
buffer / public mmap read    1,097 / 940 MB/s    561 / 512 MB/s
buffer / public sink write   527 / 778 MB/s      420 / 550 MB/s
Pillow writer / reader       851 / 1,161 MB/s    889 / 1,136 MB/s
buffer / mmap read peak      3.2 / 0.0 MB        3.2 / 0.0 MB
buffer / sink write peak     3.2 / 0.0 MB        3.2 / 0.0 MB
full / inspect latency       3.346 / 0.048 ms    6.145 / 0.058 ms
full / inspect RSS growth    6.3 / 0.0 MB        6.3 / 0.0 MB
```

Both mmap readers remove the encoded-size Python input copy. Their native
256 KiB callback staging makes direct file writes genuinely bounded and also
faster than returning a complete Python `bytes` on this fixture. Header-only
inspection is about 69.4x faster for BMP and 105.6x faster for TGA. Pixel
correctness is separately triangulated across Windows top/bottom orientation,
BMP palettes and 16-bit bitfields, TGA raw/RLE top/bottom orientation,
zero-origin palettes, packed 16-bit color, and gray/RGB/RGBA modes. The
complete same-run O4/O5 throughput and memory regression guard passed with both
formats included.

## Typed FLO semantic-adapter delta — 2026-07-24

The raw FLO benchmark row remains unchanged and continues to measure the
zero-copy mapped ndarray path. A dedicated nested row now measures the owning
`FlowField` adapter on the same 1024x1024 float32 UV raster (8.389 MB):

```text
operation                         result
-------------------------------------------------------------
typed mmap read                   2,864 MB/s
typed direct-sink write           2,253 MB/s
typed header inspection           0.038 ms
typed read/write traced peak      0.011 / 0.001 MB
raw public mmap read              180,400 MB/s
raw direct-sink write             2,515 MB/s
```

The large raw-read number reflects the intended O2 mapped view, whereas the
typed read intentionally owns one native copy so its `FlowField` outlives the
mapping. Both paths avoid an encoded-size Python `bytes`; typed sink output is
byte-identical to the raw writer and independent NumPy oracle. The five-run
29-codec O4/O5 throughput and memory regression guard passed.

## Typed PFM depth-adapter delta — 2026-07-24

The raw PFM benchmark row remains the compatibility reference for grayscale
and RGB ndarray I/O. A nested row measures the explicit scalar `DepthMap`
adapter on the same 1024x1024 float32 raster (4.194 MB), including a bounded
middle window:

```text
operation                         result
-------------------------------------------------------------
typed mmap read                   2,026 MB/s
typed direct-sink write           1,955 MB/s
typed header inspection           0.056 ms
typed read/write traced peak      0.011 / 0.001 MB
typed middle-window latency       0.55 ms
raw public mmap read              2,059 MB/s
raw direct-sink write             2,198 MB/s
```

The typed reader owns exactly one native float32 raster because PFM's required
bottom-to-top transform prevents a positive-stride mapped view. It avoids an
additional encoded-size Python `bytes`, preserves every float bit, and attaches
only the caller-supplied immutable `DepthEncoding`. Typed output is
byte-identical to the raw writer and independent oracle. A generated 128 MiB
sparse-file test keeps typed inspection plus an 8x8 bounded window below 1 MiB
of traced Python allocation. The five-run 29-codec O4/O5 throughput and memory
regression guard passed.

## Typed PNG depth-adapter delta — 2026-07-24

A nested PNG row measures the explicit `DepthMap` adapter on a 1024x1024
grayscale uint16 raster, reported over the 4.194 MB widened float32 depth
payload:

```text
operation                         result
-------------------------------------------------------------
typed mmap read                     979 MB/s
typed direct-sink write             193 MB/s
typed header inspection           0.052 ms
typed read/write traced peak      0.011 / 0.001 MB
```

The reader losslessly widens uint16 samples to float32 and records only the
mandatory external `DepthEncoding`; it never applies a scale. The writer scans
for exact integral `[0,65535]` representability, rejects negative zero,
non-finite/fractional/out-of-range values and confidence, then produces bytes
identical to the existing deterministic grayscale uint16 Image writer. The
compressed container cannot provide a bounded window without a full inflate, so
the typed API rejects that selector explicitly. The five-run 29-codec O4/O5
throughput and memory regression guard passed.

## Typed EXR depth-adapter delta — 2026-07-24

A nested EXR row measures the explicit named-channel `DepthMap` adapter on a
1024x1024 scalar FLOAT raster, reported over the 4.194 MB raw float32 payload:

```text
operation                         result
-------------------------------------------------------------
typed mmap read                   1,341 MB/s
typed direct-sink write             304 MB/s
typed header inspection           0.057 ms
typed read/write traced peak      0.011 / 0.001 MB
```

The reader checks the exact selected channel in the same TinyEXR parse that
decodes the raster, preventing a mutable-source gap between validation and
decode. FLOAT bits are preserved exactly and HALF uses the unchanged exact
widening path; no scale, transfer function, or invalid-value policy is applied.
The typed writer shares the raw encoder while supplying an explicit scalar
channel name; typed `Y` output is byte-identical to the original raw scalar
writer. EXR compression cannot provide a bounded typed window without full
decode, so that selector rejects before invoking the reader. The accepted
five-run 29-codec O4/O5 throughput and memory regression guard passed.

## Generic point PLY baseline — 2026-07-24

The harness now covers 30 codecs and reports all three generic point PLY
encodings. A three-run generated 4,000,000-point fixture carries float32
positions/normals plus uint8 RGB: 108.0 MB of logical data and 108.0 MB for
either binary file (319.6 MB as canonical ASCII).

```text
encoding / operation                 result
-------------------------------------------------------------
binary little-endian write             762 MB/s
binary little-endian read              891 MB/s
binary big-endian write                547 MB/s
binary big-endian read                 546 MB/s
ASCII write                             22 MB/s
ASCII read                             108 MB/s
public mmap read                       612 MB/s
direct file-sink write                 521 MB/s
header-only inspect                  0.082 ms
middle 1/16 point range             12.559 ms
full read                           176.338 ms
```

Inspection was 2,148x faster than full decode and touched no measurable payload
RSS. The fixed-record point range was 14.04x faster, with 12.3 MB sampled RSS
versus 215.4 MB for the full mapping plus output record. The public mmap path
removed the 108.0 MB traced whole-file `bytes` allocation, and the direct sink
removed the corresponding 108.0 MB Python write allocation.

A separate three-run 100,000-point oracle pass measured SceneIO at 768 MB/s
write and 930 MB/s read versus Open3D 0.19 at 23 MB/s and 128 MB/s. Open3D is
MIT-licensed and test-only. The plan's earlier `plyfile` suggestion was
discarded because its current GPLv3 license violates SceneIO's
permissive-license-only rule.

The accepted five-run 30-codec guard then measured the default 1,000,000-point
PLY row at 753 MB/s write and 851 MB/s read, with a 469x inspection gain and
20.76x partial-read gain. Every retained O4/O5 directional and mmap/sink
allocation guard passed.

## PCD baseline — 2026-07-24

The harness now covers 31 codecs and reports PCD 0.7 ASCII, little-endian
binary, and LZF `binary_compressed` variants. A three-run generated
4,000,000-point fixture carries float32 positions/normals plus uint8 RGB:
108.0 MB of logical arrays, 112.0 MB as binary (packed RGB occupies four
bytes), 310.1 MB as ASCII, and 114.9 MB as LZF. The random fixture is
intentionally incompressible; LZF correctly grows it slightly rather than
claiming a synthetic compression win.

```text
encoding / operation                 result
-------------------------------------------------------------
binary write                          1,937 MB/s
binary read                           3,595 MB/s
binary_compressed write                 168 MB/s
binary_compressed read                1,566 MB/s
ASCII write                              25 MB/s
ASCII read                              113 MB/s
public mmap binary read               1,238 MB/s
direct streaming binary sink          1,155 MB/s
header-only inspect                   0.086 ms
middle 1/16 point range               3.882 ms
full public read                     87.258 ms
```

Inspection was 1,015x faster than full decode and added 0.02 MB sampled RSS.
The fixed-record range was 22.48x faster and used 12.9 MB sampled RSS versus
219.2 MB for the full mapping plus output record. Mmap removed 112.0 MB of
traced input allocation. The chunked binary sink reduced traced allocation
from 112.0 MB to 0.001 MB and sampled RSS from 112.0 MB to 1.9 MB while
remaining byte-identical to the buffer writer.

A separate three-run 100,000-point oracle pass measured SceneIO binary write
and read at 1,894 and 3,233 MB/s versus Open3D 0.19 at 25 and 63 MB/s.
Open3D is MIT-licensed and test-only; no new native or runtime dependency was
added.

The accepted five-run 31-codec guard measured the default 1,000,000-point PCD
row at 1,933 MB/s write and 3,414 MB/s read, with a 276x inspection gain and
26.34x partial-read gain. Every retained O4/O5 directional and mmap/sink
allocation guard passed.

## EuRoC state CSV baseline — 2026-07-24

The harness now covers 32 codecs. The default generated fixture contains
100,000 complete navigation states: 13.6 MB of logical int64/float64 SoA data
and 35.2 MB of deterministic 17-column CSV.

```text
operation                              result
-------------------------------------------------------------
buffer write                           42 MB/s
buffer read                           202 MB/s
public mmap read                      176 MB/s
stdlib CSV oracle write/read        16 / 18 MB/s
direct streaming sink                 42 MB/s
metadata inspection                 73.407 ms
middle 1/16 state range             73.730 ms
full public read                    77.434 ms
```

The separate oracle run measured the compiled reader at 11.19x the independent
stdlib CSV reader. In the accepted five-run all-codec guard, metadata
inspection and the selected range were each 1.05x faster than full decode and
avoided constructing most of the 13.6 MB state arrays. The selected range
reduced sampled RSS from 48.4 MB to 35.1 MB while validating every unselected
row.
Mmap removed the 35.2 MB traced input allocation. The chunked file sink reduced
traced output allocation from 35.2 MB to effectively zero and sampled RSS from
42.1 MB to effectively zero while remaining byte-identical to the buffer
writer. Every retained 32-codec O4/O5 directional and mmap/sink allocation
guard passed.

## Camera calibration baseline — 2026-07-24

The harness now covers 36 codecs (34 single-file plus the two COLMAP
directories). OpenCV YAML, OpenCV XML, ROS CameraInfo YAML, and Kalibr YAML use
the new lossless `CameraRig` record. The representative OpenCV and ROS fixtures
contain one camera (452 logical bytes); the Kalibr fixture contains 64 cameras
(27,408 logical bytes, 23,644 encoded bytes). Five-run medians were:

```text
codec             native W/R MB/s    oracle W/R MB/s    native/oracle read
---------------------------------------------------------------------------
opencv_yaml            129 / 52             2 / 1              62.75x
opencv_xml             119 / 89            19 / 36              2.43x
ros_camera_info         77 / 38             1 / <1             76.92x
kalibr                  134 / 81             2 / 1              91.56x
```

The independent oracles are test-only PyYAML for all YAML schemas and stdlib
ElementTree for XML. The tiny single-camera files make filesystem latency
dominate public-path timing, but the direct sink was consistently faster than
buffer-plus-file output (roughly 3–4 MB/s versus 2–3 MB/s; Kalibr 82 versus
75 MB/s) and remained byte-identical.

A separate 1.65 MB comment-padded valid OpenCV YAML fixture isolates transport
allocation: bytes input traced 1.659 MB while the warmed mmap public path
traced 0.010 MB. The complete one-run 36-codec harness completed without codec
failures, preserving the established mmap/sink allocation directions and all
retained O4/O5 controls. Calibration inspection validates the complete small
metadata document; because these formats contain no bulk payload beyond that
metadata, it intentionally has approximately the same latency as a full
record decode.

## g2o pose-graph baseline — 2026-07-24

The harness now covers 37 codecs (35 single-file plus the two COLMAP
directories). The representative g2o fixture contains 25,000 SE3 nodes, 24,999
SE3 edges, one fixed node, and full symmetric float64 information matrices:
10.6 MB of logical record arrays and 4.7 MB of deterministic text. Five-run
medians were:

```text
operation                         throughput
------------------------------------------------
native buffer write              104 MB/s
native direct-sink write          106 MB/s
independent writer                50 MB/s
native in-memory read             248 MB/s
native public mmap read           255 MB/s
independent reader                98 MB/s
native/oracle read                2.53x
full read / inspection            41.714 / 31.929 ms (1.31x)
```

The independent implementation is a strict stdlib/NumPy parser/writer rather
than the SceneIO reader reflected through Python. It validates vertex ids,
XYZ+XYZW coefficients, fixed declarations, edge endpoints, all 21
upper-triangle information coefficients, and exact record widths.

Bytes input traced 4.7 MB while the public mmap path traced effectively zero.
Buffer-plus-file output traced 4.7 MB while the chunked direct sink traced
effectively zero and remained byte-identical. Sampled RSS is dominated by the
owned graph arrays and hash tables (about 56–59 MB on read); inspection reduces
that to about 39 MB by retaining only ids/endpoints needed for whole-graph
referential validation. No partial selector is claimed because a range slice
would need a separately specified induced/subgraph contract.

## COLMAP feature-database baseline — 2026-07-24

The harness now covers 38 codecs: 35 buffer-backed files, the path-native
SQLite database, and two COLMAP directory formats. The representative database
contains one camera, 64 images with 1,024 four-column keypoints and 128-byte
descriptors each, and 63 consecutive image pairs with raw and verified
matches. That is 9.65 MB of logical record data in a 9.92 MB SQLite file.
Five-run medians were:

```text
operation                              result
-------------------------------------------------------------
native transactional write            178 MB/s
stdlib sqlite3 transaction             185 MB/s
native full read                     1,405 MB/s
stdlib sqlite3 full materialization  1,634 MB/s
metadata inspection                  0.808 ms  (8.50x vs full)
one-image partial read               0.525 ms (13.10x vs full)
one-pair partial read                0.421 ms (16.31x vs full)
```

## SuperSplat compressed-Ply baseline — 2026-07-24

Compressed PLY raises the harness to 39 codecs: 36 mmap-backed single-file
formats, the path-native SQLite database, and two COLMAP directories. The
representative degree-0 cloud has 200,000 Gaussians (11.2 MB of canonical
`GaussianCloud` values) and encodes to 3.3 MB. Five-run local MSVC medians:

```text
operation                              result
-------------------------------------------------------------
deterministic Morton/quantized write   341 MB/s
in-memory decode                        98 MB/s
public mmap decode                      97 MB/s
metadata inspection                  0.094 ms (1,230.84x vs full)
1/16 point selection                  7.684 ms (15.01x vs full)
```

The public mmap read removes the 3.3 MB whole-file Python allocation and the
direct sink removes the same output-sized allocation while measuring 346 MB/s
versus 332 MB/s for the buffer-plus-file path. The partial result materializes
only its selected `GaussianCloud` rows; its sampled RSS increase was 0.3 MB
versus 13.7 MB for the full decode. A generated 103+ MiB sparse-container test
also keeps traced Python allocation below 4 MiB for an eight-point selection.
The writer body is byte-identical to the pinned PlayCanvas
`splat-transform` 3.1.6 reference vector; the producer-specific header comment
is intentionally different.

The independent reference uses stdlib `sqlite3` prepared statements and an
explicit transaction; pycolmap separately verifies both directions in the
parity suite. Native full read, inspection, both selectors, and transactional
write each stayed below 0.05 MB traced Python allocation. Full-read sampled RSS
was 8.9 MB for the owned decoded arrays; inspection and either selector stayed
near zero above the SQLite page cache and selected output.

## PlayCanvas SOG v2 baseline — 2026-07-24

SOG raises the harness to 40 codecs and the buffer-backed differential/sink
sweep to 37. The representative degree-0 cloud has 200,000 Gaussians (11.2 MB
of canonical values) and encodes to a 2.9 MB stored ZIP whose payload members
are lossless WebP. Five-run local MSVC medians:

```text
operation                              result
-------------------------------------------------------------
deterministic Morton/codebook write     35 MB/s
in-memory decode                       454 MB/s
public mmap decode                     430 MB/s
metadata inspection                  0.353 ms (73.65x vs full)
1/16 point selection                 18.273 ms (1.42x vs full)
```

The public mmap path removes the 2.9 MB whole-file Python allocation, and the
direct sink removes the same output-sized allocation while retaining 34 MB/s
throughput. Full decode sampled 22.4 MB RSS growth; the point-selection path
sampled 11.1 MB because WebP has no sub-image random access but only selected
`GaussianCloud` rows are allocated. A generated 106.4 MB logical fixture keeps
traced Python allocation below 4 MiB for an eight-row selection.

Both SceneIO- and PlayCanvas-produced SH2 archives were cross-decoded through
pinned `splat-transform` 3.1.6 commit
`6b07ba05d731eac1163ad4ff1b14e47e5e3f162c`; all six exposed fields were
bit-identical after the reference re-exported them as Gaussian PLY. The
committed independent Pillow/NumPy/ZIP oracle covers every SH degree without
sharing the SceneIO codec.

## mkkellogg KSplat v0.1 baseline — 2026-07-24

KSplat raises the harness to 41 codecs and the buffer-backed
differential/sink sweep to 38. The representative degree-0 cloud contains
200,000 Gaussians (11.2 MB of canonical values) and encodes to 4.8 MB with the
default level-1 float16/bucket representation. Five-run local MSVC medians:

```text
operation                              result
-------------------------------------------------------------
deterministic bucketed write             568 MB/s
in-memory decode                         988 MB/s
public mmap decode                       874 MB/s
metadata inspection                    0.039 ms (332.84x vs full)
1/16 point selection                   0.774 ms (16.56x vs full)
```

The public mmap path removes the 4.8 MB whole-file Python allocation, and the
direct sink removes the same output-sized allocation while retaining 542 MB/s
throughput. Full decode sampled 15.2 MB RSS growth; the selector sampled
0.1 MB because it validates the complete section layout but allocates only the
selected `GaussianCloud` rows. A generated 105.6 MB level-0 fixture keeps
traced Python allocation below 4 MiB for an eight-row selection.

## Polygon-preserving mesh PLY baseline — 2026-07-24

Mesh PLY raises the harness to 42 codecs and the buffer-backed
differential/sink sweep to 39. The representative full-domain mesh contains
333,333 vertices, 166,666 triangle faces, independent vertex/corner normals,
UVs, and RGBA, plus primitive/material ranges. Its canonical buffers total
28.0 MB and encode to 30.0 MB. Five-run local MSVC medians:

```text
operation                              result
-------------------------------------------------------------
deterministic binary-LE write           886 MB/s
in-memory decode                        325 MB/s
public mmap decode                      283 MB/s
metadata inspection                   0.089 ms (1,110.41x vs full)
1/16 face selection                  72.240 ms (1.34x vs full)
```

The public mmap path removes the 30.0 MB whole-file Python allocation. The
direct sink removes the same output-sized allocation while reaching 673 MB/s
versus 618 MB/s for the buffer-plus-file path. A separate oracle-enabled run
measured SceneIO and trimesh decode at 315 and 325 MB/s respectively; the
triangle output opens in trimesh with exact vertices and indices. The
independent struct/NumPy oracle additionally verifies all polygon, corner,
primitive, material, transform, and coordinate fields that trimesh does not
retain.

A generated 105.6 MB binary mesh fixture keeps traced Python allocation below
4 MiB on the public mmap path. A separate 50.0 MB, two-face fixture places
12.5 million corners in an unselected face: the face-range reader validates
every index without retaining that face, keeps traced Python allocation below
1 MiB, and uses less than three-fifths of the full decoder's fresh-process RSS.
On the representative fixture, sampled RSS falls from 63.4 MB to 42.1 MB
because the contract retains the complete vertex domain while omitting
unselected face/corner arrays.

The complete one-run 42-codec harness finishes without failures; its mesh row
measured 855 MB/s write, 328 MB/s in-memory decode, 289 MB/s public mmap
decode, 0.142 ms inspection, and a 1.36x face-selection speedup.

## Polygon-preserving OBJ/MTL baseline — 2026-07-25

OBJ/MTL raises the harness to 43 codecs and the buffer-backed benchmark sweep
to 40. The representative mesh contains 333,333 vertices and 111,111 triangle
faces with vertex-domain normals, UVs, and RGB8. Its canonical buffers total
14.7 MB and encode to a 53.8 MB deterministic OBJ. Five-run local MSVC medians
were:

```text
operation                                 result
----------------------------------------------------------------
deterministic write before formatter fix   7.4 MB/s
locale-independent deterministic write   20.4 MB/s (2.78x)
in-memory decode                          18.5 MB/s
public mmap decode                        12.7 MB/s
trimesh decode                             9.1 MB/s
metadata inspection                    544.790 ms (2.12x vs full)
```

Replacing one locale-classic stream construction per scalar with an explicit
C numeric locale per encode and bounded canonical float appends produced the
writer gain while preserving byte-for-byte determinism across process locales
and float32 round trips. The public mmap path removes the 53.8 MB
whole-file Python allocation (53.83 MB to 0.013 MB traced), and the direct sink
removes the same output-sized write allocation (53.83 MB to 0.005 MB traced)
while matching the buffer writer. Inspection retains only directive counts and
material/texture metadata; sampled RSS falls from 265.5 MB for a full decode to
53.8 MB. No face selector is claimed: headerless OBJ requires a complete
directive/index scan, and its independent attribute pools need an explicit
subset contract before a partial result can be lossless.

The independent Trimesh writer/reader is measured alongside hand-built
polygon, negative-index, object/group/smoothing, MTL-factor, and texture-map
fixtures. Both core and public-path suites preserve vertex- versus corner-domain
normal/UV indexing, and malformed/lossy constructs reject rather than being
silently triangulated or discarded.

## Strict STL/OFF mesh baseline — 2026-07-25

STL and OFF raise the harness to 45 codecs and the buffer-backed differential
and direct-sink sweep to 42. The representative STL contains 111,111
independent triangles with explicit facet normals (8.0 MB of canonical arrays,
5.56 MB binary file). The indexed OFF fixture contains 33,333 vertices reused
by 333,333 triangles (8.4 MB of canonical arrays, 7.55 MB ASCII file). Five-run
local MSVC medians:

```text
codec  write     read      mmap read  oracle W/R  inspect            partial
--------------------------------------------------------------------------------
stl    1,021 MB/s 1,166 MB/s 935 MB/s   362/204     2.331 ms (3.67x)  2.624 ms (3.26x)
off      206 MB/s   442 MB/s 396 MB/s    41/13     10.685 ms (1.98x) 17.487 ms (1.21x)
```

STL's public mmap read removes the 5.57 MB traced input allocation and its
direct sink removes the 5.57 MB output allocation (both fall to about
0.01/0.001 MB). OFF removes the corresponding 7.56 MB input and output
allocations. The STL sink reaches 1,047 MB/s versus 814 MB/s for the
buffer-plus-file path; OFF reaches 201 versus 189 MB/s.

Independent binary `struct` and ASCII token parsers validate exact file
records, all eight supported OFF vertex variants, polygon boundaries, facet
normal policy, and malformed extent/index handling. Trimesh consumes both
writers and supplies independent binary/ASCII STL and OFF inputs. Face
selection validates the complete mapped input while materializing only the
selected topology; OFF deliberately retains its complete vertex domain.

## Plain glTF/GLB scene baseline — 2026-07-25

Plain glTF and GLB raise the registry and harness to 47 codecs. The benchmark
scene has one source mesh split into four triangle primitives, one node, and one
scene. Its canonical buffers total 13.2 MB for the trimesh-compatible glTF
payload view and 14.7 MB including SceneIO's GLB attribute accounting; the
deterministic outputs are 12.0 MB JSON+BIN and 13.3 MB GLB. Five-run local MSVC
medians were:

```text
codec  core write  core read  mmap read  oracle W/R  inspect             partial
----------------------------------------------------------------------------------
gltf   573 MB/s    904 MB/s   739 MB/s   231/1045    0.081 ms (220.26x)  4.168 ms (4.29x)
glb    526 MB/s    948 MB/s   751 MB/s   215/746     0.097 ms (200.61x)  5.044 ms (3.87x)
```

The public mmap readers remove the complete 12.0/13.3 MB encoded-size Python
allocation (traced peaks fall to displayed 0.0 MB). Direct sinks likewise
remove the output-sized Python allocation and match the buffer writers
byte-for-byte. The paired glTF sink encodes once, writes JSON and BIN native
temporaries, and atomically installs the pair; at this size it measured
451 MB/s versus 467 MB/s for non-atomic buffer-plus-direct-file writes. GLB
measured 471 versus 431 MB/s. One-of-four primitive reads reduce sampled RSS
from 26.4 to 5.1 MB for glTF and from 29.2 to 5.7 MB for GLB.

Hand-built independent JSON/GLB fixtures exercise external and data URI
buffers, byte strides, normalized u16 UVs, normalized RGB8 colors, sparse
accessors, duplicate/empty material names, samplers, and node TRS. Both
pygltflib and trimesh consume SceneIO output. Lifetime, truncation, malformed
extent, convention-guard, missing-resource, rollback, sink-identity, and
large-external-buffer allocation tests cover the optimized paths.

## LAZ compressed-point baseline — 2026-07-25

LAZ raises the registry and benchmark harness to 48 codecs and the
buffer-backed differential/direct-sink sweep to 43. The representative
fixture contains one million colored/intensity points (12.0 MB of canonical
XYZ payload) and encodes to a 14.6 MB format-2 LAZ file with 50,000-point
chunks. Five-run local MSVC medians were:

```text
operation                         SceneIO       oracle laspy/lazrs
-----------------------------------------------------------------
direct-sink write                  66 MB/s              144 MB/s
in-memory read                    235 MB/s              393 MB/s
public mmap read                  184 MB/s                    -
metadata inspection            0.049 ms (1,335x)               -
one-sixteenth point range      20.558 ms (3.17x)                -
```

The mapped read removes the full 14.6 MB Python input allocation, and the
seekable streaming sink removes the corresponding output allocation while
improving over the 62 MB/s buffer-plus-file path. The partial decoder validates
the LAS/LASzip container, reads one anchor point to preserve the full record's
origin, and decompresses only overlapping chunks. Its sampled RSS was 1.5 MB
versus 47.2 MB for a full decode. SceneIO and the laspy/lazrs oracle encode the
same format-2 XYZ, RGB16, and intensity fields from a shared exact-u16 fixture.

Independent laspy/lazrs fixtures cover point formats 0-3 and 6-8 in both LAS
1.2 and 1.4 containers. The codec rejects waveform formats, extra bytes,
unrelated VLR/EVLR metadata, COPC, invalid global-encoding semantics, malformed
item schemas, unbounded chunk metadata, and trailing unindexed bytes. Bytes,
memoryview, mmap, one/many lanes, direct sink, short writes, empty files,
multi-chunk ranges, every truncated prefix, and isolated lifetime/memory paths
are checked separately from the benchmark.

The N0 instrumented run exposed signed overflow in upstream LAZperf while
decoding a malformed format-1.4 integer layer. SceneIO's local arithmetic patch
keeps valid full-int32 transitions bit-exact and makes that mutation reject.
The ordinary five-run harness measured the exact pre-patch commit at
178/168 MB/s for buffer/mmap read and the patched build at 179/168 MB/s after
unrelated background build load was removed.
A same-machine, alternating direct-kernel check used the unchanged one-million
point fixture and identical 14,584,870-byte output
(`d35a9d4e38cb907a5d7a39607890b59548f0c2c0fc9e802dc40100b759468ef0`):

```text
pair/order       unpatched read   patched read   patched delta
----------------------------------------------------------------
old then new        162.01 MB/s     184.27 MB/s          +13.7%
new then old        193.37 MB/s     185.08 MB/s           -4.3%
old then new        205.41 MB/s     201.56 MB/s           -1.9%
```

There is no consistent directional loss. The median of the three paired
deltas is -1.9%; independently dividing the two column medians gives -4.3%.
Both are within the observed same-host run-order variation. The surrounding
five-run harness also remained structurally green: mmap removed the 14.6 MB
Python allocation, the sink removed the output allocation, inspection stayed
above 1,000x, and partial decode stayed above 2.8x.

## N0.5 local closure checkpoint — 2026-07-25

The one-run, `--scale 0.001` all-50-codec smoke completed successfully. The
first production-scale five-run guard had one non-reproduced reversal for LAS
parallel read (0.75x). An immediate `--only las --runs 5` diagnostic measured
1.43x, and the complete 50-codec rerun measured 1.82x for the same row while
passing every retained O4/O5 directional and mmap/sink allocation guard. The
isolated diagnostic changed only scope to LAS; the two complete guards used
identical thresholds, fixtures, codec set, and lane counts.

The exact sequence was `bench/bench_io.py --runs 1 --scale 0.001`,
`bench/bench_io.py --runs 5 --require-o4-gains --require-o5-inspect-gains
--require-o5-partial-gains`, `bench/bench_io.py --only las --runs 5`, then the
unchanged complete five-run guard again. Each invocation also used `--json`
to retain its result under `build/`.

The corresponding option-off MSVC tree collected 2,923 tests and passed 2,919
with four documented skips. An sdist-first Windows wheel build, exact license
and payload audit, native dependency inspection, and clean Python 3.12
environment containing only SceneIO plus NumPy all passed. Artifact hashes and
entry-level evidence are recorded in
`docs/next_stage_implementation_checklist.md`.

## N0.5 hosted LAZ boundary follow-up — 2026-07-25

Snapshot `c759f3c` passed normal CI, the full retained performance guard, the
three-OS mmap matrix, pinned GCC-10 portability, and the three-platform
wheel-build dry run. The full compiler-instrumented suite reproducibly stopped
at the first valid format-0 `INT32_MAX`/`INT32_MIN` transition. An isolated
GCC-13 reproduction identified signed coordinate reconstruction in the pinned
LAZperf legacy path; after that path was corrected, the format-6 case exposed
the equivalent layered path.

The follow-up centralizes the specified LAS modulo-2^32 conversion and uses it
for legacy and layered coordinate differences and reconstruction. Direct
native checks cover wrapped addition/subtraction, the full-range compressor,
and both corrector configurations. The focused GCC-13 build passes all 62 LAZ
tests, a fresh manylinux2014 GCC-10 build passes the same 62 tests, and the
complete local MSVC suite passes 2,919 tests with four documented skips.

The first local five-run timing overlapped a Linux rebuild and is retained only
as diagnostic evidence. An uncontended repeat measured 229 MB/s in-memory read
and 178 MB/s mmap-path read, versus 179/168 MB/s at the earlier ordinary
checkpoint. Bytes and sink writes both measured 63 MB/s, the sink retained its
whole-output allocation reduction, inspection remained 1,091x faster than
full decode, and partial read remained 3.24x faster.

## N0.5 hosted closure at `a5e7fa4` — 2026-07-25

Normal CI run
[30181287022](https://github.com/SceneAPI/SceneIO/actions/runs/30181287022)
passes the complete Linux suite, all 50 benchmark builders, the retained
directional and mmap/sink allocation guard, pinned GCC 10, and the
Linux/Windows/macOS focused matrix. The hosted LAZ row measured 56 MB/s on
both in-memory and mmap reads, with 14.6 MB versus 0.0 MB traced input
allocation. Buffer and sink writes both measured 42 MB/s, with 14.6 MB versus
0.0 MB traced output allocation. Inspection was 4,991.79x faster than full
decode and the bounded point range was 6.53x faster. These hosted values are a
separate runner checkpoint, not a replacement for the local MSVC baseline.

Compiler-instrumented run
[30181287161](https://github.com/SceneAPI/SceneIO/actions/runs/30181287161)
collects exactly 2,923 tests and completes 2,894 passes with 29 documented
platform/oracle skips; its focused native lifetime job also passes. Explicit
attempt 2 repeats those exact collection/pass/skip counts and the focused
native lifetime pass at the same `a5e7fa4` commit. The
nonpublishing release run
[30181286675](https://github.com/SceneAPI/SceneIO/actions/runs/30181286675)
builds and smoke-tests Linux, macOS, and Windows wheel sets plus the source
archive, with the PyPI job skipped.

## ImageSequence directory and raw Y4M baseline — 2026-07-25

The sequence wave raises the registry and complete harness to 50 codecs and
the buffer-backed differential/direct-sink sweep to 44. `ImageSequence`
supports owned lazy encoded paths or owned uint8 planar Y/U/V frames, with
exact optional nanosecond timing and explicit chroma/range/matrix/rate/aspect
metadata.

The representative Y4M fixture contains four odd-dimension-ready 4:2:0 frames
(6.3 MB of canonical planes and a 6.3 MB file). Five-run local MSVC medians:

```text
operation                                  result
--------------------------------------------------------------
direct native encode                    1,932 MB/s
in-memory decode                        7,584 MB/s
public mmap decode                      2,574 MB/s
metadata inspection                    0.073 ms (33.48x)
one-sixteenth frame range               0.583 ms (4.19x)
```

The mmap path removes the full 6.3 MB traced Python input allocation, and the
direct sink removes the matching 6.3 MB output allocation while reaching
3,902 MB/s versus 1,113 MB/s for buffer-plus-file writing. Full decode sampled
12.4 MB RSS growth; the selected range sampled 1.5 MB. A separate oracle-enabled
three-run pass measured the independent Python writer/reader at 676/804 MB/s.
All six supported
layout tokens (mono, three 4:2:0 sitings, 4:2:2, and 4:4:4), odd dimensions,
exact rational timing, CRLF, malformed prefixes, mmap lifetime, and short
writes are independently pinned. The implementation performs no RGB
conversion and has no video-framework dependency.

The companion directory fixture stores 32 independently encoded PPM frames
(6.3 MB). Lazy reads retain only validated absolute frame paths and optional
manifest timing. The bounded transactional copy writer measured 242 MB/s with
a 1.3 MB traced peak, independent of total output size; full lazy read measured
1,565 MB/s, inspection was 1.45x faster, and a middle frame range was 1.61x
faster. Exact encoded bytes, natural ordering, deterministic manifests,
same-directory replacement, heterogeneous-frame rejection, and failed-stage
rollback are covered separately from timing.

## COLMAP malformed-input RSS qualification — 2026-07-25

The former absolute 16 MiB checks are replaced by a payload-relative
fresh-process protocol. Each child first exercises a fixed 64-byte malformed
fixture to warm imports, native dispatch, filesystem metadata, and allocator
pools. It then measures one first size-dependent operation using both sampled
current RSS and the platform process high-water mark. Three independent child
processes are run for approximately 8 MiB and 32 MiB malformed payloads, and
the median increase between sizes must stay below one quarter of the added
file-controlled extent.

The test retains exact `FormatError` checks at both measured sizes for
oversized observation counts and unterminated image names, plus a 1 MiB
`tracemalloc` ceiling. A test-only transient resident allocation clears the
process-startup high-water headroom, adds one file-controlled extent, releases
it before the final current-RSS sample, and is required to fail the same
payload-relative assertion using its high-water delta. This independently
checks the platform high-water conversion rather than relying on sampler
timing or retained current RSS.

Local MSVC medians were:

```text
malformed case       SceneIO 8/32 MiB delta    transient high-water control
------------------------------------------------------------------------------
observation extent       0.160 / 0.156 MiB           8.15 / 32.15 MiB
unterminated name        0.141 / 0.156 MiB           8.14 / 32.13 MiB
```

The absolute values are diagnostic only. The portable regression contract is
the paired slope, failure diagnostics containing every repeated sample, exact
error behavior, and a positive allocating control. The clean pinned
manylinux2014 GCC 10.2 job passes that contract; the pending hosted
Windows/Linux/macOS portability workflow will validate it by pass/fail rather
than treating any single machine's RSS as a numeric SLA.

## R2 aggregate-registry equivalence — 2026-07-26

The aggregate staging boundary changes registry construction only; codec
payload and metric behavior must remain unchanged. Two parent captures at
`14bf53b` and one candidate capture used:

```text
.venv/Scripts/python.exe bench/bench_io.py \
  --runs 1 --scale 0.001 --skip-oracles --json <output>
```

All three contain the same 50 rows and reproduce portable structural
projection SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
The projection retains codec order, payload/file sizes, nested result schema,
and every traced-allocation key. It normalizes `*_peak_mb` values because
`tracemalloc` baselines vary with the Python runtime and platform, and it
excludes timing/throughput and RSS diagnostics. The first hosted Linux run
made that distinction observable: its image-sequence inspect and partial
peaks were about 7.5 KiB below the Windows captures despite identical
behavior. The comparator still fails when a peak field disappears or is
renamed, or when a stable structural value changes. Top-level O1/O3/O5
benchmark acceptance remains in the separate strict guard described below;
the typed-adapter allocation paths retain their focused memory tests.

`bench/compare_io_structure.py` makes the portable comparison reproducible.
The normal CI smoke uses the contract's matching `--skip-oracles` fixture
surface before invoking it; oracle correctness remains covered by the full
test suite.

A separate default-scale five-run candidate invocation with
`--require-o4-gains --require-o5-inspect-gains
--require-o5-partial-gains` completed successfully and reported that the
stable O4 directions plus mmap/sink allocation bounds passed. Its JSON is
intentionally not compared with the small-fixture structural hash because
payload and encoded sizes scale with the generated fixture.

Fifteen same-host samples were interleaved between an extracted parent source
tree and the candidate source tree. Candidate/parent median import times were
5.632/5.659 ms for `import sceneio`, 75.163/75.218 ms for the I/O facade, and
7.394/7.464 ms for `_core`. The candidate adds exactly one eager facade
module, `sceneio.io._registry.assembly`; the other two import boundaries have
no module-set delta. These timings are local diagnostic evidence. The durable
contracts are the exact module sets, the existing broad alert thresholds, and
the same-host relative comparison.

## R2 arrays-family structural equivalence — 2026-07-26

The arrays extraction is an organization-only move for PFM, NPY, NPZ,
safetensors, FLO, and DMB. Two parent captures at exact commit `6086315` and
the committed result at `d99dcf0` use the same small all-codec command as the
aggregate unit. The result reproduces both the portable 50-row projection SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and the six-array-row projection SHA-256
`5c0104dc8a0372ede12a86f48c8c57a7426718b030c95ec9d7088a9b26364aac`.
This unit claims no codec speedup: encoded sizes, stable schema, traced-memory
fields, mmap/sink relationships, inspection results, and partial-read
surfaces remain exact.

The default-scale five-run invocation with all retained O4/O5 requirements
completed successfully and reported stable O4 gains plus mmap/sink memory
bounds. Its JSON remains separate from the small-fixture structural
projection because generated payload sizes intentionally differ.

Fifteen interleaved Windows samples compared extracted parent and candidate
source trees while using the same compiled module. Candidate/parent medians
were 19.797/19.889 ms for `import sceneio`, 97.138/96.928 ms for the I/O
facade, and 22.042/22.218 ms for direct `_core`. Only the I/O facade changes
its eager module set, adding exactly `_registry.families.arrays` and
`_inspectors.arrays`; counts move from 37 to 39. The other two module sets are
unchanged. Timing remains same-host diagnostic evidence; exact module sets,
parent-derived behavior contracts, and the structural hashes are the durable
acceptance evidence.

Normal CI run 30207617248 and compiler-instrumented run 30207617253 pass the
exact `d99dcf0` commit, including the retained throughput/allocation guard and
the full cross-platform and instrumented validation lanes.

## R2 points-family structural equivalence â€” 2026-07-26

The points extraction is an organization-only move for PLY, PCD, XYZ, PTS,
LAS, and LAZ. Two parent captures at exact commit `efb106e` and the working
candidate use the same small all-codec command as the aggregate unit. All
three reproduce portable 50-row projection SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and six-point-row projection SHA-256
`8282b574166aeb88d0eb51ded126566d7a4f21b0752244ea0c987dcee06437bd`.
This unit claims no codec speedup: encoded sizes, stable schema, traced-memory
fields, mmap/sink relationships, inspection results, and point-range surfaces
remain exact.

The default-scale five-run invocation with all retained O4/O5 requirements
passes and reports stable O4 gains plus mmap/sink memory bounds. Generated
50,000-point fixtures separately confirm bounded metadata inspection and
prompt path release for all six formats.

Fifteen interleaved Windows samples compare exact parent and candidate source
trees with the same compiled module. Candidate/parent medians are
17.565/18.287 ms for `import sceneio`, 89.031/87.407 ms for the I/O facade,
and 19.725/19.734 ms for direct `_core`. Only the I/O facade changes its eager
module set, adding exactly `_registry.families.points` and
`_inspectors.points`; counts move from 39 to 41. The other two module sets are
unchanged. Timing is same-host diagnostic evidence; exact module sets,
parent-derived behavior contracts, and structural hashes are the durable
acceptance evidence.

The pre-review staged-tree package check uses tree
`942314b30d5e21a62420a0c1ff1332356046792b`. Its source archive SHA-256 is
`2cd51368e13c5f93fb98e53214861c9d0356686f9a727bda5f23157cc14a4405`;
the Windows cp312-abi3 wheel SHA-256 is
`8310dfb7102cb4dd1b6e8390a9b803831ae3bd7877273aa3c5c418f76694aa5c`.
The wheel adds only the two intended lower point modules relative to the
arrays checkpoint and passes a fresh NumPy-only installed smoke plus all-six
point and point-range probes.

All three independent reviews are clear for staged tree
`442093b402db2af290c9a19a61747b6691e2af1c`. The test/performance review
independently reproduced both benchmark projections and the strict guard, and
its 729-test focused matrix passed. No review required a source change. A final
exact-tree artifact confirmation follows this documentation closure.

The final exact staged tree is
`688f0a4caa81edf6e499f7b72e1bc03117a4ddf0`. Its source archive SHA-256 is
`cad77d9a9b311c686279d150cc2a68c4a4221f21db1b1cdc2473af38d96ce3ab`
and its Windows cp312-abi3 wheel SHA-256 is
`171aa3ff0b6e28a59ca45489b72818289a2dbb7f8bf63dd5e666be9b9221676a`.
The exact tree is commit `686f42e`; normal CI run 30210055913 and
compiler-instrumented run 30210055930 pass, including the retained
throughput/allocation guard and the full cross-platform lanes.

## R2 reconstruction-family registry equivalence — 2026-07-26

The reconstruction registry extraction is an organization-only move for the
12 non-contiguous reconstruction, pose, state, graph, and database codecs.
Two candidate captures use:

```text
.venv/Scripts/python.exe bench/bench_io.py \
  --runs 1 --scale 0.001 --skip-oracles --json <output>
```

Both reproduce the portable all-50 projection SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered 12-row projection SHA-256
`92d354dfd4aa415cbd908168d55310902e56fd21541c94d66fc740c1915540d9`,
matching both frozen parent captures. The strict default-scale five-run
invocation with all retained O4/O5 requirements also passes. This extraction
claims no codec speedup; identical output structure, mmap/sink allocation
relationships, inspection, and partial-read behavior are the acceptance
criteria.

A separate three-run family-only diagnostic uses `--scale 1 --cold-cache` and
all 12 `--only` selectors. Encoded sizes range through 35.2 MiB for EuRoC and
9.9 MiB for COLMAP DB. Traced Python allocation remains approximately zero
above the mmap/direct-path readers and direct sinks, while the corresponding
bytes writers allocate approximately the encoded size. Metadata-only reads
remain faster than full decode for every scaled family member in this sample;
COLMAP image/pair selectors remain materially faster, while the EuRoC
half-open state range selected by this fixture is intentionally large and is
treated as a behavior/memory diagnostic rather than a timing target.

Windows has no `POSIX_FADV_DONTNEED`, and the harness reports:

```text
WARNING: this platform has no POSIX_FADV_DONTNEED; cold-cache hint was unavailable.
```

Therefore these family measurements are warm-cache diagnostics. They are not
presented as confirmed cold-cache results.

Fifteen interleaved parent/candidate imports were also run from exact exported
source trees with `python -S` and an explicit `PYTHONPATH`, so the editable
install could not redirect either sample to the working tree. Median timings
are diagnostic rather than acceptance thresholds:

| Import | Parent | Candidate | SceneIO modules |
|---|---:|---:|---|
| `import sceneio` | 18.687 ms | 18.771 ms | 7 / 7, exact same set |
| I/O facade | 96.710 ms | 96.938 ms | 42 / 43 |
| direct `_core` | 21.696 ms | 21.711 ms | 8 / 8, exact same set |

The sole I/O-facade module addition is
`sceneio.io._registry.families.reconstruction`, as required by the extraction.
The measured deltas are within ordinary import-timing variation and no speed
claim is made.

The reviewed exact-tree package inventory is 321 tracked files, 322
source-archive files (only generated `PKG-INFO` is extra), and 79 wheel
members. All tracked archive files and all changed packaged runtime files
match their Git blobs. The wheel retains 15 license/attribution members, one
native extension, NumPy as its sole unconditional dependency, and the same
native dependency list as the parent. An external NumPy-only installed-wheel
run exercises every reconstruction family member and completes the packaged
smoke.

The first hosted normal run at extraction commit `be836a0` found an
AppleClang-only byte spelling in BAL's canonical 180-degree quaternion:
`[-0.0, 1.0, 0.0, 0.0]` instead of `[0.0, 1.0, 0.0, 0.0]`. The nonzero
components and represented rotation are identical. The repair normalizes only
exact-zero quaternion components after canonical sign selection. Benchmark
structure, the retained guard, and exact-tree package evidence are rerun
before closing the checkpoint; no speed claim is attached to this
deterministic-output correction.

The repaired candidate reproduces the portable all-50 structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`,
and the default-scale five-run throughput/allocation guard passes. The
zero-component store has no measurable BAL regression.

The closed combined implementation tree is
`06f89e8b685c3536af0e67a462d9cff90a86bc9c`. Its source archive SHA-256 is
`89304b849aeef699fadb79c2fed8c211b6bd84150ff4bfe313b9b7547ff7bccb`;
the derived Windows cp312-abi3 wheel SHA-256 is
`ffbc561b547423cb6266db2540afdb698f75b5f30785077bd1cead7f8570b87b`.
Normal run `30218232248` passes the complete suite, retained performance
guard, all three reconstruction operating systems, all mmap lanes, and the
isolated GCC-10 lane. Compiler-instrumented run `30218232246` passes both
jobs.

## R2 splat-family inspector equivalence — 2026-07-26

The six splat metadata readers moved without algorithm changes from the
compatibility facade to `_inspectors/splats.py`. Two candidate runs use:

```text
.venv/Scripts/python.exe bench/bench_io.py \
  --runs 1 --scale 0.001 --skip-oracles --json <output>
```

Both reproduce the portable all-50 structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered six-row SHA-256
`5c6adc3584ba25050c885b37313d009311e2253b0c841cbc8738b806cb090bfd`,
matching both frozen parent captures. The separate default-scale five-run
invocation with all retained O4/O5 requirements passes.

An exact-parent inspector comparison uses the generated 36 MiB-plus fixtures
for every family member. It takes 15 randomized interleaved timing samples
and 15 traced-allocation samples per parent/candidate implementation. A row
passes when the candidate median increase is no larger than the maximum of
10 percent of the parent median, three times the sum of both median absolute
deviations, or 0.05 ms, and its maximum traced allocation does not exceed the
parent maximum.

| Codec | Parent inspect | Candidate inspect | Parent/candidate peak |
|---|---:|---:|---:|
| `gaussian_ply` | 0.0343 ms | 0.0355 ms | 11,650 / 11,650 bytes |
| `compressed_ply` | 0.0852 ms | 0.0841 ms | 15,339 / 15,339 bytes |
| `sog` | 0.3667 ms | 0.3642 ms | 1,059,105 / 1,059,105 bytes |
| `ksplat` | 0.0292 ms | 0.0297 ms | 14,394 / 14,394 bytes |
| `spz` | 0.0324 ms | 0.0324 ms | 10,012 / 10,012 bytes |
| `splat` | 0.0057 ms | 0.0059 ms | 1,320 / 1,320 bytes |

Every row passes. This is equivalence evidence for the ownership-only move,
not a performance-gain claim. The broader read/write/partial family
comparison remains in the registry-extraction gate.

Pre-final package tree `301fd6693fe758dfd555337708bf7bd0ca73384a`
produces a 326-file source archive with only generated `PKG-INFO` beyond its
325 tracked files and no missing or differing blob. Its SHA-256 is
`f04fc37d7b79ecc41d19744dee7195746ab306e78f626a1dc387e48ef3a29606`.
The derived 80-member Windows cp312-abi3 wheel SHA-256 is
`c6a7248a0eb88a5920c7f11f28e745d66dc42f8b442c0c680162d1481a8d5904`.
The wheel retains one native extension, all 15 attribution entries, NumPy as
its only unconditional dependency, and no packaged build/include/lib/share/bin
tree. A fresh NumPy-only environment passes the packaged smoke and explicit
all-six splat inspection/read/partial/path-release probe.
