"""Bounded USD mesh value extraction shared by legacy and rich reads."""

from __future__ import annotations

import numpy as np

from sceneio import _core

MESH_PROPERTIES = frozenset(
    {
        "points",
        "faceVertexCounts",
        "faceVertexIndices",
        "normals",
        "primvars:st",
        "subdivisionScheme",
        "extent",
    }
)


def value_array(
    prim,
    name: str,
    dtype: np.dtype,
    *,
    copy: bool = True,
) -> np.ndarray:
    """Extract one static provider value with exact dtype."""

    attribute = prim.get_attribute(name)
    if attribute is None:
        raise ValueError(f"USD mesh {prim.name!r}: missing {name!r}")
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


def interpolation(prim, name: str) -> str:
    """Return an accepted mesh primvar interpolation domain."""

    value = prim.get_attribute_metadata(name, "interpolation")
    if value not in {"vertex", "faceVarying"}:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} interpolation must be "
            "'vertex' or 'faceVarying'"
        )
    return value


def mesh_arrays_from_prim(
    prim,
    *,
    copy: bool,
    shell_properties: frozenset[str] = frozenset(),
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, np.ndarray]]:
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

    positions = value_array(
        prim, "points", np.dtype(np.float32), copy=copy
    )
    if positions.ndim != 2 or positions.shape[1:] != (3,):
        raise ValueError(
            f"USD mesh {prim.name!r}: points must have shape (N, 3)"
        )
    counts = value_array(
        prim, "faceVertexCounts", np.dtype(np.int32), copy=copy
    )
    indices_i32 = value_array(
        prim, "faceVertexIndices", np.dtype(np.int32), copy=copy
    )
    if counts.ndim != 1 or indices_i32.ndim != 1:
        raise ValueError(
            f"USD mesh {prim.name!r}: face topology arrays must be rank 1"
        )
    if counts.size and int(counts.min()) < 3:
        raise ValueError(
            f"USD mesh {prim.name!r}: faces must contain at least 3 corners"
        )
    if int(counts.astype(np.int64).sum()) != len(indices_i32):
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

    kwargs: dict[str, np.ndarray] = {}
    for usd_name, vertex_name, corner_name, width in (
        ("normals", "vertex_normals", "corner_normals", 3),
        ("primvars:st", "vertex_uvs", "corner_uvs", 2),
    ):
        if usd_name not in properties:
            continue
        array = value_array(
            prim, usd_name, np.dtype(np.float32), copy=copy
        )
        if array.ndim != 2 or array.shape[1:] != (width,):
            raise ValueError(
                f"USD mesh {prim.name!r}: {usd_name!r} has invalid shape"
            )
        if array.size and not np.isfinite(array).all():
            raise ValueError(
                f"USD mesh {prim.name!r}: {usd_name!r} must be finite"
            )
        domain = interpolation(prim, usd_name)
        expected = len(positions) if domain == "vertex" else len(indices_i32)
        if len(array) != expected:
            raise ValueError(
                f"USD mesh {prim.name!r}: {usd_name!r} {domain} count "
                "does not match topology"
            )
        kwargs[vertex_name if domain == "vertex" else corner_name] = array

    if "subdivisionScheme" in properties:
        attribute = prim.get_attribute("subdivisionScheme")
        if attribute is None or attribute.value.to_string() != '"none"':
            raise ValueError(
                f"USD mesh {prim.name!r}: subdivision surfaces are unsupported"
            )
    if "extent" in properties:
        extent = value_array(
            prim, "extent", np.dtype(np.float32), copy=copy
        )
        if extent.shape != (2, 3) or (
            extent.size and not np.isfinite(extent).all()
        ):
            raise ValueError(f"USD mesh {prim.name!r}: invalid extent")

    return positions, counts, indices_i32, kwargs


def mesh_from_prim(
    prim,
    *,
    shell_properties: frozenset[str] = frozenset(),
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
    return _core.mesh(
        positions,
        face_offsets,
        indices,
        coordinate_frame="opengl",
        scale_to_meters=1.0,
        **kwargs,
    )


__all__ = [
    "MESH_PROPERTIES",
    "interpolation",
    "mesh_arrays_from_prim",
    "mesh_from_prim",
    "value_array",
]
