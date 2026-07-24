# O0 baseline — SceneIO I/O harness

Snapshot from `python bench/bench_io.py --runs 7`. **Indicative** (median of 7,
single machine, local **MSVC** build, warm cache); the *conclusions* below are what
order the O1+ sweep, not the exact MB/s. Regenerate on any machine — the harness is
the source of truth, this file is a dated reading.

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

2. **Encode throughput has three real hotspots** (decode is healthy everywhere —
   competitive with or faster than the oracles: npy 1.4×, webp 1.5×, las 0.73×):
   - **jpeg 60 vs libjpeg 900 MB/s (0.28×)** — stb's JPEG *encoder* is the outlier.
     SIMD/threads (O4) won't fix an algorithmic gap; flag as "accept, or swap to a
     faster permissive encoder later" rather than an O4 target.
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
covers all 23 codecs, including both COLMAP directory variants, Bundler, NVM,
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

CI runs the all-23-codec smoke and uploads its JSON. A second five-run sweep
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
