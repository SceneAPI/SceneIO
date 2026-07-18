"""Tests for the sceneapi_io.formats DataType vocabulary."""

from __future__ import annotations

import json

import sceneapi_io
from sceneapi_io.formats import (
    CORE_DATA_TYPES,
    CORE_DATA_TYPES_BY_ID,
    CORE_FORMATS,
    DATA_TYPE_KINDS,
    is_data_type,
)
from sceneapi_io.formats import datatypes as dt

# The exact DataType ids of the core's vocabulary
# (sceneapi/server/core/datatypes.py::CORE_DATA_TYPES). Wire identity is
# untouched: this table must never drift from the core (which re-homes
# its module onto this one as pure re-exports).
EXPECTED_IDS_IN_ORDER = [
    "image_sequence",
    "camera",
    "camera_collection",
    "feature_set",
    "pair_set",
    "match_graph",
    "sparse_model",
    "projection",
]


def test_core_datatype_ids_mirror_core_vocabulary_in_order() -> None:
    assert [t.type_id for t in CORE_DATA_TYPES] == EXPECTED_IDS_IN_ORDER


def test_type_ids_are_unique_and_well_kinded() -> None:
    ids = [t.type_id for t in CORE_DATA_TYPES]
    assert len(ids) == len(set(ids)), "duplicate type_id"
    for t in CORE_DATA_TYPES:
        assert t.kind in DATA_TYPE_KINDS, (t.type_id, t.kind)
        assert t.title
        assert t.description
    assert CORE_DATA_TYPES_BY_ID.keys() == set(ids)


def test_kind_vocabulary() -> None:
    assert frozenset({"scene_input", "artifact"}) == DATA_TYPE_KINDS
    by_kind: dict[str, set[str]] = {}
    for t in CORE_DATA_TYPES:
        by_kind.setdefault(t.kind, set()).add(t.type_id)
    assert {"image_sequence", "camera", "camera_collection"} <= by_kind["scene_input"]
    assert {
        "feature_set",
        "pair_set",
        "match_graph",
        "sparse_model",
        "projection",
    } <= by_kind["artifact"]


def test_is_data_type() -> None:
    assert is_data_type("sparse_model")
    assert not is_data_type("dense_model")


def test_every_format_kind_is_an_artifact_datatype() -> None:
    # FormatSpec.kind names ids from this vocabulary, and a format only
    # serializes artifact-kind DataTypes (scene inputs are ingested, not
    # serialized) — the SceneIO twin of the core's I/O-completeness gate.
    for spec in CORE_FORMATS.values():
        assert is_data_type(spec.kind), (spec.id, spec.kind)
        assert CORE_DATA_TYPES_BY_ID[spec.kind].kind == "artifact", (spec.id, spec.kind)


def test_contract_dict_is_json_serializable_and_self_describing() -> None:
    payload = dt.contract_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["contract"] == dt.CONTRACT_NAME == "datatypes"
    assert payload["contract_schema_version"] == dt.CONTRACT_SCHEMA_VERSION == 1
    assert payload["kinds"] == sorted(DATA_TYPE_KINDS)
    assert [t["type_id"] for t in payload["types"]] == EXPECTED_IDS_IN_ORDER


def test_exported_via_formats_namespace_and_lazy_top_level() -> None:
    formats = sceneapi_io.formats  # lazy top-level namespace access
    assert formats.CORE_DATA_TYPES is CORE_DATA_TYPES
    assert formats.DATA_TYPE_KINDS is DATA_TYPE_KINDS
    assert formats.DataType is dt.DataType
