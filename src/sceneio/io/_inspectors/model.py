"""Shared metadata-inspection value types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

type MetadataScalar = str | int | float | bool | None
type MetadataValue = (
    MetadataScalar
    | tuple[MetadataValue, ...]
    | Mapping[str, MetadataValue]
)


def _freeze_metadata(value):
    """Recursively detach inspection metadata from caller-owned containers."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_metadata(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_metadata(item) for item in value)
    return value


@dataclass(frozen=True)
class ArrayInspection:
    """The name, shape, and dtype of one array in a multi-array container."""

    name: str
    shape: tuple[int, ...]
    dtype: str


@dataclass(frozen=True)
class Inspection:
    """Metadata available without decoding a format's bulk payload.

    ``shape`` describes the primary decoded array when a format has one.
    ``count`` is the primary repeated-record count for point, Gaussian, pose,
    reconstruction, and tensor-container formats. Image formats use ``shape``
    and ``channels`` instead. Format-specific scalar metadata is exposed through
    the read-only ``metadata`` mapping.
    """

    format: str
    datatype: str
    byte_size: int
    shape: tuple[int, ...] | None = None
    dtype: str | None = None
    count: int | None = None
    channels: int | None = None
    arrays: tuple[ArrayInspection, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.shape is not None:
            object.__setattr__(self, "shape", tuple(self.shape))
        object.__setattr__(self, "arrays", tuple(self.arrays))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def coordinates(self):
        """Coordinate convention determinable without bulk decoding."""

        from sceneio.coordinates import inspection_coordinate_convention

        return inspection_coordinate_convention(self.format, self.metadata)


# These public value types historically lived in the compatibility facade.
# Retaining that module identity preserves repr and existing pickle payloads.
ArrayInspection.__module__ = "sceneio.io._inspection"
Inspection.__module__ = "sceneio.io._inspection"
