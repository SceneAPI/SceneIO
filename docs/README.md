# SceneIO documentation

SceneIO uses repository-native Markdown rather than Sphinx or MkDocs. The
documents below have different authority levels; a dated implementation
checkpoint is evidence for that revision, not the current capability source.

## Current user and API contracts

- [`../README.md`](../README.md) — installation, package scope, and public API
  examples.
- [`format_coverage.md`](format_coverage.md) — canonical live format,
  capability, optional-provider, and validation inventory. Its registry tables
  are generated from the runtime manifest.
- [`coordinate_conventions.md`](coordinate_conventions.md) — coordinate,
  pixel-center, transform-direction, and explicit-conversion rules.
- [`representation_normalization.md`](representation_normalization.md) —
  versioned normalization, units, scale, and conversion policies for public
  data representations.
- [`public_type_contracts.md`](public_type_contracts.md) — generated exhaustive
  public class identity, kind, evidence, and built-in codec payload
  relationship catalog.
- [`colmap_adapters.md`](colmap_adapters.md) — public COLMAP workflow adapter
  surface outside the format registry.
- [`core_architecture.md`](core_architecture.md) — current Python/native
  layering, ownership boundaries, and codec-extension procedure.

For a current fact, these documents and the runtime contracts they name take
precedence over dated plans and benchmark checkpoints.

## Current engineering policy and release record

- [`plans/representation_consolidation_2026-08-30.md`](plans/representation_consolidation_2026-08-30.md)
  — completed 0.4 contract reset that consolidated cameras, features,
  correspondences, depth, posed views, point tracks, and scenes without a
  legacy adapter layer.
- [`coverage_roadmap.md`](coverage_roadmap.md) — deliberate exclusions,
  aspirational gates, and optional future sequencing. It does not override the
  shipped capability table.
- [`public_fixture_corpus.md`](public_fixture_corpus.md) — licensed fixture and
  deterministic oracle-derived coverage.
- [`colmap_ecosystem_coverage.md`](colmap_ecosystem_coverage.md) — the bounded
  COLMAP interoperability matrix and closure boundary.
- [`large_file_io_benchmark_spec.md`](large_file_io_benchmark_spec.md) — the
  completed large-file measurement protocol and retained evidence rules.

## Release information

- [`../CHANGELOG.md`](../CHANGELOG.md) — concise release history.
- [`releases/v0.4.0.md`](releases/v0.4.0.md) — SceneIO 0.4.0 canonical
  representation contract and unchanged I/O inventory.
- [`releases/v0.3.0.md`](releases/v0.3.0.md) — SceneIO 0.3.0 scope,
  compatibility boundaries, and publication evidence.

## Completed implementation records

These pages preserve decisions, checkpoints, commands, and measurements from
the work they closed. Counts and phrases such as “current worktree” inside a
dated checkpoint describe that checkpoint unless its preamble explicitly says
otherwise.

- [`format_gap_implementation_plan.md`](format_gap_implementation_plan.md) —
  completed format-expansion program.
- [`repository_organization_plan.md`](repository_organization_plan.md) and
  [`next_stage_implementation_checklist.md`](next_stage_implementation_checklist.md)
  — completed architecture, source-closure, and package-gate program.
- [`remaining_3dcv_profile_checklist.md`](remaining_3dcv_profile_checklist.md)
  — completed FC0-FC7 finite-profile acceptance record.
- [`usd_3d_cv_implementation_plan.md`](usd_3d_cv_implementation_plan.md) —
  completed bounded USD 3D-CV profile plan, including its explicit exclusions.
- [`io_implementation_plan.md`](io_implementation_plan.md) and
  [`io_optimization_plan.md`](io_optimization_plan.md) — original compiled-I/O
  design and completed transport-optimization record.
- [`plans/completed/README.md`](plans/completed/README.md) — immutable archived
  execution evidence.
- [`plans/completed/public_type_contract_standardization_2026-08-29.md`](plans/completed/public_type_contract_standardization_2026-08-29.md)
  — completed compatibility-safe standardization of every public class
  identity and built-in codec payload kind.

Provider and benchmark evidence pages remain useful for reproducing their
named environment and date:

- [`oracle_validation_plan.md`](oracle_validation_plan.md)
- [`e57_multiscan_benchmark.md`](e57_multiscan_benchmark.md)
- [`tiff_collection_benchmark.md`](tiff_collection_benchmark.md)
- [`openvdb_provider_qualification.md`](openvdb_provider_qualification.md)
- [`usd_provider_qualification.md`](usd_provider_qualification.md)
- [`usd_animation_benchmark.md`](usd_animation_benchmark.md)

[`formats_survey.md`](formats_survey.md) is a research and licensing survey,
not the shipped-support inventory. Use `format_coverage.md` for support claims.

## Documentation checks

Run the generated-contract and documentation tests after changing a registry,
public representation, release surface, or Markdown link:

```powershell
uv run python tools/documentation_contract.py --check
uv run python -m pytest -q tests/test_documentation_consistency.py
```

Use `tools/documentation_contract.py --write` only after an intentional change
to a machine-owned generated section. Historical archive payloads are
content-hashed and must not be rewritten to match later runtime counts.
