"""Bounded UsdGeomPoints mapping over the qualified TinyUSDZ provider."""

from __future__ import annotations

import re

import numpy as np

from sceneio import _core
from sceneio.io._usd import geometry

_DECLARATION = re.compile(
    r"^ {4}(?:(?:custom|uniform)\s+)*"
    r"(?P<type>rel|[A-Za-z_][A-Za-z0-9_]*\[\]|"
    r"[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_:.]*)\s*=",
    re.MULTILINE,
)
_TIME_SAMPLES = re.compile(
    r"^ {4}(?:(?:custom|uniform)\s+)*"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\[\])?\s+"
    r"[A-Za-z_][A-Za-z0-9_:]*\.timeSamples\s*=",
    re.MULTILINE,
)
_METADATA_OPEN = re.compile(r"\s*\(")
_INTERPOLATION = re.compile(r'\binterpolation\s*=\s*"([^"]+)"')
_NONFINITE = re.compile(
    r"(?i)(?<![A-Za-z])(?:[+-]?(?:nan|inf(?:inity)?))(?![A-Za-z])"
)
POINT_PROPERTIES = frozenset(
    {
        "points",
        "normals",
        "primvars:normals",
        "primvars:normals:indices",
        "widths",
        "primvars:widths",
        "primvars:widths:indices",
        "ids",
        "velocities",
        "accelerations",
        "primvars:displayColor",
        "primvars:displayColor:indices",
        "primvars:displayOpacity",
        "primvars:displayOpacity:indices",
        "extent",
    }
)


def property_names(prim, *, text: str | None = None) -> set[str]:
    """Return directly authored property names from provider-normalized text."""

    if text is None:
        text = prim.to_string()
    return {
        match.group("name").removesuffix(".timeSamples")
        for match in _DECLARATION.finditer(text)
    }


def has_time_samples(prim, *, text: str | None = None) -> bool:
    """Report value samples without using TinyUSDZ's missing Points binding."""

    if text is None:
        text = prim.to_string()
    return _TIME_SAMPLES.search(text) is not None


def _declaration(
    prim,
    text: str,
    name: str,
    expected_type: str,
) -> int:
    for match in _DECLARATION.finditer(text):
        if match.group("name") != name:
            continue
        actual_type = match.group("type")
        if actual_type != expected_type:
            raise ValueError(
                f"USD points {prim.name!r}: {name!r} must have type "
                f"{expected_type}, not {actual_type}"
            )
        return match.end()
    raise ValueError(f"USD points {prim.name!r}: missing {name!r}")


def _array_span(
    prim,
    text: str,
    name: str,
    expected_type: str,
) -> tuple[int, int, str | None]:
    start = _declaration(prim, text, name, expected_type)
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] != "[":
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} must be a static array"
        )
    end = text.find("]", start + 1)
    if end < 0:
        raise ValueError(
            f"USD points {prim.name!r}: unterminated {name!r} array"
        )
    interpolation = None
    opening = _METADATA_OPEN.match(text, end + 1)
    if opening is not None:
        closing = text.find("\n    )", opening.end())
        if closing < 0:
            raise ValueError(
                f"USD points {prim.name!r}: invalid {name!r} metadata"
            )
        match = _INTERPOLATION.search(text, opening.end(), closing)
        if match is not None:
            interpolation = match.group(1)
    return start, end, interpolation


def _array_text(
    prim,
    text: str,
    name: str,
    expected_type: str,
) -> tuple[str, str | None]:
    start, end, interpolation = _array_span(
        prim,
        text,
        name,
        expected_type,
    )
    return text[start : end + 1], interpolation


def _array_count(
    prim,
    text: str,
    name: str,
    expected_type: str,
    *,
    width: int,
) -> tuple[int, str | None]:
    """Count provider-normalized array rows without materializing values."""

    start, end, interpolation = _array_span(
        prim,
        text,
        name,
        expected_type,
    )
    cursor = start + 1
    while cursor < end and text[cursor].isspace():
        cursor += 1
    if cursor == end:
        return 0, interpolation
    if _NONFINITE.search(text, cursor, end) is not None:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} must be finite"
        )
    if width == 1:
        return text.count(",", cursor, end) + 1, interpolation
    rows = text.count("(", cursor, end)
    if rows != text.count(")", cursor, end):
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} has incomplete rows"
        )
    return rows, interpolation


def _parse_array(
    prim,
    text: str,
    name: str,
    expected_type: str,
    dtype: np.dtype,
    *,
    width: int,
) -> tuple[np.ndarray, str | None]:
    source, interpolation = _array_text(prim, text, name, expected_type)
    normalized = source.translate(str.maketrans("[](),", "     "))
    try:
        values = (
            np.empty(0, dtype=dtype)
            if not normalized or normalized.isspace()
            else np.fromstring(normalized, dtype=dtype, sep=" ")
        )
    except ValueError:
        raise ValueError(
            f"USD points {prim.name!r}: invalid numeric value in {name!r}"
        ) from None
    if len(values) % width:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} has incomplete rows"
        )
    if width > 1:
        values = values.reshape(-1, width)
    return values, interpolation


def _typed_primvar_data(
    prim,
    name: str,
    dtype: np.dtype,
    *,
    text: str,
    expected_type: str,
    width: int,
    count: int,
    properties: set[str],
    default_interpolation: str = "constant",
) -> tuple[np.ndarray, str, np.ndarray | None]:
    _validate_primvar_metadata(prim, name, text=text)
    attribute = prim.get_attribute(name)
    if attribute is None:
        raise ValueError(f"USD points {prim.name!r}: missing {name!r}")
    if str(attribute.type_name) != expected_type:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} must have type "
            f"{expected_type}, not {attribute.type_name}"
        )
    if prim.get_attribute_timesamples(name):
        raise ValueError(
            f"USD points {prim.name!r}: time-sampled {name!r} is unsupported"
        )
    values = np.asarray(attribute.value)
    if values.dtype != dtype:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} must have dtype {dtype.name}"
        )
    expected_shape = (len(values),) if width == 1 else (len(values), width)
    if values.shape != expected_shape:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} has invalid shape"
        )
    if values.size and not np.isfinite(values).all():
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} must be finite"
        )
    if name == "primvars:widths" and np.any(values < 0):
        raise ValueError(f"USD points {prim.name!r}: widths must be nonnegative")
    if name == "primvars:displayOpacity" and (
        np.any(values < 0) or np.any(values > 1)
    ):
        raise ValueError(
            f"USD points {prim.name!r}: display opacity must be in [0, 1]"
        )
    domain = (
        prim.get_attribute_metadata(name, "interpolation")
        or default_interpolation
    )
    if domain not in {"constant", "vertex", "varying"}:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} interpolation must be "
            "constant, vertex, or varying"
    )
    expected = 1 if domain == "constant" else count
    indices_name = f"{name}:indices"
    indices = None
    if indices_name in properties:
        indices_attribute = prim.get_attribute(indices_name)
        if indices_attribute is None:
            raise ValueError(
                f"USD points {prim.name!r}: missing {indices_name!r}"
            )
        if prim.get_attribute_timesamples(indices_name):
            raise ValueError(
                f"USD points {prim.name!r}: time-sampled "
                f"{indices_name!r} is unsupported"
            )
        if str(indices_attribute.type_name) != "int[]":
            raise ValueError(
                f"USD points {prim.name!r}: {indices_name!r} must have "
                f"type int[], not {indices_attribute.type_name}"
            )
        indices = np.asarray(indices_attribute.value)
        if indices.dtype != np.dtype(np.int32) or indices.shape != (expected,):
            raise ValueError(
                f"USD points {prim.name!r}: {indices_name!r} must be "
                f"({expected},) int32"
            )
        if indices.size and (
            int(indices.min()) < 0 or int(indices.max()) >= len(values)
        ):
            raise ValueError(
                f"USD points {prim.name!r}: {indices_name!r} is out of range"
            )
    elif len(values) != expected:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} {domain} count "
            "does not match points"
        )
    return values, domain, indices


def _typed_primvar(
    prim,
    name: str,
    dtype: np.dtype,
    *,
    text: str,
    expected_type: str,
    width: int,
    count: int,
    properties: set[str],
    default_interpolation: str = "constant",
) -> np.ndarray:
    values, domain, indices = _typed_primvar_data(
        prim,
        name,
        dtype,
        text=text,
        expected_type=expected_type,
        width=width,
        count=count,
        properties=properties,
        default_interpolation=default_interpolation,
    )
    if indices is not None:
        values = values[indices]
    if domain == "constant":
        values = np.repeat(values, count, axis=0)
    values = np.array(values, copy=True, order="C")
    return values


def _primvar_metadata_int(text: str, name: str, key: str) -> int | None:
    declaration = next(
        (
            match
            for match in _DECLARATION.finditer(text)
            if match.group("name") == name
        ),
        None,
    )
    if declaration is None:
        return None
    value_end = text.find("]", declaration.end())
    if value_end < 0:
        return None
    opening = _METADATA_OPEN.match(text, value_end + 1)
    if opening is None:
        return None
    closing = text.find("\n    )", opening.end())
    if closing < 0:
        return None
    match = re.compile(
        rf"^ {{8}}{re.escape(key)}\s*=\s*(-?\d+)\s*$",
        re.MULTILINE,
    ).search(text, opening.end(), closing)
    return None if match is None else int(match.group(1))


def _validate_primvar_metadata(prim, name: str, *, text: str) -> None:
    element_size = _primvar_metadata_int(text, name, "elementSize")
    unauthored = _primvar_metadata_int(
        text,
        name,
        "unauthoredValuesIndex",
    )
    if element_size not in {None, 1}:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} elementSize must be 1"
        )
    if unauthored not in {None, -1}:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} "
            "unauthoredValuesIndex must be -1"
        )


def _builtin_array(
    prim,
    text: str,
    name: str,
    expected_type: str,
    dtype: np.dtype,
    *,
    width: int,
    count: int | None = None,
    interpolated: bool = False,
    default_interpolation: str = "vertex",
) -> np.ndarray:
    values, interpolation = _parse_array(
        prim,
        text,
        name,
        expected_type,
        dtype,
        width=width,
    )
    if values.size and not np.isfinite(values).all():
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} must be finite"
        )
    if count is None:
        return values
    if not interpolated:
        if len(values) != count:
            raise ValueError(
                f"USD points {prim.name!r}: {name!r} count "
                "does not match points"
            )
        return values
    domain = interpolation or default_interpolation
    if domain == "constant":
        if len(values) != 1:
            raise ValueError(
                f"USD points {prim.name!r}: {name!r} constant "
                "interpolation requires one value"
            )
        return np.repeat(values, count, axis=0)
    if domain not in {"vertex", "varying"} or len(values) != count:
        raise ValueError(
            f"USD points {prim.name!r}: {name!r} interpolation/count "
            "does not match points"
        )
    return values


def _point_extent_bounds(
    positions: np.ndarray,
    widths: np.ndarray | None,
    width_indices: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Compute point/diameter bounds with fixed-size numeric temporaries."""

    if not len(positions):
        return None
    if widths is None:
        return positions.min(axis=0), positions.max(axis=0)
    minimum = np.full(3, np.inf, dtype=np.float32)
    maximum = np.full(3, -np.inf, dtype=np.float32)
    for start in range(0, len(positions), 65_536):
        stop = min(start + 65_536, len(positions))
        chunk = positions[start:stop]
        if width_indices is not None:
            selected_indices = (
                width_indices
                if len(width_indices) == 1
                else width_indices[start:stop]
            )
            half_width = widths[selected_indices] * np.float32(0.5)
        elif len(widths) == 1:
            half_width = widths[0] * np.float32(0.5)
        else:
            half_width = widths[start:stop] * np.float32(0.5)
        for axis in range(3):
            minimum[axis] = min(
                minimum[axis],
                np.min(chunk[:, axis] - half_width),
            )
            maximum[axis] = max(
                maximum[axis],
                np.max(chunk[:, axis] + half_width),
            )
    return minimum, maximum


def point_arrays_from_prim(
    prim,
    *,
    shell_properties: frozenset[str] = frozenset(),
    coordinate_frame: str,
    scale_to_meters: float,
    text: str | None = None,
) -> tuple[np.ndarray, dict[str, object]]:
    """Validate and extract the qualified static Points attribute subset."""

    if text is None:
        text = prim.to_string()
    properties = property_names(prim, text=text)
    unsupported = sorted(properties - POINT_PROPERTIES - shell_properties)
    if unsupported:
        raise ValueError(
            f"USD points {prim.name!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    if "points" not in properties:
        raise ValueError(f"USD points {prim.name!r}: missing 'points'")
    for base_name in (
        "primvars:normals",
        "primvars:widths",
        "primvars:displayColor",
        "primvars:displayOpacity",
    ):
        indices_name = f"{base_name}:indices"
        if indices_name in properties and base_name not in properties:
            raise ValueError(
                f"USD points {prim.name!r}: {indices_name!r} requires "
                f"{base_name!r}"
            )
    positions = _builtin_array(
        prim,
        text,
        "points",
        "point3f[]",
        np.dtype(np.float32),
        width=3,
    )
    count = len(positions)
    kwargs: dict[str, object] = {
        "coordinate_frame": coordinate_frame,
        "scale_to_meters": scale_to_meters,
    }
    normals_name = (
        "primvars:normals"
        if "primvars:normals" in properties
        else "normals" if "normals" in properties else None
    )
    if normals_name == "primvars:normals":
        kwargs["normals"] = _typed_primvar(
            prim,
            normals_name,
            np.dtype(np.float32),
            text=text,
            expected_type="normal3f[]",
            width=3,
            count=count,
            properties=properties,
        )
    elif normals_name == "normals":
        kwargs["normals"] = _builtin_array(
            prim,
            text,
            "normals",
            "normal3f[]",
            np.dtype(np.float32),
            width=3,
            count=count,
            interpolated=True,
            default_interpolation="vertex",
        )
    widths_name = (
        "primvars:widths"
        if "primvars:widths" in properties
        else "widths" if "widths" in properties else None
    )
    if widths_name == "primvars:widths":
        kwargs["widths"] = _typed_primvar(
            prim,
            widths_name,
            np.dtype(np.float32),
            text=text,
            expected_type="float[]",
            width=1,
            count=count,
            properties=properties,
        )
    elif widths_name == "widths":
        kwargs["widths"] = _builtin_array(
            prim,
            text,
            "widths",
            "float[]",
            np.dtype(np.float32),
            width=1,
            count=count,
            interpolated=True,
        )
    if "widths" in kwargs and np.any(np.asarray(kwargs["widths"]) < 0):
        raise ValueError(f"USD points {prim.name!r}: widths must be nonnegative")
    for name, expected_type, dtype, width, target in (
        ("ids", "int64[]", np.dtype(np.int64), 1, "ids"),
        (
            "velocities",
            "vector3f[]",
            np.dtype(np.float32),
            3,
            "velocities",
        ),
        (
            "accelerations",
            "vector3f[]",
            np.dtype(np.float32),
            3,
            "accelerations",
        ),
    ):
        if name in properties:
            kwargs[target] = _builtin_array(
                prim,
                text,
                name,
                expected_type,
                dtype,
                width=width,
                count=count,
            )
    for name, expected_type, width, target in (
        (
            "primvars:displayColor",
            "color3f[]",
            3,
            "display_colors",
        ),
        (
            "primvars:displayOpacity",
            "float[]",
            1,
            "display_opacities",
        ),
    ):
        if name in properties:
            kwargs[target] = _typed_primvar(
                prim,
                name,
                np.dtype(np.float32),
                text=text,
                expected_type=expected_type,
                width=width,
                count=count,
                properties=properties,
            )
    if "primvars:displayColor" in properties:
        color_space = prim.get_attribute_metadata(
            "primvars:displayColor",
            "colorSpace",
        )
        if color_space not in {
            None,
            "lin_rec709_scene",
            "srgb_rec709_scene",
        }:
            raise ValueError(
                f"USD points {prim.name!r}: unsupported colorSpace "
                f"{color_space!r}"
            )
        kwargs["display_color_space"] = (
            "srgb" if color_space == "srgb_rec709_scene" else "linear"
        )
    if "extent" in properties:
        extent = _builtin_array(
            prim,
            text,
            "extent",
            "float3[]",
            np.dtype(np.float32),
            width=3,
        )
        if extent.shape != (2, 3):
            raise ValueError(
                f"USD points {prim.name!r}: extent must be (2, 3)"
            )
        if np.any(extent[0] > extent[1]):
            raise ValueError(
                f"USD points {prim.name!r}: extent minimum exceeds maximum"
            )
        bounds = _point_extent_bounds(
            positions,
            (
                np.asarray(kwargs["widths"])
                if "widths" in kwargs
                else None
            ),
        )
        if bounds is not None:
            minimum, maximum = bounds
            if np.any(extent[0] > minimum) or np.any(extent[1] < maximum):
                raise ValueError(
                    f"USD points {prim.name!r}: extent does not enclose "
                    "points and widths"
                )
    return positions, kwargs


def _inspect_typed_primvar(
    prim,
    name: str,
    dtype: np.dtype,
    *,
    text: str,
    expected_type: str,
    width: int,
    count: int,
    properties: set[str],
) -> tuple[np.ndarray, str, np.ndarray | None]:
    """Run the shared primvar guards without constructing a PointCloud."""

    return _typed_primvar_data(
        prim,
        name,
        dtype,
        text=text,
        expected_type=expected_type,
        width=width,
        count=count,
        properties=properties,
    )


def inspect_point_prim(
    prim,
    *,
    shell_properties: frozenset[str] = frozenset(),
    text: str | None = None,
) -> int:
    """Validate structural compatibility and return the point count."""

    if text is None:
        text = prim.to_string()
    properties = property_names(prim, text=text)
    unsupported = sorted(properties - POINT_PROPERTIES - shell_properties)
    if unsupported:
        raise ValueError(
            f"USD points {prim.name!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    if "points" not in properties:
        raise ValueError(f"USD points {prim.name!r}: missing 'points'")
    for base_name in (
        "primvars:normals",
        "primvars:widths",
        "primvars:displayColor",
        "primvars:displayOpacity",
    ):
        indices_name = f"{base_name}:indices"
        if indices_name in properties and base_name not in properties:
            raise ValueError(
                f"USD points {prim.name!r}: {indices_name!r} requires "
                f"{base_name!r}"
            )
    positions = _builtin_array(
        prim,
        text,
        "points",
        "point3f[]",
        np.dtype(np.float32),
        width=3,
    )
    count = len(positions)
    normals_name = (
        "primvars:normals"
        if "primvars:normals" in properties
        else "normals" if "normals" in properties else None
    )
    if normals_name == "primvars:normals":
        _inspect_typed_primvar(
            prim,
            normals_name,
            np.dtype(np.float32),
            text=text,
            expected_type="normal3f[]",
            width=3,
            count=count,
            properties=properties,
        )
    elif normals_name == "normals":
        normal_count, domain = _array_count(
            prim,
            text,
            "normals",
            "normal3f[]",
            width=3,
        )
        domain = domain or "vertex"
        expected = 1 if domain == "constant" else count
        if domain not in {"constant", "vertex", "varying"} or (
            normal_count != expected
        ):
            raise ValueError(
                f"USD points {prim.name!r}: normals interpolation/count "
                "does not match points"
            )
    widths = None
    width_indices = None
    if "primvars:widths" in properties:
        widths, _, width_indices = _inspect_typed_primvar(
            prim,
            "primvars:widths",
            np.dtype(np.float32),
            text=text,
            expected_type="float[]",
            width=1,
            count=count,
            properties=properties,
        )
    elif "widths" in properties:
        widths, width_domain = _parse_array(
            prim,
            text,
            "widths",
            "float[]",
            np.dtype(np.float32),
            width=1,
        )
        if widths.size and not np.isfinite(widths).all():
            raise ValueError(
                f"USD points {prim.name!r}: widths must be finite"
            )
        if np.any(widths < 0):
            raise ValueError(
                f"USD points {prim.name!r}: widths must be nonnegative"
            )
        width_domain = width_domain or "vertex"
        expected = 1 if width_domain == "constant" else count
        if width_domain not in {"constant", "vertex", "varying"} or (
            len(widths) != expected
        ):
            raise ValueError(
                f"USD points {prim.name!r}: widths interpolation/count "
                "does not match points"
            )
    for name, expected_type, width in (
        ("ids", "int64[]", 1),
        ("velocities", "vector3f[]", 3),
        ("accelerations", "vector3f[]", 3),
    ):
        if name in properties:
            if name == "ids":
                values = _builtin_array(
                    prim,
                    text,
                    name,
                    expected_type,
                    np.dtype(np.int64),
                    width=width,
                    count=count,
                )
                if len(np.unique(values)) != len(values):
                    raise ValueError(
                        f"USD points {prim.name!r}: ids must be unique"
                    )
                continue
            value_count, _ = _array_count(
                prim,
                text,
                name,
                expected_type,
                width=width,
            )
            if value_count != count:
                raise ValueError(
                    f"USD points {prim.name!r}: {name!r} count "
                    "does not match points"
                )
    for name, expected_type, width in (
        ("primvars:displayColor", "color3f[]", 3),
        ("primvars:displayOpacity", "float[]", 1),
    ):
        if name in properties:
            _inspect_typed_primvar(
                prim,
                name,
                np.dtype(np.float32),
                text=text,
                expected_type=expected_type,
                width=width,
                count=count,
                properties=properties,
            )
    if "primvars:displayColor" in properties:
        color_space = prim.get_attribute_metadata(
            "primvars:displayColor",
            "colorSpace",
        )
        if color_space not in {
            None,
            "lin_rec709_scene",
            "srgb_rec709_scene",
        }:
            raise ValueError(
                f"USD points {prim.name!r}: unsupported colorSpace "
                f"{color_space!r}"
            )
    if "extent" in properties:
        extent = _builtin_array(
            prim,
            text,
            "extent",
            "float3[]",
            np.dtype(np.float32),
            width=3,
        )
        if extent.shape != (2, 3):
            raise ValueError(
                f"USD points {prim.name!r}: extent must be (2, 3)"
            )
        if np.any(extent[0] > extent[1]):
            raise ValueError(
                f"USD points {prim.name!r}: extent minimum exceeds maximum"
            )
        bounds = _point_extent_bounds(
            positions,
            widths,
            width_indices,
        )
        if bounds is not None:
            minimum, maximum = bounds
            if np.any(extent[0] > minimum) or np.any(extent[1] < maximum):
                raise ValueError(
                    f"USD points {prim.name!r}: extent does not enclose "
                    "points and widths"
                )
    return count


def point_cloud_from_prim(
    prim,
    *,
    shell_properties: frozenset[str] = frozenset(),
    coordinate_frame: str,
    scale_to_meters: float,
    text: str | None = None,
):
    """Build an owning PointCloud from the qualified static schema subset."""

    positions, kwargs = point_arrays_from_prim(
        prim,
        shell_properties=shell_properties,
        coordinate_frame=coordinate_frame,
        scale_to_meters=scale_to_meters,
        text=text,
    )
    return _core.point_cloud(positions, **kwargs)


def validate_writable_point_cloud(
    cloud,
    *,
    up_axis: str,
    meters_per_unit: float,
    context: str,
) -> None:
    """Guard PointCloud fields outside the bounded UsdGeomPoints profile."""

    geometry._validate_scene_conventions(
        cloud,
        up_axis=up_axis,
        meters_per_unit=meters_per_unit,
        context=context,
    )
    if cloud.has_rgb or cloud.has_rgb16 or cloud.has_intensity:
        raise ValueError(
            f"USD: {context} quantized color/intensity fields are not "
            "representable; use float display fields explicitly"
        )
    if tuple(cloud.origin) != (0.0, 0.0, 0.0):
        raise ValueError(
            f"USD: {context} origin is not representable; use a node transform"
        )
    if (
        cloud.width != cloud.num_points
        or cloud.height != 1
        or tuple(cloud.viewpoint) != (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
        or cloud.has_las_waveform
    ):
        raise ValueError(
            f"USD: {context} organization/viewpoint/LAS sidecar is not "
            "representable"
        )
    accepted_color_spaces = (
        {"linear", "srgb"} if cloud.has_display_colors else {"unknown"}
    )
    if cloud.display_color_space not in accepted_color_spaces:
        raise ValueError(
            f"USD: {context} display_color_space must be one of "
            f"{sorted(accepted_color_spaces)!r}"
        )


def _write_interpolated(
    stream,
    *,
    inner: str,
    declaration: str,
    values: np.ndarray,
    scalar: bool,
    color_space: str | None = None,
) -> None:
    stream.write(f"{inner}{declaration} = ")
    if scalar:
        geometry.write_scalars(stream, values)
    else:
        geometry.write_rows(stream, values)
    stream.write(
        f" (\n{inner}    interpolation = \"vertex\"\n"
    )
    if color_space == "srgb":
        stream.write(
            f'{inner}    colorSpace = "srgb_rec709_scene"\n'
        )
    stream.write(f"{inner})\n")


def write_point_attributes(stream, cloud, *, inner: str) -> None:
    """Write the qualified static UsdGeomPoints attribute subset."""

    stream.write(f"{inner}point3f[] points = ")
    positions = np.asarray(cloud.positions)
    geometry.write_rows(stream, positions)
    stream.write("\n")
    if len(positions):
        minimum, maximum = _point_extent_bounds(
            positions,
            np.asarray(cloud.widths) if cloud.has_widths else None,
        )
        extent = np.stack((minimum, maximum))
        stream.write(f"{inner}float3[] extent = ")
        geometry.write_rows(stream, extent)
        stream.write("\n")
    for present, values, declaration, scalar in (
        (cloud.has_normals, cloud.normals, "normal3f[] normals", False),
        (cloud.has_widths, cloud.widths, "float[] widths", True),
        (
            cloud.has_display_colors,
            cloud.display_colors,
            "color3f[] primvars:displayColor",
            False,
        ),
        (
            cloud.has_display_opacities,
            cloud.display_opacities,
            "float[] primvars:displayOpacity",
            True,
        ),
    ):
        if present:
            _write_interpolated(
                stream,
                inner=inner,
                declaration=declaration,
                values=np.asarray(values),
                scalar=scalar,
                color_space=(
                    cloud.display_color_space
                    if "displayColor" in declaration
                    else None
                ),
            )
    for present, values, declaration, scalar in (
        (cloud.has_ids, cloud.ids, "int64[] ids", True),
        (
            cloud.has_velocities,
            cloud.velocities,
            "vector3f[] velocities",
            False,
        ),
        (
            cloud.has_accelerations,
            cloud.accelerations,
            "vector3f[] accelerations",
            False,
        ),
    ):
        if not present:
            continue
        stream.write(f"{inner}{declaration} = ")
        if scalar:
            geometry.write_scalars(stream, np.asarray(values), integer=True)
        else:
            geometry.write_rows(stream, np.asarray(values))
        stream.write("\n")


__all__ = [
    "POINT_PROPERTIES",
    "has_time_samples",
    "inspect_point_prim",
    "point_arrays_from_prim",
    "point_cloud_from_prim",
    "property_names",
    "validate_writable_point_cloud",
    "write_point_attributes",
]
