"""Bounded UsdGeomCamera vocabulary and convention boundary."""

from __future__ import annotations

CAMERA_PRIM_TYPE = "Camera"
CAMERA_PROPERTIES = frozenset(
    {
        "clippingRange",
        "exposure",
        "fStop",
        "focalLength",
        "focusDistance",
        "horizontalAperture",
        "horizontalApertureOffset",
        "projection",
        "shutter:close",
        "shutter:open",
        "stereoRole",
        "verticalAperture",
        "verticalApertureOffset",
    }
)
PROJECTIONS = frozenset({"perspective", "orthographic"})


__all__ = ["CAMERA_PRIM_TYPE", "CAMERA_PROPERTIES", "PROJECTIONS"]
