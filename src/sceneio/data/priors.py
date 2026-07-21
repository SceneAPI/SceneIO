"""Pose prior contract."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sceneio.data._validation import as_float64, ensure_instance
from sceneio.data.transforms import SE3
from sceneio.errors import ContractViolation


@dataclass(frozen=True)
class PosePrior:
    """A prior belief about a view's pose.

    ``weight`` is a scalar confidence (bigger = trusted more);
    ``covariance`` the optional (6, 6) uncertainty over the se(3)
    tangent (rotation then translation). Both are optional and
    independent. ``is_metric`` declares whether the prior's translation
    is in metric units — the anchor a mapper needs to claim
    ``scale="metric"`` with ``scale_provenance="prior_anchored"``.
    """

    pose: SE3
    weight: float | None = None
    covariance: object | None = None  # (6, 6) float64
    is_metric: bool = False

    def __post_init__(self) -> None:
        ensure_instance("PosePrior.pose", self.pose, SE3, "SE3")
        if self.weight is not None:
            if not isinstance(self.weight, int | float) or isinstance(self.weight, bool):
                raise ContractViolation(
                    f"PosePrior.weight: expected a non-negative float or None, "
                    f"got {type(self.weight).__name__}"
                )
            weight = float(self.weight)
            if not math.isfinite(weight) or weight < 0.0:
                raise ContractViolation(
                    f"PosePrior.weight: expected a finite non-negative float, got {weight!r}"
                )
            object.__setattr__(self, "weight", weight)
        if self.covariance is not None:
            object.__setattr__(
                self,
                "covariance",
                as_float64("PosePrior.covariance", self.covariance, (6, 6)),
            )
        if not isinstance(self.is_metric, bool):
            raise ContractViolation(
                f"PosePrior.is_metric: expected bool, got {type(self.is_metric).__name__}"
            )
