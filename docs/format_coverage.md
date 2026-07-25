# Format & data-structure coverage

The single source of truth for **what SceneIO's compiled core reads/writes today
vs. what's planned**. Consolidates the catalog (`formats_survey.md`) and the
roadmap (`io_implementation_plan.md` §3, §6, §7) against the actual codec
registry (`src/sceneio/io/registry.py`).

The detailed execution, verification, and wheel-validation sequence for the
remaining formats is in
[`format_gap_implementation_plan.md`](format_gap_implementation_plan.md).

Legend: ✅ done · 🟡 partial · ⬜ pending · **R** read · **W** write

> Status note: everything marked ✅ is implemented by the compiled
> `sceneio._core`. The original 23 codecs ship in SceneIO 0.2.0; safetensors,
> PTS, DMB, BAL, BMP, TGA, generic point PLY, PCD, EuRoC state CSV, and the
> OpenCV/ROS/Kalibr calibration codecs, g2o pose graphs, and the COLMAP
> feature database, SuperSplat compressed PLY, PlayCanvas SOG, and KSplat are
> post-0.2 formats on
> `phase0-nanobind-core` and are not released yet.

## Data structures (memory Records)

SoA, zero-copy to numpy/torch (DLPack), conventions carried as metadata.

| Record | Intended DataType | Status | Notes |
|---|---|---|---|
| `Reconstruction` | `sparse_model` | ✅ | cameras + image poses (WXYZ, world→cam) + points3D + tracks |
| `GaussianCloud` | `splat` | ✅ record / ⬜ datatype | DataType registration is **Phase‑C** (needs a wire‑format id); the codecs use `"splat"` as an informal label |
| `PosedViewSet` | `camera` + poses | ✅ record / ⬜ datatype | SE3/view + optional `Camera` intrinsics; per‑source convention tags (order/direction/axis/scale). `"posed_views"` label is informal, Phase‑C |
| `Camera` | (shared) | ✅ | COLMAP model id + `params[]`; reused by `Reconstruction` and `PosedViewSet` |
| `Image` | `image_sequence` elem | ✅ | interleaved HxWxC (u8/u16/f32), color_space/alpha_mode/maxval metadata, owner‑safe zero‑copy `pixels` |
| `TensorDict` | (named arrays) | ✅ | dict‑like, 12 numpy dtypes (dtype‑erased), zero‑copy views; backs NPZ and mapped safetensors |
| `PointCloud` | `point_cloud` (new) | ✅ | xyz + rgb/rgb16 + normals + intensity, optional organized width/height and acquisition viewpoint; backs `.xyz`, count-prefixed `.pts`, point `.ply`, PCD, and plain `.las` |
| `DepthMap` | `depth_map` | ✅ | scalar f32 depth + scale/unit/invalid + confidence; backs scalar DMB and explicit typed PFM/PNG/EXR adapters |
| `FlowField` | `flow` | ✅ | HxWx2 f32 vectors with component/axis/row/unit/invalid metadata; raw FLO API remains ndarray-compatible |
| `StateTrajectory` | `state_trajectory` | ✅ record / ⬜ datatype | exact int64 nanosecond timestamps plus float64 position, WXYZ orientation, velocity, gyro bias, and accelerometer bias; explicit frame/unit/sign metadata |
| `CameraRig` | `camera_rig` | ✅ record / ⬜ datatype | ordered cameras; ragged model parameters; exact optional K/R/P; extrinsic, ROI/binning, topic, and time-offset metadata with explicit conventions |
| `PoseGraph` | `pose_graph` | ✅ record / ⬜ datatype | ordered typed SE(3) nodes/edges, fixed-node flags, exact ids, XYZW transforms, and symmetric 6×6 information matrices with explicit direction/order metadata |
| `FeatureSet` | `feature_set` | ✅ record / ⬜ datatype | per-image id/name/camera/size; Nx{2,4,6} f32 keypoints; optional u8/f32 descriptors and f32 scores with absent-vs-empty fidelity |
| `MatchGraph` | `match_graph` | ✅ record / ⬜ datatype | canonical COLMAP image pairs and pair ids; ragged raw/verified u32 matches; optional scores, F/E/H, config, and relative pose |
| `ColmapDatabase` | `match_graph` | ✅ record / ⬜ datatype | cameras, prior-focal flags, ordered `FeatureSet` values, `MatchGraph`, and schema user version |

## Formats (codecs)

### ✅ Implemented — Tier‑1 zero‑dep spine (18 codecs, Phase 1a/1b/1c + 2)

| Format id | Record | R/W | Oracle | Notes |
|---|---|---|---|---|
| `pfm` | ndarray (raw) + `DepthMap` (typed) | R+W | pure‑Python | gray/color raw API unchanged; explicit scalar typed-depth encoding, unit-magnitude header guard, bounded typed windows |
| `colmap_sparse` | `Reconstruction` | R+W | **pycolmap** | `.bin`; byte‑identical to pycolmap 4.1.1 |
| `colmap_sparse_txt` | `Reconstruction` | R+W | **pycolmap** | text twin of `.bin` |
| `gaussian_ply` | `GaussianCloud` | R+W | **gsply** | 3DGS Gaussian PLY, channel‑grouped f_rest |
| `compressed_ply` | `GaussianCloud` | R+W | pinned **PlayCanvas splat-transform 3.1.6** vector + NumPy oracle | SuperSplat chunked PLY; deterministic Morton writer; lossy position/scale/quaternion/RGBA/SH quantization; degree 0–3; bounded point reads |
| `sog` | `GaussianCloud` | R+W | pinned **PlayCanvas splat-transform 3.1.6** source + independent Pillow/NumPy/ZIP oracle | SOG v2 bundled ZIP and unbundled directory; strict lossless-WebP layers; deterministic Morton/codebook/palette writer; degree 0–3; bounded point allocation |
| `ksplat` | `GaussianCloud` | R+W | pinned **GaussianSplats3D 0.4.7** vectors + independent struct/NumPy oracle | mkkellogg v0.1; compression levels 0–2; SH degrees 0–2; multi-section read; deterministic single-section bucketed writer; bounded point allocation |
| `spz` | `GaussianCloud` | R+W | **gsply** | v1/2/3 read, **v3+v4 write**, v4 read; bit‑exact v3 encode |
| `splat` | `GaussianCloud` | R+W | numpy oracle | antimatter15 blob; WXYZ+SH_C0 verified; lossy 8‑bit, SH‑drop |
| `transforms_json` | `PosedViewSet` | R+W | pure‑Python | NeRF/Instant‑NGP/Nerfstudio; records OpenGL c2w |
| `tum` | `PosedViewSet` | R+W | pure‑Python | TUM trajectory (xyzw, verbatim) |
| `kitti` | `PosedViewSet` | R+W | pure‑Python | KITTI 3×4 [R\|t] poses |
| `bundler` | `Reconstruction` | R+W | pycolmap | Bundler `.out` |
| `nvm` | `Reconstruction` | R+W | manual | VisualSFM `.nvm` (NVM_V3) |
| `openmvg` | `Reconstruction` | R+W | manual | openMVG `sfm_data.json` |
| `npy` | ndarray | R+W | **numpy** | pinned mapped native/C-order view; byte‑exact v1.0 writer (== np.save) |
| `npz` | `TensorDict` | R+W | **numpy** | ZIP (stored+deflate) via vendored miniz; 12 dtypes |
| `netpbm` | `Image` | R+W | pure‑Python | PGM P5/P2 + PPM P6/P3; 16‑bit big‑endian, comment‑tolerant |
| `.xyz` | `PointCloud` | R+W | pure‑Python | headerless point-cloud text (fast_float parsing) |
| `.pts` | `PointCloud` | R+W | independent parser | mandatory count header; XYZ/XYZI/XYZRGB/XYZIRGB; count validation |
| `.flo` | ndarray (raw) + `FlowField` (typed) | R+W | independent NumPy parser | raw API retains its pinned mapped view; `read_flow`/`write_flow`/`inspect_flow` attach and guard Middlebury semantics |

### ✅ Complete — image / point tier via **vendored permissive source** (no system libs)

Key reframing (proven out): most "needs a C lib" formats have permissive,
self‑contained source libraries that drop into the **existing FetchContent/vendored
pattern** (miniz, zstd, nlohmann/json, fast_float) — so they needed **no vcpkg/conda
`SCENEIO_WITH_*` gate** and kept runtime numpy‑only.

| Format | Record | Vendored lib (license) | Status |
|---|---|---|---|
| PNG (incl. 16‑bit depth) | `Image` (raw) + `DepthMap` (typed) | lodepng (zlib) — self‑contained inflate | ✅ R+W; raw palette/RGB/RGBA API unchanged; typed grayscale uint16 exact widening/guarded write with explicit encoding |
| JPEG (baseline+progressive) | `Image` | stb (public domain) | ✅ R (gray+RGB) / W (RGB‑only); pillow oracle; lossy |
| Radiance `.hdr` | `Image`(f32) | stb (public domain) | ✅ R+W; numpy RGBE oracle; lossy encode |
| OpenEXR | `Image`(f32) (raw) + `DepthMap` (typed) | tinyexr (BSD) — reuses our miniz | ✅ R+W; OpenEXR‑python oracle; HALF→FLOAT, premult‑alpha, PIZ/ZIP/RLE; explicit single-channel typed depth |
| plain `.las` | `PointCloud` | **none** — hand‑parsed binary, like colmap `.bin` | ✅ R+W; laspy oracle; formats 0‑3/6‑8, origin+rgb16, georef rebase |
| WebP | `Image` | libwebp (BSD) — CMake FetchContent from source | ✅ R+W; pillow oracle; lossless byte‑exact + lossy; built clean on MSVC |

Cross‑cutting: the cibuildwheel dry run and tagged release both built and
smoke‑tested the abi3 wheels on Linux, macOS, and Windows. SceneIO 0.2.0 is
published on PyPI from the tag workflow; libwebp‑from‑source therefore clears
the outstanding wheel‑build gate. Vendored stb carries documented **local
hardening patches** for truncated HDR input, corrupt JPEG marker failure, and a
signed-shift UB in JPEG entropy output (see `stb/COMMIT.txt`). CMYK JPEG is
best‑effort stb→RGB and opaque RGBA collapses to RGB in WebP (both documented).

Genuinely need the system‑lib `SCENEIO_WITH_*` gate (deferred): HDF5 (+hloc), TIFF
(libtiff). **LAZ is vendorable after all** — laz‑perf (Apache‑2.0), point‑cloud
tier. COLMAP DB `.db` is covered by a pinned public-domain SQLite amalgamation
statically linked into `_core`.

### ✅ Post-0.2 self-contained expansion

| Format id | Record | R/W | Oracle | Notes |
|---|---|---|---|---|
| `safetensors` | `TensorDict` | R+W | **safetensors.numpy 0.8** | deterministic canonical writer; all 12 TensorDict dtypes; string metadata; read-only mmap views; named-tensor and leading-axis slice reads |
| `dmb` | `DepthMap` | R+W | independent NumPy parser | scalar Gipuma/COLMAP float32 depth; exact little-endian payload; unknown scale; zero-invalid; bounded windows |
| `bal` | `Reconstruction` | R+W | UW BAL specification + independent parser | zero-based observations; angle-axis cameras with focal and two radial terms; explicit BAL↔SceneIO frame transform; strict canonical writer |
| `bmp` | `Image` | R+W | **Pillow** + Microsoft DIB specification | Windows V3/V4/V5 BI_RGB/BI_BITFIELDS; palette and packed-16 reads; top/bottom orientation; deterministic RGB/RGBA writers |
| `tga` | `Image` | R+W | **Pillow** + Truevision 2.0 specification | grayscale/RGB/RGBA and zero-origin palettes; raw/RLE; top/bottom orientation; deterministic RLE writer |
| `ply` | `PointCloud` | R+W | independent NumPy/stdlib parser + **Open3D 0.19** | ASCII and binary LE/BE; all standard scalar input types; exact rgb8/rgb16; schema-aware Gaussian/point/mesh dispatch; binary point ranges |
| `pcd` | `PointCloud` | R+W | independent NumPy/stdlib parser + **Open3D 0.19** | PCD 0.7 ASCII, little-endian binary, and LZF `binary_compressed`; organized dimensions and viewpoint; packed RGB/intensity; bounded binary point ranges |
| `euroc_state` | `StateTrajectory` | R+W | independent stdlib CSV parser + EuRoC schema | exact int64-ns timestamps; p/q(WXYZ)/v/gyro-bias/accel-bias; canonical-header detection; bounded state ranges |
| `opencv_yaml` / `opencv_xml` | `CameraRig` | R+W | **PyYAML** / stdlib ElementTree | exact K/D plus optional R/P; schema-signature detection; generic YAML/XML extensions intentionally unclaimed |
| `ros_camera_info` | `CameraRig` | R+W | **PyYAML** + ROS CameraInfo schema | exact K/D/R/P, distortion model, binning, ROI, and rectify flag |
| `kalibr` | `CameraRig` | R+W | **PyYAML** + Kalibr schema | pinhole/omni intrinsics, distortion, topics, camera-chain or IMU extrinsics, and camera↔IMU time offsets |
| `g2o` | `PoseGraph` | R+W | independent strict parser + g2o BSD-3 source semantics | `VERTEX_SE3:QUAT`, `EDGE_SE3:QUAT`, `FIX`; XYZW; exact upper-triangle information; unsupported mixed types/parameters reject |
| `colmap_db` | `ColmapDatabase` (`FeatureSet` + `MatchGraph`) | R+W | stdlib **sqlite3** + **pycolmap 4.1.1** | current six-table cameras/images/features/matches/two-view geometry subset; exact pair ids and absent/empty BLOB state; transactional writes; one-image/one-pair selectors |

### ⬜ Pending — later phases (meshes + niche)
glTF / GLB (+Draco) · OBJ / STL / OFF / mesh PLY · USD / USDZ · OpenVDB · Zarr · Parquet · AVIF / JPEG‑XL.

### 🟡 In progress — Phase 7 (hardening)
✅ mmap-backed reads for all 38 buffer codecs (SOG additionally supports an
unbundled native multi-file path; COLMAP DB and the two COLMAP directory codecs
read paths directly in native code) · ✅ zero-copy read-only mapped
ndarray views for native NPY/FLO payloads (PFM row-flips into owned storage) · ✅ bytes/mmap differential +
scheduled 100-case backing-store mutation sweep · ✅ ASan/UBSan/LSan workflow
(local and branch Linux runs green) · ⬜ randomized oracle-triangulated
fuzzing · ✅ direct file-sink writes · ✅ bounded measured-path workers
(XYZ/LAS/EXR/PNG16/WebP lossless) · ✅ partial/lazy reads (`inspect` covers all
41; bounded pixel/point/state/COLMAP-image/COLMAP-pair/tensor subsets cover
capable containers) · ⬜ GPU-via-DLPack (torch-cuda/cupy) · ✅ expanded
41-codec benchmark/oracles.

## Infrastructure & capabilities

| Piece | Status | Notes |
|---|---|---|
| nanobind + scikit‑build‑core build | ✅ | abi3/cp312, `NB_STATIC` |
| cibuildwheel release path | ✅ | Linux/macOS/Windows; `publish.yml` |
| CI parity (oracles in CI) | ✅ | gsply + pycolmap; runs on the branch |
| Codec registry + `read`/`write`/`inspect`/`read_partial`/`detect` | ✅ | inspection covers all 40; bounded partial hooks are capability-specific |
| Zero‑copy numpy + torch (DLPack) | ✅ | validated per codec |
| Conventions‑as‑metadata + write guards | ✅ | record‑don't‑convert enforced |
| Parity kit (`sceneio.testing.parity`) | ✅ | cross‑impl + round‑trip + convention pins |
| Vendored deps (miniz, zstd, nlohmann/json, fast_float) | ✅ | permissive; statically linked / header‑only |
| Vendored image libs (lodepng/stb/tinyexr/libwebp) | ✅ | permissive, pinned/local-patched; no system libs, numpy‑only runtime kept |
| Feature‑flagged optional C libs (`SCENEIO_WITH_*`) | ⬜ | planned for HDF5, TIFF, E57, Arrow, USD, and OpenVDB; LAZ uses vendored LAZperf instead |
| mmap / streaming sources | ✅ | mmap reads + raw NPY/FLO views + direct file-sink writes complete |
| Bounded intra-file workers | ✅ | measured O4 paths; deterministic one-vs-many lane tests |
| Sanitizer + mmap differential CI | ✅ | local Linux green; scheduled remote lane activates on default branch |
| Capability flags (`reads/writes/inspect/partial/streams/lossy/needs_dep`) | ✅ | frozen metadata through `sceneio.capabilities()`; snapshot below is CI-validated |
| `splat` / `posed_views` DataTypes in the vocabulary | ⬜ | **Phase‑C** (wire identity; cross‑repo) |

<!-- sceneio-capabilities:start -->
### Registry capability snapshot

This table is generated conceptually from `sceneio.capabilities()` and checked
byte-for-byte against the live registry by `tests/test_io_capabilities.py`.
Streaming means the public path avoids a whole-file/output-sized Python
`bytes`; it does not imply that the underlying compression algorithm is
incremental.

| Format id | Container | Read | Write | Inspect | Partial selectors | Stream read | Stream write | Lossy-capable | Native feature |
|---|---|---|---|---|---|---|---|---|---|
<!-- sceneio-capability-rows:start -->
| `bal` | file | yes | yes | yes | - | yes | yes | no | - |
| `bmp` | file | yes | yes | yes | - | yes | yes | no | - |
| `bundler` | file | yes | yes | yes | - | yes | yes | no | - |
| `colmap_db` | file | yes | yes | yes | image_id, pair | yes | yes | no | - |
| `colmap_sparse` | directory | yes | yes | yes | image_id | yes | yes | no | - |
| `colmap_sparse_txt` | directory | yes | yes | yes | image_id | yes | yes | no | - |
| `compressed_ply` | file | yes | yes | yes | points | yes | yes | yes | - |
| `dmb` | file | yes | yes | yes | window | yes | yes | no | - |
| `euroc_state` | file | yes | yes | yes | states | yes | yes | no | - |
| `exr` | file | yes | yes | yes | - | yes | yes | no | - |
| `flo` | file | yes | yes | yes | window | yes | yes | no | - |
| `g2o` | file | yes | yes | yes | - | yes | yes | no | - |
| `gaussian_ply` | file | yes | yes | yes | points | yes | yes | no | - |
| `hdr` | file | yes | yes | yes | - | yes | yes | yes | - |
| `jpeg` | file | yes | yes | yes | - | yes | yes | yes | - |
| `kalibr` | file | yes | yes | yes | - | yes | yes | no | - |
| `kitti` | file | yes | yes | yes | - | yes | yes | no | - |
| `ksplat` | file | yes | yes | yes | points | yes | yes | yes | - |
| `las` | file | yes | yes | yes | points | yes | yes | yes | - |
| `netpbm` | file | yes | yes | yes | window | yes | yes | no | - |
| `npy` | file | yes | yes | yes | - | yes | yes | no | - |
| `npz` | file | yes | yes | yes | - | yes | yes | no | - |
| `nvm` | file | yes | yes | yes | - | yes | yes | no | - |
| `opencv_xml` | file | yes | yes | yes | - | yes | yes | no | - |
| `opencv_yaml` | file | yes | yes | yes | - | yes | yes | no | - |
| `openmvg` | file | yes | yes | yes | - | yes | yes | no | - |
| `pcd` | file | yes | yes | yes | points | yes | yes | no | - |
| `pfm` | file | yes | yes | yes | window | yes | yes | no | - |
| `ply` | file | yes | yes | yes | points | yes | yes | no | - |
| `png` | file | yes | yes | yes | - | yes | yes | no | - |
| `pts` | file | yes | yes | yes | points | yes | yes | no | - |
| `ros_camera_info` | file | yes | yes | yes | - | yes | yes | no | - |
| `safetensors` | file | yes | yes | yes | tensors, slices | yes | yes | no | - |
| `sog` | multi_file | yes | yes | yes | points | yes | yes | yes | - |
| `splat` | file | yes | yes | yes | points | yes | yes | yes | - |
| `spz` | file | yes | yes | yes | - | yes | yes | yes | - |
| `tga` | file | yes | yes | yes | - | yes | yes | no | - |
| `transforms_json` | file | yes | yes | yes | - | yes | yes | no | - |
| `tum` | file | yes | yes | yes | - | yes | yes | no | - |
| `webp` | file | yes | yes | yes | window | yes | yes | yes | - |
| `xyz` | file | yes | yes | yes | points | yes | yes | no | - |
<!-- sceneio-capability-rows:end -->

Supported and intentionally unsupported subfeatures, such as LAS point formats
or WebP animation/window behavior, are carried by each immutable capability
record rather than expanded into this summary.
<!-- sceneio-capabilities:end -->

<!-- sceneio-native-features:start -->
### Optional native-feature manifest

`sceneio.native_features()` reports build-time integrations even when they are
not compiled into the current extension. The table is checked byte-for-byte
against that public manifest.

| Feature | CMake option | Compiled | Planned format ids |
|---|---|---|---|
<!-- sceneio-native-feature-rows:start -->
| `arrow` | `SCENEIO_WITH_ARROW` | no | `parquet` |
| `avif` | `SCENEIO_WITH_AVIF` | no | `avif` |
| `draco` | `SCENEIO_WITH_DRACO` | no | `gltf`, `glb` |
| `e57` | `SCENEIO_WITH_E57` | no | `e57` |
| `hdf5` | `SCENEIO_WITH_HDF5` | no | `hdf5`, `hloc_features`, `hloc_matches` |
| `jxl` | `SCENEIO_WITH_JXL` | no | `jpeg_xl` |
| `openvdb` | `SCENEIO_WITH_OPENVDB` | no | `openvdb` |
| `tiff` | `SCENEIO_WITH_TIFF` | no | `tiff` |
| `usd` | `SCENEIO_WITH_USD` | no | `usd`, `usdz` |
<!-- sceneio-native-feature-rows:end -->

An unknown feature name raises the same normalized `FormatError` family used
by codec discovery. Future feature-enabled builds must export their compiled
names from `_core.__native_features__`.
<!-- sceneio-native-features:end -->

## Partial-read capability

`sceneio.read_partial` exposes only measured bounded paths:

| Selector | Formats | Result |
|---|---|---|
| pixel `window=(r0,r1,c0,c1)` | PFM, binary P5/P6 Netpbm, lossless VP8L WebP, FLO, scalar DMB | ndarray, `Image`, or `DepthMap`, matching the full-read slice with metadata preserved |
| point range `points=(start,stop)` | XYZ, PTS, binary generic PLY, uncompressed binary PCD, LAS, Gaussian PLY, SPLAT | `PointCloud` / `GaussianCloud`, with convention metadata preserved |
| `image_id` | COLMAP binary + text | one-image `Reconstruction` + its camera; no point-container read |
| `image_id` | COLMAP SQLite database | one compiled `FeatureSet`; unrelated keypoint/descriptor BLOBs remain unread |
| unordered `pair=(image_id1,image_id2)` | COLMAP SQLite database | one compiled `MatchGraph` with raw/verified matches and optional geometry |
| `tensors=(...)` | safetensors | selected complete tensors as a mapped `TensorDict`; other payload pages remain untouched |
| `slices={name: (start, stop)}` | safetensors | contiguous leading-axis slices as a mapped `TensorDict` |

PNG, JPEG, HDR, EXR, SPZ, ASCII generic PLY, ASCII/compressed PCD, and other compressed/scene containers intentionally
do not advertise a partial hook when their current decoder would still
materialize the complete payload. ASCII P2/P3 Netpbm rejects because it must
token-decode the complete raster; lossy VP8 rejects because a crop-local decode
cannot promise bit-exact parity with the full decoder's chroma context.
