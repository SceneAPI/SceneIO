# SceneIO — comprehensive coverage roadmap & execution checklist

> Current shipped and branch-local status is tracked in `format_coverage.md`.
> The status markers below have been reconciled to the live 72-format registry;
> broader checklist boxes remain open where a codec has not completed an
> aspirational per-format or cross-platform gate. The authoritative
> implementation sequence for the remaining formats is
> [`format_gap_implementation_plan.md`](format_gap_implementation_plan.md);
> the prerequisite maintainability and backend-selection work is in
> [`repository_organization_plan.md`](repository_organization_plan.md), with
> its reviewed execution checklist in
> [`next_stage_implementation_checklist.md`](next_stage_implementation_checklist.md).
> The bounded standards-based USD expansion is specified separately in
> [`usd_3d_cv_implementation_plan.md`](usd_3d_cv_implementation_plan.md).
> The 2026-08-02 cross-platform correction changes no roadmap scope or format
> capability. Local MSVC and clean Linux focused checks pass; the exact local
> suite passes 4,372 tests with six documented skips after three
> benchmark-evidence tests were added. Commit `5387350` passes
> compiler run `30738228920` and every dedicated Linux/Windows/macOS and GCC 10
> job in CI run `30738228914`; that run's full suite and 72-row smoke also pass.
> Its final five-run guard found one missing benchmark field for animated AVIF
> independent inspect/frame-range comparison. The follow-up emits direct
> Pillow timings and distinguishes that range metric from COLMAP DB's two
> selector metrics. Follow-up compiler run `30739519901` collects all 4,378
> tests but stops at the stale 4,375 count assertion; its lifetime shard
> passes. At count-correction commit `67acc7b`, compiler-instrumented run
> `30740026804` passes the exact suite and lifetime shard. CI `30740026814`
> passes the suite, all platform/compiler shards, and the 72-row smoke before
> its terminal guard correctly measures animated AVIF's two-frame selection at
> 16.8 MB versus 25.2 MB for full decode. The follow-up classifies that owned
> output by an 18 MB ceiling and 75%-of-full limit instead of the metadata-like
> 1 MB cap; all existing limits remain unchanged. At correction commit
> `54925ea`, compiler-instrumented run `30741117526` and CI run `30741117473`
> are fully green. The latter passes all platform/compiler jobs, the exact
> suite, 72-row smoke/structure, and five-run guard, which records a 1.32x
> selected-range gain and 25.2/16.8 MB full/partial allocation. Hosted
> confirmation is complete; release publication remains separate.
> The first hosted correction run passed every dedicated platform shard. Its
> remaining repository-byte and instrumented-Theora residuals are addressed by
> canonical LF source-manifest rows for libvpx/libogg/libtheora and a documented
> three-file arithmetic correction for upstream libtheora signed deltas and
> bitsets; normal optimized builds are unchanged.
> U0-U5 qualify the bounded provider, records, stage skeleton, and all direct
> static payload kinds. C6 is closed through the explicit static-only Exit B;
> C7 local source-to-wheel qualification is complete. At implementation source
> `47eb2e1`, build-only package run `30703473199` and compiler run
> `30703469313` pass with publication skipped. CI run `30703469317` passes the
> full suite, repaired 67-row smoke/structure, and every platform shard before
> the completed five-run guard identifies one classification gap: USD/USdz
> inspection has the documented TinyUSDZ full-stage cost, and Parquet's named
> selection returns 1.6 MB of logical data. The local correction preserves the
> universal 1 MB cap elsewhere. USD/USdz inspection is capped at 8 MB and 80%
> of full; Parquet selection is capped at 2 MB and 25% of full. Correction
> source `b16ee1c` passes final CI `30705438186`, including all 67 rows and the
> five-run guard, while compiler run `30705438179` passes both jobs.
> Animated WebP is the 55th local codec; the preceding 54-codec hosted package
> evidence remains a dated checkpoint rather than evidence for this addition.
> The current branch-local COLMAP dense checkpoint adds exact depth/normal
> matrices, consistency graphs, fused visibility, and lazy canonical/PMVS/CMP
> workspace adapters. It contains no encoded-media decoder; image paths remain
> opaque and reuse SceneIO's existing still-image codecs when callers choose
> to open them.
> This branch-local checkpoint closes at packaged source `2253e0f`: normal run
> `30469273173`, instrumented run `30469271293`, and nonpublishing
> three-platform package run `30470889876` pass. The exact 54-row benchmark
> structure, sdist, MSVC/GCC 10/AppleClang wheels, installed smokes, and
> combined inventory are verified; publication is skipped.
> R6 is closed at packaged source commit `105b301`: exact-head CI
> `30405666674`, native-runtime validation `30405666673`, and build-only
> three-platform package run `30406706115` pass, with publication skipped.
> The downloaded sdist and all three cp312-abi3 wheels pass independent
> inventory inspection. No roadmap item is automatically activated by this
> closure; later pending-R6 wording is historical and superseded by this note.
> R2 is closed at registry implementation `3e46d82` plus platform-contract
> repair `9928c6d`. R3.1a has split benchmark models, measurements, and
> reporting behind the compatible CLI. R3.1b closes at `0bdfe0f`; normal run
> `30234796010` and compiler-instrumented run `30234796025` pass. R3.2
> family-by-family benchmark extraction closes through: arrays at `6d9ec34`
> with normal run `30236069971` and compiler-instrumented run `30236069959`;
> calibration closes at `5dc03f4` with normal run `30237676629` and
> compiler-instrumented run `30237676648`; raster images close at `6572a76`
> with normal run `30239455960` and compiler-instrumented run `30239455952`;
> meshes close at `613fd26` with normal run `30241711640` and
> compiler-instrumented run `30241711620`; points close at `45e2757` with
> normal run `30244892746` and compiler-instrumented run `30244892600`.
> Reconstruction closes at `76ed21b` with normal run `30247662591` and
> compiler-instrumented run `30247662622`. Sequences close at `4b8c829` with
> normal run `30250394890` and compiler-instrumented run `30250394906`.
> Splats close at `cd32268` with normal run `30253301819` and
> compiler-instrumented run `30253301871`. The runner closes at `cf8d117`
> with normal run `30257105454` and compiler-instrumented run `30257105468`.
> The final R3.2 behavior checkpoint closes at `0e54cf5`: normal run
> `30263506366` and compiler-instrumented run `30263506270` pass. Immutable
> built-in completeness covers exactly 50 ids, runtime extensions remain
> outside repository qualification, and strict comparison mode requires 33
> timed providers while retaining 17 exact reviewed exemptions. R3.3 then
> began with an immutable 44-buffer/3-path/3-directory case catalog under
> `tests/_support/codec_cases.py`; the mmap suite consumes its lower-owned
> deterministic buffer builder. Exact migration commit `9a73892` passes normal
> run `30268797350` and compiler-instrumented run `30268797374`; the duplicated
> local matrix is removed and its exact order, bindings, 43-codec portable
> byte projection, and platform-profiled compressed-PLY semantic fixture
> remain contract-pinned. Exact removal commit `fc86f44` passes normal run
> `30271311308` and compiler-instrumented run `30271309916`. The 14 streaming
> behavior functions now have
> focused ownership in `tests/test_io_streaming.py`; all 16 collected node
> renames are explicit, parameter ids are unchanged, and the complete local
> collection remains 3,345. Exact streaming commit `914702d` passes normal
> run `30274413815` and compiler-instrumented run `30274413693`. Inspection
> now has focused ownership in `tests/test_io_inspection.py`; its 47 tests and
> three helpers preserve all 76 node suffixes under an exact path-only rename
> group. Exact inspection commit `0e21e27` passes normal run `30278777267`
> and compiler-instrumented run `30278777173`. Partial-family migration starts
> with three unchanged array-specific DMB/FLO tests under
> `tests/test_io_partial_arrays.py`. Exact array commit `5009ea0` passes normal
> run `30282057346` and compiler-instrumented run `30282056576`. The image
> unit gives 10 Netpbm/WebP nodes focused ownership and lowers their two shared
> window assertions. Exact image commit `d198560` passes normal run
> `30285128366` and compiler-instrumented run `30285128448`. The mesh unit
> moves its unchanged face-range behavior into
> `tests/test_io_partial_meshes.py`. Exact mesh commit `4294dbe` passes normal
> run `30287854716` and compiler-instrumented run `30287854692`. The point
> unit moves 13 unchanged XYZ/LAS nodes into
> `tests/test_io_partial_points.py` and lowers their shared range assertion.
> Exact point commit `ac1a4d1` passes normal run `30290617469` and
> compiler-instrumented run `30290617607`. The reconstruction unit moves 15
> unchanged COLMAP nodes into `tests/test_io_partial_reconstruction.py` and
> lowers the one fresh-process RSS helper shared with the broad suite.
> Follow-up selector commit `b5e5c55` passes normal run `30296172958` and
> compiler-instrumented run `30296174522`. The final sequence/splat audit
> confirms their dedicated partial behavior was already family-owned and pins
> the seven intentionally cross-family tests that remain shared. Exact R3.3
> closure commit `811cb0d` passes normal run `30300122309` and
> compiler-instrumented run `30300122324`, without a format or public API
> change. R3.4 is implemented locally: a definition-driven installed-wheel
> smoke covers all 50 built-ins, public write/read/inspect, a successful
> public path call for each declared stream-capability direction, and all 32
> selectors declared by 28 codecs, with zero property-specific exemptions.
> Dedicated mmap/sink suites retain independent allocation evidence. The
> complete local suite passes 3,344 tests
> with four documented skips; Ruff and the five-run strict guard pass. Its
> first exact 380-file tree produces a 381-file sdist and 81-member Windows
> ABI3 wheel, and a fresh SceneIO-plus-NumPy environment passes the complete
> installed smoke. R4.1 then splits the native build into four focused CMake
> modules. All 40 codec sources have one of eight family owners, all 16 record
> sources are explicit, the historical `_core` source/link order is retained,
> and fresh MSVC/GCC 10 cache plus compile/link projections match the R3.4
> parent exactly. R4.1 is pushed at `b2cf5d4`; normal run `30310780347` and
> compiler-instrumented run `30310780355` pass. R4.2 closes at pushed commit
> `81e0e1c`:
> one record table and eight codec-family tables own the 16/40 registration
> functions and generate a validated 49-entry native/hybrid inventory. MSVC,
> GCC 10, a focused 416-test sweep, exact 3,354-node collection, and the
> unchanged strict five-run guard pass. The complete suite passes 3,350 tests
> with four documented skips, and Ruff is clean. The exact 398-file source
> tree, 399-file sdist, 81-member Windows ABI3 wheel, and fresh NumPy-only
> installed smoke pass. All three confirmation reviews are clear; normal run
> `30316577366` and compiler-instrumented run `30316577369` pass that exact
> commit. R4.3 and final R4 qualification close at pushed commit `da1d709`.
> All 40 native codec sources are family-nested. Exact-tree MSVC/GCC 10,
> package, public-snapshot, normal CI `30326256230`, and instrumented
> `30326256137` gates pass.
> R5.1 is complete as a backend-intake checkpoint. The stable JPEG
> path remains the repository-owned stb implementation, while pinned
> libjpeg-turbo 3.2.0 is available only through an explicit, default-off
> qualification build. Ordinary builds do not compile the candidate
> translation unit or expose its private build marker. Fresh ordinary-stb,
> explicit-stb, and libjpeg-turbo Windows ABI3 wheels pass the installed
> all-50-codec smoke and contain one native module with no development
> payload. The local 50-row strict-comparison sweep retains the established
> O4/O5 results without a changed threshold. This establishes candidate
> viability and isolation. R5.2's frozen same-corpus installed-wheel
> harness is complete, including production mmap/sink paths,
> output quality and size bounds, startup/repeatability/memory evidence, an
> actual configured-SIMD receipt, and a manual nonpublishing MSVC/GCC
> 10/AppleClang workflow. The clean-wheel MSVC result at `7a88e7c` passes
> 1,596/1,597 frozen gates: the candidate is 4.787x/1.782x faster for
> encode/decode by median geomean but misses the q95 comparative-quality floor
> (`-0.058242 dB` versus `-0.05 dB`). libjpeg-turbo is therefore rejected as
> the combined default and stb remains unchanged. No candidate advanced to
> the user-gated remote comparison. R6 source intake is complete. The corrected
> package graph now requires and verifies Python’s stable ABI, and the local
> Windows/Ubuntu native builds use the expected platform suffixes. The release
> workflow builds every platform wheel from one verified sdist; its final
> exact-tree MSVC package gate and user-gated GCC 10/AppleClang validation
> close R6.

The granular, per‑format execution plan for covering **every relevant file type
that has a permissively‑licensed open‑source option**. Sits below the strategy
(`io_implementation_plan.md`) and the status snapshot (`format_coverage.md`):
this is the *how* — implementation, parity, C++ optimization, and verification —
for each remaining item.

Current test counts, workflow evidence, and the immutable validated checkpoint
are maintained only in
[`format_coverage.md`](format_coverage.md#format--data-structure-coverage);
  this policy roadmap intentionally does not duplicate them. R6 package closure
  is complete. The explicitly requested COLMAP ecosystem portable-data
  adapters are implemented and validated under `sceneio.colmap`; their final
  exact-pushed-tree MSVC/GCC 10/AppleClang package validation passes in run
  `30470889876`.
  The user-directed post-R6 3D-CV format sequence is locally complete for
  Animated WebP, APNG, HDF5/hloc, Zarr, TIFF, E57, Parquet/Arrow IPC,
  OpenVDB, USD/USDZ, bounded read-only RTMV, Ogg/Theora, and bounded temporal
  VP8/VP9 WebM. The provisional
  performance ledger remains a trigger-based optimization backlog rather than
  an active gate.

**License gate (hard):** MIT / BSD / Apache‑2.0 / zlib / libpng / HPND / public
domain only. No copyleft (GPL/AGPL/MPL data libs), no proprietary SDKs, no
patented codecs. Runtime deps: **numpy only** — oracle libs and optional C
libraries are test‑time / feature‑flag only.

---

## 1. Engineering standards — apply to EVERY codec

Each format is one work item; it is **Done** only when all four boxes below are
green. Don't land a codec that skips a box — file a follow‑up instead.

### 1.1 Implementation (the codec recipe)
- [ ] `src/cpp/codecs/<fmt>.cpp` with `read_<fmt>(Source)->Record` and
      `write_<fmt>(const Record&)->bytes`; **read/write only**, no dispatch.
- [ ] Reuse an existing Record or add one under `records/` (see §2). Records are
      **SoA, 64‑byte‑aligned, zero‑copy** to numpy/torch (DLPack).
- [ ] **Conventions as metadata**, never in the arrays: quaternion order, pose
      direction, axis frame, depth scale/unit, color space, opacity/scale
      activation. Reader *records* what it read; **writers guard** (refuse a
      foreign‑convention record) — a normalizer converts on request.
- [ ] Register one `Codec(...)` in `io/registry.py` (+ `sniff`/magic/extension).
- [ ] Stable/default formats keep their production adapter, grammar,
      validation, inspection, partial-read logic, and sinks in this repository.
      Prefer a measured, mature permissive upstream kernel over a bespoke
      algorithm; store the selected source under `src/cpp/third_party/`.
      Separately installed implementations and executables are verification
      oracles, not runtime delegates.
- [ ] Errors → typed `sceneio.errors` (`FormatError` / `ContractViolation` /
      `UnsupportedFeature`); malformed input **raises, never crashes**.
- [ ] Capability flags surfaced: `reads / writes / streams / lossy / needs_dep`.

### 1.2 Parity & testing (three kinds, always)
- [ ] **Cross‑impl equality** — `ours.read(f)` == `oracle.read(f)` (bit‑exact for
      lossless/int; documented `eps` for lossy/quantized).
- [ ] **Round‑trip** — `ours.read(ours.write(x)) == x` (bit‑exact for our own
      formats) **and** `oracle.read(ours.write(x)) == expected` (proves the
      *writer* is spec‑correct, not just self‑consistent).
- [ ] **Convention pins** — decode a known file, assert the *interpreted*
      quantity (a full 4×4 pose, metric depth in meters, a normalized quat) —
      catches WXYZ/axis/scale bugs the raw‑array test misses. Include
      **hand‑derived** known answers (external ground truth), not just a mirror
      oracle.
- [ ] **Cross‑framework** — `np.asarray(rec.x) == torch.from_dlpack(rec.x)`.
- [ ] **Differential fuzzing** — Hypothesis‑generated valid Records → write →
      read → compare; byte‑mutated real files must raise (not crash/OOB).
- [ ] Oracles are **test‑only extras** (`[test]`), pinned for reproducibility.

### 1.3 C++ optimization checklist
- [x] **Release the GIL** (`nb::gil_scoped_release`) around the C++ decode/encode
      body so big files don't block Python and codecs can run in parallel.
- [x] **Zero‑copy out**: decoded buffers become Record‑owned ndarrays with no
      extra copy; bulk `memcpy`/`assign` into SoA, not element loops where a
      block copy works.
- [x] **Fast text parsing**: use `fast_float` (Apache/MIT) / `std::from_chars`,
      **not** `std::istringstream >> double` (retrofit the TUM/KITTI/OBJ/PPM‑ascii
      readers — iostream float parse is ~10–50× slower).
- [x] **mmap sources** for all single-file codecs; COLMAP directory codecs read
      paths directly in C++. Native NPY/FLO payloads return pinned read-only
      mapped ndarray views; PFM retains an owned positive-stride row-flip decode.
      All writers have direct file sinks without an output-sized Python bytes copy;
      protocol conversion completes before sink activation and native short/error
      paths have deterministic cross-platform coverage.
- [x] **SIMD‑friendly hot loops** (quant/dequant, byte‑pack, endian‑swap):
      contiguous, branch‑light, auto‑vectorizable; measure before hand‑writing
      intrinsics.
- [x] **Parallel decode/encode** of measured independent chunks/transforms,
      bounded to eight automatic lanes; one-vs-many output and worker-exception
      tests keep it deterministic.
- [x] Minimize allocations on measured hot paths: fixed-capacity XYZ blocks,
      pre-sized LAS records, and reused codec scratch buffers.
- [x] **Metadata-only inspection** for every registered format: binary headers
      are read directly; headerless text is streamed; no pixel/point/record
      arrays are constructed.
- [x] **Partial reads where the container permits**: PFM/binary P5-P6
      Netpbm/lossless VP8L WebP/FLO/DMB pixel windows; XYZ/PTS/binary
      PLY/PCD/LAS/Gaussian PLY/compressed PLY/SOG/KSplat/SPLAT point ranges;
      mesh PLY/STL/OFF face ranges; EuRoC state ranges; selected safetensors tensors
      and slices; single-image COLMAP binary/text; and COLMAP database image
      and pair selectors. Unsupported subformats and codecs fail explicitly
      instead of falling back to a full decode.

### 1.4 Verification gates (per‑format Definition of Done)
- [ ] All §1.2 tests green **in CI on all 3 platforms** (parity oracles installed).
- [x] The **compiler-instrumented native reliability lane** builds the core and
      vendored libraries, collects the exact full suite, runs focused native
      lifetime controls, and passes the three-case push mmap mutation sweep.
      The default-branch schedule retains the 100-case sweep. The current
      result is recorded in
      [`format_coverage.md`](format_coverage.md#infrastructure--capabilities).
- [ ] **Golden byte‑exact** blob committed for our writer (regenerated by a
      documented script) so encode drift fails loudly.
- [x] **Benchmark vs oracle** recorded (target: ≥ parity on decode throughput,
      large wins on binary formats); a regression gate flags slowdowns.
- [ ] Docs: a row in `format_coverage.md` flips to ✅; conventions documented.

---

## 2. Records to build (data structures)

Build a record before (or with) the first codec that needs it. All SoA +
zero‑copy + convention tags.

| Record | Fields (canonical dtype/shape) | Needed by | Status |
|---|---|---|---|
| `Image` | `pixels` HxWxC (u8/u16/f16/f32) + `color_space` + alpha/maxval metadata | PNG/JPEG/HDR/WebP/EXR/Netpbm | ✅ |
| `DepthMap` | `depth` HxW f32 + `scale`/`unit`/`invalid` meta + `confidence` HxW | typed depth adapters, Gipuma `.dmb`, COLMAP MVS depth | ✅ including camera-Z/nonpositive COLMAP MVS semantics |
| `NormalMap` | HxWx3 f32 + component/frame conventions | COLMAP MVS normal maps | ✅ |
| `ConsistencyGraph` | pixel/image-index CSR + row/column/index conventions | COLMAP MVS consistency graphs | ✅ |
| `PointVisibility` | fused-point/image-index CSR + index convention | COLMAP fused visibility | ✅ |
| `FlowField` | `vectors` HxWx2 f32 + component/axis/row/unit/invalid meta | typed `.flo` adapter | ✅ |
| `PointCloud` | `xyz` Nx3, `rgb`/`rgb16`, normals, intensity, optional organized shape/viewpoint/LAS waveform sidecar, plus authored float display RGB/opacity, widths, signed ids, velocity, acceleration, and display color space | PLY‑point, PCD, LAS/LAZ, E57, `.xyz`, bounded USD | ✅ record; rich static fields map through `read_scene`/`write_scene` for USD while unrelated legacy writers refuse them |
| `Mesh` | positions; ragged face offsets/indices; vertex/corner normals, UVs, RGBA8 and authored float display RGB/opacity; primitive/material ranges; coordinate metadata, transform, orientation, and tri-state double-sidedness | PLY‑mesh, OBJ, STL, OFF, glTF, USD | ✅ record; rich static geometry fields map through bounded USD while unrelated legacy writers refuse them |
| `MeshScene` | ordered `Mesh` primitives; mesh ranges/names; shared `MaterialSet`; node hierarchy and local transforms; scene roots/names/default | glTF/GLB, bounded USD/USDZ | ✅ |
| `FeatureSet` | `keypoints` Nx{2,4,6} f32, polymorphic `descriptors` NxD with extractor dtype/dim/name presence, keypoint colors, scores, quality, image time/id/size, and absent-state metadata | HDF5/hloc, COLMAP DB | ✅ |
| `MatchGraph` | ragged per-pair raw/verified `matches` Mx2 u32, optional score rows, source/retrieval provenance, `F/E/H` 3x3, config, relative pose, and optional recovered endpoint cameras | HDF5/hloc, COLMAP DB | ✅ |
| `PairCorrespondences` / `CorrespondenceGraph` | indexed or coordinate matches, scores, two-view geometry, ordered pair validation, and per-image feature references | hloc and detector-free matching adapters | ✅ Python-neutral models |
| `TrackObservation` / `TrackedPointCloud` | sparse XYZ plus aligned per-point image/keypoint observations | reconstruction and dataset adapters | ✅ Python-neutral models; compiled reconstruction uses CSR tracks |
| `Mask` | HxW bool, `True` means the pixel participates | segmentation, filtering, and dataset adapters | ✅ Python-neutral model |
| `ColmapDatabase` | cameras, prior-focal flags, ordered features, match graph, nested rig/frame, pose-prior, marker, metadata-only video, and ownership records; exact profile/application/schema version | COLMAP DB | ✅ stock/current/MAXX reads and exact selected-profile writers |
| `TensorDict` | named ndarrays + attrs | npz, HDF5, safetensors, zarr, parquet | ✅ |
| `CameraRig` | lossless ragged intrinsics/distortion, exact K/R/P, extrinsics, operational/time/topic metadata + convention tags | OpenCV/ROS/Kalibr calib | ✅ |
| `StateTrajectory` | int64-ns timestamps + p/q/v/gyro-bias/accel-bias with frame/unit/sign tags | EuRoC state CSV | ✅ |
| `PoseGraph` | typed SE3 nodes/edges, exact ids/fixed flags, XYZW transforms, symmetric 6×6 information + convention tags | g2o | ✅ |

*(Done: `Reconstruction`, `GaussianCloud`, `PosedViewSet`, `Camera`.)*

---

## 3. Per‑format checklist

Columns: **Ext/id** · **Record** · **Lib/oracle (license)** · **R/W** ·
**Stream** · **Notes / conventions / gotchas**. ✅ done · ⬜ pending.

### 3a. SfM / reconstruction / poses
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ COLMAP `.bin` | `Reconstruction` | pycolmap (BSD) | R+W | legacy three-file + modern five-file byte identity; rigs/frames; camera models 0-17; bounded direct writer |
| ✅ COLMAP `.txt` | `Reconstruction` | pycolmap | R+W | legacy/modern text twin; rigs/frames; fast_float parse |
| ✅ COLMAP `.db` | `ColmapDatabase` (`FeatureSet`/`MatchGraph`/nested companions) | pycolmap + sqlite3 (PD) | inspect + R/W all exact profiles + partial | exact 3.13/4.1.1/current/MAXX identity and profile-preserving public writes; guarded cross-profile conversion reports; hybrid compatibility writer retained for constructed core records |
| ✅ COLMAP dense workspace | lazy paths + dense records | independent format parsers + pycolmap comparison | inspect + R/W + partial | canonical, PMVS, and CMP-MVS topology; patch/fusion configs, projections, name lists, and raw visibility; encoded images remain opaque paths |
| ✅ Bundler `.out` | `Reconstruction` | pycolmap/manual | R+W | y‑down camera convention pinned |
| ✅ VisualSFM `.nvm` | `Reconstruction` | manual | R+W | quat WXYZ, focal in px |
| ✅ OpenMVG `sfm_data.json` | `Reconstruction` | manual json (nlohmann) | R+W | pose = center+rotation |
| ✅ BAL `.txt` / `.bal` | `Reconstruction` | UW specification + independent parser | R+W | angle-axis cameras, centered observations, strict canonical writer; generic `.txt` requires `format="bal"` |
| ✅ TUM / ✅ KITTI | `PosedViewSet` | pure‑Python | R+W | done (retrofit fast_float) |
| ✅ EuRoC `state_groundtruth` | `StateTrajectory` | independent stdlib CSV parser | R+W | exact int64 ns; p_RS_R, q_RS WXYZ, v_RS_R, b_w_RS_S, b_a_RS_S; mmap/sink/inspect/state ranges |
| ✅ g2o | `PoseGraph` | independent strict parser + g2o BSD-3 source semantics | R+W | SE3:QUAT nodes/edges, FIX, XYZW, symmetric 6×6 information; mmap/sink/inspect |

### 3b. 3DGS / splat
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ Gaussian `.ply` | `GaussianCloud` | gsply (MIT) | R+W | done |
| ✅ `.spz` v1‑4 | `GaussianCloud` | gsply | R+W | done |
| ✅ `.splat` | `GaussianCloud` | numpy oracle/test vectors | R+W | 32B/point; lossy 8-bit, SH dropped |
| ✅ SuperSplat `.compressed.ply` | `GaussianCloud` | pinned splat-transform 3.1.6 vector + NumPy oracle | R+W | 256-row chunks; deterministic Morton writer; explicit lossy quantization; point ranges |
| ✅ PlayCanvas SOG v2 | `GaussianCloud` | pinned splat-transform source + Pillow/NumPy/ZIP oracle | R+W | bundled ZIP or unbundled directory; strict lossless WebP layers; deterministic Morton/codebook/palette writer; point ranges |
| ✅ `.ksplat` v0.1 | `GaussianCloud` | pinned GaussianSplats3D 0.4.7 vectors + struct/NumPy oracle | R+W | levels 0–2; SH degree 0–2; multi-section read; deterministic guarded writer; point ranges |

### 3c. Point clouds
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ PLY (point) / ✅ PLY (mesh) | `PointCloud`/`Mesh` | independent parsers + Open3D/trimesh (MIT) | R+W | schema-dispatched ASCII+binary LE/BE; mesh preserves polygons and separate vertex/corner attributes |
| ✅ PCD | `PointCloud` | independent parser + Open3D (MIT) | R+W | PCD 0.7 ASCII/binary/LZF `binary_compressed`; organization/viewpoint; binary point ranges |
| ✅ LAS | `PointCloud` | laspy (BSD) | R+W | mmap; point formats 0‑10; internal waveform formats 4/5/9/10 retain a validated lossless sidecar |
| ✅ LAZ | `PointCloud` | LAZperf 3.4.0 (Apache‑2.0/BSD‑3-Clause/BSD‑2-Clause) + laspy/lazrs oracle | R+W | formats 0‑3 and 6‑8; mmap, seekable direct sink, inspect, and chunk-aware point ranges; waveform/extra-byte/metadata extensions reject |
| ✅ E57 | `PointCloud` | pye57 (MIT) / libE57Format (BSL-1.0) | R+W | optional `sceneio[e57]`; one Cartesian scan, exact RGB8/intensity/pose, invalid-state filtering; inspection stays metadata-only unless exact valid-point counting requires the provider scan path |
| ✅ `.xyz` / ✅ count-prefixed `.pts` | `PointCloud` | independent parser | R+W | `.pts` is a distinct count-validated grammar, not an alias |

### 3d. Meshes
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ PLY mesh | `Mesh` | independent struct/NumPy + trimesh (MIT) | R+W | polygon-preserving; vertex/corner attributes and primitive/material ranges |
| ✅ OBJ (+MTL) | `Mesh` + `MaterialSet` | pinned tinyobjloader/trimesh (MIT) | R+W | strict polygon-preserving independent indices; factors/textures and sampler clamp preserved; mmap read, paired direct-sink write, metadata inspect |
| ✅ STL | `Mesh` | independent parser + trimesh (MIT) | R+W | strict ASCII + binary LE; unwelded triangle soup and facet normals; bounded face ranges |
| ✅ OFF | `Mesh` | independent parser + trimesh (MIT) | R+W | polygon-preserving ASCII vertex variants with normals, UVs, and exact RGBA8; bounded face ranges |
| ✅ glTF / GLB (plain) | `MeshScene` | cgltf (MIT); pygltflib + trimesh oracles | R+W | 2.0 JSON/external or data buffers and GLB BIN; sparse/strided accessors, nodes/scenes, PBR subset, mesh/primitive selectors; unsupported extensions/Draco reject |
| policy-gated Draco glTF | `MeshScene` | Draco (Apache) | R+W | requires a separate patented-codec policy decision; never required for plain glTF/GLB |
| 🟡 USD / USDZ / historical USDC | `MeshScene` compatibility + `SceneGraph` | TinyUSDZ (Apache-2.0) | rich direct-static 3D-CV R+W | optional `sceneio[usd]`; C1-C5 cover hierarchy, polygon meshes/points, bounded PreviewSurface materials/textures, official float/half Gaussian particles, static camera/render-product pairs, direct scalar-float OpenVDB references, one inherited semantic pair, and static PointInstancer rows; historical USDC input is qualified through crate 10 and later crates refuse before provider dispatch; C6 Exit B explicitly leaves current USDC, evaluated composition, and animated selected time unavailable; OpenUSD remains reference-only under the current license allow-list; C7 local and hosted Linux/macOS/Windows package/provider/compiler/CI evidence passes |

### 3e. Arrays / tensors / features
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ `.npy` / `.npz` | ndarray / `TensorDict` | numpy (BSD) | R+W | NPY native C-order mmap view; NPZ stored/deflate |
| ✅ HDF5 `.h5` / `.hdf5` | `TensorDict` | h5py (BSD-3) + HDF5 permissive license | R+W | optional `sceneio[hdf5]`; numeric/bool datasets, nested paths, text attrs, inspect, named reads, hyperslabs, atomic path writes |
| ✅ hloc feature layout | `HlocFeatureStore` + native `FeatureSet` | documented hloc schema + h5py oracle | R+W | keypoints, D×N descriptors, scores, image size, uncertainty, nested names |
| ✅ hloc match layout | `HlocMatchStore` + native `MatchGraph` | documented hloc schema + h5py oracle | R+W | dense `matches0`, optional scores, exact endpoints/order/dtypes |
| ✅ safetensors | `TensorDict` | safetensors (Apache) | R+W | JSON header, mmap tensors, name/slice selectors |
| ✅ Zarr v2/v3 | `TensorDict` | zarr (MIT) + numcodecs (MIT) | R+W | optional `sceneio[zarr]`; numeric/bool directory stores, nested paths, text root attrs, metadata inspection, named reads, leading-axis slices, transactional replacement, fixed-width zero-copy normalization for NumPy platform/generic numeric aliases |
| ✅ Parquet / Arrow IPC | `TensorDict` numeric table | PyArrow (Apache-2.0) | R+W | optional `sceneio[arrow]`; fixed-width numeric columns, metadata, mmap reads; Parquet named-column selection |
| ✅ OpenVDB | sparse-grid `TensorDict` | TinyVDB (Apache-2.0) | R+W | optional `sceneio[openvdb]`; one identity-transform, zero-background float32 scalar grid with sparse coordinates and ZIP/active-mask output; rebuilt active count is verified and unsupported provider topologies refuse |

### 3f. Images (feature‑flagged C libs)
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ PFM | ndarray (raw) + `DepthMap` (typed) | pure‑Python | R+W | owned positive-stride decode; mandatory external `DepthEncoding`; unit-magnitude scalar subset and bounded typed windows |
| ✅ PPM / PGM / PNM | `Image` | pypng/manual | R+W | P2/P3/P5/P6, 8/16-bit |
| ✅ PNG | `Image` (raw) + `DepthMap` (typed) | Pillow+pypng / lodepng (zlib) | R+W | 8/16‑bit, palette, interlace; explicit grayscale uint16 typed-depth adapter |
| ✅ JPEG | `Image` | Pillow / stb (public domain) | R+W | lossy; gray/RGB read, RGB write |
| ✅ Radiance HDR | `Image` | numpy RGBE / stb (public domain) | R+W | float32 RGB; lossy RGBE encode |
| ✅ TIFF | `Image` / `Mask` / grayscale-stack `TensorDict` | tifffile (BSD-3-Clause) | R+W | optional `sceneio[tiff]`; bounded single-series uint8/uint16/float32/boolean profile, BigTIFF, alpha metadata |
| ✅ WebP | `Image` | Pillow / libwebp (BSD) | R+W | lossy+lossless RGB/RGBA |
| ✅ OpenEXR | `Image` (raw) + `DepthMap` (typed) | OpenEXR (BSD‑3) / tinyexr | R+W | HALF→FLOAT; PIZ/ZIP/RLE; explicit named scalar depth channel |
| ✅ BMP / TGA | `Image` | stb_image (PD/MIT) + Pillow | R+W | BMP BI_RGB/bitfields/palette and TGA raw/RLE/palette; strict unsupported-variant guards |
| ✅ AVIF | `Image` | optional Pillow/libavif + libaom/dav1d (MIT-CMU/BSD, royalty-free grant) | R+W | repository-owned bounded adapter; 8-bit gray/RGB/straight RGBA, mmap read, inspect; no high-bit-depth/HDR profile yet |
| ⬜ JPEG‑XL | `Image` | libjxl (BSD, royalty‑free) | R+W | |

### 3g. Depth / flow / spatial‑AI
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ 16‑bit depth PNG | `DepthMap` | pypng oracle + lodepng | R+W | mandatory external encoding; TUM 1/5000 and ScanNet mm profiles tested; no implicit scale |
| ✅ scalar depth EXR | `DepthMap` | OpenEXR / tinyexr | R+W | mandatory external encoding and exact UTF-8 channel name; HALF/FLOAT values preserved; no implicit scale |
| ✅ `.flo` (Middlebury) | ndarray (raw) + `FlowField` (typed) | manual | R+W | magic 202021.25; mapped raw view; typed semantic adapters with strict writer guards |
| ✅ `.dmb` (Gipuma) | `DepthMap` | independent NumPy parser | R+W | scalar float32 Gipuma depth; unknown scale, zero-invalid; bounded windows; distinct from COLMAP MVS matrices |
| ✅ COLMAP MVS depth | `DepthMap` | independent `struct`/NumPy parser | R+W | exact ampersand header, planar little-endian f32 camera-Z values, nonpositive-invalid, bounded windows |
| ✅ COLMAP MVS normal | `NormalMap` | independent `struct`/NumPy parser | R+W | exact three-channel planar little-endian f32 camera-frame normals; bounded windows |
| ✅ COLMAP MVS consistency | `ConsistencyGraph` | independent `struct` parser | R+W | strict signed-int32 pixel records and positional image-index lists |
| ✅ COLMAP fused visibility | `PointVisibility` | independent `struct` parser | R+W | strict count-prefixed uint32 positional image-index lists |
| ✅ transforms.json | `PosedViewSet` | pure‑Python | R+W | done (OpenGL c2w) |
| ✅ RTMV / synthetic sets | `RtmvDataset`+`PosedViewSet`+lazy encoded layers | independent NumPy/OpenEXR fixture | R | strict contiguous five-digit layout, complete camera/object/header validation, optional all-or-none segmentation, bounded frames; intentionally read-only |

### 3h. Camera calibration
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ OpenCV YAML/XML | `CameraRig` | native bounded subset + PyYAML/ElementTree oracle | R+W | exact K/D and optional R/P; distinct syntax ids; generic extensions unclaimed |
| ✅ ROS `camera_info` yaml | `CameraRig` | native bounded subset + PyYAML oracle | R+W | exact K,D,R,P, binning, ROI, rectify flag |
| ✅ Kalibr yaml | `CameraRig` | native bounded subset + PyYAML oracle | R+W | multi-camera models/coefficients, chained or IMU extrinsics, topics, signed time offsets |

### 3i. Video — constrained (no FFmpeg; royalty-free grants only)
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ image sequence (dir) | `ImageSequence` | existing image inspectors + independent manifest/PGM fixtures | R+W | lazy flat frames, natural order or exact-timing manifest, bounded transactional copy |
| ✅ `.y4m` (raw YUV) | `ImageSequence` | original native codec + independent Python oracle | R+W | uint8 mono/420/422/444 planar frames; uncompressed and unpatented |
| ✅ animated WebP | `ImageSequence` | pinned libwebp + Pillow oracle | R+W | fully composited packed RGB/RGBA frames; exact millisecond timing, loop/background metadata, mmap, direct sink, inspect |
| ✅ APNG | `ImageSequence` | existing lodepng/miniz substrate + Pillow/spec oracle | R+W | bounded repository-owned animation chunk/state layer; composited RGBA, exact accepted-profile timing, blend/disposal, mmap, sink, inspect |
| ✅ animated AVIF | `ImageSequence` | optional Pillow/libavif + libaom/dav1d | R+W | owned 8-bit frames, exact accepted timing, frame ranges, mmap, inspect; writer is provider-buffered and does not claim a direct sink |
| ✅ WebM VP8 all-keyframe | `ImageSequence` | repository EBML + pinned libwebp VP8; independent EBML/Pillow oracle | R+W | compatible default: packed uint8 RGB, progressive independently decodable frames, exact whole-ms timing, mmap, direct sink, inspect, frame ranges |
| ✅ WebM inter-frame VP8/VP9 | `ImageSequence` | repository EBML + pinned libvpx; independent EBML layout oracle + official codec API | R+W | explicit `vp8-temporal` / `vp9-temporal` profiles; owned planar uint8 4:2:0, Colour matrix/range, backward references, keyframe-aware ranges, mmap/direct sink/worker lanes; no audio/subtitles/general media framework |
| ✅ Ogg/Theora | `ImageSequence` | pinned libogg/libtheora + independent Ogg page/CRC/lacing/remux oracle | R+W | progressive uint8 planar 4:2:0, fixed rational timing, pixel aspect, mmap, direct sink, inspect, frame ranges; no audio/subtitles/general video framework |

**Excluded (out of scope):** FBX (proprietary SDK), H.264/H.265/ProRes and
royalty-bearing video codecs without an accepted open grant, HEIF/HEIC (HEVC
patents), Draco‑only
niche, anything GPL/AGPL/NC.

---

## 4. Sequencing & critical path

The original Tier‑1, splat, vendored image/HDR, plain-LAS, and O1–O5
hardening work shipped in 0.2.0. The remaining dependency-ordered sequence is
maintained in `format_gap_implementation_plan.md`:

1. machine-readable capabilities and optional-feature state;
2. COLMAP DB, PCD, calibration, and other self-contained formats (generic
   point PLY is complete);
3. meshes and vendorable LAZ (complete locally);
4. lazy image directories, raw Y4M, animated WebP, APNG, animated AVIF,
   bounded WebM VP8/VP9, RTMV, and Ogg/Theora (complete locally);
5. optional-provider TIFF/E57/Arrow integrations (complete locally);
6. bounded USD/USDZ and OpenVDB integrations (complete locally), with
   broader scene/volume semantics and policy-gated codecs left explicit.

**Gates:** (a) each optional C-library phase needs a pinned permissive source,
tested disabled/enabled builds, a clean unavailable-feature path, and the full
cibuildwheel matrix; (b) the `splat`/`posed_views`
DataType **vocabulary** ids stay deferred to **Phase‑C** (cross‑repo wire
identity) regardless of codec progress — codecs work today via informal labels.

---

## 5. Build/CI implications as C libs enter

- In-tree/header-only dependencies keep the default build independent of
  system libraries. The production adapters and all selected native sources
  are repository-maintained: miniz, nlohmann/json, zstd, fast_float, LAZperf,
  and libwebp complete the R6 repository-source set. The build now requires
  `Python::SABIModule` and verifies nanobind’s stable target/suffix rather than
  accepting a CPython-specific fallback. `publish.yml` builds all platform
  wheels from one verified sdist with locked build inputs. Final build-only run
  `30406706115` passes its exact-tree MSVC, GCC 10, and AppleClang package jobs
  plus downloaded-artifact inspection, closing the R6 validation gate.
- Optional system libs compile in per `SCENEIO_WITH_*`; absent → the codec
  reports `needs_dep` and raises a clean "format not built" error, never an
  import crash. The cibuildwheel images gain them via vcpkg/conda as each phase
  lands; the smoke wheel stays numpy‑only.
- Sanitizer lane (ASan/UBSan/LSan) plus an all-format benchmark smoke run on
  Linux; mmap-specific tests also run on Windows and macOS.
