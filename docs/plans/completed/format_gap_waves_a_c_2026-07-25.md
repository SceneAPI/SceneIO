# Completed format-gap Waves A-C evidence

This dated record preserves the completed Wave A, Wave B, and Wave C
implementation and validation evidence exactly as it appeared in the active
[`format-gap implementation plan`](../../format_gap_implementation_plan.md).
The active plan retains stable section headings and links back here.

Navigation for contextual references preserved inside the immutable evidence:

- “section 12.9” points to the active
  [`per-commit verification gate`](../../format_gap_implementation_plan.md#129-per-commit-verification-gate);
- “current checkpoint above” now points to canonical
  [`format coverage`](../../format_coverage.md#format--data-structure-coverage);
- “section 12.10” points to the active
  [`dependency-wave validation gate`](../../format_gap_implementation_plan.md#1210-dependency-wave-validation-gate).

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
  The dependency-wave compiler-instrumented jobs and three-platform wheel
  build pass at `a5e7fa4`.

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
  applied manually. The dependency-wave compiler-instrumented jobs and
  three-platform wheel build pass at `a5e7fa4`.

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
  applied manually. The dependency-wave compiler-instrumented jobs and
  three-platform wheel build pass at `a5e7fa4`.

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
  unavailable locally; the dependency-wave compiler-instrumented jobs and
  three-platform wheel build pass at `a5e7fa4`.

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
  the dependency-wave compiler-instrumented jobs and three-platform wheel
  build pass at `a5e7fa4`.

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
  and UTF-8 filesystem handling. Fable remains unavailable locally; the
  dependency-wave compiler-instrumented jobs and three-platform wheel build
  pass at `a5e7fa4`.

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
  overflow float32 SH storage. Fable remains unavailable locally; the
  dependency-wave compiler-instrumented jobs and three-platform wheel build
  pass at `a5e7fa4`.

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
  locally; the dependency-wave compiler-instrumented jobs and three-platform
  wheel build pass at `a5e7fa4`.

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
  check. Fable is unavailable locally; the dependency-wave
  compiler-instrumented jobs and three-platform wheel build pass at
  `a5e7fa4`.

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


---

Return to the
[`active format-gap implementation plan`](../../format_gap_implementation_plan.md#125-wave-d--compressed-points-and-sequences)
or the [`completed-plan index`](README.md).
