"""Large-file benchmark components.

The package is intentionally import-light: optional providers are imported only
inside a selected case or a worker process.
"""

from .model import (
    MIB,
    SCHEMA_VERSION,
    CaseArtifact,
    CaseDefinition,
    Measurement,
    OperationResult,
    ProviderInfo,
)

__all__ = [
    "MIB",
    "SCHEMA_VERSION",
    "CaseArtifact",
    "CaseDefinition",
    "Measurement",
    "OperationResult",
    "ProviderInfo",
]
