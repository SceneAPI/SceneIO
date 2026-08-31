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
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

import numpy as np

from sceneio import _core
from sceneio._data._validation import (
    ensure_array,
    ensure_choice,
    ensure_instance,
    ensure_integer_array,
)
from sceneio._data.transforms import SE3
from sceneio.errors import ContractViolation

CORRESPONDENCE_MODES: frozenset[str] = frozenset({"indexed", "coordinates"})
INDEX_VALIDATION_MODES: frozenset[str] = frozenset({"eager", "deferred"})


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

    features: Mapping[str, _core.FeatureSet]
    pairs: Mapping[tuple[str, str], PairCorrespondences]
    verified_pairs: Mapping[tuple[str, str], PairCorrespondences] = field(
        default_factory=dict
    )
    configurations: Mapping[tuple[str, str], int] = field(default_factory=dict)
    relative_poses: Mapping[tuple[str, str], SE3] = field(default_factory=dict)
    source_metadata: Mapping[tuple[str, str], Mapping[str, object]] = field(
        default_factory=dict
    )
    index_validation: Literal["eager", "deferred"] = "eager"
    _storage: object | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        features: dict[str, _core.FeatureSet] = {}
        for image_id, feature_set in dict(self.features).items():
            if not isinstance(image_id, str) or not image_id:
                raise ContractViolation(
                    f"CorrespondenceGraph.features: image ids must be non-empty "
                    f"str, got {image_id!r}"
                )
            ensure_instance(
                f"CorrespondenceGraph.features[{image_id!r}]",
                feature_set,
                _core.FeatureSet,
                "FeatureSet",
            )
            features[image_id] = feature_set
        ensure_choice(
            "CorrespondenceGraph.index_validation",
            self.index_validation,
            INDEX_VALIDATION_MODES,
        )

        def validate_pairs(
            values: Mapping[tuple[str, str], PairCorrespondences],
            channel: str,
        ) -> dict[tuple[str, str], PairCorrespondences]:
            pairs: dict[tuple[str, str], PairCorrespondences] = {}
            for key, pair in dict(values).items():
                self._validate_pair_key(key, pair, channel)
                if pair.mode == "indexed" and self.index_validation == "eager":
                    self._validate_pair_indices(key, pair, features, channel)
                pairs[key] = pair
            return pairs

        pairs = validate_pairs(self.pairs, "pairs")
        verified_pairs = validate_pairs(self.verified_pairs, "verified_pairs")
        known_pairs = set(pairs) | set(verified_pairs)

        configurations: dict[tuple[str, str], int] = {}
        for key, config in dict(self.configurations).items():
            self._validate_metadata_key(key, known_pairs, "configurations")
            if isinstance(config, bool) or not isinstance(config, int) or config not in range(10):
                raise ContractViolation(
                    f"CorrespondenceGraph.configurations[{key!r}]: "
                    "expected an integer in 0..9"
                )
            configurations[key] = config

        relative_poses: dict[tuple[str, str], SE3] = {}
        for key, pose in dict(self.relative_poses).items():
            self._validate_metadata_key(key, known_pairs, "relative_poses")
            ensure_instance(
                f"CorrespondenceGraph.relative_poses[{key!r}]",
                pose,
                SE3,
                "SE3",
            )
            if pose.convention != "opencv_second_from_first":
                raise ContractViolation(
                    f"CorrespondenceGraph.relative_poses[{key!r}]: expected "
                    "convention='opencv_second_from_first'"
                )
            relative_poses[key] = pose

        source_metadata: dict[tuple[str, str], Mapping[str, object]] = {}
        for key, metadata in dict(self.source_metadata).items():
            self._validate_metadata_key(key, known_pairs, "source_metadata")
            if not isinstance(metadata, Mapping) or any(
                not isinstance(name, str) or not name for name in metadata
            ):
                raise ContractViolation(
                    f"CorrespondenceGraph.source_metadata[{key!r}]: expected "
                    "a mapping with non-empty string keys"
                )
            source_metadata[key] = MappingProxyType(dict(metadata))

        object.__setattr__(self, "features", MappingProxyType(features))
        object.__setattr__(self, "pairs", MappingProxyType(pairs))
        object.__setattr__(self, "verified_pairs", MappingProxyType(verified_pairs))
        object.__setattr__(self, "configurations", MappingProxyType(configurations))
        object.__setattr__(self, "relative_poses", MappingProxyType(relative_poses))
        object.__setattr__(self, "source_metadata", MappingProxyType(source_metadata))

    @staticmethod
    def _validate_metadata_key(
        key: object,
        known_pairs: set[tuple[str, str]],
        channel: str,
    ) -> None:
        if key not in known_pairs:
            raise ContractViolation(
                f"CorrespondenceGraph.{channel}: key {key!r} has no raw or "
                "verified correspondence pair"
            )

    @staticmethod
    def _validate_pair_key(
        key: object,
        pair: object,
        channel: str,
    ) -> None:
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or not all(isinstance(part, str) and part for part in key)
        ):
            raise ContractViolation(
                f"CorrespondenceGraph.{channel}: keys must be (image_a, image_b) "
                f"tuples of non-empty str, got {key!r}"
            )
        image_a, image_b = key
        if image_a == image_b:
            raise ContractViolation(
                f"CorrespondenceGraph.{channel}: self-pair {key!r} is not allowed"
            )
        ensure_instance(
            f"CorrespondenceGraph.{channel}[{key!r}]",
            pair,
            PairCorrespondences,
            "PairCorrespondences",
        )

    @staticmethod
    def _validate_pair_indices(
        key: tuple[str, str],
        pair: PairCorrespondences,
        features: Mapping[str, _core.FeatureSet],
        channel: str,
    ) -> None:
        assert pair.indices is not None
        for side, image_id in enumerate(key):
            if image_id not in features:
                raise ContractViolation(
                    f"CorrespondenceGraph.{channel}[{key!r}]: indexed pair "
                    f"references image {image_id!r} with no FeatureSet"
                )
            if len(pair) and int(pair.indices[:, side].max()) >= len(features[image_id]):
                raise ContractViolation(
                    f"CorrespondenceGraph.{channel}[{key!r}]: index "
                    f"{int(pair.indices[:, side].max())} out of range for "
                    f"FeatureSet {image_id!r} of {len(features[image_id])} keypoints"
                )

    def validate_indices(self) -> CorrespondenceGraph:
        """Return the same graph after eager endpoint index validation."""
        if self.index_validation == "eager":
            return self
        return CorrespondenceGraph(
            self.features,
            self.pairs,
            self.verified_pairs,
            self.configurations,
            self.relative_poses,
            self.source_metadata,
            index_validation="eager",
        )
