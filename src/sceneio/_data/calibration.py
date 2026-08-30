"""Camera calibration contracts: COLMAP intrinsics or a per-pixel ray map.

``CameraIntrinsics`` is the parametric form — a COLMAP camera-model enum
plus its model-specific params vector (COLMAP's exact model names, ids,
and parameter layouts). ``RayMap`` is the first-class alternative for
non-pinhole / non-parametric cameras: a per-pixel field of unit ray
directions in the camera frame (the calibration form the feed-forward
family predicts natively). ``Calibration`` is the mutually-exclusive
union of the two.
"""

from __future__ import annotations

import enum
import operator
from dataclasses import dataclass
from typing import Literal

import numpy as np

from sceneio import _core
from sceneio._camera_models import (
    CAMERA_MODEL_IDS_BY_NAME,
    CAMERA_MODEL_NAMES,
    CAMERA_MODEL_PARAMETER_NAMES,
)
from sceneio._data._validation import ensure_array
from sceneio.errors import ContractViolation


class _CameraModelMixin:
    @property
    def model_id(self) -> int:
        """COLMAP's integer model id."""
        return CAMERA_MODEL_IDS_BY_NAME[self.value]

    @property
    def param_names(self) -> tuple[str, ...]:
        """COLMAP's ordered parameter names for this model."""
        return CAMERA_MODEL_PARAMETER_NAMES[self.model_id]

    @property
    def num_params(self) -> int:
        return len(self.param_names)

    @classmethod
    def from_id(cls, model_id: object):
        """Resolve a persisted integer id or raise ``ValueError``."""
        try:
            selected = operator.index(model_id)
        except TypeError:
            raise ValueError(f"unknown camera model id {model_id!r}") from None
        if selected < 0 or selected >= len(CAMERA_MODEL_NAMES):
            raise ValueError(f"unknown camera model id {selected}")
        return cls(CAMERA_MODEL_NAMES[selected])


CameraModel = enum.Enum(
    "CameraModel",
    {name: name for name in CAMERA_MODEL_NAMES},
    type=_CameraModelMixin,
    module=__name__,
)
CameraModel.__doc__ = "COLMAP's camera-model vocabulary (names, ids, and param layouts)."


@dataclass(frozen=True)
class RayMap:
    """Per-pixel unit ray directions in the camera frame — (H, W, 3).

    The non-parametric calibration form: pixel ``(v, u)`` observes along
    unit direction ``directions[v, u]`` (OpenCV camera axes). This is
    the first-class alternative to :class:`CameraIntrinsics` for
    non-pinhole cameras and for models that predict rays directly.
    """

    directions: np.ndarray  # (H, W, 3) float32 or float64, unit-norm

    _UNIT_ATOL = 1e-3

    def __post_init__(self) -> None:
        directions = ensure_array(
            "RayMap.directions",
            self.directions,
            dtypes=(np.float32, np.float64),
            shape=(None, None, 3),
            finite=True,
        )
        norms = np.linalg.norm(directions.astype(np.float64, copy=False), axis=-1)
        max_dev = float(np.abs(norms - 1.0).max()) if norms.size else 0.0
        if max_dev > self._UNIT_ATOL:
            raise ContractViolation(
                f"RayMap.directions: rays must be unit-norm "
                f"(max |norm - 1| = {max_dev:.2e}, tolerance {self._UNIT_ATOL})"
            )

    @property
    def height(self) -> int:
        return int(self.directions.shape[0])

    @property
    def width(self) -> int:
        return int(self.directions.shape[1])


@dataclass(frozen=True)
class Calibration:
    """Exactly one calibration form: parametric intrinsics XOR a ray map."""

    intrinsics: _core.CameraIntrinsics | None = None
    rays: RayMap | None = None

    def __post_init__(self) -> None:
        if (self.intrinsics is None) == (self.rays is None):
            given = "both" if self.intrinsics is not None else "neither"
            raise ContractViolation(
                f"Calibration: exactly one of intrinsics/rays must be set, got {given}"
            )
        if self.intrinsics is not None and not isinstance(
            self.intrinsics, _core.CameraIntrinsics
        ):
            raise ContractViolation(
                f"Calibration.intrinsics: expected CameraIntrinsics, "
                f"got {type(self.intrinsics).__name__}"
            )
        if self.rays is not None and not isinstance(self.rays, RayMap):
            raise ContractViolation(
                f"Calibration.rays: expected RayMap, got {type(self.rays).__name__}"
            )

    @classmethod
    def from_intrinsics(cls, intrinsics: _core.CameraIntrinsics) -> Calibration:
        return cls(intrinsics=intrinsics)

    @classmethod
    def from_rays(cls, rays: RayMap) -> Calibration:
        return cls(rays=rays)

    @property
    def kind(self) -> Literal["intrinsics", "rays"]:
        return "intrinsics" if self.intrinsics is not None else "rays"

    @property
    def image_size(self) -> tuple[int, int]:
        """The declared (height, width) of the calibrated image."""
        if self.intrinsics is not None:
            return (self.intrinsics.height, self.intrinsics.width)
        assert self.rays is not None
        return (self.rays.height, self.rays.width)
