"""The matching procedure contracts.

Three runtime-checkable Protocols cover the matching stage:

- :class:`FeatureExtractor` — image in, :class:`FeatureSet` out.
- :class:`PairMatcher` — matches one image pair. Its
  :class:`MatcherTraits` make the two operating families explicit
  rather than hiding them behind one dishonest signature:

  * detector-based (``detector_free=False``): ``match_pair`` receives
    two :class:`FeatureSet` operands and returns ``mode="indexed"``
    correspondences (index pairs into those sets).
  * detector-free (``detector_free=True``): ``match_pair`` receives two
    image refs (:data:`~sceneio.data.ImageRef`) and returns
    ``mode="coordinates"`` correspondences — there are no persistent
    per-image keypoints to index into.

  The operand type is therefore ``FeatureSet | ImageRef``, and
  ``traits()`` tells the caller which to pass; a conforming matcher
  raises :class:`~sceneio.errors.ContractViolation` when handed the
  wrong operand kind.

- :class:`GeometricVerifier` — filters a pair's correspondences and may
  attach the estimated two-view geometry. Mode is preserved; the output
  is a subset (``len(out) <= len(in)``).

This namespace imports only :mod:`sceneio.data` — never
:mod:`sceneio.mapping` (guard-tested), so either can graduate to
its own distribution later.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sceneio.data import FeatureSet, ImageRef, PairCorrespondences
from sceneio.data._validation import ensure_bool
from sceneio.errors import ContractViolation

__all__ = [
    "FeatureExtractor",
    "GeometricVerifier",
    "MatcherTraits",
    "MatchingOptions",
    "PairMatcher",
]


@dataclass(frozen=True)
class MatcherTraits:
    """What a concrete matcher is, honestly.

    - ``persistent_keypoints``: the same image always yields the same
      keypoints across pairs, so correspondences can be chained into
      multi-view tracks. Detector-based pipelines have this;
      pair-conditioned detector-free matchers typically do not.
    - ``detector_free``: ``match_pair`` operates on image refs and
      returns coordinate correspondences (no FeatureSet operands).
    """

    persistent_keypoints: bool
    detector_free: bool

    def __post_init__(self) -> None:
        ensure_bool("MatcherTraits.persistent_keypoints", self.persistent_keypoints)
        ensure_bool("MatcherTraits.detector_free", self.detector_free)


@dataclass(frozen=True)
class MatchingOptions:
    """Common matching knobs; implementation-specific ones ride in ``extra``."""

    seed: int | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seed is not None and (
            not isinstance(self.seed, int) or isinstance(self.seed, bool)
        ):
            raise ContractViolation(
                f"MatchingOptions.seed: expected an int or None, got {self.seed!r}"
            )
        if not isinstance(self.extra, Mapping):
            raise ContractViolation(
                f"MatchingOptions.extra: expected a mapping, got {type(self.extra).__name__}"
            )
        object.__setattr__(self, "extra", dict(self.extra))


@runtime_checkable
class FeatureExtractor(Protocol):
    """Extracts a per-image :class:`FeatureSet` from an image."""

    def extract(
        self,
        image: ImageRef,
        *,
        options: MatchingOptions | None = None,
    ) -> FeatureSet: ...


@runtime_checkable
class PairMatcher(Protocol):
    """Matches one image pair; see the module docstring for the operand
    contract implied by ``traits().detector_free``."""

    def traits(self) -> MatcherTraits: ...

    def match_pair(
        self,
        a: FeatureSet | ImageRef,
        b: FeatureSet | ImageRef,
        *,
        options: MatchingOptions | None = None,
    ) -> PairCorrespondences: ...


@runtime_checkable
class GeometricVerifier(Protocol):
    """Filters a pair's correspondences to the geometrically consistent
    subset, optionally attaching the estimated two-view geometry."""

    def verify(
        self,
        pair: PairCorrespondences,
        *,
        options: MatchingOptions | None = None,
    ) -> PairCorrespondences: ...
