"""Deterministic plain-data serialization for the public contract catalog."""

from __future__ import annotations

from sceneio.contracts.model import PUBLIC_TYPE_CONTRACT_SCHEMA_VERSION
from sceneio.contracts.payloads import BUILTIN_CODEC_PAYLOAD_KINDS
from sceneio.contracts.registry import PUBLIC_TYPE_CONTRACTS


def _member_dict(member) -> dict[str, object]:
    return {
        "name": member.name,
        "kind": member.kind,
        "type_expression": member.type_expression,
        "presence": member.presence,
        "mutability": member.mutability,
        "semantics": member.semantics,
        "default": member.default,
        "units": list(member.units),
        "ordered": member.ordered,
    }


def _evidence_dict(evidence) -> dict[str, object]:
    return {
        "path": evidence.path,
        "node_id": evidence.node_id,
        "claims": list(evidence.claims),
        "artifact": evidence.artifact,
    }


def _contract_dict(contract) -> dict[str, object]:
    return {
        "canonical_path": contract.canonical_path,
        "implementation_paths": list(contract.implementation_paths),
        "kind": contract.kind,
        "stability": contract.stability,
        "summary": contract.summary,
        "members": [_member_dict(member) for member in contract.members],
        "rules": list(contract.rules),
        "refusal": contract.refusal,
        "evidence": [_evidence_dict(item) for item in contract.evidence],
        "procedure_role": contract.procedure_role,
        "relations": [
            {"kind": relation.kind, "target": relation.target} for relation in contract.relations
        ],
        "specialized_contract_key": contract.specialized_contract_key,
    }


def _payload_dict(payload) -> dict[str, object]:
    return {
        "id": payload.id,
        "title": payload.title,
        "description": payload.description,
        "public_types": list(payload.public_types),
        "format_ids": list(payload.format_ids),
        "evidence": list(payload.evidence),
        "logical_data_type_id": payload.logical_data_type_id,
        "dynamic_output": payload.dynamic_output,
        "dynamic_output_rule": payload.dynamic_output_rule,
    }


def catalog_dict() -> dict[str, object]:
    """Return a detached, deterministic serialization of the full catalog."""

    return {
        "contract_schema_version": PUBLIC_TYPE_CONTRACT_SCHEMA_VERSION,
        "contracts": [_contract_dict(contract) for contract in PUBLIC_TYPE_CONTRACTS.values()],
        "builtin_codec_payload_kinds": [
            _payload_dict(BUILTIN_CODEC_PAYLOAD_KINDS[payload_id])
            for payload_id in sorted(BUILTIN_CODEC_PAYLOAD_KINDS)
        ],
    }


__all__ = ["catalog_dict"]
