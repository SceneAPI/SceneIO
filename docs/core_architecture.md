# SceneIO core architecture (nanobind)

How the compiled core is organized and how to add a codec. Current format
capabilities are listed separately in
[`format_coverage.md`](format_coverage.md).

The R1-R6 organization and source/package closure are complete.
Optional-provider adapters remain isolated and preserve the
NumPy-only base import. Coordinate semantics are a checked cross-layer
contract; see [`coordinate_conventions.md`](coordinate_conventions.md).

<!-- sceneio-architecture-summary:start -->
**Generated ownership contract:** The **74** built-ins span **11** registry families:
**53** native, **4** hybrid, and **17** Python-owned rows. The compiled
`_core.__codec_inventory__` projection therefore contains **57** native/hybrid rows;
Python-owned rows remain outside that compiled inventory. The values come directly from
`FAMILY_MEMBERS` and `BUILTIN_OWNERSHIP`.
<!-- sceneio-architecture-summary:end -->

The dated R3-R6 paragraphs below preserve migration evidence for their named
commits. Their older codec, family, source, and test counts are historical,
not descriptions of the current registry.

> **Historical migration log:**
> R3.3 closes at `811cb0d` with normal run `30300122309` and
> compiler-instrumented run `30300122324` passing. The R3.4 installed-wheel
> smoke is now manifest-driven: it requires exact agreement among all 50
> built-in definitions, the installed registry, and the public codec list,
> then observes public write/read/inspect and every declared selector, while
> pairing each declared stream-capability direction with a successful
> corresponding public path call. Dedicated mmap and sink tests retain the
> independent allocation proof. The current property-specific exemption set
> is empty. The
> complete suite passes 3,344 tests with four documented skips, and the first
> exact-tree 380/381/81 source/sdist/wheel package gate passes.
>
> R4.1 closes at pushed commit `b2cf5d4` and leaves the root `CMakeLists.txt`
> as a four-include assembly over
> `SceneIOInstrumentation.cmake`, `SceneIOSources.cmake`,
> `SceneIODependencies.cmake`, and `SceneIOTargets.cmake`. The dependency
> block is byte-identical to the R3.4 parent, the original `_core` source/link
> order is frozen, and configure-time checks require every native codec and
> record source to have exactly one owner. R4.2 closes at pushed commit
> `81e0e1c`: a
> record table and eight codec-family tables preserve the exact 16-record and
> 40-codec registration order, and the same family descriptors expose a
> validated 49-entry native/hybrid inventory of read-only rows. An independent
> contract freezes each ordered operation tuple and requires callable symbols;
> source ownership checks are recursive and full-path exact for R4.3. The
> Python-owned `image_sequence` adapter remains outside that native projection.
> Normal run `30316577366` and compiler-instrumented run `30316577369` pass
> that exact commit. R4.3 and final R4 qualification close at pushed commit
> `da1d709`. All 40 native codec sources live under the eight family
> directories, and no flat codec source remains. Exact-tree MSVC/GCC 10,
> package, public-snapshot, normal CI `30326256230`, and instrumented
> `30326256137` gates pass.
>
> R5.1 adds a fifth, default-off
> `SceneIOBackendQualification.cmake` include after the stable dependency
> module. Ordinary builds still compile and link only the retained JPEG
> backend and preserve the 232-name core surface. A source-controlled internal
> default is separate from the explicit qualification override, so a later
> selection changes one default rather than redesigning the build. Explicit
> qualification builds select either stb or libjpeg-turbo 3.2.0 while
> traversing the same JPEG guards, records, bindings, mmap reader, and direct
> sink. `jpeg.cpp` now owns that common contract; `jpeg_stb.cpp` and
> qualification-only `src/cpp/qualification/jpeg_turbo.cpp` isolate backend
> mechanics. The candidate source is absent from ordinary target manifests.
> This is a comparison seam, not a selected-default change.
>
> R5.2 adds a repository-owned installed-wheel qualification layer under
> `bench/io_bench/backend_qualification/`. Its copied `-I` worker imports each
> wheel from a separate environment, prepares one hashed retained/independent
> corpus, exercises core buffer/mmap/sink and public path/sink surfaces, and
> emits raw paired samples plus correctness, output-size, startup,
> repeatability, allocation, RSS, and package evidence. The frozen matrix and
> thresholds live in `bench/BACKEND_QUALIFICATION.toml`. Candidate builds emit
> a receipt derived from libjpeg-turbo's generated SIMD header. The manual
> `.github/workflows/backend-qualification.yml` repeats the comparison on
> MSVC, manylinux2014 GCC 10, and AppleClang without publishing. This layer is
> evidence tooling only. The clean MSVC report rejected libjpeg-turbo 3.2.0
> as the combined default after its q95 comparative-quality result missed the
> frozen floor. stb remains stable, and no candidate advanced to a
> three-platform selection commit.

## Layering

```
sceneio (Python)                     public, stable surface
  read() / write() / inspect()       format-dispatched I/O + metadata-only probes
  read_partial()                     bounded format-specific selectors
  read_scene() / write_scene()       bounded rich USD-family SceneGraph API
  detect()
  io.registry                        one entry per format + optional inspect/partial hooks
  Reconstruction, GaussianCloud, …   re-exported record types
  errors                             C++ faults mapped to SceneIO exceptions
        │  (thin wrappers over)
sceneio._core (C++ / nanobind)
  records/     SoA in-memory types + zero-copy views + **convention metadata**
  codecs/      format-focused translation units: read_<fmt>() / write_<fmt>()
  bindings/    record + nine native codec-family tables and assembler
  io/          format-agnostic helpers: endian, byte reader/writer, gzip
  module.cpp   invokes the record pass, codec pass, then publishes inventory

cmake/
  SceneIOInstrumentation.cmake  opt-in compiler instrumentation
  SceneIOSources.cmake          bindings, records + nine native codec-family owners
  SceneIODependencies.cmake     Python/nanobind + native dependency targets
  SceneIOCameraModels.cmake     generated native lookup from Python authority
  SceneIOBackendQualification.cmake
                                internal defaults + default-off comparison
  SceneIOTargets.cmake          _core and native-control targets
```

**Separation of concerns**
- `src/sceneio/_camera_models.py` is the sole camera-model id/name/parameter
  authority. Python contracts and COLMAP adapters import its derived tables;
  CMake generates the native `colmap_model_info()` header from the same
  manifest before `_core` is defined.
- The package root owns the one public representation vocabulary. Private
  implementation modules and native storage records may differ internally,
  but codecs project directly into the root contracts rather than through a
  second public model layer.
- A **record** (e.g. `Reconstruction`, `GaussianCloud`) is a memory
  representation. It owns contiguous SoA buffers, hands out zero-copy
  ndarray views (numpy default; torch/cupy via DLPack), and **carries its
  conventions as machine-readable metadata** (quaternion order, pose
  direction, scale/opacity space) — never only in comments. A record is
  registered **once** and reused by every codec that produces it (SPZ and
  PLY both yield `GaussianCloud`).
- Static mesh scenes and rich 3D-CV stages share the `SceneGraph` record.
  `SceneGraph` owns node topology,
  transforms, typed payload references, visibility/purpose, stage
  axis/unit/time metadata, authored external dependency URIs, separate source
  locators used for transactional copying, and semantic labels.
  `InstanceSet` retains point-instancer prototype node identity, authored row
  order, ids, transforms, an explicit invisible mask, quaternion order, and
  numeric per-instance `TensorDict` attributes. `VolumeAsset` is a named
  external OpenVDB grid reference. Their numeric tables use owner-retaining,
  read-only ndarray views; nested payload access keeps the parent scene alive.
  The additive USD stage path maps hierarchy/metadata/static transforms,
  polygon meshes, point clouds, and the bounded PreviewSurface material/asset
  vocabulary. Repository-owned USDA/USDZ serializers stream numeric arrays and
  texture sources; direct-layer files and package-member locators remain
  separate from the authored portable URI. Schema mappings live in focused
  `gaussians.py`, `cameras.py`, `volumes.py`, `semantics.py`, and
  `instances.py` adapters. The state-B `animation.py` adapter structurally
  parses only provider-normalized direct-USDA matrix/visibility sample tables
  and materializes one selected static value; it owns no composition or
  animation-preservation model. Camera records use one unambiguous render-product
  resolution and an explicit local camera-to-parent/OpenGL pose. Volume
  records retain one direct scalar-float OpenVDB dependency without decoding
  it; semantics retain one effective inherited pair; and point instances
  retain shared prototype identity rather than expanded geometry.
- `PointCloud` keeps authored float display colors and opacities, point
  widths (diameters), signed 64-bit ids, velocities, accelerations, and
  display color-space metadata separate from its legacy quantized color
  fields. `Mesh` likewise keeps vertex/corner float display colors and
  opacities separate from RGBA8 and records orientation plus tri-state
  double-sidedness. Existing point and mesh writers refuse these additive
  fields until a format-specific mapping is implemented, so they cannot be
  dropped implicitly. Their ndarray accessors retain the owning record and
  follow the established writable-view behavior of `PointCloud` and `Mesh`.
- A **codec** is pure I/O for one format. Native buffer entry points accept a
  contiguous buffer-protocol view without first materializing Python
  `bytes`; public single-file reads normally keep a read-only mmap alive for
  the decode. Multi-file and directory containers use format-specific direct
  path adapters. Buffer writers remain available for parity tests, while
  public writes use native file sinks or container-specific path sinks. Native
  chunked encoders share one buffer-or-file accumulator in `io/common.hpp`, so
  sink ownership, GIL transitions, size checks, and empty streaming returns do
  not drift between codecs. A codec depends on `records/` and `io/`, never on
  another codec.
- The **Python `io` layer** is the UX and extensibility seam. The public
  `read()`, `write()`, `inspect()`, `read_partial()`, and `detect()`
  functions dispatch through `sceneio.io.registry`, which maps each format id
  to its detection rules, production reader/writer, canonical record,
  `payload_kind`, and optional inspection or selector hooks.
- Built-ins are declared once in `_builtin_manifest.py` and grouped by the
  eleven modules under `_registry/families/`. `_registry/assembly.py`
  validates the complete ordered candidate before publishing it atomically.
  Runtime registrations remain separate from that immutable built-in set and
  survive a successful registry reload.
- Metadata parsers live in the matching modules under `_inspectors/`.
  `_inspectors/model.py` owns `ArrayInspection` and `Inspection`, while
  `_inspectors/common.py` owns the small set of shared bounded parsing
  primitives. `_inspection.py` contains only the canonical format-to-inspector
  tables and dispatch validation; it does not mirror family functions through
  compatibility wrappers.
- Directory and multi-file codecs receive the live services they need through
  narrow objects such as `ImageFrameAccess`; lower family modules do not
  import the public registry or public I/O namespace. Optional-provider
  families keep imports lazy, so the base package remains NumPy-only.
- `bench/io_bench/runner.py` owns the benchmark CLI, sweep orchestration, and
  specialized glTF/COLMAP/image-directory cases. Family fixtures, oracles, and
  specifications live under their corresponding `bench/io_bench/`
  subpackages. `bench/bench_io.py` is only an import-and-call command-line
  shim and exports no compatibility helper surface.
- Cross-codec behavior fixtures are owned by `tests/_support/codec_cases.py`
  and its focused support modules. The mmap, sink, inspection, partial-read,
  installed-wheel, registry, and package tests consume those canonical
  fixtures rather than maintaining parallel builders.

## Stable codec ownership and backend selection

SceneIO owns the public adapter, grammar/subset, validation, record mapping,
convention guards, inspection, partial semantics, direct sink, normalized
errors, tests, benchmarks, and packaging for every stable codec. It does not
need to reimplement mature compression algorithms.

Use a popular optimized upstream kernel when production-path benchmarks prove
it is the best viable choice and it satisfies fidelity, deterministic output,
permissive licensing, static/offline buildability, cross-platform support,
maintenance, startup, and artifact-size requirements. Default stable kernels
must ultimately be pinned under `src/cpp/third_party/`, built into `_core`, and
  attributed in `LICENSES/`. Miniz 3.0.2, nlohmann/json 3.11.3, zstd 1.5.6,
  fast_float 6.1.6, LAZperf 3.4.0, and libwebp 1.5.0 are now
  repository-contained. The production CMake build has no native-source
  download step. The native build requires `Python::SABIModule` and fails
  configuration unless nanobind selects its stable-ABI target and suffix.
  Corrected local MSVC and Ubuntu builds produce `_core.pyd` and
  `_core.abi3.so`, respectively; the Windows binary imports `python3.dll` and
  the Unix binary has no libpython dependency. The exact-tree disconnected
  MSVC sdist-to-wheel build, package inventory, license gate, and all-74
  installed smoke form the final package gate. The release workflow
  makes every platform wheel consume that one verified sdist with hash-locked
  build inputs. Final run `30406706115` passes its MSVC, GCC 10, and AppleClang
  execution and downloaded-artifact inspection, closing R6. The R5 JPEG
candidate is
additionally built by a default-off external project from the official
libjpeg-turbo 3.2.0 archive. The clean MSVC qualification rejected that exact
candidate as the combined stable default after it missed the frozen q95
comparative-quality floor, so it does not enter ordinary builds or wheels and
stb remains the repository-owned default. Declared optional providers are
runtime delegates only for their named extras; qualification-only libraries
and executables remain test oracles and never enter normal runtime imports.

## Conventions are data, not comments

The survey's #1 bug class is silent convention mismatch. Every record
exposes them:
- `Reconstruction.quaternion_order == "wxyz"`,
  `.pose_convention == "world_to_camera"`; optional modern COLMAP rig/frame
  arrays preserve WXYZ `sensor_from_rig` and `rig_from_world` transforms,
  sensor/data assignments, and legacy-vs-modern file presence.
- `ColmapDatabase.rig_frames` owns database-only rig topology and frame data
  assignments. Its frames have no world pose. Nullable non-reference
  transforms use WXYZ `sensor_from_rig`; `ColmapDatabase.pose_priors`
  preserves image-linked or generalized associations, coordinate-system
  codes, and SQL BLOB presence. Logical covariance views are row-major even
  though the SQLite Eigen buffer is column-major.
- MAXX pose-prior rotations are XYZW `cam_from_world`. Rotation covariance is
  SO(3) tangent xyz in radians squared; 6x6 pose covariance orders rotation
  tangent xyz before translation xyz, with metre-squared translation and
  radian-metre cross terms.
- `FeatureSet` uses explicit presence for descriptor dtype/dimension/name,
  keypoint colors, and quality. `CorrespondenceGraph` preserves the distinction
  between raw and verified pairs, optional score rows, and source metadata;
  its private native storage retains unknown source-mask bits and zero-fills
  score slots only where the storage presence arrays mark them absent.
- `ColmapDatabase.markers` exposes optional position/covariance BLOB presence
  and top-left-origin pixel projections. `video_metadata` carries only SQLite
  metadata; nullable strings have presence arrays and source paths are never
  opened. `maxx_schema_info` is `None` outside an owned MAXX profile.
- `GaussianCloud` records quaternion order, scale/opacity activation space, SH
  layout, float16/float32 source precision, and the official USD Gaussian
  projection/sorting hints. Existing splat codecs default to
  WXYZ/log/logit/channel-grouped/float32 plus perspective/z-depth hints and
  refuse other conventions. `convert_gaussian_conventions()` performs an
  explicit numeric conversion and preserves the rendering hints; writers
  never activate, reorder, or discard values implicitly.
- `Mesh.coordinate_frame == "opengl"` for canonical glTF geometry;
  `SceneGraph` retains the source node hierarchy, local transforms, scenes, and
  mesh-to-primitive ranges instead of baking or flattening transforms.

## Adding a codec — current wiring recipe

This recipe describes the current manifest, family, binding, documentation,
and validation boundaries.

1. **Declare ownership** — add the built-in id, family,
   `implementation_owner`, native symbols, and Python adapter symbols to
   `sceneio/io/_builtin_manifest.py`. The immutable manifest is the
   repository-completeness scope; the mutable runtime registry remains the
   third-party extension seam.
2. **Record** — if the format needs a new in-memory type, add
   `records/<name>.hpp` (the SoA struct + conventions) and
   `records/<name>.cpp` (`register_<name>()` binding zero-copy views +
   convention properties). Reuse an existing record otherwise.
3. **Codec** — use `codecs/<family>/<fmt>.cpp`. Implement `read_<fmt>()` /
   `write_<fmt>()` over `records/` + `io/`, plus a `register_<fmt>()` that
   `m.def(...)`s them. Map malformed input to a thrown
   `std::invalid_argument`.
4. **Wire C++** — add the codec registration descriptor and native operation
   descriptor to `bindings/<family>.cpp`; do not edit `module.cpp`. Explicit
   ordinals preserve record-before-codec construction and canonical manifest
   order. Add the codec source to its exact
   `SCENEIO_<FAMILY>_CODEC_SOURCES` owner and preserved link-order list in
   `cmake/SceneIOSources.cmake`; configure and architecture tests reject
   missing, duplicate, or mismatched ownership. The private
   `_core.__codec_inventory__` must resolve the native/hybrid manifest
   projection exactly.
5. **Register adapters** — add one `Codec(...)` entry in its
   `sceneio/io/_registry/families/<family>.py` module. Declare extensions,
   detection signature, reader, writer, record, payload kind, container kind,
   stream flags, and optional inspection/partial hooks. Public reads and
   writes must exercise the production mmap/path/sink adapter rather than only
   the buffer seam.
6. **Inspect and select** — add the built-in parser and `inspect_path()`
   table entry, or provide `Codec.inspect`; add each supported
   `read_partial` selector and capability declaration. Match the full reader's
   accepted grammar and return the normal public record type.
7. **Benchmark and evidence** — add the format/profile builders and result
   cases consumed by `bench/io_bench/runner.py`, then add every applicable
   profile/direction to `bench/PERFORMANCE_STATUS.toml`. New backend state
   remains provisional and visible until a trigger-based comparison qualifies
   it; provisional status alone does not block an otherwise verified release.
8. **Parity and common-path tests** — add `tests/codecs/test_<fmt>.py` using
   `sceneio.testing.assert_codec_parity(...)` against the reference oracle
   (pycolmap / gsply / Open3D / imageio / …). Cover: cross-impl equality,
   round-trip identity, a convention pin, and numpy↔torch. Enroll the codec in
   shared mmap, direct-sink, inspection, partial-read, E2E, and malformed-input
   cases as applicable.
9. **Package and document** — add the NumPy-only installed-wheel smoke,
   generated capability row, architecture/source completeness entry, and any
   required `LICENSES/` and `third_party/*/COMMIT.txt` records.

The public dispatch layer handles common routing and error mapping. The
manifest, native bindings/build list, production adapters, inspection/partial
tables, benchmark corpus, shared tests, wheel smoke, capability row, and
dependency records are all part of the current codec contract.

After R1-R4, a codec is declared once in the authoritative manifest and
implemented within its format family. Architecture tests require that the
registry, inspector table, benchmark cases, test cases, native feature
metadata, binding registration, and build source list all resolve to the same
id set. Backend replacement follows the R5 comparison mechanism only when a
measured regression, material hotspot, or concrete candidate triggers it. The
result is recorded in `bench/PERFORMANCE_STATUS.toml`; exhaustive alternative
discovery is not part of ordinary codec or R6 closure.

## Metadata-only inspection

`sceneio.inspect(path, format=None)` returns a frozen `Inspection`:

- `shape`, `dtype`, and `channels` describe the primary decoded array;
- `count` describes repeated points, Gaussians, views/images, or tensors;
- `arrays` carries per-member shape/dtype for NPZ;
- `metadata` is a read-only mapping for scalar details such as reconstruction
  camera/image/point counts, SH degree, LAS point format, or Netpbm maxval;
- `byte_size` is the encoded file or directory size.

Simple binary formats stop at their public headers; databases and compound
containers may additionally read bounded indexes or metadata directories.
NPY/NPZ read only array headers, legacy gzip SPZ inflates only its 16-byte
metadata prefix, and COLMAP binary reads the three leading counts. Headerless
text formats stream their records; XYZ and COLMAP text use GIL-released
compiled scans. The `transforms.json` and OpenMVG inspection paths use bounded
nlohmann SAX passes and do not construct a document DOM or record arrays;
plain glTF/GLB inspection uses cgltf. Individual metadata tokens are capped at
1 MiB and JSON nesting at 256 levels. Bounded text scanners enforce their
line/token limit before searching farther into the mapping, so malformed
no-newline inputs do not fault the whole file into RSS. Inspection reports
structural metadata and is not a substitute for decoding and validating every
payload sample.

BMP and TGA use the already-vendored stb raster implementation only after a
format-specific bounded preflight. BMP preflight validates Windows DIB
dimensions, palette layout, row size, BI_RGB/BI_BITFIELDS masks, and complete
pixel storage. TGA preflight validates image type, palette origin/extent,
orientation flags, raw or RLE packet counts, and complete pixel storage.
Unsupported conventions are refused rather than approximated. Both inspectors
stop after these small headers, while their deterministic writers stream native
callback output through a bounded 256 KiB staging buffer on public file writes.

BAL inspection reads only the three header counts. Full BAL decoding maps
zero-based observations and angle-axis camera blocks into a `Reconstruction`,
using the explicit self-inverse `diag(1,-1,-1)` camera-frame transform and a
Y-coordinate sign flip for centered observations. Its writer accepts only the
lossless canonical subset (one zero-dimension RADIAL camera per image, no
names/colors/errors/principal point or untracked observations) and refuses
unsupported record fields. The unambiguous `.bal` suffix is auto-detected;
official datasets using the generic `.txt` suffix require `format="bal"`.

## Partial reads

`sceneio.read_partial(path, ...)` requires exactly one selector and normally
returns the same public record kind as `read()`. The deliberate exception is
`colmap_db`: a selected image returns `FeatureSet` including time,
descriptor dtype/dimension/name, colors, and quality. A selected pair returns
`CorrespondenceGraph` including score-row and provenance state, while a full read
returns `ColmapDatabase`.

<!-- sceneio-partial-summary:start -->
| Selector | Built-in codecs |
|---|---|
| `faces` | `off`, `ply_mesh`, `stl` |
| `frames` | `animated_avif`, `image_sequence`, `rtmv`, `theora`, `webm`, `y4m` |
| `image_id` | `colmap_db`, `colmap_sparse`, `colmap_sparse_txt` |
| `mesh_id` | `glb`, `gltf` |
| `pair` | `colmap_db` |
| `points` | `compressed_ply`, `gaussian_ply`, `ksplat`, `las`, `laz`, `pcd`, `ply`, `pts`, `sog`, `splat`, `xyz` |
| `primitive_id` | `glb`, `gltf` |
| `slices` | `hdf5`, `safetensors`, `zarr` |
| `states` | `euroc_state` |
| `tensors` | `hdf5`, `parquet`, `safetensors`, `zarr` |
| `window` | `colmap_mvs_depth`, `colmap_mvs_normal`, `dmb`, `flo`, `netpbm`, `pfm`, `webp` |
<!-- sceneio-partial-summary:end -->

Selector semantics are:

- `window=(row_start, row_stop, column_start, column_stop)` uses half-open bounds
  for PFM, binary P5/P6 Netpbm, lossless VP8L WebP, FLO, scalar DMB, and
  COLMAP MVS depth/normal matrices;
- `points=(start, stop)` selects a half-open range from XYZ, count-prefixed PTS,
  LAS/LAZ, point PLY/PCD, binary Gaussian PLY, compressed PLY/SOG/KSplat, and
  `.splat`;
- `faces=(start, stop)` selects half-open polygon or triangle ranges from mesh
  PLY, OFF, and STL;
- `frames=(start, stop)` selects lazy encoded paths from image directories or
  selected native planar frames from raw Y4M;
- `states=(start, stop)` selects a half-open EuRoC trajectory range;
- `tensors=("name", ...)` selects named tensors from safetensors without
  materializing unrelated payload tensors;
- `slices={"name": (start, stop), ...}` selects half-open leading-axis ranges
  from named safetensors tensors;
- `image_id=<persisted COLMAP id>` returns a one-image `Reconstruction` plus
  every camera required by its retained modern rig/frame, or its one referenced
  camera for a legacy model. It deliberately leaves the point arrays empty and
  does not open `points3D.bin` / `points3D.txt`.
- `image_id=<persisted COLMAP id>` on `colmap_db` returns that image's compiled
  `FeatureSet`; `pair=(image_id1, image_id2)` returns the unordered pair's
  canonical `CorrespondenceGraph`. Both use indexed SQL queries and do not fetch
  unrelated feature or match BLOBs.
- `mesh_id=<source mesh index>` or `primitive_id=<flattened source primitive
  index>` on glTF/GLB returns a `SceneGraph` containing only those selected
  primitive arrays and the shared materials.

PFM, binary Netpbm, and DMB copy only selected rows, lossless WebP uses
libwebp's cropped decoder, and FLO returns a read-only derived view whose owner
retains the mmap. ASCII P2/P3 reject because they require complete-payload token
decoding; lossy VP8 rejects because crop-local chroma upsampling is not
guaranteed to match a full-decode slice. Fixed-record
cloud formats index their selected records; XYZ and PTS scan text for row
boundaries but allocate and parse numeric values only for the requested range.
PTS additionally validates its mandatory declared point count.
Safetensors selection returns read-only mmap-backed tensor views where host
byte order and payload alignment permit; each view retains its mapping owner
after the file handle leaves scope.
Unsupported codecs raise `FormatError` rather than disguising a full decode as
a partial read. COLMAP text caps non-name tokens at 1 MiB consistently in its
full and partial readers; image names retain their unbounded format behavior.

## Plain glTF/GLB scene subset

The compiled cgltf-backed path preserves multiple meshes/primitives, node
parent/child relationships, local matrix/TRS transforms, multiple scenes,
default-scene identity, metallic-roughness material factors, URI image
references, and sampler metadata in `SceneGraph` + `MaterialSet`. JSON glTF maps
each relative external buffer beside the document; data-URI buffers and the
GLB BIN chunk are also supported. Dense, strided, and sparse accessors normalize
to canonical record arrays while preserving their values.

The canonical geometry subset is triangle primitives with POSITION float32 and
optional NORMAL float32, TEXCOORD_0 (float or normalized u8/u16), normalized
RGBA/RGB u8 colors, and u8/u16/u32 indices. Writers produce deterministic dense
float32 attributes, RGBA8 colors, and u32 indices. A `.gltf` write encodes once,
writes sibling JSON/BIN temporaries through native sinks, then atomically
publishes the pair; `.glb` uses the normal single-file sink.

Features without a faithful record contract reject explicitly: non-triangle
primitive modes, corner-domain attributes, additional UV sets, bufferView
images, double-sided or extended material properties, skins, morph targets,
animation, cameras, lights, unknown extensions, Draco, and meshopt.
