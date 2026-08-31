# In-memory representation merging plan

- **Status:** implementation and local qualification complete as of
  2026-08-30; hosted cross-platform and sanitizer qualification follows the
  final branch push.
- **Baseline:** SceneIO 0.3.0 at `182c9120`; 103 contracted
  representations, 144 public class identities, 51 representation alias
  paths, and 5 bidirectional loaded/neutral adapter pairs.
- **Owner decision:** SceneIO is a new project. No legacy API, import-path,
  constructor, pickle, or generic-read compatibility is required for this
  consolidation.
- **Release posture:** make one direct contract reset for 0.4.0. Do not ship
  aliases, deprecations, compatibility wrappers, or parallel old/new models.
- **Target:** 90 contracted representations, one public path per
  representation, and no representation adapters. Coordinate, unit, and dtype
  conversions that change values remain explicit operations.
- **Result:** 90 contracted representations, 131 public class identities,
  zero aliases, and zero representation adapters. The complete 74-reader,
  73-writer, and 74-inspector built-in I/O inventory remains available.

This plan supersedes the earlier additive-adapter proposal. That proposal was
appropriate only under a stable-API assumption. The repository currently
labels the surface stable, but the project owner has explicitly removed that
constraint. Following the new/alpha guidance adapted from AIP-181 and AIP-205,
the duplicate shapes should be corrected directly before the API is frozen.

## 1. Reviewed findings

### Required findings

| Finding | Category | Severity / confidence | Evidence | Impact | Direct correction |
|---|---|---|---|---|---|
| Loaded and neutral models duplicate the same domain nouns | design smell: duplicate abstraction | high / high | `src/cpp/records/feature_match.hpp:15` contains `struct FeatureSet {`; `src/sceneio/data/features.py:32` contains `class FeatureSet:` | Callers choose between identities and reconstruct conversion policy | Keep one canonical model per noun and update codecs and procedures to use it directly |
| The adapter layer institutionalizes the duplicate model split | code smell: middle man and shotgun surgery | high / high | `src/sceneio/contracts/manifest.py:199` contains `adapter_targets = {`; `src/sceneio/canonical.py:841` begins the ten adapter exports | A field change crosses the native type, neutral type, adapter, relation table, tests, and docs | Remove representation adapters after callers converge on the canonical models |
| Collection identity is mixed into reusable value objects | design smell: deficient ownership | medium / high | `src/sceneio/colmap/models.py:90` declares `camera_id: int` beside camera intrinsic fields | The same intrinsic calibration needs multiple wrapper types depending on its container | Put ids and source-only flags on `Reconstruction`, `ColmapDatabase`, and `MappingInput`; keep intrinsics identity-free |
| Static mesh scenes have two competing aggregate owners | design smell: duplicate abstraction | high / high | `src/cpp/records/scene_graph.hpp:4` says `compatibility record for static mesh-only callers.` | glTF and USD callers receive different scene models and shared scene logic drifts | Extend `SceneGraph` to cover the complete static mesh subset, migrate codecs, delete `MeshScene` |
| Tracked and untracked point clouds are separate classes despite an additive relationship | design smell: alternative classes with different interfaces | medium / high | `src/cpp/records/point_cloud.hpp:41` contains `struct PointCloud {`; `src/sceneio/data/pointcloud.py:38` contains `class TrackedPointCloud:` | Mapping results cannot flow directly into point-cloud codecs | Add optional track CSR data to `PointCloud` and delete `TrackedPointCloud` |
| Contract metadata overstates stability | API contract defect | high / high | `pyproject.toml:3` is `version = "0.3.0"`; `src/sceneio/contracts/manifest.py:222` sets `stability="stable"` for every representation | The catalog blocks pre-1 design correction and contradicts the owner's release posture | Mark the redesigned representation surface `provisional` until its 1.0 freeze |

The AIP references are design guardrails for the local SDK, not a claim that
SceneIO is a Google resource-oriented API. Resource naming, HTTP methods,
pagination, authentication, retries, and long-running operations are not
applicable.

### Investigated and deliberately not merged

| Types | Decision |
|---|---|
| `PointCloud`, `PointScan`, `ScanSet` | Keep composition. A scan adds stored-row validity, acquisition metadata, and organization; a scan set is an ordered aggregate. Only `TrackedPointCloud` folds into `PointCloud`. |
| `DepthMap`, `Pointmap`, `RayMap`, `NormalMap`, `FlowField` | Keep separate physical quantities and coordinate rules. Similar array shape is not shared meaning. |
| `Mask`, `SemanticMap`, `InstanceMap`, `PanopticMap` | Keep separate element domains and invariants. |
| `Calibration`, `CameraIntrinsics`, `RayMap` | Keep the tagged calibration union and its two genuinely different alternatives. |
| NCore schema and payload records | Keep declaration and materialized-value lifetimes separate. |
| `ColmapMvsWorkspace`, `LegacyMvsWorkspace` | Keep different on-disk ecosystems and operations separate. |
| `WorkspaceInspection`, `WorkspaceValidation` | Keep observation and policy result views separate. |
| `Reconstruction`, `MappingResult`, `SceneGraph` | Keep file reconstruction, procedure result, and general scene aggregates separate; make them compose the same leaf records. |

## 2. Canonical ownership rules

1. **One noun, one public class, one public path.** Public representations live
   at `sceneio.<Type>`.
2. **Values do not own collection identity.** Numeric ids, names, database row
   presence, and source profiles belong to the aggregate or codec provenance
   that defines them.
3. **Canonical records are faithful supersets, not least-common-denominator
   DTOs.** Optional fields are allowed only when absence is a valid state of
   the noun. Mutually exclusive variants remain discriminated.
4. **Codecs translate format syntax, not object models.** Every codec reads and
   writes the canonical record for its payload kind. It may retain private
   provenance needed for exact re-emission, but it may not publish a second
   leaf representation.
5. **Procedures accept the same records that codecs return.** A mapper or
   matcher may validate a narrower profile without requiring a conversion
   class.
6. **Conversions live with the semantic owner.** Quaternion/matrix, coordinate,
   unit, or dtype operations remain explicit methods or `sceneio.coordinates`
   functions. Identity-only representation adapters disappear.
7. **No semantic mega-type.** Types remain separate when merging would combine
   different physical quantities or make invalid states routinely
   representable.

## 3. Merge matrix

The following 13 public representations are removed. No replacement wrapper
types are added, so the contracted representation count falls from 103 to 90.

| Remove | Canonical survivor | Required shape change |
|---|---|---|
| `sceneio.Camera`, `sceneio.colmap.MappingCamera` | `sceneio.CameraIntrinsics` | Move camera ids and prior-focal flags to their owning aggregates |
| `sceneio.data.FeatureSet`, `sceneio.colmap.SiftFeatures` | `sceneio.FeatureSet` | Make the existing loaded record the complete feature contract; derive descriptor dtype/dimension from the array |
| `sceneio.MatchGraph` | `sceneio.CorrespondenceGraph` | Preserve raw and verified pair channels plus optional source metadata in the aggregate |
| `sceneio.colmap.NamedMatches` | `sceneio.PairCorrespondences` within `CorrespondenceGraph` | Use ordered string pair keys; support externally indexed pairs when features are not loaded |
| `sceneio.data.DepthMap` | `sceneio.DepthMap` | Add explicit validity while retaining unit, scale, convention, confidence, and encoding facts |
| `sceneio.data.PosedViewSet` | `sceneio.PosedViewSet` | Store canonical `SE3`, `FrameMeta`, optional images/calibrations, names, and timestamps in one aligned set |
| `sceneio.colmap.SimilarityTransform` | `sceneio.Sim3` | Add deterministic WXYZ construction/materialization and explicit source/target frame context |
| `sceneio.MeshScene` | `sceneio.SceneGraph` | Add mesh grouping and named scene/root sets before migrating glTF and USD |
| `sceneio.data.TrackedPointCloud` | `sceneio.PointCloud` | Add optional per-point track CSR arrays using canonical image identities |
| `sceneio.colmap.MappingImage`, `sceneio.colmap.MappingMatch` | Canonical records composed by `sceneio.colmap.MappingInput` | Replace leaf wrappers with ids/times/names plus `FeatureSet` and `PairCorrespondences` collections |

The retained canonical paths move from `sceneio.data` to the root where
necessary. A move is not an alias: the old path is removed.

## 4. Target record contracts

### 4.1 `CameraIntrinsics`

Canonical fields are `model`, `width`, `height`, and ordered float64 `params`.
`CameraModel` remains the single view of `src/sceneio/_camera_models.py`.

- `Reconstruction` owns aligned `camera_ids` and `cameras`.
- `ColmapDatabase` owns camera ids and prior-focal flags.
- `MappingInput` owns camera ids and references from images.
- `PosedViewSet` and `CameraRig` reference `CameraIntrinsics` without inventing
  ids when the source has none.

The native binding becomes the implementation of `CameraIntrinsics`; the
Python duplicate and `MappingCamera` are deleted.

### 4.2 `FeatureSet`, `PairCorrespondences`, and `CorrespondenceGraph`

`FeatureSet` owns only feature payload meaning:

- float32 keypoints with a declared layout for 2-, 4-, or 6-column profiles;
- optional numeric descriptors, scores, colors, extractor metadata, image
  size, pixel center, and quality;
- `None` means absent and a zero-row array means present-but-empty; redundant
  `has_*` and `*_present` flags are removed when that distinction suffices;
- image id, image name, camera id, and time id move to the containing dataset.

`PairCorrespondences` remains a discriminated indexed/coordinate value. It
owns optional scores and `TwoViewGeometry`. `CorrespondenceGraph` owns:

- canonical image keys and optional `FeatureSet` values;
- ordered pair keys;
- raw and verified correspondence channels without collapsing one into the
  other;
- relative poses and semantic two-view metadata where present;
- explicit deferred index validation when a named-match file has no feature
  payload, rather than pretending indices have already been checked.

COLMAP SQL row presence, application/user version, and exact database profile
remain on `ColmapDatabase` as aggregate provenance. They do not justify a
second `MatchGraph` class.

`MappingInput` is reshaped to compose these canonical values:

```text
MappingInput
  version
  cameras: camera_id -> CameraIntrinsics
  images: image_id/name/camera_id/time_id metadata + FeatureSet
  correspondences: CorrespondenceGraph
```

The SIFT and named-match text readers return `FeatureSet` and
`CorrespondenceGraph` directly. Their writers validate the required SIFT or
indexed-pair profile and refuse values the format cannot encode.

### 4.3 `DepthMap`

The survivor contains:

- float32 `depth`;
- optional boolean `valid`;
- optional raw confidence;
- declared unit and `scale_to_meters`;
- `camera_z`, `ray_distance`, or `unspecified` depth convention;
- source invalid encoding when exact re-emission needs it.

The array remains in declared record units. Procedures request an explicit
normalized view or validate the declared scale; codecs do not silently rescale.
Validity is semantic, while a zero/NaN/negative sentinel is encoding metadata.

### 4.4 `PosedViewSet`

The survivor stores index-aligned canonical values:

- `poses: tuple[SE3, ...]`;
- names and optional timestamps;
- optional image references and calibrations;
- one `FrameMeta` declaring world-frame and scale provenance.

Source quaternion order, pose direction, and axis frame are normalized into
`SE3` during reading. Source encoding needed for exact writing is aggregate
provenance, not a second public posed-view type. `ViewInput` remains separate
because it is a procedure input that requires an image and may contain priors.

### 4.5 `Sim3`

`Sim3` owns positive scale, a proper rotation, translation, and explicit
source/target frame meaning. It gains WXYZ quaternion constructors and
materializers using the same deterministic sign policy as `SE3`.

The COLMAP text API reads and writes `Sim3` directly. Because the text payload
does not declare frame direction, its reader requires source/target context;
it must not guess a pose convention.

### 4.6 `PointCloud`

Add optional track CSR arrays to the existing SoA record:

- preserve float32 or float64 positions without implicit narrowing;
- `track_offsets` aligned to points;
- canonical image keys or an aggregate-owned image-key table;
- non-negative keypoint indices.

No tracks remains the ordinary point-cloud profile. `TrackObservation` may
remain as an ergonomic row view/factory, but `TrackedPointCloud` is deleted.

### 4.7 `SceneGraph`

Before deleting `MeshScene`, extend `SceneGraph` to preserve every static mesh
fact:

- primitive-to-mesh grouping and mesh names;
- node hierarchy, child order, local transforms, and reset-stack state;
- named scene root sets and `default_scene`;
- materials and per-primitive associations;
- stage axis, units, source representation, and default-prim meaning.

glTF, GLB, USD, and USDZ then share `SceneGraph`. Mesh-only writers validate a
mesh-only profile and refuse point, splat, camera, volume, instance, external
asset, semantic, visibility, purpose, or time features they cannot encode.

## 5. Namespace and contract reset

The final namespace rule is intentionally strict:

- `sceneio.<Type>` is the only public path for every representation.
- `sceneio.io` exposes I/O operations and registry objects, not record aliases.
- `sceneio.data` is removed from the public package. Implementation-only Python
  models move under a private module such as `sceneio._data`.
- `sceneio.colmap` and `sceneio.colmap_mvs` retain only source-specific
  aggregates, workspace types, and operations that have no generic semantic
  equivalent.
- `sceneio.canonical` is deleted after its callers disappear.
- `adapts_to` relations are removed from the public contract model and
  manifest.

The public contract schema is bumped from 1 to 2 because `adapts_to` is removed
from the relation vocabulary and root-only representation paths become a
validated rule. Catalog membership changes are captured by the new snapshot;
membership alone is not the reason for a schema bump. Representation entries
use `provisional` through the 0.x line. The 1.0 release process may promote
reviewed entries to `stable`.

No legacy import-path table, unpickler hook, forwarding module, `__getattr__`
fallback, or deprecated constructor is included.

## 6. Implementation sequence

All work lands on one consolidation branch and merges only after the final
contract is complete. Logical commits may be reviewed separately, but the
default branch must never contain a half-migrated public model.

### M0 - freeze semantics, not old identities

**Work**

- Change the affected public contracts to `provisional` and declare the 0.4.0
  contract reset.
- Add characterization fixtures for every format currently producing a type
  in the merge matrix.
- Record semantic round-trips, encoded byte identity where promised, array
  ownership, dtype/layout, conventions, absence-versus-empty behavior, and
  refusal cases.
- Add a test containing the exact 13-name removal set and the 90-representation
  target.

**Exit gate:** characterization tests pass on the unchanged baseline; every
field in a removed type has an assigned target owner or an explicit deletion
rationale.

### M1 - canonical namespace, transforms, and cameras

**Work**

- Establish root exports for canonical semantic records and update internal
  imports away from `sceneio.data`.
- Move `SE3`, `Sim3`, `CameraModel`, `CameraIntrinsics`, `Calibration`, and
  related foundational types to their final implementation modules.
- Merge `Camera` and `MappingCamera` into `CameraIntrinsics`; reshape owning
  aggregates for ids and prior-focal flags.
- Make similarity text I/O use `Sim3`; delete `SimilarityTransform`.

**Exit gate:** all 18 camera models and Sim3 edge cases pass; no duplicate
camera or similarity class remains.

### M2 - features, correspondences, and COLMAP mapping input

**Work**

- Expand native `FeatureSet` to the reviewed canonical schema and migrate
  matching procedure contracts.
- Replace `MatchGraph` with `CorrespondenceGraph` and preserve raw/verified
  channels and exact COLMAP database provenance at the aggregate boundary.
- Reshape `MappingInput` to compose canonical camera, feature, and pair values.
- Migrate SIFT, named-match, HLoc, COLMAP database, and mapping-input codecs.
- Delete the six superseded feature/match leaf classes listed in the matrix.

**Exit gate:** all feature profiles, detector-free pairs, raw and verified DB
rows, absent/empty rows, pair order, and exact-profile writes pass without an
adapter call.

### M3 - depth and posed views

**Work**

- Merge validity and storage conventions into the native `DepthMap`.
- Make mapping inputs and dense-map/workspace codecs use that type directly.
- Redesign native `PosedViewSet` around `SE3`, `FrameMeta`, optional images,
  calibrations, names, and timestamps.
- Migrate pose codecs and procedure call sites; delete both neutral duplicates.

**Exit gate:** scale, invalid-value, camera-z/ray-distance, pose direction,
axes, timestamp, and missing-image cases are explicit and tested.

### M4 - point clouds

**Work**

- Add track CSR storage and validation to `PointCloud`.
- Update `MappingResult.geometry`, reconstruction projections, coordinate
  conversion, and tests to use `PointCloud`.
- Delete `TrackedPointCloud` without weakening ordinary point-codec profiles.

**Exit gate:** tracked clouds flow into supported point writers when their
profile is representable, float64 positions are never silently narrowed, and
writers otherwise issue a precise refusal.

### M5 - scenes

**Work**

- Complete the field-level `MeshScene` to `SceneGraph` ownership table.
- Extend `SceneGraph`, then migrate glTF/GLB and USD/USDZ readers, writers,
  inspectors, partial reads, and snapshots.
- Delete `MeshScene`, its bindings, factories, payload references, and tests
  that assert the old identity.

**Exit gate:** every former `MeshScene` field round-trips through `SceneGraph`;
rich-only features still refuse in narrower writers before output mutation.

### M6 - remove superseded architecture

**Work**

- Delete `sceneio.canonical`, all ten representation adapter functions, the
  `adapter_targets` table, and `adapts_to` contract relations.
- Remove all `sceneio.io.<Type>` and `sceneio.data.<Type>` public aliases and
  the public `sceneio.data` package.
- Bump the contract schema, regenerate the public catalog, and assert 90
  representations and zero aliases.
- Rewrite README, architecture, normalization, format coverage, COLMAP, and
  public-contract docs around one canonical in-memory model. Remove
  `docs/canonicalization.md` after its remaining semantic conversion guidance
  is moved to the owning docs.

**Exit gate:** repository search finds none of the 13 removed class names in
source or current docs, none of the old public paths in tests, and no
representation-adapter concept in the contract model.

### M7 - qualification and release

**Work**

- Run focused record/codec tests after each merge unit and the complete suite
  after M6.
- Build an sdist and platform wheel from the same source, install into a clean
  CPython 3.12 environment, and run wheel smoke plus contract tests against the
  installation.
- Run the affected Windows, Linux, macOS, sanitizer, provider, and optional USD
  lanes.
- Publish 0.4.0 release notes as a clean pre-1 contract reset, not a migration
  guide.

**Exit gate:** source and installed wheel expose exactly the same canonical
types, codec return types, payload relationships, and contract catalog.

## 7. Verification

### Required focused gates

```powershell
uv run ruff check .
uv run python tools/documentation_contract.py --check
uv run python -m pytest -q tests/test_public_type_contracts.py tests/test_representation_contracts.py
uv run python -m pytest -q tests/test_data_calibration.py tests/test_data_transforms.py
uv run python -m pytest -q tests/test_data_features.py tests/test_mapping_contracts.py
uv run python -m pytest -q tests/test_colmap_ecosystem_adapters.py tests/test_colmap_db_contract.py
uv run python -m pytest -q tests/records/test_depth_map.py tests/test_data_views.py
uv run python -m pytest -q tests/records/test_point_cloud.py tests/test_data_pointcloud_priors.py
uv run python -m pytest -q tests/records/test_scene_graph.py tests/codecs/test_gltf.py tests/codecs/test_usd_scene.py
```

Rename focused test files as their old model names disappear; do not retain a
test module solely to preserve legacy terminology.

### Contract gates

- the built-in I/O inventory remains exactly 74 readable, 73 writable, 74
  inspectable, 37 formats with 43 partial selectors, 74 streaming readers, and
  71 streaming writers;
- built-in format ids/order, extensions, container kinds, detection,
  availability, lossy flags, partial selectors, streaming flags, mmap/buffer
  entry points, and optional-provider boundaries match the frozen 0.3
  capability snapshot;
- exactly 90 representation entries;
- zero representation aliases;
- no `adapts_to` relations;
- no canonical path beginning with `sceneio.data.` or `sceneio.io.`;
- every built-in codec's `record` resolves to its canonical payload class;
- every public class has one normalization profile and executable evidence;
- the 13 removed names fail public lookup and import tests;
- plain `import sceneio` remains provider-lazy and does not eagerly load the
  compiled core unless the final root-export design requires it and that cost
  is explicitly accepted.

### Final gate

```powershell
uv run ruff check .
uv run python tools/documentation_contract.py --check
uv run python -m pytest -q
uv pip check
git diff --check
```

Local qualification on 2026-08-30 completed with 5,068 tests passed and 73
expected optional-provider skips. Ruff, the documentation contract, dependency
integrity, the 74-codec benchmark sweep, source/sdist/wheel closure, the
isolated installed-wheel smoke test, and 45 installed-wheel canonical contract
tests also passed.

## 8. Stop conditions

- Stop a proposed merge if it combines different physical quantities,
  coordinate meanings, or lifetimes merely because array shapes match.
- Stop if a canonical type needs many mutually exclusive optional fields; use
  a discriminated semantic type instead.
- Keep format-specific provenance on the owning aggregate when moving it onto
  a leaf would pollute all callers.
- Do not preserve an old class just to make an intermediate commit easier.
  Temporary branch-local scaffolding must be gone before merge.
- Do not weaken byte, dtype, ordering, absence, convention, ownership, or
  refusal tests to reach the target count.
- If a new public representation is genuinely required, review it explicitly
  and adjust the 90-count gate in the same design change; do not add a wrapper
  that recreates a removed duplicate under another name.

## 9. Definition of done

- [x] The 13 superseded representations are deleted.
- [x] Canonical paths are root-only and representation aliases are zero.
- [x] `sceneio.canonical` and `adapts_to` are gone.
- [x] Codecs and procedures consume the same record identities directly.
- [x] Collection ids and format provenance have one explicit aggregate owner.
- [x] The public contract schema is version 2 with 90 provisional
      representations.
- [x] Current docs describe one in-memory model and contain no legacy examples.
- [x] Local focused, full, documentation, dependency, source, sdist, and wheel
      gates pass on the final tree.
- [ ] Hosted Windows, Linux, macOS, sanitizer, provider, and optional USD gates
      pass on the final pushed commit.
- [x] No compatibility shim, deprecated alias, forwarding module, or old-name
      pickle hook remains.

The consolidation is complete when a user can read a value from a codec, pass
that same object to a compatible procedure, and write it again without first
choosing between loaded and neutral identities.
