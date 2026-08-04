"""Machine-checked FC2 record and generic-carrier contract."""

from __future__ import annotations

import dataclasses
import tomllib
from datetime import date
from pathlib import Path

import sceneio
import sceneio.data
import sceneio.io

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/dense_label_maps_v1.toml").read_text(encoding="utf-8")
)
FIXTURE_CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/public_fixture_sources_v1.toml").read_text(
        encoding="utf-8"
    )
)


def test_contract_identity_public_surface_and_live_fields() -> None:
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["status"] == "adapters_qualified_oracle_generated"
    assert date.fromisoformat(CONTRACT["contract_date"]).isoformat() == CONTRACT[
        "contract_date"
    ]
    assert CONTRACT["schema"] == sceneio.LABEL_MAP_SCHEMA
    assert CONTRACT["public_namespace"] == "sceneio.data"
    expected_fields = {
        "LabelTaxonomy": CONTRACT["label_taxonomy"]["fields"],
        "SemanticMap": CONTRACT["semantic_map"]["fields"],
        "InstanceMap": CONTRACT["instance_map"]["fields"],
        "PanopticMap": CONTRACT["panoptic_map"]["fields"],
    }
    assert sorted(expected_fields) == CONTRACT["public_symbols"]
    for name, fields in expected_fields.items():
        record = getattr(sceneio.data, name)
        assert dataclasses.is_dataclass(record)
        assert [field.name for field in dataclasses.fields(record)] == fields
        assert sceneio.representation_contract(record).representation == (
            f"sceneio.data.{name}"
        )
    for name in CONTRACT["typed_io"]:
        assert getattr(sceneio, name) is getattr(sceneio.io, name)
        assert name in sceneio.__all__
        assert name in sceneio.io.__all__


def test_carrier_schema_names_are_exact_and_nonoverlapping() -> None:
    arrays = CONTRACT["carrier_arrays"]
    groups = (
        arrays["required_marker"],
        arrays["semantic"],
        arrays["instance"],
        arrays["validity"],
        arrays["taxonomy_required"],
        arrays["taxonomy_optional"],
        arrays["instance_table"],
    )
    flattened = [name for group in groups for name in group]
    assert len(flattened) == len(set(flattened))
    assert arrays["required_marker"] == [CONTRACT["marker_array"]]
    assert arrays["unknown_array_policy"] == "reject"
    assert CONTRACT["carrier_formats"] == ["npz", "zarr", "tiff"]
    assert CONTRACT["projection_formats"] == ["ncore_v4"]
    assert CONTRACT["pending_adapters"] == []


def test_oracle_revision_matches_public_fixture_catalog() -> None:
    [source] = [
        item
        for item in FIXTURE_CONTRACT["sources"]
        if item["id"] == "kubric_procedural_generator"
    ]
    oracle = CONTRACT["kubric_oracle"]
    assert source["revision"] == oracle["revision"]
    assert source["license"] == oracle["license"] == "Apache-2.0"
    assert source["status"] == "generator"
    for evidence in oracle["evidence"]:
        assert (ROOT / evidence).is_file()


def test_generic_carrier_claims_match_dependency_boundaries() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == ["numpy>=1.26"]
    assert "zarr>=3.1,<4" in project["project"]["optional-dependencies"]["zarr"]
    assert CONTRACT["npz"]["encodings"] == ["stored", "deflate"]
    assert CONTRACT["zarr"]["versions"] == [2, 3]
    assert CONTRACT["tiff"]["oracle"] == "tifffile"
    assert CONTRACT["ncore_v4"]["qualifiers"] == [
        "semantic",
        "instance",
        "panoptic",
    ]
    assert "TensorDict" in CONTRACT["raw_compatibility"]


def test_focused_benchmark_contract_is_present_and_qualifying() -> None:
    benchmark = CONTRACT["benchmark"]
    assert (ROOT / benchmark["entrypoint"]).is_file()
    assert benchmark["default_side"] ** 2 * 4 == 64 * 1024 * 1024
    assert benchmark["logical_payload_mib"] == 64
    assert benchmark["operations"] == [
        "write",
        "read",
        "inspect",
        "fresh_process_read_rss",
        "fresh_process_inspect_rss",
    ]
    assert benchmark["carriers"] == ["npz", "zarr", "tiff"]
    assert benchmark["oracles"] == ["numpy", "zarr", "tifffile"]
    assert "not a collection" in benchmark["selection"]
