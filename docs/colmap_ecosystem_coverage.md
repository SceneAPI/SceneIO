# COLMAP ecosystem I/O coverage

This document is the authoritative gap matrix for interoperability with the
user-owned `colmap_mod` repository. It complements
[`format_coverage.md`](format_coverage.md), which lists SceneIO's live public
codec registry.

Reference snapshot:

- repository: `C:\Users\opsiclear\Desktop\projects\colmap_mod`
- commit: `de15b08a2dba98b55d6ddfb7cedac147838afbb4`
- upstream COLMAP formats: BSD-3-Clause
- OpsiClear additions: used with the repository owner's explicit
  authorization and reimplemented in SceneIO under Apache-2.0
- C1d source inventory: pinned `src/colmap/scene/database_sqlite.cc`,
  `src/colmap/scene/database.h`, `src/colmap/geometry/pose_prior.h`,
  `src/colmap/scene/marker.h`, `src/colmap/scene/pair_provenance.h`,
  `src/colmap/feature/types.h`, `src/colmap/util/types.h`,
  `src/colmap/scene/database_ownership.h`, and
  `src/colmap/scene/database_ownership.cc`, with the pinned database and Python
  tests used as behavioral references.

No FFmpeg/libav implementation, build dependency, runtime dependency, or
encoded-video implementation is included. Encoded containers may be used only
as external verification references.

## Closure boundary

Full closure means that portable scene, reconstruction, feature, dense-MVS,
calibration, and interchange data can be read and written without silent field
loss. It does not mean that SceneIO adopts application caches, diagnostic
reports, solver traces, hardware-specific engines, or every command-line input
list as a first-class codec.

Status terms:

- **complete**: represented losslessly with read/write coverage and a
  differential or independent oracle;
- **implemented locally**: code and focused tests exist; full local and
  cross-platform gates remain;
- **verified locally**: the full local suite, lint, differential and memory
  checks, benchmark, wheel smoke, and three independent reviews pass;
- **partial**: useful fields are supported, but a documented persisted field or
  companion file is not;
- **planned**: in the lean closure implementation queue;
- **adapter**: supported outside the 54-codec core registry because it is a
  workflow bundle rather than a standalone scene format;
- **reference only**: inventoried for verification, not implemented.

## Current compatibility matrix

| Persisted surface | Current SceneIO status | Closure action |
|---|---|---|
| Legacy COLMAP sparse binary: cameras/images/points3D | complete | Retain byte identity |
| Modern sparse binary: rigs/cameras/frames/images/points3D | complete | Retain five-file byte identity, models 0-17, multi-sensor rigs, bounded writes, and the exact-commit three-toolchain validation |
| Legacy and modern sparse text twins | complete | Retain value parity, binary-text-binary identity, and the exact-commit three-toolchain validation |
| Markers and marker projections, binary/text | planned | Extend `Reconstruction` with lossless typed arrays; optional sidecars remain absent when no values exist |
| Image-time, point-frame, and time-frame sidecars | planned | Preserve exact IDs, timestamps, sync groups, labels, version, and file-presence state |
| ChArUco board and calibration sidecars | planned | Add typed board/calibration records with exact per-image poses and errors |
| Stock COLMAP 3.13 database | complete | Exact schema, typed rows, selected-profile writer, conversion report, and transactional validation |
| Stock COLMAP 4.1.1 database | complete | Exact schema, typed rows, selected-profile writer, conversion report, and transactional validation |
| Current upstream database | complete | Exact schema, recovered cameras, selected-profile writer, conversion report, and transactional validation |
| Current OpsiClear/MAXX database | complete | Exact ownership plus timing, quality, provenance, markers, typed descriptors, scores, video metadata, extended priors, and exact selected-profile writer |
| Database profile import/export reports | complete adapter | Structured destination-free compatibility and field-loss report |
| COLMAP MVS depth maps | implemented locally | Repo-owned `width&height&1&` camera-Z float32 codec; distinct from Gipuma DMB |
| COLMAP MVS normal maps | implemented locally | Repo-owned planar-wire/HWC-record float32 XYZ codec |
| Consistency graphs | implemented locally | Bounded ordered CSR over exact `(column,row,count,images...)` tuples |
| Fused point visibility `.vis` | implemented locally | Bounded ordered point/image CSR with exact `fused.ply.vis` detection |
| Canonical COLMAP dense workspace and configs | implemented locally adapter | Lazy `sceneio.colmap_mvs` topology, patch-match/fusion configs, nested names, explicit map dispatch, and cross-file validation |
| PMVS/CMP-MVS export topology | implemented locally adapter | Opaque encoded-image paths plus exact projection text; PMVS Bundler name list and raw-domain `vis.dat` are read/write |
| NVM model | complete | No new codec |
| Bundler bundle | complete with adapter companion | Core bundle values plus repository-owned one-name-per-line PMVS/Bundler list I/O |
| Point/mesh PLY | complete | Keep SceneIO implementation; use current upstream only as a validation reference |
| CAM export | planned | Small guarded write adapter |
| Recon3D export | planned adapter | Directory writer for `Recon/` payload and image maps |
| VRML camera/point export | planned | Guarded write-only adapter |
| Rig config JSON | partial overlap only | Add a dedicated `CameraRig` adapter; generic calibration YAML/XML is not equivalent |
| Project INI and joint-BA/alias JSON | planned adapter | Preserve unknown keys and exact numeric text; do not add Boost |
| SIFT text import and pair/match text | planned | Small dependency-free feature/pair codecs |
| Sim3 and alignment text | planned | Small typed geometry adapters |
| MappingInput `PCMAPIN` v1/v2 | opaque partial | Replace opaque-only helper with a semantic versioned codec |
| MegaLoc descriptor/pair artifact directory | planned adapter | Map numeric payloads to typed records and preserve manifest/name tables |
| IncrementalVLAD NPZ | partial | Numeric arrays work; Unicode metadata needs an explicit metadata adapter |
| Raster pixels shared with SceneIO codecs | partial by extension | Keep deterministic in-tree codecs; add TIFF separately if selected |
| EXIF/XMP metadata | planned adapter | Add bounded metadata records and sidecar parsing without Exiv2 |
| Encoded video and container readers/writers | reference only | No FFmpeg/libav or fork video implementation; use only for external verification |
| Hardware engines, ONNX/TensorRT state, RoMaXX runtime artifacts | reference only | Treat as application runtime state, not scene interchange |
| Solver logs, profiling, reports, and decoded/staged caches | outside closure | No core codec |

## Lean implementation sequence

### C0 - modern sparse models and bounded writes

- [x] Extend `Reconstruction` with lossless rig/frame SoA and CSR fields.
- [x] Auto-detect paired rigs/frames files while preserving legacy three-file
  output.
- [x] Support camera models 0-17.
- [x] Preserve binary five-file bytes against pycolmap 4.1.1.
- [x] Preserve text values and binary-text-binary bytes.
- [x] Use bounded direct binary file writes rather than output-sized strings.
- [x] Refuse conversion to reconstruction formats that cannot represent
  rig/frame metadata.
- [x] Refuse known unrepresented fork sidecars instead of ignoring or leaving
  them stale.
- [x] Run the full local suite, benchmark delta, wheel smoke, and three-agent
  final review.
- [x] Validate the exact commit on MSVC, manylinux2014 GCC 10, and
  AppleClang.

Local C0 evidence for pushed implementation commit `801bd77` on 2026-07-28:

- the complete suite passed 3,573 tests with four documented skips; the
  focused COLMAP, partial-read, compatibility, benchmark-qualification,
  assembly-contract, and license gate passed 197 tests;
- Ruff, `git diff --check`, the editable wheel smoke, and the package-license
  inventory passed;
- the bounded legacy binary writer reached a 1,058 MB/s median, 2.20x the
  pre-C0 writer, while the committed modern five-file benchmark reached a
  286 MB/s median; a fresh-child scaling check kept the 30.6 MB output's RSS
  delta below half of its output size;
- Ampere (`lean_r6_arch_review`), Epicurus (`lean_r6_test_review`), and
  Lagrange (`lean_r6_platform_docs_review`) completed independent final
  reviews with no remaining blockers.

Remote C0 evidence for correction and validation commit `7046761`:

- [standard CI run 30421438904](https://github.com/SceneAPI/SceneIO/actions/runs/30421438904)
  passed all 11 jobs, including the full suite, reconstruction parity on three
  platforms, manylinux2014 GCC 10 portability, the deterministic 50-codec
  structure check, and the strict five-run performance guard;
- [instrumented run 30421438926](https://github.com/SceneAPI/SceneIO/actions/runs/30421438926)
  passed the complete ASan/UBSan suite and dedicated native lifetime job;
- [nonpublishing distribution run 30422291891](https://github.com/SceneAPI/SceneIO/actions/runs/30422291891)
  passed the exact source archive, macOS AppleClang arm64, Windows MSVC amd64,
  manylinux2014 GCC 10 x86-64, and combined inventory jobs; PyPI was skipped;
- artifact SHA-256 digests: source archive
  `fe72b54eedd31dad41045baed1a19319c4ae5fdbef7c306c23e355a58bf4b575`,
  macOS wheel bundle
  `cc56c53aff03dee174c1b0d8bae046735d4b7da6abddae758404b6d80253686b`,
  Windows wheel bundle
  `51e29a9a5e0dd4f1a1a92966ef1be94461b4f518b23dcf0ea870ff5172832ff3`,
  and manylinux wheel bundle
  `8366f2065e57bc29f9751a91035ae94b22b78de9a7712054bd67464bb539b313`.

### C1 - database profiles

- [x] Freeze exact 3.13, 4.1.1, current-upstream, and current-MAXX schema
  fixtures.
- [x] Add a versioned profile catalog and exact structural inspection layer;
  keep the six-table payload reader guarded until each additional field is
  represented.
- [x] Represent recovered `camera1`/`camera2` values, endpoint-local SQL NULL,
  and prior-focal flags in `MatchGraph`.
- [x] Represent stock rigs, rig sensors, frames, frame data, and both stock
  pose-prior layouts.
- [x] Represent extended MAXX pose priors, descriptor
  dtype/type/name/dimension, keypoint colors,
  match scores, pair provenance, timing/video metadata, quality, markers, and
  ownership metadata.
- [x] Make the writer emit an exact selected profile while retaining the
  established hybrid route for constructed core records.
- [x] Refuse in-place writes whenever a selected profile cannot preserve an
  existing represented table or column.
- [x] Differentially validate schemas, values, null/empty distinctions, and
  rollback behavior with sqlite3, live pycolmap 4.1.1, and pinned source/DDL
  fixtures for the other profiles.

C1a profile evidence:

- stock profiles are pinned to COLMAP 3.13.0
  `0b31f98133b470eae62811b557dc2bcff1e4f9a5`, COLMAP 4.1.1
  `a0d785fba74b2664f31edc4a29026a8b27c00f67`, and current upstream
  `64805cb870b574a569dccc34918d95a2db2b2fee`;
- the MAXX ownership profile is pinned to the authorized
  `colmap_mod` snapshot `de15b08a2dba98b55d6ddfb7cedac147838afbb4`;
- migration-derived pre-ownership databases are deliberately reported as
  legacy/unknown until C4's final row-classification pass; they are
  not mislabeled as one synthetic exact schema;
- inspection compares the full normalized SQLite schema structure together
  with `application_id`, `user_version`, and the MAXX ownership row. A matching
  version alone reports `profile="unknown"`;
- independent schema signatures for 3.13, 4.1.1, and MAXX were captured from
  the authorized `colmap_mod` database exporter/creator; the current-upstream
  signature was frozen from official `64805cb` DDL. Tests also mutate schema,
  application id, version, and ownership fields one at a time;
- at the C1a checkpoint, current-upstream recovered cameras and populated
  companion tables remained guarded. C1b later landed recovered-camera reads,
  C1c landed stock rig/frame/prior reads, and C1d then landed represented MAXX
  extension reads.

Local C1a verification:

- editable MSVC build, Ruff, diff check, and the complete suite pass with
  3,594 tests and four documented skips;
- the three review lenses report no remaining blocker after correcting writer
  identity guards, ownership cardinality, locale-independent normalization,
  and independent fixture provenance;
- the three-run `colmap_db` harness reports 1,070 MB/s full read, 179 MB/s
  direct write, 1.80 ms exact-profile inspection, and 5.00x inspection
  speedup over full decode, with no Python-sized staging allocation.

C1b recovered-camera contract:

- current-upstream `two_view_geometries.camera1/camera2` BLOBs use the exact
  repository-owned little-endian wire order: camera id, model id, width,
  height, prior-focal byte, parameter count, and float64 parameters. MAXX uses
  the same wire layout; C1d now represents its additional columns and tables;
- `MatchGraph.camera1_present` / `camera2_present` preserve each SQL NULL,
  prior-focal arrays preserve the serialized flag, and
  `recovered_camera1(index)` / `recovered_camera2(index)` return typed
  `Camera` values only when present;
- full reads and indexed pair reads use the same parser. Bounds, exact
  exhaustion, known model/parameter cardinality, dimensions, canonical flags,
  and finite numeric values are checked before the record is returned;
- recovered cameras retain the producer's full domain: every camera id except
  the `UINT32_MAX` sentinel and all positive uint64 dimensions. These values
  are validated separately from SQLite camera-table/image-pair limits;
- Python construction accepts one `Camera | None` value per pair and endpoint,
  so mixed present/NULL state can be copied without an inaccessible placeholder;
- the legacy hybrid writer refuses recovered cameras. Exact current/MAXX
  emission remains C1e work, so this unit cannot silently discard the new
  fields;
- the unchanged legacy fixture regression benchmark reports 1,137 MB/s full
  read, 154 MB/s direct write, 1.81 ms inspection, and 0.59-0.60 ms indexed
  image/pair reads with no Python-sized staging allocation. Recovered-camera
  correctness and allocation behavior are covered by the dedicated current
  profile full/partial/lifetime tests rather than claimed by that legacy row;
- complete local validation covers 3,620 tests: 3,616 passed and four
  documented skips;
  the focused recovered-camera gate passes 24 tests, Ruff and wheel smoke pass,
  and the collection contract is 3,620 nodes at
  `a22141fcd211da2437e14a4ba062ab0356e7e1285cf6f7e80846bf2a05703fba`;
- Ampere, Epicurus, and Lagrange completed the native-lifetime,
  correctness/test, and platform/documentation reviews. Findings from the
  first round were corrected before final sign-off.

C1c stock companion-row contract:

- `ColmapDatabase.rig_frames` exposes a nested owned `ColmapRigFrameSet`
  containing non-sentinel uint32 rig/frame/sensor IDs, uint64 data IDs and
  CSR offsets,
  reference sensors, non-reference sensors, nullable `sensor_from_rig`
  transforms in WXYZ order, and frame-to-datum assignments;
- `ColmapDatabase.pose_priors` exposes `ColmapPosePriorSet`. Stock 3.13 rows
  normalize their image-linked association while retaining
  `generalized=False`; 4.1.1 and current rows retain independent prior IDs,
  correlation triples, coordinate-system codes, position, covariance, and
  gravity;
- presence flags preserve SQL NULL independently from the numeric payload.
  Exact-size producer BLOBs retain signed zero and NaN payload bits. Public
  covariance views are row-major while the codec explicitly transposes the
  Eigen column-major wire buffer;
- full reads validate the complete rig/frame/prior aggregate. Existing
  image/pair selectors remain index-local and do not decode unrelated
  companion BLOBs;
- inspection reports rig, sensor, frame, frame-data, and pose-prior counts
  plus the legacy/modern layout without decoding BLOBs;
- the legacy writer refuses every populated companion record before opening
  the destination. Exact stock and MAXX writers remain C1e work;
- final local validation collects 3,659 nodes at
  `d98dd314db7a05ab87d392864988de8a7fab52cde37605216b121af6e9ca2d6d`
  and passes 3,655 tests with four documented skips. The focused codec gate
  passes 127 tests with one expected Windows filename skip; wheel smoke,
  Ruff, diff checks, and all three independent review lenses pass. Remote
  sanitizer and Linux/macOS wheel validation remain release gates.

C1d MAXX extension read contract:

- `FeatureSet` preserves independent SQL presence for descriptor dtype,
  logical dimension, and open extractor name; uint8, int8, float16, float32,
  and float64 descriptor matrices retain their raw row-major bytes. Optional
  RGB keypoint colors, image quality, and uint32 image time IDs are exposed by
  full and indexed image reads.
- `MatchGraph` exposes per-pair score-row presence, float32 scores parallel to
  raw matches, raw provenance flags, and retrieval-score presence.
  Provenance-only pairs are retained even when neither endpoint image nor a
  match/geometry row exists. Unknown provenance bits and IEEE score payloads
  are not rewritten.
- Extended pose priors preserve nullable XYZW `cam_from_world` rotations,
  3x3 rotation covariance, and 6x6 pose covariance. SQLite Eigen matrices are
  transposed to public row-major arrays. The pose variable order is rotation
  tangent xyz then translation xyz, with explicit radian/metre covariance
  unit tags.
- `ColmapMarkerSet` preserves marker/projection rows, independently nullable
  world positions/covariances, point sentinels, and projection indices.
  Projection coordinates are top-left-origin pixels; numeric SQLite values
  are carried as stored.
- `ColmapVideoMetadataSet` is metadata-only. Source paths are inert strings;
  no file is opened and no encoded-media implementation is present. Presence
  arrays distinguish SQL NULL from empty text, and frame PTS/time metadata is
  independent from `images.time_id`.
- `ColmapMaxxSchemaInfo | None` exposes the exact ownership row. Inspection
  reports all extension row counts, typed descriptor shape/dtype, and all four
  ownership values without fetching BLOBs.
- Independent stdlib `sqlite3`/`struct`/NumPy fixtures cover every field,
  NULL-versus-empty state, column-major matrices, IEEE payloads, malformed
  extents/types/layouts, partial-read isolation, handle release, nested-view
  lifetime, and pre-mutation legacy-writer refusal. At the C1d checkpoint,
  exact-profile emission was deliberately deferred to C1e.
- Final local validation collects 3,732 nodes and passes 3,727 tests with five
  documented skips. The focused C1d gate passes 286 tests with two expected
  skips; Ruff, diff checks, a source-archive-derived NumPy-only wheel smoke,
  distribution inventory verification, and all three independent review
  lenses pass.
- The three-run 9.9 MB database benchmark records 1,067 MB/s full/path read,
  158 MB/s direct write, 2.192 ms inspection, 0.999 ms image selection, and
  0.949 ms pair selection, with bounded traced Python allocation. Exact-commit
  remote instrumentation and GCC 10/AppleClang package validation remain
  release gates.

### C1e - exact profile writes and conversion reports

- `sceneio.write(database, path, profile=...)` and
  `sceneio.write_colmap_db(...)` select one frozen profile name. A decoded
  exact database preserves its profile when `profile` is omitted; a
  constructed `sceneio-hybrid-v1` record keeps the established hybrid route.
  The low-level two-argument writer also retains its compatibility behavior.
- `sceneio.colmap_database_conversion_report` returns the source/target
  profiles, fixed identity changes, a writable flag, and a stable ordered list
  of represented-data incompatibilities. The report has no path argument
  and cannot touch a destination.
- Every selected-profile write completes aggregate and target-profile
  analysis before filesystem inspection. Stock profiles reject MAXX fields;
  3.13 additionally requires untyped uint8 SIFT descriptors and the
  image-linked prior layout; recovered cameras require current or MAXX.
  Per-keypoint generic scores have no column in any frozen database profile
  and always reject.
- MAXX output requires an explicit valid ownership record. SceneIO never
  invents a `colmap_mod` producer version or commit. Video source paths and
  codec names remain inert stored strings; writing them does not inspect or
  decode media.
- Replacement runs inside one rollback-capable SQLite transaction. Before
  commit, the writer checks foreign keys, SQLite integrity, exact canonical
  schema, ownership, application ID, and user version. Unrepresented tables,
  views, triggers, and indexes refuse before mutation. New-file failures
  remove the database and SQLite sidecars after handles are released.
- Exactness means the frozen schema plus every represented value, SQL
  presence bit, and BLOB byte. Whole-file SQLite bytes, historical
  `sqlite_sequence` counters, and page layout are not part of the contract.
  Zero-row dynamic payloads are emitted canonically as present empty BLOBs;
  this matches the existing record contract, which does not distinguish
  empty BLOB from SQL NULL for those required data columns. MAXX retrieval
  scores retain the producer-semantic float32 domain.
- Same-profile populated round-trips cover all four profiles, including
  covariance transposes, recovered-camera wire bytes, all MAXX extension
  rows, full/indexed/inspection agreement, cross-profile refusal, source
  immutability, schema-object refusal, and three injected rollback stages.
  Live pycolmap 4.1.1 and independent frozen DDL/row-byte fixtures remain the
  local oracles. Exact de15 live-producer validation stays optional until the
  matching binding is supplied.
- Three-run 9.65 MB local medians measure 153/1,141 MB/s write/read for
  3.13, 153/1,118 for 4.1.1, 160/1,131 for current, and 150/1,018 for MAXX.
  Every profile records 0.000 MB traced write allocation and 0.003 MB mapped
  read allocation at the harness precision.
- Migration-derived pre-ownership databases continue to report
  `profile="unknown"`; their import classification is explicitly assigned to
  C4 rather than guessed during exact emission.

### C2 - dense MVS

- [x] Add depth and normal-map records/codecs with inspect, mmap, window reads,
  and direct sinks.
- [x] Add consistency-graph and fused-visibility CSR codecs.
- [x] Add lazy adapters for canonical COLMAP, PMVS, and CMP-MVS companion
  topology without decoding encoded media.
- [x] Use hand-built golden payloads plus current-upstream COLMAP as the
  independent oracle.
- [x] Correct every DMB document: SceneIO `dmb` is Gipuma DMB, not the COLMAP
  MVS matrix format.

C2 local implementation evidence:

- The registry now has 54 built-ins. The four appended `dense` codecs all
  read, write, inspect, mmap, and stream; depth and normal additionally expose
  bounded pixel windows.
- Depth records declare camera-Z, unknown reconstruction scale, and
  nonpositive invalid values. Normal records expose HWC float32 while the wire
  remains planar XYZ in the OpenCV camera frame. Consistency and visibility
  preserve stored list order and declare the positional
  `mvs_sequential_image_index` domain.
- Independent `struct`/NumPy goldens cover hostile IEEE values, planar order,
  sparse tuples, malformed bounds, exact sink bytes, mapping lifetime, and
  payload-sized allocation. Consistency and fused visibility validate and
  count before exact record allocation, including few-entry/many-link and
  malformed trailing-payload shapes. Installed pycolmap is used only where
  its binding semantics are reliable.
- `sceneio.colmap_mvs` parses `__all__`, `__auto__, N`, and explicit
  patch-match sources, ordered fusion names, nested map paths, PMVS/CMP
  projection pairs, PMVS Bundler name lists, and raw `vis.dat`. Encoded images
  remain opaque paths.
- PMVS visibility values intentionally retain
  `raw_colmap_image_id_or_mvs_index`: the authorized producer writes persisted
  image IDs while the matching consumer treats values as positional indices.
  SceneIO preserves the values except COLMAP's reserved invalid uint32
  sentinel and makes no false semantic conversion. Parsing and writing use
  bounded chunks rather than whole-row Python lists/strings, and row
  permutation validation uses a compact chunked NumPy bitmap.
- PMVS Bundler-profile workspaces use `bundle.rd.out` plus opaque `visualize`
  images, require the bundle-declared image count to match that inventory, and
  do not require the raw-PMVS `txt` or `vis.dat` companions.
- Patch-match configs accept upstream comma or semicolon separators and
  upstream-style empty repeated/trailing fields, then enforce nonempty,
  unique, non-reference sources.
- Workspace validation compares dense companion dimensions, checks every
  decoded consistency/visibility index against the MVS positional table, and
  requires `fused.ply.vis` point count to equal the companion PLY vertex
  count.
- Legacy models use their sparse image sequence for that table; modern models
  use registered frame/camera data order and are regression-tested with an
  images-file order that deliberately differs.
- The final local gate collects 3,832 nodes and passes 3,827 tests with five
  documented optional/platform skips. Ruff, diff checks, wheel smoke, the
  independent-oracle benchmark, and the three architecture, test, and
  platform/documentation reviews are clear.

### C3 - sparse extensions and compact interchange

- [ ] Add marker/projection, time/frame, and ChArUco sidecars.
- [ ] Add Bundler `list.txt`, CAM, Recon3D, VRML, rig JSON, SIFT text,
  pair/match text, and Sim3 adapters.
- [ ] Add semantic MappingInput v1/v2 and MegaLoc artifact adapters.
- [ ] Preserve optional-file presence and reject unsupported conversions.

### C4 - metadata and final closure

- [ ] Add the selected TIFF route and bounded EXIF/XMP metadata adapter if
  dependency qualification succeeds.
- [ ] Update the registry, public API, license inventory, wheel smoke, format
  coverage, and benchmark catalog.
- [ ] Run full local gates and the three-toolchain nonpublishing validation.
- [ ] Record reference-only encoded-video coverage without adding its code.
- [ ] Close the matrix with every row marked complete, adapter, reference only,
  or outside closure; no ambiguous partial row remains.

## Verification required for every unit

1. Exact fast-versus-reference differential fixtures, including empty,
   malformed, truncated, overflow, optional-field, and stale-companion cases.
2. Record lifetime, zero-copy view, conversion-loss guard, and memory-bound
   tests.
3. Focused tests, `tests/test_io_api.py`, full pytest, Ruff, `git diff --check`,
   benchmark qualification, and wheel smoke with `.venv/Scripts/python.exe`.
4. Three independent reviews covering memory/lifetime, format correctness, and
   test/portability/documentation soundness.
5. A green commit with the required co-author trailer before moving to the next
   unit.

Remote builds are validation, not publication. Tags, releases, and PyPI
publication remain separate user-controlled actions.
