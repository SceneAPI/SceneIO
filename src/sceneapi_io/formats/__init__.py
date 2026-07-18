"""Disk/wire format-id registry for the SceneAPI family.

The single home for the *identity* of every serialized format the
family exchanges. Wire identity is untouched: the ids seeded here are
the exact strings the sceneapi core's artifacts vocabulary uses today
(``sfmapi.*.v1``); the core re-homes its format vocabulary onto this
registry in a later migration step.
"""

from __future__ import annotations

from sceneapi_io.formats.registry import (
    CORE_FORMAT_IDS,
    CORE_FORMATS,
    FormatSpec,
    get_format,
    is_core_format,
)

__all__ = [
    "CORE_FORMATS",
    "CORE_FORMAT_IDS",
    "FormatSpec",
    "get_format",
    "is_core_format",
]
