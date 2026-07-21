# SceneIO format survey — 3DGS · SfM · spatial AI

A survey of the data representations and file formats relevant to
SceneIO — the numpy-native I/O + contract-plane package for the SceneAPI
family — **filtered to a permissive, non-messy set** we can actually ship
(MIT / BSD / Apache-family or self-implementable; see §1).

Every row records **source · format-spec license vs reference-impl
license · copyright/steward · citation · payload · SceneIO relevance &
caveats**, verified against primary sources; unconfirmed items are marked
**⚠ verify**. **Not legal advice.**

---

## 1. Scope & license policy (what stays, what's cut)

**The load-bearing principle: data ≠ code.** SceneIO ships its *own*
numpy readers/writers (as it already does for `points_binary`), or depends
only on permissively-licensed libraries. It **never vendors the originating
engine**. So a format is *safe to support* when **SceneIO's implementation
path is permissive** — independent of the license of the research engine
that popularized it.

- ✅ **Allow-list** (SceneIO's dependency or self-implementation must be one
  of): **MIT, BSD-2/3-Clause, Apache-2.0, ISC, Zlib, Boost (BSL-1.0),
  public-domain / CC0** — or SceneIO writes the codec itself from a
  documented, patent-free format.
- ❌ **Cut — SceneIO would have to depend on something unsafe**: GPL / LGPL /
  AGPL (this is why **FFmpeg is out**), non-commercial / research-only code,
  or a proprietary SDK / EULA.
- ❌ **Cut — patent-encumbered** (esp. video): H.264/AVC, H.265/HEVC, HEIC,
  ProRes-encode.
- ❌ **Cut — "messy"**: proprietary undocumented binaries, paywalled specs,
  or no schema at all.

**Why 3DGS `.ply` and COLMAP survive despite NC/BSD engines:** the *format*
PLY is public-domain and COLMAP is BSD; SceneIO reads/writes both with its
own code. The INRIA 3DGS and NVIDIA instant-ngp **non-commercial** terms
bind only *their training code and pretrained weights* — which SceneIO does
not distribute. Interop is safe; vendoring their engines would not be.

**Video policy:** SceneIO's canonical moving-image input is an **image
sequence** (numbered PNG/JPEG/EXR — the COLMAP/nerfstudio convention).
SceneIO bundles **no video decoder**: no FFmpeg, no patented codecs. If a
project must decode video, it does so upstream and hands SceneIO the frames.
(Royalty-free AV1 / VP8-VP9 have permissive decoders — dav1d / libvpx, BSD —
and MJPEG is just JPEG frames; these are noted, not bundled.)

See §8 for the full **Excluded (and why)** list.

---

## 2. What SceneIO supports today (baseline)

SceneIO currently ships **only its own portable interchange formats** — it
ingests no external standards yet. That is the gap this survey fills.

- **Architecture:** `sceneio.formats` separates the **DataType** (noun:
  `image_sequence`, `camera`, `feature_set`, `match_graph`, `sparse_model`,
  `projection`, …) from the **Format** (serialization). "One type, many
  formats." `dense_model` and `splat` DataTypes are **deferred until a
  producer + format exists** — so 3DGS format support is what unblocks them.
- **Formats today:** the `sfmapi.*.v1` family (features, pairs, matches,
  reconstruction, projection), the `points_binary` codec
  (`application/x-sfm-points-v1`), the COLMAP SQLite schema contract, the
  `PCMAPIN` mapping-input/resume format, and numpy-native `data.*` types.

Each external format below slots in as a new `FormatSpec` + reader/writer
mapped onto a DataType.

---

## 3. SfM / MVS bundles + camera / pose / calibration (safe set)

All rows are self-implementable by SceneIO (documented, patent-free) or use
a permissive lib; the *pose/quaternion/axis conventions* are the real work.

| Format / spec | Ext(s) | Origin | Impl path (license) | Copyright / steward | Citation | Carries (payload) | SceneIO relevance & caveats |
|---|---|---|---|---|---|---|---|
| **COLMAP sparse model (binary)** | `.bin` | COLMAP (ETH Zürich / UNC) | own numpy codec; pycolmap **New BSD** | ETH Zürich & UNC; Schönberger | colmap.github.io/format.html ; Schönberger & Frahm, CVPR 2016 | little-endian packed cameras, images `(qw,qx,qy,qz,tx,ty,tz)`, points3D+RGB+tracks | **The essential target.** Quaternion **WXYZ**, pose **world→camera**, cam center = −Rᵀt |
| **COLMAP sparse model (text)** | `.txt` | COLMAP | own codec; **New BSD** | ETH Zürich & UNC | colmap.github.io/format.html | same payload, human-readable | Slower/larger than `.bin`; identical semantics |
| **COLMAP database** | `database.db` | COLMAP | SQLite (**public domain**) + own BLOB decode | ETH Zürich & UNC | colmap.github.io/database.html | tables: cameras, images, keypoints (`f32`), descriptors (`u8`), matches (`u32`), two_view_geometries (F/E/H `f64`) | Reuse features/matches without re-detection. BLOBs row-major LE; `pair_id = id1*2147483647 + id2` |
| **COLMAP camera models** | (within above) | COLMAP | own codec; **New BSD** | ETH Zürich & UNC | colmap.github.io/cameras.html | SIMPLE_PINHOLE, PINHOLE, SIMPLE_RADIAL(_FISHEYE), RADIAL, OPENCV, OPENCV_FISHEYE, FULL_OPENCV, FOV, THIN_PRISM_FISHEYE | each = ordered `params[]`; contract must carry the model id. Superset of OpenCV distortion |
| **Kapture** | `.txt`/`.csv` set + dirs | NAVER Labs Europe | own reader; kapture **BSD-3** | NAVER Corp | arXiv:2007.13867 ; github.com/naver/kapture | unified: sensors/rigs, trajectories, records, keypoints/descriptors/global-features, matches, 3D points+observations | **Closest existing analog to SceneIO's contract-plane goal** — strong reference model (BSD-3, directory-of-tables) |
| **TUM RGB-D trajectory** | `.txt` | TU München CVG | own parser; eval tools **BSD-2** | TUM CVG; Sturm et al. | Sturm et al., IROS 2012 | `timestamp tx ty tz qx qy qz qw` | De-facto for evo/ATE/RPE. Pose **camera→world**, quaternion **XYZW**, seconds, `#` comments |
| **KITTI odometry poses** | `.txt` | KIT & TTI-Chicago | own parser (trivial text) | Geiger et al. | cvlibs.net/datasets/kitti ; Geiger et al., CVPR 2012 | 12 floats = row-major 3×4 `[R\|t]`, cam i rel. frame 0 | Format is safe to read; the **KITTI data is CC-BY-NC-SA** (don't bundle it, §8). Cam→world; no timestamps in `poses.txt` |
| **EuRoC MAV ground truth** | `.csv` + `.yaml` | ETH Zürich ASL | own parser | Burri et al. | DOI 10.1177/0278364915620033 (IJRR 2016) | GT csv `t[ns], p, q(w,x,y,z), v, b_w, b_a`; `sensor.yaml` `T_BS` | GT in **body/IMU frame** — needs `T_BS` for camera pose. Quaternion **WXYZ**, ns |
| **g2o graph** | `.g2o` | Kümmerle et al. (Freiburg) | own text parser; g2o core **BSD-3** | Kümmerle, Grisetti et al. | github.com/RainerKuemmerle/g2o wiki ; ICRA 2011 | `VERTEX_SE3:QUAT`, `EDGE_SE3:QUAT` + info matrices | Pose-**graph** exchange (not a scene container). Quaternion **XYZW**; `g2o_viewer` is GPL — not needed |
| **OpenCV calibration (FileStorage)** | `.yml` `.xml` `.json` | OpenCV | own FileStorage parser; OpenCV 4.x **Apache-2.0** | OpenCV Foundation | docs.opencv.org (FileStorage) | `camera_matrix` K, `distortion_coefficients` (k1 k2 p1 p2 k3…), stereo R/T/E/F | OpenCV's `!!opencv-matrix` nodes aren't plain YAML — needs a small custom reader. Ubiquitous intrinsics carrier |
| **transforms.json (instant-ngp / nerfstudio)** | `.json` | NeRF → instant-ngp → nerfstudio | own JSON reader; nerfstudio **Apache-2.0** | NeRF authors / NVIDIA / nerfstudio | Mildenhall et al., ECCV 2020, arXiv 2003.08934 | intrinsics + per-frame `file_path` + 4×4 `transform_matrix` (**camera→world, OpenGL/Blender +Y up, −Z fwd**) | Central pose interchange. **#1 interop bug:** OpenGL/Blender vs OpenCV/COLMAP axes + c2w vs w2c; nerfstudio also reorients/auto-scales |

> **Also readable via own JSON parser if ever needed** (engine is **MPL-2.0**,
> not mit/bsd/apache, so not bundled by default): **OpenMVG** `sfm_data.json`
> and **Meshroom/AliceVision** `.sfm` — both clean JSON, OpenMVG-lineage
> schema. Their `.bin`/`.abc` variants need the engines → out.

**Uncertainties (§3):** EuRoC data CC version ⚠; OpenCV FileStorage `!!opencv-matrix` needs custom handling; g2o quaternion is XYZW vs COLMAP WXYZ (convert explicitly).

---

## 4. 3D Gaussian Splatting / NeRF / radiance fields (safe set)

The formats here are public-domain/MIT and self-implementable. **Supporting
the 3DGS PLY schema unblocks SceneIO's deferred `splat` DataType.**

| Format / spec | Ext(s) | Origin | Impl path (license) | Copyright / steward | Citation | Carries (payload) | SceneIO relevance & caveats |
|---|---|---|---|---|---|---|---|
| **3DGS Gaussian PLY** | `.ply` | INRIA GraphDeco (reference 3DGS) | own numpy codec (PLY **public-domain**) | Inria + MPI Informatik | Kerbl et al., ACM TOG 42(4) 2023; arXiv 2308.04079 | per-Gaussian: xyz, `f_dc_0..2` (SH DC=color), `f_rest_0..44` (SH≤3), opacity, `scale_0..2`, `rot_0..3` (quat); f32; activations at load (exp scale, sigmoid opacity, normalize quat) | **Unblocks the `splat` DataType.** Reading/writing is unencumbered; do **not** vendor INRIA's NC training code/weights. Record activation conventions in the contract |
| **`.splat`** | `.splat` | antimatter15 (Kevin Kwok) | own codec; ref **MIT** | Kevin Kwok | github.com/antimatter15/splat | 32 B/Gaussian: pos 3×f32, scale 3×f32, color RGBA 4×u8, rot quat 4×u8; **no SH** | Fixed-stride → single numpy structured dtype, near-zero-copy. Lossy (8-bit, SH dropped). Great compact interchange |
| **`.spz` (SPlat-Zip)** | `.spz` | Niantic Labs / Scaniverse | own codec + gzip/zstd; ref **MIT** | Niantic Labs | github.com/nianticlabs/spz | compressed; magic "NGSP"; pos 24-bit fixed, scales 8-bit log, rot ~10-bit, color/SH 8-bit; ~10× smaller than PLY | Decompress → destructure to numpy; lossy. **Version drift v1→v4** (gzip→zstd) — branch on header. Axis differs from INRIA PLY |
| **SuperSplat compressed PLY** | `.ply` `.compressed.ply` | PlayCanvas SuperSplat | own PLY codec; ref **MIT** | PlayCanvas | github.com/playcanvas/supersplat | PLY with `chunk` element (per-256 min/max) + packed `vertex` (pos 11/10/11-bit, quat, scale, color); optional SH | Still a PLY → numpy read, de-quantize per chunk. Very common editor output; document chunking for exact round-trips |
| **PlayCanvas SOG / "SOGS"** | `meta.json` + `.webp` | PlayCanvas (Snap Inc.) | own reader + WebP (libwebp **BSD-3**); ref **MIT** | PlayCanvas | developer.playcanvas.com/…/formats/sog | meta.json + WebP: pos 16-bit over 2 imgs (log), quat ~26-bit, scales/colors via codebooks, optional SH palettes; Morton-ordered | Strong **web-delivery emit target**. Naming trap: distinct from Fraunhofer SOG. Codebooks lossy but reversible |
| **`.ksplat`** | `.ksplat` | mkkellogg GaussianSplats3D | own reader; ref **MIT** | Mark Kellogg | github.com/mkkellogg/GaussianSplats3D | section+bucket layout; pos/scale/color/rot + optional SH; levels 0/1/2 = f32/16-bit/8-bit | Small custom reader → numpy after de-bucketing. **Repo archived** — pin the version. Niche |

> **Poses for NeRF/3DGS training data** use `transforms.json` — see §3.
> **Consumer apps** (Luma / Polycam / KIRI) export these same open formats;
> there's no format barrier, but check each asset's *terms of service*
> (some are personal/NC or watermarked) before redistributing the data.

**Cut from this domain (see §8):** instant-ngp `.ingp` (NVIDIA NC engine + brittle schema); nerfstudio `.ckpt`/`.pt` (**pickle = code-execution risk** — use the `.ply` export instead); Fraunhofer SOG (training derives from INRIA NC); PlenOctree/MERF/SMERF (niche/historical).

**Uncertainties (§4):** `.spz` bit-widths shifted v1→v4 (current v4 shown); `.ksplat` layout from an archived repo; 3DGS DOI from secondary index (arXiv + repo firm); `transforms.json` has no normative spec.

---

## 5. Point clouds · meshes (safe set)

| Format / spec | Ext(s) | Origin | Impl path (license) | Copyright / steward | Citation | Carries | SceneIO relevance & caveats |
|---|---|---|---|---|---|---|---|
| **PLY** | `.ply` | Greg Turk / Stanford | own numpy codec (**public-domain**); tinyply/happly **MIT** | Greg Turk (de-facto) | paulbourke.net/dataformats/ply | verts, faces, normals, colors, **arbitrary typed props**; ASCII + binary LE/BE | **The base container** (also the 3DGS splat carrier). Binary → numpy structured dtype. Handle endianness + property order |
| **PCD** | `.pcd` | Point Cloud Library | PCL **BSD-3**; own reader trivial | Willow Garage / Open Perception | pointclouds.org/…/pcd_file_format.html | x/y/z, normals, RGB, intensity, arbitrary `FIELDS`; organized (W×H) | Native ROS/robotics cloud; binary numpy-mappable. RGB packed as bit-cast float; `binary_compressed` = LZF |
| **LAS** | `.las` | ASPRS | laspy **BSD-2**; spec ASPRS royalty-free | ASPRS | github.com/ASPRSorg/LAS | scaled-int32 x/y/z, intensity, returns, classification, GPS time, RGB, waveform | Canonical lidar. **Integer scale+offset (not float)**, needs CRS handling |
| **LAZ** | `.laz` | rapidlasso / M. Isenburg | **lazrs (Apache-2.0/MIT)** or LASzip **Apache-2.0** | rapidlasso GmbH | laszip.org ; PE&RS 79(2):209–217 | LAS payload, losslessly compressed to 7–20% | Use the current **Apache** LASzip / lazrs backend (older embedded LASzip was LGPL — pin the version) |
| **OBJ (+ MTL)** | `.obj` `.mtl` | Wavefront | tinyobjloader **MIT** | de-facto public | paulbourke.net/dataformats/obj | mesh (v/vt/vn, faces), groups; MTL: Kd/Ks + texture maps | Ubiquitous human-readable mesh. 1-indexed, no transforms/units; sidecar MTL + textures |
| **glTF 2.0 / GLB** | `.gltf` `.glb` | Khronos | cgltf / tinygltf **MIT**; spec CC-BY-4.0 | Khronos Group | registry.khronos.org/glTF/specs/2.0 ; ISO/IEC 12113:2022 | scene graph, meshes, **PBR materials**, textures, skins/animation, cameras; binary buffers | Modern runtime/web/AR delivery; GLB bufferViews map cleanly to numpy. y-up/right-handed; delivery (not authoring) |
| **Draco** | `.drc` / in glTF | Google | **Apache-2.0** | Google | github.com/google/draco | compressed mesh **or point clouds** (quantized) | Optional glTF geometry compression (~10×). **Lossy quantization** — not for exact reproduction |
| **USD / USDZ** (OpenUSD) | `.usd` `.usdc` `.usdz` | Pixar / AOUSD | OpenUSD **modified Apache-2.0** (altered Trademarks §); tinyusdz **Apache-2.0/MIT** | Pixar / Alliance for OpenUSD | openusd.org | scene graph + composition, geometry, materials, cameras, lights, volumes | Emerging spatial/AR + **NVIDIA Omniverse** standard. usdz = 64-byte-aligned uncompressed zip (mmap). Caveat: full OpenUSD is a heavy C++ dep (modified-Apache trademark clause) |
| **OpenVDB / NanoVDB** | `.vdb` `.nvdb` | DreamWorks / ASWF | **Apache-2.0** (since v12.0, 2024) | DreamWorks / ASWF | Museth 2013, ACM TOG 32(3), DOI 10.1145/2487228.2487235 | sparse volumetric grids — density, **SDF/level sets**, VDB Points; NanoVDB = GPU grid | Volumetric/SDF + neural-field export; NanoVDB for CUDA. Use **v12+** (older files were MPL-2.0). Niche |
| **STL** | `.stl` | 3D Systems | numpy-stl **BSD** | de-facto public | LOC FDD fdd000504 | **triangle soup** — per-facet normal + 3 verts | Universal 3D-print mesh. No shared verts / topology / units. Niche for SfM/3DGS |
| **OFF** | `.off` | Geomview (NSF Geometry Center) | trimesh **MIT**; own reader trivial | de-facto public | geomview.org/docs/html/OFF.html | verts + polygon faces, optional color/normals | Common in ML shape datasets (ModelNet). Minimal — no materials. Niche |

**Uncertainties (§5):** LASzip DOI digits ⚠; USD is *modified* Apache-2.0 (trademark clause); OpenVDB Apache only from v12.0.

---

## 6. Images · HDR · depth (safe set); video = image sequences

**Stills / HDR** — all have permissive impls (libjpeg-turbo, libpng, libtiff,
libwebp, OpenEXR, libjxl — MIT/BSD/Apache-family) or are trivially
self-implementable.

| Format | Ext(s) | Origin | Impl path (license) | Steward | Citation | Carries | SceneIO relevance & caveats |
|---|---|---|---|---|---|---|---|
| **JPEG** | `.jpg` `.jpeg` | JPEG (ISO/ITU) | libjpeg-turbo (BSD-3 + IJG + zlib) | JPEG committee | ISO/IEC 10918-1; ITU-T T.81 | 8-bit YCbCr/RGB, lossy DCT, EXIF/ICC | Primary photographic capture. **Lossy → never for depth/masks.** Honor EXIF orientation |
| **PNG** | `.png` | W3C / libpng | libpng (permissive, MIT/BSD-like) | W3C / libpng | W3C REC-png-3 (2025); ISO/IEC 15948 | 1–16-bit gray/RGB(A), lossless | Lossless capture, alpha masks, **de-facto 16-bit depth container**. Samples big-endian in-file |
| **TIFF / BigTIFF** | `.tif` `.tiff` | Adobe / libtiff | libtiff (permissive) | Adobe / libtiff | Adobe TIFF Rev 6.0 | arbitrary int/**float** bit-depth, tiled, multi-page; BigTIFF >4 GB | 16-bit/32-float scientific rasters, ortho tiles. Tag-based → check endianness |
| **GeoTIFF** | `.tif` | OGC / libgeotiff | libgeotiff **X/MIT** + GDAL **MIT** | OGC | OGC 19-008r4 (GeoTIFF 1.1) | TIFF + georef tags (CRS, affine) | Georeferenced ortho/DSM **outputs** of drone/aerial SfM. Niche |
| **WebP** | `.webp` | Google | libwebp **BSD-3** | Google | RFC 9649 (2024) | lossy (8-bit YUV420) / lossless (8-bit RGBA), alpha | Common in web datasets + PlayCanvas SOG. Lossy subsamples chroma; **8-bit only** |
| **OpenEXR** | `.exr` | ILM → ASWF | OpenEXR + Imath **BSD-3** | ASWF | openexr.com | 16/32-bit **float**, arbitrary named channels, tiled/multi-part, **DEEP** samples | **Standard for HDR scene-linear + GT depth/normal/albedo AOVs.** Deep EXR for occlusion-aware supervision |
| **Radiance HDR** | `.hdr` | Greg Ward (LBNL) | own codec (rgbe.c free); LBNL permissive | LBNL / Ward | Ward, Graphics Gems II (1991) | RGBE 32-bpp shared-exponent HDR | Legacy HDR environment maps / IBL. Lower precision than EXR. Niche |
| **AVIF** | `.avif` | Alliance for Open Media | libavif **BSD-2** + dav1d **BSD** (AV1 = royalty-free) | AOM | AVIF v1.2.0 (2025) | AV1 still, up to 12-bit, alpha, HDR, aux depth | **Royalty-free, permissive impl** — a clean modern still format. Niche (growing) |
| **JPEG XL** | `.jxl` | JPEG + Google | libjxl **BSD-3** (royalty-free) | JPEG committee | ISO/IEC 18181-1:2022 | lossy/lossless, up to 32-bit float, HDR, alpha | Promising for HDR + high bit depth + lossless. **Tooling still thin (2026)**. Niche |
| **netpbm (PPM/PGM/PBM/PAM)** | `.ppm` `.pgm` `.pbm` | Netpbm | own codec (**public-domain**) | Netpbm project | netpbm.sourceforge.net | 8/16-bit gray, RGB, 1-bit, PAM | **Dead-simple numpy read/write, zero deps** → debug/intermediate. Big-endian samples |
| **BMP** | `.bmp` | Microsoft | own codec (trivial) | Microsoft | Windows BMP/DIB | 1–32-bit RGB(A), uncompressed / RLE | Simple debug exchange. Rows bottom-up, BGR, 4-byte padded. Niche |

**Depth / geometry-image conventions** (over the codecs above)

| Convention | Ext | Origin | License | Citation | Carries | SceneIO relevance & caveats |
|---|---|---|---|---|---|---|
| **16-bit PNG depth (TUM / ScanNet)** | `.png` | TUM RGB-D / ScanNet / Redwood | dataset convention (own codec) | cvg.cit.tum.de/…/file_formats | uint16 depth; **TUM scale=5000** (m), **ScanNet/Azure=1000** (mm); **0=invalid** | **THE RGB-D depth container.** CAVEAT: **scale factor is NOT in the file** → SceneIO must carry it in metadata. 16-bit caps range |
| **PFM depth / disparity** | `.pfm` | Middlebury / ETH3D / Sintel | informal (own codec) | vision.middlebury.edu/stereo | 32-bit float depth **or disparity**; inf/nan=invalid | Full-float GT, no scale ambiguity. **Rows bottom-up**; disparity-vs-depth semantics tracked in the contract |
| **EXR depth** | `.exr` | renderer AOV convention | BSD-3 (OpenEXR) | openexr.com | float Z channel, optionally **deep** | Standard synthetic depth GT; co-packs with normals/flow. Deep EXR → per-sample depth |
| **Optical flow `.flo`** | `.flo` | Middlebury flow (Baker et al.) | informal (own codec) | vision.middlebury.edu/flow | 2-ch float32 (u,v), LE, tag "PIEH" | Per-pixel float motion field. Not depth; sentinel >1e9 = unknown. Niche |

**Video / moving images** — **no FFmpeg, no patented codecs.**

| What | Status | Notes |
|---|---|---|
| **Image sequence** (`frame_%06d.png/.jpg/.exr`) | ✅ **canonical input** | THE SfM/3DGS input (COLMAP/glomap/nerfstudio consume image folders). Lossless PNG/EXR sequences preserve quality. SceneIO enumerates + orders; watch zero-padding + per-frame pose association |
| **MJPEG** | ➖ degenerate case | A stream of independent JPEG frames (libjpeg-turbo, permissive, no patents) — decodable without FFmpeg if ever needed |
| AV1 / VP8-VP9 (in WebM/MKV) | ➖ noted, not bundled | Royalty-free; permissive decoders exist (**dav1d / libvpx, BSD**). SceneIO still recommends extracting frames upstream rather than bundling a decoder |
| **H.264 / H.265 / HEIC / ProRes / MP4 / MOV / AVI** | ❌ **out** | Patent pools (Via LA / Access Advance) and/or decode paths that mean FFmpeg. Extract frames upstream and feed SceneIO an image sequence |

**Uncertainties (§6):** libjpeg-turbo is a composite license (IJG + BSD-3 + zlib); AVIF v1.2.0 clause-level not re-checked; BMP/netpbm/PFM/.flo have no standards steward (self-implement).

---

## 7. Arrays · features · databases · serialization (safe set)

The store for learned features, matches, tensors, and metadata. All
permissive (HDF5 BSD, Zarr MIT, Arrow/Parquet Apache, SQLite public-domain,
numpy BSD, safetensors Apache) or self-implementable.

| Format / spec | Ext(s) | Origin | Impl path (license) | Steward | Citation | Carries | SceneIO relevance & caveats |
|---|---|---|---|---|---|---|---|
| **HDF5** | `.h5` `.hdf5` | The HDF Group | libhdf5 / h5py **BSD-3** | The HDF Group | docs.hdfgroup.org | hierarchical groups/datasets: chunked+compressed n-D arrays, attributes | **THE store hloc uses for features & matches.** Caveat: no safe concurrent multi-writer (SWMR = 1 writer/N readers); heavy dep |
| **hloc HDF5 layout** | `.h5` | cvg / hloc (Sarlin) | own reader over h5py; hloc **Apache-2.0** | ETH Zurich CVG | github.com/cvg/Hierarchical-Localization ; CVPR 2019 | per-image group → `keypoints` [N×2 f32], `descriptors` [D×N f32], `scores`, `image_size`; matches keyed `p0-p1` → `matches0` [N, index/−1] | **De-facto layout for learned features (SuperPoint) & matches (LightGlue).** Descriptors **D×N** (transposed vs COLMAP N×D); key mangles `/`→`-`; export to COLMAP DB to reconstruct |
| **NumPy `.npy`/`.npz`** | `.npy` `.npz` | NumPy | numpy **BSD-3** | NumPy / NumFOCUS | numpy.org/…/lib.format | `.npy`=one dtyped n-D array; `.npz`=zip of many | **Lingua franca for arrays/features/embeddings.** Caveat: `allow_pickle=True` executes code (default False now); `.npz` random access poor |
| **safetensors** | `.safetensors` | Hugging Face | **Apache-2.0** | Hugging Face | github.com/huggingface/safetensors | JSON header (`dtype`,`shape`,`data_offsets`) + raw contiguous tensor bytes; zero-copy/mmap | **Safe** (no code exec, unlike pickle/`.pt`), zero-copy weights/embeddings/features. Flat metadata; tensors only |
| **Zarr** | `.zarr` (store) | Zarr Developers | zarr-python **MIT** | Zarr / NumFOCUS | zarr-specs.readthedocs.io | chunked, compressed n-D arrays; one file per chunk; object-store friendly | Cloud-native HDF5 alternative; concurrency-friendly. Many small objects unless sharded. Niche |
| **Apache Parquet** | `.parquet` | Apache | pyarrow **Apache-2.0** | Apache SF | github.com/apache/parquet-format | columnar tabular data, compressed, nested schemas | Scalable store for tabular metadata (poses, tracks, keypoint-attr tables). Columnar → poor single-row access |
| **Apache Arrow / Feather** | `.arrow` `.feather` | Apache Arrow | pyarrow **Apache-2.0** | Apache SF | arrow.apache.org/docs/format | zero-copy columnar; Feather = Arrow IPC file | Zero-copy feature tables (mmap). In-memory-oriented; less compression than Parquet |
| **SQLite (file format)** | `.db` `.sqlite` | SQLite team | **public domain** | SQLite | sqlite.org/fileformat2.html | embedded relational tables incl. opaque BLOBs | Substrate of COLMAP's `database.db`. Single-writer lock; BLOBs opaque (you own the encoding) |
| **JSON / JSON-Lines** | `.json` `.jsonl` | ECMA / IETF | stdlib **PSF** / MIT | Ecma / IETF | RFC 8259 ; ECMA-404 | text structured data; JSONL = one object/line | **Universal for config/metadata** — `transforms.json` poses. Bulky/lossy for big float arrays; no typed arrays |
| **TOML** | `.toml` | Tom Preston-Werner | tomllib **PSF** / tomli **MIT** | TOML community | toml.io/en/v1.0.0 | minimal typed config | Project/tool config (`pyproject.toml`). Config-only; awkward for large arrays |
| **Kapture features** | `.kpt` `.dsc` `.mch` | NAVER | kapture **BSD-3** | NAVER Corp | github.com/naver/kapture | typed binary keypoint/descriptor/match arrays + CSV sensors/poses | NAVER's unified format (also §3). Descriptor dtype metadata must match |

> **Deliberately handled with care, not blanket-banned:** **YAML** (config;
> `.yml`) is fine via PyYAML **`safe_load` only** — the default loader executes
> Python. **Pickle / torch `.pt` / `.ckpt`** are **not ingested**: unpickling
> untrusted data is arbitrary-code-execution — prefer safetensors / npz.

**Cut from this domain (see §8):** NetCDF (niche; HDF5 underneath), LMDB (OpenLDAP-PL, niche), Protobuf/FlatBuffers/TFRecord (schema-coupled, TF-centric), MessagePack/CBOR (weak numeric typing), Lowe `.key`/`.sift` (legacy, Lowe demo NC), Middlebury `.flo` lives in §6.

**Uncertainties (§7):** Zarr spec-doc license ⚠; HDF5 older releases use a custom BSD-style `HDF5` SPDX id (equivalent terms).

---

## 8. Datasets & benchmarks (incl. NVIDIA) — bundle-able vs reference-only

The **formats** these ship in are all in §3–§7 (COLMAP, PFM, HDF5, PLY,
glTF, `transforms.json`, 16-bit-PNG depth, headerless float32 LiDAR `.bin`).
The license question here is about the **data**: what SceneIO can ship as a
bundled test fixture vs. reference by URL. **Reader ≠ redistribution** — we
can support any of these formats; we only bundle data from the ✅ list.

**✅ Bundle-able (commercial-safe — CC-BY-4.0 / CC0):**

| Dataset | License | Formats it exercises | Citation |
|---|---|---|---|
| **TUM RGB-D** | CC-BY-4.0 | 16-bit PNG depth (÷5000), TUM traj `.txt` | Sturm et al., IROS 2012 |
| **BlendedMVS** | CC-BY-4.0 | JPG, PFM depth, MVSNet `_cam.txt`, `pair.txt` | arXiv:1911.10127 |
| **Google Scanned Objects** | CC-BY-4.0 | OBJ/MTL + PNG, Gazebo SDF | arXiv:2204.11918 |
| **OmniObject3D** | CC-BY-4.0 | OBJ/MTL, PLY, HDF5 point clouds, `transforms.json` | arXiv:2301.07525 |
| **MegaDepth** (depth layer) | CC-BY-4.0 (⚠ Flickr images per-photo) | HDF5 depth, COLMAP | arXiv:1804.00607 |
| **NVIDIA GSO / PhysicalAI** (CC-BY subsets) | CC-BY-4.0 (per-repo ⚠) | PNG/JSON, some USD | Cosmos arXiv:2501.03575 |
| **Objaverse** (CC-BY/CC0 subset only) | per-asset ⚠ filter on metadata `license` | glTF/GLB | arXiv:2212.08051 |

**⛔ Reference-only (NC / research-only / signed-TOS — link, do NOT bundle):**
- **Signed academic EULAs** (Matterport's even restricts *models trained on
  the data*): **ScanNet** (`.sens`), **ScanNet++**, **Matterport3D**
  (`.house`), **Habitat HM3D** (`.glb`+`.navmesh`), **Replica**.
- **Non-commercial CC / custom**: **KITTI** / **KITTI-360** (CC-BY-NC-SA,
  LiDAR `.bin`), **nuScenes** (CC-BY-NC-SA), **Waymo** (custom NC, TFRecord/
  proto), **ARKitScenes** (Apple-custom NC), **EuRoC** (InC-NC — *often
  mis-assumed permissive*), **7-Scenes** (MSR NC), **ETH3D** (CC-BY-NC-SA),
  **DL3DV-10K** (CC-BY-NC, gated), **CO3D** (CC-BY-NC), **Aachen** /
  **Cambridge Landmarks** (NC).
- **No clear / contradictory license → treat research-only**: **Mip-NeRF 360**,
  **DTU MVS**, **Tanks and Temples**.

**NVIDIA specifics:** NVIDIA's scene format is **OpenUSD** (§5, Apache-family)
— *not* NVIDIA-owned. Isaac Lab is BSD-3, Isaac Sim/Kaolin cores are
Apache-2.0, nvblox is Apache-2.0/BSD-3 (exports `.ply`), Cosmos weights are
commercial-OK under the NVIDIA Open Model License. But **Omniverse sample
assets, Kit SDK, and the `kaolin/non_commercial` module are NOT permissive**
— reference-only. PhysicalAI is per-sub-repo (only some CC-BY-4.0).

**Uncertainties (§8):** Mip-NeRF 360 / DTU / Tanks-and-Temples licenses unverified or self-contradictory (treat research-only); PhysicalAI varies per sub-repo; **EuRoC is InC-NC, not CC** (verified); **ARKitScenes is Apple-custom, not the CC-BY-NC-ND often cited** (verified from repo LICENSE); Objaverse ODC-By covers only metadata (per-asset filtering required).

---

## 9. Excluded — and why (the record, so we don't re-survey)

| Excluded | Domain | Reason |
|---|---|---|
| **Bundler `.out`** | SfM | GPL engine, legacy, superseded by COLMAP |
| **VisualSFM `.nvm`** | SfM | closed non-commercial freeware; legacy |
| **OpenMVS `.mvs`** | MVS | **AGPL** `Interface.h`; binary needs their code |
| **OpenMVG / Meshroom** (`.bin`/`.abc`) | SfM | **MPL-2.0** engines (JSON variants noted in §3 as own-parser-only) |
| **Theia**, **BAL** | SfM | no stable format / a BA benchmark, not a scene container |
| **Agisoft `.psx`/XML**, **RealityCapture** native | SfM | **proprietary**, undocumented / no redistributable impl |
| **TORO** | pose-graph | reference **code is CC-BY-NC**; superseded by g2o |
| **instant-ngp `.ingp`** | NeRF | **NVIDIA non-commercial** engine; brittle internal schema |
| **nerfstudio `.ckpt`/`.pt`** | 3DGS | **pickle = code-execution risk** — use the `.ply` export |
| **Fraunhofer SOG** | 3DGS | training derives from **INRIA NC** code |
| **PlenOctree / MERF / SMERF** | NeRF | niche / historical |
| **E57** | point cloud | **paywalled ASTM spec** (messy), niche |
| **XYZ / PTS / PTX** | point cloud | **no schema** (messy) — column/delimiter/locale ambiguity |
| **FBX** | mesh | **undocumented proprietary binary** (messy) |
| **COLLADA / 3MF / Alembic** | mesh | niche / heavy / out of the 3DGS-SfM domain |
| **nvblox / OctoMap** | voxel | robotics-specific; nvblox has no interchange format; OctoMap viewer is GPL |
| **DNG / camera RAW** | image | decode needs **LGPL LibRaw** / Adobe SDK; RAW is proprietary-undocumented |
| **HEIF / HEIC** | image | **HEVC patent-encumbered**; libheif is LGPL |
| **JPEG 2000 / TGA** | image | niche |
| **H.264 / H.265 / ProRes / MP4 / MOV / AVI** | video | **patent pools** and/or decode = **FFmpeg**; use image sequences |
| **NetCDF / LMDB / Protobuf / FlatBuffers / TFRecord / MessagePack / CBOR** | serialization | niche / schema-coupled / weak numeric typing for this domain |
| **Lowe `.key`/`.sift`** | features | legacy; Lowe demo non-commercial |

---

## 10. Recommended adoption plan for SceneIO

Every item below is self-implementable or uses a permissive lib, mapped to a
DataType. Order = value × cost.

**Tier 1 — essential (the SfM → 3DGS spine; build first)**

| Format(s) | DataType | Read/Write |
|---|---|---|
| **COLMAP `.bin`/`.txt` + camera models** | `sparse_model` | both |
| **Image folders (JPEG/PNG/EXR)** + enumeration/ordering | `image_sequence` | read |
| **3DGS `.ply`** — *unblocks the deferred `splat` DataType* | `splat` (new) | both |
| **16-bit PNG (TUM/ScanNet) · PFM · EXR** depth | `dense`/`depth_map` (new) | both |
| **hloc HDF5 layout + COLMAP DB** | `feature_set` / `match_graph` | both |
| **`transforms.json`** (explicit axis-convention handling) | `camera`/poses | both |
| **`.npy`/`.npz`** | (arrays, everywhere) | both |

**Tier 2 — common (broad interop)**
- Point clouds: **PLY, PCD, LAS/LAZ** (→ `point_cloud`/`dense`)
- Compact/web splats: **`.splat`, `.spz`, SuperSplat `.ply`**
- Meshes: **glTF/GLB** (+ optional Draco)
- Poses/calib: **TUM, KITTI, g2o, OpenCV FileStorage**
- Tensors/tables: **safetensors, Parquet/Arrow**
- HDR/GT: **OpenEXR** (deep, AOVs)

**Tier 3 — niche (as demand appears)**
- **USD/USDZ** (Omniverse / AR boundary — heavy dep), **OpenVDB** (volumes/SDF)
- **Zarr** (cloud arrays), **AVIF / JPEG-XL** (modern royalty-free stills)
- **OBJ / STL / OFF** (mesh/shape datasets), **Kapture** (unified VisLoc),
  **PlayCanvas SOG/SOGS** (web splats), **netpbm/PFM/BMP** (debug I/O)

**Non-goals (per the §1 policy):** video decode (image sequences only —
no FFmpeg, no patented codecs), FBX / Agisoft / RealityCapture (proprietary),
E57 / XYZ (paywalled/messy), pickle ingestion, and bundling any
non-commercial dataset.

---

*Survey conducted 2026-07-21 across six domains with per-format primary-source
license/citation verification. Filtered to a permissive (MIT/BSD/Apache-family
or self-implementable), non-messy set per the §1 policy. Items marked ⚠ verify
should be confirmed against the cited primary source before relying on them.*
