"""Ergonomic row view for canonical PointCloud observation tracks."""

from __future__ import annotations

from dataclasses import dataclass

from sceneio.errors import ContractViolation


@dataclass(frozen=True)
class TrackObservation:
    """One 2-D observation of a 3-D point: an image and a keypoint index."""

    image_id: str
    keypoint_idx: int

    def __post_init__(self) -> None:
        if not isinstance(self.image_id, str) or not self.image_id:
            raise ContractViolation(
                f"TrackObservation.image_id: expected a non-empty str, got {self.image_id!r}"
            )
        if (
            not isinstance(self.keypoint_idx, int)
            or isinstance(self.keypoint_idx, bool)
            or self.keypoint_idx < 0
            or self.keypoint_idx > 0xFFFF_FFFF_FFFF_FFFF
        ):
            raise ContractViolation(
                f"TrackObservation.keypoint_idx: expected a non-negative int, "
                f"got {self.keypoint_idx!r}"
            )
