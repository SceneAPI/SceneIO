"""Machine checks for the licensed public-fixture corpus contract."""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path

from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "tests/contracts/public_fixture_sources_v1.toml"
ORACLE_PATH = ROOT / "tests/contracts/oracle_sources_v1.toml"
CATALOG = tomllib.loads(CATALOG_PATH.read_text(encoding="utf-8"))

_SOURCE_FIELDS = {
    "id",
    "project",
    "revision",
    "revision_type",
    "artifact",
    "url",
    "license",
    "license_url",
    "attribution",
    "status",
    "redistribution",
    "default_ci",
    "expected_size_bytes",
    "expected_sha256",
    "observed_result",
    "notes",
}
_ROUTE_FIELDS = {
    "id",
    "mode",
    "source_ids",
    "oracle_source_ids",
    "formats",
    "evidence",
    "derivation",
    "qualification",
}
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_CONTENT_REVISION = re.compile(r"^content-sha256:[0-9a-f]{64}$")
_SNAPSHOT_REVISION = re.compile(r"^snapshot:\d{4}-\d{2}-\d{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def test_catalog_policy_is_versioned_and_excludes_restricted_data():
    assert CATALOG["schema_version"] == 1
    assert CATALOG["catalog_date"] == "2026-08-03"
    assert date.fromisoformat(CATALOG["catalog_date"]).isoformat() == CATALOG[
        "catalog_date"
    ]
    assert CATALOG["required_builtin_count"] == len(CANONICAL_BUILTIN_IDS) == 74
    assert CATALOG["direct_format_count"] == 13
    assert CATALOG["derived_format_count"] == 61
    assert CATALOG["direct_format_count"] + CATALOG["derived_format_count"] == 74
    assert all("-NC" not in license for license in CATALOG["allowed_licenses"])


def test_every_public_source_has_explicit_provenance_license_and_delivery_status():
    rows = CATALOG["sources"]
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))

    for row in rows:
        assert set(row) == _SOURCE_FIELDS, row["id"]
        assert _ID.fullmatch(row["id"]), row["id"]
        assert row["project"].strip()
        assert row["revision_type"] in {
            "git_commit",
            "content_sha256",
            "catalog_snapshot",
        }
        revision_patterns = {
            "git_commit": _GIT_REVISION,
            "content_sha256": _CONTENT_REVISION,
            "catalog_snapshot": _SNAPSHOT_REVISION,
        }
        assert revision_patterns[row["revision_type"]].fullmatch(row["revision"]), (
            row["id"],
            row["revision"],
        )
        assert row["url"].startswith("https://"), row["id"]
        assert row["license_url"].startswith("https://"), row["id"]
        assert row["license"] in CATALOG["allowed_licenses"], row["id"]
        assert "-NC" not in row["license"]
        assert row["status"] in CATALOG["allowed_source_statuses"]
        assert isinstance(row["default_ci"], bool) and not row["default_ci"]
        assert row["artifact"].strip()
        assert row["attribution"].strip()
        assert row["redistribution"].strip()
        assert row["observed_result"].strip()
        assert row["notes"].strip()

        if row["status"] in {
            "sceneio_read",
            "bundle_verified",
            "profile_refusal",
        }:
            assert row["expected_size_bytes"] > 0, row["id"]
            assert _SHA256.fullmatch(row["expected_sha256"]), row["id"]
        else:
            assert row["expected_size_bytes"] >= 0, row["id"]
            assert not row["expected_sha256"] or _SHA256.fullmatch(
                row["expected_sha256"]
            )


def test_primary_routes_cover_every_builtin_exactly_once_with_real_evidence():
    source_rows = {row["id"]: row for row in CATALOG["sources"]}
    oracle_catalog = tomllib.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    oracle_ids = {row["id"] for row in oracle_catalog["sources"]}
    routes = CATALOG["routes"]
    route_ids = [route["id"] for route in routes]
    assert len(route_ids) == len(set(route_ids))

    observed_formats: list[str] = []
    direct_formats: list[str] = []
    derived_formats: list[str] = []
    for route in routes:
        assert set(route) == _ROUTE_FIELDS, route["id"]
        assert _ID.fullmatch(route["id"]), route["id"]
        assert route["mode"] in CATALOG["allowed_route_modes"]
        assert route["source_ids"]
        assert set(route["source_ids"]) <= set(source_rows), route["id"]
        assert route["oracle_source_ids"]
        assert set(route["oracle_source_ids"]) <= oracle_ids, route["id"]
        assert route["formats"]
        assert route["derivation"].strip()
        assert route["qualification"].strip()

        for relative_path in route["evidence"]:
            path = (ROOT / relative_path).resolve()
            assert path.is_file(), (route["id"], relative_path)
            assert path.is_relative_to(ROOT / "tests"), (route["id"], relative_path)

        if route["mode"] == "direct":
            direct_formats.extend(route["formats"])
            assert route["derivation"] == "none"
            assert all(
                source_rows[source_id]["status"]
                in {"sceneio_read", "bundle_verified"}
                for source_id in route["source_ids"]
            ), route["id"]
        else:
            derived_formats.extend(route["formats"])
            assert route["derivation"] != "none"
        observed_formats.extend(route["formats"])

    assert len(observed_formats) == len(set(observed_formats))
    assert set(observed_formats) == set(CANONICAL_BUILTIN_IDS)
    assert len(direct_formats) == CATALOG["direct_format_count"]
    assert len(derived_formats) == CATALOG["derived_format_count"]


def test_profile_refusals_and_hosted_sources_are_not_counted_as_direct_fixtures():
    sources = {row["id"]: row for row in CATALOG["sources"]}
    direct_source_ids = {
        source_id
        for route in CATALOG["routes"]
        if route["mode"] == "direct"
        for source_id in route["source_ids"]
    }
    assert not {
        source_id
        for source_id, row in sources.items()
        if row["status"] in {"profile_refusal", "hosted_only", "generator"}
    } & direct_source_ids
    assert sources["monado_mio09"]["expected_sha256"] == (
        "14072018b9e424b06abfd1173169b24e53ad47632d3051e3164b27d322a0b898"
    )
    assert sources["fire_actioncam_scene001_meta"]["expected_sha256"] == (
        "7fe21660b705408e52ba30188a2d5f003ee9213ed70b95848432c306135f0930"
    )
