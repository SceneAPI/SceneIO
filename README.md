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
