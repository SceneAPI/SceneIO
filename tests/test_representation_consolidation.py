"""Finite gates for the direct in-memory representation consolidation."""

from __future__ import annotations

import pytest

import sceneio
from sceneio.representations import REPRESENTATION_CONTRACTS

REMOVED_REPRESENTATIONS = frozenset(
    {
        "sceneio.Camera",
        "sceneio.MatchGraph",
        "sceneio.MeshScene",
        "sceneio.colmap.MappingCamera",
        "sceneio.colmap.MappingImage",
        "sceneio.colmap.MappingMatch",
        "sceneio.colmap.NamedMatches",
        "sceneio.colmap.SiftFeatures",
        "sceneio.colmap.SimilarityTransform",
        "sceneio.data.DepthMap",
        "sceneio.data.FeatureSet",
        "sceneio.data.PosedViewSet",
        "sceneio.data.TrackedPointCloud",
    }
)


def test_merge_boundary_stays_finite_during_consolidation() -> None:
    """Each slice may remove only identities in the approved removal set."""
    current = set(REPRESENTATION_CONTRACTS)
    assert len(current - REMOVED_REPRESENTATIONS) == 90
    assert len(current) == 90 + len(current & REMOVED_REPRESENTATIONS)


def test_io_capability_inventory_is_unchanged_by_consolidation() -> None:
    capabilities = sceneio.capabilities()
    assert len(capabilities) == 77
    assert sum(item.can_read for item in capabilities.values()) == 77
    assert sum(item.can_write for item in capabilities.values()) == 75
    assert sum(item.can_inspect for item in capabilities.values()) == 77
    assert sum(bool(item.partial_selectors) for item in capabilities.values()) == 40
    assert sum(len(item.partial_selectors) for item in capabilities.values()) == 46
    assert sum(item.streams_read for item in capabilities.values()) == 77
    assert sum(item.streams_write for item in capabilities.values()) == 73


def test_representation_surface_is_provisional_during_pre_1_reset() -> None:
    representations = (
        contract
        for contract in sceneio.PUBLIC_TYPE_CONTRACTS.values()
        if contract.kind == "representation"
    )
    assert all(contract.stability == "provisional" for contract in representations)


@pytest.mark.parametrize("path", sorted(REMOVED_REPRESENTATIONS))
def test_removed_representation_names_do_not_resolve(path: str) -> None:
    with pytest.raises(KeyError, match="unknown SceneIO representation"):
        sceneio.representation_contract(path)
