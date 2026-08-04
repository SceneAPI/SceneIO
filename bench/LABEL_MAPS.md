# Dense-label carrier benchmark

This ledger covers the explicit `sceneio.label_map/1` overlay on NPZ and Zarr.
It is separate from the registry-wide `bench_io.py` table because the typed
overlay is an API/schema profile, not a new format id. The executable harness
is `bench/bench_label_maps.py` and cross-checks SceneIO with NumPy and the
official Zarr implementation before recording timings.

## FC2 generic-carrier checkpoint — 2026-08-03

Command:

```powershell
.venv\Scripts\python.exe bench/bench_label_maps.py `
  --runs 3 --side 4096 --rss-samples 3 `
  --json build/bench-label-maps-fc2-final.json
```

The generated fixture is one `4096 x 4096` C-contiguous int32 semantic raster
(64 MiB logical payload), 23 explicit classes, void id `-1`, and a small
taxonomy including color and thing/stuff metadata. Values repeat
deterministically, so the 0.045 MiB Zarr-v3 store is a
deliberately low-entropy compression case rather than a representative file-
size ratio. Measurements are warm-cache medians on the local Windows/MSVC
development machine. Fresh-process RSS is the median of three separately
warmed child interpreters. These numbers are comparative evidence for this
machine and profile, not portable thresholds.

| Carrier/operation | SceneIO | Oracle | SceneIO traced peak | SceneIO fresh RSS |
|---|---:|---:|---:|---:|
| NPZ stored write | 381 MB/s | NumPy 1,510 MB/s | 0.005 MiB | not measured |
| NPZ stored read | 379 MB/s | NumPy 1,474 MB/s | 8.02 MiB | 256.3 MiB |
| NPZ inspect | 1.63 ms | NumPy-header 0.65 ms | 0.051 MiB | 0.25 MiB |
| Zarr v3 write | 699 MB/s | Zarr 653 MB/s | 80.37 MiB | not measured |
| Zarr v3 read | 839 MB/s | Zarr 2,155 MB/s | 104.21 MiB | 92.5 MiB |
| Zarr inspect | 25.76 ms | Zarr 2.84 ms | 0.168 MiB | 16.00 MiB |

Both read/write carrier directions compare every array present in this
semantic schema fixture before timing. Inspection parity separately checks
shape, dtype, marker, and void metadata. Typed inspection does not decode the
64 MiB raster.

## Optimization delta

The initial qualified implementation exposed two avoidable adapter costs. The
final checkpoint keeps only the improved path:

| Change | Before | After | Result |
|---|---:|---:|---:|
| Bounded taxonomy membership, NPZ typed read | 182 MB/s; 25.01 MiB traced | 379 MB/s; 8.02 MiB traced | 2.08x throughput; 68% less traced peak |
| Direct owned-array Zarr typed read | 237 MB/s; 144.6 MiB fresh RSS | 839 MB/s; 92.5 MiB fresh RSS | 3.54x throughput; 36% less fresh RSS |
| Direct owned-array Zarr typed write, current fixture | staged `TensorDict`: 626 MB/s | direct: 699 MB/s | 1.12x throughput and no temporary `TensorDict` copy |

The Zarr correction removes the temporary copy through `TensorDict`; raw Zarr
continues to return `TensorDict` for compatibility. The membership correction
uses bounded contiguous/small-table checks while retaining exact rejection of
unknown ids. Typed Zarr reads validate metadata and the version marker before
bulk decode while reusing one provider session, avoiding repeated group opens.

The remaining NPZ read RSS is understood: the existing miniz decoder stages a
complete extracted NPY member and an intermediate payload before filling the
owned `TensorDict` entry. That is a raw NPZ codec optimization opportunity,
not evidence that typed inspection allocates the raster, and it is deliberately
not hidden by tracemalloc-only reporting.
