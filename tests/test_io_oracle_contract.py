"""Repository-wide independent-oracle coverage for every built-in format."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import sceneio
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/io_oracles_v1.toml").read_text(encoding="utf-8")
)
GAUSSIAN_CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/gaussian_oracles_v1.toml").read_text(
        encoding="utf-8"
    )
)
LEDGER = tomllib.loads(
    (ROOT / CONTRACT["ledger_source"]).read_text(encoding="utf-8")
)[CONTRACT["ledger_table"]]


def _test_names(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.name.lower()
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def _has_named_direction(names: tuple[str, ...], markers: list[str]) -> bool:
    return any(marker in name for name in names for marker in markers)


def test_every_builtin_has_executable_independent_oracle_evidence():
    assert CONTRACT["expected_builtin_count"] == len(CANONICAL_BUILTIN_IDS) == 73
    assert tuple(entry["id"] for entry in LEDGER) == CANONICAL_BUILTIN_IDS
    assert len({entry["id"] for entry in LEDGER}) == len(LEDGER)

    codecs = sceneio.codecs()
    required_fields = set(CONTRACT["required_row_fields"])
    evidence_root = (ROOT / CONTRACT["evidence_directory"]).resolve()
    read_markers = CONTRACT["read_test_name_markers"]
    write_markers = CONTRACT["write_test_name_markers"]
    directional_evidence = CONTRACT["directional_evidence"]
    assert tuple(directional_evidence) == CANONICAL_BUILTIN_IDS

    for entry in LEDGER:
        format_id = entry["id"]
        assert set(entry) == required_fields, format_id
        assert isinstance(entry["oracle"], str) and entry["oracle"].strip(), format_id
        oracle = entry["oracle"].casefold()
        assert not any(
            oracle == invalid.casefold()
            for invalid in CONTRACT["disallowed_oracle_descriptions"]
        ), format_id
        assert entry["tests"], format_id

        sources: list[str] = []
        names: list[str] = []
        for relative_path in entry["tests"]:
            path = (ROOT / relative_path).resolve()
            assert path.is_file(), (format_id, relative_path)
            assert path.parent == evidence_root, (format_id, relative_path)
            sources.append(path.read_text(encoding="utf-8").casefold())
            names.extend(_test_names(path))

        joined_source = "\n".join(sources)
        assert any(
            marker.casefold() in joined_source
            for marker in CONTRACT["source_evidence_markers"]
        ), format_id
        assert _has_named_direction(tuple(names), read_markers), format_id
        evidence = directional_evidence[format_id]
        assert set(evidence) == {"decode", "encode"}, format_id
        assert evidence["decode"].lower() in names, format_id

        codec = codecs[format_id]
        assert codec.read is not None, format_id
        if format_id in CONTRACT["read_only_formats"]:
            assert codec.write is None, format_id
            assert entry["encode"] == "unsupported", format_id
            assert evidence["encode"] == "unsupported", format_id
        else:
            assert codec.write is not None, format_id
            assert entry["encode"] != "unsupported", format_id
            assert _has_named_direction(tuple(names), write_markers), format_id
            assert evidence["encode"].lower() in names, format_id


def test_oracle_contract_matches_runtime_direction_and_loss_metadata():
    capabilities = [sceneio.capabilities(format_id) for format_id in CANONICAL_BUILTIN_IDS]
    assert sum(item.can_read for item in capabilities) == CONTRACT["expected_readable_count"]
    assert sum(item.can_write for item in capabilities) == CONTRACT["expected_writable_count"]
    assert {
        item.format for item in capabilities if item.lossy
    } == set(CONTRACT["lossy_or_quantized_formats"])
    assert {
        item.format for item in capabilities if not item.can_write
    } == set(CONTRACT["read_only_formats"])


def test_gaussian_storage_oracles_cover_every_registered_carrier():
    gaussian = CONTRACT["gaussian_attributes"]
    ledger_by_id = {entry["id"]: entry for entry in LEDGER}
    required_suites = set(gaussian["evidence_suites"])

    for format_id in gaussian["carrier_formats"]:
        assert format_id in ledger_by_id
        suites = set(ledger_by_id[format_id]["tests"])
        if format_id in {"usd", "usdz"}:
            assert "tests/codecs/test_usd_gaussians.py" in suites
        else:
            assert suites & required_suites, format_id

    for relative_path in required_suites:
        assert (ROOT / relative_path).is_file(), relative_path

    convention_source = (
        ROOT / "tests/records/test_gaussian_cloud_conventions.py"
    ).read_text(encoding="utf-8").casefold()
    for semantic in ("scale", "opacity", "quaternion", "sh_layout"):
        assert semantic in convention_source

    assert gaussian["pending_universal_semantics"] == [
        "quaternion_raw_or_unit_state",
        "spherical_harmonic_basis_phase_and_coefficient_order",
        "color_space",
        "coordinate_frame",
    ]
    assert gaussian["qualified_semantic_operations"] == [
        "quaternion_reorder_and_explicit_normalization",
        "scale_activation",
        "opacity_activation",
        "spherical_harmonic_memory_layout",
    ]
    assert set(gaussian["pending_universal_semantics"]).isdisjoint(
        gaussian["qualified_semantic_operations"]
    )

    semantic_source = (
        ROOT / "tests/records/test_gaussian_semantic_oracles.py"
    ).read_text(encoding="utf-8")
    for executable_marker in ("Rotation.from_quat", "expit(", "logit("):
        assert executable_marker in semantic_source
    assert "for point, channel, coefficient in product" in semantic_source
    assert "convert_coordinates(cloud" in semantic_source


def test_gaussian_third_party_oracle_roles_are_pinned_and_executable():
    assert GAUSSIAN_CONTRACT["schema_version"] == 1
    contract_test = ROOT / GAUSSIAN_CONTRACT["contract_test"]
    assert contract_test.is_file()
    source = contract_test.read_text(encoding="utf-8")
    oracles = {
        oracle["id"]: oracle for oracle in GAUSSIAN_CONTRACT["oracles"]
    }
    requirements = GAUSSIAN_CONTRACT["requirements"]

    assert len(oracles) == len(GAUSSIAN_CONTRACT["oracles"])
    assert set(requirements["permitted_licenses"]) == {
        oracle["license"] for oracle in oracles.values()
    }
    assert all(len(oracle["revision"]) == 40 for oracle in oracles.values())

    executable = oracles[requirements["executable_full_family_oracle"]]
    assert executable["execution"] == "cross_platform_ci"
    assert set(executable["read_formats"]) == set(
        requirements["legacy_wire_formats"]
    )
    assert executable["version"] in source
    assert executable["revision"][:7] in source

    for format_id in requirements["second_implementation_formats"]:
        assert any(
            format_id in oracle["read_formats"]
            and oracle["id"] != executable["id"]
            for oracle in oracles.values()
        ), format_id

    for oracle_id in requirements[
        "reference_only_projects_must_not_be_claimed_as_executable"
    ]:
        assert oracles[oracle_id]["execution"] == "reference_only"

    official_ids = tuple(requirements["official_oracle_ids"])
    assert official_ids == ("niantic_spz", "openusd")
    assert tuple(requirements["official_oracle_test_suites"]) == tuple(
        oracles[oracle_id]["test_suite"] for oracle_id in official_ids
    )

    niantic = oracles["niantic_spz"]
    assert niantic["version"] == "3.0.0"
    assert niantic["execution"] == "focused_hosted_ci"
    assert tuple(niantic["executable_versions"]) == ("v2", "v3", "v4")
    assert tuple(niantic["read_versions"]) == ("v2", "v3", "v4")
    assert tuple(niantic["write_versions"]) == ("v3", "v4")
    assert tuple(niantic["excluded_versions"]) == ("v1",)
    niantic_suite = ROOT / niantic["test_suite"]
    assert niantic_suite.is_file()
    niantic_source = niantic_suite.read_text(encoding="utf-8")
    assert niantic["revision"] in niantic_source
    assert "_EXECUTABLE_VERSIONS" in niantic_source
    assert "v1" in niantic_source and "obsolete" in niantic_source

    openusd = oracles["openusd"]
    assert openusd["version"] == "26.08"
    assert openusd["license"] == "TOST-1.0"
    assert openusd["execution"] == "focused_hosted_ci"
    assert tuple(openusd["profiles"]) == ("USDA", "USDZ")
    assert "source provenance" in openusd["source_revision_role"]
    openusd_suite = ROOT / openusd["test_suite"]
    assert openusd_suite.is_file()
    openusd_source = openusd_suite.read_text(encoding="utf-8")
    assert "usd-core==26.8" in openusd_source
    assert "pxr" in openusd_source
    openusd_notice = (ROOT / "LICENSES/openusd.txt").read_text(
        encoding="utf-8"
    )
    assert f"Release source revision: {openusd['revision']}" in openusd_notice
    assert f"Executed Python artifact: {openusd['distribution']}" in openusd_notice
