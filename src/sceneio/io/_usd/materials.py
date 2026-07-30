"""Bounded material vocabulary for the USD 3D-CV profile."""

from __future__ import annotations

MATERIAL_PRIM_TYPES = frozenset({"Material", "Shader", "NodeGraph"})
PREVIEW_SURFACE_SHADER_ID = "UsdPreviewSurface"
SUPPORTED_TEXTURE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".exr"})
PREVIEW_SURFACE_INPUTS = frozenset(
    {
        "diffuseColor",
        "emissiveColor",
        "metallic",
        "roughness",
        "clearcoat",
        "clearcoatRoughness",
        "opacity",
        "opacityThreshold",
        "ior",
        "normal",
        "displacement",
        "occlusion",
    }
)


__all__ = [
    "MATERIAL_PRIM_TYPES",
    "PREVIEW_SURFACE_INPUTS",
    "PREVIEW_SURFACE_SHADER_ID",
    "SUPPORTED_TEXTURE_EXTENSIONS",
]
