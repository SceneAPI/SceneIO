"""The neutral mapping procedure contract.

A :class:`Mapper` turns a sequence of :class:`~sceneapi_io.data.ViewInput`
into a :class:`MappingResult`. The contract is neutral between the
classical and feed-forward families: correspondences are *optional* at
the signature level, and :class:`MapperTraits` declares what a concrete
implementation actually requires and consumes.

Honesty rules a conforming implementation must follow (exercised by
:func:`sceneapi_io.testing.assert_mapper_conformance`):

- ``requires_correspondences=True`` mappers MUST raise
  :class:`~sceneapi_io.errors.ContractViolation` when called with
  ``correspondences=None``; ``False`` mappers MUST accept ``None``.
- ``emits_dense=True`` mappers return a non-None ``dense`` payload.
- A result may only claim ``frame.scale == "metric"`` when the mapper's
  traits say ``metric_capable=True``.

This namespace imports only :mod:`sceneapi_io.data` — never
:mod:`sceneapi_io.matching` (guard-tested), so either can graduate to
its own distribution later.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sceneapi_io.data import (
    Calibration,
    ConfidenceMap,
    CorrespondenceGraph,
    FrameMeta,
    Pointmap,
    TrackedPointCloud,
    ViewInput,
)
from sceneapi_io.data._validation import ensure_bool, ensure_instance
from sceneapi_io.data.transforms import SE3
from sceneapi_io.errors import ContractViolation

__all__ = [
    "Mapper",
    "MapperTraits",
    "MappingOptions",
    "MappingResult",
]


@dataclass(frozen=True)
class MapperTraits:
    """What a concrete Mapper requires, consumes, and can honestly claim.

    - ``requires_correspondences``: True for the classical family
      (COLMAP-style incremental/global mappers); False for feed-forward
      models that map raw views.
    - ``accepts_pose_priors`` / ``accepts_depth_priors`` /
      ``accepts_calibration``: whether the per-view optional inputs are
      consumed (False = silently ignored is NOT allowed to become
      required; it means "ignored").
    - ``emits_dense``: the result carries per-view (Pointmap,
      ConfidenceMap) payloads.
    - ``metric_capable``: the mapper can produce metric-scale results
      (given the right priors); without it a result must not claim
      ``scale="metric"``.
    """

    requires_correspondences: bool
    accepts_pose_priors: bool
    accepts_depth_priors: bool
    accepts_calibration: bool
    emits_dense: bool
    metric_capable: bool

    def __post_init__(self) -> None:
        for field_name in (
            "requires_correspondences",
            "accepts_pose_priors",
            "accepts_depth_priors",
            "accepts_calibration",
            "emits_dense",
            "metric_capable",
        ):
            ensure_bool(f"MapperTraits.{field_name}", getattr(self, field_name))


@dataclass(frozen=True)
class MappingOptions:
    """Common mapping knobs; implementation-specific ones ride in ``extra``."""

    max_views: int | None = None
    seed: int | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_views is not None and (
            not isinstance(self.max_views, int)
            or isinstance(self.max_views, bool)
            or self.max_views < 1
        ):
            raise ContractViolation(
                f"MappingOptions.max_views: expected a positive int or None, got {self.max_views!r}"
            )
        if self.seed is not None and (
            not isinstance(self.seed, int) or isinstance(self.seed, bool)
        ):
            raise ContractViolation(
                f"MappingOptions.seed: expected an int or None, got {self.seed!r}"
            )
        if not isinstance(self.extra, Mapping):
            raise ContractViolation(
                f"MappingOptions.extra: expected a mapping, got {type(self.extra).__name__}"
            )
        object.__setattr__(self, "extra", dict(self.extra))


@dataclass(frozen=True)
class MappingResult:
    """A mapping run's output, index-aligned to the input views.

    ``poses[i]`` is view ``i``'s pose (one shared convention);
    ``calibrations`` and ``dense`` are likewise aligned when present.
    ``geometry`` is the sparse tracked cloud (classical mappers);
    ``dense`` the per-view (Pointmap, ConfidenceMap) payload
    (feed-forward mappers). ``frame`` declares world frame + scale +
    scale provenance; ``stats`` is free-form run metadata.
    """

    poses: tuple[SE3, ...]
    frame: FrameMeta
    calibrations: tuple[Calibration, ...] | None = None
    geometry: TrackedPointCloud | None = None
    dense: tuple[tuple[Pointmap, ConfidenceMap], ...] | None = None
    stats: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        poses = _typed_tuple("MappingResult.poses", self.poses, SE3)
        if not poses:
            raise ContractViolation("MappingResult.poses: expected at least one pose")
        conventions = {pose.convention for pose in poses}
        if len(conventions) > 1:
            raise ContractViolation(
                f"MappingResult.poses: mixed pose conventions {sorted(conventions)}"
            )
        object.__setattr__(self, "poses", poses)
        ensure_instance("MappingResult.frame", self.frame, FrameMeta, "FrameMeta")
        if self.calibrations is not None:
            calibrations = _typed_tuple(
                "MappingResult.calibrations", self.calibrations, Calibration
            )
            if len(calibrations) != len(poses):
                raise ContractViolation(
                    f"MappingResult.calibrations: expected one per view "
                    f"({len(poses)}), got {len(calibrations)}"
                )
            object.__setattr__(self, "calibrations", calibrations)
        if self.geometry is not None:
            ensure_instance(
                "MappingResult.geometry",
                self.geometry,
                TrackedPointCloud,
                "TrackedPointCloud",
            )
        if self.dense is not None:
            dense = self._validated_dense(self.dense, len(poses))
            object.__setattr__(self, "dense", dense)
        if not isinstance(self.stats, Mapping):
            raise ContractViolation(
                f"MappingResult.stats: expected a mapping, got {type(self.stats).__name__}"
            )
        object.__setattr__(self, "stats", dict(self.stats))

    @staticmethod
    def _validated_dense(
        dense: object, num_views: int
    ) -> tuple[tuple[Pointmap, ConfidenceMap], ...]:
        if isinstance(dense, str | bytes) or not isinstance(dense, Sequence):
            raise ContractViolation(
                f"MappingResult.dense: expected a sequence of "
                f"(Pointmap, ConfidenceMap) pairs, got {type(dense).__name__}"
            )
        if len(dense) != num_views:
            raise ContractViolation(
                f"MappingResult.dense: expected one (Pointmap, ConfidenceMap) "
                f"per view ({num_views}), got {len(dense)}"
            )
        out: list[tuple[Pointmap, ConfidenceMap]] = []
        for index, item in enumerate(dense):
            if not isinstance(item, tuple) or len(item) != 2:
                raise ContractViolation(
                    f"MappingResult.dense[{index}]: expected a "
                    f"(Pointmap, ConfidenceMap) pair, got {type(item).__name__}"
                )
            pointmap, confidence = item
            ensure_instance(f"MappingResult.dense[{index}][0]", pointmap, Pointmap, "Pointmap")
            ensure_instance(
                f"MappingResult.dense[{index}][1]",
                confidence,
                ConfidenceMap,
                "ConfidenceMap",
            )
            if pointmap.shape != confidence.shape:
                raise ContractViolation(
                    f"MappingResult.dense[{index}]: Pointmap shape "
                    f"{pointmap.shape} != ConfidenceMap shape {confidence.shape}"
                )
            out.append((pointmap, confidence))
        return tuple(out)

    def __len__(self) -> int:
        return len(self.poses)


def _typed_tuple(name: str, value: object, expected: type) -> tuple:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ContractViolation(
            f"{name}: expected a sequence of {expected.__name__}, got {type(value).__name__}"
        )
    for index, item in enumerate(value):
        if not isinstance(item, expected):
            raise ContractViolation(
                f"{name}[{index}]: expected {expected.__name__}, got {type(item).__name__}"
            )
    return tuple(value)


@runtime_checkable
class Mapper(Protocol):
    """The neutral mapping contract.

    Implementations MUST honor their own :class:`MapperTraits` (see the
    module docstring for the honesty rules); conformance is provable
    with :func:`sceneapi_io.testing.assert_mapper_conformance`.
    """

    def traits(self) -> MapperTraits: ...

    def map(
        self,
        views: Sequence[ViewInput],
        *,
        correspondences: CorrespondenceGraph | None = None,
        options: MappingOptions | None = None,
    ) -> MappingResult: ...
