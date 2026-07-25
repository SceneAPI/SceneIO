# Format-gap implementation, verification, and validation plan

- **Status:** execution in progress after SceneIO 0.2.0. G0, safetensors, PTS,
  scalar DMB, BAL, BMP/TGA, the compiled `FlowField` record, typed FLO, typed
  PFM depth, typed PNG depth, typed scalar EXR depth, generic point PLY, and
  PCD, `StateTrajectory`/EuRoC, `CameraRig` with OpenCV/ROS/Kalibr
  calibration, `PoseGraph`/g2o, and the `FeatureSet`/`MatchGraph`-backed
  COLMAP database, SuperSplat compressed PLY, PlayCanvas SOG v2, and KSplat
  v0.1 are complete locally. The polygon-preserving `Mesh` record and generic
  mesh PLY are also complete locally; canonical `MaterialSet`, strict
  polygon-preserving OBJ/MTL, strict STL/OFF, the `MeshScene` record, and plain
  glTF/GLB, LAZ point formats 0-3/6-8, the `ImageSequence` record, lazy image
  directories, and raw planar Y4M are complete locally.
  The remote workflows have now been dispatched. Windows and macOS mmap jobs
  pass at `ea622ac`, but Linux normal CI and the instrumented reliability lane
  are red; the current blockers are listed in section 12.1. Cross-platform
  validation therefore remains incomplete rather than merely user-gated.
- **Current branch:** 50 compiled codecs, all read/write and inspectable, with
  bounded partial reads where their containers permit them.
- **Scope:** close every unblocked format gap declared by SceneIO's coverage
  documents without reimplementing the 0.2.0 codec tier.

This plan is subordinate to the current shipped-state inventory in
`format_coverage.md`. `coverage_roadmap.md` has been reconciled to the live
registry; Phase G0 below records the mechanism that keeps the three documents
and public capability manifest aligned. Repository restructuring and backend
performance qualification are specified in
[`repository_organization_plan.md`](repository_organization_plan.md) and are
prerequisites for the next codec wave.

## 1. Outcome and boundaries

The program is complete when every declared format is in one of three explicit
states:

1. **Shipped**: implemented, independently verified, benchmarked, and present
   in the supported wheel matrix.
2. **Optional**: implemented behind a named `SCENEIO_WITH_*` build feature,
   with release wheels and source-build behavior documented.
3. **Excluded or policy-gated**: not silently left "pending"; the reason and
   decision owner are recorded.

"Coverage" means a documented, fidelity-preserving subset of a format. It does
not mean accepting every extension ever added to USD, TIFF, glTF, HDF5, Zarr,
or similar ecosystems. Unsupported features must be detected and rejected
clearly rather than flattened, triangulated, color-converted, or dropped
silently.

### 1.1 Non-negotiable constraints

- Runtime Python dependency remains numpy-only.
- Native libraries must use permissive licenses: MIT, BSD, zlib, Apache-2.0,
  public domain, or an already-approved equivalent.
- No ffmpeg, GPL/AGPL/NC dependencies, proprietary SDKs, or patented video
  codecs.
- The extension remains abi3/cp312 and builds with manylinux2014 GCC 10,
  AppleClang, and MSVC.
- `read_X(buffer) -> record`, `write_X(record) -> bytes`, buffer-protocol
  input, GIL release around pure native work, RAII, and zero-copy record views
  remain the codec conventions.
- Writers guard rather than silently convert conventions or unsupported
  fields.
- Large generated fixtures are created during tests and are never committed.
- This is an I/O correctness, performance, memory-safety, and portability
  program. It does not introduce a separate cybersecurity workstream.

### 1.2 Scope boundary

The following remain excluded unless the project constraints change:

- FBX and other proprietary-SDK formats.
- H.264, H.265, ProRes, HEIF/HEIC, and ffmpeg-backed containers.
- GPL/AGPL/non-commercial libraries.
- Arbitrary Python object serialization.

AVIF, JPEG-XL, and optional Draco compression remain policy-gated until their
fit with the project's patented-codec rule is explicitly resolved. Plain
glTF/GLB is not blocked by that gate.

### 1.3 Stable-format repository ownership

For this plan, **repo-owned** means the stable/default-wheel implementation is
reviewable, reproducible, and maintainable from the SceneIO repository. It
does not mean SceneIO claims copyright ownership of upstream permissive code.
Every upstream license and attribution remains intact.

Repository ownership applies to the SceneIO integration and release artifact,
not to authorship of a compression or parser algorithm. A mature optimized
upstream kernel is preferred to a bespoke reimplementation when it satisfies
the format contract and project constraints. The candidate must first pass the
same-path performance qualification in
[`repository_organization_plan.md`](repository_organization_plan.md); once
selected, its exact permissive source and notices become part of the
reproducible repository build.

A format may be called stable only when:

- its public adapter, format grammar, validation, convention handling,
  inspection, partial-read policy, streaming sink, and errors are implemented
  and tested in `src/cpp` or `src/sceneio`;
- it never delegates runtime work to an external executable, subprocess,
  plugin, or separately installed Python codec;
- any required compression/parser kernel is permissively licensed, pinned,
  stored under `src/cpp/third_party/`, statically linked or compiled
  header-only, and represented in `LICENSES/`;
- a clean source checkout can build the default wheel without downloading
  native source archives during CMake configure;
- independent projects remain test/reference oracles only and are not the
  production implementation.

All 50 current codecs already have repo-maintained adapters and optimized I/O
contracts. Repository source closure is not yet complete: `miniz`,
`nlohmann_json`, `zstd`, `fast_float`, `lazperf`, and `libwebp` are still
obtained through CMake `FetchContent`. Before the post-0.2 codec tier is called
stable, vendor those exact audited revisions into `src/cpp/third_party/`, copy
their upstream notices into `LICENSES/`, retain the current local patches, and
prove an offline sdist-to-wheel build on MSVC, GCC 10, and AppleClang.

Optional scientific/heavy integrations may remain behind
`SCENEIO_WITH_*` and use separately provisioned native libraries. They are
reported as optional, never as default stable formats, until their source and
wheel policy satisfies the same repository-ownership rule.

## 2. Shipped baseline and authoritative gap inventory

SceneIO 0.2.0 already ships these 23 registry entries:

`pfm`, `colmap_sparse`, `gaussian_ply`, `spz`, `transforms_json`, `tum`,
`kitti`, `npy`, `npz`, `netpbm`, `png`, `jpeg`, `hdr`, `exr`, `webp`,
`colmap_sparse_txt`, `xyz`, `las`, `flo`, `bundler`, `nvm`, `openmvg`, and
`splat`.

They are not part of the implementation backlog. New work may extend their
semantic coverage, such as typed depth PNG or animated WebP, without replacing
their current codec paths.

G0 must also reconcile these shipped-surface details:

- correct the current `.pts` documentation mismatch: the registry exposes only
  `.xyz`, and common PTS files may carry a leading point count, so `.pts` needs
  a specified dialect and codec rather than a blind extension alias;
- standardize the COLMAP text public id as `colmap_sparse_txt` in every
  document and example;
- distinguish generic PLY from `gaussian_ply` through header schema rather than
  first-registration extension order;
- record existing LAS point-format support as 0-3 and 6-8, with waveform
  formats 4/5/9/10 remaining unsupported until their packet fields have a
  fidelity-preserving record contract;
- distinguish raw ndarray reads from typed `DepthMap`/flow semantic adapters.

### 2.1 Record gaps

| Record | Required canonical content | First consumers |
|---|---|---|
| `Mesh` — complete locally | vertex positions; ragged face indices; optional vertex/corner normals, UVs, colors; primitive/material ranges; coordinate metadata | generic PLY, OBJ, STL, OFF, glTF |
| `MaterialSet` — complete locally | material names; base/emissive factors; metallic/roughness; alpha mode; texture image references, UV sets, and sampler metadata | OBJ/MTL, glTF, USD |
| `FeatureSet` — complete locally | keypoints, descriptors with dtype/shape metadata, scores, image size, image id/name | COLMAP DB, hloc |
| `MatchGraph` — complete locally | image-pair ids, ragged raw/verified match pairs, scores, optional F/E/H models and relative pose | COLMAP DB, hloc |
| `PoseGraph` — complete locally | pose nodes, typed edges, relative transforms, information matrices | g2o |
| `StateTrajectory` — complete locally | timestamps, position/orientation, velocity, gyroscope bias, accelerometer bias, frame/unit metadata | EuRoC state CSV |
| `CameraRig` — complete locally | ordered cameras, rig-to-camera extrinsics, names/ids, frame and unit metadata | OpenCV, ROS, Kalibr |
| `FlowField` — complete locally | HxWx2 f32 vectors plus component order, axes, row order, units, and invalid-value convention | typed FLO adapter |
| `ImageSequence` — path/planar modes complete locally | lazy frame references, timestamps/durations, dimensions, packed images or native planar frames with chroma subsampling metadata | image directories, Y4M, animated WebP/APNG |
| `Table` | named typed columns, null validity, UTF-8 offsets/data, row count, metadata | Parquet |
| `SparseGrid` / `Scene` | sparse grid values/transforms; scene nodes, transforms, mesh/camera references | OpenVDB, USD/USDZ |

`Mesh` must preserve polygon boundaries through offsets plus indices. A
triangle-only record would force silent triangulation on OBJ/OFF/PLY and is
therefore insufficient. Codecs that inherently require triangles may reject
non-triangular faces at write time or perform an explicit, opt-in conversion
outside the codec.

### 2.2 Format-gap ledger

The completed column records branch-local work beyond the original 23-codec
baseline. A remaining item is not considered covered until its work-package
exit gate and the validation matrix in section 8 both pass.

| Family | Remaining work | Complete locally on this branch |
|---|---|---|
| Reconstruction and pose | — | BAL, COLMAP database, EuRoC state CSV, g2o |
| Splat | — | SuperSplat compressed PLY, PlayCanvas SOG v2, and KSplat v0.1 |
| Point cloud | E57; optional future LAZ waveform/extra-byte/COPC extensions | count-prefixed PTS, generic point PLY, PCD, plain-LAS waveform sidecars for formats 4/5/9/10, and standard LAZ formats 0-3/6-8 |
| Mesh | USD/USDZ; optional Draco is policy-gated | generic mesh PLY, OBJ/MTL, STL, OFF, and plain glTF/GLB |
| Tensor/feature/table | HDF5, hloc layout, Zarr v2/v3, Parquet | safetensors, COLMAP features/matches |
| Image and depth | TIFF | BMP, TGA, typed PFM depth, typed PNG depth, typed scalar EXR depth, scalar DMB |
| Optical flow | — | compiled `FlowField` plus typed FLO |
| Calibration | — | OpenCV YAML/XML, ROS `camera_info`, Kalibr YAML |
| Sequence/dataset | animated WebP, APNG, RTMV layout | lazy image directories and raw planar Y4M |
| Volumetric/niche | OpenVDB | — |
| Policy-gated | AVIF, JPEG-XL, Draco compression | — |

## 3. Architecture work that precedes codec growth

### G0 — One machine-readable source of truth

**Purpose:** eliminate contradictory status tables and make registry
capabilities testable.

Implementation:

1. Extend `Codec` with explicit immutable metadata:
   - `can_read`, `can_write`, `can_inspect`;
   - `partial_selectors`;
   - `streams_read`, `streams_write`;
   - `lossy`;
   - `requires_features`;
   - `container_kind` (`file`, `directory`, or multi-file scene);
   - supported and intentionally unsupported subfeatures.
2. Derive fields when unambiguous, for example `can_write = write is not None`,
   but require explicit declarations for fidelity and optional dependencies.
3. Add `sceneio.capabilities(format=None)` returning frozen public metadata.
4. Generate or validate the format table in `format_coverage.md` from the
   registry. CI fails when a registered codec and the declared coverage
   inventory differ.
5. Reconcile every stale row in `coverage_roadmap.md` against 0.2.0.
6. Add a manifest of optional native features and their compiled state.
7. Correct the `.pts` shipped-status claim and the COLMAP text id without
   changing compiled codec behavior.

Verification:

- Unit-test capability metadata for all 23 existing codecs.
- Snapshot the sorted public capability schema.
- Prove that every registered writer, inspector, and partial hook agrees with
  its declared flags.
- Verify unknown feature names and unavailable optional codecs produce one
  normalized `FormatError`.

Validation:

- Run the unchanged public API E2E suite before and after the metadata change.
- Build a minimal source configuration with all optional features off.
- Build a release-like configuration with all currently available features on.

Exit gate:

- Registry, coverage document, and generated/snapshotted manifest report the
  same formats and capabilities.

### G1 — Record foundation

Records land only immediately before their first codecs, in this order:

1. `Mesh` and `MaterialSet`.
2. `FeatureSet` and `MatchGraph`.
3. `CameraRig`, `PoseGraph`, and `StateTrajectory`.
4. `ImageSequence`.
5. `Table`.
6. `SparseGrid` and the minimal `Scene` graph.

Every record follows the existing SoA pattern:

- C++ owns contiguous numeric buffers.
- numpy and DLPack views are zero-copy and keep the record alive.
- variable-length data uses offsets plus contiguous values, not Python object
  arrays.
- dtype, shape, endianness, coordinate frame, units, and transform direction
  are explicit.
- constructors validate coupled lengths and monotonic offsets before exposing
  any view.
- foreign buffers are pinned during construction and copied only when the
  canonical record representation requires ownership or dtype normalization.

Verification per record:

- empty, singleton, large, and maximum-index fixtures;
- mismatched lengths, non-monotonic offsets, invalid indices, overflow, and
  non-contiguous foreign arrays;
- zero-copy pointer identity and DLPack round-trip;
- parent/view lifetime after `gc.collect()`;
- read-only/writable policy;
- copy/deepcopy/pickle policy explicitly tested, whether supported or rejected.

Validation per record:

- MSVC build and full record suite;
- Linux instrumented build;
- abi3 wheel import and numpy interop smoke on all three wheel platforms.

Exit gate:

- A record cannot be considered complete until at least one codec uses it
  end-to-end; unused speculative records do not land.

New public `DataType` vocabulary ids for `splat`, posed views, mesh, material
set, rig, pose graph, state trajectory, sequence, table, scene, and sparse grid
remain a cross-repository integration gate. Record and codec implementation may
use clearly documented internal labels, as the 0.2.0 splat/pose codecs do, but
the shared vocabulary change is not implied. It requires an explicit
user-approved coordinated change in every consumer repository.

## 4. Codec work packages and sequencing

The dependency path is:

```text
G0 capability truth
 ├─ G1 Mesh/MaterialSet ── G3 mesh codecs ───── optional USD/Draco
 ├─ G1 Feature/Match ───── COLMAP DB ────────── HDF5/hloc
 ├─ existing TensorDict ── safetensors ──────── Zarr
 ├─ existing PointCloud ── generic point PLY ✅ ── PCD ✅ ── LAZ/E57
 ├─ G1 CameraRig/PoseGraph/StateTrajectory ─ calibration/g2o/EuRoC
 ├─ G1 ImageSequence ───── image-dir/Y4M ────── animated formats
 └─ G1 Table/Grid/Scene ── Parquet/OpenVDB/USD
```

Each numbered work package is independently committable and releasable.

### G2 — High-value self-contained coverage

#### G2.1 Safetensors — complete locally

Implementation:

- Implement the documented little-endian header-length, JSON header, and
  packed-buffer layout directly with existing JSON support.
- Map supported numeric dtypes onto `TensorDict`.
- Reject duplicate names, overlapping/gapped offsets, unknown dtypes, invalid
  shapes, non-C-order layouts, and payload length mismatches.
- `inspect` parses only the header.
- Full path reads return read-only mapped arrays where byte order/alignment
  permit; fallback decode owns converted data.
- Add tensor-name and tensor-slice selectors without decoding unrelated
  tensors.
- Writer emits deterministic key order, offsets, padding, and metadata.

Oracle:

- `safetensors.numpy` in the test extra only.

Verification:

- oracle-written -> SceneIO read;
- SceneIO-written -> oracle read;
- golden deterministic writer bytes;
- every supported `TensorDict` dtype and scalar/empty dimension;
- mapped-array lifetime after the original file and mapping handles leave
  scope;
- selected tensor memory bounded independently of total payload size.

Benchmark:

- full read, inspect, single-tensor read, and write versus the oracle;
- generated 128 MiB and 1 GiB multi-tensor fixtures;
- traced allocation and RSS above the unavoidable mapping.

Completion evidence (2026-07-24):

- all 12 supported dtypes, scalar/empty shapes, canonical bytes, malformed
  offsets/JSON, duplicate keys, selectors, mmap aliasing/lifetime, DLPack copy
  isolation, chunked file sinks, and randomized oracle triangulation pass;
- the complete local MSVC suite passes 1,475 tests with 3 documented optional
  skips, and Ruff is clean;
- generated 128 MiB and 1 GiB runs show constant-size SceneIO traced
  allocation/RSS for full and selected mapped reads, with comparable streaming
  write throughput to `safetensors.numpy`;
- Linux instrumentation and Linux/macOS wheel validation remain pending until
  the user authorizes the branch push and remote workflows.

#### G2.2 COLMAP database — complete locally

Implementation:

- Vendor or statically build the public-domain SQLite amalgamation.
- Add `FeatureSet` and `MatchGraph` mappings for cameras, images, keypoints,
  descriptors, matches, and two-view geometry.
- Preserve COLMAP ids and pair-id encoding.
- Use transactions for writes; a failed write must not leave a partially
  committed database.
- `inspect` reads schema/version, row counts, descriptor dimensions, and image
  metadata without materializing blobs.
- Partial API selects one image's features or one image pair's matches.

Oracle:

- `sqlite3` plus pycolmap/test-side SQL queries.

Verification:

- SceneIO/oracle bidirectional database compatibility;
- keypoint layouts, descriptor widths, empty images, sparse ids, pair ordering,
  and every geometry matrix field;
- transaction rollback on a deliberately rejected record;
- database opened read-only for reads and released after exceptions;
- large BLOB count/size validation before allocation.

Benchmark:

- bulk feature/match insertion, one-image read, one-pair read, and full scan;
- compare prepared statements/transactions against the test-side reference.

Completion evidence (2026-07-24):

- pinned public-domain SQLite 3.53.4 is compiled privately with the extension;
  the source archive SHA3-256, amalgamation hash, release id, and local compile
  options are recorded in `third_party/sqlite/COMMIT.txt`;
- `FeatureSet`, `MatchGraph`, and `ColmapDatabase` preserve sparse ids,
  2/4/6-column keypoints, descriptor metadata, absent-versus-empty rows,
  ragged raw/verified matches, exact COLMAP pair ids, F/E/H/config, and
  optional relative pose with owner-safe zero-copy views;
- native read-only full/image/pair paths, transactional replacement writes,
  SQL-only inspection, public detection/capabilities, and the NumPy-only wheel
  smoke pass locally;
- 45 focused cases pass on MSVC with one POSIX-only literal-path case skipped;
  they include independent stdlib `sqlite3` and pycolmap 4.1.1 compatibility,
  20 randomized exact round trips, malformed schema/BLOB/index bounds,
  duplicate rows, rollback, file-lock/handle release, Unicode paths, and
  post-close array lifetime;
- the 9.65 MB five-run fixture measured 178 MB/s transactional write,
  1,405 MB/s full read, 0.808 ms inspection, and 0.525/0.421 ms image/pair
  selection; inspection and selectors remain below 0.05 MB traced Python
  allocation;
- manual memory-safety, format-correctness, and test-soundness review fixed
  ownerless optional-array views, partial-statement cleanup, new-file rollback
  cleanup, literal-path/URI ambiguity, partial duplicate-row acceptance,
  endpoint/index validation, and UTF-8 filesystem handling. Fable remains
  unavailable locally; Linux instrumentation and Linux/macOS wheel validation
  remain user-gated remote actions.

#### G2.3 PTS, generic point PLY, and PCD complete locally

PTS implementation:

- Add `pts` as a distinct text format with an optional/required count-header
  policy chosen from documented dialect fixtures. Validate the declared count,
  define supported XYZ/intensity/RGB columns, and reuse the fast numeric parser
  without making `xyz` accept ambiguous one-column rows.

PTS completion evidence (2026-07-24):

- mandatory decimal count headers and XYZ/XYZI/XYZRGB/XYZIRGB rows pass
  independent bidirectional parity, canonical-byte, count-mismatch, malformed
  input, and 100-case mutation tests;
- mmap/bytes results and 1-lane/8-lane output are bit-identical; partial ranges
  equal full-read slices and remain bounded in traced allocation;
- the complete local MSVC suite passes 1,507 tests with 3 documented optional
  skips, and Ruff is clean;
- the generated 100,000-point benchmark shows zero encoded-size traced
  allocation on mmap/sink paths, header inspection about 282x faster than full
  parsing, and the bounded middle range about 1.85x faster;
- Linux instrumentation and Linux/macOS wheel validation remain pending until
  the user authorizes the branch push and remote workflows.

PCD completion:

- PCD 0.7 ASCII, little-endian binary, and LZF `binary_compressed` map required
  x/y/z plus optional normals, packed RGB, and intensity into `PointCloud`.
- The record now carries optional organized width/height and
  tx/ty/tz/qw/qx/qy/qz viewpoint metadata; older point codecs retain implicit
  `(N,1)` plus identity defaults and refuse PCD-only metadata on write.
- Header-only inspection validates schema and file extents without decoding
  payloads. Uncompressed binary point ranges allocate only the selected rows;
  ASCII and compressed ranges reject explicitly.
- Public binary sinks stream fixed-record chunks rather than materializing a
  full native output buffer. Compressed writes retain the unavoidable
  field-major transform and LZF buffer.

Oracles:

- independent PTS/PLY/PCD parsers plus Open3D in test extras. `plyfile` is
  deliberately excluded: its current GPLv3 license violates the project's
  permissive-license-only constraint.

Verification:

- organized clouds, every PCD scalar field type, packed RGB encodings, field
  ordering, malformed counts/sizes, and LZF literal/back-reference bounds;
- PTS declared-count mismatch, missing count, supported column layouts, and
  canonical writer header;
- writer refusal when the selected output format cannot represent a record
  field.

Benchmark:

- PCD ASCII/binary/LZF encode and decode throughput;
- header inspection, mmap and sink allocation, and point-range memory versus
  full decode.

#### G2.4 Small reconstruction, depth, calibration, and splat formats

Land one codec per green commit:

| Format | Record | Implementation focus | Oracle |
|---|---|---|---|
| BAL — complete locally | `Reconstruction` | camera/point/observation text with a pinned canonical writer | UW specification + independent parser |
| EuRoC state CSV — complete locally | `StateTrajectory` | timestamps, pose, velocity and biases with no field loss | independent CSV parser |
| DMB — complete locally | `DepthMap` | dimensions/type header, float payload, scale/unit metadata | independent NumPy parser |
| Typed PFM/PNG/EXR depth — complete locally | `DepthMap` | explicit scale, unit, invalid-value and confidence semantics layered over existing payload codecs | numpy/Pillow/OpenEXR |
| Typed FLO flow — complete locally | `FlowField` | preserve component, axis, unit, row-order, and unknown-value semantics rather than returning an untagged ndarray | independent numpy parser |
| OpenCV YAML/XML — complete locally | `Camera`/`CameraRig` | matrices, distortion models, explicit model mapping | OpenCV test extra |
| ROS `camera_info` — complete locally | `Camera` | K/D/R/P and distortion model | independent YAML parser |
| Kalibr YAML — complete locally | `CameraRig` | chained extrinsics, camera models, time offsets | independent YAML parser |
| g2o — complete locally | `PoseGraph` | vertices, typed edges, information matrices | independent parser plus generated goldens |
| PlayCanvas SOG v2 — complete locally | `GaussianCloud` | clustered/quantized fields, explicit lossy metadata | pinned reference loader plus independent oracle |
| KSplat v0.1 — complete locally | `GaussianCloud` | levels 0–2, multi-section reads, guarded deterministic single-section writer | pinned loader vectors plus independent struct/NumPy oracle |
| BMP/TGA — complete locally | `Image` | bounded existing-stb decode plus deterministic writers | Pillow + format specifications |

Typed depth/flow adapter contract and landing sequence:

1. **FlowField record — complete locally**
   - Add a compiled SoA record with one contiguous `(H,W,2)` float32 vector
     buffer and immutable semantic metadata:
     `component_order="uv"`, `u_axis="right"`, `v_axis="down"`,
     `row_order="top_to_bottom"`, `unit="pixels"`, and
     `invalid_policy="component_abs_gt_1e9"`.
   - Expose a zero-copy NumPy view whose base retains the record. The record
     owns typed-read output; the existing raw `read_flo_view` remains the
     mmap-backed path and remains source-compatible.
   - Guard exact shape, C contiguity, dtype, checked `H*W*2` arithmetic, and
     the closed metadata vocabulary before construction.
2. **Typed FLO adapter — complete locally**
   - Add `read_flow(path, *, format=None)` and
     `write_flow(flow, path, *, format=None)` as explicit public adapters.
     Existing `read(path)` and `_core.read_flo*` continue returning an ndarray,
     and existing writer bytes cannot change.
   - Copy the raw decoded values bit-for-bit into `FlowField`; do not replace
     NaN, infinity, or Middlebury's unknown-flow sentinel.
   - The writer accepts only the canonical `.flo` conventions above and
     rejects any future `FlowField` convention that `.flo` cannot represent.
3. **Depth encoding contract — complete locally**
   - Add a frozen public `DepthEncoding` value containing `unit`,
     `scale_to_meters`, `invalid_policy`, and optional EXR channel name.
   - Add `read_depth(path, *, encoding, format=None)` and
     `write_depth(depth, path, *, encoding, format=None)`. The encoding is
     mandatory because PFM, PNG, and EXR do not serialize all `DepthMap`
     semantics. A write verifies that `DepthMap` metadata equals `encoding`;
     a later read must be given the same encoding. No sidecar is implied.
   - Keep `sceneio.read`/`write` and every existing raw codec unchanged.
     Typed adapters are additive and never change registry dispatch by
     extension.
4. **PFM depth — complete locally**
   - Accept only one-channel float32 PFM payloads. Preserve raw stored values,
     including signed zero and non-finite bit patterns, after the format's
     required bottom-to-top row transform.
   - Extend typed inspection to expose the signed third header token. The
     original PFM definition uses its sign for endian selection and does not
     portably encode depth units in its magnitude, so the supported typed
     subset requires absolute magnitude `1.0`. `DepthEncoding` remains the
     external semantic contract; the existing and typed writers both emit
     `-1.0` on little-endian output.
   - Reject RGB PFM, ambiguous non-unit header magnitudes, and
     confidence-bearing `DepthMap` writes. Every current depth unit and invalid
     policy remains available through the required external encoding because
     the float payload is passed through rather than normalized.
5. **PNG depth — complete locally**
   - Accept only grayscale 16-bit PNG for typed depth. Widen uint16 samples to
     float32 exactly and record the supplied scale; never divide or multiply
     samples during decode.
   - The writer requires every stored float32 sample to be an exact integer in
     `[0,65535]`, rejects confidence and unsupported metadata, and emits the
     same deterministic 16-bit PNG bytes as the existing image writer.
   - Pin named test profiles for TUM (`scale_to_meters=1/5000`, zero invalid)
     and ScanNet/millimeter depth (`scale_to_meters=0.001`, zero invalid)
     without making a profile implicit.
6. **EXR depth — complete locally**
   - In the first typed subset, accept an exactly one-channel EXR whose header
     name matches the explicitly selected channel. Do not infer a depth
     channel or silently select one from a multi-channel/AOV file.
   - Preserve float32 values without color conversion or transfer-function
     changes. A dedicated typed writer emits the requested scalar channel name
     while the existing raw one-channel writer continues to emit `Y`. Reject
     confidence and multi-channel selection until a documented mapping can
     round-trip them without ambiguity.
7. **Public inspection and partial reads**
   - `inspect_depth` overlays the caller-supplied encoding on the existing
     payload inspection and confirms the payload is in the supported typed
     subset without allocating the full raster.
   - PFM/PNG/EXR typed windows are advertised only where the underlying codec
     can return a bounded window. Otherwise the typed API raises a normalized
     unsupported-selector error rather than decoding the whole image
     implicitly.

Verification for this slice:

- hand-computable convention fixtures for row order, axes, scale, invalid
  values, and EXR channel selection;
- typed result equals the existing raw decode bit-for-bit before metadata is
  attached;
- SceneIO-written files reopen in NumPy/Pillow/OpenEXR or the independent FLO
  parser, and oracle-written files produce the same values in SceneIO;
- all supported special float32 bit patterns, zero/max uint16 values, empty or
  malformed headers, wrong channel count/dtype, non-integral PNG writes,
  mismatched encoding metadata, and confidence rejection;
- bytes versus mmap/path equality, deterministic buffer versus file-sink
  bytes, record/view lifetime after `gc.collect()`, DLPack isolation, and
  mutation isolation;
- generated 100 MiB-class fixtures proving mmap input avoids a whole-file
  Python `bytes`, inspection remains header-bounded, and sink output avoids an
  output-sized Python `bytes`;
- registry-wide E2E, capability snapshot, randomized valid/malformed
  differential cases, and unchanged raw-codec golden bytes.

Validation for this slice:

- local editable MSVC rebuild, compiled-symbol smoke, affected suites, full
  suite, Ruff, `git diff --check`, and the all-codec benchmark guard;
- instrumented Linux full suite and minimal/full-feature configurations;
- cp312-abi3 manylinux2014 x86-64, macOS arm64, and Windows amd64 wheel build,
  clean-wheel import, typed adapter smoke, and original-codec smoke;
- no new runtime Python dependency or external shared-library dependency.

Land this slice as five independently green commits: `FlowField`, typed FLO,
typed PFM depth, typed PNG depth, then typed EXR depth plus public integration.
Each commit records its benchmark delta and the three review lenses before the
next one starts.

FlowField record completion evidence (2026-07-24):

- the compiled record owns one exact float32 `(H,W,2)` copy and exposes
  owner-retaining zero-copy NumPy views; direct, derived, and DLPack views
  remain valid after the record temporary is collected;
- signed zero, infinities, NaN payloads, subnormals, and the Middlebury `1e10`
  sentinel survive bit-for-bit under every declared invalid policy;
- shape, dtype, zero extent, checked element-count arithmetic, metadata
  vocabularies, immutable metadata, non-contiguous input, source mutation
  isolation, and big-endian rejection-or-correctness are pinned;
- the raw FLO codec and public `sceneio.read` behavior are unchanged; the
  record is re-exported through `sceneio.io` and the flat package and included
  in wheel smoke;
- the local MSVC extension rebuild succeeds, the focused record/FLO suite
  passes 40 tests with one documented optional OpenCV skip, and the full suite
  passes 1,627 tests with the same three documented optional skips.

Three-lens FlowField record review:

- **memory/lifetime:** both dimension products are checked before allocation,
  the factory owns its copy, every NumPy view carries the record as owner, and
  large direct/derived/DLPack lifetime tests churn freed-size heap blocks;
- **correctness:** values are never normalized or scrubbed, component and axis
  directions remain independent closed metadata, ambiguous normalized units
  were excluded, and the `.flo` defaults pin UV, +right/+down, top-to-bottom,
  pixels, and per-component absolute threshold semantics;
- **test soundness:** bit patterns are stamped through uint32 rather than
  produced by floating arithmetic, mutation proves pointer aliasing, source
  mutation proves ownership isolation, and the unchanged raw FLO suite guards
  source compatibility.

No unresolved finding remains in the local FlowField record review.
Instrumented Linux and Linux/macOS wheel validation remain pending until the
next dependency-wave remote validation authorized by the user.

Typed FLO adapter completion evidence (2026-07-24):

- compiled `read_flo_field` and `write_flo_field` share the established raw
  parser/encoder, while public `read_flow`, `write_flow`, and `inspect_flow`
  add mmap input, direct native sink output, normalized errors, and fixed
  convention metadata without changing `sceneio.read(.flo)` or raw bytes;
- raw, typed, and independent NumPy paths are bit-identical across signed
  zero, infinities, NaN payloads, subnormals, both `1e10` sentinel signs,
  75 randomized rasters, and every truncated prefix of a canonical file;
- each noncanonical component, axis, row, unit, and invalid convention is
  rejected before the destination opens; forced seven-byte native short writes
  reproduce the canonical raw/oracle bytes;
- a generated 32 MiB file keeps typed mmap read and sink write below one eighth
  of encoded size in traced Python allocation, a generated 256 MiB sparse file
  keeps typed inspection below 1 MiB, and the owning result remains usable
  after the source path is deleted;
- the five-run all-codec harness reports about 2,864 MB/s typed read,
  2,253 MB/s typed sink write, 0.038 ms typed inspection, and
  0.011/0.001 MB traced read/write peaks; all existing O4/O5 directional and
  memory guards pass;
- the final local MSVC suite passes 1,648 tests with 3 documented optional
  skips, Ruff and `git diff --check` are clean, and a clean Python 3.12
  environment containing only NumPy imports the locally built cp312-abi3
  Windows wheel and passes typed read/write/inspect plus unchanged raw-read
  smoke.

Three-lens typed FLO review:

- **memory/lifetime:** read input remains pinned for the entire GIL-released
  copy, no source pointer escapes, output size arithmetic includes header and
  payload overflow checks, typed records own their values, and sink callbacks
  receive only the finished native buffer;
- **correctness:** typed and raw paths use one parser/encoder, writer guards
  every convention the file cannot serialize, raw APIs retain ndarray/mapped
  behavior, and special values remain raw rather than being classified or
  rewritten;
- **test soundness:** the oracle uses only `struct` and NumPy, hand-built bytes
  pin UV and row order independently of SceneIO, randomized cases triangulate
  all three paths, complete-prefix truncation exercises native bounds, and
  mmap/sparse/sink tests measure the public optimized adapters.

No unresolved finding remains in the local typed FLO review. The local
cp312-abi3 Windows wheel is validated; instrumented Linux and Linux/macOS wheel
validation remain pending until the user-authorized remote dependency-wave run.

Typed PFM depth completion evidence (2026-07-24):

- frozen `DepthEncoding` validates the complete `DepthMap` unit/scale/invalid
  vocabulary and an optional nonempty, NUL-free channel name; PFM requires the
  channel name to be absent;
- compiled full/window readers accept only scalar float32 PFM with an exact
  unit-magnitude signed header token, preserve bottom-to-top row conversion and
  every float bit, and attach external encoding metadata without rescaling or
  invalid-value scrubbing;
- typed writers reject metadata mismatch and confidence before the lazy
  destination opens, emit the same deterministic bytes as the unchanged raw
  writer and independent parser, and handle deterministic seven-byte native
  short writes;
- little- and big-endian inputs, hand-computable row/scale fixtures, all unit
  and invalid policies, signed zeros, infinities, NaN payloads, subnormals,
  every truncated prefix, 100 payload mutations, and 75 randomized bit-pattern
  rasters triangulate typed, raw, and independent paths;
- a 32 MiB full read/write avoids an encoded-size Python allocation, and
  inspection plus an 8x8 window over a generated 128 MiB sparse PFM stays below
  1 MiB traced allocation;
- the five-run all-codec harness reports about 2,026 MB/s typed read,
  1,955 MB/s typed sink write, 0.056 ms typed inspection, and
  0.011/0.001 MB traced read/write peaks; all O4/O5 directional and memory
  guards pass;
- the final local MSVC suite passes 1,739 tests with 3 documented optional
  skips, Ruff and `git diff --check` are clean, the parsed cibuildwheel smoke
  command passes, and a clean Python 3.12 environment containing only NumPy
  passes typed full/window read, sink write, inspect, and unchanged raw-read
  smoke from the locally built cp312-abi3 Windows wheel.

Three-lens typed PFM review:

- **memory/lifetime:** header-derived products are checked before pointer
  arithmetic or allocation; `ByteView` pins the exporter throughout
  GIL-released row copies; selected-window allocation is proportional only to
  the requested region; returned records own their values; no source pointer
  escapes;
- **correctness:** one parser and one encoder serve raw and typed paths, the
  signed PFM header token controls endian only, its magnitude must be exactly
  one for typed depth, values are never transformed semantically, and external
  metadata plus confidence guards prevent unrepresentable writes;
- **test soundness:** the oracle uses only ASCII header construction and NumPy
  endian dtypes, raw compatibility is asserted alongside every typed
  restriction, special values originate as uint32 bit patterns, and sparse,
  mmap-fallback, short-write, randomized, lifetime, and public API tests all
  exercise the optimized paths.

No unresolved finding remains in the local typed PFM review. The local
cp312-abi3 Windows wheel is validated; instrumented Linux and Linux/macOS wheel
validation remain pending until the next user-authorized remote dependency-wave
run.

Typed PNG depth completion evidence (2026-07-24):

- compiled typed readers accept only grayscale uint16 PNG, exactly widen every
  sample to float32, preserve top-to-bottom rows, and attach the required
  external encoding without multiplying, dividing, or classifying values;
- typed writers verify encoding equality and absent confidence, reject
  non-finite, fractional, negative, above-65535, and negative-zero samples, and
  produce the same deterministic bytes as the existing Image writer and pypng
  oracle;
- TUM 1/5000 and ScanNet millimeter profiles, zero/max samples, interlaced
  input, raw grayscale/RGB/RGBA/palette compatibility, wrong modes, mmap
  fallback, mapping/result lifetime, every truncated prefix, 100 mutations,
  50 randomized rasters, and one-vs-many lane identity are pinned;
- compressed PNG exposes no false typed window: a requested selector raises
  before the decoder runs, while typed inspection validates the supported
  subset and reports the decoded float32 dtype plus stored uint16 dtype;
- generated 16 MiB encoded-size read/write fixtures avoid a whole-file Python
  allocation and multi-megabyte inspection remains below 1 MiB traced
  allocation;
- the five-run all-codec harness reports about 979 MB/s typed read,
  193 MB/s typed sink write, 0.052 ms typed inspection, and 0.011/0.001 MB
  traced read/write peaks; all O4/O5 directional and memory guards pass;
- the final local MSVC suite passes 1,787 tests with 3 documented optional
  skips, Ruff and `git diff --check` are clean, the cross-shell wheel smoke is
  now a packaged numpy-only private module, and a clean Python 3.12 environment
  passes it against the locally built cp312-abi3 Windows wheel.

Three-lens typed PNG review:

- **memory/lifetime:** lodepng state and malloc buffers remain RAII-guarded;
  dimensions are capped before typed conversion allocation; input exporters
  remain pinned across decode; bounded worker exceptions are joined and
  rethrown; returned `DepthMap` storage owns all widened values;
- **correctness:** typed mode checks occur against the decoded source mode,
  widening is exact for all uint16 values, representability is checked before
  narrowing, negative zero is rejected rather than silently canonicalized, and
  raw Image behavior and deterministic bytes remain unchanged;
- **test soundness:** pypng independently reads and writes big-endian uint16
  samples, hand-computable profiles prove no implicit rescale, wrong raw modes
  remain accepted by the raw API while typed calls reject them, and public
  mmap/sink/inspect, short-write, mutation, lane, and lifetime paths are
  exercised directly.

No unresolved finding remains in the local typed PNG review. The local
cp312-abi3 Windows wheel is validated; instrumented Linux and Linux/macOS wheel
validation remain pending until the next user-authorized remote dependency-wave
run.

Typed scalar EXR depth completion evidence (2026-07-24):

- compiled `read_exr_depth` validates the exact selected channel in the same
  native header/decode pass that returns its pixels, accepts scalar HALF/FLOAT,
  widens through the unchanged raw path, and moves the decoded float32 buffer
  into an owning `DepthMap` without rescaling or classifying values;
- the dedicated writer requires matching external metadata and absent
  confidence, emits an exact caller-selected UTF-8 channel name up to 255 bytes,
  and shares the raw writer implementation; typed channel `Y` is byte-identical
  to the unchanged raw scalar writer;
- OpenEXR bidirectional parity covers FLOAT bit patterns (signed zero,
  subnormals, infinities, and NaN payloads), exact HALF widening, five lossless
  compression modes, named/layered channels, 50 randomized rasters, every
  truncated prefix, 100 mutations, dimension limits, and multipart/deep/tiled/
  UINT/multi-channel rejection;
- public read/write/inspect, magic detection, extensionless explicit format,
  mmap fallback, source-mutation isolation, mapping/result lifetime, forced
  short writes, pre-truncation writer guards, capability metadata, and packaged
  wheel smoke are pinned by 42 typed-EXR cases;
- compressed EXR advertises no false typed window; inspection validates the
  scalar channel and stored HALF/FLOAT dtype from bounded header reads and
  rejects non-UTF-8 stored names that the native typed API cannot select;
- generated 32 MiB-class read/write fixtures avoid encoded-size Python
  allocations and inspection remains below 1 MiB traced allocation;
- the accepted five-run all-codec harness reports about 1,341 MB/s typed read,
  304 MB/s typed sink write, 0.057 ms typed inspection, and 0.011/0.001 MB
  traced read/write peaks; all retained O4/O5 directional and memory guards
  pass;
- the final local MSVC suite passes 1,829 tests with 3 documented optional
  skips, Ruff and `git diff --check` are clean, and a clean Python 3.12
  environment containing only NumPy passes the packaged smoke against the
  locally built cp312-abi3 Windows wheel; its 34 entries contain no headers,
  build tree, or static libraries.

Three-lens typed EXR review:

- **memory/lifetime:** TinyEXR headers, images, errors, and encoded buffers use
  RAII; dimensions and channel tables are validated before allocation or
  indexing; one `ByteView` pins the exporter through channel validation and
  decode; returned depth storage owns its values; no source pointer escapes;
- **correctness:** channel validation and raster decode use one parse, removing
  the review-found mutable-backing-store TOCTOU; typed and raw writers share one
  implementation, raw scalar output remains `Y`, HALF/FLOAT bits are never
  color-converted or rescaled, and every unrepresentable field is rejected;
- **test soundness:** OpenEXR is independent of TinyEXR, explicit uint32 bit
  patterns pin NaN payloads and signed zero, typed/raw/oracle paths are
  triangulated, hand-patched headers break round-trip symmetry, and public
  mmap/sink/inspect/lifetime/memory paths are exercised directly.

No unresolved finding remains in the local typed EXR review. The local
cp312-abi3 Windows wheel is validated; instrumented Linux and Linux/macOS wheel
validation remain pending until the next user-authorized remote dependency-wave
run.

DMB completion evidence (2026-07-24):

- independent little-endian oracle parity covers special float32 values,
  canonical bytes, randomized values, and 100 single-byte mutations;
- reads enforce scalar type/channels, positive bounded dimensions, and exact
  payload length; writers reject confidence and unrepresentable scale/unit or
  invalid-value conventions;
- mmap and bytes decodes are bit-identical, direct file sinks are
  byte-identical under forced short writes, and bounded windows equal full-read
  `DepthMap` slices while preserving metadata;
- generated 64 MiB sparse-file inspection and 8x8 window reads stay below
  1 MiB traced allocation;
- the all-codec suite, benchmark evidence, and local MSVC result are recorded
  with the codec commit; Linux instrumentation and Linux/macOS wheel validation
  remain pending until the user authorizes the remote workflows.

Three-lens DMB review:

- **memory/lifetime:** dimensions and total pixels are capped before allocation,
  exact payload size is checked before pointer arithmetic, `ByteView` remains
  alive for every native read, returned `DepthMap` buffers own their data, no
  pointer escapes the mapping, and sink callbacks run with the GIL held;
- **format correctness:** header order, signed-field rejection, fixed
  little-endian encoding, scalar-only channels, row-major order, special
  float32 bit patterns, exact trailing-byte policy, and unknown-scale/
  zero-invalid metadata are pinned;
- **test soundness:** the oracle uses only `struct` and NumPy, writer bytes are
  consumed independently, public and compiled paths are both exercised,
  randomized mutations compare outcomes, and large sparse-file assertions
  measure inspection/window allocation rather than a mirrored implementation.

No unresolved finding remains in the local review.

BAL completion evidence (2026-07-24):

- the grammar and camera parameter order are pinned to the University of
  Washington BAL description and Ceres reference reader: three header counts,
  zero-based observation indices, four fields per observation, nine
  angle-axis/translation/intrinsic values per camera, then XYZ triples;
- an independent Python parser/writer and independent Rodrigues/projection math
  cover hand-computable fixtures, zero- and pi-angle branches, 50 randomized
  valid problems, deterministic 17-digit output, and malformed counts, indices,
  numeric tokens, trailing data, and oversized tokens;
- BAL's centered, +Y-up, -Z-forward camera convention is mapped explicitly
  through `F=diag(1,-1,-1)` and pinned by a projected-point test rather than
  only a round trip;
- bytes and mmap reads are record-identical and the decoded reconstruction
  remains valid after its mapping closes; the 64 MiB sparse inspection fixture
  stays below 1 MiB traced allocation and the large direct sink is byte-identical
  under forced short writes while avoiding an output-sized Python `bytes`;
- the writer validates the complete canonical subset before opening the file:
  contiguous one-based IDs, one zero-dimension RADIAL camera per image,
  zero principal point, empty names, zero point colors, sentinel point errors,
  and an exact one-to-one observation/track relation.
- final local MSVC validation passed 1,567 tests with 3 documented optional
  skips, Ruff and `git diff --check` are clean, and the five-run 27-codec
  O4/O5 throughput and memory regression guard passed.

Three-lens BAL review:

- **memory/lifetime:** bounded token lengths, header-derived token budgets, and
  explicit `size_t` product limits precede allocations; signed counts and
  indices are checked before casts;
  `ByteView` remains scoped to parsing; returned reconstruction arrays own their
  memory; no mapping pointer escapes; the complete sink plan is validated
  before the first write and callbacks run with the GIL held;
- **format correctness:** primary-source grammar, zero-based indexing, all nine
  camera parameters, centered observations, the camera-frame transform,
  canonical quaternion sign, small-angle and pi rotations, deterministic
  numeric text, unsupported field guards, and the exact observation/track
  relation are independently pinned;
- **test soundness:** the oracle does not call the compiled codec, projection
  tests break read/write symmetry, randomized cases include observation order
  independent of point order, malformed cases exercise every bounded scanner
  edge, and mmap/sparse-file/short-sink tests measure the optimized public paths.

No unresolved finding remains in the local BAL review. Linux instrumentation
and Linux/macOS wheel validation remain pending until the user authorizes the
remote workflows.

BMP/TGA completion evidence (2026-07-24):

- BMP support covers Windows 40/56/108/124-byte DIB headers, BI_RGB and
  BI_BITFIELDS, 1/4/8-bit palettes, packed 16-bit color, 24-bit RGB, explicit
  32-bit alpha bitfields, and both top-down and bottom-up rows; 32-bit BI_RGB's
  specification-defined unused high byte is ignored;
- TGA support covers grayscale/RGB/RGBA and zero-origin palettes, raw and RLE
  storage, packed 15/16-bit color, image IDs, and top/bottom origins;
  right-to-left/interleaved layouts, nonzero palette origins, and
  grayscale+alpha are explicitly refused because the pinned decoder or
  `Image` record cannot preserve them;
- independent Pillow parity covers every supported channel/orientation/storage
  family plus 40 randomized image cases; manual BMP/TGA builders independently
  pin row order, 16-bit packing, bitfield masks, and exact header metadata;
- every truncated prefix of canonical BMP and TGA output rejects, malformed
  palettes/masks/RLE packets reject before stb decode, and both decoded images
  remain valid after their mmap closes;
- generated 64 MiB sparse files keep inspection below 1 MiB traced allocation;
  native writer callbacks stage at most 256 KiB for direct sinks, remain
  byte-identical under forced short writes, and avoid output-sized Python
  allocations.
- final local MSVC validation passed 1,612 tests with 3 documented optional
  skips, Ruff and `git diff --check` are clean, the wheel smoke command runs,
  and the five-run 29-codec O4/O5 throughput and memory guard passed.

Three-lens BMP/TGA review:

- **memory/lifetime:** dimensions, pixel products, palette extents, BMP row
  spans, and TGA raw/RLE packet spans are bounded before allocation or decode;
  mask widths are capped; stb buffers have RAII ownership; `ByteView` remains
  live through decode; returned `Image` vectors own their pixels; sink callbacks
  reacquire the GIL before bounded file emission and no native pointer escapes;
- **format correctness:** Microsoft DIB orientation/plane/bit-depth/compression
  rules and Truevision type/depth/descriptor rules are pinned; the review found
  and fixed a signed top-down BMP height propagation defect and added explicit
  contiguous, non-overlapping BMP mask validation;
- **test soundness:** Pillow is independent of stb, manual binary builders break
  writer/reader symmetry, randomized dimensions/modes exercise both
  orientations and TGA storage modes, complete-prefix truncation tests the
  preflight rather than the oracle, and public mmap/sink/inspection paths are
  measured directly.

No unresolved finding remains in the local BMP/TGA review. Linux
instrumentation and Linux/macOS wheel validation remain pending until the user
authorizes the remote workflows.

YAML support must use a permissive native parser or a deliberately bounded
format-specific parser; it may not add a runtime Python dependency.
OpenCV XML likewise uses a pinned permissive XML parser or a narrow
format-specific implementation. The YAML and XML paths share one camera-model
mapping test matrix so syntax-specific code cannot change camera semantics.

Exit gate for G2:

- All G2 codecs appear in capabilities and the all-codec E2E sweep.
- Default wheels remain numpy-only and contain no new external shared-library
  dependency.

### G3 — Mesh tier

#### G3.1 Mesh record and generic PLY mesh — complete locally

Generic PLY is the reference codec for validating every `Mesh` buffer:

- polygon boundaries and indices;
- vertex versus corner attributes;
- colors and alpha;
- primitive/material ranges;
- coordinate frame and units.

No implicit triangulation is permitted in the record constructor or PLY codec.

Completion evidence:

- The compiled `Mesh` owns contiguous canonical buffers for positions,
  CSR-style polygon offsets/indices, independent vertex/corner normals, UVs,
  and RGBA, primitive/material ranges, coordinate frame/scale, and a 4×4 local
  transform. Fifty-one record tests cover empty/singleton/ragged domains,
  malformed offsets and indices, mismatched attributes, nonfinite values,
  non-contiguous foreign arrays, zero-copy writable NumPy/DLPack views,
  parent/view lifetime, and explicit copy/pickle rejection.
- `ply_mesh` reads ASCII and binary little/big-endian PLY 1.0 without
  triangulating, merging index domains, or dropping supported attributes. Its
  deterministic binary writer preserves all record fields through documented
  face-list and metadata extensions; unknown elements, properties, and
  SceneIO metadata reject. Schema detection now routes point, Gaussian,
  compressed-Gaussian, and mesh PLY independently of registry order.
- Fifty-five codec tests include independent hand-built ASCII/big-endian
  fixtures, a struct/NumPy writer oracle, twenty randomized meshes, malformed
  aggregate/list/primitive cases, readonly mmap lifetime and mutation
  isolation, direct-sink preservation, and a 105.6 MB generated mmap fixture
  whose traced Python allocation remains below 4 MiB. A deterministic triangle
  file also opens in trimesh 4.12.2 with exact vertices and faces.
- Five-run medians on the 28.0 MB logical fixture are 886 MB/s write,
  325 MB/s in-memory read, and 283 MB/s public mmap read. The direct sink
  reaches 673 MB/s and removes the 30.0 MB output-sized Python allocation;
  mmap removes the matching input allocation. Inspection takes 0.089 ms,
  about 1,110× faster than full decode. The complete 42-codec one-run harness
  finishes without failures.
- Native and public `faces=(start, stop)` reads retain the complete vertex
  domain, slice all face/corner fields, and clip primitive ranges. They are
  bit-exact against independently constructed slices for binary little-endian,
  hand-built ASCII, hand-built big-endian, and twenty randomized meshes.
  A 1/16 selection takes 72.240 ms versus 96.918 ms full decode (1.34×) and
  reduces sampled RSS from 63.4 MB to 42.1 MB. A generated 50.0 MB fixture with
  12.5 million corners in an unselected face stays below 1 MiB traced Python
  allocation and below three-fifths of full-read fresh-process RSS.
- A clean cp312-abi3 Windows wheel contains 36 expected members, leaks no
  headers or native build artifacts, declares only `numpy>=1.26`
  unconditionally, links only standard Python/Windows runtimes, and passes the
  isolated NumPy-only wheel smoke including mesh PLY.
- Manual memory-safety, format-correctness, and test-soundness review found and
  fixed allocation before impossible header-count feasibility checks, an
  unbounded per-face list allocation, uint32 overflow in corner-list and
  primitive-run arithmetic, a missing feasibility check in the partial entry,
  retention of skipped face lists, and silent texture/`obj_info` metadata
  loss. Fable is unavailable locally and remote instrumented/wheel validation
  remains user-gated.

#### G3.2 OBJ/MTL — complete locally

Implementation:

- Pin and vendor TinyObjLoader, or its C implementation, at an audited release
  commit with license and provenance recorded.
- Preserve independent position/normal/UV indices as corner attributes.
- Define the supported MTL subset against `MaterialSet` before coding,
  including texture path, UV set, and scalar-factor behavior.
- External file resolution stays relative to the OBJ directory and never
  changes process working directory.
- Writer groups primitives/materials deterministically.
- Unsupported free-form surfaces, line primitives, or material fields are
  rejected or documented as intentionally ignored only when they carry no
  mesh fidelity represented by `Mesh`.

Oracle:

- trimesh and TinyObjLoader's fixtures in tests.

Completion evidence:

- `MaterialSet` stores unique UTF-8 material names, linear base/emissive
  factors, metallic/roughness, alpha mode/cutoff, and a separate texture-binding
  domain with semantic, relative path, UV-set, wrap, and filter metadata.
  Numeric fields expose writable zero-copy views while string offset/value
  tables remain read-only; 51 record tests cover shape/range/enumeration,
  duplicate binding, lifetime, and mutation/revalidation behavior.
- TinyObjLoader is pinned at
  `45636bdcef1a4fec140346b90c0b50bf0bc3e23b`; its MIT, bundled ISC, and embedded
  fast_float MIT/Apache-2.0/BSL-1.0 notices are recorded. The embedded
  fast_float is translation-unit namespaced so it cannot collide with
  SceneIO's separately pinned version.
- `obj` preserves polygon boundaries, negative and independent indices,
  vertex- versus corner-domain normals/UVs, exact RGB8, object/group runs,
  smoothing groups, material assignment, PBR MTL factors, and the supported
  texture-map subset. Unknown or unrepresentable directives, material fields,
  mixed domains, free-form/line/point primitives, alpha cutoff/mask, texture
  options, and implicit triangulation reject explicitly.
- The public multi-file adapter maps OBJ and its single relative MTL without
  changing the process working directory. Paired direct-sink writes stage both
  files and publish the MTL before the OBJ entry point, restoring prior
  destinations after a failed install. Inspection counts geometry, materials,
  and textures without constructing a `Mesh` or retaining per-face metadata.
- Sixty-one codec tests include hand-built polygon/negative-index and MTL
  fixtures, deterministic core/public round trips, Trimesh cross-consumption,
  mmap lifetime and mutation isolation, malformed/fidelity guards, randomized
  vertex/corner meshes, scheduled bytes-versus-mmap mutation fuzzing, large
  traced-allocation checks, non-truncating paired output, and comma-decimal
  process-locale independence.
- On the 14.7 MB canonical fixture, five-run local MSVC medians are 20.4 MB/s
  write, 18.5 MB/s in-memory decode, 12.7 MB/s public mmap decode, and
  544.790 ms inspection (2.12× faster than full decode). Mmap and direct-sink
  traced allocations fall from 53.83 MB to 0.013/0.005 MB. Replacing
  per-scalar stream construction with bounded canonical float appends under an
  explicit C numeric locale improved deterministic write throughput 2.78×
  without changing output semantics.
- Final native-lifetime, format-correctness, and test-soundness review found
  and fixed private fast-float namespace collisions, exact RGB8 and
  alpha-cutoff fidelity gaps, texture-row reordering, paired-output rollback,
  process-locale-dependent numeric output, and test-collection retention of
  compiled records. No local review finding remains; Fable is unavailable
  locally, and the remote instrumented/wheel matrix remains user-gated.

#### G3.3 STL and OFF — complete locally

- STL: binary and ASCII, triangle-only write guard, facet-normal preservation
  policy, and robust binary/ASCII detection.
- OFF: polygonal OFF plus explicitly selected color variants; preserve polygon
  boundaries.
- Oracle with trimesh and independent minimal parsers.

Completion evidence:

- STL accepts exact-length binary little-endian records and a strict
  case-insensitive ASCII grammar. Exact binary extent wins even when the
  80-byte header begins with `solid`, and nonzero facet attribute words reject
  because the competing color extensions are ambiguous.
- STL decodes each stored corner to a distinct `Mesh` vertex, preserving the
  format's lack of indexed connectivity. Facet normals become three
  bit-identical corner normals; an entirely zero normal stream is canonical
  absence. The writer accepts only canonical triangle soup and rejects shared
  topology, polygons, vertex normals, nonuniform facet normals, colors, UVs,
  materials, primitive segmentation, and coordinate metadata.
- OFF preserves the complete indexed vertex domain and polygon offsets for
  `OFF`, `NOFF`, `COFF`, `CNOFF`, `STOFF`, `STNOFF`, `STCOFF`, and
  `STCNOFF`. Vertex normals, UVs, and exact RGBA8 colors round-trip. Binary
  OFF, homogeneous/n-dimensional coordinates, face colors, corner-domain
  attributes, and unrepresentable metadata reject explicitly.
- Both codecs accept read-only contiguous buffers, use mmap-backed public
  reads, stream deterministic output through bounded direct-sink chunks,
  inspect without constructing record arrays, and implement bounded face
  selection. OFF selections retain the complete vertex domain; STL selections
  return canonical local triangle soup.
- Seventy-seven codec tests use independent `struct` and token parsers,
  hand-built malformed fixtures, and
  trimesh cross-consumption cover binary/ASCII detection, all OFF variants,
  polygon preservation, writer guards, read-only mmap lifetime, public
  detection/inspection/partial reads, sink byte identity, numeric-locale
  independence, and malformed count/index/extent handling.
- Representative five-run local MSVC medians measured STL at 1,021 MB/s write,
  1,166 MB/s decode, and 935 MB/s public mmap decode; OFF measured 206, 442,
  and 396 MB/s respectively. Traced mmap and sink allocation fall from the
  5.57 MB STL and 7.56 MB OFF file sizes to about 0.01 MB or less. Inspection
  is 3.67x/1.98x faster and 1/16 face selection is 3.26x/1.21x faster.
- Manual native-lifetime, format-correctness, and test-soundness review added
  impossible-count extent checks before OFF allocation and checked STL count
  arithmetic, then caught and closed an OFF writer/reader mismatch for
  polygons whose emitted record would exceed the parser's 1 MiB line cap.
  Fable is unavailable locally; the remote instrumented/wheel matrix remains
  user-gated.

#### G3.4 glTF/GLB core — complete locally

Implementation:

- Pinned MIT cgltf 1.15 provides glTF 2.0 JSON/GLB parsing, validation, and
  deterministic JSON writing; SceneIO owns checked binary packing.
- `MeshScene` retains ordered source meshes/primitives, a shared `MaterialSet`,
  node hierarchy and row-major local transforms, scenes/roots/names, and the
  default scene rather than flattening the document.
- Readers cover external mapped buffers, base64 data buffers, GLB BIN,
  bufferViews/strides, dense and sparse accessors, u8/u16/u32 indices,
  normalized UV/color attributes, TRIANGLES, node matrix/TRS transforms,
  multiple scenes, metallic-roughness factors, URI image references, and
  sampler metadata.
- Inspect parses structural metadata without loading external payloads.
  `mesh_id` and flattened `primitive_id` partial reads validate the whole
  container while materializing only the selected primitive arrays.
- The paired `.gltf` + `.bin` writer encodes once into temporary native sinks
  and publishes both atomically; GLB uses the standard single-file native sink.
- Non-triangles, corner attributes, additional UV sets, unrepresentable color
  encodings, embedded bufferView images, double-sided/extended materials,
  skins, morph targets, animation, cameras, lights, extensions, Draco, and
  meshopt reject clearly.

Oracle:

- Hand-built binary/JSON fixtures break writer/reader symmetry; pygltflib 1.16
  and trimesh 4 independently consume both SceneIO writers.

Local verification:

- 100 focused record/material/glTF cases pass, including external and data URI
  buffers, stride/normalization/sparse accessors, duplicate/empty material
  names, hierarchy/TRS, bytes-versus-memoryview, lifetime after file removal,
  sink identity and rollback, numeric-locale independence, missing resources,
  unsupported features, random truncation, and a generated 3.6 MB external
  buffer whose public read stays below one-third of the payload in traced
  Python allocation.
- The 47-codec one-run harness completes. On the 13.2/14.7 MB canonical
  glTF/GLB fixtures, five-run local MSVC medians measure 904/948 MB/s core
  decode and 739/751 MB/s public mmap decode. Mmap removes 12.0/13.3 MB of
  traced Python input allocation; native sinks remove the same output-sized
  allocation. Inspection is 220x/201x faster, and one-of-four primitive reads
  are 4.29x/3.87x faster with about one-fifth the full-read RSS growth.
- Cross-platform wheel and instrumented validation remain part of the
  user-gated remote matrix; Draco remains separately policy-gated.
- A staged source distribution contains the codec, record, Python adapter,
  and byte-exact cgltf headers/license/provenance. Building that archive from
  a short Windows path produces the ABI3 wheel; an isolated environment with
  only NumPy passes `_wheel_smoke`, and archive inspection finds one native
  extension with no installed dependency headers, libraries, or vendor files.
- Manual native-lifetime, format-correctness, and test-soundness review found
  and closed recursive hierarchy validation on deep valid scenes, unchecked
  output-size arithmetic, divergent inspect/read accessor validation,
  unordered sparse destinations, duplicate writer work in the paired sink,
  and locale-dependent JSON float arrays. No local review finding remains;
  Fable is unavailable locally, and the remote instrumented/wheel matrix
  remains user-gated.

Validation for G3:

- Windows/macOS/manylinux builds with the vendored parsers.
- Round-trip files opened by at least two independent consumers.
- Large mesh fixtures demonstrate bounded mmap input and direct sink output.

### G4 — Compressed point clouds and sequences

#### G4.1 LAZ

Status: implemented locally; local verification is complete. The new
LAZperf dependency still requires the user-gated Linux/macOS wheel and
instrumented validation lanes before the unit can be called validated.

Implementation:

- Pin LAZperf (Apache-2.0) and build its static library through CMake.
- Reuse the existing LAS header, scale, offset, point-field, and convention
  code rather than creating a parallel LAS model.
- Support the LAZ point formats actually handled by the chosen LAZperf
  revision; advertise the exact set.
- Connect LAZperf callbacks to buffer sources and direct file sinks.
- Preserve VLR/EVLR policy explicitly; reject fields the record cannot retain.
- Use chunk metadata for bounded point ranges when available.

Oracles:

- laspy plus lazrs in test extras.

Verification:

- every supported point format, scale/offset combination, color/intensity,
  chunking mode, empty cloud, and large count;
- LAS and LAZ decode to equivalent `PointCloud` values;
- selected chunk/range equals the full slice;
- compressor output reopens in both laspy/lazrs and SceneIO.

Benchmark:

- compression/decompression throughput, one versus multiple lanes where
  supported, memory above compressed input, and chunk selection.

Local implementation checkpoint (2026-07-25):

- LAZperf 3.4.0 is pinned to commit
  `b7bbe26109dc986f42d4fc80b8de3d2b6ca634ce` and archive SHA-256
  `17df34ca64cc60e107f0c214db4729c54a514df4e32de5bc1b8b7b7c5a805a56`.
  CMake builds only its 15 library translation units into a hidden static
  archive; upstream tools, tests, shared library, and install rules are not
  configured.
- `_core.read_laz`, `read_laz_points`, and `write_laz` cover exact standard
  point formats 0-3 and 6-8. Full reads parallelize independent LASzip chunks;
  partial reads validate the container and decompress only the origin anchor
  plus overlapping chunks.
- The wrapper bounds every LAZperf callback, validates the LASzip VLR/item
  schema, chunk-table counts and extents, format-1.4 stream sizes, and exact
  arithmetic termination. A documented local patch also bounds LAZperf's
  internal format-1.4 `MemoryStream::getByte`; deterministic mutations across
  every nonempty layered stream now either decode or raise a normal codec
  error without terminating the interpreter. Waveform formats, extra-byte
  strides, unrelated VLR/EVLR metadata, COPC, deferred chunk tables, and
  unrepresented global encoding flags reject instead of being discarded.
- Public `.laz` dispatch uses read-only mmap, a seekable direct file sink,
  metadata-only inspection, extensionless LASF compression-bit detection, and
  point-range selection. The sink streams 256 KiB chunks and seeks only to
  patch the header and chunk-table pointer.
- laspy/lazrs independently verifies both directions for formats 0-3/6-8,
  including legacy formats in LAS 1.4 containers, empty files, anisotropic
  oracle scales, GPS/NIR projection behavior, multi-chunk ranges, bytes versus
  mmap and one-versus-many lanes, lifetime, forced short writes, every
  truncated prefix, bounded metadata mutations, and large-file traced-memory
  checks.
- The dedicated suite passes 59 tests. The complete local MSVC suite passes
  2,827 tests with four documented skips; Ruff and `git diff --check` are
  clean.
- On the 12.0 MB logical/14.6 MB encoded benchmark fixture, five-run medians
  are 66 MB/s direct-sink write, 235 MB/s buffer read, and 184 MB/s public mmap
  read. Mmap and the sink each remove 14.6 MB of traced Python allocation;
  inspection is 1,335x faster and a one-sixteenth point range is 3.17x faster.
  The SceneIO and laspy/lazrs writers receive the same format-2 XYZ, RGB16,
  and exact-u16 intensity payload.
- A fresh source distribution rebuilds the `cp312-abi3` Windows wheel. Its
  39-entry payload contains exactly one native extension, the project license
  and LAZperf notice, no build-only include/lib/share/bin trees, and only NumPy
  as a runtime dependency. The packaged smoke, including LAZ, passes in an
  unseeded environment containing only SceneIO and NumPy.
- The manual three-lens review is complete. The memory/lifetime lens found
  LAZperf's unchecked internal layered-stream read and led to the pinned local
  bounds patch plus child-process mutation sweep. The correctness lens replaced
  silent intensity rounding/clamping with exact-u16 guards and aligned
  `inspect` with read-time scale/offset/waveform/EVLR rules. The test-soundness
  lens corrected the benchmark oracle so both writers receive identical
  format-2 fields. No local findings remain open.
- The user-gated `publish.yml` dry run
  [30163127394](https://github.com/SceneAPI/SceneIO/actions/runs/30163127394)
  passed at commit `daf991ab426d2db6ea9bd1d2ccea0f6ddc2d83b9`:
  manylinux2014, macOS, and Windows ABI3 wheels all built and passed their
  packaged smoke, and the sdist built successfully. The tag-only PyPI job was
  skipped as intended. PyPI trusted-publisher configuration remains a
  user-owned release prerequisite.

The same package resolves plain LAS waveform point formats 4/5/9/10. Add the
wave-packet fields to `PointCloud` only if they can be represented without
penalizing ordinary points; otherwise add a dedicated optional sidecar buffer.
Readers and writers must preserve waveform descriptor references and packet
offset/size/location fields or reject those point formats. They may not decode
them as a lower point format and drop the waveform data.

Plain-LAS waveform checkpoint — complete locally (2026-07-25):

- `PointCloud` now owns an optional `LasWaveformSidecar` containing the exact
  raw point records, canonical descriptor VLR stream, and internal waveform
  packet EVLR. Ordinary point clouds pay only for one absent shared pointer.
- LAS 1.3 formats 4/5 and LAS 1.4 formats 9/10 read, write, inspect, mmap,
  direct-sink, and point-range paths are implemented. Writers patch only
  canonical XYZ/intensity/RGB16 fields and preserve packet references,
  location/direction values, GPS/classification/return fields, NIR, and other
  opaque record bytes.
- External `.wdp` storage, unrelated VLR/EVLR records, noncanonical descriptor
  encodings, and packet references that cannot be retained exactly reject
  explicitly.
- Independent hand-built specification fixtures plus laspy cover all four
  formats in both directions. Public dispatch, deterministic bytes, partial
  writes, empty clouds, mutable-sidecar revalidation, mmap/bytes parity,
  source-copy isolation, and view lifetime after `gc.collect()` are pinned.
- The full local MSVC suite passes 2,768 tests with four documented skips;
  Ruff and `git diff --check` are clean. The accepted five-run LAS benchmark
  remains healthy at 1,095 MB/s write, 3,220 MB/s buffer read, 2,033 MB/s mmap
  read, zero traced mmap-copy allocation, 153x metadata inspection, and 11.29x
  middle-range selection.
- A staged source distribution rebuilds the cp312-abi3 Windows wheel. Its 38
  entries contain exactly one native extension and no leaked build headers,
  libraries, or vendor trees; a fresh environment containing only NumPy passes
  the expanded `_wheel_smoke` waveform read/write/inspect/partial case.
- Manual lifetime/ownership, format-correctness, and test-soundness review
  found and fixed non-finite coordinate-transform acceptance and empty colored
  waveform round-trip failure. Fable is unavailable locally; the Linux
  instrumented and Linux/macOS wheel lanes remain user-gated.

#### G4.2 ImageSequence and raw Y4M — complete locally

Implementation:

- Image-directory sequence: deterministic natural ordering, optional manifest,
  timestamps, heterogeneous-frame rejection, and lazy frame decoding.
- Y4M: parse stream header and frame headers; retain Y, U, and V planes plus
  chroma subsampling, range, and matrix metadata natively. RGB conversion is an
  explicit operation outside the codec.
- Support only explicitly listed uncompressed Y4M chroma layouts and reject
  layouts the planar frame contract cannot represent.
- Add frame-range selectors; a one-frame half-open range is the single-frame
  operation.
- Writers stream frames and never concatenate the full sequence in memory.

Oracles:

- an independent dependency-free Y4M parser/writer, exact golden bytes, and
  existing independently verified image inspectors for individual frame files.

Local verification:

- all six supported Y4M layout tokens (`mono`, three 4:2:0 sitings, 4:2:2,
  and 4:4:4) round-trip against the independent oracle, including odd
  dimensions, CRLF headers, exact rational timing, bytes/memoryview/mmap,
  malformed prefixes, direct-sink short writes, and selected-frame parity;
- image directories preserve encoded bytes, deterministic natural or manifest
  order, optional exact timing, same-directory replacement, bounded copying,
  and rollback on a failed staging copy; heterogeneous or missing frames reject;
- the universal buffer sweep is now 44 codecs and proves Y4M bytes/mmap and
  buffer/direct-sink identity; the public registry/capability snapshot is
  50 codecs;
- the representative 6.3 MB Y4M fixture measured 2,574 MB/s public mmap read,
  removed the 6.3 MB traced input allocation, and showed 33.48x inspection and
  4.19x one-sixteenth frame-range speedups. The 6.3 MB lazy directory fixture
  remained bounded and showed 1.45x inspection and 1.61x range gains;
- a manual three-lens review covered memory/lifetime, format correctness, and
  test soundness. It found and fixed mapped-view ownership, exact-timing,
  chroma-siting, inspector/parser agreement, duplicate-tag, source-metadata,
  natural-order tie, and duplicate-JSON-key defects. The Fable review tool was
  unavailable in this environment, so the manual review and focused tests are
  recorded explicitly rather than claiming an automated Fable sign-off;
- a 255-entry staged sdist rebuilt a 53-entry cp312-abi3 Windows wheel with
  exactly one native extension, the root Apache-2.0 license and every indexed
  third-party notice recorded as PEP 639 license files, no video-framework
  artifacts, NumPy as the sole runtime dependency, and a passing packaged
  sequence smoke in an environment containing only NumPy and SceneIO.

#### G4.3 Animated WebP and APNG

- Extend the existing libwebp path for animation metadata and frame decode.
- Add APNG through a permissive library or a small container layer over the
  existing PNG implementation.
- Preserve duration, loop count, blend, and disposal semantics.
- `read_partial(..., frames=...)` decodes only selected frames when the
  underlying container supports it.
- Inter-frame blend/disposal dependencies may require decoding a prefix to
  reconstruct the selected composited frame. The capability metadata states
  this, and memory remains bounded to decoder state plus one canvas rather than
  retaining every prior frame.
- Writer support lands only if output is deterministic and independently
  readable; otherwise advertise read-only explicitly.

#### G4.4 RTMV dataset layout

- Treat RTMV as a directory adapter over existing image/depth and
  `transforms_json`-style pose codecs, not as a duplicate raster decoder.
- Define the accepted directory/schema versions, camera convention, depth
  scale, frame pairing, optional segmentation/normal layers, and missing-frame
  policy.
- `inspect` validates metadata and enumerates frames without decoding images.
- Single-frame and frame-range reads remain lazy and preserve association
  between pose, RGB, depth, and auxiliary layers.
- Generate tiny and large synthetic layouts in tests; compare camera matrices,
  paths, and decoded frame values with an independent JSON/path oracle.
- Reject mixed resolutions, inconsistent frame ids, or unsupported auxiliary
  layers instead of silently dropping them.

Exit gate for G4:

- No sequence operation materializes all frames unless the caller requests the
  full sequence.

### G5 — Optional scientific/container libraries

Each library gets its own feature flag, build target, wheel smoke, license
notice, and clean unavailable-feature error:

| Feature | Formats |
|---|---|
| `SCENEIO_WITH_HDF5` | HDF5 and hloc |
| `SCENEIO_WITH_TIFF` | TIFF |
| `SCENEIO_WITH_E57` | E57 |
| `SCENEIO_WITH_ARROW` | Parquet |

The base source build must succeed with every flag off. Release wheels may
enable approved features statically while retaining numpy as the only Python
runtime dependency.

#### G5.1 HDF5 and hloc

Implementation:

- Use the HDF5 C API behind RAII handles.
- Map numeric datasets and groups to `TensorDict`.
- Add `FeatureSet`/`MatchGraph` adapters for the documented hloc group layout.
- Preserve attributes that fit the record metadata contract; reject unsupported
  object/reference/vlen layouts rather than coercing them.
- `inspect` traverses names, shapes, dtypes, chunking, and compression without
  dataset reads.
- Partial selectors cover dataset names, hyperslabs, images, and image pairs.
- Writer uses chunked streaming for large arrays.

Oracles:

- h5py and hloc in test extras only.

Validation:

- static/shared linkage behavior on all platforms;
- compressed/chunked/contiguous datasets;
- release-wheel import with no external-library lookup failure;
- minimal build reports the optional codec as unavailable without breaking
  `import sceneio`.

#### G5.2 TIFF

Implementation:

- Use LibTIFF behind `SCENEIO_WITH_TIFF`.
- Support an explicit matrix of strips/tiles, planar/interleaved samples,
  integer/float sample formats, photometric modes, alpha, orientation, and
  multi-page images.
- Window reads use tiles/strips rather than full-page decode.
- Multi-page files return `ImageSequence`; a single page returns `Image`.
- Unsupported color spaces or predictor/compression combinations fail with
  actionable errors.

Oracles:

- Pillow, tifffile, and imageio in test extras.

Benchmark:

- tiled windows, striped scan, multi-page lazy access, and streaming writes.

#### G5.3 E57

- Use libE57Format behind `SCENEIO_WITH_E57`.
- Preserve scan grouping, coordinate bounds, intensity/color, invalid-state
  flags, and transforms.
- Expose scan-level inspection and selection.
- Write only the subset the record can represent without losing required scan
  metadata.
- Oracle with pye57/libE57Format-generated fixtures.

#### G5.4 Parquet

Implementation:

- Add the `Table` record before the codec.
- Use Arrow C++/Parquet behind `SCENEIO_WITH_ARROW`.
- Define supported physical/logical types, nulls, UTF-8, row groups, metadata,
  and compression codecs.
- Inspect schema and row-group statistics without column decode.
- Partial reads select columns and row groups/ranges.
- Writers stream row groups.

Oracle:

- pyarrow test extra.

Exit gate for G5:

- Each optional feature has green off/on builds and wheel smoke tests.
- Optional native code does not change behavior of the original 23 codecs.
- Parallel independent reads and writes are exercised for each library. If an
  upstream build is not thread-safe, SceneIO serializes only calls into that
  library with a documented native lock; it must not hold the Python GIL merely
  to provide library serialization.

### G6 — Zarr and heavyweight scene/volume formats

#### G6.1 Zarr v2/v3

Implementation is capability-driven:

1. Directory store and Zip store.
2. Zarr v2 metadata and core numeric arrays.
3. Zarr v3 nodes and core bytes codec.
4. gzip/zlib and zstd using existing libraries.
5. transpose and CRC32C.
6. sharding.
7. Blosc behind a separately pinned permissive dependency.

Unknown codecs and extensions must identify themselves in the error. SceneIO
must not claim generic Zarr compatibility merely because it can parse
`zarr.json`.

Partial reads select array names and chunks/slices. `inspect` reads metadata
only. Write tests compare directory trees and decoded values with zarr-python;
byte identity is required only where the specification defines deterministic
bytes and the configuration is fixed.

#### G6.2 USD/USDZ

- Add the minimal `Scene` contract first.
- Build OpenUSD behind `SCENEIO_WITH_USD`.
- Start with mesh/camera/node-transform read support.
- Do not flatten variants, instancing, animation, materials, or composition
  arcs unless represented explicitly.
- USDZ packaging must be deterministic if write support is offered.
- Oracle against usd-core/PXR in test environments.

#### G6.3 OpenVDB

- Add `SparseGrid` with background value, active values, transform, dtype, and
  grid metadata.
- Build OpenVDB behind `SCENEIO_WITH_OPENVDB`.
- Start with scalar numeric grids; vector/point grids require explicit record
  support.
- Inspect grid names, bounds, transforms, dtypes, and active voxel counts.
- Partial reads select a grid and optional index-space window.
- Oracle against OpenVDB Python bindings.

G6 does not enter default wheels until build size, startup behavior, and
platform availability are measured and accepted.

### G7 — Policy-gated image/compression formats

Before implementation, record a project decision for:

- AVIF;
- JPEG-XL;
- Draco-compressed glTF.

The decision must state whether each format satisfies the no-patented-codec
constraint and which native implementation is approved. Until then:

- they remain absent from build files and wheels;
- plain glTF/GLB continues independently;
- coverage documents label them `policy-gated`, not generically pending.

## 5. Public API evolution

Existing calls remain source-compatible:

```python
sceneio.read(path, format=None)
sceneio.write(record, path, format=None)
sceneio.inspect(path, format=None)
sceneio.read_partial(path, format=None, ...)
```

Add keyword-only selectors as their records land:

| Selector | Applies to |
|---|---|
| `tensors=(...)`, `slices={...}` | safetensors, HDF5, Zarr |
| `image_id=<persisted id>` | COLMAP directory image/camera, COLMAP DB `FeatureSet`, future hloc |
| `pair=(image_id1, image_id2)` | COLMAP DB `MatchGraph`, future hloc |
| `columns=(...)`, `rows=(start, stop)` | Parquet |
| `mesh_id` / `primitive_id` | glTF, USD |
| `frames=(start, stop)` | image sequences, Y4M, animated WebP/APNG, TIFF |
| `scan_id` | E57 |
| `grid`, `window` | OpenVDB |

Selector validation happens before opening or mapping payload data. Exactly one
selection family may be supplied unless a documented combination, such as
Parquet columns plus rows, is meaningful.

Capability discovery is public and stable before optional codecs ship, so
callers never need import-time probing:

```python
caps = sceneio.capabilities("tiff")
if caps.available and "window" in caps.partial_selectors:
    ...
```

## 6. Per-codec implementation loop

Every codec uses the same order:

1. **Contract**
   - Define supported versions, fields, dtypes, conventions, lossy behavior,
     unsupported features, and write guards.
2. **Fixture/oracle**
   - Add independent reader/writer oracle and generated/golden fixtures before
     optimizing.
3. **Reader**
   - Implement buffer input, checked size arithmetic, GIL release, RAII, and
     record construction.
4. **Writer**
   - Implement deterministic buffer output and direct file sink.
5. **Registry**
   - Add extensions, exact filenames, magic, record, datatype, inspect,
     selectors, and capability metadata.
6. **Differential correctness**
   - Prove path/mmap/bytes and full/partial equivalence.
7. **Memory and lifetime**
   - Prove mapping ownership, bounded allocation, exception cleanup, and file
     handle release.
8. **Benchmark**
   - Measure before/after and oracle-relative throughput plus peak allocation.
9. **Fable three-lens review**
   - Record the memory-safety, format-correctness, and test-soundness findings
     and their disposition before commit.
10. **Cross-platform validation**
    - Native build/tests and wheel smoke.
11. **Documentation and commit**
    - Update coverage, public API, benchmark baseline, and third-party
      provenance; commit only when green.

## 7. Verification plan

### 7.1 Common automated contract

Add a registry-driven test matrix that requires, for every available codec:

- detection by extension, filename, magic, or documented explicit-format
  requirement;
- public `write -> detect -> inspect -> read`;
- direct compiled bytes read versus public path/mmap read;
- buffer writer versus file-sink byte equality for deterministic formats;
- record type, dtype, shape/count, and convention metadata;
- inspector agreement with full decode;
- partial selection agreement with a full-read slice;
- unknown/truncated/overflowing data normalized to `FormatError`;
- the capability manifest agrees with callable hooks.

Read-only formats omit writer equivalence only when their declared capability
explicitly says so.

### 7.2 Per-format parity

Each new `tests/codecs/test_<format>.py` contains:

1. Oracle-written -> SceneIO read.
2. SceneIO-written -> oracle read.
3. SceneIO round-trip.
4. Golden writer bytes for deterministic lossless formats.
5. Value tolerance and metadata checks for lossy formats.
6. Convention pins using hand-computable fixtures.
7. Unsupported-feature guard tests.
8. Cross-endian and alignment cases where the format permits them.

No oracle package moves into runtime dependencies.

### 7.3 Randomized differential correctness

For each format, generate small valid records across the supported feature
matrix and compare:

```text
record -> SceneIO writer -> SceneIO reader
record -> oracle writer  -> SceneIO reader
record -> SceneIO writer -> oracle reader
full read slice          == bounded partial read
bytes input              == mmap/path input
buffer output            == sink output
```

Malformed variants are used to check deterministic failure and bounded memory,
not as a separate cybersecurity deliverable.

### 7.4 Large-file and memory verification

Generated fixtures cover 100 MiB, 512 MiB, and, where practical, 1 GiB logical
payloads. The fixture matrix includes:

- raw/mapped;
- compressed;
- chunked/tiled;
- text;
- multi-file directory;
- many-small-array/frame/primitive cases.

Measurements:

- `tracemalloc` peak above input mapping;
- fresh-process RSS or platform equivalent;
- output-record size;
- retained mapping lifetime;
- read and write file-handle release;
- inspect and partial memory versus full decode.

Assertions are structural rather than universal numeric SLAs:

- mmap paths do not allocate a whole-file Python `bytes`;
- sink writers do not allocate an output-sized Python `bytes`;
- inspect does not construct payload arrays;
- partial reads allocate only selected output plus container-required mapping
  or chunk state;
- zero-copy views remain valid after local file handles leave scope.

Platform-specific allocator/page-cache allowances are documented beside each
numeric threshold.

### 7.5 Benchmark verification

Extend `bench/bench_io.py` with one representative fixture builder per new
codec and these modes:

- warm read/write;
- cold-cache path read where supported;
- inspect;
- bounded partial read;
- bytes versus mmap;
- buffer versus sink;
- one versus multiple lanes when implemented;
- SceneIO versus oracle.

Every benchmark row records:

- raw payload and encoded file sizes;
- throughput and latency;
- traced allocation and RSS;
- selection ratio for partial reads;
- exact identity mode (`bytes`, `values`, or tolerance);
- native feature configuration.

CI uses same-run directional comparisons for high-signal operations. Historical
numbers remain in `bench/BASELINE.md` for investigation, not as brittle
cross-machine absolute throughput requirements.

### 7.6 Review checklist

Memory-safety lens:

- all size arithmetic checked before multiplication/addition;
- no pointer retained beyond its buffer owner;
- mapping and selected views share an explicit owner;
- library buffers use RAII deleters;
- exceptions release mappings, handles, transactions, and locks;
- no GIL-free access to Python objects;
- threaded callbacks cannot outlive inputs or sinks.

Format-correctness lens:

- spec versions and endian rules pinned;
- oracle independence maintained;
- conventions and units represented;
- optional fields preserved or rejected;
- lossy behavior declared;
- deterministic output requirements tested;
- detect rules do not steal another format.

Test-soundness lens:

- fixtures exercise independent code paths rather than mirroring production;
- writer tests are read by an external oracle;
- partial tests compare against full decoded values;
- memory tests run in fresh processes where allocator reuse would hide growth;
- skips require an explicit platform/dependency reason;
- each optional feature has both enabled and disabled tests.

## 8. Cross-platform and packaging validation

### 8.1 Local development gate

After every C++ or CMake change:

```powershell
uv pip install -e ".[dev,test]"
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check
```

Verify the new compiled symbols explicitly before running parity tests.

### 8.2 Continuous integration lanes

Required on every codec commit:

| Lane | Coverage |
|---|---|
| Ubuntu normal | full suite, all test oracles, benchmark smoke |
| Windows | affected codec suites, mmap/locking/lifetime, sink behavior |
| macOS | affected codec suites, mmap/lifetime, sink behavior |
| Instrumented Linux | full in-tree suite with native extension and vendored libraries instrumented |
| Minimal features | all `SCENEIO_WITH_*` off; import and original 23 codecs green |
| Full features | all approved optional libraries on; new codec parity and smoke |

Scheduled jobs run the larger randomized differential corpus and generated
large fixtures.

### 8.3 Wheel validation

At the end of every dependency wave:

1. Build the sdist.
2. Build cp312-abi3 wheels for:
   - manylinux2014 x86-64;
   - macOS arm64;
   - Windows amd64.
3. Install each wheel in a clean environment containing only numpy plus
   test-only smoke dependencies.
4. Run:
   - `_core` symbol/capability check;
   - one read/write/inspect/partial smoke per newly enabled library;
   - original 23-codec smoke;
   - shared-library dependency inspection with `auditwheel`, `otool`, or the
     Windows dependency tools as appropriate.
5. Confirm the tag version matches `pyproject.toml`.
6. Confirm Linux artifacts retain the manylinux2014/glibc 2.17 tag, numpy is
   installed from a compatible binary wheel rather than built from source, and
   no optional library is accidentally left as an unresolved external
   dependency.

The cibuildwheel dry-run trigger and each PyPI release remain user-gated
external actions. No branch push, tag, or publication is implicit in completing
a local work package.

### 8.4 Third-party intake

Before adding a native library:

- record repository, exact tag/SHA, license, source files built, build options,
  and local patches in `src/cpp/third_party/<name>/COMMIT.txt`;
- disable tools, tests, examples, shared libraries, and unused codecs;
- reuse existing miniz/zstd/json implementations where compatible;
- verify static linkage and symbol visibility;
- build on all three compilers before codec code depends on it.

## 9. Documentation and release validation

Every codec commit updates:

- `docs/format_coverage.md`;
- `docs/coverage_roadmap.md`;
- this plan's work-package status;
- `README.md` for public API examples;
- `bench/BASELINE.md`;
- third-party provenance when applicable.

Before a release:

1. Coverage manifest has no unexplained pending entries.
2. Public docs distinguish shipped, optional, unavailable, and policy-gated.
3. All newly public selectors and record fields have examples.
4. The release wheel matrix and instrumented lane are green.
5. The all-codec E2E sweep includes every available registry entry.
6. PyPI publishing is performed only from a version-matching tag through
   `.github/workflows/publish.yml`.

## 10. Work-package exit matrix

| Package | Functional gate | Verification gate | Validation gate |
|---|---|---|---|
| G0 capabilities | registry/docs agree | manifest contract tests | minimal/full builds |
| G1 records | zero-copy canonical record | dtype/shape/lifetime matrix | MSVC + instrumented Linux + wheels |
| G2 self-contained | all listed codecs registered | oracle parity, inspect/partial, benchmark | default wheel matrix |
| G3 mesh | PLY/OBJ/STL/OFF/glTF supported subset | topology/attribute parity and external readers | wheel matrix, large mesh |
| G4 LAZ/sequences | streaming compressed points/frames | chunk/frame partial parity and memory | wheel matrix, long sequence |
| G5 optional libs | off/on feature behavior | per-library oracle and regression suite | minimal + full-feature wheels |
| G6 heavy formats | scoped Zarr/USD/OpenVDB support | independent ecosystem readers | size/startup/platform acceptance |
| G7 policy | written decision | dependency/license/build proof | explicit user approval |

## 11. Recommended release sequence

The work should ship in small releases rather than one long-lived branch:

1. **0.3 — capability truth and self-contained data**
   - G0, the records required by G2, safetensors, COLMAP DB, generic PLY, PCD,
     and the small reconstruction/depth/calibration codecs.
2. **0.4 — meshes**
   - `Mesh`, mesh PLY, OBJ/MTL, STL, OFF, and plain glTF/GLB.
3. **0.5 — compressed points and sequences**
   - LAZ, SOG/KSplat, image sequences, Y4M, animated WebP/APNG, and RTMV.
4. **0.6 — scientific optional libraries**
   - HDF5/hloc, TIFF, E57, and Parquet with off/on wheel configurations.
5. **0.7 — chunked and heavyweight ecosystems**
   - Zarr, then USD/USDZ and OpenVDB if their size and record contracts pass
     acceptance.
6. **Policy release**
   - AVIF/JPEG-XL/Draco only after the explicit G7 decision.

Within a release, each codec still follows its own green commit and review
loop. A release number expresses a coherent capability tier; it does not allow
partially verified codecs to batch-land.

### 11.1 Relative sizing and critical path

One engineering unit means one record or codec-sized green change, including
its parity suite, benchmark delta, review, and documentation. It is not a
calendar estimate.

| Package | Relative units | Dominant uncertainty |
|---|---:|---|
| G0 capabilities and reconciliation | 1-2 | public capability schema |
| G1 records | 8-12 | polygon/corner/material attributes, trajectory/planar frames, variable-length tables, scene/grid scope |
| G2 self-contained codecs | 14-20 | COLMAP DB contracts, PLY dispatch, calibration variants |
| G3 meshes | 8-12 | glTF scene fidelity and material/attribute scope |
| G4 LAZ and sequences | 7-10 | waveform fields, animation disposal/blend semantics |
| G5 optional libraries | 12-18 | static wheel builds and optional-library feature matrices |
| G6 heavyweight ecosystems | 12-20 | USD/OpenVDB record scope and wheel size |
| G7 policy decisions | decision gate | patented-codec constraint |

The critical path is:

```text
G0 -> Mesh -> PLY/OBJ/STL/OFF -> glTF
G0 -> FeatureSet/MatchGraph -> COLMAP DB -> HDF5/hloc
G0 -> optional-feature build matrix -> HDF5/TIFF/E57/Arrow -> full wheels
G0 -> Scene/SparseGrid scope -> USD/OpenVDB
```

Safetensors, PCD, DMB, and the small pose/calibration formats can proceed after
G0 without waiting for the mesh or optional-library paths.

## 12. Detailed implementation and closure plan

This section is the operational queue. The package specifications above define
what each format means; this queue defines the exact landing order and evidence
required to call it covered. Relative units are intentionally not calendar
estimates.

### 12.1 Current checkpoint and status vocabulary

The current local checkpoint is:

- 50 compiled registry codecs with read, write, inspect, mmap or path-native
  input, and direct file sinks;
- O0-O5 complete for the existing codec tier;
- `FlowField`, typed FLO, typed PFM depth, typed PNG depth, and typed scalar EXR
  depth complete;
- 2,912 local tests pass with 4 documented platform/optional skips, Ruff and
  `git diff --check` are clean;
- the complete 50-codec benchmark, staged source-distribution rebuild, and
  packaged NumPy-only wheel smoke pass;
- generic point PLY, PCD, StateTrajectory/EuRoC, CameraRig calibration,
  PoseGraph/g2o, the COLMAP feature database, SuperSplat compressed PLY,
  PlayCanvas SOG v2, KSplat v0.1, the canonical `Mesh` record, generic mesh PLY,
  canonical `MaterialSet`, OBJ/MTL, STL/OFF, `MeshScene`, and plain glTF/GLB
  are complete locally; plain LAS point formats 4/5/9/10 now retain internal
  waveform data losslessly through an optional `PointCloud` sidecar; lazy
  image directories and raw Y4M are complete over the new `ImageSequence`;
- all 50 codecs have repo-maintained production adapters and optimized I/O
  contracts, but the default native source closure is incomplete while six
  pinned dependencies still use CMake `FetchContent`;
- the build-only dependency-wave release run at `daf991ab` produced successful
  Windows, macOS, Linux wheels and an sdist with publication skipped. It
  predates `ImageSequence`, Y4M, and the centralized license inventory;
- at the latest tested code checkpoint `ea622ac`, Windows and macOS mmap jobs
  pass. Linux normal CI fails six portability assertions and the instrumented
  reliability job stops during test collection/filtering, so that checkpoint
  is **verified locally, not validated**.

Status terms are strict:

| Status | Meaning |
|---|---|
| Planned | contract exists, but implementation has not started |
| Implemented locally | code, focused parity tests, and documentation exist |
| Verified locally | full suite, lint, differential/memory tests, benchmark guard, and three-lens review pass |
| Validated | required compiler, instrumented, sdist, and wheel lanes pass |
| Shipped | validated artifacts were published from a matching version tag |
| Policy-gated | implementation cannot start until the named project decision is recorded |

#### 12.1.1 Immediate closure blockers

Do not begin another format implementation until these existing-coverage gates
are green:

1. **Linux Y4M inspection:** reproduce and remove the GCC/Linux
   `std::bad_cast` raised by `_inspect_y4m` for mmap input. Prove bytes,
   memoryview, mmap, public `inspect`, full read, and frame selection on GCC 10,
   AppleClang, and MSVC with identical metadata.
2. **Portable SQLite lock semantics:** replace the Linux-only assumption that
   `BEGIN EXCLUSIVE` must block a read with a test that establishes the exact
   lock/journal mode it intends to exercise. Preserve the Windows share-lock
   test separately.
3. **Baseline-relative RSS assertions:** replace the two absolute 16 MiB fresh
   process limits with a payload-relative or measured-baseline bound that still
   proves malformed COLMAP prefixes do not allocate from file-controlled
   counts.
4. **Instrumented test environment:** keep required oracles importable during
   collection, isolate the SceneIO test subset from unrelated optional native
   modules, and distinguish CPython/pydantic shutdown allocations from stacks
   rooted in `sceneio._core`.
5. **CI labels and documentation:** keep workflow names, codec counts, coverage
   tables, benchmark counts, and the public capability snapshot synchronized.

Exit gate: current-head Linux normal CI, Windows/macOS mmap jobs, the
instrumented native reliability job, local MSVC, Ruff, and `git diff --check`
all pass without weakening format correctness or payload-relative memory
proofs.

#### 12.1.2 Ordered next implementation queue

The queue below is dependency-ordered. Finish and commit each numbered unit
with its focused parity suite, full regression suite, benchmark delta,
three-lens review, documentation, license inventory, and required platform
lane before starting the next unit.

1. **Repository organization gate (R1-R4).**
   Freeze the 50-codec contracts, introduce the single codec/performance
   manifest, split the Python registry and inspectors by format family, split
   benchmark/test data builders, and organize native dependency and binding
   registration by family. Preserve the existing public facades and prove the
   capability, detection, `_core` symbol, and full E2E snapshots after every
   mechanical unit. Follow
   [`repository_organization_plan.md`](repository_organization_plan.md);
   do not combine file moves with codec behavior changes.
2. **Backend performance qualification (R5).**
   Create one `bench/PERFORMANCE_STATUS.toml` entry for every live codec and
   compare each viable permissive upstream backend through SceneIO's production
   read/write paths. Measure encode/decode, warm/cold path I/O, direct sinks,
   traced allocation, fresh-process RSS, determinism, artifact size, and
   startup on representative and generated fixtures. Resolve known gaps
   beginning with JPEG encode/decode by evaluating libjpeg-turbo; retain or
   replace a backend only from measured evidence. Existing optimized transport
   does not by itself qualify every codec kernel.
3. **Repository source closure for the stable tier (R6).**
   Vendor the exact selected revisions under `src/cpp/third_party/`. The
   current closure set is miniz 3.0.2, nlohmann/json 3.11.3, zstd 1.5.6,
   fast_float 6.1.6, LAZperf 3.4.0 commit, and libwebp 1.5.0; include any R5
   backend replacement such as libjpeg-turbo and retire an old kernel only
   when no live codec uses it. Preserve local LAZperf integration changes, add
   `COMMIT.txt` provenance/hashes, retain all `LICENSES/` notices, and remove
   default-build network fetches. Verify golden codec output and benchmark
   results are unchanged. Validate an sdist-to-wheel build with network source
   fetching disabled on MSVC, manylinux2014 GCC 10, and AppleClang.
4. **Animation-capable `ImageSequence`.**
   Add an owned packed-frame mode with exact canvas size, pixel dtype/channels,
   per-frame duration, loop count, blend operation, disposal operation, and
   source-frame rectangle. Views remain read-only and owner-safe. Path and YUV
   modes remain source-compatible.
5. **Animated WebP.**
   Use only the qualified, in-tree permissive libwebp source. Implement
   repository-owned
   container/metadata validation, composited full reads, dependency-aware
   selected-frame reads, deterministic writing only if libwebp produces stable
   output, inspection, and direct sinks. Pillow/libwebp tools are test
   references only; no external executable or video framework enters runtime.
6. **APNG.**
   Implement a bounded repository-owned APNG chunk/state layer over the
   existing PNG/deflate components. Preserve `acTL`/`fcTL`/`fdAT` order,
   rectangles, duration rationals, loop count, blend, and disposal. Add
   independent Pillow/spec goldens, prefix-dependency frame selection, exact
   inspection, and deterministic writing only after cross-reader proof.
7. **RTMV directory layout.**
   Specify accepted metadata versions, camera/pose convention, depth scale,
   RGB/depth/normal/segmentation pairing, and missing-frame policy. Reuse
   existing image, depth, transform, and lazy-path codecs; do not duplicate
   raster decoders. Inspection and selected-frame reads remain metadata/path
   bounded.
8. **Common optional-library substrate.**
   Implement one `SCENEIO_WITH_*` pattern with explicit disabled, enabled, and
   unavailable states; accurate capability metadata; clean import behavior;
   license/provenance hooks; minimal/full wheel profiles; and no change to the
   default NumPy-only runtime.
9. **Optional scientific formats, one dependency wave at a time.**
   Land HDF5 plus hloc, TIFF, E57, then Parquet/Arrow. Each wave needs off/on
   builds, independent oracle parity, streaming/partial tests, artifact-size
   accounting, and all three compilers before the next library begins.
10. **Chunked and heavyweight formats.**
   Implement Zarr v2 then v3, followed only after explicit size/startup
   acceptance by USD/USDZ and OpenVDB. Define `Table`, general `Scene`, and
   `SparseGrid` records before their first codec.
11. **Cross-repository vocabulary closure.**
   Assign stable wire/DataType ids for the branch-local records in SceneAPI
   Phase C without changing the already working SceneIO record ABI.

AVIF, JPEG-XL, and Draco-compressed glTF remain outside this queue until an
explicit policy decision. H.264/H.265/ProRes, HEIF/HEIC, FFmpeg-backed
containers, proprietary SDK formats, and copyleft/non-commercial dependencies
remain excluded.

### 12.2 Wave A — typed-depth slice complete locally

#### A1. Typed scalar EXR depth — complete locally

Implementation:

1. Extend `DepthEncoding.channel_name` validation to require a nonempty,
   NUL-free UTF-8 name of at most 255 encoded bytes for EXR. PFM and PNG
   continue to require no channel name.
2. Extend the single native header/decode pass to reject multipart, deep,
   tiled, UINT, and multi-channel EXR and validate the exact stored channel
   before raster decode.
3. Add `_core.read_exr_depth` using the existing raw EXR decoder. It accepts
   exactly one HALF/FLOAT channel whose name equals the explicit encoding,
   widens HALF according to the existing raw path, and copies decoded float32
   values bit-for-bit into an owning `DepthMap`.
4. Refactor the existing writer through one internal implementation. Raw
   one-channel `Image` writes continue to emit channel `Y`; the new typed writer
   emits the explicitly requested scalar name. Neither path rescales,
   color-converts, classifies invalid values, or changes raw golden bytes.
5. Add the native file-sink request, public `read_depth`, `write_depth`, and
   `inspect_depth` dispatch, the `typed_depth_adapter` capability marker, and
   numpy-only wheel smoke coverage.
6. Reject confidence, encoding mismatch, multi-channel selection, and typed
   windows before opening a write destination or invoking a full compressed
   decode.

Verification:

- OpenEXR-written HALF/FLOAT scalar files read identically through raw, typed,
  bytes, mmap, and public path APIs.
- SceneIO typed output reopens in OpenEXR with the exact channel name and float
  bit patterns, including signed zero, infinities, subnormals, and NaN payloads.
- Raw one-channel output remains byte-identical and retains `Y`.
- Hand-built and oracle files cover channel mismatch, RGB/RGBA/extra channels,
  UINT, every truncated prefix, bounded mutations, dimension/product limits,
  unsupported multipart/deep/tiled layouts, and all supported compressions.
- One versus multiple lanes is deterministic; forced short file writes equal
  buffer output; destination preflight failures leave no file behind.
- A generated multi-megabyte fixture proves mmap reading and direct sink writing
  do not allocate an encoded-size Python `bytes`; header inspection remains
  below the documented bounded threshold; returned data outlives mapping
  closure and `gc.collect()`.
- `bench/bench_io.py --runs 5` records typed read/write/inspect rows and leaves
  every retained O4/O5 directional and memory guard green.

Validation and exit:

- Rebuild the extension, verify the three new native symbols, run the focused
  EXR/raw-compatibility suites, then run the common local gate in section 12.9.
- Complete and record the memory/lifetime, format-correctness, and
  test-soundness review with no unresolved finding.
- Update README, both coverage documents, this ledger, the benchmark baseline,
  and wheel smoke.
- Land one green commit, `feat(io): add typed EXR depth adapters`, with the
  required co-author trailer.
- Wave A is locally complete only when PFM, PNG, and EXR expose the same typed
  public contract without changing any raw codec result or byte stream.

### 12.3 Wave B — finish default-wheel, self-contained G2 coverage

Land each numbered item as its own verified commit. Do not combine records or
codecs merely to make the ledger look complete.

#### B1. Generic point PLY — complete locally

Implementation:

- A separate `ply` registry codec maps point-only PLY into `PointCloud`; the
  bounded shared header classifier routes complete Gaussian schemas to
  `gaussian_ply`, ordinary point schemas to `ply`, and mesh/list/non-vertex
  schemas to an explicit not-yet-supported mesh result before extension-order
  fallback.
- The native reader accepts PLY 1.0 ASCII, binary little-endian, and binary
  big-endian bodies, arbitrary property ordering, every standard scalar
  spelling for numeric point fields, float32 canonicalization, exact uint8 or
  uint16 RGB, optional normals, and optional intensity with u8/u16 range tags.
- Unknown or list-valued vertex properties, incomplete semantic groups,
  non-vertex elements, finite float64 values outside float32 range, malformed
  counts, oversized headers/tokens, truncated/trailing payloads, and hybrid
  Gaussian schemas are refused instead of discarded.
- The deterministic writer supports all three encodings through a private
  verification seam and defaults publicly to binary little-endian. It guards
  georeferenced origins, coordinate/scale metadata, simultaneous rgb/rgb16,
  unit intensity semantics, and non-integral integer-tagged intensity.
- Inspection reads at most the 1 MiB header and validates fixed binary extent
  from file size. Binary point ranges validate the complete record extent
  before allocating only the requested slice; ASCII ranges remain
  intentionally unsupported.

Verification and validation evidence (2026-07-24):

- 67 focused cases triangulate the native codec with an independent
  NumPy/stdlib parser and Open3D 0.19, including all scalar families, both
  endians, ASCII, property order, NaNs, normals, rgb8/rgb16, intensity,
  malformed schemas, count bombs, mmap lifetime/mutation isolation, direct
  sinks, header-only inspection, schema-aware detection, and Gaussian
  non-regression.
- The shared public/mmap/sink/inspection/partial/capability suites include PLY;
  the complete local MSVC gate passes 1,898 tests with 3 documented optional
  skips.
- A three-run 4,000,000-point (108 MB logical) harness run measured 762 MB/s
  binary-LE write, 891 MB/s binary-LE read, 547/546 MB/s binary-BE write/read,
  and 22/108 MB/s ASCII write/read. Header inspection was 2,148x faster than
  full read and the 1/16 range was 14.04x faster with 12.3 MB versus 215.4 MB
  sampled RSS.
- The mmap path removed 108.0 MB of traced input allocation and the direct
  sink removed 108.0 MB of traced Python output allocation. A separate
  100,000-point pass measured 930 MB/s SceneIO read versus 128 MB/s Open3D and
  768 MB/s SceneIO write versus 23 MB/s Open3D.
- A clean Windows cp312-abi3 wheel contains 35 entries, no leaked
  include/lib/share/bin build artifacts, retains numpy as its only runtime
  requirement, exports all three PLY symbols, and passes the expanded
  numpy-only wheel smoke.
- The accepted five-run 30-codec harness leaves every retained O4/O5
  directional and mmap/sink memory guard green.
- Manual memory-safety, format-correctness, and test-soundness review found and
  fixed pre-allocation count validation and hybrid-schema dispatch gaps.
  Linux sanitizer and Linux/macOS wheel validation remain user-gated remote
  actions.

#### B2. PCD — complete locally

Implementation:

- The native PCD 0.7 reader accepts ASCII, little-endian binary, and LZF
  `binary_compressed`, arbitrary supported field order, every standard
  integer/float size, required x/y/z, complete normal triples, packed
  SIZE-4 TYPE-F/U RGB, and optional intensity.
- `PointCloud` additively records organized width/height and the seven-value
  acquisition viewpoint. Full reads preserve both; point subsets become
  unorganized while retaining viewpoint. XYZ, PTS, generic PLY, and LAS
  writers reject nondefault values they cannot serialize.
- Unknown fields, COUNT other than one, incomplete normals, unsupported RGB,
  finite float64 overflow, inconsistent WIDTH/HEIGHT/POINTS, malformed header
  order, oversized headers, truncated/trailing bodies, size bombs, and invalid
  LZF streams reject before record allocation.
- The deterministic writer defaults publicly to binary and exposes private
  ASCII/binary/LZF variants for verification. Binary and ASCII file sinks emit
  bounded chunks; LZF output uses a clean in-tree compatible implementation
  with no new native or runtime dependency.
- Registry detection, mmap input, direct sinks, header-only inspection,
  capabilities, public E2E dispatch, and fixed-record binary ranges cover PCD.
  ASCII and compressed ranges intentionally reject.

Verification and validation evidence (2026-07-24):

- 76 focused cases triangulate the native reader/writer with an independent
  NumPy/stdlib parser, an independently implemented LZF decoder, and Open3D
  0.19 in both directions across all three storage modes.
- The cases cover scalar widths, field ordering, packed RGB F/U, intensity
  tags, signed zero/infinity/NaN behavior, organized metadata, empty clouds,
  malformed counts/extents/LZF tokens, mmap lifetime and mutation isolation,
  bounded inspection, streaming sinks, partial reads, and guard-before-open
  behavior.
- Shared mmap/sink/inspection/partial/capability/E2E tests include PCD. The
  full local MSVC suite passes 1,976 tests with 3 documented optional skips;
  Ruff is clean and the numpy-only wheel smoke passes.
- On a generated 4,000,000-point fixture (108 MB logical, 112 MB binary),
  binary write/read measured 1,937/3,595 MB/s, LZF 168/1,566 MB/s, and ASCII
  25/113 MB/s. Header inspection was 1,015x faster and the middle 1/16 point
  range was 22.48x faster than full public decode.
- Mmap removed 112.0 MB of traced input allocation. The chunked binary sink
  reduced traced output allocation from 112.0 MB to 0.001 MB and sampled RSS
  from 112.0 MB to 1.9 MB. The partial path used 12.9 MB sampled RSS versus
  219.2 MB for the full mapping plus decoded record.
- A 100,000-point oracle run measured SceneIO binary write/read at
  1,894/3,233 MB/s versus Open3D at 25/63 MB/s. Random data made LZF slightly
  larger, and that honest incompressible result is recorded rather than
  filtered.
- The accepted five-run 31-codec harness leaves every retained O4/O5
  directional and mmap/sink allocation guard green.
- A clean Windows cp312-abi3 wheel contains 36 entries, no leaked
  include/lib/share/bin artifacts, retains numpy as its only unconditional
  runtime requirement, exports all three PCD symbols, and passes the packaged
  smoke under NumPy 2.5.
- Manual memory-safety, format-correctness, and test-soundness review found and
  fixed overflow-prone worst-case LZF sizing, noncanonical empty organization,
  missing valid overlap-match coverage, and inspection-parser failure gaps.
  The Fable executable was unavailable locally, so the same three lenses were
  applied manually. Linux sanitizer and Linux/macOS wheel validation remain
  user-gated remote actions.

#### B3. Small record-backed pose and calibration formats

Land each record with its first consumer, then add the remaining syntax
adapters:

1. ✅ `StateTrajectory` plus EuRoC state CSV (B3.1 complete locally).
2. ✅ `CameraRig` plus OpenCV YAML/XML, ROS `camera_info`, and Kalibr YAML
   (B3.2 complete locally).
3. ✅ `PoseGraph` plus g2o (B3.3 complete locally).

Every record commit must pin coordinate frames, units, timestamp precision,
quaternion ordering/sign policy, covariance/information layouts, ragged
offsets, zero-copy view ownership, source-mutation isolation, and exact writer
guards. YAML/XML parsing must remain native and bounded; no runtime Python
dependency is added.

##### B3.1 StateTrajectory + EuRoC state CSV — complete locally

Implementation:

- `StateTrajectory` owns exact signed-int64 nanosecond timestamps and float64
  SoA arrays for position, WXYZ/XYZW quaternion coefficients, velocity,
  gyroscope bias, and accelerometer bias. Its closed convention metadata pins
  quaternion order/sign policy, pose direction, vector frames, SI units, and
  timestamp units. The factory validates rank/shape alignment, finite values,
  nonzero quaternions, strict nonnegative timestamps, and a declared
  canonical-positive-W policy before copying into record-owned storage.
- `euroc_state` implements the official 17-column
  `t,p_RS_R,q_RS,v_RS_R,b_w_RS_S,b_a_RS_S` CSV schema. It preserves
  epoch-scale timestamps and every float64 coefficient, writes deterministic
  17-digit text, accepts read-only contiguous buffer exporters, releases the
  GIL around pure C++, and rejects headers, fields, frames, units, signs, or
  values it cannot represent.
- Canonical header magic detects standard EuRoC files without claiming the
  ambiguous `.csv` extension. Public reads use mmap, public writes emit the
  header plus bounded 2,048-row chunks, native inspection validates the stream
  without constructing state arrays, and `read_partial(..., states=(a,b))`
  materializes only the selected half-open range while validating all rows.
- Lines are capped at 1 MiB; NULs, non-ASCII schema drift, wrong/empty column
  counts, non-int64/duplicate/decreasing timestamps, non-finite values, zero
  quaternions, and oversized extents reject. No dependency was added.

Verification and validation evidence (2026-07-24):

- 96 focused record/codec cases include an independent stdlib CSV oracle,
  hand-derived 90-degree WXYZ convention pin, exact timestamps beyond float64
  integer precision, extreme finite/subnormal doubles, 40 randomized valid
  round trips, 200 randomized malformed-row differentials, source mutation,
  view lifetime/DLPack, mmap-vs-bytes, bounded inspection, sink identity and
  error behavior, partial equality, and writer guards.
- The shared mmap/sink/inspection/capability and public API paths include
  EuRoC. The full local MSVC suite passes 2,072 tests with 3 documented
  optional skips; repository-wide Ruff and `git diff --check` are clean.
- The accepted five-run 32-codec guard passes every retained O4/O5 direction
  and mmap/sink memory bound. On 100,000 states (13.6 MB logical, 35.2 MB CSV),
  buffer write/read measured 42/202 MB/s and public mmap read 176 MB/s.
  A separate oracle run measured the compiled reader at 11.19x stdlib CSV.
- Mmap removes the 35.2 MB traced input allocation. The direct sink removes the
  35.2 MB traced output allocation and reduced sampled output RSS from 42.1 MB
  to effectively zero. Inspection and the middle 1/16 state range each
  measured 1.05x faster than full decode; the range reduced sampled RSS from
  48.4 MB to 35.1 MB.
- A clean Windows cp312-abi3 wheel has 36 entries, no leaked
  include/lib/share/bin artifacts, NumPy as its sole unconditional runtime
  dependency, and passes the installed-wheel smoke with EuRoC
  read/write/detect/inspect/state-range coverage.
- Manual memory-safety, format-correctness, and test-soundness review found and
  fixed empty-range null-pointer arithmetic, unchecked claimed quaternion sign
  metadata, and missing hand-derived/malformed differential coverage. The
  Fable executable was unavailable locally, so the same three lenses were
  applied manually. Linux sanitizer and Linux/macOS wheel validation remain
  user-gated remote actions.

##### B3.2 CameraRig + OpenCV/ROS/Kalibr calibration — complete locally

Implementation:

- `CameraRig` is a lossless record for ordered camera ids/names and positive
  resolutions; source model names with ragged float64 intrinsic and distortion
  vectors; exact optional row-major K/R/P matrices; reference-to-camera WXYZ
  extrinsics with explicit presence; ROS binning/ROI/rectify state; Kalibr
  topics and signed camera-to-reference time offsets; and closed
  frame/direction/sign/unit convention tags. Factories copy into record-owned
  storage while properties expose lifetime-safe zero-copy views.
- `opencv_yaml` and `opencv_xml` preserve K/D plus optional R/P and reject
  records whose ids, pinhole/K relationship, frames, extrinsics, operational
  state, topics, or time offsets cannot be represented. The two syntaxes have
  separate format ids and canonical signatures rather than claiming generic
  YAML/XML suffixes.
- `ros_camera_info` preserves exact K/D/R/P, the distortion model (including
  the valid empty uncalibrated spelling), binning, ROI bounds, and rectify
  flag. `kalibr` preserves per-camera model vectors, distortion vectors,
  resolutions, ROS topics, `T_cam_imu` / `T_cn_cnm1` semantics, and
  `timeshift_cam_imu` with the explicit
  `reference_time = camera_time + time_offset_seconds` convention. Chained
  transforms are composed into one reference frame on read and reconstructed
  on write.
- All four native entries accept contiguous buffer exporters, release the GIL
  around parsing/formatting, use mmap and direct sinks through the public
  registry, validate complete documents during inspection, and keep the
  runtime dependency set NumPy-only. PyYAML was added only to `[test]` as an
  independent permissively licensed oracle.
- The shared native YAML subset is deliberately bounded and schema-specific:
  mappings, quoted/bare scalars, inline/block numeric sequences, multiline
  flow sequences, and OpenCV's exact `!!opencv-matrix` tag are supported.
  Duplicate nodes, aliases, arbitrary tags/directives, tab indentation,
  overlong lines/documents, non-finite values, invalid extents, and malformed
  transforms reject. The XML subset requires the real `opencv_storage` root,
  exact matrix type tags, one occurrence per known node, supported entities,
  and no trailing wrapper/content.

Verification and validation evidence (2026-07-24):

- 75 focused record/codec cases cover source-copy isolation, view lifetime and
  DLPack, empty records, ragged offsets, every presence mask, XYZW identity,
  canonical sign, controls/duplicates, K/D/R/P bit identity, empty ROS
  distortion, hand-derived Kalibr chain composition, camera0 versus IMU
  references, 40 randomized coefficient round trips, malformed documents,
  mmap-buffer address equality, closed-map lifetime, sink byte identity,
  public detection/inspection/capabilities, and non-truncating writer guards.
- Independent PyYAML and stdlib ElementTree oracles validate all serialized
  fields. The four new codecs are also in the 34-entry single-file
  bytes-versus-mmap, direct-sink, inspection, readonly-buffer, truncation, and
  mutation-fuzz sweeps. The full registry is now 36 codecs including the two
  COLMAP directory formats.
- Five-run representative medians measured native/oracle read ratios of
  62.75x (`opencv_yaml`), 2.43x (`opencv_xml`), 76.92x
  (`ros_camera_info`), and 91.56x (`kalibr`). A 1.65 MB valid padded YAML
  fixture reduced traced input allocation from 1.659 MB on the bytes path to
  0.010 MB on the warmed mmap path. The complete one-run 36-codec benchmark
  sweep completed without failures.
- The final full local MSVC suite passes 2,147 tests with three documented
  optional skips. Repository-wide Ruff and `git diff --check` are clean; the
  pre-existing nanobind interpreter-shutdown diagnostics remain non-fatal.
- The clean local cp312-abi3 Windows wheel exposes all 36 registry entries and
  `CameraRig`, passes the installed-wheel smoke for all four calibration
  formats, contains no leaked build/include/library directories, and retains
  NumPy as its only unconditional runtime dependency. The isolated validation
  used a refreshed package cache because the wheel version and filename were
  intentionally unchanged during local rebuilds.
- Manual memory-safety, format-correctness, and test-soundness review found and
  fixed null-range construction for empty optional arrays, public/input matrix
  shape disagreement, XYZW absent-transform identity, writer-generated
  overlong lines, shadowable YAML duplicates, silently ignored malformed
  optional matrices, and an XML root/trailing-content gap. Fable remains
  unavailable locally; Linux sanitizer and Linux/macOS cibuildwheel validation
  remain user-gated remote actions.

##### B3.3 PoseGraph + g2o — complete locally

Implementation:

- `PoseGraph` owns ordered signed-int64 node ids, float64 node translations and
  XYZW quaternions, canonical fixed-node flags, typed edges by endpoint id,
  float64 relative translations/quaternions, and full bitwise-symmetric 6×6
  information matrices. Closed metadata pins preserved quaternion sign,
  node-to-reference estimates, the exact
  `source.inverse() * target` edge convention, unspecified source translation
  units, and `(tx,ty,tz,qx,qy,qz)` information-variable order. Factories copy
  sources while all numeric properties expose lifetime-safe zero-copy views.
- `g2o` accepts exactly `VERTEX_SE3:QUAT`, `EDGE_SE3:QUAT`, `FIX`, blank lines,
  and comments. Vertex ids use g2o's nonnegative signed-32-bit domain;
  quaternions are XYZW and unit-length checked; each edge expands the 21
  row-major upper-triangle coefficients into an exact symmetric matrix.
  Duplicate/missing ids, duplicate fixes, unknown parameter or mixed graph
  records, non-finite values, non-unit quaternions, wrong token counts, NULs,
  and lines over 1 MiB reject rather than dropping graph content.
- The deterministic writer emits vertices in record order, fixed declarations
  in node order, then edges, formats doubles with 17 significant digits, and
  refuses non-SE3 types or foreign transform/unit/order conventions. The
  public `.g2o` entry uses mmap input, bounded native sink chunks, full-stream
  metadata validation, distinctive extension/magic detection, and no new
  dependency. A partial selector is intentionally absent: returning a node or
  edge range without an explicit induced/subgraph contract would create
  dangling endpoints or silently change graph meaning.

Verification and validation evidence (2026-07-24):

- 74 focused record/codec cases cover every field and dtype/shape, source-copy
  isolation, view lifetime and DLPack, empty graphs, explicit empty optionals,
  closed metadata, typed edges, fixed nodes before/after vertices, edge-before-
  vertex ordering, hand-derived 90-degree transform composition, exact
  upper-triangle placement, signed zero, 40 randomized bit-exact round trips,
  bounded malformed inputs, readonly mmap address identity, post-unmap
  lifetime, source mutation isolation, direct-sink identity, destination
  preflight, public detection/read/write/inspect, and capabilities.
- An independent strict stdlib/NumPy parser validates every writer field and
  generated golden graph. The convention follows the BSD-3 g2o implementation:
  `EdgeSE3::setMeasurementFromState` stores
  `from.estimate().inverse() * to.estimate()`, and its six error/information
  variables are translation followed by compact quaternion components.
- g2o joins the 35-entry single-file bytes-versus-mmap, direct-sink,
  inspection, readonly-buffer, empty/truncation, and mutation-fuzz sweeps. The
  full registry is now 37 codecs including the two COLMAP directory formats.
  The final local MSVC suite passes 2,221 tests with three documented optional
  skips; Ruff and `git diff --check` are clean.
- On the representative 25,000-node graph (10.6 MB logical, 4.7 MB encoded),
  five-run medians are 104 MB/s write, 248 MB/s in-memory read, and 255 MB/s
  public mmap read. The independent writer/reader measure 50/98 MB/s, so the
  native reader is 2.53× faster. Mmap and the direct sink each remove the full
  4.7 MB traced Python allocation; sink throughput is 106 versus 103 MB/s, and
  inspection is 1.31× faster than full decode while omitting record arrays.
- The clean local cp312-abi3 Windows wheel exposes all 37 registry codecs,
  `PoseGraph`, and the g2o capability metadata; the refreshed isolated install
  passes the packaged g2o read/write/detect/inspect smoke. Its 36 archive
  members contain no leaked build/include/library directories, and NumPy
  remains the only unconditional runtime dependency.
- Manual memory-safety, format-correctness, and test-soundness review found and
  fixed a possible empty-buffer null-pointer arithmetic path and a signed-zero
  fidelity hole where numerically symmetric but bitwise-different matrix
  triangles could pass the writer guard. Fable remains unavailable locally;
  Linux sanitizer and Linux/macOS cibuildwheel validation remain user-gated
  remote actions.

#### B4. COLMAP database — complete locally

Implementation:

- `FeatureSet` owns canonical float32 keypoints in all COLMAP 2/4/6-column
  layouts, optional uint8/float32 descriptors, optional scores, persisted image
  identity/size/camera/time/extractor metadata, and explicit absent-versus-empty
  SQL-row state. `MatchGraph` owns canonical low/high image pairs and exact
  pair ids, ragged raw and verified u32 matches, optional scores,
  F/E/H/config, and WXYZ second-from-first relative poses.
- `ColmapDatabase` couples validated cameras and prior-focal flags to ordered
  features, the match graph, and `PRAGMA user_version`. Aggregate validation
  checks unique ids/names/pairs, camera references and dimensions, match
  endpoint/index bounds, finite values, canonical flags, and SQLite INTEGER
  limits before a writer opens its destination.
- SQLite 3.53.4 is vendored as the official public-domain amalgamation with
  SHA3-256 provenance. It is linked privately with double-quoted string
  literals, deprecated APIs, loadable extensions, and default memory-status
  accounting disabled; filename URI interpretation remains disabled so paths
  are literal.
- `_core.read_colmap_db`, `read_colmap_db_image`,
  `read_colmap_db_pair`, `write_colmap_db`, and `inspect_colmap_db` use native
  read-only connections or one rollback-capable write transaction. Reads
  refuse unknown schema payload, unsupported nonempty tables, malformed BLOB
  extents, duplicate rows, missing endpoints, and invalid match indices.
- The public `colmap_db` registry entry detects SQLite magic and
  `database.db`, exposes `image_id` and unordered `pair` selectors, and reports
  SQL-only row/count/shape metadata without fetching feature or match BLOBs.
  Writes preserve the existing database on failure and remove a newly-created
  incomplete file.

Verification and validation evidence (2026-07-24):

- The 45-pass focused MSVC suite (one POSIX-only literal-filename case skipped)
  triangulates exact SQL rows with stdlib `sqlite3`, reads pycolmap-created
  databases, and has pycolmap 4.1.1 read SceneIO output. It covers sparse ids,
  reversed pair requests, all geometry, absent/empty BLOBs, float write guards,
  large BLOB bounds, two injected rollback points, locked/read-only databases,
  exception handle release, owner lifetime after file removal, schema drift,
  Unicode paths, duplicate target rows, and 20 randomized exact round trips.
- The related public I/O, mmap, partial, and capability sweep passes 242 tests
  with the one POSIX-only case skipped; the complete final suite and clean
  wheel result are recorded in the current checkpoint above.
- A five-run 9.65 MB logical fixture in a 9.92 MB database measured native and
  independent transaction writes at 178/185 MB/s and full materializing reads
  at 1,405/1,634 MB/s. Metadata inspection was 8.50× faster than full native
  read; one-image and one-pair selectors were 13.10× and 16.31× faster.
  Native write/read/inspect/select paths each traced below 0.05 MB of Python
  allocation.
- The complete one-run 38-codec benchmark sweep finishes without failures.
  The local cp312-abi3 Windows wheel retains NumPy as its only unconditional
  dependency, contains no leaked build/include/library trees, links SQLite
  statically, and passes the installed-wheel database smoke. A clean sdist
  contains every pinned SQLite/codec/record source, excludes generated
  workspace output, rebuilds in isolation, and passes the same smoke.
- Manual three-lens review found and fixed ownerless score arrays, statement
  cleanup on prepare failure, newly-created-file cleanup after rollback,
  literal filename semantics, partial duplicate-row/index/endpoint validation,
  and UTF-8 filesystem handling. Fable remains unavailable locally; Linux
  sanitizer and Linux/macOS cibuildwheel validation remain user-gated.

#### B5. Self-contained splat formats

##### B5.1 SuperSplat compressed PLY — complete locally

Implementation:

- `_core.read_compressed_ply`, `read_compressed_ply_points`, and
  `write_compressed_ply` implement the binary-little-endian PlayCanvas schema:
  256-row chunks, 11/10/11-bit positions and log scales, largest-three
  2/10/10/10 quaternions, RGBA8, and optional 9/24/45-byte SH rows.
- The reader accepts both the current 18-float per-chunk color-range schema and
  the legacy 12-float direct-color schema. It rejects unknown elements or
  properties, invalid element order/counts, non-finite/reversed chunk ranges,
  float32 SH overflow, and any truncated or trailing payload.
- The deterministic writer uses the reference recursive Morton ordering and
  current color-range schema. Loss is explicit in capability metadata. It
  refuses NaNs, zero/non-finite quaternions, non-finite positions/SH, and log
  scales outside the reference writer's `[-20, 20]` interval rather than
  clamping them. Infinite logit opacity is retained because RGBA8 exactly
  represents alpha endpoints.
- Public `.compressed.ply` compound-extension dispatch outranks plain `.ply`;
  header classification distinguishes compressed Gaussian, raw Gaussian,
  point, and future mesh schemas. Inspection parses only the bounded PLY header,
  and point selection validates the complete container while allocating only
  selected record rows.

Verification and validation evidence (2026-07-24):

- The encoded body for a deterministic 513-point SH2 vector is byte-identical
  to PlayCanvas `splat-transform` 3.1.6 commit
  `6b07ba05d731eac1163ad4ff1b14e47e5e3f162c`; an independent NumPy/struct
  decoder triangulates all four SH degrees and the legacy schema.
- Twenty-one focused cases cover deterministic bytes, quantized decode,
  current/legacy layouts, public detect/read/write/inspect/partial dispatch,
  mmap lifetime, source-mutation isolation, malformed headers and extents,
  writer destination preflight, alpha endpoints, empty containers, and a
  generated 100 MiB-class sparse partial-read fixture. The codec also joins
  every registry-wide mmap/bytes, direct-sink, inspection, partial,
  readonly-buffer, truncation, and mutation-fuzz sweep.
- The complete local MSVC suite passes 2,287 tests with four documented skips;
  Ruff, `git diff --check`, and the NumPy-only packaged smoke are clean.
- On the representative 200,000-point cloud (11.2 MB logical, 3.3 MB encoded),
  five-run medians are 341 MB/s write and 97 MB/s public mmap decode.
  Inspection is 1,230.84× faster than full decode and a 1/16 point selection is
  15.01× faster. Mmap and the direct sink each remove the 3.3 MB Python
  whole-file allocation; the partial path sampled 0.3 MB versus 13.7 MB RSS
  growth for full decode.
- Manual memory-safety, format-correctness, and test-soundness review found and
  fixed a possible null pointer passed to a zero-length SH append, rejection of
  valid decoded alpha endpoints on rewrite, and finite chunk colors that would
  overflow float32 SH storage. Fable remains unavailable locally; Linux
  sanitizer and Linux/macOS cibuildwheel validation remain user-gated.

##### B5.2 PlayCanvas SOG — complete locally

- The compiled codec reads and deterministically writes current SOG v2 as
  either a classic bundled ZIP or an unbundled `meta.json` directory. It
  exposes buffer, mmap/path-native, direct-sink, metadata-inspection, and point
  range paths through the public registry and records its quantized/lossy
  contract in capability metadata.
- Required position, scale, quaternion, opacity/DC, and optional degree-1
  through degree-3 SH layers are lossless WebP. The codec implements the
  reference texture dimensions, inverse-log position transform,
  smallest-three quaternion representation, shared codebooks, SH palette, and
  Morton ordering. Missing, lossy, mismatched, non-finite, unsupported, or
  ambiguous inputs are rejected rather than silently converted.
- ZIP metadata and member names, methods, flags, dimensions, codebook sizes,
  label ranges, classic-ZIP limits, and aggregate extents are bounded and
  reconciled. Unbundled writes encode before mutation, use same-directory
  temporary files, and roll back existing regular-file targets on failure.
  Point ranges allocate only selected record rows, although WebP necessarily
  decodes complete layers because it provides no sub-image random access.
- The independent Pillow/NumPy/standard-library ZIP oracle covers SH degrees
  0–3. Both SceneIO- and PlayCanvas-produced SH2 archives were decoded and
  re-exported by pinned `splat-transform` 3.1.6 commit
  `6b07ba05d731eac1163ad4ff1b14e47e5e3f162c`; means, scales, quaternions,
  opacities, DC, and residual SH were bit-identical in both directions.
- Twenty-eight dedicated tests cover oracle parity, deterministic encoding,
  bundled/unbundled parity, mmap and read-only buffers, mutation isolation,
  path preservation, lifetime-sensitive inputs, partial allocation, and
  malformed metadata/ZIP/WebP cases. The complete local MSVC suite passes
  2,315 tests with four documented skips; Ruff and `git diff --check` are
  clean.
- A generated 1,900,000-point, 106.4 MB logical fixture keeps traced Python
  allocation below 4 MiB for an eight-row point selection. On the 200,000-point
  benchmark, five-run medians are 35 MB/s write, 454 MB/s in-memory decode,
  and 430 MB/s public mmap decode. Inspection is 73.65× faster than full
  decode; mmap and the direct sink each remove the 2.9 MB Python whole-file
  allocation.
- A clean ABI3 wheel contains 36 expected members, leaks no build headers or
  libraries, declares only `numpy>=1.26` unconditionally, links only standard
  Python/Windows runtimes, and passes the isolated NumPy-only wheel smoke.
- Manual memory-safety, format-correctness, and test-soundness review found and
  fixed JSON-number narrowing that caused a one-ULP position mismatch against
  PlayCanvas, attempted replacement of a non-file layer target, and aggregate
  ZIP-size accounting that omitted container overhead. Fable is unavailable
  locally; Linux sanitizer and Linux/macOS cibuildwheel validation remain
  user-gated.

##### B5.3 KSplat v0.1 — complete locally

- The compiled codec reads every identified v0.1 section and compression level
  (0–2), including degree-0 through degree-2 SH, and writes one deterministic
  bucketed section. The pinned project includes a canonical generator, so
  read/write support is justified; degree-3 SH and unknown versions reject.
- Buffer, public mmap/path, direct-sink, metadata-inspection, and point-range
  paths are wired through the registry with explicit lossy capability
  metadata. Multi-section point ranges allocate only selected record rows.
- Pinned official vectors and an independent struct/NumPy oracle cover all
  compression levels and SH degrees. SceneIO-produced degree-2 files at all
  three compression levels also decode through the pinned JavaScript loader:
  means, normalized WXYZ quaternions, and SH are exact; scale-log conversion
  is exact for levels 1 and 2 and differs by at most one float32 rounding step
  (`7.45e-09`) at level 0.
- Thirty-five dedicated tests cover all nine compression-level/SH-degree
  writer combinations, official vectors, twenty randomized valid cases,
  multi-section ranges, mmap and read-only lifetime, mutation isolation,
  malformed headers/buckets/records, half subnormals, exact block boundaries,
  truncation, trailing bytes, writer guards, and empty clouds. The focused
  registry/API/mmap/partial sweep passes 228 tests; the complete local MSVC
  suite passes 2,350 tests with four documented skips.
- A generated 2,400,000-point, 105.6 MB level-0 fixture keeps traced Python
  allocation below 4 MiB for an eight-row point selection. On the standard
  fixture, five-run medians are 568 MB/s write, 988 MB/s in-memory decode, and
  874 MB/s public mmap decode. Inspection is 332.84× faster and point
  selection 16.56× faster than full decode; mmap and direct-sink paths remove
  the 4.8 MB whole-file Python allocation. The complete 41-codec benchmark
  also finishes without an error.
- A clean ABI3 wheel contains 36 expected members, leaks no build headers or
  libraries, declares only `numpy>=1.26` unconditionally, links only standard
  Python/Windows runtimes, and passes the isolated NumPy-only wheel smoke.
- Manual memory-safety, format-correctness, and test-soundness review found
  and fixed a half-subnormal exponent error, a multi-section partial-range
  underflow with out-of-bounds-read potential, bucket-ID aliasing at exact
  block boundaries and planar extents, and an unsafe float-to-uint64 boundary
  check. Fable is unavailable locally; Linux sanitizer and Linux/macOS
  cibuildwheel validation remain user-gated.

Wave B exit:

- every default-wheel G2 item appears in `sceneio.capabilities()` and the
  registry-wide E2E sweep;
- the default install remains numpy-only and all native code is vendored,
  pinned, permissively licensed, and statically linked;
- all codec behaviors registered at Wave B exit, benchmarks, and golden bytes
  remain green;
- the dependency-wave remote validation in section 12.10 passes.

### 12.4 Wave C — canonical mesh tier

The mesh record is the gate; codec work must not invent format-specific
topology containers.

1. **`Mesh` and `MaterialSet` — complete locally**
   - represent polygon boundaries with offsets plus indices;
   - distinguish vertex, corner, face, primitive, and material domains;
   - preserve normals, UV sets, colors, material ranges, transforms, texture
     references, alpha mode, and coordinate metadata;
   - validate offsets, indices, aliasing, lifetime, empty meshes, and very large
     ragged topology before any codec lands.
2. **Mesh PLY — complete locally**
   - reuse the generic PLY parser while preserving face lists and
     vertex/face properties;
   - dispatch point, mesh, and Gaussian schemas without extension-order
     ambiguity.
3. **OBJ/MTL — complete locally**
   - preserve separate position/UV/normal indices, polygon boundaries,
     smoothing groups, objects/groups, material assignment, negative indices,
     and relative resource resolution;
   - do not silently triangulate or merge index domains.
4. **STL and OFF — complete locally**
   - support binary/ASCII STL with explicit triangle-only write guards;
   - preserve OFF polygon boundaries and supported attributes without implicit
     triangulation.
5. **Plain glTF/GLB — complete locally**
   - implement buffers, buffer views, accessors, sparse accessors, node
     transforms, meshes/primitives, PBR materials, and image references for a
     documented core subset;
   - reject unsupported extensions and Draco payloads explicitly.

Verification uses trimesh/tinygltf-compatible readers plus hand-built binary
fixtures that break SceneIO reader/writer symmetry. Required cases include
non-triangular faces, disjoint index streams, sparse accessors, normalized
integer attributes, byte strides, malformed offsets, external/embedded
resources, cyclic nodes, and path/resource lifetime. Large-mesh benchmarks
cover topology decode, attribute interleave, inspect, primitive selection, and
direct sinks.

Wave C exits only after all five units pass the default wheel matrix with no
silent triangulation, dropped attributes, or material loss.

### 12.5 Wave D — compressed points and sequences

1. **Complete locally:** extend the point-cloud contract with a lossless
   optional sidecar and add plain-LAS formats 4/5/9/10 parity.
2. **Complete locally:** vendor LAZperf 3.4.0
   (Apache-2.0/BSD-3-Clause/BSD-2-Clause) for
   LAZ, retain the same point semantics, add chunk-aware selection, and prove
   bounded decompression memory.
3. **Complete locally:** land `ImageSequence` with frame timestamps/durations,
   dimensions, ownership, and native planar/chroma metadata.
4. **Complete locally:** add image-directory and raw Y4M support; these
   establish sequence and frame-selection semantics without an animation
   library.
5. **Planned after the organization/performance/source gates:** extend WebP
   and PNG to animated WebP/APNG only after blend, disposal, duration, loop
   count, and partial-frame semantics round-trip.
6. **Planned after animated sequence semantics:** add RTMV as a multi-file
   layout over existing camera, image, depth, and sequence records.

Verification includes chunk/frame boundary corruption, long sequences,
timestamp precision, odd chroma dimensions, disposal/blend goldens, random
access equal to full-decode slices, deterministic directory manifests, and
100 MiB/1 GiB-class RSS tests. The already successful LAZ dependency-wave wheel
run predates the sequence additions; the current sequence head and later
source-closure changes each require a fresh build-only wheel-matrix run.

### 12.6 Wave E — optional scientific libraries

First add one common `SCENEIO_WITH_*` build/manifest pattern with disabled,
enabled, and unavailable states. Then land:

1. HDF5 and hloc layouts;
2. TIFF;
3. E57;
4. Parquet plus the canonical `Table` record.

Each library is pinned and statically built where the license and platform
permit. Default wheels must continue importing and passing the original suite
with every optional feature off. Full-feature wheels must expose accurate
capabilities and pass oracle parity. The validation matrix covers both
configurations on GCC 10, AppleClang, and MSVC and checks wheel dependencies,
artifact size, import time, thread behavior, and clean process shutdown.

TIFF starts with unambiguous strips/tiles, numeric sample formats, and explicit
photometric handling. HDF5 starts with numeric datasets and hloc's documented
layout. E57 starts with supported point scans. Parquet starts with the canonical
column types represented by `Table`. Unsupported filters, schemas, null/union
types, or metadata are rejected rather than coerced.

### 12.7 Wave F — chunked and heavyweight ecosystems

1. Implement Zarr v2, then v3, over a native `TensorDict` store abstraction;
   validate directory trees, chunk codecs, array selection, and consolidated
   metadata against zarr-python.
2. Define the minimal `Scene` contract before optional OpenUSD; start with
   meshes, cameras, nodes, and transforms and reject unrepresented composition,
   variants, instancing, and animation.
3. Define `SparseGrid` before optional OpenVDB; begin with named scalar numeric
   grids, transforms, background values, active bounds, and grid/window
   selection.

No G6 format enters release wheels until correctness passes and wheel size,
startup cost, platform support, and dependency closure are measured and
explicitly accepted.

### 12.8 Wave G — explicit policy decisions

AVIF, JPEG-XL, and Draco-compressed glTF remain policy-gated. For each, record:

- the approved implementation and exact license;
- the patent-policy decision;
- static-build and wheel-matrix evidence;
- supported fidelity subset and oracle;
- artifact-size/performance impact;
- explicit user approval to enter the implementation queue.

An exclusion is a valid closed state. An unexplained pending row is not.

### 12.9 Per-commit verification gate

For every C++/CMake unit, use the repository interpreter and this order:

```powershell
uv pip install -e ".[dev,test]"
.venv/Scripts/python.exe -c "from sceneio import _core; print(_core)"
.venv/Scripts/python.exe -m pytest -q tests/codecs/test_<format>.py
.venv/Scripts/python.exe -m pytest -q tests/test_io_api.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check
git diff --check
.venv/Scripts/python.exe bench/bench_io.py --runs 5 --require-o4-gains --require-o5-inspect-gains --require-o5-partial-gains
.venv/Scripts/python.exe -m sceneio._wheel_smoke
```

Replace the symbol smoke with explicit new symbol assertions and add
record-focused tests where applicable. A unit does not commit if any of these
is true:

- the oracle and SceneIO disagree outside a documented lossy tolerance;
- raw/public compatibility or a golden byte stream changes unintentionally;
- mmap, lifetime, partial, or sink memory structure regresses;
- the same-run benchmark guard reports a retained-path regression;
- any of the three review lenses has an unresolved finding;
- capabilities, docs, test collection, and registry entries disagree.

The commit must include the codec/record, parity and memory tests, benchmark
builder/result, capability metadata, wheel smoke, documentation, and this exact
trailer:

```text
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

### 12.10 Dependency-wave validation gate

After all local commits in a dependency wave are green:

1. Build an sdist and a clean local cp312-abi3 Windows wheel.
2. Install the wheel in a fresh Python 3.12 environment containing only NumPy
   plus smoke-only oracle dependencies; run `_wheel_smoke`, explicit new-symbol
   checks, and one public read/write/inspect/partial case per new codec.
3. Inspect the Windows wheel contents and native dependencies; ensure no build
   tree, headers, static libraries, or undeclared DLLs leaked into it.
4. With explicit user authorization, push the branch and dispatch:

   ```powershell
   gh workflow run sanitizers.yml --ref phase0-nanobind-core
   gh workflow run publish.yml --ref phase0-nanobind-core
   ```

   The manual `publish.yml` run is build-only: it creates and smoke-tests
   manylinux2014 x86-64, macOS arm64, and Windows amd64 abi3 wheels plus the
   sdist; it cannot publish.
5. Require green normal CI, instrumented Linux, minimal-feature, full-feature,
   and cibuildwheel lanes as applicable. Download artifacts and verify wheel
   tags, imports, capabilities, smoke results, and `auditwheel`/`otool`/Windows
   dependency closure.
6. Record workflow links, artifact names/hashes, compiler/platform results,
   skips, and any platform-specific thresholds in the completion evidence.

Remote validation failure reopens the responsible work package. A local pass
does not override a compiler, instrumented, or clean-wheel failure.

### 12.11 Release and PyPI validation

Publication uses `.github/workflows/publish.yml`; no local `twine upload` or
manual artifact replacement is part of this plan.

Before the first release, the user must create the SceneIO PyPI trusted
publisher for the GitHub repository, workflow `publish.yml`, and environment
`pypi`. Then:

1. confirm every release format is `Validated`, not merely implemented locally;
2. reconcile the capability manifest and both coverage documents;
3. set one version in `pyproject.toml`, build locally, and verify package
   metadata;
4. create a signed/annotated matching `vX.Y.Z` tag only with explicit user
   approval;
5. push the tag, which rebuilds all wheels and the sdist and publishes through
   OIDC only after all artifact jobs pass;
6. verify the PyPI file set, hashes, metadata, and clean installation on each
   supported platform;
7. run public read/write/inspect smoke from the published artifacts before
   marking the release shipped.

Branch pushes, workflow dispatches, tags, and PyPI publication remain explicit
user-gated actions. The earlier build-only `publish.yml` run succeeded at
`daf991ab`, before ImageSequence/Y4M. After the current Linux and instrumented
blockers are fixed locally, the next remote validation action is to rerun
normal/instrumented CI and a build-only `publish.yml` matrix at the then-current
head, not to create a release tag.

### 12.12 Program completion criteria

The format-gap program is complete only when:

- every row in section 2.2 is `Shipped`, `Optional` with tested off/on behavior,
  or `Excluded/policy-gated` with an owner and decision;
- every available codec satisfies the registry-driven E2E, oracle parity,
  malformed-input, lifetime, large-memory, inspect/partial, sink, benchmark, and
  wheel contracts;
- the default runtime dependency remains NumPy only;
- all native dependencies have approved provenance and close on the supported
  wheel matrix;
- docs, capabilities, installed artifacts, and PyPI metadata describe the same
  supported subsets;
- no pending remote validation result or unresolved three-lens finding remains.
