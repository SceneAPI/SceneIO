"""Lazy reader for NVIDIA's RTMV multi-view directory layout.

The adapter owns the layout and validation logic.  It decodes the small camera
documents into a :class:`PosedViewSet`, while RGB, depth, segmentation, and the
complete object annotations remain available through owned absolute paths.
No pixels are decoded during read or inspection.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio._data.views import PosedViewSet
from sceneio._posed_views import posed_views_from_storage
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._inspectors.model import Inspection

_FRAME_NAME = re.compile(
    r"(?P<frame>\d{5})(?P<layer>\.json|\.depth\.exr|\.seg\.exr|\.exr)"
)
_JSON_LIMIT = 16 * 1024 * 1024
_MAX_FRAMES = 100_000
_MAX_PIXELS = 1 << 32
_MATRIX_ATOL = 2e-4


@dataclass(frozen=True, slots=True)
class RtmvDataset:
    """One validated, path-backed RTMV scene directory.

    ``views`` carries canonical OpenCV camera-to-world poses and per-frame
    pinhole intrinsics. The path tuples keep all encoded layers and original object
    metadata accessible without copying or silently projecting their content
    into a narrower SceneIO record.
    """

    root: str
    views: PosedViewSet
    frame_ids: tuple[str, ...]
    metadata_paths: tuple[str, ...]
    rgb_paths: tuple[str, ...]
    depth_paths: tuple[str, ...]
    segmentation_paths: tuple[str, ...]
    object_counts: tuple[int, ...]
    height: int
    width: int
    rgb_channels: int
    depth_channels: int
    segmentation_channels: int

    def __post_init__(self) -> None:
        if not isinstance(self.root, str) or not Path(self.root).is_absolute():
            raise ValueError("RtmvDataset.root must be an absolute path")
        if not isinstance(self.views, PosedViewSet):
            raise TypeError("RtmvDataset.views must be a PosedViewSet")
        for name in (
            "frame_ids",
            "metadata_paths",
            "rgb_paths",
            "depth_paths",
            "segmentation_paths",
            "object_counts",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        count = len(self.frame_ids)
        if count == 0 or self.views.num_views != count:
            raise ValueError("RtmvDataset requires one view per frame")
        for name in (
            "metadata_paths",
            "rgb_paths",
            "depth_paths",
            "object_counts",
        ):
            if len(getattr(self, name)) != count:
                raise ValueError(f"RtmvDataset.{name} must have one item per frame")
        if len(self.segmentation_paths) not in {0, count}:
            raise ValueError(
                "RtmvDataset.segmentation_paths must be empty or complete"
            )
        for path in (
            *self.metadata_paths,
            *self.rgb_paths,
            *self.depth_paths,
            *self.segmentation_paths,
        ):
            if not isinstance(path, str) or not Path(path).is_absolute():
                raise ValueError("RtmvDataset layer paths must be absolute")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in self.object_counts
        ):
            raise ValueError("RtmvDataset.object_counts must be non-negative integers")
        if self.height <= 0 or self.width <= 0:
            raise ValueError("RtmvDataset dimensions must be positive")
        if self.rgb_channels not in {3, 4}:
            raise ValueError("RtmvDataset.rgb_channels must be 3 or 4")
        if self.depth_channels not in {1, 3, 4}:
            raise ValueError("RtmvDataset.depth_channels must be 1, 3, or 4")
        if self.segmentation_channels not in {0, 1, 3, 4}:
            raise ValueError(
                "RtmvDataset.segmentation_channels must be 0, 1, 3, or 4"
            )

    @property
    def num_frames(self) -> int:
        """Number of views in this selected dataset range."""

        return len(self.frame_ids)

    @property
    def has_segmentation(self) -> bool:
        """Whether every selected frame has a segmentation layer."""

        return bool(self.segmentation_paths)

@dataclass(frozen=True, slots=True)
class _Frame:
    id: str
    metadata: Path
    rgb: Path
    depth: Path
    segmentation: Path | None


@dataclass(frozen=True, slots=True)
class _Camera:
    matrix: np.ndarray
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    object_count: int


def _duplicate_checked_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _discover(path: str | Path) -> tuple[Path, tuple[_Frame, ...]]:
    directory = Path(path)
    if not directory.is_dir():
        raise ValueError("rtmv: path is not a directory")
    layers: dict[str, dict[str, Path]] = {}
    for item in directory.iterdir():
        if item.is_symlink() or not item.is_file():
            raise ValueError(
                f"rtmv: unexpected non-regular entry {item.name!r}"
            )
        match = _FRAME_NAME.fullmatch(item.name)
        if match is None:
            raise ValueError(f"rtmv: unexpected file {item.name!r}")
        frame_id = match.group("frame")
        layer = match.group("layer")
        per_frame = layers.setdefault(frame_id, {})
        if layer in per_frame:
            raise ValueError(f"rtmv: duplicate layer for frame {frame_id}")
        per_frame[layer] = item
    if not layers:
        raise ValueError("rtmv: directory contains no frames")
    if len(layers) > _MAX_FRAMES:
        raise ValueError(f"rtmv: frame count exceeds {_MAX_FRAMES}")
    ids = sorted(layers)
    expected = [f"{index:05d}" for index in range(len(ids))]
    if ids != expected:
        raise ValueError("rtmv: frame ids must be contiguous from 00000")
    segmentation_flags = {".seg.exr" in layers[frame_id] for frame_id in ids}
    if len(segmentation_flags) != 1:
        raise ValueError("rtmv: segmentation must be present for every frame or none")
    has_segmentation = segmentation_flags.pop()
    required = {".json", ".exr", ".depth.exr"}
    if has_segmentation:
        required.add(".seg.exr")
    frames = []
    for frame_id in ids:
        actual = set(layers[frame_id])
        if actual != required:
            missing = ", ".join(sorted(required - actual))
            raise ValueError(
                f"rtmv: frame {frame_id} is missing required layer(s): {missing}"
            )
        layer = layers[frame_id]
        frames.append(
            _Frame(
                id=frame_id,
                metadata=layer[".json"],
                rgb=layer[".exr"],
                depth=layer[".depth.exr"],
                segmentation=layer.get(".seg.exr"),
            )
        )
    return directory.resolve(), tuple(frames)


def _load_document(path: Path) -> dict[str, object]:
    size = path.stat().st_size
    if size > _JSON_LIMIT:
        raise ValueError(f"rtmv: {path.name!r} exceeds the 16 MiB metadata limit")
    with path.open("rb") as stream:
        payload = stream.read(size + 1)
    if len(payload) != size:
        raise ValueError(f"rtmv: {path.name!r} changed while it was being read")
    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_duplicate_checked_object,
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"rtmv: invalid {path.name!r}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"rtmv: {path.name!r} must contain a JSON object")
    return document


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"rtmv: {name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"rtmv: {name} must be finite")
    return result


def _positive_dimension(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"rtmv: {name} must be a positive integer")
    return value


def _vector(value: object, length: int, name: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"rtmv: {name} must contain {length} numbers")
    return np.asarray(
        [_finite_number(item, f"{name}[{index}]") for index, item in enumerate(value)],
        dtype=np.float64,
    )


def _matrix(value: object, name: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"rtmv: {name} must be a 4x4 matrix")
    rows = [_vector(row, 4, f"{name}[{index}]") for index, row in enumerate(value)]
    return np.ascontiguousarray(np.stack(rows).T)


def _quaternion_matrix(xyzw: np.ndarray) -> np.ndarray:
    x, y, z, w = xyzw
    return np.asarray(
        [
            [
                1.0 - 2.0 * (y * y + z * z),
                2.0 * (x * y - w * z),
                2.0 * (x * z + w * y),
            ],
            [
                2.0 * (x * y + w * z),
                1.0 - 2.0 * (x * x + z * z),
                2.0 * (y * z - w * x),
            ],
            [
                2.0 * (x * z - w * y),
                2.0 * (y * z + w * x),
                1.0 - 2.0 * (x * x + y * y),
            ],
        ],
        dtype=np.float64,
    )


def _parse_camera(document: dict[str, object], name: str) -> _Camera:
    camera = document.get("camera_data")
    objects = document.get("objects")
    if not isinstance(camera, dict):
        raise ValueError(f"rtmv: {name} is missing camera_data")
    if not isinstance(objects, list) or any(not isinstance(item, dict) for item in objects):
        raise ValueError(f"rtmv: {name} objects must be an array of objects")

    width = _positive_dimension(camera.get("width"), f"{name} width")
    height = _positive_dimension(camera.get("height"), f"{name} height")
    if width * height > _MAX_PIXELS:
        raise ValueError(f"rtmv: {name} dimensions exceed the pixel limit")
    intrinsics = camera.get("intrinsics")
    if not isinstance(intrinsics, dict):
        raise ValueError(f"rtmv: {name} is missing intrinsics")
    fx = _finite_number(intrinsics.get("fx"), f"{name} intrinsics.fx")
    fy = _finite_number(intrinsics.get("fy"), f"{name} intrinsics.fy")
    cx = _finite_number(intrinsics.get("cx"), f"{name} intrinsics.cx")
    cy = _finite_number(intrinsics.get("cy"), f"{name} intrinsics.cy")
    if fx <= 0.0 or fy <= 0.0:
        raise ValueError(f"rtmv: {name} focal lengths must be positive")
    if not (0.0 <= cx <= width and 0.0 <= cy <= height):
        raise ValueError(f"rtmv: {name} principal point is outside the image")

    c2w = _matrix(camera.get("cam2world"), f"{name} cam2world")
    view = _matrix(camera.get("camera_view_matrix"), f"{name} camera_view_matrix")
    if not np.allclose(c2w[3], (0.0, 0.0, 0.0, 1.0), atol=_MATRIX_ATOL, rtol=0.0):
        raise ValueError(f"rtmv: {name} cam2world is not affine")
    if not np.allclose(view[3], (0.0, 0.0, 0.0, 1.0), atol=_MATRIX_ATOL, rtol=0.0):
        raise ValueError(f"rtmv: {name} camera_view_matrix is not affine")
    rotation = c2w[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=_MATRIX_ATOL, rtol=0.0):
        raise ValueError(f"rtmv: {name} cam2world rotation is not orthonormal")
    if not math.isclose(float(np.linalg.det(rotation)), 1.0, abs_tol=_MATRIX_ATOL):
        raise ValueError(f"rtmv: {name} cam2world rotation is reflected")
    if not np.allclose(view @ c2w, np.eye(4), atol=_MATRIX_ATOL, rtol=0.0):
        raise ValueError(f"rtmv: {name} camera matrices are not inverses")

    location = _vector(camera.get("location_world"), 3, f"{name} location_world")
    look_at = camera.get("camera_look_at")
    if not isinstance(look_at, dict):
        raise ValueError(f"rtmv: {name} is missing camera_look_at")
    eye = _vector(look_at.get("eye"), 3, f"{name} camera_look_at.eye")
    target = _vector(look_at.get("at"), 3, f"{name} camera_look_at.at")
    up = _vector(look_at.get("up"), 3, f"{name} camera_look_at.up")
    forward = target - eye
    forward_norm = float(np.linalg.norm(forward))
    up_norm = float(np.linalg.norm(up))
    if forward_norm <= 1e-12 or up_norm <= 1e-12:
        raise ValueError(f"rtmv: {name} camera_look_at vectors are degenerate")
    if not np.allclose(location, c2w[:3, 3], atol=_MATRIX_ATOL, rtol=0.0):
        raise ValueError(f"rtmv: {name} location_world disagrees with cam2world")
    if not np.allclose(eye, location, atol=_MATRIX_ATOL, rtol=0.0):
        raise ValueError(f"rtmv: {name} camera eye disagrees with location_world")
    if not np.allclose(
        forward / forward_norm,
        -rotation[:, 2],
        atol=_MATRIX_ATOL,
        rtol=0.0,
    ):
        raise ValueError(f"rtmv: {name} camera look direction disagrees with cam2world")
    if not np.allclose(
        up / up_norm,
        rotation[:, 1],
        atol=_MATRIX_ATOL,
        rtol=0.0,
    ):
        raise ValueError(f"rtmv: {name} camera up direction disagrees with cam2world")

    quaternion = _vector(
        camera.get("quaternion_world_xyzw"),
        4,
        f"{name} quaternion_world_xyzw",
    )
    if not math.isclose(float(np.linalg.norm(quaternion)), 1.0, abs_tol=_MATRIX_ATOL):
        raise ValueError(f"rtmv: {name} quaternion is not normalized")
    if not np.allclose(
        _quaternion_matrix(quaternion),
        rotation,
        atol=_MATRIX_ATOL,
        rtol=0.0,
    ):
        raise ValueError(f"rtmv: {name} quaternion disagrees with cam2world")

    bounds = []
    for field in (
        "scene_min_3d_box",
        "scene_center_3d_box",
        "scene_max_3d_box",
    ):
        bounds.append(_vector(camera.get(field), 3, f"{name} {field}"))
    minimum, center, maximum = bounds
    if np.any(minimum > maximum) or np.any(center < minimum) or np.any(center > maximum):
        raise ValueError(f"rtmv: {name} scene bounds are inconsistent")
    return _Camera(c2w, width, height, fx, fy, cx, cy, len(objects))


def _frame_shape(
    frame_access: ImageFrameAccess,
    path: Path,
    frame_name: str,
    layer: str,
) -> tuple[int, int, int, str]:
    info = frame_access.inspect(path)
    if not isinstance(info, Inspection):
        raise TypeError(
            f"rtmv: frame inspector returned {type(info).__name__}, expected Inspection"
        )
    if info.shape is None or info.channels is None or info.dtype is None:
        raise ValueError(f"rtmv: {frame_name} {layer} is not an image")
    return info.shape[0], info.shape[1], info.channels, info.dtype


def _select(
    frames: tuple[_Frame, ...],
    start: int | None,
    stop: int | None,
) -> tuple[_Frame, ...]:
    if start is None:
        return frames
    if start < 0 or stop is None or start >= stop or stop > len(frames):
        raise ValueError("rtmv: frame range is out of bounds")
    return frames[start:stop]


def _scan(
    frame_access: ImageFrameAccess,
    path: str | Path,
    start: int | None = None,
    stop: int | None = None,
) -> tuple[Path, tuple[_Frame, ...], tuple[_Camera, ...], tuple[int, int, int, int, int]]:
    root, discovered = _discover(path)
    frames = _select(discovered, start, stop)
    cameras = []
    expected: tuple[int, int, int, int, int] | None = None
    for frame in frames:
        camera = _parse_camera(_load_document(frame.metadata), frame.metadata.name)
        rgb = _frame_shape(frame_access, frame.rgb, frame.metadata.name, "RGB")
        depth = _frame_shape(frame_access, frame.depth, frame.metadata.name, "depth")
        segmentation = (
            _frame_shape(
                frame_access,
                frame.segmentation,
                frame.metadata.name,
                "segmentation",
            )
            if frame.segmentation is not None
            else None
        )
        if rgb[:2] != (camera.height, camera.width) or depth[:2] != rgb[:2]:
            raise ValueError(f"rtmv: {frame.id} layer dimensions disagree")
        if segmentation is not None and segmentation[:2] != rgb[:2]:
            raise ValueError(f"rtmv: {frame.id} segmentation dimensions disagree")
        if rgb[2] not in {3, 4} or rgb[3] != "float32":
            raise ValueError("rtmv: RGB layers require FLOAT/HALF RGB or RGBA EXR")
        if depth[2] not in {1, 3, 4} or depth[3] != "float32":
            raise ValueError("rtmv: depth layers require FLOAT/HALF EXR")
        if segmentation is not None and (
            segmentation[2] not in {1, 3, 4} or segmentation[3] != "float32"
        ):
            raise ValueError("rtmv: segmentation layers require FLOAT/HALF EXR")
        current = (
            camera.height,
            camera.width,
            rgb[2],
            depth[2],
            0 if segmentation is None else segmentation[2],
        )
        if expected is None:
            expected = current
        elif current != expected:
            raise ValueError("rtmv: heterogeneous frame layers are unsupported")
        cameras.append(camera)
    assert expected is not None
    return root, frames, tuple(cameras), expected


def _build_views(frames: tuple[_Frame, ...], cameras: tuple[_Camera, ...]):
    document = {
        "frames": [
            {
                "camera_model": "PINHOLE",
                "fl_x": camera.fx,
                "fl_y": camera.fy,
                "cx": camera.cx,
                "cy": camera.cy,
                "w": camera.width,
                "h": camera.height,
                "file_path": str(frame.rgb.resolve()),
                "transform_matrix": camera.matrix.tolist(),
            }
            for frame, camera in zip(frames, cameras, strict=True)
        ]
    }
    payload = json.dumps(document, separators=(",", ":"), allow_nan=False).encode()
    return posed_views_from_storage(
        _core.read_transforms_json(payload),
        source_profile="transforms_json",
    )


def _dataset(
    root: Path,
    frames: tuple[_Frame, ...],
    cameras: tuple[_Camera, ...],
    shape: tuple[int, int, int, int, int],
) -> RtmvDataset:
    height, width, rgb_channels, depth_channels, segmentation_channels = shape
    return RtmvDataset(
        root=str(root),
        views=_build_views(frames, cameras),
        frame_ids=tuple(frame.id for frame in frames),
        metadata_paths=tuple(str(frame.metadata.resolve()) for frame in frames),
        rgb_paths=tuple(str(frame.rgb.resolve()) for frame in frames),
        depth_paths=tuple(str(frame.depth.resolve()) for frame in frames),
        segmentation_paths=tuple(
            str(frame.segmentation.resolve())
            for frame in frames
            if frame.segmentation is not None
        ),
        object_counts=tuple(camera.object_count for camera in cameras),
        height=height,
        width=width,
        rgb_channels=rgb_channels,
        depth_channels=depth_channels,
        segmentation_channels=segmentation_channels,
    )


def read_rtmv_directory(frame_access: ImageFrameAccess, path: str) -> RtmvDataset:
    """Read one RTMV directory without decoding its EXR payloads."""

    return _dataset(*_scan(frame_access, path))


def read_rtmv_directory_frames(
    frame_access: ImageFrameAccess,
    path: str,
    start: int,
    stop: int,
) -> RtmvDataset:
    """Read a contiguous RTMV view range without visiting other frame payloads."""

    return _dataset(*_scan(frame_access, path, start, stop))


def inspect_rtmv_directory(frame_access: ImageFrameAccess, path: str) -> Inspection:
    """Inspect RTMV camera documents and EXR headers without pixel decode."""

    root, frames, cameras, shape = _scan(frame_access, path)
    height, width, rgb_channels, depth_channels, segmentation_channels = shape
    byte_size = sum(item.stat().st_size for item in root.iterdir() if item.is_file())
    return Inspection(
        format="rtmv",
        payload_kind="rtmv_dataset",
        byte_size=byte_size,
        shape=(len(frames), height, width, rgb_channels),
        dtype="float32",
        count=len(frames),
        channels=rgb_channels,
        metadata={
            "storage_mode": "encoded_paths",
            "pose_convention": "camera_to_world",
            "axis_frame": "opengl",
            "depth_channels": depth_channels,
            "segmentation_channels": segmentation_channels,
            "has_segmentation": bool(segmentation_channels),
            "frame_ids": tuple(frame.id for frame in frames),
            "object_counts": tuple(camera.object_count for camera in cameras),
        },
    )


__all__ = [
    "RtmvDataset",
    "inspect_rtmv_directory",
    "read_rtmv_directory",
    "read_rtmv_directory_frames",
]
