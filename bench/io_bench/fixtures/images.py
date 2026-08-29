"""Deterministic fixtures for raster-image benchmark codecs."""

from __future__ import annotations

import numpy as np

from sceneio import _core


def _img_u8(h, w):
    a = np.random.default_rng(0).integers(
        0,
        256,
        (h, w, 3),
        dtype=np.uint8,
    )
    return _core.image(a, color_space="srgb"), a


def _img_f32(h, w):
    a = (
        np.random.default_rng(0).random(
            (h, w, 3),
            dtype=np.float32,
        )
        * 10.0
    ).astype(np.float32)
    return _core.image(a, color_space="linear"), a


def _img_webp_palette(h, w):
    palette = np.array(
        [
            [0, 0, 0],
            [255, 255, 255],
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
            [255, 0, 255],
            [0, 255, 255],
        ],
        dtype=np.uint8,
    )
    yy, xx = np.indices((h, w))
    a = palette[((xx // 7) + (yy // 11)) % len(palette)]
    return _core.image(a, color_space="srgb"), a


__all__ = ["_img_f32", "_img_u8", "_img_webp_palette"]
