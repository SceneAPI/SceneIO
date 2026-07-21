"""Dense per-pixel data contracts: depth, pointmaps, confidence, masks.

These are the image-aligned array types: strict dtype (no silent
conversion of large buffers) and strict shape, validated on
construction with :class:`~sceneio.errors.ContractViolation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from sceneio.data._validation import ensure_array, ensure_choice
from sceneio.errors import ContractViolation

POINTMAP_FRAMES: frozenset[str] = frozenset({"world", "camera"})


@dataclass(frozen=True)
class DepthMap:
    """Per-pixel depth in the camera frame — (H, W) float32.

    ``valid`` marks pixels carrying a real measurement; ``None`` means
    every pixel is valid. Valid pixels must be finite and strictly
    positive; invalid pixels may hold anything (0, NaN, garbage).
    Depth units follow the owning set's :class:`FrameMeta` scale.
    """

    depth: np.ndarray  # (H, W) float32
    valid: np.ndarray | None = None  # (H, W) bool

    def __post_init__(self) -> None:
        depth = ensure_array("DepthMap.depth", self.depth, dtypes=(np.float32,), shape=(None, None))
        if self.valid is not None:
            ensure_array(
                "DepthMap.valid",
                self.valid,
                dtypes=(np.bool_,),
                shape=(depth.shape[0], depth.shape[1]),
            )
            observed = depth[self.valid]
        else:
            observed = depth.reshape(-1)
        if observed.size:
            if not np.isfinite(observed).all():
                raise ContractViolation(
                    "DepthMap.depth: valid pixels contain non-finite values (NaN/Inf)"
                )
            min_depth = float(observed.min())
            if min_depth <= 0.0:
                raise ContractViolation(
                    f"DepthMap.depth: valid pixels must be > 0 (min {min_depth:g})"
                )

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.depth.shape[0]), int(self.depth.shape[1]))


@dataclass(frozen=True)
class Pointmap:
    """Per-pixel 3-D points — (H, W, 3) float32 — in a declared frame.

    ``frame`` declares the coordinate frame of the points: ``"world"``
    (the owning set's world frame, see :class:`FrameMeta`) or
    ``"camera"`` (the emitting view's camera frame). Invalid pixels may
    be NaN.
    """

    points: np.ndarray  # (H, W, 3) float32
    frame: Literal["world", "camera"] = "world"

    def __post_init__(self) -> None:
        ensure_array("Pointmap.points", self.points, dtypes=(np.float32,), shape=(None, None, 3))
        ensure_choice("Pointmap.frame", self.frame, POINTMAP_FRAMES)

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.points.shape[0]), int(self.points.shape[1]))


@dataclass(frozen=True)
class ConfidenceMap:
    """Per-pixel confidence in [0, 1] — (H, W) float32, finite."""

    values: np.ndarray  # (H, W) float32 in [0, 1]

    def __post_init__(self) -> None:
        values = ensure_array(
            "ConfidenceMap.values",
            self.values,
            dtypes=(np.float32,),
            shape=(None, None),
            finite=True,
        )
        if values.size:
            lo, hi = float(values.min()), float(values.max())
            if lo < 0.0 or hi > 1.0:
                raise ContractViolation(
                    f"ConfidenceMap.values: values must lie in [0, 1] "
                    f"(observed range [{lo:g}, {hi:g}])"
                )

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.values.shape[0]), int(self.values.shape[1]))


@dataclass(frozen=True)
class Mask:
    """Per-pixel boolean mask — (H, W) bool. True = pixel participates."""

    mask: np.ndarray  # (H, W) bool

    def __post_init__(self) -> None:
        ensure_array("Mask.mask", self.mask, dtypes=(np.bool_,), shape=(None, None))

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.mask.shape[0]), int(self.mask.shape[1]))
