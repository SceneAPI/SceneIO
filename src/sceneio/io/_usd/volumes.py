"""Bounded UsdVolVolume/OpenVDBAsset dependency mapping."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sceneio import _core
from sceneio.io._usd import package

VOLUME_PRIM_TYPE = "Volume"
OPENVDB_PRIM_TYPE = "OpenVDBAsset"
_FIELD_PREFIX = "field:"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_FIELD_PROPERTIES = frozenset(
    {
        "filePath",
        "fieldName",
        "fieldDataType",
        "vectorDataRoleHint",
        "fieldClass",
    }
)


@dataclass(frozen=True)
class VolumeDependency:
    volume: object
    uri: str
    source: str
    field_path: str


@dataclass(frozen=True)
class WritableVolume:
    node: int
    payload: int
    field_name: str
    field_path: str


@dataclass(frozen=True)
class WritableField:
    owner_node: int
    name: str
    path: str
    uri: str
    grid_name: str


def prim_index(stage) -> dict[str, object]:
    result: dict[str, object] = {}

    def visit(prim, parent_path: str) -> None:
        path = f"{parent_path}/{prim.name}"
        if path in result:
            raise ValueError(f"USD: duplicate prim path {path!r}")
        result[path] = prim
        for child in prim.children():
            visit(child, path)

    for root in stage.root_prims():
        visit(root, "")
    return result


def stage_resource_paths(stage) -> frozenset[str]:
    """Identify OpenVDB field resources excluded from SceneGraph nodes."""

    return frozenset(
        path
        for path, prim in prim_index(stage).items()
        if prim.type_name == OPENVDB_PRIM_TYPE
    )


def volume_properties(prim) -> frozenset[str]:
    """Return direct field relationship property names."""

    return frozenset(
        name for name in prim.property_names() if name.startswith(_FIELD_PREFIX)
    )


def _scalar(prim, name: str, expected_type: str, *, required: bool = True):
    attribute = prim.get_attribute(name)
    if attribute is None or attribute.value is None:
        if required:
            raise ValueError(
                f"USD OpenVDBAsset {prim.name!r}: missing {name!r}"
            )
        return None
    if str(attribute.type_name) != expected_type:
        raise ValueError(
            f"USD OpenVDBAsset {prim.name!r}: {name!r} must have type "
            f"{expected_type}, not {attribute.type_name}"
        )
    if prim.get_attribute_timesamples(name):
        raise ValueError(
            f"USD OpenVDBAsset {prim.name!r}: time-sampled {name!r} is "
            "outside the static profile"
        )
    return attribute.value.as_scalar()


def _field_resource(prim, path: str) -> tuple[str, str]:
    properties = set(prim.property_names())
    unsupported = sorted(properties - _FIELD_PROPERTIES)
    if unsupported:
        raise ValueError(
            f"USD OpenVDBAsset {path!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    if prim.children():
        raise ValueError(f"USD OpenVDBAsset {path!r}: children are unsupported")
    encoded_uri = str(_scalar(prim, "filePath", "asset"))
    match = re.fullmatch(r"@([^@\r\n]+)@", encoded_uri)
    if match is None:
        raise ValueError(
            f"USD OpenVDBAsset {path!r}: filePath must be one direct asset"
        )
    uri = package.normalize_asset_uri(
        match.group(1), context="USD OpenVDB asset"
    )
    if PurePosixPath(uri).suffix.lower() != ".vdb":
        raise ValueError(
            f"USD OpenVDBAsset {path!r}: filePath must use the .vdb suffix"
        )
    grid_name = str(_scalar(prim, "fieldName", "token"))
    if not grid_name:
        raise ValueError(
            f"USD OpenVDBAsset {path!r}: fieldName must be non-empty"
        )
    if str(_scalar(prim, "fieldDataType", "token")) != "float":
        raise ValueError(
            f"USD OpenVDBAsset {path!r}: fieldDataType must be 'float'"
        )
    role = _scalar(
        prim, "vectorDataRoleHint", "token", required=False
    )
    if role not in {None, "None"}:
        raise ValueError(
            f"USD OpenVDBAsset {path!r}: vectorDataRoleHint must be 'None'"
        )
    field_class = _scalar(prim, "fieldClass", "token", required=False)
    if field_class not in {None, "unknown"}:
        raise ValueError(
            f"USD OpenVDBAsset {path!r}: fieldClass must be 'unknown'"
        )
    return uri, grid_name


def volume_from_prim(
    prim,
    *,
    path: str,
    prims: dict[str, object],
    source_path: str | Path,
    source_representation: str,
    shell_properties: frozenset[str],
    resolve_asset: bool,
) -> VolumeDependency:
    """Map one direct field relationship without opening the VDB bytes."""

    properties = set(prim.property_names())
    fields = sorted(name for name in properties if name.startswith(_FIELD_PREFIX))
    unsupported = sorted(properties - set(fields) - shell_properties)
    if unsupported:
        raise ValueError(
            f"USD Volume {path!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    if len(fields) != 1:
        raise ValueError(
            f"USD Volume {path!r}: exactly one field relationship is required"
        )
    relationship = fields[0]
    field_name = relationship[len(_FIELD_PREFIX) :]
    if not _IDENTIFIER.fullmatch(field_name):
        raise ValueError(
            f"USD Volume {path!r}: field name {field_name!r} is not portable"
        )
    targets = prim.get_relationship_targets(relationship)
    if targets is None or len(targets) != 1:
        raise ValueError(
            f"USD Volume {path!r}: {relationship!r} must have one target"
        )
    field_path = str(targets[0])
    target = prims.get(field_path)
    if target is None or target.type_name != OPENVDB_PRIM_TYPE:
        raise ValueError(
            f"USD Volume {path!r}: target {field_path!r} must name an "
            "OpenVDBAsset"
        )
    if source_representation == "usdz":
        raise ValueError("USDZ: OpenVDB dependencies are outside USDZ 1.3")
    uri, grid_name = _field_resource(target, field_path)
    source = (
        package.asset_source_for(
            source_path,
            uri,
            kind="OpenVDB asset",
        )
        if resolve_asset
        else uri
    )
    return VolumeDependency(
        volume=_core.volume_asset(uri, grid_name, field_name),
        uri=uri,
        source=source,
        field_path=field_path,
    )


def validate_writable_volumes(
    scene,
    *,
    payload_kinds: tuple[str, ...],
    payload_indices,
    node_paths: tuple[str, ...],
) -> tuple[tuple[WritableVolume, ...], tuple[WritableField, ...]]:
    """Validate volume payloads and assign deterministic shared field prims."""

    used: set[int] = set()
    rows: list[WritableVolume] = []
    fields: list[WritableField] = []
    by_key: dict[tuple[str, str], WritableField] = {}
    child_names: dict[int, set[str]] = {node: set() for node in range(scene.num_nodes)}
    for child, parent in enumerate(scene.node_parents):
        if int(parent) >= 0:
            child_names[int(parent)].add(scene.node_names[child])
    for node, kind in enumerate(payload_kinds):
        if kind != "volume":
            continue
        payload = int(payload_indices[node])
        if payload in used:
            raise ValueError(
                f"USD: volume payload {payload} is referenced by multiple nodes"
            )
        used.add(payload)
        volume = scene.volume_at(payload)
        uri = package.normalize_asset_uri(
            volume.uri, context="USD OpenVDB asset"
        )
        if PurePosixPath(uri).suffix.lower() != ".vdb":
            raise ValueError("USD: OpenVDB volume URIs must use the .vdb suffix")
        if not volume.grid_name:
            raise ValueError("USD: OpenVDB grid names must be non-empty")
        field_name = volume.field_name or volume.grid_name
        if not _IDENTIFIER.fullmatch(field_name):
            raise ValueError(
                f"USD: volume field name {field_name!r} is not a portable "
                "identifier"
            )
        key = (uri, volume.grid_name)
        field = by_key.get(key)
        if field is None:
            serial = len(fields)
            name = f"_SceneIOOpenVDB_{serial:04d}"
            while name in child_names[node]:
                serial += 1
                name = f"_SceneIOOpenVDB_{serial:04d}"
            field = WritableField(
                owner_node=node,
                name=name,
                path=f"{node_paths[node]}/{name}",
                uri=uri,
                grid_name=volume.grid_name,
            )
            by_key[key] = field
            fields.append(field)
            child_names[node].add(name)
        rows.append(
            WritableVolume(
                node=node,
                payload=payload,
                field_name=field_name,
                field_path=field.path,
            )
        )
    if used != set(range(scene.num_volumes)):
        raise ValueError("USD: every volume payload must be referenced exactly once")
    return tuple(rows), tuple(fields)


def write_volume_attribute(stream, row: WritableVolume, *, inner: str) -> None:
    """Write the volume-to-field relationship."""

    stream.write(
        f"{inner}rel {_FIELD_PREFIX}{row.field_name} = <{row.field_path}>\n"
    )


def write_field_resource(
    stream,
    field: WritableField,
    *,
    inner: str,
    asset_paths: dict[str, str],
) -> None:
    """Write one canonical scalar-float OpenVDB field resource."""

    stream.write(f'\n{inner}def {OPENVDB_PRIM_TYPE} "{field.name}"\n')
    stream.write(f"{inner}{{\n")
    body = inner + "    "
    stream.write(f'{body}token fieldClass = "unknown"\n')
    stream.write(f'{body}token fieldDataType = "float"\n')
    stream.write(
        f"{body}token fieldName = "
        f"{json.dumps(field.grid_name, ensure_ascii=False)}\n"
    )
    stream.write(f"{body}asset filePath = @{asset_paths[field.uri]}@\n")
    stream.write(f'{body}token vectorDataRoleHint = "None"\n')
    stream.write(f"{inner}}}\n")


__all__ = [
    "OPENVDB_PRIM_TYPE",
    "VOLUME_PRIM_TYPE",
    "VolumeDependency",
    "WritableField",
    "WritableVolume",
    "prim_index",
    "stage_resource_paths",
    "validate_writable_volumes",
    "volume_from_prim",
    "volume_properties",
    "write_field_resource",
    "write_volume_attribute",
]
