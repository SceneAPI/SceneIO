"""Contracts for the modular native build and source ownership."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import MappingProxyType

import pytest

from sceneio import _core
from sceneio.io import registry
from sceneio.io._builtin_manifest import (
    BUILTIN_OWNERSHIP,
    CANONICAL_BUILTIN_IDS,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests/contracts/native_build_v1.json").read_text(encoding="utf-8")
)
NATIVE_INVENTORY_CONTRACT = json.loads(
    (ROOT / "tests/contracts/native_inventory_v1.json").read_text(
        encoding="utf-8"
    )
)
SOURCES = (ROOT / "cmake/SceneIOSources.cmake").read_text(encoding="utf-8")


def _normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _cmake_source_set(name: str) -> tuple[str, ...]:
    match = re.search(rf"set\({re.escape(name)}\s+(.*?)\)", SOURCES, re.DOTALL)
    assert match is not None, name
    return tuple(re.findall(r"src/cpp/[^\s)]+", match.group(1)))


def _basenames(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(Path(path).name for path in paths)


def test_root_cmake_is_only_the_ordered_build_assembly() -> None:
    root_cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    for relative_path, expected_hash in CONTRACT["cmake_file_sha256"].items():
        assert _normalized_sha256(ROOT / relative_path) == expected_hash

    includes = re.findall(r"^include\((cmake/[^)]+)\)$", root_cmake, re.MULTILINE)
    assert includes == CONTRACT["cmake_modules"]
    assert "project(sceneio_core LANGUAGES C CXX)" in root_cmake
    assert "set(CMAKE_CXX_STANDARD 17)" in root_cmake
    assert not re.search(
        r"\b(?:FetchContent_Declare|add_library|nanobind_add_module|"
        r"target_link_libraries)\s*\(",
        root_cmake,
    )


def test_codec_family_manifests_partition_native_sources() -> None:
    variable_by_family = {
        "arrays": "SCENEIO_ARRAY_CODEC_SOURCES",
        "calibration": "SCENEIO_CALIBRATION_CODEC_SOURCES",
        "dense": "SCENEIO_DENSE_CODEC_SOURCES",
        "images": "SCENEIO_IMAGE_CODEC_SOURCES",
        "meshes": "SCENEIO_MESH_CODEC_SOURCES",
        "points": "SCENEIO_POINT_CODEC_SOURCES",
        "reconstruction": "SCENEIO_RECONSTRUCTION_CODEC_SOURCES",
        "sequences": "SCENEIO_SEQUENCE_CODEC_SOURCES",
        "splats": "SCENEIO_SPLAT_CODEC_SOURCES",
    }
    owned_paths = []
    for family, variable in variable_by_family.items():
        paths = _cmake_source_set(variable)
        assert paths == tuple(CONTRACT["codec_source_owners"][family])
        owned_paths.extend(paths)

    discovered = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/cpp/codecs").rglob("*.cpp")
    }
    assert len(owned_paths) == len(set(owned_paths))
    assert set(owned_paths) == discovered
    assert (
        "_sceneio_assert_unique_sources(\n"
        '  "SCENEIO_CODEC_SOURCES" ${SCENEIO_CODEC_SOURCES})'
    ) in SOURCES
    assert "SCENEIO_CODEC_SOURCES must own every codec source exactly once" in SOURCES


def test_record_and_link_manifests_match_the_frozen_native_layout() -> None:
    binding_paths = _cmake_source_set("SCENEIO_BINDING_SOURCES")
    discovered_bindings = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/cpp/bindings").glob("*.cpp")
    }
    assert _basenames(binding_paths) == tuple(CONTRACT["binding_sources"])
    assert set(binding_paths) == discovered_bindings

    record_paths = _cmake_source_set("SCENEIO_RECORD_SOURCES")
    discovered_records = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/cpp/records").rglob("*.cpp")
    }
    assert _basenames(record_paths) == tuple(CONTRACT["record_sources"])
    assert set(record_paths) == discovered_records

    core_paths = _cmake_source_set("SCENEIO_CORE_SOURCES")
    assert core_paths == tuple(CONTRACT["core_link_order"])
    assert len(core_paths) == len(set(core_paths))
    assert all((ROOT / path).is_file() for path in core_paths)


def test_registration_tables_preserve_order_and_single_ownership() -> None:
    binding_root = ROOT / "src/cpp/bindings"
    record_source = (binding_root / "records.cpp").read_text(encoding="utf-8")
    family_sources = [
        binding_root / name for name in CONTRACT["binding_sources"][2:]
    ]
    family_text = "\n".join(
        path.read_text(encoding="utf-8") for path in family_sources
    )

    entry_pattern = re.compile(
        r'\{(\d+),\s*"[^"]+",\s*&::(register_\w+)\}'
    )
    record_entries = [
        (int(order), function)
        for order, function in entry_pattern.findall(record_source)
    ]
    codec_entries = [
        (int(order), function)
        for order, function in entry_pattern.findall(family_text)
    ]
    assert [order for order, _ in sorted(record_entries)] == list(range(17))
    assert tuple(function for _, function in sorted(record_entries)) == tuple(
        CONTRACT["record_registration_order"]
    )
    assert [order for order, _ in sorted(codec_entries)] == list(range(42))
    assert tuple(function for _, function in sorted(codec_entries)) == tuple(
        CONTRACT["codec_registration_order"]
    )

    declaration_pattern = re.compile(
        r"^void (register_\w+)\(nanobind::module_ &\);$", re.MULTILINE
    )
    codec_declarations = Counter(declaration_pattern.findall(family_text))
    record_declarations = Counter(declaration_pattern.findall(record_source))
    assert codec_declarations == Counter(
        {name: 1 for name in CONTRACT["codec_registration_order"]}
    )
    assert record_declarations == Counter(
        {name: 1 for name in CONTRACT["record_registration_order"]}
    )

    definition_pattern = re.compile(
        r"^void\s+(register_\w+)\s*"
        r"\((?:nb|nanobind)::module_\s*&\w+\)\s*\{",
        re.MULTILINE,
    )
    codec_definitions = Counter(
        function
        for path in (ROOT / "src/cpp/codecs").rglob("*.cpp")
        for function in definition_pattern.findall(
            path.read_text(encoding="utf-8")
        )
    )
    record_definitions = Counter(
        function
        for path in (ROOT / "src/cpp/records").glob("*.cpp")
        for function in definition_pattern.findall(
            path.read_text(encoding="utf-8")
        )
    )
    assert codec_definitions == codec_declarations
    assert record_definitions == record_declarations

    module = (ROOT / "src/cpp/module.cpp").read_text(encoding="utf-8")
    assert not re.search(r"^void register_\w+", module, re.MULTILINE)
    records_call = module.index("sio::bindings::register_records(m);")
    codecs_call = module.index("sio::bindings::register_codecs(m);")
    inventory_call = module.index("sio::bindings::codec_inventory(m)")
    assert records_call < codecs_call < inventory_call
    assert module.count("sio::bindings::register_records(m);") == 1
    assert module.count("sio::bindings::register_codecs(m);") == 1
    assert 'm.attr("__codec_inventory__")' in module


def test_live_native_inventory_matches_builtin_ownership_and_capabilities() -> None:
    inventory = _core.__codec_inventory__
    expected_ids = tuple(
        format_id
        for format_id in CANONICAL_BUILTIN_IDS
        if BUILTIN_OWNERSHIP[format_id].implementation_owner
        in {"native", "hybrid"}
    )
    assert isinstance(inventory, tuple)
    assert tuple(item["id"] for item in inventory) == expected_ids
    assert len(expected_ids) == 54

    schema = tuple(NATIVE_INVENTORY_CONTRACT["schema"])
    assert schema == ("id", "read", "write", "inspect", "partial")
    assert NATIVE_INVENTORY_CONTRACT["stream_contract"] == {
        "stream_read": "read",
        "stream_write": "write",
    }
    operation_contract = {
        row[0]: {
            name: tuple(value)
            for name, value in zip(schema[1:], row[1:], strict=True)
        }
        for row in NATIVE_INVENTORY_CONTRACT["entries"]
    }
    assert tuple(operation_contract) == expected_ids

    operation_keys = (
        "read",
        "write",
        "inspect",
        "stream_read",
        "stream_write",
        "partial",
    )
    for item in inventory:
        assert isinstance(item, MappingProxyType)
        assert set(item) == {"id", "family", *operation_keys}
        ownership = BUILTIN_OWNERSHIP[item["id"]]
        codec = registry.REGISTRY[item["id"]]
        capabilities = codec.capabilities()
        expected_operations = operation_contract[item["id"]]
        assert item["family"] == ownership.family
        for operation in schema[1:]:
            symbols = item[operation]
            assert isinstance(symbols, tuple)
            assert symbols == expected_operations[operation]
            assert len(symbols) == len(set(symbols))
            assert all(
                isinstance(symbol, str)
                and symbol
                and hasattr(_core, symbol)
                and callable(getattr(_core, symbol))
                for symbol in symbols
            )
        assert item["read"]
        assert item["write"]
        assert item["stream_read"] == expected_operations["read"]
        assert item["stream_write"] == expected_operations["write"]
        assert bool(item["stream_read"]) == capabilities.streams_read
        assert bool(item["stream_write"]) == capabilities.streams_write
        assert bool(item["partial"]) == bool(capabilities.partial_selectors)

        declared = set(ownership.native_symbols)
        inventoried = (
            set(item["read"])
            | set(item["write"])
            | set(item["inspect"])
            | set(item["partial"])
        )
        assert inventoried == declared

    with pytest.raises(TypeError):
        inventory[0]["id"] = "mutated"

    inventory_ids = set(expected_ids)
    for ownership in BUILTIN_OWNERSHIP.values():
        if ownership.implementation_owner == "python":
            assert ownership.id not in inventory_ids
        elif ownership.implementation_owner == "hybrid":
            assert ownership.id in inventory_ids
        if ownership.implementation_owner in {"python", "hybrid"}:
            for dotted in ownership.python_symbols:
                module_name, _, name = dotted.rpartition(".")
                assert callable(getattr(importlib.import_module(module_name), name))


def test_target_and_instrumentation_contracts_remain_explicit() -> None:
    dependencies = (
        ROOT / "cmake/SceneIODependencies.cmake"
    ).read_text(encoding="utf-8")
    assert re.search(
        r"find_package\(\s*Python 3\.12\s+REQUIRED COMPONENTS\s+"
        r"Interpreter\s+Development\.Module\s+"
        r"Development\.SABIModule\s*\)",
        dependencies,
    )
    assert "if(NOT TARGET Python::SABIModule)" in dependencies
    assert (
        "SceneIO's cp312 stable-ABI build requires Python::SABIModule"
        in dependencies
    )

    targets = (ROOT / "cmake/SceneIOTargets.cmake").read_text(encoding="utf-8")
    link_block = re.search(
        r"target_link_libraries\(\s*_core\s+PRIVATE\s+(.*?)\)",
        targets,
        re.DOTALL,
    )
    assert link_block is not None
    assert tuple(link_block.group(1).split()) == tuple(CONTRACT["core_link_targets"])
    assert "nanobind_add_module(_core STABLE_ABI NB_STATIC" in targets
    assert '"(^|;)nanobind-static-abi3(;|$)"' in targets
    assert (
        'if(NOT "${_sceneio_core_suffix}" STREQUAL "${NB_SUFFIX_S}")'
        in targets
    )
    assert "install(TARGETS _core LIBRARY DESTINATION sceneio)" in targets

    instrumentation = (
        ROOT / "cmake/SceneIOInstrumentation.cmake"
    ).read_text(encoding="utf-8")
    assert re.search(
        r"option\(\s*SCENEIO_ENABLE_SANITIZERS\s+"
        r'"[^"]+"\s+OFF\s*\)',
        instrumentation,
    )
    assert re.search(
        r"option\(\s*SCENEIO_BUILD_NATIVE_TEST_HOOKS\s+"
        r'"[^"]+"\s+OFF\s*\)',
        instrumentation,
    )


def test_live_core_uses_the_platform_stable_abi_suffix() -> None:
    expected_name = "_core.pyd" if sys.platform == "win32" else "_core.abi3.so"
    assert Path(_core.__file__).name == expected_name
