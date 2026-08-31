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

from sceneio import camera_intrinsics, feature_set
from sceneio._camera_models import (
    CAMERA_MODEL_PARAMETER_COUNTS as _CAMERA_PARAM_COUNTS,
)
from sceneio._data.features import CorrespondenceGraph, PairCorrespondences
from sceneio._data.transforms import SE3
from sceneio.errors import ContractViolation

from .models import (
    UINT32_MAX,
    ColmapAdapterError,
    MappingInput,
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
    cameras = {}
    camera_priors = {}
    image_ids = {}
    image_camera_ids = {}
    image_time_ids = {}
    features = {}
    pairs = {}
    configurations = {}
    relative_poses = {}
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
            if camera_id in cameras:
                raise ColmapAdapterError("MappingInput camera ids must be unique")
            cameras[camera_id] = camera_intrinsics(
                model_id,
                width,
                height,
                params,
            )
            camera_priors[camera_id] = bool(prior)

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
            if image_id in image_ids.values() or name in image_ids:
                raise ColmapAdapterError(
                    "MappingInput image ids and names must be unique"
                )
            image_ids[name] = image_id
            image_camera_ids[name] = camera_id
            image_time_ids[name] = time_id
            features[name] = feature_set(keypoints)

        image_names = {image_id: name for name, image_id in image_ids.items()}

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
            if image_id1 not in image_names or image_id2 not in image_names:
                raise ColmapAdapterError(
                    "MappingInput matches must reference declared images"
                )
            key = (image_names[image_id1], image_names[image_id2])
            if key[0] == key[1] or frozenset(key) in {
                frozenset(existing) for existing in pairs
            }:
                raise ColmapAdapterError("MappingInput match pairs must be unique")
            pairs[key] = PairCorrespondences.from_indices(pair_values)
            configurations[key] = config
            if relative_pose is not None:
                relative_poses[key] = SE3.from_quaternion_wxyz(
                    relative_pose[[3, 0, 1, 2]],
                    relative_pose[4:7],
                    convention="opencv_second_from_first",
                )

        if cursor.offset != cursor.size:
            raise ColmapAdapterError("MappingInput has trailing bytes after its match records")
        graph = CorrespondenceGraph(
            features,
            pairs,
            configurations=configurations,
            relative_poses=relative_poses,
        )
        return MappingInput(
            version=version,
            cameras=cameras,
            camera_prior_focal_length=camera_priors,
            image_ids=image_ids,
            image_camera_ids=image_camera_ids,
            image_time_ids=image_time_ids,
            correspondences=graph,
            _owner=owner,
        )
    except ContractViolation as exc:
        message = str(exc)
        cursor = None
        params = None
        keypoints = None
        relative_pose = None
        pair_values = None
        cameras.clear()
        camera_priors.clear()
        image_ids.clear()
        image_camera_ids.clear()
        image_time_ids.clear()
        features.clear()
        pairs.clear()
        configurations.clear()
        relative_poses.clear()
        owner.close()
        raise ColmapAdapterError(f"invalid MappingInput semantics: {message}") from None
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
        camera_priors.clear()
        image_ids.clear()
        image_camera_ids.clear()
        image_time_ids.clear()
        features.clear()
        pairs.clear()
        configurations.clear()
        relative_poses.clear()
        owner.close()
        raise error_type(message) from None


def inspect_mapping_input(path) -> dict[str, int]:
    """Return version and record counts after a full bounded wire scan."""

    record = read_mapping_input(path)
    return {
        "version": record.version,
        "num_cameras": len(record.cameras),
        "num_images": len(record.image_ids),
        "num_matches": len(record.correspondences.pairs),
        "num_keypoints": sum(
            len(item) for item in record.correspondences.features.values()
        ),
        "num_correspondences": sum(
            len(item) for item in record.correspondences.pairs.values()
        ),
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
    if value.version == 1 and any(
        time_id != UINT32_MAX for time_id in value.image_time_ids.values()
    ):
        raise ColmapAdapterError("MappingInput v1 cannot represent image time_id values")
    if value.correspondences.verified_pairs:
        raise ColmapAdapterError("MappingInput cannot encode verified correspondences")
    if value.correspondences.source_metadata:
        raise ColmapAdapterError("MappingInput cannot encode correspondence source metadata")
    for index, name in enumerate(value.image_ids):
        try:
            encoded = name.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ColmapAdapterError(f"MappingInput image {index} name is not valid UTF-8") from exc
        if len(encoded) > _MAX_TEXT_BYTES:
            raise ColmapAdapterError(f"MappingInput image {index} name exceeds its bound")
        features = value.correspondences.features[name]
        if features.keypoints.shape[1:] != (2,):
            raise ColmapAdapterError("MappingInput keypoints must have shape (N, 2)")
        if (
            features.descriptors is not None
            or features.scores is not None
            or features.keypoint_colors is not None
            or features.quality is not None
        ):
            raise ColmapAdapterError(
                "MappingInput cannot encode descriptors, scores, colors, or quality"
            )
    for _pair, correspondences in value.correspondences.pairs.items():
        if correspondences.mode != "indexed" or correspondences.indices is None:
            raise ColmapAdapterError("MappingInput requires indexed correspondences")
        if correspondences.scores is not None or correspondences.geometry is not None:
            raise ColmapAdapterError(
                "MappingInput cannot encode match scores or two-view matrices"
            )
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
            for camera_id, camera in value.cameras.items():
                stream.write(_U32.pack(camera_id))
                stream.write(_U32.pack(camera.model_id))
                stream.write(_U64.pack(camera.width))
                stream.write(_U64.pack(camera.height))
                stream.write(_U32.pack(_u32_size(camera.params.size, "camera parameters")))
                _write_array(stream, camera.params)
                stream.write(
                    _U8.pack(int(value.camera_prior_focal_length[camera_id]))
                )

            stream.write(_U32.pack(_u32_size(len(value.image_ids), "images")))
            for image_name, image_id in value.image_ids.items():
                name = image_name.encode("utf-8")
                stream.write(_U32.pack(image_id))
                stream.write(_U32.pack(value.image_camera_ids[image_name]))
                if value.version == 2:
                    stream.write(_U32.pack(value.image_time_ids[image_name]))
                stream.write(_U32.pack(_u32_size(len(name), "image name")))
                stream.write(name)
                features = value.correspondences.features[image_name]
                stream.write(
                    _U32.pack(
                        _u32_size(
                            features.keypoints.shape[0],
                            "image keypoints",
                        )
                    )
                )
                _write_array(stream, features.keypoints)

            stream.write(
                _U32.pack(_u32_size(len(value.correspondences.pairs), "matches"))
            )
            for pair, correspondences in value.correspondences.pairs.items():
                stream.write(_U32.pack(value.image_ids[pair[0]]))
                stream.write(_U32.pack(value.image_ids[pair[1]]))
                stream.write(_I32.pack(value.correspondences.configurations.get(pair, 0)))
                relative_pose = value.correspondences.relative_poses.get(pair)
                stream.write(_U8.pack(int(relative_pose is not None)))
                if relative_pose is not None:
                    quaternion = relative_pose.to_quaternion_wxyz()
                    wire_pose = np.concatenate(
                        (quaternion[1:4], quaternion[0:1], relative_pose.translation)
                    )
                    _write_array(stream, wire_pose)
                assert correspondences.indices is not None
                stream.write(
                    _U32.pack(
                        _u32_size(
                            correspondences.indices.shape[0],
                            "match correspondences",
                        )
                    )
                )
                _write_array(stream, correspondences.indices)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
        raise
