"""Conformance kits for the mapping/matching procedure contracts.

Implementation bundles prove they honor the contracts by calling
:func:`assert_mapper_conformance` / :func:`assert_matcher_conformance`
from their own test suites. The kits exercise a Protocol implementation
against tiny synthetic fixtures and validate result shapes, frames, and
**traits honesty** (e.g. a ``requires_correspondences=False`` mapper
must accept ``correspondences=None``).

pytest is imported *inside* the functions that need it — importing this
module never imports pytest, so pytest-free consumers stay clean.
"""

from __future__ import annotations

import numpy as np

from sceneio.data import (
    CorrespondenceGraph,
    FeatureSet,
    PairCorrespondences,
    ViewInput,
)
from sceneio.errors import ContractViolation
from sceneio.mapping import Mapper, MapperTraits, MappingResult
from sceneio.matching import (
    FeatureExtractor,
    GeometricVerifier,
    MatcherTraits,
    PairMatcher,
)

__all__ = [
    "assert_mapper_conformance",
    "assert_matcher_conformance",
    "make_synthetic_correspondence_graph",
    "make_synthetic_feature_set",
    "make_synthetic_image",
    "make_synthetic_views",
]


def make_synthetic_image(height: int = 8, width: int = 8, *, seed: int = 0) -> np.ndarray:
    """A tiny deterministic (H, W, 3) uint8 image."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def make_synthetic_views(
    count: int = 3, *, height: int = 8, width: int = 8, seed: int = 0
) -> tuple[ViewInput, ...]:
    """Tiny in-memory views named ``view000``, ``view001``, ..."""
    return tuple(
        ViewInput(
            image=make_synthetic_image(height, width, seed=seed + index),
            name=f"view{index:03d}",
        )
        for index in range(count)
    )


def make_synthetic_feature_set(
    num_keypoints: int = 6,
    descriptor_dim: int = 8,
    *,
    height: int = 8,
    width: int = 8,
    seed: int = 0,
) -> FeatureSet:
    """A tiny deterministic FeatureSet with float32 descriptors."""
    rng = np.random.default_rng(seed)
    keypoints = np.stack(
        [
            rng.uniform(0, width, size=num_keypoints),
            rng.uniform(0, height, size=num_keypoints),
        ],
        axis=1,
    ).astype(np.float32)
    descriptors = rng.normal(size=(num_keypoints, descriptor_dim)).astype(np.float32)
    scores = rng.uniform(0, 1, size=num_keypoints).astype(np.float32)
    return FeatureSet(keypoints=keypoints, descriptors=descriptors, scores=scores)


def make_synthetic_correspondence_graph(
    views: tuple[ViewInput, ...] | None = None,
    *,
    num_keypoints: int = 6,
    seed: int = 0,
) -> CorrespondenceGraph:
    """An indexed CorrespondenceGraph chaining consecutive views."""
    if views is None:
        views = make_synthetic_views()
    names = [
        view.ref if view.ref is not None else f"view{index:03d}" for index, view in enumerate(views)
    ]
    features = {
        name: make_synthetic_feature_set(num_keypoints, seed=seed + index)
        for index, name in enumerate(names)
    }
    matches = np.stack(
        [np.arange(num_keypoints, dtype=np.int64)] * 2, axis=1
    )  # trivial i<->i matches
    pairs = {
        (names[index], names[index + 1]): PairCorrespondences.from_indices(matches)
        for index in range(len(names) - 1)
    }
    return CorrespondenceGraph(features=features, pairs=pairs)


def assert_mapper_conformance(
    mapper: Mapper,
    views_fixture: tuple[ViewInput, ...] | None = None,
) -> MappingResult:
    """Exercise ``mapper`` against a synthetic fixture; assert conformance.

    Checks structural conformance to the :class:`Mapper` Protocol, then
    traits honesty:

    - ``requires_correspondences=True``: mapping without correspondences
      must raise ``ContractViolation``; mapping with a graph succeeds.
    - ``requires_correspondences=False``: mapping with
      ``correspondences=None`` must succeed.
    - ``emits_dense=True``: the result must carry a dense payload.
    - ``metric_capable=False``: the result must not claim metric scale.

    Result alignment is enforced positionally: one pose per input view,
    where ``None`` marks an unregistered view (allowed, as long as at
    least one view registers — validated by ``MappingResult`` itself).

    Returns the (validated) :class:`MappingResult` for extra checks.
    """
    import pytest

    assert isinstance(mapper, Mapper), (
        f"{type(mapper).__name__} does not satisfy the Mapper Protocol (needs traits() and map())"
    )
    traits = mapper.traits()
    assert isinstance(traits, MapperTraits), (
        f"traits() must return MapperTraits, got {type(traits).__name__}"
    )

    views = views_fixture if views_fixture is not None else make_synthetic_views()
    assert len(views) >= 2, "mapper conformance needs at least two views"

    if traits.requires_correspondences:
        with pytest.raises(ContractViolation):
            mapper.map(views, correspondences=None)
        graph = make_synthetic_correspondence_graph(views)
        result = mapper.map(views, correspondences=graph)
    else:
        result = mapper.map(views, correspondences=None)

    assert isinstance(result, MappingResult), (
        f"map() must return MappingResult, got {type(result).__name__}"
    )
    assert len(result.poses) == len(views), (
        f"poses must align to views: {len(views)} views, {len(result.poses)} poses"
    )
    # Unregistered views (poses[i] is None) are allowed — alignment is
    # positional, and MappingResult itself guarantees >= 1 registered view.
    mask = result.registered_mask
    assert mask.shape == (len(views),), (
        f"registered_mask must align to views: {len(views)} views, shape {mask.shape}"
    )
    if traits.emits_dense:
        assert result.dense is not None, (
            "traits claim emits_dense=True but the result has dense=None"
        )
    if result.frame.scale == "metric":
        assert traits.metric_capable, (
            "result claims scale='metric' but traits say metric_capable=False"
        )
    return result


def assert_matcher_conformance(
    matcher: PairMatcher,
    *,
    extractor: FeatureExtractor | None = None,
    verifier: GeometricVerifier | None = None,
) -> PairCorrespondences:
    """Exercise a matching stack against synthetic images; assert conformance.

    ``matcher`` is required; pass ``extractor`` / ``verifier`` to check
    those too. Traits honesty checked:

    - ``detector_free=True``: image-ref operands, ``mode="coordinates"``.
    - ``detector_free=False``: FeatureSet operands, ``mode="indexed"``,
      indices in range of the operand FeatureSets.
    - a verifier preserves the mode and never grows the match set.

    Returns the final :class:`PairCorrespondences` for extra checks.
    """
    assert isinstance(matcher, PairMatcher), (
        f"{type(matcher).__name__} does not satisfy the PairMatcher Protocol "
        f"(needs traits() and match_pair())"
    )
    traits = matcher.traits()
    assert isinstance(traits, MatcherTraits), (
        f"traits() must return MatcherTraits, got {type(traits).__name__}"
    )

    image_a = make_synthetic_image(seed=1)
    image_b = make_synthetic_image(seed=2)

    if extractor is not None:
        assert isinstance(extractor, FeatureExtractor), (
            f"{type(extractor).__name__} does not satisfy the FeatureExtractor "
            f"Protocol (needs extract())"
        )
        features_a = extractor.extract(image_a)
        features_b = extractor.extract(image_b)
        for name, features in (("a", features_a), ("b", features_b)):
            assert isinstance(features, FeatureSet), (
                f"extract() must return FeatureSet for image {name}, got {type(features).__name__}"
            )
    else:
        features_a = make_synthetic_feature_set(seed=1)
        features_b = make_synthetic_feature_set(num_keypoints=5, seed=2)

    if traits.detector_free:
        pair = matcher.match_pair(image_a, image_b)
        assert isinstance(pair, PairCorrespondences), (
            f"match_pair() must return PairCorrespondences, got {type(pair).__name__}"
        )
        assert pair.mode == "coordinates", (
            f"traits claim detector_free=True but match_pair() returned "
            f"mode={pair.mode!r} (expected 'coordinates')"
        )
    else:
        pair = matcher.match_pair(features_a, features_b)
        assert isinstance(pair, PairCorrespondences), (
            f"match_pair() must return PairCorrespondences, got {type(pair).__name__}"
        )
        assert pair.mode == "indexed", (
            f"traits claim detector_free=False but match_pair() returned "
            f"mode={pair.mode!r} (expected 'indexed')"
        )
        assert pair.indices is not None
        if len(pair):
            for side, features in ((0, features_a), (1, features_b)):
                max_index = int(pair.indices[:, side].max())
                assert max_index < len(features), (
                    f"match_pair() emitted index {max_index} out of range for "
                    f"operand FeatureSet of {len(features)} keypoints (side {side})"
                )

    if verifier is not None:
        assert isinstance(verifier, GeometricVerifier), (
            f"{type(verifier).__name__} does not satisfy the GeometricVerifier "
            f"Protocol (needs verify())"
        )
        verified = verifier.verify(pair)
        assert isinstance(verified, PairCorrespondences), (
            f"verify() must return PairCorrespondences, got {type(verified).__name__}"
        )
        assert verified.mode == pair.mode, (
            f"verify() must preserve the mode: got {verified.mode!r}, expected {pair.mode!r}"
        )
        assert len(verified) <= len(pair), (
            f"verify() must never grow the match set: {len(pair)} in, {len(verified)} out"
        )
        pair = verified

    return pair
