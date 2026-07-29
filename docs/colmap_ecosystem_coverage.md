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
| Modern sparse binary: rigs/cameras/frames/images/points3D | verified locally | Run the exact verified commit through the nonpublishing MSVC, GCC 10, and AppleClang validation after five-file byte identity, models 0-17, multi-sensor rigs, bounded writes, and the full local gate passed |
| Legacy and modern sparse text twins | verified locally | Run the exact verified commit through the nonpublishing three-toolchain validation after value parity, binary-text-binary identity, and the full local gate passed |
| Markers and marker projections, binary/text | planned | Extend `Reconstruction` with lossless typed arrays; optional sidecars remain absent when no values exist |
| Image-time, point-frame, and time-frame sidecars | planned | Preserve exact IDs, timestamps, sync groups, labels, version, and file-presence state |
| ChArUco board and calibration sidecars | planned | Add typed board/calibration records with exact per-image poses and errors |
| Stock COLMAP 3.13 database | partial | Add an exact stock profile and image-linked pose-prior representation |
| Stock COLMAP 4.1.1 database | partial | Add rigs/frames/generalized pose priors and typed descriptors |
| Current upstream database | incompatible | Add `camera1`/`camera2`, exact schema fingerprint, and profile-aware writer |
| Current OpsiClear/MAXX database | incompatible | Represent ownership metadata, videos/timing, quality, provenance, markers, colors, descriptor metadata, scores, and extended priors |
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
- [ ] Validate the exact commit on MSVC, manylinux2014 GCC 10, and
  AppleClang.

Local C0 evidence on 2026-07-28:

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

### C1 - database profiles

- [ ] Freeze exact 3.13, 4.1.1, current-upstream, and current-MAXX schema
  fixtures.
- [ ] Replace the exact six-table whitelist with a versioned profile and
  capability layer.
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
