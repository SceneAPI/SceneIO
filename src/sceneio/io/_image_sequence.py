"""Lazy encoded-frame directory adapter for :class:`ImageSequence`.

The directory tier never decodes frame pixels. It validates every frame header,
stores owned path references in the compiled record, and copies encoded files
through bounded chunks on write.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._inspection import Inspection

_MARKER = "sceneio_sequence.json"
_MANIFEST_LIMIT = 1024 * 1024
_COPY_CHUNK = 1024 * 1024
_NATURAL_PART = re.compile(r"(\d+)")


def _natural_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    folded = path.name.casefold()
    parts = _NATURAL_PART.split(folded)
    segments = tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in parts
        if part
    )
    # Numeric spellings such as frame1/frame01 have the same natural segments.
    # Explicit text tie-breakers keep discovery deterministic across filesystems.
    return (*segments, (2, folded), (3, path.name))


def _image_extensions(frame_access: ImageFrameAccess) -> frozenset[str]:
    return frame_access.image_extensions()


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
) -> tuple[list[str], np.ndarray, np.ndarray]:
    marker = directory / _MARKER
    if not marker.exists():
        names = [
            item.name
            for item in directory.iterdir()
            if item.is_file()
            and item.suffix.lower() in _image_extensions(frame_access)
        ]
        names.sort(key=lambda name: _natural_key(Path(name)))
        if not names:
            raise ValueError("image sequence: directory contains no supported frames")
        empty = np.empty(0, np.int64)
        return names, empty, empty
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
        "frames",
    }:
        raise ValueError("image sequence: manifest object has unsupported fields")
    if document["sceneio_image_sequence"] != 1:
        raise ValueError("image sequence: unsupported manifest version")
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
            timestamp = frame["timestamp_ns"]
            duration = frame["duration_ns"]
            if (
                isinstance(timestamp, bool)
                or not isinstance(timestamp, int)
                or isinstance(duration, bool)
                or not isinstance(duration, int)
            ):
                raise ValueError("image sequence: timing values must be integers")
            timestamps.append(timestamp)
            durations.append(duration)
    if len(names) != len(set(names)):
        raise ValueError("image sequence: frame names must be unique")
    return (
        names,
        np.asarray(timestamps, np.int64),
        np.asarray(durations, np.int64),
    )


def _frame_metadata(
    paths: list[Path],
    frame_access: ImageFrameAccess,
) -> tuple[int, int, int, str]:
    expected: tuple[int, int, int, str] | None = None
    for path in paths:
        if not path.is_file():
            raise ValueError(f"image sequence: missing frame {path.name!r}")
        info = frame_access.inspect(path)
        if not isinstance(info, Inspection):
            raise TypeError(
                "image sequence: frame inspector returned "
                f"{type(info).__name__}, expected Inspection"
            )
        if info.shape is None or info.dtype is None or info.channels is None:
            raise ValueError(f"image sequence: {path.name!r} is not an image frame")
        height, width = info.shape[:2]
        current = (height, width, info.channels, info.dtype)
        if expected is None:
            expected = current
        elif current != expected:
            raise ValueError(
                "image sequence: heterogeneous frame shapes/dtypes are unsupported"
            )
    assert expected is not None
    return expected


def _build(
    directory: Path,
    frame_access: ImageFrameAccess,
    start: int | None = None,
    stop: int | None = None,
):
    names, timestamps, durations = _load_manifest(directory, frame_access)
    paths = [directory / name for name in names]
    height, width, channels, dtype = _frame_metadata(paths, frame_access)
    if start is not None:
        if start < 0 or stop is None or start >= stop or stop > len(paths):
            raise ValueError("image sequence: frame range is out of bounds")
        paths = paths[start:stop]
        names = names[start:stop]
        if timestamps.size:
            timestamps = timestamps[start:stop]
            durations = durations[start:stop]
    color_space = "gray" if channels == 1 else "unknown"
    alpha_mode = "straight" if channels == 4 else "none"
    return _core.image_sequence_paths(
        [str(path.resolve()) for path in paths],
        names,
        timestamps,
        durations,
        height,
        width,
        channels,
        dtype,
        color_space,
        alpha_mode,
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
    names, timestamps, _durations = _load_manifest(directory, frame_access)
    paths = [directory / name for name in names]
    height, width, channels, dtype = _frame_metadata(paths, frame_access)
    byte_size = sum(
        item.stat().st_size for item in directory.iterdir() if item.is_file()
    )
    return Inspection(
        format="image_sequence",
        datatype="image_sequence",
        byte_size=byte_size,
        shape=(len(paths), height, width, channels),
        dtype=dtype,
        count=len(paths),
        channels=channels,
        metadata={
            "storage_mode": "encoded_paths",
            "has_timing": bool(timestamps.size),
            "manifest": (directory / _MARKER).exists(),
            "frame_names": tuple(names),
        },
    )


def _copy_file(source: Path, destination: Path) -> None:
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(_COPY_CHUNK):
            writer.write(chunk)


def write_image_sequence_directory(
    frame_access: ImageFrameAccess,
    sequence,
    path: str,
) -> None:
    if not isinstance(sequence, _core.ImageSequence):
        raise TypeError("image sequence: writer requires ImageSequence")
    if sequence.storage_mode != "encoded_paths":
        raise ValueError("image sequence: directory writer requires encoded paths")
    names = [_validate_name(name, frame_access) for name in sequence.frame_names]
    sources = [Path(value) for value in sequence.frame_paths]
    if len(names) != sequence.num_frames or len(sources) != sequence.num_frames:
        raise ValueError("image sequence: frame reference count is inconsistent")
    if not names:
        raise ValueError("image sequence: directory output requires at least one frame")
    if len(names) != len(set(names)):
        raise ValueError("image sequence: frame names must be unique")
    actual = _frame_metadata(sources, frame_access)
    expected = (
        sequence.height,
        sequence.width,
        sequence.channels,
        sequence.frame_dtype,
    )
    if actual != expected:
        raise ValueError(
            "image sequence: referenced frame metadata disagrees with the record"
        )

    destination = Path(path)
    parent = destination.parent
    if not parent.is_dir():
        raise ValueError("image sequence: output parent does not exist")
    if destination.exists() and not destination.is_dir():
        raise ValueError("image sequence: output path exists and is not a directory")
    stage = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.sceneio-", dir=parent)
    )
    backup: Path | None = None
    try:
        for source, name in zip(sources, names, strict=True):
            _copy_file(source, stage / name)
        frames = []
        has_timing = bool(sequence.has_timing)
        timestamps = np.asarray(sequence.timestamps_ns)
        durations = np.asarray(sequence.durations_ns)
        for index, name in enumerate(names):
            frame: dict[str, object] = {"file": name}
            if has_timing:
                frame["timestamp_ns"] = int(timestamps[index])
                frame["duration_ns"] = int(durations[index])
            frames.append(frame)
        document = {
            "sceneio_image_sequence": 1,
            "frames": frames,
        }
        (stage / _MARKER).write_text(
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if destination.exists():
            backup = parent / (
                f".{destination.name}.sceneio-backup-{uuid.uuid4().hex}"
            )
            os.replace(destination, backup)
        try:
            os.replace(stage, destination)
        except Exception:
            if backup is not None and backup.exists():
                os.replace(backup, destination)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
