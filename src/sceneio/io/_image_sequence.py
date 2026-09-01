"""Canonical lazy/packed image-folder adapter for :class:`ImageSequence`.

Folder membership is semantic: extensions discover candidates, but every file
must resolve through the live registry to a single-frame ``Image`` payload.
The directory tier keeps encoded paths lazy, validates frame headers, and uses
a strict manifest for timing and metadata that image files cannot carry.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._inspectors.model import Inspection

_MARKER = "sceneio_sequence.json"
_MANIFEST_VERSION = 2
_MANIFEST_LIMIT = 1024 * 1024
_COPY_CHUNK = 1024 * 1024
_NATURAL_PART = re.compile(r"(\d+)")
_DTYPES = frozenset({"uint8", "uint16", "float32"})
_COLOR_SPACES = frozenset({"srgb", "linear", "gray", "unknown"})
_ALPHA_MODES = frozenset({"none", "straight", "premultiplied"})
_PROJECTIONS = frozenset({"unknown", "equirectangular"})
_FRAME_CONTRACT_FIELDS = frozenset(
    {
        "height",
        "width",
        "channels",
        "dtype",
        "color_space",
        "alpha_mode",
        "maxval",
        "projection",
        "projection_canvas_width",
        "projection_canvas_height",
        "projection_crop_left",
        "projection_crop_top",
    }
)


def _natural_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    folded = path.name.casefold()
    parts = _NATURAL_PART.split(folded)
    segments = tuple((1, int(part)) if part.isdigit() else (0, part) for part in parts if part)
    return (*segments, (2, folded), (3, path.name))


def _image_extensions(frame_access: ImageFrameAccess) -> frozenset[str]:
    return frame_access.image_extensions()


def _strict_integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"image sequence: {name} must be an integer >= {minimum}")
    return value


def _strict_text(value: object, name: str, vocabulary: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in vocabulary:
        raise ValueError(f"image sequence: {name} must be one of {'|'.join(sorted(vocabulary))}")
    return value


@dataclass(frozen=True, slots=True)
class _FrameContract:
    height: int
    width: int
    channels: int
    dtype: str
    color_space: str
    alpha_mode: str
    maxval: int
    projection: str
    projection_canvas_width: int
    projection_canvas_height: int
    projection_crop_left: int
    projection_crop_top: int

    def __post_init__(self) -> None:
        if self.height < 1 or self.width < 1:
            raise ValueError("image sequence: frame dimensions must be positive")
        if self.channels not in {1, 3, 4}:
            raise ValueError("image sequence: frame channels must be 1, 3, or 4")
        if self.dtype not in _DTYPES:
            raise ValueError("image sequence: unsupported frame dtype")
        if self.color_space not in _COLOR_SPACES:
            raise ValueError("image sequence: unsupported frame color_space")
        if self.alpha_mode not in _ALPHA_MODES:
            raise ValueError("image sequence: unsupported frame alpha_mode")
        if (self.alpha_mode == "none") != (self.channels != 4):
            raise ValueError("image sequence: frame alpha mode and channels disagree")
        if (
            (self.dtype == "uint8" and not 1 <= self.maxval <= 255)
            or (self.dtype == "uint16" and not 1 <= self.maxval <= 65535)
            or (self.dtype == "float32" and self.maxval != 0)
        ):
            raise ValueError("image sequence: frame maxval and dtype disagree")
        if self.projection not in _PROJECTIONS:
            raise ValueError("image sequence: unsupported frame projection")
        geometry = (
            self.projection_canvas_width,
            self.projection_canvas_height,
            self.projection_crop_left,
            self.projection_crop_top,
        )
        if self.projection == "unknown":
            if any(geometry):
                raise ValueError(
                    "image sequence: unknown projection cannot carry canvas/crop geometry"
                )
            return
        canvas_width, canvas_height, left, top = geometry
        if canvas_width < 1 or canvas_height < 1:
            raise ValueError("image sequence: equirectangular canvas dimensions must be positive")
        if (
            left > canvas_width
            or self.width > canvas_width - left
            or top > canvas_height
            or self.height > canvas_height - top
        ):
            raise ValueError("image sequence: frame crop exceeds the equirectangular canvas")

    @classmethod
    def from_manifest(cls, value: object) -> _FrameContract:
        if not isinstance(value, dict) or set(value) != _FRAME_CONTRACT_FIELDS:
            raise ValueError("image sequence: manifest frame_contract has unsupported fields")
        return cls(
            height=_strict_integer(value["height"], "frame_contract.height", minimum=1),
            width=_strict_integer(value["width"], "frame_contract.width", minimum=1),
            channels=_strict_integer(value["channels"], "frame_contract.channels", minimum=1),
            dtype=_strict_text(value["dtype"], "frame_contract.dtype", _DTYPES),
            color_space=_strict_text(
                value["color_space"], "frame_contract.color_space", _COLOR_SPACES
            ),
            alpha_mode=_strict_text(value["alpha_mode"], "frame_contract.alpha_mode", _ALPHA_MODES),
            maxval=_strict_integer(value["maxval"], "frame_contract.maxval"),
            projection=_strict_text(value["projection"], "frame_contract.projection", _PROJECTIONS),
            projection_canvas_width=_strict_integer(
                value["projection_canvas_width"],
                "frame_contract.projection_canvas_width",
            ),
            projection_canvas_height=_strict_integer(
                value["projection_canvas_height"],
                "frame_contract.projection_canvas_height",
            ),
            projection_crop_left=_strict_integer(
                value["projection_crop_left"],
                "frame_contract.projection_crop_left",
            ),
            projection_crop_top=_strict_integer(
                value["projection_crop_top"],
                "frame_contract.projection_crop_top",
            ),
        )

    @classmethod
    def from_sequence(cls, value: _core.ImageSequence) -> _FrameContract:
        return cls(
            height=value.height,
            width=value.width,
            channels=value.channels,
            dtype=value.frame_dtype,
            color_space=value.color_space,
            alpha_mode=value.alpha_mode,
            maxval=value.maxval,
            projection=value.projection,
            projection_canvas_width=value.projection_canvas_width,
            projection_canvas_height=value.projection_canvas_height,
            projection_crop_left=value.projection_crop_left,
            projection_crop_top=value.projection_crop_top,
        )

    def as_manifest(self) -> dict[str, int | str]:
        return {field: getattr(self, field) for field in sorted(_FRAME_CONTRACT_FIELDS)}

    @property
    def projection_kwargs(self) -> dict[str, int | str]:
        result: dict[str, int | str] = {"projection": self.projection}
        if self.projection == "equirectangular":
            result.update(
                projection_canvas_width=self.projection_canvas_width,
                projection_canvas_height=self.projection_canvas_height,
                projection_crop_left=self.projection_crop_left,
                projection_crop_top=self.projection_crop_top,
            )
        return result

    @property
    def projection_geometry(self) -> tuple[str, int, int, int, int]:
        return (
            self.projection,
            self.projection_canvas_width,
            self.projection_canvas_height,
            self.projection_crop_left,
            self.projection_crop_top,
        )

    @property
    def is_full_sphere(self) -> bool:
        return (
            self.projection == "equirectangular"
            and self.projection_canvas_width == self.width
            and self.projection_canvas_height == self.height
            and self.projection_crop_left == 0
            and self.projection_crop_top == 0
        )


@dataclass(frozen=True, slots=True)
class _FrameScan:
    contract: _FrameContract
    formats: tuple[str, ...]


def _validate_name(value: object, frame_access: ImageFrameAccess) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("image sequence: frame file must be a non-empty string")
    if (
        value in {".", "..", _MARKER}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or "\0" in value
    ):
        raise ValueError("image sequence: frame files must be unique flat names")
    if len(value.encode("utf-8")) > 1024 * 1024:
        raise ValueError("image sequence: frame name exceeds 1 MiB")
    if Path(value).suffix.lower() not in _image_extensions(frame_access):
        raise ValueError(f"image sequence: unsupported frame extension in {value!r}")
    return value


def _manifest_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest key {key!r}")
        result[key] = value
    return result


def _load_manifest(
    directory: Path,
    frame_access: ImageFrameAccess,
) -> tuple[list[str], np.ndarray, np.ndarray, _FrameContract | None]:
    marker = directory / _MARKER
    if not marker.exists():
        names = [
            item.name
            for item in directory.iterdir()
            if item.is_file() and item.suffix.lower() in _image_extensions(frame_access)
        ]
        names.sort(key=lambda name: _natural_key(Path(name)))
        if not names:
            raise ValueError("image sequence: directory contains no supported frames")
        empty = np.empty(0, np.int64)
        return names, empty, empty, None
    if marker.stat().st_size > _MANIFEST_LIMIT:
        raise ValueError("image sequence: manifest exceeds 1 MiB")
    try:
        document = json.loads(
            marker.read_text(encoding="utf-8"),
            object_pairs_hook=_manifest_object,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"image sequence: invalid manifest: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {
        "sceneio_image_sequence",
        "frame_contract",
        "frames",
    }:
        raise ValueError("image sequence: manifest object has unsupported fields")
    if (
        isinstance(document["sceneio_image_sequence"], bool)
        or document["sceneio_image_sequence"] != _MANIFEST_VERSION
    ):
        raise ValueError("image sequence: unsupported manifest version")
    contract = _FrameContract.from_manifest(document["frame_contract"])
    frames = document["frames"]
    if not isinstance(frames, list) or not frames:
        raise ValueError("image sequence: manifest frames must be a non-empty array")
    names: list[str] = []
    timing_mode: bool | None = None
    timestamps: list[int] = []
    durations: list[int] = []
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("image sequence: every manifest frame must be an object")
        has_timing = set(frame) == {"file", "timestamp_ns", "duration_ns"}
        if set(frame) != {"file"} and not has_timing:
            raise ValueError("image sequence: manifest frame has unsupported fields")
        if timing_mode is None:
            timing_mode = has_timing
        elif timing_mode != has_timing:
            raise ValueError("image sequence: timing must be present for every frame")
        names.append(_validate_name(frame["file"], frame_access))
        if has_timing:
            timestamps.append(_strict_integer(frame["timestamp_ns"], "frame timestamp_ns"))
            durations.append(_strict_integer(frame["duration_ns"], "frame duration_ns", minimum=1))
    if len(names) != len(set(names)):
        raise ValueError("image sequence: frame names must be unique")
    return (
        names,
        np.asarray(timestamps, np.int64),
        np.asarray(durations, np.int64),
        contract,
    )


def _inspection_contract(info: Inspection, path: Path) -> _FrameContract:
    if info.payload_kind != "image":
        raise ValueError(
            f"image sequence: {path.name!r} is {info.payload_kind!r}, not an image frame"
        )
    if info.shape is None or info.dtype is None or info.channels is None:
        raise ValueError(f"image sequence: {path.name!r} is not an image frame")
    channels = info.channels
    valid_shape = (channels == 1 and len(info.shape) == 2) or (
        len(info.shape) == 3 and info.shape[-1] == channels
    )
    if not valid_shape:
        raise ValueError(f"image sequence: {path.name!r} does not resolve to one still image")
    height, width = info.shape[:2]
    metadata: Mapping[str, object] = info.metadata
    dtype = info.dtype
    maxval = metadata.get(
        "maxval",
        255 if dtype == "uint8" else 65535 if dtype == "uint16" else 0,
    )
    projection = metadata.get("projection", "unknown")
    if projection == "equirectangular":
        canvas_width = metadata.get("projection_canvas_width", width)
        canvas_height = metadata.get("projection_canvas_height", height)
        crop_left = metadata.get("projection_crop_left", 0)
        crop_top = metadata.get("projection_crop_top", 0)
    else:
        canvas_width = canvas_height = crop_left = crop_top = 0
    return _FrameContract(
        height=height,
        width=width,
        channels=channels,
        dtype=dtype,
        color_space=str(metadata.get("color_space", "gray" if channels == 1 else "unknown")),
        alpha_mode=str(metadata.get("alpha_mode", "straight" if channels == 4 else "none")),
        maxval=_strict_integer(maxval, f"{path.name!r} maxval"),
        projection=str(projection),
        projection_canvas_width=_strict_integer(
            canvas_width, f"{path.name!r} projection_canvas_width"
        ),
        projection_canvas_height=_strict_integer(
            canvas_height, f"{path.name!r} projection_canvas_height"
        ),
        projection_crop_left=_strict_integer(crop_left, f"{path.name!r} projection_crop_left"),
        projection_crop_top=_strict_integer(crop_top, f"{path.name!r} projection_crop_top"),
    )


def _require_declared_compatibility(
    declared: _FrameContract,
    observed: _FrameContract,
    path: Path,
) -> None:
    exact_fields = (
        "height",
        "width",
        "channels",
        "dtype",
        "alpha_mode",
        "maxval",
    )
    if any(getattr(declared, field) != getattr(observed, field) for field in exact_fields):
        raise ValueError(
            f"image sequence: {path.name!r} metadata disagrees with the frame contract"
        )
    if observed.color_space != "unknown" and observed.color_space != declared.color_space:
        raise ValueError(f"image sequence: {path.name!r} color space disagrees with the manifest")
    if observed.projection != "unknown" and (
        observed.projection_geometry != declared.projection_geometry
    ):
        raise ValueError(f"image sequence: {path.name!r} projection disagrees with the manifest")


def _frame_metadata(
    paths: list[Path],
    frame_access: ImageFrameAccess,
    declared: _FrameContract | None = None,
) -> _FrameScan:
    expected = declared
    formats: list[str] = []
    for path in paths:
        if not path.is_file():
            raise ValueError(f"image sequence: missing frame {path.name!r}")
        info = frame_access.inspect(path)
        if not isinstance(info, Inspection):
            raise TypeError(
                "image sequence: frame inspector returned "
                f"{type(info).__name__}, expected Inspection"
            )
        current = _inspection_contract(info, path)
        formats.append(info.format)
        if declared is not None:
            _require_declared_compatibility(declared, current, path)
        elif expected is None:
            expected = current
        elif current != expected:
            raise ValueError("image sequence: heterogeneous frame contracts are unsupported")
    assert expected is not None
    return _FrameScan(expected, tuple(formats))


def _build(
    directory: Path,
    frame_access: ImageFrameAccess,
    start: int | None = None,
    stop: int | None = None,
):
    names, timestamps, durations, declared = _load_manifest(directory, frame_access)
    paths = [directory / name for name in names]
    scan = _frame_metadata(paths, frame_access, declared)
    contract = scan.contract
    if start is not None:
        if start < 0 or stop is None or start >= stop or stop > len(paths):
            raise ValueError("image sequence: frame range is out of bounds")
        paths = paths[start:stop]
        names = names[start:stop]
        if timestamps.size:
            timestamps = timestamps[start:stop]
            durations = durations[start:stop]
    return _core.image_sequence_paths(
        [str(path.resolve()) for path in paths],
        names,
        timestamps,
        durations,
        contract.height,
        contract.width,
        contract.channels,
        contract.dtype,
        contract.color_space,
        contract.alpha_mode,
        maxval=contract.maxval,
        **contract.projection_kwargs,
    )


def read_image_sequence_directory(frame_access: ImageFrameAccess, path: str):
    directory = Path(path)
    if not directory.is_dir():
        raise ValueError("image sequence: path is not a directory")
    return _build(directory, frame_access)


def read_image_sequence_directory_frames(
    frame_access: ImageFrameAccess,
    path: str,
    start: int,
    stop: int,
):
    directory = Path(path)
    if not directory.is_dir():
        raise ValueError("image sequence: path is not a directory")
    return _build(directory, frame_access, start, stop)


def inspect_image_sequence_directory(frame_access: ImageFrameAccess, path: str):
    directory = Path(path)
    names, timestamps, _durations, declared = _load_manifest(directory, frame_access)
    paths = [directory / name for name in names]
    scan = _frame_metadata(paths, frame_access, declared)
    contract = scan.contract
    byte_size = sum(item.stat().st_size for item in directory.iterdir() if item.is_file())
    return Inspection(
        format="image_sequence",
        payload_kind="image_sequence",
        byte_size=byte_size,
        shape=(len(paths), contract.height, contract.width, contract.channels),
        dtype=contract.dtype,
        count=len(paths),
        channels=contract.channels,
        metadata={
            "storage_mode": "encoded_paths",
            "has_timing": bool(timestamps.size),
            "manifest": (directory / _MARKER).exists(),
            "manifest_version": _MANIFEST_VERSION if declared is not None else None,
            "frame_names": tuple(names),
            "frame_formats": scan.formats,
            "color_space": contract.color_space,
            "alpha_mode": contract.alpha_mode,
            "maxval": contract.maxval,
            "projection": contract.projection,
            "projection_canvas_width": contract.projection_canvas_width,
            "projection_canvas_height": contract.projection_canvas_height,
            "projection_crop_left": contract.projection_crop_left,
            "projection_crop_top": contract.projection_crop_top,
            "is_full_sphere": contract.is_full_sphere,
        },
    )


def _copy_file(source: Path, destination: Path) -> None:
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(_COPY_CHUNK):
            writer.write(chunk)


def _manifest_frames(sequence: _core.ImageSequence, names: list[str]) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    has_timing = bool(sequence.has_timing)
    timestamps = np.asarray(sequence.timestamps_ns)
    durations = np.asarray(sequence.durations_ns)
    for index, name in enumerate(names):
        frame: dict[str, object] = {"file": name}
        if has_timing:
            frame["timestamp_ns"] = int(timestamps[index])
            frame["duration_ns"] = int(durations[index])
        frames.append(frame)
    return frames


def _packed_frame_image(
    sequence: _core.ImageSequence,
    contract: _FrameContract,
    index: int,
) -> _core.Image:
    return _core.image(
        np.asarray(sequence.pixels[index]),
        color_space=sequence.color_space,
        alpha_mode=sequence.alpha_mode,
        maxval=sequence.maxval,
        **contract.projection_kwargs,
    )


def _replace_directory(stage: Path, destination: Path) -> None:
    backup: Path | None = None
    if destination.exists():
        backup = destination.parent / f".{destination.name}.sceneio-backup-{uuid.uuid4().hex}"
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def _write_image_sequence_directory(
    frame_access: ImageFrameAccess,
    sequence,
    path: str,
    *,
    frame_extension: str | None = None,
    encode_frame: Callable[[_core.Image, Path], None] | None = None,
) -> None:
    if not isinstance(sequence, _core.ImageSequence):
        raise TypeError("image sequence: writer requires ImageSequence")
    if sequence.has_acquisition_timing:
        raise ValueError("image sequence: acquisition timing metadata is not representable")
    if sequence.has_loop_count or sequence.has_background:
        raise ValueError("image sequence: loop/background metadata is not representable")
    if sequence.num_frames < 1:
        raise ValueError("image sequence: directory output requires at least one frame")

    contract = _FrameContract.from_sequence(sequence)
    sources: list[Path] | None = None
    if sequence.storage_mode == "encoded_paths":
        if frame_extension is not None or encode_frame is not None:
            raise ValueError("image sequence: frame_format is valid only for packed frame encoding")
        names = [_validate_name(name, frame_access) for name in sequence.frame_names]
        sources = [Path(value) for value in sequence.frame_paths]
        if len(names) != sequence.num_frames or len(sources) != sequence.num_frames:
            raise ValueError("image sequence: frame reference count is inconsistent")
        if len(names) != len(set(names)):
            raise ValueError("image sequence: frame names must be unique")
        _frame_metadata(sources, frame_access, contract)
    elif sequence.storage_mode == "packed":
        if frame_extension is None or encode_frame is None:
            raise ValueError(
                "image sequence: packed folder output requires an explicit frame_format"
            )
        if not frame_extension.startswith(".") or Path(frame_extension).name != frame_extension:
            raise ValueError("image sequence: invalid frame extension")
        digits = max(6, len(str(sequence.num_frames - 1)))
        names = [
            f"frame{index:0{digits}d}{frame_extension.lower()}"
            for index in range(sequence.num_frames)
        ]
    else:
        raise ValueError("image sequence: folder writer supports encoded paths or packed frames")

    destination = Path(path)
    parent = destination.parent
    if not parent.is_dir():
        raise ValueError("image sequence: output parent does not exist")
    if destination.exists() and not destination.is_dir():
        raise ValueError("image sequence: output path exists and is not a directory")
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.sceneio-", dir=parent))
    try:
        if sources is not None:
            for source, name in zip(sources, names, strict=True):
                _copy_file(source, stage / name)
        else:
            assert encode_frame is not None
            for index, name in enumerate(names):
                target = stage / name
                encode_frame(_packed_frame_image(sequence, contract, index), target)
                _frame_metadata([target], frame_access, contract)
        document = {
            "sceneio_image_sequence": _MANIFEST_VERSION,
            "frame_contract": contract.as_manifest(),
            "frames": _manifest_frames(sequence, names),
        }
        (stage / _MARKER).write_text(
            json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _replace_directory(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def write_image_sequence_directory(
    frame_access: ImageFrameAccess,
    sequence,
    path: str,
) -> None:
    """Copy a lazy encoded-path sequence into a canonical image folder.

    The registry-facing codec callback deliberately retains the uniform
    ``(record, path)`` writer signature. Typed packed-frame encoding is routed
    through :func:`sceneio.write_image_folder` instead.
    """

    _write_image_sequence_directory(frame_access, sequence, path)
