"""Atomic assembly and publication of repository-owned codec definitions.

The public registry remains mutable so applications can register extensions.
Built-ins take a stricter path: collect and validate the complete canonical
set off-registry, then publish that set in one update.
"""

from __future__ import annotations

from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS, FAMILY_MEMBERS
from sceneio.io._registry.model import Codec


def _validate_payload_contracts(definitions: tuple[Codec, ...]) -> None:
    """Validate repository-owned codecs against the closed payload catalog."""

    from sceneio.contracts.payloads import (
        BUILTIN_CODEC_PAYLOAD_KINDS,
        _build_format_index,
    )

    payload_ids_by_format = _build_format_index(tuple(BUILTIN_CODEC_PAYLOAD_KINDS.values()))
    declared_format_ids = tuple(payload_ids_by_format)
    if set(declared_format_ids) != set(CANONICAL_BUILTIN_IDS):
        missing = tuple(
            format_id for format_id in CANONICAL_BUILTIN_IDS if format_id not in declared_format_ids
        )
        extra = tuple(
            format_id for format_id in declared_format_ids if format_id not in CANONICAL_BUILTIN_IDS
        )
        raise ValueError(
            "built-in payload format coverage differs from the codec manifest: "
            f"missing={missing!r}, extra={extra!r}"
        )

    formats_by_payload = {payload_id: [] for payload_id in BUILTIN_CODEC_PAYLOAD_KINDS}
    for codec in definitions:
        try:
            payload = BUILTIN_CODEC_PAYLOAD_KINDS[codec.payload_kind]
        except KeyError:
            raise ValueError(
                f"built-in codec {codec.id!r} has undeclared payload kind {codec.payload_kind!r}"
            ) from None
        if payload_ids_by_format.get(codec.id) != codec.payload_kind:
            raise ValueError(
                f"built-in codec {codec.id!r} is not related to payload kind {codec.payload_kind!r}"
            )
        if codec.record is None and not payload.dynamic_output:
            raise ValueError(
                f"built-in codec {codec.id!r} has no record type or dynamic output rule"
            )
        if codec.record is not None:
            record_name = codec.record.__name__
            if not any(path.rsplit(".", 1)[-1] == record_name for path in payload.public_types):
                raise ValueError(
                    f"built-in codec {codec.id!r} record type "
                    f"{record_name!r} is not declared by "
                    f"payload kind {codec.payload_kind!r}"
                )
        formats_by_payload[codec.payload_kind].append(codec.id)

    unused_payloads = tuple(
        payload_id for payload_id, format_ids in formats_by_payload.items() if not format_ids
    )
    if unused_payloads:
        raise ValueError(f"built-in payload kinds are unused: {unused_payloads!r}")

    for payload_id, payload in BUILTIN_CODEC_PAYLOAD_KINDS.items():
        actual_format_ids = tuple(formats_by_payload[payload_id])
        if actual_format_ids != payload.format_ids:
            raise ValueError(
                f"built-in payload {payload_id!r} format order differs: "
                f"{actual_format_ids!r} != {payload.format_ids!r}"
            )


class BuiltinAssembly:
    """Collect one complete, ordered set of built-in codec definitions."""

    __slots__ = ("_canonical_ids", "_definitions", "_finalized")

    def __init__(
        self,
        canonical_ids: tuple[str, ...] = CANONICAL_BUILTIN_IDS,
    ) -> None:
        # The public registry always uses the manifest default. A reduced set
        # exists only for isolated state-machine contracts.
        ids = tuple(canonical_ids)
        if any(not isinstance(format_id, str) or not format_id for format_id in ids):
            raise ValueError("canonical codec ids must be non-empty strings")
        if len(ids) != len(set(ids)):
            raise ValueError("canonical codec ids must be unique")
        self._canonical_ids = ids
        self._definitions: dict[str, Codec] = {}
        self._finalized: tuple[Codec, ...] | None = None

    def _ensure_open(self) -> None:
        if self._finalized is not None:
            raise RuntimeError("built-in codec assembly is finalized")

    def add_codec(self, codec: Codec) -> Codec:
        """Stage one codec without mutating the live registry."""

        self._ensure_open()
        if type(codec) is not Codec:
            raise TypeError("built-in codec entries must be Codec instances")
        if codec.id not in self._canonical_ids:
            raise ValueError(f"unknown built-in codec id: {codec.id!r}")
        if codec.id in self._definitions:
            raise ValueError(f"built-in codec id already staged: {codec.id!r}")

        definitions = dict(self._definitions)
        definitions[codec.id] = codec
        self._definitions = definitions
        return codec

    def add_family(
        self,
        family_name: str,
        codecs: tuple[Codec, ...],
    ) -> tuple[Codec, ...]:
        """Validate and stage one canonical family as an atomic unit."""

        self._ensure_open()
        if not isinstance(family_name, str) or family_name not in FAMILY_MEMBERS:
            raise ValueError(f"unknown built-in codec family: {family_name!r}")

        definitions = tuple(codecs)
        if any(type(codec) is not Codec for codec in definitions):
            raise TypeError("built-in family entries must be Codec instances")
        actual_ids = tuple(codec.id for codec in definitions)
        expected_ids = FAMILY_MEMBERS[family_name]
        if len(actual_ids) != len(set(actual_ids)):
            raise ValueError(f"built-in family ids must be unique: {actual_ids!r}")
        if actual_ids != expected_ids:
            raise ValueError(f"built-in family ids {actual_ids!r} do not match {expected_ids!r}")
        unknown_ids = tuple(
            format_id for format_id in actual_ids if format_id not in self._canonical_ids
        )
        if unknown_ids:
            raise ValueError(f"unknown built-in codec ids: {unknown_ids!r}")
        collisions = tuple(format_id for format_id in actual_ids if format_id in self._definitions)
        if collisions:
            raise ValueError(f"built-in codec ids already staged: {collisions!r}")

        staged = dict(self._definitions)
        staged.update((codec.id, codec) for codec in definitions)
        self._definitions = staged
        return definitions

    def finalize(self) -> tuple[Codec, ...]:
        """Return the complete canonical tuple and seal successful assembly."""

        if self._finalized is not None:
            return self._finalized

        actual_ids = tuple(self._definitions)
        missing_ids = tuple(
            format_id for format_id in self._canonical_ids if format_id not in self._definitions
        )
        extra_ids = tuple(
            format_id for format_id in actual_ids if format_id not in self._canonical_ids
        )
        if missing_ids or extra_ids:
            raise ValueError(
                "built-in codec assembly is incomplete: "
                f"missing={missing_ids!r}, extra={extra_ids!r}"
            )

        definitions = tuple(self._definitions[format_id] for format_id in self._canonical_ids)
        if self._canonical_ids == CANONICAL_BUILTIN_IDS:
            _validate_payload_contracts(definitions)
        self._finalized = definitions
        return definitions


def publish_builtin_definitions(
    registry: dict[str, Codec],
    definitions: tuple[Codec, ...],
) -> None:
    """Validate and publish the complete built-in set in one update."""

    if type(registry) is not dict:
        raise TypeError("built-in registry must be an exact dict")
    codecs = tuple(definitions)
    if any(type(codec) is not Codec for codec in codecs):
        raise TypeError("built-in codec entries must be Codec instances")
    actual_ids = tuple(codec.id for codec in codecs)
    if actual_ids != CANONICAL_BUILTIN_IDS:
        raise ValueError(
            f"built-in codec ids {actual_ids!r} do not match {CANONICAL_BUILTIN_IDS!r}"
        )
    if registry:
        raise ValueError("built-in registry must be empty before publication")

    items = tuple(zip(actual_ids, codecs, strict=True))
    dict.update(registry, items)


__all__ = ["BuiltinAssembly", "publish_builtin_definitions"]
