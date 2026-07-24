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
find and validate row boundaries, so its guard requires at least a 4 MB
absolute RSS reduction; the other material rows require a directional ratio
gain. The paired five-run CI guard passed together with all retained O4 and O5
inspection controls. Final verification passed 1,289 tests / 3 optional skips
on Windows and 1,208 / 62 expected skips under ASan/UBSan/LSan on Linux.
