"""Benchmark specifications for the complete raster-image codec family."""

from __future__ import annotations

from bench.io_bench.fixtures.images import _img_f32, _img_u8
from bench.io_bench.model import Spec
from bench.io_bench.oracles.images import (
    OpenEXR,
    PILImage,
    _imageio_r,
    _imageio_w,
    _openexr_r,
    _openexr_w,
    _pil_r,
    _pil_w,
    iio,
)
from sceneio import _core


def build_image_specs(scale):
    side = max(1, int(1024 * scale**0.5))
    return [
        Spec(
            "png",
            lambda: _img_u8(side, side),
            _core.write_png,
            _core.read_png,
            (_pil_w("PNG") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "jpeg",
            lambda: _img_u8(side, side),
            lambda im: _core.write_jpeg(im, 95),
            _core.read_jpeg,
            (_pil_w("JPEG") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "bmp",
            lambda: _img_u8(side, side),
            _core.write_bmp,
            _core.read_bmp,
            (_pil_w("BMP") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "tga",
            lambda: _img_u8(side, side),
            _core.write_tga,
            _core.read_tga,
            (_pil_w("TGA") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "webp",
            lambda: _img_u8(side, side),
            lambda im: _core.write_webp(im, True),
            _core.read_webp,
            (_pil_w("WEBP") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "hdr",
            lambda: _img_f32(side, side),
            _core.write_hdr,
            _core.read_hdr,
            (_imageio_w(".hdr") if iio else None),
            (_imageio_r(".hdr") if iio else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "exr",
            lambda: _img_f32(side, side),
            _core.write_exr,
            _core.read_exr,
            (_openexr_w if OpenEXR else None),
            (_openexr_r if OpenEXR else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "netpbm",
            lambda: _img_u8(side, side),
            lambda im: _core.write_netpbm(im, False),
            _core.read_netpbm,
            (
                _imageio_w(".ppm")
                if iio
                else (_pil_w("PPM") if PILImage else None)
            ),
            (
                _imageio_r(".ppm")
                if iio
                else (_pil_r if PILImage else None)
            ),
            lambda rec, p: p.nbytes,
        ),
    ]


__all__ = ["build_image_specs"]
