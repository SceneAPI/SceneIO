# Public type-contract standardization implementation plan

- **Status:** complete and locally verified as of 2026-08-29. This archived
  record describes the implementation and acceptance gates that produced the
  current public type-contract API.
- **Baseline:** SceneIO 0.3.0 on 2026-08-29.
- **Purpose:** give every public SceneIO class identity one explicit,
  machine-readable contract classification while preserving the existing
  representation, wire, format, procedure, schema, import, and extension
  contracts.
- **Compatibility posture:** treat the existing 0.3.0 public surface as stable.
  Implementation is additive; no existing public path, field, constructor,
  format id, logical `DataType` id, exception type, serialization, or default
  behavior may change in place.
- **Current authorities:**
  [`representation_normalization.md`](../../representation_normalization.md) owns
  numeric representation semantics,
  [`format_coverage.md`](../../format_coverage.md) owns live codec capabilities, and
  this plan owns only the standardization dependency order and acceptance
  gates.

## Completion evidence

- The public catalog exhaustively classifies 144 class identities, including
  103 existing representation contracts and the 5 new contract metadata
  classes, while preserving 60 supported alias paths.
- The closed built-in vocabulary classifies all 26 payload kinds used by all
  74 built-in codecs; runtime extension tokens remain open.
- The deterministic catalog is 185,856 UTF-8 bytes with SHA-256
  `4f819cb87393c7b01f8d4129173a3c641f768c2b82624f7592f82a9619ab6358`.
- Focused compatibility, import, registry, documentation, and negative tests;
  the complete test suite; source-closure checks; and isolated sdist/wheel
  installation gates passed.

## 1. Outcome and finite boundary

The program ends with one exhaustive public-type catalog that can answer:

1. What is the canonical public identity of this class, and which import paths
   are aliases?
2. What kind of contract governs it: representation, wire record, descriptor,
   procedure value, protocol, vocabulary, or error?
3. What fields or methods are contractual, including presence, order, units,
   defaults, and refusal behavior?
4. Which existing specialized contract remains authoritative?
5. Which formats, logical data types, operations, or child types relate to it?
6. Which executable tests prove each claim?

The initial runtime census finds **139 unique exported class identities** across
`sceneio`, `sceneio.io`, `sceneio.data`, `sceneio.colmap`,
`sceneio.colmap_mvs`, `sceneio.formats`, `sceneio.mapping`,
`sceneio.matching`, and `sceneio.testing`. Identity deduplication is necessary
because classes such as `Image`, `Inspection`, and `FormatError` have more than
one supported import path.

| Existing classification | Unique identities | Current state |
|---|---:|---|
| Public data representations | 103 | Exactly covered by `REPRESENTATION_CONTRACTS` |
| Other public dataclasses | 24 | Individually validated or documented, but not exhaustively indexed |
| Public Protocols | 6 | Method and behavior contracts are distributed across modules and conformance kits |
| Public exception classes | 5 | Hierarchies exist, but no common machine-readable classification |
| Public enums | 1 | Values are validated separately, but not part of a universal type catalog |

The final count will be generated rather than copied into prose because the new
contract metadata classes are themselves public types and must be classified in
the same change that exposes them.

### Included

- All class identities exported by the nine supported public namespaces.
- The existing 103 normalization/scaling representation contracts.
- The eight cross-repository logical `CORE_DATA_TYPES` entries.
- The 26 payload-kind tokens used by the 74 built-in codecs.
- Public mapping/matching procedure values and Protocols.
- Public wire, checkpoint, image-location, schema, inspection, capability,
  configuration, vocabulary, and error types.
- Canonical paths, aliases, relationships, stability, field/method semantics,
  refusal rules, and executable evidence.
- A deterministic JSON-serializable catalog and generated documentation.

### Explicit non-goals

- Do not add, remove, or reinterpret a codec, record, procedure, or format.
- Do not expand the eight `CORE_DATA_TYPES` merely to accommodate the codec
  registry. Those ids are cross-repository wire identity and require a
  separately reviewed versioned change.
- Do not rename `Codec.datatype`; its constructor, repr, pickle behavior, and
  third-party extension surface are already public.
- Do not require runtime-extension codecs or types owned by another package to
  enter SceneIO's built-in catalog.
- Do not turn every type into a normalization/scaling contract. Protocols,
  errors, schema descriptors, and wire records need different semantics.
- Do not inventory every public function and constant in this program.
  Operations are included only where they define a type's procedure or
  serialization relationships.
- Do not import optional providers, NumPy, or the compiled I/O module merely to
  inspect contract metadata.
- Do not relocate or rewrite the existing representation, coordinate,
  `DataType`, COLMAP database, or codec-capability sources of truth.

## 2. Terms that must remain distinct

| Term | Meaning | Current authority |
|---|---|---|
| Public class identity | One Python class object, independent of how many paths re-export it | Public `__all__` values plus identity comparison |
| Canonical public path | Stable name used as the catalog key | Existing representation key when present; otherwise the shortest documented public path |
| Alias | Another supported path resolving to the exact same class object | Root/namespace re-export contracts |
| Logical `DataType` | Cross-SceneAPI pipeline noun such as `feature_set` or `sparse_model` | `sceneio.formats.CORE_DATA_TYPES` |
| Codec payload kind | Local registry token such as `image`, `mesh`, `tensor_dict`, or `visual_inertial_dataset` | Built-in `Codec.datatype` values |
| Representation contract | Numeric structure, scale, units, coordinates, conversion, and refusal semantics | `REPRESENTATION_CONTRACTS` |
| Public type contract | Common identity, classification, behavior, evidence, and relationship envelope | New catalog defined by this plan |

The current eight logical `DataType` ids and 26 built-in codec payload tokens
overlap only where they truly use the same name. They are not interchangeable
vocabularies. The standardization layer records explicit relationships instead
of assuming name equality.

## 3. Design principles

1. **Standardize the envelope, not the payload semantics.** A representation
   references its existing normalization contract; a wire record describes its
   wire schema; a Protocol describes methods and behavioral invariants.
2. **One identity, many paths.** Catalog entries are keyed by one canonical
   path and contain every supported alias. Duplicate entries for re-exports are
   forbidden.
3. **Existing sources remain authoritative.** The catalog adapts
   `REPRESENTATION_CONTRACTS`, `CORE_DATA_TYPES`, the COLMAP database contract,
   coordinate contracts, and codec capabilities rather than copying their
   fields into a second editable table.
4. **Unknown and absent remain distinct.** Contracts must document optionality,
   default values, sentinels, ordering, units, and whether unknown values are
   preserved or refused.
5. **Compatibility is additive.** Existing names and behavior stay in place;
   clearer names are added as aliases or read-only properties when needed.
6. **Evidence is executable.** Every catalog entry names repository-relative
   tests and the claims those tests prove. Historical prose is supporting
   evidence, not the only acceptance proof.
7. **Metadata lookup stays cheap.** String lookup must not import a provider,
   NumPy, or `sceneio._core`. Class/instance lookup may inspect the object the
   caller already supplied but must not probe providers.
8. **Generated facts replace hand counts.** Counts, kind matrices, payload
   vocabulary, and coverage summaries are rendered from the live catalog.
9. **Extensions remain extensions.** Built-in completeness is closed and
   exact; third-party runtime registrations remain legal and are not silently
   treated as SceneIO-owned contracts.

## 4. API review findings and required corrections

The AIP references below are design guidance adapted to a local stable Python
SDK. Resource naming, HTTP bindings, authorization, pagination, retries, and
long-running operations are not applicable.

| Finding | Evidence and risk | Basis | Compatibility-safe correction |
|---|---|---|---|
| Completeness is scoped by a test-local four-namespace list | `test_representation_contracts.py` proves 103 representations exactly, but public dataclasses in legacy, formats, mapping, matching, and schema modules are outside that census | [AIP-192](https://google.aip.dev/192), [AIP-203](https://google.aip.dev/203) | Add one production-owned public namespace/type manifest and require every exported class identity to be classified exactly once |
| `datatype` names two different concepts | Eight `CORE_DATA_TYPES` are stable cross-repository nouns, while the built-in codec registry currently uses 26 payload tokens | [AIP-190](https://google.aip.dev/190), [AIP-180](https://google.aip.dev/180) | Introduce a separate built-in payload-kind vocabulary and a read-only `payload_kind` alias; preserve `Codec.datatype` unchanged |
| A generic `contract_dict` name would collide | `sceneio.contract_dict()` already serializes the COLMAP database contract | [AIP-190](https://google.aip.dev/190), [AIP-180](https://google.aip.dev/180) | Put deterministic aggregation at `sceneio.contracts.catalog_dict()`; do not replace or overload the root function |
| Re-export aliases can create duplicate or ambiguous contracts | Root, `sceneio.io`, and implementation-module paths frequently identify the same class | [AIP-180](https://google.aip.dev/180), [AIP-190](https://google.aip.dev/190) | Store one canonical path plus exact aliases; allow a bare short name only when it resolves uniquely |
| Evidence has several shapes | Representation entries name files, other contracts use JSON/TOML snapshots, and procedure rules live in conformance tests | [AIP-192](https://google.aip.dev/192) | Normalize evidence references in the envelope while retaining the specialized source object and existing files |
| Contract errors are partly conveyed by message prefixes | Existing compatibility snapshots freeze exception classes and some prefixes; clients should not need to parse arbitrary prose | [AIP-193](https://google.aip.dev/193) | Contract the exception class and stable reason/category; keep human messages actionable but otherwise non-contractual. Do not change existing constructors in this program |
| New metadata could accidentally become an eager dependency hub | The package guarantees leaf imports, lazy NumPy, isolated mapping/matching namespaces, and lazy providers | [AIP-182](https://google.aip.dev/182), [AIP-191](https://google.aip.dev/191) | Keep the model and manifests stdlib-only and string-keyed; enforce import behavior in subprocess tests |
| Field semantics are inconsistent in discoverability, not necessarily behavior | Units, presence, order, defaults, and refusal rules exist across dataclass validation, docstrings, and tests | [AIP-140](https://google.aip.dev/140), [AIP-141](https://google.aip.dev/141), [AIP-142](https://google.aip.dev/142), [AIP-144](https://google.aip.dev/144), [AIP-149](https://google.aip.dev/149) | Give data-bearing non-representation types explicit field contracts without renaming or tightening existing fields |

### Review coverage

| Surface | Status | Plan result |
|---|---|---|
| Resources and collections | Not applicable | Local SDK types and filesystem codecs, not a resource-oriented service |
| Public methods/operations | Reviewed | Lookup, serialization, mapping/matching Protocols, and codec relationships are specified below |
| Fields and data modeling | Reviewed | Presence, units, ordering, defaults, and refusal are required contract fields |
| Compatibility and versioning | Reviewed | Existing API is preserved; the new catalog has an independent schema version |
| Documentation and examples | Reviewed | Generated catalog and hand-written interpretation guide are required |
| Errors | Reviewed | Exception class/category is contractual; free-form message text is not |
| Authentication and retry | Not applicable | No network authorization or automatic retry surface |
| SDK/package surface | Reviewed | Lazy imports, aliases, repr/pickle snapshots, and installed-wheel use are gated |

## 5. Target architecture

```text
src/sceneio/contracts/
  __init__.py        public, lightweight exports
  model.py           frozen stdlib-only envelope/member/evidence models
  manifest.py        canonical paths, aliases, classifications, relationships
  payloads.py        built-in codec payload-kind vocabulary
  registry.py        immutable maps and lookup/canonicalization
  serialization.py   deterministic JSON-safe catalog projection

existing authorities (not moved)
  representations.py             normalization/scaling profiles and entries
  formats/datatypes.py            eight cross-repository logical DataTypes
  formats/registry.py             core artifact-format identity
  colmap_db.py                    COLMAP database schema contract
  coordinates.py                 coordinate value models
  io/_coordinate_manifest.py     74 built-in format coordinate entries
  io/_builtin_manifest.py        built-in format/family/ownership identity
  io/registry.py                 codec definitions and capabilities
```

Dependency direction is strict:

```text
contracts.model
  <- contracts.manifest / contracts.payloads
  <- contracts.registry / contracts.serialization
  <- root lazy forwards and documentation tooling

contracts.* must not import sceneio.io, sceneio.data, mapping, matching,
optional providers, NumPy, or sceneio._core at import time.
```

`contracts.registry` may adapt the string-keyed
`REPRESENTATION_CONTRACTS` mapping because that module is stdlib-only. Runtime
class discovery remains a test concern, not catalog construction behavior.

## 6. Contract taxonomy and schema

### Common envelope

Every public type entry has these machine-readable fields:

| Field | Required meaning |
|---|---|
| `canonical_path` | Unique stable `sceneio...` import path |
| `aliases` | Ordered unique supported paths resolving to the same identity |
| `kind` | One closed contract kind from the table below |
| `stability` | `stable` for existing public behavior; `provisional` only for a newly introduced surface explicitly documented as such |
| `summary` | Client-facing purpose, not an implementation note |
| `members` | Field, method, or enum-value contracts appropriate to the kind |
| `rules` | Invariants not expressible by member metadata |
| `refusal` | Inputs or claims the type deliberately rejects or cannot represent |
| `evidence` | Repository-relative test references plus the claim each proves |
| `relations` | Typed links to public types, logical DataTypes, payload kinds, formats, or operations |
| `specialized_contract` | Optional reference to an existing authoritative representation/schema/coordinate contract |

All sequences are immutable tuples, mappings exposed publicly are
`MappingProxyType`, and construction rejects empty identifiers, duplicate
aliases/members/evidence, unknown kinds, invalid relation targets, and
incompatible kind/member combinations.

### Closed contract kinds

| Kind | Required payload | Initial subjects |
|---|---|---|
| `representation` | Reference to the existing normalization contract plus aliases/relations | Existing 103 entries |
| `wire_record` | Ordered fields, wire/schema id and version, round-trip and rejection rules | `Point3DRecord` |
| `descriptor` | Field presence, mutability, units/defaults, construction rules | Inspection, capability, schema, checkpoint, image-location, and contract-metadata records |
| `procedure_value` | Role (`traits`, `options`, or `result`), fields, owning operation, and conformance rules | Mapping and matching dataclasses |
| `protocol` | Required method signatures, input/output relations, invariants, and conformance evidence | Six public Protocols |
| `vocabulary` | Closed/open policy, exact value identity, extension/version rule | `DataType`, `FormatSpec`, `CameraModel` |
| `error` | Parent error, stable category, operation boundary, and non-retryable/retryable policy where meaningful | Five public exceptions |

The new envelope and member/evidence model classes must themselves receive
`descriptor` entries before they are exported. The catalog therefore proves
its own public metadata surface rather than exempting it recursively.

### Field/member semantics

Data-bearing members record, as applicable:

- public name and declared type expression;
- required, optional, derived, or conditionally present state;
- immutable, mutable, input-only, or output-only behavior;
- canonical units and conversion equation;
- ordered/unordered and duplicate policy for collections;
- default, omitted, `None`, unknown, sentinel, and empty-value distinctions;
- numeric bounds or closed value vocabulary;
- serialization participation;
- validation exception type;
- rules and refusal behavior that callers cannot infer from the name.

Protocol methods record normalized signatures and behavioral rules. Enum and
vocabulary entries record exact values and whether extension is closed,
append-only, or externally open.

### Evidence model

An evidence reference contains:

- repository-relative test path;
- optional exact pytest node id;
- one or more claim ids such as `construction`, `roundtrip`, `alias_identity`,
  `normalization`, `procedure_conformance`, or `error_boundary`;
- optional fixture/contract artifact path.

Existing representation file evidence is adapted without changing
`RepresentationNormalizationContract.evidence`. New entries start with exact
node ids. Before final closure, every public type has at least one executable
claim and every referenced path/node resolves during collection.

## 7. Public lookup and serialization API

The additive public surface is:

```python
import sceneio

contract = sceneio.public_type_contract(sceneio.Point3DRecord)
assert contract.canonical_path == "sceneio.Point3DRecord"
assert contract.kind == "wire_record"

same = sceneio.contracts.public_type_contract("sceneio.points_binary.Point3DRecord")
assert same is contract

payload = sceneio.contracts.catalog_dict()
assert payload["contract_schema_version"] == 1
```

Required lookup behavior:

- exact canonical paths and aliases return the same immutable entry;
- a class or instance resolves by public identity without importing its module;
- an unambiguous short name may resolve for parity with
  `representation_contract`;
- an ambiguous short name raises `ValueError` and lists canonical choices;
- an unknown string raises `KeyError`;
- an object with no public contract raises `TypeError`;
- `representation_contract()` remains unchanged and returns the same existing
  `RepresentationNormalizationContract` objects;
- a representation envelope references, rather than clones, that specialized
  contract.

`sceneio.contract_dict()` remains the COLMAP database serializer. The generic
catalog serializer is intentionally namespaced as
`sceneio.contracts.catalog_dict()` to avoid a stable-name collision.

The serialized catalog contains no Python class objects, callables, absolute
paths, provider availability, memory addresses, or environment-dependent
values. Keys and entries have deterministic order. `contract_schema_version`
versions the JSON shape; adding catalog entries does not change that shape.
An incompatible shape requires a new schema version, while incompatible
changes to an existing stable subject require an additive replacement or a
future major API version.

## 8. Canonical identity and alias rules

1. Keep the existing `REPRESENTATION_CONTRACTS` key as canonical for all 103
   representations.
2. Otherwise prefer a root `sceneio.Name` path when that name is explicitly in
   `sceneio.__all__`.
3. If there is no root export, use the documented public namespace path such
   as `sceneio.mapping.MappingResult`.
4. Never expose `_core` or a private `_...` implementation module as a
   canonical path.
5. Record implementation-module identity only as diagnostic metadata, not as a
   supported import alias unless it is already documented public API.
6. Require every alias to import as the exact same class object in the base
   environment.
7. Reject alias collisions during catalog construction.
8. A public rename is not part of this program. A clearer future name must be
   additive, preserve the old alias, and receive a separate compatibility
   review.

## 9. The 36 initially uncovered identities

### Wire, storage, and schema records

- `sceneio.Point3DRecord` — `wire_record` for
  `application/x-sfm-points-v1`.
- `sceneio.CheckpointRef` — immutable checkpoint reference descriptor.
- `sceneio.MaterializedImage` — materialized image-location descriptor.
- `sceneio.ColumnDef`, `sceneio.TableDef`, `sceneio.DatabaseProfile`, and
  `sceneio.ColmapDatabaseConversionReport` — schema/conversion descriptors
  linked to the existing version-3 COLMAP database contract.

### I/O, coordinate, vocabulary, and contract metadata

- `ArrayInspection`, `Inspection`, `DepthEncoding`, `Codec`,
  `CodecCapabilities`, and `NativeFeatureCapabilities`.
- `CoordinateConvention` and `FormatCoordinateContract`.
- `sceneio.formats.DataType` and `sceneio.formats.FormatSpec`.
- `NormalizationProfile` and `RepresentationNormalizationContract`.

### Procedure values and Protocols

- `MapperTraits`, `MappingOptions`, `MappingResult`, `MatcherTraits`, and
  `MatchingOptions`.
- `BlobStore`, `ImageSourceImpl`, `Mapper`, `FeatureExtractor`, `PairMatcher`,
  and `GeometricVerifier`.

### Vocabulary and errors

- `sceneio.data.CameraModel`.
- `SceneIoError`, `ContractViolation`, `FormatError`, `ColmapAdapterError`, and
  `ColmapMvsError`.

None of these receive fake scale or coordinate fields. Their kind-specific
contracts describe the behavior clients actually consume.

## 10. Codec payload-kind standardization

The built-in registry currently uses 26 `Codec.datatype` strings. Create an
immutable `BUILTIN_CODEC_PAYLOAD_KINDS` mapping whose values record:

- token, title, and description;
- associated public type contracts, possibly more than one;
- optional exact logical `DataType` relation when one exists;
- built-in format ids using the token;
- static versus profile/detection-dependent output behavior;
- tests proving the relation.

Compatibility rules:

- Keep the stored `Codec.datatype` field and `CodecCapabilities.datatype`
  output byte-for-byte unchanged.
- Add a read-only `payload_kind` property returning `datatype`; do not add a
  dataclass field that changes repr, equality, constructor, or pickle shape.
- Validate only built-in assembly against the closed built-in vocabulary.
  `register()` must continue accepting runtime extension codecs with external
  tokens.
- A runtime extension token absent from the built-in vocabulary remains valid
  but has no SceneIO-owned payload contract unless a future extension API is
  separately designed.
- Do not infer logical `DataType` equivalence from string equality. Store an
  explicit relation.
- For codecs whose `record_type` is dynamic or `None`, enumerate the accepted
  output profiles or record an explicit dynamic-output rule. Do not invent one
  record type merely to make the graph one-to-one.

Final invariants:

- all 74 built-ins reference exactly one registered built-in payload kind;
- every built-in payload kind is used by at least one built-in format;
- every non-`None` built-in `record_type` resolves to a public type contract;
- every dynamic output has explicit profile evidence;
- all eight logical `DataType` entries remain identical and in the same order.

## 11. Ordered implementation units

```text
PTC0 census and decision freeze
  -> PTC1 private contract model and immutable registry core
  -> PTC2 adapt the 103 representation contracts and aliases
  -> PTC3 wire/storage/schema/I-O descriptor contracts
  -> PTC4 procedure-value and Protocol contracts
  -> PTC5 vocabulary and error contracts
  -> PTC6 codec payload-kind vocabulary and relationship graph
  -> PTC7 public lookup, serialization, lazy exports, and snapshots
  -> PTC8 generated documentation and final package qualification
```

Do not expose a partial generic catalog publicly. PTC1-PTC6 may build and test
private modules, but `sceneio.contracts`, root forwards, and the generic lookup
become documented public API only in PTC7 after exhaustiveness is green.

### PTC0 — freeze the census and decisions

**Owned files**

- `tests/contracts/public_type_standardization_v1.toml`
- `tests/test_public_type_contracts.py`
- this plan

**Work**

- Declare the nine public namespaces and canonicalization policy.
- Freeze the 139 baseline identities, 103/24/6/5/1 classification counts,
  eight logical DataType ids, 26 built-in payload tokens, and 74 built-in
  formats.
- Store class identities as canonical/alias strings, never implementation
  memory addresses.
- Prove census results are invariant across repeated imports and root/namespace
  aliases.

**Exit gate**

- The census fails on a new, missing, duplicated, or reclassified public class.
- No production API or runtime behavior changes.

### PTC1 — implement the private model and registry core

**Owned files**

- `src/sceneio/contracts/model.py`
- `src/sceneio/contracts/manifest.py`
- `src/sceneio/contracts/registry.py`
- a minimal `src/sceneio/contracts/__init__.py` with no documented public
  exports yet
- focused model/registry tests

**Work**

- Add frozen, slotted, stdlib-only envelope/member/evidence/relation models.
- Validate closed vocabularies, canonical paths, aliases, member presence,
  evidence, relationships, and kind-specific invariants.
- Build immutable canonical and alias maps atomically; publish nothing when
  any entry is invalid.
- Keep the namespace out of root `__all__`, README examples, and the public
  compatibility snapshot until PTC7.

**Exit gate**

- Mutation, duplicate, malformed-path, alias-collision, unknown-kind,
  missing-evidence, and invalid-relation negative tests pass.
- `import sceneio.contracts.model` imports neither NumPy nor `sceneio._core`.

### PTC2 — adapt representations without duplicating them

**Owned files**

- `src/sceneio/contracts/manifest.py`
- adapter and equivalence tests

**Work**

- Create one `representation` envelope for each existing
  `REPRESENTATION_CONTRACTS` entry.
- Preserve the exact specialized contract object and evidence paths.
- Discover and freeze supported root/namespace aliases by identity.
- Preserve ambiguous-name behavior such as the compiled and neutral
  `DepthMap` distinction.

**Exit gate**

- Exact set equality remains 103 entries.
- Every generic representation envelope points to the identical existing
  specialized object.
- Existing representation tests pass unchanged.

### PTC3 — contract wire, storage, schema, I/O, and metadata dataclasses

**Owned files**

- manifest entries for the 19 non-procedure dataclasses listed in section 9
- existing focused test modules plus new contract assertions

**Work**

- Record field order, type, optionality, defaults, units, mutability,
  serialization participation, validation error, and refusal behavior.
- Link `Point3DRecord` to its exact wire constants and round-trip tests.
- Link COLMAP schema descriptors to the existing version-3 `contract_dict`.
- Link inspection/capability/coordinate/normalization descriptors to their
  existing authorities instead of restating live values.
- Preserve current repr, equality, pickle success/failure, and module identity.

**Exit gate**

- All 19 baseline identities have one entry and executable evidence.
- No constructor, repr, pickle, exception, or import snapshot changes.

### PTC4 — contract procedure values and Protocols

**Owned files**

- mapping/matching procedure-value entries
- six Protocol entries
- conformance/evidence tests

**Work**

- Classify traits, options, and results as `procedure_value` rather than
  representations.
- Capture normalized Protocol signatures, declared inputs/outputs, alignment,
  optionality, trait-honesty, and refusal invariants.
- Reuse `assert_mapper_conformance` and `assert_matcher_conformance` evidence.
- Give storage/image Protocols focused conformance fixtures where the current
  tests only exercise incidental consumers.
- Preserve mapping/matching import isolation.

**Exit gate**

- Five procedure dataclasses and six Protocols are fully covered.
- Signature drift or a missing conformance claim fails CI.

### PTC5 — contract vocabulary and errors

**Owned files**

- `CameraModel`, logical `DataType`, and format vocabulary relations
- five error entries and hierarchy tests

**Work**

- Freeze exact enum/value identities and open/closed or append-only policy.
- Reference the existing eight-entry logical DataType contract without adding
  ids.
- Record exception parent, owning boundary, stable category/reason, and whether
  retry has meaning. Local validation and format errors are non-retryable.
- Treat human-readable messages as non-contractual except for prefixes already
  frozen by compatibility snapshots.

**Exit gate**

- Exact vocabularies and exception hierarchies match runtime definitions.
- No error type or existing message-prefix contract changes.

### PTC6 — add built-in payload kinds and the relationship graph

**Owned files**

- `src/sceneio/contracts/payloads.py`
- built-in registry/capability relationship tests

**Work**

- Register the exact 26 current built-in payload tokens.
- Relate payloads to public types, logical DataTypes when exact, and formats.
- Add read-only `payload_kind` properties while retaining `datatype` storage.
- Validate built-in assembly only; preserve unrestricted runtime-extension
  tokens.
- Make dynamic NPY, flow, depth, and TIFF-style outputs explicit rather than
  pretending every codec has one static record class.

**Exit gate**

- Exact 74-format/26-payload relationship coverage is green.
- A third-party `Codec` with an external datatype token still registers and
  dispatches as before.
- I/O compatibility snapshots differ only by intentionally reviewed additive
  properties, not dataclass fields or repr.

### PTC7 — publish lookup, serialization, and lazy exports

**Owned files**

- `src/sceneio/contracts/__init__.py`
- `src/sceneio/contracts/serialization.py`
- `src/sceneio/__init__.py`
- public API/import/serialization snapshots

**Work**

- Publish `sceneio.contracts`, `PUBLIC_TYPE_CONTRACTS`, and
  `public_type_contract` lazily.
- Implement canonical, alias, class, instance, and unambiguous short-name
  lookup behavior.
- Implement deterministic `sceneio.contracts.catalog_dict()`.
- Self-register all newly public contract metadata classes.
- Update `io_public_v1.json` only for reviewed additive names and identities.
- Add installed-base-environment tests with no optional providers.

**Exit gate**

- Every public class identity, including new metadata classes, is classified
  exactly once.
- Plain `import sceneio` remains NumPy-lazy; importing the contracts namespace
  remains stdlib-only and does not load `_core`.
- Catalog serialization is byte-stable across two processes and LF/CRLF
  checkouts.

### PTC8 — generate docs and run final qualification

**Owned files**

- `docs/public_type_contracts.md`
- `README.md` and `docs/README.md`
- `tools/documentation_contract.py`
- `tests/contracts/documentation_v1.toml`
- changelog and release-facing contract notes

**Work**

- Generate current class-kind counts, aliases, payload vocabulary, and
  completeness summary from the live catalog.
- Document how to choose specialized versus generic lookup.
- Generate the relationship matrix without copying historical counts into
  active prose.
- Run focused, full, import, package, and installed-wheel validation.
- Perform final compatibility, docs, and independent review before declaring
  the program complete.

**Exit gate**

- Documentation generation is idempotent and drift-free.
- Source, sdist, and installed wheel expose the same catalog and deterministic
  serialization.
- No unclassified public type, unregistered built-in payload token, unresolved
  relation, missing evidence, or documentation drift remains.

## 12. Verification strategy

### Per-unit focused gate

```powershell
uv run ruff check .
uv run python -m pytest -q tests/test_public_type_contracts.py
uv run python -m pytest -q tests/test_representation_contracts.py tests/test_formats_datatypes.py tests/test_formats_registry.py
uv run python -m pytest -q tests/test_mapping_contracts.py tests/test_matching_contracts.py tests/test_conformance_kits.py
uv run python -m pytest -q tests/test_contract_surface.py tests/test_import_guards.py tests/test_io_compatibility_snapshots.py
uv run python tools/documentation_contract.py --check
uv run python -m pytest -q tests/test_documentation_consistency.py
```

Run only the subsets affected by an internal unit, but run the entire list
before PTC7 exposes the API.

### Required negative tests

- Duplicate canonical path or alias.
- Alias that imports to a different class identity.
- Missing or malformed evidence.
- Missing required field/member semantics.
- Representation envelope pointing to a missing or different specialized
  contract.
- Ambiguous short-name lookup.
- Unknown string and unsupported object lookup.
- Unknown relationship target.
- Built-in codec using an undeclared payload token.
- Unused built-in payload token.
- Dynamic-output codec without explicit output policy.
- Attempted mutation of any model or public mapping.
- Catalog serialization containing an absolute path, callable, class object,
  provider state, or nondeterministic value.
- Contract import loading NumPy, `_core`, mapping/matching siblings, or an
  optional provider.
- Runtime-extension codec rejected solely because its token is not built in.

### Final gate

```powershell
uv run ruff check .
uv run python tools/documentation_contract.py --check
uv run python -m pytest -q
```

The package gate must additionally build one sdist, build the platform wheel
from that exact sdist, install it into a fresh CPython 3.12 environment with
only the base dependency, and verify:

- every public contract imports and serializes;
- no source-tree module is imported accidentally;
- catalog hashes match source and wheel;
- all 74 installed built-ins retain their existing smoke behavior;
- optional-provider availability does not change the catalog bytes.

## 13. Documentation and evidence ownership

- `docs/public_type_contracts.md` becomes the current human interpretation and
  generated coverage matrix after PTC8.
- `docs/representation_normalization.md` remains authoritative for numeric
  normalization, scale, coordinates, and conversion.
- `docs/format_coverage.md` remains authoritative for current codec
  capabilities and provider availability.
- This plan remains an execution record and moves to the completed-plan index
  only after all acceptance gates pass.
- The generated documentation contract owns counts. Historical plans and
  benchmark records are never rewritten to current counts.
- Every public example uses canonical paths; alias examples are included only
  to explain compatibility.

## 14. Risks and stop conditions

| Risk | Stop condition | Required response |
|---|---|---|
| Catalog duplicates existing semantic sources | A field value must be edited in two production registries | Replace the copy with a reference/adapter before proceeding |
| Circular/eager imports | Contract import loads NumPy, `_core`, a provider, or a sibling procedure namespace | Stop the unit and move dependencies to string manifests or lazy lookup |
| Stable constructor/repr/pickle drift | Existing compatibility snapshot changes beyond additive exports/properties | Revert the shape change; use an envelope or read-only property |
| Runtime extension break | Existing external-token registration is rejected | Limit validation to built-in assembly |
| Alias ambiguity | One path maps to two identities or a bare name becomes ambiguous silently | Require qualification and preserve exact aliases |
| `DataType` identity drift | Any of the eight ids, order, kind, or serialized contract changes | Treat as a separate cross-repository versioned proposal |
| Dynamic codec output is guessed | A relation cannot be proven for every accepted profile | Mark it explicitly dynamic and add evidence; do not invent one record |
| Evidence cannot isolate the claim | Only broad full-suite success supports an entry | Add a focused test before marking the entry complete |
| New contract model escapes its own census | A newly exported metadata class is unclassified | Keep the API private until it self-registers |

No later PTC unit starts while an earlier unit has failing tests, undocumented
compatibility changes, or uncommitted generated drift.

## 15. Completion checklist

- [x] The production-owned public namespace manifest covers every supported
      `__all__` class identity.
- [x] Every identity has exactly one canonical path, one kind, and all aliases.
- [x] All 103 representation entries reference the identical existing
      specialized contracts.
- [x] All initially uncovered 24 dataclasses, 6 Protocols, 5 errors, and 1 enum
      have kind-appropriate contracts and executable evidence.
- [x] Newly public contract metadata types are self-classified.
- [x] The eight logical `DataType` entries and serialized identity are
      unchanged.
- [x] All 26 built-in payload tokens are registered and related explicitly.
- [x] All 74 built-in codecs resolve to one payload contract; dynamic outputs
      are explicit.
- [x] Runtime extension codecs with external tokens remain supported.
- [x] Existing root and namespace aliases retain exact object identity.
- [x] Existing constructors, fields, defaults, repr, pickle outcomes,
      exceptions, and wire formats remain unchanged.
- [x] `representation_contract()` remains source- and behavior-compatible.
- [x] `public_type_contract()` and `catalog_dict()` satisfy their lookup and
      deterministic serialization contracts.
- [x] Plain and contract-namespace imports remain lazy and provider-free.
- [x] Generated README/docs facts match the runtime catalog.
- [x] Focused, complete, source, sdist, and installed-wheel gates pass.

The program is complete only when a new public class cannot be exported, and a
new built-in payload token cannot be registered, without an intentional
contract classification, evidence, relationship update, and generated-doc
update in the same change.

<!-- immutable-archive:end -->
