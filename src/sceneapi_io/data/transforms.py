"""Rigid (SE3) and similarity (Sim3) transforms with explicit convention tags.

Every transform carries a ``convention`` tag naming both the coordinate
convention (OpenCV: +x right, +y down, +z forward) and the direction of
the mapping. The default, ``"opencv_cam2world"``, maps camera-frame
points to world-frame points (``x_world = R @ x_cam + t``); the inverse
direction is ``"opencv_world2cam"`` — COLMAP's native pose direction.

Conversion helpers to/from COLMAP's world-to-camera quaternion form
(``qvec`` as ``(w, x, y, z)`` + ``tvec``, the ``images.txt`` layout) are
provided so adapters never hand-roll the inversion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from sceneapi_io.data._validation import as_float64, ensure_choice
from sceneapi_io.errors import ContractViolation

DEFAULT_CONVENTION = "opencv_cam2world"

POSE_CONVENTIONS: frozenset[str] = frozenset({"opencv_cam2world", "opencv_world2cam"})

_FLIPPED = {"opencv_cam2world": "opencv_world2cam", "opencv_world2cam": "opencv_cam2world"}

_ROTATION_ATOL = 1e-5


def _validate_rotation(name: str, rotation: np.ndarray) -> None:
    residual = rotation @ rotation.T - np.eye(3)
    if float(np.abs(residual).max()) > _ROTATION_ATOL:
        raise ContractViolation(
            f"{name}: matrix is not orthonormal "
            f"(max |R @ R.T - I| = {float(np.abs(residual).max()):.2e})"
        )
    det = float(np.linalg.det(rotation))
    if abs(det - 1.0) > _ROTATION_ATOL:
        raise ContractViolation(
            f"{name}: matrix is not a proper rotation (det = {det:.6f}, expected +1)"
        )


def _quat_wxyz_to_rotation(q: np.ndarray) -> np.ndarray:
    w, x, y, z = (float(v) for v in q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _rotation_to_quat_wxyz(rotation: np.ndarray) -> np.ndarray:
    r = rotation
    trace = float(np.trace(r))
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (r[2, 1] - r[1, 2]) / s
        y = (r[0, 2] - r[2, 0]) / s
        z = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
        w = (r[2, 1] - r[1, 2]) / s
        x = 0.25 * s
        y = (r[0, 1] + r[1, 0]) / s
        z = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
        w = (r[0, 2] - r[2, 0]) / s
        x = (r[0, 1] + r[1, 0]) / s
        y = 0.25 * s
        z = (r[1, 2] + r[2, 1]) / s
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
        w = (r[1, 0] - r[0, 1]) / s
        x = (r[0, 2] + r[2, 0]) / s
        y = (r[1, 2] + r[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    q /= float(np.linalg.norm(q))
    if q[0] < 0:
        q = -q
    return q


def _validated_unit_quat(name: str, qvec_wxyz: object) -> np.ndarray:
    q = as_float64(name, qvec_wxyz, (4,))
    norm = float(np.linalg.norm(q))
    if abs(norm - 1.0) > 1e-3:
        raise ContractViolation(f"{name}: quaternion is not unit-norm (|q| = {norm:.6f})")
    return q / norm


@dataclass(frozen=True)
class SE3:
    """A rigid transform: ``x_out = rotation @ x_in + translation``.

    ``convention`` names what "in" and "out" are; the default
    ``"opencv_cam2world"`` maps camera-frame points into the world frame.
    """

    rotation: np.ndarray  # (3, 3) float64, proper rotation
    translation: np.ndarray  # (3,) float64
    convention: str = DEFAULT_CONVENTION

    def __post_init__(self) -> None:
        object.__setattr__(self, "rotation", as_float64("SE3.rotation", self.rotation, (3, 3)))
        object.__setattr__(
            self, "translation", as_float64("SE3.translation", self.translation, (3,))
        )
        _validate_rotation("SE3.rotation", self.rotation)
        ensure_choice("SE3.convention", self.convention, POSE_CONVENTIONS)

    @classmethod
    def identity(cls, convention: str = DEFAULT_CONVENTION) -> SE3:
        return cls(np.eye(3), np.zeros(3), convention=convention)

    @property
    def matrix(self) -> np.ndarray:
        """The 4x4 homogeneous matrix form."""
        out = np.eye(4, dtype=np.float64)
        out[:3, :3] = self.rotation
        out[:3, 3] = self.translation
        return out

    def inverse(self) -> SE3:
        """The inverse transform. The convention tag flips direction."""
        rotation = self.rotation.T
        return SE3(
            rotation,
            -rotation @ self.translation,
            convention=_FLIPPED[self.convention],
        )

    def as_convention(self, convention: str) -> SE3:
        """Re-express this transform under ``convention`` (flip if needed)."""
        ensure_choice("SE3.as_convention.convention", convention, POSE_CONVENTIONS)
        if convention == self.convention:
            return self
        return self.inverse()

    @classmethod
    def from_colmap_world2cam(
        cls,
        qvec_wxyz: object,
        tvec: object,
        *,
        convention: str = DEFAULT_CONVENTION,
    ) -> SE3:
        """Build from COLMAP's world-to-camera ``(qvec, tvec)`` pose.

        ``qvec_wxyz`` is the unit quaternion ``(w, x, y, z)`` and
        ``tvec`` the translation of the world-to-camera mapping, exactly
        as stored in COLMAP's ``images.txt`` / database. The result is
        re-expressed under ``convention`` (default: cam2world).
        """
        q = _validated_unit_quat("SE3.from_colmap_world2cam.qvec_wxyz", qvec_wxyz)
        t = as_float64("SE3.from_colmap_world2cam.tvec", tvec, (3,))
        world2cam = cls(_quat_wxyz_to_rotation(q), t, convention="opencv_world2cam")
        return world2cam.as_convention(convention)

    def to_colmap_world2cam(self) -> tuple[np.ndarray, np.ndarray]:
        """Return COLMAP's world-to-camera ``(qvec_wxyz, tvec)`` form.

        The quaternion is normalized with ``w >= 0``.
        """
        world2cam = self.as_convention("opencv_world2cam")
        return _rotation_to_quat_wxyz(world2cam.rotation), world2cam.translation.copy()


@dataclass(frozen=True)
class Sim3:
    """A similarity transform: ``x_out = scale * rotation @ x_in + translation``."""

    scale: float
    rotation: np.ndarray  # (3, 3) float64, proper rotation
    translation: np.ndarray  # (3,) float64
    convention: str = DEFAULT_CONVENTION

    def __post_init__(self) -> None:
        if not isinstance(self.scale, int | float) or isinstance(self.scale, bool):
            raise ContractViolation(
                f"Sim3.scale: expected a positive float, got {type(self.scale).__name__}"
            )
        scale = float(self.scale)
        if not math.isfinite(scale) or scale <= 0.0:
            raise ContractViolation(f"Sim3.scale: expected a finite positive float, got {scale!r}")
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "rotation", as_float64("Sim3.rotation", self.rotation, (3, 3)))
        object.__setattr__(
            self, "translation", as_float64("Sim3.translation", self.translation, (3,))
        )
        _validate_rotation("Sim3.rotation", self.rotation)
        ensure_choice("Sim3.convention", self.convention, POSE_CONVENTIONS)

    @classmethod
    def identity(cls, convention: str = DEFAULT_CONVENTION) -> Sim3:
        return cls(1.0, np.eye(3), np.zeros(3), convention=convention)

    @classmethod
    def from_se3(cls, se3: SE3, *, scale: float = 1.0) -> Sim3:
        return cls(scale, se3.rotation, se3.translation, convention=se3.convention)

    @property
    def matrix(self) -> np.ndarray:
        """The 4x4 homogeneous matrix form (rotation block scaled)."""
        out = np.eye(4, dtype=np.float64)
        out[:3, :3] = self.scale * self.rotation
        out[:3, 3] = self.translation
        return out

    def inverse(self) -> Sim3:
        """The inverse transform. The convention tag flips direction."""
        scale = 1.0 / self.scale
        rotation = self.rotation.T
        return Sim3(
            scale,
            rotation,
            -scale * (rotation @ self.translation),
            convention=_FLIPPED[self.convention],
        )
