"""Typed records shared by the large-file benchmark layers.

The large benchmark deliberately keeps its result model independent from the
ordinary 73-format harness.  Records are plain dataclasses so a worker can
serialize a result without importing a provider-specific object into the
parent process.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "large-io-v1"
MIB = 1024 * 1024


@dataclass(frozen=True)
class CaseDefinition:
    """Description of one large benchmark workload."""

    id: str
    format: str
    source_id: str | None
    description: str
    standard_logical_bytes: int
    operations: tuple[str, ...]
    providers: tuple[str, ...]


@dataclass(frozen=True)
class CaseArtifact:
    """A prepared common input and its serializable fixture metadata."""

    case_id: str
    tier: str
    path: Path
    logical_bytes: int
    encoded_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)
    source_id: str | None = None
    acquisition_mode: str = "synthetic_fallback"
    derivation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible metadata for a fresh worker process."""

        value = asdict(self)
        value["path"] = str(self.path)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CaseArtifact:
        """Reconstruct an artifact sent over the worker JSON protocol."""

        return cls(
            case_id=str(value["case_id"]),
            tier=str(value["tier"]),
            path=Path(value["path"]),
            logical_bytes=int(value["logical_bytes"]),
            encoded_bytes=int(value["encoded_bytes"]),
            metadata=dict(value.get("metadata", {})),
            source_id=value.get("source_id"),
            acquisition_mode=str(value.get("acquisition_mode", "synthetic_fallback")),
            derivation=dict(value.get("derivation", {})),
        )


@dataclass(frozen=True)
class Measurement:
    """Raw and aggregate measurements produced inside one fresh child."""

    raw_seconds: tuple[float, ...]
    median_seconds: float
    traced_peak_bytes: int | None
    rss_delta_bytes: int | None
    cache_mode: str = "warm"

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_seconds": list(self.raw_seconds),
            "median_seconds": self.median_seconds,
            "traced_peak_bytes": self.traced_peak_bytes,
            "rss_delta_bytes": self.rss_delta_bytes,
            "cache_mode": self.cache_mode,
        }


@dataclass(frozen=True)
class OperationResult:
    """A reportable provider/operation row."""

    case_id: str
    provider: str
    operation: str
    measurement: Measurement
    logical_bytes: int
    encoded_bytes: int
    status: str = "ok"
    diagnostic: dict[str, Any] = field(default_factory=dict)
    output_paths: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        seconds = self.measurement.median_seconds
        throughput_operation = self.operation in {"read", "full_scan", "write"}
        return {
            "case_id": self.case_id,
            "provider": self.provider,
            "operation": self.operation,
            "status": self.status,
            "measurement": self.measurement.to_dict(),
            "logical_bytes": self.logical_bytes,
            "encoded_bytes": self.encoded_bytes,
            "logical_mib_s": (
                self.logical_bytes / MIB / seconds if seconds > 0 else None
            )
            if throughput_operation
            else None,
            "encoded_mib_s": (
                self.encoded_bytes / MIB / seconds if seconds > 0 else None
            )
            if throughput_operation
            else None,
            "diagnostic": self.diagnostic,
            "output_paths": list(self.output_paths),
            "error": self.error,
        }


@dataclass(frozen=True)
class ProviderInfo:
    """Provider/version information captured in each result."""

    name: str
    version: str | None
    module: str | None = None
    revision: str | None = None
    build: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def artifact_summary(artifact: CaseArtifact) -> dict[str, Any]:
    """Return provenance and shape metadata for a result document."""

    return {
        "case_id": artifact.case_id,
        "tier": artifact.tier,
        "path": str(artifact.path),
        "logical_bytes": artifact.logical_bytes,
        "encoded_bytes": artifact.encoded_bytes,
        "source_id": artifact.source_id,
        "acquisition_mode": artifact.acquisition_mode,
        "derivation": artifact.derivation,
        "fixture": artifact.metadata,
    }


__all__ = [
    "MIB",
    "SCHEMA_VERSION",
    "CaseArtifact",
    "CaseDefinition",
    "Measurement",
    "OperationResult",
    "ProviderInfo",
    "artifact_summary",
]
