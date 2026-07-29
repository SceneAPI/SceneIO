"""Lossless adapters for OpsiClear COLMAP sparse-model sidecars."""

from __future__ import annotations

import contextlib
import functools
import math
import mmap
import os
import shlex
import struct
import tempfile
from pathlib import Path

import numpy as np

from sceneio import _core

from .models import (
    UINT32_MAX,
    CharucoBoard,
    CharucoCalibration,
    ColmapAdapterError,
    ExtendedSparseModel,
    IdTags,
    SparseExtensions,
    SparseMarker,
    SparseMarkerProjection,
    TimeFrame,
)

_VERSION = 1
_MAGICS = {
    "point3D_frames": b"PT3DFRM\0",
    "image_times": b"IMGTIMS\0",
    "time_frames": b"TIMFRMS\0",
    "charuco_boards": b"CHBORDS\0",
    "charuco_calibrations": b"CHCALIB\0",
}
_BINARY_NAMES = {
    "markers": "markers.bin",
    "marker_projections": "marker_projections.bin",
    "charuco_boards": "charuco_boards.bin",
    "charuco_calibrations": "charuco_calibrations.bin",
    "time_frames": "time_frames.bin",
    "image_times": "image_times.bin",
    "point3D_frames": "points3D_frames.bin",
}
_TEXT_NAMES = {key: name.removesuffix(".bin") + ".txt" for key, name in _BINARY_NAMES.items()}
_SIDECAR_NAMES = tuple(_BINARY_NAMES.values()) + tuple(_TEXT_NAMES.values())
_BASE_NAMES = tuple(
    f"{stem}.{suffix}"
    for suffix in ("bin", "txt")
    for stem in ("rigs", "cameras", "frames", "images", "points3D")
)
_U8 = struct.Struct("<B")
_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")
_U64 = struct.Struct("<Q")
_F64 = struct.Struct("<d")
_MAX_ENTRIES = 100_000_000
_MAX_STRING = 1 << 30
_CAMERA_PARAM_COUNTS = (
    3,
    4,
    4,
    5,
    8,
    8,
    12,
    5,
    4,
    5,
    12,
    16,
    4,
    5,
    3,
    4,
    6,
    2,
)


def _write_le_array(stream, value: np.ndarray, dtype: str) -> None:
    if value.size == 0:
        return
    little_endian = value.astype(dtype, copy=False)
    stream.write(memoryview(little_endian).cast("B"))


class _Reader:
    def __init__(self, path: Path):
        try:
            stream = path.open("rb")
        except OSError as exc:
            raise ColmapAdapterError(f"cannot read COLMAP sidecar {str(path)!r}: {exc}") from exc
        try:
            if path.stat().st_size == 0:
                raise ColmapAdapterError(f"{path.name} is empty")
            self.data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception:
            stream.close()
            raise
        finally:
            stream.close()
        self.offset = 0
        self.label = path.name

    def __del__(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            self.close()

    def close(self) -> None:
        data = getattr(self, "data", None)
        if data is not None and not data.closed:
            data.close()

    def unpack(self, layout: struct.Struct, field: str):
        if layout.size > len(self.data) - self.offset:
            raise ColmapAdapterError(f"{self.label} is truncated at {field}")
        values = layout.unpack_from(self.data, self.offset)
        self.offset += layout.size
        return values[0] if len(values) == 1 else values

    def take(self, size: int, field: str) -> bytes:
        if size < 0 or size > len(self.data) - self.offset:
            raise ColmapAdapterError(f"{self.label} is truncated at {field}")
        start = self.offset
        self.offset += size
        return self.data[start : start + size]

    def count(self, minimum_size: int, field: str) -> int:
        count = self.unpack(_U64, f"{field} count")
        if count > _MAX_ENTRIES or count > (len(self.data) - self.offset) // minimum_size:
            raise ColmapAdapterError(f"{self.label} {field} count exceeds the payload")
        return count

    def string(self, field: str) -> str:
        size = self.unpack(_U64, f"{field} length")
        if size > _MAX_STRING:
            raise ColmapAdapterError(f"{self.label} {field} exceeds its text bound")
        try:
            return self.take(size, field).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ColmapAdapterError(f"{self.label} {field} is not UTF-8") from exc

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise ColmapAdapterError(f"{self.label} has trailing bytes")


def _mapped_reader(function):
    @functools.wraps(function)
    def wrapped(path: Path, *args):
        reader = _Reader(path)
        try:
            result = function(reader, *args)
            reader.finish()
            return result
        finally:
            reader.close()

    return wrapped


def _read_header(reader: _Reader, kind: str, minimum_size: int) -> int:
    if reader.take(8, "magic") != _MAGICS[kind]:
        raise ColmapAdapterError(f"{reader.label} has the wrong {kind} magic")
    if reader.unpack(_U32, "version") != _VERSION:
        raise ColmapAdapterError(f"{reader.label} sidecar version is unsupported")
    return reader.count(minimum_size, kind)


def _bool(reader: _Reader, field: str) -> bool:
    value = reader.unpack(_U8, field)
    if value not in (0, 1):
        raise ColmapAdapterError(f"{reader.label} {field} must be 0 or 1")
    return bool(value)


@_mapped_reader
def _read_markers(reader: _Reader) -> tuple[SparseMarker, ...]:
    count = reader.count(118, "marker")
    result = []
    for index in range(count):
        marker_id = reader.unpack(_U32, f"marker {index} id")
        marker_type = reader.unpack(_U8, f"marker {index} type")
        enabled = _bool(reader, f"marker {index} enabled")
        label = reader.string(f"marker {index} label")
        position = np.array(
            [reader.unpack(_F64, f"marker {index} position") for _ in range(3)],
            np.float64,
        )
        covariance = np.array(
            [reader.unpack(_F64, f"marker {index} covariance") for _ in range(9)],
            np.float64,
        ).reshape(3, 3)
        point3d_id = reader.unpack(_U64, f"marker {index} point3D id")
        result.append(
            SparseMarker(
                marker_id,
                marker_type,
                enabled,
                label,
                position,
                covariance,
                point3d_id,
            )
        )
    return tuple(result)


@_mapped_reader
def _read_projections(reader: _Reader) -> tuple[SparseMarkerProjection, ...]:
    count = reader.count(37, "projection")
    result = []
    for index in range(count):
        result.append(
            SparseMarkerProjection(
                reader.unpack(_U32, f"projection {index} marker id"),
                reader.unpack(_U32, f"projection {index} image id"),
                np.array(
                    [
                        reader.unpack(_F64, f"projection {index} x"),
                        reader.unpack(_F64, f"projection {index} y"),
                    ],
                    np.float64,
                ),
                reader.unpack(_F64, f"projection {index} size"),
                _bool(reader, f"projection {index} pinned"),
                reader.unpack(_U32, f"projection {index} point2D index"),
            )
        )
    return tuple(result)


@_mapped_reader
def _read_id_tags(reader: _Reader, kind: str) -> IdTags:
    count = _read_header(reader, kind, 16)
    values = np.frombuffer(
        reader.data,
        dtype=np.dtype([("id", "<u8"), ("tag", "<u8")]),
        count=count,
        offset=reader.offset,
    )
    ids = np.array(values["id"], dtype=np.uint64, copy=True)
    tags = np.array(values["tag"], dtype=np.uint64, copy=True)
    reader.offset += count * 16
    del values
    return IdTags(ids, tags)


@_mapped_reader
def _read_time_frames(reader: _Reader) -> tuple[TimeFrame, ...]:
    count = _read_header(reader, "time_frames", 32)
    result = []
    for index in range(count):
        result.append(
            TimeFrame(
                reader.unpack(_U64, f"time frame {index} id"),
                reader.unpack(_F64, f"time frame {index} timestamp"),
                reader.string(f"time frame {index} sync group"),
                reader.string(f"time frame {index} label"),
            )
        )
    return tuple(result)


def _read_board(reader: _Reader, label: str) -> CharucoBoard:
    return CharucoBoard(
        reader.string(f"{label} id"),
        reader.unpack(_I32, f"{label} dictionary"),
        reader.unpack(_I32, f"{label} squares x"),
        reader.unpack(_I32, f"{label} squares y"),
        reader.unpack(_F64, f"{label} square length"),
        reader.unpack(_F64, f"{label} marker length"),
    )


@_mapped_reader
def _read_boards(reader: _Reader) -> tuple[CharucoBoard, ...]:
    count = _read_header(reader, "charuco_boards", 36)
    result = tuple(_read_board(reader, f"board {index}") for index in range(count))
    return result


def _validated_pose(values: list[float], label: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    norm = float(np.linalg.norm(result[:4]))
    if not np.isfinite(norm) or abs(norm - 1.0) > 1e-10:
        raise ColmapAdapterError(f"{label} quaternion must be unit length")
    return result


@_mapped_reader
def _read_calibrations(reader: _Reader) -> tuple[CharucoCalibration, ...]:
    count = _read_header(reader, "charuco_calibrations", 80)
    result = []
    for index in range(count):
        session_id = reader.string(f"calibration {index} session id")
        board = _read_board(reader, f"calibration {index} board")
        camera_model_id = reader.unpack(_I32, f"calibration {index} camera model")
        width = reader.unpack(_I32, f"calibration {index} width")
        height = reader.unpack(_I32, f"calibration {index} height")
        num_params = reader.count(8, f"calibration {index} parameters")
        if (
            camera_model_id not in range(len(_CAMERA_PARAM_COUNTS))
            or num_params != _CAMERA_PARAM_COUNTS[camera_model_id]
        ):
            raise ColmapAdapterError(f"calibration {index} camera model/parameter count disagrees")
        params = np.array(
            [reader.unpack(_F64, f"calibration {index} parameter") for _ in range(num_params)],
            np.float64,
        )
        overall = reader.unpack(_F64, f"calibration {index} overall RMSE")
        num_images = reader.count(72, f"calibration {index} images")
        names = []
        rmses = np.empty((num_images,), np.float64)
        poses = np.empty((num_images, 7), np.float64)
        for image_index in range(num_images):
            names.append(reader.string(f"calibration {index} image {image_index} name"))
            rmses[image_index] = reader.unpack(
                _F64,
                f"calibration {index} image {image_index} RMSE",
            )
            poses[image_index] = _validated_pose(
                [
                    reader.unpack(
                        _F64,
                        f"calibration {index} image {image_index} pose",
                    )
                    for _ in range(7)
                ],
                f"calibration {index} image {image_index}",
            )
        result.append(
            CharucoCalibration(
                session_id,
                board,
                camera_model_id,
                width,
                height,
                params,
                overall,
                tuple(names),
                rmses,
                poses,
            )
        )
    return tuple(result)


def _tokens(line: str, label: str) -> list[str]:
    try:
        return shlex.split(line, comments=False, posix=True)
    except ValueError as exc:
        raise ColmapAdapterError(f"{label} has invalid quoting") from exc


def _text_rows(path: Path):
    try:
        stream = path.open("rb")
    except OSError as exc:
        raise ColmapAdapterError(f"cannot read COLMAP sidecar {str(path)!r}: {exc}") from exc
    with stream:
        line_number = 0
        while True:
            payload = stream.readline(16 * 1024 * 1024 + 1)
            if not payload:
                break
            line_number += 1
            if len(payload) > 16 * 1024 * 1024:
                raise ColmapAdapterError(f"{path.name} line {line_number} exceeds 16 MiB")
            try:
                line = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ColmapAdapterError(
                    f"{path.name} line {line_number} is not UTF-8"
                ) from exc
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                yield line_number, stripped


def _text_reader(function):
    @functools.wraps(function)
    def wrapped(path: Path):
        rows = iter(_text_rows(path))
        try:
            return function(path, rows)
        finally:
            rows.close()

    return wrapped


def _integer(token: str, maximum: int, label: str) -> int:
    try:
        value = int(token, 10)
    except ValueError as exc:
        raise ColmapAdapterError(f"{label} is not an integer") from exc
    if value < 0 or value > maximum:
        raise ColmapAdapterError(f"{label} is outside bounds")
    return value


def _float(token: str, label: str, *, allow_nan: bool = False) -> float:
    try:
        value = float(token)
    except ValueError as exc:
        raise ColmapAdapterError(f"{label} is not numeric") from exc
    if not math.isfinite(value) and not (allow_nan and math.isnan(value)):
        raise ColmapAdapterError(f"{label} is outside its numeric domain")
    return value


@_text_reader
def _read_markers_text(path: Path, rows) -> tuple[SparseMarker, ...]:
    result = []
    for line_number, line in rows:
        fields = _tokens(line, f"{path.name} line {line_number}")
        if len(fields) != 17:
            raise ColmapAdapterError(f"{path.name} line {line_number} needs 17 fields")
        result.append(
            SparseMarker(
                _integer(fields[0], UINT32_MAX - 1, "marker id"),
                _integer(fields[1], 3, "marker type"),
                bool(_integer(fields[2], 1, "marker enabled")),
                fields[3],
                np.array(
                    [_float(item, "marker position", allow_nan=True) for item in fields[4:7]],
                    np.float64,
                ),
                np.array(
                    [_float(item, "marker covariance", allow_nan=True) for item in fields[7:16]],
                    np.float64,
                ).reshape(3, 3),
                _integer(fields[16], (1 << 64) - 1, "marker point3D id"),
            )
        )
    return tuple(result)


@_text_reader
def _read_projections_text(
    path: Path,
    rows,
) -> tuple[SparseMarkerProjection, ...]:
    result = []
    for line_number, line in rows:
        fields = line.split()
        if len(fields) not in (6, 7):
            raise ColmapAdapterError(f"{path.name} line {line_number} needs 6 or 7 fields")
        result.append(
            SparseMarkerProjection(
                _integer(fields[0], UINT32_MAX - 1, "projection marker id"),
                _integer(fields[1], UINT32_MAX - 1, "projection image id"),
                np.array(
                    [
                        _float(fields[2], "projection x"),
                        _float(fields[3], "projection y"),
                    ],
                    np.float64,
                ),
                _float(fields[4], "projection size"),
                bool(_integer(fields[5], 1, "projection pinned")),
                (
                    _integer(fields[6], UINT32_MAX, "projection point2D index")
                    if len(fields) == 7
                    else UINT32_MAX
                ),
            )
        )
    return tuple(result)


def _read_id_tags_text(path: Path) -> IdTags:
    rows = iter(_text_rows(path))
    try:
        count = sum(1 for _ in rows)
    finally:
        rows.close()
    if count > _MAX_ENTRIES:
        raise ColmapAdapterError(f"{path.name} has too many rows")
    ids = np.empty((count,), dtype=np.uint64)
    tags = np.empty((count,), dtype=np.uint64)
    rows = iter(_text_rows(path))
    try:
        for index, (line_number, line) in enumerate(rows):
            fields = line.split()
            if len(fields) != 2:
                raise ColmapAdapterError(
                    f"{path.name} line {line_number} needs 2 fields"
                )
            ids[index] = _integer(fields[0], (1 << 64) - 1, "tag id")
            tags[index] = _integer(fields[1], (1 << 64) - 1, "tag value")
    finally:
        rows.close()
    return IdTags(ids, tags)


def _board_tokens(fields: list[str], start: int, label: str):
    if len(fields) < start + 6:
        raise ColmapAdapterError(f"{label} board is truncated")
    return (
        CharucoBoard(
            fields[start],
            _integer(fields[start + 1], 19, f"{label} dictionary"),
            _integer(fields[start + 2], (1 << 31) - 1, f"{label} squares x"),
            _integer(fields[start + 3], (1 << 31) - 1, f"{label} squares y"),
            _float(fields[start + 4], f"{label} square length"),
            _float(fields[start + 5], f"{label} marker length"),
        ),
        start + 6,
    )


@_text_reader
def _read_time_frames_text(path: Path, rows) -> tuple[TimeFrame, ...]:
    result = []
    for line_number, line in rows:
        fields = _tokens(line, f"{path.name} line {line_number}")
        if len(fields) != 4:
            raise ColmapAdapterError(f"{path.name} line {line_number} needs 4 fields")
        result.append(
            TimeFrame(
                _integer(fields[0], UINT32_MAX - 1, "time id"),
                _float(fields[1], "timestamp", allow_nan=True),
                fields[2],
                fields[3],
            )
        )
    return tuple(result)


@_text_reader
def _read_boards_text(path: Path, rows) -> tuple[CharucoBoard, ...]:
    result = []
    for line_number, line in rows:
        fields = _tokens(line, f"{path.name} line {line_number}")
        board, stop = _board_tokens(fields, 0, f"{path.name} line {line_number}")
        if stop != len(fields):
            raise ColmapAdapterError(f"{path.name} line {line_number} has trailing fields")
        result.append(board)
    return tuple(result)


@_text_reader
def _read_calibrations_text(
    path: Path,
    rows,
) -> tuple[CharucoCalibration, ...]:
    result = []
    for line_number, line in rows:
        label = f"{path.name} line {line_number}"
        fields = _tokens(line, label)
        if not fields:
            continue
        session_id = fields[0]
        board, position = _board_tokens(fields, 1, label)
        if len(fields) < position + 5:
            raise ColmapAdapterError(f"{label} camera metadata is truncated")
        model = _integer(fields[position], 17, f"{label} camera model")
        width = _integer(fields[position + 1], (1 << 31) - 1, f"{label} width")
        height = _integer(fields[position + 2], (1 << 31) - 1, f"{label} height")
        num_params = _integer(fields[position + 3], 1024, f"{label} parameter count")
        position += 4
        if num_params != _CAMERA_PARAM_COUNTS[model]:
            raise ColmapAdapterError(f"{label} camera model/parameter count disagrees")
        if len(fields) < position + num_params + 2:
            raise ColmapAdapterError(f"{label} parameters are truncated")
        params = np.asarray(
            [
                _float(item, f"{label} camera parameter")
                for item in fields[position : position + num_params]
            ],
            np.float64,
        )
        position += num_params
        overall = _float(fields[position], f"{label} overall RMSE")
        num_images = _integer(fields[position + 1], _MAX_ENTRIES, f"{label} image count")
        position += 2
        if len(fields) != position + num_images * 9:
            raise ColmapAdapterError(f"{label} image records are truncated")
        names = []
        rmses = np.empty((num_images,), np.float64)
        poses = np.empty((num_images, 7), np.float64)
        for image_index in range(num_images):
            names.append(fields[position])
            rmses[image_index] = _float(fields[position + 1], f"{label} image RMSE")
            poses[image_index] = _validated_pose(
                [
                    _float(item, f"{label} image pose")
                    for item in fields[position + 2 : position + 9]
                ],
                f"{label} image {image_index}",
            )
            position += 9
        result.append(
            CharucoCalibration(
                session_id,
                board,
                model,
                width,
                height,
                params,
                overall,
                tuple(names),
                rmses,
                poses,
            )
        )
    return tuple(result)


def read_sparse_extensions(
    path,
    *,
    encoding: str,
) -> SparseExtensions:
    """Read all present extension sidecars for one sparse-model encoding."""

    if encoding not in ("binary", "text"):
        raise ColmapAdapterError("encoding must be 'binary' or 'text'")
    root = Path(path)
    names = _BINARY_NAMES if encoding == "binary" else _TEXT_NAMES

    def optional(key: str, reader):
        source = root / names[key]
        return reader(source) if source.is_file() else None

    if encoding == "binary":
        return SparseExtensions(
            optional("markers", _read_markers),
            optional("marker_projections", _read_projections),
            optional("charuco_boards", _read_boards),
            optional("charuco_calibrations", _read_calibrations),
            optional("time_frames", _read_time_frames),
            optional(
                "image_times",
                lambda item: _read_id_tags(item, "image_times"),
            ),
            optional(
                "point3D_frames",
                lambda item: _read_id_tags(item, "point3D_frames"),
            ),
        )
    return SparseExtensions(
        optional("markers", _read_markers_text),
        optional("marker_projections", _read_projections_text),
        optional("charuco_boards", _read_boards_text),
        optional("charuco_calibrations", _read_calibrations_text),
        optional("time_frames", _read_time_frames_text),
        optional("image_times", _read_id_tags_text),
        optional("point3D_frames", _read_id_tags_text),
    )


def _validate_reconstruction_links(model: ExtendedSparseModel) -> None:
    extensions = model.extensions
    image_ids = {int(item) for item in model.reconstruction.image_ids}
    point_ids = {int(item) for item in model.reconstruction.point3D_ids}
    if extensions.marker_projections is not None and any(
        item.image_id not in image_ids for item in extensions.marker_projections
    ):
        raise ColmapAdapterError("marker projection references an unknown sparse image")
    observation_offsets = model.reconstruction._observation_offsets
    observation_point_ids = model.reconstruction._observation_point3D_ids
    observation_counts = {
        int(image_id): int(observation_offsets[index + 1] - observation_offsets[index])
        for index, image_id in enumerate(model.reconstruction.image_ids)
    }
    if extensions.marker_projections is not None and any(
        item.point2D_idx != UINT32_MAX
        and item.point2D_idx >= observation_counts[item.image_id]
        for item in extensions.marker_projections
    ):
        raise ColmapAdapterError(
            "marker projection point2D index exceeds sparse image observations"
        )
    markers_by_id = {
        item.marker_id: item for item in extensions.markers or ()
    }
    image_rows = {
        int(image_id): index
        for index, image_id in enumerate(model.reconstruction.image_ids)
    }
    if extensions.marker_projections is not None and any(
        item.point2D_idx != UINT32_MAX
        and markers_by_id[item.marker_id].point3D_id != (1 << 64) - 1
        and int(
            observation_point_ids[
                int(observation_offsets[image_rows[item.image_id]])
                + item.point2D_idx
            ]
        )
        not in (-1, markers_by_id[item.marker_id].point3D_id)
        for item in extensions.marker_projections
    ):
        raise ColmapAdapterError(
            "marker projection observation and marker point3D ids disagree"
        )
    if extensions.markers is not None and any(
        item.point3D_id != (1 << 64) - 1 and item.point3D_id not in point_ids
        for item in extensions.markers
    ):
        raise ColmapAdapterError("marker references an unknown sparse point")
    if extensions.image_times is not None and any(
        int(item) not in image_ids for item in extensions.image_times.ids
    ):
        raise ColmapAdapterError("image_times references an unknown image")
    if extensions.point3D_frames is not None and any(
        int(item) not in point_ids for item in extensions.point3D_frames.ids
    ):
        raise ColmapAdapterError("points3D_frames references an unknown point")


def read_extended_sparse_model(path) -> ExtendedSparseModel:
    """Read a standard sparse model plus all repository-owned sidecars."""

    root = Path(path)
    has_binary = (root / "cameras.bin").is_file()
    has_text = (root / "cameras.txt").is_file()
    if has_binary:
        encoding = "binary"
        opposite = _TEXT_NAMES
        opposite_base = tuple(
            name for name in _BASE_NAMES if name.endswith(".txt")
        )
    elif has_text:
        encoding = "text"
        opposite = _BINARY_NAMES
        opposite_base = tuple(
            name for name in _BASE_NAMES if name.endswith(".bin")
        )
    else:
        raise ColmapAdapterError("extended sparse model has no cameras.bin or cameras.txt")
    mixed_base = sorted(name for name in opposite_base if (root / name).is_file())
    if mixed_base:
        raise ColmapAdapterError(
            "extended sparse model has opposite-encoding base files: "
            + ", ".join(mixed_base)
        )
    mismatched = sorted(
        name for name in opposite.values() if (root / name).is_file()
    )
    if mismatched:
        raise ColmapAdapterError(
            "extended sparse model has opposite-encoding sidecars: "
            + ", ".join(mismatched)
        )
    if encoding == "binary":
        reconstruction = _core._read_colmap_sparse_with_sidecars(str(root))
    else:
        reconstruction = _core._read_colmap_txt_with_sidecars(str(root))
    model = ExtendedSparseModel(
        reconstruction,
        read_sparse_extensions(root, encoding=encoding),
        encoding,
    )
    _validate_reconstruction_links(model)
    return model


def _quoted(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ColmapAdapterError("sidecar text fields cannot contain newlines")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _double(value: float) -> str:
    return "nan" if math.isnan(value) else format(value, ".17g")


def _preflight_extensions(
    extensions: SparseExtensions,
    encoding: str,
) -> None:
    def check(value: str, label: str) -> None:
        try:
            payload = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ColmapAdapterError(f"{label} is not valid UTF-8 text") from exc
        if len(payload) > _MAX_STRING:
            raise ColmapAdapterError(f"{label} exceeds its text bound")
        if encoding == "text" and ("\r" in value or "\n" in value):
            raise ColmapAdapterError(
                f"{label} cannot contain line breaks in text encoding"
            )

    for item in extensions.markers or ():
        check(item.label, "marker label")
    for item in extensions.time_frames or ():
        check(item.sync_group, "time-frame sync group")
        check(item.label, "time-frame label")
    for item in extensions.charuco_boards or ():
        check(item.board_id, "ChArUco board id")
    for item in extensions.charuco_calibrations or ():
        check(item.session_id, "ChArUco calibration session id")
        check(item.board.board_id, "ChArUco calibration board id")
        for name in item.image_names:
            check(name, "ChArUco calibration image name")


def _atomic(path: Path, writer, *, binary: bool) -> None:
    temporary = None
    mode = "w+b" if binary else "w+"
    kwargs = {} if binary else {"encoding": "utf-8", "newline": "\n"}
    try:
        with tempfile.NamedTemporaryFile(
            mode=mode,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            **kwargs,
        ) as stream:
            temporary = Path(stream.name)
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _put_string(stream, value: str) -> None:
    encoded = value.encode("utf-8")
    if len(encoded) > _MAX_STRING:
        raise ColmapAdapterError("binary sidecar text exceeds its bound")
    stream.write(_U64.pack(len(encoded)))
    stream.write(encoded)


def _put_board(stream, board: CharucoBoard) -> None:
    _put_string(stream, board.board_id)
    stream.write(_I32.pack(board.dictionary))
    stream.write(_I32.pack(board.squares_x))
    stream.write(_I32.pack(board.squares_y))
    stream.write(_F64.pack(board.square_length))
    stream.write(_F64.pack(board.marker_length))


def _write_binary(
    root: Path,
    extensions: SparseExtensions,
) -> None:
    if extensions.markers is not None:
        markers = tuple(sorted(extensions.markers, key=lambda item: item.marker_id))

        def write_markers(stream):
            stream.write(_U64.pack(len(markers)))
            for item in markers:
                stream.write(_U32.pack(item.marker_id))
                stream.write(_U8.pack(item.marker_type))
                stream.write(_U8.pack(int(item.enabled)))
                _put_string(stream, item.label)
                _write_le_array(stream, item.world_position, "<f8")
                _write_le_array(stream, item.world_covariance, "<f8")
                stream.write(_U64.pack(item.point3D_id))

        _atomic(root / _BINARY_NAMES["markers"], write_markers, binary=True)

    if extensions.marker_projections is not None:
        projections = tuple(
            sorted(
                extensions.marker_projections,
                key=lambda item: (item.marker_id, item.image_id),
            )
        )

        def write_projections(stream):
            stream.write(_U64.pack(len(projections)))
            for item in projections:
                stream.write(_U32.pack(item.marker_id))
                stream.write(_U32.pack(item.image_id))
                _write_le_array(stream, item.xy, "<f8")
                stream.write(_F64.pack(item.size))
                stream.write(_U8.pack(int(item.pinned)))
                stream.write(_U32.pack(item.point2D_idx))

        _atomic(
            root / _BINARY_NAMES["marker_projections"],
            write_projections,
            binary=True,
        )

    def write_header(stream, kind: str, count: int):
        stream.write(_MAGICS[kind])
        stream.write(_U32.pack(_VERSION))
        stream.write(_U64.pack(count))

    for kind, values in (
        ("image_times", extensions.image_times),
        ("point3D_frames", extensions.point3D_frames),
    ):
        if values is not None:

            def write_tags(stream, kind=kind, values=values):
                write_header(stream, kind, values.ids.size)
                for identifier, tag in zip(values.ids, values.tags, strict=True):
                    stream.write(_U64.pack(int(identifier)))
                    stream.write(_U64.pack(int(tag)))

            _atomic(root / _BINARY_NAMES[kind], write_tags, binary=True)

    if extensions.time_frames is not None:
        values = tuple(sorted(extensions.time_frames, key=lambda item: item.time_id))

        def write_times(stream):
            write_header(stream, "time_frames", len(values))
            for item in values:
                stream.write(_U64.pack(item.time_id))
                stream.write(_F64.pack(item.timestamp_seconds))
                _put_string(stream, item.sync_group)
                _put_string(stream, item.label)

        _atomic(
            root / _BINARY_NAMES["time_frames"],
            write_times,
            binary=True,
        )

    if extensions.charuco_boards is not None:
        values = tuple(sorted(extensions.charuco_boards, key=lambda item: item.board_id))

        def write_boards(stream):
            write_header(stream, "charuco_boards", len(values))
            for item in values:
                _put_board(stream, item)

        _atomic(
            root / _BINARY_NAMES["charuco_boards"],
            write_boards,
            binary=True,
        )

    if extensions.charuco_calibrations is not None:
        values = tuple(
            sorted(
                extensions.charuco_calibrations,
                key=lambda item: item.session_id,
            )
        )

        def write_calibrations(stream):
            write_header(stream, "charuco_calibrations", len(values))
            for item in values:
                _put_string(stream, item.session_id)
                _put_board(stream, item.board)
                stream.write(_I32.pack(item.camera_model_id))
                stream.write(_I32.pack(item.image_width))
                stream.write(_I32.pack(item.image_height))
                stream.write(_U64.pack(item.camera_params.size))
                _write_le_array(stream, item.camera_params, "<f8")
                stream.write(_F64.pack(item.overall_rmse_px))
                stream.write(_U64.pack(len(item.image_names)))
                for index, name in enumerate(item.image_names):
                    _put_string(stream, name)
                    stream.write(_F64.pack(item.per_image_rmse_px[index]))
                    _write_le_array(
                        stream,
                        item.per_image_cam_from_board[index],
                        "<f8",
                    )

        _atomic(
            root / _BINARY_NAMES["charuco_calibrations"],
            write_calibrations,
            binary=True,
        )


def _board_text(value: CharucoBoard) -> str:
    return (
        f"{_quoted(value.board_id)} {value.dictionary} {value.squares_x} "
        f"{value.squares_y} {_double(value.square_length)} "
        f"{_double(value.marker_length)}"
    )


def _write_text(root: Path, extensions: SparseExtensions) -> None:
    if extensions.markers is not None:
        values = tuple(sorted(extensions.markers, key=lambda item: item.marker_id))

        def write_markers(stream):
            stream.write(
                "# Marker list with one line of data per marker:\n"
                "# MARKER_ID TYPE ENABLED LABEL WX WY WZ WC00..WC22 "
                "POINT3D_ID\n"
            )
            for item in values:
                numeric = [
                    *item.world_position,
                    *item.world_covariance.reshape(-1),
                ]
                stream.write(
                    f"{item.marker_id} {item.marker_type} "
                    f"{int(item.enabled)} {_quoted(item.label)} "
                    + " ".join(_double(float(value)) for value in numeric)
                    + f" {item.point3D_id}\n"
                )

        _atomic(root / _TEXT_NAMES["markers"], write_markers, binary=False)

    if extensions.marker_projections is not None:
        values = tuple(
            sorted(
                extensions.marker_projections,
                key=lambda item: (item.marker_id, item.image_id),
            )
        )

        def write_projections(stream):
            stream.write(
                "# Marker projection list with one line per projection:\n"
                "# MARKER_ID IMAGE_ID X Y SIZE PINNED POINT2D_IDX\n"
            )
            for item in values:
                stream.write(
                    f"{item.marker_id} {item.image_id} "
                    f"{_double(float(item.xy[0]))} "
                    f"{_double(float(item.xy[1]))} {_double(item.size)} "
                    f"{int(item.pinned)} {item.point2D_idx}\n"
                )

        _atomic(
            root / _TEXT_NAMES["marker_projections"],
            write_projections,
            binary=False,
        )

    for kind, values, heading in (
        (
            "image_times",
            extensions.image_times,
            "# 4D per-time Image tags. Format: IMAGE_ID TIME_ID\n",
        ),
        (
            "point3D_frames",
            extensions.point3D_frames,
            "# 4D per-frame Point3D tags. Format: POINT3D_ID FRAME_ID\n",
        ),
    ):
        if values is not None:

            def write_tags(stream, values=values, heading=heading):
                stream.write(heading)
                for identifier, tag in zip(values.ids, values.tags, strict=True):
                    stream.write(f"{int(identifier)} {int(tag)}\n")

            _atomic(root / _TEXT_NAMES[kind], write_tags, binary=False)

    if extensions.time_frames is not None:
        values = tuple(sorted(extensions.time_frames, key=lambda item: item.time_id))

        def write_times(stream):
            stream.write(
                "# 4D time-frame metadata. Format: TIME_ID TIMESTAMP_SECONDS SYNC_GROUP LABEL\n"
            )
            for item in values:
                stream.write(
                    f"{item.time_id} {_double(item.timestamp_seconds)} "
                    f"{_quoted(item.sync_group)} {_quoted(item.label)}\n"
                )

        _atomic(
            root / _TEXT_NAMES["time_frames"],
            write_times,
            binary=False,
        )

    if extensions.charuco_boards is not None:
        values = tuple(sorted(extensions.charuco_boards, key=lambda item: item.board_id))

        def write_boards(stream):
            stream.write(
                "# ChArUco board specs. Format: BOARD_ID DICTIONARY "
                "SQUARES_X SQUARES_Y SQUARE_LENGTH MARKER_LENGTH\n"
            )
            for item in values:
                stream.write(_board_text(item) + "\n")

        _atomic(
            root / _TEXT_NAMES["charuco_boards"],
            write_boards,
            binary=False,
        )

    if extensions.charuco_calibrations is not None:
        values = tuple(
            sorted(
                extensions.charuco_calibrations,
                key=lambda item: item.session_id,
            )
        )

        def write_calibrations(stream):
            stream.write("# ChArUco calibration sessions. One line per session.\n")
            for item in values:
                fields = [
                    _quoted(item.session_id),
                    _board_text(item.board),
                    str(item.camera_model_id),
                    str(item.image_width),
                    str(item.image_height),
                    str(item.camera_params.size),
                    *(_double(float(value)) for value in item.camera_params),
                    _double(item.overall_rmse_px),
                    str(len(item.image_names)),
                ]
                for index, name in enumerate(item.image_names):
                    fields.extend(
                        [
                            _quoted(name),
                            _double(float(item.per_image_rmse_px[index])),
                            *(
                                _double(float(value))
                                for value in item.per_image_cam_from_board[index]
                            ),
                        ]
                    )
                stream.write(" ".join(fields) + "\n")

        _atomic(
            root / _TEXT_NAMES["charuco_calibrations"],
            write_calibrations,
            binary=False,
        )


def write_extended_sparse_model(value: ExtendedSparseModel, path) -> None:
    """Write the base model and exact sidecar-presence state to a clean target."""

    if not isinstance(value, ExtendedSparseModel):
        raise TypeError("value must be ExtendedSparseModel")
    _validate_reconstruction_links(value)
    _preflight_extensions(value.extensions, value.encoding)
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    present = [name for name in (*_BASE_NAMES, *_SIDECAR_NAMES) if (root / name).exists()]
    if present:
        raise ColmapAdapterError(
            "destination already contains sparse-model files: " + ", ".join(present)
        )
    if value.encoding == "binary":
        _core.write_colmap_sparse(
            value.reconstruction,
            str(root),
        )
        _write_binary(root, value.extensions)
    else:
        _core.write_colmap_txt(
            value.reconstruction,
            str(root),
        )
        _write_text(root, value.extensions)
