"""Machine-readable contracts for every SceneIO-owned public class identity.

The namespace is stdlib-only, provider-independent, and lazy. Use
:func:`public_type_contract` for generic discovery; representation-specific
normalization details remain available through
``sceneio.representation_contract``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sceneio.contracts.model import (
        ContractEvidence,
        ContractMember,
        ContractRelation,
        PublicTypeContract,
    )
    from sceneio.contracts.payloads import CodecPayloadKind

_EXPORT_MODULES = {
    "PUBLIC_TYPE_CONTRACT_SCHEMA_VERSION": "sceneio.contracts.model",
    "ContractEvidence": "sceneio.contracts.model",
    "ContractMember": "sceneio.contracts.model",
    "ContractRelation": "sceneio.contracts.model",
    "PublicTypeContract": "sceneio.contracts.model",
    "BUILTIN_CODEC_PAYLOAD_KINDS": "sceneio.contracts.payloads",
    "CodecPayloadKind": "sceneio.contracts.payloads",
    "builtin_payload_kind": "sceneio.contracts.payloads",
    "is_builtin_payload_kind": "sceneio.contracts.payloads",
    "PUBLIC_TYPE_ALIASES": "sceneio.contracts.registry",
    "PUBLIC_TYPE_CONTRACTS": "sceneio.contracts.registry",
    "public_type_contract": "sceneio.contracts.registry",
    "catalog_dict": "sceneio.contracts.serialization",
}


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module 'sceneio.contracts' has no attribute {name!r}")
    return getattr(importlib.import_module(module_name), name)


__all__ = [
    "BUILTIN_CODEC_PAYLOAD_KINDS",
    "PUBLIC_TYPE_ALIASES",
    "PUBLIC_TYPE_CONTRACTS",
    "PUBLIC_TYPE_CONTRACT_SCHEMA_VERSION",
    "CodecPayloadKind",
    "ContractEvidence",
    "ContractMember",
    "ContractRelation",
    "PublicTypeContract",
    "builtin_payload_kind",
    "catalog_dict",
    "is_builtin_payload_kind",
    "public_type_contract",
]
