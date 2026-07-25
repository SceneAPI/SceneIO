# Format-gap implementation, verification, and validation plan

- **Status:** execution in progress after SceneIO 0.2.0. G0, safetensors, PTS,
  scalar DMB, BAL, BMP/TGA, the compiled `FlowField` record, typed FLO, typed
  PFM depth, typed PNG depth, typed scalar EXR depth, generic point PLY, and
  PCD, `StateTrajectory`/EuRoC, `CameraRig` with OpenCV/ROS/Kalibr
  calibration, `PoseGraph`/g2o, and the `FeatureSet`/`MatchGraph`-backed
  COLMAP database and SuperSplat compressed PLY are complete locally.
  PlayCanvas SOG and KSplat are next in the default-wheel sequence.
  Cross-platform wheel and instrumented validation remains a user-gated remote
  action.
- **Current branch:** 39 compiled codecs, all read/write and inspectable, with
  bounded partial reads where their containers permit them.
- **Scope:** close every unblocked format gap declared by SceneIO's coverage
  documents without reimplementing the 0.2.0 codec tier.

This plan is subordinate to the current shipped-state inventory in
`format_coverage.md`. The older per-format checklist in
`coverage_roadmap.md` predates the compiled tier and still labels several
shipped codecs and records as pending. Phase G0 below removes that drift before
new codec work starts.

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
| `Mesh` | vertex positions; ragged face indices; optional vertex/corner normals, UVs, colors; primitive/material ranges; coordinate metadata | generic PLY, OBJ, STL, OFF, glTF |
| `MaterialSet` | material names; base/emissive factors; metallic/roughness; alpha mode; texture image references, UV sets, and sampler metadata | OBJ/MTL, glTF, USD |
| `FeatureSet` — complete locally | keypoints, descriptors with dtype/shape metadata, scores, image size, image id/name | COLMAP DB, hloc |
| `MatchGraph` — complete locally | image-pair ids, ragged raw/verified match pairs, scores, optional F/E/H models and relative pose | COLMAP DB, hloc |
| `PoseGraph` | pose nodes, typed edges, relative transforms, information matrices | g2o |
| `StateTrajectory` | timestamps, position/orientation, velocity, gyroscope bias, accelerometer bias, frame/unit metadata | EuRoC state CSV |
| `CameraRig` | ordered cameras, rig-to-camera extrinsics, names/ids, frame and unit metadata | OpenCV, ROS, Kalibr |
| `FlowField` — complete locally | HxWx2 f32 vectors plus component order, axes, row order, units, and invalid-value convention | typed FLO adapter |
| `ImageSequence` | lazy frame references, timestamps/durations, dimensions, packed images or native planar frames with chroma subsampling metadata | image directories, Y4M, animated WebP/APNG |
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
| Splat | SuperSplat SOG / compressed PLY, KSplat | — |
| Point cloud | LAS waveform formats 4/5/9/10, LAZ, E57 | count-prefixed PTS, generic point PLY, and PCD |
| Mesh | mesh PLY, OBJ/MTL, STL, OFF, glTF/GLB, USD/USDZ; optional Draco is policy-gated | — |
| Tensor/feature/table | HDF5, hloc layout, Zarr v2/v3, Parquet | safetensors, COLMAP features/matches |
| Image and depth | TIFF | BMP, TGA, typed PFM depth, typed PNG depth, typed scalar EXR depth, scalar DMB |
| Optical flow | — | compiled `FlowField` plus typed FLO |
| Calibration | OpenCV YAML/XML, ROS `camera_info`, Kalibr YAML | — |
| Sequence/dataset | image directory, Y4M, animated WebP, APNG, RTMV layout | — |
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
| EuRoC state CSV | `StateTrajectory` | timestamps, pose, velocity and biases with no field loss | independent CSV parser |
| DMB — complete locally | `DepthMap` | dimensions/type header, float payload, scale/unit metadata | independent NumPy parser |
| Typed PFM/PNG/EXR depth — complete locally | `DepthMap` | explicit scale, unit, invalid-value and confidence semantics layered over existing payload codecs | numpy/Pillow/OpenEXR |
| Typed FLO flow — complete locally | `FlowField` | preserve component, axis, unit, row-order, and unknown-value semantics rather than returning an untagged ndarray | independent numpy parser |
| OpenCV YAML/XML | `Camera`/`CameraRig` | matrices, distortion models, explicit model mapping | OpenCV test extra |
| ROS `camera_info` | `Camera` | K/D/R/P and distortion model | independent YAML parser |
| Kalibr YAML | `CameraRig` | chained extrinsics, camera models, time offsets | independent YAML parser |
| g2o | `PoseGraph` | vertices, typed edges, information matrices | independent parser plus generated goldens |
| SuperSplat SOG | `GaussianCloud` | clustered/quantized fields, explicit lossy metadata | reference loader vectors |
| KSplat | `GaussianCloud` | supported versioned reader first; writer only after canonical output is identified | reference loader vectors |
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

#### G3.1 Mesh record and generic PLY mesh

Generic PLY is the reference codec for validating every `Mesh` buffer:

- polygon boundaries and indices;
- vertex versus corner attributes;
- colors and alpha;
- primitive/material ranges;
- coordinate frame and units.

No implicit triangulation is permitted in the record constructor or PLY codec.

#### G3.2 OBJ/MTL

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

#### G3.3 STL and OFF

- STL: binary and ASCII, triangle-only write guard, facet-normal preservation
  policy, and robust binary/ASCII detection.
- OFF: polygonal OFF plus explicitly selected color variants; preserve polygon
  boundaries.
- Oracle with trimesh and independent minimal parsers.

#### G3.4 glTF/GLB core

Implementation:

- Vendor cgltf for glTF 2.0 JSON/GLB parsing and writing.
- Support external buffers, data URIs, buffer views, accessors, sparse
  accessors, node transforms, mesh primitives, normals, UVs, colors, and
  indices.
- Define a minimal scene wrapper so multiple nodes/primitives are not silently
  flattened.
- PBR materials map through `MaterialSet`. Morph targets, skins, animation, and
  cameras are added only when the corresponding record fields exist; otherwise
  reject them clearly.
- `inspect` lists scenes, nodes, primitives, accessors, dtypes, and counts from
  metadata.
- Partial reads select a scene/node/primitive or accessor where the buffer
  layout permits bounded access.
- Add optional Draco only after the policy gate is resolved; it must never be
  required for uncompressed glTF/GLB.

Oracle:

- pygltflib and trimesh, plus Khronos conformance/sample assets whose licenses
  permit redistribution.

Validation for G3:

- Windows/macOS/manylinux builds with the vendored parsers.
- Round-trip files opened by at least two independent consumers.
- Large mesh fixtures demonstrate bounded mmap input and direct sink output.

### G4 — Compressed point clouds and sequences

#### G4.1 LAZ

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

The same package resolves plain LAS waveform point formats 4/5/9/10. Add the
wave-packet fields to `PointCloud` only if they can be represented without
penalizing ordinary points; otherwise add a dedicated optional sidecar buffer.
Readers and writers must preserve waveform descriptor references and packet
offset/size/location fields or reject those point formats. They may not decode
them as a lower point format and drop the waveform data.

#### G4.2 ImageSequence and raw Y4M

Implementation:

- Image-directory sequence: deterministic natural ordering, optional manifest,
  timestamps, heterogeneous-frame rejection, and lazy frame decoding.
- Y4M: parse stream header and frame headers; retain Y, U, and V planes plus
  chroma subsampling, range, and matrix metadata natively. RGB conversion is an
  explicit operation outside the codec.
- Support only explicitly listed uncompressed Y4M chroma layouts and reject
  layouts the planar frame contract cannot represent.
- Add frame-range and single-frame selectors.
- Writers stream frames and never concatenate the full sequence in memory.

Oracles:

- independent Y4M parser and imageio/Pillow for individual frame files.

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

- 39 compiled registry codecs with read, write, inspect, mmap or path-native
  input, and direct file sinks;
- O0-O5 complete for the existing codec tier;
- `FlowField`, typed FLO, typed PFM depth, typed PNG depth, and typed scalar EXR
  depth complete;
- 2,287 local tests pass with 4 documented platform/optional skips, Ruff and
  `git diff --check` are clean;
- the complete 39-codec benchmark and packaged NumPy-only wheel smoke pass;
- generic point PLY, PCD, StateTrajectory/EuRoC, CameraRig calibration,
  PoseGraph/g2o, the COLMAP feature database, and SuperSplat compressed PLY
  are complete locally;
- instrumented Linux and Linux/macOS wheels have not yet been run for this
  dependency wave because pushing and dispatching remote workflows are
  user-gated.

Status terms are strict:

| Status | Meaning |
|---|---|
| Planned | contract exists, but implementation has not started |
| Implemented locally | code, focused parity tests, and documentation exist |
| Verified locally | full suite, lint, differential/memory tests, benchmark guard, and three-lens review pass |
| Validated | required compiler, instrumented, sdist, and wheel lanes pass |
| Shipped | validated artifacts were published from a matching version tag |
| Policy-gated | implementation cannot start until the named project decision is recorded |

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

##### B5.2 PlayCanvas SOG — next

- Implement bundled ZIP and unbundled-directory SOG v2 with explicit
  quantization and lossy metadata.
- Decode every required lossless-WebP layer and preserve all representable
  `GaussianCloud` fields; reject missing, lossy, mismatched, or unsupported
  layers.

##### B5.3 KSplat — queued after SOG

- Implement only identified KSplat versions; begin read-only if no canonical
  writer can be independently established.
- Verify against reference loader vectors and preserve every
  `GaussianCloud` field or reject the file. Benchmark decode, encode where
  supported, inspect, point selection, and large-cloud memory.

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

1. **`Mesh` and `MaterialSet`**
   - represent polygon boundaries with offsets plus indices;
   - distinguish vertex, corner, face, primitive, and material domains;
   - preserve normals, UV sets, colors, material ranges, transforms, texture
     references, alpha mode, and coordinate metadata;
   - validate offsets, indices, aliasing, lifetime, empty meshes, and very large
     ragged topology before any codec lands.
2. **Mesh PLY**
   - reuse the generic PLY parser while preserving face lists and
     vertex/face properties;
   - dispatch point, mesh, and Gaussian schemas without extension-order
     ambiguity.
3. **OBJ/MTL**
   - preserve separate position/UV/normal indices, polygon boundaries,
     smoothing groups, objects/groups, material assignment, negative indices,
     and relative resource resolution;
   - do not silently triangulate or merge index domains.
4. **STL and OFF**
   - support binary/ASCII STL with explicit triangle-only write guards;
   - preserve OFF polygon boundaries and supported attributes without implicit
     triangulation.
5. **Plain glTF/GLB**
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

1. Extend the point-cloud contract for LAS waveform packet fields and first add
   lossless plain-LAS formats 4/5/9/10 parity.
2. Vendor laz-perf (Apache-2.0) for LAZ, retain the same point semantics, add
   chunk-aware selection, and prove bounded decompression memory.
3. Land `ImageSequence` with frame timestamps/durations, dimensions, ownership,
   and native planar/chroma metadata.
4. Add image-directory and raw Y4M support first; these establish sequence and
   frame-selection semantics without an animation library.
5. Extend WebP and PNG to animated WebP/APNG only after blend, disposal,
   duration, loop count, and partial-frame semantics round-trip.
6. Add RTMV as a multi-file layout over existing camera, image, depth, and
   sequence records.

Verification includes chunk/frame boundary corruption, long sequences,
timestamp precision, odd chroma dimensions, disposal/blend goldens, random
access equal to full-decode slices, deterministic directory manifests, and
100 MiB/1 GiB-class RSS tests. Wave D requires a new dependency-wave wheel run
because laz-perf changes the native build.

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
user-gated actions. The next authorized remote action should be a build-only
`publish.yml` dry run plus the sanitizer workflow, not a release tag.

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
