"""Bounded USD mesh value extraction shared by legacy and rich reads."""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np

from sceneio import _core

MESH_PROPERTIES = frozenset(
    {
        "points",
        "faceVertexCounts",
        "faceVertexIndices",
        "normals",
        "primvars:normals",
        "primvars:normals:indices",
        "primvars:st",
        "primvars:st:indices",
        "primvars:displayColor",
        "primvars:displayColor:indices",
        "primvars:displayOpacity",
        "primvars:displayOpacity:indices",
        "subdivisionScheme",
        "extent",
        "orientation",
        "doubleSided",
    }
)
_ORIENTATION = re.compile(
    r'^ {4}(?:uniform\s+)?token\s+orientation\s*=\s*'
    r'"(rightHanded|leftHanded)"\s*$',
    re.MULTILINE,
)
_DOUBLE_SIDED = re.compile(
    r"^ {4}(?:uniform\s+)?bool\s+doubleSided\s*=\s*"
    r"(true|false|0|1)\s*$",
    re.MULTILINE,
)
_EXTENT = re.compile(
    r"^ {4}float3\[\]\s+extent\s*=\s*\[([^\]]*)\]",
    re.MULTILINE,
)
_COLOR_SPACES = {
    None: "linear",
    "lin_rec709_scene": "linear",
    "srgb_rec709_scene": "srgb",
}


def value_array(
    prim,
    name: str,
    dtype: np.dtype,
    *,
    copy: bool = True,
    expected_type: str | None = None,
) -> np.ndarray:
    """Extract one static provider value with exact dtype."""

    attribute = prim.get_attribute(name)
    if attribute is None:
        raise ValueError(f"USD mesh {prim.name!r}: missing {name!r}")
    if expected_type is not None and str(attribute.type_name) != expected_type:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} must have type "
            f"{expected_type}, not {attribute.type_name}"
        )
    samples = prim.get_attribute_timesamples(name)
    if samples:
        raise ValueError(
            f"USD mesh {prim.name!r}: time-sampled {name!r} is unsupported"
        )
    array = np.asarray(attribute.value)
    if array.dtype != dtype:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} must have dtype {dtype.name}"
        )
    if copy:
        return np.array(array, copy=True, order="C")
    return array


def interpolation(prim, name: str, *, default: str) -> str:
    """Return the effective mesh primvar interpolation domain."""

    value = prim.get_attribute_metadata(name, "interpolation") or default
    if value not in {
        "constant",
        "uniform",
        "vertex",
        "varying",
        "faceVarying",
    }:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} interpolation must be "
            "'constant', 'uniform', 'vertex', 'varying', or 'faceVarying'"
        )
    return value


def _validate_primvar_metadata(prim, name: str) -> None:
    if not name.startswith("primvars:"):
        return
    element_size = _primvar_metadata_int(prim, name, "elementSize")
    unauthored = _primvar_metadata_int(
        prim,
        name,
        "unauthoredValuesIndex",
    )
    if element_size not in {None, 1}:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} elementSize must be 1"
        )
    if unauthored not in {None, -1}:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} "
            "unauthoredValuesIndex must be -1"
        )


def _primvar_metadata_int(prim, name: str, key: str) -> int | None:
    value = prim.get_attribute_metadata(name, key)
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    text = prim.to_string()
    declaration = re.search(
        rf"^ {{4}}(?:(?:custom|uniform)\s+)*"
        rf"[A-Za-z_][A-Za-z0-9_]*\[\]\s+{re.escape(name)}\s*=",
        text,
        re.MULTILINE,
    )
    if declaration is None:
        return None
    value_end = text.find("]", declaration.end())
    if value_end < 0:
        return None
    cursor = value_end + 1
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text) or text[cursor] != "(":
        return None
    closing = text.find("\n    )", cursor + 1)
    if closing < 0:
        return None
    match = re.compile(
        rf"^ {{8}}{re.escape(key)}\s*=\s*(-?\d+)\s*$",
        re.MULTILINE,
    ).search(text, cursor + 1, closing)
    return None if match is None else int(match.group(1))


def _flatten_primvar_values(
    prim,
    name: str,
    values: np.ndarray,
    *,
    vertex_count: int,
    face_counts: np.ndarray,
    corner_count: int,
    properties: set[str],
    default_interpolation: str,
    expand: bool,
) -> tuple[np.ndarray, str]:
    """Flatten optional indices and validate one mesh primvar domain."""

    _validate_primvar_metadata(prim, name)
    domain = interpolation(prim, name, default=default_interpolation)
    expected = {
        "constant": 1,
        "uniform": len(face_counts),
        "vertex": vertex_count,
        "varying": vertex_count,
        "faceVarying": corner_count,
    }[domain]
    indices_name = f"{name}:indices"
    if values.size and not np.isfinite(values).all():
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} must be finite"
        )
    if indices_name in properties:
        indices = value_array(
            prim,
            indices_name,
            np.dtype(np.int32),
            copy=False,
            expected_type="int[]",
        )
        if indices.ndim != 1 or len(indices) != expected:
            raise ValueError(
                f"USD mesh {prim.name!r}: {indices_name!r} must have "
                f"{expected} entries"
            )
        if indices.size and (
            int(indices.min()) < 0 or int(indices.max()) >= len(values)
        ):
            raise ValueError(
                f"USD mesh {prim.name!r}: {indices_name!r} is out of range"
            )
        if expand:
            values = np.array(values[indices], copy=True, order="C")
    elif len(values) != expected:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} {domain} count "
            "does not match topology"
        )
    if not expand:
        return values, (
            "vertex"
            if domain in {"constant", "vertex", "varying"}
            else "corner"
        )
    if domain == "constant":
        return np.repeat(values, vertex_count, axis=0), "vertex"
    if domain == "uniform":
        return np.repeat(values, face_counts, axis=0), "corner"
    if domain in {"vertex", "varying"}:
        return values, "vertex"
    return values, "corner"


def _flatten_primvar(
    prim,
    name: str,
    dtype: np.dtype,
    *,
    expected_type: str,
    width: int,
    vertex_count: int,
    face_counts: np.ndarray,
    corner_count: int,
    properties: set[str],
    default_interpolation: str,
    expand: bool,
    copy: bool,
) -> tuple[np.ndarray, str]:
    """Return a validated flat primvar and its SceneIO storage domain."""

    values = value_array(
        prim,
        name,
        dtype,
        copy=copy,
        expected_type=expected_type,
    )
    if values.ndim != 2 or values.shape[1:] != (width,):
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} has invalid shape"
        )
    return _flatten_primvar_values(
        prim,
        name,
        values,
        vertex_count=vertex_count,
        face_counts=face_counts,
        corner_count=corner_count,
        properties=properties,
        default_interpolation=default_interpolation,
        expand=expand,
    )


def _authored_orientation(prim, properties: set[str]) -> str:
    if "orientation" not in properties:
        return "unknown"
    match = _ORIENTATION.search(prim.to_string())
    if match is None:
        raise ValueError(
            f"USD mesh {prim.name!r}: invalid authored orientation"
        )
    return (
        "right_handed"
        if match.group(1) == "rightHanded"
        else "left_handed"
    )


def _authored_double_sided(
    prim,
    properties: set[str],
) -> bool | None:
    if "doubleSided" not in properties:
        return None
    match = _DOUBLE_SIDED.search(prim.to_string())
    if match is None:
        raise ValueError(
            f"USD mesh {prim.name!r}: invalid authored doubleSided"
        )
    return match.group(1) in {"true", "1"}


def _display_color_space(prim, name: str) -> str:
    value = prim.get_attribute_metadata(name, "colorSpace")
    try:
        return _COLOR_SPACES[value]
    except KeyError:
        raise ValueError(
            f"USD mesh {prim.name!r}: unsupported colorSpace {value!r}"
        ) from None


def _extent_from_text(prim) -> np.ndarray:
    match = _EXTENT.search(prim.to_string())
    if match is None:
        raise ValueError(f"USD mesh {prim.name!r}: invalid extent")
    tokens = (
        match.group(1)
        .translate(str.maketrans("(),", "   "))
        .split()
    )
    try:
        extent = np.asarray([float(token) for token in tokens], np.float32)
    except (OverflowError, ValueError):
        raise ValueError(f"USD mesh {prim.name!r}: invalid extent") from None
    if extent.size != 6:
        raise ValueError(f"USD mesh {prim.name!r}: invalid extent")
    return extent.reshape(2, 3)


def _validate_extent(
    prim,
    extent: np.ndarray,
    *,
    minimum: np.ndarray | None,
    maximum: np.ndarray | None,
) -> None:
    """Require a finite, ordered bound that encloses represented geometry."""

    if extent.shape != (2, 3) or not np.isfinite(extent).all():
        raise ValueError(f"USD mesh {prim.name!r}: invalid extent")
    if np.any(extent[0] > extent[1]):
        raise ValueError(
            f"USD mesh {prim.name!r}: extent minimum exceeds maximum"
        )
    if minimum is not None and (
        np.any(extent[0] > minimum) or np.any(extent[1] < maximum)
    ):
        raise ValueError(
            f"USD mesh {prim.name!r}: extent does not enclose points"
        )


def mesh_arrays_from_prim(
    prim,
    *,
    copy: bool,
    expand: bool = True,
    shell_properties: frozenset[str] = frozenset(),
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Validate and extract the currently accepted static mesh fields."""

    properties = set(prim.property_names())
    unsupported = sorted(properties - MESH_PROPERTIES - shell_properties)
    if unsupported:
        raise ValueError(
            f"USD mesh {prim.name!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    required = {"points", "faceVertexCounts", "faceVertexIndices"}
    missing = sorted(required - properties)
    if missing:
        raise ValueError(
            f"USD mesh {prim.name!r}: missing properties: "
            + ", ".join(missing)
        )
    for base_name in (
        "primvars:normals",
        "primvars:st",
        "primvars:displayColor",
        "primvars:displayOpacity",
    ):
        indices_name = f"{base_name}:indices"
        if indices_name in properties and base_name not in properties:
            raise ValueError(
                f"USD mesh {prim.name!r}: {indices_name!r} requires "
                f"{base_name!r}"
            )

    positions = value_array(
        prim,
        "points",
        np.dtype(np.float32),
        copy=copy,
        expected_type="point3f[]",
    )
    if positions.ndim != 2 or positions.shape[1:] != (3,):
        raise ValueError(
            f"USD mesh {prim.name!r}: points must have shape (N, 3)"
        )
    counts = value_array(
        prim,
        "faceVertexCounts",
        np.dtype(np.int32),
        copy=copy,
        expected_type="int[]",
    )
    indices_i32 = value_array(
        prim,
        "faceVertexIndices",
        np.dtype(np.int32),
        copy=copy,
        expected_type="int[]",
    )
    if counts.ndim != 1 or indices_i32.ndim != 1:
        raise ValueError(
            f"USD mesh {prim.name!r}: face topology arrays must be rank 1"
        )
    if counts.size and int(counts.min()) < 3:
        raise ValueError(
            f"USD mesh {prim.name!r}: faces must contain at least 3 corners"
        )
    if int(counts.sum(dtype=np.int64)) != len(indices_i32):
        raise ValueError(
            f"USD mesh {prim.name!r}: face counts and indices disagree"
        )
    if indices_i32.size and (
        int(indices_i32.min()) < 0 or int(indices_i32.max()) >= len(positions)
    ):
        raise ValueError(
            f"USD mesh {prim.name!r}: face index is outside the point array"
        )
    if positions.size and not np.isfinite(positions).all():
        raise ValueError(f"USD mesh {prim.name!r}: points must be finite")

    kwargs: dict[str, object] = {}
    normals_name = (
        "primvars:normals"
        if "primvars:normals" in properties
        else "normals"
    )
    for usd_name, vertex_name, corner_name, width, expected_type in (
        (
            normals_name,
            "vertex_normals",
            "corner_normals",
            3,
            "normal3f[]",
        ),
        (
            "primvars:st",
            "vertex_uvs",
            "corner_uvs",
            2,
            "texCoord2f[]",
        ),
        (
            "primvars:displayColor",
            "vertex_display_colors",
            "corner_display_colors",
            3,
            "color3f[]",
        ),
        (
            "primvars:displayOpacity",
            "vertex_display_opacities",
            "corner_display_opacities",
            1,
            "float[]",
        ),
    ):
        if usd_name not in properties:
            continue
        if width == 1:
            attribute = value_array(
                prim,
                usd_name,
                np.dtype(np.float32),
                copy=copy,
                expected_type=expected_type,
            )
            if attribute.ndim != 1:
                raise ValueError(
                    f"USD mesh {prim.name!r}: {usd_name!r} "
                    "must be rank 1"
                )
            if usd_name == "primvars:displayOpacity" and attribute.size and (
                np.any(attribute < 0) or np.any(attribute > 1)
            ):
                raise ValueError(
                    f"USD mesh {prim.name!r}: display opacity "
                    "must be in [0, 1]"
                )
            array2d = attribute[:, None]
            values, domain = _flatten_primvar_values(
                prim,
                usd_name,
                array2d,
                vertex_count=len(positions),
                face_counts=counts,
                corner_count=len(indices_i32),
                properties=properties,
                default_interpolation="constant",
                expand=expand,
            )
            kwargs[
                vertex_name if domain == "vertex" else corner_name
            ] = values[:, 0]
        else:
            values, domain = _flatten_primvar(
                prim,
                usd_name,
                np.dtype(np.float32),
                expected_type=expected_type,
                width=width,
                vertex_count=len(positions),
                face_counts=counts,
                corner_count=len(indices_i32),
                properties=properties,
                default_interpolation=(
                    "vertex" if usd_name == "normals" else "constant"
                ),
                expand=expand,
                copy=copy,
            )
            kwargs[
                vertex_name if domain == "vertex" else corner_name
            ] = values
        if usd_name == "primvars:displayColor":
            kwargs["display_color_space"] = _display_color_space(
                prim,
                usd_name,
            )
    if "subdivisionScheme" not in properties:
        raise ValueError(
            f"USD mesh {prim.name!r}: subdivisionScheme must be authored "
            'as "none"; the USD fallback is a subdivision surface'
        )
    attribute = prim.get_attribute("subdivisionScheme")
    if attribute is None or attribute.value.to_string() != '"none"':
        raise ValueError(
            f"USD mesh {prim.name!r}: subdivision surfaces are unsupported"
        )
    if "extent" in properties:
        extent = _extent_from_text(prim)
        _validate_extent(
            prim,
            extent,
            minimum=positions.min(axis=0) if len(positions) else None,
            maximum=positions.max(axis=0) if len(positions) else None,
        )

    kwargs["orientation"] = _authored_orientation(prim, properties)
    kwargs["double_sided"] = _authored_double_sided(prim, properties)

    return positions, counts, indices_i32, kwargs


def mesh_from_prim(
    prim,
    *,
    shell_properties: frozenset[str] = frozenset(),
    coordinate_frame: str = "opengl",
    scale_to_meters: float = 1.0,
    binding_resolver: Callable[[int], dict[str, np.ndarray]] | None = None,
):
    """Build an owning SceneIO Mesh from one provider prim."""

    positions, counts, indices_i32, kwargs = mesh_arrays_from_prim(
        prim,
        copy=True,
        shell_properties=shell_properties,
    )
    face_offsets = np.empty(len(counts) + 1, dtype=np.uint64)
    face_offsets[0] = 0
    np.cumsum(counts, dtype=np.uint64, out=face_offsets[1:])
    indices = indices_i32.astype(np.uint64)
    if binding_resolver is not None:
        kwargs.update(binding_resolver(len(counts)))
    return _core.mesh(
        positions,
        face_offsets,
        indices,
        coordinate_frame=coordinate_frame,
        scale_to_meters=scale_to_meters,
        **kwargs,
    )


def format_float(value: object, *, double: bool = False) -> str:
    """Render a float with enough digits for exact binary round-trip."""

    return format(float(value), ".17g" if double else ".9g")


def write_rows(stream, array: np.ndarray, *, double: bool = False) -> None:
    """Stream a vector array without constructing the complete text value."""

    stream.write("[")
    for start in range(0, len(array), 1024):
        chunk = array[start : start + 1024]
        if start:
            stream.write(", ")
        stream.write(
            ", ".join(
                "("
                + ", ".join(
                    format_float(value, double=double) for value in row
                )
                + ")"
                for row in chunk
            )
        )
    stream.write("]")


def write_scalars(
    stream,
    array: np.ndarray,
    *,
    integer: bool = False,
) -> None:
    """Stream one scalar array in bounded chunks."""

    stream.write("[")
    for start in range(0, len(array), 4096):
        if start:
            stream.write(", ")
        chunk = array[start : start + 4096]
        stream.write(
            ", ".join(
                str(int(value)) if integer else format_float(value)
                for value in chunk
            )
        )
    stream.write("]")


def _validate_scene_conventions(
    payload,
    *,
    up_axis: str,
    meters_per_unit: float,
    context: str,
) -> None:
    expected_frame = "opengl" if up_axis == "y" else "enu"
    if payload.coordinate_frame not in {"unknown", expected_frame}:
        raise ValueError(
            f"USD: {context} coordinate_frame must be unknown or "
            f"{expected_frame!r} for the stage up-axis"
        )
    if payload.scale_to_meters != meters_per_unit:
        raise ValueError(
            f"USD: {context} scale_to_meters must equal stage "
            "meters_per_unit"
        )


def validate_writable_mesh(
    mesh,
    *,
    up_axis: str,
    meters_per_unit: float,
    context: str,
    material_count: int = 0,
) -> None:
    """Guard fields that the bounded mesh schema cannot preserve."""

    _validate_scene_conventions(
        mesh,
        up_axis=up_axis,
        meters_per_unit=meters_per_unit,
        context=context,
    )
    if not np.array_equal(np.asarray(mesh.local_transform), np.eye(4)):
        raise ValueError(
            f"USD: {context} local_transform must be identity; "
            "use the SceneGraph node transform"
        )
    if mesh.has_vertex_colors or mesh.has_corner_colors:
        raise ValueError(
            f"USD: {context} quantized RGBA fields are not representable; "
            "use float display colors explicitly"
        )
    if mesh.has_face_smoothing_groups:
        raise ValueError(
            f"USD: {context} smoothing groups are not representable"
        )
    if mesh.has_primitive_object_names or mesh.has_primitive_group_names:
        raise ValueError(
            f"USD: {context} object/group names are not representable"
        )
    if mesh.has_materials:
        raise ValueError(
            f"USD: {context} attached MaterialSet is not representable; "
            "use SceneGraph.materials"
        )
    materials = np.asarray(mesh.primitive_materials)
    if materials.size and (
        np.any(materials < -1)
        or np.any(materials >= material_count)
    ):
        raise ValueError(
            f"USD: {context} material index is outside SceneGraph.materials"
        )
    expected_primitives = 0 if mesh.num_faces == 0 else 1
    if (
        not np.any(materials >= 0)
        and mesh.num_primitives != expected_primitives
    ):
        raise ValueError(
            f"USD: {context} primitive partitions require material assignments"
        )
    int32_max = np.iinfo(np.int32).max
    if mesh.num_vertices > int32_max or (
        mesh.num_corners
        and int(np.asarray(mesh.face_indices).max()) > int32_max
    ):
        raise ValueError(
            f"USD: {context} topology exceeds USD int[] range"
        )
    counts = np.diff(np.asarray(mesh.face_offsets))
    if counts.size and int(counts.max()) > int32_max:
        raise ValueError(
            f"USD: {context} face size exceeds USD int[] range"
        )
    if mesh.has_vertex_normals and mesh.has_corner_normals:
        raise ValueError(
            f"USD: {context} cannot author both vertex and corner normals"
        )
    if mesh.has_vertex_uvs and mesh.has_corner_uvs:
        raise ValueError(
            f"USD: {context} cannot author both vertex and corner UVs"
        )
    if mesh.has_vertex_display_colors and mesh.has_corner_display_colors:
        raise ValueError(
            f"USD: {context} cannot author both vertex and corner "
            "display colors"
        )
    if (
        mesh.has_vertex_display_opacities
        and mesh.has_corner_display_opacities
    ):
        raise ValueError(
            f"USD: {context} cannot author both vertex and corner "
            "display opacities"
        )
    has_display_colors = (
        mesh.has_vertex_display_colors or mesh.has_corner_display_colors
    )
    accepted_color_spaces = (
        {"linear", "srgb"} if has_display_colors else {"unknown"}
    )
    if mesh.display_color_space not in accepted_color_spaces:
        raise ValueError(
            f"USD: {context} display_color_space must be one of "
            f"{sorted(accepted_color_spaces)!r}"
        )


def _write_primvar(
    stream,
    *,
    inner: str,
    declaration: str,
    values: np.ndarray,
    interpolation_value: str,
    scalar: bool = False,
    color_space: str | None = None,
) -> None:
    stream.write(f"{inner}{declaration} = ")
    if scalar:
        write_scalars(stream, values)
    else:
        write_rows(stream, values)
    stream.write(
        f" (\n{inner}    interpolation = "
        f'"{interpolation_value}"\n'
    )
    if color_space == "srgb":
        stream.write(
            f'{inner}    colorSpace = "srgb_rec709_scene"\n'
        )
    stream.write(f"{inner})\n")


def write_mesh_attributes(stream, mesh, *, inner: str) -> None:
    """Write the qualified static UsdGeomMesh attribute subset."""

    stream.write(f"{inner}point3f[] points = ")
    positions = np.asarray(mesh.positions)
    write_rows(stream, positions)
    stream.write("\n")
    if len(positions):
        extent = np.stack(
            (positions.min(axis=0), positions.max(axis=0))
        ).astype(np.float32, copy=False)
        stream.write(f"{inner}float3[] extent = ")
        write_rows(stream, extent)
        stream.write("\n")
    stream.write(f"{inner}int[] faceVertexCounts = ")
    write_scalars(
        stream,
        np.diff(np.asarray(mesh.face_offsets)),
        integer=True,
    )
    stream.write("\n")
    stream.write(f"{inner}int[] faceVertexIndices = ")
    write_scalars(stream, np.asarray(mesh.face_indices), integer=True)
    stream.write("\n")
    for present, values, declaration, interpolation_value, scalar in (
        (
            mesh.has_vertex_normals,
            mesh.vertex_normals,
            "normal3f[] normals",
            "vertex",
            False,
        ),
        (
            mesh.has_corner_normals,
            mesh.corner_normals,
            "normal3f[] normals",
            "faceVarying",
            False,
        ),
        (
            mesh.has_vertex_uvs,
            mesh.vertex_uvs,
            "texCoord2f[] primvars:st",
            "vertex",
            False,
        ),
        (
            mesh.has_corner_uvs,
            mesh.corner_uvs,
            "texCoord2f[] primvars:st",
            "faceVarying",
            False,
        ),
        (
            mesh.has_vertex_display_colors,
            mesh.vertex_display_colors,
            "color3f[] primvars:displayColor",
            "vertex",
            False,
        ),
        (
            mesh.has_corner_display_colors,
            mesh.corner_display_colors,
            "color3f[] primvars:displayColor",
            "faceVarying",
            False,
        ),
        (
            mesh.has_vertex_display_opacities,
            mesh.vertex_display_opacities,
            "float[] primvars:displayOpacity",
            "vertex",
            True,
        ),
        (
            mesh.has_corner_display_opacities,
            mesh.corner_display_opacities,
            "float[] primvars:displayOpacity",
            "faceVarying",
            True,
        ),
    ):
        if present:
            _write_primvar(
                stream,
                inner=inner,
                declaration=declaration,
                values=np.asarray(values),
                interpolation_value=interpolation_value,
                scalar=scalar,
                color_space=(
                    mesh.display_color_space
                    if "displayColor" in declaration
                    else None
                ),
            )
    stream.write(f'{inner}uniform token subdivisionScheme = "none"\n')
    if mesh.orientation != "unknown":
        token = (
            "rightHanded"
            if mesh.orientation == "right_handed"
            else "leftHanded"
        )
        stream.write(f'{inner}uniform token orientation = "{token}"\n')
    if mesh.has_double_sided:
        stream.write(
            f"{inner}uniform bool doubleSided = "
            f"{'true' if mesh.double_sided else 'false'}\n"
        )


__all__ = [
    "MESH_PROPERTIES",
    "format_float",
    "interpolation",
    "mesh_arrays_from_prim",
    "mesh_from_prim",
    "validate_writable_mesh",
    "value_array",
    "write_mesh_attributes",
    "write_rows",
    "write_scalars",
]
