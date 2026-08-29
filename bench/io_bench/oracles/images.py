"""Independent or library-backed oracles for raster-image codecs."""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import numpy as np

try:
    from PIL import Image as PILImage
except Exception:
    PILImage = None
try:
    import imageio.v3 as iio
except Exception:
    iio = None
try:
    import OpenEXR
except Exception:
    OpenEXR = None


def _pil_w(mode):
    def enc(a):
        b = io.BytesIO()
        PILImage.fromarray(a).save(
            b, mode, lossless=True
        ) if mode == "WEBP" else PILImage.fromarray(a).save(b, mode)
        return b.getvalue()

    return enc


def _pil_r(data):
    return np.asarray(PILImage.open(io.BytesIO(data)))


def _imageio_w(extension):
    return lambda array: iio.imwrite(
        "<bytes>",
        array,
        extension=extension,
    )


def _imageio_r(extension):
    return lambda data: iio.imread(data, extension=extension)


def _openexr_w(array):
    fd, path = tempfile.mkstemp(suffix=".exr")
    os.close(fd)
    try:
        channels = {
            channel: np.ascontiguousarray(array[:, :, index])
            for index, channel in enumerate("RGB")
        }
        with OpenEXR.File(
            {
                "compression": OpenEXR.ZIP_COMPRESSION,
                "type": OpenEXR.scanlineimage,
            },
            channels,
        ) as output:
            output.write(path)
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _openexr_r(data):
    fd, path = tempfile.mkstemp(suffix=".exr")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        with OpenEXR.File(path) as source:
            return {
                key: np.asarray(value.pixels)
                for key, value in source.parts[0].channels.items()
            }
    finally:
        os.remove(path)


__all__ = [
    "OpenEXR",
    "PILImage",
    "_imageio_r",
    "_imageio_w",
    "_openexr_r",
    "_openexr_w",
    "_pil_r",
    "_pil_w",
    "iio",
]
