"""Sparse tracked point cloud contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from sceneapi_io.data._validation import ensure_array
from sceneapi_io.errors import ContractViolation


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
        ):
            raise ContractViolation(
                f"TrackObservation.keypoint_idx: expected a non-negative int, "
                f"got {self.keypoint_idx!r}"
            )


@dataclass(frozen=True)
class TrackedPointCloud:
    """Sparse 3-D points with optional color and per-point tracks.

    ``tracks``, when present, is aligned to ``xyz``: entry ``i`` lists
    the :class:`TrackObservation` s of point ``i`` (which image saw it,
    at which keypoint index).
    """

    xyz: np.ndarray  # (N, 3) float32 or float64, finite
    rgb: np.ndarray | None = None  # (N, 3) uint8
    tracks: tuple[tuple[TrackObservation, ...], ...] | None = None  # len N

    def __post_init__(self) -> None:
        xyz = ensure_array(
            "TrackedPointCloud.xyz",
            self.xyz,
            dtypes=(np.float32, np.float64),
            shape=(None, 3),
            finite=True,
        )
        n = int(xyz.shape[0])
        if self.rgb is not None:
            ensure_array("TrackedPointCloud.rgb", self.rgb, dtypes=(np.uint8,), shape=(n, 3))
        if self.tracks is not None:
            if not isinstance(self.tracks, Sequence) or isinstance(self.tracks, str | bytes):
                raise ContractViolation(
                    f"TrackedPointCloud.tracks: expected a sequence of per-point "
                    f"observation lists, got {type(self.tracks).__name__}"
                )
            if len(self.tracks) != n:
                raise ContractViolation(
                    f"TrackedPointCloud.tracks: expected one track per point "
                    f"({n}), got {len(self.tracks)}"
                )
            normalized: list[tuple[TrackObservation, ...]] = []
            for point_idx, track in enumerate(self.tracks):
                if not isinstance(track, Sequence) or isinstance(track, str | bytes):
                    raise ContractViolation(
                        f"TrackedPointCloud.tracks[{point_idx}]: expected a "
                        f"sequence of TrackObservation, got {type(track).__name__}"
                    )
                for obs in track:
                    if not isinstance(obs, TrackObservation):
                        raise ContractViolation(
                            f"TrackedPointCloud.tracks[{point_idx}]: expected "
                            f"TrackObservation entries, got {type(obs).__name__}"
                        )
                normalized.append(tuple(track))
            object.__setattr__(self, "tracks", tuple(normalized))

    def __len__(self) -> int:
        return int(self.xyz.shape[0])
