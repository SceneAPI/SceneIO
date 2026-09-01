"""FC0 decisions for the finite remaining 3D-CV profile program."""

from __future__ import annotations

import importlib
import inspect
import re
import tomllib
from datetime import date
from pathlib import Path

import numpy as np
import pytest

import sceneio
import sceneio.io
from sceneio import _core
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "tests/contracts/remaining_3dcv_fc0_v1.toml"
CONTRACT = tomllib.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
FC1_CONTRACT_PATH = ROOT / "tests/contracts/visual_inertial_records_v1.toml"
FC1_CONTRACT = tomllib.loads(FC1_CONTRACT_PATH.read_text(encoding="utf-8"))

_DESIGN_IDS = {
    "visual_inertial",
    "image_acquisition_timing",
    "dense_label_maps",
    "e57_scan_sets",
    "tiff_raster_collections",
    "openvdb_multi_grid",
    "usd_authored_time_samples",
}
_PROVIDER_IDS = {"pye57", "tifffile", "tinyvdb", "tinyusdz"}
_OUTCOMES = {
    "approved_for_internal_prototype",
    "provider_limited",
    "qualified",
    "qualified_exclusion",
}
_PROVIDER_OUTCOMES = {
    "broader_container_operations_proven",
    "authoring_surface_limited",
    "authored_sample_values_unavailable",
    "qualified_exclusion",
}


def _assert_evidence(reference: str) -> None:
    relative, separator, node = reference.partition("::")
    path = (ROOT / relative).resolve()
    assert path.is_file(), reference
    assert path.is_relative_to(ROOT), reference
    if separator:
        function_name = node.partition("[")[0]
        assert re.search(
            rf"^def {re.escape(function_name)}\(",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        ), reference


def _resolve_type(type_name: str) -> type:
    module_name, separator, attribute = type_name.rpartition(".")
    assert separator, type_name
    value = getattr(importlib.import_module(module_name), attribute)
    assert isinstance(value, type), type_name
    return value


def test_fc0_decisions_are_complete_provisional_and_nonpublic():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["status"] == "locally_qualified"
    assert date.fromisoformat(CONTRACT["contract_date"]).isoformat() == (
        CONTRACT["contract_date"]
    )
    assert CONTRACT["builtin_count"] == 74
    assert len(CANONICAL_BUILTIN_IDS) >= CONTRACT["builtin_count"]
    assert CONTRACT["provisional_format_ids"] == []
    assert CONTRACT["implemented_format_ids"] == ["euroc_dataset"]
    assert "euroc_dataset" in CANONICAL_BUILTIN_IDS
    [implemented_format] = CONTRACT["implemented_formats"]
    assert implemented_format["id"] == "euroc_dataset"
    assert implemented_format["family_module"].endswith(".families.datasets")
    assert implemented_format["container_kind"] == "multi_file"
    assert implemented_format["payload_kind"] == "visual_inertial_dataset"
    assert implemented_format["directory_probe_required"] is True
    assert set(implemented_format["required_globs"]) == {
        "mav0/cam*/data.csv",
        "mav0/cam*/sensor.yaml",
        "mav0/imu*/data.csv",
        "mav0/imu*/sensor.yaml",
    }
    assert implemented_format["detection_rule"].strip()
    assert implemented_format["registration_gate"].strip()

    decisions = CONTRACT["design_decisions"]
    assert {row["id"] for row in decisions} == _DESIGN_IDS
    assert len(decisions) == len(_DESIGN_IDS)
    symbols = sorted(
        symbol for row in decisions for symbol in row["public_symbols"]
    )
    implemented = set(CONTRACT["implemented_public_symbols"])
    implemented_data = set(CONTRACT["implemented_data_symbols"])
    implemented_shared = set(CONTRACT["implemented_shared_symbols"])
    assert implemented == set(FC1_CONTRACT["public_symbols"]) | {
        "PointScan",
        "ScanSet",
    }
    assert implemented.isdisjoint(implemented_data)
    assert implemented.isdisjoint(implemented_shared)
    assert implemented_data.isdisjoint(implemented_shared)
    assert sorted(
        set(symbols) - implemented - implemented_data - implemented_shared
    ) == CONTRACT["provisional_public_symbols"]
    assert len(symbols) == len(set(symbols))

    public_modules = (sceneio, sceneio.io)
    implemented_root = implemented | implemented_data | implemented_shared
    assert implemented <= set(symbols)
    for symbol in symbols:
        if symbol in implemented_root:
            assert hasattr(sceneio, symbol)
            assert not hasattr(sceneio.io, symbol)
        else:
            assert all(not hasattr(module, symbol) for module in public_modules)
    for row in decisions:
        assert row["outcome"] in _OUTCOMES
        assert row["required_contracts"]
        assert all(statement.endswith(".") for statement in row["required_contracts"])
        for symbol in row["existing_symbols"]:
            assert any(hasattr(module, symbol) for module in public_modules), (
                row["id"],
                symbol,
            )
        for reference in row["evidence"]:
            _assert_evidence(reference)


def test_fc0_freezes_signatures_errors_and_canonical_construction():
    assert str(inspect.signature(sceneio.read_partial)) == CONTRACT[
        "read_partial_signature"
    ]
    assert str(inspect.signature(sceneio.read_scene)) == CONTRACT[
        "read_scene_signature"
    ]
    assert _resolve_type(CONTRACT["public_io_error_type"]) is sceneio.FormatError
    assert {_resolve_type(name) for name in CONTRACT["record_error_types"]} == {
        sceneio.ContractViolation,
        ValueError,
    }
    with pytest.raises(
        ValueError,
        match="read_partial requires exactly one selector family",
    ):
        sceneio.read_partial("unused")
    with pytest.raises(
        ValueError,
        match="read_partial requires exactly one selector family",
    ):
        sceneio.read_partial("unused", window=(0, 1, 0, 1), points=(0, 1))
    with pytest.raises(sceneio.FormatError, match="unknown format id"):
        sceneio.read("unused", format="__fc0_unknown__")
    with pytest.raises(ValueError, match=r"positions must be \(N,3\) float32"):
        _core.point_cloud(np.zeros((1, 4), np.float32))

    empty_timing = np.empty(0, np.int64)
    sequence = _core.image_sequence_paths(
        ["frame.png"],
        ["frame.png"],
        empty_timing,
        empty_timing,
        2,
        3,
        3,
        "uint8",
        "srgb",
        "none",
    )
    cloud = _core.point_cloud(np.zeros((1, 3), np.float32))
    tensors = _core.tensor_dict({"x": np.zeros(1, np.float32)})
    graph = _core.scene_graph([])

    assert isinstance(sequence, sceneio.ImageSequence)
    assert sequence.frame_paths == ["frame.png"]
    assert not sequence.has_timing
    assert not sequence.has_acquisition_timing
    assert sequence.exposure_durations_ns.shape == (0,)
    assert sequence.readout_step_durations_ns.shape == (0,)
    assert sequence.timestamp_reference == "unknown"
    assert isinstance(cloud, sceneio.PointCloud)
    assert cloud.num_points == 1
    assert isinstance(tensors, sceneio.TensorDict)
    assert tensors.keys() == ["x"]
    assert isinstance(graph, sceneio.SceneGraph)
    assert graph.num_nodes == 0
    assert graph.selected_time is None


def test_fc0_provider_ledger_matches_dependencies_capabilities_and_evidence():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]
    test_dependencies = extras["test"]
    providers = CONTRACT["providers"]
    assert {row["id"] for row in providers} == _PROVIDER_IDS
    assert len(providers) == len(_PROVIDER_IDS)

    covered_formats: set[str] = set()
    for row in providers:
        assert row["outcome"] in _PROVIDER_OUTCOMES
        assert row["requirement"] in extras[row["extra"]]
        assert row["requirement"] in test_dependencies
        assert re.fullmatch(r"\d+(?:\.\d+)+", row["observed_version"])
        assert row["provider_proven_operations"]
        for format_id in row["formats"]:
            capabilities = sceneio.capabilities(format_id)
            assert row["id"] in capabilities.requires_features
            assert set(row["sceneio_current_refusals"]) <= set(
                capabilities.unsupported_features
            )
            covered_formats.add(format_id)
        for reference in row["evidence"]:
            _assert_evidence(reference)

    projections = CONTRACT["canonical_records"]
    projected_formats = {
        format_id for row in projections for format_id in row["formats"]
    }
    assert covered_formats == projected_formats == {
        "e57",
        "tiff",
        "openvdb",
        "usd",
        "usdz",
    }
    for row in projections:
        assert row["return_types"]
        assert row["boundary"].endswith(".")
        for type_name in row["return_types"]:
            _resolve_type(type_name)
        for reference in row["evidence"]:
            _assert_evidence(reference)
