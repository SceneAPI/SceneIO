"""Bounded mapping for OpenUSD 26.08 3D Gaussian particle fields."""

from __future__ import annotations

import re
from typing import TextIO

import numpy as np

from sceneio import _core
from sceneio.io._usd import geometry

GAUSSIAN_PRIM_TYPE = "ParticleField3DGaussianSplat"
GAUSSIAN_PROPERTIES = frozenset(
    {
        "extent",
        "opacities",
        "opacitiesh",
        "orientations",
        "orientationsh",
        "positions",
        "positionsh",
        "projectionModeHint",
        "radiance:sphericalHarmonicsCoefficients",
        "radiance:sphericalHarmonicsCoefficientsh",
        "radiance:sphericalHarmonicsDegree",
        "scales",
        "scalesh",
        "sortingModeHint",
    }
)
PROJECTION_HINTS = frozenset({"perspective", "tangential"})
SORTING_HINTS = frozenset(
    {"zDepth", "cameraDistance", "rayHitDistance"}
)

_ARRAY_FAMILIES = {
    "positions": (
        ("positions", "point3f[]", np.dtype(np.float32)),
        ("positionsh", "point3h[]", np.dtype(np.float16)),
        3,
    ),
    "orientations": (
        ("orientations", "quatf[]", np.dtype(np.float32)),
        ("orientationsh", "quath[]", np.dtype(np.float16)),
        4,
    ),
    "scales": (
        ("scales", "float3[]", np.dtype(np.float32)),
        ("scalesh", "half3[]", np.dtype(np.float16)),
        3,
    ),
    "opacities": (
        ("opacities", "float[]", np.dtype(np.float32)),
        ("opacitiesh", "half[]", np.dtype(np.float16)),
        1,
    ),
    "coefficients": (
        (
            "radiance:sphericalHarmonicsCoefficients",
            "float3[]",
            np.dtype(np.float32),
        ),
        (
            "radiance:sphericalHarmonicsCoefficientsh",
            "half3[]",
            np.dtype(np.float16),
        ),
        3,
    ),
}
_ATTRIBUTE_DECLARATION = re.compile(
    r"^ {4}(?:(?:custom|uniform)\s+)*"
    r"[A-Za-z_][A-Za-z0-9_]*\[\]\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_:]*)\s*=",
    re.MULTILINE,
)
_ELEMENT_SIZE = re.compile(r"\belementSize\s*=\s*(-?\d+)")
_INTERPOLATION = re.compile(r'\binterpolation\s*=\s*"([^"]+)"')
_VALIDATION_CHUNK_VALUES = 1_048_576
_EXTENT_CHUNK_ROWS = 65_536


def _require_unit_quaternions(
    quaternions: np.ndarray,
    *,
    precision: str,
    context: str,
) -> None:
    if not len(quaternions):
        return
    tolerance = 5e-4 if precision == "float16" else 1e-5
    norms = np.linalg.norm(
        np.asarray(quaternions, dtype=np.float64), axis=1
    )
    if np.any(np.abs(norms - 1.0) > tolerance):
        raise ValueError(
            f"USD: {context} orientations must be unit quaternions"
        )


def _static_attribute(prim, name: str, expected_type: str):
    attribute = prim.get_attribute(name)
    if attribute is None:
        raise ValueError(f"USD Gaussian {prim.name!r}: missing {name!r}")
    if prim.get_attribute_timesamples(name):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: time-sampled {name!r} is unsupported"
        )
    if str(attribute.type_name) != expected_type:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: {name!r} must have type "
            f"{expected_type}, not {attribute.type_name}"
        )
    if attribute.value is None:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: {name!r} has no static value"
        )
    return attribute


def _selected_array(
    prim,
    properties: set[str],
    family: str,
) -> tuple[np.ndarray | None, str | None, str | None]:
    float_spec, half_spec, width = _ARRAY_FAMILIES[family]
    selected = (
        float_spec
        if float_spec[0] in properties
        else half_spec
        if half_spec[0] in properties
        else None
    )
    if selected is None:
        return None, None, None
    name, expected_type, dtype = selected
    attribute = _static_attribute(prim, name, expected_type)
    values = np.asarray(attribute.value)
    expected_shape = (
        (values.shape[0],)
        if values.ndim == 1 and width == 1
        else (values.shape[0], width)
        if values.ndim == 2 and width != 1
        else None
    )
    if values.dtype != dtype or values.shape != expected_shape:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: {name!r} must be a "
            f"{dtype.name} array with row width {width}"
        )
    if values.size and not np.isfinite(values).all():
        raise ValueError(
            f"USD Gaussian {prim.name!r}: {name!r} must be finite"
        )
    precision = "float32" if dtype == np.dtype(np.float32) else "float16"
    return values, precision, name


def _scalar_attribute(
    prim,
    properties: set[str],
    name: str,
    expected_type: str,
    default,
):
    if name not in properties:
        return default
    attribute = _static_attribute(prim, name, expected_type)
    try:
        return attribute.value.as_scalar()
    except (TypeError, ValueError):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: {name!r} must be scalar"
        ) from None


def _coefficient_metadata(
    prim,
    text: str,
    name: str,
    coefficient_count: int,
) -> None:
    declaration = next(
        (
            match
            for match in _ATTRIBUTE_DECLARATION.finditer(text)
            if match.group("name") == name
        ),
        None,
    )
    if declaration is None:
        return
    array_end = text.find("]", declaration.end())
    if array_end < 0:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: invalid coefficient array"
        )
    metadata_start = text.find("(", array_end + 1)
    next_line = text.find("\n", array_end + 1)
    if metadata_start < 0 or (
        next_line >= 0 and metadata_start > next_line
    ):
        return
    metadata_end = text.find("\n    )", metadata_start + 1)
    if metadata_end < 0:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: invalid coefficient metadata"
        )
    metadata = text[metadata_start:metadata_end]
    element_size = _ELEMENT_SIZE.search(metadata)
    if (
        element_size is not None
        and int(element_size.group(1)) != coefficient_count
    ):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: coefficient elementSize must be "
            f"{coefficient_count}"
        )
    interpolation = _INTERPOLATION.search(metadata)
    if interpolation is not None and interpolation.group(1) != "vertex":
        raise ValueError(
            f"USD Gaussian {prim.name!r}: coefficient interpolation must be "
            "vertex"
        )


def _validate_extent(
    prim,
    properties: set[str],
    positions: np.ndarray,
) -> None:
    if "extent" not in properties:
        return
    attribute = _static_attribute(prim, "extent", "float3[]")
    extent = np.asarray(attribute.value)
    if (
        extent.dtype != np.dtype(np.float32)
        or extent.shape != (2, 3)
        or not np.isfinite(extent).all()
    ):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: extent must be finite (2, 3) float32"
        )
    if np.any(extent[0] > extent[1]):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: extent minimum exceeds maximum"
        )
    if len(positions) and (
        np.any(extent[0] > positions.min(axis=0))
        or np.any(extent[1] < positions.max(axis=0))
    ):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: extent does not enclose positions"
        )


def _require_precision(
    prim,
    family: str,
    actual: str | None,
    expected: str,
) -> None:
    if actual is not None and actual != expected:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: selected {family} precision "
            f"{actual} does not match positions precision {expected}"
        )


def gaussian_arrays_from_prim(
    prim,
    *,
    shell_properties: frozenset[str] = frozenset(),
) -> tuple[np.ndarray, dict[str, object]]:
    """Validate and extract one official Gaussian particle field."""

    properties = set(prim.property_names())
    unsupported = sorted(properties - GAUSSIAN_PROPERTIES - shell_properties)
    if unsupported:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: unsupported properties: "
            + ", ".join(unsupported)
        )

    positions, source_precision, _ = _selected_array(
        prim, properties, "positions"
    )
    if positions is None:
        source_precision = "float32"
        positions_f32 = np.empty((0, 3), dtype=np.float32)
    else:
        positions_f32 = np.asarray(positions, dtype=np.float32, order="C")
    count = len(positions_f32)

    orientations, orientation_precision, _ = _selected_array(
        prim, properties, "orientations"
    )
    _require_precision(
        prim, "orientations", orientation_precision, source_precision
    )
    if orientations is None:
        quaternions = np.zeros((count, 4), dtype=np.float32)
        quaternions[:, 0] = 1.0
    else:
        if len(orientations) != count:
            raise ValueError(
                f"USD Gaussian {prim.name!r}: orientation count does not "
                "match positions"
            )
        provider_quaternions = np.asarray(orientations, dtype=np.float32)
        quaternions = np.ascontiguousarray(
            provider_quaternions[:, [3, 0, 1, 2]]
        )
    _require_unit_quaternions(
        quaternions,
        precision=source_precision,
        context=f"Gaussian {prim.name!r}",
    )

    scales, scale_precision, _ = _selected_array(
        prim, properties, "scales"
    )
    _require_precision(prim, "scales", scale_precision, source_precision)
    if scales is None:
        scales_f32 = np.ones((count, 3), dtype=np.float32)
    else:
        if len(scales) != count:
            raise ValueError(
                f"USD Gaussian {prim.name!r}: scale count does not match "
                "positions"
            )
        scales_f32 = np.asarray(scales, dtype=np.float32, order="C")
    if np.any(scales_f32 <= 0):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: linear scales must be positive"
        )

    opacities, opacity_precision, _ = _selected_array(
        prim, properties, "opacities"
    )
    _require_precision(
        prim, "opacities", opacity_precision, source_precision
    )
    if opacities is None:
        opacities_f32 = np.ones(count, dtype=np.float32)
    else:
        if len(opacities) != count:
            raise ValueError(
                f"USD Gaussian {prim.name!r}: opacity count does not match "
                "positions"
            )
        opacities_f32 = np.asarray(opacities, dtype=np.float32, order="C")
    if np.any(opacities_f32 < 0) or np.any(opacities_f32 > 1):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: opacities must be in [0, 1]"
        )

    coefficients, coefficient_precision, coefficient_name = _selected_array(
        prim, properties, "coefficients"
    )
    _require_precision(
        prim, "coefficients", coefficient_precision, source_precision
    )
    degree_authored = "radiance:sphericalHarmonicsDegree" in properties
    degree = _scalar_attribute(
        prim,
        properties,
        "radiance:sphericalHarmonicsDegree",
        "int",
        3 if coefficients is not None else 0,
    )
    if isinstance(degree, bool) or not isinstance(degree, int):
        raise ValueError(
            f"USD Gaussian {prim.name!r}: SH degree must be an integer"
        )
    if degree not in {0, 1, 2, 3}:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: SH degree must be in [0, 3]"
        )
    coefficient_count = (degree + 1) ** 2
    if coefficients is None:
        if count and degree_authored and degree != 0:
            raise ValueError(
                f"USD Gaussian {prim.name!r}: authored SH degree requires "
                "coefficient values"
            )
        if count:
            degree = 0
            coefficient_count = 1
        sh_dc = np.zeros((count, 3), dtype=np.float32)
        sh_rest = np.empty(
            (count, (coefficient_count - 1) * 3), dtype=np.float32
        )
    else:
        expected_rows = count * coefficient_count
        if len(coefficients) != expected_rows:
            raise ValueError(
                f"USD Gaussian {prim.name!r}: coefficient count must be "
                f"{expected_rows} for {count} particles at degree {degree}"
            )
        coefficient_values = np.asarray(
            coefficients, dtype=np.float32, order="C"
        ).reshape(count, coefficient_count, 3)
        sh_dc = np.ascontiguousarray(coefficient_values[:, 0, :])
        sh_rest = np.ascontiguousarray(
            coefficient_values[:, 1:, :].reshape(
                count, (coefficient_count - 1) * 3
            )
        )
        _coefficient_metadata(
            prim,
            prim.to_string(),
            coefficient_name,
            coefficient_count,
        )

    projection = _scalar_attribute(
        prim,
        properties,
        "projectionModeHint",
        "token",
        "perspective",
    )
    sorting = _scalar_attribute(
        prim,
        properties,
        "sortingModeHint",
        "token",
        "zDepth",
    )
    if projection not in PROJECTION_HINTS:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: unsupported projectionModeHint "
            f"{projection!r}"
        )
    if sorting not in SORTING_HINTS:
        raise ValueError(
            f"USD Gaussian {prim.name!r}: unsupported sortingModeHint "
            f"{sorting!r}"
        )
    _validate_extent(prim, properties, positions_f32)

    return positions_f32, {
        "scales": scales_f32,
        "quaternions": quaternions,
        "opacities": opacities_f32,
        "sh_dc": sh_dc,
        "sh_rest": sh_rest,
        "quaternion_order": "wxyz",
        "scale_space": "linear",
        "opacity_space": "linear",
        "sh_layout": "coefficient_rgb",
        "source_precision": source_precision,
        "projection_mode_hint": str(projection),
        "sorting_mode_hint": str(sorting),
    }


def gaussian_cloud_from_prim(
    prim,
    *,
    shell_properties: frozenset[str] = frozenset(),
):
    positions, kwargs = gaussian_arrays_from_prim(
        prim, shell_properties=shell_properties
    )
    return _core.gaussian_cloud(positions, **kwargs)


def inspect_gaussian_prim(
    prim,
    *,
    shell_properties: frozenset[str] = frozenset(),
) -> tuple[int, int, str]:
    positions, kwargs = gaussian_arrays_from_prim(
        prim, shell_properties=shell_properties
    )
    rest_width = int(np.asarray(kwargs["sh_rest"]).shape[1])
    degree = {0: 0, 9: 1, 24: 2, 45: 3}[rest_width]
    return len(positions), degree, str(kwargs["source_precision"])


def _require_float16_roundtrip(
    array: np.ndarray,
    *,
    context: str,
    name: str,
) -> None:
    source = np.ascontiguousarray(array, dtype=np.float32).reshape(-1)
    for start in range(0, source.size, _VALIDATION_CHUNK_VALUES):
        values = source[start : start + _VALIDATION_CHUNK_VALUES]
        restored = values.astype(np.float16).astype(np.float32)
        if not np.array_equal(
            restored.view(np.uint32), values.view(np.uint32)
        ):
            raise ValueError(
                f"USD: {context} {name} is not exactly representable as "
                "float16"
            )


def validate_writable_gaussian(
    cloud,
    *,
    context: str,
) -> tuple[np.ndarray, ...]:
    if (
        cloud.quaternion_order != "wxyz"
        or cloud.scale_space != "linear"
        or cloud.opacity_space != "linear"
        or cloud.sh_layout != "coefficient_rgb"
    ):
        raise ValueError(
            f"USD: {context} requires quaternion_order='wxyz', "
            "scale_space='linear', opacity_space='linear', and "
            "sh_layout='coefficient_rgb'; convert explicitly before writing"
        )
    if cloud.source_precision not in {"float16", "float32"}:
        raise ValueError(
            f"USD: {context} source_precision must be float16 or float32"
        )
    if cloud.projection_mode_hint not in PROJECTION_HINTS:
        raise ValueError(
            f"USD: {context} has unsupported projection_mode_hint"
        )
    if cloud.sorting_mode_hint not in SORTING_HINTS:
        raise ValueError(
            f"USD: {context} has unsupported sorting_mode_hint"
        )
    arrays = tuple(
        np.ascontiguousarray(np.asarray(getattr(cloud, name)), dtype=np.float32)
        for name in (
            "means",
            "scales",
            "quaternions",
            "opacities",
            "sh_dc",
            "sh_rest",
        )
    )
    if any(array.size and not np.isfinite(array).all() for array in arrays):
        raise ValueError(f"USD: {context} Gaussian arrays must be finite")
    _, scales, quaternions, opacities, _, _ = arrays
    if np.any(scales <= 0):
        raise ValueError(f"USD: {context} linear scales must be positive")
    if np.any(opacities < 0) or np.any(opacities > 1):
        raise ValueError(f"USD: {context} opacities must be in [0, 1]")
    _require_unit_quaternions(
        quaternions,
        precision=cloud.source_precision,
        context=context,
    )
    if cloud.source_precision == "float16":
        for name, array in zip(
            (
                "positions",
                "scales",
                "orientations",
                "opacities",
                "sh_dc",
                "sh_rest",
            ),
            arrays,
            strict=True,
        ):
            _require_float16_roundtrip(array, context=context, name=name)
    return arrays


def _gaussian_extent(
    positions: np.ndarray,
    scales: np.ndarray,
    quaternions: np.ndarray,
) -> np.ndarray | None:
    if not len(positions):
        return None
    minimum = np.full(3, np.inf, dtype=np.float64)
    maximum = np.full(3, -np.inf, dtype=np.float64)
    for start in range(0, len(positions), _EXTENT_CHUNK_ROWS):
        end = min(start + _EXTENT_CHUNK_ROWS, len(positions))
        q = quaternions[start:end].astype(np.float64)
        q /= np.linalg.norm(q, axis=1)[:, None]
        w, x, y, z = q.T
        chunk_scales = scales[start:end].astype(np.float64)
        sx, sy, sz = chunk_scales.T
        radius = np.empty((end - start, 3), dtype=np.float64)
        radius[:, 0] = 3.0 * np.sqrt(
            ((1 - 2 * (y * y + z * z)) * sx) ** 2
            + (2 * (x * y - z * w) * sy) ** 2
            + (2 * (x * z + y * w) * sz) ** 2
        )
        radius[:, 1] = 3.0 * np.sqrt(
            (2 * (x * y + z * w) * sx) ** 2
            + ((1 - 2 * (x * x + z * z)) * sy) ** 2
            + (2 * (y * z - x * w) * sz) ** 2
        )
        radius[:, 2] = 3.0 * np.sqrt(
            (2 * (x * z - y * w) * sx) ** 2
            + (2 * (y * z + x * w) * sy) ** 2
            + ((1 - 2 * (x * x + y * y)) * sz) ** 2
        )
        centers = positions[start:end].astype(np.float64)
        minimum = np.minimum(minimum, np.min(centers - radius, axis=0))
        maximum = np.maximum(maximum, np.max(centers + radius, axis=0))
    if not np.isfinite(minimum).all() or not np.isfinite(maximum).all():
        raise ValueError("USD: Gaussian extent is outside the finite domain")
    minimum_f32 = minimum.astype(np.float32)
    maximum_f32 = maximum.astype(np.float32)
    if not np.isfinite(minimum_f32).all() or not np.isfinite(maximum_f32).all():
        raise ValueError("USD: Gaussian extent exceeds float32 storage")
    minimum_f32 = np.nextafter(minimum_f32, -np.inf, dtype=np.float32)
    maximum_f32 = np.nextafter(maximum_f32, np.inf, dtype=np.float32)
    return np.stack((minimum_f32, maximum_f32))


def _write_coefficients(
    stream: TextIO,
    sh_dc: np.ndarray,
    sh_rest: np.ndarray,
) -> None:
    coefficient_count = sh_rest.shape[1] // 3 + 1
    stream.write("[")
    first = True
    for start in range(0, len(sh_dc), 1024):
        end = min(start + 1024, len(sh_dc))
        chunk = np.empty((end - start, coefficient_count, 3), np.float32)
        chunk[:, 0, :] = sh_dc[start:end]
        if coefficient_count > 1:
            chunk[:, 1:, :] = sh_rest[start:end].reshape(
                end - start, coefficient_count - 1, 3
            )
        for row in chunk.reshape(-1, 3):
            if not first:
                stream.write(", ")
            first = False
            stream.write(
                "("
                + ", ".join(geometry.format_float(value) for value in row)
                + ")"
            )
    stream.write("]")


def write_gaussian_attributes(
    stream: TextIO,
    cloud,
    *,
    inner: str,
    validated: tuple[np.ndarray, ...] | None = None,
) -> None:
    arrays = (
        validate_writable_gaussian(cloud, context="Gaussian payload")
        if validated is None
        else validated
    )
    positions, scales, quaternions, opacities, sh_dc, sh_rest = arrays
    half = cloud.source_precision == "float16"
    type_suffix = "h" if half else "f"
    name_suffix = "h" if half else ""
    scalar_type = "half" if half else "float"

    stream.write(f"{inner}point3{type_suffix}[] positions{name_suffix} = ")
    geometry.write_rows(stream, positions)
    stream.write("\n")
    extent = _gaussian_extent(positions, scales, quaternions)
    if extent is not None:
        stream.write(f"{inner}float3[] extent = ")
        geometry.write_rows(stream, extent)
        stream.write("\n")
    stream.write(
        f"{inner}quat{type_suffix}[] orientations{name_suffix} = "
    )
    geometry.write_rows(stream, quaternions)
    stream.write("\n")
    stream.write(f"{inner}{scalar_type}3[] scales{name_suffix} = ")
    geometry.write_rows(stream, scales)
    stream.write("\n")
    stream.write(f"{inner}{scalar_type}[] opacities{name_suffix} = ")
    geometry.write_scalars(stream, opacities)
    stream.write("\n")
    stream.write(
        f"{inner}uniform int radiance:sphericalHarmonicsDegree = "
        f"{cloud.sh_degree}\n"
    )
    coefficient_name = (
        "radiance:sphericalHarmonicsCoefficientsh"
        if half
        else "radiance:sphericalHarmonicsCoefficients"
    )
    stream.write(f"{inner}{scalar_type}3[] {coefficient_name} = ")
    _write_coefficients(stream, sh_dc, sh_rest)
    stream.write(
        f" (\n{inner}    interpolation = \"vertex\"\n"
        f"{inner}    elementSize = {(cloud.sh_degree + 1) ** 2}\n"
        f"{inner})\n"
    )
    stream.write(
        f'{inner}uniform token projectionModeHint = '
        f'"{cloud.projection_mode_hint}"\n'
        f'{inner}uniform token sortingModeHint = '
        f'"{cloud.sorting_mode_hint}"\n'
    )


__all__ = [
    "GAUSSIAN_PRIM_TYPE",
    "GAUSSIAN_PROPERTIES",
    "PROJECTION_HINTS",
    "SORTING_HINTS",
    "gaussian_arrays_from_prim",
    "gaussian_cloud_from_prim",
    "inspect_gaussian_prim",
    "validate_writable_gaussian",
    "write_gaussian_attributes",
]
