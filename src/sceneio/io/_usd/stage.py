"""Rich SceneGraph mapping for the bounded USD 3D-CV stage skeleton."""

from __future__ import annotations

import math
import os
import re
from contextlib import suppress
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.model import Inspection
from sceneio.io._usd import (
    cameras,
    gaussians,
    geometry,
    materials,
    package,
    points,
    provider,
)

_IDENTITY = np.eye(4, dtype=np.float64)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_TOKEN_ATTRIBUTE = re.compile(
    r'^ {4}(?:uniform\s+)?token\s+'
    r'(visibility|purpose)\s*=\s*"([^"]+)"\s*$',
    re.MULTILINE,
)
_VISIBILITY = frozenset({"inherited", "invisible"})
_PURPOSES = frozenset({"default", "render", "proxy", "guide"})
_IMAGEABLE_PROPERTIES = frozenset({"purpose", "visibility"})
_PENDING_PAYLOAD_TYPES = {
    cameras.CAMERA_PRIM_TYPE: "camera",
    gaussians.GAUSSIAN_PRIM_TYPE: "gaussian",
    **{name: "material" for name in materials.MATERIAL_PRIM_TYPES},
}
_USDA_FEATURES = re.compile(
    rb"""
    \#[^\r\n]*
    | "(?:\\[\s\S]|[^"\\])*"
    | @([^@\r\n]{1,65536})@
    | (?<![A-Za-z0-9_:])
      (subLayers|references|payload|variantSet|variants)
      (?![A-Za-z0-9_:])
    """,
    re.VERBOSE,
)
_BINARY_COMPOSITION_TOKENS = {
    "sublayers": (b"subLayers",),
    "references": (b"references",),
    "payloads": (b"payload",),
    "variants": (b"variantSet", b"variants"),
}
_FEATURE_NAMES = {
    b"subLayers": "sublayers",
    b"references": "references",
    b"payload": "payloads",
    b"variantSet": "variants",
    b"variants": "variants",
}


def _scan_authored_features(
    path: str | os.PathLike[str],
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Stream the root layer for arcs and delimited asset references."""

    features: set[str] = set()
    dependencies: set[str] = set()

    def scan(data, start: int = 0, end: int | None = None) -> None:
        if end is None:
            end = len(data)
        if data[start : min(start + 8, end)] == b"PXR-USDC":
            for name, tokens in _BINARY_COMPOSITION_TOKENS.items():
                if name not in features and any(
                    data.find(token, start, end) >= 0 for token in tokens
                ):
                    features.add(name)
            return
        for match in _USDA_FEATURES.finditer(data, start, end):
            asset = match.group(1)
            if asset is not None:
                dependencies.add(
                    asset.decode("utf-8", errors="surrogateescape")
                )
                continue
            token = match.group(2)
            if token is not None:
                features.add(_FEATURE_NAMES[token])

    with package.mapped_root_layer(path) as mapped_root:
        if mapped_root is not None:
            mapped, start, end = mapped_root
            scan(mapped, start, end)
            return frozenset(features), tuple(sorted(dependencies))

    carry = b""
    for chunk in package.iter_root_layer_chunks(path):
        data = carry + chunk
        scan(data)
        carry = data[-65537:]
    return frozenset(features), tuple(sorted(dependencies))


def _metadata_float(stage, name: str, default: float) -> float:
    value = stage.get_metadata(name)
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"USD: {name} must be numeric") from None
    if not math.isfinite(result):
        raise ValueError(f"USD: {name} must be finite")
    return result


def _stage_metadata(stage) -> dict[str, object]:
    up_axis_value = stage.get_metadata("upAxis")
    up_axis = "y" if up_axis_value is None else str(up_axis_value).lower()
    if up_axis not in {"y", "z"}:
        raise ValueError("USD: upAxis must be 'Y' or 'Z'")
    meters = _metadata_float(stage, "metersPerUnit", 0.01)
    if meters <= 0:
        raise ValueError("USD: metersPerUnit must be positive")
    start_value = stage.get_metadata("startTimeCode")
    end_value = stage.get_metadata("endTimeCode")
    if (start_value is None) != (end_value is None):
        raise ValueError(
            "USD: startTimeCode and endTimeCode must be authored together"
        )
    start = (
        None
        if start_value is None
        else _metadata_float(stage, "startTimeCode", 0.0)
    )
    end = (
        None
        if end_value is None
        else _metadata_float(stage, "endTimeCode", 0.0)
    )
    if start is not None and start > end:
        raise ValueError("USD: startTimeCode must not exceed endTimeCode")
    time_codes = _metadata_float(stage, "timeCodesPerSecond", 24.0)
    if time_codes <= 0:
        raise ValueError("USD: timeCodesPerSecond must be positive")
    return {
        "up_axis": up_axis,
        "meters_per_unit": meters,
        "start_time_code": start,
        "end_time_code": end,
        "time_codes_per_second": time_codes,
    }


def _authored_imageable_tokens(
    prim,
    *,
    point_text: str | None = None,
) -> tuple[str, str | None]:
    text = prim.to_string() if point_text is None else point_text
    values = {
        name: value for name, value in _TOKEN_ATTRIBUTE.findall(text)
    }
    visibility = values.get("visibility", "inherited")
    purpose = values.get("purpose")
    if visibility not in _VISIBILITY:
        raise ValueError(
            f"USD prim {prim.name!r}: unsupported visibility {visibility!r}"
        )
    if purpose is not None and purpose not in _PURPOSES:
        raise ValueError(
            f"USD prim {prim.name!r}: unsupported purpose {purpose!r}"
        )
    return visibility, purpose


def _render_nodes(stage) -> dict[str, tuple[np.ndarray, bool]]:
    tinyusdz = provider.require_tinyusdz()
    try:
        rendered = tinyusdz.tydra.convert_to_render_scene(stage)
    except Exception as exc:
        raise ValueError(
            f"USD: provider could not evaluate static transforms: {exc}"
        ) from exc
    result: dict[str, tuple[np.ndarray, bool]] = {}
    pending = list(reversed(rendered.nodes()))
    while pending:
        node = pending.pop()
        matrix = np.asarray(node.local_matrix, dtype=np.float64)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise ValueError(
                f"USD prim {node.abs_path!r}: invalid local transform"
            )
        result[str(node.abs_path)] = (
            np.array(matrix, copy=True, order="C"),
            bool(node.has_reset_xform),
        )
        pending.extend(reversed(node.children()))
    return result


def _has_time_samples(prim, *, point_text: str | None = None) -> bool:
    if prim.type_name == "Points":
        return points.has_time_samples(prim, text=point_text)
    return any(
        bool(prim.get_attribute_timesamples(name))
        for name in prim.property_names()
    )


def _property_names(prim, *, point_text: str | None = None) -> set[str]:
    if prim.type_name == "Points":
        return points.property_names(prim, text=point_text)
    return set(prim.property_names())


def _payload_shell_properties(
    prim,
    *,
    point_text: str | None = None,
) -> frozenset[str]:
    return _IMAGEABLE_PROPERTIES | frozenset(
        name
        for name in _property_names(prim, point_text=point_text)
        if name == "xformOpOrder" or name.startswith("xformOp:")
    )


def _validate_shell(
    prim,
    path: str,
    *,
    point_text: str | None = None,
) -> None:
    if prim.type_name not in {"Xform", "Scope", "Mesh", "Points"}:
        category = _PENDING_PAYLOAD_TYPES.get(prim.type_name)
        if category is not None:
            raise ValueError(
                f"USD: prim {path!r} uses the {category} payload mapping "
                "scheduled after the stage skeleton"
            )
        raise ValueError(
            f"USD: prim {path!r} has unsupported type {prim.type_name!r}"
        )
    if not isinstance(prim.name, str) or not _IDENTIFIER.fullmatch(prim.name):
        raise ValueError(
            f"USD: prim name {prim.name!r} is not a portable identifier"
        )
    properties = _property_names(prim, point_text=point_text)
    xform_properties = {
        name
        for name in properties
        if name == "xformOpOrder" or name.startswith("xformOp:")
    }
    allowed = _IMAGEABLE_PROPERTIES | xform_properties
    if prim.type_name == "Mesh":
        allowed |= geometry.MESH_PROPERTIES
    if prim.type_name == "Points":
        allowed |= points.POINT_PROPERTIES
    if prim.type_name == "Scope":
        allowed = _IMAGEABLE_PROPERTIES
    unsupported = sorted(properties - allowed)
    if unsupported:
        raise ValueError(
            f"USD prim {path!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    if prim.type_name == "Scope" and xform_properties:
        raise ValueError(
            f"USD prim {path!r}: transforms on {prim.type_name} "
            "are not in the stage-skeleton profile"
        )


def _normalize_prim_selection(
    prims: object,
    all_paths: frozenset[str],
) -> frozenset[str] | None:
    if prims is None:
        return None
    values = [prims] if isinstance(prims, str) else list(prims)
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.startswith("/"):
            raise ValueError("USD: prim selections must be absolute paths")
        path = value.rstrip("/") or "/"
        if path == "/" or path not in all_paths:
            raise ValueError(f"USD: selected prim {value!r} does not exist")
        normalized.add(path)
    return frozenset(normalized)


def _include_path(path: str, selected: frozenset[str] | None) -> bool:
    if selected is None:
        return True
    return any(
        path == item
        or path.startswith(item + "/")
        or item.startswith(path + "/")
        for item in selected
    )


def _select_payload(path: str, selected: frozenset[str] | None) -> bool:
    if selected is None:
        return True
    return any(path == item or path.startswith(item + "/") for item in selected)


def stage_to_scene_graph(
    stage,
    *,
    source_representation: str,
    time: float | None = None,
    prims: object = None,
    purposes: tuple[str, ...] = ("default", "render", "proxy"),
    variants: object = None,
    load_payloads: bool = True,
):
    """Map one qualified, directly-authored stage into an owning SceneGraph."""

    if variants not in (None, {}):
        raise ValueError("USD: variant selection is not available in this profile")
    if not isinstance(load_payloads, bool):
        raise TypeError("USD: load_payloads must be bool")
    if time is not None:
        time = float(time)
        if not math.isfinite(time):
            raise ValueError("USD: selected time must be finite")
    selected_purposes = tuple(purposes)
    if any(item not in _PURPOSES for item in selected_purposes):
        raise ValueError(
            "USD: purposes must contain only default/render/proxy/guide"
        )
    metadata = _stage_metadata(stage)
    render_nodes = _render_nodes(stage)

    roots = list(stage.root_prims())
    if len({prim.name for prim in roots}) != len(roots):
        raise ValueError("USD: root prim names must be unique")
    all_paths: set[str] = set()

    def collect(prim, parent_path: str) -> None:
        path = f"{parent_path}/{prim.name}"
        if path in all_paths:
            raise ValueError(f"USD: duplicate prim path {path!r}")
        all_paths.add(path)
        children = list(prim.children())
        if len({child.name for child in children}) != len(children):
            raise ValueError(
                f"USD prim {path!r}: child names must be unique"
            )
        for child in children:
            collect(child, path)

    for root in roots:
        collect(root, "")
    selected = _normalize_prim_selection(prims, frozenset(all_paths))

    node_names: list[str] = []
    node_transforms: list[np.ndarray] = []
    node_resets: list[int] = []
    node_visibility: list[str] = []
    node_purpose: list[str] = []
    node_payload_kinds: list[str] = []
    node_payload_indices: list[int] = []
    child_lists: list[list[int]] = []
    meshes = []
    point_clouds = []
    path_to_node: dict[str, int] = {}
    no_payload = np.iinfo(np.uint64).max

    def visit(prim, parent_path: str, inherited_purpose: str) -> int | None:
        path = f"{parent_path}/{prim.name}"
        if not _include_path(path, selected):
            return None
        point_text = prim.to_string() if prim.type_name == "Points" else None
        _validate_shell(prim, path, point_text=point_text)
        if _has_time_samples(prim, point_text=point_text):
            raise ValueError(
                f"USD prim {path!r}: selected-time value evaluation "
                "is not available with the qualified provider"
            )
        visibility, authored_purpose = _authored_imageable_tokens(
            prim,
            point_text=point_text,
        )
        effective_purpose = authored_purpose or inherited_purpose
        index = len(node_names)
        path_to_node[path] = index
        node_names.append(prim.name)
        node_visibility.append(visibility)
        node_purpose.append(effective_purpose)
        node_payload_kinds.append("none")
        node_payload_indices.append(no_payload)
        child_lists.append([])
        if prim.type_name != "Scope":
            try:
                transform, resets = render_nodes[path]
            except KeyError:
                raise ValueError(
                    f"USD prim {path!r}: transform evaluation is unavailable"
                ) from None
            node_transforms.append(transform)
            node_resets.append(int(resets))
        else:
            node_transforms.append(_IDENTITY.copy())
            node_resets.append(0)
        if (
            prim.type_name == "Mesh"
            and load_payloads
            and effective_purpose in selected_purposes
            and _select_payload(path, selected)
        ):
            node_payload_kinds[index] = "mesh"
            node_payload_indices[index] = len(meshes)
            meshes.append(
                geometry.mesh_from_prim(
                    prim,
                    shell_properties=_payload_shell_properties(
                        prim,
                        point_text=point_text,
                    ),
                    coordinate_frame=(
                        "opengl"
                        if metadata["up_axis"] == "y"
                        else "enu"
                    ),
                    scale_to_meters=metadata["meters_per_unit"],
                )
            )
        if (
            prim.type_name == "Points"
            and load_payloads
            and effective_purpose in selected_purposes
            and _select_payload(path, selected)
        ):
            node_payload_kinds[index] = "point_cloud"
            node_payload_indices[index] = len(point_clouds)
            point_positions, point_kwargs = points.point_arrays_from_prim(
                prim,
                shell_properties=_payload_shell_properties(
                    prim,
                    point_text=point_text,
                ),
                coordinate_frame=(
                    "opengl" if metadata["up_axis"] == "y" else "enu"
                ),
                scale_to_meters=metadata["meters_per_unit"],
                text=point_text,
            )
            # The normalized provider text can be many megabytes. Release it
            # before the owning native record copies the parsed arrays.
            point_text = None
            point_clouds.append(_core.point_cloud(point_positions, **point_kwargs))
            del point_positions, point_kwargs
        point_text = None
        for child in prim.children():
            child_index = visit(child, path, effective_purpose)
            if child_index is not None:
                child_lists[index].append(child_index)
        return index

    for root in roots:
        visit(root, "", "default")

    offsets = np.empty(len(child_lists) + 1, dtype=np.uint64)
    offsets[0] = 0
    flat_children: list[int] = []
    for index, children in enumerate(child_lists, start=1):
        flat_children.extend(children)
        offsets[index] = len(flat_children)

    default_name = stage.get_metadata("defaultPrim")
    default_prim = None
    if default_name is not None:
        default_path = f"/{default_name}"
        if default_path not in all_paths:
            raise ValueError("USD: defaultPrim must name an existing root prim")
        default_prim = path_to_node.get(default_path)

    return _core.scene_graph(
        node_names,
        node_child_offsets=offsets,
        node_children=np.asarray(flat_children, dtype=np.uint64),
        node_local_transforms=np.asarray(
            node_transforms, dtype=np.float64
        ).reshape(-1, 4, 4),
        node_resets_transform_stack=np.asarray(node_resets, dtype=np.uint8),
        node_payload_kinds=node_payload_kinds,
        node_payload_indices=np.asarray(node_payload_indices, dtype=np.uint64),
        node_visibility=node_visibility,
        node_purpose=node_purpose,
        meshes=meshes,
        point_clouds=point_clouds,
        source_representation=source_representation,
        default_prim=default_prim,
        selected_time=time,
        **metadata,
    )


def read_scene(
    path: str | os.PathLike[str],
    *,
    time: float | None = None,
    prims: object = None,
    purposes: tuple[str, ...] = ("default", "render", "proxy"),
    variants: object = None,
    load_payloads: bool = True,
):
    """Read the bounded directly-authored USD profile as a SceneGraph."""

    composition, _ = _scan_authored_features(path)
    if composition:
        raise ValueError(
            "USD: evaluated composition is not available in the stage "
            "skeleton: "
            + ", ".join(sorted(composition))
        )
    stage = provider.load_stage(path)
    return stage_to_scene_graph(
        stage,
        source_representation=provider.source_representation(path),
        time=time,
        prims=prims,
        purposes=purposes,
        variants=variants,
        load_payloads=load_payloads,
    )


def inspect_scene(
    path: str | os.PathLike[str],
    *,
    format_id: str,
) -> Inspection:
    """Inspect stage structure and compatibility without building records."""

    stage = provider.load_stage(path)
    metadata = _stage_metadata(stage)
    representation = provider.source_representation(path)
    authored_features, dependencies = _scan_authored_features(path)
    dependency_set = set(dependencies)
    unsupported: set[str] = set(authored_features)

    type_counts: dict[str, int] = {}
    variants: list[str] = []
    node_count = 0
    primitive_count = 0
    vertices = 0
    faces = 0

    def visit(prim, parent_path: str) -> None:
        nonlocal faces, node_count, primitive_count, vertices
        path_value = f"{parent_path}/{prim.name}"
        node_count += 1
        type_name = str(prim.type_name)
        type_counts[type_name] = type_counts.get(type_name, 0) + 1
        for set_name in prim.variant_sets():
            selection = prim.variant_selection(set_name)
            variants.append(
                f"{path_value}:{set_name}="
                f"{'' if selection is None else selection}"
            )
        point_text = prim.to_string() if prim.type_name == "Points" else None
        for property_name in _property_names(prim, point_text=point_text):
            attribute = prim.get_attribute(property_name)
            if (
                attribute is not None
                and attribute.type_name in {"asset", "asset[]"}
                and attribute.value is not None
            ):
                for match in re.findall(
                    r"@([^@\r\n]+)@",
                    attribute.value.to_string(),
                ):
                    dependency_set.add(match)
        try:
            _validate_shell(prim, path_value, point_text=point_text)
        except ValueError as exc:
            unsupported.add(f"{path_value}: {exc}")
        else:
            if _has_time_samples(prim, point_text=point_text):
                unsupported.add(f"{path_value}: time_samples")
            if prim.type_name == "Mesh":
                try:
                    positions, counts, _, _ = geometry.mesh_arrays_from_prim(
                        prim,
                        copy=False,
                        expand=False,
                        shell_properties=_payload_shell_properties(
                            prim,
                            point_text=point_text,
                        ),
                    )
                except ValueError as exc:
                    unsupported.add(f"{path_value}: {exc}")
                else:
                    vertices += len(positions)
                    faces += len(counts)
                    primitive_count += 1
            elif prim.type_name == "Points":
                try:
                    point_count = points.inspect_point_prim(
                        prim,
                        shell_properties=_payload_shell_properties(
                            prim,
                            point_text=point_text,
                        ),
                        text=point_text,
                    )
                except ValueError as exc:
                    unsupported.add(f"{path_value}: {exc}")
                else:
                    vertices += point_count
                    primitive_count += 1
        point_text = None
        for child in prim.children():
            visit(child, path_value)

    for root in stage.root_prims():
        visit(root, "")

    mesh_projection_available = not unsupported and all(
        name in {"Xform", "Scope", "Mesh"} for name in type_counts
    )
    details: dict[str, object] = {
        "node_count": node_count,
        "primitive_count": primitive_count,
        "face_count": faces,
        "scene_count": 1,
        "representation": representation,
        "up_axis": metadata["up_axis"],
        "meters_per_unit": metadata["meters_per_unit"],
        "time_codes_per_second": metadata["time_codes_per_second"],
        "mesh_projection_available": mesh_projection_available,
        "prim_type_counts": tuple(
            f"{name}={count}" for name, count in sorted(type_counts.items())
        ),
        "dependencies": tuple(sorted(dependency_set)),
        "variants": tuple(sorted(variants)),
        "unsupported_features": tuple(sorted(unsupported)),
    }
    default_prim = stage.get_metadata("defaultPrim")
    if default_prim is not None:
        details["default_prim"] = str(default_prim)
    if metadata["start_time_code"] is not None:
        details["time_range"] = (
            metadata["start_time_code"],
            metadata["end_time_code"],
        )
    prefix = package.root_layer_prefix(path)
    if prefix.startswith(provider.USDC_MAGIC) and len(prefix) >= 10:
        details["crate_version"] = int(prefix[9])

    return Inspection(
        format=format_id,
        datatype="mesh_scene" if mesh_projection_available else "scene_graph",
        byte_size=Path(path).stat().st_size,
        shape=(vertices, 3),
        dtype="float32" if primitive_count else None,
        count=primitive_count,
        metadata=details,
    )


def _float(value: object) -> str:
    return format(float(value), ".17g")


def _write_matrix(stream, matrix: np.ndarray) -> None:
    stream.write("(")
    for row_index, row in enumerate(matrix):
        if row_index:
            stream.write(", ")
        stream.write("(" + ", ".join(_float(value) for value in row) + ")")
    stream.write(")")


def _validate_writable_scene(scene) -> tuple[object, ...]:
    if not isinstance(scene, _core.SceneGraph):
        raise TypeError("USD: write_scene expects a SceneGraph")
    payload_kinds = tuple(scene.node_payload_kinds)
    unsupported_payloads = sorted(
        {kind for kind in payload_kinds if kind not in {"none", "mesh", "point_cloud"}}
    )
    if unsupported_payloads:
        raise ValueError(
            "USD: rich payload writing is not available for: "
            + ", ".join(unsupported_payloads)
        )
    if scene.has_materials or scene.external_asset_uris:
        raise ValueError(
            "USD: materials and external assets are not available "
            "in the stage-skeleton profile"
        )
    if any(scene.node_semantic_taxonomies) or any(scene.node_semantic_labels):
        raise ValueError(
            "USD: semantic labels are not available in the stage-skeleton profile"
        )
    names = tuple(scene.node_names)
    for name in names:
        if not _IDENTIFIER.fullmatch(name):
            raise ValueError(
                f"USD: node name {name!r} is not a portable identifier"
            )
    visibility = tuple(scene.node_visibility)
    if "visible" in visibility:
        raise ValueError(
            "USD: authored visibility supports inherited/invisible, not visible"
        )
    transforms = np.asarray(scene.node_local_transforms)
    resets = np.asarray(scene.node_resets_transform_stack)
    parents = np.asarray(scene.node_parents)
    offsets = np.asarray(scene.node_child_offsets)
    children = np.asarray(scene.node_children)
    payload_indices = np.asarray(scene.node_payload_indices)
    used_meshes: set[int] = set()
    used_points: set[int] = set()
    for node, kind in enumerate(payload_kinds):
        if kind == "none":
            continue
        index = int(payload_indices[node])
        used = used_meshes if kind == "mesh" else used_points
        if index in used:
            raise ValueError(
                f"USD: {kind} payload {index} is referenced by multiple nodes"
            )
        used.add(index)
        context = f"node {node} {kind} payload {index}"
        if kind == "mesh":
            geometry.validate_writable_mesh(
                scene.mesh_at(index),
                up_axis=scene.up_axis,
                meters_per_unit=scene.meters_per_unit,
                context=context,
            )
        else:
            points.validate_writable_point_cloud(
                scene.point_cloud_at(index),
                up_axis=scene.up_axis,
                meters_per_unit=scene.meters_per_unit,
                context=context,
            )
    if used_meshes != set(range(scene.num_meshes)):
        raise ValueError("USD: every mesh payload must be referenced exactly once")
    if used_points != set(range(scene.num_point_clouds)):
        raise ValueError(
            "USD: every point-cloud payload must be referenced exactly once"
        )
    return (
        transforms,
        resets,
        parents,
        offsets,
        children,
        payload_kinds,
        payload_indices,
    )


def _write_scene_usda(scene, stream) -> None:
    (
        transforms,
        resets,
        parents,
        offsets,
        children,
        payload_kinds,
        payload_indices,
    ) = _validate_writable_scene(scene)
    stream.write("#usda 1.0\n(\n")
    if scene.default_prim >= 0:
        stream.write(
            f'    defaultPrim = "{scene.node_names[scene.default_prim]}"\n'
        )
    stream.write(f'    upAxis = "{scene.up_axis.upper()}"\n')
    stream.write(f"    metersPerUnit = {_float(scene.meters_per_unit)}\n")
    if scene.start_time_code is not None:
        stream.write(
            f"    startTimeCode = {_float(scene.start_time_code)}\n"
            f"    endTimeCode = {_float(scene.end_time_code)}\n"
        )
    if (
        scene.start_time_code is not None
        or scene.time_codes_per_second != 24.0
    ):
        stream.write(
            "    timeCodesPerSecond = "
            f"{_float(scene.time_codes_per_second)}\n"
        )
    stream.write(")\n")

    def write_node(node: int, indent: str) -> None:
        if indent == "":
            stream.write("\n")
        kind = payload_kinds[node]
        type_name = {
            "none": "Xform",
            "mesh": "Mesh",
            "point_cloud": "Points",
        }[kind]
        stream.write(
            f'{indent}def {type_name} "{scene.node_names[node]}"\n'
            f"{indent}{{\n"
        )
        inner = indent + "    "
        matrix = transforms[node]
        reset = bool(resets[node])
        if not np.array_equal(matrix, _IDENTITY):
            stream.write(f"{inner}matrix4d xformOp:transform = ")
            _write_matrix(stream, matrix)
            stream.write("\n")
        if reset or not np.array_equal(matrix, _IDENTITY):
            tokens = []
            if reset:
                tokens.append('"!resetXformStack!"')
            if not np.array_equal(matrix, _IDENTITY):
                tokens.append('"xformOp:transform"')
            stream.write(
                f"{inner}uniform token[] xformOpOrder = "
                f"[{', '.join(tokens)}]\n"
            )
        visibility = scene.node_visibility[node]
        if visibility != "inherited":
            stream.write(f'{inner}token visibility = "{visibility}"\n')
        purpose = scene.node_purpose[node]
        if purpose != "default":
            stream.write(f'{inner}uniform token purpose = "{purpose}"\n')
        if kind == "mesh":
            geometry.write_mesh_attributes(
                stream,
                scene.mesh_at(int(payload_indices[node])),
                inner=inner,
            )
        elif kind == "point_cloud":
            points.write_point_attributes(
                stream,
                scene.point_cloud_at(int(payload_indices[node])),
                inner=inner,
            )
        begin, end = int(offsets[node]), int(offsets[node + 1])
        for child in children[begin:end]:
            stream.write("\n")
            write_node(int(child), inner)
        stream.write(f"{indent}}}\n")

    for node in np.flatnonzero(parents == -1):
        write_node(int(node), "")


def _selected_encoding(destination: Path, encoding: str | None) -> str:
    suffix = destination.suffix.lower()
    if suffix not in {".usd", ".usda", ".usdc", ".usdz"}:
        raise ValueError(
            "USD: destination suffix must be .usd, .usda, .usdc, or .usdz"
        )
    selected = (
        ("usdz" if suffix == ".usdz" else "usdc" if suffix == ".usdc" else "usda")
        if encoding is None
        else str(encoding).lower()
    )
    if selected not in {"usda", "usdc", "usdz"}:
        raise ValueError("USD: encoding must be usda, usdc, or usdz")
    if suffix == ".usda" and selected != "usda":
        raise ValueError("USD: .usda destinations require usda encoding")
    if suffix == ".usdc" and selected != "usdc":
        raise ValueError("USD: .usdc destinations require usdc encoding")
    if suffix == ".usdz" and selected != "usdz":
        raise ValueError("USD: .usdz destinations require usdz encoding")
    if selected == "usdc":
        raise ValueError(
            "USD: USDC writing is unavailable until a current-crate "
            "cross-reader qualifies the output"
        )
    return selected


def write_scene(
    scene,
    path: str | os.PathLike[str],
    *,
    encoding: str | None = None,
    package_assets: bool = True,
    profile: str = "usd-3dcv-1",
) -> None:
    """Write a hierarchy-only SceneGraph transactionally as USDA or USDZ."""

    if profile != "usd-3dcv-1":
        raise ValueError("USD: profile must be 'usd-3dcv-1'")
    if not isinstance(package_assets, bool):
        raise TypeError("USD: package_assets must be bool")
    destination = Path(path)
    selected = _selected_encoding(destination, encoding)
    destination.parent.mkdir(parents=True, exist_ok=True)
    usda = package.temporary_path(destination, ".usda.tmp")
    output = None
    try:
        with usda.open("w", encoding="utf-8", newline="\n") as stream:
            _write_scene_usda(scene, stream)
        if selected == "usdz":
            output = package.temporary_path(destination, ".usdz.tmp")
            package.write_usdz_archive(usda, output)
        else:
            output = usda
        os.replace(output, destination)
    finally:
        with suppress(FileNotFoundError):
            usda.unlink()
        if output is not None:
            with suppress(FileNotFoundError):
                output.unlink()


__all__ = [
    "inspect_scene",
    "read_scene",
    "stage_to_scene_graph",
    "write_scene",
]
