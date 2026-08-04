"""Bounded ASL/EuRoC visual-inertial dataset support."""

from __future__ import annotations

from pathlib import Path

from . import codec as _codec
from .model import VisualInertialDataset

inspect_euroc_dataset = _codec.inspect_euroc_dataset
is_euroc_dataset_directory = _codec.is_euroc_dataset_directory


def read_euroc_dataset(
    path: str | Path,
    *,
    cameras: tuple[str, ...] | list[str] | None = None,
    imus: tuple[str, ...] | list[str] | None = None,
    frame_range: tuple[int, int] | None = None,
    time_range_ns: tuple[int, int] | None = None,
    include_ground_truth: bool = True,
) -> VisualInertialDataset:
    """Read the bounded ASL profile with optional sensor/time selection."""

    from sceneio.io.registry import _IMAGE_FRAME_ACCESS

    return _codec.read_euroc_dataset(
        _IMAGE_FRAME_ACCESS,
        path,
        cameras=cameras,
        imus=imus,
        frame_range=frame_range,
        time_range_ns=time_range_ns,
        include_ground_truth=include_ground_truth,
    )


def write_euroc_dataset(
    dataset: VisualInertialDataset,
    path: str | Path,
) -> None:
    """Write the bounded ASL profile using transactional replacement."""

    from sceneio.io.registry import _IMAGE_FRAME_ACCESS

    _codec.write_euroc_dataset(_IMAGE_FRAME_ACCESS, dataset, path)


__all__ = [
    "VisualInertialDataset",
    "inspect_euroc_dataset",
    "is_euroc_dataset_directory",
    "read_euroc_dataset",
    "write_euroc_dataset",
]
