"""End-to-end tests of the conformance kits with reference fakes.

FakeMapper / FakeExtractor / FakeMatcher / FakeVerifier are honest
reference implementations of the Protocols; the "dishonest" variants
verify the kits actually catch traits lies.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from sceneapi_io.data import (
    SE3,
    ConfidenceMap,
    CorrespondenceGraph,
    FeatureSet,
    FrameMeta,
    ImageRef,
    PairCorrespondences,
    Pointmap,
    TrackedPointCloud,
    TwoViewGeometry,
    ViewInput,
)
from sceneapi_io.errors import ContractViolation
from sceneapi_io.mapping import Mapper, MapperTraits, MappingOptions, MappingResult
from sceneapi_io.matching import (
    FeatureExtractor,
    GeometricVerifier,
    MatcherTraits,
    MatchingOptions,
    PairMatcher,
)
from sceneapi_io.testing import (
    assert_mapper_conformance,
    assert_matcher_conformance,
    make_synthetic_correspondence_graph,
    make_synthetic_feature_set,
    make_synthetic_image,
    make_synthetic_views,
)

FEED_FORWARD_TRAITS = MapperTraits(
    requires_correspondences=False,
    accepts_pose_priors=True,
    accepts_depth_priors=True,
    accepts_calibration=True,
    emits_dense=True,
    metric_capable=True,
)

CLASSICAL_TRAITS = MapperTraits(
    requires_correspondences=True,
    accepts_pose_priors=False,
    accepts_depth_priors=False,
    accepts_calibration=True,
    emits_dense=False,
    metric_capable=False,
)


class FakeMapper:
    """Reference in-memory Mapper honoring its declared traits.

    ``unregister_last=True`` leaves the final view unregistered
    (``poses[-1] is None``, with the aligned ``dense`` entry None too) —
    the amended-contract fixture for partially-registered results.
    """

    def __init__(
        self,
        traits: MapperTraits = FEED_FORWARD_TRAITS,
        *,
        honest: bool = True,
        unregister_last: bool = False,
    ) -> None:
        self._traits = traits
        self._honest = honest
        self._unregister_last = unregister_last

    def traits(self) -> MapperTraits:
        return self._traits

    def map(
        self,
        views: Sequence[ViewInput],
        *,
        correspondences: CorrespondenceGraph | None = None,
        options: MappingOptions | None = None,
    ) -> MappingResult:
        if self._honest and self._traits.requires_correspondences and correspondences is None:
            raise ContractViolation("FakeMapper requires a correspondence graph")
        poses: tuple[SE3 | None, ...] = tuple(SE3.identity() for _ in views)
        if self._unregister_last and len(views) > 1:
            poses = (*poses[:-1], None)
        dense = None
        if self._traits.emits_dense:
            dense = []
            for index, view in enumerate(views):
                if poses[index] is None:
                    dense.append(None)
                    continue
                image = view.image
                h, w = (image.shape[0], image.shape[1]) if isinstance(image, np.ndarray) else (8, 8)
                dense.append(
                    (
                        Pointmap(points=np.zeros((h, w, 3), dtype=np.float32)),
                        ConfidenceMap(values=np.full((h, w), 0.5, dtype=np.float32)),
                    )
                )
            dense = tuple(dense)
        geometry = TrackedPointCloud(xyz=np.zeros((4, 3), dtype=np.float32))
        scale = "metric" if self._traits.metric_capable else "arbitrary"
        provenance = "model_claimed" if scale == "metric" else "unknown"
        return MappingResult(
            poses=poses,
            frame=FrameMeta(scale=scale, scale_provenance=provenance),
            geometry=geometry,
            dense=dense,
            stats={"num_views": len(views)},
        )


class FakeExtractor:
    def extract(self, image: ImageRef, *, options: MatchingOptions | None = None) -> FeatureSet:
        return make_synthetic_feature_set(num_keypoints=6, seed=int(np.asarray(image).sum()) % 97)


class FakeMatcher:
    """Detector-based (FeatureSet operands) or detector-free (image refs)."""

    def __init__(self, *, detector_free: bool = False, honest: bool = True) -> None:
        self._traits = MatcherTraits(
            persistent_keypoints=not detector_free, detector_free=detector_free
        )
        self._honest = honest

    def traits(self) -> MatcherTraits:
        return self._traits

    def match_pair(
        self,
        a: FeatureSet | ImageRef,
        b: FeatureSet | ImageRef,
        *,
        options: MatchingOptions | None = None,
    ) -> PairCorrespondences:
        detector_free = (
            self._traits.detector_free if self._honest else not self._traits.detector_free
        )
        if detector_free:
            coords = np.array([[1.0, 1.0], [2.0, 2.0]], dtype=np.float32)
            return PairCorrespondences.from_coordinates(coords, coords + 1.0)
        assert isinstance(a, FeatureSet)
        assert isinstance(b, FeatureSet)
        count = min(len(a), len(b))
        indices = np.stack([np.arange(count, dtype=np.int64)] * 2, axis=1)
        return PairCorrespondences.from_indices(indices)


class FakeVerifier:
    """Keeps every other correspondence and attaches a two-view geometry."""

    def verify(
        self,
        pair: PairCorrespondences,
        *,
        options: MatchingOptions | None = None,
    ) -> PairCorrespondences:
        geometry = TwoViewGeometry(E=np.eye(3), num_inliers=max(len(pair) // 2, 0))
        if pair.mode == "indexed":
            assert pair.indices is not None
            return PairCorrespondences.from_indices(pair.indices[::2], geometry=geometry)
        assert pair.coordinates_a is not None
        assert pair.coordinates_b is not None
        return PairCorrespondences.from_coordinates(
            pair.coordinates_a[::2], pair.coordinates_b[::2], geometry=geometry
        )


class TestSyntheticFixtures:
    def test_make_synthetic_views(self) -> None:
        views = make_synthetic_views(3)
        assert len(views) == 3
        assert views[0].ref == "view000"

    def test_make_synthetic_image_deterministic(self) -> None:
        np.testing.assert_array_equal(make_synthetic_image(seed=5), make_synthetic_image(seed=5))

    def test_make_synthetic_graph_covers_consecutive_pairs(self) -> None:
        views = make_synthetic_views(3)
        graph = make_synthetic_correspondence_graph(views)
        assert set(graph.pairs) == {("view000", "view001"), ("view001", "view002")}
        assert set(graph.features) == {"view000", "view001", "view002"}


class TestMapperConformanceKit:
    def test_feed_forward_mapper_passes(self) -> None:
        result = assert_mapper_conformance(FakeMapper(FEED_FORWARD_TRAITS))
        assert result.dense is not None

    def test_classical_mapper_passes(self) -> None:
        result = assert_mapper_conformance(FakeMapper(CLASSICAL_TRAITS))
        assert result.dense is None

    def test_custom_views_fixture(self) -> None:
        views = make_synthetic_views(4, height=6, width=5)
        result = assert_mapper_conformance(FakeMapper(FEED_FORWARD_TRAITS), views)
        assert len(result.poses) == 4
        assert result.dense is not None
        assert result.dense[0][0].shape == (6, 5)

    def test_mapper_with_unregistered_view_passes(self) -> None:
        # Amended contract: a mapper may leave views unregistered as long
        # as alignment holds and >= 1 view registers; the kit must accept it.
        result = assert_mapper_conformance(FakeMapper(FEED_FORWARD_TRAITS, unregister_last=True))
        assert result.poses[-1] is None
        assert result.dense is not None
        assert result.dense[-1] is None
        np.testing.assert_array_equal(
            result.registered_mask,
            np.array([True] * (len(result.poses) - 1) + [False]),
        )

    def test_classical_mapper_with_unregistered_view_passes(self) -> None:
        result = assert_mapper_conformance(FakeMapper(CLASSICAL_TRAITS, unregister_last=True))
        assert result.poses[-1] is None
        assert bool(result.registered_mask.any())

    def test_fake_mapper_satisfies_runtime_protocol(self) -> None:
        assert isinstance(FakeMapper(), Mapper)

    def test_non_mapper_fails(self) -> None:
        with pytest.raises(AssertionError, match="does not satisfy the Mapper"):
            assert_mapper_conformance(object())  # type: ignore[arg-type]

    def test_dishonest_requires_correspondences_fails(self) -> None:
        # Claims to require correspondences but happily maps without them.
        mapper = FakeMapper(CLASSICAL_TRAITS, honest=False)
        with pytest.raises(BaseException, match="DID NOT RAISE"):
            assert_mapper_conformance(mapper)

    def test_dishonest_emits_dense_fails(self) -> None:
        class NoDenseMapper(FakeMapper):
            def map(self, views, *, correspondences=None, options=None):  # type: ignore[override]
                result = super().map(views, correspondences=correspondences, options=options)
                return MappingResult(
                    poses=result.poses,
                    frame=result.frame,
                    geometry=result.geometry,
                    dense=None,
                    stats=result.stats,
                )

        with pytest.raises(AssertionError, match="emits_dense"):
            assert_mapper_conformance(NoDenseMapper(FEED_FORWARD_TRAITS))

    def test_dishonest_metric_claim_fails(self) -> None:
        class MetricBraggart(FakeMapper):
            def map(self, views, *, correspondences=None, options=None):  # type: ignore[override]
                result = super().map(views, correspondences=correspondences, options=options)
                return MappingResult(
                    poses=result.poses,
                    frame=FrameMeta(scale="metric", scale_provenance="model_claimed"),
                    geometry=result.geometry,
                    dense=result.dense,
                    stats=result.stats,
                )

        traits = MapperTraits(
            requires_correspondences=False,
            accepts_pose_priors=False,
            accepts_depth_priors=False,
            accepts_calibration=False,
            emits_dense=False,
            metric_capable=False,
        )
        with pytest.raises(AssertionError, match="metric_capable"):
            assert_mapper_conformance(MetricBraggart(traits))

    def test_misaligned_poses_fail(self) -> None:
        class DropsAView(FakeMapper):
            def map(self, views, *, correspondences=None, options=None):  # type: ignore[override]
                return super().map(
                    list(views)[:-1], correspondences=correspondences, options=options
                )

        with pytest.raises(AssertionError, match="align"):
            assert_mapper_conformance(DropsAView(CLASSICAL_TRAITS))


class TestMatcherConformanceKit:
    def test_detector_based_stack_passes(self) -> None:
        pair = assert_matcher_conformance(
            FakeMatcher(detector_free=False),
            extractor=FakeExtractor(),
            verifier=FakeVerifier(),
        )
        assert pair.mode == "indexed"
        assert pair.geometry is not None

    def test_detector_free_matcher_passes(self) -> None:
        pair = assert_matcher_conformance(FakeMatcher(detector_free=True))
        assert pair.mode == "coordinates"

    def test_matcher_alone_uses_synthetic_features(self) -> None:
        pair = assert_matcher_conformance(FakeMatcher(detector_free=False))
        assert pair.mode == "indexed"

    def test_fakes_satisfy_runtime_protocols(self) -> None:
        assert isinstance(FakeMatcher(), PairMatcher)
        assert isinstance(FakeExtractor(), FeatureExtractor)
        assert isinstance(FakeVerifier(), GeometricVerifier)

    def test_non_matcher_fails(self) -> None:
        with pytest.raises(AssertionError, match="does not satisfy the PairMatcher"):
            assert_matcher_conformance(object())  # type: ignore[arg-type]

    def test_dishonest_detector_free_claim_fails(self) -> None:
        # Claims detector_free=True but returns indexed correspondences.
        class LyingMatcher(FakeMatcher):
            def match_pair(self, a, b, *, options=None):  # type: ignore[override]
                indices = np.zeros((2, 2), dtype=np.int64)
                return PairCorrespondences.from_indices(indices)

        with pytest.raises(AssertionError, match="detector_free=True"):
            assert_matcher_conformance(LyingMatcher(detector_free=True))

    def test_dishonest_detector_based_claim_fails(self) -> None:
        with pytest.raises(AssertionError, match="detector_free=False"):
            assert_matcher_conformance(FakeMatcher(detector_free=False, honest=False))

    def test_out_of_range_indices_fail(self) -> None:
        class OutOfRangeMatcher(FakeMatcher):
            def match_pair(self, a, b, *, options=None):  # type: ignore[override]
                indices = np.array([[0, 99]], dtype=np.int64)
                return PairCorrespondences.from_indices(indices)

        with pytest.raises(AssertionError, match="out of range"):
            assert_matcher_conformance(OutOfRangeMatcher(detector_free=False))

    def test_growing_verifier_fails(self) -> None:
        class GrowingVerifier(FakeVerifier):
            def verify(self, pair, *, options=None):  # type: ignore[override]
                assert pair.indices is not None
                doubled = np.concatenate([pair.indices, pair.indices])
                return PairCorrespondences.from_indices(doubled)

        with pytest.raises(AssertionError, match="never grow"):
            assert_matcher_conformance(FakeMatcher(detector_free=False), verifier=GrowingVerifier())

    def test_mode_switching_verifier_fails(self) -> None:
        class ModeSwitchingVerifier(FakeVerifier):
            def verify(self, pair, *, options=None):  # type: ignore[override]
                coords = np.zeros((1, 2), dtype=np.float32)
                return PairCorrespondences.from_coordinates(coords, coords)

        with pytest.raises(AssertionError, match="preserve the mode"):
            assert_matcher_conformance(
                FakeMatcher(detector_free=False), verifier=ModeSwitchingVerifier()
            )
