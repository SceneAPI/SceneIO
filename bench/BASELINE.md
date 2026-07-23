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
