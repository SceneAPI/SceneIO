from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import sceneio.colmap
import sceneio.colmap_mvs
import sceneio.data
import sceneio.io
from sceneio.representations import (
    REPRESENTATION_CONTRACT_SCHEMA_VERSION,
    REPRESENTATION_CONTRACTS,
    REPRESENTATION_PROFILES,
    REPRESENTATION_UNIT_VOCABULARY,
    representation_contract,
)

ROOT = Path(__file__).resolve().parents[1]

_NAMESPACES = (
    ("sceneio", sceneio.io),
    ("sceneio.data", sceneio.data),
    ("sceneio.colmap", sceneio.colmap),
    ("sceneio.colmap_mvs", sceneio.colmap_mvs),
)
_NON_REPRESENTATION_CLASSES = {
    "sceneio": {
        "ArrayInspection",
        "Codec",
        "CodecCapabilities",
        "ColmapDatabaseConversionReport",
        "CoordinateConvention",
        "DepthEncoding",
        "FormatCoordinateContract",
        "FormatError",
        "Inspection",
        "NativeFeatureCapabilities",
    },
    "sceneio.data": {"CameraModel"},
    "sceneio.colmap": {"ColmapAdapterError"},
    "sceneio.colmap_mvs": {"ColmapMvsError"},
}


def _public_representation_ids() -> set[str]:
    result: set[str] = set()
    for public_prefix, module in _NAMESPACES:
        exclusions = _NON_REPRESENTATION_CLASSES[public_prefix]
        exported_classes = {
            name
            for name in module.__all__
            if inspect.isclass(getattr(module, name))
        }
        assert exclusions <= exported_classes
        result.update(
            f"{public_prefix}.{name}"
            for name in exported_classes - exclusions
        )
    return result


def test_contract_catalog_exactly_covers_public_representation_classes():
    assert REPRESENTATION_CONTRACT_SCHEMA_VERSION == 1
    assert set(REPRESENTATION_CONTRACTS) == _public_representation_ids()
    assert len(REPRESENTATION_CONTRACTS) == 93


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


def test_lookup_accepts_public_alias_type_and_unambiguous_name():
    assert representation_contract("Image").representation == "sceneio.Image"
    assert representation_contract("sceneio.io.Image") is representation_contract(
        sceneio.io.Image
    )
    assert representation_contract(sceneio.data.Mask).representation == (
        "sceneio.data.Mask"
    )
    assert representation_contract(sceneio.colmap.SimilarityTransform).profile.id == (
        "colmap_adapter_sim3"
    )
    assert representation_contract(sceneio.colmap_mvs.ProjectionMatrix).profile.id == (
        "mvs_projection"
    )


def test_lookup_refuses_ambiguous_or_unknown_representations():
    with pytest.raises(ValueError, match=r"ambiguous representation.*sceneio.DepthMap"):
        representation_contract("DepthMap")
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
    assert direct == {"sceneio.Mesh", "sceneio.PointCloud", "sceneio.PosedViewSet"}

    metric = {
        name
        for name, contract in REPRESENTATION_CONTRACTS.items()
        if contract.scale == "metric"
    }
    assert metric == {
        "sceneio.ImuCalibration",
        "sceneio.MeshScene",
        "sceneio.RtmvDataset",
        "sceneio.colmap.TimeFrame",
    }
    assert representation_contract("sceneio.Reconstruction").scale == "arbitrary"
    assert representation_contract("sceneio.data.SE3").scale == "arbitrary"
    assert representation_contract("sceneio.data.FrameMeta").scale == (
        "record_declared"
    )
    for name in ("sceneio.Mesh", "sceneio.PointCloud"):
        contract = representation_contract(name)
        assert "unknown frame" in contract.refusal.lower()
        assert "unit-normalizes nonzero normals" in " ".join(contract.rules)


def test_gaussian_activation_contract_does_not_claim_world_normalization():
    contract = representation_contract(sceneio.io.GaussianCloud)
    assert contract.normalization == "declared"
    assert contract.scale == "mixed"
    assert contract.coordinates == "unknown"
    assert contract.profile.conversion == "requires_context"
    assert set(contract.profile.scale_fields) == {
        "opacity_space",
        "quaternion_order",
        "scale_space",
        "sh_layout",
        "source_precision",
    }
    joined = " ".join((*contract.profile.rules, contract.profile.refusal))
    assert "Means use an unspecified source length unit" in joined
    assert "SH basis" in joined


def test_compiled_and_neutral_records_with_same_name_remain_distinct():
    compiled_depth = representation_contract("sceneio.DepthMap")
    neutral_depth = representation_contract("sceneio.data.DepthMap")
    assert compiled_depth.profile.id == "depth_declared"
    assert neutral_depth.profile.id == "depth_parent_scale"
    assert "scale_to_meters" in compiled_depth.profile.scale_fields
    assert "FrameMeta.scale" in neutral_depth.profile.scale_fields

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
