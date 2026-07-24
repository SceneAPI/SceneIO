# Format-gap implementation, verification, and validation plan

- **Status:** execution in progress after SceneIO 0.2.0; G0, G2.1, the PTS
  slice of G2.3, and scalar DMB plus BAL from G2.4 are complete locally.
  BMP/TGA image codecs are also complete locally. Cross-platform wheel and
  instrumented validation remains a user-gated remote action.
- **Current branch:** 29 compiled codecs, all read/write and inspectable, with
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
| `FeatureSet` | keypoints, descriptors with dtype/shape metadata, scores, image size, image id/name | COLMAP DB, hloc |
| `MatchGraph` | image-pair ids, ragged match pairs, scores, optional F/E/H models and inlier masks | COLMAP DB, hloc |
| `PoseGraph` | pose nodes, typed edges, relative transforms, information matrices | g2o |
| `StateTrajectory` | timestamps, position/orientation, velocity, gyroscope bias, accelerometer bias, frame/unit metadata | EuRoC state CSV |
| `CameraRig` | ordered cameras, rig-to-camera extrinsics, names/ids, frame and unit metadata | OpenCV, ROS, Kalibr |
| `FlowField` | HxWx2 f32 vectors plus component order, axes, row order, units, and invalid-value convention | typed FLO adapter |
| `ImageSequence` | lazy frame references, timestamps/durations, dimensions, packed images or native planar frames with chroma subsampling metadata | image directories, Y4M, animated WebP/APNG |
| `Table` | named typed columns, null validity, UTF-8 offsets/data, row count, metadata | Parquet |
| `SparseGrid` / `Scene` | sparse grid values/transforms; scene nodes, transforms, mesh/camera references | OpenVDB, USD/USDZ |

`Mesh` must preserve polygon boundaries through offsets plus indices. A
triangle-only record would force silent triangulation on OBJ/OFF/PLY and is
therefore insufficient. Codecs that inherently require triangles may reject
non-triangular faces at write time or perform an explicit, opt-in conversion
outside the codec.

### 2.2 Format gaps

| Family | Remaining formats |
|---|---|
| Reconstruction and pose | COLMAP database, BAL, EuRoC state CSV, g2o |
| Splat | SuperSplat SOG / compressed PLY, KSplat |
| Point cloud | PTS text, generic point PLY, PCD, LAS waveform formats 4/5/9/10, LAZ, E57 |
| Mesh | mesh PLY, OBJ/MTL, STL, OFF, glTF/GLB, optional Draco, USD/USDZ |
| Tensor/feature/table | safetensors, HDF5, hloc layout, Zarr v2/v3, Parquet |
| Image and depth | TIFF, BMP, TGA, typed PFM/PNG/EXR depth, typed FLO flow, DMB |
| Calibration | OpenCV YAML/XML, ROS `camera_info`, Kalibr YAML |
| Sequence/dataset | image directory, Y4M, animated WebP, APNG, RTMV layout |
| Volumetric/niche | OpenVDB |
| Policy-gated | AVIF, JPEG-XL, Draco compression |

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
 ├─ existing PointCloud ── PCD/generic PLY ──── LAZ/E57
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

#### G2.2 COLMAP database

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

#### G2.3 PTS complete locally; generic PLY and PCD pending

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

Remaining implementation:

- Keep `gaussian_ply` bespoke; add separate generic `ply` dispatch for
  point-cloud and mesh schemas.
- Support PLY ASCII, binary little-endian, and binary big-endian; preserve
  declared scalar/list property types and reject unsupported semantic mappings.
- Support PCD ASCII, binary, and `binary_compressed` LZF layouts.
- Map organized PCD width/height and viewpoint into metadata.
- Inspect headers without reading payloads.
- Provide point ranges for fixed-record binary PLY/PCD. Text and compressed
  variants expose partial reads only if a bounded index can be constructed
  without full payload materialization.

Oracles:

- independent PTS parser plus `plyfile` and Open3D in test extras.

Verification:

- property ordering, endian variants, polygon list lengths, normals, color,
  intensity, NaNs, organized clouds, PCD field counts/types, and LZF blocks;
- PTS declared-count mismatch, missing count, supported column layouts, and
  canonical writer header;
- generic PLY must never auto-detect a Gaussian PLY as a generic point cloud
  when `gaussian_ply` fidelity is required;
- detection reads enough PLY header metadata to choose generic point, generic
  mesh, or Gaussian schemas before extension fallback;
- writer refusal when the selected output format cannot represent a record
  field.

Benchmark:

- ASCII and binary parse/write;
- endian transform;
- PCD LZF compression;
- point-range memory versus full decode.

#### G2.4 Small reconstruction, depth, calibration, and splat formats

Land one codec per green commit:

| Format | Record | Implementation focus | Oracle |
|---|---|---|---|
| BAL — complete locally | `Reconstruction` | camera/point/observation text with a pinned canonical writer | UW specification + independent parser |
| EuRoC state CSV | `StateTrajectory` | timestamps, pose, velocity and biases with no field loss | independent CSV parser |
| DMB — complete locally | `DepthMap` | dimensions/type header, float payload, scale/unit metadata | independent NumPy parser |
| Typed PFM/PNG/EXR depth | `DepthMap` | explicit scale, unit, invalid-value and confidence semantics layered over existing payload codecs | numpy/Pillow/OpenEXR |
| Typed FLO flow | `FlowField` | preserve component, axis, unit, row-order, and unknown-value semantics rather than returning an untagged ndarray | independent numpy parser |
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
5. **PNG depth**
   - Accept only grayscale 16-bit PNG for typed depth. Widen uint16 samples to
     float32 exactly and record the supplied scale; never divide or multiply
     samples during decode.
   - The writer requires every stored float32 sample to be an exact integer in
     `[0,65535]`, rejects confidence and unsupported metadata, and emits the
     same deterministic 16-bit PNG bytes as the existing image writer.
   - Pin named test profiles for TUM (`scale_to_meters=1/5000`, zero invalid)
     and ScanNet/millimeter depth (`scale_to_meters=0.001`, zero invalid)
     without making a profile implicit.
6. **EXR depth**
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
| `features_for=image_id` | COLMAP DB, hloc |
| `matches_for=(image_id1, image_id2)` | COLMAP DB, hloc |
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

## 12. Current execution queue

G0, safetensors, PTS, scalar DMB, BAL, BMP, and TGA have exercised the
expansion machinery without adding a heavyweight dependency. Continue with
small green commits in this order:

1. **Typed depth and flow adapters**
   - add explicit adapters for PFM/PNG/EXR depth and a dedicated flow record
     before changing the existing raw codec return types;
   - preserve existing calls and bytes; pin units, scale, invalid-value, row
     order, confidence, and writer guards;
   - prove adapter output equals the existing raw decode plus declared
     metadata, with no silent numerical conversion.
2. **Generic point PLY and PCD**
   - ship point-cloud schemas first, including ASCII and binary endian paths,
     then add mesh PLY only after the canonical ragged `Mesh` record lands;
   - implement header-only inspection, fixed-record point ranges, PCD LZF,
     organized-cloud metadata, and schema-aware dispatch that cannot steal
     Gaussian PLY;
   - validate against `plyfile` and Open3D and benchmark text, binary, endian,
     compressed, and partial paths.
3. **Record-dependent packages**
   - `Mesh`/`MaterialSet` unlock OBJ, STL, OFF, glTF/GLB, and mesh PLY;
   - `FeatureSet`/`MatchGraph` unlock COLMAP DB and later hloc/HDF5;
   - `StateTrajectory`/`CameraRig`/`PoseGraph` unlock EuRoC, OpenCV, ROS,
     Kalibr, and g2o;
   - each record lands only with its first codec and the record-level
     zero-copy, lifetime, offset/index, and wheel matrix from G1.

After each numbered slice, update the capability snapshot and coverage ledger,
run the common all-codec matrix, record same-run benchmark deltas, complete the
three review lenses, and commit locally. Dependency waves trigger the sdist and
cibuildwheel validation matrix; branch pushes, release workflow dispatches,
tags, and PyPI publication remain explicit user-gated actions.
