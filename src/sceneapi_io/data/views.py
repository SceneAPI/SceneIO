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
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from sceneapi_io.data._validation import (
    ensure_choice,
    ensure_instance,
    ensure_optional_instance,
)
from sceneapi_io.data.calibration import Calibration
from sceneapi_io.data.dense import DepthMap, Mask
from sceneapi_io.data.priors import PosePrior
from sceneapi_io.data.transforms import SE3
from sceneapi_io.errors import ContractViolation
from sceneapi_io.imagesource import MaterializedImage

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
    depth_prior: DepthMap | None = None
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
        ensure_optional_instance("ViewInput.depth_prior", self.depth_prior, DepthMap, "DepthMap")
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
    """Views with index-aligned poses in a declared frame."""

    views: tuple[ViewInput, ...]
    poses: tuple[SE3, ...]  # aligned to views
    frame: FrameMeta

    def __post_init__(self) -> None:
        views = _as_typed_tuple("PosedViewSet.views", self.views, ViewInput)
        poses = _as_typed_tuple("PosedViewSet.poses", self.poses, SE3)
        if not views:
            raise ContractViolation("PosedViewSet.views: expected at least one view")
        if len(poses) != len(views):
            raise ContractViolation(
                f"PosedViewSet.poses: expected one pose per view ({len(views)}), got {len(poses)}"
            )
        conventions = {pose.convention for pose in poses}
        if len(conventions) > 1:
            raise ContractViolation(
                f"PosedViewSet.poses: mixed pose conventions {sorted(conventions)}"
            )
        ensure_instance("PosedViewSet.frame", self.frame, FrameMeta, "FrameMeta")
        object.__setattr__(self, "views", views)
        object.__setattr__(self, "poses", poses)

    def __len__(self) -> int:
        return len(self.views)


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
