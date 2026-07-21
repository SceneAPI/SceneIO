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
from dataclasses import dataclass
from typing import Literal

import numpy as np

from sceneio.data._validation import as_float64, ensure_array, ensure_positive_int
from sceneio.errors import ContractViolation


class CameraModel(enum.Enum):
    """COLMAP's camera-model vocabulary (names, ids, and param layouts)."""

    SIMPLE_PINHOLE = "SIMPLE_PINHOLE"
    PINHOLE = "PINHOLE"
    SIMPLE_RADIAL = "SIMPLE_RADIAL"
    RADIAL = "RADIAL"
    OPENCV = "OPENCV"
    OPENCV_FISHEYE = "OPENCV_FISHEYE"
    FULL_OPENCV = "FULL_OPENCV"
    FOV = "FOV"
    SIMPLE_RADIAL_FISHEYE = "SIMPLE_RADIAL_FISHEYE"
    RADIAL_FISHEYE = "RADIAL_FISHEYE"
    THIN_PRISM_FISHEYE = "THIN_PRISM_FISHEYE"

    @property
    def model_id(self) -> int:
        """COLMAP's integer model id."""
        return _MODEL_IDS[self]

    @property
    def param_names(self) -> tuple[str, ...]:
        """COLMAP's ordered parameter names for this model."""
        return _PARAM_NAMES[self]

    @property
    def num_params(self) -> int:
        return len(_PARAM_NAMES[self])


_MODEL_IDS: dict[CameraModel, int] = {
    CameraModel.SIMPLE_PINHOLE: 0,
    CameraModel.PINHOLE: 1,
    CameraModel.SIMPLE_RADIAL: 2,
    CameraModel.RADIAL: 3,
    CameraModel.OPENCV: 4,
    CameraModel.OPENCV_FISHEYE: 5,
    CameraModel.FULL_OPENCV: 6,
    CameraModel.FOV: 7,
    CameraModel.SIMPLE_RADIAL_FISHEYE: 8,
    CameraModel.RADIAL_FISHEYE: 9,
    CameraModel.THIN_PRISM_FISHEYE: 10,
}

_PARAM_NAMES: dict[CameraModel, tuple[str, ...]] = {
    CameraModel.SIMPLE_PINHOLE: ("f", "cx", "cy"),
    CameraModel.PINHOLE: ("fx", "fy", "cx", "cy"),
    CameraModel.SIMPLE_RADIAL: ("f", "cx", "cy", "k"),
    CameraModel.RADIAL: ("f", "cx", "cy", "k1", "k2"),
    CameraModel.OPENCV: ("fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2"),
    CameraModel.OPENCV_FISHEYE: ("fx", "fy", "cx", "cy", "k1", "k2", "k3", "k4"),
    CameraModel.FULL_OPENCV: (
        "fx",
        "fy",
        "cx",
        "cy",
        "k1",
        "k2",
        "p1",
        "p2",
        "k3",
        "k4",
        "k5",
        "k6",
    ),
    CameraModel.FOV: ("fx", "fy", "cx", "cy", "omega"),
    CameraModel.SIMPLE_RADIAL_FISHEYE: ("f", "cx", "cy", "k"),
    CameraModel.RADIAL_FISHEYE: ("f", "cx", "cy", "k1", "k2"),
    CameraModel.THIN_PRISM_FISHEYE: (
        "fx",
        "fy",
        "cx",
        "cy",
        "k1",
        "k2",
        "p1",
        "p2",
        "k3",
        "k4",
        "sx1",
        "sy1",
    ),
}


@dataclass(frozen=True)
class CameraIntrinsics:
    """Parametric camera calibration in COLMAP's model vocabulary."""

    model: CameraModel
    width: int
    height: int
    params: np.ndarray  # (model.num_params,) float64

    def __post_init__(self) -> None:
        model = self.model
        if isinstance(model, str):
            try:
                model = CameraModel(model)
            except ValueError:
                raise ContractViolation(
                    f"CameraIntrinsics.model: unknown camera model {self.model!r}; "
                    f"expected one of {[m.value for m in CameraModel]}"
                ) from None
            object.__setattr__(self, "model", model)
        elif not isinstance(model, CameraModel):
            raise ContractViolation(
                f"CameraIntrinsics.model: expected CameraModel, got {type(model).__name__}"
            )
        ensure_positive_int("CameraIntrinsics.width", self.width)
        ensure_positive_int("CameraIntrinsics.height", self.height)
        params = as_float64("CameraIntrinsics.params", self.params, (None,))
        if params.shape[0] != model.num_params:
            raise ContractViolation(
                f"CameraIntrinsics.params: model {model.value} takes "
                f"{model.num_params} params {model.param_names}, got {params.shape[0]}"
            )
        object.__setattr__(self, "params", params)


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

    intrinsics: CameraIntrinsics | None = None
    rays: RayMap | None = None

    def __post_init__(self) -> None:
        if (self.intrinsics is None) == (self.rays is None):
            given = "both" if self.intrinsics is not None else "neither"
            raise ContractViolation(
                f"Calibration: exactly one of intrinsics/rays must be set, got {given}"
            )
        if self.intrinsics is not None and not isinstance(self.intrinsics, CameraIntrinsics):
            raise ContractViolation(
                f"Calibration.intrinsics: expected CameraIntrinsics, "
                f"got {type(self.intrinsics).__name__}"
            )
        if self.rays is not None and not isinstance(self.rays, RayMap):
            raise ContractViolation(
                f"Calibration.rays: expected RayMap, got {type(self.rays).__name__}"
            )

    @classmethod
    def from_intrinsics(cls, intrinsics: CameraIntrinsics) -> Calibration:
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
