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

## R2 splat-family registry equivalence — 2026-07-26

The final family extraction moves the same six `Codec(...)` expressions into
`_registry/families/splats.py` and injects the facade-owned SOG callbacks. It
changes registry ownership only. Two candidate captures use the command above
and reproduce both the portable all-50 structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and ordered six-row SHA-256
`5c6adc3584ba25050c885b37313d009311e2253b0c841cbc8738b806cb090bfd`.
The default-scale five-run throughput/allocation guard passes.

A separate exact-parent comparison uses one identical 256-Gaussian corpus for
commit `0696533e515b5f8e65cbb676df28d852f9d0a049` and the candidate. It takes
15 randomized interleaved fresh-process samples per source. Each process warms
the operation, measures one call, and separately records traced allocation.
The acceptance limit is parent median plus the maximum of 10 percent of that
median, three times the sum of parent/candidate median absolute deviations, or
0.05 ms. Candidate maximum traced allocation must not exceed the parent.

| Operation | Parent | Candidate | Acceptance limit | Parent/candidate peak |
|---|---:|---:|---:|---:|
| compressed PLY inspect | 0.1841 ms | 0.1836 ms | 0.2341 ms | 16,307 / 16,307 B |
| compressed PLY partial | 0.1561 ms | 0.1552 ms | 0.2061 ms | 11,402 / 11,402 B |
| compressed PLY read | 0.2498 ms | 0.2635 ms | 0.2998 ms | 11,218 / 11,218 B |
| compressed PLY write | 0.4896 ms | 0.5126 ms | 0.6501 ms | 3,189 / 3,189 B |
| Gaussian PLY inspect | 0.1182 ms | 0.1208 ms | 0.1682 ms | 12,797 / 12,797 B |
| Gaussian PLY partial | 0.1180 ms | 0.1265 ms | 0.1738 ms | 11,358 / 11,358 B |
| Gaussian PLY read | 0.1801 ms | 0.1778 ms | 0.3466 ms | 11,174 / 11,174 B |
| Gaussian PLY write | 0.4929 ms | 0.4838 ms | 0.5826 ms | 3,134 / 3,134 B |
| KSplat inspect | 0.0879 ms | 0.0946 ms | 0.1379 ms | 15,650 / 15,650 B |
| KSplat partial | 0.1037 ms | 0.0999 ms | 0.1537 ms | 11,370 / 11,370 B |
| KSplat read | 0.1009 ms | 0.1044 ms | 0.1509 ms | 11,186 / 11,186 B |
| KSplat write | 0.4969 ms | 0.4910 ms | 0.6574 ms | 3,149 / 3,149 B |
| SOG inspect | 0.4278 ms | 0.4409 ms | 0.5505 ms | 33,748 / 33,748 B |
| SOG partial | 0.3558 ms | 0.3630 ms | 0.4359 ms | 12,009 / 12,009 B |
| SOG read | 0.3644 ms | 0.3666 ms | 0.4169 ms | 11,825 / 11,825 B |
| SOG write | 2.1216 ms | 2.1311 ms | 2.3652 ms | 3,764 / 3,764 B |
| SPLAT inspect | 0.0328 ms | 0.0340 ms | 0.0828 ms | 3,091 / 3,091 B |
| SPLAT partial | 0.0999 ms | 0.0983 ms | 0.1499 ms | 11,366 / 11,366 B |
| SPLAT read | 0.0970 ms | 0.0955 ms | 0.1470 ms | 11,182 / 11,182 B |
| SPLAT write | 0.4350 ms | 0.4390 ms | 0.5634 ms | 3,144 / 3,144 B |
| SPZ inspect | 0.1821 ms | 0.1840 ms | 0.2321 ms | 160,322 / 160,322 B |
| SPZ read | 0.1029 ms | 0.0985 ms | 0.1529 ms | 11,174 / 11,174 B |
| SPZ write | 0.5224 ms | 0.5314 ms | 0.7417 ms | 3,134 / 3,134 B |

All 23 rows pass. Every candidate allocation maximum is byte-for-byte equal
to its parent maximum. This is non-regression evidence, not a speed claim.

A scale-1 family diagnostic uses 11.2 MiB logical clouds. Encoded files are
11.2 MiB Gaussian PLY, 3.3 MiB compressed PLY, 2.9 MiB SOG, 4.8 MiB KSplat,
3.4 MiB SPZ, and 6.4 MiB SPLAT. Public path-read traced allocation remains
0.0 MiB at the displayed precision, and sink-write traced allocation remains
0.0 MiB while the legacy byte writers peak near encoded size. Windows reports
that the requested `POSIX_FADV_DONTNEED` hint is unavailable, so these are
warm-cache diagnostics rather than cold-cache measurements.

Fifteen randomized interleaved fresh-process import samples produce:

| Import | Parent | Candidate | SceneIO modules |
|---|---:|---:|---:|
| `import sceneio` | 5.230 ms | 4.452 ms | 7 / 7, exact same set |
| I/O facade | 75.253 ms | 69.788 ms | 43 / 45 |
| direct `_core` | 7.013 ms | 6.271 ms | 8 / 8, exact same set |

The I/O facade adds only `_inspectors.splats` and
`_registry.families.splats`, as planned. Import timings are diagnostic; exact
module sets are the acceptance contract.

Pre-final package tree `7ab4f960dcb43ac95c4cf7269fed7d733bad71cc`
contains 326 tracked files. Its 327-file source archive adds only generated
`PKG-INFO`; every tracked blob is present and byte-identical. The archive
SHA-256 is
`47211c9a22d05e673265daaa99a813ac74ac1607116d3b5c9331d9accaf1e04c`.
The 81-member Windows cp312-abi3 wheel derived only from that source archive
has SHA-256
`b3cd1f1046297339c7fc88c0f89c66deb4e6a4cc78cc96bce9ce99565c06fb2a`.
It contains one native extension, all 15 attribution members, no packaged
build/include/lib/share/bin tree, and NumPy as its only unconditional
dependency. The three changed runtime files match across Git, source archive,
and wheel; the native module depends only on Python and standard Windows
runtimes. A fresh external NumPy-only environment passes the complete wheel
smoke, including all six splat read/inspect/partial/lifetime/path-release
probes.

As with the prior inspector checkpoint, the final package confirmation is a
no-further-edit rebuild after this evidence is staged. Its hashes remain
outside the source tree so recording them cannot invalidate the tree they
describe.

The first hosted all-six parity lane exposed one existing platform-specific
fingerprint outside the benchmark corpus: on the characterized hosted macOS
AppleClang/ARM profile, the larger compressed-PLY PlayCanvas vector has body
SHA-256
`412aed8223afa9dd6e38cd3e36052ac8520ecb9381517567d292ba1cf8457c5f`
while hosted Windows/MSVC and Ubuntu/glibc retain PlayCanvas-exact
`e32c9d9340ff7489177d93403078faa695e2a67ad19f763a4755ff24bdf3eff5`.
Native exp/log rounding is the inferred cause consistent with the one changed
lossy quantization boundary, not a universal platform claim. Both outputs
pass the independent layout/decode oracle. The exact hosted-profile
fingerprints are now explicit; codec and benchmark behavior are unchanged.

Registry implementation `3e46d82` and test-contract repair `9928c6d` are
pushed. The repair's exact tree
`79819558208fdb8099b23d3c38fd1afee3ee2f7c` contains 326 tracked files,
a byte-consistent 327-file source archive, and an 81-member Windows abi3
wheel. The source archive SHA-256 is
`33e0bb7f0a85a630f8fbe45117c4e645979848bf11d5edc6bbfa963c7f067134`;
the derived wheel SHA-256 is
`1796fffd3a207fa9033f05500986fee36be152884cec2230ca9a68889bb4a112`.
The external NumPy-only installed smoke passes. Normal run `30228235491`
passes the all-50 benchmark structure and retained five-run guard plus every
platform lane; compiler-instrumented run `30228235535` passes both jobs. R2
is closed.

## R3.1a benchmark-boundary equivalence (2026-07-26)

R3.1a is a development-harness organization change, not a codec optimization.
The compatible `bench/bench_io.py` entry point now delegates shared models,
timing/traced allocation and warmed-parent RSS measurement, and console
formatting to `bench/io_bench/{model,measure,reporting}.py`. The JSON envelope,
row ordering, nested shapes, fixture builders, codec operations, and guard
logic remain unchanged. The existing `*_rss_mb` values are explicitly named
`in_process_rss` internally and remain exploratory warmed-parent deltas; they
are not fresh-process qualification evidence.

The frozen parent is commit
`683ae483a3a2407dc192fb32cdcf964eb3b1fe9a`, tree
`5dfe9bbd36940bfa4b03a322a2b452b38d3f463e`, benchmark blob
`bcb502936cc8ccce4a52b843a1220f27cdddba1f`. All three captures used:

```text
.venv/Scripts/python.exe bench/bench_io.py --runs 1 --scale 0.001 --skip-oracles --json <output>
```

The parent JSON SHA-256 is
`d30840742c571dd4a8ad86076ef0af8dd1fc884ecf59e1af2f3330adffaffd57`.
The two candidate JSON SHA-256 values are
`c0ec1a358ae5e7e51d650d3b1fd1069f76c97bf9f8573d917cd2e74ef976521e`
and
`5ae19649975f4ced69d9f0817a15c000c7a82e4c93cb5d3f873763273e43c7b8`.
Timing and sampled-memory values naturally differ, but all three reproduce the
50-row structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
and identical deterministic values. The parent/candidate combined AST hash for
the eight representative fixture builders is
`ce8dda677da61550035dcd2062d4cb53aed20f21e37024d87d5f50449ba1fbfd`.
Record-aware fingerprints additionally cover image color/channel metadata,
Y4M timing/chroma conventions, point-cloud conventions, mesh topology and
scene graph, Gaussian parameter spaces, camera conventions, tensor metadata,
and reconstruction structure. A checked synthetic transcript pins every
reporting variant.

The first unchanged complete five-run command rejected only the LAS
`points-read` comparator during a noisy sample. A seven-run isolated
diagnostic then measured 1.41x, and a complete no-oracle repeat passed. Per the
benchmark repeat policy, the unchanged complete command was run again:

```text
.venv/Scripts/python.exe bench/bench_io.py --runs 5 --require-o4-gains --require-o5-inspect-gains --require-o5-partial-gains
```

The confirming run passes all retained O4/O5 and mmap/sink allocation guards.
Its LAS read pair is 2,178 versus 2,882 MB/s (1.32x); LAS write is 487 versus
1,015 MB/s (2.08x), XYZ write retains 6.33x, and both WebP comparisons retain
directional gains. The confirming JSON SHA-256 is
`b426086aaf02483d4a36bb4e4297fba4c7ac85b8786d849cd4de3ff07726dc3b`.
These values confirm behavior preservation under the retained controls; they
do not replace the codec-performance baseline or make a new optimization
claim. The final local MSVC gate collects 3,309 nodes, passes 3,305 with the
same four documented skips, and passes Ruff. Exact-commit normal run
[30231629465](https://github.com/SceneAPI/SceneIO/actions/runs/30231629465)
passes the complete suite, 50-codec smoke, retained performance guard, all
platform lanes, and GCC-10 job. Exact-commit compiler-instrumented run
[30231629496](https://github.com/SceneAPI/SceneIO/actions/runs/30231629496)
passes both jobs.

## R3.1b fresh-child memory protocol (2026-07-26)

R3.1b separates qualification evidence from the legacy warmed-parent
`*_rss_mb` table fields. `bench/io_bench/memory_protocol.py` launches one new
interpreter per sample. The child imports SceneIO, executes one explicit
warm-up, collects garbage, records current and platform-high-water baselines,
retains calibration pages until current RSS reaches the prior high-water mark,
starts a 0.5 ms `psutil` sampler, confirms its first reading, and executes
exactly one measured operation. Warm-up receives a fixed zero payload size.
The version-1 response reports payload bytes, baseline/peak/delta RSS,
calibration and residual headroom, platform, sampler backend and availability,
canonical warm/measured operation signatures, and operation counts. Strict
mode requires three or more samples per size, an available sampler, and zero
residual headroom; non-strict probes return `unavailable` with all RSS fields
null rather than numeric zero. Response identity and sampling interval must
match the request. Growth assessment compares every larger payload with the
smallest, not only the endpoints. The validator accepts only Windows
`peak_wset`, Linux/macOS `ru_maxrss`, or the explicitly non-qualifying
current-only fallback, and recomputes headroom from the baseline counters.
The lifetime value is the monotonic envelope of the named native counter and
all observed current-RSS samples. This preserves a coherent high-water value
when Linux `/proc` RSS briefly exceeds `ru_maxrss`, without dropping either a
native or sampled allocation peak. The sampler is stopped before the final
envelope is captured while the measured result and calibration pages remain
alive.
Instrumented runtimes report the protocol unavailable because their resident
memory is not comparable. Throughput timing remains in the separate timing
path and is not performed under this sampler.

The generated control run uses three independent children at 8 MiB and
48 MiB:

| Control | 8 MiB median delta | 48 MiB median delta | Growth | 10 MiB bound | Result |
|---|---:|---:|---:|---:|---|
| 64 KiB bounded file read | 208,896 B | 192,512 B | 0 B | 10,485,760 B | pass |
| touched whole-payload allocation | 8,523,776 B | 50,462,720 B | 41,938,944 B | 10,485,760 B | fail as intended |

The raw six-sample-per-control JSON has SHA-256
`cf3764e50ed5aceae576989c0439341070df510b1ec456584fbf08dd6b3b761f`
and remains generated development output under `build/`, not a committed
fixture. The checked response contract is
`tests/contracts/memory_protocol_v1.json`; focused tests also run actual NPY
read and inspect operations and prove strict versus non-strict missing-sampler
behavior. A direct bounded-read result check and counterexample matrices cover
semantic-signature mismatch, insufficient repetitions, intermediate-size
spikes, request/response mismatch, and obscured high-water windows. The same
protocol test now runs in the existing three-platform mmap/partial CI lane.
R3.3, not this unit, owns the staged migration of existing codec-test-local
subprocess helpers.

The final local R3.1b tree collects 3,320 tests and passes 3,316 with the same
four documented skips. The unchanged complete five-run guard passes with JSON
SHA-256
`a8c5366a999cbe90b7f29ca7f6face5584612cb021708b99644496ceb08951bc`.
Representative retained comparisons are:

| Comparator | Baseline | Optimized | Gain |
|---|---:|---:|---:|
| XYZ write | 20.81 MB/s | 101.41 MB/s | 4.87x |
| LAS read | 1,407.76 MB/s | 3,139.14 MB/s | 2.23x |
| LAS write | 526.43 MB/s | 1,092.20 MB/s | 2.07x |
| WebP balanced configuration | 13.35 MB/s | 35.71 MB/s | 2.68x |
| WebP worker control | 18.10 MB/s | 19.64 MB/s | 1.09x |

All three independent reviews are clear. Exact-source packaging contains 336
byte-identical repository files plus generated `PKG-INFO`; the derived
81-member Windows abi3 wheel excludes development/build content and passes the
isolated NumPy-only installed smoke. The first exact hosted attempt,
`aafd283`, exposed the Linux `/proc` versus `ru_maxrss` boundary and a final
sampler-read ordering window in CI run `30234117571`; its
compiler-instrumented run `30234117580` passes. The follow-up preserves the
response validator's high-water invariant, adds deterministic
counter-mismatch and join-time peak controls, passes all 3,316 local tests,
and passes the 11-test protocol suite under the pinned manylinux2014 GCC-10
image. Follow-up commit `0bdfe0f` closes R3.1b: normal run
[30234796010](https://github.com/SceneAPI/SceneIO/actions/runs/30234796010)
and compiler-instrumented run
[30234796025](https://github.com/SceneAPI/SceneIO/actions/runs/30234796025)
both pass.

## R3.2 arrays benchmark-family extraction (2026-07-26)

The first R3.2 checkpoint moves all six array `Spec` builders and their inline
fixtures to `bench/io_bench/families/arrays.py`, with the deterministic DMB
fixture, NumPy/NPZ/DMB independent oracles, and optional safetensors bindings
under `bench/io_bench/{fixtures,oracles}/arrays.py`. The compatible
`bench/bench_io.py` facade re-exports every historical compatibility helper
and splices the family hook into the same result position, so commands and
developer imports are unchanged. The benchmark contract records each helper's
owning source and AST hash in addition to the existing representative fixture
fingerprints.

Direct controls round-trip NumPy, NPZ, and DMB. When safetensors is installed,
all five buffer/file/open bindings must be callable and execute successfully;
otherwise all five must be absent together. PFM and FLO retain explicit
exemptions for independent benchmark encode/decode throughput while their
format parity remains independently tested. A one-run 50-codec smoke retains
structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused compatibility, array-family, and parity validation passes 334 tests
with one documented optional OpenCV skip. Adding the typed PFM/FLO suites
expands that run to 445 passes with the same skip. The complete suite passes
3,316 tests with the same four documented skips, and Ruff is clean. A fresh
exact-tree source archive has 343 members and contains all six new benchmark
family/fixture/oracle modules without generated cache files. Its derived
81-member wheel contains no benchmark, test, or safetensors module, retains
all 15 attribution files, and keeps `numpy>=1.26` as its sole unconditional
dependency. This is a mechanical ownership change and makes no
codec-performance claim. Exact commit `6d9ec34` passes normal run
[30236069971](https://github.com/SceneAPI/SceneIO/actions/runs/30236069971)
and compiler-instrumented run
[30236069959](https://github.com/SceneAPI/SceneIO/actions/runs/30236069959).

## R3.2 calibration benchmark-family extraction (2026-07-27)

The second R3.2 checkpoint moves the complete `opencv_yaml`, `opencv_xml`,
`ros_camera_info`, and `kalibr` `Spec` hook to
`bench/io_bench/families/calibration.py`. Deterministic rig builders now live
in `fixtures/calibration.py`; PyYAML and standard-library XML oracles live in
`oracles/calibration.py`. The unchanged record-size helper moves once to
`families/common.py` because pose, reconstruction, and calibration specs share
it. The facade retains exact historical helper identities and inserts the
four-codec hook at the same position.

All seven moved helper ASTs match the parent exactly. Contract controls pin the
four core bindings, fixture/partial arguments, logical-size results, and
oracle identities. They execute all installed PyYAML and XML pairs through
the actual `Spec` objects; a fresh process with PyYAML blocked proves all
three YAML-backed pairs become unavailable together while XML remains active.
Lower-module imports do not load the facade. The four-codec live benchmark
produces independent write/read metrics for every row, and the complete
50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused calibration/contract validation passes 117 tests; the complete suite
passes 3,316 with the same four documented skips, and Ruff is clean. A fresh
347-member exact-tree source archive contains exactly the four new
calibration/common benchmark modules and no generated cache files. Its
81-member derived wheel contains no benchmark, test, or YAML module, retains
all 15 attribution files, and keeps `numpy>=1.26` as its sole unconditional
dependency; `pyyaml>=6.0` remains test-extra only. A fresh environment with
that wheel and NumPy, but without PyYAML, passes
`python -m sceneio._wheel_smoke`. All three independent reviews are clear.
This is a mechanical ownership change and makes no codec-performance claim.
Exact commit `5dc03f4` passes normal run
[30237676629](https://github.com/SceneAPI/SceneIO/actions/runs/30237676629)
and compiler-instrumented run
[30237676648](https://github.com/SceneAPI/SceneIO/actions/runs/30237676648).

## R3.2 raster-image benchmark-family extraction (2026-07-27)

The third R3.2 checkpoint moves the complete `png`, `jpeg`, `bmp`, `tga`,
`webp`, `hdr`, `exr`, and `netpbm` hook to
`bench/io_bench/families/images.py`. Its unchanged uint8/float32 builders live
in `fixtures/images.py`; optional Pillow, imageio, and OpenEXR comparisons live
in `oracles/images.py`. The facade preserves every historical helper identity
and splices the two image-hook slices around the unchanged interleaved `y4m`
row, retaining exact order.

All nine moved helper ASTs match the parent exactly. Contract controls pin
family-to-fixture/oracle identities, core callback settings, image dtype,
shape, and logical size, plus the complete optional-library matrix and
Netpbm's imageio-to-Pillow fallback. Every available non-HDR oracle writer and
reader executes as the actual `Spec` pair; EXR packed and planar channel
layouts are normalized to RGB and compared exactly for both oracle- and
core-produced files. The installed imageio/Pillow environment cannot
portably encode or decode Radiance HDR float32 RGB, so independent benchmark
throughput for that pair is an explicit reviewed exemption; codec parity
continues to use the independent NumPy RGBE parser and serializer in
`tests/codecs/test_hdr.py`.

Seven of eight live rows produce independent write/read metrics; only the
declared HDR comparison is null. The complete 50-codec smoke retains
structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused raster/contract validation passes 352 tests; the complete suite passes
3,316 with the same four documented skips, and Ruff is clean. A fresh
350-member exact-tree source archive contains exactly the three new image
benchmark modules and no generated cache files. Its 81-member derived wheel
contains no benchmark, test, Pillow, imageio, or OpenEXR module, retains all
15 attribution files, and keeps `numpy>=1.26` as its sole unconditional
dependency; those three comparison libraries remain test-extra only. A fresh
environment with that wheel and NumPy, but without any of them, passes
`python -m sceneio._wheel_smoke`. All three independent reviews are clear.
This is a mechanical ownership change and makes no codec-performance claim.
Exact commit `6572a76` passes normal run
[30239455960](https://github.com/SceneAPI/SceneIO/actions/runs/30239455960)
and compiler-instrumented run
[30239455952](https://github.com/SceneAPI/SceneIO/actions/runs/30239455952).

## R3.2 mesh benchmark-family extraction (2026-07-27)

The fourth R3.2 checkpoint moves the five buffer-backed `ply_mesh`, `obj`,
`stl`, `off`, and `glb` specs to `bench/io_bench/families/meshes.py`. The five
unchanged mesh/scene builders now live in `fixtures/meshes.py`; all 12 optional
trimesh comparison helpers, including the multi-file glTF pair, live in
`oracles/meshes.py`. The specialized `gltf` benchmark row remains in
`bench_io.py::_benchmark_gltf` until the final R3.2 runner extraction, but
consumes the same lower-owned fixture/oracle helpers through exact facade
aliases.

All 17 moved helper ASTs and all five standard `Spec` ASTs match the raster
checkpoint exactly. Contract controls pin lower/facade identities, core
callbacks, payload-size accounting, installed and absent trimesh states, and
the unchanged interleaved mesh result positions. Real trimesh writer-to-reader
and core-to-trimesh paths execute for all five standard rows and specialized
glTF. Their transformed scene geometry is canonicalized by triangle and
compared to the fixture's positions and connectivity, so equal face counts
alone cannot pass. The complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.

All six live mesh rows produce independent write/read metrics. Focused
mesh/contract validation passes 336 tests; the complete suite passes 3,316
with the same four documented skips, and Ruff is clean. A fresh 353-member
exact-tree source archive contains exactly the three new mesh benchmark
modules and no generated cache files. Its 81-member derived wheel contains no
benchmark, test, trimesh, or pygltflib module, retains all 15 attribution
files, and keeps `numpy>=1.26` as its sole unconditional dependency; trimesh
and pygltflib remain test-extra only. A fresh environment with that wheel and
NumPy, but without either comparison library, passes
`python -m sceneio._wheel_smoke`. This is a mechanical ownership change and
makes no codec-performance claim.

Exact mesh commit `613fd26` passes normal run
[30241711640](https://github.com/SceneAPI/SceneIO/actions/runs/30241711640)
and compiler-instrumented run
[30241711620](https://github.com/SceneAPI/SceneIO/actions/runs/30241711620).

## R3.2 point benchmark-family extraction (2026-07-27)

The fifth R3.2 checkpoint moves the non-contiguous `xyz`, `pts`, point `ply`,
`pcd`, `las`, and `laz` specs to
`bench/io_bench/families/points.py`. Their three deterministic fixtures now
live in `fixtures/points.py`; nine comparison helpers—the portable PTS pair
and optional Open3D/LASpy pairs—live in `oracles/points.py`. The compatible
facade re-exports the same helpers and optional bindings, then slices the
point hook around the already extracted five-row mesh block so all 50 result
positions remain unchanged.

The 11 unaffected moved helper ASTs and five unaffected standard `Spec` ASTs
match the mesh checkpoint. Review found that the historical LAS comparison
encoded XYZ-only point format 0 through LASpy while SceneIO encoded point
format 2 with RGB and intensity. The repaired LAS/LAZ specs use one
point-format-2 payload on both sides and retain the same positions-equivalent
throughput denominator. Contract controls pin lower/facade identities, core
callbacks, scale arguments, logical payload sizes, installed and independently
absent Open3D/LASpy states, and real writer-to-reader plus core-to-reader
comparisons. PTS arrays compare exactly; PLY/PCD positions, normals, and colors
compare within `1e-6`; LAS/LAZ compare positions within half the declared
`0.001` scale and keep RGB/intensity exact. Five of six live rows produce
independent write/read metrics. XYZ records the exact unverified property,
independent benchmark encode/decode throughput, while its NumPy text parser
and serializer continue to provide independent parity in
`tests/codecs/test_xyz.py`.

The complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused point/contract validation passes 449 tests; the complete suite passes
3,316 with the same four documented skips, and Ruff is clean. A fresh
356-member exact-tree source archive contains exactly the three new point
benchmark modules and no generated cache files. Its 81-member derived wheel
contains no benchmark, test, Open3D, LASpy, or LAZ-backend module, retains all
15 attribution files, and keeps `numpy>=1.26` as its sole unconditional
dependency; comparison packages remain test-extra only. A fresh environment
with that wheel and NumPy, but without those packages, passes
`python -m sceneio._wheel_smoke`. This combines an ownership move with a
benchmark-fixture correction and makes no codec-implementation performance
claim.

Exact point commit `45e2757` passes normal run
[30244892746](https://github.com/SceneAPI/SceneIO/actions/runs/30244892746)
and compiler-instrumented run
[30244892600](https://github.com/SceneAPI/SceneIO/actions/runs/30244892600).

## R3.2 reconstruction benchmark-family extraction (2026-07-27)

The sixth R3.2 checkpoint moves the nine buffer-backed `transforms_json`,
`tum`, `kitti`, `euroc_state`, `g2o`, `bundler`, `bal`, `nvm`, and `openmvg`
specs to `bench/io_bench/families/reconstruction.py`. Their deterministic
pose, state, graph, and reconstruction fixtures now live in
`fixtures/reconstruction.py`; the portable EuRoC, g2o, and BAL comparisons
live in `oracles/reconstruction.py`. The facade slices the hook around the
four calibration rows, preserving the 50-row order. Specialized
`colmap_sparse`, `colmap_sparse_txt`, and `colmap_db` orchestration remains
facade-owned until the shared runner moves.

All nine `Spec` ASTs and 12 of the 13 moved helper ASTs match the point
checkpoint. Review strengthened `_g2o_oracle_read`, the sole intentional
helper difference, from a count-only result to complete node, edge, fixed-id,
quaternion, translation, and symmetric information-matrix materialization.
The regenerated live capture therefore times a full semantic decode. EuRoC,
g2o, and BAL produce independent write/read metrics. The other six rows carry
the exact exemption, independent benchmark encode/decode throughput, backed
by their independent codec parity suites.

The complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused reconstruction/contract validation passes 505 tests with one existing
optional PyCOLMAP skip; the complete suite passes 3,316 with the same four
documented skips, and Ruff is clean. The exact-tree source archive has 359
members and exactly the three new reconstruction benchmark modules. Its
81-member wheel excludes benchmark, test, and PyCOLMAP modules, retains all 15
attribution files, and keeps NumPy as its sole unconditional dependency;
PyCOLMAP remains test-extra only. A fresh NumPy-only environment without
PyCOLMAP passes the installed-wheel smoke. All three independent reviews are
clear. This checkpoint changes benchmark ownership and strengthens one
comparison workload; it makes no codec-implementation performance claim.

Exact reconstruction commit `76ed21b` passes normal run
[30247662591](https://github.com/SceneAPI/SceneIO/actions/runs/30247662591)
and compiler-instrumented run
[30247662622](https://github.com/SceneAPI/SceneIO/actions/runs/30247662622).

## R3.2 sequence benchmark-family extraction (2026-07-27)

The seventh R3.2 checkpoint moves the buffer-backed `y4m` spec to
`bench/io_bench/families/sequences.py`, its deterministic planar-YUV fixture
and the image-directory fixture to `fixtures/sequences.py`, and the portable
Y4M parser/writer to `oracles/sequences.py`. The facade preserves the Y4M
position between WebP and HDR. The `image_sequence` `DirectorySpec` remains
facade-owned until the shared runner moves, but consumes the lower fixture
through an exact compatibility alias.

The Y4M `Spec` AST, directory orchestration AST, and three of four moved helper
ASTs match the reconstruction checkpoint. Review strengthened
`_y4m_oracle_read`, the sole intentional helper difference, so the timed
comparison validates and returns all Y/U/V planes plus dimensions, frame rate,
pixel aspect, chroma configuration, range, matrix, and interlace. The live Y4M
row has portable independent write/read metrics. `image_sequence` records the
exact exemption, independent benchmark directory encode/decode throughput;
manifest and PGM payload parity remain independently covered in
`tests/codecs/test_image_sequence.py`. Its SceneIO directory round trip pins
dimensions, channels, frame dtype, resolved paths, timing, and byte-identical
copied frames.

The complete 50-codec smoke retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused sequence/contract validation passes 225 tests, the complete suite
passes 3,316 with four documented skips, and Ruff is clean. The exact-tree
source archive has 362 members and exactly the three new sequence benchmark
modules. Its 81-member wheel excludes benchmark and test modules, retains all
15 attribution files, and keeps NumPy as its sole unconditional dependency. A
fresh NumPy-only environment passes the installed-wheel smoke. All three
independent reviews are clear. This checkpoint changes benchmark ownership
and strengthens one comparison workload; it makes no codec-implementation
performance claim.

Exact sequence commit `4b8c829` passes normal run
[30250394890](https://github.com/SceneAPI/SceneIO/actions/runs/30250394890)
and compiler-instrumented run
[30250394906](https://github.com/SceneAPI/SceneIO/actions/runs/30250394906).

## R3.2 splat benchmark-family extraction (2026-07-27)

The eighth R3.2 family checkpoint moves all six ordinary splat specifications
to `bench/io_bench/families/splats.py`, the deterministic Gaussian fixture to
`fixtures/splats.py`, and the optional `gsply` PLY/SPZ adapters to
`oracles/splats.py`. Canonical order remains `gaussian_ply`,
`compressed_ply`, `sog`, `ksplat`, `spz`, and `splat` between the point and
array families.

All six `Spec` ASTs and all five moved helper ASTs are unchanged from the
sequence checkpoint. Gaussian PLY and SPZ retain live independent `gsply`
encode/decode measurements. The contract records the exact missing
independent benchmark encode/decode throughput for Compressed PLY, SOG,
KSplat, and `.splat`; their independent format parity remains covered by the
corresponding codec suites. Installed-`gsply` tests compare every Gaussian
field in both producer directions, with SPZ compared after its specified
quantization. A fresh process without `gsply` retains all six SceneIO rows and
removes only the two optional comparison pairs.

The six live rows execute successfully, and the complete 50-codec smoke
retains structural projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Focused splat/contract validation passes 176 tests with one documented SPZ-v2
writer skip; the complete suite passes 3,316 with four documented skips, and
Ruff is clean. The exact-tree source archive has 365 members and exactly the
three new splat benchmark modules. Its sdist-derived 81-member Windows wheel
contains no benchmark, test, or `gsply` payload, retains all 15 attribution
files, and keeps NumPy as its sole unconditional dependency. A fresh
NumPy-only environment passes the installed-wheel smoke. All three independent
reviews are clear. This checkpoint changes benchmark ownership only; it makes
no codec-implementation performance claim.

Exact splat commit `cd32268` passes normal run
[30253301819](https://github.com/SceneAPI/SceneIO/actions/runs/30253301819)
and compiler-instrumented run
[30253301871](https://github.com/SceneAPI/SceneIO/actions/runs/30253301871).

## R3.2 benchmark-runner extraction (2026-07-27)

The ninth R3.2 ownership checkpoint moves the complete sweep, specialized
glTF/COLMAP/image-directory orchestration, CLI parser, and all supporting
helpers to `bench/io_bench/runner.py`. `bench/bench_io.py` is now a small
compatible entry point that re-exports the runner's complete historical
non-dunder helper surface and delegates direct execution.

All 20 moved function ASTs match the splat checkpoint. The exact 166-name
attribute surface has the same checked SHA-256, and importing the lower runner
does not import the facade. A first facade import preserves existing runner
callable identities and rebindings; explicit facade reload restores the runner
source definitions. Facade attribute rebinding propagates to runner globals as
it did when functions shared the facade namespace, while star imports retain
the exact parent 67-name public surface. Direct facade
execution retains the same program name, options, defaults, rejection
behavior, row schemas, output order, and bare-list JSON envelope. The complete
50-codec smoke retains structural
projection
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
This is an ownership-only move and makes no codec-implementation performance
claim. Repository-built-in completeness and strict comparison-provider
qualification remain the final R3.2 behavior checkpoint.

Focused runner/contract validation passes 145 tests; the complete suite
passes 3,316 with four documented skips, and Ruff is clean. The exact staged
tree has 365 tracked files and produces a 366-member source archive whose only
generated member is `PKG-INFO`. Its sdist-derived 81-member Windows wheel
excludes benchmark and test modules, retains all 15 attribution files, and
keeps NumPy as its sole unconditional dependency. A fresh NumPy-only
installation passes `sceneio._wheel_smoke`.

Exact runner commit `cf8d117` passes normal run
[30257105454](https://github.com/SceneAPI/SceneIO/actions/runs/30257105454)
and compiler-instrumented run
[30257105468](https://github.com/SceneAPI/SceneIO/actions/runs/30257105468).

## R3.2 repository-complete comparison qualification (2026-07-27)

The final R3.2 behavior checkpoint adds an immutable 50-entry comparison
ledger in `bench/io_bench/qualification.py`. The ledger is keyed by
`CANONICAL_BUILTIN_IDS`, not the mutable runtime registry: 33 formats require
timed independent encode/decode comparisons (with COLMAP DB also covering
inspect and partial operations), while 17 record a reviewed exemption with
the exact untimed property and parity-suite path.

Every complete sweep validates the canonical 50-id set before selector
filtering or measurement. A runtime-added codec remains usable through the
public registry but cannot enter repository fixture/comparison completeness.
`--strict-oracles` is a complete-sweep qualification mode and therefore
rejects `--only`, `--skip-oracles`, and the safetensors-only large-fixture
mode. It preflights binding availability for every timed callback, propagates
provider execution failures, and audits every declared metric after the
complete sweep; the optional `_try(...)` path remains available only to
ordinary developer runs.

The local one-run strict sweep produces 50 successful rows: all 33 timed
entries have both comparison metrics and all 17 reviewed exemptions remain
untimed by declaration. The separate skip-comparison smoke retains structural
SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
The CI performance guard now uses strict qualification without changing the
existing O4/O5 acceptance rules. The complete five-run strict guard passes;
the exact local tree collects 3,339 tests and passes 3,335 with four documented
skips, and Ruff is clean. All three independent closure reviews are clear. The
exact staged tree has 367 tracked files and produces a 368-file sdist whose
only generated file is `PKG-INFO`; its sdist-derived 81-member Windows abi3
wheel contains one native module and all 15 attribution files, excludes
benchmark/test/build payloads, and installs only SceneIO plus NumPy in a fresh
environment. `sceneio._wheel_smoke` returns `2`.

Exact qualification commit `0e54cf5` passes normal run
[30263506366](https://github.com/SceneAPI/SceneIO/actions/runs/30263506366)
and compiler-instrumented run
[30263506270](https://github.com/SceneAPI/SceneIO/actions/runs/30263506270).

## R3.3 non-consuming cross-codec case catalog (2026-07-27)

The first R3.3 checkpoint adds a test-only, immutable case catalog in
`tests/_support/codec_cases.py` without changing any benchmark or codec
consumer. Its canonical-order definitions cover all 50 repository built-ins:
44 use the existing buffer-fixture path, three use path-native fixtures, and
three use directory fixtures. The catalog separately pins the exact 28
partial-capable codecs and their 32 selector declarations.

The independent one-run all-codec benchmark smoke still returns 50 successful
rows and retains structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
Six focused architecture controls pin completeness, ordered partitions,
family ownership, live capability agreement, runtime-extension isolation,
and the non-consuming boundary. The complete local suite collects 3,345 tests
and passes 3,341 with four documented skips; Ruff is clean. All three
independent reviews are clear. This checkpoint establishes reusable test
ownership only and makes no codec-implementation performance claim. The exact
staged tree has 370 tracked files and produces a 371-file sdist whose only
generated file is `PKG-INFO`; its sdist-derived 81-member Windows abi3 wheel
contains one native module and all 15 attribution files, excludes benchmark
and test payloads, and installs only SceneIO plus NumPy in a fresh
environment. `sceneio._wheel_smoke` returns `2`.

Exact catalog commit `81f143b` passes normal run
[30266501529](https://github.com/SceneAPI/SceneIO/actions/runs/30266501529)
and compiler-instrumented run
[30266501618](https://github.com/SceneAPI/SceneIO/actions/runs/30266501618).

## R3.3 mmap consumer migration (2026-07-27)

The mmap behavior suite now consumes the reusable deterministic 44-case
builder in `tests/_support/buffer_codec_cases.py`. The original local builder
remains as an independent migration comparator: the focused control proves
the exact traversal order, reader/writer identity, every encoded byte string,
and every full record fingerprint before the mutation-sensitive mmap tests
run. No codec implementation or benchmark path changes.

The mmap suite passes 114 tests. The complete local suite collects 3,346 tests
and passes 3,342 with four documented skips; Ruff is clean. All three
independent reviews are clear. The independent one-run all-codec benchmark
smoke returns 50 successful rows and retains structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
This is a test-ownership migration and makes no codec-implementation
performance claim. The exact staged tree has 371 tracked files and produces a
372-file sdist whose only generated file is `PKG-INFO`; its sdist-derived
81-member Windows abi3 wheel contains one native module and all 15 attribution
files, excludes benchmark and test payloads, and installs only SceneIO plus
NumPy in a fresh environment. `sceneio._wheel_smoke` returns `2`.

Exact mmap migration commit `9a73892` passes normal run
[30268797350](https://github.com/SceneAPI/SceneIO/actions/runs/30268797350)
and compiler-instrumented run
[30268797374](https://github.com/SceneAPI/SceneIO/actions/runs/30268797374).

## R3.3 mmap legacy-matrix removal (2026-07-27)

After exact local equivalence and both hosted workflows passed, the duplicated
`_legacy_buffer_codecs` matrix and its temporary comparison node were removed.
The lower-owned builder remains the only source for these 44 deterministic
cases. Its architecture contract pins the exact original traversal order,
live reader/writer identities, and 43-codec portable encoded-fixture projection
SHA-256
`b21a55c6cbde2a46d89bf2bc013b6e81ffe3d58565922dcd690c2605f31143ab`.
Compressed PLY is excluded from that universal byte hash because native
exp/log quantization has an established AppleClang profile; its shared
semantic Gaussian input and platform-profiled parity test remain checked. The
existing mmap suite continues to validate semantic records, lifetimes, buffer
protocol behavior, truncation, and deterministic mutations.

The candidate collection returns exactly to 3,345 nodes with sorted normalized
SHA-256
`fc4934cb3fcf4a1a37fb5a087dcf0b13821df1f926f12412931b8ce040b93a05`;
no original node id, parameter id, or skip reason changes. The complete local
suite passes 3,341 tests with four documented skips, and Ruff is clean. The
one-run all-codec benchmark smoke returns 50 successful rows and retains
structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
This cleanup changes test ownership only and makes no codec-implementation
performance claim.

Exact mmap legacy-matrix removal commit `fc86f44` passes normal run
[30271311308](https://github.com/SceneAPI/SceneIO/actions/runs/30271311308)
and compiler-instrumented run
[30271309916](https://github.com/SceneAPI/SceneIO/actions/runs/30271309916).

## R3.3 streaming consumer migration (2026-07-27)

The 14 O3 file-sink behavior functions now live in the focused
`tests/test_io_streaming.py` module and continue to consume the reusable
44-case builder in `tests/_support/buffer_codec_cases.py`. Their 16 collected
nodes retain the exact test names and three `npy`/`pfm`/`flo` parameter ids;
the assembly contract records every old `test_io_mmap.py` node and its exact
new path. An AST comparison against `fc86f44` proves the moved function bodies
are unchanged apart from renaming the shared allocation helper. That helper
now lives in `tests/_support/memory_measurement.py` and is reused by the mmap
allocation control instead of being duplicated.

The focused streaming, mmap, and assembly suites pass 124 tests. The complete
local suite still collects 3,345 nodes and passes 3,341 with four documented
skips; sorted normalized collection SHA-256 is
`1131f211bb324c4d6800350b71364eb1f95efd13acef5a6dc4e984d708a88d53`,
and Ruff is clean. The independent one-run all-codec benchmark returns 50
successful rows and retains structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
This checkpoint changes test ownership only and makes no codec-implementation
performance claim. Its exact staged tree has 373 files and produces a
374-file sdist whose only generated member is `PKG-INFO`; the sdist-derived
81-member Windows abi3 wheel contains one native module and all 15
attribution files, with no test, benchmark, build, include, library, or
shared-data payload. A fresh environment installs only SceneIO and NumPy, and
`sceneio._wheel_smoke` returns `2`. The focused mmap platform job runs the
new streaming module explicitly on Windows, Linux, and macOS.

Exact streaming migration commit `914702d` passes normal run
[30274413815](https://github.com/SceneAPI/SceneIO/actions/runs/30274413815)
and compiler-instrumented run
[30274413693](https://github.com/SceneAPI/SceneIO/actions/runs/30274413693).

## R3.3 inspection consumer migration (2026-07-27)

Inspection behavior now has focused ownership in
`tests/test_io_inspection.py`. The 47 tests and three local helpers are
AST-identical to their `914702d` definitions and produce the same 76 test
names and parameter ids. Both mmap and inspection continue to consume the
same 44 deterministic buffer cases without importing one another. The
collection contract now represents path-only moves as reusable rename groups:
the prior 16 streaming nodes and these 76 inspection nodes expand to exact
old/new paths independently of feature additions and removals.

The focused mmap, inspection, assembly, and catalog suites pass 114 tests.
The complete collection remains 3,345 nodes with sorted normalized SHA-256
`f90c2f368fa8d5f976291cc8af3c7038c740893ac1abc78ec9b1bcf4ca5af959`.
The Windows, Linux, and macOS mmap-platform commands each include the focused
inspection module explicitly. The independent one-run all-codec benchmark
retains 50 successful rows and structural SHA-256
`2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
This checkpoint changes test ownership only and makes no codec-implementation
performance claim. Its exact package verification records 374 staged files,
a 375-file sdist whose only generated member is `PKG-INFO`, and the unchanged
81-member wheel with one native module and 15 attribution files. The wheel
installs with only SceneIO and NumPy and passes `sceneio._wheel_smoke`.

Exact inspection migration commit `0e21e27` passes normal run
[30278777267](https://github.com/SceneAPI/SceneIO/actions/runs/30278777267)
and compiler-instrumented run
[30278777173](https://github.com/SceneAPI/SceneIO/actions/runs/30278777173).

## R3.3 array partial-consumer migration (2026-07-27)

The DMB window test and both FLO mapped-window lifetime/error-release tests
move unchanged into `tests/test_io_partial_arrays.py`. Their three destination
function ASTs match `0e21e27` exactly with projection SHA-256
`a1733b7513c8633d4eff9c228d68ff2beadee5b9191083086671fc7925544051`.
The assembly contract pins all three path-only node renames. Broad
cross-family window, endian, validation, truncation, and memory relationships
remain in `tests/test_io_partial.py`. Both platform commands run the shared
and array-focused modules explicitly. The complete collection remains 3,345
with normalized SHA-256
`ae4ab66a375c9c130ddf10682eb37e2ba21a0433ba2fb454ecce4358ef616414`.
This unit changes test ownership only and makes no codec performance claim.
Its exact package verification records 375 source files, a 376-file sdist
whose only generated member is `PKG-INFO`, and an 81-member Windows abi3
wheel with one native module and all 15 license/inventory files. The wheel
installs with only SceneIO and NumPy and returns `2` from
`sceneio._wheel_smoke`.

Exact array partial migration commit `5009ea0` passes normal run
[30282057346](https://github.com/SceneAPI/SceneIO/actions/runs/30282057346)
and compiler-instrumented run
[30282056576](https://github.com/SceneAPI/SceneIO/actions/runs/30282056576).

## R3.3 image partial-consumer migration (2026-07-27)

Three unchanged Netpbm/WebP test functions now live in
`tests/test_io_partial_images.py` and produce the same 10 parameterized nodes.
Their function projection SHA-256 is
`c501630b2918a9faae74f88672a5c9bbdf7206fc5452d202592f1a57afbf90ad`.
The unchanged `_pixels` and `_assert_image_window` helpers move once into
`tests/_support/partial_read.py`, with projection SHA-256
`5299b065b8e4a6dbc78ea41bff275a26be1eeeaba2a4e200634f8cc9ce0415b1`.
The shared cross-family window differential imports those lower assertions;
test modules do not import one another. Exact node and helper moves plus both
platform commands are contract-pinned. The complete collection remains 3,345
with normalized SHA-256
`c9db2c71c11f6af8d4fcd5a08a5bf75a2428ea915805e3671c5cadb2ef581cc4`.
This unit changes test ownership only and makes no codec performance claim.
Exact package verification records 377 source files, a 378-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.

Exact image partial migration commit `d198560` passes normal run
[30285128366](https://github.com/SceneAPI/SceneIO/actions/runs/30285128366)
and compiler-instrumented run
[30285128448](https://github.com/SceneAPI/SceneIO/actions/runs/30285128448).

## R3.3 mesh partial-consumer migration (2026-07-27)

The unchanged mesh face-range semantic and mapping-close test now lives in
`tests/test_io_partial_meshes.py`. Its single exact path-only rename and
destination function AST projection SHA-256
`68eb089e1f7c5fe457354b435c1d3dcd8160f45c18360ee002a48c4cb9396ae9`
are contract-pinned. Both platform commands name the focused module. The
complete collection remains 3,345 with normalized SHA-256
`c658cb0d7353ad5c6cf4f6e38b01a02418f693b121e6d8f4bba887945821cc9d`.
This unit changes test ownership only and makes no codec performance claim.
Exact package verification records 378 source files, a 379-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.

Exact mesh partial migration commit `4294dbe` passes normal run
[30287854716](https://github.com/SceneAPI/SceneIO/actions/runs/30287854716)
and compiler-instrumented run
[30287854692](https://github.com/SceneAPI/SceneIO/actions/runs/30287854692).

## R3.3 point partial-consumer migration (2026-07-27)

Three unchanged XYZ/LAS functions now live in
`tests/test_io_partial_points.py` and produce the same 13 parameterized nodes.
The unchanged `_assert_point_range` helper moves once into
`tests/_support/partial_read.py`, where the shared point/splat differential
continues to consume it. Function projection SHA-256 is
`4cfa5aea51601322a2d7d83cad7cfd1f00eb3eb3395c7fda351347352b5c12d3`;
helper projection SHA-256 is
`f0c527f421207171019327332821e81c1a47561b5b935fa65a1e4a3dea52c24c`.
Exact node/helper moves and both platform commands are contract-pinned. The
complete collection remains 3,345 with normalized SHA-256
`2451c9bb2606ac1587011eafeb2345fc9f34f7e08df7ea17b239b5a1e78a624f`.
This unit changes test ownership only and makes no codec performance claim.
Exact package verification records 379 source files, a 380-file sdist whose
only generated member is `PKG-INFO`, and the unchanged 81-member Windows abi3
wheel. It contains one native module and all 15 attribution members, excludes
repository test/benchmark/build payloads, and passes `sceneio._wheel_smoke` in
a fresh SceneIO-plus-NumPy environment.

Exact point partial migration commit `ac1a4d1` passes normal run
[30290617469](https://github.com/SceneAPI/SceneIO/actions/runs/30290617469)
and compiler-instrumented run
[30290617607](https://github.com/SceneAPI/SceneIO/actions/runs/30290617607).

## R3.3 reconstruction partial-consumer migration (2026-07-27)

Twelve unchanged COLMAP functions now live in
`tests/test_io_partial_reconstruction.py` and produce the same 15 nodes. Nine
private reconstruction helpers move with them. The unchanged
`_fresh_process_partial_rss` helper moves once into
`tests/_support/partial_read.py`, where the retained cross-family large-read
test and reconstruction suite both consume it. Test projection SHA-256 is
`49ef051e49cd4beb6b9c26f7cfe314d67cd3bd59fa91c78ffb16971903b2acdb`;
private-helper projection SHA-256 is
`a45d371755429aa070f514854d35bd83ca6afe032fad3d6a242835fdf5aa4e92`;
the lower helper projection is
`b22d3960f81b894d7b666067cb584e530858349a6ca53fefb6c58705e6892a13`.
Exact node/helper moves and both platform commands are contract-pinned. The
complete collection remains 3,345 with normalized SHA-256
`217c227e566a6767fc59b031b1217202ced5ba0dc6a14b3b7fa2d27c0f9314f4`.
This unit changes test ownership only and makes no codec performance claim.
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

## R3.3 sequence/splat ownership disposition (2026-07-27)

The remaining audit makes no benchmark or codec change. Eight sequence
partial-behavior functions already live in the sequence architecture/Y4M/
directory-sequence suites, and three splat range/selector functions already
live in the splat-family architecture suite. The seven tests retained in
`tests/test_io_partial.py` deliberately span multiple families. Their AST
projection SHA-256 is
`171b853303af63ada53183f4ca76d9bdc0c54e55b9218f56ab70207e88535bf0`;
the sequence anchor projections are
`19600f254659e7cb0c7049f22f254ef1d9b7dfcd68fbbddf7c80810ccb8d81ef`,
`399158a382461bfb55da3339625cd6477ec9c194c9f5318b67fb17b792116dbd`,
and `5364d79d5b96dcc28497dfbc756ec40889f64f13b68d9387add4f4ee3e27a2d0`;
the splat anchor projection is
`a504deeef1ea23d2e53d0398fbc010464c5e692faf23eb37f0cea9acb3a485f7`.
The assembly contract verifies those projections, all 21 exact
family-owned collected node/parameter ids, and the AST-derived format-id map
for each shared function without adding or renaming a pytest node.

The complete five-run strict O4/O5 guard passes unchanged. The closure
candidate collects 3,345 tests and passes 3,341 with four documented skips;
Ruff is clean. Exact staged packaging records 380 source files, a 381-file
sdist whose only generated member is `PKG-INFO`, and an 81-member Windows ABI3
wheel with one native module and all 15 attribution files. The wheel excludes
repository test/benchmark/build payloads, keeps NumPy as its sole
unconditional dependency, and passes a fresh SceneIO-plus-NumPy installed
smoke.

Exact R3.3 closure commit `811cb0d` passes normal run
[30300122309](https://github.com/SceneAPI/SceneIO/actions/runs/30300122309)
and compiler-instrumented run
[30300122324](https://github.com/SceneAPI/SceneIO/actions/runs/30300122324).

## R3.4 complete installed-wheel smoke qualification (2026-07-27)

The package smoke no longer relies on a manually called representative helper
list. An immutable format-to-runner map must equal the exact
`BUILTIN_DEFINITIONS` ids and order, and the runner rejects disagreement with
the installed registry or public codec listing. Successful public operations
are observed per format; expected write/read/inspect, stream, and partial
properties are derived from each live capability record.

The candidate covers all 50 built-ins, pairs each declared streaming direction
with a successful corresponding public path call, and exercises all 32
selector declarations across the 28 partial-capable codecs. Dedicated mmap
and sink suites independently prove the allocation behavior represented by
those capability flags. The reviewable property-specific exemption mapping is
empty. This changes package verification breadth only: no codec, timed path,
fixture payload, or performance threshold changes, so no speedup is claimed.
Focused
architecture/documentation tests and the source-tree NumPy-only smoke pass.
The complete tree collects 3,348 tests and passes 3,344 with four documented
skips; Ruff and the complete five-run strict O4/O5 guard pass.

The first frozen package tree contains 380 files and produces a 381-file sdist
whose only generated member is `PKG-INFO`; all source members are byte-identical
to their staged Git blobs. Its sdist-derived 81-member Windows ABI3 wheel has
one native module, all 15 attribution files, no excluded repository or native
development payload, and NumPy as its sole unconditional dependency. A fresh
outside-repository SceneIO-plus-NumPy environment returns `2` from the
complete installed smoke. The final documentation tree repeats this package
gate before review; artifact hashes remain in immutable commit evidence rather
than this self-referential source document.

## R4.1 modular native-build preservation (2026-07-27)

R4.1 changes build ownership only. The root CMake file now assembles focused
instrumentation, source-manifest, dependency, and SceneIO-target modules. The
dependency block is byte-identical to parent `9ca6bb8`; the source contract
retains the original `_core` link order while partitioning all 40 codec files
across the eight manifest families and listing all 16 record files.

Fresh MSVC and manylinux2014 GCC 10.2.1 parent/candidate configurations have
no non-path cache difference. The normalized MSVC `_core` command stream is
exact across 60 commands; GCC 10 is exact across 59 compile commands and its
final link command. Both toolchains build the candidate. Since no codec,
adapter, fixture, compiler option, source, or link dependency changed, this
unit makes no throughput claim. The unchanged complete five-run strict O4/O5
and mmap/sink allocation guard passes; raw results are retained locally as
`build/r4_1_strict_guard.json`.

The 386-file staged tree produces a 387-file sdist with only generated
`PKG-INFO` added. All 386 repository members are byte-identical to their staged
Git blobs; the Windows qualification archive disables checkout line-ending
conversion before extraction. Its sdist-derived 81-member Windows ABI3 wheel
retains one native module, all 15 attribution files, no excluded build payload,
and NumPy as its sole unconditional dependency. Complete installed smoke
returns `2` in a fresh SceneIO-plus-NumPy environment.

R4.1 is pushed at `b2cf5d4`. Normal run `30310780347` and
compiler-instrumented run `30310780355` pass that exact commit.

## R4.2 family-owned native binding closure (2026-07-27)

R4.2 changes binding ownership only. A dedicated record table and eight
codec-family tables own the historical 16 record and 40 codec registration
functions behind one validated assembler. The same family descriptors expose a
canonical private inventory for all 49 native/hybrid built-ins; the
Python-owned `image_sequence` adapter remains outside that projection and is
separately checked through its declared Python operations.

The committed implementation builds with MSVC and manylinux2014 GCC 10.2.1. Its
non-dunder `_core` surface remains 232 names, a focused 416-test I/O and
architecture sweep passes, and collection is exactly 3,354 nodes. The
unchanged complete five-run strict O4/O5 and mmap/sink allocation guard passes
and is retained locally as `build/r4_2_strict_guard_final.json`. No codec timed loop,
transport adapter, fixture, compiler option, or native dependency changed, so
this mechanical unit makes no throughput claim. The complete 3,354-node suite
passes 3,350 tests with four documented skips, and Ruff is clean.

The 398-file staged tree produces a 399-file sdist whose only generated member
is `PKG-INFO`; every repository member is byte-identical to its staged Git
blob. The sdist-derived 81-member Windows ABI3 wheel contains one native
module, all 15 notices, no excluded build payload, and NumPy as its sole
unconditional dependency. It contains no FFmpeg/libav payload. A fresh
outside-repository environment contains only SceneIO 0.2.0 and NumPy 2.5.1,
and the complete installed smoke returns `2`. All three confirmation reviews
are clear. Commit `81e0e1c`, normal run `30316577366`, and
compiler-instrumented run `30316577369` close the checkpoint.

The first independent review pass found no native pointer, reference-count, or
descriptor-lifetime defect. It identified an operation-category test gap,
mutable inventory rows, and basename/nonrecursive source checks that would
weaken after R4.3. The candidate now freezes every ordered operation tuple in
an independent 49-row contract, requires every referenced symbol to be
callable, publishes mapping-proxy rows, and validates codec ownership
recursively by full path. These changes affect registration metadata and tests
only; no timed codec path changed.

## R4.3 arrays-family source move closure (2026-07-27)

PFM, NPY/NPZ, Safetensors, FLO, and DMB move from the flat native codec
directory to `src/cpp/codecs/arrays/`. Their implementation blobs are
unchanged apart from the Safetensors source-location comment. CMake family
ownership, the frozen core link order, the native-build contract, and all
performance-ledger provenance paths use the new locations.

The MSVC editable build passes. A 561-node array-family and cross-I/O sweep
covers codec parity, bytes/mmap reads, direct sinks, inspection, partial
reads, the public API, and native build/inventory contracts; 560 pass with one
documented absent-OpenCV oracle skip. Ruff, the 232-name non-dunder
`_core` surface, and the 49-entry native inventory remain unchanged. No timed
codec implementation changed, so this unit makes no performance claim.

The first complete strict run encountered a single noisy
`transforms_json` full-read/inspection control ratio. A focused five-run
confirmation measured 26.543 ms versus 10.437 ms (2.54x, inside the 3x
control) and is retained as
`build/r4_3_arrays_transforms_confirm.json`. A second complete five-run strict
all-50-codec sweep passed in 363 seconds and is retained as
`build/r4_3_arrays_strict_guard.json`; its final verdict confirms the stable
O4 controls, O5 inspection/partial controls, and mmap/sink allocation bounds.
The architecture/lifetime, test/performance, and
platform/package/documentation reviews are clear.
Commit `f57c677` is pushed to `phase0-nanobind-core`.

## R4.3 calibration-family source move closure (2026-07-27)

The shared OpenCV/ROS/Kalibr implementation moves to
`src/cpp/codecs/calibration/camera_calibration.cpp`. Its executable source is
unchanged; the embedded source-location comment and the CMake,
native-build-contract, and performance-ledger paths use the new location.
The frozen core link and registration order remain unchanged.

The MSVC editable build and 223 focused codec/family/mmap/sink/inspection/API
tests pass. The complete suite passes 3,350 tests with four documented skips;
Ruff, the 232-name non-dunder `_core` surface, and the 49-entry native
inventory remain unchanged. The complete five-run strict all-50-codec guard
passes in 363.5 seconds and is retained as
`build/r4_3_calibration_strict_guard.json`. No timed codec implementation
changed, so this unit makes no performance claim. The architecture/lifetime,
test/performance, and platform/package/documentation reviews are clear.
Commit `366aac0` is pushed to `phase0-nanobind-core`.

## R4.3 images-family source move closure (2026-07-27)

Netpbm, PNG, JPEG, BMP/TGA, HDR, EXR, and WebP move to
`src/cpp/codecs/images/`. Netpbm and BMP/TGA are byte-identical moves; the
other five executable bodies are unchanged and only their first-line
source-location comments use the new paths. CMake ownership, frozen link
order, native-build contracts, and the live performance-ledger paths move
with them.

The MSVC editable build and 493 focused codec/family/mmap/sink/inspection/
partial/API tests pass. The complete suite passes 3,350 tests with four
documented skips; Ruff, the 232-name non-dunder `_core` surface, and the
49-entry native inventory remain unchanged. The complete five-run strict
all-50-codec guard passes in 363.4 seconds and is retained as
`build/r4_3_images_strict_guard.json`. No timed codec implementation changed,
so this unit makes no performance claim. The architecture/lifetime,
test/performance, and platform/package/documentation reviews are clear.
Commit `aff2a37` is pushed to `phase0-nanobind-core`.

## R4.3 meshes-family source move closure (2026-07-27)

PLY-mesh, OBJ/MTL, STL/OFF, and glTF move to `src/cpp/codecs/meshes/`.
PLY-mesh and OBJ/MTL are byte-identical moves; the other two executable bodies
are unchanged and only their first-line source-location comments use the new
paths. CMake ownership, frozen link order, native-build contracts, and the
live performance-ledger paths move with them.

The MSVC editable build and 419 focused codec/family/mmap/sink/inspection/
partial/API tests pass. The complete suite passes 3,350 tests with four
documented skips; Ruff, the 232-name non-dunder `_core` surface, and the
49-entry native inventory remain unchanged. The complete five-run strict
all-50-codec guard passes in 372.9 seconds and is retained as
`build/r4_3_meshes_strict_guard.json`. No timed codec implementation changed,
so this unit makes no performance claim. The architecture/lifetime,
test/performance, and platform/package/documentation reviews are clear.
Commit `c5de24b` is pushed to `phase0-nanobind-core`.

## R4.3 points-family source move closure (2026-07-27)

PLY-point, PCD, XYZ/PTS, LAS, and LAZ move to `src/cpp/codecs/points/`.
PLY-point and PCD are byte-identical moves; the other three executable bodies
are unchanged and only their first-line source-location comments use the new
paths. CMake ownership, frozen link order, native-build contracts, and all 32
live performance-ledger paths move with them.

The MSVC editable build and 583 focused codec/family/mmap/sink/inspection/
partial/API tests pass. The complete suite passes 3,350 tests with four
documented skips; Ruff, the 232-name non-dunder `_core` surface, and the
49-entry native inventory remain unchanged. The complete five-run strict
all-50-codec guard passes in 373.5 seconds and is retained as
`build/r4_3_points_strict_guard.json`. No timed codec implementation changed,
so this unit makes no performance claim. The architecture/lifetime,
test/performance, and platform/package/documentation reviews are clear.
Commit `97b24e2` is pushed to `phase0-nanobind-core`.

## R4.3 reconstruction-family source move candidate (2026-07-27)

All eleven native sparse-model, pose/state, JSON, and COLMAP database sources
move to `src/cpp/codecs/reconstruction/`. BAL is byte-identical; every other
executable body is unchanged and only its first-line source-location comment
uses the new path. CMake ownership, frozen link order, native-build contracts,
and all 34 live performance-ledger paths move with them.

The MSVC editable build and 691 focused codec/family/mmap/sink/inspection/
partial/API tests pass with two documented skips. The complete suite passes
3,350 tests with four documented skips; Ruff, the 232-name non-dunder `_core`
surface, and the 49-entry native inventory remain unchanged. The complete
five-run strict all-50-codec guard passes in 364.5 seconds and is retained as
`build/r4_3_reconstruction_strict_guard.json`. No timed codec implementation
changed, so this unit makes no performance claim. The architecture/lifetime,
test/performance, and platform/package/documentation reviews are clear.
