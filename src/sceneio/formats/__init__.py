"""Disk/wire format-id + DataType-id registries for the SceneAPI family.

The single home for the *identity* of every serialized format the
family exchanges (``registry``) and for the logical DataType vocabulary
those formats serialize (``datatypes``). Wire identity is untouched:
the ids seeded here are the exact strings the sceneapi core's
artifacts/datatypes vocabularies use today (``sfmapi.*.v1`` format ids,
``feature_set``-style DataType ids); the core re-homes its vocabulary
modules onto these registries.
"""

from __future__ import annotations

from sceneio.formats.datatypes import (
    CORE_DATA_TYPES,
    CORE_DATA_TYPES_BY_ID,
    DATA_TYPE_KINDS,
    DataType,
    is_data_type,
)
from sceneio.formats.registry import (
    CORE_FORMAT_IDS,
    CORE_FORMATS,
    FormatSpec,
    get_format,
    is_core_format,
)

__all__ = [
    "CORE_DATA_TYPES",
    "CORE_DATA_TYPES_BY_ID",
    "CORE_FORMATS",
    "CORE_FORMAT_IDS",
    "DATA_TYPE_KINDS",
    "DataType",
    "FormatSpec",
    "get_format",
    "is_core_format",
    "is_data_type",
]
