"""Bounded UsdGeomPointInstancer mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from sceneio import _core
from sceneio.io._usd import geometry

INSTANCE_PRIM_TYPE = "PointInstancer"
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
_INACTIVE_IDS = re.compile(
    r"^ {4}(?:(?:prepend|append|add|delete|reorder)\s+)?"
    r"inactiveIds\s*=\s*(?P<value>[^\r\n]+)$",
    re.MULTILINE,
)
_INTERPOLATION = re.compile(r'\binterpolation\s*=\s*"([^"]+)"')
_NONFINITE = re.compile(
    r"(?i)(?<![A-Za-z])(?:[+-]?(?:nan|inf(?:inity)?))(?![A-Za-z])"
)
_INSTANCE_ATTRIBUTES = {
    "velocities": ("velocities", "vector3f[]", 3),
    "accelerations": ("accelerations", "vector3f[]", 3),
    "angular_velocities": ("angularVelocities", "vector3f[]", 3),
    "display_colors": ("primvars:displayColor", "color3f[]", 3),
    "display_opacities": ("primvars:displayOpacity", "float[]", 1),
}
_USD_ATTRIBUTE_NAMES = {value[0] for value in _INSTANCE_ATTRIBUTES.values()}
INSTANCE_PROPERTIES = frozenset(
    {
        "prototypes",
        "protoIndices",
        "ids",
        "positions",
        "orientations",
        "orientationsf",
        "scales",
        "invisibleIds",
        *_USD_ATTRIBUTE_NAMES,
    }
)


@dataclass(frozen=True)
class ParsedInstanceSet:
    prototype_paths: tuple[str, ...]
    prototype_indices: np.ndarray
    translations: np.ndarray
    orientations: np.ndarray
    scales: np.ndarray
    ids: np.ndarray
    invisible_ids: np.ndarray
    attributes: dict[str, np.ndarray]

    def build(self, path_to_node: dict[str, int], *, path: str):
        try:
            prototype_nodes = np.asarray(
                [path_to_node[target] for target in self.prototype_paths],
                dtype=np.uint64,
            )
        except KeyError as exc:
            raise ValueError(
                f"USD PointInstancer {path!r}: prototype {exc.args[0]!r} "
                "does not name a scene prim in the selected SceneGraph"
            ) from None
        return _core.instance_set(
            prototype_nodes,
            self.prototype_indices.astype(np.uint64, copy=False),
            self.translations,
            orientations=self.orientations,
            scales=self.scales,
            ids=self.ids,
            invisible_ids=self.invisible_ids,
            attributes=(
                _core.tensor_dict(self.attributes) if self.attributes else None
            ),
            quaternion_order="wxyz",
        )


@dataclass(frozen=True)
class WritableInstanceSet:
    node: int
    payload: int
    prototype_paths: tuple[str, ...]


def validate_prototype_dependencies(
    dependencies: dict[str, tuple[str, ...]],
    *,
    scene_paths: frozenset[str],
) -> None:
    """Require existing prototypes and an acyclic instancer dependency graph."""

    for path, targets in dependencies.items():
        for target in targets:
            if target not in scene_paths:
                raise ValueError(
                    f"USD PointInstancer {path!r}: prototype {target!r} "
                    "does not name a scene prim"
                )
            if path == target or path.startswith(target + "/"):
                raise ValueError(
                    f"USD PointInstancer {path!r}: prototype {target!r} "
                    "contains the instancer"
                )

    visiting: set[str] = set()
    complete: set[str] = set()

    def visit(path: str) -> None:
        if path in complete:
            return
        if path in visiting:
            raise ValueError("USD: PointInstancer prototype graph contains a cycle")
        visiting.add(path)
        for target in dependencies[path]:
            if target in dependencies:
                visit(target)
        visiting.remove(path)
        complete.add(path)

    for path in dependencies:
        visit(path)


def property_names(prim, *, text: str | None = None) -> set[str]:
    """Return directly authored properties despite provider schema gaps."""

    if text is None:
        text = prim.to_string()
    return {
        match.group("name").removesuffix(".timeSamples")
        for match in _DECLARATION.finditer(text)
    }


def has_time_samples(prim, *, text: str | None = None) -> bool:
    """Report authored samples from normalized text."""

    if text is None:
        text = prim.to_string()
    return _TIME_SAMPLES.search(text) is not None


def _declaration(text: str, name: str, expected_type: str, *, context: str):
    for match in _DECLARATION.finditer(text):
        if match.group("name") != name:
            continue
        if match.group("type") != expected_type:
            raise ValueError(
                f"{context}: {name!r} must have type {expected_type}, not "
                f"{match.group('type')}"
            )
        return match
    raise ValueError(f"{context}: missing {name!r}")


def _array_span(
    text: str,
    name: str,
    expected_type: str,
    *,
    context: str,
) -> tuple[int, int, str | None]:
    declaration = _declaration(text, name, expected_type, context=context)
    start = declaration.end()
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] != "[":
        raise ValueError(f"{context}: {name!r} must be a static array")
    end = text.find("]", start + 1)
    if end < 0:
        raise ValueError(f"{context}: unterminated {name!r} array")
    interpolation = None
    cursor = end + 1
    while cursor < len(text) and text[cursor] in " \t":
        cursor += 1
    if cursor < len(text) and text[cursor] == "(":
        closing = text.find("\n    )", cursor + 1)
        if closing < 0:
            raise ValueError(f"{context}: invalid {name!r} metadata")
        match = _INTERPOLATION.search(text, cursor + 1, closing)
        if match is not None:
            interpolation = match.group(1)
    return start, end, interpolation


def _parse_array(
    text: str,
    name: str,
    expected_type: str,
    dtype,
    *,
    width: int,
    context: str,
) -> tuple[np.ndarray, str | None]:
    start, end, interpolation = _array_span(
        text, name, expected_type, context=context
    )
    encoded = text[start : end + 1]
    normalized = encoded.translate(str.maketrans("[](),", "     "))
    try:
        values = (
            np.empty(0, dtype=dtype)
            if normalized.isspace()
            else np.fromstring(normalized, dtype=dtype, sep=" ")
        )
    except ValueError:
        raise ValueError(f"{context}: invalid values in {name!r}") from None
    if len(values) % width:
        raise ValueError(f"{context}: {name!r} has incomplete rows")
    if width > 1:
        values = values.reshape(-1, width)
    if values.size and not np.isfinite(values).all():
        raise ValueError(f"{context}: {name!r} must be finite")
    return values, interpolation


def _array_count(
    text: str,
    name: str,
    expected_type: str,
    *,
    width: int,
    context: str,
) -> tuple[int, str | None]:
    start, end, interpolation = _array_span(
        text, name, expected_type, context=context
    )
    cursor = start + 1
    while cursor < end and text[cursor].isspace():
        cursor += 1
    if cursor == end:
        return 0, interpolation
    if _NONFINITE.search(text, cursor, end):
        raise ValueError(f"{context}: {name!r} must be finite")
    if width == 1:
        return text.count(",", cursor, end) + 1, interpolation
    rows = text.count("(", cursor, end)
    if rows != text.count(")", cursor, end):
        raise ValueError(f"{context}: {name!r} has incomplete rows")
    return rows, interpolation


def _prototype_paths(text: str, *, context: str) -> tuple[str, ...]:
    declaration = _declaration(text, "prototypes", "rel", context=context)
    end = text.find("\n", declaration.end())
    encoded = text[declaration.end() : end if end >= 0 else len(text)].strip()
    paths = tuple(re.findall(r"<([^<>]+)>", encoded))
    residue = re.sub(r"<[^<>]+>", "", encoded)
    if residue.translate(str.maketrans("", "", "[], \t")):
        raise ValueError(f"{context}: invalid prototypes relationship")
    if len(paths) != len(set(paths)):
        raise ValueError(f"{context}: prototype targets must be unique")
    if any(
        not path.startswith("/") or "." in path.rsplit("/", 1)[-1]
        for path in paths
    ):
        raise ValueError(f"{context}: prototype targets must be absolute prim paths")
    return paths


def prototype_paths(prim, *, path: str, text: str | None = None) -> tuple[str, ...]:
    """Read the ordered prototype relationship without instance expansion."""

    if text is None:
        text = prim.to_string()
    return _prototype_paths(text, context=f"USD PointInstancer {path!r}")


def _validate_metadata(text: str, *, context: str) -> None:
    match = _INACTIVE_IDS.search(text)
    if match is not None and match.group("value").strip() != "[]":
        raise ValueError(
            f"{context}: non-empty inactiveIds metadata is not representable "
            "by InstanceSet.invisible_ids"
        )


def instance_set_from_prim(
    prim,
    *,
    path: str,
    shell_properties: frozenset[str],
    text: str | None = None,
) -> ParsedInstanceSet:
    """Parse one static point instancer into owning numeric arrays."""

    if text is None:
        text = prim.to_string()
    context = f"USD PointInstancer {path!r}"
    properties = property_names(prim, text=text)
    unsupported = sorted(properties - INSTANCE_PROPERTIES - shell_properties)
    if unsupported:
        raise ValueError(
            f"{context}: unsupported properties: " + ", ".join(unsupported)
        )
    _validate_metadata(text, context=context)
    required = {"prototypes", "protoIndices", "positions"}
    missing = sorted(required - properties)
    if missing:
        raise ValueError(
            f"{context}: missing required properties: " + ", ".join(missing)
        )
    targets = _prototype_paths(text, context=context)
    prototype_indices, _ = _parse_array(
        text,
        "protoIndices",
        "int[]",
        np.int64,
        width=1,
        context=context,
    )
    if prototype_indices.size and (
        int(prototype_indices.min()) < 0
        or int(prototype_indices.max()) >= len(targets)
    ):
        raise ValueError(f"{context}: protoIndices are out of range")
    positions, _ = _parse_array(
        text,
        "positions",
        "point3f[]",
        np.float32,
        width=3,
        context=context,
    )
    count = len(prototype_indices)
    if len(positions) != count:
        raise ValueError(f"{context}: positions count must match protoIndices")
    if "orientationsf" in properties:
        orientations, _ = _parse_array(
            text,
            "orientationsf",
            "quatf[]",
            np.float32,
            width=4,
            context=context,
        )
    elif "orientations" in properties:
        orientations, _ = _parse_array(
            text,
            "orientations",
            "quath[]",
            np.float32,
            width=4,
            context=context,
        )
    else:
        orientations = np.zeros((count, 4), np.float32)
        orientations[:, 0] = 1.0
    if len(orientations) != count:
        raise ValueError(f"{context}: orientations count must match protoIndices")
    if count:
        norms = np.linalg.norm(orientations.astype(np.float64), axis=1)
        tolerance = (
            5e-3
            if "orientations" in properties
            and "orientationsf" not in properties
            else 1e-5
        )
        if not np.allclose(norms, 1.0, rtol=tolerance, atol=tolerance):
            raise ValueError(f"{context}: orientation quaternions must be unit length")
    if "scales" in properties:
        scales, _ = _parse_array(
            text,
            "scales",
            "float3[]",
            np.float32,
            width=3,
            context=context,
        )
    else:
        scales = np.ones((count, 3), np.float32)
    if len(scales) != count:
        raise ValueError(f"{context}: scales count must match protoIndices")
    if "ids" in properties:
        ids, _ = _parse_array(
            text, "ids", "int64[]", np.int64, width=1, context=context
        )
    else:
        ids = np.arange(count, dtype=np.int64)
    if len(ids) != count:
        raise ValueError(f"{context}: ids count must match protoIndices")
    if "invisibleIds" in properties:
        invisible_ids, _ = _parse_array(
            text,
            "invisibleIds",
            "int64[]",
            np.int64,
            width=1,
            context=context,
        )
    else:
        invisible_ids = np.empty(0, np.int64)

    attributes: dict[str, np.ndarray] = {}
    for key, (usd_name, expected_type, width) in _INSTANCE_ATTRIBUTES.items():
        if usd_name not in properties:
            continue
        values, interpolation = _parse_array(
            text,
            usd_name,
            expected_type,
            np.float32,
            width=width,
            context=context,
        )
        if len(values) != count:
            raise ValueError(f"{context}: {usd_name!r} count must match protoIndices")
        if usd_name.startswith("primvars:") and interpolation != "instance":
            raise ValueError(
                f"{context}: {usd_name!r} interpolation must be 'instance'"
            )
        if key == "display_opacities" and (
            np.any(values < 0) or np.any(values > 1)
        ):
            raise ValueError(f"{context}: display opacity must be in [0, 1]")
        attributes[key] = values
    return ParsedInstanceSet(
        prototype_paths=targets,
        prototype_indices=prototype_indices,
        translations=positions,
        orientations=orientations,
        scales=scales,
        ids=ids,
        invisible_ids=invisible_ids,
        attributes=attributes,
    )


def inspect_instance_prim(
    prim,
    *,
    path: str,
    shell_properties: frozenset[str],
    text: str | None = None,
) -> tuple[int, int]:
    """Validate array structure and return instance/prototype counts."""

    if text is None:
        text = prim.to_string()
    context = f"USD PointInstancer {path!r}"
    properties = property_names(prim, text=text)
    unsupported = sorted(properties - INSTANCE_PROPERTIES - shell_properties)
    if unsupported:
        raise ValueError(
            f"{context}: unsupported properties: " + ", ".join(unsupported)
        )
    _validate_metadata(text, context=context)
    missing = sorted({"prototypes", "protoIndices", "positions"} - properties)
    if missing:
        raise ValueError(
            f"{context}: missing required properties: " + ", ".join(missing)
        )
    prototypes = _prototype_paths(text, context=context)
    count, _ = _array_count(
        text, "protoIndices", "int[]", width=1, context=context
    )
    position_count, _ = _array_count(
        text, "positions", "point3f[]", width=3, context=context
    )
    if position_count != count:
        raise ValueError(f"{context}: positions count must match protoIndices")
    for name, expected_type, width in (
        ("ids", "int64[]", 1),
        ("orientations", "quath[]", 4),
        ("orientationsf", "quatf[]", 4),
        ("scales", "float3[]", 3),
        ("invisibleIds", "int64[]", 1),
        *((value[0], value[1], value[2]) for value in _INSTANCE_ATTRIBUTES.values()),
    ):
        if name not in properties:
            continue
        value_count, interpolation = _array_count(
            text, name, expected_type, width=width, context=context
        )
        if name != "invisibleIds" and value_count != count:
            raise ValueError(f"{context}: {name!r} count must match protoIndices")
        if name.startswith("primvars:") and interpolation != "instance":
            raise ValueError(f"{context}: {name!r} interpolation must be 'instance'")
    return count, len(prototypes)


def validate_writable_instances(
    scene,
    *,
    payload_kinds: tuple[str, ...],
    payload_indices,
    node_paths: tuple[str, ...],
) -> tuple[WritableInstanceSet, ...]:
    """Guard the closed InstanceSet attribute vocabulary."""

    used: set[int] = set()
    rows: list[WritableInstanceSet] = []
    for node, kind in enumerate(payload_kinds):
        if kind != "instances":
            continue
        payload = int(payload_indices[node])
        if payload in used:
            raise ValueError(
                f"USD: instances payload {payload} is referenced by multiple nodes"
            )
        used.add(payload)
        value = scene.instance_set_at(payload)
        prototype_nodes = np.asarray(value.prototype_nodes)
        if np.any(prototype_nodes == node):
            raise ValueError("USD: PointInstancer cannot use itself as a prototype")
        prototype_paths = tuple(node_paths[int(index)] for index in prototype_nodes)
        orientations = np.asarray(value.orientations)
        if len(orientations):
            norms = np.linalg.norm(orientations.astype(np.float64), axis=1)
            if not np.allclose(norms, 1.0, rtol=1e-5, atol=1e-5):
                raise ValueError(
                    "USD: PointInstancer orientation quaternions must be unit length"
                )
        keys = tuple(value.attributes.keys()) if value.has_attributes else ()
        unsupported = sorted(set(keys) - set(_INSTANCE_ATTRIBUTES))
        if unsupported:
            raise ValueError(
                "USD: unsupported PointInstancer attributes: "
                + ", ".join(unsupported)
            )
        for key in keys:
            array = np.asarray(value.attributes[key])
            width = _INSTANCE_ATTRIBUTES[key][2]
            expected_shape = (
                (value.num_instances,)
                if width == 1
                else (value.num_instances, width)
            )
            if array.dtype != np.dtype(np.float32) or array.shape != expected_shape:
                raise ValueError(
                    f"USD: PointInstancer attribute {key!r} must be "
                    f"{expected_shape} float32"
                )
            if key == "display_opacities" and (
                np.any(array < 0) or np.any(array > 1)
            ):
                raise ValueError(
                    "USD: PointInstancer display opacity must be in [0, 1]"
                )
        rows.append(
            WritableInstanceSet(
                node=node,
                payload=payload,
                prototype_paths=prototype_paths,
            )
        )
    if used != set(range(scene.num_instance_sets)):
        raise ValueError(
            "USD: every instances payload must be referenced exactly once"
        )
    validate_prototype_dependencies(
        {
            node_paths[row.node]: row.prototype_paths
            for row in rows
        },
        scene_paths=frozenset(node_paths),
    )
    return tuple(rows)


def write_instance_attributes(
    stream,
    value,
    row: WritableInstanceSet,
    *,
    inner: str,
) -> None:
    """Stream the closed static PointInstancer attribute subset."""

    stream.write(f"{inner}rel prototypes = [")
    stream.write(", ".join(f"<{path}>" for path in row.prototype_paths))
    stream.write("]\n")
    stream.write(f"{inner}int[] protoIndices = ")
    geometry.write_scalars(stream, np.asarray(value.prototype_indices), integer=True)
    stream.write("\n")
    stream.write(f"{inner}point3f[] positions = ")
    geometry.write_rows(stream, np.asarray(value.translations))
    stream.write("\n")
    orientations = np.asarray(value.orientations)
    if value.quaternion_order == "xyzw":
        orientations = orientations[:, [3, 0, 1, 2]]
    stream.write(f"{inner}quatf[] orientationsf = ")
    geometry.write_rows(stream, orientations)
    stream.write("\n")
    stream.write(f"{inner}float3[] scales = ")
    geometry.write_rows(stream, np.asarray(value.scales))
    stream.write("\n")
    stream.write(f"{inner}int64[] ids = ")
    geometry.write_scalars(stream, np.asarray(value.ids), integer=True)
    stream.write("\n")
    if len(value.invisible_ids):
        stream.write(f"{inner}int64[] invisibleIds = ")
        geometry.write_scalars(stream, np.asarray(value.invisible_ids), integer=True)
        stream.write("\n")
    if value.has_attributes:
        for key, (usd_name, declaration, width) in _INSTANCE_ATTRIBUTES.items():
            if key not in value.attributes:
                continue
            array = np.asarray(value.attributes[key])
            stream.write(f"{inner}{declaration} {usd_name} = ")
            if width == 1:
                geometry.write_scalars(stream, array)
            else:
                geometry.write_rows(stream, array)
            if usd_name.startswith("primvars:"):
                stream.write(
                    f' (\n{inner}    interpolation = "instance"\n{inner})'
                )
            stream.write("\n")


__all__ = [
    "INSTANCE_PRIM_TYPE",
    "INSTANCE_PROPERTIES",
    "ParsedInstanceSet",
    "WritableInstanceSet",
    "has_time_samples",
    "inspect_instance_prim",
    "instance_set_from_prim",
    "property_names",
    "prototype_paths",
    "validate_prototype_dependencies",
    "validate_writable_instances",
    "write_instance_attributes",
]
