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
| `DepthMap` / `Dense` | `dense` / `depth_map` | ⬜ | PFM already decodes to a raw ndarray; the *typed* depth record (scale/unit/invalid metadata) is Phase 4 |
| `FeatureSet` | `feature_set` | ⬜ | Phase 1/3 — keypoints + descriptors + scores |
| `MatchGraph` | `match_graph` | ⬜ | Phase 1/3 — per‑pair matches + F/E/H + inliers |
| `PointCloud` | `point_cloud` (new) | ⬜ | Phase 5 — xyz + rgb + normals + intensity |
| `Image` | `image_sequence` elem | ⬜ | Phase 4 — pixels + color space + EXIF |
| `TensorDict` | (named arrays) | ⬜ | Phase 3 — HDF5 / npz / safetensors |

## Formats (codecs)

### ✅ Implemented (7 codecs)

| Format id | Record | R/W | Oracle | Notes |
|---|---|---|---|---|
| `pfm` | ndarray | R+W | pure‑Python | reference codec; PFM depth/gray/color |
| `colmap_sparse` | `Reconstruction` | R+W | **pycolmap** | `.bin`; byte‑identical to pycolmap 4.1.1 |
| `gaussian_ply` | `GaussianCloud` | R+W | **gsply** | 3DGS Gaussian PLY, channel‑grouped f_rest |
| `spz` | `GaussianCloud` | R+W | **gsply** | v1/2/3 read, **v3+v4 write**, v4 read; bit‑exact v3 encode |
| `transforms_json` | `PosedViewSet` | R+W | pure‑Python | NeRF/Instant‑NGP/Nerfstudio; records OpenGL c2w |
| `tum` | `PosedViewSet` | R+W | pure‑Python | TUM trajectory (xyzw, verbatim) |
| `kitti` | `PosedViewSet` | R+W | pure‑Python | KITTI 3×4 [R\|t] poses |

### ⬜ Pending — Tier‑1 spine (Phase 1, zero external deps)

| Format | Record | Oracle | Notes |
|---|---|---|---|
| `.npy` / `.npz` | `TensorDict`/ndarray | numpy | trivial; low marginal value (numpy does it) |
| PPM / PGM | `Image` | imageio | no‑dep image I/O |
| COLMAP `.txt` | `Reconstruction` | pycolmap | text variant (only `.bin` done) |
| g2o poses | `PosedViewSet` | manual | deferred — pose‑graph *edges* don't fit `PosedViewSet` |

### ⬜ Pending — Phase 2 (splat, mostly done)

| Format | Record | Oracle | Notes |
|---|---|---|---|
| `.splat` | `GaussianCloud` | ref loaders | the simple splat blob |
| SuperSplat compressed `.ply` | `GaussianCloud` | ref loaders | |
| *(3DGS `.ply` ✅, `.spz` ✅)* | | | already done |

### ⬜ Pending — Phase 3 (arrays / features · first C libs)
HDF5 + hloc layout (h5py) · COLMAP DB `.db` sqlite (pycolmap) · safetensors.

### ⬜ Pending — Phase 4 (images / HDR / depth)
PNG · JPEG · TIFF · WebP (Pillow/imageio) · **OpenEXR** · 16‑bit depth PNG · `.flo` optical flow.

### ⬜ Pending — Phase 5 (point clouds)
PCD (open3d) · LAS / LAZ (laspy / lazrs).

### ⬜ Pending — Phase 6 (meshes + niche)
glTF / GLB (+Draco) · OBJ / STL / OFF · USD / USDZ · OpenVDB · Zarr · Parquet · AVIF / JPEG‑XL · PlayCanvas SOG.

### ⬜ Pending — Phase 7 (hardening)
Differential fuzzing at scale · big‑file mmap/streaming · GPU‑via‑DLPack (torch‑cuda/cupy) · benchmarks vs oracles · ASan/leak runs.

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
| Vendored deps (miniz, zstd, nlohmann/json) | ✅ | permissive; statically linked |
| Feature‑flagged optional C libs (`SCENEIO_WITH_*`) | ⬜ | Phase 3+ (HDF5/PNG/EXR/LAS/…) |
| mmap / streaming sources | ⬜ | Phase 7 (early for COLMAP/LAS) |
| Capability flags (`reads/writes/streams/lossy/needs_dep`) | ⬜ | surface per codec |
| `splat` / `posed_views` DataTypes in the vocabulary | ⬜ | **Phase‑C** (wire identity; cross‑repo) |
