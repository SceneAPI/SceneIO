"""Shared registry value types."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_PARTIAL_SELECTORS = (
    ("read_window", "window"),
    ("read_points", "points"),
    ("read_faces", "faces"),
    ("read_mesh", "mesh_id"),
    ("read_primitive", "primitive_id"),
    ("read_states", "states"),
    ("read_frames", "frames"),
    ("read_image", "image_id"),
    ("read_pair", "pair"),
    ("read_tensors", "tensors"),
    ("read_slices", "slices"),
)


@dataclass(frozen=True)
class Codec:
    """One format's binding into the I/O layer."""

    id: str
    extensions: tuple[str, ...]
    read: Callable[[str], object]
    write: Callable[[object, str], None] | None
    record: type | None
    payload_kind: str
    magic: tuple[bytes, ...] = ()
    filenames: tuple[str, ...] = ()
    is_directory: bool = False
    dir_marker: str = "cameras.bin"
    directory_markers: tuple[str, ...] = ()
    file_probe: Callable[[Path], bool] | None = None
    directory_probe: Callable[[Path], bool] | None = None
    inspect: Callable[[str], object] | None = None
    read_window: Callable[[str, int, int, int, int], object] | None = None
    read_points: Callable[[str, int, int], object] | None = None
    read_faces: Callable[[str, int, int], object] | None = None
    read_mesh: Callable[[str, int], object] | None = None
    read_primitive: Callable[[str, int], object] | None = None
    read_states: Callable[[str, int, int], object] | None = None
    read_frames: Callable[[str, int, int], object] | None = None
    read_image: Callable[[str, int], object] | None = None
    read_pair: Callable[[str, int, int], object] | None = None
    read_tensors: Callable[[str, tuple[str, ...]], object] | None = None
    read_slices: Callable[[str, tuple[tuple[str, int, int], ...]], object] | None = None
    streams_read: bool = True
    streams_write: bool = True
    lossy: bool = False
    requires_features: tuple[str, ...] = ()
    supported_features: tuple[str, ...] = ()
    unsupported_features: tuple[str, ...] = ()
    container_kind: str | None = None

    def __post_init__(self) -> None:
        kind = self.container_kind or ("directory" if self.is_directory else "file")
        if kind not in {"file", "directory", "multi_file"}:
            raise ValueError("container_kind must be 'file', 'directory', or 'multi_file'")
        if self.is_directory and kind not in {"directory", "multi_file"}:
            raise ValueError("is_directory and container_kind disagree")
        if not self.is_directory and kind == "directory":
            raise ValueError("is_directory and container_kind disagree")
        object.__setattr__(self, "container_kind", kind)
        markers = tuple(self.directory_markers)
        if self.is_directory and not markers:
            markers = (self.dir_marker,)
        if any(not isinstance(value, str) or not value for value in markers):
            raise ValueError("directory_markers entries must be non-empty strings")
        object.__setattr__(self, "directory_markers", markers)
        for field_name in (
            "extensions",
            "magic",
            "filenames",
            "requires_features",
            "supported_features",
            "unsupported_features",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        for field_name in (
            "requires_features",
            "supported_features",
            "unsupported_features",
        ):
            values = getattr(self, field_name)
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{field_name} entries must be non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} entries must be unique")
        overlap = set(self.supported_features) & set(self.unsupported_features)
        if overlap:
            raise ValueError(
                "supported_features and unsupported_features overlap: " + ", ".join(sorted(overlap))
            )

    def capabilities(self) -> CodecCapabilities:
        """Return the immutable public capability snapshot for this codec."""

        available = all(
            importlib.util.find_spec(requirement) is not None
            for requirement in self.requires_features
        )
        selectors = tuple(
            selector
            for field_name, selector in _PARTIAL_SELECTORS
            if getattr(self, field_name) is not None
        )
        return CodecCapabilities(
            format=self.id,
            payload_kind=self.payload_kind,
            record_type=self.record.__name__ if self.record is not None else None,
            extensions=self.extensions,
            filenames=self.filenames,
            container_kind=self.container_kind,
            available=available,
            can_read=available,
            can_write=available and self.write is not None,
            can_inspect=available,
            partial_selectors=selectors,
            streams_read=available and self.streams_read,
            streams_write=(available and self.write is not None and self.streams_write),
            lossy=self.lossy,
            requires_features=self.requires_features,
            supported_features=self.supported_features,
            unsupported_features=self.unsupported_features,
        )

@dataclass(frozen=True)
class CodecCapabilities:
    """Stable, immutable discovery metadata for one registered format.

    ``streams_read`` means the public path avoids a whole-file Python
    ``bytes`` allocation through mmap or native directory I/O. ``streams_write``
    means it uses a direct native file sink instead of an output-sized Python
    ``bytes`` object. These flags do not claim that a compression library itself
    is incremental.
    """

    format: str
    payload_kind: str
    record_type: str | None
    extensions: tuple[str, ...]
    filenames: tuple[str, ...]
    container_kind: str
    available: bool
    can_read: bool
    can_write: bool
    can_inspect: bool
    partial_selectors: tuple[str, ...]
    streams_read: bool
    streams_write: bool
    lossy: bool
    requires_features: tuple[str, ...]
    supported_features: tuple[str, ...]
    unsupported_features: tuple[str, ...]

    @property
    def coordinates(self):
        """Coordinate contract for this built-in or extension codec."""

        from sceneio.io._registry.coordinates import codec_coordinate_contract

        return codec_coordinate_contract(self.format)


@dataclass(frozen=True)
class NativeFeatureCapabilities:
    """Build-time state for one optional native integration.

    ``available`` is derived from the feature names exported by the compiled
    extension. Keeping unavailable integrations in this manifest lets callers
    distinguish a known build option from an unknown feature name without
    importing an optional Python package.
    """

    name: str
    build_option: str
    available: bool
    formats: tuple[str, ...]
