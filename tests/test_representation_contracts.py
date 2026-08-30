from __future__ import annotations

from pathlib import Path

import pytest

import sceneio.colmap
import sceneio.colmap_mvs
from sceneio.contracts import PUBLIC_TYPE_CONTRACTS
from sceneio.representations import (
    REPRESENTATION_CONTRACT_SCHEMA_VERSION,
    REPRESENTATION_CONTRACTS,
    REPRESENTATION_PROFILES,
    REPRESENTATION_UNIT_VOCABULARY,
    representation_contract,
)

ROOT = Path(__file__).resolve().parents[1]

def test_contract_catalog_exactly_covers_public_representation_classes():
    assert REPRESENTATION_CONTRACT_SCHEMA_VERSION == 1
    assert set(REPRESENTATION_CONTRACTS) == {
        path
        for path, contract in PUBLIC_TYPE_CONTRACTS.items()
        if contract.kind == "representation"
    }
    assert len(REPRESENTATION_CONTRACTS) == 90
    assert not any(
        path.startswith(("sceneio.data.", "sceneio.io."))
        for path in REPRESENTATION_CONTRACTS
    )


def test_every_contract_uses_a_registered_profile_and_live_evidence():
    documentation = (ROOT / "docs/representation_normalization.md").read_text(
        encoding="utf-8"
    )
    for name, contract in REPRESENTATION_CONTRACTS.items():
        assert contract.representation == name
        assert REPRESENTATION_PROFILES[contract.profile.id] is contract.profile
        assert f"`{name}`" in documentation
        assert f"`{contract.profile.id}`" in documentation
        assert contract.profile.rules
        assert contract.profile.refusal
        for relative_path in contract.evidence:
            assert not Path(relative_path).is_absolute()
            assert (ROOT / relative_path).is_file(), (name, relative_path)
    used_units = {
        unit
        for profile in REPRESENTATION_PROFILES.values()
        for unit in profile.canonical_units
    }
    assert used_units == REPRESENTATION_UNIT_VOCABULARY


def test_lookup_accepts_root_type_and_unambiguous_name():
    assert representation_contract("Image").representation == "sceneio.Image"
    assert representation_contract(sceneio.Image).representation == "sceneio.Image"
    assert representation_contract(sceneio.Mask).representation == (
        "sceneio.Mask"
    )
    assert representation_contract(sceneio.RasterCollection).profile.id == (
        "raster_collection"
    )
    assert representation_contract(sceneio.colmap_mvs.ProjectionMatrix).profile.id == (
        "mvs_projection"
    )


def test_lookup_refuses_unknown_representations():
    assert representation_contract("DepthMap").representation == "sceneio.DepthMap"
    with pytest.raises(KeyError, match="unknown SceneIO representation"):
        representation_contract("NotARecord")
    with pytest.raises(TypeError, match="no normalization/scaling contract"):
        representation_contract(object())


def test_conversion_and_metric_claims_stay_narrow():
    direct = {
        name
        for name, contract in REPRESENTATION_CONTRACTS.items()
        if contract.profile.conversion == "direct"
    }
    assert direct == {
        "sceneio.GaussianCloud",
        "sceneio.Mesh",
        "sceneio.PointCloud",
    }

    metric = {
        name
        for name, contract in REPRESENTATION_CONTRACTS.items()
        if contract.scale == "metric"
    }
    assert metric == {
        "sceneio.ImuCalibration",
        "sceneio.RtmvDataset",
        "sceneio.colmap.TimeFrame",
    }
    assert representation_contract("sceneio.Reconstruction").scale == "arbitrary"
    assert representation_contract("sceneio.SE3").scale == "arbitrary"
    assert representation_contract("sceneio.FrameMeta").scale == (
        "record_declared"
    )
    for name in ("sceneio.Mesh", "sceneio.PointCloud"):
        contract = representation_contract(name)
        assert "unknown frame" in contract.refusal.lower()
        assert "unit-normalizes nonzero normals" in " ".join(contract.rules)


def test_gaussian_semantic_contract_qualifies_only_declared_world_normalization():
    contract = representation_contract(sceneio.GaussianCloud)
    assert contract.normalization == "declared"
    assert contract.scale == "mixed"
    assert contract.coordinates == "record_declared"
    assert contract.profile.conversion == "direct"
    assert set(contract.profile.scale_fields) == {
        "color_space",
        "coordinate_frame",
        "opacity_space",
        "quaternion_norm",
        "quaternion_order",
        "scale_to_meters",
        "scale_to_meters_source",
        "scale_space",
        "sh_basis",
        "sh_coefficient_order",
        "sh_layout",
        "sh_phase",
        "source_precision",
    }
    joined = " ".join((*contract.profile.rules, contract.profile.refusal))
    assert "qualified scale_to_meters" in joined
    assert "SH basis/phase/coefficient" in joined
    assert "directional-SH rotations" in joined


def test_dense_label_contracts_keep_ids_unscaled_and_unpacking_explicit():
    taxonomy = representation_contract(sceneio.LabelTaxonomy)
    semantic = representation_contract(sceneio.SemanticMap)
    instance = representation_contract(sceneio.InstanceMap)
    panoptic = representation_contract(sceneio.PanopticMap)
    assert taxonomy.profile.id == "label_taxonomy"
    assert semantic.profile.id == "semantic_labels"
    assert instance.profile.id == "instance_labels"
    assert panoptic.profile.id == "panoptic_labels"
    assert semantic.canonical_units == ("semantic_id", "boolean", "pixel")
    assert "instance_id" in instance.canonical_units
    assert "No packed divisor is implicit" in " ".join(panoptic.rules)
    assert all(contract.scale == "identity" for contract in (taxonomy, semantic, instance, panoptic))


def test_consolidated_records_have_one_owner_and_complete_semantics():
    depth = representation_contract("sceneio.DepthMap")
    assert depth.profile.id == "depth_declared"
    assert "scale_to_meters" in depth.profile.scale_fields

    rig = representation_contract("sceneio.CameraRig")
    assert "second" in rig.canonical_units
    assert "nanosecond" not in rig.canonical_units
    assert "reference_time = camera_time + time_offset_seconds" in " ".join(
        rig.rules
    )

    megaloc = representation_contract("sceneio.colmap.MegaLocArtifacts")
    assert megaloc.scale_fields == ("descriptors_normalized",)
    assert "never inferred" in megaloc.refusal

    features = representation_contract("sceneio.FeatureSet")
    assert "feature_score" in features.canonical_units
    assert "unit_interval" not in features.canonical_units

    sequence = representation_contract("sceneio.ImageSequence")
    assert "planar YUV" in " ".join(sequence.rules)

    imu_calibration = representation_contract("sceneio.ImuCalibration")
    assert imu_calibration.scale == "metric"
    assert "time_offset_ns" in imu_calibration.scale_fields
    assert "absent values remain distinct from zero" in " ".join(
        imu_calibration.rules
    )

    imu_sequence = representation_contract("sceneio.ImuSequence")
    assert imu_sequence.scale == "record_declared"
    assert "clock_domain" in imu_sequence.scale_fields
