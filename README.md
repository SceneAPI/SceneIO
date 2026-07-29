# sceneio

The **contract plane** for [SceneAPI](https://github.com/SceneAPI): the data
contracts *and* the procedure contracts the whole family agrees on. This is a
contract package — datatypes, Protocols, wire codecs, and format registries —
not an implementation. The SceneAPI core, the implementation bundles
(SceneMap, SceneMatch, ...), and the generated SDKs all meet here.

- Distribution: `sceneio`
- Import package: `sceneio`
- Version: `0.2.0`
- Dependencies: `numpy>=1.26` (the contracts are numpy-native)
- Leaf property: imports **nothing from the SceneAPI family**
  (`sceneapi` / `sfm_hub` / `app`) — guard-tested

## What it owns

### Data contracts — `sceneio.data`

Numpy-native, construction-validated datatypes (violations raise
`ContractViolation`):

- **Calibration** — `CameraIntrinsics` (COLMAP camera-model enum + params
  array) | `RayMap` (per-pixel unit ray directions, the first-class
  non-pinhole alternative), unioned exclusively by `Calibration`.
- **Transforms** — `SE3` / `Sim3` with explicit convention tags (default
  `"opencv_cam2world"`) and to/from COLMAP world-to-camera quaternion form.
- **Priors** — `PosePrior` (SE3 + weight/covariance + `is_metric`).
- **Dense per-view** — `DepthMap`, `Pointmap` (declared frame),
  `ConfidenceMap`, `Mask`.
- **Sparse correspondence** — `FeatureSet`, `PairCorrespondences`
  (`indexed` = detector-based | `coordinates` = detector-free),
  `CorrespondenceGraph`, `TwoViewGeometry`, `TrackedPointCloud`.
- **View inputs** — `ViewInput` (image ref via the imagesource types or an
  in-memory array + optional calibration/priors/mask), `PosedViewSet`, and
  `FrameMeta` (`world_frame="first_view"`, scale
  `arbitrary | normalized | metric` + scale provenance).

### Procedure contracts — `sceneio.mapping` / `sceneio.matching`

- `Mapper` (+ `MapperTraits`, `MappingOptions`, `MappingResult`): the neutral
  mapping contract. Correspondences are **optional** — classical mappers
  declare `requires_correspondences=True`; feed-forward mappers accept raw
  views. Traits declare what priors/calibration a backend consumes and
  whether it emits dense geometry or metric scale.
- `FeatureExtractor`, `PairMatcher`, `GeometricVerifier` (+ `MatcherTraits`):
  the matching contracts, honest about detector-based vs detector-free
  operation.
- The two namespaces never import each other (guard-tested), so either can
  graduate to its own distribution later.

### Conformance kits — `sceneio.testing`

`assert_mapper_conformance` / `assert_matcher_conformance` exercise any
Protocol implementation against tiny synthetic fixtures and check traits
honesty. pytest is imported lazily inside functions — importing the module
keeps pytest-free consumers clean.

### Wire codecs, storage protocols, schema contracts (pre-0.2 surface, unchanged)

- The `application/x-sfm-points-v1` binary points codec
  (`sceneio.points_binary`).
- `BlobStore` / `validate_sha` (`sceneio.blobstore`), `ImageSourceImpl` /
  `MaterializedImage` (`sceneio.imagesource`).
- The extended COLMAP scene-database schema (`sceneio.colmap_db`) and the
  `PCMAPIN` resume-checkpoint helpers (`sceneio.mapping_input`).
- Portable COLMAP workflow data (`sceneio.colmap`): extended sparse
  companions, semantic MappingInput v1/v2, MegaLoc artifacts, rig JSON, SIFT,
  pair/cap and match text, and Sim3. Encoded image/model paths remain opaque.

### Format registry — `sceneio.formats`

`FormatSpec` + `CORE_FORMATS`: the identity registry for the family's
disk/wire format ids. Seeded with the exact `sfmapi.*.v1` ids from the core's
artifacts vocabulary — wire identity unchanged.

### Compiled format I/O — `read` / `write` / `inspect` / `read_partial`

The lazy-loaded compiled core and repository-owned adapters read and write 59
image, image-sequence, depth, tensor,
point-cloud, Gaussian, mesh/scene, pose/state, reconstruction, calibration,
graph, feature-database, and scientific-container formats. HDF5 and the
documented hloc feature/match layouts use the optimized upstream `h5py`
storage engine as an optional dependency:

```console
uv pip install "sceneio[hdf5]"
```

`sceneio.inspect(path)` returns an immutable `Inspection` with shape, dtype,
channels, repeated-record counts, and format-specific scalar metadata without
decoding bulk pixel/point arrays:

```python
import sceneio

info = sceneio.inspect("frame.exr")
assert info.shape == (1080, 1920, 3)
assert info.dtype == "float32"

image = sceneio.read("frame.exr")
sceneio.write(image, "copy.exr")

# The raw `.flo` API remains an mmap-backed ndarray. Explicit typed adapters
# attach the format's fixed component, axis, row, unit, and invalid semantics.
flow = sceneio.read_flow("motion.flo")
assert flow.component_order == "uv"
assert flow.u_axis == "right" and flow.v_axis == "down"
sceneio.write_flow(flow, "motion-copy.flo")
flow_info = sceneio.inspect_flow("motion.flo")
assert flow_info.metadata["unit"] == "pixels"

# PFM does not portably serialize depth units or invalid-value semantics.
# The immutable encoding is therefore explicit on every typed operation.
depth_encoding = sceneio.DepthEncoding(
    unit="meters",
    scale_to_meters=1.0,
    invalid_policy="nonfinite",
)
depth = sceneio.read_depth("depth.pfm", encoding=depth_encoding)
sceneio.write_depth(depth, "depth-copy.pfm", encoding=depth_encoding)
depth_info = sceneio.inspect_depth("depth.pfm", encoding=depth_encoding)
assert depth_info.metadata["scale_to_meters"] == 1.0

# A ScanNet-style uint16 millimeter PNG uses the same explicit API. Stored
# integers are widened exactly to float32; they are not divided on read.
millimeter_encoding = sceneio.DepthEncoding(
    unit="millimeters",
    scale_to_meters=0.001,
    invalid_policy="zero",
)
millimeter_depth = sceneio.read_depth(
    "depth.png",
    encoding=millimeter_encoding,
)

# Scalar EXR depth also requires the exact stored channel name. HALF input
# widens to float32; values are otherwise preserved without color conversion.
exr_encoding = sceneio.DepthEncoding(
    unit="meters",
    scale_to_meters=1.0,
    invalid_policy="nonfinite",
    channel_name="Z",
)
exr_depth = sceneio.read_depth("depth.exr", encoding=exr_encoding)
sceneio.write_depth(exr_depth, "depth-copy.exr", encoding=exr_encoding)

# Half-open row/column bounds; returns the normal Image/ndarray type.
tile = sceneio.read_partial("flow.flo", window=(100, 356, 200, 712))

# Typed PFM windows return a DepthMap and read only the selected rows.
depth_tile = sceneio.read_depth(
    "depth.pfm",
    encoding=depth_encoding,
    window=(100, 356, 200, 712),
)

# Scalar DMB windows preserve DepthMap unit and invalid-value metadata.
depth = sceneio.read_partial("depth.dmb", window=(100, 356, 200, 712))

# `.bal` is detected directly. Official BAL datasets commonly use the generic
# `.txt` suffix, which requires an explicit format to avoid text ambiguity.
problem = sceneio.read("problem-16-22106-pre.txt", format="bal")

# Fixed-record point containers allocate only the selected range.
points = sceneio.read_partial(
    "survey.las", points=(1_000_000, 1_010_000)
)
# LAS waveform formats 4/5/9/10 retain their internal descriptor VLRs,
# packet EVLR, references, and opaque point fields in `points.las_waveform`.
# External `.wdp` packet files are rejected instead of silently dropped.

# LAZ formats 0-3 and 6-8 use pinned LAZperf. Point subsets decompress only
# overlapping LASzip chunks; inspect reads only the LAS/LASzip headers.
compressed_points = sceneio.read_partial(
    "survey.laz", points=(1_000_000, 1_010_000)
)
assert sceneio.inspect("survey.laz").metadata["point_format"] in {
    0, 1, 2, 3, 6, 7, 8
}

# `.ply` detection reads the header schema: ordinary vertices become a
# PointCloud, 3DGS properties remain a GaussianCloud, and face elements become
# a polygon-preserving Mesh. Binary point and mesh-face ranges are bounded.
cloud = sceneio.read("scan.ply")
cloud_part = sceneio.read_partial("scan.ply", points=(10_000, 20_000))
assert sceneio.inspect("scan.ply").metadata["encoding"] in {
    "ascii",
    "binary_little_endian",
    "binary_big_endian",
}

# OBJ resolves its single relative MTL reference beside the OBJ. Writing a Mesh
# with an attached MaterialSet creates deterministic adjacent `.obj` + `.mtl`
# outputs without output-sized Python bytes.
mesh = sceneio.read("asset.obj")
sceneio.write(mesh, "asset-copy.obj")

# STL maps its format-native triangle soup and facet normals without welding.
# OFF preserves indexed polygon boundaries and its supported vertex attributes.
triangle_part = sceneio.read_partial("part.stl", faces=(1_000, 2_000))
polygon_mesh = sceneio.read("model.off")
polygon_part = sceneio.read_partial("model.off", faces=(100, 200))

# Plain glTF/GLB keeps source mesh/primitive ranges, node hierarchy and local
# transforms, scenes, shared metallic-roughness materials, and URI images in a
# MeshScene. JSON glTF maps sibling buffers; GLB maps its embedded BIN chunk.
mesh_scene = sceneio.read("asset.gltf")
primitive = sceneio.read_partial("asset.gltf", primitive_id=3)
assert sceneio.inspect("asset.gltf").metadata["num_primitives"] >= 4
sceneio.write(mesh_scene, "asset-copy.glb")

# PCD 0.7 preserves organized WIDTH/HEIGHT and VIEWPOINT. Public writes use
# little-endian binary; the core also supports ASCII and LZF binary_compressed.
organized = sceneio.read("organized.pcd")
assert organized.width * organized.height == organized.num_points
pcd_part = sceneio.read_partial(
    "organized.pcd", points=(10_000, 20_000)
)
assert sceneio.inspect("organized.pcd").metadata["storage"] in {
    "ascii",
    "binary",
    "binary_compressed",
}

# EuRoC ground-truth CSV keeps epoch timestamps exact as int64 nanoseconds and
# records its reference/sensor frame, WXYZ, sign, and SI-unit conventions.
states = sceneio.read("state_groundtruth_estimate0/data.csv")
assert states.timestamps_ns.dtype.name == "int64"
state_part = sceneio.read_partial(
    "state_groundtruth_estimate0/data.csv", states=(1_000, 2_000)
)

# A marked image directory returns lazy encoded-frame paths; individual pixels
# are decoded only when those paths are passed back to sceneio.read().
sequence = sceneio.read("frames")
first_frame = sceneio.read(sequence.frame_paths[0])
middle = sceneio.read_partial("frames", frames=(100, 200))

# Raw Y4M preserves native uint8 planar Y/U/V sampling without RGB conversion.
planar = sceneio.read("capture.y4m")
assert planar.storage_mode == "yuv_planar"
assert planar.chroma_subsampling in {"mono", "420", "422", "444"}
selected = sceneio.read_partial("capture.y4m", frames=(100, 200))

# One COLMAP pose and its camera, without opening points3D.
view = sceneio.read_partial("sparse/0", image_id=42)

# COLMAP SQLite databases return the compiled I/O FeatureSet and MatchGraph
# records. A pair request is unordered and uses persisted image ids.
features = sceneio.read_partial("database.db", image_id=42)
pair_matches = sceneio.read_partial("database.db", pair=(42, 91))
assert features.image_id == 42
assert pair_matches.image_pairs.tolist() == [[42, 91]]

# Exact database profiles are repository-owned. Decoded exact records preserve
# their profile by default; inspect a cross-profile conversion before writing.
database = sceneio.read("database.db")
report = sceneio.colmap_database_conversion_report(
    database, profile="colmap-4.1.1"
)
if report.writable:
    sceneio.write(
        database, "database-4.1.db", profile="colmap-4.1.1"
    )

# Safetensors tensors are read-only mmap views. Slices are half-open on the
# leading axis and do not decode or copy unrelated tensor payloads.
weights = sceneio.read_partial(
    "model.safetensors", tensors=("encoder.weight", "encoder.bias")
)
rows = sceneio.read_partial(
    "model.safetensors", slices={"embedding.weight": (10_000, 20_000)}
)

# Generic HDF5 maps supported numeric datasets to a TensorDict. Named reads
# and leading-axis hyperslabs avoid loading unrelated datasets.
tensors = sceneio.read("arrays.h5", format="hdf5")
selected = sceneio.read_partial(
    "arrays.h5",
    format="hdf5",
    tensors=("features/descriptors",),
)
rows = sceneio.read_partial(
    "arrays.h5",
    format="hdf5",
    slices={"features/descriptors": (1_000, 2_000)},
)
sceneio.write(tensors, "arrays-copy.h5", format="hdf5")

# hloc adapters preserve the documented on-disk D-by-N descriptor layout
# while exposing native N-by-D FeatureSet records and a native MatchGraph.
feature_store = sceneio.read("features.h5", format="hloc_features")
match_store = sceneio.read("matches.h5", format="hloc_matches")
first_features = feature_store[next(iter(feature_store))]
assert first_features.descriptors.shape[0] == first_features.keypoints.shape[0]
assert match_store.graph.pair_count == len(match_store.pair_names)

# Frozen discovery metadata: no trial import/read is needed.
caps = sceneio.capabilities("webp")
assert caps.can_read and caps.can_write and caps.can_inspect
assert caps.partial_selectors == ("window",)
assert "animation" in caps.unsupported_features

# Optional compiled integrations remain discoverable when unavailable.
assert not sceneio.native_features("hdf5").available
```

`sceneio.FeatureSet`, `sceneio.MatchGraph`, `sceneio.ColmapDatabase`,
`sceneio.ColmapRigFrameSet`, `sceneio.ColmapPosePriorSet`,
`sceneio.ColmapMarkerSet`, `sceneio.ColmapVideoMetadataSet`,
`sceneio.ColmapMaxxSchemaInfo`,
`sceneio.Mesh`, `sceneio.MaterialSet`, `sceneio.MeshScene`, and
`sceneio.ImageSequence` are compiled, storage-faithful I/O records.
`sceneio.HlocFeatureStore` and `sceneio.HlocMatchStore` are immutable
repository-owned schema adapters over those native feature and match records.
The procedure-contract `sceneio.data.FeatureSet` remains a separate Python
record for matcher APIs.

Partial reads are available only when the container has a genuine bounded
access path; requesting one from a codec that would have to decode the complete
payload raises `FormatError`. Pixel windows support PFM, binary P5/P6 Netpbm,
lossless VP8L WebP, FLO, and scalar DMB; lossy WebP and ASCII P2/P3 reject because they
cannot provide a bit-exact bounded slice. Safetensors supports complete
named-tensor selection and contiguous leading-axis slices.
Image directories return lazy validated frame paths, while raw Y4M frame
ranges copy only the selected planar frames.
Count-prefixed PTS supports bounded point ranges while validating the declared
point count and preserving supported intensity/RGB columns. Generic PLY reads
ASCII and binary little/big endian point schemas; only fixed-record binary PLY
supports bounded point ranges. COLMAP SQLite indexed image reads include
time ID, descriptor dtype/dimension/name, colors, and quality; indexed pair
reads include raw/verified matches, score-row state, and provenance. Current
upstream COLMAP database reads also expose optional recovered endpoint cameras
on `MatchGraph`, including independent SQL-NULL presence and prior-focal flags.
Full stock 3.13/4.1.1/current database reads additionally expose owned
rig/frame assignments and image-linked or generalized pose priors. SQL NULL
state, WXYZ rig transforms, and covariance wire order are preserved; exact
3.13, 4.1.1, current, and MAXX schemas can now be selected explicitly when
writing. A decoded exact database keeps its profile through ordinary
`sceneio.write`; constructed legacy records retain the hybrid default.
`sceneio.colmap_database_conversion_report` lists identity changes and every
represented-data incompatibility before a conversion opens its destination.
Owned MAXX
database reads also preserve all five descriptor scalar dtypes, keypoint
colors, match scores and provenance, image quality/time, extended pose priors,
markers/projections, metadata-only video/frame rows, and the ownership record.
Source-path text is inert metadata; SceneIO does not decode encoded media.
Generic HDF5 accepts fixed-size numeric and boolean datasets plus text root
attributes; named-tensor selection and contiguous leading-axis hyperslabs are
bounded reads. String datasets, compound or variable-length dtypes, references,
virtual datasets, and linked datasets are rejected rather than converted.
Plain
glTF/GLB supports source mesh and flattened primitive selection while rejecting
unrepresented scene features instead of silently dropping them.

### Errors

`SceneIoError` is the root; `ContractViolation` is raised for every
data/procedure contract breach.

## Who depends on it

The SceneAPI **core** (`sceneapi`) re-exports these contracts from its
historic module paths and orchestrates implementations of them. Backend
bundles (SceneMap, SceneMatch, 3DGS trainers) are *conforming
implementations*: they depend on `sceneio` for the datatypes and
Protocols, and prove conformance with the kits in `sceneio.testing`. The
Python / TypeScript / C++ SDKs decode the same wire formats. Keeping every
contract in one leaf package means all of them move in lockstep — and
because each namespace is import-isolated, a domain contract can graduate to
its own distribution once it stabilizes.

## Usage

```python
import numpy as np
from sceneio.data import ViewInput, FrameMeta, SE3

view = ViewInput(image=np.zeros((480, 640, 3), dtype=np.uint8), name="frame0")
pose = SE3.from_colmap_world2cam([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
frame = FrameMeta(scale="arbitrary", scale_provenance="unknown")
```

```python
from sceneio.mapping import Mapper, MapperTraits, MappingResult

class MyMapper:
    def traits(self) -> MapperTraits: ...
    def map(self, views, *, correspondences=None, options=None) -> MappingResult: ...

# prove conformance in your test suite:
from sceneio.testing import assert_mapper_conformance
assert_mapper_conformance(MyMapper())
```

```python
from sceneio import Point3DRecord, encode_all, decode_records

blob = encode_all(
    [Point3DRecord(point3d_id=1, xyz=(1.0, 2.0, 3.0), rgb=(255, 0, 0), track_len=4)],
    bbox_min=(1.0, 2.0, 3.0),
    bbox_max=(1.0, 2.0, 3.0),
)
records, bbox_min, bbox_max = decode_records(blob)
```

## Development

```powershell
uv pip install -e ".[dev,test]"
.venv/Scripts/python.exe -m ruff check
.venv/Scripts/python.exe -m pytest -q
```

Engineering status and extension work are tracked in:

- [`docs/format_coverage.md`](docs/format_coverage.md) — exact live codec
  capabilities and validation status;
- [`docs/colmap_ecosystem_coverage.md`](docs/colmap_ecosystem_coverage.md) —
  the audited `colmap_mod` persisted-I/O matrix, lean closure boundary, and
  staged verification plan;
- [`docs/colmap_adapters.md`](docs/colmap_adapters.md) — the public typed
  sparse-sidecar, MappingInput, MegaLoc, rig, SIFT, pair/match, and Sim3
  workflow adapters;
- [`docs/coverage_roadmap.md`](docs/coverage_roadmap.md) — format policy,
  declared destinations, and future sequencing rather than current evidence;
- [`docs/core_architecture.md`](docs/core_architecture.md) — current public and
  native boundaries;
- [`docs/repository_organization_plan.md`](docs/repository_organization_plan.md)
  — the completed family split, offline-source closure, trigger-based backend
  comparison mechanism, and bounded final R6 package gate;
- [`docs/next_stage_implementation_checklist.md`](docs/next_stage_implementation_checklist.md)
  — the reviewed commit-by-commit implementation, testing, benchmark, and
  cross-platform validation checklist for that gate;
- [`docs/format_gap_implementation_plan.md`](docs/format_gap_implementation_plan.md)
  — the active dependency-ordered format queue and package checkpoints;
- [`docs/plans/completed/README.md`](docs/plans/completed/README.md) — immutable
  evidence moved out of active plans after its implementation wave closes.

All live codecs have optimized mmap/direct-sink/inspection contracts, with
bounded partial paths where their format permits them. Codec-kernel performance
is tracked separately and is not called qualified until measured against the
best viable permissive upstream backend. An honest provisional ledger row is
accepted as current release behavior without making that qualification claim;
candidate comparisons are triggered by a measured regression, material
hotspot, or concrete replacement proposal.

## License

SceneIO is Apache-2.0 licensed; see [`LICENSE`](LICENSE). Licenses and required
attributions for every third-party component compiled into the native wheel
are collected in [`LICENSES/`](LICENSES/README.md).
