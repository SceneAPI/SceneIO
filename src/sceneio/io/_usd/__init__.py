"""Bounded USD-family I/O facade."""

from __future__ import annotations

import os

from sceneio.io._inspectors.model import Inspection
from sceneio.io._usd import legacy
from sceneio.io._usd.stage import read_scene, write_scene


def read_usd(path: str | os.PathLike[str]):
    """Read the compatibility static-mesh profile as a MeshScene."""

    return legacy.read_usd(path)


def inspect_usd(
    path: str | os.PathLike[str],
    *,
    format_id: str = "usd",
) -> Inspection:
    """Inspect stage structure and rich-read compatibility."""

    return legacy.inspect_usd(path, format_id=format_id)


def inspect_usdz(path: str | os.PathLike[str]) -> Inspection:
    """Inspect an aligned USDZ package."""

    return legacy.inspect_usdz(path)


def write_usd(scene, path: str | os.PathLike[str]) -> None:
    """Write the compatibility MeshScene profile as USDA or USDZ."""

    legacy.write_usd(scene, path)


def write_usdz(scene, path: str | os.PathLike[str]) -> None:
    """Write the compatibility MeshScene profile as USDZ."""

    legacy.write_usdz(scene, path)


__all__ = [
    "inspect_usd",
    "inspect_usdz",
    "read_scene",
    "read_usd",
    "write_scene",
    "write_usd",
    "write_usdz",
]
