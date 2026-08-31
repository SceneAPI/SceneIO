"""Bounded USD-family I/O facade."""

from __future__ import annotations

import os

from sceneio.io._inspectors.model import Inspection
from sceneio.io._usd.stage import inspect_scene, read_scene, write_scene


def read_usd(path: str | os.PathLike[str]):
    """Read the bounded USD profile as a SceneGraph."""

    return read_scene(path)


def inspect_usd(
    path: str | os.PathLike[str],
    *,
    format_id: str = "usd",
) -> Inspection:
    """Inspect stage structure and SceneGraph compatibility."""

    return inspect_scene(path, format_id=format_id)


def inspect_usdz(path: str | os.PathLike[str]) -> Inspection:
    """Inspect an aligned USDZ package."""

    return inspect_scene(path, format_id="usdz")


def write_usd(scene, path: str | os.PathLike[str]) -> None:
    """Write the bounded SceneGraph profile as USDA or USDZ."""

    write_scene(scene, path)


def write_usdz(scene, path: str | os.PathLike[str]) -> None:
    """Write the bounded SceneGraph profile as USDZ."""

    write_scene(scene, path, encoding="usdz")


__all__ = [
    "inspect_usd",
    "inspect_usdz",
    "read_scene",
    "read_usd",
    "write_scene",
    "write_usd",
    "write_usdz",
]
