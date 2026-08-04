# E57 multi-scan benchmark evidence

The FC3 benchmark is separate from the legacy one-scan `e57` row in
`bench/bench_io.py`.  It exercises the typed scan API:

- `_core.point_scan` and `_core.scan_set` build a deterministic three-scan
  fixture;
- `sceneio.read_e57_scans` measures the complete `ScanSet` read;
- `sceneio.read_e57_scan(..., scan_index=..., stored_point_range=(start, stop))`
  measures a half-open stored-row selection;
- `sceneio.write_e57_scans` measures the typed writer; and
- `sceneio.inspect_e57_scans` measures header-only typed inspection.

The benchmark resolves these functions lazily so importing the benchmark does
not make the optional E57 provider a runtime dependency. The inspection row
does not decode point payloads.

## Fixture and oracle

`bench/io_bench/e57_multiscan.py` generates all arrays from fixed formulas.  A
fixture contains Cartesian float32 positions, RGB uint8, float32 intensity,
raw nonzero `cartesianInvalidState` values, sparse row/column indices, and a
different WXYZ pose for each scan.  Scan IDs and names are deterministic;
`guid=""` is intentional because pye57/libE57Format generates GUIDs on write.
A represented timestamp of zero is intentional because pye57 always authors
`acquisitionStart`. The logical payload is never checked into the repository.

Each run writes two files. This is a direct-provider/format-owner differential:
pye57 and SceneIO's adapter share the libE57Format lineage, so it is not
described as an independent parser comparison.

1. SceneIO writes the typed `ScanSet`; pye57 reopens it and checks every raw
   field, valid row, pose, and scan count.
2. pye57 writes the same payload; SceneIO reopens it and checks the same
   contract, including `PointScan.valid_point_cloud()`.

Invalid-row coordinates are compared only through the valid mask because the
FC3 contract permits canonical placeholders for invalid coordinates; the raw
invalid-state values themselves must remain exact.  Selection uses stored row
indices, not the count of valid points.

## Running

Use the repository interpreter and an output directory outside source control:

```text
.venv/Scripts/python.exe -m bench.io_bench.e57_multiscan \
  --directory .bench/e57-multiscan --runs 3 --scale 1
```

For a larger generated fixture, increase `--scale` (`--scale 256` produces
3,145,728 stored rows and a 113.25 MB logical payload). `--cold-cache` applies
the platform cache hint
when available.  The JSON result has schema
`e57-multiscan-benchmark-v1` and records file sizes, selected scan/range,
throughput inputs, traced Python peak allocation, and sampled RSS for typed
and oracle write/full-read/selected-read/inspect operations.

SceneIO's selected reader uses libE57Format's sequential reader with a fixed
65,536-row buffer. The provider's `seek()` entry raises
`ErrorNotImplemented`, so SceneIO streams and discards preceding chunks before
copying only the requested overlap. The direct pye57 comparison intentionally
uses `read_scan_raw` followed by a slice and therefore materializes every scan.

## Local result — 2026-08-04

Windows/MSVC, Python 3.12, pye57 0.4.19, warm cache, one measured large run:

| operation | ms | traced peak MB | RSS growth MB | logical MB/s |
|---|---:|---:|---:|---:|
| typed selected read | 81.055 | 11.333 | 11.067 | 46.57 |
| direct pye57 selected control | 424.467 | 151.004 | 148.828 | 8.89 |
| typed full `ScanSet` read | 706.567 | 113.259 | 205.791 | 160.28 |
| direct pye57 full read | 451.110 | 151.004 | 150.045 | 251.04 |
| typed header inspection | 11.714 | 0.024 | 0.033 | — |
| typed write | 1172.989 | 199.951 | 195.146 | 96.55 |
| direct pye57 write | 744.922 | 180.012 | 38.261 | 152.02 |

The fixture was 113,246,376 logical bytes; both outputs were 68,870,144 bytes.
The selected range contained 104,857 rows from one scan. Against the direct
pye57 full-decode control, the typed range reduced traced peak allocation by
92.5%, RSS growth by 92.6%, and elapsed time by 80.9%. A separate three-run
28.31 MB sweep showed the same direction (3.31 versus 37.76 MB traced peak).
The write rows expose pye57's fixed internal authoring buffers; FC3 does not
claim a write-allocation improvement.

These are warm, in-process, same-machine observations rather than an SLA.
`tracemalloc` covers Python-tracked allocations; sampled process RSS supplies
the complementary whole-process direction, including native provider memory.

## Official multi-scan boundary vector

The opt-in official `pumpNoInvalidPoints.e57` sample is pinned at 22,146,048
bytes and SHA-256
`5b85b18fe9860e9f9a2f397434530f2d403fefcc15cf1ff92d75d96d274ff5a5`.
pye57 reports five ordered structured Cartesian scans and 1,213,990 stored
rows. The public typed reader first refuses unrepresented standard scan
metadata; a direct payload probe also finds coordinates that fail exact
float32 representation. SceneIO therefore cannot accept this file by silently
dropping metadata or narrowing values. The generated fixture is the positive
round-trip vector; the official file is a real-producer bounded-profile vector.

The format-owner oracle is the optional pinned `pye57` 0.4.19 provider over
libE57Format; both entries share one E57 lineage in the oracle catalog.
Licensing and provenance are recorded in `LICENSES/README.md` and the E57
oracle contract.  Official multi-scan E57 examples are an opt-in extension of
this generated run and remain digest-pinned external fixtures; they are not
required for the normal test tier.
