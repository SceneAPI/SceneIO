# Representation consolidation implementation plan

- **Status:** proposed and ready for implementation as of 2026-08-30.
- **Baseline:** the SceneIO 0.3 public surface in the current worktree: 103
  contracted data representations, 144 total public class identities, 26
  built-in payload kinds, 74 built-in codecs, and 5 existing bidirectional
  loaded-to-neutral adapter pairs.
- **Purpose:** reduce duplicate semantic ownership across loaded, neutral,
  COLMAP-wire, and scene representations without weakening storage fidelity or
  changing existing public behavior.
- **Compatibility posture:** treat the current API as stable. Consolidation is
  additive in this program. Existing classes, import paths, constructors,
  fields, defaults, reprs, pickle behavior, codec return classes, writer input
  contracts, errors, and wire bytes remain unchanged.
- **Primary authorities:**
  [`canonicalization.md`](../canonicalization.md) owns conversion and refusal
  behavior,
  [`representation_normalization.md`](../representation_normalization.md) owns
  numeric normalization and coordinate semantics, and
  [`public_type_contracts.md`](../public_type_contracts.md) owns public identity
  and relationship coverage.

## 1. Outcome and finite boundary

This program ends with a small, explicit conversion graph between public
representations that describe the same semantic object at different fidelity
levels. It does **not** attempt to force all values into one universal record.

The target outcome is:

1. Every supported representation conversion has one implementation owner,
   one machine-readable relationship, one documented fidelity boundary, and
   focused executable evidence.
2. Format-specific classes retain only format-specific or storage-specific
   responsibilities. Shared transform, calibration, feature, correspondence,
   and scene meaning belongs to an existing canonical record.
3. Generic `sceneio.read()` continues to return storage-faithful records.
   Projection remains an explicit caller action through `sceneio.canonical`.
4. Missing context, unrepresentable meaning, and metadata loss remain three
   different outcomes. Missing geometric context always refuses; omittable
   metadata requires explicit loss acknowledgement; exact conversions need
   neither.
5. The number of public representations does not need to decrease. A wire view
   and a semantic view may remain separate indefinitely when the boundary
   protects round-trip fidelity.

### Included consolidation seams

- COLMAP `SimilarityTransform` and neutral `sceneio.data.Sim3`.
- COLMAP `MappingCamera` and neutral `sceneio.data.CameraIntrinsics`.
- COLMAP `SiftFeatures`, loaded `sceneio.FeatureSet`, and neutral
  `sceneio.data.FeatureSet`.
- COLMAP `NamedMatches` and neutral `sceneio.data.PairCorrespondences`.
- Compatibility `sceneio.MeshScene` and rich `sceneio.SceneGraph` on the exact
  mutually representable mesh-only subset.
- One internal adapter manifest from which public `adapts_to` relationships and
  the documentation conversion matrix are derived.

### Explicit non-goals

- Do not alias two classes merely because they share a short name.
- Do not replace `MappingInput`, `Reconstruction`, `ColmapDatabase`, or an MVS
  workspace with a generic bag of neutral records.
- Do not merge `PointCloud`, `PointScan`, and `ScanSet`; their current
  composition preserves stored rows, invalid states, scan metadata, and
  aggregation correctly.
- Do not merge `Mask`, `SemanticMap`, `InstanceMap`, and `PanopticMap`; their
  element domains and semantic invariants are intentionally distinct.
- Do not merge NCore schema records with NCore payload records.
- Do not make `allow_loss=True` the default and do not let it authorize a
  coordinate, unit, frame, or transform-direction guess.
- Do not add a magic `canonicalize(value)` dispatcher. Several conversions
  require caller-owned context that a generic function could only guess.
- Do not change any built-in codec's `record`, `datatype`, `payload_kind`,
  detection behavior, or generic read result.
- Do not deprecate a wire/storage class merely because an adapter exists.

## 2. Current evidence and consolidation decisions

SceneIO already establishes the correct high-level distinction: loaded records
preserve source facts while `sceneio.data` supplies the smaller procedure
floor. The existing camera, feature, match, depth, and posed-view pairs are
therefore not duplicate identities; their checked adapters are the model for
this program.

| Candidate | Shared meaning | Non-shared facts | Decision |
|---|---|---|---|
| `sceneio.colmap.SimilarityTransform` / `sceneio.data.Sim3` | Positive scale, proper rotation, translation | WXYZ quaternion sample/sign versus rotation matrix; neutral convention tag | Add strict bidirectional adapters; keep both classes |
| `sceneio.colmap.MappingCamera` / `sceneio.data.CameraIntrinsics` | Camera model, dimensions, ordered parameters | Mapping camera id and prior-focal flag | Reuse one camera-field conversion policy; require context/loss acknowledgement |
| `sceneio.colmap.SiftFeatures` / `sceneio.FeatureSet` / `sceneio.data.FeatureSet` | Pixel keypoints and descriptors | SIFT fixes 4 columns, uint8, 128 descriptors; neutral features retain only XY | Use loaded `FeatureSet` as the exact SIFT bridge, then the existing neutral adapter for the smaller subset |
| `sceneio.colmap.NamedMatches` / `sceneio.data.PairCorrespondences` | Ordered endpoint pair and indexed correspondences | Wire endpoint names; neutral optional scores and geometry | Add ordered pair-map adapters with strict refusal for unsupported neutral fields |
| `sceneio.MeshScene` / `sceneio.SceneGraph` | Mesh payloads, hierarchy, local transforms, names, materials | Rich scene payload kinds, visibility, purpose, semantics, instances, assets, time, and stage metadata | Add a strict mesh-only projection; keep both public scene models |

### Representations investigated but not selected

| Representations | Reason not to consolidate |
|---|---|
| Existing native/neutral camera, feature, match, depth, and posed-view pairs | They already share semantic authority through checked adapters while preserving distinct storage and procedure roles |
| `PointCloud`, `PointScan`, `ScanSet` | `PointScan` contains a point cloud plus stored-row/scan facts; `ScanSet` is an ordered aggregate |
| `DepthMap`, `Pointmap`, `RayMap`, `NormalMap`, `FlowField` | Similar array shapes do not imply the same physical quantity, coordinate rule, or conversion |
| `Mask`, `SemanticMap`, `InstanceMap`, `PanopticMap` | Separate classes prevent binary, class-label, instance-id, and packed panoptic values from being confused |
| NCore schema/payload classes | Metadata declarations and materialized component values have different lifetime and loading behavior |
| `ColmapMvsWorkspace`, `LegacyMvsWorkspace` | They coordinate different on-disk ecosystems and expose different valid operations |
| `WorkspaceInspection`, `WorkspaceValidation` | They are related result views, not interchangeable representations |

## 3. Design principles

1. **One semantic authority, multiple fidelity views.** Consolidate validation,
   conversion, and relationships before considering identity removal.
2. **Explicit direction and context.** Function names identify source and
   target. Required convention, id, scale, frame, and name mappings are keyword
   arguments rather than inferred defaults.
3. **Exact by default.** An adapter either preserves the declared shared
   contract or refuses. Only named, storage-only omissions may be acknowledged
   with `allow_loss=True`.
4. **No semantic mega-type.** A type that represents every camera, map, scene,
   or match mode through optional fields would make invalid states easier to
   construct and would move validation into scattered branches.
5. **Wire views stay close to codecs.** Parsing and writing retain their
   current wire-specific classes. Canonical adapters do not become hidden
   codec steps.
6. **Relations are generated from one adapter manifest.** Production code must
   not maintain a function list, contract edge list, and documentation table
   independently.
7. **Provider-independent conversion.** In-memory conversion must not serialize
   through a temporary file or import an optional codec provider.
8. **Owned results.** Converted arrays and nested records have explicit
   ownership and remain valid after the source name, mapped file, or provider
   handle is released.
9. **Stable APIs change additively.** Guidance from
   [AIP-180](https://google.aip.dev/180) and
   [AIP-181](https://google.aip.dev/181) is adapted to this local Python SDK:
   add adapters and relationships; do not change stable classes in place.
10. **Removal is a separately approved versioning event.** Any future identity,
    constructor, or return-type removal follows
    [AIP-185](https://google.aip.dev/185), not this implementation program.

## 4. API review findings and required corrections

The AIP references below are compatibility guidance adapted to a stable local
SDK. HTTP resources, pagination, authentication, and retry semantics are not
applicable.

| Finding | Evidence and risk | Basis | Compatibility-safe correction |
|---|---|---|---|
| Adapter relationships are maintained as a one-target dictionary | `contracts.manifest._representation_entries()` can express only one `adapts_to` target per representation | [AIP-180](https://google.aip.dev/180), [AIP-202](https://google.aip.dev/202) | Replace the hand table with a directional internal adapter manifest that supports multiple targets without altering `ContractRelation` |
| Sim3 meaning has two validators and no declared bridge | COLMAP stores WXYZ quaternion plus scale/translation; neutral `Sim3` stores rotation plus convention | [AIP-190](https://google.aip.dev/190), [AIP-192](https://google.aip.dev/192) | Add explicitly named conversion functions and reciprocal catalog relationships; never infer direction |
| COLMAP leaf records re-state camera/feature/match semantics | Mapping and text records validate shapes and camera models independently of existing native/neutral records | [AIP-190](https://google.aip.dev/190), [AIP-180](https://google.aip.dev/180) | Route shared conversion math through the canonical layer while retaining wire-specific constraints and classes |
| `MeshScene` and `SceneGraph` are documented as projection-related but expose no in-memory projection API | Users must reassemble a scene or round-trip through USD to cross the boundary | [AIP-192](https://google.aip.dev/192), [AIP-180](https://google.aip.dev/180) | Add strict provider-free conversion for the exact mesh-only subset; preserve both read paths |
| Removing the apparent duplicates would change stable constructors and read outcomes | Existing snapshots and codec tests contract those identities and shapes | [AIP-180](https://google.aip.dev/180), [AIP-185](https://google.aip.dev/185) | Make removal explicitly out of scope; record a future major-version decision gate instead |

## 5. Target architecture

```text
format/wire view                 checked canonical layer       semantic/storage authority

colmap.SimilarityTransform  ──>  sceneio.canonical  ─────────> data.Sim3
colmap.MappingCamera        ──>  sceneio.canonical  ─────────> data.CameraIntrinsics
colmap.SiftFeatures         ──>  sceneio.canonical  ─────────> sceneio.FeatureSet
                                                              └─> data.FeatureSet (existing)
tuple[colmap.NamedMatches]  ──>  sceneio.canonical  ─────────> map[pair, PairCorrespondences]
sceneio.MeshScene           <──  sceneio.canonical  ────────> sceneio.SceneGraph
```

The implementation ownership is:

```text
src/sceneio/contracts/_adapters.py
  stdlib-only directional adapter definitions and validation

src/sceneio/contracts/manifest.py
  derives public adapts_to relations from _adapters.py

src/sceneio/canonical.py
  explicit runtime conversion implementations; imports NumPy/_core lazily

src/sceneio/data/transforms.py
  Sim3-owned quaternion/matrix conversion behavior

tools/documentation_contract.py
  renders the current adapter matrix from _adapters.py
```

Dependency direction remains:

```text
contracts.model <- contracts._adapters <- contracts.manifest/registry/docs

sceneio.canonical -> sceneio.data + sceneio._core + selected public wire types
```

`contracts._adapters` must not import NumPy, `_core`, `sceneio.canonical`, a
provider, or a runtime public class. Operation paths and representation paths
are strings. Runtime function resolution is tested only when the caller imports
`sceneio.canonical`.

## 6. Internal adapter manifest

Add one frozen internal `_AdapterDefinition` for each **direction**, because
context and fidelity may differ between the forward and inverse operations.

| Field | Required meaning |
|---|---|
| `id` | Stable lower-snake-case internal identity |
| `source` | Canonical public representation path |
| `target` | Canonical public representation path; an operation may convert an ordered collection of that representation |
| `operation` | Exact `sceneio.canonical` function path |
| `inverse` | Opposite adapter id, or `None` for a one-way projection |
| `fidelity` | `exact`, `conditional`, or `loss_acknowledged` |
| `required_context` | Ordered keyword names callers must provide |
| `refusal` | Concise statement of non-representable meaning |
| `evidence` | Exact pytest node ids proving the direction |

Construction must reject:

- duplicate ids or duplicate `(source, target, operation)` tuples;
- unknown source or target representation paths;
- a missing operation, malformed function path, or operation absent from
  `sceneio.canonical.__all__` during runtime validation;
- a non-reciprocal inverse declaration;
- `exact` fidelity with `allow_loss` context;
- empty refusal/evidence or evidence outside the repository;
- an adapter relation that is not reflected in both public type contracts when
  an inverse exists.

The manifest is metadata only. It does not dispatch conversions dynamically.
Callers continue to select an explicit function so required context remains
visible at the call site.

## 7. Additive runtime API

Signatures below are the intended review surface. Type spellings may be
normalized during implementation, but names, direction, required context, and
default-loss policy must not drift without updating this plan first.

### Sim3

```text
sceneio.data.Sim3.from_quaternion_wxyz(
    scale,
    quaternion_wxyz,
    translation,
    *,
    convention,
) -> Sim3

sim3.to_quaternion_wxyz() -> tuple[float, np.ndarray, np.ndarray]

sceneio.canonical.sim3_from_colmap(
    value,
    *,
    convention,
) -> sceneio.data.Sim3

sceneio.canonical.similarity_transform_from_neutral(
    value,
    *,
    convention,
) -> sceneio.colmap.SimilarityTransform
```

Rules:

- `convention` is required in both directions because the COLMAP text record
  has no direction tag.
- Neutral-to-wire conversion refuses when `value.convention != convention`;
  callers explicitly invert or rebuild the transform first.
- Quaternion-to-matrix conversion preserves mathematical rotation, not the
  original quaternion sign bit. Exact wire re-emission uses the original
  `SimilarityTransform` record.
- Matrix-to-quaternion output is deterministic and uses the existing
  canonical sign policy.

### Mapping cameras

```text
sceneio.canonical.camera_intrinsics_from_mapping(
    value,
    *,
    allow_loss=False,
) -> sceneio.data.CameraIntrinsics

sceneio.canonical.mapping_camera_from_neutral(
    value,
    *,
    camera_id,
    has_prior_focal_length=False,
) -> sceneio.colmap.MappingCamera
```

Rules:

- Camera model ids, names, parameter counts, and order continue to come only
  from `sceneio._camera_models`.
- `camera_id` is collection identity and is supplied on materialization.
- Projecting a true `has_prior_focal_length` flag requires
  `allow_loss=True`; the neutral intrinsic contract has no equivalent field.
- Existing native-camera adapters reuse the same private field-to-intrinsics
  helper so model validation has one owner.

### SIFT feature text

```text
sceneio.canonical.feature_set_from_sift(
    value,
    *,
    image_id=0,
    image_name="image",
    camera_id=0,
    image_size=(1, 1),
) -> sceneio.FeatureSet

sceneio.canonical.sift_features_from_native(
    value,
    *,
    allow_loss=False,
) -> sceneio.colmap.SiftFeatures
```

Rules:

- SIFT-to-native is exact for keypoint columns and descriptor values. It sets
  the first-pixel center and supplied collection metadata explicitly.
- Native-to-SIFT requires exactly four float32 keypoint columns and a present
  `(N, 128)` uint8 descriptor matrix.
- Scores, colors, quality, time, extractor metadata, dimensions, ids, and
  names are refused unless `allow_loss=True` acknowledges each omitted
  storage-only field.
- Neutral `FeatureSet` is not used as the exact intermediate because its Nx2
  keypoints intentionally omit SIFT scale and orientation. Callers may then use
  the existing `feature_set_from_native(..., allow_loss=True)` projection.

### Named matches

```text
sceneio.canonical.correspondence_pairs_from_named(
    values,
) -> Mapping[tuple[str, str], sceneio.data.PairCorrespondences]

sceneio.canonical.named_matches_from_pairs(
    values,
    *,
    allow_loss=False,
) -> tuple[sceneio.colmap.NamedMatches, ...]
```

Rules:

- Pair order and correspondence column order are preserved; endpoint reversal
  is never performed implicitly.
- Duplicate or self pairs refuse.
- Wire-to-neutral produces indexed pairs with no invented scores or geometry.
- Neutral-to-wire refuses coordinate-mode pairs. Scores and geometry require
  explicit loss acknowledgement because the text format cannot carry them.
- Output ordering is insertion order from the supplied mapping and is tested.

### Mesh scenes

```text
sceneio.canonical.scene_graph_from_mesh_scene(value) -> sceneio.SceneGraph
sceneio.canonical.mesh_scene_from_scene_graph(value) -> sceneio.MeshScene
```

The first implementation ships **without** `allow_loss`. It supports only a
proven exact subset and refuses everything else. Before coding either function,
RC4 must publish the field-level correspondence table described below.

## 8. Fidelity and refusal policy

### Fidelity vocabulary

| Fidelity | Meaning |
|---|---|
| `exact` | Every declared source fact has a target representation and round-trips semantically |
| `conditional` | Exact only when stated shape, dtype, profile, convention, or metadata predicates hold; otherwise refuses |
| `loss_acknowledged` | Shared meaning is preserved, but named storage-only facts may be omitted only with `allow_loss=True` |

No adapter may call a conversion `lossless` merely because values are
numerically close. Dtype, ordering, presence, duplicate policy, quaternion
sign policy, frame, scale, units, and ownership are part of fidelity.

### Refusal categories

Tests and docs use stable categories even when full messages remain
human-oriented:

- `missing_context`: convention, id/name map, scale, frame, or calibration is
  required and absent;
- `semantic_mismatch`: source meaning cannot be represented by the target;
- `profile_mismatch`: source shape/dtype/profile is outside the adapter's
  bounded subset;
- `metadata_loss`: named storage-only facts require acknowledgement;
- `range_or_dtype`: target carrier cannot represent the numeric values;
- `invalid_source`: the input violates its own public representation contract.

Use existing exception classes. Do not introduce a new exception hierarchy in
this program. `TypeError` remains for wrong object types; `ContractViolation`
remains the canonical semantic/refusal error; format-specific readers and
writers retain their existing format errors.

## 9. Work breakdown and dependency order

Each RC unit is independently reviewable and leaves the tree green. No later
unit starts while an earlier unit has unresolved compatibility or import
failures.

```text
RC0 adapter authority
 ├─> RC1 Sim3
 ├─> RC2 mapping cameras
 ├─> RC3 SIFT and named matches
 └─> RC4 MeshScene/SceneGraph characterization and projection

RC1 + RC2 + RC3 + RC4 -> RC5 generated contracts/docs -> RC6 qualification
```

### RC0 — establish one adapter authority without behavior change

**Owned files**

- new `src/sceneio/contracts/_adapters.py`
- `src/sceneio/contracts/manifest.py`
- `src/sceneio/contracts/registry.py`
- `tests/test_public_type_contracts.py`
- new `tests/test_representation_consolidation.py`

**Work**

- Encode the current five bidirectional pairs as ten directional definitions.
- Derive every existing `adapts_to` relation from the adapter definitions.
- Generalize relation generation from one target to ordered multiple targets.
- Validate ids, paths, inverse symmetry, evidence, and lazy operation strings.
- Add a runtime audit that imports `sceneio.canonical` only on demand and proves
  every operation exists in `canonical.__all__`.
- Freeze current root exports, constructors, repr/pickle outcomes, and the 74
  generic codec return identities before adding new adapters.

**Exit gate**

- The serialized public catalog is byte-identical to the pre-RC0 baseline.
- Plain `import sceneio` and `import sceneio.contracts` remain NumPy/core/provider
  lazy.
- Removing any current adapter function or reciprocal relation fails a focused
  contract test.

### RC1 — consolidate Sim3 conversion policy

**Owned files**

- `src/sceneio/data/transforms.py`
- `src/sceneio/canonical.py`
- `src/sceneio/contracts/_adapters.py`
- `tests/test_data_transforms.py`
- `tests/test_representation_consolidation.py`
- `tests/test_colmap_ecosystem_adapters.py`

**Work**

- Put quaternion/matrix conversion on `Sim3` using the same validation and
  deterministic sign policy already used by `SE3`.
- Add the two explicit canonical functions and lazy namespace exports.
- Require convention agreement in both directions.
- Add reciprocal adapter definitions and `adapts_to` relations.
- Keep `read_similarity_transform` and `write_similarity_transform` signatures,
  return type, accepted type, formatting, and precision-17 bytes unchanged.

**Exit gate**

- Identity, nontrivial rotation, near-180-degree rotation, negative input
  quaternion sign, arbitrary positive scale, and translation round-trip within
  the existing float64 tolerance.
- Missing/wrong convention and malformed types refuse before producing a
  target value.
- Rewriting the original wire record remains byte-identical.

### RC2 — consolidate camera field conversion

**Owned files**

- `src/sceneio/canonical.py`
- `src/sceneio/colmap/models.py` only if shared validation can replace copied
  logic without changing exceptions/messages
- `src/sceneio/contracts/_adapters.py`
- `tests/test_canonicalization.py`
- `tests/test_representation_consolidation.py`
- camera-manifest parity tests

**Work**

- Extract one private field-to-`CameraIntrinsics` conversion that accepts model
  id, dimensions, and ordered parameters.
- Route both `camera_intrinsics_from_native` and the new mapping-camera adapter
  through that helper.
- Add neutral-to-mapping materialization with explicit id and prior flag.
- Exercise all camera models from the single camera-model manifest.
- Preserve current `MappingCamera` constructor validation and error prefixes.

**Exit gate**

- All camera models round-trip model id, dimensions, parameter dtype/order, and
  values exactly.
- Prior-focal loss refuses by default and succeeds only when acknowledged.
- The existing native camera adapter behavior and camera-manifest Python/C++
  parity remain unchanged.

### RC3 — consolidate SIFT and named-match leaf semantics

**Owned files**

- `src/sceneio/canonical.py`
- `src/sceneio/contracts/_adapters.py`
- `tests/test_representation_consolidation.py`
- `tests/test_colmap_ecosystem_adapters.py`
- feature/match record tests

**Work**

- Add exact SIFT-to-native feature materialization.
- Add conditional native-to-SIFT projection with enumerated loss checks.
- Add named-match sequence to ordered neutral pair-map conversion and inverse.
- Reuse existing native/neutral feature and match helpers where their contracts
  overlap; do not copy dtype/range policy into the COLMAP module.
- Add size/ownership tests proving conversion allocates only the owned target
  payload and does not retain a mapped source file accidentally.
- Do not add a `MappingInput` aggregate projection. Its version, time ids,
  camera links, configuration codes, and relative poses have no single current
  neutral aggregate that preserves them all.

**Exit gate**

- SIFT keypoints and descriptors round-trip exactly on the bounded profile.
- Every omitted native feature field is either default or named in the loss
  refusal.
- Named pair order, endpoint order, indices, empty pairs, and duplicate
  refusal are exact.
- Existing SIFT and feature-match wire bytes and reader result identities are
  unchanged.

### RC4 — characterize and implement the scene projection

**Owned files**

- `src/sceneio/canonical.py`
- `src/sceneio/contracts/_adapters.py`
- `src/cpp/records/mesh_scene.*` and `scene_graph.*` only if a shared native
  helper is required for correct ownership/performance
- `tests/test_representation_consolidation.py`
- `tests/records/test_mesh_scene.py`
- `tests/records/test_scene_graph.py`
- `tests/codecs/test_usd_scene.py`
- glTF/USD compatibility snapshots

**Characterization gate before implementation**

Create and review a field-level table covering:

- primitive grouping and mesh indices;
- node parent/child topology and root ordering;
- local transforms and reset-stack semantics;
- mesh/node/scene names and default-scene/default-prim meaning;
- material sets and per-mesh material associations;
- up axis, coordinate frame, and meters-per-unit;
- visibility, purpose, semantic labels/taxonomies;
- point, Gaussian, camera, volume, instance, and external-asset payloads;
- selected time and time-range metadata;
- empty scenes, multiple scenes, and multiple primitives per mesh.

Every row must be classified as exact, conditionally exact, unrepresentable,
or requiring a separately approved semantic conversion. Do not implement the
adapter while any field remains “probably equivalent.”

**Work after characterization passes**

- Implement provider-free owned conversion for the exact subset.
- Preserve node and child order; never flatten or synthesize hierarchy merely
  to make conversion succeed.
- Refuse rich payload kinds and metadata with no `MeshScene` carrier.
- Refuse coordinate/unit changes rather than applying an implicit transform.
- Add the reciprocal relation only if both directions have a non-empty exact
  subset. Otherwise publish only the direction proved by tests.
- Keep generic USD/glTF reads, `read_scene`, and both writer surfaces unchanged.

**Exit gate**

- Exact-subset conversion round-trips all representable fields and owns its
  nested records/arrays.
- Every rich-only field causes a targeted refusal.
- No adapter imports TinyUSDZ or serializes through USD/glTF.
- Legacy USD/glTF bytes, generic read type, rich read type, and inspection
  behavior remain unchanged.

**Stop condition**

If exact conversion requires topology mutation, provider round-tripping, or
unbounded payload copying that exceeds the existing record ownership model,
stop RC4 and document the types as related but deliberately non-adaptable. Do
not weaken fidelity to complete the matrix.

### RC5 — generate relationships and documentation

**Owned files**

- `tools/documentation_contract.py`
- `tests/contracts/documentation_v1.toml`
- `tests/test_documentation_consistency.py`
- `docs/canonicalization.md`
- `docs/public_type_contracts.md`
- `docs/colmap_adapters.md`
- `README.md` and `docs/README.md`

**Work**

- Generate the canonical adapter table from the internal manifest, including
  direction, operation, fidelity, required context, and refusal summary.
- Generate `adapts_to` relationships from the same definitions.
- Document why an adapter relation does not claim universal losslessness.
- Add one concise example for Sim3, mapping camera, SIFT, named matches, and
  mesh-scene projection.
- Update deterministic catalog snapshots only for intentional additive
  relations; public representation and type counts remain unchanged.
- Keep historical completed plans immutable.

**Exit gate**

- No hand-maintained adapter row or relationship remains outside the manifest.
- Documentation generation is idempotent and current.
- Every documented operation exists, every operation has exact evidence, and
  every reciprocal relation has an inverse definition.

### RC6 — final compatibility and package qualification

**Owned surface**

- full source tree, package metadata, wheel smoke, release notes, and CI gates

**Work**

- Run focused, complete, import, documentation, dependency, source-closure,
  sdist, and installed-wheel validation.
- Compare the complete existing public API and codec capability snapshots.
- Verify optional provider availability cannot change adapter metadata.
- Run Windows and non-Windows native/provider lanes affected by the scene
  projection.
- Record exact test counts, skips, artifact hashes, and environment-dependent
  exclusions before moving this plan to `docs/plans/completed/`.

**Exit gate**

- All tests and documentation checks pass.
- Source and installed wheel expose the same adapter functions and relations.
- No existing public identity, constructor, repr, pickle outcome, generic read
  result, writer contract, exception class, or wire byte snapshot changed.
- The plan is archived only after the implementation and release-facing docs
  are complete.

## 10. Verification strategy

### Per-unit focused gate

```powershell
uv run ruff check .
uv run ruff format --check src/sceneio tests tools
uv run python -m pytest -q tests/test_representation_consolidation.py
uv run python -m pytest -q tests/test_canonicalization.py tests/test_data_transforms.py
uv run python -m pytest -q tests/test_public_type_contracts.py tests/test_representation_contracts.py
uv run python -m pytest -q tests/test_colmap_ecosystem_adapters.py
uv run python tools/documentation_contract.py --check
uv run python -m pytest -q tests/test_documentation_consistency.py tests/test_import_guards.py
```

RC4 additionally runs:

```powershell
uv run python -m pytest -q tests/records/test_mesh_scene.py tests/records/test_scene_graph.py
uv run python -m pytest -q tests/codecs/test_usd.py tests/codecs/test_usd_scene.py
uv run python -m pytest -q tests/codecs/test_gltf.py
```

Use the repository's exact glTF test filename if it differs; do not silently
skip that compatibility family.

### Required negative tests

- Unknown adapter source/target/operation or duplicate adapter id.
- Broken inverse relationship or one-sided public relation.
- Operation omitted from `sceneio.canonical.__all__`.
- Adapter metadata import loading NumPy, `_core`, or an optional provider.
- Missing or unsupported Sim3 convention.
- Non-unit quaternion, improper rotation, non-positive scale, and wrong dtype.
- Mapping-camera prior flag discarded without acknowledgement.
- SIFT wrong keypoint width, descriptor dimension/dtype, and unacknowledged
  native metadata.
- Named self-pair, duplicate pair, coordinate-mode pair, score/geometry loss,
  and reversed endpoint assumptions.
- Mesh scene with unsupported payload, visibility, purpose, semantics, time,
  units, axis, grouping, root, or material state.
- Converted view retaining a dead mapped file/provider owner accidentally.
- Any change to existing generic read return classes or writer accepted types.

### Final gate

```powershell
uv run ruff check .
uv run python tools/documentation_contract.py --check
uv run python -m pytest -q
uv pip check
git diff --check
```

The package gate must additionally build an sdist, build the platform wheel
from that exact sdist, install it into a clean CPython 3.12 environment with
base dependencies, and run `python -m sceneio._wheel_smoke` plus the focused
adapter tests against the installed package rather than the source tree.

## 11. Compatibility and deprecation policy

The following are prohibited in this program:

- replacing a public class with an alias to a different class object;
- changing dataclass or native constructor fields/defaults;
- changing `__module__`, `__qualname__`, repr, equality, copy, or pickle policy;
- changing a generic reader's output class;
- making a writer silently accept a broader semantic profile;
- changing error classes or stable message prefixes;
- moving public import paths or eagerly importing `canonical`;
- marking a class deprecated solely because its semantic projection exists.

A future deprecation proposal may be opened only when all of these are true:

1. A replacement adapter has shipped for at least one release and is documented
   at every old entry point.
2. The replacement preserves every required contract field or the proposal
   proves why the old representation adds no remaining fidelity.
3. Installed-wheel telemetry or repository call-site evidence shows the old
   type can be retired; absence of internal calls alone is insufficient.
4. A migration guide covers construction, reading, writing, type checks,
   serialization, and errors.
5. Removal is approved for a major API version and the old version remains
   available for its documented compatibility window.

Likely outcome: `SimilarityTransform`, `SiftFeatures`, `NamedMatches`,
`MappingCamera`, and `MeshScene` remain as useful wire/storage views even after
semantic consolidation. This plan does not assume eventual deletion.

## 12. Documentation and evidence ownership

- `docs/canonicalization.md` becomes the current human conversion matrix and
  refusal guide.
- `docs/public_type_contracts.md` remains the exhaustive identity and relation
  view; it does not copy conversion implementation prose.
- `docs/representation_normalization.md` remains authoritative for units,
  coordinate frames, scale, and normalization profiles.
- `docs/colmap_adapters.md` continues to document wire readers/writers and links
  to canonical projections rather than redefining them.
- Format coverage continues to describe codec behavior; adapters must not make
  a codec appear to return its projection automatically.
- Exact pytest node ids in `_adapters.py` own executable evidence.
- This plan remains active under `docs/plans/` and moves to
  `docs/plans/completed/` only after RC6.

## 13. Risks and stop conditions

| Risk | Stop condition | Required response |
|---|---|---|
| False consolidation erases source facts | A conversion needs to invent/drop an unacknowledged field | Keep the source representation and add/refine a conditional adapter |
| Generic dispatch hides required context | An implementation selects convention, scale, id, frame, or names from defaults | Remove the dispatch/default and require the context explicitly |
| Adapter metadata becomes an import hub | Importing contracts loads NumPy, `_core`, canonical, or a provider | Move runtime objects back to string paths and lazy validation |
| Stable behavior drifts | Constructor, repr, pickle, read result, writer input, or error snapshot changes | Revert and use an additive function or future major-version proposal |
| Conversion policy is duplicated | One rule must be edited in canonical and a codec/wire model | Move the shared rule to its semantic owner and retain only wire-specific checks |
| Scene projection is only approximately correct | Topology, grouping, materials, units, or metadata cannot round-trip exactly | Narrow the subset or stop RC4; never relabel approximate output as exact |
| `allow_loss` becomes semantic permission | A frame/unit/coordinate mismatch succeeds with the flag | Refuse unconditionally and add the missing explicit geometric conversion |
| New public metadata type escapes the catalog | RC0 exposes an adapter class publicly | Keep it internal or classify it in the public type catalog before exposure |
| Docs imply automatic projection | A format table or example says `read()` returns a neutral/canonical target | Correct the docs and add a regression assertion for the actual return class |

## 14. Completion checklist

- [ ] Existing five adapter pairs are represented by one internal authority
      with no catalog-byte or behavior change in RC0.
- [ ] Adapter metadata supports multiple ordered targets and reciprocal
      direction validation.
- [ ] `SimilarityTransform` and `Sim3` have explicit checked conversion with a
      required convention.
- [ ] Native and mapping cameras share one camera-field conversion policy for
      all camera models.
- [ ] SIFT text converts exactly to the loaded feature carrier and conditionally
      back without hidden metadata loss.
- [ ] Named match blocks convert to/from ordered indexed-pair mappings with
      explicit refusal for unsupported neutral data.
- [ ] The MeshScene/SceneGraph field correspondence is fully classified before
      implementation.
- [ ] Any shipped scene adapter is provider-free, owned, exact on its declared
      subset, and strict elsewhere.
- [ ] Every adapter has an exact function path, fidelity class, context list,
      refusal rule, inverse policy, and executable evidence.
- [ ] Public `adapts_to` relations and docs are generated from the adapter
      authority.
- [ ] No new generic dispatcher or semantic mega-type exists.
- [ ] Existing public identities, aliases, constructors, fields, defaults,
      reprs, pickle outcomes, errors, and lazy imports are unchanged.
- [ ] All 74 generic codec rows retain their result identities and behavior.
- [ ] Focused, full, documentation, dependency, source, sdist, and installed-
      wheel gates pass.
- [ ] Release notes describe additive projection APIs without promising class
      removal.
- [ ] This plan is archived only after all implementation and qualification
      evidence is recorded.

Consolidation is complete when users and maintainers have one authoritative
path for shared meaning and no conversion must be reconstructed ad hoc. It is
not complete merely because two class names were made identical or the public
representation count decreased.
