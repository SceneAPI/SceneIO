"""Qualified TinyUSDZ provider boundary."""

from __future__ import annotations

import os

from sceneio.io._usd.package import root_layer_prefix, validate_usdz_input

USDC_MAGIC = b"PXR-USDC\x00"
TINYUSDZ_MAX_QUALIFIED_CRATE_VERSION = 10


def require_tinyusdz():
    """Import the optional provider or report the installation extra."""

    try:
        import tinyusdz
    except ModuleNotFoundError:
        raise RuntimeError(
            "USD/USDZ support requires the optional dependency; "
            "install sceneio[usd]"
        ) from None
    return tinyusdz


def require_qualified_input(path: str | os.PathLike[str]) -> None:
    """Refuse USDC versions outside the locally qualified provider range."""

    validate_usdz_input(path)
    prefix = root_layer_prefix(path)
    if not prefix.startswith(USDC_MAGIC) or len(prefix) < 10:
        return
    version = prefix[9]
    if version > TINYUSDZ_MAX_QUALIFIED_CRATE_VERSION:
        raise ValueError(
            f"USD: USDC crate version {version} exceeds TinyUSDZ 0.9.4's "
            "qualified maximum version 10"
        )


def load_stage(path: str | os.PathLike[str]):
    """Load a stage after applying the qualified-input boundary."""

    require_qualified_input(path)
    tinyusdz = require_tinyusdz()
    try:
        return tinyusdz.load(os.fspath(path))
    except Exception as exc:
        raise ValueError(f"USD: provider could not load the stage: {exc}") from exc


def source_representation(path: str | os.PathLike[str]) -> str:
    """Classify a loaded path into the SceneGraph representation vocabulary."""

    prefix = root_layer_prefix(path)
    with open(path, "rb") as source:
        container_prefix = source.read(4)
    if container_prefix.startswith(b"PK\x03\x04"):
        return "usdz"
    if prefix.startswith(USDC_MAGIC):
        return "usdc"
    return "usda"


__all__ = [
    "TINYUSDZ_MAX_QUALIFIED_CRATE_VERSION",
    "USDC_MAGIC",
    "load_stage",
    "require_qualified_input",
    "require_tinyusdz",
    "source_representation",
]
