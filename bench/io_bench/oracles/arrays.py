"""Independent or library-backed oracles for array-family codecs."""

from __future__ import annotations

import io
import struct

import numpy as np

try:
    from safetensors import safe_open as safetensors_open
    from safetensors.numpy import load as safetensors_load
    from safetensors.numpy import load_file as safetensors_load_file
    from safetensors.numpy import save as safetensors_save
    from safetensors.numpy import save_file as safetensors_save_file
except Exception:
    safetensors_open = None
    safetensors_load = None
    safetensors_load_file = None
    safetensors_save = None
    safetensors_save_file = None


def _np_w(a):
    b = io.BytesIO()
    np.save(b, a)
    return b.getvalue()


def _np_r(d):
    return np.load(io.BytesIO(d))


def _save_npz_oracle(arrays):
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    return buffer.getvalue()


def _load_npz_oracle(data):
    with np.load(io.BytesIO(data)) as archive:
        return {
            name: np.array(archive[name], copy=True)
            for name in archive.files
        }


def _dmb_oracle_write(values):
    values = np.asarray(values, dtype=np.float32)
    height, width = values.shape
    return (
        struct.pack("<4i", 1, height, width, 1)
        + values.astype("<f4", copy=False).tobytes()
    )


def _dmb_oracle_read(data):
    image_type, height, width, channels = struct.unpack_from("<4i", data)
    if image_type != 1 or channels != 1:
        raise ValueError("unsupported DMB header")
    expected = 16 + height * width * 4
    if height < 1 or width < 1 or len(data) != expected:
        raise ValueError("invalid DMB payload")
    return np.frombuffer(data, dtype="<f4", offset=16).reshape(height, width)


__all__ = [
    "_dmb_oracle_read",
    "_dmb_oracle_write",
    "_load_npz_oracle",
    "_np_r",
    "_np_w",
    "_save_npz_oracle",
    "safetensors_load",
    "safetensors_load_file",
    "safetensors_open",
    "safetensors_save",
    "safetensors_save_file",
]
