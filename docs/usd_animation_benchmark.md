# USD selected-time qualification and benchmark

FC6 closes in **state B: selected-time read only**. SceneIO evaluates a
bounded subset of directly authored USDA node samples through the existing
`read_scene(path, time=...)` API. It does not preserve or author animation and
does not export a `SceneAnimation` record.

## Qualified subset

- Direct `.usda`, `.usd` containing USDA, and `.usdz` with a USDA root layer.
- `matrix4d xformOp:transform.timeSamples` with a single matrix op, optionally
  preceded by `!resetXformStack!`.
- `token visibility.timeSamples` with `inherited` and `invisible` values.
- OpenUSD-compatible component-wise matrix interpolation, held token values,
  and held values before the first and after the last sample.
- Static hierarchy, topology, meshes, points, Gaussians, cameras, materials,
  volumes, instances, and semantic payloads.

The repository-owned evaluator parses TinyUSDZ-normalized direct prim text
with fixed matrix/token grammar and explicit text, line, token, string, and
sample-count limits. It refuses duplicate/nonfinite times, empty tables,
unknown visibility values, arbitrary sampled xform stacks, all sampled payload
properties, composition, USDC selected time, animation preservation, and
dynamic writing. A selected `SceneGraph` may be written only as an ordinary
static snapshot; the writer never reproduces the source sample tables.

`tests/codecs/test_openusd_animation_oracle.py` compares USDA and USDA-root
USDZ at negative, fractional, exact, between-sample, and held-endpoint times
against the separately installed official `usd-core==26.8` package. OpenUSD is
test-only and remains absent from normal imports and runtime dependencies.

## Retained measurement

Command, run on Windows CPython 3.12 on 2026-08-29:

```powershell
.venv/Scripts/python.exe bench/bench_usd_animation.py `
  --directory build/usd-animation-bench --runs 3 `
  --nodes 256 --samples 24 --time 6.25 `
  --output build/fc6-usd-animation-benchmark.json
```

The generated 479,971-byte stage contains 256 nodes and 6,912 authored
property samples (24 matrices and three visibility samples per node). The
equal-node static control is 42,512 bytes. Median wall time and separately
measured warmed-process peaks were:

| Operation | Median | Traced peak | RSS growth |
|---|---:|---:|---:|
| selected-time read | 229.74 ms | 0.425 MB | 5.984 MB |
| inspection | 241.13 ms | 0.506 MB | 4.891 MB |
| equal-node static read | 13.33 ms | 0.422 MB | 3.973 MB |

The benchmark validates the selected node count/time and inspection's exact
sample count before recording metrics. Full-animation preservation read and
authored-animation write are explicitly marked not applicable for state B,
rather than being inferred from selected-time materialization.

## 64 MiB and fresh-process qualification

The universal large-profile gate uses 35,000 nodes, 24 matrix samples and
three visibility samples per node. Its 69,087,011-byte USDA layer is 65.89 MiB
and contains 945,000 authored property samples, so it clears the 64 MiB
minimum without approaching the per-prim parser limits. The equal-node static
control is 6,012,261 bytes.

```powershell
.venv/Scripts/python.exe bench/bench_usd_animation.py `
  --directory build/fc6-usd-animation-large-fresh --runs 1 `
  --nodes 35000 --samples 24 --time 6.25 `
  --fresh-rss-samples 3 --fresh-rss-timeout-seconds 180 `
  --output build/fc6-usd-animation-large-fresh-benchmark.json
```

| Operation | Wall time | Traced peak | Median fresh-process RSS growth |
|---|---:|---:|---:|
| selected-time read | 33.44 s | 50.63 MB | 1,404,755,968 bytes |
| inspection | 33.98 s | 49.64 MB | 1,404,219,392 bytes |
| equal-node static read | 2.77 s | 39.76 MB | 979,726,336 bytes |

Fresh-process values are medians of three independent children under
`sceneio-fresh-child-memory-v1`. The reported delta is the greater of the
sampled-current and Windows lifetime peak-working-set deltas; the native
lifetime counter captures short provider peaks that the sampling thread can
miss.

These results are qualification evidence for successful bounded-grammar
evaluation at the required input size, not a claim that selected-time parsing
avoids provider layer materialization. State B has no full-animation
preservation read or authored-animation writer to use as a valid directional
control. The smaller 256-node profile remains the repeatable development
benchmark, while this large run makes the provider cost and the nonclaim
explicit.
