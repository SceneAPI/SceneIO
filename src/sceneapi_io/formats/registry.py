"""The format-id registry type and the core seed table.

``FormatSpec`` is deliberately minimal — it registers a format's
*identity*, not its serialization details (JSON schemas, media-type
alternates, and kind bindings stay with the emitting side until the
core re-homes them). ``kind`` names the logical payload the format
serializes, using the core's DataType-id vocabulary (``feature_set``,
``pair_set``, ``match_graph``, ``sparse_model``, ``projection``).

``media_type`` is the single canonical media type for single-stream
wire formats; the core's artifact formats are multi-file manifest
formats with several media types, so they register ``media_type=None``.

The ``CORE_FORMATS`` seed mirrors, byte-for-byte, the format ids in the
core's ``sceneapi/server/core/artifacts.py`` vocabulary. Do NOT invent
new ids here; wire identity is Phase-C territory.
"""

from __future__ import annotations

from dataclasses import dataclass

from sceneapi_io.errors import ContractViolation


@dataclass(frozen=True)
class FormatSpec:
    """The registered identity of one disk/wire format."""

    id: str
    kind: str
    media_type: str | None
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ContractViolation(f"FormatSpec.id: expected a non-empty str, got {self.id!r}")
        if not isinstance(self.kind, str) or not self.kind:
            raise ContractViolation(f"FormatSpec.kind: expected a non-empty str, got {self.kind!r}")
        if self.media_type is not None and (
            not isinstance(self.media_type, str) or not self.media_type
        ):
            raise ContractViolation(
                f"FormatSpec.media_type: expected a non-empty str or None, got {self.media_type!r}"
            )
        if not isinstance(self.description, str) or not self.description:
            raise ContractViolation(
                f"FormatSpec.description: expected a non-empty str, got {self.description!r}"
            )


_CORE_FORMAT_SEED: tuple[FormatSpec, ...] = (
    FormatSpec(
        id="sfmapi.features.local.v1",
        kind="feature_set",
        media_type=None,
        description=(
            "Versioned interchange manifest for per-image keypoints, descriptors, "
            "descriptor dtype/layout, and detector metadata."
        ),
    ),
    FormatSpec(
        id="sfmapi.features.global.v1",
        kind="feature_set",
        media_type=None,
        description="Versioned interchange manifest for per-image retrieval descriptors.",
    ),
    FormatSpec(
        id="sfmapi.pairs.image_names.v1",
        kind="pair_set",
        media_type=None,
        description="Portable image-pair list keyed by dataset image names.",
    ),
    FormatSpec(
        id="sfmapi.matches.indexed.v1",
        kind="match_graph",
        media_type=None,
        description="Portable match graph expressed as feature-index pairs.",
    ),
    FormatSpec(
        id="sfmapi.matches.coordinates.v1",
        kind="match_graph",
        media_type=None,
        description="Portable detector-free match graph expressed as image coordinates.",
    ),
    FormatSpec(
        id="sfmapi.matches.dense.v1",
        kind="match_graph",
        media_type=None,
        description="Portable tiled dense or semi-dense correspondence field.",
    ),
    FormatSpec(
        id="sfmapi.matches.verified.v1",
        kind="match_graph",
        media_type=None,
        description="Portable verified correspondences with F/E/H matrices and inliers.",
    ),
    FormatSpec(
        id="sfmapi.reconstruction.sparse.v1",
        kind="sparse_model",
        media_type=None,
        description="Portable cameras, image poses, rigs, tracks, and sparse points manifest.",
    ),
    FormatSpec(
        id="sfmapi.reconstruction.snapshot.v1",
        kind="sparse_model",
        media_type=None,
        description="Immutable snapshot directory containing portable sparse reconstruction files.",
    ),
    FormatSpec(
        id="sfmapi.reconstruction.submodel.v1",
        kind="sparse_model",
        media_type=None,
        description="One disconnected component inside a sparse reconstruction snapshot.",
    ),
    FormatSpec(
        id="sfmapi.projection.images.v1",
        kind="projection",
        media_type=None,
        description="Projected image files plus a manifest with source/output geometry metadata.",
    ),
)


def _build_registry(seed: tuple[FormatSpec, ...]) -> dict[str, FormatSpec]:
    registry: dict[str, FormatSpec] = {}
    for spec in seed:
        if spec.id in registry:
            raise ContractViolation(f"duplicate format id in registry: {spec.id!r}")
        registry[spec.id] = spec
    return registry


CORE_FORMATS: dict[str, FormatSpec] = _build_registry(_CORE_FORMAT_SEED)

CORE_FORMAT_IDS: frozenset[str] = frozenset(CORE_FORMATS)


def get_format(format_id: str) -> FormatSpec | None:
    return CORE_FORMATS.get(format_id)


def is_core_format(format_id: str) -> bool:
    return format_id in CORE_FORMATS
