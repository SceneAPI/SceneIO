"""Typed depth adapters layered over SceneIO's raw payload codecs.

Depth units, scale, and invalid-value conventions are not portable metadata in
PFM, PNG, or EXR.  The immutable :class:`DepthEncoding` is therefore mandatory
on every typed read, write, and inspection; no sidecar or implicit profile is
used.
"""

from __future__ import annotations

import math
import operator
from dataclasses import dataclass, replace
from numbers import Real
from pathlib import Path

from sceneio import _core
from sceneio.io._inspection import inspect_path
from sceneio.io._inspectors.model import Inspection
from sceneio.io._registry.adapters import (
    _mmap_reader,
    _mmap_selector_reader,
)
from sceneio.io.registry import FormatError, detect

_UNITS = frozenset({"meters", "millimeters", "custom", "unitless", "unknown"})
_INVALID_POLICIES = frozenset({"none", "zero", "nonfinite", "negative"})
_TYPED_DEPTH_FORMATS = frozenset({"exr", "pfm", "png"})


@dataclass(frozen=True)
class DepthEncoding:
    """External semantic contract for a raw stored-depth raster.

    ``stored_value * scale_to_meters`` converts metric encodings to meters.
    Non-metric ``unitless`` and ``unknown`` encodings use a scale of ``0.0``.
    ``channel_name`` is reserved for explicit scalar EXR channel selection and
    must be omitted for PFM and PNG.
    """

    unit: str
    scale_to_meters: float
    invalid_policy: str
    channel_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.unit, str) or self.unit not in _UNITS:
            raise ValueError(
                "DepthEncoding.unit must be "
                "meters|millimeters|custom|unitless|unknown"
            )
        if isinstance(self.scale_to_meters, bool) or not isinstance(
            self.scale_to_meters, Real
        ):
            raise TypeError("DepthEncoding.scale_to_meters must be a real number")
        scale = float(self.scale_to_meters)
        if self.unit == "meters":
            valid_scale = scale == 1.0
        elif self.unit == "millimeters":
            valid_scale = scale == 0.001
        elif self.unit == "custom":
            valid_scale = math.isfinite(scale) and scale > 0.0
        else:
            valid_scale = scale == 0.0
        if not valid_scale:
            raise ValueError(
                "DepthEncoding unit/scale_to_meters mismatch"
            )
        object.__setattr__(self, "scale_to_meters", scale)

        if (
            not isinstance(self.invalid_policy, str)
            or self.invalid_policy not in _INVALID_POLICIES
        ):
            raise ValueError(
                "DepthEncoding.invalid_policy must be "
                "none|zero|nonfinite|negative"
            )
        if self.channel_name is not None:
            if not isinstance(self.channel_name, str):
                raise TypeError("DepthEncoding.channel_name must be str or None")
            if not self.channel_name or "\0" in self.channel_name:
                raise ValueError(
                    "DepthEncoding.channel_name must be non-empty and contain no NUL"
                )
            try:
                encoded_channel_name = self.channel_name.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError(
                    "DepthEncoding.channel_name must be valid UTF-8"
                ) from None
            if len(encoded_channel_name) > 255:
                raise ValueError(
                    "DepthEncoding.channel_name must be at most 255 UTF-8 bytes"
                )


_PFM_DEPTH_READER = _mmap_selector_reader(_core.read_pfm_depth)
_PFM_DEPTH_WINDOW_READER = _mmap_selector_reader(_core.read_pfm_depth_window)
_PFM_DEPTH_INSPECTOR = _mmap_reader(_core._inspect_pfm_depth)
_PNG_DEPTH_READER = _mmap_selector_reader(_core.read_png_depth)
_EXR_DEPTH_READER = _mmap_selector_reader(_core.read_exr_depth)


def _require_encoding(encoding) -> DepthEncoding:
    if not isinstance(encoding, DepthEncoding):
        raise TypeError("encoding must be a DepthEncoding")
    return encoding


def _resolve_depth_format(path, format: str | None, *, writing: bool) -> str:
    if format is not None:
        selected = format
    elif writing:
        extension = Path(path).suffix.lower()
        selected = extension[1:] if extension else ""
    else:
        selected = detect(path)
    if selected not in _TYPED_DEPTH_FORMATS:
        operation = "write" if writing else "read"
        rendered = selected or Path(path).suffix.lower() or "<none>"
        supported = ", ".join(sorted(_TYPED_DEPTH_FORMATS))
        raise FormatError(
            f"{operation}_depth supports typed depth for {supported} "
            f"(selected {rendered!r})"
        )
    return selected


def _require_channel(encoding: DepthEncoding, format_id: str) -> None:
    if format_id == "exr":
        if encoding.channel_name is None:
            raise ValueError(
                "EXR depth requires an explicit DepthEncoding.channel_name"
            )
    elif encoding.channel_name is not None:
        raise ValueError(
            f"{format_id} depth has no named channel; "
            "DepthEncoding.channel_name must be None"
        )


def _window(value) -> tuple[int, int, int, int]:
    if isinstance(value, (str, bytes)):
        raise TypeError("window must contain four integers")
    try:
        items = tuple(value)
    except TypeError:
        raise TypeError("window must contain four integers") from None
    if len(items) != 4:
        raise ValueError("window must contain exactly four integers")
    result = []
    for item in items:
        if isinstance(item, bool):
            raise TypeError("window values must be integers, not bool")
        try:
            result.append(operator.index(item))
        except TypeError:
            raise TypeError("window values must be integers") from None
    return tuple(result)


def read_depth(
    path,
    *,
    encoding: DepthEncoding,
    format: str | None = None,
    window=None,
):
    """Read a raw depth payload into an owning, convention-tagged DepthMap.

    ``encoding`` is mandatory and values are never rescaled or scrubbed.
    ``window`` is an optional half-open
    ``(row_start, row_stop, column_start, column_stop)`` region.  It is accepted
    only when the selected payload codec provides a bounded native window read.
    """

    resolved = _resolve_depth_format(path, format, writing=False)
    selected_encoding = _require_encoding(encoding)
    _require_channel(selected_encoding, resolved)
    arguments = (
        selected_encoding.unit,
        selected_encoding.scale_to_meters,
        selected_encoding.invalid_policy,
    )
    selected_window = None if window is None else _window(window)
    try:
        if resolved == "pfm":
            if selected_window is None:
                return _PFM_DEPTH_READER(str(path), *arguments)
            return _PFM_DEPTH_WINDOW_READER(
                str(path),
                *selected_window,
                *arguments,
            )
        if selected_window is not None:
            raise FormatError(
                f"typed {resolved.upper()} depth does not support bounded "
                "pixel-window reads"
            )
        if resolved == "png":
            return _PNG_DEPTH_READER(str(path), *arguments)
        return _EXR_DEPTH_READER(
            str(path), *arguments, selected_encoding.channel_name
        )
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(
            f"reading {str(path)!r} as typed {resolved!r} depth: {exc}"
        ) from exc


def inspect_depth(
    path,
    *,
    encoding: DepthEncoding,
    format: str | None = None,
) -> Inspection:
    """Validate and inspect a typed depth payload without decoding its raster."""

    resolved = _resolve_depth_format(path, format, writing=False)
    selected_encoding = _require_encoding(encoding)
    _require_channel(selected_encoding, resolved)
    try:
        if resolved == "pfm":
            height, width, channels, little_endian, header_scale, byte_size = (
                _PFM_DEPTH_INSPECTOR(str(path))
            )
            return Inspection(
                resolved,
                "depth_map",
                byte_size,
                shape=(height, width),
                dtype="float32",
                channels=channels,
                metadata={
                    "byte_order": "little" if little_endian else "big",
                    "header_scale": header_scale,
                    "row_order": "top_to_bottom",
                    "unit": selected_encoding.unit,
                    "scale_to_meters": selected_encoding.scale_to_meters,
                    "invalid_policy": selected_encoding.invalid_policy,
                },
            )
        result = inspect_path(path, resolved, "depth_map")
        if resolved == "png":
            if result.channels != 1 or result.dtype != "uint16":
                raise ValueError(
                    "PNG depth: expected grayscale uint16 samples"
                )
            stored_dtype = "uint16"
        else:
            channel_names = result.metadata.get("channel_names")
            channel_name_encodings = result.metadata.get(
                "channel_name_encodings"
            )
            if result.channels != 1 or channel_names != (
                selected_encoding.channel_name,
            ):
                raise ValueError(
                    "EXR depth: expected exactly the explicitly selected "
                    f"channel {selected_encoding.channel_name!r}"
                )
            if channel_name_encodings != ("utf8",):
                raise ValueError(
                    "EXR depth: stored channel name is not valid UTF-8"
                )
            channel_dtypes = result.metadata.get("channel_dtypes")
            if (
                not isinstance(channel_dtypes, tuple)
                or len(channel_dtypes) != 1
            ):
                raise ValueError("EXR depth: missing scalar channel dtype")
            stored_dtype = channel_dtypes[0]
        return replace(
            result,
            dtype="float32",
            metadata={
                **result.metadata,
                "stored_dtype": stored_dtype,
                "decoded_dtype": "float32",
                "row_order": "top_to_bottom",
                "unit": selected_encoding.unit,
                "scale_to_meters": selected_encoding.scale_to_meters,
                "invalid_policy": selected_encoding.invalid_policy,
                **(
                    {"channel_name": selected_encoding.channel_name}
                    if resolved == "exr"
                    else {}
                ),
            },
        )
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(
            f"inspecting {str(path)!r} as typed {resolved!r} depth: {exc}"
        ) from exc


def write_depth(
    depth,
    path,
    *,
    encoding: DepthEncoding,
    format: str | None = None,
) -> None:
    """Write a DepthMap whose metadata exactly matches ``encoding``.

    The payload format does not carry the complete semantic encoding, so it
    remains an external contract and must be supplied again on read. PNG also
    requires every stored float32 value to be exactly representable as uint16.
    """

    resolved = _resolve_depth_format(path, format, writing=True)
    selected_encoding = _require_encoding(encoding)
    _require_channel(selected_encoding, resolved)
    if not isinstance(depth, _core.DepthMap):
        raise TypeError("depth must be a DepthMap")
    request = (
        depth,
        selected_encoding.unit,
        selected_encoding.scale_to_meters,
        selected_encoding.invalid_policy,
        *(
            (selected_encoding.channel_name,)
            if resolved == "exr"
            else ()
        ),
    )
    encoders = {
        "pfm": _core._write_pfm_depth_request,
        "png": _core._write_png_depth_request,
        "exr": _core._write_exr_depth_request,
    }
    try:
        _core._write_to_file(
            encoders[resolved],
            request,
            str(path),
        )
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError(
            f"writing {str(path)!r} as typed {resolved!r} depth: {exc}"
        ) from exc


__all__ = [
    "DepthEncoding",
    "inspect_depth",
    "read_depth",
    "write_depth",
]
