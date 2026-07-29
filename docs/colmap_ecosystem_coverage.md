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
- **adapter**: supported outside the 50-codec core registry because it is a
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
| Stock COLMAP 3.13 database | partial | Exact profile identity is implemented; add image-linked pose-prior and populated rig/frame representation |
| Stock COLMAP 4.1.1 database | partial | Exact profile identity is implemented; add populated rigs/frames/generalized pose priors |
| Current upstream database | partial | Exact profile identity is implemented; add `camera1`/`camera2` payloads and the exact writer |
| Current OpsiClear/MAXX database | partial | Exact ownership/profile identity is implemented; represent timing, quality, provenance, markers, colors, descriptor metadata, scores, and extended priors |
| Database profile import/export reports | planned adapter | Emit structured compatibility results and explicit field-loss decisions |
| COLMAP MVS depth maps | planned | New contiguous `width&height&1&` float32 codec; do not alias Gipuma DMB |
| COLMAP MVS normal maps | planned | New HxWx3 float32 record/codec |
| Consistency graphs | planned | New bounded CSR record using actual `(column,row,count,images...)` order |
| Fused point visibility `.vis` | planned | New bounded CSR record |
| COLMAP/PMVS/CMP-MVS workspace topology and configs | planned adapter | Preserve canonical paths, patch-match/fusion config, projections, and visibility companions |
| NVM model | complete | No new codec |
| Bundler bundle | partial | Add optional `list.txt` companion so image names round-trip |
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
- [ ] Represent rigs, rig sensors, frames, frame data, generalized and
  extended pose priors, descriptor dtype/type/name/dimension, keypoint colors,
  match scores, pair provenance, recovered cameras, timing/video metadata,
  quality, markers, and ownership metadata.
- [ ] Make the writer emit an exact selected profile; stop emitting the current
  hybrid schema.
- [ ] Refuse in-place writes whenever a selected profile cannot preserve an
  existing represented table or column.
- [ ] Differentially validate schemas, values, null/empty distinctions, and
  rollback behavior with sqlite3, pycolmap, and `colmap_mod`.

C1a profile evidence:

- stock profiles are pinned to COLMAP 3.13.0
  `0b31f98133b470eae62811b557dc2bcff1e4f9a5`, COLMAP 4.1.1
  `a0d785fba74b2664f31edc4a29026a8b27c00f67`, and current upstream
  `64805cb870b574a569dccc34918d95a2db2b2fee`;
- the MAXX ownership profile is pinned to the authorized
  `colmap_mod` snapshot `de15b08a2dba98b55d6ddfb7cedac147838afbb4`;
- migration-derived pre-ownership databases are deliberately reported as
  legacy/unknown until C1e provides a field-level import classifier; they are
  not mislabeled as one synthetic exact schema;
- inspection compares the full normalized SQLite schema structure together
  with `application_id`, `user_version`, and the MAXX ownership row. A matching
  version alone reports `profile="unknown"`;
- independent schema signatures for 3.13, 4.1.1, and MAXX were captured from
  the authorized `colmap_mod` database exporter/creator; the current-upstream
  signature was frozen from official `64805cb` DDL. Tests also mutate schema,
  application id, version, and ownership fields one at a time;
- this unit deliberately does not loosen the payload reader. Current-upstream
  recovered cameras and populated stock/MAXX companion tables remain guarded
  until C1b-C1d provide lossless records.

Local C1a verification:

- editable MSVC build, Ruff, diff check, and the complete suite pass with
  3,594 tests and four documented skips;
- the three review lenses report no remaining blocker after correcting writer
  identity guards, ownership cardinality, locale-independent normalization,
  and independent fixture provenance;
- the three-run `colmap_db` harness reports 1,070 MB/s full read, 179 MB/s
  direct write, 1.80 ms exact-profile inspection, and 5.00x inspection
  speedup over full decode, with no Python-sized staging allocation.

### C2 - dense MVS

- [ ] Add depth and normal-map records/codecs with inspect, mmap, window reads,
  and direct sinks.
- [ ] Add consistency-graph and fused-visibility CSR codecs.
- [ ] Add a workspace adapter for canonical COLMAP and PMVS companion files.
- [ ] Use hand-built golden payloads plus current-upstream COLMAP as the
  independent oracle.
- [x] Correct every DMB document: SceneIO `dmb` is Gipuma DMB, not the COLMAP
  MVS matrix format.

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
