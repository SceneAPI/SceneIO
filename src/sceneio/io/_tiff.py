"""Bounded computer-vision TIFF adapter backed by upstream ``tifffile``.

The provider handles classic TIFF and BigTIFF directly from file paths.
SceneIO intentionally supports one unambiguous series containing either one
grayscale/RGB/RGBA image, one boolean mask, or a grayscale page/volume stack.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.data import Mask
from sceneio.io._inspectors.model import ArrayInspection, Inspection

_IMAGE_DTYPES = frozenset({"uint8", "uint16", "float32"})
_STACK_DTYPES = frozenset({"bool", "uint8", "uint16", "float32"})
_STACK_AXES = frozenset({"CYX", "IYX", "QYX", "TYX", "ZYX"})


def _require_tifffile():
    try:
        import tifffile
    except ModuleNotFoundError:
        raise RuntimeError(
            "TIFF support requires the optional dependency; "
            "install sceneio[tiff]"
        ) from None
    return tifffile


def _native_c_array(value: object, context: str) -> np.ndarray:
    array = np.asarray(value)
    if not array.dtype.isnative:
        array = array.byteswap().view(array.dtype.newbyteorder("="))
    if array.flags.c_contiguous:
        return array
    return np.ascontiguousarray(array)


def _validate_file_layout(tiff):
    if len(tiff.series) != 1:
        raise ValueError("TIFF: exactly one image series is supported")
    series = tiff.series[0]
    if len(series.levels) != 1:
        raise ValueError("TIFF: pyramidal image series are unsupported")
    axes = str(series.axes)
    shape = tuple(int(value) for value in series.shape)
    dtype = np.dtype(series.dtype)
    if dtype.fields is not None or dtype.subdtype is not None:
        raise ValueError("TIFF: structured and subarray dtypes are unsupported")
    if not series.pages:
        raise ValueError("TIFF: image series has no pages")
    for page in series.pages:
        orientation = page.tags.get("Orientation")
        if orientation is not None and int(orientation.value) != 1:
            raise ValueError("TIFF: only top-left orientation is supported")
        planar = page.planarconfig
        if planar is not None and int(planar) != 1:
            raise ValueError("TIFF: planar-separate samples are unsupported")
    if axes == "YX":
        if dtype.name not in _STACK_DTYPES:
            raise ValueError(f"TIFF image: unsupported dtype {dtype.name!r}")
        kind = "mask" if dtype.name == "bool" else "image"
        channels = 1
    elif axes in {"YXS", "YXC"} and len(shape) == 3 and shape[-1] in {3, 4}:
        if dtype.name not in _IMAGE_DTYPES:
            raise ValueError(f"TIFF image: unsupported dtype {dtype.name!r}")
        kind = "image"
        channels = shape[-1]
    elif axes in _STACK_AXES and len(shape) == 3:
        if dtype.name not in _STACK_DTYPES:
            raise ValueError(f"TIFF stack: unsupported dtype {dtype.name!r}")
        kind = "stack"
        channels = 1
    else:
        raise ValueError(
            f"TIFF: unsupported or ambiguous axes {axes!r} and shape {shape!r}"
        )
    return series, axes, shape, dtype, kind, channels


def _image_metadata(series, channels: int) -> tuple[str, str]:
    page = series.pages[0]
    photometric = int(page.photometric)
    if channels == 1:
        if photometric not in {0, 1}:
            raise ValueError("TIFF image: grayscale samples require min-is-black/white")
        return "gray", "none"
    if photometric != 2:
        raise ValueError("TIFF image: RGB samples require RGB photometric data")
    if channels == 3:
        return "srgb", "none"
    extras = tuple(int(value) for value in page.extrasamples)
    if extras == (1,):
        return "srgb", "premultiplied"
    if extras == (2,):
        return "srgb", "straight"
    raise ValueError(
        "TIFF image: RGBA samples require associated or unassociated alpha"
    )


def read_tiff(path: str | Path):
    """Read one bounded CV TIFF series."""

    tifffile = _require_tifffile()
    with tifffile.TiffFile(path) as tiff:
        series, axes, _shape, _dtype, kind, channels = _validate_file_layout(tiff)
        if kind == "image":
            color_space, alpha_mode = _image_metadata(series, channels)
        decoded = _native_c_array(series.asarray(), "TIFF")
    if kind == "mask":
        return Mask(decoded)
    if kind == "stack":
        return _core.tensor_dict({"pages": decoded}, attrs={"axes": axes})
    return _core.image(
        decoded,
        color_space=color_space,
        alpha_mode=alpha_mode,
    )


def _image_write_args(image) -> tuple[np.ndarray, dict[str, object]]:
    pixels = _native_c_array(image.pixels, "TIFF image")
    if pixels.dtype.name not in _IMAGE_DTYPES:
        raise ValueError(
            f"TIFF image: unsupported dtype {pixels.dtype.name!r}"
        )
    channels = 1 if pixels.ndim == 2 else pixels.shape[-1]
    expected_maxval = {
        "uint8": 255,
        "uint16": 65535,
        "float32": 0,
    }[pixels.dtype.name]
    if image.maxval != expected_maxval:
        raise ValueError(
            "TIFF image: only the dtype's full-range maxval is representable"
        )
    if channels == 1:
        if image.color_space != "gray" or image.alpha_mode != "none":
            raise ValueError(
                "TIFF image: grayscale requires gray color and no alpha"
            )
        return pixels, {"photometric": "minisblack"}
    if image.color_space != "srgb":
        raise ValueError("TIFF image: RGB/RGBA requires srgb color")
    if channels == 3:
        if image.alpha_mode != "none":
            raise ValueError("TIFF image: RGB requires no alpha")
        return pixels, {"photometric": "rgb"}
    if channels == 4 and image.alpha_mode in {"straight", "premultiplied"}:
        alpha = "unassalpha" if image.alpha_mode == "straight" else "assocalpha"
        return pixels, {"photometric": "rgb", "extrasamples": (alpha,)}
    raise ValueError(
        "TIFF image: RGBA requires straight or premultiplied alpha"
    )


def _stack_write_args(tensors) -> tuple[np.ndarray, dict[str, object]]:
    if tuple(tensors.keys()) != ("pages",):
        raise ValueError("TIFF stack: TensorDict must contain only 'pages'")
    attrs = dict(tensors.attrs)
    if set(attrs) != {"axes"} or attrs["axes"] not in _STACK_AXES:
        raise ValueError(
            "TIFF stack: attrs must contain one supported 'axes' value"
        )
    array = _native_c_array(tensors["pages"], "TIFF stack")
    if array.ndim != 3 or array.dtype.name not in _STACK_DTYPES:
        raise ValueError(
            "TIFF stack: pages must be a rank-3 bool/uint8/uint16/float32 array"
        )
    return array, {
        "photometric": "minisblack",
        "metadata": {"axes": attrs["axes"]},
    }


def write_tiff(
    value,
    path: str | Path,
    *,
    bigtiff: bool | None = None,
) -> None:
    """Write one Image, Mask, or bounded grayscale TensorDict stack."""

    if isinstance(value, _core.Image):
        array, kwargs = _image_write_args(value)
    elif isinstance(value, Mask):
        array = _native_c_array(value.mask, "TIFF mask")
        kwargs = {"photometric": "minisblack"}
    elif isinstance(value, _core.TensorDict):
        array, kwargs = _stack_write_args(value)
    else:
        raise TypeError("TIFF: expected an Image, Mask, or TensorDict stack")

    tifffile = _require_tifffile()
    destination = Path(path)
    destination.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        tifffile.imwrite(
            temporary,
            array,
            bigtiff=bigtiff,
            software="SceneIO",
            **kwargs,
        )
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def inspect_tiff(path: str | Path) -> Inspection:
    """Inspect bounded TIFF metadata without decoding sample payloads."""

    tifffile = _require_tifffile()
    source = Path(path)
    with tifffile.TiffFile(source) as tiff:
        series, axes, shape, dtype, kind, channels = _validate_file_layout(tiff)
        if kind == "image":
            _image_metadata(series, channels)
        page_count = len(series.pages)
        bigtiff = bool(tiff.is_bigtiff)
    if kind == "stack":
        return Inspection(
            format="tiff",
            datatype="image_stack",
            byte_size=source.stat().st_size,
            shape=shape,
            dtype=dtype.name,
            count=shape[0],
            channels=1,
            arrays=(ArrayInspection("pages", shape, dtype.name),),
            metadata={
                "axes": axes,
                "bigtiff": bigtiff,
                "page_count": page_count,
            },
        )
    return Inspection(
        format="tiff",
        datatype="mask" if kind == "mask" else "image",
        byte_size=source.stat().st_size,
        shape=shape,
        dtype=dtype.name,
        channels=channels,
        metadata={
            "axes": axes,
            "bigtiff": bigtiff,
            "page_count": page_count,
        },
    )


__all__ = ["inspect_tiff", "read_tiff", "write_tiff"]
