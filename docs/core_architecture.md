# SceneIO core architecture (nanobind)

How the compiled core is organized, and **how to add a codec** — the two
things that keep this expansible as the format list from
`formats_survey.md` grows.

> **Growth checkpoint:** the live registry has reached 70 format ids. The
> format-focused native layer remains coherent, but registry, inspection,
> benchmark, test-matrix, dependency, and binding wiring have outgrown a flat
> layout. The behavior-preserving R3-R5 organization work and R6 source/package
> closure are complete at packaged source commit `105b301`. Exact-head CI,
> native-runtime validation, the MSVC/GCC 10/AppleClang build-only matrix,
> artifact inspection, and closure review pass; publication is skipped. A new
> codec wave starts only on explicit user direction. The paths below describe
> the current family boundaries and compatibility contracts; full closure
> evidence is in
> [`next_stage_implementation_checklist.md`](next_stage_implementation_checklist.md#r6-closure-evidence).
> The post-R6 COLMAP dense unit adds a ninth `dense` family, three records,
> four buffer codecs, and a lazy workspace adapter. The current inventory is
> 55 native/hybrid rows, 12 Python-owned optional-provider rows, ten registry
> families, and 19 compiled record-registration units. The optional-provider
> adapters are
> isolated by family (`_hdf5`, `_zarr`, `_tiff`, `_e57`, `_arrow`,
> `_openvdb`, `_usd`) and preserve the NumPy-only base import. The repository
> owns their stable schema, validation, inspection, and public mapping while
> established upstream libraries own optimized storage and parsing. The
> older 50-codec and eight-family numbers below remain immutable evidence
> for their named commits.
>
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
  bindings/    record + nine codec-family descriptor tables and assembler
  io/          format-agnostic helpers: endian, byte reader/writer, gzip
  module.cpp   invokes the record pass, codec pass, then publishes inventory

cmake/
  SceneIOInstrumentation.cmake  opt-in compiler instrumentation
  SceneIOSources.cmake          bindings, records + nine codec-family owners
  SceneIODependencies.cmake     Python/nanobind + native dependency targets
  SceneIOBackendQualification.cmake
                                internal defaults + default-off comparison
  SceneIOTargets.cmake          _core and native-control targets
```

**Separation of concerns**
- A **record** (e.g. `Reconstruction`, `GaussianCloud`) is a memory
  representation. It owns contiguous SoA buffers, hands out zero-copy
  ndarray views (numpy default; torch/cupy via DLPack), and **carries its
  conventions as machine-readable metadata** (quaternion order, pose
  direction, scale/opacity space) — never only in comments. A record is
  registered **once** and reused by every codec that produces it (SPZ and
  PLY both yield `GaussianCloud`).
- Rich 3D-CV stages use the additive `SceneGraph` record rather than widening
  the established `MeshScene` contract. `SceneGraph` owns node topology,
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
  `instances.py` adapters. Camera records use one unambiguous render-product
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
  public writes use native file sinks or container-specific path sinks. A
  codec depends on `records/` and `io/`, never on another codec.
- The **Python `io` layer** is the UX + extensibility seam: the registry maps
  a format id to its extensions, magic sniff, reader, writer, optional
  inspector, partial readers, record type, and DataType;
  `read()`/`write()`/`inspect()`/`read_partial()`/`detect()` dispatch through it
  and map errors. Today, registration plus inspector, benchmark, test-matrix,
  CMake, and nanobind wiring are separate touch points. R1-R4 preserve this
  public facade while deriving those family views from one codec manifest.
  The image-sequence directory adapter is the first completed R2 boundary: its
  live image-extension catalog and frame inspector are injected through
  `ImageFrameAccess`, so it no longer imports the registry or public I/O facade
  during an operation. `inspect_codec` is the shared lower-level dispatcher
  used by both public and injected inspection. R2.1 keeps `registry.py` as the
  compatibility facade while extracting shared value types, mmap/path/sink
  adapters, ordered detection, and native-feature metadata into focused
  `sceneio.io._registry` modules. Family extraction consumes those lower
  modules and never the public facade. The model classes are defined in
  `_registry/model.py` but deliberately advertise their historical
  `sceneio.io.registry` module so repr and existing pickle payloads remain
  compatible. Because `sceneio.io` remains an eager compatibility facade,
  importing a dotted `_registry` module in a fresh process still initializes
  its parent package; R2.1 guarantees an acyclic source dependency direction,
  not a standalone lightweight import boundary.
  Calibration is the first extracted registry/inspection family:
  `_registry/families/calibration.py` exports an immutable, side-effect-free
  four-codec tuple, and the registry facade validates its exact ids, order,
  types, uniqueness, and collisions before installing any member at the
  canonical position. `_inspectors/calibration.py` owns the corresponding
  metadata conversion and native inspector table. The shared inspection value
  types now live in `_inspectors/model.py` and the common mmap-buffer bridge
  lives in `_inspectors/common.py`; both are lower-layer dependencies rather
  than facade injections. `ArrayInspection` and `Inspection` deliberately
  advertise their historical `sceneio.io._inspection` module so repr, type
  identity, and existing pickle payloads remain compatible. The compatibility
  `_inspection.py` facade re-exports those exact objects and retains the
  historical calibration wrapper signature. Family definitions and lower
  inspectors do not import either compatibility facade.
  `_inspectors/common.py` owns only proven cross-family inspection primitives:
  the bounded mmap bridge, metadata header and image-pixel limits, exact
  fixed-length reads, unsigned-decimal grammar, and the common image-result
  constructor used by PFM/FLO and raster image formats. The facade re-exports
  those exact private objects for compatibility; format-local token,
  container, and marker grammars remain with their owning family.
  Meshes are the second extracted family:
  `_registry/families/meshes.py` exports the exact contiguous PLY-mesh, OBJ,
  STL, OFF, glTF, and GLB tuple, installed atomically at its canonical
  position. `_inspectors/meshes.py` owns only PLY-mesh/STL/OFF metadata
  conversion; the compatibility facade retains same-signature wrappers and
  point-PLY ownership. OBJ and glTF/GLB keep their repository-owned bespoke
  path adapters and callable identities.
  Images are the third extracted family:
  `_registry/families/images.py` exports the exact contiguous Netpbm, PNG,
  JPEG, BMP, TGA, HDR, EXR, and WebP tuple, installed atomically between
  safetensors and Y4M. `_inspectors/images.py` owns their bounded metadata
  parsers while `_inspection.py` retains same-signature wrappers and unchanged
  dispatch branches. The image-sequence `ImageFrameAccess` object remains
  facade-owned and is constructed after image registration, preserving its
  live extension catalog and third-party registration behavior.
  Sequences are the fourth extracted family:
  `_registry/families/sequences.py` keeps Y4M static and exposes a
  side-effect-free factory for the directory codec. The registry facade
  creates `ImageFrameAccess` after image registration, passes it to the
  factory, and installs the exact Y4M/image-sequence tuple atomically.
  `_inspectors/sequences.py` owns only Y4M metadata conversion; directory
  grammar and inspection remain in `_image_sequence.py`. Repeated factory
  calls bind fresh directory codecs to their supplied live access objects
  without storing registry state in the family module.
  Arrays are the fifth extracted family and the first non-contiguous one:
  `_registry/families/arrays.py` returns the exact PFM, NPY, NPZ,
  safetensors, FLO, and DMB tuple after receiving the facade-owned `_canon`
  and `_prepare_tensor_dict` callbacks. Keeping those callbacks in
  `registry.py` preserves writer callable identity while the aggregate
  collector restores canonical positions 0/25/26/27/43/44.
  `_inspectors/arrays.py` owns their metadata-only parsing, including the
  shared NPY-header parser used by NPZ. `_inspection.py` retains
  same-signature wrappers, its historical private helper identities, and the
  unchanged dispatch table. The family module owns no registry state, and
  neither lower module calls a full decoder during inspection.
  Points are the sixth extracted family and the second non-contiguous one:
  `_registry/families/points.py` exports the exact PLY, PCD, XYZ, PTS, LAS,
  and LAZ tuple. Aggregate publication restores canonical positions
  12/13/39/40/41/42 while retaining every mmap, sink, and point-range native
  target. `_inspectors/points.py` owns their metadata-only PLY/PCD header,
  streamed text, LAS public-header, and LAZ VLR/chunk-table parsing.
  `_inspection.py` retains same-signature wrappers and unchanged dispatch;
  the lower inspector calls no full point decoder.
  Reconstruction is the seventh extracted family and the third
  non-contiguous one: `_registry/families/reconstruction.py` exports the exact
  12-codec tuple spanning COLMAP binary/text/database, transforms JSON,
  TUM/KITTI, EuRoC, g2o, Bundler, BAL, NVM, and OpenMVG. Aggregate publication
  restores positions 1/15/16/17/18/23/24/38/45/46/47/48 while retaining
  direct native directory/database calls, mmap/sink closures, and every
  selector target. `_inspectors/reconstruction.py` owns metadata-only parsing;
  `_inspection.py` keeps same-signature wrappers and dispatch.
  The final extraction and platform follow-ups are committed through
  `aa5b624`; normal run `30218232248` and compiler-instrumented run
  `30218232246` pass the combined tree.
  Splats are the eighth and final family. Their six metadata implementations
  now live in `_inspectors/splats.py`; `_inspection.py` retains unchanged
  dispatch and same-signature wrappers. The lower module calls only the
  compiled metadata helpers, shared inspection primitives, and shared PLY
  parser, never a full decoder or registry.
  `_registry/families/splats.py` now builds the exact Gaussian PLY, compressed
  PLY, SOG, KSplat, SPZ, and SPLAT tuple after receiving the facade-owned SOG
  archive/directory callbacks. Aggregate publication restores canonical
  positions 2/3/4/5/14/49 while preserving every mmap reader, direct sink,
  point selector, detection rule, and SOG path decision. All eight built-in
  families therefore have lower registry and inspection ownership; the
  compatibility facade contains no individual built-in definition. The
  parent contract is green across MSVC, AppleClang/ARM, hosted glibc, and
  manylinux2014/GCC-10 at `1864359`, and inspector commit `a4c968b` passes
  normal run `30224059298` and compiler-instrumented run `30224059282`. The
  registry implementation commit `3e46d82` and platform-contract repair
  `9928c6d` are pushed. Normal run `30228235491` and
  compiler-instrumented run `30228235535` pass the final tree, including the
  three-OS splat parity matrix and GCC-10 lane. Exact-tree source/wheel
  packaging and all three independent reviews also pass. R2 is closed; R3
  now splits benchmark and cross-codec verification ownership.
  The current ninth family is `dense`. Its four definitions live in
  `_registry/families/dense.py`, metadata conversion lives in
  `_inspectors/dense.py`, native bindings live in `bindings/dense.cpp`, and
  the shared records/codecs live in `records/dense_mvs.*` and
  `codecs/dense/colmap_mvs.cpp`. The family owns exact COLMAP MVS depth,
  normal, consistency, and fused-visibility formats; aggregate publication
  stages the tuple once while preserving the established canonical order.
  `DepthMap`, `NormalMap`, `ConsistencyGraph`, and `PointVisibility` expose
  owned, validated arrays; native readers consume contiguous buffer views and
  do not retain the mmap after decoding. Depth and normal window readers copy
  only the selected planar samples. The public `sceneio.colmap_mvs` module is
  deliberately outside the format registry: it lazily coordinates canonical,
  PMVS, and CMP-MVS path topology, configs, optional raw-PMVS projections,
  Bundler-profile workspaces, raw visibility, and existing image-codec paths
  without opening encoded image payloads.
  The tenth registry family is `containers`. Its lower-owned
  `_registry/families/containers.py` definitions and `_hdf5.py` adapters add
  generic HDF5 plus the documented hloc feature and match schemas. Importing
  SceneIO does not import h5py; capabilities report these codecs unavailable
  until the named `sceneio[hdf5]` extra is installed. Optimized upstream
  h5py/HDF5 owns storage calls, while SceneIO owns accepted schemas,
  validation, detection, native-record mapping, metadata inspection, partial
  selection, and atomic path replacement. The C-native
  `SCENEIO_WITH_HDF5` manifest entry remains a future comparison seam rather
  than the current implementation.
  The public `sceneio.colmap` package follows the same adapter boundary for
  portable fork workflow data: extended sparse sidecars, semantic
  MappingInput v1/v2, MegaLoc artifacts, rig JSON, SIFT, pair/cap and match
  text, and Sim3. It owns strict records and mapped/streamed transport without
  adding registry codec IDs or runtime dependencies. The low-level sparse
  bindings retain their default sidecar refusal; only the explicit extended
  adapter opts into base-model parsing while it validates every companion.
  R3.1a keeps `bench/bench_io.py` as the compatible development-only facade
  while `bench/io_bench/model.py`, `measure.py`, and `reporting.py` own shared
  benchmark records, timing/traced allocation plus explicitly named
  warmed-parent `in_process_rss`, and deterministic presentation. Its checked
  contract pins parent provenance, JSON shape, record-aware fixture
  fingerprints, and a console transcript. The production package does not
  include `bench`. R3.1b now supplies the separate versioned fresh-child
  memory protocol in `bench/io_bench/memory_protocol.py` and
  `memory_child.py`: one warm-up precedes the RSS baseline, each child performs
  exactly one measured operation, and unavailable sampling remains explicit
  rather than becoming a zero. A retained calibration closes any
  pre-measurement high-water gap. The reported lifetime peak is the monotonic
  envelope of the platform counter and every observed current-RSS value, and
  the sampler stops before the final envelope while the measured result stays
  alive. Strict evidence rejects residual headroom, fewer than three samples,
  request/response mismatch, differing semantic operation signatures, and a
  spike at any intermediate payload size.
  Repeated 8/48 MiB controls distinguish a bounded 64 KiB read from a
  whole-payload allocation, and the protocol test is wired into the
  three-platform mmap lane. R3.2 moves family fixtures/oracles before moving
  the remaining sweep runner. The arrays checkpoint now owns its deterministic
  six-codec `Spec` construction under `bench/io_bench/families/arrays.py`,
  plus its DMB fixture, NumPy/NPZ/DMB oracles, and optional safetensors
  bindings under `bench/io_bench/{fixtures,oracles}/arrays.py`; the compatible
  facade re-exports those helpers, and a checked source/AST map plus direct
  installed/absent-mode oracle execution controls prove their identity and
  availability. R3.1b closes at `0bdfe0f`; normal run `30234796010` and
  compiler-instrumented run `30234796025` pass. The arrays extraction at
  `6d9ec34` passes normal run `30236069971` and compiler-instrumented run
  `30236069959`. Calibration is the second R3.2 benchmark family:
  `families/calibration.py` owns its complete four-`Spec` hook,
  `fixtures/calibration.py` owns both deterministic rig builders,
  `oracles/calibration.py` owns optional PyYAML and standard-library XML
  comparisons, and `families/common.py` owns the unchanged record-size helper
  shared with later pose/reconstruction families. Lower modules do not load
  the facade; checked installed/absent-mode controls preserve every callback
  and compatibility alias. Exact calibration commit `5dc03f4` passes normal
  run `30237676629` and compiler-instrumented run `30237676648`. The raster
  image checkpoint lower-owns all eight PNG/JPEG/BMP/TGA/WebP/HDR/EXR/Netpbm
  specs under `families/images.py`, deterministic uint8/float32 fixtures under
  `fixtures/images.py`, and optional Pillow/imageio/OpenEXR comparisons under
  `oracles/images.py`. The facade slices that hook around the unchanged Y4M
  position. Checked helper identities, real oracle-pair execution, exact EXR
  RGB normalization, and installed/absent/fallback controls preserve the
  historical behavior. Portable independent Radiance HDR benchmark throughput
  is an explicit exemption; independent NumPy RGBE codec parity remains in the
  HDR parity suite. Exact raster commit `6572a76` passes normal run
  `30239455960` and compiler-instrumented run `30239455952`. The mesh
  checkpoint lower-owns the five buffer-backed PLY-mesh/OBJ/STL/OFF/GLB specs,
  five deterministic mesh/scene fixtures, and 12 optional trimesh helpers.
  Specialized multi-file glTF orchestration remains in
  `bench_io.py::_benchmark_gltf` until runner extraction but consumes the
  lower fixture/oracle pair through compatibility aliases. Checked cyclic
  triangle normalization preserves winding while comparing positions and
  connectivity for real oracle and core files. Exact mesh commit `613fd26`
  passes normal run `30241711640` and compiler-instrumented run `30241711620`.
  The point checkpoint lower-owns the non-contiguous XYZ/PTS/point-PLY/PCD/
  LAS/LAZ hook under `families/points.py`, its three deterministic fixtures,
  and nine PTS/Open3D/LASpy comparison helpers. The facade retains exact
  compatibility identities and slices the hook around the mesh block.
  Installed and independently absent provider controls, real comparison
  round trips, and scale-aware LAS/LAZ checks preserve the prior behavior.
  Review also aligned LAS and LAZ to one point-format-2 XYZ/RGB/intensity
  payload and one positions-equivalent throughput denominator for both
  SceneIO and LASpy. Five live oracle rows and the explicit XYZ
  benchmark-throughput exemption are recorded; independent NumPy XYZ text
  parity remains in the codec suite. Exact point commit `45e2757` passes
  normal run `30244892746` and compiler-instrumented run `30244892600`.
  The reconstruction checkpoint lower-owns the nine buffer-backed
  transforms/TUM/KITTI/EuRoC/g2o/Bundler/BAL/NVM/OpenMVG specs under
  `families/reconstruction.py`, their deterministic builders under
  `fixtures/reconstruction.py`, and portable EuRoC/g2o/BAL comparisons under
  `oracles/reconstruction.py`. The facade slices those specs around
  calibration; specialized COLMAP binary, text, and database orchestration
  remains facade-owned until runner extraction. All nine `Spec` ASTs and 12
  of 13 moved helper ASTs are unchanged. The one reviewed difference expands
  the g2o comparison reader from counts to complete semantic arrays and
  symmetric information matrices. Three rows have live portable comparison
  metrics; six carry an exact benchmark-throughput exemption backed by
  independent parity suites. The lower reconstruction modules do not import
  the facade, and the complete result-order projection remains unchanged.
  Exact reconstruction commit `76ed21b` passes normal run `30247662591` and
  compiler-instrumented run `30247662622`. The sequence checkpoint lower-owns
  the buffer-backed Y4M spec, Y4M and image-directory fixtures, and portable
  Y4M comparison under `bench/io_bench/{families,fixtures,oracles}/sequences.py`.
  Y4M remains
  between WebP and HDR; the image-directory `DirectorySpec` remains
  facade-owned until runner extraction and consumes the lower fixture through
  an exact alias. The Y4M `Spec`, directory orchestration, and three of four
  moved helpers are unchanged. The reviewed Y4M reader difference validates
  complete planes and metadata. The Y4M row has live portable comparison
  metrics; image-directory throughput has an exact exemption backed by
  independent manifest/PGM parity.
  Exact sequence commit `4b8c829` passes normal run `30250394890` and
  compiler-instrumented run `30250394906`. The splat checkpoint lower-owns
  all six ordinary splat specs, the Gaussian fixture, and the optional
  `gsply` PLY/SPZ adapters under
  `bench/io_bench/{families,fixtures,oracles}/splats.py`. Their canonical
  order and callback identities are unchanged. Gaussian PLY and SPZ retain
  live independent comparisons; Compressed PLY, SOG, KSplat, and `.splat`
  carry exact benchmark-throughput exemptions backed by their independent
  parity suites. Exact splat commit `cd32268` passes normal run `30253301819`
  and compiler-instrumented run `30253301871`. The complete sweep,
  specialized glTF/COLMAP/image-directory orchestration, CLI, and 20
  supporting functions now live in `bench/io_bench/runner.py`.
  `bench/bench_io.py` is a compatible entry point that re-exports the checked
  166-name helper surface. Repository completeness is now defined by the
  immutable `CANONICAL_BUILTIN_IDS` through
  `bench/io_bench/qualification.py`, independently of mutable runtime
  registrations. Its 50-entry ledger requires 33 timed comparisons and
  records 17 reviewed, property-specific parity exemptions. Complete sweeps
  validate the exact built-in set before measurement; strict qualification
  requires every timed callback and propagates its failures.
  Cross-codec behavior-case ownership begins under
  `tests/_support/codec_cases.py`: its immutable canonical-order catalog
  partitions the 50 built-ins into 44 buffer, three path, and three directory
  fixture definitions and pins all 28 partial-capable codecs and their 32
  selector declarations. The mmap suite now consumes the lower-owned
  `buffer_codec_cases.py` builder. After exact hosted equivalence passed, the
  duplicated local builder was removed; the architecture contract retains its
  exact traversal order, live callable identities, and 43-codec portable
  encoded-fixture projection. Compressed PLY retains the same semantic
  Gaussian input as its paired fixture and its established platform-profiled
  parity test. The mmap suite retains semantic and malformed-input coverage.
  O3 file-sink behavior now has focused ownership in
  `tests/test_io_streaming.py`; its 14 functions and 16 nodes consume the same
  buffer builder, and the assembly contract pins the exact path-only rename.
  The mmap and streaming suites share only the lower allocation-measurement
  helper rather than importing one another. Inspection behavior now has
  focused ownership in `tests/test_io_inspection.py`; its 47 tests and three
  helpers consume the same buffer builder, and its exact 76-node path-only
  move is contract-pinned alongside streaming.
  Partial migration starts with three unchanged array-specific DMB/FLO tests
  in `tests/test_io_partial_arrays.py`; their exact path moves and destination
  AST projection are contract-pinned. Image-specific Netpbm/WebP behavior now
  lives in `tests/test_io_partial_images.py`; two shared image-window
  assertions have lower ownership in `tests/_support/partial_read.py`.
  Mesh face-range behavior now has focused ownership in
  `tests/test_io_partial_meshes.py`; its exact path move and destination AST
  projection are contract-pinned.
  Point-specific XYZ/LAS behavior now lives in
  `tests/test_io_partial_points.py`; its shared point/splat range assertion
  has lower ownership in `tests/_support/partial_read.py`.
  Reconstruction-specific COLMAP behavior and private measurement helpers now
  live in `tests/test_io_partial_reconstruction.py`; their one shared
  fresh-process RSS helper has lower ownership in
  `tests/_support/partial_read.py`.
  Cross-family partial invariants remain in `tests/test_io_partial.py` while
  sequence and splat dedicated partial behavior remains in the existing
  family architecture/codec suites. The assembly contract pins that
  disposition and all seven shared test projections, preventing an empty
  family suite or an artificial split of point/splat and large-read
  invariants.
  Built-in startup uses `_registry/assembly.py` as a lower staging boundary.
  Eight complete family tuples are collected without touching the public
  registry. After all 50 canonical ids validate, the facade publishes the
  same ordered `Codec` objects to its existing `REGISTRY` dictionary in one
  update on first import. Reloads assemble and validate a private candidate
  mapping before replacing the contents of the same live dictionary, so a
  failed reload cannot expose a partial registry and registered extensions
  survive successful reloads. `ImageFrameAccess` is created while that
  dictionary is empty, but
  its callbacks read the live dictionary on every use; the initial empty
  probe is not cached. Once publication completes, built-in detection and
  sequence access see the complete set, and later public `register()`
  additions/removals remain immediately visible. The collector owns no
  registry, codec implementation, or dispatch policy.

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
  MSVC sdist-to-wheel build, package inventory, license gate, and all-50
  installed smoke form the final local package gate. The release workflow
  makes every platform wheel consume that one verified sdist with hash-locked
  build inputs. Final run `30406706115` passes its MSVC, GCC 10, and AppleClang
  execution and downloaded-artifact inspection, closing R6. The R5 JPEG
candidate is
additionally built by a default-off external project from the official
libjpeg-turbo 3.2.0 archive. The clean MSVC qualification rejected that exact
candidate as the combined stable default after it missed the frozen q95
comparative-quality floor, so it does not enter ordinary builds or wheels and
stb remains the repository-owned default. Separately installed libraries and
executables remain verification oracles; they are not runtime delegates.

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
  keypoint colors, and quality. `MatchGraph.scores` is absent when no score
  row exists anywhere; otherwise it is parallel to all raw matches and
  zero-filled for pairs whose `match_score_present` is zero. Pair provenance
  follows the same presence-first rule and retains unknown source-mask bits.
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
  `MeshScene` retains the source node hierarchy, local transforms, scenes, and
  mesh-to-primitive ranges instead of baking or flattening transforms.

## Adding a codec — current wiring recipe

This recipe describes the committed R4.2 binding boundary and the in-progress
R4.3 family layout. During this behavior-preserving migration, use the recipe
to verify compatibility and do not start a new format.

1. **Declare ownership** — add the built-in id, family,
   `implementation_owner`, native symbols, and Python adapter symbols to
   `sceneio/io/_builtin_manifest.py`. The immutable manifest is the
   repository-completeness scope; the mutable runtime registry remains the
   third-party extension seam.
2. **Record** — if the format needs a new in-memory type, add
   `records/<name>.hpp` (the SoA struct + conventions) and
   `records/<name>.cpp` (`register_<name>()` binding zero-copy views +
   convention properties). Reuse an existing record otherwise.
3. **Codec** — use `codecs/<family>/<fmt>.cpp`; existing flat sources move
   one family at a time during R4.3. Implement `read_<fmt>()` /
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
   detection signature, reader, writer, record, datatype, container kind,
   stream flags, and optional inspection/partial hooks. Public reads and
   writes must exercise the production mmap/path/sink adapter rather than only
   the buffer seam.
6. **Inspect and select** — add the built-in parser and `inspect_path()`
   dispatch branch, or provide `Codec.inspect`; add each supported
   `read_partial` selector and capability declaration. Match the full reader's
   accepted grammar and return the normal public record type.
7. **Benchmark and evidence** — add the format/profile builders and result
   cases consumed by `bench/bench_io.py`, then add every applicable
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

The compatibility facades handle common dispatch and error mapping, but the
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
`MatchGraph` including score-row and provenance state, while a full read
returns `ColmapDatabase`.

<!-- sceneio-partial-summary:start -->
| Selector | Built-in codecs |
|---|---|
| `faces` | `off`, `ply_mesh`, `stl` |
| `frames` | `animated_avif`, `image_sequence`, `rtmv`, `webm`, `y4m` |
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
  compiled `MatchGraph`. Both use indexed SQL queries and do not fetch
  unrelated feature or match BLOBs.
- `mesh_id=<source mesh index>` or `primitive_id=<flattened source primitive
  index>` on glTF/GLB returns a `MeshScene` containing only those selected
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
references, and sampler metadata in `MeshScene` + `MaterialSet`. JSON glTF maps
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
