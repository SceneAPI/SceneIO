# TIFF collection selection benchmark

FC4 has a dedicated benchmark because the typed collection selectors do not
fit the generic one-selector codec benchmark. The executable source is
[`bench/io_bench/tiff_collections.py`](../bench/io_bench/tiff_collections.py).

The default fixture is a deterministic tiled `uint16` `ZYX` stack with shape
`(8, 2048, 2048)`: 67,108,864 logical bytes (64 MiB). tifffile writes it as a
67,122,784-byte classic TIFF with 128x128 tiles. The selected operation reads
one page and a 512x512 window, or 524,288 logical bytes. SceneIO binds
`TiffPageSeries.aszarr(level=...)` to the exact source level and lets Zarr
decode only intersecting tiles. The control calls `tifffile.imread` for the
whole stack and slices afterward.

Run the measured profile from the repository environment:

```text
.venv/Scripts/python.exe -m bench.io_bench.tiff_collections \
  --directory build/fc4-tiff-benchmark-data --runs 3 \
  --output build/fc4-tiff-benchmark.json
```

## Local result — 2026-08-29

Windows/MSVC, Python 3.12.10, tifffile 2026.7.14, Zarr 3.3.0, warm cache,
three timed runs plus separate allocation/RSS passes:

| operation | median ms | traced peak MB | RSS growth MB |
|---|---:|---:|---:|
| typed selected page + window | 2.279 | 1.146 | 1.245 |
| direct tifffile full decode + slice | 67.086 | 84.602 | 83.542 |
| typed full collection read | 76.818 | 84.604 | 134.619 |
| typed metadata-only inspection | 0.674 | 0.179 | 0.020 |

Against the full-decode-and-slice control, the selected typed read reduced
traced peak allocation by 98.65% (1.35% of the control peak). Exact array
equality is checked for the full typed read, selected typed read, and provider
control before a result is emitted. The executable test also runs a small
fixture in the normal suite.

These numbers are same-machine observations, not an SLA. `tracemalloc`
measures Python-tracked allocation; sampled process RSS supplies the
complementary native-process direction. The qualification claim is bounded:
chunk-granular selection is proven for tiled and stripped TIFF through the
pinned provider surface, while arbitrary OME microscopy semantics remain a
deliberate refusal.

### Fresh-process RSS qualification

The warmed-parent RSS column above remains useful exploratory evidence, but
it does not substitute for a clean-process measurement. The retained strict
qualification reruns each operation in three independent Python processes
after a registry-only warm-up:

```text
.venv/Scripts/python.exe -m bench.io_bench.tiff_collections \
  --directory build/fc4-tiff-fresh-rss-final-data --runs 1 \
  --fresh-rss-samples 3 --fresh-rss-timeout-seconds 120 \
  --output build/fc4-tiff-fresh-rss-final.json
```

| operation | median fresh-process RSS growth |
|---|---:|
| typed full collection read | 139,366,400 bytes |
| typed selected page + window | 19,849,216 bytes |
| typed metadata-only inspection | 4,300,800 bytes |

The bounded selection uses 14.24% of full-read resident growth and inspection
uses 3.09%. All samples use the Windows `psutil_peak_wset` lifetime-peak
backend through `sceneio-fresh-child-memory-v1`; the protocol requires one
warm-up and exactly one measured operation in every child.
