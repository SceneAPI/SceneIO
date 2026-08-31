"""Rich SceneGraph mapping for the bounded USD 3D-CV stage skeleton."""

from __future__ import annotations

import math
import os
import re
from contextlib import ExitStack, suppress
from pathlib import Path, PurePosixPath

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.model import Inspection
from sceneio.io._usd import (
    animation,
    cameras,
    gaussians,
    geometry,
    instances,
    materials,
    package,
    points,
    provider,
    semantics,
    volumes,
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
    **{name: "material" for name in materials.MATERIAL_PRIM_TYPES},
}
_USDA_FEATURES = re.compile(
    rb"""
    \#[^\r\n]*
    | "(?:\\[\s\S]|[^"\\])*"
    | @([^@\r\n]{1,65536})@
    | (?<![A-Za-z0-9_:])
      (subLayers|references|payload|variantSet|variants|inherits|specializes|bindMaterialAs)
      (?![A-Za-z0-9_:])
    """,
    re.VERBOSE,
)
_BINARY_COMPOSITION_TOKENS = {
    "sublayers": (b"subLayers",),
    "references": (b"references",),
    "payloads": (b"payload",),
    "variants": (b"variantSet", b"variants"),
    "inherits": (b"inherits",),
    "specializes": (b"specializes",),
    "material_binding_strength": (b"bindMaterialAs",),
}
_FEATURE_NAMES = {
    b"subLayers": "sublayers",
    b"references": "references",
    b"payload": "payloads",
    b"variantSet": "variants",
    b"variants": "variants",
    b"inherits": "inherits",
    b"specializes": "specializes",
    b"bindMaterialAs": "material_binding_strength",
}
_LIST_OP_PREFIXES = frozenset(
    {b"add", b"append", b"delete", b"prepend", b"reorder"}
)
_FEATURE_DELIMITERS = frozenset(b"\n\r({};")
_HORIZONTAL_WHITESPACE = frozenset({9, 11, 12, 32})


def _is_authored_feature_token(
    data,
    token_start: int,
    *,
    lower_bound: int,
) -> bool:
    """Distinguish arc metadata from same-named typed properties."""

    cursor = token_start
    while (
        cursor > lower_bound
        and data[cursor - 1] in _HORIZONTAL_WHITESPACE
    ):
        cursor -= 1
    if cursor == lower_bound or data[cursor - 1] in _FEATURE_DELIMITERS:
        return True

    word_end = cursor
    while cursor > lower_bound and (
        65 <= data[cursor - 1] <= 90 or 97 <= data[cursor - 1] <= 122
    ):
        cursor -= 1
    if bytes(data[cursor:word_end]) not in _LIST_OP_PREFIXES:
        return False
    while (
        cursor > lower_bound
        and data[cursor - 1] in _HORIZONTAL_WHITESPACE
    ):
        cursor -= 1
    return cursor == lower_bound or data[cursor - 1] in _FEATURE_DELIMITERS


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
            if token is not None and _is_authored_feature_token(
                data,
                match.start(2),
                lower_bound=start,
            ):
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


def _root_layer_has_time_samples(path: str | os.PathLike[str]) -> bool:
    """Return whether the authored root layer contains a timeSamples token."""

    token = b".timeSamples"
    with package.mapped_root_layer(path) as mapped_root:
        if mapped_root is not None:
            mapped, start, end = mapped_root
            return mapped.find(token, start, end) >= 0

    carry = b""
    for chunk in package.iter_root_layer_chunks(path):
        data = carry + chunk
        if token in data:
            return True
        carry = data[-(len(token) - 1) :]
    return False


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


def _authored_purpose(prim) -> str | None:
    """Read only the authored purpose token for payload reachability."""

    if prim.type_name == cameras.CAMERA_PRIM_TYPE:
        value = dict(_TOKEN_ATTRIBUTE.findall(prim.to_string())).get("purpose")
        if value is not None and value not in _PURPOSES:
            raise ValueError(
                f"USD prim {prim.name!r}: unsupported purpose {value!r}"
            )
        return value
    if "purpose" not in set(prim.property_names()):
        return None
    attribute = prim.get_attribute("purpose")
    if attribute is None or attribute.value is None:
        return None
    value = attribute.value.as_scalar()
    if value not in _PURPOSES:
        raise ValueError(
            f"USD prim {prim.name!r}: unsupported purpose {value!r}"
        )
    return str(value)


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
    # TinyUSDZ 0.9.4 treats the new OpenUSD 26.08 Gaussian schema as generic
    # typed data.  Its render-scene converter consequently emits the prim but
    # does not evaluate xformOps authored directly on it.  Re-evaluate only
    # those local stacks through a tiny Xform-only shadow stage.  This keeps
    # transform math inside the qualified provider, does not serialize any
    # Gaussian arrays, and remains O(number of Gaussian prims), not O(points).
    gaussian_prims: list[tuple[str, object]] = []

    def collect_gaussians(prim, parent_path: str) -> None:
        path = f"{parent_path}/{prim.name}"
        if prim.type_name == gaussians.GAUSSIAN_PRIM_TYPE:
            names = set(prim.property_names())
            if "xformOpOrder" in names or any(
                name.startswith("xformOp:") for name in names
            ):
                gaussian_prims.append((path, prim))
        for child in prim.children():
            collect_gaussians(child, path)

    for root in stage.root_prims():
        collect_gaussians(root, "")
    if not gaussian_prims:
        return result

    lines = ["#usda 1.0"]
    shadow_paths: dict[str, str] = {}
    for index, (path, prim) in enumerate(gaussian_prims):
        # Selected-time evaluation is refused by the stage profile below.  Do
        # not turn an authored time-sampled stack into a misleading default.
        if any(
            bool(prim.get_attribute_timesamples(name))
            for name in prim.property_names()
            if name == "xformOpOrder" or name.startswith("xformOp:")
        ):
            continue
        shadow_name = f"SceneIOGaussianTransform{index}"
        lines.extend((f'def Xform "{shadow_name}"', "{"))
        for name in prim.property_names():
            if name != "xformOpOrder" and not name.startswith("xformOp:"):
                continue
            attribute = prim.get_attribute(name)
            if attribute is None or attribute.value is None:
                continue
            variability = "uniform " if name == "xformOpOrder" else ""
            lines.append(
                f"    {variability}{attribute.type_name} {name} = "
                f"{attribute.value.to_string()}"
            )
        lines.append("}")
        shadow_paths[f"/{shadow_name}"] = path
    if not shadow_paths:
        return result

    try:
        shadow_stage = tinyusdz.loads("\n".join(lines) + "\n")
        shadow_render = tinyusdz.tydra.convert_to_render_scene(shadow_stage)
    except Exception as exc:
        raise ValueError(
            f"USD: provider could not evaluate Gaussian static transforms: {exc}"
        ) from exc
    shadow_nodes = {str(node.abs_path): node for node in shadow_render.nodes()}
    if set(shadow_nodes) != set(shadow_paths):
        raise ValueError(
            "USD: provider returned an incomplete Gaussian transform result"
        )
    for shadow_path, path in shadow_paths.items():
        node = shadow_nodes[shadow_path]
        matrix = np.asarray(node.local_matrix, dtype=np.float64)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise ValueError(f"USD prim {path!r}: invalid local transform")
        result[path] = (
            np.array(matrix, copy=True, order="C"),
            bool(node.has_reset_xform),
        )
    return result


def _has_time_samples(prim, *, point_text: str | None = None) -> bool:
    text = prim.to_string() if point_text is None else point_text
    return bool(
        animation.sampled_property_names(
            text,
            context=f"USD prim {prim.name!r}",
        )
    )


def _property_names(prim, *, point_text: str | None = None) -> set[str]:
    if prim.type_name == "Points":
        return points.property_names(prim, text=point_text)
    if prim.type_name == instances.INSTANCE_PRIM_TYPE:
        return instances.property_names(prim, text=point_text)
    if prim.type_name == cameras.CAMERA_PRIM_TYPE:
        return cameras.property_names(prim, text=point_text)
    return set(prim.property_names())


def _payload_shell_properties(
    prim,
    *,
    point_text: str | None = None,
) -> frozenset[str]:
    return _IMAGEABLE_PROPERTIES | semantics.semantic_properties(
        prim,
        text=point_text,
    ) | frozenset(
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
    if prim.type_name not in {
        "Xform",
        "Scope",
        "Mesh",
        "Points",
        cameras.CAMERA_PRIM_TYPE,
        gaussians.GAUSSIAN_PRIM_TYPE,
        volumes.VOLUME_PRIM_TYPE,
        instances.INSTANCE_PRIM_TYPE,
    }:
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
        allowed |= geometry.MESH_PROPERTIES | materials.MESH_MATERIAL_PROPERTIES
    if prim.type_name == "Points":
        allowed |= points.POINT_PROPERTIES
    if prim.type_name == gaussians.GAUSSIAN_PRIM_TYPE:
        allowed |= gaussians.GAUSSIAN_PROPERTIES
    if prim.type_name == cameras.CAMERA_PRIM_TYPE:
        allowed |= cameras.CAMERA_PROPERTIES
    if prim.type_name == volumes.VOLUME_PRIM_TYPE:
        allowed |= volumes.volume_properties(prim)
    if prim.type_name == instances.INSTANCE_PRIM_TYPE:
        allowed |= instances.INSTANCE_PROPERTIES
    allowed |= semantics.semantic_properties(prim, text=point_text)
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


def _validate_inherited_material_bindings(
    roots,
    *,
    resource_paths: frozenset[str],
    selected: frozenset[str] | None = None,
) -> None:
    """Refuse renderable descendants of a directly bound Mesh prim."""

    def visit(
        prim,
        parent_path: str,
        bound_ancestor: str | None,
    ) -> None:
        path = f"{parent_path}/{prim.name}"
        if path in resource_paths or not _include_path(path, selected):
            return
        if (
            bound_ancestor is not None
            and prim.type_name in {"Mesh", "Points"}
            and _select_payload(path, selected)
        ):
            raise ValueError(
                f"USD mesh {bound_ancestor!r}: inherited material bindings "
                "on descendant renderable prims are outside the bounded "
                "profile"
            )
        direct_binding = prim.get_relationship_targets("material:binding")
        descendant_binding = bound_ancestor
        if prim.type_name == "Mesh" and direct_binding is not None:
            descendant_binding = path
        for child in prim.children():
            visit(child, path, descendant_binding)

    for root in roots:
        visit(root, "", None)


def stage_to_scene_graph(
    stage,
    *,
    source_path: str | os.PathLike[str],
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
    selected_time_usda = package.root_layer_prefix(source_path).startswith(
        b"#usda"
    )
    scan_authored_samples = (
        not selected_time_usda
        or _root_layer_has_time_samples(source_path)
    )
    stage_cameras = cameras.collect_stage_products(stage)
    resource_paths = (
        materials.stage_resource_paths(stage)
        | stage_cameras.resource_paths
        | volumes.stage_resource_paths(stage)
    )
    prim_index = volumes.prim_index(stage)

    roots = list(stage.root_prims())
    if len({prim.name for prim in roots}) != len(roots):
        raise ValueError("USD: root prim names must be unique")
    all_paths: set[str] = set()

    def collect(prim, parent_path: str) -> None:
        path = f"{parent_path}/{prim.name}"
        if path in resource_paths:
            return
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
    if selected is not None:
        expanded = set(selected)
        changed = True
        while changed:
            changed = False
            active = frozenset(expanded)
            for path, prim in prim_index.items():
                if (
                    prim.type_name != instances.INSTANCE_PRIM_TYPE
                    or not _select_payload(path, active)
                ):
                    continue
                for target in instances.prototype_paths(prim, path=path):
                    if target not in all_paths:
                        raise ValueError(
                            f"USD PointInstancer {path!r}: prototype "
                            f"{target!r} does not name a scene prim"
                        )
                    if target not in expanded:
                        expanded.add(target)
                        changed = True
        selected = frozenset(expanded)

    selected_mesh_paths: set[str] = set()
    reachable_material_paths: set[str] = set()
    _validate_inherited_material_bindings(
        roots,
        resource_paths=resource_paths,
        selected=selected,
    )

    def collect_payload_bindings(
        prim,
        parent_path: str,
        inherited_purpose: str,
    ) -> None:
        path = f"{parent_path}/{prim.name}"
        if path in resource_paths or not _include_path(path, selected):
            return
        children = list(prim.children())
        effective_purpose = inherited_purpose
        if prim.type_name == "Mesh" or children:
            effective_purpose = _authored_purpose(prim) or inherited_purpose
        if (
            load_payloads
            and prim.type_name == "Mesh"
            and effective_purpose in selected_purposes
            and _select_payload(path, selected)
        ):
            selected_mesh_paths.add(path)
            reachable_material_paths.update(
                materials.bound_material_paths(prim)
            )
        for child in children:
            collect_payload_bindings(child, path, effective_purpose)

    for root in roots:
        collect_payload_bindings(root, "", "default")

    stage_materials = materials.collect_stage_materials(
        stage,
        source_path=source_path,
        build_record=load_payloads,
        include_material_paths=(
            None
            if load_payloads and selected is None
            else frozenset(reachable_material_paths)
        ),
        include_mesh_paths=(
            None
            if load_payloads and selected is None
            else frozenset(selected_mesh_paths)
        ),
        resolve_assets=load_payloads,
    )
    # Validate the bounded material graph before the provider's render-scene
    # conversion.  That conversion consumes materials as an implementation
    # detail and can otherwise replace a precise profile refusal with a vague
    # provider error even though only transforms are needed from it here.
    render_nodes = _render_nodes(stage)

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
    gaussian_clouds = []
    camera_rows: list[dict[str, object]] = []
    volume_assets = []
    openvdb_uris: list[str] = []
    openvdb_sources: list[str] = []
    openvdb_by_uri: dict[str, str] = {}
    parsed_instances: list[tuple[str, instances.ParsedInstanceSet]] = []
    node_semantic_taxonomies: list[str] = []
    node_semantic_labels: list[str] = []
    path_to_node: dict[str, int] = {}
    no_payload = np.iinfo(np.uint64).max
    evaluated_selected_time = False

    def visit(
        prim,
        parent_path: str,
        inherited_purpose: str,
        inherited_semantics: dict[str, frozenset[str]],
    ) -> int | None:
        nonlocal evaluated_selected_time
        path = f"{parent_path}/{prim.name}"
        if path in resource_paths:
            return None
        if not _include_path(path, selected):
            return None
        point_text = (
            prim.to_string()
            if scan_authored_samples
            or prim.type_name
            in {
                "Points",
                cameras.CAMERA_PRIM_TYPE,
                instances.INSTANCE_PRIM_TYPE,
            }
            else None
        )
        _validate_shell(prim, path, point_text=point_text)
        sampled = (
            animation.parse_prim_samples(point_text, path=path)
            if scan_authored_samples
            else animation.ParsedPrimSamples(frozenset())
        )
        selected_values = animation.SelectedPrimValues()
        if sampled.sampled_properties:
            if time is None:
                raise ValueError(
                    f"USD prim {path!r}: authored time samples require "
                    "read_scene(..., time=...); animation preservation is "
                    "unavailable"
                )
            if not selected_time_usda:
                raise ValueError(
                    f"USD prim {path!r}: selected-time evaluation is limited "
                    "to directly authored USDA root layers"
                )
            selected_values = animation.evaluate_prim_samples(
                sampled,
                time=time,
            )
            evaluated_selected_time = True
        visibility, authored_purpose = _authored_imageable_tokens(
            prim,
            point_text=point_text,
        )
        if selected_values.visibility is not None:
            visibility = selected_values.visibility
        effective_purpose = authored_purpose or inherited_purpose
        taxonomy, label, effective_semantics = semantics.inherited_pair(
            prim,
            inherited_semantics,
            text=point_text,
        )
        index = len(node_names)
        path_to_node[path] = index
        node_names.append(prim.name)
        node_visibility.append(visibility)
        node_purpose.append(effective_purpose)
        node_semantic_taxonomies.append(taxonomy)
        node_semantic_labels.append(label)
        node_payload_kinds.append("none")
        node_payload_indices.append(no_payload)
        child_lists.append([])
        if prim.type_name != "Scope":
            if selected_values.transform is not None:
                transform = selected_values.transform
                resets = selected_values.transform_resets_stack
            else:
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
                    )
                    | materials.mesh_shell_properties(prim),
                    coordinate_frame=(
                        "opengl"
                        if metadata["up_axis"] == "y"
                        else "enu"
                    ),
                    scale_to_meters=metadata["meters_per_unit"],
                    binding_resolver=lambda face_count: (
                        materials.binding_ranges_for_mesh(
                            prim,
                            face_count=face_count,
                            material_indices=stage_materials.material_indices,
                        )
                    ),
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
        if (
            prim.type_name == gaussians.GAUSSIAN_PRIM_TYPE
            and load_payloads
            and effective_purpose in selected_purposes
            and _select_payload(path, selected)
        ):
            node_payload_kinds[index] = "gaussian_cloud"
            node_payload_indices[index] = len(gaussian_clouds)
            gaussian_clouds.append(
                gaussians.gaussian_cloud_from_prim(
                    prim,
                    shell_properties=_payload_shell_properties(prim),
                    coordinate_frame=(
                        "opengl" if metadata["up_axis"] == "y" else "enu"
                    ),
                    scale_to_meters=metadata["meters_per_unit"],
                )
            )
        if (
            prim.type_name == cameras.CAMERA_PRIM_TYPE
            and load_payloads
            and effective_purpose in selected_purposes
            and _select_payload(path, selected)
        ):
            node_payload_kinds[index] = "camera"
            node_payload_indices[index] = len(camera_rows)
            camera_rows.append(
                cameras.camera_row_from_prim(
                    prim,
                    path=path,
                    product=stage_cameras.by_camera.get(path),
                    transform=node_transforms[index],
                    shell_properties=_payload_shell_properties(prim),
                    text=point_text,
                )
            )
        if (
            prim.type_name == volumes.VOLUME_PRIM_TYPE
            and load_payloads
            and effective_purpose in selected_purposes
            and _select_payload(path, selected)
        ):
            node_payload_kinds[index] = "volume"
            node_payload_indices[index] = len(volume_assets)
            dependency = volumes.volume_from_prim(
                prim,
                path=path,
                prims=prim_index,
                source_path=source_path,
                source_representation=source_representation,
                shell_properties=_payload_shell_properties(
                    prim,
                    point_text=point_text,
                ),
                resolve_asset=True,
            )
            previous = openvdb_by_uri.get(dependency.uri)
            if previous is not None and previous != dependency.source:
                raise ValueError(
                    f"USD OpenVDB asset {dependency.uri!r}: conflicting "
                    "source locators"
                )
            if previous is None:
                openvdb_by_uri[dependency.uri] = dependency.source
                openvdb_uris.append(dependency.uri)
                openvdb_sources.append(dependency.source)
            volume_assets.append(dependency.volume)
        if (
            prim.type_name == instances.INSTANCE_PRIM_TYPE
            and load_payloads
            and effective_purpose in selected_purposes
            and _select_payload(path, selected)
        ):
            node_payload_kinds[index] = "instances"
            node_payload_indices[index] = len(parsed_instances)
            parsed_instances.append(
                (
                    path,
                    instances.instance_set_from_prim(
                        prim,
                        path=path,
                        shell_properties=_payload_shell_properties(
                            prim,
                            point_text=point_text,
                        ),
                        text=point_text,
                    ),
                )
            )
        point_text = None
        for child in prim.children():
            child_path = f"{path}/{child.name}"
            if child_path in resource_paths:
                continue
            child_index = visit(
                child,
                path,
                effective_purpose,
                effective_semantics,
            )
            if child_index is not None:
                child_lists[index].append(child_index)
        return index

    for root in roots:
        if f"/{root.name}" not in resource_paths:
            visit(root, "", "default", {})

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

    instances.validate_prototype_dependencies(
        {
            path: parsed.prototype_paths
            for path, parsed in parsed_instances
        },
        scene_paths=frozenset(path_to_node),
    )
    instance_sets = [
        parsed.build(path_to_node, path=path)
        for path, parsed in parsed_instances
    ]

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
        node_semantic_taxonomies=node_semantic_taxonomies,
        node_semantic_labels=node_semantic_labels,
        meshes=meshes,
        point_clouds=point_clouds,
        gaussian_clouds=gaussian_clouds,
        cameras=cameras.camera_rig_from_rows(
            camera_rows,
            scale_to_meters=metadata["meters_per_unit"],
        ),
        volumes=volume_assets,
        instances=instance_sets,
        materials=stage_materials.record if load_payloads else None,
        external_asset_uris=(
            stage_materials.external_asset_uris + tuple(openvdb_uris)
            if load_payloads
            else ()
        ),
        external_asset_kinds=(
            ("texture",) * len(stage_materials.external_asset_uris)
            + ("openvdb",) * len(openvdb_uris)
            if load_payloads
            else ()
        ),
        external_asset_sources=(
            stage_materials.external_asset_sources + tuple(openvdb_sources)
            if load_payloads
            else ()
        ),
        source_representation=source_representation,
        default_prim=default_prim,
        selected_time=time if evaluated_selected_time else None,
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
    if "material_binding_strength" in composition:
        raise ValueError(
            "USD: material binding strength metadata is outside the bounded "
            "material profile"
        )
    composition = composition - {"material_binding_strength"}
    if composition:
        raise ValueError(
            "USD: evaluated composition is not available in the stage "
            "skeleton: "
            + ", ".join(sorted(composition))
        )
    stage = provider.load_stage(path)
    return stage_to_scene_graph(
        stage,
        source_path=path,
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
    try:
        stage_cameras = cameras.collect_stage_products(stage)
    except ValueError as exc:
        stage_cameras = None
        unsupported.add(f"cameras: {exc}")
    camera_resource_paths = cameras.stage_resource_paths(stage)
    volume_resource_paths = volumes.stage_resource_paths(stage)
    prim_index = volumes.prim_index(stage)
    try:
        stage_materials = materials.collect_stage_materials(
            stage,
            source_path=path,
            build_record=False,
            resolve_assets=False,
        )
        resource_paths = (
            stage_materials.resource_paths
            | camera_resource_paths
            | volume_resource_paths
        )
    except ValueError as exc:
        stage_materials = None
        resource_paths = (
            materials.stage_resource_paths(stage)
            | camera_resource_paths
            | volume_resource_paths
        )
        unsupported.add(f"materials: {exc}")

    type_counts: dict[str, int] = {}
    variants: list[str] = []
    node_count = 0
    primitive_count = 0
    vertices = 0
    faces = 0
    camera_resolutions: list[str] = []
    instance_count = 0
    prototype_count = 0
    semantic_node_count = 0
    volume_count = 0
    instance_dependencies: dict[str, tuple[str, ...]] = {}
    sampled_properties: list[str] = []
    sampled_times: list[float] = []
    sampled_value_count = 0
    prefix = package.root_layer_prefix(path)
    selected_time_usda = prefix.startswith(b"#usda")
    scan_authored_samples = (
        not selected_time_usda or _root_layer_has_time_samples(path)
    )

    def record_samples(prim_text: str, path_value: str) -> None:
        nonlocal sampled_value_count
        try:
            names = animation.sampled_property_names(
                prim_text,
                context=f"USD prim {path_value!r}",
            )
        except ValueError as exc:
            unsupported.add(f"{path_value}: {exc}")
            return
        if not names:
            return
        sampled_properties.extend(
            f"{path_value}:{name}" for name in sorted(names)
        )
        # Reading without a selected time cannot preserve authored samples in
        # the state-B profile, even when selected-time materialization is safe.
        unsupported.add(f"{path_value}: time_samples")
        try:
            parsed = animation.parse_prim_samples(
                prim_text,
                path=path_value,
            )
        except ValueError as exc:
            unsupported.add(str(exc))
            return
        sampled_value_count += parsed.sample_count
        sampled_times.extend(float(value) for value in parsed.sample_times)
        if not selected_time_usda:
            unsupported.add(
                f"{path_value}: selected-time evaluation requires a "
                "directly authored USDA root layer"
            )

    def visit(
        prim,
        parent_path: str,
        inherited_semantics: dict[str, frozenset[str]],
    ) -> None:
        nonlocal faces, instance_count, node_count, primitive_count
        nonlocal prototype_count, semantic_node_count, vertices, volume_count
        path_value = f"{parent_path}/{prim.name}"
        type_name = str(prim.type_name)
        type_counts[type_name] = type_counts.get(type_name, 0) + 1
        point_text = None
        if scan_authored_samples:
            point_text = prim.to_string()
            record_samples(point_text, path_value)
        if path_value in resource_paths:
            for child in prim.children():
                visit(child, path_value, inherited_semantics)
            return
        if point_text is None and prim.type_name in {
            "Points",
            cameras.CAMERA_PRIM_TYPE,
            instances.INSTANCE_PRIM_TYPE,
        }:
            point_text = prim.to_string()
        node_count += 1
        for set_name in prim.variant_sets():
            selection = prim.variant_selection(set_name)
            variants.append(
                f"{path_value}:{set_name}="
                f"{'' if selection is None else selection}"
            )
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
        effective_semantics = inherited_semantics
        try:
            taxonomy, label, effective_semantics = semantics.inherited_pair(
                prim,
                inherited_semantics,
                text=point_text,
            )
            if taxonomy and label:
                semantic_node_count += 1
            _validate_shell(prim, path_value, point_text=point_text)
        except ValueError as exc:
            unsupported.add(f"{path_value}: {exc}")
        else:
            if prim.type_name == "Mesh":
                try:
                    positions, counts, _, _ = geometry.mesh_arrays_from_prim(
                        prim,
                        copy=False,
                        expand=False,
                        shell_properties=_payload_shell_properties(
                            prim,
                            point_text=point_text,
                        )
                        | materials.mesh_shell_properties(prim),
                    )
                except ValueError as exc:
                    unsupported.add(f"{path_value}: {exc}")
                else:
                    vertices += len(positions)
                    faces += len(counts)
                    primitive_count += 1
                    if stage_materials is not None:
                        try:
                            materials.binding_ranges_for_mesh(
                                prim,
                                face_count=len(counts),
                                material_indices=(
                                    stage_materials.material_indices
                                ),
                            )
                        except ValueError as exc:
                            unsupported.add(f"{path_value}: {exc}")
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
            elif prim.type_name == gaussians.GAUSSIAN_PRIM_TYPE:
                try:
                    gaussian_count, _, _ = gaussians.inspect_gaussian_prim(
                        prim,
                        shell_properties=_payload_shell_properties(prim),
                    )
                except ValueError as exc:
                    unsupported.add(f"{path_value}: {exc}")
                else:
                    vertices += gaussian_count
                    primitive_count += 1
            elif prim.type_name == cameras.CAMERA_PRIM_TYPE:
                try:
                    model, resolution = cameras.inspect_camera_prim(
                        prim,
                        path=path_value,
                        product=(
                            None
                            if stage_cameras is None
                            else stage_cameras.by_camera.get(path_value)
                        ),
                        shell_properties=_payload_shell_properties(prim),
                        text=point_text,
                    )
                except ValueError as exc:
                    unsupported.add(f"{path_value}: {exc}")
                else:
                    camera_resolutions.append(
                        f"{path_value}={resolution[0]}x{resolution[1]}:{model}"
                    )
            elif prim.type_name == volumes.VOLUME_PRIM_TYPE:
                try:
                    volumes.volume_from_prim(
                        prim,
                        path=path_value,
                        prims=prim_index,
                        source_path=path,
                        source_representation=representation,
                        shell_properties=_payload_shell_properties(
                            prim,
                            point_text=point_text,
                        ),
                        resolve_asset=False,
                    )
                except ValueError as exc:
                    unsupported.add(f"{path_value}: {exc}")
                else:
                    volume_count += 1
                    primitive_count += 1
            elif prim.type_name == instances.INSTANCE_PRIM_TYPE:
                try:
                    count, prototypes = instances.inspect_instance_prim(
                        prim,
                        path=path_value,
                        shell_properties=_payload_shell_properties(
                            prim,
                            point_text=point_text,
                        ),
                        text=point_text,
                    )
                except ValueError as exc:
                    unsupported.add(f"{path_value}: {exc}")
                else:
                    targets = instances.prototype_paths(
                        prim,
                        path=path_value,
                        text=point_text,
                    )
                    missing_targets = sorted(
                        target for target in targets if target not in prim_index
                    )
                    if missing_targets:
                        unsupported.add(
                            f"{path_value}: prototypes do not name scene prims: "
                            + ", ".join(missing_targets)
                        )
                    else:
                        instance_dependencies[path_value] = targets
                    instance_count += count
                    prototype_count += prototypes
                    vertices += count
                    primitive_count += 1
        point_text = None
        for child in prim.children():
            visit(child, path_value, effective_semantics)

    roots = list(stage.root_prims())
    try:
        _validate_inherited_material_bindings(
            roots,
            resource_paths=resource_paths,
        )
    except ValueError as exc:
        unsupported.add(str(exc))

    for root in roots:
        visit(root, "", {})

    try:
        instances.validate_prototype_dependencies(
            instance_dependencies,
            scene_paths=frozenset(prim_index) - resource_paths,
        )
    except ValueError as exc:
        unsupported.add(str(exc))

    mesh_projection_available = not unsupported and all(
        name in {"Xform", "Scope", "Mesh"} for name in type_counts
    )
    details: dict[str, object] = {
        **provider.inspection_metadata(),
        "node_count": node_count,
        "primitive_count": primitive_count,
        "face_count": faces,
        "scene_count": 1,
        "representation": representation,
        "up_axis": metadata["up_axis"],
        "meters_per_unit": metadata["meters_per_unit"],
        "time_codes_per_second": metadata["time_codes_per_second"],
        "selected_time_profile": "direct_usda_matrix_visibility_v1",
        "selected_time_representation_supported": selected_time_usda,
        "sampled_properties": tuple(sorted(sampled_properties)),
        "sample_count": sampled_value_count,
        "mesh_projection_available": mesh_projection_available,
        "prim_type_counts": tuple(
            f"{name}={count}" for name, count in sorted(type_counts.items())
        ),
        "dependencies": tuple(sorted(dependency_set)),
        "variants": tuple(sorted(variants)),
        "unsupported_features": tuple(sorted(unsupported)),
        "num_materials": (
            0
            if stage_materials is None
            else len(stage_materials.material_indices)
        ),
        "num_textures": (
            0
            if stage_materials is None
            else len(stage_materials.external_asset_uris)
        ),
        "num_gaussian_clouds": type_counts.get(
            gaussians.GAUSSIAN_PRIM_TYPE, 0
        ),
    }
    if volumes.VOLUME_PRIM_TYPE in type_counts:
        details["num_volumes"] = volume_count
    if instances.INSTANCE_PRIM_TYPE in type_counts:
        details.update(
            num_instance_sets=type_counts[instances.INSTANCE_PRIM_TYPE],
            num_instances=instance_count,
            num_instance_prototypes=prototype_count,
        )
    if semantic_node_count:
        details["num_semantic_nodes"] = semantic_node_count
    if (
        cameras.CAMERA_PRIM_TYPE in type_counts
        or cameras.RENDER_PRODUCT_PRIM_TYPE in type_counts
    ):
        details.update(
            num_cameras=type_counts.get(cameras.CAMERA_PRIM_TYPE, 0),
            num_render_products=type_counts.get(
                cameras.RENDER_PRODUCT_PRIM_TYPE, 0
            ),
            camera_resolutions=tuple(camera_resolutions),
        )
    default_prim = stage.get_metadata("defaultPrim")
    if default_prim is not None:
        details["default_prim"] = str(default_prim)
    if metadata["start_time_code"] is not None:
        details["time_range"] = (
            metadata["start_time_code"],
            metadata["end_time_code"],
        )
    if sampled_times:
        details["sample_time_range"] = (
            min(sampled_times),
            max(sampled_times),
        )
    if prefix.startswith(provider.USDC_MAGIC) and len(prefix) >= 10:
        details["crate_version"] = int(prefix[9])

    return Inspection(
        format=format_id,
        datatype="scene_graph",
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


def _node_paths(
    names: tuple[str, ...], parents: np.ndarray
) -> tuple[str, ...]:
    """Resolve absolute paths while revalidating mutable parent views."""

    paths: list[str | None] = [None] * len(names)
    visiting: set[int] = set()

    def resolve(node: int) -> str:
        cached = paths[node]
        if cached is not None:
            return cached
        if node in visiting:
            raise ValueError("USD: node hierarchy contains a cycle")
        visiting.add(node)
        parent = int(parents[node])
        if parent == -1:
            value = f"/{names[node]}"
        elif parent < 0 or parent >= len(names):
            raise ValueError("USD: node parent index is out of range")
        else:
            value = f"{resolve(parent)}/{names[node]}"
        visiting.remove(node)
        paths[node] = value
        return value

    return tuple(resolve(node) for node in range(len(names)))


def _validate_writable_scene(scene) -> tuple[object, ...]:
    if not isinstance(scene, _core.SceneGraph):
        raise TypeError("USD: write_scene expects a SceneGraph")
    payload_kinds = tuple(scene.node_payload_kinds)
    unsupported_payloads = sorted(
        {
            kind
            for kind in payload_kinds
            if kind
            not in {
                "none",
                "mesh",
                "point_cloud",
                "gaussian_cloud",
                "camera",
                "volume",
                "instances",
            }
        }
    )
    if unsupported_payloads:
        raise ValueError(
            "USD: rich payload writing is not available for: "
            + ", ".join(unsupported_payloads)
        )
    unsupported_assets = sorted(
        {
            kind
            for kind in scene.external_asset_kinds
            if kind not in {"texture", "openvdb"}
        }
    )
    if unsupported_assets:
        raise ValueError(
            "USD: external asset writing is not available for: "
            + ", ".join(unsupported_assets)
        )
    mesh_offsets = np.asarray(scene.mesh_primitive_offsets)
    if not np.array_equal(
        mesh_offsets,
        np.arange(scene.num_meshes + 1, dtype=np.uint64),
    ):
        raise ValueError(
            "USD: logical meshes with multiple primitive payloads are not "
            "representable without changing the node hierarchy"
        )
    if scene.num_scenes:
        roots = np.flatnonzero(np.asarray(scene.node_parents) == -1)
        scene_offsets = np.asarray(scene.scene_root_offsets)
        scene_roots = np.asarray(scene.scene_roots)
        compatible_scene = (
            scene.num_scenes == 1
            and scene.default_scene == 0
            and scene.scene_names == [""]
            and np.array_equal(
                scene_offsets,
                np.array([0, len(scene_roots)], dtype=np.uint64),
            )
            and set(map(int, scene_roots)) == set(map(int, roots))
        )
        if not compatible_scene:
            raise ValueError(
                "USD: named or multiple document scene sets are not representable"
            )
    materials.validate_writable_materials(scene)
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
    node_paths = _node_paths(names, parents)
    if len(node_paths) != len(set(node_paths)):
        raise ValueError("USD: sibling node names must be unique")
    used_meshes: set[int] = set()
    used_points: set[int] = set()
    used_gaussians: set[int] = set()
    for node, kind in enumerate(payload_kinds):
        if kind in {"none", "camera", "volume", "instances"}:
            continue
        index = int(payload_indices[node])
        used = {
            "mesh": used_meshes,
            "point_cloud": used_points,
            "gaussian_cloud": used_gaussians,
        }[kind]
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
                material_count=(
                    scene.materials.num_materials
                    if scene.has_materials
                    else 0
                ),
            )
        elif kind == "point_cloud":
            points.validate_writable_point_cloud(
                scene.point_cloud_at(index),
                up_axis=scene.up_axis,
                meters_per_unit=scene.meters_per_unit,
                context=context,
            )
        else:
            gaussians.validate_writable_gaussian(
                scene.gaussian_cloud_at(index),
                context=context,
                coordinate_frame=(
                    "opengl" if scene.up_axis == "y" else "enu"
                ),
                scale_to_meters=scene.meters_per_unit,
            )
    if used_meshes != set(range(scene.num_meshes)):
        raise ValueError("USD: every mesh payload must be referenced exactly once")
    if used_points != set(range(scene.num_point_clouds)):
        raise ValueError(
            "USD: every point-cloud payload must be referenced exactly once"
        )
    if used_gaussians != set(range(scene.num_gaussian_clouds)):
        raise ValueError(
            "USD: every Gaussian payload must be referenced exactly once"
        )
    camera_rows = cameras.validate_writable_camera_rig(
        scene,
        payload_kinds=payload_kinds,
        payload_indices=payload_indices,
        transforms=transforms,
        node_paths=node_paths,
    )
    volume_rows, volume_fields = volumes.validate_writable_volumes(
        scene,
        payload_kinds=payload_kinds,
        payload_indices=payload_indices,
        node_paths=node_paths,
    )
    instance_rows = instances.validate_writable_instances(
        scene,
        payload_kinds=payload_kinds,
        payload_indices=payload_indices,
        node_paths=node_paths,
    )
    semantic_authored = semantics.validate_writable_semantics(scene, parents)
    return (
        transforms,
        resets,
        parents,
        offsets,
        children,
        payload_kinds,
        payload_indices,
        camera_rows,
        volume_rows,
        volume_fields,
        instance_rows,
        semantic_authored,
    )


def _write_scene_usda(
    scene,
    stream,
    *,
    texture_paths: dict[str, str],
    openvdb_paths: dict[str, str],
    validated: tuple[object, ...] | None = None,
) -> None:
    values = _validate_writable_scene(scene) if validated is None else validated
    (
        transforms,
        resets,
        parents,
        offsets,
        children,
        payload_kinds,
        payload_indices,
        camera_rows,
        volume_rows,
        volume_fields,
        instance_rows,
        semantic_authored,
    ) = values
    camera_rows_by_node = {row.node: row for row in camera_rows}
    volume_rows_by_node = {row.node: row for row in volume_rows}
    instance_rows_by_node = {row.node: row for row in instance_rows}
    volume_fields_by_owner: dict[int, list[volumes.WritableField]] = {}
    for field in volume_fields:
        volume_fields_by_owner.setdefault(field.owner_node, []).append(field)
    material_scope = (
        materials.choose_material_scope(scene) if scene.has_materials else None
    )
    material_paths = (
        materials.material_paths(material_scope, scene.materials)
        if material_scope is not None
        else ()
    )
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
            "gaussian_cloud": gaussians.GAUSSIAN_PRIM_TYPE,
            "camera": cameras.CAMERA_PRIM_TYPE,
            "volume": volumes.VOLUME_PRIM_TYPE,
            "instances": instances.INSTANCE_PRIM_TYPE,
        }[kind]
        mesh = (
            scene.mesh_at(int(payload_indices[node]))
            if kind == "mesh"
            else None
        )
        has_material_binding = (
            mesh is not None
            and np.any(np.asarray(mesh.primitive_materials) >= 0)
        )
        stream.write(f'{indent}def {type_name} "{scene.node_names[node]}"\n')
        api_schemas = []
        if has_material_binding:
            api_schemas.append("MaterialBindingAPI")
        semantic_schema = semantics.api_schema(
            scene,
            node,
            semantic_authored,
        )
        if semantic_schema is not None:
            api_schemas.append(semantic_schema)
        if api_schemas:
            encoded_schemas = ", ".join(
                '"' + value + '"' for value in api_schemas
            )
            stream.write(
                f"{indent}(\n"
                f"{indent}    prepend apiSchemas = "
                f"[{encoded_schemas}]\n"
                f"{indent})\n"
            )
        stream.write(f"{indent}{{\n")
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
        if semantic_authored[node]:
            semantics.write_label_attribute(scene, node, stream, inner=inner)
        if kind == "mesh":
            geometry.write_mesh_attributes(
                stream,
                mesh,
                inner=inner,
            )
            if has_material_binding:
                materials.write_mesh_bindings(
                    stream,
                    mesh,
                    inner=inner,
                    paths=material_paths,
                )
        elif kind == "point_cloud":
            points.write_point_attributes(
                stream,
                scene.point_cloud_at(int(payload_indices[node])),
                inner=inner,
            )
        elif kind == "gaussian_cloud":
            gaussians.write_gaussian_attributes(
                stream,
                scene.gaussian_cloud_at(int(payload_indices[node])),
                inner=inner,
            )
        elif kind == "camera":
            cameras.write_camera_attributes(
                stream,
                camera_rows_by_node[node],
                inner=inner,
            )
        elif kind == "volume":
            volumes.write_volume_attribute(
                stream,
                volume_rows_by_node[node],
                inner=inner,
            )
        elif kind == "instances":
            row = instance_rows_by_node[node]
            instances.write_instance_attributes(
                stream,
                scene.instance_set_at(row.payload),
                row,
                inner=inner,
            )
        for field in volume_fields_by_owner.get(node, ()):
            volumes.write_field_resource(
                stream,
                field,
                inner=inner,
                asset_paths=openvdb_paths,
            )
        begin, end = int(offsets[node]), int(offsets[node + 1])
        for child in children[begin:end]:
            stream.write("\n")
            write_node(int(child), inner)
        stream.write(f"{indent}}}\n")

    for node in np.flatnonzero(parents == -1):
        write_node(int(node), "")
    if scene.has_materials:
        materials.write_material_library(
            stream,
            scene.materials,
            scope_name=material_scope,
            texture_paths=texture_paths,
        )
    if camera_rows:
        cameras.write_render_products(
            stream,
            camera_rows,
            names=cameras.choose_product_names(scene, len(camera_rows)),
        )


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
    """Write the bounded static SceneGraph transactionally as USDA or USDZ."""

    if profile != "usd-3dcv-1":
        raise ValueError("USD: profile must be 'usd-3dcv-1'")
    if not isinstance(package_assets, bool):
        raise TypeError("USD: package_assets must be bool")
    destination = Path(path)
    selected = _selected_encoding(destination, encoding)
    validated = _validate_writable_scene(scene)
    texture_assets = _texture_assets(scene)
    openvdb_assets = _openvdb_assets(scene)
    if selected == "usdz" and openvdb_assets:
        raise ValueError(
            "USDZ: OpenVDB dependencies are outside USDZ 1.3; write USDA/USD"
        )
    if selected == "usdz" and texture_assets and not package_assets:
        raise ValueError(
            "USDZ: texture assets must be packaged in the self-contained profile"
        )
    if selected == "usda" and texture_assets and not package_assets:
        package.validate_unpacked_asset_sources(destination, texture_assets)
    if selected == "usda" and openvdb_assets and not package_assets:
        package.validate_unpacked_asset_sources(
            destination,
            openvdb_assets,
            kind="OpenVDB asset",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    usda = package.temporary_path(destination, ".usda.tmp")
    output = None
    try:
        if selected == "usdz":
            texture_paths = {
                uri: (
                    f"textures/texture_{index:04d}"
                    f"{PurePosixPath(uri).suffix.lower()}"
                )
                for index, (uri, _) in enumerate(texture_assets)
            }
            with usda.open("w", encoding="utf-8", newline="\n") as stream:
                _write_scene_usda(
                    scene,
                    stream,
                    texture_paths=texture_paths,
                    openvdb_paths={},
                    validated=validated,
                )
            output = package.temporary_path(destination, ".usdz.tmp")
            package.write_usdz_archive(
                usda,
                output,
                assets=(
                    (texture_paths[uri], source)
                    for uri, source in texture_assets
                ),
            )
            os.replace(output, destination)
        elif (texture_assets or openvdb_assets) and package_assets:
            with ExitStack() as stack:
                texture_paths = (
                    stack.enter_context(
                        package.prepared_sidecar_assets(
                            destination,
                            texture_assets,
                        )
                    )
                    if texture_assets
                    else {}
                )
                openvdb_paths = (
                    stack.enter_context(
                        package.prepared_sidecar_assets(
                            destination,
                            openvdb_assets,
                            kind="openvdb",
                        )
                    )
                    if openvdb_assets
                    else {}
                )
                with usda.open(
                    "w",
                    encoding="utf-8",
                    newline="\n",
                ) as stream:
                    _write_scene_usda(
                        scene,
                        stream,
                        texture_paths=texture_paths,
                        openvdb_paths=openvdb_paths,
                        validated=validated,
                    )
                output = usda
                os.replace(output, destination)
        else:
            texture_paths = {
                uri: uri for uri, _ in texture_assets
            }
            openvdb_paths = {uri: uri for uri, _ in openvdb_assets}
            with usda.open("w", encoding="utf-8", newline="\n") as stream:
                _write_scene_usda(
                    scene,
                    stream,
                    texture_paths=texture_paths,
                    openvdb_paths=openvdb_paths,
                    validated=validated,
                )
            output = usda
            os.replace(output, destination)
    finally:
        with suppress(FileNotFoundError):
            usda.unlink()
        if output is not None:
            with suppress(FileNotFoundError):
                output.unlink()


def _texture_assets(scene) -> tuple[tuple[str, str], ...]:
    if not scene.has_materials:
        return ()
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for uri, kind, source in zip(
        scene.external_asset_uris,
        scene.external_asset_kinds,
        scene.external_asset_sources,
        strict=True,
    ):
        if kind != "texture":
            continue
        if uri in seen:
            raise ValueError(f"USD: duplicate external texture URI {uri!r}")
        seen.add(uri)
        values.append((uri, source))
    expected = set(scene.materials.texture_paths)
    if seen != expected:
        raise ValueError(
            "USD: external texture assets must exactly match material paths"
        )
    first_use = tuple(dict.fromkeys(scene.materials.texture_paths))
    if tuple(uri for uri, _ in values) != first_use:
        raise ValueError(
            "USD: external texture assets must follow first material use"
        )
    return tuple(values)


def _openvdb_assets(scene) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for uri, kind, source in zip(
        scene.external_asset_uris,
        scene.external_asset_kinds,
        scene.external_asset_sources,
        strict=True,
    ):
        if kind != "openvdb":
            continue
        if uri in seen:
            raise ValueError(f"USD: duplicate external OpenVDB URI {uri!r}")
        seen.add(uri)
        values.append((uri, source))
    expected = {
        scene.volume_at(index).uri for index in range(scene.num_volumes)
    }
    if seen != expected:
        raise ValueError(
            "USD: external OpenVDB assets must exactly match volume URIs"
        )
    first_use = tuple(
        dict.fromkeys(
            scene.volume_at(index).uri for index in range(scene.num_volumes)
        )
    )
    if tuple(uri for uri, _ in values) != first_use:
        raise ValueError(
            "USD: external OpenVDB assets must follow first volume use"
        )
    return tuple(values)


__all__ = [
    "inspect_scene",
    "read_scene",
    "stage_to_scene_graph",
    "write_scene",
]
