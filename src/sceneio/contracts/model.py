"""Immutable value models for SceneIO's public type-contract catalog.

This module is deliberately stdlib-only.  Contract discovery must stay usable
without importing NumPy, the compiled core, or any optional format provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Literal, get_args

PUBLIC_TYPE_CONTRACT_SCHEMA_VERSION = 1

ContractKind = Literal[
    "representation",
    "wire_record",
    "descriptor",
    "procedure_value",
    "protocol",
    "vocabulary",
    "error",
]
ContractStability = Literal["stable", "provisional"]
ProcedureRole = Literal["traits", "options", "result"]
ContractMemberKind = Literal["field", "method", "enum_value"]
ContractPresence = Literal["required", "optional", "derived", "conditional"]
ContractMutability = Literal[
    "immutable",
    "mutable",
    "input_only",
    "output_only",
    "not_applicable",
]
ContractRelationKind = Literal[
    "adapts_to",
    "contains",
    "input_to",
    "output_of",
    "parent_error",
    "logical_data_type",
    "payload_kind",
    "format",
    "operation",
    "schema",
    "profile",
    "specializes",
]

PUBLIC_CONTRACT_KINDS: frozenset[str] = frozenset(get_args(ContractKind))
PUBLIC_CONTRACT_STABILITIES: frozenset[str] = frozenset(get_args(ContractStability))
PROCEDURE_ROLES: frozenset[str] = frozenset(get_args(ProcedureRole))
CONTRACT_MEMBER_KINDS: frozenset[str] = frozenset(get_args(ContractMemberKind))
CONTRACT_PRESENCE_VALUES: frozenset[str] = frozenset(get_args(ContractPresence))
CONTRACT_MUTABILITY_VALUES: frozenset[str] = frozenset(get_args(ContractMutability))
CONTRACT_RELATION_KINDS: frozenset[str] = frozenset(get_args(ContractRelationKind))

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_PUBLIC_SCENEIO_PATH = re.compile(r"^sceneio(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
_IMPLEMENTATION_SCENEIO_PATH = re.compile(r"^sceneio(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _non_empty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _unique_text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str | bytes):
        raise TypeError(f"{field_name} must be an iterable of strings")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"{field_name} must be an iterable of strings") from exc
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"{field_name} entries must be non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} entries must be unique")
    return values


def _repository_path(value: object, field_name: str) -> str:
    text = _non_empty_text(value, field_name)
    if "\\" in text:
        raise ValueError(f"{field_name} must use forward slashes")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field_name} must be repository-relative")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class ContractMember:
    """One contractual field, method, or vocabulary value."""

    name: str
    kind: ContractMemberKind
    type_expression: str
    presence: ContractPresence
    mutability: ContractMutability
    semantics: str
    default: str | None = None
    units: tuple[str, ...] = ()
    ordered: bool | None = None

    def __post_init__(self) -> None:
        _non_empty_text(self.name, "ContractMember.name")
        if not self.name.isidentifier():
            raise ValueError("ContractMember.name must be a Python identifier")
        if self.kind not in CONTRACT_MEMBER_KINDS:
            raise ValueError(f"unknown contract member kind {self.kind!r}")
        _non_empty_text(self.type_expression, "ContractMember.type_expression")
        if self.presence not in CONTRACT_PRESENCE_VALUES:
            raise ValueError(f"unknown contract presence {self.presence!r}")
        if self.mutability not in CONTRACT_MUTABILITY_VALUES:
            raise ValueError(f"unknown contract mutability {self.mutability!r}")
        _non_empty_text(self.semantics, "ContractMember.semantics")
        if self.default is not None:
            _non_empty_text(self.default, "ContractMember.default")
        object.__setattr__(
            self,
            "units",
            _unique_text_tuple(self.units, "ContractMember.units"),
        )
        if self.ordered is not None and not isinstance(self.ordered, bool):
            raise TypeError("ContractMember.ordered must be bool or None")
        if self.kind != "field" and self.mutability != "not_applicable":
            raise ValueError("method and enum-value members must use not_applicable mutability")


@dataclass(frozen=True, slots=True)
class ContractEvidence:
    """Executable repository evidence for one or more contract claims."""

    path: str
    claims: tuple[str, ...]
    node_id: str | None = None
    artifact: str | None = None

    def __post_init__(self) -> None:
        normalized_path = _repository_path(self.path, "ContractEvidence.path")
        object.__setattr__(self, "path", normalized_path)
        claims = _unique_text_tuple(self.claims, "ContractEvidence.claims")
        if not claims:
            raise ValueError("ContractEvidence.claims must not be empty")
        if any(_IDENTIFIER.fullmatch(claim) is None for claim in claims):
            raise ValueError("ContractEvidence.claims must use lower_snake_case")
        object.__setattr__(self, "claims", claims)
        if self.node_id is not None:
            node_id = _non_empty_text(self.node_id, "ContractEvidence.node_id")
            if not node_id.startswith(f"{normalized_path}::"):
                raise ValueError("ContractEvidence.node_id must start with its repository path")
        if self.artifact is not None:
            object.__setattr__(
                self,
                "artifact",
                _repository_path(self.artifact, "ContractEvidence.artifact"),
            )


@dataclass(frozen=True, slots=True)
class ContractRelation:
    """Typed edge from one public type to another contract subject."""

    kind: ContractRelationKind
    target: str

    def __post_init__(self) -> None:
        if self.kind not in CONTRACT_RELATION_KINDS:
            raise ValueError(f"unknown contract relation kind {self.kind!r}")
        _non_empty_text(self.target, "ContractRelation.target")


@dataclass(frozen=True, slots=True)
class PublicTypeContract:
    """Common envelope for one canonical public class identity."""

    canonical_path: str
    aliases: tuple[str, ...]
    implementation_paths: tuple[str, ...]
    kind: ContractKind
    stability: ContractStability
    summary: str
    members: tuple[ContractMember, ...]
    rules: tuple[str, ...]
    refusal: str
    evidence: tuple[ContractEvidence, ...]
    procedure_role: ProcedureRole | None = None
    relations: tuple[ContractRelation, ...] = ()
    specialized_contract_key: str | None = None
    specialized_contract: object | None = field(
        default=None,
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        canonical = _non_empty_text(self.canonical_path, "PublicTypeContract.canonical_path")
        if _PUBLIC_SCENEIO_PATH.fullmatch(canonical) is None:
            raise ValueError("PublicTypeContract.canonical_path must be a public sceneio path")
        aliases = _unique_text_tuple(self.aliases, "PublicTypeContract.aliases")
        if canonical in aliases:
            raise ValueError("canonical path must not be repeated as an alias")
        if any(_PUBLIC_SCENEIO_PATH.fullmatch(alias) is None for alias in aliases):
            raise ValueError("public aliases must be public sceneio paths")
        object.__setattr__(self, "aliases", aliases)
        implementation_paths = _unique_text_tuple(
            self.implementation_paths,
            "PublicTypeContract.implementation_paths",
        )
        if any(
            _IMPLEMENTATION_SCENEIO_PATH.fullmatch(path) is None for path in implementation_paths
        ):
            raise ValueError("implementation paths must be sceneio dotted paths")
        object.__setattr__(self, "implementation_paths", implementation_paths)
        if self.kind not in PUBLIC_CONTRACT_KINDS:
            raise ValueError(f"unknown public contract kind {self.kind!r}")
        if self.stability not in PUBLIC_CONTRACT_STABILITIES:
            raise ValueError(f"unknown contract stability {self.stability!r}")
        _non_empty_text(self.summary, "PublicTypeContract.summary")
        members = tuple(self.members)
        if any(not isinstance(member, ContractMember) for member in members):
            raise TypeError("PublicTypeContract.members must contain ContractMember")
        member_keys = tuple((member.kind, member.name) for member in members)
        if len(member_keys) != len(set(member_keys)):
            raise ValueError("PublicTypeContract member identities must be unique")
        object.__setattr__(self, "members", members)
        rules = _unique_text_tuple(self.rules, "PublicTypeContract.rules")
        if not rules:
            raise ValueError("PublicTypeContract.rules must not be empty")
        object.__setattr__(self, "rules", rules)
        _non_empty_text(self.refusal, "PublicTypeContract.refusal")
        evidence = tuple(self.evidence)
        if not evidence or any(not isinstance(item, ContractEvidence) for item in evidence):
            raise ValueError("PublicTypeContract.evidence must contain ContractEvidence")
        if len(evidence) != len(set(evidence)):
            raise ValueError("PublicTypeContract evidence must be unique")
        object.__setattr__(self, "evidence", evidence)
        relations = tuple(self.relations)
        if any(not isinstance(item, ContractRelation) for item in relations):
            raise TypeError("PublicTypeContract.relations must contain ContractRelation")
        if len(relations) != len(set(relations)):
            raise ValueError("PublicTypeContract relations must be unique")
        object.__setattr__(self, "relations", relations)

        if self.kind == "procedure_value":
            if self.procedure_role not in PROCEDURE_ROLES:
                raise ValueError(
                    "procedure_value entries require a traits, options, or result procedure_role"
                )
        elif self.procedure_role is not None:
            raise ValueError("only procedure_value entries may declare procedure_role")

        field_kinds = {member.kind for member in members}
        if self.kind == "representation":
            if self.specialized_contract_key is None or self.specialized_contract is None:
                raise ValueError("representation entries require their specialized contract")
        elif self.specialized_contract_key is not None or self.specialized_contract is not None:
            raise ValueError("only representation entries may embed a specialized contract")
        if self.kind in {"wire_record", "descriptor", "procedure_value"} and (
            "field" not in field_kinds
        ):
            raise ValueError(f"{self.kind} entries require field members")
        if self.kind == "protocol" and "method" not in field_kinds:
            raise ValueError("protocol entries require method members")
        if self.kind == "error" and not any(
            relation.kind == "parent_error" for relation in relations
        ):
            raise ValueError("error entries require a parent_error relation")


EMPTY_PUBLIC_TYPE_CONTRACTS = MappingProxyType({})


__all__ = [
    "CONTRACT_MEMBER_KINDS",
    "CONTRACT_MUTABILITY_VALUES",
    "CONTRACT_PRESENCE_VALUES",
    "CONTRACT_RELATION_KINDS",
    "PROCEDURE_ROLES",
    "PUBLIC_CONTRACT_KINDS",
    "PUBLIC_CONTRACT_STABILITIES",
    "PUBLIC_TYPE_CONTRACT_SCHEMA_VERSION",
    "ContractEvidence",
    "ContractKind",
    "ContractMember",
    "ContractMemberKind",
    "ContractMutability",
    "ContractPresence",
    "ContractRelation",
    "ContractRelationKind",
    "ContractStability",
    "ProcedureRole",
    "PublicTypeContract",
]
