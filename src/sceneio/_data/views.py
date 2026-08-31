"""View-level input contracts: ViewInput, PosedViewSet, FrameMeta.

``ViewInput`` is the neutral per-view input floor shared by classical
and feed-forward mappers: an image (a :class:`MaterializedImage`
reference from the existing imagesource contract, or an in-memory uint8
array) plus optional calibration, pose prior, depth prior, and mask —
priors are always optional; a backend's traits declare what it consumes.

``FrameMeta`` declares the output frame: which view anchors the world
frame, the scale class (``arbitrary | normalized | metric``), and where
that scale claim comes from (``model_claimed | prior_anchored |
unknown``).

``PosedViewSet`` is the canonical in-memory pose collection. Its poses are
always OpenCV camera-to-world transforms; source quaternion order, camera
axes, and pose direction remain private codec-boundary concerns.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from numbers import Real
from typing import Literal

import numpy as np

from sceneio import _core
from sceneio._data._validation import (
    ensure_choice,
    ensure_instance,
    ensure_optional_instance,
)
from sceneio._data.calibration import Calibration
from sceneio._data.dense import Mask
from sceneio._data.priors import PosePrior
from sceneio._data.transforms import SE3
from sceneio.errors import ContractViolation
from sceneio.imagesource import MaterializedImage

# An image reference: the persisted-source form (existing imagesource
# contract) or an in-memory uint8 array — (H, W, 3) RGB or (H, W) gray.
ImageRef = MaterializedImage | np.ndarray

SCALE_CLASSES: frozenset[str] = frozenset({"arbitrary", "normalized", "metric"})

SCALE_PROVENANCES: frozenset[str] = frozenset({"model_claimed", "prior_anchored", "unknown"})


@dataclass(frozen=True)
class FrameMeta:
    """The output-frame declaration of a mapped result.

    ``world_frame="first_view"`` means the world frame is anchored at
    the first view's camera (the learned-family convention). ``scale``
    declares the scale class, ``scale_provenance`` where the claim
    comes from — a model's own say-so (``model_claimed``) is not the
    same evidence as a metric prior anchor (``prior_anchored``).
    """

    world_frame: str = "first_view"
    scale: Literal["arbitrary", "normalized", "metric"] = "arbitrary"
    scale_provenance: Literal["model_claimed", "prior_anchored", "unknown"] = "unknown"

    def __post_init__(self) -> None:
        if not isinstance(self.world_frame, str) or not self.world_frame:
            raise ContractViolation(
                f"FrameMeta.world_frame: expected a non-empty str, got {self.world_frame!r}"
            )
        ensure_choice("FrameMeta.scale", self.scale, SCALE_CLASSES)
        ensure_choice("FrameMeta.scale_provenance", self.scale_provenance, SCALE_PROVENANCES)


def _validate_image_ref(name: str, image: object) -> tuple[int, int] | None:
    """Validate an ImageRef; return (H, W) when knowable (in-memory)."""
    if isinstance(image, MaterializedImage):
        return None
    if isinstance(image, np.ndarray):
        if image.dtype != np.uint8:
            raise ContractViolation(
                f"{name}: in-memory images must be uint8, got {image.dtype.name}"
            )
        if not (image.ndim == 2 or (image.ndim == 3 and image.shape[2] == 3)):
            raise ContractViolation(
                f"{name}: in-memory images must be (H, W) gray or (H, W, 3) RGB, "
                f"got shape {image.shape}"
            )
        if image.shape[0] < 1 or image.shape[1] < 1:
            raise ContractViolation(
                f"{name}: image dimensions must be >= 1, got shape {image.shape}"
            )
        return (int(image.shape[0]), int(image.shape[1]))
    raise ContractViolation(
        f"{name}: expected MaterializedImage or an in-memory uint8 ndarray, "
        f"got {type(image).__name__}"
    )


@dataclass(frozen=True)
class ViewInput:
    """One view's inputs: an image plus optional calibration and priors.

    Every resolution-bearing component (in-memory image, calibration,
    depth prior, mask) must agree on one (H, W); a mismatch raises
    :class:`ContractViolation` at construction.
    """

    image: ImageRef
    name: str | None = None
    calibration: Calibration | None = None
    pose_prior: PosePrior | None = None
    depth_prior: _core.DepthMap | None = None
    mask: Mask | None = None

    def __post_init__(self) -> None:
        image_size = _validate_image_ref("ViewInput.image", self.image)
        if self.name is not None and (not isinstance(self.name, str) or not self.name):
            raise ContractViolation(
                f"ViewInput.name: expected a non-empty str or None, got {self.name!r}"
            )
        ensure_optional_instance(
            "ViewInput.calibration", self.calibration, Calibration, "Calibration"
        )
        ensure_optional_instance("ViewInput.pose_prior", self.pose_prior, PosePrior, "PosePrior")
        ensure_optional_instance(
            "ViewInput.depth_prior", self.depth_prior, _core.DepthMap, "DepthMap"
        )
        ensure_optional_instance("ViewInput.mask", self.mask, Mask, "Mask")

        sizes: list[tuple[str, tuple[int, int]]] = []
        if image_size is not None:
            sizes.append(("image", image_size))
        if self.calibration is not None:
            sizes.append(("calibration", self.calibration.image_size))
        if self.depth_prior is not None:
            sizes.append(("depth_prior", self.depth_prior.shape))
        if self.mask is not None:
            sizes.append(("mask", self.mask.shape))
        if sizes:
            ref_name, ref_size = sizes[0]
            for other_name, other_size in sizes[1:]:
                if other_size != ref_size:
                    raise ContractViolation(
                        f"ViewInput: resolution mismatch — {ref_name} is "
                        f"(H, W) = {ref_size} but {other_name} is {other_size}"
                    )

    @property
    def ref(self) -> str | None:
        """A stable display id: ``name`` or the materialized image's name."""
        if self.name is not None:
            return self.name
        if isinstance(self.image, MaterializedImage):
            return self.image.name
        return None


@dataclass(frozen=True)
class PosedViewSet:
    """Canonical posed views with index-aligned optional metadata.

    Every pose uses ``opencv_cam2world``. Optional fields are normalized to
    tuples of length ``N`` containing ``None`` for missing values. Empty pose
    sets are valid because supported trajectory formats can encode them.
    """

    poses: tuple[SE3, ...]
    frame: FrameMeta
    names: tuple[str | None, ...] = ()
    timestamps: tuple[float | None, ...] = ()
    images: tuple[ImageRef | None, ...] = ()
    calibrations: tuple[Calibration | None, ...] = ()
    _source_storage: object | None = field(default=None, init=False, repr=False, compare=False)
    _source_profile: str | None = field(default=None, init=False, repr=False, compare=False)
    _source_signature: object | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        poses = _as_typed_tuple("PosedViewSet.poses", self.poses, SE3)
        ensure_instance("PosedViewSet.frame", self.frame, FrameMeta, "FrameMeta")
        for index, pose in enumerate(poses):
            if pose.convention != "opencv_cam2world":
                raise ContractViolation(
                    f"PosedViewSet.poses[{index}]: expected convention "
                    f"'opencv_cam2world', got {pose.convention!r}"
                )
        count = len(poses)
        names = _as_optional_tuple("PosedViewSet.names", self.names, count)
        for index, name in enumerate(names):
            if name is not None and (not isinstance(name, str) or not name):
                raise ContractViolation(
                    f"PosedViewSet.names[{index}]: expected a non-empty str or None, "
                    f"got {name!r}"
                )
        timestamps = _as_optional_tuple("PosedViewSet.timestamps", self.timestamps, count)
        normalized_timestamps: list[float | None] = []
        for index, timestamp in enumerate(timestamps):
            if timestamp is None:
                normalized_timestamps.append(None)
                continue
            if isinstance(timestamp, bool) or not isinstance(timestamp, Real):
                raise ContractViolation(
                    f"PosedViewSet.timestamps[{index}]: expected a finite number or None, "
                    f"got {type(timestamp).__name__}"
                )
            value = float(timestamp)
            if not math.isfinite(value):
                raise ContractViolation(
                    f"PosedViewSet.timestamps[{index}]: expected a finite number or None, "
                    f"got {value!r}"
                )
            normalized_timestamps.append(value)
        images = _as_optional_tuple("PosedViewSet.images", self.images, count)
        for index, image in enumerate(images):
            if image is not None:
                _validate_image_ref(f"PosedViewSet.images[{index}]", image)
        calibrations = _as_optional_tuple(
            "PosedViewSet.calibrations", self.calibrations, count
        )
        for index, calibration in enumerate(calibrations):
            if calibration is not None and not isinstance(calibration, Calibration):
                raise ContractViolation(
                    f"PosedViewSet.calibrations[{index}]: expected Calibration or None, "
                    f"got {type(calibration).__name__}"
                )
        object.__setattr__(self, "poses", poses)
        object.__setattr__(self, "names", names)
        object.__setattr__(self, "timestamps", tuple(normalized_timestamps))
        object.__setattr__(self, "images", images)
        object.__setattr__(self, "calibrations", calibrations)

    @property
    def num_views(self) -> int:
        """Number of aligned poses/views."""

        return len(self.poses)

    def __len__(self) -> int:
        return len(self.poses)


def _as_optional_tuple(name: str, value: object, count: int) -> tuple:
    if isinstance(value, tuple) and not value:
        return (None,) * count
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ContractViolation(
            f"{name}: expected a sequence with one item per pose, "
            f"got {type(value).__name__}"
        )
    result = tuple(value)
    if len(result) != count:
        raise ContractViolation(
            f"{name}: expected one item per pose ({count}), got {len(result)}"
        )
    return result


def _as_typed_tuple(name: str, value: object, expected: type) -> tuple:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ContractViolation(
            f"{name}: expected a sequence of {expected.__name__}, got {type(value).__name__}"
        )
    for index, item in enumerate(value):
        if not isinstance(item, expected):
            raise ContractViolation(
                f"{name}[{index}]: expected {expected.__name__}, got {type(item).__name__}"
            )
    return tuple(value)
