"""Production-owned manifest for SceneIO public class contracts.

The manifest is string-keyed and stdlib-only.  It adapts the existing
representation catalog without importing public record namespaces or the
compiled I/O layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sceneio._camera_models import CAMERA_MODEL_NAMES
from sceneio.contracts.model import (
    ContractEvidence,
    ContractMember,
    ContractRelation,
    PublicTypeContract,
)
from sceneio.representations import REPRESENTATION_CONTRACTS

BASELINE_PUBLIC_TYPE_NAMESPACES = (
    "sceneio",
    "sceneio.colmap",
    "sceneio.colmap_mvs",
    "sceneio.formats",
    "sceneio.mapping",
    "sceneio.matching",
    "sceneio.testing",
)
PUBLIC_TYPE_NAMESPACES = (*BASELINE_PUBLIC_TYPE_NAMESPACES, "sceneio.contracts")

_REQUIRED = object()
_SURFACE_TEST = (
    "tests/test_public_type_contracts.py::test_non_representation_contracts_match_runtime_surface"
)
_PROTOCOL_TEST = (
    "tests/test_public_type_contracts.py::test_protocol_contracts_match_runtime_signatures"
)
_ERROR_TEST = "tests/test_public_type_contracts.py::test_error_contracts_match_hierarchy"
_SELF_TEST = "tests/test_public_type_contracts.py::test_contract_metadata_types_self_classify"


def _evidence(
    path: str,
    *claims: str,
    node_id: str | None = None,
    artifact: str | None = None,
) -> ContractEvidence:
    return ContractEvidence(
        path=path,
        claims=tuple(claims),
        node_id=node_id,
        artifact=artifact,
    )


def _node(node_id: str, *claims: str) -> ContractEvidence:
    path = node_id.partition("::")[0]
    return _evidence(path, *claims, node_id=node_id)


def _relation(kind: str, target: str) -> ContractRelation:
    return ContractRelation(kind=kind, target=target)  # type: ignore[arg-type]


def _field(
    subject: str,
    name: str,
    type_expression: str,
    default: object = _REQUIRED,
    *,
    units: tuple[str, ...] = (),
    ordered: bool | None = None,
    presence: str | None = None,
    semantics: str | None = None,
) -> ContractMember:
    resolved_presence = (
        presence if presence is not None else "required" if default is _REQUIRED else "optional"
    )
    return ContractMember(
        name=name,
        kind="field",
        type_expression=type_expression,
        presence=resolved_presence,  # type: ignore[arg-type]
        mutability="immutable",
        semantics=semantics or f"Stable {subject}.{name} value.",
        default=None if default is _REQUIRED else str(default),
        units=units,
        ordered=ordered,
    )


def _method(name: str, signature: str, semantics: str) -> ContractMember:
    return ContractMember(
        name=name,
        kind="method",
        type_expression=signature,
        presence="required",
        mutability="not_applicable",
        semantics=semantics,
    )


def _enum_value(name: str, value: str) -> ContractMember:
    return ContractMember(
        name=name,
        kind="enum_value",
        type_expression="str",
        presence="required",
        mutability="not_applicable",
        semantics="Stable COLMAP camera-model identity.",
        default=repr(value),
    )


def _fields(
    subject: str,
    required: Iterable[tuple[str, str]],
    optional: Iterable[tuple[str, str, str]] = (),
    *,
    units: Mapping[str, tuple[str, ...]] | None = None,
    ordered: Iterable[str] = (),
    semantics: Mapping[str, str] | None = None,
) -> tuple[ContractMember, ...]:
    unit_map = {} if units is None else dict(units)
    ordered_fields = set(ordered)
    semantic_map = {} if semantics is None else dict(semantics)
    members = [
        _field(
            subject,
            name,
            type_expression,
            units=unit_map.get(name, ()),
            ordered=True if name in ordered_fields else None,
            semantics=semantic_map.get(name),
        )
        for name, type_expression in required
    ]
    members.extend(
        _field(
            subject,
            name,
            type_expression,
            default,
            units=unit_map.get(name, ()),
            ordered=True if name in ordered_fields else None,
            semantics=semantic_map.get(name),
        )
        for name, type_expression, default in optional
    )
    return tuple(members)


def _entry(
    canonical_path: str,
    *,
    kind: str,
    summary: str,
    members: tuple[ContractMember, ...],
    rules: tuple[str, ...],
    refusal: str,
    evidence: tuple[ContractEvidence, ...],
    implementation_paths: tuple[str, ...] = (),
    procedure_role: str | None = None,
    relations: tuple[ContractRelation, ...] = (),
) -> PublicTypeContract:
    return PublicTypeContract(
        canonical_path=canonical_path,
        implementation_paths=implementation_paths,
        kind=kind,  # type: ignore[arg-type]
        stability="stable",
        summary=summary,
        members=members,
        rules=rules,
        refusal=refusal,
        evidence=evidence,
        procedure_role=procedure_role,  # type: ignore[arg-type]
        relations=relations,
    )


def _representation_entries() -> tuple[PublicTypeContract, ...]:
    entries: list[PublicTypeContract] = []
    for canonical_path, specialized in REPRESENTATION_CONTRACTS.items():
        evidence = tuple(
            _evidence(path, "normalization", "refusal") for path in specialized.evidence
        )
        entries.append(
            PublicTypeContract(
                canonical_path=canonical_path,
                implementation_paths=(),
                kind="representation",
                stability="provisional",
                summary=(
                    "Numeric normalization, scale, coordinate, and conversion "
                    f"contract for {canonical_path}."
                ),
                members=(),
                rules=tuple(dict.fromkeys(specialized.rules)),
                refusal=specialized.refusal,
                evidence=evidence,
                relations=(
                    _relation("profile", f"representation-profile:{specialized.profile.id}"),
                ),
                specialized_contract_key=canonical_path,
                specialized_contract=specialized,
            )
        )
    return tuple(entries)


def _descriptor_entries() -> tuple[PublicTypeContract, ...]:
    surface = _node(
        _SURFACE_TEST,
        "public_identity",
        "member_shape",
        "implementation_identity",
    )
    return (
        _entry(
            "sceneio.ArrayInspection",
            implementation_paths=("sceneio.io._inspectors.model.ArrayInspection",),
            kind="descriptor",
            summary="Immutable shape and dtype summary for one named array.",
            members=_fields(
                "ArrayInspection",
                (("name", "str"), ("shape", "tuple[int, ...]"), ("dtype", "str")),
                ordered=("shape",),
            ),
            rules=("Shape dimensions are ordered and dtype is a stable textual name.",),
            refusal="Construction rejects malformed names, shapes, or dtype metadata.",
            evidence=(
                surface,
                _node(
                    "tests/test_io_inspection_shared.py::test_shared_inspection_types_match_the_current_contract",
                    "construction",
                    "contract",
                ),
            ),
        ),
        _entry(
            "sceneio.CheckpointRef",
            implementation_paths=("sceneio.mapping_input.CheckpointRef",),
            kind="descriptor",
            summary="Immutable reference to one mapping-input checkpoint.",
            members=_fields(
                "CheckpointRef",
                (("seq", "int"), ("path", "Path"), ("summary", "dict")),
                semantics={
                    "seq": "Monotonic checkpoint sequence number.",
                    "path": "Filesystem path containing the checkpoint payload.",
                    "summary": "Detached checkpoint summary metadata.",
                },
            ),
            rules=("Checkpoint discovery orders references by sequence number.",),
            refusal="Duplicate sequence numbers are rejected by checkpoint publication.",
            evidence=(
                surface,
                _node("tests/test_mapping_input.py::test_round_trip", "roundtrip"),
            ),
        ),
        _entry(
            "sceneio.CodecCapabilities",
            implementation_paths=("sceneio.io._registry.model.CodecCapabilities",),
            kind="descriptor",
            summary="Frozen discovery metadata for one registered codec.",
            members=_fields(
                "CodecCapabilities",
                (
                    ("format", "str"),
                    ("payload_kind", "str"),
                    ("record_type", "str | None"),
                    ("extensions", "tuple[str, ...]"),
                    ("filenames", "tuple[str, ...]"),
                    ("container_kind", "str"),
                    ("available", "bool"),
                    ("can_read", "bool"),
                    ("can_write", "bool"),
                    ("can_inspect", "bool"),
                    ("partial_selectors", "tuple[str, ...]"),
                    ("streams_read", "bool"),
                    ("streams_write", "bool"),
                    ("lossy", "bool"),
                    ("requires_features", "tuple[str, ...]"),
                    ("supported_features", "tuple[str, ...]"),
                    ("unsupported_features", "tuple[str, ...]"),
                ),
                ordered=(
                    "extensions",
                    "filenames",
                    "partial_selectors",
                    "requires_features",
                    "supported_features",
                    "unsupported_features",
                ),
                semantics={
                    "payload_kind": "Declared output payload kind for the codec.",
                    "available": "Derived from required optional-provider features.",
                    "partial_selectors": "Ordered bounded selector names exposed by public read_partial.",
                },
            ),
            rules=(
                "Capability snapshots are immutable and detached from the mutable runtime registry.",
                "Supported and unsupported feature vocabularies never overlap.",
            ),
            refusal="Unknown format ids raise FormatError instead of returning a guessed capability.",
            evidence=(
                surface,
                _node(
                    "tests/test_io_capabilities.py::test_capability_hooks_and_metadata_are_consistent",
                    "capability",
                ),
                _node(
                    "tests/test_io_capabilities.py::test_capability_snapshots_are_frozen_and_mapping_is_detached",
                    "immutability",
                ),
            ),
            relations=(_relation("payload_kind", "builtin-payload:*"),),
        ),
        _entry(
            "sceneio.ColmapDatabaseConversionReport",
            implementation_paths=("sceneio.colmap_db.ColmapDatabaseConversionReport",),
            kind="descriptor",
            summary="Destination-free report for an exact COLMAP database profile conversion.",
            members=_fields(
                "ColmapDatabaseConversionReport",
                (
                    ("source_profile", "str"),
                    ("target_profile", "str"),
                    ("writable", "bool"),
                    ("identity_changes", "tuple[tuple[str, object, object], ...]"),
                    ("incompatibilities", "tuple[str, ...]"),
                ),
                ordered=("identity_changes", "incompatibilities"),
            ),
            rules=(
                "The report is computed without opening or mutating a destination database.",
                "Every represented-data incompatibility makes writable false.",
            ),
            refusal="A report never silently authorizes conversion when incompatibilities remain.",
            evidence=(
                surface,
                _evidence("tests/codecs/test_colmap_db.py", "conversion", "refusal"),
            ),
            relations=(_relation("schema", "colmap_db/3"),),
        ),
        _entry(
            "sceneio.ColumnDef",
            implementation_paths=("sceneio.colmap_db.ColumnDef",),
            kind="descriptor",
            summary="One ordered column in the repository-owned COLMAP database schema.",
            members=_fields(
                "ColumnDef",
                (("name", "str"), ("sql_type", "str")),
                (("extension", "bool", "False"), ("note", "str", "''")),
            ),
            rules=("Column declaration order is serialization and schema order.",),
            refusal="Empty names or SQL types are not valid schema declarations.",
            evidence=(
                surface,
                _node(
                    "tests/test_colmap_db_contract.py::test_contract_dict_tables_match_the_table_model",
                    "schema",
                    "serialization",
                ),
            ),
            relations=(_relation("schema", "colmap_db/3"),),
        ),
        _entry(
            "sceneio.CoordinateConvention",
            implementation_paths=("sceneio.coordinates.CoordinateConvention",),
            kind="descriptor",
            summary="Immutable coordinate, pose, image, depth, and scale convention value.",
            members=_fields(
                "CoordinateConvention",
                (("name", "str"),),
                (
                    ("camera_axes", "str", "'not_applicable'"),
                    ("handedness", "str", "'not_applicable'"),
                    ("pose_direction", "str", "'not_applicable'"),
                    ("quaternion_order", "str", "'not_applicable'"),
                    ("quaternion_algebra", "str", "'not_applicable'"),
                    ("world_frame", "str", "'not_applicable'"),
                    ("up_axis", "str", "'not_applicable'"),
                    ("scale_class", "str", "'not_applicable'"),
                    ("scale_to_meters", "float | None", "None"),
                    ("image_origin", "str", "'not_applicable'"),
                    ("image_x_axis", "str", "'not_applicable'"),
                    ("image_y_axis", "str", "'not_applicable'"),
                    ("pixel_center", "tuple[float, float] | None", "None"),
                    ("depth_interpretation", "str", "'not_applicable'"),
                    ("crs", "str | None", "None"),
                    ("reference_frame", "str | None", "None"),
                ),
                units={"scale_to_meters": ("meter",), "pixel_center": ("pixel",)},
                ordered=("pixel_center",),
            ),
            rules=(
                "Not-applicable, unspecified, file-declared, and fixed semantics remain distinct.",
                "A scale_to_meters value is interpreted only with its declared scale class.",
            ),
            refusal="Contradictory coordinate domains or incomplete fixed conventions are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_coordinate_systems.py::test_coordinate_value_types_are_frozen_and_reject_contradictions",
                    "construction",
                    "refusal",
                ),
            ),
        ),
        _entry(
            "sceneio.DatabaseProfile",
            implementation_paths=("sceneio.colmap_db.DatabaseProfile",),
            kind="descriptor",
            summary="Exact supported COLMAP database schema/profile identity.",
            members=_fields(
                "DatabaseProfile",
                (
                    ("name", "str"),
                    ("source_revision", "str"),
                    ("application_id", "int"),
                    ("user_version", "int"),
                    ("typed_descriptors", "bool"),
                    ("generalized_pose_priors", "bool"),
                    ("recovered_two_view_cameras", "bool"),
                ),
                (("maxx_extensions", "bool", "False"), ("ownership_row", "bool", "False")),
            ),
            rules=("Profile identity controls exact schema and conversion behavior.",),
            refusal="Unknown or internally inconsistent database profiles are not inferred.",
            evidence=(
                surface,
                _node(
                    "tests/test_colmap_db_contract.py::test_exact_profile_catalog_is_pinned",
                    "vocabulary",
                    "schema",
                ),
            ),
            relations=(_relation("schema", "colmap_db/3"),),
        ),
        _entry(
            "sceneio.DepthEncoding",
            implementation_paths=("sceneio.io._depth.DepthEncoding",),
            kind="descriptor",
            summary="Explicit stored-depth unit, scale, invalid-value, and channel contract.",
            members=_fields(
                "DepthEncoding",
                (("unit", "str"), ("scale_to_meters", "float"), ("invalid_policy", "str")),
                (("channel_name", "str | None", "None"),),
                units={"scale_to_meters": ("meter",)},
                semantics={
                    "scale_to_meters": "Meters equal stored depth multiplied by this positive scale.",
                    "channel_name": "Exact stored scalar channel when the carrier has named channels.",
                },
            ),
            rules=(
                "Depth meaning is explicit on every typed operation and never guessed from a path.",
            ),
            refusal="Unknown units, non-positive scales, invalid policies, or missing required channels are rejected.",
            evidence=(
                surface,
                _evidence("tests/codecs/test_pfm_typed.py", "construction", "typed_io"),
                _evidence("tests/codecs/test_exr_depth_typed.py", "channel_contract"),
            ),
        ),
        _entry(
            "sceneio.FormatCoordinateContract",
            implementation_paths=("sceneio.coordinates.FormatCoordinateContract",),
            kind="descriptor",
            summary="Per-format coordinate status, domains, writer rule, and conversion boundary.",
            members=_fields(
                "FormatCoordinateContract",
                (
                    ("status", "CoordinateStatus"),
                    ("domains", "tuple[CoordinateDomain, ...]"),
                    ("decoded", "CoordinateConvention | None"),
                    ("writer_requirement", "str"),
                    ("conversion", "Literal['supported', 'requires_context', 'not_applicable']"),
                    ("reference", "str"),
                ),
                ordered=("domains",),
            ),
            rules=("Every built-in format has exactly one immutable coordinate contract.",),
            refusal="Unknown format ids and contradictory status/domain combinations are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_coordinate_systems.py::test_checked_manifest_exactly_covers_registry_in_registry_order",
                    "registry_completeness",
                ),
            ),
        ),
        _entry(
            "sceneio.Inspection",
            implementation_paths=("sceneio.io._inspectors.model.Inspection",),
            kind="descriptor",
            summary="Immutable metadata-only inspection result for one format payload.",
            members=_fields(
                "Inspection",
                (("format", "str"), ("payload_kind", "str"), ("byte_size", "int")),
                (
                    ("shape", "tuple[int, ...] | None", "None"),
                    ("dtype", "str | None", "None"),
                    ("count", "int | None", "None"),
                    ("channels", "int | None", "None"),
                    ("arrays", "tuple[ArrayInspection, ...]", "()"),
                    ("metadata", "Mapping[str, MetadataValue]", "<factory>"),
                ),
                units={"byte_size": ("byte",)},
                ordered=("shape", "arrays"),
            ),
            rules=(
                "Metadata is recursively detached and immutable.",
                "Inspection does not imply bulk payload decode.",
            ),
            refusal="Unsupported or malformed metadata is normalized to FormatError by public I/O.",
            evidence=(
                surface,
                _node(
                    "tests/test_io_inspection_shared.py::test_inspection_metadata_recursively_detaches_and_freezes_containers",
                    "immutability",
                    "metadata",
                ),
            ),
        ),
        _entry(
            "sceneio.MaterializedImage",
            implementation_paths=("sceneio.imagesource.MaterializedImage",),
            kind="descriptor",
            summary="Resolved image name, absolute path, and optional content digest.",
            members=_fields(
                "MaterializedImage",
                (("name", "str"), ("abs_path", "Path")),
                (("content_sha", "str | None", "None"),),
            ),
            rules=(
                "The path is a materialized locator; image pixels remain outside this descriptor.",
            ),
            refusal="An absent digest remains distinct from an asserted but invalid digest.",
            evidence=(
                surface,
                _node(
                    "tests/test_data_views.py::TestViewInput::test_materialized_image_ref",
                    "construction",
                    "composition",
                ),
            ),
        ),
        _entry(
            "sceneio.NativeFeatureCapabilities",
            implementation_paths=("sceneio.io._registry.model.NativeFeatureCapabilities",),
            kind="descriptor",
            summary="Frozen build-option and format metadata for one optional native seam.",
            members=_fields(
                "NativeFeatureCapabilities",
                (
                    ("name", "str"),
                    ("build_option", "str"),
                    ("available", "bool"),
                    ("formats", "tuple[str, ...]"),
                ),
                ordered=("formats",),
            ),
            rules=("Known unavailable seams remain discoverable without importing providers.",),
            refusal="Unknown feature names raise FormatError.",
            evidence=(
                surface,
                _node(
                    "tests/test_io_capabilities.py::test_native_feature_manifest_has_stable_compiled_state",
                    "capability",
                ),
            ),
            relations=(_relation("format", "builtin-format:*"),),
        ),
        _entry(
            "sceneio.NormalizationProfile",
            implementation_paths=("sceneio.representations.NormalizationProfile",),
            kind="descriptor",
            summary="Reusable normalization, scale, coordinate, conversion, unit, and refusal policy.",
            members=_fields(
                "NormalizationProfile",
                (
                    ("id", "str"),
                    ("normalization", "NormalizationPolicy"),
                    ("scale", "ScalePolicy"),
                    ("coordinates", "CoordinatePolicy"),
                    ("conversion", "ConversionPolicy"),
                    ("canonical_units", "tuple[str, ...]"),
                    ("scale_fields", "tuple[str, ...]"),
                    ("rules", "tuple[str, ...]"),
                    ("refusal", "str"),
                ),
                ordered=("canonical_units", "scale_fields", "rules"),
            ),
            rules=("Profile ids and policy/unit vocabularies are closed and validated.",),
            refusal="Unknown policies, duplicate fields/units, and empty rules are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_representation_contracts.py::test_every_contract_uses_a_registered_profile_and_live_evidence",
                    "profile",
                    "evidence",
                ),
            ),
            relations=(_relation("schema", "representation-contract/1"),),
        ),
        _entry(
            "sceneio.RepresentationNormalizationContract",
            implementation_paths=("sceneio.representations.RepresentationNormalizationContract",),
            kind="descriptor",
            summary="Binding from one public representation path to a reusable normalization profile and evidence.",
            members=_fields(
                "RepresentationNormalizationContract",
                (
                    ("representation", "str"),
                    ("profile", "NormalizationProfile"),
                    ("evidence", "tuple[str, ...]"),
                ),
                ordered=("evidence",),
            ),
            rules=("Every entry names one public path and at least one repository evidence file.",),
            refusal="Non-public paths and empty evidence are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_representation_contracts.py::test_contract_catalog_exactly_covers_public_representation_classes",
                    "registry_completeness",
                ),
            ),
            relations=(_relation("schema", "representation-contract/1"),),
        ),
        _entry(
            "sceneio.TableDef",
            implementation_paths=("sceneio.colmap_db.TableDef",),
            kind="descriptor",
            summary="One ordered table in the repository-owned COLMAP database schema.",
            members=_fields(
                "TableDef",
                (("name", "str"), ("columns", "tuple[ColumnDef, ...]")),
                (("extension", "bool", "False"), ("note", "str", "''")),
                ordered=("columns",),
            ),
            rules=("Table and column declaration order is stable serialized schema order.",),
            refusal="Duplicate or malformed table/column definitions are invalid schema state.",
            evidence=(
                surface,
                _node(
                    "tests/test_colmap_db_contract.py::test_contract_dict_tables_match_the_table_model",
                    "schema",
                    "serialization",
                ),
            ),
            relations=(
                _relation("contains", "sceneio.ColumnDef"),
                _relation("schema", "colmap_db/3"),
            ),
        ),
        _entry(
            "sceneio.Codec",
            implementation_paths=("sceneio.io._registry.model.Codec",),
            kind="descriptor",
            summary="One format's immutable read/write/inspect/partial dispatch definition.",
            members=_fields(
                "Codec",
                (
                    ("id", "str"),
                    ("extensions", "tuple[str, ...]"),
                    ("read", "Callable[[str], object]"),
                    ("write", "Callable[[object, str], None] | None"),
                    ("record", "type | None"),
                    ("payload_kind", "str"),
                ),
                (
                    ("magic", "tuple[bytes, ...]", "()"),
                    ("filenames", "tuple[str, ...]", "()"),
                    ("is_directory", "bool", "False"),
                    ("dir_marker", "str", "'cameras.bin'"),
                    ("directory_markers", "tuple[str, ...]", "()"),
                    ("file_probe", "Callable[[Path], bool] | None", "None"),
                    ("directory_probe", "Callable[[Path], bool] | None", "None"),
                    ("inspect", "Callable[[str], object] | None", "None"),
                    ("read_window", "Callable[[str, int, int, int, int], object] | None", "None"),
                    ("read_points", "Callable[[str, int, int], object] | None", "None"),
                    ("read_faces", "Callable[[str, int, int], object] | None", "None"),
                    ("read_mesh", "Callable[[str, int], object] | None", "None"),
                    ("read_primitive", "Callable[[str, int], object] | None", "None"),
                    ("read_states", "Callable[[str, int, int], object] | None", "None"),
                    ("read_frames", "Callable[[str, int, int], object] | None", "None"),
                    ("read_image", "Callable[[str, int], object] | None", "None"),
                    ("read_pair", "Callable[[str, int, int], object] | None", "None"),
                    ("read_tensors", "Callable[[str, tuple[str, ...]], object] | None", "None"),
                    (
                        "read_slices",
                        "Callable[[str, tuple[tuple[str, int, int], ...]], object] | None",
                        "None",
                    ),
                    ("streams_read", "bool", "True"),
                    ("streams_write", "bool", "True"),
                    ("lossy", "bool", "False"),
                    ("requires_features", "tuple[str, ...]", "()"),
                    ("supported_features", "tuple[str, ...]", "()"),
                    ("unsupported_features", "tuple[str, ...]", "()"),
                    ("container_kind", "str | None", "None"),
                ),
                ordered=(
                    "extensions",
                    "magic",
                    "filenames",
                    "directory_markers",
                    "requires_features",
                    "supported_features",
                    "unsupported_features",
                ),
                semantics={
                    "payload_kind": "Declared output payload kind for the codec.",
                    "record": "Static output class when the format does not require profile-dependent dispatch.",
                },
            ),
            rules=(
                "Built-in codecs are assembled atomically in canonical manifest order.",
                "Runtime extension registration remains open outside built-in completeness.",
            ),
            refusal="Built-in assembly rejects unknown ids, duplicate ids, and undeclared built-in payload kinds.",
            evidence=(
                surface,
                _node(
                    "tests/test_io_registry_architecture.py::test_third_party_registration_is_outside_builtin_completeness_boundary",
                    "extension_boundary",
                ),
                _node(
                    "tests/test_io_registry_assembly.py::test_family_staging_is_exact_atomic_and_recoverable",
                    "atomicity",
                ),
            ),
            relations=(_relation("payload_kind", "builtin-payload:*"),),
        ),
    )


def _wire_entries() -> tuple[PublicTypeContract, ...]:
    surface = _node(
        _SURFACE_TEST,
        "public_identity",
        "member_shape",
        "implementation_identity",
    )
    return (
        _entry(
            "sceneio.Point3DRecord",
            implementation_paths=("sceneio.points_binary.Point3DRecord",),
            kind="wire_record",
            summary="One fixed-size application/x-sfm-points-v1 point record.",
            members=_fields(
                "Point3DRecord",
                (
                    ("point3d_id", "int"),
                    ("xyz", "tuple[float, float, float]"),
                    ("rgb", "tuple[int, int, int]"),
                    ("track_len", "int"),
                ),
                units={"xyz": ("source_length_unit",)},
                ordered=("xyz", "rgb"),
                semantics={
                    "point3d_id": "Unsigned stable point identifier on the wire.",
                    "xyz": "Ordered XYZ coordinates preserved as encoded floats.",
                    "rgb": "Ordered red, green, blue uint8 values.",
                    "track_len": "Unsigned observation count associated with the point.",
                },
            ),
            rules=(
                "Record layout and header constants are fixed by application/x-sfm-points-v1.",
                "Encoding preserves record order and the declared bounding box.",
            ),
            refusal="Invalid magic, truncated payloads, and out-of-domain field values are rejected.",
            evidence=(
                surface,
                _node("tests/test_points_binary.py::test_round_trip", "roundtrip"),
                _node(
                    "tests/test_points_binary.py::test_record_layout_is_fixed_size",
                    "wire_layout",
                ),
            ),
            relations=(_relation("schema", "application/x-sfm-points-v1"),),
        ),
    )


def _procedure_entries() -> tuple[PublicTypeContract, ...]:
    surface = _node(
        _SURFACE_TEST,
        "public_identity",
        "member_shape",
        "implementation_identity",
    )
    return (
        _entry(
            "sceneio.mapping.MapperTraits",
            implementation_paths=("sceneio.mapping.MapperTraits",),
            kind="procedure_value",
            procedure_role="traits",
            summary="Declared requirements and output capabilities of a Mapper implementation.",
            members=_fields(
                "MapperTraits",
                (
                    ("requires_correspondences", "bool"),
                    ("accepts_pose_priors", "bool"),
                    ("accepts_depth_priors", "bool"),
                    ("accepts_calibration", "bool"),
                    ("emits_dense", "bool"),
                    ("metric_capable", "bool"),
                ),
            ),
            rules=("A Mapper must behave consistently with every declared trait.",),
            refusal="Non-boolean trait values and dishonest implementation behavior are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_mapping_contracts.py::TestMapperTraits::test_valid", "construction"
                ),
                _node(
                    "tests/test_conformance_kits.py::TestMapperConformanceKit::test_dishonest_metric_claim_fails",
                    "procedure_conformance",
                ),
            ),
            relations=(_relation("operation", "mapping"),),
        ),
        _entry(
            "sceneio.mapping.MappingOptions",
            implementation_paths=("sceneio.mapping.MappingOptions",),
            kind="procedure_value",
            procedure_role="options",
            summary="Common mapping controls plus a copied implementation-specific option map.",
            members=_fields(
                "MappingOptions",
                (),
                (
                    ("max_views", "int | None", "None"),
                    ("seed", "int | None", "None"),
                    ("extra", "Mapping[str, object]", "<factory>"),
                ),
            ),
            rules=("max_views is positive when present and extra is copied to a plain dict.",),
            refusal="Boolean/inapplicable integers and non-mapping extra values are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_mapping_contracts.py::TestMappingOptions::test_defaults",
                    "construction",
                ),
            ),
            relations=(_relation("input_to", "sceneio.mapping.Mapper"),),
        ),
        _entry(
            "sceneio.mapping.MappingResult",
            implementation_paths=("sceneio.mapping.MappingResult",),
            kind="procedure_value",
            procedure_role="result",
            summary="Index-aligned mapping output with explicit frame, scale, sparse, and dense state.",
            members=_fields(
                "MappingResult",
                (("poses", "tuple[SE3 | None, ...]"), ("frame", "FrameMeta")),
                (
                    ("calibrations", "tuple[Calibration | None, ...] | None", "None"),
                    ("geometry", "PointCloud | None", "None"),
                    ("dense", "tuple[tuple[Pointmap, ConfidenceMap] | None, ...] | None", "None"),
                    ("stats", "Mapping[str, object]", "<factory>"),
                ),
                ordered=("poses", "calibrations", "dense"),
            ),
            rules=(
                "All per-view members are index-aligned and at least one pose is registered.",
                "Registered poses share one convention; dense shapes match their confidence maps.",
            ),
            refusal="All-unregistered, misaligned, mixed-convention, or wrong-type results are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_mapping_contracts.py::TestMappingResult::test_full_valid",
                    "construction",
                ),
                _node(
                    "tests/test_conformance_kits.py::TestMapperConformanceKit::test_misaligned_poses_fail",
                    "procedure_conformance",
                ),
            ),
            relations=(
                _relation("output_of", "sceneio.mapping.Mapper"),
                _relation("contains", "sceneio.FrameMeta"),
                _relation("contains", "sceneio.PointCloud"),
            ),
        ),
        _entry(
            "sceneio.matching.MatcherTraits",
            implementation_paths=("sceneio.matching.MatcherTraits",),
            kind="procedure_value",
            procedure_role="traits",
            summary="Persistent-keypoint and detector-free identity of a PairMatcher.",
            members=_fields(
                "MatcherTraits",
                (("persistent_keypoints", "bool"), ("detector_free", "bool")),
            ),
            rules=("Matcher operand and output mode must agree with detector_free.",),
            refusal="Non-boolean traits and dishonest operand/output behavior are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_matching_contracts.py::TestMatcherTraits::test_detector_based",
                    "construction",
                ),
                _node(
                    "tests/test_conformance_kits.py::TestMatcherConformanceKit::test_dishonest_detector_free_claim_fails",
                    "procedure_conformance",
                ),
            ),
            relations=(_relation("operation", "matching"),),
        ),
        _entry(
            "sceneio.matching.MatchingOptions",
            implementation_paths=("sceneio.matching.MatchingOptions",),
            kind="procedure_value",
            procedure_role="options",
            summary="Common matching controls plus a copied implementation-specific option map.",
            members=_fields(
                "MatchingOptions",
                (),
                (("seed", "int | None", "None"), ("extra", "Mapping[str, object]", "<factory>")),
            ),
            rules=("extra is copied to a plain dict and seed remains an integer when present.",),
            refusal="Boolean/non-integer seeds and non-mapping extra values are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_matching_contracts.py::TestMatchingOptions::test_defaults",
                    "construction",
                ),
            ),
            relations=(
                _relation("input_to", "sceneio.matching.FeatureExtractor"),
                _relation("input_to", "sceneio.matching.PairMatcher"),
                _relation("input_to", "sceneio.matching.GeometricVerifier"),
            ),
        ),
    )


def _protocol_entries() -> tuple[PublicTypeContract, ...]:
    signature_evidence = _node(
        _PROTOCOL_TEST,
        "public_identity",
        "method_signature",
        "procedure_conformance",
    )
    return (
        _entry(
            "sceneio.BlobStore",
            implementation_paths=("sceneio.blobstore.BlobStore",),
            kind="protocol",
            summary="Content-addressed blob storage interface.",
            members=(
                _method(
                    "put_bytes",
                    "(self, data: 'bytes') -> 'tuple[str, int]'",
                    "Store bytes and return digest plus byte count.",
                ),
                _method(
                    "put_stream",
                    "(self, reader: 'BinaryIO', *, chunk_size: 'int' = Ellipsis) -> 'tuple[str, int]'",
                    "Stream a blob and return digest plus byte count.",
                ),
                _method(
                    "open",
                    "(self, sha: 'str') -> 'BinaryIO'",
                    "Open a readable binary stream for a digest.",
                ),
                _method(
                    "local_path",
                    "(self, sha: 'str') -> 'Path'",
                    "Return a local materialized path when supported.",
                ),
                _method("exists", "(self, sha: 'str') -> 'bool'", "Test digest presence."),
                _method("delete", "(self, sha: 'str') -> 'None'", "Delete a digest-owned blob."),
                _method(
                    "aiter_chunks",
                    "(self, sha: 'str', *, chunk_size: 'int' = Ellipsis) -> 'AsyncIterator[bytes]'",
                    "Iterate blob bytes in ordered chunks.",
                ),
            ),
            rules=(
                "Digest identity is content-addressed and byte counts describe stored payload bytes.",
            ),
            refusal="Implementations must reject invalid digests and unavailable blobs without fabricating content.",
            evidence=(signature_evidence,),
        ),
        _entry(
            "sceneio.ImageSourceImpl",
            implementation_paths=("sceneio.imagesource.ImageSourceImpl",),
            kind="protocol",
            summary="Materialization and fingerprint interface for external image sources.",
            members=(
                _method(
                    "materialize",
                    "(self, into: 'Path') -> 'list[MaterializedImage]'",
                    "Materialize ordered image references into a destination.",
                ),
                _method(
                    "fingerprint",
                    "(self) -> 'dict'",
                    "Return deterministic source fingerprint metadata.",
                ),
            ),
            rules=("Materialized images retain names and optional content digests.",),
            refusal="Implementations must not claim a digest or materialized path they did not produce.",
            evidence=(signature_evidence,),
            relations=(_relation("output_of", "sceneio.MaterializedImage"),),
        ),
        _entry(
            "sceneio.mapping.Mapper",
            implementation_paths=("sceneio.mapping.Mapper",),
            kind="protocol",
            summary="Neutral mapping procedure from ordered views to a MappingResult.",
            members=(
                _method(
                    "traits", "(self) -> 'MapperTraits'", "Return immutable implementation traits."
                ),
                _method(
                    "map",
                    "(self, views: 'Sequence[ViewInput]', *, correspondences: 'CorrespondenceGraph | None' = None, options: 'MappingOptions | None' = None) -> 'MappingResult'",
                    "Map ordered views under declared correspondence and option semantics.",
                ),
            ),
            rules=(
                "Implementation behavior must remain honest with traits and preserve view alignment.",
            ),
            refusal="Missing required correspondences and dishonest metric/dense claims fail conformance.",
            evidence=(
                signature_evidence,
                _node(
                    "tests/test_conformance_kits.py::TestMapperConformanceKit::test_feed_forward_mapper_passes",
                    "procedure_conformance",
                ),
            ),
            relations=(
                _relation("input_to", "sceneio.ViewInput"),
                _relation("output_of", "sceneio.mapping.MappingResult"),
            ),
        ),
        _entry(
            "sceneio.matching.FeatureExtractor",
            implementation_paths=("sceneio.matching.FeatureExtractor",),
            kind="protocol",
            summary="Feature extraction procedure from one image reference to a FeatureSet.",
            members=(
                _method(
                    "extract",
                    "(self, image: 'ImageRef', *, options: 'MatchingOptions | None' = None) -> 'FeatureSet'",
                    "Extract one persistent per-image feature set.",
                ),
            ),
            rules=("Returned features satisfy the neutral FeatureSet contract.",),
            refusal="Invalid operands or outputs fail matcher conformance.",
            evidence=(signature_evidence,),
            relations=(
                _relation("input_to", "sceneio.ImageRef"),
                _relation("output_of", "sceneio.FeatureSet"),
            ),
        ),
        _entry(
            "sceneio.matching.GeometricVerifier",
            implementation_paths=("sceneio.matching.GeometricVerifier",),
            kind="protocol",
            summary="Geometric filtering procedure for pair correspondences.",
            members=(
                _method(
                    "verify",
                    "(self, pair: 'PairCorrespondences', *, options: 'MatchingOptions | None' = None) -> 'PairCorrespondences'",
                    "Return a mode-preserving subset with optional geometry.",
                ),
            ),
            rules=("Verification preserves correspondence mode and never grows the pair.",),
            refusal="Mode switches and growing outputs fail conformance.",
            evidence=(
                signature_evidence,
                _node(
                    "tests/test_conformance_kits.py::TestMatcherConformanceKit::test_growing_verifier_fails",
                    "procedure_conformance",
                ),
            ),
            relations=(
                _relation("input_to", "sceneio.PairCorrespondences"),
                _relation("output_of", "sceneio.PairCorrespondences"),
            ),
        ),
        _entry(
            "sceneio.matching.PairMatcher",
            implementation_paths=("sceneio.matching.PairMatcher",),
            kind="protocol",
            summary="Detector-based or detector-free pair matching procedure.",
            members=(
                _method(
                    "traits",
                    "(self) -> 'MatcherTraits'",
                    "Return persistent-keypoint and detector-free traits.",
                ),
                _method(
                    "match_pair",
                    "(self, a: 'FeatureSet | ImageRef', b: 'FeatureSet | ImageRef', *, options: 'MatchingOptions | None' = None) -> 'PairCorrespondences'",
                    "Match one ordered operand pair under the declared mode.",
                ),
            ),
            rules=("Operand type and correspondence mode must agree with detector_free.",),
            refusal="Dishonest traits, wrong operand families, and invalid indices fail conformance.",
            evidence=(
                signature_evidence,
                _node(
                    "tests/test_conformance_kits.py::TestMatcherConformanceKit::test_detector_based_stack_passes",
                    "procedure_conformance",
                ),
            ),
            relations=(_relation("output_of", "sceneio.PairCorrespondences"),),
        ),
    )


def _vocabulary_entries() -> tuple[PublicTypeContract, ...]:
    surface = _node(
        _SURFACE_TEST,
        "public_identity",
        "member_shape",
        "implementation_identity",
    )
    return (
        _entry(
            "sceneio.CameraModel",
            implementation_paths=("sceneio._data.calibration.CameraModel",),
            kind="vocabulary",
            summary="Closed public COLMAP camera-model vocabulary used by neutral calibration records.",
            members=tuple(_enum_value(value, value) for value in CAMERA_MODEL_NAMES),
            rules=(
                "Member names and string values are identical and stable.",
                "The camera-model vocabulary is closed for this contract version.",
            ),
            refusal="Unknown model strings are rejected rather than mapped to a nearby camera model.",
            evidence=(
                surface,
                _node(
                    "tests/test_data_calibration.py::TestCameraModel::test_colmap_model_ids_are_stable",
                    "vocabulary",
                ),
            ),
        ),
        _entry(
            "sceneio.formats.DataType",
            implementation_paths=("sceneio.formats.datatypes.DataType",),
            kind="vocabulary",
            summary="One cross-SceneAPI logical pipeline type identity.",
            members=_fields(
                "DataType",
                (("type_id", "str"), ("title", "str"), ("kind", "str"), ("description", "str")),
            ),
            rules=(
                "The eight CORE_DATA_TYPES ids, order, kind, title, and description are stable wire vocabulary.",
                "New logical ids require a separately versioned cross-repository change.",
            ),
            refusal="Unknown ids are not accepted as core logical DataTypes.",
            evidence=(
                surface,
                _node(
                    "tests/test_formats_datatypes.py::test_core_datatype_ids_mirror_core_vocabulary_in_order",
                    "vocabulary",
                    "compatibility",
                ),
                _node(
                    "tests/test_formats_datatypes.py::test_contract_dict_is_json_serializable_and_self_describing",
                    "serialization",
                ),
            ),
            relations=(_relation("schema", "datatypes/1"),),
        ),
        _entry(
            "sceneio.formats.FormatSpec",
            implementation_paths=("sceneio.formats.registry.FormatSpec",),
            kind="vocabulary",
            summary="One stable cross-SceneAPI artifact-format identity.",
            members=_fields(
                "FormatSpec",
                (
                    ("id", "str"),
                    ("kind", "str"),
                    ("media_type", "str | None"),
                    ("description", "str"),
                ),
            ),
            rules=(
                "Format kind names one artifact logical DataType and format ids retain exact wire identity.",
                "The core format vocabulary changes only through an explicit contract-version review.",
            ),
            refusal="Empty ids/kinds/descriptions and invalid empty media types are rejected.",
            evidence=(
                surface,
                _node(
                    "tests/test_formats_registry.py::test_core_format_ids_mirror_core_artifacts_vocabulary",
                    "vocabulary",
                    "compatibility",
                ),
            ),
            relations=(_relation("schema", "artifact-formats/1"),),
        ),
    )


def _error_entries() -> tuple[PublicTypeContract, ...]:
    evidence = (_node(_ERROR_TEST, "public_identity", "error_hierarchy", "error_boundary"),)

    def error(
        canonical: str,
        implementation: str,
        parent: str,
        summary: str,
        refusal: str,
        retry_policy: str = "non_retryable",
    ) -> PublicTypeContract:
        return _entry(
            canonical,
            implementation_paths=(implementation,),
            kind="error",
            summary=summary,
            members=(),
            rules=(
                "The exception class and hierarchy are contractual; free-form message text is not unless separately snapshotted.",
                f"Retry policy: {retry_policy}.",
            ),
            refusal=refusal,
            evidence=evidence,
            relations=(_relation("parent_error", parent),),
        )

    return (
        error(
            "sceneio.SceneIoError",
            "sceneio.errors.SceneIoError",
            "builtins.Exception",
            "Root exception for SceneIO contract and I/O failures.",
            "It is not used to hide unrelated programming or system exceptions.",
            retry_policy="operation_dependent",
        ),
        error(
            "sceneio.ContractViolation",
            "sceneio.errors.ContractViolation",
            "sceneio.SceneIoError",
            "Construction or procedure-contract violation.",
            "Invalid caller-owned values are not normalized silently.",
        ),
        error(
            "sceneio.FormatError",
            "sceneio.io.registry.FormatError",
            "sceneio.SceneIoError",
            "Normalized public format detection, inspection, read, or write failure.",
            "Provider-specific failures do not escape public I/O without normalization.",
        ),
        error(
            "sceneio.colmap.ColmapAdapterError",
            "sceneio.colmap.models.ColmapAdapterError",
            "builtins.ValueError",
            "Portable COLMAP workflow-adapter value or wire failure.",
            "Malformed adapter payloads are rejected without partial publication.",
        ),
        error(
            "sceneio.colmap_mvs.ColmapMvsError",
            "sceneio.colmap_mvs.ColmapMvsError",
            "sceneio.SceneIoError",
            "COLMAP dense-workspace topology, configuration, or payload failure.",
            "Ambiguous or inconsistent workspace state is never guessed.",
        ),
    )


def _contract_metadata_entries() -> tuple[PublicTypeContract, ...]:
    evidence = (_node(_SELF_TEST, "public_identity", "member_shape", "self_classification"),)
    return (
        _entry(
            "sceneio.contracts.ContractMember",
            implementation_paths=("sceneio.contracts.model.ContractMember",),
            kind="descriptor",
            summary="Machine-readable field, method, or enum-value contract member.",
            members=_fields(
                "ContractMember",
                (
                    ("name", "str"),
                    ("kind", "ContractMemberKind"),
                    ("type_expression", "str"),
                    ("presence", "ContractPresence"),
                    ("mutability", "ContractMutability"),
                    ("semantics", "str"),
                ),
                (
                    ("default", "str | None", "None"),
                    ("units", "tuple[str, ...]", "()"),
                    ("ordered", "bool | None", "None"),
                ),
                ordered=("units",),
            ),
            rules=(
                "Member kind, presence, mutability, units, and ordering use closed validated vocabularies.",
            ),
            refusal="Empty names/types/semantics and incompatible member-kind metadata are rejected.",
            evidence=evidence,
            relations=(_relation("schema", "public-type-contract/1"),),
        ),
        _entry(
            "sceneio.contracts.ContractEvidence",
            implementation_paths=("sceneio.contracts.model.ContractEvidence",),
            kind="descriptor",
            summary="Repository-relative executable evidence for contract claims.",
            members=_fields(
                "ContractEvidence",
                (("path", "str"), ("claims", "tuple[str, ...]")),
                (("node_id", "str | None", "None"), ("artifact", "str | None", "None")),
                ordered=("claims",),
            ),
            rules=(
                "Paths are repository-relative POSIX paths and node ids begin with their path.",
            ),
            refusal="Absolute, parent-escaping, duplicate, empty, or malformed evidence is rejected.",
            evidence=evidence,
            relations=(_relation("schema", "public-type-contract/1"),),
        ),
        _entry(
            "sceneio.contracts.ContractRelation",
            implementation_paths=("sceneio.contracts.model.ContractRelation",),
            kind="descriptor",
            summary="Typed edge from one public type contract to another contract subject.",
            members=_fields(
                "ContractRelation",
                (("kind", "ContractRelationKind"), ("target", "str")),
            ),
            rules=(
                "Relation kinds use a closed vocabulary and targets are validated by the assembled catalog.",
            ),
            refusal="Unknown relation kinds and empty targets are rejected.",
            evidence=evidence,
            relations=(_relation("schema", "public-type-contract/1"),),
        ),
        _entry(
            "sceneio.contracts.PublicTypeContract",
            implementation_paths=("sceneio.contracts.model.PublicTypeContract",),
            kind="descriptor",
            summary="Immutable common envelope for one canonical public class identity.",
            members=_fields(
                "PublicTypeContract",
                (
                    ("canonical_path", "str"),
                    ("implementation_paths", "tuple[str, ...]"),
                    ("kind", "ContractKind"),
                    ("stability", "ContractStability"),
                    ("summary", "str"),
                    ("members", "tuple[ContractMember, ...]"),
                    ("rules", "tuple[str, ...]"),
                    ("refusal", "str"),
                    ("evidence", "tuple[ContractEvidence, ...]"),
                ),
                (
                    ("procedure_role", "ProcedureRole | None", "None"),
                    ("relations", "tuple[ContractRelation, ...]", "()"),
                    ("specialized_contract_key", "str | None", "None"),
                    ("specialized_contract", "object | None", "None"),
                ),
                ordered=(
                    "implementation_paths",
                    "members",
                    "rules",
                    "evidence",
                    "relations",
                ),
            ),
            rules=(
                "Canonical paths, implementation identities, members, evidence, relations, and kind-specific requirements are validated atomically.",
            ),
            refusal="Incomplete, duplicate, ambiguous, or kind-incompatible entries are rejected before publication.",
            evidence=evidence,
            relations=(_relation("schema", "public-type-contract/1"),),
        ),
        _entry(
            "sceneio.contracts.CodecPayloadKind",
            implementation_paths=("sceneio.contracts.payloads.CodecPayloadKind",),
            kind="descriptor",
            summary="One SceneIO-owned built-in codec payload-kind contract.",
            members=_fields(
                "CodecPayloadKind",
                (
                    ("id", "str"),
                    ("title", "str"),
                    ("description", "str"),
                    ("public_types", "tuple[str, ...]"),
                    ("format_ids", "tuple[str, ...]"),
                    ("evidence", "tuple[str, ...]"),
                ),
                (
                    ("logical_data_type_id", "str | None", "None"),
                    ("dynamic_output_rule", "str | None", "None"),
                ),
                ordered=("public_types", "format_ids", "evidence"),
            ),
            rules=(
                "Built-in payload ids are unique, used, and distinct from runtime extension tokens.",
            ),
            refusal="Unknown built-in payload ids and unqualified empty dynamic outputs are rejected.",
            evidence=evidence,
            relations=(_relation("schema", "builtin-codec-payloads/1"),),
        ),
    )


def manifest_entries() -> tuple[PublicTypeContract, ...]:
    """Return every SceneIO-owned public class contract before indexing."""

    return (
        *_representation_entries(),
        *_descriptor_entries(),
        *_wire_entries(),
        *_procedure_entries(),
        *_protocol_entries(),
        *_vocabulary_entries(),
        *_error_entries(),
        *_contract_metadata_entries(),
    )


__all__ = [
    "BASELINE_PUBLIC_TYPE_NAMESPACES",
    "PUBLIC_TYPE_NAMESPACES",
    "manifest_entries",
]
