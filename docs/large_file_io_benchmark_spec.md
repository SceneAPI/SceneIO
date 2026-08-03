# Large-file 3D-CV I/O benchmark specification

Status: Sol specification approved for local execution, 2026-08-03. The
benchmark is an evidence run, not a permanent performance-tuning loop.

## Goal and boundary

Measure SceneIO's large-file read and write behavior against the established
independent implementation for each representative 3D-CV workload. The result
must answer four questions:

1. Can SceneIO and the reference implementation read the same licensed or
   deterministically generated artifact?
2. Can each implementation read the other implementation's output without a
   semantic mismatch?
3. What are the median full-read and full-write throughput and peak process
   memory deltas on the same machine?
4. Do SceneIO's mapped-path and direct-sink paths avoid an additional
   file-sized Python allocation at large scale?

This is deliberately a five-case closure run. It does not benchmark every
registered format, tune codec internals, add a runtime dependency, download a
general media framework, or establish machine-independent numeric pass/fail
thresholds. `bench/bench_io.py` remains the complete 73-format regression
harness; this benchmark supplies large, representative evidence for Gaussian,
point-cloud, mesh, reconstruction, and dense-array workloads.

## Fixture policy

The acquisition order is fixed:

1. Prefer an upstream asset only when the asset or its containing tree has an
   explicit reusable license.
2. Pin a repository revision where the host supports immutable URLs. Record
   the downloaded byte count and SHA-256 before decoding it.
3. Keep downloaded and generated large files below `build/bench-data/`; never
   add them to Git or a wheel.
4. When a licensed source is too small for the target payload, decode it first
   and enlarge its records deterministically. Record the seed, repeat count,
   spatial offsets, and whether the result is a `derived_fixture`.
5. If acquisition is unavailable, use the specified deterministic fallback and
   mark the result `synthetic_fallback`. Never silently substitute data.
6. Time neither download nor fixture construction. Validate each source and
   constructed artifact before the first measured operation.

### Licensed source catalog

The checked-in TOML manifest is the machine-readable authority. These are the
sources selected during the 2026-08-03 online review:

| Source id | Use | Pin | License and attribution |
|---|---|---|---|
| `niantic_racoonfamily_spz` | Gaussian/SPZ qualification seed decoded by the pinned official provider | Niantic SPZ `5bf2945de1a003cee07133b1e495fe9c6ffdc7e7`; sample Git blob `d21ab3d660c64d134219702b6a11deeaefc43878` | MIT; Niantic Labs, [`nianticlabs/spz`](https://github.com/nianticlabs/spz) |
| `pdal_autzen_laz` | real LiDAR/LAZ workload | PDAL data `ce0024257c573526389c4db9ab26e82739b8aaa9`; LFS object verified by SHA-256 | CC-BY-4.0; data provided by Aaron Reyna/Watershed Sciences for libLAS testing, with PDAL/Hobu curation, [`PDAL/data`](https://github.com/PDAL/data/tree/main/autzen) |
| `khronos_box_vertex_colors_glb` | topology and vertex-attribute seed | glTF Sample Assets `2bac6f8c57bf471df0d2a1e8a8ec023c7801dddf`; model asset `BoxVertexColors.glb` | model files CC0-1.0; Marco Hutter, [`KhronosGroup/glTF-Sample-Assets`](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/BoxVertexColors) |
| `tum_freiburg1_xyz_groundtruth` | realistic timestamp, translation, and quaternion seed for reconstruction | immutable content by recorded SHA-256 at the official TUM download URL | CC-BY-4.0; TUM Computer Vision Group RGB-D benchmark, [`freiburg1_xyz`](https://cvg.cit.tum.de/data/datasets/rgbd-dataset) |

The Niantic sample is already a meaningful compressed scene, and Autzen is a
10,653,336-point, roughly 56 MB LAZ file. Source qualification found that the
Niantic sample carries the antialiasing flag absent from SceneIO's current
`GaussianCloud`, Autzen's source container is outside SceneIO's bounded
single-LASzip-VLR profile, and the Khronos model uses a `COLOR_0` representation
SceneIO intentionally does not preserve. Those are not decoder failures to
paper over: the timed common files are reference-decoded, explicitly transformed
derived fixtures. The derived SPZ clears the unsupported rendering flag, the
derived LAZ is rewritten into the supported canonical profile, and the derived
GLB quantizes vertex colors to normalized uint8. The TUM trajectory is directly
readable with explicit `format="tum"`. Every transformation is recorded; none
of these derived files is presented as an unmodified captured dataset. The TUM
text seed is parsed by a small independent strict parser in the benchmark
fixture layer, so fixture pose conversion does not share SceneIO's TUM reader.

## Benchmark matrix

The standard tier targets at least 256 MiB of logical decoded payload for
derived cases. Direct source cases retain their original encoded size. A
separate `--tier stress` mode may target 1 GiB but is not part of this closure
run or its acceptance criteria.

| Case id | SceneIO format | Standard fixture | Reference implementation | Required operations |
|---|---|---|---|---|
| `spz_racoon_v4` | `spz` | official-decoded licensed sample, unsupported antialias metadata explicitly omitted, then translated repeats as needed to at least 256 MiB logical payload and reference-written as flag-free v4 | official Niantic binding (Python distribution reports 1.1.0) at pinned commit `5bf2945`; gsply 0.4.6 is a second reader/writer check where its supported profile overlaps | derived common-file read, write, cross-read, inspect diagnostic |
| `laz_autzen` | `laz` | licensed Autzen values decoded by laspy/lazrs and rewritten into SceneIO's supported canonical LAZ profile; 10,653,336 points, no count scaling required | laspy 2.7.0 with lazrs 0.8.1 | derived common-file read, write, cross-read, bounded point-selection diagnostic |
| `glb_box_grid` | `glb` | CC0 box geometry decoded by trimesh, colors explicitly quantized to normalized uint8, then flattened on a deterministic 3D translation grid until logical vertex/index/attribute payload is at least 256 MiB; one named instance carries a fixed non-identity translation | trimesh 4.12.2 | derived common-file read, write, cross-read, inspect diagnostic |
| `colmap_tum_tracks` | `colmap_sparse` | TUM poses sampled deterministically, with seeded finite 3D points and two observations per point; grow until the three binary model files total at least 256 MiB | pycolmap 4.1.1 | directory read, write, cross-read, inspect and one-image diagnostics |
| `npy_depth_stack` | `npy` | deterministic C-contiguous float32 depth stack based on 640x480 TUM frame geometry, at least 256 MiB | NumPy 2.4.6 | common-file map-open, full scan, write, cross-read, metadata diagnostic |

The reconstruction builder must preserve COLMAP's world-to-camera convention,
WXYZ quaternion ordering, valid image/camera ids, valid point/observation
references, and finite reprojection coordinates. Points and observations are
generated data. TUM contributes pose distribution only; no claim is made that
the derived points were measured in the original sequence.

## Provider and operation contract

Each implementation is called through its ordinary public or documented
optimized path:

- SceneIO: `sceneio.read(path)`, `sceneio.write(record, path)`, and
  `sceneio.inspect(path)`. These select mapped input and direct file sinks when
  the format supports them.
- Niantic SPZ: its pinned Python binding backed by the official C++ library.
- laspy/lazrs: path read and compressed path write.
- trimesh: `load(..., process=False, maintain_order=True)` and binary GLB
  export.
- pycolmap: `Reconstruction(path)` and `Reconstruction.write(path)`.
- NumPy: `np.load(path, mmap_mode="r", allow_pickle=False)` and
  `np.save(path, array, allow_pickle=False)`.

Reference packages stay test/benchmark-only. Nothing in this work changes the
base NumPy-only runtime requirement. Provider versions, module paths, and the
SceneIO Git commit are written into every result file.

### Common input and cross matrix

Read throughput compares both implementations on one identical common input:

- reference-written canonical output for the SPZ, LAZ, GLB, COLMAP, and NPY
  rows. The original licensed SPZ/LAZ/GLB files are provenance seeds and
  source-qualification inputs, not timed common files, because their bounded
  profiles are not directly representable by SceneIO.

Write throughput starts from already-constructed, semantically equivalent
in-memory records. Fixture conversion and validation are outside the timed
region. After timing, each provider's output is read by both providers. A row
is reportable only when all required cross-reads pass.

Provider outputs need not be byte-identical when a format permits different
serialization, compression, or record order. The comparison is semantic:

- NPY: shape, dtype, order, and every value exact.
- GLB: scene/mesh counts, vertex attributes, indices, transforms, and names
  exact after canonical ordering; float values use their stored-width bound.
- COLMAP: small fixtures exhaustively compare cameras, image poses, names,
  points, colors, errors, tracks, and observation coordinates after id
  sorting; quaternions are sign-invariant. The 256 MiB standard fixture keeps
  complete camera/image metadata, counts, and total-observation checks, then
  compares 4,096 evenly spaced sequential fixture point ids, attributes, and
  two-entry tracks. Observation XY is also checked in directions where both
  pycolmap records expose it. SceneIO's public record exposes association ids
  and offsets but not observation XY/track arrays, so its sampled tracks are
  independently derived from that CSR. The sampled profile and exact ids are
  written into the result rather than presented as an exhaustive point check.
- LAZ: point count and integer attributes exact; coordinates agree within
  half the declared scale plus one float32 ULP.
- SPZ: count, degree, metadata, position, log-scale, opacity, color/SH, and
  rotation equivalence use bounds derived from the selected SPZ quantization;
  quaternion signs are equivalent.

## Measurement protocol

The closure run uses the following fixed protocol:

- Windows 11/MSVC local editable build, recorded CPU/RAM/storage and provider
  versions.
- Preflight requires 8 GiB available RAM and 2 GiB free cache-volume storage
  for the standard run. This reflects provider-native COLMAP object overhead;
  it is recorded in the result and is not a wheel/runtime requirement.
- Standard tier, one untimed warm-up, then three timed samples per operation;
  report the median and all raw samples.
- One provider/operation per fresh child process. Constructed in-memory input
  is prepared before timing inside that child; fixture-construction duration is
  recorded separately but excluded from throughput.
- Persistent fixture preparation and decode-heavy cross validation also run in
  fresh children under the recorded worker timeout. A slow provider therefore
  yields a structured incomplete result instead of leaving the run unbounded.
- The final 256 MiB closure run uses a 900-second per-child bound because one
  timing child contains all three sequential samples and the COLMAP validation
  child performs several full provider decodes. The earlier 300-second attempt
  is retained as incomplete evidence; increasing the child bound does not
  change any timed sample or fixture.
- Reads retain the decoded object until the memory sampler observes the end of
  the operation. Writes close their destination before the timer stops.
- A mapped raw array is not reported as a full-file read merely because its
  header was parsed. NPY therefore has two rows: `map_open` measures validated
  mapping/view construction, while `full_scan` also visits every element with
  the same fixed NumPy reduction for both providers and verifies its scalar
  result. Logical full-read throughput is taken only from `full_scan`.
- Report wall time, logical-payload MiB/s, encoded-file MiB/s, peak RSS delta,
  and peak Python traced allocation. RSS is the primary whole-process memory
  metric; traced allocation identifies Python-visible file-sized copies.
- Warm-cache results are the required Windows result. `--cold-cache` is
  optional and reportable only when the platform confirms that an eviction
  request was applied; an unavailable hint is recorded, never treated as cold.
- Record logical CPU count and provider thread settings. Use each provider's
  ordinary optimized default; do not compare a deliberately restricted
  reference configuration with an unrestricted SceneIO configuration.
- Each measured write uses a distinct destination under the benchmark cache.
  The worker verifies that the closed output is non-empty, then removes it
  outside the timed interval. After timing it writes one additional unmeasured
  representative output through the identical provider path; that single file
  supplies encoded size and the full writer-by-reader cross matrix. This caps
  temporary storage without making cleanup part of the measurement.

Throughput uses binary MiB (`2**20` bytes). Both logical and encoded rates are
reported because compression ratios differ. Ratios are SceneIO/reference;
values above one favor SceneIO, but no ratio alone is a correctness or release
gate.

## Result schema and repository layout

Implementation should retain the current benchmark organization:

```text
bench/
  bench_large_io.py                 # stable CLI facade
  LARGE_FILE_IO.md                  # consolidated human-readable result
  io_bench/large/                    # source, fixture, provider, worker modules
  results/large_io/
    windows-msvc-<sceneio-sha>.json # machine-readable evidence
  data/large_io_sources.toml         # URLs, revisions, sizes, hashes, licenses
tests/
  test_large_io_benchmark.py         # micro-fixture and schema tests; no network
```

Large assets and derived files live only in `build/bench-data/large-io/`.
Normal tests use tiny deterministic fixtures and a local fake downloader; they
must not access the network or allocate a standard-tier payload.

Each JSON result records:

- schema version, UTC timestamp, SceneIO commit and dirty flag;
- platform, Python, compiler/build, CPU, RAM, storage, and thread policy;
- every provider name/version/revision;
- source id, URL, license, attribution, byte count, SHA-256, acquisition mode,
  derivation parameters, and fixture counts/shapes/dtypes;
- per operation/provider raw times, median, logical and encoded throughput,
  traced peak, RSS delta, and cache mode;
- cross-read status and the exact comparison profile; and
- any skip or unavailable optional metric as structured data, not a zero.

`bench/LARGE_FILE_IO.md` is generated or updated from that JSON and includes
fixture provenance, the environment, compact read/write/memory tables,
correctness status, interpretation, limitations, and exact reproduction
commands. It must distinguish direct licensed assets, derived fixtures, and
synthetic fallbacks.

## Commands

The intended command surface is:

```powershell
.venv\Scripts\python.exe bench\bench_large_io.py acquire --cache build\bench-data\large-io
.venv\Scripts\python.exe bench\bench_large_io.py verify --cache build\bench-data\large-io
.venv\Scripts\python.exe bench\bench_large_io.py run --tier standard --runs 3 --worker-timeout 900 --cache build\bench-data\large-io --json bench\results\large_io\windows-msvc-<sha>.json
.venv\Scripts\python.exe bench\bench_large_io.py report bench\results\large_io\windows-msvc-<sha>.json --output bench\LARGE_FILE_IO.md
```

Case selection (`--only`) and a small `--tier smoke` are required so adapters
can be verified without rerunning the entire large experiment.

## Acceptance checklist

- [x] All four online assets have explicit licenses, immutable provenance where
      available, recorded byte counts, and verified SHA-256 values.
- [x] No downloaded or generated large asset is tracked by Git or included in
      package artifacts.
- [x] The smoke tier and result-schema tests pass without network access.
- [ ] Every standard case reaches its declared size/count and passes both
      cross-read directions.
- [ ] Each measured row contains three raw samples, a median, throughput, RSS,
      and traced-allocation evidence, or a structured explanation of an
      unavailable metric.
- [ ] The SceneIO path read and file-sink paths show no additional
      approximately file-sized Python allocation for the applicable formats.
- [ ] Results name exact provider versions and do not combine warm and cold
      cache measurements.
- [ ] `bench/LARGE_FILE_IO.md` is reproducible from the committed JSON and
      accurately labels source, derived, and fallback data.
- [ ] Focused tests, documentation consistency checks, Ruff, and `git diff
      --check` pass.
- [ ] Three final reviews cover resource ownership/lifetime, format and
      coordinate correctness, and measurement/test soundness.

The benchmark is complete when this checklist is green and the result document
states any bounded provider limitation. A slower row is a finding to record,
not permission to weaken cross-read correctness or extend the experiment
indefinitely.
