# Format & data-structure coverage

The single source of truth for **what SceneIO's compiled core reads/writes today
vs. what's planned**. Consolidates the catalog (`formats_survey.md`) and the
roadmap (`io_implementation_plan.md` §3, §6, §7) against the actual codec
registry (`src/sceneio/io/registry.py`).

Legend: ✅ done · 🟡 partial · ⬜ pending · **R** read · **W** write

> Status note: everything marked ✅ lives on branch `phase0-nanobind-core`
> (compiled `sceneio._core`), not yet merged to `main` or published. See the
> release path in `io_implementation_plan.md` §8.

## Data structures (memory Records)

SoA, zero-copy to numpy/torch (DLPack), conventions carried as metadata.

| Record | Intended DataType | Status | Notes |
|---|---|---|---|
| `Reconstruction` | `sparse_model` | ✅ | cameras + image poses (WXYZ, world→cam) + points3D + tracks |
| `GaussianCloud` | `splat` | ✅ record / ⬜ datatype | DataType registration is **Phase‑C** (needs a wire‑format id); the codecs use `"splat"` as an informal label |
| `PosedViewSet` | `camera` + poses | ✅ record / ⬜ datatype | SE3/view + optional `Camera` intrinsics; per‑source convention tags (order/direction/axis/scale). `"posed_views"` label is informal, Phase‑C |
| `Camera` | (shared) | ✅ | COLMAP model id + `params[]`; reused by `Reconstruction` and `PosedViewSet` |
| `Image` | `image_sequence` elem | ✅ | interleaved HxWxC (u8/u16/f32), color_space/alpha_mode/maxval metadata, owner‑safe zero‑copy `pixels` |
| `TensorDict` | (named arrays) | ✅ | dict‑like, 12 numpy dtypes (dtype‑erased), zero‑copy views; backs npz now, HDF5/safetensors later |
| `PointCloud` | `point_cloud` (new) | ✅ | xyz + rgb + normals + intensity; backs `.xyz`/`.pts` (and plain `.las` next) |
| `DepthMap` / `Dense` | `dense` / `depth_map` | ✅ | typed depth + scale/unit/invalid + confidence |
| `FeatureSet` | `feature_set` | ⬜ | Phase 3 — keypoints + descriptors + scores |
| `MatchGraph` | `match_graph` | ⬜ | Phase 3 — per‑pair matches + F/E/H + inliers |

## Formats (codecs)

### ✅ Implemented — Tier‑1 zero‑dep spine (17 codecs, Phase 1a/1b/1c + 2)

| Format id | Record | R/W | Oracle | Notes |
|---|---|---|---|---|
| `pfm` | ndarray | R+W | pure‑Python | PFM depth/gray/color; mmap input + owned positive-stride row-flip |
| `colmap_sparse` | `Reconstruction` | R+W | **pycolmap** | `.bin`; byte‑identical to pycolmap 4.1.1 |
| `colmap_txt` | `Reconstruction` | R+W | **pycolmap** | text twin of `.bin` |
| `gaussian_ply` | `GaussianCloud` | R+W | **gsply** | 3DGS Gaussian PLY, channel‑grouped f_rest |
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
| `.xyz` / `.pts` | `PointCloud` | R+W | pure‑Python | point‑cloud text (fast_float parsing) |
| `.flo` | ndarray (H,W,2) | R+W | pure‑Python | Middlebury optical flow; pinned mapped view |

Deferred within Tier‑1: g2o poses (pose‑graph *edges* don't fit `PosedViewSet`).

### ✅ Complete — image / point tier via **vendored permissive source** (no system libs)

Key reframing (proven out): most "needs a C lib" formats have permissive,
self‑contained source libraries that drop into the **existing FetchContent/vendored
pattern** (miniz, zstd, nlohmann/json, fast_float) — so they needed **no vcpkg/conda
`SCENEIO_WITH_*` gate** and kept runtime numpy‑only.

| Format | Record | Vendored lib (license) | Status |
|---|---|---|---|
| PNG (incl. 16‑bit depth) | `Image` | lodepng (zlib) — self‑contained inflate | ✅ R+W; pillow+pypng oracles; palette/16‑bit/interlace |
| JPEG (baseline+progressive) | `Image` | stb (public domain) | ✅ R (gray+RGB) / W (RGB‑only); pillow oracle; lossy |
| Radiance `.hdr` | `Image`(f32) | stb (public domain) | ✅ R+W; numpy RGBE oracle; lossy encode |
| OpenEXR | `Image`(f32) | tinyexr (BSD) — reuses our miniz | ✅ R+W; OpenEXR‑python oracle; HALF→FLOAT, premult‑alpha, PIZ/ZIP/RLE |
| plain `.las` | `PointCloud` | **none** — hand‑parsed binary, like colmap `.bin` | ✅ R+W; laspy oracle; formats 0‑3/6‑8, origin+rgb16, georef rebase |
| WebP | `Image` | libwebp (BSD) — CMake FetchContent from source | ✅ R+W; pillow oracle; lossless byte‑exact + lossy; built clean on MSVC |

Cross‑cutting: all 6 codecs are validated on the **local MSVC build only** — the plan
gates the tier on a **cibuildwheel dry‑run** (Linux/macOS), still a pending user
action (push + `gh workflow run publish.yml`). libwebp‑from‑source is the one real
wheel‑build risk to confirm there. Vendored stb carries documented **local
hardening patches** for truncated HDR input, corrupt JPEG marker failure, and a
signed-shift UB in JPEG entropy output (see `stb/COMMIT.txt`). CMYK JPEG is
best‑effort stb→RGB and opaque RGBA collapses to RGB in WebP (both documented).

Genuinely need the system‑lib `SCENEIO_WITH_*` gate (deferred): HDF5 (+hloc), TIFF
(libtiff). **LAZ is vendorable after all** — laz‑perf (Apache‑2.0), point‑cloud
tier. COLMAP DB `.db` (sqlite) and safetensors are separate.

### ⬜ Pending — later phases (meshes + niche)
glTF / GLB (+Draco) · OBJ / STL / OFF · USD / USDZ · OpenVDB · Zarr · Parquet · AVIF / JPEG‑XL · PlayCanvas SOG · PCD.

### 🟡 In progress — Phase 7 (hardening)
✅ mmap-backed reads for all 21 single-file codecs (the two COLMAP directory
codecs already read paths directly in C++) · ✅ zero-copy read-only mapped
ndarray views for native NPY/FLO payloads (PFM row-flips into owned storage) · ✅ bytes/mmap differential +
scheduled 100-case backing-store mutation sweep · ✅ ASan/UBSan/LSan workflow
(local Linux green; remote run user-gated) · ⬜ randomized oracle-triangulated
fuzzing · ✅ direct file-sink writes · ⬜ partial/lazy reads · ⬜ GPU-via-DLPack
(torch-cuda/cupy) · 🟡 expanded 23-codec benchmark/oracles.

## Infrastructure & capabilities

| Piece | Status | Notes |
|---|---|---|
| nanobind + scikit‑build‑core build | ✅ | abi3/cp312, `NB_STATIC` |
| cibuildwheel release path | ✅ | Linux/macOS/Windows; `publish.yml` |
| CI parity (oracles in CI) | ✅ | gsply + pycolmap; runs on the branch |
| Codec registry + `read`/`write`/`detect` | ✅ | one‑entry‑per‑format |
| Zero‑copy numpy + torch (DLPack) | ✅ | validated per codec |
| Conventions‑as‑metadata + write guards | ✅ | record‑don't‑convert enforced |
| Parity kit (`sceneio.testing.parity`) | ✅ | cross‑impl + round‑trip + convention pins |
| Vendored deps (miniz, zstd, nlohmann/json, fast_float) | ✅ | permissive; statically linked / header‑only |
| Vendored image libs (lodepng/stb/tinyexr/libwebp) | ⬜ | **next tier** — FetchContent, no system libs, numpy‑only runtime kept |
| Feature‑flagged optional C libs (`SCENEIO_WITH_*`) | ⬜ | deferred — only for HDF5 / TIFF / LAZ (no permissive single‑header option) |
| mmap / streaming sources | ✅ | mmap reads + raw NPY/FLO views + direct file-sink writes complete |
| Sanitizer + mmap differential CI | ✅ | local Linux green; scheduled remote lane activates on default branch |
| Capability flags (`reads/writes/streams/lossy/needs_dep`) | ⬜ | surface per codec |
| `splat` / `posed_views` DataTypes in the vocabulary | ⬜ | **Phase‑C** (wire identity; cross‑repo) |
