"""Exhaustive contracts for SceneIO's public class and codec payload surface."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import hashlib
import importlib
import inspect
import io as stdlib_io
import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from types import MappingProxyType

import pytest

import sceneio
import sceneio.colmap
import sceneio.colmap_mvs
import sceneio.contracts
import sceneio.contracts.payloads as payload_module
import sceneio.data
import sceneio.formats
import sceneio.io
import sceneio.mapping
import sceneio.matching
import sceneio.testing
from sceneio.contracts import (
    BUILTIN_CODEC_PAYLOAD_KINDS,
    PUBLIC_TYPE_ALIASES,
    PUBLIC_TYPE_CONTRACTS,
    ContractEvidence,
    ContractMember,
    ContractRelation,
    PublicTypeContract,
    catalog_dict,
    public_type_contract,
)
from sceneio.contracts.manifest import (
    BASELINE_PUBLIC_TYPE_NAMESPACES,
    PUBLIC_TYPE_NAMESPACES,
)
from sceneio.contracts.registry import (
    _build_path_index,
    _validate_catalog,
    _validate_runtime_identities,
)
from sceneio.formats import CORE_DATA_TYPES
from sceneio.io import registry as io_registry
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS
from sceneio.io._registry.assembly import _validate_payload_contracts
from sceneio.representations import REPRESENTATION_CONTRACTS

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "tests/contracts/public_type_standardization_v1.toml"
SNAPSHOT = tomllib.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

_PUBLIC_MODULES = {
    "sceneio": sceneio,
    "sceneio.io": sceneio.io,
    "sceneio.data": sceneio.data,
    "sceneio.colmap": sceneio.colmap,
    "sceneio.colmap_mvs": sceneio.colmap_mvs,
    "sceneio.formats": sceneio.formats,
    "sceneio.mapping": sceneio.mapping,
    "sceneio.matching": sceneio.matching,
    "sceneio.testing": sceneio.testing,
    "sceneio.contracts": sceneio.contracts,
}
_DATA_CONTRACT_KINDS = {
    "wire_record",
    "descriptor",
    "procedure_value",
    "vocabulary",
}


def _resolve(path: str) -> object:
    module_name, _, name = path.rpartition(".")
    return getattr(importlib.import_module(module_name), name)


def _exported_class_paths() -> dict[int, tuple[type[object], set[str]]]:
    exports: dict[int, tuple[type[object], set[str]]] = {}
    for prefix in SNAPSHOT["catalog_namespaces"]:
        module = _PUBLIC_MODULES[prefix]
        for name in module.__all__:
            value = getattr(module, name)
            if not inspect.isclass(value):
                continue
            identity = id(value)
            if identity not in exports:
                exports[identity] = (value, set())
            exports[identity][1].add(f"{prefix}.{name}")
    return exports


def _minimal_descriptor(
    canonical_path: str,
    *,
    aliases: tuple[str, ...] = (),
    relations: tuple[ContractRelation, ...] = (),
) -> PublicTypeContract:
    return PublicTypeContract(
        canonical_path=canonical_path,
        aliases=aliases,
        implementation_paths=(),
        kind="descriptor",
        stability="stable",
        summary="Focused registry validation fixture.",
        members=(
            ContractMember(
                name="value",
                kind="field",
                type_expression="str",
                presence="required",
                mutability="immutable",
                semantics="Fixture value.",
            ),
        ),
        rules=("The fixture remains valid.",),
        refusal="Invalid fixture values are rejected.",
        evidence=(
            ContractEvidence(
                path="tests/test_public_type_contracts.py",
                node_id=(
                    "tests/test_public_type_contracts.py::"
                    "test_model_and_registry_reject_malformed_contracts"
                ),
                claims=("construction",),
            ),
        ),
        relations=relations,
    )


def test_frozen_census_exactly_matches_every_public_class_identity() -> None:
    assert SNAPSHOT["schema_version"] == 1
    assert tuple(_PUBLIC_MODULES) == tuple(SNAPSHOT["catalog_namespaces"])
    assert tuple(SNAPSHOT["baseline_namespaces"]) == tuple(_PUBLIC_MODULES)[:-1]
    assert tuple(SNAPSHOT["catalog_namespaces"]) == PUBLIC_TYPE_NAMESPACES
    assert tuple(SNAPSHOT["baseline_namespaces"]) == (BASELINE_PUBLIC_TYPE_NAMESPACES)

    exports = _exported_class_paths()
    assert len(exports) == SNAPSHOT["catalog_identity_count"] == 144
    assert len(PUBLIC_TYPE_CONTRACTS) == len(exports)

    resolved_paths: set[str] = set()
    for cls, exported_paths in exports.values():
        contract = public_type_contract(cls)
        resolved_paths.add(contract.canonical_path)
        supported_paths = {contract.canonical_path, *contract.aliases}
        assert exported_paths <= supported_paths, (contract, exported_paths)
        for path in exported_paths:
            assert _resolve(path) is cls
    assert resolved_paths == set(PUBLIC_TYPE_CONTRACTS)

    baseline_paths = tuple(
        path for path in PUBLIC_TYPE_CONTRACTS if not path.startswith("sceneio.contracts.")
    )
    assert baseline_paths == tuple(SNAPSHOT["baseline"]["canonical_paths"])
    assert len(baseline_paths) == SNAPSHOT["baseline_identity_count"] == 139
    assert (
        Counter(contract.kind for contract in PUBLIC_TYPE_CONTRACTS.values())
        == (SNAPSHOT["contract_kind_counts"])
    )

    baseline_classes = [
        cls
        for cls, _ in exports.values()
        if not public_type_contract(cls).canonical_path.startswith("sceneio.contracts.")
    ]
    representation_classes = [
        cls for cls in baseline_classes if public_type_contract(cls).kind == "representation"
    ]
    remaining = [cls for cls in baseline_classes if cls not in representation_classes]
    classification = {
        "representation": len(representation_classes),
        "dataclass": sum(dataclasses.is_dataclass(cls) for cls in remaining),
        "protocol": sum(bool(getattr(cls, "_is_protocol", False)) for cls in remaining),
        "error": sum(issubclass(cls, Exception) for cls in remaining if cls is not Exception),
        "enum": sum(
            issubclass(cls, __import__("enum").Enum)
            for cls in remaining
            if cls is not __import__("enum").Enum
        ),
    }
    assert classification == SNAPSHOT["baseline_classification"]


def test_representation_envelopes_adapt_the_authoritative_objects() -> None:
    representation_entries = {
        path: contract
        for path, contract in PUBLIC_TYPE_CONTRACTS.items()
        if contract.kind == "representation"
    }
    assert len(representation_entries) == SNAPSHOT["representation_count"] == 103
    assert set(representation_entries) == set(REPRESENTATION_CONTRACTS)
    for path, entry in representation_entries.items():
        specialized = REPRESENTATION_CONTRACTS[path]
        assert entry.specialized_contract is specialized
        assert entry.specialized_contract_key == path
        assert entry.members == ()
        assert {evidence.path for evidence in entry.evidence} == set(specialized.evidence)
        assert sceneio.representation_contract(path) is specialized


def test_non_representation_contracts_match_runtime_surface() -> None:
    procedure_roles = {
        "sceneio.mapping.MapperTraits": "traits",
        "sceneio.mapping.MappingOptions": "options",
        "sceneio.mapping.MappingResult": "result",
        "sceneio.matching.MatcherTraits": "traits",
        "sceneio.matching.MatchingOptions": "options",
    }
    for path, contract in PUBLIC_TYPE_CONTRACTS.items():
        if contract.kind not in _DATA_CONTRACT_KINDS:
            continue
        cls = _resolve(path)
        if dataclasses.is_dataclass(cls):
            fields = dataclasses.fields(cls)
            field_members = tuple(member for member in contract.members if member.kind == "field")
            assert tuple(field.name for field in fields) == tuple(
                member.name for member in field_members
            )
            assert cls.__dataclass_params__.frozen
            for field, member in zip(fields, field_members, strict=True):
                has_default = (
                    field.default is not dataclasses.MISSING
                    or field.default_factory is not dataclasses.MISSING
                )
                assert (member.presence == "optional") is has_default
                assert member.mutability == "immutable"
                assert member.semantics

        canonical_cls = _resolve(contract.canonical_path)
        for alias in (*contract.aliases, *contract.implementation_paths):
            assert _resolve(alias) is canonical_cls
            assert public_type_contract(alias) is contract
        assert public_type_contract(canonical_cls) is contract
        assert contract.procedure_role == procedure_roles.get(path)


def test_protocol_contracts_match_runtime_signatures(tmp_path: Path) -> None:
    protocols = {
        path: contract
        for path, contract in PUBLIC_TYPE_CONTRACTS.items()
        if contract.kind == "protocol"
    }
    assert len(protocols) == 6
    for path, contract in protocols.items():
        protocol = _resolve(path)
        assert protocol._is_protocol
        assert {member.name for member in contract.members} == {
            name
            for name in protocol.__dict__
            if not name.startswith("_") and callable(getattr(protocol, name))
        }
        for member in contract.members:
            assert member.kind == "method"
            assert str(inspect.signature(getattr(protocol, member.name))) == (
                member.type_expression
            )

    class MemoryBlobStore:
        def __init__(self) -> None:
            self.values: dict[str, bytes] = {}

        def exists(self, sha: str) -> bool:
            return sha in self.values

        def put_bytes(self, data: bytes) -> tuple[str, int]:
            sha = hashlib.sha256(data).hexdigest()
            self.values[sha] = data
            return sha, len(data)

        def put_stream(
            self,
            reader,
            *,
            chunk_size: int = 1024,
        ) -> tuple[str, int]:
            del chunk_size
            return self.put_bytes(reader.read())

        def open(self, sha: str):
            return stdlib_io.BytesIO(self.values[sha])

        def local_path(self, sha: str) -> Path:
            path = tmp_path / sha
            path.write_bytes(self.values[sha])
            return path

        def delete(self, sha: str) -> None:
            del self.values[sha]

        async def aiter_chunks(self, sha: str, *, chunk_size: int = 2):
            value = self.values[sha]
            for offset in range(0, len(value), chunk_size):
                yield value[offset : offset + chunk_size]

    async def collect_chunks(store: MemoryBlobStore, sha: str) -> bytes:
        return b"".join([chunk async for chunk in store.aiter_chunks(sha)])

    blob_store = MemoryBlobStore()
    assert isinstance(blob_store, sceneio.BlobStore)
    digest, size = blob_store.put_stream(stdlib_io.BytesIO(b"contract"))
    assert size == 8
    assert blob_store.exists(digest)
    assert blob_store.open(digest).read() == b"contract"
    assert blob_store.local_path(digest).read_bytes() == b"contract"
    assert asyncio.run(collect_chunks(blob_store, digest)) == b"contract"
    blob_store.delete(digest)
    assert not blob_store.exists(digest)

    class ImageSourceFixture:
        kind = "fixture"

        def fingerprint(self) -> dict:
            return {"kind": self.kind, "images": ("frame.png",)}

        def materialize(self, into: Path) -> list[sceneio.MaterializedImage]:
            return [sceneio.MaterializedImage("frame.png", into / "frame.png")]

    source = ImageSourceFixture()
    assert source.fingerprint() == {"kind": "fixture", "images": ("frame.png",)}
    assert source.materialize(tmp_path) == [
        sceneio.MaterializedImage("frame.png", tmp_path / "frame.png")
    ]


def test_error_contracts_match_hierarchy() -> None:
    errors = {
        path: contract
        for path, contract in PUBLIC_TYPE_CONTRACTS.items()
        if contract.kind == "error"
    }
    assert len(errors) == 5
    for path, contract in errors.items():
        error_type = _resolve(path)
        parent_relation = next(
            relation for relation in contract.relations if relation.kind == "parent_error"
        )
        parent = _resolve(parent_relation.target)
        assert inspect.isclass(error_type)
        assert issubclass(error_type, parent)
        assert error_type.__bases__[0] is parent
        retry_rules = tuple(rule for rule in contract.rules if rule.startswith("Retry policy:"))
        assert retry_rules == (
            "Retry policy: operation_dependent."
            if path == "sceneio.SceneIoError"
            else "Retry policy: non_retryable.",
        )


def test_contract_metadata_types_self_classify() -> None:
    expected = {
        "sceneio.contracts.ContractMember",
        "sceneio.contracts.ContractEvidence",
        "sceneio.contracts.ContractRelation",
        "sceneio.contracts.PublicTypeContract",
        "sceneio.contracts.CodecPayloadKind",
    }
    assert {
        path for path in PUBLIC_TYPE_CONTRACTS if path.startswith("sceneio.contracts.")
    } == expected
    for path in expected:
        contract = PUBLIC_TYPE_CONTRACTS[path]
        assert contract.kind == "descriptor"
        assert public_type_contract(_resolve(path)) is contract


def test_vocabulary_contracts_preserve_exact_runtime_values() -> None:
    camera_contract = public_type_contract(sceneio.data.CameraModel)
    assert camera_contract.kind == "vocabulary"
    assert tuple(
        (member.name, ast.literal_eval(member.default)) for member in camera_contract.members
    ) == tuple((member.name, member.value) for member in sceneio.data.CameraModel)

    assert tuple(item.type_id for item in CORE_DATA_TYPES) == tuple(
        SNAPSHOT["logical_data_types"]["ids"]
    )
    assert len(CORE_DATA_TYPES) == 8
    assert public_type_contract(sceneio.formats.DataType).kind == "vocabulary"
    assert public_type_contract(sceneio.formats.FormatSpec).kind == "vocabulary"


def test_lookup_canonical_alias_class_instance_and_short_name_rules() -> None:
    contract = PUBLIC_TYPE_CONTRACTS["sceneio.Point3DRecord"]
    value = sceneio.Point3DRecord(7, (1.0, 2.0, 3.0), (4, 5, 6), 0)
    assert sceneio.public_type_contract is public_type_contract
    assert sceneio.PUBLIC_TYPE_CONTRACTS is PUBLIC_TYPE_CONTRACTS
    assert public_type_contract("sceneio.Point3DRecord") is contract
    assert public_type_contract("sceneio.points_binary.Point3DRecord") is contract
    assert public_type_contract("Point3DRecord") is contract
    assert public_type_contract(sceneio.Point3DRecord) is contract
    assert public_type_contract(value) is contract
    assert PUBLIC_TYPE_ALIASES["sceneio.io.Image"] == "sceneio.Image"
    _validate_runtime_identities()

    wrong_alias = dataclasses.replace(
        contract,
        aliases=("sceneio.Camera",),
    )
    with pytest.raises(ValueError, match="does not resolve to canonical identity"):
        _validate_runtime_identities((wrong_alias,))

    with pytest.raises(ValueError, match=r"ambiguous.*sceneio\.DepthMap") as exc_info:
        public_type_contract("DepthMap")
    assert "sceneio.data.DepthMap" in str(exc_info.value)
    with pytest.raises(KeyError, match="unknown public type contract"):
        public_type_contract("NotAPublicType")
    with pytest.raises(KeyError, match="unknown public type contract path"):
        public_type_contract("sceneio.NotAPublicType")
    with pytest.raises(TypeError, match="has no SceneIO public type contract"):
        public_type_contract(object())


def test_model_and_registry_reject_malformed_contracts() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        ContractMember(
            name="value",
            kind="field",
            type_expression="str",
            presence="required",
            mutability="immutable",
            semantics="",
        )
    with pytest.raises(ValueError, match="repository-relative"):
        ContractEvidence(path="/absolute/path", claims=("construction",))
    with pytest.raises(ValueError, match="lower_snake_case"):
        ContractEvidence(
            path="tests/test_public_type_contracts.py",
            claims=("Not-Snake",),
        )
    with pytest.raises(ValueError, match="must start with"):
        ContractEvidence(
            path="tests/test_public_type_contracts.py",
            node_id="tests/other.py::test_other",
            claims=("construction",),
        )
    with pytest.raises(ValueError, match="unknown contract relation kind"):
        ContractRelation(kind="unknown", target="sceneio.Value")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="public sceneio path"):
        dataclasses.replace(
            _minimal_descriptor("sceneio.ValidFixture"),
            canonical_path="sceneio._private.Value",
        )
    with pytest.raises(ValueError, match="require a traits, options, or result"):
        dataclasses.replace(
            _minimal_descriptor("sceneio.ProcedureFixture"),
            kind="procedure_value",
        )

    first = _minimal_descriptor("sceneio.ContractFixtureA", aliases=("sceneio.Shared",))
    second = _minimal_descriptor("sceneio.ContractFixtureB", aliases=("sceneio.Shared",))
    with pytest.raises(ValueError, match="resolves to both"):
        _build_path_index((first, second))
    duplicate = dataclasses.replace(first, aliases=())
    with pytest.raises(ValueError, match="duplicate canonical"):
        _build_path_index((duplicate, duplicate))

    invalid_relation = _minimal_descriptor(
        "sceneio.ContractFixture",
        relations=(ContractRelation("contains", "sceneio.UnknownTarget"),),
    )
    indexes = _build_path_index((invalid_relation,))
    with pytest.raises(ValueError, match="unknown contains relation target"):
        _validate_catalog((invalid_relation,), indexes[2])

    representation = PUBLIC_TYPE_CONTRACTS["sceneio.Camera"]
    mismatched = dataclasses.replace(
        representation,
        specialized_contract_key="sceneio.WrongCamera",
    )
    indexes = _build_path_index((mismatched,))
    with pytest.raises(ValueError, match="specialized contract key differs"):
        _validate_catalog((mismatched,), indexes[2])


def test_contract_models_and_public_mappings_are_immutable() -> None:
    member = PUBLIC_TYPE_CONTRACTS["sceneio.Point3DRecord"].members[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        member.name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        PUBLIC_TYPE_CONTRACTS["sceneio.Changed"] = member  # type: ignore[index]
    with pytest.raises(TypeError):
        BUILTIN_CODEC_PAYLOAD_KINDS["changed"] = object()  # type: ignore[index]


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("sceneio.Camera", "sceneio.data.CameraIntrinsics"),
        ("sceneio.FeatureSet", "sceneio.data.FeatureSet"),
        ("sceneio.MatchGraph", "sceneio.data.CorrespondenceGraph"),
        ("sceneio.DepthMap", "sceneio.data.DepthMap"),
        ("sceneio.PosedViewSet", "sceneio.data.PosedViewSet"),
    ],
)
def test_native_and_neutral_roles_declare_bidirectional_adapters(source: str, target: str) -> None:
    assert ContractRelation("adapts_to", target) in PUBLIC_TYPE_CONTRACTS[source].relations
    assert ContractRelation("adapts_to", source) in PUBLIC_TYPE_CONTRACTS[target].relations


def test_every_evidence_path_and_exact_node_exists() -> None:
    parsed: dict[Path, ast.Module] = {}
    for contract in PUBLIC_TYPE_CONTRACTS.values():
        for evidence in contract.evidence:
            path = ROOT / evidence.path
            assert path.is_file(), (contract.canonical_path, evidence.path)
            if evidence.node_id is None:
                continue
            tree = parsed.setdefault(
                path,
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
            )
            node_parts = evidence.node_id.split("::")[1:]
            current: ast.AST = tree
            for raw_name in node_parts:
                name = raw_name.partition("[")[0]
                body = getattr(current, "body", ())
                current = next(
                    (
                        child
                        for child in body
                        if isinstance(
                            child,
                            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and child.name == name
                    ),
                    None,
                )
                assert current is not None, evidence.node_id


def test_payload_catalog_exactly_covers_builtin_registry() -> None:
    payload_ids = tuple(BUILTIN_CODEC_PAYLOAD_KINDS)
    assert payload_ids == tuple(SNAPSHOT["payloads"]["ids"])
    assert len(payload_ids) == SNAPSHOT["payload_kind_count"] == 26
    definitions = io_registry.BUILTIN_DEFINITIONS
    assert tuple(codec.id for codec in definitions) == CANONICAL_BUILTIN_IDS
    assert len(definitions) == SNAPSHOT["builtin_format_count"] == 74
    declared_formats = tuple(
        format_id
        for payload in BUILTIN_CODEC_PAYLOAD_KINDS.values()
        for format_id in payload.format_ids
    )
    assert declared_formats == tuple(SNAPSHOT["payloads"]["format_ids"])
    assert set(declared_formats) == set(CANONICAL_BUILTIN_IDS)

    for payload_id, payload in BUILTIN_CODEC_PAYLOAD_KINDS.items():
        assert (
            tuple(codec.id for codec in definitions if codec.datatype == payload_id)
            == payload.format_ids
        )
        for public_path in payload.public_types:
            assert public_path in PUBLIC_TYPE_CONTRACTS
        if payload.logical_data_type_id is not None:
            assert payload.logical_data_type_id in SNAPSHOT["logical_data_types"]["ids"]
        assert payload.evidence == (
            "tests/test_public_type_contracts.py::"
            "test_payload_catalog_exactly_covers_builtin_registry",
        )

    for codec in definitions:
        payload = BUILTIN_CODEC_PAYLOAD_KINDS[codec.datatype]
        assert codec.payload_kind == codec.datatype
        assert codec.capabilities().payload_kind == codec.datatype
        if codec.record is None:
            assert payload.dynamic_output
        else:
            assert public_type_contract(codec.record).canonical_path in payload.public_types
    assert {codec.id for codec in definitions if codec.record is None} == {
        "pfm",
        "flo",
        "tiff",
        "npy",
    }
    assert {
        payload.id for payload in BUILTIN_CODEC_PAYLOAD_KINDS.values() if payload.dynamic_output
    } == {"depth_map", "flow", "image_or_mask_or_stack", "tensor"}


def test_payload_kind_alias_does_not_change_dataclass_compatibility_shape() -> None:
    codec = io_registry.BUILTIN_DEFINITIONS[0]
    capabilities = codec.capabilities()
    assert "payload_kind" not in {field.name for field in dataclasses.fields(codec)}
    assert "payload_kind" not in {field.name for field in dataclasses.fields(capabilities)}
    assert "payload_kind=" not in repr(codec)
    assert "payload_kind=" not in repr(capabilities)


def test_builtin_payload_validation_is_closed_but_runtime_extensions_remain_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = dataclasses.replace(
        io_registry.BUILTIN_DEFINITIONS[0],
        datatype="vendor.external_payload",
    )
    invalid_definitions = (invalid, *io_registry.BUILTIN_DEFINITIONS[1:])
    with pytest.raises(ValueError, match="undeclared payload kind"):
        _validate_payload_contracts(invalid_definitions)

    depth_payload = BUILTIN_CODEC_PAYLOAD_KINDS["depth_map"]
    without_dynamic_rule = dataclasses.replace(
        depth_payload,
        dynamic_output_rule=None,
    )
    patched_payloads = MappingProxyType(
        {
            **BUILTIN_CODEC_PAYLOAD_KINDS,
            "depth_map": without_dynamic_rule,
        }
    )
    monkeypatch.setattr(
        payload_module,
        "BUILTIN_CODEC_PAYLOAD_KINDS",
        patched_payloads,
    )
    with pytest.raises(ValueError, match="no record type or dynamic output rule"):
        _validate_payload_contracts(io_registry.BUILTIN_DEFINITIONS)

    duplicated_format = dataclasses.replace(
        depth_payload,
        format_ids=(*depth_payload.format_ids, "png"),
    )
    monkeypatch.setattr(
        payload_module,
        "BUILTIN_CODEC_PAYLOAD_KINDS",
        MappingProxyType(
            {
                **BUILTIN_CODEC_PAYLOAD_KINDS,
                "depth_map": duplicated_format,
            }
        ),
    )
    with pytest.raises(ValueError, match="assigned to multiple payload kinds"):
        _validate_payload_contracts(io_registry.BUILTIN_DEFINITIONS)

    extension = io_registry.Codec(
        id="test_external_payload_contract",
        extensions=(".external-contract",),
        read=lambda path: path,
        write=None,
        record=None,
        datatype="vendor.external_payload",
    )
    try:
        assert io_registry.register(extension) is extension
        assert io_registry.REGISTRY[extension.id] is extension
        assert extension.payload_kind == "vendor.external_payload"
    finally:
        io_registry.REGISTRY.pop(extension.id, None)


def test_catalog_serialization_is_detached_plain_and_process_deterministic() -> None:
    payload = catalog_dict()
    assert payload["contract_schema_version"] == 1
    assert len(payload["contracts"]) == 144
    assert len(payload["builtin_codec_payload_kinds"]) == 26

    def visit(value: object) -> None:
        assert not inspect.isclass(value)
        assert not callable(value)
        if isinstance(value, dict):
            assert all(isinstance(key, str) for key in value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        else:
            assert value is None or isinstance(value, str | int | float | bool)

    visit(payload)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(encoded) == SNAPSHOT["catalog_json_bytes"]
    assert hashlib.sha256(encoded).hexdigest() == SNAPSHOT["catalog_json_sha256"]
    assert str(ROOT).encode() not in encoded
    assert b"0x" not in encoded

    payload["contracts"][0]["canonical_path"] = "changed"
    assert catalog_dict()["contracts"][0]["canonical_path"] != "changed"

    code = (
        "import hashlib,json; from sceneio.contracts import catalog_dict; "
        "data=json.dumps(catalog_dict(),ensure_ascii=False,allow_nan=False,"
        "separators=(',',':')).encode(); print(hashlib.sha256(data).hexdigest())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == hashlib.sha256(encoded).hexdigest()


def test_contract_namespace_import_is_lazy_stdlib_only_and_provider_free() -> None:
    code = """
import sys
import sceneio
assert 'sceneio.contracts' not in sys.modules
assert 'numpy' not in sys.modules
contracts = sceneio.contracts
assert contracts.PUBLIC_TYPE_CONTRACTS
for forbidden in (
    'numpy',
    'sceneio._core',
    'sceneio.io',
    'sceneio.data',
    'sceneio.mapping',
    'sceneio.matching',
    'h5py',
    'zarr',
    'tifffile',
    'pyarrow',
):
    assert forbidden not in sys.modules, forbidden
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
