# SceneIO I/O + memory implementation plan (nanobind core)

**Status: DRAFT for review.** How to implement read/write **and** the
in-memory representation for the safe format set
(`docs/formats_survey.md`), as a **nanobind (C++)** core that hands back
**numpy and torch** (any recent version) **zero-copy**, with **parity
tests against reference "oracle" implementations** for every format.

---

## 0. Goals & non-goals

**Goals**
- One C++ core, bound with **nanobind**, implementing codecs + the
  struct-of-arrays memory model for the Tier-1→3 formats in the survey.
- **Zero-copy interop with numpy AND torch, version-agnostic** — via
  **DLPack** + nanobind's **stable ABI**. **numpy is the only hard runtime
  dep; torch is optional** (never a build or runtime dependency).
- **Parity ("oracle") tests** for every format: decode/encode with our
  core and with the canonical reference lib, assert equality; plus
  round-trip identity and convention pins.
- **Permissive-only** dependencies at runtime *and* build time; even the
  test-only oracle libs are MIT/BSD/Apache/Boost/zlib.

**Non-goals**
- **No video decode** — image sequences only (no FFmpeg, no patented codecs).
- **No engine logic** (SfM/3DGS training, matching) — this is pure I/O +
  memory. SceneIO stays a contract/representation plane.
- **No GPU-side decode** initially — decode is host-side; the framework
  moves buffers to device via DLPack.
- **No proprietary / copyleft / NC** code, per `formats_survey.md` §1.

---

## 1. Architecture & layering

```
             ┌─────────────────────────────────────────────┐
  files ⇄    │  sceneio._core   (C++ / nanobind, compiled)  │
 (bytes,     │   • codecs: read(source)->Record             │
  mmap,      │             write(Record, sink)              │
  streams)   │   • SoA Record objects own contiguous buffers│
             └───────────────┬─────────────────────────────┘
                             │ zero-copy views (owner keepalive)
             ┌───────────────▼─────────────────────────────┐
             │  numpy ndarray  ·  torch tensor  ·  (cupy…)  │  via DLPack
             └───────────────┬─────────────────────────────┘
                             │
             ┌───────────────▼─────────────────────────────┐
  public API │  sceneio  (Python contract plane, unchanged) │
             │   formats.registry · data.* protocols ·      │
             │   errors · testing (conformance kit)         │
             └─────────────────────────────────────────────┘
```

- **`sceneio` (Python)** keeps its role and public surface: the DataType /
  FormatSpec registry, the `data.*` protocols, `errors`, and the
  conformance `testing` kit. **Still imports nothing from the family.**
- **`sceneio._core` (C++/nanobind)** is the compiled codec + memory engine,
  registered *into* the existing `formats.registry` (a codec per format id).
- **The compiled `_core` is mandatory** (decision **D1: compiled-only** — no
  pure-Python fallback). `import sceneio` requires the built extension, so
  there is exactly **one code path per format** and the parity suite can
  never diverge between a fast and a slow implementation. Cost: every install
  and CI lane needs a compiler or a prebuilt wheel (see §8).

The load-bearing property (`data ≠ code` from the survey): SceneIO writes
its **own** codecs. It never links COLMAP/INRIA/NVIDIA engines; the oracle
libs are **test-only**.

---

## 2. Array interop — the crux (numpy + torch, any version)

`nb::ndarray` is the entire bridge. It speaks the **buffer protocol**
(numpy) and **DLPack** (torch, cupy, jax), so version independence comes
"for free" from those stable protocols rather than from the numpy/torch C
ABI.

**Return path (read) — zero-copy view with lifetime safety.** The Record
object owns the contiguous C++ buffer; the accessor returns a view whose
`owner` is the Record, so the buffer outlives every array handed out:

```cpp
// SoA record: contiguous, aligned, native-endian buffers
struct PointCloud { std::vector<float> xyz; std::vector<uint8_t> rgb; size_t n; };

nb::class_<PointCloud>(m, "PointCloud")
  .def_prop_ro("positions", [](nb::object self) {
      auto& pc = nb::cast<PointCloud&>(self);
      size_t shape[2]{pc.n, 3};
      return nb::ndarray<nb::numpy, float, nb::c_contig>(
          pc.xyz.data(), /*ndim*/2, shape, /*owner*/self);   // no copy
  });
```

- **Default = numpy** (the hard dep). Every Record exposes **`__dlpack__`**,
  so `torch.from_dlpack(rec.positions)` / `cupy.from_dlpack(...)` are
  **zero-copy and version-agnostic**; `torch.from_numpy(...)` also works for
  CPU. Optional thin `.torch()` helpers wrap this.
- **Write path** accepts `nb::ndarray<>` from *any* framework (buffer or
  DLPack) as a **read-only view**; it copies only when non-contiguous or the
  dtype/endianness needs converting — otherwise it consumes the caller's
  buffer directly.
- **Canonicalization:** decode to **native-endian, C-contiguous** with a
  **fixed canonical dtype per field** (e.g. positions `float32` Nx3, colors
  `uint8` Nx3, descriptors `float32`/`uint8` NxD). Endianness (PLY BE, PNG
  BE-in-file, PFM sign-bit, COLMAP LE) is resolved in C++; Python always
  sees native.
- **Stable ABI:** build against the limited API (`abi3`) so **one wheel
  covers all supported Python 3.x**; DLPack decouples us from the numpy/torch
  ABIs entirely.

---

## 3. In-memory representation (the memory model)

**Struct-of-Arrays (SoA), contiguous, 64-byte aligned.** SoA is the right
model: it's zero-copy to numpy/torch, SIMD/GPU-friendly, and matches how
every consumer (COLMAP, gsplat, hloc) already thinks. Records own their
buffers; ndarray accessors are views.

Records map onto the existing (+ deferred) SceneIO DataTypes:

| Record (C++) | DataType | Fields (canonical dtype / shape) |
|---|---|---|
| `Reconstruction` | `sparse_model` | cameras (model id + `params[]`), images (pose `SE3` R\|t, name), points3D (`xyz` Nx3 f64, `rgb` Nx3 u8, `error` N, tracks) |
| `FeatureSet` | `feature_set` | `keypoints` Nx{2,4,6} f32, `descriptors` NxD (f32/u8), `scores` N, `image_size` 2 |
| `MatchGraph` | `match_graph` | per-pair `matches` Mx2 u32, `scores` M, optional `F/E/H` 3x3 f64, `inliers` |
| `GaussianCloud` | **`splat`** (new) | `means` Nx3, `scales` Nx3, `quats` Nx4, `opacity` N, `sh` Nx(3+45); activation flags |
| `DepthMap` / `Dense` | **`dense`/`depth_map`** (new) | `depth` HxW f32 (+ `scale`, `unit`, `invalid` sentinel in metadata), `confidence` HxW |
| `PointCloud` | `point_cloud` (new) | `xyz` Nx3, `rgb` Nx3 u8, `normals` Nx3, `intensity` N |
| `Image` | `image_sequence` element | `pixels` HxWxC (u8/u16/f16/f32), `color_space`, EXIF |
| `PosedViewSet` | `camera` + poses | intrinsics + `SE3` per view + **explicit convention tag** |
| `TensorDict` | (arrays) | named ndarrays (HDF5/npz/safetensors) |

**Conventions live in metadata, not the arrays** — the survey's #1 bug
class. Every pose-bearing record carries an explicit tag: quaternion order
(WXYZ vs XYZW), pose direction (world→cam vs cam→world), axis frame
(OpenCV +Z-fwd/+Y-down vs OpenGL/Blender −Z-fwd/+Y-up), and depth scale/unit
(TUM 1/5000 m, ScanNet mm). Codecs record what they read; a normalizer
converts on request.

---

## 4. Codec interface & registry

A uniform C++ codec concept, one instance per **format id** already in
`sceneio.formats.registry`:

```cpp
struct Codec {
  bool        sniff(std::span<const std::byte> head) const;  // magic/heuristic
  Record      read (Source&)  const;   // path | bytes | file-like | mmap
  void        write(const Record&, Sink&) const;
  FormatId    id;                      // e.g. "colmap.sparse.bin", "gaussian.ply"
};
```

- **Registry integration:** each codec registers under a format id; the
  Python `FormatSpec` gains a `codec` binding. `read(path)` dispatches by
  `sniff` + extension; `read_as(format_id, path)` forces one.
- **Sources/sinks:** path, `bytes`, Python file-like, and **mmap**;
  **streaming** for big files (LAS, HDF5, snapshot dirs, image sequences) so
  we never materialize a whole dataset.
- **Errors → `sceneio.errors`:** C++ throws typed errors mapped to
  `ContractViolation` / `FormatError` / `UnsupportedFeature`, so callers see
  the existing exception hierarchy, never a raw C++ abort.
- **Capability flags** per codec: `reads`, `writes`, `streams`, `lossy`,
  `needs_dep` (which optional C lib) — surfaced so a missing optional lib
  gives a clean "format not built" message, not an import crash.

---

## 5. Build & packaging

- **Toolchain:** `scikit-build-core` (PEP 517) + **CMake** + **nanobind**
  (FetchContent-pinned). Stable-ABI (`abi3`) wheels via **cibuildwheel**
  (manylinux + macOS + Windows, x86_64 + arm64).
- **Dependency policy (permissive only):**
  - **Vendored / header-only** (no system dep): `miniz`/`zlib`, `zstd`,
    `nlohmann/json` (or `simdjson`, Apache), the trivial parsers we write
    ourselves (COLMAP, PLY, PFM, npy, `.splat`/`.spz`, poses).
  - **Optional system libs behind feature flags** (`SCENEIO_WITH_*`):
    `libpng`, `libjpeg-turbo`, `libtiff`, **OpenEXR** (BSD-3), **HDF5**
    (BSD), `libwebp` (BSD), **laszip/lazrs** (Apache), `sqlite3` (public
    domain), optionally `OpenUSD`/`OpenVDB` (Apache). Provisioned via vcpkg
    or conda in CI.
  - **Runtime deps: numpy only.** torch/cupy never linked. Oracle libs are
    **test-only** extras.
- **Feature detection:** formats compile in as their deps are present;
  absent → the codec reports `needs_dep` and raises a clean error. A minimal
  build (no system libs) still ships the whole Tier-1 spine.

---

## 6. Parity testing — oracles (the core requirement)

Every format is validated against a **reference implementation as oracle**.
Three test kinds per format, all in an extension of the existing
`sceneio.testing` conformance kit (`assert_codec_parity(...)`):

1. **Cross-impl equality** — `ours.read(f)` vs `oracle.read(f)`; assert
   arrays equal (bit-exact for lossless/int, documented `eps` for lossy).
2. **Round-trip identity** — `ours.read(ours.write(x)) == x` (bit-exact for
   our own formats), and `oracle.read(ours.write(x)) == oracle_expected`
   (proves our *writer* is spec-correct, not just self-consistent).
3. **Convention pins** — decode a known file; assert the *interpreted*
   quantity (a full 4×4 pose matrix, a metric depth in meters) matches the
   oracle's, catching WXYZ/axis/scale mistakes the raw-array test misses.

Plus **cross-framework** (`np.asarray(rec.x) == torch.from_dlpack(rec.x)`)
and **differential fuzzing** (Hypothesis-generated valid Records → write →
read → compare to oracle; and byte-mutated real files must raise, not crash).

**Oracle matrix (all permissive, test-only):**

| Format(s) | Oracle | License |
|---|---|---|
| COLMAP `.bin`/`.txt`/`.db` + camera models | **pycolmap** | BSD |
| PLY, PCD | **open3d** (MIT) / **plyfile** (BSD) | MIT/BSD |
| 3DGS `.ply` | plyfile + **gsplat/nerfstudio** loader cross-check | Apache |
| `.splat` / `.spz` / SuperSplat | reference py/JS loaders → **captured test vectors** | MIT |
| HDF5, hloc layout | **h5py** (BSD) + **hloc** (Apache) | BSD/Apache |
| LAS / LAZ | **laspy** + `lazrs` | BSD/Apache |
| npy / npz | **numpy** | BSD |
| PFM, 16-bit depth PNG, `.flo` | **imageio** + manual scale | BSD |
| PNG / JPEG / TIFF / WebP | **Pillow** / imageio | HPND/BSD |
| OpenEXR (+ deep, AOVs) | **OpenImageIO** / OpenEXR-python | BSD |
| `transforms.json` poses | stdlib `json` + manual 4×4 | — |
| glTF/GLB, OBJ, STL, OFF | **trimesh** / **pygltflib** | MIT |
| safetensors | **safetensors** | Apache |
| Parquet / Arrow | **pyarrow** | Apache |
| USD/USDZ | **usd-core (pxr)** | Apache |
| OpenVDB | **openvdb** python | Apache |
| Zarr | **zarr** | MIT |

**Fixtures:** tiny files, either permissively licensed or **generated by
the oracle** at test time (no NC data bundled — see survey §8); **golden
byte-exact** blobs for our writers, regenerated by a documented script.

---

## 7. Phased roadmap

Ordered by value × cost; each phase ships codecs + their oracle tests +
docs, and closes with "all parity green."

- **Phase 0 — scaffold.** scikit-build-core + nanobind build; `abi3` wheel
  in CI (cibuildwheel); a numpy+torch **zero-copy round-trip** proof on one
  toy array; the `assert_codec_parity` harness; **one trivial format
  end-to-end** (`.npy` or PFM) as the reference codec pattern.
- **Phase 1 — Tier-1 spine, zero external deps.** COLMAP `.bin`/`.txt` +
  camera models, PLY, `.npy`/`.npz`, PFM, PPM/PGM, `transforms.json`,
  TUM/KITTI/g2o text. Oracles: pycolmap, plyfile, numpy, imageio. *(Also:
  wire the `Reconstruction`/`FeatureSet` Records to the existing
  `sparse_model`/`feature_set` DataTypes.)*
- **Phase 2 — 3DGS splat → unblocks the `splat` DataType.** 3DGS `.ply`,
  `.splat`, `.spz` (zstd/zlib), SuperSplat compressed `.ply`. Register the
  new `splat` DataType + its formats; record activation/axis conventions.
- **Phase 3 — arrays / features (first C libs).** HDF5 + **hloc layout**,
  COLMAP DB (sqlite), safetensors. Oracles: h5py, hloc, pycolmap, safetensors.
- **Phase 4 — images / HDR / depth.** PNG/JPEG/TIFF/WebP + **OpenEXR** +
  16-bit-PNG/PFM/EXR depth (with the `dense`/`depth_map` DataType + scale
  metadata). Oracles: Pillow, imageio, OpenImageIO.
- **Phase 5 — point clouds.** PCD, LAS/LAZ (laszip/lazrs). Oracles: open3d,
  laspy.
- **Phase 6 — meshes + niche.** glTF/GLB (+Draco), OBJ/STL/OFF, USD/USDZ,
  OpenVDB, Zarr, Parquet, AVIF/JPEG-XL, PlayCanvas SOG. Oracles per matrix.
- **Phase 7 — hardening.** Differential fuzzing at scale; big-file
  mmap/streaming; GPU-via-DLPack validation (torch-cuda/cupy); **benchmarks
  vs oracles** (target: ≥ parity libs on decode throughput, big wins on the
  binary formats); memory/leak/ASan runs.

---

## 8. CI & release implications

Making `sceneio` a **compiled** package changes the sibling-checkout story
the core CI just adopted (`../SceneIO` editable install):

- Core CI must now **build** the extension (add a C++ toolchain + the
  optional C libs to the CI image) **or** install a **prebuilt wheel**
  instead of editable-source. With **no fallback** (D1/D2), there is no
  contract-only degraded path — the wheel/build is required wherever sceneio
  is imported. **Sequencing matters:** publish `sceneio` wheels (or add the
  toolchain to the family's sibling-checkout CI) **before** the compiled-only
  change lands, so the family's currently-green CI does not break.
- New CI: a **cibuildwheel** matrix producing `abi3` wheels, published to the
  **`sceneio`** PyPI project (already reserved — see the family publish plan).
- The compat lane (bundles vs core+io HEAD) keeps working if bundles install
  the wheel; if they build from source they inherit the toolchain need.

---

## 9. Risks & decisions for you (D1–D5)

| # | Decision | Resolution |
|---|---|---|
| **D1** | Package topology | **DECIDED: compiled-only `sceneio`.** The `_core` extension is mandatory; no separate accelerator dist. One code path per format for parity; every install/CI needs a compiler or a wheel |
| **D2** | Pure-Python fallback | **DECIDED: none** (follows D1). Single implementation per format — the parity suite cannot diverge across a fast/slow path |
| **D3** | In-memory ownership | **C++-owned Record + zero-copy views** (Python protocols still describe them) — best perf + true zero-copy |
| **D4** | torch coupling | **Optional DLPack** — `torch.from_dlpack`, any recent torch, zero build/runtime cost |
| **D5** | Big-file strategy | **Defer to Phase 7** for most; mmap the COLMAP/LAS readers early where it's cheap |

**Other risks:** OpenEXR/HDF5/USD are heavyweight C++ deps (keep them
optional, feature-flagged); Windows arm64 wheel coverage; keeping the
`abi3` discipline (no unstable CPython API); ensuring the fallback and the
C++ path pass the *same* parity suite so they can't diverge.

---

*Companion to `docs/formats_survey.md`. The format list, licenses, and
per-format conventions/caveats referenced above come from that survey.*
