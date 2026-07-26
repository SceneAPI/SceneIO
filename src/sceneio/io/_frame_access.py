"""Lower-level dependencies injected into encoded-frame sequence adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ImageFrameAccess:
    """Live image-container catalog and metadata-inspection contract."""

    extensions: Callable[[], frozenset[str]]
    inspect: Callable[[Path], object]

    def __post_init__(self) -> None:
        if not callable(self.extensions):
            raise TypeError("image frame extension catalog must be callable")
        if not callable(self.inspect):
            raise TypeError("image frame inspector must be callable")
        self.image_extensions()

    def image_extensions(self) -> frozenset[str]:
        return frozenset(value.lower() for value in self.extensions())
