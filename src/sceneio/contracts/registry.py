"""Immutable index and lookup rules for SceneIO public type contracts.

Catalog construction is intentionally independent of runtime class imports.
The manifest and every validation dependency in this module are stdlib-only;
class and instance lookup uses their already-loaded public identity strings.
"""

from __future__ import annotations

import importlib
from collections import defaultdict
from collections.abc import Collection
from types import MappingProxyType

from sceneio.contracts.manifest import manifest_entries
from sceneio.contracts.model import ContractRelation, PublicTypeContract
from sceneio.contracts.payloads import (
    _BUILTIN_PAYLOAD_IDS_BY_FORMAT,
    BUILTIN_CODEC_PAYLOAD_KINDS,
)

_LOGICAL_DATA_TYPE_IDS = frozenset(
    {
        "camera",
        "camera_collection",
        "feature_set",
        "image_sequence",
        "match_graph",
        "pair_set",
        "projection",
        "sparse_model",
    }
)
_SCHEMA_TARGETS = frozenset(
    {
        "application/x-sfm-points-v1",
        "artifact-formats/1",
        "builtin-codec-payloads/1",
        "colmap_db/3",
        "datatypes/1",
        "public-type-contract/1",
        "representation-contract/1",
    }
)
_OPERATION_TARGETS = frozenset({"mapping", "matching"})
_PUBLIC_RELATION_KINDS = frozenset(
    {"adapts_to", "contains", "input_to", "output_of", "specializes"}
)
_FIXED_RELATION_TARGETS = MappingProxyType(
    {
        "logical_data_type": _LOGICAL_DATA_TYPE_IDS,
        "operation": _OPERATION_TARGETS,
        "schema": _SCHEMA_TARGETS,
    }
)
_EXTERNAL_PUBLIC_TARGETS = frozenset(
    {
        # ImageRef is a documented public union alias, not a class identity,
        # so it is intentionally outside the class-contract census.
        "sceneio.data.ImageRef",
    }
)
_BUILTIN_PARENT_ERRORS = frozenset({"builtins.Exception", "builtins.ValueError"})


def _prefixed_target(target: str, prefix: str, known: Collection[str]) -> bool:
    marker = f"{prefix}:"
    return target == f"{marker}*" or (
        target.startswith(marker) and target.removeprefix(marker) in known
    )


def _build_path_index(
    entries: tuple[PublicTypeContract, ...],
) -> tuple[
    MappingProxyType[str, PublicTypeContract],
    MappingProxyType[str, str],
    MappingProxyType[str, PublicTypeContract],
    MappingProxyType[str, tuple[str, ...]],
]:
    canonical: dict[str, PublicTypeContract] = {}
    aliases: dict[str, str] = {}
    lookup: dict[str, PublicTypeContract] = {}
    short_names: defaultdict[str, list[str]] = defaultdict(list)

    for entry in entries:
        path = entry.canonical_path
        if path in canonical:
            raise ValueError(f"duplicate canonical public type path: {path!r}")
        canonical[path] = entry

    for entry in entries:
        for path in (entry.canonical_path, *entry.aliases, *entry.implementation_paths):
            existing = lookup.get(path)
            if existing is not None and existing is not entry:
                raise ValueError(
                    f"public type path {path!r} resolves to both "
                    f"{existing.canonical_path!r} and {entry.canonical_path!r}"
                )
            lookup[path] = entry
        for alias in entry.aliases:
            if alias in canonical:
                raise ValueError(f"public alias collides with canonical path: {alias!r}")
            existing_path = aliases.get(alias)
            if existing_path is not None and existing_path != entry.canonical_path:
                raise ValueError(f"duplicate public type alias: {alias!r}")
            aliases[alias] = entry.canonical_path
        short_names[entry.canonical_path.rsplit(".", 1)[-1]].append(entry.canonical_path)

    ordered_canonical = dict(sorted(canonical.items()))
    ordered_aliases = dict(sorted(aliases.items()))
    ordered_lookup = dict(sorted(lookup.items()))
    ordered_short_names = {
        name: tuple(sorted(paths)) for name, paths in sorted(short_names.items())
    }
    return (
        MappingProxyType(ordered_canonical),
        MappingProxyType(ordered_aliases),
        MappingProxyType(ordered_lookup),
        MappingProxyType(ordered_short_names),
    )


def _validate_relation(
    relation: ContractRelation,
    path_lookup: MappingProxyType[str, PublicTypeContract],
    profiles: frozenset[str],
) -> None:
    kind = relation.kind
    target = relation.target
    public_targets = path_lookup.keys() | _EXTERNAL_PUBLIC_TARGETS

    if kind in _PUBLIC_RELATION_KINDS:
        valid = target in public_targets
    elif kind == "parent_error":
        valid = target in public_targets or target in _BUILTIN_PARENT_ERRORS
    elif kind == "payload_kind":
        valid = _prefixed_target(target, "builtin-payload", BUILTIN_CODEC_PAYLOAD_KINDS)
    elif kind == "format":
        valid = _prefixed_target(target, "builtin-format", _BUILTIN_PAYLOAD_IDS_BY_FORMAT)
    elif kind in _FIXED_RELATION_TARGETS:
        valid = target in _FIXED_RELATION_TARGETS[kind]
    elif kind == "profile":
        valid = target in profiles
    else:  # The model rejects unknown kinds; this keeps the check total.
        valid = False

    if not valid:
        raise ValueError(f"unknown {kind} relation target: {target!r}")


def _validate_catalog(
    entries: tuple[PublicTypeContract, ...],
    path_lookup: MappingProxyType[str, PublicTypeContract],
) -> None:
    profiles = frozenset(
        f"representation-profile:{entry.specialized_contract.profile.id}"
        for entry in entries
        if entry.kind == "representation"
    )
    for entry in entries:
        if entry.kind == "representation":
            expected = entry.specialized_contract_key
            if expected != entry.canonical_path:
                raise ValueError(
                    "representation specialized contract key differs from its "
                    f"canonical path: {entry.canonical_path!r}"
                )
        for relation in entry.relations:
            _validate_relation(relation, path_lookup, profiles)

    public_paths = path_lookup.keys()
    for payload_id, payload in BUILTIN_CODEC_PAYLOAD_KINDS.items():
        if payload.id != payload_id:
            raise ValueError(f"payload mapping key differs from id: {payload_id!r}")
        unknown_types = tuple(path for path in payload.public_types if path not in public_paths)
        if unknown_types:
            raise ValueError(
                f"payload kind {payload_id!r} has unknown public types: {unknown_types!r}"
            )
        if (
            payload.logical_data_type_id is not None
            and payload.logical_data_type_id not in _LOGICAL_DATA_TYPE_IDS
        ):
            raise ValueError(
                f"payload kind {payload_id!r} has unknown logical DataType "
                f"{payload.logical_data_type_id!r}"
            )


def _build_catalog() -> tuple[
    MappingProxyType[str, PublicTypeContract],
    MappingProxyType[str, str],
    MappingProxyType[str, PublicTypeContract],
    MappingProxyType[str, tuple[str, ...]],
]:
    entries = manifest_entries()
    indexes = _build_path_index(entries)
    _validate_catalog(entries, indexes[2])
    return indexes


(
    PUBLIC_TYPE_CONTRACTS,
    PUBLIC_TYPE_ALIASES,
    _PATH_LOOKUP,
    _SHORT_NAMES,
) = _build_catalog()


def _object_candidate_paths(subject: type[object] | object) -> tuple[str, ...]:
    cls = subject if isinstance(subject, type) else type(subject)
    module = getattr(cls, "__module__", "")
    qualname = getattr(cls, "__qualname__", "")
    name = getattr(cls, "__name__", "")
    if not module or not qualname or not name:
        return ()

    candidates = [f"{module}.{qualname}", f"{module}.{name}"]
    public_prefixes = (
        "sceneio.data",
        "sceneio.colmap_mvs",
        "sceneio.colmap",
        "sceneio.mapping",
        "sceneio.matching",
        "sceneio.formats",
        "sceneio.contracts",
    )
    if module == "sceneio._core" or module.startswith("sceneio._core."):
        candidates.append(f"sceneio.{name}")
    for prefix in public_prefixes:
        if module == prefix or module.startswith(f"{prefix}."):
            candidates.append(f"{prefix}.{name}")
    if module == "sceneio.io" or module.startswith("sceneio.io."):
        candidates.extend((f"sceneio.io.{name}", f"sceneio.{name}"))

    # Preserve order while removing duplicates.
    return tuple(dict.fromkeys(candidates))


def public_type_contract(subject: str | type[object] | object) -> PublicTypeContract:
    """Return the immutable contract for a public path, class, or instance.

    Qualified strings accept canonical paths, supported aliases, and recorded
    implementation identities. Bare names resolve only when unambiguous.
    """

    if isinstance(subject, str):
        if not subject:
            raise KeyError("unknown public type contract: ''")
        if "." in subject:
            try:
                return _PATH_LOOKUP[subject]
            except KeyError:
                raise KeyError(f"unknown public type contract path {subject!r}") from None
        candidates = _SHORT_NAMES.get(subject, ())
        if len(candidates) == 1:
            return PUBLIC_TYPE_CONTRACTS[candidates[0]]
        if len(candidates) > 1:
            choices = ", ".join(candidates)
            raise ValueError(
                f"ambiguous public type contract name {subject!r}; choose one of: {choices}"
            )
        raise KeyError(f"unknown public type contract name {subject!r}")

    for path in _object_candidate_paths(subject):
        contract = _PATH_LOOKUP.get(path)
        if contract is not None:
            return contract
    raise TypeError(
        f"object of type {type(subject).__module__}.{type(subject).__qualname__} "
        "has no SceneIO public type contract"
    )


def _runtime_path_value(path: str) -> object:
    module_name, _, name = path.rpartition(".")
    return getattr(importlib.import_module(module_name), name)


def _validate_runtime_identities(
    entries: tuple[PublicTypeContract, ...] | None = None,
) -> None:
    """Validate importable canonical, alias, and implementation identities.

    This audit is deliberately not part of stdlib-only catalog construction;
    callers opt into importing the public runtime namespaces.
    """

    values = tuple(PUBLIC_TYPE_CONTRACTS.values()) if entries is None else entries
    for entry in values:
        canonical = _runtime_path_value(entry.canonical_path)
        for path in (*entry.aliases, *entry.implementation_paths):
            if _runtime_path_value(path) is not canonical:
                raise ValueError(
                    f"public type path {path!r} does not resolve to canonical "
                    f"identity {entry.canonical_path!r}"
                )


__all__ = [
    "PUBLIC_TYPE_ALIASES",
    "PUBLIC_TYPE_CONTRACTS",
    "public_type_contract",
]
