# Format & data-structure coverage

The single source of truth for **what SceneIO's compiled core reads/writes today
vs. what's planned**. Consolidates the catalog (`formats_survey.md`) and the
roadmap (`io_implementation_plan.md` §3, §6, §7) against the actual codec
registry (`src/sceneio/io/registry.py`).

The detailed execution, verification, and wheel-validation sequence for the
remaining formats is in
[`format_gap_implementation_plan.md`](format_gap_implementation_plan.md).
The prerequisite module-boundary, offline-source, and measured codec-backend
gate is in
[`repository_organization_plan.md`](repository_organization_plan.md).

Legend: ✅ done · 🟡 partial · ⬜ pending · **R** read · **W** write

> Status note: everything marked ✅ is implemented by the compiled
> `sceneio._core`. The original 23 codecs ship in SceneIO 0.2.0; safetensors,
> PTS, DMB, BAL, BMP, TGA, generic point PLY, PCD, EuRoC state CSV, and the
> OpenCV/ROS/Kalibr calibration codecs, g2o pose graphs, and the COLMAP
> feature database, SuperSplat compressed PLY, PlayCanvas SOG, KSplat,
> mesh/scene codecs, LAZ, lazy image directories, and raw Y4M are post-0.2
> formats on
> `phase0-nanobind-core` and are not released yet.
>
> **Latest tested code checkpoint (2026-07-25, `ea622ac`):** the live registry contains
> 50 available codecs. Every codec reports read, write, inspect, streaming read,
> and streaming write support; 28 advertise a bounded partial selector. Local
> MSVC validation passes 2,912 tests with 4 documented skips, the 50-codec
> benchmark guard, sdist/wheel rebuild, and a NumPy-only installed-wheel smoke.
> The latest Windows and macOS mmap jobs pass. The current Linux normal and
> instrumented jobs are not green; their exact blockers are recorded below and
> in `format_gap_implementation_plan.md` rather than being described as pending
> remote work.

## Data structures (memory Records)

SoA, zero-copy to numpy/torch (DLPack), conventions carried as metadata.

| Record | Intended DataType | Status | Notes |
|---|---|---|---|
| `Reconstruction` | `sparse_model` | ✅ | cameras + image poses (WXYZ, world→cam) + points3D + tracks |
| `GaussianCloud` | `splat` | ✅ record / ⬜ datatype | DataType registration is **Phase‑C** (needs a wire‑format id); the codecs use `"splat"` as an informal label |
| `PosedViewSet` | `camera` + poses | ✅ record / ⬜ datatype | SE3/view + optional `Camera` intrinsics; per‑source convention tags (order/direction/axis/scale). `"posed_views"` label is informal, Phase‑C |
| `Camera` | (shared) | ✅ | COLMAP model id + `params[]`; reused by `Reconstruction` and `PosedViewSet` |
| `Image` | `image_sequence` elem | ✅ | interleaved HxWxC (u8/u16/f32), color_space/alpha_mode/maxval metadata, owner-safe zero-copy `pixels` |
| `ImageSequence` | `image_sequence` | ✅ | owned lazy encoded-frame paths or owned uint8 planar Y/U/V frames; exact optional int64-ns timing, dimensions, chroma sampling/siting, range, matrix, interlace, rate, and aspect metadata |
| `TensorDict` | (named arrays) | ✅ | dict‑like, 12 numpy dtypes (dtype‑erased), zero‑copy views; backs NPZ and mapped safetensors |
| `PointCloud` | `point_cloud` (new) | ✅ | xyz + rgb/rgb16 + normals + intensity, optional organized width/height and acquisition viewpoint, plus an optional validated lossless LAS waveform sidecar; backs `.xyz`, count-prefixed `.pts`, point `.ply`, PCD, plain `.las`, and `.laz` |
| `DepthMap` | `depth_map` | ✅ | scalar f32 depth + scale/unit/invalid + confidence; backs scalar DMB and explicit typed PFM/PNG/EXR adapters |
| `FlowField` | `flow` | ✅ | HxWx2 f32 vectors with component/axis/row/unit/invalid metadata; raw FLO API remains ndarray-compatible |
| `StateTrajectory` | `state_trajectory` | ✅ record / ⬜ datatype | exact int64 nanosecond timestamps plus float64 position, WXYZ orientation, velocity, gyro bias, and accelerometer bias; explicit frame/unit/sign metadata |
| `CameraRig` | `camera_rig` | ✅ record / ⬜ datatype | ordered cameras; ragged model parameters; exact optional K/R/P; extrinsic, ROI/binning, topic, and time-offset metadata with explicit conventions |
| `PoseGraph` | `pose_graph` | ✅ record / ⬜ datatype | ordered typed SE(3) nodes/edges, fixed-node flags, exact ids, XYZW transforms, and symmetric 6×6 information matrices with explicit direction/order metadata |
| `FeatureSet` | `feature_set` | ✅ record / ⬜ datatype | per-image id/name/camera/size; Nx{2,4,6} f32 keypoints; optional u8/f32 descriptors and f32 scores with absent-vs-empty fidelity |
| `MatchGraph` | `match_graph` | ✅ record / ⬜ datatype | canonical COLMAP image pairs and pair ids; ragged raw/verified u32 matches; optional scores, F/E/H, config, and relative pose |
| `ColmapDatabase` | `match_graph` | ✅ record / ⬜ datatype | cameras, prior-focal flags, ordered `FeatureSet` values, `MatchGraph`, and schema user version |
| `MaterialSet` | `material_set` | ✅ record / ⬜ datatype | metallic-roughness factors, alpha modes, URI texture references, UV sets, and sampler metadata; material names may be empty or repeated as glTF permits |
| `Mesh` | `mesh` | ✅ record / ⬜ datatype | polygon-preserving ragged topology; vertex/corner normals, UVs, RGBA; primitive/material domains; coordinate metadata and local transform |
| `MeshScene` | `mesh_scene` | ✅ record / ⬜ datatype | ordered mesh primitives, mesh-to-primitive ranges, shared materials, node hierarchy/local transforms, scene roots, names, and default scene |

## Formats (codecs)

### ✅ Implemented — original and self-contained codec spine

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

### ✅ Complete — image / point tier via **permissive native source** (no system libs)

Key reframing (proven out): most "needs a C lib" formats have permissive,
self-contained source libraries that drop into the existing pinned-source
native build pattern (miniz, zstd, nlohmann/json, fast_float) — so they needed **no vcpkg/conda
`SCENEIO_WITH_*` gate** and kept runtime numpy-only.

| Format | Record | Native backend (license) | Status |
|---|---|---|---|
| PNG (incl. 16‑bit depth) | `Image` (raw) + `DepthMap` (typed) | lodepng (zlib) — self‑contained inflate | ✅ R+W; raw palette/RGB/RGBA API unchanged; typed grayscale uint16 exact widening/guarded write with explicit encoding |
| JPEG (baseline+progressive) | `Image` | stb (public domain) | ✅ R (gray+RGB) / W (RGB‑only); pillow oracle; lossy |
| Radiance `.hdr` | `Image`(f32) | stb (public domain) | ✅ R+W; numpy RGBE oracle; lossy encode |
| OpenEXR | `Image`(f32) (raw) + `DepthMap` (typed) | tinyexr (BSD) — reuses our miniz | ✅ R+W; OpenEXR‑python oracle; HALF→FLOAT, premult‑alpha, PIZ/ZIP/RLE; explicit single-channel typed depth |
| plain `.las` | `PointCloud` | **none** — hand‑parsed binary, like colmap `.bin` | ✅ R+W; laspy oracle; formats 0‑10, origin+rgb16, georef rebase; formats 4/5/9/10 preserve internal waveform descriptor VLRs, packet EVLR, references, and opaque point fields in a sidecar |
| `.laz` | `PointCloud` | LAZperf 3.4.0 (Apache‑2.0/BSD‑3-Clause/BSD‑2-Clause) | ✅ R+W; laspy/lazrs oracle; formats 0‑3 and 6‑8, exact standard records, chunk-parallel decode and chunk-aware ranges, mmap, header inspect, seekable streaming sink; waveform, extra bytes, unrelated VLR/EVLR metadata, and COPC reject |
| WebP | `Image` | libwebp (BSD) — CMake FetchContent from source | ✅ R+W; pillow oracle; lossless byte‑exact + lossy; built clean on MSVC |

Cross‑cutting: the cibuildwheel dry run and tagged release both built and
smoke‑tested the abi3 wheels on Linux, macOS, and Windows. SceneIO 0.2.0 is
published on PyPI from the tag workflow; libwebp‑from‑source therefore clears
the outstanding wheel‑build gate. Vendored stb carries documented **local
hardening patches** for truncated HDR input, corrupt JPEG marker failure, and a
signed-shift UB in JPEG entropy output (see `stb/COMMIT.txt`). CMYK JPEG is
best‑effort stb→RGB and opaque RGBA collapses to RGB in WebP (both documented).

Genuinely need the system‑lib `SCENEIO_WITH_*` gate (deferred): HDF5 (+hloc),
TIFF (libtiff). **LAZ is vendored** through pinned LAZperf 3.4.0
(Apache‑2.0/BSD‑3-Clause/BSD‑2-Clause), with formats 0‑3 and 6‑8 in its supported
compression set. COLMAP DB `.db` is covered by a pinned public-domain SQLite amalgamation
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
| `ply_mesh` | `Mesh` | R+W | independent struct/NumPy oracle | polygon-preserving ASCII and binary LE/BE; vertex/corner normals, UVs, RGBA; primitive/material ranges; coordinate metadata and local transforms |
| `obj` | `Mesh` + `MaterialSet` | R+W | pinned **TinyObjLoader** + **trimesh 4** | polygon-preserving independent indices; vertex/corner normals and UVs; RGB8, object/group/smoothing domains; strict single-library MTL factors and texture maps; adjacent paired OBJ/MTL output |
| `stl` | `Mesh` | R+W | independent `struct`/text parsers + **trimesh 4** | strict binary LE and ASCII; canonical unwelded triangle soup; facet normals; bounded face ranges; ambiguous facet attributes/colors reject |
| `off` | `Mesh` | R+W | independent token parser + **trimesh 4** | strict record-per-line (1 MiB cap) polygon-preserving ASCII OFF/NOFF/COFF/ST variants; exact vertex normals, UVs, and RGBA8; bounded face ranges |
| `gltf` | `MeshScene` | R+W | **pygltflib 1.16** + **trimesh 4** | glTF 2.0 JSON with mapped external or base64 data buffers; strided/sparse accessors, triangle primitives, nodes/scenes, metallic-roughness materials, and URI images; mesh/primitive selectors; atomic paired `.gltf` + `.bin` sink |
| `glb` | `MeshScene` | R+W | **pygltflib 1.16** + **trimesh 4** | GLB 2.0 with embedded BIN; same canonical scene/material subset and selectors as `gltf`; single-file mmap and direct sink |
| `pcd` | `PointCloud` | R+W | independent NumPy/stdlib parser + **Open3D 0.19** | PCD 0.7 ASCII, little-endian binary, and LZF `binary_compressed`; organized dimensions and viewpoint; packed RGB/intensity; bounded binary point ranges |
| `euroc_state` | `StateTrajectory` | R+W | independent stdlib CSV parser + EuRoC schema | exact int64-ns timestamps; p/q(WXYZ)/v/gyro-bias/accel-bias; canonical-header detection; bounded state ranges |
| `opencv_yaml` / `opencv_xml` | `CameraRig` | R+W | **PyYAML** / stdlib ElementTree | exact K/D plus optional R/P; schema-signature detection; generic YAML/XML extensions intentionally unclaimed |
| `ros_camera_info` | `CameraRig` | R+W | **PyYAML** + ROS CameraInfo schema | exact K/D/R/P, distortion model, binning, ROI, and rectify flag |
| `kalibr` | `CameraRig` | R+W | **PyYAML** + Kalibr schema | pinhole/omni intrinsics, distortion, topics, camera-chain or IMU extrinsics, and camera↔IMU time offsets |
| `g2o` | `PoseGraph` | R+W | independent strict parser + g2o BSD-3 source semantics | `VERTEX_SE3:QUAT`, `EDGE_SE3:QUAT`, `FIX`; XYZW; exact upper-triangle information; unsupported mixed types/parameters reject |
| `colmap_db` | `ColmapDatabase` (`FeatureSet` + `MatchGraph`) | R+W | stdlib **sqlite3** + **pycolmap 4.1.1** | current six-table cameras/images/features/matches/two-view geometry subset; exact pair ids and absent/empty BLOB state; transactional writes; one-image/one-pair selectors |
| `laz` | `PointCloud` | R+W | **laspy 2.7 + lazrs 0.8.1** | pinned LAZperf 3.4.0; standard formats 0–3/6–8; strict LASzip VLR/chunk extents; chunk-aware ranges; seekable streaming sink |
| `image_sequence` | `ImageSequence` | R+W | independent manifest/PGM fixtures + existing image-codec parity suites | flat image directories; deterministic natural order or strict versioned manifest; lazy owned paths; exact optional timing; heterogeneous frames reject; transactional bounded-copy writer; frame ranges |
| `y4m` | `ImageSequence` | R+W | independent Python parser/writer + exact golden bytes | original dependency-free YUV4MPEG2 subset; uint8 mono/4:2:0/4:2:2/4:4:4 planar frames, odd dimensions, exact rational timing, mmap, streaming sink, inspect, and frame ranges; no RGB conversion or video-framework dependency |

### ⬜ Pending — declared roadmap gaps

- Sequence/dataset: animated WebP, APNG, and RTMV.
- Optional scientific/container: HDF5, hloc feature/match layouts, TIFF, E57,
  and Parquet/Arrow.
- Chunked/heavyweight: Zarr v2/v3, USD/USDZ, and OpenVDB.
- Policy-gated: AVIF, JPEG-XL, and Draco-compressed glTF. These do not enter
  implementation without an explicit decision under the patented-codec rule.

Draco-compressed glTF remains policy-gated. Plain glTF/GLB is implemented and
rejects Draco, meshopt, unknown extensions, and unrepresented scene features
rather than silently flattening or dropping them.

### 🟡 In progress — Phase 7 (hardening)
✅ mmap-backed reads for all buffer-backed file codecs plus paired OBJ/MTL and
glTF/external-buffer mappings (SOG additionally supports an unbundled native
multi-file path; COLMAP DB and the two COLMAP directory codecs read paths
directly in native code) · ✅
zero-copy read-only mapped
ndarray views for native NPY/FLO payloads (PFM row-flips into owned storage) · ✅ bytes/mmap differential +
scheduled 100-case backing-store mutation sweep · 🟡 instrumented native
reliability workflow exists, but the current Linux job is blocked by test
environment collection/leak-filter issues before it can establish a green
core result · ⬜ randomized oracle-triangulated
fuzzing · ✅ direct file-sink writes · ✅ bounded measured-path workers
(XYZ/LAS/LAZ/EXR/PNG16/WebP lossless) · ✅ partial/lazy reads (`inspect` covers all
50; bounded pixel/point/face/mesh/primitive/state/frame/COLMAP-image/COLMAP-pair/tensor
subsets cover capable containers) · ⬜ GPU-via-DLPack (torch-cuda/cupy) · ✅
expanded 50-codec benchmark/oracles.

## Infrastructure & capabilities

| Piece | Status | Notes |
|---|---|---|
| nanobind + scikit‑build‑core build | ✅ | abi3/cp312, `NB_STATIC` |
| cibuildwheel release path | ✅ | Linux/macOS/Windows; `publish.yml` |
| CI parity (oracles in CI) | 🟡 | Windows/macOS mmap jobs pass at `ea622ac`; Linux normal CI has six unresolved portability failures: three Y4M inspection `std::bad_cast` failures, one SQLite exclusive-lock expectation, and two environment-sensitive RSS bounds |
| Codec registry + `read`/`write`/`inspect`/`read_partial`/`detect` | ✅ | inspection covers all 50; bounded partial hooks are capability-specific |
| Repo-maintained stable codec adapters | ✅ | all 50 production adapters, grammars, convention guards, inspectors, partial capability policies/available paths, and sinks live in `src/cpp` / `src/sceneio`; separately installed implementations and executables are test/reference oracles only |
| Offline native-source closure | 🟡 | lodepng, stb, tinyexr, SQLite, tinyobjloader, and cgltf are stored in-tree; miniz, nlohmann/json, zstd, fast_float, LAZperf, and libwebp still use pinned CMake `FetchContent` and must move under `src/cpp/third_party/` before the post-0.2 tier is called stable |
| Zero‑copy numpy + torch (DLPack) | ✅ | validated per codec |
| Conventions‑as‑metadata + write guards | ✅ | record‑don't‑convert enforced |
| Parity kit (`sceneio.testing.parity`) | ✅ | cross‑impl + round‑trip + convention pins |
| In-tree native dependencies | 🟡 | permissive and license-indexed; six dependencies remain source-fetched as described by the offline-closure row |
| Image libraries | 🟡 | lodepng/stb/tinyexr are in-tree; libwebp 1.5.0 is pinned and statically built but still fetched at configure time |
| Feature‑flagged optional C libs (`SCENEIO_WITH_*`) | ⬜ | planned for HDF5, TIFF, E57, Arrow, USD, and OpenVDB; LAZ instead uses pinned, statically built LAZperf in the default tier |
| mmap / streaming sources | ✅ | mmap reads + raw NPY/FLO views + direct file-sink writes complete |
| Bounded intra-file workers | ✅ | measured O4 paths; deterministic one-vs-many lane tests |
| Instrumented + mmap differential CI | 🟡 | workflow is present; the latest instrumented Linux job stops during collection because its helper removes the unconditionally imported pycolmap oracle, and leak filtering also reports 376 bytes from CPython/pydantic rather than SceneIO frames |
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
| `glb` | file | yes | yes | yes | mesh_id, primitive_id | yes | yes | no | - |
| `gltf` | multi_file | yes | yes | yes | mesh_id, primitive_id | yes | yes | no | - |
| `hdr` | file | yes | yes | yes | - | yes | yes | yes | - |
| `image_sequence` | directory | yes | yes | yes | frames | yes | yes | no | - |
| `jpeg` | file | yes | yes | yes | - | yes | yes | yes | - |
| `kalibr` | file | yes | yes | yes | - | yes | yes | no | - |
| `kitti` | file | yes | yes | yes | - | yes | yes | no | - |
| `ksplat` | file | yes | yes | yes | points | yes | yes | yes | - |
| `las` | file | yes | yes | yes | points | yes | yes | yes | - |
| `laz` | file | yes | yes | yes | points | yes | yes | yes | - |
| `netpbm` | file | yes | yes | yes | window | yes | yes | no | - |
| `npy` | file | yes | yes | yes | - | yes | yes | no | - |
| `npz` | file | yes | yes | yes | - | yes | yes | no | - |
| `nvm` | file | yes | yes | yes | - | yes | yes | no | - |
| `obj` | multi_file | yes | yes | yes | - | yes | yes | no | - |
| `off` | file | yes | yes | yes | faces | yes | yes | no | - |
| `opencv_xml` | file | yes | yes | yes | - | yes | yes | no | - |
| `opencv_yaml` | file | yes | yes | yes | - | yes | yes | no | - |
| `openmvg` | file | yes | yes | yes | - | yes | yes | no | - |
| `pcd` | file | yes | yes | yes | points | yes | yes | no | - |
| `pfm` | file | yes | yes | yes | window | yes | yes | no | - |
| `ply` | file | yes | yes | yes | points | yes | yes | no | - |
| `ply_mesh` | file | yes | yes | yes | faces | yes | yes | no | - |
| `png` | file | yes | yes | yes | - | yes | yes | no | - |
| `pts` | file | yes | yes | yes | points | yes | yes | no | - |
| `ros_camera_info` | file | yes | yes | yes | - | yes | yes | no | - |
| `safetensors` | file | yes | yes | yes | tensors, slices | yes | yes | no | - |
| `sog` | multi_file | yes | yes | yes | points | yes | yes | yes | - |
| `splat` | file | yes | yes | yes | points | yes | yes | yes | - |
| `spz` | file | yes | yes | yes | - | yes | yes | yes | - |
| `stl` | file | yes | yes | yes | faces | yes | yes | no | - |
| `tga` | file | yes | yes | yes | - | yes | yes | no | - |
| `transforms_json` | file | yes | yes | yes | - | yes | yes | no | - |
| `tum` | file | yes | yes | yes | - | yes | yes | no | - |
| `webp` | file | yes | yes | yes | window | yes | yes | yes | - |
| `xyz` | file | yes | yes | yes | points | yes | yes | no | - |
| `y4m` | file | yes | yes | yes | frames | yes | yes | no | - |
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
| point range `points=(start,stop)` | XYZ, PTS, binary generic PLY, uncompressed binary PCD, LAS, Gaussian PLY, compressed PLY, SOG, KSplat, SPLAT | `PointCloud` / `GaussianCloud`, with convention metadata preserved |
| face range `faces=(start,stop)` | generic mesh PLY, STL, OFF | `Mesh`; PLY/OFF retain the complete vertex domain, while STL returns local canonical triangle soup |
| state range `states=(start,stop)` | EuRoC state CSV | `StateTrajectory` with convention metadata preserved |
| frame range `frames=(start,stop)` | image directories, raw Y4M | `ImageSequence`; directory frames remain lazy encoded paths and Y4M copies only selected planar frames |
| `image_id` | COLMAP binary + text | one-image `Reconstruction` + its camera; no point-container read |
| `image_id` | COLMAP SQLite database | one compiled `FeatureSet`; unrelated keypoint/descriptor BLOBs remain unread |
| unordered `pair=(image_id1,image_id2)` | COLMAP SQLite database | one compiled `MatchGraph` with raw/verified matches and optional geometry |
| `tensors=(...)` | safetensors | selected complete tensors as a mapped `TensorDict`; other payload pages remain untouched |
| `slices={name: (start, stop)}` | safetensors | contiguous leading-axis slices as a mapped `TensorDict` |

PNG, JPEG, HDR, EXR, SPZ, ASCII point-cloud PLY, ASCII/compressed PCD, and other compressed/scene containers intentionally
do not advertise a partial hook when their current decoder would still
materialize the complete payload. ASCII P2/P3 Netpbm rejects because it must
token-decode the complete raster; lossy VP8 rejects because a crop-local decode
cannot promise bit-exact parity with the full decoder's chroma context.
