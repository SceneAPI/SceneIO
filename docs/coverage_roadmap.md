# SceneIO — comprehensive coverage roadmap & execution checklist

> Current shipped status is tracked in `format_coverage.md`. The status markers
> below have been reconciled to the 0.2.0 registry; broader checklist boxes
> remain open where a shipped codec has not completed that aspirational,
> per-format hardening gate. The authoritative implementation sequence for the
> remaining formats is
> [`format_gap_implementation_plan.md`](format_gap_implementation_plan.md).

The granular, per‑format execution plan for covering **every relevant file type
that has a permissively‑licensed open‑source option**. Sits below the strategy
(`io_implementation_plan.md`) and the status snapshot (`format_coverage.md`):
this is the *how* — implementation, parity, C++ optimization, and verification —
for each remaining item.

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
      Netpbm/lossless VP8L WebP/FLO pixel windows; XYZ/LAS/Gaussian
      PLY/SPLAT point ranges; single-image COLMAP binary/text without opening
      the point container. Unsupported subformats and codecs fail explicitly
      instead of falling back to a full decode.

### 1.4 Verification gates (per‑format Definition of Done)
- [ ] All §1.2 tests green **in CI on all 3 platforms** (parity oracles installed).
- [x] **ASan + UBSan + LSan** sanitizer CI lane instruments the core and vendored
      libraries; local Linux and remote branch full-suite runs are green, and
      scheduled runs raise the mmap mutation sweep to 100 cases.
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
| `DepthMap` | `depth` HxW f32 + `scale`/`unit`/`invalid` meta + `confidence` HxW | typed depth adapters, `.dmb` | ✅ record / ⬜ typed codecs |
| `PointCloud` | `xyz` Nx3, `rgb` Nx3 u8, `normals` Nx3, `intensity` N | PLY‑point, PCD, LAS/LAZ, E57, `.xyz` | ✅ |
| `Mesh` | `vertices` Nx3, `faces` Mx3 u32, `normals`, `uv`, `vertex_color` | OBJ, STL, OFF, PLY‑mesh, glTF, USD | ⬜ |
| `FeatureSet` | `keypoints` Nx{2,4,6} f32, `descriptors` NxD, `scores` N, `image_size` 2 | HDF5/hloc, COLMAP DB | ⬜ |
| `MatchGraph` | per‑pair `matches` Mx2 u32, `scores` M, `F/E/H` 3x3, `inliers` | HDF5/hloc, COLMAP DB | ⬜ |
| `TensorDict` | named ndarrays + attrs | npz, HDF5, safetensors, zarr, parquet | ✅ |
| `CameraRig` | N `Camera` + extrinsics + convention tag | OpenCV/ROS/Kalibr calib | ⬜ |

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
| ⬜ COLMAP `.db` | `FeatureSet`/`MatchGraph` | pycolmap + sqlite3 (PD) | R+W | sqlite; contract at `colmap_db` |
| ✅ Bundler `.out` | `Reconstruction` | pycolmap/manual | R+W | y‑down camera convention pinned |
| ✅ VisualSFM `.nvm` | `Reconstruction` | manual | R+W | quat WXYZ, focal in px |
| ✅ OpenMVG `sfm_data.json` | `Reconstruction` | manual json (nlohmann) | R+W | pose = center+rotation |
| ⬜ BAL `.txt` | `Reconstruction` | manual | R | Bundle‑Adjustment‑in‑the‑Large |
| ✅ TUM / ✅ KITTI | `PosedViewSet` | pure‑Python | R+W | done (retrofit fast_float) |
| ⬜ EuRoC `state_groundtruth` | `PosedViewSet` | manual csv | R+W | ts,p,q,v,bw,ba |
| ⬜ g2o | `PoseGraph` (new) | manual | R+W | edges → needs a pose‑graph record |

### 3b. 3DGS / splat
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ Gaussian `.ply` | `GaussianCloud` | gsply (MIT) | R+W | done |
| ✅ `.spz` v1‑4 | `GaussianCloud` | gsply | R+W | done |
| ✅ `.splat` | `GaussianCloud` | numpy oracle/test vectors | R+W | 32B/point; lossy 8-bit, SH dropped |
| ⬜ SuperSplat SOG / `.compressed.ply` | `GaussianCloud` | ref loaders | R+W | clustered/quantized |
| ⬜ `.ksplat` | `GaussianCloud` | ref loader | R | mkkellogg viewer format |

### 3c. Point clouds
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ⬜ PLY (point/mesh) | `PointCloud`/`Mesh` | plyfile (BSD)/open3d (MIT) | R+W | ascii+binary LE/BE; generic PLY reader |
| ⬜ PCD | `PointCloud` | open3d | R+W | ascii/binary/binary_compressed (lzf) |
| ✅ LAS | `PointCloud` | laspy (BSD) | R+W | mmap; point formats 0‑3 and 6‑8 |
| ⬜ LAZ | `PointCloud` | lazrs (Apache) / laszip | R+W | LAS compression |
| ⬜ E57 | `PointCloud` | libE57Format (BSD) | R+W | optional C lib |
| ✅ `.xyz` / ⬜ count-prefixed `.pts` | `PointCloud` | manual | R+W | `.pts` is a distinct grammar, not an alias |

### 3d. Meshes
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ⬜ OBJ (+MTL) | `Mesh` | tinyobjloader/trimesh (MIT) | R+W | fast_float; ignore/pass materials |
| ⬜ STL | `Mesh` | numpy‑stl/trimesh | R+W | ascii + binary |
| ⬜ OFF | `Mesh` | trimesh | R+W | trivial |
| ⬜ glTF / GLB (+Draco) | `Mesh` | pygltflib (MIT); Draco (Apache) | R+W | json+bin; Draco optional |
| ⬜ USD / USDZ | `Mesh`/scene | usd‑core/pxr (Apache) | R | heavyweight C lib; feature‑flag |

### 3e. Arrays / tensors / features
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ `.npy` / `.npz` | ndarray / `TensorDict` | numpy (BSD) | R+W | NPY native C-order mmap view; NPZ stored/deflate |
| ⬜ HDF5 `.h5` | `TensorDict` | h5py (BSD) + libhdf5 (BSD) | R+W | optional C lib; streaming |
| ⬜ hloc feature layout | `FeatureSet`/`MatchGraph` | hloc (Apache) + h5py | R+W | h5 group conventions |
| ⬜ safetensors | `TensorDict` | safetensors (Apache) | R+W | json header + mmap tensors |
| ⬜ Zarr | `TensorDict` | zarr (MIT) | R+W | chunked; blosc (BSD) |
| ⬜ Parquet / Arrow | table | pyarrow (Apache) | R+W | columnar; optional |

### 3f. Images (feature‑flagged C libs)
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ✅ PFM | ndarray | pure‑Python | R+W | owned positive-stride decode; typed depth adapter pending |
| ✅ PPM / PGM / PNM | `Image` | pypng/manual | R+W | P2/P3/P5/P6, 8/16-bit |
| ✅ PNG | `Image` | Pillow+pypng / lodepng (zlib) | R+W | 8/16‑bit, palette, interlace |
| ✅ JPEG | `Image` | Pillow / stb (public domain) | R+W | lossy; gray/RGB read, RGB write |
| ✅ Radiance HDR | `Image` | numpy RGBE / stb (public domain) | R+W | float32 RGB; lossy RGBE encode |
| ⬜ TIFF | `Image` | libtiff (BSD‑like) | R+W | tiled/striped; multi‑page |
| ✅ WebP | `Image` | Pillow / libwebp (BSD) | R+W | lossy+lossless RGB/RGBA |
| ✅ OpenEXR | `Image` | OpenEXR (BSD‑3) / tinyexr | R+W | HALF→FLOAT; PIZ/ZIP/RLE |
| ⬜ BMP / TGA | `Image` | stb_image (PD) | R+W | trivial fallbacks |
| ⬜ AVIF | `Image` | libavif+aom (BSD, royalty‑free) | R+W | AV1 still |
| ⬜ JPEG‑XL | `Image` | libjxl (BSD, royalty‑free) | R+W | |

### 3g. Depth / flow / spatial‑AI
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ⬜ 16‑bit depth PNG | `DepthMap` | libpng + scale meta | R+W | TUM 1/5000, ScanNet mm — **scale pin** |
| ✅ `.flo` (Middlebury) | ndarray (H,W,2) | manual | R+W | magic 202021.25; mapped view |
| ⬜ `.dmb` (Gipuma/COLMAP) | `DepthMap` | manual | R+W | dense MVS depth |
| ✅ transforms.json | `PosedViewSet` | pure‑Python | R+W | done (OpenGL c2w) |
| ⬜ RTMV / synthetic sets | `PosedViewSet`+`Image` | manual | R | dataset layout |

### 3h. Camera calibration
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ⬜ OpenCV `.yml`/`.xml` | `Camera`/`CameraRig` | manual yaml | R+W | model → COLMAP model map |
| ⬜ ROS `camera_info` yaml | `Camera` | manual | R+W | K,D,R,P |
| ⬜ Kalibr yaml | `CameraRig` | manual | R+W | multi‑cam + extrinsics |

### 3i. Video — constrained (no ffmpeg / patented codecs)
| Format | Record | Lib / oracle | R/W | Notes |
|---|---|---|---|---|
| ⬜ image sequence (dir) | `ImageSequence` | via image codecs | R+W | the primary "video" path |
| ⬜ `.y4m` (raw YUV) | `ImageSequence` | manual | R+W | uncompressed, unpatented |
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
2. safetensors, COLMAP DB, generic PLY/PCD, calibration, and other
   self-contained formats;
3. meshes and vendorable LAZ;
4. lazy sequence/dataset containers;
5. independently gated HDF5/TIFF/E57/Arrow integrations;
6. heavyweight scene/volume integrations and policy-gated codecs.

**Gates:** (a) each C‑lib phase needs the cibuildwheel matrix to provision that
lib (vcpkg/conda) and a `needs_dep` clean‑error path; (b) the `splat`/`posed_views`
DataType **vocabulary** ids stay deferred to **Phase‑C** (cross‑repo wire
identity) regardless of codec progress — codecs work today via informal labels.

---

## 5. Build/CI implications as C libs enter

- Vendored/header‑only (miniz, zstd, nlohmann/json, stb, fast_float, lodepng)
  keep the minimal build self‑contained — the whole Tier‑1 spine needs **no
  system libs**.
- Optional system libs compile in per `SCENEIO_WITH_*`; absent → the codec
  reports `needs_dep` and raises a clean "format not built" error, never an
  import crash. The cibuildwheel images gain them via vcpkg/conda as each phase
  lands; the smoke wheel stays numpy‑only.
- Sanitizer lane (ASan/UBSan/LSan) plus an all-format benchmark smoke run on
  Linux; mmap-specific tests also run on Windows and macOS.
