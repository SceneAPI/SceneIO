# Finite 3D-CV profile closure checklist

- **Status:** FC0 and the bounded FC1A record/acquisition slice are locally
  complete as of 2026-08-03. `ImuCalibration` and `ImuSequence` are compiled
  public records, and `ImageSequence` carries exact optional acquisition
  timing. `VisualInertialDataset`, the `euroc_dataset` id, and FC2-FC7 remain
  provisional and non-public.
- **Baseline:** 73 built-in formats, each mapped to a licensed direct fixture
  or deterministic oracle-derived route.
- **Purpose:** close the remaining 3D-computer-vision representation and
  bounded-profile gaps without turning SceneIO into a general scientific,
  media, or scene-authoring framework.
- **Authority:** current shipped capability remains
  [`format_coverage.md`](format_coverage.md). This document owns only the
  dependency order and acceptance checklist for the finite follow-on work.
- **Machine decision contract:**
  [`remaining_3dcv_fc0_v1.toml`](../tests/contracts/remaining_3dcv_fc0_v1.toml)
  freezes the stable signatures, provisional names, provider observations,
  legacy projections, and registration gate used by FC0.
  [`visual_inertial_records_v1.toml`](../tests/contracts/visual_inertial_records_v1.toml)
  freezes the implemented FC1A fields, units, vocabularies, equations, and
  73-format registry boundary.

## 1. Review outcome

The initial closure proposal was directionally correct but would have created
several overlapping records. The reviewed plan reuses the following shipped
foundations:

| Existing foundation | Reuse decision | Actual missing layer |
|---|---|---|
| `CameraRig` | Keep camera calibration, camera extrinsics, topics, ROI/binning, and camera clock offsets here | `ImuCalibration`, IMU samples, and a dataset-level sensor/timeline aggregate |
| `StateTrajectory` | Keep pose, velocity, and bias ground truth here | Raw accelerometer and gyroscope observations |
| `ImageSequence` | Extend compatibly instead of adding a separate capture timeline | Per-frame exposure and rolling-readout metadata |
| `Mask` | Keep boolean participation/validity semantics | Integer semantic, instance, and panoptic label rasters |
| `InstanceSet` | Keep 3-D scene-object instances | Per-pixel instance identifiers and their class association |
| `PointCloud` | Keep one dense/unstructured cloud's owned samples, organization, and attributes | `PointScan` for raw validity/row/column indexing and `ScanSet` for multiple scans |
| TIFF `Image`/`Mask`/`TensorDict` profile | Preserve current simple-file return behavior | A format-neutral `RasterCollection` for multiple series and pyramid levels |
| OpenVDB `TensorDict` profile | Preserve compatibility for one identity-transform scalar grid | Multi-grid read/inspect/select only unless a qualified provider can also write the profile |
| `SceneGraph` | Keep static topology and payload ownership | Authored node-transform and visibility time samples |

The plan therefore does **not** add a generic `CaptureTimeline`, replace
`Mask`, duplicate `InstanceSet`, or create a second static scene graph.

## 2. Second-review findings and correction plan

SceneIO 0.2 is treated as a stable SDK surface for this review. The AIP links
below are design guidance adapted to a local Python/C++ API; REST resources,
authorization, pagination, and retries are not applicable.

### Required corrections

| Finding | Evidence | Risk and AIP basis | Required correction |
|---|---|---|---|
| The IMU model is incomplete | `CameraRig` has camera rows only; its Kalibr fields do not preserve IMU rate/noise/random-walk calibration | Silent calibration loss; [AIP-140](https://google.aip.dev/140), [AIP-141](https://google.aip.dev/141), and [AIP-180](https://google.aip.dev/180) | Add `ImuCalibration`; do not overload or rename stable `CameraRig` fields |
| Proposed acquisition names confuse instants and durations | `exposure_times_ns` and `line_readout_times_ns` do not state whether values are timestamps, totals, or per-step durations | Client ambiguity; [AIP-141](https://google.aip.dev/141) and [AIP-142](https://google.aip.dev/142) | Use `exposure_durations_ns` and `readout_step_durations_ns`; define the timestamp equation and presence rules |
| Label identifiers were narrowed inconsistently | `InstanceSet.ids` is `int64`, while the first plan proposed `InstanceMap` as `int32` | Unnecessary conversion/refusal and mismatched scene/raster ids; [AIP-180](https://google.aip.dev/180) | Keep semantic ids `int32`, instance ids `int64`, and add a shared taxonomy/table contract |
| Organized E57 was mapped onto an insufficient record | `PointCloud` requires `width * height == point_count` and has no raw invalid-state or sparse row/column arrays; the current E57 reader drops invalid rows | Lost organization/validity; [AIP-180](https://google.aip.dev/180) | Add `PointScan` around a `PointCloud`, raw invalid-state values, row/column indices, and pose; `ScanSet` owns scans |
| `TiffCollection` is format-specific | Existing public records are neutral and reused across codecs | API duplication and weak reuse; [AIP-190](https://google.aip.dev/190) | Use neutral `RasterLevel`, `RasterSeries`, and `RasterCollection` records; TIFF is one adapter |
| OpenVDB write scope exceeds the installed provider | TinyVDB 0.9 exposes no `add_grid`; its template has one scalar grid, and `VDBGrid.transform` is read-only | An advertised round trip could not be implemented honestly; [AIP-182](https://google.aip.dev/182) | Support multi-grid metadata/read/select only in this closure, retain one-grid writes, and mark broader writes excluded unless provider qualification proves them |
| USD already exposes selected-time input | `read_scene(..., time=...)` and `SceneGraph.selected_time` exist, but provider qualification currently reports `selected_time=False` | Redundant methods and contradictory behavior; [AIP-180](https://google.aip.dev/180) | Qualify and activate the existing `time` parameter; add `SceneAnimation` only after authored-sample extraction is proven |
| Compound selections do not fit the current global API | `read_partial` accepts exactly one fixed selector family, while scan/raster/grid selections need an id plus a range/window | Signature sprawl or ambiguous combinations; [AIP-140](https://google.aip.dev/140) and [AIP-180](https://google.aip.dev/180) | Keep compound operations on typed format-specific methods in this program; leave `read_partial` unchanged unless a future cross-format selection design is reviewed separately |
| Error behavior was underspecified | The first plan allowed either `ValueError` or `FormatError`; public I/O currently normalizes codec faults to `FormatError` | Callers cannot write stable handling; [AIP-193](https://google.aip.dev/193) | Keep record construction errors as `ContractViolation`/`ValueError`; require public I/O to raise `FormatError` with stable operation/format/feature prefixes |
| The plan prematurely reserved names and a registry count | No new record or dataset codec exists yet | Speculative public commitments; [AIP-180](https://google.aip.dev/180) | Treat names and `euroc_dataset` as provisional until an FC0 prototype and compatibility test pass; update 73 -> 74 only with a working codec |
| The verification schedule was too large | Six profiles each mandated 100/512 MiB fixtures and sixteen commits before provider feasibility | Excess runtime without proportional evidence | Use one 64-128 MiB qualifying fixture per implemented profile, a larger case only for a demonstrated selector/chunk boundary, and ten reviewable commits |

### API-review coverage

| Surface | Status | Evidence/result |
|---|---|---|
| Public records and fields | reviewed | Existing C++/Python records and proposed additions; corrections above |
| Read/write/inspect/partial methods | reviewed | Existing registry facade and optional-provider adapters |
| Backward compatibility/versioning | reviewed | Additive behavior only for previously refused profiles; stable simple-file behavior retained |
| Documentation/examples | reviewed | Field units, ordering, absence, equations, and refusal boundaries added to required gates |
| Errors | reviewed | Public `FormatError` normalization retained; provider strings remain non-contractual |
| Dependencies | reviewed | Existing optional providers retained; OpenVDB claim reduced to demonstrated capability |
| Resources, auth, pagination, retries | not applicable | Local filesystem/SDK API, not a network service |

### Correction execution order

1. [x] Apply field/name/provider-feasibility corrections in FC0 before any
       public symbol lands.
2. [x] Prototype each questionable provider operation with a tiny local file;
       record supported and refused behavior in capabilities.
3. [x] Land records only with an exercising codec or public projection. FC1A
       adds live normalization/coordinate projections and installed-wheel
       construction; the dataset codec remains in FC1B.
4. [x] Run focused compatibility and contract checks for FC1A. A codec
       benchmark is not applicable to this record-only slice and is deferred
       to FC1B.
5. [x] Reconcile this checklist and completion matrix for FC1A without marking
       the remaining profile units complete.

## 3. Finite closure boundary

### Included profiles

- [ ] One ASL/EuRoC-style visual-inertial directory profile containing camera
      streams, camera and IMU calibration, IMU samples, and optional ground
      truth.
- [x] Exact per-frame exposure and rolling-readout metadata on
      `ImageSequence`.
- [ ] Typed `SemanticMap`, `InstanceMap`, and `PanopticMap` records and explicit
      adapters for carriers that can preserve them.
- [ ] Multiple Cartesian E57 scans, including raw validity and sparse
      row/column organization plus per-scan rigid poses.
- [ ] Homogeneous 3D-CV TIFF series and image pyramids with explicit axes.
- [ ] Multiple supported OpenVDB grids for metadata, read, and selection;
      broader write support remains contingent on a provider that can create
      grids and set transforms.
- [ ] USD time-sampled node transforms and visibility with static payload
      topology.

### Explicit non-goals

- [ ] Do not add a general ROS bag, MCAP, or arbitrary sensor-log reader.
- [ ] Do not ingest video streams from visual-inertial datasets; image paths or
      already-supported image sequences remain the carrier.
- [ ] Do not add FFmpeg code, binaries, bindings, or a runtime dependency.
- [ ] Do not implement arbitrary OME microscopy axes, vendor TIFF tags, or a
      general metadata editor.
- [ ] Do not add E57 spherical/cylindrical coordinates, embedded imagery, or
      arbitrary extension schemas in this closure.
- [ ] Do not add arbitrary OpenVDB tree types, point grids, nonlinear
      transforms, inactive-tile fidelity, or level-set editing.
- [ ] Do not claim multi-grid/vector/transformed OpenVDB writing through
      TinyVDB 0.9; its current file API cannot add a grid or mutate a transform.
- [ ] Do not add USD layer authoring, variants, references/payload composition,
      value clips, deforming topology, general shader graphs, rendering, or
      simulation schemas.
- [ ] Do not reopen JPEG-XL, Draco, generic Arrow schemas, or formats unrelated
      to 3D-CV models.

An explicit refusal with a capability entry is a completed outcome for every
non-goal above.

## 4. Dependency and commit order

```text
FC0 contract and provider-feasibility freeze
  |
  +-- FC1 visual-inertial records and directory I/O
  +-- FC2 dense label maps and typed carrier adapters
  +-- FC3 E57 multi-scan profile
  +-- FC4 TIFF collection/pyramid profile
  +-- FC5 OpenVDB multi-grid profile
  +-- FC6 USD transform-animation profile
          |
          +-- FC7 combined package and hosted qualification
```

- [ ] Land one record/API unit at a time.
- [ ] Keep record-only commits adjacent to the first codec commit that uses
      them; do not land unused speculative types.
- [ ] Do not mix repository moves, provider replacement, or unrelated
      optimization with a profile-expansion commit.
- [ ] Preserve the current optional-provider boundaries and NumPy-only base
      runtime.
- [ ] End every green implementation commit with the required co-author line.

## 5. Universal acceptance contract

Every FC1-FC6 unit must satisfy all applicable boxes in this section.

### 5.1 Representation contract

- [ ] Define shape, dtype, ownership, ordering, optional-field presence, units,
      coordinate frame, pose direction, quaternion order, timestamp epoch, and
      time reference before implementing I/O.
- [ ] Add the representation to `sceneio.representation_contract(...)` and the
      exhaustive public-representation discovery test.
- [ ] Add or update coordinate contracts for every affected format.
- [ ] Preserve source values when the record can represent them; otherwise
      reject instead of guessing. Record construction uses
      `ContractViolation`/`ValueError`; the public I/O facade normalizes codec
      failures to `FormatError`.
- [ ] Make any conversion an explicit public operation with forward/backward
      tests against an independent mathematical reference.
- [ ] Retain existing constructor calls, defaults, return types for currently
      supported files, and raw compatibility APIs.

### 5.2 Fixture and oracle contract

- [ ] Add every new source, revision, artifact digest, license, attribution,
      and delivery decision to
      [`public_fixture_sources_v1.toml`](../tests/contracts/public_fixture_sources_v1.toml).
- [ ] Keep normal tests offline; acquisition writes only to an ignored cache.
- [ ] Require oracle-written -> SceneIO-read coverage.
- [ ] Require SceneIO-written -> oracle-read coverage.
- [ ] Keep SceneIO self-round-trip as supplementary evidence, never the sole
      evidence.
- [ ] Compare every represented array and convention field; do not reduce
      parity to dimensions or element counts.
- [ ] State exact equality, byte equality, or a justified numeric tolerance per
      field.
- [ ] Retain valid broader-profile artifacts as expected-refusal vectors.

### 5.3 Public I/O contract

- [ ] `write -> detect -> inspect -> read` passes through the public API.
- [ ] `inspect` obtains structural metadata without decoding bulk samples.
- [ ] Every collection profile has a bounded selector whose result equals the
      corresponding full-read slice.
- [ ] Direct-file writes are transactional and do not build an output-sized
      Python `bytes` object.
- [ ] Mapped or provider-owned inputs remain valid for the lifetime of every
      exposed array view.
- [ ] Empty, singleton, large, truncated, inconsistent, unsupported-profile,
      and destination-replacement cases have focused tests.
- [ ] Capabilities list supported and refused subfeatures exactly.
- [ ] Public errors begin with stable operation, format id, and refused-feature
      context; tests do not make provider wording part of the public contract.

### 5.4 Performance and resource contract

- [ ] Add a representative builder and oracle comparison to `bench/bench_io.py`.
- [ ] Measure full read, selected read, inspect, write, encoded size,
      `tracemalloc`, and fresh-process RSS.
- [ ] Include one generated 64-128 MiB logical payload per implemented
      profile; add a larger case only where it materially exercises a measured
      chunk or selection boundary.
- [ ] Prove inspect and selected reads allocate materially less than full
      decode for large fixtures.
- [ ] Record same-machine before/after and SceneIO/oracle results in the
      benchmark ledger; do not introduce brittle cross-machine absolute SLAs.
- [ ] Run the lifetime/resource, format-correctness, and test-soundness review
      and resolve every finding before commit.

### 5.5 Documentation and platform contract

- [ ] Update `format_coverage.md`, `coverage_roadmap.md`, public API docs,
      representation normalization, coordinate conventions, and this
      checklist in the implementing commit.
- [ ] Update installed-wheel smoke for every new symbol, selector, provider
      extra, and supported/refused feature.
- [ ] Verify the optional dependency is absent from the base import graph.
- [ ] Verify the source archive and wheels contain required license and
      attribution files but no downloaded dataset cache.
- [ ] Pass local MSVC tests and the existing Linux/macOS/Windows package lanes
      before marking a unit validated.

## 6. FC0 — freeze APIs, provider feasibility, and compatibility

### 6.1 API and provider decisions

- [x] Freeze the contract-level prototypes for `ImuCalibration` and
      `ImuSequence` as separate calibration and raw-observation records. No
      constructor is exported before the FC1 implementation exercises it.
- [x] Specify `VisualInertialDataset` as a thin aggregate over one
      `CameraRig`, IMU calibrations, camera `ImageSequence` values, one or more
      `ImuSequence` values, and optional `StateTrajectory` ground truth.
- [x] Select a compatible `ImageSequence` extension with optional acquisition
      arrays instead of adding
      a parallel timeline record.
- [x] Specify `LabelTaxonomy`, `SemanticMap`, `InstanceMap`, and
      `PanopticMap` in `sceneio.data`; keep `Mask` unchanged.
- [x] Specify `PointScan` and `ScanSet` for raw scan organization, validity,
      transforms, and multi-scan ownership.
- [x] Select neutral `RasterLevel`, `RasterSeries`, and `RasterCollection`
      records only if a full multi-series read/write needs a returned aggregate;
      preserve existing simple TIFF return types.
- [x] Measure TinyVDB 0.9 capabilities before adding any sparse-volume public
      record. Pin the observed lack of `add_grid` and transform mutation in a
      provider qualification test.
- [x] Probe authored USD time-sample extraction through the existing
      `read_scene(..., time=...)` surface before exporting `SceneAnimation`.
- [x] Treat `euroc_dataset` as a provisional format id for the ASL/EuRoC
      directory layout. Confirm detection and naming against existing dataset
      ids; change the built-in count from 73 to 74 only with working
      read/write/inspect and a fixture route.
- [x] Specify which public names are stable, provisional, or internal in the
      compatibility snapshot.
- [x] Pin the current `read_partial` signature and exactly-one-selector rule.
      Put compound dataset/scan/raster/grid operations on format-specific
      methods; do not add a generic selection framework in this program.

### 6.2 Compatibility snapshots

- [x] Snapshot exported symbols, constructor/factory behavior, record properties,
      registry ids, capability rows, and installed-wheel smoke before changes.
- [x] Add legacy-construction tests for `ImageSequence`, `PointCloud`,
      `TensorDict`, and `SceneGraph`.
- [x] Pin the current simple TIFF, one-scan E57, one-grid VDB, and static USD
      return types.
- [x] Pin the existing `read_scene(..., time=...)` signature and its current
      deliberate refusal while provider-selected-time support is unavailable.
- [x] Pin the current E57 projection behavior that returns only valid Cartesian
      rows, so the new raw `PointScan` path cannot silently change legacy
      `PointCloud` values.
- [x] Require the proposed optional fields to remain absent on legacy records
      until their implementation lands; later FC units must require them to be
      empty on legacy fixture reads.
- [x] Retain the exhaustive public-fixture route test so adding
      `euroc_dataset` cannot leave the 74th format unmapped.

### 6.3 FC0 local qualification result

- The machine contract keeps 15 proposed symbols and one proposed format id
  absent from the public surface and live 73-format registry.
- Generated probes qualify pye57 0.4.19 two-scan/pose I/O and tifffile
  2026.7.14 multi-series/subIFD-pyramid I/O. These are provider capabilities,
  not claims that SceneIO already accepts those profiles.
- TinyVDB 0.9.0 has one packaged template grid, no `add_grid`, and a read-only
  grid transform. Multi-grid or transformed writing therefore remains outside
  the current claim.
- TinyUSDZ 0.9.4 enumerates authored USDA and qualified USDC sample times but
  returns untyped sample values in both probes. `provider_selected_time` stays
  false and selected-time reads continue to fail deliberately.
- The focused FC0/provider gate passes 60 tests. The exact candidate collection
  (excluding the separately gated Niantic SPZ module) is 4,651 nodes; the
  complete local suite passes 4,666 tests with 16 documented optional/platform
  skips in 371.33 seconds. Repository-wide Ruff and `git diff --check` pass.

### 6.4 Three-lens review

- **Lifetime/resource:** no production mapping, buffer, or ownership path
  changed. Every generated E57, TIFF, and TinyVDB handle is closed by a context
  manager or `finally`, and no generated artifact leaves `tmp_path`.
- **Behavior correctness:** current public signatures, registry ids, return
  types, and refusal flags remain unchanged. Provider abilities are recorded
  separately from SceneIO support, so a successful broad-file generator does
  not widen the live capability claim.
- **Test soundness:** the review removed an unnecessary exact TinyVDB version
  assertion and made the tifffile multi-series probe decode and compare both
  payloads. The final probes validate file behavior, not merely method names or
  metadata shapes. No unresolved finding remains in this FC0 slice.

### FC0 exit

- [x] Names and boundaries are documented and machine-checked before record
      code.
- [x] Compatibility snapshots pass unchanged in the focused gate.
- [x] No new format or record has shipped prematurely.

## 7. FC1 — visual-inertial data and acquisition timing

### 7.1 `ImuCalibration` record

- [x] Store sensor id, name/topic, nominal rate, and one explicit
      sensor-to-reference rigid transform.
- [x] Store gyroscope noise density, gyroscope random walk, accelerometer noise
      density, and accelerometer random walk as optional `float64` quantities
      with exact units: `rad/s/sqrt(Hz)`, `rad/s^2/sqrt(Hz)`,
      `m/s^2/sqrt(Hz)`, and `m/s^3/sqrt(Hz)` respectively.
- [x] Store an optional signed `int64` clock offset in nanoseconds and define
      `reference_time_ns = sensor_time_ns + time_offset_ns`, matching the
      existing `CameraRig` offset direction.
- [x] Distinguish absent calibration from a numerically zero calibration; do
      not invent defaults for missing noise terms.
- [x] Validate finite/nonnegative noise quantities, a valid rigid transform,
      a positive rate when present, and closed unit vocabularies.

### 7.2 `ImuSequence` record

- [x] Add contiguous `int64` nanosecond timestamps.
- [x] Add contiguous `float64 (N, 3)` angular velocity and linear acceleration.
- [x] Carry explicit angular-velocity and acceleration units, sensor axis
      frame, timestamp reference, sensor id, and clock domain.
- [x] Require equal row counts, finite measurements, and strictly increasing
      timestamps.
- [x] Define empty and singleton behavior.
- [x] Expose owner-retaining NumPy views and DLPack consistently with other
      compiled numeric records.
- [x] Test pointer identity, read-only policy, `gc.collect()` lifetime,
      non-contiguous constructor inputs, and mismatched arrays.

### 7.3 `ImageSequence` acquisition extension

- [x] Append keyword-only optional fields without changing existing positional
      construction:
      `exposure_durations_ns`, `readout_step_durations_ns`,
      `readout_directions`, and one declared timestamp reference.
- [x] Use empty arrays to mean absent metadata; do not use zero as absence.
- [x] Define the readout-direction vocabulary for global, top-to-bottom,
      bottom-to-top, left-to-right, and right-to-left exposure.
- [x] Require acquisition arrays to be empty together where their semantics
      depend on one another, or document the independently optional cases.
- [x] Check nonnegative durations and exact `int64` range.
- [x] Define the acquisition equation explicitly. For frame timestamp `t`,
      step index `i`, signed direction `d`, exposure duration `e`, and readout
      step duration `r`, document the instant represented by
      `t + d * i * r` and whether `t` denotes exposure start, midpoint, or end.
- [x] Require global-shutter rows to omit readout-step durations and reject
      contradictory direction/duration combinations.
- [x] Preserve existing APNG/WebP/AVIF/Y4M timing behavior byte-for-byte when
      acquisition fields are absent.

The equation uses zero-based raster row `i` for vertical readout and
zero-based column `i` for horizontal readout. `d` is `+1` for top-to-bottom or
left-to-right and `-1` for bottom-to-top or right-to-left. `t` is the declared
start, midpoint, or end instant at raster coordinate zero; therefore
`t + d * i * r` is the same reference instant at coordinate `i`. `e` is the
per-frame exposure duration. For midpoint references, an odd `e` can imply
conceptual half-nanosecond interval endpoints, while the stored `t` and `e`
remain exact integers. Construction rejects any full-row/full-column equation
that would leave the signed `int64` domain. Exposure timing is independently
optional; rolling direction and step duration must be present together, and a
global/rolling mixture requires separate records.

Writers for APNG, animated WebP, animated AVIF, WebM, Theora, Y4M, and image
sequence directories reject acquisition timing because those bounded writer
profiles cannot preserve it.

### 7.3.1 FC1A local qualification result

- The public surface exports the two compiled IMU records and retains 73
  built-in format ids. `VisualInertialDataset` and `euroc_dataset` remain
  absent.
- The rebuilt MSVC extension exposes the new factories and record types. The
  focused implementation/codec/contract gate passes 234 tests; the exact
  candidate collection is 4,714 nodes; the complete local suite passes 4,729
  tests with 16 documented optional/platform skips in 382.58 seconds.
- The post-review focused gate passes 135 tests, including the coordinate
  regression and exact collection contract. Repository-wide Ruff and
  `git diff --check` pass.
- This record-only slice changes no registered read/write/inspect/partial
  implementation, so no codec throughput or large-file delta is claimed. The
  dataset benchmark and independent directory-parser comparison belong to
  FC1B.
- Linux/macOS wheel validation remains pending and user-gated; no hosted run
  was triggered for FC1A.

### 7.3.2 FC1A three-lens review

- **Lifetime/resource:** calibration arrays and IMU sample vectors are record
  owned; exposed NumPy/DLPack views pin their parent, use a non-null empty
  sentinel, and remain valid after `gc.collect()`. Acquisition arrays are
  copied into `ImageSequence` ownership and their views retain the record.
- **Behavior correctness:** exact units, optional-versus-zero presence, unit
  quaternion/sign policy, strictly increasing timestamps, clock-offset and
  rolling-readout equations, signed-range overflow, and writer refusal are
  executable contracts. Review found and fixed a misplaced handedness branch:
  Python `PosedViewSet` remains right-handed, while generic `sensor` IMU axes
  remain unknown until ENU/NED is declared.
- **Test soundness:** equation tests use live record values rather than
  restating constants; malformed, boundary, ownership, DLPack, legacy, public
  export, and every affected writer path are exercised. No unresolved FC1A
  finding remains.

### 7.4 `VisualInertialDataset` aggregate

- [ ] Store one `CameraRig`, ordered IMU calibrations, ordered named camera
      streams, ordered IMU streams, and optional `StateTrajectory` ground truth
      without copying child arrays.
- [ ] Validate sensor ids/topics against the rig and reject duplicate names.
- [ ] Declare one timestamp epoch and clock domain per stream; do not align or
      interpolate clocks implicitly.
- [ ] Carry dataset-root-relative image names as inert paths.
- [ ] Define partial selection by camera, IMU sensor, frame range, and
      nanosecond interval on the format-specific dataset API; do not extend the
      global `read_partial` signature for compound sensor selection.
- [ ] Test child lifetime after the aggregate and local path handles leave
      scope.

### 7.5 provisional `euroc_dataset` directory adapter

- [ ] Implement repository-owned layout parsing in
      `src/sceneio/io/_euroc_dataset.py` and register it under the dataset
      family.
- [ ] Support the bounded ASL layout: `mav0/cam*/data.csv`, image paths,
      `sensor.yaml`, `mav0/imu*/data.csv`, and optional state ground truth.
- [ ] Preserve calibrated intrinsics, distortion, camera/IMU extrinsics,
      sensor rate/noise/random-walk metadata, clock offsets, and nanosecond
      timestamps.
- [ ] Write a deterministic bounded directory with relative paths and atomic
      destination replacement.
- [ ] Keep image bytes opaque; do not transcode or add a video path.
- [ ] Add `inspect` counts, time ranges, sensor names, resolutions, and presence
      flags without reading image payloads.
- [ ] Add camera/frame/time/IMU selection to the format-specific dataset API
      and verify it against full reads.
- [ ] Reject unsupported sensor types, duplicate timestamps, missing files,
      ambiguous transforms, and inconsistent CSV/YAML rows.

### 7.6 FC1 oracle and data

- [ ] Use permissively licensed TUM-VI and Monado layouts as hosted read
      sources; keep official EuRoC bytes excluded from redistribution.
- [ ] Use Fire Actioncam `meta.npz` only to qualify exposure/readout mapping,
      with NumPy as the independent parser.
- [ ] Build a tiny deterministic ASL directory from the pinned permissive
      values for offline write/read tests.
- [ ] Compare YAML calibration with Kalibr/CamTools equations and CSV values
      with an independent stdlib/NumPy parser.
- [x] Add hand-computable clock-offset, quaternion-order, and acquisition
      direction fixtures for the FC1A records. Dataset pose-direction fixtures
      remain part of FC1B.

### FC1A exit

- [x] `ImuCalibration`, `ImuSequence`, and acquisition timing are compiled,
      public, normalization-qualified, coordinate-qualified, and installed-
      wheel-smoked.
- [x] All FC1A temporal fields have exact units, presence rules, reference
      semantics, and range checks.
- [x] Existing sequence codecs retain legacy behavior when fields are absent
      and refuse metadata they cannot preserve.
- [x] The registry remains exactly 73 because no dataset codec was added.

### FC1 exit

- [ ] `euroc_dataset` reads, writes, inspects, and partially selects the bounded
      directory profile.
- [ ] All temporal fields have exact units and reference semantics.
- [ ] Existing sequence codecs remain byte/value compatible.
- [ ] The fixture, coordinate, representation, registry, and documentation
      contracts agree on 74 built-ins if the provisional dataset id passes
      FC0; otherwise the aggregate remains an explicit high-level API and the
      registry stays at 73.

## 8. FC2 — semantic, instance, and panoptic raster maps

### 8.1 Records

- [ ] Add immutable NumPy-native records in `sceneio.data.dense`.
- [ ] `LabelTaxonomy`: unique `int32` semantic ids, ordered names, optional
      display colors, and optional thing/stuff flags; taxonomy identity and
      version are explicit strings rather than inferred from names.
- [ ] `SemanticMap`: `int32 (H, W)` class ids, optional boolean validity,
      an optional `LabelTaxonomy`, and explicit void id.
- [ ] `InstanceMap`: `int64 (H, W)` instance ids, optional boolean validity,
      explicit background id, and optional unique `int64 -> int32`
      instance-to-semantic table.
- [ ] `PanopticMap`: composed `SemanticMap` and `InstanceMap` with identical
      shape/validity plus explicit void and background semantics; do not copy
      child arrays or assume a packed divisor encoding.
- [ ] Require C-contiguous arrays, equal shapes, finite integer-domain values,
      and consistent instance/class tables.
- [ ] Define packed panoptic encodings only as explicit converters whose
      divisor, void id, and overflow behavior are caller-visible.
- [ ] Keep `Mask(True = participates)` unchanged and use it only for validity,
      never as an integer label carrier.

### 8.2 Typed carrier adapters

- [ ] Add explicit typed adapters for NCore camera-label/mask components.
- [ ] Add versioned NPZ/Zarr schemas for semantic, instance, and panoptic maps.
- [ ] Add a TIFF typed path only when the caller supplies a label contract or a
      versioned `sceneio.label_map/1` description tag declares the kind and
      taxonomy; never infer semantics from integer pixels.
- [ ] Treat a TIFF without that declaration as a raster projection only. Refuse
      a typed write when non-default semantics would be lost.
- [ ] Preserve raw `read("tiff")`, raw `TensorDict`, and NCore component APIs.
- [ ] Refuse palettes/taxonomies that cannot be represented without loss.

### 8.3 FC2 oracle and data

- [ ] Generate one tiny deterministic Kubric scene with RGB, depth, semantic
      ids, instance ids, object poses, and optical flow.
- [ ] Pin the Kubric revision, generation parameters, assets, and resulting
      hashes; do not depend on a hosted MOVi artifact's implicit terms.
- [ ] Keep Kubric/Blender out of normal CI. Store only a tiny attributed
      deterministic result or reconstruct the checked numeric arrays from a
      compact regeneration manifest; run full regeneration in an opt-in lane.
- [ ] Compare typed maps with Kubric's emitted arrays and metadata.
- [ ] Cross-read NPZ/Zarr/TIFF carriers with NumPy, Zarr, and tifffile.
- [ ] Test non-contiguous views, void pixels, large ids, empty instance sets,
      invalid table references, and mixed semantic/instance backgrounds.

### FC2 exit

- [ ] All three maps round-trip through at least one lossless generic carrier.
- [ ] NCore projection produces the same canonical maps as its independent
      component parser.
- [ ] Typed TIFF requires explicit meaning and cannot misclassify an ordinary
      grayscale image.
- [ ] Coordinate and normalization contracts cover all new public records.

## 9. FC3 — E57 multiple Cartesian scans

### 9.1 `PointScan` and `ScanSet`

- [ ] `PointScan` owns one `PointCloud` containing stored E57 rows plus optional
      raw `uint8` invalid-state values of the same length; zero means valid and
      nonzero values remain distinguishable.
- [ ] Preserve optional raw `int64` row and column indices rather than forcing
      sparse organized scans into `PointCloud.width * height == point_count`.
- [ ] Store declared row/column bounds separately and validate every index
      against them.
- [ ] Store stable scan name/guid, optional acquisition timestamp, rigid pose,
      and source-coordinate metadata.
- [ ] Make the `PointScan` pose authoritative. Keep the child cloud viewpoint
      neutral and have `valid_point_cloud()` apply the pose to the legacy
      `PointCloud.viewpoint`, avoiding two independently mutable copies.
- [ ] Pin the exact E57 pose direction/quaternion ordering with pye57 and a
      hand-computable translated/rotated scan before naming public fields.
- [ ] Provide an explicit `valid_point_cloud()` projection matching the legacy
      E57 reader's current valid-row behavior.
- [ ] `ScanSet` owns ordered `PointScan` children and rejects duplicate scan
      identifiers.

### 9.2 E57 adapter expansion

- [ ] Preserve current one-scan unorganized `PointCloud` return behavior; use
      the typed scan API for raw validity/organization.
- [ ] Return `ScanSet` for multi-scan or structured input and accept
      `PointCloud`, `PointScan`, or `ScanSet` for writing.
- [ ] Add `scan_index` and combined `scan_index` + half-open
      `stored_point_range` to the typed E57 scan API. Do not call a stored-row
      range a valid point range or add these compound values to global
      `read_partial`.
- [ ] Inspect every scan's count, organization, bounds, fields, and pose
      without decoding point payloads.
- [ ] Report stored counts from headers; report valid counts as unknown unless
      the provider exposes them without reading `cartesianInvalidState`.
- [ ] Preserve supported Cartesian coordinates, intensity, RGB, row/column
      organization, and rigid pose fields per scan.
- [ ] Retain the existing exact-float32 Cartesian and uint8-color boundary.
      Valid values must round-trip exactly; coordinate payloads on invalid rows
      are canonicalized to a documented placeholder because the invalid-state
      field, not those coordinates, carries meaning.
- [ ] Keep imagery, non-Cartesian coordinates, unsupported extensions, and
      lossy field narrowing as explicit refusals.
- [ ] Verify temporary output cleanup and destination preservation when a later
      scan fails to write.

### 9.3 FC3 oracle and data

- [ ] Select at least one official permissive multi-scan E57 example and pin
      its content digest.
- [x] Generate a tiny two-scan file with `pye57` in the provider probe, with
      distinct poses and exact Cartesian values.
- [ ] Extend that generated case with invalid-state, row/column, and organized
      dimension fields as part of the FC3 record implementation.
- [ ] Compare every scan with `pye57.read_scan_raw` and header metadata.
- [ ] Have `pye57` reopen SceneIO's multi-scan output and compare scan order,
      poses, stored/valid counts, invalid-state values, row/column indices, and
      every valid point attribute.
- [ ] Retain official examples containing imagery or unsupported extensions as
      expected-refusal cases.

### FC3 exit

- [ ] One- and multi-scan behavior is documented and oracle-proven.
- [ ] Selected scan/range reads equal full-read slices.
- [ ] Large multi-scan read/write measurements show bounded per-selection
      allocation.

## 10. FC4 — bounded TIFF series and pyramids

### 10.1 neutral raster collection model

- [ ] Define `RasterLevel`, `RasterSeries`, and `RasterCollection` as
      format-neutral immutable Python records.
- [ ] Store ordered series/levels, explicit axes, dtype, shape, payload kind,
      and `Image`/`Mask`/`TensorDict` children that own their arrays.
- [ ] Limit each series to the currently accepted CV raster/stack dtypes and
      axes.
- [ ] Permit multiple series only when each series is independently
      unambiguous under the bounded profile.
- [ ] Preserve the current `Image`, `Mask`, or `TensorDict` return for a simple
      one-series, one-level file.

### 10.2 TIFF adapter expansion

- [ ] Fix frame/page metadata traversal so valid OME frames do not produce the
      current wrapped `TiffFrame.tags` failure.
- [ ] Add `series_index`, `level_index`, `page_range`, and `window` to the
      typed TIFF collection API; define valid combinations without changing
      global `read_partial`.
- [ ] Inspect all series/levels and report axes, shapes, dtypes, page counts,
      tile/strip layout, and BigTIFF status without decoding samples.
- [ ] Read only the selected series/level/page/window when tifffile exposes a
      bounded path; document unavoidable provider granularity.
- [ ] Write deterministic homogeneous series and pyramid files through
      tifffile and reopen them before atomic replacement.
- [ ] Before exporting `RasterCollection`, prove tifffile can write and reopen
      the exact bounded subIFD/series layouts on all supported platforms. If
      not, keep multi-series/pyramid support read/select-only and report that
      capability honestly.
- [ ] Reject ambiguous OME axes, structured dtypes, mixed unsupported
      photometric interpretations, and metadata that the record would drop.
- [ ] Keep arbitrary OME-XML editing outside the profile.

### 10.3 FC4 oracle and data

- [ ] Pin the checked CC-BY-4.0 OME-TIFF 4D file and one permissive pyramid
      sample or generate the pyramid independently with tifffile.
- [ ] Compare series/level/page/window arrays and metadata with tifffile.
- [ ] Have tifffile reopen SceneIO-written classic TIFF and BigTIFF variants.
- [ ] Test tiled and stripped files, endian variants, one/many pages, and
      selected reads that cross tile/strip boundaries.

### FC4 exit

- [ ] The previously checked OME file either reads under the bounded profile or
      fails with a deliberate documented boundary, never an incidental
      provider attribute error.
- [ ] Simple TIFF compatibility is unchanged.
- [ ] Pyramid/series selection shows a measured memory advantage over full
      collection decoding.

## 11. FC5 — provider-constrained OpenVDB expansion

### 11.1 provider feasibility gate

The 2026-08-03 local review inspected installed TinyVDB 0.9.0 and the packaged
`openvdb_float_template.vdb`: the template contains one
`Tree_float_5_4_3` grid, `VDBFile` has no `add_grid`, and assigning
`VDBGrid.transform` raises `AttributeError`. These observations constrain the
plan but do not replace file-based oracle qualification.

- [x] Pin TinyVDB 0.9's actual local surface: it can enumerate existing grids
      and replace one existing template grid, but has no `add_grid` and exposes
      a read-only transform.
- [ ] Test multi-grid files containing every candidate value/tree type before
      declaring that type readable.
- [ ] Test whether selecting one grid avoids materializing other grids; do not
      advertise bounded selection based only on a post-decode slice.
- [ ] Evaluate an alternative provider only through the existing dependency
      intake/benchmark process. Do not pull full OpenVDB/Boost/TBB into release
      wheels merely to satisfy an aspirational checklist row.
- [ ] Choose one explicit state: implemented read expansion with current
      provider, qualified provider replacement, or documented exclusion.

### 11.2 read/inspect/select profile

- [ ] If the feasibility gate passes, add `SparseGrid` only for value types
      actually returned by the provider and `SparseVolumeSet` for ordered
      uniquely named grids.
- [ ] Carry observed grid name, class, value kind, background, tree type, and
      finite `float64 (4, 4)` index-to-world matrix without claiming those
      fields are writable.
- [ ] Read multiple supported grids while preserving file order and names.
- [ ] Add `grid_name`/`grid_index` and optional index-space/world-space bounds
      to the typed OpenVDB API only where the provider demonstrates bounded
      access. Grid selection is required; bounding-box selection is optional
      and measured.
- [ ] Inspect grid count, names, types, active counts, bounds, backgrounds,
      classes, and transforms without materializing active voxels.
- [ ] Preserve affine transforms in the returned record within declared
      float64 tolerance.
- [ ] Continue refusing unsupported tree/value types, point grids, nonlinear
      transforms, inactive-tile semantics, and level sets that cannot survive
      the sparse record.
- [ ] Ensure USD volume assets select an exact named grid rather than silently
      using the first grid.
- [ ] Retain the legacy identity scalar `TensorDict` read/write path unchanged.
- [ ] Reject `SparseVolumeSet` writes with a stable feature-specific
      `FormatError` while the provider cannot create grids/set transforms.

### 11.3 FC5 oracle and data

- [ ] Generate scalar density and three-component velocity grids with distinct
      affine transforms through official OpenVDB; use only the subset the local
      provider can read as positive fixtures.
- [ ] Cross-read expanded files with TinyVDB locally and official OpenVDB in
      the hosted lane.
- [ ] Keep the existing one-grid SceneIO-write -> TinyVDB-read oracle as the
      write-direction evidence; do not mislabel it as multi-grid write parity.
- [ ] Run an official OpenVDB comparison in the optional hosted lane for
      metadata, transforms, active coordinates, and values.
- [ ] Test duplicate names, singular transforms, nonzero backgrounds, empty
      grids, negative coordinates, and unsupported grid classes.

### FC5 exit

- [ ] Legacy single identity-grid files retain their current compatibility
      return path.
- [ ] Multi-grid read, exact grid selection, and affine metadata are
      oracle-proven for the declared types, or the feature is explicitly
      excluded with provider evidence.
- [ ] Multi-grid/vector/transformed writes remain listed as unsupported unless
      a later provider qualifies both directions.
- [ ] Selected-grid memory excludes unselected grid payloads; no stronger
      bounded-region claim is made without measurement.

## 12. FC6 — bounded dynamic USD

### 12.1 provider and authored-sample feasibility

- [x] Preserve and snapshot the existing `read_scene(path, time=...)` method and
      `SceneGraph.selected_time`; do not add a competing time method.
- [ ] Prove whether TinyUSDZ exposes authored transform/visibility sample times
      and values for USDA, USDA-root USDZ, and qualified USDC inputs.
- [ ] If TinyUSDZ cannot expose them, assess a bounded repository-owned USDA
      parser only for the exact directly authored profile; do not claim USDC
      animation support through text scanning.
- [ ] Compare exact authored-time and between-sample evaluation with OpenUSD
      before setting `provider_selected_time=True`.
- [ ] Keep the current deliberate refusal when the provider/path cannot
      evaluate the requested time correctly.

### 12.2 conditional `SceneAnimation`

- [ ] Export `SceneAnimation` only after section 12.1 proves authored-sample
      extraction and deterministic writing; otherwise close with selected-time
      read support plus an explicit animation-preservation refusal.
- [ ] Attach optional animation to `SceneGraph`; do not duplicate static nodes
      or payloads.
- [ ] Store node-indexed CSR time samples for local 4x4 transforms.
- [ ] Store node-indexed CSR time samples for visibility.
- [ ] Preserve authored float64 time codes, stage start/end time, and
      `timeCodesPerSecond`.
- [ ] Require strictly increasing sample times per property, valid node
      indices, finite transforms, and consistent CSR offsets.
- [ ] Keep mesh topology, point arrays, Gaussian attributes, camera optics,
      materials, and volume assets static in the proposed dynamic profile.

### 12.3 USD adapter expansion

- [ ] Read authored transform and visibility samples without baking them into
      one static value.
- [ ] Activate the existing `time` argument to materialize one static
      `SceneGraph` using qualified USD interpolation behavior. Report it as a
      high-level supported feature; do not extend global `read_partial` in this
      program.
- [ ] Write deterministic USDA/USDZ time samples and preserve stage timing
      metadata.
- [ ] Support rigid animation of mesh, point-cloud, Gaussian, camera, volume,
      and instance payload nodes through their owning node transform.
- [ ] Reject time-varying topology, primvars, per-point/per-Gaussian values,
      camera optics, material networks, value clips, and unsupported
      composition.
- [ ] Keep the existing static `usd-3dcv-1` profile unchanged; declare a new
      versioned dynamic profile only if both authored-sample read and write are
      qualified, instead of silently widening profile 1.

### 12.4 FC6 oracle and data

- [ ] Author a tiny permissive USDA fixture with two nodes, three nonuniform
      transform samples, visibility changes, and one static Gaussian payload.
- [ ] Compare authored sample arrays and selected-time evaluation with
      OpenUSD in the hosted oracle lane.
- [ ] Have TinyUSDZ read SceneIO-authored USDA/USDZ locally and compare every
      supported static payload plus the time metadata it actually exposes.
- [ ] Test negative/fractional time codes, non-24 rates, held endpoints,
      interpolation between samples, and malformed sample arrays.
- [ ] Retain composed, clipped, or deforming official USD examples as
      expected-refusal vectors.

### FC6 exit

- [ ] Static USD fixtures remain value/byte compatible where deterministic.
- [ ] Dynamic transform/visibility samples cross-read both directions.
- [ ] If two-direction preservation is not feasible with the qualified
      provider, selected-time read is reported separately and dynamic writing
      remains explicitly unsupported rather than marking this box complete.
- [ ] Selected-time reads equal the OpenUSD-evaluated static scene within the
      declared transform tolerance.
- [ ] Per-Gaussian deformation and general USD authoring remain clearly out of
      scope.

## 13. FC7 — combined qualification and closure

### 13.1 Local aggregate gate

- [ ] Rebuild after every C++/CMake change with
      `uv pip install -e ".[dev,test]"`.
- [ ] Verify every new `_core` symbol from the repository interpreter.
- [ ] Run focused record and codec suites after each unit.
- [ ] Run the registry-driven public API, oracle, partial-read, mapping
      lifetime, documentation, package-inventory, and installed-wheel smoke
      tests.
- [ ] Run the complete suite and repository-wide Ruff.
- [ ] Run `git diff --check` and review the complete diff for unrelated edits.
- [ ] Run the five-run benchmark guard and record new rows/deltas.

### 13.2 Package and hosted gate

- [ ] Build the source archive and clean Windows abi3 wheel from the exact
      candidate commit.
- [ ] Install the base wheel with NumPy only and prove every optional provider
      remains lazy.
- [ ] Install each affected extra separately and run its installed-wheel smoke.
- [ ] Verify source archive and wheel license inventories.
- [ ] Run the affected optional-provider hosted lane after each locally green
      provider unit rather than deferring every platform finding to FC7.
- [ ] Push and trigger Linux/macOS/Windows build-only validation only after the
      local candidate is green and the user authorizes that exact action.
- [ ] Run hosted OpenUSD/OpenVDB and large-data comparisons without adding
      those packages or datasets to normal CI.
- [ ] Record workflow links, artifact hashes, platform results, optional skips,
      and benchmark summaries in the coverage documents.

### 13.3 Final documentation reconciliation

- [ ] Generate/validate registry capability tables from the 73-format runtime,
      or 74 only if the provisional dataset codec qualified and landed.
- [ ] Update the public-fixture manifest counts and route only if the
      provisional dataset format lands.
- [ ] Confirm every new public representation is present exactly once in the
      normalization contract.
- [ ] Confirm every affected format has a coordinate contract and executable
      evidence.
- [ ] Mark each profile `validated`, `locally complete awaiting hosted result`,
      or `excluded`; leave no unexplained pending row.
- [ ] Move completed execution evidence into `docs/plans/completed/` only after
      its immutable archive contract is updated deliberately.

## 14. Corrected green commit slices

1. [x] FC0 provider probes, compatibility snapshots, corrected API contracts,
       and documentation only (commit `c91a0d9`).
2. [x] `ImuCalibration`/`ImuSequence`, compatible `ImageSequence` acquisition
       fields, and record tests; locally green, with hosted wheel validation
       still pending.
3. [ ] `VisualInertialDataset` plus provisional dataset read/write/inspect,
       oracle suite, benchmark, and docs; omit the registry id if FC0 rejects it.
4. [ ] `LabelTaxonomy` and dense label records plus NPZ/Zarr/NCore carriers,
       Kubric evidence, benchmark, and docs.
5. [ ] `PointScan`/`ScanSet` plus E57 multi-scan/structured read/write/inspect,
       oracle suite, benchmark, and docs.
6. [ ] Neutral raster collection plus the qualified TIFF read/write subset,
       oracle suite, benchmark, and docs.
7. [ ] OpenVDB read/inspect/grid-selection expansion or evidence-backed
       exclusion, retaining the current one-grid writer.
8. [ ] USD selected-time qualification through the existing API, followed by
       `SceneAnimation`/dynamic writing only if both directions pass.
9. [ ] Per-provider hosted correction commits, if platform results require
       focused changes.
10. [ ] FC7 exact-head package, aggregate hosted validation, and final evidence.

Do not combine slices merely to reduce commit count. A slice may be split when
its record and codec changes cannot be reviewed or reverted independently.

## 15. Program completion matrix

| Unit | Record/API | Read | Write | Inspect | Partial | Oracle per supported direction | Large benchmark | Local suite | Hosted wheels | Docs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FC1A IMU records/acquisition | [x] | n/a | refusal-only | n/a | n/a | [x] record vectors | n/a | [x] | pending/user-gated | [x] |
| FC1B visual-inertial dataset | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| FC2 dense labels | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| FC3 E57 scans | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| FC4 TIFF collections | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| FC5 OpenVDB expansion | conditional | [ ] | existing one-grid | [ ] | [ ] | expanded-read + base-write | [ ] | [ ] | [ ] | [ ] |
| FC6 dynamic USD | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| FC7 aggregate | n/a | n/a | n/a | n/a | n/a | [ ] | [ ] | [ ] | [ ] | [ ] |

## 16. Final stopping rule

The follow-on program is closed when FC1-FC6 satisfy the matrix and FC7 passes.
At that point:

- the registry remains at 73 built-ins or reaches 74 only if the provisional
  visual-inertial directory codec passes every format gate;
- all new behavior is constrained by versioned 3D-CV profiles;
- every supported read/write direction has independent evidence, and every
  unsupported direction has a tested capability/refusal entry;
- current simple-format behavior remains compatible;
- normal CI uses no network data and the base runtime remains NumPy-only; and
- every broader upstream-standard feature is documented as refused or future,
  not treated as unfinished work in this program.
