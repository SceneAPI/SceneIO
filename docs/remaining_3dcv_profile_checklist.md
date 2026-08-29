# Finite 3D-CV profile closure checklist

- **Status:** FC0-FC4 and FC6 are validated as of 2026-08-29; FC5 is closed by
  evidence-backed exclusion. Exact implementation candidate
  `9a20bc61f177c28ba228b89e80cff665e3f1b426` passes the complete local gate,
  strict benchmark, exact source closure, Linux/macOS/Windows installed-wheel
  matrix, OpenUSD and Niantic SPZ oracles, standard CI, and ASan/UBSan in
  nonpublishing Release run
  [`33249900572`](https://github.com/SceneAPI/SceneIO/actions/runs/33249900572)
  and its linked final runs. FC7's technical and evidence gates are closed;
  the existing PR remains a mergeable draft pending the user's review-state
  decision, and publication remains a separate tag-driven action.
- **Baseline:** 74 built-in formats, each mapped to a licensed direct fixture
  or deterministic oracle-derived route.
- **Purpose:** close the remaining 3D-computer-vision representation and
  bounded-profile gaps without turning SceneIO into a general scientific,
  media, or scene-authoring framework.
- **Authority:** current shipped capability remains
  [`format_coverage.md`](format_coverage.md). This document owns only the
  dependency order and acceptance checklist for the finite follow-on work.
- **Execution plan:**
  [`remaining_gap_implementation_plan.md`](remaining_gap_implementation_plan.md)
  turns this checklist into ordered work packages, file/API change surfaces,
  validation commands, provider decision gates, and commit boundaries.
- **Machine decision contract:**
  [`remaining_3dcv_fc0_v1.toml`](../tests/contracts/remaining_3dcv_fc0_v1.toml)
  freezes the stable signatures, provisional names, provider observations,
  legacy projections, and registration gate used by FC0.
  [`visual_inertial_records_v1.toml`](../tests/contracts/visual_inertial_records_v1.toml)
  freezes the implemented FC1A fields, units, vocabularies, and equations.
  [`euroc_dataset_v1.toml`](../tests/contracts/euroc_dataset_v1.toml) freezes
  the qualified FC1B layout, transform, timing, selection, write, and oracle
  contract. [`dense_label_maps_v1.toml`](../tests/contracts/dense_label_maps_v1.toml)
   freezes the implemented FC2 record fields, versioned carrier schemas,
   NCore projection boundary, and oracle-recipe status.
  [`gaussian_semantics_v1.toml`](../tests/contracts/gaussian_semantics_v1.toml)
  freezes the validated G1 quaternion, SH, color, coordinate, scale,
  quantization, and carrier mappings.

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
| USD already exposes selected-time input | `read_scene(..., time=...)` and `SceneGraph.selected_time` existed while the FC0 provider probe reported `selected_time=False`; FC6 state B now qualifies the bounded direct-USDA subset | Redundant methods and contradictory behavior; [AIP-180](https://google.aip.dev/180) | [x] Activate the existing `time` parameter; keep `SceneAnimation` absent because preservation/write did not qualify |
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

- [x] One ASL/EuRoC-style visual-inertial directory profile containing camera
      streams, camera and IMU calibration, IMU samples, and optional ground
      truth.
- [x] Exact per-frame exposure and rolling-readout metadata on
      `ImageSequence`.
- [x] Typed `SemanticMap`, `InstanceMap`, and `PanopticMap` records and explicit
      adapters for carriers that can preserve them.
- [x] Multiple Cartesian E57 scans, including raw validity and sparse
      row/column organization plus per-scan rigid poses.
- [x] Homogeneous 3D-CV TIFF series and image pyramids with explicit axes.
- [x] Close the proposed OpenVDB multi-grid profile by evidence-backed
      exclusion because TinyVDB cannot preserve or select the required grids;
      retain and harden the existing one-grid profile.
- [x] USD time-sampled node transforms and visibility with static payload
      topology in selected-time state B.

### Explicit non-goals

- [x] Do not add a general ROS bag, MCAP, or arbitrary sensor-log reader.
- [x] Do not ingest video streams from visual-inertial datasets; image paths or
      already-supported image sequences remain the carrier.
- [x] Do not add FFmpeg code, binaries, bindings, or a runtime dependency.
- [x] Do not implement arbitrary OME microscopy axes, vendor TIFF tags, or a
      general metadata editor.
- [x] Do not add E57 spherical/cylindrical coordinates, embedded imagery, or
      arbitrary extension schemas in this closure.
- [x] Do not add arbitrary OpenVDB tree types, point grids, nonlinear
      transforms, inactive-tile fidelity, or level-set editing.
- [x] Do not claim multi-grid/vector/transformed OpenVDB writing through
      TinyVDB 0.9; its current file API cannot add a grid or mutate a transform.
- [x] Do not add USD layer authoring, variants, references/payload composition,
      value clips, deforming topology, general shader graphs, rendering, or
      simulation schemas.
- [x] Do not reopen JPEG-XL, Draco, generic Arrow schemas, or formats unrelated
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

- [x] Land one record/API unit at a time.
- [x] Keep record-only commits adjacent to the first codec commit that uses
      them; do not land unused speculative types.
- [x] Do not mix repository moves, provider replacement, or unrelated
      optimization with a profile-expansion commit.
- [x] Preserve the current optional-provider boundaries and NumPy-only base
      runtime.
- [x] End every green implementation commit with the required co-author line.

## 5. Universal acceptance contract

Every FC1-FC6 unit must satisfy all applicable boxes in this section.

### 5.1 Representation contract

- [x] Define shape, dtype, ownership, ordering, optional-field presence, units,
      coordinate frame, pose direction, quaternion order, timestamp epoch, and
      time reference before implementing I/O.
- [x] Add the representation to `sceneio.representation_contract(...)` and the
      exhaustive public-representation discovery test.
- [x] Add or update coordinate contracts for every affected format.
- [x] Preserve source values when the record can represent them; otherwise
      reject instead of guessing. Record construction uses
      `ContractViolation`/`ValueError`; the public I/O facade normalizes codec
      failures to `FormatError`.
- [x] Make any conversion an explicit public operation with forward/backward
      tests against an independent mathematical reference.
- [x] Retain existing constructor calls, defaults, return types for currently
      supported files, and raw compatibility APIs.

### 5.2 Fixture and oracle contract

- [x] Add every new source, revision, artifact digest, license, attribution,
      and delivery decision to
      [`public_fixture_sources_v1.toml`](../tests/contracts/public_fixture_sources_v1.toml).
- [x] Keep normal tests offline; acquisition writes only to an ignored cache.
- [x] Require oracle-written -> SceneIO-read coverage.
- [x] Require SceneIO-written -> oracle-read coverage for every supported
      write direction; excluded directions retain tested refusals.
- [x] Keep SceneIO self-round-trip as supplementary evidence, never the sole
      evidence.
- [x] Compare every represented array and convention field; do not reduce
      parity to dimensions or element counts.
- [x] State exact equality, byte equality, or a justified numeric tolerance per
      field.
- [x] Retain valid broader-profile artifacts as expected-refusal vectors.

### 5.3 Public I/O contract

- [x] `write -> detect -> inspect -> read` passes through the public API for
      supported write directions.
- [x] `inspect` obtains structural metadata without decoding bulk samples.
- [x] Every collection profile has a bounded selector whose result equals the
      corresponding full-read slice.
- [x] Direct-file writes are transactional and do not build an output-sized
      Python `bytes` object.
- [x] Mapped or provider-owned inputs remain valid for the lifetime of every
      exposed array view.
- [x] Empty, singleton, large, truncated, inconsistent, unsupported-profile,
      and destination-replacement cases have focused tests.
- [x] Capabilities list supported and refused subfeatures exactly.
- [x] Public errors begin with stable operation, format id, and refused-feature
      context; tests do not make provider wording part of the public contract.

### 5.4 Performance and resource contract

- [x] Add a representative builder and oracle comparison to `bench/bench_io.py`
      or a dedicated typed-profile benchmark where the generic selector model
      cannot express the operation.
- [x] Measure every applicable full read, selected read, inspect, write,
      encoded size, `tracemalloc`, warmed-parent RSS, and strict fresh-process
      RSS; state-B preservation read/write remain explicit non-applications.
- [x] Include one generated 64-128 MiB logical payload per implemented
      profile; add a larger case only where it materially exercises a measured
      chunk or selection boundary.
- [x] Prove inspect and selected reads allocate materially less than full
      decode for large fixtures where a full decode exists; FC6 state B has no
      preservation read to mislabel as a full-animation control.
- [x] Record same-machine before/after and SceneIO/oracle results in the
      benchmark ledger; do not introduce brittle cross-machine absolute SLAs.
- [x] Run the lifetime/resource, format-correctness, and test-soundness review
      and resolve every finding before commit.

### 5.5 Documentation and platform contract

- [x] Update `format_coverage.md`, `coverage_roadmap.md`, public API docs,
      representation normalization, coordinate conventions, and this
      checklist in the implementing commit.
- [x] Update installed-wheel smoke for every new symbol, selector, provider
      extra, and supported/refused feature.
- [x] Verify the optional dependency is absent from the base import graph.
- [x] Verify the source archive and wheels contain required license and
      attribution files but no downloaded dataset cache.
- [x] Pass the exact-candidate Linux/macOS/Windows package lanes before
      upgrading locally complete units to `validated`.

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
- [x] Pin the existing `read_scene(..., time=...)` signature and its
      then-current FC0 refusal; FC6 later activates that same signature without
      adding another method.
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
- At this FC1A checkpoint, Linux/macOS wheel validation was still pending and
  no hosted run had been triggered. The later exact-commit installed-wheel
  smoke in run `30914739031` supersedes that package-level status.

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

- [x] Store one `CameraRig`, ordered IMU calibrations, ordered named camera
      streams, ordered IMU streams, and optional `StateTrajectory` ground truth
      without copying child arrays.
- [x] Validate sensor ids/topics against the rig and reject duplicate names.
- [x] Declare one timestamp epoch and clock domain per stream; do not align or
      interpolate clocks implicitly.
- [x] Carry dataset-root-relative image names as inert paths.
- [x] Define partial selection by camera, IMU sensor, frame range, and
      nanosecond interval on the format-specific dataset API; do not extend the
      global `read_partial` signature for compound sensor selection.
- [x] Test child lifetime after the aggregate and local path handles leave
      scope.

### 7.5 `euroc_dataset` directory adapter

- [x] Implement repository-owned layout parsing in
      `src/sceneio/io/_euroc_dataset/` and register it under the dataset
      family.
- [x] Support the bounded ASL layout: `mav0/cam*/data.csv`, image paths,
      `sensor.yaml`, `mav0/imu*/data.csv`, and optional state ground truth.
- [x] Preserve calibrated intrinsics, distortion, camera/IMU extrinsics,
      sensor rate/noise/random-walk metadata, clock offsets, and nanosecond
      timestamps.
- [x] Write a deterministic bounded directory with relative paths and atomic
      destination replacement.
- [x] Keep image bytes opaque; do not transcode or add a video path.
- [x] Add `inspect` counts, time ranges, sensor names, resolutions, and presence
      flags without reading image payloads.
- [x] Add camera/frame/time/IMU selection to the format-specific dataset API
      and verify it against full reads.
- [x] Reject unsupported sensor types, duplicate timestamps, missing files,
      ambiguous transforms, and inconsistent CSV/YAML rows.

### 7.6 FC1 oracle and data

- [x] Use the pinned CC-BY-4.0 Monado ASL layout as the public fixture source;
      keep official EuRoC bytes excluded from redistribution and hosted use.
- [x] Use Fire Actioncam `meta.npz` only to qualify exposure/readout mapping,
      with NumPy as the independent parser.
- [x] Build a tiny deterministic ASL directory from the pinned permissive
      values for offline write/read tests.
- [x] Compare YAML calibration with Kalibr/CamTools equations and CSV values
      with an independent stdlib/NumPy parser.
- [x] Add hand-computable clock-offset, quaternion-order, acquisition
      direction, and dataset pose-direction fixtures.

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

- [x] `euroc_dataset` reads, writes, inspects, and partially selects the bounded
      directory profile.
- [x] All temporal fields have exact units and reference semantics.
- [x] Existing sequence codecs remain byte/value compatible.
- [x] The fixture, coordinate, representation, registry, and documentation
      contracts agree on 74 built-ins.

### 7.7 FC1B local qualification result

- The rebuilt MSVC extension exposes native mapped-buffer IMU inspection,
  full/time-range reads, and direct sink writing. Public discovery, inspection,
  read/write, typed selection, installed-wheel smoke, coordinate,
  representation, fixture, oracle, benchmark, architecture, and compatibility
  contracts agree on the 74th format.
- The final complete local run passes 4,753 tests with 16 documented
  optional/platform skips in 411.87 seconds. Repository-wide Ruff, the
  generated documentation contract, and `git diff --check` pass.
- The five-run generated 6.858 MB directory baseline records 319.7 MB/s public
  mapped read with 0.118 MB traced overhead, 0.047 MB inspection allocation,
  and a 2.081 ms bounded selection versus about 16.65 ms for full public read.
  It is an initial format baseline, not a fixed numeric threshold.
- At this FC1B checkpoint, Linux/macOS wheel and hosted Monado validation were
  still pending. The later exact-commit installed-wheel smoke in run
  `30914739031` covers the bounded EuRoC package path; it does not replace the
  independent local Monado oracle evidence above.

### 7.8 FC1B three-lens review

- **Lifetime/resource:** each native call pins its contiguous input until GIL-
  released parsing completes, decoded IMU vectors own their storage, and the
  Python mapping closes only after the native call returns. Child array views
  outlive the dataset aggregate, Windows rename proves mappings/file handles
  are released, camera paths remain lazy, and transactional staging preserves
  an existing destination on failure.
- **Behavior correctness:** the independent parser confirms ASL `T_BS` as
  sensor-to-body, WXYZ quaternion order, metres/SI values, exact int64-ns
  timestamps, signed camera clock offsets, half-open selection, and all
  read/write fields. The writer refuses unsupported units, frames, metadata,
  layouts, duplicate names/IMU ids, and non-contiguous sensor indices instead
  of converting or dropping them.
- **Test soundness:** PyYAML, stdlib CSV, and SciPy rotation code do not reuse
  the production parser; Kalibr/CamTools pin semantic direction. Tests cover
  oracle-authored and SceneIO-authored directories, bytes versus mmap,
  mutation isolation, empty/truncated rows, lifetime, inspection without image
  decode, typed slices versus full reads, deterministic output, and staged
  failure. Review found and fixed incomplete writer-oracle assertions: every
  intrinsic, distortion, topic, offset, noise term, transform, state field,
  CSV row, and copied image now participates. No unresolved FC1B finding
  remains.

## 8. FC2 — semantic, instance, and panoptic raster maps

### 8.1 Records

- [x] Add immutable NumPy-native records in `sceneio.data.dense`.
- [x] `LabelTaxonomy`: unique `int32` semantic ids, ordered names, optional
      display colors, and optional thing/stuff flags; taxonomy identity and
      version are explicit strings rather than inferred from names.
- [x] `SemanticMap`: `int32 (H, W)` class ids, optional boolean validity,
      an optional `LabelTaxonomy`, and explicit void id.
- [x] `InstanceMap`: `int64 (H, W)` instance ids, optional boolean validity,
      explicit background id, and optional unique `int64 -> int32`
      instance-to-semantic table.
- [x] `PanopticMap`: composed `SemanticMap` and `InstanceMap` with identical
      shape/validity plus explicit void and background semantics; do not copy
      child arrays or assume a packed divisor encoding.
- [x] Require C-contiguous arrays, equal shapes, finite integer-domain values,
      and consistent instance/class tables.
- [x] Define packed panoptic encodings only as explicit converters whose
      divisor, void id, and overflow behavior are caller-visible.
- [x] Keep `Mask(True = participates)` unchanged and use it only for validity,
      never as an integer label carrier.

### 8.2 Typed carrier adapters

- [x] Add strict typed projections for NCore `SEGMENTATION` camera-label
      qualifiers (`semantic`, `instance`, and `panoptic`). Keep static NCore
      camera masks as boolean `Mask` projections.
- [x] Add versioned NPZ/Zarr schemas for semantic, instance, and panoptic maps.
- [x] Add a TIFF typed path only when the caller supplies a label contract or a
      versioned `sceneio.label_map/1` description tag declares the kind and
      taxonomy; never infer semantics from integer pixels.
- [x] Treat a TIFF without that declaration as a raster projection only. Refuse
      a typed write when non-default semantics would be lost.
- [x] Preserve raw NPZ/Zarr `TensorDict` behavior plus raw TIFF and NCore
      behavior; typed entry points do not change ordinary reads.
- [x] Refuse incomplete, unknown, or lossy generic-carrier schema fields rather
      than inferring a palette or taxonomy.

### 8.3 FC2 oracle and data

- [x] Define one tiny deterministic 32x32, two-frame procedural Kubric scene
      with RGBA, depth, instance ids, object poses, and optical flow. Semantic
      ids are an explicit SceneIO taxonomy mapping, not a Kubric-emitted claim.
- [x] Pin the Kubric revision and generation parameters. Use only Kubric's
      Apache-2.0 procedural Cube/Sphere primitives; do not use its external
      KuBasic asset manifest or a hosted MOVi artifact.
- [x] Keep Kubric/Blender out of normal CI. Store only a compact attributed
      deterministic result or reconstruct the checked numeric arrays from a
      compact regeneration manifest; run full regeneration in an opt-in lane.
- [x] Execute the opt-in recipe. Its single `generate` operation validates
      typed maps, fixed poses, unit WXYZ quaternions, flow ranges/conversion,
      and runtime provenance before atomically recording the resulting hashes.
      The accepted run used Blender 4.3.0/Python 3.11 and published 11 compact
      artifacts totaling 23,781 bytes.
- [x] Cross-read NPZ carriers with NumPy in both directions, stored and
      deflated.
- [x] Cross-read Zarr v2/v3 carriers with the official Zarr implementation in
      both directions.
- [x] Cross-read the typed TIFF carrier with tifffile in both directions,
      including classic TIFF, BigTIFF, endian variation, and page metadata.
- [x] Test non-contiguous views, void pixels, large ids, empty instance sets,
      invalid table references, and mixed semantic/instance backgrounds.

### FC2 exit

- [x] All three maps round-trip through at least one lossless generic carrier.
- [x] NCore projection produces the same canonical maps as its independent
      component parser.
- [x] Typed TIFF requires explicit meaning and cannot misclassify an ordinary
      grayscale image.
- [x] Coordinate and normalization contracts cover all new public records.

### 8.4 Typed-carrier local qualification result

- `LabelTaxonomy`, `SemanticMap`, `InstanceMap`, and `PanopticMap` are public
  NumPy-native records. The normalization catalog now contains 98 exact
  representations, and image-aligned map records use `IMAGE_COORDINATES`.
- `sceneio.label_map/1` reads, writes, and inspects exact NPZ, Zarr v2/v3, and
  TIFF schemas while preserving all raw carrier behavior. TIFF requires an
  exact description or caller contract. Inspection reads container/page
  metadata without decoding raster samples.
- NumPy, official Zarr, and tifffile writers/readers verify both directions.
  NCore uses only exact `SEGMENTATION` qualifiers plus a descriptor-owned
  `__sceneio_label_map_v1__` extension; unknown, incompatible, per-item, and
  unmarked typed fields are refused. A manually authored component fixture
  crosses the NCore profile parser before projection, and SceneIO-written
  components reopen through the repository reader with exact descriptors.
- Normal CI uses a hand-evaluated vector for Kubric's pinned
  `adjust_segmentation_idxs` rule and verifies all hashes of the generated
  procedural scene without installing Kubric or Blender. The fixture has no
  external asset manifest. Generation and hash recording remain one validated,
  atomic operation; the checked-in result is accurately reported as generated.
- On the generated 64 MiB low-entropy semantic fixture (MSVC, three warm-cache
  runs), the post-review typed NPZ read is 379 MB/s with 8.02 MiB traced peak,
  versus 182 MB/s and 25.01 MiB before the bounded membership fast path. Typed
  Zarr v3 read is 839 MB/s with 92.5 MiB fresh-process RSS, versus 237 MB/s and
  144.6 MiB before direct retention of decoded NumPy arrays. The direct Zarr
  writer is 699 MB/s versus 626 MB/s through the staged `TensorDict` adapter.
  NPZ inspection is 1.63 ms/0.051 MiB traced and Zarr inspection is 25.76
  ms/0.168 MiB traced. Typed TIFF writes at 1,802 MB/s and reads at
  1,571 MB/s on the same 64 MiB fixture; the tifffile comparison boundary is
  documented in `bench/LABEL_MAPS.md`.
  These values are same-machine evidence, not portable thresholds. Stored NPZ
  native decoding still peaks at 256 MiB RSS because the existing miniz path
  stages member buffers; that optimization is recorded, not hidden.
- The FC2 implementation/adapters and procedural Kubric evidence are locally
  complete. Regeneration remains explicit. User-authorized build-only Release
  run `30914739031` passed exact-commit Linux, Windows, and macOS installed
  wheel smokes, the combined inventory, and the dedicated OpenUSD/Niantic
  oracle jobs; PyPI publication was skipped.
- The exact local tree collects 4,954 tests and passes 4,938 with 16 documented
  optional/platform skips. The provider-independent CI collection contract is
  4,919 unique nodes. Ruff, the installed-wheel smoke, compatibility snapshots,
  and the focused 64 MiB benchmark are green. The generated Kubric directory
  contains 11 artifacts totaling 23,781 bytes; every artifact SHA-256 is
  frozen in `tests/fixtures/kubric_procedural_tiny_v1.json`.

### 8.5 Generic-carrier three-lens review

- **Lifetime/resource:** NPZ decode owns returned storage and releases the
  mapping before return; Zarr typed reads retain owned NumPy arrays directly
  and no longer copy them through `TensorDict`. Child records keep their arrays
  alive, typed inspection avoids bulk decode, direct NPZ writes avoid a second
  output-sized Python `bytes`, and staged replacement preserves destinations
  on failure. TIFF validates and decodes through one open file and bounds its
  uint8 validity check without a raster-sized temporary. Canonical RAW NCore
  labels retain their already-owned arrays. Zarr replacement uses unique
  recovery names, and cleanup failure after commit cannot block the next write.
- **Behavior correctness:** dtypes, contiguity, shape, void/background ids,
  taxonomy identity/version, optional fields, instance tables, validity, and
  explicit packed-divisor overflow are guarded. Unknown schema arrays and
  carrier-specific options on the wrong backend are refused. Packed decoding
  promotes small integer inputs without losing `uint64`, accepts negative void
  metadata, and validates schema metadata plus the version marker before bulk
  payload decode.
- **Test soundness:** independent NumPy/Zarr/tifffile writers and readers cover
  both directions, all three map variants, and every represented field; the
  Kubric rule is explicitly labeled hand-evaluated rather than a generated-scene
  oracle. Its opt-in result validator independently checks renderer identity,
  visibility, projected object centers, fixed camera look-at, and forward-flow
  order/direction before hashes can be recorded. Large-memory,
  mutation-isolation, file-release, malformed-schema, transactional-failure,
  raw-compatibility, and no-full-decode inspection tests are distinct.

## 9. FC3 — E57 multiple Cartesian scans

**Status (2026-08-29): locally and package complete.** The
typed API is additive: generic `sceneio.read` keeps its one-scan `PointCloud`
projection, while the four explicit E57 scan functions expose stored rows,
organization, and ordered scan sets. The accepted profile is intentionally
Cartesian and exactly representable; broader E57 content remains a tested or
digest-pinned refusal.

### 9.1 `PointScan` and `ScanSet`

- [x] `PointScan` owns one `PointCloud` containing stored E57 rows plus optional
      raw `uint8` invalid-state values of the same length; zero means valid and
      nonzero values remain distinguishable.
- [x] Preserve optional raw `int64` row and column indices rather than forcing
      sparse organized scans into `PointCloud.width * height == point_count`.
- [x] Store declared row/column bounds separately and validate every index
      against them.
- [x] Store stable scan name/guid, optional acquisition timestamp, rigid pose,
      and source-coordinate metadata.
- [x] Make the `PointScan` pose authoritative. Keep the child cloud viewpoint
      neutral and have `valid_point_cloud()` apply the pose to the legacy
      `PointCloud.viewpoint`, avoiding two independently mutable copies.
- [x] Pin the exact E57 pose direction/quaternion ordering with pye57 and a
      hand-computable translated/rotated scan before naming public fields.
- [x] Provide an explicit `valid_point_cloud()` projection matching the legacy
      E57 reader's current valid-row behavior.
- [x] `ScanSet` owns ordered `PointScan` children and rejects duplicate scan
      identifiers and duplicate nonempty GUIDs.

### 9.2 E57 adapter expansion

- [x] Preserve current one-scan unorganized `PointCloud` return behavior; use
      the typed scan API for raw validity/organization.
- [x] Make typed `read_e57_scans` return `ScanSet`, make `read_e57_scan`
      return one `PointScan`, and accept `PointCloud`, `PointScan`, or
      `ScanSet` for typed writing.
- [x] Add `scan_index` and combined `scan_index` + half-open
      `stored_point_range` to the typed E57 scan API. Do not call a stored-row
      range a valid point range or add these compound values to global
      `read_partial`.
- [x] Inspect every scan's count, organization, bounds, fields, and pose
      without decoding point payloads.
- [x] Report stored counts from headers; report valid counts as unknown unless
      the provider exposes them without reading `cartesianInvalidState`.
- [x] Preserve supported Cartesian coordinates, intensity, RGB, row/column
      organization, and rigid pose fields per scan.
- [x] Retain the existing exact-float32 Cartesian and uint8-color boundary.
      Valid values must round-trip exactly; coordinate payloads on invalid rows
      are canonicalized to a documented placeholder because the invalid-state
      field, not those coordinates, carries meaning.
- [x] Keep imagery, non-Cartesian coordinates, unsupported extensions, and
      lossy field narrowing as explicit refusals.
- [x] Verify temporary output cleanup and destination preservation when a later
      scan fails to write.

### 9.3 FC3 oracle and data

- [x] Pin the official permissively granted five-scan Pump example and two
      broader profile examples by exact byte count and SHA-256. They are
      refusal vectors because their values or metadata exceed this profile.
- [x] Generate a tiny two-scan file with `pye57` in the provider probe, with
      distinct poses and exact Cartesian values.
- [x] Extend that generated case with invalid-state, row/column, and organized
      dimension fields as part of the FC3 record implementation.
- [x] Compare every scan with `pye57.read_scan_raw` and header metadata.
- [x] Have `pye57` reopen SceneIO's multi-scan output and compare scan order,
      poses, stored/valid counts, invalid-state values, row/column indices, and
      every valid point attribute.
- [x] Retain official examples containing imagery or unsupported extensions as
      digest-pinned, opt-in expected-refusal cases.

### FC3 exit

- [x] One- and multi-scan behavior is documented and direct-provider-proven in
      both directions.
- [x] Selected scan/range reads equal full-read slices.
- [x] Large multi-scan read/write measurements record time, traced allocation,
      and RSS. The fixed-capacity selected reader is bounded by chunk plus
      result size; the provider-buffered writer is measured without claiming
      an allocation improvement.

FC3's generated 3,145,728-row fixture contains 113.25 MB of logical payload.
On local Windows/MSVC, selecting 104,857 stored rows reduced traced peak from
151.00 MB to 11.33 MB and RSS growth from 148.83 MB to 11.07 MB versus direct
`pye57.read_scan_raw` plus slicing. Full measurements and limitations are in
[`e57_multiscan_benchmark.md`](e57_multiscan_benchmark.md).

Exact-head qualification rebuilt the editable package, passed the 64-test
focused E57/FC3 gate, passed the complete suite (4,962 passed, 16 documented
skips), and passed the five-run strict O4/O5/oracle benchmark retained at
`build/v0-benchmark-3fcdf81.json`. Nonpublishing Release run
[`33231962034`](https://github.com/SceneAPI/SceneIO/actions/runs/33231962034)
then passed its exact-source-distribution job, Linux/macOS/Windows installed
wheels, combined distribution inventory, OpenUSD 26.08 oracle, and Niantic SPZ
oracle at exact commit `3fcdf8195e8909e3e1cc2a6091a237f89af3bc41`;
the PyPI publish job was intentionally skipped.

### FC3 three-angle review

- **Ownership/lifetime:** native optional arrays expose zero-length views when
  absent; present views retain their record owner; `ScanSet` owns its children;
  projections and decoded arrays own their storage after provider handles and
  source files close. Low-level range readers and staged writers close in all
  paths.
- **Behavior correctness:** the WXYZ scan-to-reference pose is checked against
  pye57 and a hand-computable 90-degree Z rotation; exact float32/RGB8,
  invalid-state, bounds, scan-id, GUID, timestamp, and unsupported-field
  boundaries are guarded rather than narrowed.
- **Test soundness:** direct pye57/libE57Format authors input and reopens output
  as a format-owner differential (not a second parser lineage);
  public typed wrappers, range/full equivalence, no-full-decode inspection,
  ownership, transactional failure, official-file boundaries, and measured
  large-fixture behavior are separate tests or evidence rows.

## 10. FC4 — bounded TIFF series and pyramids

### 10.1 neutral raster collection model

- [x] Define `RasterLevel`, `RasterSeries`, and `RasterCollection` as
      format-neutral immutable Python records.
- [x] Store ordered series/levels, explicit axes, dtype, shape, payload kind,
      and `Image`/`Mask`/`TensorDict` children that own their arrays.
- [x] Limit each series to the currently accepted CV raster/stack dtypes and
      axes.
- [x] Permit multiple series only when each series is independently
      unambiguous under the bounded profile.
- [x] Preserve the current `Image`, `Mask`, or `TensorDict` return for a simple
      one-series, one-level file.

### 10.2 TIFF adapter expansion

- [x] Fix frame/page metadata traversal so valid OME frames do not produce the
      current wrapped `TiffFrame.tags` failure.
- [x] Add `series_index`, `level_index`, `page_range`, and `window` to the
      typed TIFF collection API; define valid combinations without changing
      global `read_partial`.
- [x] Inspect all series/levels and report axes, shapes, dtypes, page counts,
      tile/strip layout, and BigTIFF status without decoding samples.
- [x] Read only the selected series/level/page/window when tifffile exposes a
      bounded path; document unavoidable provider granularity.
- [x] Write deterministic homogeneous series and pyramid files through
      tifffile and reopen them before atomic replacement.
- [x] Confirm the exact bounded SubIFD/series writer layouts on hosted Linux
      and macOS; Windows write/reopen is green. If either hosted provider
      differs, keep that layout read/select-only and report the capability
      boundary before upgrading FC4 from locally complete to validated.
- [x] Reject ambiguous OME axes, structured dtypes, mixed unsupported
      photometric interpretations, and metadata that the record would drop.
- [x] Keep arbitrary OME-XML editing outside the profile.

### 10.3 FC4 oracle and data

- [x] Pin the checked CC-BY-4.0 OME-TIFF 4D file and one permissive pyramid
      sample or generate the pyramid independently with tifffile.
- [x] Compare series/level/page/window arrays and metadata with tifffile.
- [x] Have tifffile reopen SceneIO-written classic TIFF and BigTIFF variants.
- [x] Test tiled and stripped files, endian variants, one/many pages, and
      selected reads that cross tile/strip boundaries.

### FC4 exit

- [x] The previously checked OME file either reads under the bounded profile or
      fails with a deliberate documented boundary, never an incidental
      provider attribute error.
- [x] Simple TIFF compatibility is unchanged.
- [x] Pyramid/series selection shows a measured memory advantage over full
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
- [x] Test multi-grid files containing every candidate value/tree type before
      declaring that type readable.
- [x] Test whether selecting one grid avoids materializing other grids; do not
      advertise bounded selection based only on a post-decode slice.
- [x] Evaluate the official OpenVDB binding as an oracle author; retain
      TinyVDB after the alternative-provider wheel/intake gate fails. Do not
      pull full OpenVDB/Boost/TBB into release wheels for this excluded profile.
- [x] Choose documented provider exclusion and record it in
      `tests/contracts/openvdb_provider_limits_v1.toml`.

### 11.2 read/inspect/select profile

- [x] Keep `SparseGrid` and `SparseVolumeSet` absent rather than exporting
      records that promise values and metadata TinyVDB cannot preserve.
- [x] Do not claim multiple-grid read: TinyVDB only decompresses all grids and
      loses candidate vector and empty-grid semantics.
- [x] Do not add `grid_name`, `grid_index`, or bounds selectors without a
      bounded provider operation.
- [x] Limit header-only provider evidence to grid count, names, and types;
      richer metadata requires all-grid decode and is not exported.
- [x] Preserve the legacy identity-transform boundary; nonempty-scalar affine
      reads remain provider evidence, not a public-record claim.
- [x] Continue refusing unsupported tree/value types, point grids, nonlinear
      transforms, inactive-tile semantics, and level sets.
- [x] Ensure USD volume assets retain their exact authored grid name and never
      silently default to the first grid.
- [x] Retain the legacy nonempty identity scalar `TensorDict` read/write path.
- [x] Keep multiple/vector/transformed public writes discoverably unsupported.

### 11.3 FC5 oracle and data

- [x] Generate scalar density and three-component velocity grids with distinct
      affine transforms through official OpenVDB.
- [x] Author with official OpenVDB and cross-read with TinyVDB locally; retain
      the generator for the optional hosted lane.
- [x] Keep the existing one-grid SceneIO-write -> TinyVDB-read oracle as the
      write-direction evidence; do not mislabel it as multi-grid parity.
- [x] Use official OpenVDB-authored values as the format-owner side of the
      provider-loss comparison; no expanded positive profile is claimed.
- [x] Test duplicate names, affine transforms, nonzero backgrounds, empty
      grids, negative coordinates, and unsupported grid classes.

### FC5 exit

- [x] Legacy nonempty single identity-grid files retain their compatibility
      return path.
- [x] Multi-grid read and exact selection are explicitly excluded with
      executable provider evidence.
- [x] Multi-grid/vector/transformed writes remain listed as unsupported unless
      a later provider qualifies both directions.
- [x] No selected-grid memory claim is made because the provider has no
      selected-grid operation; post-decode slicing does not qualify.

## 12. FC6 — bounded dynamic USD

FC6 closes in **state B: selected-time read only**. TinyUSDZ 0.9.4 enumerates
matrix sample times but exposes untyped values and does not expose visibility
sample values. SceneIO therefore adds a bounded repository-owned evaluator for
provider-normalized, directly authored USDA prim text; it does not claim USDC
or general USDA parsing.

### 12.1 provider, grammar, and API

- [x] Preserve the existing `read_scene(path, time=...)` method and
      `SceneGraph.selected_time`; add no competing time method.
- [x] Probe USDA, USDA-root USDZ, and qualified historical USDC sample
      exposure and record the provider's untyped-value boundary.
- [x] Freeze a structural matrix/token grammar with explicit prim-text, line,
      token, string, and 65,536-sample-per-property limits.
- [x] Support only `matrix4d xformOp:transform.timeSamples` with one matrix op
      and `token visibility.timeSamples` with inherited/invisible values.
- [x] Match OpenUSD 26.8 component-wise matrix interpolation, held tokens, and
      held endpoints at exact, between, negative, and fractional times.
- [x] Set `selected_time` only when at least one accepted sample table was
      actually evaluated.

### 12.2 explicit state-B exclusions

- [x] Keep `SceneAnimation` absent because authored sample preservation and
      deterministic two-direction writing did not qualify.
- [x] Keep `dynamic_write`, `authored_animation_preservation`, USDC selected
      time, composition, clips, arbitrary sampled xform stacks, and sampled
      payload values in the unsupported capability set.
- [x] Permit writing an evaluated result only as a static snapshot and prove
      that no `.timeSamples` declaration is emitted.
- [x] Keep topology, meshes, points, Gaussians, cameras, materials, volumes,
      instances, and semantic payloads static.

### 12.3 evidence and exit

- [x] `tests/codecs/test_usd_animation.py` covers the two-node/three-transform
      fixture, visibility, a static Gaussian, hierarchy/selection/reset stacks,
      USDA/USDZ, malformed limits, and refusal paths.
- [x] `tests/codecs/test_openusd_animation_oracle.py` executes 22 official
      OpenUSD 26.8 comparisons when the optional oracle is installed.
- [x] `tests/contracts/usd_selected_time_v1.toml` freezes state B, semantics,
      limits, inspection fields, capabilities, and nonclaims.
- [x] Inspection reports sampled properties/count/range and whether the root
      representation supports selected-time evaluation.
- [x] The retained 256-node/6,912-sample benchmark measures selected read,
      inspection, equal-node static control, traced allocation, and RSS in
      `docs/usd_animation_benchmark.md`.

FC6 is validated in state B. Final candidate Release run `33249900572` passed
the dedicated OpenUSD 26.08 comparisons and installed-wheel confirmation.

## 13. FC7 — combined qualification and closure

### 13.1 Local aggregate gate

- [x] Rebuild after every C++/CMake change with
      `uv pip install -e ".[dev,test]"`.
- [x] Verify every new `_core` symbol from the repository interpreter.
- [x] Run focused record and codec suites after each unit.
- [x] Run the registry-driven public API, oracle, partial-read, mapping
      lifetime, documentation, package-inventory, and installed-wheel smoke
      tests.
- [x] Run the complete suite and repository-wide Ruff.
- [x] Run `git diff --check` and review the complete diff for unrelated edits.
- [x] Run the five-run benchmark guard and record new rows/deltas.

Local result on 2026-08-29: 5,066 collected registry nodes; 5,082 tests pass
with 19 reviewed optional/platform skips. Ruff, documentation, lock, and diff
checks pass. `build/fc7-post-memory-strict-benchmark.json` passes every strict
O4/O5 guard.
The retained 64 MiB TIFF and 65.89 MiB USD profiles each add three strict
fresh-process RSS samples per applicable operation.

### 13.2 Package and hosted gate

Final exact-candidate evidence: nonpublishing Release run
[`33249900572`](https://github.com/SceneAPI/SceneIO/actions/runs/33249900572)
passed the exact source archive, three-wheel matrix, combined provider smoke,
distribution inventory, OpenUSD 26.08, and Niantic SPZ jobs at commit
`9a20bc61f177c28ba228b89e80cff665e3f1b426`. Publication was intentionally
skipped because this was a manual build, not a version tag.

- [x] Build the source archive and clean Windows abi3 wheel from the exact
      local candidate snapshot; repeat the build from the immutable candidate
      commit in the hosted matrix.
- [x] Install the base wheel with NumPy only and prove every optional provider
      remains lazy.
- [x] Install each affected extra separately and run its installed-wheel smoke.
- [x] Verify source archive and wheel license inventories.
- [x] Exercise affected providers during candidate hardening and land focused
      corrections for hosted findings before the final FC7 run.
- [x] Push and trigger Linux/macOS/Windows build-only validation only after the
      local candidate is green and the user authorizes that exact action.
- [x] Run hosted OpenUSD/OpenVDB and large-data comparisons without adding
      those packages or datasets to normal CI.
- [x] Record workflow links, artifact hashes, platform results, optional skips,
      and benchmark summaries in the coverage documents.

The hosted source closure contains 1,624 expected files plus `PKG-INFO`, with
source-tree SHA-256
`18587c6a573a306f54e8d49cba9e8623fb04183e4b948e7e713d74548922c95a`.
Independent base, TIFF, OpenVDB, USD, and NCore Python 3.12 environments load
the wheel from `site-packages`, expose only their intended optional capability,
and pass `python -I -m sceneio._wheel_smoke`. The sdist payload SHA-256 is
`15eb2e13b44a84a423a9fe075c7a2265c4348f16ca45758a762376dcc10b9d1c`;
macOS, manylinux, and Windows wheel payloads are respectively
`3c4d95189bd5e01fc528d7918e1a5c668180ce67493069bddd789a3c224f6487`,
`4592504f971810d0e25f1719d34e683fac1ad758946905130ba91de157c3e08d`,
and `bb567c00961e94ad784294861b5ebaee817296aacf68e81d394df04cc8715750`.
The complete nine-artifact payload/archive digest ledger is in
[`remaining_gap_implementation_plan.md`](remaining_gap_implementation_plan.md#93-distribution-and-hosted-gate).

Both final CI copies
([push `33249897819`](https://github.com/SceneAPI/SceneIO/actions/runs/33249897819),
[PR `33249899654`](https://github.com/SceneAPI/SceneIO/actions/runs/33249899654))
and both sanitizer copies
([push `33249897883`](https://github.com/SceneAPI/SceneIO/actions/runs/33249897883),
[PR `33249899660`](https://github.com/SceneAPI/SceneIO/actions/runs/33249899660))
pass. The retained five-run strict benchmark is
`build/fc7-post-memory-strict-benchmark.json`, SHA-256
`3b1bcdae188d111865826edc258e485c8a3ea4e645660d3cfab14fb4eb335bcb`.

### 13.3 Final documentation reconciliation

- [x] Generate/validate registry capability tables from the current 74-format
      runtime before final FC7 closure.
- [x] No provisional dataset format landed; public-fixture manifest route/count
      changes are not applicable.
- [x] Confirm every new public representation is present exactly once in the
      normalization contract.
- [x] Confirm every affected format has a coordinate contract and executable
      evidence.
- [x] Mark each profile `validated` or `excluded`; leave no unexplained pending
      row.
- [ ] Move completed execution evidence into `docs/plans/completed/` only after
      its immutable archive contract is updated deliberately.

## 14. Corrected green commit slices

1. [x] FC0 provider probes, compatibility snapshots, corrected API contracts,
       and documentation only (commit `c91a0d9`).
2. [x] `ImuCalibration`/`ImuSequence`, compatible `ImageSequence` acquisition
       fields, and record tests; locally green and covered by the hosted
       installed-wheel smoke in run `30914739031`.
3. [x] `VisualInertialDataset` plus dataset read/write/inspect, oracle suite,
       benchmark, and docs; locally green and covered by the hosted
       installed-wheel smoke in run `30914739031`.
4. [x] `LabelTaxonomy` and dense label records plus NPZ/Zarr/TIFF carriers,
       strict NCore projection, bounded Kubric rule evidence, procedural
       regeneration recipe, generated/hash-verified Blender 4.3 result,
       benchmark, and docs are locally complete. The typed-carrier/NCore
       package smoke is hosted-wheel green in run `30914739031`; Kubric
       generation and hash verification remain explicit offline evidence.
5. [x] `PointScan`/`ScanSet` plus E57 multi-scan/structured read/write/inspect,
       oracle suite, benchmark, and docs are validated through the final
       exact-head build-only run.
6. [x] Neutral raster collection plus the qualified TIFF read/write subset,
       oracle suite, benchmark, and docs.
7. [x] Evidence-backed OpenVDB expansion exclusion, retaining and hardening the
       qualified nonempty one-grid writer.
8. [x] USD selected-time qualification through the existing API in state B;
       `SceneAnimation` and dynamic writing remain explicit exclusions.
9. [x] Per-provider hosted corrections: `3e329c9` added OpenVDB to the combined
       wheel smoke, `56d1922` isolated the sanitizer collection finding, and
       `9a20bc6` stabilized optional OpenUSD oracle collection at 5,066 nodes.
10. [x] FC7 exact-head aggregate hosted validation and final evidence at
        implementation candidate `9a20bc61` and Release run `33249900572`.

Do not combine slices merely to reduce commit count. A slice may be split when
its record and codec changes cannot be reviewed or reverted independently.

## 15. Program completion matrix

`Hosted wheels` records installed-package smoke coverage. It does not replace
the fuller local edge, conversion, or independent-oracle suites represented in
their own columns and validation records.

| Unit | Record/API | Read | Write | Inspect | Partial | Oracle per supported direction | Large benchmark | Local suite | Hosted wheels | Docs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FC1A IMU records/acquisition | [x] | n/a | refusal-only | n/a | n/a | [x] record vectors | n/a | [x] | [x] `30914739031` | [x] |
| FC1B visual-inertial dataset | [x] | [x] | [x] | [x] | [x] | [x] | [x] bounded baseline | [x] | [x] `30914739031` | [x] |
| FC2 dense labels | [x] | carriers/NCore [x] | carriers/NCore [x] | carriers [x] | n/a for one-map carriers | NPZ/Zarr/TIFF/NCore/Kubric [x] | [x] NPZ/Zarr/TIFF | [x] | [x] `30914739031` | [x] |
| FC3 E57 scans | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] `33231962034` | [x] |
| G1 Gaussian semantics | [x] | carrier mapping [x] | guarded writers [x] | n/a | existing carrier selectors [x] | [x] official lanes | [x] | [x] | [x] `33249900572` | [x] |
| FC4 TIFF collections | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] `33249900572` | [x] |
| FC5 OpenVDB exclusion | n/a | existing one-grid [x] | existing one-grid [x] | [x] | excluded | official provider loss probes [x] | n/a | [x] | [x] `33249900572` | [x] |
| FC6 USD state B | no new record [x] | selected time [x] | dynamic excluded [x] | [x] | existing `time` API [x] | OpenUSD 26.8 [x] | [x] | [x] | [x] `33249900572` | [x] |
| FC7 aggregate | n/a | n/a | n/a | n/a | n/a | local [x]; hosted [x] | [x] | [x] | [x] `33249900572` | [x] |

## 16. Final stopping rule

The follow-on program is closed when FC1-FC6 satisfy the matrix and FC7 passes.
At that point:

- the registry contains exactly 74 built-ins, including the qualified bounded
  visual-inertial directory codec;
- all new behavior is constrained by versioned 3D-CV profiles;
- every supported read/write direction has independent evidence, and every
  unsupported direction has a tested capability/refusal entry;
- current simple-format behavior remains compatible;
- normal CI uses no network data and the base runtime remains NumPy-only; and
- every broader upstream-standard feature is documented as refused or future,
  not treated as unfinished work in this program.
