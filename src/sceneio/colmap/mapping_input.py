"""Versioned, repository-owned MappingInput ``PCMAPIN`` I/O."""

from __future__ import annotations

import contextlib
import mmap
import os
import struct
import tempfile
import traceback
from pathlib import Path

import numpy as np

from sceneio._camera_models import (
    CAMERA_MODEL_PARAMETER_COUNTS as _CAMERA_PARAM_COUNTS,
)

from .models import (
    UINT32_MAX,
    ColmapAdapterError,
    MappingCamera,
    MappingImage,
    MappingInput,
    MappingMatch,
)

_MAGIC = b"PCMAPIN\0"
_HEADER = struct.Struct("<8sI")
_U8 = struct.Struct("<B")
_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")
_U64 = struct.Struct("<Q")
_MAX_RECORDS = 100_000_000
_MAX_TEXT_BYTES = 64 * 1024 * 1024


class _Cursor:
    def __init__(self, owner: mmap.mmap):
        self.owner = owner
        self.size = len(owner)
        self.offset = 0

    def take(self, size: int, label: str) -> memoryview:
        if size < 0 or size > self.size - self.offset:
            raise ColmapAdapterError(f"MappingInput {label} is truncated")
        start = self.offset
        self.offset += size
        return memoryview(self.owner)[start : start + size]

    def unpack(self, layout: struct.Struct, label: str):
        if layout.size > self.size - self.offset:
            raise ColmapAdapterError(f"MappingInput {label} is truncated")
        result = layout.unpack_from(self.owner, self.offset)
        self.offset += layout.size
        return result[0] if len(result) == 1 else result

    def count(self, minimum_bytes: int, label: str) -> int:
        value = self.unpack(_U32, f"{label} count")
        if value > _MAX_RECORDS or value > (self.size - self.offset) // minimum_bytes:
            raise ColmapAdapterError(f"MappingInput {label} count exceeds the payload")
        return value

    def array(self, dtype, shape: tuple[int, ...], label: str) -> np.ndarray:
        count = int(np.prod(shape, dtype=np.uint64))
        itemsize = np.dtype(dtype).itemsize
        if count > (self.size - self.offset) // itemsize:
            raise ColmapAdapterError(f"MappingInput {label} is truncated")
        result = np.frombuffer(
            self.owner,
            dtype=dtype,
            count=count,
            offset=self.offset,
        ).reshape(shape)
        self.offset += count * itemsize
        result.setflags(write=False)
        return result


def _open_mapping(path) -> mmap.mmap:
    source = Path(path)
    try:
        stream = source.open("rb")
    except OSError as exc:
        raise ColmapAdapterError(f"cannot open MappingInput {str(source)!r}: {exc}") from exc
    try:
        if source.stat().st_size == 0:
            raise ColmapAdapterError("MappingInput file is empty")
        return mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
    except Exception:
        stream.close()
        raise
    finally:
        stream.close()


def read_mapping_input(path) -> MappingInput:
    """Read MappingInput v1/v2 using read-only mapped numeric views."""

    owner = _open_mapping(path)
    cursor = None
    cameras = []
    images = []
    matches = []
    params = None
    keypoints = None
    relative_pose = None
    pair_values = None
    try:
        cursor = _Cursor(owner)
        magic, version = cursor.unpack(_HEADER, "header")
        if magic != _MAGIC:
            raise ColmapAdapterError("MappingInput magic must be PCMAPIN\\0")
        if version not in (1, 2):
            raise ColmapAdapterError(f"MappingInput version {version} is unsupported")

        num_cameras = cursor.count(29, "camera")
        for index in range(num_cameras):
            camera_id = cursor.unpack(_U32, f"camera {index} id")
            model_id = cursor.unpack(_U32, f"camera {index} model")
            width = cursor.unpack(_U64, f"camera {index} width")
            height = cursor.unpack(_U64, f"camera {index} height")
            num_params = cursor.unpack(_U32, f"camera {index} parameter count")
            expected = (
                _CAMERA_PARAM_COUNTS[model_id]
                if model_id < len(_CAMERA_PARAM_COUNTS)
                else None
            )
            if expected is None or num_params != expected:
                raise ColmapAdapterError(
                    f"MappingInput camera {index} model/parameter count is unsupported"
                )
            params = cursor.array("<f8", (num_params,), f"camera {index} parameters")
            prior = cursor.unpack(_U8, f"camera {index} prior flag")
            if prior not in (0, 1):
                raise ColmapAdapterError(f"MappingInput camera {index} prior flag is not 0 or 1")
            cameras.append(
                MappingCamera(
                    camera_id,
                    model_id,
                    width,
                    height,
                    params,
                    bool(prior),
                )
            )

        minimum_image_bytes = 20 if version == 2 else 16
        num_images = cursor.count(minimum_image_bytes, "image")
        for index in range(num_images):
            image_id = cursor.unpack(_U32, f"image {index} id")
            camera_id = cursor.unpack(_U32, f"image {index} camera id")
            time_id = cursor.unpack(_U32, f"image {index} time id") if version == 2 else UINT32_MAX
            name_size = cursor.unpack(_U32, f"image {index} name size")
            if name_size > _MAX_TEXT_BYTES:
                raise ColmapAdapterError(f"MappingInput image {index} name exceeds its bound")
            try:
                name = bytes(cursor.take(name_size, f"image {index} name")).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ColmapAdapterError(f"MappingInput image {index} name is not UTF-8") from exc
            num_keypoints = cursor.unpack(_U32, f"image {index} keypoint count")
            keypoints = cursor.array(
                "<f4",
                (num_keypoints, 2),
                f"image {index} keypoints",
            )
            images.append(
                MappingImage(
                    image_id,
                    camera_id,
                    time_id,
                    name,
                    keypoints,
                )
            )

        num_matches = cursor.count(17, "match")
        for index in range(num_matches):
            image_id1 = cursor.unpack(_U32, f"match {index} image id 1")
            image_id2 = cursor.unpack(_U32, f"match {index} image id 2")
            config = cursor.unpack(_I32, f"match {index} config")
            has_pose = cursor.unpack(_U8, f"match {index} pose flag")
            if has_pose not in (0, 1):
                raise ColmapAdapterError(f"MappingInput match {index} pose flag is not 0 or 1")
            relative_pose = (
                cursor.array("<f8", (7,), f"match {index} relative pose") if has_pose else None
            )
            num_pairs = cursor.unpack(_U32, f"match {index} pair count")
            pair_values = cursor.array("<u4", (num_pairs, 2), f"match {index} pairs")
            matches.append(
                MappingMatch(
                    image_id1,
                    image_id2,
                    config,
                    pair_values,
                    relative_pose,
                )
            )

        if cursor.offset != cursor.size:
            raise ColmapAdapterError("MappingInput has trailing bytes after its match records")
        return MappingInput(
            version,
            tuple(cameras),
            tuple(images),
            tuple(matches),
            owner,
        )
    except Exception as exc:
        error_type = type(exc)
        message = str(exc)
        traceback.clear_frames(exc.__traceback__)
        exc.__traceback__ = None
        exc.__context__ = None
        cursor = None
        params = None
        keypoints = None
        relative_pose = None
        pair_values = None
        cameras.clear()
        images.clear()
        matches.clear()
        owner.close()
        raise error_type(message) from None


def inspect_mapping_input(path) -> dict[str, int]:
    """Return version and record counts after a full bounded wire scan."""

    record = read_mapping_input(path)
    return {
        "version": record.version,
        "num_cameras": len(record.cameras),
        "num_images": len(record.images),
        "num_matches": len(record.matches),
        "num_keypoints": sum(item.keypoints.shape[0] for item in record.images),
        "num_correspondences": sum(item.matches.shape[0] for item in record.matches),
    }


def _write_array(stream, value: np.ndarray) -> None:
    if value.size == 0:
        return
    expected = value.dtype.newbyteorder("<")
    if value.dtype == expected and value.flags.c_contiguous:
        stream.write(memoryview(value).cast("B"))
    else:
        stream.write(value.astype(expected, copy=True).tobytes())


def _u32_size(value: int, label: str) -> int:
    if value > UINT32_MAX:
        raise ColmapAdapterError(f"{label} exceeds uint32")
    return value


def write_mapping_input(value: MappingInput, path) -> None:
    """Stream a canonical MappingInput v1/v2 file to ``path``."""

    if not isinstance(value, MappingInput):
        raise TypeError("value must be a MappingInput")
    if value.version == 1 and any(image.time_id != UINT32_MAX for image in value.images):
        raise ColmapAdapterError("MappingInput v1 cannot represent image time_id values")
    for index, image in enumerate(value.images):
        try:
            encoded = image.name.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ColmapAdapterError(f"MappingInput image {index} name is not valid UTF-8") from exc
        if len(encoded) > _MAX_TEXT_BYTES:
            raise ColmapAdapterError(f"MappingInput image {index} name exceeds its bound")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(_HEADER.pack(_MAGIC, value.version))
            stream.write(_U32.pack(_u32_size(len(value.cameras), "cameras")))
            for camera in value.cameras:
                stream.write(_U32.pack(camera.camera_id))
                stream.write(_U32.pack(camera.model_id))
                stream.write(_U64.pack(camera.width))
                stream.write(_U64.pack(camera.height))
                stream.write(_U32.pack(_u32_size(camera.params.size, "camera parameters")))
                _write_array(stream, camera.params)
                stream.write(_U8.pack(int(camera.has_prior_focal_length)))

            stream.write(_U32.pack(_u32_size(len(value.images), "images")))
            for image in value.images:
                name = image.name.encode("utf-8")
                stream.write(_U32.pack(image.image_id))
                stream.write(_U32.pack(image.camera_id))
                if value.version == 2:
                    stream.write(_U32.pack(image.time_id))
                stream.write(_U32.pack(_u32_size(len(name), "image name")))
                stream.write(name)
                stream.write(
                    _U32.pack(
                        _u32_size(
                            image.keypoints.shape[0],
                            "image keypoints",
                        )
                    )
                )
                _write_array(stream, image.keypoints)

            stream.write(_U32.pack(_u32_size(len(value.matches), "matches")))
            for match in value.matches:
                stream.write(_U32.pack(match.image_id1))
                stream.write(_U32.pack(match.image_id2))
                stream.write(_I32.pack(match.config))
                stream.write(_U8.pack(int(match.relative_pose is not None)))
                if match.relative_pose is not None:
                    _write_array(stream, match.relative_pose)
                stream.write(
                    _U32.pack(
                        _u32_size(
                            match.matches.shape[0],
                            "match correspondences",
                        )
                    )
                )
                _write_array(stream, match.matches)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
        raise
