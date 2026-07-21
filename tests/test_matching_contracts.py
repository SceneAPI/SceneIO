"""Validation tests for sceneio.matching contract types."""

from __future__ import annotations

import pytest

from sceneio.errors import ContractViolation
from sceneio.matching import MatcherTraits, MatchingOptions


class TestMatcherTraits:
    def test_detector_based(self) -> None:
        traits = MatcherTraits(persistent_keypoints=True, detector_free=False)
        assert traits.persistent_keypoints is True

    def test_detector_free(self) -> None:
        traits = MatcherTraits(persistent_keypoints=False, detector_free=True)
        assert traits.detector_free is True

    @pytest.mark.parametrize("field_name", ["persistent_keypoints", "detector_free"])
    def test_non_bool_field_raises(self, field_name: str) -> None:
        kwargs = {"persistent_keypoints": True, "detector_free": False, field_name: 1}
        with pytest.raises(ContractViolation, match=rf"MatcherTraits\.{field_name}"):
            MatcherTraits(**kwargs)  # type: ignore[arg-type]


class TestMatchingOptions:
    def test_defaults(self) -> None:
        options = MatchingOptions()
        assert options.seed is None
        assert options.extra == {}

    def test_extra_copied(self) -> None:
        source = {"ratio_test": 0.8}
        options = MatchingOptions(extra=source)
        source["ratio_test"] = 0.9
        assert options.extra == {"ratio_test": 0.8}

    @pytest.mark.parametrize("bad", [1.5, True, "7"])
    def test_bad_seed_raises(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match="seed"):
            MatchingOptions(seed=bad)  # type: ignore[arg-type]

    def test_non_mapping_extra_raises(self) -> None:
        with pytest.raises(ContractViolation, match="extra"):
            MatchingOptions(extra=[("k", "v")])  # type: ignore[arg-type]
