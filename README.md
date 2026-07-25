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

### Format registry — `sceneio.formats`

`FormatSpec` + `CORE_FORMATS`: the identity registry for the family's
disk/wire format ids. Seeded with the exact `sfmapi.*.v1` ids from the core's
artifacts vocabulary — wire identity unchanged.

### Compiled format I/O — `read` / `write` / `inspect` / `read_partial`

The lazy-loaded compiled core reads and writes 38 image, depth, tensor,
point-cloud, Gaussian, pose/state, reconstruction, calibration, graph, and
feature-database formats.
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

# One COLMAP pose and its camera, without opening points3D.
view = sceneio.read_partial("sparse/0", image_id=42)

# COLMAP SQLite databases return the compiled I/O FeatureSet and MatchGraph
# records. A pair request is unordered and uses persisted image ids.
features = sceneio.read_partial("database.db", image_id=42)
pair_matches = sceneio.read_partial("database.db", pair=(42, 91))
assert features.image_id == 42
assert pair_matches.image_pairs.tolist() == [[42, 91]]

# Safetensors tensors are read-only mmap views. Slices are half-open on the
# leading axis and do not decode or copy unrelated tensor payloads.
weights = sceneio.read_partial(
    "model.safetensors", tensors=("encoder.weight", "encoder.bias")
)
rows = sceneio.read_partial(
    "model.safetensors", slices={"embedding.weight": (10_000, 20_000)}
)

# Frozen discovery metadata: no trial import/read is needed.
caps = sceneio.capabilities("webp")
assert caps.can_read and caps.can_write and caps.can_inspect
assert caps.partial_selectors == ("window",)
assert "animation" in caps.unsupported_features

# Optional compiled integrations remain discoverable when unavailable.
assert not sceneio.native_features("hdf5").available
```

`sceneio.FeatureSet`, `sceneio.MatchGraph`, and `sceneio.ColmapDatabase` are
the compiled, storage-faithful I/O records. The procedure-contract
`sceneio.data.FeatureSet` remains a separate Python record for matcher APIs.

Partial reads are available only when the container has a genuine bounded
access path; requesting one from a codec that would have to decode the complete
payload raises `FormatError`. Pixel windows support PFM, binary P5/P6 Netpbm,
lossless VP8L WebP, FLO, and scalar DMB; lossy WebP and ASCII P2/P3 reject because they
cannot provide a bit-exact bounded slice. Safetensors supports complete
named-tensor selection and contiguous leading-axis slices.
Count-prefixed PTS supports bounded point ranges while validating the declared
point count and preserving supported intensity/RGB columns. Generic PLY reads
ASCII and binary little/big endian point schemas; only fixed-record binary PLY
supports bounded point ranges. COLMAP SQLite supports one-image features and
one-pair raw/verified matches through native indexed SQL queries.
advertises bounded point ranges.

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
uv sync --extra dev
uv run ruff check src tests
uv run pytest -q
```

## License

Apache-2.0. See `LICENSE`.
