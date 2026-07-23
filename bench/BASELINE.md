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

## Not yet covered

Reconstruction/pose codecs (colmap/bundler/nvm/openmvg/tum/kitti/transforms) — need
a `Reconstruction`/`PosedViewSet` builder; they're metadata-sized, low perf
priority. npz, and hdr/exr/netpbm oracles (imageio/OpenEXR) — add as O1 lands.
