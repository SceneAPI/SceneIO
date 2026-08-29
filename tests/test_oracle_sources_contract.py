"""Machine checks for the pinned external-oracle source catalog."""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path

from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "tests/contracts/oracle_sources_v1.toml"
IO_ORACLE_PATH = ROOT / "tests/contracts/io_oracles_v1.toml"
CATALOG = tomllib.loads(CATALOG_PATH.read_text(encoding="utf-8"))

_SOURCE_FIELDS = {
    "id",
    "project",
    "repository",
    "revision",
    "version",
    "stars",
    "stars_snapshot",
    "license",
    "license_class",
    "distribution_role",
    "authority",
    "lineage",
    "formats",
    "semantic_roles",
    "execution",
    "execution_markers",
    "evidence_tests",
    "qualification",
    "notice",
}
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_URL = re.compile(r"^https://github\.com/[^/]+/[^/]+$")


def test_catalog_schema_is_pinned_and_uses_the_approved_policy():
    assert CATALOG["schema_version"] == 1
    assert CATALOG["catalog_date"] == "2026-08-03"
    assert date.fromisoformat(CATALOG["catalog_date"]).isoformat() == CATALOG[
        "catalog_date"
    ]
    assert "TOST-1.0" in CATALOG["permitted_license_expressions"]
    assert "MPL-2.0" in CATALOG["permitted_license_expressions"]
    assert "BSL-1.0" in CATALOG["permitted_license_expressions"]
    assert "GPL-3.0" in CATALOG["reference_only_license_expressions"]


def test_every_source_row_has_a_pinned_revision_license_role_and_evidence():
    rows = CATALOG["sources"]
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(CATALOG["required_source_ids"])

    for row in rows:
        assert set(row) == _SOURCE_FIELDS, row["id"]
        assert row["id"] and row["project"]
        assert _URL.fullmatch(row["repository"]), row["id"]
        assert _REVISION.fullmatch(row["revision"]), row["id"]
        assert isinstance(row["version"], str) and row["version"].strip()
        assert isinstance(row["stars"], int) and row["stars"] >= 0
        assert row["stars_snapshot"] == CATALOG["catalog_date"]
        assert row["license"] in (
            CATALOG["permitted_license_expressions"]
            + CATALOG["reference_only_license_expressions"]
        )
        assert row["license_class"] in CATALOG["allowed_license_classes"]
        assert row["distribution_role"] in CATALOG["allowed_roles"]
        assert row["authority"] in CATALOG["allowed_authorities"]
        assert row["qualification"] in CATALOG["allowed_qualifications"]
        assert row["lineage"].strip()
        assert row["formats"] and all(isinstance(item, str) for item in row["formats"])
        assert row["semantic_roles"]
        assert row["execution"].strip()
        assert row["execution_markers"] and all(
            isinstance(marker, str) and marker.strip()
            for marker in row["execution_markers"]
        )
        assert row["evidence_tests"]

        for relative_path in row["evidence_tests"]:
            path = (ROOT / relative_path).resolve()
            assert path.is_file(), (row["id"], relative_path)
            assert path.is_relative_to(ROOT / "tests"), (row["id"], relative_path)

        if row["notice"]:
            notice = (ROOT / row["notice"]).resolve()
            assert notice.is_file(), (row["id"], row["notice"])
            assert notice.is_relative_to(ROOT / "LICENSES"), (row["id"], row["notice"])

        if row["license"] in CATALOG["reference_only_license_expressions"]:
            assert row["distribution_role"] == "reference_only", row["id"]
            assert row["qualification"] == "reference", row["id"]
            assert row["license_class"] == "strong_copyleft_reference", row["id"]

        if row["qualification"] == "executed":
            assert row["distribution_role"] in {
                "runtime_required",
                "runtime_optional",
                "test_executable",
            }
            source = "\n".join(
                (ROOT / relative_path).read_text(encoding="utf-8").casefold()
                for relative_path in row["evidence_tests"]
            )
            assert any(
                marker.casefold() in source for marker in row["execution_markers"]
            ), row["id"]


def test_lineage_groups_prevent_correlated_implementations_being_counted_twice():
    rows = CATALOG["sources"]
    by_lineage: dict[str, set[str]] = {}
    for row in rows:
        by_lineage.setdefault(row["lineage"], set()).add(row["id"])
    assert by_lineage["colmap"] == {"colmap", "pycolmap"}
    assert len(by_lineage) < len(rows)
    assert all(lineage and ids for lineage, ids in by_lineage.items())


def test_directional_io_evidence_still_covers_every_builtin_format():
    io_contract = tomllib.loads(IO_ORACLE_PATH.read_text(encoding="utf-8"))
    directional = io_contract["directional_evidence"]
    assert tuple(directional) == CANONICAL_BUILTIN_IDS
    assert set(directional) == set(CANONICAL_BUILTIN_IDS)
    for format_id in CANONICAL_BUILTIN_IDS:
        evidence = directional[format_id]
        assert set(evidence) == {"decode", "encode"}, format_id
        assert all(isinstance(value, str) and value.strip() for value in evidence.values())


def test_weak_and_permissive_sources_can_be_selected_without_runtime_imports():
    rows = {row["id"]: row for row in CATALOG["sources"]}
    for source_id in ("openmvg", "alicevision", "openusd", "libe57format"):
        row = rows[source_id]
        assert row["license_class"] in {"permissive", "weak_copyleft"}
        assert row["distribution_role"] != "runtime_optional"

    runtime_rows = [
        row
        for row in CATALOG["sources"]
        if row["distribution_role"] in {"runtime_required", "runtime_optional"}
    ]
    assert {row["id"] for row in runtime_rows} == {"numpy"}
