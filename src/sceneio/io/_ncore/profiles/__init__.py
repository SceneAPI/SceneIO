"""Routing for repository-owned NCore V4 semantic component profiles."""

from __future__ import annotations

from collections.abc import Callable

from sceneio.io._ncore.model import (
    NCoreComponentData,
    NCoreItem,
    NCoreSemanticComponent,
)
from sceneio.io._ncore.profiles.calibration import (
    read_intrinsics_profile,
    read_masks_profile,
    read_poses_profile,
)
from sceneio.io._ncore.profiles.scene import (
    read_camera_labels_profile,
    read_cuboids_profile,
    read_point_clouds_profile,
)
from sceneio.io._ncore.profiles.sensors import (
    read_camera_profile,
    read_lidar_profile,
    read_radar_profile,
)

_ProfileReader = Callable[
    [NCoreComponentData, tuple[int, int]], NCoreSemanticComponent
]


def _intrinsics(
    data: NCoreComponentData, _interval: tuple[int, int]
) -> NCoreSemanticComponent:
    return read_intrinsics_profile(data)


def _masks(
    data: NCoreComponentData, _interval: tuple[int, int]
) -> NCoreSemanticComponent:
    return read_masks_profile(data)


_READERS: dict[str, _ProfileReader] = {
    "cameras": read_camera_profile,
    "camera_labels": read_camera_labels_profile,
    "cuboids": read_cuboids_profile,
    "intrinsics": _intrinsics,
    "lidars": read_lidar_profile,
    "masks": _masks,
    "poses": read_poses_profile,
    "point_clouds": read_point_clouds_profile,
    "radars": read_radar_profile,
}


def interpret_ncore_component(
    data: NCoreComponentData,
    sequence_interval_us: tuple[int, int],
) -> NCoreSemanticComponent:
    """Validate one standard profile or retain an unknown profile generically."""

    reader = _READERS.get(data.component.name)
    if reader is not None:
        return reader(data, sequence_interval_us)
    group_attributes = {
        group.name: dict(group.attributes) for group in data.groups
    }
    return NCoreSemanticComponent(
        raw=data,
        profile=f"generic/{data.component.version}",
        items=(
            NCoreItem(
                kind="generic_component",
                id=data.component.id,
                arrays=data.arrays,
                attributes={"groups": group_attributes},
            ),
        ),
    )


__all__ = ["interpret_ncore_component"]
