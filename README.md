# SceneIO

SceneIO is the contract and data-I/O layer for SceneAPI. It owns validated
in-memory representations, mapping and matching protocols, format detection,
inspection, partial reads, and bounded readers and writers. Mapping, matching,
training, and application backends live in separate packages.

- Distribution and import package: `sceneio`
- Version: `0.4.0`
- Python: `>=3.12,<3.13`
- Runtime dependency: `numpy>=1.26`
- License: Apache-2.0
- PyPI: [`sceneio`](https://pypi.org/project/sceneio/)
- Source: [SceneAPI/SceneIO](https://github.com/SceneAPI/SceneIO)
- Changes: [`CHANGELOG.md`](CHANGELOG.md)

SceneIO is a leaf package: importing it does not import another SceneAPI
package. Optional format providers are lazy, so the base runtime remains
NumPy-only.

## Installation

```console
python -m pip install sceneio
```

Install only the optional providers an application needs:

```console
python -m pip install "sceneio[hdf5,zarr,tiff,e57,arrow,openvdb,usd,avif,ncore]"
```

Provider-specific profiles and platform limits are listed in the
[`format coverage contract`](docs/format_coverage.md).

## Canonical in-memory data

Every supported representation has one public identity at the `sceneio` root.
There is no second public data namespace and no loaded-versus-neutral adapter
layer. In particular, `sceneio.data`, `sceneio.canonical`, and public type
aliases under `sceneio.io` are not part of the 0.4 API.

The principal consolidated records are:

| Concept | Canonical type | Important semantics |
|---|---|---|
| Camera calibration | `CameraIntrinsics`, `RayMap`, `Calibration` | One 18-model camera vocabulary; collection ids stay on owning aggregates. |
| Sparse features | `FeatureSet` | Keypoints, optional descriptors/scores/colors/quality, pixel center, and image size. |
| Correspondences | `CorrespondenceGraph` | Per-image features plus raw and verified `PairCorrespondences`, geometry, pose, and source metadata. |
| Depth | `DepthMap` | Values, validity, unit, scale, depth meaning, coordinates, and optional confidence. |
| Posed views | `PosedViewSet` | Aligned poses, names, times, metadata, images, and calibrations. |
| Point geometry | `PointCloud` | Untracked or tracked points in one type; optional tracks use compact CSR arrays. |
| Scenes | `SceneGraph` | Hierarchy, scenes, mesh groups, materials, points, Gaussians, cameras, instances, semantics, and volumes. |

Other root records cover images and sequences, meshes, scans, state and IMU
streams, reconstructions, dense maps, label maps, tensors, NCore, RTMV, HLoc,
and COLMAP database companions. The exact 90-record catalog and its scale,
coordinate, and refusal rules are in
[`representation_normalization.md`](docs/representation_normalization.md).

Construct records directly from the root API:

```python
import numpy as np
import sceneio

view = sceneio.ViewInput(
    image=np.zeros((480, 640, 3), dtype=np.uint8),
    name="frame0",
)
pose = sceneio.SE3.from_colmap_world2cam(
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
)
frame = sceneio.FrameMeta(
    scale="arbitrary",
    scale_provenance="unknown",
)
```

## Format I/O

<!-- sceneio-inventory-summary:start -->
**Generated registry contract:** SceneIO has **74 built-in formats**: **64**
single-file, **5** directory, and **5** multi-file containers. **74** are readable,
**73** writable, and **74** inspectable; **37** formats expose **43** bounded partial
selectors. **74** provide streaming reads and **71** provide streaming writes. The
values come directly from `CANONICAL_BUILTIN_IDS` and `sceneio.capabilities()`.
<!-- sceneio-inventory-summary:end -->

The root API is the public I/O surface:

```python
import sceneio

record = sceneio.read("asset.glb")
assert isinstance(record, sceneio.SceneGraph)

info = sceneio.inspect("asset.glb")
assert info.format == "glb"

primitive = sceneio.read_partial("asset.glb", primitive_id=0)
sceneio.write(record, "asset-copy.gltf")
```

Readers preserve all semantics represented by their bounded profile. Writers
reject a value when the destination cannot preserve it. Unsupported partial
access raises `FormatError` instead of decoding the whole payload behind the
caller's back.

Specialized typed entry points attach semantics that raw carriers do not infer:

```python
import numpy as np
import sceneio

taxonomy = sceneio.LabelTaxonomy(
    np.array([0, 4], dtype=np.int32),
    ("background", "vehicle"),
    identity="example.taxonomy",
    version="v1",
)
labels = sceneio.SemanticMap(
    np.array([[0, 4], [4, -1]], dtype=np.int32),
    void_id=-1,
    taxonomy=taxonomy,
)
sceneio.write_label_map(labels, "labels.npz")
decoded = sceneio.read_label_map("labels.npz")
```

COLMAP and HLoc pair reads return the same correspondence representation used
by matching contracts:

```python
import sceneio

database = sceneio.read("database.db", format="colmap_db")
graph = database.correspondences
assert isinstance(graph, sceneio.CorrespondenceGraph)

pair = sceneio.read_partial("database.db", pair=(42, 91))
assert isinstance(pair, sceneio.CorrespondenceGraph)
```

All built-ins publish immutable discovery metadata without trial imports or
reads:

```python
import sceneio

capability = sceneio.capabilities("glb")
assert capability.can_read and capability.can_write and capability.can_inspect
assert "primitive_id" in capability.partial_selectors
```

## Coordinates and representation contracts

I/O never silently relabels coordinate systems. Each format declares fixed,
file-declared, unspecified, or not-applicable coordinates. Conversion is an
explicit operation:

```python
import sceneio

record = sceneio.read("trajectory.txt", format="tum")
metadata = sceneio.inspect("trajectory.txt", format="tum")
assert metadata.coordinates == record.coordinates
converted = sceneio.convert_coordinates(record)
```

Every public representation also has a machine-readable normalization
contract:

```python
import sceneio

contract = sceneio.representation_contract(sceneio.GaussianCloud)
assert contract.profile.id == "gaussian_cloud"
assert contract.coordinates == "record_declared"
```

The generic public-type catalog covers representations, descriptors,
protocols, procedure values, vocabularies, errors, and wire records:

```python
import sceneio

contract = sceneio.public_type_contract(sceneio.Point3DRecord)
assert contract.kind == "wire_record"
catalog = sceneio.contracts.catalog_dict()
```

See [`coordinate_conventions.md`](docs/coordinate_conventions.md),
[`representation_normalization.md`](docs/representation_normalization.md), and
the generated [`public_type_contracts.md`](docs/public_type_contracts.md).

## Procedure contracts

`sceneio.mapping` defines `Mapper`, `MapperTraits`, `MappingOptions`, and
`MappingResult`. `sceneio.matching` defines `FeatureExtractor`, `PairMatcher`,
`GeometricVerifier`, their traits, and options. The namespaces do not import
one another.

`sceneio.testing` provides conformance checks for backend implementations:

```python
from sceneio.mapping import MapperTraits, MappingResult
from sceneio.testing import assert_mapper_conformance

class MyMapper:
    def traits(self) -> MapperTraits: ...
    def map(self, views, *, correspondences=None, options=None) -> MappingResult: ...

assert_mapper_conformance(MyMapper())
```

Contract violations raise `ContractViolation`; format detection, decoding,
encoding, and representability failures raise `FormatError`. Both derive from
`SceneIoError`.

## Development

```powershell
uv sync --extra dev --extra test
uv run ruff check .
uv run python -m pytest -q
uv run python tools/documentation_contract.py --check
```

The [`documentation index`](docs/README.md) distinguishes live contracts from
historical implementation evidence. Authoritative entry points are:

- [`docs/format_coverage.md`](docs/format_coverage.md) — exact live codec and
  provider coverage;
- [`docs/coordinate_conventions.md`](docs/coordinate_conventions.md) — axes,
  frames, pixel centers, transform directions, and conversions;
- [`docs/representation_normalization.md`](docs/representation_normalization.md)
  — the exact in-memory representation catalog;
- [`docs/public_type_contracts.md`](docs/public_type_contracts.md) — generated
  contracts for every public class identity and payload kind;
- [`docs/core_architecture.md`](docs/core_architecture.md) — current ownership
  and extension boundaries;
- [`docs/colmap_adapters.md`](docs/colmap_adapters.md) and
  [`docs/colmap_ecosystem_coverage.md`](docs/colmap_ecosystem_coverage.md) —
  repository-owned COLMAP workflow and persisted-I/O contracts;
- [`docs/public_fixture_corpus.md`](docs/public_fixture_corpus.md) — licensed,
  content-pinned interoperability evidence;
- [`docs/coverage_roadmap.md`](docs/coverage_roadmap.md) — deliberate limits
  and future policy;
- [`docs/plans/representation_consolidation_2026-08-30.md`](docs/plans/representation_consolidation_2026-08-30.md)
  — completed 0.4 representation consolidation record;
- [`docs/releases/v0.4.0.md`](docs/releases/v0.4.0.md) — the 0.4 contract reset.

Historical engineering records remain available for provenance:

- [`docs/plans/completed/public_type_contract_standardization_2026-08-29.md`](docs/plans/completed/public_type_contract_standardization_2026-08-29.md)
- [`docs/repository_organization_plan.md`](docs/repository_organization_plan.md)
- [`docs/next_stage_implementation_checklist.md`](docs/next_stage_implementation_checklist.md)
- [`docs/format_gap_implementation_plan.md`](docs/format_gap_implementation_plan.md)
- [`docs/remaining_3dcv_profile_checklist.md`](docs/remaining_3dcv_profile_checklist.md)
- [`docs/plans/completed/README.md`](docs/plans/completed/README.md)
