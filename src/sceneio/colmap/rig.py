"""Strict reader/writer for COLMAP rig configuration JSON."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np

from .models import ColmapAdapterError, RigConfigCamera, RigConfiguration

_MAX_JSON_BYTES = 64 * 1024 * 1024
_MODEL_PARAM_COUNTS = {
    "SIMPLE_PINHOLE": 3,
    "PINHOLE": 4,
    "SIMPLE_RADIAL": 4,
    "RADIAL": 5,
    "OPENCV": 8,
    "OPENCV_FISHEYE": 8,
    "FULL_OPENCV": 12,
    "FOV": 5,
    "SIMPLE_RADIAL_FISHEYE": 4,
    "RADIAL_FISHEYE": 5,
    "THIN_PRISM_FISHEYE": 12,
    "RAD_TAN_THIN_PRISM_FISHEYE": 16,
    "SIMPLE_DIVISION": 4,
    "DIVISION": 5,
    "SIMPLE_FISHEYE": 3,
    "FISHEYE": 4,
    "EUCM": 6,
    "EQUIRECTANGULAR": 2,
}
_CAMERA_KEYS = {
    "image_prefix",
    "ref_sensor",
    "cam_from_rig_rotation",
    "cam_from_rig_translation",
    "camera_model_name",
    "camera_params",
}


def _number_array(value, size: int, label: str) -> np.ndarray:
    if (
        not isinstance(value, list)
        or len(value) != size
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise ColmapAdapterError(f"{label} must contain exactly {size} numbers")
    result = np.asarray(value, dtype=np.float64)
    if not bool(np.all(np.isfinite(result))):
        raise ColmapAdapterError(f"{label} must contain only finite values")
    return result


def read_rig_config(path) -> tuple[RigConfiguration, ...]:
    """Read the portable JSON accepted by COLMAP's ``ReadRigConfig``."""

    source = Path(path)
    try:
        if source.stat().st_size > _MAX_JSON_BYTES:
            raise ColmapAdapterError("rig config exceeds 64 MiB")
        document = json.loads(source.read_text(encoding="utf-8"))
    except ColmapAdapterError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ColmapAdapterError(f"cannot read rig config: {exc}") from exc
    if not isinstance(document, list):
        raise ColmapAdapterError("rig config root must be an array")
    result = []
    for rig_index, rig in enumerate(document):
        if not isinstance(rig, dict) or set(rig) != {"cameras"}:
            raise ColmapAdapterError(f"rig {rig_index} must contain only a cameras array")
        if not isinstance(rig["cameras"], list):
            raise ColmapAdapterError(f"rig {rig_index} cameras must be an array")
        cameras = []
        for camera_index, camera in enumerate(rig["cameras"]):
            label = f"rig {rig_index} camera {camera_index}"
            if not isinstance(camera, dict) or not set(camera) <= _CAMERA_KEYS:
                raise ColmapAdapterError(f"{label} contains unsupported fields")
            image_prefix = camera.get("image_prefix")
            if not isinstance(image_prefix, str):
                raise ColmapAdapterError(f"{label} image_prefix must be text")
            ref_sensor = camera.get("ref_sensor", False)
            if not isinstance(ref_sensor, bool):
                raise ColmapAdapterError(f"{label} ref_sensor must be boolean")
            rotation = camera.get("cam_from_rig_rotation")
            translation = camera.get("cam_from_rig_translation")
            if (rotation is None) != (translation is None):
                raise ColmapAdapterError(f"{label} rotation and translation must occur together")
            pose = None
            if rotation is not None:
                pose = np.concatenate(
                    (
                        _number_array(rotation, 4, f"{label} rotation"),
                        _number_array(translation, 3, f"{label} translation"),
                    )
                )
            model = camera.get("camera_model_name")
            params_value = camera.get("camera_params")
            if (model is None) != (params_value is None):
                raise ColmapAdapterError(f"{label} model and parameters must occur together")
            params = None
            if model is not None:
                if not isinstance(model, str) or model not in _MODEL_PARAM_COUNTS:
                    raise ColmapAdapterError(f"{label} camera model is unsupported")
                params = _number_array(
                    params_value,
                    _MODEL_PARAM_COUNTS[model],
                    f"{label} camera parameters",
                )
            cameras.append(
                RigConfigCamera(
                    image_prefix,
                    ref_sensor,
                    pose,
                    model,
                    params,
                )
            )
        result.append(RigConfiguration(tuple(cameras)))
    return tuple(result)


def write_rig_config(value: tuple[RigConfiguration, ...], path) -> None:
    """Write canonical UTF-8 rig configuration JSON atomically."""

    if any(not isinstance(rig, RigConfiguration) for rig in value):
        raise TypeError("value must contain RigConfiguration records")
    document = []
    for rig in value:
        cameras = []
        for camera in rig.cameras:
            item = {"image_prefix": camera.image_prefix}
            if camera.ref_sensor:
                item["ref_sensor"] = True
            if camera.cam_from_rig is not None:
                item["cam_from_rig_rotation"] = camera.cam_from_rig[:4].tolist()
                item["cam_from_rig_translation"] = camera.cam_from_rig[4:].tolist()
            if camera.camera_model_name is not None:
                item["camera_model_name"] = camera.camera_model_name
                item["camera_params"] = camera.camera_params.tolist()
            cameras.append(item)
        document.append({"cameras": cameras})
    payload = (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
