"""Numpy-native data contracts shared across the SceneAPI family.

The neutral nouns every mapping/matching implementation — classical
(COLMAP-style) or feed-forward (MapAnything-style) — agrees on:
calibration, poses, priors, dense per-pixel outputs, sparse features
and correspondences, tracked point clouds, and the view-level inputs.
Every array-carrying type validates shape/dtype/value on construction
and raises :class:`sceneio.errors.ContractViolation` with a precise
message on violation.

This namespace imports nothing from the SceneAPI family (guard-tested)
and nothing from the sibling :mod:`sceneio.mapping` /
:mod:`sceneio.matching` namespaces — it is the shared floor both
stand on.
"""

from __future__ import annotations

from sceneio.data.calibration import (
    Calibration,
    CameraIntrinsics,
    CameraModel,
    RayMap,
)
from sceneio.data.dense import (
    POINTMAP_FRAMES,
    ConfidenceMap,
    DepthMap,
    Mask,
    Pointmap,
)
from sceneio.data.features import (
    CORRESPONDENCE_MODES,
    CorrespondenceGraph,
    FeatureSet,
    PairCorrespondences,
    TwoViewGeometry,
)
from sceneio.data.pointcloud import TrackedPointCloud, TrackObservation
from sceneio.data.priors import PosePrior
from sceneio.data.transforms import (
    DEFAULT_CONVENTION,
    POSE_CONVENTIONS,
    SE3,
    Sim3,
)
from sceneio.data.views import (
    SCALE_CLASSES,
    SCALE_PROVENANCES,
    FrameMeta,
    ImageRef,
    PosedViewSet,
    ViewInput,
)

__all__ = [
    "CORRESPONDENCE_MODES",
    "DEFAULT_CONVENTION",
    "POINTMAP_FRAMES",
    "POSE_CONVENTIONS",
    "SCALE_CLASSES",
    "SCALE_PROVENANCES",
    "SE3",
    "Calibration",
    "CameraIntrinsics",
    "CameraModel",
    "ConfidenceMap",
    "CorrespondenceGraph",
    "DepthMap",
    "FeatureSet",
    "FrameMeta",
    "ImageRef",
    "Mask",
    "PairCorrespondences",
    "Pointmap",
    "PosePrior",
    "PosedViewSet",
    "RayMap",
    "Sim3",
    "TrackObservation",
    "TrackedPointCloud",
    "TwoViewGeometry",
    "ViewInput",
]
