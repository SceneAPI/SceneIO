"""Sparse-correspondence contracts: features, pair matches, the graph.

``FeatureSet`` is the per-image detector output. ``PairCorrespondences``
carries the matches of one image pair in one of two modes — ``"indexed"``
(detector-based: index pairs into two FeatureSets) or ``"coordinates"``
(detector-free: raw pixel-coordinate pairs). ``CorrespondenceGraph``
aggregates per-image FeatureSets and per-pair correspondences (each pair
optionally carrying its verified two-view geometry).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np

from sceneio.data._validation import (
    ensure_array,
    ensure_choice,
    ensure_instance,
    ensure_integer_array,
)
from sceneio.errors import ContractViolation

CORRESPONDENCE_MODES: frozenset[str] = frozenset({"indexed", "coordinates"})


@dataclass(frozen=True)
class FeatureSet:
    """Per-image keypoints with optional descriptors and scores.

    ``descriptors`` may be any numeric dtype; the dtype tag is exposed
    as :attr:`descriptor_dtype` and can never drift from the array.
    """

    keypoints: np.ndarray  # (N, 2) float32, (x, y) pixel coordinates
    descriptors: np.ndarray | None = None  # (N, D), any numeric dtype
    scores: np.ndarray | None = None  # (N,) float32

    def __post_init__(self) -> None:
        keypoints = ensure_array(
            "FeatureSet.keypoints",
            self.keypoints,
            dtypes=(np.float32,),
            shape=(None, 2),
            finite=True,
        )
        n = keypoints.shape[0]
        if self.descriptors is not None:
            descriptors = ensure_array("FeatureSet.descriptors", self.descriptors, shape=(n, None))
            if not np.issubdtype(descriptors.dtype, np.number):
                raise ContractViolation(
                    f"FeatureSet.descriptors: expected a numeric dtype, "
                    f"got {descriptors.dtype.name}"
                )
        if self.scores is not None:
            ensure_array(
                "FeatureSet.scores",
                self.scores,
                dtypes=(np.float32,),
                shape=(n,),
                finite=True,
            )

    def __len__(self) -> int:
        return int(self.keypoints.shape[0])

    @property
    def descriptor_dtype(self) -> str | None:
        """The descriptor dtype tag (``"float32"``, ``"uint8"``, ...) or None."""
        return None if self.descriptors is None else self.descriptors.dtype.name

    @property
    def descriptor_dim(self) -> int | None:
        return None if self.descriptors is None else int(self.descriptors.shape[1])


@dataclass(frozen=True)
class TwoViewGeometry:
    """Verified two-view geometry for one pair (any subset of E/F/H)."""

    E: np.ndarray | None = None  # (3, 3) float64 essential matrix
    F: np.ndarray | None = None  # (3, 3) float64 fundamental matrix
    H: np.ndarray | None = None  # (3, 3) float64 homography
    num_inliers: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("E", "F", "H"):
            value = getattr(self, field_name)
            if value is not None:
                ensure_array(
                    f"TwoViewGeometry.{field_name}",
                    value,
                    dtypes=(np.float64,),
                    shape=(3, 3),
                    finite=True,
                )
        if self.num_inliers is not None and (
            not isinstance(self.num_inliers, int)
            or isinstance(self.num_inliers, bool)
            or self.num_inliers < 0
        ):
            raise ContractViolation(
                f"TwoViewGeometry.num_inliers: expected a non-negative int, "
                f"got {self.num_inliers!r}"
            )


@dataclass(frozen=True)
class PairCorrespondences:
    """Matches for one image pair, detector-based or detector-free.

    ``mode="indexed"``: ``indices`` is (M, 2) integer — column 0 indexes
    into the first image's FeatureSet, column 1 into the second's;
    coordinate fields must be None. ``mode="coordinates"``:
    ``coordinates_a`` / ``coordinates_b`` are (M, 2) float32 pixel
    coordinates in the first/second image; ``indices`` must be None.
    Use :meth:`from_indices` / :meth:`from_coordinates`.
    """

    mode: Literal["indexed", "coordinates"]
    indices: np.ndarray | None = None  # (M, 2) integer
    coordinates_a: np.ndarray | None = None  # (M, 2) float32
    coordinates_b: np.ndarray | None = None  # (M, 2) float32
    scores: np.ndarray | None = None  # (M,) float32
    geometry: TwoViewGeometry | None = None

    def __post_init__(self) -> None:
        ensure_choice("PairCorrespondences.mode", self.mode, CORRESPONDENCE_MODES)
        if self.mode == "indexed":
            if self.coordinates_a is not None or self.coordinates_b is not None:
                raise ContractViolation(
                    "PairCorrespondences: mode='indexed' must not carry "
                    "coordinates_a/coordinates_b (use mode='coordinates')"
                )
            if self.indices is None:
                raise ContractViolation("PairCorrespondences: mode='indexed' requires indices")
            ensure_integer_array(
                "PairCorrespondences.indices",
                self.indices,
                shape=(None, 2),
                non_negative=True,
            )
            count = int(self.indices.shape[0])
        else:
            if self.indices is not None:
                raise ContractViolation(
                    "PairCorrespondences: mode='coordinates' must not carry "
                    "indices (use mode='indexed')"
                )
            if self.coordinates_a is None or self.coordinates_b is None:
                raise ContractViolation(
                    "PairCorrespondences: mode='coordinates' requires both "
                    "coordinates_a and coordinates_b"
                )
            a = ensure_array(
                "PairCorrespondences.coordinates_a",
                self.coordinates_a,
                dtypes=(np.float32,),
                shape=(None, 2),
                finite=True,
            )
            ensure_array(
                "PairCorrespondences.coordinates_b",
                self.coordinates_b,
                dtypes=(np.float32,),
                shape=(a.shape[0], 2),
                finite=True,
            )
            count = int(a.shape[0])
        if self.scores is not None:
            ensure_array(
                "PairCorrespondences.scores",
                self.scores,
                dtypes=(np.float32,),
                shape=(count,),
                finite=True,
            )
        if self.geometry is not None:
            ensure_instance(
                "PairCorrespondences.geometry",
                self.geometry,
                TwoViewGeometry,
                "TwoViewGeometry",
            )

    @classmethod
    def from_indices(
        cls,
        indices: np.ndarray,
        *,
        scores: np.ndarray | None = None,
        geometry: TwoViewGeometry | None = None,
    ) -> PairCorrespondences:
        return cls(mode="indexed", indices=indices, scores=scores, geometry=geometry)

    @classmethod
    def from_coordinates(
        cls,
        coordinates_a: np.ndarray,
        coordinates_b: np.ndarray,
        *,
        scores: np.ndarray | None = None,
        geometry: TwoViewGeometry | None = None,
    ) -> PairCorrespondences:
        return cls(
            mode="coordinates",
            coordinates_a=coordinates_a,
            coordinates_b=coordinates_b,
            scores=scores,
            geometry=geometry,
        )

    def __len__(self) -> int:
        if self.mode == "indexed":
            assert self.indices is not None
            return int(self.indices.shape[0])
        assert self.coordinates_a is not None
        return int(self.coordinates_a.shape[0])


@dataclass(frozen=True)
class CorrespondenceGraph:
    """Per-image FeatureSets plus per-pair correspondences.

    ``features`` may be empty for a purely detector-free graph. Every
    ``"indexed"`` pair must reference FeatureSets present in
    ``features``, with in-range indices. Pair keys are ordered
    ``(image_a, image_b)`` tuples of distinct image ids; the
    correspondence columns/sides follow that order.
    """

    features: Mapping[str, FeatureSet]
    pairs: Mapping[tuple[str, str], PairCorrespondences]

    def __post_init__(self) -> None:
        features: dict[str, FeatureSet] = {}
        for image_id, feature_set in dict(self.features).items():
            if not isinstance(image_id, str) or not image_id:
                raise ContractViolation(
                    f"CorrespondenceGraph.features: image ids must be non-empty "
                    f"str, got {image_id!r}"
                )
            ensure_instance(
                f"CorrespondenceGraph.features[{image_id!r}]",
                feature_set,
                FeatureSet,
                "FeatureSet",
            )
            features[image_id] = feature_set
        pairs: dict[tuple[str, str], PairCorrespondences] = {}
        for key, pair in dict(self.pairs).items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not all(isinstance(part, str) and part for part in key)
            ):
                raise ContractViolation(
                    f"CorrespondenceGraph.pairs: keys must be (image_a, image_b) "
                    f"tuples of non-empty str, got {key!r}"
                )
            image_a, image_b = key
            if image_a == image_b:
                raise ContractViolation(
                    f"CorrespondenceGraph.pairs: self-pair {key!r} is not allowed"
                )
            ensure_instance(
                f"CorrespondenceGraph.pairs[{key!r}]",
                pair,
                PairCorrespondences,
                "PairCorrespondences",
            )
            if pair.mode == "indexed":
                assert pair.indices is not None
                for side, image_id in enumerate(key):
                    if image_id not in features:
                        raise ContractViolation(
                            f"CorrespondenceGraph.pairs[{key!r}]: indexed pair "
                            f"references image {image_id!r} with no FeatureSet"
                        )
                    if len(pair) and int(pair.indices[:, side].max()) >= len(features[image_id]):
                        raise ContractViolation(
                            f"CorrespondenceGraph.pairs[{key!r}]: index "
                            f"{int(pair.indices[:, side].max())} out of range for "
                            f"FeatureSet {image_id!r} of {len(features[image_id])} "
                            f"keypoints"
                        )
            pairs[key] = pair
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "pairs", pairs)
