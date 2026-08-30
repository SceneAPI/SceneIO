"""Private implementations backing SceneIO's root data contracts.

The neutral nouns every mapping/matching implementation — classical
(COLMAP-style) or feed-forward (MapAnything-style) — agrees on:
calibration, poses, priors, dense per-pixel outputs, sparse features
and correspondences, point clouds with optional tracks, and view-level inputs.
Every array-carrying type validates shape/dtype/value on construction
and raises :class:`sceneio.errors.ContractViolation` with a precise
message on violation.

Public identities live at :mod:`sceneio`. This namespace imports nothing from
the SceneAPI family (guard-tested) and nothing from the sibling
:mod:`sceneio.mapping` / :mod:`sceneio.matching` namespaces.
"""

from __future__ import annotations

from sceneio._data.calibration import (
    Calibration,
    CameraModel,
    RayMap,
)
from sceneio._data.dense import (
    POINTMAP_FRAMES,
    ConfidenceMap,
    InstanceMap,
    LabelTaxonomy,
    Mask,
    PanopticMap,
    Pointmap,
    SemanticMap,
)
from sceneio._data.features import (
    CORRESPONDENCE_MODES,
    CorrespondenceGraph,
    PairCorrespondences,
    TwoViewGeometry,
)
from sceneio._data.pointcloud import TrackObservation
from sceneio._data.priors import PosePrior
from sceneio._data.raster import (
    RASTER_AXES,
    RASTER_DTYPES,
    RASTER_PAYLOAD_KINDS,
    RasterCollection,
    RasterLevel,
    RasterSeries,
)
from sceneio._data.transforms import (
    DEFAULT_CONVENTION,
    POSE_CONVENTIONS,
    SE3,
    Sim3,
)
from sceneio._data.views import (
    SCALE_CLASSES,
    SCALE_PROVENANCES,
    FrameMeta,
    ImageRef,
    PosedViewSet,
    ViewInput,
)
from sceneio.coordinates import install_coordinate_properties

install_coordinate_properties(
    Calibration,
    ConfidenceMap,
    CorrespondenceGraph,
    FrameMeta,
    InstanceMap,
    LabelTaxonomy,
    Mask,
    PairCorrespondences,
    PanopticMap,
    Pointmap,
    PosePrior,
    PosedViewSet,
    RayMap,
    SE3,
    Sim3,
    SemanticMap,
    RasterCollection,
    RasterLevel,
    RasterSeries,
    TwoViewGeometry,
    ViewInput,
)

__all__ = [
    "CORRESPONDENCE_MODES",
    "DEFAULT_CONVENTION",
    "POINTMAP_FRAMES",
    "POSE_CONVENTIONS",
    "RASTER_AXES",
    "RASTER_DTYPES",
    "RASTER_PAYLOAD_KINDS",
    "SCALE_CLASSES",
    "SCALE_PROVENANCES",
    "CameraModel",
    "ConfidenceMap",
    "FrameMeta",
    "ImageRef",
    "InstanceMap",
    "LabelTaxonomy",
    "Mask",
    "PanopticMap",
    "Pointmap",
    "PosePrior",
    "PosedViewSet",
    "RasterCollection",
    "RasterLevel",
    "RasterSeries",
    "SemanticMap",
    "TrackObservation",
    "ViewInput",
]
