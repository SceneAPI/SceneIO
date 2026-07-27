# SceneIO — comprehensive coverage roadmap & execution checklist

> Current shipped and branch-local status is tracked in `format_coverage.md`.
> The status markers below have been reconciled to the live 50-codec registry;
> broader checklist boxes remain open where a codec has not completed an
> aspirational per-format or cross-platform gate. The authoritative
> implementation sequence for the remaining formats is
> [`format_gap_implementation_plan.md`](format_gap_implementation_plan.md);
> the prerequisite maintainability and backend-selection work is in
> [`repository_organization_plan.md`](repository_organization_plan.md), with
> its reviewed execution checklist in
> [`next_stage_implementation_checklist.md`](next_stage_implementation_checklist.md).
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
> timed providers while retaining 17 exact reviewed exemptions. R3.3 is now
> active with an immutable 44-buffer/3-path/3-directory case catalog under
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
> collection remains 3,345.

The granular, per‑format execution plan for covering **every relevant file type
that has a permissively‑licensed open‑source option**. Sits below the strategy
(`io_implementation_plan.md`) and the status snapshot (`format_coverage.md`):
this is the *how* — implementation, parity, C++ optimization, and verification —
for each remaining item.

Current test counts, workflow evidence, and the immutable validated checkpoint
are maintained only in
[`format_coverage.md`](format_coverage.md#format--data-structure-coverage);
this policy roadmap intentionally does not duplicate them. The next execution
order is: complete the repository-organization and codec-backend performance
gates, close default native sources for offline builds, then finish animated
WebP/APNG and RTMV.
The common optional-library feature pattern follows before HDF5/hloc, TIFF,
E57, and Parquet.

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
| `DepthMap` | `depth` HxW f32 + `scale`/`unit`/`invalid` meta + `confidence` HxW | typed depth adapters, `.dmb` | ✅ record + scalar DMB + typed PFM/PNG/EXR |
| `FlowField` | `vectors` HxWx2 f32 + component/axis/row/unit/invalid meta | typed `.flo` adapter | ✅ |
| `PointCloud` | `xyz` Nx3, `rgb`/`rgb16`, `normals`, `intensity`, optional organized shape + viewpoint, optional lossless LAS waveform sidecar | PLY‑point, PCD, LAS/LAZ, E57, `.xyz` | ✅ |
| `Mesh` | positions; ragged face offsets/indices; vertex/corner normals, UVs, RGBA; primitive/material ranges; coordinate metadata and transform | PLY‑mesh, OBJ, STL, OFF, glTF, USD | ✅ |
| `MeshScene` | ordered `Mesh` primitives; mesh ranges/names; shared `MaterialSet`; node hierarchy and local transforms; scene roots/names/default | glTF/GLB, future USD | ✅ |
| `FeatureSet` | `keypoints` Nx{2,4,6} f32, `descriptors` NxD, `scores` N, image identity/size and absent-state metadata | HDF5/hloc, COLMAP DB | ✅ |
| `MatchGraph` | ragged per-pair raw/verified `matches` Mx2 u32, `scores` M, `F/E/H` 3x3, config and relative pose | HDF5/hloc, COLMAP DB | ✅ |
| `ColmapDatabase` | cameras, prior-focal flags, ordered features, match graph, schema version | COLMAP DB | ✅ |
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
| ✅ COLMAP `.bin` | `Reconstruction` | pycolmap (BSD) | R+W | byte‑identical; rigs/frames in 4.1.1 |
| ✅ COLMAP `.txt` | `Reconstruction` | pycolmap | R+W | text twin; fast_float parse |
| ✅ COLMAP `.db` | `ColmapDatabase` (`FeatureSet`/`MatchGraph`) | pycolmap + sqlite3 (PD) | R+W | pinned SQLite 3.53.4; transaction-safe write, metadata inspect, one-image/one-pair selectors |
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
| ⬜ E57 | `PointCloud` | libE57Format (BSD) | R+W | optional C lib |
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
| ⬜ USD / USDZ | `Mesh`/scene | usd‑core/pxr (Apache) | R | heavyweight C lib; feature‑flag |

### 3e. Arrays / tensors / features
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ `.npy` / `.npz` | ndarray / `TensorDict` | numpy (BSD) | R+W | NPY native C-order mmap view; NPZ stored/deflate |
| ⬜ HDF5 `.h5` | `TensorDict` | h5py (BSD) + libhdf5 (BSD) | R+W | optional C lib; streaming |
| ⬜ hloc feature layout | `FeatureSet`/`MatchGraph` | hloc (Apache) + h5py | R+W | h5 group conventions |
| ✅ safetensors | `TensorDict` | safetensors (Apache) | R+W | JSON header, mmap tensors, name/slice selectors |
| ⬜ Zarr | `TensorDict` | zarr (MIT) | R+W | chunked; blosc (BSD) |
| ⬜ Parquet / Arrow | table | pyarrow (Apache) | R+W | columnar; optional |

### 3f. Images (feature‑flagged C libs)
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ PFM | ndarray (raw) + `DepthMap` (typed) | pure‑Python | R+W | owned positive-stride decode; mandatory external `DepthEncoding`; unit-magnitude scalar subset and bounded typed windows |
| ✅ PPM / PGM / PNM | `Image` | pypng/manual | R+W | P2/P3/P5/P6, 8/16-bit |
| ✅ PNG | `Image` (raw) + `DepthMap` (typed) | Pillow+pypng / lodepng (zlib) | R+W | 8/16‑bit, palette, interlace; explicit grayscale uint16 typed-depth adapter |
| ✅ JPEG | `Image` | Pillow / stb (public domain) | R+W | lossy; gray/RGB read, RGB write |
| ✅ Radiance HDR | `Image` | numpy RGBE / stb (public domain) | R+W | float32 RGB; lossy RGBE encode |
| ⬜ TIFF | `Image` | libtiff (BSD‑like) | R+W | tiled/striped; multi‑page |
| ✅ WebP | `Image` | Pillow / libwebp (BSD) | R+W | lossy+lossless RGB/RGBA |
| ✅ OpenEXR | `Image` (raw) + `DepthMap` (typed) | OpenEXR (BSD‑3) / tinyexr | R+W | HALF→FLOAT; PIZ/ZIP/RLE; explicit named scalar depth channel |
| ✅ BMP / TGA | `Image` | stb_image (PD/MIT) + Pillow | R+W | BMP BI_RGB/bitfields/palette and TGA raw/RLE/palette; strict unsupported-variant guards |
| ⬜ AVIF | `Image` | libavif+aom (BSD, royalty‑free) | R+W | AV1 still |
| ⬜ JPEG‑XL | `Image` | libjxl (BSD, royalty‑free) | R+W | |

### 3g. Depth / flow / spatial‑AI
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ 16‑bit depth PNG | `DepthMap` | pypng oracle + lodepng | R+W | mandatory external encoding; TUM 1/5000 and ScanNet mm profiles tested; no implicit scale |
| ✅ scalar depth EXR | `DepthMap` | OpenEXR / tinyexr | R+W | mandatory external encoding and exact UTF-8 channel name; HALF/FLOAT values preserved; no implicit scale |
| ✅ `.flo` (Middlebury) | ndarray (raw) + `FlowField` (typed) | manual | R+W | magic 202021.25; mapped raw view; typed semantic adapters with strict writer guards |
| ✅ `.dmb` (Gipuma/COLMAP) | `DepthMap` | independent NumPy parser | R+W | scalar float32 dense MVS depth; unknown scale, zero-invalid; bounded windows |
| ✅ transforms.json | `PosedViewSet` | pure‑Python | R+W | done (OpenGL c2w) |
| ⬜ RTMV / synthetic sets | `PosedViewSet`+`Image` | manual | R | dataset layout |

### 3h. Camera calibration
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ OpenCV YAML/XML | `CameraRig` | native bounded subset + PyYAML/ElementTree oracle | R+W | exact K/D and optional R/P; distinct syntax ids; generic extensions unclaimed |
| ✅ ROS `camera_info` yaml | `CameraRig` | native bounded subset + PyYAML oracle | R+W | exact K,D,R,P, binning, ROI, rectify flag |
| ✅ Kalibr yaml | `CameraRig` | native bounded subset + PyYAML oracle | R+W | multi-camera models/coefficients, chained or IMU extrinsics, topics, signed time offsets |

### 3i. Video — constrained (no ffmpeg / patented codecs)
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ image sequence (dir) | `ImageSequence` | existing image inspectors + independent manifest/PGM fixtures | R+W | lazy flat frames, natural order or exact-timing manifest, bounded transactional copy |
| ✅ `.y4m` (raw YUV) | `ImageSequence` | original native codec + independent Python oracle | R+W | uint8 mono/420/422/444 planar frames; uncompressed and unpatented |
| ⬜ animated WebP / APNG | `ImageSequence` | libwebp / libpng | R | royalty‑free frame stacks |

**Excluded (out of scope):** FBX (proprietary SDK), H.264/H.265/ProRes and any
patented video codec (per directive), HEIF/HEIC (HEVC patents), Draco‑only
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
4. lazy image directories and raw Y4M (complete locally), followed by animated
   WebP/APNG and RTMV;
5. independently gated HDF5/TIFF/E57/Arrow integrations;
6. heavyweight scene/volume integrations and policy-gated codecs.

**Gates:** (a) each optional C-library phase needs a pinned permissive source,
tested disabled/enabled builds, a clean unavailable-feature path, and the full
cibuildwheel matrix; (b) the `splat`/`posed_views`
DataType **vocabulary** ids stay deferred to **Phase‑C** (cross‑repo wire
identity) regardless of codec progress — codecs work today via informal labels.

---

## 5. Build/CI implications as C libs enter

- In-tree/header-only dependencies keep the default build independent of
  system libraries. The production adapters are already repo-maintained, but
  miniz, zstd, nlohmann/json, fast_float, LAZperf, and libwebp still arrive
  through pinned `FetchContent`; moving those exact revisions under
  `src/cpp/third_party/` is the remaining offline/source-ownership gate for the
  post-0.2 stable tier.
- Optional system libs compile in per `SCENEIO_WITH_*`; absent → the codec
  reports `needs_dep` and raises a clean "format not built" error, never an
  import crash. The cibuildwheel images gain them via vcpkg/conda as each phase
  lands; the smoke wheel stays numpy‑only.
- Sanitizer lane (ASan/UBSan/LSan) plus an all-format benchmark smoke run on
  Linux; mmap-specific tests also run on Windows and macOS.
